# -*- coding: utf-8 -*-
"""`simgo/` 对 `battle/` 的**导入级**依赖——`spec_deps.py` 结构上看不到的那一半。

## 为什么需要它

`spec_deps.py` 量的是"`build_spec` 调了 `battle/` 的哪些**方法**"，
那一路已经归零。但它量不到另一种关系：

```python
from ..battle import environment as env          # mech.py:36
from ..battle.devices import BLOCKER_KEY          # mech.py:37
from ..battle import sim as _sim_mod              # mech.py:270（三个常量）
from ..battle import talents as _talents          # spec.py:342/510/535/566/735
```

这些**一个方法都不调**，可 `battle/` 一删就全断。
⇒ "摘除面"必须两张表一起看：**调用面**（`spec_deps`）＋ **导入面**（本工具）。

⚠ 这是本会话第三次遇到同一形态：**仪器的视野决定了它能否证什么**。
"归零"永远要问一句"这台仪器看得见哪些关系"。

## 输出

* 每个 `simgo/` 文件从 `battle/` 导入了哪些模块、哪些名字
* 按 `battle/` 的**目标模块**归并（那才是"要搬什么"的清单）
* 每个被导入的名字在源码里**被用了几次**（0 次的说明是死导入）

跑法：`python tools\\spec_imports.py`
"""
from __future__ import annotations

import ast
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SIMGO = ROOT / "ak_tactic" / "simgo"
BATTLE = ROOT / "ak_tactic" / "battle"
sys.stdout.reconfigure(encoding="utf-8")


def scan(path: Path) -> list[tuple[int, str, list[tuple[str, str]]]]:
    """`(行号, battle 子模块, [(原名, 代码里用的名)])`。

    ⚠ **一定要认别名**：`from ..battle import environment as env` 之后代码里写的是
    `env`。按原名 `environment` 去数会数出 0 次，读成"死导入"——
    第一版就是这么报的（一个**不存在**的死导入）。
    """
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            #: `from ..battle import x` → level=2, module='battle'
            #: `from ..battle.devices import a, b` → module='battle.devices'
            if not mod.startswith("battle"):
                continue
            sub = mod[len("battle"):].lstrip(".") or "（包本身）"
            out.append((node.lineno, sub,
                        [(a.name, a.asname or a.name) for a in node.names]))
    return out


def uses_of(src: str, name: str) -> int:
    """这个名字在**代码**里出现几次（排除它自己那行 import）。"""
    n = 0
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if s.startswith("#") or s.startswith("from ") or s.startswith("import "):
            continue
        n += len(re.findall(rf"\b{re.escape(name)}\b", line.split("#", 1)[0]))
    return n


def main() -> int:
    by_module: dict[str, list[tuple[str, int, str, int]]] = defaultdict(list)
    total = 0
    for path in sorted(SIMGO.glob("*.py")):
        src = path.read_text(encoding="utf-8")
        found = scan(path)
        if not found:
            continue
        print("=== %s ===" % path.name)
        for lineno, sub, pairs in found:
            shown = ", ".join(
                "%s%s(用%d次)" % (orig, "" if used == orig else "→" + used,
                                  uses_of(src, used))
                for orig, used in pairs)
            print("  %4d: battle.%s → %s" % (lineno, sub, shown))
            for orig, used in pairs:
                by_module[sub].append((path.name, lineno, orig,
                                       uses_of(src, used)))
                total += 1
        print()

    print("=" * 70)
    print("按 `battle/` 的目标模块归并（**这才是「要搬什么」的清单**）：")
    for sub, rows in sorted(by_module.items(), key=lambda kv: -len(kv[1])):
        lines = None
        cand = BATTLE / (sub + ".py") if sub != "（包本身）" else BATTLE / "__init__.py"
        if cand.exists():
            lines = len(cand.read_text(encoding="utf-8").splitlines())
        print("  battle/%-14s %d 处导入%s"
              % (sub, len(rows), "，该文件 %d 行" % lines if lines else ""))
        #: 名字 → 用了几次；0 次的是死导入，删起来最便宜
        agg: dict[str, int] = {}
        for _f, _l, n, u in rows:
            agg[n] = agg.get(n, 0) + u
        dead = [n for n, u in agg.items() if u == 0]
        print("      名字：%s" % ", ".join(
            "%s%s" % (n, "" if agg[n] else "（**没用到**）")
            for n in sorted(agg)))
        if dead:
            print("      ⚠ %d 个死导入：%s" % (len(dead), dead))
    print()
    print("合计 %d 处导入。" % total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
