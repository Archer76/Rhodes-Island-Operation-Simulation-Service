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

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `enemy_stats`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/敌人.json`，**不 import `ak_tactic`**。

## ★ 本套比关卡多三件麻烦事（每一件都对应一条会造假信号的路径）

**① 期望值是 dataclass 对象** ⇒ 必须先**投影**成 JSON（`py_enemy_expect`），
而不是把对象直接冻起来。投影只做形状转换，**比法的谓词一个字不改**。

**② `refs` 是 Go 的产出，同时又是查询集的来源**（问哪些敌人由 Go 决定）。
于是「现读 ≠ 冻结」有三种因，**必须分得开**：

| 因 | 归属 | 码 |
| --- | --- | --- |
| 这一关的**输入**（缓存文件内容）变了 | 调用方/数据侧 | `6` |
| **Go 的 `refs` 产出**变了（多了/少了引用） | **Go 侧** | `6` |
| 覆盖到的 ref 上**逐字段不一致** | 实现 | `1` |

压成一种读法，就会出现那条最危险的误导：**Go 改了 refs 的产出被读成「对象集变了」**。
所以输入身份记**两侧**：关卡批次（id ＋ 缓存内容 sha16）＋ 每个 ref（id, level）。

★ 顺带补一个**原来没有的守卫**：refs **少了**意味着分母缩水，而旧判据只会
「比更少的敌人」然后照样绿——现在它进对账、具名印出。

**③ `DEFAULTS`（dataclass 默认值）是 Python 侧产物** ⇒ 当**判定参数**冻住。
不冻的话，将来往 `NOT_PORTED` 加字段时，check 档会拿一份**空** `DEFAULTS` 判「非默认」，
**把每一只敌人都报成缺口**（假红）。

用法:
    python tools\\check_enemy_go.py main_00-01 main_01-07 main_02-01
    python tools\\check_enemy_go.py main_00-01 --mutate      # 反向守卫
    python tools\\freeze_baseline.py --record 敌人            # 录/重录
"""
from __future__ import annotations

import dataclasses
import json
import os
import subprocess
import sys
from pathlib import Path

_MISSING = object()
#: 字段名 → dataclass 默认值。**默认档从 Python 读、冻结档读冻的那份**
#: （判定参数，见文件头 ③）。空字典时判「非默认」一律为假——那正是要冻它的理由。
DEFAULTS: dict[str, object] = {}

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

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

    ★ 两侧都过 `norm()`：冻回来的默认值只能是 JSON 形状（`()` 会变成 `[]`），
    不归一化就会拿 `()` 与 `[]` 比 ⇒ **每一只敌人都被报成缺口**（假红）。
    """
    d = DEFAULTS.get(name, _MISSING)
    if d is _MISSING:
        return False
    return norm(v) == norm(d)


_LIB = None
_STAGES: dict[str, object] = {}


def _library():
    """`EnemyLibrary` 全表只建一次（冻结档下**根本不会建**）。"""
    global _LIB
    if _LIB is None:
        from ak_tactic.gamedata.enemy import EnemyLibrary
        _LIB = EnemyLibrary()
    return _LIB


def _stage(level: str):
    if level not in _STAGES:
        from ak_tactic.gamedata.stage import load_stage
        _STAGES[level] = load_stage(level)
    return _STAGES[level]


def py_enemy_defaults() -> dict:
    """判定参数：`EnemyStats` 每个字段的 dataclass 默认值（**Python 侧产物**）。"""
    from ak_tactic.gamedata.enemy import EnemyStats
    out: dict[str, object] = {}
    for f in dataclasses.fields(EnemyStats):
        if f.default is not dataclasses.MISSING:
            out[f.name] = norm(f.default)
        elif f.default_factory is not dataclasses.MISSING:      # type: ignore[misc]
            out[f.name] = norm(f.default_factory())
    return out


def py_enemy_expect(level: str, key: str, lv: int) -> dict:
    """期望值入口：把 Python 的 `EnemyStats` **投影**成判据要比的全部字段。

    ★ 投影只做形状转换，**不改谓词**：`core` 原样、`derived` 过 `norm`（与旧判据
    一模一样），免疫取原值（旧判据用 `bool()` 判，投影到这边照旧）。
    """
    from ak_tactic.frontend.enemy_stats import enemy_stats
    py = enemy_stats(_library().get, _stage(level), key, lv)
    return {
        "core": {gk: getattr(py, pk, None) for gk, pk in CORE},
        "immunities": {f: py.immunities.get(f) for f in IMMUNES},
        "talent_blackboard": dict(py.talent_blackboard),
        "skills": list(py.skills_raw or ()),
        "derived": {f: norm(getattr(py, f, None)) for f in DERIVED},
        #: ★ 仍未移植族也**进投影**：不进的话，将来往 `NOT_PORTED` 加字段时，
        #: 冻的那份里没有它 ⇒ `.get(f)` 得 `None` ⇒ 被判「非默认」⇒ 每只敌人都报缺口。
        #: 进了投影，加字段会改脚本内容 sha 与值条数 ⇒ `--check` 当场报「该重录」。
        "not_ported": {f: norm(getattr(py, f, None)) for f in NOT_PORTED},
    }


def main() -> int:
    G = GB.bind("敌人", __file__)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    mutate = "--mutate" in sys.argv
    levels = args or ["main_00-01"]

    #: ③ 判定参数：dataclass 默认值 ⇒ 与期望值一起冻住。
    global DEFAULTS
    DEFAULTS = G.expect(("consts", "enemy_defaults"), py_enemy_defaults)

    #: 输入身份两侧之一：调用方给的**关卡批次**（id ＋ 缓存内容 sha16）。
    batch = GB.level_inputs(DATA, levels)
    #: `record` 档返回这一批、`check` 档返回冻的那一批 —— 同一行代码，两种语义。
    batch_ref = G.expect(("query", "level_batch"), lambda: batch)
    #: ★ 声明：这份记录**真的进了判定**（下面的 `lv_same` 由它决定 ⇒ 内容变了会被
    #: 判成「输入改动」，而不是被读成「对象集变了」）。`--control` 的 P4 据此才敢开
    #: ——对**红不起来**的套开探针，等于造一条永远不响的守卫。
    G.batch_consumed()

    now_by_lv = {r["level"]: r["sha16"] for r in batch}
    ref_by_lv = {r["level"]: r["sha16"] for r in batch_ref}
    lv_same = sorted(l for l in now_by_lv if ref_by_lv.get(l) == now_by_lv[l])
    lv_changed = sorted(l for l in now_by_lv
                        if l in ref_by_lv and ref_by_lv[l] != now_by_lv[l])
    lv_new = sorted(set(now_by_lv) - set(ref_by_lv))
    lv_gone = sorted(set(ref_by_lv) - set(now_by_lv))

    #: ② refs 是 Go 的产出、又是查询集的来源。先把 Go 的答案**收齐**（每关一次调用），
    #: 再拿它去与冻的那一批对账，最后才逐字段比。
    go_cache = {l: go_enemies(l) for l in lv_same}
    live_groups = []
    for lv in lv_same:
        sha = now_by_lv[lv]
        for r in go_cache[lv]["refs"]:
            live_groups.append((lv, sha, r["id"], r["level"]))
    cov = G.coverage("enemy", live_groups)
    frozen_lv = {(r["level"], r["sha16"]) for r in batch_ref}
    #: 归属：同一个 ref 差，落在「输入变了」还是「Go 的 refs 产出变了」，
    #: 看它那一关的输入身份在不在冻的那一批里。**这两条必须能分辨**。
    go_up = [g for g in cov.extra if (g[0], g[1]) in frozen_lv]
    in_up = [g for g in cov.extra if (g[0], g[1]) not in frozen_lv]
    go_down = [g for g in cov.missing if (g[0], g[1]) in frozen_lv]
    in_down = [g for g in cov.missing if (g[0], g[1]) not in frozen_lv]
    covered = {tuple(x) for x in cov.covered}

    bad = 0
    compared = 0
    gap_fields: dict[str, list[str]] = {}
    for stage in lv_same:
        got = go_cache[stage]
        for ref in got["refs"]:
            key, lv = ref["id"], ref["level"]
            grp = (stage, now_by_lv[stage], key, lv)
            if G.mode == GB.CHECK and grp not in covered:
                #: 未覆盖的 ref **不猜**（猜＝自己写一份期望值）；它已在对账里具名。
                continue
            g = ref["stats"]
            #: ★ 期望值只能从这里来：键带**两侧输入身份**（关卡 id ＋ 内容 sha ＋ ref）。
            want = G.expect(
                ("enemy", stage, now_by_lv[stage], key, lv),
                lambda stage=stage, key=key, lv=lv: py_enemy_expect(stage, key, lv))
            compared += 1
            out = []
            for gk, pk in CORE:
                a, b = g.get(gk), want["core"][gk]
                if isinstance(a, float) and isinstance(b, float):
                    if a != b:
                        out.append("%s：Go=%r Python=%r" % (gk, a, b))
                elif a != b:
                    out.append("%s：Go=%r Python=%r" % (gk, a, b))
            for f in IMMUNES:
                a = g.get("immunities", {}).get(f)
                b = want["immunities"][f]
                if bool(a) != bool(b):
                    out.append("immunities.%s：Go=%r Python=%r" % (f, a, b))
            if g.get("talent_blackboard") != want["talent_blackboard"]:
                out.append("talent_blackboard 不一致（Go %d 键 / Python %d 键）"
                           % (len(g.get("talent_blackboard") or {}),
                              len(want["talent_blackboard"])))
            if list(g.get("skills") or []) != list(want["skills"]):
                out.append("skills 不一致（Go %d 条 / Python %d 条）"
                           % (len(g.get("skills") or []), len(want["skills"])))
            # 派生字段：**已移植的逐字段比**（这一栏才是判据）
            for f in DERIVED:
                a = norm(g.get(f))
                b = want["derived"][f]
                if a != b:
                    out.append("派生.%s：Go=%r Python=%r" % (f, _short(a), _short(b)))
            # 仍未移植族：只统计「非默认」的，具名落账
            for f in NOT_PORTED:
                if not is_default(want["not_ported"].get(f), f):
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

    #: ---- 对账：三种因分开报（② 的要害）------------------------------------
    named = (lv_changed or lv_new or lv_gone or go_up or go_down or in_up or in_down)
    if G.mode == GB.CHECK and named:
        print()
        print("输入批次对账（enemy）：这一批 %d 关 ＝ 逐关身份相同 %d；"
              "改动 %d／新增 %d／这次没问 %d"
              % (len(batch), len(lv_same), len(lv_changed), len(lv_new), len(lv_gone)))
        for tag, who in (("输入改动", lv_changed), ("输入新增", lv_new),
                         ("这次没问", lv_gone)):
            if who:
                print("  · %s（前 8 关）：%s" % (tag, "、".join(who[:8])))
        if in_up or in_down:
            print("  · 由**输入变化**引起的 ref 差：+%d / −%d"
                  "（这些 ref 的期望值随输入重算，不是 Go 的事）"
                  % (len(in_up), len(in_down)))
        if go_up or go_down:
            print("  · ★ **Go 的 refs 产出变了**：+%d / −%d"
                  % (len(go_up), len(go_down)))
            for tag, who in (("新增", go_up), ("消失", go_down)):
                for g in who[:6]:
                    print("      %s：%s@%s（关卡 %s，输入身份相同）"
                          % (tag, g[2], g[3], g[0]))
            print("    ⇒ 这两栏的**归属不同**：上面那栏是输入变了，这一栏是 **Go 侧**变了"
                  "（关卡输入逐关相同）")
        print("  ⇒ 读数**不可用**（分母不完整），基线该重录："
              "python tools\\freeze_baseline.py --record 敌人")

    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if mutate:
        print()
        print("反向守卫：本轮**期望**判红（合成一处不一致）——%s"
              % ("成立 ✓" if bad else "不成立 ✗（判据没有分辨力）"))
        return 0 if bad else 1
    print("结论：%d 只敌人逐字段一致" % (compared - bad))
    if bad:
        return 1
    if G.mode == GB.CHECK and named:
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
