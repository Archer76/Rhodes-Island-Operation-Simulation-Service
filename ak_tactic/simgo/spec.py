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

from collections.abc import Iterable
from typing import Any

from . import mech, skills

#: 攻击间隔的下限与攻速下限，与 `battle/unit.py` 同源（那里写死 0.05 / 20）
MIN_INTERVAL = 0.05
ASPD_MIN = 20.0


def _attach_skill_for_spec(d, *, allow_skills: bool = True) -> str | None:
    """照 `sim._attach_skill` 的分支，把这次部署的技能挂到干员身上。

    原版是在**部署那一刻**挂技能的，规则三条：

    * `d.skill` 是**槽位号**（1/2/3）→ 查 `skill_book`（跑起来才查得到）；
    * `d.skill` 是现成的 `SkillLevel` → 直接挂上；
    * `d.skill` 是 **0 或 None → 把 `op.skill` 清成 None**。

    第三条最坑：先给干员绑好技能、再摆一条默认的 `Deployment`（`skill=0`），
    跑起来技能是**没有**的——而生成规格发生在跑之前，那里还看得见它，
    于是"规格里带着技能、那一趟却没开"这种不对称的对拍会以**别的字段**的
    形态爆出来（实测就是这样：Go 开了技能、原版一次没开，两边 elapsed 差 18 秒）。

    返回非 None 表示这次部署的技能**现在确定不了**（槽位号那条路），
    调用方据此拒跑。副作用只有 `op.skill` 一个字段，而且写的就是原版将要写的内容。
    """
    op = d.operator
    spec = getattr(d, "skill", 0)
    if spec is None or (isinstance(spec, int) and spec == 0):
        op.skill = None
        return None
    if isinstance(spec, int):
        return (f"技能槽号 {spec}（{op.name or op.char_id}）："
                f"调用方要先把 SkillLevel 绑好再生成规格")
    op.skill = spec
    return None


def unsupported_reasons(sim, *, allow_devices: bool = False,
                        allow_skills: bool = False) -> list[str]:
    """这一局用到了最小版本没覆盖的机制吗？逐条给理由。

    宁可多报几条（那几个字段本来是空列表也是零成本），也不要漏报：漏报的症状是
    "对拍通过了，但两边算的根本不是同一场战斗"。

    `allow_devices` / `allow_skills` 是**给对拍台用的、必须带着证据打开**的两个口子：

    * `allow_devices` —— 只有对拍台**实测过**"把装置摘掉结果一字不变"时才传 True；
    * `allow_skills` —— 打开之后，技能**逐条走 `simgo.skills` 的白名单**：
      落在已移植子集里的放行，其余逐条写明理由（理由的粒度是
      "谁 + 哪一项"，方便直接看出该补哪一块）。关着的时候一律拒跑——
      搜索那条路在技能对拍全绿之前不会打开它。
    """
    bad: list[str] = []
    if sim.skill_uses:
        pass          # 手动开技能现在**支持**（白名单判定在下面逐人做）
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
    bad += _enemy_reasons(sim)
    if getattr(sim, "farmland", None) is not None:
        # 田地本身**已接线**（Go 的 `mech/huai_shu_li.go`）：几何与参数随规格送过去，
        # 时间由 Go 跑。所以这里不再一刀切拒跑，改成按**这一关实际用到的东西**逐条判
        # ——没接线的部分（敌人侧污染、天桩链、拆阀还原）由 `mech.port_reasons` 报。
        bad += mech.port_reasons(sim)
    if getattr(sim, "_devices", None) and not allow_devices:
        bad.append(f"关卡装置 ×{len(sim._devices)}")
    if getattr(sim, "total_attack", None) is not None:
        bad.append("全场总攻击装置")

    for d in sim.deployments:
        op = d.operator
        # 先按原版的分支把技能挂好（`Deployment.skill` 的默认值是 **0**，
        # 而它会把干员身上已绑的技能清掉——这一步不做，规格与那一趟就会不一致）
        stuck = _attach_skill_for_spec(d)
        if stuck:
            bad.append(stuck)
        elif getattr(op, "skill", None) is not None:
            if allow_skills:
                bad += [f"{op.name or op.char_id}：{r}"
                        for r in skills.port_reasons(sim, op)]
            else:
                bad.append(f"技能：{op.name or op.char_id}")
        for attr, why in (("summon_of", "召唤物"),
                          ("splash_radius", "特性溅射"),
                          ("highland_splash_scale", "高台溅射"),
                          ("hammer", "锤击"),
                          ("effects_override", "技能效果覆盖"),
                          ("power_attack_count", "天赋「强击瓶专家」"),
                          ("sp_per_attack_talent", "天赋回技力（出手）"),
                          ("sp_per_kill_talent", "天赋回技力（击杀）")):
            val = getattr(op, attr, 0)
            if val:
                bad.append(f"{why}：{op.name or op.char_id}")
        # `combo_hits` 的"没有这条"是 **1**（不是 0）：原版判的是 `> 1`。
        # 按真值判会把**每一位没有连击的干员**全挡在门外——实测阿米娅就中招。
        if int(getattr(op, "combo_hits", 1) or 1) > 1:
            bad.append(f"普攻连击（结算后缩放）：{op.name or op.char_id}")
        for attr, why in (("dodge_phys", "物理闪避"), ("dodge_arts", "法术闪避"),
                          ("aura_atk_pct", "攻击力光环"), ("aura_def_pct", "防御光环"),
                          ("blessing_save", "免死"), ("weakness_damage", "弱点伤害"),
                          ("aspd_when_free", "天赋攻速"), ("aspd_high_ground", "天赋攻速")):
            val = getattr(op, attr, 0)
            if val:
                bad.append(f"{why}：{op.name or op.char_id}")
        if getattr(op, "heals", False):
            bad.append(f"医疗（平A 是治疗）：{op.name or op.char_id}")
        # 天赋里那两条**会改数值但不落在干员字段上**的：回技力与「翔虫机动」。
        # 它们只在跑起来之后才写进 `op`，所以只能按天赋本身判。
        if _talent_reason(op, "find_sp_on_action"):
            bad.append(f"天赋回技力：{op.name or op.char_id}")
        if _talent_reason(op, "find_glider_mobility"):
            bad.append(f"天赋「翔虫机动」：{op.name or op.char_id}")
    # 去重但保序：同一个人有两条问题时只报一条，方便读
    seen: set[str] = set()
    out: list[str] = []
    for item in bad:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def _enemy_reasons(sim) -> list[str]:
    """敌人侧：Go 侧还没建模的敌人行为，逐条给理由。

    **字段驱动**：照着 `EnemyUnit` 的字段列（每个字段在 `sim.py` 里都有一个消费点），
    字段非零就说明那一段代码这一局会跑。判据不看名字、不看描述关键词。

    这一条闸门是补上来的：在此之前，"敌人有技能出手 / 会重生 / 会换形态"这种关
    会被原样交给 Go——而 Go 那边这些行为**一行都没有**，判决却照样给出来。
    那正是"对拍通过但两边算的不是同一场战斗"。
    """
    bad: list[str] = []
    field_why = {
        "phit_pollut": "蜕皮被动",
        "phit_block_pollut": "蜕皮被动（被阻挡时）",
        "reborn_pollut": "重生吸病害值",
        "pm2_mark_pollut": "明识形态",
        "awake_value": "按田地病害值觉醒",
        "hp_drain_per_sec": "持续自伤",
    }
    #: `skill_atk_*`（敌方技能出手「污」）与 `passive_pollut`（被击倒污染田地）
    #: **都已经接线**，所以不在这张表里：
    #:  * 技能出手 → Go 侧的 `AttackTick`（帧序 7.2，`sim.py:3468`）；
    #:  * 被击倒污染 → Go 侧的 `PostAttack`（帧序 7.5，`sim.py:3891`）。
    #: 两条黑板数值都随敌人规格送过去（`_spawn_spec`）。
    #: 它们曾经都在表里，那是对的：没接线的时候放行，等于让 Go 少算一层却照样给判决。
    names: dict[str, set[str]] = {}
    for e in mech._spawns_of(sim):
        for attr, why in field_why.items():
            if getattr(e, attr, 0):
                names.setdefault(why, set()).add(e.name)
        for attr, why in mech.ENEMY_BEHAVIOR_ATTRS.items():
            if getattr(e, attr, None):
                names.setdefault(why, set()).add(e.name)
        # 「被击倒给可部署装置」的额度**只在计划里真放装置时才起作用**：不给额度，
        # `_do_deploy_device` 会拒放；给不给额度本身不改判决（原版把它记进
        # `res.device_tokens`，那是记录不是效果）。而"计划里有没有放装置"由
        # `device_deployments` 那一条独立判——所以这里只在放装置时才报，
        # 否则会把"敌人会掉装置"这个**没有后果**的事实，报成不能跑的理由。
        if getattr(e, "death_cnt", 0) and getattr(e, "death_token", None) \
                and getattr(sim, "device_deployments", None):
            names.setdefault("被击倒给可部署装置", set()).add(e.name)
    for why, who in names.items():
        bad.append(f"{why}：{'/'.join(sorted(who))}")
    return bad


def _talent_reason(op, finder: str) -> bool:
    """这名干员身上有没有 `finder` 认得出的那条天赋。

    取不到天赋模块（比如只装了数据、没装战斗层）就当**没有**——这条判据的
    作用是"别漏报"，而漏报的前提是先得有天赋。
    """
    talents = getattr(op, "talents", None)
    if not talents:
        return False
    try:
        from ..battle import talents as _talents
    except Exception:                                          # noqa: BLE001
        return False
    fn = getattr(_talents, finder, None)
    if fn is None:
        return False
    try:
        return fn(talents) is not None
    except Exception:                                          # noqa: BLE001
        return True          # 判不了就当有：宁可拒跑


def _talent_dodge(op: Any, d: Any) -> tuple[float, float]:
    """这名干员的**天赋常驻闪避**（原版 `sim.py:2682-2689`）。

    ⚠ 必须在这里自己算一遍，不能读 `op.talent_dodge_phys`：那个字段是在
    **部署的那一刻**由 `_do_deploy` 写上的（`sim.py:2688`），而规格是在**跑之前**
    生成的——此刻它还是初值 0。这与 `_operator_spec` 里补 `op.position` 是同一个
    坑，而且**不报错**：只表现为"这名干员少了一截抵挡"。

    取的是与 `_do_deploy` **同一个来源**（`d.talents` → `find_damage_block` →
    `value("prob")`），不是自己另立一套判据；`tools/check_simgo.py` 里有一条
    "跑完之后这两个数必须等于规格里送的"的守卫，两处口径一旦分开就会响。
    """
    try:
        from ..battle import talents as _talents
    except Exception:                                          # noqa: BLE001
        return 0.0, 0.0
    fn = getattr(_talents, "find_damage_block", None)
    if fn is None:
        return 0.0, 0.0
    try:
        block = fn(getattr(d, "talents", None) or [])
    except Exception:                                          # noqa: BLE001
        return 0.0, 0.0
    if block is None:
        return 0.0, 0.0
    value = float(block.value("prob", 0.0) or 0.0)
    return value, value


def _operator_spec(sim, d) -> dict[str, Any]:
    """一名干员的规格。数值取**无技能帧**的那一套，外加技能开启期间的那一套。

    ⚠️ `_range_of()` 读的是 `op.position` / `op.direction`，而这两个字段要等
    `_do_deploy` 才写上。规格是在**跑之前**生成的，所以这里先把它们按这次部署
    填进去（值与模拟器随后要填的完全一样）——不填的话，算出来的是一张以 (0,0)
    为原点的范围表，而且**不会报错**，只会让两边的覆盖格悄悄不同。
    """
    op = d.operator
    op.position = (int(d.position[0]), int(d.position[1]))
    op.direction = d.direction
    # 幂等：正常情况下闸门（`unsupported_reasons`）已经挂过了，这里再挂一次
    # 只是让 `_operator_spec` 单独被调用时也读得到技能。
    _attach_skill_for_spec(d)
    spd = float(getattr(op, "attack_speed", 100.0) or 100.0)
    interval = max(MIN_INTERVAL, float(op.attack_interval) * 100.0 / max(ASPD_MIN, spd))
    cells = sim._range_of(op)
    skill, active = skills.skill_spec(sim, d)
    out = {
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
    talent_phys, talent_arts = _talent_dodge(op, d)
    if talent_phys or talent_arts:
        out["talent_dodge_phys"] = talent_phys
        out["talent_dodge_arts"] = talent_arts
    if skill is not None:
        out["skill"] = skill
        out["active"] = active
    return out


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
        # 被击倒时给田地加病害的那两项（怀黍离）。送的是**圆心之外的原始数值**：
        # 圆心由 Go 在击倒那一刻自己判（被阻挡时取挡它的干员那一格，否则取自己
        # 那一格）——那不是"敌人是什么"的一部分，是"当时场上是谁"的一部分。
        "passive_pollut": float(getattr(e, "passive_pollut", 0.0) or 0.0),
        "passive_radius": float(getattr(e, "passive_radius", 0.0) or 0.0),
        # 敌方**技能出手**（怀黍离「玷 / 勿玷」技能「污」）。这一组数送的是
        # 黑板里的量；"1 名 / 地面 / 十字五格 / 100%"四件事只在正文里，
        # 落在 Go 侧的 `AttackTick` 上（`sim.py:3471-3482` 的来历）。
        "skill_atk_scale_phys": float(getattr(e, "skill_atk_scale_phys", 0.0) or 0.0),
        "skill_atk_scale_magic": float(getattr(e, "skill_atk_scale_magic", 0.0) or 0.0),
        "skill_atk_init": float(getattr(e, "skill_atk_init", 0.0) or 0.0),
        "skill_atk_interval": float(getattr(e, "skill_atk_interval", 0.0) or 0.0),
        "skill_atk_cross": int(getattr(e, "skill_atk_cross", 0) or 0),
        "skill_atk_pollut": float(getattr(e, "skill_atk_pollut", 0.0) or 0.0),
        "skill_atk_ground_only": bool(getattr(e, "skill_atk_ground_only", False)),
        "legs": _legs_spec(e.legs),
    }


def build_spec(sim, *, stage_label: str = "", allow_devices: bool = False,
               allow_skills: bool = False, mechanisms: Iterable[str] = ()) -> dict[str, Any]:
    """`BattleSimulator` → 规格 dict。**调用前要先把 plan 排好。**

    只读 `sim` 的状态（`_spawn` 与 `_range_of` 都是纯读；后者要先补 position——
    见 `_operator_spec` 的说明），不改战斗状态。`allow_*` 见 `unsupported_reasons`。

    `mechanisms` 是**额外的**关卡特有机制名字（博士 2026-09-18：「机制单独成层、
    每个活动分开、按需取用」）。**这一关需要哪几个，由规格生成这一侧自己判**
    （`mech.names_for`），不由调用方点：调用方只知道自己给了什么阵容，不知道地图
    里有什么；漏点一个名字的症状是 Go 侧什么都不做却照样给判决。
    传进来的名字与自动判出来的**取并集**（调用方偶尔要点名一个自动判不出的机制时
    用得上）。**名字是 Python 与 Go 之间的契约**，两边都得改的时候一起改。
    """
    mechanisms = list(dict.fromkeys([*mech.names_for(sim), *mechanisms]))
    mech_config: dict[str, Any] = {}
    if mech.FARMLAND_ID in mechanisms:
        farm = mech.farmland_spec(sim)
        if farm is not None:
            mech_config[mech.FARMLAND_ID] = farm
    operators: list[dict[str, Any]] = []
    deploys: list[dict[str, Any]] = []
    for d in sorted(sim.deployments, key=lambda d: d.time):
        operators.append(_operator_spec(sim, d))
        deploys.append({
            "time": float(d.time),
            "index": len(operators) - 1,
            "char_id": d.operator.char_id,
            "cost": int(d.operator.deploy_cost),
            # 显式送：Go 侧的零值是 False，而原版的默认是 True（`Deployment.auto_skill`）
            "auto_skill": bool(getattr(d, "auto_skill", True)),
        })
    spawns = [_spawn_spec(sim, t, sp) for t, sp in sim._spawns]
    skill_uses = [{"time": float(u.time),
                   "cell": [int(u.position[0]), int(u.position[1])]}
                  for u in getattr(sim, "skill_uses", []) or []]
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
        "skill_uses": skill_uses,
        "unsupported": unsupported_reasons(
            sim, allow_devices=allow_devices, allow_skills=allow_skills),
        "mechanisms": mechanisms,
        "mech_config": mech_config,
    }
