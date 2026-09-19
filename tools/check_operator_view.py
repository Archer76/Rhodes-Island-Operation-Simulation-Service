# -*- coding: utf-8 -*-
"""`OperatorView` 与真 `OperatorUnit` 的逐项 A/B。

## 判据

对每一份计划、每一个上场的练度，`verify.py::unit` 会算出一份 `kw`（35 键）。
把它**同时**喂给两台构造器：

```python
real = OperatorUnit(**kw)          # 原版
view = operator_view(kw)           # 新家
```

然后逐项比 `_operator_spec` 真正读到的那些名字。

⚠ **读取面从 AST 现取**，不写死一张表。写死会漂：本会话里同一份代码在
两个工具下量出过 31 与 36 两个数（正则口径不同），照哪一张写都会漏。
「判据能看见什么」必须与「结论要说什么」对齐——这是本项目最贵的一条教训。

## 为什么这个 A/B 是必要的

手抄 134 个 dataclass 默认值必然错几个，而错的症状是
「某个字段开局不是 0」——不报错、只在特定关卡差一点。
本视图是**机械生成**的（`tools/gen_operator_view.py`），这个 A/B 是它的守卫。

跑法：`python tools\\check_operator_view.py [--limit N]`
"""
from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle.unit import OperatorUnit                     # noqa: E402
from ak_tactic.frontend.operator_view import operator_view         # noqa: E402
from ak_tactic.plan import Plan, Roster                            # noqa: E402
from ak_tactic.verify import Verifier                              # noqa: E402

OUT = ROOT / "out"
SPEC = ROOT / "ak_tactic" / "simgo" / "spec.py"
UNIT = ROOT / "ak_tactic" / "battle" / "unit.py"

DOTTED = re.compile(r"\b(?:op|d\.operator|e)\.([a-z_][a-z_0-9]*)\b")
GETATTR = re.compile(
    r"""getattr\(\s*(?:op|d\.operator|e)\s*,\s*["']([a-z_][a-z_0-9]*)["']""")

#: 采集到的 kw（每个练度一份，去重）
COLLECTED: dict[tuple, dict] = {}


def read_set() -> tuple[set[str], set[str]]:
    """`(_operator_spec` 读到的名字, `OperatorUnit` 的方法名)`。"""
    src = SPEC.read_text(encoding="utf-8")
    tree = ast.parse(src)
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_operator_spec":
            seg = ast.get_source_segment(src, node) or ""
            names = set(DOTTED.findall(seg)) | set(GETATTR.findall(seg))
    utree = ast.parse(UNIT.read_text(encoding="utf-8"))
    meths: set[str] = set()
    for node in ast.walk(utree):
        if isinstance(node, ast.ClassDef) and node.name == "OperatorUnit":
            meths = {m.name for m in node.body if isinstance(m, ast.FunctionDef)}
    return names, meths


def _kw_keys() -> set[str]:
    """`verify.py::unit` 那个 `kw = dict(...)` 的**全部**键（它才是理论上限）。"""
    src = (ROOT / "ak_tactic" / "verify.py").read_text(encoding="utf-8")
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == "unit":
            for sub in ast.walk(node):
                if (isinstance(sub, ast.Assign) and len(sub.targets) == 1
                        and isinstance(sub.targets[0], ast.Name)
                        and sub.targets[0].id == "kw"
                        and isinstance(sub.value, ast.Call)
                        and getattr(sub.value.func, "id", "") == "dict"):
                    return {k.arg for k in sub.value.keywords if k.arg}
    raise SystemExit("找不到 verify.py::unit 里的 kw = dict(...)")


class OpCapture(Verifier):
    """只为在 `build_spec` 之前把 `_unit_cache` 抄下来。"""

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None, **kw):
        for key, val in dict(self._unit_cache).items():
            COLLECTED[key] = dict(val)
        return Verifier._run_other_engine(
            self, sim=sim, plan=plan, stage=stage, deployed=deployed,
            title=title, schedule=schedule, env=env)


def _find(name: str) -> Path:
    """按名字找夹具。⚠ 要**带 .json 再试一遍**（`roster_max_modelled` 是别名）。"""
    names = [name] if name.endswith(".json") else [name, f"{name}.json"]
    for n in names:
        for cand in (OUT / n, ROOT.parent / "ak-tactic-head" / "out" / n):
            if cand.exists():
                return cand
    raise SystemExit(f"找不到夹具 {name}")


def main() -> int:
    limit = None
    if "--limit" in sys.argv:
        limit = int(sys.argv[sys.argv.index("--limit") + 1])

    reads, meths = read_set()
    print("读取面（AST 现取）：`_operator_spec` 读到 %d 个名字、其中 %d 个是方法"
          % (len(reads), len(reads & meths)))

    roster_file = _find("roster_max_modelled")
    plans = sorted(OUT.glob("plan-*.json"))
    if limit:
        plans = plans[:limit]

    failed = 0
    for plan_file in plans:
        raw = json.loads(plan_file.read_text(encoding="utf-8-sig"))
        try:
            OpCapture().run(Plan.from_dict(raw), roster=Roster.from_json(roster_file))
        except Exception as exc:                                  # noqa: BLE001
            print("  ⚠ %s 跑不动：%s" % (plan_file.stem, exc))
            failed += 1

    print("采到 %d 个练度的 `kw`" % len(COLLECTED))
    if not COLLECTED:
        print("⚠ 一个都没采到——**判据跑空了**，不能当成通过")
        return 1

    #: ⚠ **覆盖自检**：`kw` 的键不是每份都有——`splash_*` 只有撼地者、
    #: `combo_*` 只有连击特性、`hp_drain_per_sec` 只有怪杰…7 个练度如果都没踩到
    #: 某一条，那一条的字段就**从没被比过**，而报告照样全绿。
    #: 「判据没跑到」与「判据说没问题」是两件事——这条纪律本会话已经付过学费。
    seen_keys: set[str] = set()
    for kw in COLLECTED.values():
        seen_keys |= set(kw)
    all_keys = _kw_keys()
    missing = sorted(all_keys - seen_keys)
    print("   `kw` 的键覆盖：%d/%d" % (len(seen_keys & all_keys), len(all_keys)))
    if missing:
        print("   ⚠ 这 %d 个键**在所有样本里都没出现**（那几个字段这次没被比过）："
              % len(missing))
        print("      " + ", ".join(missing))

    diffs: list[str] = []
    for key, kw in COLLECTED.items():
        real = OperatorUnit(**kw)
        view = operator_view(kw)
        for name in sorted(reads):
            try:
                r = getattr(real, name)
                if callable(r):
                    r = r()
            except Exception as exc:                              # noqa: BLE001
                diffs.append("%s: 原版 %s 读不出（%s）" % (key, name, exc))
                continue
            try:
                g = getattr(view, name)
                if callable(g):
                    g = g()
            except Exception as exc:                              # noqa: BLE001
                diffs.append("%s: 视图 %s 读不出（%s）" % (key, name, exc))
                continue
            if r != g:
                diffs.append("%s: %s 原版=%r 视图=%r" % (key, name, r, g))

    print()
    if diffs:
        print("❌ %d 处不一致：" % len(diffs))
        for d in diffs[:20]:
            print("   " + d)
        return 1
    print("✅ %d 个练度 × %d 项，逐项一致"
          % (len(COLLECTED), len(reads)))
    if failed:
        print("（另有 %d 份计划没跑起来，见上）" % failed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
