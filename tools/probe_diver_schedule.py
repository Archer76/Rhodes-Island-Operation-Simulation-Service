"""比两台引擎上"甲啃啮 → 天标贴上"的**排期**，按干员分组。

由来：`hsex07` 最后剩下的 1100.8 已经追到"天标扣血的**时刻**不一样"
（可露希尔：原版 96.3667 / Go 92.3667）。扣血是被动的，**时刻由贴上决定**，
贴上又由"甲扑到谁身上"决定。所以要把这条链的三跳按干员并排打出来。

原版侧钩 `_pile_attach_mark(diver, target, t)`（`sim.py:4787`）——
它是贴上动作本身，比在 `_pile_diver_tick` 里猜"哪一下算咬到"可靠。
Go 侧读 `PILEDIVERBITE`（`target` 是**干员序号**，要用规格里的 operators 表翻名字）。

用法：python tools/probe_diver_schedule.py [plan]
"""
from __future__ import annotations

import collections
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
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    py: list[tuple[float, str, str]] = []
    orig = sim_mod.BattleSimulator._pile_attach_mark

    def patched(self, diver, target, t):                            # noqa: ANN001
        py.append((round(float(t), 4), str(getattr(target, "name", "?")),
                   str(getattr(diver, "name", "?"))))
        return orig(self, diver, target, t)

    sim_mod.BattleSimulator._pile_attach_mark = patched
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._pile_attach_mark = orig

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    names = [o["name"] for o in spec["operators"]]
    from ak_tactic.simgo import find_binary
    proc = subprocess.run([str(find_binary())],
                          input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                          capture_output=True, text=True, encoding="utf-8",
                          env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(proc.stderr, "PILEDIVERBITE",
                         ("t", "idx", "target", "dist", "boom", "pos", "tpos"))
    go = [(round(float(r["t"]), 4), names[int(r["target"])],
           f"idx={r['idx']} dist={r['dist']}") for r in rows]

    print(f"贴上笔数：原版 {len(py)}  Go {len(go)}")
    pa = collections.defaultdict(list)
    ga = collections.defaultdict(list)
    for t, tgt, _ in py:
        pa[tgt].append(t)
    for t, tgt, _ in go:
        ga[tgt].append(t)
    print(f"{'干员':<18}{'原版贴上时刻':<44}{'Go 贴上时刻'}")
    for n in sorted(set(pa) | set(ga)):
        a = " ".join(f"{x:g}" for x in pa[n])
        b = " ".join(f"{x:g}" for x in ga[n])
        mark = "" if pa[n] == ga[n] else "   ← 不同"
        print(f"{n:<18}{a:<44}{b}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
