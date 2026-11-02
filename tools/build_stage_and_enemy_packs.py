"""将游戏数据提纯并构建中央纯敌人库与怀黍离活动关卡资源包 SQLite 数据库。

输出：
- data/enemydb_pure.sqlite (中央纯敌人库：2154 个敌人的纯战斗属性、逐档数值与技能黑板)
- data/stages_act31side.sqlite (怀黍离 36 个关卡档位的纯战斗几何、路线、装置、出怪与机制包)
"""

import json
import os
import pathlib
import sqlite3
import sys

def unwrap(cell, default=None):
    if cell is None:
        return default
    if isinstance(cell, dict) and 'm_defined' in cell:
        if cell['m_defined']:
            return cell.get('m_value', default)
        return default
    return cell

def build_enemy_db(gamedata_root: pathlib.Path, out_db: pathlib.Path):
    print(f"Building pure enemy library: {out_db}...")
    if out_db.exists():
        out_db.unlink()

    conn = sqlite3.connect(out_db)
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE enemy (
        id TEXT PRIMARY KEY,
        name TEXT,
        max_level INTEGER
    )
    """)

    cur.execute("""
    CREATE TABLE enemy_stats (
        enemy_id TEXT,
        level INTEGER,
        max_hp REAL,
        atk REAL,
        def REAL,
        res REAL,
        move_speed REAL,
        attack_interval REAL,
        block_cnt INTEGER,
        life_cost INTEGER,
        taunt_level INTEGER,
        mass_level INTEGER,
        is_flying BOOLEAN,
        range_radius REAL,
        blackboard TEXT,
        skills TEXT,
        PRIMARY KEY (enemy_id, level)
    )
    """)

    # 读取 enemy_database.json
    db_path = gamedata_root / "map.ark-nights.com" / "levels" / "enemydata" / "enemy_database.json"
    data = json.loads(db_path.read_text(encoding="utf-8"))
    enemies = data.get("enemies", [])

    total_levels = 0
    for e in enemies:
        enemy_id = e["Key"]
        levels = e.get("Value", [])
        max_level = len(levels) - 1

        name = enemy_id
        cur.execute("INSERT INTO enemy (id, name, max_level) VALUES (?, ?, ?)", (enemy_id, name, max_level))

        # 逐档合并属性（低档先入，高档覆写）
        merged = {}
        for lvl_idx, lvl_data in enumerate(levels):
            # 获取 levelType / enemyData
            edata = lvl_data.get("enemyData", {})
            attrs = edata.get("attributes", {})

            for k, v in attrs.items():
                val = unwrap(v)
                if val is not None:
                    merged[k] = val

            for k in ("lifePointReduce", "rangeRadius", "applyWay"):
                if k in edata:
                    val = unwrap(edata[k])
                    if val is not None:
                        merged[k] = val

            bb = {}
            for item in edata.get("talentBlackboard", []) or []:
                k = item.get("key")
                v = item.get("value", 0.0)
                if k:
                    bb[k] = v

            skills_raw = edata.get("skills", [])

            max_hp = float(merged.get("maxHp", 1000.0))
            atk = float(merged.get("atk", 100.0))
            defense = float(merged.get("def", 0.0))
            res = float(merged.get("magicResistance", 0.0))
            move_speed = float(merged.get("moveSpeed", 1.0))
            attack_interval = float(merged.get("baseAttackTime", 1.0))
            block_cnt = int(merged.get("blockCnt", 1))
            life_cost = int(merged.get("lifePointReduce", 1))
            taunt_level = int(merged.get("tauntLevel", 0))
            mass_level = int(merged.get("massLevel", 0))
            is_flying = (merged.get("applyWay") == "FLY")
            range_radius = float(merged.get("rangeRadius", 1.0))

            cur.execute("""
            INSERT INTO enemy_stats (
                enemy_id, level, max_hp, atk, def, res, move_speed,
                attack_interval, block_cnt, life_cost, taunt_level,
                mass_level, is_flying, range_radius, blackboard, skills
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                enemy_id, lvl_idx, max_hp, atk, defense, res, move_speed,
                attack_interval, block_cnt, life_cost, taunt_level,
                mass_level, is_flying, range_radius, json.dumps(bb), json.dumps(skills_raw)
            ))
            total_levels += 1

    conn.commit()
    conn.close()
    print(f"Enemy DB build complete: {len(enemies)} enemies, {total_levels} stats rows.")

def build_stage_pack(gamedata_root: pathlib.Path, out_db: pathlib.Path):
    print(f"Building stage pack: {out_db}...")
    if out_db.exists():
        out_db.unlink()

    conn = sqlite3.connect(out_db)
    cur = conn.cursor()

    cur.execute("CREATE TABLE manifest (key TEXT PRIMARY KEY, value TEXT)")
    cur.execute("""
    CREATE TABLE stage (
        stage_id TEXT,
        difficulty TEXT,
        code TEXT,
        name TEXT,
        map_width INTEGER,
        map_height INTEGER,
        life INTEGER,
        cost_init REAL,
        cost_max REAL,
        cost_time REAL,
        deploy_limit INTEGER,
        speed_scale REAL,
        fps INTEGER,
        mechanisms TEXT,
        mech_config TEXT,
        required_enemies TEXT,
        PRIMARY KEY (stage_id, difficulty)
    )
    """)

    cur.execute("""
    CREATE TABLE stage_tiles (
        stage_id TEXT,
        difficulty TEXT,
        col INTEGER,
        row INTEGER,
        tile_key TEXT,
        buildable_type TEXT,
        PRIMARY KEY (stage_id, difficulty, col, row)
    )
    """)

    cur.execute("""
    CREATE TABLE stage_routes (
        stage_id TEXT,
        difficulty TEXT,
        route_index INTEGER,
        start_col REAL,
        start_row REAL,
        end_col REAL,
        end_row REAL,
        checkpoints TEXT,
        PRIMARY KEY (stage_id, difficulty, route_index)
    )
    """)

    cur.execute("""
    CREATE TABLE stage_tokens (
        stage_id TEXT,
        difficulty TEXT,
        token_index INTEGER,
        character_key TEXT,
        col INTEGER,
        row INTEGER,
        direction TEXT,
        blackboard TEXT,
        PRIMARY KEY (stage_id, difficulty, token_index)
    )
    """)

    cur.execute("""
    CREATE TABLE stage_spawns (
        stage_id TEXT,
        difficulty TEXT,
        spawn_index INTEGER,
        enemy_id TEXT,
        time REAL,
        level INTEGER,
        route_index INTEGER,
        overwritten_data TEXT,
        PRIMARY KEY (stage_id, difficulty, spawn_index)
    )
    """)

    stage_table_path = gamedata_root / "raw.githubusercontent.com" / "excel" / "stage_table.json"
    stage_table = json.loads(stage_table_path.read_text(encoding="utf-8")).get("stages", {})

    all_stages = [
        # 主线 HS-1 ~ HS-9
        ("act31side_01", "HS-1", "NORMAL", "level_act31side_01"),
        ("act31side_02", "HS-2", "NORMAL", "level_act31side_02"),
        ("act31side_03", "HS-3", "NORMAL", "level_act31side_03"),
        ("act31side_04", "HS-4", "NORMAL", "level_act31side_04"),
        ("act31side_05", "HS-5", "NORMAL", "level_act31side_05"),
        ("act31side_06", "HS-6", "NORMAL", "level_act31side_06"),
        ("act31side_07", "HS-7", "NORMAL", "level_act31side_07"),
        ("act31side_08", "HS-8", "NORMAL", "level_act31side_08"),
        ("act31side_09", "HS-9", "NORMAL", "level_act31side_09"),

        # 遭遇与支线 HS-S-1 ~ HS-S-4, MO-1, TR-1, TR-2
        ("act31side_s01", "HS-S-1", "NORMAL", "level_act31side_sub-1-1"),
        ("act31side_s01", "HS-S-1", "FOUR_STAR", "level_act31side_sub-1-1"),
        ("act31side_s02", "HS-S-2", "NORMAL", "level_act31side_sub-1-2"),
        ("act31side_s02", "HS-S-2", "FOUR_STAR", "level_act31side_sub-1-2"),
        ("act31side_s03", "HS-S-3", "NORMAL", "level_act31side_sub-1-3"),
        ("act31side_s03", "HS-S-3", "FOUR_STAR", "level_act31side_sub-1-3"),
        ("act31side_s04", "HS-S-4", "NORMAL", "level_act31side_sub-1-4"),
        ("act31side_s04", "HS-S-4", "FOUR_STAR", "level_act31side_sub-1-4"),
        ("act31side_mo01", "HS-MO-1", "NORMAL", "level_act31side_mo01"),
        ("act31side_tr01", "HS-TR-1", "NORMAL", "level_act31side_tr01"),
        ("act31side_tr02", "HS-TR-2", "NORMAL", "level_act31side_tr02"),

        # 高难/突袭 HS-EX-1 ~ HS-EX-8
        ("act31side_ex01", "HS-EX-1", "NORMAL", "level_act31side_ex01"),
        ("act31side_ex01", "HS-EX-1", "FOUR_STAR", "level_act31side_ex01"),
        ("act31side_ex02", "HS-EX-2", "NORMAL", "level_act31side_ex02"),
        ("act31side_ex02", "HS-EX-2", "FOUR_STAR", "level_act31side_ex02"),
        ("act31side_ex03", "HS-EX-3", "NORMAL", "level_act31side_ex03"),
        ("act31side_ex03", "HS-EX-3", "FOUR_STAR", "level_act31side_ex03"),
        ("act31side_ex04", "HS-EX-4", "NORMAL", "level_act31side_ex04"),
        ("act31side_ex04", "HS-EX-4", "FOUR_STAR", "level_act31side_ex04"),
        ("act31side_ex05", "HS-EX-5", "NORMAL", "level_act31side_ex05"),
        ("act31side_ex05", "HS-EX-5", "FOUR_STAR", "level_act31side_ex05"),
        ("act31side_ex06", "HS-EX-6", "NORMAL", "level_act31side_ex06"),
        ("act31side_ex06", "HS-EX-6", "FOUR_STAR", "level_act31side_ex06"),
        ("act31side_ex07", "HS-EX-7", "NORMAL", "level_act31side_ex07"),
        ("act31side_ex07", "HS-EX-7", "FOUR_STAR", "level_act31side_ex07"),
        ("act31side_ex08", "HS-EX-8", "NORMAL", "level_act31side_ex08"),
        ("act31side_ex08", "HS-EX-8", "FOUR_STAR", "level_act31side_ex08"),
    ]

    cur.execute("INSERT INTO manifest VALUES ('activity_id', 'act31side')")
    cur.execute("INSERT INTO manifest VALUES ('activity_name', '怀黍离')")
    cur.execute("INSERT INTO manifest VALUES ('stage_count', ?)", (str(len(all_stages)),))
    cur.execute("INSERT INTO manifest VALUES ('version', '1.0.0')")

    levels_dir = gamedata_root / "map.ark-nights.com" / "levels" / "activities" / "act31side"

    for stage_id, code, diff, file_prefix in all_stages:
        file_path = levels_dir / f"{file_prefix}.json"
        raw_level = json.loads(file_path.read_text(encoding="utf-8"))

        map_data = raw_level.get("mapData", {})
        map_grid = map_data.get("map", [])
        tiles_meta = map_data.get("tiles", [])
        H = len(map_grid)
        W = len(map_grid[0]) if H > 0 else 0

        # 地块写入
        for row_idx, row in enumerate(map_grid):
            for col_idx, tile_idx in enumerate(row):
                tm = tiles_meta[tile_idx]
                tkey = tm.get("tileKey", "tile_road")
                btype = tm.get("buildableType", "ALL")
                cur.execute("""
                INSERT INTO stage_tiles (stage_id, difficulty, col, row, tile_key, buildable_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (stage_id, diff, col_idx, row_idx, tkey, btype))

        # 路线写入 (路线 Y 轴在 Ark-Nights 口径中翻转: H - 1 - y)
        routes = raw_level.get("routes", [])
        for r_idx, r in enumerate(routes):
            if not r:
                continue
            sp = r.get("startPosition", {})
            ep = r.get("endPosition", {})
            start_col = float(sp.get("col", 0))
            start_row = float(H - 1 - sp.get("row", 0))
            end_col = float(ep.get("col", 0))
            end_row = float(H - 1 - ep.get("row", 0))

            cps = []
            for cp in r.get("checkpoints") or []:
                pos = cp.get("position", {})
                cps.append({
                    "type": cp.get("type", 0),
                    "time": cp.get("time", 0.0),
                    "col": float(pos.get("col", 0)),
                    "row": float(H - 1 - pos.get("row", 0))
                })

            cur.execute("""
            INSERT INTO stage_routes (stage_id, difficulty, route_index, start_col, start_row, end_col, end_row, checkpoints)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (stage_id, diff, r_idx, start_col, start_row, end_col, end_row, json.dumps(cps)))

        # 预定义装置 (Y 翻转)
        tokens = raw_level.get("predefines", {}).get("tokenInsts", [])
        for t_idx, t in enumerate(tokens):
            ckey = t.get("inst", {}).get("characterKey", "")
            pos = t.get("position", {})
            col = int(pos.get("col", 0))
            row = int(H - 1 - pos.get("row", 0))
            direction = t.get("direction", "Right")
            bb = t.get("overrideSkillBlackboard", [])

            cur.execute("""
            INSERT INTO stage_tokens (stage_id, difficulty, token_index, character_key, col, row, direction, blackboard)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (stage_id, diff, t_idx, ckey, col, row, direction, json.dumps(bb)))

        # 波次展开出怪
        waves = raw_level.get("waves", [])
        spawns = []
        start_time = 0.0
        for w in waves:
            fstart = start_time + w.get("preDelay", 0.0)
            for f in w.get("fragments", []):
                fstart += f.get("preDelay", 0.0)
                acts = [a for a in f.get("actions", []) if a.get("actionType") == "SPAWN"]
                for a in acts:
                    cnt = a.get("count", 1)
                    interval = a.get("interval", 1.0)
                    pre_delay = a.get("preDelay", 0.0)
                    key = a.get("key", "")
                    route_idx = a.get("routeIndex", 0)
                    overwritten = a.get("overwrittenData")

                    for i in range(cnt):
                        spawn_t = fstart + pre_delay + i * interval
                        spawns.append((spawn_t, key, 0, route_idx, json.dumps(overwritten) if overwritten else None))

                span = max((a.get("preDelay", 0.0) + (a.get("count", 1) - 1) * a.get("interval", 1.0) for a in acts), default=0.0)
                fstart += span
            start_time = fstart + w.get("postDelay", 0.0)

        spawns.sort(key=lambda x: x[0])
        req_enemies = set()
        for s_idx, (st_time, ekey, lvl, r_idx, ow) in enumerate(spawns):
            req_enemies.add(ekey)
            cur.execute("""
            INSERT INTO stage_spawns (stage_id, difficulty, spawn_index, enemy_id, time, level, route_index, overwritten_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (stage_id, diff, s_idx, ekey, st_time, lvl, r_idx, ow))

        # 读取 stage_table 基础参数
        s_info = stage_table.get(stage_id, {})
        life = 1 if diff == "FOUR_STAR" else 3
        if "mo01" in stage_id:
            life = 10
        cost_init = 50.0 if "mo01" in stage_id else (20.0 if ("s02" in stage_id or "tr0" in stage_id) else 10.0)
        cost_max = 99.0
        cost_time = 1.0
        deploy_limit = 8
        speed_scale = 0.5
        fps = 30
        mechanisms = ["huai_shu_li.farmland"]
        mech_config = {"huai_shu_li.farmland": {}}

        cur.execute("""
        INSERT INTO stage (
            stage_id, difficulty, code, name, map_width, map_height,
            life, cost_init, cost_max, cost_time, deploy_limit, speed_scale,
            fps, mechanisms, mech_config, required_enemies
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stage_id, diff, code, s_info.get("name", code), W, H,
            life, cost_init, cost_max, cost_time, deploy_limit, speed_scale,
            fps, json.dumps(mechanisms), json.dumps(mech_config), json.dumps(sorted(list(req_enemies)))
        ))

    conn.commit()
    conn.close()
    print(f"Stage pack build complete: {len(all_stages)} stages written to {out_db}.")

def main():
    root = pathlib.Path("data/gamedata")
    out_dir = pathlib.Path("data")

    enemy_db_path = out_dir / "enemydb_pure.sqlite"
    stage_pack_path = out_dir / "stages_act31side.sqlite"

    build_enemy_db(root, enemy_db_path)
    build_stage_pack(root, stage_pack_path)

if __name__ == "__main__":
    main()
