"""逐帧坐标对拍：找**第一帧两条位置分叉**。

为什么需要它：`hsex07` 里那只除秽在 t=17.0 时原版 x=`7.4999999999999885`、
Go x=`7.5`——差 1.15e-14，而这 1.15e-14 把落格从 7 翻到 8（凛冬范围只含格 7），
主目标因此换了人，判决差出 杀 +1 / 用时 +12.7s。

只知道"某一刻差了"没用：**要指认是哪一步算错的，必须先知道从哪一帧开始差**。
`%.7f` 的痕迹看不见 1e-14，所以本探针两边都用**全精度**（`repr` / `%.17g`）。

时刻对齐：`EnemyUnit.advance` 拿不到 `t`，所以用上一帧 `_enemies_attack` 记下的
`t` 加一个 `dt` 推出来（帧序上 `_enemies_attack` 在 7.x，`advance` 在 3.1）。

用法：
    python tools/probe_pos_track.py <plan> <出怪表序号> [from] [to]
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
    idx = int(sys.argv[2]) if len(sys.argv) > 2 else 2
    lo = float(sys.argv[3]) if len(sys.argv) > 3 else 0.0
    hi = float(sys.argv[4]) if len(sys.argv) > 4 else 1e9
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    _, spec = cap.held
    spawns = spec.get("spawns") or []
    name = str(spawns[idx].get("name") or "")
    print(f"目标 = 出怪表第 {idx} 条：{name}   （fps={spec.get('fps')}）")

    # ---- 原版：钩 `EnemyUnit.advance`，逐帧记全精度坐标 ----
    from ak_tactic.battle import sim as sim_mod
    dt = 1.0 / float(spec.get("fps") or 30)
    state = {"last_t": -dt}
    py: list[tuple[float, float, float, int, int]] = []
    orig_atk = sim_mod.BattleSimulator._enemies_attack

    def patched_atk(self, d, t):                                  # noqa: ANN001
        state["last_t"] = float(t)
        return orig_atk(self, d, t)

    orig_adv = sim_mod.EnemyUnit.advance

    def patched_adv(self, d, scale):                              # noqa: ANN001
        out = orig_adv(self, d, scale)
        if self.name == name:
            t = state["last_t"] + dt
            if lo <= t <= hi:
                px, py_ = self.position
                py.append((round(t, 4), px, py_,
                           int(round(px)), int(round(py_))))
        return out

    sim_mod.BattleSimulator._enemies_attack = patched_atk
    sim_mod.EnemyUnit.advance = patched_adv
    try:
        SimCapture().run(plan, roster=roster)
    finally:
        sim_mod.EnemyUnit.advance = orig_adv
        sim_mod.BattleSimulator._enemies_attack = orig_atk
    print(f"  原版记下 {len(py)} 帧")

    # ---- Go：读 `POS`（已改成 %.17g + cell） ----
    from ak_tactic.simgo import find_binary
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1", RIOS_TRACE_POS=name))
    rows = trace_kv.rows(p.stderr, "POS",
                         ("t", "idx", "name", "x", "y", "cell", "hp"))
    go = [(round(float(r["t"]), 4), float(r["x"]), float(r["y"]), r["cell"])
          for r in rows if lo <= float(r["t"]) <= hi]
    print(f"  Go   记下 {len(go)} 帧")

    # ---- 按**时刻**对齐，而不是按下标 ----
    #: ⚠ 按下标对齐会骗人：两边帧数不一定相同（某帧 `advance` 没被调用、
    #: 或某只在窗口头还没登场），一旦错位，"逐位相同"就可能只是把 A 的第 k 帧
    #: 与 B 的第 k+2 帧比出来的巧合。**同名敌人还会一只变两只**，
    #: 所以先按 `t` 分桶，桶内个数不同就整桶判为不可比。
    def bucket(rows, key_x, key_y, key_cell):
        out: dict[float, list[tuple[float, float, str]]] = {}
        for r in rows:
            out.setdefault(r[0], []).append((key_x(r), key_y(r), key_cell(r)))
        return out

    py_b = bucket(py, lambda r: r[1], lambda r: r[2], lambda r: f"{r[3]},{r[4]}")
    go_b = bucket(go, lambda r: r[1], lambda r: r[2], lambda r: r[3])
    common = sorted(set(py_b) & set(go_b))
    print(f"  两边共有的时刻 {len(common)} 个"
          f"（原版独有 {len(set(py_b) - set(go_b))}、Go 独有 {len(set(go_b) - set(py_b))}）")
    #: 并排打出**最后几个时刻**的全部实例：只报"第一处不同"在两边个数不一致时
    #: 会静默跳过，而"跳过"和"相同"在输出上长得一样。
    print("  —— 窗口末尾各时刻的两边全量（原版 → | Go →）——")
    for t in common[-4:]:
        a, b = py_b[t], go_b[t]
        sa = "  ".join(f"({x!r},{y!r})[{c}]" for x, y, c in a)
        sb = "  ".join(f"({x!r},{y!r})[{c}]" for x, y, c in b)
        print(f"     t={t}  原版 {len(a)} 只: {sa}")
        print(f"     {' ' * len(str(t))}  Go   {len(b)} 只: {sb}")
    cell_first = None
    pos_first = None
    bad_len = 0
    for t in common:
        a, b = py_b[t], go_b[t]
        if len(a) != len(b):
            bad_len += 1
            continue
        for k in range(len(a)):
            if cell_first is None and a[k][2] != b[k][2]:
                cell_first = (t, k, a[k], b[k])
            if pos_first is None and (a[k][0] != b[k][0] or a[k][1] != b[k][1]):
                pos_first = (t, k, a[k], b[k])
    if bad_len:
        print(f"  ⚠ 有 {bad_len} 个时刻两边**个数不同**（同名多实例，跳过）")
    print("  **落格**第一处不同：" +
          ("全同" if cell_first is None else f"t={cell_first[0]} 第 {cell_first[1]} 只"))
    if pos_first is None:
        print("  **全精度坐标**第一处不同：全同（逐位相同）")
    else:
        t, k, a, b = pos_first
        print(f"  **全精度坐标**第一处不同：t={t} 第 {k} 只")
        print(f"     原版 x={a[0]!r}  y={a[1]!r}  格={a[2]}")
        print(f"     Go   x={b[0]!r}  y={b[1]!r}  格={b[2]}")
        print(f"     Δx={a[0] - b[0]!r}  Δy={a[1] - b[1]!r}")
    if cell_first is not None:
        t, k, a, b = cell_first
        print(f"  落格分叉：t={t} 原版 {a[2]} / Go {b[2]}"
              f"   （x 分别是 {a[0]!r} / {b[0]!r}）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
