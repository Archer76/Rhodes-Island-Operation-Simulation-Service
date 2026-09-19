# -*- coding: utf-8 -*-
"""关卡 `runes` 里的**敌人修饰层**：按难度生效的属性乘数、黑板乘数、生命点改写。

【为什么单独一层】
这三条 rune 改的都是**别人**（敌人属性、敌人天赋黑板、关卡生命点），
既不属于环境系统（`environment.py` 只管田地和病害值），也不属于某一条敌人
自己的天赋（黑板里没有它们）。合进任何一边都会让那一层多出一堆
"顺便也管管"的分支。

【三条 rune，逐字来历】
* ``enemy_attribute_mul`` —— 黑板是「属性名 → 系数」，如
  ``atk 1.2 / def 1.2 / max_hp 1.2``。四条星难度的敌人整体变强 20%。
  黑板里若另有 ``enemy`` 键，则**该条的其余系数只作用于它点名的敌人**——
  `act31side_ex02` 就是这么用的（全局 1.2 的那条 + 只给
  `enemy_1395_dhxts_2` 的 `max_hp 1.5` 那条）。
* ``enemy_talent_blackb_mul`` —— ``enemy`` 点名一批敌人、其余键是
  「天赋黑板键 → 系数」。`act31side_ex07` 给 `enemy_1390_dhsbr_2|enemy_1392_dhshld_2`
  的 ``Passive.extra_value`` 乘 2，即被击倒时的田地污染由 +5/+15 变 +10/+30。
* ``enemy_skill_blackb_mul`` —— 同上，但多一个 ``skill`` 键点名**技能**
  （值是 `prefabKey`，如 `Drink`）。`act31side_ex04` 给 `enemy_1393_dhele_2`
  的 `Drink` 技能黑板 ``atk_scale_magic`` 乘 1.3（0.8 → 1.04）。

【两个不做的事，都很容易顺手做错】
1. **不许改到库里的对象**。`EnemyLibrary` 的 `EnemyStats` 是按敌人全库缓存的，
   乘数是按关生效的：不改副本就会把"这一关四星难度敌人更强"永久写进库里，
   下一关跟着一起变强，且不报错。
2. **不许只改黑板不重算派生字段**。天赋黑板乘完必须重跑一遍
   `EnemyStats.derive_blackboard_fields()`，否则 `Passive.extra_value` 是变了，
   而真正被读的 `passive_pollut` 没变——乘数落在一张没人再读的表上。

【`global_lifepoint`】
``value`` 就是这一关的生命点数。八关 EX 的 FOUR_STAR 档全都把它改写成 1，
而关卡文件自己的 `options.maxLifePoint` 是 3（普通与四星两份**都是 3**）
——不接这条，四星档就凭空多两条命，而模拟照常给出结果。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from .blackboard import bb_number, find_rune, mask_applies

__all__ = [
    "ATTR_MUL_KEY", "TALENT_MUL_KEY", "SKILL_MUL_KEY", "LIFEPOINT_KEY",
    "COST_MUL_KEY", "ATTR_FIELDS", "RuneMul", "parse_rune_muls",
    "apply_rune_muls", "wrap_enemy_at", "global_lifepoint",
    "cost_recovery_scale",
]

ATTR_MUL_KEY = "enemy_attribute_mul"
TALENT_MUL_KEY = "enemy_talent_blackb_mul"
SKILL_MUL_KEY = "enemy_skill_blackb_mul"
LIFEPOINT_KEY = "global_lifepoint"
COST_MUL_KEY = "cbuff_cost_recovery"

#: **同一机制的两代键名**。老活动的 runes 用的是 `gbuff_*` / `ebuff_*` 这一套，
#: 新活动换成了语义化的名字，黑板结构一模一样（都是 `value` / `atk+def+max_hp`）。
#: 例：`main_01-07`（1-7）的四星档就是 `gbuff_lifepoint` + `ebuff_attribute`。
#:
#: ⚠ 不认老名字的后果很具体：按四星档跑 1-7 时会**少算那条生命点改写**
#: （3 条命而不是 1 条），而模拟照常给出结果、不报错。
#: 两代名字都收，键名归一化到新名。
_ALIASES = {
    "gbuff_lifepoint": LIFEPOINT_KEY,
    "ebuff_attribute": ATTR_MUL_KEY,
}

#: `enemy_attribute_mul` 的黑板键 → `EnemyStats` 上的字段名。
#: 黑板用数据侧的 `def`，类里叫 `defense`；别的都同名。
#: **表里没有的键一律记进 `RuneMul.unknown`**，不静默丢弃——
#: 上游加了新属性（比如 `move_speed`）时，报告会立刻显示出来。
ATTR_FIELDS = {
    "atk": "atk",
    "def": "defense",
    "max_hp": "max_hp",
}

#: 黑板里用作**选择器**、不是系数的键。
_SELECTORS = frozenset({"enemy", "skill"})


@dataclass(frozen=True)
class RuneMul:
    """一条乘数 rune 解析后的样子。"""

    #: `attr` / `talent` / `skill`
    kind: str
    #: 点名了哪些敌人（空 = 该关全部敌人）
    enemies: frozenset[str]
    #: 点名了哪个技能（仅 `skill` 类；空 = 不指名）
    skill: str
    #: 键 → 系数（属性名 / 天赋黑板键 / 技能黑板键）
    factors: dict[str, float]
    #: 表里没有的键（属性类才有）——非空即上游加了新属性
    unknown: tuple[str, ...] = ()

    @property
    def scope(self) -> str:
        if not self.enemies:
            return "全部敌人"
        return "、".join(sorted(self.enemies))


def _bb_pairs(rune: dict) -> list[tuple[str, Any]]:
    """黑板取「键 → 值」。数值在 `value`、文本在 `valueStr`。

    ⚠ 判据与库内一致：**`valueStr` 非空才用它，否则用 `value`**。
    写成 `valueStr is not None` 会让空字符串顶掉真正的数值（然后 `float("")`
    报错、键被记成"不认识的属性"，看着像上游改了数据）。
    """
    out: list[tuple[str, Any]] = []
    for b in rune.get("blackboard") or []:
        key = b.get("key")
        if not key:
            continue
        sv = b.get("valueStr")
        out.append((key, sv if isinstance(sv, str) and sv.strip()
                    else b.get("value")))
    return out


def _parse_one(rune: dict, kind: str) -> RuneMul | None:
    """把一条 rune 的黑板拆成「选择器 + 系数表」。"""
    enemies: frozenset[str] = frozenset()
    skill = ""
    factors: dict[str, float] = {}
    unknown: list[str] = []
    for key, raw in _bb_pairs(rune):
        if key == "enemy":
            enemies = frozenset(
                x.strip() for x in str(raw or "").split("|") if x.strip())
            continue
        if key == "skill":
            skill = str(raw or "").strip()
            continue
        try:
            factors[key] = float(raw)
        except (TypeError, ValueError):
            unknown.append(key)
            continue
        if kind == "attr" and key not in ATTR_FIELDS:
            unknown.append(key)
    if not factors:
        return None
    return RuneMul(kind=kind, enemies=enemies, skill=skill,
                   factors=factors, unknown=tuple(unknown))


def parse_rune_muls(runes: Iterable[dict] | None,
                    difficulty: str = "NORMAL") -> list[RuneMul]:
    """把关卡 `runes` 里的三条乘数 rune 解析出来（按难度消歧）。

    同一个键可能有多条（如 `enemy_attribute_mul` 的全局条 + 点名条），
    所以这里返回的是**列表**而不是单条——`find_rune` 那种"取最后一条"
    会把全局那条整个吃掉。
    """
    out: list[RuneMul] = []
    for r in runes or []:
        key = _ALIASES.get(r.get("key"), r.get("key"))
        kind = {ATTR_MUL_KEY: "attr", TALENT_MUL_KEY: "talent",
                SKILL_MUL_KEY: "skill"}.get(key)
        if kind is None:
            continue
        if not mask_applies(r.get("difficultyMask"), difficulty):
            continue
        one = _parse_one(r, kind)
        if one is not None:
            out.append(one)
    return out


def apply_rune_muls(stats: Any, muls: Iterable[RuneMul]) -> Any:
    """把乘数作用到一份 `EnemyStats` 上，返回**可能是新对象**的 stats。

    没有任何一条命中时原样返回（同一个对象）——绝大多数关卡走这条，
    零拷贝开销。
    """
    out = stats
    enemy_id = str(getattr(stats, "enemy_id", "") or "")
    for m in muls:
        if m.enemies and enemy_id not in m.enemies:
            continue
        if out is stats:
            out = stats.clone()               # 见模块开头第 1 条
        if m.kind == "attr":
            for key, factor in m.factors.items():
                # 表里没有的键在解析时已记进 `unknown`，这里跳过——
                # `ATTR_FIELDS[key]` 会 KeyError，而那是"上游加了个新属性"，
                # 该出现在报告里，不该把整场模拟打崩。
                fname = ATTR_FIELDS.get(key)
                if fname is None:
                    continue
                cur = getattr(out, fname, None)
                if cur is None:
                    continue                  # 没这个属性就不凭空造一个 0
                setattr(out, fname, float(cur) * factor)
        elif m.kind == "talent":
            out.rescale_talent_blackboard(m.factors)
        else:
            out.rescale_skill_blackboard(m.skill, m.factors)
    return out


def wrap_enemy_at(base: Callable[[str, int], Any],
                  muls: Iterable[RuneMul]) -> Callable[[str, int], Any]:
    """把 `enemy_at` 包一层，出库的每个 `EnemyStats` 都过一遍乘数。

    包在**取数的出口**上而不是逐处调用点：模拟器里取敌人属性的地方有好几处
    （出怪、形态、报告），漏掉任何一处都会让乘数只生效一半。
    """
    muls = list(muls)
    if not muls:
        return base

    def at(enemy_id: str, level: int = 0):
        return apply_rune_muls(base(enemy_id, level), muls)

    return at


def global_lifepoint(stage: Any, difficulty: str = "NORMAL") -> int | None:
    """这一关的生命点数被 rune 改写成了几；没有这条就是 None（用关卡自己的）。"""
    raw = getattr(stage, "raw", None) or {}
    r = find_rune(raw.get("runes") or [], LIFEPOINT_KEY, difficulty)
    if r is None:                       # 老键名（`gbuff_lifepoint`）同样认
        r = find_rune(raw.get("runes") or [], "gbuff_lifepoint", difficulty)
    if r is None:
        return None
    v = bb_number(r.get("blackboard"), "value")
    return None if v is None else int(v)


def cost_recovery_scale(stage: Any, difficulty: str = "NORMAL") -> float:
    """费用回复速度的倍率（`cbuff_cost_recovery.scale`，没有就是 1.0）。

    原文没有一句中文描述，只有黑板上的 `scale`——语义从它在关卡里的位置
    反推：四星档把它设成 2，即「费用回复速度翻倍」，也就是**每点费用所需
    时间减半**。`cost_increase_time` 是"每点费用几秒"，所以这里是**除**。
    """
    raw = getattr(stage, "raw", None) or {}
    r = find_rune(raw.get("runes") or [], COST_MUL_KEY, difficulty)
    if r is None:
        return 1.0
    v = bb_number(r.get("blackboard"), "scale")
    return float(v) if v else 1.0
