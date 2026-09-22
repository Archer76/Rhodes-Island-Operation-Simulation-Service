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

用法:
    python tools\\check_cells_go.py
    python tools\\check_cells_go.py --mutate
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


def main() -> int:
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import _find_goals, _highland_cells

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：simgo/spec.py 的 _find_goals / _highland_cells")
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    both_refused = 0
    seen: dict[str, int] = {}
    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue
        inp = types.SimpleNamespace(stage=st)
        ok, got = go_cells(lv)
        if not ok:
            bad += 1
            print("✗ %s —— Go 拒了：%s" % (lv, got))
            continue
        compared += 1
        want_goal = [[x, y] for x, y in sorted(_find_goals(inp))]
        want_high = _highland_cells(inp)
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

    print()
    print("已比：两张格表；%d 关（缓存可达）" % compared)
    print("★ 行使计数：")
    for k, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-22s %d" % (k, n))
    print()
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
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
