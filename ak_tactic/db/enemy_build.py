"""把 prts.wiki 的敌人页灌进独立的敌人库 `data/enemydb.sqlite`。

    python -m ak_tactic enemy build      # 重建 data/enemydb.sqlite
    python -m ak_tactic enemy info       # 版本戳与行数
    python -m ak_tactic enemy show 源石虫 # 一个敌人的完整战斗数据

## 设计取舍

* **独立文件**：与干员库（`data/akdb.sqlite`）不共用文件、不共用结构版本、
  不互相引用。理由见 `enemy_schema.py` 顶部——来源不同、节奏不同、主键口径不同，
  连数值口径都是**相反**的（干员只存关键帧原文，敌人存算好继承的结果）。
* **继承在建库时算好**：PRTS 页面里没有"显式/继承"的标志位，只有"写了/没写"；
  模板靠 SMW `#ask` 向上一档取。本库把结果落进列，同时把**本档显式写出的参数**
  留在 `explicit_params`，把**被 HTML 注释掉的**留在 `hidden_params`。
* **原子落盘**：先写 `.part` 再 `os.replace`，构建中途炸掉不会毁掉手上的库。
* **可重复构建**：每次 `build` 都从零建表，不做增量。库是纯派生物。
* **抓不动就如实报错**：这个库**只有** PRTS 一个源，抓不到就是没有——
  不像干员库那样可以"少一半照样用"。所以失败直接抛，不产出空库。
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..prts.client import PrtsClient, PrtsError
from ..prts.enemy import PrtsEnemy, all_enemy_titles, fetch_enemy_pages, parse_page
from .enemy_schema import ENEMY_DB_VERSION, ENEMY_SCHEMA_SQL

__all__ = ["DEFAULT_ENEMY_DB_PATH", "ENEMY_SOURCE", "EnemyBuildReport",
           "build_enemy_db"]

#: 库文件。与干员库同级、同名不同文件，一眼分得开。
DEFAULT_ENEMY_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "enemydb.sqlite"

#: 唯一的来源
ENEMY_SOURCE = "prts.wiki 分类:敌人"


def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


@dataclass
class EnemyBuildReport:
    path: Path
    counts: dict[str, int] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"库文件：{self.path}", f"耗时：{self.seconds:.1f}s"]
        lines += [f"  {k} = {v}" for k, v in self.meta.items()]
        width = max((len(k) for k in self.counts), default=0)
        for k, v in self.counts.items():
            lines.append(f"  {k.ljust(width)} {v:>8,} 行")
        lines += [f"  警告：{w}" for w in self.warnings]
        return "\n".join(lines)


def _insert(conn: sqlite3.Connection, e: PrtsEnemy) -> None:
    """一个敌人的图鉴 + 全部档位 + 抗性 + 技能。"""
    conn.execute(
        """INSERT OR REPLACE INTO enemy
           (page, prts_id, name, display_name, index_code, grade, category,
            damage_type, attack_way, move_way, camp, ability,
            ability_fixed, ability_errata, debut_event, is_irregular,
            has_handbook, level_count, raw_wikitext)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (e.page, e.prts_id, e.name, e.display_name, e.index_code, e.grade,
         e.category, e.damage_type, e.attack_way, e.move_way, e.camp,
         e.ability, e.ability_fixed, e.ability_errata_raw,
         e.debut_event,
         int(e.is_irregular), int(e.has_handbook), len(e.levels),
         e.raw_wikitext),
    )

    for lv in e.levels:
        n = lv.numbers()
        sp = lv.sp_slot()
        conn.execute(
            """INSERT OR REPLACE INTO enemy_level
               (page, level, name, grade, category, description,
                description_fixed, attack_way,
                move_way, target_value, range_radius, hp, atk, defense, res,
                move_speed, attack_speed, base_attack_time, hp_recovery,
                sp_recovery, weight, damage_resistance, element_resistance,
                taunt_level, talent, init_sp, max_sp, sp_recovery_type,
                sp_recovery_value, params, explicit_params, hidden_params,
                blackboard, blackboard_raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,
                       ?,?,?,?,?,?)""",
            (e.page, lv.index, lv.name, lv.grade, lv.category, lv.description,
             lv.description_fixed, lv.attack_way, lv.move_way,
             n["target_value"], n["range_radius"], n["hp"], n["atk"],
             n["defense"], n["res"], n["move_speed"], n["attack_speed"],
             n["base_attack_time"], n["hp_recovery"], n["sp_recovery"],
             n["weight"], n["damage_resistance"], n["element_resistance"],
             n["taunt_level"], lv.talent,
             sp["init_sp"], sp["max_sp"], sp["sp_recovery_type"],
             sp["sp_recovery_value"],
             _json(lv.params), _json(lv.explicit), _json(lv.hidden),
             _json(lv.blackboard), _json(lv.blackboard_raw)),
        )
        # 抗性两条来源：`覆写` 压过同名的 `字段`。两条都落库（不丢数据），
        # 由 is_effective 标明谁说了算。
        rows = lv.resists()
        overridden = {rn for rn, _rv, _im, src in rows if src == "覆写"}
        for rname, rvalue, immune, source in rows:
            effective = not (source == "字段" and rname in overridden)
            conn.execute(
                """INSERT OR REPLACE INTO enemy_resist
                   (page, level, name, value, is_immune, source, is_effective)
                   VALUES (?,?,?,?,?,?,?)""",
                (e.page, lv.index, rname, rvalue, int(immune), source,
                 int(effective)),
            )
        for s in lv.skills():
            conn.execute(
                """INSERT OR REPLACE INTO enemy_skill
                   (page, level, slot, name, init_cooldown, cooldown, sp_cost,
                    kind, effect)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (e.page, lv.index, s["slot"], s["name"], s["init_cooldown"],
                 s["cooldown"], s["sp_cost"], s["kind"], s["effect"]),
            )


def build_enemy_db(path: Path | str | None = None, *,
                   client: PrtsClient | None = None,
                   verbose: bool = False,
                   limit: int | None = None) -> EnemyBuildReport:
    """从 prts.wiki 重建敌人库，返回构建报告。

    :param path: 库文件路径，默认 `data/enemydb.sqlite`
    :param client: PRTS 客户端（默认新建一个，走 `data/cache/prts/` 缓存）
    :param limit: 只抓前 N 页，供试跑用；正式建库不要给
    """
    target = Path(path) if path else DEFAULT_ENEMY_DB_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    started = time.time()
    report = EnemyBuildReport(path=target)

    def note(msg: str) -> None:
        if verbose:
            print(f"    {msg}")

    c = client or PrtsClient()

    note("取分类成员……")
    titles = all_enemy_titles(c)
    if limit is not None:
        titles = titles[:limit]

    def step(done: int, total: int) -> None:
        if verbose and done % 500 < 50:
            note(f"已抓 {done}/{total}")

    note(f"批量抓取 {len(titles)} 页……")
    pages = fetch_enemy_pages(titles, c, progress=step)

    failed: list[str] = []
    counts = {"enemy": 0, "enemy_level": 0, "enemy_resist": 0, "enemy_skill": 0}

    if part.exists():
        part.unlink()
    conn = sqlite3.connect(part)
    try:
        conn.executescript(ENEMY_SCHEMA_SQL)
        note("解析并入库……")
        for title in titles:
            text = pages.get(title)
            if text is None:                 # 分类里有、批量抓取却没回来的
                failed.append(title)
                continue
            try:
                e = parse_page(title, text)
            except Exception as exc:         # 单页解析炸掉不该带倒整次建库
                failed.append(f"{title}（{type(exc).__name__}: {exc}）")
                continue
            _insert(conn, e)
            counts["enemy"] += 1
            counts["enemy_level"] += len(e.levels)
            counts["enemy_resist"] += sum(len(lv.resists()) for lv in e.levels)
            counts["enemy_skill"] += sum(len(lv.skills()) for lv in e.levels)

        meta = {
            "db_version": str(ENEMY_DB_VERSION),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "enemy_source": ENEMY_SOURCE,
            "schema_note": "只含战斗相关数据；见 ak_tactic/db/enemy_schema.py 顶部说明",
        }
        conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                         list(meta.items()))
        conn.commit()
    except Exception:
        conn.close()
        if part.exists():
            part.unlink()
        raise
    conn.close()

    os.replace(part, target)
    report.counts = counts
    report.meta = meta
    report.seconds = time.time() - started
    if failed:
        report.warnings.append(f"{len(failed)} 个敌人页抓取/解析失败："
                               + "、".join(str(f) for f in failed[:5]) + " 等")
    return report
