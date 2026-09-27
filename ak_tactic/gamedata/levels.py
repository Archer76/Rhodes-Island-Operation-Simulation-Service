# -*- coding: utf-8 -*-
"""把**库里真正用到的**逐关 JSON 一次性取齐（关卡缓存补齐）。

## 为什么需要它

引擎（`rios-sim`）的 `load` **只读盘、不下载**：它按关卡索引给的 `data_path` 去读

    <数据根>/gamedata/<镜像域名>/levels/<data_path>

而 gamedata 缓存是**按需增长**的 —— 谁问过哪一关，哪一关才在盘上。于是发布形态下
没被问过的关一律取不到，界面上的表现是

    取部署人数上限失败（main_09-12）：★ 桥报错：读关卡文件失败 (…\\levels\\obt\\main\\
    level_main_09-12.json)：… The system cannot find the path specified.

2026-09-27 实测：索引 4715 条里，开发树命中 603（12.8%）、发布树 0（0.0%）；
而**库里真正有的关卡**（`stage` 表的 distinct `level_id`）去重后是 1541 个
`data_path`，本机当时只有 324 个。

## 三条设计

1. **范围按库定，不按索引定**：索引那 4715 条里有一大半是肉鸽/爬塔/小玩法
   （本项目不取），按索引取会白下几倍。范围取 `stage` 表 —— 那才是界面能选到的关。
2. **可续跑**：盘上已有的直接跳过（判据是文件存在，不是缓存的 TTL）。
   中断了再跑一次就接着下，不会重下已经有的。
3. **失败具名**：404／超时逐条记下来在末尾打印 —— 「镜像里没有」和「网络抖了一下」
   是两件事，不许并成一句"有失败"。有失败 ⇒ 返回值里如实带着，调用方据此定 rc。

并发默认 4 线程：每个文件写自己的路径（`_write_cache` 是 tmp + `replace`，原子），
统计计数在 `GameDataSource._lock` 里，所以并行是安全的。内存也不涨 ——
走的是 `download_to_cache`（只落盘，不进 `_mem`）。

★ **必须带重试，而且这条是实测逼出来的**（2026-09-27）：第一次用 8 线程跑全量，
1213 个里 1184 个报 `SSL: UNEXPECTED_EOF_WHILE_READING` —— 而 5.1 秒就跑完了
1213 次尝试（每次约 4 ms），那个形状**不是"文件不存在"，是连接被瞬时掐掉**。
判别实验：同一个文件刚才失败、隔一轮串行重取就成功（0.68 s、61 KB），
并发 4 再取也是成功。⇒ 处置：**瞬时错误退避重试**（默认 3 次，0.3/0.6/1.2 s 起步
＋抖动），**404 不重试**（那种是镜像里真没有，重试只是白等），并发降到 4。
"""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from .source import GameDataSource, GamedataError

#: 库（范围来源）。与 `ak_tactic/db/build.py` 的 `DEFAULT_DB_PATH` 同一个算法，
#: 这里不 import 它是为了不让 `gamedata/` 依赖 `db/`（两边都会用到 gamedata）。
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "akdb.sqlite"


def level_ids_from_db(db_path: Path | str | None = None) -> list[str]:
    """库里出现的全部 `level_id`（去重、**有序** —— 计划要可复现）。

    只读开库（`mode=ro`）：这个模块永远不写库。
    """
    p = Path(db_path) if db_path else DEFAULT_DB_PATH
    if not p.is_file():
        raise SystemExit("库不在：%s（先跑 `python -m ak_tactic db build`）" % p)
    con = sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True)
    try:
        return sorted({r[0] for r in con.execute("select level_id from stage")})
    finally:
        con.close()


@dataclass
class LevelFetchPlan:
    """取齐计划：哪些已经在盘上、哪些缺、哪些**索引里查不到**。"""

    present: list[str] = field(default_factory=list)     # data_path
    missing: list[str] = field(default_factory=list)     # data_path
    unknown: list[str] = field(default_factory=list)     # level_id（索引里没有）

    @property
    def total(self) -> int:
        return len(self.present) + len(self.missing)


def plan_levels(src: GameDataSource, level_ids: list[str],
                index: dict) -> LevelFetchPlan:
    """算出「该下哪些」。**同一个 `data_path` 只算一次**（普通档与突袭档共用文件）。

    `unknown` 单列：索引里查不到 `data_path` 的 `level_id` —— 那是**另一类问题**
    （库与索引不同版本），不该混进"缺文件"里当成下载失败。
    """
    plan = LevelFetchPlan()
    seen: set[str] = set()
    for lid in level_ids:
        dp = ((index.get(lid) or {}).get("data_path") or "").strip()
        if not dp:
            plan.unknown.append(lid)
            continue
        if dp in seen:
            continue
        seen.add(dp)
        rel = "levels/" + dp
        (plan.present if src.local_path(rel).is_file() else plan.missing).append(dp)
    return plan


@dataclass
class FetchReport:
    asked: int = 0
    fetched: int = 0
    bytes: int = 0
    failed: list[tuple[str, str]] = field(default_factory=list)
    unknown: list[str] = field(default_factory=list)
    retries: int = 0
    seconds: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.failed


def _is_missing(err: BaseException) -> bool:
    """这个错是「镜像里真没有」（404）还是「这次没连上」。

    判别式是取数层给的措辞（`source._download` 对 404 单独包了一句）——
    镜像里没有 ⇒ **不该重试**，重试只是让它多等三倍时间还是失败。
    """
    return "镜像里没有这个文件" in str(err)


def fetch_one(src: GameDataSource, data_path: str, *,
              retries: int = 3, counter: list | None = None):
    """取一个关卡文件：**瞬时错误退避重试**，404 立刻放弃。

    `counter` 是给调用方累加"重试了几次"用的（一个单元素列表，调用方自己加锁）。
    """
    last: BaseException | None = None
    for attempt in range(retries + 1):
        try:
            return src.download_to_cache("levels/" + data_path)
        except (GamedataError, OSError) as e:
            last = e
            if _is_missing(e) or attempt == retries:
                break
            if counter is not None:
                counter[0] += 1
            #: 0.3 / 0.6 / 1.2 s 起步 ＋ 抖动：多个线程同时被掐时别一起重来
            time.sleep(min(4.0, 0.3 * (2 ** attempt)) * (0.5 + random.random()))
    raise last if last is not None else GamedataError("取数失败：%s" % data_path)


def fetch_levels(*, db_path: Path | str | None = None,
                 workers: int = 4, limit: int | None = None,
                 retries: int = 3, log=print) -> FetchReport:
    """按库的范围把缺的关卡文件取下来。返回报告（**不打印结论、不 sys.exit**）。"""
    t0 = time.time()
    src = GameDataSource()
    ids = level_ids_from_db(db_path)
    index = src.level_index()
    plan = plan_levels(src, ids, index)
    objs = plan.missing if limit is None else plan.missing[:limit]

    log("范围：库里 %d 个 level_id → 去重后 %d 个 data_path"
        % (len(ids), plan.total))
    log("  已在盘上 %d 个；缺 %d 个%s"
        % (len(plan.present), len(plan.missing),
           "（本次只取前 %d 个）" % len(objs) if limit is not None
           and len(objs) < len(plan.missing) else ""))
    if plan.unknown:
        log("  ⚠ 索引里查不到的 level_id %d 个（**不是**下载失败）：%s"
            % (len(plan.unknown), ", ".join(plan.unknown[:5])))
    log("  缓存目录：%s" % src.cache_dir)

    rep = FetchReport(asked=len(objs), unknown=list(plan.unknown))
    if not objs:
        rep.seconds = time.time() - t0
        log("  没有要下的（已经齐了）")
        return rep

    done = 0
    lock = threading.Lock()
    retry_ctr = [0]

    def one(dp: str) -> None:
        nonlocal done
        try:
            n, fetched = fetch_one(src, dp, retries=retries, counter=retry_ctr)
        except (GamedataError, OSError) as e:
            with lock:
                rep.failed.append((dp, str(e).replace("\n", " ")))
                done += 1
            return
        with lock:
            if fetched:
                rep.fetched += 1
                rep.bytes += n
            done += 1
            if done % 25 == 0 or done == len(objs):
                log("  [%d/%d] 已下 %d 个、%.1f MB、失败 %d、重试 %d"
                    % (done, len(objs), rep.fetched, rep.bytes / 1048576.0,
                       len(rep.failed), retry_ctr[0]))

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        list(pool.map(one, objs))

    rep.retries = retry_ctr[0]
    rep.seconds = time.time() - t0
    return rep


# ------------------------------------------------------------------ 自检

def selftest(log=print) -> int:
    """**离线**自检：拿一个 `file://` 假镜像走完整条路（不下一个真文件）。

    判据（每条都配负对照，见 `_selftest_body` 的注释）：
      ① 计划把「已在盘上 / 缺 / 索引里查不到」分成三堆，且**按 `data_path` 去重**；
      ② 取完 ⇒ 缺的那批都落到盘上，字节数如实累加；
      ③ **续跑幂等**：再跑一次 ⇒ 一个都不下（否则每次启动都重下 57 MB）；
      ④ 镜像里没有的文件 ⇒ **具名失败**（不是静默算成"下过了"）；
      ⑤ 负对照：把那个文件补进假镜像 ⇒ 同一条路立刻变绿（证明 ④ 的红是"文件真缺"，
         不是尺子恒红）。
    """
    bad = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal bad
        if cond:
            log("  ✓ %s  %s" % (label, detail))
        else:
            bad += 1
            log("  ✗ %s  %s" % (label, detail))

    log("== 关卡取齐 · 自检（离线，用 file:// 假镜像）==")
    with tempfile.TemporaryDirectory(prefix="rios-levels-") as td:
        tmp = Path(td)
        mirror = tmp / "mirror"
        cache = tmp / "cache"
        #: 假镜像里只放 a、b 两个；c 预先塞进缓存（装作"以前问过"）
        for name in ("a", "b"):
            p = mirror / "levels" / "obt" / "main" / ("level_%s.json" % name)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"options": {"characterLimit": 6}}),
                         encoding="utf-8")
        src = GameDataSource(base=mirror.as_uri(), cache_dir=cache)
        pc = src.local_path("levels/obt/main/level_c.json")
        pc.parent.mkdir(parents=True, exist_ok=True)
        pc.write_text('{"options": {"characterLimit": 8}}', encoding="utf-8")

        index = {
            "a": {"data_path": "obt/main/level_a.json"},
            "b": {"data_path": "obt/main/level_b.json"},
            "c": {"data_path": "obt/main/level_c.json"},
            "c#f#": {"data_path": "obt/main/level_c.json"},   #: 同一个文件的两个档
            "e": {"data_path": "obt/main/level_e.json"},       #: 镜像里没有 ⇒ 该失败
            "zzz": {},                                          #: 索引里没有 data_path
        }
        ids = ["a", "b", "c", "c#f#", "e", "zzz"]
        plan = plan_levels(src, ids, index)
        check("计划：已在盘上 1 个（c；c#f# 与它同文件，只算一次）",
              plan.present == ["obt/main/level_c.json"], repr(plan.present))
        check("计划：缺 3 个 —— a、b，以及镜像里也没有的 e"
              "（计划只看**盘上**有没有；镜像里有没有要取了才知道）",
              sorted(plan.missing) == ["obt/main/level_a.json",
                                       "obt/main/level_b.json",
                                       "obt/main/level_e.json"],
              repr(plan.missing))
        check("计划：索引里查不到的单独一堆（zzz）", plan.unknown == ["zzz"],
              repr(plan.unknown))

        #: ④ 镜像里没有 e ⇒ 具名失败。这里直接调取数（`fetch_levels` 要库，自检不碰库）
        try:
            src.download_to_cache("levels/obt/main/level_e.json")
            check("④ 镜像里没有的文件 ⇒ 报错（不是静默成功）", False, "居然没报错")
        except GamedataError as exc:
            check("④ 镜像里没有的文件 ⇒ 具名失败", "level_e.json" in str(exc),
                  str(exc)[:60].replace("\n", " "))
        check("④ 顺带：失败的那一步**没在盘上留下任何东西**（不留 .part）",
              not list((cache).rglob("*.part")), "")

        #: ② 把缺的两个取下来
        got = []
        for dp in list(plan.missing) + ["obt/main/level_e.json"]:
            try:
                n, fetched = src.download_to_cache("levels/" + dp)
                got.append((dp, n, fetched))
            except GamedataError:
                got.append((dp, 0, False))
        plan2 = plan_levels(src, ids, index)
        check("② 取完 ⇒ 缺的只剩镜像里真没有的那个（e）",
              plan2.missing == ["obt/main/level_e.json"], repr(plan2.missing))
        check("② 真下载的字节数如实累加（两个文件 > 0）",
              sum(n for _d, n, f in got if f) > 0,
              "%d 字节" % sum(n for _d, n, f in got if f))

        #: ③ 续跑幂等
        again = [src.download_to_cache("levels/" + dp)[1]
                 for dp in ("obt/main/level_a.json", "obt/main/level_b.json",
                            "obt/main/level_c.json")]
        check("③ 续跑幂等：再取一次，三个**一个都没重下**",
              again == [False, False, False], repr(again))

        #: ⑤ 负对照：把 e 补进假镜像 ⇒ 同一条路变绿
        pe = mirror / "levels" / "obt" / "main" / "level_e.json"
        pe.write_text('{"options": {"characterLimit": 4}}', encoding="utf-8")
        _n, fetched = src.download_to_cache("levels/obt/main/level_e.json")
        plan3 = plan_levels(src, ids, index)
        check("⑤ 负对照：补上那个文件后，同一条路立刻变绿（缺 0、真下了）",
              fetched and plan3.missing == [], "缺 %d 个" % len(plan3.missing))

        #: ⑥ 重试：**瞬时错误**要退避重试到成功；**404 一次都不重试**
        #: （这一条是 2026-09-27 那次 1184/1213 假失败逼出来的：镜像会掐 TLS 连接，
        #:  没有重试就会把"抖动"记成"下不到"。负对照见 ⑦。）
        class Flaky:
            def __init__(self, fail_first: int, msg: str) -> None:
                self.left = fail_first
                self.msg = msg
                self.calls = 0

            def download_to_cache(self, rel_path: str):
                self.calls += 1
                if self.left > 0:
                    self.left -= 1
                    raise GamedataError(self.msg)
                return 123, True

        ctr = [0]
        fl = Flaky(2, "下载失败：https://x/y\n  <urlopen error [SSL: EOF]>")
        n, fetched = fetch_one(fl, "obt/main/level_a.json", retries=3, counter=ctr)
        check("⑥ 瞬时错误 ⇒ 退避重试到成功（试了 3 次、记了 2 次重试）",
              (n, fetched, fl.calls, ctr[0]) == (123, True, 3, 2),
              "返回 %s，调用 %d 次，记重试 %d 次" % ((n, fetched), fl.calls, ctr[0]))

        absent = Flaky(99, "镜像里没有这个文件：https://x/y")
        try:
            fetch_one(absent, "obt/main/level_z.json", retries=3, counter=[0])
            check("⑥ 404 ⇒ 立刻放弃", False, "居然没抛错")
        except GamedataError:
            check("⑥ 404 ⇒ **一次都不重试**（重试只是让它白等三倍时间）",
                  absent.calls == 1, "调用 %d 次" % absent.calls)

        #: ⑦ 负对照：一直瞬时失败 ⇒ 尝试次数必须**有界**（= retries+1），
        #:    不许变成死循环 —— 那会让"一键取数据"永远卡住。
        forever = Flaky(99, "下载失败：<urlopen error [SSL: EOF]>")
        try:
            fetch_one(forever, "obt/main/level_y.json", retries=2, counter=[0])
            check("⑦ 负对照：一直失败 ⇒ 有界放弃", False, "居然成功了")
        except GamedataError:
            check("⑦ 负对照：一直失败 ⇒ 尝试次数有界（retries+1=3），不会卡死",
                  forever.calls == 3, "调用 %d 次" % forever.calls)

    log("== 结论：%s（红 %d 条）==" % ("全绿" if bad == 0 else "有红", bad))
    return 0 if bad == 0 else 1


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m ak_tactic.gamedata.levels",
        description="把库里用到的逐关 JSON 一次性取齐；--selftest 走离线假镜像")
    ap.add_argument("--selftest", action="store_true", help="离线自检（不联网）")
    ap.add_argument("--db", help="库路径（默认 data/akdb.sqlite）")
    ap.add_argument("--workers", type=int, default=4,
                    help="并发线程数（默认 4；更高会更容易被镜像掐连接）")
    ap.add_argument("--limit", type=int, help="只取前 N 个（试跑用）")
    ap.add_argument("--retries", type=int, default=3, help="瞬时错误的重试次数（默认 3）")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    rep = fetch_levels(db_path=a.db, workers=a.workers, limit=a.limit,
                       retries=a.retries)
    print("取齐：真下 %d 个、%.1f MB、失败 %d 个、重试 %d 次、用时 %.1fs"
          % (rep.fetched, rep.bytes / 1048576.0, len(rep.failed), rep.retries,
             rep.seconds))
    for dp, err in rep.failed[:20]:
        print("  ✗ %s\n      %s" % (dp, err))
    return 0 if rep.ok else 1


if __name__ == "__main__":
    sys.exit(_main())
