"""攻击范围。

prts.wiki 的 ``Widget:Range/<代号>`` 给的是**朝右**时的相对坐标集合（自身站位格为
``(0,0)``，其余是攻击覆盖格）。所以换朝向就是把这组坐标转一下：

===========  ==================
朝向          变换
===========  ==================
Right        ``(x, y)``
Left         ``(-x, y)``
Up           ``(-y, x)``
Down         ``(y, -x)``
===========  ==================

以「前方三格」``{(0,0), (1,0), (2,0)}`` 为例：朝上得 ``{(0,0), (0,1), (0,2)}``，
朝左得 ``{(0,0), (-1,0), (-2,0)}``——都对。

干员当前的 ``rangeId`` 就在 `character_table` 的 ``phases[].rangeId`` 里，
按精英阶段不同而不同（如「1-1」→「1-2」→「1-3」），所以取范围要连阶段一起看。
"""

from __future__ import annotations

__all__ = [
    "rotate_cells", "footprint", "normalize_direction",
    "normalize_cells", "RangeProvider",
]

Cell = tuple[int, int]


def normalize_direction(direction: str) -> str:
    """把各种写法（right / R / 右）收敛成四个标准朝向。"""
    d = (direction or "Right").strip().lower()
    table = {
        "right": "Right", "r": "Right", "右": "Right",
        "left": "Left", "l": "Left", "左": "Left",
        "up": "Up", "u": "Up", "上": "Up",
        "down": "Down", "d": "Down", "下": "Down",
    }
    if d not in table:
        raise ValueError(f"认不出的朝向：{direction}")
    return table[d]


def normalize_cells(cells, self_cell) -> set[Cell]:
    """把 prts.wiki 给的格集合平移到「自身格 = (0,0)」。

    **这一步不能省**：prts.wiki 的 ``self_cell``（蓝色实心那一个）不总在原点——
    ``3-6`` 是 ``(0,1)``、``x-1`` 是 ``(2,2)``。直接用原始格集合去旋转，
    范围会整体偏掉好几格，症状是「站对了格子却打不到人」。
    """
    sx, sy = self_cell
    return {(x - sx, y - sy) for x, y in cells}


def rotate_cells(cells, direction: str) -> set[Cell]:
    """把朝右的范围格旋转到指定朝向。

    屏幕坐标系（MAA 标准）是 x 向右、**y 向下**，所以这里的旋转公式与
    "数学课上那套"差一个符号：``Up`` 对应的是屏幕上的逆时针 90°，
    即 ``(x, y) → (y, -x)``。

    四个朝向放在一起看更清楚（基准是朝右）：

    ========  ================
    朝向      相对格
    ========  ================
    Right     ``(x, y)``
    Up        ``(y, -x)``     ← 屏幕上往上
    Left      ``(-x, -y)``
    Down      ``(-y, x)``     ← 屏幕上往下
    ========  ================
    """
    d = normalize_direction(direction)
    out: set[Cell] = set()
    for x, y in cells:
        if d == "Right":
            out.add((x, y))
        elif d == "Up":
            out.add((y, -x))
        elif d == "Left":
            out.add((-x, -y))
        else:                       # Down
            out.add((-y, x))
    return out


def footprint(cells, direction: str, origin: Cell) -> set[Cell]:
    """范围的绝对格集合——把相对格平移到 `origin`（干员所在格）。"""
    ox, oy = origin
    return {(ox + x, oy + y) for x, y in rotate_cells(cells, direction)}


class RangeProvider:
    """把「干员 + 精英阶段 + 朝向 + 位置」换算成实际的攻击格集合。

    :param registry: `ak_tactic.prts.RangeRegistry`，也可以是任何提供 `get(code)` 的对象
    :param range_id_of: `(char_id, elite) -> rangeId`，通常取自
        `character_table.phases[elite].rangeId`

    近战（``block_cnt > 0``）会**额外补上自身格**：prts.wiki 的格集合只标攻击覆盖格，
    而 ``1-1`` 这类近战范围只有 ``[(1,0)]``、不含自身格——但近战必须能打自己
    挡住的敌人，否则模拟器里会出现「挡住了却打不到」的怪象。
    """

    def __init__(self, registry, range_id_of, *, block_of=None):
        self.registry = registry
        self.range_id_of = range_id_of
        self.block_of = block_of
        self._cache: dict[str, set[Cell]] = {}
        self.missing: set[str] = set()

    def _cells(self, code: str) -> set[Cell] | None:
        if code in self._cache:
            return self._cache[code]
        try:
            r = self.registry.get(code)
        except Exception:
            self.missing.add(code)
            return None
        cells = normalize_cells(r.cells, r.self_cell)
        self._cache[code] = cells
        return cells

    def __call__(self, char_id: str, elite: int, direction: str,
                 position: Cell, *, range_id: str | None = None) -> set[Cell]:
        """算出攻击格集合。

        :param range_id: 覆盖代号。技能期间攻击范围被改写时传技能给的那个
            （`SkillLevel.range_id`），为 None 才按精英阶段查干员自己的范围。
        """
        code = range_id or self.range_id_of(char_id, elite)
        cells = self._cells(code)
        if cells is None:
            fx, fy = {"Right": (1, 0), "Left": (-1, 0),
                      "Up": (0, -1), "Down": (0, 1)}[normalize_direction(direction)]
            ox, oy = position
            return {(ox, oy)} | {(ox + fx * i, oy + fy * i) for i in (1, 2, 3)}
        if self.block_of is not None and self.block_of(char_id, elite) > 0:
            cells = cells | {(0, 0)}
        return footprint(cells, direction, position)
