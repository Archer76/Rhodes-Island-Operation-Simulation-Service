#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自足收口量测：把「已经自足的部分」与「仍由 Python 供的部分」放在同一条命令里。

## 为什么要有它

台账 `docs/go-selfsufficiency.md` 是**手写文档**，它的数字不会自己更新。
一份自陈进度的文档最危险的失效方式不是写错，而是**悄悄过期**：某一层后来
真的接上了，而缺口表还写着「未接」，于是下一个人照着过期的清单去干活。

所以这份脚本不重复台账的散文，只做一件事：**把台账里的每个数拿回代码里
重新数一遍**，数不上就红。它自己不做跨实现对拍（那是那十二套判据的事），
它只对「文档说的」与「代码是的」是否同一件事。

## 它数什么

1. **入口齐备**：每个声明过的 Go 命令，在 `main.go` 里真有 `case`，
   对应的判据脚本真在盘上，且真在 `check_go_all.py` 的 `SUITE` 里。
   （「漏跑一套的症状是全绿，只是那份绿少了一块」——所以这里数的是三处
   同屏：命令、脚本、登记。）
2. **三处行数相等**：Go 命令数 ＝ 判据脚本数 ＝ 台账读数表的行数 ＝ 台账
   自己声明的套数。任何一个不等，说明有一边过期了。
3. **缺口件数**：台账第三节那张表数出来的行数，与它自己声明的件数比。
4. **规格的来源**：Go 侧**有没有**「从计划＋名册造规格」的入口。
   现在的答案是**没有**——`ResolveLoadout` 的调用点只有 `loadout` 命令那一处，
   而规格是从 `req.Spec` 收进来的。这一条是目标最后那半句的判据头。

## 退出码

* `0` —— 量测一致（**注意：这不等于目标达成**，见末尾的收口条件）；
* `1` —— 有一处对不上，逐条印出来。

用法:
    python tools\\closeout_selfsufficiency.py
    python tools\\closeout_selfsufficiency.py --mutate
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]

MAIN_GO = ROOT / "rios-sim" / "main.go"
SUITE_PY = ROOT / "tools" / "check_go_all.py"
LEDGER = ROOT / "docs" / "go-selfsufficiency.md"
GO_DIR = ROOT / "rios-sim"

#: 这份台账**自己声明**的数。改动它们必须与真实改动同批，否则本脚本会红。
DECLARED = {
    "suites": 16,          # 一 · 「十六套判据」「十六套守卫」
    "gaps": 6,             # 三 · 缺口表的行数
    "resolve_callsites": 1,  # 出 loadout.go 之外调 ResolveLoadout 的地方
    "spec_builders": 1,    # 四 · Go 侧「造规格」的入口：BuildSpecPart（部分规格）
}

#: 判据套名 → Go 命令名。SUITE 的行里没有命令名，这一步只能显式登记。
COMMAND_OF = {
    "关卡": "load", "敌人": "enemies", "干员": "opstats", "范围": "range",
    "技能": "skill", "分类": "classify", "生命上限": "maxhp",
    "攻击间隔": "interval", "面板": "panel", "名册": "roster",
    "计划": "plan", "练度": "loadout", "关卡静态": "stageenv", "格表": "cells",
    "部分规格": "specgo", "费用天赋": "costbonus",
}

#: 有 Go 命令、但**有意**没有跨实现判据的两个。
#: ⚠ 第一版把「Go 命令数」直接等于「判据套数」，于是这两个被当成漏登记，
#: 数出 14 ≠ 12 的假红。等式本身写错了，不是登记漏了。
NON_JUDGED = ("ping", "sim")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def go_commands() -> list[str]:
    return re.findall(r'^\s*case "([a-z_]+)":', read(MAIN_GO), re.M)


def suite_rows() -> list[tuple[str, str]]:
    return re.findall(r'^\s*\("([^"]+)",\s*"([^"]+)"',
                      read(SUITE_PY), re.M)


def table_rows(section: str, start: str, end: str) -> list[str]:
    """取某节里某张表的**数据行**。

    ⚠ 这里踩过一次：第一版只滤掉分隔行（`|---|---|`），于是**表头**
    `| 判据 | 取证面 | 读数 |` 被当成数据行，读数表数出 13 而真值是 12。
    现在表头与分隔行都去掉——「表格的行数」这个量在两种数法下差一，
    正是最容易被当成真差异的那种假红。
    """
    body = section.split(start, 1)[1].split(end, 1)[0]
    rows = []
    for line in body.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        if set(s) <= set("|-: "):
            continue
        rows.append(s)
    return rows[1:] if rows else rows   #: 第一条是表头


def ledger_counts() -> dict[str, list[str]]:
    text = read(LEDGER)
    return {
        "readings": table_rows(text, "### 当前读数", "## 二"),
        "gaps": table_rows(text, "## 三", "## 四"),
    }


def ruler_selftest() -> list[str]:
    """量尺自己的正负对照：不依赖仓库文件，就地造一张带表头的表。

    来历：第一版 `table_rows` 把表头当成数据行，读数表数出 13（真值 12）。
    那不是仓库的错，是尺子的错——所以尺子也要有一条不依赖被测对象的检查。
    """
    doc = ("### 当前读数\n| a | b |\n|---|---|\n| r1 | x |\n| r2 | y |\n## 二\n")
    return table_rows(doc, "### 当前读数", "## 二")


def resolve_callsites() -> tuple[int, list[str]]:
    """`ResolveLoadout(` 出现在哪些文件、几次（`loadout.go` 的定义处不算）。"""
    hits: list[str] = []
    for f in sorted(GO_DIR.glob("*.go")):
        if f.name == "loadout.go":
            continue
        n = read(f).count("ResolveLoadout(")
        hits.extend(["%s×%d" % (f.name, n)] * n)
    return len(hits), hits


def spec_entry_points() -> list[str]:
    """Go 侧「造规格」的函数。现在的答案是**没有**。

    判据是**具名的代理**：`rios-sim/` 里没有任何函数名同时含 Spec 与
    Build/From/Make（那种形状才是「从别的输入造一份规格出来」）。
    代理会说谎的方式是有人换个名字写，所以这里把命中的行也印出来，
    不只看个数。
    """
    pat = re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w*Spec\w*)\(", re.M)
    out = []
    for f in sorted(GO_DIR.glob("*.go")):
        for name in pat.findall(read(f)):
            if any(w in name for w in ("Build", "From", "Make", "New")):
                out.append("%s:%s" % (f.name, name))
    return out


def main() -> int:
    mutate = "--mutate" in sys.argv
    declared = dict(DECLARED)
    if mutate:
        declared["suites"] = declared["suites"] + 1

    cmds = go_commands()
    rows = suite_rows()
    counts = ledger_counts()
    n_readings = len(counts["readings"])
    n_gaps = len(counts["gaps"])
    n_resolve, resolve_where = resolve_callsites()
    spec_builders = spec_entry_points()
    n_spec_in = read(MAIN_GO).count("req.Spec")

    print("台账：%s" % LEDGER.relative_to(ROOT))
    print("命令面：%s" % MAIN_GO.relative_to(ROOT))
    print()

    bad = 0
    problems: list[str] = []

    def one(label: str, got, want) -> None:
        nonlocal bad
        ok = got == want
        if not ok:
            bad += 1
            problems.append("%s：实得 %r，台账声明 %r" % (label, got, want))
        print("  %s %-28s %s" % ("✓" if ok else "✗", label,
                                 got if ok else "%r ≠ %r" % (got, want)))

    print("一 · 入口齐备（命令 / 脚本 / 登记 三处同屏）")
    ruled = ruler_selftest()
    one("量尺自检：表头不算数据行", len(ruled), 2)
    if len(ruled) == 2 and not all(r.startswith("| r") for r in ruled):
        bad += 1
        problems.append("量尺自检：取到的不像数据行：%r" % ruled)
        print("      ✗ 取到的不像数据行：%r" % ruled)
    for name, script in rows:
        p = ROOT / script
        flagged = p.exists()
        print("  %s %-10s %-26s %s" % ("✓" if flagged else "✗", name,
                                       script, "在盘上" if flagged else "找不到"))
        if not flagged:
            bad += 1
            problems.append("判据脚本不存在：%s" % script)
    print()

    print("二 · 三处同屏（命令 ↔ 判据 ↔ 台账；一边过期就会在这里露出来）")
    missing_cmd = [n for n, _ in rows if COMMAND_OF.get(n) not in cmds]
    one("判据套数", len(rows), declared["suites"])
    one("台账读数表行数", n_readings, declared["suites"])
    one("判据套名都有命令映射", len(missing_cmd), 0)
    if missing_cmd:
        print("      没映射到的套：%s" % "、".join(missing_cmd))
    one("命令面减去有意无判据的两个", len(cmds) - len(NON_JUDGED), len(rows))
    stray = sorted(set(cmds) - set(COMMAND_OF.values()) - set(NON_JUDGED))
    one("既非判据命令也非 ping/sim 的余项", len(stray), 0)
    if stray:
        print("      余项：%s" % "、".join(stray))
    print()

    print("三 · 缺口件数")
    one("缺口表行数", n_gaps, declared["gaps"])
    print()

    print("四 · 规格的来源（目标最后那半句的判据头）")
    one("规格入口 req.Spec 出现次数（只收不造）", n_spec_in >= 1, True)
    one("Go 侧造规格的函数数（已产出的入口）", len(spec_builders),
        declared["spec_builders"])
    if spec_builders:
        for s in spec_builders:
            print("      命中：%s" % s)
    one("ResolveLoadout 的调用点（仅 loadout 命令）", n_resolve,
        declared["resolve_callsites"])
    if resolve_where:
        print("      落点：%s" % "、".join(resolve_where))
    print()

    if mutate:
        if bad:
            print("反向守卫：改动台账声明的一处数 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1

    if bad:
        print("结论：量测不一致，逐条如下 ——")
        for p in problems:
            print("  · %s" % p)
        print()
        print("（这是**文档过期**或**登记漏项**，不是自足与否的结论。）")
        return 1

    print("量测一致：命令面、判据面、台账三处的数对得上。")
    print()
    print("★ 目标状态：**未达成**")
    print("  已自足（每一层都有跨实现对拍判据）：%d 套" % declared["suites"])
    print("  未接（具名，见台账第三节）：%d 件" % declared["gaps"])
    print("  ★ 规格仍由 Python 送：Go 侧**有** %d 个造规格的入口（%s），"
          % (len(spec_builders), "、".join(spec_builders) or "无"))
    print("    但它只造 19 个顶层键里的 12 个，且**不读计划／名册**；")
    print("    `ResolveLoadout` 仍只被 loadout 命令调用 %d 处。" % n_resolve)
    print("    规格是从 req.Spec 收进来的（该字段在 main.go 出现 %d 次）。"
          % n_spec_in)
    print()
    print("  收口条件（三条全中才算达成，缺一不算）：")
    print("    ① Go 侧出现能造**齐 19 个键**、且输入是「关卡＋名册＋计划」的入口"
          "（现在是 12/19，且不吃计划／名册）；")
    print("    ② 该入口有跨实现对拍判据，且登记进 SUITE（本脚本的第 2 节会跟着变）；")
    print("    ③ 台账第三节里「规格构造与闸门」那一行被移出，"
          "DECLARED['gaps'] 同批减一。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
