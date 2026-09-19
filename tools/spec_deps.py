#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""摘除面测量：从 `build_spec` 出发，`ak_tactic/battle/` 里到底有多少代码是
**Go 这条路真正要用的**？

## 为什么先量这个

目标是把 `ak_tactic/battle/`（9280 行）整体摘除。但 `build_spec(sim)` 现在读一个
**活的 `BattleSimulator`**，其中既有"关卡静态"（stage/fps/cost），也有**引擎内部计算**
（`_spawn` / `_build_enemy` / `_range_of` / `_path_from` / `_cannot_clear`）。

不知道**哪些函数真的在路上**，就只能整包重写——那是把它当新项目做。
知道了可达集，才能分清三件事：

* **要搬走的**：可达且是纯计算（范围、寻路、造敌人、出怪表）→ 搬进新家；
* **要换成数据的**：可达但只是"排程产物"或"关卡静态"（deployments / stage / cost）
  → 改成显式入参，不必搬代码；
* **可以删的**：不可达 → 随着 `battle/` 一起消失，不用管。

## 判据与它的边界

可达性按**同一个包内的名字**做：`self._foo(...)` / `sim._foo(...)` / 裸 `foo(...)`
解析到 `battle/` 包里的定义就算一条边。⚠ 这是**静态近似**，它只回答"这个名字有没有
被提到"，不回答"运行期真的走到没有"——所以本报告的口径是**上界**（宁可多算不可少算）。

root 是 `simgo/spec.py` 里所有 `sim.<name>` 的**方法名**（属性读算作的另记，
它们没有函数体，属于"换成数据"那一类）。

用法:
    python tools\\spec_deps.py            # 打印分档报告
    python tools\\spec_deps.py --list     # 连可达函数名一起列出来
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

BATTLE = ROOT / "ak_tactic" / "battle"
SIMGO = ROOT / "ak_tactic" / "simgo"

#: ⚠ **要扫的是整个 `simgo/` 包，不是只有 `spec.py`。**
#:
#: 这个工具的第一版只扫 `spec.py`，于是报出"方法调 0 项、可达闭包 0 个函数"
#: ——而同一时刻 `mech.py` 里 `sim._pile_spec` / `sim._build_enemy` /
#: `sim._summon_level` 都还是**真调用**。仪器没往那边看，那三个名字就
#: 从来没机会出现，看起来像"已经摘干净了"。
#:
#: ⚠ 这是本项目反复吃亏的同一形态：**判据覆盖不到的地方只会沉默，不会否证。**
#: 一个"归零"的读数必须先问"这台仪器看得见哪些文件"，再当结论用。
SOURCES = sorted(SIMGO.glob("*.py"))

#: 当作"模拟器对象"的变量名（`probe` 是浅拷贝的历史写法）。
RECEIVERS = {"sim", "probe"}

#: 读数要怎么读——**清单本身会误导人**，这几条是逐项核过的。
#:
#: ⚠ 一张"还差 N 项"的表如果不写清楚哪几项不是欠账，下一个人会照着它去修
#: 不该修的东西，或者相反地以为"有 7 项呢，还早"。
KNOWN_OK = {
    "ping": "`client.py` 里的 `sim` 是 **Go 进程句柄**（`Simgo`），不是模拟器——假阳性",
    "run": "`verifier.py` 的**退回 Python 兜底路径**：规格报 unsupported 时才走，"
           "有意保留（`battle/` 整体弃用之前它必须还在）",
}


def _defs_of(tree: ast.Module) -> dict[str, ast.AST]:
    """模块里所有函数/方法的定义（按名字，不区分归属）。"""
    out: dict[str, ast.AST] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
    return out


def _callees(node: ast.AST) -> set[str]:
    """一个函数体里出现的被调名（`self.x()` / `sim.x()` / `x()` 都收 `x`）。"""
    out: set[str] = set()
    for n in ast.walk(node):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Attribute):
                out.add(f.attr)
            elif isinstance(f, ast.Name):
                out.add(f.id)
    return out


def main() -> int:
    # ---- root：**simgo/ 全部文件**里读过/调过的 sim 成员 ----
    #
    # ⚠ 收集时**记住出处文件**：`mech.py` 与 `spec.py` 的残留要能分开看，
    # 否则修完一处会以为全干净了。
    props: dict[str, list[str]] = {}
    methods: dict[str, list[str]] = {}
    called: set[str] = set()
    scanned: list[str] = []
    for path in SOURCES:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        scanned.append(path.name)
        for node in ast.walk(tree):
            if (isinstance(node, ast.Attribute)
                    and isinstance(node.value, ast.Name)
                    and node.value.id in RECEIVERS):
                props.setdefault(node.attr, []).append(
                    f"{path.name}:{node.lineno}")
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and isinstance(node.func.value, ast.Name)
                    and node.func.value.id in RECEIVERS):
                called.add(node.func.attr)
    for name in called:
        entries = props.pop(name, [])
        methods.setdefault(name, entries or ["(仅出现在调用里)"])

    # ---- battle 包的全部定义 ----
    all_defs: dict[str, ast.AST] = {}
    where: dict[str, str] = {}
    trees: dict[str, ast.Module] = {}
    for f in sorted(BATTLE.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            t = ast.parse(src)
        except SyntaxError:
            continue
        trees[f.name] = t
        for name, node in _defs_of(t).items():
            all_defs.setdefault(name, node)
            where.setdefault(name, f.name)

    # ---- 从 methods 出发做闭包 ----
    #
    # ⚠ **只从"真正要搬的"那些出发**。`KNOWN_OK` 里的 `sim.run` 是退回 Python 的
    # 兜底路径，从它出发的闭包就是**整个引擎**（223 个函数）——那个数字
    # 既吓人又没意义：它算的是"Python 引擎一共多大"，不是"还欠多少"。
    # 一张把两种东西混在一起的表，比没有表更容易把人带偏。
    roots = [m for m in methods if m not in KNOWN_OK]
    seen: set[str] = set()
    stack = [m for m in roots if m in all_defs]
    missing = [m for m in roots if m not in all_defs]
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        for callee in _callees(all_defs[name]):
            if callee in all_defs and callee not in seen:
                stack.append(callee)

    total_lines = sum(len((BATTLE / f).read_text(encoding="utf-8").splitlines())
                      for f in [x.name for x in sorted(BATTLE.glob("*.py"))])

    print("摘除面测量：`build_spec` → `ak_tactic/battle/`")
    print(f"  battle/ 合计 {total_lines} 行")
    print(f"  ⚠ 扫的文件（{len(scanned)}）：{', '.join(scanned)}")
    print()
    print(f"① 属性读（没有函数体，属于「换成数据」那一类）：{len(props)} 项")
    for name in sorted(props, key=lambda n: (-len(props[n]), n)):
        where_s = ", ".join(props[name][:4]) + ("…" if len(props[name]) > 4 else "")
        print(f"     sim.{name:<22} {where_s}")
    print()
    print(f"② 方法调（有函数体，要判「搬走」还是「本来就能删」）：{len(methods)} 项")
    real = [m for m in methods if m not in KNOWN_OK]
    for name in sorted(methods):
        ok = KNOWN_OK.get(name)
        if ok:
            flag = "—（已核过，不是欠账）"
        elif name in all_defs:
            flag = "✅在 battle/ ← **要搬**"
        else:
            flag = "❓不在 battle/"
        w = where.get(name, "—")
        loc = methods[name][:3]
        print(f"     sim.{name:<22} {flag:<32} {w:<14} {loc}")
        if ok:
            print(f"         ↳ {ok}")
    print(f"     ⇒ **真正要搬的：{len(real)} 项** {sorted(real)}")
    print()
    print(f"③ 从那些方法出发的**可达闭包**：{len(seen)} 个函数"
          f"（占了 battle/ 的一大部分，逐条见 --list）")
    by_file: dict[str, int] = {}
    for name in seen:
        by_file[where[name]] = by_file.get(where[name], 0) + 1
    for fn, cnt in sorted(by_file.items(), key=lambda kv: -kv[1]):
        lines = len((BATTLE / fn).read_text(encoding="utf-8").splitlines())
        print(f"     {fn:<22} {cnt:>4} 个可达函数 / 该文件 {lines} 行")
    if missing:
        print()
        print(f"⚠ 这 {len(missing)} 个名字在 battle/ 里没有定义（规格层自己的）："
              f"{sorted(missing)}")

    if "--list" in sys.argv:
        print()
        print("可达函数全表：")
        for name in sorted(seen):
            node = all_defs[name]
            n = (getattr(node, "end_lineno", 0) or 0) - node.lineno + 1
            print(f"     {where[name]:<22} {name:<44} {n:>4} 行")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
