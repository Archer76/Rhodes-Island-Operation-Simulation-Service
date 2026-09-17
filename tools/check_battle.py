"""战斗与技能的回归检查。

跑法：`python tools/check_battle.py`，全过返回 0。

这里检查的是**能被证伪的东西**，而不是"跑起来没报错"：

1. **1-7 无技能基线**——三条既有阵容必须还是 137.0s / 41 击杀 / 0 漏 /
   总伤害 60750。技能系统是后加进来的，这一条防的是"新代码改坏了旧路径"。
2. **技能解析的定点值**——机械师的总倍率必须是 9.88（(1+2.8)×2.6），
   这个数有社区标定作对照；取错黑板键会算成 11.4。
3. **1-7 实机录像用例**——用户提供的单干员（怒潮凛冬）通关录像。
   只按黑板跑只有 35 击杀；把"第二次及以后"的变体取值叠上才到 41 击杀，
   与录像一致。这条同时证明了变体解析是对的。

第 3 条要说明白：`headb2_s_2[second].atk = 1.8` 是黑板里真实存在的键，
所以"第二次起加成翻倍"**不是**靠描述文本猜的；但"且持续时间无限"那半句
黑板里确实没有，只能由调用方手工把 duration 置为 None。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator, Deployment           # noqa: E402
from ak_tactic.battle.damage import DamageType, resolve_damage      # noqa: E402
from ak_tactic.battle.talents import (SnowField, find_snow, find_sp_on_action,
                                      squad_cost_bonus)  # noqa: E402
from ak_tactic.operator.attack_speed import attack_speed_bonus      # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                      # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.gamedata.stage import RouteLeg                        # noqa: E402
from ak_tactic.battle.unit import EnemyUnit                          # noqa: E402
from ak_tactic.operator import (                                    # noqa: E402
    OperatorCalculator, SkillBook, SummonBook, TalentBook,
)
from ak_tactic import formula as F                                   # noqa: E402
from ak_tactic.operator.skill import _wants_dodge                    # noqa: E402

_FAILED: list[str] = []
_PASSED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}   {detail}")


def close(a: float, b: float, tol: float = 1e-6) -> bool:
    return abs(float(a) - float(b)) <= tol


def make_unit(calc, char_id: str, **kw) -> OperatorUnit:
    """按属性计算器的结果造一个 OperatorUnit（与 CLI 一致的取数路径）。"""
    st = calc.stats(char_id, **kw)
    t = st.total
    aspd = attack_speed_bonus(
        calc, char_id, elite=kw.get("elite", 2), level=kw.get("level", 1),
        potential=kw.get("potential", 1), module=kw.get("module"),
        module_level=kw.get("module_level", 0))
    return OperatorUnit(
        name=st.name, char_id=char_id, elite=kw.get("elite", 2),
        max_hp=float(t["maxHp"]), atk=float(t["atk"]), defense=float(t["def"]),
        res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100) + aspd.flat,
        aspd_when_free=aspd.when_free,
    )


# ------------------------------------------------------------------ 各项检查

def check_baseline(stage, lib, calc) -> None:
    """1-7 三条阵容、不开技能。

    **这里的 137.0s 是"退化范围"那条路的数**：本函数不传 `range_provider`，
    模拟器于是退回 `_range_of` 里那个「自身格 + 朝向前方三格」的近似。
    接上真实攻击范围（`range.Provider` + gamedata `range_table.json`）
    同一阵容是 **133.0s**——击杀数与总伤害完全相同，只差覆盖格数。
    本节锚的是**旧路径没被改坏**（技能系统是后加进来的），不是精度；
    精度的锚在 `tools/check_verify.py`，那两条例都锚。
    """
    print("\n[1] 1-7 无技能基线（回归坐标）")
    sim = BattleSimulator(stage, enemy_at=lib.get)
    sim.plan(Deployment(1.0, make_unit(calc, "char_002_amiya", elite=2, level=80,
                                       trust=100, potential=6), (5, 2), "Left"))
    sim.plan(Deployment(5.0, make_unit(calc, "char_102_texas", elite=2, level=1),
                        (4, 3), "Right"))
    sim.plan(Deployment(9.0, make_unit(calc, "char_140_whitew", elite=2, level=1),
                        (2, 3), "Right"))
    r = sim.run()
    print(f"         {r.summary()}")
    check("胜利", r.won)
    check("击杀 41", r.kills == 41, f"实得 {r.kills}")
    check("漏怪 0", r.leaks == 0, f"实得 {r.leaks}")
    check("阵亡 0", r.operator_deaths == 0, f"实得 {r.operator_deaths}")
    check("总伤害 60750", close(r.damage_dealt, 60750, 1),
          f"实得 {r.damage_dealt:,.0f}")
    check("耗时 137.0s", close(r.elapsed, 137.0, 0.2), f"实得 {r.elapsed:.1f}s")


def check_calibration(stage, lib, calc, book) -> None:
    """怒潮凛冬单干员——用户提供的实机通关录像。"""
    print("\n[2] 1-7 实机录像用例（怒潮凛冬 精英2 60级，单干员）")
    print("         录像：41 击杀、0 漏、胜利。模拟耗时 142.0s vs 实机 140s（移速校准）")

    def fresh():
        return make_unit(calc, "char_1051_headb2", elite=2, level=60)

    sim = BattleSimulator(stage, enemy_at=lib.get, skill_book=book)
    sim.plan(Deployment(17.0, fresh(), (2, 3), "Right", skill=2, skill_mastery=3))
    raw = sim.run()
    print(f"         只按黑板：{raw.summary()}")

    lv = book.for_operator("char_1051_headb2")[1].level(7, 3)
    esc = lv.effects.with_variant("second")
    check("变体 [second] 被解析出来", lv.effects.variant_names() == ["second"],
          f"实得 {lv.effects.variant_names()}")
    check("第二次起攻击力增益翻倍（0.9→1.8）",
          close(esc.atk_pct, 1.8, 1e-9), f"实得 {esc.atk_pct}")
    check("第二次起防御力增益翻倍（0.6→1.2）",
          close(esc.buffs.get("def", 0), 1.2, 1e-9),
          f"实得 {esc.buffs.get('def', 0)}")

    import copy
    permanent = copy.deepcopy(lv)
    permanent.effects = esc
    permanent.duration = None      # 「持续时间无限」黑板里没有，只能手工给
    sim2 = BattleSimulator(stage, enemy_at=lib.get, skill_book=book)
    sim2.plan(Deployment(17.0, fresh(), (2, 3), "Right", skill=permanent))
    r = sim2.run()
    print(f"         叠加变体：{r.summary()}")
    check("击杀 41（与录像一致）", r.kills == 41, f"实得 {r.kills}")
    check("漏怪 0（与录像一致）", r.leaks == 0, f"实得 {r.leaks}")
    check("总伤害 60750（= 全部 41 只敌人血量之和）",
          close(r.damage_dealt, 60750, 1), f"实得 {r.damage_dealt:,.0f}")
    check("只按黑板会明显少杀（说明差距来自变体而非别处）",
          raw.kills < r.kills, f"{raw.kills} < {r.kills}")


def check_parsing(book) -> None:
    """技能解析的定点值——这些数错了伤害就会错一个量级。"""
    print("\n[3] 技能解析定点值")

    lv = book.for_operator("char_4230_mcnist")[2].level(7, 3)
    total = lv.effects.attack_power(1.0)
    check("机械师「工程学十字星」总倍率 9.88 =（1+2.8）×2.6",
          close(total, 9.88, 1e-6), f"实得 {total:.4f}")
    check("  平A取 attack@atk_scale 而非裸 atk_scale",
          close(lv.effects.atk_scale, 2.6, 1e-9),
          f"实得 {lv.effects.atk_scale}")
    check("  裸 atk_scale（冲锋段）另存不丢",
          close(lv.effects.atk_scale_other or 0, 3.0, 1e-9),
          f"实得 {lv.effects.atk_scale_other}")
    check("  攻击间隔 +2.3s 是加算秒数",
          close(lv.effects.attack_interval(1.8), 4.1, 1e-6),
          f"实得 {lv.effects.attack_interval(1.8):.2f}s")

    lv = book.for_operator("char_1032_excu2")[0].level(7, 3)
    check("圣约送葬人「遗嘱执行」弹药 8 发", lv.effects.ammo == 8,
          f"实得 {lv.effects.ammo}")
    check("  攻击范围改写为 2-5", lv.range_id == "2-5", f"实得 {lv.range_id}")
    check("  无视防御 400", close(lv.effects.buffs.get("def_penetrate_fixed", 0),
                                  400, 1e-9))

    lv = book.for_operator("char_2027_wang")[2].level(7, 3)
    check("望「天下劫」攻击范围 4-12（写在字段里）", lv.range_id == "4-12",
          f"实得 {lv.range_id}")
    # 「天下劫」是**弹药技**（装有 20 发弹药），不是无限持续。这里原来断言
    # `duration = -1 ⇒ 无限持续`——那是拿 `duration is None` 当判据的旧读法，
    # 已被 `SkillLevel.infinite` 的注释否掉：同样长这样的还有"瞬发"。
    # 改成按 `durationType` 与弹药数断言，真无限另找标本（圣聆初雪技2）。
    check("  天下劫是弹药技", lv.duration_type == "AMMO", f"实得 {lv.duration_type}")
    check("  弹药 20 发（写在裸 trigger_time 里）", lv.effects.ammo == 20,
          f"实得 {lv.effects.ammo}")
    check("  弹药技不算无限持续", not lv.infinite)
    check("  真无限：圣聆初雪技2「霜涛覆岭」",
          book.for_operator("char_1046_sbell2")[1].level(7, 3).infinite)
    check("  平A倍率 3.8", close(lv.effects.atk_scale, 3.8, 1e-9))

    lv = book.for_operator("char_002_amiya")[1].level(7, 3)
    check("阿米娅「精神爆发」8 连击 × 60%",
          lv.effects.hit_count == 8 and close(lv.effects.atk_scale, 0.6, 1e-9),
          f"实得 {lv.effects.hit_count}× × {lv.effects.atk_scale}")
    check("  自动回复 100 技力 → 攒满需 100s",
          close(lv.time_to_ready() or 0, 100.0, 1e-6),
          f"实得 {lv.time_to_ready()}")

    lv = book.for_operator("char_1046_sbell2")[0].level(7, 3)
    check("圣聆初雪「铃音吹雪」攻击间隔 +1.5s 之类不影响倍率",
          close(lv.effects.atk_scale, 5.2, 1e-9), f"实得 {lv.effects.atk_scale}")

    # 技力回复方式的三种取值都要认出来
    kinds = {}
    for cid, slot in (("char_002_amiya", 1), ("char_1032_excu2", 1)):
        kinds[cid] = book.for_operator(cid)[slot - 1].level(7, 3).sp_type
    check("自动回复 / 攻击回复 能区分",
          kinds["char_002_amiya"] == "INCREASE_WITH_TIME"
          and kinds["char_1032_excu2"] == "INCREASE_WHEN_ATTACK",
          f"实得 {kinds}")
    passive_book = book.levels("skchr_gravel_1")     # 砾「影袭」，被动
    check("被动技能归一成 PASSIVE（spType 8 不是第四种回复）",
          passive_book and all(l.is_passive for l in passive_book),
          f"实得 {passive_book[0].sp_type if passive_book else '—'}")


def check_coverage(book) -> None:
    print("\n[4] 黑板键归类覆盖率（如实报告，不假装全懂）")
    cov = book.coverage()
    print(f"         {cov['classified']:,} / {cov['total']:,} = "
          f"{cov['coverage'] * 100:.1f}%，未归类 {cov['distinct_unknown']} 种")
    check("覆盖率 ≥ 55%", cov["coverage"] >= 0.55,
          f"实得 {cov['coverage'] * 100:.1f}%")


# ------------------------------------------------------------------ 天赋

def check_talents(book_t) -> None:
    """天赋解析：档位选择、潜能门槛、显式建模的机制。"""
    print("\n[5] 天赋解析")

    e2 = book_t.for_operator("char_1046_sbell2", elite=2, level=90, potential=1)
    snow = find_snow(e2)
    check("圣聆初雪 精2 有积雪天赋", snow is not None,
          snow.name if snow else "无")
    if snow:
        check("精英2 每 5.5 秒积一层", close(snow.value("interval"), 5.5),
              f"实得 {snow.value('interval'):g}")
        check("精英2 单格上限 5 层", close(snow.value("max_cast_cnt"), 5),
              f"实得 {snow.value('max_cast_cnt'):g}")
        check("精英2 每层减速 12%", close(abs(snow.value("move_speed")), 0.12),
              f"实得 {abs(snow.value('move_speed')):g}")
        check("精英2 踏入伤害 75%", close(snow.value("talent_magic_scale"), 0.75),
              f"实得 {snow.value('talent_magic_scale'):g}")

    e0 = book_t.for_operator("char_1046_sbell2", elite=0, level=1, potential=1)
    s0 = find_snow(e0)
    check("精英0 是 10 秒 / 20%", s0 is not None
          and close(s0.value("interval"), 10.0)
          and close(s0.value("talent_magic_scale"), 0.20),
          f"interval={s0.value('interval'):g} scale={s0.value('talent_magic_scale'):g}" if s0 else "无")

    # requiredPotentialRank 是 0 起算：4 表示需要潜能 5
    p5 = find_snow(book_t.for_operator("char_1046_sbell2", elite=2, level=90,
                                       potential=5))
    check("潜能 5 才拿到 +5% 那一档", p5 is not None
          and close(p5.value("talent_magic_scale"), 0.80),
          f"实得 {p5.value('talent_magic_scale'):g}" if p5 else "无")
    p4 = find_snow(book_t.for_operator("char_1046_sbell2", elite=2, level=90,
                                       potential=4))
    check("潜能 4 还拿不到", p4 is not None
          and close(p4.value("talent_magic_scale"), 0.75),
          f"实得 {p4.value('talent_magic_scale'):g}" if p4 else "无")

    # 天赋解锁在精英1：精0 应该**一条都没有**，而不是"数值为 0"
    check("德克萨斯 精0 没有天赋",
          book_t.for_operator("char_102_texas", elite=0, level=1, potential=1) == [])
    tx = book_t.for_operator("char_102_texas", elite=2, level=1, potential=1)
    check("德克萨斯 精2 返初始费 2 点",
          close(squad_cost_bonus(tx), 2.0), f"实得 {squad_cost_bonus(tx):g}")
    check("积雪天赋不会被误认成返费天赋", close(squad_cost_bonus(e2), 0.0),
          f"实得 {squad_cost_bonus(e2):g}")

    # 变体键不能吞掉天赋：阿米娅情绪吸收用 [atk]/[kill] 区分场景
    amiya = book_t.for_operator("char_002_amiya", elite=2, level=80, potential=1)
    check("阿米娅 精2 有情绪吸收", any(t.name == "情绪吸收" for t in amiya),
          "、".join(t.name for t in amiya))
    check("天赋数量不超过天赋组数", len(amiya) == len({t.group for t in amiya}))


def check_snow_field() -> None:
    """积雪机制的单元检查——不依赖关卡数据。"""
    print("\n[6] 积雪机制")

    def hit(raw):                     # 模拟器传进来的伤害函数
        return raw

    sf = SnowField(owner="T", interval=5.5, max_layers=5,
                   slow_per_layer=0.12, magic_scale=0.75)
    ground = [(1, 0), (2, 0)]
    sf.tick(5.5, ground, lambda c: [])
    check("到点积一层", sf.layers.get((1, 0)) == 1 and sf.layers.get((2, 0)) == 1,
          f"实得 {sf.layers}")
    check("未到点不积", sf.tick(5.4, ground, lambda c: []) == 0)
    for _ in range(10):
        sf.tick(5.5, ground, lambda c: [])
    check("单格封顶 5 层", sf.layers[(1, 0)] == 5, f"实得 {sf.layers[(1, 0)]}")
    check("满层减速 60%", close(sf.slow_at((1, 0)), 0.4),
          f"实得 {sf.slow_at((1, 0)):.2f}")
    check("无雪格不减速", close(sf.slow_at((9, 9)), 1.0))

    # 踏入伤害每次一次，不乘层数
    d1 = sf.enter(1, (1, 0), 1000.0, hit)
    check("踏入伤害 = 75% × 攻击力（不乘层数）", close(d1, 750.0), f"实得 {d1:g}")
    d2 = sf.enter(1, (1, 0), 1000.0, hit)
    check("同一格内不重复触发", close(d2, 0.0), f"实得 {d2:g}")
    d3 = sf.enter(2, (1, 0), 1000.0, hit)
    check("换一个敌人踏入会再触发", close(d3, 750.0), f"实得 {d3:g}")

    # 首个敌人离开 → 该格积雪消失。
    # 注意顺序：`enter` 本身就会先判"离开旧格"，所以 1 号从 (1,0) 走到 (2,0)
    # 的那一刻 (1,0) 的雪就该没了，不必等 leave_all。
    sf.enter(2, (1, 0), 1000.0, hit)          # 2 号是后来者
    sf.enter(1, (2, 0), 1000.0, hit)          # 1 号（(1,0) 的首敌）走开
    check("首个敌人离开该格时雪消失", (1, 0) not in sf.layers,
          f"实得 {sorted(sf.layers)}")
    check("它走到的新格雪照旧", (2, 0) in sf.layers, f"实得 {sorted(sf.layers)}")

    # 2 号离开 (2,0) 时，首敌仍是 1 号，不该清雪
    sf.leave_all(2)
    check("非首敌离开不清雪", (2, 0) in sf.layers, f"实得 {sorted(sf.layers)}")
    # 1 号离开才清
    sf.leave_all(1)
    check("首敌离开才清雪", (2, 0) not in sf.layers, f"实得 {sorted(sf.layers)}")


# ------------------------------------------------------------------ 路线分段

def check_routes(stage_sr6, stage_sr8, sr8_map) -> None:
    """路线分段：传送必须切成「离场」段，而不是连成一条横穿地图的折线。"""
    print("\n[7] 路线分段与传送")

    legs = stage_sr6.route(0).legs(walk_map=stage_sr6.map)
    check("SR-6 路线是「等待 + 走」两段",
          [x.kind for x in legs] == ["wait", "walk"],
          "、".join(x.kind for x in legs))
    check("SR-6 待命 3 秒", close(legs[0].seconds, 3.0), f"实得 {legs[0].seconds:g}")
    check("SR-6 走段 12.0 格（沿地块绕行，不是直线 3.2；洞已按不可走处理）",
          abs(legs[1].length - 12.0) < 0.02, f"实得 {legs[1].length:.2f}")

    # 洞（tile_hole）：字段与 tile_floor 等六种完全一致，行为只能靠 tileKey 判，
    # 最容易在别人「顺手放宽 passable 判据」时静默回退，所以钉三条守卫。
    holes = stage_sr6.map.find("tile_hole")
    check("SR-6 的洞在 (6,6)~(9,6) 四格（MAA 口径，y 自上而下）",
          holes == [(6, 6), (7, 6), (8, 6), (9, 6)], f"实得 {holes}")
    check("洞一律按不可走处理（IMPASSABLE_KEYS）",
          all(not stage_sr6.map.walkable(*h) for h in holes),
          "洞仍被当成可走——passable 是 ALL，别只看这一个字段")
    crossed = []
    for r in stage_sr6.used_routes():
        if not r.path:
            continue
        for c in stage_sr6.map.ground_path(r.path[0], r.path[-1]):
            if stage_sr6.map.tile(*c).key == "tile_hole":
                crossed.append(c)
    check("没有路线穿过洞（含斜切墙角）", not crossed, f"仍穿过 {sorted(set(crossed))}")

    r1 = stage_sr8.route(1).legs(walk_map=sr8_map)
    check("SR-EX-8 路线是「等待60 + 走 + 离场1 + 走」四段",
          [x.kind for x in r1] == ["wait", "walk", "vanish", "walk"],
          "、".join(f"{x.kind}{x.seconds:g}" for x in r1))
    check("SR-EX-8 入场待命 60 秒", close(r1[0].seconds, 60.0),
          f"实得 {r1[0].seconds:g}")
    check("SR-EX-8 离场 1 秒", close(r1[2].seconds, 1.0), f"实得 {r1[2].seconds:g}")
    check("传送后从 (6,5) 出发（MAA 口径）", r1[3].points[0] == (6, 5),
          f"实得 {r1[3].points[0]}")
    check("传送不会把 (0,2)→(6,5) 连成折线（横穿地图）",
          not any(x.kind == "walk" and (0, 2) in x.points and (6, 5) in x.points
                  for x in r1))
    check("飞行路线只有一段、不传送",
          [x.kind for x in stage_sr8.route(38).legs(walk_map=sr8_map)] == ["walk"],
          "、".join(x.kind for x in stage_sr8.route(38).legs(walk_map=sr8_map)))


def check_leg_walk() -> None:
    """逐帧走一遍分段计划，钉死"段落在走到一半时被误判完成"这个 bug。"""
    print("\n[8] 分段推进")

    legs = [RouteLeg("wait", (), 3.0, 0.0),
            RouteLeg("walk", ((0, 0), (10, 0)), 10.0, 10.0)]
    e = EnemyUnit(name="T", max_hp=100, atk=0, defense=0, res=0,
                  move_speed=1.0, legs=legs)
    fps, dt = 30, 1.0 / 30
    # 3 秒待命：走 2.9 秒时还在 wait 段
    for _ in range(int(2.9 * fps)):
        e.advance(dt, 1.0)
    check("待命 2.9 秒时仍在第一段", e.leg_index == 0,
          f"实得段 {e.leg_index}，位置 {e.position}")
    check("待命期间不移动", close(e.position[0], 0.0), f"实得 {e.position[0]:.2f}")
    for _ in range(int(0.2 * fps)):
        e.advance(dt, 1.0)
    check("满 3 秒后进入走段", e.leg_index == 1, f"实得段 {e.leg_index}")

    # 走段全长 10 格、移速 1.0 → 约 10 秒；这是"走过一半"的关键区
    for _ in range(int(5.0 * fps)):
        e.advance(dt, 1.0)
    check("走了 5 秒不该判定走完（曾在此处提前完成）",
          e.leg_index == 1 and 4.8 < e.position[0] < 5.2,
          f"段 {e.leg_index}，位置 {e.position[0]:.2f}")
    for _ in range(int(5.2 * fps)):
        e.advance(dt, 1.0)
    check("满 10 格后到达终点", e.reached_end and close(e.position[0], 10.0),
          f"位置 {e.position[0]:.2f}，到达={e.reached_end}")
    check("走段总进度是全长而不是一半", close(e.progress, 10.0),
          f"实得 {e.progress:.2f}")

    # 离场段：时间不被移速缩放
    legs2 = [RouteLeg("vanish", (), 1.0, 0.0),
             RouteLeg("walk", ((0, 0), (1, 0)), 1.0, 1.0)]
    e2 = EnemyUnit(name="T2", max_hp=100, atk=0, defense=0, res=0,
                   move_speed=0.25, legs=legs2)
    e2.advance(dt, 1.0)
    check("离场段首帧就标记为不在地图上", e2.off_map)
    for _ in range(int(1.1 * fps)):
        e2.advance(dt, 1.0)
    check("慢速敌人的 1 秒离场仍是 1 秒（不被移速拉长）",
          e2.leg_index == 1, f"实得段 {e2.leg_index}")


# ------------------------------------------------------------------ 入口

def check_ranged_stop(stage, lib, calc) -> None:
    """远程敌人**不会永久停下**——判据是 1-7 的实机录像。

    这条规则的来历值得写下来，因为它改过一次口径：

    `applyWay == "RANGED"` 的敌人原先被读成「锁到目标就中止路线推进」，
    于是 1-7 的 4 只鸡尾酒投掷者（射程 1.75）永久停在怒潮凛冬 1-1 范围
    之外——她够不着，只能挨打，模拟给出「37 杀 4 漏 3 阵亡 343.9s」，
    而实机同配置录像（单干员）是 **41 杀 0 漏**。若那条读法成立，她
    永远打不到那 4 只，必然漏 4，录像不该是 0 漏。

    与博士确认后改成：**不会永久停，边走边打，只在攻击动作期间停一下**。

    攻击动作长度不在 gamedata 里（`enemy_windup` 是模拟器给的值），
    所以这里顺带做敏感性扫描——结论不能只挂在某一个数上。
    """
    print("\n[9] 远程敌人：边走边打，不永久停（1-7 实机录像为判据）")

    def run(windup: float):
        sim = BattleSimulator(stage, enemy_at=lib.get, enemy_windup=windup)
        sim.plan(Deployment(1.0, make_unit(calc, "char_002_amiya", elite=2,
                                           level=80, trust=100, potential=6),
                            (5, 2), "Left"))
        sim.plan(Deployment(5.0, make_unit(calc, "char_102_texas", elite=2,
                                           level=1), (4, 3), "Right"))
        sim.plan(Deployment(9.0, make_unit(calc, "char_140_whitew", elite=2,
                                           level=1), (2, 3), "Right"))
        return sim.run()

    for windup in (0.0, 0.25, 0.5, 1.0):
        r = run(windup)
        print(f"         攻击动作 {windup:.2f}s：{r.summary()}")
        check(f"  动作 {windup:.2f}s 时仍 41 杀", r.kills == 41,
              f"实得 {r.kills}")
        check(f"  动作 {windup:.2f}s 时仍 0 漏", r.leaks == 0,
              f"实得 {r.leaks}")

    # 反例守卫：把动作时间拉到 60 秒，等于「一开枪就站桩到死」——
    # 也就是被否掉的那条旧读法。它必须跑不出 41 杀，否则这条检查
    # 根本没有分辨力（等于什么都没测）。
    bad = run(60.0)
    print(f"         反例（动作 60s ≈ 永久停）：{bad.summary()}")
    check("  旧读法（永久停）确实打不出 41 杀", bad.kills < 41,
          f"实得 {bad.kills}")


def check_effect_source(stage, lib, calc, book) -> None:
    """[10] 描述驱动结算：同一关同一配置，三种效果来源对比。

    标本是芳汀技1「攻击变为二连击」——**黑板里没有 `times`**，连击只写在
    描述正文里。所以：只读黑板是 1 段，描述驱动是 2 段，伤害差约 12%。
    另一头是德克萨斯技2「对范围内的所有敌人造成2次…」，那是技能自己的
    一次性范围多段，**不能**并进平A——同一套规则必须把两者分开。
    """
    print("\n[10] 描述驱动结算（effect_source）")

    def make(char_id: str):
        return make_unit(calc, char_id, elite=2, level=1)

    # —— 该并的：平A变二连击
    lv = book.for_operator("char_271_spikes")[0].level(7, 3)
    desc = lv.formula_effects()
    check("芳汀技1：黑板确实没有 times",
          lv.effects.damage.get("times") is None,
          f"实得 {lv.effects.damage.get('times')}")
    check("描述解出二连击", desc.hit_count == 2, f"实得 {desc.hit_count}")
    check("且作用域判为平A（attack）", desc.hit_scope == "attack",
          f"实得 {desc.hit_scope!r}")

    runs = {}
    for mode in ("blackboard", "merge", "desc"):
        sim = BattleSimulator(stage, enemy_at=lib.get, skill_book=book,
                              effect_source=mode)
        sim.plan(Deployment(1.0, make("char_271_spikes"), (2, 3), "Right",
                            skill=1, skill_mastery=3))
        runs[mode] = sim.run()
        print(f"         {mode:<10} {runs[mode].summary()}")
    b, m = runs["blackboard"], runs["merge"]
    # 2026-09-16 起「攻击变为 N 连击」落在 `SkillEffects.multi_hit` 上，
    # 与 `repeat_hits` / `true_damage` **同层**——这三个字段都在
    # `_parse_level` 里由描述赋值。于是**三种 effect_source 都会并进连击**，
    # 不再有「黑板驱动少一半」的差异。
    #
    # 原先这里断的是 `m.damage_dealt > b.damage_dealt` 与 `m.leaks < b.leaks`
    # （描述驱动更优），那是 `multi_hit` 只存在于 formula 层时的表现。
    # 现在如实改成三者相等：**这不是回归，是黑板驱动也变正确了**。
    # 描述编译层的价值改由上面那条「描述解出二连击」（`desc.hit_count == 2`）
    # 钉住——它测的是编译层本身，不受结算层这层影响。
    check("三种效果来源都把连击并进了结算（同层，故相等）",
          b.damage_dealt == m.damage_dealt == runs["desc"].damage_dealt,
          f"{b.damage_dealt:,.0f} / {m.damage_dealt:,.0f} / "
          f"{runs['desc'].damage_dealt:,.0f}")
    check("且连击确实生效（伤害为正、编译层为 2 连击）",
          b.damage_dealt > 0 and desc.hit_count == 2,
          f"hit_count={desc.hit_count}  伤害 {b.damage_dealt:,.0f}")
    check("三种模式漏怪数一致", b.leaks == m.leaks == runs["desc"].leaks,
          f"{b.leaks} / {m.leaks} / {runs['desc'].leaks}")
    check("两种模式都胜利", b.won and m.won, f"{b.won} / {m.won}")
    check("`desc` 与原黑板一致或更强（此例二者相同）",
          runs["desc"].damage_dealt >= b.damage_dealt,
          f"{runs['desc'].damage_dealt:,.0f}")

    # —— 不该并的：一次性范围多段
    dl = book.for_operator("char_102_texas")[1].level(7, 3)
    dd = dl.formula_effects()
    check("德克萨斯技2：描述里的 2 次被识别为技能自己的多段",
          dd.hit_scope == "skill", f"实得 {dd.hit_scope!r}")
    merged, _ = dl.resolved_effects("merge")
    check("一次性范围多段不并入平A（命中数仍为 1）",
          merged.hit_count == 1, f"实得 {merged.hit_count}")

    # —— 元素损伤：黑板完全没有这条轴，描述给了就要记下来
    ep = book.for_operator("char_4148_philae")[1].level(7, 3)
    de = ep.formula_effects()
    if de.ep_damage:
        check("元素损伤被解出来", bool(de.ep_damage), str(de.ep_damage))
        me, _ = ep.resolved_effects("merge")
        check("元素损伤进了效果对象的 other（供后续结算取用）",
              any(k.startswith("ep_damage@") for k in me.other),
              str([k for k in me.other if k.startswith("ep_")]))


def check_damage_rulings() -> None:
    """把博士 2026-09-16 的两条裁定**钉成断言**，防止被"顺手改回去"。

    两条都是那种"改了不会报错、只会让数字悄悄变错"的口径：
    * 法术伤害的 5% 保底（此前只有物理有）——SR-EX-8 的「吓人路灯」法抗 99，
      无保底吃 1%、有保底吃 5%，**差五倍**；
    * 攻速下限 20——不夹的话减速叠满会把攻击间隔拉到无穷大。

    第三条断言（法抗 100 仍免疫）是保底的**故意例外**：法抗满值等于免疫是
    另一条独立规则，不该被保底覆盖。若博士日后裁定去掉该例外，这条要一起改。
    """
    from ak_tactic.battle.damage import (DAMAGE_FLOOR, DamageType, arts,       # noqa: E402
                                         physical, resolve_damage)
    from ak_tactic.operator.skill import ASPD_MIN, SkillEffects               # noqa: E402

    check("保底比例是 5%", close(DAMAGE_FLOOR, 0.05), f"实得 {DAMAGE_FLOOR}")
    check("物理有保底（ATK1000 打 DEF5000 仍打出 5%）",
          close(physical(1000, 5000).final, 50.0), f"实得 {physical(1000, 5000).final}")
    check("法术**也**有保底：RES 99 吃 5% 而不是 1%",
          close(arts(1000, 99).final, 50.0) and arts(1000, 99).floored,
          f"实得 {arts(1000, 99).final}")
    check("RES 90 仍按 10% 算，没被保底顶上",
          close(arts(1000, 90).final, 100.0) and not arts(1000, 90).floored,
          f"实得 {arts(1000, 90).final}")
    check("RES 100 是**免疫**，保底不覆盖它（故意的例外）",
          close(arts(1000, 100).final, 0.0), f"实得 {arts(1000, 100).final}")
    check("RES -100 受双倍伤害",
          close(arts(1000, -100).final, 2000.0), f"实得 {arts(1000, -100).final}")
    check("真实伤害无保底（ATK1000 打防御 5000 仍是 1000）",
          close(resolve_damage(1000, damage_type=DamageType.TRUE,
                               defense=5000, res=100).final, 1000.0))

    check("攻速下限是 20", close(ASPD_MIN, 20.0), f"实得 {ASPD_MIN}")
    eff = SkillEffects()
    eff.buffs["attack_speed"] = -95          # 100 → 5，必须夹到 20
    check("攻速被减到 5 时夹到 20（间隔 5.0 而不是 20.0）",
          close(eff.attack_interval(1.0, 100.0), 5.0),
          f"实得 {eff.attack_interval(1.0, 100.0)}")
    eff2 = SkillEffects()
    eff2.buffs["attack_speed"] = 50          # 100 → 150
    check("没触发下限时照常折算（100→150 ⇒ 间隔 1.0→0.6667）",
          close(eff2.attack_interval(1.0, 100.0), 100.0 / 150.0),
          f"实得 {eff2.attack_interval(1.0, 100.0)}")


def check_attack_speed(calc) -> None:
    """攻速链路：天赋 + 模组特性 → 出手间隔。

    2026-09-16 之前这条链是**断的**：`tools/squad.py` 造 `OperatorUnit` 时
    根本没传 `attack_speed`，它一直停在默认的 100；而 `current_interval()`
    在平A 时又直接返回 `attack_interval`、连攻速都不看。赤刃明霄陈是
    SR-EX-8 的主输出，实际总攻速 124，被当成 100 就是出手频率低 24%。

    这一节的数来自攻略录像的实测（BV14yY96mEzt，2 倍速、30fps）：她连续
    攻击的基频是 **15.11 帧**，换算游戏内 **1.008s**，正是「未阻挡」那一档
    （1.25×100/124）；若按 100 算则是 1.25s，相差 24%。
    """
    from ak_tactic.operator.skill import SkillEffects                     # noqa: E402

    print("\n[11] 攻速链路（天赋 + 模组特性 → 出手间隔）")
    chen = "char_1050_chen3"
    full = attack_speed_bonus(calc, chen, elite=2, level=90, potential=6,
                              module="uniequip_002_chen3", module_level=3)
    check("天赋「形意洞照」给 +16 攻速", close(full.flat, 16.0), f"实得 {full.flat}")
    check("模组特性给 +8，且判为**条件性**",
          close(full.when_free, 8.0), f"实得 {full.when_free}")

    bare = attack_speed_bonus(calc, chen, elite=2, level=90, potential=6)
    check("不装模组时只有天赋那 16",
          close(bare.flat, 16.0) and close(bare.when_free, 0.0),
          f"实得 flat={bare.flat} when_free={bare.when_free}")

    e1 = attack_speed_bonus(calc, chen, elite=1, level=80, potential=6,
                            module="uniequip_002_chen3", module_level=3)
    check("精1 拿不到模组特性（解锁条件是精二 60 级）",
          close(e1.when_free, 0.0), f"实得 {e1.when_free}")
    check("天赋档位随精英阶段降为 +11", close(e1.flat, 11.0), f"实得 {e1.flat}")

    low = attack_speed_bonus(calc, chen, elite=2, level=90, potential=1)
    check("潜能 1 只有 +13（+16 那档要潜能 5）",
          close(low.flat, 13.0), f"实得 {low.flat}")

    # 平A 期间也必须按攻速折算——旧实现丢得最干净的一处。
    u = OperatorUnit(name="probe", max_hp=1000.0, atk=100.0, defense=0.0, res=0.0,
                     attack_interval=1.25, attack_speed=116.0, aspd_when_free=8.0)
    check("未阻挡敌人 ⇒ 总攻速 124 ⇒ 间隔 1.0081s",
          close(u.current_attack_speed(), 124.0)
          and close(u.current_interval(), 1.25 * 100 / 124),
          f"实得 {round(u.current_interval(), 4)}s")
    u.blocking = [object()]
    check("一旦挡住敌人 ⇒ 掉回 116 ⇒ 间隔 1.0776s",
          close(u.current_attack_speed(), 116.0)
          and close(u.current_interval(), 1.25 * 100 / 116),
          f"实得 {round(u.current_interval(), 4)}s")

    plain = OperatorUnit(name="plain", max_hp=1000.0, atk=100.0, defense=0.0,
                         res=0.0, attack_interval=1.25)
    check("攻速 100 时折算恒等（对既有三关基线零影响）",
          close(plain.current_interval(), 1.25), f"实得 {plain.current_interval()}")

    eff = SkillEffects()
    check("技能不给攻速 buff 时，常驻 124 照样参与折算",
          close(eff.attack_interval(1.25, 124.0), 1.25 * 100 / 124),
          f"实得 {round(eff.attack_interval(1.25, 124.0), 4)}s")


def check_desc_effects(book, book_t) -> None:
    """[12] 只写在描述里的效果：判据与结算。

    这一节守的是 2026-09-16 补的一批建模。它们的**共同点**是：黑板里没有，
    只能从技能正文判断，因此最容易被日后「顺手改成读键名」而静默失效。

    三条已经真实踩过的坑：
    ① `true_damage` 旧判据用「真实伤害」，被附加伤害类的描述**大量误判**
       （装置自爆、脉冲波、「额外造成 50% 攻击力的真实伤害」），
       真判据是「伤害类型变为真实」；
    ② 连击的数值藏在描述里（「攻击变为二连击」），而 `atk_scale_2` 这个键
       在别的干员身上另有含义，**不能按名字通用**；
    ③ `SkillBook` / `TalentBook` 早先都漏了 `char_patch_table.patchChars`，
       术战者与医疗形态的阿米娅**技能和天赋一条都查不到**。
    """
    print("\n[12] 描述驱动的效果（连击 / 真实伤害 / 末击 / 自身代价 / SP）")

    def lv(char_id: str, slot: int, level: int = 7, mastery: int = 3):
        return book.for_operator(char_id)[slot - 1].level(level, mastery)

    # ---- 连击：三种来源各不相同，都要能取到
    a1 = lv("char_1001_amiya2", 1)
    check("阿米娅技1 二连击（描述驱动，黑板无 times）",
          a1.effects.damage.get("times") is None and a1.effects.hit_count == 2,
          f"times={a1.effects.damage.get('times')} "
          f"hit={a1.effects.hit_count}")
    chen1 = lv("char_1050_chen3", 1)
    check("赤刃明霄陈技1 二连击（同为描述驱动）",
          chen1.effects.hit_count == 2, f"实得 {chen1.effects.hit_count}")
    mc1 = lv("char_4230_mcnist", 1)
    check("机械师技1 五连击（黑板 times 优先于描述）",
          mc1.effects.damage.get("times") == 5.0 and mc1.effects.hit_count == 5,
          f"times={mc1.effects.damage.get('times')} hit={mc1.effects.hit_count}")

    # ---- 真实伤害：判据必须是「伤害类型变为真实」
    qimera = lv("char_002_amiya", 3)
    check("奇美拉判为真实伤害（原文写作『伤害类型变为真实』）",
          qimera.effects.true_damage is True,
          f"实得 {qimera.effects.true_damage}")
    check("奇美拉生命上限 +100%",
          qimera.effects.buffs.get("max_hp") == 1.0,
          f"实得 {qimera.effects.buffs.get('max_hp')}")

    # ---- 末击加倍（键名不可通用，只认描述）
    a2 = lv("char_1001_amiya2", 2)
    check("影霄·绝影末击倍率 = 常规的两倍",
          a2.effects.final_hit_scale == a2.effects.atk_scale * 2,
          f"{a2.effects.final_hit_scale} vs {a2.effects.atk_scale}")

    # ---- 技能结束时的自身代价
    burst = lv("char_002_amiya", 2)
    check("精神爆发自身晕眩 10s（裸 stun 键是**自己**晕，不是控敌）",
          burst.effects.self_stun == 10.0, f"实得 {burst.effects.self_stun}")
    check("奇美拉技能结束后强制退场", qimera.effects.self_retreat is True)
    check("技1 无自身代价",
          a1.effects.self_stun == 0.0 and a1.effects.self_retreat is False,
          f"stun={a1.effects.self_stun} retreat={a1.effects.self_retreat}")

    # ---- 天赋「情绪吸收」：**形态专属**，只有中坚术师有
    spa = find_sp_on_action(
        book_t.for_operator("char_002_amiya", elite=2, potential=6))
    check("情绪吸收（潜能 6）为 攻 3 / 杀 10",
          spa is not None and spa.per_attack == 3.0 and spa.per_kill == 10.0,
          f"实得 {spa}")
    spa4 = find_sp_on_action(
        book_t.for_operator("char_002_amiya", elite=2, potential=4))
    check("情绪吸收潜能门槛：潜能 4 仍是 攻 2 / 杀 8",
          spa4 is not None and spa4.per_attack == 2.0 and spa4.per_kill == 8.0,
          f"实得 {spa4}")
    check("术战者形态**没有**情绪吸收（它是青色怒火）",
          find_sp_on_action(book_t.for_operator(
              "char_1001_amiya2", elite=2, potential=6)) is None)

    # ---- 无视法抗：解析出来就必须真的传进结算
    sbell = lv("char_1046_sbell2", 3)
    check("圣聆初雪技3 解析出固定法术穿透 10",
          sbell.effects.buffs.get("res_penetrate_fixed") == 10.0,
          f"实得 {sbell.effects.buffs.get('res_penetrate_fixed')}")


def check_dodge(book) -> None:
    """[13] 闪避：编译层 / 判据层 / 结算层三层同口径，且**不误认**。

    批次一（⑤）新建的链路。补这一节的原因很实在：这条链路**此前全套自检里
    一条守卫都没有**——只有 `_proto/dodge_check.py` 那个探针在管，而探针不进
    套件，等于它坏了没人会知道。文档写着「已完成」，回归上却是裸的。

    三层都要守，任何一层断了都是**静默失效**（当初就是这样漏掉整条链路的）：

    ① `formula.py`：正文里带「的」与不带「的」**各占一半**（赤刃技2 原文就没有
       「的」），旧规则只认带「的」的写法 → 编译层一个项都吐不出来；
    ② `skill.py` 的 `_wants_dodge`：判据必须走**描述**，不能按黑板键名认——
       `chen3_s2[respawn_buff].prob` 与提丰的 `attack@prob` 都叫 `prob`，
       前者是闪避 60%、后者是晕眩 40%，**同名反义**，按键名认必错；
    ③ `damage.resolve_damage`：**期望值法**（博士 2026-09-17 裁定④）——
       伤害 ×(1−闪避率)，不掷骰。掷骰会让同一份作业每次跑出不同结果，
       搜索与回归都不可复现。物理闪避不挡法术、法术闪避不挡物理、
       真实伤害两类都不吃。
    """
    print("\n[13] 闪避（批次一 ⑤）：三层同口径，且不误认")

    # ---- ① 编译层：带「的」与不带「的」都要出项
    for text, want in [
        ("获得50%的物理和法术闪避", "物理/法术闪避"),
        ("获得50%物理和法术闪避", "物理/法术闪避"),      # ← 赤刃的真实写法
        ("获得19%的物理闪避", "物理闪避"),
        ("获得19%物理闪避", "物理闪避"),
        ("获得30%的法术闪避", "法术闪避"),
        ("获得30%法术闪避", "法术闪避"),
    ]:
        got = [t.attr for t in F.parse(text) if t.kind == "dodge"]
        check(f"formula「{text}」出项", got == [want], f"实得 {got}")

    # ---- ② 判据层：数值正确，且三种**故意不认**的写法必须仍是 (0, 0)
    for text, want in [
        ("获得60%物理和法术闪避", (0.6, 0.6)),
        ("获得60%的物理和法术闪避", (0.6, 0.6)),
        ("获得19%（+4%）的物理闪避", (0.19, 0.0)),
        ("获得30%法术闪避", (0.0, 0.3)),
        # 以下三种是**主动放弃**的写法（宁可少认，不要认错），
        # 已记进 docs/uncertainties.md，别顺手"修好"它们。
        ("获得30%的近战物理闪避", (0.0, 0.0)),
        ("有15%的概率闪避敌人的近战物理攻击", (0.0, 0.0)),
        ("治疗友方单位后为其提供持续3秒的10%物理闪避", (0.0, 0.0)),
    ]:
        got = _wants_dodge(text)
        check(f"_wants_dodge「{text}」", got == want, f"实得 {got}")

    # ---- ②b 真实干员：赤刃技2 取到 60%，且它落在 variants 而不是 buffs
    chen2 = book.for_operator("char_1050_chen3")[1].level(7, 3)
    check("赤刃明霄陈技2 取到 60% 物理闪避",
          close(chen2.effects.dodge_phys, 0.6), f"实得 {chen2.effects.dodge_phys}")
    check("赤刃明霄陈技2 取到 60% 法术闪避",
          close(chen2.effects.dodge_arts, 0.6), f"实得 {chen2.effects.dodge_arts}")
    check("技2 的 +300% 攻击力落在 variants（键带 [respawn_buff] 前缀）",
          close(chen2.effects.variants.get("respawn_buff", {}).get("atk", 0.0), 3.0),
          f"实得 {chen2.effects.variants.get('respawn_buff', {}).get('atk')}")
    check("技2 的变体值**不该**混进 buffs",
          close(chen2.effects.buffs.get("atk", 0.0), 0.0),
          f"实得 {chen2.effects.buffs.get('atk')}")

    # ---- ②c 第二个真实用户：阿米娅(近卫)技1「影霄·奔夜」
    # 原文：「…攻击变为二连击，获得{prob:0%}的法术闪避」。
    # **是法术闪避、没有物理**——两个字段要分开验，不能只看"有没有闪避"。
    # 这条是补守卫时新发现的：此前只有中坚术师形态被测过，近卫形态没人管。
    ami1 = book.for_operator("char_1001_amiya2")[0].level(7, 3)
    check("阿米娅(近卫)技1 只有法术闪避（60%），不带物理",
          close(ami1.effects.dodge_arts, 0.6) and close(ami1.effects.dodge_phys, 0.0),
          f"实得 phys={ami1.effects.dodge_phys} arts={ami1.effects.dodge_arts}")

    # ---- ②d 同名反义：提丰的 attack@prob 是晕眩，不能被认成闪避
    ty2 = book.for_operator("char_2012_typhon")[1].level(7, 3)
    check("提丰技2（attack@prob = 晕眩 40%）不产生闪避",
          close(ty2.effects.dodge_phys, 0.0) and close(ty2.effects.dodge_arts, 0.0),
          f"实得 phys={ty2.effects.dodge_phys} arts={ty2.effects.dodge_arts}")

    # ---- ②e 前十名里，除赤刃技2 与阿米娅(近卫)技1 外都不该有闪避
    # （防判据放宽后误伤：这三处的 prob/闪避字样必须各归各位）
    for name, cid in [("圣聆初雪", "char_1046_sbell2"), ("逻各斯", "char_4133_logos"),
                      ("予愿安洁莉娜", "char_1015_aglna2"),
                      ("机械师", "char_4230_mcnist"), ("望", "char_2027_wang"),
                      ("电弧", "char_4195_radian"), ("令", "char_2023_ling"),
                      ("阿米娅(中坚术师)", "char_002_amiya")]:
        bad = [(s.name, s.level(7, 3).effects.dodge_phys,
                s.level(7, 3).effects.dodge_arts)
               for s in book.for_operator(cid)
               if s.level(7, 3).effects.dodge_phys
               or s.level(7, 3).effects.dodge_arts]
        check(f"{name} 的技能都不带闪避", not bad, f"误判 {bad}")

    # ---- ③ 结算层：期望值法的算术
    r = resolve_damage(1000, damage_type=DamageType.PHYSICAL, defense=0.0,
                       dodge_phys=0.6)
    check("物理 1000 ×(1−0.6) = 400（期望值法，不掷骰）",
          close(r.final, 400.0), f"实得 {r.final}")
    check("结算结果里如实记下 dodged", close(r.dodged, 0.6), f"实得 {r.dodged}")
    r2 = resolve_damage(1000, damage_type=DamageType.PHYSICAL, defense=0.0,
                        dodge_arts=0.6)
    check("物理闪避不挡法术、法术闪避不挡物理",
          close(r2.final, 1000.0), f"实得 {r2.final}")
    r3 = resolve_damage(1000, damage_type=DamageType.TRUE, defense=999.0,
                        dodge_phys=0.6, dodge_arts=0.6)
    check("真实伤害两类闪避都不吃", close(r3.final, 1000.0), f"实得 {r3.final}")
    r4 = resolve_damage(1000, damage_type=DamageType.PHYSICAL, defense=0.0,
                        dodge_phys=1.5)
    check("闪避 >1 夹到 1（不会反向加伤）", close(r4.final, 0.0), f"实得 {r4.final}")
    r5 = resolve_damage(1000, damage_type=DamageType.PHYSICAL, defense=100.0)
    check("不传闪避时与改动前逐字一致（三条基线不被波及的前提）",
          close(r5.final, 900.0) and r5.floored is False,
          f"实得 {r5.final} / floored={r5.floored}")


def check_summons(sbook) -> None:
    """[14] 召唤物：链路解析 + 属性取数（批次二的"召唤物"这一件的数据层）。

    守两件事，都是**查错地方就整条取不到**的类型：

    ① `overrideTokenKey` 挂在 **`character_table` 里干员的技能槽**上，
       **不在** `skill_table` 的技能条目上——后者一律 `None`。若日后有人
       "顺手"改成查技能表，这几名干员的召唤物会集体消失且**不报错**；
    ② 属性的**阶段在 phase 上、范围也在 phase 上**，顶层的 `rangeId` 不存在。

    另外钉住上游的一条悬空引用（凛御银灰的 `token_10057_svash2_eagle`）。
    """
    print("\n[14] 召唤物：谁带出谁，以及它的属性")

    for name, cid, want in [
        ("电弧", "char_4195_radian",
         ["token_10051_radian_tower1", "token_10052_radian_tower2",
          "token_10053_radian_tower3"]),
        ("令", "char_2023_ling",
         ["token_10020_ling_soul1", "token_10020_ling_soul2",
          "token_10020_ling_soul3"]),
        ("望", "char_2027_wang", ["token_10064_wang_stone1"]),
        ("机械师", "char_4230_mcnist", ["token_10069_mcnist_mcgraf"]),
        ("圣聆初雪", "char_1046_sbell2", ["token_10058_sbell2_icetgt"]),
        ("予愿安洁莉娜", "char_1015_aglna2", ["token_10071_aglna2_agairp"]),
    ]:
        got = [s.token_key for s in sbook.for_operator(cid)]
        check(f"{name}的召唤物链路（走干员技能槽，不走技能表）", got == want,
              f"实得 {got}")

    # 望的棋子被 3 个技能槽 + 6 个天赋候选项引用，但它是**一件**召唤物
    wang = sbook.for_operator("char_2027_wang")
    check("望的棋子去重成 1 件（不是 9 件）", len(wang) == 1, f"实得 {len(wang)}")
    check("来源合并为 技1/技2/技3/天赋「铸子」",
          wang[0].origins == ("技1", "技2", "技3", "天赋「铸子」"),
          f"实得 {wang[0].origins}")

    # 属性定点值（对上 gamedata 原值）
    a = sbook.attributes("token_10051_radian_tower1", phase=0, level=1)
    check("戴乌 E0L1 = 2001/314/284，18 费，阻挡 3",
          (a.max_hp, a.atk, a.defense, a.cost, a.block_cnt)
          == (2001.0, 314.0, 284.0, 18.0, 3),
          f"实得 {a.max_hp}/{a.atk}/{a.defense}/{a.cost}/{a.block_cnt}")
    a2 = sbook.attributes("token_10051_radian_tower1", phase=2)
    check("戴乌 E2 满级 = 3230/471（默认取该阶段满级）",
          (a2.max_hp, a2.atk) == (3230.0, 471.0), f"实得 {a2.max_hp}/{a2.atk}")
    check("范围取**阶段上**的 rangeId（顶层没有 rangeId）",
          a.range_id == "0-1", f"实得 {a.range_id}")
    check("phase 越界夹到可用范围，不抛错",
          sbook.attributes("token_10051_radian_tower1", phase=9).phase == 2)

    check("召唤物自带技能（棋子有三个不同技能）",
          sbook.skills("token_10064_wang_stone1")
          == ["sktok_wang_1", "sktok_wang_2", "sktok_wang_3"],
          f"实得 {sbook.skills('token_10064_wang_stone1')}")

    check("profession 判据：token 是召唤物、trap 是装置",
          sbook.is_token("token_10051_radian_tower1")
          and not sbook.is_token("trap_001_crate")
          and not sbook.is_token("char_4195_radian"))

    # 上游悬空引用：钉住它，多出一条就要查（与 check_db 的那条呼应）
    dangling = [(cid, s.token_key)
                for cid in sbook._load()
                for s in sbook.for_operator(cid) if s.missing]
    check("全表恰好一条悬空引用（凛御银灰的 svash2_eagle）",
          dangling == [("char_1045_svash2", "token_10057_svash2_eagle")],
          f"实得 {dangling}")
    check("悬空时 name 回落成 key，不静默跳过",
          sbook.for_operator("char_1045_svash2")[0].name
          == "token_10057_svash2_eagle")


def check_summons_battle(stage, lib, calc, book_t) -> None:
    """[15] 召唤物：部署层。

    批次二「召唤物」的第二段。第一段（数据层，`SummonBook`）在 `[14]`，
    这一段管**真放下去**：归属、费用、同时上限、拒收留痕。

    同时上限那条是这一节的**主要价值**：它踩过两个坑——
    ① 天赋黑板里的 `cnt` 是「可以使用 N 个」（**可动用总量**，随精英变），
       不是同时上限；同时上限只在描述文字里（电弧/令恒为 3）；
    ② token 的 `maxDeployCount` **也不能用**——令/深池/梅尔身上是 1，
       取它会把令错压成只能放 1 个。
    两个坑都钉在这里，任何一个被改回去都会当场红。
    """
    print("\n[15] 召唤物：部署层（归属 / 费用 / 同时上限 / 拒收留痕）")

    from ak_tactic.battle.summons import SummonDeployment            # noqa: E402
    from ak_tactic.battle.talents import find_summon_allowance       # noqa: E402

    print("     —— 额度解析：两个数不是一回事 ——")
    for who, cid, want in [("电弧", "char_4195_radian", (5, 3, "同时部署")),
                           ("令", "char_2023_ling", (5, 3, "同时部署")),
                           ("望", "char_2027_wang", (6, 7, "拥有"))]:
        a = find_summon_allowance(book_t.for_operator(cid))
        got = None if a is None else (a.pool, a.simultaneous, a.source)
        check(f"{who}：可动用 {want[0]} / 同时 {want[1]}（来源 {want[2]}）",
              got == want, f"实得 {got}")

    check("深池的文字没写同时上限，如实回落 pool 并标明来源",
          (lambda a: a is not None and a.source == "回落 pool"
           and a.simultaneous == a.pool)(
              find_summon_allowance(book_t.for_operator("char_110_deepcl"))))
    for cid, who in [("char_002_amiya", "阿米娅"), ("char_4230_mcnist", "机械师"),
                     ("char_1046_sbell2", "圣聆初雪")]:
        check(f"{who} 不是召唤者，取不到额度（不猜默认值）",
              find_summon_allowance(book_t.for_operator(cid)) is None)

    print("     —— 真的放下去：戴乌站上 1-7 的路径格 ——")
    R_TAL = book_t.for_operator("char_4195_radian")
    check("电弧的天赋里确有召唤额度（下面几条的前提）",
          find_summon_allowance(R_TAL) is not None)

    sim = BattleSimulator(stage, enemy_at=lib.get)
    sim.plan(Deployment(1.0, make_unit(calc, "char_4195_radian", elite=2, level=90),
                        (5, 2), "Left", talents=R_TAL))
    sim.plan_summon(SummonDeployment(2.0, "token_10051_radian_tower1", (4, 3),
                                     "Right", owner="char_4195_radian"))
    r = sim.run()
    print(f"         {r.summary()}")

    check("放下去 1 个", r.summons_deployed == 1, f"实得 {r.summons_deployed}")
    check("没有被拒收", r.summon_rejected == [], f"实得 {r.summon_rejected}")
    summons = [o for o in sim.operators if o.is_summon]
    check("场上恰好 1 个召唤物", len(summons) == 1, f"实得 {len(summons)}")
    if summons:
        u = summons[0]
        check("归属正确（summon_of = 召唤者 char_id）",
              u.summon_of == "char_4195_radian", f"实得 {u.summon_of!r}")
        check("名字取自 token 表（戴乌）", u.name == "戴乌", f"实得 {u.name!r}")
        # 三个数都锚 phase 2 的**末帧**（L90）。别拿 phase 0 的数来对——
        # 戴乌逐阶段递进：hp 2001→2501→2875→3230，def 284→389→533→683，
        # 拿 E0 满级的 389 当 E2 会凭空多出一条假失败。
        check("属性取自 token 自己 phase 2 的末帧（L90 = 3230/471/683）",
              (u.max_hp, u.atk, u.defense) == (3230.0, 471.0, 683.0),
              f"实得 {u.max_hp:.0f}/{u.atk:.0f}/{u.defense:.0f}")
        check("阻挡 3（照 token 自己的 blockCnt）", u.block_cnt == 3,
              f"实得 {u.block_cnt}")
        check("费用 18（照 token 自己的 cost）", u.deploy_cost == 18,
              f"实得 {u.deploy_cost}")
        check("**真在打架**（出过手或被挡过敌人）",
              u.hits > 0 or bool(u.blocking),
              f"hits={u.hits} blocking={len(u.blocking)}")

    # 费用必须在**部署那一刻**量：整场跑完后费用随时间回复过，差值没有意义。
    sim_c = BattleSimulator(stage, enemy_at=lib.get)
    sim_c._do_deploy(Deployment(1.0, make_unit(calc, "char_4195_radian",
                                               elite=2, level=90),
                                (5, 2), "Left", talents=R_TAL), 1.0)
    # **必须先把费用垫高**：1-7 的初始费用是 0，而部署走的是
    # `max(0, cost - 费)`，两次部署都夹在 0 上，差值恒为 0，什么也测不出来。
    sim_c.cost = 100.0
    before = sim_c.cost
    sim_c._do_deploy_summon(SummonDeployment(
        2.0, "token_10051_radian_tower1", (4, 3), "Right",
        owner="char_4195_radian"), 2.0)
    check("费用在部署那一刻扣掉 18（与干员部署同一口径）",
          close(before - sim_c.cost, 18, 1e-6),
          f"实得 {before - sim_c.cost:g}（{before:g} → {sim_c.cost:g}）")

    print("     —— 同时上限：第 4 个必须被拒收并留痕 ——")
    sim2 = BattleSimulator(stage, enemy_at=lib.get)
    sim2.plan(Deployment(1.0, make_unit(calc, "char_4195_radian", elite=2, level=90),
                         (5, 2), "Left", talents=R_TAL))
    for i, cell in enumerate([(4, 3), (5, 3), (6, 3), (7, 3)]):
        sim2.plan_summon(SummonDeployment(2.0 + i, "token_10051_radian_tower1",
                                          cell, "Right",
                                          owner="char_4195_radian"))
    r2 = sim2.run()
    check("只放下 3 个（电弧的同时上限）", r2.summons_deployed == 3,
          f"实得 {r2.summons_deployed}")
    check("第 4 个被拒收且记了原因", len(r2.summon_rejected) == 1
          and "已达同时部署上限 3" in r2.summon_rejected[0][2],
          f"实得 {r2.summon_rejected}")

    print("     —— 召唤者不在场 / 不是召唤者 ——")
    sim3 = BattleSimulator(stage, enemy_at=lib.get)
    sim3.plan_summon(SummonDeployment(1.0, "token_10051_radian_tower1", (4, 3),
                                      "Right", owner="char_4195_radian"))
    r3 = sim3.run()
    check("召唤者没下场就召唤 → 拒收", r3.summons_deployed == 0
          and len(r3.summon_rejected) == 1
          and "不在场" in r3.summon_rejected[0][2],
          f"实得 {r3.summon_rejected}")

    sim4 = BattleSimulator(stage, enemy_at=lib.get)
    sim4.plan(Deployment(1.0, make_unit(calc, "char_002_amiya", elite=2, level=80),
                         (5, 2), "Left",
                         talents=book_t.for_operator("char_002_amiya")))
    sim4.plan_summon(SummonDeployment(2.0, "token_10051_radian_tower1", (4, 3),
                                      "Right", owner="char_002_amiya"))
    r4 = sim4.run()
    check("阿米娅**带着自己的天赋**仍被拒（她不是召唤者，说明 token_key 写错了）",
          r4.summons_deployed == 0 and len(r4.summon_rejected) == 1
          and "没有召唤额度" in r4.summon_rejected[0][2],
          f"实得 {r4.summon_rejected}")

    print("     —— 不排召唤物时，行为与从前逐字一致 ——")
    sim5 = BattleSimulator(stage, enemy_at=lib.get)
    sim5.plan(Deployment(1.0, make_unit(calc, "char_002_amiya", elite=2, level=80,
                                        trust=100, potential=6), (5, 2), "Left"))
    sim5.plan(Deployment(5.0, make_unit(calc, "char_102_texas", elite=2, level=1),
                         (4, 3), "Right"))
    sim5.plan(Deployment(9.0, make_unit(calc, "char_140_whitew", elite=2, level=1),
                         (2, 3), "Right"))
    r5 = sim5.run()
    check("1-7 三阵容仍是 137.0s / 41 杀 / 0 漏 / 60750（加了召唤物层也没动它）",
          r5.kills == 41 and r5.leaks == 0 and close(r5.damage_dealt, 60750, 1)
          and close(r5.elapsed, 137.0, 0.2),
          f"实得 {r5.elapsed:.1f}s / {r5.kills} / {r5.leaks} / "
          f"{r5.damage_dealt:,.0f}")
    check("召唤物计数为 0", r5.summons_deployed == 0 and r5.summon_rejected == [])


def check_barrier(stage, lib, calc, book, book_t) -> None:
    """[16] 屏障。

    批次二「屏障」这一项。技能交互的第一个落点，选它是因为电弧技1 正好
    同时需要两件事：**屏障机制**与**效果发给召唤物**（召唤物没有技能槽）。

    ## 判据为什么不能按黑板键

    这条**踩过坑，钉在这里**：直觉会想用 `hp_ratio` 这个键，但全表核验下来
    它同名反义——47 个技能有它却与屏障无关（它是「流失/回复/治疗目标 X% 生命」），
    而且即便同时出现「屏障」也不一定是屏障的量：摩根 `hp_ratio=1.5` 确是屏障
    150%，**左乐 `hp_ratio=0.5` 却是流失量**（屏障 120% 只写在正文里）。
    所以判据只能按**渲染后的描述**取，并且要挡住"给别人"的写法。
    """
    print("\n[16] 屏障（技能授予 / 先于生命值消耗 / 发给召唤物）")

    from ak_tactic.battle.summons import (SummonDeployment,       # noqa: E402
                                          build_summon_unit)

    print("     —— 判据的全表指纹：命中谁、放过谁 ——")
    raw = book._load()
    hit: dict[str, float] = {}
    for sid in raw:
        if not book.exists(sid):
            continue
        vals = [lv.effects.barrier_pct for lv in book.levels(sid)]
        if any(vals):
            hit[sid] = max(vals)
    want = {"skchr_radian_1", "skchr_mcnist_2", "skchr_angel2_2",
            "skchr_cairn_2", "skchr_gravel_2", "skchr_judge_3",
            "skchr_morgan_2", "skchr_nasti_2", "skchr_zuole_2",
            "sktok_acspell008_1"}
    check(f"命中恰好 {len(want)} 个技能（多一个少一个都说明判据漂了）",
          set(hit) == want,
          f"多出 {sorted(set(hit) - want)}；少 {sorted(want - set(hit))}")
    check("**电弧在名单里**（本项的主标本）", "skchr_radian_1" in hit)
    check("**机械师也在**（同一条判据顺带覆盖，名单里的第二人）",
          "skchr_mcnist_2" in hit)
    print("       以下四条是「屏障给了别人」——判据必须放过，否则会把队友的算到自己头上：")
    for sid, why in [("skchr_svash2_1", "屏障给待部署区新下的那名干员"),
                     ("skchr_cathy_2", "给目标干员，量纲取的是凯瑟琳自己的生命上限"),
                     ("sktok_cdshield", "「添加相当于其生命上限」——其＝队友"),
                     ("sktok_cdshieldb", "同上")]:
        check(f"放过 {sid}（{why}）", sid not in hit)
    check("傀影技1 是**只吸物理**的屏障，故意不认",
          "skchr_phatom_1" not in hit and "sktok_phatom_1" not in hit)

    print("     —— 电弧技1 的解析（7 级 / 专精 0）——")
    lv = book.levels("skchr_radian_1")[6]
    check("屏障 70% 最大生命值", close(lv.effects.barrier_pct, 0.70, 1e-9),
          f"实得 {lv.effects.barrier_pct}")
    check("防御力 +60%", close(lv.effects.buffs.get("def", 0), 0.60, 1e-9),
          f"实得 {lv.effects.buffs.get('def', 0)}")
    check("主语是「自身和召唤物」→ 效果要发一份给召唤物",
          lv.effects.affects_summons)
    check("满级（10 级）是 100% / 防御 +80%，逐级递增不是常数",
          close(book.levels("skchr_radian_1")[9].effects.barrier_pct, 1.0, 1e-9)
          and close(book.levels("skchr_radian_1")[0].effects.barrier_pct, 0.2,
                    1e-9))
    check("技2/技3 不该有屏障（它们只给攻击力）",
          all(book.levels(s)[6].effects.barrier_pct == 0.0
              for s in ("skchr_radian_2", "skchr_radian_3")))

    print("     —— 机制本体：屏障先扛，扛完才动血条 ——")
    u = OperatorUnit(name="试验体", max_hp=1000.0, atk=10.0, defense=0.0,
                     res=0.0, attack_interval=1.0)
    u.grant_barrier(0.5)
    check("授予 = 50% × **生命上限**（1000） = 500",
          close(u.barrier, 500.0, 1e-9), f"实得 {u.barrier}")
    check("挨 200：血一点不掉", close(u.take(200.0), 0.0) and close(u.hp, 1000.0),
          f"实得 dealt={u.take(0.0)} hp={u.hp}")
    check("屏障剩 300", close(u.barrier, 300.0, 1e-9), f"实得 {u.barrier}")
    dealt = u.take(400.0)
    check("再挨 400：屏障挡 300、血掉 100", close(dealt, 100.0, 1e-9)
          and close(u.hp, 900.0, 1e-9) and u.barrier == 0.0,
          f"实得 dealt={dealt} hp={u.hp} 屏障={u.barrier}")
    check("累计吸收 500（对账用，且**不计入** damage_taken）",
          close(u.barrier_absorbed, 500.0, 1e-9)
          and close(u.damage_taken, 100.0, 1e-9),
          f"实得 吸收={u.barrier_absorbed} damage_taken={u.damage_taken}")
    check("重复授予取较大值、不累加（同一技能不该叠上去）",
          (lambda v: (v.grant_barrier(0.3), v.grant_barrier(0.2),
                      close(v.barrier, 300.0, 1e-9))[2])(u))

    print("     —— 进战斗：发给自己**和召唤物** ——")
    R_TAL = book_t.for_operator("char_4195_radian")
    sim = BattleSimulator(stage, enemy_at=lib.get, skill_book=book)
    op = make_unit(calc, "char_4195_radian", elite=2, level=90)
    sim.plan(Deployment(1.0, op, (5, 2), "Left", skill=1, skill_level=7,
                        talents=R_TAL))
    sim.plan_summon(SummonDeployment(2.0, "token_10051_radian_tower1", (4, 3),
                                     "Right", owner="char_4195_radian"))
    ok = True
    try:
        r = sim.run()
    except Exception as exc:                                    # noqa: BLE001
        ok = False
        check("开技1 跑得完（不抛错）", False, f"{type(exc).__name__}: {exc}")
    tower = [o for o in sim.operators if o.is_summon]
    if ok:
        check("开技1 跑得完（不抛错）", True)
        check("技能确实开成了", r.skill_activations >= 1,
              f"实得 {r.skill_activations}")
        if tower:
            sm = tower[0]
            check("戴乌也拿到了屏障（效果发下去了）",
                  sm.barrier_absorbed > 0.0 or sm.barrier > 0.0,
                  f"实得 吸收={sm.barrier_absorbed:.1f} 剩={sm.barrier:.1f}")
            check("两边至少一边真吸收了伤害",
                  sm.barrier_absorbed > 0.0 or op.barrier_absorbed > 0.0,
                  f"主人 {op.barrier_absorbed:.1f} / 召唤物 "
                  f"{sm.barrier_absorbed:.1f}")

    # 技能结束清零：**直接调** `_activate` / `_deactivate`，不走帧网格。
    # 第一版把这条挂在整场跑完去看 `op.barrier`，结果是假红——电弧技1 是自动
    # 技能，跑完时她正好开着第二次，屏障是新授予的那一份。这类"结束态"的断言
    # 不该依赖"跑完那一刻恰好是什么状态"。
    print("     —— 技能结束：屏障一起清（直接调，不依赖帧网格）——")
    sim2 = BattleSimulator(stage, enemy_at=lib.get, skill_book=book)
    op2 = make_unit(calc, "char_4195_radian", elite=2, level=90)
    op2.skill = book.levels("skchr_radian_1")[6]
    op2.talents = list(R_TAL)
    op2.position, op2.direction = (5, 2), "Left"
    sm2 = build_summon_unit(SummonDeployment(
        0.0, "token_10051_radian_tower1", (4, 3), "Right",
        owner="char_4195_radian"))
    sim2.operators.extend([op2, sm2])
    sim2._activate(op2, 0.0)
    check("开着技能时：主人有屏障、召唤物也有",
          op2.barrier > 0.0 and sm2.barrier > 0.0,
          f"实得 主人={op2.barrier:.1f} 召唤物={sm2.barrier:.1f}")
    check("主人屏障 = 70% × 她自己的生命上限",
          close(op2.barrier, 0.70 * op2.max_hp, 1e-6),
          f"实得 {op2.barrier:.1f} vs {0.70 * op2.max_hp:.1f}")
    check("召唤物屏障 = 70% × **它自己的**生命上限（不是主人的）",
          close(sm2.barrier, 0.70 * sm2.max_hp, 1e-6)
          and abs(sm2.max_hp - op2.max_hp) > 1.0,
          f"实得 {sm2.barrier:.1f} vs {0.70 * sm2.max_hp:.1f}"
          f"（主人 {0.70 * op2.max_hp:.1f}）")
    sim2._deactivate(op2, 25.0)
    check("技能结束：两边屏障一起归零",
          op2.barrier == 0.0 and sm2.barrier == 0.0,
          f"实得 主人={op2.barrier} 召唤物={sm2.barrier}")


def main() -> int:
    ap = argparse.ArgumentParser(description="战斗与技能的回归检查")
    ap.parse_args()

    src = GameDataSource()
    stage = load_stage("1-7", source=src)
    sr6 = load_stage("act54side_06", source=src)
    sr8 = load_stage("act54side_ex08", source=src)
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    book = SkillBook()
    book_t = TalentBook()
    sbook = SummonBook()

    check_baseline(stage, lib, calc)
    check_damage_rulings()
    check_calibration(stage, lib, calc, book)
    check_parsing(book)
    check_coverage(book)
    check_talents(book_t)
    check_snow_field()
    check_routes(sr6, sr8, sr8.map)
    check_leg_walk()
    check_ranged_stop(stage, lib, calc)
    check_effect_source(stage, lib, calc, book)
    check_attack_speed(calc)
    check_desc_effects(book, book_t)
    check_dodge(book)
    check_summons(sbook)
    check_summons_battle(stage, lib, calc, book_t)
    check_barrier(stage, lib, calc, book, book_t)

    print(f"\n通过 {_PASSED} 项", end="")
    if _FAILED:
        print(f"，失败 {len(_FAILED)} 项：")
        for f in _FAILED:
            print(f"  - {f}")
        return 1
    print("，无失败。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
