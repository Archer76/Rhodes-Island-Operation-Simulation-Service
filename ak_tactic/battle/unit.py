"""战斗单位：我方干员与敌人在战场上的实例。

两边的共同点是「有属性、有血量、按攻击间隔出手」，差别在于敌人**会走路**。
所以敌人多两样东西：一条折线路径，和一个已走距离 `progress`。

坐标系沿用全局约定（**MAA 标准**）：``(x, y)``，x 向右、y **向下**，``y=0`` 在最上面一行。
朝向取 MAA 的写法（Right / Left / Up / Down），转成单位向量使用。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "DIRECTIONS", "Combatant", "OperatorUnit", "EnemyUnit",
    "path_length", "point_at",
]

#: 朝向 → 单位向量。y 向下为正，所以「上」是 (0, -1)。
DIRECTIONS: dict[str, tuple[int, int]] = {
    "Right": (1, 0), "Left": (-1, 0), "Up": (0, -1), "Down": (0, 1),
}

#: 攻速下限（2026-09-16 博士裁定：wiki 写 20、xulai1001/akdata 写 10，取 20）。
#: 与 `ak_tactic.operator.skill.ASPD_MIN` 是同一个口径——这里再写一遍只是为了
#: 不让 `battle` 反向 import `operator`，改一处必须同时改另一处。
ASPD_MIN = 20.0

#: 攻击间隔下限，与 `SkillEffects.attack_interval` 的 `max(0.05, …)` 同源。
MIN_INTERVAL = 0.05

#: 「已经走进某格中心附近」的距离容差（格），`EnemyUnit.is_at` 用。
#:
#: 单独提出来是为了让**热路径上的就地展开**能和它共用同一个数：模拟器
#: `_update_blocking` 每帧要判 41 次进入，改成平方比较（省掉 `math.dist`
#: 的开方）后必须与这里保持一致，否则两处判定会各说各话。
#: 平方形式见 `sim.POSITION_TOL2`。
POSITION_TOL = 0.35


def path_length(points: list[tuple[float, float]]) -> float:
    """折线总长（格）。"""
    return sum(math.dist(a, b) for a, b in zip(points, points[1:]))


def point_at(points: list[tuple[float, float]], travelled: float) -> tuple[float, float]:
    """沿折线走 `travelled` 格之后的位置。

    超出末端则停在末端（调用方应在此之前判定漏怪）。

    ⚠️ 这里**保留** `zip(points, points[1:])` 与 `math.dist`，别"顺手优化"成
    下标循环 + `sqrt(dx*dx+dy*dy)`：本函数一场 1-7 要跑约 1.8 万次，看着
    像是该省掉那次切片复制，实测却**慢了 3.6%**（1-7 端到端 219.9 → 227.9 ms）。
    `math.dist` 是一次 C 调用，而手写平方和要跑六条字节码，两点的切片复制
    远比它便宜。剖面读数看着这里占 0.038s，但"占得多"不等于"有便宜的改法"。
    """
    if not points:
        return (0.0, 0.0)
    if travelled <= 0:
        return points[0]
    acc = 0.0
    for a, b in zip(points, points[1:]):
        seg = math.dist(a, b)
        if seg <= 0:
            continue
        if acc + seg >= travelled:
            t = (travelled - acc) / seg
            return (a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
        acc += seg
    return points[-1]


@dataclass
class Combatant:
    """能挨打、能出手的东西。"""

    name: str
    max_hp: float
    atk: float
    defense: float
    res: float
    attack_interval: float = 1.0
    attack_type: str = "PHYSICAL"
    hp: float = -1.0
    #: 累计承受的伤害（只算真实扣掉的血量，过量伤害不计）
    damage_taken: float = 0.0
    #: 阵亡时刻，由模拟器填写；-1 表示还活着
    death_time: float = -1.0

    def __post_init__(self) -> None:
        if self.hp < 0:
            self.hp = self.max_hp

    @property
    def alive(self) -> bool:
        return self.hp > 0

    @property
    def hp_ratio(self) -> float:
        return 0.0 if self.max_hp <= 0 else max(0.0, self.hp / self.max_hp)

    def take(self, amount: float) -> float:
        """扣血，返回真实扣掉的量。"""
        dealt = min(self.hp, max(0.0, amount))
        self.hp -= dealt
        self.damage_taken += dealt
        return dealt

    def heal(self, amount: float) -> float:
        before = self.hp
        self.hp = min(self.max_hp, self.hp + max(0.0, amount))
        return self.hp - before


@dataclass
class OperatorUnit(Combatant):
    """部署在场上的我方干员。

    ## 技能怎么挂上来

    `skill` 放一个 `ak_tactic.operator.SkillLevel`。这里用 `object` 而不是写死
    类型，是为了让 `battle` 不反向依赖 `operator`——模拟器只要求这个东西有
    `.effects` / `.is_passive` / `.sp_cost` 等属性，是谁提供的无所谓。

    技能的加成**不写进面板**，而是由 `current_atk()` / `current_interval()`
    这类方法在开技能期间现算。理由是同一个 `OperatorUnit` 在技能开关的前后
    是同一个对象，把 `atk` 原地改掉，关技能时就还不回去了。
    """

    char_id: str = ""
    position: tuple[int, int] = (0, 0)
    direction: str = "Right"
    block_cnt: int = 0
    deploy_cost: int = 0
    #: 已判定生效的天赋（`ak_tactic.operator.talent.Talent`）。
    #: 与 `skill` 同理用 `object`，免得 battle 反向依赖 operator。
    talents: list = field(default_factory=list)
    redeploy_time: float = 70.0
    #: 精英阶段——取攻击范围、判技能解锁都要它
    elite: int = 2
    #: 攻速属性，游戏的基准值是 100。**含天赋与模组的常驻加成**，
    #: 由 `operator/attack_speed.py` 取数——不再停在默认值上。
    attack_speed: float = 100.0
    #: **未阻挡敌人时**额外获得的攻速（模组特性改写，如赤刃明霄陈的 +8）。
    #: 不能并进 `attack_speed`：它是条件加成，一挡住人就没了。
    aspd_when_free: float = 0.0

    #: 这个干员的**普通攻击是治疗**而不是伤害——医疗系特性的
    #: 「恢复友方单位生命」。判据取 `character_table` 的特性文本，
    #: 不按职业名推（守望者也是医疗，但它同时会起飞）。
    heals: bool = False
    #: 「弱点伤害」（赤刃明霄陈天赋「形意洞照」）：出手时两系都算、取伤害更高的一系。
    #: 相性免疫的那一侧会被压成 0，所以它天然躲开被免疫的类型 —— 对「每倒地一次
    #: 就换一次免疫类型」的 BOSS 是直接对症的。
    weakness_damage: bool = False
    #: 模拟器按 `effect_source` 解析出来的效果（描述驱动的那一层）；
    #: None = 回落到技能自己的黑板效果（见 `effects` 属性）
    effects_override: Any = None
    #: 累计治疗量，便于对账
    healing_done: float = 0.0
    #: 增益治疗的剩余秒数与每秒回复量（天赋「入场增益治疗」给的）
    regen_left: float = 0.0
    regen_per_sec: float = 0.0
    #: 天赋「情绪吸收」给的额外技力：每次**出手**回 `sp_per_attack_talent`，
    #: 每次**击杀**回 `sp_per_kill_talent`。二者与技能自己的 `sp_type`
    #: **叠加**而不是二选一——技能是自动回复型时这条照样生效。
    sp_per_attack_talent: float = 0.0
    sp_per_kill_talent: float = 0.0

    # ------------------------------------------------------------ 技能状态

    #: `SkillLevel`，None 表示不带技能
    skill: object | None = None
    #: 带的是手动技能时，技力满了要不要自动开
    auto_skill: bool = True
    #: 技能是否正在生效
    skill_active: bool = False
    #: 当前技力
    sp: float = 0.0
    #: 这个技能已经开过几次，便于对账
    sp_charges: int = 0
    #: 本帧收到的手动开启请求
    skill_request: bool = False
    #: 剩余持续时间（秒），无限持续为 inf
    skill_timer: float = 0.0
    #: 弹药类技能剩余发数
    ammo_left: int = 0
    #: 开技能期间强制改变的伤害类型（机械师这类"攻击变法术"的技能）
    skill_attack_type: str | None = None
    #: 技能结束后**自身**晕眩的剩余秒数（阿米娅技2 精神爆发那类）。
    #: 晕眩期间不能出手，但仍在场上、仍会阻挡、仍会挨打。
    stun_timer: float = 0.0
    #: 是不是**技能强制退场**走的（阿米娅技3 奇美拉），而不是被打死。
    #: 结算时必须与阵亡分开——`operator_deaths` 只数被打死的那些。
    retreated: bool = False
    #: 「末击起为真实」类技能（阿米娅技2 影霄·绝影）的**斩击阶段还没打完**。
    #: 为 True 时这一次出手的前 N-1 击仍用干员本来的伤害类型，只有末击转真实；
    #: 打完置 False，此后技能期内的普攻才整体走 `skill_attack_type`。
    slash_pending: bool = False
    #: 击杀叠层的当前层数（阿米娅技2 影霄·绝影）。技能期间每击杀一个 +1，
    #: 上限取 `SkillEffects.kill_max_stack`；**技能结束时清零**。
    kill_stacks: int = 0
    #: 全场光环（「青色怒火」）给的攻击力/防御力比例加成。由模拟器每帧刷新——
    #: **不能在建单位时定死**，因为「光环主人开技能期间效果加倍」会随时间变。
    aura_atk_pct: float = 0.0
    aura_def_pct: float = 0.0
    #: 技能期间获得的闪避（比例，0.6 = 60%），由模拟器在开技能时置上、
    #: 关技能时清零。物理与法术**分开存**，因为游戏里是两条独立词条
    #: （「物理闪避」/「法术闪避」/「物理和法术闪避」），合成一个数会在
    #: 只给单边的时候静默搞错。
    #:
    #: 结算走**期望值法**（`damage.resolve_damage` 的 `dodge_*` 参数相乘），
    #: 不掷骰——理由与判据见那里的 docstring。
    #: 标本：赤刃明霄陈技2「赤霄·绝影-驰」，描述「获得 60% 物理和法术闪避」，
    #: 黑板键是 `chen3_s2[respawn_buff].prob = 0.6`——**键名是 `prob`，
    #: 与提丰技2 的 `attack@prob`（40% 概率晕眩）同名反义**，所以这个数
    #: 只能由描述驱动（`skill._wants_dodge`），不能按键名认。
    dodge_phys: float = 0.0
    dodge_arts: float = 0.0
    #: 是不是**撤离/退场**离场的。`Combatant.alive` 只看血量，而强制退场
    #: 时干员是满血的，所以必须覆写：让 `alive` 一次覆盖「被打死」与
    #: 「自己下场」两种不在场，其它所有 `if op.alive` 的地方自动跟着对。
    @property
    def alive(self) -> bool:
        return self.hp > 0 and not self.retreated
    #: 技能加生命上限之前的基准值，用于关技能时还原
    _base_max_hp: float = field(default=0.0, repr=False)

    #: 当前挡住的敌人（最多 block_cnt 个）
    blocking: list["EnemyUnit"] = field(default_factory=list)

    #: 攻击计时器，累加到 attack_interval 就出手
    attack_timer: float = 0.0
    #: 已出手次数，便于对账
    hits: int = 0

    @property
    def facing(self) -> tuple[int, int]:
        return DIRECTIONS.get(self.direction, (1, 0))

    @property
    def free_block_slots(self) -> int:
        return max(0, self.block_cnt - len(self.blocking))

    def can_block(self, enemy: "EnemyUnit") -> bool:
        # 飞行单位（`motion == "FLY"`）**不可被地面干员阻挡**。
        # SR-EX-8 的挥铳圣像就是 FLY，而它同时无弱点、永不倒地——
        # 不挡这一条，它会被 (6,1) 的阻挡位白白拦下，模拟比实机好看。
        if enemy.is_flying:
            return False
        return self.block_cnt > 0 and self.free_block_slots > 0

    # ------------------------------------------------------------ 技能读数

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

    @property
    def is_passive_skill(self) -> bool:
        return bool(self.skill is not None and getattr(self.skill, "is_passive", False))

    def current_atk(self) -> float:
        """当前攻击力——开技能期间含攻击力增益、技能倍率与**击杀叠层**。

        注意 `effects is None`（这一帧没开技能）的分支**也要算全场光环**：
        「青色怒火」是发给所有友方的，不挑对方开不开技能。早期版本在这个分支
        直接 `return self.atk`，症状是光环只对开着技能的人生效、对队友一点用没有。
        """
        e = self.effects
        if e is None:
            return self.atk * (1.0 + self.aura_atk_pct)
        # 击杀叠层的加成与普通攻击力增益**同层相加**（都进 `(1 + 攻击力增益)`
        # 这个括号），不乘在外面——三层的 +40% 是 +120%，不是 1.4³。
        pct = 0.0
        if self.kill_stacks:
            v = e.variants.get("kill") or {}
            pct = float(v.get("atk", 0.0)) * self.kill_stacks
        # 全场光环（青色怒火）同样是**同层相加**的百分比加成。
        if pct or self.aura_atk_pct:
            return (self.atk * (1.0 + e.atk_pct + pct + self.aura_atk_pct)
                    * e.atk_scale)
        return e.attack_power(self.atk)

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

    def current_defense(self) -> float:
        e = self.effects
        if e is None:
            return self.defense * (1.0 + self.aura_def_pct)
        return self.defense * (1.0 + e.buffs.get("def", 0.0) + self.aura_def_pct)

    def current_attack_speed(self) -> float:
        """当前总攻速——含「未阻挡敌人时」的条件加成。

        攻速是**实时**量：模组特性给的那 8 点只在没挡住人时才有，
        所以不能在建单位那一步就并进 `attack_speed`。
        """
        spd = self.attack_speed
        if self.aspd_when_free and not self.blocking:
            spd += self.aspd_when_free
        return spd

    def current_interval(self) -> float:
        """当前攻击间隔——**平A 也按攻速折算**，开技能期间再叠技能修正。

        旧写法在没有技能效果时直接返回 `attack_interval`，等于把攻速整个丢掉：
        天赋与模组的攻速在平A 期间一律不生效，出手频率只剩基础值。攻速正好是
        100 时两种写法等价，所以这个缺口一直没露出来。
        """
        spd = self.current_attack_speed()
        e = self.effects
        if e is None:
            return max(MIN_INTERVAL, self.attack_interval * 100.0 / max(ASPD_MIN, spd))
        return e.attack_interval(self.attack_interval, spd)

    def current_max_target(self) -> int:
        e = self.effects
        return e.max_target if e is not None else 1

    def current_range_id(self) -> str | None:
        """开技能期间被改写的攻击范围代号，没有就是 None。"""
        if self.skill_active and self.skill is not None:
            return getattr(self.skill, "range_id", None)
        return None

    def active_attack_type(self) -> str:
        """当前伤害类型——技能期间可能被强制改写。"""
        if self.skill_active and self.skill_attack_type:
            return self.skill_attack_type
        return self.attack_type

    # ------------------------------------------------------------ 生命上限

    def apply_max_hp_bonus(self, pct: float) -> None:
        """技能给的生命上限增益。上限和当前血量一起涨。"""
        if pct == 0:
            return
        if self._base_max_hp <= 0:
            self._base_max_hp = self.max_hp
        self.max_hp = self._base_max_hp * (1.0 + pct)
        self.hp = min(self.max_hp, self.hp + self._base_max_hp * pct)

    def revert_max_hp_bonus(self) -> None:
        """关技能时还原生命上限，当前血量按新上限夹一次。"""
        if self._base_max_hp > 0:
            self.max_hp = self._base_max_hp
            self.hp = min(self.hp, self.max_hp)
            self._base_max_hp = 0.0


@dataclass
class EnemyUnit(Combatant):
    """场上的敌人——沿折线推进。"""

    enemy_id: str = ""
    level: int = 0
    weight: float = 0.0
    move_speed: float = 1.0
    block_cnt: int = 0          #: 敌人自身的阻挡数（一般 1）
    attack_type: str = "PHYSICAL"
    life_cost: int = 1          #: 漏掉扣几点生命（lifePointReduce）
    #: 漏怪时刻（秒）。-1 表示没漏过。诊断"几点压到防线"要靠它。
    leak_time: float = -1.0

    #: 路径：从出生点到防守点的格心坐标序列
    route: list[tuple[float, float]] = field(default_factory=list)
    #: 已走距离（格）
    progress: float = 0.0
    #: 出现时刻（秒）
    spawn_time: float = 0.0
    #: 当前坐标
    position: tuple[float, float] = (0.0, 0.0)

    #: 分段行进计划（`ak_tactic.gamedata.stage.RouteLeg` 列表）。
    #: 非空时**取代** `route` 的整条折线推进——因为路线里可能有离场传送，
    #: 连成一条折线会让敌人"横穿半张地图"而不是瞬移。
    legs: list = field(default_factory=list)
    #: 当前在第几段
    leg_index: int = 0
    #: 段内进度：walk 段是已走格数，wait/vanish 段是已过秒数
    leg_u: float = 0.0
    #: 是否处于离场传送状态（不在地图上：不能被打、不阻挡、不算漏怪）
    off_map: bool = False

    #: 挡住它的干员
    blocked_by: "OperatorUnit | None" = None

    #: 入场后**原地待命**的剩余秒数（路线的 WAIT_FOR_SECONDS）。
    #: 待命期间不动，也不该被当成"已经推进到位"。
    wait_remaining: float = 0.0

    #: 移速乘数，由场上的减速效果（如积雪）逐帧写入。1.0 = 不减速。
    speed_multiplier: float = 1.0

    #: 本帧是否处于冻结（积雪满层的地块）。冻结期间**不能移动、不能攻击**。
    #: 每帧由积雪重算，不是持续状态。
    frozen: bool = False

    #: 剩余【停顿】秒数（技能黑板里的 `sluggish`）。停顿 = **不能移动**，
    #: 但仍然可以攻击——这与眩晕/冻结不同，别混。
    #: 标本：凯尔希·思衡托「保护性拒止」`sluggish 5.0`。
    sluggish_timer: float = 0.0

    #: 剩余【待机】秒数。待机 = **不能移动也不能攻击**。
    #: 标本：BOSS `Skill_Revelation` 的 `idle_duration 5`。
    idle_timer: float = 0.0
    #: 剩余【缴械】秒数。缴械 = **不能攻击但能移动**。
    #: 标本：`disarmed_duration 7`。
    disarm_timer: float = 0.0

    # ---------------------------------------------------------- 伤害相性 P3R
    #: 伤害相性：`{"physical": 0, "magical": 1, "element": 2}`。
    #: 0 弱点 / 1 正常 / 2 免疫 / 3 反射。空 = 这个敌人不吃相性规则。
    affinity: dict = field(default_factory=dict)
    #: 这个敌人的**形态档**（BOSS 的真档位）：`{"Mode_A": {...}, "Mode_B": {...}}`。
    #: 空 = 没有形态，相性固定不变。有它才谈得上「弱点在物理和法术间切换」。
    modes: dict = field(default_factory=dict)
    #: 击破值计量（`ak_tactic.battle.p3r.BreakState`），None = 没有计量
    break_state: object | None = None
    #: 本帧是否处于【倒地】。倒地 = 眩晕（不能动、不能攻击）+ **不可阻挡**。
    #: 每帧由 P3R 层重算，不是持续状态。
    down: bool = False

    attack_timer: float = 0.0
    hits: int = 0
    #: 是否已经走到终点（漏怪）
    leaked: bool = False

    # ------------------------------------------------------- 关卡机制（敌人侧）
    #: 屏障。数据里的 `Shield.shield_hp_ratio`（如吓人路灯 0.25），按最大生命
    #: 折算成一层额外血条，**在生命值之前被消耗**——它不是减伤，是加血。
    shield: float = 0.0
    #: 屏障上限，用于展示
    shield_max: float = 0.0
    #: 是否飞行。`motion == "FLY"` 的敌人**不可被地面干员阻挡**。
    is_flying: bool = False
    #: 出手方式（`applyWay`）与射程（`rangeRadius`，格）。
    #: `RANGED` 的敌人**在射程内开火，但不会因此停下不走**——它只是
    #: 在攻击动作期间停一下（见 `attack_pause`），动作一结束就继续推进。
    #: 这条是 2026-09-15 与实机对照后定下的：若读成「锁到目标就中止推进」，
    #: 1-7 的鸡尾酒投掷者（RANGED / 射程 1.75）会永久停在怒潮凛冬
    #: 1-1 范围之外，必然漏 4 只——而实机录像（单干员）是 41 杀 0 漏。
    apply_way: str = "MELEE"
    attack_range: float = 0.0
    #: 剩余的攻击动作时间（秒）。出手后置为 `enemy_windup`，期间不能移动。
    #: 敌人动画长度不在 gamedata 里，故长度由模拟器给定：
    #: 见 `BattleSimulator.enemy_windup`，可用它做敏感性扫描。
    attack_pause: float = 0.0
    #: 当前锁定的干员（被阻挡时就是阻挡者；远程则是射程内最近的）
    engaged: "OperatorUnit | None" = None
    #: 击杀奖励费用（`Talent1.cost`，「没办法车」是 50）
    kill_cost: int = 0
    #: 击杀奖励是否已发放，防止重复结算
    cost_awarded: bool = False
    #: 还能重生几次。BOSS「死志的凝结」有 `Reborn.*`：死后以
    #: `reborn_hp_ratio` 的血量归来，**等于多一条命**。
    reborn_left: int = 0
    #: 两次重生之间的间隔秒数（`Reborn.reborn_duration` = 10）
    reborn_delay: float = 0.0
    #: 重生时的血量比例（`Reborn.max_hp_ratio` = 1，即满血归来）
    reborn_hp_ratio: float = 1.0
    #: 重生倒计时的结束时刻；>= 0 表示「已倒下、正在等重生」。
    #: 这个窗口里它不算活人（不能被选中、不能阻挡、不推路），
    #: 但**也不能算击杀**，否则击杀数会虚高、战斗会提前判胜。
    reborn_at: float = -1.0
    # ---- 【怀黍离】重生期充能（瘴 / 鄙瘴；「祟」同前缀但没有那两项）----
    #: 重生期间每隔几秒结算一次（`Reborning.interval` = 0.5）。0 = 无此机制。
    reborn_interval: float = 0.0
    #: 每次充能扣掉所在地块多少点病害值（`Reborning.value` = 10，已取正）
    reborn_pollut: float = 0.0
    #: 每层充能的防御力比例（`Reborning.def_add` = 0.3 → 每层 +30%）
    reborn_def_add: float = 0.0
    #: 每层充能的附加法术伤害比例（`Reborning.damage_magic` = 0.1）
    reborn_damage_magic: float = 0.0
    #: 已积累的充能层数。**只在重生窗口里增长**，重生后定住——
    #: 原文是「重生期间每 0.5s…获得1层充能」「重生后，自身防御力+(30×层数)%」。
    reborn_charge: int = 0
    #: 下一次充能结算的时刻（绝对时间；< 0 表示不在充能窗口里）
    reborn_charge_at: float = -1.0
    #: 本次重生开始时的防御力。充能加成按「基础值 × (1 + 比例×层数)」算，
    #: 每次都从这个基准重算，避免二次重生时把上一次的加成再乘一遍。
    reborn_def_base: float = 0.0
    #: 重生期间按间隔召唤：`((间隔秒, 个数, 敌人 id), …)`（怀黍离「祟」）。
    #: 与充能是两条互不相干的分支——「祟」有 interval 但没有 value，
    #: 按"有 interval 就是充能"去读会把它算成「每次扣 0 点」的充能怪。
    reborn_summons: tuple = ()
    #: 运行时：每一路召唤的下一次到期时刻（与 `reborn_summons` 一一对应）
    reborn_summon_at: list = field(default_factory=list)

    # ---- 六个机制前缀（怀黍离实测；字段来历见 gamedata/enemy.py::mech_fields）----
    #: 「Passive.」被击倒时把半径 `passive_radius` 内的田地各抬高这么多病害值
    passive_pollut: float = 0.0
    passive_radius: float = 0.0
    #: 「DeathPassive.」被击倒时给予**我方**可部署装置（key 与个数）。
    #: ⚠ 模拟器目前没有"部署装置"这一层（部署计划只收干员），故这两项
    #: 只被记账、不影响结算——见 activity.py 里该前缀的状态说明。
    death_token: str = ""
    death_cnt: int = 0
    #: 「AuraHit.」进入阻流阀 `aura_hit_radius` 格内时对其造成**阻流阀最大生命**
    #: 的 `aura_hit_ratio` 倍真实伤害（目标血量比例，不是自己的）
    aura_hit_ratio: float = 0.0
    aura_hit_radius: float = 0.5
    #: 「SpeedUp.」受击且未被阻挡 → 移速 +`speedup_move`×100%，持续
    #: `speedup_duration` 秒、冷却 `speedup_cooldown` 秒（被阻挡立刻解除）
    speedup_move: float = 0.0
    speedup_duration: float = 0.0
    speedup_cooldown: float = 0.0
    #: 运行时：增益剩余秒数 / 冷却到期的绝对时刻
    speedup_timer: float = 0.0
    speedup_ready_at: float = 0.0
    #: 运行时：当前的**加速倍率**（1.0 = 无增益）。
    #: ⚠ 不并进 `speed_multiplier`：那一个由积雪天赋**每帧重写**
    #: （`_snow_tick` 里先置 1.0 再乘减速），并进去会被当场抹掉，
    #: 而且是静默的——增益看着挂上了，敌人该多快还是多快。
    haste_multiplier: float = 1.0
    #: 「Passive_Hit.」每受 `phit_cnt` 次伤害蜕皮一层，上限 `phit_max_stack`；
    #: 每层改属性（负数是减）并污染半径 1.0 内的田地；每 `phit_weight_cnt` 层
    #: 重量 −1
    phit_cnt: int = 0
    phit_atk: float = 0.0
    phit_def: float = 0.0
    phit_res: float = 0.0
    phit_move: float = 0.0
    phit_pollut: float = 0.0
    phit_block_pollut: float = 0.0
    phit_extra: float = 0.0
    phit_max_stack: int = 0
    phit_weight_cnt: int = 0
    #: 运行时：累计受击次数 / 已蜕皮层数。
    #: ⚠ 计的是**次数**而不是伤害量（原文「每受到 N 次伤害」），所以一次
    #: 多段攻击要按段数计——它由 `_damage_enemy` 的调用次数决定。
    phit_hits: int = 0
    phit_stacks: int = 0
    #: 「PassiveM2.」明识形态的属性改写与清水减益（`clean_*` 三项只有在
    #: 「水田中且本格病害值=0」或「清澈泵站生效范围内」时才生效）
    pm2_atk: float = 0.0
    pm2_def: float = 0.0
    pm2_res: float = 0.0
    pm2_move: float = 0.0
    pm2_clean_def: float = 0.0
    pm2_clean_res: float = 0.0
    pm2_clean_move: float = 0.0
    pm2_mark_pollut: float = 0.0
    pm2_invincible: float = 0.0
    pm2_pollut_threshold: float = 0.0
    #: 运行时：是否已进入明识形态
    pm2_active: bool = False
    #: 运行时：属性改写是否**已经算过一次**（属性只改一次，不能逐帧反复乘）
    pm2_applied: bool = False
    #: 运行时：当前清水减益是否生效（用于把移速加成收回去）
    pm2_clean: bool = False
    #: 运行时：无敌到期的绝对时刻（<0 表示不无敌）。
    #: 混沌形态下天桩-甲是**常驻**无敌，那种走 `always_invincible`。
    invincible_until: float = -1.0
    #: 运行时：常驻无敌（`CheckAwake` 监测状态的天桩-甲、以及「不死」）。
    #: 它挡伤害但**不挡**「重设生命」这类直接写血的行为。
    always_invincible: bool = False
    #: 每一次攻击动作打几段。【怀黍离】「祟」明识形态的普攻是 2 连击。
    #: ⚠ 逐段结算，不是把攻击力乘 2——两段的防御/法抗各减一次，
    #: 合并成一次会少减一次，对高防目标差得很远。
    attack_times: int = 1
    #: 运行时：明识形态「受到伤害时标记伤害来源」，存 `id(干员)`。
    #: 用 id 而不是对象本身：`OperatorUnit` 是普通 dataclass、不可哈希。
    marked_ops: set = field(default_factory=set)
    #: 运行时：被击倒后的那批一次性效果（死亡污染 / 给装置）是否已结算
    death_done: bool = False

    def __post_init__(self) -> None:
        super().__post_init__()
        if self.route:
            self.position = self.route[0]

    @property
    def pending_reborn(self) -> bool:
        """已倒下、正在等重生。既不算活着，也不算死了。"""
        return self.reborn_at >= 0.0

    def take(self, amount: float) -> float:
        """扣血。屏障先扛，扛不住的才进生命值。

        返回**实际扣掉的生命值**（不含被屏障吃掉的），因为上层用它累积
        P3R 的击破值——屏障吃掉的伤害不该算进击破。
        """
        amount = max(0.0, amount)
        if self.shield > 0.0:
            absorbed = min(self.shield, amount)
            self.shield -= absorbed
            amount -= absorbed
        return super().take(amount)

    @property
    def route_length(self) -> float:
        if self.legs:
            return sum(leg.length for leg in self.legs)
        return path_length(self.route)

    def advance(self, dt: float, speed_scale: float = 1.0) -> None:
        """向前推进 dt 秒。待命、被阻挡、或被减速效果放慢时按规则处理。"""
        if not self.alive:
            return
        if self.frozen:
            return
        if self.down:
            # 【倒地】= 眩晕，不能移动
            return
        if self.attack_pause > 0:
            # 攻击动作期间原地出手。**动作结束就继续走**，不是永久停下——
            # 这一点是这套模型与"停在射程外不走"读法的唯一差别，也是
            # 1-7 能不能复现实机录像（41 杀 0 漏）的分水岭。
            return
        if self.wait_remaining > 0:
            self.wait_remaining = max(0.0, self.wait_remaining - dt)
            return
        if self.sluggish_timer > 0 or self.idle_timer > 0:
            # 【停顿】/【待机】不能移动。停顿还能开火，待机连开火也不行
            # （开火那一侧由模拟器的出手环节拦）。计时器由模拟器每帧统一递减
            # ——这里只拦移动，免得"锁到目标的敌人不走 advance"那条路上漏减。
            return
        if self.blocked_by is not None:
            return
        speed = (self.move_speed * speed_scale * self.speed_multiplier
                 * self.haste_multiplier)
        if speed <= 0:
            return
        if not self.legs:
            self.progress += speed * dt
            self.position = point_at(self.route, self.progress)
            return
        self._advance_legs(dt, speed)

    def _advance_legs(self, dt: float, speed: float) -> None:
        """按分段计划推进。

        三种段落共用 `leg_u`：走段里它是已走格数，等待/离场段里是已过秒数。
        段落之间会重置，所以不必分成两个字段。

        整个循环**以时间为预算**（不是以格数）：走段消耗 `距离 / 速度` 秒，
        等待与离场段消耗真实秒数。若按格数当预算，等待段会被移速缩放——
        3 秒的待命会被拉长成好几分钟，而且移速为 0 的敌人会永远卡在等待里。
        """
        left = dt
        guard = 0
        while left > 1e-12 and self.leg_index < len(self.legs):
            guard += 1
            if guard > 4096:                    # 防段落本身异常导致死循环
                break
            leg = self.legs[self.leg_index]
            self.off_map = (leg.kind == "vanish")
            if leg.kind == "walk":
                room = leg.length - self.leg_u          # 剩余格数
                if room <= 0:
                    self._next_leg()
                    continue
                can = speed * left                      # 剩余时间最多能走多少格
                step = can if can < room else room
                self.leg_u += step
                self.progress += step
                # 直接传 `leg.points`：`point_at` 只读不写，原先的 `list(...)`
                # 是每次调用白抄一份（本行每帧跑一次、一场上万次）。
                self.position = point_at(leg.points, self.leg_u)
                left -= step / speed
                # 判据是"这一步有没有把剩余量走完"，**不能**写成 leg_u >= room
                # ——room 是剩余量、leg_u 是已走量，那样会让段落在走到一半时
                # 就判定完成（u >= L-u ⟺ u >= L/2）。
                if step >= room - 1e-9:
                    self._next_leg()
                else:
                    break
            else:
                room = leg.seconds - self.leg_u         # 剩余秒数
                if room <= 0:
                    self._next_leg()
                    continue
                step = left if left < room else room
                self.leg_u += step
                left -= step
                if step >= room - 1e-9:
                    self._next_leg()
                else:
                    break
        if self.leg_index >= len(self.legs):
            self.off_map = False

    def _next_leg(self) -> None:
        self.leg_index += 1
        self.leg_u = 0.0

    @property
    def reached_end(self) -> bool:
        if self.legs:
            return self.leg_index >= len(self.legs)
        return self.progress >= self.route_length > 0

    def cell(self) -> tuple[int, int]:
        """所在格（四舍五入到整数格）。"""
        return (int(round(self.position[0])), int(round(self.position[1])))

    def is_at(self, cell: tuple[int, int], tol: float = POSITION_TOL) -> bool:
        """是否已经进入某一格的中心附近——用于判定被阻挡。

        热路径（模拟器 `_update_blocking`）已就地展开成平方比较，不走这里；
        本方法留给外部调用与自检，两者共用 `POSITION_TOL`。
        """
        return (math.dist(self.position, (float(cell[0]), float(cell[1]))) <= tol)
