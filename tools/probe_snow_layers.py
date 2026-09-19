#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""只看**有雪的格**上的 `enter` 调用（Probe 的补充视角）。

为什么需要它：`enter` 会在**每一格**上被调用（没雪也调，因为要记 `last_cell`），
所以"调用次数"这个指标分不出"雪积起来了没有"。这里把 `layers>0` 的那些筛出来
——那才是真正该产生踏入伤害的调用。

用法: python tools\probe_snow_layers.py [k]
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
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spec = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
        raise SystemExit(0)


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    raw = dict(raw, deploys=raw["deploys"][:k])
    thief = Thief()
    try:
        thief.run(Plan.from_dict(raw),
                  roster=Roster.from_json(_fixture("roster_max_modelled.json")))
    except SystemExit:
        pass
    spec = thief.spec
    assert spec is not None
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s")

    lines = [ln for ln in (p.stderr or "").splitlines() if "SNOWENTER" in ln]
    with_snow = []
    for ln in lines:
        m = re.search(r"t=([\d.]+).*layers=(\d+)", ln)
        if m and int(m.group(2)) > 0:
            with_snow.append((float(m.group(1)), int(m.group(2)), ln.strip()))
    print(f"`enter` 共 {len(lines)} 笔，其中**层数 > 0** 的 {len(with_snow)} 笔")
    if with_snow:
        print(f"  首笔有雪 t={with_snow[0][0]:.4f} 层数={with_snow[0][1]}")
        for t, n, ln in with_snow[:10]:
            print("   " + ln)
    else:
        # 没雪就把"最后一次调用"和最大层数亮出来，好判断是没积起来还是格不对
        mx = 0
        for ln in lines:
            m = re.search(r"layers=(\d+)", ln)
            if m:
                mx = max(mx, int(m.group(1)))
        print(f"  ⚠ 一笔都没有：说明雪**从来没积到任何敌人脚下的格**上。"
              f"全程最大层数={mx}")
        for ln in lines[-4:]:
            print("   末笔 " + ln.strip())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
