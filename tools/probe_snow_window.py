#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两类痕迹**按时刻窗口**拉出来对。

`probe_snow_trace.py` 只打"前 20 + 末 3 笔"，而真正出事的那一帧往往在中间。
这里按 `--from/--to` 过筛，再把 `SNOWT`（计时器算术）与 `SNOWCAST`（施放）并排看——
"计时器跌破 interval 的那一刻发生了什么"只有并排才看得出。

用法: python tools\probe_snow_window.py [k] --from 56.3 --to 56.9
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
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    tags = args[args.index("--tags") + 1].split(",") if "--tags" in args else None

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
    env = dict(os.environ, RIOS_TRACE="1")
    #: Go 侧那些"逐帧每敌一行"的痕迹按窗口收（见 `RIOS_SNOW_DBG`），
    #: 免得几万行洪水把真正要看的那几帧冲掉。
    env["RIOS_SNOW_DBG"] = f"{lo},{hi}"
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=env)
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s")

    kept = []
    for ln in (p.stderr or "").splitlines():
        if tags and not any(re.search(rf"(^|\s){re.escape(x)}\b", ln) for x in tags):
            continue
        m = re.search(r"t=([\d.]+)", ln)
        if not m:
            continue
        t = float(m.group(1))
        if lo <= t <= hi:
            kept.append(ln.strip())
    print(f"窗口 [{lo}, {hi}] 内 {len(kept)} 笔：")
    for ln in kept:
        print("   " + ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
