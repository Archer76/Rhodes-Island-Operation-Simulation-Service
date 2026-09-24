#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三星干员的**逐位行使见证**：技能绑没绑上、运行期有没有真开、active 快照是什么。

## 它答什么（博士 2026-09-24 的验收标准）

对 17 位玩家库存三星干员（`rarity=3 and is_operator=1` 减 5 位预备干员）逐位问三件事：

  ① **绑上了吗**：`operators[0].skill` 非空？（`skillbind.go` 那条链走通没有）
  ② **真开了吗**：`RIOS_TRACE=1` 跑一遍，`SKILL` 痕迹出现几次
     ——这是**运行期**证据，不是「键非空」；
  ③ **快照是什么**：`active` 那几个量，与基准面板并排，人一眼能看出技能有没有改数。

★ 为什么用**内联**的计划与名册而不是往 `fixtures/` 里加文件：
`fixtures/*.json` 里的计划是**别的判据的夹具集**（`check_specgo_go.real_specs()` 那一族按
`deploys` 键扫描目录），加一份进去会**改变那些判据的对象集**、逼它们全体重录基线。
内联传参不落盘，谁都影响不到。

## 用法

    python tools\\three_star_check.py            # 全部 17 位
    python tools\\three_star_check.py --level main_00-01
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
AKDB = ROOT / "data" / "akdb.sqlite"

#: 5 位预备干员 —— **不在本次范围**（博士：只管玩家干员库存里的那些）。
RESERVE = {"char_504_rguard", "char_505_rcast", "char_506_rmedic",
           "char_507_rsnipe", "char_514_rdfend"}

#: 三星的满配（3★ 最高精一满级）。
ELITE, LEVEL, POTENTIAL = 1, 55, 6


def three_stars() -> list[dict]:
    c = sqlite3.connect("file:%s?mode=ro" % AKDB.as_posix(), uri=True)
    c.row_factory = sqlite3.Row
    out = []
    for r in c.execute("select char_id, name, profession_cn from operator "
                       "where rarity = 3 and is_operator = 1 order by char_id"):
        d = dict(r)
        if d["char_id"] not in RESERVE:
            out.append(d)
    return out


def call(reqs: list[dict], trace: bool = False) -> tuple[list[dict], str]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    if trace:
        env["RIOS_TRACE"] = "1"
    else:
        env.pop("RIOS_TRACE", None)
    p = subprocess.run([GO_BIN], input=("\n".join(json.dumps(r) for r in reqs) + "\n")
                       .encode("utf-8"), stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:300]))
    out = [json.loads(x) for x in p.stdout.decode("utf-8", "replace").strip().splitlines()]
    return out, p.stderr.decode("utf-8", "replace")


def main() -> int:
    ap = argparse.ArgumentParser(description="三星干员逐位行使见证")
    ap.add_argument("--level", default="main_00-01")
    a = ap.parse_args()

    ops = three_stars()
    print("对象：%d 位玩家库存三星干员（已排除 5 位预备干员）；关卡 %s" % (len(ops), a.level))
    print("仪器：%s" % GO_BIN)
    print()
    hdr = ("%-18s %-8s %-6s %-7s %-9s %s"
           % ("干员", "技能槽", "绑上", "SKILL", "active.atk", "未识别键"))
    print(hdr)
    print("-" * len(hdr))
    bad = 0
    for o in ops:
        roster = [{"id": o["char_id"], "name": o["name"], "elite": ELITE,
                   "level": LEVEL, "own": True, "potential": POTENTIAL, "rarity": 3}]
        plan = {"stage": a.level, "deploys": [
            {"operator": o["name"], "position": [4, 3], "direction": "Left",
             "skill": 0, "elite": ELITE, "level": LEVEL, "potential": POTENTIAL,
             "module_level": 0}]}
        body = {"plan": plan, "roster": roster}
        b, _ = call([{"id": 1, "cmd": "buildspec", "level": a.level, "spec": body}])
        b = b[0]
        if not b.get("ok"):
            print("%-18s buildspec 失败：%s" % (o["name"], str(b.get("error"))[:60]))
            bad += 1
            continue
        spec = b["build_spec"]["spec"]
        op0 = (spec.get("operators") or [{}])[0]
        sk = op0.get("skill")
        act = op0.get("active") or {}
        r, err = call([{"id": 2, "cmd": "sim", "spec": spec}], trace=True)
        n_skill = len(re.findall(r"(?m)^SKILL ", err))
        unknown = b["build_spec"].get("skill_unknown_keys") or []
        print("%-18s %-8s %-6s %-7s %-9s %s"
              % (o["name"], ("有" if sk else "无"),
                 "✓" if sk else "✗", n_skill,
                 ("%.0f" % act["atk"]) if act else "—",
                 "、".join(unknown) if unknown else "（无）"))
        if not sk:
            bad += 1
    print()
    print("⇒ 绑定失败 %d 位（有技能槽却没绑上）" % bad)
    print("★ 判据口径：`SKILL` 是**运行期痕迹**（每开一次技能一行），不是「键非空」。")
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
