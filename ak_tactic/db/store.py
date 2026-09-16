"""两个本地库共用的 SQLite 门面。

干员库（`data/akdb.sqlite`）与敌人库（`data/enemydb.sqlite`）是**两个独立的文件**，
互不引用、各自可单独重建。但"开库 / 读版本戳 / 跑只读 SQL"这三件事是一样的，
收在这里，免得两处各写一遍——尤其是只读守卫，那是安全相关的，
有两份会漂移的实现迟早出事。
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Iterable

__all__ = ["DatabaseMissing", "open_db", "db_info", "rows", "run_readonly_sql"]


class DatabaseMissing(RuntimeError):
    """库文件不存在、结构版本不符，或查询被只读守卫拒绝。"""


def open_db(path: Path | str, *, readonly: bool = True,
            rebuild_hint: str = "") -> sqlite3.Connection:
    """打开库。默认只读；文件不存在时给一句能照做的提示。"""
    target = Path(path)
    if not target.exists():
        msg = f"本地库还不存在：{target}"
        if rebuild_hint:
            msg += f"\n  先建一次：{rebuild_hint}"
        raise DatabaseMissing(msg)
    if readonly:
        conn = sqlite3.connect(f"file:{target.as_posix()}?mode=ro", uri=True)
    else:
        conn = sqlite3.connect(target)
    conn.row_factory = sqlite3.Row
    return conn


def db_info(conn: sqlite3.Connection, *, expected_version: int) -> dict[str, Any]:
    """版本戳 + 各表行数，并核对结构版本（旧结构直接说明白）。"""
    meta = {r["key"]: r["value"] for r in conn.execute("SELECT * FROM meta")}
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    counts: dict[str, int] = {}
    for t in tables:
        if t == "meta":
            continue
        counts[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
    version = int(meta.get("db_version") or -1)
    return {"meta": meta, "counts": counts, "tables": tables,
            "version_ok": version == expected_version,
            "expected_version": expected_version}


def rows(conn: sqlite3.Connection, sql: str, params: Iterable = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params)]


def run_readonly_sql(conn: sqlite3.Connection, query: str, *,
                     limit: int = 200) -> list[dict]:
    """跑一条**只读** SQL。写语句一律拒绝——库是可重建的派生物，别绕过构建器。"""
    stripped = query.strip().lstrip("(").lower()
    if not stripped.startswith(("select", "with", "pragma table_info")):
        raise DatabaseMissing("只允许 SELECT / WITH / PRAGMA table_info 查询")
    return [dict(r) for r in list(conn.execute(query))[:limit]]
