#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""盯住**某一格**的首敌归属与清雪时刻（Go 侧）。

首敌归属决定"这一格的雪什么时候被清掉"，而它只在某个敌人**第一次**踏入
那一格时定下——那一刻往往在几百帧之前。所以要单独盯一格、全程记录。

用法: python tools\probe_snow_cell.py 3 --cell 9,2
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.simgo import build_spec, find_binary            # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


class Thief(GoVerifier):
    spec = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        Thief.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
        raise SystemExit(0)


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    cell = args[args.index("--cell") + 1] if "--cell" in args else "9,2"

    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    raw = dict(raw, deploys=raw["deploys"][:k])
    try:
        Thief().run(Plan.from_dict(raw),
                    roster=Roster.from_json(_fixture("roster_max_modelled.json")))
    except SystemExit:
        pass
    spec = Thief.spec
    assert spec is not None
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1", RIOS_SNOW_CELL=cell,
                                RIOS_SNOW_ALL="1"))
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s")
    #: ⚠ 这里**必须带上 SNOWDROP**：整格清雪只发生在"首敌离场"那一帧，
    #: 而它既不产生伤害也不改层数的中间态——只看 SNOWOWN / SNOWSLOW 会得出
    #: "这一格什么都没发生"的假结论（本轮就是这么误判了一整轮）。
    lines = [ln.strip() for ln in (p.stderr or "").splitlines()
             if "SNOWDROP" in ln
             or ("SNOWOWN" in ln or "SNOWSLOW" in ln)
             and f"cell=[{' '.join(cell.split(','))}]" in ln]
    print(f"cell {cell} 相关痕迹 {len(lines)} 笔：")
    for ln in lines[:60]:
        print("   " + ln)
    #: 乘区痕迹里这一格出现的时刻范围 = 这一格"有雪"的区间（近似）
    slow = [re.search(r"t=([\d.]+)", ln).group(1) for ln in lines if "SNOWSLOW" in ln]
    if slow:
        print(f"   这一格的乘区痕迹：{len(slow)} 笔，"
              f"t={float(slow[0]):.4f} … {float(slow[-1]):.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
