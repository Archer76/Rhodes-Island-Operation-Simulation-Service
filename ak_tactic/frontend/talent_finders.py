# -*- coding: utf-8 -*-
"""天赋的**认法**——`find_*` 与它们的判据、指纹常量。

⚠ **本文件由 `tools/gen_talent_finders.py` 从 `battle/talents.py` 按行区间机械搬出，
不要手改。** 改口径请改原件再重跑，这样两边永远取的是同一段源码。

## 为什么单独一份

`build_spec` 只需要"这位干员身上有没有这条天赋"，不需要任何跑帧逻辑。
实测这块闭包是 **13 个函数、46 行，全部无 `self`、无引擎态**，
而 `battle/talents.py` 有 1126 行——规格只碰其中很小的一片。

`battle/talents.py` 仍然从**这里** re-export 同一批名字，所以引擎那边一行不用改，
一份实现、两个消费者。

## ⚠ 注释是搬过来的，别删

每一条 `is_*` 上面那一大段写着**为什么这样认**（例如「青色怒火」为什么只能按
天赋名认、不能按黑板键名认——它和技能自己的增益**完全同名**）。
重打代码很容易，重打论证不容易；这段文字是判据的一半。
"""
from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "AMMO_COVENANT_NAME", "ANGEL_BLESSING_TALENTS", "BLESSING_KEYS",
    "CLASS_AURA_TALENTS", "FACTION_AURA_NAME", "LATERANO_NATION",
    "LIMIT_DISPATCH_TALENTS", "MEDIC_MONUMENT_NAME", "REGEN_KEYS",
    "RHODES_NATION", "SNOW_KEYS", "STUDENT_TEAM", "TEAM_AURA_NAME",
    "find_ammo_covenant", "find_angel_blessing", "find_blessing",
    "find_class_aura", "find_limit_dispatch", "find_medic_monument",
    "find_regen", "find_snow", "find_team_aura",
    "is_ammo_covenant_talent", "is_angel_blessing", "is_blessing_talent",
    "is_class_aura_talent", "is_faction_aura_talent", "is_limit_dispatch",
    "is_medic_monument_talent", "is_regen_talent", "is_snow_talent",
    "is_team_aura_talent",
]


class Talent(Protocol):
    """只看得到这两个成员——`battle/talents.Talent` 满足它。"""

    name: str

    def has(self, *keys: str) -> bool: ...



# ====================================================================
# 指纹常量（`talents.py` 原样搬）
# ====================================================================

#: 新约能天使天赋2「铳弹协约」——「在场时，**携带弹药类技能**的干员攻击力
#: +9%（潜满 +13%），对【拉特兰】干员的效果**翻倍**」。
#:
#: 两处判据都不是键名能给的：`atk` 与技能自己的攻击力增益完全同名；
#: `mult` 在不同天赋里的含义各不相同（本仓库里它只在这一处出现，值 2.0）。
AMMO_COVENANT_NAME = "铳弹协约"

#: 「天使的祝福」（能天使天赋1）：「攻击力+6%，生命上限+10%。置入战场后这个
#: 效果会**同样赋予给一名随机友方单位**」——`{atk: 0.06, max_hp: 0.10}`，
#: 潜能 2 起 0.08/0.13。
#:
#: **本轮只做"自身那半"**（确定、无歧义）。「随机友方」那半需要一个口径
#: ——取最先部署的友方？把期望摊给全队？——**没有裁定就不动手**，
#: 见 `docs/uncertainties.md`。所以这条天赋在审计里**只算做了一半**，
#: 别把它当成已收口。
ANGEL_BLESSING_TALENTS = frozenset({"天使的祝福"})

#: 认出「圣山的祝福」天赋的黑板指纹（圣聆初雪天赋1）。
#:
#: 依据：天赋描述与黑板逐字对应——
#:
#: > 受到伤害时使敌人**寒冷** 1.5 秒，若受到**致命伤害**，仅一次立刻回复
#: > 所有生命值并使自身**冻结** 4 秒，使攻击范围内所有敌方单位**冻结** 8 秒
#:
#: ```
#: 精2 潜能 0–4： c2e_freeze 8.0   cold 1.5   freeze 4.0   hp_ratio 1.0
#: 精2 潜能 5–6： c2e_freeze 8.0   cold 2.0   freeze 4.0   hp_ratio 1.0
#: ```
#:
#: **为什么取这两个键，而不是 `cold` 或 `hp_ratio`**：全表核验过命中面——
#: `c2e_freeze` 与 `freeze` 各只命中这 2 条（同一天赋的两档潜能），
#: 而 `cold` 命中 10 条、`hp_ratio` 命中 156 条（`operator_talent` 共 2647 条）。
#: 后两个键单用会把一堆无关天赋认成这条。守卫把它钉成指纹。
BLESSING_KEYS = ("c2e_freeze", "freeze")

CLASS_AURA_TALENTS: dict[str, str] = {"特种作战策略": "TANK"}

#: 按**职业**发的全场光环：「在场时所有友方【重装】职业干员的防御力提升 6%」。
#: 名字 → 主职业**代号**（不是中文名）。与「万众巨潮」按**阵营**分是两回事：
#: 那是 `team_id`（哪个团），这是 `profession`（哪个职业）。
#:
#: 判据用**名字**而不是黑板键：这条天赋的黑板只有一个 `def`，而 `def` 满天飞，
#: 按键判会把一大票干员都算进来。名字是唯一能把"这句话"钉死的锚。
#: 「战术装甲」：**获得 X% 的伤害抵挡**（星熊天赋1）。
#:
#: **判据用名字，不用键。** 它的黑板键是 `prob`——而 `prob` 在全库**同名反义**
#: （本批十位干员里恰好三个概率键，其中就有同键不同义的），按键判会把它和
#: "眩晕概率"混成一件事。名字是唯一能把这句话钉死的锚。
#:
#: **语义上的一点说明**：「伤害抵挡」按确定性减伤 25% 读、还是按"25% 概率
#: 完全抵挡"读，**期望完全一样**（都是 ×0.75），所以这里可以直接借闪避那条
#: 现成的**期望值**通道表达，不必新增一套机制。这与"闪避能线性折进伤害"是
#: 同一条口径。**唯一不成立于真实伤害**：`resolve_damage` 里 dodge 只对
#: 物理/法术生效，真伤不吃。若日后发现抵挡该减免真伤，改这一处。
DAMAGE_BLOCK_TALENTS = frozenset({"战术装甲"})

#: 「技能期间**才**生效、且对某一阵营翻倍」的另一族全场光环：
#: 怒潮凛冬天赋2「万众巨潮」——「技能期间所有场上干员攻击力和防御力 +14%
#: （潜3 起 +18%），【乌萨斯学生自治团】干员获得加成效果翻倍」。
FACTION_AURA_NAME = "万众巨潮"

#: 【拉特兰】的势力代号（`operator.nation_id`）。
#:
#: ⚠️ 取的是 gamedata 的 `nationId` 字段，**不是"出身地"**：新约能天使本人这一栏
#: 写的是 `lungmen`（企鹅物流所在地），所以按本字段她**不吃自己的翻倍**。
#: 这是数据怎么写的就怎么算；PRTS 若另有说法再改，先记进 uncertainties。
#: 复核命令：`SELECT char_id, name FROM operator WHERE nation_id='laterano';`
LATERANO_NATION = "laterano"

#: 「极限调度」（可露希尔天赋2）：「携带可露希尔时，**部署费用下限降低 3**，
#: 【罗德岛】干员攻击力 +4%」——`{atk: 0.04, cost: -3.0}`。
#:
#: **只做攻击力那半。**`cost: -3` 是"部署费用下限"，属**名册/费用规则**侧的量，
#: 不在 `battle/`——所以这条天赋**同样只算做了一半**，别当成已收口。
LIMIT_DISPATCH_TALENTS = frozenset({"极限调度"})

#: 凯尔希 / 凯尔希·思衡托 **共用**的天赋2「**医者丰碑**」——「其他友方干员进入
#: 自身攻击范围时立刻获得 1 层护盾并额外获得一次每秒回复 50 点生命值的增益治疗，
#: 持续 30 秒（不可叠加），增益治疗对【罗德岛】干员的效果翻倍」。
#:
#: 三件事各有一个键：`hp_recovery_per_sec`（50）、`buff_duration`（30）、
#: `rhodes_bonus`（2.0）。**护盾那一层没有对应的黑板键**（层数写在正文里），
#: 所以它取不到数、也就不建模——见 `docs/uncertainties.md`。
MEDIC_MONUMENT_NAME = "医者丰碑"

#: 认出"入场增益治疗"天赋的黑板指纹。
#:
#: 依据：凯尔希·思衡托天赋2 的描述与黑板逐字对应——
#:
#: > 其他友方干员**进入自身攻击范围时**立刻获得 1 层护盾并额外获得一次
#: > **每秒回复 60 点生命值**的增益治疗，持续 **30 秒**（不可叠加），
#: > 增益治疗对【罗德岛】干员的效果翻倍
#:
#: ```
#: 黑板： buff_duration 30   hp_recovery_per_sec 60   rhodes_bonus 2
#: ```
#:
#: 建模的是"每秒回复 + 持续 + 不可叠加"这三条。**护盾那一层没建模**
#: （描述只写"1 层护盾"，没给数值），【罗德岛】翻倍也没建模——
#: 两处都按**偏保守**处理：宁可把治疗算少，不把生存算多。
REGEN_KEYS = ("hp_recovery_per_sec", "buff_duration")

#: 【罗德岛】——`operator.nation_id` 的取值。**不是 `team_id`**：那列是**小队**
#: （`student`/`rainbow`…），且能天使的 `team_id` 是 None 却属**龙门**。
RHODES_NATION = "rhodes"

#: 认出"积雪天赋"的黑板指纹。三个键同时出现才是，缺一不可。
SNOW_KEYS = ("interval", "max_cast_cnt", "talent_magic_scale")

#: 【乌萨斯学生自治团】的成员（`operator.team_id == 'student'`）。
#:
#: 用 char_id 常量而不是查库：**战斗层不连数据库**，而阵营是稳定的游戏数据。
#: 复核命令：`SELECT char_id, name FROM operator WHERE team_id='student';`
STUDENT_TEAM: frozenset[str] = frozenset({
    "char_1051_headb2",   # 怒潮凛冬
    "char_115_headbr",    # 凛冬
    "char_194_leto",      # 烈夏
    "char_195_glassb",    # 真理
    "char_196_sunbr",     # 古米
    "char_197_poca",      # 早露
    "char_405_absin",     # 苦艾
})

#: 「青色怒火」——阿米娅·**术战者**形态的天赋。
#:
#: 为什么只能按**天赋名**认、不能按键名认：它的黑板就是裸 `atk` / `def`，
#: 与技能自己的攻击力/防御力增益**完全同名**，靠键名根本分不出"这是光环"
#: 还是"这是技能给自己加的"。三个形态的天赋名各不相同（中坚术师「情绪吸收」
#: 的键是 `amiya_t_1[atk].sp`，不会误中），所以名字在这里是**可靠判据**。
#:
#: ```
#: 精一： atk 0.04  def 0.04
#: 精二： atk 0.07  def 0.07
#: ```
TEAM_AURA_NAME = "青色怒火"


# ====================================================================
# 判据与查找器（`talents.py` 原样搬）
# ====================================================================

def find_ammo_covenant(talents) -> Talent | None:
    for t in talents or ():
        if is_ammo_covenant_talent(t):
            return t
    return None

def find_angel_blessing(talents) -> Talent | None:
    for t in talents or ():
        if is_angel_blessing(t):
            return t
    return None

def find_blessing(talents) -> Talent | None:
    """找出「圣山的祝福」。没建模的技能/天赋一概不猜，这里也只认指纹。"""
    for t in talents or ():
        if is_blessing_talent(t):
            return t
    return None

def find_class_aura(talents) -> Talent | None:
    for t in talents or ():
        if is_class_aura_talent(t):
            return t
    return None

def find_damage_block(talents) -> Talent | None:
    for t in talents or ():
        if is_damage_block_talent(t):
            return t
    return None

def find_limit_dispatch(talents) -> Talent | None:
    for t in talents or ():
        if is_limit_dispatch(t):
            return t
    return None

def find_medic_monument(talents) -> Talent | None:
    for t in talents or ():
        if is_medic_monument_talent(t):
            return t
    return None

def find_regen(talents) -> Talent | None:
    for t in talents or ():
        if is_regen_talent(t):
            return t
    return None

def find_snow(talents) -> Talent | None:
    for t in talents or ():
        if is_snow_talent(t):
            return t
    return None

def find_team_aura(talents) -> Talent | None:
    for t in talents or ():
        if is_team_aura_talent(t) or is_faction_aura_talent(t):
            return t
    return None

def is_ammo_covenant_talent(t: Talent) -> bool:
    return t.name == AMMO_COVENANT_NAME and t.has("atk", "mult")

def is_angel_blessing(t: Talent) -> bool:
    return getattr(t, "name", "") in ANGEL_BLESSING_TALENTS

def is_blessing_talent(t: Talent) -> bool:
    return t.has(*BLESSING_KEYS)

def is_class_aura_talent(t: Talent) -> bool:
    return getattr(t, "name", "") in CLASS_AURA_TALENTS

def is_damage_block_talent(t: Talent) -> bool:
    return getattr(t, "name", "") in DAMAGE_BLOCK_TALENTS

def is_faction_aura_talent(t: Talent) -> bool:
    """「万众巨潮」：技能期间才生效，且对【乌萨斯学生自治团】翻倍。"""
    return t.name == FACTION_AURA_NAME and t.has("atk", "def")

def is_limit_dispatch(t: Talent) -> bool:
    return getattr(t, "name", "") in LIMIT_DISPATCH_TALENTS

def is_medic_monument_talent(t: Talent) -> bool:
    return t.name == MEDIC_MONUMENT_NAME and t.has("rhodes_bonus")

def is_regen_talent(t: Talent) -> bool:
    return t.has(*REGEN_KEYS)

def is_snow_talent(t: Talent) -> bool:
    return t.has(*SNOW_KEYS)

def is_team_aura_talent(t: Talent) -> bool:
    return t.name == TEAM_AURA_NAME and t.has("atk", "def")

