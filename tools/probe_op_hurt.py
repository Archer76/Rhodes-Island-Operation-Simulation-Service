"""对账：**干员挨打**的逐笔流水（原版侧钩 `OperatorUnit.take`，Go 侧读 `OPDMG`）。

背景：四项判决里**没有干员血量**，所以"某名干员早了 3 秒阵亡"这类分歧
在判决上只表现为用时/伤害的间接差异——`hsex07` 就是如此
（原版 凛冬 73.0s 阵亡、Go 70.0s，判决则是 杀+1 / 用时+12.7s）。

用法：
    python tools/probe_op_hurt.py <plan>
"""
from __future__ import annotations

import collections
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                       # noqa: E402
from ak_tactic.plan import Plan, Roster                          # noqa: E402
from probe_pile_chain import SimCapture                          # noqa: E402
import trace_kv                                                  # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    upto = float(sys.argv[2]) if len(sys.argv) > 2 else 80.0
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    hits: list[tuple[float, str, float]] = []
    #: `OperatorUnit` 身上**没有** `sim`/`time`——时间得从外面喂进来。
    #: 钩 `_enemies_attack` 来拿本帧的 `t`（它跑在帧序 7，与挨打同一段）。
    state = {"t": 0.0}
    orig_atk = sim_mod.BattleSimulator._enemies_attack

    def patched_atk(self, dt, t):                                 # noqa: ANN001
        state["t"] = float(t)
        return orig_atk(self, dt, t)

    orig = sim_mod.OperatorUnit.take

    def patched(self, dmg):                                       # noqa: ANN001
        out = orig(self, dmg)
        if out > 0:
            hits.append((round(state["t"], 4), self.name, float(out)))
        return out

    sim_mod.BattleSimulator._enemies_attack = patched_atk
    sim_mod.OperatorUnit.take = patched

    #: 治疗也要一起看：`hsex07` 里 Go 的凛冬血量反复**回到满血**，
    #: 只看挨打流水会以为"她一直在挨打然后突然死"，其实是治疗在拉。
    #: 两个量必须成对出现，否则会把"多治了一次"读成"少挨了一刀"。
    heals: list[tuple[float, str, float, float]] = []
    orig_heal = sim_mod.OperatorUnit.heal

    def patched_heal(self, amount):                               # noqa: ANN001
        got = orig_heal(self, amount)
        if got:
            heals.append((round(state["t"], 4), self.name, float(got),
                          float(getattr(self, "hp", 0.0))))
        return got

    sim_mod.OperatorUnit.heal = patched_heal
    try:
        pv = SimCapture()
        v = pv.run(plan, roster=roster)
    finally:
        sim_mod.OperatorUnit.take = orig
        sim_mod.OperatorUnit.heal = orig_heal
        sim_mod.BattleSimulator._enemies_attack = orig_atk

    total = collections.defaultdict(float)
    for _t, who, d in hits:
        total[who] += d
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s｜挨打 {len(hits)} 笔")
    print("  累计承受：", {k: round(x, 1) for k, x in total.items()})
    htot = collections.defaultdict(float)
    for _t, who, g, _hp in heals:
        htot[who] += g
    print(f"  治疗 {len(heals)} 笔，累计：", {k: round(x, 1) for k, x in htot.items()})
    for h in heals[:6]:
        print(f"     治 t={h[0]:<9} {h[1]} +{h[2]:.1f} → hp={h[3]:.1f}")
    print(f"  t<{upto} 的笔数：", len([h for h in hits if h[0] < upto]))
    for h in hits[:14]:
        print(f"     t={h[0]:<9} {h[1]} -{h[2]:.1f}")

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
    rows = trace_kv.rows(p.stderr, "OPDMG", ("t", "op", "dealt", "cum", "hp"))
    tot2 = collections.defaultdict(float)
    for r in rows:
        tot2[r["op"]] += float(r["dealt"])
    print(f"[go]     {gv['kills']}杀 {gv['leaks']}漏 {gv['elapsed']:.6f}s｜挨打 {len(rows)} 笔")
    print("  累计承受：", {k: round(x, 1) for k, x in tot2.items()})
    hrows = trace_kv.rows(p.stderr, "OPHEAL", ("t", "op", "want", "got", "hp", "max"))
    h2 = collections.defaultdict(float)
    for r in hrows:
        h2[r["op"]] += float(r["got"])
    print(f"  治疗 {len(hrows)} 笔，累计：", {k: round(x, 1) for k, x in h2.items()})
    for r in hrows[:6]:
        print(f"     治 t={r['t']:<9} {r['op']} +{float(r['got']):.1f} → hp={r['hp']}")
    print(f"  t<{upto} 的笔数：",
          len([r for r in rows if float(r["t"]) < upto]))
    for r in rows[:14]:
        print(f"     t={r['t']:<9} {r['op']} -{float(r['dealt']):.1f} hp={r['hp']}")

    # ---- 按序号对齐，找**第一处数值不同** ----
    #: ⚠ 不比时刻：两台引擎的痕迹里 `t` 系统性差一帧（同一件事一边记 20.9667、
    #: 另一边记 21.0），逐帧比时刻会把**每一个事件都报成差**。
    #: 金额（dealt / got）与对象名才是可比量，时刻只用来定位。
    py_h = [(w, round(g, 3)) for _t, w, g, _hp in heals]
    go_h = [(r["op"], round(float(r["got"]), 3)) for r in hrows]
    py_d = [(w, round(d, 3)) for _t, w, d in hits]
    go_d = [(r["op"], round(float(r["dealt"]), 3)) for r in rows]
    for name, a, b in (("治疗", py_h, go_h), ("挨打", py_d, go_d)):
        n = min(len(a), len(b))
        first = next((i for i in range(n) if a[i] != b[i]), None)
        print(f"  [{name}] 原版 {len(a)} 笔 / Go {len(b)} 笔"
              + (f"｜**逐笔全同**（共 {n} 笔）" if first is None
                 else f"｜第一处不同在第 {first} 笔：{a[first]} vs {b[first]}"))
        if first is not None:
            #: 时刻要单独打：金额只说明"差了多少"，**时刻才说明"从哪一刻开始差"**。
            t_py = hits[first][0] if name == "挨打" else heals[first][0]
            t_go = (rows[first]["t"] if name == "挨打" else hrows[first]["t"])
            print(f"      第一处不同的时刻：原版 t={t_py}  Go t={t_go}")
            for i in range(max(0, first - 2), min(n, first + 3)):
                mark = "  ←" if i == first else ""
                print(f"       #{i:<5} 原版 {a[i]}   Go {b[i]}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
