#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把积雪这一族的**全部输入**从真夹具里 dump 出来（走 SpecThief 那条路）。

为什么要走 SpecThief：`Simulation` 的构造与 `plan()` 调用都在 `Verifier.run`
内部，想拿到"**排完程、还没跑**"的那个 sim，唯一干净的入口是重写
`_run_other_engine`——那里正好拿到 sim/plan/stage/deployed，而且还没跑。

要看的三件事：
  1. 积雪天赋的几个数（interval / max_cast_cnt / move_speed / talent_magic_scale）；
  2. 干员射程内的**可行走格**有多少（雪只铺在可行走格上）；
  3. 技能开启时那两个值从哪读（`skill.effects.other` 上的黑板键）。

用法: python tools\probe_snow_inputs.py [k]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle.talents import find_snow                 # noqa: E402
from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.simgo import build_spec                         # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


def load_plan(k: int) -> Plan:
    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    if k:
        raw = dict(raw, deploys=raw["deploys"][:k])
    return Plan.from_dict(raw)


def load_roster() -> Roster:
    return Roster.from_json(_fixture("roster_max_modelled.json"))


class Thief(GoVerifier):
    """排完程、还没跑的那一刻，把现场扣住。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.held = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None):
        self.held = (sim, plan, stage, deployed)
        raise SystemExit(0)


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 8
    thief = Thief()
    try:
        thief.run(load_plan(k), roster=load_roster())
    except SystemExit:
        pass
    assert thief.held, "没扣住现场"
    sim, plan, stage, deployed = thief.held

    mp = stage.map
    walkable = sum(1 for y in range(mp.height) for x in range(mp.width) if mp.walkable(x, y))
    print(f"关卡 {stage.code}")
    print(f"snow_freeze 开关 = {getattr(sim, 'snow_freeze', None)}"
          f"   （原版判满层冻结时读的字段）")
    print(f"地图 {mp.width}×{mp.height}，可行走格 {walkable}")
    print(f"部署结算**之前**的 snow_fields = {len(sim.snow_fields)}  ← 闸门读到的就是它")
    print(f"排程 {len(sim.deployments)} 条\n")

    print("=== 每条排程的积雪相关输入 ===")
    for i, d in enumerate(sim.deployments, start=1):
        op = d.operator
        pos = (int(d.position[0]), int(d.position[1]))
        tal = getattr(op, "talents", None) or []
        snow = find_snow(tal)
        print(f"\n{i}. {op.char_id} ({op.name}) 落点 {pos} 朝向 {d.direction} skill={d.skill!r}")
        if snow is None:
            print("   积雪天赋：无")
            continue
        print(f"   积雪天赋 {snow.name!r}")
        print(f"     interval           = {snow.value('interval', 10.0)}")
        print(f"     max_cast_cnt       = {snow.value('max_cast_cnt', 5)}")
        print(f"     move_speed（取绝对值）= {abs(snow.value('move_speed', 0.0))}")
        print(f"     talent_magic_scale = {snow.value('talent_magic_scale', 0.0)}")
        print(f"     黑板全键 = {sorted((snow.blackboard or {}).keys())}")
        # 射程内的可行走格：雪**只铺在这些格上**
        op.position = pos
        op.direction = d.direction
        cells = sim._range_of(op)
        ground = [c for c in cells if mp.walkable(*c)]
        print(f"     射程 {len(cells)} 格，其中可行走 {len(ground)} 格")
        sk = getattr(op, "skill", None)
        if sk is None:
            print("     技能：无（技能2 的扩散与每秒伤害都不会发生）")
        else:
            eff = getattr(sk, "effects", None)
            other = (getattr(eff, "other", None) or {}) if eff is not None else {}
            print(f"     技能 {getattr(sk, 'name', '?')!r} duration={getattr(sk, 'duration', None)}")
            keys = sorted(other.keys())
            print(f"     黑板键共 {len(keys)} 个，含 cast/magic_scale/s2 的："
                  f"{[x for x in keys if 'cast' in x or 'magic_scale' in x or 's2' in x]}")
        print(f"     spread_cap（技能期）= {int(((getattr(getattr(sk, 'effects', None), 'other', {}) or {}).get('talent@max_cast_tile_count') or 0)) if sk else 0}")
        print(f"     dot_scale（技能期）= {float(((getattr(getattr(sk, 'effects', None), 'other', {}) or {}).get('talent@s2_magic_scale') or 0.0)) if sk else 0.0}")

    print("\n=== Go 规格里的现状 ===")
    spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
    print(f"unsupported = {spec.get('unsupported')}")
    print(f"mechanisms  = {spec.get('mechanisms')}")
    snow = (spec.get("mech_config") or {}).get("snow.field")
    if snow:
        print(f"积雪规格：freeze={snow['freeze']}  片数={len(snow['fields'])}"
              f"  终点格={snow['goal_cells']}")
        for f in snow["fields"]:
            print(f"  {f['owner']} @{f['cell']} operator_index={f.get('operator_index')}"
                  f" 可行走格={len(f['ground'])}"
                  f" interval={f['interval']} max_layers={f['max_layers']}"
                  f" slow={f['slow_per_layer']} magic={f['magic_scale']}")
            print(f"     ground = {f['ground']}")
        print(f"  相邻表 {len(snow['neighbours'])} 个键")
        print(f"  规格 operators 共 {len(spec.get('operators') or [])} 位："
              f"{[o.get('char_id') for o in (spec.get('operators') or [])]}")
    else:
        print("积雪规格：无")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
