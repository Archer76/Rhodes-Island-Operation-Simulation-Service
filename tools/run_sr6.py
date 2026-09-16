"""SR-6 模拟：按干员盒练度跑 MAA 作业，并做三档练度对照。

## 落位坐标：MAA 作业直接对拷，不做换算

本项目**内部就是 MAA 口径**（原点左上、y 自上而下），所以 MAA copilot 的
`location: [x, y]` 原样就是项目坐标，**不做换算**：

    圣聆初雪 [5,4] → (5,4)   tile_wall（高台）✓
    德克萨斯 [6,3] → (6,3)   tile_road（地面）✓

判据仍是职业与地形必须相容——术师/辅助站高台、先锋站地面。
（2026-09-16 改口径前，本项目 y 向上，`MAA_PLAN` 的这两个数要经
`pos = (x, H-1-y)` 翻一次才落对；现在那一步是恒等，已删。
**教训**：项目坐标与 MAA 坐标混在同一份代码里时，必须先认清手上这个字面量
是哪一套再动手——两个都翻等于翻两次，落点会错到另一条行上，
而模拟器并不校验地形合法性，只会安静地跑出一个"看起来对"的结果。）

## 为什么这条路必须沿地块寻路

SR-6 的 21 条路线**一条 MOVE 路点都没有**，只有起点与终点，且
`options.steeringEnabled = true`。若按直线走，(4,6) → (5,3) 只有 3.16 格；
沿可行走地块绕行则是 **12.00 格**（`... → (9,4) → (8,3) → (7,3) → (6,3) → (5,3)`）。
**21 条路线里有 17 条经过 (6,3)**——德克萨斯站的位置正是通往防守点的咽喉。

（2026-09-15 更正：此前这里写 11.41 格，是因为 `StageMap.walkable()` 把
`tile_hole` 当成了可走地面，敌人能从 `(8,6)[洞] → (9,5)` 斜切一步角省下 0.59 格。
按用户口径洞不可走后，21 条路线全部仍连通，但其中 12 条各长 0.59 格。）
"""

from __future__ import annotations

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator, Deployment, RangeProvider  # noqa: E402
from ak_tactic.operator.attack_speed import attack_speed_bonus            # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                            # noqa: E402
from ak_tactic.battle.talents import squad_cost_bonus                      # noqa: E402
from ak_tactic.gamedata import (                                          # noqa: E402
    EnemyLibrary, GameDataSource, RangeTable, load_stage,
)
from ak_tactic.operator import (                                          # noqa: E402
    OperatorCalculator, SkillBook, TalentBook,
)

sys.stdout.reconfigure(encoding="utf-8")

from operbox_path import operbox_path                                  # noqa: E402

#: 账号名册是**外部输入**，不入库：见 tools/operbox_path.py 的两种取法。
BOX = operbox_path()

STAGE_ID = "act54side_06"          # SR-6
#: 作业落位。**这就是 MAA 的 `location`，原样抄，不做任何换算**——
#: 改口径后项目内部即 MAA 口径。别手贱去翻它：翻一次就变成
#: 圣聆初雪站 `tile_end`、德克萨斯站 `tile_wall`，两个都非法。
MAA_PLAN = [
    ("圣聆初雪", 2, (5, 4), "Right", 3),
    ("德克萨斯", 1, (6, 3), "Right", 0),
]

#: 三档对照：用户实际练度 / 作业标注的最低要求 / 满配
VARIANTS = [
    ("你的练度", {}),
    ("作业要求", {"德克萨斯": {"level": 40}, "圣聆初雪": {"level": 60}}),
    ("满配", {"德克萨斯": {"level": 80}, "圣聆初雪": {"level": 90}}),
]


def load_box() -> dict[str, dict]:
    return {e["name"]: e for e in json.loads(BOX.read_text(encoding="utf-8-sig"))}


def build(calc, entry: dict) -> OperatorUnit:
    st = calc.stats(entry["id"], elite=entry["elite"], level=entry["level"],
                    potential=entry["potential"])
    t = st.total
    aspd = attack_speed_bonus(
        calc, entry["id"], elite=entry["elite"], level=entry["level"],
        potential=entry["potential"])
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
    stage = load_stage(STAGE_ID, source=src)
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    book = SkillBook()
    talents = TalentBook()
    table = RangeTable()
    box = load_box()
    H = stage.map.height

    def range_id_of(char_id: str, elite: int) -> str:
        phases = calc.character(char_id).get("phases") or []
        e = max(0, min(elite, len(phases) - 1))
        return phases[e].get("rangeId") or "1-1"

    provider = RangeProvider(table, range_id_of, block_of=lambda c, e: 1)

    print(f"=== {stage.code}  {stage.map.width}×{H}  生命 {stage.options.max_life_point}"
          f"  初始费用 {stage.options.initial_cost:g}"
          f"  回费 {stage.options.cost_increase_time:g}s/点"
          f"  移速系数 {stage.options.move_multiplier:g} ===")
    print("敌人 " + "、".join(f"{lib.name(e)}×{n}"
                            for e, n in stage.enemy_counts().items()))
    total_hp = sum(lib.get(e, 0).max_hp * n for e, n in stage.enemy_counts().items())
    print(f"敌方总血量 {total_hp:,.0f}（21 只，生命只有 3 点 ⇒ 最多放过 3 只）")
    print()

    for title, over in VARIANTS:
        sim = BattleSimulator(stage, enemy_at=lib.get,
                              range_provider=provider, skill_book=book)
        # 先把各人的天赋都解出来：天赋「编入队伍后额外获得初始部署费用」要在
        # **排部署时刻之前**知道，否则第一个干员会被排晚 2 秒。
        squad = []
        for name, slot, loc, direction, mastery in MAA_PLAN:
            entry = dict(box[name], **(over.get(name) or {}))
            tal = talents.for_operator(entry["id"], elite=entry["elite"],
                                       level=entry["level"],
                                       potential=entry["potential"])
            squad.append((name, slot, loc, direction, mastery, entry, tal))
        rate = float(stage.options.cost_increase_time)
        now = 0.0
        cost = float(stage.options.initial_cost) + sum(
            squad_cost_bonus(t) for *_, t in squad)
        detail = []
        for name, slot, loc, direction, mastery, entry, tal in squad:
            op = build(calc, entry)
            pos = (loc[0], loc[1])          # MAA 即项目口径，直接落位
            # 模拟器**不校验地形合法性**：站错了不会报错，只会安静地跑出一个
            # "看起来对"的结果（2026-09-16 真踩过——把 MAA 字面量误翻了一次，
            # 术师落到 tile_end、先锋落到 tile_wall，结果照样 21 杀 0 漏）。
            # 所以在这里把职业与地形相容性钉死。
            melee_side = calc._load_chars().get(op.char_id, {}).get(
                "position") == "MELEE"
            spots = stage.map.melee_spots if melee_side else stage.map.ranged_spots
            tile = stage.map.tile(*pos).key
            if pos not in spots:
                raise SystemExit(
                    f"落点非法：{name} 落在 {pos}（{tile}），"
                    f"但它需要{'地面' if melee_side else '高台'}可部署格。"
                    f"MAA 的 location 与项目坐标同口径，不要再翻一次。")
            wait = max(0.0, (op.deploy_cost - cost) * rate)
            now += wait
            cost = cost + wait / rate - op.deploy_cost
            detail.append(f"{name} 精{entry['elite']}{entry['level']}级"
                          f"({op.max_hp:.0f}血/{op.defense:.0f}防, {now:.0f}s)")
            sim.plan(Deployment(now, op, pos, direction, skill=slot,
                                skill_mastery=mastery, auto_skill=True,
                                talents=tal))
        r = sim.run(max_time=900)
        verdict = "胜利" if r.won else "失败"
        print(f"【{title}】{verdict}  {r.elapsed:.1f}s  击杀 {r.kills}"
              f"  漏怪 {r.leaks}  剩余生命 {r.life}  总伤害 {r.damage_dealt:,.0f}")
        print(f"     {' | '.join(detail)}")
        for o in sim.operators:
            end = (f"阵亡于 {o.death_time:.1f}s（共承受 {o.damage_taken:,.0f}）"
                   if not o.alive else f"存活 {o.hp:,.0f} HP")
            print(f"     {o.name}: 出手 {o.hits} 次，{end}")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
