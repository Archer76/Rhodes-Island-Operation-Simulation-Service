# -*- coding: utf-8 -*-
"""从 `battle/unit.py` **机械生成** `ak_tactic/frontend/operator_view.py`。

## 思路与 `gen_enemy_view.py` 一模一样

敌人那一侧能脱钩，是因为"造一个敌人"本质是"抄一组字段"。干员这一侧形状相同：
`verify.py::unit` 建一个 `kw` dict（35 键）再 `OperatorUnit(**kw)`，
而 `OperatorUnit` 是 **134 字段的 dataclass**——`kw` 没给的那些走**默认值**。

⇒ 视图 = `kw` ＋ **全部默认值** ＋ **四个现算的方法**。三样都从 AST 里取，
一个手打的字都没有：

| 来源 | 怎么取 |
|---|---|
| `kw` | 运行时由 `verify.py::unit` 给（调用方传进来） |
| 默认值 | `OperatorUnit` / `Combatant` 的 dataclass 字段右值，原样 `ast.unparse` |
| 方法 | `current_atk` / `current_defense` / `current_res` 的**函数体原文** |

⚠ `current_range_id` 不抄：它早就搬进 `frontend/geometry.py` 了，
视图里直接转调那一份（与 `battle/unit.py` 现在的写法一致）。

## 为什么值得这样搬

`OperatorUnit` 846 行里绝大多数是**跑帧**（位移、碰撞、技力、护盾、站场），
规格一行都不碰。手抄那 134 个默认值必然错几个，而错的症状是
"某个字段开局不是 0"——不报错、只在特定关卡上差一点。

跑法：`python tools\\gen_operator_view.py`（幂等）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ak_tactic" / "battle" / "unit.py"
DST = ROOT / "ak_tactic" / "frontend" / "operator_view.py"

#: 要原样抄进视图的方法（`current_range_id` 不在此列，它只转调 geometry）
METHODS = ["current_atk", "current_defense", "current_res"]

#: 也用原样抄：`effects` 在原版是 **property**，抄成 property 就**没有初始化顺序问题**
#: ——普通属性要在 `kw` 覆盖之后再算一遍，而 property 每读一次现算，天生一致。
PROPERTIES = ["effects"]

HEADER = '''# -*- coding: utf-8 -*-
"""一个干员的**规格视图**——`build_spec` 要的那组字段，不需要一个活的对象。

⚠ **本文件由 `tools/gen_operator_view.py` 从 `battle/unit.py` 机械生成，不要手改。**
改口径请改生成器再重跑，这样两边永远取的是同一段源码。

## 它是干什么的

`OperatorUnit` 是 **134 字段的 dataclass、846 行**——其中绝大多数是**跑帧**
（位移、碰撞、技力、护盾、站场），规格一行都不碰。

规格真正要的只有三样：

* `verify.py::unit` 建的那个 `kw`（35 键，来自 `OperatorCalculator` ＋ 天赋 ＋ 特性文本）
* `kw` 没给的那些字段的**默认值**（本文件照 `OperatorUnit` 的 dataclass 右值抄）
* 四个**现算**的量：`current_atk` / `current_defense` / `current_res` / `current_range_id`

⇒ 视图 = 这三样。`spec.py::_operator_spec` 是 `getattr` 式的读法，喂得饱。

## ⚠ 口径的边界

* `effects`（技能效果）在这里是**普通属性**，不是 property —— 因为 `kw` 里不带它，
  而规格取的是**开局态**（技能还没开、`skill_active` 为假、`effects` 为 None）。
  原版那个 property 的三行判断照抄在 `__init__` 里。
* `position` / `direction` 会被 `spec.py` **在读到之前改写**
  （`spec.py:687-688`：`op.position = d.position`），所以视图必须允许写。
* 跑帧才会变的那些字段（`hp` / `hits` / `sp` / 护盾…）**照抄默认值**——
  规格就在开局那一刻取，它们就该是那个值。
"""
from __future__ import annotations

from typing import Any

from .geometry import current_range_id as _current_range_id

__all__ = ["OperatorView", "operator_view"]


#: 下面这几行是 `OperatorUnit` 的**模块级常量**，由生成器按需带过来
#: （默认值表达式引用到它们，比如 `block_tol2 = POSITION_TOL * POSITION_TOL`）。
'''

CLASS_HEAD = '''

class OperatorView:
    """一个干员的规格视图。**字段名与 `OperatorUnit` 逐个相同。**"""

    def __init__(self, kw: dict[str, Any], **overrides: Any) -> None:
        # ---- `kw` 没给的那些：照 `OperatorUnit` / `Combatant` 的 dataclass 默认值
'''


def _default_expr(value: ast.AST) -> str | None:
    """把 dataclass 字段的右值翻成**视图里能直接跑**的表达式。

    ⚠ 原样抄会炸：dataclass 用 `field(default_factory=list)` 表达"每个实例一份
    空表"，而视图模块里根本没有 `field` 这个名字
    （第一次跑就 `NameError: name 'field' is not defined`）。

    翻译规则（只认这几种，遇到别的**如实报错**而不是猜）：

    | dataclass 写法 | 视图里 |
    |---|---|
    | `field(default_factory=X)` | `X()` |
    | `field(default=X)` | `X` |
    | `field(init=False, …)` | 跳过（不是构造参数，规格也不读） |
    | 其它 | 原样 |

    找不到可翻的形式时返回 `None`，由调用方**报错**——悄悄塞一个默认值进去，
    症状会是"某个字段开局不是它该有的值"，不报错、只在特定关卡差一点。
    """
    if isinstance(value, ast.Call) and getattr(value.func, "id", "") == "field":
        kw = {k.arg: k.value for k in value.keywords}
        if "init" in kw and isinstance(kw["init"], ast.Constant) \
                and kw["init"].value is False:
            return None
        if "default_factory" in kw:
            f = ast.unparse(kw["default_factory"])
            return "%s()" % f
        if "default" in kw:
            return ast.unparse(kw["default"])
        raise SystemExit("认不出的 field(...) 形式：%s" % ast.unparse(value))
    return ast.unparse(value)


def _defaults(cls_name: str, src: str, tree: ast.Module) -> list[tuple[str, str]]:
    """`(字段名, 默认值源码)`；`init=False` 的跳过。"""
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == cls_name:
            out = []
            for st in node.body:
                if (isinstance(st, ast.AnnAssign)
                        and isinstance(st.target, ast.Name) and st.value):
                    expr = _default_expr(st.value)
                    if expr is not None:
                        out.append((st.target.id, expr))
            return out
    raise SystemExit("找不到类 %s" % cls_name)


def _method_src(name: str, src: str, tree: ast.Module) -> str:
    """原样取一个方法（含装饰器）的源码，**并把首行缩进补回来**。

    ⚠ `ast.get_source_segment` 从 `col_offset` 开始切，而 `col_offset` 指向
    `def` 那个字符——**首行的 4 个空格不在段里**，后面几行的缩进却在。
    直接拼进类体会得到 `def current_atk` 落在第 0 列，
    生成的文件 `SyntaxError`（第一次生成就撞上了）。
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            seg = ast.get_source_segment(src, node)
            if seg is None:
                raise SystemExit("取不到 %s 的源码" % name)
            first, _, rest = seg.partition("\n")
            body = "    " + first + ("\n" + rest if rest else "")
            decs = "".join("    @%s\n" % ast.unparse(d)
                           for d in node.decorator_list)
            return decs + body
    raise SystemExit("找不到方法 %s" % name)


FOOTER = '''

    def current_range_id(self):
        """开技能期间被改写的攻击范围代号，没有就是 None。

        ⚠ 转调 `frontend/geometry.py`——与 `battle/unit.py` 现在的写法一致，
        实现只有那一份。
        """
        return _current_range_id(self.skill, self.skill_active)


def operator_view(kw: dict[str, Any], **overrides: Any) -> OperatorView:
    """`verify.py::unit` 那个 `kw` → 规格视图。"""
    return OperatorView(kw, **overrides)
'''


def _module_consts(names: set[str], src: str, tree: ast.Module) -> list[tuple[str, str]]:
    """默认值表达式里引用到的**模块级常量**，从 `unit.py` 原样带过来。

    ⚠ 抄默认值就必须连它引用的常量一起抄：`block_tol2 = POSITION_TOL * POSITION_TOL`
    原样搬过去会 `NameError`（第二次跑撞上的就是这个）。
    只带真正用到的那些——把 `unit.py` 的模块顶层整段搬过来会牵出一片无关的导入。
    """
    out: list[tuple[str, str]] = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name) \
                and node.targets[0].id in names:
            out.append((node.targets[0].id, ast.unparse(node.value)))
    return out


def _names_in(exprs: list[str]) -> set[str]:
    """表达式串里出现的**裸名字**（排除属性名与关键字参数名）。"""
    found: set[str] = set()
    for e in exprs:
        try:
            node = ast.parse(e, mode="eval")
        except SyntaxError:
            continue
        for sub in ast.walk(node):
            if isinstance(sub, ast.Name):
                found.add(sub.id)
    return found


def build() -> str:
    src = SRC.read_text(encoding="utf-8")
    tree = ast.parse(src)

    parts = [HEADER]
    #: ⚠ `Combatant` 是基类，它的字段（hp / max_hp / alive …）在子类里不再声明，
    #: 所以**两份都要**，且基类在前（子类同名覆盖）。
    pairs: list[tuple[str, str]] = []
    for cls in ("Combatant", "OperatorUnit"):
        pairs.extend(_defaults(cls, src, tree))

    consts = _module_consts(_names_in([e for _n, e in pairs]), src, tree)
    if consts:
        parts.append("\n")
        for name, expr in consts:
            parts.append("%s = %s\n" % (name, expr))
    else:
        parts.append("\n")

    parts.append(CLASS_HEAD)
    for name, expr in pairs:
        parts.append("        self.%s = %s\n" % (name, expr))
    parts.append("""
        # ---- `kw` 覆盖默认值（`kw` 是权威：来自 `OperatorCalculator`）
        for _k, _v in kw.items():
            setattr(self, _k, _v)
        # ---- 调用方显式给的（`position` / `direction` 这类）
        for _k, _v in overrides.items():
            setattr(self, _k, _v)
""")
    for name in PROPERTIES + METHODS:
        parts.append("\n")
        parts.append(_method_src(name, src, tree))
        parts.append("\n")
    parts.append(FOOTER)
    return "".join(parts)


def main() -> int:
    text = build()
    old = DST.read_text(encoding="utf-8") if DST.exists() else None
    if old == text:
        print("与现有文件一致，未改动")
        return 0
    DST.write_text(text, encoding="utf-8")
    print("已写入 %s（%d 行）" % (DST, len(text.splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
