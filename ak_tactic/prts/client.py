"""prts.wiki 的 MediaWiki API 客户端。

职责单一：把"一次 API 调用"变成"一次可靠的、被限速的、可缓存的取数"。
所有上游的脏活（403、SSL 抖动、限速）都在这里收口，上层只看见 dict。
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

API_ENDPOINT = "https://prts.wiki/api.php"
WIKI_BASE = "https://prts.wiki/w/"

#: PRTS 的 WAF 会拦掉没有浏览器 UA 的请求（裸 urllib 一律 403）。
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)

DEFAULT_CACHE_DIR = Path(__file__).resolve().parents[2] / "data" / "cache" / "prts"

#: 两次请求之间的最小间隔（秒）。并发打 PRTS 会吃 403，这是实测出来的值。
MIN_INTERVAL = 1.2

#: 默认缓存有效期（秒）：7 天。干员数据变动很慢。
DEFAULT_TTL = 7 * 24 * 3600


class PrtsError(RuntimeError):
    """上游不可用或返回了不符合预期的结构。"""


class RateLimiter:
    """进程内全局串行限速器——PRTS 的 WAF 是按来源 IP 计的。"""

    def __init__(self, min_interval: float = MIN_INTERVAL) -> None:
        self.min_interval = min_interval
        self._lock = threading.Lock()
        self._last = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = now - self._last
            if delta < self.min_interval:
                time.sleep(self.min_interval - delta)
            self._last = time.monotonic()


class Cache:
    """把 URL 映射到磁盘上的一个 JSON 文件。命中即零网络开销。"""

    def __init__(self, root: Path, enabled: bool = True, ttl: int = DEFAULT_TTL) -> None:
        self.root = Path(root)
        self.enabled = enabled
        self.ttl = ttl

    @staticmethod
    def _key(url: str) -> str:
        return hashlib.sha1(url.encode("utf-8")).hexdigest()

    def path_for(self, url: str) -> Path:
        return self.root / f"{self._key(url)}.json"

    def get(self, url: str, ttl: int | None = None) -> Any | None:
        if not self.enabled:
            return None
        p = self.path_for(url)
        if not p.exists():
            return None
        try:
            record = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        age = time.time() - record.get("fetched_at", 0)
        if age > (self.ttl if ttl is None else ttl):
            return None
        return record.get("body")

    def put(self, url: str, body: Any) -> None:
        if not self.enabled:
            return
        self.root.mkdir(parents=True, exist_ok=True)
        record = {"fetched_at": time.time(), "url": url, "body": body}
        tmp = self.path_for(url).with_suffix(".tmp")
        tmp.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.path_for(url))

    def clear(self) -> int:
        n = 0
        if self.root.exists():
            for f in self.root.glob("*.json"):
                f.unlink()
                n += 1
        return n


class PrtsClient:
    """prts.wiki API 的门面。"""

    def __init__(
        self,
        *,
        cache_dir: Path | str | None = None,
        use_cache: bool = True,
        ttl: int = DEFAULT_TTL,
        min_interval: float = MIN_INTERVAL,
        max_retries: int = 3,
        timeout: float = 45.0,
        user_agent: str = DEFAULT_UA,
    ) -> None:
        self.endpoint = API_ENDPOINT
        self.cache = Cache(Path(cache_dir) if cache_dir else DEFAULT_CACHE_DIR,
                           enabled=use_cache, ttl=ttl)
        self.limiter = RateLimiter(min_interval)
        self.max_retries = max_retries
        self.timeout = timeout
        self.user_agent = user_agent
        self.stats = {"requests": 0, "cache_hits": 0, "retries": 0, "errors": 0}

    # ---------------------------------------------------------------- 底层

    def _fetch(self, url: str) -> str:
        req = urllib.request.Request(url, headers={
            "User-Agent": self.user_agent,
            "Accept": "application/json,text/html;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Referer": "https://prts.wiki/",
        })
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read().decode("utf-8", "replace")

    def _fetch_with_retry(self, url: str) -> str:
        last: Exception | None = None
        for attempt in range(self.max_retries + 1):
            self.limiter.wait()
            self.stats["requests"] += 1
            try:
                return self._fetch(url)
            except urllib.error.HTTPError as e:
                # 403 多为 WAF 限速，退避后重试往往就能过；404 是真实不存在。
                if e.code == 404:
                    raise PrtsError(f"404 Not Found: {url}") from e
                last = e
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                last = e
            if attempt < self.max_retries:
                self.stats["retries"] += 1
                time.sleep(1.5 * (attempt + 1))
        self.stats["errors"] += 1
        raise PrtsError(f"请求失败（重试 {self.max_retries} 次后放弃）: {url}\n  最后错误: {last}")

    # ---------------------------------------------------------------- 公开

    def get_json(self, params: dict[str, Any], *, ttl: int | None = None,
                 use_cache: bool | None = None) -> dict:
        """调用 api.php 并返回解析后的 JSON。"""
        query = {**params, "format": "json", "formatversion": "2"}
        url = f"{self.endpoint}?{urllib.parse.urlencode(query)}"

        if use_cache is not False:
            hit = self.cache.get(url, ttl)
            if hit is not None:
                self.stats["cache_hits"] += 1
                return hit

        raw = self._fetch_with_retry(url)
        try:
            data = json.loads(raw)
        except ValueError as e:
            raise PrtsError(f"上游没有返回 JSON（可能被 WAF 拦成了 HTML）: {url}") from e
        if "error" in data:
            raise PrtsError(f"API 报错: {data['error'].get('info', data['error'])}")
        self.cache.put(url, data)
        return data

    def wikitext(self, title: str, *, ttl: int | None = None,
                 use_cache: bool | None = None) -> str:
        """取一个页面的 wikitext。页面不存在则抛 PrtsError。"""
        data = self.get_json({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": title,
        }, ttl=ttl, use_cache=use_cache)
        pages = data.get("query", {}).get("pages", [])
        if not pages:
            raise PrtsError(f"页面查询无结果: {title}")
        page = pages[0]
        if "missing" in page or "revisions" not in page:
            raise PrtsError(f"页面不存在: {title}")
        return page["revisions"][0]["slots"]["main"]["content"]

    def try_wikitext(self, title: str, **kw) -> str | None:
        """wikitext 的容错版：不存在就返回 None，不抛异常。"""
        try:
            return self.wikitext(title, **kw)
        except PrtsError:
            return None

    def search_pages(self, prefix: str, namespace: int = 0, limit: int = 500) -> list[str]:
        """按前缀列页面（用于枚举干员）。"""
        data = self.get_json({
            "action": "query", "list": "allpages", "apnamespace": str(namespace),
            "apprefix": prefix, "aplimit": str(limit),
        })
        return [p["title"] for p in data.get("query", {}).get("allpages", [])]

    def category_members(self, category: str, limit: int = 5000) -> list[str]:
        """列一个分类的全部成员，自动翻页。"""
        titles: list[str] = []
        cont: str | None = None
        while True:
            params = {
                "action": "query", "list": "categorymembers",
                "cmtitle": category if category.startswith("分类:") else f"分类:{category}",
                "cmlimit": "500", "cmnamespace": "0",
            }
            if cont:
                params["cmcontinue"] = cont
            data = self.get_json(params)
            titles.extend(m["title"] for m in data.get("query", {}).get("categorymembers", []))
            cont = data.get("continue", {}).get("cmcontinue")
            if not cont or len(titles) >= limit:
                break
        return titles[:limit]

    def cargo(self, tables: str, fields: str, *, where: str | None = None,
              order_by: str | None = None, limit: int = 500,
              offset: int = 0, group_by: str | None = None) -> list[dict]:
        """Cargo 结构查询。返回 [{字段: 值}, ...]。

        注意：Cargo API 不允许字段别名以 `_` 开头，所以 `_pageName` 必须
        写成 `_pageName=Page` 这种带别名的形式。
        """
        params: dict[str, Any] = {
            "action": "cargoquery", "tables": tables, "fields": fields,
            "limit": str(limit), "offset": str(offset),
        }
        if where:
            params["where"] = where
        if order_by:
            params["order_by"] = order_by
        if group_by:
            params["group_by"] = group_by
        data = self.get_json(params)
        return [row["title"] for row in data.get("cargoquery", [])]


_default_client: PrtsClient | None = None


def default_client() -> PrtsClient:
    """进程级默认客户端（共享缓存与限速器）。"""
    global _default_client
    if _default_client is None:
        _default_client = PrtsClient()
    return _default_client
