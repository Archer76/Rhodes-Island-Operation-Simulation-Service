"""原样打印两台引擎在**一个时间窗内**的逐笔伤害（不按序号配对）。

为什么要它：`probe_attack_ledger` 是按"第 N 笔"配对显示的，一边多一笔就整体错位，
逐行 Δ 大半是假象。查"某一次出手多打了一个"这类问题时，要看的是
**两边各自在那一刻打了哪几笔、每笔多少、打给谁**——也就是原样清单。

用法：
    python tools/probe_dmg_window.py <plan> <from> <to> [enemy_filter]
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
from probe_pile_chain import SimCapture                          # noqa: E402
import trace_kv                                                  # noqa: E402


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    lo = float(sys.argv[2]) if len(sys.argv) > 2 else 30.0
    hi = float(sys.argv[3]) if len(sys.argv) > 3 else 35.0
    filt = sys.argv[4] if len(sys.argv) > 4 else ""
    #: 第 5 个参数 = 要逐帧看坐标的那只敌人的**名字**（喂给 `RIOS_TRACE_POS`）。
    #: 名字走 argv，所以**只能在 Python 里取**，不能经 PowerShell 传。
    pos_name = sys.argv[5] if len(sys.argv) > 5 else ""
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    from ak_tactic.battle import sim as sim_mod
    py: list[tuple[float, str, str, float, float]] = []
    #: 窗口刚开始那一刻的**全场快照**：只比"打了几笔"分不清是
    #: "目标选得不同"还是"场上站的位置不同"，几何要一起看。
    snap: dict[str, list[tuple[str, float, float, float]]] = {}
    orig = sim_mod.BattleSimulator._damage_enemy

    def patched(self, target, amount, t, damage_type, source=None, **kw):  # noqa: ANN001
        if float(t) >= lo and "at" not in snap:
            snap["at"] = [(e.name, float(e.position[0]), float(e.position[1]),
                           float(getattr(e, "hp", 0.0)))
                          for e in self.enemies]
        before = float(getattr(target, "hp", 0.0))
        out = orig(self, target, amount, t, damage_type, source=source, **kw)
        py.append((round(float(t), 4), getattr(source, "name", "(机制)"),
                   str(getattr(target, "name", "?")), float(amount),
                   round(before - float(getattr(target, "hp", 0.0)), 4)))
        return out

    sim_mod.BattleSimulator._damage_enemy = patched
    try:
        pv = SimCapture()
        v = pv.run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._damage_enemy = orig

    #: ⚠ **过滤 `实掉 > 0` 才可比**：Go 的 `DMGENEMY` 只在 `dealt > 0` 时记
    #: （`sim.go:2510` 的 `if traceOn && … && dealt > 0`），而这里的钩子记**每一次
    #: 调用**——不过滤就会把"甲身上那几笔 0 伤害"读成"原版多打了 3 笔"。
    #: 这是本会话第六个"两边计数器含义不同"的坑。
    sel = [r for r in py if lo <= r[0] <= hi and r[4] > 0
           and (not filt or filt in r[2])]
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s｜"
          f"窗口内（实掉>0）{len(sel)} 笔")
    for t, src, tgt, amt, real in sel:
        print(f"     t={t:<9} {src} → {tgt}  量={amt:.2f} 实掉={real:.2f}")
    if "at" in snap:
        near = [s for s in snap["at"] if abs(s[1] - 7.0) <= 2.5 and abs(s[2] - 3.0) <= 2.5]
        print(f"  原版 t≈{lo} 场上 {len(snap['at'])} 只，凛冬(7,3) 附近 5×5 内 {len(near)} 只：")
        for nm, x, y, hp in sorted(near, key=lambda s: (s[0], s[1], s[2])):
            print(f"     {nm} @ ({x!r},{y!r}) hp={hp:.1f}")

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    from ak_tactic.simgo import find_binary
    #: ⚠ `POS` 痕迹是**按名字门控**的（`RIOS_TRACE_POS`，`skill.go:256`）——
    #: 不设这个变量时它一行都不打，很容易被读成"场上没有敌人"。
    #: 这是本会话第七个不对称仪器。
    #:
    #: 名字**不能经 PowerShell 传**（中文首字会被吃掉，本项目的旧坑），
    #: 所以 `pos_name` 支持写成**出怪表序号**：在这里用 Python 解析成真名。
    env = dict(os.environ, RIOS_TRACE="1")
    if pos_name.strip().isdigit():
        spawns = spec.get("spawns") or []
        i = int(pos_name)
        if not 0 <= i < len(spawns):
            raise SystemExit(f"出怪表只有 {len(spawns)} 条，取不到第 {i} 条")
        pos_name = str(spawns[i].get("name") or "")
        print(f"  （RIOS_TRACE_POS ← 出怪表第 {i} 条：{pos_name}）")
    if pos_name:
        env["RIOS_TRACE_POS"] = pos_name
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=env)
    gv = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    rows = trace_kv.rows(p.stderr, "DMGENEMY", ("t", "enemy", "src", "dealt"))
    gsel = [r for r in rows if lo <= float(r["t"]) <= hi
            and (not filt or filt in r["enemy"])]
    print(f"[go]     {gv['kills']}杀 {gv['leaks']}漏 {gv['elapsed']:.6f}s｜"
          f"窗口内 {len(gsel)} 笔")
    for r in gsel:
        print(f"     t={r['t']:<9} {r['src']} → {r['enemy']}  实掉={float(r['dealt']):.2f}")
    pos = trace_kv.rows(p.stderr, "POS",
                        ("t", "idx", "name", "x", "y", "hp", "blocked", "legu"))
    frame = [r for r in pos if abs(float(r["t"]) - lo) < 0.02]
    near2 = [r for r in frame if abs(float(r["x"]) - 7.0) <= 2.5
             and abs(float(r["y"]) - 3.0) <= 2.5]
    print(f"  Go t≈{lo} 场上 {len(frame)} 只，凛冬(7,3) 附近 5×5 内 {len(near2)} 只：")
    for r in sorted(near2, key=lambda r: (r["name"], float(r["x"]), float(r["y"]))):
        #: 坐标打**原样 7 位**，不要 `:.2f`：卡在**整数边界**上的敌人
        #: （如 x=7.4996 / 7.5004）两位小数看着都像 7.50，而落格一个是 7、一个是 8，
        #: 一个在范围里、一个不在——这类分歧只在小数第 4 位以后才看得见。
        print(f"     {r['name']} @ ({r['x']},{r['y']}) "
              f"hp={float(r['hp']):.1f} blocked={r['blocked']}")

    # ---- 累计伤害曲线：**免键的标量序列** ----
    #: 逐笔配对在"同名敌人有好几只"时必然撞车（本会话栽过），
    #: 而"到 t 为止某个名字总共挨了多少"是**每台引擎自己算得出来的标量**，
    #: 不需要任何跨引擎的键。第一个对不上的时刻就是分歧点。
    def curve(rows: list[tuple[float, str, float]]) -> dict[float, dict[str, float]]:
        cum: dict[str, float] = {}
        out: dict[float, dict[str, float]] = {}
        for t, nm, d in rows:
            cum[nm] = cum.get(nm, 0.0) + d
            out[round(t, 4)] = dict(cum)
        return out

    py_rows = [(r[0], r[2], r[4]) for r in py if r[4] > 0]
    go_rows = [(float(r["t"]), r["enemy"], float(r["dealt"])) for r in rows]
    cpy, cgo = curve(py_rows), curve(go_rows)
    #: ⚠ **只比严格同刻的 t**。曾经写成"取 0.04 内最近的一个"，而字典是按时间
    #: 插入的，`near[0]` 拿到的是**早一帧**那个键——累计值天然更小，
    #: 于是**每一个时刻都被报成"有差"**，第一处分歧永远指向窗口开头。
    #: 时刻本来就该是同一张网格（都是 `frame/fps`），对不上就是别的问题。
    same = sorted(set(cpy) & set(cgo))
    only_py = sorted(set(cpy) - set(cgo))
    only_go = sorted(set(cgo) - set(cpy))
    print(f"  同刻可比 {len(same)} 个（原版独有 {len(only_py)}、Go 独有 {len(only_go)}）")
    #: ⚠ **只有一边有的时刻同样算分歧。** 曾经只报"共有时刻里第一处不同"，
    #: 于是"两边各自打了几笔、时刻完全不重叠"会打印成"逐帧全同"——
    #: `hsex07` 最后剩下的那 4 笔（共 56 个同刻全同、差额全在只有原版有的
    #: 4 个时刻上）差一点就被这条盖掉。**不可比 ≠ 相同。**
    if only_py or only_go:
        print("  ⚠ 只有一边有伤害的时刻（这些**本身就是分歧**）：")
        for t in only_py[:6]:
            print(f"     仅原版 t={t}：{ {n: round(v, 1) for n, v in cpy[t].items() if v} }")
        for t in only_go[:6]:
            print(f"     仅 Go   t={t}：{ {n: round(v, 1) for n, v in cgo[t].items() if v} }")
        if len(only_py) > 6 or len(only_go) > 6:
            print(f"     …（原版独有 {len(only_py)}、Go 独有 {len(only_go)}，只列前 6）")
    first = None
    for t in same:
        g, h = cpy[t], cgo[t]
        names = set(g) | set(h)
        bad = [n for n in names if abs(g.get(n, 0.0) - h.get(n, 0.0)) > 0.5]
        if bad:
            first = (t, bad, g, h)
            break
    if first is None:
        if only_py or only_go:
            print("  累计曲线：共有时刻逐帧全同，**但存在只有一边有伤害的时刻**"
                  f"（原版独有 {len(only_py)}、Go 独有 {len(only_go)}）——不算相同。")
        else:
            print("  累计曲线：**逐帧全同**（同名敌人合计对得上）")
    else:
        t, bad, g, h = first
        print(f"  累计曲线第一处分歧：t={t}")
        for n in bad:
            print(f"     {n}：原版累计 {g.get(n, 0.0):.1f}  Go 累计 {h.get(n, 0.0):.1f}"
                  f"  （差 {g.get(n, 0.0) - h.get(n, 0.0):.1f}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
