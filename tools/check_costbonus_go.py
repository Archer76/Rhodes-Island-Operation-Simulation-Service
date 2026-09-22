#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：初始部署费用天赋（`squad_cost_bonus`）。

## 对的是什么

`ak_tactic/battle/talents.py:714-728`。判据只有一句：把天赋黑板里 `$` 开头的
键滤掉之后，**剩下的签好等于 `["cost"]`** 才算，数额取该键的值。

## 为什么它要排在 `deploys` 前面

排程的起始费用是 `initial_cost + Σ squad_cost_bonus(全队天赋)`
（`verify.py:403-405`）。少了它，带这类天赋的队伍**每一次落地时刻都会偏**，
而模拟照常给判决——`deploys` 与 `skill_uses` 两个键都吃这个数。

## 怎么造 oracle

`t.blackboard` 是「键 → 值」的映射，`t.value(k)` 取值。所以拿
`types.SimpleNamespace` 造替身、把**真实函数**当纯函数调即可——不必起 sim，
也不必解析真实天赋表（那是另一层的事，本判据不声称覆盖它）。

用法:
    python tools\\check_costbonus_go.py
    python tools\\check_costbonus_go.py --mutate
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

#: 单条天赋黑板的各种形状。`$` 开头的键是**写法标记**，不是条目。
BOARDS = [
    {},                              # 空：签为 []，不算
    {"cost": 1.0},                   # 命中
    {"cost": 0.0},                   # 命中，数额 0
    {"cost": -3.0},                  # 命中，负值照加
    {"cost": 2.5},                   # 命中，小数
    {"cost": 1.0, "atk": 2.0},       # 键多了 → 不认
    {"atk": 2.0},                    # 没有 cost → 不认
    {"$cost": 9.0},                  # 只剩写法标记 → 滤完为空 → 不认
    {"$x": 1.0, "cost": 4.0},        # 滤掉 $ 后只剩 cost → 命中
    {"cost": 4.0, "$y": 2.0},        # 同上
    {"$a": 1.0, "$b": 2.0},          # 全是标记 → 不认
    {"cost": 1.0, "cost2": 1.0},     # 键名像但不同 → 不认
]


def board_of(bb: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(
        blackboard=dict(bb), value=lambda k, b=bb: float(b.get(k, 0.0)))


def go_costbonus(queries: list[dict]) -> list[float]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "costbonus", "spec": queries}) + "\n"
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
    return resp["cost_bonus"]


def main() -> int:
    from ak_tactic.battle.talents import squad_cost_bonus

    #: 一份入参 = 一次求解：全队的天赋黑板。用叉乘把「命中/不命中/混杂」全走一遍。
    picks = [(), (1,), (5,), (7,), (0, 2), (1, 2), (5, 5), (7, 7), (1, 7), (2, 3, 5)]
    queries = [{"boards": [BOARDS[i] for i in combo]} for combo in picks]
    got = go_costbonus(queries)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0] = got[0] + 1.0

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：ak_tactic.battle.talents.squad_cost_bonus")
    print()

    bad = 0
    seen: dict[str, int] = {"单条命中": 0, "单条不认": 0, "一次多板": 0}
    for q, g in zip(queries, got):
        want = squad_cost_bonus([board_of(b) for b in q["boards"]])
        if len(q["boards"]) > 1:
            seen["一次多板"] += 1
        for b in q["boards"]:
            sig = [k for k in b if not k.startswith("$")]
            seen["单条命中" if sig == ["cost"] else "单条不认"] += 1
        if abs(g - want) > 1e-9:
            bad += 1
            if bad <= 8:
                print("✗ boards=%r —— Go=%r Python=%r" % (q["boards"], g, want))
    print("已比：初始部署费用天赋；%d 次求解（%d 种黑板形状 × %d 种队伍组合）"
          % (len(queries), len(BOARDS), len(picks)))
    print("★ 行使计数：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
    unchecked = [k for k, v in seen.items() if v == 0]
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        print("结论：网格没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d / %d 次求解逐点一致" % (len(queries) - bad, len(queries)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
