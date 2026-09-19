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


#: 排程那五个列表（`frontend.schedule.Schedule` 的形状，见那里 `__init__`）。
#: 名字**逐字照抄**，因为 `spec.py:141` 会把这份输入**当作排程用**
#: （`sch = schedule if schedule is not None else inp`）——少一个就是 `AttributeError`。
_SCHEDULE_LISTS = ("deployments", "device_deployments", "summon_deployments",
                   "retreats", "skill_uses")


def _schedule_lists(schedule: Any) -> dict[str, list]:
    """从显式排程里取那五个列表；没有排程就给五个空表。

    ⚠ 没有排程时**不能**返回 `None`：`spec.py` 会把这份输入当排程读，
    五个属性一个都不能缺。给空表的效果是"这一局没有排程"，
    与"属性不存在"是两件事（后者是 17 份作业一起红的那种错）。
    """
    out: dict[str, list] = {name: [] for name in _SCHEDULE_LISTS}
    if schedule is None:
        return out
    for name in _SCHEDULE_LISTS:
        got = getattr(schedule, name, None)
        if got is None:
            raise AttributeError(
                f"排程对象 {type(schedule).__name__} 上没有 `{name}`。"
                f"`spec.py` 会拿这份输入当排程读，缺一个就是 AttributeError。"
                f"要么补齐排程，要么显式传 None 表示'这一局没有排程'。")
        out[name] = list(got)
    return out


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

    @classmethod
    def from_stage(cls, stage: Any, *, env: Any = None,
                   enemy_at: Callable[..., Any] | None = None,
                   species_provider: Callable[..., Any] | None = None,
                   range_provider: Callable[..., Any] | None = None,
                   schedule: Any = None,
                   **overrides: Any) -> "SpecInputs":
        """**不碰模拟器**：从 `stage` + 关卡静态项 + 排程直接算出一份输入。

        这是 `from_sim` 的**兄弟**，不是它的内部兜底——所以
        `grep -c "SpecInputs.from_sim"` 始终是一个有意义的计数
        （博士 2026-09-19 的批准里专门点了这一条）。

        ## 它为什么能对

        `build_spec` 要的是**开局那一刻的输入**。而在开局那一刻：

        * `snow_fields` / `team_auras` 在原版构造里就是**空表**（`sim.py:573/578`）
          ⇒ 直接给空表，**不是**"去问模拟器现在有几片雪"。这一条是**闸门盲区**的正解：
          规格取的是开局态，部署时才建的机制本来就不该出现在规格里。
        * `devices` / `farmland` / `total_attack` 是构造期**纯由 `stage` 造出来**的
          （`sim.py:525 / 536-544 / 583`）⇒ 照抄同样三步即等价。
        * 其余（`fps`/`speed_scale`/`ranged_enemies`/`enemy_windup`/
          `environment_difficulty`/`max_time`）由调用方经 `env` 交进来——
          它们**只有构造参数手上有**，反推不回去（见 `verify.py:399-409` 那段）。

        ⚠ `goal_cells` **仍留着**：`simgo/spec.py:405` 现在还在读 `inp.goal_cells`，
        而那个文件当前属于后端的工作窗口。**删它必须和那一行同批**，否则
        中间态会 `AttributeError`。PM #5 §五 已定"要删"，此处只是把顺序记明白。

        ## 判据

        **与 `from_sim` 产出的 `spec_sha` 逐字节一致**（金标准 17/17 的 `spec_sha`
        就是基线；见 `out/golden_go.json`）。**17/17 之前不许切**。
        """
        #: 关卡静态那 8 项。传进来就用，没传就现算——现算的那条与
        #: `verify.py:410` 的 `stage_env(...)` 是**同一个函数**，不另写一份。
        if env is None:
            from ak_tactic.frontend.stage_env import stage_env
            env = stage_env(stage)

        # ---- 装置：构造期纯由 stage 造出（`sim.py:525`）----
        from ak_tactic.battle.devices import BLOCKER_KEY, make_devices
        devices = make_devices(stage)
        blocker_cells = [d.cell for d in devices if d.key == BLOCKER_KEY]

        # ---- 田地：与 `sim.py:534-544` 逐字同序，包括那一次 `sever` ----
        #: ⚠ 预置阻流阀走装置技能 2（无持续时间）⇒ **开场即在位**，
        #: 它们的格子从第 0 秒起就不算田地。漏掉这几句 `sever`，
        #: 有田地的图会多算若干格田地（原版为这件事专门写过注释）。
        farmland = None
        from ak_tactic.battle.environment import FarmlandSystem, PolluteParams
        params = PolluteParams.from_stage(
            stage, getattr(env, "environment_difficulty", "NORMAL"))
        if params is not None and params.valid:
            farmland = FarmlandSystem(stage, params)
            for cell in blocker_cells:
                farmland.sever(*cell)

        # ---- 全场总攻击装置（`sim.py:583`）----
        #: ⚠ 它在 `battle.sim` 里（`:192`），**不在** `battle.p3r` 里——
        #: `p3r` 只放 `TotalAttackDevice` 这个类。别按名字猜模块（这一处我猜错过一次）。
        from ak_tactic.battle.sim import make_total_attack
        total_attack = make_total_attack(stage)

        # ---- 排程：`spec.py:141` 有 `sch = schedule if schedule is not None else inp` ----
        #: 有显式排程时，这几个列表只是**兜底**（`build_spec` 不会读它们）；
        #: 没有显式排程时它们必须齐——少一个就是 `AttributeError`，而且是 17 份一起红。
        lists = _schedule_lists(schedule)

        return cls(
            stage=stage,
            enemy_at=enemy_at, species_provider=species_provider,
            range_provider=range_provider,
            fps=getattr(env, "fps", 30),
            speed_scale=getattr(env, "speed_scale", 1.0),
            ranged_enemies=getattr(env, "ranged_enemies", True),
            enemy_windup=getattr(env, "enemy_windup", 0.5),
            environment_difficulty=getattr(env, "environment_difficulty", "NORMAL"),
            max_time=getattr(env, "max_time", 0.0),
            devices=list(devices),
            snow_fields=[],          #: 开局恒空（`sim.py:573`）——不许改成"现在有几片"
            farmland=farmland,
            total_attack=total_attack,
            deployments=lists["deployments"],
            device_deployments=lists["device_deployments"],
            skill_uses=lists["skill_uses"],
            retreats=lists["retreats"],
            summon_deployments=lists["summon_deployments"],
            team_auras=[],           #: 开局恒空（`sim.py:578`）
            goal_cells=None,         #: 见上文：与 `spec.py:405` 同批删
            snow_freeze=getattr(env, "snow_freeze", True),
            heal_mode=getattr(env, "heal_mode", "range"),
            **overrides,
        )
