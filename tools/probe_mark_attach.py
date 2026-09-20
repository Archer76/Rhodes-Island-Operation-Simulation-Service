"""对账：天桩-乙**咬中并挂天标**的时刻与位置（原版侧）。

为什么要单独有这个工具：`probe_pile_chain.py` 里"原版数生成过的／Go 数残余的"
是一个**不可比的对照**——原版的 `sim.enemies` 含已阵亡的，Go 的 `remnants`
只列活到最后的。两个计数器名字都叫"敌人"，含义却不同，
第一版就是这么把"16 个天标"读成了"Go 一个都没造"的。

这里改用**同一件东西**：原版钩住 `_pile_attach_mark`、Go 读自己的
`PILEMARK` / 甲召唤日志。判据是"第 N 次挂天标发生在哪一刻"，
两台引擎各自产出，不依赖任何跨引擎的键。

用法：
    python tools/probe_mark_attach.py <plan>      # 例：out/plan-hsex07.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                       # noqa: E402
from ak_tactic.plan import Plan, Roster                          # noqa: E402
from ak_tactic.verify import Verifier                            # noqa: E402
from probe_pile_chain import SimCapture                          # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    marks: list[tuple[float, tuple[float, float], int]] = []
    orig = sim_mod.BattleSimulator._pile_attach_mark

    def patched(self, diver, target, t):                          # noqa: ANN001
        cell = (float(target.position[0]), float(target.position[1]))
        marks.append((round(float(t), 4), cell, len(self.operators)))
        return orig(self, diver, target, t)

    sim_mod.BattleSimulator._pile_attach_mark = patched
    try:
        pv = SimCapture()
        v = pv.run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._pile_attach_mark = orig

    deaths = sorted(round(float(getattr(op, "death_time", -1) or -1), 4)
                    for op in pv.sim.operators if getattr(op, "hp", 1) <= 0)
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    print(f"  挂天标 {len(marks)} 次")
    for t, cell, n in marks[:8]:
        print(f"     t={t:<9} cell=({cell[0]:.1f},{cell[1]:.1f}) 场上干员 {n}")
    if len(marks) > 8:
        print(f"     … 末次 t={marks[-1][0]}")
    print("  干员阵亡时刻：", deaths)

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    from ak_tactic.simgo import find_binary
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    gv = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    attach = [e for e in gv["events"] if e["kind"] == "mech" and "挂上" in e.get("who", "")]
    print(f"[go]     {gv['kills']}杀 {gv['leaks']}漏 {gv['elapsed']:.6f}s")
    print(f"  挂天标 {len(attach)} 次")
    for e in attach[:8]:
        print(f"     t={round(e['t'], 4):<9} {e['who']}")
    if len(attach) > 8:
        print(f"     … 末次 t={round(attach[-1]['t'], 4)}")
    print("  干员阵亡时刻：", sorted(round(e["t"], 4)
                                    for e in gv["events"] if e["kind"] == "death"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
