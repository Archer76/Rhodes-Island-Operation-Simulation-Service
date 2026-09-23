#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自读的攻击范围 vs Python 的 `RangeTable` + `battle.range`。

## 比什么（两栏都要比）

* `cells` —— 相对格（**朝右约定**那张表读对没有）；
* `footprint` —— 绝对格（旋转公式 ＋ 平移对不对）。

只比绝对格会让「旋转错」与「表读错」两种因长得一样；只比相对格盖不到平移。

## 覆盖面

**全表每个范围代号 × 四个朝向 × 一个落点**——不抽样。
「只查几个代号」的话，剩下那些读错了也照样绿。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `RangeTable.cells` ＋ `footprint`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/范围.json`，**不 import `ak_tactic`**。

★ 这套冻的**两半**：代号集（`("query", …)`，来自 `RangeTable.known()`）与逐点期望值。
**只冻期望值不冻代号集**，check 档就问不出该问哪些代号——分母静默变小而全绿是本仓记过的形状。

★ **类型还原（JSON 会抹掉 `tuple` / `set`）**：`tbl.cells()` 给的是 `tuple` 列表、
`footprint()` 给的是 `set[tuple]`，而 `json` 只认 `list`。所以取期望值时**先规范化成
JSON 形状**，判据侧再**统一还原**成 `tuple`——**两种模式走同一条还原路径**
（只在 check 档还原的话，两档就不是同一个判据了）。

用法:
    python tools\\check_range_go.py
    python tools\\check_range_go.py --mutate
    python tools\\freeze_baseline.py --record 范围
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

DIRECTIONS = ["Right", "Up", "Left", "Down"]
ORIGIN = (3, 4)

_TBL = None


def _range_table():
    """`RangeTable()` 要读数据，全表只建一次（冻结档下**根本不会建**）。"""
    global _TBL
    if _TBL is None:
        from ak_tactic.gamedata.range import RangeTable
        _TBL = RangeTable()
    return _TBL


def py_range_codes() -> list[str]:
    """查询集：全表已知的范围代号（**Python 侧的产物，必须冻住**）。"""
    return _range_table().known()


def py_range_expect(code: str, direction: str) -> dict:
    """一个 (代号, 朝向) 的期望值：相对格 ＋ 绝对格。

    ★ 返回值**先规范化成 JSON 形状**（`tuple` → `list`、`set` → 排序后的 `list`），
    判据侧再用 `tuples()` 还原。这样两种模式比的是同一个东西。
    """
    from ak_tactic.battle.range import footprint
    cells = _range_table().cells(code)
    fp = footprint(cells, direction, ORIGIN)
    return {"cells": [list(c) for c in cells],
            "footprint": [list(c) for c in fp]}


def tuples(rows) -> list[tuple]:
    """JSON 形状 → `tuple` 列表。**两种模式共用这一个还原口**。"""
    return [tuple(r) for r in rows]


def go_range(queries: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "range", "spec": queries}) + "\n"
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
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["ranges"]


def main() -> int:
    G = GB.bind("范围", __file__)

    codes = G.expect(("query", "range_codes"), py_range_codes)
    queries = [{"code": c, "direction": d, "x": ORIGIN[0], "y": ORIGIN[1]}
               for c in codes for d in DIRECTIONS]
    got = go_range(queries)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        #: 合成一处不一致：判据**必须**红。
        got[0]["footprint"] = list(got[0]["footprint"]) + [[999, 999]]

    bad = 0
    empty = 0
    compared = 0
    for q, g in zip(queries, got):
        #: ★ 期望值只能从这里来；还原成 tuple 这一步**两种模式共用**同一个口。
        want = G.expect(("range", q["code"], q["direction"]),
                        lambda q=q: py_range_expect(q["code"], q["direction"]))
        cells = tuples(want["cells"])
        py_fp = set(tuples(want["footprint"]))
        compared += 1
        if not cells:
            empty += 1
        out = []
        if sorted(map(tuple, g["cells"])) != sorted(cells):
            out.append("cells 不一致（Go %d 格 / Python %d 格）"
                       % (len(g["cells"]), len(cells)))
        if sorted(map(tuple, g["footprint"])) != sorted(py_fp):
            only_go = sorted(set(map(tuple, g["footprint"])) - py_fp)
            only_py = sorted(py_fp - set(map(tuple, g["footprint"])))
            out.append("footprint 不一致（Go %d / Python %d）；Go 多 %s；Python 多 %s"
                       % (len(g["footprint"]), len(py_fp), only_go[:6], only_py[:6]))
        if out:
            bad += 1
            print("✗ %s %s —— %d 处" % (q["code"], q["direction"], len(out)))
            for line in out[:6]:
                print("    " + line)
    print()
    print("已比：相对格 cells ＋ 绝对格 footprint 两栏；共 %d 次（全表 %d 个代号 × %d 朝向）"
          % (compared, len(codes), len(DIRECTIONS)))
    if empty:
        print("⚠ 其中 %d 次该范围在本表里是**空集**——那几次只证明了「两边都空」" % empty)
    else:
        print("★ 零个空集：每一次都比到了真实的格集合（不是「两边都空」的假绿）")
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
    print("结论：%d / %d 次逐格一致" % (compared - bad, compared))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
