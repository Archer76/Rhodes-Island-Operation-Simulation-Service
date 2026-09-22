#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：各自练度下的**部署费用**（`deploys[].cost`）。

## 对的是什么

期望值**不是**我另算一遍，而是**生产规格**里 `deploys[].cost`
（`build_spec` 的 `int(operator_of(d).deploy_cost)`）。做法是复用
`check_specgo_go.real_specs()`——那个只抄规格就跑的 `SpecCapture` 子类。

## 为什么这条要单独验

`cost` 其实早就在干员判据的四个整字典里被比过了（679 次折算）。但
`deploys` 要的是**按部署顺序、按各人自己的练度**取出来的那一个数——
顺序与练度来源是新的，而「取错人的费用」在判决上表现为「落地时刻整体偏移」，
不会报错。所以这里按 `char_id` 配对来比。

用法:
    python tools\\check_costof_go.py
    python tools\\check_costof_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER_FIX = ROOT / "fixtures" / "roster_max_modelled.json"


def go_costof(cfgs: list[dict]) -> list[int]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "costof", "spec": cfgs}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["cost_of"]


def main() -> int:
    from check_specgo_go import real_specs
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier

    class Stub:
        _by_name = Verifier._by_name
        _entry = Verifier._entry

        def __init__(self, calc):
            self.calc = calc

    from ak_tactic.operator import OperatorCalculator
    stub = Stub(OperatorCalculator())
    roster = Roster.from_json(ROSTER_FIX)

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：**生产规格**的 deploys[].cost（经 SpecCapture 抄出）")
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    seen: dict[str, int] = {}
    for name, spec, err, _lv in real_specs():
        if spec is None:
            continue
        plan = Plan.from_dict(json.loads(
            (ROOT / "fixtures" / name).read_text(encoding="utf-8-sig")))
        cfgs = []
        want = {}
        for d in plan.deploys:
            e = stub._entry(d, roster)
            cfgs.append({"char_id": e["char_id"], "elite": e["elite"],
                         "level": e["level"], "trust": e.get("trust") or 0,
                         "potential": e.get("potential", 1),
                         "module": e.get("module") or "",
                         "module_level": e.get("module_level") or 0})
        if not cfgs:
            continue
        got = go_costof(cfgs)
        compared += 1
        if mutate and compared == 1 and got:
            got[0] = got[0] + 1
        for c, g in zip(cfgs, got):
            want[c["char_id"]] = g
        #: 按 char_id 与生产规格配对——同一份计划里干员不重复（`validate` 保证）。
        for dep in spec.get("deploys") or []:
            cid = str(dep.get("char_id"))
            if cid not in want:
                bad += 1
                print("✗ 夹具 %s：生产规格里的 %s 在计划里找不到" % (name, cid))
                continue
            if want[cid] != int(dep.get("cost", 0)):
                bad += 1
                print("✗ 夹具 %s %s：Go=%r 生产规格=%r"
                      % (name, cid, want[cid], dep.get("cost")))
            else:
                seen["部署费用逐人一致"] = seen.get("部署费用逐人一致", 0) + 1
        seen["夹具"] = seen.get("夹具", 0) + 1

    print("已比：部署费用；%d 份夹具 × 生产规格的 deploys[].cost" % compared)
    print("★ 行使计数：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if not seen.get("部署费用逐人一致"):
        print("结论：一个人都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    print("结论：%d 份夹具、%d 人次的部署费用与生产规格一致"
          % (compared, seen["部署费用逐人一致"]))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
