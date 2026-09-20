#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把某一手规格里每位干员的**关键字段**打出来（排障用，不参与对拍）。

用途：当"某位干员什么都没做"时，第一个要排除的就是"规格根本没把该送的字段送来"。
本仓库已经栽过好几次：字段有、消费点没有（假完成），或者消费点有、字段没送
（静默不生效）。两边都要看，不能只看一边。

用法: python tools\\dump_op_spec.py 4 [--idx 3]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: ⚠ 规格是**蛇形**键（`max_hp` / `block_cnt` / `heals`），不是 Go 结构体的
#: 驼峰名。第一版按驼峰写，于是每位干员都打出 `{}`——"字段没送"与"我查错了键"
#: 长得一模一样，这正是本仓库反复踩的那个坑。
FIELDS = ("heals", "max_hp", "atk", "def", "res", "interval", "block_cnt",
          "range", "skill", "blessing_save", "blessing_self_freeze")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 4
    only = int(args[args.index("--idx") + 1]) if "--idx" in args else None

    from probe_snow_damage import Thief
    from probe_windup_phase import load_plan, load_roster
    thief = Thief()
    try:
        thief.run(load_plan(k), roster=load_roster())
    except SystemExit:
        pass
    _sim, spec = thief.held
    ops = spec.get("operators") or []
    print(f"k={k}：{len(ops)} 位干员的规格")
    for i, op in enumerate(ops):
        if only is not None and i != only:
            continue
        keys = [f for f in FIELDS if f in op]
        brief = {f: op[f] for f in keys if f != "range"}
        print(f"\n[{i}] {op.get('name')}")
        print(f"    {json.dumps(brief, ensure_ascii=False)}")
        rng = op.get("range")
        if rng is not None:
            print(f"    Range({len(rng)} 格)={rng}")
        extra = sorted(set(op) - set(FIELDS) - {"name"})
        print(f"    其它键：{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
