#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""田地层对拍：某一格在两边**是不是田地**、病害值多少、每秒回血多少。

## 为什么需要它

k=4 的形态：怒潮凛冬在 Go 里 100.3 秒倒下、原版活到 205.3 秒，
而她的**每秒承伤两边完全一致**。差的全部在回血：
原版到 100.4 秒为止治了她 **5,010 点 ≈ 50/秒**（田地病害值 0 的恒值回复，
`sim.py:1401-1404`），Go 那边**一点都没有**。

而 Go 的田地回血分支本身写得没问题——所以问题在"**她那格算不算田地**"。
这一层两边的取数路径不同（原版自己建，Go 走 `simgo/mech.py` 送过来的规格），
必须直接把两边的答案问出来，不能靠读代码推断。

用法: python tools\\probe_farmland.py 4 --cell 10,2
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
    cell = args[args.index("--cell") + 1] if "--cell" in args else "10,2"
    cx, cy = (int(v) for v in cell.split(","))
    plan, roster = load_plan(k), load_roster()

    # ---- Go 侧：直接读送过去的规格 ----
    from probe_snow_damage import Thief
    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    farm = spec.get("farmland") or {}
    groups = farm.get("groups") or []
    print(f"[go] 田地规格：{len(groups)} 片，"
          f"每片格数 {[len(g.get('cells') or []) for g in groups]}")
    hit = [i for i, g in enumerate(groups) if [cx, cy] in (g.get("cells") or [])]
    print(f"[go] ({cx},{cy}) 是不是田地：{'是，第 %s 片' % hit if hit else '**不是**'}")

    # ---- 原版侧：问系统本人 ----
    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    seen = {"done": False}
    orig_env = cls._environment_tick

    def env(self, dt, t):
        fs = getattr(self, "farmland", None)
        if fs is not None and not seen["done"]:
            seen["done"] = True
            print(f"[py] (0,0) 是不是田地：{fs.is_farmland(0, 0)}")
            print(f"[py] ({cx},{cy}) 是不是田地：{fs.is_farmland(cx, cy)}")
            print(f"[py] ({cx},{cy}) 每秒回血：{fs.regen_per_second(cx, cy)}")
            print(f"[py] ({cx},{cy}) 每秒伤害：{fs.damage_per_second(cx, cy)}")
            #: 把原版那套田地格集合抠出来（属性名各版本不同，逐个试），
            #: 好与 Go 的格集合做**集合差**——"少哪些格"比"某格在不在"更值钱。
            cells = None
            for name in ("cells", "farmland", "tiles", "all_cells", "index"):
                v = getattr(fs, name, None)
                if isinstance(v, dict) and v:
                    cells = set(v)
                    break
                if isinstance(v, (set, frozenset)) and v:
                    cells = set(v)
                    break
            if cells:
                print(f"[py] 田地格共 {len(cells)} 个（来自 {name}）")
                gocells = {(c[0], c[1]) for g in groups
                           for c in (g.get("cells") or [])}
                print(f"[go] 田地格共 {len(gocells)} 个")
                miss = sorted(cells - gocells)
                extra = sorted(gocells - cells)
                print(f"    原版有 Go 没有 {len(miss)} 格：{miss[:20]}")
                print(f"    Go 有原版没有 {len(extra)} 格：{extra[:20]}")
        return orig_env(self, dt, t)

    cls._environment_tick = env
    try:
        from probe_snow_damage import PyProbe                  # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._environment_tick = orig_env
    print(f"[py] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
