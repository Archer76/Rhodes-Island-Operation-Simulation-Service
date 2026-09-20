#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原版田地**逐拍**探针：某一格每秒的 `ticks` / `actual` / 每秒伤害。

## 为什么需要它

HS-7 上银灰（4 号位）在原版 **t=62.0 阵亡**，Go 侧**没有这条死亡事件**；
承伤逐笔显示差在**第一笔**：原版 62.0 那一拍扣 **505.0**，Go 从 63.0 才开始、
每笔 155~176（两边 63.0 起逐笔相同）。原版 11 拍、Go 10 拍。

所以问题不是"每秒伤害算错了"，而是**62.0 这一拍**：
要么 Go 少算了一拍，要么这一拍的病害值两边不同。
`_environment_tick` 里那一笔是 `op.take(dmg * ticks)`——
"dmg 多少"和"ticks 几次"必须分开看，`ticks` 是**整秒累加器**，
与敌人那次结算共用同一个 `_env_timer`，所以两个量得同时读出来才能定性。

用法:
    python tools\\probe_py_farmtick.py 0 --cell 1,3 --from 58 --to 65
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from probe_windup_phase import load_plan, load_roster          # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 0
    cell = args[args.index("--cell") + 1] if "--cell" in args else "1,3"
    cx, cy = (int(v) for v in cell.split(","))
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    plan, roster = load_plan(k), load_roster()

    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig_env = cls._environment_tick
    state = {"t": -1.0, "n": 0, "patched": False}

    #: 用可变容器装原方法：`nonlocal`/`global` 在两层闭包里容易指错对象，
    #: 而指错的表现是 `orig_dps` 为 None → 整个对拍崩在调用点上。
    hold = {"dps": None}

    def dmg_of(self, x, y):
        r = hold["dps"](self, x, y)
        if lo - 0.05 <= state["t"] <= hi and (x, y) == (cx, cy):
            print(f"      · damage_per_second({x},{y}) = {r:.2f}"
                  f"   [t={state['t']:.4f} 计时器={state['timer']!s}]")
        return r

    def env(self, dt, t):
        fs = getattr(self, "farmland", None)
        sim_holder[0] = self
        #: 只在**结算之前**读：`_environment_tick` 内部会把 `_env_timer` 减掉，
        #: 之后再看就只剩余量，"这一拍是几次"就丢了。
        timer = getattr(self, "_env_timer", None)
        state["t"], state["timer"] = t, timer
        if fs is not None and not state["patched"]:
            #: `damage_per_second` 在这段里会被调用**不止一次**（泵水前/后各一次，
            #: 敌人侧还要再来一次）。差 505 这种东西只能来自"调用了几次 × 每次多少"，
            #: 所以把每一次调用都记下来，而不是只看开头那一次。
            hold["dps"] = type(fs).damage_per_second
            type(fs).damage_per_second = dmg_of
            state["patched"] = True
        if fs is not None and lo <= t <= hi and fs.is_farmland(cx, cy):
            d = fs.damage_per_second(cx, cy)
            r = fs.regen_per_second(cx, cy)
            ticks = int(timer + dt) if isinstance(timer, float) else "?"
            ops = [f"{o.name}@{tuple(o.position)} hp={o.hp:.0f} alive={o.alive}"
                   for o in getattr(self, "operators", ())]
            state["n"] += 1
            print(f"t={t:8.4f} 计时器={timer!s:>7} 本拍ticks={ticks}"
                  f" 每秒伤害={d:8.2f} 每秒回血={r:5.1f}")
            for line in ops:
                print(f"        干员 {line}")
        return orig_env(self, dt, t)

    cls._environment_tick = env

    #: 伤害入口也钩住：`_environment_tick` 的干员循环里那一笔是 `op.take(dmg*ticks)`，
    #: 而"这一拍到底结算了几个 ticks、dmg 是多少"要**在扣血那一瞬**读才作数——
    #: 在函数开头读到的 timer 与真正用上的 ticks 之间隔着 `pump_once`。
    from ak_tactic.battle import unit as U
    orig_take = U.Combatant.take

    def take(self, amount):
        before = self.hp
        r = orig_take(self, amount)
        nm = getattr(self, "name", None)
        if nm and lo - 0.05 <= state["t"] <= hi and r > 0:
            print(f"      ★ take {nm} hp {before:.1f} → {self.hp:.1f}"
                  f"（扣 {r:.1f}，请求 {amount:.1f}）  [t={state['t']:.4f}"
                  f" 计时器={state['timer']!s}]")
        return r

    U.Combatant.take = take

    #: 部署与泵水都钩住：`_environment_tick` 开头那份名册里**没有**银灰，
    #: 可这一拍里它却挨了 505——名册只能在**调用内部**变。
    #: `fs.tick(dt)` 与 `pump_once(...)` 是仅有的两件事，逐个看。
    from ak_tactic.battle import environment as E
    orig_pump = E.pump_once

    def pump(fs, devices, ally_cells=None):
        if lo - 0.05 <= state["t"] <= hi:
            print(f"      ~ pump 之前 操作员="
                  f"{[getattr(o, 'name', '?') for o in sim_holder[0].operators]}")
        r = orig_pump(fs, devices, ally_cells=ally_cells)
        if lo - 0.05 <= state["t"] <= hi:
            print(f"      ~ pump 之后 操作员="
                  f"{[getattr(o, 'name', '?') for o in sim_holder[0].operators]}")
        return r

    E.pump_once = pump
    sim_holder = [None]
    cls_orig_deploy = cls._do_deploy if hasattr(cls, "_do_deploy") else None
    if cls_orig_deploy is not None:
        def do_deploy(self, d, t):
            if lo - 0.05 <= t <= hi:
                print(f"      + _do_deploy t={t:.4f} op={getattr(d, 'operator', d)}")
            return cls_orig_deploy(self, d, t)
        cls._do_deploy = do_deploy

    try:
        from probe_snow_damage import PyProbe                  # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._environment_tick = orig_env
        U.Combatant.take = orig_take
    print(f"窗口内 {state['n']} 拍；原版 {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
