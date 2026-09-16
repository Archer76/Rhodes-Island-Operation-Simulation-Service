"""地块字典（`tile` 表）——地块键 → 中文名与说明。

## 为什么它不在 gamedata 里

`excel/tile_table.json` **不存在**（GitHub 镜像与 ark-nights 两个源都 404），
`tile_data.json` 也没有。关卡 JSON 的 `mapData.tiles[]` 只给 `tileKey`，不给名字——
于是「这一格是什么」只能靠名字猜，而地块的**行为**（能不能部署、能不能走、
走进去会怎样）恰恰不在数据字段里（见 `gamedata/stage.py` 的 `IMPASSABLE_KEYS`：
洞与传送点的 `(heightType, buildableType, passableMask)` 与普通地面**完全一致**）。

目前唯一有这份字典的是 **theresa.wiki** 的地图页：它的 Next.js 数据接口
`/_next/data/<build>/map/<zone>/<stage>.json` 在 `pageProps.tileInfo` 里带一份
**95 条**的地块表（`tileKey` / `name` / `description` / `isFunctional`）。

## 三条实测事实

1. **它是全局表，不是每关一份。** 怀黍离 `act31side_08` 与红丝绒 `act54side_ex08`
   各取一份，**逐字节相同**（都是 95 条、键集合相同）。所以随便挑一关取即可。
2. **它不全。** 本地缓存 60 关用到的地块键并集里，`tile_xbdpsea`（只在生息演算
   `sandbox1_02` 出现）**不在表里**。按「子玩法忽视」的口径这可以接受，但**不能**
   把这张表当全集——`KNOWN_GAPS` 记着已知缺口，引用完整性自检据此放行而不是报错。
3. **它的说明是权威的，能纠正误判。** 例如 `tile_infection` 的真名是**活性源石**
   （部署的友军与经过的敌军获得攻击力与攻速提升，但持续受伤），**不是**被污染的
   田地；`tile_forbidden` 是**禁入区**、`tile_empty` 是**空**（且明说「游戏本体
   未包含该内容」）——这两条此前只能靠名字猜。

## 取数

`fetch_tile_info()` 走 theresa 的数据接口，缓存 7 天在 `data/cache/theresa/`。
build id 会随站点重新部署而变，所以先取首页正则
`/_next/static/<build>/_buildManifest.js` 拿到当前 build，再拼数据 URL。
取不到时 `build_db` 只记一条警告、**不挡住建库**——干员库其余部分不依赖它。
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

THERESA_BASE = "https://theresa.wiki"
DEFAULT_CACHE_DIR = Path("data/cache/theresa")
CACHE_TTL = 7 * 24 * 3600.0
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")

#: 取 tileInfo 用的探针关卡。**任意一关都行**（见模块 docstring 第一条），
#: 这里留两个不同活动的，前一个挂了还有后一个。
PROBE_ROUTES: tuple[tuple[str, str], ...] = (
    ("act31sre_zone1", "act31side_08"),      # 怀黍离
    ("act54side_zone2", "act54side_ex08"),   # 红丝绒
)

#: 已知缺口：本地关卡用得到、但 theresa 表里没有的地块键。
#: `tile_xbdpsea` 只在生息演算 `sandbox1_02` 出现（子玩法，按口径忽视）。
KNOWN_GAPS: tuple[str, ...] = ("tile_xbdpsea",)


class TileTableError(RuntimeError):
    """地块字典取不到。"""


def _get(url: str, *, timeout: float = 45.0) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
        return resp.read().decode("utf-8")


def current_build_id(*, timeout: float = 45.0) -> str:
    """站点当前的 Next.js build id（会随重新部署而变）。"""
    html = _get(THERESA_BASE + "/", timeout=timeout)
    m = re.search(r"/_next/static/([^/\"']+)/_buildManifest\.js", html)
    if not m:
        raise TileTableError("theresa 首页里找不到 build id")
    return m.group(1)


def fetch_tile_info(*, cache_dir: Path | str | None = None,
                    ttl: float = CACHE_TTL,
                    force: bool = False,
                    timeout: float = 45.0) -> dict[str, dict[str, Any]]:
    """取地块字典，返回 `{tileKey: {"name", "description", "isFunctional"}}`。

    :param cache_dir: 缓存目录，默认 `data/cache/theresa/`
    :param ttl: 缓存有效期（秒）；`0` 表示不用缓存
    :param force: 忽略缓存强制重取
    """
    cache = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
    cache.mkdir(parents=True, exist_ok=True)
    blob = cache / "tile_info.json"

    if not force and ttl > 0 and blob.exists():
        try:
            saved = json.loads(blob.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = None
        if isinstance(saved, dict):
            age = time.time() - float(saved.get("fetched_at") or 0.0)
            tiles = saved.get("tiles")
            if tiles and age < ttl:
                return tiles

    build = current_build_id(timeout=timeout)
    last: Exception | None = None
    for zone, stage in PROBE_ROUTES:
        url = f"{THERESA_BASE}/_next/data/{build}/map/{zone}/{stage}.json"
        try:
            data = json.loads(_get(url, timeout=timeout))
        except (urllib.error.URLError, OSError, ValueError) as exc:
            last = exc
            continue
        tiles = (data.get("pageProps") or {}).get("tileInfo")
        if tiles:
            blob.write_text(json.dumps(
                {"fetched_at": time.time(), "build": build,
                 "probe": f"{zone}/{stage}", "tiles": tiles},
                ensure_ascii=False, indent=1), encoding="utf-8")
            return tiles
        last = TileTableError(f"{zone}/{stage} 的 pageProps 里没有 tileInfo")
    raise TileTableError(f"地块字典取不到：{last}")


def insert_tiles(conn: sqlite3.Connection,
                 tiles: dict[str, dict[str, Any]]) -> int:
    """把地块字典写进 `tile` 表，返回写入条数。"""
    payload = [
        (key, str(v.get("name") or ""), str(v.get("description") or ""),
         1 if v.get("isFunctional") else 0)
        for key, v in sorted(tiles.items())
    ]
    conn.executemany(
        "INSERT OR REPLACE INTO tile (tile_key, name, description, is_functional) "
        "VALUES (?, ?, ?, ?)", payload)
    return len(payload)


def load_tiles(conn: sqlite3.Connection) -> dict[str, dict[str, Any]]:
    """从库里读回地块字典（读不到返回空 dict，调用方自己决定怎么办）。"""
    try:
        cur = conn.execute(
            "SELECT tile_key, name, description, is_functional FROM tile")
    except sqlite3.OperationalError:
        return {}
    return {r[0]: {"name": r[1], "description": r[2],
                   "is_functional": bool(r[3])} for r in cur}


def tile_name(conn: sqlite3.Connection, tile_key: str) -> str:
    """单个地块的中文名；库里没有就返回键本身（**不返回空串**，
    否则日志里会看到一片空白分不清是"没名字"还是"没查到"）。"""
    row = conn.execute("SELECT name FROM tile WHERE tile_key = ?",
                       (tile_key,)).fetchone()
    return (row[0] if row and row[0] else tile_key)
