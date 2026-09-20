# -*- coding: utf-8 -*-
"""盯住**原版**某一格积雪：层数什么时候变、谁把它整格清掉的。

对拍里"两边都冻着、只差一帧解冻"这种残差，光看坐标查不出是谁干的——
要去问**清雪**那一侧。原版 `SnowField.leave_all`（`talents.py:1113`）判的是
"这位敌人**上一格**的首敌是不是它"，**不是首敌就不清**：两拨敌人先后走过
同一格时，先走的那只离场不能把后来那只脚下的雪清掉。

用法: python tools\probe_py_snow_leave.py 5 --cell 9,2
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
import ak_tactic.battle.talents as tal                               # noqa: E402

k = int(sys.argv[1]) if len(sys.argv) > 1 else 5
cell = (9, 2)
if "--cell" in sys.argv:
    a, b = sys.argv[sys.argv.index("--cell") + 1].split(",")
    cell = (int(a), int(b))

CUR = {"t": 0.0, "sim": None}
LOG: list[str] = []


def who(enemy_id) -> str:
    """把原版的 `id(e)` 还原成 (名字, 出怪时刻)——否则日志里只有一串 2719…。"""
    sim = CUR["sim"]
    if sim is None:
        return f"id={enemy_id}"
    for e in sim.enemies:
        if id(e) == enemy_id:
            return f"{e.name}@{e.spawn_time:.1f}"
    return f"id={enemy_id}(已不在列表)"


orig_snow = simmod.BattleSimulator._snow_tick


def snow(self, dt, t):
    CUR["t"] = t
    CUR["sim"] = self
    fields = list(self.snow_fields)
    before = [sf.layers.get(cell) for sf in fields]
    out = orig_snow(self, dt, t)
    for sf, was in zip(fields, before):
        now = sf.layers.get(cell)
        if now != was:
            LOG.append(f"{t:9.4f}  格{cell} 层 {was} → {now}"
                       f"  （施放者={sf.owner} 首敌={who(sf.first_enemy.get(cell)) if cell in sf.first_enemy else None}）")
    return out


#: 首敌归属**只在某个敌人第一次踏入那一格时定下**（`enter` 里的 `setdefault`），
#: 那一刻往往在几百帧之前——所以要单独记它，不能只看离场。
orig_enter = tal.SnowField.enter


def enter(self, enemy_id, c, atk, damage_fn):
    fresh = c == cell and c not in self.first_enemy
    out = orig_enter(self, enemy_id, c, atk, damage_fn)
    if fresh and c in self.first_enemy:
        LOG.append(f"{CUR['t']:9.4f}  ◆首敌确定：格{c} 归 {who(enemy_id)}"
                   f"（层={self.layers.get(c)}）")
    return out


orig_leave = tal.SnowField.leave_all


def leave(self, enemy_id):
    prev = self.last_cell.get(enemy_id)
    if prev == cell:
        owner = self.first_enemy.get(prev)
        LOG.append(f"{CUR['t']:9.4f}  ★leave_all(敌={who(enemy_id)}) 上一格={prev}"
                   f"  那格首敌={who(owner) if owner is not None else None}"
                   f"  层={self.layers.get(prev)}"
                   f"{'  ← 整格清雪' if owner == enemy_id else ''}")
    return orig_leave(self, enemy_id)


simmod.BattleSimulator._snow_tick = snow
tal.SnowField.enter = enter
tal.SnowField.leave_all = leave

plan = load_plan(k)
roster = load_roster()
py, pv, _pa = run_python(plan, roster)

print(f"原版判决 {pv.kills}杀 {pv.leaks}漏 {pv.elapsed:.6f}s")
print(f"格 {cell} 相关记录 {len(LOG)} 笔：")
for line in LOG:
    print("  " + line)
