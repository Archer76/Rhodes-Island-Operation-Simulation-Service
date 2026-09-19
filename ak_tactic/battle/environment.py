"""关卡环境机制：怀黍离的田地 / 病害值。

【为什么单独一层】
`mechanics.py` 负责把机制**正文**编译成公式项（语料层），这里负责把机制**跑起来**
（战斗层）。两者的分工与 `formula.py` / `battle/` 的关系相同。

【三个数据来源，各自能分辨】
* **数值** —— 关卡 JSON 的 `runes[key=env_system_new][].blackboard`。
  黑板条目形如 ``{"key":…, "value":<num>, "valueStr":<str|null>}``：
  **数值型键的值住 `value`，`valueStr` 恒为 `null`**；只有 `init_pollut_value`
  这类字符串住 `valueStr`。只读 `valueStr` 会得出「参数全是 None」的假结论。
* **公式形状** —— prts.wiki「特殊机制」页的「病害值」条目 + 关卡页的
  「特殊地形效果」字段（两条互为校验，见 `docs/mechanics.md`）。
* **地块** —— 关卡 JSON 的 `mapData`。

【⚠ 难度掩码：禁止取第一条】
同一个 rune 键在关卡里常有多条，靠 `difficultyMask` 区分，取值实测有三种：
`NORMAL` / `FOUR_STAR` / **`ALL`**。`act31side_08` 用的就是 `ALL`——
只认 `NORMAL` 会把它整条漏掉，而且**不会报错**，只是环境伤害静默变成 0。
匹配规则：``mask == "ALL" or mask == 难度``。

【坐标】全项目内部为 MAA 口径（原点左上、y 向下）。`init_pollut_value` 写作
``"row,col:value"``，其 row 是**游戏内部口径（自下而上）**，解析时翻一次
``y = 高 - 1 - row``。自证：`act31side_08` 写 ``7,1:100``，而该关情报写
「场地**左上角**田地区域的初始病害值+100」——翻过来 y=0 正是最上面一行；
不翻则落到最下面一行，与情报相反。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .devices import DIRECTIONS, PUMP_KEY, behind_of

#: ⚠ **黑板取值原语已经搬走**，搬到 `ak_tactic/frontend/blackboard.py`（原样搬，不重写）。
#:
#: 搬的理由是依赖方向：`stage_mul.py` 用它们，而 `stage_mul` 要搬去 `frontend/`
#: 与 `build_spec` 同住（`docs/spec-extraction-surface.md`）。若让新家反过来
#: import 本模块，就等于"新家依赖要删掉的 `battle/`"，白搬。
#:
#: 这里**继续转出**同一个函数对象（下面 `__all__` 里那四个名字不变），
#: 所以 `environment.bb_number(...)` / `from .environment import bb_number`
#: 这类既有写法**一个字都不用改**。
from ..frontend.blackboard import (                          # noqa: E402
    bb_number, bb_text, find_rune, mask_applies,
)

__all__ = [
    "DIFFICULTIES", "RUNES_KEY", "FARMLAND_EXCLUDED_KEYS",
    "POLLUT_MIN", "POLLUT_MAX", "CACHE_INTERVAL", "CACHE_PER_TICK",
    "ACTUAL_INTERVAL", "ACTUAL_PER_DIVISOR", "ACTUAL_BASE_STEP",
    "PUMP_RATE", "PUMP_RANGE", "PUMP_RANGE_BONUS",
    "mask_applies", "find_rune", "bb_number", "bb_text",
    "parse_init_pollut", "is_farmland", "farmland_cells", "farmland_groups",
    "cells_in_radius",
    "PolluteParams", "Field", "FarmlandSystem", "actual_step",
]

#: 实验过的难度掩码取值。`ALL` 表示两种难度都适用。
DIFFICULTIES: tuple[str, ...] = ("NORMAL", "FOUR_STAR")

#: 承载环境系统的 rune 键。
RUNES_KEY = "env_system_new"

#: **不是田地**的地块。
#:
#: 判据是 prts.wiki「田地」原文：「仅适用于'''地形标记'''为'''默认'''的地面地块
#: （传送门出入口/地穴除外）」——注意原文写的是**地形标记为默认**，即普通地面，
#: 而不是「高度为低地」的全体。故排除传送门出入口与地穴。
#:
#: 前两版口径都作废了：第一版自造了一个排除集（把 `start`/`end`/`fence_bound`/
#: `flystart` 也排掉），由博士的地图预览图证伪；第二版一律收 LOWLAND，
#: 把传送点与洞穴也当成了田地。**⚠ 本条待实机校正。**
FARMLAND_EXCLUDED_KEYS: frozenset[str] = frozenset({
    "tile_telin", "tile_telout", "tile_hole",
})

POLLUT_MIN = 0.0
POLLUT_MAX = 100.0

#: 【缓存】每 0.2 秒释放 1 点病害值，累加到所属田地的【最大病害值】上。
CACHE_INTERVAL = 0.2
CACHE_PER_TICK = 1.0

#: 【实际病害值】每 1 秒向【最大病害值】靠拢一次。
ACTUAL_INTERVAL = 1.0

#: 『与最大值的差值每 25 点 +1 实际病害值』里的分母。
ACTUAL_PER_DIVISOR = 25.0

#: 上面那句里的「+1」按哪种读法算。见 `actual_step`。
ACTUAL_BASE_STEP = 1.0

#: 泵站的泵水速率（点/秒）。原文「以每秒1点的速度」。
PUMP_RATE = 1.0
#: 前方生效范围的默认格数。原文「自身前方生效范围（默认身前一格）」。
PUMP_RANGE = 1
#: 水源地部署有我方单位时的范围加成。原文「自身生效范围+2」——
#: 加的是**前方格数**（1 → 3），不是攻击范围那种几何。
PUMP_RANGE_BONUS = 2

#: ⚠ **这里原先站着一个常量 `POLLUTE_LIFTS_MAX`，它已经被删掉了。**
#:
#: 它编码的是这样一个两难：「令…半径 1.0 范围内的田地地块病害值 +N」里的
#: +N 是抬【实际】还是（顺便）抬【最大】？甲说两者都抬，乙说只抬【实际】。
#:
#: **这是个假的两难。** 博士 2026-09-17 给出 prts.wiki「特殊机制#病害值」原文：
#: 污染**既不直接进【实际】也不直接进【最大】**，而是先进【缓存】，
#: 每 0.2s 释放 1 点累加到【最大】上，【实际】再按每 1s 靠拢【最大】。
#: 于是「+N」的落地路径是 **缓存 → 【最大】 → 【实际】**，两个读法都不对。
#:
#: 留这段注释是因为"删掉一个曾经写得很像样的两难"这件事本身值得记：
#: 当时两种读法都有自检盯着、还列了各自理由，看起来比现在更"严谨"，
#: 但它严谨地框在了一个错误的二选一里——**先去找权威原文，比在两种
#: 读法之间反复推敲更省事**。


# ================================================================ 一、runes 黑板

#: 四个取值原语（`mask_applies` / `find_rune` / `bb_number` / `bb_text`）
#: **已经搬到 `ak_tactic/frontend/blackboard.py`**，本模块在文件头从那里 import 并
#: 继续转出——所以本模块的公开面**没有变化**。
#:
#: ⚠ 搬迁是**原样搬**：`find_rune` 的"禁止取第一条"与 `bb_number` 的
#: "数值住 `value` 不是 `valueStr`"这两条，各自对应一次真实踩过的错，
#: 而它们的差异只在**同键多条 rune** 时才分叉——当前流水线恒为 NORMAL
#: （`Verifier` 不传 `environment_difficulty`），FOUR_STAR 那条是**沉默区**。
#: 也就是说：重写错了，没有任何判据会响。所以只许搬，不许改。


def parse_init_pollut(text: str | None, map_height: int) -> dict[tuple[int, int], float]:
    """``"row,col:value|row,col:value"`` → ``{(x, y): value}``（MAA 口径）。

    row 是游戏内部口径（自下而上），**翻一次** `y = 高 - 1 - row`。
    格式坏的条目跳过而不是抛异常——关卡数据里偶有占位串，
    整条解析失败会让「这一关没有污染点」与「解析炸了」分不出来。
    """
    out: dict[tuple[int, int], float] = {}
    for chunk in (text or "").split("|"):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk or "," not in chunk:
            continue
        pos, _, val = chunk.partition(":")
        r_s, _, c_s = pos.partition(",")
        try:
            row, col, v = int(r_s), int(c_s), float(val)
        except ValueError:
            continue
        out[(col, map_height - 1 - row)] = v
    return out


# ================================================================ 二、田地

def is_farmland(tile: Any) -> bool:
    """一个地块是不是田地。

    判据：**低地** 且 `tileKey` 不属于 `FARMLAND_EXCLUDED_KEYS`。
    只认 `heightType` 不够——`tile_hole` / `tile_telin` / `tile_telout` 的
    `(heightType, buildableType, passableMask)` 与普通低地**完全一致**，
    字段分不出来，只能看 `tileKey` 的名字。
    """
    return tile.is_lowland and tile.key not in FARMLAND_EXCLUDED_KEYS


def farmland_cells(stage_map: Any) -> set[tuple[int, int]]:
    return {(x, y)
            for y, row in enumerate(stage_map.tiles)
            for x, t in enumerate(row) if is_farmland(t)}


def farmland_groups(stage_map: Any,
                    cells: set[tuple[int, int]] | None = None
                    ) -> list[set[tuple[int, int]]]:
    """把田地切成**四邻连片**的连通域。

    未被隔断的连片田地共享一个【最大病害值】，所以连通域就是系统的分组单位。
    用四邻而非八邻：斜向相接的两块地在游戏里并不共享病害。
    """
    todo = set(farmland_cells(stage_map) if cells is None else cells)
    groups: list[set[tuple[int, int]]] = []
    while todo:
        seed = todo.pop()
        group = {seed}
        stack = [seed]
        while stack:
            x, y = stack.pop()
            for nb in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if nb in todo:
                    todo.discard(nb)
                    group.add(nb)
                    stack.append(nb)
        groups.append(group)
    return groups


def cells_in_radius(x: int, y: int, radius: float) -> list[tuple[int, int]]:
    """以这一格为心、`radius` 格为半径的**圆**内的整数格（含自身）。

    原文里「半径1.0范围内的田地地块」出现在两处：敌人的死亡污染
    （「令阻挡自身的单位(被阻挡时)/自身(未被阻挡时)半径1.0范围内的
    田地地块病害值+N」）与「祟」蜕皮。半径 1.0 恰好够到**上下左右四邻**
    （距离正好 1.0），而斜角是 √2 ≈ 1.414、够不到——所以结果是十字五格。

    ⚠ 不要与「1.0 **边长**正方形范围内」混为一谈：天桩-甲召唤天桩-乙写的
    是「在当前位置1.0边长正方形范围内**随机位置**」，那是 3×3 的连续区域，
    与本函数的整数格集合不是一回事。
    """
    if radius <= 0:
        return [(x, y)]
    span = int(math.floor(radius))
    out: list[tuple[int, int]] = []
    for dy in range(-span, span + 1):
        for dx in range(-span, span + 1):
            if math.hypot(dx, dy) <= radius + 1e-9:
                out.append((x + dx, y + dy))
    return out


def pump_once(system: "FarmlandSystem", devices: Iterable[Any], *,
              ally_cells: Iterable[tuple[int, int]] = (),
              rate: float = PUMP_RATE) -> list[dict[str, Any]]:
    """让一批泵站各泵水一次（每秒调用一次）。

    处理两条叠加规则：

    * **同一泵站对同一连片田地只生效一次**——所以按 (泵站, 目标组) 去重，
      同一个泵站在同一次结算里不会对同一片田连加两下；
    * **多个泵站作用于同一连片田地时效果可叠加**——所以**不跨泵站去重**。

    只收 `PUMP_KEY` 的装置；传别的进来会被忽略（不是报错，装置表本来就会混着装）。
    """
    allies = set(ally_cells)
    out: list[dict[str, Any]] = []
    for d in devices:
        if getattr(d, "key", None) != PUMP_KEY:
            continue
        r = system.pump(d.cell, d.direction,
                        ally_on_source=d.behind in allies, rate=rate)
        if r is not None:
            r["device"] = d.cell
            out.append(r)
    return out


# ================================================================ 三、参数

@dataclass(frozen=True)
class PolluteParams:
    """环境系统的五个参数（`runes[key=env_system_new].blackboard`）。"""

    basic_damage: float = 0.0
    damage_ratio: float = 0.0
    first_basic_damage: float = 0.0
    first_damage_ratio: float = 0.0
    hp_recovery_per_sec: float = 50.0
    system: str = ""
    difficulty: str = "NORMAL"
    init_pollut: dict[tuple[int, int], float] = field(default_factory=dict)

    @property
    def valid(self) -> bool:
        """五个参数是否齐备。缺任何一个都说明 rune 没取对。"""
        return (self.damage_ratio > 0 and self.basic_damage > 0
                and self.first_damage_ratio > 0 and self.first_basic_damage > 0)

    @classmethod
    def from_stage(cls, stage: Any, difficulty: str = "NORMAL",
                   *, runes: Iterable[dict] | None = None) -> "PolluteParams | None":
        """从关卡里取环境系统参数；这一关没有环境系统则返回 None。"""
        if runes is None:
            runes = (getattr(stage, "raw", None) or {}).get("runes") or []
        r = find_rune(runes, RUNES_KEY, difficulty)
        if r is None:
            return None
        bb = r.get("blackboard") or []
        height = stage.map.height
        return cls(
            basic_damage=bb_number(bb, "basic_damage") or 0.0,
            damage_ratio=bb_number(bb, "damage_ratio") or 0.0,
            first_basic_damage=bb_number(bb, "first_basic_damage") or 0.0,
            first_damage_ratio=bb_number(bb, "first_damage_ratio") or 0.0,
            hp_recovery_per_sec=bb_number(bb, "hp_recovery_per_sec") or 50.0,
            system=bb_text(bb, "key") or "",
            difficulty=difficulty,
            init_pollut=parse_init_pollut(bb_text(bb, "init_pollut_value"), height),
        )


def actual_step(delta: float, *, divisor: float = ACTUAL_PER_DIVISOR,
                base: float = ACTUAL_BASE_STEP) -> float:
    """【实际病害值】每秒向【最大】靠拢的步长。

    原文（prts.wiki「病害值」）：
    『每1秒更新自身的【实际病害值】直到达到【最大病害值】
    （与最大值的差值每25点+1实际病害值，小数部分上入）』。

    ⚠ **这句话有两种读法，本实现取博士 2026-09-17 记录的甲，但差别是实的**：

    * **甲（本实现，`base=1`）**：步长 = ``ceil(差值/25 + 1)``
    * **乙（原文直读，`base=0`）**：步长 = ``ceil(差值/25)``

    两者相差恰好 **1 点/秒**（差值 25 时甲给 2、乙给 1）。原文的「每25点+1」
    更像乙；博士记录里写作「差值 ÷ 25 + 1」是甲。**标为待裁定**，
    改 `base` 即可切换，两种读法都有自检盯着。
    """
    if delta <= 0:
        return 0.0
    return math.ceil(delta / divisor + base)


# ================================================================ 四、运行态

@dataclass
class Field:
    """一群连片田地共享的【最大病害值】与【缓存】。

    【实际病害值】**不是**在这里的——它按格存在 `FarmlandSystem.actual` 上。
    依据是原文的两句话分开写：「田地拥有【实际病害值】」（每格），
    「未被隔断的连片田地拥有共同的【最大病害值】」（每组）。
    阻流阀隔断后『各自取当前最高实际病害值作为新的最大』也只有在
    实际按格计时才讲得通。
    """

    cells: set[tuple[int, int]]
    maximum: float = 0.0
    cache: float = 0.0

    def clamp(self) -> None:
        self.maximum = min(POLLUT_MAX, max(POLLUT_MIN, self.maximum))


class FarmlandSystem:
    """怀黍离的田地/病害系统。

    时间推进走 `tick(dt)`：内部按 0.2s 与 1s 两个节拍累加，调用方只管每帧
    喂 delta。**不要**在 tick 之外直接改 `maximum` / `actual`——
    那会绕过夹取，让病害值跑出 0–100。
    """

    def __init__(self, stage: Any, params: PolluteParams,
                 *, severable: bool = True) -> None:
        self.params = params
        self.map = stage.map
        self.severable = severable
        self.actual: dict[tuple[int, int], float] = {}
        self._t_cache = 0.0
        self._t_actual = 0.0
        self.fields: list[Field] = [
            Field(cells=g) for g in farmland_groups(self.map)]
        #: **地形原本就是田地的格子**（不随阻流阀的建成/被拆而变）。
        #: `sever` 把它从 `fields` 里摘掉、`restore` 再还回来，两边都要用到
        #: 这个"原始名单"——只看 `fields` 的话，被摘掉的格子就再也找不回来了。
        self._all_cells: frozenset[tuple[int, int]] = frozenset(
            c for f in self.fields for c in f.cells)
        #: 当前被装置占掉（地形被重写、不算田地）的格子。
        self._severed: set[tuple[int, int]] = set()
        self._index: dict[tuple[int, int], Field] = {}
        self._rebuild_index()
        self._seed()

    # ---------------------------------------------------------- 构造

    def _rebuild_index(self) -> None:
        self._index = {c: f for f in self.fields for c in f.cells}

    def _seed(self) -> None:
        """按 `init_pollut_value` 播种。

        ⚠ **一处歧义，标为待实机校正。** 关卡数据写的是**坐标 + 值**
        （`7,1:100`），所以本实现把那一格的【实际】设为该值、并把所属田地的
        【最大】抬到该值；**同组其余格子的【实际】仍从 0 起**，之后按
        「每秒向【最大】靠拢」爬升（该组每秒 +5）。

        另一种读法是**整片播种**——`init_pollut_value` 是「该田地区域的初始
        病害值」，则同组每一格的【实际】都从该值起。两者在开场那一秒差别很大：
        格子里有单位的场合，逐格播种给 `basic_damage`（20），整片播种给
        `basic_damage + 100×damage_ratio`（320）。

        当前取逐格，理由是数据格式本身就是「单点 + 值」，且 `act31side_ex03`
        确实给了**两个**点（`5,5:90|5,3:90`）而它们落在**同一片**田地里——
        若是整片播种，第二个点就是冗余的。**这个理由不是定论。**
        """
        for (x, y), v in self.params.init_pollut.items():
            f = self._index.get((x, y))
            if f is None:
                continue          # 污染点落在了非田地上，忽略（关卡数据不多管）
            self.actual[(x, y)] = min(POLLUT_MAX, max(POLLUT_MIN, v))
            f.maximum = max(f.maximum, v)
        for f in self.fields:
            f.clamp()

    # ---------------------------------------------------------- 查询

    def field_at(self, x: int, y: int) -> Field | None:
        return self._index.get((x, y))

    def is_farmland(self, x: int, y: int) -> bool:
        return (x, y) in self._index

    def actual_at(self, x: int, y: int) -> float:
        return self.actual.get((x, y), 0.0)

    def maximum_at(self, x: int, y: int) -> float:
        f = self._index.get((x, y))
        return f.maximum if f else 0.0

    # ---------------------------------------------------------- 装置接口

    def add_cache(self, x: int, y: int, amount: float) -> float:
        """往该格所属田地的【缓存】里加病害（泵站、天桩等装置走这里）。

        返回实际加进去的量。**缓存加的是【最大】不是【实际】**——
        原文「每0.2s释放1点病害值**累加至当前的【最大病害值】上**」。
        """
        f = self._index.get((x, y))
        if f is None:
            return 0.0
        f.cache += amount
        return amount

    def zero_cell(self, x: int, y: int) -> None:
        """把这一格的【实际】清零（阻流阀的行为之一）。"""
        self.actual.pop((x, y), None)

    def drain_cell(self, x: int, y: int, amount: float) -> float:
        """从这一格的【实际】病害值里扣掉 `amount`，返回**实际扣掉的量**。

        对应敌人「瘴 / 鄙瘴」的充能：重生期间每 0.5s，
        「若自身所在田地地块病害值>0，则降低此地块10点病害值并获得1层充能」。

        ⚠ 三处口径，写的时候别"顺手统一"：
        * 判据是**这一格**的病害值 > 0（不是它所属连片的【最大】）；
          扣的也是**这一格**的【实际】。若不大于 0 则**不扣、也不给层数**——
          原文把「降低」与「获得1层充能」写在同一个条件里。
        * 只动【实际】，**不动【最大】**。这跟泵站受污那一支（两者都抬）
          不对称，但两边原文就是这么写的。
        * 返回实际扣掉的量而不是请求量：本格不足 `amount` 时按剩余量扣，
          避免把负数写进 `actual`。
        """
        cur = self.actual.get((x, y), 0.0)
        if cur <= 0.0:
            return 0.0
        moved = min(amount, cur)
        left = cur - moved
        if left <= 0.0:
            self.actual.pop((x, y), None)
        else:
            self.actual[(x, y)] = left
        return moved

    # ---------------------------------------------------------- 污染

    def pollute_cell(self, x: int, y: int, amount: float) -> float:
        """把 **+`amount` 病害**记到这一格所属田地的【缓存】里，返回记入量。

        用于所有「令…**田地地块病害值+N**」的效果：秽 / 除秽 / 肮 / 厌肮被击倒时
        的污染（+5 / +15）、「祟」每层蜕皮的 +4、被标记者退场时的 +40、玷的 +5。

        ⚠ **不是直接加到【实际】或【最大】上**，这一点是博士 2026-09-17 给出
        prts.wiki「特殊机制#病害值」原文后才定下的：

        > 受到污染（病害值=0）时：【缓存】获得的病害，每0.2s释放1点病害值
        > **累加至当前的【最大病害值】上**；每1秒更新自身的【实际病害值】
        > 直到达到【最大病害值】…

        也就是说「病害值 +N」这句话的落地路径是
        **缓存 →（每 0.2s 释放 1 点）→ 【最大】 →（每 1s 靠拢）→ 【实际】**。

        我先前写的是"立刻加【实际】，并顺手抬【最大】"，还为「要不要抬【最大】」
        列了两种读法（`POLLUTE_LIFTS_MAX`）——**那是个假的两难**：原文里
        污染根本不直接落到任何一套值上，两种读法都不对。这条路径还解释得通
        另一件事：为什么被击倒污染 5 点之后，效果不是"啪"地一下，而是慢慢涨。

        返回**记入缓存的量**（不是最终落到【最大】的量）——释放是渐进的、
        且【最大】在 100 封顶，所以两者本来就不是一个数。用它判断
        「这一下有没有落在田地上」是安全的：非田地返回 0。
        """
        f = self._index.get((x, y))
        if f is None or amount <= 0:
            return 0.0
        f.cache += amount
        return amount

    def pollute_area(self, x: int, y: int, radius: float,
                     amount: float) -> float:
        """把半径 `radius` 格**圆**内所有田地格各 +`amount` 病害，返回记入总量。

        每个受影响的格子**各自**往它所属田地的【缓存】里加一份：同一片田地里
        有 3 个格子在范围内，就加 3×`amount`（原文是"范围内的**田地地块**+N"，
        按地块算，不是按连片算一次）。

        非田地格被跳过，不报错（原文一律限定「田地地块」）。返回值用于
        自检与日志判断「这一下到底有没有落到田地上」，落在高台或图外时自然为 0。
        """
        total = 0.0
        for c in cells_in_radius(x, y, radius):
            total += self.pollute_cell(*c, amount)
        return total

    def sever(self, x: int, y: int) -> list[Field]:
        """把这一格从田地里摘掉，并重算连通域。

        对应「阻流阀」：它把**自身地块**的`地形标记`重写为「阻流阀」，
        该格不再是田地，于是原本连片的田地被断开。
        断开后**各组各自取当前最高的【实际病害值】作为新的【最大】**——
        这正是 `actual` 必须按格存的原因，否则「各组当前最高」无从谈起。

        返回重建后的分组。

        ⚠ 切分时**缓存一律归零**（`Field(cache=0.0)`）。这不是"丢掉缓存"：
        原文说建成的瞬间「令所在地形的实际病害值/**缓存病害值**变为0」，而
        建成要么发生在开场（预置阻流阀）、要么发生在手动部署后的 3 秒内，
        那时**还没有任何污染**，缓存必然是 0。真要在有污染时切分（例如将来
        支持"拆掉一个已建成的阻流阀再原样建回去"），这条得改成按格记缓存。
        """
        if not self.severable or (x, y) not in self._index:
            return self.fields
        old = self._index[(x, y)]
        self.actual.pop((x, y), None)
        self._severed.add((x, y))

        rest = old.cells - {(x, y)}
        groups = farmland_groups(self.map, rest)
        if not groups:
            self.fields = [f for f in self.fields if f is not old]
            self._rebuild_index()
            return self.fields

        fresh = []
        for g in groups:
            peak = max((self.actual.get(c, 0.0) for c in g), default=0.0)
            fresh.append(Field(cells=g, maximum=peak, cache=0.0))
        # 该组之外的田地原样保留
        self.fields = [f for f in self.fields if f is not old] + fresh
        self._rebuild_index()
        return self.fields

    def restore(self, x: int, y: int) -> list[Field]:
        """把这一格**还回**田地（阻流阀被摧毁 / 被撤回时），并重算连通域。

        与 `sever` 对称。原文（prts.wiki「阻流阀」装置机制）：

            令所在地形的实际病害值/缓存病害值变为0且不视为「田地」地块
            （实际效果为：**自技能结束到自身退场**，重写自身所在地块的
            **地形标记**为**阻流阀**）；被分隔的连片田地各自以当前的最高
            实际病害值作为当前最大病害值。

        「**自技能结束到自身退场**」是这句话的关键：重写是**有期限**的，装置
        一退场（被田鼷拆掉、或被玩家撤回），地形标记就回到原来的水田——所以
        必须有这条还原路径。三条边界写清楚：

        * **不是田地的格子不做任何事**：`_all_cells` 记的是地形原本的田地格，
          高台/地面格即便被装置占了也不算田地，还回来还是不算。
        * **还回来的格子【实际】从 0 起**：它从建成起就不是田地，任何污染都
          没记在它头上（建成时原文也要求「实际/缓存病害值变为0」）。
        * **合并时缓存相加**：还原只会让田地**变多、连通**（永远不会再切分），
          所以每片旧田地整个落进某一新片里，把各旧片的【缓存】相加就是新片的
          待释放量——污染已经在缓存里、迟早要释放，不该因为合并而消失。
        * **【最大】取"旧的最高"与"当前最高的实际"里更大的那个**：原文那条
          「各自以当前的最高实际病害值作为当前最大」是**切分**时的规矩；合并时
          若照抄它，会把已经释放进【最大】、但【实际】还没爬上去的值抹掉
          （缓存→最大→实际 是三步，中间那步的值不能因为合并而归零）。
        """
        if (not self.severable or (x, y) in self._index
                or (x, y) not in self._all_cells):
            return self.fields

        self._severed.discard((x, y))
        self.actual.pop((x, y), None)          # 还回来时不带污染
        cells = set(self._all_cells) - self._severed
        groups = farmland_groups(self.map, cells)

        # 旧片 → 新片 的归属：一次还原只做合并，故每片旧田地整个进某一片新田地。
        fresh: list[Field] = []
        for g in groups:
            peak = max((self.actual.get(c, 0.0) for c in g), default=0.0)
            merge = [f for f in self.fields if f.cells & g]
            cache = sum(f.cache for f in merge)
            top = max((f.maximum for f in merge), default=0.0)
            fresh.append(Field(cells=g, maximum=max(peak, top), cache=cache))
        self.fields = fresh
        self._rebuild_index()
        return self.fields

    # ---------------------------------------------------------- 泵站

    def pump(self, cell: tuple[int, int], direction: str, *,
             ally_on_source: bool = False, rate: float = PUMP_RATE,
             front_range: int | None = None) -> dict[str, Any] | None:
        """泵站「泵水」一次（每秒结算一次）。

        原文（prts.wiki「泵站」装置机制，逐字）：

            部署后若自身身后一格为田地，且自身前方生效范围（默认身前一格）
            存在可用的田地时执行泵水：将身后一格的水泵至生效范围
            · 若水源地为清澈（病害值=0），则以每秒1点的速度'''降低'''目标格
              所在连片田地【最大病害值】；
            · 若水源地为污染状态（病害值>0），则以每秒1点的速度'''增加'''目标格
              所在连片田地各田地【当前病害值】及【最大病害值】，当 目标格所在
              连片田地≥水源地 的【最大病害值】时停止增加；
            · 若水源地部署有我方单位，自身生效范围+2；
            · 同一泵站对同一连片田地只生效一次增减效果，多个泵站作用于同一
              连片田地时效果可叠加

        三处容易被"顺手续上"的地方，这里都按原文的边界停住：

        * **降低的只有【最大】**，不动各格的【当前】；而**增加的既有【当前】
          也有【最大】**。两个分支不对称，这是原文自己写的，不是笔误。
        * 污染的停止条件是 **目标组【最大】 ≥ 水源地【最大】**（组间比较），
          不是"等于水源地那一格的病害值"。
        * `生效范围` 是**前方格数**（默认 1），不是我方单位那种攻击范围几何。

        返回这一步做了什么（便于自检与日志）；条件不满足时返回 None。
        """
        src = behind_of(cell, direction)
        if src is None or not self.is_farmland(*src):
            return None                      # 身后一格不是田地 → 不泵水

        span = PUMP_RANGE if front_range is None else front_range
        if ally_on_source:
            span += PUMP_RANGE_BONUS
        d = DIRECTIONS[(direction or "").upper()]
        target = None
        for k in range(1, span + 1):
            cand = (cell[0] + d[0] * k, cell[1] + d[1] * k)
            if self.is_farmland(*cand):
                target = cand
                break
        if target is None:
            return None                      # 前方生效范围内没有可用的田地

        g = self.field_at(*target)
        if g is None:
            return None

        src_wet = self.actual_at(*src)
        if src_wet <= 0:
            moved = min(rate, g.maximum)
            g.maximum -= moved
            g.clamp()
            return {"kind": "clear", "source": src, "target": target,
                    "group": id(g), "delta": -moved}

        # 受污：抬目标组的【最大】与**各格的【当前】**，直到追平水源组的【最大】
        src_max = self.maximum_at(*src)
        if g.maximum >= src_max:
            return {"kind": "hold", "source": src, "target": target,
                    "group": id(g), "delta": 0.0}
        g.maximum += rate
        g.clamp()
        for c in g.cells:
            self.actual[c] = min(POLLUT_MAX, self.actual.get(c, 0.0) + rate)
        return {"kind": "raise", "source": src, "target": target,
                "group": id(g), "delta": rate}

    # ---------------------------------------------------------- 演化

    def tick(self, dt: float) -> None:
        """推进 `dt` 秒。0.2s 释缓存、1s 靠拢，各自累加到点才触发。"""
        if dt <= 0:
            return
        self._t_cache += dt
        self._t_actual += dt

        while self._t_cache >= CACHE_INTERVAL:
            self._t_cache -= CACHE_INTERVAL
            for f in self.fields:
                if f.cache > 0:
                    moved = min(CACHE_PER_TICK, f.cache)
                    f.cache -= moved
                    f.maximum += moved
                    f.clamp()

        while self._t_actual >= ACTUAL_INTERVAL:
            self._t_actual -= ACTUAL_INTERVAL
            for f in self.fields:
                for c in f.cells:
                    cur = self.actual.get(c, 0.0)
                    delta = f.maximum - cur
                    if delta == 0:
                        continue
                    if delta > 0:
                        cur = min(f.maximum, cur + actual_step(delta))
                    else:
                        cur = max(f.maximum, cur - actual_step(-delta))
                    self.actual[c] = min(POLLUT_MAX, max(POLLUT_MIN, cur))

    # ---------------------------------------------------------- 结算

    def deploy_damage(self, x: int, y: int) -> float:
        """部署瞬间的一次性环境法术伤害。

        `first_basic_damage + 实际病害值 × first_damage_ratio`。
        病害值为 0 时不结算（原文：等于 0 时走回复那条）。
        """
        a = self.actual_at(x, y)
        if a <= 0 or not self.is_farmland(x, y):
            return 0.0
        return self.params.first_basic_damage + a * self.params.first_damage_ratio

    def damage_per_second(self, x: int, y: int) -> float:
        """每秒的环境法术伤害：`basic_damage + 实际病害值 × damage_ratio`。"""
        a = self.actual_at(x, y)
        if a <= 0 or not self.is_farmland(x, y):
            return 0.0
        return self.params.basic_damage + a * self.params.damage_ratio

    def regen_per_second(self, x: int, y: int) -> float:
        """病害值为 0 时的每秒回复量；不为 0 则为 0。"""
        if not self.is_farmland(x, y) or self.actual_at(x, y) > 0:
            return 0.0
        return self.params.hp_recovery_per_sec

    # ---------------------------------------------------------- 呈现

    def render(self) -> str:
        """给自检/CLI 看的一张病害值表（按行打印，与地图同向）。"""
        lines = []
        for y in range(self.map.height):
            cells = []
            for x in range(self.map.width):
                f = self._index.get((x, y))
                if f is None:
                    cells.append("  . ")
                else:
                    cells.append(f"{int(self.actual.get((x, y), 0)):>3} ")
            lines.append("".join(cells))
        return "\n".join(lines)

    def summary(self) -> str:
        live = [f for f in self.fields if f.cells]
        dirty = [f for f in live if f.maximum > 0 or f.cache > 0]
        worst = max((self.actual.get(c, 0.0) for c in self._index), default=0.0)
        return (f"田地 {len(self._index)} 格 / {len(live)} 片，"
                f"有病害的 {len(dirty)} 片，最高实际病害值 {worst:g}")
