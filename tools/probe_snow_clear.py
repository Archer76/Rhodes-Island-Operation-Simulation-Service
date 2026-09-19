#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把 Go 侧**全部**清格/不清格/离场摘记账的痕迹倒出来，按格筛（默认不过筛）。

为什么要单独一个：`probe_snow_cell.py` 走的是 `RIOS_SNOW_CELL` 单格门控，
而"这条痕迹到底有没有触发过"这个问题**不能用门控本身来回答**——
门控坏了的话，答案是"没触发过"，看起来跟"机制没走到"一模一样。
所以这里用 `RIOS_SNOW_ALL=1` 把全部打出来，再到 **Python 侧**过筛。

用法:
  python tools\\probe_snow_clear.py 3                 # 全部（可能很长）
  python tools\\probe_snow_clear.py 3 --cell 9,2      # 只看这一格
  python tools\\probe_snow_clear.py 3 --kind DROP     # 只看离场摘记账
"""
from __future__ import annotations

import json
import os
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
    want = args[args.index("--cell") + 1] if "--cell" in args else ""
    kind = args[args.index("--kind") + 1] if "--kind" in args else ""
    limit = int(args[args.index("--limit") + 1]) if "--limit" in args else 60

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
                       env=dict(os.environ, RIOS_TRACE="1", RIOS_SNOW_ALL="1",
                                RIOS_SNOW_CELL=""))
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s")
    print(f"mech_state['snow.field'] = "
          f"{json.dumps((got.get('mech_state') or {}).get('snow.field'), ensure_ascii=False)}")

    raw_lines = [ln.strip() for ln in (p.stderr or "").splitlines()]
    buckets = {b: [ln for ln in raw_lines if b in ln]
               for b in ("SNOWCLEAR", "SNOWKEEP", "SNOWDROP", "SNOWOWN")}
    for b, ls in buckets.items():
        print(f"  {b}: 全程 {len(ls)} 笔")
    sel = []
    for b, ls in buckets.items():
        if kind and kind not in b:
            continue
        for ln in ls:
            if want and f"[{want.replace(',', ' ')}]" not in ln:
                continue
            sel.append(ln)
    tag = f"（筛：cell={want or '全部'} kind={kind or '全部'}）"
    print(f"命中 {len(sel)} 笔 {tag}")
    for ln in sel[:limit]:
        print("   " + ln)
    if len(sel) > limit:
        print(f"   … 还有 {len(sel) - limit} 笔（--limit 调整）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
