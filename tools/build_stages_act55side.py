#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
tools/build_stages_act55side.py:
构建《时间啊，向前！》（act55side，代号 TL）TL-1 至 TL-10 普通关卡数据包：
输出到 data/stages_act55side.sqlite
"""

import json
import pathlib
import sqlite3
import sys

# 官方关卡中文名称映射（依据 gamedata stage_table.json 官方数据）
OFFICIAL_NAMES = {
    "act55side_01": "庸俗的实践",
    "act55side_02": "孑遗的道路",
    "act55side_03": "苦难的历程",
    "act55side_04": "刻板的争论",
    "act55side_05": "轰鸣的沉默",
    "act55side_06": "元音的长度",
    "act55side_07": "滚烫的双眸",
    "act55side_08": "潮湿的火焰",
    "act55side_09": "自由的黄昏",
    "act55side_10": "活着的重量",
}

STAGES_CONFIG = [
    ("act55side_01", "TL-1", "NORMAL", "level_act55side_01"),
    ("act55side_02", "TL-2", "NORMAL", "level_act55side_02"),
    ("act55side_03", "TL-3", "NORMAL", "level_act55side_03"),
    ("act55side_04", "TL-4", "NORMAL", "level_act55side_04"),
    ("act55side_05", "TL-5", "NORMAL", "level_act55side_05"),
    ("act55side_06", "TL-6", "NORMAL", "level_act55side_06"),
    ("act55side_07", "TL-7", "NORMAL", "level_act55side_07"),
    ("act55side_08", "TL-8", "NORMAL", "level_act55side_08"),
    ("act55side_09", "TL-9", "NORMAL", "level_act55side_09"),
    ("act55side_10", "TL-10", "NORMAL", "level_act55side_10"),
]


def build_stage_pack(gamedata_root: pathlib.Path, out_db: pathlib.Path):
    print(f"Building act55side stage pack: {out_db}...")
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
    stage_table = {}
    if stage_table_path.exists():
        try:
            stage_table = json.loads(stage_table_path.read_text(encoding="utf-8")).get("stages", {})
        except Exception as e:
            print(f"Warning: could not read stage_table.json: {e}", file=sys.stderr)

    cur.execute("INSERT INTO manifest VALUES ('activity_id', 'act55side')")
    cur.execute("INSERT INTO manifest VALUES ('activity_name', '时间啊，向前！')")
    cur.execute("INSERT INTO manifest VALUES ('stage_count', ?)", (str(len(STAGES_CONFIG)),))
    cur.execute("INSERT INTO manifest VALUES ('version', '1.0.0')")

    levels_dir = gamedata_root / "map.ark-nights.com" / "levels" / "activities" / "act55side"

    for stage_id, code, diff, file_prefix in STAGES_CONFIG:
        file_path = levels_dir / f"{file_prefix}.json"
        if not file_path.exists():
            raise FileNotFoundError(f"关卡 JSON 文件缺失: {file_path}")

        raw_level = json.loads(file_path.read_text(encoding="utf-8"))

        map_data = raw_level.get("mapData", {})
        map_grid = map_data.get("map", [])
        tiles_meta = map_data.get("tiles", [])
        H = len(map_grid)
        W = len(map_grid[0]) if H > 0 else 0

        # 1. 地块写入
        for row_idx, row in enumerate(map_grid):
            for col_idx, tile_idx in enumerate(row):
                tm = tiles_meta[tile_idx]
                tkey = tm.get("tileKey", "tile_road")
                btype = tm.get("buildableType", "ALL")

                # 战壕地块支持：确保战壕具备可部署地面干员的合理属性（ALL 支持地面与高台）
                if tkey == "tile_trench":
                    btype = "ALL"

                cur.execute("""
                INSERT INTO stage_tiles (stage_id, difficulty, col, row, tile_key, buildable_type)
                VALUES (?, ?, ?, ?, ?, ?)
                """, (stage_id, diff, col_idx, row_idx, tkey, btype))

        # 2. 路线写入 (路线 Y 轴在 Ark-Nights 口径中翻转: H - 1 - y)
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

        # 3. 预定义装置 (Y 翻转)
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

        # 4. 波次展开出怪
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

        # 5. 读取 options 与 stage_table 基础参数
        opt = raw_level.get("options", {})
        s_info = stage_table.get(stage_id, {})
        stage_name = s_info.get("name") or OFFICIAL_NAMES.get(stage_id, code)

        life = int(opt.get("maxLifePoint", 3))
        cost_init = float(opt.get("initialCost", 10.0))
        cost_max = float(opt.get("maxCost", 99.0))
        cost_time = float(opt.get("costIncreaseTime", 1.0))
        deploy_limit = int(opt.get("characterLimit", 8))
        speed_scale = float(opt.get("moveMultiplier", 0.5))
        fps = 30
        mechanisms = []
        mech_config = {}

        cur.execute("""
        INSERT INTO stage (
            stage_id, difficulty, code, name, map_width, map_height,
            life, cost_init, cost_max, cost_time, deploy_limit, speed_scale,
            fps, mechanisms, mech_config, required_enemies
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            stage_id, diff, code, stage_name, W, H,
            life, cost_init, cost_max, cost_time, deploy_limit, speed_scale,
            fps, json.dumps(mechanisms), json.dumps(mech_config), json.dumps(sorted(list(req_enemies)))
        ))

    conn.commit()
    conn.close()
    print(f"Act55Side stage pack build complete: {len(STAGES_CONFIG)} stages written to {out_db}.")


def main():
    root = pathlib.Path("data/gamedata")
    out_dir = pathlib.Path("data")
    out_dir.mkdir(parents=True, exist_ok=True)

    stage_pack_path = out_dir / "stages_act55side.sqlite"
    build_stage_pack(root, stage_pack_path)


if __name__ == "__main__":
    main()
