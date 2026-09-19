# -*- coding: utf-8 -*-
"""把 `battle/talents.py` 里那 13 个函数 + 11 个常量**删掉**，改成从新家 re-export。

## 为什么是"删掉"而不是"留着两份"

留着两份 = 两处定义，迟早走散（本项目已有先例：`PILE_MARK` 那张表
在 `sim.py` 与 `frontend/enemy_rules.py` 各写一遍的念头被打掉过一次）。
⇒ 定义只有一份，在新家；`talents.py` 只做转出。

## ⚠ 三件必须先确认的事

1. **这些名字在 `talents.py` 内部还有没有人用？** 有的话删了会 `NameError`。
   实测：**0 处**（脚本自己会再查一遍并把结果打出来）。
2. **删的是不是"连同前导注释"？** 是 —— 与生成器用**同一套行区间算法**，
   否则注释会留在原地变成孤零零的一段，读的人以为代码还在。
3. **导出的名字要与生成器里的清单完全一致**，多一个少一个都会在下一次
   全仓自检里以 `ImportError` 的形式炸出来。

跑法：`python tools\\move_talent_finders.py [--apply]`（不带参数只列不改）
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "ak_tactic" / "battle" / "talents.py"
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

#: 与 `gen_talent_finders.py` 里的清单**必须一致** —— 而且必须是**自动推出来的那两份**
#: （`AUTO_*`）。第一版这里用的是我手写的 `CONSTS`/`FUNCS`，漏了三个名字，
#: 结果 `spec.py` 在 `_team_auras_of` 里 `AttributeError`，17 份计划全红。
from tools.gen_talent_finders import AUTO_CONSTS, AUTO_FUNCS     # noqa: E402

CONSTS, FUNCS = list(AUTO_CONSTS), list(AUTO_FUNCS)

ANCHOR = "from ..operator.talent import Talent"
#: 锚点行号（运行时算）；用于判"引用在转出导入之前还是之后"
ANCHOR_LINE = 0


def _ranges(lines: list[str], tree: ast.Module, names: list[str]) -> list[tuple[int, int, str]]:
    """`(起始行, 结束行, 名字)`，1-based、含前导注释块。"""
    out = []
    for node in tree.body:
        name = None
        if isinstance(node, ast.FunctionDef):
            name = node.name
        elif isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            name = node.targets[0].id
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
        if name not in names:
            continue
        start = node.lineno
        while start > 1 and lines[start - 2].startswith("#"):
            start -= 1
        out.append((start, node.end_lineno or node.lineno, name))
    return out


def main() -> int:
    global ANCHOR_LINE
    apply = "--apply" in sys.argv
    lines = TARGET.read_text(encoding="utf-8").splitlines(keepends=True)
    tree = ast.parse("".join(lines))
    for i, line in enumerate(lines, 1):
        if line.startswith(ANCHOR):
            ANCHOR_LINE = i
            break
    if not ANCHOR_LINE:
        raise SystemExit("找不到锚点 %r" % ANCHOR)

    found = _ranges(lines, tree, CONSTS + FUNCS)
    have = {n for _a, _b, n in found}
    want = set(CONSTS) | set(FUNCS)
    missing = sorted(want - have)
    print("找到 %d 块（共 %d 个名字）" % (len(found), len(want)))
    for a, b, n in sorted(found):
        print("   %4d-%-4d %s" % (a, b, n))
    if missing:
        print("⚠ 这些名字没找到，**不能继续**：%s" % missing)
        return 1

    #: ① 内部还有没有别处引用（排除定义块自身）
    #
    #: ⚠ **必须走 AST**：第一版用正则扫行，把模块底下的 `__all__` 列表里那些
    #: **字符串**也算成了引用（`"ANGEL_BLESSING_TALENTS",` …），于是报出
    #: 十来个根本不存在的"别处引用"。字符串不是引用。
    doomed = set()
    for a, b, _n in found:
        doomed |= set(range(a, b + 1))
    leaked = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or node.lineno in doomed:
            continue
        if node.id in want:
            leaked.append((node.lineno, node.id, lines[node.lineno - 1].strip()[:70]))
    if leaked:
        #: ⚠ **引用了不等于会断**：转出导入插在文件顶部（第 60 行那个锚点之后），
        #: 所以**函数体里**的引用照样解析得到。真正会断的只有
        #: "在导入之前就地求值"的那种（模块级表达式）。
        #: 第一版把两类混在一起，差点为了一个安全的引用放弃整个搬运。
        before = [x for x in leaked if x[0] < ANCHOR_LINE]
        if before:
            print("⚠ 这些引用**在转出导入之前**就地求值，删掉会 NameError：")
            for i, x, l in before[:10]:
                print("   %4d %-24s %s" % (i, x, l))
            return 1
        print("ℹ 别处引用 %d 处，但都在**转出导入之后**（函数体里），"
              "导入能解析得到 —— 不阻断：" % len(leaked))
        for i, x, l in leaked[:6]:
            print("   %4d %-24s %s" % (i, x, l))
    print("✅ 没有「导入之前」的引用")

    if not apply:
        print("\n（只列不改。加 --apply 落盘。）")
        return 0

    #: ② 自下而上删
    for a, b, _n in sorted(found, reverse=True):
        del lines[a - 1:b]

    #: ③ 在锚点后面插入 re-export
    text = "".join(lines)
    names = sorted(want)
    block = ("\n#: ⚠ 下面这一批的**实现已经搬到 `ak_tactic/frontend/talent_finders.py`**\n"
             "#: （`tools/gen_talent_finders.py` 按行区间原样搬，连同论证用的注释）。\n"
             "#: 这里只做转出：一份定义、两个消费者（引擎与 `build_spec`）。\n"
             "#: 删掉下面这块的**定义**是有意的——两处各写一遍必然走散。\n"
             "from ..frontend.talent_finders import (                        # noqa: E402\n"
             + "".join("    %s,\n" % n for n in names) + ")\n")
    idx = text.index(ANCHOR)
    end = text.index("\n", idx) + 1
    text = text[:end] + block + text[end:]
    TARGET.write_text(text, encoding="utf-8")
    print("\n已改 %s（%d → %d 行）" % (TARGET, len("".join(lines).splitlines()),
                                   len(text.splitlines())))
    return 0


if __name__ == "__main__":
    sys.exit(main())
