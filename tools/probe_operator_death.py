#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""干员**阵亡/撤退时刻**对拍：谁先塌、差多久。

## 为什么 k=4 起要看这个（而不是继续看敌人的承伤账）

k=4 加的第 4 位干员是**医疗**——她在两个引擎里都**一笔伤害都不产生**
（`probe_attack_ledger.py` 里干脆不出现），所以"承伤账"这条路天生看不见她。
她的贡献全在**让别人活得久**上；而一旦她（或任何一位）倒得比原版早，
后面的账会整片塌掉——症状就是"Go 的敌人血比原版多、杀得比原版少"，
但那只是**下游**，不是病根。

⚠ 这也是 k≥4 与 k=1..3 的分水岭：**前几位全是输出，第 4 位是生存**。
拿"输出类"的账本去查"生存类"的偏差，只会看到一堆长度不同的表。

## 取数

* 原版：`result.log` 里那两行（措辞就是 Go 注释里引的那句）——
  `阵亡（承受 N 伤害）` / 撤退；
* Go：判决回执 `events` 里 `kind == "death"` 的那几条（`sim.go` 的 `hurt`）。

用法: python tools\\probe_operator_death.py 4
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster          # noqa: E402

#: 原版日志行：`   70.3s  机械师 阵亡（承受 4210 伤害）`
PY_DEATH = re.compile(r"^\s*(?P<t>[\d.]+)s\s+(?P<who>\S+)\s+阵亡（承受\s*(?P<dmg>[\d,]+)\s*伤害）")
PY_RETREAT = re.compile(r"^\s*(?P<t>[\d.]+)s\s+(?P<who>\S+)\s+撤退")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 4
    plan, roster = load_plan(k), load_roster()

    from probe_snow_damage import PyProbe, Thief            # noqa: E402
    v = PyProbe(verbose=True).run(plan, roster=roster)
    py_death, py_retreat = [], []
    for ln in (getattr(v.result, "log", None) or []):
        m = PY_DEATH.match(ln)
        if m:
            py_death.append((float(m.group("t")), m.group("who"),
                             float(m.group("dmg").replace(",", ""))))
            continue
        m = PY_RETREAT.match(ln)
        if m:
            py_retreat.append((float(m.group("t")), m.group("who")))
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s "
          f"阵亡 {len(py_death)} 撤退 {len(py_retreat)}")

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
    go_death = [(float(e["t"]), str(e.get("who", "")).split("（")[0])
                for e in (got.get("events") or []) if e.get("kind") == "death"]
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"阵亡 {len(go_death)}")

    #: 干员顺序按**阵亡先后**排（先倒的在前）——按名字排会把"第 3 位先倒"
    #: 读成"第 1 位先倒"；而规格里的 deploys 字段名各版本不一，不去猜它。
    who = [x[1] for x in sorted(py_death)]
    for t, n in sorted(go_death):
        if n not in who:
            who.append(n)
    print(f"\n{'干员':<12} {'原版阵亡':>12} {'Go 阵亡':>12}   {'差':>10}")
    bad = 0
    for name in who:
        a = next((x[0] for x in py_death if x[1] == name), None)
        b = next((x[0] for x in go_death if x[1] == name), None)
        sa = f"{a:.4f}" if a is not None else "—"
        sb = f"{b:.4f}" if b is not None else "—"
        if a is None and b is None:
            d = "都没倒"
        elif a is None or b is None:
            d = "**只有一边倒**"
            bad += 1
        elif abs(a - b) > 5e-4:
            d = f"{b - a:+.4f}"
            bad += 1
        else:
            d = "一致"
        print(f"{name:<12} {sa:>12} {sb:>12}   {d:>10}")
    if py_retreat:
        print(f"\n原版撤退：{py_retreat}")
    print(f"\n阵亡时刻不一致的干员 {bad} 位")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
