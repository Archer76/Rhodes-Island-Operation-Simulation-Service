# -*- coding: utf-8 -*-
"""怀黍离端到端冒烟：把整条时间线跑完，看新机制有没有在真关卡里真的响。

**这不是成绩单。** 为了让时间线跑满，它把生命点临时放大到 999——漏光了就
看不全后面几分钟的机制了。要的是三件事：

1. 全程不抛异常（新字段/新分支在真实敌人身上都不炸）；
2. 日志里**真的出现**死亡污染 / 加速 / 蜕皮 / 明识形态 / 召唤的痕迹；
3. 结算数值合理（伤害、击杀数不为 0）。

⚠ 因此它跑出来的"胜利/剩余生命"**没有任何参考价值**，别拿它当基线。
真基线只有三条：1-7、SR-6、SR-EX-8（见 `tools/check_battle.py`、`run_sr6.py`）。
怀黍离不在基线里，这是它的机制只能靠构造场景 + 这种冒烟来验的原因。

用法：

```
python tools/smoke_hsl.py act31side_08       # 死亡污染 / 加速 / 重生充能 / 给装置
python tools/smoke_hsl.py act31side_ex08     # 死亡污染 / 蜕皮
```
"""
from __future__ import annotations

import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from ak_tactic.battle import BattleSimulator, Deployment, RangeProvider    # noqa: E402
from ak_tactic.battle.talents import squad_cost_bonus                      # noqa: E402
from ak_tactic.gamedata import (EnemyLibrary, GameDataSource, RangeTable,  # noqa: E402
                                load_stage)
from ak_tactic.operator import (OperatorCalculator, SkillBook,             # noqa: E402
                                TalentBook)
from ak_tactic.operator.attack_speed import attack_speed_bonus              # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                             # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")
from operbox_path import operbox_path                                       # noqa: E402

import json                                                                 # noqa: E402

STAGE = sys.argv[1] if len(sys.argv) > 1 else "act31side_ex08"


def load_box() -> dict:
    return {e["name"]: e for e in json.loads(
        operbox_path().read_text(encoding="utf-8-sig"))}


def build(calc, entry: dict) -> OperatorUnit:
    st = calc.stats(entry["id"], elite=entry["elite"], level=entry["level"],
                    potential=entry["potential"])
    t = st.total
    aspd = attack_speed_bonus(calc, entry["id"], elite=entry["elite"],
                              level=entry["level"], potential=entry["potential"])
    return OperatorUnit(
        name=st.name, char_id=entry["id"], elite=entry["elite"],
        max_hp=float(t["maxHp"]), atk=float(t["atk"]), defense=float(t["def"]),
        res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100) + aspd.flat,
        aspd_when_free=aspd.when_free,
    )


def main() -> int:
    src = GameDataSource()
    stage = load_stage(STAGE, source=src)
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    book = SkillBook()
    talents = TalentBook()
    table = RangeTable()
    box = load_box()

    def range_id_of(char_id: str, elite: int) -> str:
        phases = calc.character(char_id).get("phases") or []
        e = max(0, min(elite, len(phases) - 1))
        return phases[e].get("rangeId") or "1-1"

    provider = RangeProvider(table, range_id_of, block_of=lambda c, e: 1)

    print(f"=== {STAGE}  {stage.map.width}×{stage.map.height} ===")
    counts = Counter()
    for e, n in stage.enemy_counts().items():
        counts[lib.get(e).name] += n
    print("敌人 " + "、".join(f"{k}×{v}" for k, v in counts.items()))

    # 粗排：地面位挑离保护目标最近的几个，高台位补在其附近
    goal = stage.map.end_points[0]
    melee = sorted(stage.map.melee_spots,
                   key=lambda c: abs(c[0] - goal[0]) + abs(c[1] - goal[1]))[:4]
    ranged = sorted(stage.map.ranged_spots,
                    key=lambda c: min(abs(c[0] - m[0]) + abs(c[1] - m[1])
                                      for m in melee))[:3]

    # 挑练度最高的几个近战/远程
    melee_ops, ranged_ops = [], []
    for name, entry in box.items():
        try:
            pos = calc._load_chars().get(entry["id"], {}).get("position")
        except Exception:                                              # noqa: BLE001
            continue
        (melee_ops if pos == "MELEE" else ranged_ops).append(entry)
    melee_ops.sort(key=lambda e: -e.get("level", 0))
    ranged_ops.sort(key=lambda e: -e.get("level", 0))

    plan = []
    for entry, spot in zip(melee_ops, melee):
        plan.append((entry, spot, "Right"))
    for entry, spot in zip(ranged_ops, ranged):
        plan.append((entry, spot, "Left"))
    print("部署 " + "、".join(f"{e['name']}@{s}" for e, s, _d in plan))

    sim = BattleSimulator(stage, enemy_at=lib.get, range_provider=provider,
                          skill_book=book, verbose=True)
    # ⚠ 冒烟专用：临时放大量生命，好让整条时间线跑满（不是关卡真值）
    sim.life = 999
    squad = []
    for entry, spot, direction in plan:
        tal = talents.for_operator(entry["id"], elite=entry["elite"],
                                   level=entry["level"],
                                   potential=entry["potential"])
        squad.append((entry, spot, direction, tal))
    rate = float(stage.options.cost_increase_time)
    now, cost = 0.0, float(stage.options.initial_cost) + sum(
        squad_cost_bonus(t) for *_, t in squad)
    for entry, spot, direction, tal in squad:
        op = build(calc, entry)
        wait = max(0.0, (op.deploy_cost - cost) * rate)
        now += wait
        cost = cost + wait / rate - op.deploy_cost
        sim.plan(Deployment(now, op, spot, direction, skill=1,
                            skill_mastery=0, auto_skill=True, talents=tal))
    res = sim.run()
    print("\n" + res.summary())

    log = "\n".join(res.log)
    marks = {
        "死亡污染": "记入缓存",
        "加速": "受击 → 移速",
        "解除加速": "被阻挡 → 移速增益解除",
        "蜕皮": "蜕皮",
        "明识形态": "进入明识形态",
        "召唤": "召唤",
        "重生": "重生",
        "给装置(仅记账)": "仅记账",
        "明识清水": "明识形态：",
    }
    print("\n--- 机制痕迹 ---")
    for k, needle in marks.items():
        n = log.count(needle)
        print(f"  {'✓' if n else '·'} {k:16s} {n:4d} 次")

    fs = sim.farmland
    if fs is not None:
        dirty = [c for c in fs._index if fs.actual.get(c, 0.0) > 0]
        print(f"\n田地：{len(fs.fields)} 片、{len(fs._index)} 格，"
              f"结束时 {len(dirty)} 格病害值 > 0，"
              f"最高 {max((fs.actual.get(c, 0.0) for c in dirty), default=0):g}")
    print(f"装置：{len(sim._devices)} 个；召唤出来的敌人 "
          f"{sum(1 for e in sim.enemies if e.spawn_time > 0 and e.enemy_id in ('enemy_1391_dhbow_2', 'enemy_1392_dhshld_2'))} 个")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
