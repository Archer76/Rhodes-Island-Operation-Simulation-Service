# -*- coding: utf-8 -*-
"""敌人到达时刻（ETA）：从「移速 + 路线」解析出「几点到哪一格」。

## 为什么需要它

搜索器要评估成百上千个候选落位，而一次完整模拟是秒级的——**不能拿模拟当
内循环**。但"这个落位到底接不接得到敌人、什么时候接得到"这件事根本不需要
打架就能算：只要路线长度和移速。

于是本模块给出一个**解析式**（不是逐帧）的到达时刻表：

    走段耗时 = 距离 ÷ 速度      等待/离场段耗时 = 真实秒数
    速度(格/秒) = moveSpeed × move_multiplier × speed_scale

这与 `EnemyUnit._advance_legs` 的语义完全一致——那边也是"走段消耗
距离/速度、等待与离场段消耗真实秒数，整个循环以时间为预算"。差别只有
逐帧推进带来的 ≤1 帧（1/30 秒）量化误差。

## 与模拟器共用一份路线解析

路线的解析（无路点时沿地块寻路、传送必须分段）原本埋在
`BattleSimulator.__init__` 里。这里把它抽成 `route_plans()`，模拟器改为
调用它——**同一份实现**。这类"两处各算一遍"的账本，本项目已经吃过亏
（干员面板、术语量纲各一次），不能再来一次。

格子口径与模拟器一致：`cell = (round(x), round(y))`，即敌人占据**最近的
格心**。所以"到达某格"= 位置四舍五入落在该格，进入/离开各在路过格心前后
半格处。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from math import hypot, inf
from typing import Any, Callable, Iterable, Iterator

Cell = tuple[int, int]
Point = tuple[float, float]

__all__ = [
    "RoutePlan", "route_plans", "leading_wait", "polyline_length",
    "Visit", "EnemyArrival", "enemy_arrivals", "ArrivalIndex",
    "enemy_speed",
]


# ---------------------------------------------------------------- 路线解析

def leading_wait(route) -> float:
    """路线上**开头的**待命总秒数（WAIT_FOR_SECONDS）。

    关卡数据里 WAIT_FOR_SECONDS 是「入场后就地待命」，不是「走到某处再等」。
    SR-6 的 21 条路线全部只有一条 WAIT、没有任何 MOVE checkpoint，路径是从
    起点到终点的直线，所以待命必然发生在入场那一刻——3 秒或 10 秒。

    只累加**开头连续**的 WAIT：一旦出现 MOVE，后面的 WAIT 就是"走到那儿再等"，
    那属于路径中段，不是入场待命（SR-EX-8 有 60 秒的那种）。
    """
    total = 0.0
    for c in (getattr(route, "checkpoints", None) or []):
        if getattr(c, "type", None) != "WAIT_FOR_SECONDS":
            break
        total += float(getattr(c, "wait", 0.0) or 0.0)
    return total


def polyline_length(pts: Iterable[Point]) -> float:
    pts = list(pts)
    return sum(hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))


@dataclass
class RoutePlan:
    """一条路线的可执行形态：走点折线 + 分段计划 + 入场待命。"""

    index: int
    points: list[Point] = field(default_factory=list)
    legs: list[Any] = field(default_factory=list)
    wait: float = 0.0
    mode: str = "WALK"

    @property
    def has_legs(self) -> bool:
        return bool(self.legs)

    @property
    def length(self) -> float:
        """整条路线的**行走**总格数（不含待命与离场时间）。"""
        if self.legs:
            return sum(float(getattr(l, "length", 0.0) or 0.0)
                       for l in self.legs)
        return polyline_length(self.points)

    @property
    def fixed_seconds(self) -> float:
        """待命 + 离场的总秒数（不随移速缩放）。"""
        if self.legs:
            return sum(float(getattr(l, "seconds", 0.0) or 0.0)
                       for l in self.legs)
        return self.wait

    def duration(self, speed: float) -> float:
        """以 `speed` 格/秒走完全程要多久。"""
        if speed <= 0:
            return inf
        return self.length / speed + self.fixed_seconds

    def timeline_hint(self) -> str:
        if not self.legs:
            return f"{self.length:.1f}格 直行 + 待命{self.wait:g}s"
        parts = []
        for l in self.legs:
            k = getattr(l, "kind", "?")
            if k == "walk":
                parts.append(f"走{l.length:g}格")
            elif k == "vanish":
                parts.append(f"离场{l.seconds:g}s")
            else:
                parts.append(f"待命{l.seconds:g}s")
        return " → ".join(parts)


def route_plans(stage) -> dict[int, RoutePlan]:
    """把 `stage.routes` 解析成按 index 索引的 `RoutePlan`。

    **这是模拟器与本模块共用的唯一实现**，改动请只改这里。
    """
    out: dict[int, RoutePlan] = {}
    for r in stage.routes:
        pts = list(getattr(r, "path", None) or [])
        # 没有 MOVE 路点的路线不是直线，而是沿可行走地块绕行
        has_move = any(
            getattr(c, "is_move", False) or getattr(c, "is_appear", False)
            for c in (getattr(r, "checkpoints", None) or []))
        if not has_move and getattr(r, "mode", "WALK") == "WALK":
            walk = getattr(getattr(stage, "map", None), "ground_path", None)
            if walk is not None:
                pts = walk(r.start, r.end)
        if not pts:
            pts = ([r.start]
                   + [c.position for c in r.checkpoints if c.position]
                   + [r.end])
        # 格心：格 (x, y) 的中心即 (x, y)（本项目坐标就是格坐标）
        points = [(float(p[0]), float(p[1])) for p in pts]
        wait = leading_wait(r)
        legs: list[Any] = []
        build = getattr(r, "legs", None)
        if build is not None:
            legs = list(build(walk_map=stage.map) or [])
        out[r.index] = RoutePlan(index=r.index, points=points, legs=legs,
                                 wait=wait, mode=str(getattr(r, "mode", "WALK")))
    return out


# ---------------------------------------------------------------- 速度

def enemy_speed(enemy_at: Callable[[str, int], Any], enemy_id: str, level: int,
                *, move_multiplier: float = 1.0,
                speed_scale: float = 1.0) -> float:
    """敌人实际推进速度（格/秒）。

    公式与模拟器同一口径：`moveSpeed × move_multiplier × speed_scale`。
    已用 1-7 实机录像校准过（怒潮凛冬单干员，模拟 142.0s vs 实机 140s，误差 1.4%）。

    **`move_speed` 为 0 时返回 0，不被兜底成 1**。移速 0 是"原地不动"的敌人
    （库里 23 页如此），把它当成 1 会让一个永不移动的敌人满地图跑。
    """
    stats = enemy_at(enemy_id, level)
    ms = getattr(stats, "move_speed", None)
    if ms is None:
        ms = 1.0
    return max(0.0, float(ms)) * float(move_multiplier) * float(speed_scale)


# ---------------------------------------------------------------- 到达表

@dataclass(frozen=True)
class Visit:
    """某只敌人占据某一格的时段。"""

    cell: Cell
    enter: float
    exit: float
    name: str = ""
    enemy_id: str = ""
    route: int = -1

    @property
    def dwell(self) -> float:
        return max(0.0, self.exit - self.enter)


@dataclass
class EnemyArrival:
    """一只敌人从入场到抵达终点（或离场）的全过程。"""

    enemy_id: str
    name: str
    level: int
    route: int
    spawn: float
    speed: float
    length: float
    visits: list[Visit] = field(default_factory=list)
    #: 走上场的那一刻（入场待命结束）
    starts_at: float = 0.0
    #: 抵达终点（= 漏怪时刻，前提是没人拦）
    arrives_at: float = inf
    #: 中途离场过（传送）
    vanished: bool = False

    @property
    def travel(self) -> float:
        return self.arrives_at - self.spawn


def _walk_visits(pts: list[Point], t0: float, speed: float, *, name: str,
                 enemy_id: str, route: int, appear: bool) -> tuple[list[Visit], float]:
    """沿折线走，产出每一格的占据时段。返回 (visits, 结束时刻)。"""
    out: list[Visit] = []
    if len(pts) < 2:
        return out, t0
    cum = 0.0
    for i, p in enumerate(pts):
        if i == 0:
            # 起点也要算一格：敌人**在出生点待过半格时间**，站在出生点旁边
            # 的干员是真的能打到它的。早先这里直接 continue，热度图上出生点
            # 那格恒为 0，看着像"没人经过"。
            seg = hypot(pts[1][0] - p[0], pts[1][1] - p[1]) or 1.0
            half = 0.5 * seg / speed if speed > 0 else 0.0
            cell = (int(round(p[0])), int(round(p[1])))
            # 起点/传送落点都从 t0 开始算：**t0 之前它不在场上**。
            # 后一格从 t0+半格开始接管，两段首尾相接。
            out.append(Visit(cell, t0, t0 + half, name, enemy_id, route))
            continue
        seg = hypot(p[0] - pts[i - 1][0], p[1] - pts[i - 1][1])
        cum += seg
        if speed <= 0:
            continue
        tv = t0 + cum / speed
        # `cell = round(position)`：路过格心前后各半格都算占着这一格
        half = 0.5 * seg / speed
        cell = (int(round(p[0])), int(round(p[1])))
        out.append(Visit(cell, tv - half, tv + half, name, enemy_id, route))
    return out, t0 + (cum / speed if speed > 0 else inf)


def enemy_arrivals(stage, enemy_at: Callable[[str, int], Any], *,
                   speed_scale: float = 1.0,
                   plans: dict[int, RoutePlan] | None = None,
                   ) -> list[EnemyArrival]:
    """按 `stage.timeline()` 把每只敌人的到达时刻全算出来。

    `speed_scale` 是给"敌速未知量扫描"用的：整关敌人一起加速/减速。
    缺省的 1.0 就是关卡数据本身的值。
    """
    plans = plans if plans is not None else route_plans(stage)
    mul = float(getattr(stage.options, "move_multiplier", 1.0) or 1.0)
    out: list[EnemyArrival] = []
    for item in stage.timeline():
        spawn_t, enemy_id, level, route_index = _unpack_spawn(item)
        plan = plans.get(route_index)
        if plan is None:
            continue
        stats = enemy_at(enemy_id, level)
        name = str(getattr(stats, "name", enemy_id) or enemy_id)
        ms = getattr(stats, "move_speed", None)
        speed = max(0.0, float(1.0 if ms is None else ms)) * mul * speed_scale

        visits: list[Visit] = []
        t = float(spawn_t)
        vanished = False
        if plan.has_legs:
            for leg in plan.legs:
                kind = getattr(leg, "kind", "walk")
                if kind == "walk":
                    pts = [tuple(map(float, p)) for p in (leg.points or ())]
                    vs, t = _walk_visits(pts, t, speed, name=name,
                                         enemy_id=enemy_id, route=route_index,
                                         appear=False)
                    visits.extend(vs)
                elif kind == "vanish":
                    vanished = True
                    t += float(getattr(leg, "seconds", 0.0) or 0.0)
                else:
                    secs = float(getattr(leg, "seconds", 0.0) or 0.0)
                    if visits:
                        last = visits[-1]
                        visits[-1] = Visit(last.cell, last.enter,
                                           last.exit + secs, name,
                                           enemy_id, route_index)
                    t += secs
            arrives = t
        else:
            starts = t + plan.wait
            pts = plan.points
            vs, arrives = _walk_visits(pts, starts, speed, name=name,
                                       enemy_id=enemy_id, route=route_index,
                                       appear=False)
            if plan.wait and vs:
                first = vs[0]
                vs[0] = Visit(first.cell, t, first.exit, name, enemy_id,
                              route_index)
            visits.extend(vs)

        # 离场过的话，"抵达终点"要按最后一段算——分段之后 t 已经是终点时刻
        out.append(EnemyArrival(
            enemy_id=enemy_id, name=name, level=level, route=route_index,
            spawn=float(spawn_t), speed=speed, length=plan.length,
            visits=visits, starts_at=float(spawn_t) + plan.wait,
            arrives_at=arrives if speed > 0 else inf, vanished=vanished))
    return out


def _unpack_spawn(item) -> tuple[float, str, int, int]:
    """`stage.timeline()` 的条目是 `(时刻, EnemySpawn)`。

    `EnemySpawn` 上才有 `enemy_id` / `level` / `route_index`；
    早先我按四元组解包，直接 IndexError。
    """
    t, s = item[0], item[1]
    return (float(t), str(s.enemy_id), int(getattr(s, "level", 0) or 0),
            int(s.route_index))


# ---------------------------------------------------------------- 查询索引

class ArrivalIndex:
    """按格反查"什么时候有敌人经过"，以及"在给定格集合里待了多少敌人·秒"。

    第二件事就是**落位价值的便宜上界**：一个干员的攻击格集合里敌人待的
    敌人·秒越多，它越可能值得放。这不需要跑模拟。
    """

    def __init__(self, arrivals: Iterable[EnemyArrival]) -> None:
        self.arrivals = list(arrivals)
        self._by_cell: dict[Cell, list[Visit]] = {}
        for a in self.arrivals:
            for v in a.visits:
                self._by_cell.setdefault(v.cell, []).append(v)
        for vs in self._by_cell.values():
            vs.sort(key=lambda v: v.enter)

    # -------------------------------------------------- 单格

    def cells(self) -> list[Cell]:
        return sorted(self._by_cell)

    def at(self, cell: Cell) -> list[Visit]:
        return list(self._by_cell.get(cell, ()))

    def first(self, cell: Cell) -> float | None:
        vs = self._by_cell.get(cell)
        return min(v.enter for v in vs) if vs else None

    # -------------------------------------------------- 格集合

    def visits(self, cells: Iterable[Cell]) -> list[Visit]:
        out: list[Visit] = []
        for c in cells:
            out.extend(self._by_cell.get(c, ()))
        out.sort(key=lambda v: v.enter)
        return out

    def names(self, cells: Iterable[Cell]) -> dict[str, int]:
        """每个敌人有**几次**会进入这片格子（同一只分两次经过算两次）。"""
        out: dict[str, int] = {}
        for v in self.visits(cells):
            out[v.name] = out.get(v.name, 0) + 1
        return out

    def dwell(self, cells: Iterable[Cell], t0: float = -inf,
              t1: float = inf) -> float:
        """这片格子上累计的**敌人·秒**（可加时间窗）。

        这就是"这个落位能接到多少活"的便宜度量。它只是上界——干员打不打得动、
        会不会被反杀，模拟器才知道——但用来**剪枝**足够：dwell 为零的落位
        连试都不必试。
        """
        total = 0.0
        for v in self.visits(cells):
            lo, hi = max(v.enter, t0), min(v.exit, t1)
            if hi > lo:
                total += hi - lo
        return total

    def count(self, cells: Iterable[Cell], t0: float = -inf,
              t1: float = inf) -> int:
        """有多少次"进入"落在这个时间窗里。"""
        return sum(1 for v in self.visits(cells)
                   if t0 <= v.enter <= t1)

    def busiest(self, top: int = 12) -> list[tuple[Cell, float]]:
        """按累计占据时长排出最忙的格子——摆位的第一手直觉。"""
        agg: dict[Cell, float] = {}
        for cell, vs in self._by_cell.items():
            agg[cell] = sum(v.dwell for v in vs)
        return sorted(agg.items(), key=lambda kv: -kv[1])[:top]

    def span(self) -> tuple[float, float]:
        if not self.arrivals:
            return (0.0, 0.0)
        return (min(a.spawn for a in self.arrivals),
                max(a.arrives_at for a in self.arrivals
                    if a.arrives_at != inf) if any(
                    a.arrives_at != inf for a in self.arrivals) else 0.0)
