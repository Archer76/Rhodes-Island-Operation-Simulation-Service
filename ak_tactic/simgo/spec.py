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

#: ⚠ 敌方那三条**规矩**的实现住在 `ak_tactic/frontend/enemy_rules.py`（不在 `battle/` 里）。
#: 从 `sim` 上转调也能拿到同样的结果（那边的方法就是转调这里），
#: 但**直接调新家**才是"摘除 `battle/`"要的方向——每一处都少一次对模拟器的依赖。
from ..frontend.enemy_rules import (                             # noqa: E402
    cannot_clear, pile_mark_key, summon_level,
)

#: ⚠ 两条**几何**同理（`range_of` / `path_from`，住 `frontend/geometry.py`）。
#: 直接调新家而不是 `sim._range_of`：少一次对模拟器的依赖，而且新接口把
#: 位置与朝向**当参数传**——算"某个假设位置上的范围"不必再篡改干员对象。
from ..frontend.geometry import path_from, range_of               # noqa: E402

#: ⚠ 敌人的**规格视图**（`enemy_view`）与取数（`enemy_stats`）住新家。
#: 从这一轮起，规格里那些敌人**不再需要一个活的对象**——`enemy_view` 按
#: `_build_enemy` 的同一套表达式算出同一组字段，装进一个 `SimpleNamespace`。
#: 口径的逐字段证据见 `tools/check_enemy_view.py`（798 行出怪零差异）。
from ..frontend.enemy_stats import enemy_stats                    # noqa: E402
from ..frontend.enemy_view import enemy_view                      # noqa: E402
from ..frontend.stage_env import stage_env                        # noqa: E402
#: ⚠ 干员一律走这个入口取，**不要直接写 `d.operator`**——那个是活的
#: `OperatorUnit`（Python 引擎要拿它跑帧），规格只要开局那一组字段。
from ..frontend.schedule import operator_of                       # noqa: E402

#: 路线解析**与 `ak_tactic.eta` 共用同一份实现**（原版 `sim.py:583` 也是从
#: 这里取的）——两处各写一遍必然对不上。
from ..eta import route_plans                                     # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs

#: 攻击间隔的下限与攻速下限，与 `battle/unit.py` 同源（那里写死 0.05 / 20）
MIN_INTERVAL = 0.05
ASPD_MIN = 20.0

#: Go 侧的**积雪**是否已经接线。这是个开关而不是"看有没有字段"：
#: 闸门的职责是"Go 能不能跑这一局"，而"Python 这边有没有这片雪"是另一件事——
#: 两者混在一起，正是 2026-09-19 那个静默缺口（见 `snow_spec` 的说明）。
#:
#: 置 True 的**唯一条件**：Go 的 `mech/snow.go` 已实现、且 HS-EX-8 第 3 手起
#: 逐帧对拍通过（含冻结那一半——`frozen` 是复合判据）。
#:
#: 2026-09-19：`mech/snow.go` 已落地（积层/扩散/减速/踏入伤害/满层冻结/
#: 首敌离场清雪六条，技能2 那一半未移植，作业里 skill=0 用不到），
#: 闸门打开交给对拍验证。**对拍不过就把它改回 False**——那等于"退回原版"，
#: 是这套闸门存在的意义，不是失败。
ALLOW_SNOW = True


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
    op = operator_of(d)
    spec = getattr(d, "skill", 0)
    if spec is None or (isinstance(spec, int) and spec == 0):
        op.skill = None
        return None
    if isinstance(spec, int):
        return (f"技能槽号 {spec}（{op.name or op.char_id}）："
                f"调用方要先把 SkillLevel 绑好再生成规格")
    op.skill = spec
    return None


def unsupported_reasons(inp, *, allow_devices: bool = False,
                        allow_skills: bool = False,
                        schedule=None) -> list[str]:
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
    #: ⚠ **排程从哪读**：给了 `schedule`（新家 `frontend/schedule.py` 的载体）就用它，
    #: 没给就退回模拟器。迁移期的开关——两边方法名逐字相同（`schedule.py` 的
    #: `Schedule`），所以下面的读法一字不用改；等 `battle/` 删掉时把这里的兜底
    #: 去掉、`schedule` 变成必填就完事。
    #:
    #: 为什么先做这一步：`build_spec` 对 `battle/` 的依赖里，"排程产物"占 5 项
    #: （deployments / retreats / skill_uses / device_deployments / summon_deployments）。
    #: 它们全是**五个 append** 攒出来的列表，搬走它们等于把那 5 项一次性清零。
    #:
    #: ⚠ **本函数与 `build_spec` 各要一份 `sch`**：闸门那几条（召唤/装置/撤退）
    #: 住在本函数里，而部署循环住在 `build_spec` 里。只在一处定义会
    #: `NameError: name 'sch' is not defined`——而它会被记成"规格抄不到"。
    sch = schedule if schedule is not None else inp

    bad: list[str] = []
    if sch.skill_uses:
        pass          # 手动开技能现在**支持**（白名单判定在下面逐人做）
    if sch.summon_deployments:
        bad.append(f"召唤物部署 ×{len(sch.summon_deployments)}")
    if sch.device_deployments:
        bad.append(f"装置部署 ×{len(sch.device_deployments)}")
    if sch.retreats:
        bad.append(f"撤退 ×{len(sch.retreats)}")
    if getattr(inp, "team_auras", None):
        # ⚠ 这段现在是**死代码**，但仍然要留着提醒：`sim.team_auras` 是
        # **部署那一刻**才 append 的（`sim.py:3451`），而闸门取的是**开局态**
        # ——这里读到的**永远是空**。真正的全场光环现在随**干员规格**送过去
        # （见 `_team_auras_of` 与 Go 的 `teamAuraTick`），判定按"目标是谁"逐人算。
        #
        # ⚠ 更要紧的是：**这条闸门从来就没有起到过作用**。
        # 曾经它读的是同一张空表，看上去"拒跑了全场光环"，实际一次都没拦下
        # ——这正是闸门盲区的形态："闸门不报、规格里也没这项，Go 静默跑出另一场战斗"。
        pass
    # ⚠ 这里**曾经**有一条 `增益治疗光环 ×N`——
    # 「医者丰碑」那时没移植，所以一刀切拒跑。现在它接上了
    # （Go 的 `regenAuraTick`，帧位 5.5；规格见 `_operator_spec` 的 `regen_aura`），
    # 该条**必须删掉**：留着会让这一关永远走不到 Go，
    # 而"拒跑"与"跑了但不一致"是两种完全不同的红。
    if getattr(inp, "snow_fields", None):
        bad.append(f"积雪 ×{len(inp.snow_fields)}")
    bad += _snow_reasons(inp)
    bad += _enemy_reasons(inp)
    if getattr(inp, "farmland", None) is not None:
        # 田地本身**已接线**（Go 的 `mech/huai_shu_li.go`）：几何与参数随规格送过去，
        # 时间由 Go 跑。所以这里不再一刀切拒跑，改成按**这一关实际用到的东西**逐条判
        # ——没接线的部分（敌人侧污染、天桩链、拆阀还原）由 `mech.port_reasons` 报。
        bad += mech.port_reasons(inp)
    if getattr(inp, "devices", None) and not allow_devices:
        bad.append(f"关卡装置 ×{len(inp.devices)}")
    if getattr(inp, "total_attack", None) is not None:
        bad.append("全场总攻击装置")

    for d in sch.deployments:
        op = operator_of(d)
        # 先按原版的分支把技能挂好（`Deployment.skill` 的默认值是 **0**，
        # 而它会把干员身上已绑的技能清掉——这一步不做，规格与那一趟就会不一致）
        stuck = _attach_skill_for_spec(d)
        if stuck:
            bad.append(stuck)
        elif getattr(op, "skill", None) is not None:
            if allow_skills:
                bad += [f"{op.name or op.char_id}：{r}"
                        for r in skills.port_reasons(inp, op)]
            else:
                bad.append(f"技能：{op.name or op.char_id}")
        for attr, why in (("summon_of", "召唤物"),
                          ("hammer", "锤击"),
                          ("effects_override", "技能效果覆盖"),
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
        #
        # ⚠ 这一条**已经放行**（Go 的 `operatorsAttack` 已兑现三连击与
        # 「结算后再缩放」）。放行的依据是那两项都只用到"这一刻的数值"，
        # 不依赖任何 Go 侧没有的技能结构——所以它不需要再挡。
        #
        # 天赋「强击瓶专家」现在也放行，但**只放行 `rounds == 1` 的那一半**：
        # 原版按**轮**扣层，而"一轮"在技2（三轮齐射 ＋ 落地点射）、技1（刚连射）
        # 那几种出手里大于 1，那三样（`volley_arrows` / `landing_scale` /
        # `charge_arrows`）**还没进 Go 的 `Profile`**。Go 那边只兑现 `rounds = 1`，
        # 所以带这三样的技能必须继续挡——否则层数消耗会比原版慢，
        # 而症状是"多打了十几轮 115% 加成"，在判决里只表现为伤害偏高。
        if int(getattr(op, "power_attack_count", 0) or 0) > 0:
            _pa_eff = getattr(getattr(op, "skill", None), "effects", None)
            _multi = False
            if _pa_eff is not None:
                if len(getattr(_pa_eff, "volley_arrows", None) or ()) > 1:
                    _multi = True
                if float(getattr(_pa_eff, "landing_scale", 0.0) or 0.0):
                    _multi = True
                if float(getattr(_pa_eff, "charge_arrows", 0.0) or 0.0):
                    _multi = True
            if _multi:
                bad.append(f"天赋「强击瓶专家」一次出手多轮：{op.name or op.char_id}")
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


def _ground_neighbours(inp, cells) -> dict[str, list[list[int]]]:
    """每个雪格的**相邻可行走格**，按距离由近及远，去重、确定性排序。

    Go 没有地图（`wire.go` 文件头那条原则），所以"谁能扩散到谁"这份几何必须由
    Python 算好送来。口径照原版 `sim.py::_ground_neighbours`（`_snow_tick` 传给
    `SnowField.tick` 的那个回调），**不相邻、不可行走、以及已有的格**都不在里面。

    排序规则（四个方向 + 四个对角，按 `(dx, dy)` 字典序）**必须与 Go 侧遍历
    顺序一致**：`_spread_frontier` 的顺序决定了"扩散上限先被谁占掉"，
    而扩散上限是硬约束（`spread_cap`）——顺序不同 = 雪落在不同的格上。
    """
    mp = inp.stage.map
    seen: set[tuple[int, int]] = set(cells)
    out: dict[str, list[list[int]]] = {}
    for (x, y) in sorted(cells):
        nbrs: list[list[int]] = []
        for dx, dy in ((-1, 0), (0, -1), (0, 1), (1, 0),
                       (-1, -1), (-1, 1), (1, -1), (1, 1)):
            c = (x + dx, y + dy)
            if c in seen:
                continue
            try:
                if not mp.walkable(*c):
                    continue
            except Exception:                                  # noqa: BLE001
                continue
            seen.add(c)
            nbrs.append([c[0], c[1]])
        out[f"{x},{y}"] = nbrs
    return out


def snow_spec(inp) -> list[dict[str, Any]]:
    """本局会铺出来的每一片雪。**单一来源**：闸门与送数都调它。

    ⚠ 这里读的是 `d.talents` 而**不是** `op.talents`——后者要到 `_do_deploy`
    里才被写上（`sim.py:3353`），而本函数在**跑之前**就要给答案。
    这与 `_talent_dodge`（`spec.py:257`）是同一个坑的同一种修法：值从
    `_do_deploy` 的**同一个来源**取，不另立一套判据。

    原版建对象的位置在 `sim.py:3396-3406`：

        snow = find_snow(op.talents)
        if snow is not None:
            self.snow_fields.append(SnowField(owner, interval, max_layers,
                slow_per_layer=abs(move_speed), magic_scale, operator=op))

    四个数逐字对应，一个都不许自己发明。

    **为什么需要它（这是一个真实的静默缺口，2026-09-19 实测）**：
    `snow_fields` 是**部署那一刻**才创建的列表，而闸门与 `build_spec` 都在
    **跑之前**执行 —— 于是 `unsupported_reasons` 里的
    `if sim.snow_fields` 永远读到空列表，闸门**不报**、规格里也没有这一项，
    Go 静默跑出另一场战斗。HS-EX-8 第 3 手（圣聆初雪）就这么被放过：
    Go 17杀 90.2s vs 原版 18杀 99.1s，而 `go_fallbacks == 0` 看起来"走了 Go"。
    判据：**闸门读运行期对象，就必须逐条问"这个对象是什么时候创建的"**。

    除了四个天赋数，还要送两样 Go 拿不到的东西：

    * `ground` —— 射程内的**可行走格**（雪只铺在这些格上，原版
      `ground = [c for c in self._range_of(op) if m.walkable(*c)]`）。
      必须是**确定性顺序**（排序后），否则积层顺序一变、`added` 的计数就变。
    * `neighbours` —— 扩散用的相邻关系（见 `_ground_neighbours`）。
    * `goal_cells` —— 防守点格。**满层的雪不冻结终点格**（原版
      `and not self._is_goal(cell)`）：把已经踏到终点的敌人冻在离终点半格处，
      它永远到不了终点，等于白送一条命。
    """
    fields: list[dict[str, Any]] = []
    for d in getattr(inp, "deployments", None) or ():
        op = operator_of(d)
        try:
            from ..frontend import talent_finders as _talents
        except Exception:                                      # noqa: BLE001
            return fields
        snow = _talents.find_snow(getattr(d, "talents", None) or ())
        if snow is None:
            continue
        fields.append({
            "owner": op.name or op.char_id,
            "char_id": op.char_id,
            "cell": [int(d.position[0]), int(d.position[1])],
            "direction": str(d.direction),
            "interval": float(snow.value("interval", 10.0)),
            "max_layers": int(snow.value("max_cast_cnt", 5)),
            "slow_per_layer": abs(float(snow.value("move_speed", 0.0))),
            "magic_scale": float(snow.value("talent_magic_scale", 0.0)),
        })
    return fields


def snow_mech_spec(inp, deployments=None) -> dict[str, Any] | None:
    """送给 Go 的积雪规格（`mech.SNOW_ID` 那一段）。没有雪就返回 None。

    ⚠ `deployments` 是**迁移期的开关**：给了就用新家的那一份
    （`frontend/schedule.py` 的 `Schedule.deployments`），没给才退回模拟器。
    """
    fields = snow_spec(inp)
    if not fields:
        return None
    mp = inp.stage.map
    out_fields: list[dict[str, Any]] = []
    all_cells: set[tuple[int, int]] = set()
    #: `operator_index` 必须与 `build_spec` 给 `deploys[].index` 的**同一个
    #: 计数器**：那里是 `sorted(deployments, key=time)` 之后的下标。
    #: Go 侧 `Snow.Start` 会核对它指向的那一位 `char_id`/`cell` 都对得上，
    #: 所以这里只要跟着同一个排序走就不会错位。
    if deployments is None:
        deployments = inp.deployments
    ordered = sorted(deployments, key=lambda d: d.time)
    for f in fields:
        op = None
        idx = -1
        for i, d in enumerate(ordered):
            if operator_of(d).char_id == f["char_id"] and \
                    [int(d.position[0]), int(d.position[1])] == f["cell"]:
                op, idx = operator_of(d), i
                break
        ground: list[list[int]] = []
        if op is not None:
            op.position = (f["cell"][0], f["cell"][1])
            op.direction = f["direction"]
            cells = sorted((int(x), int(y)) for x, y in range_of(
                inp.range_provider, char_id=op.char_id, elite=op.elite,
                direction=f["direction"],
                position=(f["cell"][0], f["cell"][1]),
                range_id=op.current_range_id()))
            ground = [[x, y] for x, y in cells if mp.walkable(x, y)]
        all_cells.update((x, y) for x, y in ground)
        g = dict(f)
        g["ground"] = ground
        g["operator_index"] = idx
        out_fields.append(g)
    goals = sorted({(int(x), int(y)) for x, y in
                    (inp.goal_cells or _find_goals(inp))})
    return {
        "freeze": bool(getattr(inp, "snow_freeze", True)),
        "fields": out_fields,
        "neighbours": _ground_neighbours(inp, all_cells),
        "goal_cells": [[x, y] for x, y in goals],
    }


def _find_goals(inp) -> set[tuple[int, int]]:
    """防守点格（原版 `_is_goal(cell)` 判的那些，`sim.py:672`）。

    原版判据只有一句：`m.tile(*cell).key == "tile_end"`。所以这里用的就是
    **同一个判据**，不另立一套（比如去找路线终点）——路线终点与防守点不是一回事，
    而"少冻一格"的后果是判决级偏差。

    取不到（地图对象没有 `tile`）就返回空集：那时行为退化成"不豁免任何格"，
    即多冻。多冻只影响已经站在终点上的敌人，而原版对那种敌人也不冻
    （它已经按漏怪处理了）——这是安全的退化方向。
    """
    mp = inp.stage.map
    try:
        out = set()
        for y in range(int(mp.height)):
            for x in range(int(mp.width)):
                if not mp.inside(x, y):
                    continue
                if mp.tile(x, y).key == "tile_end":
                    out.add((x, y))
        return out
    except Exception:                                          # noqa: BLE001
        return set()


def _snow_reasons(inp) -> list[str]:
    """积雪这一族的闸门。按 `snow_spec` 的产物判——**别再读运行期列表**。"""
    fields = snow_spec(inp)
    if not fields:
        return []
    if ALLOW_SNOW:
        return []
    who = "/".join(sorted({f"{f['owner']}({f['char_id']})" for f in fields}))
    return [f"积雪（天赋「无垠的雪景」）：{who}"]


def _enemy_reasons(inp) -> list[str]:
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
    for e in mech._spawns_of(inp):
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
                and getattr(inp, "device_deployments", None):
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
        from ..frontend import talent_finders as _talents
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

    ⚠ **这里原先是一串 `try/except` + `getattr(..., None)` 兜底，返回 `(0.0, 0.0)`。
    那是个会把 bug 藏起来的写法**：`find_damage_block` 一旦取不到（例如搬运天赋
    查找器时漏带），结果不是报错，而是"这名干员**恰好**没有天赋闪避"——
    键在规格里**静默消失**（`if talent_phys or talent_arts:` 不成立），
    判决一模一样，只有 `spec_sha` 变了。2026-09-19 搬运 `talent_finders` 时
    就真的这么中过一次，17 份金标准里 `plan-hs06` 单独变红才抓到。
    ⇒ 取数一律直取，取不到就炸。
    """
    from ..frontend import talent_finders as _talents
    block = _talents.find_damage_block(getattr(d, "talents", None) or [])
    if block is None:
        return 0.0, 0.0
    value = float(block.value("prob", 0.0) or 0.0)
    return value, value


def _team_auras_of(d, op) -> list[dict[str, Any]]:
    """这一位干员自己带出去的**全场光环**（天赋），照原版部署那一刻那几段写。

    来源是 `find_team_aura` / `find_class_aura` / `find_ammo_covenant` 三个
    **互不重叠**的探测器，一名干员可以同时命中多条（「万众巨潮」与
    「特种作战策略」就是并列的两条天赋，不是同一件事）。

    ⚠ `skill_only` 那一条**不能在规格里定死数值**：它随主人开不开技能变，
    Go 侧每帧重算（`teamAuraTick`）。这里送的是"这条光环长什么样"，
    不是"这一刻它值多少"。

    ⚠ `double_scale` **每次都要显式送**：原版那个字段的默认值是 2.0
    （`double_scale: float = 2.0`），不是"没有就不翻倍"。靠 `omitempty`
    省掉它，Go 侧读到的就是 0——主人一开技能，加成会被乘成 0。
    """
    from ..frontend import talent_finders as _t
    out: list[dict[str, Any]] = []
    tal = getattr(d, "talents", None) or []
    name = op.name or op.char_id
    aura = _t.find_team_aura(tal)
    if aura is not None:
        if aura.name == _t.FACTION_AURA_NAME:
            # 「万众巨潮」：**只在主人技能期间**生效，且对【乌萨斯学生自治团】
            # 翻倍（按 char_id 名单）。与「青色怒火」是两种形状，不能用同一个
            # 倍率表达——那个是常驻 + 开技能加倍。
            out.append({
                "owner": name,
                "atk_pct": float(aura.value("atk", 0.0) or 0.0),
                "def_pct": float(aura.value("def", 0.0) or 0.0),
                "skill_only": True,
                "faction": sorted(_t.STUDENT_TEAM),
                "faction_scale": float(aura.value("scale_bonus", 2.0) or 2.0),
                "double_scale": 2.0,
            })
        else:
            # 「青色怒火」：常驻 + 主人开技能时加倍。
            out.append({
                "owner": name,
                "atk_pct": float(aura.value("atk", 0.0) or 0.0),
                "def_pct": float(aura.value("def", 0.0) or 0.0),
                "double_scale": 2.0,
            })
    class_aura = _t.find_class_aura(tal)
    if class_aura is not None:
        out.append({
            "owner": name,
            "atk_pct": float(class_aura.value("atk", 0.0) or 0.0),
            "def_pct": float(class_aura.value("def", 0.0) or 0.0),
            # ⚠ 这里是**主职业代号**（`TANK` = 重装），不是阵营 char_id 名单。
            "profession": _t.CLASS_AURA_TALENTS[class_aura.name],
            "double_scale": 2.0,
        })
    covenant = _t.find_ammo_covenant(tal)
    if covenant is not None:
        out.append({
            "owner": name,
            "atk_pct": float(covenant.value("atk", 0.0) or 0.0),
            "def_pct": float(covenant.value("def", 0.0) or 0.0),
            "double_scale": float(covenant.value("mult", 2.0) or 2.0),
            "ammo_skill_only": True,
            # 按**势力**翻倍（【拉特兰】），与按名单翻倍是两种数据形态。
            "nation_double": _t.LATERANO_NATION,
        })
    # 「天使的祝福」（能天使）：**自身** +6% 攻击。自身那半借光环通道，
    # `self_only` 只发自己。
    # ⚠ 同句的「随机友方」那半**两边都没做**（等裁定），所以这条天赋只算一半。
    # ⚠ 同一段里还有一句 `op.apply_max_hp_bonus(...)`（自身生命上限 +10%），
    # 那**不是光环**、也不在这里送：它在部署那一刻改 `op.max_hp`，而规格正是
    # 那一刻取的 ⇒ Go 拿到的是**没加过**的生命上限。名册里暂时没有能天使，
    # 所以还没显形；**换名册时这条会静默变成"Go 那边血少一截"**。
    angel = _t.find_angel_blessing(tal)
    if angel is not None:
        out.append({
            "owner": name,
            "atk_pct": float(angel.value("atk", 0.0) or 0.0),
            "def_pct": 0.0,
            "self_only": True,
            "double_scale": 2.0,
        })
    # 「极限调度」（可露希尔）：【罗德岛】干员攻击力 +4%。
    # ⚠ 同句的「部署费用下限 -3」**不在战斗层**（属名册/费用规则），原版也没做
    # ——所以这条天赋两边都只算一半。
    # ⚠ `faction_only` 是**筛选**（不匹配的一律 0），不是 `nation_double` 那种
    # "该势力 ×2、别人 ×1"。两个字段别混。
    dispatch = _t.find_limit_dispatch(tal)
    if dispatch is not None:
        out.append({
            "owner": name,
            "atk_pct": float(dispatch.value("atk", 0.0) or 0.0),
            "def_pct": 0.0,
            "faction_only": _t.RHODES_NATION,
            "double_scale": 2.0,
        })
    return out


def _shield_of(d) -> dict[str, Any] | None:
    """这一次部署的**层数护盾**配置；这个干员没有护盾就返回 None。

    ⚠ **读 `d.talents`，不读运行期对象** —— 与上面 `blessing_*`、以及积雪的
    `snow_spec` 是同一个坑的同一种修法。`op.shield_max_layers` / `op.shield_layers`
    要到 `_do_deploy` 里 `_attach_talent_shield`（`sim.py:3157-3182`）才被写上，
    而这份规格正是**在那之前**取的：读运行期只会读到 0，而"规格里是 0"与
    "这个干员本来就没护盾"在 Go 那边长得一模一样，是**静默**的。

    判据与 `sim.py:3165-3175` 逐字对齐：谁的天赋效果带 `shield_max_layers`
    就是谁（泥岩「沃土予身」有黑板 `max_times`；空弦「铁弦」没有上限、正文只写
    "获得**一层**护盾"，取两者的**大**者）；两者都为 0 就跳过。**只取第一个命中的**
    ——原版那一句就是 `return`，不是求并集。

    送**比例**而不是回血量：原版 `op.shield_break_heal = ratio × op.max_hp` 用的是
    **部署那一刻**的生命上限，所以由 Go 在同一时刻用同一个上限去乘。
    """
    for tal in getattr(d, "talents", None) or ():
        eff = getattr(tal, "effects", None)
        if eff is None:
            continue
        cap = max(int(eff.shield_max_layers), int(eff.shield_layers_on_deploy))
        if cap <= 0:
            continue
        return {
            "max_layers": cap,
            "layers": int(eff.shield_layers_on_deploy),
            "interval": float(eff.shield_interval),
            "break_heal_ratio": float(eff.shield_break_heal_ratio),
            "break_sp": float(eff.shield_break_sp),
        }
    return None


def _operator_spec(inp, d) -> dict[str, Any]:
    """一名干员的规格。数值取**无技能帧**的那一套，外加技能开启期间的那一套。

    ⚠️ `_range_of()` 读的是 `op.position` / `op.direction`，而这两个字段要等
    `_do_deploy` 才写上。规格是在**跑之前**生成的，所以这里先把它们按这次部署
    填进去（值与模拟器随后要填的完全一样）——不填的话，算出来的是一张以 (0,0)
    为原点的范围表，而且**不会报错**，只会让两边的覆盖格悄悄不同。
    """
    op = operator_of(d)
    op.position = (int(d.position[0]), int(d.position[1]))
    op.direction = d.direction
    # 幂等：正常情况下闸门（`unsupported_reasons`）已经挂过了，这里再挂一次
    # 只是让 `_operator_spec` 单独被调用时也读得到技能。
    _attach_skill_for_spec(d)
    spd = float(getattr(op, "attack_speed", 100.0) or 100.0)
    interval = max(MIN_INTERVAL, float(op.attack_interval) * 100.0 / max(ASPD_MIN, spd))
    cells = range_of(inp.range_provider, char_id=op.char_id, elite=op.elite,
                     direction=d.direction,
                     position=(int(d.position[0]), int(d.position[1])),
                     range_id=op.current_range_id())
    skill, active = skills.skill_spec(inp, d)
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
    # `圣山的祝福`（圣聆初雪的天赋）：**受到致命伤害时不撤退**——免死一次、
    # 满血复活，并冻结自身 `freeze` 秒（原版判在 `take()` 里，unit.py:643-650，
    # 参数在部署时挂上，sim.py:3417-3418）。
    #
    # 两个参数都在部署那一刻就写到了单位上，所以这里直接读即可，不必自己再查
    # 一遍天赋黑板——少一次重算就少一处会漂的口径。
    #
    # ⚠ `c2e_freeze` 那半（触发时**冻结攻击范围内全体敌人** N 秒，sim.py:1069-1090）
    # 未移植：Go 侧没有敌人冻结状态。Go 现在能免死、能自冻结，但不会冻住敌人，
    # 两边因此仍**不必**一致——这一条如实留在 `unsupported_reasons` 里。
    # ⚠ 不能读运行期那两个属性（`op.blessing_save` / `op.blessing_self_freeze`）：
    # 它们由部署钩子在 `sim.py:3417-3418` 挂上，而这份规格是在**部署那一刻**取的
    # ——实测取到的是 0（"规格里是 0、原版跑起来却免死了一次"，两边于是永远差
    # 一条命，而规格看上去"送到了"）。照原版那一句直接查天赋，得到同一个数。
    from ..frontend import talent_finders as _talents
    _bless = _talents.find_blessing(getattr(d, "talents", None) or [])
    _bsave = float(_bless.value("c2e_freeze", 0.0) or 0.0) if _bless else 0.0
    if _bsave > 0.0:
        out["blessing_save"] = _bsave
        out["blessing_self_freeze"] = float(
            (_bless.value("freeze", 0.0) or 0.0) if _bless else 0.0)
    # `层数护盾`（泥岩「沃土予身」/ 空弦「铁弦」）：**次数制抵挡**，一层把这一下
    # 整笔吃掉（原版 `unit.py:613-620`）。没有它的时候，`tr02` 的单人泥岩在原版
    # 前三下**一下都没挨**、在 Go 里每下按 5% 保底扣 14.5 —— 她于是提前阵亡，
    # 判决从"430.13s 零漏"变成"187.33s 三漏"，而**四项里只看得到结果、看不到原因**。
    _sh = _shield_of(d)
    if _sh is not None:
        out["shield"] = _sh
    # 天赋「医者丰碑」（凯尔希 / 凯尔希·思衡托）：「其他友方干员**进入自身攻击
    # 范围时**立刻获得 1 层护盾并额外获得一次**每秒回复 N 点生命值**的增益治疗，
    # 持续 M 秒（**不可叠加**），增益治疗对【罗德岛】干员的效果**翻倍**。」
    #
    # 这个字段**只挂在光环主人自己身上**（范围问的是它本人），不是关卡机制那一层。
    # 和 `blessing_*` 同款理由：`sim.regen_auras` 是**部署那一刻**才 append 的
    # （`sim.py:3423-3434`），而这份规格正是部署那一刻取的——读运行期属性会拿到
    # 空表，而且**不会报错**，只会让 Go 那边静默地少掉一整套机制。
    #
    # ⚠ 原文里的「1 层护盾」**没有黑板键**（层数写在正文里），原版 `RegenAura`
    # 也只兑现了回血那一半（`talents.py:620` 写明了）。所以这里同样只送回血，
    # 两边一致——不是漏了，是照着原版的口径走。
    _rgen_talents = getattr(d, "talents", None) or []
    _regen = _talents.find_regen(_rgen_talents)
    if _regen is not None:
        _mon = _talents.find_medic_monument(_rgen_talents)
        out["regen_aura"] = {
            "hp_per_sec": float(_regen.value("hp_recovery_per_sec", 0.0) or 0.0),
            "duration": float(_regen.value("buff_duration", 0.0) or 0.0),
            # **势力与倍率都从黑板取**，不写死 2.0（原版 `sim.py:3421-3433` 同）。
            "nation": (_talents.RHODES_NATION if _mon is not None else ""),
            "nation_mult": (float(_mon.value("rhodes_bonus", 1.0) or 1.0)
                            if _mon is not None else 1.0),
            # 「进入」的两种读法跟着 `heal_mode` 一起切（原版 `sim.py:2837-2838`）。
            "strict": str(getattr(inp, "heal_mode", "range")) == "target",
        }
    # 势力代号：光环的「对【罗德岛】翻倍」要按**被治者**的势力判，
    # 所以每位干员都得带上自己的。取不到就是空串（等于不翻倍）。
    if getattr(op, "nation_id", ""):
        out["nation_id"] = str(op.nation_id)
    # 主职业代号：**只有一个消费者**——按职业发的全场光环（星熊「特种作战策略」）。
    if getattr(op, "profession", ""):
        out["profession"] = str(op.profession)
    # 这一位干员自己带出去的**全场光环**（天赋）。一个干员可以有多条，
    # 所以是列表。
    #
    # 和 `blessing_*` / `regen_aura` 同款理由：`sim.team_auras` 是**部署那一刻**
    # 才 append 的（`sim.py:3448-3531`），而这份规格正是部署那一刻取的——
    # 读运行期那张表会拿到**空**，而且不会报错。照原版那几段直接查天赋，
    # 得到的是同一批对象。
    auras = _team_auras_of(d, op)
    if auras:
        out["team_auras"] = auras
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
    # ---- 普攻连击（焰狐龙梓兰的**隐藏天赋**）+ 天赋「强击瓶专家」
    #
    # 这两条在 `spec.py` 的上半段**原本是拒绝项**（`combo_hits > 1` 与
    # `power_attack_count` 各挡一道），现在 Go 侧已经兑现，改成送字段。
    #
    # ⚠ 默认值必须按原版抄：`combo_hits` 的"没有这条"是 **1**、`combo_hit_scale`
    # 是 **1.0**、`combo_damage_scale` 是 **1.0**。原版判的是 `> 1`，
    # 写成 0 或漏送会让"每一位没有连击的干员"在 Go 那边被当成连击处理。
    _combo = int(getattr(op, "combo_hits", 1) or 1)
    if _combo > 1:
        out["combo_hits"] = _combo
        out["combo_hit_scale"] = float(
            getattr(op, "combo_hit_scale", 1.0) or 1.0)
        out["combo_damage_scale"] = float(
            getattr(op, "combo_damage_scale", 1.0) or 1.0)
    _pac = int(getattr(op, "power_attack_count", 0) or 0)
    if _pac > 0:
        out["power_attack_count"] = _pac
        out["power_attack_scale"] = float(
            getattr(op, "power_attack_scale", 1.0) or 1.0)
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


def _route_tables(stage) -> dict[int, tuple[list, float, list]]:
    """`{路线号: (折线点, 待命秒数, 分段腿)}`——**与 `sim.py:583-586` 同口径**。

    ⚠ 算一次就够：`route_plans` 里面要走寻路。别放进按敌人循环里。
    """
    out: dict[int, tuple[list, float, list]] = {}
    for i, p in route_plans(stage).items():
        out[i] = (p.points, p.wait, p.legs)
    return out


def _view(inp, *, enemy_id: str, level: int,
          route: list, legs: list, t: float, wait: float = 0.0):
    """造一个敌人的**规格视图**（不是 `EnemyUnit`）。

    ⚠ 与原版 `sim._build_enemy` 的差别只有一处、而且是**去掉**了一个副作用：
    原版会顺手写 `sim.mode_skill` / `sim._mode_next`（所以 `_reborn_summons_spec`
    得靠 `copy.copy(sim)` 绕开），`enemy_view` **不写任何地方**。
    换关卡乘区/难度档位这些仍走同一个 `enemy_at`（原版也是这样），所以不必重实现。
    """
    stats = enemy_stats(inp.enemy_at, inp.stage, enemy_id, level)
    return enemy_view(stats, enemy_id=enemy_id, level=level,
                      route=route, legs=legs, t=float(t), wait=float(wait),
                      species_provider=inp.species_provider)


def _spawn_spec(inp, t: float, sp,
                routes: dict[int, tuple[list, float, list]]) -> dict[str, Any]:
    """一个敌人的规格。

    路线分段从 `routes`（由 `_route_tables` 算一次）取——**与 `sim._spawn` 同一套**：
    有分段腿时开头的待命已经在计划里，不再另设。
    """
    pts, w, legs = routes.get(sp.route_index, ([], 0.0, []))
    # 有分段计划时，开头的待命已经是计划里的 wait 段，别再设一遍
    e = _view(inp, enemy_id=sp.enemy_id, level=sp.level, route=pts, legs=legs,
              t=float(t), wait=0.0 if legs else w)
    out = _unit_spec(inp, e, time=float(t))
    #: **天桩-乙也要从出怪表刷出来**，而且原版对它们照样跑 `_pile_diver_tick`。
    #:
    #: 判据走 `pile_mark_key(sim.stage, e)`——与装置召唤那条链**同一处查表**，不是
    #: 另写一张名字表。理由是"哪些单位是乙"这件事只有一个真相来源
    #: （`PILE_MARK` + 关卡本地 `_dhtb_b` 退到 `prefabKey`）。
    #:
    #: ⚠ 只给**出怪表**的这条路打标：装置召唤出来的甲/乙/天标走
    #: `_unit_spec`（由 `_pile_device_spec` 的模板送给 Go 的机制层），
    #: 那几只是在 Go 的 `m.units` 里被管的。两边都打标会**同一只被推两遍**。
    out["diver"] = bool(pile_mark_key(inp.stage, e))
    if out["diver"]:
        #: 乙咬中之后要挂**天标**，所以模板随它一起送——和机制层
        #: `mech.py::_pile_device_spec` 用的是**同一处口径**（同一张 `PILE_MARK`
        #: 表、同一组常量），不是另写一份。
        #:
        #: ⚠ 天标不只是"给干员掉血的挂件"：它 `hp` 也是 1.0，**会被我方索敌**。
        #: `act31side_09` 的逐笔出手账里原版有一笔 `t=47.1000 → 身上的天标 1.00`
        #: ——只做掉血那一半、不把天标当敌人造出来，会再差一次。
        mark_key = pile_mark_key(inp.stage, e)
        try:
            mark = _view(inp, enemy_id=str(mark_key),
                         level=summon_level(inp.stage, str(mark_key)),
                         route=[(0.0, 0.0)], legs=[], t=0.0, wait=0.0)
        except Exception:                                        # noqa: BLE001
            mark = None
        if mark is not None:
            mspec = _unit_spec(inp, mark)
            #: 「无法攻击/被阻挡」是它的天赋原文：不可阻挡、也不参与索敌优先级。
            mspec["unblockable"] = True
            mspec["attach_damage"] = float(
                getattr(mark, "attach_damage", 0.0) or 0.0)
            #: 附着半径 0.3、贴到目标的判据 0.5——与 `mech.py` 同一处常量。
            mspec["attach_radius"] = 0.3
            out["mark"] = mspec
            out["hit_radius"] = 0.5
    return out


def _unit_spec(inp, e, *, time: float = 0.0) -> dict[str, Any]:
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
        "cannot_clear": bool(cannot_clear(e)),
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
        #: 天赋「不进行远程普通攻击」（prts：玷 / 勿玷）。**这是闸门不是数值**：
        #: 它关掉的是普攻那整条路（原版 `sim.py::_enemies_attack` 里
        #: `if e.skill_atk_no_normal: continue`）。漏送它，Go 就会让这只敌人
        #: 既走技能又走普攻——HS-EX-8 第 2 手多出的两笔 192（勿玷攻击力 600
        #: 打在怒潮凛冬身上）就是这么来的。原版字段在 `unit.py:1326`，值来自
        #: `gamedata/enemy.py:262` 的 `no_normal_ranged`。
        "skill_atk_no_normal": bool(getattr(e, "skill_atk_no_normal", False)),
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
        "reborn_summons": _reborn_summons_spec(inp, e),
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


def _highland_cells(inp) -> list[list[int]]:
    """地图上**高台**格的列表（`[x, y]`）。

    天赋「汹涌怒火」的高台那一半要判"被溅射到的格是不是高台"，而 Go 侧只有
    规格、没有地图。只送这一个布尔分类，不送整张地形——够用且小。
    """
    m = inp.stage.map
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


def _reborn_summons_spec(inp, e) -> list[dict[str, Any]]:
    """重生期召唤的规格：每拍的时间/个数 + **召唤物的完整规格** + 逐格路线表。

    `e.reborn_summons` 是 `(间隔, 每拍个数, 敌人 id)` 的三元组列表（原版
    `_reborn_tick` 4176 行就是这样解包的），"召唤谁"要**现造一只**才知道它长
    什么样——Go 侧没有敌人图鉴，只有规格。

    造模板以前要用 `copy.copy(sim)`：原版 `_build_enemy` 会顺手写
    `sim.mode_skill` 这类"随规格走的"实例状态，直接拿本体造就等于**提前改了
    要跑的那一份**，浅拷贝只是把这些写入留在副本上。

    ⚠ **那个绕法已经不需要了**（本文件不再 `import copy`）：改用 `enemy_view`
    之后"造敌人"**不写任何地方**，副作用没了，副本也就没有意义。
    这也正是为什么"把副作用按归属切开"值得做——它顺手消掉了一处陷阱。

    路线表按**地图每一格**算（`ground_path` 到最近保护目标，与
    `eta.route_plans` 同一个寻路）：召唤那一刻站在哪一格只有跑到才知道，
    而"最近"是按**路径长度**算的（绕远路的直线距离可能更近）。查不到这一格
    时 Go 会当场拒跑——宁可拒跑也不给一条错的路。
    """
    rows = list(getattr(e, "reborn_summons", ()) or ())
    if not rows:
        return []
    #: ⚠ 这里曾经有一句 `import copy`（浅拷贝模拟器造模板）。改用 `enemy_view` 之后
    #: 不再需要——它不写任何地方，见本函数的文档串。

    m = inp.stage.map
    paths: dict[str, list[list[int]]] = {}
    for x in range(int(getattr(m, "width", 0))):
        for y in range(int(getattr(m, "height", 0))):
            if not m.walkable(x, y):
                continue
            p = path_from(inp.stage, (x, y))
            if p:
                paths[f"{x},{y}"] = [[int(a), int(b)] for a, b in p]
    out: list[dict[str, Any]] = []
    for itv, cnt, key in rows:
        level = summon_level(inp.stage, str(key))
        #: 腿留空：真正那条腿由 Go 按召唤那一刻的格子从 `paths` 里取。
        #:
        #: ⚠ 以前这里是 `probe = copy.copy(sim)` 再 `probe._build_enemy(...)`——
        #: 因为原版的"造敌人"会顺手写 `sim.mode_skill`，直接拿本体造就等于
        #: **提前改了要跑的那一份**。改用 `enemy_view` 之后那个绕法自然消失：
        #: 它**不写任何地方**。
        unit = _view(inp, enemy_id=str(key), level=level,
                     route=[(0.0, 0.0)], legs=[], t=0.0, wait=0.0)
        out.append({
            "interval": float(itv),
            "count": int(cnt),
            "template": _unit_spec(inp, unit),
            "paths": paths,
        })
    return out


def build_spec(inp, *, stage_label: str = "", allow_devices: bool = False,
               allow_skills: bool = False, mechanisms: Iterable[str] = (),
               schedule=None, env=None) -> dict[str, Any]:
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
    #: ⚠ **本函数也要一份 `sch`**：闸门那几条住在 `unsupported_reasons()` 里、
    #: 部署循环住在这里，两处是**两个函数**，各要各的。只在一处定义会
    #: `NameError: name 'sch' is not defined`——而它会被上层记成"规格抄不到"，
    #: 看起来像"这次改动把规格改坏了"。口径与 `unsupported_reasons` 里那份一致。
    sch = schedule if schedule is not None else inp

    #: ⚠ **关卡静态那 8 项**（`fps` / `speed_scale` / `ranged_enemies` /
    #: `enemy_windup` / `cost_init` / `cost_max` / `cost_time` / `life`）
    #: 同样从**新家** `frontend/stage_env.py` 取，不再从模拟器上读**派生后**的值。
    #:
    #: ⚠ **两个数别混**：`env` 承载、并在本函数末尾被消费的是这 **8** 项
    #: （`stage_env.ENV_KEYS` 就是这 8 个；取用点 `spec.py:1197`／`:1206-1212`）；
    #: 而 `env` **缺席**时改由 `inp` 现取的是**另外 5** 项
    #: （`fps`／`speed_scale`／`ranged_enemies`／`enemy_windup` ＋ `environment_difficulty`，
    #: 见 `:1150-1160`）。后者只有 5，是因为 `cost_init`／`cost_max`／`cost_time`／`life`
    #: **根本不是 `SpecInputs` 的字段**（`SpecInputs` 实测 23 个字段，这四个不在其中）
    #: ⇒ **「8」与「5」量的是两个不同的量，别把后者当前者**
    #: （依据：2026-09-20 后端2 复核，三组坐标同 `tools/parity_ledger.py` 该处登记）。
    #:
    #: 为什么必须从**构造参数**重算而不是继续读 `sim.*`：`sim.speed_scale` 已经
    #: 乘过关卡的 `move_multiplier`、`sim.enemy_windup` 已经夹过零——那是
    #: **派生的结果**，反推不回原始参数。`stage_env` 拿原始参数算一遍，
    #: 得到的值与模拟器**逐字相同**（`stage_env` 就是照 `sim.py:418-440` 搬的），
    #: 但它不欠 `battle/` 一分钱。
    #:
    #: 迁移期：调用方（`verify.py::run`）给了 `env` 就用它；没给就自己算一份 +
    #: 从模拟器上补齐那四项（兜底，行为与迁移前一致）。
    if env is None:
        env = dict(stage_env(
            inp.stage,
            #: ⚠ 现算这条也要带上难度：`inp.environment_difficulty` 为空时退回
            #: **关卡自己**那一档（`Stage.difficulty`，来源是关卡索引）。口径与
            #: `frontend/inputs.py::_env_difficulty` 同，改一处要改两处。
            environment_difficulty=str(
                getattr(inp, "environment_difficulty", "") or
                getattr(getattr(inp, "stage", None), "difficulty", "") or
                "NORMAL")))
        env.update({
            "fps": int(inp.fps),
            "speed_scale": float(inp.speed_scale),
            "ranged_enemies": bool(inp.ranged_enemies),
            "enemy_windup": float(inp.enemy_windup),
        })

    mechanisms = list(dict.fromkeys([*mech.names_for(inp), *mechanisms]))
    mech_config: dict[str, Any] = {}
    if mech.FARMLAND_ID in mechanisms:
        farm = mech.farmland_spec(inp)
        if farm is not None:
            mech_config[mech.FARMLAND_ID] = farm
    if mech.SNOW_ID in mechanisms:
        snow_cfg = snow_mech_spec(inp, deployments=sch.deployments)
        if snow_cfg is not None:
            mech_config[mech.SNOW_ID] = snow_cfg
    operators: list[dict[str, Any]] = []
    deploys: list[dict[str, Any]] = []
    for d in sorted(sch.deployments, key=lambda d: d.time):
        operators.append(_operator_spec(inp, d))
        deploys.append({
            "time": float(d.time),
            "index": len(operators) - 1,
            "char_id": operator_of(d).char_id,
            "cost": int(operator_of(d).deploy_cost),
            # 显式送：Go 侧的零值是 False，而原版的默认是 True（`Deployment.auto_skill`）
            "auto_skill": bool(getattr(d, "auto_skill", True)),
        })
    #: ⚠ 算**一次**：`route_plans` 里面要走寻路，放进按敌人循环里会重算几百遍。
    routes = _route_tables(inp.stage)
    #: ⚠ **不再读 `sim._spawns`**：那是模拟器在构造时把 `stage.timeline()`
    #: 排好序之后存下的（`sim.py:557`）。出怪表是**关卡数据**，直接从关卡取，
    #: 排序口径也照同一处（`stage.timeline()` 自己就是按时刻排好的，模拟器
    #: 那次 `sorted` 只是保险）。
    spawns = [_spawn_spec(inp, t, sp, routes) for t, sp in inp.stage.timeline()]
    skill_uses = [{"time": float(u.time),
                   "cell": [int(u.position[0]), int(u.position[1])]}
                  for u in sch.skill_uses]
    #: 关卡静态那 8 项**已经**在本函数开头由 `env` 备好了（口径与出处见那里）。
    #: ⚠ 这个 **8** 指 `env` 承载并被消费的量；「`env` 缺席时由 `inp` 现取的 **5** 项」
    #: 是**另一个量**，别混（坐标见 `:1138` 那一段）。
    return {
        "stage": stage_label or str(getattr(inp.stage, "code", "") or ""),
        "fps": int(env["fps"]),
        # ⚠ 不能写死 600：原版的 `BattleSimulator.run(max_time=600.0)` 只是**默认**，
        # 而验证这一路调的是 `sim.run(max_time=900.0)`（`verifier.py:93` 与
        # `verify.py:410`）。写死 600 会让"打到 814 秒才赢"的作业在 Go 侧被
        # **截断在 600 秒**——判决从"胜利"变成"超时"，而且看不出是截断造成的。
        #
        # `sim` 自己不一定记着这个数（它是 `run` 的形参），所以回退到 900——
        # 那就是上面两处调用点用的值。哪天上游改成按关卡给，这里会自己跟上。
        "max_time": float(getattr(inp, "max_time", 0.0) or 900.0),
        "life": env["life"],
        "cost_init": env["cost_init"],
        "cost_max": env["cost_max"],
        "cost_time": env["cost_time"],
        "enemy_windup": float(env["enemy_windup"]),
        "ranged_enemies": bool(env["ranged_enemies"]),
        "speed_scale": float(env["speed_scale"]),
        # 高台格：Go 没有地图，而天赋「汹涌怒火」的高台那一半要判"被溅射到的格
        # 是不是高台"。只在这条特性真在场时才送（通用关卡一帧都不多花）。
        "highland_cells": _highland_cells(inp) if any(
            float(getattr(operator_of(d), "highland_splash_scale", 0.0) or 0.0) > 0.0
            for d in sch.deployments) else [],
        # 防守点格：只有积雪在场时才需要（它的满层冻结对终点格豁免）。
        # Go 侧的 `IsGoalCell` 每帧每个敌人问一次，空列表的代价可忽略。
        "goal_cells": [[x, y] for x, y in sorted(_find_goals(inp))]
        if mech.SNOW_ID in mechanisms else [],
        "operators": operators,
        "deploys": deploys,
        "spawns": spawns,
        "skill_uses": skill_uses,
        "unsupported": unsupported_reasons(
            inp, allow_devices=allow_devices, allow_skills=allow_skills,
            schedule=schedule),
        "mechanisms": mechanisms,
        "mech_config": mech_config,
    }
