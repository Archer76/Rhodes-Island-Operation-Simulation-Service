#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主线关卡**分层表** —— 把「434」这个数拆成可判的几层。

## 为什么必须先做这一步

派工时给的是「主线关卡存量 434 关」。那个数**不能当工作量用**，因为它至少混了
四件不同的事：

1. `stage` 表里 `stage_type='MAIN'` 的**行数**；
2. 其中 `level_id` 前缀是 `main_` 的行数；
3. 去掉「同一关的多档难度」之后**真正的关卡数**（主键是 levelId 不是 code）；
4. 其中**真有数据、真能进 Go** 的那些。

同一关在表里可以有多行：`main_00-01`（标准实战）、`main_00-01#f#`（突袭）、
以及第 9 章起的 `easy_*`（剧情体验）与 `tough_*`（磨难险地）——**它们是同一关
（同一个 `code`）的三档难度**，不是三关。

★ 本仓铁律：**两套分母的数不许并列**。所以本工具把每个数都挂上口径标签，
并在表头显式写「跨行不可比」。

## 三件口径各自是什么

* **口径 R（行）**：`stage` 表的行数。口径 B 与它同分母，可以直接比。
* **口径 M（main_ 行）**：`level_id` 前缀 `main_`。这是**标准实战**那一档。
* **口径 C（关卡）**：去重 `code` 之后的关卡号数。**只有它可以当工作量分母。**
  与 R/M **跨行不可比**（同一关多档难度 ⇒ C 小于 M）。

## 数据齐备性问的是「源上有没有」，不是「本地有没有」

权威全量是关卡索引 `data/gamedata/_level_index.json`（`levelId -> data_path`）。
**本地缓存目录不是权威清单**——它反映的是「过去谁取过」（PM 2026-09-20 通告 #1）。
所以本工具把两者分两栏印，并给缓存栏打上「非权威」标签。

## 第二道闸（`simgo.skills.port_reasons`）

`--gate <levelId>...` 会对指定关卡**真取数**并跑一次闸门，给出：
* **关卡侧**理由（`SpecInputs.from_stage` + `unsupported_reasons`，零人排程）；
* 逐条理由原文。

⚠ 这条口径只证明「**技能结构被认识**」，**不证明效果值正确**。
⚠ 取数有副作用（会往 `data/gamedata/` 写缓存）——见 PM 通告 #1 第四节第 2 条。

用法:
    python tools\\mainline_strata.py                      # 分层表（不联网）
    python tools\\mainline_strata.py --json out/mainline-strata.json
    python tools\\mainline_strata.py --gate main_00-01 main_01-07
"""
from __future__ import annotations

import argparse
import collections
import json
import sqlite3
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

DB = ROOT / "data" / "akdb.sqlite"
INDEX = ROOT / "data" / "gamedata" / "_level_index.json"

#: 口径标签。**改口径要连标签一起改**，不许让同名标签换含义。
K_R = "R 行(stage表 MAIN)"
K_M = "M 行(level_id main_*)"
K_C = "C 关(去重 code)"
K_F = "F 行(突袭 #f#)"

#: 关卡号 → 章。`0-1` → 0；`9-2` → 9；`S2-1` → S2；`TR-1` → TR1。
#: ⚠ 正则必须容 `S2-1` 这种「字母紧跟数字、再跟短横」的写法——
#: 第一版写成 `(?:([A-Za-z]+)[-_])?(\d+)`，对 `S2-1` 直接失配，
#: 53 行（含 33 行 main_）被静默丢进 `?` 章。**失配要报出来，不许当 0。**
_CH_RE = re.compile(r"^([A-Za-z]*)[-_]?(\d+)")


def chapter_of(code: str) -> str:
    """把关卡号折成章标签。折不出来返回 `?`（**不许静默当 0 章**）。"""
    c = (code or "").strip()
    if not c:
        return "?"
    m = _CH_RE.match(c)
    if not m:
        return "?"
    pre, num = m.group(1), m.group(2)
    return f"{pre}{num}" if pre else num


def suffix_of(level_id: str) -> str:
    """`main_00-01#f#` → `#f#`；无后缀返回空串。"""
    i = level_id.find("#")
    return level_id[i:] if i >= 0 else ""


def load_rows() -> list[dict]:
    con = sqlite3.connect(str(DB))
    con.row_factory = sqlite3.Row
    cur = con.execute(
        "SELECT level_id, code, difficulty, zone_id, data_path, name, "
        "diff_group, hard_level_id FROM stage WHERE stage_type='MAIN'")
    rows = [dict(r) for r in cur.fetchall()]
    con.close()
    return rows


def load_index() -> dict:
    if not INDEX.exists():
        return {}
    return json.loads(INDEX.read_text(encoding="utf-8"))


def cached_level_ids() -> set[str]:
    """本地缓存里的关卡（**非权威**：只说明「过去取过」）。"""
    base = ROOT / "data" / "gamedata"
    out: set[str] = set()
    if not base.is_dir():
        return out
    for p in base.rglob("level_*.json"):
        stem = p.stem                      # level_main_00-01
        if stem.startswith("level_"):
            out.add(stem[len("level_"):])
    return out


def strata() -> dict:
    rows = load_rows()
    idx = load_index()
    cache = cached_level_ids()

    by_ch_r: collections.Counter = collections.Counter()
    by_ch_m: collections.Counter = collections.Counter()
    codes_by_ch: dict[str, set] = collections.defaultdict(set)
    codes_m_by_ch: dict[str, set] = collections.defaultdict(set)
    by_ch_f: collections.Counter = collections.Counter()
    ch_order: list[str] = []
    unparsed: list[str] = []
    for r in rows:
        ch = chapter_of(r["code"])
        if ch == "?":
            unparsed.append(f"{r['level_id']} (code={r['code']!r})")
        if ch not in by_ch_r:
            ch_order.append(ch)
        by_ch_r[ch] += 1
        if r["level_id"].startswith("main_"):
            by_ch_m[ch] += 1
            codes_m_by_ch[ch].add(r["code"])
        codes_by_ch[ch].add(r["code"])
        if suffix_of(r["level_id"]) == "#f#":
            by_ch_f[ch] += 1

    def sort_key(ch: str):
        m = _CH_RE.match(ch)
        if m:
            return (0 if not m.group(1) else 1, m.group(1) or "", int(m.group(2)))
        return (2, ch, 0)

    ch_order.sort(key=sort_key)

    main_rows = [r for r in rows if r["level_id"].startswith("main_")]
    main_ids = [r["level_id"] for r in main_rows]
    #: ★ 口径 C 也要分家：**main_ 那一档的关卡数**才是「主线标准实战」的工作量分母。
    #: 全部 MAIN 行的去重 code 数把 sub_/tr_ 也算进来了 —— 两者不可混。
    c_all = len({r["code"] for r in rows})
    c_main = len({r["code"] for r in main_rows})
    per_prefix: dict[str, dict] = {}
    for p in ("main", "easy", "tough", "sub", "tr"):
        sel = [r for r in rows if r["level_id"].split("_")[0] == p]
        if not sel:
            continue
        per_prefix[p] = {"rows": len(sel),
                         "codes": len({r["code"] for r in sel}),
                         "four_star": sum(1 for r in sel
                                          if suffix_of(r["level_id"]) == "#f#")}

    #: 数据齐备性：DB 的 levelId 与索引（权威）对账。
    db_ids = {r["level_id"] for r in rows}
    in_index = sorted(i for i in db_ids if i in idx)
    not_in_index = sorted(i for i in db_ids if i not in idx)
    index_has_no_db = sorted(set(idx) - db_ids)
    cached_hit = sorted(i for i in db_ids if i in cache)

    #: 难度两轴（正交，不能压成一栏）
    diff_group = collections.Counter(r["diff_group"] for r in rows)
    difficulty = collections.Counter(r["difficulty"] for r in rows)
    has_hard = sum(1 for r in rows if r["hard_level_id"])
    suffix_cnt = collections.Counter(suffix_of(r["level_id"]) for r in rows)
    #: 同一 code 有几档难度
    per_code = collections.Counter(r["code"] for r in rows)
    mult = collections.Counter(per_code.values())

    return {
        "db": str(DB.relative_to(ROOT)),
        "index": str(INDEX.relative_to(ROOT)),
        "totals": {
            K_R: len(rows),
            K_M: len(main_ids),
            K_C: c_all,
            K_F: sum(1 for r in rows if suffix_of(r["level_id"]) == "#f#"),
            "C_main 关(去重 code, 仅 main_*)": c_main,
        },
        "per_prefix": per_prefix,
        "unparsed_chapter_codes": unparsed,
        "per_chapter": [
            {"chapter": ch, K_R: by_ch_r[ch], K_M: by_ch_m[ch],
             K_C: len(codes_by_ch[ch]), K_F: by_ch_f[ch],
             "C_main 关(去重 code, 仅 main_*)": len(codes_m_by_ch[ch])}
            for ch in ch_order
        ],
        "difficulty_axis": {
            "diff_group": dict(diff_group),
            "difficulty": dict(difficulty),
            "hard_level_id_nonempty": has_hard,
            "level_id_suffix": dict(suffix_cnt),
        },
        "codes_per_difficulty": {str(k): v for k, v in sorted(mult.items())},
        "data": {
            "db_level_ids": len(db_ids),
            "in_index_authoritative": len(in_index),
            "not_in_index": not_in_index,
            "index_but_not_in_db": index_has_no_db[:50],
            "index_but_not_in_db_n": len(index_has_no_db),
            "index_total": len(idx),
            "cached_local_nonauthoritative_n": len(cached_hit),
            "cached_local_nonauthoritative": cached_hit[:50],
            "cache_dir_total_files": len(cache),
        },
    }


def print_strata(s: dict) -> None:
    t = s["totals"]
    kc = "C_main 关(去重 code, 仅 main_*)"
    print("=" * 78)
    print("口径声明（★ 跨行不可比：C 与 R/M 分母不同，同一关有多档难度）")
    print("=" * 78)
    print(f"  {K_R:26} = {t[K_R]}")
    print(f"  {K_M:26} = {t[K_M]}   ← 「434」指的就是这一行（实测 {t[K_M]}）")
    print(f"  {kc:26} = {t[kc]}   ← ★ 主线标准实战的工作量分母是它")
    print(f"  {K_C:26} = {t[K_C]}   ← 含 sub_/tr_，与上一行**跨行不可比**")
    print(f"  {K_F:26} = {t[K_F]}   ← 突袭（四星）档，与普通档同一 code")
    print(f"  同一 code 的难度档数分布 = {s['codes_per_difficulty']}")
    print(f"  → 口径 M − 口径 C_main = {t[K_M] - t[kc]}（同一关多档／多难度所致）")
    print()
    print("  按 level_id 前缀分家（口径不可混）：")
    for p, v in sorted(s["per_prefix"].items()):
        print(f"      {p:6} 行={v['rows']:4}  去重 code={v['codes']:4}  突袭={v['four_star']:3}")
    if s["unparsed_chapter_codes"]:
        print(f"  ⚠ 折不出章的 code：{len(s['unparsed_chapter_codes'])} 条")
        for x in s["unparsed_chapter_codes"][:20]:
            print(f"      ? {x}")
    else:
        print("  ✓ 全部 code 都折得出章（无 `?` 桶）")

    print()
    print("=" * 78)
    print("一 · 按章分组")
    print("=" * 78)
    print(f"  {'章':6} {K_R:>18} {K_M:>18} {kc:>28} {K_F:>14}")
    for r in s["per_chapter"]:
        print(f"  {r['chapter']:6} {r[K_R]:>18} {r[K_M]:>18} {r[kc]:>28} {r[K_F]:>14}")
    print(f"  {'合计':6} {t[K_R]:>18} {t[K_M]:>18} {t[kc]:>28} {t[K_F]:>14}")

    print()
    print("=" * 78)
    print("二 · 难度维度（两条轴是正交的，不许压成一栏）")
    print("=" * 78)
    d = s["difficulty_axis"]
    print(f"  diff_group（章节内难度分级）: {d['diff_group']}")
    print( "      EASY=剧情体验(easy_*) / NORMAL=标准实战(main_*) /")
    print( "      TOUGH=磨难险地(tough_*) / ALL=通用(tr_*/st_* 等剧情与教学)")
    print(f"  difficulty（战斗难度档）    : {d['difficulty']}")
    print( "      NORMAL=普通 / FOUR_STAR=突袭 / SIX_STAR=险地作战(15~17章)")
    print(f"  hard_level_id 非空          : {d['hard_level_id_nonempty']}")
    print(f"  level_id 后缀分布           : {d['level_id_suffix']}")

    print()
    print("=" * 78)
    print("三 · 数据齐备性（权威=关卡索引，不是本地缓存）")
    print("=" * 78)
    dd = s["data"]
    print(f"  DB 里 MAIN 的 levelId            = {dd['db_level_ids']}")
    print(f"  其中在关卡索引里（＝源上拿得到） = {dd['in_index_authoritative']}")
    print(f"  其中不在索引里（＝拿不到，具名） = {len(dd['not_in_index'])}")
    if dd["not_in_index"]:
        for x in dd["not_in_index"][:40]:
            print(f"      ✗ {x}")
    print(f"  ★ 本地缓存里的（**非权威**，只说明过去取过） = "
          f"{dd['cached_local_nonauthoritative_n']}")
    if dd["cached_local_nonauthoritative"]:
        print(f"      {dd['cached_local_nonauthoritative']}")
    print(f"  （缓存目录里 level_*.json 共 {dd['cache_dir_total_files']} 份）")
    print(f"  反向：索引里有、DB 的 MAIN 里没有 = {dd['index_but_not_in_db_n']}"
          f"（活动/教学等其它 stage_type，不属本表分母）")
    print()
    print("  ★ 「本地缓存」栏不参与「拿得到/拿不到」的判定——见 PM 通告 #1 第四节。")


def gate(level_ids: list[str]) -> int:
    """对指定关卡真取数 + 跑第二道闸。**有副作用：会写 data/gamedata 缓存。**

    ★ **两个口径必须并排印，不许只印一个**：

    * **严格口径** `allow_devices=False` —— `unsupported_reasons` 的**默认值**。
      它问的是「这一关的装置运行期在 Go 里有没有实现」。
    * **生产口径** `allow_devices=True` —— `simgo/verifier.py:93` 里硬写的那一个，
      也就是 `verify` / `golden_go` 真跑时用的。它问的是「把装置**运行期**关掉之后
      还跑不跑得动」。

    两个口径的差 = **这一关有几个装置**。生产口径打开是要**带证据**的
    （`spec.py:112-123`：只在实测过「关掉 `_device_tick`/`_pile_tick` 判决不变」时才许开），
    而 `verifier.py:93` 是**对所有关卡一刀切开**的 ⇒ 主线关里带装置的，
    它的 Go 读数是在「装置运行期被关掉」的前提下取的。**这是要单独登记的缺口。**
    """
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.simgo.spec import unsupported_reasons

    print("=" * 78)
    print("第二道闸（关卡侧）：SpecInputs.from_stage + unsupported_reasons")
    print("  ⚠ 口径：只证明「技能结构被认识」，不证明效果值正确")
    print("  ⚠ 这一路**零人排程**（deployments=[]）⇒ 闸门里只有关卡侧的理由；")
    print("     干员侧的理由要有一份作业才判得了")
    print("  ⚠ 取数有副作用：会往 data/gamedata/ 写缓存")
    print("=" * 78)
    import os
    print(f"  引擎 RIOS_SIM_BIN = {os.environ.get('RIOS_SIM_BIN', '<未设>')}")
    print(f"  {'关卡':22} {'严格(装置关)':14} {'生产(装置开)':14} {'code':8} {'出怪':>5}")
    bad = 0
    for lid in level_ids:
        try:
            st = load_stage(lid)
        except Exception as exc:                                 # noqa: BLE001
            print(f"  {lid:22} ❌ 取数失败：{type(exc).__name__}: {exc}")
            bad += 1
            continue
        try:
            #: ⚠ **不要传 `deployments=[]`**：`from_stage` 自己会填这五个列表
            #: （`_schedule_lists(None)` 给的就是空表），再传一次是
            #: `got multiple values for keyword argument`——实测踩过一次。
            strict = unsupported_reasons(SpecInputs.from_stage(st))
            prod = unsupported_reasons(SpecInputs.from_stage(st), allow_devices=True)
        except Exception as exc:                                 # noqa: BLE001
            print(f"  {lid:22} ❌ 闸门跑不起来：{type(exc).__name__}: {exc}")
            bad += 1
            continue
        a = "可跑" if not strict else f"拒跑({len(strict)})"
        b = "可跑" if not prod else f"拒跑({len(prod)})"
        print(f"  {lid:22} {a:14} {b:14} {st.code:8} {st.total_enemies():>5}")
        for w in strict:
            print(f"        严格 · {w}")
        if set(strict) != set(prod):
            for w in sorted(set(strict) - set(prod)):
                print(f"        ★仅严格口径挡下 · {w}")
    return 0 if bad == 0 else 1


def gate_selftest() -> int:
    """**反向守卫**：证明这道闸门红得起来，而不是一台只会说「可跑」的机器。

    敏感性那一步用一份**合成**输入（往 `snow_fields` 塞一项）——`unsupported_reasons`
    读它就会报「积雪 ×N」；控制组是不动它、要求理由为空。
    没有这一步，「全部 433 关都可跑」这句话与「闸门根本没接上」在输出上长得一样。
    """
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.simgo.spec import unsupported_reasons

    print("=" * 78)
    print("第二道闸 · 反向守卫（合成输入 → 必须变红；不动它 → 必须为空）")
    print("=" * 78)
    st = load_stage("main_00-01")
    base = SpecInputs.from_stage(st)
    ctrl = unsupported_reasons(base)
    ok_ctrl = (ctrl == [])
    print(f"  控制组（原样）              → {len(ctrl)} 条 {ctrl}")
    probe = SpecInputs.from_stage(st)
    probe.snow_fields = [object()]                  #: 合成注入：非空即触发那一条
    sens = unsupported_reasons(probe)
    ok_sens = any("积雪" in r for r in sens)
    print(f"  敏感性（雪场注入 1 项）      → {len(sens)} 条 {sens}")
    print()
    if ok_ctrl and ok_sens:
        print("  ✓ 闸门红得起来、也绿得下来")
        return 0
    print(f"  ❌ 守卫不过：控制组空={ok_ctrl} 敏感性红={ok_sens}")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description="主线关卡分层表")
    ap.add_argument("--json", default="", help="把分层表写成 JSON")
    ap.add_argument("--gate", nargs="*", default=None,
                    help="对指定关卡跑第二道闸（会联网取数）")
    ap.add_argument("--gate-selftest", action="store_true",
                    help="第二道闸的反向守卫：合成输入必须变红、控制组必须为空")
    args = ap.parse_args()

    if args.gate_selftest:
        return gate_selftest()
    if not DB.exists():
        print(f"❌ 库不存在：{DB}")
        return 2
    s = strata()
    print_strata(s)
    if args.json:
        outp = Path(args.json)
        outp.parent.mkdir(parents=True, exist_ok=True)
        outp.write_text(json.dumps(s, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n写出 {outp}")
    if args.gate is not None:
        print()
        return gate(args.gate)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
