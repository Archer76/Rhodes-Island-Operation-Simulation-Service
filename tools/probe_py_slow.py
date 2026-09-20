#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 `_snow_tick` 里**对某一只敌人的那一段**逐帧打出来（原版侧）。

为什么值得单独一个探针：`speed_multiplier` 与积雪层数、可行走判定、施放者
存活三件事纠缠在一起，而"乘区为什么是 1.0"这个问题的答案只在那几行里。
判决与日志都看不出它——它们是粗指标。

用法: python tools\probe_py_slow.py 3 --enemy 去蚀 --spawn 54.0 --from 72.16 --to 72.3
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle import sim as S                        # noqa: E402
from ak_tactic.plan import Plan, Roster                      # noqa: E402
from ak_tactic.verify import Verifier                        # noqa: E402


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    enemy = args[args.index("--enemy") + 1] if "--enemy" in args else "去蚀"
    spawn = float(args[args.index("--spawn") + 1]) if "--spawn" in args else 54.0
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    watch_cell = None
    if "--cell" in args:
        xy = args[args.index("--cell") + 1].split(",")
        watch_cell = (int(xy[0]), int(xy[1]))

    state = {"t": 0.0, "n": 0}
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_snow_tick"))
    orig = cls._snow_tick

    def st(self, dt, t):
        state["t"] = t
        state["n"] += 1
        #: ⚠ **帧首四闸门**：`enter` 不再被调时，"为什么"只藏在这几个 `continue` 里
        #: （`sim.py:1135` 离场三态、`:1140` 非可行走、`:1146` 施放者不在场）。
        #: 只看 `enter` 的痕迹会得出"这只敌人凭空消失了"——本轮就是这么被卡住的：
        #: 它 hp 一点没掉、格也可走，却不再出现在 `enter` 里。
        if state.get("enemies") and lo <= t <= hi:
            mm = state.get("map")
            for sf in (getattr(self, "snow_fields", None) or []):
                op = sf.operator
                print(f"[雪片] t={t:.4f} owner={sf.owner} "
                      f"op={getattr(op, 'name', None)} "
                      f"alive={getattr(op, 'alive', None)} "
                      f"hp={getattr(op, 'hp', 0.0):.1f} 层数={len(sf.layers)} "
                      f"计时={sf.timer:.4f}")
            for e in state["enemies"]:
                if e.name == enemy and abs(e.spawn_time - spawn) < 1e-6:
                    c = (int(round(e.position[0])), int(round(e.position[1])))
                    print(f"[帧首] t={t:.4f} {e.name}@{e.spawn_time} "
                          f"alive={e.alive} leaked={e.leaked} off_map={e.off_map} "
                          f"pos=({e.position[0]:.4f},{e.position[1]:.4f}) cell={c} "
                          f"可走={mm.walkable(*c) if mm else '?'} hp={e.hp:.1f}")
        return orig(self, dt, t)

    cls._snow_tick = st
    #: 直接包 `SnowField.enter`：只有它被调用时才说明这一段走到了。
    from ak_tactic.battle import talents as T
    orig_enter = T.SnowField.enter

    def enter(self, enemy_id, cell, atk, damage_fn):
        #: 盯任意一格：把"谁踏入、谁被记为首敌、谁把这格的雪清掉"全程记下来。
        #: 首敌归属决定清雪时刻，而它只在**第一次**踏入时定下——不专门盯住
        #: 那一格，那一刻就是几百帧之前的一行，翻不回来。
        if "--cell" in args and cell == watch_cell and lo <= state["t"] <= hi:
            for e in state.get("enemies", []):
                if id(e) == enemy_id:
                    print(f"   t={state['t']:.4f} {e.name}@{e.spawn_time} "
                          f"踏入 {cell} 上帧={self.last_cell.get(enemy_id)} "
                          f"层={self.layers.get(cell)} "
                          f"（踏入前）首敌={self.first_enemy.get(cell)}")
                    break
        for e in state.get("enemies", []):
            if id(e) == enemy_id and e.name == enemy and \
                    abs(e.spawn_time - spawn) < 1e-6 and lo <= state["t"] <= hi:
                m = state.get("map")
                #: ⚠ **必须把 `e.frozen` 一起打出来**：`层=5` 只说明"按规则该冻"，
                #: 冻没冻是另一个事实。冻结一旦成立，`advance` 直接返回、这只敌人
                #: 永远离不开那一格 → 那一格的雪也永远清不掉（首敌不走就不清）。
                #: 于是"满层格上的敌人"是个**自锁**：判错的代价不是慢一帧，是停住。
                print(f"   t={state['t']:.4f} enter cell={cell} "
                      f"pos=({e.position[0]:.4f},{e.position[1]:.4f}) hp={e.hp:.1f} "
                      f"层={self.layers.get(cell)} 返回前乘区={e.speed_multiplier:.4f} "
                      f"frozen={e.frozen} freeze_timer={e.freeze_timer:.4f} "
                      f"可行走={m.walkable(*cell) if m else '?'} "
                      f"施放者存活={getattr(self.operator, 'alive', None)}")
        return orig_enter(self, enemy_id, cell, atk, damage_fn)

    T.SnowField.enter = enter
    orig_loop = cls.run

    def run_wrapped(self, *a, **kw):
        state["map"] = self.stage.map
        state["enemies"] = self.enemies
        return orig_loop(self, *a, **kw)

    cls.run = run_wrapped

    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    raw = dict(raw, deploys=raw["deploys"][:k])
    v = Verifier().run(Plan.from_dict(raw),
                       roster=Roster.from_json(_fixture("roster_max_modelled.json")))
    print(f"原版 {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
