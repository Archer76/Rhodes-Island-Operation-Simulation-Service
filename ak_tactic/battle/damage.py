"""伤害结算。

明日方舟的伤害分三类，物理和法术的公式**完全不同**：

* **物理**：``max(ATK × scale − DEF, ATK × scale × 5%)`` —— 有 5% 保底。
  所以防御高于攻击力时不是打不动，而是稳定刮 5%。SR-EX-8 的「沉默收音机」
  防御 1750 就是靠这条把一切平A压成 5%。
* **法术**：``max(ATK × scale × (1 − RES/100), ATK × scale × 5%)`` —— **同样有 5% 保底**。
* **真实**：``ATK × scale`` —— 无视防御与法抗，无保底。

**5% 保底是 2026-09-16 博士裁定加上去的**（此前只对物理生效）。分歧在于
wiki.gg 的 Damage 页与 xulai1001/akdata 都说「不论伤害类型」，而
wxhwwla/calc-framework 只对物理保底。实机影响：SR-EX-8 的「吓人路灯」
法抗 99，无保底时只吃 1%，有保底时吃 5%（**五倍**）。

保底有一个**故意的例外**：``RES >= 100`` 仍然结算为 0。理由是「法抗 100 = 免疫」
是另一条独立的游戏规则，不是「减免到很低」的极限情形；把保底盖上去会让
免疫不再免疫。若博士认为该例外也该去掉，改 ``_IMMUNE_RES`` 一处即可。

三者之后还要过一遍最终乘区（脆弱 / 法术脆弱 / 伤害加成与减免）。

法抗会被夹到 ``[-100, 100]``：-100 表示受到双倍伤害，100 表示免疫。
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = ["DamageType", "DamageResult", "resolve_damage", "physical", "arts", "true_damage"]

#: 伤害保底比例——物理与法术都按「攻击力 × 这个值」兜底
DAMAGE_FLOOR = 0.05

#: 旧名。**保留**是因为外部可能还在引用，语义等同 `DAMAGE_FLOOR`。
PHYSICAL_FLOOR = DAMAGE_FLOOR

#: 法抗达到这个值即为免疫——保底**不**覆盖它（见模块文档的例外说明）
_IMMUNE_RES = 100.0

#: 法术抗性的上下限
RES_MIN, RES_MAX = -100.0, 100.0


class DamageType:
    PHYSICAL = "PHYSICAL"
    MAGIC = "MAGIC"
    TRUE = "TRUE"
    HEAL = "HEAL"


@dataclass
class DamageResult:
    """一次结算的完整账，便于核对「为什么只打出这么点」。"""

    raw: float          #: 结算前的攻击力 × 倍率
    final: float        #: 最终伤害（未取整）
    type: str
    floored: bool = False   #: 是否吃到了物理 5% 保底
    mitigated: float = 0.0  #: 被防御/法抗吃掉的部分

    @property
    def value(self) -> int:
        """面板上看到的伤害——游戏向下取整。"""
        return int(math.floor(self.final + 1e-9))

    def __float__(self) -> float:
        return self.final


def resolve_damage(
    atk: float,
    *,
    damage_type: str = DamageType.PHYSICAL,
    scale: float = 1.0,
    defense: float = 0.0,
    res: float = 0.0,
    ignore_defense: float = 0.0,
    ignore_res: float = 0.0,
    defense_reduce: float = 0.0,
    res_reduce: float = 0.0,
    fragile: float = 0.0,
    final_multiplier: float = 1.0,
) -> DamageResult:
    """结算一次伤害。

    :param atk: 攻击方最终攻击力
    :param damage_type: `PHYSICAL` / `MAGIC` / `TRUE`
    :param scale: 技能给的伤害倍率（「造成相当于攻击力 480% 的伤害」→ 4.8）
    :param defense: 受击方最终防御力
    :param res: 受击方最终法术抗性（百分数，99 表示 99%）
    :param ignore_defense: 无视防御的固定值
    :param ignore_res: 无视法抗的**点数**（不是百分比）
    :param defense_reduce: 削减防御的固定值（如「防御力 −200」）
    :param res_reduce: 削减法抗的点数
    :param fragile: 脆弱 / 法术脆弱等最终增伤，0.3 表示 +30%
    :param final_multiplier: 其它最终乘区
    """
    raw = atk * scale
    floored = False
    mitigated = 0.0
    floor = raw * DAMAGE_FLOOR

    if damage_type == DamageType.PHYSICAL:
        eff_def = max(0.0, defense - ignore_defense - defense_reduce)
        dealt = raw - eff_def
        if dealt < floor:
            dealt = floor
            floored = True
        mitigated = raw - dealt
    elif damage_type == DamageType.MAGIC:
        eff_res = min(RES_MAX, max(RES_MIN, res - ignore_res - res_reduce))
        if eff_res >= _IMMUNE_RES:
            # 法抗满值 = 免疫，**保底不覆盖**（见模块文档的例外说明）
            dealt = 0.0
        else:
            dealt = raw * (100.0 - eff_res) / 100.0
            if dealt < floor:
                dealt = floor
                floored = True
        mitigated = raw - dealt
    elif damage_type == DamageType.TRUE:
        dealt = raw
    else:
        raise ValueError(f"未知的伤害类型：{damage_type}")

    dealt *= (1.0 + fragile) * final_multiplier
    return DamageResult(raw=raw, final=dealt, type=damage_type,
                        floored=floored, mitigated=mitigated)


def physical(atk: float, defense: float, **kw) -> DamageResult:
    return resolve_damage(atk, damage_type=DamageType.PHYSICAL, defense=defense, **kw)


def arts(atk: float, res: float, **kw) -> DamageResult:
    return resolve_damage(atk, damage_type=DamageType.MAGIC, res=res, **kw)


def true_damage(atk: float, **kw) -> DamageResult:
    return resolve_damage(atk, damage_type=DamageType.TRUE, **kw)
