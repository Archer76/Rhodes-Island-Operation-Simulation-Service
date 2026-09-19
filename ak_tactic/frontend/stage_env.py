# -*- coding: utf-8 -*-
"""**关卡静态**:构建规格要用、但**与战斗无关**的那 8 个量。

## 它替换掉什么

`build_spec` 现在从**活的 `BattleSimulator`** 上读这 8 项
（`spec.py:1062-1078`）：

```
fps  speed_scale  ranged_enemies  enemy_windup
cost_init  cost_max  cost_time  life
```

而它们在 `sim.py` 那边的来源是 `sim.py:418-489`——**全是派生**，
没有一项需要引擎跑起来：

| 项 | 源头 |
|---|---|
| `fps` | 构造参数（`sim.py:418`） |
| `speed_scale` | 构造参数 × `stage.options.move_multiplier`（419） |
| `ranged_enemies` | 构造参数（428） |
| `enemy_windup` | `max(0, 构造参数)`（440） |
| `cost_init` | `stage.options.initial_cost`（474） |
| `cost_max` | `stage.options.max_cost`（475） |
| `cost_time` | `stage.options.cost_increase_time` **÷** `cost_recovery_scale(...)`（476/479-481） |
| `life` | `global_lifepoint(...)` 优先，否则 `stage.options.max_life_point`（483/487-489） |

## ⚠ 两处容易漏的派生（它们正是"四星档"的来历）

* `cost_time` 要被 `cbuff_cost_recovery.scale` **除**（四星档常见 2 = 回复速度翻倍）。
  1-7 的四星档就是这条。**乘除弄反不会有任何判据报警**，只会让费用回得快/慢。
* `life` 要被关卡级的 `global_lifepoint` **覆写**（八关 EX 的四星档都改成 1，
  而关卡文件自己的 `maxLifePoint` 是 3、普通与四星**两份都是 3**）。
  不接这条，四星档就凭空多两条命。

## 判据边界（照抄 `blackboard.py` 那段）

这两条都只在**非 NORMAL 难度**下才与普通档不同，而当前流水线**恒为 NORMAL**
（`Verifier` 建模拟器时不传 `environment_difficulty`）⇒ 那是**沉默区**。

**所以本模块是"原样搬"，不是重写**：上面每一行的口径都与 `sim.py` 逐字对齐，
包括 `or 0.0` / `or 99.0` / `or 1.0` 这些"0 与 None 一视同仁"的写法
（改成 `is None` 判断会在 `max_cost=0` 这类取值上分叉，而现有计划覆盖不到）。
"""
from __future__ import annotations

from typing import Any

from .stage_mul import cost_recovery_scale, global_lifepoint

__all__ = ["FPS", "stage_env", "ENV_KEYS"]

#: 每秒帧数。⚠ **一份来源**：`battle/sim.py` 从这里 import（原来是 `sim.py:79`
#: 自己写的 30）。两处各写一个 30 的话，哪天要改就会只改一处。
FPS = 30

#: 本模块产出的键（规格里对应的字段名）。
ENV_KEYS = ("fps", "speed_scale", "ranged_enemies", "enemy_windup",
            "cost_init", "cost_max", "cost_time", "life")


def stage_env(stage: Any, *, environment_difficulty: str = "NORMAL",
              fps: int = FPS, speed_scale: float = 1.0,
              ranged_enemies: bool = True,
              enemy_windup: float = 0.5) -> dict[str, Any]:
    """`stage` ＋ 那几个构造参数 → 规格里那 8 个字段。

    后四个参数的默认值与 `BattleSimulator.__init__`（`sim.py:324-330`）逐字一致，
    这样"不传 switches"这条常见路径得到的就是同一个值。
    """
    # ---- 构造参数那四个（`sim.py:418-440`）----
    out: dict[str, Any] = {
        "fps": int(fps),
        # `move_multiplier` 是关卡级的移速档（`stage.options`）
        "speed_scale": float(speed_scale)
        * float(getattr(stage.options, "move_multiplier", 1.0) or 1.0),
        "ranged_enemies": bool(ranged_enemies),
        "enemy_windup": max(0.0, float(enemy_windup)),
    }
    # ---- 费用三项（`sim.py:474-481`）----
    out["cost_init"] = float(getattr(stage.options, "initial_cost", 0.0) or 0.0)
    out["cost_max"] = float(getattr(stage.options, "max_cost", 99.0) or 99.0)
    cost_time = float(getattr(stage.options, "cost_increase_time", 1.0) or 1.0)
    #: `cbuff_cost_recovery.scale`（四星档常见 2 = 回复速度翻倍）。它改的是
    #: **每点费用几秒**，所以要**除**。
    scale = cost_recovery_scale(stage, environment_difficulty)
    if scale and scale != 1.0:
        cost_time = cost_time / scale
    out["cost_time"] = cost_time
    # ---- 生命点（`sim.py:483-489`）----
    life = int(getattr(stage.options, "max_life_point", 1) or 1)
    lp = global_lifepoint(stage, environment_difficulty)
    if lp is not None:
        life = int(lp)
    out["life"] = life
    return out
