# -*- coding: utf-8 -*-
"""把 Go 侧痕迹在某个时间窗口里**全标签**打出来，用来回答"这一帧谁动的手"。

用法：
    python tools\\probe_window_trace.py 8 65.5 66.1
    python tools\\probe_window_trace.py 8 65.5 66.1 --only PILE,DMGENEMY

为什么需要它：`probe_hp_cross.py` 能告诉我们"`t=65.8` 原版掉了 626.4 血、Go 没掉"，
但**回答不了"那 626.4 是谁打的"**。Go 侧有一整套痕迹标签（`PILE*` 天桩、
`DMGENEMY` 对敌伤害、`SPLASH` 溅射、`ENV` 环境……），把窗口内**所有**标签按时刻
排出来，就能看出那一帧到底有没有对应的事件。

⚠ 原版侧**没有等价标签**（`trace_kv()` 在 `ak_tactic/battle/` 里 0 命中）——
所以本脚本只回答"Go 这一帧做了什么"，**不能单独用它下"两边不同"的结论**。
要判"原版做了什么"，得另配钩子（见 `probe_windup_phase.py` 的 `scan/atk`）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import probe_windup_phase as P                                    # noqa: E402

LABEL_RE = re.compile(r"^\s*([A-Z][A-Z0-9]*)\s+t=([\d.]+)")


def main() -> int:
    args = [a for a in sys.argv[1:]]
    pos = [a for a in args if not a.startswith("-")]
    k = int(pos[0]) if pos else 8
    lo = float(pos[1]) if len(pos) > 1 else 0.0
    hi = float(pos[2]) if len(pos) > 2 else 1e9
    only = None
    if "--only" in args:
        only = {s.strip().upper() for s in args[args.index("--only") + 1].split(",") if s.strip()}

    plan = P.load_plan(k)
    roster = P.load_roster()

    thief = P.SpecThief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    spec = thief.spec
    assert spec is not None, "没偷到规格"
    print(f"  规格：stage={spec.get('stage')}  spawns={len(spec.get('spawns') or [])}  "
          f"deploys={len(spec.get('deploys') or [])}")

    exe = P.find_binary()
    env = dict(os.environ, RIOS_TRACE="1")
    p = subprocess.run([str(exe)],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8", env=env)
    resp = json.loads(p.stdout.strip().splitlines()[-1])
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error"))
    g = resp["verdict"]
    print(f"  Go 判决：{g['kills']}杀 {g['leaks']}漏 {g['elapsed']:.6f}s\n")

    #: 按标签归并窗口内的行
    buckets: dict[str, list[str]] = {}
    total = 0
    for line in (p.stderr or "").splitlines():
        m = LABEL_RE.match(line)
        if not m:
            continue
        label, t = m.group(1), float(m.group(2))
        if not (lo - 1e-9 <= t <= hi + 1e-9):
            continue
        if only and label not in only:
            continue
        total += 1
        buckets.setdefault(label, []).append(line.rstrip())

    if not total:
        print(f"  ⚠ Go 侧在 t∈[{lo}, {hi}] 里**一条痕迹都没有**。")
        print("     这不等于「这一帧什么都没发生」——先确认标签名对不对、")
        print("     以及 RIOS_TRACE=1 是否真的生效（记忆 223402c9 那类假信号）。")
        return 1

    print(f"  Go 侧 t∈[{lo}, {hi}] 共 {total} 条，按标签分组：")
    for label in sorted(buckets, key=lambda L: -len(buckets[L])):
        rows = buckets[label]
        print(f"\n  ── {label}  {len(rows)} 条 ──")
        for r in rows[:18]:
            print(f"     {r}")
        if len(rows) > 18:
            print(f"     ……（还有 {len(rows) - 18} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
