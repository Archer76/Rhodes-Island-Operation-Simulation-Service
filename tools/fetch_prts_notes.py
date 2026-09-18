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

#: 天赋参数的**两种命名**：多数页写 `|天赋1=`，而有些页（联动干员等，如虎狼丸）
#: 写作 `|第一天赋1=` / `|第二天赋1=`。
#:
#: 2026-09-19 实测的教训：只认前者时，虎狼丸的天赋效果**一条都没落**，`--verify`
#: 于是报它"连正文都没有"——而页面上明明有「黑色猎犬」五档效果全文。**判据要按
#: 运行时实际怎么命名走**，不要按"我以为的模板长什么样"走。
_TALENT = r"\|\s*(?:第[一二三四]天赋|天赋)\d*"

#: 取「这一条备注说的是谁」用的锚点，**按顺序回溯最近的一个**。
#: 天赋模板里是 `|天赋1=名字`、技能模板里是 `|技能名=名字`；
#: 两者都没有就归到 `其他`——不硬塞给上一个锚点（那会把特性备注算到末位天赋头上）。
_ANCHORS = (
    ("天赋", re.compile(_TALENT + r"\s*=\s*([^\n|}]*)")),
    ("技能", re.compile(r"\|\s*技能名\s*=\s*([^\n|}]*)")),
)

#: 顺手存下来的正文（供提议器做语义对照）：天赋效果与技能专精3描述。
_FACTS = (
    ("天赋效果", re.compile(_TALENT + r"效果\s*=\s*([^\n]*)")),
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


#: **不抓**的页面：模式限定的同形页。
#:
#: 博士 2026-09-19 裁定：暮落有**日常版**与**集成战略限定版**两个，**去掉限定
#: 那个**。列在这里的页名既不抓、也不进差集（否则会被当成"本地缺数据"）。
SKIP_PAGES = {"暮落(集成战略)"}

#: **不抓**的 charId：同一个干员的非日常形态。
#:
#: 判据不是名字（两个暮落都叫「暮落」），而是数据：`char_512_aprot` 的
#: `raw_json.isNotObtainable = True`、没有编号；日常版 `char_4025_aprot2` 有
#: 编号 `VC07` 且 `itemObtainApproach = 集成战略获得`（集成战略**赠送**干员，
#: 日常可用——博士 2026-09-19 明确过）。
SKIP_CHARS = {"char_512_aprot"}

#: 页面里那一行「这一页是谁」——`|干员id=char_xxxx`。
_ID_PARAM = re.compile(r"\|\s*干员id\s*=\s*(char_[A-Za-z0-9_]+)")


def _page_id(text: str) -> str:
    """取页面自己写的 `|干员id=`（取不到返回空串）。

    **这才是"这一页是谁"的判据**：阿米娅的三个形态在游戏库里都叫「阿米娅」，
    PRTS 上基础页同名、另两个带括号消歧，靠名字分不开；页面里这一行才分得开。
    """
    m = _ID_PARAM.search(text or "")
    return m.group(1) if m else ""


def _resolve(cli, name: str, char_id: str = "") -> tuple[str, str]:
    """取页面并**按 `|干员id=` 校验**，对不上就找带括号的消歧页。

    2026-09-19 实测的坑：`阿米娅(近卫)`/`阿米娅(医疗)` 的页名带括号，而库里两个
    形态的名字都是「阿米娅」——只按名字取页，会把三个形态**全抓成同一个基础页**
    （正文里是「？？？？？」和后勤技能，一条机制都没有），而 `--verify` 只看
    "有没有正文"，于是**一路绿灯**。所以取到页先验 id，不符就搜「名字(」拿候选
    逐个验 id；全都不符就如实报错，绝不拿错页充数。
    """
    kept: list[str] = []

    def _try(title: str) -> str:
        """取这一页；**页名不符 or 是子页面 or id 不符**都算不成。

        ⚠️ 子页面必须挡掉：实测 `阿米娅(医疗)/语音记录`、`暮落(集成战略)/spine`
        这类页面**没有 `|干员id=`**，只按时"有没有正文"判会让它们一路通过，
        最后落进库里的是 0 条备注 0 条正文的语音页。所以：名字带 `/` 的直接拒。
        """
        if title in SKIP_PAGES or "/" in title:
            return ""
        try:
            txt = cli.wikitext(title)
        except Exception:                           # noqa: BLE001
            return ""
        if not txt:
            return ""
        pid = _page_id(txt)
        if not char_id:                             # 不知道期望 id 时，只认带 id 的
            return title if pid else ""
        if pid == char_id:
            kept.append(title)
            return title
        if not pid:                                 # 页里没写 id：留作**末位**候选
            kept.append(title)
            return ""
        return ""

    def _resolve_pass(require_id: bool) -> str:
        """先只认 id 相符的页；一轮都不成才退到"页里没写 id"的候选。"""
        hit = _try(name)
        if hit:
            return hit
        for prefix in (f"{name}(", f"{name}（"):
            try:
                cands = cli.search_pages(prefix) or []
            except Exception:                       # noqa: BLE001
                cands = []
            for c in cands[:10]:
                t = c if isinstance(c, str) else (c.get("title") or "")
                if not t or not t.startswith(name):
                    continue
                ok = _try(t)
                if ok:
                    return ok
        try:
            cands = cli.search_pages(name) or []
        except Exception:                           # noqa: BLE001
            cands = []
        for c in cands[:8]:
            t = c if isinstance(c, str) else (c.get("title") or "")
            ok = _try(t) if t else ""
            if ok:
                return ok
        return ""

    hit = _resolve_pass(True)
    if hit:
        return hit, ""
    if not char_id:
        for t in kept:                              # 没有期望 id：接受无 id 的候选
            return t, ""
    return "", f"按名取页不成；搜索无 id 相符的候选（期望 {char_id or '?'}）"


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
        if cid in SKIP_CHARS:
            # 非日常形态：既不抓，也不留下旧的页——不然它会一直挂在库里
            con.execute("DELETE FROM page WHERE char_id=?", (cid,))
            con.execute("DELETE FROM note WHERE char_id=?", (cid,))
            con.execute("DELETE FROM fact WHERE char_id=?", (cid,))
            con.commit()
            skip += 1
            continue
        if not refresh and cid in done:
            skip += 1
            continue
        page, err = _resolve(cli, name, cid)
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


def diff_with_prts() -> int:
    """对 PRTS 的**「干员」分类**做差集：本地还缺谁。

    为什么不走 Cargo：2026-09-19 实试 `chara` / `characters` 两种表名与三种字段
    拼法，**全部报 MWException**——表名不可猜。分类成员这条路不依赖 schema，
    稳定，且回答的正是"本地有没有漏人"。

    ⚠️ **判据是 `charId`，不是名字**。PRTS 用括号消歧（`阿米娅(近卫)`、
    `暮落(集成战略)`、`预备干员-先锋(卫戍协议)`…），本地库用基名或另一套名字；
    拿名字做差集会把它们全报成"缺数据"，而其实人就在库里。页面的
    `|干员id=char_xxxx` 才是同一把钥匙。

    ⚠️ **括号后缀也不是"模式专用"的判据**：博士 2026-09-19 指出阿米娅的两个
    升变形态与暮落（集成战略赠送）**都是日常可用**。所以本函数只做**id 级差集**、
    如实分栏，不替人下"这个算不算"的结论。
    """
    import ak_tactic.prts as P                                  # noqa: PLC0415

    cli = P.default_client()
    names = cli.category_members("干员")
    print(f"PRTS「干员」分类：{len(names)} 个页面")
    con = _connect()
    have = {r[0]: (r[1], r[2]) for r in con.execute(
        "SELECT char_id, name, ok FROM page")}
    ak = ROOT / "data" / "akdb.sqlite"
    local_ids: set[str] = set()
    local_names: set[str] = set()
    if ak.exists():
        import sqlite3                                          # noqa: PLC0415
        c2 = sqlite3.connect(ak)
        for cid, nm in c2.execute(
                "SELECT char_id, name FROM operator WHERE is_operator=1"):
            local_ids.add(cid)
            local_names.add(nm)
        c2.close()

    no_page = [n for n in names
               if n not in {v[0] for v in have.values()} and n not in SKIP_PAGES]
    print(f"\n① 有页但**抓失败**（{sum(1 for v in have.values() if not v[1])}）")
    print(f"② PRTS 分类里有、**本地没抓到页**（{len(no_page)}）——逐页解析 干员id：")
    real_gap: list[str] = []
    for n in no_page:
        try:
            wt = cli.try_wikitext(n) or ""
        except Exception:                                       # noqa: BLE001
            wt = ""
        m = re.search(r"\|\s*干员id\s*=\s*(char_[A-Za-z0-9_]+)", wt)
        cid = m.group(1) if m else ""
        in_local = "**库里没有**" if (cid and cid not in local_ids) else \
                   ("库里有（只是页名不同）" if cid else "页里取不到 干员id")
        if cid and cid not in local_ids:
            real_gap.append(f"{n}({cid})")
        print(f"     {n} → {cid or '?'}：{in_local}")
    print(f"\n③ **真缺口**（PRTS 有、本地游戏库按 charId 查不到）：{len(real_gap)}"
          f" {real_gap}")
    only_local = sorted(local_names - set(names))
    print(f"④ 本地库有、PRTS 分类里没有同名页（{len(only_local)}，含 token/陷阱/异名）："
          f"{only_local[:12]}")
    return 0


def main() -> None:
    ap = argparse.ArgumentParser(description="抓 PRTS 干员页备注（本地工作库）")
    ap.add_argument("--limit", type=int, default=0, help="只抓前 N 位（试跑）")
    ap.add_argument("--only", default="", help="只抓名字含该子串的")
    ap.add_argument("--report", action="store_true", help="只看已抓到的统计")
    ap.add_argument("--refresh", action="store_true", help="忽略已抓的，重抓")
    ap.add_argument("--diff", action="store_true",
                    help="对 PRTS「干员」分类做差集（本地缺了谁）")
    a = ap.parse_args()
    if a.diff:
        raise SystemExit(diff_with_prts())
    raise SystemExit(report() if a.report else fetch(a.limit, a.only, a.refresh))


if __name__ == "__main__":
    main()
