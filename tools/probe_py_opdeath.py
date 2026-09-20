#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓住「某位干员在某一刻被打死」的**那一击是谁打的**（原版侧）。

## 为什么需要它

第 3 手剩下的 1.167 秒残差，追到最后落在这一件事上：
原版 **圣聆初雪在 t=84.4000 阵亡**（hp 203 → 0），她一倒下，那 8 格积雪
**立刻全部失效**（不减速、不冻结、不积层）——因为 `_snow_tick` 的敌人循环里
`if op is None or not op.alive: continue`（`sim.py:1146`）在 `enter` 之前。

于是原版从 84.4 起等于"没有雪"，Go 那边雪一直生效，差出这 1.167 秒。

但"她死于什么"看不见：`enter` 的痕迹只说明她**之后**不在场，`帧首` 四闸门
也全是 False（敌人活着、格可走），只剩施放者这一条。伤害入口只有
`Combatant.take`（`unit.py:104`）一个，钩住它就能把那一击的**调用方**打出来。

用法: python tools\\probe_py_opdeath.py 3 --op 圣聆初雪 --from 84.3 --to 84.5
"""
from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle import unit as U                          # noqa: E402
from ak_tactic.plan import Plan, Roster                         # noqa: E402
from ak_tactic.verify import Verifier                           # noqa: E402


def _fixture(name: str) -> Path:
    p = Path(name)
    if p.is_absolute() and p.exists():
        return p
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        for cand in (base / "out" / name, base / "out" / f"{name}.json"):
            if cand.exists():
                return cand
    raise SystemExit(f"找不到 {name}")


def main() -> int:
    import os
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    target = args[args.index("--op") + 1] if "--op" in args else "圣聆初雪"
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9

    #: ⚠ 干员名在 PowerShell 里往返**可能掉字符**，而掉字符的症状是"这个探针
    #: 一笔都不打印"——与"这位干员真的没挨打"长得一样。`--op-idx N` 从作业
    #: 文件里取名字（Python 自己按 UTF-8 读），名字全程不出命令行。
    plan_path = _fixture(os.environ.get("RIOS_PLAN", "hsex8_max.json"))
    raw = json.loads(plan_path.read_text(encoding="utf-8"))
    if "--op-idx" in args:
        target = raw["deploys"][int(args[args.index("--op-idx") + 1])]["operator"]
    raw = dict(raw, deploys=raw["deploys"][:k]) if k else raw
    print(f"作业={plan_path.name}  目标干员={target}  窗口=[{lo}, {hi}]")

    state = {"t": -1.0}
    orig_take = U.Combatant.take

    def take(self, amount):
        before = self.hp
        r = orig_take(self, amount)
        if getattr(self, "name", None) == target and lo <= state["t"] <= hi:
            #: 栈只取伤害入口下面这几层：再往下是模拟器的通用循环，没有信息量。
            frames = [f"{Path(f.filename).name}:{f.lineno} {f.function}"
                      for f in inspect.stack()[1:6]]
            print(f"   t={state['t']:.4f} {target} hp {before:.1f} → {self.hp:.1f} "
                  f"（扣 {r:.1f}，请求 {amount:.1f}）")
            for f in frames:
                print(f"        ← {f}")
        return r

    U.Combatant.take = take

    #: 时刻只从**帧首**取：`take` 可能在一帧里被调多次，用帧时间才对齐得上。
    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig_env = cls._environment_tick

    def env(self, dt, t):
        state["t"] = t
        return orig_env(self, dt, t)

    cls._environment_tick = env

    v = Verifier().run(Plan.from_dict(raw),
                       roster=Roster.from_json(_fixture(
                           os.environ.get("RIOS_ROSTER", "roster_max_modelled.json"))))
    print(f"原版 {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
