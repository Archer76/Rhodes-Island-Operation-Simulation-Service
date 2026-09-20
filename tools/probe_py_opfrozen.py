#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员**冻结/晕眩/闭锁**计时器的来源追踪（原版侧）。

## 为什么需要它

原版 `_operators_attack` 开头有三道"出不了手"的闸门（`sim.py:3973-3983`）：

    if op.stun_timer   > 0: continue        # 晕眩
    if op.freeze_timer > 0: continue        # 冻结（= 缴械，但不掉阻挡）
    if op.locked_timer > 0: continue        # 闭锁（泥岩技3 的前 10 秒）

Go 侧**这三种状态一个都没有**。于是"原版某一帧没出手、Go 出手了"这种偏差，
在 Go 的痕迹里**没有任何东西可看**——它连"我少了这道闸门"都不会报。
本探针把原版那三个计时器的**变化时刻**打出来，好指认"是哪来的、持续多久"。

HS-EX-8 第 3 手实测：圣聆初雪在 t≈64.4 被冻 4 秒，正好吃掉 65.0 / 67.0 两次出手，
Go 因此多打了 2 笔 696（= 1,392 点，正好是总伤害的残差）。

用法: python tools\\probe_py_opfrozen.py 3 --op 圣聆初雪 --from 60 --to 72
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from probe_windup_phase import load_plan, load_roster          # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    target = args[args.index("--op") + 1] if "--op" in args else "圣聆初雪"
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    plan, roster = load_plan(k), load_roster()

    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig_env = cls._environment_tick
    prev: dict[int, tuple] = {}

    def env(self, dt, t):
        r = orig_env(self, dt, t)
        if lo <= t <= hi:
            for op in getattr(self, "operators", ()) or ():
                if getattr(op, "name", None) != target:
                    continue
                now = (round(op.freeze_timer, 4), round(op.stun_timer, 4),
                       round(op.locked_timer, 4))
                if prev.get(id(op)) != now:
                    prev[id(op)] = now
                    #: 只在**变化时**打：逐帧打会在 30fps 下淹掉真正的变化点。
                    print(f"  t={t:8.4f} {target} freeze={now[0]:6.4f} "
                          f"stun={now[1]:6.4f} locked={now[2]:6.4f} "
                          f"hp={op.hp:.1f} alive={op.alive}")
        return r

    cls._environment_tick = env
    try:
        from probe_snow_damage import PyProbe                  # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._environment_tick = orig_env
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
