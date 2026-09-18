"""把 PRTS 干员页的「备注」抓下来落盘（**本地工作库，不进仓库**）。

为什么要有这个脚本
------------------
干员机制的权威出处是 PRTS 干员页里的 `|备注=` / `|特性备注=`（技能与天赋模板的
※ 段）。此前每做一条机制都要人工开一次页面去抄：慢，而且"抄没抄全"没人知道。
这个脚本按名册逐页抓下来，写进 `data/prts-notes.sqlite`，供
`tools/semantics_propose.py` 离线查，也供人复核。

三条设计
--------
1. **落本地库、不进仓库**：备注正文是第三方内容（PRTS 是 CC BY-SA），本仓库
   不分发它——`data/*.sqlite` 已在 `.gitignore` 里，数据留在本机。脚本本身
   （抓取逻辑）可以进仓库。
2. **页面名先按名册名试，失败再用搜索兜**：名册名与 PRTS 页面名并非总一致
   （异格、带后缀的名字最容易分家）。两次都失败就如实记为失败，不猜。
3. **可续跑**：已抓成功的页直接跳过；再配上 `ak_tactic.prts` 自带的磁盘缓存，
   重跑几乎不联网。

用法：
    python tools/fetch_prts_notes.py              # 增量抓全部干员
    python tools/fetch_prts_notes.py --limit 5    # 只抓前 5 位（试跑）
    python tools/fetch_prts_notes.py --only 凯尔希 # 名字含该子串的
    python tools/fetch_prts_notes.py --report     # 只看已抓到什么（不联网）
    python tools/fetch_prts_notes.py --refresh    # 忽略已抓的，重抓
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB_PATH = ROOT / "data" / "akdb.sqlite"
OUT_PATH = ROOT / "data" / "prts-notes.sqlite"

#: 备注字段的两种写法：普通备注与特性备注（特性模板用后者）。
_NOTE_FIELDS = ("备注", "特性备注")

#: 取「这一条备注说的是谁」用的锚点，**按顺序回溯最近的一个**。
#: 天赋模板里是 `|天赋1=名字`、技能模板里是 `|技能名=名字`；
#: 两者都没有就归到 `其他`——不硬塞给上一个锚点（那会把特性备注算到末位天赋头上）。
_ANCHORS = (
    ("天赋", re.compile(r"\|\s*天赋\d*\s*=\s*([^\n|}]*)")),
    ("技能", re.compile(r"\|\s*技能名\s*=\s*([^\n|}]*)")),
)

#: 顺手存下来的正文（供提议器做语义对照）：天赋效果与技能专精3描述。
_FACTS = (
    ("天赋效果", re.compile(r"\|\s*天赋\d*效果\s*=\s*([^\n]*)")),
    ("技能描述", re.compile(r"\|\s*技能专精3描述\s*=\s*([^\n]*)")),
)


def _strip_markup(text: str) -> str:
    """去掉 wiki 标记，只留人读得懂的正文。

    只做四件事，**不追求渲染成最终样子**：清注释、清 `<br>` 系列、把
    `{{color|#xxx|正文}}` / `{{+|值|显示}}` / `{{术语|键|显示}}` 这类模板取正文、
    去掉残余的花括号与链接括号。意义在于：提议器要按关键词找语义，而原始
    wikitext 里「阻挡范围扩大」被 `{{|0.23|0.23倍}}` 切得七零八落。
    """
    t = re.sub(r"<!--.*?-->", "", text, flags=re.S)
    t = re.sub(r"<br\s*/?>", "\n", t)
    t = re.sub(r"<[^>]+>", "", t)
    # {{模板|参数1|参数2|…}}：取**最后一个**非空参数（多数模板最后一项才是显示文本）
    for _ in range(4):                      # 模板可嵌套，多跑几轮
        t = re.sub(r"\{\{[^{}]*\|([^{}|]*)\}\}", r"\1", t)
        t = re.sub(r"\{\{[^{}]*\}\}", "", t)
    t = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", t)
    t = re.sub(r"\[\[([^\]]*)\]\]", r"\1", t)
    t = t.replace("<", "").replace(">", "")
    return t.strip()


def _anchored_notes(text: str) -> list[tuple[str, str, str]]:
    """抽出全部备注，返回 `(kind, anchor, note)`。

    `anchor` 是「这条备注挂在哪个天赋/技能上」——按**最近的锚点**回溯取，
    取不到就是空串（特性备注、或模板写法变了）。
    """
    out: list[tuple[str, str, str]] = []
    for m in re.finditer(r"\|\s*(特性备注|备注)\s*=\s*", text):
        field = m.group(1)
        start = m.end()
        nxt = re.search(r"\n\s*\|", text[start:])
        raw = text[start:start + (nxt.start() if nxt else 600)]
        note = _strip_markup(raw)
        if not note:
            continue
        if field == "特性备注":
            out.append(("特性", "", note))
            continue
        head = text[:m.start()]
        kind, anchor = "其他", ""
        best = -1
        for k, pat in _ANCHORS:
            for am in pat.finditer(head):
                if am.start() > best:
                    best, kind, anchor = am.start(), k, _strip_markup(am.group(1))
        out.append((kind, anchor, note))
    return out


def _facts(text: str) -> list[tuple[str, str, str]]:
    """顺手存下来的正文事实：`(kind, anchor, value)`。"""
    out: list[tuple[str, str, str]] = []
    for kind, pat in _FACTS:
        for m in pat.finditer(text):
            val = _strip_markup(m.group(1))
            if val:
                out.append((kind, "", val))
    return out


def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(OUT_PATH)
    c.executescript(
        """
        CREATE TABLE IF NOT EXISTS page (
            char_id  TEXT PRIMARY KEY,
            name     TEXT,
            page     TEXT,
            ok       INTEGER,
            note     TEXT,
            n_notes  INTEGER,
            fetched  TEXT
        );
        CREATE TABLE IF NOT EXISTS note (
            char_id TEXT, kind TEXT, anchor TEXT, text TEXT
        );
        CREATE TABLE IF NOT EXISTS fact (
            char_id TEXT, kind TEXT, value TEXT
        );
        """)
    return c


def _resolve(cli, name: str) -> tuple[str, str]:
    """按名册名取页面；失败的用搜索兜一次。返回 `(页面名, 失败原因)`。"""
    try:
        txt = cli.wikitext(name)
        if txt:
            return name, ""
        return "", "wikitext 返回空"
    except Exception as exc:                       # noqa: BLE001 —— 如实记录，不吞
        first = f"{type(exc).__name__}: {exc}"
    try:
        hits = cli.search_pages(name) or []
    except Exception as exc:                       # noqa: BLE001
        return "", f"{first}；搜索也失败：{type(exc).__name__}: {exc}"
    for hit in hits[:5]:
        title = hit if isinstance(hit, str) else (
            hit.get("title") or hit.get("page") or "")
        if not title:
            continue
        try:
            if cli.wikitext(title):
                return title, ""
        except Exception:                          # noqa: BLE001
            continue
    return "", f"{first}；搜索无可用候选"


def fetch(limit: int, only: str, refresh: bool) -> int:
    sys.path.insert(0, str(ROOT))
    import ak_tactic.prts as prts                    # noqa: PLC0415

    cli = prts.default_client()
    roster = sqlite3.connect(DB_PATH)
    rows = roster.execute(
        "SELECT char_id, name FROM operator WHERE is_operator=1 "
        "ORDER BY sort_index").fetchall()
    if only:
        rows = [r for r in rows if only in r[1]]
    if limit:
        rows = rows[:limit]

    con = _connect()
    done = {r[0] for r in con.execute("SELECT char_id FROM page WHERE ok=1")}
    ok = fail = skip = 0
    for i, (cid, name) in enumerate(rows, 1):
        if not refresh and cid in done:
            skip += 1
            continue
        page, err = _resolve(cli, name)
        if not page:
            con.execute(
                "INSERT OR REPLACE INTO page VALUES (?,?,?,?,?,?,datetime('now'))",
                (cid, name, "", 0, err[:300], 0))
            con.commit()
            fail += 1
            print(f"[{i}/{len(rows)}] {name} —— 失败：{err[:90]}", flush=True)
            continue
        text = cli.wikitext(page)
        notes = _anchored_notes(text)
        facts = _facts(text)
        con.execute("DELETE FROM note WHERE char_id=?", (cid,))
        con.execute("DELETE FROM fact WHERE char_id=?", (cid,))
        con.executemany("INSERT INTO note VALUES (?,?,?,?)",
                        [(cid, k, a, t) for k, a, t in notes])
        con.executemany("INSERT INTO fact VALUES (?,?,?)",
                        [(cid, k, v) for k, _, v in facts])
        con.execute(
            "INSERT OR REPLACE INTO page VALUES (?,?,?,?,?,?,datetime('now'))",
            (cid, name, page, 1, "", len(notes)))
        con.commit()
        ok += 1
        print(f"[{i}/{len(rows)}] {name} → {page}：{len(notes)} 条备注、"
              f"{len(facts)} 条正文", flush=True)
        time.sleep(0.2)
    print(f"\n完成：成功 {ok}、失败 {fail}、跳过（已抓过）{skip}")
    return 0 if fail == 0 else 1


def report() -> int:
    if not OUT_PATH.exists():
        print(f"还没有 {OUT_PATH.relative_to(ROOT)}——先跑一次抓取。")
        return 0
    con = _connect()
    tot, ok, notes = con.execute(
        "SELECT COUNT(*), SUM(ok=1), SUM(n_notes) FROM page").fetchone()
    print(f"页面 {tot} 条：成功 {ok or 0}、失败 {(tot or 0) - (ok or 0)}；"
          f"备注合计 {notes or 0} 条")
    print("\n按挂靠物分：")
    for kind, cnt in con.execute(
            "SELECT kind, COUNT(*) FROM note GROUP BY kind ORDER BY 2 DESC"):
        print(f"  {kind}: {cnt}")
    print("\n抓失败的（前 15）：")
    for name, note in con.execute(
            "SELECT name, note FROM page WHERE ok=0 LIMIT 15"):
        print(f"  {name}: {(note or '')[:80]}")
    print("\n备注里最常出现的关键词（前 20，按命中干员数）：")
    for pat, cnt in con.execute(
            "SELECT '阻挡半径倍率', COUNT(DISTINCT char_id) FROM note "
            "WHERE text LIKE '%阻挡半径倍率%' "
            "UNION ALL SELECT '视为', COUNT(DISTINCT char_id) FROM note "
            "WHERE text LIKE '%视为%' "
            "UNION ALL SELECT '取最高', COUNT(DISTINCT char_id) FROM note "
            "WHERE text LIKE '%取最高%' "
            "UNION ALL SELECT '不可叠加', COUNT(DISTINCT char_id) FROM note "
            "WHERE text LIKE '%不可叠加%'"):
        print(f"  {pat}: {cnt} 位干员")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="抓 PRTS 干员页备注（本地工作库）")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 位（试跑）")
    ap.add_argument("--only", default="", help="只抓名字含该子串的")
    ap.add_argument("--report", action="store_true", help="只看已抓到的统计")
    ap.add_argument("--refresh", action="store_true", help="忽略已抓的，重抓")
    a = ap.parse_args()
    raise SystemExit(report() if a.report else fetch(a.limit, a.only, a.refresh))


if __name__ == "__main__":
    main()
