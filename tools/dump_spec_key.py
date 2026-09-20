#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把交给 Go 的规格里**某一个顶层键**摘出来看（条数 / 种类分布 / 首条样例）。

为什么要有它：对拍时最常问的一句是"这一项到底送过去了没有"，
而答案有两个面——**机制层**（`spec["mechanisms"]`）与**装置层**（`spec["devices"]`）。
两片面名字相近、内容互不包含（`simgo/mech.py:48` 明确写了
「天桩：召唤物，**不入本层**」），问错面就会得到一个**看着像结论的假答案**：
"不在规格里"其实只是"不在这一层里"。本会话在 `act31side_09` 上正是这么绊了一下。

用法:
    python tools\\dump_spec_key.py out\\plan-hs09.json --key devices --deploys 1
    python tools\\dump_spec_key.py out\\plan-hs09.json --key mechanisms
"""
from __future__ import annotations

import json
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                 # noqa: E402
from parity_plan import GoCapture, compare, resolve      # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    plan_path = args[0]
    key = args[args.index("--key") + 1] if "--key" in args else "devices"
    deploys = int(args[args.index("--deploys") + 1]) if "--deploys" in args else 0
    full = "--full" in args

    #: `compare()` 内部自己 new 一个 `GoCapture`，抓不到它那份；所以这里单独跑一次
    #: ——`GoCapture` 只到 `build_spec` 为止，不启动 Go 进程，代价就是一次原版装载。
    #: ⚠ `compare()` 返回的 `plan` 是**名字串**不是对象（它只拿它做打印），
    #: 所以这里得自己按 `parity_plan.compare` 的同一口径重新装一遍。
    src = resolve(plan_path)
    raw = json.loads(src.read_text(encoding="utf-8"))
    res = compare(plan_path, deploys=deploys, quiet=True)
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))
    cap = GoCapture()
    try:
        cap.run(plan, roster=roster)
    except SystemExit:
        pass
    if not getattr(cap, "held", None):
        print("没扣到规格：GoCapture 没走到 build_spec")
        return 1
    spec = cap.held[1]

    print(f"关卡 {res.get('stage')}｜规格顶层键 {len(spec)} 个："
          f"{sorted(spec.keys())}")
    val = spec.get(key)
    if val is None:
        print(f"⚠ 顶层没有 {key!r} —— 注意：这只说明**这一层没有**，"
              f"不代表这项机制不存在（见本文件抬头）")
        return 1
    if isinstance(val, list):
        print(f"\n{key}: {len(val)} 条")
        print("种类分布:", dict(Counter(
            (x.get("kind") if isinstance(x, dict) else type(x).__name__)
            for x in val)))
        if "--idx" in args:
            #: 点名看第几只：`spawns` 里同名同波的很多，看"首条"常常不是想问的那只
            #: （本会话就因为"首条"与"按 idx 取"不是同一只，白追过一轮）。
            i = int(args[args.index("--idx") + 1])
            if not (0 <= i < len(val)):
                print(f"idx={i} 越界（共 {len(val)} 条）")
                return 1
            print(f"\n[{i}] =", json.dumps(
                val[i], ensure_ascii=False,
                **({} if "--compact" in args else {"indent": 2}))[:6000])
        elif val:
            print("首条:", json.dumps(val[0], ensure_ascii=False)[:900])
    elif isinstance(val, dict):
        print(f"\n{key}: {len(val)} 个键 {sorted(val.keys())}")
        if full:
            print(json.dumps(val, ensure_ascii=False, indent=2)[:4000])
        else:
            print("（加 --full 看内容）")
    else:
        print(f"\n{key} = {val!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
