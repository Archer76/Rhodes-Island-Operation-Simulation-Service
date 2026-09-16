"""把 gamedata 的 6 张战斗表灌进干员库 `data/akdb.sqlite`。

    python -m ak_tactic db build          # 重建 data/akdb.sqlite
    python -m ak_tactic db info           # 看库里的版本戳与条数
    python -m ak_tactic db char 阿米娅     # 一个干员的完整战斗数据

敌人不在这里：那是**另一个文件** `data/enemydb.sqlite`，走
`python -m ak_tactic enemy build`（见 `enemy_build.py`）。

## 设计取舍

* **只搬不推**：库存的是**原文**（关键帧、黑板、模组改写），不是算好的面板——
  属性插值、信赖与潜能的叠加、模组三道门，全部仍由 `ak_tactic.operator`
  那套负责，两处各算一遍必然有一天对不上。
* **原子落盘**：先写到 `.part` 再 `os.replace`，构建中途炸掉不会毁掉手上的库。
* **可重复构建**：每次 `build` 都从零建表，不做增量。库是纯派生物，删了重建
  比修它便宜。
* **不需要联网**：源表已缓存在 `data/gamedata/` 下。
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..gamedata.source import GITHUB_BASE, GameDataSource, GamedataError
from .schema import DB_VERSION, SCHEMA_SQL
from .tiles import KNOWN_GAPS, fetch_tile_info, insert_tiles

__all__ = ["DEFAULT_DB_PATH", "BuildReport", "build_db", "DEFAULT_SOURCE"]

#: 库文件位置（与 gamedata 缓存同级，已随 data/ 一起 gitignore）
DEFAULT_DB_PATH = Path(__file__).resolve().parents[2] / "data" / "akdb.sqlite"

#: excel/ 只有 GitHub 镜像提供，ark-nights 不带这个目录
DEFAULT_SOURCE = GITHUB_BASE

#: character_table 的职业英文枚举 → 面板上的中文（与 cli.py 里那份同源）
PROFESSION_CN = {
    "PIONEER": "先锋", "WARRIOR": "近卫", "TANK": "重装", "SNIPER": "狙击",
    "CASTER": "术师", "MEDIC": "医疗", "SUPPORT": "辅助", "SPECIAL": "特种",
    "TOKEN": "召唤物", "TRAP": "装置",
}

#: 这些职业不是"干员"（召唤物与装置），但仍然入库——它们也有战斗数值
NON_OPERATOR_PROFESSIONS = ("TOKEN", "TRAP")

#: **生息演算整体剔除**：该模式的装置与战斗建模无关，留着只会污染语料与统计。
#: 判据取自游戏本体——`excel/sandbox_table.json` 与 `excel/sandbox_perm_table.json`
#: 列出了这个模式引用的**全部**装置 id，不是按 id 前缀猜的：按前缀猜既会漏掉
#: `trap_413_hiddenstone`、`trap_466_tzumama` 这类没有 xb 标记的（第一季的
#: NPC 与道具），也会误伤名字里恰好出现 wf/ac 的 `trap_403_wfactory`。
SANDBOX_TABLES = ("excel/sandbox_table.json", "excel/sandbox_perm_table.json")

#: 沙盒表**也**引用了这批低编号的通用战场装置（干扰地雷、便携式补给站、
#: 轰隆隆先生…）。它们不是为生息演算做的，主线与活动关同样在用，删掉会伤到
#: 非生息演算的数据，因此保留——剔除只针对为那个模式而生的装置。
SHARED_BATTLE_TRAPS = frozenset({
    "trap_009_battery", "trap_012_mine", "trap_018_bomb", "trap_019_electric",
    "trap_031_sleep", "trap_033_sbomb", "trap_040_canoe", "trap_052_slowfd",
    "trap_053_airbomb", "trap_084_aidkit",
})

_DEVICE_ID_RE = re.compile(r"^(?:trap|token)_\d+_[A-Za-z0-9_]+$")

#: 属性字段 → 表里的列名。没列进来的（各种免疫位）落进 extra_json。
_ATTR_COLUMNS: dict[str, str] = {
    "maxHp": "hp",
    "atk": "atk",
    "def": "def",
    "magicResistance": "res",
    "cost": "cost",
    "blockCnt": "block_cnt",
    "attackSpeed": "attack_speed",
    "baseAttackTime": "base_attack_time",
    "moveSpeed": "move_speed",
    "respawnTime": "respawn_time",
    "hpRecoveryPerSec": "hp_recovery",
    "spRecoveryPerSec": "sp_recovery",
    "tauntLevel": "taunt_level",
    "massLevel": "mass_level",
    "baseForceLevel": "base_force_level",
    "maxDeployCount": "max_deploy_count",
    "maxDeckStackCnt": "max_deck_stack",
}


@dataclass
class BuildReport:
    """一次构建的结果。`counts` 是各表的行数，`meta` 是写进去的版本戳。"""

    path: Path
    counts: dict[str, int] = field(default_factory=dict)
    meta: dict[str, str] = field(default_factory=dict)
    seconds: float = 0.0
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> str:
        lines = [f"库文件：{self.path}",
                 f"耗时：{self.seconds:.1f}s"]
        for k, v in self.meta.items():
            lines.append(f"  {k} = {v}")
        for k, v in self.counts.items():
            lines.append(f"  {k:<18} {v:>7,} 行")
        for w in self.warnings:
            # 用「警告：」而不是 ⚠：Windows 控制台是 GBK，编不出的字符会让
            # 打印这一步抛 UnicodeEncodeError —— 库其实已经建好了，命令却
            # 以非零退出，看起来像失败。
            lines.append(f"  警告：{w}")
        return "\n".join(lines)


# ------------------------------------------------------------------ 小工具

def _json(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True)


def _phase_index(value: Any) -> int:
    """`PHASE_2` → 2。取不到就给 -1（宁可显眼，别静默变成 0）。"""
    if isinstance(value, int):
        return value
    if not value:
        return -1
    tail = str(value).rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else -1


def _rarity(value: Any) -> int:
    tail = str(value or "").rsplit("_", 1)[-1]
    return int(tail) if tail.isdigit() else 0


def _collect_device_ids(node: Any, into: set[str]) -> None:
    """把 JSON 里出现的装置 id 收进来。**键与值都要看**——沙盒表两处都用：
    有的是值，有的是字典键（`trap_475_xbcbag_1` 这类变体以键的形式出现）。"""
    if isinstance(node, str):
        if _DEVICE_ID_RE.match(node):
            into.add(node)
    elif isinstance(node, dict):
        for k, v in node.items():
            if _DEVICE_ID_RE.match(str(k)):
                into.add(str(k))
            _collect_device_ids(v, into)
    elif isinstance(node, list):
        for v in node:
            _collect_device_ids(v, into)


def sandbox_device_ids(src: GameDataSource) -> tuple[set[str], list[str]]:
    """生息演算专属装置的 id（已减去与主线共用的那批）。返回 `(id 集合, 警告)`。

    取不到表时返回**空集而不是抛错**：剔除是清理动作，不该因为一张表拉不下来
    就让整个建库失败；但会记一条警告，免得静默地什么都没剔。
    """
    ids: set[str] = set()
    warnings: list[str] = []
    for name in SANDBOX_TABLES:
        try:
            _collect_device_ids(src.fetch_json(name), ids)
        except GamedataError as exc:
            warnings.append(f"{name} 取不到，生息演算装置可能未剔净：{exc}")
    return ids - SHARED_BATTLE_TRAPS, warnings


def ra_dropped_skills(chars: dict[str, dict], excluded: set[str]) -> set[str]:
    """**只被剔除装置引用**的技能 id（建库与校验两侧共用同一份判据）。"""
    ra: set[str] = set()
    others: set[str] = set()
    for cid, char in chars.items():
        target = ra if cid in excluded else others
        for entry in char.get("skills") or []:
            if entry.get("skillId"):
                target.add(entry["skillId"])
    return ra - others


def _blackboard(pairs: Any) -> tuple[str, str]:
    """黑板列表 → (方便查询的 {key: 数值}, 原文 JSON)。

    值可能是数字也可能只有 `valueStr`（文本型参数）；数字型进字典，
    文本型的也放进去（值取字符串），原文另存一份以防日后要还原。
    """
    flat: dict[str, Any] = {}
    for item in pairs or []:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        if key is None:
            continue
        val = item.get("value")
        flat[key] = val if val is not None else item.get("valueStr")
    return _json(flat), _json(pairs or [])


# ------------------------------------------------------------------ 构建

def _insert_operator(conn: sqlite3.Connection, char_id: str, char: dict,
                     sub_prof: dict, *, is_patch: bool = False) -> bool:
    prof = char.get("profession") or ""
    sub_id = char.get("subProfessionId") or ""
    is_op = prof not in NON_OPERATOR_PROFESSIONS
    conn.execute(
        """INSERT INTO operator (char_id, name, appellation, rarity, rarity_str,
                profession, profession_cn, sub_profession_id, sub_profession_name,
                position, tag_list, trait_text, nation_id, group_id, team_id,
                display_number, sort_index, is_not_obtainable, is_sp_char,
                max_potential_level, is_operator, is_patch, raw_json)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (
            char_id,
            char.get("name") or char_id,
            char.get("appellation"),
            _rarity(char.get("rarity")),
            char.get("rarity"),
            prof,
            PROFESSION_CN.get(prof, prof),
            sub_id,
            (sub_prof.get(sub_id) or {}).get("subProfessionName"),
            char.get("position"),
            _json(char.get("tagList") or []),
            char.get("description"),
            char.get("nationId"),
            char.get("groupId"),
            char.get("teamId"),
            char.get("displayNumber"),
            char.get("sortIndex"),
            int(bool(char.get("isNotObtainable"))),
            int(bool(char.get("isSpChar"))),
            char.get("maxPotentialLevel"),
            int(is_op),
            int(is_patch),
            _json(char),
        ),
    )
    return is_op


def _insert_attrs(conn: sqlite3.Connection, char_id: str, kind: str, phase: int,
                  level: int, data: dict) -> None:
    cols = ["char_id", "kind", "phase", "level"] + list(_ATTR_COLUMNS.values())
    extra = {k: v for k, v in data.items() if k not in _ATTR_COLUMNS}
    values: list[Any] = [char_id, kind, phase, level]
    values += [data.get(k) for k in _ATTR_COLUMNS]
    values.append(_json(extra))
    cols.append("extra_json")
    conn.execute(
        f"INSERT OR REPLACE INTO operator_attr ({','.join(cols)}) "
        f"VALUES ({','.join('?' * len(cols))})",
        values,
    )


def build_db(path: Path | str | None = None, *,
             source: GameDataSource | None = None,
             verbose: bool = False) -> BuildReport:
    """重建干员库，返回构建报告。

    :param path: 库文件路径，默认 `data/akdb.sqlite`
    :param source: 取数源；默认 GitHub 镜像（`excel/` 只有它有）
    """
    from ..gamedata.range import RangeTable

    t0 = time.time()
    target = Path(path) if path else DEFAULT_DB_PATH
    src = source or GameDataSource(base=DEFAULT_SOURCE)
    report = BuildReport(path=target)

    def note(msg: str) -> None:
        if verbose:
            print(f"    {msg}")

    note("取表……")
    chars = src.fetch_json("excel/character_table.json")
    skills = src.fetch_json("excel/skill_table.json")
    uniequip = src.fetch_json("excel/uniequip_table.json")
    battle_equip = src.fetch_json("excel/battle_equip_table.json")
    # 升变形态（阿米娅的近卫/医疗）单独在 char_patch_table.json 里，结构与
    # 干员本体一致，**但不在 character_table 里**——只灌前者会少 2 个可玩形态
    # （森空岛名册里就有 char_1001_amiya2，是名册交叉校验把它揪出来的）。
    patch_chars = src.fetch_json("excel/char_patch_table.json").get("patchChars") or {}
    all_chars = [(cid, c, False) for cid, c in chars.items()]
    all_chars += [(cid, c, True) for cid, c in patch_chars.items()]
    # 生息演算的装置整体不入库（判据见 SANDBOX_TABLES）。与主线共用的那批装置
    # 已被 sandbox_device_ids 减掉，不在此列。
    excluded, ra_warnings = sandbox_device_ids(src)
    report.warnings.extend(ra_warnings)
    excluded &= {cid for cid, _, _ in all_chars}
    dropped_skills = ra_dropped_skills({cid: c for cid, c, _ in all_chars}, excluded)
    range_table = RangeTable(source=src)
    try:
        data_version = src.fetch_text("excel/data_version.txt").strip()
    except GamedataError as exc:                      # 版本戳取不到不该挡住建库
        data_version = "(取不到)"
        report.warnings.append(f"data_version.txt 取不到：{exc}")

    sub_prof = uniequip.get("subProfDict") or {}

    target.parent.mkdir(parents=True, exist_ok=True)
    part = target.with_suffix(target.suffix + ".part")
    if part.exists():
        part.unlink()
    conn = sqlite3.connect(part)
    try:
        conn.executescript(SCHEMA_SQL)

        # ---- 1. 干员本体 + 阶段 + 属性 + 潜能 + 天赋 + 特性 + 技能引用
        note("灌干员……")
        operators = 0
        skipped_ra: list[str] = []
        null_skill_slots: list[str] = []
        for char_id, char, is_patch in all_chars:
            if char_id in excluded:               # 生息演算装置：连同它的所有子表一起跳过
                skipped_ra.append(char_id)
                continue
            if _insert_operator(conn, char_id, char, sub_prof, is_patch=is_patch):
                operators += 1

            for phase_i, ph in enumerate(char.get("phases") or []):
                conn.execute(
                    """INSERT OR REPLACE INTO operator_phase
                       (char_id, phase, range_id, max_level, prefab_key)
                       VALUES (?,?,?,?,?)""",
                    (char_id, phase_i, ph.get("rangeId"), ph.get("maxLevel"),
                     ph.get("characterPrefabKey")),
                )
                for frame in ph.get("attributesKeyFrames") or []:
                    _insert_attrs(conn, char_id, "phase", phase_i,
                                  int(frame.get("level") or 0),
                                  frame.get("data") or {})

            for frame in char.get("favorKeyFrames") or []:
                _insert_attrs(conn, char_id, "trust", -1,
                              int(frame.get("level") or 0),
                              frame.get("data") or {})

            for rank, pot in enumerate(char.get("potentialRanks") or []):
                mods = (((pot.get("buff") or {}).get("attributes") or {})
                        .get("attributeModifiers") or [])
                conn.execute(
                    """INSERT OR REPLACE INTO operator_potential
                       (char_id, rank, type, description, modifiers)
                       VALUES (?,?,?,?,?)""",
                    (char_id, rank, pot.get("type"), pot.get("description"),
                     _json(mods)),
                )

            for gi, group in enumerate(char.get("talents") or []):
                for ci, cand in enumerate(group.get("candidates") or []):
                    cond = cand.get("unlockCondition") or {}
                    bb, bb_raw = _blackboard(cand.get("blackboard"))
                    conn.execute(
                        """INSERT OR REPLACE INTO operator_talent
                           (char_id, group_index, cand_index, prefab_key, name,
                            description, unlock_phase, unlock_level,
                            required_potential_rank, range_id, is_hide_talent,
                            token_key, blackboard, blackboard_raw)
                           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (char_id, gi, ci, cand.get("prefabKey"), cand.get("name"),
                         cand.get("description"), _phase_index(cond.get("phase")),
                         cond.get("level"), cand.get("requiredPotentialRank"),
                         cand.get("rangeId"), int(bool(cand.get("isHideTalent"))),
                         cand.get("tokenKey"), bb, bb_raw),
                    )

            trait = char.get("trait") or {}
            for ci, cand in enumerate(trait.get("candidates") or []):
                cond = cand.get("unlockCondition") or {}
                bb, _ = _blackboard(cand.get("blackboard"))
                conn.execute(
                    """INSERT OR REPLACE INTO operator_trait
                       (char_id, cand_index, unlock_phase, unlock_level,
                        required_potential_rank, override_description,
                        prefab_key, range_id, blackboard)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (char_id, ci, _phase_index(cond.get("phase")), cond.get("level"),
                     cand.get("requiredPotentialRank"),
                     cand.get("overrideDescripton") or cand.get("overrideDescription"),
                     cand.get("prefabKey"), cand.get("rangeId"), bb),
                )

            for slot, entry in enumerate(char.get("skills") or [], start=1):
                # 有些条目（占位/召唤物）的 skillId 是 null——跳过，别写空主键
                if not entry.get("skillId"):
                    null_skill_slots.append(f"{char_id}·槽{slot}")
                    continue
                cond = entry.get("unlockCond") or {}
                conn.execute(
                    """INSERT OR REPLACE INTO operator_skill
                       (char_id, slot, skill_id, unlock_phase, unlock_level,
                        override_prefab_key, override_token_key)
                       VALUES (?,?,?,?,?,?,?)""",
                    (char_id, slot, entry.get("skillId"),
                     _phase_index(cond.get("phase")), cond.get("level"),
                     entry.get("overridePrefabKey"), entry.get("overrideTokenKey")),
                )

        # 一条汇总就够：这些全是召唤物/装置的占位槽位，逐条列会把输出淹掉
        if null_skill_slots:
            report.warnings.append(
                f"{len(null_skill_slots)} 个技能槽位的 skillId 为空"
                f"（全是召唤物/装置的占位，已跳过）："
                + "、".join(null_skill_slots[:3]) + " 等")
        if skipped_ra:
            report.warnings.append(
                f"剔除生息演算装置 {len(skipped_ra)} 个"
                f"（如 {skipped_ra[0]}），及其**专属**技能 {len(dropped_skills)} 条；"
                f"该模式与主线共用的 {len(SHARED_BATTLE_TRAPS)} 个通用装置已保留")

        # ---- 2. 技能表
        note("灌技能……")
        skill_levels = 0
        for skill_id, sk in skills.items():
            if skill_id in dropped_skills:        # 只服务被剔除装置的技能，一并去掉
                continue
            levels = sk.get("levels") or []
            first = levels[0] if levels else {}
            conn.execute(
                """INSERT OR REPLACE INTO skill
                   (skill_id, name, icon_id, hidden, level_count, prefab_id)
                   VALUES (?,?,?,?,?,?)""",
                (skill_id, first.get("name"), sk.get("iconId"),
                 int(bool(sk.get("hidden"))), len(levels), first.get("prefabId")),
            )
            for li, lv in enumerate(levels, start=1):
                sp = lv.get("spData") or {}
                bb, bb_raw = _blackboard(lv.get("blackboard"))
                conn.execute(
                    """INSERT OR REPLACE INTO skill_level
                       (skill_id, level, name, description, skill_type,
                        duration_type, sp_type, sp_cost, init_sp, increment,
                        max_charge_time, duration, range_id, prefab_id,
                        blackboard, blackboard_raw)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (skill_id, li, lv.get("name"), lv.get("description"),
                     lv.get("skillType"), lv.get("durationType"),
                     sp.get("spType"), sp.get("spCost"), sp.get("initSp"),
                     sp.get("increment"), sp.get("maxChargeTime"),
                     lv.get("duration"), lv.get("rangeId"), lv.get("prefabId"),
                     bb, bb_raw),
                )
                skill_levels += 1

        # ---- 3. 模组
        note("灌模组……")
        equip_dict = uniequip.get("equipDict") or {}
        char_equip = uniequip.get("charEquip") or {}
        # 模组归属以 **charEquip** 为准：它按形态分别列，而 equipDict.charId
        # 对升变形态的模组一律指回原形态（uniequip_002_amiya2 的 charId 是
        # char_002_amiya），照它写会把「阿米娅(近卫)」的模组挂到本体名下。
        # 这与 OperatorCalculator.modules() 的口径一致。
        owner = {mid: cid for cid, mids in char_equip.items() for mid in mids}
        module_levels = 0
        for mid, eq in equip_dict.items():
            phases = (battle_equip.get(mid) or {}).get("phases") or []
            conn.execute(
                """INSERT OR REPLACE INTO module
                   (module_id, char_id, name, type, type_name1, type_name2,
                    is_special_equip, special_equip_desc, unlock_evolve_phase,
                    unlock_level, show_evolve_phase, show_level,
                    has_unlock_mission, mission_count)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (mid, owner.get(mid) or eq.get("charId"), eq.get("uniEquipName"),
                 eq.get("type"),
                 eq.get("typeName1"), eq.get("typeName2"),
                 int(bool(eq.get("isSpecialEquip"))), eq.get("specialEquipDesc"),
                 _phase_index(eq.get("unlockEvolvePhase")), eq.get("unlockLevel"),
                 _phase_index(eq.get("showEvolvePhase")), eq.get("showLevel"),
                 int(bool(eq.get("hasUnlockMission"))),
                 len(eq.get("missionList") or []) or 0),
            )
            for ph in phases:
                conn.execute(
                    """INSERT OR REPLACE INTO module_level
                       (module_id, level, attribute_blackboard, token_blackboard,
                        parts)
                       VALUES (?,?,?,?,?)""",
                    (mid, ph.get("equipLevel") or len(phases),
                     _json(ph.get("attributeBlackboard") or []),
                     _json(ph.get("tokenAttributeBlackboard") or {}),
                     _json(ph.get("parts") or [])),
                )
                module_levels += 1

        # ---- 4. 攻击范围
        note("灌范围……")
        range_raw = src.fetch_json("excel/range_table.json")
        range_count = 0
        for rid, entry in (range_raw or {}).items():
            try:
                cells = sorted([x, y] for x, y in range_table.cells(rid))
            except GamedataError:
                cells = []
                report.warnings.append(f"范围 {rid} 解析不出格集合")
            grids = entry.get("grids") or []
            conn.execute(
                """INSERT OR REPLACE INTO attack_range
                   (range_id, direction, grid_count, grids, cells)
                   VALUES (?,?,?,?,?)""",
                (rid, entry.get("direction"), len(grids), _json(grids),
                 _json(cells)),
            )
            range_count += 1

        # ---- 5. 地块字典（唯一非 gamedata 来源的表；取不到只记警告）
        # 见 db/tiles.py：gamedata 根本没有地块表，这份来自 theresa.wiki。
        # **取不到不该挡住建库**——其余五张表跟它没有依赖关系。
        tile_count = 0
        try:
            tiles = fetch_tile_info()
            tile_count = insert_tiles(conn, tiles)
            note(f"地块字典 {tile_count} 条")
        except Exception as exc:                  # noqa: BLE001 —— 网络问题一律降级
            report.warnings.append(f"地块字典取不到（tile 表留空）：{exc}")

        # ---- 6. 版本戳
        build_meta = {
            "db_version": str(DB_VERSION),
            "built_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "data_version": data_version,
            "source": src.base,
            "tables": "character_table + char_patch_table + skill_table + "
                      "uniequip_table + battle_equip_table + range_table"
                      "（生息演算装置按其 sandbox 表剔除）"
                      "+ tile（地块字典，**非 gamedata 来源**，取自 theresa.wiki）",
            "schema_note": "只含战斗相关数据；见 ak_tactic/db/schema.py 顶部说明。"
                           "敌人另有一库 data/enemydb.sqlite",
            "tile_source": "theresa.wiki 地图数据接口（gamedata 无地块表）；"
                           f"已知缺口 {'/'.join(KNOWN_GAPS)}",
        }
        conn.executemany("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)",
                         list(build_meta.items()))
        conn.commit()

        report.counts = {
            "operator": conn.execute("SELECT COUNT(*) FROM operator").fetchone()[0],
            "（其中真干员）": conn.execute(
                "SELECT COUNT(*) FROM operator WHERE is_operator=1").fetchone()[0],
            "（其中升变形态）": conn.execute(
                "SELECT COUNT(*) FROM operator WHERE is_patch=1").fetchone()[0],
            "operator_phase": conn.execute(
                "SELECT COUNT(*) FROM operator_phase").fetchone()[0],
            "operator_attr": conn.execute(
                "SELECT COUNT(*) FROM operator_attr").fetchone()[0],
            "operator_potential": conn.execute(
                "SELECT COUNT(*) FROM operator_potential").fetchone()[0],
            "operator_talent": conn.execute(
                "SELECT COUNT(*) FROM operator_talent").fetchone()[0],
            "operator_trait": conn.execute(
                "SELECT COUNT(*) FROM operator_trait").fetchone()[0],
            "operator_skill": conn.execute(
                "SELECT COUNT(*) FROM operator_skill").fetchone()[0],
            "skill": conn.execute("SELECT COUNT(*) FROM skill").fetchone()[0],
            "skill_level": skill_levels,
            "module": conn.execute("SELECT COUNT(*) FROM module").fetchone()[0],
            "module_level": module_levels,
            "attack_range": range_count,
            "tile": tile_count,
        }
        report.meta = build_meta
        assert operators, "一个真干员都没灌进去，说明表结构变了"
    finally:
        conn.close()

    if target.exists():
        target.unlink()
    os.replace(part, target)
    report.path = target
    report.seconds = time.time() - t0
    return report
