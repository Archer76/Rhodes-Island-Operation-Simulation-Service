#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把两台引擎的**事件表**（部署/出怪/阵亡/撤退/漏/技能/机制/重生）并排打出来。

用途：当某个量"整片塌掉"（比如 Go 的人倒得早、某位干员一笔都没出力）时，
先看**时间线上"谁什么时候上场"**对齐没有。部署差一拍，后面全是下游。

⚠ 顺序：**先看 deploy**。本会话在 k=4 上正要问"医疗为什么一次都没治"，
而"她根本没上场"/"她上场了但选不到人"是两件完全不同的事，
在别的痕迹里都看不出来。

用法:
  python tools\\probe_events.py 4
  python tools\\probe_events.py 4 --kind deploy
  python tools\\probe_events.py 4 --kind death,deploy
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster          # noqa: E402

#: 原版日志行的关键词 → 归一化的事件名（与 Go 的 `Kind` 对齐）。
PY_KINDS = {
    "deploy": ("部署",),
    "death": ("阵亡",),
    "retreat": ("撤退",),
    "kill": ("击倒", "击杀"),
    "leak": ("漏", "进入终点"),
    "skill": ("开启技能", "技能"),
    "reborn": ("重生",),
}
PY_LINE = re.compile(r"^\s*(?P<t>[\d.]+)s\s+(?P<rest>.*\S)\s*$")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 4
    want = None
    if "--kind" in args:
        want = {x.strip() for x in args[args.index("--kind") + 1].split(",")}
    plan, roster = load_plan(k), load_roster()

    from probe_snow_damage import PyProbe, Thief            # noqa: E402
    v = PyProbe(verbose=True).run(plan, roster=roster)
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    if not want or "deploy" in want:
        print("\n—— 原版日志里带关键词的行 ——")
        for ln in (getattr(v.result, "log", None) or []):
            for kind, kws in PY_KINDS.items():
                if want and kind not in want:
                    continue
                if any(w in ln for w in kws):
                    m = PY_LINE.match(ln)
                    print(f"  {kind:<8} {m.group('t') if m else '?':>9}  {ln.strip()}")
                    break

    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    from ak_tactic.simgo import find_binary                 # noqa: E402
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8")
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    evs = got.get("events") or []
    from collections import Counter
    print(f"\n[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s"
          f"  事件 {len(evs)} 条：{dict(Counter(e['kind'] for e in evs))}")
    #: ⚠ 「出怪表一共几条」与「实际出怪事件几条」必须分开看：
    #: Go 的结束判据之一是**出怪表走完**（`cursor >= len(spec.Spawns)`），
    #: 而"出怪事件数"只反映真的放出来了几只。两者不等 = 表里还有没到点的条目，
    #: 战斗就会一直跑到时间上限——**用时对不上、杀漏却全对**，正是这个形态。
    print(f"     出怪表 {got.get('spawns_total')} 条 / 已出 {got.get('spawns_done')} 条"
          f" / 时间上限 {got.get('max_time')}")
    rem = got.get("remnants") or []
    print(f"     残余单位 {len(rem)} 只：{rem if rem else '（无）'}"
          f"{'   ← 「清不掉」的那类非空时这一局永远收不了场' if any(r[1] for r in rem) else ''}")
    print("\n—— Go 事件 ——")
    for e in evs:
        if want and e["kind"] not in want:
            continue
        print(f"  {e['kind']:<8} {e['t']:>9.4f}  {e.get('who', '')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
