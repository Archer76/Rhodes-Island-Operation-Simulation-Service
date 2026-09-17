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

__all__ = [
    "DIFFICULTIES", "RUNES_KEY", "FARMLAND_EXCLUDED_KEYS",
    "POLLUT_MIN", "POLLUT_MAX", "CACHE_INTERVAL", "CACHE_PER_TICK",
    "ACTUAL_INTERVAL", "ACTUAL_PER_DIVISOR", "ACTUAL_BASE_STEP",
    "PUMP_RATE", "PUMP_RANGE", "PUMP_RANGE_BONUS", "POLLUTE_LIFTS_MAX",
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

#: 「令…半径 1.0 范围内的田地地块病害值 +N」这类**一次性加病害值**的做法：
#: 抬【实际】的同时要不要把该片的【最大】也顶上去？
#:
#: ⚠ **原文没有明说，这是本项目的一处待裁定读数**，两读法都有自检盯着：
#:
#: * **甲（当前实现，`True`）**：两者都抬。理由是「对田地造成病害污染」
#:   （秽 / 除秽 / 肮 / 厌肮被击倒时的能力）若只抬【实际】，靠拢会在下一秒
#:   按 `ceil(差值/25+1)` 把它拉回【最大】（差值 20 → 每秒掉 2 点），
#:   污染变成几秒的闪烁，与「造成**严重**病害污染」的措辞不符；
#:   且同一活动里泵站的受污支正是「【当前】及【最大】」两者都抬。
#: * **乙**：只抬【实际】。理由是同一条原文在泵站那一处**明确写了两种量**，
#:   而这里只写「地块病害值」，按字面只该动**按格存的那个量**（即【实际】）。
#:
#: 甲、乙在「敌人刚倒下那一秒」完全相同，之后分道扬镳：甲留下持续污染，
#: 乙在十几秒内被靠拢抹平。**待实机校正**（见 docs/uncertainties.md）。
POLLUTE_LIFTS_MAX = True


# ================================================================ 一、runes 黑板

def mask_applies(mask: str | None, difficulty: str) -> bool:
    """这条 rune 在当前难度下生效吗。

    `ALL` 必须认——`act31side_08` 用的就是它，不认则整条环境系统静默消失。
    """
    return mask in ("ALL", "", None) or mask == difficulty


def find_rune(runes: Iterable[dict], key: str,
              difficulty: str = "NORMAL") -> dict | None:
    """按 `difficultyMask` **消歧**后取 rune，取不到返回 None。

    ⚠ **禁止取第一条**：同一关常有多条同名 rune（`act31side_ex08` 的
    `env_system_new` 有 NORMAL 与 FOUR_STAR 两条，黑板数值相同但
    `init_pollut_value` 不同——`1,1:0` vs `4,4:100`）。取错了不会报错，
    只是污染点画在了别处。
    """
    hit = None
    for r in runes:
        if r.get("key") == key and mask_applies(r.get("difficultyMask"), difficulty):
            hit = r                      # 同键同难度若仍有多条，取最后一条
    return hit


def bb_number(entries: Iterable[dict] | None, key: str) -> float | None:
    """从黑板上取**数值**——值住 `value`，不是 `valueStr`。

    这是本项目记录在案的一次真错：只读 `valueStr` 会得出「五个参数全是 None」，
    进而误判「环境系统不在 gamedata 里」。
    """
    for e in entries or ():
        if e.get("key") == key:
            v = e.get("value")
            if isinstance(v, (int, float)):
                return float(v)
            return None
    return None


def bb_text(entries: Iterable[dict] | None, key: str) -> str | None:
    """从黑板上取**字符串**——值住 `valueStr`（`key` / `init_pollut_value` 走这条）。"""
    for e in entries or ():
        if e.get("key") == key:
            v = e.get("valueStr")
            if isinstance(v, str) and v.strip():
                return v.strip()
            return None
    return None


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
        """把**这一格**的病害值抬高 `amount` 点，返回实际抬高的量。

        用于所有「令…地块病害值+N」的效果：秽 / 除秽 / 肮 / 厌肮被击倒时的
        污染（+5 / +15）、「祟」每层蜕皮的 +4、被标记单位退场时的 +50、
        玷的「污」+5。

        三条口径：

        * **不是田地就什么也不做**（返回 0）——原文一律写「**田地**地块」。
        * 上限是 100（`POLLUT_MAX`），超出部分被吃掉，返回值是**实际**增量，
          所以「甲给满值格子加 5」会如实返回 0 而不是 5。
        * 【最大】要不要一起抬见 `POLLUTE_LIFTS_MAX`，那里写了两读法的理由。
        """
        f = self._index.get((x, y))
        if f is None or amount <= 0:
            return 0.0
        cur = self.actual.get((x, y), 0.0)
        new = min(POLLUT_MAX, cur + amount)
        applied = new - cur
        if applied <= 0:
            return 0.0
        self.actual[(x, y)] = new
        if POLLUTE_LIFTS_MAX and new > f.maximum:
            f.maximum = min(POLLUT_MAX, new)
        return applied

    def pollute_area(self, x: int, y: int, radius: float,
                     amount: float) -> float:
        """把半径 `radius` 格**圆**内所有田地格各抬高 `amount` 点。

        返回这些格子实际抬高的**总量**（不是格数）——自检与日志用它判断
        「这一下到底有没有落到田地上」，落在高台或图外时自然为 0。
        非田地格被跳过，不报错（原文一律限定「田地地块」）。
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
        """
        if not self.severable or (x, y) not in self._index:
            return self.fields
        old = self._index[(x, y)]
        self.actual.pop((x, y), None)

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
