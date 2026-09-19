# -*- coding: utf-8 -*-
"""量一下"删掉 `battle/` 还差什么"——按**消费者的字段面**算，不按行数算。

## 为什么要量这个

`build_spec` 对 `battle/` 的**方法调用**已经归零，但还有两种残留：

1. **对象**：`_operator_spec(sim, d)` 读的是 `d.operator`，那是个 `OperatorUnit`；
   `_unit_spec(sim, e)` 读的是 `enemy_view` 出来的命名空间（已脱钩 ✓）。
2. **属性**：`sim.stage` / `sim.enemy_at` / `sim.species_provider` 等。

行数说明不了问题——`unit.py` 里几百行是**跑帧**用的（`_tick`、位移、碰撞），
规格一行都不碰。要量的是**规格真正读到的那些名字**。

## 输出

* `unit.py` 的类/函数清单与行数
* `_operator_spec` 从 `d.operator` 上读到的名字集合
* 这些名字里，有多少**只由跑帧写**（那种字段在规格里必须写死或另找来源）

跑法：`python tools/size_unit_surface.py`
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

SPEC = ROOT / "ak_tactic" / "simgo" / "spec.py"
UNIT = ROOT / "ak_tactic" / "battle" / "unit.py"

#: `getattr(x, "名字", 默认)` 这种读法也要抓到——本项目大量用它，
#: 只抓 `x.名字` 会**漏掉一半**（`_unit_spec` 的清单就是这么漏出来的）。
GETATTR = re.compile(r"""getattr\(\s*(?:sim|op|e|d\.operator)\s*,\s*["']([a-z_0-9]+)["']""")
DOTTED = re.compile(r"""\b(?:sim|op|e|d\.operator)\.([a-z_0-9]+)\b""")


def reads_of(src: str, func_name: str) -> tuple[int, set[str]]:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            seg = ast.get_source_segment(src, node) or ""
            names = set(DOTTED.findall(seg)) | set(GETATTR.findall(seg))
            # 内部调用的名字不是"读属性"，剔掉常见的几个
            return (node.end_lineno or 0) - node.lineno + 1, names
    raise SystemExit("找不到函数 %s" % func_name)


def main() -> int:
    spec_src = SPEC.read_text(encoding="utf-8")
    unit_src = UNIT.read_text(encoding="utf-8")

    print("unit.py 共 %d 行" % len(unit_src.splitlines()))
    tree = ast.parse(unit_src)
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef)):
            n = (node.end_lineno or 0) - node.lineno + 1
            print("  %-16s %5d-%-6d %5d 行" % (node.name, node.lineno,
                                               node.end_lineno, n))

    print()
    for fn in ("_operator_spec", "_unit_spec"):
        n, names = reads_of(spec_src, fn)
        print("%s：%d 行，读到 %d 个名字" % (fn, n, len(names)))
        print("   " + ", ".join(sorted(names)))
        print()

    #: 这些名字里哪些**在 unit.py 里被赋过值**（说明是 `OperatorUnit` 的字段）
    assigned: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name in ("OperatorUnit",
                                                            "Combatant"):
            for st in ast.walk(node):
                if isinstance(st, ast.AnnAssign) and isinstance(st.target, ast.Name):
                    assigned.add(st.target.id)
                elif (isinstance(st, ast.Assign) and len(st.targets) == 1
                      and isinstance(st.targets[0], ast.Attribute)
                      and isinstance(st.targets[0].value, ast.Name)
                      and st.targets[0].value.id == "self"):
                    assigned.add(st.targets[0].attr)
    _, opn = reads_of(spec_src, "_operator_spec")
    on_unit = sorted(x for x in opn if x in assigned)
    print("`_operator_spec` 读的 %d 个名字里，**%d 个是 `OperatorUnit`/`Combatant` "
          "的字段**：" % (len(opn), len(on_unit)))
    print("   " + ", ".join(on_unit))
    rest = sorted(opn - set(on_unit))
    print("其余 %d 个（多半是方法或 `Deployment` 上的）：" % len(rest))
    print("   " + ", ".join(rest))
    return 0


if __name__ == "__main__":
    sys.exit(main())
