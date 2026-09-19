"""技能（通用核心）：翻译成 rios-sim 的**状态机参数 + 两套数值**。

## 为什么这样切

原版把技能拆成两件事：**什么时候开/开多久**（`sim._skill_tick` 那张状态机），
与**开着的时候数值是多少**（`OperatorUnit.current_*()` 读 `op.effects`）。
Go 版要快，但**不能把效果模型抄第二遍**——那是全仓最容易漂的一层。

所以这里切成：

* **状态机**（攒技力、能不能开、持续时间、弹药、被动）→ 交给 Go，参数是
  `sp_type / sp_cost / init_sp / increment / max_charge / duration / …`；
* **数值**（攻击力、防御、法抗、攻击间隔、伤害类型、目标数、倍率、连击数）
  → 在 Python 侧算好**两套**：不开启的那套（`OperatorSpec` 顶层）与开启期间的
  那套（`active` profile）。

两套数值都是**拿原版自己的读数函数读出来的**（`current_atk()` / `current_defense()`
/ `current_res()` / `current_interval()` / `current_max_target()` / `active_attack_type()`
与 `effects.*`），做法是临时把那三个决定"这一帧开没开技能"的字段摆成开启态、
读完再原样放回。这不是重写效果模型，是**借用**它。

## 只收一个**白名单**

`SkillEffects` 有六十来个字段，一个技能只要有一个落在白名单外就**拒跑**。
判据不是"我以为这个字段没事"，而是逐字段读出来跟 dataclass 的默认值比：

* `buffs` 只许 `atk / def / res / attack_speed / cost`；
* `damage` 只许 `atk_scale / atk_scale_2 / atk_scale_other / times /
  max_target / ammo`（后三个里 `atk_scale_2` 与 `atk_scale_other` 在
  **战斗结算里根本没有读者**，只有 `final_hit_scale` 那一层会用到"末击加倍"，
  这一点是逐处核过 `battle/` 的）；
* 标量只许 `true_damage / final_hit_scale / once_per_battle / multi_hit /
  repeat_hits / volley_arrows / landing_scale`（后四个都只经由 `hit_count`
  影响结算，`hit_count` 由 Python 算好送来）；
* 其余字段必须等于默认值，否则拒跑。

**新字段自动落进"不支持"**——这是白名单而不是黑名单的理由：以后谁往
`SkillEffects` 里加一个字段，Go 侧不会默默按旧口径跑。

## 描述驱动的钩子

原版有几处不看黑板、看**描述文本**：剑气（`"剑气" in description`）、
描述编译效果（`effect_source != "blackboard"`）。前者这里显式挡掉；
后者**照原样复现**：`effects_of()` 走的就是 `resolved_effects(policy)` 那条路。
"""

from __future__ import annotations

import dataclasses
from typing import Any

#: ⚠ 干员一律走这个入口取，**不要直接写 `d.operator`**——那个是活的
#: `OperatorUnit`（Python 引擎要拿它跑帧），技能规格只要开局那一组字段。
from ..frontend.schedule import operator_of

#: 允许非默认的 `buffs` 键
#:
#: `attack_interval` 是**加算秒数**的攻速修正（`SkillLevel.attack_interval`：
#: 先加秒数、再按总攻速折算），它的结果就是 `current_interval()` 那一个数，
#: 而那个数由 Python 算好送过来——Go 侧一行都不用改。挡着它等于白挡掉 99 条技能。
_ALLOWED_BUFFS = frozenset({"atk", "def", "res", "attack_speed",
                            "attack_interval", "cost"})
#: 允许出现的 `damage` 键（`atk_scale_2` / `atk_scale_other` 在战斗结算里无读者）
_ALLOWED_DAMAGE = frozenset({"atk_scale", "atk_scale_2", "atk_scale_other",
                             "times", "max_target", "ammo"})
#: 允许非默认的标量字段
_ALLOWED_SCALARS = frozenset({"true_damage", "final_hit_scale",
                              "once_per_battle", "multi_hit", "repeat_hits",
                              "volley_arrows", "landing_scale"})
#: 纯记账的字段，不影响结算
_BOOKKEEPING = frozenset({"units", "variant_units", "classified", "total"})


def _default_of(f) -> Any:
    """dataclass 字段的默认值（`default_factory` 的也算）。"""
    if f.default is not dataclasses.MISSING:
        return f.default
    if f.default_factory is not dataclasses.MISSING:      # type: ignore[misc]
        return f.default_factory()                        # type: ignore[misc]
    return None


def effects_of(sim, op):
    """这名干员**技能开启时**真正会被读的那份效果对象。

    与 `OperatorUnit.effects`（`unit.py` 的 property）＋ `_bind_skill`
    （`sim.py` 里那段 `resolved_effects`）逐条对齐：优先 `effects_override`，
    否则按 `effect_source` 策略用描述补一次黑板。**不改任何状态**——这里只是
    算出"运行时会用哪一份"，不把它写回干员身上。
    """
    sk = getattr(op, "skill", None)
    if sk is None:
        return None
    override = getattr(op, "effects_override", None)
    if override is not None:
        return override
    policy = getattr(sim, "effect_source", "blackboard") or "blackboard"
    if policy != "blackboard":
        try:
            resolved, _diffs = sk.resolved_effects(policy)
        except Exception:                                     # noqa: BLE001
            resolved = None          # 与原版一致：解析失败就沿用黑板
        if resolved is not None:
            return resolved
    return getattr(sk, "effects", None)


def _field_reasons(eff) -> list[str]:
    """逐字段扫一遍效果对象，返回白名单外的那些。"""
    bad: list[str] = []
    for f in dataclasses.fields(eff):
        name = f.name
        if name in _BOOKKEEPING:
            continue
        val = getattr(eff, name, None)
        default = _default_of(f)
        if val == default:
            continue
        if name == "buffs":
            extra = sorted(set(val) - _ALLOWED_BUFFS)
            if extra:
                bad.append("面板增益：" + "/".join(extra))
            continue
        if name == "damage":
            extra = sorted(set(val) - _ALLOWED_DAMAGE)
            if extra:
                bad.append("技能倍率/计数：" + "/".join(extra))
            continue
        if name in _ALLOWED_SCALARS:
            continue
        bad.append(f"技能效果 {name}")
    return bad


def port_reasons(sim, op) -> list[str]:
    """这名干员的技能**能不能**交给 Go 跑；不能就逐条给理由（空 = 能）。"""
    sk = getattr(op, "skill", None)
    if sk is None:
        return []
    bad: list[str] = []
    eff = effects_of(sim, op)
    if eff is None:
        return ["技能没有效果对象"]
    if getattr(sk, "range_id", None):
        bad.append("技能改写攻击范围")
    if getattr(sk, "duration_type", "NONE") not in ("NONE", "AMMO"):
        bad.append(f"持续时间类型 {sk.duration_type}")
    if "剑气" in (getattr(sk, "description", "") or ""):
        # 原版这一条**不看黑板、看描述**（`_spawn_qi`）。白名单扫不出来。
        bad.append("剑气（描述驱动）")
    bad += _field_reasons(eff)
    if getattr(eff, "variants", None):
        bad.append("技能变体（第二次及以后换一套数值）")
    if getattr(op, "effects_override", None) is not None and \
            getattr(op, "effects_override", None) is not eff:
        bad.append("效果覆盖（effects_override）")
    # 注意：`effects_override` 是**运行时**才写上的，所以上面那条只在
    # "已经跑过一遍的 sim" 上才会命中；规格是从**没跑过的** sim 上取的，
    # 这条留着是为了让"拿跑过的 sim 生成规格"这种误用不至于静默出错。
    return _dedup(bad)


def _dedup(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


# ---------------------------------------------------------------- 数值两套


def _max_hp_after_bonus(op, eff) -> float:
    """技能开着时的生命上限（原版 `apply_max_hp_bonus` 那一式的**求值**）。

    `基准 × (1 + pct)`，`pct` 取 `effects.buffs["max_hp"]`——与
    `sim.py:2498` 施加时读的是同一个键，不另立一份口径。

    基准取 `_base_max_hp`：原版只有"身上已经有加成"时它才非 0（unit.py:949），
    此时当前值已经被乘过一次，拿它当基准会越算越大。
    """
    base = float(getattr(op, "_base_max_hp", 0.0) or 0.0)
    if base <= 0.0:
        base = float(op.max_hp)
    pct = float((getattr(eff, "buffs", None) or {}).get("max_hp", 0.0) or 0.0)
    return base * (1.0 + pct)


def _profile(sim, op, *, active: bool) -> dict[str, Any]:
    """一名干员的数值快照。

    `active=False` 是**不开启**的那套（与 `spec._operator_spec` 现在读的完全一致）；
    `active=True` 临时把状态摆成"技能开着"，读完立刻还原。

    摆的三个字段就是 `OperatorUnit.effects` 这个 property 读的那三个
    （`skill_active` / `skill` / `effects_override`），外加 `skill_attack_type`
    ——它是 `_activate` 根据 `true_damage` 写上的，`active_attack_type()` 读它。
    **用 try/finally 还原**：读的时候抛异常也不能把状态留在"技能开着"上，
    否则后面生成的规格会把一名干员当成全程开着技能。

    ⚠️ **可选数值一律"没有就不出现"，绝不许写 `None`**：Go 那边的 `float64`
    收到 JSON 的 `null` 会变成 0，而 0 在数值位置上全都是合法值
    （0 倍率 = 打不死人、0 秒 = 瞬发），没有一种能在下游看出来的。
    实测被 `final_hit_scale` 咬过一口：单发攻击的最后一击倍率变成 0，
    整局只表现为"这名干员打不死人"。
    """
    saved = (op.skill_active, op.skill_attack_type, op.effects_override)
    if active:
        eff = effects_of(sim, op)
        op.skill_active = True
        op.effects_override = eff
        op.skill_attack_type = ("TRUE" if getattr(eff, "true_damage", False)
                                else None)
    try:
        eff = op.effects if active else None
        out = {
            "atk": float(op.current_atk()),
            "def": float(op.current_defense()),
            "res": float(op.current_res()),
            "interval": float(op.current_interval()),
            "damage_type": str(op.active_attack_type() if active
                               else op.attack_type),
            "max_target": int(op.current_max_target() if active else 1),
            "atk_scale": float(getattr(eff, "atk_scale", 1.0)) if active else 1.0,
            "hit_count": int(getattr(eff, "hit_count", 1)) if active else 1,
            #: 技能开启期间的**生命上限**（原版 `sim.py:2498` →
            #: `unit.py:947`：`apply_max_hp_bonus(buffs["max_hp"])`，即
            #: `上限 = 基准 × (1 + pct)`，同时 `hp += 基准 × pct`；
            #: 关技能时 `revert_max_hp_bonus` 还原并把血量按新上限夹一次）。
            #:
            #: ⚠ 不能直接读 `op.max_hp`：那是**主循环施加之后**的值，而
            #: "主循环此刻是否正开着技能"与"这份快照是按 active=True 取的"
            #: 是两件事。照原版那一句现算才不受调用时机影响。
            #: 基准取 `_base_max_hp`（有加成在身时它才是基准，为 0 表示
            #: 身上没有加成、当前值就是基准）。
            #:
            #: 这一段曾经**整条没送**：规格里的 `max_hp` 只有开场那一个静态
            #: 值，于是"开技能把生命上限翻倍"的干员在 Go 侧少了一半血——
            #: HS-EX-8 第 3 手圣聆初雪承受 2058 就倒，原版要到 4116（正好
            #: 一半），整局因此短了 18 秒。
            "max_hp": (_max_hp_after_bonus(op, eff) if active
                       else float(op.max_hp)),
        }
        if active:
            final = getattr(eff, "final_hit_scale", None)
            if final is not None:
                out["final_hit_scale"] = float(final)
            # 技能给的闪避（原版 `sim.py:2018-2019` 把这两个值写进
            # `op.dodge_phys/arts`，`_deactivate` 清零）。**照送不误**，
            # 哪怕当前白名单里没有一个技能带它：`dodge_*` 不在
            # `_ALLOWED_*` 字段表里，带闪避的技能会被闸门整条拒跑，
            # 所以送到这里必然是 0。真送了才有意义——哪天白名单放开，
            # 两边不必再改一次衔接（而"Go 侧那两个字段恒为 0"这种假设，
            # 正是这一路上最容易悄悄不成立的东西）。
            for key in ("dodge_phys", "dodge_arts"):
                value = float(getattr(eff, key, 0.0) or 0.0)
                if value:
                    out[key] = value
        return out
    finally:
        op.skill_active, op.skill_attack_type, op.effects_override = saved


def skill_spec(sim, d) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    """`(状态机参数, 开启期间的数值)`；没有技能槽就是 `(None, None)`。

    `d` 是这次部署（`Deployment`）——技能等级已经由调用方绑到 `d.operator.skill`
    上了（原版在 `_bind_skill` 里绑，见 `spec.build_spec` 的说明）。
    """
    op = operator_of(d)
    sk = getattr(op, "skill", None)
    if sk is None:
        return None, None
    eff = effects_of(sim, op)
    ammo = 0
    if getattr(sk, "duration_type", "NONE") == "AMMO":
        ammo = int((getattr(eff, "ammo", None) or 0))
    # 持续时间照 `SkillLevel.effective_duration` 那一条口径走：
    # `None` 表示**无限**，而它有三种来路——弹药类（打光才结束）、
    # 描述里明写「持续时间无限」的、以及 durationType 就是 INFINITE 的。
    # 只看 `sk.infinite` 会把弹药类读成 0 秒（＝瞬发），技能开启的那一帧就结束，
    # 而且是**静默**的：判决只会表现为"开了技能但伤害没变"。
    dur = sk.effective_duration
    state = {
        "sp_type": str(sk.sp_type),
        "passive": bool(sk.is_passive),
        "auto_trigger": bool(sk.auto_trigger),
        "sp_cost": float(sk.sp_cost),
        "init_sp": float(sk.init_sp),
        "increment": float(sk.increment),
        "max_charge": int(sk.max_charge),
        "duration": 0.0 if dur is None else float(dur),
        "infinite": dur is None,
        "ammo": ammo,
        # 持续时间类型（`AMMO` = 弹药类）。**只有一个消费者**：队友天赋里那条
        # 「**携带**弹药类技能的干员攻击力 +9%」（新约能天使「铳弹协约」，
        # `ammo_skill_only`）——它判的是"这个人装备的是不是弹药技能"，
        # **与技能开没开无关**（正文写的是「携带」）。所以这个字段必须送，
        # 不能拿 `ammo > 0` 顶替：那个是"打光就结束"的运行时表现，语义不同。
        "duration_type": str(getattr(sk, "duration_type", "NONE") or "NONE"),
        "once_per_battle": bool(getattr(eff, "once_per_battle", False)),
        "cost_gain": float(getattr(eff, "buffs", {}).get("cost", 0.0)),
    }
    return state, _profile(sim, op, active=True)
