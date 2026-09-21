#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：同一帧的五处干员面板读数。

## 对的是什么

`frontend/operator_view.py:212-350` 的五个方法——`current_atk` /
`current_defense` / `current_res` / `current_attack_speed` /
`current_interval` / `current_max_target` / `active_attack_type`。
它们就是 `simgo/skills.py:_profile` 造两套快照时读的那几行。

## 为什么不用起 sim 当 oracle

这几个方法**只读实例属性**，不碰引擎、不碰地图、不碰主循环。所以造一个
`types.SimpleNamespace` 替身、把**真实方法**当纯函数调即可——oracle 依旧是
原版实现。`current_interval` 内部会调 `self.current_attack_speed()`，
所以给替身补一个只返回已算好值的同名属性。

## 怎么验

网格是**有序叉乘**（`itertools.product`），不是随机抽样：6 种效果 × 替身形态
× 目标数快照 × 击杀叠层 × 阻挡 × 未阻挡攻速 × 高台 × 偷取 × 出手次数 ×
数值幅度 × 技能伤害类型，另加一张 `max_target` 派生边界小表。十七道分支
**各自记行使计数**，任何一条为 0 就判红——不是「比过一万多点」，而是
「这一万点真的走到过那十七条路」。

★ 不写「全称」结论：这是**一组叉乘**，不是对全部输入空间的穷举。

用法:
    python tools\\check_panel_go.py
    python tools\\check_panel_go.py --mutate
"""
from __future__ import annotations

import itertools
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

#: 六种效果档。`none` 是「这一帧没开技能」，与「效果全为零」是两回事。
EFFS = {
    "none": None,
    "plain": dict(buffs_atk=0.35, buffs_def=0.40, buffs_res=15.0, buffs_iv=0.0,
                  buffs_spd=0.0, damage_max=1.0, target_step=0, target_cap=0,
                  kill_atk=0.0, kill_res=0.0),
    "kill": dict(buffs_atk=0.10, buffs_def=0.0, buffs_res=5.0, buffs_iv=0.0,
                 buffs_spd=0.0, damage_max=1.0, target_step=0, target_cap=0,
                 kill_atk=0.40, kill_res=10.0),
    "multi": dict(buffs_atk=0.0, buffs_def=0.0, buffs_res=0.0, buffs_iv=0.0,
                  buffs_spd=0.0, damage_max=1.0, target_step=9, target_cap=2,
                  kill_atk=0.0, kill_res=0.0),
    "iv": dict(buffs_atk=0.0, buffs_def=0.0, buffs_res=0.0, buffs_iv=0.30,
               buffs_spd=-20.0, damage_max=1.0, target_step=0, target_cap=0,
               kill_atk=0.0, kill_res=0.0),
    "wide": dict(buffs_atk=0.60, buffs_def=0.25, buffs_res=-10.0, buffs_iv=0.10,
                 buffs_spd=30.0, damage_max=4.0, target_step=0, target_cap=0,
                 kill_atk=0.20, kill_res=3.0),
}

#: `max_target` 那条派生（`max(1, int(damage["max_target"] or 1))`）的四条边界。
#: 单独一张小表，不并进主叉乘（并进去会让行数乘四，而它要的就是这几个值）。
EDGE_MAX = [(0.0, 1), (0.5, 1), (-3.0, 1), (2.0, 2), (3.7, 3), (1.0, 1)]

AURA_ATK, AURA_DEF, MOB, STAND_ATK, STAND_IV_ADD = 0.15, 0.20, 0.12, 0.40, 0.4


def go_panel(rows: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "panel", "spec": rows}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["panel"]


def want(row: dict) -> dict:
    """把那五个真实方法当纯函数调——替身只带它们读得到的那些属性。

    效果侧**不是**替身而是真的 `SkillEffects`：`e.atk_pct` / `e.max_target`
    是**派生属性**（后者带 `max(1, int(… or 1))`），`current_interval` 还要调
    `e.attack_interval`。用替身就把这三处派生一起挡掉了，等于少验一段。
    """
    from ak_tactic.frontend.operator_view import OperatorView as V
    from ak_tactic.operator.skill import SkillEffects

    e = row["effects"]
    eff = None
    if e is not None:
        eff = SkillEffects(
            buffs={"atk": e["buffs_atk"], "def": e["buffs_def"],
                   "res": e["buffs_res"], "attack_interval": e["buffs_iv"],
                   "attack_speed": e["buffs_spd"]},
            damage={"max_target": e["damage_max"]},
            target_step=e["target_step"], target_cap=e["target_cap"],
            variants={"kill": {"atk": e["kill_atk"], "res": e["kill_res"]}},
        )
    op = types.SimpleNamespace(
        atk=row["atk"], defense=row["defense"], res=row["res"],
        attack_speed=row["attack_speed"],
        attack_interval=row["attack_interval"],
        attack_type=row["attack_type"],
        aura_atk_pct=row["aura_atk_pct"], aura_def_pct=row["aura_def_pct"],
        mobility_atk_pct=row["mobility_atk_pct"],
        stand_timer=row["stand_timer"], stand_atk_pct=row["stand_atk_pct"],
        stand_interval_add=row["stand_iv_add"],
        stand_max_target=row["stand_max_target"],
        kill_stacks=row["kill_stacks"],
        aspd_when_free=row["aspd_when_free"], blocking=row["blocking"],
        aspd_high_ground=row["aspd_high_ground"],
        high_ground_neighbor=row["high_ground_neighbor"],
        aspd_steal_bonus=row["aspd_steal_bonus"], aspd_loss=row["aspd_loss"],
        skill_active=row["skill_active"],
        skill_attack_type=row["skill_attack_type"],
        trigger_hits=row["trigger_hits"], effects=eff,
    )
    spd = V.current_attack_speed(op)
    op.current_attack_speed = lambda: spd
    return {
        "atk": V.current_atk(op),
        "defense": V.current_defense(op),
        "res": V.current_res(op),
        "attack_speed": spd,
        "interval": V.current_interval(op),
        "max_target": V.current_max_target(op),
        "attack_type": V.active_attack_type(op),
    }


def branches(row: dict) -> list[str]:
    """这一行走到过哪几条路——按**输入**判，不看实现。"""
    e, k = row["effects"], row["kill_stacks"]
    out = []
    if e is None:
        out.append("效果为空")
    else:
        out.append("效果非空")
        if e["target_step"] > 0:
            out.append("目标数递增")
        if (e["target_step"] > 0 and e["target_cap"] > 0
                and row["trigger_hits"] // e["target_step"] > e["target_cap"]):
            out.append("递增被上限夹")
        if e["damage_max"] <= 0:
            out.append("目标数原值非正")
        elif e["damage_max"] < 1:
            out.append("目标数原值分数")
        elif e["damage_max"] >= 2:
            out.append("目标数原值>=2")
    if row["stand_timer"] > 0:
        out.append("替身形态")
        if e is None and row["stand_max_target"] > 1:
            out.append("替身目标数抢先")
        if row["stand_iv_add"] != 0:
            out.append("替身间隔加算")
    if k and e is not None and (e["kill_atk"] or e["kill_res"]):
        out.append("击杀叠层")
    if row["aspd_when_free"] and not row["blocking"]:
        out.append("未阻挡攻速")
    if row["aspd_high_ground"] and row["high_ground_neighbor"]:
        out.append("高台攻速")
    if row["aspd_steal_bonus"] - row["aspd_loss"] != 0:
        out.append("偷取攻速")
    if row["stand_timer"] > 0:
        out.append("替身强制法术")
    elif row["skill_active"] and row["skill_attack_type"]:
        out.append("技能改写伤害类型")
    else:
        out.append("伤害类型回落")
    return out


def build_rows() -> list[dict]:
    rows = []
    axes = (EFFS, [0.0, 3.0], [0, 4], [0, 2], [True, False], [0.0, 8.0],
            [(0.0, True), (12.0, False), (12.0, True)],
            [(0.0, 0.0), (70.0, 25.0)], [0, 27], [0.0, 1.0],
            [(True, "MAGIC"), (False, "MAGIC"), (True, "")])
    for ename, timer, smt, kill, blocking, free, hgnb, sl, hits, scale, atype in itertools.product(*axes):
        hg, nb = hgnb
        steal, loss = sl
        act, stype = atype
        e = EFFS[ename]
        rows.append({
            "atk": 1000.0, "defense": 350.0, "res": 10.0,
            "attack_speed": 100.0, "attack_interval": 1.2,
            "attack_type": "PHYSICAL",
            "aura_atk_pct": AURA_ATK * scale,
            "aura_def_pct": AURA_DEF * scale,
            "mobility_atk_pct": MOB * scale,
            "stand_timer": timer, "stand_atk_pct": STAND_ATK * scale,
            "stand_iv_add": STAND_IV_ADD * scale, "stand_max_target": smt,
            "kill_stacks": kill,
            "aspd_when_free": free, "blocking": blocking,
            "aspd_high_ground": hg, "high_ground_neighbor": nb,
            "aspd_steal_bonus": steal, "aspd_loss": loss,
            "skill_active": act, "skill_attack_type": stype,
            "trigger_hits": hits,
            "effects": dict(e) if e is not None else None,
        })
    #: 派生边界那一小张表：把 `damage["max_target"]` 换成会分叉的那几个原值。
    for raw, _ in EDGE_MAX:
        for timer, kill in itertools.product([0.0, 3.0], [0, 2]):
            base = dict(EFFS["kill"])
            base["damage_max"] = raw
            rows.append({
                "atk": 1000.0, "defense": 350.0, "res": 10.0,
                "attack_speed": 100.0, "attack_interval": 1.2,
                "attack_type": "PHYSICAL",
                "aura_atk_pct": 0.0, "aura_def_pct": 0.0,
                "mobility_atk_pct": 0.0,
                "stand_timer": timer, "stand_atk_pct": 0.0,
                "stand_iv_add": 0.0, "stand_max_target": 0,
                "kill_stacks": kill,
                "aspd_when_free": 0.0, "blocking": True,
                "aspd_high_ground": 0.0, "high_ground_neighbor": True,
                "aspd_steal_bonus": 0.0, "aspd_loss": 0.0,
                "skill_active": False, "skill_attack_type": "",
                "trigger_hits": 0,
                "effects": base,
            })
    return rows


def main() -> int:
    rows = build_rows()
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：frontend/operator_view.py 的七个读数方法（替身对象调）")
    print()
    got = go_panel(rows)
    if len(got) != len(rows):
        raise SystemExit("Go 回了 %d 条，问了 %d 条" % (len(got), len(rows)))
    mutate = "--mutate" in sys.argv
    if mutate:
        got[0] = dict(got[0])
        got[0]["atk"] = got[0]["atk"] + 1.0

    bad = 0
    seen: dict[str, int] = {}
    for row, g in zip(rows, got):
        for b in branches(row):
            seen[b] = seen.get(b, 0) + 1
        w = want(row)
        diff = []
        for f in w:
            if f == "attack_type":
                if g[f] != w[f]:
                    diff.append((f, g[f], w[f]))
            elif f == "max_target":
                if int(g[f]) != int(w[f]):
                    diff.append((f, g[f], w[f]))
            elif abs(g[f] - w[f]) > 1e-9:
                diff.append((f, g[f], w[f]))
        if diff:
            bad += 1
            if bad <= 6:
                print("✗ eff=%s timer=%g smt=%d kill=%d blk=%s free=%g hg=%g"
                      " nb=%s steal=%g loss=%g hits=%d scale=%g act=%s type=%r"
                      % (row["effects"] and "有" or "无", row["stand_timer"],
                         row["stand_max_target"], row["kill_stacks"],
                         row["blocking"], row["aspd_when_free"],
                         row["aspd_high_ground"], row["high_ground_neighbor"],
                         row["aspd_steal_bonus"], row["aspd_loss"],
                         row["trigger_hits"],
                         row["aura_atk_pct"] / AURA_ATK if AURA_ATK else 0,
                         row["skill_active"], row["skill_attack_type"]))
                for f, a, b in diff:
                    print("    %-13s Go=%r Python=%r" % (f, a, b))
    print()
    print("已比：同一帧的七处读数（atk/defense/res/attack_speed/interval/"
          "max_target/attack_type）；叉乘 %d 行" % len(rows))
    print("★ 行使计数（十七道分支各走了多少行）：")
    for b, n in sorted(seen.items(), key=lambda kv: -kv[1]):
        print("    %-16s %d" % (b, n))
    unchecked = [b for b in (
        "效果为空", "效果非空", "目标数递增", "递增被上限夹", "替身形态",
        "替身目标数抢先", "替身间隔加算", "击杀叠层", "未阻挡攻速", "高台攻速",
        "偷取攻速", "替身强制法术", "技能改写伤害类型", "伤害类型回落",
        "目标数原值非正", "目标数原值分数", "目标数原值>=2")
        if seen.get(b, 0) == 0]
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        print("结论：叉乘没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d / %d 行逐字段一致" % (len(rows) - bad, len(rows)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
