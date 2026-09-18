"""干员库（`data/akdb.sqlite`）的表结构。

## 这个库装什么

只装**干员**的**战斗相关**数据，不装档案、语音、时装、基建技能、养成材料。

| 源表（gamedata，`excel/` 目录，只有 GitHub 镜像有） | 内容 | 落进哪几张表 |
|---|---|---|
| `character_table.json` | 干员本体、阶段与属性关键帧、潜能、信赖、天赋、特性 | `operator` / `operator_phase` / `operator_attr` / `operator_potential` / `operator_talent` / `operator_trait` |
| `char_patch_table.json` | **升变形态**（阿米娅的近卫/医疗形态），结构与干员本体相同 | 同上（`operator.is_patch = 1`） |
| `skill_table.json` | 技能全等级、黑板、SP、持续时间、范围改写 | `skill` / `skill_level` |
| `uniequip_table.json` | 模组本体与解锁条件 | `module` |
| `battle_equip_table.json` | 模组逐级的属性与特性/天赋改写 | `module_level` |
| `range_table.json` | 攻击范围代号 → 格集合 | `attack_range` |

**唯一例外：`tile`（地块字典）。** 它不是 gamedata 来源——`excel/tile_table.json`
两个镜像都 404，关卡 JSON 只给 `tileKey` 不给名字。这份字典来自 theresa.wiki 的
地图数据接口（95 条：`tileKey` / 中文名 / 说明 / 是否功能性），取数与缓存见
`db/tiles.py`。放进来是因为它读的是**同一种东西**（关卡里的格），而不是因为同源。
它是全局表（不同活动取到的逐字节相同）但**不全**（`tile_xbdpsea` 缺失），别当全集。

## 敌人不在这里

敌人（图鉴、逐档数值、抗性、敌方技能、天赋黑板）来自 prts.wiki，存在**另一个文件**
`data/enemydb.sqlite`，结构见 `enemy_schema.py`，建库走 `python -m ak_tactic enemy build`。

两个库**完全独立**：来源不同（游戏本体 vs 站内编辑）、更新节奏不同、主键口径不同
（`char_id` vs prts.wiki 页名）、数值口径甚至**相反**（这边只存关键帧原文、那边存算好继承的
结果）。放进同一个文件只会让人以为它们同源、可以按同一套口径读，所以拆开。

## 三个口径上的事实（都踩过）

1. **职业特性（trait）不在独立表里。** `talent_table.json` 根本不存在（404），
   而 `character_table` 里也没有 `traits` 字段。特性文本是**每个干员的
   `description` 字段**（如阿米娅的"攻击造成法术伤害"）；另有 156/458 名干员
   带**结构化** `trait`（含黑板），例如怒潮凛冬的 `attack@atk_scale_2 = 0.5`
   （群体伤害系数）。两者都存：前者进 `operator.trait_text`，后者进
   `operator_trait`。
2. **属性是"关键帧 + 插值"**，不是逐级存全。多数阶段 2 帧（如精1 的 1 级与 70 级），
   中间等级靠线性插值；信赖同理（`favorKeyFrames` 的 level 是 0–50，对应**游戏内显示信赖
   0%–200%**，故 `level = trust / 2`，其中 `trust` 是 0–100 内部标度）。
   所以 `operator_attr` 存的是**关键帧原文**，不是插值结果——插值由
   `ak_tactic.operator.stats` 负责，两处不要各算一遍。
3. **模组有三道门**：`type != INITIAL`、`isSpecialEquip == False`、
   在 `battle_equip_table` 里且有等级。第二道最容易漏（特限/特勤证章
   `type` 也是 ADVANCED 且照样有数值）。本库把 `is_special_equip` 原样存下来，
   判定交给调用方，别在库层面替人决定。

表结构变动时改 `DB_VERSION` 并在 `build.py` 里加迁移说明；库文件本身可以随时
删掉重建（`python -m ak_tactic db build`）。
"""

from __future__ import annotations

#: 结构版本。改了下面的 DDL 就 +1，便于判断手上的 .sqlite 是不是旧结构。
#: v2：operator 增加 is_patch（升变形态来自 char_patch_table.json）
#: v3：敌人四表拆去独立的 data/enemydb.sqlite，本库回到纯干员
#:     （v3 与 v2 的表结构相同，改版本号是为了让手上的旧文件主动认出来）
#: v4：新增 tile（地块字典，95 条）——本库**第一张非 gamedata 来源的表**，
#:     来源是 theresa.wiki 的地图数据接口，见 db/tiles.py
#: v5（2026-09-17）：删掉 `module.description`——模组**故事**（905 行约 42 万字，
#:     麦哲伦的探险日记那类）。喂公式语料的从来是 `module_level.parts` 而非这一列，
#:     且全仓无一处读取它，故按"库只装战斗数据"删掉。守卫见 check_db 对应两项。
#: v6（2026-09-17）：新增 `stage`（关卡索引）——本库**第二张非 gamedata 来源的表**
#:     （第一张是 v4 的 tile）。来源是 map.ark-nights.com 编译进 JS bundle 的那份
#:     索引（gamedata 的 `excel/` 两个镜像都没有关卡表），见 db/stages.py。
#:     它由 `db stage-fetch` **单独建**（要联网）；`db build` 保持"不联网"的既有
#:     性质，重建时把旧库里的 stage 原样搬过去，**不会把它清空**。
#: v7（2026-09-17）：加上「关卡叫什么、属于哪一章、什么环境」。
#:     `stage` 增 4 列（name / stage_type / diff_group / hard_level_id），
#:     新增 `zone` 表（477 条章节与分部）。来源是 GitHub 镜像的
#:     `excel/stage_table.json`（3549 条）与 `excel/zone_table.json`——**同一张
#:     `db stage-fetch` 里一起取**，因为它们和关卡索引是同一件事的三面：
#:     索引给「SR-EX-8 ↔ act54side_ex08」，stage_table 给「act54side_ex08 = 虚无之顶」，
#:     zone_table 给「act54side_zone2 = 殡仪堂」。三样缺一样，选关界面就只能显示 levelId
#:     （博士明确要求不显示它）。
#:     注意两表要 **join 而不是替代**：索引 4694 条 vs stage_table 3549 条，
#:     索引独有 1346 条（生息演算等），那些 name 留空。
#:     旧库（v6）搬运时新列一律为空——**搬不搬得动都不影响已有数据**，
#:     想要名字再跑一次 `db stage-fetch` 即可。
DB_VERSION = 7

SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 出处与版本：data_version.txt 的原文、各表条数、构建时间
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 干员本体。TOKEN/TRAP（召唤物与装置）也存，用 is_operator 区分。
CREATE TABLE IF NOT EXISTS operator (
    char_id            TEXT PRIMARY KEY,
    name               TEXT NOT NULL,
    appellation        TEXT,
    rarity             INTEGER NOT NULL,
    rarity_str         TEXT,
    profession         TEXT NOT NULL,
    profession_cn      TEXT,
    sub_profession_id  TEXT,
    sub_profession_name TEXT,
    position           TEXT,
    tag_list           TEXT,
    trait_text         TEXT,
    nation_id          TEXT,
    group_id           TEXT,
    team_id            TEXT,
    display_number     TEXT,
    sort_index         INTEGER,
    is_not_obtainable  INTEGER,
    is_sp_char         INTEGER,
    max_potential_level INTEGER,
    is_operator        INTEGER NOT NULL,
    is_patch           INTEGER NOT NULL DEFAULT 0,
    raw_json           TEXT
);

-- 阶段：范围代号与阶段内最高等级
CREATE TABLE IF NOT EXISTS operator_phase (
    char_id    TEXT NOT NULL,
    phase      INTEGER NOT NULL,
    range_id   TEXT,
    max_level  INTEGER,
    prefab_key TEXT,
    PRIMARY KEY (char_id, phase)
);

-- 属性关键帧。kind='phase' 是等级关键帧，kind='trust' 是信赖关键帧。
CREATE TABLE IF NOT EXISTS operator_attr (
    char_id          TEXT NOT NULL,
    kind             TEXT NOT NULL,
    phase            INTEGER NOT NULL,
    level            INTEGER NOT NULL,
    hp               REAL,
    atk              REAL,
    def              REAL,
    res              REAL,
    cost             REAL,
    block_cnt        REAL,
    attack_speed     REAL,
    base_attack_time REAL,
    move_speed       REAL,
    respawn_time     REAL,
    hp_recovery      REAL,
    sp_recovery      REAL,
    taunt_level      REAL,
    mass_level       REAL,
    base_force_level REAL,
    max_deploy_count REAL,
    max_deck_stack   REAL,
    extra_json       TEXT,
    PRIMARY KEY (char_id, kind, phase, level)
);

-- 潜能：0 起算（潜能 1 = rank 0），逐项是属性修正器
CREATE TABLE IF NOT EXISTS operator_potential (
    char_id  TEXT NOT NULL,
    rank     INTEGER NOT NULL,
    type     TEXT,
    description TEXT,
    modifiers TEXT,
    PRIMARY KEY (char_id, rank)
);

-- 天赋：组 → 候选（同一组的候选是不同阶段/潜能的版本）
CREATE TABLE IF NOT EXISTS operator_talent (
    char_id     TEXT NOT NULL,
    group_index INTEGER NOT NULL,
    cand_index  INTEGER NOT NULL,
    prefab_key  TEXT,
    name        TEXT,
    description TEXT,
    unlock_phase INTEGER,
    unlock_level INTEGER,
    required_potential_rank INTEGER,
    range_id    TEXT,
    is_hide_talent INTEGER,
    token_key   TEXT,
    blackboard  TEXT,
    blackboard_raw TEXT,
    PRIMARY KEY (char_id, group_index, cand_index)
);

-- 结构化职业特性（只有部分干员有；没有的看 operator.trait_text）
CREATE TABLE IF NOT EXISTS operator_trait (
    char_id     TEXT NOT NULL,
    cand_index  INTEGER NOT NULL,
    unlock_phase INTEGER,
    unlock_level INTEGER,
    required_potential_rank INTEGER,
    override_description TEXT,
    prefab_key  TEXT,
    range_id    TEXT,
    blackboard  TEXT,
    PRIMARY KEY (char_id, cand_index)
);

CREATE TABLE IF NOT EXISTS operator_skill (
    char_id     TEXT NOT NULL,
    slot        INTEGER NOT NULL,
    skill_id    TEXT NOT NULL,
    unlock_phase INTEGER,
    unlock_level INTEGER,
    override_prefab_key TEXT,
    override_token_key  TEXT,
    PRIMARY KEY (char_id, slot)
);

CREATE TABLE IF NOT EXISTS skill (
    skill_id    TEXT PRIMARY KEY,
    name        TEXT,
    icon_id     TEXT,
    hidden      INTEGER,
    level_count INTEGER,
    prefab_id   TEXT
);

CREATE TABLE IF NOT EXISTS skill_level (
    skill_id     TEXT NOT NULL,
    level        INTEGER NOT NULL,
    name         TEXT,
    description  TEXT,
    skill_type   TEXT,
    duration_type TEXT,
    sp_type      TEXT,
    sp_cost      REAL,
    init_sp      REAL,
    increment    REAL,
    max_charge_time INTEGER,
    duration     REAL,
    range_id     TEXT,
    prefab_id    TEXT,
    blackboard   TEXT,
    blackboard_raw TEXT,
    PRIMARY KEY (skill_id, level)
);

CREATE TABLE IF NOT EXISTS module (
    module_id     TEXT PRIMARY KEY,
    char_id       TEXT NOT NULL,
    name          TEXT,
    type          TEXT,
    type_name1    TEXT,
    type_name2    TEXT,
    is_special_equip INTEGER,
    special_equip_desc TEXT,
    unlock_evolve_phase INTEGER,
    unlock_level  INTEGER,
    show_evolve_phase INTEGER,
    show_level    INTEGER,
    has_unlock_mission INTEGER,
    mission_count INTEGER
);

CREATE TABLE IF NOT EXISTS module_level (
    module_id   TEXT NOT NULL,
    level       INTEGER NOT NULL,
    attribute_blackboard TEXT,
    token_blackboard     TEXT,
    parts       TEXT,
    PRIMARY KEY (module_id, level)
);

CREATE TABLE IF NOT EXISTS attack_range (
    range_id  TEXT PRIMARY KEY,
    direction INTEGER,
    grid_count INTEGER,
    grids     TEXT,
    cells     TEXT
);

-- 地块字典：tileKey → 中文名与说明。
-- **不是 gamedata 来源的表之一**（另一张见下面的 stage）：gamedata 里没有地块表
-- （tile_table.json 两个镜像都 404），关卡 JSON 只给 tileKey 不给名字。来源是
-- theresa.wiki 的地图数据接口，取数与缓存见 ak_tactic/db/tiles.py。
-- 两份实测事实要跟着这张表一起记住：**它是全局表**（不同活动取到的逐字节相同），
-- 但**不全**（`tile_xbdpsea` 缺失，见 tiles.KNOWN_GAPS），所以别当全集用。
CREATE TABLE IF NOT EXISTS tile (
    tile_key      TEXT PRIMARY KEY,
    name          TEXT NOT NULL DEFAULT '',
    description   TEXT NOT NULL DEFAULT '',
    is_functional INTEGER NOT NULL DEFAULT 0
);

-- 关卡索引：levelId → 显示名（`SR-EX-8` 这种）、难度、所属区域、数据路径。
--
-- **第二张非 gamedata 来源的表**（第一张是上面的 tile）。gamedata 的 `excel/`
-- 两个镜像都没有关卡表，而活动关的显示名与 levelId 之间**没有可推导关系**
-- （`SR-EX-8` ↔ `act54side_ex08` 猜不出来），所以这份索引是换算显示名的唯一途径。
-- 来源、扒法与缓存见 ak_tactic/db/stages.py。
--
-- **主键必须是 levelId 而不是 code**：同一关卡号下还有 `#f#` 后缀的四星限定版，
-- 两者**共用同一个 code**（如 `main_00-01` 与 `main_00-01#f#` 的 code 都是 `0-1`），
-- 拿 code 当主键会直接撞掉一批。
--
-- 由 `db stage-fetch` **单独建**（要联网）；`db build` 全程不联网，重建时把旧库的
-- stage 原样搬过去，**不会清空它**——这一点与 tile 不同（tile 缺了只是少点名字，
-- 关卡表空了整个选关界面就没东西可选）。
CREATE TABLE IF NOT EXISTS stage (
    level_id      TEXT PRIMARY KEY,
    code          TEXT NOT NULL DEFAULT '',
    difficulty    TEXT NOT NULL DEFAULT 'NORMAL',
    zone_id       TEXT NOT NULL DEFAULT '',
    data_path     TEXT NOT NULL DEFAULT '',
    -- 以下四列来自 GitHub 镜像的 excel/stage_table.json（ark-nights 没有 excel/ 目录）。
    -- `name` 是**关卡中文名**（SR-EX-8 = 虚无之顶）；关卡索引本身不带名字，
    -- 而名字散在 4694 个关卡文件里，逐个拉不现实，所以从这张汇总表取。
    -- 索引独有、stage_table 没有的条目（写这段时 1346 条，生息演算那类）name 留空。
    name          TEXT NOT NULL DEFAULT '',
    stage_type    TEXT NOT NULL DEFAULT '',
    -- diff_group 是**环境分层**：EASY=剧情体验 / NORMAL=标准实战 / TOUGH=磨难险地 /
    -- ALL=通用（剧情与教学关）/ NONE=无分层。主线第 9-14 章靠它分环境，
    -- 第 0-8 章与第 15-17 章全是 NONE（后者的环境在 difficulty 上）。
    diff_group    TEXT NOT NULL DEFAULT '',
    hard_level_id TEXT NOT NULL DEFAULT ''
);

-- 章节/区域（`zone_table.json`，477 条）。**第三张非 gamedata 来源的表**。
-- **先过一道口径**（博士 2026-09-18）：`zone_table` 有 11 类，这里只留
-- MAINLINE / BRANCHLINE / CAMPAIGN / MAINLINE_ACTIVITY / ACTIVITY 五类，
-- 其余（肉鸽、爬塔、周常、导览、SIDESTORY、MAINLINE_RETRO）连同它们的关卡
-- 一并清掉，进了库的也就 350 条。判据与实清数见 `db/stages.py` 的
-- `CHAPTER_TYPES` / `prune_foreign_rows`，菜单口径见 `docs/tui-plan.md`。
-- 关卡索引只有 zone_id，没有章节名与分部名，靠这张表补：
--   第 1-14 章 type=MAINLINE，name_first 直接写着「第一章」…「第十四章」；
--   **第 15-17 章是 MAINLINE_ACTIVITY**，name_first 是英文，中文副标题在
--   name_second，章号只在 name_title（"17"）——「第十七章」得自己拼；
--   side story 的分部名也在 name_second（act54side_zone1=通学路、zone2=殡仪堂）。
CREATE TABLE IF NOT EXISTS zone (
    -- NOT NULL 不是装饰：`zone_id` 是「按字典键取值」最容易漏的一列，
    -- 漏了会写出 NULL 主键，而 SQLite 允许 PRIMARY KEY 列为 NULL，
    -- 477 行会静默地全挤在同一个 None 键上、读回来只剩 1 条。这个坑真踩过。
    zone_id    TEXT PRIMARY KEY NOT NULL,
    zone_index INTEGER,
    type       TEXT NOT NULL DEFAULT '',
    name_first  TEXT NOT NULL DEFAULT '',
    name_second TEXT NOT NULL DEFAULT '',
    name_title  TEXT NOT NULL DEFAULT '',
    name_third  TEXT NOT NULL DEFAULT '',
    -- 上面两列来自 `excel/activity_table.json` 的 zoneToActivity 与 basicInfo。
    -- **这层是「活动」不是「章节」**：一个活动可能含多个 zone（写这段时实测
    -- 103 个活动如此，如 act54side「月行水上」= act54side_zone1 通学路 +
    -- act54side_zone2 殡仪堂），选关界面因此需要「先选活动、再选分部、再选关卡」。
    -- 主线 zone（main_1 那类）查不到活动，两列留空、直接按章节名展示。
    activity_id   TEXT NOT NULL DEFAULT '',
    activity_name TEXT NOT NULL DEFAULT ''
);

CREATE INDEX IF NOT EXISTS idx_op_name      ON operator(name);
CREATE INDEX IF NOT EXISTS idx_op_prof      ON operator(profession, rarity);
CREATE INDEX IF NOT EXISTS idx_skill_name   ON skill(name);
CREATE INDEX IF NOT EXISTS idx_skilllevel   ON skill_level(skill_id, level);
CREATE INDEX IF NOT EXISTS idx_module_char  ON module(char_id);
CREATE INDEX IF NOT EXISTS idx_talent_name  ON operator_talent(name);
CREATE INDEX IF NOT EXISTS idx_opskill_char ON operator_skill(char_id, slot);
CREATE INDEX IF NOT EXISTS idx_tile_name    ON tile(name);
CREATE INDEX IF NOT EXISTS idx_stage_code   ON stage(code);
CREATE INDEX IF NOT EXISTS idx_stage_zone   ON stage(zone_id);
CREATE INDEX IF NOT EXISTS idx_stage_name   ON stage(name);
"""

#: meta 表里必须有值的键
META_KEYS = ("db_version", "built_at", "data_version", "source", "schema_note")
