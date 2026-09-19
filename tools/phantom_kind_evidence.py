#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""幽灵 kind 的自伤证据与回归守卫（C 档乙，2026-09-20）。

**为什么有这支脚本**：验收在 v1／v2 的**交付产物**里核不到「`enemy` 被当成 kind」这件事
（产物里 `"enemy"` 零次出现）——因为那是我**中间那次运行**的状态，产物已被覆盖。
验收的原话：**「修了什么」我不当既成事实；要把这类自伤留成证据，得能重跑。**
⇒ 所以这里不写叙述，写**可重跑的两面**：

* **自伤面**：把 **v1 的解析器逐字**从 git 里取出来跑（`git show 83a11a4:tools/kind_mech_map.py`），
  打印它把哪些**不是 kind 的东西**当成了 kind（本次是 `enemy`，来自
  `elif t.kind == "targets" and t.op == "enemy":`）。
* **修复面（控制组）**：v2 的解析器必须**一个幽灵都不产出**——否则这条守卫自己就是坏的。

退出码：0＝自伤可复现且修复有效；1＝任一面不成立（说明我描述的自伤不存在，或修复没生效）。
"""

from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
V1_SHA = "83a11a4"          #: 乙表第一版（自伤就在这一版）
V2_TOOL = ROOT / "tools" / "kind_mech_map.py"
FORMULA = ROOT / "ak_tactic" / "formula.py"


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def real_kinds() -> set[str]:
    """真 kind 的权威清单＝跑起来的 `RULES[*].kind`。"""
    sys.path.insert(0, str(ROOT))
    from ak_tactic import formula as F

    return {r.kind for r in F.RULES}


def v1_phantom_kinds() -> tuple[set[str], int]:
    """用 **v1 的解析器逐字**跑一遍，返回 (幽灵 kind 集合, v1 认到的 kind 总数)。"""
    blob = subprocess.run(["git", "show", f"{V1_SHA}:tools/kind_mech_map.py"],
                          cwd=ROOT, capture_output=True, text=True, encoding="utf-8")
    if blob.returncode != 0:
        raise SystemExit(f"取不到 v1 版本（{V1_SHA}）：{blob.stderr.strip()}")
    with tempfile.TemporaryDirectory() as td:
        p = Path(td) / "v1_kind_mech_map.py"
        p.write_text(blob.stdout, encoding="utf-8")
        mod = _load(p, "v1_kind_mech_map")
        # ★ v1 是**按自己的 `__file__` 推仓库根**的，放到临时目录后会把根算成 %TEMP%
        #   （实测 FileNotFoundError: ...\Temp\ak_tactic\formula.py）⇒ 路径全局量必须改回真仓库。
        mod.ROOT = ROOT
        mod.FORMULA = FORMULA
        mod.GO_ROOT = ROOT / "rios-sim"
        fields = mod.landing_fields()
    got = set(fields)
    return got - real_kinds(), len(got)


def v2_phantom_kinds() -> tuple[set[str], int]:
    """v2 的解析器（当前工作区那份）跑一遍，返回 (幽灵 kind 集合, 认到的 kind 总数)。"""
    mod = _load(V2_TOOL, "v2_kind_mech_map")
    got = set(mod.landing_fields())
    return got - real_kinds(), len(got)


def main() -> int:
    real = real_kinds()
    print(f"  真 kind 权威清单：{len(real)} 种（跑起来的 RULES[*].kind）")
    v1_ph, v1_n = v1_phantom_kinds()
    v2_ph, v2_n = v2_phantom_kinds()
    print(f"  【自伤面】v1（{V1_SHA}）认到 {v1_n} 个名字，其中**不是 kind 的**：{sorted(v1_ph) or '无'}")
    print(f"  【修复面】v2（当前工作区）认到 {v2_n} 个名字，其中不是 kind 的：{sorted(v2_ph) or '无'}")

    ok = True
    if not v1_ph:
        print("  ✗ 自伤面不成立：v1 解析器没有产出幽灵 kind ⇒ 我描述的那条自伤无法复现（不许当既成事实）")
        ok = False
    else:
        print(f"  ✓ 自伤可复现：v1 把 {sorted(v1_ph)} 当成了 kind（每条都来自 kind 条件里**不属于 kind 的那段**）")
    if v2_ph:
        print(f"  ✗ 修复面不成立：v2 仍产出幽灵 {sorted(v2_ph)} ⇒ 修复没生效")
        ok = False
    else:
        print("  ✓ 修复有效：v2 幽灵 0 个（控制组）")
    #: 定位到行：让「它从哪来」也能复核
    lines = FORMULA.read_text(encoding="utf-8").splitlines()
    for i, ln in enumerate(lines, 1):
        if re.search(r"""t\.kind\s*==\s*["']targets["']""", ln) and "enemy" in ln:
            print(f"  · 幽灵的来源行：ak_tactic/formula.py:{i}: {ln.strip()}")
    print(f"  ⇒ 证据{'成立' if ok else '不成立'}（rc={0 if ok else 1}）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
