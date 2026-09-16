"""攻击范围：把 `Widget:Range/<代号>` 里的 SVG 还原成网格。

PRTS 把每个攻击范围画成一张 SVG，格子只有两种：

* `#1` —— 蓝色实心，**干员站位格**（图中恰好一个，记作 ★）
* `#2` —— 灰色描边，**攻击覆盖格**（记作 ●）

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
from typing import Iterable

CELL_STEP = 26
SELF_RECT_ID = "1"

_USE_RE = re.compile(r'<use\s+xlink:href="#(\d+)"\s+x="(-?\d+)"\s+y="(-?\d+)"')


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
                           frozenset(cells))

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "size": self.size,
            "cells": sorted([list(c) for c in self.cells]),
            "grid": ["".join(r) for r in self.grid()],
        }


def parse_svg(code: str, svg: str) -> AttackRange:
    """从 SVG 文本解析出攻击范围。"""
    uses = _USE_RE.findall(svg)
    if not uses:
        raise RangeParseError(f"{code}: SVG 里没有找到 <use> 元素")

    raw: dict[tuple[int, int], str] = {}
    for rect_id, xs, ys in uses:
        col = round(int(xs) / CELL_STEP)
        row = round(int(ys) / CELL_STEP)
        # 同一格若被重复标注，站位格优先
        kind = "self" if rect_id == SELF_RECT_ID else "range"
        if raw.get((col, row)) == "self":
            continue
        raw[(col, row)] = kind

    self_cells = [pos for pos, k in raw.items() if k == "self"]
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
    return AttackRange(code, cols, rows, self_cell, cells)


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
