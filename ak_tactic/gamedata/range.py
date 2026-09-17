"""攻击范围网格——取自游戏本体的 `excel/range_table.json`。

## 为什么不走 prts.wiki 了

原先范围是抓 prts.wiki 的 `Widget:Range/<代号>`（一张 SVG），再解析成格集合。**那条路今天
仍然通**——2026-09-17 实测 `Widget:Range/1-1` 返回 631 字符；被 WAF 挡住的是 `Template:` /
`Module:` 命名空间，不是 `Widget:`。所以换掉它的理由不是「抓不到」，而是三个纯代价：要联网、
请求得间隔 1.2 秒，而且 SVG 的 `self_cell`（蓝色实心格）**不总在原点**，得先平移到自身格
再旋转——`3-6` 是 `(0,1)`、`x-1` 是 `(2,2)`，踩过这个坑。

`excel/range_table.json` 是游戏自己的表，53 KB、73 个代号，结构就是答案：

```json
"x-1": {"id": "x-1", "direction": 1, "grids": [{"row": 0, "col": -2}, ...]}
```

**坐标约定**：`col` 是朝向轴（正 = 面朝方向），`row` 是侧向轴，**自身格
`(0,0)` 已经在 grids 里**（`1-1` 只有两格：自身 + 正前方一格）。所以相对格就是
`(x, y) = (col, row)`，与项目「朝右」的约定天然一致，**不需要平移，也不需要
补自身格**。

`direction` 全表 73 条都是 `1`，含义是"朝右"；朝向的旋转交给
`ak_tactic.battle.range.rotate_cells`。全表 73 个范围**纵向全部对称**
（`(row, col)` 与 `(-row, col)` 同时存在），所以 row 的正负方向不影响结果——
这也是本表不必纠结"row 向上还是向下"的原因。

## 用法

    table = RangeTable()
    table.cells("x-1")            # {(x, y)} 相对格，含自身格
    provider = RangeProvider(table, range_id_of)   # 直接当 registry 用

`RangeTable.get(code)` 返回的对象有 `.cells` 与 `.self_cell`（恒为 `(0, 0)`），
所以它能直接顶替 `RangeProvider` 要的那个 registry。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .source import GameDataSource, GamedataError

__all__ = ["RangeTable", "RangeGrid", "RANGE_TABLE_PATH"]

#: 表在仓库里的相对路径（`excel/` 只有 GitHub 镜像有）
RANGE_TABLE_PATH = "excel/range_table.json"

Cell = tuple[int, int]


@dataclass(frozen=True)
class RangeGrid:
    """一个攻击范围代号对应的格集合。

    字段名（`cells` / `self_cell`）刻意与 `prts.grid.AttackRange` 对齐，这样
    它能直接塞进 `RangeProvider`，不必为换数据源改模拟器。
    """

    code: str
    cells: frozenset[Cell]
    #: 本表里自身格恒为原点——prts.wiki 那套要平移，这里不用
    self_cell: Cell = (0, 0)

    @property
    def size(self) -> int:
        return len(self.cells)

    @property
    def cols(self) -> list[int]:
        return sorted({x for x, _ in self.cells})

    @property
    def rows(self) -> list[int]:
        return sorted({y for _, y in self.cells})

    def draw(self) -> str:
        """画成网格。y 向下为正（MAA 标准），所以顺序打印即所见。"""
        if not self.cells:
            return "(空)"
        xs, ys = self.cols, self.rows
        lines = []
        for y in ys:
            lines.append(" ".join("#" if (x, y) in self.cells else "."
                                  for x in xs))
        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {"code": self.code, "self_cell": list(self.self_cell),
                "cells": sorted([x, y] for x, y in self.cells)}


class RangeTable:
    """`excel/range_table.json` 的读取入口。

    :param source: 默认 `GameDataSource(base=GITHUB_BASE)`——`excel/` 只有
        GitHub 镜像有，ark-nights 不带。
    """

    def __init__(self, source: GameDataSource | None = None):
        from .source import GITHUB_BASE
        self.source = source or GameDataSource(base=GITHUB_BASE)
        self._table: dict[str, RangeGrid] | None = None

    def _load(self) -> dict[str, RangeGrid]:
        if self._table is not None:
            return self._table
        try:
            raw = self.source.fetch_json(RANGE_TABLE_PATH)
        except GamedataError as e:
            raise GamedataError(
                f"取不到 {RANGE_TABLE_PATH}。\n"
                f"  excel/ 目录只有 GitHub 镜像有，map.ark-nights.com 不带。\n  {e}") from e
        out: dict[str, RangeGrid] = {}
        for code, entry in (raw or {}).items():
            cells = frozenset(
                (int(g["col"]), int(g["row"]))
                for g in (entry.get("grids") or [])
                if "col" in g and "row" in g
            )
            out[code] = RangeGrid(code=code, cells=cells)
        self._table = out
        return out

    # ------------------------------------------------------------ 查询

    def known(self) -> list[str]:
        return sorted(self._load())

    def exists(self, code: str) -> bool:
        return code in self._load()

    def get(self, code: str) -> RangeGrid:
        """`RangeProvider` 要的 registry 接口就是这一个方法。"""
        table = self._load()
        if code not in table:
            raise GamedataError(
                f"range_table.json 里没有范围 {code!r}；"
                f"已知 {len(table)} 个，如 {', '.join(self.known()[:8])} …")
        return table[code]

    def cells(self, code: str) -> set[Cell]:
        """相对格集合（含自身格）。"""
        return set(self.get(code).cells)
