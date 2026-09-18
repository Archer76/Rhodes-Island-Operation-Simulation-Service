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

    * `allow_devices` —— 只有对拍台**实测过**"**只关装置运行期**、保留开场断田几何，
    结果一字不变"时才传 True。口径要说准，这里踩过一次：

      - **不是**"把 `sim._devices` 清空判决不变"。那是问错了问题——清空连开场的
        断田几何一起摘了，而几何**已经在 Go 的规格里**（随 `farmland.actual`/`groups`
        送过去）。照那个口径，HS-EX-3 被误判成"装置有影响"、白挡了一轮。
      - **是**把 `_device_tick`（建成 / AuraHit 进入触发 / 被拆后把地形还回去）
        与 `_pile_tick`（天桩链）换成空操作之后判决不变。这两段才是 Go 没有的东西。
      - ⚠ 泵站**不在这条口子里**：泵水住在 `_environment_tick`（`sim.py:1363`），
        Go 的田地机制已经实现了它。关掉 `_device_tick` 时泵水**照旧**，这正是要的。
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
                          ("hammer", "锤击"),
                          ("effects_override", "技能效果覆盖"),
                          ("power_attack_count", "天赋「强击瓶专家」"),
                          ("sp_per_attack_talent", "天赋回技力（出手）"),
                          ("sp_per_kill_talent", "天赋回技力（击杀）")):
            val = getattr(op, attr, 0)
            if val:
                bad.append(f"{why}：{op.name or op.char_id}")
        # ⚠ 特性溅射附带的【停顿】（`highland_splash_sluggish`）**故意不挡**：
        # 原版自己也没有消费它——全仓 `sluggish_timer` 只有两处，一是置位
        # （`_highland_splash` / `eff.control["sluggish"]`）、二是每帧倒计时，
        # **没有任何地方读它来降移速**。那是"两边都没有这条"，不是"Go 少了一条"，
        # 挡着它就等于让 HS-EX-8 永远验不了。
        # 哪天原版真把这一支接上（`advance()` 里按 `sluggish_timer` 折速），
        # 这条闸门必须一起回来——判据是再扫一遍 `sluggish_timer` 的消费点。
        # 「每次有高台触发第一天赋的效果时，获得 N 点技力」住在**技能黑板**里
        # （原版 `_highland_sp` 读 `sp_per_highland`），Go 侧没有这条。
        _sk = getattr(op, "skill", None)
        if _sk is not None and float(
                (getattr(_sk, "blackboard", None) or {}).get("sp_per_highland") or 0.0):
            bad.append(f"高台触发回技力：{op.name or op.char_id}")
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
        # 医疗的平A（`heals`）已经接线（Go 的 `operatorsAttack`：判"这一击有没有
        # 被技能改成伤害"、按 (血量比例, 血量) 选最低的治疗、回复量夹生命上限）。
        # **没接的是技能自己写 `heal_scale` 的那一族**——Go 只做"平A 倍率 1.0"
        # 这一种，所以只挡那一种。
        _heal_sk = getattr(op, "skill", None)
        _heal_eff = getattr(_heal_sk, "effects", None) if _heal_sk is not None else None
        if getattr(op, "heals", False) and float(
                getattr(_heal_eff, "heal_scale", 0.0) or 0.0):
            bad.append(f"技能治疗倍率（heal_scale）：{op.name or op.char_id}")
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
        "awake_value": "按田地病害值觉醒",
        "hp_drain_per_sec": "持续自伤",
    }
    #: 已经接线、因此**不在这张表里**的敌人行为：
    #:  * `skill_atk_*`（敌方技能出手「污」）→ Go 的 `AttackTick`（帧序 7.2）；
    #:  * `passive_pollut`（被击倒污染田地）→ Go 的 `PostAttack`（帧序 7.5）；
    #:  * `reborn_pollut` 与整套 `Reborn.*`（重生、重生期充能、归来后的防御
    #:    加成与普攻附加法术伤害）→ Go 的帧序 3.4 与 `PollutionDrainer`；
    #:  * 整套 `phit_*`（蜕皮被动：每挨打 N 次叠层改属性 + 加病害）→ Go 的
    #:    `enemy.take` → `simCtx.onEnemyHit`（与普攻同帧）与 `PollutionAdder`；
    #:  * `reborn_summons`（重生期召唤）→ Go 的帧序 3.4（路线按格查表，
    #:    查不到当场拒跑）；
    #:  * 整套 `pm2_*`（明识形态：归来改一次面板 + 清水开关 + 标记退场 +
    #:    限时无敌）→ Go 的 `enterPm2`/`pm2Tick`（帧序 7.6）与
    #:    `ClearWaterProbe`（清水判定住在田地/装置那一层）。
    #: 它们曾经都在表里，那是对的：没接线的时候放行，等于让 Go 少算一层却照样
    #: 给判决。**新加一条进这张表时先确认那条路真的没接线**，别把已接的留在
    #: 表里——那会让整关无谓地被挡住。
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
    # 医疗的平A 是**治疗**。Go 侧原来连这个字段都没有，于是"人被打死"与
    # "人被奶住"在那边长得一模一样——满练度作业的偏差就是这么来的。
    if getattr(op, "heals", False):
        out["heals"] = True
    talent_phys, talent_arts = _talent_dodge(op, d)
    if talent_phys or talent_arts:
        out["talent_dodge_phys"] = talent_phys
        out["talent_dodge_arts"] = talent_arts
    # ---- 职业特性溅射（撼地者那四位；解好的三个倍率，见 `battle/traits.py`）
    #
    # `splash_damage_scale` 是天赋「汹涌怒火」叠上来的那一半，**只乘溅射**；
    # 溅射真正用的倍率是 `splash_scale × splash_damage_scale`（0.5 × 1.24）。
    # 高台那一半的倍率单独送——它是另一套几何（十字五格、只打地面）。
    _splash_radius = float(getattr(op, "splash_radius", 0.0) or 0.0)
    if _splash_radius > 0.0:
        out["splash_radius"] = _splash_radius
        out["splash_scale"] = float(getattr(op, "splash_scale", 0.0) or 0.0)
        out["splash_damage_scale"] = float(
            getattr(op, "splash_damage_scale", 1.0) or 1.0)
        _high = float(getattr(op, "highland_splash_scale", 0.0) or 0.0)
        if _high > 0.0:
            out["highland_splash_scale"] = _high
            # 高台那一半溅到之后挂的【停顿】（`attack@sluggish`，怒潮凛冬 0.5 秒）。
            #
            # ⚠ 这一条**必须送**：原版 `EnemyUnit.advance` 在停顿期间整帧不移动，
            # 所以它是个会改判决的量，不是"只用来显示的状态"。曾经把它当成
            # "原版也不消费的假账"而从规格里删掉，代价是敌人每次中一发高台溅射
            # 就比原版多走 0.5 × 移速 = 0.2 格，几十秒后判决从"守住"翻成"漏怪"。
            _slu = float(getattr(op, "highland_splash_sluggish", 0.0) or 0.0)
            if _slu > 0.0:
                out["highland_splash_sluggish"] = _slu
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
    return _unit_spec(sim, e, time=float(t))


def _unit_spec(sim, e, *, time: float = 0.0) -> dict[str, Any]:
    """**一名已经建好的敌人** → 规格。

    与 `_spawn_spec` 是同一个口径（后者只是先 `_spawn` 再调这里）。分开的理由是
    天桩链那三跳：甲／乙／天标都**不在出怪表里**，它们是装置或上级单位造出来的
    （原版 `_build_enemy(key, level, pts, [], t, 0.0)`），手上只有对象、没有"出怪行"。
    一个口径只留一处，免得"出怪表里的甲"和"装置召唤的甲"算成两个人。
    """
    return {
        "time": float(time),
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
        # ---- 蜕皮（`Passive_Hit.*`，「祟」的混沌形态）
        #
        # 送的是**每挨打一次**要用的那套数：挨几次叠一层、每层改多少属性、
        # 每次挨打给圆心周围加多少病害（被挡 / 没被挡两个数）。
        # 圆心由 Go 在挨打那一刻自己判（与击倒污染同一套口径，但**用量的选择
        # 多看一位**：被挡那一位这一帧刚倒也算"被挡"，见 `sim.py:1263-1265`）。
        "phit_cnt": int(getattr(e, "phit_cnt", 0) or 0),
        "phit_max_stack": int(getattr(e, "phit_max_stack", 0) or 0),
        "phit_atk": float(getattr(e, "phit_atk", 0.0) or 0.0),
        "phit_def": float(getattr(e, "phit_def", 0.0) or 0.0),
        "phit_res": float(getattr(e, "phit_res", 0.0) or 0.0),
        "phit_move": float(getattr(e, "phit_move", 0.0) or 0.0),
        "phit_weight_cnt": int(getattr(e, "phit_weight_cnt", 0) or 0),
        "phit_pollut": float(getattr(e, "phit_pollut", 0.0) or 0.0),
        "phit_block_pollut": float(
            getattr(e, "phit_block_pollut", 0.0) or 0.0),
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
        # ---- 重生（`Reborn.*`，怀黍离「瘴 / 鄙瘴」的 `Reborning.*` 共用这套状态）
        #
        # 这一段曾经**整条没送**：Go 那边因此静默少算 BOSS 的一条命，只有恰好
        # 因此改变判决的关卡才会露馅。送的是"敌人是什么"这一半；"什么时候吸、
        # 吸哪一格"由 Go 的帧序 3.4 与田地那一层分别负责。
        "reborn_left": int(getattr(e, "reborn_left", 0) or 0),
        "reborn_delay": float(getattr(e, "reborn_delay", 0.0) or 0.0),
        "reborn_hp_ratio": float(getattr(e, "reborn_hp_ratio", 1.0) or 1.0),
        "reborn_interval": float(getattr(e, "reborn_interval", 0.0) or 0.0),
        "reborn_pollut": float(getattr(e, "reborn_pollut", 0.0) or 0.0),
        "reborn_def_add": float(getattr(e, "reborn_def_add", 0.0) or 0.0),
        "reborn_damage_magic": float(
            getattr(e, "reborn_damage_magic", 0.0) or 0.0),
        # --- 重生期**召唤**（「祟」）：窗口内每 interval 秒在脚下召唤 count 个
        #
        # 召唤物要走到最近的保护目标，所以需要**一条真路线**；而路线只取决于
        # "倒下那一刻站在哪一格"，那一格出规格时还不知道。做法是把地图上
        # **每一格**的路线都算好随规格发过去（`sim._path_from`，与 `eta.route_plans`
        # 同一个寻路），Go 按召唤那刻的格子查表——查不到它会当场拒跑，
        # 而不是随便给一条路（那会让漏怪判定悄悄偏）。
        "reborn_summons": _reborn_summons_spec(sim, e),
        # ---- 明识形态（`PassiveM2.*`，「祟」重生归来后的第二形态）
        #
        # 送的是"进形态要改哪些量"；"什么时候判清水、什么时候算标记退场"
        # 由 Go 的帧序 7.6 与田地/装置那一层分别负责。
        "pm2_atk": float(getattr(e, "pm2_atk", 0.0) or 0.0),
        "pm2_def": float(getattr(e, "pm2_def", 0.0) or 0.0),
        "pm2_res": float(getattr(e, "pm2_res", 0.0) or 0.0),
        "pm2_move": float(getattr(e, "pm2_move", 0.0) or 0.0),
        "pm2_clean_def": float(getattr(e, "pm2_clean_def", 0.0) or 0.0),
        "pm2_clean_move": float(getattr(e, "pm2_clean_move", 0.0) or 0.0),
        "pm2_mark_pollut": float(getattr(e, "pm2_mark_pollut", 0.0) or 0.0),
        "pm2_invincible": float(getattr(e, "pm2_invincible", 0.0) or 0.0),
        "legs": _legs_spec(e.legs),
    }


def _highland_cells(sim) -> list[list[int]]:
    """地图上**高台**格的列表（`[x, y]`）。

    天赋「汹涌怒火」的高台那一半要判"被溅射到的格是不是高台"，而 Go 侧只有
    规格、没有地图。只送这一个布尔分类，不送整张地形——够用且小。
    """
    m = sim.stage.map
    out: list[list[int]] = []
    # ⚠ 遍历 `tiles` 表本身，**不要**按 `range(width) × range(height)` 取：
    # 地图的行列长度与这两个数并不总是一致，`tile()` 越界会抛 IndexError，
    # 而"取不到就当不是高台"的兜底会把**真的高台格静默吃掉**。
    # 实测后果：怒潮凛冬单手一份作业的伤害从 23260 掉到 22656（少一格高台
    # 就少几次 0.27 倍溅射），判决跟着从"守住"变成"漏怪"。
    try:
        tiles = m.tiles
    except Exception:
        tiles = []
    for y, row in enumerate(tiles):
        for x, tile in enumerate(row):
            if getattr(tile, "is_highland", False):
                out.append([x, y])
    return out


def _reborn_summons_spec(sim, e) -> list[dict[str, Any]]:
    """重生期召唤的规格：每拍的时间/个数 + **召唤物的完整规格** + 逐格路线表。

    `e.reborn_summons` 是 `(间隔, 每拍个数, 敌人 id)` 的三元组列表（原版
    `_reborn_tick` 4176 行就是这样解包的），"召唤谁"要**现造一只**才知道它长
    什么样——Go 侧没有敌人图鉴，只有规格。

    造模板用的是 `copy.copy(sim)`：`_build_enemy` 会顺手写 `sim.mode_skill`
    这类"随规格走的"实例状态，直接拿本体造就等于**提前改了要跑的那一份**。
    浅拷贝把这些写入留在副本上，本体在正式跑之前仍然是干净的。

    路线表按**地图每一格**算（`ground_path` 到最近保护目标，与
    `eta.route_plans` 同一个寻路）：召唤那一刻站在哪一格只有跑到才知道，
    而"最近"是按**路径长度**算的（绕远路的直线距离可能更近）。查不到这一格
    时 Go 会当场拒跑——宁可拒跑也不给一条错的路。
    """
    rows = list(getattr(e, "reborn_summons", ()) or ())
    if not rows:
        return []
    import copy

    m = sim.stage.map
    paths: dict[str, list[list[int]]] = {}
    for x in range(int(getattr(m, "width", 0))):
        for y in range(int(getattr(m, "height", 0))):
            if not m.walkable(x, y):
                continue
            p = sim._path_from((x, y))
            if p:
                paths[f"{x},{y}"] = [[int(a), int(b)] for a, b in p]
    out: list[dict[str, Any]] = []
    for itv, cnt, key in rows:
        level = sim._summon_level(str(key))
        probe = copy.copy(sim)
        # 腿留空：真正那条腿由 Go 按召唤那一刻的格子从 `paths` 里取。
        unit = probe._build_enemy(str(key), level, [(0.0, 0.0)], [], 0.0, 0.0)
        out.append({
            "interval": float(itv),
            "count": int(cnt),
            "template": _unit_spec(sim, unit),
            "paths": paths,
        })
    return out


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
        # ⚠ 不能写死 600：原版的 `BattleSimulator.run(max_time=600.0)` 只是**默认**，
        # 而验证这一路调的是 `sim.run(max_time=900.0)`（`verifier.py:93` 与
        # `verify.py:410`）。写死 600 会让"打到 814 秒才赢"的作业在 Go 侧被
        # **截断在 600 秒**——判决从"胜利"变成"超时"，而且看不出是截断造成的。
        #
        # `sim` 自己不一定记着这个数（它是 `run` 的形参），所以回退到 900——
        # 那就是上面两处调用点用的值。哪天上游改成按关卡给，这里会自己跟上。
        "max_time": float(getattr(sim, "max_time", 0.0) or 900.0),
        "life": int(sim.life),
        "cost_init": float(sim.cost),
        "cost_max": float(sim.max_cost),
        "cost_time": float(sim.cost_time),
        "enemy_windup": float(sim.enemy_windup),
        "ranged_enemies": bool(sim.ranged_enemies),
        "speed_scale": float(sim.speed_scale),
        # 高台格：Go 没有地图，而天赋「汹涌怒火」的高台那一半要判"被溅射到的格
        # 是不是高台"。只在这条特性真在场时才送（通用关卡一帧都不多花）。
        "highland_cells": _highland_cells(sim) if any(
            float(getattr(d.operator, "highland_splash_scale", 0.0) or 0.0) > 0.0
            for d in sim.deployments) else [],
        "operators": operators,
        "deploys": deploys,
        "spawns": spawns,
        "skill_uses": skill_uses,
        "unsupported": unsupported_reasons(
            sim, allow_devices=allow_devices, allow_skills=allow_skills),
        "mechanisms": mechanisms,
        "mech_config": mech_config,
    }
