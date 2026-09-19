#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**11 关现状台账**生成器（修复窗口期的一次性输入）。

项目经理通告 #3 三.▸ 把「11 关现状台账」定为 P0：没有它谁也动不了。
本工具就是把台账**机械地**跑出来的那一步，逐关给四样：

1. **Go 能不能跑**：`spec.unsupported` 是否为空、是否发生 `fallback` 回退原版；
   拒跑则列出**具体键**（闸门条目），这些键就是"要接的字段族"。
2. **四项差**：杀 / 漏 / 用时 / 伤害（Go − 原版）。
3. **差异指纹（粗）**：四项里哪几项非零 —— **这是"什么量"分岔，不是"什么时刻"**；
   时刻级的指纹要 trace 对拍，本工具不做，台账里如实标注。
4. **闸门归属**：把 unsupported 键按**机制族**归类（人工判断，写在
   `docs/gate-ledger.md` 里，不在本脚本里：脚本只负责给键，归类要读 PRTS 原文）。

⚠ 关于"对拍不再作验收"与本次**例外**：
博士 09-19 裁定弃用 Python 模拟器、对拍退役；随后又裁定「11 关先修好」，
**修复窗口＝battle/ 还在的这段时间**，期间 `parity_plan` 复职为**诊断工具**
（通告 #3 二）。所以本工具在窗口内用它是合规的，且**窗口关闭后应随之退役**——
那正是它 docstring 里自己写的定位。

用法:
    python tools\\gate_ledger.py                    # 扫两棵树里全部作业
    python tools\\gate_ledger.py --stage act31side  # 只跑某活动的关卡
    python tools\\gate_ledger.py --limit 3          # 先试跑 3 关
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from parity_plan import compare  # noqa: E402  （同目录，sys.path 已含 tools）

PLAN_GLOBS = [
    str(ROOT / "out" / "*.json"),
    str(ROOT.parent / "ak-tactic-head" / "out" / "*.json"),
]
ROSTER = "roster_max_modelled"


def scan_plans() -> list[tuple[str, str]]:
    """返回 [(stage, 作业路径)]，跳过名单/名册这类不是作业的 JSON。"""
    out = []
    for pat in PLAN_GLOBS:
        for p in sorted(glob.glob(pat)):
            try:
                d = json.loads(Path(p).read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(d, dict):
                continue
            if "deploys" not in d or "stage" not in d:
                continue
            out.append((str(d["stage"]), p))
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", default="", help="只跑 stage 名含此子串的关卡")
    ap.add_argument("--limit", type=int, default=0, help="最多跑几关（试跑用）")
    ap.add_argument("--out-dir", default=str(ROOT / "out"))
    args = ap.parse_args()

    plans = scan_plans()
    if args.stage:
        plans = [(s, p) for s, p in plans if args.stage in s]
    if args.limit:
        plans = plans[: args.limit]
    print(f"待跑 {len(plans)} 个作业")

    rows = []
    for i, (stage, path) in enumerate(plans, 1):
        t0 = time.time()
        try:
            r = compare(path, ROSTER, quiet=True)
        except Exception as exc:  # noqa: BLE001
            r = {"ok": False, "why": f"{type(exc).__name__}: {exc}", "stage": stage,
                 "plan": os.path.basename(path)}
        r["plan_path"] = path
        r["seconds"] = round(time.time() - t0, 1)
        rows.append(r)
        uns = r.get("unsupported") or []
        state = ("拒跑" if uns else ("回退" if r.get("fallback") else "可跑"))
        d = r.get("diff")
        ds = ("—" if not d else
              f"杀{d[0]:+d} 漏{d[1]:+d} 用时{d[2]:+.3f} 伤{d[3]:+,.0f}")
        print(f"  [{i}/{len(plans)}] {stage:26} {state:4} {ds}   ({r['seconds']}s)")

    out_json = Path(args.out_dir) / "gate-ledger.json"
    out_json.write_text(json.dumps(rows, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    runnable = [r for r in rows if not (r.get("unsupported") or r.get("fallback"))]
    zero = [r for r in runnable if r.get("ok")]
    print()
    print(f"可跑 {len(runnable)}/{len(rows)}；其中四项全归零 {len(zero)}")
    print(f"写出 {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
