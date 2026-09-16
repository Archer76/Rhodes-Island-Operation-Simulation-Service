"""敌人库（`data/enemydb.sqlite`）的完整性与一致性检查。

    python tools/check_enemy_db.py

分五类：

1. **出处与自洽**——结构版本、来源、行数、`level_count` 与逐档行数、孤儿行；
2. **覆盖**——有图鉴的比例、每档都有生命值、黑板与天赋文本的档位数；
3. **跨源对账**——库是从 **PRTS 页面**解析来的，对账用的是**游戏本体**的
   `enemy_database.json`（`EnemyLibrary`）。两个独立来源逐项比
   生命/攻击/防御/法抗/重量与档数；
4. **解析口径守卫**——注释掉的参数、档位继承、技能冷却语义、形态相性、
   免疫项数，每一条都对应一个真踩过的坑；
5. **查询入口冒烟**——`find_enemies` / `enemy_detail` 各真跑一次，
   防"检查全绿但命令崩溃"。

干员库是**另一个文件**，自检在 `tools/check_db.py`。

第 3 类是整个文件里最有价值的一项：PRTS 与 gamedata 同源，所以两边一起错的
概率远低于解析器单独错的概率。
"""

from __future__ import annotations

import json
import re
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.db import (                                          # noqa: E402
    DEFAULT_ENEMY_DB_PATH, ENEMY_DB_VERSION, connect_enemy, enemy_db_info,
    enemy_detail, find_enemies,
)
from ak_tactic.gamedata import EnemyLibrary                         # noqa: E402
from ak_tactic.gamedata.source import GameDataSource                # noqa: E402

_PASSED = 0
_FAILED: list[str] = []

#: 跨源锚点：SR-EX-8 的 8 个敌人 + 源石虫。项目已用**游戏本体**（gamedata 的
#: `enemy_database.json`）单独核过它们，而本库是从 **PRTS 页面**解析来的。
#: 两个独立来源对得上，才算真对上了——只比"库和解析器一起错"抓得住。
CROSS_ENEMY_IDS = (
    "enemy_1007_slime",
    "enemy_10184_pppsbr_2", "enemy_10185_pppshd_2", "enemy_10186_ppparc_2",
    "enemy_10188_pppdp_2", "enemy_10189_pppmag_2", "enemy_10191_pppgst",
    "enemy_10192_ppprpr", "enemy_1589_pppdth",
)

#: BOSS 页名。它同时是"注释里的参数"与"形态黑板"两个坑的载体，单独钉死。
BOSS_PAGE = "“死志的凝结”"

_QUOTE_RE = re.compile(r"[“”\"「」『』\s·・]")


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}   {detail}")


def close(a, b, tol: float = 1e-6) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _count(conn: sqlite3.Connection, sql: str, params=()) -> int:
    return conn.execute(sql, params).fetchone()[0]


def _norm_name(s: str) -> str:
    """比名字时把引号与空白抹掉——gamedata 叫「死志的凝结」，
    PRTS 页名是「“死志的凝结”」，不抹就永远对不上。"""
    return _QUOTE_RE.sub("", s or "")


# ------------------------------------------------------ 1 出处与自洽

def check_selfconsistency(conn: sqlite3.Connection) -> dict:
    print("\n[1] 出处与自洽")
    info = enemy_db_info(conn)
    meta = info["meta"]
    counts = info["counts"]

    check(f"结构版本 = {ENEMY_DB_VERSION}", info["version_ok"],
          f"库里是 {meta.get('db_version')}")
    check("来源标注为 prts.wiki", "prts.wiki" in (meta.get("enemy_source") or ""),
          meta.get("enemy_source") or "空")
    check("built_at 有值", bool(meta.get("built_at")))

    n_enemy = counts.get("enemy", 0)
    n_level = counts.get("enemy_level", 0)
    check("敌人条数 > 1500", n_enemy > 1500, f"实得 {n_enemy}")

    summed = _count(conn, "SELECT COALESCE(SUM(level_count), 0) FROM enemy")
    check("level_count 之和 = enemy_level 行数", summed == n_level,
          f"{summed} vs {n_level}")
    check("没有「有图鉴却一档都没有」的敌人",
          _count(conn, """SELECT COUNT(*) FROM enemy
                          WHERE level_count = 0 AND has_handbook = 1""") == 0)
    for table in ("enemy_level", "enemy_resist", "enemy_skill"):
        orphan = _count(conn, f"""SELECT COUNT(*) FROM {table} t
                                  LEFT JOIN enemy e ON e.page = t.page
                                  WHERE e.page IS NULL""")
        check(f"{table} 的 page 都在 enemy 里", orphan == 0, f"孤儿 {orphan} 行")
    return counts


# ---------------------------------------------------------------- 2 覆盖

def check_coverage(conn: sqlite3.Connection, counts: dict) -> None:
    print("\n[2] 覆盖")
    n_enemy = counts["enemy"]
    with_hb = _count(conn, "SELECT COUNT(*) FROM enemy WHERE has_handbook = 1")
    check("有图鉴（有编号）的敌人 ≥ 90%", with_hb >= n_enemy * 0.9,
          f"{with_hb}/{n_enemy} = {with_hb / n_enemy:.1%}")
    no_hp = _count(conn, "SELECT COUNT(*) FROM enemy_level WHERE hp IS NULL")
    check("每一档都有生命值", no_hp == 0, f"缺 {no_hp} 档")
    with_bb = _count(conn, """SELECT COUNT(*) FROM enemy_level
                              WHERE blackboard IS NOT NULL
                                AND blackboard NOT IN ('{}')""")
    check("带黑板的档位 > 500（P3R 相性/倒地阈值/重生参数的来源）",
          with_bb > 500, f"实得 {with_bb}")
    with_talent = _count(conn, "SELECT COUNT(*) FROM enemy_level "
                               "WHERE talent IS NOT NULL")
    check("有天赋文本的档位 > 1000", with_talent > 1000, f"实得 {with_talent}")


# ------------------------------------------------------------ 3 跨源对账

def check_cross_source(conn: sqlite3.Connection, src: GameDataSource) -> None:
    print("\n[3] 跨源对账：PRTS 解析 vs 游戏本体 enemy_database")
    lib = EnemyLibrary(source=src)
    by_name: dict[str, str] = {}
    for row in conn.execute("SELECT page, name FROM enemy"):
        by_name.setdefault(_norm_name(row["name"]), row["page"])

    hit = 0
    for eid in CROSS_ENEMY_IDS:
        st = lib.get(eid, 0)
        page = by_name.get(_norm_name(st.display_name))
        if page is None:
            check(f"跨源：{st.display_name} 在库里找得到", False, "页名对不上")
            continue
        hit += 1
        row = conn.execute(
            "SELECT hp, atk, defense, res, weight, level_count FROM enemy_level l "
            "JOIN enemy e ON e.page = l.page WHERE l.page = ? AND l.level = 0",
            (page,)).fetchone()
        want = (st.max_hp, st.atk, st.defense, st.magic_resistance, st.weight)
        got = (row["hp"], row["atk"], row["defense"], row["res"], row["weight"])
        check(f"跨源 {st.display_name}：生命/攻击/防御/法抗/重量",
              all(close(a, b) for a, b in zip(got, want)),
              f"PRTS {got} vs 本体 {want}")
        n_body = len(lib.levels(eid))
        check(f"跨源 {st.display_name}：档数",
              row["level_count"] == n_body,
              f"PRTS {row['level_count']} vs 本体 {n_body}")
    check("跨源对账命中数 = 锚点数", hit == len(CROSS_ENEMY_IDS),
          f"{hit}/{len(CROSS_ENEMY_IDS)}")


# ---------------------------------------------------- 4 解析口径守卫

def check_parsing_rules(conn: sqlite3.Connection) -> None:
    print("\n[4] 解析口径守卫（每一条都对应一个真踩过的坑）")
    boss = conn.execute("SELECT page FROM enemy WHERE page = ?",
                        (BOSS_PAGE,)).fetchone()
    check(f"BOSS「{BOSS_PAGE}」在库里", boss is not None)
    if boss is not None:
        levels = {r["level"]: r for r in conn.execute(
            "SELECT * FROM enemy_level WHERE page = ? ORDER BY level",
            (BOSS_PAGE,))}
        lv0, lv1 = levels.get(0), levels.get(1)
        check("BOSS 两档俱全", lv0 is not None and lv1 is not None)
        if lv0 is not None and lv1 is not None:
            check("BOSS 档0 数值与文档一致",
                  (lv0["hp"], lv0["atk"], lv0["defense"], lv0["res"],
                   lv0["move_speed"], lv0["base_attack_time"], lv0["weight"],
                   lv0["range_radius"], lv0["target_value"]) ==
                  (150000.0, 650.0, 600.0, 20.0, 0.7, 6.0, 7.0, 2.6, 2.0))
            check("BOSS 档1 覆写了生命/攻击/防御，其余继承档0",
                  (lv1["hp"], lv1["atk"], lv1["defense"], lv1["move_speed"],
                   lv1["base_attack_time"]) ==
                  (180000.0, 750.0, 800.0, 0.7, 6.0))
            explicit = json.loads(lv1["explicit_params"] or "{}")
            check("注释掉的参数**没有**混进生效参数（档1 的 名称 必须缺席）",
                  "名称" not in explicit, f"实得 {sorted(explicit)}")
            hidden = json.loads(lv1["hidden_params"] or "{}")
            check("注释里的参数被单独收下（档1 的真名「死志暗影」）",
                  hidden.get("名称") == "死志暗影", f"实得 {hidden}")
            bb = json.loads(lv0["blackboard"] or "{}")
            check("BOSS 档0 黑板：倒地阈值 6000 / 持续 5 秒",
                  (bb.get("TotalAttack.weak_max"),
                   bb.get("TotalAttack.fall_duration")) == (6000.0, 5.0),
                  f"实得 {bb.get('TotalAttack.weak_max')} / "
                  f"{bb.get('TotalAttack.fall_duration')}")
            check("BOSS 两形态的物理相性（A 弱点 0 / B 免疫 2）",
                  (bb.get("Mode_A.PHYSICAL"), bb.get("Mode_B.PHYSICAL"))
                  == (0.0, 2.0))
            n_imm = _count(conn, """SELECT COUNT(*) FROM enemy_resist
                                    WHERE page = ? AND level = 0
                                      AND is_immune = 1""", (BOSS_PAGE,))
            check("BOSS 档0 免疫 9 项", n_imm == 9, f"实得 {n_imm}")
            sk = conn.execute("""SELECT init_cooldown, cooldown, sp_cost
                                 FROM enemy_skill
                                 WHERE page = ? AND level = 0 AND slot = 0""",
                              (BOSS_PAGE,)).fetchone()
            check("技能冷却语义：技能N初始=首次冷却、技能N消耗=周期冷却",
                  sk is not None and tuple(sk) == (25.0, 30.0, None),
                  f"实得 {tuple(sk) if sk else None}")

    slime = conn.execute("SELECT * FROM enemy WHERE page = '源石虫'").fetchone()
    if slime is None:
        check("源石虫在库里", False)
    else:
        lvs = {r["level"]: r for r in conn.execute(
            "SELECT * FROM enemy_level WHERE page = '源石虫' ORDER BY level")}
        check("源石虫 两档的覆写（550/130 → 2050/300）",
              (lvs[0]["hp"], lvs[0]["atk"], lvs[1]["hp"], lvs[1]["atk"])
              == (550.0, 130.0, 2050.0, 300.0))
        check("源石虫 档1 显式参数只有 index/攻击力/最大生命值",
              sorted(json.loads(lvs[1]["explicit_params"] or "{}"))
              == ["index", "攻击力", "最大生命值"])

    idol = conn.execute("SELECT * FROM enemy WHERE page = '挥铳圣像'").fetchone()
    if idol is None:
        check("挥铳圣像在库里", False)
    else:
        check("挥铳圣像 行动方式 = 飞行（对应本体的 motion=FLY）",
              idol["move_way"] == "飞行", f"实得 {idol['move_way']}")
        bb = json.loads(conn.execute(
            "SELECT blackboard FROM enemy_level WHERE page = '挥铳圣像' "
            "AND level = 0").fetchone()["blackboard"] or "{}")
        check("挥铳圣像 击破阈值 4000（但相性 1/1/1，永不倒地）",
              bb.get("TotalAttack.weak_max") == 4000.0
              and bb.get("TotalAttack.PHYSICAL") == 1.0)


# -------------------------------------------------------- 5 查询入口冒烟

def check_api(conn: sqlite3.Connection) -> None:
    print("\n[5] 查询入口冒烟")
    rows = find_enemies(conn, "死志")
    check("find_enemies('死志') 有结果", bool(rows), f"实得 {len(rows)} 条")
    check("find_enemies 按地位级别过滤", all(
        r["grade"] == "领袖" for r in find_enemies(conn, "", limit=50,
                                                   grade="领袖")),
        "领袖档")
    detail = enemy_detail(conn, "源石虫")
    check("enemy_detail('源石虫') 给得出两档",
          [lv["level"] for lv in detail["levels"]] == [0, 1])


# ------------------------------------------- 6 字段审计补上的四处（2026-09-16）
#
# 每一条都对应"上游写了、解析器没认"的静默少数据。这类缺陷**不报错、行数照旧**，
# 只有拿模板逐字段点才算得出来（工具：tools/enemy_field_audit.py）。

def check_field_audit(conn: sqlite3.Connection) -> None:
    print("\n[6] 字段审计（上游写了但白名单没认的那几处）")

    # -- 抗性覆写：压过同名的 *抗性 字段 ------------------------------------
    live = {r["name"]: dict(r) for r in conn.execute(
        "SELECT name, value, is_immune, source FROM enemy_resist "
        "WHERE page='蔓德拉' AND level=0 AND is_effective=1")}
    check("蔓德拉 眩晕抗性 = 覆写来的免疫，而不是字段里的「无」",
          live.get("眩晕抗性", {}).get("is_immune") == 1
          and live.get("眩晕抗性", {}).get("source") == "覆写",
          f"实得 {dict(live.get('眩晕抗性') or {})}")
    check("覆写还能表达标准字段表里没有的项（失衡/强制缴械）",
          {"失衡抗性", "强制缴械抗性"} <= set(live),
          f"实得 {sorted(live)}")
    dead = {r["name"] for r in conn.execute(
        "SELECT name FROM enemy_resist WHERE page='蔓德拉' AND level=0 "
        "AND is_effective=0")}
    check("被覆写顶掉的字段值仍留档（不丢数据，只是标了失效）",
          {"眩晕抗性", "沉默抗性", "冻结抗性"} <= dead, f"实得 {sorted(dead)}")
    check("没有任何一条抗性同时既是生效又是失效",
          _count(conn, "SELECT COUNT(*) n FROM enemy_resist r1 JOIN enemy_resist "
                       "r2 ON r1.page=r2.page AND r1.level=r2.level "
                       "AND r1.name=r2.name AND r1.source<>r2.source "
                       "AND r1.is_effective=1 AND r2.is_effective=1") == 0)

    # -- 技力槽的词序颠倒写法 ----------------------------------------------
    sp = conn.execute(
        "SELECT init_sp, max_sp FROM enemy_level WHERE page='反巫术变位炸弹' "
        "AND level=0").fetchone()
    check("`技力初始`（词序颠倒）也能认出来 init_sp",
          sp["init_sp"] == 0.0 and sp["max_sp"] == 10.0, f"实得 {dict(sp)}")

    # -- 空串不覆盖继承值 ---------------------------------------------------
    # 模板写 `{{{字段|默认}}}`，而 MediaWiki 在参数**为空**时同样取默认，
    # 故 `|技力初始=` 的语义是"继承上一档"。原实现让空串顶掉继承值。
    sp1 = conn.execute(
        "SELECT init_sp, max_sp FROM enemy_level WHERE page='反巫术变位炸弹' "
        "AND level=1").fetchone()
    check("档 1 的空串不抹掉档 0 的技力槽（空 = 继承）",
          sp1["init_sp"] == 0.0 and sp1["max_sp"] == 10.0, f"实得 {dict(sp1)}")
    rng = [r["range_radius"] for r in conn.execute(
        "SELECT range_radius FROM enemy_level WHERE page='杜卡雷，“君主之红”' "
        "ORDER BY level")]
    check("杜卡雷 四档攻击范围半径都是 2.2（不是 None/近战 0）",
          rng == [2.2] * 4, f"实得 {rng}")

    # -- 站方勘误是两份文本，不是清洗前后 -----------------------------------
    ab = conn.execute("SELECT ability, ability_fixed FROM enemy WHERE "
                      "page='“大总统”汉科'").fetchone()
    check("「大总统」汉科 的原文与勘误文本确实不同（语义反转）",
          ab["ability"] is not None and ab["ability_fixed"] is not None
          and "不会" not in ab["ability"] and "不会" in ab["ability_fixed"],
          f"原文含『不会』={'不会' in (ab['ability'] or '')}")
    check("有勘误的页面数 = 114", _count(
        conn, "SELECT COUNT(*) n FROM enemy WHERE ability_fixed IS NOT NULL") == 114)
    check("勘误原文（带标记）也留着，可追溯",
          _count(conn, "SELECT COUNT(*) n FROM enemy WHERE ability_errata "
                       "LIKE '%修正lite%'") == 114)
    check("档位描述的内联勘误展开存进 description_fixed（6 档）", _count(
        conn, "SELECT COUNT(*) n FROM enemy_level "
              "WHERE description_fixed IS NOT NULL") == 6)

    # -- 展开勘误时不能多吃花括号 -------------------------------------------
    # `iter_templates` 曾把 `end` 给成闭合 `}}` 的**第一个字符**下标，
    # 而第三项 `raw` 却含完整的 `}}`——两者不自洽。照 `last = end` 续接的
    # `resolve_fixes` 于是每次都多吃一对 `}}`，114 个页面的 `ability_fixed`
    # 全部混进孤立 `}}`（「并不会}}使其中…失效」），不报错、只污染正文。
    # 判据用**配平**而不是"不许出现"，因为展开后的文本仍合法地含有
    # `{{术语|…}}` 这类未展开的模板。
    check("ability_fixed 的花括号配平（没错位吃进 `}}`）", _count(
        conn, r"""SELECT COUNT(*) n FROM enemy WHERE
            (LENGTH(ability_fixed) - LENGTH(REPLACE(ability_fixed,'{{',''))) <>
            (LENGTH(ability_fixed) - LENGTH(REPLACE(ability_fixed,'}}','')))"""
    ) == 0)
    check("description_fixed 的花括号配平", _count(
        conn, r"""SELECT COUNT(*) n FROM enemy_level WHERE
            description_fixed IS NOT NULL AND
            (LENGTH(description_fixed) - LENGTH(REPLACE(description_fixed,'{{',''))) <>
            (LENGTH(description_fixed) - LENGTH(REPLACE(description_fixed,'}}','')))"""
    ) == 0)


# ------------------------------------------------------------------ 主流程

def main() -> int:
    print(f"检查敌人库：{DEFAULT_ENEMY_DB_PATH}")
    conn = connect_enemy()
    try:
        src = GameDataSource()
        counts = check_selfconsistency(conn)
        check_coverage(conn, counts)
        check_cross_source(conn, src)
        check_parsing_rules(conn)
        check_api(conn)
        check_field_audit(conn)
    finally:
        conn.close()

    print()
    print("=" * 60)
    if _FAILED:
        print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
        for name in _FAILED:
            print(f"  - {name}")
        return 1
    print(f"通过 {_PASSED} 项，无失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
