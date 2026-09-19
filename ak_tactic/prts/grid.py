"""攻击范围：把 `Widget:Range/<代号>` 里的 SVG 还原成网格。

prts.wiki 把每个攻击范围画成一张 SVG。格子是两种语义，但**站位格有两种画法**：

* **`#1`** —— 蓝色实心 `rect`，**干员站位格**（★）——**画法 A**；
* **`#2`** —— 灰色描边 `rect`，**攻击覆盖格**（●）；
* ★ **画法 B（2026-09-20 补）**：站位格**不用 `#1`**，而是**内联画成一条蓝色
  `<path fill:#27a6f3>`**，位置由 `transform="translate(x,y)"` 给出——
  这些页的 `<defs>` 里**只定义 `#2`，`#1` 压根不存在**。

## 两套画法都要认（否则 9 个范围代号永远取不到）

2026-09-20 对全部 73 个代号逐页普查（**不是抽样**）：

* **画法 A** —— **63 个**；原解析器**只认这一种**；
* **画法 B** —— **9 个**：`1-5` `2-7` `3-16` `4-3` `4-4` `4-5` `4-6` `4-7` `4-13`。
  它们原先必然报「期望恰好 1 个站位格，实得 0」，**被误读成"prts 上没有"**。

两套用的是**同一套格坐标**：画法 B 的 `translate` 的 y 取 `-1 / 25 / 51`，
步长正好 `CELL_STEP = 26`（`4-5` 是 `24.728024`，浮点抖动，四舍五入即 25）。
⇒ **不是"源上没有"，是同一样东西的两种画法。**

★ **判定信号是颜色，不是序号**：`fill:#27a6f3` = 站位格；`fill:none` + `stroke:gray` = 覆盖格。
**别再用 `#1` 当判据**——序号是画法 A 的偶然编号，颜色才是语义。

## 回退路径必须留痕

`AttackRange.self_source` 记下这一格**是从哪条路径取到的**（`use#1` / `path#27a6f3`）。
★ 没有它，将来"蓝 path 回退"在某页上**误命中**时，**查不出是哪一类**——
**放宽一条判据的同时，必须留下"它是靠哪一条通过的"。**

## 另一处：`<use>` 的属性之间可以没有空格

`4-13` 原文里有 `<use xlink:href="#2"x="28"y="54"id="use10" />`（**属性间无空格**）。
旧正则要求 `\\s+` ⇒ 该页**漏掉 5 个覆盖格**。
★ 它与上面那条**会耦合**：**只修站位格那一半，`4-13` 就会从"响亮的失败"变成
"成功的静默少 5 格"**——所以两半必须一起改。

坐标是 26px 步进的（格 22px + 间 4px），但描边格比实心格多 1px 的 stroke
补偿，所以锚点会在 1/2、27/28 这种相邻整数间抖动。用「除以步长再四舍五入」
就能把它们吸附到同一个格子上。

已用近卫三个基准校准过语义：`1-1` → 前方 1 格、`1-2` → 前方 1 格带上下、
`1-3` → 前方 2 格带上下，与游戏内一致。
输出一律是**相对自身站位格**的坐标：右为 +x（面朝方向），下为 +y。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Iterator

CELL_STEP = 26
SELF_RECT_ID = "1"
#: 站位格的**填充色**——跨两种画法都成立的判据。
SELF_FILL = "#27a6f3"

#: `self_source` 的取值：这一格是从哪条路径取到的。
SRC_USE = "use#1"
SRC_PATH = f"path{SELF_FILL}"

#: `<use …>` / `<path …>` 标签本身（属性间的空白**可有可无**，故不用一整条正则钉死顺序）。
_USE_TAG_RE = re.compile(r"<use\b([^>]*)>")
_PATH_TAG_RE = re.compile(r"<path\b([^>]*)>")
#: 标签内的属性：`名="值"`。`\s*` 允许 `x="28"y="54"` 这种无空格写法。
_ATTR_RE = re.compile(r'([A-Za-z_:][-A-Za-z0-9_:.]*)\s*=\s*"([^"]*)"')
_TRANSLATE_RE = re.compile(r"translate\(\s*(-?[\d.]+)\s*[,\s]\s*(-?[\d.]+)\s*\)")
_D_MOVE_RE = re.compile(r"M\s*(-?[\d.]+)\s*[,\s]\s*(-?[\d.]+)")


def _attrs(tag_inner: str) -> dict[str, str]:
    return dict(_ATTR_RE.findall(tag_inner))


def _iter_uses(svg: str) -> Iterator[tuple[str, int, int]]:
    """产出 `(href 去 # 的 id, x, y)`。

    ★ **容忍属性间无空格**（`<use xlink:href="#2"x="28"y="54"/>`）：旧正则在
    `4-13` 上漏掉 5 格，是"静默少算"的来源。缺 `x` 或 `y` 的标签跳过。
    """
    for m in _USE_TAG_RE.finditer(svg):
        a = _attrs(m.group(1))
        href = a.get("xlink:href") or a.get("href") or ""
        xs, ys = a.get("x"), a.get("y")
        if not href or xs is None or ys is None:
            continue
        try:
            yield href.lstrip("#"), int(float(xs)), int(float(ys))
        except ValueError:
            continue


def _self_cell_from_path(svg: str) -> tuple[int, int] | None:
    """画法 B：站位格是**内联的蓝色 `<path>`**，位置 = `translate(x,y)` + `d` 的首个起点。

    ★ 只在**颜色命中** `SELF_FILL` 时才算——**判据是颜色，不是 id 序号**。
    算出来的格坐标与画法 A 用**同一个** `round(值 / CELL_STEP)`，故两者可互换。
    """
    for m in _PATH_TAG_RE.finditer(svg):
        a = _attrs(m.group(1))
        if SELF_FILL not in a.get("style", "") and SELF_FILL not in a.get("fill", ""):
            continue
        d = a.get("d", "").strip()
        dm = _D_MOVE_RE.match(d)
        if not dm:
            continue
        tx = ty = 0.0
        tm = _TRANSLATE_RE.search(a.get("transform", ""))
        if tm:
            tx, ty = float(tm.group(1)), float(tm.group(2))
        lx, ly = float(dm.group(1)), float(dm.group(2))
        return (round((tx + lx) / CELL_STEP), round((ty + ly) / CELL_STEP))
    return None


class RangeParseError(ValueError):
    """SVG 结构不符合预期。"""


@dataclass(frozen=True)
class AttackRange:
    """一个攻击范围。

    `cells` 是相对干员站位格的坐标集合（不含站位格本身）。
    `self_cell` 是站位格在原始网格中的绝对格坐标（保留给需要对齐原图的场景）。
    """

    code: str
    cols: int
    rows: int
    self_cell: tuple[int, int]
    cells: frozenset[tuple[int, int]] = field(default_factory=frozenset)
    #: 站位格**是从哪条路径取到的**：`use#1`（画法 A）/ `path#27a6f3`（画法 B 回退）。
    #: ★ 放宽一条判据的同时，必须留下"**它是靠哪一条通过的**"——否则回退路径
    #: 在某页上误命中时，**查不出是哪一类**。
    self_source: str = "unknown"

    @property
    def is_fallback(self) -> bool:
        """站位格**是不是靠画法 B 的回退路径**取到的。

        ★ 只在**确知**走的是回退路径时为真。`self_source == "unknown"`
        （旧索引文件没记这一键）**返回 False**——**"不知道它怎么来的"与
        "知道它是回退来的"是两件事**，不许压成一个值。要区分请直接读
        `self_source`（`use#1` / `path#27a6f3` / `unknown` 三态）。
        """
        return self.self_source == SRC_PATH

    # ------------------------------------------------------------ 视图

    @property
    def size(self) -> int:
        return len(self.cells)

    def grid(self) -> list[list[str]]:
        """以自身格为原点画一张字符画，方便人眼核对。"""
        xs = [x for x, _ in self.cells] + [0]
        ys = [y for _, y in self.cells] + [0]
        lo_x, hi_x = min(xs), max(xs)
        lo_y, hi_y = min(ys), max(ys)
        out: list[list[str]] = []
        for y in range(lo_y, hi_y + 1):
            row = []
            for x in range(lo_x, hi_x + 1):
                if (x, y) == (0, 0):
                    row.append("★")
                elif (x, y) in self.cells:
                    row.append("●")
                else:
                    row.append("·")
            out.append(row)
        return out

    def draw(self) -> str:
        return "\n".join("".join(r) for r in self.grid())

    def covers(self, dx: int, dy: int) -> bool:
        """相对偏移 (dx, dy) 是否在攻击范围内。"""
        return (dx, dy) in self.cells

    def rotated(self, times: int) -> "AttackRange":
        """顺时针旋转 90° × times——干员朝上/下/左时用得到。"""
        times %= 4
        cells = set(self.cells)
        for _ in range(times):
            cells = {(y, -x) for x, y in cells}
        return AttackRange(self.code, self.cols, self.rows, self.self_cell,
                           frozenset(cells), self.self_source)

    def index_entry(self) -> dict:
        """落盘到 `ranges.json` 的那一份——**唯一的序列化出口**。

        ★ 别再在 `RangeRegistry.save()` 里另拼一份：2026-09-20 就是这么漏掉
        `self_source` 的（**同一个东西写了两处，只改了一处**），
        而它当时**不会报错**、只是那个字段静默消失。
        """
        return {
            "cols": self.cols,
            "rows": self.rows,
            "self_cell": list(self.self_cell),
            "cells": sorted([list(c) for c in self.cells]),
            "self_source": self.self_source,
        }

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "size": self.size,
            "cells": sorted([list(c) for c in self.cells]),
            "grid": ["".join(r) for r in self.grid()],
            # ★ 留痕：这一格的站位格是哪条路径取到的（画法 A / 画法 B 回退）。
            "self_source": self.self_source,
        }


def parse_svg(code: str, svg: str) -> AttackRange:
    """从 SVG 文本解析出攻击范围。

    站位格按**两条路径**取，先画法 A 后画法 B（见模块 docstring）：

    * A = `<use xlink:href="#1" …>`；
    * B = **内联的蓝色 `<path fill="#27a6f3">`**（这些页的 `<defs>` 里没有 `#1`）。

    ★ **两条都不命中时仍然抛错。** 回退路径**不许**退化成"什么都当站位格"——
    那只是把**一个漏判**换成**一批误判**。
    """
    uses = list(_iter_uses(svg))
    if not uses:
        raise RangeParseError(f"{code}: SVG 里没有找到 <use> 元素")

    raw: dict[tuple[int, int], str] = {}
    for rect_id, xs, ys in uses:
        pos = (round(xs / CELL_STEP), round(ys / CELL_STEP))
        # 同一格若被重复标注，站位格优先
        kind = "self" if rect_id == SELF_RECT_ID else "range"
        if raw.get(pos) == "self":
            continue
        raw[pos] = kind

    self_cells = [pos for pos, k in raw.items() if k == "self"]
    self_source = SRC_USE
    if not self_cells:
        fallback = _self_cell_from_path(svg)
        if fallback is None:
            raise RangeParseError(
                f"{code}: 找不到站位格——既没有 `#{SELF_RECT_ID}` 的 <use>，"
                f"也没有含 `{SELF_FILL}` 的内联 <path>")
        # ★ 也计入 `raw`：画法 A 的站位格本来就在 `raw` 里，
        #   这样 `cols`/`rows` 的口径**两条路径才一致**。
        raw.setdefault(fallback, "self")
        self_cells = [fallback]
        self_source = SRC_PATH
    if len(self_cells) != 1:
        raise RangeParseError(f"{code}: 期望恰好 1 个站位格，实得 {len(self_cells)}")
    self_cell = self_cells[0]

    cols = max(c for c, _ in raw) + 1
    rows = max(r for _, r in raw) + 1

    # 归一化：把绝对格坐标平移成「相对自身」的偏移
    ox, oy = self_cell
    cells = frozenset(
        (c - ox, r - oy) for (c, r), k in raw.items() if k == "range"
    )
    return AttackRange(code, cols, rows, self_cell, cells, self_source)


def merge_ranges(ranges: Iterable[AttackRange]) -> str:
    """把若干范围并排画出来（调试用）。"""
    blocks = [r.draw().splitlines() for r in ranges]
    height = max((len(b) for b in blocks), default=0)
    width = max((max((len(l) for l in b), default=0) for b in blocks), default=0)
    out: list[str] = []
    for b in blocks:
        padded = [line.ljust(width) for line in b] + [" " * width] * (height - len(b))
        out.append("\n".join(padded))
    return "\n\n".join(out)
