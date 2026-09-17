# -*- coding: utf-8 -*-
"""召唤物：把 `SummonBook` 解析出的 token 变成战场上真能站住的单位。

## 为什么召唤物能直接复用一个"干员"单位

`BattleSimulator` 的主循环有三处是**均匀遍历 `self.operators`** 的——
阻挡（`_update_blocking`）、敌人索敌（`_enemy_target`）、干员出手
（`_operators_attack`）。所以召唤物只要是挂好 `summon_of` 的 `OperatorUnit`、
塞进那个列表，**阻挡 / 被打 / 出手三件事就自动成立**，不必在模拟器里另开
一条并行通道。

范围也是白拿的：`_range_of` 走 `range_provider(char_id, elite, ...)`，
而 `operator_phase` 表里**有 token 的行**（戴乌 → `0-1`、清平 → `1-1`、
棋子 → `0-1`），`attack_range` 有对应格。所以召唤物不必特判范围。

属性也不走这条模块——`operator_attr` 里 token 的 `kind='phase'` 行是齐的。
本模块只用 `SummonBook`（读 gamedata 的 `excel/`），因为那是"脱离本地库也能跑"
的那条路，与 `ak_tactic/operator/` 的其余部分一致。

## 尚未建模（别当成已支持）

- **召唤者退场后召唤物消失**：实机如此，这里**没做**。要做就得在 `run()`
  的主循环里加一条级联，容易与其他离场路径打架，先留着。
- **技能开启时"获得 1 个召唤物"**：电弧/令/圣聆初雪都写了这句，说的是
  **可动用总量 +1**（`pool`），不是凭空多一个已部署的。没做。
- **令技3 的高级形态合并**、**电弧技3 的协同攻击**、**令技1/2 的伤害类型改写**、
  **电弧技1 的屏障**：都属于技能侧，本条只负责"放下去并站住"。
- **望的棋子**：它是"摆下去等敌人踩"的触发式单位（`block_cnt=0`），
  与召唤师那套"放下去打架"不同，本条只把它当普通单位放下。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..operator.summons import SummonBook
from .unit import OperatorUnit

__all__ = ["SummonDeployment", "build_summon_unit"]


@dataclass
class SummonDeployment:
    """一次召唤物部署。

    :param owner: **召唤者的 `char_id`**。不是可选的语义——同时部署上限、
        归属、以及日后的"主人退场"都靠它。留空会在模拟器里被拒收。
    :param elite: 召唤物取哪个阶段的属性。**当前按"跟召唤者同精英阶段"处理**，
        这是从数据形态推的假设，未见实机确认（见 `docs/batch2-plan.md`）。
    :param attack_type: 伤害类型。**token 表里没有这个字段**，只能从技能描述
        得知（例：令技1「召唤物伤害类型变为法术」），所以由调用方给，
        默认物理。技能侧接管之前不会自动改写。
    """

    time: float
    token_key: str
    position: tuple[int, int]
    direction: str = "Right"
    owner: str = ""
    elite: int = 2
    level: float | None = None
    attack_type: str = "PHYSICAL"
    #: 预留：日后再挂技能/天赋用，现在不参与结算。
    talents: list = field(default_factory=list)


def build_summon_unit(d: SummonDeployment, *, book: SummonBook | None = None,
                      cost: int | None = None) -> OperatorUnit:
    """按一次部署造出召唤物的单位对象（**不入场**，入场由模拟器负责）。

    :param cost: 覆盖费用。默认取 token 自己的 `cost`。
    """
    book = book or SummonBook()
    a = book.attributes(d.token_key, phase=d.elite, level=d.level)
    return OperatorUnit(
        name=a.name,
        max_hp=a.max_hp,
        atk=a.atk,
        defense=a.defense,
        res=a.res,
        attack_interval=a.attack_interval or 1.0,
        attack_type=d.attack_type,
        char_id=d.token_key,
        summon_of=d.owner,
        position=tuple(d.position),
        direction=d.direction,
        block_cnt=a.block_cnt,
        deploy_cost=int(a.cost) if cost is None else int(cost),
        elite=d.elite,
        attack_speed=a.attack_speed,
        talents=list(d.talents or []),
    )
