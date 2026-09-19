# -*- coding: utf-8 -*-
"""把 `build_spec(SpecInputs.from_sim(sim), ...)` 的调用点改成 `build_spec(SpecInputs.from_sim(sim), ...)`。

## 为什么不做"函数内部兜底"

`build_spec` 现在收的是 `SpecInputs`（一份数据），而调用方手里还攥着一台活模拟器。
最省事的写法是在 `build_spec` 开头加一句

    if not isinstance(inp, SpecInputs):
        inp = SpecInputs.from_sim(inp)

**但那正是本项目反复踩的那类坑**：它把"还有多少地方在依赖活模拟器"这件事
藏进函数体里，谁都看不见。而"彻底摘除 battle/"这件事的全部难点就在于
**把剩余依赖数清楚**。

⇒ 改成在**每一处调用点**显式写 `SpecInputs.from_sim(sim)`。
欠账于是变成可 grep 的：`grep -c "from_sim" ` 就是剩余量。

## 自校验

改完用 AST 复查：**每一个** `build_spec(...)` 调用的第一个实参，
必须是 `SpecInputs.from_sim(...)` 这种调用（或在测试里显式构造的 `SpecInputs`）。
发现漏网的直接报错退出 —— 这类工具最容易"改了一半就说成功"。

跑法：`python tools\\wrap_spec_inputs.py [--apply]`
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
SKIP_DIRS = {".git", "__pycache__", ".venv", "node_modules", "out", "data"}

IMPORT_LINE = "from ak_tactic.frontend.inputs import SpecInputs"
#: ⚠ 这道 `(?<!def )` 是踩出来的：第一版把**函数定义**
#: `def build_spec(inp, *, ...)` 也当成调用点，改成了
#: `def build_spec(SpecInputs.from_sim(inp), ...)` —— 直接把 spec.py 写坏。
#: 它顺带还改了自己的 docstring。所以：定义不碰、本文件不碰。
PATTERN = re.compile(r"(?<!def )build_spec\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")
SELF = Path(__file__).resolve()


def py_files() -> list[Path]:
    return [p for p in ROOT.rglob("*.py")
            if not any(part in SKIP_DIRS for part in p.parts)]


def main() -> int:
    apply = "--apply" in sys.argv
    changed: list[tuple[Path, int, str, str]] = []
    for path in py_files():
        src = path.read_text(encoding="utf-8")
        if "build_spec(" not in src:
            continue
        out_lines = []
        touched = False
        for i, line in enumerate(src.splitlines(keepends=True), 1):
            m = PATTERN.search(line)
            if m:
                arg = m.group(1)
                if arg == "SpecInputs":                 # 已经是新写法
                    out_lines.append(line)
                    continue
                new = line[:m.start(1)] + (
                    "SpecInputs.from_sim(%s)" % arg) + line[m.end(1):]
                changed.append((path, i, line.strip(), new.strip()))
                out_lines.append(new)
                touched = True
            else:
                out_lines.append(line)
        if touched and apply:
            text = "".join(out_lines)
            if IMPORT_LINE not in text:
                #: 插到最后一个顶层 import 之后；没有 import 就放最前
                lines = text.splitlines(keepends=True)
                last = 0
                for i, l in enumerate(lines[:80]):
                    if re.match(r"^(import|from)\s", l):
                        last = i + 1
                lines.insert(last, IMPORT_LINE + "\n")
                text = "".join(lines)
            path.write_text(text, encoding="utf-8")

    rel = lambda p: str(p.relative_to(ROOT)).replace("\\", "/")
    print("共 %d 处调用点：" % len(changed))
    for path, lineno, old, new in changed:
        print("  %s:%d" % (rel(path), lineno))
        print("      - %s" % old[:96])
        print("      + %s" % new[:96])
    if not apply:
        print("\n（只列不改。加 --apply 落盘。）")
        return 0

    #: ⚠ 事后自校验：还有没有"第一个实参不是 SpecInputs"的 build_spec 调用
    bad = []
    for path in py_files():
        src = path.read_text(encoding="utf-8")
        if "build_spec(" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            bad.append("%s 语法坏了：%s" % (rel(path), exc))
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                    and node.func.id == "build_spec" and node.args:
                a = node.args[0]
                ok = (isinstance(a, ast.Call) and isinstance(a.func, ast.Attribute)
                      and a.func.attr == "from_sim")
                if not ok:
                    bad.append("%s:%d 第一个实参不是 from_sim：%s"
                               % (rel(path), node.lineno,
                                  ast.unparse(a)[:60]))
    if bad:
        print("\n❌ 自校验发现 %d 处漏网：" % len(bad))
        for b in bad:
            print("   %s" % b)
        return 1
    print("\n✅ 自校验：全仓 %d 处 build_spec 调用，第一个实参都是 from_sim" % len(changed))
    return 0


if __name__ == "__main__":
    sys.exit(main())
