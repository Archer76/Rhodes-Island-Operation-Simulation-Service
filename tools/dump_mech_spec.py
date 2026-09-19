#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把某一关交给 Go 的**机制规格原文**打出来（按键取值）。

来历：`Farmland.DeployDamage` 接上之后仍然返回 0，可同一格的
`DamagePerSecond` 明明是对的（155）。两者用的是同一个 `Params` 结构，
那就只剩"规格里那两个键本来就是 0"。**规格是唯一的证据**——
读 Python 侧构造代码只能证明"它打算送什么"，证明不了"实际送出去的是什么"。

用法: python tools\\dump_mech_spec.py --key first_basic_damage
      python tools\\dump_mech_spec.py --mech huai_shu_li.farmland --path params
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

from probe_windup_phase import load_plan, load_roster          # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def main() -> int:
    args = sys.argv[1:]
    mech = args[args.index("--mech") + 1] if "--mech" in args else "huai_shu_li.farmland"
    only = args[args.index("--key") + 1] if "--key" in args else None
    path = args[args.index("--path") + 1] if "--path" in args else None

    from ak_tactic.simgo import build_spec
    from ak_tactic.simgo.verifier import GoVerifier

    class Grab(GoVerifier):
        def _run_other_engine(self, *, sim, plan, stage, deployed, title):
            self.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
            raise SystemExit(0)

    g = Grab()
    try:
        g.run(load_plan(0), roster=load_roster())
    except SystemExit:
        pass
    cfg = (g.spec.get("mech_config") or {}).get(mech)
    print(f"机制 {mech}：{'在规格里' if cfg is not None else '**不在规格里**'}")
    print(f"点名的机制：{g.spec.get('mechanisms')}")
    if cfg is None:
        return 1
    if path:
        for part in path.split("."):
            cfg = cfg.get(part) if isinstance(cfg, dict) else None
            if cfg is None:
                print(f"  —— 取到 {part} 就没了")
                return 1
    if only:
        print(f"  {only} = {cfg.get(only)!r}")
        return 0
    print(json.dumps(cfg, ensure_ascii=False, indent=2, sort_keys=True)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
