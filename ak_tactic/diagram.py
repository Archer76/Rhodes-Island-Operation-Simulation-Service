# -*- coding: utf-8 -*-
"""阶段六的输出：地图摆位图与时间轴表格。

两者都是**给人看**的，所以只有一条设计原则：信息密度要让位给可读性。
坐标一律 MAA 口径（原点左上、y 向下），与打印顺序天然一致——**从上往下读
就是地图的上下**，不需要在脑子里翻。

* `placement_diagram()` —— 摆位图。干员编号落在自己那格，方向、时机、技能
  写进图例。可选叠上攻击覆盖（`.`）与路线热度。
* `route_heat()` —— 路线热度图。每格被多少条路线经过 / 敌人待了多久。
  搜索器的几何剪枝用的就是这张表。
* `timeline_table()` —— 时间轴表格。出怪、落地、开技能、漏怪、阵亡、结束
  按时刻排在一张表里，**敌人的预计到达时刻也列出来**（由 `ak_tactic.eta`
  算，与模拟器共用路线解析）。
"""
from __future__ import annotations

from typing import Any, Iterable, Sequence

from .eta import ArrivalIndex, enemy_arrivals, route_plans

__all__ = ["placement_diagram", "route_heat", "timeline_table", "battle_report"]

#: 方向 → 给人看的说法。地图上用字母，图例里说清楚
_DIR_WORD = {"Right": "朝右", "Left": "朝左", "Up": "朝上", "Down": "朝下"}
_DIR_LETTER = {"Right": "R", "Left": "L", "Up": "U", "Down": "D"}


def _index(stage, enemy_at=None) -> ArrivalIndex:
    if enemy_at is None:
        from .gamedata import EnemyLibrary
        enemy_at = EnemyLibrary().get
    return ArrivalIndex(enemy_arrivals(stage, enemy_at))


# ---------------------------------------------------------------- 摆位图

def placement_diagram(stage, plan=None, *, verdict=None, show_range: bool = True,
                      show_enemy: bool = False, index: ArrivalIndex | None = None,
                      enemy_at=None) -> str:
    """画摆位图：干员编号 + 方向，可选叠攻击覆盖与敌人路线。

    `plan` 给落位（未跑过也能画）；`verdict` 给实际落地时刻。两者都给时
    以 verdict 的实际时刻为准——那是模拟器真正用的时刻，可能与计划不同。
    """
    deploys: list[tuple[str, tuple[int, int], str, float | None]] = []
    if verdict is not None:
        for o in verdict.operators:
            deploys.append((o["name"], tuple(o["position"]),
                            o.get("direction", "?"), o.get("time")))
    if plan is not None:
        have = {d[0] for d in deploys}
        for d in plan.deploys:
            if d.operator in have:
                continue
            deploys.append((d.operator, (int(d.position[0]), int(d.position[1])),
                            d.direction, d.time))
    # 计划里没有、verdict 里有的已经收进去了；编号按落地时刻排，与时间轴一致
    deploys.sort(key=lambda x: (x[3] is None, x[3] if x[3] is not None else 0))

    overlay: dict[tuple[int, int], str] = {}
    if show_enemy:
        idx = index or _index(stage, enemy_at)
        for cell, _d in idx.busiest(999):
            if stage.map.tile(*cell).deployable:
                overlay[cell] = "·"

    cells: dict[int, tuple[int, int]] = {}
    for i, (_n, pos, _d, _t) in enumerate(deploys, 1):
        cells[i] = pos
        overlay[pos] = str(i)

    out = [stage.map.render(overlay=overlay)]
    out.append("")
    out.append("图例：")
    out.append(f"  地面可部署 {len(stage.map.melee_spots)} 格 / "
               f"高台可部署 {len(stage.map.ranged_spots)} 格"
               + ("   · = 有敌人经过的可部署格" if show_enemy else ""))
    if not deploys:
        out.append("  （还没有落位）")
    for i, (name, pos, direction, t) in enumerate(deploys, 1):
        when = "未派时刻" if t is None else f"{float(t):.1f}s 落地"
        out.append(f"  {i}  {name:<8} MAA[{pos[0]},{pos[1]}]  "
                   f"{_DIR_WORD.get(direction, direction)}  {when}")
    if show_range and plan is not None:
        out.append("")
        out.append(_range_summary(stage, plan))
    return "\n".join(out)


def _range_summary(stage, plan) -> str:
    """逐人列出攻击覆盖的格数（不画进地图，免得把图糊住）。"""
    from .verify import Verifier
    v = Verifier()
    lines = ["攻击覆盖（格数）："]
    for d in plan.deploys:
        cid = v._by_name(d.operator)
        if not cid:
            lines.append(f"  {d.operator}：查不到编号")
            continue
        entry = {"char_id": cid, "elite": 2, "level": 1}
        try:
            prov = v.range_provider(stage)
            cs = prov(cid, 2, d.direction,
                      (int(d.position[0]), int(d.position[1])))
        except Exception as exc:                          # noqa: BLE001
            lines.append(f"  {d.operator}：取范围失败（{exc}）")
            continue
        lines.append(f"  {d.operator:<8} {len(cs):>2} 格  "
                     f"{sorted(cs)[:12]}{' …' if len(cs) > 12 else ''}")
    return "\n".join(lines)


def route_heat(stage, *, index: ArrivalIndex | None = None,
               metric: str = "dwell", enemy_at=None) -> str:
    """路线热度图：`dwell` 看敌人待了多久，`routes` 看几条路线经过。

    这张表就是搜索器几何剪枝的依据——**摆位要先看它**，dwell 为 0 的格子
    再怎么试也是白试。
    """
    idx = index or _index(stage, enemy_at)
    if metric == "routes":
        counts: dict[tuple[int, int], int] = {}
        for p in route_plans(stage).values():
            for cell in _path_cells(p):
                counts[cell] = counts.get(cell, 0) + 1
        top = max(counts.values()) if counts else 1
        value = lambda c: counts.get(c, 0)                       # noqa: E731
        fmt = lambda v: str(v) if v else "."                     # noqa: E731
        head = f"每格被几条路线经过（最多 {top} 条）"
    else:
        dwell = {c: idx.dwell([c]) for c in idx.cells()}
        top = max(dwell.values()) if dwell else 1.0
        value = lambda c: dwell.get(c, 0.0)                      # noqa: E731
        fmt = lambda v: (str(min(9, int(round(v / top * 9))))     # noqa: E731
                         if v > 0 else ".")
        head = f"每格累计敌人·秒（最深 {top:.1f}，图上按 0–9 归一）"

    lines = [head]
    header = " " * 5 + "".join(str(x).rjust(2) for x in range(stage.map.width))
    lines.append(header)
    for y in range(stage.map.height):
        row = []
        for x in range(stage.map.width):
            if not stage.map.tile(x, y).walkable:
                row.append("##".rjust(2))
            else:
                row.append(fmt(value((x, y))).rjust(2))
        lines.append(f"y={y}  " + "".join(row))
    lines.append("  ## = 不可行走；. = 没有敌人经过")
    return "\n".join(lines)


def _path_cells(plan) -> list[tuple[int, int]]:
    out: list[tuple[int, int]] = []
    if plan.legs:
        for leg in plan.legs:
            if getattr(leg, "kind", "") == "walk":
                out.extend((int(round(p[0])), int(round(p[1])))
                           for p in (leg.points or ()))
    else:
        out.extend((int(round(p[0])), int(round(p[1]))) for p in plan.points)
    return out


# ---------------------------------------------------------------- 时间轴

def timeline_table(stage, plan=None, *, verdict=None, enemy_at=None,
                   show_arrival: bool = True,
                   from_eta: bool = True) -> str:
    """把所有事件按时刻排成一张表。

    行格式：`时刻 | 类别 | 谁 | 位置 | 说明`

    敌人的「预计到达终点」由 `ak_tactic.eta` 算出并单独成列——这是搜索器与
    摆位判断的依据（几点会压到防线），而模拟器里的实际漏怪时刻会另起一行
    作为对照。两者差在一帧以内即为自洽。
    """
    rows: list[tuple[float, str, str, str, str]] = []

    for t, sp in stage.timeline():
        route = f"路线{sp.route_index}"
        rows.append((float(t), "出怪", _enemy_name(stage, sp, enemy_at),
                     route, f"档 {sp.level}"))

    if verdict is not None:
        for o in verdict.operators:
            pos = tuple(o["position"])
            rows.append((float(o["time"]), "落地", o["name"],
                         f"[{pos[0]},{pos[1]}]",
                         f"{_DIR_WORD.get(o.get('direction'), '')} "
                         f"{o.get('elite', '')}精{o.get('level', '')}级"))
            if o.get("death_time", -1) > 0:
                rows.append((float(o["death_time"]), "阵亡", o["name"],
                             f"[{pos[0]},{pos[1]}]", "干员退场"))
        for t, name, cost in verdict.leak_events:
            rows.append((float(t), "漏怪", name, "→ 防守点",
                         f"−{cost} 生命"))
        rows.append((float(verdict.elapsed), "结束",
                     "胜利" if verdict.won else "失败", "",
                     f"{verdict.stars} 星  击杀 {verdict.kills}  "
                     f"漏 {verdict.leaks}"))

    if show_arrival and from_eta:
        try:
            idx = _index(stage, enemy_at)
        except Exception:                                 # noqa: BLE001
            idx = None
        if idx is not None:
            for a in idx.arrivals:
                if a.arrives_at == float("inf"):
                    continue
                note = f"路线{a.route}  {a.speed:.2f} 格/秒"
                if a.vanished:
                    note += "  中途传送"
                rows.append((float(a.arrives_at), "预估到终点", a.name, "防守点",
                             note))

    rows.sort(key=lambda r: (r[0], _KIND_ORDER.get(r[1], 9)))
    lines = [f"{'时刻':>8}  {'类别':<10} {'谁':<12} {'位置':<10} 说明"]
    lines.append("-" * 76)
    for t, kind, who, pos, note in rows:
        lines.append(f"{t:7.1f}s  {kind:<10} {who:<12} {pos:<10} {note}")
    lines.append("-" * 76)
    lines.append(f"共 {len(rows)} 条事件")
    if show_arrival and from_eta:
        n = sum(1 for r in rows if r[1] == "预估到终点")
        if n:
            lines.append(
                f"注：「预估到终点」的 {n} 行是**没有任何干员拦截时**的理论"
                f"到达时刻（由移速与路线解析式算出，与模拟器共源，误差 ≤1 帧）。"
                f"实战里被拦下的敌人不会走到终点——实际漏怪以上面的「漏怪」"
                f"行为准。这一列是摆位判断的依据：它告诉你敌人**几点会压到"
                f"防线**。")
    return "\n".join(lines)


_KIND_ORDER = {"落地": 0, "出怪": 1, "预估到终点": 2, "漏怪": 3, "阵亡": 4,
               "结束": 5}


def _enemy_name(stage, sp, enemy_at) -> str:
    if enemy_at is None:
        try:
            from .gamedata import EnemyLibrary
            enemy_at = EnemyLibrary().get
        except Exception:                                 # noqa: BLE001
            return sp.enemy_id
    try:
        return str(getattr(enemy_at(sp.enemy_id, sp.level), "name",
                           sp.enemy_id) or sp.enemy_id)
    except Exception:                                     # noqa: BLE001
        return sp.enemy_id


# ---------------------------------------------------------------- 合成

def battle_report(stage, plan=None, *, verdict=None, title: str = "",
                  route_metric: str = "dwell",
                  with_heat: bool = True, with_timeline: bool = True) -> str:
    """摆位图 + 时间轴 + 战报，合成一份可以贴出去的完整报告。"""
    parts: list[str] = []
    head = title or (getattr(plan, "title", "") if plan else "") or \
        (verdict.title if verdict else "") or stage.code or stage.level_id
    parts.append(f"# {head}")
    parts.append("")
    parts.append(f"关卡 {stage.level_id}（{stage.code}）  "
                 f"坐标口径 MAA（原点左上、y 向下）")
    parts.append(f"{stage.map.describe()}  生命 "
                 f"{stage.options.max_life_point}  初始费用 "
                 f"{stage.options.initial_cost:g}  人数上限 "
                 f"{stage.options.character_limit}")
    if verdict is not None:
        parts.append("")
        parts.append(verdict.line())
    parts.append("")
    parts.append("## 摆位")
    parts.append(placement_diagram(stage, plan, verdict=verdict,
                                  show_enemy=with_heat))
    if with_heat:
        parts.append("")
        parts.append("## 路线热度")
        parts.append(route_heat(stage, metric=route_metric))
    if with_timeline:
        parts.append("")
        parts.append("## 时间轴")
        parts.append(timeline_table(stage, plan, verdict=verdict))
    if verdict is not None:
        parts.append("")
        parts.append(verdict.report())
    return "\n".join(parts)
