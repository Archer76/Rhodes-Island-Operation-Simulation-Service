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

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `_classify` / `_split_variant`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/分类.json`，**不 import `ak_tactic`**。

★ **这套要冻的是两半**：键集（`("query", …)`）与逐键期望值。
**只冻期望值不冻键集**，check 档就问不出该问哪些键——而若有人顺手改成硬编码子集，
**分母静默变小而全绿**。查询集是判据的一部分。

用法:
    python tools\\check_classify_go.py
    python tools\\check_classify_go.py --mutate
    python tools\\freeze_baseline.py --record 分类
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"


def py_blackboard_keys() -> list[str]:
    """查询集：全表所有技能所有等级的黑板键并集（**这是 Python 侧的产物，必须冻住**）。"""
    from ak_tactic.operator import SkillBook
    book = SkillBook()
    keys: set[str] = set()
    for sid in book.all_ids():
        for lv in book.levels(sid):
            keys.update(lv.blackboard.keys())
    return sorted(keys)


def py_classify_expect(k: str) -> dict:
    """单个键的期望值。★ **直接问 Python 的分类器**，不自己重写一遍表。

    第一版是照着表手写的期望值，于是「control 的量纲」两处都写成 `secs`
    （Python 是 `sec`），判据照样全绿——**两把相同的尺子互证**。
    现在期望值来自 `_classify` 本身，才是真的在被测方那一侧取证。
    """
    from ak_tactic.operator.skill import _classify, _split_variant
    var, rest = _split_variant(k)
    e = {"key": k, "kind": "", "field": "", "unit": "",
         "variant": var or "", "no_variant": rest, "has_variant": var is not None}
    hit = _classify(k)
    if hit:
        e["kind"], e["field"], e["unit"] = hit
    return e


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
    G = GB.bind("分类", __file__)

    keys = G.expect(("query", "blackboard_keys"), py_blackboard_keys)
    print("全表黑板键并集：%d 个（所有技能 × 所有等级）" % len(keys))

    got = go_classify(keys)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0]["kind"] = "<mutated>"

    bad = 0
    kinds: dict[str, int] = {}
    variants = 0
    for k, g in zip(keys, got):
        #: ★ 期望值只能从这里来：默认档现问 Python，冻结档读冻的那份。
        e = G.expect(("classify", k), lambda k=k: py_classify_expect(k))
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
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
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
