#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自读的技能元数据 vs Python 的 `SkillBook`。

## 比什么

状态机那一半的九个字段：`name / skill_type / duration_type / sp_type /
sp_cost / init_sp / increment / max_charge_time / duration / range_id`
（外加 `blackboard` 条数——数值那一半的原料，本轮只报个数不解析）。

## 覆盖面

**全表每个技能 × 最高级**（专精满级那一档）——不抽样。
「只查几个技能」的话，剩下那些读错了照样绿。

用法:
    python tools\\check_skill_go.py
    python tools\\check_skill_go.py --mutate
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

#: Go 键 → Python 属性（`SkillLevel` 的字段名）。
FIELDS = [
    ("name", "name"), ("skill_type", "skill_type"),
    ("duration_type", "duration_type"), ("sp_type", "sp_type"),
    ("sp_cost", "sp_cost"), ("init_sp", "init_sp"),
    ("increment", "increment"), ("max_charge_time", "max_charge"),
    ("duration", "duration"), ("range_id", "range_id"),
    #: 级号（0 起算）与**原样正文**；渲染过的 description 本轮未接。
    ("index", "index"), ("raw_description", "raw_description"),
]


def go_skills(queries: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "skill", "spec": queries}) + "\n"
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
    return resp["skills"]


def norm(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def main() -> int:
    from ak_tactic.operator import SkillBook
    book = SkillBook()

    #: 全表技能 × 最高级。`blackboard` 条数也拿来对——它是数值那一半的原料。
    ids = sorted(book.all_ids())
    if not ids:
        raise SystemExit("拿不到技能全表（SkillBook 的接口变了？）")
    queries = []
    for sid in ids:
        try:
            levels = book.levels(sid)
        except Exception:                                        # noqa: BLE001
            continue
        if not levels:
            continue
        queries.append({"skill_id": sid, "level": len(levels)})
    got = go_skills(queries)

    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0]["sp_cost"] = got[0]["sp_cost"] + 1

    bad = 0
    bb_keys = 0
    bb_dollar = 0
    hit = {k: 0 for k, _ in FIELDS}
    hit["duration_nonzero"] = 0
    hit["range_id_nonnull"] = 0
    for q, g in zip(queries, got):
        py = book.levels(q["skill_id"])[q["level"] - 1]
        out = []
        for gk, pk in FIELDS:
            a, b = norm(g.get(gk)), norm(getattr(py, pk, None))
            #: ⚠ `sp_type` 在原始数据里**不总是字符串**（`skchr_acspec_1` 是数字），
            #: Go 侧按宽松类型透传，两边都字符串化再比——**不把它压成 str 存起来**，
            #: 那样会丢掉「它本来是个数」这件事。
            if gk == "sp_type":
                a, b = str(a), str(b)
            if b not in (None, "", 0, 0.0, False):
                hit[gk] += 1
            if gk == "duration" and b:
                hit["duration_nonzero"] += 1
            if gk == "range_id" and b is not None:
                hit["range_id_nonnull"] += 1
            if a != b:
                out.append("%s：Go=%r Python=%r" % (gk, a, b))
        if out:
            bad += 1
            print("✗ %s L%d —— %d 处" % (q["skill_id"], q["level"], len(out)))
            for line in out[:6]:
                print("    " + line)
        #: ★ 黑板单独比：数值键 ＋ `$key` 两套都要（`skill.py:1758-1763` 的口径）。
        #: 只比数值键会让「字符串键整批丢掉」看不出来——而那正是召唤/装置那类
        #: 机制唯一的住处，丢了不报错、上层当「没这项机制」。
        gbb = {str(k): norm(v) for k, v in (g.get("blackboard") or {}).items()}
        pbb = {str(k): norm(v) for k, v in (getattr(py, "blackboard", None) or {}).items()}
        if gbb != pbb:
            bad += 1
            only_go = sorted(set(gbb) - set(pbb))[:6]
            only_py = sorted(set(pbb) - set(gbb))[:6]
            diff = [k for k in sorted(set(gbb) & set(pbb)) if gbb[k] != pbb[k]][:6]
            print("✗ %s L%d 黑板不一致（Go %d 键 / Python %d 键）；Go 多 %s；Python 多 %s；值不同 %s"
                  % (q["skill_id"], q["level"], len(gbb), len(pbb), only_go, only_py, diff))
        bb_keys += len(pbb)
        bb_dollar += sum(1 for k in pbb if k.startswith("$"))
    print()
    print("已比：状态机九字段 ＋ **完整黑板**（数值键 ＋ `$key` 两套）；"
          "共 %d 个技能（全表 × 最高级）" % len(queries))
    print("★ 黑板行使计数：共 %d 个键，其中 `$` 字符串键 **%d** 个（那套就是"
          "召唤/装置类机制唯一的住处）" % (bb_keys, bb_dollar))
    print("★ 行使计数（Python 侧非默认次数）：")
    for k, n in hit.items():
        print("    %-20s %d" % (k, n))
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    print("结论：%d / %d 个技能逐字段一致" % (len(queries) - bad, len(queries)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
