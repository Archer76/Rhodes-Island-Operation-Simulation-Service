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

#: ② 特性那两条**只在正文里**的（黑板是空的）——同样是「规格键 → 运行期痕迹」。
#:
#: ⚠ 两条的痕迹都带了**判别条件**，不是「发生了就算」：
#:   · `TRAITAIR` 只在「选中的是飞行单位」**且**「范围里同时有地面候选」时打——
#:     只判「选中了飞行」在满屏飞行单位的关卡里会恒真，那是零信息量的绿。
#:   · `TRAITMULTI` 只在**一次出手真的命中 ≥2 个**时打——「她挡住了三个」不是见证。
TRAIT_MECHS = [
    ("air_priority", "TRAITAIR", "优先攻击空中单位"),
    ("attacks_all_blocked", "TRAITMULTI", "同时攻击阻挡的所有敌人"),
    #: ★ 这两条的出处是**天赋**正文（不是特性正文）——史都华德／安德切尔的黑板里
    #: 一个字都没写选目标，所以它们与上面两条同一个取证口（`talentText`）。
    ("prefer_highest_def", "TRAITDEF", "优先攻击防御力最高"),
    ("prefer_ranged", "TRAITRANGE", "优先攻击使用远程武器"),
    #: ★ 2026-09-25：特性「攻击附带停顿」（梓兰 凝滞师）。这条**不是选目标**，
    #: 是命中效果；判据词在特性黑板的 `sluggish`（**秒数**，减速比例是全局常数 80%）。
    ("slow_on_hit_sec", "TRAITSLOW", "攻击附带停顿"),
    #: ★ 2026-09-25：特性「可以进行远程攻击，但攻击力降低至 80%」（领主那一族，月见夜）。
    #: 判据是**目标有没有被她挡住**（博士裁定），不是格子几何。
    ("ranged_atk_scale", "TRAITRANGED", "远程攻击降攻"),
    #: ★ 2026-09-25：特性「击杀敌人后获得 N 点部署费用」（冲锋手那一族，翎羽）。
    ("kill_cost_on_kill", "TRAITKILLCOST", "击杀得费"),
]

#: ② 那两条在默认关卡上**行使不了**（`main_00-01` 一只飞行单位都没有、也挡不住两个），
#: 所以各配一层专属夹具。两处选择都**按证据**、不手挑：
#:
#:   · 关卡：`main_02-09` 是缓存里飞行单位最多的早期主线之一（52 项出怪里 36 只是飞行），
#:     `main_01-07` 是地面密集的样板关（41 项出怪、全地面）。
#:   · 站位：取该关**地面路线出现次数最多**的那一格（主路径的咽喉）。
#:     ⚠ 写死一个坐标（例如 [4,3]）会让下一个人问「为什么是它」而无从复算——
#:     实测 [4,3] 在 `main_01-07` 上根本不在任何路线格里，泡普卡**一次都没挡住过人**，
#:     于是那条机制的痕迹恒为 0，看起来像「没接」。
TRAIT_LEVELS = {
    "air_priority": "main_02-09",
    "attacks_all_blocked": "main_01-07",
    #: 这两条先在**同一批候选关**上试：史都华德（术师）要的是「范围内同时有防御力不同的
    #: 敌人」，安德切尔（狙击）要的是「范围内同时有使用远程武器的敌人」。
    #: ⚠ 与上面两条同一条纪律：关卡与站位都按证据取、不手挑坐标；实测读数为 0
    #: 就换关重试，并把「为什么是这一关」写进文档，不许挑到绿为止。
    "prefer_highest_def": "main_02-09",
    "prefer_ranged": "main_02-09",
    #: 梓兰那条与关卡无关（她**每次攻击命中**都挂停顿），用默认那关即可。
    "slow_on_hit_sec": "main_00-01",
    #: 月见夜那条要**一个她没挡住的靶子**（挡住了就算近战、不降攻），
    #: 所以挑一个地面连续来敌的关，站位仍按路线格依次试。
    "ranged_atk_scale": "main_01-07",
    #: 翎羽那条要**她自己打死人**，`main_00-01` 这种小关就够。
    "kill_cost_on_kill": "main_00-01",
}


def synth_ranged_probe(op: dict, level: str, cell: list[int]) -> int:
    """**合成夹具**：手造两个敌人（一个近战、一个使用远程武器）同局，专测那条优先规则。

    ★ 为什么必须造（而不是继续换关卡）：博士 2026-09-25 的指示是「你可以自己修改一个
    关卡，放一个近战和一个远程进行测试」。此前已经穷举过 5 个无飞行关卡的全部路线格
    （143 格）与 `main_02-09` 的 12 格，**一个行使时刻都没有**——那说明"自然发生的
    时刻"在这些关卡里不存在，而不是规则没接。

    判据（先说清，免得变成"造到绿为止"）：
      · **近战**那只走一段路（`progress` > 0），**远程武器**那只先站在原地等
        （`progress` = 0）；
      · 两只**同时**在干员范围内；
      · ⇒ 默认规则（嘲讽, 推进度）会选**近战**那只，而「优先攻击使用远程武器」
        这条规则会选**远程**那只。两者不同，那次选择才是这条规则的见证。

    返回 `TRAITRANGE` 的出现次数（0 = 合成夹具上都没行使 ⇒ 那才是真没接）。
    """
    b, _ = call([{"id": 1, "cmd": "buildspec", "level": level,
                  "spec": {"plan": {"stage": level, "deploys": [
                      {"operator": op["name"], "position": cell, "direction": "Left",
                       "skill": 0, "elite": ELITE, "level": LEVEL, "potential": POTENTIAL,
                       "module_level": 0}]},
                      "roster": [{"id": op["char_id"], "name": op["name"], "elite": ELITE,
                                  "level": LEVEL, "own": True, "potential": POTENTIAL,
                                  "rarity": 3}]}}])
    b = b[0]
    if not b.get("ok"):
        return -1
    spec = b["build_spec"]["spec"]
    spawns = spec.get("spawns") or []
    melee = next((s for s in spawns if s.get("apply_way") != "RANGED"), None)
    ranged = next((s for s in spawns if s.get("apply_way") == "RANGED"), None)
    if melee is None or ranged is None:
        return -1
    x, y = cell[0], cell[1]
    #: 干员朝左 ⇒ 范围在左侧（实测该位狙击的范围格是 x∈[cell−3, cell]、同一行含 y）。
    #:
    #: ⚠ **走完必须在原地停住**（walk 之后接一条 wait）：只给一条 walk 的话，
    #: 走完那一段就没腿了、敌人当场离场，而「离场」在 `pickTargets` 里是**被过滤掉**的
    #: ⇒ 那一刻范围内只剩远程那一只，默认规则与优先规则**选的是同一个人**，
    #: 于是痕迹恒为 0——那看起来与「规则没接」一模一样。第一版就是这么写的。
    #: ⚠ 第二版写成「远程那只先站着不动 ⇒ progress 更低」，**判据不成立**：
    #: `wait` 那一段的 `progress` **照样在涨**（与 `static` 自缚同一条口径），
    #: 两只一起涨 ⇒ 默认规则选的就是远程那一只 ⇒ 痕迹恒为 0。
    #: 真正能把两者的 `progress` 拉开的是**入场时刻**：让远程那只晚 3 秒进场，
    #: 那时近战那只已经走了两个多格。
    melee = dict(melee)
    ranged = dict(ranged)
    melee["time"] = 0.0
    #: ⚠ 近战那只**必须活着等到远程那只进场**：用原关卡的 HP 时它三秒就被打死了
    #: （实测 800 血、每轮约 338），而那一刻远程那只才刚出场 ⇒ 两只**从不同时在范围内**
    #: ⇒ 默认规则与优先规则选的是同一个人 ⇒ 痕迹恒为 0。
    #: 这是合成夹具的**构造参数**，不是判据——所以直接把它调到打不死。
    melee["hp"] = max(float(melee.get("hp") or 0), 20000.0)
    melee["legs"] = [{"kind": "walk", "points": [[x - 3, y], [x - 1, y]]},
                     {"kind": "wait", "seconds": 600.0, "points": [[x - 1, y]]}]
    ranged["time"] = 3.0
    ranged["legs"] = [{"kind": "wait", "seconds": 600.0, "points": [[x - 2, y]]}]
    spec = dict(spec)
    spec["spawns"] = [melee, ranged]
    _, err = call([{"id": 2, "cmd": "sim", "spec": spec}], trace=True)
    return trace_count(err, "TRAITRANGE")


def route_cells(level: str) -> list[list[int]]:
    """该关**地面路线**上出现过的格，按出现次数从多到少（复算：从出怪规格现读，不写坐标）。"""
    b, _ = call([{"id": 1, "cmd": "buildspec", "level": level, "spec": {}}])
    b = b[0]
    if not b.get("ok"):
        return []
    cnt: dict[tuple[int, int], int] = {}
    for s in b["build_spec"]["spec"].get("spawns") or []:
        if s.get("is_flying"):
            continue
        for leg in s.get("legs") or []:
            for pt in leg.get("points") or []:
                if isinstance(pt, list) and len(pt) >= 2:
                    cell = (int(round(pt[0])), int(round(pt[1])))
                    cnt[cell] = cnt.get(cell, 0) + 1
    ordered = sorted(cnt, key=lambda c: (-cnt[c], c))
    return [[c[0], c[1]] for c in ordered]


#: 一个机制最多试几格。★ 站位**不是判据**，它是**夹具构造**：试路线格只是把
#: 「这个时刻到底存不存在」找出来，不是在挑一个能变绿的读数——试遍全部仍为 0 的，
#: 工具会**把试过的格数一起印出来**（那才是可复核的读数）。
MAX_CELLS = 12


def trait_probe(op: dict, level: str, tag: str) -> tuple[list[int] | None, int, int]:
    """在指定关卡的路线格上按序试，返回 (命中的格, 该族痕迹次数, 试了几格)。"""
    tried = 0
    for cell in route_cells(level)[:MAX_CELLS]:
        tried += 1
        tr = _one_sim(op, level, cell)
        if tr is None:
            continue
        n = trace_count(tr, tag)
        if n > 0:
            return cell, n, tried
    return None, 0, tried


def _one_sim(op: dict, level: str, cell: list[int]) -> str | None:
    roster = [{"id": op["char_id"], "name": op["name"], "elite": ELITE, "level": LEVEL,
               "own": True, "potential": POTENTIAL, "rarity": 3}]
    plan = {"stage": level, "deploys": [
        {"operator": op["name"], "position": cell, "direction": "Left",
         "skill": 0, "elite": ELITE, "level": LEVEL, "potential": POTENTIAL,
         "module_level": 0}]}
    b, _ = call([{"id": 1, "cmd": "buildspec", "level": level,
                  "spec": {"plan": plan, "roster": roster}}])
    b = b[0]
    if not b.get("ok") or b["build_spec"].get("unsupported"):
        return None
    _, err = call([{"id": 2, "cmd": "sim", "spec": b["build_spec"]["spec"]}], trace=True)
    return err


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
    trait_pass: list[str] = []
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
        for key, tag, label in TALENT_MECHS + TRAIT_MECHS:
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

        #: ---- 第三趟：② 那两条**只在正文里**的特性，各配一个专属夹具 ----
        for key, tag, lbl in TRAIT_MECHS:
            if op0.get(key) is None:
                continue
            lv = TRAIT_LEVELS.get(key)
            if not lv:
                continue
            cell, n, tried = trait_probe(o, lv, tag)
            if cell is None and key == "prefer_ranged":
                #: 自然发生的时刻找不到 ⇒ 换**合成夹具**（博士 2026-09-25 指示）。
                sc = synth_ranged_probe(o, lv, [5, 3])
                if sc > 0:
                    trait_pass.append("%s（%s 的**合成**夹具：近战 + 远程各一只）：%s→%d"
                                      % (o["name"], lv, lbl, sc))
                    zero_exercise.pop("%s 的「%s」" % (o["name"], lbl), None)
                    continue
                trait_pass.append("%s（%s，路线格试过 %d + 合成夹具 %s）：%s→**0**"
                                  % (o["name"], lv, tried,
                                     "跑不动" if sc < 0 else "也是 0", lbl))
                zero_exercise["%s 的「%s」" % (o["name"], lbl)] = (
                    "专属夹具 %s 上试遍 %d 个路线格、**外加合成夹具**仍为 0" % (lv, tried))
                continue
            if cell is None:
                trait_pass.append("%s（%s，试过 %d 格）：%s→**0**"
                                  % (o["name"], lv, tried, lbl))
                zero_exercise["%s 的「%s」" % (o["name"], lbl)] = (
                    "专属夹具 %s 上试遍 %d 个路线格仍为 0" % (lv, tried))
                continue
            trait_pass.append("%s（%s @%s）：%s→%d" % (o["name"], lv, cell, lbl, n))
            zero_exercise.pop("%s 的「%s」" % (o["name"], lbl), None)
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
    print("三 · ② 特性那两条的专属夹具（关卡按证据选、站位现算＝该关地面路线最密的一格）")
    if trait_pass:
        for line in trait_pass:
            print("  · %s" % line)
    else:
        print("  （17 位里没有带这两条特性的）")
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
