"""敌人库（`data/enemydb.sqlite`）的表结构。

与干员库（`data/akdb.sqlite`）**完全独立**：两个文件、两套结构版本、各自可单独
重建，互不引用。理由是两者处处不同——

| | 干员库 | 敌人库 |
|---|---|---|
| 来源 | 游戏本体 gamedata 的 `excel/`（只有 GitHub 镜像有） | prts.wiki 的「分类:敌人」 |
| 更新节奏 | 跟着游戏版本走 | 跟着站内编辑走 |
| 主键口径 | `char_id`（`char_002_amiya`） | PRTS 页名（`“死志的凝结”`） |
| 数值口径 | 只存**关键帧原文**，插值/信赖/潜能/模组另算 | 存**算好继承的逐档数值** |

混在一个文件里，只会让人以为它们同源、可以按同一套口径读。

## 这个库装什么

只装**战斗相关**的敌人数据：图鉴、逐档数值、抗性、敌方技能、天赋与天赋黑板。
不含头像立绘、不含关卡页的「敌方情报」覆写（那是关卡级数据，要另开一层）。

| 表 | 内容 |
|---|---|
| `enemy` | 图鉴级：页名/编号/地位级别/种类/伤害类型/攻击方式/行动方式/描述/能力/登场活动 |
| `enemy_level` | 逐档数值 + 天赋文本 + 技力槽 + 生效参数 + **黑板**（P3R 相性、倒地阈值、重生参数） |
| `enemy_resist` | 十余项 `*抗性`（眩晕/沉默/沉睡/冻结/浮空/战栗/恐惧/麻痹/诱导/传送/缚地…） |
| `enemy_skill` | 敌方技能：名称、首次冷却、周期冷却、技力消耗、效果文本 |

## 四个事实（都踩过）

1. **高档位只写被改写的字段**，其余向上一档继承（PRTS 模板靠 SMW `#ask` 做，
   本库在建库时就算好，落在 `enemy_level` 的列里）。`explicit_params` 单独留着，
   用来分辨"这一档真的改了没有"。
2. **黑板藏在 PRTS 页面的 HTML 注释里**，含 P3R 相性（`TotalAttack.*` /
   `Mode_A|B.*`）、倒地阈值与重生参数。它是**逐档**的，别只取第一档。
3. **注释掉的参数不能丢**：BOSS 页写着 `|index=1<!--|名称=死志暗影-->`，
   页面上这一档仍显示「“死志的凝结”」，而游戏数据里的名字是「死志暗影」。
   生效参数进列，注释参数进 `hidden_params`。
4. **站方勘误是两份文本，不是清洗前后**。`{{修正lite|修正后|原文=游戏内原文|原因=N}}`
   的模板说明写着「此处游戏内原文是X，因<原因>，我们对其进行了修正」——所以
   `能力` 是**游戏原文**、`能力修正` 是**站方勘误文本**，两边都留：
   `ability` = 原文，`ability_fixed` = 勘误后，`ability_errata` = 勘误原文（带标记）。
   详见 `tools/enemy_field_audit.py`。

## 抗性的两条来源，语义不同

`enemy_resist.source` 区分 `字段`（标准 `眩晕抗性=有` 那一批）与 `覆写`
（`抗性覆写={{异常效果|眩晕|免疫}}`）。**`覆写` 压过同名的 `字段`**，
`is_effective` 已经把胜负算好，直接用 `is_effective=1` 即可。
活例是「蔓德拉」：字段全写「无」，覆写写七项免疫，只读字段会把她记成什么都不免疫。

结构变动时改 `ENEMY_DB_VERSION`；库文件本身随时可删可重建
（`python -m ak_tactic enemydb build`）。
"""

from __future__ import annotations

#: 结构版本。改了下面的 DDL 就 +1。
#: v1：enemy / enemy_level / enemy_resist / enemy_skill 四表，来源 prts.wiki
#: v2（2026-09-16 字段审计后）：
#:   * enemy 增 `ability_fixed` / `ability_errata`——站方勘误与游戏原文是两份文本；
#:   * enemy_level 增 `description_fixed`——档位描述的内联勘误（6 档有）；
#:   * enemy_resist 增 `source` / `is_effective`，主键并入 `source`——
#:     `抗性覆写` 压过 `*抗性` 字段，同名条目必须能并存。
ENEMY_DB_VERSION = 2

ENEMY_SCHEMA_SQL = """
PRAGMA foreign_keys = ON;

-- 出处与版本：来源、页数、构建时间
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- 图鉴级。**页名做主键**：敌人的中文名会撞车
-- （「“阿米娅”」与「阿米娅」是两回事），页名才是唯一的。
CREATE TABLE IF NOT EXISTS enemy (
    page         TEXT PRIMARY KEY,   -- PRTS 页名
    prts_id      INTEGER,            -- 模板 |id=
    name         TEXT NOT NULL,      -- |名称=
    display_name TEXT,               -- |显示名=
    index_code   TEXT,               -- 图鉴编号，如 B1 / SD13；空 = 不具有图鉴
    grade        TEXT,               -- 地位级别：普通 / 精英 / 领袖
    category     TEXT,               -- 种类，如"感染生物"
    damage_type  TEXT,               -- 伤害类型
    attack_way   TEXT,               -- 攻击方式：近战 / 远程 / 不攻击
    move_way     TEXT,               -- 行动方式：地面 / 飞行
    camp         TEXT,               -- 阵营
    description  TEXT,
    ability      TEXT,               -- 图鉴「能力」一栏，**游戏内原文**
    ability_fixed TEXT,              -- 同上，**站方勘误后**（展开 修正lite；空=无勘误）
    ability_errata TEXT,             -- 勘误原文（带 修正lite 标记），留作追溯
    debut_event  TEXT,               -- 登场活动
    is_irregular INTEGER NOT NULL DEFAULT 0,  -- 非常规敌人
    has_handbook INTEGER NOT NULL DEFAULT 0,  -- 有 index 才算有图鉴
    level_count  INTEGER NOT NULL DEFAULT 0,
    raw_wikitext TEXT
);

-- 逐档数值。列里的值**已经算好继承**（本档没写的字段取自上一档），
-- 这一点与干员库的"只存关键帧原文"不同——PRTS 页面里没有
-- "显式/继承"的标志位，只有"写了/没写"，继承由模板的 SMW 查询完成。
CREATE TABLE IF NOT EXISTS enemy_level (
    page        TEXT NOT NULL,
    level       INTEGER NOT NULL,
    name        TEXT, grade TEXT, category TEXT, description TEXT,
    description_fixed TEXT,   -- 档位描述里内联勘误展开后的正文（空 = 该档无勘误）
    attack_way  TEXT, move_way TEXT,
    target_value REAL,      -- 模板里的「数量」，语义是漏掉扣几点关卡生命
    range_radius REAL,      -- 空 = 近战（半径 0），不是"没有数据"
    hp REAL, atk REAL, defense REAL, res REAL,
    move_speed REAL, attack_speed REAL, base_attack_time REAL,
    hp_recovery REAL, sp_recovery REAL, weight REAL,
    damage_resistance REAL, element_resistance REAL, taunt_level REAL,
    talent      TEXT,       -- |天赋= 的原文（带 wikitext 标记）
    init_sp REAL, max_sp REAL,
    sp_recovery_type TEXT, sp_recovery_value REAL,
    params          TEXT,   -- 生效参数（本档 + 继承），原文 JSON
    explicit_params TEXT,   -- 本档**显式**写出的参数
    hidden_params   TEXT,   -- 被 HTML 注释掉的参数（页面上不显示，往往是游戏真值）
    blackboard      TEXT,   -- 拍平的黑板 {键: 值}
    blackboard_raw  TEXT,   -- 黑板原文
    PRIMARY KEY (page, level)
);

-- 抗性。以 `抗性` 结尾的参数一律收进来（不写死名单，PRTS 加一项这里自动跟上）
-- `source` 两种取值语义不同：`字段` 是标准 `*抗性` 参数，`覆写` 来自 `抗性覆写`
-- （`{{异常效果|失衡免疫}}` 这种写法能表达标准字段表里根本没有的免疫项）。
-- **`覆写` 压过同名的 `字段`**——主键并入 source 就是为了让两者并存而不互相顶掉。
-- `is_effective` 已把胜负算好：直接用 `is_effective=1` 就是该敌人的真实抗性。
CREATE TABLE IF NOT EXISTS enemy_resist (
    page      TEXT NOT NULL,
    level     INTEGER NOT NULL,
    name      TEXT NOT NULL,          -- 如 眩晕抗性
    value     TEXT,                   -- 原文：有 / 无 / 免疫
    is_immune INTEGER NOT NULL DEFAULT 0,
    source    TEXT NOT NULL DEFAULT '字段',
    is_effective INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (page, level, name, source)
);

-- 敌方技能。注意字段口径：init_cooldown 是**首次就绪的冷却**，cooldown 是
-- **之后每次就绪的冷却**，sp_cost 才是技力消耗——别按"初始技力"理解。
CREATE TABLE IF NOT EXISTS enemy_skill (
    page     TEXT NOT NULL,
    level    INTEGER NOT NULL,
    slot     INTEGER NOT NULL,
    name     TEXT,
    init_cooldown REAL,
    cooldown      REAL,
    sp_cost       REAL,
    kind     TEXT,
    effect   TEXT,
    PRIMARY KEY (page, level, slot)
);

CREATE INDEX IF NOT EXISTS idx_enemy_name   ON enemy(name);
CREATE INDEX IF NOT EXISTS idx_enemy_index  ON enemy(index_code);
CREATE INDEX IF NOT EXISTS idx_enemy_grade  ON enemy(grade);
CREATE INDEX IF NOT EXISTS idx_enemylvl     ON enemy_level(page, level);
CREATE INDEX IF NOT EXISTS idx_resist_kind  ON enemy_resist(name, is_immune);
CREATE INDEX IF NOT EXISTS idx_resist_live  ON enemy_resist(page, level, is_effective);
CREATE INDEX IF NOT EXISTS idx_enemyskill   ON enemy_skill(page, level, slot);
"""

#: meta 表里必须有值的键
ENEMY_META_KEYS = ("db_version", "built_at", "enemy_source", "schema_note")
