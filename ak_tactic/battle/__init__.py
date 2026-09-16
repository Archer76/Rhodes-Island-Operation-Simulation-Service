"""战斗模型：把「阵容 + 操作序列」推成「每个敌人何时死、我方何时倒」。

分四块：

* `damage` —— 伤害结算（物理有 5% 保底、法术没有）
* `unit`   —— 战斗单位：我方干员与沿路线推进的敌人
* `range`  —— 攻击范围与朝向旋转
* `sim`    —— 按帧推进的主循环
"""

from .damage import DamageResult, DamageType, arts, physical, resolve_damage, true_damage
from .range import RangeProvider, footprint, normalize_cells, normalize_direction, rotate_cells
from .sim import BattleResult, BattleSimulator, Deployment, SkillUse
from .unit import (
    DIRECTIONS,
    Combatant,
    EnemyUnit,
    OperatorUnit,
    path_length,
    point_at,
)

__all__ = [
    "DamageType", "DamageResult", "resolve_damage", "physical", "arts", "true_damage",
    "Combatant", "OperatorUnit", "EnemyUnit", "DIRECTIONS", "path_length", "point_at",
    "rotate_cells", "footprint", "normalize_direction", "normalize_cells",
    "RangeProvider",
    "BattleSimulator", "BattleResult", "Deployment", "SkillUse",
]
