#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员**承伤/受治账本**（原版侧钩 `Combatant.take` / `Combatant.heal`）。

## 为什么需要它

k=4 的形态是：某位干员在 Go 里早倒 105 秒，而她的**每秒承伤两边完全一致**
（约 61/s）。两边承伤速率一样却一个活到 205 秒、一个 100 秒就倒，
那只可能是**回血**不一样——而回血在原版侧原先**一条痕迹都没有**
（Go 侧有 `OPHEAL`，原版只有 `result.log` 里零散的几行）。

⚠ 钩的是 `Combatant` 上的那两个方法，对干员与敌人都生效，
所以按名字分账、并按 `Operators` 过滤——**不要按"名字在名册里"猜**。

用法:
  python tools\\probe_operator_ledger.py 4
  python tools\\probe_operator_ledger.py 4 --op 怒潮凛冬 --from 90 --to 101
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster          # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 4
    only = args[args.index("--op") + 1] if "--op" in args else None
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    plan, roster = load_plan(k), load_roster()

    from ak_tactic.battle import sim as S
    from ak_tactic.battle import unit as U
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    state = {"t": -1.0, "ops": set()}
    taken: dict[str, float] = {}
    healed: dict[str, float] = {}
    ledger: list[tuple] = []
    orig_take, orig_heal = U.Combatant.take, U.Combatant.heal
    orig_env = cls._environment_tick

    def is_op(obj) -> bool:
        #: `self.operators` 里的对象就是干员；用容器判身份，不按类名猜。
        return id(obj) in state["ops"]

    def take(self, amount, *a, **kw):
        dealt = orig_take(self, amount, *a, **kw)
        if is_op(self) and dealt:
            n = getattr(self, "name", "?")
            taken[n] = taken.get(n, 0.0) + float(dealt)
            if lo <= state["t"] <= hi:
                ledger.append(("受击", state["t"], n, float(dealt)))
        return dealt

    def heal(self, amount, *a, **kw):
        got = orig_heal(self, amount, *a, **kw)
        if is_op(self) and got:
            n = getattr(self, "name", "?")
            healed[n] = healed.get(n, 0.0) + float(got)
            if lo <= state["t"] <= hi:
                ledger.append(("受治", state["t"], n, float(got)))
        return got

    def env(self, dt, t):
        state["t"] = t
        for o in getattr(self, "operators", ()) or ():
            state["ops"].add(id(o))
        return orig_env(self, dt, t)

    U.Combatant.take, U.Combatant.heal = take, heal
    cls._environment_tick = env
    try:
        from probe_snow_damage import PyProbe                  # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        U.Combatant.take, U.Combatant.heal = orig_take, orig_heal
        cls._environment_tick = orig_env

    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    print(f"\n{'干员':<12} {'累计承伤':>12} {'累计受治':>12} {'净':>12}")
    for n in sorted(set(taken) | set(healed)):
        if only and n != only:
            continue
        a, b = taken.get(n, 0.0), healed.get(n, 0.0)
        print(f"{n:<12} {a:>12,.1f} {b:>12,.1f} {b - a:>12,.1f}")
    if ledger:
        print(f"\n窗口 [{lo}, {hi}] 明细（{len(ledger)} 笔）：")
        for kind, t, n, amt in sorted(ledger, key=lambda r: r[1]):
            print(f"  {t:8.4f} {kind} {n} {amt:,.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
