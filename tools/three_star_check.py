#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""三星干员的**逐位行使见证**：技能绑没绑上、运行期有没有真开、天赋的非面板效果有没有真行使。

## 它答什么（博士 2026-09-24 的验收标准）

对 17 位玩家库存三星干员（`rarity=3 and is_operator=1` 减 5 位预备干员）逐位问四件事：

  ① **绑上了吗**：`operators[0].skill` 非空？（`skillbind.go` 那条链走通没有）
  ② **真开了吗**：`RIOS_TRACE=1` 跑一遍，`SKILL` 痕迹出现几次
     ——这是**运行期**证据，不是「键非空」；
  ③ **快照是什么**：`active` 那几个量，与基准面板并排，人一眼能看出技能有没有改数；
  ④ **天赋的非面板效果**（`talenteffects.go`，2026-09-25 加）：规格里送了哪几项
     （`talent_deploy_sp` / `talent_proc_factor` / `talent_extra_heal_prob` /
     `talent_dodge_on_heal`），以及它们各自在**运行期**被行使了几次
     （`TALSP` / `TALPROC` / `TALXHEAL` / `TALDODGE` 四族痕迹）。

★ 为什么用**内联**的计划与名册而不是往 `fixtures/` 里加文件：
`fixtures/*.json` 里的计划是**别的判据的夹具集**（`check_specgo_go.real_specs()` 那一族按
`deploys` 键扫描目录），加一份进去会**改变那些判据的对象集**、逼它们全体重录基线。
内联传参不落盘，谁都影响不到。

★ **「送出了但零行使」单列一栏，不并进红**：四位医疗/辅助的机制要么要有队友掉血
（`TALXHEAL` / `TALDODGE`），要么要有敌人进范围（`TALPROC`），在短关卡里零行使是
**正常的**——把并成红会造一个恒假红，而恒假红等于没有判据。所以它印出来、计数，
由人（或 `--level` 换一关）去解释。**零行使的绿是零信息量的绿**这句话说的是
「不许把零行使当通过」，不是说「零行使就是错」。

## 用法

    python tools\\three_star_check.py                     # 全部 17 位，默认关卡
    python tools\\three_star_check.py --level hsex8_max   # 换一关（长局才行使得了治疗）
    python tools\\three_star_check.py --require-exercise   # 送出了却零行使 ⇒ rc=1
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
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

#: 天赋非面板效果的**规格键 → 运行期痕迹**对照。
#:
#: ★ 为什么必须成对写：只报「规格里送了」是本仓明令不许的那种假见证
#: （`键非空` ≠ 行使过）。右边那一族才是运行期计数。
TALENT_MECHS = [
    ("talent_deploy_sp", "TALSP", "部署给技力"),
    ("talent_proc_factor", "TALPROC", "概率强化攻击"),
    ("talent_extra_heal_prob", "TALXHEAL", "附加治疗"),
    ("talent_dodge_on_heal", "TALDODGE", "治疗授闪避"),
]


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


def trace_count(err: str, tag: str) -> int:
    """数一个痕迹族出现了几次。**锚在行首**：`TALSP` 是 `TALPROC` 的前缀，
    不锚行首会让两者互相计入（本仓记过好几回这种"尺子本身"造成的假读数）。"""
    return len(re.findall(r"(?m)^%s " % re.escape(tag), err))


#: 第二趟用的队友：一名**挡在前面、会掉血**的重装（卡缇，三星，同在本次范围内）。
#: 挑它的理由只有一条：医疗的天赋要在「有病人」时才行使得了，而单人格局里
#: `pickHeals` 的池子是空的（医疗自己满血）。队友是谁不影响被测的那位。
PARTNER_ID, PARTNER_NAME = "char_209_ardign", "卡缇"
#: 队友站位与朝向（挡在前排、朝左迎敌）；医疗站在它身后一格。
PARTNER_CELL, HEALER_CELL = [4, 3], [5, 3]


def pair_probe(op: dict, level: str) -> str | None:
    """带一名会掉血的队友跑一趟，返回 trace 文本（跑不动就返回 None）。"""
    roster = [
        {"id": op["char_id"], "name": op["name"], "elite": ELITE, "level": LEVEL,
         "own": True, "potential": POTENTIAL, "rarity": 3},
        {"id": PARTNER_ID, "name": PARTNER_NAME, "elite": ELITE, "level": LEVEL,
         "own": True, "potential": 6, "rarity": 3},
    ]
    plan = {"stage": level, "deploys": [
        {"operator": PARTNER_NAME, "position": PARTNER_CELL, "direction": "Left",
         "skill": 0, "elite": ELITE, "level": LEVEL, "potential": 6, "module_level": 0},
        {"operator": op["name"], "position": HEALER_CELL, "direction": "Left",
         "skill": 0, "elite": ELITE, "level": LEVEL, "potential": POTENTIAL,
         "module_level": 0},
    ]}
    body = {"plan": plan, "roster": roster}
    b, _ = call([{"id": 1, "cmd": "buildspec", "level": level, "spec": body}])
    b = b[0]
    if not b.get("ok") or b["build_spec"].get("unsupported"):
        return None
    _, err = call([{"id": 2, "cmd": "sim", "spec": b["build_spec"]["spec"]}], trace=True)
    return err


def main() -> int:
    ap = argparse.ArgumentParser(description="三星干员逐位行使见证")
    ap.add_argument("--level", default="main_00-01")
    ap.add_argument("--pair-level", default="main_01-07",
                    help="第二趟（带一名会掉血的队友）用的关卡")
    ap.add_argument("--require-exercise", action="store_true",
                    help="「规格里送了、运行期零行使」也判 rc=1（默认只印不判）")
    a = ap.parse_args()

    ops = three_stars()
    print("对象：%d 位玩家库存三星干员（已排除 5 位预备干员）；主关卡 %s"
          % (len(ops), a.level))
    print("仪器：%s" % GO_BIN)
    print()
    hdr = ("%-18s %-6s %-6s %-7s %-9s %-24s %s"
           % ("干员", "技能槽", "绑上", "SKILL", "active.atk", "天赋效果（送了→行使）", "未识别键"))
    print(hdr)
    print("-" * len(hdr))
    bad = 0
    #: 键＝「某位干员的某一条机制」，值＝为什么它还零行使（换关卡跑通了就删掉）。
    #: ★ 用 dict 而不是 list：两位干员可能带同一条机制，逐条删时 list 会删错那一条。
    zero_exercise: dict[str, str] = {}
    paired: list[str] = []
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
        _, err = call([{"id": 2, "cmd": "sim", "spec": spec}], trace=True)
        n_skill = trace_count(err, "SKILL")

        lines = []
        heal_family: list[tuple[str, str, str]] = []
        for key, tag, label in TALENT_MECHS:
            if op0.get(key) is None:
                continue
            n = trace_count(err, tag)
            lines.append("%s→%d" % (label, n))
            if key in ("talent_extra_heal_prob", "talent_dodge_on_heal"):
                heal_family.append((key, tag, label))
            if n == 0:
                zero_exercise["%s 的「%s」" % (o["name"], label)] = (
                    "主关卡 %s 零行使" % a.level)
        unknown = b["build_spec"].get("skill_unknown_keys") or []
        t_unknown = b["build_spec"].get("talent_unknown_keys") or []
        print("%-18s %-6s %-6s %-7s %-9s %-24s %s"
              % (o["name"], ("有" if sk else "无"),
                 "✓" if sk else "✗", n_skill,
                 ("%.0f" % act["atk"]) if act else "—",
                 "、".join(lines) if lines else "（无）",
                 "、".join(unknown + t_unknown) if (unknown or t_unknown) else "（无）"))
        if not sk:
            bad += 1

        #: ---- 第二趟：治疗那一族要有**会掉血的队友**才行使得了 ----
        #:
        #: 单人格局里 `pickHeals` 的池子只有医疗自己一个人，而它满血 ⇒ 池子为空
        #: ⇒ 连出手都不会出手。所以「零行使」在那一趟里是**夹具的性质**，不是机制的问题。
        #: 这一趟带一名挡在前面的重装，让医疗真的有病人可治。
        if heal_family:
            pair = pair_probe(o, a.pair_level)
            if pair is None:
                paired.append("%s：第二趟跑不动（%s）" % (o["name"], a.pair_level))
            else:
                fired = []
                for key, tag, lbl in heal_family:
                    n = trace_count(pair, tag)
                    fired.append("%s→%d" % (lbl, n))
                    k = "%s 的「%s」" % (o["name"], lbl)
                    if n > 0:
                        zero_exercise.pop(k, None)
                    else:
                        zero_exercise[k] = ("两趟（%s 与 %s）都零行使"
                                            % (a.level, a.pair_level))
                paired.append("%s（%s 带 %s）：%s"
                              % (o["name"], a.pair_level, PARTNER_NAME, "、".join(fired)))
    print()
    print("⇒ 绑定失败 %d 位（有技能槽却没绑上）" % bad)
    print("★ 判据口径：`SKILL` 与四个 `TAL*` 都是**运行期痕迹**，不是「键非空」。")
    print()
    print("二 · 治疗那一族的两趟见证（第二趟：%s ＋ 队友 %s）"
          % (a.pair_level, PARTNER_NAME))
    if paired:
        for line in paired:
            print("  · %s" % line)
    else:
        print("  （17 位里没有带治疗族天赋的）")
    print()
    if zero_exercise:
        print("⇒ 送出了但**零行使** %d 处（要解释，不并进红）：%s"
              % (len(zero_exercise),
                 "；".join("%s（%s）" % (k, v) for k, v in zero_exercise.items())))
    else:
        print("⇒ 送出了但零行使：0 处（送出的每一项都至少行使过一次）")
    if a.require_exercise and zero_exercise:
        return 1
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
