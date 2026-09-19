# -*- coding: utf-8 -*-
"""`_operator_spec` 读的名字，哪些**来自 `verify.py::unit` 的 `kw`**、哪些不是。

## 为什么量这个

敌人那一侧能脱钩，是因为 `_build_enemy` 那一大段就是"从 `stats` 抄字段"，
机械生成一份视图即可。干员这一侧形状**看起来**一样（`OperatorUnit(**kw)`），
但 `kw` 只喂了一部分——`OperatorUnit` 有 134 个 dataclass 字段，`kw` 大约 50 个，
其余走**默认值**，另有一批是**跑帧时**才写的。

⇒ 规格要的那 36 个名字里，有多少落在"默认值"那一类，决定了视图能不能只是
`SimpleNamespace(**kw)`，还是得补齐默认值 / 现算。

## 三类

* **kw** —— `verify.py::unit` 的 `kw` dict 里显式给了
* **default** —— `OperatorUnit` 的 dataclass 默认值（`kw` 没给），类型上仍是"数据"
* **computed** —— `OperatorUnit` 的方法（`current_atk` 等），要现算

跑法：`python tools\size_operator_surface.py`
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
VERIFY = ROOT / "ak_tactic" / "verify.py"
UNIT = ROOT / "ak_tactic" / "battle" / "unit.py"

DOTTED = re.compile(r"\b(?:op|d\.operator)\.([a-z_0-9]+)\b")
GETATTR = re.compile(r"""getattr\(\s*(?:op|d\.operator)\s*,\s*["']([a-z_0-9]+)["']""")


def unit_kw_keys() -> set[str]:
    """`verify.py::unit` 里那个 `kw = dict(...)` 的键。"""
    tree = ast.parse(VERIFY.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "unit":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and isinstance(sub.targets[0], ast.Name)
                        and sub.targets[0].id == "kw"
                        and isinstance(sub.value, ast.Call)
                        and getattr(sub.value.func, "id", "") == "dict"):
                    return {k.arg for k in sub.value.keywords if k.arg}
    raise SystemExit("找不到 verify.py::unit 里的 kw = dict(...)")


def spec_reads(func: str) -> set[str]:
    src = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func:
            seg = ast.get_source_segment(src, node) or ""
            return set(DOTTED.findall(seg)) | set(GETATTR.findall(seg))
    raise SystemExit("找不到 %s" % func)


def cls_members(name: str) -> tuple[set[str], set[str]]:
    """(dataclass 字段, 方法名)。"""
    tree = ast.parse(UNIT.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            fields = {x.target.id for x in node.body
                      if isinstance(x, ast.AnnAssign) and isinstance(x.target, ast.Name)}
            meths = {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
            return fields, meths
    raise SystemExit("找不到类 %s" % name)


def main() -> int:
    kw = unit_kw_keys()
    reads = spec_reads("_operator_spec")
    fields, meths = cls_members("OperatorUnit")

    print("verify.py::unit 的 `kw` 给了 **%d 个**键" % len(kw))
    print("OperatorUnit dataclass 字段 %d 个、方法 %d 个" % (len(fields), len(meths)))
    print("_operator_spec 读 %d 个名字" % len(reads))
    print()

    from_kw = sorted(reads & kw)
    computed = sorted(reads & meths)
    from_default = sorted(reads - kw - meths - {"py"})
    unknown = sorted(x for x in from_default if x not in fields)

    print("A. **来自 `kw`**（%d 个）—— 视图直接带得走：" % len(from_kw))
    print("   " + ", ".join(from_kw))
    print()
    print("B. **是方法**（%d 个）—— 视图要现算：" % len(computed))
    print("   " + ", ".join(computed))
    print()
    print("C. **没在 `kw` 里**（%d 个）—— 走 dataclass 默认值或跑帧才写：" % len(from_default))
    print("   " + ", ".join(from_default))
    if unknown:
        print()
        print("   ⚠ 其中 %d 个**连字段都不是**（可能是别的对象的、或写错了）：%s"
              % (len(unknown), unknown))
    print()
    print("⇒ 结论：视图可以 = `SimpleNamespace(**kw)` ＋ %d 个方法 ＋ %d 个默认值。"
          % (len(computed), len(from_default)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
