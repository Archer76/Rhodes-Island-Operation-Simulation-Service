# -*- coding: utf-8 -*-
"""把 `d.operator` 机械换成 `operator_of(d)`——**按 AST 定位，不碰文档串**。

## 为什么不用逐行正则

`skills.py:266` 的文档串里就写着 `d.operator.skill`（那是在**解释**口径）。
逐行替换会把它也改掉，读起来就变成"解释里写着一个不存在的写法"。
本项目已经吃过一次同类亏（正则扫行把文档串里的名字算进读数）。

⇒ 用 AST 找出**真正的 `Attribute` 节点**，按 `(行, 列)` 精确替换。

⚠ 替换前先列出每一处原文，**人肉核一遍再落盘**——这是"机械替换范围"
第三次出事之后定的规矩：目标看起来在范围内、其实不在。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

FILES = ["ak_tactic/simgo/spec.py", "ak_tactic/simgo/skills.py"]
OLD, NEW = "d.operator", "operator_of(d)"

apply = "--apply" in sys.argv


def sites(p: Path) -> list[tuple[int, int, int, str]]:
    src = p.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        #: `d.operator`：接收者是名为 d 的 Name
        if (isinstance(node, ast.Attribute) and node.attr == "operator"
                and isinstance(node.value, ast.Name) and node.value.id == "d"):
            out.append((node.value.lineno, node.value.col_offset,
                        node.end_col_offset, src.splitlines()[node.value.lineno - 1]))
    return out


def main() -> int:
    total = 0
    for rel in FILES:
        p = ROOT / rel
        found = sites(p)
        total += len(found)
        print("%s：%d 处" % (rel, len(found)))
        for ln, _c0, _c1, line in found:
            print("   %4d: %s" % (ln, line.strip()[:96]))
    print("合计 %d 处" % total)

    if not apply:
        print()
        print("（只列不改。加 --apply 落盘。）")
        return 0

    for rel in FILES:
        p = ROOT / rel
        lines = p.read_text(encoding="utf-8").splitlines(keepends=True)
        #: 从后往前改，避免前面变长之后列号失效
        for ln, c0, c1, _line in sorted(sites(p), reverse=True):
            row = lines[ln - 1]
            lines[ln - 1] = row[:c0] + NEW + row[c1:]
        p.write_text("".join(lines), encoding="utf-8")
        print("已改 %s" % rel)
    return 0


if __name__ == "__main__":
    sys.exit(main())
