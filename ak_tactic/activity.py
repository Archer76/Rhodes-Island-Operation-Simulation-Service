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

    def to_dict(self) -> dict:
        return {"key": self.key, "name": self.name, "status": self.status,
                "note": self.note, "source": self.source}


# --------------------------------------------------------------------------
# 登记表。key 一律用数据里的**原样**写法（装置用 trap_*，黑板用**前缀**含点，
# runes 用键名），不要改写、不要去掉前缀的点——本文件的判据就是字符串相等。
# --------------------------------------------------------------------------

DEVICE_REGISTRY: dict[str, Entry] = {
    "trap_139_dhtl": Entry(
        "trap_139_dhtl", "阻流阀", DONE,
        "3 秒建成，自身地块不再是田地、连片由此重划",
        source="prts.wiki 阻流阀 / 关卡 predefines.tokenInsts"),
    "trap_140_dhsb": Entry(
        "trap_140_dhsb", "泵站", DONE,
        "泵水；清澈降【最大】、受污两者都抬，范围按前方格数",
        source="prts.wiki 泵站 / 装置机制字段"),
    "trap_146_dhdcr": Entry(
        "trap_146_dhdcr", "天桩（装置）", TODO,
        "退场时所在地块的天桩装置死亡；天桩-甲是本装置释放的**敌人**，"
        "其监测/激活两形态见 ENEMY_BB_REGISTRY 的 Reborning 邻近项",
        source="prts.wiki 天桩-甲 / 天桩(装置)"),
}

#: 敌人黑板键的**前缀**（含结尾的点）。前缀是分机制的自然粒度：
#: 同一机制下各键（.duration/.interval/.value）必然同生同死。
ENEMY_BB_REGISTRY: dict[str, Entry] = {
    "Reborning.": Entry(
        "Reborning.", "重生期充能（怀黍离）", TODO,
        "重生期间每 interval 秒若所在田地病害值>0 则降该地块 |value| 点并获得 1 层充能；"
        "重生后防御力 +(def_add×层数)%、普攻附加攻击力 (damage_magic×层数)% 法术伤害",
        source="prts.wiki 瘴 / 鄙瘴 天赋；关卡敌方 talentBlackboard"),
    "DeathPassive.": Entry(
        "DeathPassive.", "死亡被动（召唤/污染）", TODO,
        "死后释放 token_key 指定的单位，cnt 个；本活动表现为「被击倒后对田地造成病害污染」",
        source="prts.wiki 秽 / 除秽 / 肮 / 厌肮 能力"),
    "AuraHit.": Entry(
        "AuraHit.", "光环命中", TODO,
        "hp_ratio 控制光环触发时的生命比例",
        source="关卡敌方 talentBlackboard"),
    "Passive.": Entry(
        "Passive.", "被动（范围/附加值）", TODO,
        "range_radius 光环半径、extra_value 附加量",
        source="关卡敌方 talentBlackboard"),
    "SpeedUp.": Entry(
        "SpeedUp.", "加速（移速增益）", TODO,
        "cooldown 触发间隔 / duration 持续 / move_speed 幅度",
        source="关卡敌方 talentBlackboard"),
    "Passive_Hit.": Entry(
        "Passive_Hit.", "受击被动（「祟」第一形态）", TODO,
        "被攻击时按 value 叠层、max_stack_cnt 封顶，改变 atk/def/move_speed 等",
        source="prts.wiki 祟 / 敌方 talentBlackboard"),
    "PassiveM2.": Entry(
        "PassiveM2.", "明识形态被动（「祟」第二形态）", TODO,
        "属性改写 + 标记 + dhnzzh_clean_water 系列（无病害水流中的减益）",
        source="prts.wiki 祟 / 敌方 talentBlackboard"),
}

RUNES_REGISTRY: dict[str, Entry] = {
    "env_system_new": Entry(
        "env_system_new", "环境系统：田地 / 病害值", DONE,
        "五个结算参数；按 difficultyMask 消歧",
        source="关卡 runes[].blackboard"),
    "enemy_attribute_mul": Entry(
        "enemy_attribute_mul", "敌人属性乘数", DONE,
        "按难度缩放敌人属性；已由 EnemyLibrary 读入",
        source="关卡 runes[].blackboard"),
    "global_lifepoint": Entry(
        "global_lifepoint", "全局生命点改写", DONE,
        "覆写关卡生命数；已由 load_stage 读入",
        source="关卡 runes[].blackboard"),
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
        "按难度缩放敌方技能黑板；未读入",
        source="关卡 runes[].blackboard"),
    "enemy_talent_blackb_mul": Entry(
        "enemy_talent_blackb_mul", "敌方天赋黑板乘数", TODO,
        "按难度缩放敌方天赋黑板；未读入。⚠ 与 Reborning 的数值可能有交互，"
        "实现充能时须先确认本关是否带这个 rune",
        source="关卡 runes[].blackboard"),
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
