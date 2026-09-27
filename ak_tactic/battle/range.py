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
    "FORTRESS_SUB_PROFESSION", "fortress_self_cell_of",
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


#: **要塞**的子职业代号。「攻击范围要不要补自身格」这条判据只认它。
FORTRESS_SUB_PROFESSION = "fortress"


def fortress_self_cell_of(calc):
    """造一个 ``self_cell_of(char_id, elite) -> bool``：**只有要塞**为真。

    这是「攻击范围要不要补上自身格 ``(0,0)``」的**唯一判据**，Python 侧所有调用方
    都必须走它（Go 侧是同一份判据：`rios-sim/operators.go` 的
    `operatorCoversSelfCell`）——两处各写一份迟早会漂，而漂的后果是
    「搜索用的范围」与「模拟器执行用的范围」不再是同一个集合。

    :param calc: `ak_tactic.operator.OperatorCalculator`，也可以是任何提供
        ``character(char_id) -> dict`` 的对象（读的就是 `character_table` 那份）

    **为什么不是「阻挡数 > 0」**（这是这条判据原来那版，是错的）：阻挡数刻画的是
    「能挡几个人」，与「攻击范围盖不盖自己脚下」是两件事，而且它**双向**都错——

    * 它把自身格发给了**所有近战**，只是其中大多数范围代号本来就含 ``(0,0)``
      （73 个里 64 个），**补了看不出来**，所以一直没暴露；
    * **攻城手**的阻挡数也是 1（> 0）⇒ 它还给攻城手**多补**了一格，与游戏行为相反。

    **为什么只有要塞**：

    * **要塞**（号角／火哨／灰毫）：prts.wiki 三位的页面都写着
      *※通常情况下，该干员的攻击范围为自身所在地块＋常规攻击范围组成的复合攻击范围*。
      「自身所在地块」在范围里，所以补。（注意：要塞是近战，敌人会被它挡在
      **面前一格**，并不会站到它脚下——所以这一格**不是**「打自己挡住的人」用的，
      阻挡数那条旧判据编出来的正是这个理由，它站不住。）
    * **攻城手**（提丰／早露／熔泉／埃拉托／铅踝／矩）：页面**没写**这一条，
      特性只有「优先攻击重量最重的敌人」；数据侧一致——``4-3``／``4-4`` 的
      ``grids`` 不含 ``(0,0)``。机制上也讲得通：**高台格上出现敌人只有一种情形，
      就是飞行敌人**，而**攻城手打不到飞过自己头顶的敌人**。
    """
    def self_cell_of(char_id: str, elite: int) -> bool:
        entry = calc.character(char_id) or {}
        return entry.get("subProfessionId") == FORTRESS_SUB_PROFESSION
    return self_cell_of


class RangeProvider:
    """把「干员 + 精英阶段 + 朝向 + 位置」换算成实际的攻击格集合。

    :param registry: `ak_tactic.prts.RangeRegistry`，也可以是任何提供 `get(code)` 的对象
    :param range_id_of: `(char_id, elite) -> rangeId`，通常取自
        `character_table.phases[elite].rangeId`
    :param self_cell_of: `(char_id, elite) -> bool`，**这一位的攻击范围要不要补上
        自身格 ``(0,0)``**。传 ``None`` 表示一例都不补。现成的判据是
        `fortress_self_cell_of`（只有**要塞**为真）——理由与「为什么不是阻挡数」
        都写在那里的 docstring 里，这里不重复。

    ⚠ 73 个范围代号里 64 个的 ``grids`` 本来就含 ``(0,0)``
    （``1-5``/``2-7``/``3-16``/``4-13``/``4-3``/``4-4``/``4-5``/``4-6``/``4-7``
    这 9 个不含），所以补格对绝大多数干员是**恒等**的，真正被改动的只有
    ``4-5``/``4-6``（要塞）与 ``4-3``/``4-4``（攻城手）这些。
    """

    def __init__(self, registry, range_id_of, *, self_cell_of=None):
        self.registry = registry
        self.range_id_of = range_id_of
        self.self_cell_of = self_cell_of
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
        if self.self_cell_of is not None and self.self_cell_of(char_id, elite):
            cells = cells | {(0, 0)}
        return footprint(cells, direction, position)
