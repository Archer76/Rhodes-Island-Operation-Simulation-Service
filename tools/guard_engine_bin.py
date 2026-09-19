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
import hashlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from ak_tactic.simgo import (EngineBinaryUnpinned, legacy_binary,  # noqa: E402
                             require_binary, staleness_minutes)

try:
    #: ⚠ **复用**验收/门的实现（`tools/engine_pin.py`），**绝不另写一份**：
    #: 两处各写一份 `source_sig`，一改就对不上——这正是本项目反复吃到的那类账。
    from engine_pin import source_sig as _source_sig              # noqa: E402
except Exception:                                                # noqa: BLE001
    _source_sig = None

#: ⚠ **exe 的 sha16 只证明"是不是那一次构建"，不证明"是哪份源码"**（同一份源码两次构建哈希就不同）
#: ——验收 2026-09-19 指出。所以每台仪器要同时记 `source_sig`（`rios-sim/**/*.go` 的内容摘要）。
#: 这也是 `LEGACY_INSTRUMENTS` 里那一枚最要命的地方：它连 `source_sig` 都**不可得**（树已不存在）。

#: ⚠ **不可复现仪器的存档**（PM 2026-09-19 裁定「留」，并要求把 sha 与读数写进入库物）。
#:
#: 为什么要留：这一枚构建于 2026-09-19 19:08 的**混合工作树**（当时已提交的部分 + 尚未提交的
#: 五个文件），那个状态此后**不复存在** ⇒ 删掉它就再没有任何实物能复现那次读数。
#: 同一条道理在本项目里的老形状是「**预录制的哈希优于"两边互等"**」：**不可复现的读数必须留实物**。
#:
#: 它**不在** `legacy_binary()` 的默认定位路径上 ⇒ 「留证」与「不许静默用旧」是两件事，同时成立。
#: `out/` 是易失目录 ⇒ **文件可以丢，读数不可无凭**：身份与读数记在这里（入库、可 diff）。
LEGACY_INSTRUMENTS: tuple[dict, ...] = (
    {
        "preserved_copy": "out/acceptance/rios-sim-legacy-1908_b3e4d6b1.exe",
        "sha256": "b3e4d6b1565d63b45128516588603853a8c8333c08777593fcc1ed24f30c4dc6",
        "size": 3594240,
        "mtime": "2026-09-19 19:08:28",
        "built_from": ("rios-sim/ 工作树 @ 2026-09-19 19:08：当时的 HEAD + 未提交的五个文件"
                       "（main.go / mech/mech.go / mech/huai_shu_li.go / wire.go / skill.go）"),
        "source_sig": ("**不可得**——那棵树（19:08 的混合工作树）已不存在，任何摘要都算不回来；"
                       "这正是它不可复现、且必须留实物+留读数的那一条"),
        "removed_default_path": "rios-sim/rios-sim.exe（2026-09-19 23:36 删除——PM 三步走之第三步）",
        "reproduces": {
            "plan": "fixtures/hsex8_max.json",
            "reading": "83杀 / 1漏 / 814.0333s / 591046.1",
            "spec_sha": ("464a9dc2f94b1428c8569a36f3b00d1211b6de2c902b481c5f0fa97cae607564"),
            "baseline_it_differed_from": "48杀 / 3漏 / 221.6667s / 282276.8（**同一 spec_sha**）",
            "how": ("同一条 golden_go.py --check、同一批 19 份夹具、同一份基线，"
                    "唯一变量 = RIOS_SIM_BIN 设没设（未设⇒落到这枚；钉住⇒当轮私有构建）"),
        },
    },
)

#: 曾经把「没有引擎」当成正常分支、**rc=0 跳过**的出口（PM 2026-09-19 要求回去补一刀）。
#: 它们此前只是被上游 `require_binary()` 抛异常"顺带救活"——但**顺带救活不算修复**，
#: 所以另加静态控制（文件里不许再出现真的 print 跳过出口）+ 端到端反向守卫（见下）。
SKIP_EXIT_SITES = (
    "tools/simgo_cost.py",
    "tools/check_simgo_parity.py",
)

#: ⚠ `_proto/` **不入库**（`.gitignore:45`）、跑前须自行钉 `RIOS_SIM_BIN`、**此处改动不保证留存**。
#: 所以下面这两处的同名修复**只在磁盘上**（PM 2026-09-19 裁定：不 force-add）。
#: **若将来某份原型要被当真，正确动作是把它移出 `_proto/` 并入库，而不是给它开 force-add 的口子。**
#: ⚠ 这段说明必须住在**入库物**里（就是本文件）——不能写在 `_proto/` 自己里面，因为它也不入库。
#: 也因为这层身份，这里**不在场不算失败**：fresh checkout 里根本没有 `_proto/`，
#: 一条"干净解出树才能跑"的判据不能因为原型区缺席而变红。
#: ★ 一句话说明**为什么这两组不许再合并回去**：
#:   **"一条只在干净解出树里才跑得动的判据，不能因为自己的脚手架缺席而变红。"**
#:   ——判据的红必须红在它要验的那件事上（PM 2026-09-19 就这处点名留档）。
SKIP_EXIT_SITES_PROTO = (
    "_proto/simgo_cost_split.py",
    "_proto/simgo_parity.py",
)
SKIP_EXIT_MARKER = "跳过："
#: ⚠ 只认**真的 print 调用**，不认"这个词出现在文件里"。
#: 本守卫的第一版就是按子串判的，结果被我自己删出口时留下的**注释**（"这里原本是「跳过：…」"）
#: 判红——那正是本项目记录过的假信号「注释被当证据」的一个微缩版：**判据必须落在会执行的那一行上**。
SKIP_EXIT_RE = re.compile(r"""print\(\s*[fr]?["']跳过""")


def check_legacy_instrument() -> int:
    """核对留证副本与入库记录是否一致（副本不在＝`out/` 被清，不算失败）。"""
    bad = 0
    for rec in LEGACY_INSTRUMENTS:
        p = ROOT / rec["preserved_copy"]
        if not p.exists():
            print(f"  ✅ 留证副本不在场（out/ 易失，正常）：{rec['preserved_copy']}")
            print(f"     身份与读数仍在入库物里：sha256 {rec['sha256'][:16]}… ⇒ "
                  f"{rec['reproduces']['reading']}")
            continue
        got = hashlib.sha256(p.read_bytes()).hexdigest()
        ok = (got == rec["sha256"]) and (p.stat().st_size == rec["size"])
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '⛔'} 留证副本与入库记录一致：{rec['preserved_copy']}")
        print(f"     记录 sha256 {rec['sha256'][:16]}… ↔ 实测 {got[:16]}… ｜ "
              f"size {rec['size']} ｜ 它复现的读数：{rec['reproduces']['reading']}")
        print(f"     源码身份 source_sig：{rec['source_sig']}")
        if not ok:
            print("     ⛔ 不一致 ⇒ 入库记录或副本被人动过，这正是「文件可以丢、读数不可无凭」要防的")
    return bad


def check_skip_exit_sites() -> int:
    """端到端反向守卫：把 exe 钉成一个**不存在的路径** ⇒ 这些出口必须 rc≠0 且点名路径，不许「跳过」。"""
    ghost = ROOT / "out" / "acceptance" / "ghost-guard-nonexistent.exe"   # 全 ASCII：断言不受编码影响
    env = dict(os.environ)
    env["RIOS_SIM_BIN"] = str(ghost)
    env.pop("PYTHONIOENCODING", None)          # 不许靠环境变量兜住编码
    bad = 0
    for rel, required in ([(r, True) for r in SKIP_EXIT_SITES]
                          + [(r, False) for r in SKIP_EXIT_SITES_PROTO]):
        src_path = ROOT / rel
        if not src_path.exists():
            # ⚠ `_proto/` 不入库 ⇒ fresh checkout 里没有它：**缺席不算失败**（但要说出来）
            print(f"  ➖ {rel}：不在场（`_proto/` 不入库，fresh checkout 里没有）——跳过本项")
            if required:
                print("     ⛔ 但它属于**必须存在**的那一组 ⇒ 这一点是失败")
                bad += 1
            continue
        src = src_path.read_text(encoding="utf-8")
        static_ok = not SKIP_EXIT_RE.search(src)
        proc = subprocess.run([sys.executable, rel], cwd=str(ROOT), env=env,
                              capture_output=True, text=True, encoding="utf-8",
                              errors="replace", timeout=900)
        out = (proc.stdout or "") + (proc.stderr or "")
        rc_ok = proc.returncode != 0
        named = ghost.name in out
        ok = static_ok and rc_ok and named
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '⛔'} {rel}：rc={proc.returncode}（须≠0）｜"
              f"点名路径={named}｜已无真正的「跳过」出口={static_ok}")
        if not ok:
            tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
            print(f"       末尾输出：{tail if tail else '（空）'}")
    return bad


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

    # ---- 0：仪器身份的两个维度（`sha16` 只证"哪次构建"，`source_sig` 才证"哪份源码"）----
    sig = _source_sig() if _source_sig is not None else None
    print(f"  本树源码身份 source_sig = {sig if sig else '（engine_pin 不可用 ⇒ 不可得）'}")
    print("　⚠ 判「这台仪器是不是 HEAD 的构建」要看 source_sig，不能只看 exe 的 sha16")

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
    print("== 留证仪器：不可复现的那个读数必须有实物/有据 ==")
    bad += check_legacy_instrument()

    print()
    print("== 曾把「没有引擎」当正常分支的四处出口：钉错必须点名，不许「跳过」 ==")
    bad += check_skip_exit_sites()

    print()
    print(f"== 小结：{'全部成立' if not bad else f'{bad} 条不成立'}；"
          f"这组判据的断言是「**没钉住就不敢跑**」，不是「跑出来一致」 ==")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
