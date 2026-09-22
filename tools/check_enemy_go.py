#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自读的敌人数据 vs Python 的 `EnemyLibrary`。

## 比什么、不比什么（★ 两件都要打印）

**比**：Python `EnemyStats` 暴露的核心数值与黑板/技能——
`max_hp / atk / defense / magic_resistance / move_speed / attack_speed /
base_attack_time / weight / life_point_reduce / range_radius /
hp_recovery_per_sec / level_type / immunities(11) / is_flying / apply_way /
taunt_level / name / talent_blackboard / skills`。

**不比（本轮未移植，`enemy.go` 文件头已具名）**：`enemy.py:997` 的
`derive_blackboard_fields()` 派生的**机制族**——相性 P3R、屏障、击杀费用、
重生 `reborn_*`、六个 `phit_*` 前缀、`awake_*`、`aura/passive/death`、
`skill_atk_*`。这一族**在本批敌人上非默认的条数会单独印出来**：
非 0 就是真缺口，不能因为"没比"就当它不存在。

用法:
    python tools\\check_enemy_go.py main_00-01 main_01-07 main_02-01
    python tools\\check_enemy_go.py main_00-01 --mutate      # 反向守卫
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

_MISSING = object()
#: 字段名 → dataclass 默认值（main 里填）。空字典时判「非默认」一律为假。
DEFAULTS: dict[str, object] = {}

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

#: 已比字段 → (Go 键, Python 属性)
CORE = [
    ("max_hp", "max_hp"), ("atk", "atk"), ("defense", "defense"),
    ("magic_resistance", "magic_resistance"), ("move_speed", "move_speed"),
    ("attack_speed", "attack_speed"), ("base_attack_time", "base_attack_time"),
    ("weight", "weight"), ("life_point_reduce", "life_point_reduce"),
    ("range_radius", "range_radius"), ("hp_recovery_per_sec", "hp_recovery_per_sec"),
    ("level_type", "level_type"), ("is_flying", "is_flying"),
    ("apply_way", "apply_way"), ("taunt_level", "taunt_level"), ("name", "name"),
]
IMMUNES = [
    "stunImmune", "silenceImmune", "sleepImmune", "frozenImmune",
    "levitateImmune", "fearedImmune", "palsyImmune", "attractImmune",
    "teleportImmune", "groundBoundImmune", "disarmedCombatImmune",
]

#: 由黑板/技能派生、**本轮已移植**的字段——必须逐字段比，不是只计数。
DERIVED = [
    "p3r", "weak_max", "fall_duration", "modes", "shield_hp_ratio", "kill_cost",
    "reborn_count", "reborn_duration", "reborn_hp_ratio", "reborn_prefix",
    "reborn_interval", "reborn_pollut", "reborn_def_add", "reborn_damage_magic",
    "reborn_summons",
    "skill_atk_key", "skill_atk_scale_phys", "skill_atk_scale_magic",
    "skill_atk_pollut", "skill_atk_targets", "skill_atk_cross",
    "skill_atk_ground_only", "skill_atk_no_normal", "skill_atk_interval",
    "skill_atk_init",
    # ---- 机制前缀那一族（七个前缀）----
    "passive_pollut", "passive_radius", "passive_attach_damage",
    "death_token", "death_cnt",
    "aura_hit_ratio", "aura_hit_radius",
    "speedup_move", "speedup_duration", "speedup_cooldown",
    "phit_cnt", "phit_atk", "phit_def", "phit_res", "phit_move", "phit_pollut",
    "phit_block_pollut", "phit_extra", "phit_max_stack", "phit_weight_cnt",
    "pm2_atk", "pm2_def", "pm2_res", "pm2_move", "pm2_clean_def",
    "pm2_clean_res", "pm2_clean_move", "pm2_mark_pollut", "pm2_invincible",
    "pm2_pollut_threshold",
    "awake_hp_ratio", "awake_summon_ratio", "awake_value", "awake_value_eff",
    "awake_enemy_key", "awake_summon_cnt",
]

#: **仍未移植**的字段。现在是空的——三批之后这一族已经全部接进 Go。
#: 留着这个通道：下一族出现时按名字列进来，判据会把它印出来。
NOT_PORTED: list[str] = []


def norm(v):
    """把 Python 的 tuple 摊成 list —— Go 的 JSON 里没有 tuple。

    `reborn_summons` 是 `((间隔, 个数, id), …)`，不与 Go 的 `[[…]]` 同形；
    不归一化会**每一只敌人都报不一致**，那是比法错、不是实现差。
    """
    if isinstance(v, tuple):
        return [norm(x) for x in v]
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    return v


def go_enemies(stage: str) -> dict:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "enemies", "level": stage}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    resp = json.loads(p.stdout.decode("utf-8", "replace").strip().splitlines()[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["enemies"]


def is_default(v, name: str) -> bool:
    """★ 与 **dataclass 的默认值**比，不是与 0 比。

    第一版按「非 None / 非 0 / 非空即非默认」判，于是 `reborn_hp_ratio`（默认 1.0）
    与 `aura_hit_radius`（模块常量）**在每一只敌人身上都被报成缺口**——
    那是尺子的毛病，不是敌人的。判据要跟着数据类的默认值走。
    """
    d = DEFAULTS.get(name, _MISSING)
    if d is _MISSING:
        return False
    return v == d


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    mutate = "--mutate" in sys.argv
    levels = args or ["main_00-01"]

    from ak_tactic.frontend.enemy_stats import enemy_stats
    from ak_tactic.gamedata.enemy import EnemyLibrary, EnemyStats
    from ak_tactic.gamedata.stage import load_stage
    lib = EnemyLibrary()

    #: 每个字段在 dataclass 里的默认值——「没建模」的判据要拿它比。
    global DEFAULTS
    for f in dataclasses.fields(EnemyStats):
        if f.default is not dataclasses.MISSING:
            DEFAULTS[f.name] = f.default
        elif f.default_factory is not dataclasses.MISSING:      # type: ignore[misc]
            DEFAULTS[f.name] = f.default_factory()

    bad = 0
    compared = 0
    gap_fields: dict[str, list[str]] = {}
    for stage in levels:
        got = go_enemies(stage)
        #: ★ 取数要走 Python 的**同一条路**：库里没有的 id 要先落到关卡本地定义上
        #: （`frontend/enemy_stats.py:37-55`）。直接 `lib.get(key, lv)` 会对
        #: `useDb:false` 的敌人抛 KeyError——那是**测试自己的用法错**，不是实现差。
        py_stage = load_stage(stage)
        for ref in got["refs"]:
            key, lv = ref["id"], ref["level"]
            g = ref["stats"]
            py = enemy_stats(lib.get, py_stage, key, lv)
            compared += 1
            out = []
            for gk, pk in CORE:
                a, b = g.get(gk), getattr(py, pk, None)
                if isinstance(a, float) and isinstance(b, float):
                    if a != b:
                        out.append("%s：Go=%r Python=%r" % (gk, a, b))
                elif a != b:
                    out.append("%s：Go=%r Python=%r" % (gk, a, b))
            for f in IMMUNES:
                a = g.get("immunities", {}).get(f)
                b = py.immunities.get(f)
                if bool(a) != bool(b):
                    out.append("immunities.%s：Go=%r Python=%r" % (f, a, b))
            if g.get("talent_blackboard") != dict(py.talent_blackboard):
                out.append("talent_blackboard 不一致（Go %d 键 / Python %d 键）"
                           % (len(g.get("talent_blackboard") or {}),
                              len(py.talent_blackboard)))
            if list(g.get("skills") or []) != list(py.skills_raw or ()):
                out.append("skills 不一致（Go %d 条 / Python %d 条）"
                           % (len(g.get("skills") or []), len(py.skills_raw or ())))
            # 派生字段：**已移植的逐字段比**（这一栏才是判据）
            for f in DERIVED:
                a = norm(g.get(f))
                b = norm(getattr(py, f, None))
                if a != b:
                    out.append("派生.%s：Go=%r Python=%r" % (f, _short(a), _short(b)))
            # 仍未移植族：只统计「非默认」的，具名落账
            for f in NOT_PORTED:
                if not is_default(getattr(py, f, None), f):
                    gap_fields.setdefault(f, []).append("%s@%d" % (key, lv))
            if mutate:
                out.append("__mutate__：Go.max_hp=%r" % g.get("max_hp"))
            if out:
                bad += 1
                print("✗ %s@%d —— %d 处不一致" % (key, lv, len(out)))
                for line in out[:12]:
                    print("    " + line)
        print("  %-14s 引用敌人 %d 只" % (stage, len(got["refs"])))

    print()
    print("已比字段：核心 16 ＋ 免疫 11 ＋ **派生 %d** ＋ 黑板 ＋ 技能；共 %d 只敌人"
          % (len(DERIVED), compared))
    if not NOT_PORTED:
        print("★ 未移植字段：**无** —— `derive_blackboard_fields()` 那一族已全部接入 Go")
    elif gap_fields:
        print("★ 未移植族在**本批**非默认的字段：%d 个（这是真缺口，不是「没比」）"
              % len(gap_fields))
        for f, who in sorted(gap_fields.items()):
            print("    %-24s %d 处，如 %s" % (f, len(who), who[0]))
    else:
        print("★ 未移植族在本批敌人上**全部取默认值** —— 这一批不因此失真")
    print()
    if mutate:
        print("反向守卫：本轮**期望**判红（合成一处不一致）——%s"
              % ("成立 ✓" if bad else "不成立 ✗（判据没有分辨力）"))
        return 0 if bad else 1
    print("结论：%d 只敌人逐字段一致" % (compared - bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
