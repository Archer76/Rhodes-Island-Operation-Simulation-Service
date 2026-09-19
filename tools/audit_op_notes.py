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
    # ── ★ 修账（2026-09-20）：这三条原登记为 `-`，实为**错账**——两侧都已实现。
    #    改法是「给出真落点」，**不是「删掉这一行」**：词表要保留，
    #    因为它仍要参与核对（删了就变成"这个词我们不看了"，那是把账做平不是把账做对）。
    "闪避": ("rios-sim/skill.go::dodgeVs",
             "**已建模**：干员侧闪避比例入口，消费点 `sim.go:1319`。"
             "⚠ 敌人侧 `sim.go:239 enemy.dodgeVs` 恒 0，**且与原版同值**——"
             "是「两边一致的零」，**不是「零调用点」**。"
             "锚点与 `tools/coverage_table.py` 一致（PM 2026-09-20 裁定的那个锚）"),
    "治疗": ("rios-sim/sim.go::heal",
             "**已建模**：治疗量入口 `operator.heal`（Python 侧对应 "
             "`ak_tactic/battle/unit.py::heal`）；技能治疗倍率另走 `Heals` / `heal_scale` "
             "一路，见 `tools/gate_inventory.py`"),
    "回复": ("rios-sim/sim.go::heal",
             "**同上**：语料里 `回复` 与 `治疗` 是同一件事的两种写法"
             "（同 `晕眩`／`眩晕` 的先例，两条指向同一个落点）"),
    # ── 明确登记为"我们没有"（不是漏填）
    "庇护": ("-", "**未建模**：减伤型庇护不在现模型里"),
    "冷却": ("-", "**未建模**：技能冷却另有口径，未建字段族"),
    "沉默": ("-", "**未建模**：它是异常效果 `SILENCED`，但 Go 侧没有对应标志位/实现"),
}

#: 2026-09-20 修账时逐条对过的 6 个词（**原 `-` 档的全集**）。
#:
#: 留在这里，是为了让「这 6 条现在各在哪一档」**随时可复现**，
#: 而不是只活在某一次汇报里（`--absent` 就打印它）。
ABSENT_LEDGER: tuple[str, ...] = ("闪避", "庇护", "冷却", "沉默", "回复", "治疗")

#: `-` 档（登记为"我们没有这个字段族"）的**反证锚**。
#:
#: ## 为什么必须有它
#:
#: `-` 曾经是四档里**唯一一个不需要证据就能通过的档**：旧版 `verify_target("-")`
#: 直接 `return True, "登记为未建模"`。于是"我们**没做**"与"我们**做了却没登记**"
#: 被压成了同一个值——而后者**无处安放**，只能被读成前者。
#: 2026-09-20 实测：该档 6 条里 **3 条是错账**（闪避／治疗／回复 其实两侧都已实现），
#: 且因为这一档不会翻红，**错了也没人知道**。
#: ★ **同日已修**：这三条搬去真落点（见 `FAMILIES`），本表现在只剩 3 条。
#: **留下来的 3 条不是"没查过"，是"查过、反证锚都没命中"**——两者的区别写在这里，
#: 免得下一个读的人以为这里少了一半。
#:
#: ## 口径
#:
#: 每条形如 `(文件, 必须不存在的符号, 这条声明凭什么这么说)`：
#:
#: * 符号在文件里**被找到了** ⇒ 声明被证伪 ⇒ **BAD**（"表说没有，可是找到了"）；
#: * 载体文件不在 ⇒ **UNKNOWN**（不含糊地当通过）；
#: * 都没找到 ⇒ 声明**还活着**——⚠ 这只是"没被证伪"，**不等于已证实**。
#:
#: 没登记反证锚的 `-` 条目**直接判 BAD**：`不可证伪`本身就是要报出来的病。
ABSENT_ANCHORS: dict[str, tuple[tuple[str, str, str], ...]] = {
    # ★ 闪避／治疗／回复 的锚**已随修账移除**：它们是错账（反证锚命中过 ⇒ 声明被证伪），
    #   现在搬去 `FAMILIES` 的真落点。**移除本身就是那笔错账的记录**——
    #   若哪天有人想把它们搬回来，先解释为什么 `dodgeVs` / `heal` 不存在了。
    "庇护": (("ak_tactic/battle/sim.py", "庇护",
              "原声明：减伤型庇护不在现模型里"),),
    "沉默": (("rios-sim/control.go", "Silence",
              "原声明：Go 侧没有对应标志位（`SILENCED` 异常效果）"),),
    "冷却": (("ak_tactic/operator/skill.py", "cooldown",
              "原声明：技能冷却另有口径，未建字段族"),),
}

#: 落点验证的**三态**。⚠ 不许把 UNKNOWN 并进 OK 或 BAD：
#: "验了成立"/"验了不成立"/"**根本验不了**"是三件事。
#: 库是 0 字节时，把每一条面板落点都报成"列找不到"，读到的是一片**假红**——
#: 而假红比没有红更坏，因为它看起来像"查过了"（PM 2026-09-20 裁定）。
OK, BAD, UNKNOWN = "ok", "bad", "unknown"


def _akdb_usable() -> tuple[bool, str]:
    """干员库当前**能不能用来验落点**（问的不是"落点对不对"）。"""
    if not AKDB.exists():
        return False, f"{AKDB.name} 不存在"
    if AKDB.stat().st_size == 0:
        return False, f"{AKDB.name} 是 0 字节"
    try:
        c = sqlite3.connect(f"file:{AKDB}?mode=ro", uri=True)
        try:
            n = c.execute(
                "select count(*) from sqlite_master where type='table'").fetchone()[0]
        finally:
            c.close()
    except sqlite3.Error as e:                                   # noqa: BLE001
        return False, f"{AKDB.name} 打不开：{e}"
    if n == 0:
        return False, f"{AKDB.name} 里没有任何表"
    return True, f"可用（{n} 张表）"


def _columns(db: Path, table: str) -> set[str]:
    """⚠ 用**只读 URI** 打开。

    默认的 `sqlite3.connect(path)` 在文件**不存在时会当场凭空建一枚 0 字节的**——
    一个"读"动作把工作树改了，是最难查的一类副作用（2026-09-20 实测踩过）。
    """
    c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
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


def verify_target(target: str, keyword: str = "") -> tuple[str, str]:
    """验证一个落点声明。返回 (OK|BAD|UNKNOWN, 说明)。

    `keyword` 只有 `-` 档用得上（要靠它去 `ABSENT_ANCHORS` 取反证锚）。
    """
    if target == "-":
        anchors = ABSENT_ANCHORS.get(keyword, ())
        if not anchors:
            return BAD, ("`-` 档**没有登记反证锚**（`ABSENT_ANCHORS`）"
                         "⇒ 这条声明不可证伪，等同于没断言")
        dead = []
        for rel, needle, _why in anchors:
            p = ROOT / rel
            if not p.exists():
                return UNKNOWN, f"反证锚的载体文件不在：{rel}"
            txt = p.read_text(encoding="utf-8", errors="ignore")
            if re.search(rf"\b{re.escape(needle)}\b", txt):
                dead.append(f"{rel} 里有 `{needle}`")
        if dead:
            return BAD, ("登记为未建模，但反证锚命中：" + "；".join(dead)
                         + " ⇒ **表说没有，可是找到了**")
        return OK, (f"已过 {len(anchors)} 个反证锚、均未命中"
                    "（只是没被证伪，不等于已证实）")
    if "::" in target:
        path, _, sym = target.partition("::")
        p = ROOT / path
        if not p.exists():
            return UNKNOWN, f"符号载体文件不在：{path}"
        txt = p.read_text(encoding="utf-8", errors="ignore")
        ok = re.search(rf"\b{re.escape(sym)}\b", txt) is not None
        return (OK, "符号存在") if ok else (BAD, f"符号找不到：{target}")
    table, _, col = target.partition(".")
    if not table or not col:
        return BAD, f"落点写法不认识：{target}"
    usable, why = _akdb_usable()
    if not usable:
        # ★ 这里是③：**库不可用 ⇒ 判不了**，绝不许落到 BAD。
        return UNKNOWN, f"验不了：{why}"
    cols = _columns(AKDB, table)
    if not cols:
        return BAD, f"表不存在：{table}（库可用，所以这是表名写错了）"
    return (OK, "列存在") if col in cols else (BAD, f"列找不到：{table}.{col}")


def keywords_in(text: str) -> list[str]:
    return [k for k in FAMILIES if k in text]


def classify(text: str) -> tuple[str, list[str], list[str]]:
    """返回 (档位, 命中词, 说明)。

    档位：`LINKED` / `UNMODELED` / `PARSE` / `BROKEN` / `UNDECIDABLE`。

    ⚠ `UNMODELED`（未实现）与 `UNDECIDABLE`（判不了）**必须分列**：
    前者是"我们验过了，确实没有"，后者是"我们**根本验不了**"。
    把两者并成一个值，就是本工具旧版最大的假信号来源。
    """
    hits = keywords_in(text)
    if not hits:
        return "PARSE", [], []
    broken: list[str] = []
    unknown: list[str] = []
    unmodeled: list[str] = []
    for k in hits:
        target, _note = FAMILIES[k]
        state, why = verify_target(target, k)
        if state == BAD:
            broken.append(f"{k}→{target}（{why}）")
        elif state == UNKNOWN:
            unknown.append(f"{k}→{target}（{why}）")
        if target == "-":
            unmodeled.append(k)
    if broken:
        return "BROKEN", hits, broken
    if unknown:
        return "UNDECIDABLE", hits, unknown
    if len(unmodeled) == len(hits):
        return "UNMODELED", hits, []
    return "LINKED", hits, []


def self_test() -> int:
    """自证：每一档都要能落到自己那一档（判据红得起来吗）。"""
    global AKDB
    cases = [
        ("攻击力提升至130%", "LINKED"),
        ("庇护+30", "UNMODELED"),
        ("这是一句没有任何机制词的描述文字而已", "PARSE"),
    ]
    bad = 0
    print("== 自证：每档都要能落到自己那一档 ==")
    for text, want in cases:
        got, hits, why = classify(text)
        ok = got == want
        bad += 0 if ok else 1
        print(f"  {'✅' if ok else '⛔'} 期望 {want}／得到 {got}  命中词={hits}  「{text[:24]}」")
        if got == "BROKEN" and why:
            print(f"       {why[0]}")

    # ① `-` 档守卫：反证锚命中 ⇒ 必须翻红。
    # ★ 2026-09-20 修账后，`-` 档只剩 3 条、且**都没有可命中的锚**
    #   （那正是它们还活着的原因）⇒ **"现成的活例子"没有了**。
    #   所以这里**必须合成一个**。否则这条守卫会随着错账被修完而
    #   **悄悄变成看不见的守卫**——而这正是它当初要防的那件事。
    print("== ① `-` 档守卫：反证锚命中时必须变红（合成用例） ==")
    _k = "__自证_必然命中__"
    _saved_fam, _saved_anc = dict(FAMILIES), dict(ABSENT_ANCHORS)
    FAMILIES[_k] = ("-", "自证用：故意登记一个**必然命中**的反证锚")
    ABSENT_ANCHORS[_k] = (("tools/audit_op_notes.py", "ABSENT_ANCHORS",
                           "自证用：这个词就写在本文件里，翻一下必然命中"),)
    try:
        got, _, why = classify(_k)
    finally:
        FAMILIES.clear()
        FAMILIES.update(_saved_fam)
        ABSENT_ANCHORS.clear()
        ABSENT_ANCHORS.update(_saved_anc)
    ok = got == "BROKEN"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '⛔'} 期望 BROKEN／得到 {got}")
    for w in why:
        print(f"       {w}")

    # ★ 修账复核：这三条**必须已经落到 LINKED**（落点符号真实存在）。
    #   把"修好了"也做成一条**会红的断言**——否则修完就再没人看它了。
    print("== 修账复核：闪避／治疗／回复 必须落到 LINKED ==")
    for text in ("闪避+30", "回复生命值", "治疗自身"):
        got, hits, why = classify(text)
        ok = got == "LINKED"
        bad += 0 if ok else 1
        tgt = FAMILIES[hits[-1]][0] if hits else "?"
        print(f"  {'✅' if ok else '⛔'} 期望 LINKED／得到 {got}  命中词={hits} 落点={tgt}")
        for w in why:
            print(f"       {w}")

    # ① 反向：**没有反证锚**的 `-` 档也必须红——"不可证伪"本身就是要报的病
    print("== ① 反向：`-` 档缺反证锚时必须变红 ==")
    saved_anchor = ABSENT_ANCHORS.pop("庇护")
    got, _, why = classify("庇护+30")
    ABSENT_ANCHORS["庇护"] = saved_anchor
    ok = got == "BROKEN"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '⛔'} 期望 BROKEN／得到 {got}  {why}")

    # ③ 库不可用 ⇒ 判不了，**不许**报 BROKEN
    print("== ③ 库不可用 ⇒ UNDECIDABLE，不许报 BROKEN ==")
    saved_db = AKDB
    AKDB = ROOT / "data" / "__no_such_akdb__.sqlite"
    try:
        got, _, why = classify("攻击力提升至130%")
    finally:
        AKDB = saved_db
    ok = got == "UNDECIDABLE"
    bad += 0 if ok else 1
    print(f"  {'✅' if ok else '⛔'} 期望 UNDECIDABLE／得到 {got}  {why}")
    print(f"      （库恢复后同一条：{classify('攻击力提升至130%')[0]}）")

    # 反向守卫：落点声明错时必须变红
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


def print_absent_ledger() -> int:
    """原 `-` 档那 6 条的**对账单**：每一条现在落在哪一档、凭什么。

    为什么做成命令而不是写进汇报里：PM 2026-09-20 要求「修完把 6 条现在各分列到
    哪一档逐条印出来」——**一次性的打印会随上下文丢掉，命令不会**。
    """
    tier_of = {OK: "已建模（落点成立）", BAD: "错账（落点不成立）",
               UNKNOWN: "判不了（验不了，不是没有）"}
    print("== 原 `-` 档对账单：这 6 条现在各在哪一档 ==")
    print("   `-` 档曾是四档里**唯一不需要证据就能通过**的档；2026-09-20 查出 3 条错账并已修。")
    print()
    n_bad = 0
    for k in ABSENT_LEDGER:
        if k not in FAMILIES:
            print(f"  ⛔ {k}：**已不在 FAMILIES 里**——删词等于把它移出核对范围，那是把账做平")
            n_bad += 1
            continue
        target, note = FAMILIES[k]
        state, why = verify_target(target, k)
        if target == "-":
            tier = "未建模（登记为「我们没有」，反证锚均未命中）"
            if state == BAD:
                tier = "**错账**：登记为未建模，可反证锚命中了"
        else:
            tier = tier_of[state]
        mark = "⛔" if state == BAD else ("❓" if state == UNKNOWN else "✅")
        print(f"  {mark} {k}　落点 `{target}`")
        print(f"        档位：{tier}")
        print(f"        依据：{why}")
        print(f"        备注：{note}")
        print()
        if state == BAD:
            n_bad += 1
    print(f"  合计 {len(ABSENT_LEDGER)} 条：**落点不成立 {n_bad} 条**")
    print("  ★ 剩下的 `-` 条**不是「没查过」，是「查过、反证锚都没命中」**——"
          "只是没被证伪，**不等于已证实**。")
    return 1 if n_bad else 0


def main() -> int:
    _force_utf8_stdout()
    ap = argparse.ArgumentParser(description="干员 wiki 备注逐条核查（覆盖率视角）")
    ap.add_argument("--only", help="只看名字/char_id 含该子串的干员")
    ap.add_argument("--top", type=int, default=10, help="各档列出前 N 个关键词族")
    ap.add_argument("--self-test", action="store_true", help="自证三档可红")
    ap.add_argument("--absent", action="store_true",
                    help=f"打印原 `-` 档那 {len(ABSENT_LEDGER)} 条的**对账单**："
                         "每一条现在落在哪一档、凭什么")
    ap.add_argument("--dump-parse", metavar="PATH",
                    help="把 PARSE 那批（没有普查词的 fact）落盘成待核清单，供下一轮扩充普查表")
    args = ap.parse_args()

    if args.self_test:
        return self_test()

    if args.absent:
        return print_absent_ledger()

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

    # 落点先整体验一遍：表写错了要在汇总里立刻看到，而不是散在每条 fact 上。
    # ⚠ 这一段**只依赖干员库、不依赖 fact 语料**，所以放在 NOTES_DB 检查**之前**：
    #   语料缺了也必须能看见"表本身对不对"——否则 `-` 档守卫红没红根本无从观察，
    #   而"看不见的守卫"就等于没有守卫。
    print("== 落点验证（声明即断言） ==")
    bad_targets: list[tuple[str, str, str]] = []
    unknown_targets: list[tuple[str, str, str]] = []
    for k, (target, _n) in sorted(FAMILIES.items()):
        state, why = verify_target(target, k)
        if state == BAD:
            bad_targets.append((k, target, why))
        elif state == UNKNOWN:
            unknown_targets.append((k, target, why))
    print(f"  声明 {len(FAMILIES)} 个机制词："
          f"落点不成立 {len(bad_targets)} 个、判不了 {len(unknown_targets)} 个")
    for k, target, why in bad_targets:
        print(f"    ⛔ {k} → {target}：{why}")
    for k, target, why in unknown_targets:
        print(f"    ❓ {k} → {target}：{why}")

    if not NOTES_DB.exists():
        print()
        print(f"== 汇总：判不了 ==")
        print(f"  ⛔ 找不到 {NOTES_DB.name}（本地工作库，不入仓库）⇒ "
              "**fact 级核对整段判不了**，上面那段落点验证仍然有效。")
        print("  重建：python tools/fetch_prts_notes.py（要联网，按名册逐页抓 PRTS 干员页）")
        return 2

    c = sqlite3.connect(f"file:{NOTES_DB}?mode=ro", uri=True)
    c.row_factory = sqlite3.Row
    where, params = "", []
    if args.only:
        where = " where char_id like ? or char_id in (select char_id from page where name like ?)"
        params = [f"%{args.only}%", f"%{args.only}%"]
    rows = c.execute(f"select char_id, kind, value from fact{where}", params).fetchall()

    tiers: dict[str, int] = {
        "LINKED": 0, "UNMODELED": 0, "PARSE": 0, "BROKEN": 0, "UNDECIDABLE": 0}
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
    for t in ("LINKED", "UNMODELED", "PARSE", "BROKEN", "UNDECIDABLE"):
        share = tiers[t] / len(rows) if rows else 0
        print(f"  {t:<12} {tiers[t]:>5}  {share:>6.1%}")
    print("  ⚠ LINKED 读作「**有这个字段族**」，不是「已核对」——本工具不做数值对账。")
    print("  ⚠ UNMODELED（验过了，确实没有）与 UNDECIDABLE（**根本验不了**）"
          "是两件事，见 `verify_target` 的三态说明。")

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
