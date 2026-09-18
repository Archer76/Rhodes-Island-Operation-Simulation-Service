# -*- coding: utf-8 -*-
"""撼地者的技3「无可抵挡」：正前方一格的**五连锤击**。

## 为什么要单独一个模块

这是仓库里第一条「**技能自己打一轮**」的通道。在此之前技能开启时只有一步
主动效果（`sim._apply_push` 的推击），伤害一律由普攻循环产生；而这一条是
**不吃攻速的固定 1.8 秒间隔五连击**，挂进普攻循环就必然错。

## 语义出处（prts.wiki「怒潮凛冬」页 技3 备注，逐条对黑板）

> ※锤击间隔 **1.8s**（动画间隔与攻击间隔正好相同可能对玩家的判断产生误导，
> 实际上该技能为发动一次连续的"五连击"，**不受攻击速度影响**），每次锤击以
> **正前方 1.0 距离位置为中心**（会尝试选择前方 1 格的一个单位，将其视为攻击
> 主目标；通常情况下锤击不存在主目标），对主目标与溅射目标的伤害必定显示伤害红字
>
> ※主攻击拥有 **1.5 的溅射半径**
>
> ※第二次锤击起，所有本次锤击触发第一天赋的高台生效时将令相邻的未受影响的
> 高台触发第一天赋（即扩散），最大扩散次数等同于当前已完成锤击次数；
> 不论如何，一轮锤击中每个高台只会触发一次天赋效果。

黑板（`skill_level.blackboard`，专精 3 / 7 级）：

    {atk_base: 1.0, atk_scale: 2.4, atk_step: 0.3,
     splash_atk_scale_bonus: 3.5, unmovable: 2.0}

* `atk_base` = 技能期间攻击力 **+100%**（`skill.py` 把它并进 `atk` 那一桶）；
* `atk_scale` = 每击造成 **240%** 攻击力物理伤害；
* `atk_step` = **每击之后**攻击力额外 **+30%**（累加，作用于后续锤击）；
* `splash_atk_scale_bonus` = 技能期间**高台溅射伤害 ×3.5**（24% → 84%）；
* `unmovable` = 控制效果**从 0.5 秒停顿改为 2 秒【束缚】**。

## 若干处按已有资料的口径（不是猜，但每条都留了出处或标注）

* **每击的攻击力**按 `1 + atk_base + atk_step × i`（i 从 0 起）算。文本的语序是
  「每次造成…**并使**攻击力额外+30%」，即加成落在该击**之后**；两个都是
  "攻击力+X%"，在同一个乘区里相加，不是逐次相乘。
* **溅射半径 1.5** 只来自 wiki 备注（数据里没有这个字段），所以它写死在
  `HAMMER_SPLASH_RADIUS` 并带守卫。**这个数还反过来钉住了判据本身**：半径
  1.5 时正交两格的地块离圆心最近的点距离**正好是 1.5**，判据若取严格小于，
  1.5 与特性原本的 1.0 会盖出**同一片** 3×3，技能正文那句「溅射范围更大」
  就成了空话。所以圆是**闭圆**（`<= r + eps`）：1.0 → 九格、1.5 → 十三格。
  "更大必须真的更大"是这条数据给出的硬约束，不是审美。
* **高台触发用的就是这 1.5 的圆盖到的地块**。备注里另有一句被注释掉的
  `<!--，1.0的第一天赋判定半径-->`——说明"高台判定半径是 1.0 还是 1.5"连
  wiki 自己都没定；这里取 **1.5**（与该次锤击的溅射范围一致），
  已记进 `docs/uncertainties.md`，等实机录屏裁定。
* **对空**：备注只说「前方 1 格的一个单位」，没有地面限定，所以不排除空中；
  高台那一半仍按天赋正文只打**地面**敌人（两者不同源，别合并）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "HAMMER_ATK_KEY", "HAMMER_HITS", "HAMMER_INTERVAL", "HAMMER_KEYS",
    "HAMMER_ROOT_KEY", "HAMMER_SPLASH_RADIUS", "HammerStrike", "read_hammer",
]

#: 判据键：三个同时在场才算这条技能。**不含 `atk_base` / `unmovable`**——
#: 后者是控制类的通用键，别处也用（`skill.CONTROL_KEYS`），拿它当判据会把
#: 别的技能误认成五连锤击。
HAMMER_KEYS: tuple[str, ...] = ("atk_scale", "atk_step", "splash_atk_scale_bonus")
HAMMER_ATK_KEY = "atk_base"
HAMMER_ROOT_KEY = "unmovable"

#: 五连击：次数与间隔都不吃攻速（wiki 备注明写）。
HAMMER_HITS = 5
HAMMER_INTERVAL = 1.8

#: 主攻击的溅射半径（wiki 备注：1.5，比特性的 1.0 大）。
HAMMER_SPLASH_RADIUS = 1.5


@dataclass(frozen=True)
class HammerStrike:
    """一次五连锤击的全部系数（不随每击变化的部分）。"""

    #: 技能自身的攻击力加成（`atk_base`，M3 = 1.0 即 +100%）。
    atk_pct: float
    #: 每击的伤害倍率（`atk_scale`，M3 = 2.4）。
    atk_scale: float
    #: 每击之后攻击力额外加成（`atk_step`，M3 = 0.3）。
    atk_step: float
    #: 主攻击的溅射半径（格）。
    splash_radius: float
    #: 高台溅射伤害的倍数（`splash_atk_scale_bonus`，M3 = 3.5）。
    highland_bonus: float
    #: 控制效果：【束缚】秒数（`unmovable`，M3 = 2.0；0 = 沿用【停顿】）。
    root: float

    @property
    def hits(self) -> int:
        return HAMMER_HITS

    @property
    def interval(self) -> float:
        return HAMMER_INTERVAL

    def atk_multiplier(self, index: int) -> float:
        """第 `index` 击（0 起）吃到多少倍的攻击力。

        两个加成都在同一个乘区里相加：`1 + atk_base + atk_step × i`。
        把 `atk_step` 当成逐次相乘（`1.3^i`）在 M3 的第五击上会多算三成。
        """
        return 1.0 + self.atk_pct + self.atk_step * index

    def total_multiplier(self) -> float:
        """一轮五击的等效总倍率（按裸攻击力算），只为守卫与文档对账用。"""
        return sum(self.atk_multiplier(i) * self.atk_scale
                   for i in range(HAMMER_HITS))


def read_hammer(blackboard: Mapping[str, Any] | None) -> HammerStrike | None:
    """从技能黑板读出五连锤击的系数；不是这条技能就返回 `None`。

    **判据是三个键同时在**（`HAMMER_KEYS`），不是"有没有 `atk_scale`"——
    带 `atk_scale` 的技能全库有一大把，拿它当判据会让一堆技能凭空开始锤地。
    """
    if not blackboard:
        return None
    if any(key not in blackboard for key in HAMMER_KEYS):
        return None
    return HammerStrike(
        atk_pct=float(blackboard.get(HAMMER_ATK_KEY) or 0.0),
        atk_scale=float(blackboard["atk_scale"] or 0.0),
        atk_step=float(blackboard["atk_step"] or 0.0),
        splash_radius=HAMMER_SPLASH_RADIUS,
        highland_bonus=float(blackboard["splash_atk_scale_bonus"] or 0.0),
        root=float(blackboard.get(HAMMER_ROOT_KEY) or 0.0),
    )
