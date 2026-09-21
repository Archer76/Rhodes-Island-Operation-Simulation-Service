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
    #: ★ 渲染后的正文：占位符代入 ＋ 标签剥掉 ＋ 两种换行还原。
    #: 它是描述驱动机制（剑气/真伤/连击数）唯一的出处。
    ("description", "description"),
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
    ids = sorted(book.all_ids())
    if not ids:
        raise SystemExit("拿不到技能全表（SkillBook 的接口变了？）")

    #: ★ **全等级**，不只最高级。第一版每个技能只查最高级（1810 次）——那是
    #: **抽样**：等级之间的 spCost/initSp/increment/duration 与黑板都在变，
    #: 只查一级的话剩下那几级读错了照样绿。
    queries = []
    for sid in ids:
        try:
            levels = book.levels(sid)
        except Exception:                                        # noqa: BLE001
            continue
        for lv in range(1, len(levels) + 1):
            queries.append({"skill_id": sid, "level": lv})
    got = go_skills(queries)

    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0]["sp_cost"] = got[0]["sp_cost"] + 1

    bad = 0
    bb_keys = 0
    bb_dollar = 0
    eff_total = 0
    eff_other = 0
    eff_buffs = 0
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
        #: 效果对象：五个箱子 ＋ 两个计数 ＋ 演出参数 ＋ 击杀叠层上限。
        #: ★ 期望值从 Python 的 `effects` 直接取——不自己重写一遍口径。
        #: ⚠ 上一轮这里红成 11012/11012，逐条只有 `effects_total：Go=None`
        #: ——Go 已把效果对象改成**嵌套字段** `effects:{eff_*}`，而这里仍按
        #: 扁平名取。**红的是尺子**，本轮把它重写。
        pe = getattr(py, "effects", None)
        ge = g.get("effects") or {}
        pairs = [
            ("eff_total", "total"), ("eff_classified", "classified"),
            ("eff_buffs", "buffs"), ("eff_units", "units"),
            ("eff_damage", "damage"), ("eff_control", "control"),
            ("eff_variants", "variants"), ("eff_variant_units", "variant_units"),
            ("eff_other", "other"), ("eff_kill_max_stack", "kill_max_stack"),
            ("eff_airborne_height", "airborne_height"),
            ("eff_airborne_rise", "airborne_rise"),
            ("eff_airborne_fall", "airborne_fall"),
        ]

        def _normbox(v):
            """一箱数值：dict-of-值 或 dict-of-dict，两种都要归一。"""
            if not isinstance(v, dict):
                return norm(v if v is not None else 0)
            return {str(k): ({str(kk): norm(vv) for kk, vv in x.items()}
                             if isinstance(x, dict) else norm(x))
                    for k, x in v.items()}

        for gk, pk in pairs:
            a, b = ge.get(gk), getattr(pe, pk, None)
            a, b = _normbox(a), _normbox(b)
            if a != b:
                out.append("%s：Go=%r Python=%r" % (gk, a, b))
            if a and gk in ("eff_buffs", "eff_damage", "eff_control", "eff_variants"):
                eff_buffs += 1
        eff_total += getattr(pe, "total", 0)
        eff_other += len(getattr(pe, "other", {}) or {})
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
          "共 %d 个「技能×等级」（全表 × **每一级**，不是只查最高级）" % len(queries))
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
