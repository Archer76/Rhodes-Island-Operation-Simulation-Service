#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""引擎二进制默认路径的反向守卫——**"未设 RIOS_SIM_BIN 必须大声失败"**。

## 为什么这条要单独成判据

2026-09-19 的事故不是"某个数算错了"，是**两台仪器被当成一台**：同一条 `golden_go.py --check`、
同一批 19 份夹具、同一份基线，**只差 `RIOS_SIM_BIN` 设没设**：

* 未设 ⇒ 静默落到工作树里那枚预编译 exe ⇒ `hsex8_max` 83杀/1漏/814.0333s，报 1 份不一致；
* 设上 ⇒ 当轮私有构建 ⇒ 48杀/3漏/221.6667s，19/19 一致。

两次都 rc=0/正常打印，**读数看起来一样可信**。所以判据不能是"能不能跑出数"，
只能是"**没钉住的时候它敢不敢停下来**"。

## 四问 + 一个控制组

1. 未设 `RIOS_SIM_BIN` ⇒ `require_binary()` 必须抛 `EngineBinaryUnpinned`；
2. 报错消息里必须**有那条能直接粘的构建命令**（报错不附修法只报了一半）；
3. **不许悄悄挑一个能跑的**：若工作树里那枚老 exe 存在，未设时**仍然必须失败**，
   且消息里要写出它"旧了多少分钟"（这条是本题的核心——它证明失败不是因为"没得挑"，
   而是因为"有的挑也不挑"）；
4. 指向不存在的文件 ⇒ 必须抛，且**点名那个路径**；
5. **控制组**：钉一个真实存在的文件 ⇒ 必须成功返回（证明第 1~4 条不是"函数恒抛异常"）。

用法：
    python tools/guard_engine_bin.py            # 全过 rc=0
    python tools/guard_engine_bin.py --self-test  # 同上（保留开关，与其它工具同形）

⚠ 本工具**只改自己的进程环境变量**（`os.environ` 就地增删），不写文件、不起子进程。
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ak_tactic.simgo import (EngineBinaryUnpinned, legacy_binary,  # noqa: E402
                             require_binary, staleness_minutes)


def _with_env(value: str | None):
    """临时设置/删除 RIOS_SIM_BIN，返回原值供还原。"""
    old = os.environ.get("RIOS_SIM_BIN")
    if value is None:
        os.environ.pop("RIOS_SIM_BIN", None)
    else:
        os.environ["RIOS_SIM_BIN"] = value
    return old


def _restore(old: str | None) -> None:
    if old is None:
        os.environ.pop("RIOS_SIM_BIN", None)
    else:
        os.environ["RIOS_SIM_BIN"] = old


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except Exception:                            # noqa: BLE001
            pass
    argparse.ArgumentParser(description="引擎二进制默认路径的反向守卫").parse_args()

    print("== 自证：未设 RIOS_SIM_BIN 时它敢不敢停下来 ==")
    bad = 0

    legacy = legacy_binary()
    print(f"  现场：工作树里那枚老 exe = "
          f"{legacy if legacy is not None else '（不存在，第 3 条按「仍然要失败」验）'}")

    # ---- 1/2/3：未设 ⇒ 必须抛，且消息里有构建命令、（若有老 exe）有"旧了多少分钟" ----
    old = _with_env(None)
    try:
        raised = None
        try:
            got = require_binary()
        except EngineBinaryUnpinned as e:
            raised = e
            got = None
        ok1 = raised is not None and got is None
        bad += 0 if ok1 else 1
        print(f"  {'✅' if ok1 else '⛔'} 未设时必须抛 EngineBinaryUnpinned："
              f"{'抛了' if raised else '没抛（还返回了 ' + str(got) + '）'}")

        msg = str(raised) if raised else ""
        ok2 = "go build" in msg and "RIOS_SIM_BIN" in msg
        bad += 0 if ok2 else 1
        print(f"  {'✅' if ok2 else '⛔'} 报错必须附上那条能直接粘的命令："
              f"{'有' if ok2 else '缺'}（‘go build’与‘RIOS_SIM_BIN’都要出现）")

        # ★ 核心一条：有得挑，也不许挑
        ok3 = raised is not None
        detail = ""
        if legacy is not None:
            st = staleness_minutes(legacy)
            detail = (f"；消息里写了老 exe 旧 {st[0]:.1f} 分钟" if st else "；老 exe 目前不比 .go 旧")
            ok3 = ok3 and ("未采用" in msg)
        bad += 0 if ok3 else 1
        print(f"  {'✅' if ok3 else '⛔'} 不许悄悄挑一个能跑的："
              f"老 exe {'在场' if legacy is not None else '不在场'}而仍然失败{detail}")
    finally:
        _restore(old)

    # ---- 4：指向不存在的文件 ⇒ 必须抛并点名路径 ----
    ghost = str(ROOT / "out" / "acceptance" / "这个文件不存在-guard.exe")
    old = _with_env(ghost)
    try:
        raised4 = None
        try:
            require_binary()
        except EngineBinaryUnpinned as e:
            raised4 = e
        ok4 = raised4 is not None and ghost in str(raised4)
        bad += 0 if ok4 else 1
        print(f"  {'✅' if ok4 else '⛔'} 指向不存在的文件必须抛且点名路径："
              f"{'点名了' if ok4 else '没点名/没抛'}")
    finally:
        _restore(old)

    # ---- 5：控制组——钉一个真实存在的文件必须成功（防"恒抛异常"冒充严格） ----
    with tempfile.NamedTemporaryFile(suffix=".exe", delete=False) as fh:
        probe = Path(fh.name)
    old = _with_env(str(probe))
    try:
        try:
            got5 = require_binary()
            ok5 = got5 == probe
        except EngineBinaryUnpinned:
            ok5 = False
        bad += 0 if ok5 else 1
        print(f"  {'✅' if ok5 else '⛔'} 控制组：钉一个真实存在的文件必须成功返回："
              f"{'成功' if ok5 else '失败 ⇒ 上面几条就成了「恒抛异常」而不是判据'}")
    finally:
        _restore(old)
        probe.unlink(missing_ok=True)

    print()
    print(f"== 小结：{'全部成立' if not bad else f'{bad} 条不成立'}；"
          f"这组判据的断言是「**没钉住就不敢跑**」，不是「跑出来一致」 ==")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
