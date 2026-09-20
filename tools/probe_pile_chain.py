"""天桩链的**总量对账**：两边各造了多少甲、多少乙、多少天标，干员何时阵亡。

为什么要有这个工具：`act31side_09` 的乙是**出怪表刷的**，`hsex07` 的乙是
**装置召唤的**（`失控天桩-乙`），两条路的记账完全不同——
出怪表的走 `spec.Spawns`，装置召唤的走机制层的 `m.units`。
对拍只报"杀/漏/用时/伤害"四项时，看不出是"少造了几只"还是"造了但没推"。

判据一律用**每台引擎自己的数**（自己的敌人列表、自己的日志），
不比跨引擎的键——这个会话里已经栽过三次"键撞车/键不存在"的假信号。

用法：
    python tools/probe_pile_chain.py <plan>        # 例：out/plan-hsex07.json
"""
from __future__ import annotations

import collections
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                       # noqa: E402
from ak_tactic.plan import Plan, Roster                          # noqa: E402
from ak_tactic.verify import Verifier                            # noqa: E402
import trace_kv                                                  # noqa: E402


class SimCapture(Verifier):
    """跑原版（默认引擎）并扣住 `sim`。

    ⚠ **不能复用 `parity_plan.PyCapture`**：它的 `self.sim` 是在
    `_run_other_engine` 里赋的，而那个钩子只在 `engine != "python"` 时才走
    （`verify.py:405`）。`compare` 用的是默认引擎，所以 `PyCapture.sim`
    **永远是 None**——它只是一段没人走的死代码，`compare` 又恰好只需要
    `result`，于是这个坑一直没露头。实测 `pv.sim is None` 才发现的。

    真正的挂载点是 `_verdict`：它在两条路上都会被调，而且 `sim` 就在参数里。
    """

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sim = None
        self.res = None

    def _verdict(self, plan, stage, sim, res, deployed, **kw):
        self.sim = sim
        self.res = res
        return super()._verdict(plan, stage, sim, res, deployed, **kw)


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    # ---- 原版：跑一遍，然后数它自己场上的单位 ----
    pv = SimCapture()
    v = pv.run(plan, roster=roster)
    sim = pv.sim
    #: 宁可当场炸，也不要拿到 None 之后把"0 只敌人"当成一条结论报出去。
    assert sim is not None, "没扣住 sim——判据不成立，直接拒跑"
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    cnt = collections.Counter(e.name for e in sim.enemies)
    print("  python 生成过的敌人（含已离场）：", dict(cnt))
    alive = [e for e in sim.enemies
             if getattr(e, "hp", 0) > 0 and not getattr(e, "leaked", False)]
    print("  python 场上还活着：", dict(collections.Counter(e.name for e in alive)))
    dead = [(op.name, getattr(op, "death_time", None) or getattr(op, "death_at", None))
            for op in sim.operators if getattr(op, "hp", 1) <= 0]
    print("  python 干员阵亡：", dead)
    print("  python 漏怪：", [(round(t, 3), n) for t, n in
                              (getattr(sim, "leak_log", None) or [])][:6] or "（看判决）")
    marks = [ln for ln in (getattr(v.result, "log", None) or []) if "天桩" in ln]
    print(f"  python 日志里带「天桩」的行 {len(marks)} 条，头 4 条：")
    for ln in marks[:4]:
        print("     ", ln.strip())

    # ---- Go：直接跑，数它自己的痕迹与残余 ----
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
    blob = json.loads(p.stdout.strip().splitlines()[-1])
    gv = blob["verdict"]
    print(f"[go]     {gv['kills']}杀 {gv['leaks']}漏 {gv['elapsed']:.6f}s  "
          f"won={gv['won']} life={gv['life']} 干员阵亡={gv['operator_deaths']}")
    print("  go 残余：", dict(collections.Counter(str(x[0]) for x in gv["remnants"])))
    print("  go 干员阵亡：", [(e["who"], round(e["t"], 3))
                              for e in gv["events"] if e["kind"] == "death"])
    print("  go 漏怪：", [(round(a, 3), b) for a, b, _ in gv["leak_events"]])
    mech = [e for e in gv["events"] if e["kind"] == "mech"]
    print(f"  go 机制事件 {len(mech)} 条，头 4 条：")
    for e in mech[:4]:
        print("     ", round(e["t"], 3), e.get("who", ""))
    for tag, keys in (("PILEMARK", ("t", "idx", "cell", "attached")),
                      ("PILEBITE", ("t", "idx", "target")),
                      ("PILEBOOM", ("t", "idx"))):
        rows = trace_kv.rows(p.stderr, tag, keys)
        print(f"  go {tag} {len(rows)} 笔")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
