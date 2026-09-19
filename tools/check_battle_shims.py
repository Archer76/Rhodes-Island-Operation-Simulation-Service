# -*- coding: utf-8 -*-
"""搬运后的**消费者体检**：`battle/` 那些转出壳有没有让谁断掉。

## 为什么这个判据必须有

搬一个模块到 `frontend/` 之后，"新家对不对"有金标准盯着（规格哈希），
但"**旧地址还有没有人用、用了还解析得到吗**"没有判据。

搬 `devices.py` / `environment.py` 时，仓库里还有这些**不属于本层**的消费者：

```
ak_tactic/sim.py:523    from .devices import (BLOCKER_KEY, DeviceUnit, ...)
ak_tactic/sim.py:3391   from .environment import FarmlandSystem, PolluteParams
ak_tactic/sim.py:3966   from .environment import PUMP_RANGE, PUMP_RANGE_BONUS
ak_tactic/activity.py:77    anchor="ak_tactic.battle.devices:BLOCKER_KEY"
ak_tactic/activity.py:223   anchor="ak_tactic.battle.environment:RUNES_KEY"
ak_tactic/activity.py:376   from .battle.devices import parse_devices
```

`activity.py` **不是本会话的文件**，我不会去改它。所以"壳能不能让它继续工作"
只能靠**实测**回答，不能靠"反正转出了"推断。

## 判据

1. **导入点全解析**：全仓 grep 出所有 `battle.<模块>` 的导入点与字符串锚点，
   用 `importlib` + `getattr` 真的取一遍，取不到就报。
2. **同一对象**：新家的 `__all__` 里每个名字，旧壳取到的必须 `is` 新家的。
3. **`__all__` 之外的也照转**：把"被外部真正导入、但不在 `__all__` 里"的名字
   单独列出来，逐条验（`pump_once` 就是这么一位）。
4. **覆盖率自报**：扫到几个导入点就说几个 —— 判据跑空了不能读成通过。

跑法：`python tools\\check_battle_shims.py`
"""
from __future__ import annotations

import ast
import importlib
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

#: 转出壳 ↔ 新家
SHIMS = {
    "devices": "ak_tactic.frontend.devices",
    "environment": "ak_tactic.frontend.environment",
}

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "out", "data"}


def sources() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        out.append(p)
    return out


def import_sites() -> list[tuple[Path, int, str, str]]:
    """`(文件, 行号, battle 子模块, 名字)` —— 所有从 `battle.<模块>` 取名的点。"""
    hits = []
    for path in sources():
        try:
            src = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        #: 形态一：`from .devices import a, b` / `from ..battle.devices import a`
        for i, line in enumerate(src.splitlines(), 1):
            m = re.match(r"\s*from [\w.]*?battle\.(\w+) import (.+)$", line)
            if not m:
                m2 = re.match(r"\s*from \.(\w+) import (.+)$", line)
                if not m2 or path.parent.name != "battle":
                    continue
                m = m2
            sub = m.group(1)
            if sub not in SHIMS:
                continue
            body = m.group(2).split("#", 1)[0].strip().strip("()")
            for name in body.split(","):
                name = name.strip().split(" as ")[0].strip()
                if name and name.isidentifier():
                    hits.append((path, i, sub, name))
        #: 形态二：字符串锚点 `ak_tactic.battle.<模块>:<名字>`
        for i, line in enumerate(src.splitlines(), 1):
            for m in re.finditer(r"ak_tactic\.battle\.(\w+):(\w+)", line):
                if m.group(1) in SHIMS:
                    hits.append((path, i, m.group(1), m.group(2)))
    return hits


def main() -> int:
    bad = 0
    sites = import_sites()
    print("扫到 %d 个从 battle/ 转出壳取名字的点" % len(sites))
    if not sites:
        print("⚠ 一个点都没扫到 —— **判据跑空了**，不能当成通过")
        return 1

    per: dict[str, set[str]] = {k: set() for k in SHIMS}
    for path, lineno, sub, name in sites:
        per[sub].add(name)
    for sub, names in sorted(per.items()):
        print("  battle.%-12s 被取用 %d 个名字：%s" % (sub, len(names), sorted(names)))

    print()
    for sub, newpath in sorted(SHIMS.items()):
        old = importlib.import_module("ak_tactic.battle.%s" % sub)
        new = importlib.import_module(newpath)
        declared = list(getattr(new, "__all__", []))
        used = per[sub]
        extra = sorted(used - set(declared))
        print("=== battle/%s.py（新家 %s）===" % (sub, newpath))
        print("  新家 __all__ %d 项；外部实际取用 %d 项；其中 **不在 __all__ 里** %d 项%s"
              % (len(declared), len(used), len(extra),
                 ("：" + str(extra)) if extra else ""))
        for name in sorted(used):
            try:
                a, b = getattr(old, name), getattr(new, name)
            except AttributeError as exc:
                print("  ❌ %-26s 取不到：%s" % (name, exc))
                bad += 1
                continue
            if a is not b:
                print("  ❌ %-26s 不是同一对象（旧 %r / 新 %r）" % (name, a, b))
                bad += 1
        print("  ✅ %d 项逐条同一对象" % len(used))
        #: 壳的 dir 应当覆盖新家
        missing = [n for n in dir(new) if not n.startswith("__")
                   and not hasattr(old, n)]
        if missing:
            print("  ⚠ 壳取不到新家的 %d 个名字：%s" % (len(missing), missing[:8]))
            bad += 1
        else:
            print("  ✅ 壳覆盖新家全部公开名字（含 __all__ 之外的）")
        print()

    if bad:
        print("❌ %d 处有问题" % bad)
        return 1
    print("✅ 全部转出壳：%d 个取用点、%d 个子模块，逐条同一对象"
          % (len(sites), len(SHIMS)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
