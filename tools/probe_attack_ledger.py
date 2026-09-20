#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员**出手账本**对拍：一笔一笔列出"谁、在哪一帧、打了谁、多少"。

## 为什么需要它（而不是继续用承伤账）

承伤账（`probe_enemy_damage.py`）把差缩到了"某一只敌人多挨了 1,392 点"，
再把逐笔清单拉出来，看到多出来的两笔是 **696.00**——再往下就必须知道
**这一笔是谁打的**。承伤账里没有出手者，所以只能追到"多了两笔"为止。

两边都从**出手落点**取数：
* 原版：钩 `_damage_enemy`（`sim.py:1216`，普攻/技能伤害落到敌人身上的唯一去处），
  它的 `source=` 就是出手的干员；
* Go：`DMGENEMY` 痕迹里的 `src=`（打在同一条链路的汇点上）。

⚠ 这条账本的**价值在于它同时看得见"没打出去的那一笔"**：承伤账只能告诉你
"两边总量差多少"，出手账本能告诉你"哪一帧该出手却没出手"——本轮的第 3 手
残差正是后者（原版圣聆初雪在 65.0/67.0 没出手，Go 出手了）。

用法:
  python tools\\probe_attack_ledger.py 3 --from 64.8 --to 69.2
  python tools\\probe_attack_ledger.py 3 --from 64.8 --to 69.2 --op 圣聆初雪
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace_kv                                                # noqa: E402
from probe_windup_phase import load_plan, load_roster          # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    only = args[args.index("--op") + 1] if "--op" in args else None
    plan, roster = load_plan(k), load_roster()

    # ---- 原版：钩出手落点 ----
    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig = cls._damage_enemy
    state = {"t": -1.0}
    py: list[tuple] = []

    def patched(self, target, amount, t, damage_type, source=None, **kw):
        dealt = orig(self, target, amount, t, damage_type, source=source, **kw)
        if dealt and lo <= t <= hi:
            py.append((t, getattr(source, "name", "(机制)"),
                       getattr(target, "name", "?"), float(dealt)))
        return dealt

    cls._damage_enemy = patched
    orig_env = cls._environment_tick
    try:
        from probe_snow_damage import PyProbe                    # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._damage_enemy = orig
        cls._environment_tick = orig_env
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s "
          f"窗口内出手 {len(py)} 笔")

    # ---- Go：同规格，读 DMGENEMY 的 src ----
    from probe_snow_damage import Thief                          # noqa: E402
    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    from ak_tactic.simgo import find_binary                      # noqa: E402
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(p.stderr, "DMGENEMY", ("t", "enemy", "src", "dealt"))
    go = [(float(d["t"]), d["src"], d["enemy"], float(d["dealt"]))
          for d in rows if lo <= float(d["t"]) <= hi]
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"窗口内出手 {len(go)} 笔")

    #: 按**出手者**分列：残差的形态往往是"某一门干员多/少了 N 次出手"，
    #: 混在一起按时间排会被其它干员的出手冲掉。
    names = sorted({r[1] for r in py} | {r[1] for r in go})
    if only:
        names = [n for n in names if n == only]
    for name in names:
        a = sorted([r for r in py if r[1] == name])
        b = sorted([r for r in go if r[1] == name])
        if not a and not b:
            continue
        print(f"\n—— 出手者「{name}」：原版 {len(a)} 笔（合计 "
              f"{sum(x[3] for x in a):,.2f}） / Go {len(b)} 笔（合计 "
              f"{sum(x[3] for x in b):,.2f}）——")
        show_all = "--all" in args
        for j in range(max(len(a), len(b))):
            x = a[j] if j < len(a) else None
            y = b[j] if j < len(b) else None
            sx = f"t={x[0]:8.4f} → {x[2]:<6} {x[3]:9.2f}" if x else " " * 32
            sy = f"t={y[0]:8.4f} → {y[2]:<6} {y[3]:9.2f}" if y else " " * 32
            mark = ""
            if x is None or y is None:
                mark = "   ← 只有一边有"
            elif abs(x[0] - y[0]) > 1e-4 or abs(x[3] - y[3]) > 0.01:
                mark = f"   ← Δt {y[0] - x[0]:+.4f} / Δ伤害 {y[3] - x[3]:+,.2f}"
            if mark or show_all:
                print(f"  {j:>3} {sx} | {sy}{mark}")
        if len(a) == len(b) and all(
                abs(x[0] - y[0]) < 1e-4 and abs(x[3] - y[3]) < 0.01
                for x, y in zip(a, b)):
            print("    （逐笔一致，未列）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

