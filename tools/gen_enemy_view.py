# -*- coding: utf-8 -*-
"""从 `BattleSimulator._build_enemy` **机械生成** `ak_tactic/frontend/enemy_view.py`。

## 为什么要生成而不是手抄

`_build_enemy`（`battle/sim.py`）里那一大段是**同一个形状**的搬运，一共 **80 行**：

    <字段名>=<从 stats 上 getattr 出来、再转个型或兜个底>,

手抄一遍必然抄错一两个，而抄错的表现是"某个数值差一点"——最贵的那种 bug：
不报错、不对齐、要一列一列比才看得出来。

从 AST 里把实参**原样取出来**，生成的代码里放的就是**同一段表达式**。
这与本项目那条纪律一致：**原样搬，不许重写**。

## 它读什么、写什么

* 读：`ak_tactic/battle/sim.py` 里 `_build_enemy` 的 `EnemyUnit(...)` 调用
* 写：`ak_tactic/frontend/enemy_view.py`（幂等）

## 自由变量怎么处理

表达式里引用的自由变量是 `stats` / `enemy_id` / `level` / `pts`(=route) / `legs` /
`t` / `wait` / `aff` / `bk` / `self.species_provider`。前几个直接当形参；
`pts` 与 `self.species_provider` 按 `RENAME` 换名。

⚠ **`always_invincible` 与 `unblockable` 不在 kwargs 里**——它们是运行时由天桩机制
写的（`sim.py:4612-4613` / `4772`）。刚造出来的敌人两者都是 `False`，生成物照此置
`False`，由规格层自己显式写死需要的值。

跑法：`python tools\\gen_enemy_view.py`
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "ak_tactic" / "battle" / "sim.py"
DST = ROOT / "ak_tactic" / "frontend" / "enemy_view.py"

#: `_build_enemy` 里的写法 → `enemy_view` 的形参名
RENAME = [("self.species_provider", "species_provider"), ("pts", "route")]

HEADER = '''# -*- coding: utf-8 -*-
"""一个敌人的**规格视图**——`build_spec` 需要的那组字段，不需要一个活的对象。

⚠ **本文件由 `tools/gen_enemy_view.py` 从 `battle/sim.py::_build_enemy` 机械生成，
不要手改。** 改口径请改生成器再重跑，这样两边永远是同一段表达式。

## 它是干什么的

`spec.py` 原本要 `sim._build_enemy(...)` 造一个 `EnemyUnit` 才能读它的字段。
而 `EnemyUnit` 是个 **142 字段的 dataclass**——`__init__` 只存不算，真正要的只是
那份**数据**，不是那台对象（跑帧的那几百行一行都用不上）。

所以这里按同一套表达式算出同一组字段，装进一个 `SimpleNamespace`。
`spec.py::_unit_spec` 是 `getattr` 式的读法，命名空间就能喂饱它。

## 口径的边界

* `always_invincible` / `unblockable` **不在这里算**：它们是运行时由天桩机制写的
  （`sim.py:4612-4613` / `4772`），刚造出来的敌人两者都是 `False`。
  规格层需要它们为真时**自己显式写死**。
* 尾部的构造后调整（`reborn_def_base` / 屏障）**照样搬**：它们落在字段工厂的
  尾巴上，抄字段时最容易漏。
* `route_length` 是 `EnemyUnit` 的 property（`unit.py:1419`），这里照它的定义算。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from .geometry import path_length

__all__ = ["route_length", "enemy_view"]


def route_length(route: list, legs: list) -> float:
    """路线总长。⚠ 与原版 `EnemyUnit.route_length`（`unit.py:1419`）同口径：

    有分段腿就按腿长求和，**否则**退回按折线算（`path_length`）。
    `cannot_clear` 判"自缚"（单点路线永不判漏）读的正是这个值。
    """
    if legs:
        return sum(leg.length for leg in legs)
    return path_length(route)


def enemy_view(stats: Any, *, enemy_id: str, level: int,
               route: list, legs: list, t: float, wait: float = 0.0,
               aff: dict | None = None, bk: Any = None,
               species_provider: Any = None) -> SimpleNamespace:
    """按 `_build_enemy` 的**同一套表达式**算出规格视图。"""
    e = SimpleNamespace()
'''

TAIL = '''
    # ---- 构造后调整（原版 `_build_enemy` 尾部那几行，照搬）
    #
    # ⚠ 这几行极易在"抄字段"时被跳过——它们是**算出来**的，形状与上面那 80 行不同。
    #: 防御力基准：充能加成按它重算，避免二次重生时把上次的加成再乘一遍
    e.reborn_def_base = e.defense
    #: 屏障：按最大生命折算，在血量之前被消耗
    _ratio = float(getattr(stats, "shield_hp_ratio", 0.0) or 0.0)
    e.shield = e.shield_max = (e.max_hp * _ratio) if _ratio else 0.0
    # ---- 路线长度（原版是 property，见上面 `route_length`）
    e.route_length = route_length(route, legs)
    # ---- 运行时才写的两个（新造出来时都是 False，见模块头）
    e.always_invincible = False
    e.unblockable = False
    return e
'''


def extract() -> list[tuple[str, str]]:
    tree = ast.parse(SRC.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_build_enemy":
            call = next(x for x in ast.walk(node)
                        if isinstance(x, ast.Call)
                        and getattr(x.func, "id", "") == "EnemyUnit")
            out: list[tuple[str, str]] = []
            for kw in call.keywords:
                expr = ast.unparse(kw.value)
                for old, new in RENAME:
                    expr = expr.replace(old, new)
                out.append((kw.arg, expr))
            return out
    raise SystemExit("在 %s 里找不到 _build_enemy" % SRC)


def build_text(fields: list[tuple[str, str]]) -> str:
    parts = [HEADER]
    for name, expr in fields:
        parts.append("    e.%s = %s\n" % (name, expr))
    parts.append(TAIL)
    return "".join(parts)


def main() -> int:
    fields = extract()
    text = build_text(fields)
    old = DST.read_text(encoding="utf-8") if DST.exists() else None
    if old == text:
        print("与现有文件一致，未改动（%d 个字段）" % len(fields))
        return 0
    DST.write_text(text, encoding="utf-8")
    print("已写入 %s（%d 个字段）" % (DST, len(fields)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
