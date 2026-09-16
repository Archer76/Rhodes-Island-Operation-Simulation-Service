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
from ak_tactic.battle.talents import SnowField, find_snow, squad_cost_bonus  # noqa: E402
from ak_tactic.operator.attack_speed import attack_speed_bonus      # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                      # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.gamedata.stage import RouteLeg                        # noqa: E402
from ak_tactic.battle.unit import EnemyUnit                          # noqa: E402
from ak_tactic.operator import (                                    # noqa: E402
    OperatorCalculator, SkillBook, TalentBook,
)

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
    check("描述驱动把连击并进了结算（总伤害更高）",
          m.damage_dealt > b.damage_dealt,
          f"{m.damage_dealt:,.0f} vs {b.damage_dealt:,.0f}")
    check("描述驱动少漏怪", m.leaks < b.leaks, f"{m.leaks} < {b.leaks}")
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
