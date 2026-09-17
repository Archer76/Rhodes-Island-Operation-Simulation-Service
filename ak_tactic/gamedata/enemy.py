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
    "Passive_Hit.", "PassiveM2.",
)


def _bb_float(bb: dict, key: str, default: float = 0.0) -> float:
    v = bb.get(key)
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _bb_int(bb: dict, key: str, default: int = 0) -> int:
    return int(_bb_float(bb, key, float(default)))


def mech_fields(bb: dict) -> dict:
    """从天赋黑板解出六个机制前缀对应的字段。

    【逐项正文来历】全部取自 prts.wiki 的敌人页「天赋」栏（原文已留档
    `out/prts-act31side-pages.txt` / `-pages2.txt`）：

    * ``Passive.`` —— 秽 / 除秽 / 肮 / 厌肮：「被击倒时，令阻挡自身的单位
      (被阻挡时)/自身(未被阻挡时)**半径1.0范围内**的田地地块病害值
      **+extra_value**」。`range_radius` 就是那个 1.0。
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
    }
    if not any(k.startswith(p) for k in bb for p in _MECH_PREFIXES):
        return out

    if "Passive." in _present(bb):
        out["passive_pollut"] = _bb_float(bb, "Passive.extra_value")
        out["passive_radius"] = _bb_float(bb, "Passive.range_radius")
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
    return out


def _present(bb: dict) -> frozenset[str]:
    """黑板里**实际出现**的前缀集合。逐前缀判断，不是「有任意一个就全填」——
    混着填会让没有某机制的敌人凭空带上它的默认值。"""
    return frozenset(p for p in _MECH_PREFIXES if any(k.startswith(p) for k in bb))


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

        ⚠ 目前**没有消费者**：模拟器不驱动敌方技能（既没有敌方 SP 回转，
        也没有技能效果结算），所以这条乘数眼下只让数据变正确、不改变任何
        一次结算。这不是"顺手接了一半"，是如实记账——
        `activity.py` 里 `enemy_skill_blackb_mul` 因此仍标 `todo`。
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
