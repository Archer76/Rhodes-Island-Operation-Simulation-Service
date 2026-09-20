"""按**干员**比"承伤累计"随时间的第一处分叉。

为什么用累计承伤而不是血量：血量在两边都只在"有事件"时才有样本，
而两边的**事件条数不一样**（截断、护盾、驱散都会让条数不同），
按下标对齐会一路漂。累计承伤是**单调量**，在同一时刻上比较是有意义的。

原版：`op.damage_taken`（`Combatability.take` 自己累的，权威）；
Go：`OPDMG` 的 `cum=` 列。

用法：python tools/probe_cum_dmg.py [plan] [干员名]
"""
from __future__ import annotations

import bisect
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                          # noqa: E402
from ak_tactic.plan import Plan, Roster                             # noqa: E402
from probe_pile_chain import SimCapture                             # noqa: E402
import trace_kv                                                     # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    who = sys.argv[2] if len(sys.argv) > 2 else "泥岩"
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    py: list[tuple[float, float]] = []
    tick: dict[str, float] = {"t": 0.0}
    o_take = sim_mod.OperatorUnit.take
    o_atk = sim_mod.BattleSimulator._enemies_attack

    def patched_atk(self, dt, t):                                   # noqa: ANN001
        tick["t"] = float(t)
        return o_atk(self, dt, t)

    def patched(self, amount, *a, **kw):                            # noqa: ANN001
        out = o_take(self, amount, *a, **kw)
        if self.name == who:
            py.append((round(tick["t"], 4), round(float(self.damage_taken), 3)))
        return out

    sim_mod.OperatorUnit.take = patched
    sim_mod.BattleSimulator._enemies_attack = patched_atk
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.OperatorUnit.take = o_take
        sim_mod.BattleSimulator._enemies_attack = o_atk

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    from ak_tactic.simgo import find_binary
    proc = subprocess.run([str(find_binary())],
                          input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                          capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(proc.stderr, "OPDMG", ("t", "op", "dealt", "cum", "hp"))
    go = [(round(float(r["t"]), 4), round(float(r["cum"]), 3))
          for r in rows if r["op"] == who]

    print(f"{who}：原版 {len(py)} 笔 / Go {len(go)} 笔")
    if not py or not go:
        print("  有一边没有任何一笔，先查是不是根本没参战")
        return 0
    py_t = [x[0] for x in py]

    def py_at(t: float) -> float:
        i = bisect.bisect_right(py_t, t + 1e-9) - 1
        return py[i][1] if i >= 0 else 0.0

    print(f"{'t':>11}{'原版累计':>12}{'Go累计':>12}{'差':>10}")
    first = None
    for t, c in go:
        a = py_at(t)
        d = c - a
        if first is None and abs(d) > 0.5:
            first = t
        if first is not None:
            print(f"{t:>11}{a:>12.1f}{c:>12.1f}{d:>10.1f}")
            if t > first + 0.01 and len([1]) and t - first > 0.5:
                break
    if first is None:
        print("  累计承伤：Go 的每一笔时刻上，原版都对得上")
        print(f"  末值：原版 {py[-1][1]:.1f} @ {py[-1][0]}   Go {go[-1][1]:.1f} @ {go[-1][0]}")
    else:
        print(f"  第一处分叉时刻 t={first}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
