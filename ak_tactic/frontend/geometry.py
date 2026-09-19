# -*- coding: utf-8 -*-
"""两条**几何**：干员的攻击格集合、从某格到保护目标的路。

两个原本是 `BattleSimulator` 的方法（`sim.py:663` / `sim.py:1550`），但读一遍会发现
它们**不吃引擎状态**：

* `range_of` 吃的是干员身上的一把**数据**（`char_id` / `elite` / `direction` /
  `position` ＋ 技能改写的范围代号）和一个**取数钩子**（`range_provider`）；
* `path_from` 只吃 `stage.map`。

所以它们能搬进 `frontend/`，`battle/sim.py` 的那两个方法改成**转调这里**
（一份实现、两个消费者）。

## ⚠ 一处顺带修掉的坏味道

原版 `spec.py` 为了"算某个**假设位置**上的范围"，是**先篡改干员对象、再调
`sim._range_of(op)`**（`spec.py:349-350` 与 `645-646` 都这么写）：

    op.position = (f["cell"][0], f["cell"][1])
    op.direction = f["direction"]
    cells = sim._range_of(op)

新接口把位置与朝向**当参数传**，于是"算一个假设位置上的范围"不再需要动任何对象。
⚠ 但 `spec.py` 那两处的赋值**仍然保留**——后面还有别的读法（`op.current_atk()` /
`current_defense()` 要吃位置上的光环）依赖它。这里只把范围那一问改成显式传参。

## `DIRECTIONS` 为什么也搬过来

`OperatorUnit.facing`（`unit.py:741`）是 `DIRECTIONS.get(self.direction, (1, 0))`，
而 `DIRECTIONS` 原本住在 `battle/devices.py:121`。既然 `range_of` 要用朝向，
搬过来才能让 `frontend/` **不 import `battle/`**。`battle/devices.py` 改成从这里转出。
"""
from __future__ import annotations

import math
from typing import Any, Callable, Iterable

__all__ = ["DIRECTIONS", "facing", "current_range_id", "range_of", "path_from",
           "path_length"]


def path_length(points: list[tuple[float, float]]) -> float:
    """折线总长（格）。

    ⚠ 定义原本在 `battle/unit.py:54`，搬到这里是因为 `route_length`（敌方路线总长、
    `cannot_clear` 判"自缚"要读）在**没有分段腿时**退回按折线算，而新家不许
    import `battle/`。`battle/unit.py` 改成从这里转出。

    ⚠ 别"顺手优化"成下标循环 + `sqrt(dx*dx+dy*dy)`：原版在 `point_at` 上量过，
    手写平方和反而**慢 3.6%**（`math.dist` 是一次 C 调用）。这里是同一套口径。
    """
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))

#: 朝向 → 单位向量。y 向下为正，所以「上」是 (0, -1)。
#:
#: ⚠⚠ **本表是 Title Case（`"Right"` / `"Left"` / `"Up"` / `"Down"`）**，
#: 与 `battle/devices.py` 那张 **UPPER**（`"LEFT"` / `"RIGHT"` / `"UP"` / `"DOWN"`）
#: **是两张不同的表**——它们各自的消费者不同：干员的 `direction` 是 Title Case，
#: 装置的朝向是 UPPER。**千万别合并**：合并了不会报错，只会让 `"Left"`
#: 在另一张表里查不到、静默落回默认值 `(1, 0)`，即**方向反了**。
#:
#: 定义原本在 `battle/unit.py:22`，搬到这里是因为 `range_of` 的退化范围要按朝向推
#: 前方三格，而 `frontend/` 不许 import `battle/`。`battle/unit.py` 改成从这里转出。
DIRECTIONS: dict[str, tuple[int, int]] = {
    "Right": (1, 0), "Left": (-1, 0), "Up": (0, -1), "Down": (0, 1),
}


def facing(direction: str) -> tuple[int, int]:
    """朝向 → 单位向量。认不出的一律朝右（`(1, 0)`），与原版一致。"""
    return DIRECTIONS.get(direction, (1, 0))


def current_range_id(skill: Any, skill_active: bool) -> str | None:
    """开技能期间被改写的攻击范围代号，没有就是 None。"""
    if skill_active and skill is not None:
        return getattr(skill, "range_id", None)
    return None


def range_of(range_provider: Callable[..., Any] | None, *,
             char_id: str, elite: int, direction: str,
             position: tuple[float, float],
             range_id: str | None = None) -> set[tuple[int, int]]:
    """干员当前的攻击格集合——技能改了范围就用技能给的那个代号。

    ⚠ 两条**退化/兜底**行为是原样搬的，别顺手"清理"：

    * 取数钩子**不接受 `range_id` 关键字**时（自定义 provider）退回调四参数的写法；
    * 钩子抛任何异常 → 整个 `except Exception: pass` 吞掉，走下面的退化范围。
      这条不是"不该发生"，而是"取不到也要能跑完"——规格里少几格会被
      金标准抓出来，比当场崩掉好定位。
    """
    if range_provider is not None:
        try:
            try:
                cells = range_provider(char_id, elite, direction, position,
                                       range_id=range_id)
            except TypeError:
                # 自定义的 range_provider 未必接受 range_id
                cells = range_provider(char_id, elite, direction, position)
            if cells:
                return cells
        except Exception:                                        # noqa: BLE001
            pass
    # 退化：自身格 + 朝向前方三格
    fx, fy = facing(direction)
    ox, oy = position
    return {(ox, oy)} | {(ox + fx * i, oy + fy * i) for i in (1, 2, 3)}


def path_from(stage: Any, cell: tuple[int, int]) -> list[tuple[int, int]]:
    """从 `cell` 走到**最近的可达保护目标**的那条路。

    逐目标试 `ground_path`（它不可达时返回空），取第一条走通的——
    「最近」按**路径长度**而不是直线距离算：绕远路的直线距离可能更近。
    """
    m = stage.map
    best: list[tuple[int, int]] = []
    for goal in m.end_points:
        p = m.ground_path(cell, goal)
        if not p:
            continue
        if not best or len(p) < len(best):
            best = list(p)
    return best
