# -*- coding: utf-8 -*-
"""一次性对账：直接把某个时刻的坐标打出来，看"分歧从哪一帧起"。

`probe_windup_phase.py --first` 报的是**窗口内**最早那条位移差；真要找"位置第一次
分开"，得把两边同一帧的 x/y 直接相减——本脚本就干这一件事。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from probe_windup_phase import load_plan, load_roster, run_go, run_python  # noqa: E402

k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
tol = float(sys.argv[2]) if len(sys.argv) > 2 else 1e-6

plan = load_plan(k)
roster = load_roster()
py, pv, _pa = run_python(plan, roster)
_got, go, _ga = run_go(plan, roster)

pyat = {(f["key"], round(f["t"], 4)): f for f in py}
goat = {(f["key"], round(f["t"], 4)): f for f in go}

found = 0
for key in sorted(set(pyat) & set(goat), key=lambda x: (x[1], x[0][1])):
    a, b = pyat[key], goat[key]
    d = abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])
    if d > tol:
        found += 1
        if found <= 8:
            print(f"{key[0][0]}@{key[0][1]} t={key[1]:.4f}  "
                  f"py x={a['x']:.7f} go x={b['x']:.7f} 差={a['x'] - b['x']:+.7f}  "
                  f"py speed_mult={a['speed_mult']:.4f} haste={a['haste']:.4f} "
                  f"slow_pct={a['slow_pct']:.4f} lock_slow={a['lock_slow']:.4f} "
                  f"move={a['move_speed']:.4f}")
print(f"共 {found} 条坐标分开（容差 {tol:g}）")

# 参考：这只敌人在分歧前后几帧的原版移速分量（看是谁改了速度）
if found:
    key0 = sorted(set(pyat) & set(goat), key=lambda x: (x[1], x[0][1]))
    first = next(k for k in key0
                 if abs(pyat[k]["x"] - goat[k]["x"]) + abs(pyat[k]["y"] - goat[k]["y"]) > tol)
    ident, t0 = first
    print(f"\n{ident[0]}@{ident[1]} 在 t={t0:.4f} 前后各 12 帧的原版移速分量")
    print(f"{'t':>9} {'x':>11} {'speed_mult':>10} {'haste':>7} {'slow_pct':>9} "
          f"{'lock_slow':>10} {'move':>7} {'root':>6} {'idle':>6} {'sluggish':>9}")
    for k in key0:
        if k[0] != ident or not (t0 - 0.45 <= k[1] <= t0 + 0.45):
            continue
        f = pyat[k]
        print(f"{k[1]:9.4f} {f['x']:11.7f} {f['speed_mult']:10.4f} {f['haste']:7.4f} "
              f"{f['slow_pct']:9.4f} {f['lock_slow']:10.4f} {f['move_speed']:7.4f} "
              f"{f['root']:6.3f} {f['idle']:6.3f} {f['sluggish']:9.3f}")
