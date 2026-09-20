"""比两台引擎上**干员的回血**（逐笔、按干员）。

由来：`hsex07` 追到"伤害逐笔相同、总血量相同、只有最后一笔截断值不同"，
那剩下的唯一去处就是**回血**——两边的伤害进账一样，血池一样，
谁在那一拍血更多，只能是谁回得更多。

用法：python tools/probe_op_heal.py [plan]
"""
from __future__ import annotations

import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                          # noqa: E402
from ak_tactic.plan import Plan, Roster                             # noqa: E402
from probe_pile_chain import SimCapture                             # noqa: E402
import trace_kv                                                     # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    py: list[tuple[str, float, float]] = []
    tick: dict[str, float] = {"t": 0.0}
    orig_heal = sim_mod.OperatorUnit.heal
    orig_atk = sim_mod.BattleSimulator._enemies_attack

    def patched_atk(self, dt, t):                                   # noqa: ANN001
        tick["t"] = float(t)
        return orig_atk(self, dt, t)

    def patched(self, amount, *a, **kw):                            # noqa: ANN001
        before = float(getattr(self, "hp", 0.0))
        out = orig_heal(self, amount, *a, **kw)
        after = float(getattr(self, "hp", 0.0))
        if after - before > 0:
            py.append((self.name, round(after - before, 3), round(tick["t"], 4)))
        return out

    sim_mod.OperatorUnit.heal = patched
    sim_mod.BattleSimulator._enemies_attack = patched_atk
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.OperatorUnit.heal = orig_heal
        sim_mod.BattleSimulator._enemies_attack = orig_atk

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    import subprocess
    from ak_tactic.simgo import find_binary
    proc = subprocess.run([str(find_binary())],
                          input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                          capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(proc.stderr, "OPHEAL", ("t", "op", "got"))
    go = [(r["op"], round(float(r["got"]), 3), round(float(r["t"]), 4)) for r in rows]

    pa = collections.defaultdict(list)
    ga = collections.defaultdict(list)
    for n, d, t in py:
        pa[n].append((d, t))
    for n, d, t in go:
        ga[n].append((d, t))

    print(f"回血合计：原版 {sum(x[1] for x in py):.1f}（{len(py)} 笔）"
          f"  Go {sum(x[1] for x in go):.1f}（{len(go)} 笔）")
    print(f"{'干员':<18}{'原版笔':>7}{'Go笔':>7}{'原版合计':>12}{'Go合计':>12}{'差':>10}")
    for n in sorted(set(pa) | set(ga)):
        sa = sum(x[0] for x in pa[n])
        sb = sum(x[0] for x in ga[n])
        print(f"{n:<18}{len(pa[n]):>7}{len(ga[n]):>7}{sa:>12.1f}{sb:>12.1f}{sa - sb:>10.1f}")
    for n in sorted(set(pa) | set(ga)):
        A = [x[0] for x in pa[n]]
        B = [x[0] for x in ga[n]]
        k = next((i for i in range(min(len(A), len(B))) if A[i] != B[i]), None)
        if k is None:
            continue
        print(f"  {n} 第 {k + 1} 笔起不同：")
        for j in range(max(0, k - 1), min(k + 3, min(len(A), len(B)))):
            print(f"     #{j + 1} 原版 {A[j]:10.1f} t={pa[n][j][1]}"
                  f"    Go {B[j]:10.1f} t={ga[n][j][1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
