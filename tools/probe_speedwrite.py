# -*- coding: utf-8 -*-
"""只读排查：原版是谁把 `speed_multiplier` 从 1.0 写成 0.76 的。

做法：给 `EnemyUnit` 实例挂属性写入监视（`object.__setattr__` 记录调用栈）。
只观测、不改判定，退出时把监视摘掉。
"""
from __future__ import annotations

import pathlib
import sys
import traceback

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import probe_windup_phase as P                      # noqa: E402
from ak_tactic.battle import sim as S               # noqa: E402
from ak_tactic.battle import unit as U              # noqa: E402

plan = P.load_plan(3)
roster = P.load_roster()

hits: list[str] = []
orig_setattr = U.EnemyUnit.__setattr__


def watcher(self, name, value):
    if name == "speed_multiplier":
        old = self.__dict__.get("speed_multiplier")
        if value != old and abs(float(value) - 1.0) > 1e-12:
            hits.append(
                f"t≈{getattr(self, 'sim_t', '?')} {self.name}@"
                f"{self.spawn_time} {old} → {value}")
            if len(hits) <= 3:
                print(f"\n=== speed_multiplier {old} → {value}  "
                      f"（{self.name}@{self.spawn_time}）===")
                traceback.print_stack(limit=12)
    return orig_setattr(self, name, value)


U.EnemyUnit.__setattr__ = watcher

orig_env = S.BattleSimulator._environment_tick


def env_hook(self, dt, t):
    for e in self.enemies:
        e.sim_t = t
    return orig_env(self, dt, t)


S.BattleSimulator._environment_tick = env_hook

try:
    P.run_python(plan, roster)
finally:
    U.EnemyUnit.__setattr__ = orig_setattr

print(f"\n非 1.0 写入次数 = {len(hits)}")
for h in hits[:20]:
    print("  ", h)
