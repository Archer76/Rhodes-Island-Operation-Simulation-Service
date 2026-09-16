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
    #: 重生次数（`Reborn.*`）。BOSS「死志的凝结」死一次后以满血归来。
    reborn_count: int = 0
    #: 两次重生之间的间隔（`Reborn.reborn_duration`，10 秒）
    reborn_duration: float = 0.0
    #: 重生时的血量比例（`Reborn.max_hp_ratio`，1 = 满血）
    reborn_hp_ratio: float = 1.0

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
                    bv = _unwrap(b.get("value"))
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
                    p3r=affinity_of(merged_bb),
                    weak_max=float(merged_bb.get("TotalAttack.weak_max") or 0.0),
                    fall_duration=float(merged_bb.get("TotalAttack.fall_duration") or 0.0),
                    modes={m: affinity_of(merged_bb, m)
                           for m in ("Mode_A", "Mode_B")
                           if affinity_of(merged_bb, m)},
                    talent_blackboard=dict(merged_bb),
                    skills_raw=merged_skills,
                    # ---- 关卡机制（敌人侧）。键名全部来自战数据，别猜。
                    # 吓人路灯 0.25；别人没有这一项。
                    shield_hp_ratio=float(merged_bb.get("Shield.shield_hp_ratio") or 0.0),
                    # 挥铳圣像 motion=FLY；它同时是 1/1/1 无弱点
                    is_flying=str(merged.get("motion") or "") == "FLY",
                    apply_way=str(merged.get("applyWay") or "MELEE"),
                    # 没办法车：击倒 +50 费用，且 lifePointReduce = 0
                    kill_cost=int(merged_bb.get("Talent1.cost") or 0),
                    # BOSS「死志的凝结」：Reborn.reborn_duration 10 /
                    # max_hp_ratio 1（满血归来）。数据里没有明写次数，
                    # 按「一次」建模——这是唯一有旁证（TalentReborn 是
                    # 一次性触发）的读法，且次数越多结论越保守。
                    reborn_count=1 if "Reborn.reborn_duration" in merged_bb else 0,
                    reborn_duration=float(merged_bb.get("Reborn.reborn_duration") or 0.0),
                    reborn_hp_ratio=float(merged_bb.get("Reborn.max_hp_ratio") or 1.0),
                )
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
