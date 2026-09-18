# -*- coding: utf-8 -*-
"""把怀黍离的田地/病害系统抽成一份**自足的规格**，交给 Go 侧跑。

## 为什么是"规格"而不是"逐帧数据"

田地这一层的状态（【缓存】/【最大】/【实际】三个量、连片分组、泵站每秒的动作）
**只能在战斗中演进**：污染从哪来取决于敌人什么时候死、谁被阻挡、谁蜕皮，
事前算不出来。所以分工跟技能那一层一样：

* **Python 送几何与参数**：哪些格是田地、分成哪几片、每片当前的【最大】与【缓存】、
  每格的【实际】、场上装置（阻风阀/泵站）的格子与朝向；
* **Go 跑时间**：0.2s 释缓存 → 【最大】、1s 靠拢 → 【实际】、每秒的环境伤害/回复、
  泵站每秒的增减，以及所有"令田地地块病害值 +N"的调用点。

这份规格必须**足以重建原系统**——这一点不靠断言，靠
`_proto/mech_sufficiency.py` 实测：拿规格重建一个 Python 的 `FarmlandSystem`，
与原系统喂同一串事件，逐帧比对三个量。**规格不够，端口就会漂**，
而漂的是"病害值涨得快一点"这种没人看得见的东西。

## 三个容易写错的地方（都在本文件里显式处理）

1. **格子的键**：JSON 的键只能是字符串，而坐标是二元组。用 `[[x, y, 值], …]`
   而不是 ``"x,y"`` 拼串——拼串要定分隔符与顺序，是白送的一处漂移点。
2. **分组要连 `maximum` 与 `cache` 一起送**：只送格子集合的话，
   "开局播种把某片【最大】抬到 100"这条信息就丢了；而 `sever` 重划时的规矩是
   「各组各自取当前最高的【实际】作为新的【最大】」，它需要旧的【最大】做合并上限。
3. **装置要送"它是什么"而不是"它现在在做什么"**：泵站是**每秒**动作的，
   送一个"已泵过"的结果没有意义。送 `kind`（valve/pump/pile）+ 格子 + 朝向，
   由 Go 在每一秒自己结算。
"""

from __future__ import annotations

from typing import Any

from ..battle import environment as env
from ..battle.devices import BLOCKER_KEY, PILE_KEY, PUMP_KEY

__all__ = [
    "KINDS", "kind_of", "farmland_spec", "from_spec", "spec_summary",
    "spec_farmland_cells", "names_for", "port_reasons",
]

#: 装置 key → 规格里的 `kind`。**用 key 判，不用名字**（名字是中文、会随版本改）。
KINDS: dict[str, str] = {
    BLOCKER_KEY: "valve",       # 阻流阀：断田/还原
    PUMP_KEY: "pump",           # 泵站：每秒泵水
    PILE_KEY: "pile",           # 天桩：召唤物，不入本层
}

#: 机制名（Python 与 Go 之间的契约，改名等于改协议）。
FARMLAND_ID = "huai_shu_li.farmland"


def names_for(sim: Any) -> list[str]:
    """这一关需要 Go 侧挂上哪些机制。**由规格生成这一侧自己判**，不由调用方点。

    理由：调用方（对拍台/搜索）只知道自己给了什么阵容，不知道这一关地图里有什么；
    让它点名等于让它重算一遍"这关有没有田地"。而漏点一个名字的症状是
    **Go 侧什么都不做却照样给判决**——正是机制层立规矩要防的那种错。
    """
    out: list[str] = []
    if getattr(sim, "farmland", None) is not None:
        out.append(FARMLAND_ID)
    return out


#: 敌人侧的哪些字段一出现，就说明这一关用到了 Go 侧还没建模的敌人行为。
#:
#: 判据是**字段驱动**（照着 `EnemyUnit` 的字段列，不照名字猜）：每个字段都在
#: `sim.py` 里有一个消费点，字段非零就说明那一段代码这一局会跑。
#: 住在 `spec.py` 的闸门里，这里只留两张表给它查。
#:
#: ⚠ 与**田地这一层**的关系：这些字段里有一半读的是田地病害值
#: （`passive_pollut` / `phit_pollut` / `awake_value`），所以它们既是"敌人侧没建模"
#: 的理由，也是"田地机制还没接完线"的理由——但**只报一次**（报在敌人侧那条），
#: 否则同一件事在两处各写一句，读的人会以为有两个问题。
ENEMY_BEHAVIOR_FIELDS: dict[str, str] = {
    "skill_atk_scale_phys": "敌方技能出手",
    "skill_atk_scale_magic": "敌方技能出手",
    "skill_atk_pollut": "敌方技能出手（并污染田地）",
    "passive_pollut": "被击倒污染田地",
    "phit_pollut": "蜕皮污染田地",
    "phit_block_pollut": "蜕皮污染田地（被阻挡时）",
    "reborn_pollut": "重生吸病害值",
    "pm2_mark_pollut": "标记退场污染田地",
    "awake_value": "按田地病害值觉醒",
    "hp_drain_per_sec": "持续自伤",
}

#: 名字带前缀、不是数值字段的那几样（`modes` 是形态表，真值判空列表）。
#:
#: `death_token` **不在**这张表里：它只在"计划里真放了装置"时才有后果，
#: 而那条由 `device_deployments` 独立判——放进这张无条件的表，会把一件
#: 没有后果的事报成不能跑的理由（见 `spec.py::_enemy_reasons` 里的注释）。
ENEMY_BEHAVIOR_ATTRS: dict[str, str] = {
    "modes": "BOSS 换弱点形态",
}


def port_reasons(sim: Any) -> list[str]:
    """这一关的**关卡机制**里，有哪些是 Go 侧还没接线的？逐条给理由。

    粒度是"哪一样东西"而不是"这关不行"：闸门要能指出该补哪一块，否则
    "不支持"三个字会变成一个没人敢动的黑洞。

    覆盖边界（2026-09-18，逐条都有出处）：

    * **已接线**：田地几何、环境伤害/回复、泵站每秒泵水。位置 =
      原版 `sim.py:2164` 的 `_environment_tick`（Go 侧 `EnvTick`）。
    * **还没接线、但由别的闸门盖住**——不在本函数里重复报：
      - 敌人侧那条污染链（被击倒/蜕皮/技能出手/重生吸值）：报在
        `spec.py::_enemy_reasons`（那是敌人行为，Go 侧整段没有）；
      - 运行期改田地几何（田鼷拆掉阻流阀 → 地形还原）与天桩链：报在
        `spec.py` 的**关卡装置**那一条上——它们整段住在装置层里，而"装置摘掉
        结果一字不变"是那一条闸门要求实测证据的原因（拆掉装置连开场那次 `sever`
        也一并没了，所以那份证据同时盖住了几何的两种状态）。

    于是本函数现在**恒为空**。留着它而不是删掉：下一个机制（全场总攻击装置）
    会带着自己的一份"用了什么、接没接线"进来，位置在这里。**恒为空不等于可以
    省掉这条判据**——省掉之后，将来某一份规格漂了，读代码的人找不着"谁该为此负责"。
    """
    return []


def _spawns_of(sim: Any) -> list[Any]:
    """这一关会出现的每一种敌人（按 `_spawn` 建一次对象，纯读）。"""
    out = []
    for t, sp in getattr(sim, "_spawns", None) or []:
        try:
            out.append(sim._spawn(sp.enemy_id, sp.level, sp.route_index, float(t)))
        except Exception:                                       # noqa: BLE001
            continue
    return out


def _any_spawn_has(sim: Any, attr: str) -> bool:
    for e in _spawns_of(sim):
        if getattr(e, attr, 0):
            return True
    return False


def kind_of(key: str | None) -> str | None:
    return KINDS.get(key or "")


def _cells_pairs(cells: Any) -> list[list[int]]:
    return [[int(x), int(y)] for x, y in sorted(cells)]


def _pile_device_spec(sim, d) -> dict[str, Any] | None:
    """天桩装置 → **它那条召唤链的四跳模板**（装置 → 甲 → 乙 → 天标）。

    四跳里三跳是"谁造谁"，全在原版的代码里、不在正文里猜：

    * 装置 → 甲：`sim._pile_spec(d)`（结构化字段 `branch_id` → `branches` →
      `actions[].enemyKey`）；**甲的站位就是装置那一格**，那条关卡指派路径是留档的，
      甲自缚、不执行它（全活动 32 个天桩逐关核过）。
    * 甲 → 乙：甲自己的 `awake_enemy_key`（读它的天赋黑板）。
    * 乙 → 天标：`sim._pile_mark_key(乙)`（这一跳是全链唯一还要查表的，已登记在
      `docs/verdicts-pending.md`）。

    ⚠ 模板里的每一名都是**真建出来的对象**（`sim._build_enemy`）再走
    `spec._unit_spec`，与出怪表那条路**同一个口径**。另加的三个动作位：

    * `static` —— 自缚：站在原地、不算走完路线（原版靠"单点路线 + `reached_end`
      要求路线长度 > 0"实现；Go 侧是 `kind: "static"` 那条腿）。
    * `invincible` —— 甲**监测状态**下的无敌（激活时 Go 侧会关掉它）。
    * `self_bind` —— 乙登场自缚的秒数。

    数值（污浊满值、召唤延迟、自缚秒数）**一律从原版的常量里读**，不在 Go 里写死：
    它们是"原文里的数字"，改口径时改的是这一处。
    """
    from ..battle import sim as _sim_mod
    from . import spec as _spec

    try:
        child_key, _route = sim._pile_spec(d)
    except Exception:                                          # noqa: BLE001
        return None
    if not child_key:
        return None
    cell = [int(d.cell[0]), int(d.cell[1])]

    def build(key: str, positions: list[tuple[float, float]]):
        try:
            return sim._build_enemy(key, sim._summon_level(key), positions, [],
                                    0.0, 0.0)
        except Exception:                                      # noqa: BLE001
            return None

    parent = build(child_key, [(float(cell[0]), float(cell[1]))])
    if parent is None:
        return None
    pspec = _spec._unit_spec(sim, parent)
    pspec["static"] = True
    #: 监测状态＝"这只甲带 `CheckAwake.`"。⚠ 不能读 `parent.monitor`：那两个位是
    #: 原版在 `_pile_tick` **里**写上的（`child.monitor = awake_value > 0`），
    #: 此刻刚建出来的对象上还是默认值——实测第一版就是这么把 `invincible`
    #: 报成 False 的。照原版那一行的判据自己算一遍。
    pspec["invincible"] = float(getattr(parent, "awake_value", 0.0) or 0.0) > 0.0
    pspec["awake_value"] = float(getattr(parent, "awake_value", 0.0) or 0.0)
    pspec["awake_hp_ratio"] = float(getattr(parent, "awake_hp_ratio", 0.0) or 0.0)
    pspec["awake_summon_ratio"] = float(
        getattr(parent, "awake_summon_ratio", 0.0) or 0.0)
    pspec["awake_summon_cnt"] = int(getattr(parent, "awake_summon_cnt", 0) or 0)
    pspec["awake_enemy_key"] = str(getattr(parent, "awake_enemy_key", "") or "")
    pspec["summon_delay"] = float(getattr(_sim_mod, "PILE_SUMMON_DELAY", 1.25))
    pspec["pollut_full"] = float(getattr(_sim_mod, "PILE_POLLUT_FULL", 100.0))

    diver_key = str(getattr(parent, "awake_enemy_key", "") or "")
    if diver_key:
        diver = build(diver_key, [(float(cell[0]), float(cell[1]))])
        if diver is not None:
            dspec = _spec._unit_spec(sim, diver)
            dspec["static"] = False           # 乙会扑向干员，不是自缚
            dspec["self_bind"] = float(getattr(_sim_mod, "PILE_SELF_BIND", 1.0))
            dspec["hit_radius"] = 0.5         # 原版"贴到目标格"的判据
            mark_key = sim._pile_mark_key(diver)
            if mark_key:
                mark = build(mark_key, [(float(cell[0]), float(cell[1]))])
                if mark is not None:
                    mspec = _spec._unit_spec(sim, mark)
                    mspec["static"] = True
                    mspec["unblockable"] = True
                    mspec["attach_damage"] = float(
                        getattr(mark, "attach_damage", 0.0) or 0.0)
                    mspec["attach_radius"] = 0.3
                    dspec["mark"] = mspec
            pspec["summon"] = dspec
    return {
        "kind": "pile",
        "key": str(getattr(d, "key", "")),
        "cell": cell,
        #: 朝向照送：天桩自己不用它，但**规格的形状要一致**——
        #: `tools/check_mech_spec.py` 会逐字段核装置的形状，少一个键就报
        #: `KeyError: 'direction'`（实测就是这么被抓出来的）。
        "direction": str(getattr(d, "direction", "") or ""),
        "child": pspec,
    }


def farmland_spec(sim: Any) -> dict[str, Any] | None:
    """从**当前**模拟器状态抽一份田地规格；这一关没有环境系统则返回 None。

    取的是"此刻"的状态，所以调用时机是**开局初始化之后**（预置的阻流阀
    已经在 `BattleSimulator.__init__` 里断过田了）。若在别处调用，
    拿到的是那一刻的分组，这一点写在返回值里（`groups` 是当前分组）。
    """
    fs = getattr(sim, "farmland", None)
    if fs is None:
        return None
    p = fs.params
    groups = []
    for f in fs.fields:
        if not f.cells:
            continue
        groups.append({
            "cells": _cells_pairs(f.cells),
            "maximum": float(f.maximum),
            "cache": float(f.cache),
        })
    devices = []
    for d in getattr(sim, "_devices", None) or []:
        kind = kind_of(getattr(d, "key", None))
        # 运行期真的要动的装置才送。
        #
        #  * **泵站**：每秒泵水，住在 `_environment_tick`（本层已实现）；
        #  * **天桩**：召唤链（装置 → 甲 → 乙 → 天标）现在**已接线**，模板随它送过去
        #    （`_pile_device_spec`），时间在 Go 的机制层跑；
        #  * **阻流阀**不送：它只剩"运行期被拆掉 → 地形还原"一条动作，而开场那一次
        #    `sever` **已经算进上面的 `groups`**（几何是"此刻"的）。被拆还原还没移植，
        #    由对拍台的装置证据控制（只关 `_device_tick`／`_pile_tick` 再看判决）负责，
        #    证据不成立时闸门整关拒跑——不会静默少算。
        if kind == "pile":
            one = _pile_device_spec(sim, d)
            if one is not None:
                devices.append(one)
            continue
        if kind != "pump":
            continue
        devices.append({
            "kind": kind,
            "key": str(getattr(d, "key", "")),
            "cell": [int(d.cell[0]), int(d.cell[1])],
            "direction": str(getattr(d, "direction", "") or "").upper(),
        })
    return {
        "kind": "farmland",
        "width": int(fs.map.width),
        "height": int(fs.map.height),
        "difficulty": str(p.difficulty),
        "params": {
            "basic_damage": float(p.basic_damage),
            "damage_ratio": float(p.damage_ratio),
            "first_basic_damage": float(p.first_basic_damage),
            "first_damage_ratio": float(p.first_damage_ratio),
            "hp_recovery_per_sec": float(p.hp_recovery_per_sec),
        },
        #: 每 0.2s 释 1 点缓存、每 1s 靠拢一次——**写成规格而不是 Go 里的常量**：
        #: 它们是"原文里的数字"，将来原文改了口径，改的是这一处。
        "cache_interval": env.CACHE_INTERVAL,
        "cache_per_tick": env.CACHE_PER_TICK,
        "actual_interval": env.ACTUAL_INTERVAL,
        "actual_per_divisor": env.ACTUAL_PER_DIVISOR,
        "actual_base_step": env.ACTUAL_BASE_STEP,
        "pollut_min": env.POLLUT_MIN,
        "pollut_max": env.POLLUT_MAX,
        "pump_rate": env.PUMP_RATE,
        "pump_range": env.PUMP_RANGE,
        "pump_range_bonus": env.PUMP_RANGE_BONUS,
        "groups": groups,
        #: ⚠ **不要把值为 0 的条目滤掉**：`actual` 里"存在一个 0"与"没有这一格"
        #: 在状态上是两回事（实测 HS-EX-4 的播种就是 `(1,7): 0.0`）。
        #: 滤掉它不会让伤害算错（`actual_at` 缺格也返回 0），但会让规格重建出的
        #: 状态与原系统不等——那正是"规格够不够"要抓的东西。
        "actual": [[int(x), int(y), float(v)]
                   for (x, y), v in sorted(fs.actual.items())],
        "severed": _cells_pairs(getattr(fs, "_severed", ()) or ()),
        "devices": devices,
    }


class _StubTile:
    """给重建用的假地块：只回答"是不是低地"与 `tileKey`。"""

    __slots__ = ("is_lowland", "key")

    def __init__(self, lowland: bool) -> None:
        self.is_lowland = lowland
        self.key = "tile_ground"


class _StubMap:
    """一棵足以让 `farmland_groups` 还原出同一分组的假地图。

    重建走的是**原版自己的分组函数**（`env.farmland_groups`），不是另写一份
    连通域算法——两份实现必然有一天不一致，而"分组不一样"表现为
    "病害值涨得不一样"，很难查。
    """

    def __init__(self, width: int, height: int,
                 cells: set[tuple[int, int]]) -> None:
        self.width = width
        self.height = height
        self.tiles = [[_StubTile((x, y) in cells) for x in range(width)]
                      for y in range(height)]


def spec_farmland_cells(spec: dict[str, Any]) -> set[tuple[int, int]]:
    out: set[tuple[int, int]] = set()
    for g in spec.get("groups") or ():
        for x, y in g["cells"]:
            out.add((int(x), int(y)))
    for x, y in spec.get("severed") or ():
        out.add((int(x), int(y)))
    return out


def from_spec(spec: dict[str, Any]) -> Any:
    """用规格重建一个 `FarmlandSystem`（供探针/自检与 Go 侧对照）。

    重建出来的对象与 `farmland_spec` 抽的那个**必须逐帧等价**——
    这就是"规格够不够"的判据本身。
    """
    width = int(spec["width"])
    height = int(spec["height"])
    groups = list(spec.get("groups") or [])
    farmland: set[tuple[int, int]] = set()
    for g in groups:
        for x, y in g["cells"]:
            farmland.add((int(x), int(y)))
    severed = {(int(x), int(y)) for x, y in spec.get("severed") or ()}

    params = env.PolluteParams(**{
        k: spec["params"][k] for k in
        ("basic_damage", "damage_ratio", "first_basic_damage",
         "first_damage_ratio", "hp_recovery_per_sec")},
        difficulty=str(spec.get("difficulty", "NORMAL")),
    )
    stub = _StubMap(width, height, farmland | severed)
    fs = env.FarmlandSystem(_Stage(stub), params)
    # 用规格里的分组**覆盖**重建出来的分组：分组必须来自规格，
    # 假地图只负责让构造过程不炸。两者不一致时下面的断言会立刻抓住。
    rebuilt = env.farmland_groups(stub, farmland)
    if {frozenset(g) for g in rebuilt} != {frozenset(
            (int(x), int(y)) for x, y in g["cells"]) for g in groups}:
        raise ValueError("规格里的分组与按格子重算的分组不一致——规格自相矛盾")
    fs.fields = [env.Field(cells={(int(x), int(y)) for x, y in g["cells"]},
                           maximum=float(g.get("maximum", 0.0)),
                           cache=float(g.get("cache", 0.0))) for g in groups]
    fs.actual = {(int(x), int(y)): float(v) for x, y, v in spec.get("actual") or []}
    fs._severed = severed
    fs._all_cells = frozenset(farmland | severed)
    fs._rebuild_index()
    for f in fs.fields:
        f.clamp()
    return fs


class _Stage:
    """`FarmlandSystem.__init__` 只读 `stage.map`，所以壳子给这一项就够了。"""

    def __init__(self, stage_map: Any) -> None:
        self.map = stage_map


def spec_summary(spec: dict[str, Any] | None) -> str:
    if not spec:
        return "（这一关没有田地系统）"
    cells = spec_farmland_cells(spec)
    dirty = [g for g in spec["groups"] if float(g.get("maximum", 0)) > 0
             or float(g.get("cache", 0)) > 0]
    kinds: dict[str, int] = {}
    for d in spec["devices"]:
        kinds[d["kind"]] = kinds.get(d["kind"], 0) + 1
    dev = "、".join(f"{k}×{v}" for k, v in sorted(kinds.items())) or "无"
    return (f"田地 {len(cells)} 格 / {len(spec['groups'])} 片"
            f"（有病害 {len(dirty)} 片），播种 {len(spec['actual'])} 格，"
            f"断田 {len(spec['severed'])} 格，装置 {dev}")
