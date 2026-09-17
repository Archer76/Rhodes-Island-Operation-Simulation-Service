# -*- coding: utf-8 -*-
"""活动机制完整性盘点。

【为什么需要这一层】
地图机制不像干员/敌人那样有稳定的数据表——每个活动都会新引入一批装置、敌人黑板键、
runes 键。若只是"遇到一个做一个"，**没人知道还剩多少没做**，而"看起来跑通了"的关卡
与"其实漏了半个机制"的关卡在输出上完全没有区别。

本模块把「解析完整」变成可检查的事：对给定活动枚举**全部**承载机制的实体
（装置 / 敌人黑板键 / runes 键），逐个登记状态，任何**既没实现、也没登记**的东西
一律判为 UNKNOWN，由自检拦下。

【三种状态，含义必须分清】
* ``DONE``    —— 已实现并接进模拟器。
* ``TODO``    —— 已识别、已有明确来历（必须写明 `source`），但尚未实现。
                  **TODO 会出现在报告里，是给人看的待办，不是"通过"。**
* ``NONE``    —— 确认不需要实现（写明理由），例如纯定义性条目。

【纪律】
* 未登记 → UNKNOWN → 自检红。**不许把未知悄悄归到 TODO**——那等于把守卫关掉。
* ``TODO`` 必须有 ``source``（正文取自哪一页/哪个键），否则后来人无从下手。
* 状态是**声明**不是**探测**：改完代码要同时把这里的状态改掉，两处对不上就是 bug。
"""

from __future__ import annotations

import collections
import glob
import os
from dataclasses import dataclass, field

__all__ = [
    "DONE", "TODO", "NONE", "UNKNOWN",
    "Entry", "ActivityReport",
    "DEVICE_REGISTRY", "ENEMY_BB_REGISTRY", "RUNES_REGISTRY",
    "audit_activity", "activity_stages", "KNOWN_ACTIVITIES",
]

DONE = "done"
TODO = "todo"
NONE = "none"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Entry:
    key: str
    name: str
    status: str
    note: str = ""
    source: str = ""
    #: 这条状态**在哪段代码里兑现**：`模块路径:符号名`。
    #:
    #: 为什么要它：本表的状态是**声明**，而声明与代码对不上是这里最容易
    #: 出的错——`enemy_attribute_mul` 与 `global_lifepoint` 两条就曾长期
    #: 标着 DONE，而代码里根本没有它们的消费者，**没有任何自检拦得住**
    #: （`check_activity.py` 原先只查 DONE 的装置有没有常量，不查 rune）。
    #: 有了锚点，`check_activity.py` 就能要求每个 DONE 条目都指到一个真实
    #: 符号，且该 key 确实出现在那段代码里。TODO 可以留空。
    anchor: str = ""

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "status": self.status,
                "note": self.note, "source": self.source, "anchor": self.anchor}


# --------------------------------------------------------------------------
# 登记表。key 一律用数据里的**原样**写法（装置用 trap_*，黑板用**前缀**含点，
# runes 用键名），不要改写、不要去掉前缀的点——本文件的判据就是字符串相等。
# --------------------------------------------------------------------------

DEVICE_REGISTRY: dict[str, Entry] = {
    "trap_139_dhtl": Entry(
        "trap_139_dhtl", "阻流阀", DONE,
        "3 秒建成，自身地块不再是田地、连片由此重划",
        source="prts.wiki 阻流阀 / 关卡 predefines.tokenInsts",
        anchor="ak_tactic.battle.devices:BLOCKER_KEY"),
    "trap_140_dhsb": Entry(
        "trap_140_dhsb", "泵站", DONE,
        "泵水；清澈降【最大】、受污两者都抬，范围按前方格数",
        source="prts.wiki 泵站 / 装置机制字段",
        anchor="ak_tactic.battle.devices:PUMP_KEY"),
    "trap_146_dhdcr": Entry(
        "trap_146_dhdcr", "天桩（装置）", TODO,
        "装置本体已取到正文（原先只知道技能正文为空）：**登场时在自身位置"
        "以预设路径召唤一名天桩-甲（或失控天桩-甲）**，且**于所在地块的"
        "天桩-甲退场时死亡**（不可撤回、不可被玩家查看、生命 100、阵营敌方）。"
        "未做的是它召唤出来的那两个敌人：天桩-甲 50000 血，**监测形态**下无敌"
        "不死、自缚、生命百分比与所在地块病害值同步（1%=1 点，不致死），"
        "≥70 闪红、首次 ≥100 激活；**激活形态**每秒受自身最大生命 1% 真伤、"
        "每损失 10% 生命延迟 1~1.5 秒召唤 3 个天桩-乙（1.0 边长正方形内）。"
        "天桩-乙会扑向射程内第一个我方单位、命中时在目标地块召唤「身上的天标」。",
        source="prts.wiki 天桩(装置) / 天桩-甲 / 天桩-乙",
        anchor="ak_tactic.battle.devices:PILE_KEY"),
}

#: 敌人黑板键的**前缀**（含结尾的点）。前缀是分机制的自然粒度：
#: 同一机制下各键（.duration/.interval/.value）必然同生同死。
ENEMY_BB_REGISTRY: dict[str, Entry] = {
    "Reborning.": Entry(
        "Reborning.", "重生期充能 / 召唤（怀黍离）", DONE,
        "两条**互不相干**的分支，判据不同、别混："
        "① 充能（瘴 / 鄙瘴）——重生期间每 interval 秒若所在田地病害值>0 则降该地块 "
        "|value| 点并获得 1 层充能，重生后防御力 +(def_add×层数)%、普攻附加攻击力 "
        "(damage_magic×层数)% 法术伤害；"
        "② 召唤（「祟」）——重生期间每 interval 秒在自己脚下召唤 cnt 个 enemy_key，"
        "另有 dhnzzh_reborn_c2 第二路。"
        "⚠ 「祟」有 interval 但没有 value：按「有 interval 就是充能」去读会把它算成"
        "「每次扣 0 点病害值」的充能怪，召唤整支静默消失",
        source="prts.wiki 瘴 / 鄙瘴 / 祟 天赋；关卡敌方 talentBlackboard",
        anchor="ak_tactic.gamedata.enemy:_REBORN_SPECS"),
    "DeathPassive.": Entry(
        "DeathPassive.", "被击倒时给予可部署装置", TODO,
        "田鼷飞贼 / 田鼷大盗：被击倒时死亡爆炸，予我方可部署的 token_key 装置 ×cnt"
        "（本活动是 trap_139_dhtl 阻流阀 ×2）。"
        "**已记账未生效**：`BattleResult.device_tokens` 记下了「打死了几个、该得几个」，"
        "但模拟器没有**部署装置**这一层——部署计划只收干员，装置全是关卡预先摆好的。"
        "所以这条不算实现：账是对的，效果无处落地。",
        source="prts.wiki 田鼷飞贼 / 田鼷大盗 天赋；黑洞 token_key",
        anchor="ak_tactic.battle.sim:BattleResult"),
    "AuraHit.": Entry(
        "AuraHit.", "进入阻流阀范围立刻真伤", TODO,
        "田鼷力士 / 猛士 / 飞贼 / 大盗：进入阻流阀**半径 0.5**范围内时立刻对其造成"
        "**目标最大生命值** 50%/70% 的真实伤害（比例相对阻流阀、不是相对自己）。"
        "未做：需要「阻流阀有生命、会被摧毁」这一层——现在装置只是一张静态表，"
        "没有血量也没有被摧毁后**把田地还原**的分支。",
        source="prts.wiki 田鼷力士 / 猛士 / 飞贼 / 大盗 天赋",
        anchor="ak_tactic.gamedata.enemy:AURA_HIT_RADIUS"),
    "Passive.": Entry(
        "Passive.", "被击倒时污染田地", DONE,
        "秽 / 除秽（+5）、肮 / 厌肮（+15）：被击倒时令**阻挡自身的单位(被阻挡时)/"
        "自身(未被阻挡时)**半径 range_radius(=1.0) 范围内的田地地块病害值 +extra_value。"
        "半径按**圆**算：1.0 恰好够到上下左右四邻、够不到斜角（√2），共十字五格",
        source="prts.wiki 秽 / 除秽 / 肮 / 厌肮 天赋；关卡敌方 talentBlackboard",
        anchor="ak_tactic.gamedata.enemy:mech_fields"),
    "SpeedUp.": Entry(
        "SpeedUp.", "受击且未被阻挡时加速", DONE,
        "田鼷四兄弟：受到伤害且**未被阻挡**时获得 move_speed×100% 移速增益、"
        "持续 duration 秒，被阻挡时**立刻解除**，获得后 cooldown 秒内不能再次获得。"
        "⚠ 增益写进 `haste_multiplier` 而**不并进 `speed_multiplier`**：后者被积雪"
        "天赋每帧重写，并进去会被当场抹掉且不报错",
        source="prts.wiki 田鼷力士 / 猛士 / 飞贼 / 大盗 天赋；关卡敌方 talentBlackboard",
        anchor="ak_tactic.gamedata.enemy:mech_fields"),
    "Passive_Hit.": Entry(
        "Passive_Hit.", "受击蜕皮（「祟」混沌形态）", DONE,
        "每受到 cnt 次伤害（4 次，**次数不是伤害量**）且蜕皮未达 max_stack_cnt(=80) 时"
        "叠一层：攻击力+atk(-40)、防御力+def(-50)、法抗+res(-1)、移速+move_speed(0.01)，"
        "并令阻挡者(被阻挡时)/自身(未被阻挡时)半径 1.0 内田地病害值 +value(=4)；"
        "每 other_cnt(=10) 层重量等级 −1。"
        "⚠ 黑板里还有一条 `extra_value = -0.001`**没有任何正文提到**，只登记不使用",
        source="prts.wiki 祟 天赋；关卡敌方 talentBlackboard",
        anchor="ak_tactic.gamedata.enemy:mech_fields"),
    "PassiveM2.": Entry(
        "PassiveM2.", "明识形态（「祟」重生后）", DONE,
        "重生归来：攻击力 -60%、防御力 -70%、法抗 -30、移速 +200%、普攻变 2 连击、"
        "获得 duration_invic(=5) 秒无敌；受到伤害时**标记伤害来源**，被标记者退场时"
        "若自身未被阻挡则半径 1.0 内田地病害值 +dhnzzh_passive_mark[host].value；"
        "位于水田且本格病害值=0（或处于清澈泵站生效范围内）时防御再 -15%~-20%、"
        "法抗 -30、**失去移速加成**。"
        "⚠ 两处读数存疑：①「可进行远程攻击」但数据里没有射程，故只在本来就有射程时转远程；"
        "② 标记退场污染的**圆心**取祟自身（另一读法是以退场干员为中心），见 "
        "docs/uncertainties.md",
        source="prts.wiki 祟 天赋；关卡敌方 talentBlackboard",
        anchor="ak_tactic.gamedata.enemy:mech_fields"),
}

RUNES_REGISTRY: dict[str, Entry] = {
    "env_system_new": Entry(
        "env_system_new", "环境系统：田地 / 病害值", DONE,
        "五个结算参数；按 difficultyMask 消歧",
        source="关卡 runes[].blackboard",
        anchor="ak_tactic.battle.environment:RUNES_KEY"),
    "enemy_attribute_mul": Entry(
        "enemy_attribute_mul", "敌人属性乘数", DONE,
        "按难度缩放敌人属性（atk / def / max_hp），可另带 `enemy` 键点名一批敌人；"
        "同键多条**依次相乘**。作用在 `enemy_at` 的出口上、**改副本不改库**。"
        "老活动的同一机制叫 `ebuff_attribute`（黑板结构相同），两个名字都认",
        source="关卡 runes[].blackboard（act31side_ex01~ex08 的四星档）",
        anchor="ak_tactic.battle.stage_mul:ATTR_MUL_KEY"),
    "global_lifepoint": Entry(
        "global_lifepoint", "全局生命点改写", DONE,
        "**覆写关卡生命数**（八关 EX 的四星档都改成 1，而关卡文件自己的 "
        "maxLifePoint 是 3、普通与四星两份**都是 3**）。"
        "老活动的同一机制叫 `gbuff_lifepoint`（黑板结构相同），两个名字都认。"
        "⚠ 先前这条标着 DONE 却**没有任何消费者**",
        source="关卡 runes[].blackboard",
        anchor="ak_tactic.battle.stage_mul:LIFEPOINT_KEY"),
    "cbuff_cost_recovery": Entry(
        "cbuff_cost_recovery", "费用回复速度乘数", DONE,
        "`scale` = 回复速度倍率（四星档常见 2），它改的是**每点费用几秒**，故实现里是**除**。"
        "⚠ 这一条**不在怀黍离的 runes 里**（1-7 的四星档才用），登记在此是因为"
        "本模块的乘数层一并收它；`audit_activity('act31side')` 不会枚举到它",
        source="关卡 runes[].blackboard（main_01-07 的四星档）",
        anchor="ak_tactic.battle.stage_mul:COST_MUL_KEY"),
    "global_token_cnt_add": Entry(
        "global_token_cnt_add", "装置数量上限增量", NONE,
        "只影响部署计数上限，不改变战斗结算",
        source="关卡 runes[].blackboard"),
    "level_predefines_enable": Entry(
        "level_predefines_enable", "开关预置单位", NONE,
        "开关位，无自身效果；预置单位已由 predefines 解析",
        source="关卡 runes[].blackboard"),
    "level_hidden_group_enable": Entry(
        "level_hidden_group_enable", "开关隐藏波次组", NONE,
        "开关位，无自身效果",
        source="关卡 runes[].blackboard"),
    "enemy_skill_blackb_mul": Entry(
        "enemy_skill_blackb_mul", "敌方技能黑板乘数", TODO,
        "黑板已按 `enemy` + `skill`(prefabKey) 点名改写（`act31side_ex04` 给"
        "`enemy_1393_dhele_2` 的 `Drink` 把 atk_scale_magic 1.3 倍 → 1.04），"
        "**但改写结果没有消费者**：模拟器不驱动敌方技能（既没有敌方 SP 回转、"
        "也没有技能效果结算）。数据对了、结算没变，故不算实现",
        source="关卡 runes[].blackboard",
        anchor="ak_tactic.gamedata.enemy:rescale_skill_blackboard"),
    "enemy_talent_blackb_mul": Entry(
        "enemy_talent_blackb_mul", "敌方天赋黑板乘数", DONE,
        "按 `enemy` 点名一批敌人，其余键是「天赋黑板键 → 系数」。"
        "`act31side_ex07` 给 `enemy_1390_dhsbr_2|enemy_1392_dhshld_2` 的 "
        "`Passive.extra_value` ×2，即被击倒时的田地污染由 +5/+15 变 **+10/+30**。"
        "⚠ 乘完**必须重算派生字段**（`derive_blackboard_fields`）——否则乘数只落在一张"
        "没人再读的黑板表上，机制实际没变",
        source="关卡 runes[].blackboard",
        anchor="ak_tactic.battle.stage_mul:TALENT_MUL_KEY"),
}


# --------------------------------------------------------------------------
# 盘点
# --------------------------------------------------------------------------

KNOWN_ACTIVITIES = {"act31side": "怀黍离"}


def activity_stages(activity: str, cache_root: str | None = None) -> dict:
    """取活动目录下所有能加载的关卡 {level_id: Stage}。"""
    from .gamedata.stage import load_stage                          # noqa: PLC0415

    root = cache_root or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "data", "gamedata", "map.ark-nights.com", "levels", "activities")

    # 活动名 → 目录名不是一一对应（act31side 就是目录名），故先按目录找。
    cand = [os.path.join(root, activity)]
    if not os.path.isdir(cand[0]):
        hits = glob.glob(os.path.join(root, f"*{activity}*"))
        cand = [h for h in hits if os.path.isdir(h)]
    out: dict = {}
    for d in cand:
        for p in sorted(glob.glob(os.path.join(d, "level_*.json"))):
            lid = os.path.basename(p)[len("level_"):-len(".json")]
            try:
                out[lid] = load_stage(lid)
            except Exception:                                       # noqa: BLE001
                continue
    return out


@dataclass
class ActivityReport:
    activity: str
    stages: int = 0
    devices: dict = field(default_factory=dict)          # key -> 出现次数
    enemy_bb: dict = field(default_factory=dict)         # 前缀 -> {敌人: 键}
    runes: dict = field(default_factory=dict)            # key -> 出现次数
    enemies: dict = field(default_factory=dict)          # enemy_id -> 次数
    unknown: list = field(default_factory=list)          # [(kind, key)]
    todo: list = field(default_factory=list)             # [Entry]

    def summary(self) -> str:
        lines = [f"活动 {self.activity}：{self.stages} 关、{len(self.enemies)} 种敌人、"
                 f"{len(self.devices)} 种装置、{len(self.runes)} 种 runes、"
                 f"{len(self.enemy_bb)} 类黑板机制"]
        lines.append(f"  已实现 {self._n(DONE)} / 待实现 {self._n(TODO)} / "
                     f"不需要 {self._n(NONE)} / **未登记 {len(self.unknown)}**")
        for e in self.todo:
            lines.append(f"    [待实现] {e.name}（{e.key}）—— {e.source}")
        for kind, key in self.unknown:
            lines.append(f"    [!! 未登记] {kind} {key}")
        return "\n".join(lines)

    def _n(self, status: str) -> int:
        seen = [e for e in self._entries() if e.status == status]
        return len({e.key for e in seen})

    def _entries(self) -> list:
        out = []
        for k in self.devices:
            out.append(DEVICE_REGISTRY.get(
                k, Entry(k, k, UNKNOWN, "装置未登记")))
        for p in self.enemy_bb:
            out.append(ENEMY_BB_REGISTRY.get(
                p, Entry(p, p, UNKNOWN, "黑板前缀未登记")))
        for k in self.runes:
            out.append(RUNES_REGISTRY.get(k, Entry(k, k, UNKNOWN, "rune 未登记")))
        return out


def audit_activity(activity: str = "act31side", cache_root: str | None = None,
                   *, with_enemies: bool = True) -> ActivityReport:
    """盘点一个活动里**全部**承载机制的实体，并标出未登记项。"""
    from .battle.devices import parse_devices                       # noqa: PLC0415

    rep = ActivityReport(activity=activity)
    stages = activity_stages(activity, cache_root)
    rep.stages = len(stages)

    dev: collections.Counter = collections.Counter()
    rk: collections.Counter = collections.Counter()
    en: collections.Counter = collections.Counter()
    for st in stages.values():
        for d in parse_devices(st):
            dev[d.key] += 1
        for r in (st.raw.get("runes") or []):
            rk[r.get("key")] += 1
        for k, n in st.enemy_counts().items():
            en[k] += n
    rep.devices = dict(dev.most_common())
    rep.runes = dict(rk.most_common())
    rep.enemies = dict(en.most_common())

    if with_enemies:
        from .gamedata.enemy import EnemyLibrary                     # noqa: PLC0415
        lib = EnemyLibrary()
        pref: dict = {}
        for eid in sorted(en):
            try:
                bb = getattr(lib.get(eid), "talent_blackboard", {}) or {}
            except Exception:                                       # noqa: BLE001
                continue
            for k in bb:
                p = k.split(".")[0] + "." if "." in k else k
                pref.setdefault(p, {}).setdefault(eid, []).append(k)
        rep.enemy_bb = pref

    for kind, keys, table in (("装置", rep.devices, DEVICE_REGISTRY),
                              ("黑板", rep.enemy_bb, ENEMY_BB_REGISTRY),
                              ("rune", rep.runes, RUNES_REGISTRY)):
        for k in keys:
            if k not in table:
                rep.unknown.append((kind, k))
            elif table[k].status == TODO:
                rep.todo.append(table[k])
    return rep
