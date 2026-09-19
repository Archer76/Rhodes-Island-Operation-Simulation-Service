# -*- coding: utf-8 -*-
"""`spec.py` / `mech.py` 对**模拟器对象**的完整读取面——用 AST，只算真的读。

## 为什么需要它

`spec_deps.py` 量的是"从 `build_spec` 出发能走到 `battle/` 的**函数**"，
那一路已经归零。但还有另一种残留：**把 `sim` 当一个容器用**——
`sim.stage`、`sim.enemy_at`、`mech.port_reasons(sim)` 这类。
函数体一个都不进 `battle/`，可对象还是得有。

⇒ 要回答"删掉 `battle/` 还差什么"，就得把这张**属性名表**列全，
它同时就是将来那个 `SpecInputs` 的**字段清单**。

## ⚠ 为什么必须走 AST

第一版用正则扫行，结果把**文档串里的名字**也算了进去
（`py`、`_attach_skill`、`_build_enemy`… 全是从注释与文档串里捞的）。
本项目大量在注释里写 `sim.xxx` **解释**某个设计——正则分不清"解释"与"读"。
**不准确的测量比没有更糟**：它会让人以为还差 30 项，实际没那么多。

AST 只认 `ast.Attribute` 且接收者是那几个名字，一个不多一个不少。
两种接收者写法都抓：`sim.x` 与 `getattr(sim, "x", ...)`（后者是 `ast.Constant`）。

跑法：`python tools\spec_sim_surface.py [--files a.py,b.py]`
"""
from __future__ import annotations

import ast
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

DEFAULT = ["ak_tactic/simgo/spec.py", "ak_tactic/simgo/mech.py"]

#: 当作"模拟器对象"的变量名。`probe`/`src` 是历史写法（浅拷贝与别名）。
RECEIVERS = {"sim", "probe", "src"}


class Scan(ast.NodeVisitor):
    def __init__(self) -> None:
        self.direct: dict[str, list[int]] = defaultdict(list)
        self.getattr_: dict[str, list[int]] = defaultdict(list)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        v = node.value
        if isinstance(v, ast.Name) and v.id in RECEIVERS:
            self.direct[node.attr].append(node.lineno)
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        f = node.func
        if (isinstance(f, ast.Name) and f.id == "getattr" and node.args
                and isinstance(node.args[0], ast.Name)
                and node.args[0].id in RECEIVERS
                and len(node.args) >= 2 and isinstance(node.args[1], ast.Constant)
                and isinstance(node.args[1].value, str)):
            self.getattr_[node.args[1].value].append(node.lineno)
        self.generic_visit(node)


def main() -> int:
    argv = sys.argv[1:]
    files = DEFAULT
    if "--files" in argv:
        files = argv[argv.index("--files") + 1].split(",")

    total: set[str] = set()
    for rel in files:
        tree = ast.parse((ROOT / rel).read_text(encoding="utf-8"))
        s = Scan()
        s.visit(tree)
        names = sorted(set(s.direct) | set(s.getattr_))
        total |= set(names)
        print("%s：读到 **%d 个**不同的名字" % (rel, len(names)))
        for n in names:
            d = s.direct.get(n, [])
            g = s.getattr_.get(n, [])
            parts = []
            if d:
                parts.append("直读 %s" % (d[:4] + (["…"] if len(d) > 4 else [])))
            if g:
                parts.append("getattr %s" % (g[:4] + (["…"] if len(g) > 4 else [])))
            print("   %-24s %s" % (n, "；".join(parts)))
        print()

    chars = ROOT / "ak_tactic" / "battle"
    print("=" * 66)
    print("合计 **%d 个**不同的名字 —— 这就是 `SpecInputs` 要覆盖的规模。" % len(total))
    print("battle/ 现有 %d 个 .py 文件" % len(list(chars.glob("*.py"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
