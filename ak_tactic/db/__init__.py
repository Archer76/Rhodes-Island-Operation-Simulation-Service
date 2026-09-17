"""本地战斗数据库：**两个独立文件**，各建各的、各查各的。

| | 干员库 | 敌人库 |
|---|---|---|
| 文件 | `data/akdb.sqlite` | `data/enemydb.sqlite` |
| 来源 | 游戏本体 gamedata 的 `excel/` | prts.wiki 的「分类:敌人」 |
| 主键 | `char_id` | prts.wiki 页名 |
| 数值口径 | 只存**关键帧原文**，面板另算 | 存**算好继承的逐档数值** |
| 建库 | `python -m ak_tactic db build` | `python -m ak_tactic enemy build` |
| 自检 | `tools/check_db.py` | `tools/check_enemy_db.py` |

```python
from ak_tactic.db import build_db, connect, char_detail          # 干员
from ak_tactic.db import build_enemy_db, connect_enemy, enemy_detail  # 敌人

build_db()
char_detail(connect(), "阿米娅")

build_enemy_db()
enemy_detail(connect_enemy(), "源石虫")
```

只装**战斗相关**数据（干员：属性/潜能/信赖/天赋/特性/技能/模组/范围；
敌人：图鉴/逐档数值/抗性/技能/天赋黑板），不含档案、语音、时装、基建技能与养成材料。
两个库各自的口径说明见 `schema.py` 与 `enemy_schema.py` 顶部。
"""

from .api import (
    DB_SCHEMA_DOC,
    DatabaseMissing,
    char_detail,
    connect,
    db_info,
    find_operators,
    run_sql,
    search_skills,
    search_talents,
    skill_levels,
)
from .build import DEFAULT_DB_PATH, BuildReport, build_db
from .enemy_api import (
    ENEMY_DB_SCHEMA_DOC,
    connect_enemy,
    effective_resists,
    enemy_db_info,
    enemy_detail,
    enemy_sql,
    find_enemies,
)
from .enemy_build import (
    DEFAULT_ENEMY_DB_PATH,
    ENEMY_SOURCE,
    EnemyBuildReport,
    build_enemy_db,
)
from .enemy_schema import ENEMY_DB_VERSION, ENEMY_SCHEMA_SQL
from .schema import DB_VERSION, SCHEMA_SQL
from .store import DatabaseMissing as _DbMissing  # noqa: F401  (同一个类，勿重复定义)

__all__ = [
    # 干员库
    "build_db", "BuildReport", "DEFAULT_DB_PATH", "DB_VERSION", "SCHEMA_SQL",
    "connect", "DatabaseMissing", "db_info", "find_operators", "char_detail",
    "skill_levels", "search_skills", "search_talents", "run_sql",
    "DB_SCHEMA_DOC",
    # 敌人库
    "build_enemy_db", "EnemyBuildReport", "DEFAULT_ENEMY_DB_PATH",
    "ENEMY_DB_VERSION", "ENEMY_SCHEMA_SQL", "ENEMY_SOURCE",
    "connect_enemy", "enemy_db_info", "find_enemies", "enemy_detail",
    "enemy_sql", "ENEMY_DB_SCHEMA_DOC", "effective_resists",
]
