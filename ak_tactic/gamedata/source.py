"""游戏本体数据（gamedata）的取数层。

有两个可用镜像，**默认走 ark-nights**：

* **map.ark-nights.com**（PRTS.Map 的部署，第一选择）
  `https://map.ark-nights.com/data/...`，与 gamedata 同构但更精简
  （敌人库 6.4 MB vs 14.9 MB）。站点源码在 github.com/Houdou/prts-map。
* **Kengxxiao/ArknightsGameData**（备选，也是 theresa.wiki 自己声明的测试镜像）
  `https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/master/zh_CN/gamedata`

两者数据布局一致，差别在于 ark-nights 少一张 `excel/` 表（没有
`enemy_handbook_table.json`），并且**附带一份关卡索引**——这是它最值钱的
东西，见下。

## 关卡索引

ark-nights 的前端把一份 4694 条的关卡索引直接编译进了 JS bundle：

```json
"act54side_ex08": {"difficulty": "NORMAL", "zone_id": "act54side_zone2",
                   "data_path": "activities/act54side/level_act54side_ex08.json",
                   "code": "SR-EX-8"}
```

有了它才能把玩家嘴里的「SR-EX-8」换算成 `act54side_ex08`——活动关的
`levelId` 和显示名之间没有任何可推导的关系（`SR` 这个前缀只存在于活动表里）。
索引没有独立的 JSON 端点，只能从 bundle 里扒，所以这里做了解析 + 缓存。
"""

from __future__ import annotations

import json
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, NamedTuple

#: 数据根。ark-nights 的静态数据目录（PRTS.Map 部署）。
ARKNIGHTS_SITE = "https://map.ark-nights.com"
DEFAULT_BASE = f"{ARKNIGHTS_SITE}/data"

#: 备选镜像：站长声明的 gamedata 直链，目录结构完全相同。
GITHUB_BASE = ("https://raw.githubusercontent.com/Kengxxiao/ArknightsGameData/"
               "master/zh_CN/gamedata")

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "gamedata"

DEFAULT_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

INDEX_TTL = 7 * 86400


class GamedataError(RuntimeError):
    """取不到数据，或数据长得不像 gamedata。"""


class LevelEntry(NamedTuple):
    """关卡索引里的一条。"""

    level_id: str          # 如 act54side_ex08（四星版为 act54side_ex08#f#）
    code: str              # 玩家看到的关卡号，如 SR-EX-8
    zone_id: str           # 所属区域，如 act54side_zone2
    data_path: str         # 相对 levels/ 的路径
    difficulty: str        # NORMAL / FOUR_STAR


class GameDataSource:
    """gamedata 的取数门面。

    base 可以换成任何同构镜像：

        GameDataSource(base=GITHUB_BASE)          # 换回 GitHub 直链
        GameDataSource(base="https://your-mirror/gamedata")
    """

    def __init__(
        self,
        *,
        base: str = DEFAULT_BASE,
        site: str | None = None,
        cache_dir: Path | str | None = None,
        use_cache: bool = True,
        ttl: int | None = None,
        index_ttl: int = INDEX_TTL,
        timeout: float = 300.0,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self.base = base.rstrip("/")
        # 站点根：只有 ark-nights 源才用得上（取 bundle 扒索引）
        self.site = (site or (ARKNIGHTS_SITE if "ark-nights" in self.base else "")).rstrip("/")
        self.cache_dir = Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR
        self.use_cache = use_cache
        self.ttl = ttl              # None = 永不过期（gamedata 是版本化的快照）
        self.index_ttl = index_ttl
        self.timeout = timeout
        self.user_agent = user_agent
        self._lock = threading.Lock()
        self._mem: dict[str, Any] = {}
        self._index: dict[str, dict] | None = None
        self.stats = {"downloads": 0, "disk_hits": 0, "mem_hits": 0, "bytes": 0}

    # ---------------------------------------------------------------- 路径

    def _url(self, rel_path: str) -> str:
        return f"{self.base}/{rel_path.lstrip('/')}"

    def _mirror_id(self) -> str:
        """缓存分目录用的镜像标识。

        两个镜像的 gamedata 路径完全同名（`levels/enemydata/enemy_database.json`），
        按路径缓存会互相顶替——先用 ark-nights 抓一份，再换 GitHub 就会
        命中错的缓存。所以按域名分开放。
        """
        host = urllib.parse.urlparse(self.base).netloc or "local"
        return re.sub(r"[^0-9A-Za-z._-]", "_", host)

    def local_path(self, rel_path: str) -> Path:
        safe = rel_path.replace("\\", "/").lstrip("/")
        return self.cache_dir / self._mirror_id() / safe

    # ---------------------------------------------------------------- 取数

    def fetch_json(self, rel_path: str, *, use_cache: bool | None = None) -> Any:
        """取一个 JSON 文件。内存 → 磁盘 → 网络，三级取数。"""
        if rel_path in self._mem:
            self.stats["mem_hits"] += 1
            return self._mem[rel_path]

        cache_on = self.use_cache if use_cache is None else use_cache
        local = self.local_path(rel_path)

        if cache_on and local.exists():
            if self.ttl is None or (time.time() - local.stat().st_mtime) < self.ttl:
                self.stats["disk_hits"] += 1
                data = self._read_json(local)
                self._mem[rel_path] = data
                return data

        raw = self._download(self._url(rel_path))
        data = self._parse(raw, rel_path)
        if cache_on:
            self._write_cache(local, raw)
        self._mem[rel_path] = data
        return data

    def fetch_text(self, rel_path: str, *, use_cache: bool | None = None) -> str:
        """取一个纯文本文件（如 `excel/data_version.txt`）。三级取数同 `fetch_json`。

        用途主要是**版本戳**：把 data_version.txt 的原文存进本地库，日后才答得上
        "这个库是哪一版数据建的"。内存键加 `text:` 前缀，免得与同路径的 JSON 撞。
        """
        key = f"text:{rel_path}"
        if key in self._mem:
            self.stats["mem_hits"] += 1
            return self._mem[key]

        cache_on = self.use_cache if use_cache is None else use_cache
        local = self.local_path(rel_path)

        if cache_on and local.exists():
            if self.ttl is None or (time.time() - local.stat().st_mtime) < self.ttl:
                self.stats["disk_hits"] += 1
                text = local.read_text(encoding="utf-8-sig")
                self._mem[key] = text
                return text

        raw = self._download(self._url(rel_path), accept="text/plain,*/*")
        text = raw.decode("utf-8-sig")
        if cache_on:
            self._write_cache(local, raw)
        self._mem[key] = text
        return text

    def _write_cache(self, local: Path, raw: bytes) -> None:
        local.parent.mkdir(parents=True, exist_ok=True)
        tmp = local.with_suffix(local.suffix + ".part")
        tmp.write_bytes(raw)
        tmp.replace(local)

    def _download(self, url: str, *, accept: str = "application/json,*/*",
                  timeout: float | None = None) -> bytes:
        with self._lock:
            self.stats["downloads"] += 1
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": accept,
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise GamedataError(
                    f"镜像里没有这个文件：{url}\n"
                    f"  （关卡路径由关卡索引给出，形如 levels/obt/main/level_main_01-07.json "
                    f"或 levels/activities/act54side/level_act54side_ex08.json）") from e
            raise GamedataError(f"下载失败 HTTP {e.code}：{url}") from e
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise GamedataError(f"下载失败：{url}\n  {e}") from e
        self.stats["bytes"] += len(raw)
        return raw

    @staticmethod
    def _parse(raw: bytes, label: str) -> Any:
        text = raw.decode("utf-8-sig")
        try:
            return json.loads(text)
        except ValueError as e:
            raise GamedataError(f"{label} 不是合法 JSON：{e}") from e

    @staticmethod
    def _read_json(path: Path) -> Any:
        return json.loads(path.read_text(encoding="utf-8-sig"))

    # ------------------------------------------------------------ 关卡索引

    @property
    def index_path(self) -> Path:
        return self.cache_dir / "_level_index.json"

    def level_index(self, *, refresh: bool = False) -> dict[str, dict]:
        """关卡索引：levelId → {code, zone_id, data_path, difficulty}。

        ark-nights 把它编译进了 JS bundle，没有独立端点，所以这里先把
        bundle 拉下来、把那份 `JSON.parse('...')` 里最长的字典抠出来，
        再缓存到本地。首次约 7 MB，之后走缓存。
        """
        if self._index is not None and not refresh:
            return self._index

        cache = self.index_path
        if not refresh and cache.exists() and \
                (time.time() - cache.stat().st_mtime) < self.index_ttl:
            self._index = self._read_json(cache)
            return self._index

        if not self.site:
            raise GamedataError(
                "当前镜像没有关卡索引（只有 ark-nights 源带这份索引）。\n"
                "  用 levelId 直接取关卡，或换成 GameDataSource(base=DEFAULT_BASE)")
        try:
            index = self._scrape_index()
        except GamedataError:
            if cache.exists():          # 扒不到就先用旧的，别把路堵死
                self._index = self._read_json(cache)
                return self._index
            raise

        self._write_cache(cache, json.dumps(index, ensure_ascii=False).encode("utf-8"))
        self._index = index
        return index

    def _scrape_index(self) -> dict[str, dict]:
        html = self._download(f"{self.site}/", accept="text/html",
                             timeout=60).decode("utf-8", "replace")
        names = re.findall(r'"(/bundle\.[0-9a-fA-F]+\.js)"', html)
        if not names:
            raise GamedataError("站点首页里找不到 bundle 文件名，关卡索引扒不到")

        best: dict[str, dict] | None = None
        for name in names:
            js = self._download(f"{self.site}{name}", accept="*/*",
                                timeout=180).decode("utf-8", "replace")
            for m in re.finditer(r"JSON\.parse\(", js):
                q = js.find("'", m.end())
                if q < 0 or q > m.end() + 30:
                    continue
                i = q + 1
                while i < len(js):
                    c = js[i]
                    if c == "\\":
                        i += 2
                        continue
                    if c == "'":
                        break
                    i += 1
                try:
                    obj = json.loads(js[q + 1:i])
                except ValueError:
                    continue
                if isinstance(obj, dict) and obj and \
                        all(isinstance(v, dict) and "data_path" in v for v in obj.values()):
                    if best is None or len(obj) > len(best):
                        best = obj
        if best is None:
            raise GamedataError("bundle 里没找到关卡索引")
        return best

    def resolve_level(self, query: str) -> LevelEntry:
        """把玩家写的关卡号或 levelId 解析成一条索引。

        认得这几种写法：``SR-EX-8``、``main_01-07``、``1-7``、``act54side_ex08``。
        默认取普通难度；带 `#f#` 后缀的是四星限定版，要用的话直接写全。
        """
        q = query.strip()
        try:
            index = self.level_index()
        except GamedataError:
            index = {}

        if q in index:
            v = index[q]
            return LevelEntry(q, v.get("code", q), v.get("zone_id", ""),
                              v["data_path"], v.get("difficulty", "NORMAL"))

        upper = q.upper()
        hits = [(k, v) for k, v in index.items()
                if (v.get("code") or "").upper() == upper]
        if hits:
            # 同 code 可能有普通/四星两条，优先普通
            k, v = next(((k, v) for k, v in hits if v.get("difficulty") == "NORMAL"),
                        hits[0])
            return LevelEntry(k, v.get("code", q), v.get("zone_id", ""),
                              v["data_path"], v.get("difficulty", "NORMAL"))

        # 索引里没有（新关卡、或非 ark-nights 源）：按老规矩猜主线路径
        head = q.split("_", 1)[0]
        guess = f"obt/{head}/level_{q}.json"
        return LevelEntry(q, q, "", guess, "NORMAL")

    def search_levels(self, keyword: str, *, limit: int = 30) -> list[LevelEntry]:
        """按 code 或 levelId 模糊找关卡。"""
        kw = keyword.strip().upper()
        out: list[LevelEntry] = []
        for k, v in self.level_index().items():
            if kw in k.upper() or kw in (v.get("code") or "").upper() \
                    or kw in (v.get("zone_id") or "").upper():
                out.append(LevelEntry(k, v.get("code", k), v.get("zone_id", ""),
                                      v["data_path"], v.get("difficulty", "NORMAL")))
        # 普通难度在前，同 code 去重
        out.sort(key=lambda e: ("#f#" in e.level_id, e.code))
        seen: set[str] = set()
        uniq: list[LevelEntry] = []
        for e in out:
            if e.code in seen:
                continue
            seen.add(e.code)
            uniq.append(e)
        return uniq[:limit]

    # ------------------------------------------------------------ 语义接口

    def level(self, level_id: str, *, chapter: str | None = None) -> dict:
        """取一份关卡数据。

        参数可以是 levelId（``act54side_ex08``），也可以是玩家写的关卡号
        （``SR-EX-8``）——后者靠关卡索引换算。
        """
        entry = self.resolve_level(level_id)
        rel = f"levels/{entry.data_path}"
        data = self.fetch_json(rel)
        if isinstance(data, dict):
            # 关卡文件自己不记录关卡号，回填进去省得调用方再查一遍
            data.setdefault("_levelId", entry.level_id)
            data.setdefault("_code", entry.code)
        return data

    def level_path(self, level_id: str) -> str:
        return f"levels/{self.resolve_level(level_id).data_path}"

    def enemy_database(self) -> dict:
        """敌人属性库。约 6.4 MB（ark-nights）或 14.9 MB（GitHub）。"""
        return self.fetch_json("levels/enemydata/enemy_database.json")

    def enemy_handbook(self) -> dict:
        """敌人图鉴：名字、编号、描述、伤害类型。

        **只有 GitHub 镜像有这张表**；ark-nights 没有 `excel/`，
        这时返回空字典，名字改用属性库里的 `name` 字段。
        """
        try:
            return self.fetch_json("excel/enemy_handbook_table.json")
        except GamedataError:
            return {}

    def has_handbook(self) -> bool:
        try:
            self.fetch_json("excel/enemy_handbook_table.json")
            return True
        except GamedataError:
            return False

    # ---------------------------------------------------------------- 维护

    def release(self, rel_path: str) -> None:
        """丢掉内存里的一份数据（磁盘缓存不动）。

        给 `EnemyLibrary` 用：属性库解析成精简索引后，原始对象没有留着的
        必要，而它变成 Python 对象后会膨胀好几倍。
        """
        self._mem.pop(rel_path, None)

    def cached_files(self) -> list[Path]:
        if not self.cache_dir.exists():
            return []
        return sorted(p for p in self.cache_dir.rglob("*") if p.is_file())

    def cache_size(self) -> int:
        return sum(p.stat().st_size for p in self.cached_files())

    def clear_cache(self) -> tuple[int, int]:
        """删掉本地 gamedata 缓存，返回 (文件数, 释放字节数)。"""
        files = self.cached_files()
        total = sum(p.stat().st_size for p in files)
        for p in files:
            try:
                p.unlink()
            except OSError:
                pass
        self._mem.clear()
        self._index = None
        return len(files), total
