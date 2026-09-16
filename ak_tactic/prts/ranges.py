"""攻击范围代号的取数与缓存。

`精英0范围=3-1` 只是个代号，真正的网格在 `Widget:Range/3-1` 页面里。
这个模块负责按代号取回来、解析成 `AttackRange`，并把结果另存一份，
这样重复查询不会反复走 wikitext 解析。
"""

from __future__ import annotations

import json
from pathlib import Path

from .client import PrtsClient, default_client
from .grid import AttackRange, parse_svg

#: 代号一共没多少种，全表拉下来也就几百 KB。
RANGE_INDEX = Path(__file__).resolve().parents[2] / "data" / "ranges.json"


class RangeRegistry:
    """代号 → AttackRange。内存 + 磁盘两级缓存。"""

    def __init__(self, client: PrtsClient | None = None,
                 index_path: Path | str | None = None) -> None:
        self.client = client or default_client()
        self.index_path = Path(index_path) if index_path else RANGE_INDEX
        self._mem: dict[str, AttackRange] = {}
        self._load()

    # ------------------------------------------------------------ 磁盘

    def _load(self) -> None:
        if not self.index_path.exists():
            return
        try:
            raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for code, d in raw.items():
            self._mem[code] = AttackRange(
                code=code,
                cols=d["cols"],
                rows=d["rows"],
                self_cell=tuple(d["self_cell"]),
                cells=frozenset(tuple(c) for c in d["cells"]),
            )

    def save(self) -> None:
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            code: {"cols": r.cols, "rows": r.rows,
                   "self_cell": list(r.self_cell),
                   "cells": sorted([list(c) for c in r.cells])}
            for code, r in self._mem.items()
        }
        self.index_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

    # ------------------------------------------------------------ 查询

    def get(self, code: str, *, use_cache: bool | None = None) -> AttackRange:
        code = code.strip()
        if code in self._mem and use_cache is not False:
            return self._mem[code]
        wt = self.client.wikitext(f"Widget:Range/{code}", use_cache=use_cache)
        rng = parse_svg(code, wt)
        self._mem[code] = rng
        return rng

    def get_many(self, codes: list[str]) -> dict[str, AttackRange]:
        out: dict[str, AttackRange] = {}
        for code in codes:
            if code:
                out[code] = self.get(code)
        return out

    def for_operator(self, operator, *, use_cache: bool | None = None) -> dict[str, AttackRange]:
        """`{elite0: AttackRange, elite1: …}`"""
        return {slot: self.get(code, use_cache=use_cache)
                for slot, code in operator.range_codes.items()}

    def known(self) -> list[str]:
        return sorted(self._mem)


def fetch_range(code: str, *, client: PrtsClient | None = None,
                use_cache: bool | None = None) -> AttackRange:
    """取单个攻击范围（便捷函数，不落磁盘索引）。"""
    c = client or default_client()
    return parse_svg(code, c.wikitext(f"Widget:Range/{code}", use_cache=use_cache))
