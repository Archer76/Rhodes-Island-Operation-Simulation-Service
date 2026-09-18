"""把一场排好的战斗序列化成 `rios-sim` 的规格。

## 最小版本覆盖到哪里

**常规关卡**：出怪、推进（含分段计划）、阻挡、我方平A、敌方平A、费用与漏怪。
**不覆盖**（出现就在 `unsupported` 里逐条写明，Go 侧拒跑）：技能（含自动开）、
召唤物、装置、撤退、位移（推/拉）、硬控（晕眩/冻结/束缚/停顿/待机/缴械）、
持续伤害、场地机制、重生与相性、嘲讽等级之外的仇恨规则、闪避、无敌、溅射与连击。

为什么不"顺手多支持一点"：每多一条没对拍过的机制，对拍台就多一分把 bug 固化成
基线的风险——**缺了机制的"对齐"比"没实现"更坏**。所以先让这一版在一批
常规关卡上逐项对齐，再一条条往里加，每加一条补一组对拍用例。

## 数值从哪来

干员的攻击力/防御/法抗/攻击间隔**取无技能帧的值**（`current_atk()` 那一族在
`effects is None` 时的分支）。所以 `unsupported` 里必须挡住一切能改变它们的
东西：技能（被动也不行——被动技能同样会写 `effects`）、全场光环、增益光环、
积雪、天赋攻速……挡住的方式是**直接读那些字段**，而不是"我以为没有"。
"""

from __future__ import annotations

from typing import Any

#: 攻击间隔的下限与攻速下限，与 `battle/unit.py` 同源（那里写死 0.05 / 20）
MIN_INTERVAL = 0.05
ASPD_MIN = 20.0


def unsupported_reasons(sim, *, allow_devices: bool = False,
                        allow_skills: bool = False) -> list[str]:
    """这一局用到了最小版本没覆盖的机制吗？逐条给理由。

    宁可多报几条（那几个字段本来是空列表也是零成本），也不要漏报：漏报的症状是
    "对拍通过了，但两边算的根本不是同一场战斗"。

    `allow_devices` / `allow_skills` 是**给对拍台用的、必须带着证据打开**的两个口子：

    * `allow_devices` —— 只有对拍台**实测过**"把装置摘掉结果一字不变"时才传 True；
    * `allow_skills` —— 只有原版那一趟的 `skill_activations == 0`（从头到尾没开过
      技能，于是"无技能帧的数值"就是全场的数值）时才传 True。
    """
    bad: list[str] = []
    if sim.skill_uses:
        bad.append(f"手动开技能 ×{len(sim.skill_uses)}")
    if sim.summon_deployments:
        bad.append(f"召唤物部署 ×{len(sim.summon_deployments)}")
    if sim.device_deployments:
        bad.append(f"装置部署 ×{len(sim.device_deployments)}")
    if sim.retreats:
        bad.append(f"撤退 ×{len(sim.retreats)}")
    if getattr(sim, "team_auras", None):
        bad.append(f"全场光环 ×{len(sim.team_auras)}")
    if getattr(sim, "regen_auras", None):
        bad.append(f"增益治疗光环 ×{len(sim.regen_auras)}")
    if getattr(sim, "snow_fields", None):
        bad.append(f"积雪 ×{len(sim.snow_fields)}")
    if getattr(sim, "farmland", None) is not None:
        bad.append("场地机制（田地/病害值）")
    if getattr(sim, "_devices", None) and not allow_devices:
        bad.append(f"关卡装置 ×{len(sim._devices)}")
    if getattr(sim, "total_attack", None) is not None:
        bad.append("全场总攻击装置")

    for d in sim.deployments:
        op = d.operator
        # `Deployment.skill` 的默认值是 **0**（＝不带技能），所以这里判的是真值
        # 而不是 `is not None`——写成后者会把整批"本来就没技能"的用例全挡在门外。
        if getattr(op, "skill", None) is not None and not allow_skills:
            bad.append(f"技能：{op.name or op.char_id}")
        if getattr(d, "skill", 0) and not allow_skills:
            bad.append(f"部署夹带技能：{op.name or op.char_id}")
        for attr, why in (("summon_of", "召唤物"),
                          ("splash_radius", "特性溅射"),
                          ("highland_splash_scale", "高台溅射"),
                          ("hammer", "锤击"),
                          ("effects_override", "技能效果覆盖")):
            val = getattr(op, attr, 0)
            if val:
                bad.append(f"{why}：{op.name or op.char_id}")
        for attr, why in (("dodge_phys", "物理闪避"), ("dodge_arts", "法术闪避"),
                          ("aura_atk_pct", "攻击力光环"), ("aura_def_pct", "防御光环"),
                          ("blessing_save", "免死"), ("weakness_damage", "弱点伤害"),
                          ("aspd_when_free", "天赋攻速"), ("aspd_high_ground", "天赋攻速")):
            val = getattr(op, attr, 0)
            if val:
                bad.append(f"{why}：{op.name or op.char_id}")
        if getattr(op, "heals", False):
            bad.append(f"医疗（平A 是治疗）：{op.name or op.char_id}")
    # 去重但保序：同一个人有两条问题时只报一条，方便读
    seen: set[str] = set()
    out: list[str] = []
    for item in bad:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _operator_spec(sim, d) -> dict[str, Any]:
    """一名干员的规格。数值取**无技能帧**的那一套。

    ⚠️ `_range_of()` 读的是 `op.position` / `op.direction`，而这两个字段要等
    `_do_deploy` 才写上。规格是在**跑之前**生成的，所以这里先把它们按这次部署
    填进去（值与模拟器随后要填的完全一样）——不填的话，算出来的是一张以 (0,0)
    为原点的范围表，而且**不会报错**，只会让两边的覆盖格悄悄不同。
    """
    op = d.operator
    op.position = (int(d.position[0]), int(d.position[1]))
    op.direction = d.direction
    spd = float(getattr(op, "attack_speed", 100.0) or 100.0)
    interval = max(MIN_INTERVAL, float(op.attack_interval) * 100.0 / max(ASPD_MIN, spd))
    cells = sim._range_of(op)
    return {
        "char_id": op.char_id,
        "name": op.name or op.char_id,
        "cell": [int(d.position[0]), int(d.position[1])],
        "max_hp": float(op.max_hp),
        "atk": float(op.current_atk()),
        "def": float(op.current_defense()),
        "res": float(op.current_res()),
        "interval": interval,
        "damage_type": str(op.attack_type),
        "block_cnt": int(op.block_cnt),
        "deploy_cost": int(op.deploy_cost),
        "redeploy_time": float(getattr(op, "redeploy_time", 70.0) or 70.0),
        "range": sorted([int(x), int(y)] for x, y in cells),
    }


def _legs_spec(legs) -> list[dict[str, Any]]:
    out = []
    for leg in legs or []:
        item: dict[str, Any] = {"kind": str(leg.kind)}
        if leg.kind == "walk":
            item["points"] = [[float(x), float(y)] for x, y in (leg.points or [])]
            item["length"] = float(leg.length)
        else:
            item["seconds"] = float(getattr(leg, "seconds", 0.0) or 0.0)
        out.append(item)
    return out


def _spawn_spec(sim, t: float, sp) -> dict[str, Any]:
    """一个敌人的规格。

    这里调的是 `sim._spawn()`——**和原版那条路是同一个函数**，所以路线分段、
    关卡乘区、难度档位这些不必再实现第二遍。它只建对象、不改模拟器状态。
    """
    e = sim._spawn(sp.enemy_id, sp.level, sp.route_index, float(t))
    return {
        "time": float(t),
        "name": e.name,
        "enemy_id": e.enemy_id,
        "level": int(e.level),
        "hp": float(e.max_hp),
        "atk": float(e.atk),
        "def": float(e.defense),
        "res": float(e.res),
        "move_speed": float(e.move_speed),
        "interval": float(e.attack_interval),
        "damage_type": str(getattr(e, "attack_type", "PHYSICAL")),
        "attack_range": float(getattr(e, "attack_range", 0.0) or 0.0),
        "apply_way": str(getattr(e, "apply_way", "MELEE") or "MELEE"),
        "attack_times": int(getattr(e, "attack_times", 1) or 1),
        "is_flying": bool(getattr(e, "is_flying", False)),
        "unblockable": bool(getattr(e, "unblockable", False)),
        "taunt_level": int(getattr(e, "taunt_level", 0) or 0),
        "life_cost": int(e.life_cost),
        "kill_cost": int(getattr(e, "kill_cost", 0) or 0),
        "cannot_clear": bool(sim._cannot_clear(e)),
        "legs": _legs_spec(e.legs),
    }


def build_spec(sim, *, stage_label: str = "", allow_devices: bool = False,
               allow_skills: bool = False) -> dict[str, Any]:
    """`BattleSimulator` → 规格 dict。**调用前要先把 plan 排好。**

    只读 `sim` 的状态（`_spawn` 与 `_range_of` 都是纯读；后者要先补 position——
    见 `_operator_spec` 的说明），不改战斗状态。`allow_*` 见 `unsupported_reasons`。
    """
    operators: list[dict[str, Any]] = []
    deploys: list[dict[str, Any]] = []
    for d in sorted(sim.deployments, key=lambda d: d.time):
        operators.append(_operator_spec(sim, d))
        deploys.append({
            "time": float(d.time),
            "index": len(operators) - 1,
            "char_id": d.operator.char_id,
            "cost": int(d.operator.deploy_cost),
        })
    spawns = [_spawn_spec(sim, t, sp) for t, sp in sim._spawns]
    return {
        "stage": stage_label or str(getattr(sim.stage, "code", "") or ""),
        "fps": int(sim.fps),
        "max_time": 600.0,
        "life": int(sim.life),
        "cost_init": float(sim.cost),
        "cost_max": float(sim.max_cost),
        "cost_time": float(sim.cost_time),
        "enemy_windup": float(sim.enemy_windup),
        "ranged_enemies": bool(sim.ranged_enemies),
        "speed_scale": float(sim.speed_scale),
        "operators": operators,
        "deploys": deploys,
        "spawns": spawns,
        "unsupported": unsupported_reasons(
            sim, allow_devices=allow_devices, allow_skills=allow_skills),
    }
