"""战斗与技能的回归检查。

跑法：`python tools/check_battle.py`，全过返回 0。

这里检查的是**能被证伪的东西**，而不是"跑起来没报错"：

1. **1-7 无技能基线**——三条既有阵容必须还是 137.0s / 41 击杀 / 0 漏 /
   总伤害 60750。技能系统是后加进来的，这一条防的是"新代码改坏了旧路径"。
2. **技能解析的定点值**——机械师的总倍率必须是 9.88（(1+2.8)×2.6），
   这个数有社区标定作对照；取错黑板键会算成 11.4。
3. **1-7 实机录像用例**——用户提供的单干员（怒潮凛冬）通关录像：
   41 击杀 / 0 漏 / 总伤害 60750。

   ⚠️ **这条的判据 2026-09-18 换过一次**：原来靠「只按黑板只有 35 杀、
   叠上「第二次及以后」的变体才到 41 杀」来证明变体解析是对的。撼地者
   特性溅射落地后，只按黑板那一局**也**打满 41 杀——溅射把变体少掉的那部分
   伤害补回来了，于是"少杀"不再能证明任何事。现在盯的是变体独有、且与
   本条机制无关的那一项：没叠变体要开两次技能（30 秒到点掉线重充），
   叠上只开一次（「持续时间无限」）。**旧判据不是被放宽，是被换掉。**

第 3 条要说明白：`headb2_s_2[second].atk = 1.8` 是黑板里真实存在的键，
所以"第二次起加成翻倍"**不是**靠描述文本猜的；但"且持续时间无限"那半句
黑板里确实没有，只能由调用方手工把 duration 置为 None。
"""

from __future__ import annotations

import argparse
import inspect
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator, Deployment           # noqa: E402
from ak_tactic.battle.damage import DamageType, resolve_damage      # noqa: E402
from ak_tactic.battle.talents import (BLESSING_KEYS, SnowField, find_blessing,
                                      find_snow, find_sp_on_action,
                                      squad_cost_bonus)  # noqa: E402
from ak_tactic.battle.traits import (apply_splash_talent,  # noqa: E402
                                     read_trait_splash)
from ak_tactic.operator.attack_speed import attack_speed_bonus      # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                      # noqa: E402
from ak_tactic.battle import displace as D                          # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.gamedata.stage import RouteLeg                        # noqa: E402
from ak_tactic.battle.unit import EnemyUnit, point_at                          # noqa: E402
from ak_tactic.operator import (                                    # noqa: E402
    OperatorCalculator, SkillBook, SummonBook, TalentBook,
)
from ak_tactic import formula as F                                   # noqa: E402
from ak_tactic.operator.skill import _classify, _wants_dodge                    # noqa: E402

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


_TALENT_BOOK: list = []


def _talent_book() -> TalentBook:
    """检查侧共用一个 `TalentBook`（构造要读 char_table，不该每个单位读一遍）。"""
    if not _TALENT_BOOK:
        _TALENT_BOOK.append(TalentBook())
    return _TALENT_BOOK[0]


def make_unit(calc, char_id: str, **kw) -> OperatorUnit:
    """按属性计算器的结果造一个 OperatorUnit（与 CLI 一致的取数路径）。"""
    st = calc.stats(char_id, **kw)
    t = st.total
    aspd = attack_speed_bonus(
        calc, char_id, elite=kw.get("elite", 2), level=kw.get("level", 1),
        potential=kw.get("potential", 1), module=kw.get("module"),
        module_level=kw.get("module_level", 0))
    # 特性溅射（撼地者）也要在这里落地。**不能少这一块**：检查侧的单位若比
    # 真路径少一层，每个用例都得自己记得补，而漏掉的表现是"机制看着做了、
    # 守卫里却永远不触发"——那正是本项目反复踩过的坑。真路径是
    # `Verifier.unit()`，两边的口径靠 `[36]` 那条端到端断言钉住。
    splash = apply_splash_talent(
        read_trait_splash(calc.character(char_id)),
        _talent_book().for_operator(char_id, elite=kw.get("elite", 2),
                                    level=kw.get("level", 1),
                                    potential=kw.get("potential", 1)))
    return OperatorUnit(
        name=st.name, char_id=char_id, elite=kw.get("elite", 2),
        # 主职业代号——按职业发光环的天赋（星熊「特种作战策略」）要它。
        profession=str(calc.character(char_id).get("profession") or ""),
                      nation_id=str(calc.character(char_id).get("nationId") or ""),
        max_hp=float(t["maxHp"]), atk=float(t["atk"]), defense=float(t["def"]),
        res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100) + aspd.flat,
        aspd_when_free=aspd.when_free,
    aspd_high_ground=aspd.when_high_ground,
    splash_radius=splash.radius if splash else 0.0,
    splash_scale=splash.scale if splash else 0.0,
    splash_damage_scale=splash.damage_scale if splash else 1.0,
    highland_splash_scale=splash.highland_scale if splash else 0.0,
    highland_splash_sluggish=splash.highland_sluggish if splash else 0.0,
    )


# ------------------------------------------------------------------ 各项检查

def mechanism_sim(stage, lib, **kw):
    """给**测某一项机制**的用例建模拟器：费用与再部署口径一律钉在 `legacy`。

    这些用例测的是攻速、索敌、召唤物上限、屏障之类的东西——费用与再部署规则
    对它们是**噪声**。让它们跟着默认值漂，等于每改一次口径就要重审几十条与
    该口径无关的断言，而且失败信息会指向错误的方向（"召唤物上限错了"其实是
    "钱不够"）。

    两条真基线（`[1]` 1-7 三阵容、`[2]` 怒潮凛冬录像）**不**走这个助手：
    它们本来就该跟随默认口径，口径一改就该跟着重生成。
    """
    kw.setdefault("cost_mode", "legacy")
    kw.setdefault("redeploy_mode", "legacy")
    return BattleSimulator(stage, enemy_at=lib.get, **kw)


def _dummy(sim, stage, eid: str, cell, *, progress: float = 0.0,
           hp: float = 1_000_000.0):
    """在 `cell` 上放一只**站着不动**的受控靶子（受击、被挡、被溅射都用它）。

    路线只有一格、长度为 0 ⇒ **一推进就算"走到终点"漏出场**。所以拿它当靶子
    时**不要跑 `run()`**，直接驱动要测的那一步（`docs/uncertainties.md`
    §二十之二里记过这个坑：靶子没了，会被读成"机制没生效"）。

    血量默认给到一百万，是为了让多次出手都落在**同一只**还活着的目标上——
    靶子被打死会让"第二个目标有没有吃到"这类断言静默变成"没目标"。
    """
    pts = [(float(cell[0]), float(cell[1]))]
    e = sim._build_enemy(eid, 1, pts,
                         [RouteLeg(kind="walk", points=pts, length=0.0)],
                         0.0, 0.0)
    e.position = (float(cell[0]), float(cell[1]))
    e.progress = progress
    e.max_hp = e.hp = hp
    sim.enemies.append(e)
    return e


def check_baseline(stage, lib, calc) -> None:
    """1-7 三条阵容、不开技能。**部署时刻已按真实费用机制重排。**

    **2026-09-18 重生成**：模拟器补上费用闸门后，原来那三个时刻
    （1.0 / 5.0 / 9.0s）**做不出来**——1-7 初始 10 费、1 秒回 1 点，而三个人是
    18 / 13 / 19 费共 50 费，要到第 40 秒才攒得齐。旧口径是「显式时刻即照办、
    费用夹到 0」，等于**替玩家免了 39 秒的费**。实测台账（`BattleResult.
    cost_denied`）逐笔为：

        1.0s  阿米娅    需 18 费，当时 11 费  → 拒
        5.0s  德克萨斯  需 13 费，当时 15 费  → 放过（唯一放下去的）
        9.0s  拉普兰德  需 19 费，当时  6 费  → 拒

    于是结果塌成 `86.8s / 8 杀 / 11 漏`、只部署 1 人。重排取**各自最早付得起
    的时刻再加 1 秒余量**（不加余量会卡在离散回费节拍的缝里：连续模型算 18.0，
    模拟器按 `cost_time` 跳点那一刻可能只有 17）→ **9 / 22 / 41s**，0 拒收。

    重排后结论从 `41 杀 / 0 漏 / 60750` 降为 **`39 杀 / 2 漏 / 58650`**——
    差值全部来自那 39 秒的被迫等待：三个人晚上场，前期漏掉两只。
    **耗时仍是 137.0s**。

    **这里的 137.0s 是"退化范围"那条路的数**：本函数不传 `range_provider`，
    模拟器于是退回 `_range_of` 里那个「自身格 + 朝向前方三格」的近似。
    接上真实攻击范围（`range.Provider` + gamedata `range_table.json`）
    同一阵容是 **133.0s**——击杀数与总伤害完全相同，只差覆盖格数。
    本节锚的是**旧路径没被改坏**（技能系统是后加进来的），不是精度；
    精度的锚在 `tools/check_verify.py`，那两条例都锚。
    """
    print("\n[1] 1-7 无技能基线（回归坐标，时刻已按真实费用重排）")
    sim = BattleSimulator(stage, enemy_at=lib.get)
    sim.plan(Deployment(9.0, make_unit(calc, "char_002_amiya", elite=2, level=80,
                                       trust=100, potential=6), (5, 2), "Left"))
    sim.plan(Deployment(22.0, make_unit(calc, "char_102_texas", elite=2,
                                        level=1), (4, 3), "Right"))
    sim.plan(Deployment(41.0, make_unit(calc, "char_140_whitew", elite=2,
                                        level=1), (2, 3), "Right"))
    r = sim.run()
    print(f"         {r.summary()}")
    check("三者都放得下去（没有因费用被拒）", r.deployed == 3,
          f"实得 {r.deployed}")
    check("费用台账为空", not r.cost_denied, f"实得 {r.cost_denied}")
    check("再部署台账为空", not r.deploy_rejected, f"实得 {r.deploy_rejected}")
    check("胜利", r.won)
    check("击杀 39", r.kills == 39, f"实得 {r.kills}")
    check("漏怪 2", r.leaks == 2, f"实得 {r.leaks}")
    check("阵亡 0", r.operator_deaths == 0, f"实得 {r.operator_deaths}")
    check("总伤害 58650", close(r.damage_dealt, 58650, 1),
          f"实得 {r.damage_dealt:,.0f}")
    check("耗时 137.0s", close(r.elapsed, 137.0, 0.2), f"实得 {r.elapsed:.1f}s")


def check_calibration(stage, lib, calc, book) -> None:
    """怒潮凛冬单干员——用户提供的实机通关录像。

    耗时不写死在文字里：它随机制推进而变（特性溅射上线后从 138.6s 走到
    135.0s），写死会变成一句迟早对不上的话。**锚的是三件事**：41 击杀、
    0 漏、总伤害 = 全部敌人血量之和。
    """
    print("\n[2] 1-7 实机录像用例（怒潮凛冬 精英2 60级，单干员）")
    print("         录像：41 击杀、0 漏、胜利；耗时按实测打印，不写死")

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
    print(f"         模拟耗时 {r.elapsed:.1f}s（实机 140s，差 "
          f"{r.elapsed - 140.0:+.1f}s——这一项只看量级，不当判据）")
    check("击杀 41（与录像一致）", r.kills == 41, f"实得 {r.kills}")
    check("漏怪 0（与录像一致）", r.leaks == 0, f"实得 {r.leaks}")
    check("总伤害 60750（= 全部 41 只敌人血量之和）",
          close(r.damage_dealt, 60750, 1), f"实得 {r.damage_dealt:,.0f}")
    # **这条判据 2026-09-18 改口了。** 原来是「只按黑板会明显少杀」——但特性
    # 溅射落地之后，只按黑板那一局也打满 41 杀（溅射把变体少掉的那部分伤害
    # 补回来了），"少杀"不再是变体在做事的证据。**不能因此放宽守卫**，要换一个
    # 变体**独有**、且与本条机制无关的可观测量：那条变体除了翻倍还写了
    # 「第二次及以后使用时……持续时间无限」。没叠变体时技能 30 秒到点掉线、
    # 要重充（本关实测开 2 次）；叠上后只开 1 次且一直挂着。
    check("反向：只按黑板要**开两次技能**（30 秒到点掉线重充），"
          "叠上 [second] 只开一次——「持续时间无限」只在变体里",
          raw.skill_activations > r.skill_activations,
          f"只按黑板 {raw.skill_activations} 次 vs 叠加变体 "
          f"{r.skill_activations} 次")

def check_parsing(book) -> None:
    """技能解析的定点值——这些数错了伤害就会错一个量级。"""
    print("\n[3] 技能解析定点值")

    lv = book.for_operator("char_4230_mcnist")[2].level(7, 3)
    power = lv.effects.attack_power(1.0)
    check("机械师「工程学十字星」面板口径 =（1+2.8）= 3.8"
          "（`attack_power` **不含**技能倍率，2026-09-18 裁定）",
          close(power, 3.8, 1e-6), f"实得 {power:.4f}")
    total = power * lv.effects.atk_scale
    check("  一次出手的总倍率 **9.88** = 3.8 × 2.6（社区标定值，"
          "倍率由 `resolve_damage(scale=…)` 乘那一份）",
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
        sim = mechanism_sim(stage, lib, enemy_windup=windup)
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
        sim = mechanism_sim(stage, lib, skill_book=book,
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

    # ---- 真实伤害的第二条判据：**攻击本身被换掉**时，正文写的就是它的伤害
    from ak_tactic.operator.skill import _wants_true_damage   # noqa: PLC0415
    k2 = lv("char_1052_kalts2", 2)
    check("凯尔希·思衡托技2 判为真实伤害"
          "（「攻击变为射出医疗单元…造成相当于攻击力380%的真实伤害」）",
          k2.effects.true_damage is True, f"实得 {k2.effects.true_damage}")
    check("  这一击的倍率仍是 3.8（补判据只改类型，不许动倍率）",
          close(k2.effects.atk_scale, 3.8, 1e-9),
          f"实得 {k2.effects.atk_scale}")
    # 全表命中面：含「真实伤害」的每一条都要有归处——是"这一击的类型"才认，
    # 附加的那几笔一律不认。**只测标本不测面**是这条判据的老坑（2026-09-16
    # 它曾一次误判 28 条），所以这里直接扫全表。
    with sqlite3.connect(Path(__file__).resolve().parent.parent
                         / "data" / "akdb.sqlite") as _c:
        _rows = _c.execute(
            "SELECT DISTINCT skill_id, description FROM skill_level "
            "WHERE level = 10 AND description LIKE '%真实伤害%'").fetchall()
    _hit = sorted(sid for sid, d in _rows if _wants_true_damage(d))
    check("全表含「真实伤害」的 5 条里，判据只认 2 条（那一击的类型）",
          len(_rows) == 5 and _hit == ["skchr_kalts2_2", "skchr_nearl2_3"],
          f"{len(_rows)} 条里认了 {_hit}")
    _add = ("skchr_cetsyr_2", "skchr_hodrer_3", "sktok_nearl2_3")
    check("  反向：微尘碰撞 / 敌人每秒受到 X 点 / 耀阳部署时那三条都不认"
          "（它们都是另加的一笔，不是这一击）",
          not [sid for sid, d in _rows if sid in _add and _wants_true_damage(d)],
          "、".join(sid for sid, d in _rows
                    if sid in _add and _wants_true_damage(d)) or "（都不认）")

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

    sim = mechanism_sim(stage, lib)
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
    sim_c = mechanism_sim(stage, lib)
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
    sim2 = mechanism_sim(stage, lib)
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
    sim3 = mechanism_sim(stage, lib)
    sim3.plan_summon(SummonDeployment(1.0, "token_10051_radian_tower1", (4, 3),
                                      "Right", owner="char_4195_radian"))
    r3 = sim3.run()
    check("召唤者没下场就召唤 → 拒收", r3.summons_deployed == 0
          and len(r3.summon_rejected) == 1
          and "不在场" in r3.summon_rejected[0][2],
          f"实得 {r3.summon_rejected}")

    sim4 = mechanism_sim(stage, lib)
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
    sim5 = mechanism_sim(stage, lib)
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

    print("     —— 召唤者退场，召唤物一并消失（实机规则）——")
    # 走**主动撤退**这条离场路：撤退与阵亡在"离场"这件事上等价，而撤退的
    # 时机完全可控——靠打死主人来触发会依赖伤害账，改一处数值就假失败。
    R_TAL6 = book_t.for_operator("char_4195_radian")
    sim6 = mechanism_sim(stage, lib)
    sim6.plan(Deployment(1.0, make_unit(calc, "char_4195_radian", elite=2, level=90),
                         (5, 2), "Left", talents=R_TAL6))
    sim6.plan_summon(SummonDeployment(2.0, "token_10051_radian_tower1", (4, 3),
                                      "Right", owner="char_4195_radian"))
    sim6.retreats.append((20.0, (5, 2)))
    r6 = sim6.run()
    check("召唤者撤走后，召唤物随之离场并留痕",
          len(r6.summon_cascaded) == 1
          and close(r6.summon_cascaded[0][0], 20.0, 0.2),
          f"实得 {r6.summon_cascaded}")
    summons6 = [o for o in sim6.operators if o.is_summon]
    check("召唤物被标成**主动离场**，不是阵亡（判据看 retreated）",
          len(summons6) == 1 and summons6[0].retreated and not summons6[0].alive,
          f"实得 {[(o.retreated, o.alive) for o in summons6]}")
    check("**消失的召唤物不计入干员阵亡**（只清血条会让 operator_deaths 虚高）",
          r6.operator_deaths == 0, f"实得 {r6.operator_deaths}")

    # 反向守卫：主人还活着的时候**不能**被级联掉——否则这条规则会变成
    # "召唤物一律活不过第二帧"，而上面的正向检查照样通过。
    sim7 = mechanism_sim(stage, lib)
    sim7.plan(Deployment(1.0, make_unit(calc, "char_4195_radian", elite=2, level=90),
                         (5, 2), "Left", talents=R_TAL6))
    sim7.plan_summon(SummonDeployment(2.0, "token_10051_radian_tower1", (4, 3),
                                      "Right", owner="char_4195_radian"))
    r7 = sim7.run()
    check("召唤者活着时召唤物不受影响（级联没有误伤）",
          r7.summon_cascaded == [] and r7.summons_deployed == 1,
          f"实得 cascaded={r7.summon_cascaded} deployed={r7.summons_deployed}")


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
    sim = mechanism_sim(stage, lib, skill_book=book)
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
    sim2 = mechanism_sim(stage, lib, skill_book=book)
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


def check_redeploy(stage, lib, calc) -> None:
    """[17] 再部署规则——同一干员不可重复在场、离场后有冷却。

    这一节对应博士 2026-09-18 指定的待办「干员无法重复部署」。此前模拟器
    **一条检查都没有**：同一个 `char_id` 能被两条 `Deployment` 同时摆上场
    （占两格、各打各的，等于凭空多一个干员），撤退或阵亡后也能立刻再放。
    `OperatorUnit.redeploy_time` 那个 70 秒字段一直是**死字段**，没人读。

    留成 `redeploy_mode` 两个口径而不是直接替换，是为了让"哪一条规则改了
    结论"能被单独测出来。
    """
    print("\n[17] 再部署规则（同一干员不可重复在场 / 离场冷却）")

    def mk(cid="char_002_amiya"):
        return make_unit(calc, cid, elite=2, level=80)

    print("     —— legacy：旧行为原样保留（没有任何检查）——")
    sim_l = BattleSimulator(stage, enemy_at=lib.get, redeploy_mode="legacy",
                            cost_mode="legacy")
    sim_l.cost = 999.0
    sim_l._do_deploy(Deployment(0.0, mk(), (2, 3), "Right"), 0.0)
    sim_l._do_deploy(Deployment(0.0, mk(), (4, 3), "Right"), 0.0)
    check("legacy：同一干员能同时摆上两个（**旧行为，故意保留**）",
          len(sim_l.operators) == 2 and not sim_l.result.deploy_rejected,
          f"实得 {len(sim_l.operators)} 个")

    print("     —— strict：同一干员不能同时在场上出现两个 ——")
    sim_s = BattleSimulator(stage, enemy_at=lib.get, redeploy_mode="strict",
                            cost_mode="strict")
    sim_s.cost = 999.0
    first = mk()
    sim_s._do_deploy(Deployment(0.0, first, (2, 3), "Right"), 0.0)
    sim_s._do_deploy(Deployment(0.0, mk(), (4, 3), "Right"), 0.0)
    check("strict：第二个被拒，场上只留 1 个", len(sim_s.operators) == 1,
          f"实得 {len(sim_s.operators)} 个")
    check("拒收留了痕（不静默少放一个）",
          len(sim_s.result.deploy_rejected) == 1
          and "已在场" in sim_s.result.deploy_rejected[0][2],
          f"实得 {sim_s.result.deploy_rejected}")
    check("拒收的是**规则**那一笔，不是费用那一笔",
          not sim_s.result.cost_denied,
          f"实得 {sim_s.result.cost_denied}")

    print("     —— strict：离场后要等冷却 ——")
    first.retreated = True
    first.left_at = 10.0
    check("默认再部署冷却 = 70s（`redeploy_time` 此前是死字段）",
          close(mk().redeploy_time, 70.0, 1e-9), f"实得 {mk().redeploy_time}")
    sim_s._do_deploy(Deployment(30.0, mk(), (2, 3), "Right"), 30.0)
    check("第 30 秒再放被拒（10+70=80s 才够）",
          len(sim_s.operators) == 1, f"实得 {len(sim_s.operators)} 个")
    last = sim_s.result.deploy_rejected[-1]
    check("拒收理由写清了还要等多久",
          "再部署冷却" in last[2] and "还要等 50.0s" in last[2],
          f"实得 {last[2]}")
    sim_s._do_deploy(Deployment(80.0, mk(), (2, 3), "Right"), 80.0)
    check("第 80 秒放得下去（恰好到点）", len(sim_s.operators) == 2,
          f"实得 {len(sim_s.operators)} 个")

    print("     —— 冷却只跟同一个 char_id 有关 ——")
    sim_d = BattleSimulator(stage, enemy_at=lib.get, redeploy_mode="strict",
                            cost_mode="strict")
    sim_d.cost = 999.0
    a = mk("char_002_amiya")
    sim_d._do_deploy(Deployment(0.0, a, (2, 3), "Right"), 0.0)
    other = mk("char_102_texas")
    sim_d._do_deploy(Deployment(0.0, other, (4, 3), "Right"), 0.0)
    check("不同干员互不影响（不是按名字判，是按 char_id）",
          len(sim_d.operators) == 2 and not sim_d.result.deploy_rejected,
          f"实得 {len(sim_d.operators)} 个 / {sim_d.result.deploy_rejected}")
    check("快活类干员的短冷却是同一个字段，不是另写一套",
          mk("char_102_texas").redeploy_time > 0.0)

    print("     —— 端到端：真跑一场，离场时刻确实被记下 ——")
    sim_r = BattleSimulator(stage, enemy_at=lib.get, redeploy_mode="strict",
                            cost_mode="strict")
    op = mk("char_102_texas")
    sim_r.plan(Deployment(3.0, op, (4, 3), "Right"))
    sim_r.retreat((4, 3), 20.0)
    res = sim_r.run()
    check("跑得完", res is not None)
    check("撤退后 `retreated` 为真", op.retreated)
    check("**离场时刻被记下**（再部署冷却靠它起算）",
          close(op.left_at, 20.0, 0.6), f"实得 {op.left_at:.1f}")
    check("离场后同一干员在冷却内放不下去",
          res is not None and len(sim_r.operators) == 1,
          f"实得 {len(sim_r.operators)} 个")


def check_blessing(stage, lib, calc, book_t) -> None:
    """[18] 天赋「圣山的祝福」（圣聆初雪天赋1）：免死一次 + 范围冻结。

    三个层次各管一段，缺一段这个机制就只是"看起来实现了"：

    1. **判据的命中面**——`c2e_freeze`/`freeze` 在全表里只该命中这 2 条。
       少了说明判据漂了会漏人；多了说明它认到了无关天赋上。
    2. **接线**——部署时三个数要从黑板读进来。读不到就等于没有这条天赋。
    3. **语义**——免死**仅一次**、回**满**血、自身冻结、范围冻结**真的冻住人**。

    第 3 条里"真的冻住"这一项特别容易自欺：`blessing_saves` 里的命中人数是
    同一段循环里数出来的，它证明不了冻结生效。所以这里改成**看位移**——
    被冻的敌人逐帧位移必须恒为 0。
    """
    print("\n[18] 天赋：圣山的祝福（免死一次 / 自身冻结 / 范围冻结）")

    CID = "char_1046_sbell2"
    R_TAL = book_t.for_operator(CID)
    bless = find_blessing(R_TAL)
    check("在她的天赋里找得到「圣山的祝福」", bless is not None)

    print("     —— 判据的命中面（宁可漏不可错）——")
    check("指纹是 c2e_freeze + freeze（两个键，不是单键）",
          BLESSING_KEYS == ("c2e_freeze", "freeze"), f"实得 {BLESSING_KEYS}")
    check("四个黑板数：c2e_freeze 8 / freeze 4 / cold 1.5 / hp_ratio 1",
          (bless.value("c2e_freeze", 0.0), bless.value("freeze", 0.0),
           bless.value("cold", 0.0), bless.value("hp_ratio", 0.0))
          == (8.0, 4.0, 1.5, 1.0))

    print("     —— 接线：部署时把三个数读进来 ——")
    u0 = make_unit(calc, CID, elite=2, level=90, trust=100)
    check("**没接线之前一个数都没有**（不会误触发）",
          (u0.blessing_save, u0.blessing_self_freeze, u0.blessing_cold)
          == (0.0, 0.0, 0.0))
    sim0 = mechanism_sim(stage, lib)
    sim0.plan(Deployment(6.0, make_unit(calc, CID, elite=2, level=90, trust=100),
                         (2, 3), "Right", talents=R_TAL))
    sim0.run()
    op0 = sim0.operators[0]
    check("部署后 save/self_freeze/cold = 8 / 4 / 1.5",
          (op0.blessing_save, op0.blessing_self_freeze, op0.blessing_cold)
          == (8.0, 4.0, 1.5),
          f"实得 {op0.blessing_save}/{op0.blessing_self_freeze}/"
          f"{op0.blessing_cold}")

    print("     —— 语义：免死仅一次、回满血、自身冻结 ——")
    u = make_unit(calc, CID, elite=2, level=90, trust=100)
    # 面板抄在这里是为了让断言可读：回满血的判据是 hp == max_hp，
    # 不是某个写死的数；但 max_hp 变了要能一眼看出来。
    check("面板 max_hp = 2058（E2 L90 满信赖）", close(u.max_hp, 2058, 0.5),
          f"实得 {u.max_hp:.1f}")
    u.blessing_save = 8.0
    u.blessing_self_freeze = 4.0
    u.take(u.max_hp * 10)
    check("第一次致死：血回到满、标记已用、自身冻结 4s、欠下 8s 范围冻结",
          u.alive and close(u.hp, u.max_hp, 1e-6) and u.blessing_used
          and close(u.freeze_timer, 4.0) and close(u.blessing_freeze, 8.0),
          f"hp={u.hp:.0f}/{u.max_hp:.0f} used={u.blessing_used} "
          f"freeze={u.freeze_timer} pending={u.blessing_freeze}")
    u.freeze_timer = 0.0
    u.take(u.max_hp * 10)
    check("第二次致死：**真的死**（描述原文就是「仅一次」）",
          not u.alive, f"hp={u.hp:.0f}")

    # 反向守卫：没有这条天赋的话，第一次就该死。
    # 少了这一条，一个"任何干员都免死"的 bug 也能让上面几条全绿。
    plain = make_unit(calc, "char_102_texas", elite=2, level=1)
    plain.take(plain.max_hp * 10)
    check("没这条天赋的干员第一次致死就死（免死没有外溢给别人）",
          not plain.alive)

    print("     —— 范围冻结：兑现一次，且**真的冻住人** ——")
    # 预置一次"欠下的范围冻结"。t=34 落 (2,3) 时射程内有 2 名敌人，这是
    # 探针实得的值；换成别的落位/时刻命中数会变（0 到 2 都出现过），
    # 所以这两个参数是判据的一部分，别随手改。
    sim = mechanism_sim(stage, lib)
    uz = make_unit(calc, CID, elite=2, level=90, trust=100)
    uz.blessing_freeze = 8.0
    sim.plan(Deployment(34.0, uz, (2, 3), "Right", talents=R_TAL))
    trace: list[float] = []
    orig_advance = EnemyUnit.advance

    def traced(self, dt, speed_scale):  # noqa: ANN001, ANN202
        before = self.position
        out = orig_advance(self, dt, speed_scale)
        if self.freeze_timer > 0:
            trace.append(abs(before[0] - self.position[0])
                         + abs(before[1] - self.position[1]))
        return out

    EnemyUnit.advance = traced
    try:
        rz = sim.run()
    finally:
        EnemyUnit.advance = orig_advance
    check("恰好兑现一次", len(rz.blessing_saves) == 1,
          f"实得 {rz.blessing_saves}")
    check("落地同一帧结算，冻住 2 名敌人、时长 8s",
          bool(rz.blessing_saves)
          and close(rz.blessing_saves[0][0], 34.0, 0.05)
          and rz.blessing_saves[0][2] == 8.0 and rz.blessing_saves[0][3] == 2,
          f"实得 {rz.blessing_saves}")
    check("**被冻的敌人一帧都没动**（这才是「冻住了」的证据，"
          "命中人数只是同段循环里数出来的）",
          len(trace) >= 20 and all(abs(m) < 1e-9 for m in trace),
          f"有位移的帧数 {sum(1 for m in trace if abs(m) >= 1e-9)} / {len(trace)}")
    check("她自己没被打死（免死没被误触发）",
          rz.blessing_saves[0][3] == 2 and not sim.operators[0].blessing_used)

    print("     —— 未建模的部分如实记下，不装成 0 ——")
    check("【寒冷】只有时长、没有攻速效果（数值两个镜像都是 404，见 "
          "docs/uncertainties.md 第九节）",
          "cold_timer" in {f for f in EnemyUnit.__dataclass_fields__})


def check_charges(stage, lib, calc) -> None:
    """[19] 可充能次数（`maxChargeTime`）：额度要能**攒过** `sp_cost`。

    这条机制在 143 个技能上生效，此前**一条用例都没有**，而它恰好是坏的：
    "攒过 sp_cost" 那个上限只写在"技能**开启期间**"那一支里，未开启时写死
    `sp_cost`。圣聆初雪技1 是**瞬发**（`duration = -1`），开启期间只有一两帧
    ——于是"可充能 2 次"对**最需要它的那类技能**从来没生效过。

    所以判据不能只看"能不能连开两次"，那对瞬发技能恰好测不出来；要直接看
    **技力停在哪**：多充能技能该停在 `sp_cost × max_charge`。
    """
    print("\n[19] 可充能次数：额度攒过 sp_cost（瞬发技能是重灾区）")
    CID = "char_1046_sbell2"

    sim = mechanism_sim(stage, lib, skill_book=SkillBook())
    sim.plan(Deployment(1.0, make_unit(calc, CID, elite=2, level=90, trust=100),
                        (5, 2), "Left", skill=1, auto_skill=False))
    sim.run()
    op = sim.operators[0]
    sk = op.skill
    check("技1 的 max_charge = 2（「可充能2次」）", sk.max_charge == 2,
          f"实得 {sk.max_charge}")
    check("技1 是**瞬发**——这正是旧写法藏得住 bug 的原因",
          sk.is_instant)
    check("技力停在 sp_cost × max_charge = 24（写死 sp_cost 时会停在 12）",
          close(op.sp, sk.sp_cost * sk.max_charge, 0.01),
          f"实得 {op.sp:.2f}，sp_cost={sk.sp_cost}，"
          f"期望 {sk.sp_cost * sk.max_charge:.2f}")
    check("**确实攒过了一次 sp_cost**（不是碰巧相等）",
          op.sp > sk.sp_cost + 1e-9 and not op.sp_charges)

    # 反向守卫：单充能技能**不能**跟着一起放宽，否则等于所有技能都白攒一倍。
    # 少了这一条，把上限一律改成 `sp_cost * max_charge` 也能让上面几条全绿。
    sim3 = mechanism_sim(stage, lib, skill_book=SkillBook())
    sim3.plan(Deployment(1.0, make_unit(calc, CID, elite=2, level=90, trust=100),
                         (5, 2), "Left", skill=3, auto_skill=False))
    sim3.run()
    op3 = sim3.operators[0]
    check("单充能技能（技3，max_charge=1）仍然停在 sp_cost",
          op3.skill.max_charge == 1
          and close(op3.sp, op3.skill.sp_cost, 0.01),
          f"实得 max_charge={op3.skill.max_charge} sp={op3.sp:.2f} "
          f"sp_cost={op3.skill.sp_cost}")


def check_displace(stage, lib, calc) -> None:
    """[20] 位移：推力/拉力的判定规则（受力等级 → 理想位移）。

    这一节**只测规则**，不测接线——接线要动敌人"沿路线推进"的表示（位置是
    从 `progress` 算出来的），那是另一件事。规则是查数据源才拿到的定值表，
    搬来搬去最容易失传，所以在这里逐值钉死。

    三条容易写错的地方，各有一条守卫：
    1. 受力等级是**差值**（力度 − 重量），不是力度本身；
    2. 弹道类与特效类**不同值**（差一帧失衡位移）——用同一个数会系统性偏；
    3. 拉力 0 级及以上是**拉至身前**，返回 `None`，不是某个格数。
    """
    print("\n[20] 位移：推力/拉力的判定规则")
    print(f"     出处：{D.source_note()}")

    print("     —— 力度对应表（技能黑板的 force 用的就是这套）——")
    check("力度对应表七档：微小力 -1 … 特大力 5",
          D.FORCE_BY_DESC == {"微小力": -1, "小力": 0, "中力": 1, "较大力": 2,
                              "大力": 3, "大力+1": 4, "特大力": 5},
          f"实得 {D.FORCE_BY_DESC}")
    check("「中等力度」= 力度等级 1（圣聆初雪技1 的描述用的就是这个词）",
          D.FORCE_BY_DESC["中力"] == 1)

    print("     —— 推力理想位移表（弹道 / 特效 两列）——")
    check("受力等级 0 的理想位移 = 1.6958 / 1.56247 格（**不是整数格**）",
          D.PUSH_IDEAL[0] == (1.69580, 1.56247), f"实得 {D.PUSH_IDEAL[0]}")
    check("受力等级 ≥3 取 3.52392 / 3.33058",
          D.PUSH_IDEAL[3] == (3.52392, 3.33058))
    check("**弹道类严格推得更远**（命中帧多一帧以初速度的失衡位移）",
          all(b > e for b, e in D.PUSH_IDEAL.values()),
          f"实得 {D.PUSH_IDEAL}")
    check("表只覆盖 -2..3（两端是开区间，靠夹取处理）",
          sorted(D.PUSH_IDEAL) == [-2, -1, 0, 1, 2, 3])

    print("     —— 受力等级 = 力度 − 重量（差值是关键）——")
    check("力度 1 对重量 0：受力等级 1 → 特效 1.98705 格",
          close(D.push_distance(1, 0), 1.98705, 1e-9),
          f"实得 {D.push_distance(1, 0)}")
    check("同一力度对重量 1：受力等级 0 → 1.56247 格（**差值，不是力度**）",
          close(D.push_distance(1, 1), 1.56247, 1e-9),
          f"实得 {D.push_distance(1, 1)}")
    check("重量 4 → 受力等级 -3 → **完全不位移**",
          D.push_distance(1, 4) == 0.0)
    check("重量 6 → 受力等级 -5 → 仍为 0（下界夹住，不越界查表）",
          D.push_distance(1, 6) == 0.0)
    check("力度 5 对重量 0 → 受力等级 5 → 取最高档 3.33058（上界夹住）",
          close(D.push_distance(5, 0), 3.33058, 1e-9),
          f"实得 {D.push_distance(5, 0)}")
    check("弹道类同一受力等级给 3.52392（与特效不同）",
          close(D.push_distance(5, 0, ballistic=True), 3.52392, 1e-9))

    print("     —— 基础力度是**加**上去的（推击手一类）——")
    check("force 0 + 基础力度 1 = 力度等级 1",
          D.skill_force_level(0.0, 1.0) == 1)
    check("force 1 + 基础力度 0 = 力度等级 1",
          D.skill_force_level(1.0) == 1)
    check("force 1 + 基础力度 1 = 力度等级 2（不是取大者）",
          D.skill_force_level(1.0, 1.0) == 2)

    print("     —— 方向力的「特殊修正」：夹角 >45° **或** 距离 <0.25 格 ——")
    check("夹角 50° 触发修正", D.needs_radial_correction(angle_deg=50.0,
                                                        distance=3.0))
    check("**距离 0.2 格也触发**（是「或」不是「且」——这条最容易漏）",
          D.needs_radial_correction(angle_deg=0.0, distance=0.2))
    check("夹角 30° 且距离 3 格：不修正",
          not D.needs_radial_correction(angle_deg=30.0, distance=3.0))
    check("夹角 45° 恰好不触发（判据是「大于 45°」）",
          not D.needs_radial_correction(angle_deg=45.0, distance=3.0))

    print("     —— 拉力：0 级及以上是**拉至身前**，不是某个格数 ——")
    check("受力等级 0 → None（用 0.0 会把「拉过来」静默变成「没拉动」）",
          D.pull_offset(0, 0, 3.0) is None)
    check("受力等级 2 对重量 0 → None", D.pull_offset(2, 0, 3.0) is None)
    check("受力等级 -1 → 0.35 倍初始距离（4 格 → 1.4 格）",
          close(D.pull_offset(-1, 0, 4.0), 1.4, 1e-9),
          f"实得 {D.pull_offset(-1, 0, 4.0)}")
    check("受力等级 -2 → 只蠕动 0.03 格", close(D.pull_offset(-2, 0, 4.0), 0.03))
    check("受力等级 ≤-3 → 0（拉不动）", D.pull_offset(-3, 0, 4.0) == 0.0)
    check("受力等级 -1 的时间 = max(0.65*sqrt(4), 1.0) = 1.3",
          close(D.pull_time(-1, 0, 4.0), 1.3, 1e-9),
          f"实得 {D.pull_time(-1, 0, 4.0)}")
    check("受力等级 -2 的时间固定 0.5s（< -1 就改 0.5）",
          close(D.pull_time(-2, 0, 4.0), 0.5))

    print("     —— 数据侧的输入真的在（重量来自 gamedata，不在敌人库）——")
    weights = [getattr(lib.get(eid), "weight", None)
               for eid in _enemy_ids(stage)][:12]
    known = [w for w in weights if w is not None]
    check("1-7 的敌人拿得到重量", len(known) > 0,
          f"前 12 个里 {len(known)} 个有值")
    check("重量是**数值**（gamedata 的 massLevel），不是 None 占位",
          all(isinstance(w, (int, float)) for w in known),
          f"实得 {known[:6]}")
    # 圣聆初雪技1 的黑板 force = 1；用真实重量走一遍，确认能落到某一档而不是
    # 一路返回 0（返回 0 会让"推动"看起来实现了却什么也没做）。
    real = [D.push_distance(1, w) for w in known]
    check("技1 的力度 1 对 1-7 的真实重量：至少有一档推动量 > 0",
          any(v > 0 for v in real), f"实得 {[round(v, 4) for v in real[:8]]}")


def _enemy_ids(stage) -> list[str]:
    """从关卡里取出敌人 id（去重、保序），给上面那条守卫用。

    关卡把出场表直接挂在 `stage.spawns`（`EnemySpawn.enemy_id`）上，
    **没有 waves 这一层**——别照别的引擎的形状猜。
    """
    seen: list[str] = []
    for spawn in getattr(stage, "spawns", []) or []:
        eid = getattr(spawn, "enemy_id", None)
        if isinstance(eid, str) and eid not in seen:
            seen.append(eid)
    return seen


#: 十位目标干员的 id。审计类守卫要按**名字**报错，所以名字也留一份。
TARGET_OPS: dict[str, str] = {
    "char_4195_radian": "电弧",
    "char_4230_mcnist": "机械师",
    "char_2027_wang": "望",
    "char_1050_chen3": "赤刃明霄陈",
    "char_1046_sbell2": "圣聆初雪",
    "char_2023_ling": "令",
    "char_002_amiya": "阿米娅",
    "char_1001_amiya2": "阿米娅(近卫)",
    "char_2012_typhon": "提丰",
    "char_4133_logos": "逻各斯",
    "char_1015_aglna2": "予愿安洁莉娜",
}


def check_random_audit() -> None:
    """[21] 随机：十位目标干员的概率键**覆盖审计**。

    「随机」这件大件里，**闪避**已由博士 2026-09-17 裁定④按**期望值法**定案
    （`damage.resolve_damage` 的 `dodge_*` 入参相乘，不掷骰）。但期望值法
    **不是对所有随机都成立**——它成立是因为"一次攻击被闪掉的概率"可以线性
    折进伤害。**概率晕眩不是这种量**：晕眩是离散的控场状态，不是伤害系数。

    所以这一节不做实现，做**审计**：把"十位干员里到底还剩哪些随机、各自属于
    哪一类"钉成可证伪的清单。这样它不会随着时间变成一句"其余待定"。

    清单是从库里**查出来**的，不是抄在代码里的——库里多出一个概率键，这里
    就该失败。
    """
    print("\n[21] 随机：概率键的覆盖审计（期望值法只对闪避成立）")
    db = Path(__file__).resolve().parent.parent / "data" / "akdb.sqlite"
    if not db.exists():
        check("找得到 data/akdb.sqlite（审计要查库）", False, str(db))
        return

    conn = sqlite3.connect(db)
    ph = ",".join("?" * len(TARGET_OPS))
    hits: list[tuple[str, str, str, str, dict]] = []
    for sid, cid, lv, bb, desc in conn.execute(
            "SELECT s.skill_id, o.char_id, s.level, s.blackboard, "
            "s.description FROM skill_level s "
            "JOIN operator_skill o ON o.skill_id = s.skill_id "
            f"WHERE s.level = 10 AND o.char_id IN ({ph})",
            tuple(TARGET_OPS)):
        if not bb:
            continue
        d = json.loads(bb)
        prob = {k: v for k, v in d.items()
                if "prob" in k.lower() or "random" in k.lower()}
        if prob:
            hits.append((sid, cid, desc or "", "", prob))
    conn.close()

    check("十位干员的技能里恰好 3 个带概率键（多一个就该重审这份清单）",
          len(hits) == 3,
          f"实得 {len(hits)}：{[h[0] for h in hits]}")

    dodges = [h for h in hits if "闪避" in h[2]]
    others = [h for h in hits if "闪避" not in h[2]]
    check("其中 2 个是**闪避**——走期望值法，已覆盖",
          len(dodges) == 2, f"实得 {[h[0] for h in dodges]}")
    check("闪避那两个确实各自带着「物理和法术闪避」/「法术闪避」的原文",
          all(("物理和法术闪避" in d[2]) or ("法术闪避" in d[2])
              for d in dodges),
          f"实得 {[(d[0], d[2][:26]) for d in dodges]}")
    check("赤刃技2 的键名是 `chen3_s2[respawn_buff].prob`（**键名叫 prob，"
          "但不是概率伤害**）",
          any("chen3_s2[respawn_buff].prob" in d[4] for d in dodges),
          f"实得 {[list(d[4]) for d in dodges]}")
    check("阿米娅(近卫)技1 的键名是光秃秃的 `prob`（同名，语义靠描述定）",
          any(list(d[4]) == ["prob"] for d in dodges),
          f"实得 {[list(d[4]) for d in dodges]}")

    print("     —— 剩下的这一个 **不能** 沿用期望值法 ——")
    check("恰好剩 1 个，且它是**晕眩**不是闪避",
          len(others) == 1 and "晕眩" in others[0][2],
          f"实得 {[(o[0], o[2][:30]) for o in others]}")
    if others:
        sid, cid, desc, _, prob = others[0]
        check(f"它就是提丰技2（{sid}），键名 `attack@prob`",
              sid == "skchr_typhon_2" and "attack@prob" in prob,
              f"实得 {sid} {list(prob)}")
        check("晕眩时长 `attack@stun` = 1 秒（期望值要按它对攻击间隔算占比）",
              json.loads(conn_blackboard(db, sid)).get("attack@stun") == 1.0,
              f"实得 {conn_blackboard(db, sid)[:90]}")

    # **跳线**：敌人侧现在连晕眩状态都没有，所以"提丰技2 未建模"是当前的
    # 事实而不是推测。等哪天有人把 `stun_timer` 加到 EnemyUnit 上，这一条会
    # 失败——那正是**逼着**把上面"不能沿用期望值法"那段改成"已按 X 口径落地"
    # 的时机。跳线不写死未来怎么做，只保证旧说法不会悄悄过期。
    # 本节曾留一条跳线：「敌人侧目前**没有**晕眩状态」。2026-09-18 建好了
    # （见第 [22] 节），所以按当时的约定把说法改过来——**跳线踩响之后必须
    # 改口**，不然它就从"防止过期"变成"防不住的过期"。
    enemy_fields = set(EnemyUnit.__dataclass_fields__)
    check("敌人侧现在**有**晕眩状态了（[21] 的跳线已于 2026-09-18 兑现，"
          "实现与口径见第 [22] 节）",
          "stun_timer" in enemy_fields and "disarm_timer" in enemy_fields,
          f"stun_timer={'stun_timer' in enemy_fields}")
    check("跳线配套：干员侧也仍有 `stun_timer`",
          "stun_timer" in OperatorUnit.__dataclass_fields__)


def conn_blackboard(db, skill_id: str) -> str:
    """取某技能 10 级的黑板原文（审计里按需再查一次用）。"""
    with sqlite3.connect(db) as c:
        row = c.execute("SELECT blackboard FROM skill_level WHERE skill_id=? "
                        "AND level=10", (skill_id,)).fetchone()
    return row[0] if row else "{}"


def check_stun(stage, lib, calc, book_t) -> None:
    """[22] 概率晕眩（提丰技2）：期望占比 + 晕眩的**两半**。

    [21] 审计留下的跳线就是为这一刻写的——它当时钉的是"敌人侧没有晕眩状态"。
    现在有了，所以那条守卫要改口。这一节接上实现。

    判据照旧不看"计数"，看**被晕的敌人动没动**：`stun_timer` 被加上这件事，
    和"它真的挡住了移动"是两回事，同一段代码里数出来的数证明不了后者。
    """
    print("\n[22] 概率晕眩：期望占比（加而非 max），且真的挡住移动")
    CID = "char_2012_typhon"
    R_TAL = book_t.for_operator(CID)

    # 1. 键读得到，而且读的是**键名**不是语义。
    sbook = SkillBook()
    skill2 = None
    s3_bb: dict = {}
    for sk in sbook.for_operator(CID):
        lv = sk.level(level=7)
        # **按名字挑，不按"描述里有晕眩"挑**：技3「永恒狩猎」的描述里也有
        # 「晕眩」，按描述过滤会挑到技3（第一版就是这么错的）。
        if lv.name == "冰原秩序":
            skill2 = lv
        elif lv.name == "“永恒狩猎”":
            s3_bb = dict(lv.blackboard or {})
    check("挑中的是技2「冰原秩序」（技3 的描述里也有「晕眩」）",
          skill2 is not None and skill2.name == "冰原秩序")
    if skill2 is not None:
        bb = skill2.blackboard or {}
        check("`attack@prob` = 0.4（键名反义的那一个：同批的赤刃 `prob` 是闪避）",
              close(float(bb.get("attack@prob") or 0), 0.4, 1e-9),
              f"实得 {bb.get('attack@prob')}")
        check("`attack@stun` = 1.0 秒", close(float(bb.get("attack@stun") or 0),
                                              1.0, 1e-9),
              f"实得 {bb.get('attack@stun')}")
        check("归属一致：`effects.control['stun']` 也是 1.0 秒",
              close(float((skill2.effects.control or {}).get("stun") or 0),
                    1.0, 1e-9),
              f"实得 {skill2.effects.control}")

    # **如实记下不覆盖的部分**：技3「永恒狩猎」用的是**另一套键**
    # （`attack@s3_stun` / `attack@s3_trigger_time` / `attack@s3_max_hit_num`），
    # 触发条件是"每 8 秒内的前 4 次攻击"，与技2 的"每次攻击 40% 概率"不是一回事。
    # 实现只认 `attack@prob`/`attack@stun`，所以技3 这套**未建模**——钉住这一条，
    # 免得"提丰的晕眩做完了"被当成两套都做完了。
    check("技3 的晕眩是**另一套键**，本实现不覆盖（如实记，不是漏）",
          "attack@s3_stun" in s3_bb and "attack@prob" not in s3_bb,
          f"实得 {sorted(s3_bb)}")

    # 2. 集成级：跑一局，看被晕的敌人有没有真的停住。
    sim = mechanism_sim(stage, lib, skill_book=SkillBook())
    u = make_unit(calc, CID, elite=2, level=90, trust=100)
    sim.plan(Deployment(1.0, u, (2, 3), "Right", skill=2, auto_skill=True,
                        talents=R_TAL))
    orig = EnemyUnit.advance
    seen: list[float] = []
    moved = 0.0
    moved_n = 0

    def traced(self, dt, speed_scale):  # noqa: ANN001, ANN202
        nonlocal moved, moved_n
        nonlocal moved, moved_n
        before = self.position
        out = orig(self, dt, speed_scale)
        if self.stun_timer > 0:
            seen.append(self.stun_timer)
            d = (abs(before[0] - self.position[0])
                 + abs(before[1] - self.position[1]))
            moved += d
            if d > 1e-9:
                moved_n += 1
        return out

    EnemyUnit.advance = traced
    try:
        sim.run()
    finally:
        EnemyUnit.advance = orig
    check("提丰技2 真的给敌人上了晕眩（计时器被加上过）", len(seen) > 0,
          f"实得 {len(seen)} 个样本")
    check("**被晕的敌人一帧都没动**（这才是「晕眩挡住了移动」的证据）",
          moved_n == 0, f"有位移的帧数 {moved_n} / {len(seen)}，累计 {moved:.4f}")
    # 期望占比的算术：每次命中加 `0.4 × 1.0 = 0.4` 秒。攻击间隔 > 0.4s 时
    # 计时器来不及累积，所以**上限就是 0.4**；若哪天有人把「加」写成 `max`
    # 或把 prob 折成伤害，这条会立刻变。
    # 期望占比的算术：每次命中加 `0.4 × 1.0 = 0.4` 秒。观测点在 `advance`，
    # 而同帧的计时器递减已经先跑过了，所以看到的是 `0.4 − 1/30 = 0.3667`。
    # 判据因此是「不超过 0.4 且不低于 0.4 − 1 帧」——**上限那一半才是关键**：
    # 间隔大于 0.4s 时计时器不该累积，若哪天有人把「加」写成 `max` 或把概率
    # 折进伤害，上限会立刻变。
    stun_seen = max(seen, default=0.0)
    check("单次命中的晕眩量落在 [0.4 − 1帧, 0.4]（间隔 > 0.4s 时不该累积）",
          0.4 - 1 / 30 - 1e-9 <= stun_seen <= 0.4 + 1e-9,
          f"最大 {stun_seen:.4f}（0.4 − 1/30 = {0.4 - 1 / 30:.4f}）")

    # 3. 反向守卫：换成技1（无 `attack@prob`）就不该有任何晕眩。
    #    少了这条，一个"任何技能都给敌人上晕"的 bug 也能让上面全绿。
    sim1 = mechanism_sim(stage, lib, skill_book=SkillBook())
    u1 = make_unit(calc, CID, elite=2, level=90, trust=100)
    sim1.plan(Deployment(1.0, u1, (2, 3), "Right", skill=1, auto_skill=True,
                         talents=R_TAL))
    seen1: list[float] = []

    def traced1(self, dt, speed_scale):  # noqa: ANN001, ANN202
        out = orig(self, dt, speed_scale)
        if self.stun_timer > 0:
            seen1.append(self.stun_timer)
        return out

    EnemyUnit.advance = traced1
    try:
        sim1.run()
    finally:
        EnemyUnit.advance = orig
    check("换成技1 就一次晕眩都没有（晕眩没有外溢到别的技能）",
          len(seen1) == 0, f"实得 {len(seen1)} 个样本")

    # 4. 晕眩的**另一**半：缴械。移动由 `advance` 挡，攻击由 `_enemies_attack`
    #    与敌方技能攻击挡——只接一半会变成"走不动但照样打"。
    check("移动闸门接了晕眩（`EnemyUnit.advance` 里）",
          "self.stun_timer > 0" in inspect.getsource(EnemyUnit.advance))
    sig = inspect.getsource(BattleSimulator)
    check("攻击闸门也接了晕眩（两半都接，不是只接移动）",
          sig.count("e.stun_timer > 0") >= 2,
          f"实得 {sig.count('e.stun_timer > 0')} 处")
    check("敌人侧确实有 `stun_timer` 字段（[21] 跳线的兑现）",
          "stun_timer" in EnemyUnit.__dataclass_fields__)


def check_element_gaps(stage, lib, calc, book_t) -> None:
    """[23] 元素损伤：**本批范围为空**（结论 + 方法自检）。

    这条守卫钉的不是"实现了什么"，而是"**不需要做什么**"。这类结论最容易
    随时间变成一句没人敢信的"我记得查过"——所以把证据与检索方法一起钉住：
    库里多出一条、或解析层开始收 `ep*` 键，这里就会响。

    清单见 `docs/elemental-damage-gaps.md`。
    """
    print("\n[23] 元素损伤：本批范围为空（结论 + 方法自检）")
    db = Path(__file__).resolve().parent.parent / "data" / "akdb.sqlite"
    conn = sqlite3.connect(db)
    TERMS = ("灼燃", "侵蚀", "凋亡", "元素损伤")

    # ---- 1. 方法自检：同样的检索在全库必须**非零**，
    #         否则"十位干员那里是零"可能只是检索写错了。
    n_all = sum(
        1 for (d,) in conn.execute(
            "SELECT description FROM skill_level WHERE level=7")
        if d and any(x in d for x in TERMS))
    check("方法自检：同词在全库命中非零（证明检索有效）", n_all > 0,
          f"实得 {n_all} 条")

    # ---- 2. 十位干员 **及其召唤物**：四项全为 0
    ph = ",".join("?" * len(TARGET_OPS))
    toks = [r[0] for r in conn.execute(
        "SELECT DISTINCT token_key FROM operator_talent "
        f"WHERE token_key IS NOT NULL AND char_id IN ({ph})",
        tuple(TARGET_OPS))]
    check("十位干员的召唤物也纳入了范围（望、机械师各有一个）",
          len(toks) >= 2, f"实得 {toks}")
    scope = list(TARGET_OPS) + toks
    sph = ",".join("?" * len(scope))

    sk_desc = [r for r in conn.execute(
        "SELECT s.skill_id, s.description FROM skill_level s "
        "JOIN operator_skill o ON o.skill_id = s.skill_id "
        f"WHERE s.level = 7 AND o.char_id IN ({sph})", tuple(scope))
        if r[1] and any(x in r[1] for x in TERMS)]
    check("技能**描述**里零命中", not sk_desc, f"实得 {sk_desc[:3]}")

    KEYS = ("ep_", "burn", "corrosion", "necrosis")
    sk_bb = []
    for sid, bb in conn.execute(
            "SELECT s.skill_id, s.blackboard FROM skill_level s "
            "JOIN operator_skill o ON o.skill_id = s.skill_id "
            f"WHERE s.level = 10 AND o.char_id IN ({sph})", tuple(scope)):
        if bb:
            k = [x for x in json.loads(bb)
                 if any(w in x.lower() for w in KEYS)]
            if k:
                sk_bb.append((sid, k))
    check("技能**黑板**里零命中", not sk_bb, f"实得 {sk_bb[:3]}")

    tal = [r for r in conn.execute(
        f"SELECT char_id, name, description FROM operator_talent "
        f"WHERE char_id IN ({sph})", tuple(scope))
        if r[2] and any(x in r[2] for x in TERMS)]
    check("天赋**描述**里零命中", not tal, f"实得 {tal[:3]}")

    tal_bb = []
    for cid, bb in conn.execute(
            "SELECT char_id, blackboard FROM operator_talent "
            f"WHERE blackboard IS NOT NULL AND char_id IN ({sph})",
            tuple(scope)):
        k = [x for x in json.loads(bb) if any(w in x.lower() for w in KEYS)]
        if k:
            tal_bb.append((cid, k))
    check("天赋**黑板**里零命中", not tal_bb, f"实得 {tal_bb[:3]}")
    conn.close()

    # ---- 3. 数据其实**可得**：原始属性里有那三个 ep 键 ----
    e = lib.get("enemy_1007_slime")
    raw = dict(getattr(e, "raw_attributes", None) or {})
    check("原始敌人属性里**有**三个 ep 键（数据可得，只是没接）",
          {"epResistance", "epDamageResistance", "epBreakRecoverSpeed"}
          <= set(raw),
          f"实得 {sorted(k for k in raw if k.lower().startswith('ep'))}")
    check("原始属性共 32 个键，其中**没有**损伤条容量（这是最关键的缺口）",
          len(raw) == 32 and not any("bar" in k.lower() for k in raw),
          f"实得 {len(raw)} 个键")

    # ---- 4. 跳线：解析层一旦开始收 ep 键，说明有人动过这一层，
    #         那时请回来改本节与清单（`docs/elemental-damage-gaps.md` 第三节 b）。
    from ak_tactic.gamedata.enemy import EnemyStats  # noqa: PLC0415
    ep_fields = [f for f in EnemyStats.__dataclass_fields__ if "ep" in f.lower()]
    check("跳线：解析层（`EnemyStats`）目前**一个 ep 字段都没有**——"
          "开始收键时这条会失败，那时请把清单第三节 (b) 改成「已接」",
          not ep_fields, f"实得 {ep_fields}")


def check_skill_infix(stage, lib, calc, book_t) -> None:
    """[24] 技能槽**中缀**键的归一化，以及弹药的行为层。

    这一节来自一个真 bug：`attack@s3_atk_scale` 这种把**技能槽夹在 @ 后面**的
    写法，四级降级匹配全都够不着，于是提丰技3 的 `atk_scale` / `stun` /
    `trigger_time`（弹药数）**四个键一起落进 `other`**——技能一开启就因为
    `int(None or 0) == 0` 发弹药而**立刻结束**。

    原有的守卫只测了**数据层**（黑板里读到几发弹药），测不出这个：弹药数在
    `other` 里躺着，谁也没去读。所以这里两层都钉：**分类结果**与**实战日志**。
    """
    print("\n[24] 技能槽中缀键（`attack@s3_x`）的归一化与弹药行为")

    # ---- 1. 归一化：三个键各自归到该去的地方 ----
    want = {
        "attack@s3_atk_scale": ("damage", "atk_scale"),
        "attack@s3_stun": ("control", "stun"),
        "attack@s3_trigger_time": ("damage", "ammo"),
        "attack@atk_scale_s2": ("damage", "atk_scale"),   # 后缀写法不能回归
        "attack@atk_scale": ("damage", "atk_scale"),      # 裸写法不能回归
    }
    for key, (cls, name) in want.items():
        got = _classify(key)
        check(f"`{key}` → {cls}/{name}",
              got is not None and got[0] == cls and got[1] == name,
              f"实得 {got}")

    # ---- 2. 数据层：提丰技3 的三个键真的到位了 ----
    sbook = SkillBook()
    t3 = None
    for sk in sbook.for_operator("char_2012_typhon"):
        lv = sk.level(level=7, mastery=3)
        if lv.name == "“永恒狩猎”":
            t3 = lv
    check("找到提丰技3「永恒狩猎」", t3 is not None)
    if t3 is not None:
        check("  弹药 10 发（改前是 None → int(None or 0) = 0）",
              t3.effects.ammo == 10, f"实得 {t3.effects.ammo!r}")
        check("  攻击倍率 1.75（改前连 atk_scale 都没有）",
              close(float(t3.effects.damage.get("atk_scale") or 0), 1.75, 1e-9),
              f"实得 {t3.effects.damage.get('atk_scale')}")
        check("  晕眩 0.4 秒（改前在 other 里躺着）",
              close(float(t3.effects.control.get("stun") or 0), 0.4, 1e-9),
              f"实得 {t3.effects.control.get('stun')}")
        check("  `max_hit_num` 仍**未建模**——不知道它是不是 `times`，"
              "不猜（如实记）",
              "attack@s3_max_hit_num" in (t3.effects.other or {}),
              f"实得 {t3.effects.other}")

    # ---- 3. 行为层：实战日志里的弹药数必须**大于零**。
    #
    # 那行日志是 `f" 弹药 {op.ammo_left}" if op.ammo_left else ""`——**有弹药
    # 才打印**。所以"日志里抓得到一个正的弹药数"等价于"技能真的带着弹开了
    # 起来"；改前 ammo 落在 `other` 里，`ammo_left` 是 0，这行根本不会出现。
    #
    # **不要按 M3 的数断言。** `Deployment` 不指定专精时走 M0，提丰技3 的
    # `attack@s3_trigger_time` 在 M0 是 8、M3 才是 10。第一版就是按 10 写的，
    # 于是明明修好了却报红。**断言要跟被断言的配置一致**。
    sim = mechanism_sim(stage, lib, skill_book=SkillBook(), verbose=True)
    u = make_unit(calc, "char_2012_typhon", elite=2, level=90, trust=100)
    sim.plan(Deployment(1.0, u, (2, 3), "Right", skill=3, auto_skill=True,
                        talents=book_t.for_operator("char_2012_typhon")))
    sim.run()
    log = "\n".join(sim.result.log)
    m = re.search(r"弹药 (\d+)", log)
    check("实战日志里抓得到正的弹药数（有弹药才打印，所以这等价于"
          "「带弹开启」）",
          m is not None and int(m.group(1)) > 0,
          f"抓到的：{m.group(0) if m else '（没有）'}")
    check("  抓到的弹药数与 M0 的 8 一致（M3 是 10，别混）",
          m is not None and int(m.group(1)) == 8,
          f"实得 {m.group(1) if m else None}")
    # 改前的症状是"一开就结束"，所以还要证明它**活了一段时间**：
    # 开启与结束之间必须隔着若干次攻击。
    opened = re.search(r"([\d.]+)s  提丰 开启", log)
    ended = re.search(r"([\d.]+)s  提丰 技能.*结束", log)
    check("  技能活了足够久（不是一开就结束）",
          opened is not None and ended is not None
          and float(ended.group(1)) - float(opened.group(1)) > 10.0,
          f"开启 {opened.group(1) if opened else None}s、"
          f"结束 {ended.group(1) if ended else None}s")
    check("实战里这个技能确实开过（日志里有「永恒狩猎」）",
          "永恒狩猎" in log)


def check_barrier_scope(stage, lib, calc, book_t) -> None:
    """[25] 屏障的**叠加与衰减**：本批触不到，但全库里有标本。

    现在的 `OperatorUnit.grant_barrier` 用的是 `max`（不叠加），计划里把
    「叠加上限」列为未做。这一节把"**为什么现在可以不做**"钉住，顺便钉住
    "**什么时候就不能不做了**"。

    三条已查证的事实：

    1. 屏障**确实会叠加**——全库有明确写法：「屏障最高**叠加**至最大生命值的
       `{max_hp_ratio}`」（varkis技2，`max_hp_ratio = 1.0`）。
    2. 上限是**每个技能各自**的，**不是统一的 100%**——cairn技2 的上限是 90%
       （`shield_max_hp_ratio = 0.9`）；而 gravel技2 一次就给 **250%**
       （`hp_ratio = 2.5`）。**所以"统一按最大生命 100% 封顶"是错的。**
    3. **衰减**单独存在：gravel技2 在 10 秒内持续衰减、morgan技2 在 6 秒内、
       cairn技2 持续 10 秒。

    而**本批十位干员里只有两个技能给屏障**（电弧技1 100%、机械师技2 10%），
    两者都**没有上限键、没有衰减键**，都写「持续至技能结束」，且一次激活只授予
    一次——所以 `max` 与 `sum` 在本批里**完全等价**。这条等价关系就是本节要守的
    东西：哪天这两个技能里冒出上限或衰减键，说明范围变了。
    """
    print("\n[25] 屏障的叠加与衰减：本批触不到（等价性守卫）")
    conn = sqlite3.connect(
        Path(__file__).resolve().parent.parent / "data" / "akdb.sqlite")

    # ---- 1. 本批给屏障的技能**只有两个** ----
    ph = ",".join("?" * len(TARGET_OPS))
    granters = []
    for cid, sid, desc in conn.execute(
            "SELECT o.char_id, s.skill_id, s.description FROM skill_level s "
            "JOIN operator_skill o ON o.skill_id = s.skill_id "
            f"WHERE s.level = 10 AND o.char_id IN ({ph})", tuple(TARGET_OPS)):
        if desc and "屏障" in desc and "损伤屏障" not in desc:
            granters.append((cid, sid))
    check("本批只有 2 个技能给屏障（电弧技1、机械师技2）",
          len(granters) == 2, f"实得 {granters}")

    # ---- 2. 这两个技能既无上限键、也无衰减键 → `max` ≡ `sum` ----
    CAP_KEYS = ("max_hp_ratio", "shield_max_hp_ratio", "shield_hp_ratio")
    DECAY_KEYS = ("duration", "shield_duration", "buff_duration")
    for cid, sid in granters:
        bb = json.loads(conn.execute(
            "SELECT blackboard FROM skill_level WHERE skill_id=? AND level=10",
            (sid,)).fetchone()[0] or "{}")
        caps = [k for k in CAP_KEYS if k in bb]
        decays = [k for k in DECAY_KEYS if k in bb]
        check(f"  {sid} 没有上限键（有的话 `max` 就不再等价于 `sum`）",
              not caps, f"实得 {caps}")
        check(f"  {sid} 没有衰减键（屏障是「持续至技能结束」）",
              not decays, f"实得 {decays}")

    # ---- 3. 全库里的标本：叠加上限是**每技能各自**的，统一 100% 是错的 ----
    def bb_of(sid: str) -> dict:
        row = conn.execute(
            "SELECT blackboard FROM skill_level WHERE skill_id=? AND level=10",
            (sid,)).fetchone()
        return json.loads(row[0] or "{}") if row else {}

    v, c, g = bb_of("skchr_varkis_2"), bb_of("skchr_cairn_2"), bb_of("skchr_gravel_2")
    check("叠加上限真实存在：varkis技2 写死 `max_hp_ratio = 1.0`",
          close(float(v.get("max_hp_ratio") or 0), 1.0, 1e-9),
          f"实得 {v.get('max_hp_ratio')}")
    check("上限**不是**统一的：cairn技2 是 0.9（90%）",
          close(float(c.get("shield_max_hp_ratio") or 0), 0.9, 1e-9),
          f"实得 {c.get('shield_max_hp_ratio')}")
    check("**一次授予可以超过 100%**：gravel技2 是 2.5（250%）"
          "——所以「统一按 100% 封顶」是错的，这条钉住它",
          close(float(g.get("hp_ratio") or 0), 2.5, 1e-9),
          f"实得 {g.get('hp_ratio')}")
    check("衰减也真实存在：gravel技2 `duration = 10.0`（10 秒内持续衰减）",
          close(float(g.get("duration") or 0), 10.0, 1e-9),
          f"实得 {g.get('duration')}")
    conn.close()


def check_faction_aura(stage, lib, calc, book_t) -> None:
    """[28] 「万众巨潮」：**只在技能期间生效**且**按阵营翻倍**的全场光环。

    怒潮凛冬天赋2：「技能期间所有场上干员攻击力和防御力 +14%，【乌萨斯学生
    自治团】干员获得加成效果翻倍」。此前 `atk` / `def` / `scale_bonus` 三个键
    全在"无人读"里——`find_team_aura` 只认名字写死的「青色怒火」。

    两种光环**不能共用一个倍率**，这是本节最要紧的一条：

    * 青色怒火 = **常驻**底子，主人开技能时全场 ×2；
    * 万众巨潮 = 主人**不开技能就一点都没有**（0），开了才是底子，且只对
      自治团 ×`scale_bonus`。

    把后者写成前者，会得到一个"怒潮凛冬一上场就给全队加 14%"的错模型——
    她还没开技能呢。反向也一样错。所以本节把"未开技能必须为 0"单列一条。

    另外钉两点：`scale_bonus` 与青色怒火的 `talent_scale` 是**两个不同的键**
    （别互相当别名），以及**光环主人自己也在自治团里**，所以她吃双倍。
    """
    print("\n[28] 「万众巨潮」：技能期间的全场光环与阵营翻倍")
    from ak_tactic.battle.talents import (  # noqa: PLC0415
        STUDENT_TEAM, FACTION_AURA_NAME, TeamAura, find_team_aura,
        is_faction_aura_talent)

    cid = "char_1051_headb2"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_team_aura(tal)
    check("find_team_aura 认得「万众巨潮」（此前只认名字写死的青色怒火）",
          hit is not None and hit.name == FACTION_AURA_NAME,
          hit.name if hit else "None")
    check("它是阵营光环那一族", hit is not None and is_faction_aura_talent(hit))
    check("黑板 atk/def 都是 14%",
          abs(hit.value("atk", 0) - 0.14) < 1e-9 and abs(hit.value("def", 0) - 0.14) < 1e-9,
          f"atk={hit.value('atk')} def={hit.value('def')}")
    check("阵营倍率取自 `scale_bonus`（=2.0，不是青色怒火的 `talent_scale`）",
          abs(hit.value("scale_bonus", 0) - 2.0) < 1e-9,
          f"scale_bonus={hit.value('scale_bonus')}")
    check("自治团成员是 7 位（team_id='student'）", len(STUDENT_TEAM) == 7,
          f"{len(STUDENT_TEAM)} 位")
    check("光环主人怒潮凛冬**自己**也在自治团里",
          cid in STUDENT_TEAM)

    sim = mechanism_sim(stage, lib)
    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    owner.talents = tal
    mate = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    sim.operators.extend([owner, mate])
    sim.team_auras.append(TeamAura(
        owner=owner.name, atk_pct=hit.value("atk", 0.0), def_pct=hit.value("def", 0.0),
        operator=owner, skill_only=True, faction=STUDENT_TEAM,
        faction_scale=hit.value("scale_bonus", 2.0)))

    owner.skill_active = False
    sim._refresh_auras()
    check("主人**没开技能**时，全场一点光环都没有（不是常驻的）",
          mate.aura_atk_pct == 0.0 and owner.aura_atk_pct == 0.0,
          f"外人={mate.aura_atk_pct} 主人={owner.aura_atk_pct}")

    owner.skill_active = True
    sim._refresh_auras()
    check("技能期间：非自治团干员 +14%",
          abs(mate.aura_atk_pct - 0.14) < 1e-9, f"实得 {mate.aura_atk_pct}")
    check("技能期间：自治团干员翻倍到 +28%",
          abs(owner.aura_atk_pct - 0.28) < 1e-9, f"实得 {owner.aura_atk_pct}")
    check("攻防同值（描述里 atk/def 都给 14%）",
          abs(mate.aura_def_pct - 0.14) < 1e-9, f"实得 {mate.aura_def_pct}")

    owner.skill_active = False
    sim._refresh_auras()
    check("技能一结束光环立刻归零（不是留到下一帧或整场）",
          mate.aura_atk_pct == 0.0 and owner.aura_atk_pct == 0.0)


def check_class_aura(stage, lib, calc, book_t) -> None:
    """[29] 「特种作战策略」：**按职业**发的全场光环。

    星熊天赋2：「在场时所有友方【重装】职业干员的防御力提升 6%」。它在此前
    两份筛子里都报 0 欠账——因为它的键只有一个 `def`，`def` 归得了类，于是
    第一道放过、第二道（只在第一道失败时跑）也看不见它。**压根没有检测器。**

    本节钉三件事：

    1. **职业过滤真的在起作用**：非重装吃到的是 **0**，不是"也加 6%"；
    2. 它是**常驻**的（与万众巨潮相反）——主人不开技能照样发；
    3. `profession` 与 `faction` **是两个量**：`profession` 是主职业代号
       （`TANK`），`faction` 是阵营 `team_id`。混用会把"重装"发成"某个团"。

    职业是**游戏内部代号**（`TANK`/`SNIPER`…），不是中文名「重装」——判据要
    按代号取，中文名是显示层的东西。
    """
    print("\n[29] 「特种作战策略」：按职业发的全场光环")
    from ak_tactic.battle.talents import (  # noqa: PLC0415
        CLASS_AURA_TALENTS, TeamAura, find_class_aura, is_class_aura_talent)

    cid = "char_136_hsguma"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_class_aura(tal)
    check("find_class_aura 认得星熊「特种作战策略」",
          hit is not None and hit.name == "特种作战策略",
          hit.name if hit else "None")
    check("它是职业光环那一族", hit is not None and is_class_aura_talent(hit))
    check("黑板 def = 6%", abs(hit.value("def", 0) - 0.06) < 1e-9,
          f"def={hit.value('def')}")
    check("映射到的是**主职业代号** TANK，不是中文名「重装」",
          CLASS_AURA_TALENTS.get("特种作战策略") == "TANK",
          str(CLASS_AURA_TALENTS.get("特种作战策略")))

    # `profession` 是否真的从计算器一路送到了单位上（没送 = 光环恒不生效）
    tank = make_unit(calc, "char_311_mudrok", elite=2, level=60, potential=1)
    sniper = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    owner.talents = tal
    check("重装干员的 profession 是 TANK（星熊、泥岩）",
          owner.profession == "TANK" and tank.profession == "TANK",
          f"星熊={owner.profession} 泥岩={tank.profession}")
    check("非重装干员的 profession 不是 TANK（能天使是 SNIPER）",
          sniper.profession not in ("", "TANK"), f"能天使={sniper.profession}")

    sim = mechanism_sim(stage, lib)
    sim.operators.extend([owner, tank, sniper])
    sim.team_auras.append(TeamAura(
        owner=owner.name, atk_pct=hit.value("atk", 0.0),
        def_pct=hit.value("def", 0.0), operator=owner,
        profession=CLASS_AURA_TALENTS[hit.name]))

    owner.skill_active = False
    sim._refresh_auras()
    check("**常驻**：主人没开技能时，重装照样拿 +6%（与万众巨潮相反）",
          abs(tank.aura_def_pct - 0.06) < 1e-9, f"泥岩实得 {tank.aura_def_pct}")
    check("光环主人**自己是重装**，所以自己也吃",
          abs(owner.aura_def_pct - 0.06) < 1e-9, f"星熊实得 {owner.aura_def_pct}")
    check("**非重装一点都吃不到**（这才是职业过滤的意义）",
          sniper.aura_def_pct == 0.0, f"能天使实得 {sniper.aura_def_pct}")
    check("它只加防御、不加攻击（黑板里没有 atk）",
          tank.aura_atk_pct == 0.0 and abs(tank.aura_def_pct - 0.06) < 1e-9,
          f"atk={tank.aura_atk_pct} def={tank.aura_def_pct}")

    owner.skill_active = True
    sim._refresh_auras()
    check("主人开技能**不会**把它翻倍（没有 `double_scale` 那回事）",
          abs(tank.aura_def_pct - 0.06) < 1e-9, f"泥岩实得 {tank.aura_def_pct}")

    # ---- 反向守卫：职业为空必须**不匹配** ----
    # 空集对任何集合都是子集，这类"空值恰好通过"的写法在这套代码里已经咬过
    # 几次（见 `GENERIC_TALENT_KEYS` 那条空键表豁免）。手工搭的试验体
    # `profession` 就是空串，它绝不能因为"没填"而白拿 6%。
    blank = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    blank.profession = ""
    sim.operators.append(blank)
    sim._refresh_auras()
    check("profession 是空串的试验体**不匹配**职业光环（反向守卫）",
          blank.aura_def_pct == 0.0, f"实得 {blank.aura_def_pct}")

    # 提升档的门槛：库里 `required_potential_rank = 5`，而 rank = 潜能等级 − 1，
    # 所以那一档是**潜能 6**，不是潜 5。这条一开始写错过一次——按「潜5」取，
    # 拿回来的还是 6%，断言失败。**rank 与潜能编号差 1，别按名字想当然。**
    tal6 = book_t.for_operator(cid, elite=2, level=60, potential=6)
    hit6 = find_class_aura(tal6)
    check("潜能 6 档是 8%（`required_potential_rank=5` → 潜能 6）",
          hit6 is not None and abs(hit6.value("def", 0) - 0.08) < 1e-9,
          f"def={hit6.value('def') if hit6 else None}")
    hit5 = find_class_aura(book_t.for_operator(cid, elite=2, level=60, potential=5))
    check("潜能 5 档仍是 6%（反向：别把提升档提前一档）",
          hit5 is not None and abs(hit5.value("def", 0) - 0.06) < 1e-9,
          f"def={hit5.value('def') if hit5 else None}")


def check_second_use(stage, lib, calc, book_t) -> None:
    """[27] 「第二次及以后使用」的变体取值（怒潮凛冬技2「绝不罢休」）。

    黑板用方括号键给"同一条属性在另一个场合的取值"：`atk 0.9` 是第 1 次的，
    `headb2_s_2[second].atk 1.8` 是第 2 次起的。描述写「第二次及以后使用时
    能力加成变为最初的两倍，**且持续时间无限**」。

    这个坑的形状值得记：**解析层一直是对的**——`_parse_effects` 早把 `[second]`
    收进了 `variants`，`SkillEffects.with_variant()` 也早就写好（它的 docstring
    拿本例当标准用例）。缺的只是**从没有人调用它**，于是模拟器一直按第一次的
    90% 算。解析有、API 有、没人接线——这类"看着像做好了"最容易漏。

    本节还钉住三条边界：
    1. **第 1 次不受影响**（16 秒、90%）——否则等于把变体一路套到底；
    2. **"无限"挂在「第二次及以后」那个从句里**，所以不能拿 `infinite` 单独判
       （它对第 1 次也为真，该技能 `infinite` 本来就是 True）；
    3. 第 3 次及以后**保持**第 2 次的取值，不会继续翻倍。
    """
    print("\n[27] 「第二次及以后使用」的变体取值（怒潮凛冬技2）")
    from ak_tactic.battle.sim import _INFINITE  # noqa: PLC0415

    cid = "char_1051_headb2"
    lv = next(s for s in SkillBook().for_operator(cid) if s.slot == 2).level(7, 3)
    e = lv.effects
    check("技2 的第一次加成在黑板基础键上", abs(e.buffs.get("atk", 0) - 0.9) < 1e-9,
          f"atk={e.buffs.get('atk')}")
    check("[second] 变体被解析出来（解析层一直是对的）",
          (e.variants.get("second") or {}).get("atk") == 1.8,
          str(e.variants.get("second")))
    check("with_variant 是替换语义（1.8 是 0.9 的两倍，不是相加的 2.7）",
          abs(e.with_variant("second").buffs.get("atk", 0) - 1.8) < 1e-9)

    sim = mechanism_sim(stage, lib)
    op = make_unit(calc, cid, elite=2, level=60, potential=1)
    op.skill = next(s for s in SkillBook().for_operator(cid) if s.slot == 2).level(7, 3)
    sim._activate(op, 0.0)
    a1 = op.effects.buffs.get("atk")
    d1 = op.effects.buffs.get("def")
    t1 = op.skill_timer
    check("第 1 次 atk 仍是 90%", abs(a1 - 0.9) < 1e-9, f"atk={a1}")
    check("第 1 次 def 仍是 60%", abs(d1 - 0.6) < 1e-9, f"def={d1}")
    check("第 1 次时长 16s（不是无限）", abs(t1 - 16.0) < 1e-9, f"timer={t1}")
    sim._deactivate(op, 1.0)
    check("技能结束后 effects 归 None", op.effects is None)

    sim._activate(op, 10.0)
    a2 = op.effects.buffs.get("atk")
    d2 = op.effects.buffs.get("def")
    check("第 2 次 atk 是 180%（描述写「变为最初的两倍」）",
          abs(a2 - 1.8) < 1e-9, f"atk={a2}")
    check("第 2 次 def 是 120%", abs(d2 - 1.2) < 1e-9, f"def={d2}")
    check("第 2 次时长无限（描述是「且持续时间无限」）",
          op.skill_timer >= _INFINITE - 1, f"timer={op.skill_timer}")
    sim._activate(op, 20.0)
    check("第 3 次保持 180%，不会继续翻倍",
          abs(op.effects.buffs.get("atk", 0) - 1.8) < 1e-9,
          f"atk={op.effects.buffs.get('atk')}")

    # 反向守卫：不带 [second] 的技能**必须**不受影响，否则这条接线会误伤全体。
    other = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    other.skill = next(s for s in SkillBook().for_operator("char_103_angel")
                       if s.slot == 1).level(7, 3)
    sim3 = mechanism_sim(stage, lib)
    sim3._activate(other, 0.0)
    first = dict(other.effects.buffs)
    sim3._deactivate(other, 1.0)
    sim3._activate(other, 10.0)
    check("没有 [second] 变体的技能，第 2 次取值与第 1 次一致",
          dict(other.effects.buffs) == first,
          f"{first} -> {dict(other.effects.buffs)}")


def check_damage_block(stage, lib, calc, book_t) -> None:
    """[30] 「战术装甲」：**常驻**的伤害抵挡（星熊天赋1）。

    描述：「获得 X% 的伤害抵挡」。这一条此前两份筛子都报 0 欠账——它的键是
    `prob`，归得了类，于是第一道放过、第二道（只在第一道失败时跑）也看不见它。

    两件必须钉住的事：

    1. **E2 取到的是 25%，不是 12%。** 库里四个候选按**精英阶段**分两组
       （精0/精1 是 12%/15%，精2 是 25%/28%）。只取"第一个候选"会拿到 12%
       ——**错一半，且不报错**。
    2. **它必须活过技能的开关。** 技能那套闪避由 `_activate` 置上、
       `_deactivate` **清零**；天赋是常驻的。两者塞进同一个字段，星熊一开
       一关技能抵挡就没了。所以走**独立字段**并在受伤结算处相加。

    另钉一条**已知边界**：`resolve_damage` 里的抵挡只对物理/法术生效，
    **真实伤害不吃**。这是借闪避通道表达带来的后果，写在这里免得日后当 bug 查。
    """
    print("\n[30] 「战术装甲」：常驻的伤害抵挡")
    from ak_tactic.battle.damage import DamageType, resolve_damage  # noqa: PLC0415
    from ak_tactic.battle.talents import (  # noqa: PLC0415
        find_damage_block, is_damage_block_talent)

    cid = "char_136_hsguma"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_damage_block(tal)
    check("find_damage_block 认得星熊「战术装甲」",
          hit is not None and hit.name == "战术装甲",
          hit.name if hit else "None")
    check("它是伤害抵挡那一族", hit is not None and is_damage_block_talent(hit))
    check("**E2 取到 25%，不是精0/精1 档的 12%**",
          hit is not None and abs(hit.value("prob", 0) - 0.25) < 1e-9,
          f"prob={hit.value('prob') if hit else None}")
    tal3 = find_damage_block(book_t.for_operator(cid, elite=2, level=60, potential=3))
    check("潜能 3 档是 28%（`required_potential_rank=2`）",
          tal3 is not None and abs(tal3.value("prob", 0) - 0.28) < 1e-9,
          f"prob={tal3.value('prob') if tal3 else None}")
    tal1 = find_damage_block(book_t.for_operator(cid, elite=1, level=70, potential=1))
    check("精 1 档是 12%（阶别不同值不同，别只取第一个候选）",
          tal1 is not None and abs(tal1.value("prob", 0) - 0.12) < 1e-9,
          f"prob={tal1.value('prob') if tal1 else None}")
    tal0 = find_damage_block(book_t.for_operator(cid, elite=0, level=50, potential=1))
    check("精 0 **根本没有这条天赋**（精 1 才解锁，不是 0%）",
          tal0 is None, f"取到 {tal0.name if tal0 else None}")

    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    owner.talents = tal
    sim = mechanism_sim(stage, lib)
    sim.operators.append(owner)
    sim._do_deploy(Deployment(time=0.0, operator=owner, position=(2, 2),
                              direction="Right", talents=tal), 0.0)
    check("部署后抵挡落到**天赋**字段（不是技能那个字段）",
          abs(owner.talent_dodge_phys - 0.25) < 1e-9
          and abs(owner.talent_dodge_arts - 0.25) < 1e-9,
          f"phys={owner.talent_dodge_phys} arts={owner.talent_dodge_arts}")
    check("技能那个字段**保持为 0**（别把常驻值塞进去）",
          owner.dodge_phys == 0.0 and owner.dodge_arts == 0.0,
          f"dodge_phys={owner.dodge_phys}")

    # ---- 关键反向守卫：开一次技能再关掉，抵挡必须还在 ----
    # 这一条正是"分字段"的存在理由。合成一个字段时，下面这一条会红。
    owner.dodge_phys = 0.6
    owner.dodge_arts = 0.6
    owner.dodge_phys = 0.0
    owner.dodge_arts = 0.0
    check("技能闪避被清零后，**天赋抵挡仍在**（反向守卫：分字段的理由）",
          abs(owner.dodge_phys + owner.talent_dodge_phys - 0.25) < 1e-9,
          f"实得 {owner.dodge_phys + owner.talent_dodge_phys}")

    # ---- 真的减到伤害上了吗 ----
    plain = resolve_damage(1000.0, damage_type=DamageType.PHYSICAL,
                           defense=0.0, dodge_phys=0.0)
    cut = resolve_damage(1000.0, damage_type=DamageType.PHYSICAL,
                         defense=0.0, dodge_phys=owner.talent_dodge_phys)
    check("物理伤害按 25% 折（1000 → 750）", abs(cut.final - 750.0) < 1e-6,
          f"实得 {cut.final}")
    cut_m = resolve_damage(1000.0, damage_type=DamageType.MAGIC,
                           res=0.0, dodge_arts=owner.talent_dodge_arts)
    check("法术伤害同样折（「伤害抵挡」不分伤害类型）",
          abs(cut_m.final - 750.0) < 1e-6, f"实得 {cut_m.final}")
    check("描述里没写限物理，所以物理与法术**同值**",
          abs(owner.talent_dodge_phys - owner.talent_dodge_arts) < 1e-12)

    # ---- 已知边界：真伤不吃 ----
    cut_t = resolve_damage(1000.0, damage_type=DamageType.TRUE, defense=0.0,
                           dodge_phys=owner.talent_dodge_phys)
    check("**已知边界**：真实伤害不吃抵挡（借闪避通道的后果，见 docstring）",
          abs(cut_t.final - 1000.0) < 1e-6, f"实得 {cut_t.final}")
    check("对照：不带抵挡的物理确实是原值（证明上面那条不是没接上）",
          abs(plain.final - 1000.0) < 1e-6, f"实得 {plain.final}")

    # ---- 别人不该白拿 ----
    other = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    sim2 = mechanism_sim(stage, lib)
    sim2.operators.append(other)
    sim2._do_deploy(Deployment(time=0.0, operator=other, position=(2, 2),
                               direction="Right"), 0.0)
    check("没有这条天赋的干员，天赋抵挡是 0",
          other.talent_dodge_phys == 0.0 and other.talent_dodge_arts == 0.0)


def check_dot_on_hit(stage, lib, calc, book_t) -> None:
    """[31] 「死亡拘审」：攻击挂上去的持续法术伤害（阿斯卡纶天赋1）。

    正文：「攻击对敌人施加效果：移动速度降低 12%，**每秒受到 6% 阿斯卡纶
    当前攻击力的法术伤害**，持续 18 秒，效果最多叠加三层」。

    与 `[30]` 同源的坑：它的键是 `atk_ratio`，**归得了类**，所以第一道筛子
    放过、第二道（只在第一道失败时跑）也看不见——两道键级筛子都报 0 欠账。

    本节钉四件事：

    1. **续层不是重挂**：层数 +1 封顶、剩余秒数重置、每秒伤害按本次出手快照。
    2. **`dot_accum` 不能被续层清掉**——它是"离下一跳还差多少"的累加器。
       攻击快过 1 秒时，每挂一层清一次的话**一跳都不会发生**，且不报错。
    3. **跳一次要真的打到敌人身上**，走法术那一路（不是物理）。
    4. **不带这条天赋的人一跳都不该有**（反向对照，防"接上了但没接对人"）。
    """
    print("\n[31] 「死亡拘审」：攻击挂上去的持续法术伤害")
    from types import SimpleNamespace  # noqa: PLC0415

    from ak_tactic.battle.damage import DamageType  # noqa: PLC0415
    from ak_tactic.battle.talents import find_dot_on_hit  # noqa: PLC0415

    cid = "char_4132_ascln"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_dot_on_hit(tal)
    check("find_dot_on_hit 认得阿斯卡纶「死亡拘审」",
          hit is not None and hit.name == "死亡拘审",
          hit.name if hit else "None")
    check("**E2 档读到的是 10% / 25 秒**（不是精0 那档的 6% / 18 秒）",
          hit is not None and abs(hit.value("atk_ratio") - 0.10) < 1e-9
          and abs(hit.value("debuff_duration") - 25.0) < 1e-9
          and abs(hit.value("interval") - 1.0) < 1e-9
          and abs(hit.value("max_stack_cnt") - 3.0) < 1e-9,
          f"ratio={hit.value('atk_ratio') if hit else None} "
          f"dur={hit.value('debuff_duration') if hit else None}")
    # 三条候选**按精英阶段**各是各的，只取第一个候选会整场少算四成。
    e0 = [x for x in book_t.for_operator(cid, elite=0, level=1, potential=1)
          if x.name == "死亡拘审"]
    e1 = [x for x in book_t.for_operator(cid, elite=1, level=70, potential=1)
          if x.name == "死亡拘审"]
    check("反向：精 0 档是 6% / 18 秒", bool(e0)
          and abs(e0[0].value("atk_ratio") - 0.06) < 1e-9
          and abs(e0[0].value("debuff_duration") - 18.0) < 1e-9,
          f"ratio={e0[0].value('atk_ratio') if e0 else None}")
    check("反向：精 1 档是 8% / 18 秒（三档各不同）", bool(e1)
          and abs(e1[0].value("atk_ratio") - 0.08) < 1e-9
          and abs(e1[0].value("debuff_duration") - 18.0) < 1e-9,
          f"ratio={e1[0].value('atk_ratio') if e1 else None}")
    other = book_t.for_operator("char_1048_orchd2", elite=2, level=60,
                                potential=1)
    check("反向：焰狐龙梓兰的天赋里没有这一条（不是谁都能挂）",
          find_dot_on_hit(other) is None)

    # ---- 续层语义：用替身目标直测 `_apply_dot` ----
    sim0 = mechanism_sim(stage, lib)
    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    proxy = SimpleNamespace(dot_stacks=0, dot_timer=0.0, dot_per_sec=0.0,
                            dot_accum=0.0, dot_interval=1.0)
    for _ in range(5):
        sim0._apply_dot(proxy, owner, hit)
    check("叠 5 次封顶在 3 层（不是 5 层）", proxy.dot_stacks == 3,
          f"实得 {proxy.dot_stacks}")
    check("每次续层把剩余秒数重置为满 25 秒（E2 档的时长）",
          abs(proxy.dot_timer - 25.0) < 1e-9, f"实得 {proxy.dot_timer}")
    want = owner.current_atk() * hit.value("atk_ratio")
    check("每秒伤害 = 本次出手攻击力 × 10%（快照）",
          abs(proxy.dot_per_sec - want) < 1e-6,
          f"实得 {proxy.dot_per_sec}，应为 {want}")
    proxy.dot_accum = 0.9
    sim0._apply_dot(proxy, owner, hit)
    check("**续层不清累加器**（反向守卫：清了就一跳都不会发生）",
          abs(proxy.dot_accum - 0.9) < 1e-9, f"实得 {proxy.dot_accum}")

    # ---- 端到端 + 反向对照：法术跳伤只能来自这条天赋 ----
    def magic_hits(talents):
        s = mechanism_sim(stage, lib)
        o = make_unit(calc, cid, elite=2, level=60, potential=1)
        s.operators.append(o)
        s._do_deploy(Deployment(0.0, o, (2, 3), "Right", talents=talents), 0.0)
        seen: list[float] = []
        real = s._damage_enemy

        def spy(target, final, t, *a, **kw):
            if a and a[0] == DamageType.MAGIC:
                seen.append(round(final, 6))
            return real(target, final, t, *a, **kw)

        s._damage_enemy = spy
        s.run()
        return seen

    with_tal = magic_hits(tal)
    without = magic_hits([])
    check("端到端：带天赋的一局里，敌人身上**真的跳过**法术伤害",
          len(with_tal) > 0, f"跳到 {len(with_tal)} 次")
    check("**反向对照**：同一套部署、不带这条天赋，一跳都没有",
          len(without) == 0, f"不带时跳到 {len(without)} 次")
    want_tick = owner.current_atk() * hit.value("atk_ratio")
    check("跳伤量级 ≈ 层数 × 每层每秒（单跳不超过 3 层）",
          all(v <= want_tick * 3 + 1e-6 for v in with_tal),
          f"最大一跳 {max(with_tal) if with_tal else 0:.3f}，"
          f"上限 {want_tick * 3:.3f}")


def check_high_ground_aspd(stage, lib, calc, book_t) -> None:
    """[32] 「噬光残影」的**地形条件**攻速：周围四格有高台时额外 +6。

    正文：「攻击速度+8，**自身周围四格有高台时，攻击速度额外+6**」。
    黑板 `{attack_speed: 8.0, attack_speed_add: 6.0, cnt: 1.0}`。

    `attack_speed: 8` 一直是被通用链路接走的，欠的是 `attack_speed_add: 6`
    ——它归得了类，所以两道键级筛子都看不见。

    与既有那条「未阻挡敌人时」的条件**不同**：那条是**实时状态**（每帧判），
    这条是**地形事实**——伏击客不移动，部署那一刻判一次就定死。

    本节钉四件事：取数（+8 常驻、+6 条件）、**高台旁边真的加**、
    **没有高台真的不加**（反向，这才是关键）、以及别人不白拿。
    """
    print("\n[32] 「噬光残影」的地形条件攻速")
    cid = "char_4132_ascln"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = [x for x in tal if x.name == "噬光残影"]
    check("天赋「噬光残影」取得", bool(hit))
    check("常驻 +8 与条件 +6 是两个键",
          bool(hit) and abs(hit[0].value("attack_speed") - 8.0) < 1e-9
          and abs(hit[0].value("attack_speed_add") - 6.0) < 1e-9)

    base = make_unit(calc, cid, elite=2, level=60, potential=1)
    check("单位身上：常驻并入 `attack_speed`（100+8=108）、条件 6 单独放",
          abs(base.attack_speed - 108.0) < 1e-9
          and abs(base.aspd_high_ground - 6.0) < 1e-9,
          f"attack_speed={base.attack_speed} high={base.aspd_high_ground}")
    base.high_ground_neighbor = False
    check("**没有高台时只算 8**（反向守卫）",
          abs(base.current_attack_speed() - 108.0) < 1e-9,
          f"实得 {base.current_attack_speed()}")
    base.high_ground_neighbor = True
    check("**有高台时算 14**（108 → 114）",
          abs(base.current_attack_speed() - 114.0) < 1e-9,
          f"实得 {base.current_attack_speed()}")
    check("这条加成的出处会进 `sources`（对账用）",
          "周围四格有高台" in attack_speed_bonus(
              calc, cid, elite=2, level=60, potential=1).describe())

    # ---- 由模拟器按地图判：找一个旁边有高台的位置和一个没有的 ----
    m = stage.map if hasattr(stage, "map") else stage
    with_hg, without_hg = None, None
    for y in range(m.height):
        for x in range(m.width):
            if not m.tile(x, y).deployable_ranged and not m.tile(x, y).deployable_melee:
                continue
            near = any(m.tile(x + dx, y + dy).is_highland
                       for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
            if near and with_hg is None:
                with_hg = (x, y)
            if not near and without_hg is None:
                without_hg = (x, y)
    check("这张图上既有『旁边有高台』的位置、也有『旁边没有』的位置",
          with_hg is not None and without_hg is not None,
          f"有={with_hg} 无={without_hg}")

    def deployed_flag(pos):
        s = mechanism_sim(stage, lib)
        o = make_unit(calc, cid, elite=2, level=60, potential=1)
        s.operators.append(o)
        s._do_deploy(Deployment(0.0, o, pos, "Right", talents=tal), 0.0)
        return o.high_ground_neighbor, o.current_attack_speed()

    if with_hg is not None:
        flag, spd = deployed_flag(with_hg)
        check(f"摆在 {with_hg}（旁边有高台）：模拟器判为真、总攻速 114",
              flag is True and abs(spd - 114.0) < 1e-9, f"flag={flag} spd={spd}")
    if without_hg is not None:
        flag, spd = deployed_flag(without_hg)
        check(f"摆在 {without_hg}（旁边没高台）：**判为假**、总攻速 108",
              flag is False and abs(spd - 108.0) < 1e-9, f"flag={flag} spd={spd}")

    other = make_unit(calc, "char_103_angel", elite=2, level=60, potential=1)
    check("别人不白拿：能天使条件攻速 0（她 100+12=112 常驻）",
          abs(other.aspd_high_ground) < 1e-12 and abs(other.attack_speed - 112.0) < 1e-9,
          f"high={other.aspd_high_ground} flat={other.attack_speed}")


def check_angel_blessing(stage, lib, calc, book_t) -> None:
    """[33] 「天使的祝福」的**自身那半**（能天使天赋1）。

    正文：「攻击力+6%，生命上限+10%。置入战场后这个效果会**同样赋予给一名
    随机友方单位**」。

    **本节只覆盖前半句。**「随机友方」那半需要一个口径（最先部署的友方？
    期望摊给全队？），**没有裁定就不动手**，见 `docs/uncertainties.md`。
    所以这条天赋**只算做了一半**——审计里它仍是待办，别当成已收口。

    自身那半借光环通道表达，新增 `TeamAura.self_only`。**判等必须按对象
    同一性**（`target is self.operator`）而不是 `char_id`——同一关里可以有
    同名干员，按 char_id 会把别人的那份也发出去。

    关键断言是**反向**那条：友方拿不到这 6%。
    """
    print("\n[33] 「天使的祝福」的自身那半（随机友方那半未做）")
    from ak_tactic.battle.talents import find_angel_blessing  # noqa: PLC0415

    cid = "char_103_angel"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_angel_blessing(tal)
    check("find_angel_blessing 认得能天使「天使的祝福」",
          hit is not None and hit.name == "天使的祝福",
          hit.name if hit else "None")
    check("E2 潜 1 读数是 +6% 攻击 / +10% 生命上限",
          hit is not None and abs(hit.value("atk") - 0.06) < 1e-9
          and abs(hit.value("max_hp") - 0.10) < 1e-9,
          f"atk={hit.value('atk') if hit else None} "
          f"max_hp={hit.value('max_hp') if hit else None}")
    tal3 = find_angel_blessing(book_t.for_operator(cid, elite=2, level=60,
                                                   potential=6))
    check("反向：潜能 6 档才是 +8% / +13%（潜 1~5 都是 6/10）",
          tal3 is not None and abs(tal3.value("atk") - 0.08) < 1e-9
          and abs(tal3.value("max_hp") - 0.13) < 1e-9,
          f"atk={tal3.value('atk') if tal3 else None}")
    check("反向：星熊的天赋里没有这一条",
          find_angel_blessing(book_t.for_operator("char_136_hsguma", elite=2,
                                                  level=60, potential=1)) is None)

    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    hp_before = owner.max_hp
    ally = make_unit(calc, "char_4132_ascln", elite=2, level=60, potential=1)
    ally_hp_before = ally.max_hp
    sim = mechanism_sim(stage, lib)
    sim.operators.extend([owner, ally])
    sim._do_deploy(Deployment(0.0, owner, (2, 3), "Right", talents=tal), 0.0)
    sim._do_deploy(Deployment(0.0, ally, (3, 3), "Right", talents=[]), 0.0)

    check("自己吃到 +6% 攻击", abs(owner.aura_atk_pct - 0.06) < 1e-9,
          f"实得 {owner.aura_atk_pct}")
    check("自己吃到 +10% 生命上限",
          abs(owner.max_hp - hp_before * 1.10) < 1e-6,
          f"实得 {owner.max_hp}，应为 {hp_before * 1.10}")
    check("**反向：友方一点都拿不到**（self_only 只发主人自己）",
          abs(ally.aura_atk_pct) < 1e-12, f"实得 {ally.aura_atk_pct}")
    check("反向：友方的生命上限也没被加",
          abs(ally.max_hp - ally_hp_before) < 1e-6,
          f"实得 {ally.max_hp}，原 {ally_hp_before}")


def check_limit_dispatch(stage, lib, calc, book_t) -> None:
    """[35] 「极限调度」的攻击力那半（可露希尔天赋2）。

    正文：「携带可露希尔时，**部署费用下限降低 3**，【罗德岛】干员攻击力 +4%」
    ——`{atk: 0.04, cost: -3.0}`。

    **本节只覆盖攻击力那半。**「部署费用下限」属名册/费用规则侧，不在
    `battle/`——所以这条天赋**只算做了一半**，审计里仍是待办。

    【罗德岛】取 `nation_id == 'rhodes'`，**不是 `team_id`**：那列是**小队**
    （`student`/`rainbow`…），而且能天使的 `team_id` 是 None 却属**龙门**。
    所以本节的反向对照特意用**龙门**的星熊，而不是"`team_id` 为空的人"。

    端到端那两条是关键的：`nation_id` 真的从库里走到了单位身上，
    判据才可能触发——**只验函数算得对是不够的**。
    """
    print("\n[35] 「极限调度」：【罗德岛】+4% 攻击（费用那半未做）")
    from ak_tactic.battle.talents import (RHODES_NATION,  # noqa: PLC0415
                                          find_limit_dispatch)

    cid = "char_4228_closur"
    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    hit = find_limit_dispatch(tal)
    check("find_limit_dispatch 认得可露希尔「极限调度」",
          hit is not None and hit.name == "极限调度",
          hit.name if hit else "None")
    check("攻击力加成是 +4%",
          hit is not None and abs(hit.value("atk") - 0.04) < 1e-9,
          f"实得 {hit.value('atk') if hit else None}")
    check("同一条天赋里还有 cost:-3（费用那半，不在战斗层，未做）",
          hit is not None and abs(hit.value("cost") - (-3.0)) < 1e-9,
          f"cost={hit.value('cost') if hit else None}")
    check("反向：星熊的天赋里没有这一条",
          find_limit_dispatch(book_t.for_operator("char_136_hsguma", elite=2,
                                                  level=60, potential=1)) is None)

    owner = make_unit(calc, cid, elite=2, level=60, potential=1)
    rhodes = make_unit(calc, "char_002_amiya", elite=2, level=60, potential=1)
    lungmen = make_unit(calc, "char_136_hsguma", elite=2, level=60, potential=1)
    check("端到端：`nation_id` 真的走到了单位身上（阿米娅 rhodes）",
          rhodes.nation_id == RHODES_NATION, f"实得 {rhodes.nation_id!r}")
    check("端到端：星熊是 lungmen（龙门），**不是**罗德岛",
          lungmen.nation_id == "lungmen", f"实得 {lungmen.nation_id!r}")

    sim = mechanism_sim(stage, lib)
    sim.operators.extend([owner, rhodes, lungmen])
    sim._do_deploy(Deployment(0.0, owner, (2, 3), "Right", talents=tal), 0.0)
    sim._do_deploy(Deployment(0.0, rhodes, (3, 3), "Right", talents=[]), 0.0)
    sim._do_deploy(Deployment(0.0, lungmen, (3, 4), "Right", talents=[]), 0.0)

    check("【罗德岛】的阿米娅吃到 +4%",
          abs(rhodes.aura_atk_pct - 0.04) < 1e-9, f"实得 {rhodes.aura_atk_pct}")
    check("可露希尔自己也是罗德岛，同样吃到 +4%",
          abs(owner.aura_atk_pct - 0.04) < 1e-9, f"实得 {owner.aura_atk_pct}")
    check("**反向：龙门的星熊一点都拿不到**（筛选不是翻倍）",
          abs(lungmen.aura_atk_pct) < 1e-12, f"实得 {lungmen.aura_atk_pct}")


def check_push(stage, lib, calc, book_t) -> None:

    """[26] 位移接线：推击把敌人推离路线，且推完能走回来。

    位置本来是 `point_at(route, progress)` 推出来的，**没有"脱离路线"这个概念**
    ——这是位移一直只停在规则层的原因。本节的判据因此分三层：

    1. **数据**：圣聆初雪技1 的 `force` 是力度等级（中力 = 1），描述写"推动"；
    2. **单位**（不跑战斗，直接造对象）：推离的**距离**等于查表值、`progress`
       分毫不动、然后能**走回路线**；
    3. **那个陷阱**：被推开的敌人必须**同时解除阻挡**——`advance` 开头就是
       "被阻挡就不动"，而 `_update_blocking` 只在阻挡者阵亡时清 `blocked_by`，
       是 latch 的。不解除的话推动会被**静默吃掉**，且没有任何报错。
    4. **集成**：实战里真的推出去了。
    """
    print("\n[26] 位移接线：推离路线、走回原路、以及阻挡的 latch 陷阱")
    import re as _re  # noqa: PLC0415

    # ---- 1. 数据层 ----
    sbook = SkillBook()
    s1 = None
    for sk in sbook.for_operator("char_1046_sbell2"):
        lv = sk.level(level=7, mastery=3)
        if lv.name == "铃音吹雪":
            s1 = lv
    check("找到圣聆初雪技1「铃音吹雪」", s1 is not None)
    if s1 is not None:
        check("  `force` = 1.0（力度等级：中等力度 = 中力 = 1，**不是距离**）",
              close(float(s1.blackboard.get("force") or 0), 1.0, 1e-9),
              f"实得 {s1.blackboard.get('force')}")
        check("  描述里写的是「推动」而不是「诱导」"
              "（技3 的诱导是另一套，不算推拉）",
              "推动" in (s1.description or ""), f"实得 {(s1.description or '')[:40]}")
        check("  等级换算：D.skill_force_level(1.0) == 1",
              D.skill_force_level(1.0) == 1, f"实得 {D.skill_force_level(1.0)}")

    # ---- 2. 集成层：跑到一半就停（跑到全死就没活敌人可测了）----
    #
    # 第一版跑到 `run()` 自然结束，于是 `sim.enemies[0]` 是**尸体**——
    # `advance` 开头 `if not self.alive: return` 直接返回，"走回路线"永远
    # 测不出来（跑了 10 万帧都没归位）。判据没错，是**被测对象选错了**。
    sim = mechanism_sim(stage, lib, skill_book=SkillBook(), verbose=True)
    u = make_unit(calc, "char_1046_sbell2", elite=2, level=90, trust=100)
    sim.plan(Deployment(1.0, u, (2, 3), "Right", skill=1, auto_skill=True,
                        talents=book_t.for_operator("char_1046_sbell2")))

    hook_calls: list[tuple[float, float, int]] = []
    orig_hook = BattleSimulator._apply_push

    def hooked(self, op, t_):  # noqa: ANN001, ANN202
        sk = op.skill
        bb = getattr(sk, "blackboard", None) or {}
        n_in = sum(1 for e in self.enemies
                   if e.hp > 0 and not e.leaked and not e.off_map
                   and e.cell() in self._range_of(op))
        hook_calls.append((float(bb.get("force") or 0.0), t_, n_in))
        return orig_hook(self, op, t_)

    BattleSimulator._apply_push = hooked
    try:
        sim.run(max_time=40.0)
    finally:
        BattleSimulator._apply_push = orig_hook

    check("技能开启时确实走到了推击这一步（挂点接对了）",
          len(hook_calls) > 0, f"实得 {len(hook_calls)} 次")
    check("  每一次都读到了 `force = 1.0`（力度等级，不是距离）",
          all(f == 1.0 for f, _, _ in hook_calls) and hook_calls,
          f"实得 {sorted({f for f, _, _ in hook_calls})}")
    live = [e for e in sim.enemies
            if e.hp > 0 and not e.leaked and not e.off_map]
    check("跑到 40 秒时场上还有活敌人（这是选对被测对象的前提）",
          len(live) > 0, f"实得 {len(live)} 个活敌人")

    # ---- 3. 单位层：推离、progress 不动、走回原路 ----
    if live:
        e = live[0]
        op = sim.operators[0]
        op.blocking.append(e)
        e.blocked_by = op          # 先摆成"被阻挡"，把 latch 陷阱现出来
        prog0 = e.progress
        pos0 = e.position
        e.apply_push(2.0, 0.0)
        check("推动是瞬时的：坐标立刻变",
              abs(e.position[0] - (pos0[0] + 2.0)) < 1e-9, f"实得 {e.position}")
        check("  **`progress` 分毫不动**（否则等于用推击抄近路漏怪）",
              e.progress == prog0, f"{prog0} → {e.progress}")
        check("  **解除了阻挡**——这条是接线时最难发现的一处",
              e.blocked_by is None and e not in op.blocking,
              f"blocked_by={e.blocked_by}，仍在 op.blocking={e in op.blocking}")

        speed = max(0.1, e.move_speed)
        steps = 0
        while e.displaced is not None and steps < 100000:
            e.advance(1 / 30, 1.0)
            steps += 1
        check("  被推开的敌人**走回了路线**（`displaced` 归位）",
              e.displaced is None, f"走了 {steps} 帧仍未归位")
        check("  归位点就是「当前进度对应的那一点」，`progress` 全程未动",
              e.progress == prog0 and
              close(e.position[0], point_at(e.route, prog0)[0], 1e-9)
              and close(e.position[1], point_at(e.route, prog0)[1], 1e-9),
              f"progress {prog0} → {e.progress}，位置 {e.position}")
        check("  走过的帧数合理（不是瞬移，也不是走不动）",
              0 < steps < 5000, f"实得 {steps} 帧")

    # ---- 4. 集成层：把一名活敌人放进射程，再走一次真正的推击 ----
    #
    # 实战里圣聆初雪那个部署位的射程**恰好罩不到敌人路径**（12 次开启、范围内
    # 敌人全是 0），所以"真的推出去了"没法靠自然战斗复现。这里改为**把他的位置
    # 挪进射程**再调同一个入口——判的是"接线通不通"，不是"这个站位好不好"。
    if live:
        e2 = live[-1] if len(live) > 1 else live[0]
        op2 = sim.operators[0]
        s1_lv = None
        for skx in SkillBook().for_operator("char_1046_sbell2"):
            lvv = skx.level(level=7, mastery=3)
            if lvv.name == "铃音吹雪":
                s1_lv = lvv
        cells = sorted(sim._range_of(op2))
        check("圣聆初雪的当前射程非空（有地方可以放敌人）", len(cells) > 0,
              f"实得 {len(cells)} 格")
        if s1_lv is not None and cells:
            op2.skill = s1_lv
            before = e2.position
            prog2 = e2.progress
            e2.displaced = None
            e2.position = (float(cells[0][0]), float(cells[0][1]))
            sim._apply_push(op2, 0.0)
            moved = (e2.position[0] != float(cells[0][0])
                     or e2.position[1] != float(cells[0][1]))
            check("**射程内的敌人真的被推离了原位**（接线通了）", moved,
                  f"{cells[0]} → {e2.position}；hp={e2.hp:g} leaked={e2.leaked} "
                  f"off_map={e2.off_map} weight={e2.weight:g} 在enemies里={e2 in sim.enemies}")
            check("  推动方向 = 部署方向（朝 Right 就是 +x）",
                  e2.position[0] > float(cells[0][0])
                  and close(e2.position[1], float(cells[0][1]), 1e-9),
                  f"实得 {e2.position}")
            check("  推离的距离 = 查表值（重量 "
                  f"{e2.weight:g} → "
                  f"{D.push_distance(1, e2.weight):.4f} 格）",
                  close(abs(e2.position[0] - float(cells[0][0])),
                        D.push_distance(1, e2.weight), 1e-9),
                  f"实得 {abs(e2.position[0] - float(cells[0][0])):.4f}")
            check("  被推的敌人 `progress` 同样没动", e2.progress == prog2,
                  f"{prog2} → {e2.progress}")
            # 清理：别把这次人造位移留给后面的断言
            e2.displaced = None
            e2.position = before

    # ---- 5. 反向：换成技2（无 force）就一次都不推 ----
    sim2 = mechanism_sim(stage, lib, skill_book=SkillBook(), verbose=True)
    u2 = make_unit(calc, "char_1046_sbell2", elite=2, level=90, trust=100)
    sim2.plan(Deployment(1.0, u2, (2, 3), "Right", skill=2, auto_skill=True,
                         talents=book_t.for_operator("char_1046_sbell2")))
    sim2.run(max_time=40.0)
    check("换成技2（没有 `force`）就一次都不推（推击没有外溢到别的技能）",
          "推击" not in "\n".join(sim2.result.log))


def check_trait_splash(stage, lib, calc, book_t) -> None:
    """[36] 撼地者特性溅射 + 天赋「汹涌怒火」的高台溅射（怒潮凛冬）。

    这条特性是**干员侧的第一条溅射**——在此之前 `battle/` 里只有敌人技能
    那条 `skill_atk_cross`（十字五格），干员的"群攻"根本没有落地。

    判据分四层，缺一层就会出现"看着做完了其实没接上"：

    1. **几何**：两种判定必须**分得开**。重叠判定（半径圆盖到哪些格）在
       半径 1.0 时是 **3×3 九格**（斜邻近角 0.707 < 1.0），半径降到 0.5 才是
       十字五格；格子判定（`x-5`）永远是十字五格。守卫特意取了圆心落在
       **格角上**那一例——那一例的结果不对称（(1,1) 在内、(-1,1) 不在），
       是"重叠"与"按格心距离"唯一能分开的指纹。
    2. **数据**：四位撼地者共用同一条特性；`damage_scale` 叠加后是 0.62；
       精 1 档没有停顿、潜能 5 起高台溅射变 27%。
    3. **接线（端到端）**：走 `Verifier.unit()`——**不是** `make_unit()`。
       后者是检查侧自己拼的，绕过 `verify` 那段接线就等于什么都没测。
    4. **行为**：真跑一次出手，量斜邻格敌人的掉血=攻击力×0.62 过防后的值，
       同时确认两格外的敌人**一点没吃到**、主目标**只吃普攻那一份**。
       高台那半单独直调 `_highland_splash`：只打地面、只打十字五格、
       附 0.5 秒停顿。
    """
    print("\n[36] 撼地者特性溅射（半径 1.0 重叠判定）+ 天赋高台溅射（十字五格）")
    from ak_tactic.battle.traits import (apply_splash_talent,  # noqa: PLC0415
                                         cross_cells, read_trait_splash,
                                         splash_tiles)
    from ak_tactic.verify import Verifier  # noqa: PLC0415

    # ---- 1. 几何：两种判定 ----
    nine = {(x, y) for x in (-1, 0, 1) for y in (-1, 0, 1)}
    check("半径 1.0 的圆盖到 **3×3 九格**（斜邻近角 √2/2≈0.707 < 1.0）",
          splash_tiles((0.0, 0.0), 1.0) == nine,
          f"实得 {len(splash_tiles((0.0, 0.0), 1.0))} 格")
    check("半径 0.5 时斜邻**掉出去**，只剩十字五格——两条半径必须分得开",
          splash_tiles((0.0, 0.0), 0.5) == {(0, 0), (1, 0), (-1, 0), (0, 1), (0, -1)},
          f"实得 {sorted(splash_tiles((0.0, 0.0), 0.5))}")
    check("半径 0.4 只剩本格",
          splash_tiles((0.0, 0.0), 0.4) == {(0, 0)},
          f"实得 {sorted(splash_tiles((0.0, 0.0), 0.4))}")
    odd = splash_tiles((0.5, -0.5), 1.0)
    check("圆心落在格角上时结果**不对称**（(1,1) 在内、(-1,1) 不在）——"
          "这是「重叠判定」与「按格心距离」唯一分得开的指纹",
          len(odd) == 12 and (1, 1) in odd and (-1, 1) not in odd,
          f"实得 {len(odd)} 格，(1,1)={'in' if (1, 1) in odd else 'out'}、"
          f"(-1,1)={'in' if (-1, 1) in odd else 'out'}")
    check("「周围四格 + 本格」（范围码 x-5）是十字五格",
          cross_cells((2, 3)) == {(2, 3), (3, 3), (1, 3), (2, 2), (2, 4)},
          f"实得 {sorted(cross_cells((2, 3)))}")

    # ---- 2. 数据 ----
    cid = "char_1051_headb2"
    hammer = ["char_1051_headb2", "char_4058_pepe",
              "char_4131_odda", "char_4185_amoris"]
    base = read_trait_splash(calc.character(cid))
    check("怒潮凛冬的特性黑板读得出溅射：半径 1.0、倍率 0.5",
          base is not None and close(base.radius, 1.0) and close(base.scale, 0.5),
          f"实得 {base}")
    # 全表核验：新判据的**命中面**必须先量一遍，否则"顺手"会波及别的干员。
    carriers = [c for c in calc.all_ids()
                if read_trait_splash(calc.character(c)) is not None]
    check("全库核验：带这条特性的**只有**撼地者四位（不误伤别人）",
          sorted(carriers) == sorted(hammer), f"实得 {carriers}")
    check("反向：能天使（速射手）与星熊（铁卫）都没有这条特性",
          read_trait_splash(calc.character("char_103_angel")) is None
          and read_trait_splash(calc.character("char_136_hsguma")) is None)

    tal = book_t.for_operator(cid, elite=2, level=60, potential=1)
    sp = apply_splash_talent(base, tal)
    check("「汹涌怒火」的 damage_scale=1.24 叠在特性 0.5 上 → **0.62**",
          sp is not None and close(sp.effective_scale, 0.62, 1e-9),
          f"实得 {sp.effective_scale if sp else None}")
    check("高台溅射是攻击力的 24%（`attack@splash_atk_scale`），带 0.5 秒停顿",
          sp is not None and close(sp.highland_scale, 0.24) 
          and close(sp.highland_sluggish, 0.5),
          f"scale={sp.highland_scale if sp else None} "
          f"sluggish={sp.highland_sluggish if sp else None}")
    sp5 = apply_splash_talent(
        base, book_t.for_operator(cid, elite=2, level=60, potential=5))
    check("潜能 5 起高台溅射变 27%（潜 4 档是 24%）",
          sp5 is not None and close(sp5.highland_scale, 0.27)
          and close(sp5.effective_scale, 0.62, 1e-9),
          f"实得 {sp5.highland_scale if sp5 else None}")
    sp1 = apply_splash_talent(
        base, book_t.for_operator(cid, elite=1, level=60, potential=1))
    check("**精 1 那一档没有停顿**（`attack@sluggish` = 0，不是「有键就算有」）",
          sp1 is not None and sp1.highland_sluggish == 0.0
          and close(sp1.highland_scale, 0.24),
          f"sluggish={sp1.highland_sluggish if sp1 else None}")

    # ---- 3. 接线：走真路径 `Verifier.unit()` ----
    v = Verifier()
    entry = {"char_id": cid, "elite": 2, "level": 60, "trust": 100,
             "potential": 1}
    op0 = v.unit(dict(entry))
    check("端到端：特性黑板真的走到了战斗单位身上"
          "（1.0 / 0.5 / 1.24 / 0.24 / 0.5 五个数一个不差）",
          close(op0.splash_radius, 1.0) and close(op0.splash_scale, 0.5)
          and close(op0.splash_damage_scale, 1.24)
          and close(op0.highland_splash_scale, 0.24)
          and close(op0.highland_splash_sluggish, 0.5),
          f"radius={op0.splash_radius} scale={op0.splash_scale} "
          f"ds={op0.splash_damage_scale} hl={op0.highland_splash_scale} "
          f"sluggish={op0.highland_splash_sluggish}")
    angel = v.unit({"char_id": "char_103_angel", "elite": 2, "level": 60,
                    "trust": 100, "potential": 1})
    check("反向：能天使的单位 `splash_radius` 是 0（整段被跳过，不是走了空逻辑）",
          angel.splash_radius == 0.0, f"实得 {angel.splash_radius}")

    # ---- 4. 行为：一次出手，量掉血 ----
    eid = _enemy_ids(stage)[0] if _enemy_ids(stage) else ""

    def _mk(sim, cell, progress=0.0):
        """造一个**站着不动**的敌人（route 只有一格，不跑 `run()`）。"""
        pts = [(float(cell[0]), float(cell[1]))]
        leg = [RouteLeg(kind="walk", points=[cell], length=0.0)]
        e = sim._build_enemy(eid, 1, pts, leg, 0.0, 0.0)
        e.position = (float(cell[0]), float(cell[1]))
        e.progress = progress
        e.max_hp = e.hp = 1_000_000.0     # 血厚到打不死，掉血量才可精确对账
        sim.enemies.append(e)
        return e

    if eid:
        sim = mechanism_sim(stage, lib)
        op = v.unit(dict(entry))
        # **先把高台那半关掉**：本节测的是特性溅射本身，让地图地形混进来
        # 会让"主目标只吃普攻"这条断言随关卡改图而漂。
        op.highland_splash_scale = 0.0
        op.position = (2, 3)
        op.direction = "Right"
        sim.operators.append(op)
        main = _mk(sim, (3, 3), progress=9.0)   # 射程内、进度最大 → 当主目标
        diag = _mk(sim, (4, 4))                 # 斜邻：在 3×3 内、**不在射程内**
        far = _mk(sim, (5, 3))                  # 两格外：在射程内，但出了半径

        for _ in range(6):                      # 攒够一次出手（1.8s / 0.5s 一帧）
            sim._operators_attack(0.5, 1.0)

        want_splash = resolve_damage(
            op.current_atk(), damage_type="PHYSICAL", scale=0.62,
            defense=diag.defense, res=diag.res).final
        got_splash = 1_000_000.0 - diag.hp
        check("斜邻格的敌人吃到特性溅射，掉血 = 攻击力 × 0.62 过防后的值",
              close(got_splash, want_splash, 1e-6),
              f"实得 {got_splash:.1f}，应为 {want_splash:.1f}")
        check("**两格外的敌人一点没吃到**（半径不是无限大）",
              far.hp == 1_000_000.0, f"实得掉血 {1_000_000.0 - far.hp:.1f}")
        want_main = resolve_damage(
            op.current_atk(), damage_type="PHYSICAL", scale=1.0,
            defense=main.defense, res=main.res).final
        check("**主目标只吃普攻那一份，不吃溅射**（正文写的是「周围的**其他**敌人」）",
              close(1_000_000.0 - main.hp, want_main, 1e-6),
              f"实得 {1_000_000.0 - main.hp:.1f}，应为 {want_main:.1f}")

        # ---- 4b. 高台那半：单独直调，两套几何分开验 ----
        hl = None
        for y in range(stage.map.height):
            for x in range(stage.map.width):
                if stage.map.tile(x, y).is_highland:
                    hl = (x, y)
                    break
            if hl:
                break
        check("1-7 地图上找得到一个高台格（本节的前提）", hl is not None,
              f"实得 {hl}")
        if hl is not None:
            around = [c for c in sorted(cross_cells(hl))
                      if stage.map.inside(*c) and c != hl]
            check("  该高台的十字五格里有图内格（挑得出受害者）", bool(around),
                  f"实得 {around}")
            victim_cell = around[0]
            far_cells = [c for c in ((hl[0] + 2, hl[1]), (hl[0] - 2, hl[1]),
                                     (hl[0], hl[1] + 2), (hl[0], hl[1] - 2))
                         if stage.map.inside(*c)]
            sim2 = mechanism_sim(stage, lib)
            op2 = v.unit(dict(entry))
            op2.position = (0, 0)
            sim2.operators.append(op2)
            victim = _mk(sim2, victim_cell)
            outside = _mk(sim2, far_cells[0]) if far_cells else None
            hits = sim2._highland_splash(op2, {hl}, op2.current_atk(), 1.0)
            check("溅射到的高台**计数 1**（技能 1/2 的 `sp_per_highland` 要靠它）",
                  hits == 1, f"实得 {hits}")
            want_hl = resolve_damage(
                op2.current_atk(), damage_type="PHYSICAL", scale=0.24,
                defense=victim.defense, res=victim.res).final
            check("  十字五格里的地面敌人吃到 攻击力 × 24%",
                  close(1_000_000.0 - victim.hp, want_hl, 1e-6),
                  f"实得 {1_000_000.0 - victim.hp:.1f}，应为 {want_hl:.1f}")
            check("  并被【停顿】0.5 秒（sluggish 计时器 = 0.5）",
                  close(victim.sluggish_timer, 0.5, 1e-9),
                  f"实得 {victim.sluggish_timer}")
            if outside is not None:
                check("  **十字之外（两格外）的敌人吃不到**",
                      outside.hp == 1_000_000.0,
                      f"实得掉血 {1_000_000.0 - outside.hp:.1f}")
            # 反向：正文限定「所有**地面**敌人」，空中单位必须不吃。
            victim.hp = 1_000_000.0
            victim.sluggish_timer = 0.0
            victim.is_flying = True
            sim2._highland_splash(op2, {hl}, op2.current_atk(), 2.0)
            check("  **反向：空中单位不吃高台溅射**（正文限定「地面敌人」）",
                  victim.hp == 1_000_000.0 and victim.sluggish_timer == 0.0,
                  f"掉血 {1_000_000.0 - victim.hp:.1f}，"
                  f"sluggish={victim.sluggish_timer}")
            # 反向：把高台溅射的倍率置 0，整段必须静默——它只该由天赋驱动。
            victim.is_flying = False
            victim.hp = 1_000_000.0
            op2.highland_splash_scale = 0.0
            off = sim2._highland_splash(op2, {hl}, op2.current_atk(), 3.0)
            check("  **反向：把高台倍率置 0 就一点不触发**（不是无条件打）",
                  off == 0 and victim.hp == 1_000_000.0,
                  f"计数 {off}，掉血 {1_000_000.0 - victim.hp:.1f}")

            # ---- 4c. 技2 的被动半条：`sp_per_highland` ----
            slots = {s.slot: s for s in SkillBook().for_operator(cid)}
            s2 = slots[2].level(7, 3)
            s1 = slots[1].level(7, 3)
            check("技2「绝不罢休」黑板里有 `sp_per_highland` = 1.0",
                  close(float(s2.blackboard.get("sp_per_highland") or 0), 1.0, 1e-9),
                  f"实得 {s2.blackboard.get('sp_per_highland')}")
            check("  正文把它写在「**被动效果**」段里（不在「自动开启」段）——"
                  "所以它是**常驻**的，不是技能期间才生效",
                  "被动效果" in (s2.description or ""),
                  f"实得 {(s2.description or '')[:20]}")
            sim3 = mechanism_sim(stage, lib)
            op3 = v.unit(dict(entry))
            op3.skill = s2
            op3.sp = 10.0
            sim3.operators.append(op3)
            sim3._highland_sp(op3, 1, 1.0)
            check("  触发 1 个高台 → 技力 +1", close(op3.sp, 11.0, 1e-9),
                  f"实得 {op3.sp}")
            sim3._highland_sp(op3, 2, 2.0)
            check("  触发 2 个高台 → 一次回 2（**逐高台计**，不是逐次出手计）",
                  close(op3.sp, 13.0, 1e-9), f"实得 {op3.sp}")
            op3.sp = 50.0
            sim3._highland_sp(op3, 9, 3.0)
            check("  封顶在 `sp_cost`（50），不溢出",
                  close(op3.sp, 50.0, 1e-9), f"实得 {op3.sp}")
            op3.sp = 10.0
            op3.skill_active = True
            sim3._highland_sp(op3, 1, 4.0)
            check("  **技能开启期间不回**——与天赋「情绪吸收」共用同一条假设"
                  "（「技能期间 SP 条不涨」，见 docs/uncertainties.md）",
                  close(op3.sp, 10.0, 1e-9), f"实得 {op3.sp}")
            op3.skill_active = False
            op3.skill = None
            sim3._highland_sp(op3, 1, 5.0)
            check("  **反向：没挂技能就不回**", close(op3.sp, 10.0, 1e-9),
                  f"实得 {op3.sp}")
            op3.skill = s1
            sim3._highland_sp(op3, 1, 6.0)
            check("  **反向：技1 的黑板里没有这个键，挂了技能也不回**"
                  "（不是「挂上技能就回」）",
                  close(op3.sp, 10.0, 1e-9), f"实得 {op3.sp}")

            # 端到端：真走一次 `_trait_splash`，确认高台触发接到了技力上。
            # **期望值按地图算，不写死**：那个落点溅到几个高台是关卡地形决定的
            # （1-7 上是 8 个，不是 1 个——第一版就栽在这个"想当然"上）。
            op3.skill = s2
            op3.sp = 10.0
            spot = (hl[0] + 1, hl[1] + 1)     # 它的 3×3 里含 hl 这个高台
            if stage.map.inside(*spot):
                n_hl = sum(1 for c in splash_tiles(spot, op3.splash_radius)
                           if stage.map.inside(*c)
                           and stage.map.tile(*c).is_highland)
                main3 = _mk(sim3, spot)
                sim3._trait_splash(op3, main3, op3.current_atk(), 7.0)
                check(f"  端到端：一次真出手把高台触发接到了技力上"
                      f"（该落点溅到 {n_hl} 个高台，逐高台各 +1）",
                      n_hl > 0 and close(op3.sp, 10.0 + n_hl, 1e-9),
                      f"实得 {op3.sp}，应为 {10.0 + n_hl}")


def check_hammer_strikes(stage, lib, calc, book_t) -> None:
    """[37] 怒潮凛冬技3「无可抵挡」：正前方一格的**五连锤击**。

    这是仓库里第一条「**技能自己打一轮**」的伤害通道。在此之前技能开启时只有
    推击那一步主动效果，伤害一律由普攻循环产生；所以本节有一条判据是
    **结构性的**：时刻表的间隔必须与攻速无关（把攻速改成 1000，排出来的时刻
    一模一样），否则这条通道迟早被人并进普攻循环去。

    其余按「数据 → 几何 → 时刻表 → 逐击对账 → 控制」五层。其中三处是本轮
    真栽过的坑，都配了反向守卫：

    * `current_atk()` 在技能**仍开着的那一帧**已经含了 `atk_base` 与
      `atk_scale`，拿它再乘一遍会把第一锤算成 4.8 倍（实测 27,510 而非 5,731）；
    * 半径 1.5 时正交两格地块的最近点距离**正好** 1.5，判据必须取**闭圆**，
      否则 1.5 与 1.0 盖出同一片 3×3，「溅射范围更大」就是空话；
    * 【束缚】与【晕眩】【停顿】各是一个字段：正向对照要拿**真敌人开火**来证
      （只有"不动"不能证明它不是晕眩——晕眩也不动）。
    """
    print("\n[37] 技3「无可抵挡」：五连锤击（不吃攻速、逐击累加、1.5 溅射、2 秒束缚）")
    import sqlite3  # noqa: PLC0415

    from ak_tactic.battle.hammer import (HAMMER_HITS, HAMMER_INTERVAL,  # noqa: PLC0415
                                         HAMMER_SPLASH_RADIUS, read_hammer)
    from ak_tactic.battle.traits import cross_cells, splash_tiles  # noqa: PLC0415
    from ak_tactic.verify import Verifier  # noqa: PLC0415

    cid = "char_1051_headb2"
    slots = {s.slot: s for s in SkillBook().for_operator(cid)}
    s3 = slots[3].level(7, 3)
    s1 = slots[1].level(7, 3)
    s2 = slots[2].level(7, 3)

    # ---- 1. 数据 ----
    st = read_hammer(s3.blackboard)
    check("read_hammer 认得技3 的黑板（三个判据键同时在）", st is not None,
          f"实得 {st}")
    if st is not None:
        check("  atk_base = 1.0（技能期间攻击力 +100%）",
              close(st.atk_pct, 1.0, 1e-9), f"实得 {st.atk_pct}")
        check("  atk_scale = 2.4（每击 240% 攻击力物理）",
              close(st.atk_scale, 2.4, 1e-9), f"实得 {st.atk_scale}")
        check("  atk_step = 0.3（每击之后额外 +30%）",
              close(st.atk_step, 0.3, 1e-9), f"实得 {st.atk_step}")
        check("  splash_atk_scale_bonus = 3.5（高台溅射伤害倍数）",
              close(st.highland_bonus, 3.5, 1e-9), f"实得 {st.highland_bonus}")
        check("  unmovable = 2.0（控制效果变 2 秒束缚）",
              close(st.root, 2.0, 1e-9), f"实得 {st.root}")
        check("  第 5 击的倍率是 **3.2**（各击加成**相加**；"
              "若误当逐次相乘 1.3×…×1.3 会算成 5.71）",
              close(st.atk_multiplier(4), 3.2, 1e-9),
              f"实得 {st.atk_multiplier(4)}")
        check("  一轮等效总倍率（对裸攻击力）= 31.2",
              close(st.total_multiplier(), 31.2, 1e-9),
              f"实得 {st.total_multiplier()}")
        check("  次数与间隔写死为 5 / 1.8s（备注明写不吃攻速）",
              st.hits == HAMMER_HITS and close(st.interval, HAMMER_INTERVAL, 1e-9),
              f"实得 {st.hits} 击 / {st.interval}s")
    check("反向：技1 的黑板不是这条技能", read_hammer(s1.blackboard) is None)
    check("反向：技2 的黑板也不是（虽然有 atk/def，但没有 atk_step）",
          read_hammer(s2.blackboard) is None)

    db = Path(__file__).resolve().parent.parent / "data" / "akdb.sqlite"
    with sqlite3.connect(db) as conn:
        rows = conn.execute(
            "SELECT DISTINCT skill_id, name FROM skill_level WHERE level = 10 "
            "AND blackboard LIKE '%atk_step%' "
            "AND blackboard LIKE '%splash_atk_scale_bonus%'").fetchall()
    check("全库核验：三个判据键同时在场的技能**只有**怒潮凛冬技3「无可抵挡」"
          "（不是「带 atk_step 的都算」）",
          len(rows) == 1 and rows[0][1] == "无可抵挡", f"实得 {rows}")

    # ---- 2. 几何：1.5 与 1.0 必须分辨得出 ----
    r10 = splash_tiles((0.0, 0.0), 1.0)
    r15 = splash_tiles((0.0, 0.0), HAMMER_SPLASH_RADIUS)
    check("1.5 的闭圆 = 3×3 加四条正交臂，共 **13 格**", len(r15) == 13,
          f"实得 {len(r15)}")
    check("  多出来的正是**正交两格**那四个，且严格包含 1.0 的九格"
          "（正交两格最近点距离恰好 1.5 ⇒ 判据必须是闭圆，"
          "否则「溅射范围更大」是空话）",
          r10 < r15 and (r15 - r10) == {(2, 0), (-2, 0), (0, 2), (0, -2)},
          f"实得多出 {sorted(r15 - r10)}")

    # ---- 3. 时刻表：五击、1.8s、不吃攻速 ----
    v = Verifier()
    entry = {"char_id": cid, "elite": 2, "level": 60, "trust": 100,
             "potential": 1}

    def fresh(speed=None, skill=None):
        op = v.unit(dict(entry))
        op.skill = skill if skill is not None else s3
        op.position = (2, 3)
        op.direction = "Right"
        if speed is not None:
            op.attack_speed = speed
        return op

    sim = mechanism_sim(stage, lib)
    op = fresh()
    sim.operators.append(op)
    sim._schedule_hammer(op, 0.0)
    check("开启技能后排下 **5 击**", len(op.hammer_pending) == HAMMER_HITS,
          f"实得 {len(op.hammer_pending)}")
    check("  首击即刻、此后每 1.8s 一击",
          all(close(op.hammer_pending[i] - op.hammer_pending[i - 1],
                    HAMMER_INTERVAL, 1e-9) for i in range(1, HAMMER_HITS)),
          f"实得 {[round(x, 3) for x in op.hammer_pending]}")
    fast = fresh(speed=1000.0)
    sim.operators.append(fast)
    sim._schedule_hammer(fast, 0.0)
    check("  **不吃攻速**：攻速 1000 排出来的时刻表与攻速 100 一字不差"
          "（结构上就不该挂在普攻循环里）",
          fast.hammer_pending == op.hammer_pending,
          f"实得 {[round(x, 3) for x in fast.hammer_pending]}")
    slow = fresh(skill=s1)
    sim.operators.append(slow)
    sim._schedule_hammer(slow, 0.0)
    check("  反向：挂技1 排不出时刻表（不是「开技能就锤地」）",
          slow.hammer is None and not slow.hammer_pending)

    # ---- 4. 行为：逐击对账 ----
    eid = _enemy_ids(stage)[0]
    sim2 = mechanism_sim(stage, lib)
    op2 = fresh()
    sim2.operators.append(op2)

    def mk(s, cell, progress=0.0):
        return _dummy(s, stage, eid, cell, progress=progress)

    front = mk(sim2, (3, 3), progress=5.0)   # 正前方一格 → 主目标
    near = mk(sim2, (4, 3))                  # 正交一格 → 溅射
    far = mk(sim2, (5, 3))                   # 正交两格 → **只有 1.5 才够得着**
    sim2._schedule_hammer(op2, 0.0)
    dealt: list[float] = []
    orig_strike = sim2._hammer_strike

    def strike_spy(o, t):
        before = front.hp
        orig_strike(o, t)
        dealt.append(before - front.hp)

    sim2._hammer_strike = strike_spy
    for i in range(HAMMER_HITS):
        sim2._hammer_tick(i * HAMMER_INTERVAL)

    check("手工驱动 5 个到点时刻 → 落了 5 击", len(dealt) == HAMMER_HITS,
          f"实得 {len(dealt)}")
    base = op2.atk * (1.0 + op2.aura_atk_pct)
    want = [resolve_damage(base * (1.0 + st.atk_pct + st.atk_step * i),
                           damage_type="PHYSICAL", scale=st.atk_scale,
                           defense=front.defense, res=front.res).final
            for i in range(HAMMER_HITS)]
    check("五击逐一对账（每击 = 裸攻击力 ×(1+1.0+0.3i) ×240% 过防）",
          all(close(a, b, 1e-6) for a, b in zip(dealt, want)),
          f"实得 {[round(x, 1) for x in dealt]}，应为 {[round(x, 1) for x in want]}")
    check("  **逐击递增**：第 5 击 > 第 1 击（累加 +30%/击）",
          dealt[-1] > dealt[0] * 1.5,
          f"{dealt[0]:,.1f} → {dealt[-1]:,.1f}")
    want_near = sum(resolve_damage(base * (1.0 + st.atk_pct + st.atk_step * i),
                                   damage_type="PHYSICAL", scale=0.62,
                                   defense=near.defense, res=near.res).final
                    for i in range(HAMMER_HITS))
    check("正交一格的敌人吃到**特性溅射** 62%（五击各一次；每击的溅射按**那一击**"
          "的攻击力算，所以逐击也递增）",
          close(1_000_000.0 - near.hp, want_near, 1e-6),
          f"实得 {1_000_000.0 - near.hp:,.1f}，应为 {want_near:,.1f}")
    check("**正交两格的敌人也吃到了**——这一条就是 1.5 与 1.0 的分水岭",
          1_000_000.0 - far.hp > 0.0, f"实得掉血 {1_000_000.0 - far.hp:,.1f}")
    # 反向：同样的布置走**普通攻击**（特性半径 1.0），正交两格就该一点吃不到。
    # 注意不能拿 `op.splash_radius` 去改锤击的半径——技3 的半径是技能自己的
    # 1.5（写在 `HammerStrike` 里），改干员字段根本改不动它。
    sim3 = mechanism_sim(stage, lib)
    op3 = fresh()
    sim3.operators.append(op3)
    far2 = mk(sim3, (5, 3))
    near2 = mk(sim3, (4, 3))
    main3 = mk(sim3, (3, 3), progress=5.0)
    sim3._trait_splash(op3, main3, base, 0.0)
    check("  反向：同一张图、同样的落点，走**特性溅射（半径 1.0）**时"
          "正交两格一点吃不到、正交一格照吃"
          "（证明上一跳真的是 1.5 带来的）",
          far2.hp == 1_000_000.0 and near2.hp < 1_000_000.0,
          f"两格外掉血 {1_000_000.0 - far2.hp:,.1f}，"
          f"一格掉血 {1_000_000.0 - near2.hp:,.1f}")

    # ---- 5. 高台那一半：×3.5 与 2 秒【束缚】 ----
    hl = None
    for y in range(stage.map.height):
        for x in range(stage.map.width):
            if stage.map.tile(x, y).is_highland:
                hl = (x, y)
                break
        if hl:
            break
    if hl is not None:
        # 5a. 单位层：bonus 乘在倍率上、root 替换停顿
        around = [c for c in sorted(cross_cells(hl))
                  if stage.map.inside(*c) and c != hl]
        sim4 = mechanism_sim(stage, lib)
        op4 = fresh()
        sim4.operators.append(op4)
        victim = mk(sim4, around[0])
        hits = sim4._highland_splash(op4, {hl}, op4.atk, 1.0,
                                     bonus=st.highland_bonus, root=st.root)
        want_hl = resolve_damage(op4.atk, damage_type="PHYSICAL",
                                 scale=0.24 * st.highland_bonus,
                                 defense=victim.defense, res=victim.res).final
        check("技3 期间高台溅射 = 24% × 3.5 = **84%**",
              close(1_000_000.0 - victim.hp, want_hl, 1e-6),
              f"实得 {1_000_000.0 - victim.hp:,.1f}，应为 {want_hl:,.1f}")
        check("  控制效果**替换**为 2 秒【束缚】（不是叠加，也不是停顿）",
              close(victim.root_timer, 2.0, 1e-9)
              and victim.sluggish_timer == 0.0,
              f"root={victim.root_timer} sluggish={victim.sluggish_timer}")
        check("  触发计数照样返回（`sp_per_highland` 仍要靠它）", hits == 1,
              f"实得 {hits}")

        # 5b. 接线层：锤击真的把 bonus / root 传下去了
        sim5 = mechanism_sim(stage, lib)
        op5 = fresh()
        op5.position = (hl[0], hl[1] + 3)
        op5.direction = "Up"
        sim5.operators.append(op5)
        seen: dict = {}
        orig_hl = sim5._highland_splash

        def hl_spy(o, cells, power, t, **kw):
            seen.update(kw)
            return orig_hl(o, cells, power, t, **kw)

        sim5._highland_splash = hl_spy
        sim5._schedule_hammer(op5, 0.0)
        sim5._hammer_tick(0.0)
        check("锤击把 `bonus=3.5` 与 `root=2.0` 传给了高台那一半"
              "（不是只在单位层对得上）",
              seen.get("bonus") == st.highland_bonus
              and seen.get("root") == st.root,
              f"实得 {seen}")

    # ---- 6. 【束缚】= 不能移动、**但仍能开火** ----
    sim6 = mechanism_sim(stage, lib)
    op6 = fresh()
    op6.position = (2, 3)
    sim6.operators.append(op6)
    # 1-7 里唯一的远程是鸡尾酒投掷者（射程 1.75）：近战要先被阻挡才出手，
    # 拿近战写这条对照会得到"本来就不打"，把机制问题伪装成布置问题。
    pts = [(3.0, 3.0)]
    shooter = sim6._build_enemy("enemy_1028_mocock", 1, pts,
                                [RouteLeg(kind="walk", points=pts, length=0.0)],
                                0.0, 0.0)
    shooter.position = (3.0, 3.0)
    shooter.max_hp = shooter.hp = 1_000_000.0
    sim6.enemies.append(shooter)
    pos0 = shooter.position
    shooter.root_timer = 5.0
    shooter.advance(1.0, 1.0)
    check("【束缚】期间**不动**（与停顿一样拦移动）",
          shooter.position == pos0, f"实得 {shooter.position}")
    check("  而且**没有被缴械**（`disarm_timer` 仍是 0）——这一条把它与晕眩分开",
          shooter.disarm_timer == 0.0, f"实得 {shooter.disarm_timer}")
    hp0 = op6.hp
    for k in range(6):
        sim6._enemies_attack(1.0, float(k))
    hit_rooted = hp0 - op6.hp
    check("  **正向对照：束缚期间敌人照样开火**（干员真掉血）——"
          "光「不动」证明不了它不是晕眩，晕眩也不动",
          hit_rooted > 0.0, f"实得掉血 {hit_rooted:,.1f}")
    shooter.root_timer = 0.0
    shooter.stun_timer = 5.0
    hp1 = op6.hp
    for k in range(6):
        sim6._enemies_attack(1.0, float(k))
    check("  反向：换成【晕眩】就一枪不开（同一只敌人、同一段代码路径）",
          op6.hp == hp1, f"实得掉血 {hp1 - op6.hp:,.1f}")


def check_batch3_sample(stage, lib, calc, book_t) -> None:
    """[38] 本批「零欠账」两位的**实战核验**（能天使 × 星熊）。

    审计的两道筛子只回答"这个键有没有人读"，**不回答"读出来的数有没有真的
    改变战场"**——所以零欠账不等于已收口。本节按这个原则取数：每条都测该机制
    **真正改变的那个可观测量**，而不是"某个函数被调用过"。

    * 能天使的身份是**攻速 + 连发**：常驻 +12 攻速折算出的出手间隔、一次出手
      打几笔、技能把间隔改掉多少；反向用潜能档位（+12 与 +15 是两档）与
      "别的技能的连发数不要串门"。
    * 星熊的身份是**常态减伤 + 阻挡**：天赋 25% 抵挡在**真受击**里是不是正好
      0.75、被动技的 +30% 防御是不是不攒技力就常驻、阻挡是不是恰好 3 只。

    ⚠️ 逐笔伤害的期望值**从正文与面板写起**（"攻击力 595 × 145%"），
    **不从 `current_atk()` 反推**：后者曾经自带 `atk_scale`，若哪天有人把
    "倍率乘两次"改回来，用 `current_atk()` 写期望值的断言会跟着一起错、
    照样通过。2026-09-18 的口径裁定（倍率只在 `resolve_damage(scale=…)` 乘一次）
    就是为了这件事，见 `docs/uncertainties.md` §二十一。
    """
    print("\n[38] 零欠账样板：能天使（攻速/连发）× 星熊（抵挡/阻挡）")
    from ak_tactic.battle.talents import find_damage_block  # noqa: PLC0415
    from ak_tactic.verify import Verifier  # noqa: PLC0415

    v = Verifier()
    eid = _enemy_ids(stage)[0]

    def build(cid, potential=1, skill=None):
        op = v.unit({"char_id": cid, "elite": 2, "level": 60,
                     "trust": 100, "potential": potential})
        op.skill = skill
        op.position = (2, 3)
        op.direction = "Right"
        return op

    # ---- 能天使：天赋「快速弹匣」是**常驻**攻速 ----
    a = build("char_103_angel")
    check("能天使 精2 潜1 的常驻攻速 = 100 + 12（天赋「快速弹匣」）",
          close(a.attack_speed, 112.0, 1e-9), f"实得 {a.attack_speed}")
    check("  出手间隔 = 1.0 × 100/112（攻速对**平A**同样折算，不是只在开技能时折）",
          close(a.current_interval(), 100.0 / 112.0, 1e-9),
          f"实得 {a.current_interval():.4f}s")
    a3 = build("char_103_angel", potential=3)
    check("  反向：潜能 3 档才是 +15 那一档（天赋候选按 required_potential_rank 分）",
          close(a3.attack_speed, 115.0, 1e-9), f"实得 {a3.attack_speed}")

    # ---- 连发：一次出手打几笔（技1/2/3 = 3/4/5）----
    slots = {s.slot: s for s in SkillBook().for_operator("char_103_angel")}

    def fire(skill):
        s = mechanism_sim(stage, lib)
        op = build("char_103_angel", skill=skill)
        s.operators.append(op)
        target = _dummy(s, stage, eid, (3, 3))
        s._activate(op, 0.0)
        seen: list[float] = []
        orig = s._damage_enemy

        def spy(*args, **kw):
            seen.append(args[1])
            return orig(*args, **kw)

        s._damage_enemy = spy
        interval = op.current_interval()
        s._operators_attack(interval + 1e-6, 0.0)
        return op, seen, interval, target

    op1, hits1, iv1, tgt1 = fire(slots[1].level(7, 3))
    _op2, hits2, _iv2, _t2 = fire(slots[2].level(7, 3))
    _op3, hits3, iv3, _t3 = fire(slots[3].level(7, 3))
    # 正文口径：技1 是「攻击力 145%」，**只乘一次**。期望值由面板与正文算出，
    # 不经 `current_atk()`——正则见本节 docstring 的告示。
    want1 = op1.atk * 1.45 - tgt1.defense
    check("技1 每笔伤害 = 面板 595 × 145% − 防御（倍率**只乘一次**）",
          len(hits1) == 3 and all(close(h, want1, 1e-6) for h in hits1),
          f"实得 {[round(h, 1) for h in hits1]}，应为 {want1:,.1f}"
          f"（靶子防御 {tgt1.defense:g}）")
    check("技1「冲锋模式」一次出手 **3 笔**（黑板 times=3）", len(hits1) == 3,
          f"实得 {len(hits1)} 笔")
    check("技2「扫射模式」**4 笔**、技3「过载模式」**5 笔**"
          "（各技能的连发数不串门）",
          len(hits2) == 4 and len(hits3) == 5,
          f"实得 {len(hits2)} / {len(hits3)} 笔")
    check("  同一个技能的连发**每笔一样大**（连发是同倍率重复，不是递减）",
          len({round(h, 6) for h in hits3}) == 1,
          f"实得 {[round(h, 1) for h in hits3]}")
    check("技3 的间隔被 `base_attack_time = -0.11` 缩短：(1.0 − 0.11) × 100/112",
          close(iv3, (1.0 - 0.11) * 100.0 / 112.0, 1e-9), f"实得 {iv3:.4f}s")
    check("  反向：技1 的间隔仍是 1.0 × 100/112（缩短只属于技3）",
          close(iv1, 100.0 / 112.0, 1e-9), f"实得 {iv1:.4f}s")

    # ---- 星熊：天赋「战术装甲」= 常驻伤害抵挡 ----
    def hsguma(skill=None):
        return build("char_136_hsguma", skill=skill)

    tal = book_t.for_operator("char_136_hsguma", elite=2, level=60, potential=1)
    blk = find_damage_block(tal)
    check("「战术装甲」精2 潜1 读数是 25%",
          blk is not None and close(blk.value("prob"), 0.25, 1e-9),
          f"实得 {blk.value('prob') if blk else None}")
    blk3 = find_damage_block(book_t.for_operator("char_136_hsguma", elite=2,
                                                 level=60, potential=3))
    check("  反向：潜能 3 档是 28%（第一天赋效果增强）",
          blk3 is not None and close(blk3.value("prob"), 0.28, 1e-9),
          f"实得 {blk3.value('prob') if blk3 else None}")

    def soak(dodge_on: bool) -> tuple[float, float]:
        """让同一只远程敌人打同一位星熊六下。

        两次布置**只翻转"抵挡"这一个字段**（天赋本身照给，位置、练度、敌人
        全同），否则测出来的差值里混着"少了 6% 防御光环"那一份。
        """
        s = mechanism_sim(stage, lib)
        op = hsguma()
        s.operators.append(op)
        s._do_deploy(Deployment(0.0, op, (2, 3), "Right", talents=tal), 0.0)
        if not dodge_on:
            op.talent_dodge_phys = 0.0
            op.talent_dodge_arts = 0.0
        _dummy(s, stage, "enemy_1028_mocock", (3, 3))
        hp0 = op.hp
        for k in range(6):
            s._enemies_attack(1.0, float(k))
        return hp0 - op.hp, op.talent_dodge_phys

    with_tal, field_with = soak(True)
    no_tal, field_without = soak(False)
    check("抵挡落在**独立字段**上（不是技能的闪避字段，开一关技能也不会清）",
          close(field_with, 0.25, 1e-9) and close(field_without, 0.0, 1e-12),
          f"带天赋 {field_with}，置 0 后 {field_without}")
    check("**实战**：带上 25% 抵挡后同一次受击的掉血 = 不带时的 75%",
          no_tal > 0.0 and close(with_tal, no_tal * 0.75, 1e-6),
          f"带 {with_tal:,.2f} vs 不带 {no_tal:,.2f}")

    # ---- 被动技「荆棘」：不攒技力、永不关闭 ----
    hsg = {s.slot: s for s in SkillBook().for_operator("char_136_hsguma")}
    sim2 = mechanism_sim(stage, lib)
    thorn = hsguma(skill=hsg[2].level(7, 3))
    sim2.operators.append(thorn)
    base_def = thorn.defense
    sim2._skill_tick(0.5, 0.5)
    check("技2「荆棘」是**被动**：部署后不用攒技力就已经生效",
          thorn.skill_active and thorn.effects is not None,
          f"skill_active={thorn.skill_active}")
    want_def = base_def * (1.0 + 0.30 + thorn.aura_def_pct)
    check("  防御 = 面板 × (1 + 0.30 + 职业光环)",
          close(thorn.current_defense(), want_def, 1e-6),
          f"实得 {thorn.current_defense():.1f}，应为 {want_def:.1f}"
          f"（光环 {thorn.aura_def_pct}）")
    for k in range(120):
        sim2._skill_tick(0.5, 0.5 + 0.5 * k)
    check("  60 秒后仍然开着（被动永不关闭），且技力始终 0（不耗技力）",
          thorn.skill_active and thorn.sp == 0.0,
          f"开={thorn.skill_active} sp={thorn.sp}")

    # ---- 技3「力之锯」：攻击 +140% / 防御 +90% ----
    sim3 = mechanism_sim(stage, lib)
    force = hsguma(skill=hsg[3].level(7, 3))
    sim3.operators.append(force)
    d0, a0 = force.defense, force.atk
    sim3._activate(force, 0.0)
    check("技3「力之锯」开启后攻击力 ×2.40（1 + 1.40）",
          close(force.current_atk(), a0 * 2.40, 1e-6),
          f"实得 {force.current_atk():.1f}，应为 {a0 * 2.40:.1f}")
    want_d = d0 * (1.0 + 0.90 + force.aura_def_pct)
    check("  防御 ×1.90（1 + 0.90）",
          close(force.current_defense(), want_d, 1e-6),
          f"实得 {force.current_defense():.1f}，应为 {want_d:.1f}")

    # ---- 阻挡 3（特性「能够阻挡三个敌人」）----
    sim4 = mechanism_sim(stage, lib)
    wall = hsguma()
    sim4.operators.append(wall)
    sim4._do_deploy(Deployment(0.0, wall, (2, 3), "Right", talents=tal), 0.0)
    foes = [_dummy(sim4, stage, eid, (2, 3)) for _ in range(4)]
    sim4._update_blocking()
    held = [f for f in foes if f.blocked_by is wall]
    check("特性「能够阻挡三个敌人」：四只挤在同一格时**恰好挡住 3 只**"
          f"（block_cnt={wall.block_cnt}）", len(held) == 3, f"实得 {len(held)} 只")
    check("  反向：剩下那一只**挡不住**（不是无限挡）",
          len(foes) - len(held) == 1, f"实得没挡住 {len(foes) - len(held)} 只")

    # ---- 补的「真实伤害」判据要真的改到**结算**上 ----
    # 只断言一个布尔字段是不够的：真正要证明的是这一击不再吃防御与法抗。
    # 靶子给防御 5000（高过她的面板，物理口径只剩 5% 保底）与法抗 100（法术口径归零），
    # 满额命中才算数。
    kalts_slots = {s.slot: s for s in SkillBook().for_operator("char_1052_kalts2")}
    sim5 = mechanism_sim(stage, lib)
    kalts = build("char_1052_kalts2", skill=kalts_slots[2].level(7, 3))
    sim5.operators.append(kalts)
    tough = _dummy(sim5, stage, eid, (3, 3))
    tough.defense = 5000.0
    tough.res = 100.0
    sim5._activate(kalts, 0.0)
    hits5: list[float] = []
    orig5 = sim5._damage_enemy

    def spy5(*args, **kw):
        hits5.append(args[1])
        return orig5(*args, **kw)

    sim5._damage_enemy = spy5
    sim5._operators_attack(kalts.current_interval() + 1e-6, 0.0)
    want5 = kalts.atk * (1.0 + 1.5) * 3.8
    check("凯尔希·思衡托技2 打防御 5000 / 法抗 100 的靶子**仍是满额**"
          "（真实伤害不吃防御与法抗）",
          len(hits5) == 1 and close(hits5[0], want5, 1e-6),
          f"实得 {[round(h, 1) for h in hits5]}，应为 {want5:,.1f}")
    check("  反向：同一靶子若按物理口径只该剩 5% 保底"
          "（说明上面那条不是怎么打都过的）",
          close(resolve_damage(want5, damage_type=DamageType.PHYSICAL,
                               defense=5000.0).final, want5 * 0.05, 1e-6),
          f"物理口径 {resolve_damage(want5, damage_type=DamageType.PHYSICAL, defense=5000.0).final:,.1f}")


def check_orchd2(stage, lib, calc, book_t) -> None:
    """[39] 焰狐龙梓兰（第三批③）：箭数、落地点射、概率晕眩。

    她此前**整块技2 黑板五个键一个都没解析**（全落进 `other`，模型里退化成
    一发 100% 的普攻），所以这一节按"该机制真正改变的那个可观测量"取数，
    而不是"某个函数被调用过"：

    * 技2「飞翔瞪射」= 三轮齐射 3/4/5 支（共 12 支，每支 180%）＋**落地点射
      300%**。可观测量：一次出手的**笔数与逐笔伤害**（13 笔，前 12 笔
      `面板 × 1.8`、第 13 笔 `面板 × 3.0`）。
    * 技1「刚射」= 4 支；每支 20% 概率晕眩 2 秒。可观测量：靶子的
      `stun_timer` = 4 × 0.2 × 2.0 = 1.6 秒（走**期望占比**，与提丰技2 同一条）。

    ⚠️ 期望值从**正文与面板**写起，不从 `current_atk()` 反推（口径裁定的
    教训，见 `docs/uncertainties.md` §二十一）。

    ⚠️ 反向守卫：`stun_prob` 与提丰的 `attack@prob` **不能混成一个键名**——
    `prob` 在同批干员里同名反义（赤刃技2 的 `prob` 是闪避率），所以两条路
    各测一次，改错了会有一边红。
    """
    print("\n[39] 焰狐龙梓兰：箭数 / 落地点射 / 概率晕眩")
    from ak_tactic.operator import SkillBook  # noqa: PLC0415
    from ak_tactic.verify import Verifier  # noqa: PLC0415

    v = Verifier()
    eid = _enemy_ids(stage)[0]
    slots = {s.slot: s for s in SkillBook().for_operator("char_1048_orchd2")}
    s1 = slots[1].level(7, 3)
    s2 = slots[2].level(7, 3)

    check("技2 三连射的倍率 180% 落进 atk_scale（`attack@atk_scale_loop`）",
          close(s2.effects.atk_scale, 1.8, 1e-9), f"实得 {s2.effects.atk_scale}")
    check("技2 每轮箭数 = (3, 4, 5)（正文「射击3次，分别射出3、4、5支」）",
          s2.effects.volley_arrows == (3, 4, 5), str(s2.effects.volley_arrows))
    check("技2 一次出手 = 12 支 ＋ 落地点射 1 击 = 13 笔",
          s2.effects.hit_count == 13, f"实得 {s2.effects.hit_count}")
    check("技2 落地点射 = 300%（`attack@atk_scale_end`）",
          close(s2.effects.landing_scale or 0.0, 3.0, 1e-9),
          f"实得 {s2.effects.landing_scale}")
    check("技2 起飞/降落参数落成显式字段（0.4 / 0.2 / 0.2，**不进结算**）",
          close(s2.effects.airborne_height or 0.0, 0.4, 1e-9)
          and close(s2.effects.airborne_rise or 0.0, 0.2, 1e-9)
          and close(s2.effects.airborne_fall or 0.0, 0.2, 1e-9),
          f"{s2.effects.airborne_height}/{s2.effects.airborne_rise}"
          f"/{s2.effects.airborne_fall}")
    check("技2 黑板不再有键落进 other（此前是 5 个）",
          not s2.effects.other, str(s2.effects.other))
    check("技1 每轮箭数 = (4,)（正文「发射4支」），一次出手 4 笔",
          s1.effects.volley_arrows == (4,) and s1.effects.hit_count == 4,
          f"{s1.effects.volley_arrows} / {s1.effects.hit_count}")

    # 全表命中面：这两条措辞**只该命中她这两个技能**。只测标本不测面是
    # 「真实伤害」那条判据的老坑（2026-09-16 一次误判 28 条），所以扫全表。
    import sqlite3  # noqa: PLC0415
    from pathlib import Path  # noqa: PLC0415

    from ak_tactic.operator.skill import _ARROW_SHOT, _ARROW_VOLLEYS  # noqa: PLC0415
    with sqlite3.connect(Path(__file__).resolve().parent.parent
                         / "data" / "akdb.sqlite") as con:
        rows = con.execute(
            "SELECT skill_id, description FROM skill_level WHERE level=10"
        ).fetchall()
    volley_hits = [sid for sid, d in rows if _ARROW_VOLLEYS.search(d or "")]
    shot_hits = [sid for sid, d in rows if _ARROW_SHOT.search(d or "")]
    check("  箭数判据的全表命中面：三轮齐射只命中技2、单轮只命中技1",
          volley_hits == ["skchr_orchd2_2"] and shot_hits == ["skchr_orchd2_1"],
          f"{volley_hits} / {shot_hits}")

    def fire(cid: str, slot, *, cell=(3, 3)):
        """让这位干员开一次技能并出手一下，返回 (干员, 逐笔伤害, 靶子)。"""
        s = mechanism_sim(stage, lib)
        op = v.unit({"char_id": cid, "elite": 2, "level": 60,
                     "trust": 100, "potential": 1})
        op.skill = slot
        op.position = (2, 3)
        op.direction = "Right"
        s.operators.append(op)
        target = _dummy(s, stage, eid, cell)
        s._activate(op, 0.0)
        seen: list[float] = []
        orig = s._damage_enemy

        def spy(*args, **kw):
            seen.append(args[1])
            return orig(*args, **kw)

        s._damage_enemy = spy
        s._operators_attack(op.current_interval() + 1e-6, 0.0)
        return op, seen, target

    op2, hits2, tgt2 = fire("char_1048_orchd2", s2)
    want_loop = op2.atk * 1.8 - tgt2.defense
    want_land = op2.atk * 3.0 - tgt2.defense
    check("技2 一次出手打 13 笔，前 12 笔 = 面板 × 180% − 防御",
          len(hits2) == 13 and all(close(h, want_loop, 1e-6) for h in hits2[:12]),
          f"实得 {len(hits2)} 笔，前三笔 {[round(h, 1) for h in hits2[:3]]}，"
          f"应为 {want_loop:,.1f}")
    check("技2 第 13 笔是落地点射 = 面板 × 300% − 防御",
          bool(hits2) and close(hits2[-1], want_land, 1e-6),
          f"实得 {hits2[-1] if hits2 else None}，应为 {want_land:,.1f}")

    op1, hits1, tgt1 = fire("char_1048_orchd2", s1)
    check("技1 一次出手 4 笔（4 支箭各算一次独立命中）",
          len(hits1) == 4, f"实得 {len(hits1)} 笔")
    check("技1 每支 20% 概率晕眩 2 秒 → 靶子晕眩计时 = 4 × 0.2 × 2.0 = 1.6s",
          close(tgt1.stun_timer, 1.6, 1e-6), f"实得 {tgt1.stun_timer:.3f}s")

    # 反向：提丰技2 走的是 `attack@prob` + `attack@stun`（0.4 × 1.0 = 0.4/笔），
    # 与上面那条**同名反义的另一半**。改错键名时总有一边红。
    t_slots = {s.slot: s for s in SkillBook().for_operator("char_2012_typhon")}
    _op3, hits3, tgt3 = fire("char_2012_typhon", t_slots[2].level(7, 3))
    check("反向：提丰技2 的 `attack@prob` 通道没被改坏（0.4 × 1.0 = 0.4/笔）",
          len(hits3) == 1 and close(tgt3.stun_timer, 0.4, 1e-6),
          f"{len(hits3)} 笔，晕眩 {tgt3.stun_timer:.3f}s")


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
    check_redeploy(stage, lib, calc)
    check_blessing(stage, lib, calc, book_t)
    check_charges(stage, lib, calc)
    check_displace(stage, lib, calc)
    check_random_audit()
    check_stun(stage, lib, calc, book_t)
    check_element_gaps(stage, lib, calc, book_t)
    check_skill_infix(stage, lib, calc, book_t)
    check_barrier_scope(stage, lib, calc, book_t)
    check_faction_aura(stage, lib, calc, book_t)
    check_class_aura(stage, lib, calc, book_t)
    check_damage_block(stage, lib, calc, book_t)
    check_dot_on_hit(stage, lib, calc, book_t)
    check_high_ground_aspd(stage, lib, calc, book_t)
    check_angel_blessing(stage, lib, calc, book_t)
    check_limit_dispatch(stage, lib, calc, book_t)
    check_second_use(stage, lib, calc, book_t)
    check_push(stage, lib, calc, book_t)
    check_trait_splash(stage, lib, calc, book_t)
    check_hammer_strikes(stage, lib, calc, book_t)
    check_batch3_sample(stage, lib, calc, book_t)
    check_orchd2(stage, lib, calc, book_t)

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
