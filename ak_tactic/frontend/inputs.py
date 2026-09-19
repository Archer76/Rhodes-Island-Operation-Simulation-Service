# -*- coding: utf-8 -*-
"""`build_spec` 的输入：**一份数据**，不是一台跑着的模拟器。

## 为什么要有这个类

`build_spec` 原本收一个活的 `BattleSimulator`，从它身上读 11 项属性
（`stage` / `range_provider` / `enemy_at` / `species_provider` / `_devices` /
`deployments` / `snow_fields` / `farmland` / `total_attack` / `fps` /
`speed_scale` / `ranged_enemies` / `enemy_windup` / `max_time` /
`environment_difficulty`，外加几处 `getattr` 的可选位）。

问题不在"读了几个属性"，而在**那个对象是一台正在跑的机器**：

* 它的 `stage` 会被中途改写（天桩路线、阻流阀断田）；
* `_devices` / `snow_fields` 是**运行期 append** 出来的，开局恒为空
  （这正是"积雪闸门盲区"的来源，见 `audit_gate_blindspot.py`）；
* `deployments` 会被引擎按帧消费后**出队**。

⇒ 规格层要的是"**开局那一刻的输入**"，而拿到的是"**当下这台机器**"。
两者在开局那一刻恰好相等，这就是它能一直工作的原因，也是它随时会错的原因。

## 这一版做了什么、没做什么

**做了**：把这 17 项收成一个 dataclass，`from_sim()` 从活模拟器**抄一份**。
`build_spec` 拿到的从此是一份**快照**——它不再能顺着引用去读一台正在变的机器。

**没做**（下一阶段）：`from_sim()` 里仍然要一台模拟器。
要真正断掉，得让这些字段**从 gamedata + 计划 + 干员计算器直接算出来**，
不再问模拟器要。这一步先把"读的是数据不是机器"这层语义立起来，
否则后面每一步都在跟一个会变的引用讨价还价。

## ⚠ 字段默认值都是从原代码的 `getattr` 默认值**抄**的

它们不是随手定的：`snow_freeze` 默认 `True`、`heal_mode` 默认 `"range"`、
`max_time` 默认 `0.0` 且再 `or 900.0`——每一条都对应原代码里的一处 `getattr`。
改这里的默认值等于改口径，**必须回去对一遍原代码**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

__all__ = ["SpecInputs"]


@dataclass
class SpecInputs:
    """`build_spec` 的全部输入。字段名与它原先从模拟器上读的名字**逐字相同**，
    这样 `build_spec` 体内的 `inp.stage` 与原代码的 `sim.stage` 一一对应，
    diff 时看得清哪一处换了来源。"""

    #: 关卡（`gamedata.stage.Stage`）。**唯一必需的一项**——没有它什么都算不了。
    stage: Any

    #: 三张查表函数。`enemy_at(敌人 id, 等级)`、`species_provider(敌人)`、
    #: `range_provider(干员)`。原先直接挂在模拟器上。
    enemy_at: Callable[..., Any] | None = None
    species_provider: Callable[..., Any] | None = None
    range_provider: Callable[..., Any] | None = None

    #: 环境四项。原先从模拟器构造参数推出来（`stage_env` 那条路算的就是它们）。
    fps: int = 30
    speed_scale: float = 1.0
    ranged_enemies: bool = True
    enemy_windup: float = 0.5
    environment_difficulty: str = "NORMAL"
    max_time: float = 0.0

    #: 装置层。⚠ 模拟器上这两个都是**运行期**产物：`_devices` 开局建好后会被拆、
    #: `snow_fields` 是跑起来才 append 的。规格取的是**开局态**。
    devices: list[Any] = field(default_factory=list)
    snow_fields: list[Any] | None = None
    farmland: Any = None
    total_attack: Any = None

    #: 排程。`deployments` 在模拟器上会被引擎按帧消费出队，
    #: 所以规格**宁可要一份独立快照**，不要那个会被吃掉的列表。
    #:
    #: ⚠ 这五个列表合起来就是 `frontend.schedule.Schedule` 的形状：
    #: `spec.py` 里有一句 `sch = schedule if schedule is not None else inp` ——
    #: 也就是说**没有显式排程时，这份输入自己当作排程用**。
    #: 所以少一个列表就是 `AttributeError`（本轮实测：漏了 `skill_uses`，
    #: 17 份作业**全部**报 `'SpecInputs' object has no attribute 'skill_uses'`）。
    #: 这也说明这条判据很灵：漏一个字段，17 份一起红，不会有半红。
    deployments: list[Any] | None = None
    device_deployments: list[Any] | None = None
    skill_uses: list[Any] = field(default_factory=list)
    retreats: list[Any] = field(default_factory=list)
    summon_deployments: list[Any] = field(default_factory=list)

    #: 三个可选位，默认值照抄原代码的 `getattr` 默认值。
    team_auras: Any = None
    goal_cells: Any = None
    snow_freeze: bool = True
    heal_mode: str = "range"

    @classmethod
    def from_sim(cls, sim: Any, **overrides: Any) -> "SpecInputs":
        """**迁移期的桥**：从活模拟器抄一份快照。

        ⚠ 这个名字里带 `sim` 是有意的——**上一阶段的欠账明摆在这里**，
        不要在下一阶段把它忘掉：真正要断的是这个方法。
        它现在把 17 项从模拟器上抄过来；等 `stage_env` + 计划 + 计算器
        能把它们直接算出来，这个方法就该消失。

        `overrides` 用于调用方已经知道答案的项（例如 `verify.py` 自己算的
        `env` 那四项）——**以调用方给的为准**，不去问模拟器。
        """
        def _get(name: str, default: Any) -> Any:
            return getattr(sim, name, default)

        kw: dict[str, Any] = dict(
            stage=sim.stage,
            enemy_at=_get("enemy_at", None),
            species_provider=_get("species_provider", None),
            range_provider=_get("range_provider", None),
            fps=_get("fps", 30),
            speed_scale=_get("speed_scale", 1.0),
            ranged_enemies=_get("ranged_enemies", True),
            enemy_windup=_get("enemy_windup", 0.5),
            environment_difficulty=_get("environment_difficulty", "NORMAL"),
            max_time=_get("max_time", 0.0),
            #: ⚠ `_devices` 在模拟器上是私有名，这里**换成公开的 `devices`**：
            #: 规格层不该看见引擎的私有名单。抄的时候做这一次改名。
            devices=list(_get("_devices", None) or []),
            snow_fields=_get("snow_fields", None),
            farmland=_get("farmland", None),
            total_attack=_get("total_attack", None),
            deployments=_get("deployments", None),
            device_deployments=_get("device_deployments", None),
            skill_uses=list(_get("skill_uses", None) or []),
            retreats=list(_get("retreats", None) or []),
            summon_deployments=list(_get("summon_deployments", None) or []),
            team_auras=_get("team_auras", None),
            goal_cells=_get("_goal_cells", None),
            snow_freeze=_get("snow_freeze", True),
            heal_mode=_get("heal_mode", "range"),
        )
        kw.update(overrides)
        return cls(**kw)
