"""取数前的预估：**告诉用户要花多久、多大，再动手**。

## 为什么要有这个

「开始拉取数据」这一步动辄几十秒到几分钟、几十 MB。用户在按下去之前应当知道代价，
否则只会以为程序卡死了。本模块给出一行一源的预估：**多久、多大、依据是什么**。

## 不写死水位（这是本模块的第一原则）

字节数与耗时都会随上游版本变（关卡索引的 bundle 会换 hash、excel 表会随版本长）。
所以**上报的数字按可信度分三档，每一档都把自己的依据写出来**：

| 档 | 依据 | 打印成 |
|---|---|---|
| 1 | 缓存里已有文件，`stat()` 出来的**实际字节** | `已缓存 24.8 MB` |
| 2 | 上一次真取过，`_fetch_stats.json` 里的**实测**字节与耗时 | `约 24.8 MB / 38 秒（上次实测）` |
| 3 | 都没有 → 发一个 `HEAD` 拿 `Content-Length` | `约 24.8 MB（本次实测体积）；耗时按 300 KB/s 估` |
| — | 连 HEAD 都失败 | `体积未知（探测失败）；按 N 个请求估 ≥ M 秒` |

**耗时永远带一个显式假设**，因为吞吐量取决于用户网络；字节数则尽量是真值。
`POLITE_INTERVAL` 那一条是硬下限而不是估算——prts.wiki 的礼貌间隔是实测约束
（并发即 403），所以「N 个请求」直接给出 N × 1.2 秒的地板。

## 统计怎么攒起来

每次真取完（成功或失败）都 `record()` 一次，落 `data/cache/_fetch_stats.json`。
它不是缓存的一部分（删了只会让预估退回第 3 档），所以 `cache --clear-*` 不必管它。
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "POLITE_INTERVAL", "DEFAULT_THROUGHPUT", "FetchEstimate", "EstimateReport",
    "stats_path", "load_stats", "record", "probe_bytes", "format_bytes",
    "format_seconds",
]

#: prts.wiki 的礼貌间隔（实测：并发即 403）。这是**硬下限**，不是估值。
POLITE_INTERVAL = 1.2

#: 拿不到实测耗时时用的假设吞吐。**这是个假设，打印时必须标出来。**
DEFAULT_THROUGHPUT = 300 * 1024.0        # 字节/秒

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")


# ---------------------------------------------------------------- 统计落盘

def stats_path(root: Path | str | None = None) -> Path:
    base = Path(root) if root else Path("data/cache")
    return base / "_fetch_stats.json"


def load_stats(root: Path | str | None = None) -> dict[str, dict]:
    p = stats_path(root)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def record(key: str, *, hits: int, bytes_: int | None,
           seconds: float, ok: bool = True,
           bytes_basis: str = "", root: Path | str | None = None) -> None:
    """记一次真取的实测值。失败也记——失败次数同样是预估的依据。

    `bytes_` 传 `None` 表示"这次没测到体积"，保留上一次的值不动；
    `bytes_basis` 说明那个体积是怎么来的（实测/HEAD 探测），免得下次把它
    当成真下载量报出去。
    """
    p = stats_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    data = load_stats(root)
    prev = data.get(key) or {}
    data[key] = {
        "hits": hits,
        "bytes": bytes_ if bytes_ is not None else prev.get("bytes"),
        "bytes_basis": bytes_basis or prev.get("bytes_basis") or "",
        "seconds": round(seconds, 2),
        "ok": ok,
        "at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }
    try:
        p.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    except OSError:
        pass                                  # 记不上统计不该让取数失败


# ---------------------------------------------------------------- 体积探测

def probe_bytes(urls: list[str], *, timeout: float = 20.0,
                headers: dict | None = None) -> tuple[int | None, list[str]]:
    """对每个 URL 发 HEAD，返回 `(总字节数, 拿不到的那批 URL)`。

    HEAD 被拒（405/501）或服务端不给 `Content-Length` 时，那个 URL 进第二项——
    **不猜**，猜出来的体积比没有体积更坏。整批一个都没拿到就返回 `(None, ...)`。
    """
    total = 0
    got_any = False
    failed: list[str] = []
    hdr = {"User-Agent": USER_AGENT, **(headers or {})}
    for url in urls:
        size = _head_size(url, hdr, timeout)
        if size is None:
            failed.append(url)
            continue
        total += size
        got_any = True
    return (total if got_any else None), failed


def _head_size(url: str, headers: dict, timeout: float) -> int | None:
    req = urllib.request.Request(url, headers=headers, method="HEAD")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:   # noqa: S310
            raw = resp.headers.get("Content-Length")
            return int(raw) if raw and raw.isdigit() else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


# ---------------------------------------------------------------- 预估条目

@dataclass
class FetchEstimate:
    """一个取数源的预估。**每一项都自带依据**，不许只有数字。"""

    key: str
    label: str
    hits: int = 0
    bytes_: int | None = None
    seconds: float | None = None
    basis: str = ""
    cached_bytes: int = 0
    floor_seconds: float = 0.0            # 硬下限（礼貌间隔 × 请求数）

    @property
    def cached(self) -> bool:
        return self.cached_bytes > 0 and not self.seconds

    def line(self) -> str:
        size = (f"已缓存 {format_bytes(self.cached_bytes)}"
                if self.cached else
                f"{format_bytes(self.bytes_)}"
                if self.bytes_ is not None else "体积未知")
        when = (f"不用取" if self.cached else
                f"{format_seconds(self.seconds)}"
                if self.seconds is not None else "耗时未知")
        head = f"  {self.label:<14} {self.hits:>3} 个请求  {size:<18} {when}"
        return f"{head}\n      {self.basis}" if self.basis else head


@dataclass
class EstimateReport:
    title: str
    items: list[FetchEstimate] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def total_bytes(self) -> int | None:
        vals = [i.bytes_ or i.cached_bytes for i in self.items]
        return sum(vals) if any(v is not None for v in vals) else None

    @property
    def total_seconds(self) -> float:
        return sum(max(i.floor_seconds, i.seconds or 0.0)
                   for i in self.items if not i.cached)

    def render(self) -> str:
        lines = [self.title, ""]
        if not self.items:
            lines.append("  （没有要取的东西）")
        for it in self.items:
            lines.append(it.line())
        lines.append("")
        tot_b = self.total_bytes
        lines.append(f"  合计：体积 {format_bytes(tot_b) if tot_b is not None else '未知'}"
                     f"　预计耗时 {format_seconds(self.total_seconds)}")
        for n in self.notes:
            lines.append(f"  注：{n}")
        return "\n".join(lines)


# ---------------------------------------------------------------- 小工具

def format_bytes(n: int | None) -> str:
    if n is None:
        return "未知"
    v = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if v < 1024 or unit == "GB":
            return f"{v:.0f} {unit}" if unit == "B" else f"{v:.1f} {unit}"
        v /= 1024
    return f"{v:.1f} GB"


def format_seconds(s: float | None) -> str:
    if s is None:
        return "未知"
    if s < 60:
        return f"约 {s:.0f} 秒"
    m, sec = divmod(int(round(s)), 60)
    return f"约 {m} 分 {sec:02d} 秒"


# ---------------------------------------------------------------- 各源的具体预估

#: `db build` 要取的表（与 ak_tactic/db/build.py 的取数一致）
GAMEDATA_STATS_KEY = "gamedata_excel"
GAMEDATA_FILES = (
    "excel/character_table.json",
    "excel/skill_table.json",
    "excel/uniequip_table.json",
    "excel/battle_equip_table.json",
    "excel/char_patch_table.json",
    "excel/range_table.json",
    "excel/data_version.txt",
)


def throughput(key: str, root: Path | str | None = None) -> tuple[float, str]:
    """本机实测吞吐 `(字节/秒, 依据说明)`。没有实测就退回假设值并**标出来**。

    实测吞吐 = 上次真取的 `bytes / seconds`。这比写死一个 KB/s 强得多：
    用户换网络、换镜像，下一次的实测自然会跟上。
    """
    saved = (load_stats(root) or {}).get(key) or {}
    b, s = saved.get("bytes"), saved.get("seconds")
    if b and s and float(s) > 0:
        return float(b) / float(s), f"上次实测吞吐 {float(b) / float(s) / 1024:.0f} KB/s"
    return DEFAULT_THROUGHPUT, f"按 {DEFAULT_THROUGHPUT / 1024:.0f} KB/s 估（假设值，取决于你的网络）"


def estimate_gamedata(source=None, *,
                      root: Path | str | None = None) -> tuple[FetchEstimate, list[str]]:
    """`db build` 之前的一笔账。返回 `(预估, 还需下载的相对路径列表)`。

    已缓存的文件按**实际字节**计入 `cached_bytes` 并从待下载里剔除——重复建库
    一分钱不花，这件事用户该看得见。
    """
    from .db.build import DEFAULT_SOURCE
    from .gamedata.source import GameDataSource

    src = source or GameDataSource(base=DEFAULT_SOURCE)
    cached = 0
    pending: list[str] = []
    for rel in GAMEDATA_FILES:
        p = src.local_path(rel)
        if p.exists() and p.stat().st_size > 0:
            cached += p.stat().st_size
        else:
            pending.append(rel)

    if not pending:
        return FetchEstimate(
            key=GAMEDATA_STATS_KEY, label="干员库表", hits=0,
            cached_bytes=cached,
            basis=f"{len(GAMEDATA_FILES)} 个 excel 表全都已缓存，建库不联网"), pending

    size, failed = probe_bytes([src._url(r) for r in pending])
    tput, tnote = throughput(GAMEDATA_STATS_KEY, root)
    secs = (size / tput) if size else None
    basis = (f"{len(pending)}/{len(GAMEDATA_FILES)} 个要下，体积本次 HEAD 实测；"
             f"耗时{tnote}")
    if size is None:
        basis = (f"{len(pending)}/{len(GAMEDATA_FILES)} 个要下，但 HEAD 拿不到 "
                 f"Content-Length（{len(failed)} 个），体积未知；耗时{tnote}")
    return FetchEstimate(
        key=GAMEDATA_STATS_KEY, label="干员库表", hits=len(pending),
        bytes_=size, seconds=secs, cached_bytes=cached,
        basis=basis), pending


def dir_bytes(path: Path | str) -> int:
    """一个目录下所有文件的总字节数（目录不存在算 0）。用于量"这次真下了多少"。"""
    p = Path(path)
    if not p.exists():
        return 0
    total = 0
    for f in p.rglob("*"):
        try:
            if f.is_file():
                total += f.stat().st_size
        except OSError:
            pass
    return total
