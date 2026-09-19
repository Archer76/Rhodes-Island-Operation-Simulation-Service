# -*- coding: utf-8 -*-
"""只读盘点：HS-EX-8 作业逐手加了谁，谁带「积雪」天赋。

用来回答两个问题：① 为什么 k=1/k=2 能一致而 k≥3 不能；② 修完闸门之后
k≥3 会变成「退回原版」（说明还缺 Go 侧实现），还是本来就能对上。
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

import json                                            # noqa: E402
from ak_tactic.battle.talents import SNOW_KEYS, is_snow_talent  # noqa: E402

FIX = pathlib.Path("out/hsex8_max.json")
if not FIX.exists():
    FIX = pathlib.Path("../ak-tactic-head/out/hsex8_max.json")
plan = json.loads(FIX.read_text(encoding="utf-8"))

print(f"夹具: {FIX}")
print(f"积雪天赋指纹键 = {SNOW_KEYS}")
print()
for i, d in enumerate(plan.get("deploys", []), 1):
    op = d.get("operator") or d.get("name")
    tal = d.get("talents") or []
    names = [t.get("name") for t in tal]
    snow = [t.get("name") for t in tal if set(SNOW_KEYS) <= set(t.get("blackboard", {}))]
    print(f"  第{i}手 {op:<8} @{d.get('time')} {d.get('position')} "
          f"技能={d.get('skill')} 天赋={names}"
          + (f"   ← 积雪: {snow}" if snow else ""))
