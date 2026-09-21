#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 的四张分类表与拆变体 vs Python 的同名表和 `_split_variant`。

## 比什么（两件都已确定的事）

* **表成员**：`BUFF_KEYS` / `DAMAGE_KEYS` / `CONTROL_KEYS` / `_FLIGHT_KEYS`
  在本仓是**可直接 import 的常量**，逐键比成员与量纲；
* **拆变体**：`_split_variant` 是纯函数，逐键比。

## 不比什么（本轮**未接**，具名）

`_classify` 的**降级序列**（原样 → 去 `xxx@` 前缀 → 去 `_s2`/`_2` 尾巴 →
去夹在 `@` 后的技能槽标记）——本文件不拿它当判据，Go 也没实现它。

## 覆盖面

**全表所有技能的所有等级的全部黑板键**取并集后逐个比——不抽样。

用法:
    python tools\\check_classify_go.py
    python tools\\check_classify_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"


def go_classify(keys: list[str]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "classify", "spec": keys}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["classes"]


def main() -> int:
    from ak_tactic.operator import SkillBook
    from ak_tactic.operator.skill import _classify, _split_variant

    book = SkillBook()
    keys: set[str] = set()
    for sid in book.all_ids():
        for lv in book.levels(sid):
            keys.update(lv.blackboard.keys())
    keys = sorted(keys)
    print("全表黑板键并集：%d 个（所有技能 × 所有等级）" % len(keys))

    got = go_classify(keys)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0]["kind"] = "<mutated>"

    def expect(k: str) -> dict:
        """★ **直接问 Python 的分类器**，不自己重写一遍表。

        第一版是我照着表手写的期望值，于是"control 的量纲"我两处都写成
        `secs`（Python 是 `sec`），判据照样全绿——**两把相同的尺子互证**。
        现在期望值来自 `_classify` 本身，才是真的在被测方那一侧取证。
        """
        var, rest = _split_variant(k)
        e = {"key": k, "kind": "", "field": "", "unit": "",
             "variant": var or "", "no_variant": rest, "has_variant": var is not None}
        hit = _classify(k)
        if hit:
            e["kind"], e["field"], e["unit"] = hit
        return e

    bad = 0
    kinds: dict[str, int] = {}
    variants = 0
    for k, g in zip(keys, got):
        e = expect(k)
        out = [f for f in ("kind", "field", "unit", "variant", "no_variant")
               if g.get(f) != e[f]]
        if e["has_variant"] != g.get("has_variant"):
            out.append("has_variant")
        kinds[e["kind"] or "(未归类)"] = kinds.get(e["kind"] or "(未归类)", 0) + 1
        if e["has_variant"]:
            variants += 1
        if out:
            bad += 1
            if bad <= 12:
                print("✗ %s —— %s" % (k, "、".join(
                    "%s Go=%r Python=%r" % (f, g.get(f), e[f]) for f in out)))
    print()
    print("已比：四张表的成员与量纲 ＋ 拆变体；共 %d 个键" % len(keys))
    print("★ 行使计数（按类别）：%s" % ", ".join(
        "%s=%d" % (k, v) for k, v in sorted(kinds.items())))
    print("★ 带变体限定的键：%d 个" % variants)
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    print("结论：%d / %d 个键逐字段一致" % (len(keys) - bad, len(keys)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
