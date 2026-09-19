# -*- coding: utf-8 -*-
"""敌方的三条**规矩**——判"清不清得掉""用哪一档""砸下什么"。

这三个原本是 `BattleSimulator` 的方法（`sim.py:1530 / 2606 / 4575`），
但读一遍就会发现它们**跟引擎状态无关**：

| 函数 | 它到底读了什么 |
|---|---|
| `cannot_clear(unit)` | 单位自己的 `always_invincible` ＋ `route_length` |
| `summon_level(stage, key)` | `stage.enemy_refs` |
| `pile_mark_key(stage, diver)` | `PROSE_SUMMON_EDGES`（**gamedata**）＋ `stage.local_enemy_prefab` |

所以它们能搬进 `frontend/`，`battle/sim.py` 的那三个方法改成**转调这里**
（一份实现、两个消费者），`spec.py` 也可以直接调这里、不再经过模拟器。

## 为什么值得先搬这三个

`tools/spec_deps.py` 量出的 7 个 `sim.<方法>` 调用里，这三个是**唯一不需要造对象**的
——另外四个（`_spawn` / `_build_enemy` / `_range_of` / `_path_from`）要 `EnemyUnit`
或地图寻路。先把便宜的摘掉，硬骨头的边界就更清楚。

## `cannot_clear` 的判据来源（原文两条，都写在数据里）

「既打不死、又不会离场」的单位清不掉：只要把它算进完成判据，这一局就永远结束不了
（跑满时间上限、0 星）。目前只有怀黍离的天桩-甲满足：

* **打不死**：监测形态持有「无敌、不死」，落成 `always_invincible`；
  激活状态会摘掉它，但那时甲会**每秒自损 1% 最大生命**，自己会死——所以照旧算数。
* **不会离场**：它天赋第一句是「自缚」，模拟器给它的是**单点路线**
  （`route_length == 0`；`reached_end` 要求长度 > 0，单点路线永不判漏）。

⚠ 两个条件**同时**成立才算"清不掉"。只满足一个的不算：能走的无敌单位会自己走掉
（照样能结束这一局），会死的自缚单位会被打死。
"""
from __future__ import annotations

from typing import Any

from ..gamedata.enemy import PROSE_SUMMON_EDGES
from ..gamedata.stage import branch_prefix

__all__ = ["PILE_MARK", "cannot_clear", "summon_level", "pile_mark_key",
           "pile_spec"]

#: 装置 key → 它召唤的甲的 key（**退路**，正常走 `_pile_spec` 的结构化查询）
PILE_CHILD = {
    k: v[0] for k, v in PROSE_SUMMON_EDGES.items() if k.startswith("trap_")
}
#: 乙的 key → 它命中时召唤的天标的 key（这一跳**仍然只能查表**：乙的黑板是空的）
#:
#: ⚠ 与 `sim.py` 里那张是**同一张表推出来的**（原来就写在 `sim.py:144`），
#: 搬过来是为了让 `pile_mark_key` 能跟着搬——两边各写一遍必然走散。
PILE_MARK = {
    k: v[0] for k, v in PROSE_SUMMON_EDGES.items() if k.startswith("enemy_")
}


def cannot_clear(unit: Any) -> bool:
    """这个单位**有没有可能被清掉**——要么被打死，要么走到目标点。

    判据的两条依据见模块头。⚠ 是**并且**，不是或者。
    """
    return (bool(getattr(unit, "always_invincible", False))
            and float(getattr(unit, "route_length", 0.0)) == 0.0)


def summon_level(stage: Any, enemy_key: str) -> int:
    """被召唤的敌人用哪一档数值。

    先看这一关的 `enemyDbRefs` 有没有点名它（有就按那一档），
    没有就用 0 档——**不猜**。召唤体往往不在关卡的出怪表里，
    所以这条回退路径是常态而不是异常。
    """
    for ref in (getattr(stage, "enemy_refs", None) or []):
        if str(ref.get("id") or "") == enemy_key:
            try:
                return int(ref.get("level") or 0)
            except (TypeError, ValueError):
                return 0
    return 0


def pile_mark_key(stage: Any, diver: Any) -> str:
    """天桩-乙 → 它砸下的**身上的天标**。

    乙的天赋黑板是**空的**（`talentBlackboard: []`），"砸下什么"只写在正文里，
    所以走 `PROSE_SUMMON_EDGES` 推出的 `PILE_MARK` 那张表；关卡本地的
    ``…_dhtb_b`` 先退到它的 ``prefabKey``（``enemy_1399_dhtb``）再查表。
    """
    key = PILE_MARK.get(diver.enemy_id)
    if key:
        return key
    return PILE_MARK.get(stage.local_enemy_prefab(diver.enemy_id), "")


def pile_spec(stage: Any, device: Any) -> tuple[str, Any]:
    """装置 → **它召唤的那名天桩-甲**，以及关卡给它指派的那条路径。

    ⚠ 原样搬自 `BattleSimulator._pile_spec`（`sim.py:4493`，36 行）——它**只用
    `self.stage`**，其余全是结构化字段查询，所以"一次都没进过引擎状态"。
    搬过来之后 `sim` 上那个方法只剩转调，`mech.py` 也不必再向模拟器借手。

    这一段**全是结构化字段**，不用猜正文（`PILE_CHILD` 表已降级为退路）：

    装置 predefine 的 ``overrideSkillBlackboard[branch_id]``（关卡没写覆盖时
    退回技能默认黑板 ``branch_dhdcr_1``，见 `Stage.branch_for`）
    → 关卡 ``branches[branch_id].phases[].actions[]``
    → ``key`` 是甲（``enemy_1398_dhdcr`` / 失控 ``_2`` / 关卡本地 ``_b``），
    ``routeIndex`` 指向关卡 ``extraRoutes``（**与出怪表用的 ``routes``
    是两个命名空间**）。

    ⚠ 这条路径**不是甲的行进计划**。甲的天赋第一句就是「自缚」（不能移动），
    它站在原地监测脚下那格的病害值。全活动 32 个天桩逐关核过：**每个装置格
    都等于它那条路径的起点格**。路径因此只作留档与交叉校验用
    （`tools/check_environment.py` §11 会核"起点 == 装置格"），甲不执行它。

    整条都查不到时退回 `PILE_CHILD`（并返回 `("", None)`），模拟照跑。
    """
    bid = str(getattr(device, "branch_id", "") or "")
    # 装置 key 末段 → 支线前缀（`trap_146_dhdcr` → `branch_dhdcr`）。
    # 这一道把**没有支线语义**的装置挡在外面：阻流阀/泵站推不出
    # `branch_dhtl` / `branch_dhsb`，于是它们不会误领天桩那条支线
    # （踩过：不挡的话 act31side_08 的 26 个装置会各召唤一名甲）。
    branch = stage.branch_for(bid, prefix=branch_prefix(device.key))
    for act in stage.branch_actions(branch):
        if not act.enemy_key:
            continue
        return (act.enemy_key, stage.extra_route(act.route_index))
    if device.key not in PILE_CHILD:
        return ("", None)
    return (PILE_CHILD[device.key], None)
