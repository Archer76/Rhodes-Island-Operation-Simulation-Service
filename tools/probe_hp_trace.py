"""并排打某个干员在一段窗口里的**血线**（逐帧），两台引擎对照。

由来：`hsex07` 的泥岩在原版死于 89.3667、Go 死于 89.3333——**只差一帧**，
而这一帧让甲改扑凯尔希，级联出后面全部差异。差一帧这种事，
逐笔比伤害是看不出来的（序数会漂），必须看**同一时刻的血量**。

Go 侧读 `OPDMG`（带 `hp=`，且只在掉血时发），所以窗口内没有 OPDMG 行的帧
用「上一行的 hp 减去回血」推——这里只求**形状**，不追求逐帧精确。
原版侧直接钩 `take`/`heal` 记 hp。

用法：python tools/probe_hp_trace.py <plan> <干员名> <从> <到>
"""
from __future__ import annotations

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
    lo = float(sys.argv[3]) if len(sys.argv) > 3 else 88.0
    hi = float(sys.argv[4]) if len(sys.argv) > 4 else 89.6
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    py: list[tuple[float, float, str]] = []
    tick: dict[str, float] = {"t": 0.0}
    o_take, o_heal = sim_mod.OperatorUnit.take, sim_mod.OperatorUnit.heal
    o_atk = sim_mod.BattleSimulator._enemies_attack

    def patched_atk(self, dt, t):                                   # noqa: ANN001
        tick["t"] = float(t)
        return o_atk(self, dt, t)

    def mk(orig, kind):                                             # noqa: ANN001
        def inner(self, amount, *a, **kw):                          # noqa: ANN001
            out = orig(self, amount, *a, **kw)
            if self.name == who:
                py.append((round(tick["t"], 4), round(float(self.hp), 3), kind))
            return out
        return inner

    sim_mod.OperatorUnit.take = mk(o_take, "take")
    sim_mod.OperatorUnit.heal = mk(o_heal, "heal")
    sim_mod.BattleSimulator._enemies_attack = patched_atk
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.OperatorUnit.take = o_take
        sim_mod.OperatorUnit.heal = o_heal
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
    go = [(round(float(r["t"]), 4), round(float(r["hp"]), 3), round(float(r["dealt"]), 3))
          for r in rows if r["op"] == who and lo <= float(r["t"]) <= hi]
    pyw = [x for x in py if lo <= x[0] <= hi]

    print(f"—— {who} 血线 t∈[{lo}, {hi}] ——")
    print(f"{'t(原版)':>11} {'hp':>10}  {'':<5} | {'t(Go)':>11} {'hp':>10} {'dealt':>9}")
    n = max(len(pyw), len(go))
    for i in range(n):
        a = f"{pyw[i][0]:>11} {pyw[i][1]:>10}" if i < len(pyw) else " " * 22
        b = (f"{go[i][0]:>11} {go[i][1]:>10} {go[i][2]:>9}"
             if i < len(go) else "")
        print(f"{a}  {'':<5} | {b}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
