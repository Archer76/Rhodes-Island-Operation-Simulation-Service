#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Go 的敌人下标与 (名字, 出怪时刻) 对上。

为什么需要：对拍的比对键是 `(名字, round(出怪时刻,3))`，而 Go 的痕迹里只有
下标。两边名字还不总是相同（同名不同波次时更麻烦），所以先建这张对照表，
后面所有"idx=24 是谁"的问题都查它。

用法: python tools\probe_enemy_index.py [k]
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import os
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
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    raw = dict(raw, deploys=raw["deploys"][:k])
    try:
        Thief().run(Plan.from_dict(raw),
                    roster=Roster.from_json(_fixture("roster_max_modelled.json")))
    except SystemExit:
        pass
    spec = Thief.spec
    assert spec is not None

    # 规格里的**出怪表**顺序 = 主循环里的下标顺序（`Enemies()` 按它建视图）。
    #: 键名是 `spawns`（不是 `enemies`）——写错的那次症状是"共 0 只"。
    waves = spec.get("spawns") or []
    if "--idx" in sys.argv:
        i = int(sys.argv[sys.argv.index("--idx") + 1])
        print(f"规格出怪表第 {i} 条（原样）：")
        print(json.dumps(waves[i], ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    print(f"规格出怪表共 {len(waves)} 条；下标 → (名字, 出怪时刻)：")
    for i, e in enumerate(waves):
        print(f"   idx={i:3d}  {e.get('name')}   time={e.get('time')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
