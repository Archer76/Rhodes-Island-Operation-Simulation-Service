#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""主线关卡**装置表**：哪些关带装置、各带几个、是哪几个。

## 为什么需要它

`ak_tactic/simgo/verifier.py:93` **对所有关卡一刀切**硬开
`build_spec(..., allow_devices=True)`，而 `simgo/spec.py:112-123` 写明这个口子
**本来要带证据开**（只在实测过「关掉 `_device_tick` / `_pile_tick` 判决不变」时才许开）。

⇒ **凡是带装置的主线关，它的 Go 读数都是在「装置运行期被关掉」的前提下取的。**
先有这张表，才知道**哪些数要作废**。

## 装置的唯一来源

`predefines.tokenInsts`（`ak_tactic/frontend/devices.py:205` 写明「是唯一来源」）。
它在**每关的 level JSON** 里，不在 `excel/` 那一层——这一点是**穷举**核过的：

* `_level_index.json` 4694 条，字段全集只有 4 个（`difficulty`/`zone_id`/`data_path`/`code`）；
* `excel/stage_table.json` 3549 条，字段全集 62 个，`tokenInsts` / `predefines` /
  `hardPredefines` / `mapData` / `waves` 命中 **0 / 3549**。

⇒ **没有便宜路**，必须按 `data_path` 逐份取 level JSON。但：

## ★ 零落盘

`GameDataSource.fetch_json(rel, use_cache=False)` 既不读盘也不写盘
（`gamedata/source.py:134-147`：`cache_on` 为假即跳过 `local.exists()` 与 `_write_cache`）。
本工具**默认就走这一路**，所以跑完 `data/gamedata/` 一份都不会涨。
要落盘得显式加 `--write-cache`，且它会大声说明自己写了什么。

## 口径（两栏分开，不许压成一栏）

* **433 行** = `stage_type='MAIN'` 且 `level_id` 前缀 `main_` 的行数。
* **267 份** = 这 433 行**去重后的 `data_path`**（166 个文件被 2 行共用＝普通＋突袭）。
  一次取数同时覆盖普通档与突袭档（`gamedata/stage.py:625-627` 写明两档读同一个文件）。

## 三态

* `predefines.tokenInsts` —— 装置本体。
* `hardPredefines.tokenInsts` —— 突袭档那一节。**抽到的 3 关里都是 0 条**
  （`main_15-01` 有该节但空）⇒ **突袭档是否有专属装置，本工具判不了**，
  表里写 `未核(hardPredefines 空)`，**不写 0**。

用法:
    python tools\\mainline_devices.py                  # 全量 267 份，零落盘
    python tools\\mainline_devices.py --limit 5        # 试跑
    python tools\\mainline_devices.py --json out\\mainline-devices.json
    python tools\\mainline_devices.py --check-cache    # 内置控制组：与本地缓存逐份对账
"""
from __future__ import annotations

import argparse
import collections
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

#: ⚠ ★ **本机 python 的 `sys.stdout.encoding` 默认就是 `gbk`**（实测，不是推断；
#: `PYTHONIOENCODING` 未设时），而本工具要印 `✓` / `❌` / `⇒`。
#: 不管的话，**最后那行总结会抛 `UnicodeEncodeError`、rc 变 1** ——
#: 而 rc=1 会被读成「有违规」，**崩溃伪装成了结论**（判据级陷阱，同族 `ab0483bd`）。
#:
#: 处置**只放宽错误处理器、不改编码**：改编码会让 GBK 终端整片变乱码。
#: 配套第二条在下面几处：**判定词用 ASCII 打头**，别把结论只放在字形里。
try:
    sys.stdout.reconfigure(errors="backslashreplace")
except Exception:                                            # noqa: BLE001
    pass

DB = ROOT / "data" / "akdb.sqlite"
CACHE = ROOT / "data" / "gamedata"
STAGE_TABLE = CACHE / "raw.githubusercontent.com" / "excel" / "stage_table.json"

#: 章节：`^([A-Za-z]*)[-_]?(\d+)`，与 `tools/mainline_strata.py` 同一把尺子。
CHAPTER = re.compile(r"^([A-Za-z]*)[-_]?(\d+)")


def chapter_of(code: str) -> str:
    m = CHAPTER.match(code or "")
    if not m:
        return "?"
    pre, num = m.group(1), int(m.group(2))
    if pre:
        return f"{pre.upper()}{num}"
    return str(num)


def device_keys(raw: dict, section: str) -> list[dict] | None:
    """取某一节的装置；**该节整节缺省时返回 None（＝未核），不是 []**。"""
    sec = raw.get(section)
    if sec is None:
        return None
    return list((sec.get("tokenInsts") or []))


def summarize(insts: list[dict]) -> list[str]:
    out = []
    for i in insts:
        ck = ((i.get("inst") or {}).get("characterKey")) or "?"
        pos = i.get("position") or {}
        tail = f"@{pos.get('row')},{pos.get('col')}"
        if i.get("hidden"):
            tail += "/hidden"
        out.append(ck + tail)
    return out


def rows_from_db() -> list[tuple[str, str, str, str]]:
    """(level_id, code, difficulty, data_path) —— 只取 main_ 前缀的 MAIN 行。"""
    c = sqlite3.connect(DB)
    cur = c.cursor()
    cur.execute("select level_id, code, difficulty, data_path from stage "
                "where stage_type='MAIN' and level_id like 'main\\_%' escape '\\' "
                "order by level_id")
    return cur.fetchall()


def excel_has_no_devices() -> tuple[bool, int, int]:
    """**穷举守卫**：`excel/stage_table.json` 里必须一条装置字段都没有。

    这条要是红了，说明「便宜路走不通」这个前提本身塌了 —— 那时应当回头
    重估，而不是继续取 267 份。
    """
    if not STAGE_TABLE.exists():
        return False, 0, 0
    st = json.loads(STAGE_TABLE.read_text(encoding="utf-8"))["stages"]
    hits = sum(1 for s in st.values()
               if any(k in s for k in ("tokenInsts", "predefines", "hardPredefines")))
    return hits == 0, len(st), hits


def main() -> int:
    ap = argparse.ArgumentParser(description="主线关卡装置表")
    ap.add_argument("--json", default="", help="把结果写成 JSON")
    ap.add_argument("--limit", type=int, default=0, help="只做前 N 份（试跑）")
    ap.add_argument("--write-cache", action="store_true",
                    help="允许写 data/gamedata 缓存（默认禁止，见模块 docstring）")
    ap.add_argument("--check-cache", action="store_true",
                    help="对本地已有缓存的关，逐份与远程值对账（控制组）")
    args = ap.parse_args()

    print("=" * 78)
    print("主线关卡装置表")
    print("=" * 78)

    ok, n_st, n_hit = excel_has_no_devices()
    print(f"  [GUARD] 穷举守卫 · excel/stage_table.json：{n_st} 条，含装置字段的 {n_hit} 条 "
          f"→ {'[OK] 便宜路确实不通' if ok else '[FAIL] 守卫红了，先别取数'}")
    if not ok:
        print("  [FAIL] stage_table 里出现了装置字段 ⇒ "
              "「必须逐份取 level JSON」这个前提不成立。")
        return 2

    rows = rows_from_db()
    paths = sorted({r[3] for r in rows})
    print(f"  口径：main_ 行 = {len(rows)}  去重 data_path = {len(paths)}"
          f"（一次取数覆盖普通＋突袭两档）")
    if args.limit:
        paths = paths[: args.limit]
        print(f"  ⚠ --limit {args.limit}：只做前 {len(paths)} 份")

    from ak_tactic.gamedata.source import GameDataSource
    src = GameDataSource()
    #: ★ 零落盘：use_cache=False 让 source.py 既不读盘也不写盘。
    use_cache = bool(args.write_cache)
    if use_cache:
        print("  ⚠ --write-cache 已开：这次会往 data/gamedata/ 写文件")

    per_path: dict[str, dict] = {}
    errors: list[tuple[str, str]] = []
    mism: list[tuple[str, int, int]] = []
    n_cmp = 0                       #: ★ 控制组**真对账了几份**——不比就报绿是空洞的绿
    t_normal = t_hard = 0
    for i, dp in enumerate(paths, 1):
        rel = f"levels/{dp}"
        try:
            raw = src.fetch_json(rel, use_cache=use_cache)
        except Exception as exc:                                 # noqa: BLE001
            errors.append((dp, f"{type(exc).__name__}: {exc}"))
            print(f"  [{i:3}/{len(paths)}] ❌ {dp}  {type(exc).__name__}: {exc}")
            continue
        n_insts = device_keys(raw, "predefines")
        h_insts = device_keys(raw, "hardPredefines")
        n = len(n_insts or [])
        h = len(h_insts) if h_insts is not None else None
        t_normal += n
        t_hard += h or 0
        per_path[dp] = {
            "normal_n": n, "normal_keys": summarize(n_insts or []),
            "hard_n": h, "hard_keys": summarize(h_insts or []),
            "hard_section": ("缺节" if h_insts is None else
                             ("空" if not h_insts else "有")),
        }
        if args.check_cache:
            #: 控制组：本地缓存里若已有这一份，两边必须逐数一致。
            local = CACHE / "map.ark-nights.com" / "levels" / dp
            if local.exists():
                n_cmp += 1
                c = json.loads(local.read_text(encoding="utf-8"))
                cn = len(device_keys(c, "predefines") or [])
                if cn != n:
                    mism.append((dp, n, cn))
                    print(f"  ⚠ {dp} 远程 {n} ≠ 缓存 {cn}")
        if i % 25 == 0 or n:
            print(f"  [{i:3}/{len(paths)}] {dp:42} 装置={n}"
                  + (f"  hard={h}" if h else ""))

    if errors:
        print()
        print(f"  [FAIL] {len(errors)} 份取数失败（**不许当成 0**）：")
        for dp, why in errors[:10]:
            print(f"      {dp}  {why}")

    #: 按行展开（433 行，普通/突袭各一行）
    per_row = []
    for lid, code, diff, dp in rows:
        v = per_path.get(dp)
        per_row.append({
            "level_id": lid, "code": code, "difficulty": diff, "data_path": dp,
            "chapter": chapter_of(code),
            "devices": (None if v is None else v["normal_n"]),
            "keys": ([] if v is None else v["normal_keys"]),
        })

    have = [r for r in per_row if r["devices"] is not None]
    withd = [r for r in have if r["devices"] > 0]
    print()
    print("=" * 78)
    print("结果")
    print("=" * 78)
    print(f"  取到 {len(per_path)}/{len(paths)} 份文件，覆盖 {len(have)}/{len(rows)} 行")
    print(f"  ★ 带装置的关（行） = {len(withd)} / {len(have)}"
          f"  = {100.0*len(withd)/max(1,len(have)):.1f}%")
    print(f"  装置条目合计（普通档）= {t_normal}；hardPredefines 合计 = {t_hard}")

    dist = collections.Counter()
    for v in per_path.values():
        if v["normal_n"]:
            dist[v["normal_n"]] += 1
    print(f"  每份文件的装置数分布（文件数）：{dict(sorted(dist.items()))}")

    keyd = collections.Counter()
    for v in per_path.values():
        for k in v["normal_keys"]:
            keyd[k.split("@")[0]] += 1
    print(f"  装置 characterKey 分布（前 12）：{keyd.most_common(12)}")

    hstate = collections.Counter(v["hard_section"] for v in per_path.values())
    print(f"  hardPredefines 三态：{dict(hstate)}"
          f"  ← 「缺节/空」**是未核，不是 0**")

    print()
    print("  按章（口径：main_ 行数 / 其中带装置的 / 装置条目合计）")
    bych: dict[str, list[int]] = collections.defaultdict(lambda: [0, 0, 0])
    for r in have:
        b = bych[r["chapter"]]
        b[0] += 1
        if r["devices"]:
            b[1] += 1
            b[2] += r["devices"]

    def sortkey(ch: str):
        return (0, int(ch)) if ch.isdigit() else (1, ch)

    for ch in sorted(bych, key=sortkey):
        a, b, c = bych[ch]
        if b:
            print(f"    {ch:6} 行={a:4}  带装置={b:3}  装置条目={c:4}")

    if args.check_cache:
        print()
        if n_cmp == 0:
            print("  [FAIL] 控制组**一份都没比到**（本地缓存里没有这些 data_path）"
                  "——这不叫通过，叫没行使。")
            mism.append(("__none_compared__", 0, 0))
        else:
            print(f"  [{'OK' if not mism else 'FAIL'}] 控制组（--check-cache）："
                  f"实比 {n_cmp} 份，失配 {len(mism)} 处")

    if args.json:
        out = {"n_rows": len(rows), "n_paths": len(paths),
               "n_fetched": len(per_path), "n_with_devices": len(withd),
               "n_errors": len(errors),
               "errors": [{"data_path": d, "why": w} for d, w in errors],
               "hard_predefines_states": dict(hstate),
               "key_dist": dict(keyd),
               "per_path": per_path, "per_row": per_row}
        p = ROOT / args.json if not Path(args.json).is_absolute() else Path(args.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\n写出 {p}")

    #: ★ 不许「安静的绿」：取数失败一律 rc≠0。
    return 1 if errors else 0


if __name__ == "__main__":
    #: ⚠ 给「崩了」留一个**与业务态不重叠**的退出码：0=跑完、1=有取数失败、2=守卫红、
    #: **5=本工具自己崩了**。不这样分，崩溃会伪装成「有违规」（上面 GBK 那条就是）。
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:                              # noqa: BLE001
        print(f"\n[CRASH] {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(5)
