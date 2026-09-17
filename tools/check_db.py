"""干员库（`data/akdb.sqlite`）的完整性与一致性检查。

    python tools/check_db.py

分五类：

1. **出处**——库的结构版本、data_version、行数与源表条数逐一对齐；
2. **引用完整性**——外键式的引用在库里都找得到（技能、范围、模组、阶段）；
3. **覆盖**——每个真干员都有阶段、属性关键帧、信赖帧；模组"三道门"的口径
   与 `battle_equip_table` 的条数吻合；
4. **取值**——拿已核对的实机面板当坐标（阿米娅六个端点、怒潮凛冬精2 60
   的插值结果），并抽查结构与 `OperatorCalculator` 是否同源一致；
5. **查询入口**——`db find/skill/talent` 背后的函数各真跑一次，防 SQL 列名
   一类"检查全绿但命令崩溃"的错。

第 4 类里的面板值是**外部锚点**（PRTS 属性模板 / 实机录像），不是从库里
反推的，所以它能抓住"库和计算器一起错"的情况。

敌人库是**另一个文件**，自检在 `tools/check_enemy_db.py`。
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.db import (                                          # noqa: E402
    DEFAULT_DB_PATH, DB_VERSION, char_detail, connect, db_info,
)
from ak_tactic.db.build import (                                    # noqa: E402
    SHARED_BATTLE_TRAPS, ra_dropped_skills, sandbox_device_ids,
)
from ak_tactic.db.tiles import KNOWN_GAPS, load_tiles               # noqa: E402
from ak_tactic.gamedata.source import GITHUB_BASE, GameDataSource   # noqa: E402
from ak_tactic.operator import OperatorCalculator, SkillBook            # noqa: E402

_FAILED: list[str] = []
_PASSED = 0


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


# ------------------------------------------------------------------ 1 出处

def check_provenance(conn: sqlite3.Connection, src: GameDataSource) -> None:
    print("\n[1] 出处与行数")
    info = db_info(conn)
    meta = info["meta"]
    check(f"结构版本 = {DB_VERSION}", info["version_ok"],
          f"库里是 {meta.get('db_version')}")
    check("data_version 有值", bool(meta.get("data_version")),
          (meta.get("data_version") or "").splitlines()[0] if
          meta.get("data_version") else "空")
    check("source 指向 GitHub 镜像", "ArknightsGameData" in (meta.get("source") or ""),
          meta.get("source") or "空")

    chars = src.fetch_json("excel/character_table.json")
    patches = src.fetch_json("excel/char_patch_table.json").get("patchChars") or {}
    skills = src.fetch_json("excel/skill_table.json")
    uniequip = src.fetch_json("excel/uniequip_table.json")
    battle_equip = src.fetch_json("excel/battle_equip_table.json")
    ranges = src.fetch_json("excel/range_table.json")

    # 生息演算装置在入库时被整体剔除，故源表条数要减掉它们——判据与建库器同一份
    # （tools 侧不重写一遍，否则两边迟早对不上）。
    ra_all, _warn = sandbox_device_ids(src)
    every_char = {**chars, **patches}
    excluded = ra_all & set(every_char)
    dropped = ra_dropped_skills(every_char, excluded)

    want_ops = len(chars) + len(patches) - len(excluded)
    got_ops = info["counts"]["operator"]
    check(f"干员条数 = character_table {len(chars)} + 升变形态 {len(patches)}"
          f" − 生息演算装置 {len(excluded)}",
          got_ops == want_ops, f"实得 {got_ops}")

    db_ids = {r[0] for r in conn.execute("SELECT char_id FROM operator")}
    ra_in_db = sorted(ra_all & db_ids)
    check(f"生息演算装置已剔净（源表 {len(ra_all)} 个）", not ra_in_db,
          f"库里仍有 {len(ra_in_db)}：{ra_in_db[:3]}")
    missing_shared = [t for t in sorted(SHARED_BATTLE_TRAPS)
                      if not _count(conn, "SELECT COUNT(*) FROM operator "
                                          "WHERE char_id=?", (t,))]
    check(f"与主线共用的 {len(SHARED_BATTLE_TRAPS)} 个通用装置仍保留",
          not missing_shared, f"少了 {missing_shared[:3]}")

    got_patch = _count(conn, "SELECT COUNT(*) FROM operator WHERE is_patch=1")
    check(f"升变形态被标出来（{len(patches)} 条）", got_patch == len(patches),
          f"实得 {got_patch}")

    real = sum(1 for c in chars.values()
               if (c.get("profession") or "") not in ("TOKEN", "TRAP"))
    real += sum(1 for c in patches.values()
                if (c.get("profession") or "") not in ("TOKEN", "TRAP"))
    got_real = info["counts"]["operator"] and _count(
        conn, "SELECT COUNT(*) FROM operator WHERE is_operator=1")
    check(f"其中真干员 = {real}", got_real == real, f"实得 {got_real}")

    check(f"技能条数 = skill_table 的 {len(skills)} − 装置专属 {len(dropped)}",
          info["counts"]["skill"] == len(skills) - len(dropped),
          f"实得 {info['counts']['skill']}")

    want_levels = sum(len(v.get("levels") or []) for k, v in skills.items()
                      if k not in dropped)
    check(f"技能等级行数 = {want_levels}",
          info["counts"]["skill_level"] == want_levels,
          f"实得 {info['counts']['skill_level']}")

    check(f"模组条数 = equipDict 的 {len(uniequip['equipDict'])}",
          info["counts"]["module"] == len(uniequip["equipDict"]),
          f"实得 {info['counts']['module']}")

    want_mlv = sum(len((battle_equip.get(m) or {}).get("phases") or [])
                   for m in uniequip["equipDict"])
    check(f"模组等级行数 = battle_equip 的 {want_mlv}",
          info["counts"]["module_level"] == want_mlv,
          f"实得 {info['counts']['module_level']}")

    check(f"范围条数 = range_table 的 {len(ranges)}",
          info["counts"]["attack_range"] == len(ranges),
          f"实得 {info['counts']['attack_range']}")


# ------------------------------------------------------------------ 2 引用

def check_references(conn: sqlite3.Connection, src: GameDataSource) -> None:
    print("\n[2] 引用完整性")

    def orphans(sql: str) -> list[str]:
        return [r[0] for r in conn.execute(sql).fetchall()]

    bad = orphans("SELECT DISTINCT s.skill_id FROM operator_skill s "
                  "JOIN operator o ON o.char_id = s.char_id "
                  "LEFT JOIN skill k ON k.skill_id = s.skill_id "
                  "WHERE k.skill_id IS NULL AND o.is_operator = 1")
    check("真干员的技能引用都在 skill 表里", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    # 召唤物/装置那侧有一条**上游缺口**：`trap_755_cdsoul`（啸叫音响）引用
    # `sktok_cdsoul`，而 skill_table.json 里根本没有这一条（881 条 sktok_* 里
    # 没它）。这不是建库漏了，是游戏数据自己的事——钉住它，多出一条就要查。
    tok = orphans("SELECT DISTINCT s.skill_id FROM operator_skill s "
                  "JOIN operator o ON o.char_id = s.char_id "
                  "LEFT JOIN skill k ON k.skill_id = s.skill_id "
                  "WHERE k.skill_id IS NULL AND o.is_operator = 0")
    check("召唤物/装置的技能引用：已知只剩 sktok_cdsoul 一条缺口",
          tok == ["sktok_cdsoul"], f"实得 {tok}")

    bad = orphans("SELECT DISTINCT p.range_id FROM operator_phase p "
                  "LEFT JOIN attack_range r ON r.range_id = p.range_id "
                  "WHERE p.range_id IS NOT NULL AND r.range_id IS NULL")
    check("阶段的攻击范围都在 attack_range 里", not bad,
          f"悬空 {len(bad)}：{bad[:3]}")

    bad = orphans("SELECT DISTINCT m.char_id FROM module m "
                  "LEFT JOIN operator o ON o.char_id = m.char_id "
                  "WHERE o.char_id IS NULL")
    check("模组挂的干员都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    bad = orphans("SELECT DISTINCT l.module_id FROM module_level l "
                  "LEFT JOIN module m ON m.module_id = l.module_id "
                  "WHERE m.module_id IS NULL")
    check("模组等级挂的模组都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    # 模组归属：与 uniequip_table 的 charEquip 逐项对齐（按形态分别列）。
    # 升变形态那几个模组的 equipDict.charId 一律指回原形态，所以不能拿它当准。
    uniequip = src.fetch_json("excel/uniequip_table.json")
    char_equip = uniequip.get("charEquip") or {}
    want_owner = {mid: cid for cid, mids in char_equip.items() for mid in mids}
    got_owner = {r["module_id"]: r["char_id"] for r in conn.execute(
        "SELECT module_id, char_id FROM module")}
    wrong = [f"{mid}: 库 {got_owner.get(mid)} / charEquip {cid}"
             for mid, cid in want_owner.items() if got_owner.get(mid) != cid]
    check(f"模组归属与 charEquip 一致（{len(want_owner)} 条有归属）", not wrong,
          f"不符 {len(wrong)}：{wrong[:2]}")

    bad = orphans("SELECT DISTINCT a.char_id FROM operator_attr a "
                  "LEFT JOIN operator o ON o.char_id = a.char_id "
                  "WHERE o.char_id IS NULL")
    check("属性关键帧挂的干员都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    bad = orphans("SELECT DISTINCT t.char_id FROM operator_talent t "
                  "LEFT JOIN operator o ON o.char_id = t.char_id "
                  "WHERE o.char_id IS NULL")
    check("天赋挂的干员都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    bad = orphans("SELECT DISTINCT c.char_id FROM operator_trait c "
                  "LEFT JOIN operator o ON o.char_id = c.char_id "
                  "WHERE o.char_id IS NULL")
    check("结构化特性挂的干员都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")

    bad = orphans("SELECT DISTINCT p.char_id FROM operator_phase p "
                  "LEFT JOIN operator o ON o.char_id = p.char_id "
                  "WHERE o.char_id IS NULL")
    check("阶段挂的干员都存在", not bad, f"悬空 {len(bad)}：{bad[:3]}")


# ------------------------------------------------------------------ 3 覆盖

def check_coverage(conn: sqlite3.Connection) -> None:
    print("\n[3] 覆盖")

    no_phase = [r[0] for r in conn.execute(
        "SELECT char_id FROM operator WHERE is_operator=1 AND char_id NOT IN "
        "(SELECT char_id FROM operator_phase)")]
    check("每个真干员都有阶段", not no_phase, f"缺 {len(no_phase)}：{no_phase[:3]}")

    no_attr = [r[0] for r in conn.execute(
        "SELECT char_id FROM operator WHERE is_operator=1 AND char_id NOT IN "
        "(SELECT char_id FROM operator_attr WHERE kind='phase')")]
    check("每个真干员都有等级关键帧", not no_attr, f"缺 {len(no_attr)}：{no_attr[:3]}")

    no_trust = [r[0] for r in conn.execute(
        "SELECT char_id FROM operator WHERE is_operator=1 AND char_id NOT IN "
        "(SELECT char_id FROM operator_attr WHERE kind='trust')")]
    check("每个真干员都有信赖帧", not no_trust, f"缺 {len(no_trust)}：{no_trust[:3]}")

    no_skill = [r[0] for r in conn.execute(
        "SELECT o.char_id FROM operator o WHERE o.is_operator=1 AND o.char_id NOT IN "
        "(SELECT char_id FROM operator_skill)")]
    print(f"         没有技能槽位的真干员：{len(no_skill)} 个"
          + (f"（如 {no_skill[:3]}）" if no_skill else ""))

    no_pot = [r[0] for r in conn.execute(
        "SELECT o.char_id FROM operator o WHERE o.is_operator=1 AND o.char_id NOT IN "
        "(SELECT char_id FROM operator_potential)")]
    # 潜能不是人人都有：**不可获取**的干员（29 名，isNotObtainable=1，全是
    # 预备干员与模式专属）在数据里就没有潜能表；另有 3 名联动/活动干员
    # （断罪者、罗小黑、九色鹿）也没有。除这 32 名之外多出一个就是异常。
    known_no_pot = {"char_159_peacok", "char_4067_lolxh", "char_4019_ncdeer"}
    unobtainable = {r[0] for r in conn.execute(
        "SELECT char_id FROM operator WHERE is_operator=1 AND is_not_obtainable=1")}
    check(f"没有潜能的干员 = 不可获取的 {len(unobtainable)} 名 + "
          f"联动 3 名（断罪者/罗小黑/九色鹿）",
          set(no_pot) == unobtainable | known_no_pot,
          f"实得 {len(no_pot)} 名，多出 "
          f"{sorted(set(no_pot) - unobtainable - known_no_pot)[:5]}")

    # 模组三道门：INITIAL 无战斗数值、ADVANCED 有数值、特限/特勤单列
    initial_with_levels = _count(
        conn, "SELECT COUNT(*) FROM module m WHERE m.type='INITIAL' AND EXISTS "
              "(SELECT 1 FROM module_level l WHERE l.module_id=m.module_id)")
    check("INITIAL（证章）都没有战斗数值", initial_with_levels == 0,
          f"实得 {initial_with_levels}")

    adv = _count(conn, "SELECT COUNT(*) FROM module WHERE type='ADVANCED'")
    adv_with = _count(
        conn, "SELECT COUNT(*) FROM module m WHERE m.type='ADVANCED' AND EXISTS "
              "(SELECT 1 FROM module_level l WHERE l.module_id=m.module_id)")
    check(f"ADVANCED 模组都有数值（{adv} 条）", adv == adv_with,
          f"有数值的 {adv_with}")

    special = _count(conn, "SELECT COUNT(*) FROM module WHERE is_special_equip=1")
    check("特限/特勤证章被标出来（21 条）", special == 21, f"实得 {special}")

    # 风味文本不入库（2026-09-17 裁定）：`module.description` 是模组故事
    # （麦哲伦的探险日记那类，905 行约 42 万字），全仓无一处读取——喂公式语料的
    # 是 `module_level.parts`，不是这一列。删掉零影响；这道守卫防的是"顺手加回来"
    # （上游 `uniequipDesc` 还在，加回来只要一行）。
    mod_cols = {r[1] for r in conn.execute("PRAGMA table_info(module)")}
    check("module 表不存模组风味文本（无 description 列）",
          "description" not in mod_cols, f"实得列 {sorted(mod_cols)}")

    # 攻击范围：1-1 必须是「自身格 + 正前方一格」
    cells = conn.execute("SELECT cells FROM attack_range WHERE range_id='1-1'"
                         ).fetchone()
    got = {tuple(c) for c in json.loads(cells[0])} if cells else set()
    check("范围 1-1 = {(0,0),(1,0)}", got == {(0, 0), (1, 0)}, f"实得 {sorted(got)}")

    empty = _count(conn, "SELECT COUNT(*) FROM attack_range WHERE cells='[]'")
    check("没有空的攻击范围", empty == 0, f"实得 {empty}")


# ------------------------------------------------------------------ 3b 技力回复口径


def check_sp_type(conn: sqlite3.Connection) -> None:
    """技力回复方式的安全边界。

    `skill._normalize_sp_type` 对 `sp_type == 8` 一律返回 PASSIVE（常亮）。
    这条归一**只在「干员侧不存在 sp_type=8 的非被动技能」时才成立**：
    `sktok_`（召唤物）里恰有 72 个技能是 8 + AUTO/MANUAL 且真的带 spCost
    （`sktok_cjbtow_1` cost=10、`sktok_dublst` cost=25），它们一旦进入
    `operator_skill`，就会被静默改成常亮技能，症状是「技能开了但看不出在转」。

    这两条断言把「批次二做召唤物时该改哪里」钉成红灯，而不是留一句注释。
    """
    print("\n[3c] 技力回复口径")

    #: `operator` 表里有 915 行**不是真干员**（召唤物 / 生息演算建筑，is_operator=0），
    #: `sktok_*` 技能正是挂在它们名下。第一版漏了 `is_operator=1` 这道，
    #: 于是把 72 个召唤物技能一并算成「干员侧的例外」，自检当场红——**红的对**，
    #: 错的是查询：它问的不是「干员侧」，而是「operator 表侧」。
    bad = [r[0] for r in conn.execute(
        "SELECT DISTINCT sl.skill_id FROM operator_skill os "
        "JOIN operator o ON o.char_id = os.char_id "
        "JOIN skill_level sl ON sl.skill_id = os.skill_id "
        "WHERE o.is_operator = 1 AND sl.sp_type = '8' "
        "AND sl.skill_type <> 'PASSIVE'")]
    check("真干员侧 sp_type=8 的技能全是 PASSIVE（否则会被归一成常亮）",
          not bad, f"例外：{bad[:6]}")

    stray = [r[0] for r in conn.execute(
        "SELECT DISTINCT sl.skill_id FROM skill_level sl "
        "WHERE sl.sp_type = '8' AND sl.skill_type <> 'PASSIVE' "
        "AND sl.skill_id NOT LIKE 'sktok_%'")]
    check("sp_type=8 的非被动技能全在召唤物（sktok_）名下",
          not stray, f"例外：{stray[:6]}")

    #: 三条 SP 通道各须有真身，否则批次一 ② 的接线是空转。
    for label, st in (("自动回复", "INCREASE_WITH_TIME"),
                      ("攻击回复", "INCREASE_WHEN_ATTACK"),
                      ("受击回复", "INCREASE_WHEN_TAKEN_DAMAGE")):
        n = _count(conn, "SELECT COUNT(DISTINCT sl.skill_id) FROM operator_skill os "
                         "JOIN skill_level sl ON sl.skill_id = os.skill_id "
                         "WHERE sl.sp_type = ?", (st,))
        check(f"{label}技能存在（批次一 ② 的三通道之一）", n > 0, f"{n} 个")


# ------------------------------------------------------------------ 4 取值

#: 外部锚点：PRTS「属性」模板给的阿米娅端点（精英, 阶段内等级）
AMIYA_PANEL = {
    (0, 1): (699, 276, 48, 10),
    (0, 50): (958, 390, 81, 10),
    (1, 1): (958, 390, 81, 15),
    (1, 70): (1198, 514, 110, 15),
    (2, 1): (1198, 514, 110, 20),
    (2, 80): (1480, 612, 121, 20),
}


def check_values(conn: sqlite3.Connection, calc: OperatorCalculator,
                 book: SkillBook) -> None:
    print("\n[4] 取值（拿外部锚点对）")

    d = char_detail(conn, "char_002_amiya")
    frames = {(a["phase"], a["level"]): a for a in d["attributes"]
              if a["kind"] == "phase"}
    for (phase, level), (hp, atk, df, res) in AMIYA_PANEL.items():
        f = frames.get((phase, level))
        ok = (f is not None and close(f["hp"], hp, 0.5)
              and close(f["atk"], atk, 0.5) and close(f["def"], df, 0.5)
              and close(f["res"], res, 0.5))
        check(f"阿米娅 精{phase} {level}级 = {hp}/{atk}/{df}/{res}", ok,
              "库里没有这一帧" if f is None else
              f"实得 {f['hp']}/{f['atk']}/{f['def']}/{f['res']}")

    trust = {a["level"]: a for a in d["attributes"] if a["kind"] == "trust"}
    check("阿米娅 满信赖帧 = 生命+200 / 攻击+70",
          close(trust[50]["hp"], 200, 0.5) and close(trust[50]["atk"], 70, 0.5),
          f"实得 {trust[50]['hp']}/{trust[50]['atk']}")

    # 怒潮凛冬精2 60（零信赖、无模组）：实机面板，靠**阶段内线性插值**得到
    # （关键帧只有 1 级与 90 级）。这条同时验库里的帧与计算器的插值口径。
    #
    # ⚠️ 容差已从 ±1 收到 0。原先写 `close(..., 1)` 时它**分辨不出取整方式**：
    # 攻击 floor=1193 / round=1194 恰好相差 1，容差 1 把两者一起放过，于是
    # 2026-09-17 把默认取整从 floor 改成 round 时，这一条**毫无反应**。
    # 口径定案后必须锚死具体整数，否则守卫等于没有。
    #
    # 录像读数（2026-09-15）记的是 1193，与 round 差 1；同日博士给出的
    # 完整面板（信赖 200% + 模组 Lv1）三个数全部精确命中 round，见 [4b] 节。
    st = calc.stats("char_1051_headb2", elite=2, level=60, trust=0, potential=1)
    t = st.total
    check("怒潮凛冬 精2 60 零信赖 = 2731/1194/387/0",
          t["maxHp"] == 2731 and t["atk"] == 1194 and t["def"] == 387
          and close(t["magicResistance"], 0, 0.5),
          f"实得 {t['maxHp']}/{t['atk']}/{t['def']}/{t['magicResistance']}")

    # 同源抽查：库里每个阶段的第一帧，与计算器读到的关键帧必须一致。
    # 两处都从 character_table 来，所以对不上就是建库时映射错了列。
    diff: list[str] = []
    sample = [r[0] for r in conn.execute(
        "SELECT char_id FROM operator WHERE is_operator=1 ORDER BY char_id")]
    for cid in sample:
        char = calc.character(cid)
        for phase_i, ph in enumerate(char.get("phases") or []):
            for frame in ph.get("attributesKeyFrames") or []:
                data = frame.get("data") or {}
                row = conn.execute(
                    "SELECT hp, atk, base_attack_time FROM operator_attr "
                    "WHERE char_id=? AND kind='phase' AND phase=? AND level=?",
                    (cid, phase_i, int(frame.get("level") or 0))).fetchone()
                if row is None or not close(row["hp"], data.get("maxHp"), 0.5) \
                        or not close(row["atk"], data.get("atk"), 0.5):
                    diff.append(f"{cid} 精{phase_i} {frame.get('level')}级")
    check(f"全部 {len(sample)} 名真干员的关键帧与计算器一致", not diff,
          f"不一致 {len(diff)}：{diff[:3]}")

    # 技能黑板的拍平形态可用：挑一个已知的读一读。
    # 注意**原文键带 `attack@` 前缀**（`attack@times` / `attack@atk_scale`），
    # 去前缀是 `SkillEffects` 的活，不是建库的活——两处都验一遍才说得清。
    row = conn.execute(
        "SELECT blackboard FROM skill_level WHERE skill_id=? AND level=10",
        ("skchr_amiya_2",)).fetchone()
    bb = json.loads(row[0]) if row else {}
    check("阿米娅「精神爆发」10 级黑板含 attack@times=8 / attack@atk_scale=0.6",
          close(bb.get("attack@times"), 8) and close(bb.get("attack@atk_scale"), 0.6, 0.001),
          f"实得 {bb}")

    lv = book.for_operator("char_002_amiya")[1].level(7, 3)
    check("同一条经 SkillEffects 归一后 = 8 连击 × 60%",
          lv.effects.hit_count == 8 and close(lv.effects.atk_scale, 0.6, 1e-9),
          f"实得 {lv.effects.hit_count}× × {lv.effects.atk_scale}")

    # 天赋黑板（怒潮凛冬的溅射系数，命中实机机制）
    row = conn.execute(
        "SELECT blackboard FROM operator_talent WHERE char_id=? AND name=? "
        "ORDER BY cand_index LIMIT 1", ("char_1051_headb2", "汹涌怒火")).fetchone()
    bb = json.loads(row[0]) if row else {}
    check("怒潮凛冬「汹涌怒火」黑板含 splash_atk_scale=0.24",
          close(bb.get("attack@splash_atk_scale"), 0.24, 1e-9), f"实得 {bb}")

    # 结构化特性（只有部分干员有）
    row = conn.execute(
        "SELECT blackboard FROM operator_trait WHERE char_id=?",
        ("char_1051_headb2",)).fetchone()
    bb = json.loads(row[0]) if row else {}
    check("怒潮凛冬的结构化特性含 attack@atk_scale_2=0.5",
          close(bb.get("attack@atk_scale_2"), 0.5, 1e-9), f"实得 {bb}")


def check_stat_anchors(calc: OperatorCalculator) -> None:
    """[4b] 属性口径的**实机锚点**——信赖映射与取整方式的定案依据。

    2026-09-17 定案，两条都是博士提供的实机面板、逐位精确：

    * **取整 = 四舍五入（round）**。旁证：prts.wiki 干员页内嵌的
      「属性计算器」用的就是 `Math.round`，插值写法与本项目同构。
    * **信赖**：`favorKeyFrames` 的 level = **显示信赖 ÷ 2**，且**显示信赖到
      100% 即封顶**（prts.wiki「信赖值」页：「干员信赖值达到100%后，属性加成
      达到上限」）。名册的 `trust` 字段本身就是「森空岛 favorPercent ÷ 2」，
      即显示 ÷ 2，所以它**直接就是 level，不能再除一次**。

    这两条以前都写错过：取整曾默认 floor；信赖曾写成 `level = trust / 2`
    （把**助战干员**的旧换算当成了通用规则，那条 2025/12/5 已取消），
    症状是 154% 信赖只给 +46.2 攻击而非满值 +60。
    """
    print("\n[4b] 属性口径的实机锚点（2026-09-17 定案）")

    check("默认取整 = round（四舍五入）",
          calc.rounding == "round", f"实得 {calc.rounding!r}")

    # 红豆：她的信赖只加攻击、潜 4 也只加攻击 ⇒ **生命是纯基础值的试纸**，
    # 不掺信赖与潜能。攻击那一栏则能把 floor 排除（floor 只能到 509）。
    v = calc.stats("char_290_vigna", elite=1, level=38, trust=77.0,
                   potential=6).total
    check("红豆 精1 38 潜6 信赖154% = 生命 1185 / 攻击 510（实机）",
          v["maxHp"] == 1185 and v["atk"] == 510,
          f"实得 {v['maxHp']}/{v['atk']}")

    # 信赖封顶的守卫：显示 100% 与显示 200% 必须给**完全一样**的加成。
    lo = calc.stats("char_290_vigna", elite=1, level=38, trust=50.0,
                    potential=6).total
    hi = calc.stats("char_290_vigna", elite=1, level=38, trust=100.0,
                    potential=6).total
    check("信赖封顶：内部 50（显示100%）与内部 100（显示200%）加成相同",
          lo["atk"] == hi["atk"], f"实得 {lo['atk']} vs {hi['atk']}")

    # 怒潮凛冬满配：三个数一起对。攻击一栏是决定性的——
    # round(1193.91 + 50 + 63) = 1307，而 floor 给 1306。
    w = calc.stats("char_1051_headb2", elite=2, level=60, trust=100.0,
                   potential=1, module="uniequip_002_headb2",
                   module_level=1).total
    check("怒潮凛冬 精2 60 信赖200% 模组Lv1 = 2981/1307/473（实机）",
          w["maxHp"] == 2981 and w["atk"] == 1307 and w["def"] == 473,
          f"实得 {w['maxHp']}/{w['atk']}/{w['def']}")


def check_roster(conn: sqlite3.Connection) -> None:
    """与森空岛名册交叉校验。

    名册是**独立外部源**（鹰角官方账号数据，见 `tools/skland.py`），不是从
    gamedata 推的，所以它能抓住"库里根本没有这个干员"这类整块缺口：
    名册里每个干员的职业、分支、模组、专精技能 id，都要在库里对得上。
    """
    print("\n[3b] 与森空岛名册交叉校验")
    files = sorted((Path(__file__).resolve().parent.parent
                    / "data" / "skland").glob("roster_*.json"))
    if not files:
        print("         没有名册文件（data/skland/roster_*.json），跳过")
        return

    for path in files:
        roster = json.loads(path.read_text(encoding="utf-8"))
        opers = roster.get("opers") or []
        print(f"         {path.name}：{roster.get('nickName')}，"
              f"{len(opers)} 名干员")

        miss_op: list[str] = []
        bad_prof: list[str] = []
        bad_sub: list[str] = []
        miss_skill: list[str] = []
        miss_module: list[str] = []
        for o in opers:
            cid = o.get("charId")
            row = conn.execute(
                "SELECT name, profession, sub_profession_name, is_operator "
                "FROM operator WHERE char_id=?", (cid,)).fetchone()
            if row is None or not row["is_operator"]:
                miss_op.append(f"{o.get('name')}({cid})")
                continue
            if o.get("profession") and o["profession"] != row["profession"]:
                bad_prof.append(f"{cid}: 名册 {o['profession']} / 库 "
                                f"{row['profession']}")
            if o.get("subProfession") and row["sub_profession_name"] \
                    and o["subProfession"] != row["sub_profession_name"]:
                bad_sub.append(f"{cid}: 名册 {o['subProfession']} / 库 "
                               f"{row['sub_profession_name']}")
            ids = list((o.get("mastery") or {}).keys())
            if o.get("defaultSkillId"):
                ids.append(o["defaultSkillId"])
            for sid in ids:
                if conn.execute("SELECT 1 FROM skill WHERE skill_id=?",
                                (sid,)).fetchone() is None:
                    miss_skill.append(sid)
                elif conn.execute(
                        "SELECT 1 FROM operator_skill WHERE char_id=? AND skill_id=?",
                        (cid, sid)).fetchone() is None:
                    miss_skill.append(f"{sid}（不属于 {cid}）")
            for m in o.get("modules") or []:
                mid = m.get("id")
                row2 = conn.execute(
                    "SELECT char_id FROM module WHERE module_id=?", (mid,)).fetchone()
                if row2 is None:
                    miss_module.append(mid)
                elif row2["char_id"] != cid:
                    miss_module.append(f"{mid}（挂在 {row2['char_id']}）")

        check(f"名册里的干员库里都有（{len(opers)} 名）", not miss_op,
              f"缺 {len(miss_op)}：{miss_op[:3]}")
        check("职业（profession）逐项一致", not bad_prof,
              f"不一致 {len(bad_prof)}：{bad_prof[:2]}")
        check("职业分支（subProfession）逐项一致", not bad_sub,
              f"不一致 {len(bad_sub)}：{bad_sub[:2]}")
        check("名册引用的技能都在库里且属于该干员", not miss_skill,
              f"缺 {len(miss_skill)}：{miss_skill[:3]}")
        check("名册引用的模组都在库里且挂在该干员名下", not miss_module,
              f"缺 {len(miss_module)}：{miss_module[:3]}")


def check_api(conn: sqlite3.Connection) -> None:
    """查询入口的冒烟测试。

    为什么单开一节：这些函数就是 `python -m ak_tactic db ...` 背后的实现，SQL 里
    一个列名写错就整条命令崩，而**行数/取舍/取值那几类检查全都照样通过**。
    2026-09-15 就撞过一次：`search_talents` 因为 JOIN 了 operator，两张表都有
    `name`，裸写 `name` 直接 `ambiguous column name`，`db talent` 整个子命令报错，
    而 check_db 当时 50 项全绿、毫无察觉。所以每个入口都在这里真跑一次。
    """
    print("\n[6] 查询入口冒烟")
    from ak_tactic.db.api import find_operators, search_skills, search_talents

    ops = find_operators(conn, "能天使", limit=5)
    check("find_operators 按名搜到能天使",
          any(r["char_id"] == "char_103_angel" for r in ops),
          f"实得 {[r['char_id'] for r in ops]}")

    sk = search_skills(conn, "取势", limit=5)
    check("search_skills 按名搜到取势",
          any(r["skill_id"] == "skchr_wang_1" for r in sk),
          f"实得 {[r['skill_id'] for r in sk]}")

    # 下面三条走的是同一个函数的不同分支：只有走 JOIN 的那条会暴露列名歧义，
    # 三个都留，缺一个都可能让这个 bug 再溜回来。
    tal = search_talents(conn, "铸子", limit=5)
    check("search_talents 按名搜（JOIN 之后列名必须带表别名）",
          any(r["name"] == "铸子" for r in tal), f"实得 {len(tal)} 行")

    tal_key = search_talents(conn, "", limit=5,
                             blackboard_key="attack@max_trigger_cnt")
    check("search_talents 按黑板键搜", bool(tal_key), f"实得 {len(tal_key)} 行")

    tal_desc = search_talents(conn, "停顿", limit=5)
    check("search_talents 按描述搜", bool(tal_desc), f"实得 {len(tal_desc)} 行")


def check_tiles(conn: sqlite3.Connection) -> None:
    """[7] 地块字典：tile 表。

    这是本库**唯一非 gamedata 来源**的表（gamedata 里没有地块表，两个镜像都
    404），来自 theresa.wiki 的地图数据接口。它把此前只能靠 tileKey 名字猜的
    东西钉死了，所以要连名字一起守卫。
    """
    print("\n[7] 地块字典（tile 表，来源 theresa.wiki）")
    table = load_tiles(conn)
    check("tile 表非空（建库时取不到只记警告、会留空）", bool(table),
          f"{len(table)} 条")
    check("条数与实测的 95 一致", len(table) == 95, f"{len(table)} 条")

    # 这 13 条此前全靠猜，现在有权威名字，钉住
    pinned = {
        "tile_road": "平地", "tile_wall": "高台", "tile_floor": "不可放置位",
        "tile_forbidden": "禁入区", "tile_empty": "空", "tile_hole": "地穴",
        "tile_start": "侵入点", "tile_end": "保护目标",
        "tile_infection": "活性源石", "tile_telin": "通道入口",
        "tile_telout": "通道出口", "tile_fence_bound": "围墙",
        "tile_flystart": "空袭侵入点",
    }
    wrong = {k: (table.get(k) or {}).get("name")
             for k, v in pinned.items() if (table.get(k) or {}).get("name") != v}
    check("13 个关键地块的中文名与字典逐条一致", not wrong,
          str(wrong) if wrong else "平地/高台/不可放置位/禁入区/空/地穴…")

    # **纠错守卫**：tile_infection 是「活性源石」（增益地块：部署的友军与经过的
    # 敌军获得攻击力与攻速提升，但持续受伤），**不是**被污染的田地。
    # 曾据坐标巧合（act31side_08 的污染点 (7,1) 翻过来正落在它上面）把它判成田地。
    inf = (table.get("tile_infection") or {}).get("description") or ""
    check("tile_infection 是增益地块、不是田地（曾据坐标巧合误判）",
          "攻击" in inf and "田" not in inf, inf[:36])

    # tile_empty 的说明明写「游戏本体未包含该内容」——与它只在生息演算三关
    # 出现完全吻合，这条悬案（tile_forbidden vs tile_empty 谁对应哪种）可以销。
    emp = (table.get("tile_empty") or {}).get("description") or ""
    check("tile_empty 标注了「游戏本体未包含该内容」", "未包含" in emp, emp[-18:])

    func = {k for k, v in table.items() if v.get("is_functional")}
    check("能改变规则的地块被标成功能性（洞/传送/侵入点/保护目标）",
          {"tile_hole", "tile_telin", "tile_telout", "tile_start",
           "tile_end"} <= func, f"{len(func)} 条功能性")

    # 引用完整性。字典**不全**（已实测），所以判据是"缺口只有记录在案的"，
    # 不是"一个都不能缺"——把 KNOWN_GAPS 换成断言全在，等于自欺。
    used: set[str] = set()
    for p in sorted(Path("data/gamedata").rglob("level_*.json")):
        try:
            lv = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for t in (lv.get("mapData") or {}).get("tiles") or []:
            if t.get("tileKey"):
                used.add(t["tileKey"])
    missing = sorted(used - set(table))
    check("缓存关卡用到的地块键都查得到，缺口只有记录在案的",
          all(m in KNOWN_GAPS for m in missing),
          f"用到 {len(used)} 种；缺 {missing}" if missing else f"用到 {len(used)} 种，无缺口")
    check("KNOWN_GAPS 记的缺口确实是关卡里用到的（不是凭空记的）",
          all(g in used for g in KNOWN_GAPS), "、".join(KNOWN_GAPS) or "（无）")

    # 负面事实，也是这套数据的用途所在：**字典里没有「田地」类地块**。
    # 所以田地的判定没有数据可依，只能回到地形（低地且非特殊地形），
    # 这条断言防止日后有人"顺手"按某个地块名判田地。
    farm = sorted(k for k, v in table.items()
                  if "田" in (v.get("name") or "")
                  or "田" in (v.get("description") or ""))
    check("字典里没有「田地」类地块——田地判定只能靠地形（低地）", not farm,
          str(farm) if farm else "0 条")


def main() -> int:
    print(f"检查本地库：{DEFAULT_DB_PATH}")
    if not DEFAULT_DB_PATH.exists():
        print("  库不存在。先跑：python -m ak_tactic db build")
        return 1
    conn = connect()
    try:
        src = GameDataSource(base=GITHUB_BASE)
        calc = OperatorCalculator()
        book = SkillBook()
        check_provenance(conn, src)
        check_references(conn, src)
        check_coverage(conn)
        check_sp_type(conn)
        check_roster(conn)
        check_values(conn, calc, book)
        check_stat_anchors(calc)
        check_api(conn)
        check_tiles(conn)
    finally:
        conn.close()

    print(f"\n通过 {_PASSED} 项", end="")
    if _FAILED:
        print(f"，失败 {len(_FAILED)} 项：")
        for f in _FAILED:
            print(f"  - {f}")
        return 1
    print("，无失败。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
