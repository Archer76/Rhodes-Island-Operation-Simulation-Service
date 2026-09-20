#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""积雪**踏入伤害逐笔对账**（原版 `result.log` ↔ Go 的 `SNOWENTRY` 痕迹）。

## 为什么值得单独一个探针

总伤害差 1,392 点这件事，`probe_snow_damage.py` 只能告诉你**数字差了多少**：
它报的是"伤害 +1,392.0"，看不出是**哪一笔**多的。而积雪的踏入伤害是一个
**逐笔可点名**的量——原版每次踏入都往 `result.log` 写一行
`{t}s {owner} 积雪伤害 {hit} → {name}`，Go 侧对应的就是 `SNOWENTRY`。

对账方式：两边按**发生顺序**并排（原版日志把时刻压到 1 位小数，
所以不能拿时刻当键，只能按序比），逐笔看
**时刻 / 敌人 / 数值**三项。少一笔、多一笔、或某一笔数值不同，一眼就能看见。

用法: python tools\\probe_snow_entry.py 3
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace_kv                                               # noqa: E402
from probe_windup_phase import find_binary, load_plan, load_roster  # noqa: E402

#: 原版日志行：`   63.1s  圣聆初雪 积雪伤害 557 → 厌肮`
PY_LINE = re.compile(r"^\s*(?P<t>[\d.]+)s\s+(?P<owner>\S+)\s+积雪伤害\s+"
                     r"(?P<hit>[\d,\.]+)\s+→\s+(?P<name>\S+)\s*$")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    plan, roster = load_plan(k), load_roster()

    from probe_snow_damage import PyProbe, Thief        # noqa: E402
    v = PyProbe(verbose=True).run(plan, roster=roster)
    py = []
    for ln in (getattr(v.result, "log", None) or []):
        m = PY_LINE.match(ln)
        if m:
            py.append((float(m.group("t")), m.group("name"),
                       float(m.group("hit").replace(",", ""))))
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s "
          f"踏入伤害 {len(py)} 笔，合计 {sum(x[2] for x in py):,.2f}")

    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    from ak_tactic.simgo.client import Simgo        # noqa: E402
    import json
    import os
    import subprocess
    from ak_tactic.simgo import find_binary as _fb  # noqa: E402
    p = subprocess.run([str(_fb())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(p.stderr, "SNOWENTRY", ("t", "enemy", "dmg"))
    go = [(float(d["t"]), d["enemy"], float(d["dmg"])) for d in rows]
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"踏入伤害 {len(go)} 笔，合计 {sum(x[2] for x in go):,.2f}")

    print(f"\n{'#':>3} {'原版 t':>8} {'敌人':<6} {'伤害':>9}   | "
          f"{'Go t':>8} {'敌人':<6} {'伤害':>9}   | 判定")
    bad = 0
    for i in range(max(len(py), len(go))):
        a = py[i] if i < len(py) else None
        b = go[i] if i < len(go) else None
        if a is None or b is None:
            verdict = "**只有一边有**"
            bad += 1
        elif a[1] != b[1]:
            verdict = f"**敌人不同**（{a[1]} vs {b[1]}）"
            bad += 1
        elif abs(a[2] - b[2]) > 0.05 or abs(a[0] - b[0]) > 0.051:
            verdict = f"差 {b[2] - a[2]:+.2f} / Δt {b[0] - a[0]:+.4f}"
            bad += 1
        else:
            verdict = "一致"
        sa = f"{a[0]:8.4f} {a[1]:<6} {a[2]:9.2f}" if a else " " * 26
        sb = f"{b[0]:8.4f} {b[1]:<6} {b[2]:9.2f}" if b else " " * 26
        print(f"{i:>3} {sa}   | {sb}   | {verdict}")
    print(f"\n合计差 {sum(x[2] for x in go) - sum(x[2] for x in py):+,.2f}，"
          f"有问题的笔数 {bad}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
