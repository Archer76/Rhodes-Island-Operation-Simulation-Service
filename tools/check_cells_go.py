#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：规格里的两张格表（防守点格 ＋ 高台格）。

## 对的是什么

`ak_tactic/simgo/spec.py:414-436` 的 `_find_goals` 与 `:1082-1103` 的
`_highland_cells`。两者都只读关卡地图，是 `build_spec` 19 个顶层键里
`goal_cells` / `highland_cells` 的算法本体。

## 两个函数长得像但不一样

* `_find_goals` 按 `range(height) × range(width)` 走、每格先问 `inside()`，
  返回 **set**，调用处 `sorted(...)` ⇒ 输出按 **(x, y) 字典序**；
* `_highland_cells` 直接遍历 `m.tiles`、**不问** `inside()`，返回**行序**。

原版给后者写明「地图的行列长度与这两个数并不总是一致」，按宽高取会静默
吃掉真的高台格（实测后果：一份作业伤害 23260 → 22656，判决从守住变漏怪）。
Go 那边 `parseMap` 强制 `len(Tiles)==Height` 且每行宽 `==Width`，不一致就报错
——所以形状这个坑不存在，但**顺序仍然要各自照原样**。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `_find_goals` / `_highland_cells`，
  **现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/格表.json`，**不 import `ak_tactic`**。

★ 冻的**两半 ＋ 输入身份**：查询集是调用方按**缓存**现算的关卡清单（会随别的
会话逐章取数而长大），所以键是 `("cells", 关卡 id, 该关缓存文件内容 sha16)`，
并先做 `G.coverage("cells", …)` 对账；一关一条键（原版对 `load_stage` 抛错的关
是**整关跳过**的，按两表拆键会让冻结档问到没有期望值的问题）。另记一条可读的
批次记录 `("query", "level_batch")`——它**不参与判定**，但 `--check` 的「改值」栏
会量到它：缓存一变，这里第一个显形。

⚠ `highland_cells` 的比较是**逐位、按原样**（它是行序、`goal_cells` 是字典序）。

用法:
    python tools\\check_cells_go.py
    python tools\\check_cells_go.py --mutate
    python tools\\freeze_baseline.py --record 格表
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"


def go_cells(level: str) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "cells", "level": level}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        return False, resp.get("error") or ""
    return True, resp["cells"]


def py_cells_level(lv: str) -> dict:
    """一关的期望值：两张格表。

    ★ `ak_tactic` 的 import 住在函数体里：冻结档下本函数不会被调到。
    ★ 一条键带两表：原版对 `load_stage` 抛错的关是**整关跳过**的。
    """
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import _find_goals, _highland_cells
    try:
        st = load_stage(lv)
    except Exception as exc:                                   # noqa: BLE001
        return {"loaded": False, "why": "%s: %s" % (type(exc).__name__, exc),
                "goal": [], "high": []}
    inp = types.SimpleNamespace(stage=st)
    return {"loaded": True, "why": "",
            "goal": [[int(x), int(y)] for x, y in sorted(_find_goals(inp))],
            "high": [[int(x), int(y)] for x, y in _highland_cells(inp)]}


def main() -> int:
    G = GB.bind("格表", __file__)

    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：simgo/spec.py 的 _find_goals / _highland_cells")
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    both_refused = 0
    seen: dict[str, int] = {}

    #: ★ 这一批关卡的**输入身份**（公式只有一份：`freeze_baseline.level_inputs()`）。
    batch = GB.level_inputs(DATA, levels)
    if G.mode == GB.RECORD:
        G.expect(("query", "level_batch"), lambda: batch)
    cov = G.coverage("cells", [[r["level"], r["sha16"]] for r in batch])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov.ok:
        covered = {tuple(x) for x in cov.covered}
        to_cmp = [r for r in batch if (r["level"], r["sha16"]) in covered]

    for rec in to_cmp:
        lv = rec["level"]
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        E = G.expect(("cells", lv, rec["sha16"]), lambda lv=lv: py_cells_level(lv))
        if not E["loaded"]:
            continue
        ok, got = go_cells(lv)
        if not ok:
            bad += 1
            print("✗ %s —— Go 拒了：%s" % (lv, got))
            continue
        compared += 1
        want_goal = E["goal"]
        want_high = E["high"]
        seen["有防守点格" if want_goal else "无防守点格"] = \
            seen.get("有防守点格" if want_goal else "无防守点格", 0) + 1
        seen["有高台格" if want_high else "无高台格"] = \
            seen.get("有高台格" if want_high else "无高台格", 0) + 1
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got["goal_cells"] = got["goal_cells"] + [[99, 99]]
        for key, want in (("goal_cells", want_goal),
                          ("highland_cells", want_high)):
            g = got[key]
            if g != want:
                bad += 1
                print("✗ %s %s：Go 条数=%d Python 条数=%d%s"
                      % (lv, key, len(g), len(want),
                         "" if len(g) != len(want)
                         else "（条数相同、内容不同，前 3 项 Go=%r Python=%r）"
                              % (g[:3], want[:3])))
            else:
                seen["%s 逐格一致" % key] = seen.get("%s 逐格一致" % key, 0) + 1

    if G.mode == GB.CHECK and not cov.ok:
        print()
        print(cov.report("cells", len(batch)))
    print()
    print("已比：两张格表；%d 关（缓存可达）" % compared)
    print("★ 行使计数：")
    for k, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-22s %d" % (k, n))
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    #: 只要求两表都真被比过 + 有格的那一侧真出现过（否则是空集对空集，零信息量）。
    must = ["goal_cells 逐格一致", "highland_cells 逐格一致", "有高台格"]
    unchecked = [k for k in must if seen.get(k, 0) == 0]
    if unchecked:
        print("结论：没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d 关逐格一致（另 %d 例两边都拒）" % (compared, both_refused))
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
