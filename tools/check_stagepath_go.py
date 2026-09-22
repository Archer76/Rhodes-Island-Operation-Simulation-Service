#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：地面寻路（`StageMap.ground_path`）。

## 对的是什么

`ak_tactic/gamedata/stage.py:172-226`。它是**路线生产侧**的一半，
卡着 `spawns` 与 `unsupported` 两个键。

## ★ 这条判据自己踩过的坑（写在这里防止再犯）

第一版把「这个用例属于哪一类」的统计与「期望值」混在同一个 if/elif 链里：
期望值用**海象运算符只在一个分支内赋值**，于是用例落进前两支（同格／端点
不可走）时，`wm` 留的是**上一轮的期望值**——拿陈旧值去比，必然不等，
报出一串 `[0,6]→[0,6]：Go 长 1 / Python 长 12` 的假失配。

⇒ 规矩：**分类与期望值是两件事**。期望值在循环开头**无条件**算好；
分类只用来计数，绝不给期望值赋值。

用法:
    python tools\\check_path_go.py
    python tools\\check_path_go.py --mutate
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
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"


def go_paths(level: str, qs: list[dict]) -> list[list[list[int]]]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "path", "level": level, "spec": qs}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    resp = json.loads(line[0]) if line else {}
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["paths"]


def main() -> int:
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []
    from ak_tactic.gamedata.stage import load_stage

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：gamedata/stage.py 的 StageMap.ground_path")
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    seen = {"关卡": 0, "同格": 0, "端点不可走": 0, "正常寻路": 0, "路径一致": 0}
    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue
        qs, wants, kinds = [], [], []
        for r in st.routes:
            for diag in (True, False):
                s, e = tuple(r.start), tuple(r.end)
                qs.append({"start": [int(s[0]), int(s[1])],
                           "end": [int(e[0]), int(e[1])],
                           "diagonal": diag})
                #: ★ 期望值**无条件**算好（不放进任何分支）。
                wants.append([[int(x), int(y)] for x, y in
                              st.map.ground_path(s, e, diagonal=diag)])
                #: 分类只用于计数。
                if s == e:
                    kinds.append("同格")
                elif not st.map.walkable(*s) or not st.map.walkable(*e):
                    kinds.append("端点不可走")
                else:
                    kinds.append("正常寻路")
        if not qs:
            continue
        got = go_paths(lv, qs)
        if len(got) != len(wants):
            bad += 1
            print("✗ %s 条数：Go=%d Python=%d" % (lv, len(got), len(wants)))
            continue
        compared += 1
        seen["关卡"] += 1
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got[0] = got[0] + [[99, 99]]
        for i, (q, g, w) in enumerate(zip(qs, got, wants)):
            seen[kinds[i]] += 1
            gm = [list(map(int, p)) for p in g]
            if gm == w:
                seen["路径一致"] += 1
            else:
                bad += 1
                if bad <= 5:
                    print("✗ %s %s→%s（diagonal=%s，%s）：Go 长 %d / Python 长 %d"
                          % (lv, q["start"], q["end"], q["diagonal"],
                             kinds[i], len(gm), len(w)))
                    if len(gm) == len(w):
                        for k, (a, b) in enumerate(zip(gm, w)):
                            if a != b:
                                print("    首个不同在第 %d 步：Go=%r Python=%r"
                                      % (k, a, b))
                                break

    print("已比：地面寻路；%d 关的全部路线 × {含斜向, 不含斜向}，共 %d 例"
          % (compared, seen["路径一致"] + bad))
    print("★ 行使计数：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if seen["正常寻路"] == 0 or seen["关卡"] == 0:
        print("结论：正常寻路一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    print("结论：%d 例逐格一致（退化分支的行使计数见上；为 0 表示这批关卡没有）"
          % seen["路径一致"])
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
