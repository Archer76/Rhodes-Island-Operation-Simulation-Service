# -*- coding: utf-8 -*-
"""一个敌人的**规格视图**——`build_spec` 需要的那组字段，不需要一个活的对象。

⚠ **本文件由 `tools/gen_enemy_view.py` 从 `battle/sim.py::_build_enemy` 机械生成，
不要手改。** 改口径请改生成器再重跑，这样两边永远是同一段表达式。

## 它是干什么的

`spec.py` 原本要 `sim._build_enemy(...)` 造一个 `EnemyUnit` 才能读它的字段。
而 `EnemyUnit` 是个 **142 字段的 dataclass**——`__init__` 只存不算，真正要的只是
那份**数据**，不是那台对象（跑帧的那几百行一行都用不上）。

所以这里按同一套表达式算出同一组字段，装进一个 `SimpleNamespace`。
`spec.py::_unit_spec` 是 `getattr` 式的读法，命名空间就能喂饱它。

## 口径的边界

* `always_invincible` / `unblockable` **不在这里算**：它们是运行时由天桩机制写的
  （`sim.py:4612-4613` / `4772`），刚造出来的敌人两者都是 `False`。
  规格层需要它们为真时**自己显式写死**。
* 尾部的构造后调整（`reborn_def_base` / 屏障）**照样搬**：它们落在字段工厂的
  尾巴上，抄字段时最容易漏。
* `route_length` 是 `EnemyUnit` 的 property（`unit.py:1419`），这里照它的定义算。
"""
from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from .geometry import path_length

__all__ = ["route_length", "enemy_view"]


def route_length(route: list, legs: list) -> float:
    """路线总长。⚠ 与原版 `EnemyUnit.route_length`（`unit.py:1419`）同口径：

    有分段腿就按腿长求和，**否则**退回按折线算（`path_length`）。
    `cannot_clear` 判"自缚"（单点路线永不判漏）读的正是这个值。
    """
    if legs:
        return sum(leg.length for leg in legs)
    return path_length(route)


def enemy_view(stats: Any, *, enemy_id: str, level: int,
               route: list, legs: list, t: float, wait: float = 0.0,
               aff: dict | None = None, bk: Any = None,
               species_provider: Any = None) -> SimpleNamespace:
    """按 `_build_enemy` 的**同一套表达式**算出规格视图。"""
    e = SimpleNamespace()
    e.name = getattr(stats, 'name', enemy_id) or enemy_id
    e.enemy_id = enemy_id
    e.species = species_provider(enemy_id) if species_provider else ''
    e.level = level
    e.max_hp = float(getattr(stats, 'max_hp', 0) or 0)
    e.atk = float(getattr(stats, 'atk', 0) or 0)
    e.defense = float(getattr(stats, 'defense', 0) or 0)
    e.res = float(getattr(stats, 'magic_resistance', 0) or 0)
    e.attack_interval = float(getattr(stats, 'base_attack_time', 1.0) or 1.0)
    e.attack_type = 'PHYSICAL'
    e.weight = float(getattr(stats, 'weight', 0) or 0)
    e.move_speed = float(_ms if (_ms := getattr(stats, 'move_speed', None)) is not None else 1.0)
    e.life_cost = int(_lp if (_lp := getattr(stats, 'life_point_reduce', 1)) is not None else 1)
    e.route = route
    e.legs = legs
    e.affinity = aff
    e.modes = dict(getattr(stats, 'modes', None) or {})
    e.break_state = bk
    e.position = route[0] if route else (0.0, 0.0)
    e.spawn_time = t
    e.wait_remaining = wait
    e.is_flying = bool(getattr(stats, 'is_flying', False))
    e.apply_way = str(getattr(stats, 'apply_way', 'MELEE') or 'MELEE')
    e.attack_range = float(getattr(stats, 'range_radius', 0.0) or 0.0)
    e.kill_cost = int(getattr(stats, 'kill_cost', 0) or 0)
    e.reborn_left = int(getattr(stats, 'reborn_count', 0) or 0)
    e.reborn_delay = float(getattr(stats, 'reborn_duration', 0.0) or 0.0)
    e.reborn_hp_ratio = float(getattr(stats, 'reborn_hp_ratio', 1.0) or 1.0)
    e.reborn_interval = float(getattr(stats, 'reborn_interval', 0.0) or 0.0)
    e.reborn_pollut = float(getattr(stats, 'reborn_pollut', 0.0) or 0.0)
    e.reborn_def_add = float(getattr(stats, 'reborn_def_add', 0.0) or 0.0)
    e.reborn_damage_magic = float(getattr(stats, 'reborn_damage_magic', 0.0) or 0.0)
    e.reborn_summons = tuple(getattr(stats, 'reborn_summons', ()) or ())
    e.passive_pollut = float(getattr(stats, 'passive_pollut', 0.0) or 0.0)
    e.passive_radius = float(getattr(stats, 'passive_radius', 0.0) or 0.0)
    e.death_token = str(getattr(stats, 'death_token', '') or '')
    e.death_cnt = int(getattr(stats, 'death_cnt', 0) or 0)
    e.aura_hit_ratio = float(getattr(stats, 'aura_hit_ratio', 0.0) or 0.0)
    e.aura_hit_radius = float(getattr(stats, 'aura_hit_radius', 0.5) or 0.5)
    e.speedup_move = float(getattr(stats, 'speedup_move', 0.0) or 0.0)
    e.speedup_duration = float(getattr(stats, 'speedup_duration', 0.0) or 0.0)
    e.speedup_cooldown = float(getattr(stats, 'speedup_cooldown', 0.0) or 0.0)
    e.phit_cnt = int(getattr(stats, 'phit_cnt', 0) or 0)
    e.phit_atk = float(getattr(stats, 'phit_atk', 0.0) or 0.0)
    e.phit_def = float(getattr(stats, 'phit_def', 0.0) or 0.0)
    e.phit_res = float(getattr(stats, 'phit_res', 0.0) or 0.0)
    e.phit_move = float(getattr(stats, 'phit_move', 0.0) or 0.0)
    e.phit_pollut = float(getattr(stats, 'phit_pollut', 0.0) or 0.0)
    e.phit_block_pollut = float(getattr(stats, 'phit_block_pollut', 0.0) or 0.0)
    e.phit_extra = float(getattr(stats, 'phit_extra', 0.0) or 0.0)
    e.phit_max_stack = int(getattr(stats, 'phit_max_stack', 0) or 0)
    e.phit_weight_cnt = int(getattr(stats, 'phit_weight_cnt', 0) or 0)
    e.pm2_atk = float(getattr(stats, 'pm2_atk', 0.0) or 0.0)
    e.pm2_def = float(getattr(stats, 'pm2_def', 0.0) or 0.0)
    e.pm2_res = float(getattr(stats, 'pm2_res', 0.0) or 0.0)
    e.pm2_move = float(getattr(stats, 'pm2_move', 0.0) or 0.0)
    e.pm2_clean_def = float(getattr(stats, 'pm2_clean_def', 0.0) or 0.0)
    e.pm2_clean_res = float(getattr(stats, 'pm2_clean_res', 0.0) or 0.0)
    e.pm2_clean_move = float(getattr(stats, 'pm2_clean_move', 0.0) or 0.0)
    e.pm2_mark_pollut = float(getattr(stats, 'pm2_mark_pollut', 0.0) or 0.0)
    e.pm2_invincible = float(getattr(stats, 'pm2_invincible', 0.0) or 0.0)
    e.pm2_pollut_threshold = float(getattr(stats, 'pm2_pollut_threshold', 0.0) or 0.0)
    e.awake_hp_ratio = float(getattr(stats, 'awake_hp_ratio', 0.0) or 0.0)
    e.awake_summon_ratio = float(getattr(stats, 'awake_summon_ratio', 0.0) or 0.0)
    e.awake_value = float(getattr(stats, 'awake_value', 0.0) or 0.0)
    e.awake_value_eff = float(getattr(stats, 'awake_value_eff', 0.0) or 0.0)
    e.awake_enemy_key = str(getattr(stats, 'awake_enemy_key', '') or '')
    e.awake_summon_cnt = int(getattr(stats, 'awake_summon_cnt', 0) or 0)
    e.attach_damage = float(getattr(stats, 'passive_attach_damage', 0.0) or 0.0)
    e.taunt_level = float(getattr(stats, 'taunt_level', 0.0) or 0.0)
    e.skill_atk_key = str(getattr(stats, 'skill_atk_key', '') or '')
    e.skill_atk_scale_phys = float(getattr(stats, 'skill_atk_scale_phys', 0.0) or 0.0)
    e.skill_atk_scale_magic = float(getattr(stats, 'skill_atk_scale_magic', 0.0) or 0.0)
    e.skill_atk_pollut = float(getattr(stats, 'skill_atk_pollut', 0.0) or 0.0)
    e.skill_atk_targets = int(getattr(stats, 'skill_atk_targets', 0) or 0)
    e.skill_atk_cross = int(getattr(stats, 'skill_atk_cross', 0) or 0)
    e.skill_atk_ground_only = bool(getattr(stats, 'skill_atk_ground_only', False))
    e.skill_atk_no_normal = bool(getattr(stats, 'skill_atk_no_normal', False))
    e.skill_atk_interval = float(getattr(stats, 'skill_atk_interval', 0.0) or 0.0)
    e.skill_atk_init = float(getattr(stats, 'skill_atk_init', 0.0) or 0.0)

    # ---- 构造后调整（原版 `_build_enemy` 尾部那几行，照搬）
    #
    # ⚠ 这几行极易在"抄字段"时被跳过——它们是**算出来**的，形状与上面那 80 行不同。
    #: 防御力基准：充能加成按它重算，避免二次重生时把上次的加成再乘一遍
    e.reborn_def_base = e.defense
    #: 屏障：按最大生命折算，在血量之前被消耗
    _ratio = float(getattr(stats, "shield_hp_ratio", 0.0) or 0.0)
    e.shield = e.shield_max = (e.max_hp * _ratio) if _ratio else 0.0
    # ---- 路线长度（原版是 property，见上面 `route_length`）
    e.route_length = route_length(route, legs)
    # ---- 运行时才写的两个（新造出来时都是 False，见模块头）
    e.always_invincible = False
    e.unblockable = False
    return e
