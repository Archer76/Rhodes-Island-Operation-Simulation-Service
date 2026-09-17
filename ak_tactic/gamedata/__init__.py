"""游戏本体数据（gamedata）的接入层：关卡、地图、路线、敌人。

这里的数据与 prts.wiki 那套是**两回事**：prts.wiki 是玩家整理的 Wiki，适合查干员
的文字资料；而关卡的地图网格、出怪路线、敌人数值这些，只有游戏本体的解包
数据才有。theresa.wiki 的地图功能读的也正是这一套。
"""

from .enemy import LEVEL_TYPES, EnemyLibrary, EnemyStats
from .range import RANGE_TABLE_PATH, RangeGrid, RangeTable
from .source import (
    ARKNIGHTS_SITE,
    DEFAULT_BASE,
    DEFAULT_CACHE_DIR,
    GITHUB_BASE,
    GameDataSource,
    GamedataError,
    LevelEntry,
)
from .stage import (
    Checkpoint,
    EnemySpawn,
    Route,
    Stage,
    StageMap,
    StageOptions,
    Tile,
    enemy_refs,
    load_stage,
    parse_stage,
)

__all__ = [
    "ARKNIGHTS_SITE", "DEFAULT_BASE", "DEFAULT_CACHE_DIR", "GITHUB_BASE",
    "GameDataSource", "GamedataError", "LevelEntry",
    "EnemyLibrary", "EnemyStats", "LEVEL_TYPES",
    "RangeTable", "RangeGrid", "RANGE_TABLE_PATH",
    "Stage", "StageMap", "StageOptions", "Tile", "Route", "Checkpoint",
    "EnemySpawn", "load_stage", "parse_stage", "enemy_refs",
]
