# -*- coding: utf-8 -*-
"""把两边**同一时刻的索敌键**并排打出来：`(-taunt_level, -progress)`。

原版 `_pick_targets`（`sim.py:3624`）对"射程内的敌人"就是按这个键排序取第一个。
两边帧位对齐、伤害却打在不同敌人身上时，唯一要问的就是这张表——
它同时给出 `taunt_level`（相性/天标那类"非首要目标"标记）与 `progress`（路线进度）。

`progress` 是**运行期**量，规格里没有；`taunt_level` 是规格里就有的静态值，
所以两张表要分开拿：原版跑一遍拿两张，Go 只拿 `taunt_level`。

用法: python tools\probe_pick_key.py 5 --at 733.4
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster, run_python  # noqa: E402
from probe_snow_cell import Thief, _fixture                         # noqa: E402

from ak_tactic.plan import Plan, Roster                             # noqa: E402
from ak_tactic.simgo import build_spec, find_binary                 # noqa: E402

import ak_tactic.battle.sim as simmod                               # noqa: E402

args = sys.argv[1:]
k = int(args[0]) if args and not args[0].startswith("-") else 5
at = float(args[args.index("--at") + 1]) if "--at" in args else 733.4

# ---- 原版：跑一遍，在指定时刻把"射程内敌人的索敌键"打出来 ----
SHOT = {"done": False}
orig_atk = simmod.BattleSimulator._operators_attack


def atk(self, dt, t):
    if not SHOT["done"] and t >= at:
        SHOT["done"] = True
        rows = []
        for e in self.enemies:
            if e.hp <= 0 or e.leaked or e.off_map:
                continue
            rows.append((e.name, float(e.taunt_level), float(e.progress),
                         e.position, e.hp, e.spawn_time,
                         float(e.defense), float(e.res), float(e.atk)))
        rows.sort(key=lambda r: (-r[1], -r[2]))
        print(f"原版 t={t:.4f} 在场敌人 {len(rows)} 只（按索敌键排序）：")
        for nm, taunt, prog, pos, hp, sp, de, rs, ak in rows:
            print(f"   {nm:<8} taunt={taunt:>5.1f} progress={prog:>9.4f} "
                  f"pos=({pos[0]:.4f},{pos[1]:.4f}) hp={hp:,.0f} "
                  f"def={de:,.2f} res={rs:,.2f} atk={ak:,.1f} 出怪={sp:.1f}")
    return orig_atk(self, dt, t)


simmod.BattleSimulator._operators_attack = atk

plan = load_plan(k)
roster = load_roster()
_py, pv, _pa = run_python(plan, roster)
print(f"原版判决 {pv.kills}杀 {pv.leaks}漏 {pv.elapsed:.6f}s")

# ---- Go：只需要规格里的静态 `taunt_level` ----
raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
raw = dict(raw, deploys=raw["deploys"][:k])
try:
    Thief().run(Plan.from_dict(raw),
                roster=Roster.from_json(_fixture("roster_max_modelled.json")))
except SystemExit:
    pass
spec = Thief.spec
assert spec is not None
seen = {}
for e in spec.get("spawns", []) + spec.get("enemies", []):
    nm = e.get("name")
    if nm is not None and nm not in seen:
        seen[nm] = e.get("taunt_level")
print("Go 规格里的 taunt_level：")
for nm, lv in sorted(seen.items(), key=lambda kv: (kv[1] is None, -(kv[1] or 0))):
    print(f"   {nm:<8} taunt={lv}")
