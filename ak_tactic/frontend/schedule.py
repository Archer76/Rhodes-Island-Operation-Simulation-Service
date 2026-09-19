# -*- coding: utf-8 -*-
"""**排程**：把"这一局要怎么打"记下来，交给 Go 去跑。

## 为什么这一层几乎不用重写

量过之后发现一件反直觉的事：**排程逻辑本来就不在 `battle/` 里**。

* 真正的排程——费用模型（"钱够了就下" / 显式时刻按那一刻结账）、落地时刻、
  地形守卫、翔虫机动的上次落点——**全在 `verify.py::run`**（`verify.py:363-414`）。
* `battle/` 出的那一份只有**五个 `append`**：

```
sim.plan(dep)            → deployments.append(dep)          2 行
sim.retreat(pos, t)      → retreats.append((t, tuple(pos)))   2 行
sim.use_skill(pos, t)    → skill_uses.append(SkillUse(...))   7 行
sim.plan_device(dep)     → device_deployments.append(dep)     1 行
sim.plan_summon(dep)     → summon_deployments.append(dep)     1 行
```

所以"把排程挪出 `battle/`"不是重写一套排程器，而是**把这五个 append 收进一个
不依赖 `battle/` 的载体** —— 就是这里的 `Schedule`。

## 两个数据结构也一起搬

`Deployment` 与 `SkillUse` 原本是 `battle/sim.py:207/232` 的 dataclass。它们是
**纯数据**（`Deployment.operator` 那类注解在 `from __future__ import annotations`
下只是字符串，不牵 import），所以整体搬走没有代价。`battle/sim.py` 改成从
这里转出——同一批对象，两个消费者。

## 判定与记账分家

⚠ 这里**只记"请求"**，与 `verify.py` 的注释一致：技能能不能开、装置放不放得下，
都要看那一刻的技力/额度，那是**跑帧**的事，归 Go。原版也是这么分的
（`use_skill` 的正文写着"只是**请求**……真正的判定在 `_skill_tick` 里"）。

## `snow_fields` / `_devices` 为什么不在这里

那两个是**跑帧时**才被填的（`sim.py:3380` / `3016`）。规格在**跑之前**读它们，
拿到的本来就是空的 —— 这正是"积雪闸门盲区"那条已知问题的来历
（`build_spec` 取开局态，部署时才建的机制闸门永远看不见）。
所以载体里不放它们，不是漏了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

__all__ = ["Deployment", "SkillUse", "Schedule"]


# ---------------------------------------------------------------- 计划动作

@dataclass
class Deployment:
    """一次部署。

    :param skill: 用第几个技能。可以是槽位号 1/2/3（0 = 不带技能，需要
        `BattleSimulator(skill_book=...)` 才能解析），也可以直接给一个
        `SkillLevel` 对象。
    :param skill_level: 技能的普通等级 1–7
    :param skill_mastery: 专精等级 0–3
    :param auto_skill: 手动技能在技力满了之后要不要自动开
    """

    time: float
    operator: Any
    position: tuple[int, int]
    direction: str = "Right"
    skill: object = 0
    skill_level: int = 7
    skill_mastery: int = 0
    auto_skill: bool = True
    #: 已判定生效的天赋（`ak_tactic.operator.talent.Talent` 列表）。
    #: 模拟器只对**显式建模过**的天赋做事，见 `ak_tactic.battle.talents`。
    talents: list = field(default_factory=list)
    #: **规格视图**（`frontend/operator_view.py`），迁移期为 `None` 时退回 `operator`。
    #:
    #: ⚠ 为什么是**并行字段**而不是直接换掉 `operator`：迁移期两台引擎同时在跑，
    #: `operator` 必须是活的 `OperatorUnit`（Python 引擎要拿它跑帧），
    #: 而 `build_spec` 只需要开局那一组字段。同一个 `Deployment` **对象**
    #: 交给两边，`sched.diff(sim)` 比出来的才是排程的差（`verify.py` 上有这条注释）。
    operator_view: Any = None


def operator_of(d: Any) -> Any:
    """一次部署里的干员——**规格层唯一的取值入口**。

    有视图就用视图，没有就退回 `operator`。迁移期两台引擎同时在跑，
    `d.operator` 是活的 `OperatorUnit`（Python 引擎要拿它跑帧），
    而规格只需要开局那一组字段；`verify.py` 会在排程时把视图挂上。

    ⚠ **必须走这个函数，不要直接写 `d.operator`**：`spec.py` 与 `skills.py`
    里有 8 处读它。留一处不换，那一处就会读活对象——
    症状是"规格里某一个字段跟别的不一样"，不报错、只有在那个字段被读到的
    关卡上才看得出来。
    """
    return getattr(d, "operator_view", None) or getattr(d, "operator", None)


@dataclass
class SkillUse:
    """一次手动开技能。"""

    time: float
    position: tuple[int, int]


class Schedule:
    """一局的排程——五个列表，五个 append。

    ⚠ 方法名与 `BattleSimulator` 上的**逐字相同**，参数也相同。这样
    `verify.py` 那三行 `sim.plan(...)` / `sim.retreat(...)` / `sim.use_skill(...)`
    可以**同步**写到两边，迁移期两边都填、随时可对，切过去只是不再调 sim 而已。
    """

    def __init__(self) -> None:
        #: 干员部署（`Deployment`），按排入顺序
        self.deployments: list[Deployment] = []
        #: 装置部署（`DeviceDeployment`）——不占干员名额、不归属干员，但要花费与额度
        self.device_deployments: list[Any] = []
        #: 召唤物部署（`SummonDeployment`）——归属与上限口径与上面两个都不同
        self.summon_deployments: list[Any] = []
        #: 撤退：`(时刻, 坐标)`。**按坐标**排，因为模拟器的接口就是坐标
        self.retreats: list[tuple[float, tuple[int, int]]] = []
        #: 手动开技能：**只是请求**，能不能开看那一刻的技力
        self.skill_uses: list[SkillUse] = []

    # ---- 与 `BattleSimulator` 同名同参（迁移期两边都调，切过去只留这边）

    def plan(self, deployment: Deployment) -> None:
        self.deployments.append(deployment)

    def retreat(self, position, time: float) -> None:
        self.retreats.append((time, tuple(position)))

    def use_skill(self, position, time: float) -> None:
        self.skill_uses.append(SkillUse(time=time, position=tuple(position)))

    def plan_device(self, deployment) -> None:
        self.device_deployments.append(deployment)

    def plan_summon(self, deployment) -> None:
        self.summon_deployments.append(deployment)

    # ---- 一致性自检（迁移期用）

    def diff(self, sim) -> list[str]:
        """与一个填好的模拟器比这五个列表，返回差异描述（空 = 一致）。

        ⚠ 这是**迁移期的脚手架**：等 `battle/` 删掉之后它就没有对象可比了，
        连同这个方法的调用点一起删。
        """
        out: list[str] = []
        for name in ("deployments", "device_deployments", "summon_deployments",
                     "retreats", "skill_uses"):
            mine = getattr(self, name)
            theirs = getattr(sim, name, None)
            if theirs is None:
                out.append(f"{name}: 模拟器上没有这个字段")
                continue
            if list(mine) != list(theirs):
                out.append(f"{name}: 载体 {len(mine)} 条 vs 模拟器 {len(theirs)} 条")
        return out
