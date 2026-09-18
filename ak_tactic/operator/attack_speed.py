"""攻速加成的取数层：天赋（常驻）与模组特性（可能带条件）。

战斗单位的出手频率取决于**总攻速** = 基础 100 + 天赋 + 模组特性 + 技能。
技能那一路由 `SkillEffects.buffs["attack_speed"]` 负责；本模块补的是前两项，
它们此前整体缺失——`OperatorUnit.attack_speed` 一直停在默认的 100，
于是任何靠攻速天赋吃饭的干员出手频率都被低估。

两侧的形状并不一样：

* **天赋**（`character_table.talents`）是无条件常驻，按精英阶段／等级／潜能选档，
  `talent.resolve_talents` 已经做对了这件事，这里只负责把黑板读出来。
* **模组特性**（`battle_equip_table[].phases[].parts` 的 `overrideTraitDataBundle`）
  改写的是**特性**，而且可能带条件。赤刃明霄陈的 `uniequip_002_chen3` 三级一致地
  把特性改成「未阻挡敌人时攻击速度 +8」——这一项**不能并进常驻值**，必须交给
  战斗单位逐帧按"当前有没有挡住敌人"来判。把它当常驻会白送，
  当不存在则少算 8 点攻速（本关主输出，实测差 6% 的出手频率）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .talent import PHASE_INDEX, resolve_talents

__all__ = [
    "AttackSpeedBonus",
    "talent_attack_speed",
    "module_attack_speed",
    "attack_speed_bonus",
]

#: 带这些字的特性是**条件性**加成，不能算进常驻值。
CONDITION_MARKERS = ("未阻挡", "未被阻挡", "不阻挡")


@dataclass(frozen=True)
class AttackSpeedBonus:
    """一名干员在某个练度下的攻速加成。"""

    #: 无条件常驻，直接加到 `OperatorUnit.attack_speed` 上。
    flat: float = 0.0
    #: 只在**未挡住任何敌人**时生效，交给 `OperatorUnit.aspd_when_free`。
    when_free: float = 0.0
    #: 只在**自身周围四格有高台**时生效（阿斯卡纶「噬光残影」）。条件由地形
    #: 承载，不是实时状态——模拟器在部署那一刻按地图判一次。
    when_high_ground: float = 0.0
    #: 出处，供对账时打印。
    sources: tuple[str, ...] = field(default_factory=tuple)

    @property
    def total(self) -> float:
        """各段相加——用于"纸面上最多能有多少"的估值，不用于结算。"""
        return self.flat + self.when_free + self.when_high_ground

    def describe(self) -> str:
        if not self.sources:
            return "无攻速加成"
        head = f"+{self.flat:g}"
        if self.when_free:
            head += f"（未阻挡时再 +{self.when_free:g}）"
        if self.when_high_ground:
            head += f"（周围四格有高台时再 +{self.when_high_ground:g}）"
        return f"{head} ← " + "、".join(self.sources)


def talent_attack_speed(char: dict, *, elite: int = 2, level: int = 1,
                        potential: int = 1) -> tuple[float, float, tuple[str, ...]]:
    """天赋给的攻速加成，返回 `(常驻, 周围四格有高台时, 出处)`。

    天赋的攻速是绝对值（黑板键 `attack_speed`，与技能的 `+50` 同一量纲），
    不是百分比——按百分比理解会得到荒谬的间隔。

    **`attack_speed_add` 是另一个量**：同一块黑板里它表示"满足某个条件时
    再给多少"。已全表核验，**全库只有阿斯卡纶「噬光残影」一处**用它，
    且正文写明条件是「**自身周围四格有高台时**」。所以这里可以放心把
    `attack_speed_add` 等同于"高台条件加成"；**若日后有第二个人用这个键，
    必须先看他的正文再决定，不能默认也是高台**——那会静默给错条件。
    """
    flat = 0.0
    high = 0.0
    sources: list[str] = []
    for t in resolve_talents(char, elite=elite, level=level, potential=potential):
        v = t.value("attack_speed")
        if v:
            flat += v
            sources.append(f"天赋「{t.name}」+{v:g}")
        add = t.value("attack_speed_add")
        if add:
            high += add
            sources.append(f"天赋「{t.name}」（周围四格有高台时）+{add:g}")
    return flat, high, tuple(sources)


def module_attack_speed(parts: Any, *, elite: int = 2, level: int = 1,
                        potential: int = 1) -> tuple[float, float, tuple[str, ...]]:
    """模组 `parts` 改写的特性所给的攻速。

    返回 `(常驻, 未阻挡敌人时, 出处)`。每个 candidate 自带 `unlockCondition`
    （阶段/等级）与 `requiredPotentialRank`，未解锁的不计——模组的特性改写
    同样不是一装上就有，例如 `uniequip_002_chen3` 要求精二 60 级。
    """
    flat = 0.0
    free = 0.0
    sources: list[str] = []
    have_pot = max(0, potential - 1)
    for part in parts or ():
        bundle = (part or {}).get("overrideTraitDataBundle") or {}
        for cand in bundle.get("candidates") or ():
            uc = cand.get("unlockCondition") or {}
            if PHASE_INDEX.get(uc.get("phase"), 0) > elite:
                continue
            if int(uc.get("level") or 1) > level:
                continue
            if int(cand.get("requiredPotentialRank") or 0) > have_pot:
                continue
            value = 0.0
            for b in cand.get("blackboard") or ():
                if b.get("key") == "attack_speed" and b.get("value"):
                    value += float(b["value"])
            if not value:
                continue
            text = " ".join(
                str(cand.get(k) or "") for k in
                ("additionalDescription", "overrideDescripton", "description"))
            label = (text.replace("<@ba.kw>", "").replace("</>", "")
                         .replace("{attack_speed}", f"{value:g}").strip()
                     or "模组特性")
            if any(m in text for m in CONDITION_MARKERS):
                free += value
                sources.append(f"特性「{label}」（未阻挡时）")
            else:
                flat += value
                sources.append(f"特性「{label}」")
    return flat, free, tuple(sources)


def attack_speed_bonus(calc: Any, char_id: str, *, elite: int = 2, level: int = 1,
                       potential: int = 1, module: str | None = None,
                       module_level: int = 0) -> AttackSpeedBonus:
    """把两个来源合起来——调用点只需要这一句。

    `calc` 是 `OperatorCalculator`（用来取干员本体与模组 `parts`）。
    `module_level` 为 0 或 `module` 为空时不看模组。
    """
    char = calc.character(char_id)
    flat, high, sources = talent_attack_speed(char, elite=elite, level=level,
                                              potential=potential)
    free = 0.0
    if module and module_level:
        m_flat, m_free, m_src = module_attack_speed(
            calc.module_parts(module, int(module_level)),
            elite=elite, level=level, potential=potential)
        flat += m_flat
        free += m_free
        sources += m_src
    return AttackSpeedBonus(flat=flat, when_free=free,
                            when_high_ground=high, sources=sources)
