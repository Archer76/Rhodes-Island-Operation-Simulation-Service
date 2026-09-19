# -*- coding: utf-8 -*-
"""从 `battle/talents.py` **按行区间原样搬**出 `frontend/talent_finders.py`。

## 搬哪一块

`spec.py` 只从 `talents` 用了四类东西：

| 类别 | 名字 |
|---|---|
| 数据常量 | `RHODES_NATION` / `LATERANO_NATION` / `STUDENT_TEAM` / `CLASS_AURA_TALENTS` |
| `find_*` | `find_angel_blessing` / `find_team_aura` / `find_blessing` / `find_medic_monument` / `find_regen` / `find_snow` |
| `is_*`（上面那六个的判据） | `is_angel_blessing` / `is_team_aura_talent` / `is_faction_aura_talent` / `is_blessing_talent` / `is_medic_monument_talent` / `is_regen_talent` / `is_snow_talent` |
| 指纹常量 | `ANGEL_BLESSING_TALENTS` / `REGEN_KEYS` / `TEAM_AURA_NAME` / `FACTION_AURA_NAME` / `MEDIC_MONUMENT_NAME` / `SNOW_KEYS` / `BLESSING_KEYS` |

闭包实测 **13 个函数、46 行，全部无 `self`、无引擎态**（`battle/talents.py` 共 1126 行）。
⇒ 值得整体搬，`battle/talents.py` 改成从新家 re-export。

## ⚠ 为什么按行区间抄、不重打

`talents.py` 的注释里记着**为什么这样认**（「只能按天赋名认、不能按键名认」那一大段）。
重打会把论证丢掉，只留下结论——而这份代码的价值一半在论证里。
按 `lineno..end_lineno` 原样切，**连同紧邻的前导注释块**一起带过来。

跑法：`python tools\\gen_talent_finders.py`（幂等）
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "ak_tactic" / "battle" / "talents.py"
DST = ROOT / "ak_tactic" / "frontend" / "talent_finders.py"

FUNCS = [
    "is_angel_blessing", "find_angel_blessing",
    "is_regen_talent", "find_regen",
    "is_team_aura_talent", "is_faction_aura_talent", "find_team_aura",
    "is_medic_monument_talent", "find_medic_monument",
    "is_snow_talent", "find_snow",
    "is_blessing_talent", "find_blessing",
]

CONSTS = [
    "SNOW_KEYS", "REGEN_KEYS", "CLASS_AURA_TALENTS", "RHODES_NATION",
    "ANGEL_BLESSING_TALENTS", "TEAM_AURA_NAME", "FACTION_AURA_NAME",
    "STUDENT_TEAM", "LATERANO_NATION", "MEDIC_MONUMENT_NAME", "BLESSING_KEYS",
]

#: ⚠ **上面两份手写清单被证明会漏**：第一版照着它们搬完之后，
#: `spec.py` 在 `_team_auras_of` 里调 `_t.find_class_aura` —— 那个名字不在单子上，
#: 于是 `AttributeError`，17 份计划全部 `spec_sha = None`。
#:
#: 漏的原因很蠢也很典型：上一步的"使用处扫描"我打印时写了 `[:6]`，
#: 后面还有四个没显示出来，我就照着前六个动手了。
#:
#: ⇒ 改成本函数：**从 `spec.py` 里真正的属性访问反推**，再在 `talents.py` 里
#:    做一次传递闭包（函数 → 它调用的函数 → 函数引用的模块级常量）。
#:    手写清单只作为"应当出现"的断言用，不再是唯一真相。
SPEC = ROOT / "ak_tactic" / "simgo" / "spec.py"
TALENTS = ROOT / "ak_tactic" / "battle" / "talents.py"
#: ⚠ 搬完之后那些名字**不在 `talents.py` 了**，只在 `frontend/talent_finders.py`。
#: 所以符号表要**两个家一起建**，否则这个生成器跑第二遍就自我失明
#: （实测：第一次搬完后再跑，它报"这些名字在 talents.py 里找不到"）。
MOVED = ROOT / "ak_tactic" / "frontend" / "talent_finders.py"
#: `spec.py` 里给 `talents` 起的别名（`from ..battle import talents as X`）
ALIASES = {"_t", "_talents"}


def _symbols(path: Path) -> tuple[dict[str, ast.AST], dict[str, ast.AST]]:
    """`(函数表, 常量表)`。文件不存在就返回两张空表。"""
    if not path.exists():
        return {}, {}
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs: dict[str, ast.AST] = {}
    consts: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts[t.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consts[node.target.id] = node
    return funcs, consts


def needed_names() -> tuple[list[str], list[str]]:
    """`([常量…], [函数…])` —— 由 `spec.py` 的用法与两个家的符号表共同决定。"""
    spec_tree = ast.parse(SPEC.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(spec_tree):
        #: 形态一：`_t.find_snow(...)`
        if (isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name)
                and node.value.id in ALIASES):
            roots.add(node.attr)
        #: 形态二：`getattr(_t, "find_damage_block", None)`
        #:
        #: ⚠ **第一版只认形态一**，于是 `find_damage_block` 没被搬走。
        #: 而 `spec.py:538` 那处写的是 `getattr(..., None)`：拿不到就返回 None，
        #: `_talent_dodge` 再吞掉异常返回 `(0.0, 0.0)` —— 于是 `plan-hs06` 的规格里
        #: **静默少了两把闪避**（`if talent_phys or talent_arts:` 不成立），
        #: `spec_sha` 变了而判决一模一样。金标准是唯一抓住它的东西。
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                and node.func.id == "getattr" and len(node.args) >= 2):
            tgt, key = node.args[0], node.args[1]
            if (isinstance(tgt, ast.Name) and tgt.id in ALIASES
                    and isinstance(key, ast.Constant)
                    and isinstance(key.value, str)):
                roots.add(key.value)

    #: 两个家：原件优先（还没搬的从原件取），已搬的从新家取
    f_old, c_old = _symbols(TALENTS)
    f_new, c_new = _symbols(MOVED)
    funcs = {**f_new, **f_old}
    consts = {**c_new, **c_old}

    #: 闭包：函数 → 被调函数
    want_f: set[str] = set()
    stack = [r for r in roots if r in funcs]
    while stack:
        name = stack.pop()
        if name in want_f:
            continue
        want_f.add(name)
        for sub in ast.walk(funcs[name]):
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name) \
                    and sub.func.id in funcs:
                stack.append(sub.func.id)

    #: 常量：根里直接点的 + 闭包里引用到的模块级名字
    want_c: set[str] = {r for r in roots if r in consts}
    for name in list(want_f):
        for sub in ast.walk(funcs[name]):
            if isinstance(sub, ast.Name) and sub.id in consts:
                want_c.add(sub.id)

    unknown = sorted(roots - want_f - want_c)
    if unknown:
        raise SystemExit("⚠ 这些名字在两个家里都找不到，搬不了：%s" % unknown)
    return sorted(want_c), sorted(want_f)


AUTO_CONSTS, AUTO_FUNCS = needed_names()

HEADER = '''# -*- coding: utf-8 -*-
"""天赋的**认法**——`find_*` 与它们的判据、指纹常量。

⚠ **本文件由 `tools/gen_talent_finders.py` 从 `battle/talents.py` 按行区间机械搬出，
不要手改。** 改口径请改原件再重跑，这样两边永远取的是同一段源码。

## 为什么单独一份

`build_spec` 只需要"这位干员身上有没有这条天赋"，不需要任何跑帧逻辑。
实测这块闭包是 **13 个函数、46 行，全部无 `self`、无引擎态**，
而 `battle/talents.py` 有 1126 行——规格只碰其中很小的一片。

`battle/talents.py` 仍然从**这里** re-export 同一批名字，所以引擎那边一行不用改，
一份实现、两个消费者。

## ⚠ 注释是搬过来的，别删

每一条 `is_*` 上面那一大段写着**为什么这样认**（例如「青色怒火」为什么只能按
天赋名认、不能按黑板键名认——它和技能自己的增益**完全同名**）。
重打代码很容易，重打论证不容易；这段文字是判据的一半。
"""
from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "AMMO_COVENANT_NAME", "ANGEL_BLESSING_TALENTS", "BLESSING_KEYS",
    "CLASS_AURA_TALENTS", "FACTION_AURA_NAME", "LATERANO_NATION",
    "LIMIT_DISPATCH_TALENTS", "MEDIC_MONUMENT_NAME", "REGEN_KEYS",
    "RHODES_NATION", "SNOW_KEYS", "STUDENT_TEAM", "TEAM_AURA_NAME",
    "find_ammo_covenant", "find_angel_blessing", "find_blessing",
    "find_class_aura", "find_limit_dispatch", "find_medic_monument",
    "find_regen", "find_snow", "find_team_aura",
    "is_ammo_covenant_talent", "is_angel_blessing", "is_blessing_talent",
    "is_class_aura_talent", "is_faction_aura_talent", "is_limit_dispatch",
    "is_medic_monument_talent", "is_regen_talent", "is_snow_talent",
    "is_team_aura_talent",
]


class Talent(Protocol):
    """只看得到这两个成员——`battle/talents.Talent` 满足它。"""

    name: str

    def has(self, *keys: str) -> bool: ...


'''


def _block(lines: list[str], node: ast.AST) -> str:
    """一个定义/常量**连同紧邻的前导注释块**（只在同缩进层级、中间无空行时）。"""
    start = node.lineno - 1
    while start > 0 and lines[start - 1].lstrip().startswith("#"):
        start -= 1
    end = node.end_lineno or node.lineno
    return "".join(lines[start:end]).rstrip() + "\n"


def main() -> int:
    #: 两个家都读：还没搬的在原件里，已搬的在新家里。
    old_lines = TALENTS.read_text(encoding="utf-8").splitlines(keepends=True)
    new_src = DST.read_text(encoding="utf-8") if DST.exists() else ""
    new_lines = new_src.splitlines(keepends=True)

    def index(lines: list[str]) -> dict[str, ast.AST]:
        tree = ast.parse("".join(lines))
        out: dict[str, ast.AST] = {}
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                out[node.name] = node
            elif isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        out[t.id] = node
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                        out[node.target.id] = node
        return out

    old_idx, new_idx = index(old_lines), index(new_lines)

    def take(name: str) -> str:
        """优先取**原件**（它是权威）；原件没有才取新家（说明已搬）。"""
        if name in old_idx:
            return _block(old_lines, old_idx[name])
        if name in new_idx:
            return _block(new_lines, new_idx[name])
        raise SystemExit("⚠ %s 两个家里都没有" % name)

    parts = [HEADER]
    parts.append("\n# " + "=" * 68)
    parts.append("\n# 指纹常量（`talents.py` 原样搬）\n")
    parts.append("# " + "=" * 68 + "\n\n")
    for name in AUTO_CONSTS:
        parts.append(take(name) + "\n")

    parts.append("\n# " + "=" * 68)
    parts.append("\n# 判据与查找器（`talents.py` 原样搬）\n")
    parts.append("# " + "=" * 68 + "\n\n")
    for name in AUTO_FUNCS:
        parts.append(take(name) + "\n")

    text = "".join(parts)
    if new_src == text:
        print("与现有文件一致，未改动")
        return 0
    DST.write_text(text, encoding="utf-8")
    print("已写入 %s（%d 行）" % (DST, len(text.splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
