#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""data/ 完整性速检：**分母静默收窄仍全绿**这件事，在这里变成一个红。

## 为什么要有它（2026-09-24 的真实事故）

00:46，一个会话用 `git worktree remove --force` 收尾时**穿透 junction**，把主仓
`data/` 的内容删掉了。后果不是报错，而是**一串判据在缩水的分母上照样全绿**：
`tools/check_go_all.py` 会印「取证范围：缓存可达的关卡 N 个」，却**不因 N 变小而红**。
当晚它是从 `55 关` 掉到 `2 关`，靠人眼看那行字才发现。

⇒ 这条检查存在的唯一理由：把「分母静默收窄」变成一个红。

## 判据（逐条都印「命令 / rc / 读数」，并印 ASCII 机读行）

1. **清单完整性**：权威清单**从 `docs/data-sources.md` 现解析**（§四 的落点一览代码块
   ＋ §二 表格的「本地落点」栏），**不另抄一份**。缺哪项就逐项印出来。
2. **库可读且没被掏空**：三个 sqlite 一律 `mode=ro` 打开（**只读**；本项目记过
   `sqlite3.connect` 会静默新建 0 字节库），跑 `PRAGMA integrity_check` 并数行。
3. **行数与「现算」的上游对账**：能从上游 JSON 现算的就现算（成立的关系**断言**；
   不成立的**明说为什么不成立**，不硬凑），推不出的落到第 4 条。
4. **棘轮**：上一次已知完好的读数存在版本控制里的 `tools/data-watermarks.json`。
   现读低于棘轮 ⇒ 红（两侧并排印值＋时刻）；高于 ⇒ 绿并**只提示**可抬，**不自动写**。
   棘轮文件不存在**不算红**，但会印「棘轮缺失：本次不设下限」与生成命令。
5. **关卡分母不许缩**：从 `fixtures/` 现算出所有被打法引用到的关卡，**按集合**断言
   每一关的 `level_*.json` 都在缓存里（比「N ≥ 某数」强）。缓存可达集合用的就是
   `tools/check_go_all.py` 的 `cached_levels()` **同一份实现**（不另写算法）。
6. **正负对照**：`--selftest` 真跑四组合成输入（一组必绿、三组必红），两组都真进分支、真影响 rc。

## 退出码（与今晚定的那套一致，不另创）

* `0` 全绿
* `1` **判据红**（数据不全／被掏空／分母缩了）
* `3` **仪器缺输入**（权威 Markdown 解析不出来、`data/` 根不存在、关卡索引读不到）
  —— 与「数据坏了」**不是一回事**，不许压成一个码
* `5` **检查自己崩了**（与上面三态都不重叠；崩了不许被读成「有违规」）

## 机读行（一律 ASCII）

    DATA_MISSING <相对路径>
    DATA_UNDERFILLED <项> ratchet=<上次数>@<时刻> now=<现读数>@<时刻>
    DATA_LEVEL_UNCACHED <关卡名>
    DATA_MANIFEST_UNPARSED <文档路径> <行号>

  另有同类前缀的补充行（`DATA_DB_*` / `DATA_UPSTREAM_*` / `DATA_RATCHET_*` /
  `DATA_SELFTEST` / `DATA_READY`），见各自打印点。

## 只在库文本，不碰 data/

本工具**不写 `data/` 下任何东西**：sqlite 全走 `mode=ro`，其余全是 `Path.exists()`
与 `read_text()`。唯一的写动作是 `--write-ratchet`，**显式开关**，只写棘轮文件本身。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from urllib.parse import quote

#: ★ 本机 stdout 默认 gbk。判据**不许因编码崩**（本项目记过：7 个惯用符号编不出，
#: 会让 rc 由**崩溃**给出而不是由判据给出）。与 `tools/check_go_all.py` 同一处置：
#: 入口显式落到 utf-8 ＋ backslashreplace——机读行本来就只有 ASCII，散文编不出时
#: 退化成转义文本，信息不丢。
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

TOOLS = Path(__file__).resolve().parent
REPO = TOOLS.parent

EXIT_OK, EXIT_RED, EXIT_INSTRUMENT, EXIT_CRASH = 0, 1, 3, 5

DOC_REL = "docs/data-sources.md"
FIXTURES_REL = "fixtures"
RATCHET_REL = "tools/data-watermarks.json"
LEVEL_INDEX_REL = "data/gamedata/_level_index.json"
ARK_LEVELS_REL = "data/gamedata/map.ark-nights.com/levels"
EXCEL_REL = "data/gamedata/raw.githubusercontent.com/excel"
ENEMY_DB_REL = "data/gamedata/map.ark-nights.com/levels/enemydata/enemy_database.json"

#: 三个库各自要数行的表。行数进棘轮，项名形如 `<库>/<表>`。
DB_TABLES: list[tuple[str, list[str]]] = [
    ("data/akdb.sqlite", ["operator", "skill", "stage", "zone"]),
    ("data/enemydb.sqlite", ["enemy"]),
    ("data/prts-notes.sqlite", ["page", "fact"]),
]

#: ★ 事故对照锚（**不是任何下限**，只是让下一个人知道 55 是哪儿来的）。
#: 2026-09-24 00:26 那轮整闸（仪器 sha256(16)＝3611501bac8628a3，留证
#: `out/_main_selfcheck_postfix.txt`）读数：缓存可达关卡 55 / 敌人 251 / 干员折算 679·679。
#: 00:46 的事故之后关卡掉到 2。这三个数写在这里，**不进判据、不进 rc**。
INCIDENT_ANCHORS = {
    "note": "2026-09-24 00:46 的事故：一个会话用 git worktree remove --force 收尾时穿透 "
            "junction，删掉了主仓 data/ 的内容。症状不是报错，而是一串判据在缩水的分母上"
            "照样全绿（check_go_all.py 印「取证范围：缓存可达的关卡 N 个」却不因 N 变小而红，"
            "当晚从 55 关掉到 2 关，靠人眼看那行字才发现）。下面三个数只作对照锚，"
            "不作任何下限。",
    "run": "2026-09-24 00:26 check_go_all.py --selfcheck",
    "instrument_sha256_16": "3611501bac8628a3",
    "evidence": "out/_main_selfcheck_postfix.txt",
    "cached_levels": 55,
    "enemies": 251,
    "operator_scale": "679/679",
}


def stamp() -> str:
    """取数时刻（带本地时区偏移）。棘轮文件里的每一项都要带它。"""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _a(value) -> str:
    """机读行的字段一律降成 ASCII（编不出的退化成反斜杠转义）。"""
    return str(value).encode("ascii", "backslashreplace").decode("ascii")


def _uri(path: Path) -> str:
    """sqlite 的只读 URI。★ 路径里有空格也不许炸。"""
    return "file:" + quote(path.as_posix(), safe="/:") + "?mode=ro"


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def unwrap_unity(node):
    """剥掉 Unity 序列化包装（本项目记过：`{"Key":…,"Value":…}`）。"""
    while isinstance(node, dict) and set(node) == {"Key", "Value"}:
        node = node["Value"]
    return node


def m_value(node):
    if isinstance(node, dict) and "m_value" in node:
        return node["m_value"]
    return node


class Report:
    """三类出口分开收：判据红 / 仪器缺输入 / 纯登记；另收全部现读数。"""

    def __init__(self) -> None:
        self.red: list[str] = []
        self.instr: list[str] = []
        self.info: list[str] = []
        self.readings: dict[str, dict] = {}
        self.manifest: dict[str, dict] = {}

    def put(self, name: str, value: int, cmd: str, floor: bool = True,
            note: str = "") -> None:
        self.readings[name] = {"value": int(value), "at": stamp(), "source": cmd,
                               "floor": floor, "note": note}


class Out:
    """散文受 --quiet 管，**机读行不受**。"""

    def __init__(self, quiet: bool) -> None:
        self.quiet = quiet
        self.lines: list[str] = []

    def say(self, line: str = "") -> None:
        self.lines.append(line)
        if not self.quiet:
            print(line)

    def mline(self, line: str) -> None:
        self.lines.append(line)
        print(line)


# --------------------------------------------------------------------------- #
# 1. 权威清单：从 docs/data-sources.md 现解析（不另抄一份）
# --------------------------------------------------------------------------- #

SECTION_FOUR = "四、本地落点一览"
SECTION_TWO = "二、全部数据源"
_CELLQUOTE = re.compile(r"`(data/[^`]*)`")


def parse_manifest(doc: Path) -> tuple[dict[str, dict], str, int]:
    """从权威文档解析出 `data/` 下该有哪些项。

    返回 `(items, 失败原因, 行号)`；原因为空 ⇒ 解析成功。

    两个来源：
      * §四 的落点一览**代码块**（那一栏就是「本地落点一览」本身）；
      * §二 表格的**本地落点栏**（`data/operbox/`、`data/skland/` 只在那里出现过）。
    ★ 括号写法 `data/cache/{a,b,c}/` 的清单项取**括号之前的前缀**（`data/cache/`）——
      那一行给的是「这一项」，括号里是它的成员；成员的在场与否单独登记（不进 rc）。
    """
    if not doc.is_file():
        return {}, f"文档不存在：{doc}", 0
    lines = doc.read_text(encoding="utf-8", errors="replace").splitlines()

    def find_heading(needle: str) -> int:
        for i, line in enumerate(lines):
            if line.startswith("## ") and needle in line:
                return i
        return -1

    items: dict[str, dict] = {}

    def add(raw: str, line_no: int, section: str, members: list[str] | None) -> None:
        rel = raw.strip().strip(",、;；")
        if not rel.startswith("data/"):
            return
        ent = items.setdefault(rel, {"line": line_no, "section": section,
                                     "glob": "*" in rel, "members": None})
        if members:
            ent["members"] = members

    def unbrace(tok: str) -> tuple[str, list[str]]:
        """`a/{b,c}/` ⇒ (`a/`, [b, c])；没有括号则原样返回空成员表。"""
        if "{" not in tok:
            return tok, []
        head, _, tail = tok.partition("{")
        members = [m.strip() for m in tail.split("}")[0].split(",") if m.strip()]
        return head, members

    sec4 = find_heading(SECTION_FOUR)
    if sec4 < 0:
        return {}, f"找不到小节「{SECTION_FOUR}」", 0
    j = sec4
    while j < len(lines) and not lines[j].strip().startswith("```"):
        j += 1
    if j >= len(lines):
        return {}, f"小节「{SECTION_FOUR}」里没有代码块（第 {sec4 + 1} 行起）", sec4 + 1
    k = j + 1
    while k < len(lines) and not lines[k].strip().startswith("```"):
        k += 1
    for n, line in enumerate(lines[j + 1:k], start=j + 2):
        s = line.strip()
        if not s:
            continue
        rel, members = unbrace(s.split()[0])
        add(rel, n, "四", members)
    n_four = len(items)
    if n_four == 0:
        return {}, f"代码块里一行 data/ 都没解析出来（第 {j + 1} 行起的围栏）", j + 1

    sec2 = find_heading(SECTION_TWO)
    if sec2 >= 0:
        for n, line in enumerate(lines[sec2:], start=sec2 + 1):
            if n > sec2 + 1 and line.startswith("## "):
                break
            if not line.startswith("|"):
                continue
            cells = line.split("|")
            if len(cells) < 8:
                continue
            for raw in _CELLQUOTE.findall(cells[6]):
                rel, members = unbrace(raw)
                add(rel, n, "二", members)
    return items, "", 0


# --------------------------------------------------------------------------- #
# 5. 关卡分母：与 check_go_all 同一份实现
# --------------------------------------------------------------------------- #

def cached_levels_via_check_go_all(root: Path) -> list[str]:
    """缓存可达的关卡 id——**就是 `tools/check_go_all.py` 的那一份实现**。

    ★ 为什么是 import 而不是重写：两份必然有一天走散。`cached_levels()` 读的是
      模块级的 `ROOT`，所以这里把 `--root` 临时安上去再调（**只在同一个进程里**
      活一下就还原），算法本身一个字没动。
    """
    spec = importlib.util.spec_from_file_location(
        "_data_ready_check_go_all", str(TOOLS / "check_go_all.py"))
    if spec is None or spec.loader is None:
        raise RuntimeError("装不进 tools/check_go_all.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    old = getattr(mod, "ROOT", None)
    mod.ROOT = root
    try:
        return list(mod.cached_levels())
    finally:
        if old is not None:
            mod.ROOT = old


def fixture_levels(fixtures: Path) -> tuple[dict[str, list[str]], list[str]]:
    """从夹具里**现算**被打法引用到的关卡：任何带顶层 `stage` 的 json 都算。"""
    levels: dict[str, list[str]] = {}
    bad: list[str] = []
    if not fixtures.is_dir():
        return {}, []
    for f in sorted(fixtures.rglob("*.json")):
        try:
            obj = json.loads(f.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - 夹具读不了要大声失败
            bad.append(f"{f.name}: {type(e).__name__}")
            continue
        if not isinstance(obj, dict):
            continue
        stage = obj.get("stage")
        if isinstance(stage, str) and stage.strip():
            levels.setdefault(stage.strip(), []).append(f.name)
    return levels, bad


def db_readable(path: Path, table: str) -> bool:
    """只读地试一下库和某张表在不在。★ 只读：0 字节库在 mode=ro 下也读不出表。"""
    if not path.is_file() or path.stat().st_size == 0:
        return False
    try:
        con = sqlite3.connect(_uri(path), uri=True)
        con.execute(f'select count(*) from "{table}"').fetchone()
        con.close()
        return True
    except Exception:  # noqa: BLE001
        return False


# --------------------------------------------------------------------------- #
# 3. 上游对账
# --------------------------------------------------------------------------- #

def check_upstream(root: Path, rep: Report, out: Out) -> None:
    """第 3 条：行数与现算的上游对账。"""
    gd = root / "data" / "gamedata"
    akdb = root / "data" / "akdb.sqlite"
    enemydb = root / "data" / "enemydb.sqlite"

    def red(line: str) -> None:
        #: ★ 只登记、**不在这里印**：印在这里、汇总再印一次，机读行就会翻倍
        #: （实测 --selftest 对照 D 的 DATA_LEVEL_UNCACHED 从 23 变 46）。
        rep.red.append(line)

    def skip(metric: str, why: str) -> None:
        red(f"DATA_UPSTREAM_UNREADABLE {_a(metric)} {_a(why)}")

    # ---- akdb.operator -------------------------------------------------- #
    ok_db = db_readable(akdb, "operator")
    ct_p = gd / "raw.githubusercontent.com" / "excel" / "character_table.json"
    cpt_p = gd / "raw.githubusercontent.com" / "excel" / "char_patch_table.json"
    if not ok_db:
        skip("akdb.operator", "akdb.sqlite/operator 读不出来")
    elif not (ct_p.is_file() and cpt_p.is_file()):
        red(f"DATA_UPSTREAM_FILE_MISSING {_a(ct_p if not ct_p.is_file() else cpt_p)}")
        out.say(f"[3a] akdb.operator  rc=1  读数=上游表单不在，对账做不成")
    else:
        ct = _read_json(ct_p)
        patch = (_read_json(cpt_p).get("patchChars") or {})
        n_char = sum(1 for k in ct if k.startswith("char_"))
        n_tok = sum(1 for k in ct if k.startswith("token_"))
        n_trap = sum(1 for k in ct if k.startswith("trap_"))
        con = sqlite3.connect(_uri(akdb), uri=True)
        db_ids = [r[0] for r in con.execute("select char_id from operator")]
        con.close()
        n_db_char = sum(1 for c in db_ids if c.startswith("char_"))
        n_db_tok = sum(1 for c in db_ids if c.startswith("token_"))
        n_db_trap = sum(1 for c in db_ids if c.startswith("trap_"))
        upstream_ids = set(ct) | set(patch)
        orphans = [c for c in db_ids if c not in upstream_ids]
        ok = (n_db_char == n_char + len(patch)) and (n_db_tok == n_tok) and not orphans
        out.say(f"[3a] akdb.operator  cmd=读 character_table.json ＋ char_patch_table.json  "
                f"rc={0 if ok else 1}  读数=char_ {n_db_char} vs |CT.char_| {n_char} ＋ "
                f"|patchChars| {len(patch)}；token_ {n_db_tok} vs {n_tok}；"
                f"trap_ {n_db_trap} ⊆ {n_trap}；追不到上游的 {len(orphans)} 条")
        out.say(f"     ★ **成立**：char_ 段 == |CT.char_| ＋ |patchChars|（阿米娅升变形态住 "
                f"patchChars）；token_ 段 == |CT.token_|；trap_ 段 ⊆ CT.trap_"
                f"（建库按 excluded 名单 ＋ 生息演算装置筛掉 {n_trap - n_db_trap} 条，"
                f"这个筛子**没有**在判据里重写——重写就是第二份实现）。")
        out.say(f"     ★ **不成立**：`akdb.operator` 总数 == `char_` 条目数"
                f"（{len(db_ids)} vs {n_char}）——operator 表还装着 trap_/token_ 两族，"
                f"且 char_ 段多了 patchChars 那 {len(patch)} 条。")
        if not ok:
            red(f"DATA_UPSTREAM_MISMATCH akdb.operator char={_a(n_db_char)}"
                f" derived={_a(n_char + len(patch))} orphans={_a(len(orphans))}")
        else:
            rep.info.append("DATA_UPSTREAM_OK akdb.operator orphans=0")

    # ---- akdb.skill ----------------------------------------------------- #
    st_p = gd / "raw.githubusercontent.com" / "excel" / "skill_table.json"
    if not db_readable(akdb, "skill"):
        skip("akdb.skill", "akdb.sqlite/skill 读不出来")
    elif not st_p.is_file():
        red(f"DATA_UPSTREAM_FILE_MISSING {_a(st_p)}")
        out.say(f"[3b] akdb.skill  rc=1  读数=上游 skill_table.json 不在，对账做不成")
    else:
        keys = set(_read_json(st_p))
        bracket = sorted(k for k in keys if "[" in k)
        con = sqlite3.connect(_uri(akdb), uri=True)
        db_sk = set(r[0] for r in con.execute("select skill_id from skill"))
        con.close()
        miss = sorted(db_sk - keys)
        out.say(f"[3b] akdb.skill  cmd=读 skill_table.json  rc={0 if not miss else 1}  "
                f"读数=库 {len(db_sk)} 条 ⊆ 上游 {len(keys)} 键（其中 {len(bracket)} 个是 "
                f"`skcom_*[n]` 修饰器键、{len(keys) - len(bracket)} 个是技能键）；"
                f"追不到上游的 {len(miss)} 条")
        out.say(f"     ★ **成立**：库里每一条 skill 都能在上游找到（含于关系）。")
        out.say(f"     ★ **不成立**：行数相等（{len(db_sk)} vs {len(keys)}）——上游表里住着 "
                f"{len(bracket)} 个 `skcom_*[n]` 修饰器键（不是技能），另有一批技能没有任何"
                f"干员引用，两边按构造就不等；硬凑相等只会造一个必然假红。")
        if miss:
            red(f"DATA_UPSTREAM_ORPHAN akdb.skill count={_a(len(miss))}"
                f" first={_a(miss[0])}")
        else:
            rep.info.append("DATA_UPSTREAM_OK akdb.skill orphans=0")

    # ---- akdb.stage ----------------------------------------------------- #
    stt_p = gd / "raw.githubusercontent.com" / "excel" / "stage_table.json"
    idx_p = root / LEVEL_INDEX_REL
    if not db_readable(akdb, "stage"):
        skip("akdb.stage", "akdb.sqlite/stage 读不出来")
    elif not stt_p.is_file():
        red(f"DATA_UPSTREAM_FILE_MISSING {_a(stt_p)}")
        out.say(f"[3c] akdb.stage  rc=1  读数=上游 stage_table.json 不在，对账做不成")
    else:
        skeys = set((_read_json(stt_p).get("stages") or {}))
        con = sqlite3.connect(_uri(akdb), uri=True)
        db_st = set(r[0] for r in con.execute("select level_id from stage"))
        con.close()
        miss = sorted(db_st - skeys)
        idx_keys = set(_read_json(idx_p)) if idx_p.is_file() else set()
        out.say(f"[3c] akdb.stage  cmd=读 stage_table.json 的 stages 键  rc={0 if not miss else 1}  "
                f"读数=库 {len(db_st)} 关 ⊆ stage_table {len(skeys)} 键；追不到上游的 "
                f"{len(miss)} 条；{LEVEL_INDEX_REL} 键 {len(idx_keys)}")
        out.say(f"     ★ **成立**：库里的每一关都能在 stage_table 找到（含于关系）。")
        out.say(f"     ★ **不成立**：与 `_level_index.json` 的关卡数相等"
                f"（{len(db_st)} vs {len(idx_keys)}）——索引把 `#f#` 四星档**当独立条目**记"
                f"（同一 levelId 出现两次），且 stage 表是「索引 join stage_table 再按 zone "
                f"类型 CHAPTER_TYPES 筛行」的产物（ak_tactic/db/stages.py:137、:365），"
                f"不是任何单一上游的行数。")
        if miss:
            red(f"DATA_UPSTREAM_ORPHAN akdb.stage count={_a(len(miss))}"
                f" first={_a(miss[0])}")
        else:
            rep.info.append("DATA_UPSTREAM_OK akdb.stage orphans=0")

    # ---- enemydb.enemy -------------------------------------------------- #
    ed_p = root / ENEMY_DB_REL
    if not db_readable(enemydb, "enemy"):
        skip("enemydb.enemy", "enemydb.sqlite/enemy 读不出来")
    elif not ed_p.is_file():
        red(f"DATA_UPSTREAM_FILE_MISSING {_a(ed_p)}")
        out.say(f"[3d] enemydb.enemy  rc=1  读数=上游 enemy_database.json 不在，对账做不成")
    else:
        con2 = sqlite3.connect(_uri(enemydb), uri=True)
        db_names = [r[0] for r in con2.execute("select name from enemy")]
        con2.close()
        ed = unwrap_unity(_read_json(ed_p))
        entries = ed.get("enemies") if isinstance(ed, dict) else None
        up_names = set()
        if isinstance(entries, list):
            for e in entries:
                for lv in (e.get("Value") or []):
                    nm = m_value((lv.get("enemyData") or {}).get("name"))
                    if isinstance(nm, str) and nm:
                        up_names.add(nm)
        inter = len(set(db_names) & up_names)
        orphan = sorted(set(db_names) - up_names)
        rep.put("upstream/enemydb_enemy_intersection", inter,
                "enemy_database.json 的名 × enemydb.enemy 的 name 交集")
        out.say(f"[3d] enemydb.enemy  cmd=读 enemy_database.json 并剥 Key/Value 包装  rc=0  "
                f"读数=库 {len(db_names)} 行 / 上游 {len(up_names)} 个不同名 / 交集 {inter} / "
                f"库里上游没有的 {len(orphan)} 条")
        out.say(f"     ★ **不成立**：两边行数相等（{len(db_names)} vs {len(up_names)}）——"
                f"两侧**键空间都不同**：库里是 prts.wiki 分类:敌人 的**中文名**（源 #1），"
                f"上游是游戏本体的 `enemy_*` id（源 #8），唯一的公共同轴是中文名，而 prts "
                f"那一侧还收着演出用敌人与别名条目（如 "
                f"{_a(orphan[0]) if orphan else '-'}）。⇒ 用**交集数**当对账量，"
                f"它的水位进棘轮。")
        rep.info.append(f"DATA_UPSTREAM_INTERSECTION enemydb.enemy {_a(inter)}"
                        f" stored={_a(len(db_names))} upstream={_a(len(up_names))}")
        if inter == 0:
            red(f"DATA_UPSTREAM_MISMATCH enemydb.enemy intersection=0"
                f" stored={_a(len(db_names))} upstream={_a(len(up_names))}")


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def run(root: Path, ratchet_path: Path, *, write_ratchet: bool = False,
        force: bool = False, quiet: bool = False) -> int:
    out = Out(quiet)
    rep = Report()
    doc = root / DOC_REL
    fixtures = root / FIXTURES_REL
    datadir = root / "data"

    def red(line: str) -> None:
        #: ★ 只登记、**不在这里印**（汇总里统一印一次）——两处都印会让机读行翻倍。
        rep.red.append(line)

    # ---- 0. 仪器输入自带的三态 ------------------------------------------ #
    if not root.is_dir():
        rep.instr.append(f"DATA_ROOT_ABSENT {_a(root)}")
    if not datadir.is_dir():
        rep.instr.append(f"DATA_ROOT_ABSENT {_a(datadir)}")

    # ---- 1. 权威清单 ----------------------------------------------------- #
    items, why, line_no = parse_manifest(doc)
    rep.manifest = items
    if why:
        rep.instr.append(f"DATA_MANIFEST_UNPARSED {_a(doc)} {_a(line_no)}")
        out.say(f"[1] 清单完整性  cmd=解析 {DOC_REL}（§四 代码块 ＋ §二 本地落点栏）  rc=3  "
                f"读数=解析不出：{why}")
        out.say("     ★ 解析不出**不许**退回硬编码清单，所以这里是 rc=3（仪器缺输入），"
                "不是 rc=1（数据坏了）。")
    else:
        missing = []
        for rel, info in sorted(items.items()):
            if info["glob"]:
                hit = len(list(root.glob(rel))) > 0
            else:
                hit = (root / rel).exists()
            if not hit:
                missing.append(rel)
                red(f"DATA_MISSING {_a(rel)}")
        n_four = sum(1 for v in items.values() if v["section"] == "四")
        out.say(f"[1] 清单完整性  cmd=解析 {DOC_REL}（§四 代码块 ＋ §二 本地落点栏）  "
                f"rc={1 if missing else 0}  读数=清单 {len(items)} 项、缺 {len(missing)} 项"
                f"（来源：§四 {n_four} 项 / §二 {len(items) - n_four} 项）")
        for rel, info in sorted(items.items()):
            out.say(f"     - {rel:<47} 源=§{info['section']} 第 {info['line']} 行"
                    f"{'（glob）' if info['glob'] else ''}")
        #: ★ 括号清单的成员**单独登记、不进 rc**：`data/cache/{prts,prts_calc,theresa}/`
        #: 那一行给的是「这一项」= `data/cache/`，成员是细节，且 `prts_calc/` 全仓零引用
        #: （只有这一行文档提到过）。把它做成硬要求，就是给这道闸门装一个永久假红。
        for rel, info in sorted(items.items()):
            for member in (info["members"] or []):
                sub = rel + member + "/"
                if not (root / sub).exists():
                    rep.info.append(f"DATA_CACHE_MEMBER_ABSENT {_a(sub)}")
                    out.say(f"     ! 括号成员不在：{sub}（登记，不进 rc；文档那一行给的是 "
                            f"{rel} 这一项）")

    # ---- 2. 库可读且没被掏空 -------------------------------------------- #
    out.say()
    for rel, tables in DB_TABLES:
        p = root / rel
        cmd = (f'sqlite3 "{_uri(p)}" '
               f'"PRAGMA integrity_check; select count(*) from <table>;"')
        if not p.is_file():
            out.say(f"[2] {rel}  cmd={cmd}  rc=1  读数=文件不在（第 1 条已逐项印过）")
            continue
        size = p.stat().st_size
        if size == 0:
            out.say(f"[2] {rel}  cmd={cmd}  rc=1  读数=0 字节（空文件；mode=ro 也读不出表）")
            red(f"DATA_DB_UNREADABLE {_a(rel)} size=0")
            continue
        try:
            con = sqlite3.connect(_uri(p), uri=True)
            integrity = con.execute("PRAGMA integrity_check").fetchone()[0]
        except Exception as e:  # noqa: BLE001
            out.say(f"[2] {rel}  cmd={cmd}  rc=1  读数=打不开：{type(e).__name__}: {e}")
            red(f"DATA_DB_UNREADABLE {_a(rel)} {_a(type(e).__name__)}")
            continue
        if integrity != "ok":
            out.say(f"[2] {rel}  cmd={cmd}  rc=1  读数=integrity_check={integrity}")
            red(f"DATA_DB_CORRUPT {_a(rel)} {_a(integrity)}")
            con.close()
            continue
        counts: dict[str, int] = {}
        bad = False
        for t in tables:
            try:
                n = con.execute(f'select count(*) from "{t}"').fetchone()[0]
            except Exception as e:  # noqa: BLE001
                out.say(f"     ! {rel} 表 {t} 数不出来：{type(e).__name__}: {e}")
                red(f"DATA_DB_UNREADABLE {_a(rel)} table={_a(t)}")
                bad = True
                continue
            counts[t] = n
            rep.put(f"{rel}/{t}", n, f"select count(*) from {t}（mode=ro）")
            if n == 0:
                red(f"DATA_DB_EMPTY {_a(rel)} {_a(t)}")
                bad = True
        con.close()
        show = "  ".join(f"{t}={counts.get(t, '-')}" for t in tables)
        out.say(f"[2] {rel}  cmd={cmd}  rc={1 if bad else 0}  "
                f"读数={size} 字节；integrity_check=ok；{show}")

    # ---- 3. 上游对账 ---------------------------------------------------- #
    out.say()
    if not (root / LEVEL_INDEX_REL).is_file():
        rep.instr.append(f"DATA_LEVEL_INDEX_ABSENT {_a(root / LEVEL_INDEX_REL)}")
        out.say(f"[3] 上游对账  rc=3  读数={LEVEL_INDEX_REL} 不在 —— 关卡索引是这条检查的"
                f"输入，读不到就不给判定（不是「数据坏了」）")
    else:
        try:
            check_upstream(root, rep, out)
        except Exception as e:  # noqa: BLE001
            rep.instr.append(f"DATA_UPSTREAM_UNREADABLE {_a(type(e).__name__)}")
            out.say(f"[3] 上游对账  rc=3  读数=对账过程读不到输入："
                    f"{type(e).__name__}: {e}")

    # ---- 4. 关卡分母（按集合判，不按数判） ------------------------------- #
    out.say()
    lvls, bad_fixtures = fixture_levels(fixtures)
    if not fixtures.is_dir():
        rep.instr.append(f"DATA_FIXTURES_ABSENT {_a(fixtures)}")
        out.say(f"[4] 关卡分母  rc=3  读数=夹具目录不在：{fixtures}")
    for b in bad_fixtures:
        red(f"DATA_FIXTURE_UNREADABLE {_a(b)}")
    if lvls and (root / LEVEL_INDEX_REL).is_file():
        try:
            cached = set(cached_levels_via_check_go_all(root))
            err = ""
        except Exception as e:  # noqa: BLE001
            cached, err = set(), f"{type(e).__name__}: {e}"
        if err:
            rep.instr.append(f"DATA_LEVEL_INDEX_UNREADABLE {_a(err)}")
            out.say(f"[4] 关卡分母  cmd=check_go_all.cached_levels()  rc=3  "
                    f"读数=索引读不出来：{err}")
        else:
            uncached = sorted(lv for lv in lvls if lv not in cached)
            for lv in uncached:
                red(f"DATA_LEVEL_UNCACHED {_a(lv)}")
            out.say(f"[4] 关卡分母  cmd=tools/check_go_all.py 的 cached_levels()"
                    f"（**同一份实现**）  rc={1 if uncached else 0}  "
                    f"读数=夹具引用的关卡 {len(lvls)} 个（去重后）、缓存可达 {len(cached)} 个、"
                    f"**缺 {len(uncached)} 个**")
            out.say("     ★ 这一条**按集合**判：每一份带顶层 stage 的打法，它引用的那一关"
                    "都必须有一份 level_*.json 在缓存里。分母缩一格就红，不需要谁去看"
                    "「55 变 2」那行字。")
            if uncached:
                for lv in uncached[:20]:
                    out.say(f"     - {lv}（{', '.join(lvls[lv])}）")
                if len(uncached) > 20:
                    out.say(f"     … 还有 {len(uncached) - 20} 关（机读行是全量）")
        rep.put("fixtures/referenced_levels", len(lvls),
                "fixtures/**/*.json 的顶层 stage 去重", floor=False,
                note="夹具侧的分母，跟着 fixtures/ 走，不作下限")

    #: 关卡文件计数**只登记、不作下限**（按需缓存：访问哪个键就落哪一份）。
    ark = root / ARK_LEVELS_REL
    lv_files = sorted(ark.rglob("level_*.json")) if ark.is_dir() else []
    rep.put("gamedata/level_files", len(lv_files),
            f"rglob level_*.json under {ARK_LEVELS_REL}", floor=False,
            note="按需缓存，只作事故对照，不作为判据下限")
    out.say(f"     · {ARK_LEVELS_REL} 下 level_*.json 共 {len(lv_files)} 份")

    # ---- 5. 两个纯文本输入的规模 ---------------------------------------- #
    out.say()
    briefs = root / "data" / "op-briefs.txt"
    if briefs.is_file():
        raw = briefs.read_bytes()
        n_lines = len(raw.decode("utf-8", "replace").splitlines())
        rep.put("data/op-briefs.txt/lines", n_lines, "op-briefs.txt 行数")
        rep.put("data/op-briefs.txt/bytes", len(raw), "op-briefs.txt 字节数", floor=False,
                note="字节数随行尾口径变，只登记")
        out.say(f"[5] data/op-briefs.txt  cmd=读文件数字节与行  rc=0  读数={len(raw)} 字节 / "
                f"{n_lines} 行")
    ranges = root / "data" / "ranges.json"
    if ranges.is_file():
        rg = _read_json(ranges)
        n = len(rg) if hasattr(rg, "__len__") else 0
        rep.put("data/ranges.json/codes", n, "ranges.json 顶层代号数")
        out.say(f"[5] data/ranges.json  cmd=读文件数顶层键  rc=0  读数={n} 个代号"
                f"（大小会变，所以下限取代号数不取字节数）")

    # ---- 6. 棘轮 -------------------------------------------------------- #
    out.say()
    ratchet = None
    ratchet_exists = ratchet_path.is_file()
    if ratchet_exists:
        try:
            ratchet = json.loads(ratchet_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001
            rep.instr.append(f"DATA_RATCHET_UNREADABLE {_a(ratchet_path)} "
                             f"{_a(type(e).__name__)}")
            out.say(f"[6] 棘轮  rc=3  读数=读不出来：{type(e).__name__}: {e}")
    if not ratchet_exists:
        rep.info.append(f"DATA_RATCHET_MISSING {_a(ratchet_path)}")
        out.say(f"[6] 棘轮  rc=0（**不设下限**）  读数=棘轮缺失：{ratchet_path}")
        out.say("     ★ 「没有棘轮」不许静默当成绿，所以这里显式印一行。生成命令：")
        out.say("       python tools/check_data_ready.py --write-ratchet")
    elif ratchet is not None:
        entries = ratchet.get("items") or {}
        lowered, raised, uncovered = [], [], []
        for name in sorted(rep.readings):
            cur = rep.readings[name]
            ent = entries.get(name)
            if ent is None:
                uncovered.append(name)
                continue
            if not cur.get("floor", True) or not ent.get("floor", True):
                continue
            was = ent.get("value")
            if not isinstance(was, int):
                continue
            if cur["value"] < was:
                lowered.append((name, was, ent.get("at", "?"), cur["value"], cur["at"]))
            elif cur["value"] > was:
                raised.append((name, was, ent.get("at", "?"), cur["value"], cur["at"]))
        for name, was, wat, now, nat in lowered:
            red(f"DATA_UNDERFILLED {_a(name)} ratchet={_a(was)}@{_a(wat)}"
                f" now={_a(now)}@{_a(nat)}")
        for name in uncovered:
            red(f"DATA_RATCHET_UNCOVERED {_a(name)} now={_a(rep.readings[name]['value'])}")
        for name, was, wat, now, nat in raised:
            rep.info.append(f"DATA_RATCHET_RAISABLE {_a(name)} ratchet={_a(was)}@{_a(wat)}"
                            f" now={_a(now)}@{_a(nat)} suggest={_a(now)}")
        out.say(f"[6] 棘轮  cmd=读 {ratchet_path}  "
                f"rc={1 if (lowered or uncovered) else 0}  读数=棘轮项 {len(entries)} 个；"
                f"低于棘轮 {len(lowered)} 项；可抬 {len(raised)} 项；"
                f"本次量到但棘轮里没有的 {len(uncovered)} 项")
        out.say(f"     棘轮生成时刻：{ratchet.get('generated_at', '?')}")
        for name, was, wat, now, nat in lowered:
            out.say(f"     ✗ {name}: 棘轮 {was}@{wat}  ←→  现读 {now}@{nat}")
        for name, was, wat, now, nat in raised:
            out.say(f"     ↑ {name}: 棘轮 {was}@{wat}  ←→  现读 {now}@{nat}"
                    f"  ⇒ 可以抬到 {now}（**不自动写**：要留下谁在什么时候抬的水位）")
        if uncovered:
            out.say("     ★ 本次量到但这些项棘轮里没有 ⇒ 计红（「没有棘轮」不许静默当绿）："
                    + ", ".join(uncovered))

    # ---- 汇总 ----------------------------------------------------------- #
    rc = EXIT_RED if rep.red else EXIT_OK
    if rep.instr:
        rc = EXIT_INSTRUMENT

    # ---- 7. 若要写棘轮（显式开关；永不自动） ----------------------------- #
    if write_ratchet:
        out.say()
        if rep.red and not force:
            out.say(f"★ --write-ratchet 被拒：本次判据红 {len(rep.red)} 条。"
                    f"从一份已知被掏空的数据上取水位，会把事故烙成正常。"
                    f"确实要写就加 --force。")
        else:
            payload = {
                "schema": "ak-tactic/data-watermarks@1",
                "generated_at": stamp(),
                "tool": "tools/check_data_ready.py --write-ratchet",
                "manifest": {
                    "path": DOC_REL,
                    "at": stamp(),
                    "items": sorted(rep.manifest),
                    "why": "权威清单从这份文档现解析（§四 落点一览代码块 ＋ §二 本地落点栏），"
                           "不另抄一份",
                },
                "incident_anchors": INCIDENT_ANCHORS,
                "items": rep.readings,
            }
            ratchet_path.parent.mkdir(parents=True, exist_ok=True)
            ratchet_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
            out.say(f"★ 已写棘轮 {ratchet_path}（{len(rep.readings)} 项）。每一项都带取数"
                    f"时刻与来源；`floor=false` 的那几项只登记、不作下限。")

    out.say()
    out.say(f"结论：{'全绿' if rc == 0 else ('判据红' if rc == 1 else '仪器缺输入')}"
            f"（rc={rc}；红 {len(rep.red)} 条、仪器缺 {len(rep.instr)} 条）")
    for line in rep.red:
        out.mline(line)
    for line in rep.instr:
        out.mline(line)
    for line in rep.info:
        out.mline(line)
    print(f"DATA_READY rc={rc} manifest={len(rep.manifest)} "
          f"missing={sum(1 for x in rep.red if x.startswith('DATA_MISSING'))} "
          f"underfilled={sum(1 for x in rep.red if x.startswith('DATA_UNDERFILLED'))} "
          f"uncached={sum(1 for x in rep.red if x.startswith('DATA_LEVEL_UNCACHED'))} "
          f"red={len(rep.red)} instrument={len(rep.instr)}")
    return rc


# --------------------------------------------------------------------------- #
# 6. 正负对照
# --------------------------------------------------------------------------- #

def _child_env() -> dict:
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_child(argv: list[str]) -> tuple[int, str]:
    p = subprocess.run([sys.executable, str(Path(__file__).resolve())] + argv,
                       capture_output=True, env=_child_env(), cwd=str(REPO))
    return p.returncode, (p.stdout or b"").decode("utf-8", "replace")


def selftest(root: Path) -> int:
    """四组合成输入：一组必绿、三组必红（含一组按集合判红），全部真进分支、真影响 rc。"""
    tmp = Path(tempfile.mkdtemp(prefix="data-ready-selftest-"))
    doc_src = root / DOC_REL
    idx_src = root / LEVEL_INDEX_REL
    fix_src = root / FIXTURES_REL

    def build_base(name: str) -> Path:
        base = tmp / name
        (base / "docs").mkdir(parents=True)
        (base / "data" / "gamedata").mkdir(parents=True)
        (base / DOC_REL).write_bytes(doc_src.read_bytes())
        if idx_src.is_file():
            (base / LEVEL_INDEX_REL).write_bytes(idx_src.read_bytes())
        if fix_src.is_dir():
            for f in fix_src.rglob("*"):
                if f.is_file():
                    dst = base / FIXTURES_REL / f.relative_to(fix_src)
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    dst.write_bytes(f.read_bytes())
        return base

    results: list[tuple[str, str, int, str]] = []

    # ---- 对照 A：必绿（真树 ＋ 由真树现取的棘轮） ------------------------ #
    r_live = tmp / "live-ratchet.json"
    rc_w, _ = _run_child(["--root", str(root), "--ratchet", str(r_live),
                          "--write-ratchet"])
    rc_a, out_a = _run_child(["--root", str(root), "--ratchet", str(r_live)])
    results.append(("A-green-live", "0", rc_a,
                    f"取棘轮 rc={rc_w}；带棘轮复跑 rc={rc_a}；"
                    f"underfilled={out_a.count('DATA_UNDERFILLED')}"))

    # ---- 对照 B：必红（有一个库被换成空文件） ---------------------------- #
    base_b = build_base("b-empty-db")
    (base_b / "data" / "akdb.sqlite").write_bytes(b"")
    rc_b, out_b = _run_child(["--root", str(base_b), "--ratchet", str(r_live)])
    results.append(("B-red-empty-db", "1", rc_b,
                    f"missing={out_b.count('DATA_MISSING')} "
                    f"db_unreadable={out_b.count('DATA_DB_UNREADABLE')}"))

    # ---- 对照 C：必红（棘轮被抬高 ⇒ 现读必然低于棘轮） ------------------- #
    inflated = json.loads(r_live.read_text(encoding="utf-8"))
    for v in (inflated.get("items") or {}).values():
        if v.get("floor", True) and isinstance(v.get("value"), int):
            v["value"] = v["value"] * 2
    r_hi = tmp / "inflated-ratchet.json"
    r_hi.write_text(json.dumps(inflated, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    rc_c, out_c = _run_child(["--root", str(root), "--ratchet", str(r_hi)])
    results.append(("C-red-ratchet-high", "1", rc_c,
                    f"underfilled={out_c.count('DATA_UNDERFILLED')}"))

    # ---- 对照 D：必红（分母缩了：按集合判） ------------------------------ #
    base_d = build_base("d-level-gone")
    (base_d / FIXTURES_REL / "plan-selftest-bogus.json").write_text(
        json.dumps({"stage": "selftest_zz_not_a_level", "title": "负对照", "deploys": []},
                   ensure_ascii=False), encoding="utf-8")
    rc_d, out_d = _run_child(["--root", str(base_d), "--ratchet", str(r_live)])
    results.append(("D-red-level-uncached", "1", rc_d,
                    f"level_uncached={out_d.count('DATA_LEVEL_UNCACHED')}"))

    print("=" * 88)
    print("check_data_ready --selftest：四组合成输入（一组必绿、三组必红）")
    print("=" * 88)
    bad = 0
    for name, want, got, note in results:
        ok = str(got) == want
        if not ok:
            bad += 1
        print(f"{'✓' if ok else '✗'} {name:<22} expect_rc={want} got_rc={got}  {note}")
        print(f"    DATA_SELFTEST {name} expect={want} got={got} ok={1 if ok else 0}")
    print()
    print(f"结论：{'四组对照全部如期' if not bad else f'★ {bad} 组对照不成立 —— 整批读数作废'}"
          f"（rc={0 if not bad else 1}）")
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="check_data_ready.py",
        description="data/ 完整性速检：清单缺项 / 库被掏空 / 上游对账 / 棘轮 / 关卡分母")
    ap.add_argument("--root", default=str(REPO), help="仓库根（默认本文件的上两级）")
    ap.add_argument("--ratchet", default=None, help=f"棘轮文件（默认 <root>/{RATCHET_REL}）")
    ap.add_argument("--selftest", action="store_true", help="跑正负对照，不跑真检查")
    ap.add_argument("--write-ratchet", action="store_true",
                    help="把本次现读写成棘轮文件（显式；判据红时拒绝，除非 --force）")
    ap.add_argument("--force", action="store_true",
                    help="与 --write-ratchet 合用：允许在判据红时也写")
    ap.add_argument("--quiet", action="store_true", help="散文静音（机读行照印）")
    args = ap.parse_args(argv)
    root = Path(args.root).resolve()
    ratchet = Path(args.ratchet).resolve() if args.ratchet else root / RATCHET_REL
    if args.selftest:
        return selftest(root)
    return run(root, ratchet, write_ratchet=args.write_ratchet, force=args.force,
               quiet=args.quiet)


if __name__ == "__main__":
    try:
        _rc = main()
    except SystemExit:
        raise
    except BaseException as _e:  # noqa: BLE001 - 崩了必须是一个与业务态不重叠的值
        print(f"DATA_CRASH EXC={type(_e).__name__}: {_e}")
        _rc = EXIT_CRASH
    try:
        sys.stdout.flush()
    except Exception:  # noqa: BLE001
        pass
    raise SystemExit(_rc)
