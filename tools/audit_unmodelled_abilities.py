#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""「连字段都没有的敌人能力」审计：把**字段驱动闸门看不见的那一类**变成会响的。

## 为什么要有这个工具

`spec.py::_enemy_reasons` 是**字段驱动**的：`EnemyUnit` 上哪个字段非零，就说明
那段代码这一局会跑，于是拒跑。这个设计本身是对的——判据不看名字、不看描述关键词。

但它有一类**结构性**的盲：有些敌人能力**在原版里也没拿到字段**，只活在图鉴正文里。
字段表里没有它们，闸门对它们**永远沉默**。而"沉默"与"查过了没问题"在输出上
长得一模一样——这是本项目反复吃过的一个坑（覆盖不到机制的判据只会沉默不会否证）。

⚠ 而 `tools/audit_gate_blindspot.py` 补不了这一块：它扫的是 **`sim.X` 的读写时机**，
是字段级的；行为级的它看不见。两个工具扫的是**正交**的两个面，都要在。

## 判据（两道，都要成立才算"可以不管"）

1. **原版战斗层也没建模**。对每条登记的 `py_tokens`，扫 `ak_tactic/battle/*.py` 的
   **代码**（docstring 与注释不算——`devices.py` 那句「将身后一格的浅水泵至前方」
   就是泵站正文的文档字符串，把「浅水」扫成"已实现"是这类工具最容易出的假红）。
   命中 0 ⇒ 两台引擎同样不建模 ⇒ 对拍成立 ⇒ **不该进闸门**（进了是无理由拒跑）。
2. **载体清单对得上**。登记的 `carriers` 是名字；这一关的出怪表里出现哪几只、
   哪几只就带着这条没建模的能力。这一半是给人看的账。

## 红色意味着什么

某条 `py_tokens` 命中了 ⇒ 它**已经被接进原版战斗层**。此时：
要么把它移进闸门（Go 没跟上的话），要么把 Go 也补上。**不许放着不管**——
那正是"将来那一半"：新实现未必落在一个新字段上，字段表接不住它。

用法:
    python tools\\audit_unmodelled_abilities.py            # 审计；有红则退出码 1
    python tools\\audit_unmodelled_abilities.py --plans    # 另列出 17 份计划各带哪些
"""
from __future__ import annotations

import ast
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

BATTLE = ROOT / "ak_tactic" / "battle"


def _docstring_lines(tree: ast.Module) -> set[int]:
    """**跨行字符串**占用的行号（docstring 与长文本参数都算）。

    与 `audit_gate_blindspot.py` 里那份同源（那份的注释记了两版相反的错误方向）：
    第一版收**所有**字符串常量 ⇒ 真读被误滤；第二版只收 docstring ⇒ 长文本参数的
    第二行漏网。现在只收**跨行**的：够长、又不误伤单行短串。
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.end_lineno and node.end_lineno > node.lineno):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


def scan_code_tokens(tokens: tuple[str, ...]) -> list[tuple[str, int, str]]:
    """在**战斗层的代码行**里找这些词（docstring / 注释行不算）。"""
    hits: list[tuple[str, int, str]] = []
    for f in sorted(BATTLE.glob("*.py")):
        src = f.read_text(encoding="utf-8")
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        skip = _docstring_lines(tree)
        for i, line in enumerate(src.splitlines(), 1):
            if i in skip:
                continue
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            for tok in tokens:
                if tok in line:
                    hits.append((f.name, i, stripped[:96]))
                    break
    return hits


def main() -> int:
    from ak_tactic.simgo import mech
    from ak_tactic.gamedata import load_stage, EnemyLibrary, GameDataSource

    table = mech.UNMODELLED_ENEMY_ABILITIES
    print(f"「连字段都没有的敌人能力」审计：登记 {len(table)} 条")
    print(f"  扫描面：{BATTLE.relative_to(ROOT)}/*.py 的**代码行**"
          f"（docstring 与注释行不计）")
    print()

    red = 0
    for name, spec in table.items():
        tokens = tuple(spec["py_tokens"])
        hits = scan_code_tokens(tokens)
        if hits:
            red += 1
            print(f"  ❌ {name}：**已在原版战斗层出现**（{'/'.join(tokens)}）")
            for fn, ln, txt in hits[:4]:
                print(f"       {fn}:{ln}: {txt}")
            print(f"       ⇒ 要么把它移进 `spec.py` 的闸门，要么把 Go 补上。")
        else:
            print(f"  ✅ {name}：原版战斗层零命中 ⇒ 两台引擎都不建模，对拍成立、不进闸门")
            print(f"       能力：{spec['text']}")
            print(f"       载体：{'/'.join(spec['carriers'])}")
            if spec.get("note"):
                print(f"       ⚠ {spec['note']}")
    print()

    if "--plans" in sys.argv:
        print("各计划带到的『未建模能力』载体（按名字对出怪表）：")
        src = GameDataSource()
        lib = EnemyLibrary(src)
        carrier_of: dict[str, list[str]] = {}
        for nm, spec in table.items():
            for c in spec["carriers"]:
                carrier_of.setdefault(c, []).append(nm)
        for p in sorted((ROOT / "out").glob("plan-*.json")):
            raw = json.loads(p.read_text(encoding="utf-8"))
            try:
                st = load_stage(raw["stage"], source=src)
            except Exception as e:                       # noqa: BLE001
                print(f"  {p.name}: 关卡载入失败 {type(e).__name__}")
                continue
            names: set[str] = set()
            for sp in getattr(st, "spawns", []) or []:
                eid = getattr(sp, "enemy_id", None)
                if not eid:
                    continue
                try:
                    e = lib.get(eid, level=getattr(sp, "level", 1) or 1)
                except Exception:                        # noqa: BLE001
                    continue
                nm = getattr(e, "name", None)
                if nm:
                    names.add(nm)
            hit = sorted(n for n in names if n in carrier_of)
            if hit:
                detail = "; ".join(f"{n}→{'/'.join(carrier_of[n])}" for n in hit)
                print(f"  {p.name:<22} {detail}")
        print()

    print(f"结论：{'有 %d 条已翻红，见上' % red if red else '全部条目守卫成立，没有翻红'}")
    return 1 if red else 0


if __name__ == "__main__":
    raise SystemExit(main())
