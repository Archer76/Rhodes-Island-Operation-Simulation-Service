"""关卡解析：地图网格、出怪路线、波次时间轴。

数据来自 gamedata 的 `levels/obt/<章节>/level_<levelId>.json`。一份关卡在
纸面上就是这几块：

* `mapData.map` —— 一个 `行 × 列` 的索引表，指进 `mapData.tiles`
* `mapData.tiles` —— 扁平瓦片表，每个格子记录高度、可否部署、可否通行
* `routes` —— 27 条左右的折线，每条是一个「出生点 → 途经点 → 防守点」的路径
* `waves[].fragments[].actions[]` —— 出怪指令
* `options` —— 初始费用、生命值、人数上限这些关卡参数

坐标系按 **MAA 标准**：``(x, y)``，**原点在左上**，x 向右、y 向**下**。

这么定有两条理由：

1. ``mapData.map`` 的第 0 行本来就是**最上面那一行**，直接按行读即可，
   不必再做 ``H-1-y`` 的翻转——**翻转正是原来最容易搞错的一步**。
2. MAA 作业的 ``location: [x, y]`` 用的就是这个口径，导出时零换算。

代价是关卡 JSON 里 ``routes`` 的 ``row`` 是**游戏内部的 y（自下而上）**，
与网格相反，所以路线坐标解析时要翻转一次（``y = H - 1 - row``）。
判据：SR-EX-8 的 38 条路线全都 ``APPEAR_AT_POS`` 到 ``(6,3)``，
只有翻转后才落在 ``tile_telout`` 上；不翻会落在普通地板上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any, Iterable

from .source import GameDataSource, GamedataError

#: 瓦片种类 → 展示符号。前两个都是高台，区别只在于能不能站人。
TILE_SYMBOLS = {
    "tile_wall": "H",            # 高台，可部署远程
    "tile_forbidden": "#",       # 高台，不可部署（边界/障碍）
    "tile_road": ".",            # 地面，可部署近战
    "tile_floor": ",",           # 地面，可通行但不可部署
    "tile_start": "S",           # 敌人出生点
    "tile_end": "E",             # 防守目标点
    # 下面几种只在复杂关卡出现（SR-EX-8 就有），1-7 里没有
    "tile_telin": "I",           # 传送入口：走上去会被送走
    "tile_telout": "O",          # 传送出口
    "tile_hole": "o",            # 洞穴：不可走，掉进去会死
    "tile_replace_wall": "w",    # 可被替换/破坏的墙
    "tile_replace_road": "r",    # 可被替换成路的地面
}

#: 字段上像普通地面、实际**地面敌人不可走**的地块。
#:
#: 为什么必须单独列：`tile_hole`、`tile_floor`、`tile_start`、`tile_end`、
#: `tile_telin`、`tile_telout` 的 `(heightType, buildableType, passableMask)`
#: **完全相同**，都是 `LOWLAND / NONE / ALL`。洞穴「不可走、走进去会死」这个
#: 行为**不在数据字段里**，只能按 `tileKey` 名字判（用户口径，2026-09-15）。
IMPASSABLE_KEYS = frozenset({"tile_hole"})


@dataclass(frozen=True)
class Tile:
    """一个格子。"""

    key: str
    height: str        # HIGHLAND / LOWLAND
    buildable: str     # NONE / MELEE / RANGED / **ALL**
    passable: str      # ALL / FLY_ONLY

    @property
    def is_highland(self) -> bool:
        return self.height == "HIGHLAND"

    @property
    def is_lowland(self) -> bool:
        return self.height == "LOWLAND"

    # ⚠ `ALL` 是**真实取值**，不是笔误：关卡 `mapData.tiles[].buildableType`
    # 一共四个取值（全量扫过 `data/gamedata` 的 34 个怀黍离关卡文件：
    # NONE 1779 / MELEE 788 / RANGED 359 / **ALL 75**），`ALL` = 地面与高台都能放。
    # 原先这里只认 MELEE / RANGED，于是 `ALL` 落进"两种都不能"：
    # `act31side_ex05`（33 格）与 `act31side_sub-1-2`（42 格）**整图一个可部署格
    # 都没有**，搜索的几何剪枝自然一个候选都不剩——症状就是"无论选什么都是
    # 0 条结果"（见 `docs/environment.md` 第十四节）。
    @property
    def deployable_melee(self) -> bool:
        """能站地面干员。"""
        return self.buildable in ("MELEE", "ALL")

    @property
    def deployable_ranged(self) -> bool:
        """能站高台干员。"""
        return self.buildable in ("RANGED", "ALL")

    @property
    def deployable(self) -> bool:
        return self.buildable in ("MELEE", "RANGED", "ALL")

    @property
    def walkable(self) -> bool:
        """地面敌人能走。"""
        return self.passable == "ALL" and self.key not in IMPASSABLE_KEYS

    @property
    def symbol(self) -> str:
        return TILE_SYMBOLS.get(self.key, "?")

    def to_dict(self) -> dict:
        return {"key": self.key, "height": self.height,
                "buildable": self.buildable, "passable": self.passable}


@dataclass
class StageMap:
    """关卡地图。(x, y)，**原点在左上**、y 向下（MAA 标准）。"""

    width: int
    height: int
    tiles: list[list[Tile]]          # tiles[y][x]

    def tile(self, x: int, y: int) -> Tile:
        return self.tiles[y][x]

    def inside(self, x: int, y: int) -> bool:
        return 0 <= x < self.width and 0 <= y < self.height

    def find(self, *keys: str) -> list[tuple[int, int]]:
        want = set(keys)
        return [(x, y) for y in range(self.height) for x in range(self.width)
                if self.tiles[y][x].key in want]

    @property
    def spawn_points(self) -> list[tuple[int, int]]:
        """敌人出生格（tile_start）。"""
        return self.find("tile_start")

    @property
    def end_points(self) -> list[tuple[int, int]]:
        """防守目标格（tile_end）。"""
        return self.find("tile_end")

    @property
    def melee_spots(self) -> list[tuple[int, int]]:
        """可以放地面干员的格子。"""
        return [(x, y) for y in range(self.height) for x in range(self.width)
                if self.tiles[y][x].deployable_melee]

    @property
    def ranged_spots(self) -> list[tuple[int, int]]:
        """可以放高台干员的格子。"""
        return [(x, y) for y in range(self.height) for x in range(self.width)
                if self.tiles[y][x].deployable_ranged]

    # ------------------------------------------------------------ 寻路

    def walkable(self, x: int, y: int) -> bool:
        """地面敌人能不能走这一格。

        两个条件同时成立才算可走：`passable` 含 `ALL`，**且**不是
        `IMPASSABLE_KEYS` 里的特殊地块。前者把 `tile_wall`/`tile_forbidden`
        （FLY_ONLY）挡掉，后者把 `tile_hole` 挡掉。

        关于洞（2026-09-15 更正）：本方法原先只判 `"ALL" in passable`，
        于是把 `tile_hole` 当成了可走的普通地面，旧注释还写着「按洞不可走会切
        断 SR-6 的唯一通路」——**该理由经实测不成立**。把洞封掉后 SR-6 的 21
        条路线全部仍然连通，只是其中 12 条各长 0.59 格：旧口径下敌人会从
        `(8,1)[洞] → (9,2)` 斜切一步角（切角的直角边正好踩在洞上），
        路线 0 走成 11.41 格，封洞后是 12.00 格。
        """
        return (self.inside(x, y)
                and "ALL" in self.tiles[y][x].passable
                and self.tiles[y][x].key not in IMPASSABLE_KEYS)

    def ground_path(self, start: tuple[int, int], end: tuple[int, int],
                    *, diagonal: bool = True) -> list[tuple[int, int]]:
        """在可行走地块上求最短路径，返回**格心**折线（含起终点）。

        为什么需要它：关卡数据里有的路线带一串 MOVE 路点（1-7 就是），把路点
        连起来就是轨迹；但 **SR-6 的 21 条路线一条 MOVE 都没有**，只有起点和
        终点。这时候敌人不是走直线——`options.steeringEnabled = true` 表示它
        沿可行走地块绕行。用直线会得到 `(4,1) → (5,4)` 这种横穿 `tile_wall`
        的假路径，算出来的到达时刻比真实早十几秒。

        代价：直行 1、斜行 √2，且**不许斜穿墙角**（斜向的两条直角边都得可走），
        否则敌人会从两个 `tile_wall` 的接缝里钻过去。
        """
        import heapq

        if start == end:
            return [start]
        if not self.walkable(*start) or not self.walkable(*end):
            return [start, end]          # 数据有问题时退回直线，别静默给空路径

        steps = [(1, 0), (-1, 0), (0, 1), (0, -1)]
        if diagonal:
            steps += [(1, 1), (1, -1), (-1, 1), (-1, -1)]
        diag = 1.4142135623730951

        dist: dict[tuple[int, int], float] = {start: 0.0}
        prev: dict[tuple[int, int], tuple[int, int]] = {}
        pq: list[tuple[float, tuple[int, int]]] = [(0.0, start)]
        while pq:
            d, cur = heapq.heappop(pq)
            if cur == end:
                break
            if d > dist.get(cur, float("inf")):
                continue
            cx, cy = cur
            for dx, dy in steps:
                nxt = (cx + dx, cy + dy)
                if not self.walkable(*nxt):
                    continue
                if dx and dy and not (self.walkable(cx + dx, cy)
                                      and self.walkable(cx, cy + dy)):
                    continue
                nd = d + (diag if dx and dy else 1.0)
                if nd < dist.get(nxt, float("inf")):
                    dist[nxt] = nd
                    prev[nxt] = cur
                    heapq.heappush(pq, (nd, nxt))

        if end not in dist:
            return [start, end]          # 不连通，同样退回直线
        out = [end]
        while out[-1] != start:
            out.append(prev[out[-1]])
        out.reverse()
        return out

    def path_length(self, path: list[tuple[int, int]]) -> float:
        """折线总长（格）。"""
        return sum(math.dist(a, b) for a, b in zip(path, path[1:]))

    # ------------------------------------------------------------ 渲染

    def render(self, *, overlay: dict[tuple[int, int], str] | None = None,
               pad: int = 1, marks: dict[tuple[int, int], str] | None = None) -> str:
        """画成字符地图。y 向下递增，按打印顺序读即从上往下。"""
        cell_w = max(1, pad + 1)
        header = " " * 5 + "".join(str(x).rjust(cell_w) for x in range(self.width))
        lines = [header]
        for y in range(self.height):
            row = []
            for x in range(self.width):
                ch = self.tiles[y][x].symbol
                if marks and (x, y) in marks:
                    ch = marks[(x, y)]
                if overlay and (x, y) in overlay:
                    ch = overlay[(x, y)]
                row.append(ch.rjust(cell_w))
            lines.append(f"y={y}  " + "".join(row))
        return "\n".join(lines)

    def render_plain(self, *, overlay: dict[tuple[int, int], str] | None = None) -> str:
        """不带坐标的紧凑版。"""
        lines = []
        for y in range(self.height):
            lines.append(" ".join(
                (overlay or {}).get((x, y)) or self.tiles[y][x].symbol
                for x in range(self.width)))
        return "\n".join(lines)

    def describe(self) -> str:
        return (f"{self.width}×{self.height}  "
                f"地面可部署 {len(self.melee_spots)} 格 / "
                f"高台可部署 {len(self.ranged_spots)} 格 / "
                f"出生点 {len(self.spawn_points)} / 防守点 {len(self.end_points)}")


@dataclass
class Checkpoint:
    """路线上的一个途经指令。

    这里的 `type` 很要紧。1-7 那种简单图全是 `MOVE`，看不出问题；但
    SR-EX-8 这类关卡会掺进 `WAIT_FOR_SECONDS`——**那种节点的 position
    是 (0,0) 占位，没有意义**。把它当成坐标读，路线图上会凭空多出一条
    穿过地图原点的假路径，而且终点还落在地图外的墙角。
    """

    type: str
    position: tuple[int, int] | None = None
    wait: float = 0.0            # WAIT_FOR_SECONDS 的秒数

    @property
    def is_move(self) -> bool:
        return self.type == "MOVE"

    @property
    def is_wait(self) -> bool:
        return self.type.startswith("WAIT")

    @property
    def is_appear(self) -> bool:
        """传送落点：敌人凭空出现在这一格。坐标是**真实**的。"""
        return self.type == "APPEAR_AT_POS"

    @property
    def has_position(self) -> bool:
        """这个节点的坐标能不能用。

        `MOVE` 与 `APPEAR_AT_POS` 有真坐标；`WAIT_FOR_SECONDS` 与
        `DISAPPEAR` 的 position 一律是 (0,0) 占位。
        """
        return self.position is not None

    def to_dict(self) -> dict:
        d: dict = {"type": self.type}
        if self.position is not None:
            d["position"] = list(self.position)
        if self.wait:
            d["wait"] = self.wait
        return d


@dataclass(frozen=True)
class RouteLeg:
    """路线的一段。三种段落：

    * `walk`   —— 沿 `points` 折线走，`length` 是折线总长（格）
    * `wait`   —— 原地待命 `seconds` 秒（WAIT_FOR_SECONDS）
    * `vanish` —— **离场** `seconds` 秒（DISAPPEAR → 等待 → APPEAR_AT_POS）。
      这段时间敌人不在地图上：不能被打、不能阻挡、也不该算作漏怪。

    为什么必须分段，而不能把整条路线连成一条折线：SR-EX-8 的 38 条路线都是
    「走进传送口 → 消失 → 在 (6,3) 出现」。连成折线的话，敌人会从 (0,6)
    **横穿半张地图**走到 (6,3)，而不是瞬间传送过去——路径长度、到达时刻、
    沿途会不会被拦，全都是错的。
    """

    kind: str
    points: tuple[tuple[int, int], ...] = ()
    seconds: float = 0.0
    length: float = 0.0

    @property
    def is_walk(self) -> bool:
        return self.kind == "walk"

    @property
    def is_vanish(self) -> bool:
        return self.kind == "vanish"

    def to_dict(self) -> dict:
        d: dict[str, Any] = {"kind": self.kind}
        if self.points:
            d["points"] = [list(p) for p in self.points]
            d["length"] = round(self.length, 3)
        if self.seconds:
            d["seconds"] = self.seconds
        return d

    def __str__(self) -> str:
        if self.is_walk:
            pts = "→".join(f"({x},{y})" for x, y in self.points)
            return f"走 {self.length:.1f}格：{pts}"
        return f"{'离场' if self.is_vanish else '等待'}{self.seconds:g}s"


def _polyline_length(pts) -> float:
    return sum(math.dist(a, b) for a, b in zip(pts, pts[1:]))


@dataclass
class Route:
    """一条行进路线：出生点 → 若干途经指令 → 防守点。"""

    index: int
    mode: str
    start: tuple[int, int]
    end: tuple[int, int]
    checkpoints: list[Checkpoint] = field(default_factory=list)

    @property
    def path(self) -> list[tuple[int, int]]:
        """敌人实际站过的格子，含首尾。

        包含 `MOVE` 与 `APPEAR_AT_POS`（传送落点）——两者都是真坐标。
        传送处会有一次跳跃，用 `teleports` 看得出断点在哪。
        """
        pts = [self.start]
        pts += [c.position for c in self.checkpoints if c.has_position]
        pts.append(self.end)
        return pts

    @property
    def teleports(self) -> list[Checkpoint]:
        """传送落点（APPEAR_AT_POS）。"""
        return [c for c in self.checkpoints if c.is_appear]

    @property
    def waits(self) -> list[Checkpoint]:
        return [c for c in self.checkpoints if c.is_wait]

    @property
    def total_wait(self) -> float:
        return sum(c.wait for c in self.waits)

    def timeline_hint(self) -> str:
        """把这条路线的行进顺序写成人话，传送与等待都标出来。"""
        parts: list[str] = []
        for c in self.checkpoints:
            if c.is_wait:
                parts.append(f"等待{c.wait:g}s")
            elif c.is_appear:
                parts.append(f"传送至{c.position}")
            elif c.is_move:
                parts.append(str(c.position))
            elif c.type == "DISAPPEAR":
                parts.append("消失")
        return " → ".join(parts)

    @property
    def is_empty(self) -> bool:
        """空路线（起点=终点且无途经点）——关卡数据里用来占位。"""
        return not self.checkpoints and self.start == self.end

    def legs(self, *, walk_map: "StageMap | None" = None) -> list[RouteLeg]:
        """把 checkpoint 序列展开成可执行的分段计划。

        只有 `MOVE` 与 `APPEAR_AT_POS` 带真坐标；`WAIT_FOR_SECONDS` 与
        `DISAPPEAR` 的 position 是 `(0,0)` 占位，当坐标用会画出穿过地图
        原点的假路径。

        `WALK` 模式下相邻路点之间**沿可行走地块寻路**（要传 `walk_map`）：
        关卡数据给的路点之间可能隔着障碍，直线会穿墙。`FLY` 模式是直线，
        不做寻路——飞行单位本来就无视地形。
        """
        fly = (self.mode or "WALK").upper() == "FLY"
        use_map = None if fly else walk_map
        out: list[RouteLeg] = []
        walk = [self.start]

        def flush() -> None:
            if len(walk) < 2:
                return
            pts: list[tuple[int, int]] = []
            for a, b in zip(walk, walk[1:]):
                if pts:
                    pts.pop()                     # 与上一段接续，别重复顶点
                if use_map is not None and a != b:
                    pts.extend(use_map.ground_path(a, b))
                else:
                    pts.extend([a, b])
            if len(pts) >= 2:
                out.append(RouteLeg("walk", tuple(pts), 0.0,
                                    _polyline_length(pts)))

        cps = list(self.checkpoints or [])
        i = 0
        while i < len(cps):
            c = cps[i]
            if c.is_move:
                walk.append(c.position)
            elif c.type == "DISAPPEAR":
                flush()
                # 消失之后、出现之前的等待都算离场时长
                gone = 0.0
                appear: tuple[int, int] | None = None
                j = i + 1
                while j < len(cps):
                    cj = cps[j]
                    if cj.is_appear:
                        appear = cj.position
                        j += 1
                        break
                    if cj.is_wait:
                        gone += float(cj.wait or 0.0)
                    j += 1
                if gone > 0:
                    out.append(RouteLeg("vanish", (), gone, 0.0))
                walk = [appear if appear is not None else walk[-1]]
                i = j
                continue
            elif c.is_wait:
                flush()
                walk = [walk[-1]]
                if c.wait:
                    out.append(RouteLeg("wait", (), float(c.wait), 0.0))
            i += 1

        walk.append(self.end)
        flush()
        return out

    def length(self) -> int:
        """按曼哈顿距离估算的格数——用来粗比路线长短。"""
        pts = self.path
        return sum(abs(a[0] - b[0]) + abs(a[1] - b[1])
                   for a, b in zip(pts, pts[1:]))

    def to_dict(self) -> dict:
        return {"index": self.index, "mode": self.mode,
                "start": list(self.start), "end": list(self.end),
                "checkpoints": [c.to_dict() for c in self.checkpoints],
                "path": [list(p) for p in self.path],
                "waits": [c.to_dict() for c in self.waits]}

    def __str__(self) -> str:
        pts = " -> ".join(f"({x},{y})" for x, y in self.path)
        extra = f"  [等待 {self.total_wait:g}s]" if self.waits else ""
        return f"route[{self.index}] {self.mode} {pts}{extra}"


@dataclass
class EnemySpawn:
    """一条出怪指令，以及它展开后的具体出怪时刻。"""

    enemy_id: str
    count: int
    interval: float
    route_index: int
    wave_index: int
    fragment_index: int
    action_index: int
    pre_delay: float                  # 相对 fragment 开始
    fragment_start: float             # 相对 wave 开始
    level: int = 0
    block_fragment: bool = False
    hidden_group: str | None = None

    @property
    def times(self) -> list[float]:
        """这一条指令展开出的所有出怪时刻（相对 wave 开始，秒）。"""
        return [self.fragment_start + self.pre_delay + i * self.interval
                for i in range(self.count)]

    @property
    def span(self) -> float:
        """从 fragment 开始算，这条指令耗时多久。"""
        return self.pre_delay + max(0, self.count - 1) * self.interval

    @property
    def last_time(self) -> float:
        return self.times[-1] if self.count else self.fragment_start + self.pre_delay

    def to_dict(self) -> dict:
        return {"enemy_id": self.enemy_id, "count": self.count,
                "interval": self.interval, "route_index": self.route_index,
                "wave": self.wave_index, "fragment": self.fragment_index,
                "level": self.level, "block_fragment": self.block_fragment,
                "times": [round(t, 3) for t in self.times]}


@dataclass
class StageOptions:
    """关卡参数——算打法时每一个都用得上。"""

    character_limit: int = 0        # 可部署人数上限
    max_life_point: int = 0         # 生命值（漏怪扣光就失败）
    initial_cost: float = 0.0       # 初始费用
    max_cost: float = 0.0           # 费用上限
    cost_increase_time: float = 1.0  # 每点费用回复所需秒数
    move_multiplier: float = 1.0    # 敌人移速系数
    is_training: bool = False
    is_hard_training: bool = False

    def to_dict(self) -> dict:
        return {"character_limit": self.character_limit,
                "max_life_point": self.max_life_point,
                "initial_cost": self.initial_cost, "max_cost": self.max_cost,
                "cost_increase_time": self.cost_increase_time,
                "move_multiplier": self.move_multiplier}

    def __str__(self) -> str:
        return (f"人数上限 {self.character_limit} / 生命 {self.max_life_point} / "
                f"初始费用 {self.initial_cost:g} / 费用回复 {self.cost_increase_time:g}s 一点")


#: 装置「天桩」技能的**默认**分支名。`skill_table.sktok_dhdcr` 的 1 级黑板
#: 只有一个键 `branch_id = branch_dhdcr_1`；关卡没在 `overrideSkillBlackboard`
#: 里写覆盖时先试这条（`act31side_ex08` 那一个天桩连它都没有，退到"本关唯一
#: 一条同前缀支线"，见 `Stage.branch_for`）。
DEFAULT_DEVICE_BRANCH = "branch_dhdcr_1"


def branch_prefix(device_key: str) -> str:
    """装置 key → 它的支线前缀：``trap_146_dhdcr`` → ``branch_dhdcr``。

    装置 key 的末段就是支线名去掉 ``branch_`` 之后那部分（本活动的天桩
    ``trap_146_dhdcr`` 对 ``branch_dhdcr`` / ``branch_dhdcr_1..10``）。
    推不出末段就返回空串——**空串意味着"这个装置没有支线语义"**，
    阻流阀（``trap_139_dhtl``）与泵站（``trap_140_dhsb``）就靠它挡在门外：
    它们没有 ``branch_dhtl`` / ``branch_dhsb``，不会误领一条天桩的支线。
    """
    tail = (device_key or "").rsplit("_", 1)[-1]
    return f"branch_{tail}" if tail and tail != device_key else ""


@dataclass
class BranchAction:
    """一条**支线**里的出怪动作（关卡顶层 ``branches``）。
    怀黍离的用法：装置「天桩」的技能黑板只有一个键 ``branch_id``，
    它指向 ``branches`` 里的一条支线；支线里的 SPAWN 动作才是**谁在什么路径
    上出场**——`key` 是天桩-甲（或失控天桩-甲 / 关卡本地的 ``…_dhdcr_b``），
    ``routeIndex`` 指向**顶层 ``extraRoutes``**（不是 ``routes``）。
    """

    branch: str
    action_type: str
    enemy_key: str
    route_index: int
    count: int = 1
    interval: float = 1.0
    pre_delay: float = 0.0

    def to_dict(self) -> dict:
        return {"branch": self.branch, "action_type": self.action_type,
                "enemy_key": self.enemy_key, "route_index": self.route_index,
                "count": self.count, "interval": self.interval,
                "pre_delay": self.pre_delay}


@dataclass
class Stage:
    level_id: str
    code: str
    map: StageMap
    routes: list[Route]
    spawns: list[EnemySpawn]
    options: StageOptions
    raw: dict = field(default_factory=dict, repr=False)
    #: 顶层 ``extraRoutes``：**装置以预设路径召唤出来**的单位走的那几条路。
    #: 与 ``routes`` 分开存——两者的 ``routeIndex`` 命名空间不同，混用会串号。
    extra_routes: list[Route] = field(default_factory=list)
    #: 顶层 ``branches``：支线名 → 出怪动作。装置用 ``branch_id`` 指过来。
    branches: dict[str, list[BranchAction]] = field(default_factory=dict)
    #: 这一关是哪一档难度（``NORMAL`` / ``FOUR_STAR``）。**来源只有关卡索引那一条**
    #: （``LevelEntry.difficulty``）：源上「普通/四星」是**同一个数据文件**——
    #: ``act31side_ex08`` 与 ``act31side_ex08#f#`` 的 ``data_path`` 逐字相同，
    #: 只有索引分得开。
    #:
    #: ⚠ 2026-09-20 之前没有这个字段，于是四星档专属的 ``runes``
    #: （``global_lifepoint`` / ``enemy_attribute_mul`` / ``env_system_new``）
    #: **一条都不生效**，而读数与普通档**逐位相同**、也不报错。取证与判据见
    #: ``docs/hsl-backfill-attribution.md`` §四.3。
    difficulty: str = "NORMAL"

    # ------------------------------------------------------------ 查询

    def route(self, index: int) -> Route | None:
        for r in self.routes:
            if r.index == index:
                return r
        return None

    def extra_route(self, index: int) -> Route | None:
        """``extraRoutes`` 里的一条（与 ``route()`` 是两个命名空间）。"""
        for r in self.extra_routes:
            if r.index == index:
                return r
        return None

    def branch_actions(self, branch: str) -> list[BranchAction]:
        return list(self.branches.get(branch or "", []))

    def branch_for(self, branch_id: str,
                   *, prefix: str = "branch_dhdcr") -> str:
        """把一个装置的 ``branch_id`` 解析成**本关真实存在**的支线名。

        判据按可靠性从高到低，**第一条就是数据的原话**：

        1. 装置自己写了 ``branch_id`` 且本关有这条支线 → 直接用它
           （本活动 8 个带天桩的关卡全走这条）。
        2. 没写（``overrideSkillBlackboard`` 为 null）→ 先试 ``{prefix}_1``
           ——``prefix`` 由装置 key 末段推出来（``trap_146_dhdcr`` →
           ``branch_dhdcr``），而技能默认黑板（``skill_table.sktok_dhdcr``）
          写的正是 ``branch_dhdcr_1``。
        3. 还找不到 → 本关**只有一条**以该前缀开头的支线时用它
           （``act31side_ex08``：那一个天桩没写覆盖，而本关唯一的支线叫
           ``branch_dhdcr``，设计意图显然就是它）。
        4. 都不成立 → 返回空串：**宁可不召唤，也不猜错一条路**。

        ⚠ 第 2、3 条是**推断**，已登记在 `docs/verdicts-pending.md`
        （ex08 是全活动唯一踩到第 3 条的关卡）。
        """
        if branch_id and branch_id in self.branches:
            return branch_id
        if not prefix:
            return ""
        first = f"{prefix}_1"
        if first in self.branches:
            return first
        hits = [b for b in self.branches
                if b == prefix or b.startswith(prefix + "_")]
        return hits[0] if len(hits) == 1 else ""

    def used_routes(self) -> list[Route]:
        """真正被出怪指令引用到的路线。"""
        used = {s.route_index for s in self.spawns}
        return [r for r in self.routes if r.index in used]

    def local_enemies(self) -> dict[str, dict]:
        """关卡**自带的**敌人定义：``enemyDbRefs`` 里 ``useDb: false`` 的那些。

        它们的 ``id`` 不在敌人属性库里（属性库里只有 ``prefabKey`` 指向的
        那一个），整份数据就写在关卡文件的 ``overwrittenData`` 里。
        怀黍离的 ``enemy_1398_dhdcr_b``（小地图上的天桩-甲）就是这种。
        """
        out: dict[str, dict] = {}
        for ref in (self.raw.get("enemyDbRefs") or []):
            if ref.get("useDb") is False and ref.get("id"):
                out[str(ref["id"])] = dict(ref.get("overwrittenData") or {})
        return out

    def local_enemy_prefab(self, enemy_id: str) -> str:
        """关卡本地敌人的 ``prefabKey``；不是本地敌人就返回空串。

        用途：本地敌人**没有自己的天赋黑板以外的资料**，正文里那些"砸下什么"
        "召唤什么"的跳转要顺着 prefab 去找（天桩-乙的 ``…_dhtb_b`` →
        ``enemy_1399_dhtb`` → 它砸下的天标）。
        """
        data = self.local_enemies().get(enemy_id) or {}
        cell = data.get("prefabKey")
        val = cell.get("m_value") if isinstance(cell, dict) else cell
        return str(val or "")

    def enemy_counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for s in self.spawns:
            out[s.enemy_id] = out.get(s.enemy_id, 0) + s.count
        return dict(sorted(out.items(), key=lambda kv: -kv[1]))

    def total_enemies(self) -> int:
        return sum(s.count for s in self.spawns)

    def timeline(self) -> list[tuple[float, EnemySpawn]]:
        """把出怪指令摊平成按时间排序的 (时刻, 指令) 列表。"""
        events = [(t, s) for s in self.spawns for t in s.times]
        events.sort(key=lambda e: (e[0], e[1].wave_index, e[1].fragment_index))
        return events

    def estimated_duration(self) -> float:
        """最后一个敌人的出现时刻——不是通关时刻，但可作时间轴的右端。"""
        return max((t for t, _ in self.timeline()), default=0.0)

    def render_with_routes(self) -> str:
        """把路线的途经格标在地图上（一格多线时显示 *）。"""
        overlay: dict[tuple[int, int], str] = {}
        for r in self.used_routes():
            for (x, y) in r.path:
                overlay[(x, y)] = "*" if (x, y) in overlay else str(r.index % 10)
        return self.map.render(overlay=overlay)

    def to_dict(self, *, include_raw: bool = False) -> dict:
        d = {
            "level_id": self.level_id,
            "code": self.code,
            "size": [self.map.width, self.map.height],
            "options": self.options.to_dict(),
            "map": [[self.map.tile(x, y).symbol for x in range(self.map.width)]
                    for y in range(self.map.height)],
            "deployable_melee": [list(p) for p in self.map.melee_spots],
            "deployable_ranged": [list(p) for p in self.map.ranged_spots],
            "spawn_points": [list(p) for p in self.map.spawn_points],
            "end_points": [list(p) for p in self.map.end_points],
            "routes": [r.to_dict() for r in self.routes],
            "spawns": [s.to_dict() for s in self.spawns],
            "enemy_counts": self.enemy_counts(),
            "total_enemies": self.total_enemies(),
            "estimated_duration": round(self.estimated_duration(), 2),
        }
        if include_raw:
            d["raw"] = self.raw
        return d

    def summary(self) -> str:
        lines = [
            f"关卡 {self.code}（levelId={self.level_id}）",
            f"  {self.map.describe()}",
            f"  {self.options}",
            f"  敌人 {self.total_enemies()} 只，种类 {len(self.enemy_counts())}，"
            f"最后一只出现在 {self.estimated_duration():.1f}s",
            f"  路线 {len(self.routes)} 条，其中被使用 {len(self.used_routes())} 条",
        ]
        return "\n".join(lines)


# ------------------------------------------------------------------- 解析

def _parse_map(map_data: dict) -> StageMap:
    rows: list[list[int]] = map_data["map"]
    flat: list[dict] = map_data["tiles"]
    height = len(rows)
    width = len(rows[0]) if rows else 0

    grid: list[list[Tile]] = []
    for y in range(height):                 # MAA 标准：第 0 行就是最上面那一行
        row = []
        for x in range(width):
            idx = rows[y][x]
            t = flat[idx]
            row.append(Tile(
                key=t.get("tileKey", ""),
                height=t.get("heightType", ""),
                buildable=t.get("buildableType", ""),
                passable=t.get("passableMask", ""),
            ))
        grid.append(row)
    return StageMap(width=width, height=height, tiles=grid)


def _parse_routes(raw_routes: list[dict] | None,
                  height: int) -> list[Route]:
    """路线。**这里要翻一次 y**：关卡 JSON 的 ``row`` 是游戏内部口径
    （自下而上），而网格按 MAA 标准是自顶向下，故 ``y = height - 1 - row``。

    判据是 SR-EX-8：38 条路线的 ``APPEAR_AT_POS`` 全在 ``row=3``，
    地图 ``height=9``；翻转后是 ``y=5``，正落在 ``tile_telout`` 上
    （不翻会落在普通地板上，与「传送落点」的语义对不上）。
    """
    out: list[Route] = []

    def flip(pos: dict) -> tuple[int, int]:
        return (int(pos.get("col", 0)), height - 1 - int(pos.get("row", 0)))

    for i, r in enumerate(raw_routes or []):
        sp, ep = r.get("startPosition") or {}, r.get("endPosition") or {}
        cps: list[Checkpoint] = []
        for c in (r.get("checkpoints") or []):
            ctype = c.get("type") or "MOVE"
            pos = c.get("position") or {}
            if ctype in ("MOVE", "APPEAR_AT_POS"):
                # 这两种的坐标是真的。APPEAR_AT_POS 是传送落点——SR-EX-8
                # 里 38 条路线全都落在中央那个 tile_telout 上。
                cps.append(Checkpoint(
                    type=ctype,
                    position=flip(pos),
                ))
            else:
                # WAIT_FOR_SECONDS / DISAPPEAR 的 position 一律是 (0,0) 占位。
                # 当坐标读会在图上画出一条穿过地图原点的假路径。
                cps.append(Checkpoint(
                    type=ctype,
                    position=None,
                    wait=float(c.get("time") or 0.0),
                ))
        out.append(Route(
            index=i,
            mode=r.get("motionMode", ""),
            start=flip(sp),
            end=flip(ep),
            checkpoints=cps,
        ))
    return out


def _fragment_span(fragment: dict) -> float:
    """一个 fragment 从开始到「最后一个动作放完」需要多久。

    只算 SPAWN —— 剧情、预览光标这些不占时间。
    """
    end = 0.0
    for a in fragment.get("actions", []):
        if a.get("actionType") != "SPAWN":
            continue
        span = a.get("preDelay", 0.0) + max(0, a.get("count", 1) - 1) * a.get("interval", 1.0)
        end = max(end, span)
    return end


def _parse_spawns(waves: list[dict], refs: list[dict]) -> list[EnemySpawn]:
    """把波次摊平成出怪指令。

    fragment 是**串行**的：下一个 fragment 的 preDelay 从前一个 fragment 的
    最后一个出怪动作结束之后开始算。关卡数据里 `blockFragment` 全为 false
    时这个模型是精确的；若某条指令标了 blockFragment=true，实际还要等那批
    敌人离场，时间轴会比这里算出来的更晚——这种情况在 `EnemySpawn.block_fragment`
    上留了标记。
    """
    level_of = {r.get("id"): r.get("level", 0) for r in (refs or [])}
    out: list[EnemySpawn] = []

    for wi, wave in enumerate(waves or []):
        t = float(wave.get("preDelay", 0.0) or 0.0)
        for fi, frag in enumerate(wave.get("fragments", [])):
            t += float(frag.get("preDelay", 0.0) or 0.0)
            start = t
            for ai, a in enumerate(frag.get("actions", [])):
                if a.get("actionType") != "SPAWN":
                    continue
                eid = a.get("key", "")
                out.append(EnemySpawn(
                    enemy_id=eid,
                    count=int(a.get("count", 1) or 1),
                    interval=float(a.get("interval", 1.0) or 0.0),
                    route_index=int(a.get("routeIndex", 0) or 0),
                    wave_index=wi,
                    fragment_index=fi,
                    action_index=ai,
                    pre_delay=float(a.get("preDelay", 0.0) or 0.0),
                    fragment_start=start,
                    level=int(level_of.get(eid, 0) or 0),
                    block_fragment=bool(a.get("blockFragment")),
                    hidden_group=a.get("hiddenGroup"),
                ))
            t = start + _fragment_span(frag)
    return out


def _parse_options(raw: dict) -> StageOptions:
    o = raw.get("options") or {}
    return StageOptions(
        character_limit=int(o.get("characterLimit", 0) or 0),
        max_life_point=int(o.get("maxLifePoint", 0) or 0),
        initial_cost=float(o.get("initialCost", 0) or 0),
        max_cost=float(o.get("maxCost", 0) or 0),
        cost_increase_time=float(o.get("costIncreaseTime", 1.0) or 1.0),
        move_multiplier=float(o.get("moveMultiplier", 1.0) or 1.0),
        is_training=bool(o.get("isTrainingLevel")),
        is_hard_training=bool(o.get("isHardTrainingLevel")),
    )


def _parse_branches(raw: dict) -> dict[str, list[BranchAction]]:
    """顶层 ``branches``：支线名 → 出怪动作列表。

    只收 ``SPAWN`` 动作——怀黍离的支线里也只有它（剧情/预览光标那些不动敌人）。
    """
    out: dict[str, list[BranchAction]] = {}
    for name, blk in (raw.get("branches") or {}).items():
        acts: list[BranchAction] = []
        for ph in ((blk or {}).get("phases") or []):
            for a in (ph.get("actions") or []):
                if (a.get("actionType") or "").upper() != "SPAWN":
                    continue
                acts.append(BranchAction(
                    branch=name,
                    action_type="SPAWN",
                    enemy_key=str(a.get("key") or ""),
                    route_index=int(a.get("routeIndex", 0) or 0),
                    count=int(a.get("count", 1) or 1),
                    interval=float(a.get("interval", 1.0) or 1.0),
                    pre_delay=float(a.get("preDelay", 0.0) or 0.0),
                ))
        if acts:
            out[name] = acts
    return out


def parse_stage(raw: dict, *, level_id: str = "", code: str = "",
                difficulty: str = "NORMAL") -> Stage:
    """把一份关卡 JSON 解析成 Stage。

    `difficulty` 只能由调用方给（`load_stage` 从索引那条 `LevelEntry` 取）——
    数据文件里没有这个信息，默认 `NORMAL` 是为了让既有调用点行为不变。
    """
    if "mapData" not in raw:
        raise GamedataError("这份数据里没有 mapData，不像关卡文件")
    world = _parse_map(raw["mapData"])
    return Stage(
        level_id=level_id or raw.get("_levelId") or raw.get("levelId") or "",
        code=code or raw.get("_code") or level_id,
        map=world,
        # 路线的 row 要按地图高度翻一次，见 `_parse_routes`
        routes=_parse_routes(raw.get("routes"), world.height),
        # `extraRoutes` 是**另一个命名空间**（装置召唤出来的单位走它），
        # 索引与 `routes` 各自从 0 开始，不能混着查。
        extra_routes=_parse_routes(raw.get("extraRoutes"), world.height),
        branches=_parse_branches(raw),
        spawns=_parse_spawns(raw.get("waves") or [], raw.get("enemyDbRefs") or []),
        options=_parse_options(raw),
        # 难度**不在数据文件里**，只有索引那条记着它（见 `Stage.difficulty`）。
        difficulty=str(difficulty or "NORMAL"),
        raw=raw,
    )


def load_stage(query: str, *, code: str = "", chapter: str | None = None,
               source: GameDataSource | None = None) -> Stage:
    """取一份关卡并解析。

    `query` 既可以是 levelId（``main_01-07``、``act54side_ex08``），也可以是
    玩家写的关卡号（``1-7``、``SR-EX-8``）——后者由关卡索引换算。关卡数据
    内部并不记录自己的 levelId，所以这里把查到的那条回填进 `Stage`。
    """
    src = source or GameDataSource()
    entry = src.resolve_level(query)
    raw = src.level(entry.level_id, chapter=chapter)
    return parse_stage(raw, level_id=entry.level_id, code=code or entry.code,
                       # ⚠ 必须往下传：`entry.difficulty` 是**唯一**记着四星档的地方
                       # （`act31side_ex08#f#` 与普通版读同一个文件）。
                       difficulty=entry.difficulty)


def enemy_refs(raw: dict) -> list[dict]:
    """关卡引用的敌人清单（enemyDbRefs），含各自要用的等级。"""
    return list(raw.get("enemyDbRefs") or [])
