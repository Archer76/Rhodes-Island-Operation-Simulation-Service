"""干员库（`data/akdb.sqlite`）的查询面。

只读为主：库是派生物，改动一律走 `build_db()` 重建。`connect(readonly=True)`
会把连接开成只读（`file:...?mode=ro`），免得手滑写坏一个可重建的东西。

开库/版本戳/只读 SQL 这三件事与敌人库共用，实现在 `store.py`。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .build import DEFAULT_DB_PATH
from .schema import DB_VERSION
from .store import (
    DatabaseMissing, db_info as _store_info, open_db, rows,
    run_readonly_sql,
)

__all__ = [
    "DatabaseMissing", "connect", "db_info", "find_operators", "char_detail",
    "search_skills", "search_talents", "run_sql", "DB_SCHEMA_DOC",
]

DB_SCHEMA_DOC = """表（干员库，来自 gamedata 的 excel/；敌人另有一库，见 `enemy schema`）：
  meta              版本戳（db_version / data_version / built_at / source）
  operator          干员本体（含召唤物与装置，is_operator 区分）
  operator_phase    阶段：范围代号、阶段内最高等级
  operator_attr     属性关键帧（kind='phase' 等级帧 / 'trust' 信赖帧）
  operator_potential 潜能 0 起算的属性修正器
  operator_talent   天赋（组 → 候选），blackboard 是拍平后的 {键: 值}
  operator_trait    结构化职业特性（只有部分干员有）
  operator_skill    干员 → 技能槽位
  skill / skill_level 技能本体与全等级（倍率、SP、持续、范围、黑板）
  module / module_level 模组本体与逐级属性/改写
  attack_range      范围代号 → 格集合（cells 已是 (x, y) 相对格）"""


def connect(path: Path | str | None = None, *,
            readonly: bool = True) -> sqlite3.Connection:
    """打开干员库。默认只读；文件不存在时给一句能照做的提示。"""
    return open_db(Path(path) if path else DEFAULT_DB_PATH, readonly=readonly,
                   rebuild_hint="python -m ak_tactic db build")


def db_info(conn: sqlite3.Connection) -> dict[str, Any]:
    """版本戳 + 各表行数。顺带核对结构版本，旧结构直接说明白。"""
    return _store_info(conn, expected_version=DB_VERSION)


def find_operators(conn: sqlite3.Connection, keyword: str, *,
                   limit: int = 20, operators_only: bool = True) -> list[sqlite3.Row]:
    """按 id / 中文名 / 英文名找干员。空关键词 = 全部（按稀有度与序号排）。"""
    kw = (keyword or "").strip()
    where, params = [], []
    if operators_only:
        where.append("is_operator = 1")
    if kw:
        where.append("(char_id LIKE ? OR name LIKE ? OR appellation LIKE ?)")
        params += [f"%{kw}%"] * 3
    sql = ("SELECT char_id, name, appellation, rarity, profession_cn, "
           "sub_profession_name, position, is_operator, is_patch FROM operator")
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY rarity DESC, sort_index LIMIT ?"
    params.append(limit)
    return list(conn.execute(sql, params))


_rows = rows


def char_detail(conn: sqlite3.Connection, key: str) -> dict[str, Any]:
    """一个干员的完整战斗数据。`key` 可以是 id 也可以是名字。"""
    row = conn.execute(
        "SELECT * FROM operator WHERE char_id = ?", (key,)).fetchone()
    if row is None:
        found = list(find_operators(conn, key, limit=12))
        if not found:                       # 真干员里没有，再把召唤物/装置算上
            found = list(find_operators(conn, key, limit=12, operators_only=False))
        if not found:
            raise DatabaseMissing(f"库里没有干员 {key!r}")

        # 名字会撞车：有个装置也叫「阿米娅」，而升变形态（char_1001_amiya2 /
        # char_1037_amiya3）与本体同名同姓。优先级——
        # 精确匹配且是本体的真干员 → 精确匹配的真干员 → 精确匹配 → 真干员 → 全部。
        # 「优先本体」这一档是必须的：阿米娅有三个可玩形态，少了它，
        # `db char 阿米娅` 会直接报歧义，而大家想看的默认就是本体。
        exact = [r for r in found if r["char_id"] == key or r["name"] == key]
        chosen = None
        for cand in (exact, found):
            for pick in ([r for r in cand if r["is_operator"] and not r["is_patch"]],
                         [r for r in cand if r["is_operator"]]):
                if len(pick) == 1:
                    chosen = pick[0]
                    break
            if chosen is not None:
                break
            if len(cand) == 1:
                chosen = cand[0]
                break
        if chosen is None:
            names = ", ".join(f"{r['name']}({r['char_id']})" for r in found)
            raise DatabaseMissing(f"{key!r} 不唯一，可能是：{names}——请用 id 指定")
        row = conn.execute("SELECT * FROM operator WHERE char_id = ?",
                           (chosen["char_id"],)).fetchone()
    cid = row["char_id"]

    out: dict[str, Any] = {
        "char_id": cid,
        "name": row["name"],
        "appellation": row["appellation"],
        "rarity": row["rarity"],
        "profession": row["profession_cn"],
        "sub_profession": row["sub_profession_name"],
        "position": row["position"],
        "tags": json.loads(row["tag_list"] or "[]"),
        "trait": row["trait_text"],
        "is_operator": bool(row["is_operator"]),
        "phases": _rows(conn,
                        "SELECT phase, range_id, max_level FROM operator_phase "
                        "WHERE char_id=? ORDER BY phase", (cid,)),
        "attributes": _rows(conn,
                            "SELECT kind, phase, level, hp, atk, def, res, cost, "
                            "block_cnt, attack_speed, base_attack_time "
                            "FROM operator_attr WHERE char_id=? "
                            "ORDER BY kind, phase, level", (cid,)),
        "potential": _rows(conn,
                           "SELECT rank, type, description, modifiers "
                           "FROM operator_potential WHERE char_id=? "
                           "ORDER BY rank", (cid,)),
        "talents": _rows(conn,
                         "SELECT group_index, cand_index, name, description, "
                         "unlock_phase, unlock_level, required_potential_rank, "
                         "blackboard FROM operator_talent WHERE char_id=? "
                         "ORDER BY group_index, cand_index", (cid,)),
        "traits": _rows(conn,
                        "SELECT cand_index, unlock_phase, unlock_level, "
                        "override_description, blackboard FROM operator_trait "
                        "WHERE char_id=? ORDER BY cand_index", (cid,)),
        "skills": _rows(conn,
                        "SELECT s.slot, s.skill_id, s.unlock_phase, s.unlock_level, "
                        "k.name, k.level_count FROM operator_skill s "
                        "LEFT JOIN skill k ON k.skill_id = s.skill_id "
                        "WHERE s.char_id=? ORDER BY s.slot", (cid,)),
        "modules": _rows(conn,
                         "SELECT m.module_id, m.name, m.type, m.is_special_equip, "
                         "m.unlock_evolve_phase, m.unlock_level, "
                         "(SELECT COUNT(*) FROM module_level l "
                         " WHERE l.module_id=m.module_id) AS level_count "
                         "FROM module m WHERE m.char_id=? ORDER BY m.module_id",
                         (cid,)),
    }
    for t in out["talents"] + out["traits"] + out["potential"]:
        for k in ("blackboard", "modifiers"):
            if isinstance(t.get(k), str) and t[k]:
                try:
                    t[k] = json.loads(t[k])
                except ValueError:
                    pass
    return out


def skill_levels(conn: sqlite3.Connection, skill_id: str) -> list[dict]:
    """一个技能的十个等级。"""
    return _rows(conn,
                 "SELECT * FROM skill_level WHERE skill_id=? ORDER BY level",
                 (skill_id,))


def search_skills(conn: sqlite3.Connection, keyword: str, *,
                  limit: int = 30, blackboard_key: str = "") -> list[dict]:
    """按技能名/描述搜，或按黑板键搜（如 `atk_scale`、`sluggish`）。

    黑板键要**两种形态都试**：库里存的是原文，键名常带 `attack@` 前缀
    （`attack@atk_scale`），只匹配 `"atk_scale"` 会一条都搜不到。
    """
    where, params = ["1=1"], []
    if keyword:
        where.append("(name LIKE ? OR description LIKE ?)")
        params += [f"%{keyword}%"] * 2
    if blackboard_key:
        where.append('(blackboard LIKE ? OR blackboard LIKE ?)')
        params += [f'%"{blackboard_key}"%', f'%@{blackboard_key}"%']
    sql = (f"SELECT skill_id, level, name, skill_type, duration_type, sp_type, "
           f"sp_cost, init_sp, duration, range_id FROM skill_level "
           f"WHERE {' AND '.join(where)} AND level = 1 "
           f"ORDER BY skill_id LIMIT ?")
    params.append(limit)
    return _rows(conn, sql, params)


def search_talents(conn: sqlite3.Connection, keyword: str, *,
                   limit: int = 30, blackboard_key: str = "") -> list[dict]:
    """按天赋名/描述搜，或按黑板键搜。键名的 `attack@` 前缀同 `search_skills`。"""
    where, params = ["1=1"], []
    if keyword:
        # 必须写 t.：本查询 JOIN 了 operator，两张表都有 name，
        # 裸写 name 会撞 sqlite3.OperationalError: ambiguous column name。
        where.append("(t.name LIKE ? OR t.description LIKE ?)")
        params += [f"%{keyword}%"] * 2
    if blackboard_key:
        where.append("(blackboard LIKE ? OR blackboard LIKE ?)")
        params += [f'%"{blackboard_key}"%', f'%@{blackboard_key}"%']
    sql = (f"SELECT t.char_id, o.name AS operator, t.name, t.unlock_phase, "
           f"t.required_potential_rank, t.blackboard, t.description "
           f"FROM operator_talent t LEFT JOIN operator o ON o.char_id=t.char_id "
           f"WHERE {' AND '.join(where)} ORDER BY t.char_id LIMIT ?")
    params.append(limit)
    return _rows(conn, sql, params)


def run_sql(conn: sqlite3.Connection, query: str, *, limit: int = 200) -> list[dict]:
    """跑一条**只读** SQL。写语句一律拒绝——库是可重建的派生物，别绕过构建器。"""
    return run_readonly_sql(conn, query, limit=limit)
