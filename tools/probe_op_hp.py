"""比两台引擎上**干员的总血量**。

为什么单列一条：`hsex07` 追到最后发现"陈伤逐笔相同、只有最后一笔（被截断的那笔）
不同"——那就只剩一种可能：**两边的血池不一样大**。
逐笔比伤害看不出这件事，只有把 `max_hp` 并排打出来才看得见。

用法：python tools/probe_op_hp.py [plan]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                          # noqa: E402
from ak_tactic.plan import Plan, Roster                             # noqa: E402
from probe_pile_chain import SimCapture                             # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    seen: dict[str, float] = {}
    orig = sim_mod.BattleSimulator._update_blocking

    def patched(self):                                              # noqa: ANN001
        out = orig(self)
        for o in self.operators:
            seen.setdefault(o.name, round(float(o.max_hp), 1))
        return out

    sim_mod.BattleSimulator._update_blocking = patched
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._update_blocking = orig

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    ops = spec["operators"]
    if ops and "hp" not in ops[0] and "max_hp" not in ops[0]:
        print("规格里干员没有血量字段，实际键：", sorted(ops[0].keys()))
        return 1
    go_hp = {o["name"]: round(float(o.get("max_hp", o.get("hp"))), 1)
             for o in ops}

    print(f"{'干员':<18}{'原版 max_hp':>14}{'Go 规格 hp':>14}{'差':>14}")
    for n in sorted(set(seen) | set(go_hp)):
        a, b = seen.get(n), go_hp.get(n)
        delta = "" if (a is None or b is None) else f"{b - a:+.1f}"
        mark = "" if a == b else "   ← 不同"
        print(f"{n:<18}{a!s:>14}{b!s:>14}{delta:>14}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
