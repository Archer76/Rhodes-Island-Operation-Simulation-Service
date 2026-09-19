#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""积雪对拍：把**总伤害**这一项拉出来看。

为什么盯"总伤害"：判决那一组（杀/漏/用时）在机制有偏差时是**粗指标**——
它只在偏差累积到改变胜负时才动。而积雪的每一种错法（少一次踏入伤害、
层数上限算错、首敌清雪规则反了）都**先**体现在总伤害上，量级还是可加的。

用法: python tools\probe_snow_damage.py [k]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.simgo import build_spec, find_binary            # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402
from ak_tactic.verify import Verifier                          # noqa: E402
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
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.held = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.held = (sim, build_spec(SpecInputs.from_sim(sim), allow_devices=True))
        raise SystemExit(0)


class PyProbe(Verifier):
    """跑原版，但把 verbose 打开并顺手扣住 sim。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.sim = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.sim = sim
        res = sim.run(max_time=900.0)
        self.res = res
        return self._verdict(plan, stage, sim, res, deployed, title=title)


def main() -> int:
    k = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    plan, roster = load_plan(k), load_roster()

    # ---- 原版（verbose）：日志里每一笔积雪伤害都点名 ----
    pv = PyProbe(verbose=True)
    v = pv.run(plan, roster=roster)
    log = list(getattr(v.result, "log", []) or [])
    snow_lines = [ln for ln in log if "积雪" in ln]
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s"
          f"  总伤害={v.result.damage_dealt:,.1f}")
    print(f"  日志 {len(log)} 行，其中「积雪」{len(snow_lines)} 行")
    for ln in snow_lines[:14]:
        print(f"    {ln}")
    if len(snow_lines) > 14:
        print(f"    …… 共 {len(snow_lines)} 行，末 3 行：")
        for ln in snow_lines[-3:]:
            print(f"    {ln}")

    # ---- Go：同一个规格，直接从回执里读 ----
    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    sim2, spec = thief.held
    from ak_tactic.simgo.client import Simgo
    with Simgo(find_binary()) as cli:
        got = cli.sim(spec)
    print(f"\n[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s"
          f"  总伤害={float(got.get('damage_dealt') or 0.0):,.1f}")
    #: 机制状态快照：判决是粗指标，"雪积到了哪些格、积了几层"才是能逐项比的量。
    st = (got.get("mech_state") or {}).get("snow.field")
    if st:
        for f in st.get("fields") or []:
            cells = f.get("cells") or []
            print(f"  雪片 {f.get('owner')}：{len(cells)} 格  计时器={f.get('timer'):.4f}")
            print(f"    {cells}")
    else:
        print("  ⚠ Go 回执里没有 mech_state['snow.field']")
    print(f"  规格：mechanisms={spec.get('mechanisms')}")
    print(f"  积雪规格里的雪片数="
          f"{len(((spec.get('mech_config') or {}).get('snow.field') or {}).get('fields') or [])}")
    print(f"  差异：杀 {got['kills'] - v.kills:+d}  漏 {got['leaks'] - v.leaks:+d}"
          f"  用时 {got['elapsed'] - v.elapsed:+.3f}s"
          f"  伤害 {float(got.get('damage_dealt') or 0.0) - v.result.damage_dealt:+,.1f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
