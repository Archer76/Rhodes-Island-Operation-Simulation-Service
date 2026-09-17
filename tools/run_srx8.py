"""SR-EX-8 的共用层：编队校验、试跑函数与落位表。

`tools/export_srx8.py` 从这里 import `make_provider` / `run_plan` / `PlanError`；
落位表 `GROUND` / `HIGHLAND` 由 `assert_spots()` 钉死在关卡自身上（手抄的集合最容易
在改坐标口径时漏改，而且抄错不报错）。

**它不内置任何方案。** 先前那四组（三人 92%、圣聆初雪技2、四人 79%、三人 38%）都建立在
「BOSS 从不换相性」这条**已被推翻**的读法上，跑出来是失败，2026-09-17 已删。现行答案由
`export_srx8.py` 产出，见 `docs/srx8-qi-solution.md`。

**干员数据走森空岛名册**（`tools/squad.py` 的 `Roster`），也就是真实专精、
真实模组、真实信赖。先前这一层吃的是 MAA 的 OperBox 导出，那份数据里
这三样都没有，所有模拟都跑在「技能 7 级 / 无专精 / 无模组 / 信赖 100%」的
假口径上——差距很大，见 `tools/squad.py` 的说明。

用法：
    python tools/run_srx8.py                 # 关卡事实：地图、可部署格、敌人、名册
    python tools/run_srx8.py --rank 30       # 按练度列前 30 名候选

这一版**还没有**建模的机制（会影响结论的可信度，报告里必须带出来）：
元素损伤、敌人技能（咆哮铳炸膛 / 吓人路灯屏障）、BOSS 双形态与重生、
飞行单位的不可阻挡。
"""

from __future__ import annotations

import argparse
import pathlib
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(TOOLS.parent))
sys.path.insert(0, str(TOOLS))

from ak_tactic.battle import BattleSimulator, Deployment, RangeProvider   # noqa: E402
from ak_tactic.battle.talents import squad_cost_bonus                     # noqa: E402
from ak_tactic.gamedata import (                                          # noqa: E402
    EnemyLibrary, GameDataSource, RangeTable, load_stage,
)
from ak_tactic.operator import SkillBook, TalentBook                      # noqa: E402
from squad import Roster                                                  # noqa: E402

STAGE_ID = "act54side_ex08"

#: 高台可部署位（按与中央咽喉的距离排）。**这就是 `stage.map.ranged_spots`。**
#: 2026-09-16 改口径时这个列表看着"没变"——因为它是集合，`y=3↔5` 互换、`y=4` 不动。
HIGHLAND = [(4, 3), (8, 3), (4, 5), (8, 5), (2, 4), (10, 4)]
#: 地面可部署位。**(6,7) 是敌人唯一的必经格，也是唯一值得站人的普通地面位。**
#: 改口径前这行写的是 `(6,1)` / `(4,6)` / `(8,6)`（旧编号）——注意集合也会变：
#: 只把 `HIGHLAND` 那种对称集合换对了、`GROUND` 忘了换，会拿 `tile_telin` 当落点。
GROUND = [(6, 7), (1, 4), (4, 4), (8, 4), (11, 4), (4, 2), (8, 2)]


def assert_spots(stage) -> None:
    """把上面两张硬编码表钉死在关卡自身上。

    `GROUND` / `HIGHLAND` 是**手抄的集合**，而集合恰恰最容易在改口径时漏改
    （对称的集合看着没变：`HIGHLAND` 的 `y=3↔5` 互换、`y=4` 不动；`GROUND` 不是）。
    抄错不会报错，只会让搜索在 `tile_telin` 上评估一个根本站不住人的落点。
    """
    if set(GROUND) != set(stage.map.melee_spots):
        raise SystemExit(f"GROUND 与关卡不符：多 {sorted(set(GROUND) - set(stage.map.melee_spots))}"
                         f"，少 {sorted(set(stage.map.melee_spots) - set(GROUND))}")
    if set(HIGHLAND) != set(stage.map.ranged_spots):
        raise SystemExit(f"HIGHLAND 与关卡不符：多 {sorted(set(HIGHLAND) - set(stage.map.ranged_spots))}"
                         f"，少 {sorted(set(stage.map.ranged_spots) - set(HIGHLAND))}")


def deploy_spots(roster: Roster, name: str, stage) -> set[tuple[int, int]]:
    """这名干员能站的格子。

    **判据只能用 `character_table` 的 `position` 字段（MELEE / RANGED），
    不能用职业名推。** 职业推是错的：特种里 19 个 MELEE、5 个 RANGED；
    支援里 27 个 RANGED、2 个 MELEE；先锋里 19 个 MELEE、5 个 RANGED。
    踩过的坑：望与新约能天使都是 **RANGED**，按"特种能站地面"会把她们
    摆到 `(11,4)` 这种地面格上，实机直接下不去。
    """
    pos = roster.calc.character(roster.get(name)["charId"]).get("position")
    if pos == "MELEE":
        return set(stage.map.melee_spots)
    if pos == "RANGED":
        return set(stage.map.ranged_spots)
    return set(stage.map.deployable)

#: 一个 plan 是若干 `(干员名, (x, y), 朝向, 技能槽)`；技能槽 0 = 不带技能，
#: 专精等级**由名册自动查**，不再由调用方手写。
Plan = list[tuple[str, tuple[int, int], str, int]]


def make_provider(calc, table):
    def rid(cid, elite):
        ph = calc.character(cid).get("phases") or []
        return ph[max(0, min(elite, len(ph) - 1))].get("rangeId") or "1-1"

    def block_of(cid, elite):
        ph = calc.character(cid).get("phases") or []
        i = max(0, min(elite, len(ph) - 1))
        kf = (ph[i].get("attributesKeyFrames") or [{}])[-1].get("data") or {}
        return int(kf.get("blockCnt") or 1)

    return RangeProvider(table, rid, block_of=block_of)


class PlanError(RuntimeError):
    pass


def validate_plan(stage, roster: Roster, plan: Plan) -> list[str]:
    """编队合法性校验。

    这里挡的是一类**必然跑不通却不会报错的错**：两个人踩同一格。
    先前导出的 `srx8-b.json` 里，逻各斯与焰狐龙梓兰都落在 `[10, 4]`，
    实机运行时第二个部署步骤永远不可能成功——而模拟器只是默默把
    后一个盖在前一个上，两边都不报错，于是「模拟说行、实机说不行」。

    同格 = 硬错误（抛）；落点不在该干员可站的格集合里 = 硬错误（抛，
    判据是 `character_table.position` 而不是职业名）。

    第二类错误的实例：望与新约能天使的 `position` 是 **RANGED**，若按
    「特种可以站地面」把她们摆到 `(11,4)`，实机连部署都做不到。
    """
    problems: list[str] = []
    seen: dict[tuple[int, int], str] = {}
    for name, pos, _dir, _slot in plan:
        if pos in seen:
            problems.append(f"✗ 同格冲突：{seen[pos]} 与 {name} 都在 {pos}")
        else:
            seen[pos] = name

    melee = set(stage.map.melee_spots)
    ranged = set(stage.map.ranged_spots)
    for name, pos, _dir, _slot in plan:
        if pos in melee or pos in ranged:
            continue
        problems.append(f"✗ {name} 的落点 {pos} 不是可部署格")

    for name, pos, _dir, _slot in plan:
        cid = roster.get(name)["charId"]
        where = roster.calc.character(cid).get("position")
        spots = deploy_spots(roster, name, stage)
        if pos not in spots:
            problems.append(
                f"✗ {name}（position={where}）落在 {pos}——不在它可站的 "
                f"{'地面' if where == 'MELEE' else '高台'}格集合里")

    hard = [p for p in problems if p.startswith("✗")]
    if hard:
        raise PlanError("编队不合法：\n  " + "\n  ".join(problems))
    return problems


def run_plan(stage, lib, provider, roster: Roster, book, talents, plan: Plan,
             *, verbose=False, strict=True, ranged_enemies=True, heal_mode="range",
             speed_scale=1.0, boss_mode_switch="none",
             affinity_blocks_damage=True, sword_qi_speed=1.2, enemy_windup=0.5):
    """按 plan 跑一遍，返回 `(sim, result, detail)`。部署时刻由费用回推。

    `detail` 每项是 `(wait, name, pos, direction, slot, mastery, cost)`，
    与 MAA 导出逐条同源。

    `heal_mode` 只在治疗干员身上起作用，见 `BattleSimulator.heal_mode`。
    `speed_scale` 是**敌速敏感性开关**（1.0 = 校准值），用来量这套解对
    移速换算误差的容忍度，不是预测值。`sword_qi_speed` 是剑气速度（格/秒，
    原文没给数值，见 `BattleSimulator.sword_qi_speed`），`enemy_windup` 是
    敌人的攻击动作长度（同样不在 gamedata 里）——两者都做成开关以便扫描。
    """
    warns = validate_plan(stage, roster, plan) if strict else []
    sim = BattleSimulator(stage, enemy_at=lib.get, range_provider=provider,
                          skill_book=book, verbose=verbose,
                          ranged_enemies=ranged_enemies, heal_mode=heal_mode,
                          speed_scale=speed_scale,
                          boss_mode_switch=boss_mode_switch,
                          affinity_blocks_damage=affinity_blocks_damage,
                          sword_qi_speed=sword_qi_speed,
                          enemy_windup=enemy_windup)
    rate = float(stage.options.cost_increase_time)
    cost = float(stage.options.initial_cost)

    squad = []
    for name, pos, direction, slot in plan:
        r = roster.get(name)
        tal = talents.for_operator(r["charId"], elite=r["elite"],
                                   level=r["level"], potential=r["potential"])
        squad.append((name, pos, direction, slot, r, tal))
        cost += squad_cost_bonus(tal)      # 天赋的额外初始费用要在排时刻前算进去

    detail = []
    for name, pos, direction, slot, r, tal in squad:
        op = roster.unit(name)
        wait = max(0.0, (op.deploy_cost - cost) * rate)
        now = sum(d[0] for d in detail) + wait
        cost = cost + wait / rate - op.deploy_cost
        mastery = roster.mastery(name, slot) if slot else 0
        sim.plan(Deployment(now, op, pos, direction, skill=slot or None,
                            skill_mastery=mastery, auto_skill=True, talents=tal))
        detail.append((wait, name, pos, direction, slot, mastery, op.deploy_cost))
    return sim, sim.run(max_time=900), detail, warns


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rank", type=int, default=0, help="按练度列前 N 名候选")
    args = ap.parse_args()

    src = GameDataSource()
    stage = load_stage(STAGE_ID, source=src)
    assert_spots(stage)
    lib = EnemyLibrary(source=src)
    roster = Roster()
    table = RangeTable()
    book = SkillBook()
    talents = TalentBook()
    provider = make_provider(roster.calc, table)

    print(f"=== {stage.summary()} ===")
    print(f"名册 {roster.path.name}  uid={roster.uid} [{roster.nick}]  "
          f"{len(roster.rows)} 名")
    print(f"可部署：地面 {len(stage.map.melee_spots)} 格、"
          f"高台 {len(stage.map.ranged_spots)} 格")
    print(f"敌人 {stage.total_enemies()} 只 / {len(stage.enemy_counts())} 种")

    if args.rank:
        print(f"\n=== 练度前 {args.rank} 名（需求：优先从练度最高的干员里选）===")
        for i, (n, sc) in enumerate(roster.rank(limit=args.rank), 1):
            print(f"{i:2d}. {roster.profile(n)}   分 {sc:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
