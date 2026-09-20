#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盯住**某一格的"首敌"什么时候被定下**（原版侧，跨帧比较）。

首敌归属只在某只敌人**第一次**踏入该格时定下，而 Python 的 `enter` 用的是
`first_enemy.setdefault`——理论上那一刻必然写进去。写下不去的唯一可能是
那一刻**提前 return** 了。这个探针把"踏入前 / 踏入后"两边的值都打出来，
提前 return 的那一帧就成了唯一说得通的解释。

用法: python tools\probe_py_first.py 3 --cell 9,2 --from 56.4 --to 58.4
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle import sim as S                        # noqa: E402
from ak_tactic.battle import talents as T                    # noqa: E402
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
    xy = args[args.index("--cell") + 1].split(",") if "--cell" in args else ["9", "2"]
    watch = (int(xy[0]), int(xy[1]))
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9

    state = {"t": 0.0}
    orig_enter = T.SnowField.enter

    def enter(self, enemy_id, cell, atk, damage_fn):
        if cell != watch or not (lo <= state["t"] <= hi):
            return orig_enter(self, enemy_id, cell, atk, damage_fn)
        prev = self.last_cell.get(enemy_id)
        before = self.first_enemy.get(cell)
        layers = self.layers.get(cell)
        out = orig_enter(self, enemy_id, cell, atk, damage_fn)
        after = self.first_enemy.get(cell)
        state.setdefault("seen", set())
        #: 只在"首敌变了"或"层数>0 但首敌还是空"时打——后者正是可疑的那种。
        mark = (before, after, layers)
        if mark in state["seen"]:
            return out
        state["seen"].add(mark)
        name = next((e.name + "@" + str(e.spawn_time)
                     for e in state.get("enemies", []) if id(e) == enemy_id), "?")
        print(f"   t={state['t']:.4f} {name} 踏入 {cell} 上帧={prev} "
              f"层={layers} 首敌 {before}→{after} 返回={out}")
        return out

    T.SnowField.enter = enter

    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_snow_tick"))
    orig_st = cls._snow_tick

    def st(self, dt, t):
        state["t"] = t
        state["enemies"] = self.enemies
        return orig_st(self, dt, t)

    cls._snow_tick = st
    orig_loop = cls.run

    def run_wrapped(self, *a, **kw):
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
