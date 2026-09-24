#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""逐关**机制清单**（数据侧现算，不跑任何引擎）。

## 它答什么

「这一关引用了哪些机制」——**只列清单，不下「建了没有」的结论**。后者是另一件事
（运行期有没有被走到），由痕迹（`RIOS_TRACE=1` ＋ `tools/trace_kv.py`）回答。
两者必须分开：把清单当结论，就会把「有键但没实现」读成「有机制」。

## 四处来源（口径不同，**分栏报，不许相加**）

1. **敌人天赋黑板**：关卡 `enemyDbRefs` 引用的敌人 → `enemy_database.json` 的
   `talentBlackboard[].key`；
2. **敌方技能**：同一份数据里的 `skills[].prefabKey`；
3. **关卡机制层**：`mechanisms` 与 `mech_config` 那一族（田地／雪／装置）——
   数据侧读不到（它在规格里），所以这一栏由调用方另行回答，本工具只**留位**；
4. **关卡 `options` / `runes` / 预置卡**：生命点上限、初始费用、移速倍率、属性增益、
   功能禁用掩码…——它也是一族机制，而且最容易「算得出但没用上」。

干员侧（第 5 栏）**不在这里**：它属于「计划夹具 × akdb」那一面，见 `--ops`。

## 用法

    python tools\\level_mech_inventory.py main_00-01 main_00-02
    python tools\\level_mech_inventory.py --all-main          # 第 0～10 章 base 关卡
    python tools\\level_mech_inventory.py --all-main --json out\\mech_inv.json

★ 口径：`deploys[*].skill: 0` **不是「不用技能」**（博士 2026-09-24 判定）——
除一二星外，0 即玩家默认技能＝**技 1**。见 `docs/level-full-sim-ledger.md` §二。
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GD = ROOT / "data" / "gamedata"
AKDB = ROOT / "data" / "akdb.sqlite"
ENEMY_DB = GD / "map.ark-nights.com" / "levels" / "enemydata" / "enemy_database.json"
MAIN = re.compile(r"^main_\d\d-\d+$")


def load_index() -> dict:
    return json.loads((GD / "_level_index.json").read_text(encoding="utf-8"))


def load_enemies() -> dict:
    """`{Key: [档位条目, …]}`。整份读一次（约 2 万条），调用方缓存。"""
    blob = json.loads(ENEMY_DB.read_text(encoding="utf-8"))
    return {e.get("Key"): (e.get("Value") or []) for e in (blob.get("enemies") or [])}


def enemy_keys(by_key: dict, key: str) -> dict:
    """一只敌人**在数据里声明**的机制键：天赋黑板键 ＋ 技能 prefabKey。"""
    bb, sk = set(), set()
    for tier in by_key.get(key) or []:
        ed = (tier or {}).get("enemyData") or {}
        for b in (ed.get("talentBlackboard") or []):
            if isinstance(b, dict) and b.get("key"):
                bb.add(str(b["key"]))
        for s in (ed.get("skills") or []):
            if isinstance(s, dict) and s.get("prefabKey"):
                sk.add(str(s["prefabKey"]))
    return {"blackboard": sorted(bb), "skills": sorted(sk)}


def option_keys(raw: dict) -> list:
    """关卡 `options` / `runes` / 预置卡那一族的**键名**（值另说）。"""
    out = set()
    for blob in (raw.get("options"), raw.get("runes"), raw.get("hardRunes"),
                 raw.get("predefines"), raw.get("hardPredefines")):
        if isinstance(blob, dict):
            out |= set(blob)
        elif isinstance(blob, list):
            for it in blob:
                if isinstance(it, dict):
                    k = it.get("key") or it.get("id") or it.get("characterId")
                    if k:
                        out.add(str(k))
    return sorted(out)


def level_raw(idx: dict, lv: str) -> dict | None:
    e = idx.get(lv)
    if e is None:
        return None
    p = GD / "map.ark-nights.com" / "levels" / e["data_path"]
    if not p.is_file():
        return None
    return json.loads(p.read_text(encoding="utf-8-sig"))


def operator_mechanisms(conn, name: str) -> dict | None:
    """干员侧：特性正文 ＋ 天赋名 ＋ 技能 id（从 `akdb` 读，只读打开）。"""
    r = conn.execute("select * from operator where name = ?", (name,)).fetchone()
    if r is None:
        return None
    cid = r["char_id"]
    tal = [x[0] for x in conn.execute(
        "select distinct name from operator_talent where char_id = ? "
        "order by group_index, cand_index", (cid,))]
    #: 隐藏天赋的 `name` 是 NULL —— 换成可读的占位，**不许丢**（丢一条就是静默省略）。
    tal = [(t if t else "(隐藏天赋)") for t in tal]
    sk = [x[0] for x in conn.execute(
        "select skill_id from operator_skill where char_id = ?", (cid,))]
    return {"char_id": cid, "trait": r["trait_text"],
            "talents": [t for t in tal], "skills": sk}


def plan_fixture(lv: str) -> Path | None:
    """这一关有没有作业夹具（命名约定：`plan-main-00-01.json`）。"""
    p = ROOT / "fixtures" / ("plan-%s.json" % lv.replace("main_", "main-"))
    return p if p.is_file() else None


def main() -> int:
    ap = argparse.ArgumentParser(description="逐关机制清单（数据侧现算）")
    ap.add_argument("levels", nargs="*", help="关卡 id（缺省＝--all-main）")
    ap.add_argument("--all-main", action="store_true",
                    help="第 0～10 章的全部 base 关卡（不含 #f#）")
    ap.add_argument("--json", help="把清单写到这个文件（机器可读）")
    a = ap.parse_args()

    idx = load_index()
    levels = list(a.levels)
    if a.all_main or not levels:
        levels = sorted(k for k in idx if MAIN.match(k))
    if not levels:
        raise SystemExit("没给关卡，也没有 --all-main")

    by_key = load_enemies()
    conn = sqlite3.connect("file:%s?mode=ro" % AKDB.as_posix(), uri=True)
    conn.row_factory = sqlite3.Row
    rows = []
    for lv in levels:
        raw = level_raw(idx, lv)
        if raw is None:
            rows.append({"level": lv, "error": "关卡文件取不到"})
            continue
        refs = [r["id"] for r in (raw.get("enemyDbRefs") or [])
                if isinstance(r, dict) and r.get("id")]
        bb, sk = set(), set()
        for k in refs:
            m = enemy_keys(by_key, k)
            bb |= set(m["blackboard"])
            sk |= set(m["skills"])
        plan = plan_fixture(lv)
        ops = []
        if plan is not None:
            d = json.loads(plan.read_text(encoding="utf-8"))
            for dp in (d.get("deploys") or []):
                om = operator_mechanisms(conn, dp.get("operator"))
                ops.append({"name": dp.get("operator"), "skill": dp.get("skill"),
                            "mech": om})
        rows.append({
            "level": lv,
            "enemies": refs,
            "enemy_blackboard_keys": sorted(bb),
            "enemy_skills": sorted(sk),
            "option_keys": option_keys(raw),
            "plan": plan.name if plan else None,
            "operators": ops,
        })

    for r in rows:
        if "error" in r:
            print("%-14s ✗ %s" % (r["level"], r["error"]))
            continue
        print("%-14s 敌人 %-2d／黑板键 %-3d／敌方技能 %-3d／选项键 %-3d／%s"
              % (r["level"], len(r["enemies"]), len(r["enemy_blackboard_keys"]),
                 len(r["enemy_skills"]), len(r["option_keys"]),
                 ("夹具 " + r["plan"]) if r["plan"] else "无夹具"))
        for o in r["operators"]:
            m = o["mech"]
            if m is None:
                print("       · %s：akdb 里查不到" % o["name"])
                continue
            print("       · %s（skill=%s → 技 %d）：特性「%s」；天赋 %s；技能 %s"
                  % (o["name"], o["skill"], (int(o["skill"]) or 1),
                     m["trait"], "、".join(m["talents"]) or "（无）",
                     "、".join(m["skills"]) or "（无）"))
    print()
    print("共 %d 关；★ 清单 ≠ 结论：有键不等于那机制被模拟，"
          "「有没有被走到」要另一条路（RIOS_TRACE ＋ tools/trace_kv.py）。" % len(rows))
    if a.json:
        Path(a.json).write_text(json.dumps(rows, ensure_ascii=False, indent=1),
                                encoding="utf-8")
        print("已写 %s" % a.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
