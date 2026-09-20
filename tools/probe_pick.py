"""索敌现场取证：把某个干员某一刻的 `cells` / `blocking` / 全场 `(嘲讽, progress)`
全表打出来，和 Go 的 `OPATK`（`block=` / `pick=` / `inrange=`）逐项对。

为什么要专门做这个：`hsex07` 剩下的分歧不在伤害公式，而在**主目标选谁**，
而主目标由三段规则决定——① 先打 `op.blocking` 里的；② 再按
`(-嘲讽, -progress)` 排序取范围内；③ 取够 `n` 个。
只看"打出来多少伤害"分不清是哪一段选的，得把**输入**打出来。

用法：
    python tools/probe_pick.py <plan> <干员名> [从] [到]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import resolve                                   # noqa: E402
from ak_tactic.plan import Plan, Roster                           # noqa: E402
from probe_pile_chain import SimCapture                           # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    who = sys.argv[2] if len(sys.argv) > 2 else "泥岩"
    lo = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    hi = float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    dt = 1.0 / 30.0
    state = {"last_t": -dt}
    seen: list[tuple[float, dict]] = []
    orig_atk = sim_mod.BattleSimulator._enemies_attack
    orig = sim_mod.BattleSimulator._pick_targets

    def patched_atk(self, d, t):                                  # noqa: ANN001
        state["last_t"] = float(t)
        return orig_atk(self, d, t)

    def patched(self, op, cells, n=1):                            # noqa: ANN001
        t = state["last_t"] + dt
        if op.name == who and lo <= t <= hi:
            blk = [(getattr(e, "name", "?"), round(float(e.hp), 1))
                   for e in getattr(op, "blocking", []) or []]
            tbl = []
            for e in self.enemies:
                if e.hp <= 0 or e.leaked:
                    continue
                cell = (int(round(e.position[0])), int(round(e.position[1])))
                tbl.append((e.name, cell, cell in cells, e.taunt_level,
                            round(e.progress, 4), round(e.hp, 1)))
            out = orig(self, op, cells, n)
            seen.append((round(t, 4), {
                "cells": sorted(cells), "blocking": blk, "table": tbl,
                "picked": [getattr(e, "name", "?") for e in out],
            }))
        else:
            out = orig(self, op, cells, n)
        return out

    sim_mod.BattleSimulator._enemies_attack = patched_atk
    sim_mod.BattleSimulator._pick_targets = patched
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._pick_targets = orig
        sim_mod.BattleSimulator._enemies_attack = orig_atk

    print(f"[原版] {who} 在窗口内的索敌 {len(seen)} 次")
    for t, rec in seen:
        print(f"  ── t={t}  范围格={rec['cells']}")
        print(f"     阻挡={rec['blocking']}")
        print(f"     选中={rec['picked']}")
        for nm, cell, inr, taunt, prog, hp in sorted(
                rec["table"], key=lambda r: (not r[2], -r[3], -r[4])):
            print(f"       {'✓' if inr else ' '} {nm} {cell} 嘲讽={taunt} "
                  f"progress={prog} hp={hp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
