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
    #: ⚠ **现数**：`len(SUITE)` 才是权威（本行与它必须相等，第 2 节会量）。
    #: 两条会话各 +1 时，「都改成 +1」必丢一次——所以这里是数出来的，不是算出来的。
    "suites": 25,          # 一 · 「二十五套判据」「二十五套守卫」
    #: ⚠ **不要把它跟 `suites` 当成同一个数**（2026-09-23）：两条命令各有两套判据
    #: 之后，「命令数」与「套数」就不再相等了 —— `sim` 上有「自造规格」（Go 两种
    #: 入参形式的差分）与「调用链」（Python 那条路还造不造规格）两套。
    #: 现数＝`len(set(COMMAND_OF.values()))`，**不是**算出来的。
    "commands": 24,        # 二 · 有判据的命令数（distinct 值）
    "gaps": 6,             # 三 · 缺口表的行数
    "resolve_callsites": 2,  # 出 loadout.go 之外调 ResolveLoadout 的地方
                             # （loadout 命令 ＋ specdeploys 的规格构造）
    #: ⚠ 从 1 改成 2（2026-09-23）：`mechspec.go:MechSpecBuild` 让这个具名代理
    #: 多命中一条。它是**真的**又一个造规格的入口（造 `mechanisms` ＋ `mech_config`
    #: 两个键），所以改的是**声明**——不把函数改名去躲开这个计数（那正是「让守卫
    #: 迁就措辞」）。数的是入口个数，不是「造齐 19 键的入口个数」。
    #: ⚠ 再从 2 改成 3（同日）：`buildspec.go:BuildSpecFull` 是**第三个**真入口
    #: （造齐 19 键）。★ 同一批里那条请求解析器**改了名**（`ParseBuildSpecQuery`
    #: → `ParseSpecRequest`）：它不含任何「造规格」的语义，只是因为名字里有
    #: `BuildSpec` 才被这个**具名代理**误命中——那是**代理的假阳性**，
    #: 按本仓纪律改自己的措辞（不是放宽代理）。
#: ⚠ 再从 3 改成 4（2026-09-23 同日，`sim` 自造规格那一批）：`simquery.go:BuildSimSpecFromQuery`
#: 是**第四个**真入口——它把「关卡＋名册＋计划」的查询形式造出一份 `Spec`（再交 `runSim`）。
#: ★ 同批里另一个含 `Spec` 的名字 `ClassifySimSpec` **没有**被数到，因为它不含
#: Build/From/Make/New——代理在那一处是准的，不需要改名。
    "spec_builders": 4,    # 四 · Go 侧「造规格」的入口：BuildSpecFull ＋ BuildSimSpecFromQuery ＋ MechSpecBuild ＋ BuildSpecPart
}

#: 判据套名 → Go 命令名。SUITE 的行里没有命令名，这一步只能显式登记。
COMMAND_OF = {
    "关卡": "load", "敌人": "enemies", "干员": "opstats", "范围": "range",
    "技能": "skill", "分类": "classify", "生命上限": "maxhp",
    "攻击间隔": "interval", "面板": "panel", "名册": "roster",
    "计划": "plan", "练度": "loadout", "关卡静态": "stageenv", "格表": "cells",
    "部分规格": "specgo", "费用天赋": "costbonus", "部署费用": "costof",
    "寻路": "path", "闸门": "unsupported", "出怪规格": "spawns",
    "机制规格": "mechspec", "干员规格": "operators", "单一入口": "buildspec",
    "自造规格": "sim",
    #: ★ 与上一行**同一条命令、不同的判据面**：上一行量 Go 那两种入参形式的差分，
    #: 这一行量 Python 那条调用链（还造不造规格、还跑不跑模拟器）。`COMMAND_OF`
    #: 允许多对一（这个字典是「套名 → 命令名」，不是单射），第 2 节查的是
    #: 「有没有哪条命令**没有任何**判据」，不是「命令与套名一一对应」。
    "调用链": "sim",
}

#: 有 Go 命令、但**有意**没有跨实现判据的（现在只剩一个）。
#: ⚠ 第一版把「Go 命令数」直接等于「判据套数」，于是这两个被当成漏登记，
#: 数出 14 ≠ 12 的假红。等式本身写错了，不是登记漏了。
#: ⚠ `sim` 从这一对里**移出**（2026-09-23）：它现在有判据了——「自造规格」那一套
#: 用**差分**判它（查询形式 ≡ 先 buildspec 再送规格），不需要另一个引擎来当权威。
#: ⇒ 下面第 2/3 节的「命令面减去有意无判据的」随之从 2 变成 1，本行必须同批改。
NON_JUDGED = ("ping",)

#: 有判据、但**并进别的套里**判的命令（不单列一行）。
#: `talentbonus` 是 `费用天赋` 那一套的第二部分：同一个函数、同一份权威，
#: 拆成两行只会让「一套判据」这个词变模糊。
#: `legs` 同理并进 `寻路`：两者同属**路线生产侧**，而 `legs` 的 `walk` 段
#: 就是靠 `ground_path` 一段段拼出来的（中间还要 `pop()` 去重）——
#: 拆成两行会让同一条路上出现两把尺子（见 `tools/check_stagepath_go.py` 文件头）。
#: `routeplans`（`eta.route_plans`）是这条链的**第三层、也是最上面那层**：
#: 它把前两层组装成 `_route_tables` 的形状，`spawns` 真正消费的是它。
#: 三层用同一份判据、同一套行使计数，仍然不单列。
EXTRA_JUDGED = ("talentbonus", "specdeploys", "legs", "routeplans")


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
    """Go 侧「造规格」的函数（**部分规格也算一个入口**）。

    判据是**具名的代理**：函数名同时含 Spec 与 Build/From/Make/New
    （那种形状才是「从别的输入造一份规格出来」）。
    代理会说谎的方式是有人换个名字写，所以这里把命中的行也印出来，不只看个数。

    ⚠ 它数的是**入口个数**，不是「造齐了 19 个键的入口个数」。这一栏**不表示目标的远近**：
    `specgo` 骨架覆盖 12 / 19 且不吃计划／名册；而 `buildspec`（单一入口）**造齐 19 键、
    输入就是「关卡＋名册＋计划」**，`BuildSimSpecFromQuery` 造的是同一种「全吃」的规格，
    只是入口从 `sim` 进来。要读远近请看 `main()` 印的那句与台账第二节。
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
        #: ★ **两个声明数各改一个**，而且要**各自**红：只改一个的话，另一条等式
        #: 「红得起来吗」就没人证过（本仓：没有反向守卫的绿是零信息量的绿）。
        #: 下面收尾处会点验红的是哪几条。
        declared["commands"] = declared["commands"] + 1

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
    #: ⚠ 这一条**以前写的是「命令数 − ping − EXTRA_JUDGED == 判据套数」**，
    #: 那条等式假定「一条命令 ↔ 一套判据」是**一一对应**。2026-09-23 加「调用链」
    #: 那一套时它红了：新套判的是 `sim` 的**另一个面**（Python 那条调用链还造不造
    #: 规格、还跑不跑模拟器），命令还是 `sim` —— 于是命令数不变而套数 +1，
    #: 数出 24 ≠ 25。
    #: ★ 处置照本文件自己立过的规矩（见 `NON_JUDGED` 上面那段）：**等式写错了就改
    #: 等式，不去改登记**。现在拆成两条各自成立的等式：
    #:   ① 每套都有一个**存在**的命令（上面那条 `missing_cmd == 0`）；
    #:   ② 有判据的命令数（distinct 值）== 声明的命令数；
    #:   ③ 还有一条兜底：**没有任何判据的命令**必须为零（下面那条 `stray`）——
    #:      这条才是原来想抓的东西（加了新命令却没加判据）。
    one("有判据的命令数（distinct 值）", len(set(COMMAND_OF.values())),
        declared["commands"])
    stray = sorted(set(cmds) - set(COMMAND_OF.values()) - set(NON_JUDGED)
                   - set(EXTRA_JUDGED))
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
    one("ResolveLoadout 的调用点（loadout ＋ 规格构造）", n_resolve,
        declared["resolve_callsites"])
    if resolve_where:
        print("      落点：%s" % "、".join(resolve_where))
    print()

    if mutate:
        #: 点验：**两条等式各自都红得起来**（只改一个数就红，证明不了另一个也守得住）。
        expect = ("判据套数", "有判据的命令数")
        hit = [e for e in expect if any(p.startswith(e) for p in problems)]
        print("      红起来的条目：%s" % " ／ ".join(
            p.split("：")[0] for p in problems) or "（无）")
        if bad and len(hit) == len(expect):
            print("反向守卫：改动台账声明的数 → 判红 —— 成立 ✓（%s 两条各自都红）"
                  % "、".join(expect))
            return 0
        print("反向守卫：不成立 ✗（%d 条预期要红的只红了 %d 条）"
              % (len(expect), len(hit)))
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
    #: ⚠ 这一句**改过**（2026-09-23，丙·第三十五批）：原文是「但它只造 19 个顶层键里的
    #: 12 个，且**不读计划／名册**」——那是 `specgo.go` 骨架的旧口径，`buildspec`
    #: （单一入口）落地后**已过期**。旧读数留着会让读者以为目标还差得远，
    #: 而真实状态是「入口有了、规格仍从 req.Spec 收」。
    print("    其中 `buildspec`（单一入口）能**造齐 19 个键**、输入是「关卡＋名册＋计划」；")
    print("    另两个（`specgo` 骨架 12 键、`mechspec` 2 键）各造一部分。")
    print("    `ResolveLoadout` 被 %d 处调用（loadout 命令 ＋ specdeploys 的规格构造）。"
          % n_resolve)
    print("    规格是从 req.Spec 收进来的（该字段在 main.go 出现 %d 次）。"
          % n_spec_in)
    print()
    print("  收口条件（三条全中才算达成，缺一不算）：")
    print("    ① Go 侧出现能造**齐 19 个键**、且输入是「关卡＋名册＋计划」的入口"
          "（**已有**：buildspec，判据「单一入口」）;")
    print("    ② 该入口有跨实现对拍判据，且登记进 SUITE（**已有**，见本脚本第 2 节）；")
    print("    ③ 台账第三节里「规格构造与闸门」那一行被移出，"
          "DECLARED['gaps'] 同批减一。★ 这一条**仍未做**：故上面的「未达成」照旧。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
