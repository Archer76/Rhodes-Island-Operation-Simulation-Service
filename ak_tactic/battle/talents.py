"""天赋在战斗里的落地。

数据层（`ak_tactic.operator.talent`）只能告诉你"这条天赋的黑板长这样"，
不能告诉你它**做什么**——和技能一样，语义活在描述文字里。所以这里对
**已核实**的天赋做显式建模，一条一条写清楚依据；没建模的天赋一概不猜。

目前建模两条：

## 积雪（圣聆初雪「无垠的雪景」）

依据：天赋描述 + 天赋黑板 + 技能2黑板三方对照。

```
天赋黑板（精英2，潜能1 档）：interval 5.5  max_cast_cnt 5
                             move_speed -0.12  talent_magic_scale 0.75
技能2黑板（专精三）：talent@s2_magic_scale 0.2
                     talent@max_cast_tile_count 20   talent@cold 5.0
```

> 攻击范围内的地面每隔 5.5 秒产生一层积雪，地面敌人经过时立即受到相当于攻击力
> 75% 的法术伤害，每层积雪使经过的所有敌人移动速度下降 12%，最多叠加 5 层
> （首个敌人离开该地块时积雪消失）
>
> 技能2 追加：处于积雪上的地面敌人**每秒**受到攻击力 20% 的法术伤害，
> 积雪超过 5 层时向周围扩散一层（最多向外扩散 20 格），敌人离开积雪时获得 5 秒寒冷

落到代码上的四条：

1. **积层**：每隔 `interval` 秒，射程内每个**地面**格 +1 层，上限 `max_cast_cnt`。
2. **踏入伤害**：地面敌人**每次踏入**雪格时受一次 `talent_magic_scale × 攻击力`
   的法术伤害。描述里"每层"只修饰减速（"每层积雪使……移动速度下降"），
   伤害那句没有"每层"，所以**按每次踏入一次**算，不乘层数。
3. **减速**：雪格上的敌人移速 × `(1 + move_speed × 层数)`，即每层 −12%、满 5 层 −60%。
4. **技能2 持续伤害**：技能2 开启期间，雪格上的地面敌人每秒再受
   `s2_magic_scale × 攻击力` 的法术伤害；并把扩散上限提到 `max_cast_tile_count`。

**未建模**（如实记下，别当成 0）：离开积雪的 5 秒寒冷、满 5 层后地块的冻结状态、
冻结带来的控制效果。以及天赋2「圣山的祝福」（受致命伤害时回满血并冻结周围）——
它只在德克萨斯这类"会被打死"的干员身上才有意义，而圣聆初雪在 SR-6 里不掉血。

## 编队加初始费（德克萨斯「战术快递」）

依据：天赋描述与黑板都是单键 `cost`，精英2 为 `cost 2.0`。

> **编入队伍后**，额外获得 2 点初始部署费用

注意是**编队时**就生效，不是部署那一刻才返费——所以它是开局初始费用 +2，
由模拟器在 `run()` 开始时一次性结算，而不是挂在 `_do_deploy` 上。
两者总额相同、**时点不同**：开局就多 2 费意味着第一个干员能早 2 秒落地。

判据：**天赋黑板有且仅有 `cost` 一个键**。键多了就可能是"费用降低／费用上限"之类，
那属于没建模的范畴，宁可返回 0 也不猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..operator.talent import Talent

__all__ = [
    "DAMAGE_BLOCK_TALENTS",
    "is_damage_block_talent",
    "find_damage_block",
    "DOT_ON_HIT_TALENTS",
    "is_dot_on_hit_talent",
    "find_dot_on_hit",
    "ANGEL_BLESSING_TALENTS",
    "is_angel_blessing",
    "find_angel_blessing",
    "POWER_ATTACK_TALENTS",
    "PowerAttack",
    "is_power_attack_talent",
    "find_power_attack",
    "GLIDER_MOBILITY_TALENTS",
    "GLIDER_MOBILITY_KEYS",
    "GliderMobility",
    "is_glider_mobility",
    "find_glider_mobility",
    "RHODES_NATION",
    "LIMIT_DISPATCH_TALENTS",
    "is_limit_dispatch",
    "find_limit_dispatch",
    "CLASS_AURA_TALENTS",
    "is_class_aura_talent",
    "find_class_aura",
    "SnowField",
    "SNOW_KEYS",
    "is_snow_talent",
    "find_snow",
    "BLESSING_KEYS",
    "is_blessing_talent",
    "find_blessing",
    "squad_cost_bonus",
    "REGEN_KEYS",
    "find_regen",
    "RegenAura",
    "SP_KEYS",
    "is_sp_talent",
    "find_sp_on_action",
    "SpOnAction",
    "MODELED",
]

#: 认出"积雪天赋"的黑板指纹。三个键同时出现才是，缺一不可。
SNOW_KEYS = ("interval", "max_cast_cnt", "talent_magic_scale")

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

#: 已被显式建模的天赋一览（给 CLI 与文档用）
MODELED = {
    "snow": "积雪：积层 / 踏入伤害 / 每层减速 / 满层冻结 / 技能2 持续伤害",
    "blessing": "圣山的祝福：致命伤免死一次（回满血 + 自身冻结 + 范围冻结）",
    "squad_cost": "编入队伍后额外获得初始部署费用",
    "regen_aura": "友方进入攻击范围时获得每秒回复生命值的增益治疗",
    "sp_on_action": "情绪吸收：攻击敌人额外回技力、消灭敌人额外得技力",
    "team_aura": "青色怒火：全场友方攻击力/防御力提升，光环主人开技能时加倍",
}

#: 认出"情绪吸收"天赋的黑板指纹（阿米娅·**中坚术师**形态）。
#:
#: 依据：天赋描述与黑板逐字对应——
#:
#: > 攻击敌人时额外回复 2 点技力，消灭敌人后额外获得 8 点技力
#:
#: ```
#: 潜能 1–4 档： amiya_t_1[atk].sp 2    amiya_t_1[kill].sp 8
#: 潜能 5–6 档： amiya_t_1[atk].sp 3    amiya_t_1[kill].sp 10
#: ```
#:
#: 两个坑：
#: ① 键名里的 `atk` 指的是**"攻击"这个动作**，与攻击力无关，别被它误导；
#: ② **阿米娅三个形态的天赋各不相同**——中坚术师「情绪吸收」、术战者
#:    「青色怒火」、医疗「诚挚期许」。所以指纹只认这对键、不认干员是谁；
#:    术战者的黑板是 `atk`/`def`，不会误中。
SP_KEYS = ("amiya_t_1[atk].sp", "amiya_t_1[kill].sp")


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


#: 「死亡拘审」（阿斯卡纶天赋1）：**攻击给敌人挂一个持续伤害**。
#: 「移动速度降低 12%，每秒受到 6% 阿斯卡纶当前攻击力的法术伤害，持续 18 秒，
#: 效果最多叠加三层」——`{atk_ratio: 0.06, debuff_duration: 18, interval: 1,
#: max_stack_cnt: 3, move_speed: -0.12}`。
#:
#: 判据仍用**名字**：`atk_ratio` 这个键名本身并不说明"这是持续伤害"，
#: 全库同名反义的老问题在这里同样成立。
#:
#: **一处留档的读法选择**：正文写「**当前**攻击力」，而持续伤害在游戏里通常
#: 按**施加瞬间**快照。这里取**快照**（`dot_per_sec` 在挂上那一刻算定），
#: 理由是若能逐帧变值，同一层数会因阿斯卡纶中途开技能而改变每秒伤害，
#: 「最多叠加三层」就不再是一个稳定的量。若日后实机证明是逐帧取值，
#: 改 `_apply_dot` 一处即可。
DOT_ON_HIT_TALENTS = frozenset({"死亡拘审"})


def is_dot_on_hit_talent(t: Talent) -> bool:
    return getattr(t, "name", "") in DOT_ON_HIT_TALENTS


def find_dot_on_hit(talents) -> Talent | None:
    for t in talents or ():
        if is_dot_on_hit_talent(t):
            return t
    return None


def is_damage_block_talent(t: Talent) -> bool:
    return getattr(t, "name", "") in DAMAGE_BLOCK_TALENTS


@dataclass(frozen=True)
class GliderMobility:
    """天赋「翔虫机动」（焰狐龙梓兰 天赋2）——**一个天赋，两个平面**。

    正文（精2）：「再部署时间-15秒且不提高部署费用；部署至上次部署位置周围时，
    30秒内攻击力+15%并且可以部署在近战位」。

    prts.wiki 该页 `|备注=` 把"上次部署位置周围"落实成了一个实体：

    > ※离场后将在原地留下一个静止[[弹道]]，弹道效果范围 `[范围:x-1]`，持续存在
    > 直至下次焰狐龙梓兰部署或下次留下该弹道
    > ※非首次部署时，焰狐龙梓兰可以部署在远程位地块／弹道范围内的近战位地块，
    > 以此部署的焰狐龙梓兰的部署类型将临时变为全部位；部署于该弹道范围后将获得
    > 攻击力加成效果
    > ※不提高部署费用的实现逻辑为部署后获得永久的"离场后不累加再部署惩罚"效果

    于是七个黑板键各有归属（值取精2 档）：

    * `atk` 0.15 / `atk_duration` 30 —— 落在弹道范围内的**限时攻击力加成**
      （战斗层，`sim._mobility_on_deploy`）。
    * `projectile`（`$projectile` = `projectile_chr_orchd2_t`）——那个静止弹道的
      预制体代号，"上次部署位置周围"就是以它为准。
    * `ignore_build_type_target` 1 / `..._dir` 0 /
      `..._range`（`$...` = `x-1`）——**落位放宽**：范围代号 `x-1`、以她上次
      部署点为原点的格子里，**近战位**也可以放（部署类型临时变"全部位"）。
    * `not_add_respawn_cost_cnt` 1 —— 离场后**不累加再部署惩罚**（精1 档是 0）。
    """

    #: 限时攻击力加成（`atk`，精2 = 0.15）。
    atk_bonus: float
    #: 加成持续秒数（`atk_duration`）。
    atk_duration: float
    #: 静止弹道的预制体代号（`$projectile`）。
    projectile: str
    #: 落位放宽用的范围代号（`$ignore_build_type_target_range`），以**上次部署点**
    #: 为原点。她两档都是 `x-1`。
    deploy_range: str
    #: 是否开启落位放宽（`ignore_build_type_target`）。
    ignore_build_type: bool
    #: 放宽的方向参数（`ignore_build_type_target_dir`）。她两档都是 0。
    ignore_dir: float
    #: 离场后是否不累加再部署惩罚（`not_add_respawn_cost_cnt`）。精1 档为假。
    no_respawn_cost_add: bool


#: 具名的「翔虫机动」。
GLIDER_MOBILITY_TALENTS = frozenset({"翔虫机动"})
#: 认这条天赋要**同时**看到的键——名字可以被改、被本地化，键不会。
GLIDER_MOBILITY_KEYS = ("ignore_build_type_target", "not_add_respawn_cost_cnt")


def is_glider_mobility(t: Any) -> bool:
    """是不是「翔虫机动」。名字或键的组合命中即可（判法同本文件其它天赋）。"""
    if getattr(t, "name", "") in GLIDER_MOBILITY_TALENTS:
        return True
    bb = getattr(t, "blackboard", None) or {}
    return all(k in bb for k in GLIDER_MOBILITY_KEYS)


def find_glider_mobility(talents: Any) -> GliderMobility | None:
    """从天赋列表里取出「翔虫机动」。没有就返回 None（调用方按"没这天赋"处理）。"""
    for t in talents or ():
        if not is_glider_mobility(t):
            continue
        bb = t.blackboard or {}
        # 范围代号在 `$key`（`valueStr`）里——裸键的 value 恒为 0：
        # `{"key": "ignore_build_type_target_range", "value": 0, "valueStr": "x-1"}`。
        # 两个都读：裸键是`是否给了这一项`的证据，`$` 键才是真值。
        deploy_range = str(bb.get("$ignore_build_type_target_range")
                           or bb.get("ignore_build_type_target_range") or "")
        return GliderMobility(
            atk_bonus=float(bb.get("atk") or 0.0),
            atk_duration=float(bb.get("atk_duration") or 0.0),
            projectile=str(bb.get("$projectile") or bb.get("projectile") or ""),
            deploy_range=deploy_range,
            ignore_build_type=bool(bb.get("ignore_build_type_target") or 0.0),
            ignore_dir=float(bb.get("ignore_build_type_target_dir") or 0.0),
            no_respawn_cost_add=bool(bb.get("not_add_respawn_cost_cnt") or 0.0),
        )
    return None


@dataclass(frozen=True)
class PowerAttack:
    """天赋「强击瓶专家」（焰狐龙梓兰 天赋1）。

    正文：「部署后首次开启技能时，接下来 50 次攻击的攻击力提升至 115%」。

    prts.wiki 该页 `|备注=` 把它钉成"按**轮**数"而不是按箭矢：

    > ※其攻击力提升效果将作用于**当次连击的所有弹道**……于弹道脱手前生效
    > ※每轮技能三/四/五连击、每次二技能的降落攻击、每次三技能的龙之箭
    > 均会消耗 1 次效果

    所以 `count` 数的是**攻击动作**（一轮），`sim` 在出手时整轮乘一次、
    只扣一层；技2 一次技能含三轮齐射＋一次落地点射 ⇒ 一次扣四层。
    """

    #: 一共多少轮（`power_attack_count`，她 50）。
    count: int
    #: 攻击力倍率（`power_attack_scale`，精2 = 1.15）。
    scale: float
    """「强击瓶专家」：部署后首次开技起，接下来 N 次**攻击**的攻击力倍率。

    注意 `count` 数的是**攻击动作**，不是箭矢：prts.wiki「焰狐龙梓兰」页
    `|备注=` 原文——

    > ※天赋启动后，'''每轮'''普通攻击三连击、'''每轮'''技能三/四/五连击、
    > '''每次'''二技能的降落攻击、'''每次'''三技能的龙之箭都会消耗'''一层'''攻击力
    > 提升效果的层数来触发攻击力提升效果
    > ※攻击力提升效果为攻击力倍率提升，于**弹道脱手前**对当次连击的所有
    > 弹道/龙之箭弹道的攻击力倍率生效

    所以一次出手的所有箭矢都吃加成、整轮只扣一层。博士 2026-09-18 的裁定
    （「按出手」）与此一致。
    """

    count: int
    scale: float


#: 具名检测器（审计第三道筛子按天赋名判有没有人读它，名字要作为字面量留在源码里）。
POWER_ATTACK_TALENTS = frozenset({"强击瓶专家"})


def is_power_attack_talent(t: Any) -> bool:
    """这条天赋是不是「强击瓶专家」。

    判据是**键的组合**（`power_attack_count` + `power_attack_scale`），不是名字：
    名字只留给审计的第三道筛子看。
    """
    if str(getattr(t, "name", "")) in POWER_ATTACK_TALENTS:
        return True
    bb = getattr(t, "blackboard", None) or {}
    return "power_attack_count" in bb and "power_attack_scale" in bb


def find_power_attack(talents) -> PowerAttack | None:
    """把「强击瓶专家」的黑板翻成 `PowerAttack`，没有则返回 None。"""
    for t in talents or ():
        if not is_power_attack_talent(t):
            continue
        bb = getattr(t, "blackboard", None) or {}
        return PowerAttack(count=int(bb.get("power_attack_count") or 0),
                           scale=float(bb.get("power_attack_scale") or 1.0))
    return None


def find_damage_block(talents) -> Talent | None:
    for t in talents or ():
        if is_damage_block_talent(t):
            return t
    return None


CLASS_AURA_TALENTS: dict[str, str] = {"特种作战策略": "TANK"}

#: 【罗德岛】——`operator.nation_id` 的取值。**不是 `team_id`**：那列是**小队**
#: （`student`/`rainbow`…），且能天使的 `team_id` 是 None 却属**龙门**。
RHODES_NATION = "rhodes"

#: 「极限调度」（可露希尔天赋2）：「携带可露希尔时，**部署费用下限降低 3**，
#: 【罗德岛】干员攻击力 +4%」——`{atk: 0.04, cost: -3.0}`。
#:
#: **只做攻击力那半。**`cost: -3` 是"部署费用下限"，属**名册/费用规则**侧的量，
#: 不在 `battle/`——所以这条天赋**同样只算做了一半**，别当成已收口。
LIMIT_DISPATCH_TALENTS = frozenset({"极限调度"})


def is_limit_dispatch(t: Talent) -> bool:
    return getattr(t, "name", "") in LIMIT_DISPATCH_TALENTS


def find_limit_dispatch(talents) -> Talent | None:
    for t in talents or ():
        if is_limit_dispatch(t):
            return t
    return None


#: 「天使的祝福」（能天使天赋1）：「攻击力+6%，生命上限+10%。置入战场后这个
#: 效果会**同样赋予给一名随机友方单位**」——`{atk: 0.06, max_hp: 0.10}`，
#: 潜能 2 起 0.08/0.13。
#:
#: **本轮只做"自身那半"**（确定、无歧义）。「随机友方」那半需要一个口径
#: ——取最先部署的友方？把期望摊给全队？——**没有裁定就不动手**，
#: 见 `docs/uncertainties.md`。所以这条天赋在审计里**只算做了一半**，
#: 别把它当成已收口。
ANGEL_BLESSING_TALENTS = frozenset({"天使的祝福"})


def is_angel_blessing(t: Talent) -> bool:
    return getattr(t, "name", "") in ANGEL_BLESSING_TALENTS


def find_angel_blessing(talents) -> Talent | None:
    for t in talents or ():
        if is_angel_blessing(t):
            return t
    return None


def is_class_aura_talent(t: Talent) -> bool:
    return getattr(t, "name", "") in CLASS_AURA_TALENTS


def find_class_aura(talents) -> Talent | None:
    for t in talents or ():
        if is_class_aura_talent(t):
            return t
    return None


def is_sp_talent(t: Talent) -> bool:
    return t.has(*SP_KEYS)


@dataclass
class SpOnAction:
    """「情绪吸收」：攻击敌人时额外回技力，消灭敌人后额外获得技力。

    这是**叠加在技能自己的 `sp_type` 之上的第二条 SP 来源**，不是替代：
    技能是"攻击回复"型时两条都记；是"自动回复"型时这条照样记
    （阿米娅技1「战术咏唱·γ型」正是自动回复型，若只认 sp_type 就整条漏掉）。

    「攻击敌人时」按**出手**算一次，不按打中几个目标算——与模拟器里
    `sp_per_attack` 的口径一致（见 `_operators_attack` 的同名注释）。
    """

    per_attack: float = 0.0
    per_kill: float = 0.0


def find_sp_on_action(talents) -> "SpOnAction | None":
    """把「情绪吸收」的黑板翻成 `SpOnAction`，没有这个天赋则返回 None。"""
    for t in talents or ():
        if not is_sp_talent(t):
            continue
        return SpOnAction(per_attack=t.value("amiya_t_1[atk].sp"),
                          per_kill=t.value("amiya_t_1[kill].sp"))
    return None


def is_regen_talent(t: Talent) -> bool:
    return t.has(*REGEN_KEYS)


def find_regen(talents) -> Talent | None:
    for t in talents or ():
        if is_regen_talent(t):
            return t
    return None


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

#: 「技能期间**才**生效、且对某一阵营翻倍」的另一族全场光环：
#: 怒潮凛冬天赋2「万众巨潮」——「技能期间所有场上干员攻击力和防御力 +14%
#: （潜3 起 +18%），【乌萨斯学生自治团】干员获得加成效果翻倍」。
FACTION_AURA_NAME = "万众巨潮"

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


def is_team_aura_talent(t: Talent) -> bool:
    return t.name == TEAM_AURA_NAME and t.has("atk", "def")


def is_faction_aura_talent(t: Talent) -> bool:
    """「万众巨潮」：技能期间才生效，且对【乌萨斯学生自治团】翻倍。"""
    return t.name == FACTION_AURA_NAME and t.has("atk", "def")


def find_team_aura(talents) -> Talent | None:
    for t in talents or ():
        if is_team_aura_talent(t) or is_faction_aura_talent(t):
            return t
    return None


#: 新约能天使天赋1「火力电台」——「在场时，每当有**友方干员的弹药被消耗**就会
#: 回复自身 6% 生命值，并有 20%/25% 概率立即对该干员攻击范围的敌人召唤一次
#: 轰炸，造成相当于自身攻击力 105%…的物理**溅射**伤害」。
#:
#: 判据用**天赋名 + `aoe_atk_scale`** 双锚定：这个键全表只出现在她的天赋上
#: （四档：1.05 / 1.2 / 1.5 / 1.65，精0 → 精2 逐档抬）。同黑板的
#: `damage_scale` 是同一个数的别名、`hp_ratio` 是那一口自愈、`prob` 是轰炸概率。
#:
#: ⚠️ prts `|备注=` 补了四条正文没写的行为（2026-09-18 取）：
#: ① 「根据**本轮消耗数量循环处理**治疗与轰炸概率」——一次消耗多发就按发数触发；
#: ② 「不论消耗数量，**每轮轰炸仅选取一次目标**，每次成功的概率判定都会增加
#:    一次本轮的轰炸」，单轮多次轰炸之间间隔 0.1s；
#: ③ 「轰炸半径 1.3，造成**预计算**的物理普通伤害」；
#: ④ 「轰炸时**借用消耗者的攻击范围**，由新约能天使判断该范围内的轰炸目标
#:    （**始终使用默认索敌逻辑**）」。
BOMB_RADIO_NAME = "火力电台"

#: 新约能天使天赋2「铳弹协约」——「在场时，**携带弹药类技能**的干员攻击力
#: +9%（潜满 +13%），对【拉特兰】干员的效果**翻倍**」。
#:
#: 两处判据都不是键名能给的：`atk` 与技能自己的攻击力增益完全同名；
#: `mult` 在不同天赋里的含义各不相同（本仓库里它只在这一处出现，值 2.0）。
AMMO_COVENANT_NAME = "铳弹协约"

#: 【拉特兰】的势力代号（`operator.nation_id`）。
#:
#: ⚠️ 取的是 gamedata 的 `nationId` 字段，**不是"出身地"**：新约能天使本人这一栏
#: 写的是 `lungmen`（企鹅物流所在地），所以按本字段她**不吃自己的翻倍**。
#: 这是数据怎么写的就怎么算；PRTS 若另有说法再改，先记进 uncertainties。
#: 复核命令：`SELECT char_id, name FROM operator WHERE nation_id='laterano';`
LATERANO_NATION = "laterano"


def is_bomb_radio_talent(t: Talent) -> bool:
    return t.name == BOMB_RADIO_NAME and t.has("aoe_atk_scale")


def find_bomb_radio(talents) -> Talent | None:
    for t in talents or ():
        if is_bomb_radio_talent(t):
            return t
    return None


def is_ammo_covenant_talent(t: Talent) -> bool:
    return t.name == AMMO_COVENANT_NAME and t.has("atk", "mult")


def find_ammo_covenant(talents) -> Talent | None:
    for t in talents or ():
        if is_ammo_covenant_talent(t):
            return t
    return None


#: 结城理天赋1「不羁之力」——「〈替身〉状态下结城理召唤人格面具作战，**攻击间隔
#: 增大**，攻击力 +40/60/80%，生命值 +35%，作战能力随技能选择而改变」。
#:
#: 判据用**天赋名 + `max_hp_t1`** 双锚定：这个键全表只在他身上出现。
#: 同黑板的 `atk` 是替身形态的攻击力增益、`base_attack_time` 是攻击间隔增加量
#: （0.4 秒）、`sluggish` 是「切换为〈替身〉时停顿周围敌人的秒数」（精1 起 5、
#: 精2 为 8）。prts 特性备注补了一句正文没有的：**只有从〈本体〉切进〈替身〉
#: 才触发停顿**，〈替身〉形态之间互切不触发；停顿范围等于〈替身〉的攻击范围。
PERSONA_POWER_NAME = "不羁之力"

#: 结城理天赋2「S.E.E.S.队长」——「〈替身〉状态**结束后**，带领 S.E.E.S. 小队发动
#: 总攻击，对小队队员周围一定范围内的所有敌人造成相当于结城理攻击力 180…450%
#: 的**真实**伤害（可叠加）」。
#:
#: 三条黑板键都在这条天赋上：`atk_scale`（倍率）、`multi_attack_total_cnt`（叠加
#: 次数，1.0）、`final_damage_different_ratio`（伤害类型不同时的最终倍率，1.0）。
#: 后两个在她身上是**恒等值**，但通道照样接——见 `docs/uncertainties.md`。
SEES_LEADER_NAME = "S.E.E.S.队长"


def is_persona_power_talent(t: Talent) -> bool:
    return t.name == PERSONA_POWER_NAME and t.has("max_hp_t1")


def find_persona_power(talents) -> Talent | None:
    for t in talents or ():
        if is_persona_power_talent(t):
            return t
    return None


def is_sees_leader_talent(t: Talent) -> bool:
    return t.name == SEES_LEADER_NAME and t.has("atk_scale")


def find_sees_leader(talents) -> Talent | None:
    for t in talents or ():
        if is_sees_leader_talent(t):
            return t
    return None


#: 凯尔希 / 凯尔希·思衡托 天赋1「**遗尘守望**」——生命上限与防御力 +25%、
#: 阻挡数 +1、**阻挡范围扩大**。
#:
#: 最后一个键 `block_radius_scale`（0.23）的语义有 prts 备注作准：
#: 「阻挡范围加成为提升自身的『**阻挡半径倍率**』属性」，而且
#: 「与一技能效果间**同名效果取最高**」——**不是相加**。她的技1 给同一个属性
#: 同一个数，取最高之后还是 0.23；照着相加算会变成 0.46。
RELIC_WATCH_NAME = "遗尘守望"

#: 凯尔希 / 凯尔希·思衡托 **共用**的天赋2「**医者丰碑**」——「其他友方干员进入
#: 自身攻击范围时立刻获得 1 层护盾并额外获得一次每秒回复 50 点生命值的增益治疗，
#: 持续 30 秒（不可叠加），增益治疗对【罗德岛】干员的效果翻倍」。
#:
#: 三件事各有一个键：`hp_recovery_per_sec`（50）、`buff_duration`（30）、
#: `rhodes_bonus`（2.0）。**护盾那一层没有对应的黑板键**（层数写在正文里），
#: 所以它取不到数、也就不建模——见 `docs/uncertainties.md`。
MEDIC_MONUMENT_NAME = "医者丰碑"


def is_relic_watch_talent(t: Talent) -> bool:
    return t.name == RELIC_WATCH_NAME and t.has("block_radius_scale")


def find_relic_watch(talents) -> Talent | None:
    for t in talents or ():
        if is_relic_watch_talent(t):
            return t
    return None


def is_medic_monument_talent(t: Talent) -> bool:
    return t.name == MEDIC_MONUMENT_NAME and t.has("rhodes_bonus")


def find_medic_monument(talents) -> Talent | None:
    for t in talents or ():
        if is_medic_monument_talent(t):
            return t
    return None


@dataclass
class TeamAura:
    """一个干员发给**全场友方**的攻击力/防御力光环。

    两种语义共用一个类，靠 `skill_only` 分开：

    * **青色怒火**（`skill_only=False`）——「在场时所有友方单位的攻击力和
      防御力 +7%，**技能开启期间效果加倍**」。「加倍」的主语是**光环的主人
      自己**——博士 2026-09-17 裁定。阿米娅开技能的那段时间全场吃到双倍，
      她不开就只有基础值；别人开不开技能与她无关。技2 黑板里的
      `talent_scale: 2.0` 正是这个倍率的数据化表达。
    * **万众巨潮**（`skill_only=True`）——「**技能期间**所有场上干员攻击力和
      防御力 +14%，【乌萨斯学生自治团】干员获得加成效果翻倍」。底子不是常驻
      的：主人不开技能就**一点都没有**（返回 0），这与青色怒火"常驻 + 开技能
      加倍"是两种形状，不能用同一个 `k` 表达。

    与 `RegenAura` 的关键差别：那个是**射程内**才生效，这个是**全场**，
    不看位置，所以没有 `cells_of`、也没有"进入"那一刻的歧义。
    """

    owner: str
    atk_pct: float
    def_pct: float
    #: 加倍倍率。描述写「加倍」即 2.0。
    double_scale: float = 2.0
    #: 光环主人本体（模拟器填），翻倍与否要看它开着技能没有
    operator: object = None
    #: 「技能期间**才**生效」。False = 常驻（青色怒火）。
    skill_only: bool = False
    #: 只对这些 char_id 翻倍（万众巨潮的【乌萨斯学生自治团】）；None = 不按阵营分
    faction: frozenset[str] | None = None
    #: 阵营翻倍倍率（黑板 `scale_bonus`，写的是 2.0）
    faction_scale: float = 2.0
    #: **只发给这个主职业代号的人**（`TANK` = 重装）；None = 不按职业分。
    #: 与 `faction`（阵营 `team_id`）是**两回事**：那是"哪个团"，这是"哪个职业"。
    profession: str | None = None
    #: **只发给光环主人自己**（能天使「天使的祝福」的自身那半）。与 `profession`
    #: 的区别：那个筛"什么职业"，这个筛"就是我自己"。
    #: 判等用**同一对象**（`target is self.operator`），**不按 char_id**——
    #: 同一关里可以有同名干员，按 char_id 会把别人的那份也发出去。
    self_only: bool = False
    #: **只发给某个势力的人**（`nation_id`，如 `rhodes` = 【罗德岛】）。
    #: 与 `faction`（阵营**翻倍**）是两种语义：那个是"该阵营 ×2、别人 ×1"，
    #: 这个是"只有该势力拿、别人 0"——**筛选**，不是倍率。
    faction_only: str | None = None
    #: **只发给「携带弹药类技能」的人**（新约能天使「铳弹协约」）。判据是那个人
    #: **当前装备的技能**是弹药类（`skill.duration_type == "AMMO"`），与技能开没开
    #: 无关——正文写的是「**携带**弹药类技能」，不是"开技能期间"。
    ammo_skill_only: bool = False
    #: **对某个势力的人翻倍**（`nation_id`，如 `laterano` = 【拉特兰】）。
    #: 与 `faction`（按 char_id 枚举名单翻倍）是两种数据形态：那个是写死的名单，
    #: 这个是按势力字段判，成员随新干员增加。与 `faction_only`（筛选）也不同：
    #: 这个是"该势力 ×2、别人 ×1"。倍率用 `double_scale`。
    nation_double: str | None = None

    def current(self, target=None) -> tuple[float, float]:
        """当前对 `target` 生效的 `(攻击力比例, 防御力比例)`。

        `target` 是**吃光环的那个人**——万众巨潮要对它判阵营、特种作战策略要对它
        判职业，所以这个参数不是可选的装饰：不传就一律按不吃翻倍/不匹配算。
        """
        if self.self_only and target is not self.operator:
            # 只给自己：**不按 char_id 比**（同名干员会串），按对象同一性。
            return 0.0, 0.0
        if self.ammo_skill_only:
            # 按「携带**弹药类技能**」发：与技能开没开无关（正文写的是「携带」）。
            # 判据看那个人**当前装备的那个技能**是不是 AMMO 型。
            sk = getattr(target, "skill", None)
            if sk is None or getattr(sk, "duration_type", "") != "AMMO":
                return 0.0, 0.0
            k = 1.0
            if (self.nation_double is not None
                    and getattr(target, "nation_id", "") == self.nation_double):
                k = self.double_scale
            return self.atk_pct * k, self.def_pct * k
        if self.faction_only is not None:
            # 按势力**发**：不匹配的一律 0（这是筛选，不是翻倍）。
            if getattr(target, "nation_id", "") != self.faction_only:
                return 0.0, 0.0
            return self.atk_pct, self.def_pct
        if self.profession is not None:
            # 按职业发：**不吃倍率**，也不看主人开不开技能（星熊那条是常驻的）。
            # 空职业（手工搭的试验体）不匹配任何职业光环。
            if getattr(target, "profession", "") != self.profession:
                return 0.0, 0.0
            return self.atk_pct, self.def_pct
        op = self.operator
        active = op is not None and getattr(op, "skill_active", False)
        if self.skill_only:
            if not active:
                return 0.0, 0.0
            k = 1.0
            if self.faction and getattr(target, "char_id", None) in self.faction:
                k = self.faction_scale
            return self.atk_pct * k, self.def_pct * k
        k = self.double_scale if active else 1.0
        return self.atk_pct * k, self.def_pct * k


@dataclass
class RegenAura:
    """一个干员光环式发出的"增益治疗"。

    「进入自身攻击范围时」——注意**部署进射程内也算进入**。游戏里干员落地
    那一刻就是在范围里，天赋照样触发，所以这里在部署当帧就判一次，
    不等它"走进来"。
    """

    owner: str
    hp_per_sec: float
    duration: float
    #: 光环干员本体（模拟器填），射程要问它
    operator: object = None
    #: 已经吃过这份增益的友方名字——「不可叠加」= 每人只触发一次
    granted: set = field(default_factory=set)
    granted_count: int = 0
    #: 对某个势力的友方**效果翻倍**（`rhodes_bonus`）：势力代号与倍率。
    #:
    #: 凯尔希 / 凯尔希·思衡托 天赋「医者丰碑」原文：「…额外获得一次每秒回复 50
    #: 点生命值的增益治疗，持续 30 秒（不可叠加），**增益治疗对【罗德岛】干员的
    #: 效果翻倍**」。黑板上的两个键就是这两件事：`hp_recovery_per_sec` 是 50，
    #: `rhodes_bonus` 是 2.0。
    nation_double: str = ""
    nation_mult: float = 1.0

    def tick(self, dt: float, operators, cells_of, *, strict: bool = False) -> float:
        """推进一帧，返回本帧发出的治疗总量。

        :param cells_of: `(op) -> set[(x, y)]`，取干员的攻击范围
        :param strict: 「进入」的严格读法——只算**光环落地之后**才进场的
            友方。宽松读法（默认）把光环落地当帧已在范围内的友方也算"进入"，
            因为游戏里干员落地那一刻就是在范围里。

            **这条歧义是实质性的**：SR-EX-8 里凯尔希 72s 才落地，而圣聆初雪
            35s 就站在范围内了。严格读法下她吃不到这份治疗，本关的最优解
            会从"四人·余量 79%"退回"三人·余量 38%"。故两种都要跑。
        """
        total = 0.0
        give = self.operator is not None and self.operator.alive
        aura_cells = cells_of(self.operator) if give else set()
        # 光环本人在场上的序号：严格读法只认它之后的
        order = {}
        for i, o in enumerate(operators):
            order[o.name] = i
        owner_idx = order.get(self.owner, -1)
        for op in operators:
            if op is self.operator or not op.alive:
                continue
            cell = (int(round(op.position[0])), int(round(op.position[1])))
            eligible = (not strict) or order.get(op.name, -1) > owner_idx
            if give and eligible and op.name not in self.granted and cell in aura_cells:
                self.granted.add(op.name)
                self.granted_count += 1
                op.regen_left = max(op.regen_left, self.duration)
                # 【罗德岛】干员的效果翻倍——翻的是**速率**，不是持续时间
                # （原文「增益治疗对【罗德岛】干员的效果翻倍」，紧跟在"每秒回复
                # 50 点"后面）。倍率取黑板 `rhodes_bonus`，不是写死的 2.0：
                # 同一个键将来给别的数也能用。
                rate = self.hp_per_sec
                if (self.nation_double
                        and getattr(op, "nation_id", "") == self.nation_double):
                    rate *= self.nation_mult
                op.regen_per_sec = max(op.regen_per_sec, rate)
            if op.regen_left > 0:
                # 增益已经挂在身上了，就算光环本人倒掉也照样跳完
                step = min(dt, op.regen_left)
                got = op.heal(op.regen_per_sec * step)
                op.regen_left = max(0.0, op.regen_left - dt)
                if op.regen_left <= 0:
                    op.regen_per_sec = 0.0
                total += got
                if self.operator is not None:
                    self.operator.healing_done += got
        return total


Cell = tuple[int, int]


def is_snow_talent(t: Talent) -> bool:
    return t.has(*SNOW_KEYS)


def find_snow(talents) -> Talent | None:
    for t in talents or ():
        if is_snow_talent(t):
            return t
    return None


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


def is_blessing_talent(t: Talent) -> bool:
    return t.has(*BLESSING_KEYS)


def find_blessing(talents) -> Talent | None:
    """找出「圣山的祝福」。没建模的技能/天赋一概不猜，这里也只认指纹。"""
    for t in talents or ():
        if is_blessing_talent(t):
            return t
    return None


def squad_cost_bonus(talents) -> float:
    """「编入队伍后，额外获得 N 点初始部署费用」这类天赋的数额，没有就是 0。

    只认**单键 `cost`** 的天赋：键多了就可能是"费用降低 / 费用上限"之类，
    那属于没建模的范畴，宁可返回 0 也不猜。

    时点是**开局**，不是部署时——所以模拟器在 `run()` 起点结算一次，
    而不是在 `_do_deploy` 里返费。
    """
    total = 0.0
    for t in talents or ():
        sig = [k for k in t.blackboard if not k.startswith("$")]
        if sig == ["cost"]:
            total += t.value("cost")
    return total


#: 「可以使用 N 个召唤物（最多同时部署 M 个）」这类天赋的判据。
#:
#: 判据两条**同时**成立才算：
#:   ① 描述里出现「可以使用」且出现「召唤物」或「棋子」（两种叫法，机制同一）；
#:   ② 黑板里有 `cnt` 且大于 0。
#:
#: 为什么不只按黑板键认：`cnt` 是个泛用键名，全表有 100+ 条天赋带它
#: （计数类、层数类都叫这个），只按键名认会大面积误中。描述里的
#: 「可以使用」是这句机制独有的措辞。
#:
#: 逐条出处（2026-09-18 全表核验）：
#:   电弧「卡带里的灵感」：可以使用 3 个召唤物（最多同时部署 3 个）  cnt 3
#:   令  「挑灯问梦」  ：可以使用 3 个召唤物（最多同时部署 3 个）  cnt 3
#:   望  「铸子」      ：可以使用 4 枚棋子（最多拥有 5 枚）        cnt 4  max_cnt 0
#:
#: 望那条的 `max_cnt` 是 0，而文本说「最多拥有 5 枚」——**两个量不是一回事**
#: （一个是同时部署上限，一个是库存上限），本函数只取 `cnt`。
_SUMMON_WORDS = ("召唤物", "棋子")


def find_species_resistance(talents) -> Talent | None:
    """泥岩天赋「手足相惜」：受到来自【某类】敌人的伤害降低 X%。

    判据要**两条同时**成立：正文里有「受到来自【…】敌人的伤害」这个句式（种类
    落在 `SkillEffects.resistance_species`），且黑板 `damage_resistance` > 0
    （她这里是 0.3）。

    只拿到比例、不知道对谁，等于没建模——审计第二道筛子对这个键本来就是**假
    通过**：`damage_resistance` 的键名只在 `operator/skill.py` 的映射表里出现过，
    战斗侧从来没人用它。这里把它接上（消费点见 `sim._species_resist`）。
    """
    for t in talents:
        eff = getattr(t, "effects", None)
        if eff is None:
            continue
        if getattr(eff, "resistance_species", "") and eff.damage_resistance > 0.0:
            return t
    return None


def is_summon_limit_talent(t: Talent) -> bool:
    if not t.has("cnt") or t.value("cnt") <= 0:
        return False
    desc = t.description or ""
    return "可以使用" in desc and any(w in desc for w in _SUMMON_WORDS)


#: 「最多同时部署 N 个」——**同时**上限，只在描述文字里。
_SIMULTANEOUS_RE = re.compile(r"最多同时部署\s*(\d+)\s*[个枚]")
#: 「最多拥有 N 枚」——望用的是这个措辞（棋子是"摆下去"，不叫部署）。
_OWNED_RE = re.compile(r"最多拥有\s*(\d+)\s*[枚个]")
#: 战术点：可露希尔「精准投放」的原文是
#: 「可以**在战术点召唤**指挥中心协助作战，其被击败后会在15秒后自动刷新；
#: 战术点效果范围随携带技能变化，效果范围内的友方单位视为自身的援军」。
#:
#: ⚠️ 判据必须用**游戏内正文**的措辞。PRTS 的模板提示词是「可部署战术点」，
#: 拿它当正则的第一次写法人人认不出来——天赋原文里根本没有"可部署"三个字
#: （2026-09-19 实测，被守卫 [54] 当场抓住）。她这条天赋**有 `cnt`=1**，但
#: `_SUMMON_WORDS` 里没有"战术点"，`"可以使用"` 也不在她的正文里，所以
#: 下面那套召唤物判据认不出，必须单列一支。
_TOKEN_DEPLOY_RE = re.compile(r"可以在战术点召唤")


@dataclass(frozen=True)
class SummonAllowance:
    """一名召唤者的召唤物额度。两个数是**两回事**，别混。

    :param pool: **可动用总量**，取自黑板 `cnt`，等于描述里的「可以使用 N 个」。
        它随**精英阶段**变（电弧/令：E0=3、E1=4、E2=5），是这一场里总共能拿出
        几个召唤物。
    :param simultaneous: **同时部署上限**。这个数**不在黑板里**，只在描述文字里，
        所以只能解析文字（见 `source`）。电弧/令恒为 3——它**不随精英阶段变**，
        与 `pool` 是完全不同的量。
    :param source: `simultaneous` 的出处：`"同时部署"` / `"拥有"` / `"回落 pool"`。
        **回落只发生在文字根本没写的时候**（深池/梅尔/衡沙），那时 `pool` 是
        唯一的数，只能用它，并在 `source` 里如实标出来。
    """

    pool: int
    simultaneous: int
    source: str
    talent: Talent


def find_summon_allowance(talents) -> SummonAllowance | None:
    """解析一名干员的召唤物额度；不是召唤者就返回 `None`。

    **不返回猜的默认值**——调用方要据此判断"这人到底是不是召唤者"，
    猜一个 1 会让非召唤者也悄悄放出东西来。

    为什么同时上限要走文字、不走 `token` 的 `maxDeployCount`：那个字段在
    令/深池/梅尔身上是 **1**（它们明明能放 3-5 个），在电弧身上是 3、望身上
    是 4/5/6——**同一个字段在不同 token 上语义不一致**，取它会**把令错压成 1 个**。
    2026-09-18 全表核验的对照表见 `docs/uncertainties.md` 的待裁定条目。
    """
    for t in talents or ():
        # **战术点**（可露希尔「精准投放」=「可以在战术点召唤指挥中心」）：
        # 她这条天赋**有 `cnt`=1**，但召唤物那套判据要正文里出现「可以使用」
        # 加「召唤物/棋子」，她两句都不占，所以认不出。战术点确实是玩家可部署
        # 单位，而且只有 1 个。没有这一支，可露希尔技2 的返费在实跑里永远够
        # 不着（战术点落不了场）。
        if _TOKEN_DEPLOY_RE.search(t.description or ""):
            return SummonAllowance(1, 1, "战术点召唤", t)
        if not is_summon_limit_talent(t):
            continue
        pool = int(t.value("cnt"))
        desc = t.description or ""
        m = _SIMULTANEOUS_RE.search(desc)
        if m:
            return SummonAllowance(pool, int(m.group(1)), "同时部署", t)
        m = _OWNED_RE.search(desc)
        if m:
            return SummonAllowance(pool, int(m.group(1)), "拥有", t)
        return SummonAllowance(pool, pool, "回落 pool", t)
    return None


@dataclass
class SnowField:
    """一个干员铺出来的一片雪。

    :param interval: 每隔多少秒积一层
    :param max_layers: 单格层数上限（`max_cast_cnt`）
    :param slow_per_layer: 每层减速比例（取黑板 `move_speed` 的绝对值）
    :param magic_scale: 踏入伤害倍率（`talent_magic_scale`）
    :param spread_cap: 技能开启后允许的总雪格数（`max_cast_tile_count`）；
        为 0 表示不扩散，只在她射程内积。
    """

    owner: str                        # 干员名，仅用于日志
    interval: float
    max_layers: int
    slow_per_layer: float
    magic_scale: float
    spread_cap: int = 0
    dot_scale: float = 0.0            # 技能2 的每秒伤害倍率
    #: 铺雪的干员本体（模拟器填），射程与攻击力都要问它
    operator: object = None
    timer: float = 0.0
    #: 格 → 层数
    layers: dict[Cell, int] = field(default_factory=dict)
    #: 格 → 第一个踏入的敌人 id；它离开时整格雪消失
    first_enemy: dict[Cell, int] = field(default_factory=dict)
    #: 敌人 id → 它上一帧所在的格（用来判"踏入"与"离开"）
    last_cell: dict[int, Cell] = field(default_factory=dict)
    spawned: int = 0                  # 累计积出的层数，便于核对

    # ------------------------------------------------------------ 积雪

    @property
    def max_tiles(self) -> int:
        return self.spread_cap if self.spread_cap > 0 else 0

    def tick(self, dt: float, ground_cells: list[Cell],
             neighbour_of=None) -> int:
        """推进计时，到点就往射程内的地面格加一层。返回本帧新增层数。"""
        if self.interval <= 0:
            return 0
        self.timer += dt
        added = 0
        while self.timer >= self.interval:
            self.timer -= self.interval
            added += self._cast(ground_cells, neighbour_of)
        return added

    def _cast(self, ground_cells: list[Cell], neighbour_of) -> int:
        added = 0
        for cell in ground_cells:
            added += self._add(cell)
        # 射程内都满层了才向外扩散（描述：超过 5 层时向周围扩散一层）
        if self.spread_cap > 0 and neighbour_of is not None:
            if all(self.layers.get(c, 0) >= self.max_layers for c in ground_cells):
                for cell in self._spread_frontier(neighbour_of):
                    if len(self.layers) >= self.spread_cap:
                        break
                    added += self._add(cell)
        return added

    def _spread_frontier(self, neighbour_of) -> list[Cell]:
        """已有雪格相邻的、还没雪的可走格，按距离由近及远。"""
        seen = set(self.layers)
        frontier: list[Cell] = []
        for cell in list(self.layers):
            for nxt in neighbour_of(cell):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return frontier

    def _add(self, cell: Cell) -> int:
        cur = self.layers.get(cell, 0)
        if cur >= self.max_layers:
            return 0
        if cell not in self.layers and self.spread_cap > 0 and len(self.layers) >= self.spread_cap:
            return 0
        self.layers[cell] = cur + 1
        self.spawned += 1
        return 1

    # ------------------------------------------------------------ 敌人

    def slow_at(self, cell: Cell) -> float:
        """这一格对移速的乘数（1.0 = 不减速）。"""
        n = self.layers.get(cell, 0)
        if n <= 0:
            return 1.0
        return max(0.05, 1.0 - self.slow_per_layer * n)

    def enter(self, enemy_id: int, cell: Cell, atk: float,
              damage_fn) -> float:
        """敌人踏入某格：判"踏入"、记录首敌、结算踏入伤害。

        :param damage_fn: `(raw_amount) -> 实际伤害`，由模拟器提供（要过法抗）。
        :return: 本次造成的伤害
        """
        prev = self.last_cell.get(enemy_id)
        self.last_cell[enemy_id] = cell
        if prev == cell:
            return 0.0
        # 离开旧格：如果自己是那格的"第一个敌人"，整格雪消失
        if prev is not None and self.first_enemy.get(prev) == enemy_id:
            self.layers.pop(prev, None)
            self.first_enemy.pop(prev, None)
        if self.layers.get(cell, 0) <= 0:
            return 0.0
        self.first_enemy.setdefault(cell, enemy_id)
        return damage_fn(self.magic_scale * atk)

    def leave_all(self, enemy_id: int) -> None:
        """敌人离场（死亡/漏怪）时调用：它踩过的格按首敌规则清雪。"""
        prev = self.last_cell.pop(enemy_id, None)
        if prev is not None and self.first_enemy.get(prev) == enemy_id:
            self.layers.pop(prev, None)
            self.first_enemy.pop(prev, None)

    def draw(self, width: int, height: int) -> str:
        """把雪画出来（层数用数字，空格表示无雪）。y 向下为正，顺序打印即所见。"""
        lines = []
        for y in range(height):
            lines.append(" ".join(str(self.layers.get((x, y), 0)) if (x, y) in self.layers
                                  else "." for x in range(width)))
        return "\n".join(lines)
