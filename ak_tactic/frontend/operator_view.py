# -*- coding: utf-8 -*-
"""一个干员的**规格视图**——`build_spec` 要的那组字段，不需要一个活的对象。

⚠ **本文件由 `tools/gen_operator_view.py` 从 `battle/unit.py` 机械生成，不要手改。**
改口径请改生成器再重跑，这样两边永远取的是同一段源码。

## 它是干什么的

`OperatorUnit` 是 **134 字段的 dataclass、846 行**——其中绝大多数是**跑帧**
（位移、碰撞、技力、护盾、站场），规格一行都不碰。

规格真正要的只有三样：

* `verify.py::unit` 建的那个 `kw`（35 键，来自 `OperatorCalculator` ＋ 天赋 ＋ 特性文本）
* `kw` 没给的那些字段的**默认值**（本文件照 `OperatorUnit` 的 dataclass 右值抄）
* **现算的方法**：7 个（`current_atk` / `current_defense` / `current_res` / `current_interval` / `current_attack_speed` / `current_max_target` / `active_attack_type`）＋ `current_range_id`（转调 `geometry`，不住 `METHODS`）

⇒ 视图 = 这三样。`spec.py::_operator_spec` 是 `getattr` 式的读法，喂得饱。

## ⚠ 口径的边界

* `effects`（技能效果）在这里是**普通属性**，不是 property —— 因为 `kw` 里不带它，
  而规格取的是**开局态**（技能还没开、`skill_active` 为假、`effects` 为 None）。
  原版那个 property 的三行判断照抄在 `__init__` 里。
* `position` / `direction` 会被 `spec.py` **在读到之前改写**
  （`spec.py:687-688`：`op.position = d.position`），所以视图必须允许写。
* 跑帧才会变的那些字段（`hp` / `hits` / `sp` / 护盾…）**照抄默认值**——
  规格就在开局那一刻取，它们就该是那个值。
"""
from __future__ import annotations

from typing import Any

from .geometry import current_range_id as _current_range_id

__all__ = ["OperatorView", "operator_view"]


#: 下面这几行是 `OperatorUnit` 的**模块级常量**，由生成器按需带过来
#: （默认值表达式引用到它们，比如 `block_tol2 = POSITION_TOL * POSITION_TOL`）。

ASPD_MIN = 20.0
MIN_INTERVAL = 0.05
POSITION_TOL = 0.35


class OperatorView:
    """一个干员的规格视图。**字段名与 `OperatorUnit` 逐个相同。**"""

    def __init__(self, kw: dict[str, Any], **overrides: Any) -> None:
        # ---- `kw` 没给的那些：照 `OperatorUnit` / `Combatant` 的 dataclass 默认值
        self.attack_interval = 1.0
        self.attack_type = 'PHYSICAL'
        self.hp = -1.0
        self.damage_taken = 0.0
        self.death_time = -1.0
        self.char_id = ''
        self.summon_of = ''
        self.profession = ''
        self.nation_id = ''
        self.position = (0, 0)
        self.direction = 'Right'
        self.block_cnt = 0
        self.deploy_cost = 0
        self.talents = list()
        self.redeploy_time = 70.0
        self.elite = 2
        self.attack_speed = 100.0
        self.aspd_when_free = 0.0
        self.aspd_high_ground = 0.0
        self.high_ground_neighbor = False
        self.heals = False
        self.weakness_damage = False
        self.splash_radius = 0.0
        self.splash_scale = 0.0
        self.splash_damage_scale = 1.0
        self.highland_splash_scale = 0.0
        self.highland_splash_sluggish = 0.0
        self.combo_hits = 1
        self.combo_hit_scale = 1.0
        self.combo_damage_scale = 1.0
        self.charge_extra_ready = False
        self.charge_extra_arrows = 0
        self.charge_extra_scale = 0.0
        self.power_attack_count = 0
        self.power_attack_scale = 1.0
        self.power_attack_left = 0
        self.mobility_atk_bonus = 0.0
        self.mobility_atk_duration = 0.0
        self.mobility_atk_pct = 0.0
        self.mobility_atk_left = 0.0
        self.mobility_melee_deploy = False
        self.mobility_deploy_range = ''
        self.mobility_leftover = ''
        self.no_respawn_cost_add = False
        self.hammer = None
        self.hammer_pending = list()
        self.hammer_step = 0
        self.effects_override = None
        self.healing_done = 0.0
        self.regen_left = 0.0
        self.regen_per_sec = 0.0
        self.sp_per_attack_talent = 0.0
        self.sp_per_kill_talent = 0.0
        self.skill = None
        self.auto_skill = True
        self.skill_active = False
        self.sp = 0.0
        self.sp_charges = 0
        self.skill_request = False
        self.skill_timer = 0.0
        self.ammo_left = 0
        self.skill_attack_type = None
        self.stun_timer = 0.0
        self.retreated = False
        self.left_at = -1.0
        self.slash_pending = False
        self.kill_stacks = 0
        self.aura_atk_pct = 0.0
        self.aura_def_pct = 0.0
        self.dodge_phys = 0.0
        self.dodge_arts = 0.0
        self.talent_dodge_phys = 0.0
        self.talent_dodge_arts = 0.0
        self.barrier = 0.0
        self.barrier_decay_per_sec = 0.0
        self.barrier_breaks = 0
        self.barrier_break_hooks = list()
        self.trait_blackboard = dict()
        self.token_key = ''
        self.cost_refunded = False
        self.skill_slot = 0
        self.delivery_left = 0
        self.shield_layers = 0
        self.shield_timer = 0.0
        self.shield_interval = 0.0
        self.shield_max_layers = 0
        self.shield_break_heal = 0.0
        self.shield_break_sp = 0.0
        self.shield_breaks_taken = 0
        self.block_radius_scale = 0.0
        self.block_tol2 = POSITION_TOL * POSITION_TOL
        self.stand_duration = 0.0
        self.stand_timer = 0.0
        self.stand_form = ''
        self.stand_atk_pct = 0.0
        self.stand_hp_pct = 0.0
        self.stand_interval_add = 0.0
        self.stand_sluggish = 0.0
        self.stand_sluggish_pending = 0.0
        self.stand_max_target = 0
        self.stand_heal_scale = 0.0
        self.stand_kill_scale = 0.0
        self.stand_kill_damage = 0.0
        self.stand_heal_targets = 0
        self.stand_kill_timer = 0.0
        self.stand_killed = set()
        self.stand_heal_timer = 0.0
        self.stand_heal_queue = list()
        self.stand_ta_scale = 0.0
        self.stand_ta_count = 1.0
        self.stand_ta_ratio = 1.0
        self.stand_can_hit_air = False
        self.stand_keep_block = False
        self._stand_base_max_hp = 0.0
        self._stand_base_block = -1
        self.barrier_absorbed = 0.0
        self.blessing_save = 0.0
        self.blessing_self_freeze = 0.0
        self.blessing_cold = 0.0
        self.blessing_used = False
        self.blessing_freeze = 0.0
        self.freeze_timer = 0.0
        self._base_max_hp = 0.0
        self.blocking = list()
        self.attack_timer = 0.0
        self.hits = 0
        self.trigger_hits = 0
        self.hp_drain_per_sec = 0.0
        self.locked_timer = 0.0
        self.skill_use_count = 0
        self.cost_trickle_left = 0.0
        self.cost_trickle_per = 0.0
        self.cost_trickle_interval = 0.0
        self.cost_trickle_timer = 0.0
        self.cost_trickle_rate = 0.0
        self.aspd_steal_bonus = 0.0
        self.aspd_loss = 0.0
        self.steal_target = None
        self.steal_amount = 0.0

        # ---- `kw` 覆盖默认值（`kw` 是权威：来自 `OperatorCalculator`）
        for _k, _v in kw.items():
            setattr(self, _k, _v)
        # ---- 调用方显式给的（`position` / `direction` 这类）
        for _k, _v in overrides.items():
            setattr(self, _k, _v)

    @property
    def effects(self):
        """当前生效的技能效果；技能没开就是 None。

        `effects_override` 是模拟器按 `effect_source` 策略解析出来的那份
        （描述驱动的那一层），设了就优先用它。
        """
        if self.skill_active and self.skill is not None:
            if self.effects_override is not None:
                return self.effects_override
            return getattr(self.skill, "effects", None)
        return None

    def current_atk(self) -> float:
        """当前**面板**攻击力——开技能期间含攻击力增益、击杀叠层与全场光环。

        **不含技能倍率**（`effects.atk_scale`）。倍率只在
        `damage.resolve_damage(scale=…)` 那一处乘（2026-09-18 博士裁定，
        缘由见 `SkillEffects.attack_power` 的说明：裁定前它与平A 循环各乘一次，
        同一份倍率乘了两次）。所以本属性的含义是"这一帧的攻击力面板"，
        与开不开技能都读得通——积雪踏入伤害、持续伤害的每秒量、全场总攻击
        这些消费者要的都是这个量。

        注意 `effects is None`（这一帧没开技能）的分支**也要算全场光环**：
        「青色怒火」是发给所有友方的，不挑对方开不开技能。早期版本在这个分支
        直接 `return self.atk`，症状是光环只对开着技能的人生效、对队友一点用没有。
        """
        e = self.effects
        # 天赋「翔虫机动」的限时加成**开不开技能都在**（它挂在部署那一刻，
        # 不是技能 buff），所以两个分支都要加——与全场光环同理。
        mob = self.mobility_atk_pct
        # 〈替身〉形态的面板增益**只在替身形态里**算：它是形态自己的攻击力改写，
        # 不是常驻天赋。不设这道门，本体也会吃到 +80%（症状是本体凭空变强，
        # 而替身看起来"没有加成"——因为两边算出来一样）。
        stand = self.stand_atk_pct if self.stand_timer > 0.0 else 0.0
        if e is None:
            return self.atk * (1.0 + self.aura_atk_pct + mob + stand)
        # 击杀叠层的加成与普通攻击力增益**同层相加**（都进 `(1 + 攻击力增益)`
        # 这个括号），不乘在外面——三层的 +40% 是 +120%，不是 1.4³。
        pct = 0.0
        if self.kill_stacks:
            v = e.variants.get("kill") or {}
            pct = float(v.get("atk", 0.0)) * self.kill_stacks
        # 全场光环（青色怒火）同样是**同层相加**的百分比加成。
        # `stand_atk_pct`（〈替身〉形态的攻击力 +40/60/80%）也进这个括号：
        # 它是**形态自己的面板增益**，与开不开技能无关——事实上他进替身时技能
        # 已经结束了（`effects is None` 那条分支同样要加）。
        return self.atk * (1.0 + e.atk_pct + pct + self.aura_atk_pct + mob
                           + stand)

    def current_defense(self) -> float:
        e = self.effects
        if e is None:
            return self.defense * (1.0 + self.aura_def_pct)
        return self.defense * (1.0 + e.buffs.get("def", 0.0) + self.aura_def_pct)

    def current_res(self) -> float:
        """当前法术抗性——含技能增益与**击杀叠层**的固定值加成。

        此前敌人打干员时直接读 `op.res`，把技能自带的 `magic_resistance`
        增益整个漏掉了；顺带把击杀叠层也接上。两者都是**固定值**相加。
        """
        e = self.effects
        if e is None:
            return self.res
        res = self.res + float(e.buffs.get("res", 0.0))
        if self.kill_stacks:
            v = e.variants.get("kill") or {}
            res += float(v.get("res", 0.0)) * self.kill_stacks
        return res

    def current_interval(self) -> float:
        """当前攻击间隔——**平A 也按攻速折算**，开技能期间再叠技能修正。

        旧写法在没有技能效果时直接返回 `attack_interval`，等于把攻速整个丢掉：
        天赋与模组的攻速在平A 期间一律不生效，出手频率只剩基础值。攻速正好是
        100 时两种写法等价，所以这个缺口一直没露出来。
        """
        spd = self.current_attack_speed()
        # 〈替身〉形态的"**攻击间隔增大**"（天赋「不羁之力」的 `base_attack_time`
        # +0.4 秒）。它是**加在基础间隔上**的，不是攻速修正——两者不可互换：
        # 加 0.4 秒间隔与"减若干攻速"在非线性处结果并不相同，而正文写的是前者。
        base_iv = self.attack_interval + (self.stand_interval_add
                                          if self.stand_timer > 0.0 else 0.0)
        e = self.effects
        if e is None:
            return max(MIN_INTERVAL, base_iv * 100.0 / max(ASPD_MIN, spd))
        return e.attack_interval(base_iv, spd)

    def current_attack_speed(self) -> float:
        """当前总攻速——含「未阻挡敌人时」的条件加成。

        攻速是**实时**量：模组特性给的那 8 点只在没挡住人时才有，
        所以不能在建单位那一步就并进 `attack_speed`。
        """
        spd = self.attack_speed
        if self.aspd_when_free and not self.blocking:
            spd += self.aspd_when_free
        # 「自身周围四格有高台时」的额外攻速（阿斯卡纶「噬光残影」）。
        # 与上面那条**不同**：它的条件不是实时状态，而是**地形**——伏击客
        # 不移动，所以 `high_ground_neighbor` 由模拟器在**部署那一刻**按地图
        # 判一次就定死（见 `sim` 的部署处）。
        if self.aspd_high_ground and self.high_ground_neighbor:
            spd += self.aspd_high_ground
        # 偷来的 / 被偷走的攻击速度（新约能天使技2「开火成瘾症」）。
        # 两条都走这里，是因为**两边都是实时量**：被偷者在她开技期间一直少
        # 这 70 点，她一结束就还回去。下限（`ASPD_MIN`）不在这里夹——
        # 它由 `current_interval` 那一层管，免得两个地方各夹一次。
        spd += self.aspd_steal_bonus - self.aspd_loss
        return spd

    def current_max_target(self) -> int:
        """这一击最多打几个目标。

        两条来源**相加**，缺一不可：

        * `eff.max_target`——开技即生效的**静态**改写（「攻击目标数+3」那一族，
          素心/史尔特尔们走这条）；
        * `eff.target_step` / `target_cap`——**按出手次数递增**的那一族
          （可露希尔技3「每攻击 9 次后攻击目标数+1，最多触发 6 次」）。
          计数器 `trigger_hits` 在技能开启动时清零（`sim._activate`），
          每出手一次 +1（`sim` 的攻击循环里，与 `hits` 同一处）。

        技能没开就退回 1（`effects` 为 None），普攻永远只打一个——这是既定口径，
        递增的那一段只在技能期内兑现。
        """
        e = self.effects
        # 〈替身〉形态的目标数是**快照**下来的（技能在同一帧就结束了，`effects`
        # 已经是空的）：技2 塔纳托斯与技3 塔纳托斯·改都是 `attack@max_target 4`。
        if self.stand_timer > 0.0 and self.stand_max_target > 1:
            return self.stand_max_target
        if e is None:
            return 1
        base = e.max_target
        if e.target_step <= 0:
            return base
        # 「最多触发 M 次」是**格数**上限，不是次数上限：0 或负数表示没写上限。
        earned = self.trigger_hits // e.target_step
        if e.target_cap > 0:
            earned = min(earned, e.target_cap)
        return base + earned

    def active_attack_type(self) -> str:
        """当前伤害类型——技能期间可能被强制改写，〈替身〉形态另有口径。"""
        if self.stand_timer > 0.0:
            # 〈替身〉形态的普通攻击**都是法术**：俄耳甫斯/塔纳托斯/塔纳托斯·改
            # 三个形态的 prts 备注逐条写明"普通攻击造成法术普通伤害"，技3 的
            # 弱点伤害也是"默认伤害类型为法术伤害"。
            return "MAGIC"
        if self.skill_active and self.skill_attack_type:
            return self.skill_attack_type
        return self.attack_type


    def current_range_id(self):
        """开技能期间被改写的攻击范围代号，没有就是 None。

        ⚠ 转调 `frontend/geometry.py`——与 `battle/unit.py` 现在的写法一致，
        实现只有那一份。
        """
        return _current_range_id(self.skill, self.skill_active)


def operator_view(kw: dict[str, Any], **overrides: Any) -> OperatorView:
    """`verify.py::unit` 那个 `kw` → 规格视图。"""
    return OperatorView(kw, **overrides)
