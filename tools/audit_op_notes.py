#!/usr/bin/env python3
"""已完成建模干员的 wiki 备注**逐条核查**（覆盖率视角，不做数值对账）。

## 干什么

把 `data/prts-notes.sqlite` 的 `fact` 表（**3247 条**：天赋效果 2268 / 技能描述 979）
逐条过一遍，对每条 fact：
  1. 找出它提到的**机制词**（关键词普查表，实测真的出现在语料里的那些）；
  2. 用 `FAMILIES` 那张**声明式**映射表查出"这个词在我们模型里落在哪"；
  3. 给出四档之一：

| 档 | 含义 |
|---|---|
| `LINKED`   | 声明了落点，且**落点验证通过**（DB 列存在 / Go 符号存在） |
| `BROKEN`   | 声明了落点，但**落点不存在** ⇒ **这是红档**，必须修表或修数据 |
| `UNMODELED`| 明确登记为"我们没有这个字段族"（不是漏填） |
| `PARSE`    | 这条 fact 里**没有任何普查词** ⇒ 需要人看（可能是新机制词） |

## 设计原则（与本仓既有工具一致）

**锚点是断言，本工具负责证伪它。** 与 `tools/dict_status.py` 同一套做法：
表里的每个落点都要能被独立验证——`operator_attr.atk` 要真在库里、
`rios-sim/fear.go::fearCells` 要真在源码里。所以"映射写错了"会**翻红**，
而不是安静地把覆盖率算高。

## ⚠ 本工具**不**做什么（免得被读成"已验证通过"）

* **不做数值对账**：fact 是散文（「部署费用-1」「攻击力提升至130%」绝大多数是**增量或倍率**），
  与面板绝对值**不可直接比**。硬做只会产出一堆"看起来对不上"的噪声。
  真正能做的那一小撮（fact 给绝对值的）留待单独一步。
* **不代表语义正确**：`LINKED` 只说明"我们**有这个字段族**"，
  **不说明**它的取值/口径与这条 fact 一致。
* 所以报表里 `LINKED` 的名字是"**有落点**"，不是"**已核对**"。

用法：
    python tools/audit_op_notes.py                 # 汇总
    python tools/audit_op_notes.py --only 阿 --top 12
    python tools/audit_op_notes.py --self-test     # 自证：三档各造一条，必须各归其位
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
NOTES_DB = ROOT / "data" / "prts-notes.sqlite"
AKDB = ROOT / "data" / "akdb.sqlite"

#: 机制词 -> (落点, 备注)。落点有两种形态：
#:   · `表.列`        —— 对着 `data/akdb.sqlite` 验证列存在；
#:   · `文件::符号`   —— 对着源码验证符号存在（与 dict_status.py 同款）。
#:   · `-`            —— 明确登记为"我们没有"（UNMODELED 档，不是漏填）。
FAMILIES: dict[str, tuple[str, str]] = {
    # ── 面板字段（对着 akdb 的真实列名，列名是我读过 schema 的，不是猜的）
    "攻击力": ("operator_attr.atk", "面板；技能/天赋里的倍率另在 blackboard"),
    "防御力": ("operator_attr.def", "面板"),
    "法术抗性": ("operator_attr.res", "面板"),
    "法抗": ("operator_attr.res", "面板（简写写法）"),
    "生命值": ("operator_attr.hp", "面板"),
    "攻击速度": ("operator_attr.attack_speed", "面板；总攻速链路见记忆 873c4e90"),
    "攻击间隔": ("operator_attr.base_attack_time", "面板"),
    "阻挡": ("operator_attr.block_cnt", "面板"),
    "部署费用": ("operator_attr.cost", "面板"),
    "再部署": ("operator_attr.respawn_time", "面板"),
    "移速": ("operator_attr.move_speed", "面板"),
    "技力": ("skill_level.sp_cost", "技能 SP（另有 init_sp / increment 三列）"),
    "初始": ("skill_level.init_sp", "技能初始 SP"),
    "持续": ("skill_level.duration", "技能时长"),
    # ── 机制层（对着 Go 源码，落点就是"那个符号"）
    "晕眩": ("rios-sim/control.go::flagStun", "锚到标志位本身"),
    "眩晕": ("rios-sim/control.go::flagStun", "同上（异体字写法，语料里两种都有）"),
    "停顿": ("rios-sim/sim.go::speedFor", "移速乘区 −80%；⚠ 目前**无守卫**"),
    "寒冷": ("rios-sim/sim.go::applyCold", "攻速 −30；再受一次变冻结；⚠ **零生产调用点**"),
    "冻结": ("rios-sim/control.go::flagFrozen", "另见 sim.go::applyFreeze 与冻结 −15 法抗"),
    "脆弱": ("rios-sim/fragile.go::fragileState", "同名取最高已实现；⚠ 零生产调用点"),
    "屏障": ("rios-sim/sim.go::take", "次数制护盾与屏障都走扣血入口 take"),
    "护盾": ("rios-sim/sim.go::take", "同上（层数护盾见记忆 914dc6d2）"),
    "溅射": ("rios-sim/sim.go::traitSplash", "特性溅射；形状判据见撼地者那一条"),
    "元素损伤": ("rios-sim/element.go::elementState", "统称；⚠ 零生产调用点"),
    "凋亡": ("rios-sim/element.go::elemDark", "元素损伤族"),
    "灼燃": ("rios-sim/element.go::elemFire", "元素损伤族"),
    "侵蚀": ("rios-sim/element.go::elemWater", "元素损伤族"),
    "神经": ("rios-sim/element.go::elemSanity", "元素损伤族"),
    # ── 明确登记为"我们没有"（不是漏填）
    "闪避": ("-", "**未建模**：Go 侧 `enemy.dodgeVs` 恒返回 0，干员侧没有闪避字段族"),
    "庇护": ("-", "**未建模**：减伤型庇护不在现模型里"),
    "冷却": ("-", "**未建模**：技能冷却另有口径，未建字段族"),
    "沉默": ("-", "**未建模**：它是异常效果 `SILENCED`，但 Go 侧没有对应标志位/实现"),
    "回复": ("-", "**未建模**：治疗量口径分散，无统一字段族（`治疗` 同）"),
    "治疗": ("-", "同上"),
}


def _columns(db: Path, table: str) -> set[str]:
    c = sqlite3.connect(db)
    try:
        return {r[1] for r in c.execute(f"pragma table_info({table})")}
    finally:
        c.close()


def _has_symbol(spec: str) -> bool:
    """`文件::符号` 落点是否存在（与 dict_status.py 同款验证）。"""
    path, _, sym = spec.partition("::")
    p = ROOT / path
    if not p.exists():
        return False
    txt = p.read_text(encoding="utf-8", errors="ignore")
    return re.search(rf"\b{re.escape(sym)}\b", txt) is not None


def verify_target(target: str) -> tuple[bool, str]:
    """验证一个落点是否真的存在。返回 (通过?, 说明)。"""
    if target == "-":
        return True, "登记为未建模"
    if "::" in target:
        ok = _has_symbol(target)
        return ok, "符号存在" if ok else f"符号找不到：{target}"
    table, _, col = target.partition(".")
    if not table or not col:
        return False, f"落点写法不认识：{target}"
    if not AKDB.exists():
        return False, f"{AKDB} 不存在"
    cols = _columns(AKDB, table)
    if not cols:
        return False, f"表不存在：{table}"
    return (col in cols), ("列存在" if col in cols else f"列找不到：{table}.{col}")


def keywords_in(text: str) -> list[str]:
    return [k for k in FAMILIES if k in text]


def classify(text: str) -> tuple[str, list[str], list[str]]:
    """返回 (档位, 命中词, 红档说明)。"""
    hits = keywords_in(text)
    if not hits:
        return "PARSE", [], []
    broken = []
    unmodeled = []
    for k in hits:
        target, _note = FAMILIES[k]
        if target == "-":
            unmodeled.append(k)
            continue
        ok, why = verify_target(target)
        if not ok:
            broken.append(f"{k}→{target}（{why}）")
    if broken:
        return "BROKEN", hits, broken
    if len(unmodeled) == len(hits):
        return "UNMODELED", hits, []
    return "LINKED", hits, []


def self_test() -> int:
    """自证：三档各造一条 fact，必须各归其位（判据红得起来吗）。"""
    cases = [
        ("攻击力提升至130%", "LINKED"),
        ("闪避+30", "UNMODELED"),
        ("这是一句没有任何机制词的描述文字而已", "PARSE"),
    ]
    bad = 0
    print("== 自证：每档都要能落到自己那一档 ==")
    for text, want in cases:
        got, hits, _ = classify(text)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '⛔'} 期望 {want}／得到 {got}  命中词={hits}  「{text[:24]}」")
    # 反向：故意把一条词的落点改成一个不存在的符号 ⇒ 必须翻红
    print("== 反向守卫：落点声明错时必须变红 ==")
    saved = FAMILIES["攻击力"]
    FAMILIES["攻击力"] = ("operator_attr.atk_nonexistent", "自证用")
    got, _, why = classify("攻击力提升至130%")
    FAMILIES["攻击力"] = saved
    ok = got == "BROKEN"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '⛔'} 期望 BROKEN／得到 {got}  {why}")
    return 1 if bad else 0


def _load_facts(only: str | None = None) -> list[sqlite3.Row]:
    """读 fact 表。`only` 按 char_id 或页面名子串过滤。"""
    if not NOTES_DB.exists():
        raise SystemExit(f"⛔ 找不到 {NOTES_DB}（本地工作库，不入仓库）")
    c = sqlite3.connect(NOTES_DB)
    c.row_factory = sqlite3.Row
    if only:
        return c.execute(
            "select char_id, kind, value from fact"
            " where char_id like ? or char_id in (select char_id from page where name like ?)",
            [f"%{only}%", f"%{only}%"]).fetchall()
    return c.execute("select char_id, kind, value from fact").fetchall()


def _force_utf8_stdout() -> None:
    """把 stdout/stderr 显式设成 UTF-8。

    ⚠ 实测 `python tools/audit_op_notes.py > out.txt`（Windows、未设 PYTHONIOENCODING）
    在打印 `⚠` 时 rc=1：`UnicodeEncodeError: 'gbk' codec can't encode character '\\u26a0'`。
    这不是表里有红项，是**编码**——两者在 rc 上同形，所以必须从工具内部消掉。
    口径（2026-09-19）：**凡打印非 ASCII 符号的工具，输出重定向时必须 rc=0。**
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except Exception:                            # noqa: BLE001  （非 TextIOWrapper 时跳过）
            pass


def main() -> int:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="干员 wiki 备注逐条核查（覆盖率视角）")
    ap.add_argument("--only", help="只看名字/char_id 含该子串的干员")
    ap.add_argument("--top", type=int, default=10, help="各档列出前 N 个关键词族")
    ap.add_argument("--self-test", action="store_true", help="自证三档可红")
    ap.add_argument("--dump-parse", metavar="PATH",
                    help="把 PARSE 那批（没有普查词的 fact）落盘成待核清单，供下一轮扩充普查表")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.dump_parse:
        # ⚠ 这是**生成物**：题源是本文件的 FAMILIES 表，改词表请改这里，别手改落盘文件
        #   （记忆 eff36235：生成物的问题改题源不手改正文）。
        # 为什么要落盘：它是下一轮的**输入**，只留在工具输出里丢了就要重跑。
        rows = _load_facts()
        # ★ 条数只留**一个来源**：这个列表。旧版表头写 len(parses)、stdout 写 `len(out) - 7`，
        #   而表头实为 10 行 ⇒ 同一个文件里"304 条"与"307 条待核"并存，**307 就是这么传出去的**
        #   （2026-09-19 实测复现：落盘文件 304 行、stdout 打印 307）。两个数字不许各说各话。
        parses = [r for r in rows if classify(r["value"])[0] == "PARSE"]
        head = [
            f"{args.dump_parse} 由 tools/audit_op_notes.py --dump-parse 生成；"
            "题源是本文件的 FAMILIES 表，请勿手改本文件。", "",
            "# PARSE 待核清单：这些 fact 里没有任何普查词", "",
            f"共 {len(parses)} 条。",
            "每一行请填两栏：**拟新增的普查词**与**落点**（DB 列 / Go 符号 / 或「不建模」）。",
            "填完把词并进 tools/audit_op_notes.py 的 FAMILIES，再重跑本工具。", "",
            # ⚠ 更正留痕——留着比抹掉值钱，下一个人不必重新推（PM 2026-09-19 裁定）。
            "⚠ **数量更正（2026-09-19）**：本条数曾以 **307** 对外传出，来源不是引用错误、"
            "而是**本工具 stdout 的计数式**（旧版 `len(out) - 7`，表头实为 10 行 ⇒ 恒定多算 3）。"
            "实测 **304 条**：数据行不含表头（`| char_` 匹配 305 行含表头），"
            "与四档加总 2834+109+304=3247 自洽。⇒ 已改成只认 `len(parses)`。", "",
            "| char_id | fact 正文 | 拟新增词（人填） | 落点（人填） |", "|---|---|---|---|"]
        out = list(head)
        for r in parses:
            txt = r["value"].replace("|", "／").replace("\n", " ")[:160]
            out.append(f"| {r['char_id']} | {txt} |  |  |")
        Path(args.dump_parse).write_text("\n".join(out) + "\n", encoding="utf-8")
        print(f"已写 {args.dump_parse}（{len(parses)} 条待核；表头 {len(head)} 行）")
        return 0

    if not NOTES_DB.exists():
        print(f"⛔ 找不到 {NOTES_DB}（本地工作库，不入仓库）", file=sys.stderr)
        return 2

    # 落点先整体验一遍：表写错了要在汇总里立刻看到，而不是散在每条 fact 上。
    print("== 落点验证（声明即断言） ==")
    bad_targets = []
    for k, (target, _n) in sorted(FAMILIES.items()):
        ok, why = verify_target(target)
        if not ok:
            bad_targets.append((k, target, why))
    print(f"  声明 {len(FAMILIES)} 个机制词，落点不成立 {len(bad_targets)} 个")
    for k, target, why in bad_targets:
        print(f"    ⛔ {k} → {target}：{why}")

    c = sqlite3.connect(NOTES_DB)
    c.row_factory = sqlite3.Row
    where, params = "", []
    if args.only:
        where = " where char_id like ? or char_id in (select char_id from page where name like ?)"
        params = [f"%{args.only}%", f"%{args.only}%"]
    rows = c.execute(f"select char_id, kind, value from fact{where}", params).fetchall()

    tiers: dict[str, int] = {"LINKED": 0, "UNMODELED": 0, "PARSE": 0, "BROKEN": 0}
    kw_hits: dict[str, int] = {}
    kw_un: dict[str, int] = {}
    parse_examples: list[tuple[str, str]] = []
    for r in rows:
        tier, hits, _why = classify(r["value"])
        tiers[tier] += 1
        for k in hits:
            kw_hits[k] = kw_hits.get(k, 0) + 1
            if FAMILIES[k][0] == "-":
                kw_un[k] = kw_un.get(k, 0) + 1
        if tier == "PARSE" and len(parse_examples) < 12:
            parse_examples.append((r["char_id"], r["value"][:90]))

    print()
    print(f"== 汇总（{len(rows)} 条 fact） ==")
    for t in ("LINKED", "UNMODELED", "PARSE", "BROKEN"):
        share = tiers[t] / len(rows) if rows else 0
        print(f"  {t:<10} {tiers[t]:>5}  {share:>6.1%}")
    print("  ⚠ LINKED 读作「**有这个字段族**」，不是「已核对」——本工具不做数值对账。")

    print()
    print(f"== 命中最多的机制词（前 {args.top}） ==")
    for k, n in sorted(kw_hits.items(), key=lambda x: -x[1])[: args.top]:
        target = FAMILIES[k][0]
        mark = "⚠ 未建模" if target == "-" else "有落点"
        print(f"  {k:<8} {n:>5}  {mark}  {target}")

    print()
    print("== 明确登记为「我们没有」的（按条数） ==")
    for k, n in sorted(kw_un.items(), key=lambda x: -x[1]):
        print(f"  {k:<8} {n:>5}  {FAMILIES[k][1]}")

    print()
    print("== PARSE：这条 fact 里没有任何普查词（需要人看） ==")
    for cid, txt in parse_examples:
        print(f"  [{cid}] {txt}")

    print()
    if bad_targets:
        print(f"⛔ 有 {len(bad_targets)} 个落点声明不成立——这是红档，先修表")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
