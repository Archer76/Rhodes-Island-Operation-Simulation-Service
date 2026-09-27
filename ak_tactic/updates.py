# -*- coding: utf-8 -*-
"""检查「上游数据有没有更新」与「我们的数据包有没有新版」。

## 判据（两边各一条，都是一次很小的请求）

* **游戏数据**：上游 `excel/data_version.txt`（一个几百字节的文本）对比我们
  `akdb.sqlite` 的 `meta.data_version` —— 后者是**建库那一刻**存下的同一份内容
  （现读实测：`Stream://torappu-data/v077/rel77.0 / Change:123576 on 2026/09/17 /
  VersionControl:77.4.0`）。
* **数据包**：`api.github.com/repos/<owner>/rios-data/releases/latest` 的 `tag_name`
  对比 `data/datapack.json` 里记的 `pack`。

## 三条设计

1. **判据是纯函数**（`verdict()`）：喂两个版本串就出结论，**离线可自检**。
   取数那半边（`fetcher`）可注入 —— 自检用一个假 fetcher，一个真请求都不发。
2. **取不到 ≠ 有更新**：任何一边取不到就把 `checked=False` 如实带出来，
   绝不把"网断了"说成"你有新版本"（那种误报会让人白下一遍几十 MB）。
3. **只报结论与理由**，不在这里动手更新 —— 动手的是 `rebuild_data.py` 那条既有的流程
   （只加不删、缺件具名、每项任务一条进度条）。
"""

from __future__ import annotations

import json
import os
import sqlite3
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

#: 上游版本戳（GitHub 镜像；ark-nights 没有 excel/ 目录）
VERSION_URL = ("https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/"
               "master/zh_CN/gamedata/excel/data_version.txt")
#: 我们的数据包仓（每次发新版打一个 release tag，如 data-v0.1.1）
PACK_REPO = "Archer76/rios-data"
PACK_API = "https://api.github.com/repos/%s/releases/latest" % PACK_REPO


def _default_fetcher(url: str, timeout: float = 20.0) -> str:
    req = urllib.request.Request(url, headers={
        "User-Agent": "rios-update-check",
        "Accept": "text/plain,application/json",
    })
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8-sig", errors="replace")


def local_data_version(db_path: Path | str | None = None) -> str:
    """我们库里记的上游版本戳（建库那一刻的）。取不到返回空串。"""
    p = Path(db_path) if db_path else (DATA / "akdb.sqlite")
    if not p.is_file():
        return ""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % p.as_posix(), uri=True)
        try:
            row = list(con.execute("select value from meta where key='data_version'"))
            return (row[0][0] if row else "").strip()
        finally:
            con.close()
    except sqlite3.Error:
        return ""


def local_pack_version(data_dir: Path | str | None = None) -> str:
    """数据包装入时记下的版本（`data/datapack.json` 的 `pack`）。没装过返回空串。"""
    d = Path(data_dir) if data_dir else DATA
    p = d / "datapack.json"
    if not p.is_file():
        return ""
    try:
        return str((json.loads(p.read_text(encoding="utf-8")) or {}).get("pack") or "")
    except (OSError, ValueError):
        return ""


def verdict(local: str, remote: str) -> tuple[bool, str]:
    """**纯函数**：本地版本 vs 上游版本 ⇒ 要不要更新，以及一句话理由。

    任何一边是空的都**不判更新**（取不到 ≠ 有新版；这条与"报零命中前先证明查询跑成功"
    同一族：把"没问到"说成"有新版本"会让人白下几十 MB）。
    """
    l = (local or "").strip()
    r = (remote or "").strip()
    if not r:
        return False, "上游版本戳没取到 ⇒ 不判更新（不是「有新版」）"
    if not l:
        return False, "本地没记版本（库是旧的或没建）⇒ 不判更新，让首次运行那条路去管"
    if l == r:
        return False, "与上游一致"
    return True, "上游已更新：本地 %s → 上游 %s" % (l.splitlines()[-1], r.splitlines()[-1])


def check_updates(*, data_dir: Path | str | None = None,
                  db_path: Path | str | None = None,
                  fetcher=None, packs: bool = True) -> dict:
    """检查一次。返回一个**只含结论**的字典（界面直接念给玩家听）。"""
    f = fetcher or _default_fetcher
    out: dict = {"checked": False, "note": "", "data_update": False,
                 "data_local": "", "data_remote": "",
                 "pack_local": local_pack_version(data_dir),
                 "pack_latest": "", "pack_update": False}
    out["data_local"] = local_data_version(db_path)

    try:
        out["data_remote"] = f(VERSION_URL)
    except Exception as e:                                    # noqa: BLE001
        out["note"] = "查上游版本失败：%s" % type(e).__name__
        return out
    out["checked"] = True
    need, why = verdict(out["data_local"], out["data_remote"])
    out["data_update"] = need
    out["note"] = why

    if packs:
        try:
            tag = json.loads(f(PACK_API)).get("tag_name") or ""
        except Exception:                                     # noqa: BLE001
            tag = ""
        out["pack_latest"] = tag
        if tag and out["pack_local"] and tag != out["pack_local"]:
            out["pack_update"] = True
    return out


# ------------------------------------------------------------------ 自检

def selftest(log=print) -> int:
    """**离线**自检：判据是纯函数，取数用假 fetcher（一个真请求都不发）。"""
    bad = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal bad
        if cond:
            log("  ✓ %s  %s" % (label, detail))
        else:
            bad += 1
            log("  ✗ %s  %s" % (label, detail))

    log("== 数据更新检查 · 自检（离线）==")
    same = ("Stream://torappu-data/v077/rel77.0\n"
            "Change:123576 on 2026/09/17\nVersionControl:77.4.0")
    newer = same.replace("77.4.0", "77.5.0")

    need, why = verdict(same, same)
    check("版本一致 ⇒ 不更新", not need, why)
    need, why = verdict(same, newer)
    check("上游更新 ⇒ 判更新，且理由里带两个版本号",
          need and "77.4.0" in why and "77.5.0" in why, why)
    need, why = verdict("", newer)
    check("负对照：本地没版本 ⇒ **不**判更新（交给首次运行那条路）", not need, why)
    need, why = verdict(same, "")
    check("负对照：上游没取到 ⇒ **不**判更新（取不到 ≠ 有新版）", not need, why)

    #: 端到端（假 fetcher）
    calls = []

    def fake(url, timeout=20.0):
        calls.append(url)
        if url == VERSION_URL:
            return newer
        if url == PACK_API:
            return json.dumps({"tag_name": "data-v0.1.1"})
        raise AssertionError("不该请求这个地址：%s" % url)

    import tempfile
    with tempfile.TemporaryDirectory(prefix="rios-upd-") as td:
        d = Path(td)
        (d / "datapack.json").write_text(json.dumps({"pack": "data-v0.1.0"}),
                                         encoding="utf-8")
        db = d / "akdb.sqlite"
        con = sqlite3.connect(db)
        con.execute("create table meta(key text primary key, value text)")
        con.execute("insert into meta values('data_version', ?)", (same,))
        con.commit()
        con.close()
        r = check_updates(data_dir=d, db_path=db, fetcher=fake)
        check("端到端：数据要更新 ＋ 数据包要更新",
              r["checked"] and r["data_update"] and r["pack_update"],
              "data %s→%s｜pack %s→%s"
              % (r["data_local"].splitlines()[-1], r["data_remote"].splitlines()[-1],
                 r["pack_local"], r["pack_latest"]))
        check("端到端：只问了那两条地址（没多打一个请求）",
              sorted(calls) == sorted([VERSION_URL, PACK_API]), "%d 次" % len(calls))

        #: 负对照：取数抛错 ⇒ checked=False 且**不判更新**
        def boom(url, timeout=20.0):
            raise OSError("net down")

        r2 = check_updates(data_dir=d, db_path=db, fetcher=boom)
        check("负对照：网断了 ⇒ checked=False、不判更新、note 里写明",
              (not r2["checked"]) and (not r2["data_update"]) and "失败" in r2["note"],
              r2["note"])

    log("== 结论：%s（红 %d 条）==" % ("全绿" if bad == 0 else "有红", bad))
    return 0 if bad == 0 else 1


def _main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m ak_tactic.updates",
                                 description="检查上游数据与数据包有没有更新")
    ap.add_argument("--json", action="store_true", help="输出 JSON（给界面用）")
    ap.add_argument("--selftest", action="store_true", help="离线自检")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    r = check_updates()
    if a.json:
        print(json.dumps(r, ensure_ascii=False))
        return 0
    print("上游数据：本地 %s" % (r["data_local"].splitlines()[-1] if r["data_local"] else "（未记）"))
    print("          上游 %s" % (r["data_remote"].splitlines()[-1] if r["data_remote"] else "（没取到）"))
    print("结论：%s" % r["note"])
    print("数据包：本地 %s / 最新 %s ⇒ %s"
          % (r["pack_local"] or "（没装）", r["pack_latest"] or "（没查到）",
             "有新版" if r["pack_update"] else "无更新或未核"))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(_main())
