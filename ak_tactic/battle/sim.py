"""模拟器：把「阵容 + 操作序列」推成结果。

按帧推进（一秒 30 帧），每帧的顺序固定为：

1. 执行本帧排定的操作（部署 / 开技能 / 撤退）
2. 让到点的敌人入场
3. 敌人沿路线推进——**被挡住的不动**
4. 重算阻挡关系
5. 技能结算：回技力、够不够开、持续到点了没有
6. 我方出手
7. 敌方出手
8. 结算死亡、漏怪、费用回复

顺序不能乱：先推进再判阻挡，否则敌人会「穿过」干员那一格跑到下一格才被拦下；
技能结算要排在我方出手之前，否则「刚攒满技力」的那一帧会白打一次平A。

## 技能是怎么算的

技能本身的数据在 `ak_tactic.operator.skill`，这里只负责**何时开、开多久、
开了之后怎么打**：

* **技力回复**：自动回复按秒涨，攻击回复在出手时涨，受击回复在挨打时涨。
  一个技能只属于其中一种。
* **被动技能**（`spType == 8`）：部署即生效，不耗技力，永不关闭。
* **持续时间**：`duration` 为负表示无限（会自动回复的技能触发后就一直开着）；
  弹药类技能没有时间上限，打够 `effects.ammo` 发就结束。
* **多充能**（`maxChargeTime > 1`）：只有这种技能在开启期间还继续攒技力。

## 已知不做的

**技能不改伤害类型**——黑板里没有可靠的字段说明"这一击变成法术伤害"，
机械师「工程学十字星」的转化只写在描述文本里。需要时由调用方显式指定
`OperatorUnit.skill_attack_type`，而不是让模拟器去猜。

## 移速换算

`格/秒 = moveSpeed × move_multiplier × speed_scale`，其中 `move_multiplier`
取自关卡。这条已用 1-7 的实机录像校准过（模拟 142.0s vs 实机 140s，误差 1.4%）。

**攻击范围**：由 `range_provider` 提供，取不到时退化为「自身格 + 前方三格」。
真实的 `rangeId` 在 `character_table.phases[].rangeId` 里，技能期间会换成
`SkillLevel.range_id`。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable, Iterable

from ..eta import leading_wait, route_plans
from .damage import DamageType, resolve_damage
from .talents import (RegenAura, SnowField, TeamAura, find_regen, find_snow,
                      find_sp_on_action, find_team_aura, squad_cost_bonus)
from .p3r import BreakState, TotalAttackDevice, affinity_multiplier, damage_slot
from .unit import POSITION_TOL, EnemyUnit, OperatorUnit, point_at

__all__ = ["BattleSimulator", "BattleResult", "Deployment", "SkillUse"]

FPS = 30

#: 无限持续的技能用这个值当倒计时，省得每次都判 None
_INFINITE = float("inf")

#: 「全场总攻击」装置的 characterKey。关卡 `predefines.tokenInsts` 里出现它就启用。
TOTAL_ATTACK_KEY = "trap_335_totalattack"

#: `POSITION_TOL` 的平方，供热路径用平方比较代替 `math.dist` 的开方。
#: 两处必须同源，改 `unit.POSITION_TOL` 即自动生效。
POSITION_TOL2 = POSITION_TOL * POSITION_TOL


def make_total_attack(stage) -> TotalAttackDevice | None:
    """关卡里有没有「全场总攻击」装置。有就返回一个（参数用已验证的黑板默认值）。

    黑板出自 `character_table.json` 的 `trap_335_totalattack` 天赋
    `TalentTotalAttack`：`base_atk 15000` / `trigger_cd 8.0` / `atk_scale 1.0`。
    """
    pre = (getattr(stage, "raw", None) or {}).get("predefines") or {}
    for inst in pre.get("tokenInsts") or []:
        if (inst.get("inst") or {}).get("characterKey") == TOTAL_ATTACK_KEY:
            return TotalAttackDevice()
    return None


def _leading_wait(route) -> float:
    """兼容旧名。实现已移到 `ak_tactic.eta.leading_wait`（与 ETA 共用）。"""
    return leading_wait(route)


# ---------------------------------------------------------------- 计划动作

@dataclass
class Deployment:
    """一次部署。

    :param skill: 用第几个技能。可以是槽位号 1/2/3（0 = 不带技能，需要
        `BattleSimulator(skill_book=...)` 才能解析），也可以直接给一个
        `SkillLevel` 对象。
    :param skill_level: 技能的普通等级 1–7
    :param skill_mastery: 专精等级 0–3
    :param auto_skill: 手动技能在技力满了之后要不要自动开
    """

    time: float
    operator: OperatorUnit
    position: tuple[int, int]
    direction: str = "Right"
    skill: object = 0
    skill_level: int = 7
    skill_mastery: int = 0
    auto_skill: bool = True
    #: 已判定生效的天赋（`ak_tactic.operator.talent.Talent` 列表）。
    #: 模拟器只对**显式建模过**的天赋做事，见 `ak_tactic.battle.talents`。
    talents: list = field(default_factory=list)


@dataclass
class SkillUse:
    """一次手动开技能。"""

    time: float
    position: tuple[int, int]


@dataclass
class BattleResult:
    won: bool = False
    life: int = 0
    kills: int = 0
    leaks: int = 0
    elapsed: float = 0.0
    deployed: int = 0
    damage_dealt: float = 0.0
    operator_deaths: int = 0
    skill_activations: int = 0
    log: list[str] = field(default_factory=list)
    #: 漏怪明细 `(时刻, 敌人名, 扣几点生命)`。**与 verbose 无关**，永远记账——
    #: 验证器的失败诊断要从这里读出"几点漏了什么"。
    leak_events: list[tuple[float, str, int]] = field(default_factory=list)
    #: 每个干员这次用的是哪条效果来源（`effect_source != "blackboard"` 时才有）
    effect_source_used: dict[str, str] = field(default_factory=dict)
    #: 描述与黑板**真分歧**的记录（`agree`/`only_desc` 不记）
    effect_conflicts: list[str] = field(default_factory=list)
    #: `DeathPassive.` 给的可部署装置：`(时刻, 装置 key, 个数)`。
    #: **只记账不生效**——模拟器没有"部署装置"这一层（部署计划只收干员，
    #: 装置全是关卡预先摆好的）。留这份账是为了让这条机制**可被检查**
    #: （打死了几个飞贼、该得几个阻流阀，自检能对得上），而不是装作没接。
    device_tokens: list[tuple[float, str, int]] = field(default_factory=list)

    def summary(self) -> str:
        head = "胜利" if self.won else "失败"
        return (f"{head}：{self.elapsed:.1f}s  剩余生命 {self.life}  "
                f"击杀 {self.kills}  漏怪 {self.leaks}  "
                f"部署 {self.deployed}  干员阵亡 {self.operator_deaths}  "
                f"开技能 {self.skill_activations} 次  "
                f"总伤害 {self.damage_dealt:,.0f}")


# ---------------------------------------------------------------- 模拟器

class BattleSimulator:
    """关卡模拟器。

    :param stage: `ak_tactic.gamedata.Stage`
    :param enemy_at: `(enemy_id, level) -> Combatant 属性`，通常传 EnemyLibrary
    :param range_provider: `(char_id, elite, direction, position) -> set[(x, y)]`
    :param skill_book: `ak_tactic.operator.SkillBook`。只有 `Deployment.skill`
        给的是槽位号（1/2/3）时才需要它来查技能；直接给 `SkillLevel` 则不用。
    :param fps: 每秒帧数，默认 30
    """

    def __init__(
        self,
        stage,
        *,
        enemy_at: Callable[[str, int], object],
        range_provider: Callable[[str, int, str, tuple[int, int]], set] | None = None,
        skill_book=None,
        fps: int = FPS,
        speed_scale: float = 1.0,
        verbose: bool = False,
        snow_freeze: bool = True,
        total_attack: "TotalAttackDevice | None | bool" = None,
        ranged_enemies: bool = True,
        enemy_windup: float = 0.5,
        heal_mode: str = "range",
        boss_mode_switch: str = "none",
        affinity_blocks_damage: bool = True,
        #: 剑气速度（格 / 游戏秒）。原文只写了「向前 / 遇障碍右转 / 技能结束消失」，
        #: 没有数值。2026-09-16 由攻略录像（BV14yY96mEzt，2 倍速 30fps）实测：
        #: 三段互相独立的水平直线飞行给出 56.3 / 57.5 / 54.5 像素/视频秒，
        #: 地图 13 格水平跨度约 303 像素（1 格 ≈ 23.3 像素）⇒ **1.21~1.27 格/秒**，
        #: 取 1.2。旧默认值 4.0 是估的、偏快约 3.3 倍，而且恰好落在「0 漏」那档，
        #: 把实测速度下会漏 1 只的事实整个盖住了。
        sword_qi_speed: float = 1.2,
        effect_source: str = "merge",
        #: 关卡环境机制（怀黍离的田地/病害值）是否结算。
        #:
        #: * `auto`（默认）—— 这一关的 `runes` 里有环境系统就自动开启，
        #:   没有则整条链路不建对象、零开销。绝大多数关卡走这条。
        #: * `off` —— 显式关掉，用于回归对照（与 `effect_source` 同一套路）。
        #:
        #: 为什么默认开着：环境伤害是**关卡机制**，不是可选内容。怀黍离的
        #: 田地每秒能打出 320 点法术伤害，比多数敌人的普攻还高；不结算
        #: 等于把这一关的难度整个抹掉。
        environment: str = "auto",
        #: 环境系统按哪一档难度取参数。同一关的 `NORMAL` 与 `FOUR_STAR`
        #: 数值常不同（`act31side_ex08` 的初始污染点 `1,1:0` vs `4,4:100`），
        #: 且 **`ALL` 也要认**——`act31side_08` 用的就是 `ALL`。
        environment_difficulty: str = "NORMAL",
    ):
        self.stage = stage
        self.enemy_at = enemy_at
        #: 关卡 `runes` 里的**敌人修饰层**（`enemy_attribute_mul` /
        #: `enemy_talent_blackb_mul` / `enemy_skill_blackb_mul`），按难度消歧。
        #: 包在 `enemy_at` 的出口上，所以模拟器里每一处取敌人属性的地方都过它。
        from .stage_mul import (cost_recovery_scale, global_lifepoint,
                                parse_rune_muls, wrap_enemy_at)
        self.rune_muls = parse_rune_muls(
            (getattr(stage, "raw", None) or {}).get("runes"), environment_difficulty)
        if self.rune_muls:
            self.enemy_at = wrap_enemy_at(enemy_at, self.rune_muls)
        self.range_provider = range_provider
        self.skill_book = skill_book
        #: 技能效果的来源策略。三者都建立在**黑板**之上，区别只在描述那一路
        #: 走多远：
        #:
        #: * `blackboard` —— 只用黑板（外加 skill.py 里两条原有的描述钩子：
        #:   真实伤害、`造成 N 次`）；旧行为，用于回归对照。
        #: * `merge`（默认）—— 再用完整的描述公式模型补黑板的**空缺**：
        #:   攻击力倍率、连击数、治疗倍率、元素损伤。黑板有值时一律以黑板为准。
        #: * `desc` —— 结算只信描述（黑板仅作兜底），用于敏感性分析。
        #:
        #: 为什么默认不是 `desc`：黑板是引擎真值，描述是给人读的。全库 911 条
        #: 技能行里两者在 `atk_scale` 上一致 257 条、分歧 6 条、描述独有 42 条
        #: ——分歧那 6 条必须逐个人看，不能拿默认值去赌。
        self.effect_source = effect_source
        self.fps = fps
        self.speed_scale = speed_scale * float(getattr(stage.options, "move_multiplier", 1.0) or 1.0)
        self.verbose = verbose
        #: 积雪满层的地块是否「变为冻结状态」。这是从技能描述推出来的，
        #: 不是数据里写死的字段，所以留成开关，便于对照两种读法。
        self.snow_freeze = snow_freeze
        #: `applyWay == "RANGED"` 的敌人是否**在射程内开火**。
        #: 先前只让"被阻挡"的敌人出手，于是挥铳圣像（FLY、不可阻挡、
        #: 攻 1500）会大摇大摆从干员身边走过去一下不打——而实机录像里
        #: 干员是会阵亡的。这条留成开关，便于对照两种读法。
        self.ranged_enemies = ranged_enemies
        #: 敌人**一次攻击动作占用的秒数**：出手后原地停这么久，然后继续推进。
        #:
        #: 注意这条改过口径。原先的读法是「锁到目标就中止路线推进」——等于
        #: 敌人只要看见人就在射程边缘站桩到死。1-7 的鸡尾酒投掷者（RANGED、
        #: 射程 1.75）因此永久停在怒潮凛冬 1-1 范围之外，谁也打不着它，
        #: 模拟给出「37 杀 4 漏」，而实机同配置录像（单干员）是 **41 杀 0 漏**。
        #: 与博士确认后改为此读法：**不会永久停，边走边打，只在攻击动作期间停一下**。
        #:
        #: 敌人动画长度不在 gamedata 里，所以这 0.5 秒是模拟器给定的，不是
        #: 实测值。它对结论的影响要用扫描来界定（见 `tools/check_battle.py`
        #: 与 `docs/` 里对应的敏感性表），别当成已证实的数。
        self.enemy_windup = max(0.0, float(enemy_windup))
        #: 治疗的作用面怎么算。凯尔希·思衡托技2 的原文是"回复**目标周围**所有
        #: 友方干员"，"周围"到底是 3×3 还是她自己的攻击范围，数据里没有——
        #: 所以留成开关，两种读法都能跑：
        #:   `range`  —— 治疗自己攻击范围内的友方（宽松读法）
        #:   `target` —— 只治疗被打中那个敌人**紧邻 8 格**内的友方（严格读法）
        #: 结论必须两种读法都成立才敢下，否则就是在用宽松假设换胜率。
        self.heal_mode = heal_mode

        self.deployments: list[Deployment] = []
        self.skill_uses: list[SkillUse] = []
        self.retreats: list[tuple[float, tuple[int, int]]] = []

        self.operators: list[OperatorUnit] = []
        self.enemies: list[EnemyUnit] = []
        self.cost = float(getattr(stage.options, "initial_cost", 0.0) or 0.0)
        self.max_cost = float(getattr(stage.options, "max_cost", 99.0) or 99.0)
        self.cost_time = float(getattr(stage.options, "cost_increase_time", 1.0) or 1.0)
        # `cbuff_cost_recovery.scale`（四星档常见 2 = 回复速度翻倍）。
        # 它改的是**每点费用几秒**，所以要除。1-7 的四星档就是这条。
        self._cost_scale = cost_recovery_scale(stage, environment_difficulty)
        if self._cost_scale and self._cost_scale != 1.0:
            self.cost_time = self.cost_time / self._cost_scale
        self._cost_timer = 0.0
        self.life = int(getattr(stage.options, "max_life_point", 1) or 1)
        # `global_lifepoint` 是**关卡级**的生命点改写（八关 EX 的四星档都把它
        # 改成 1，而关卡文件自己的 maxLifePoint 是 3、普通与四星两份**都是
        # 3**）。不接这条，四星档就凭空多两条命，而模拟照常给出结果。
        _lp = global_lifepoint(stage, environment_difficulty)
        if _lp is not None:
            self.life = int(_lp)

        # 关卡环境机制：田地 / 病害值。
        # 惰性导入——`environment` 依赖 `gamedata`，放在模块顶层会让
        # `battle` 的导入链牵上 gamedata（自检与 TUI 都只想要前者）。
        self.farmland = None
        #: 阻流阀等装置是否已建成。它们在开场后 `BUILD_SECONDS` 秒才生效，
        #: 一旦生效就把自身地块从田地里摘掉，**田地几何会在那一刻整片改变**。
        self._blockers_built = False
        # 装置表**无条件**解析：泵站 / 阻流阀归环境系统用，但「祟」明识形态的
        # 「清澈泵站生效范围内」判据、以及田鼷与阻流阀的互动也都要这张表。
        # 原先只在开了环境系统时解析，等于把这几条挂在"这一关有田地"上。
        from .devices import BLOCKER_KEY, parse_devices
        self._devices = parse_devices(stage)
        self._blocker_cells = [d.cell for d in self._devices if d.key == BLOCKER_KEY]
        if environment != "off":
            from .environment import FarmlandSystem, PolluteParams
            _p = PolluteParams.from_stage(stage, environment_difficulty)
            if _p is not None and _p.valid:
                self.farmland = FarmlandSystem(stage, _p)
        #: 环境伤害的每秒结算节拍（与病害值的【实际】更新同拍，都是 1 秒）。
        self._env_timer = 0.0

        # 预先把出怪时刻摊平
        self._spawns: list[tuple[float, object]] = sorted(
            stage.timeline(), key=lambda x: x[0])
        self._spawn_cursor = 0

        self._route_points: dict[int, list[tuple[float, float]]] = {}
        self._route_wait: dict[int, float] = {}
        #: 每条路线的分段计划（含离场传送）。传送必须分段——
        #: 连成一条折线的话敌人会从传送口"横穿半张地图"走到出口。
        self._route_legs: dict[int, list] = {}
        # 路线解析**与 ak_tactic.eta 共用同一份实现**：那边要用同样的
        # 路线长度算到达时刻，两处各写一遍必然对不上。
        self.route_plans = route_plans(stage)
        for _i, _p in self.route_plans.items():
            self._route_points[_i] = _p.points
            self._route_wait[_i] = _p.wait
            self._route_legs[_i] = _p.legs

        #: 场上的雪（每条积雪天赋一个）。空 = 没开天赋
        self.snow_fields: list[SnowField] = []
        #: 场上的增益治疗光环（「进入攻击范围时每秒回复」这类天赋）
        self.regen_auras: list[RegenAura] = []
        #: 场上的**全场**光环（「青色怒火」这类给全场友方加攻防的天赋）。
        #: 与 regen_auras 的差别是不看位置，且数值随主人技能状态每帧变。
        self.team_auras: list[TeamAura] = []
        #: 「全场总攻击」装置（P3R 的结算端）。关卡没有这个装置就是 None。
        self.total_attack: TotalAttackDevice | None = (
            total_attack if total_attack is not False else None)
        if self.total_attack is None and total_attack is not False:
            self.total_attack = make_total_attack(stage)
        self._t = 0.0
        #: BOSS 形态（真档位在 Mode_A/Mode_B，不在 TotalAttack）
        self.boss_mode = "Mode_A"
        #: BOSS 的弱点会不会**换形态**。关卡里那条敌人的描述原文是
        #: 「弱点：在**物理**和**法术**间切换」，而 `Skill_Revelation`
        #: （cd 30 / init 25 / idle 5 / disarmed 7）看着就是那次切换。
        #: 数据没写死触发条件，所以做成开关，几种读法都跑：
        #:   `none`  —— 永远停在 Mode_A（旧行为）
        #:   `time`  —— 每 30 秒切一次，首次在 25 秒
        #: **这一项是决定性的**：本关队伍全是物理伤害，Mode_A 是物弱（吃满
        #: 伤害＋攒击破），Mode_B 是**物免**——写死 Mode_A 恰好是最有利的读法。
        self.boss_mode_switch = boss_mode_switch
        #: 相性为「免疫」时是否把伤害归零。**默认 False（不归零）**——免疫只挡击破值，
        #: 见 `p3r.affinity_multiplier`。留这个开关是为了能跑对照实验。
        self.affinity_blocks_damage = affinity_blocks_damage
        self.mode_switches: list[tuple[float, str]] = []
        #: 换形态技能的黑板（`Skill_Revelation`）：cd / init / 待机 / 缴械。
        #: 从敌人数据里读，不写死。
        self.mode_skill: dict | None = None
        self._mode_next: float | None = None
        #: 每个敌人被击倒过几次（按 id 计）。`boss_mode_switch="knock"` 用它换形态。
        self._knocks: dict[int, int] = {}
        #: 场上所有活着的剑气（赤刃明霄陈 技3）。
        self._qis: list[dict] = []
        #: 剑气移动速度（格/秒）。原文只写了"向前/遇障碍右转/技能结束消失"，
        #: 没写速度，故显式做成参数而不是埋在常量里——这是未知量，不是设定值。
        #: 结论对它的敏感度必须扫描给出（`tools/run_srx8.py --qi-sweep` 那类跑法）。
        self.sword_qi_speed: float = max(0.1, float(sword_qi_speed))
        self.result = BattleResult(life=self.life)

    # -------------------------------------------------------- 计划

    def plan(self, deployment: Deployment) -> None:
        self.deployments.append(deployment)

    def use_skill(self, position, time: float) -> None:
        """排一次手动开技能。

        只是**请求**：技力不够就这一帧不开，等够了再开。真正的判定在
        `_skill_tick` 里，因为"能不能开"取决于那一刻的技力。
        """
        self.skill_uses.append(SkillUse(time=time, position=tuple(position)))

    def retreat(self, position, time: float) -> None:
        self.retreats.append((time, tuple(position)))

    # -------------------------------------------------------- 辅助

    def _range_of(self, op: OperatorUnit, elite: int | None = None) -> set[tuple[int, int]]:
        """干员当前的攻击格集合——技能改了范围就用技能给的那个代号。"""
        elite = op.elite if elite is None else elite
        rid = op.current_range_id()
        if self.range_provider is not None:
            try:
                try:
                    cells = self.range_provider(op.char_id, elite, op.direction,
                                                op.position, range_id=rid)
                except TypeError:
                    # 自定义的 range_provider 未必接受 range_id
                    cells = self.range_provider(op.char_id, elite, op.direction,
                                                op.position)
                if cells:
                    return cells
            except Exception:
                pass
        # 退化：自身格 + 朝向前方三格
        fx, fy = op.facing
        ox, oy = op.position
        return {(ox, oy)} | {(ox + fx * i, oy + fy * i) for i in (1, 2, 3)}

    # -------------------------------------------------------- 天赋：积雪

    def _ground_neighbours(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """四邻里可走的格（扩散只看上下左右，与"不许斜穿墙角"一致）。"""
        x, y = cell
        m = self.stage.map
        return [(nx, ny) for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                if m.walkable(nx, ny)]

    def _is_goal(self, cell: tuple[int, int]) -> bool:
        """这一格是不是防守点（`tile_end`）。"""
        m = self.stage.map
        if not m.inside(*cell):
            return False
        return m.tile(*cell).key == "tile_end"

    # ------------------------------------------------------------ 剑气（赤刃明霄陈 技3）

    def _spawn_qi(self, op: OperatorUnit, t: float) -> None:
        """技能开启时在前方放出一道剑气（赤刃明霄陈 技3）。

        原文：「技能开启时**向前**释放一道**可转向**的剑气，对穿过的敌人造成
        相当于其当前生命值 **6%** 的法术伤害（至少造成自身攻击力 **580%** 的法术伤害）」。

        用户补充的移动规则：**向前走，遇到障碍物右转，直到技能结束时消失**。
        「右转」按屏幕方向理解——朝右行进时右转即朝下；本项目按 MAA 标准
        y 向下为正，故屏幕下 = `+y`，旋转为 `(dx, dy) → (-dy, dx)`。

        伤害两处取自原文（6% 当前生命 / 下限 580% 攻击力），不写死数值。
        速度原文没写，做成构造参数 `sword_qi_speed`（2026-09-16 由录像实测为
        **1.2 格/秒**；旧默认值 4.0 是估的、偏快约 3.3 倍），未知量显式化。
        """
        sk = op.skill
        if sk is None or "剑气" not in (sk.description or ""):
            return
        d = {"Right": (1, 0), "Left": (-1, 0), "Up": (0, -1), "Down": (0, 1)}
        dx, dy = d.get(op.direction, (1, 0))
        self._qis.append({
            "owner": op.name, "atk": float(op.atk),
            "x": float(op.position[0]), "y": float(op.position[1]),
            "dx": dx, "dy": dy, "hit": set(),
        })
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 放出剑气（朝{op.direction}）")

    def _qi_tick(self, dt: float, t: float) -> None:
        """推进所有剑气：移动 → 碰障碍右转（并刷新命中状态）→ 穿过谁就打谁。

        命中语义（用户口径）：**直行时同一敌人只吃一次伤害；拐弯之后状态刷新**，
        再路过它就再吃一次。所以 `q["hit"]` 在每次转向时清空——
        这让「拐弯折返扫两遍」的伤害成立，也决定了剑气在窄道里的实际收益。
        """
        if not self._qis:
            return
        m = self.stage.map
        speed = float(self.sword_qi_speed)
        alive = []
        for q in self._qis:
            # 技能结束了，剑气就该消失
            op = next((o for o in self.operators
                       if o.name == q["owner"] and o.alive), None)
            if op is None or not op.skill_active:
                continue
            step = speed * dt
            remain = step
            while remain > 0:
                move = min(remain, 1.0)
                nx = q["x"] + q["dx"] * move
                ny = q["y"] + q["dy"] * move
                # 前方一格不可走 → 右转（最多试四次，转回原向就停住）
                tx, ty = int(round(nx)), int(round(ny))
                if not m.walkable(tx, ty):
                    q["dx"], q["dy"] = q["dy"], -q["dx"]
                    # 拐弯会**刷新命中状态**（用户口径）：直行时同一个敌人只吃一次，
                    # 但转过弯之后再路过它，会再吃一次。所以这里清空已命中集合。
                    q["hit"].clear()
                    continue
                q["x"], q["y"] = nx, ny
                remain -= move
                cx, cy = int(round(q["x"])), int(round(q["y"]))
                for e in self.enemies:
                    if not e.alive or e.leaked or e.off_map or id(e) in q["hit"]:
                        continue
                    if (int(round(e.position[0])), int(round(e.position[1]))) != (cx, cy):
                        continue
                    q["hit"].add(id(e))
                    raw = max(e.hp * 0.06, q["atk"] * 5.8)
                    dtype = DamageType.MAGIC
                    if op.weakness_damage:
                        dtype, dres = self._adaptive_damage_raw(raw, e)
                        final = dres
                    else:
                        final = raw
                    self._damage_enemy(e, float(final), t, dtype)
                    if self.verbose:
                        self.result.log.append(
                            f"{t:7.1f}s  剑气穿过 {e.name} 造成 {final:,.0f} 法术伤害")
            alive.append(q)
        self._qis = alive

    def _adaptive_damage_raw(self, raw: float, target: EnemyUnit):
        """「弱点伤害」的另一种入口：手里只有一个伤害值（剑气那种按倍率算好的）。

        物理按 DEF 折、法术按 RES 折，哪个高走哪个；相性免疫侧归零。
        """
        best = None
        for dt in (DamageType.PHYSICAL, DamageType.MAGIC):
            d = resolve_damage(raw, damage_type=dt,
                               defense=target.defense, res=target.res)
            slot = damage_slot(dt)
            aff = target.affinity.get(slot) if slot else None
            val = d.final * affinity_multiplier(
                aff, immune_blocks_damage=self.affinity_blocks_damage)
            if best is None or val > best[0]:
                best = (val, dt, d.final)
        return best[1], best[2]

    def _snow_tick(self, dt: float, t: float) -> None:
        """积雪：积层 → 判踏入 → 施减速 → 技能期间追加每秒伤害。

        顺序有讲究：本函数排在敌人推进**之后**，所以这一帧读到的
        `e.position` 已经是新位置，"踏入了新格"才判得准；而减速写进
        `e.speed_multiplier` 是给**下一帧**的 `advance` 用。
        """
        if not self.snow_fields:
            return
        m = self.stage.map

        # 已经不在场上的敌人（死亡/漏怪/传送离场）要按"首敌离场"规则清掉它踩过的雪
        live = {id(e) for e in self.enemies
                if e.alive and not e.leaked and not e.off_map}
        for sf in self.snow_fields:
            for gone in [k for k in sf.last_cell if k not in live]:
                sf.leave_all(gone)

        # --- 积层 ---
        for sf in self.snow_fields:
            op = sf.operator
            if op is None or not op.alive:
                continue
            ground = [c for c in self._range_of(op) if m.walkable(*c)]
            # 技能2 开着时：扩散上限提到 max_cast_tile_count，并附上每秒伤害
            sf.spread_cap = 0
            sf.dot_scale = 0.0
            sk = getattr(op, "skill", None)
            if op.skill_active and sk is not None:
                other = getattr(getattr(sk, "effects", None), "other", {}) or {}
                sf.spread_cap = int(other.get("talent@max_cast_tile_count") or 0)
                sf.dot_scale = float(other.get("talent@s2_magic_scale") or 0.0)
            if sf.tick(dt, ground, self._ground_neighbours) and self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {sf.owner} 积雪 {len(sf.layers)} 格、"
                    f"最高 {max(sf.layers.values(), default=0)} 层")

        # --- 敌人 ---
        for e in self.enemies:
            if not e.alive or e.leaked or e.off_map:
                continue
            key = id(e)
            cell = (int(round(e.position[0])), int(round(e.position[1])))
            e.frozen = False
            if not m.walkable(*cell):
                e.speed_multiplier = 1.0
                continue
            e.speed_multiplier = 1.0
            for sf in self.snow_fields:
                op = sf.operator
                if op is None or not op.alive:
                    continue
                slow = sf.slow_at(cell)
                if slow < 1.0:
                    e.speed_multiplier *= slow
                # 满层地块「变为冻结状态」：站在上面的敌人不能移动也不能攻击。
                # 但**防守点格不冻结**——已经踏到终点格的敌人按漏怪处理，把它
                # 冻在离终点半格的地方会让它永远到不了终点，等于白送一条命。
                if (self.snow_freeze and sf.layers.get(cell, 0) >= sf.max_layers > 0
                        and not self._is_goal(cell)):
                    e.frozen = True
                atk = op.current_atk()
                # 注意：`_snow_hit` 自己已经把伤害记进 damage_dealt 了
                hit = sf.enter(key, cell, atk, lambda raw, en=e: self._snow_hit(en, raw))
                if hit > 0:
                    if self.verbose:
                        self.result.log.append(
                            f"{t:7.1f}s  {sf.owner} 积雪伤害 {hit:,.0f} → {e.name}")
                    if not e.alive:
                        sf.leave_all(key)
                        break
                # 技能2：雪格上的地面敌人每秒再吃一次
                if sf.dot_scale > 0 and sf.layers.get(cell, 0) > 0:
                    self._snow_hit(e, sf.dot_scale * atk * dt)
                    if not e.alive:
                        sf.leave_all(key)
                        break

    def _snow_hit(self, enemy: EnemyUnit, raw: float) -> float:
        """积雪造成的法术伤害——走正规的法抗结算，不吃物理的 5% 保底。"""
        if raw <= 0:
            return 0.0
        amount = resolve_damage(raw, damage_type=DamageType.MAGIC,
                                defense=enemy.defense, res=enemy.res)
        return self._damage_enemy(enemy, float(amount), self._t, DamageType.MAGIC)

    # -------------------------------------------------------- 伤害相性 P3R

    def _damage_enemy(self, target: EnemyUnit, final: float, t: float,
                      damage_type: str = "",
                      source: "OperatorUnit | None" = None) -> float:
        """对敌人结算一次伤害的**唯一入口**：过相性 → 扣血 → 累积击破值。

        相性只决定**击破值能不能累积**（0 弱点才累积），**不减免伤害**——
        详见 `p3r.affinity_multiplier` 的 2026-09 修订说明。
        `affinity_blocks_damage=True` 可切回旧的「免疫即归零」行为做对照。
        所有打向敌人的伤害都必须走这里，否则相性规则会被绕过——
        积雪、总攻击、普攻三条路都接进来了。

        【怀黍离】另外三个机制也挂在这个出口上，理由同上——它们都以
        「受到一次伤害」为触发条件，散在各自的调用点会漏掉某一类伤害：

        * **无敌**（明识形态开场 5 秒、天桩-甲的监测状态）→ 直接归零；
        * **蜕皮**（`Passive_Hit.`）：每受 N 次伤害叠一层，**次数**而不是
          伤害量，所以数的是本函数的调用次数；
        * **加速**（`SpeedUp.`）：受伤且**未被阻挡**时获得移速增益；
        * **标记**（`PassiveM2.`）：明识形态下记下伤害来源，它退场时污染田地。

        `source` 是伤害来源的干员（积雪、装置这类没有明确来源的传 None）。
        """
        now = t
        # 1. 无敌：明识形态的开场 5 秒、天桩-甲的监测状态。
        #    注意**只挡伤害**，不挡「重设生命」这类直接写血（天桩-甲那套）。
        if (getattr(target, "always_invincible", False)
                or now < getattr(target, "invincible_until", -1.0)):
            return 0.0
        slot = damage_slot(damage_type)
        aff = target.affinity.get(slot) if slot else None
        amount = final * affinity_multiplier(
            aff, immune_blocks_damage=self.affinity_blocks_damage)
        dealt = target.take(amount)
        if dealt <= 0:
            return 0.0
        self.result.damage_dealt += dealt
        st = target.break_state
        if st is not None and st.add(dealt, aff, t):
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {target.name} 击破值满 → 倒地 {st.fall_duration:g}s")
            self._note_knockdown(target, t)
        self._enemy_on_hit(target, dealt, t, source)
        return dealt

    def _enemy_on_hit(self, e: EnemyUnit, dealt: float, t: float,
                      source: "OperatorUnit | None") -> None:
        """「挨了一次伤害」之后要发生的事：蜕皮、加速、标记。

        单独一个函数是因为这三样都只认**次数**、不认伤害量，而且必须
        在扣完血之后判（挨打的那一下本身也会触发蜕皮）。
        """
        # ---- 蜕皮（Passive_Hit.）：「祟」混沌形态
        if e.phit_cnt > 0 and e.phit_stacks < e.phit_max_stack:
            e.phit_hits += 1
            while (e.phit_hits >= e.phit_cnt
                   and e.phit_stacks < e.phit_max_stack):
                e.phit_hits -= e.phit_cnt
                e.phit_stacks += 1
                e.atk += e.phit_atk          # 黑板存的是负数（-40 = 降低 40）
                e.defense += e.phit_def
                e.res += e.phit_res
                e.move_speed += e.phit_move
                # 每 N 层重量等级 −1
                if e.phit_weight_cnt > 0 and e.phit_stacks % e.phit_weight_cnt == 0:
                    e.weight = max(0.0, e.weight - 1.0)
                # 污染：「阻挡自身的单位(被阻挡时)/自身(未被阻挡时)半径1.0内」
                self._pollute_around(
                    e, t, e.phit_block_pollut if e.blocked_by is not None
                    else e.phit_pollut, 1.0, "蜕皮")
        # ---- 加速（SpeedUp.）：受伤且未被阻挡
        if (e.speedup_move > 0.0 and e.blocked_by is None
                and e.haste_multiplier <= 1.0 and t >= e.speedup_ready_at):
            e.speedup_timer = e.speedup_duration
            e.speedup_ready_at = t + e.speedup_cooldown
            e.haste_multiplier = 1.0 + e.speedup_move
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 受击 → 移速 "
                    f"+{e.speedup_move * 100:.0f}%（{e.speedup_duration:g}s）")
        # ---- 标记（PassiveM2.）：明识形态记下伤害来源
        if e.pm2_active and source is not None:
            e.marked_ops.add(id(source))

    def _pollute_around(self, e: EnemyUnit, t: float, amount: float,
                        radius: float, why: str) -> float:
        """在「阻挡自身的单位(被阻挡时)/自身(未被阻挡时)」周围抬高田地病害值。

        圆心按原文取：被阻挡时是**挡它的那个干员**脚下那一格，否则是敌人
        自己脚下那一格。半径按**圆**算（半径 1.0 恰好够到上下左右四邻、
        够不到斜角，见 `environment.cells_in_radius`）。
        """
        if amount <= 0.0 or self.farmland is None:
            return 0.0
        if e.blocked_by is not None and e.blocked_by.alive:
            cx, cy = e.blocked_by.position
        else:
            cx, cy = e.cell()
        got = self.farmland.pollute_area(int(cx), int(cy), radius, amount)
        if got > 0.0 and self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {e.name} {why} → 田地病害值 +{got:.0f}"
                f"（{amount:g} × 范围内田地格）")
        return got

    def _note_knockdown(self, target: EnemyUnit, t: float) -> None:
        """BOSS 倒地了一次 —— **每倒地一次就切换一次免疫类型**（用户实机确认）。

        「死志的凝结」的两套相性 `Mode_A`（物弱·法免）与 `Mode_B`（物免·法弱）
        是每次倒地翻转一轮，不是按秒计时。

        我曾经从同类敌人 `enemy_10190_pppham`（几点了钟）的
        `PowerAttackTrigger.trigger_cnt = 2`（对应描述「**数次攻击后**使目标晕眩」）
        反推 BOSS 的 `Mode_A.trigger_cnt = 2` 是「每倒地 2 次换一次」——**推错了**。
        真实节奏是每倒地 1 次。`trigger_cnt` 在这两个 prefab 上不是同一回事。

        注意由此产生的死锁：BOSS 换进 `Mode_B`（物免）后，物理伤害**归零**，
        而击破值只按实际掉血量累积 ⇒ 物理**再也攒不动击破值**，
        必须靠法术把它打倒才能翻回 `Mode_A`。这条链要转起来，两侧伤害都得够。
        """
        if self.boss_mode_switch != "knock" or not getattr(target, "modes", None):
            return
        key = id(target)
        self._knocks[key] = self._knocks.get(key, 0) + 1
        # 每倒地一次就换 —— 不读 `Mode_X.trigger_cnt`（那是 2，但实机是一换一）
        self._switch_boss_mode(t)

    def _environment_tick(self, dt: float, t: float) -> None:
        """关卡环境机制：田地/病害值的演化与结算（怀黍离）。

        三个节拍各归各的：病害值【缓存】每 0.2s 释放 1 点、【实际】每秒向
        【最大】靠拢（都由 `FarmlandSystem.tick` 管）；**环境伤害按每秒结算
        一次**，因为原文写的是「每秒受到 … 环境法术伤害」。

        结算对象是**站在田地上的我方单位**：病害值 >0 吃伤害，=0 时按
        `hp_recovery_per_sec` 回血（同一个机制的两面，不是两个机制）。
        高台天然取不到田地——田地判据本身就要求低地。
        """
        fs = self.farmland
        if fs is None:
            return

        from .devices import BUILD_SECONDS
        # 阻流阀建成：一次性事件，**改变田地几何本身**（它把自身地块从田地里
        # 摘掉，连片的田地因此被切断）。放在推进之前，因为这一刻之后要靠拢的
        # 目标（【最大】）已经换了。
        # 建成耗时取自装置自己的技能 `duration`（「3秒后建成」）。
        if not self._blockers_built and t >= BUILD_SECONDS:
            self._blockers_built = True
            for cell in self._blocker_cells:
                fs.sever(*cell)
            if self.verbose and self._blocker_cells:
                self.result.log.append(
                    f"{t:7.1f}s  阻流阀建成 ×{len(self._blocker_cells)}，"
                    f"田地重划为 {len(fs.fields)} 片")

        fs.tick(dt)

        # 伤害按整秒结算。用整数计数而不是 `>= 1.0` 后清零：掉帧时 dt 可能
        # 跨过不止一秒，只结一次等于把伤害漏掉（模拟器 fps 30 时不会发生，
        # 但 `fps=1` 的粗扫会，而粗扫正是搜索里用得最多的档）。
        self._env_timer += dt
        ticks = int(self._env_timer)
        if ticks <= 0:
            return
        self._env_timer -= ticks

        # 泵站泵水（每秒一次）。必须排在伤害结算**之前**：泵水改的是病害值，
        # 而这一秒的伤害要按**泵过之后**的病害值算——反过来的话，玩家用泵站
        # 压低病害值的那一秒仍会按旧值挨打，且这个偏差在每秒都发生。
        from .environment import pump_once
        if self._devices:
            pump_once(fs, self._devices,
                      ally_cells=[op.position for op in self.operators
                                  if op.alive])

        for op in self.operators:
            if not op.alive:
                continue
            cell = op.position
            if not fs.is_farmland(*cell):
                continue
            dmg = fs.damage_per_second(*cell)
            if dmg > 0:
                op.take(dmg * ticks)
                continue
            # 病害值为 0 的田地改成回血，且**回复量与病害值无关**（恒 50/秒）。
            heal = fs.regen_per_second(*cell)
            if heal > 0:
                op.heal(heal * ticks)

    def _p3r_tick(self, dt: float, t: float) -> None:
        """P3R：刷新倒地状态 → 驱动「全场总攻击」装置 → 打出真伤。"""
        if self.total_attack is None:
            return
        # 1. 刷新每只敌人的倒地标记（倒地 = 眩晕 + 不可阻挡）
        states: list[tuple[bool, str]] = []
        for e in self.enemies:
            if not e.alive or e.leaked or e.off_map:
                continue
            st = e.break_state
            e.down = bool(st is not None and st.is_down(t))
            if st is not None and st.enabled:
                states.append((e.down, e.name))

        # 2. 装置判定
        ally_atk = sum(o.current_atk() for o in self.operators if o.alive)
        fired_buff, fired_hit = self.total_attack.tick(
            t, down_states=states, ally_atk_sum=ally_atk)
        if fired_buff and self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  全场总攻击：全队获得攻击力 +{self.total_attack.bonus_atk:,.0f}")
        if not fired_hit:
            return

        # 3. 全场敌方真实伤害（可对空，无来源，不吃防御/法抗/相性）
        power = self.total_attack.trigger_value(ally_atk)
        victims = [e for e in self.enemies
                   if e.alive and not e.leaked and not e.off_map]
        for e in victims:
            dealt = e.take(power)
            self.result.damage_dealt += dealt
            self.total_attack.total_damage += dealt
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  全场总攻击：对 {len(victims)} 名敌人造成 {power:,.0f} 真实伤害")
        # 4. 解除全场倒地
        for e in self.enemies:
            if e.break_state is not None:
                e.break_state.clear()
            e.down = False

    def _note_mode_skill(self, stats, t: float) -> None:
        """记下这个敌人的换形态技能（`Skill_Revelation`）的黑板。

        从 `skills_raw` 里读，不写死数字：cd 30 / init 25 / idle 5 / disarmed 7
        都是这一关的实际取值，换关卡换数值也不会失准。
        """
        for sk in (getattr(stats, "skills_raw", None) or ()):
            if str(sk.get("prefabKey") or "") != "Skill_Revelation":
                continue
            bb = {b.get("key"): b.get("value") for b in (sk.get("blackboard") or [])}
            tbb = getattr(stats, "talent_blackboard", None) or {}
            if self.mode_skill is None:
                self.mode_skill = {
                    "cd": float(sk.get("cooldown") or 0.0),
                    "init": float(sk.get("initCooldown") or 0.0),
                    "idle": float(bb.get("idle_duration") or 0.0),
                    "disarm": float(bb.get("disarmed_duration") or 0.0),
                    # 换形态要攒几次「条件」——`Mode_A/trigger_cnt` 与
                    # `Mode_B/trigger_cnt` 都写着 2。这个字段的语义是从同类敌人
                    # 反推出来的：`enemy_10190_pppham`（几点了钟）的
                    # `PowerAttackTrigger.trigger_cnt = 2`，对应描述
                    # 「**数次攻击后**使目标晕眩」——即"条件满足几次才触发"。
                    "trigger": float(tbb.get("Mode_A.trigger_cnt")
                                     or tbb.get("Mode_B.trigger_cnt") or 0.0),
                }
                self._mode_next = t + float(self.mode_skill["init"])

    def _spawn(self, enemy_id: str, level: int, route_index: int, t: float) -> EnemyUnit:
        pts = self._route_points.get(route_index) or []
        legs = self._route_legs.get(route_index) or []
        # 有分段计划时，开头的待命已经是计划里的 wait 段，别再设一遍
        wait = 0.0 if legs else self._route_wait.get(route_index, 0.0)
        return self._build_enemy(enemy_id, level, pts, legs, t, wait)

    def _summon_at(self, enemy_key: str, cnt: int, cell: tuple[int, int],
                   t: float, parent: "EnemyUnit") -> list[EnemyUnit]:
        """在 `cell` 原地召唤 `cnt` 个 `enemy_key`（怀黍离「祟」重生期间的随从）。

        原文：「在自身位置**1.0 边长正方形范围内随机位置**召唤 N 个…，
        并自动生成通往**最近可通行保护目标**的路径」。

        两处按本项目的约定收口：

        * **1.0 边长的正方形**从格心量出去正好覆盖脚下那一格（±0.5），
          所以召唤位置就是脚下格，**不做随机**——模拟器必须可复现，
          掷骰会让同一份作业每次跑出不同结果。
        * 终点取地图的**保护目标**里最近的一个，路径走 `ground_path`，
          与 `eta.route_plans` 用的是同一个寻路。
        """
        path = self._path_from(cell)
        if not path:
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {parent.name} 召唤 {enemy_key} 失败："
                    f"{cell} 走不到任何保护目标")
            return []
        # 惰性导入：`battle` 的导入链**不牵 gamedata**（自检与 TUI 只用前者）
        from ..gamedata.stage import RouteLeg
        pts = [(float(x), float(y)) for x, y in path]
        legs = [RouteLeg(kind="walk", points=path,
                         length=self.stage.map.path_length(path))]
        out = []
        for _ in range(max(0, int(cnt))):
            e = self._build_enemy(enemy_key, self._summon_level(enemy_key),
                                  pts, legs, t, 0.0)
            self.enemies.append(e)
            out.append(e)
        if self.verbose and out:
            self.result.log.append(
                f"{t:7.1f}s  {parent.name} 召唤 {len(out)} 个 {out[0].name}"
                f" 于 {cell}（{len(path)} 格到保护目标）")
        return out

    def _summon_level(self, enemy_key: str) -> int:
        """被召唤的敌人用哪一档数值。

        先看这一关的 `enemyDbRefs` 有没有点名它（有就按那一档），
        没有就用 0 档——**不猜**。召唤体往往不在关卡的出怪表里，
        所以这条回退路径是常态而不是异常。
        """
        for ref in (getattr(self.stage, "enemy_refs", None) or []):
            if str(ref.get("id") or "") == enemy_key:
                try:
                    return int(ref.get("level") or 0)
                except (TypeError, ValueError):
                    return 0
        return 0

    def _path_from(self, cell: tuple[int, int]) -> list[tuple[int, int]]:
        """从 `cell` 走到**最近的可达保护目标**的那条路。

        逐目标试 `ground_path`（它不可达时返回空），取第一条走通的——
        「最近」按路径长度而不是直线距离算：绕远路的直线距离可能更近。
        """
        m = self.stage.map
        best: list[tuple[int, int]] = []
        for goal in m.end_points:
            p = m.ground_path(cell, goal)
            if not p:
                continue
            if not best or len(p) < len(best):
                best = list(p)
        return best

    def _build_enemy(self, enemy_id: str, level: int, pts: list, legs: list,
                     t: float, wait: float) -> EnemyUnit:
        stats = self.enemy_at(enemy_id, level)
        self._note_mode_skill(stats, t)
        # P3R：相性取形态档（BOSS 的真档位在 Mode_A，它的 TotalAttack 是 1/1/1）
        aff = {}
        bk = None
        if self.total_attack is not None:
            modes = getattr(stats, "modes", None) or {}
            aff = (modes.get(self.boss_mode) if self.boss_mode in modes
                   else (getattr(stats, "p3r", None) or {}))
            if getattr(stats, "has_p3r", False):
                bk = BreakState(weak_max=float(getattr(stats, "weak_max", 0.0) or 0.0),
                                fall_duration=float(getattr(stats, "fall_duration", 0.0) or 0.0))
        e = EnemyUnit(
            name=getattr(stats, "name", enemy_id) or enemy_id,
            enemy_id=enemy_id,
            level=level,
            max_hp=float(getattr(stats, "max_hp", 0) or 0),
            atk=float(getattr(stats, "atk", 0) or 0),
            defense=float(getattr(stats, "defense", 0) or 0),
            res=float(getattr(stats, "magic_resistance", 0) or 0),
            attack_interval=float(getattr(stats, "base_attack_time", 1.0) or 1.0),
            attack_type="PHYSICAL",
            weight=float(getattr(stats, "weight", 0) or 0),
            # 移速 0 = 原地不动（库里 23 页如此）。**不能写 `or 1.0`**——
            # 那会把 0 兜成 1，让一个永不移动的敌人满地图跑。同一个函数里
            # 下面 life_cost 那一行已经因为同样的写法踩过一次。
            move_speed=float(
                _ms if (_ms := getattr(stats, "move_speed", None)) is not None
                else 1.0),
            # lifePointReduce 允许为 0：「没办法车」漏掉**不扣命**。
            # 早先这里写的是 `... or 1`，会把 0 悄悄变成 1。
            life_cost=int(_lp if (_lp := getattr(stats, "life_point_reduce", 1)) is not None else 1),
            route=pts,
            legs=legs,
            affinity=aff,
            modes=dict(getattr(stats, "modes", None) or {}),
            break_state=bk,
            position=pts[0] if pts else (0.0, 0.0),
            spawn_time=t,
            # 有分段计划时，开头的待命已经是计划里的 wait 段，别再设一遍
            wait_remaining=wait,
            # ---- 关卡机制
            is_flying=bool(getattr(stats, "is_flying", False)),
            apply_way=str(getattr(stats, "apply_way", "MELEE") or "MELEE"),
            attack_range=float(getattr(stats, "range_radius", 0.0) or 0.0),
            kill_cost=int(getattr(stats, "kill_cost", 0) or 0),
            reborn_left=int(getattr(stats, "reborn_count", 0) or 0),
            reborn_delay=float(getattr(stats, "reborn_duration", 0.0) or 0.0),
            reborn_hp_ratio=float(getattr(stats, "reborn_hp_ratio", 1.0) or 1.0),
            # 怀黍离：重生期充能（瘴 / 鄙瘴）。没有这套机制的敌人全为 0。
            reborn_interval=float(getattr(stats, "reborn_interval", 0.0) or 0.0),
            reborn_pollut=float(getattr(stats, "reborn_pollut", 0.0) or 0.0),
            reborn_def_add=float(getattr(stats, "reborn_def_add", 0.0) or 0.0),
            reborn_damage_magic=float(
                getattr(stats, "reborn_damage_magic", 0.0) or 0.0),
            # 再生期间按间隔召唤（怀黍离「祟」：每 8 秒 2 个去蚀、每 20 秒 1 个厌肮）。
            # 与上面的充能是**两条互不相干**的重生分支：瘴走到充能那支，
            # 「祟」走到召唤这支，判据各看各的键。
            reborn_summons=tuple(getattr(stats, "reborn_summons", ()) or ()),
            # ---- 六个机制前缀（怀黍离；来历见 gamedata/enemy.py::mech_fields）
            passive_pollut=float(getattr(stats, "passive_pollut", 0.0) or 0.0),
            passive_radius=float(getattr(stats, "passive_radius", 0.0) or 0.0),
            death_token=str(getattr(stats, "death_token", "") or ""),
            death_cnt=int(getattr(stats, "death_cnt", 0) or 0),
            aura_hit_ratio=float(getattr(stats, "aura_hit_ratio", 0.0) or 0.0),
            aura_hit_radius=float(
                getattr(stats, "aura_hit_radius", 0.5) or 0.5),
            speedup_move=float(getattr(stats, "speedup_move", 0.0) or 0.0),
            speedup_duration=float(getattr(stats, "speedup_duration", 0.0) or 0.0),
            speedup_cooldown=float(getattr(stats, "speedup_cooldown", 0.0) or 0.0),
            phit_cnt=int(getattr(stats, "phit_cnt", 0) or 0),
            phit_atk=float(getattr(stats, "phit_atk", 0.0) or 0.0),
            phit_def=float(getattr(stats, "phit_def", 0.0) or 0.0),
            phit_res=float(getattr(stats, "phit_res", 0.0) or 0.0),
            phit_move=float(getattr(stats, "phit_move", 0.0) or 0.0),
            phit_pollut=float(getattr(stats, "phit_pollut", 0.0) or 0.0),
            phit_block_pollut=float(
                getattr(stats, "phit_block_pollut", 0.0) or 0.0),
            phit_extra=float(getattr(stats, "phit_extra", 0.0) or 0.0),
            phit_max_stack=int(getattr(stats, "phit_max_stack", 0) or 0),
            phit_weight_cnt=int(getattr(stats, "phit_weight_cnt", 0) or 0),
            pm2_atk=float(getattr(stats, "pm2_atk", 0.0) or 0.0),
            pm2_def=float(getattr(stats, "pm2_def", 0.0) or 0.0),
            pm2_res=float(getattr(stats, "pm2_res", 0.0) or 0.0),
            pm2_move=float(getattr(stats, "pm2_move", 0.0) or 0.0),
            pm2_clean_def=float(getattr(stats, "pm2_clean_def", 0.0) or 0.0),
            pm2_clean_res=float(getattr(stats, "pm2_clean_res", 0.0) or 0.0),
            pm2_clean_move=float(getattr(stats, "pm2_clean_move", 0.0) or 0.0),
            pm2_mark_pollut=float(getattr(stats, "pm2_mark_pollut", 0.0) or 0.0),
            pm2_invincible=float(getattr(stats, "pm2_invincible", 0.0) or 0.0),
            pm2_pollut_threshold=float(
                getattr(stats, "pm2_pollut_threshold", 0.0) or 0.0),
        )
        # 防御力基准：充能加成按它重算，避免二次重生时把上次的加成再乘一遍
        e.reborn_def_base = e.defense
        # 屏障：按最大生命折算，在血量之前被消耗
        ratio = float(getattr(stats, "shield_hp_ratio", 0.0) or 0.0)
        if ratio:
            e.shield = e.shield_max = e.max_hp * ratio
        return e

    def _alive_op_at(self, cell) -> OperatorUnit | None:
        for op in self.operators:
            if op.alive and op.position == cell:
                return op
        return None

    # -------------------------------------------------------- 技能

    def _attach_skill(self, op: OperatorUnit, d: "Deployment") -> None:
        """把这次部署要用的技能挂到干员身上。

        `Deployment.skill` 允许两种写法：槽位号（1/2/3）或一个现成的
        `SkillLevel`。给槽位号时必须配 `skill_book`，因为"1 号槽是哪个技能"
        要查 `character_table`。
        """
        spec = d.skill
        if spec is None or spec == 0:
            op.skill = None
            return
        if not isinstance(spec, int):
            op.skill = spec                      # 已经是 SkillLevel
        else:
            if self.skill_book is None:
                raise ValueError(
                    f"要按槽位号取技能（skill={spec}）就得给模拟器一个 "
                    f"skill_book=SkillBook()，或者直接把 SkillLevel 传给 skill=")
            slots = self.skill_book.for_operator(op.char_id)
            hit = next((s for s in slots if s.slot == spec), None)
            if hit is None:
                raise ValueError(
                    f"{op.char_id} 没有 {spec} 号技能槽"
                    f"（有 {[s.slot for s in slots]}）")
            op.skill = hit.level(d.skill_level, d.skill_mastery)

        if op.skill is not None and not op.skill.is_passive:
            op.sp = float(op.skill.init_sp)

        # 描述驱动的效果解析：`resolved_effects` 会把描述推出来的公式并进黑板
        # 结果（`merge` 只补空缺），再挂到干员身上优先使用。
        if op.skill is not None and self.effect_source != "blackboard":
            try:
                resolved, diffs = op.skill.resolved_effects(self.effect_source)
            except Exception as exc:            # pragma: no cover - 防御性
                resolved, diffs = None, []
                self.result.log.append(
                    f"描述解析失败（沿用黑板）：{op.char_id} {exc}")
            if resolved is not None and resolved is not op.skill.effects:
                op.effects_override = resolved
                self.result.effect_source_used[op.char_id] = self.effect_source
                for d in diffs:
                    if d.verdict == "conflict":
                        self.result.effect_conflicts.append(
                            f"{op.char_id} {op.skill.name} {d.line()}")

    def _skill_tick(self, dt: float, t: float) -> None:
        """每帧的技能结算：回技力、够不够开、持续到点了没有。"""
        res = self.result
        for op in self.operators:
            if not op.alive:
                continue
            # 自晕倒计时（技能结束后自身晕眩）。递减挂在这里只是因为它
            # 同样按帧走；晕眩本身与技能状态无关。
            if op.stun_timer > 0:
                op.stun_timer = max(0.0, op.stun_timer - dt)
            if op.skill is None:
                continue
            sk = op.skill

            # 被动技能：部署即生效，不耗技力，永不关闭
            if sk.is_passive:
                if not op.skill_active:
                    self._activate(op, t, passive=True)
                continue

            if op.skill_active:
                # 持续时间倒计时（无限持续是 inf，减不完）
                if op.skill_timer != _INFINITE:
                    op.skill_timer -= dt
                    if op.skill_timer <= 0:
                        self._deactivate(op, t)
                        continue
                # 弹药类：打光就结束
                if sk.duration_type == "AMMO" and op.ammo_left <= 0:
                    self._deactivate(op, t)
                    continue
                # 只有多充能技能在开启期间还继续攒技力
                if sk.max_charge > 1 and sk.sp_type == "INCREASE_WITH_TIME":
                    op.sp = min(sk.sp_cost * sk.max_charge, op.sp + sk.increment * dt)
                op.skill_request = False
                continue

            # 未开启：按回复方式攒技力
            if sk.sp_type == "INCREASE_WITH_TIME":
                op.sp = min(sk.sp_cost, op.sp + sk.increment * dt)

            ready = op.sp >= sk.sp_cost
            want = op.skill_request or sk.auto_trigger or op.auto_skill
            # 「整场战斗中该技能只能释放一次」（阿米娅技2 影霄·绝影）：
            # 放过一次就不再开，哪怕技力又攒满。`sp_charges` 是累计开启次数。
            if sk.effects.once_per_battle and op.sp_charges >= 1:
                want = False
            if ready and want:
                self._activate(op, t)
            op.skill_request = False

    def _activate(self, op: OperatorUnit, t: float, *, passive: bool = False) -> None:
        sk = op.skill
        if sk is None:
            return
        if not passive:
            op.sp = max(0.0, op.sp - float(sk.sp_cost))
        op.skill_active = True
        op.sp_charges += 1
        dur = sk.effective_duration
        op.skill_timer = _INFINITE if dur is None else float(dur)
        op.ammo_left = int(sk.effects.ammo or 0)
        op.apply_max_hp_bonus(sk.effects.buffs.get("max_hp", 0.0))
        # 技能把这一击的伤害类型改写了（"真实伤害"这一族判据）。两种要分开：
        # `true_damage` 是整条技能每一次都真实；`true_from_final_hit` 只有
        # 末击与之后的普攻是真实，前 N-1 击仍是本来的类型（见攻击循环里的
        # `slash_pending`）。两者都置 `skill_attack_type`，差别在斩击那一次。
        op.skill_attack_type = (
            "TRUE" if (sk.effects.true_damage
                       or sk.effects.true_from_final_hit) else None)
        op.slash_pending = sk.effects.true_from_final_hit
        # 技能期间获得的闪避（赤刃明霄陈技2「获得 60% 物理和法术闪避」）。
        # 值由描述驱动（`skill._wants_dodge`）——黑板那个键叫 `prob`，
        # 与提丰技2 的「40% 概率晕眩」同名反义，按键名认必错。
        op.dodge_phys = sk.effects.dodge_phys
        op.dodge_arts = sk.effects.dodge_arts
        # 回费技能（德克萨斯、桃金娘这一类）：开启时直接给费用
        gain_cost = sk.effects.buffs.get("cost", 0.0)
        if gain_cost:
            self.cost = min(self.max_cost, self.cost + gain_cost)
        self.result.skill_activations += 1
        self._spawn_qi(op, t)
        if self.verbose:
            d = "无限" if dur is None else f"{dur:g}s"
            ammo = f" 弹药 {op.ammo_left}" if op.ammo_left else ""
            refund = f" 回费 +{gain_cost:g}" if gain_cost else ""
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 开启「{sk.name}」（{d}{ammo}{refund}）")

    def _deactivate(self, op: OperatorUnit, t: float) -> None:
        sk = op.skill
        op.skill_active = False
        op.skill_timer = 0.0
        op.ammo_left = 0
        op.skill_attack_type = None
        op.revert_max_hp_bonus()
        op.sp = 0.0
        # 击杀叠层清零：「持续至技能结束」。技能结束就要掉回原样，
        # 不能带到下一次开技能（阿米娅技2 整场只放一次，但机制上如此）。
        op.kill_stacks = 0
        op.slash_pending = False
        # 闪避也是"持续至技能结束"的一类，出技能就掉回去。
        op.dodge_phys = 0.0
        op.dodge_arts = 0.0
        # 技能结束时的**自身**效果，两条都只在描述里写明，判据在 skill.py。
        if sk is not None:
            if sk.effects.self_stun:
                op.stun_timer = max(op.stun_timer, sk.effects.self_stun)
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {op.name} 技能结束，自身晕眩 "
                        f"{sk.effects.self_stun:g}s")
            if sk.effects.self_retreat:
                # `alive` 已被 OperatorUnit 覆写成「血量 > 0 且未退场」，
                # 所以这里只置标志，不去碰血条——退场不是阵亡。
                op.retreated = True
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {op.name} 技能结束，强制退出战场")
        if self.verbose and sk is not None:
            self.result.log.append(f"{t:7.1f}s  {op.name} 技能「{sk.name}」结束")

    # -------------------------------------------------------- 主循环

    def run(self, max_time: float = 600.0) -> BattleResult:
        dt = 1.0 / self.fps
        t = 0.0
        res = self.result
        pending = sorted(self.deployments, key=lambda d: d.time)

        # 天赋「编入队伍后额外获得初始部署费用」——开局一次性结算。
        # 必须在循环之前：它加的是**初始**费用，不是部署那一刻的返费，
        # 早 2 点费就意味着第一个干员能早 2 秒落地。
        for d in pending:
            bonus = squad_cost_bonus(d.talents)
            if bonus:
                self.cost = min(self.max_cost, self.cost + bonus)
                if self.verbose:
                    res.log.append(f"{0.0:7.1f}s  {d.operator.name} 天赋："
                                   f"初始费用 +{bonus:g}")

        while t < max_time:
            self._t = t
            # 1. 部署
            while pending and pending[0].time <= t:
                self._do_deploy(pending.pop(0), t)
            for use in [s for s in self.skill_uses if abs(s.time - t) < dt / 2]:
                op = self._alive_op_at(use.position)
                if op is not None:
                    op.skill_request = True
            for rt, cell in [r for r in self.retreats if abs(r[0] - t) < dt / 2]:
                op = self._alive_op_at(cell)
                if op is not None:
                    op.hp = 0
                    for e in list(op.blocking):
                        e.blocked_by = None
                    op.blocking.clear()

            # 2. 出怪
            while (self._spawn_cursor < len(self._spawns)
                   and self._spawns[self._spawn_cursor][0] <= t):
                st, sp = self._spawns[self._spawn_cursor]
                e = self._spawn(sp.enemy_id, sp.level, sp.route_index, st)
                self.enemies.append(e)
                if self.verbose:
                    res.log.append(f"{t:7.1f}s  出现 {e.name}")
                self._spawn_cursor += 1

            # 3. 推进（等重生的不算活人，不推路）
            #    【停顿】与**攻击动作**的计时器在这里统一减一次：`advance()`
            #    在它们非零时直接返回，把递减写在里面就会永远减不动。
            #    远程敌人**不会因为锁到目标就停止推进**——它只在攻击动作
            #    期间原地停一下（`attack_pause`），动作一结束继续走。
            for e in self.enemies:
                if e.sluggish_timer > 0:
                    e.sluggish_timer = max(0.0, e.sluggish_timer - dt)
                if e.idle_timer > 0:
                    e.idle_timer = max(0.0, e.idle_timer - dt)
                if e.disarm_timer > 0:
                    e.disarm_timer = max(0.0, e.disarm_timer - dt)
                if e.attack_pause > 0:
                    e.attack_pause = max(0.0, e.attack_pause - dt)
                if e.alive and not e.leaked and not e.pending_reborn:
                    e.advance(dt, self.speed_scale)

            # 3.3 BOSS 换弱点形态（时间读法：首次在 initCooldown，之后每 cooldown）
            if (self.boss_mode_switch == "time" and self.mode_skill
                    and self._mode_next is not None and t >= self._mode_next):
                self._switch_boss_mode(t)
                self._mode_next = t + float(self.mode_skill.get("cd") or 0.0)

            # 3.4 重生结算（BOSS「死志的凝结」死一次会满血归来）
            self._reborn_tick(t)

            # 3.5 天赋：积雪（要在推进之后判"踏入了哪一格"，下一帧的减速才生效）
            self._snow_tick(dt, t)
            self._qi_tick(dt, t)

            # 3.6 P3R：刷新倒地 → 全场总攻击装置
            self._p3r_tick(dt, t)

            # 3.7 关卡环境机制：田地/病害值（怀黍离）
            self._environment_tick(dt, t)

            # 4. 阻挡
            self._update_blocking()

            # 5. 技能（要排在我方出手之前：刚攒满技力的那一帧得算数）
            self._skill_tick(dt, t)

            # 5.4 全场光环（青色怒火）：数值随光环主人的技能状态变，所以必须排在
            # 技能之后——本帧刚开的技能，本帧就吃到加倍，不然会晚一帧。
            if self.team_auras:
                self._refresh_auras()

            # 5.5 增益治疗光环（放在技能之后：本帧刚上场的干员也能吃到）
            if self.regen_auras:
                rng = self._range_of
                # 「进入」的两种读法跟着 heal_mode 一起切：`target` 是严格档
                strict = self.heal_mode == "target"
                for aura in self.regen_auras:
                    aura.tick(dt, self.operators, rng, strict=strict)

            # 记阵亡时刻（技能结算之后、出手之前没人会再死）
            for o in self.operators:
                if not o.alive and o.death_time < 0:
                    o.death_time = t

            # 6. 我方出手
            self._operators_attack(dt, t)

            # 7. 敌方出手
            self._enemies_attack(dt, t)

            # 7.5 敌人侧关卡机制（怀黍离）：移速增益的计时与解除、明识形态的
            #     清水判定与标记退场、以及**被击倒之后**那批一次性效果。
            #     排在两个出手之后：这一帧谁的出手把谁打倒了，这里就看得到。
            self._enemy_mech_tick(dt, t)

            # 8. 结算
            self._resolve(t)
            if self.life <= 0:
                res.won = False
                break
            if self._spawn_cursor >= len(self._spawns) and not any(
                    (e.alive and not e.leaked) or e.pending_reborn
                    for e in self.enemies):
                res.won = True
                break

            # 费用回复
            self._cost_timer += dt
            if self._cost_timer >= self.cost_time:
                self._cost_timer -= self.cost_time
                self.cost = min(self.max_cost, self.cost + 1.0)

            t += dt

        res.elapsed = t
        res.life = self.life
        res.kills = sum(1 for e in self.enemies
                        if not e.alive and not e.leaked and not e.pending_reborn)
        res.leaks = sum(1 for e in self.enemies if e.leaked)
        res.deployed = len(self.operators)
        # 「强制退场」（阿米娅技3 奇美拉）不是阵亡，分开数
        res.operator_deaths = sum(1 for o in self.operators
                                  if not o.alive and not o.retreated)
        if self.verbose:
            for o in self.operators:
                if not o.alive:
                    self.result.log.append(
                        f"{o.death_time:7.1f}s  {o.name} 阵亡"
                        f"（承受 {o.damage_taken:,.0f} 伤害）")
        return res

    # -------------------------------------------------------- 各阶段

    def _do_deploy(self, d: Deployment, t: float) -> None:
        op = d.operator
        op.position = d.position
        op.direction = d.direction
        op.auto_skill = d.auto_skill
        op.talents = list(d.talents or [])
        self._attach_skill(op, d)
        self.operators.append(op)

        # 部署瞬间的一次性环境伤害：`first_basic_damage + 实际 × first_damage_ratio`。
        # 它**额外于**每秒结算，不是它的第一次——原文两句分开写
        # （「部署时立刻受到 …」与「每秒受到 …」），加起来才是落地那一秒的总量。
        # 病害值为 0 时 `deploy_damage` 返回 0，落进干净田地的干员不吃这下。
        if self.farmland is not None:
            hurt = self.farmland.deploy_damage(*d.position)
            if hurt > 0:
                op.take(hurt)
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {op.name} 落于有病害的田地，"
                        f"额外受到环境伤害 {hurt:g}")
        self.cost = max(0.0, self.cost - op.deploy_cost)
        # 天赋：积雪
        snow = find_snow(op.talents)
        if snow is not None:
            self.snow_fields.append(SnowField(
                owner=op.name,
                interval=snow.value("interval", 10.0),
                max_layers=int(snow.value("max_cast_cnt", 5)),
                slow_per_layer=abs(snow.value("move_speed", 0.0)),
                magic_scale=snow.value("talent_magic_scale", 0.0),
                operator=op,
            ))
        # 天赋：增益治疗光环（「友方进入攻击范围时每秒回复生命值」）
        regen = find_regen(op.talents)
        if regen is not None:
            self.regen_auras.append(RegenAura(
                owner=op.name,
                hp_per_sec=regen.value("hp_recovery_per_sec", 0.0),
                duration=regen.value("buff_duration", 0.0),
                operator=op,
            ))
        # 天赋：情绪吸收（每次出手 / 每次击杀额外回技力）。落到干员身上，
        # 由出手与击杀两处结算——它**叠加**在技能的 sp_type 之上，不是替代。
        spa = find_sp_on_action(op.talents)
        if spa is not None:
            op.sp_per_attack_talent = spa.per_attack
            op.sp_per_kill_talent = spa.per_kill
        # 天赋：全场光环（「青色怒火」——全场友方攻防提升，主人开技能时加倍）
        aura = find_team_aura(op.talents)
        if aura is not None:
            self.team_auras.append(TeamAura(
                owner=op.name,
                atk_pct=aura.value("atk", 0.0),
                def_pct=aura.value("def", 0.0),
                operator=op,
            ))
            self._refresh_auras()
        if self.verbose:
            sk = f" 带技能「{op.skill.name}」" if op.skill is not None else ""
            tal = "、".join(f"「{x.name}」" for x in op.talents)
            tal = f" 天赋 {tal}" if tal else ""
            self.result.log.append(
                f"{t:7.1f}s  部署 {op.name} 于 {d.position} 朝 {d.direction}{sk}{tal}")

    def _refresh_auras(self) -> None:
        """把全场光环的当前数值刷到每个干员身上。

        每帧做一次，因为「光环主人开技能期间效果加倍」是随时间变的。
        多个光环**相加**（目前只有「青色怒火」一个来源）。
        """
        atk = def_ = 0.0
        for a in self.team_auras:
            x, y = a.current()
            atk += x
            def_ += y
        for op in self.operators:
            op.aura_atk_pct = atk
            op.aura_def_pct = def_

    def _update_blocking(self) -> None:
        """每帧重算阻挡关系。

        ⚠️ 这里写成**就地展开**不是为了压行数。本函数一场 1-7 要跑 4111 次、
        每次扫 41 个敌人，而 `e.alive` / `op.alive` 是 property、
        `can_block` / `is_at` 是小方法——**派发开销比它们做的事还贵**
        （实测 property 访问约 80 ns，平属性读约 18 ns，整场这类调用上百万次）。
        展开后本函数 8.61 µs/帧 vs 原版 14.53 µs/帧。

        **为什么不改成「摊平成列表再写回」**：实测更慢——搬运 9.9 µs/帧
        加上算法与写回 11.6 µs/帧，合计 20.8 µs，反而比原版的 14.53 µs 还差
        （端到端 0.873×）。收益全在**减少间接层**，与数据放在对象还是列表里无关。
        详见 `_proto/flat_probe.py` 与 README 的「性能与并行」节。

        语义必须与展开前的写法逐条对齐，改动前请核对：
        * `op.alive` = `hp > 0 and not retreated`（`OperatorUnit` 覆写过，
          撤退时满血，只看血量会把已退场的人算成还在）
        * `op.can_block(e)` = 非飞行 且 `block_cnt > 0` 且有空位
        * `e.is_at(op.position)` = 距离 ≤ `POSITION_TOL`，此处改用平方比较省掉
          开方（`dx*dx+dy*dy <= POSITION_TOL2`）；容差不是判据边界，浮点上
          等价，实测三关基线逐字一致
        """
        ops = self.operators
        for op in ops:
            blocking = op.blocking
            if blocking:
                op.blocking = [e for e in blocking
                               if e.hp > 0 and e.blocked_by is op]
        for e in self.enemies:
            # 离场传送中的敌人不在地图上，不占阻挡位
            # 【倒地】不可阻挡；飞行单位任何地面干员都挡不住
            if (e.hp <= 0 or e.leaked or e.off_map or e.down
                    or e.blocked_by is not None or e.is_flying):
                continue
            ex, ey = e.position
            for op in ops:
                if op.hp <= 0 or op.retreated:
                    continue
                cap = op.block_cnt
                if cap == 0 or len(op.blocking) >= cap:
                    continue
                ox, oy = op.position
                dx = ex - ox
                dy = ey - oy
                if dx * dx + dy * dy <= POSITION_TOL2:
                    e.blocked_by = op
                    op.blocking.append(e)
                    break
        for e in self.enemies:
            b = e.blocked_by
            if b is not None and (b.hp <= 0 or b.retreated):
                e.blocked_by = None

    def _pick_targets(self, op: OperatorUnit, cells: set, n: int = 1) -> list[EnemyUnit]:
        """目标选择：先打自己挡住的，再打离防守点最近的。

        返回最多 `n` 个——`n > 1` 对应技能里的「同时攻击 N 个目标」。

        与 `_update_blocking` 同理，`e.alive` 这类 property 在此就地展开
        （一场 1-7 调 6359 次、每次扫 41 个敌人）。`EnemyUnit` 的 `alive`
        就是 `hp > 0`，没有覆写。
        """
        out: list[EnemyUnit] = []
        for e in op.blocking:
            if e.hp > 0 and not e.leaked and e not in out:
                out.append(e)
                if len(out) >= n:
                    return out
        rest = []
        for e in self.enemies:
            if e.hp <= 0 or e.leaked or e.off_map or e in out:
                continue
            if (int(round(e.position[0])), int(round(e.position[1]))) in cells:
                rest.append(e)
        rest.sort(key=lambda e: -e.progress)
        for e in rest:
            out.append(e)
            if len(out) >= n:
                break
        return out

    def _pick_target(self, op: OperatorUnit, cells: set) -> EnemyUnit | None:
        """只取一个目标（保留旧接口）。"""
        got = self._pick_targets(op, cells, 1)
        return got[0] if got else None

    def _switch_boss_mode(self, t: float) -> None:
        """BOSS 换弱点形态，并把 `Skill_Revelation` 的伴随状态挂上去。

        描述原文是「弱点：在**物理**和**法术**间切换」，黑板里没有写切换的
        触发条件，只有 `idle_duration 5` / `disarmed_duration 7` —— 即切换
        期间**待机 5 秒、缴械 7 秒**。这两条一并落地：待机不能动也不能打，
        缴械不能打但能走。
        """
        self.boss_mode = "Mode_B" if self.boss_mode == "Mode_A" else "Mode_A"
        self.mode_switches.append((t, self.boss_mode))
        idle = float((self.mode_skill or {}).get("idle") or 0.0)
        disarm = float((self.mode_skill or {}).get("disarm") or 0.0)
        for e in self.enemies:
            if not e.alive or not e.modes:
                continue
            e.affinity = dict(e.modes.get(self.boss_mode) or e.affinity)
            e.idle_timer = max(e.idle_timer, idle)
            e.disarm_timer = max(e.disarm_timer, disarm)
        if self.verbose:
            print(f"    {t:7.1f}s  BOSS 弱点切换 → {self.boss_mode}"
                  f"（待机 {idle:g}s / 缴械 {disarm:g}s）")

    def _pick_heals(self, op: OperatorUnit, cells: set,
                    enemy_targets: list[EnemyUnit], n: int = 1) -> list[OperatorUnit]:
        """治疗目标：攻击范围内**血量比例最低**的友方（游戏口径）。

        `heal_mode == "target"` 时收窄成"被打中的敌人紧邻 8 格以内"，
        对应技能原文里的"目标周围"。没有敌人目标时，严格读法就治不了人
        ——这是它和宽松读法的实质差别，不是实现细节。
        """
        pool = [o for o in self.operators if o.alive and o.hp < o.max_hp]
        if self.heal_mode == "target":
            if not enemy_targets:
                return []
            near = set()
            for e in enemy_targets:
                ex, ey = int(round(e.position[0])), int(round(e.position[1]))
                for dx in (-1, 0, 1):
                    for dy in (-1, 0, 1):
                        near.add((ex + dx, ey + dy))
            cells = cells & near
        pool = [o for o in pool
                if (int(round(o.position[0])), int(round(o.position[1]))) in cells]
        pool.sort(key=lambda o: (o.hp_ratio, o.hp))
        return pool[:n]

    def _adaptive_damage(self, power: float, scale: float, target: EnemyUnit,
                         ignore_defense: float, ignore_res: float = 0.0):
        """「弱点伤害」：物理与法术各算一遍，取最终伤害更高的那一系。

        赤刃明霄陈的天赋「形意洞照」写「攻击变为弱点伤害」，用户口径是
        「会切换成伤害更高的伤害类型」。这里把**过相性之后**的值拿来比，
        所以免疫（倍率 0）的那一系不会胜出——等于免疫对它无效。
        返回 `(DamageType, DamageResult)`，交给 `_damage_enemy` 正常结算。
        """
        best = None
        for dt in (DamageType.PHYSICAL, DamageType.MAGIC):
            d = resolve_damage(power, damage_type=dt, scale=scale,
                               defense=target.defense, res=target.res,
                               ignore_defense=ignore_defense,
                               ignore_res=ignore_res)
            slot = damage_slot(dt)
            aff = target.affinity.get(slot) if slot else None
            val = d.final * affinity_multiplier(
                aff, immune_blocks_damage=self.affinity_blocks_damage)
            if best is None or val > best[0]:
                best = (val, dt, d)
        return best[1], best[2]

    def _operators_attack(self, dt: float, t: float) -> None:
        for op in self.operators:
            if not op.alive:
                continue
            # 技能结束后自身晕眩期间不出手（阿米娅技2 那类的代价）
            if op.stun_timer > 0:
                continue
            cells = self._range_of(op)
            op.attack_timer += dt
            if op.attack_timer < op.current_interval():
                continue

            eff = op.effects
            # 这一击打不打伤害？医疗干员的平A是治疗，但技能可以把攻击
            # **改成**打伤害（凯尔希·思衡托技2："攻击变为射出医疗单元"），
            # 判据是技能自己写了攻击倍率。
            skill_scale = eff.atk_scale if eff is not None else 1.0
            deals = (not op.heals) or abs(skill_scale - 1.0) > 1e-9
            # 这一击治不治疗？技能写了 heal_scale 就治；此外医疗干员
            # 只要这一击没被改成伤害，平A本身也是治疗。
            heal_scale = eff.heal_scale if eff is not None else None
            if heal_scale is None and op.heals and not deals:
                heal_scale = 1.0

            targets = self._pick_targets(op, cells, op.current_max_target()) if deals else []
            heal_targets = self._pick_heals(op, cells, targets) if heal_scale else []
            if not targets and not heal_targets:
                continue
            op.attack_timer = 0.0
            op.hits += 1

            scale = skill_scale
            hits = eff.hit_count if eff is not None else 1
            # 「最后一击系数加倍」的末击倍率，没有就是 None。判据在
            # `skill._wants_final_double`（读描述）——**不按 `atk_scale_2`
            # 键名认**，那个键在空弦/雪猎/丰川祥子等人身上另有含义。
            final_scale = eff.final_hit_scale if eff is not None else None
            pierce_pct = eff.buffs.get("def_penetrate", 0.0) if eff is not None else 0.0
            pierce_fix = eff.buffs.get("def_penetrate_fixed", 0.0) if eff is not None else 0.0
            # 法术穿透与物理穿透同构：`magic_resist_penetrate(_fixed)` 已由
            # skill.BUFF_KEYS 归成 `res_penetrate(_fixed)`。此前这两个键是
            # **解析了但从不结算**的死键——damage.resolve_damage 一直有
            # `ignore_res` 参数，sim 却一次也没传过。
            # 标本：圣聆初雪技3 的 `magic_resist_penetrate_fixed 10`。
            res_pierce_pct = eff.buffs.get("res_penetrate", 0.0) if eff is not None else 0.0
            res_pierce_fix = eff.buffs.get("res_penetrate_fixed", 0.0) if eff is not None else 0.0
            dmg_type = op.active_attack_type()
            # 「末击起为真实」类（阿米娅技2 影霄·绝影）：**这一次出手本身就是
            # 那 10 连斩**，前 9 击仍是法术，只有第 10 击转真实；打完置
            # `slash_pending=False`，此后技能期内的普攻才整体走
            # `skill_attack_type`（也是 "TRUE"）。博士 2026-09-17 裁定。
            slashing = bool(eff is not None and eff.true_from_final_hit
                            and op.slash_pending)
            slash_type = op.attack_type
            power = op.current_atk()

            for target in targets:
                ign = pierce_fix + target.defense * pierce_pct
                ign_res = res_pierce_fix + target.res * res_pierce_pct
                for i in range(hits):
                    if not target.alive:
                        break
                    # 末击（第 `hits` 次）改用 `final_scale`。影霄·绝影的
                    # 10 次斩击里只有最后那一次系数加倍。
                    hit_scale = (final_scale
                                 if (final_scale is not None and i == hits - 1)
                                 else scale)
                    hit_type = dmg_type
                    if slashing:
                        hit_type = ("TRUE" if i == hits - 1 else slash_type)
                    dmg = resolve_damage(
                        power, damage_type=hit_type, scale=hit_scale,
                        defense=target.defense, res=target.res,
                        ignore_defense=ign,
                        ignore_res=ign_res,
                    )
                    used_type = hit_type
                    if op.weakness_damage:
                        # 「弱点伤害」：两系都算、取更高的一系（用户口径）。
                        # 免疫侧被相性压成 0，故它会自动躲开当前被免疫的类型。
                        used_type, dmg = self._adaptive_damage(
                            power, hit_scale, target, ign, ign_res)
                    # `source=op` 是给「祟」明识形态的**标记**用的：
                    # 它要记住"谁打过我"，那些干员退场时田地会被污染。
                    dealt = self._damage_enemy(target, dmg.final, t, used_type,
                                               source=op)
                    # 技能附带的【停顿】：不能移动，但照样能开火
                    if eff is not None and eff.control.get("sluggish"):
                        target.sluggish_timer = max(
                            target.sluggish_timer, eff.control["sluggish"])
                    if not target.alive:
                        # 击杀叠层（阿米娅技2 影霄·绝影）：技能期间每击败一个
                        # 敌人 +1 层，上限 `kill_max_stack`，**只在技能期间**叠。
                        # 清零在 `_deactivate`——「持续至技能结束」（博士裁定 +
                        # 游戏内注释）。放在目标循环**内部**，一次出手打死两个
                        # 就叠两层。
                        if (op.skill_active and eff is not None
                                and eff.kill_max_stack):
                            op.kill_stacks = min(eff.kill_max_stack,
                                                 op.kill_stacks + 1)
                        # 天赋「情绪吸收」：消灭敌人额外获得技力。放在目标循环
                        # **内部**而不是出手后统一结算——一次出手打死两个就回两份。
                        if op.sp_per_kill_talent and not op.skill_active \
                                and op.skill is not None:
                            op.sp = min(op.skill.sp_cost,
                                        op.sp + op.sp_per_kill_talent)
                        if self.verbose:
                            self.result.log.append(
                                f"{t:7.1f}s  {op.name} 击杀 {target.name}")

            # 斩击打完了：此后技能期内的普攻整体走 `skill_attack_type`
            if slashing:
                op.slash_pending = False

            # 治疗量 = 当前攻击力 × 治疗倍率（医疗干员平A的倍率是 1）
            for ally in heal_targets:
                got = ally.heal(power * heal_scale)
                op.healing_done += got
                if self.verbose and got > 0:
                    self.result.log.append(
                        f"{t:7.1f}s  {op.name} 治疗 {ally.name} +{got:,.0f}"
                        f"（{ally.hp:,.0f}/{ally.max_hp:,.0f}）")

            # 攻击回复的技力按"出手"算，不按打中几个目标算
            if op.skill is not None and not op.skill.is_passive:
                gain = op.skill.sp_per_attack()
                if gain and not op.skill_active:
                    op.sp = min(op.skill.sp_cost, op.sp + gain)
            # 天赋「情绪吸收」：每次出手**再额外**回一份，与技能的 sp_type 无关。
            # 阿米娅技1「战术咏唱·γ型」是自动回复型，`sp_per_attack()` 返回 0，
            # 若只在上面那一支里加，这条天赋会被整条漏掉。
            #
            # 技能开启期间不回：与上面 `sp_per_attack` 的口径一致，也是游戏里
            # 「技能期间 SP 条不涨」的常规。天赋正文没写这一条，属**未证实假设**，
            # 已记进 docs/uncertainties.md 待博士裁定。
            if op.sp_per_attack_talent and not op.skill_active \
                    and op.skill is not None:
                op.sp = min(op.skill.sp_cost, op.sp + op.sp_per_attack_talent)
            # 弹药类：每出手一次耗一发
            if op.skill_active and op.skill is not None \
                    and op.skill.duration_type == "AMMO" and op.ammo_left > 0:
                op.ammo_left -= 1

    def _enemy_target(self, e: EnemyUnit) -> "OperatorUnit | None":
        """敌人当前该打谁。

        规则，按优先级：

        1. **挡住自己的干员**——被阻挡就是最近，也最优先；
        2. 射程（`rangeRadius`）内的干员里，**最后部署的那一个**。

        第 2 条不是「距离最近」。这一点与干员侧正好相反：我方按「离目标点
        最近」挑敌人，敌方按「最后下场」挑干员。所以想把火力从脆皮身上引开，
        必须**后下**那个肉盾——先下无效，先下的反而会被顶掉。

        `self.operators` 的列表顺序就是部署顺序（动作按时刻顺序执行），
        所以取最后一个命中者即可。

        未建模：嘲讽等级（星熊/塞雷娅这类「嘲讽+1」的特性与技能）。
        它们在本关都不参与到解法里，故暂不影响结论。
        """
        if e.blocked_by is not None and e.blocked_by.alive:
            return e.blocked_by
        if (not self.ranged_enemies or e.apply_way != "RANGED"
                or e.attack_range <= 0 or e.atk <= 0):
            return None
        picked: OperatorUnit | None = None
        for op in self.operators:            # 列表顺序 = 部署顺序，越靠后越晚
            if not op.alive:
                continue
            if math.dist(e.position, op.position) <= e.attack_range:
                picked = op
        return picked

    def _enemies_attack(self, dt: float, t: float) -> None:
        """敌方出手。每帧扫全部敌人，故 `alive` / `pending_reborn` 就地展开。"""
        for e in self.enemies:
            if e.hp <= 0 or e.leaked or e.off_map or e.reborn_at >= 0.0:
                continue
            if e.frozen or e.down:
                # 冻结 / 倒地的敌人不能攻击；计时器也不该偷偷攒着
                continue
            if e.idle_timer > 0 or e.disarm_timer > 0:
                # 【待机】/【缴械】期间不能出手（待机还额外不能移动，见 advance）
                continue
            op = self._enemy_target(e)
            if op is None or op.hp <= 0 or op.retreated:
                continue
            e.attack_timer += dt
            if e.attack_timer < e.attack_interval:
                continue
            e.attack_timer = 0.0
            e.hits += 1
            # 出手要占用一段攻击动作时间，这期间它不走路（但**不会**因此
            # 停在原地不走完整条路线——动作一结束就继续推进）。
            e.attack_pause = max(e.attack_pause, self.enemy_windup)
            dealt = 0.0
            # 明识形态的普攻是 **2 连击**（原文「自身普通攻击变为2连击」）。
            # 逐段结算：两段的防御/法抗各减一次。把 atk 乘 2 再打一次会
            # 少减一次防御，对高防目标能差出成倍的伤害。
            for _seg in range(max(1, int(getattr(e, "attack_times", 1) or 1))):
                dealt += op.take(resolve_damage(
                    e.atk, damage_type=e.attack_type,
                    defense=op.current_defense(), res=op.current_res(),
                    # 闪避走期望值法：把最终伤害乘 `(1 − 闪避率)`，不掷骰。
                    # 掷骰会让同一份作业每次跑出不同结果，搜索与回归都不可复现。
                    dodge_phys=op.dodge_phys, dodge_arts=op.dodge_arts,
                ).final)
                if op.hp <= 0 or op.retreated:
                    break
            # 【怀黍离】重生后的普攻附加伤害（瘴 / 鄙瘴）：
            # 「普通攻击附加攻击力(10×充能层数)%的无途径法术普通伤害」。
            # 「无途径」= 走后**不受攻击方式/途径影响**，故这里独立结算：
            # 攻击力 × 比例 × 层数，按法术算（吃目标法抗），并同样吃闪避期望。
            # ⚠ 它是**附加**在普攻上的，不是替代——上面那次已经结算完了。
            if e.reborn_charge and e.reborn_damage_magic:
                bonus = e.atk * e.reborn_damage_magic * e.reborn_charge
                if bonus > 0.0:
                    dealt += op.take(resolve_damage(
                        bonus, damage_type="ARTS",
                        defense=0.0, res=op.current_res(),
                        dodge_phys=op.dodge_phys, dodge_arts=op.dodge_arts,
                    ).final)
            # 受击回复的技力
            if dealt > 0 and op.skill is not None and not op.skill.is_passive \
                    and not op.skill_active:
                gain = op.skill.sp_per_hit()
                if gain:
                    op.sp = min(op.skill.sp_cost, op.sp + gain)

    def _enemy_mech_tick(self, dt: float, t: float) -> None:
        """敌人侧关卡机制（怀黍离）：加速计时、明识形态、被击倒后的效果。

        四件事都在这里，因为它们都**不属于任何一帧的伤害结算**，而是
        「状态随时间走」或「一次性的收尾」：

        1. `SpeedUp.` 的移速增益：倒计时、**被阻挡立刻解除**、以及解除后
           把 `haste_multiplier` 收回 1.0。
        2. `PassiveM2.` 明识形态的**清水判定**（水田中病害值=0，或处于清澈
           泵站生效范围内 → 防御/法抗再降、并失去移速加成）。
        3. `PassiveM2.` 的**标记退场**：被标记的干员退场时，若自身未被阻挡，
           半径 1.0 内田地病害值 +`pm2_mark_pollut`。
        4. `Passive.` / `DeathPassive.`：被击倒时污染田地、给予我方可部署装置。

        ⚠ 第 4 条只认「**被击倒**」：漏怪（`leaked`）不算、传送离场
        （`off_map`）不算、等重生的（`pending_reborn`）也不算——原文一律
        写「被击倒时」。
        """
        for e in self.enemies:
            # ---- 1. 加速：被阻挡立刻解除；否则倒计时
            if e.haste_multiplier > 1.0:
                if e.blocked_by is not None:
                    e.speedup_timer = 0.0
                    e.haste_multiplier = 1.0
                    if self.verbose:
                        self.result.log.append(
                            f"{t:7.1f}s  {e.name} 被阻挡 → 移速增益解除")
                else:
                    e.speedup_timer -= dt
                    if e.speedup_timer <= 0.0:
                        e.speedup_timer = 0.0
                        e.haste_multiplier = 1.0
            # ---- 2./3. 明识形态
            if e.pm2_active and e.hp > 0 and not e.off_map:
                self._pm2_tick(e, t)
            # ---- 4. 被击倒后的效果
            if (e.hp <= 0 and e.reborn_at < 0.0 and not e.leaked
                    and not e.off_map and not e.death_done):
                e.death_done = True
                self._on_enemy_death(e, t)

    def _on_enemy_death(self, e: EnemyUnit, t: float) -> None:
        """被击倒之后的一次性效果：田地污染与「给予可部署装置」。

        * `Passive.`（秽 / 除秽 / 肮 / 厌肮）：令**阻挡自身的单位(被阻挡时)/
          自身(未被阻挡时)** 半径 1.0 范围内的田地地块病害值 +N。
        * `DeathPassive.`（田鼷飞贼 / 田鼷大盗）：死亡爆炸，予我方可部署装置
          （`token_key` 的装置 × `death_cnt`）。
          ⚠ **模拟器目前没有"部署装置"这一层**——部署计划只收干员，装置全是
          关卡预先摆好的。所以这里只把账记下来（`res.device_tokens`），
          不改变任何一次结算。这不是接了一半，是如实记账：
          `activity.py` 里 `DeathPassive.` 因此仍标 `todo`。
        """
        if e.passive_pollut > 0.0:
            self._pollute_around(e, t, e.passive_pollut,
                                 e.passive_radius or 1.0, "被击倒")
        if e.death_token and e.death_cnt:
            self.result.device_tokens.append((t, e.death_token, e.death_cnt))
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 被击倒 → 获得 {e.death_cnt} 个 "
                    f"{e.death_token}（模拟器没有装置部署层，仅记账）")

    def _pm2_tick(self, e: EnemyUnit, t: float) -> None:
        """明识形态逐帧要判的两件事：**清水**与**标记退场**。

        清水（原文）：「位于水田中，且所在地块病害值=0，或处于**身后一格
        水田为清澈状态的泵站**生效范围内时，防御力-15%、法术抗性-30、
        失去移动速度加成」。

        两读合一的写法：把「清澈泵站生效范围」也算出来，落在里面同样算清水。
        泵站自身那一格必须是田地且病害值=0（原文「身后一格水田为清澈状态」），
        它生效的前方格数按 `PUMP_RANGE`（水源地上有我方单位时 +2）。
        """
        clean = False
        fs = self.farmland
        if fs is not None:
            cell = e.cell()
            idx = fs._index.get(cell)
            if idx is not None and fs.actual.get(cell, 0.0) <= 0.0:
                clean = True
            elif self._devices:
                clean = self._in_clear_pump(e, cell)
        if clean != e.pm2_clean:
            e.pm2_clean = clean
            # 属性改写**只算一次**（`pm2_applied`），清水是叠在其上的可开关项：
            # 进去再收回去，得按同一套公式重算，不能反复乘。
            e.defense = e.reborn_def_base * (
                1.0 + e.pm2_def + (e.pm2_clean_def if clean else 0.0))
            e.haste_multiplier = 1.0 + (0.0 if clean else e.pm2_move)
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 明识形态："
                    f"{'进入清澈水域（防御/法抗降低、失去移速加成）' if clean else '离开清澈水域'}"
                    f"  防御 {e.defense:,.0f}")

        # 标记退场：被标记的干员退场（阵亡或撤退）时，若自身未被阻挡，
        # 半径 1.0 内田地病害值 +N。
        # ⚠ 圆心取**祟自己**脚下那一格：原文的「自身」是被标记者的施加者。
        #   另一种读法是以退场的那个干员为中心（见 docs/uncertainties.md）。
        if e.marked_ops:
            gone = [k for k in e.marked_ops
                    if not any(id(o) == k and o.alive and not o.retreated
                               for o in self.operators)]
            for k in gone:
                e.marked_ops.discard(k)
                if e.blocked_by is None and e.pm2_mark_pollut > 0.0:
                    self._pollute_around(e, t, e.pm2_mark_pollut, 1.0, "标记退场")

    def _in_clear_pump(self, e: EnemyUnit, cell: tuple[int, int]) -> bool:
        """敌人脚下是否落在**清澈泵站**的生效范围内。

        泵站要「清澈」得满足原文那一条：**身后一格为田地、且该格病害值=0**。
        生效范围取泵站**前方的 `span` 格**（`span = PUMP_RANGE`，
        水源地上有我方单位时 +2）。这里取**整段前方格**而不是"泵水实际打到
        的那一格"：原文说的是「处于泵站生效范围内」，指的是那圈范围，
        不是它这一秒把水打到了哪儿——后者会随田地几何逐秒变。
        """
        from .devices import DIRECTIONS, PUMP_KEY, behind_of
        from .environment import PUMP_RANGE, PUMP_RANGE_BONUS
        fs = self.farmland
        for d in self._devices:
            if d.key != PUMP_KEY:
                continue
            src = behind_of(d.cell, d.direction)
            if src is None or fs._index.get(src) is None:
                continue
            if fs.actual.get(src, 0.0) > 0.0:
                continue                      # 水源地本身被污染 → 不是清澈泵站
            dv = DIRECTIONS.get((d.direction or "").upper())
            if dv is None:
                continue
            span = PUMP_RANGE + (PUMP_RANGE_BONUS if self._ally_on(src) else 0)
            for k in range(1, span + 1):
                if (d.cell[0] + dv[0] * k, d.cell[1] + dv[1] * k) == cell:
                    return True
        return False

    def _ally_on(self, cell: tuple[int, int]) -> bool:
        return any(op.alive and op.position == cell for op in self.operators)

    def _enter_pm2(self, e: EnemyUnit, t: float) -> None:
        """「祟」重生归来 → **明识形态**。

        原文：「重生后，自身攻击力-60%、防御力-70%、法术抗性-30、移动速度
        +200%、普通攻击变为2连击且可进行远程攻击；获得 5 秒无敌」。

        ⚠ 属性改写**只做一次**（`pm2_applied`）。这个函数会在归来那一帧
        被调一次，但若哪天它被逐帧调用，反复乘会让攻击力指数衰减——
        所以判据放在函数里，不放在调用点上。
        """
        e.pm2_active = True
        if not e.pm2_applied:
            e.pm2_applied = True
            e.atk *= 1.0 + e.pm2_atk
            e.defense *= 1.0 + e.pm2_def      # 清水项在 `_pm2_tick` 里加减
            e.res += e.pm2_res
            e.haste_multiplier = 1.0 + e.pm2_move
            e.attack_times = 2
            # 「可进行远程攻击」——**射程数据里没有**，故只在本来就有射程
            # （`rangeRadius > 0`）时才转远程，否则维持近战。
            # 凭空编一个射程会让「祟」隔着半个屏幕打人，那是编数据。
            if e.attack_range > 0.0:
                e.apply_way = "RANGED"
        if e.pm2_invincible > 0.0:
            e.invincible_until = t + e.pm2_invincible
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {e.name} 进入明识形态  攻击 {e.atk:,.0f} / "
                f"防御 {e.defense:,.0f} / 移速 ×{e.haste_multiplier:.1f}"
                f" / {e.attack_times} 连击 / 无敌 {e.pm2_invincible:g}s")

    def _reborn_tick(self, t: float) -> None:
        """重生结算 + 【怀黍离】重生期充能。

        BOSS「死志的凝结」的 `Reborn.reborn_duration = 10` /
        `Reborn.max_hp_ratio = 1`：倒下 10 秒后**满血归来**——等于多一条命。
        在数据里它和普通敌人没有任何区别，只有把这条算上，
        「打完了没有」才是可信的。

        怀黍离的瘴 / 鄙瘴走另一套键（`Reborning.*`），除了重生还带**充能**：
        重生期间每 0.5s，若自身所在田地地块病害值 > 0，则降低该地块 10 点
        病害值并获得 1 层充能；重生后防御力 +(30×层数)%、普通攻击附加
        攻击力 (10×层数)% 的无途径法术普通伤害。

        ⚠ 充能**只在重生窗口里增长**（原文「重生期间每0.5s」），重生完成即定住。
        所以防御加成在归来那一刻按 `reborn_def_base` 重算一次即可，
        不必逐帧改 `defense`。
        """
        fs = self.farmland
        for e in self.enemies:
            if e.leaked:
                continue
            if e.pending_reborn:
                # ---- 召唤：重生期间按间隔在自己脚下召唤（「祟」）
                for i, (itv, cnt, key) in enumerate(e.reborn_summons):
                    if i >= len(e.reborn_summon_at):
                        break
                    while e.reborn_summon_at[i] >= 0.0 and t >= e.reborn_summon_at[i]:
                        if itv <= 0.0:
                            e.reborn_summon_at[i] = -1.0
                            break
                        e.reborn_summon_at[i] += itv
                        self._summon_at(key, cnt, e.cell(), t, e)
                # 充能：窗口内按 interval 逐个结算。用 while 而不是 if——
                # fps 高时不会漏，fps=1 的粗扫时又会一次补上欠下的所有拍。
                while e.reborn_charge_at >= 0.0 and t >= e.reborn_charge_at:
                    # 间隔非正就是「没有充能节拍」，先退出——否则
                    # `charge_at` 会原地踏步（或倒退），这个 while 永不收敛。
                    if e.reborn_interval <= 0.0:
                        break
                    e.reborn_charge_at += e.reborn_interval
                    # 原文把「降低病害值」与「获得1层充能」写在同一个条件里：
                    # 本格病害值 > 0 才**同时**发生两件事，否则一件都不发生。
                    # `drain_cell` 在 ≤0 时返回 0，正好当这个条件用。
                    moved = 0.0
                    if fs is not None:
                        # ⚠ 必须用 `e.cell()`（四舍五入到整数格）而不是
                        # `e.position`——后者是浮点坐标，而 `actual` 的键是
                        # **整数格**。传浮点进去不会报错，只是永远取不到，
                        # 于是充能永远是 0 层、整条机制静默失效。
                        moved = fs.drain_cell(*e.cell(), e.reborn_pollut)
                    if moved > 0.0:
                        e.reborn_charge += 1
                        if self.verbose:
                            self.result.log.append(
                                f"{t:7.1f}s  {e.name} 吸收病害 {moved:.0f} 点"
                                f"  充能 {e.reborn_charge} 层")
                    if e.reborn_interval <= 0.0:
                        break
                if t >= e.reborn_at:
                    e.reborn_at = -1.0
                    e.reborn_charge_at = -1.0
                    e.reborn_summon_at = [-1.0] * len(e.reborn_summons)
                    e.hp = e.max_hp * e.reborn_hp_ratio
                    # 重生后：防御力 +(def_add × 层数)%。从基准重算，
                    # 免得二次重生时把上一次的加成再乘一遍。
                    if e.reborn_charge and e.reborn_def_add:
                        e.defense = e.reborn_def_base * (
                            1.0 + e.reborn_def_add * e.reborn_charge)
                    e.blocked_by = None
                    if self.verbose:
                        extra = (f"  充能 {e.reborn_charge} 层"
                                 f"（防御 {e.defense:,.0f}）"
                                 if e.reborn_charge else "")
                        self.result.log.append(
                            f"{t:7.1f}s  {e.name} 重生  生命 {e.hp:,.0f}{extra}")
                    # 「祟」：归来的不是同一副样子——切明识形态
                    if e.pm2_atk or e.pm2_move or e.pm2_invincible:
                        self._enter_pm2(e, t)
            elif e.hp <= 0 and e.reborn_left > 0:
                e.reborn_left -= 1
                e.reborn_at = t + e.reborn_delay
                # 充能窗口与重生窗口同长：进来就排第一拍
                e.reborn_charge_at = (t + e.reborn_interval
                                      if e.reborn_interval > 0.0 else -1.0)
                # 召唤同样只在重生窗口里：进来就排第一拍
                e.reborn_summon_at = [t + itv for itv, _c, _k in e.reborn_summons]
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {e.name} 倒下，{e.reborn_delay:.0f} 秒后重生"
                        f"（还剩 {e.reborn_left} 次）")

    def _resolve(self, t: float) -> None:
        """收尾结算：击杀奖励费用与漏怪扣命。

        同样就地展开 `alive` / `pending_reborn`——本函数每帧跑一次、每次扫
        全部敌人，而这两个 property 加起来占了它自身耗时的大半。
        * `e.alive` = `hp > 0`
        * `e.pending_reborn` = `reborn_at >= 0.0`（倒下等重生，既不算活也不算死）
        """
        for e in self.enemies:
            # 击杀奖励费用（没办法车 +50）。漏掉的不算击杀，不给钱。
            if (e.hp <= 0 and e.reborn_at < 0.0 and not e.leaked
                    and e.kill_cost and not e.cost_awarded):
                e.cost_awarded = True
                self.cost += e.kill_cost
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  击倒 {e.name}  +{e.kill_cost} 费用")
            if e.hp > 0 and not e.leaked and not e.off_map and e.reached_end:
                e.leaked = True
                e.leak_time = t
                # lifePointReduce 可以是 0（没办法车），不能强行按 1 算
                self.life -= e.life_cost
                # **无条件**记账：验证器的"为什么失败"全靠这份明细，
                # 不能只在 verbose 下有（原先只有下面那行日志）。
                self.result.leak_events.append((t, e.name, e.life_cost))
                if self.verbose:
                    self.result.log.append(f"{t:7.1f}s  漏怪 {e.name}  剩余生命 {self.life}")
