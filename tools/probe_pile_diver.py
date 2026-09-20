#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证：「出怪表刷出来的」天桩-乙，原版到底有没有跑 `_pile_diver_tick`。

这条断言是 `act31side_09` 根因链的枢纽：
* 若**有** ⇒ Go 的 `PileTick` 只管自己 `m.units`（本关为空）就是缺口所在；
* 若**没有** ⇒ 根因另有其处，上一轮的结论要再撤一次。

⚠ 判据必须是**运行时调用了没有**，不是"查表里有没有这个名字"。
查表只是必要条件：`_pile_tick` 的分派是
`elif self._pile_mark_key(e): self._pile_diver_tick(e, t)`，
中间还隔着 `hp>0 / not leaked / not off_map / reborn_at<0` 几道闸门
（`sim.py:4652`）——只看表会漏掉"闸门没放行"这种情形。

用法:
    python tools\\probe_pile_diver.py 1
"""
from __future__ import annotations

import collections
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from probe_windup_phase import load_plan, load_roster            # noqa: E402


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 1
    plan, roster = load_plan(k), load_roster()

    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_pile_tick"))

    #: 表本身也要看：`PILE_MARK` 里有没有 `enemy_1399_dhtb`
    print("PILE_MARK 命中 enemy_1399_dhtb:",
          repr(getattr(S, "PILE_MARK", {}).get("enemy_1399_dhtb")))

    orig = cls._pile_tick
    calls: list[tuple] = []

    def patched(self, dt, t):
        #: 直接盯 `_pile_diver_tick`——比看 `_pile_tick` 的循环更能证明"分派到了"
        r = orig(self, dt, t)
        return r

    orig_div = cls._pile_diver_tick

    def div(self, e, t):
        #: 记下**分派瞬间**的状态，这样"为什么没重设路线"是可回答的：
        #: `idle_timer>0` 是登场自缚、`attacked_once` 是已经咬过一口。
        calls.append((float(t), e.name, str(e.enemy_id),
                      float(getattr(e, "idle_timer", 0.0)),
                      bool(getattr(e, "attacked_once", False)),
                      float(e.position[0]), float(e.position[1]),
                      int(getattr(e, "route_index", -1))))
        return orig_div(self, e, t)

    cls._pile_diver_tick = div
    try:
        from probe_snow_damage import PyProbe                    # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._pile_diver_tick = orig_div
    _ = patched

    print(f"\n[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s"
          f"｜`_pile_diver_tick` 共被调用 **{len(calls)}** 次")
    by_id = collections.Counter(c[2] for c in calls)
    print("按 enemy_id 分布:", dict(by_id))
    #: 冻结的那几次（自缚未过 / 已咬过）单独数出来：它们是"被调用了但没做事"
    frozen = [c for c in calls if c[3] > 0.0 or c[4]]
    print(f"其中 idle_timer>0 或 attacked_once 的（= 什么都不做就返回）：{len(frozen)}")
    if calls:
        print("\n最早 6 次调用（t, 名字, enemy_id, idle, attacked, x, y, route_index）：")
        for c in sorted(calls)[:6]:
            print(f"  t={c[0]:8.4f}  {c[1]:<8} {c[2]:<20} idle={c[3]:.2f} "
                  f"attacked={c[4]} ({c[5]:.4f},{c[6]:.4f}) route={c[7]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
