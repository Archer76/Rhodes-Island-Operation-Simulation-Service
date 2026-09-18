"""敌人数据：图鉴（名字、描述）+ 属性库（血量、攻防、抗性、移速、重量）。

两个来源：

* `excel/enemy_handbook_table.json` —— 图鉴。名字、编号（如 `B2`）、描述、
  伤害类型。**不含数值。**
* `levels/enemydata/enemy_database.json` —— 属性库（约 15 MB）。按 `Key`
  索引，每个敌人挂着若干「等级」档，每档一份完整 enemyData。

属性库的字段是 Unity 序列化的形状，每个值都包一层 `{m_defined, m_value}`：
`m_defined` 为 false 表示这一档没有覆写该字段，要沿用更低优先级的值。多个
等级档之间也是这样从低到高合并的——theresa.wiki 的前端做的就是这件事。
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from .source import GameDataSource, GamedataError

#: `enemyData.attributes` 里要保留的数值字段。
_ATTR_FIELDS = (
    "maxHp", "atk", "def", "magicResistance",
    "moveSpeed", "attackSpeed", "baseAttackTime",
    "massLevel", "hpRecoveryPerSec", "spRecoveryPerSec", "respawnTime",
    "tauntLevel", "blockCnt", "maxDeployCount",
)

#: 挂在 `enemyData` 顶层、不在 attributes 下的字段。
#: 这三项很容易误当成属性去 attributes 里找，然后永远取到 None。
_TOP_FIELDS = ("lifePointReduce", "rangeRadius", "levelType", "motion", "applyWay")

_IMMUNE_FIELDS = (
    "stunImmune", "silenceImmune", "sleepImmune", "frozenImmune",
    "levitateImmune", "fearedImmune", "palsyImmune", "attractImmune",
    "teleportImmune", "groundBoundImmune", "disarmedCombatImmune",
)

#: 等级类型代号，来自游戏内约定。
LEVEL_TYPES = {0: "普通", 1: "精英", 2: "领袖", 3: "精英", "ELITE": "精英",
               "BOSS": "领袖", "NORMAL": "普通"}

#: 关卡原始字段名 → `EnemyStats` 字段名。给 `with_overwrite` 用：
#: 关卡自带的敌人定义（`overwrittenData`）是**原始口径**，字段名与库里不同。
_ATTR_TO_FIELD = {
    "maxHp": "max_hp", "atk": "atk", "def": "defense",
    "magicResistance": "magic_resistance", "moveSpeed": "move_speed",
    "attackSpeed": "attack_speed", "baseAttackTime": "base_attack_time",
    "massLevel": "weight", "lifePointReduce": "life_point_reduce",
    "rangeRadius": "range_radius", "hpRecoveryPerSec": "hp_recovery_per_sec",
}


#: 重生（倒下后归来）的键拼法。**只收在 gamedata 里逐条核过的**——
#: 之前写死成 `Reborn.reborn_duration` 一个键，漏掉了整整一类敌人。
#:
#: 每项 = (前缀, 间隔键, 血量比例键或 None)。两套拼法在真实数据里并存：
#:
#:   * 死志的凝结（SR-EX-8 BOSS）：`Reborn.reborn_duration` = 10 /
#:     `Reborn.max_hp_ratio` = 1 → 倒下 10 秒后**满血归来**。
#:     ⚠ 它同时还有 `Reborn.hp_ratio` = 0.01，那是**另一个量**，不是
#:     归来时的血量比例，别顺手换过去。
#:   * 怀黍离的瘴 / 鄙瘴 = `Reborning.duration` 5；「祟」= 40。
#:     两套里都没有比率键 → 默认满血（原文写「恢复100%生命值」）。
#:
#: ⚠ 这只是**已核实**的两套，全库还有 `reborn.` / `M0Reborn.` /
#: `TalentReborn.` 等前缀（在 prts 侧的敌人库里观察到，拼法与 gamedata
#: 未必相同）。**扩充前必须在 gamedata 上验一次**——两侧拼法不一致。
_REBORN_SPECS: tuple[tuple[str, str, str | None], ...] = (
    ("Reborn.", "Reborn.reborn_duration", "Reborn.max_hp_ratio"),
    ("Reborning.", "Reborning.duration", None),
)


def reborn_fields(bb: dict) -> dict:
    """从天赋黑板解出 `EnemyStats` 的重生与充能字段。

    返回的是可直接 `**` 展开进构造调用的字典。取不到就是「不重生」，
    一律给默认值而不是 None——上层不必再判。
    """
    empty = {
        "reborn_count": 0, "reborn_duration": 0.0, "reborn_hp_ratio": 1.0,
        "reborn_prefix": "", "reborn_interval": 0.0, "reborn_pollut": 0.0,
        "reborn_def_add": 0.0, "reborn_damage_magic": 0.0,
        "reborn_summons": (),
    }
    for prefix, dur_key, ratio_key in _REBORN_SPECS:
        if dur_key not in bb:
            continue
        # 数据里没有明写重生次数，按「一次」建模——这是唯一有旁证
        # （TalentReborn 是一次性触发）的读法，且次数越多结论越保守。
        out = dict(empty)
        out["reborn_count"] = 1
        out["reborn_duration"] = float(bb.get(dur_key) or 0.0)
        out["reborn_hp_ratio"] = (
            float(bb.get(ratio_key) or 1.0) if ratio_key else 1.0)
        out["reborn_prefix"] = prefix
        # 充能四项挂在同一前缀下；少任何一项就当没有充能机制，
        # 不做「缺一项按 0 算」——那会产出「每次都扣 0 点病害值却照拿层数」。
        if f"{prefix}interval" in bb and f"{prefix}value" in bb:
            out["reborn_interval"] = float(bb.get(f"{prefix}interval") or 0.0)
            # `value` 存的是 **-10**（原文「降低此地块10点病害值」），
            # 取绝对值当正数用，动作方向由调用方决定。
            out["reborn_pollut"] = abs(float(bb.get(f"{prefix}value") or 0.0))
            out["reborn_def_add"] = float(bb.get(f"{prefix}def_add") or 0.0)
            out["reborn_damage_magic"] = float(
                bb.get(f"{prefix}damage_magic") or 0.0)
        # ---- 另一支：重生期间**按间隔召唤**
        #
        # 与充能那支互不相干，判据也不同（充能要 `interval` + `value`，
        # 召唤要 `interval` + `cnt` + `enemy_key`）——「祟」两样都有 interval，
        # 但没有 `value`，若按「有 interval 就是充能」去读，它会被算成
        # 「每次扣 0 点病害值」的充能怪，召唤整支消失。
        out["reborn_summons"] = _reborn_summons(bb, prefix)
        return out
    return empty


def _reborn_summons(bb: dict, prefix: str) -> tuple:
    """重生期间要按间隔召唤什么。返回 `((间隔秒, 个数, 敌人 id), …)`。

    主召唤写在 `{prefix}interval` / `{prefix}cnt` / `{prefix}enemy_key`；
    第二路写在 `{prefix}dhnzzh_reborn_c2.*`（「祟」的另一只随从）。
    两者都是「在自身位置 1.0 边长正方形范围内随机位置召唤」——
    1.0 边长恰好覆盖脚下那一格，故这里只取脚下格，不做随机
    （模拟器要可复现，见 docs 里的确定性约定）。

    没有 `enemy_key` 就没有召唤（瘴 / 鄙瘴正如此：它们只有充能那一支）。
    """
    out = []
    specs = [(prefix, prefix), (f"{prefix}dhnzzh_reborn_c2.", f"{prefix}dhnzzh_reborn_c2.")]
    for _, pre in specs:
        key = bb.get(f"{pre}enemy_key")
        if not isinstance(key, str) or not key.strip():
            continue
        itv = bb.get(f"{pre}interval")
        try:
            itv = float(itv or 0.0)
        except (TypeError, ValueError):
            continue
        if itv <= 0:
            continue
        try:
            cnt = int(float(bb.get(f"{pre}cnt") or 0))
        except (TypeError, ValueError):
            cnt = 0
        if cnt <= 0:
            continue
        out.append((itv, cnt, key.strip()))
    return tuple(out)


#: 「进入阻流阀半径 `AURA_HIT_RADIUS` 范围内时立刻对其造成…」。
#: **0.5 写在正文里、不在黑板上**（`AuraHit.hp_ratio` 是伤害比例，
#: 半径只出现在天赋文字里），所以它只能作为常量记在这里。
AURA_HIT_RADIUS = 0.5

#: 敌人天赋黑板上的**机制前缀** ↔ 它们各自需要哪些键。
#:
#: 登记粒度按前缀（与 `activity.py` 的登记表同一粒度）：同一前缀下各键
#: 必然同生同死。**每一项都在 gamedata 的怀黍离敌人上逐键核过**
#: （`enemy_1390_dhsbr` 秽 / `1396_dhdts` 田鼷力士 / `1550_dhnzzh` 「祟」…），
#: 不是照着 prts.wiki 的写法抄的——两侧拼法不一致（见 `_REBORN_SPECS`）。
#:
#: 键一律写全（含前缀的点），因为黑板就是一张平表。
_MECH_PREFIXES: tuple[str, ...] = (
    "Passive.", "DeathPassive.", "AuraHit.", "SpeedUp.",
    "Passive_Hit.", "PassiveM2.", "CheckAwake.",
)


def _bb_float(bb: dict, key: str, default: float = 0.0) -> float:
    v = bb.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


#: 「技能攻击」类敌人的**正文规格**，按技能 `prefabKey` 点名。
#:
#: 为什么要有这张表：技能黑板只给得出两个数（`atk_scale_magic` / `value`），
#: 而"打几个、打谁、怎么分摊"全在正文里。项目纪律是**不编数**：正文写了就
#: 按正文写死，并让自检去核那段正文（`check_enemy_formula.py` §技能攻击）。
#:
#: 原文（prts 图鉴「玷 / 勿玷」天赋 + 技能 0「污」）：
#:   「不进行远程普通攻击」
#:   「攻击场上 1 名部署于地面的我方单位，对目标及其周围 4 格的单位造成
#:     攻击力 100% 的物理伤害；自身位于病害值>0 的田地地块时，当次攻击额外
#:     附加攻击力 80% 的法术普通伤害，且令目标地块病害值+5」
PROSE_SKILL_ATTACK: dict[str, dict[str, Any]] = {
    "Drink": {
        "scale_phys": 1.0,      # 「攻击力100%的物理伤害」
        "targets": 1,           # 「攻击场上1名…我方单位」
        "cross": 1,             # 「目标及其周围4格」= 十字（曼哈顿距离 1）
        "ground_only": True,    # 「部署于地面的我方单位」
        "no_normal_ranged": True,   # 天赋「不进行远程普通攻击」
    },
}


def _bb_int(bb: dict, key: str, default: int = 0) -> int:
    return int(_bb_float(bb, key, float(default)))


def skill_attack_fields(skills_raw) -> dict:
    """由**技能**（`skills_raw`）解出「技能攻击」那一组字段。

    【结构化那半】技能 `Drink`（图鉴技能 0「污」）的 blackboard 只有两个键，
    两个都用上：

    * ``atk_scale_magic`` = 0.8 —— 「当次攻击额外附加攻击力 80% 的法术普通伤害」
      的**倍率**。ex04 四星档的 rune `enemy_skill_blackb_mul` 把它 ×1.3 → 1.04。
    * ``value`` = 5 —— 「令目标地块病害值 +5」的那个 5。
    * 另外 `initCooldown`（7）与 `baseAttackTime`（7）就是首次出手时刻与间隔。

    【正文那半】prts 图鉴「玷 / 勿玷」的天赋与技能 0 原文：

    > 天赋：**不进行远程普通攻击**
    > 技能0「污」（初始 7）：攻击场上**1 名部署于地面**的我方单位，
    > 对**目标及其周围 4 格**的单位造成**攻击力 100% 的物理伤害**；
    > 自身位于病害值 > 0 的田地地块时，当次攻击**额外附加攻击力 80% 的法术
    > 普通伤害**，且**令目标地块病害值 +5**；※此技能不可沉默

    这五件事（1 名 / 地面限定 / 十字 / 100% 基础倍率 / 不做普攻）**数据里没有**，
    按项目惯例在 `PROSE_SKILL_ATTACK` 里按正文写死，由自检逐条核。

    ⚠ 与「装置内容一定要取」同一条纪律：这里不解释、不外推。技能名叫 `Drink`
    但正文技能名是「污」，两者都留着（`skill_atk_key` 存 prefabKey）。
    """
    out: dict[str, Any] = {}
    for sk in (skills_raw or ()):
        key = str(sk.get("prefabKey") or "")
        spec = PROSE_SKILL_ATTACK.get(key)
        if spec is None:
            continue
        bb = {str(b.get("key")): b.get("value")
              for b in (sk.get("blackboard") or [])}

        def num(k: str, default: float = 0.0) -> float:
            """取一个数。带 `valueStr` 的键是**字符串参数**，不当数字用。"""
            for b in (sk.get("blackboard") or []):
                if str(b.get("key")) != k:
                    continue
                if b.get("valueStr") not in (None, ""):
                    return default
                try:
                    return float(b.get("value"))
                except (TypeError, ValueError):
                    return default
            return default

        out["skill_atk_key"] = key
        out["skill_atk_scale_phys"] = float(spec["scale_phys"])
        out["skill_atk_scale_magic"] = num("atk_scale_magic")
        out["skill_atk_pollut"] = num("value")
        out["skill_atk_targets"] = int(spec["targets"])
        out["skill_atk_cross"] = int(spec["cross"])
        out["skill_atk_ground_only"] = bool(spec["ground_only"])
        out["skill_atk_no_normal"] = bool(spec["no_normal_ranged"])
        try:
            out["skill_atk_interval"] = float(sk.get("baseAttackTime") or 0.0)
        except (TypeError, ValueError):
            out["skill_atk_interval"] = 0.0
        try:
            out["skill_atk_init"] = float(sk.get("initCooldown") or 0.0)
        except (TypeError, ValueError):
            out["skill_atk_init"] = 0.0
        del bb
        return out
    return out


def mech_fields(bb: dict) -> dict:
    """从天赋黑板解出六个机制前缀对应的字段。

    【逐项正文来历】全部取自 prts.wiki 的敌人页「天赋」栏（原文已留档
    `out/prts-act31side-pages.txt` / `-pages2.txt`）：

    * ``Passive.`` —— 秽 / 除秽 / 肮 / 厌肮：「被击倒时，令阻挡自身的单位
      (被阻挡时)/自身(未被阻挡时)**半径1.0范围内**的田地地块病害值
      **+extra_value**」。`range_radius` 就是那个 1.0。
      同一个前缀下还有**另一个不相干的量**：``damage_value`` ——
      「身上的天标」的附着效果「每秒受到 `damage_value` 预计算无途径物理
      伤害」。这两个量此前只取了前者，见 `passive_attach_damage`。
    * ``DeathPassive.`` —— 田鼷飞贼 / 田鼷大盗：「死亡爆炸（予我方可部署
      装置）」，`token_key` = `trap_139_dhtl`、`cnt` = 2。
    * ``AuraHit.`` —— 田鼷力士 / 猛士 / 飞贼 / 大盗：「进入阻流阀半径0.5
      范围内时**立刻**对其造成目标最大生命值 `hp_ratio` 的真实伤害」。
    * ``SpeedUp.`` —— 同一批田鼷：「自身受到伤害且**未被阻挡**时，获得
      `duration` 秒移动速度 +(`move_speed`×100)% 的增益（被阻挡时立刻解除；
      获得增益后 `cooldown` 秒内无法再次获得）」。
    * ``Passive_Hit.`` —— 「祟」混沌形态：「每受到 `cnt` 次伤害，若自身蜕皮
      次数未达到上限 `max_stack_cnt`，则触发【蜕皮】：攻击力+`atk`、防御力
      +`def`、法术抗性+`magic_resistance`、移动速度+`move_speed`，半径1.0
      范围内田地病害值+`value`；每触发 `other_cnt` 次蜕皮，重量等级-1」。
      （负数即"降低"，原文写「攻击力-30」，黑板存的就是 -30。）
    * ``PassiveM2.`` —— 「祟」明识形态：「攻击力 `atk`、防御力 `def`、
      法术抗性+`magic_resistance`、移动速度 `move_speed`；位于水田中且所在
      地块病害值=0（或处于清澈泵站生效范围内）时，防御力+`clean_water.def`、
      法术抗性+`clean_water.magic_resistance`、**失去移动速度加成**；被标记的
      目标退场时若自身未被阻挡，半径1.0 内田地病害值+`mark[host].value`；
      进入该形态时获得 `duration_invic` 秒无敌」。
    * ``CheckAwake.`` —— 天桩-甲 / 失控天桩-甲（**由天桩装置召唤**，不在任何
      一关的出怪表里）：「**监测状态**（初始持有）：无敌、不死、元素免疫，
      **重设自身生命百分比与所在地块病害值相同**（每 1% 生命对应 1 点病害值，
      **不会因此死亡**），病害值 ≥`value_eff` 时红光警告、**首次 ≥`value`
      时切换到激活状态**；**激活状态**：不再监测，每秒受到自身最大生命值
      `hp_ratio`×100% 的真实伤害，**每损失 `enemy_dhdcr_trigger_summon.hp_ratio`
      ×100% 生命**，在 1~1.5 秒随机延迟后于当前位置 **1.0 边长正方形**范围内
      以自身设定路径召唤 `cnt` 个 `enemy_key`」。

    ⚠ 两处**读数存疑、按原样带出但不擅自解释**：

    * ``Passive_Hit.extra_value`` = -0.001：与 `move_speed` = 0.01 同量级，
      疑似移速的某种递减项，但**没有任何正文提到它**，故只登记不用。
    * ``PassiveM2.value`` = 100：与「如梭」技能描述的触发条件「所在地块
      病害值≥100」同值，据此当作阈值带出。

    缺失的键一律给 0/空串，不给 None——上层不必再判。
    """
    out = {
        # ---- Passive.：被击倒时对田地的病害污染
        "passive_pollut": 0.0,
        "passive_radius": 0.0,
        # ---- Passive. 的另一个量：附着效果每秒的预计算伤害（身上的天标）
        "passive_attach_damage": 0.0,
        # ---- DeathPassive.：被击倒时给予可部署装置
        "death_token": "",
        "death_cnt": 0,
        # ---- AuraHit.：进入阻流阀半径 0.5 内立刻造成的真伤比例
        "aura_hit_ratio": 0.0,
        "aura_hit_radius": AURA_HIT_RADIUS,
        # ---- SpeedUp.：受击且未被阻挡时的移速增益
        "speedup_move": 0.0,
        "speedup_duration": 0.0,
        "speedup_cooldown": 0.0,
        # ---- Passive_Hit.：「祟」混沌形态的蜕皮
        "phit_cnt": 0,
        "phit_atk": 0.0,
        "phit_def": 0.0,
        "phit_res": 0.0,
        "phit_move": 0.0,
        "phit_pollut": 0.0,
        "phit_block_pollut": 0.0,
        "phit_extra": 0.0,
        "phit_max_stack": 0,
        "phit_weight_cnt": 0,
        # ---- PassiveM2.：「祟」明识形态
        "pm2_atk": 0.0,
        "pm2_def": 0.0,
        "pm2_res": 0.0,
        "pm2_move": 0.0,
        "pm2_clean_def": 0.0,
        "pm2_clean_res": 0.0,
        "pm2_clean_move": 0.0,
        "pm2_mark_pollut": 0.0,
        "pm2_invincible": 0.0,
        "pm2_pollut_threshold": 0.0,
        # ---- CheckAwake.：天桩-甲的监测 / 激活状态机
        "awake_hp_ratio": 0.0,
        "awake_summon_ratio": 0.0,
        "awake_value": 0.0,
        "awake_value_eff": 0.0,
        "awake_enemy_key": "",
        "awake_summon_cnt": 0,
    }
    if not any(k.startswith(p) for k in bb for p in _MECH_PREFIXES):
        return out

    if "Passive." in _present(bb):
        out["passive_pollut"] = _bb_float(bb, "Passive.extra_value")
        out["passive_radius"] = _bb_float(bb, "Passive.range_radius")
        out["passive_attach_damage"] = _bb_float(bb, "Passive.damage_value")
    if "DeathPassive." in _present(bb):
        out["death_token"] = str(bb.get("DeathPassive.token_key") or "")
        out["death_cnt"] = _bb_int(bb, "DeathPassive.cnt")
    if "AuraHit." in _present(bb):
        out["aura_hit_ratio"] = _bb_float(bb, "AuraHit.hp_ratio")
    if "SpeedUp." in _present(bb):
        out["speedup_move"] = _bb_float(bb, "SpeedUp.move_speed")
        out["speedup_duration"] = _bb_float(bb, "SpeedUp.duration")
        out["speedup_cooldown"] = _bb_float(bb, "SpeedUp.cooldown")
    if "Passive_Hit." in _present(bb):
        out["phit_cnt"] = _bb_int(bb, "Passive_Hit.cnt")
        out["phit_atk"] = _bb_float(bb, "Passive_Hit.atk")
        out["phit_def"] = _bb_float(bb, "Passive_Hit.def")
        out["phit_res"] = _bb_float(bb, "Passive_Hit.magic_resistance")
        out["phit_move"] = _bb_float(bb, "Passive_Hit.move_speed")
        out["phit_pollut"] = _bb_float(bb, "Passive_Hit.value")
        # 「阻挡自身的单位(被阻挡时)」那一支另有自己的量
        out["phit_block_pollut"] = _bb_float(
            bb, "Passive_Hit.enemy_dhnzzh_passive_m1[to_block].extra_value")
        out["phit_extra"] = _bb_float(bb, "Passive_Hit.extra_value")
        out["phit_max_stack"] = _bb_int(bb, "Passive_Hit.max_stack_cnt")
        out["phit_weight_cnt"] = _bb_int(bb, "Passive_Hit.other_cnt")
    if "PassiveM2." in _present(bb):
        out["pm2_atk"] = _bb_float(bb, "PassiveM2.atk")
        out["pm2_def"] = _bb_float(bb, "PassiveM2.def")
        out["pm2_res"] = _bb_float(bb, "PassiveM2.magic_resistance")
        out["pm2_move"] = _bb_float(bb, "PassiveM2.move_speed")
        out["pm2_clean_def"] = _bb_float(bb, "PassiveM2.dhnzzh_clean_water.def")
        out["pm2_clean_res"] = _bb_float(
            bb, "PassiveM2.dhnzzh_clean_water.magic_resistance")
        out["pm2_clean_move"] = _bb_float(
            bb, "PassiveM2.dhnzzh_clean_water.move_speed")
        out["pm2_mark_pollut"] = _bb_float(bb, "PassiveM2.dhnzzh_passive_mark[host].value")
        out["pm2_invincible"] = _bb_float(bb, "PassiveM2.duration_invic")
        out["pm2_pollut_threshold"] = _bb_float(bb, "PassiveM2.value")
    if "CheckAwake." in _present(bb):
        out["awake_hp_ratio"] = _bb_float(bb, "CheckAwake.hp_ratio")
        out["awake_summon_ratio"] = _bb_float(
            bb, "CheckAwake.enemy_dhdcr_trigger_summon.hp_ratio")
        out["awake_value"] = _bb_float(bb, "CheckAwake.value")
        out["awake_value_eff"] = _bb_float(bb, "CheckAwake.value_eff")
        out["awake_enemy_key"] = str(
            bb.get("CheckAwake.enemy_dhdcr_trigger_summon.enemy_key") or "")
        out["awake_summon_cnt"] = _bb_int(
            bb, "CheckAwake.enemy_dhdcr_trigger_summon.cnt")
    return out


def _present(bb: dict) -> frozenset[str]:
    """黑板里**实际出现**的前缀集合。逐前缀判断，不是「有任意一个就全填」——
    混着填会让没有某机制的敌人凭空带上它的默认值。"""
    return frozenset(p for p in _MECH_PREFIXES if any(k.startswith(p) for k in bb))


#: **只有正文、没有结构化字段**的召唤边：来源 key → 被它召唤出来的 key。
#:
#: 为什么要有这张表：盘点（`activity.audit_activity`）要顺着召唤关系把
#: **不在关卡出怪表里**的单位也收进来，否则它们的黑板键永远不会被审计到——
#: 怀黍离的天桩-甲 / 天桩-乙 / 身上的天标就是三个这样的漏网单位
#: （`CheckAwake.` 这个前缀因此长期在盘点里"不存在"，而盘点的结论是
#: 「未登记 0 项」）。模拟器也读这张表，两边同源。
#:
#: 判据：**凡是黑板里有结构化 `*enemy_key` 的边一律不写在这里**（甲→乙 走
#: `CheckAwake.enemy_dhdcr_trigger_summon.enemy_key`、祟的两路走
#: `Reborning.*.enemy_key`），本表只收"正文说了、数据里没有"的那几条。
PROSE_SUMMON_EDGES: dict[str, tuple[str, ...]] = {
    # 装置「天桩」技能「生成」（被动）：「登场时，在自身所在位置以预设路径
    # 召唤一名天桩-甲」。装置自己的技能黑板只有一个键
    # `sktok_dhdcr : branch_id = branch_dhdcr_1`，而 `branch_dhdcr_1`
    # 在客户端数据里只出现在 skill_table 里，没有 branch → prefab 的映射表。
    "trap_146_dhdcr": ("enemy_1398_dhdcr",),
    # 天桩-乙天赋：「攻击命中时，在目标所在地块中心召唤1个[[身上的天标]]」。
    # 乙自己的 `talentBlackboard` 是**空的**，这一跳只有正文。
    "enemy_1399_dhtb": ("enemy_1400_dhtbgj",),
    "enemy_1399_dhtb_2": ("enemy_1400_dhtbgj_2",),
}


def summon_edges(key: str, blackboard: dict | None = None) -> list[str]:
    """这个单位会召唤谁：结构化字段优先，另加正文里写死的那几条边。

    `blackboard` 传 `talentBlackboard`（或已解析的黑板字典）。结构化判据是
    **键名以 `enemy_key` 结尾**——`Reborning.enemy_key`、
    `Reborning.dhnzzh_reborn_c2.enemy_key`、
    `CheckAwake.enemy_dhdcr_trigger_summon.enemy_key` 都命中；
    而 `DeathPassive.token_key`（给的是**装置**不是敌人）不命中，故不会混进来。
    """
    out: list[str] = []
    for k, v in (blackboard or {}).items():
        if k.endswith("enemy_key") and isinstance(v, str) and v:
            out.append(v)
    out.extend(PROSE_SUMMON_EDGES.get(key, ()))
    seen, uniq = set(), []
    for x in out:
        if x not in seen:
            seen.add(x)
            uniq.append(x)
    return uniq


def token_keys(blackboard: dict | None = None) -> list[str]:
    """被击倒时**授予的装置**（`DeathPassive.token_key`）。盘点要顺带收进来。"""
    out = []
    for k, v in (blackboard or {}).items():
        if k.endswith("token_key") and isinstance(v, str) and v:
            out.append(v)
    return out


@dataclass
class EnemyStats:
    """一个敌人在某一等级下的数值。

    `name` 取自官方图鉴表（`enemy_handbook_table.json`），也就是玩家在游戏
    图鉴里看到的那一个。个别敌人在战斗数据（`enemy_database.json`）里挂着
    另一个名字，那会落在 `alias` 上——例如 `enemy_1029_shdsbr` 图鉴叫
    「机动盾兵」而战斗数据叫「持盾刀兵」。两个都留着，不替谁下判断。
    """

    enemy_id: str
    level: int = 0
    name: str = ""
    alias: str = ""
    max_hp: float | None = None
    atk: float | None = None
    defense: float | None = None
    magic_resistance: float | None = None    # 百分比，如 30.0 表示 30%
    move_speed: float | None = None
    attack_speed: float | None = None        # 100 为基准
    base_attack_time: float | None = None    # 攻击间隔（秒）
    weight: float | None = None              # massLevel，0 起算
    life_point_reduce: float | None = None   # 漏掉扣几点生命
    range_radius: float | None = None
    hp_recovery_per_sec: float | None = None
    level_type: Any = None
    immunities: dict[str, bool] = field(default_factory=dict)
    raw_attributes: dict[str, Any] = field(default_factory=dict, repr=False)

    # ---------------------------------------------------------- 伤害相性 P3R
    #: 伤害相性：`{"physical": 0, "magical": 1, "element": 2}`。
    #: 取值 0 弱点 / 1 正常 / 2 免疫 / 3 反射。取自 `TotalAttack.*` 黑板。
    p3r: dict[str, int] = field(default_factory=dict)
    #: 击破值阈值（`TotalAttack.weak_max`）——累积到这个实际掉血量就倒地
    weak_max: float = 0.0
    #: 倒地持续秒数（`TotalAttack.fall_duration`）
    fall_duration: float = 0.0
    #: 形态相性（BOSS 专用）：`{"Mode_A": {...}, "Mode_B": {...}}`。
    #: BOSS 的真档位在这里，它的 `TotalAttack.*` 反而是 1/1/1（无弱点）。
    modes: dict[str, dict[str, int]] = field(default_factory=dict)
    #: 该档完整的 `talentBlackboard`，键名原样保留（如 `Mode_A.PHYSICAL`）。
    #: 敌人侧没有 `talents` 字段，天赋全拍平进这里，prefabKey 只能靠前缀猜。
    talent_blackboard: dict[str, Any] = field(default_factory=dict, repr=False)
    #: 该档的原始 `skills`（每项含 prefabKey/cooldown/initCooldown/blackboard）
    skills_raw: tuple = field(default=(), repr=False)

    # ------------------------------------------------ 关卡机制（敌人侧）
    #: 屏障比例（`Shield.shield_hp_ratio`）。吓人路灯是 0.25，即一层
    #: 相当于最大生命 25% 的额外血条，**在血量之前被消耗**。
    shield_hp_ratio: float = 0.0
    #: 是否飞行（`motion == "FLY"`）。飞行单位**不可被地面干员阻挡**，
    #: SR-EX-8 里挥铳圣像就是 FLY，而它同时「没有弱点、永不倒地」。
    is_flying: bool = False
    #: 出手方式（`applyWay`）：`MELEE` / `RANGED` / `NONE`。
    #: `RANGED` 的敌人**会停在射程外开火**，射程就是 `range_radius`。
    apply_way: str = "MELEE"
    #: 击杀奖励费用（`Talent1.cost`）。没办法车是 50，且它
    #: `lifePointReduce = 0`（漏掉不扣命、不可阻挡）。
    kill_cost: int = 0
    #: 重生次数。BOSS「死志的凝结」死一次后以满血归来。
    reborn_count: int = 0
    #: 两次重生之间的间隔秒数（`Reborn.reborn_duration` = 10 /
    #: `Reborning.duration` = 5）
    reborn_duration: float = 0.0
    #: 重生时的血量比例（`Reborn.max_hp_ratio`，1 = 满血）
    reborn_hp_ratio: float = 1.0
    #: 命中的重生前缀（`Reborn.` / `Reborning.`），空串表示不重生。
    #: 充能那四个量都挂在这个前缀下，故必须把它带出来。
    reborn_prefix: str = ""
    #: 【怀黍离】重生期间每隔几秒结算一次充能（`Reborning.interval` = 0.5）
    reborn_interval: float = 0.0
    #: 每次充能扣掉所在地块多少点病害值（`Reborning.value` = -10，取绝对值）
    reborn_pollut: float = 0.0
    #: 每层充能给多少防御力比例（`Reborning.def_add` = 0.3，即每层 +30%）
    reborn_def_add: float = 0.0
    #: 每层充能给多少附加法术伤害比例（`Reborning.damage_magic` = 0.1，每层 10%）
    reborn_damage_magic: float = 0.0
    #: 重生期间按间隔召唤：`((间隔秒, 个数, 敌人 id), …)`。
    #: 与上面的充能是两条互不相干的分支（「祟」走这支、瘴走充能那支）。
    reborn_summons: tuple = ()

    # ------------------------------------------------ 六个机制前缀（见 mech_fields）
    #: 「Passive.」被击倒时对半径 `passive_radius` 内的田地各加多少病害值
    passive_pollut: float = 0.0
    passive_radius: float = 0.0
    #: 「Passive.」附着效果每秒造成的**预计算无途径物理伤害**（身上的天标 =
    #: 200，天标二 = 300）。与上面的 `passive_pollut` 同前缀、完全不相干——
    #: 这正是"前缀级覆盖"曾经漏掉的东西：`mech_fields` 只读了 `extra_value`。
    passive_attach_damage: float = 0.0
    #: 「DeathPassive.」被击倒时给予我方可部署装置：装置 key 与个数
    death_token: str = ""
    death_cnt: int = 0
    #: 「AuraHit.」进入阻流阀 `aura_hit_radius` 格内时对其造成**目标最大生命**
    #: 的这个比例（真伤）。注意比例是相对**目标（阻流阀）**的生命，不是自己的。
    aura_hit_ratio: float = 0.0
    aura_hit_radius: float = AURA_HIT_RADIUS
    #: 「SpeedUp.」受到伤害且未被阻挡时，移速 +`speedup_move`×100%、
    #: 持续 `speedup_duration` 秒、冷却 `speedup_cooldown` 秒
    speedup_move: float = 0.0
    speedup_duration: float = 0.0
    speedup_cooldown: float = 0.0
    #: 「Passive_Hit.」每受 `phit_cnt` 次伤害蜕皮一层（上限 `phit_max_stack`）
    phit_cnt: int = 0
    phit_atk: float = 0.0
    phit_def: float = 0.0
    phit_res: float = 0.0
    phit_move: float = 0.0
    phit_pollut: float = 0.0
    phit_block_pollut: float = 0.0
    phit_extra: float = 0.0
    phit_max_stack: int = 0
    phit_weight_cnt: int = 0
    #: 「PassiveM2.」明识形态的属性改写与清水减益
    pm2_atk: float = 0.0
    pm2_def: float = 0.0
    pm2_res: float = 0.0
    pm2_move: float = 0.0
    pm2_clean_def: float = 0.0
    pm2_clean_res: float = 0.0
    pm2_clean_move: float = 0.0
    pm2_mark_pollut: float = 0.0
    pm2_invincible: float = 0.0
    pm2_pollut_threshold: float = 0.0
    #: 「CheckAwake.」天桩-甲的监测/激活状态机（见 `mech_fields` 的正文）
    #: 每秒自伤比例（`hp_ratio` = 0.01，即每秒 1% 最大生命）
    awake_hp_ratio: float = 0.0
    #: 每损失这个比例的生命就召唤一批（`enemy_dhdcr_trigger_summon.hp_ratio`）
    awake_summon_ratio: float = 0.0
    #: 激活阈值（`value` = 100）：所在地块病害值**首次**达到它就切激活
    awake_value: float = 0.0
    #: 红闪警告阈值（`value_eff` = 70）：纯表现，模拟器只登记不使用
    awake_value_eff: float = 0.0
    #: 召唤谁（`enemy_key` = `enemy_1399_dhtb`，即天桩-乙）
    awake_enemy_key: str = ""
    #: 每批召唤几个（`cnt` = 3）
    awake_summon_cnt: int = 0

    #: 嘲讽等级（`tauntLevel`）。天桩-甲的 **非首要目标** 在天标身上就是
    #: `tauntLevel = -1`（prts 参数表「基础嘲讽等级 -1」），索敌时排最后。
    #: 绝大多数敌人是 0，所以这条只在负数单位上改变行为。
    taunt_level: float = 0.0

    # ---------------------------------------------- 技能攻击（见 skill_attack_fields）
    #: 命中的技能 `prefabKey`（怀黍离是 `Drink`，即图鉴技能 0「污」）。
    #: 非空 = 这个敌人的伤害来自**技能**而不是普攻。
    skill_atk_key: str = ""
    #: 基础物理倍率（正文「造成攻击力100%的物理伤害」→ 1.0）
    skill_atk_scale_phys: float = 0.0
    #: 附加法术倍率（黑板 `atk_scale_magic` = 0.8；ex04 四星档被 rune
    #: `enemy_skill_blackb_mul` 乘 1.3 变 1.04）。**这是那条 rune 的落点。**
    skill_atk_scale_magic: float = 0.0
    #: 攻击时令目标地块病害值 +N（黑板 `value` = 5），记入【缓存】。
    skill_atk_pollut: float = 0.0
    #: 打几个目标（正文「攻击场上1名部署于地面的我方单位」→ 1）
    skill_atk_targets: int = 0
    #: 溅射的十字半径（正文「对目标及其**周围4格**的单位造成…」→ 1 = 十字五格）
    skill_atk_cross: int = 0
    #: 只打**部署于地面**的单位（正文「部署于地面的我方单位」）
    skill_atk_ground_only: bool = False
    #: 不做远程普攻（正文天赋「不进行远程普通攻击」）——它的 `rangeRadius`
    #: 是 −1 正是因为这个：射程对它没有意义，**全图**才是它的射程。
    skill_atk_no_normal: bool = False
    #: 出手间隔（秒）与首次出手时刻。技能自己**没有**间隔字段，数据里的
    #: 间隔就是敌人自己的 `baseAttackTime`（玷 = 7）——所以 `skill_atk_interval`
    #: 通常是 0，模拟器那时退回 `attack_interval`；`initCooldown` = 7 是首手。
    skill_atk_interval: float = 0.0
    skill_atk_init: float = 0.0

    # ---------------------------------------------------------- 派生与副本

    def derive_blackboard_fields(self) -> None:
        """**只**由 `talent_blackboard` 推出的那些字段：相性、屏障、击杀费用、
        重生与六个机制前缀。

        单独抽出来是为了 `rescale_talent_blackboard`：关卡 runes 的
        `enemy_talent_blackb_mul` 会把某个黑板键乘一个系数，乘完必须**重算**
        由它派生的字段，否则乘数只改了一张没人再读的表（看着接好了、实际没接）。

        属性类字段（`max_hp` / `atk` / `defense` …）不在这里——它们来自
        `enemyData.attributes`，与黑板无关。
        """
        bb = self.talent_blackboard
        self.p3r = affinity_of(bb)
        self.weak_max = float(bb.get("TotalAttack.weak_max") or 0.0)
        self.fall_duration = float(bb.get("TotalAttack.fall_duration") or 0.0)
        self.modes = {m: affinity_of(bb, m) for m in ("Mode_A", "Mode_B")
                      if affinity_of(bb, m)}
        self.shield_hp_ratio = float(bb.get("Shield.shield_hp_ratio") or 0.0)
        self.kill_cost = int(bb.get("Talent1.cost") or 0)
        for k, v in reborn_fields(bb).items():
            setattr(self, k, v)
        for k, v in mech_fields(bb).items():
            setattr(self, k, v)
        self.derive_skill_fields()

    def derive_skill_fields(self) -> None:
        """由**技能**（`skills_raw`）推出的字段：见 `skill_attack_fields`。

        单列出来的理由与 `derive_blackboard_fields` 一样：`enemy_skill_blackb_mul`
        会按技能点名把黑板键乘系数，乘完**必须重算**，否则乘数只落在一张
        没人再读的表上——这一条正是 ④ 那个 TODO 的死因。
        """
        for k, v in skill_attack_fields(self.skills_raw).items():
            setattr(self, k, v)

    def rescale_talent_blackboard(self, factors: dict) -> list[str]:
        """把若干天赋黑板键各乘一个系数，并重算派生字段。

        返回**真的改到了**的键（键不在这个敌人的黑板上就没有改到）——
        调用方据此记账：`enemy_talent_blackb_mul` 指名道姓地写了对哪些敌人、
        哪个键乘多少，若一个键都没命中，那是**数据与敌人对不上**，
        静默忽略等于把守卫关掉。
        """
        hits: list[str] = []
        for key, factor in factors.items():
            if key not in self.talent_blackboard:
                continue
            try:
                self.talent_blackboard[key] = float(
                    self.talent_blackboard[key]) * factor
            except (TypeError, ValueError):
                continue
            hits.append(key)
        if hits:
            self.derive_blackboard_fields()
        return hits

    def rescale_skill_blackboard(self, prefab_key: str,
                                 factors: dict) -> list[str]:
        """把**某个技能**（按 `prefabKey` 点名）的若干黑板键乘系数。

        返回真的改到的键。`skills_raw` 是元组、里面的 dict 与 blackboard 列表
        都可能是库里共享的对象，所以这里**重建**那一项而不是就地改
        （就地改会污染全库缓存，见 `clone`）。

        ⚠ 2026-09-16 起**有消费者了**：这条乘数打的是「玷 / 勿玷」技能
        `Drink`（图鉴技能 0「污」）的 `atk_scale_magic`，而这条技能已经接进
        模拟器（`skill_attack_fields` → `BattleSimulator._skill_attack_tick`）。
        乘完**必须重算派生字段**，否则乘数只落在 `skills_raw` 那张没人再读的表上。
        """
        if not prefab_key:
            return []
        hits: list[str] = []
        out = []
        for sk in self.skills_raw or ():
            if str(sk.get("prefabKey") or "") != prefab_key:
                out.append(sk)
                continue
            new_bb = []
            for b in (sk.get("blackboard") or []):
                k = b.get("key")
                if k in factors and b.get("valueStr") in (None, ""):
                    try:
                        nv = float(b.get("value")) * factors[k]
                    except (TypeError, ValueError):
                        new_bb.append(b)
                        continue
                    b = {**b, "value": nv}
                    hits.append(str(k))
                new_bb.append(b)
            out.append({**sk, "blackboard": new_bb})
        if hits:
            self.skills_raw = tuple(out)
            # 乘完必须重算：技能攻击的倍率是从 `skills_raw` 派生出来的，
            # 不重算的话乘数只改了一张没人再读的表（这正是 ④ 的死因）。
            self.derive_skill_fields()
        return hits

    def clone(self) -> "EnemyStats":
        """一份**可以随便改**的副本。

        `EnemyLibrary` 的 `EnemyStats` 是按敌人全库缓存的，而关卡 runes 的
        乘数是**按关生效**的：不改副本就会把「这一关的四星难度敌人更强」
        永久写进库里，下一关跟着一起变强，且没有任何报错。
        """
        new = copy.copy(self)
        new.immunities = dict(self.immunities)
        new.raw_attributes = dict(self.raw_attributes)
        new.p3r = dict(self.p3r)
        new.modes = {k: dict(v) for k, v in self.modes.items()}
        new.talent_blackboard = dict(self.talent_blackboard)
        return new

    @property
    def has_p3r(self) -> bool:
        """有没有伤害相性计量——有才会卡住关卡装置「全场总攻击」。"""
        return bool(self.p3r)

    @property
    def can_fall(self) -> bool:
        """有没有弱点——`挥铳圣像` 是 1/1/1，**永远不会倒地**。"""
        return any(v == 0 for v in self.p3r.values())

    def affinity(self, mode: str | None = None) -> dict[str, int]:
        """当前的伤害相性。给了 `mode`（如 `"Mode_A"`）就取形态那一份。"""
        if mode and mode in self.modes:
            return dict(self.modes[mode])
        return dict(self.p3r)

    @property
    def display_name(self) -> str:
        return self.name or self.alias or self.enemy_id

    @property
    def is_ranged(self) -> bool:
        """是不是远程攻击（rangeRadius 大于 0 基本就是）。"""
        return bool(self.range_radius and self.range_radius > 0.1)

    def to_dict(self) -> dict:
        return {
            "enemy_id": self.enemy_id, "level": self.level, "name": self.name,
            "alias": self.alias,
            "max_hp": self.max_hp, "atk": self.atk, "defense": self.defense,
            "magic_resistance": self.magic_resistance,
            "move_speed": self.move_speed, "attack_speed": self.attack_speed,
            "base_attack_time": self.base_attack_time,
            "weight": self.weight, "life_point_reduce": self.life_point_reduce,
            "range_radius": self.range_radius,
            "level_type": self.level_type,
            "immunities": {k: v for k, v in self.immunities.items() if v},
            "p3r": self.p3r, "weak_max": self.weak_max,
            "fall_duration": self.fall_duration, "modes": self.modes,
        }


def _unwrap(value: Any) -> Any:
    """剥开 `{m_defined, m_value}`。未定义的返回 None。"""
    if isinstance(value, dict) and "m_defined" in value:
        return value["m_value"] if value.get("m_defined") else None
    return value


def _merge_defined(low: dict, high: dict) -> dict:
    """把高优先级的非 None 字段盖到低优先级上。"""
    out = dict(low)
    for k, v in high.items():
        if v is not None:
            out[k] = v
    return out


#: 伤害相性的三个槽位 ↔ 黑板键后缀
P3R_SLOTS = {"physical": "PHYSICAL", "magical": "MAGICAL", "element": "ELEMENT"}

#: 相性取值。`WEAK` 才会累积击破值；`IMMUNE` 把伤害**归零**（不是减免）
P3R_WEAK, P3R_NORMAL, P3R_IMMUNE, P3R_REFLECT = 0, 1, 2, 3


def affinity_of(blackboard: dict, prefix: str = "TotalAttack") -> dict[str, int]:
    """从黑板里取一组伤害相性，如 `prefix="TotalAttack"` 或 `"Mode_A"`。

    三个槽位缺一不可才算数；缺了就返回空字典，免得把"没有这项数据"当成
    "相性为 0（弱点）"——那会让敌人凭空多出弱点。
    """
    out: dict[str, int] = {}
    for slot, suffix in P3R_SLOTS.items():
        v = blackboard.get(f"{prefix}.{suffix}")
        if v is None:
            return {}
        out[slot] = int(v)
    return out


class EnemyLibrary:
    """敌人图鉴与属性的统一入口。

    属性库很大，所以这里做一件要紧的事：**解析完就把原始 JSON 从数据源里
    释放掉**，只留一份精简后的数值索引。否则 15 MB 的 JSON 反过来会变成
    上百 MB 的 Python 对象常驻内存。
    """

    def __init__(self, source: GameDataSource | None = None) -> None:
        self.source = source or GameDataSource()
        self._stats: dict[str, dict[int, EnemyStats]] | None = None
        self._handbook: dict[str, dict] | None = None

    # ------------------------------------------------------------ 加载

    def _ensure_stats(self) -> dict[str, dict[int, EnemyStats]]:
        if self._stats is not None:
            return self._stats
        db = self.source.enemy_database()
        if not isinstance(db, dict) or "enemies" not in db:
            raise GamedataError("enemy_database.json 的结构不是预期形状")

        stats: dict[str, dict[int, EnemyStats]] = {}
        for entry in db["enemies"]:
            key = entry.get("Key", "")
            levels: dict[int, EnemyStats] = {}
            # Value 是按优先级从低到高的若干档，逐档合并
            merged: dict[str, Any] = {}
            merged_bb: dict[str, Any] = {}
            merged_skills: tuple = ()
            for item in entry.get("Value", []):
                lv = int(item.get("level", 0) or 0)
                ed = item.get("enemyData") or {}
                attrs_raw = ed.get("attributes") or {}
                attrs = {f: _unwrap(attrs_raw.get(f)) for f in _ATTR_FIELDS}
                # 免疫位也在 attributes 里，**必须一起走合并**：
                # 高档位的免疫位常是 m_defined=false（表示"沿用低档"），
                # 直接读当前档会全变成 False。BOSS 用的正是高档位。
                attrs.update({f: _unwrap(attrs_raw.get(f)) for f in _IMMUNE_FIELDS})
                # 这三项在 enemyData 顶层，不在 attributes 里
                attrs.update({f: _unwrap(ed.get(f)) for f in _TOP_FIELDS})
                merged = _merge_defined(merged, attrs)
                # 天赋黑板同样逐档合并（敌人侧没有 talents 字段，天赋全拍平在这里）
                bb: dict[str, Any] = {}
                for b in ed.get("talentBlackboard") or []:
                    bk = b.get("key")
                    if not bk:
                        continue
                    # ⚠ 黑板有两列：**数值住 `value`、字符串住 `valueStr`**。
                    # 只读 `value` 会把所有字符串键整条丢掉，而"召唤什么"
                    # "给哪个装置"恰恰只写在字符串里：
                    # `DeathPassive.token_key = "trap_139_dhtl"`、
                    # `Reborning.enemy_key = "enemy_1390_dhsbr"`。
                    # 丢掉它们不会报错——`bb.get(k)` 只是返回 None，
                    # 上层当"这个敌人没有这项机制"处理，于是召唤/给装置
                    # 整条静默失效。
                    #
                    # ⚠ 而且字符串键的 `value` 列**不是 None 而是 0**
                    # （占位值），所以判据必须是"valueStr 非空则取它"，
                    # 不能写成"value 没了才看 valueStr"——那样仍会读到 0，
                    # 看着有值、实则拿到的是一个假的敌人 id。
                    #
                    # 这条判据在**全库**上验过：`enemy_database.json` 的天赋与
                    # 技能黑板里 valueStr 非空的条目 531 条，其中 value 列
                    # 同时非零的 **0 条**——即"valueStr 非空"与"value 是占位 0"
                    # 是同一件事，取字符串不会吃掉任何真数值。
                    sv = b.get("valueStr")
                    bv = (sv.strip() if isinstance(sv, str) and sv.strip()
                          else _unwrap(b.get("value")))
                    if bv is not None:
                        bb[bk] = bv
                merged_bb = _merge_defined(merged_bb, bb)
                # `skills` 也要跨档沿用。它**不带** {m_defined, m_value} 包装，
                # 用的是「null 表示未定义」这套：高档位若是 `skills: null`，
                # 说明这一档整体是继承档（levelType 的 m_defined 也是 false），
                # 技能要接着低档用。
                #
                # 踩坑实例：SR-EX-8 的 BOSS `enemy_1589_pppdth` 关卡引用 level 1，
                # 而 level 1 的 skills 是 null、level 0（BOSS 档）才有
                # `Skill_Revelation`——只读当前档会把它整条丢掉。
                # 空列表 `[]` 与 null 不同：那是"显式没有技能"，照旧覆盖。
                if ed.get("skills") is not None:
                    merged_skills = tuple(ed["skills"])
                levels[lv] = EnemyStats(
                    enemy_id=key,
                    level=lv,
                    # 先放战斗数据里的名字，取名时再让图鉴名覆盖上去
                    name=str(_unwrap(ed.get("name")) or ""),
                    max_hp=merged.get("maxHp"),
                    atk=merged.get("atk"),
                    defense=merged.get("def"),
                    magic_resistance=merged.get("magicResistance"),
                    move_speed=merged.get("moveSpeed"),
                    attack_speed=merged.get("attackSpeed"),
                    base_attack_time=merged.get("baseAttackTime"),
                    weight=merged.get("massLevel"),
                    life_point_reduce=merged.get("lifePointReduce"),
                    range_radius=merged.get("rangeRadius"),
                    hp_recovery_per_sec=merged.get("hpRecoveryPerSec"),
                    level_type=merged.get("levelType"),
                    immunities={f: bool(merged.get(f)) for f in _IMMUNE_FIELDS},
                    raw_attributes=dict(attrs_raw),
                    talent_blackboard=dict(merged_bb),
                    skills_raw=merged_skills,
                    # 挥铳圣像 motion=FLY；它同时是 1/1/1 无弱点
                    is_flying=str(merged.get("motion") or "") == "FLY",
                    apply_way=str(merged.get("applyWay") or "MELEE"),
                    # 嘲讽等级：负数即「非首要目标」，索敌时排最后（天标 = −1）
                    taunt_level=float(merged.get("tauntLevel") or 0.0),
                )
                # 由**天赋黑板**派生的字段统一在这里算（相性 / 屏障 / 击杀费用 /
                # 重生 / 六个机制前缀）。单列出来是为了关卡 runes 的乘数能重算
                # 一遍——见 `derive_blackboard_fields`。
                #
                # 重生那一条格外重要：原先写死成 `"Reborn.reborn_duration" in
                # merged_bb` 一个键，于是怀黍离的瘴 / 鄙瘴（`Reborning.duration`）
                # 与「祟」**从来不重生**——而模拟照常跑完、照常出结果，不报错。
                levels[lv].derive_blackboard_fields()
            stats[key] = levels

        self._stats = stats
        # 精简索引已建好，原始大对象可以走了
        self.source.release("levels/enemydata/enemy_database.json")
        return stats

    def _ensure_handbook(self) -> dict[str, dict]:
        if self._handbook is not None:
            return self._handbook
        hb = self.source.enemy_handbook()
        self._handbook = hb.get("enemyData", hb) if isinstance(hb, dict) else {}
        return self._handbook

    # ------------------------------------------------------------ 查询

    def get(self, enemy_id: str, level: int | None = None) -> EnemyStats:
        """取一个敌人的数值。level 为 None 时取它最高的一档。

        名字以官方图鉴为准；万一战斗数据里挂着另一个名字，那会落到
        `alias` 上而不是被丢掉。
        """
        stats = self._ensure_stats()
        if enemy_id not in stats:
            raise KeyError(f"属性库里没有敌人 {enemy_id}")
        levels = stats[enemy_id]
        if level is None:
            level = max(levels)
        if level not in levels:
            # 关卡可能引用一个不存在的档位，退到最高档更安全
            level = max(levels)
        st = levels[level]
        if not st.name:
            st.name = self.name(enemy_id)
        hb_name = self.handbook_entry(enemy_id).get("name")
        if hb_name and hb_name != st.name:
            st.alias = st.name
            st.name = hb_name
        return st

    def with_overwrite(self, enemy_id: str, overwritten: dict,
                       level: int | None = None) -> EnemyStats:
        """关卡**自带**的敌人定义（``enemyDbRefs[].overwrittenData``）盖到 prefab 档位上。

        用在 ``useDb: false`` 的敌人上：它们的 id **不在属性库里**，整份数据写在
        关卡文件里，只有 ``prefabKey`` 指向的那个在库里。怀黍离小地图上的
        ``enemy_1398_dhdcr_b``（天桩-甲）/ ``enemy_1399_dhtb_b``（天桩-乙）
        就是这个形态——不改这条，天桩链在 03/04/07/tr01/tr02 五关里会整条走不通。

        合并口径与库内**逐档合并**一致：

        * ``attributes`` / 顶层字段：只认 ``m_defined: true`` 的那些
          （``m_defined: false`` 表示"这一档没写、沿用 prefab"）。
        * ``talentBlackboard``：**整表替换**语义按 ``_merge_defined`` 走
          （该键在本地定义里出现就覆盖）。这里用同一套 `valueStr 优先` 判据。
        * 结果拿 prefab 的副本改，绝不写回库——库是所有关卡共用的。
        """
        base = copy.deepcopy(self.get(enemy_id if self.exists(enemy_id)
                                      else str(_unwrap(overwritten.get("prefabKey"))
                                               or enemy_id), level))
        attrs = overwritten.get("attributes") or {}
        for f in _ATTR_FIELDS + _IMMUNE_FIELDS:
            cell = attrs.get(f)
            if isinstance(cell, dict) and cell.get("m_defined"):
                base.raw_attributes[f] = cell
        top = {}
        for f in _TOP_FIELDS:
            cell = overwritten.get(f)
            if isinstance(cell, dict) and cell.get("m_defined"):
                top[f] = _unwrap(cell)
        bb = dict(base.talent_blackboard)
        for b in (overwritten.get("talentBlackboard") or []):
            bk = b.get("key")
            if not bk:
                continue
            sv = b.get("valueStr")
            bv = (sv.strip() if isinstance(sv, str) and sv.strip()
                  else _unwrap(b.get("value")))
            if bv is not None:
                bb[bk] = bv
        # 属性：本地定义里 `m_defined: true` 的覆盖 prefab，其余沿用。
        # `lifePointReduce` / `rangeRadius` 在原始数据里挂**顶层**、
        # 不在 `attributes` 下，两处都要找。
        def pick(name: str):
            for cell in (attrs.get(name), overwritten.get(name)):
                if isinstance(cell, dict) and cell.get("m_defined"):
                    return _unwrap(cell)
            return getattr(base, _ATTR_TO_FIELD[name], None)

        base.enemy_id = enemy_id
        base.level = level if level is not None else base.level
        base.name = str(_unwrap(overwritten.get("name")) or base.name)
        base.max_hp = pick("maxHp")
        base.atk = pick("atk")
        base.defense = pick("def")
        base.magic_resistance = pick("magicResistance")
        base.move_speed = pick("moveSpeed")
        base.attack_speed = pick("attackSpeed")
        base.base_attack_time = pick("baseAttackTime")
        base.weight = pick("massLevel")
        base.life_point_reduce = pick("lifePointReduce")
        base.range_radius = pick("rangeRadius")
        base.hp_recovery_per_sec = pick("hpRecoveryPerSec")
        if "motion" in top:
            base.is_flying = str(top["motion"] or "") == "FLY"
        if "applyWay" in top:
            base.apply_way = str(top["applyWay"] or base.apply_way)
        if "levelType" in top:
            base.level_type = top["levelType"]
        cell = attrs.get("tauntLevel")
        if isinstance(cell, dict) and cell.get("m_defined"):
            base.taunt_level = float(_unwrap(cell) or 0.0)
        base.immunities = {
            f: (bool(_unwrap(attrs[f]))
                if isinstance(attrs.get(f), dict) and attrs[f].get("m_defined")
                else base.immunities.get(f, False))
            for f in _IMMUNE_FIELDS}
        base.talent_blackboard = bb
        if overwritten.get("skills") is not None:
            base.skills_raw = tuple(overwritten["skills"])
        # 派生字段必须重算：`CheckAwake.` 的 enemy_key 换了（03/04 是
        # `enemy_1399_dhtb_b`，07 又换回 `enemy_1399_dhtb`），不重算就会
        # 按 prefab 的老黑板召错单位。
        base.derive_blackboard_fields()
        return base

    def name(self, enemy_id: str) -> str:
        """中文名。图鉴表优先，没有图鉴就退到属性库里的名字。

        ark-nights 镜像不带 `excel/enemy_handbook_table.json`，所以这条
        退路是常规路径而非异常路径。注意这里**不能**回头调 `get()`，
        那会和 `get()` 里的取名逻辑绕成递归。
        """
        entry = self._ensure_handbook().get(enemy_id) or {}
        if entry.get("name"):
            return entry["name"]
        levels = self._ensure_stats().get(enemy_id)
        if levels:
            for lv in sorted(levels, reverse=True):
                if levels[lv].name:
                    return levels[lv].name
        return enemy_id

    def handbook_entry(self, enemy_id: str) -> dict:
        return self._ensure_handbook().get(enemy_id) or {}

    def levels(self, enemy_id: str) -> list[int]:
        return sorted(self._ensure_stats().get(enemy_id, {}))

    def exists(self, enemy_id: str) -> bool:
        return enemy_id in self._ensure_stats()

    def all_ids(self) -> list[str]:
        return sorted(self._ensure_stats())

    def describe(self, enemy_id: str, level: int | None = None) -> str:
        st = self.get(enemy_id, level)
        hb = self.handbook_entry(enemy_id)
        lines = [
            f"{st.name}（{st.enemy_id}，编号 {hb.get('enemyIndex', '?')}）"
            f"  档位 {st.level}",
            f"  生命 {_g(st.max_hp)}  攻击 {_g(st.atk)}  防御 {_g(st.defense)}  "
            f"法抗 {_g(st.magic_resistance)}%",
            f"  移速 {_g(st.move_speed)}  攻击间隔 {_g(st.base_attack_time)}s  "
            f"重量等级 {_g(st.weight)}",
        ]
        if st.life_point_reduce is not None:
            lines.append(f"  漏掉扣生命 {_g(st.life_point_reduce)}")
        imm = [k for k, v in st.immunities.items() if v]
        if imm:
            lines.append("  免疫：" + "、".join(imm))
        ability = hb.get("ability")
        if ability:
            lines.append(f"  能力：{ability}")
        desc = (hb.get("description") or "").strip()
        if desc:
            lines.append(f"  描述：{desc}")
        return "\n".join(lines)


def _g(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
