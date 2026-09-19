# -*- coding: utf-8 -*-
"""只读：把「去蚀@54.0」的移速档位阶梯打出来（原版）。

判据用**每帧位移**与 `speed_multiplier` 一起看：积雪的减速是逐层叠上去、
到顶后**续最老那层**（总量维持封顶），所以阶梯是 1.0 → 0.88 → 0.76 → 0.64 …
还是先掉再加，一眼能看出来。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import probe_windup_phase as P                          # noqa: E402

KEY = sys.argv[1] if len(sys.argv) > 1 else "去蚀@54.0"
name, _, spawn = KEY.partition("@")
want = (name, round(float(spawn), 3))

frames, verdict, _atk = P.run_python(P.load_plan(3), P.load_roster())
seq = [f for f in frames if f["key"] == want]

print(f"{KEY}  原版判决 {verdict.kills}杀{verdict.leaks}漏 {verdict.elapsed:.3f}s")
print(f"{'t':>9} {'x':>11} {'Δx':>10} {'speed_mult':>10} {'move':>6} {'haste':>6} "
      f"{'sluggish':>9} {'blocked':>8}")
prev = None
last = None
for f in seq:
    d = (f["x"] - prev["x"]) if prev is not None else 0.0
    key = (round(f["speed_mult"], 4), round(f["haste"], 4), f["blocked"],
           round(f["sluggish"], 2))
    if key != last:                       # 只打"档位变了"的那些帧
        print(f"{f['t']:9.4f} {f['x']:11.7f} {d:10.7f} {f['speed_mult']:10.4f} "
              f"{f['move_speed']:6.3f} {f['haste']:6.4f} {f['sluggish']:9.3f} "
              f"{str(f['blocked']):>8}")
        last = key
    prev = f
