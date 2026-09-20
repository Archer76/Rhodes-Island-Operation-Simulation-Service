# -*- coding: utf-8 -*-
"""盯住**原版**的"归来／明识形态"属性改写：改写前后到底是多少。

为什么要专门造这个探针：`phit_*`（蜕皮）与 `pm2_*`（归来）这两套改的都是
`EnemyUnit` 的**普通字段**（`atk` / `defense` / `res`），**不产生任何日志、
也没有痕迹**。下游能看到的只有"伤害被顶到 5% 保底"这种间接信号——
拿它去反推"防御到底被改成了多少"是猜，不是测。

这个探针挂在三个点上，把**改写前后**的值直接打出来：
  * `_enter_pm2`（`sim.py:4971`）—— 归来那一帧乘 `(1+pm2_atk)/(1+pm2_def)`、`res += pm2_res`
  * `_pm2_tick`（`sim.py:4893`）—— 清水开关触发时**按 `reborn_def_base` 重算**防御
  * `_reborn_tick`（`sim.py:5002`）—— 把带这套黑板的敌人整只快照下来

只记"带这套黑板的敌人"（`phit_cnt` 或 `pm2_atk/pm2_move/pm2_invincible` 非零），
HS-EX-8 上就是「祟」一只，日志不会淹。

用法: python tools\probe_py_pm2.py 5 [--from 600] [--to 720]
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster, run_python  # noqa: E402

import ak_tactic.battle.sim as simmod                                # noqa: E402

args = sys.argv[1:]
k = int(args[0]) if args and not args[0].startswith("-") else 5


def opt(flag, default):
    return args[args.index(flag) + 1] if flag in args else default


lo = float(opt("--from", "0"))
hi = float(opt("--to", "1e9"))

CUR = {"t": 0.0}
LOG: list[str] = []

#: 只看带这套黑板的敌人——否则每帧每只敌人都刷一行。
def interesting(e) -> bool:
    return bool(getattr(e, "phit_cnt", 0) or getattr(e, "pm2_atk", 0.0)
                or getattr(e, "pm2_move", 0.0) or getattr(e, "pm2_invincible", 0.0))


def snap(e) -> str:
    return (f"{e.name}@{e.spawn_time:.1f} hp={e.hp:,.0f} "
            f"atk={float(e.atk):,.2f} def={float(e.defense):,.2f} res={float(e.res):,.2f} "
            f"phit={getattr(e, 'phit_stacks', '?')}/{getattr(e, 'phit_max_stack', '?')} "
            f"def_base={getattr(e, 'reborn_def_base', '?')} "
            f"clean={getattr(e, 'pm2_clean', '?')} applied={getattr(e, 'pm2_applied', '?')} "
            f"times={getattr(e, 'attack_times', '?')} "
            f"haste={getattr(e, 'haste_multiplier', '?')}")


def emit(t: float, text: str) -> None:
    if lo <= t <= hi:
        LOG.append(f"{t:9.4f}  {text}")


orig_enter_pm2 = simmod.BattleSimulator._enter_pm2


def enter_pm2(self, e, t):
    if interesting(e):
        emit(t, f"◆_enter_pm2 前  {snap(e)}")
    out = orig_enter_pm2(self, e, t)
    if interesting(e):
        emit(t, f"    _enter_pm2 后  {snap(e)}")
    return out


orig_pm2_tick = simmod.BattleSimulator._pm2_tick


def pm2_tick(self, e, t):
    before = (float(e.defense), getattr(e, "pm2_clean", None),
              getattr(e, "haste_multiplier", None))
    out = orig_pm2_tick(self, e, t)
    after = (float(e.defense), getattr(e, "pm2_clean", None),
             getattr(e, "haste_multiplier", None))
    if interesting(e) and before != after:
        emit(t, f"○_pm2_tick 清水 {before[1]} → {after[1]}；"
                f"防御 {before[0]:,.2f} → {after[0]:,.2f}；"
                f"移速倍率 {before[2]} → {after[2]}")
    return out


orig_reborn_tick = simmod.BattleSimulator._reborn_tick


def reborn_tick(self, t):
    watch = [e for e in self.enemies if interesting(e)]
    before = {id(e): (float(e.hp), float(e.atk), float(e.defense), float(e.res),
                      getattr(e, "reborn_at", None)) for e in watch}
    out = orig_reborn_tick(self, t)
    for e in watch:
        b = before.get(id(e))
        if b is None:
            continue
        a = (float(e.hp), float(e.atk), float(e.defense), float(e.res),
             getattr(e, "reborn_at", None))
        if b != a:
            emit(t, f"★重生跳变 {e.name}@{e.spawn_time:.1f}  "
                    f"hp {b[0]:,.0f}→{a[0]:,.0f}  atk {b[1]:,.0f}→{a[1]:,.0f}  "
                    f"def {b[2]:,.2f}→{a[2]:,.2f}  res {b[3]:,.2f}→{a[3]:,.2f}  "
                    f"reborn_at {b[4]}→{a[4]}；{snap(e)}")
    return out


simmod.BattleSimulator._enter_pm2 = enter_pm2
simmod.BattleSimulator._pm2_tick = pm2_tick
simmod.BattleSimulator._reborn_tick = reborn_tick

plan = load_plan(k)
roster = load_roster()
py, pv, _pa = run_python(plan, roster)

print(f"原版判决 {pv.kills}杀 {pv.leaks}漏 {pv.elapsed:.6f}s")
print(f"明识形态相关记录 {len(LOG)} 笔：")
for line in LOG:
    print("  " + line)
