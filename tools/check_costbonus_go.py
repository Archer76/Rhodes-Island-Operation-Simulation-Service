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


def find_cost_talent_chars(limit: int) -> list[str]:
    """从全表里捞出**真有**「单键 cost」天赋的干员。

    ⚠ 为什么要捞：名册夹具那 20 位里一个都没有（实测非零 0 例），
    只拿名册当网格等于**只验了「返回 0」那一条支**——那是一片零信息量的绿。
    """
    blob = json.loads((DATA / "raw.githubusercontent.com" / "excel" /
                       "character_table.json").read_text(encoding="utf-8"))
    out: list[str] = []
    for cid, c in blob.items():
        if not cid.startswith("char_"):
            continue
        hit = False
        for t in c.get("talents") or []:
            for cand in t.get("candidates") or []:
                keys = [b.get("key") for b in (cand.get("blackboard") or [])]
                sig = [k for k in keys if k and not k.startswith("$")]
                if sig == ["cost"]:
                    hit = True
        if hit:
            out.append(cid)
            if len(out) >= limit:
                break
    return out


def go_talentbonus(cfgs: list[dict]) -> list[float]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "talentbonus", "spec": cfgs}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    resp = json.loads(line[0]) if line else {}
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["talent_bonus"]


def main() -> int:
    from ak_tactic.battle.talents import squad_cost_bonus
    from ak_tactic.operator import TalentBook
    from ak_tactic.plan import Roster

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
    #: ---- 第二部分：从**真实天赋表**算（这才是排程要用的那一步）----
    tb = TalentBook()
    ros = Roster.from_json(ROOT / "fixtures" / "roster_max_modelled.json")
    cfgs, wants = [], []
    for _name, e in ros.entries.items():
        for pot in (1, 3, 6):
            cfgs.append({"char_id": e["char_id"], "elite": e["elite"],
                         "level": e["level"], "potential": pot})
            wants.append(squad_cost_bonus(tb.for_operator(
                e["char_id"], elite=e["elite"], level=e["level"],
                potential=pot)))
    #: ⚠ 名册那 20 位里一个带这条天赋的都没有（实测非零 0 例）⇒ 只验到了
    #: 「返回 0」那一条支。这里从**全表**捞真有这条天赋的干员补进网格。
    picked = find_cost_talent_chars(limit=8)
    added = 0
    for cid in picked:
        for elite, level, pot in ((2, 90, 6), (2, 90, 1), (0, 1, 1), (1, 55, 3)):
            w = squad_cost_bonus(tb.for_operator(
                cid, elite=elite, level=level, potential=pot))
            if w:
                cfgs.append({"char_id": cid, "elite": elite, "level": level,
                             "potential": pot})
                wants.append(w)
                added += 1
    print("★ 全表里带「单键 cost」天赋的干员捞到 %d 位，其中 %d 组练度数额非零"
          % (len(picked), added))
    real = go_talentbonus(cfgs)
    if mutate and real:
        real[0] = real[0] + 1.0
    nonzero = sum(1 for w in wants if w)
    for c, g, w in zip(cfgs, real, wants):
        if abs(g - w) > 1e-9:
            bad += 1
            if bad <= 8:
                print("✗ 真实天赋 %s（精英%d/等级%d/潜能%d）—— Go=%r Python=%r"
                      % (c["char_id"], c["elite"], c["level"], c["potential"],
                         g, w))
        else:
            seen["真实天赋逐人一致"] = seen.get("真实天赋逐人一致", 0) + 1
    seen["真实天赋非零"] = nonzero
    print()
    print("已比（第二部分）：%d 位干员 × 3 档潜能，对拍 TalentBook.for_operator"
          "（其中 %d 例数额非零）" % (len(cfgs), nonzero))
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
