# -*- coding: utf-8 -*-
"""数据包：把**非游戏本体**的那部分数据打成一个 zip（导出）／装回去（装入）。

## 为什么要有它

首次运行最耗时的是"取数 ＋ 建库"。其中有两块**不是游戏本体数据**、而是社区站点
（prts.wiki、theresa.wiki）的派生内容，它们的许可是 **CC BY-NC-SA 4.0**
（署名 ＋ 非商业 ＋ 相同方式共享）：

* `enemydb.sqlite`      —— 敌人图鉴/逐档数值/抗性/技能（来自 prts.wiki「分类:敌人」）
* `cache/theresa/tile_info.json` —— 地块字典 95 条（来自 theresa.wiki 的地图数据接口）

这两块**可以**由我们分发（非商业），而**游戏本体**那部分
（逐关 JSON、`enemy_database.json`、`excel/*`）**不可以** —— 它版权属鹰角、
镜像站也未授权。所以这个包只装前两块，并且每次导出都会**断言包里没有本体数据**。

## 三条设计

1. **许可随包走**：包里必带 `DATA-LICENSE.md`（署名/修改/NC/SA 四条义务）、
   `LICENSE-CC-BY-NC-SA-4.0.txt`、`SOURCES.md`（逐文件来源）、`manifest.json`
   （机器可读的快照信息）、`README.md`。**装入时先验这五份在不在** —— 缺一份就拒装，
   免得一份"来路不明"的库被灌进玩家的数据目录。
2. **不夹带本体数据**：导出与装入都按路径判据挡一道（见 `FORBIDDEN`）。这条不是
   文档里的一句话，是两次都会跑的代码。
3. **装入要留痕**：覆盖了哪个文件、原文件多大、装进来的快照是哪一刻，全部打印。
   ★ 地块那份**会把 mtime 刷成现在**：`fetch_tile_info()` 有 7 天 TTL，不刷的话
   一份旧快照会被当成过期缓存重新去抓 —— 刷 mtime 是为了"用得上"，而真实快照
   时刻从 `manifest.json` 读出来**打印给玩家看**（不是把旧的冒充成新的）。
"""

from __future__ import annotations

import argparse
import io
import json
import os
import shutil
import sys
import tempfile
import time
import urllib.request
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

#: 包内容：`(包内路径, 本机路径, 署名主体, 说明)`
PACK_ITEMS: list[tuple[str, Path, str, str]] = [
    ("enemydb.sqlite", DATA / "enemydb.sqlite", "prts.wiki",
     "敌人图鉴/逐档数值/抗性/技能（分类:敌人）"),
    ("theresa/tile_info.json", DATA / "cache" / "theresa" / "tile_info.json",
     "theresa.wiki", "地块字典（游戏本体没有这张表）"),
]

#: 包里**必须**有的许可与来源文件（缺一份就拒装）。
REQUIRED_DECL = ("README.md", "DATA-LICENSE.md",
                 "LICENSE-CC-BY-NC-SA-4.0.txt", "SOURCES.md", "manifest.json")

#: **绝不许**出现在包里的东西 —— 游戏本体数据（版权属鹰角、镜像未授权）。
FORBIDDEN_PREFIX = ("gamedata/", "excel/", "cache/prts/")
FORBIDDEN_NAME = ("enemy_database.json", "akdb.sqlite", "prts-notes.sqlite")

CC_URL = "https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.zh-hans"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _sha16(p: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


# ------------------------------------------------------------------ 判据

def offending(names: list[str]) -> list[str]:
    """包内哪些条目**不该在**（游戏本体数据）。纯函数 —— 判据直接喂它。"""
    bad = []
    for n in names:
        low = n.replace("\\", "/").lstrip("/")
        if low.startswith(FORBIDDEN_PREFIX):
            bad.append(low)
        elif os.path.basename(low) in FORBIDDEN_NAME:
            bad.append(low)
        elif os.path.basename(low).startswith("level_") and low.endswith(".json"):
            bad.append(low)
    return bad


def missing_decl(names: list[str]) -> list[str]:
    """包里缺了哪几份许可/来源文件。纯函数。"""
    have = {n.replace("\\", "/").lstrip("/") for n in names}
    return [d for d in REQUIRED_DECL if d not in have]


# ------------------------------------------------------------------ 导出

@dataclass
class ExportReport:
    zip_path: Path
    items: list[tuple[str, int]] = field(default_factory=list)
    size: int = 0


def export_pack(out_zip: Path | str, *, version: str,
                snapshot: str | None = None, data_dir: Path | str | None = None,
                log=print) -> ExportReport:
    """把两块派生数据打成 zip，并**自验**（必带声明齐 ＋ 无本体数据）。"""
    data = Path(data_dir) if data_dir else DATA
    snap = snapshot or _now()
    items = [(name, (data / p.relative_to(DATA)) if data_dir else p, who, what)
             for name, p, who, what in PACK_ITEMS]
    for name, src, _who, _what in items:
        if not src.is_file():
            raise SystemExit("★ 要打包的文件不在：%s（先跑 rebuild_data.py 把它建出来）" % src)

    out = Path(out_zip)
    out.parent.mkdir(parents=True, exist_ok=True)

    #: 各自的快照信息（能取到就写实，取不到写"未记录"，不编）
    meta = {}
    ej = next((s for n, s, _w, _t in items if n == "enemydb.sqlite"), None)
    if ej is not None:
        import sqlite3
        con = sqlite3.connect("file:%s?mode=ro" % ej.as_posix(), uri=True)
        try:
            meta = {k: v for k, v in con.execute("select key, value from meta")}
        except Exception:                                     # noqa: BLE001
            meta = {}
        finally:
            con.close()

    decl = {
        "README.md": _readme(version, snap),
        "DATA-LICENSE.md": _data_license(version, snap),
        "SOURCES.md": _sources(version, snap, items, meta),
        "manifest.json": json.dumps({
            "pack": "rios-data", "version": version, "snapshot": snap,
            "license": "CC BY-NC-SA 4.0",
            "license_url": "https://creativecommons.org/licenses/by-nc-sa/4.0/",
            "contains_game_data": False,
            "items": [{"path": n, "bytes": s.stat().st_size, "sha256_16": _sha16(s),
                       "attribution": w, "what": t}
                      for n, s, w, t in items],
            "built_by": "R.I.O.S. datapack --export",
        }, ensure_ascii=False, indent=1) + "\n",
        "LICENSE-CC-BY-NC-SA-4.0.txt":
            "本数据包采用 知识共享 署名-非商业性使用-相同方式共享 4.0 国际 "
            "(CC BY-NC-SA 4.0) 许可。\n许可全文（中文）：%s\n"
            "英文原文：https://creativecommons.org/licenses/by-nc-sa/4.0/legalcode.en\n"
            "\n（本文件是许可指向说明；分发时应同时提供上述链接，或附许可全文。）\n" % CC_URL,
    }

    log("[1/2] 打包 %d 项派生数据 ＋ %d 份许可/来源文件 → %s"
        % (len(items), len(decl), out))
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for n, s, _w, _t in items:
            z.write(s, arcname=n)
            log("      ＋ %-28s %8.2f MB" % (n, s.stat().st_size / 1048576.0))
        for n, text in decl.items():
            z.writestr(n, text)

    rep = ExportReport(zip_path=out, size=out.stat().st_size,
                       items=[(n, s.stat().st_size) for n, s, _w, _t in items])

    log("[2/2] 自验（重开 zip 逐条看）")
    with zipfile.ZipFile(out) as z:
        names = [n for n in z.namelist() if not n.endswith("/")]
    bad = offending(names)
    miss = missing_decl(names)
    if bad:
        raise SystemExit("★ 包里有**游戏本体数据**，不允许分发：%s" % bad)
    if miss:
        raise SystemExit("★ 包里缺许可/来源文件：%s" % miss)
    log("      ✓ 无本体数据（按路径判据查过 %d 条）" % len(names))
    log("      ✓ 许可与来源文件齐（%s）" % "、".join(REQUIRED_DECL))
    log("      产物 %s（%.1f MB）" % (out, rep.size / 1048576.0))
    log("      ★ 这个包按 **CC BY-NC-SA 4.0** 发布：署名 prts.wiki/theresa.wiki、"
        "非商业、再分发要沿用同一许可。")
    return rep


def _readme(version: str, snap: str) -> str:
    return """# R.I.O.S. 数据包 %s

快照时刻：%s

这个仓只放**数据**，不放程序。程序在
[Rhodes-Island-Operation-Simulation-Service](https://github.com/Archer76/Rhodes-Island-Operation-Simulation-Service)。

## 里面是什么

| 文件 | 来源 | 说明 |
| --- | --- | --- |
| `enemydb.sqlite` | prts.wiki | 敌人图鉴／逐档数值／抗性／技能／天赋黑板 |
| `theresa/tile_info.json` | theresa.wiki | 地块字典（游戏本体的 gamedata 里**没有**这张表） |

**不含任何游戏本体数据**：不含关卡地图 JSON、不含 `enemy_database.json`、不含 `excel/`。
那部分版权属上海鹰角网络科技有限公司、且镜像站未授权，只能由使用者自行从源站取得。

## 许可

**CC BY-NC-SA 4.0**（署名-非商业性使用-相同方式共享）。详见 `DATA-LICENSE.md`。

## 怎么用

下载 Release 里的 zip，让程序自己装：

```
rios-tui.exe -install-datapack <zip>     （或）
python -m ak_tactic datapack --install <zip>
```

装了就不用再去抓 prts.wiki 与 theresa.wiki —— 但**游戏本体那部分照样要自己取**。
""" % (version, snap)


def _data_license(version: str, snap: str) -> str:
    return """# 本数据包的许可：CC BY-NC-SA 4.0

数据包版本 %s；快照时刻 %s。

本包内的数据整理自 **prts.wiki** 与 **theresa.wiki**，两站内容均采用
**知识共享 署名-非商业性使用-相同方式共享 4.0 国际 (CC BY-NC-SA 4.0)** 许可。
许可全文：%s

## 四条义务，逐条对应

1. **署名**：数据来自 prts.wiki 与 theresa.wiki 及其贡献者。
   本包由 R.I.O.S. 项目独立整理，**与上述站点无隶属关系，未经其审阅或背书**。
   逐文件来源见 `SOURCES.md`。
2. **修改**：我们对原始页面做了处理（构成改编）——解析 wikitext 模板、抽取字段、
   逐档继承合并、归一化抗性与技能冷却、写入 SQLite；地块字典取自站点的地图数据接口。
   **字段值与原文可能不一致，请以源站原文为准。**
3. **非商业**：本包**不得用于商业目的**。免费分发、自用、研究与教学可以。
   （若将来本项目接受赞助、收费或上架，本包必须下架。）
4. **相同方式共享**：你再分发本包或它的改编版本时，**必须沿用 CC BY-NC-SA 4.0**
   或与之兼容的许可，并保留本声明。

## 边界

本包**不含任何游戏本体数据**（不含关卡地图 JSON、`enemy_database.json`、`excel/`）。
那部分版权属上海鹰角网络科技有限公司，本包不对它作任何授权。
""" % (version, snap, CC_URL)


def _sources(version: str, snap: str, items, meta: dict) -> str:
    rows = ["| 包内文件 | 来源 | 抓取/建库时刻 | 处理 |", "| --- | --- | --- | --- |"]
    for n, s, who, what in items:
        when = snap
        if n == "enemydb.sqlite" and meta.get("built_at"):
            when = str(meta["built_at"])
        rows.append("| `%s` | %s | %s | %s |" % (n, who, when, what))
    extra = ""
    if meta:
        extra = ("\n库内自述（`enemydb.sqlite` 的 `meta` 表）：\n\n"
                 + "".join("- `%s` = %s\n" % (k, v) for k, v in sorted(meta.items())))
    return ("# 逐文件来源（数据包 %s，快照 %s）\n\n%s\n%s\n"
            "抓取工具：R.I.O.S. 的 `ak_tactic` 取数层；源站以抓取时刻的页面为准。\n"
            % (version, snap, "\n".join(rows), extra))


# ------------------------------------------------------------------ 装入

def install_pack(src: Path | str, *, data_dir: Path | str | None = None,
                 log=print) -> int:
    """把数据包装回去。**先验声明与判据**，再动玩家的数据目录。"""
    data = Path(data_dir) if data_dir else DATA
    src = Path(src)
    tmp: tempfile.TemporaryDirectory | None = None
    if src.is_dir():
        root = src
        names = [str(p.relative_to(src)).replace("\\", "/")
                 for p in src.rglob("*") if p.is_file()]
    else:
        tmp = tempfile.TemporaryDirectory(prefix="rios-datapack-")
        root = Path(tmp.name)
        with zipfile.ZipFile(src) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
            z.extractall(root)

    log("[1/3] 校验 %s（%d 个条目）" % (src, len(names)))
    miss = missing_decl(names)
    if miss:
        raise SystemExit("★ 这不是一个合规的数据包：缺 %s —— 拒装（来路不明的库"
                         "不该灌进数据目录）" % miss)
    bad = offending(names)
    if bad:
        raise SystemExit("★ 这个包里含**游戏本体数据**：%s —— 拒装（本包的许可"
                         "只覆盖 prts/theresa 派生内容）" % bad)
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    log("      ✓ 许可与来源文件齐；无本体数据")
    log("      快照时刻：%s（版本 %s，许可 %s）"
        % (man.get("snapshot"), man.get("version"), man.get("license")))

    log("[2/3] 装入 %s" % data)
    done = []
    for name, rel, _who, _what in ((n, p.relative_to(DATA), w, t) for n, p, w, t in PACK_ITEMS):
        s = root / name
        if not s.is_file():
            log("      － %-28s 包里没有，跳过" % name)
            continue
        dst = data / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        old = dst.stat().st_size if dst.is_file() else None
        shutil.copy2(s, dst)
        if name.endswith("tile_info.json"):
            #: 刷 mtime：`fetch_tile_info()` 有 7 天 TTL，不刷的话旧快照会被当过期缓存
            #: 重新去抓（真实快照时刻上面已经打印过，不是把旧的冒充成新的）。
            os.utime(dst, None)
        done.append((name, dst, old, dst.stat().st_size))
        log("      ✓ %-28s → %s（%s → %.1f MB）"
            % (name, dst, "新建" if old is None else "覆盖 %.1f MB" % (old / 1048576.0),
               dst.stat().st_size / 1048576.0))

    log("[3/3] 读数")
    #: ★ 留一个**标记**：建库脚本看到它 + 库在位，就跳过"抓 prts.wiki 建敌人库"
    #: 这一步 —— 不写这个标记的话，装进来的库下一轮会被重抓覆盖，这个包等于白装。
    marker = data / "datapack.json"
    marker.write_text(json.dumps({
        "installed_at": _now(), "pack": man.get("version"),
        "snapshot": man.get("snapshot"), "license": man.get("license"),
        "items": [d[0] for d in done],
        "note": "删掉本文件即恢复为「自己去抓 prts.wiki / theresa.wiki」",
    }, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    log("      标记：%s（建库脚本据此跳过二次抓取）" % marker)
    log("      装入 %d 项；接下来跑 rebuild_data.py 时会直接用它们"
        "（敌人库不必再抓 prts.wiki，地块字典不必再抓 theresa.wiki）" % len(done))
    log("      ⚠ 游戏本体数据（关卡地图/敌人数值/源表）**不在这个包里**，"
        "那部分仍要自己取。")
    if tmp is not None:
        tmp.cleanup()
    return 0


# ------------------------------------------------------------------ 自检

def selftest(log=print) -> int:
    """**离线**自检：造一个假数据目录，走一遍导出与装入，并配负对照。

    判据：① 导出的包必带五份声明、且**不含**任何本体数据路径；
          ② 装入会把两份数据放到正确位置、并刷地块那份的 mtime；
          ③ 负对照一：抽掉 `DATA-LICENSE.md` ⇒ 装入**拒装**（来路不明不灌库）；
          ④ 负对照二：往包里塞一个 `gamedata/level_x.json` ⇒ 导出与装入**都拒**。
    """
    bad = 0

    def check(label: str, cond: bool, detail: str = "") -> None:
        nonlocal bad
        if cond:
            log("  ✓ %s  %s" % (label, detail))
        else:
            bad += 1
            log("  ✗ %s  %s" % (label, detail))

    log("== 数据包 · 自检（离线，用假数据目录）==")
    with tempfile.TemporaryDirectory(prefix="rios-dp-") as td:
        t = Path(td)
        src_data = t / "src"
        (src_data / "cache" / "theresa").mkdir(parents=True)
        import sqlite3
        con = sqlite3.connect(src_data / "enemydb.sqlite")
        con.execute("create table meta(key text primary key, value text)")
        con.execute("insert into meta values('built_at','2026-01-01 00:00:00')")
        con.execute("insert into meta values('enemy_source','prts.wiki')")
        con.commit()
        con.close()
        (src_data / "cache" / "theresa" / "tile_info.json").write_text(
            json.dumps({"tile_floor": {"name": "地面"}}, ensure_ascii=False),
            encoding="utf-8")

        zip1 = t / "pack.zip"
        rep = export_pack(zip1, version="test-0", data_dir=src_data,
                          snapshot="2026-01-02T00:00:00", log=lambda *a: None)
        check("① 导出成功且有内容", rep.size > 0, "%.1f KB" % (rep.size / 1024.0))
        with zipfile.ZipFile(zip1) as z:
            names = [n for n in z.namelist() if not n.endswith("/")]
        check("① 必带五份许可/来源文件", not missing_decl(names),
              "缺 %s" % (missing_decl(names) or "无"))
        check("① 不含本体数据", not offending(names), "%s" % (offending(names) or "干净"))

        #: ② 装入到另一个假数据根
        dst_data = t / "dst"
        dst_data.mkdir()
        install_pack(zip1, data_dir=dst_data, log=lambda *a: None)
        ej = dst_data / "enemydb.sqlite"
        tj = dst_data / "cache" / "theresa" / "tile_info.json"
        check("② 敌人库落到位", ej.is_file(), str(ej))
        check("② 地块字典落到位", tj.is_file(), str(tj))
        check("② 地块那份 mtime 被刷成现在（否则 7 天 TTL 会把旧快照当过期）",
              abs(tj.stat().st_mtime - time.time()) < 120,
              "%.0f 秒前" % (time.time() - tj.stat().st_mtime))

        #: ③ 负对照一：抽掉 DATA-LICENSE.md ⇒ 拒装
        zip2 = t / "no-license.zip"
        with zipfile.ZipFile(zip1) as zin, zipfile.ZipFile(zip2, "w") as zout:
            for n in names:
                if n == "DATA-LICENSE.md":
                    continue
                zout.writestr(n, zin.read(n))
        try:
            install_pack(zip2, data_dir=dst_data, log=lambda *a: None)
            check("③ 负对照：缺 DATA-LICENSE.md ⇒ 拒装", False, "竟然装进去了")
        except SystemExit as e:
            check("③ 负对照：缺 DATA-LICENSE.md ⇒ 拒装",
                  "DATA-LICENSE.md" in str(e), str(e)[:60])

        #: ④ 负对照二：塞一个本体数据文件 ⇒ 判据必须抓到
        zip3 = t / "with-game.zip"
        with zipfile.ZipFile(zip1) as zin, zipfile.ZipFile(zip3, "w") as zout:
            for n in names:
                zout.writestr(n, zin.read(n))
            zout.writestr("gamedata/map.ark-nights.com/levels/level_main_01-07.json",
                          "{}")
        check("④ 负对照：包里混进 gamedata/ ⇒ 判据抓到",
              bool(offending(["gamedata/x/level_main_01-07.json"])), "抓到")
        try:
            install_pack(zip3, data_dir=dst_data, log=lambda *a: None)
            check("④ 负对照：含本体数据的包 ⇒ 拒装", False, "竟然装进去了")
        except SystemExit as e:
            check("④ 负对照：含本体数据的包 ⇒ 拒装", "游戏本体数据" in str(e),
                  str(e)[:60])

    log("== 结论：%s（红 %d 条）==" % ("全绿" if bad == 0 else "有红", bad))
    return 0 if bad == 0 else 1


def fetch_latest_pack(*, data_dir: Path | str | None = None,
                      log=print) -> int:
    """从我们的数据仓拉**最新**的包并装入（打开工具时自动请求的那一条路）。

    ★ 为什么这一步在 Python 而不是 Go：取数（含代理解析、重定向、许可校验）在
    Python 侧只有一份实现；Go 再来一份就是两份，迟早会漂（本仓那条老账）。
    博士 2026-09-27 也说了「不是非要 tui 直连，怎么方便怎么来」。
    """
    from .updates import PACK_API, PACK_REPO, _default_fetcher

    log("查数据包最新版：%s" % PACK_REPO)
    try:
        rel = json.loads(_default_fetcher(PACK_API))
    except Exception as e:                                    # noqa: BLE001
        raise SystemExit("★ 查数据包最新版失败：%s: %s" % (type(e).__name__, e))
    tag = str(rel.get("tag_name") or "")
    assets = rel.get("assets") or []
    zip_url = ""
    for a in assets:
        if str(a.get("name") or "").endswith(".zip"):
            zip_url = str(a.get("browser_download_url") or "")
            break
    if not tag or not zip_url:
        raise SystemExit("★ 最新 release 里没有 zip 资产（tag=%r）—— 仓里是不是还没发？" % tag)

    with tempfile.TemporaryDirectory(prefix="rios-pack-dl-") as td:
        dst = Path(td) / "pack.zip"
        log("  下载 %s" % zip_url)
        try:
            req = urllib.request.Request(zip_url, headers={
                "User-Agent": "rios-datapack-fetch"})
            with urllib.request.urlopen(req, timeout=120) as r, dst.open("wb") as f:
                shutil.copyfileobj(r, f)
        except Exception as e:                                # noqa: BLE001
            raise SystemExit("★ 下载数据包失败：%s: %s" % (type(e).__name__, e))
        log("  下到 %.2f MB（%s）" % (dst.stat().st_size / 1048576.0, tag))
        return install_pack(dst, data_dir=data_dir, log=log)


def _main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="python -m ak_tactic datapack",
        description="数据包（prts/theresa 派生，CC BY-NC-SA 4.0）：导出与装入")
    ap.add_argument("--export", metavar="ZIP", help="导出到这个 zip")
    ap.add_argument("--install", metavar="ZIP_OR_DIR", help="装入这个包")
    ap.add_argument("--fetch-latest", action="store_true",
                    help="从数据仓拉最新版并装入（打开工具时自动请求的那条路）")
    ap.add_argument("--version", default="data-v0.1.0", help="包版本（也是 release tag）")
    ap.add_argument("--selftest", action="store_true", help="离线自检")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()
    if a.export:
        export_pack(Path(a.export), version=a.version)
        return 0
    if a.install:
        return install_pack(Path(a.install))
    if a.fetch_latest:
        return fetch_latest_pack()
    ap.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(_main())
