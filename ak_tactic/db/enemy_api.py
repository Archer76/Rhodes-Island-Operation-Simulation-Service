"""敌人库（`data/enemydb.sqlite`）的查询面。

与干员库那套 `api.py` 平行、互不引用。开库/版本戳/只读 SQL 共用 `store.py`。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from .enemy_build import DEFAULT_ENEMY_DB_PATH
from .enemy_schema import ENEMY_DB_VERSION
from .store import (
    DatabaseMissing, db_info as _store_info, open_db, rows,
    run_readonly_sql,
)

__all__ = [
    "connect_enemy", "enemy_db_info", "find_enemies", "enemy_detail",
    "enemy_sql", "ENEMY_DB_SCHEMA_DOC", "effective_resists",
]

ENEMY_DB_SCHEMA_DOC = """表（敌人库，来自 prts.wiki 的「分类:敌人」；干员另有 data/akdb.sqlite）：
  meta          版本戳（db_version / built_at / enemy_source）
  enemy         图鉴：page 是主键；index_code 为空即无图鉴
                ability = 图鉴「能力」的**游戏内原文**；
                ability_fixed = **站方勘误后**文本（114 页有，空即无勘误）；
                ability_errata = 勘误原文（带 修正lite 标记），留追溯
  enemy_level   逐档数值 + 天赋文本 + 技力槽 + 黑板（**已算好继承**）
                另有 explicit_params（本档显式写的）与 hidden_params（被注释掉的）
                description_fixed = 档位描述里内联勘误展开后的正文（6 档有）
  enemy_resist  逐档抗性。source 区分 `字段`（标准 *=抗性）与 `覆写`（抗性覆写）
                **覆写压过同名字段**，is_effective 已算好胜负——
                要"这个敌人的真实抗性"就查 is_effective=1，别不过滤直接取全部
  enemy_skill   敌方技能：首次冷却 init_cooldown / 周期冷却 cooldown / sp_cost"""


def effective_resists(conn: sqlite3.Connection, page: str,
                      level: int | None = None) -> list[dict]:
    """一个敌人的**真实**抗性（已解掉 `覆写` 与 `字段` 的冲突）。

    只想看"它免疫什么"时用这个，别直接 `SELECT * FROM enemy_resist`——
    那张表里 `字段` 与 `覆写` 两套值并存（「蔓德拉」的字段全写「无」、
    覆写写七项免疫），不过滤就会把两种互相矛盾的读法一起拿到手里。
    """
    sql = ("SELECT level, name, value, is_immune, source FROM enemy_resist "
           "WHERE page=? AND is_effective=1")
    args: list[Any] = [page]
    if level is not None:
        sql += " AND level=?"
        args.append(level)
    return rows(conn, sql + " ORDER BY level, name", tuple(args))


def connect_enemy(path: Path | str | None = None, *,
                  readonly: bool = True) -> sqlite3.Connection:
    """打开敌人库。默认只读；文件不存在时给一句能照做的提示。"""
    return open_db(Path(path) if path else DEFAULT_ENEMY_DB_PATH,
                   readonly=readonly,
                   rebuild_hint="python -m ak_tactic enemydb build")


def enemy_db_info(conn: sqlite3.Connection) -> dict[str, Any]:
    return _store_info(conn, expected_version=ENEMY_DB_VERSION)


def enemy_sql(conn: sqlite3.Connection, query: str, *, limit: int = 200) -> list[dict]:
    return run_readonly_sql(conn, query, limit=limit)


def find_enemies(conn: sqlite3.Connection, keyword: str, *,
                 limit: int = 30, grade: str = "") -> list[dict]:
    """按页名 / 中文名 / 图鉴编号找敌人。空关键词 = 全部。

    排序按地位级别的轻重：领袖 > 精英 > 普通（不按拼音，查起来更有用）。
    """
    where, params = ["1=1"], []
    kw = (keyword or "").strip()
    if kw:
        where.append("(page LIKE ? OR name LIKE ? OR index_code LIKE ?)")
        params += [f"%{kw}%"] * 3
    if grade:
        where.append("grade = ?")
        params.append(grade)
    sql = ("SELECT page, name, index_code, grade, category, damage_type, "
           "attack_way, move_way, level_count, is_irregular, has_handbook "
           "FROM enemy WHERE " + " AND ".join(where) +
           " ORDER BY CASE grade WHEN '领袖' THEN 0 WHEN '精英' THEN 1 "
           "ELSE 2 END, prts_id LIMIT ?")
    params.append(limit)
    return rows(conn, sql, params)


def _resolve_page(conn: sqlite3.Connection, key: str) -> str:
    """把 `key`（页名或名字）解成唯一的页名。歧义就报错，别替人挑。"""
    if not key:
        raise DatabaseMissing("要给一个敌人，例如 `enemy show 源石虫`")
    row = conn.execute("SELECT page FROM enemy WHERE page = ?", (key,)).fetchone()
    if row is not None:
        return row["page"]

    found = list(conn.execute(
        "SELECT page, name, index_code FROM enemy WHERE name = ? OR page = ?",
        (key, key)))
    if len(found) == 1:
        return found[0]["page"]
    if len(found) > 1:
        names = "、".join(f"{r['name']}（{r['page']}）" for r in found[:6])
        raise DatabaseMissing(f"{key!r} 不唯一，可能是：{names}——请用页名指定")

    like = list(conn.execute(
        "SELECT page, name, index_code FROM enemy "
        "WHERE name LIKE ? OR page LIKE ? OR index_code LIKE ? LIMIT 10",
        (f"%{key}%", f"%{key}%", f"%{key}%")))
    if not like:
        raise DatabaseMissing(f"库里没有敌人 {key!r}")
    if len(like) == 1:
        return like[0]["page"]
    names = "、".join(f"{r['name']}（{r['page']}）" for r in like[:8])
    raise DatabaseMissing(f"{key!r} 匹配到多个敌人：{names}——请写全一点")


def enemy_detail(conn: sqlite3.Connection, key: str) -> dict[str, Any]:
    """一个敌人的完整战斗数据。`key` 可以是页名、中文名或图鉴编号。"""
    page = _resolve_page(conn, key)
    row = conn.execute("SELECT * FROM enemy WHERE page = ?", (page,)).fetchone()
    out: dict[str, Any] = {k: row[k] for k in row.keys()}
    out["is_irregular"] = bool(out["is_irregular"])
    out["has_handbook"] = bool(out["has_handbook"])
    out["raw_wikitext"] = None                 # 详情里不带整页原文，太大

    levels = rows(conn, "SELECT * FROM enemy_level WHERE page=? ORDER BY level",
                  (page,))
    resists = rows(conn, "SELECT level, name, value, is_immune, source, "
                         "is_effective FROM enemy_resist "
                         "WHERE page=? ORDER BY level, name, source", (page,))
    skills = rows(conn, "SELECT * FROM enemy_skill WHERE page=? "
                        "ORDER BY level, slot", (page,))
    for lv in levels:
        for k in ("params", "explicit_params", "hidden_params", "blackboard"):
            if lv.get(k):
                try:
                    lv[k] = json.loads(lv[k])
                except ValueError:
                    pass
        lv.pop("blackboard_raw", None)
        mine = [r for r in resists if r["level"] == lv["level"]]
        lv["resists"] = [r["name"][:-2] for r in mine if r["is_immune"]
                         and r["is_effective"]]
        # 被覆写顶掉的那些字段值单独留着——它们是"页面上写着、但不是真值"的记录
        lv["resists_superseded"] = [
            {"name": r["name"], "value": r["value"]}
            for r in mine if not r["is_effective"]
        ]
        lv["skills"] = [s for s in skills if s["level"] == lv["level"]]
    out["levels"] = levels
    return out
