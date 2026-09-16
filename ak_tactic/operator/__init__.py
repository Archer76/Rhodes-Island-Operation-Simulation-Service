"""干员数据：属性计算 + 技能数据 + 天赋数据。

属性来自 `excel/` 三张表（character_table / uniequip_table /
battle_equip_table），技能来自 `excel/skill_table.json`，天赋来自
`character_table.json` 的 `talents`。
这几张表**只有 GitHub 镜像提供**（ark-nights 不带 `excel/`）。
"""

from .skill import (
    LEVEL_LABELS,
    SKILL_TYPE_CN,
    SP_TYPE_CN,
    OperatorSkill,
    SkillBook,
    SkillEffects,
    SkillError,
    SkillLevel,
    format_value,
    parse_effects,
    render_description,
    resolve_index,
)
from .stats import (
    ATTR_LABELS,
    FLOAT_ATTRS,
    INT_ATTRS,
    MODULE_KEY_MAP,
    POTENTIAL_ATTR_MAP,
    OperatorCalculator,
    OperatorError,
    OperatorStats,
    interpolate_keyframes,
    parse_rarity,
)
from .talent import (
    PHASE_CN,
    PHASE_INDEX,
    Talent,
    TalentBook,
    TalentError,
    resolve_talents,
    talent_candidates,
)

__all__ = [
    # 属性
    "OperatorCalculator", "OperatorStats", "OperatorError",
    "interpolate_keyframes", "parse_rarity",
    "INT_ATTRS", "FLOAT_ATTRS", "ATTR_LABELS",
    "MODULE_KEY_MAP", "POTENTIAL_ATTR_MAP",
    # 技能
    "SkillBook", "OperatorSkill", "SkillLevel", "SkillEffects", "SkillError",
    "resolve_index", "render_description", "format_value", "parse_effects",
    "LEVEL_LABELS", "SKILL_TYPE_CN", "SP_TYPE_CN",
    # 天赋
    "TalentBook", "Talent", "TalentError", "resolve_talents",
    "talent_candidates", "PHASE_INDEX", "PHASE_CN",
]
