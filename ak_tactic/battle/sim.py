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
from ..gamedata.enemy import PROSE_SUMMON_EDGES
from .damage import DamageType, resolve_damage
from .talents import (CLASS_AURA_TALENTS, FACTION_AURA_NAME, STUDENT_TEAM,
                      RegenAura, SnowField, TeamAura, find_blessing,
    find_ammo_covenant, find_bomb_radio, LATERANO_NATION,
                      RHODES_NATION, find_angel_blessing, find_class_aura, find_damage_block,
                      find_dot_on_hit,
                      find_limit_dispatch,
                      find_regen,
                      find_snow, find_sp_on_action, find_summon_allowance,
                      find_team_aura,
                      squad_cost_bonus)
from .p3r import BreakState, TotalAttackDevice, affinity_multiplier, damage_slot
from .summons import SummonDeployment, build_summon_unit
from .hammer import HAMMER_HITS, HAMMER_INTERVAL, read_hammer
from .talents import find_glider_mobility
from .traits import cross_cells, splash_tiles
from ..operator.summons import SummonBook
from . import displace
from .unit import POSITION_TOL, EnemyUnit, OperatorUnit, point_at

__all__ = ["BattleSimulator", "BattleResult", "Deployment", "SkillUse",
           "SummonDeployment"]

FPS = 30

#: 无限持续的技能用这个值当倒计时，省得每次都判 None
_INFINITE = float("inf")

# ------------------------------------------------------ 贯穿弹道（焰狐龙梓兰 技3）
# 这四个数**黑板里都没有**，出处是 prts.wiki「焰狐龙梓兰」页 `|备注=` 原文：
# 「其具有 10 格/秒（≈0.333 格/帧）的飞行速度与 0.5 的碰撞半径……持续存在
# 30 秒……从自身的弹道受击点（始终具有向北方向约 0.2323 格的偏移）向自身
# 正前方发射」。板上的 `max_dist`/`dist_interval` 管的是另一回事（最大飞行
# 距离与结算间隔），别混。
#: 弹道飞行速度（格/秒）。
_ARROW_SPEED = 10.0
#: 碰撞半径（格）。**判定按连续坐标的欧氏距离**，不是格子相等——
#: 半径 0.5 配上 0.25 的结算间隔，正好让一个质点敌人吃 4 次结算。
_ARROW_RADIUS = 0.5
#: 弹道存在时长（秒）。
_ARROW_LIFETIME = 30.0
#: 生成点相对自身的**向北**偏移（格）。MAA 口径 y 向下 ⇒ 北 = −y。
_ARROW_SPAWN_OFFSET = 0.2323
#: 首次开启动画与之后各开启动画的时长（秒）。由备注给的两个总时长
#: （3.67 / 3.0）**减去**那 1.5 秒蓄力（`wait_duration`）反推出来。
_ARROW_ANIM_FIRST = 2.17
_ARROW_ANIM_LATER = 1.5
#: 蓄力结束后到弹道真正出现之间的那约 3 帧（备注：≈0.1 秒）。
_ARROW_PROJECTILE_DELAY = 0.1

#: 「全场总攻击」装置的 characterKey。关卡 `predefines.tokenInsts` 里出现它就启用。
TOTAL_ATTACK_KEY = "trap_335_totalattack"

# ------------------------------------------------------------ 天桩链（怀黍离）
#
# 装置「天桩」→ 天桩-甲 → 天桩-乙 → 身上的天标，四跳里**只有一跳**是结构化字段：
#
# * 装置 → 甲：正文里的一句话（装置页技能「生成」：「登场时，在自身所在位置
#   以预设路径召唤一名天桩-甲」+ 机制「于所在地块的天桩-甲（或失控天桩-甲）
#   退场时死亡」）。装置自己的技能黑板**只有一个键**：
#   `sktok_dhdcr` 的 `branch_id = branch_dhdcr_1`，而 `branch_dhdcr_1`
#   在客户端数据里**只出现在 skill_table 里**——没有 branch → prefab 的映射表。
# * 甲 → 乙：**结构化**。`CheckAwake.enemy_dhdcr_trigger_summon.enemy_key`
#   点名 `enemy_1399_dhtb`（失控甲点名 `enemy_1399_dhtb_2`）。
# * 乙 → 天标：正文里的一句话（乙的天赋「攻击命中时，在目标所在地块中心
#   召唤1个[[身上的天标]]」），乙的 `talentBlackboard` 是**空的**。
#
# 所以下面两张表是"正文里那两跳"的落地。**值的唯一出处是
# `gamedata/enemy.py:PROSE_SUMMON_EDGES`**（盘点也读同一张表，两边不会走散），
# 这里只是按用途切一刀：装置那一条给 `PILE_CHILD`、敌人那两条给 `PILE_MARK`。
#
# ⚠ 2026-09-16 修正：**「装置 → 甲」这一跳根本不是正文跳**，是结构化字段——
# 装置 predefine 的 `overrideSkillBlackboard[branch_id]` → 关卡 `branches` →
# `extraRoutes`（见 `BattleSimulator._pile_spec`）。`PILE_CHILD` 因此降级为
# **退路**：只有在关卡里查不到那条支线时才用（本活动一个关卡都没走到）。
# 同理"没有任何一关用失控型"这句话是**错的**：`act31side_ex03` / `ex07` /
# `ex08` 三关的支线里写的正是 `enemy_1398_dhdcr_2`（失控天桩-甲），
# 03/04/07/tr01/tr02 五关写的是关卡本地的 `enemy_1398_dhdcr_b`。
#: 装置 key → 它召唤的甲的 key（**退路**，正常走 `_pile_spec` 的结构化查询）
PILE_CHILD = {
    k: v[0] for k, v in PROSE_SUMMON_EDGES.items() if k.startswith("trap_")
}
#: 乙的 key → 它命中时召唤的天标的 key（这一跳**仍然只能查表**：乙的黑板是空的）
PILE_MARK = {
    k: v[0] for k, v in PROSE_SUMMON_EDGES.items() if k.startswith("enemy_")
}
#: 甲激活后每损失一批生命，召唤的**延迟秒数**。原文是「1~1.5s 的随机延迟」，
#: 模拟器必须可复现（同一份作业每次跑出同一结果），故取中值 1.25s，不掷骰。
PILE_SUMMON_DELAY = 1.25
#: 监测 / 激活状态判定的**病害值满量程**：原文「每 1% 生命值对应 1 点病害值」，
#: 而病害值的量程是 0–100（见 `environment.MAX_POLLUT`），故除以 100。
PILE_POLLUT_FULL = 100.0
#: 天桩-乙登场时的自缚秒数（原文「登场时持有1秒自缚」）
PILE_SELF_BIND = 1.0

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
    #: 这份账是**额度**的来源：关卡开局的 `tokenCards[].initialCnt` 再加上这里
    #: 掉的，就是 `BattleSimulator.device_token_balance`（见 `_do_deploy_device`）。
    device_tokens: list[tuple[float, str, int]] = field(default_factory=list)
    #: 真放下去的**装置**：`(时刻, 装置 key, 格子)`。与干员/召唤物分开记。
    devices_deployed: list[tuple[float, str, tuple[int, int]]] = field(
        default_factory=list)
    #: **被拒收**的装置部署：`(时刻, 装置 key, 原因)`。理由三类：
    #: 额度不够（关卡给的 + 掉落的都花完了）/ 费用不够 / 那一格已有装置。
    device_deploy_rejected: list[tuple[float, str, str]] = field(
        default_factory=list)
    #: 实际放进场的召唤物个数。
    summons_deployed: int = 0
    #: **被拒收**的召唤物部署：`(时刻, token_key, 原因)`。与 `device_tokens` 同理
    #: ——拒收要留痕，不能悄悄少放一个还算胜利。
    #: 目前三种原因：召唤者不在场 / 召唤者没有召唤额度 / 已达同时部署上限。
    summon_rejected: list[tuple[float, str, str]] = field(default_factory=list)
    #: **随召唤者退场而消失**的召唤物：`(时刻, 召唤物名, 原因)`。
    #:
    #: 实机规则：召唤者一走，它的召唤物一并消失。这不是"少放一个"而是
    #: "场上少一个单位"，所以必须留痕——不留痕的话，主人阵亡后召唤物还站在
    #: 原地继续阻挡、继续出手，伤害账凭空多出一截且毫无征兆。
    summon_cascaded: list[tuple[float, str, str]] = field(default_factory=list)
    #: **圣山的祝福**的每次触发：`(时刻, 干员名, 冻结秒数, 冻住几名敌人)`。
    #:
    #: 「免死一次」是整场战斗**只可能发生一次**的事，它一旦发生就说明这名干员
    #: 本来会阵亡——结论会因此完全不同。这种事必须留痕，不能只在日志里滚过去。
    blessing_saves: list[tuple[float, str, float, int]] = field(
        default_factory=list)
    #: **因规则不成立而被拒收**的部署：`(时刻, 谁, 原因)`。目前两类原因：
    #: 「同一干员已在场」（不能同时放两个同名干员）与「再部署冷却未到」。
    deploy_rejected: list[tuple[float, str, str]] = field(default_factory=list)
    #: **因付不起费用而被拒收**的部署：`(时刻, 谁, 需要多少费, 当时有多少费)`。
    #: 只在 `cost_mode="strict"` 下会非空——这条账的意义就是让"宽松口径"与
    #: "严格口径"的差**看得见**，而不是靠人去猜哪几手做了手脚。
    cost_denied: list[tuple[float, str, int, float]] = field(default_factory=list)
    #: **被摧毁的装置**：`(时刻, 装置 key, 格子, 谁拆的)`。装置有血、会被拆
    #: （田鼷进阻流阀范围立刻造成目标最大生命值 50%/70% 的真伤，两下拆掉一个），
    #: 拆掉之后地形**还回**田地——这一整条都要能被检查，不能只看最后还剩几片田。
    devices_lost: list[tuple[float, str, tuple[int, int], str]] = field(
        default_factory=list)
    #: 这一局是**跑满时间上限**结束的（既没打赢也没打输）。
    #:
    #: 为什么要单列：`won=False` 原本同时表示"生命归零"和"跑满上限"两件事，
    #: 于是归因会写出「失败：生命归零（初始 3 点，共漏 0 只、扣了 0 点）」
    #: 这种自相矛盾的话——生命明明还剩 3 点。两者要分开说。
    timed_out: bool = False
    #: 跑满上限时**还站在场上、且不算漏怪**的单位：
    #: `[(名字, enemy_id, 是不是"清不掉"的)]`。第三个字段要留着：清不掉的单位
    #: （天桩-甲监测形态那类）**本来就不挡结算**，它出现在这张单子里是正常的；
    #: 真正让这一局收不了场的是**别的**那些。
    leftover_units: list[tuple[str, str, bool]] = field(default_factory=list)
    #: 出怪表的进度：`(已放, 总数)`。跑满上限时要靠它区分"这一波还没放完"与
    #: "放完了但场上还有东西"——两者要改的地方完全不同。
    spawns_placed: int = 0
    spawns_total: int = 0

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
        summon_book=None,
        fps: int = FPS,
        speed_scale: float = 1.0,
        verbose: bool = False,
        snow_freeze: bool = True,
        total_attack: "TotalAttackDevice | None | bool" = None,
        ranged_enemies: bool = True,
        enemy_windup: float = 0.5,
        heal_mode: str = "range",
        #: 费用口径，见 `self.cost_mode` 的说明。`legacy` / `strict`。
        #:
        #: **2026-09-18 定案：默认已是 `strict`。** 过程留档——切成 `strict` 后
        #: 三条基线先**全部塌掉**（1-7 从 137.0s/41 杀/0 漏 掉到 86.8s/8 杀/11 漏、
        #: 只部署下去 1 个干员；check_battle 231 项 24 失败、check_verify 58 项
        #: 10 失败），因为 1-7 那个三阵容的旧时刻**从来就付不起**（详见
        #: `tools/check_battle.py` 的 `[1]` 节）。把三阵容按真实费用重排
        #: （9 / 22 / 41s）后仍能胜利，结论降为 39 杀 / 2 漏 / 58650；
        #: 博士提供的真作业（怒潮凛冬单干员）在两种口径下**签名完全相同**。
        #: 其余两条基线（SR-6 196.6 / 201.4 / 196.6s、SR-EX-8 219.8s/38 杀/1 漏）
        #: 在 `strict` 下**一字未变**——它们本来就在真实费用里成立。
        cost_mode: str = "strict",
        #: **再部署规则**口径。与 `cost_mode` 同类，两条规则一起翻。
        #:
        #:   `legacy` —— 从前的行为：**一条检查都没有**。同一个 `char_id` 能被
        #:                两条 `Deployment` 同时摆上场（占两格、算两个单位），
        #:                撤退或阵亡后也能立刻再放——`OperatorUnit.redeploy_time`
        #:                那个 70 秒字段此前**没有任何人读**（死字段）。
        #:   `strict` —— 真实的游戏规则，两条：
        #:                ① 同一干员**不能同时在场上出现两个**；
        #:                ② 离场（撤退 / 阵亡 / 技能强制退场）后要等
        #:                   `redeploy_time` 秒才能重新部署。
        #:
        #: 与 `cost_mode` 分开留两个开关，是为了让"哪一条规则把结论改了"
        #: 能被单独测出来；**默认值同为 `strict`**（2026-09-18 定案）。
        redeploy_mode: str = "strict",
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
        #: 费用口径。**这是本轮新加的一条，两位数的结论都压在它上面。**
        #:
        #:   `legacy` —— 从前的行为：显式部署时刻是"**请求**"，模拟器照办，
        #:                包括付不起费的时候（费用夹到 0，等于白送）。当时的
        #:                理由是「验证器会如实写出这一手在游戏里做不出来」，
        #:                三条回归基线就靠这个宽松口径。
        #:   `strict` —— **真实的游戏规则**：付不起就这一手做不出来，拒收并
        #:                记进 `BattleResult.cost_denied`。
        #:
        #: 留成开关而不是直接替换，是为了让两种口径的差**可测量**：基线该不该
        #: 动、动了多少、哪一手动的，都能用同一份作业跑两遍对比出来，
        #: 而不是改完只看一个新数字。
        self.cost_mode = cost_mode
        self.redeploy_mode = redeploy_mode
        self.deployments: list[Deployment] = []
        self.skill_uses: list[SkillUse] = []
        self.retreats: list[tuple[float, tuple[int, int]]] = []
        #: 召唤物的部署计划。与干员分开一张表——它们的归属、上限、费用口径
        #: 都不同（见 `ak_tactic.battle.summons`）。
        self.summon_deployments: list["SummonDeployment"] = []
        #: 取召唤物属性的入口。为 None 时按需新建（首次真的要用才建，
        #: 这样不用召唤物的关卡完全不碰 `excel/character_table.json`）。
        self.summon_book = summon_book

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
        #: 阻流阀等装置**是否已把自身地块从田地里摘掉**。
        #: 预置装置开场即在位，所以这个标志在构造时就为真（见下面的 `_devices`
        #: 一段）。真正会等 3 秒的是玩家手动部署的阻流阀——那是另一条路。
        self._blockers_built = False
        # 装置表**无条件**解析：泵站 / 阻流阀归环境系统用，但「祟」明识形态的
        # 「清澈泵站生效范围内」判据、以及田鼷与阻流阀的互动也都要这张表。
        # 原先只在开了环境系统时解析，等于把这几条挂在"这一关有田地"上。
        #
        # ⚠ 这里是**运行态**（`DeviceUnit`：有血量、有建成、会被拆），不再是
        # 静态描述表。它和 `Device` 的字段名一致，所以泵水那类只读代码不用改。
        from .devices import (BLOCKER_KEY, DeviceUnit, initial_device_tokens,
                              make_devices)
        self._devices = make_devices(stage)
        #: 玩家手里的**装置额度**：关卡开局给的（`tokenCards[].initialCnt`）
        #: 加上 `DeathPassive.` 击杀掉落的。`_do_deploy_device` 从那里面扣。
        self.device_token_balance = initial_device_tokens(stage)
        #: 作业里的装置部署计划（按时刻排序后消费）。
        self.device_deployments: list = []
        # 模块级也拿一份：`_device_tick` 要判"这是不是改写地块的装置"。
        self._blocker_key = BLOCKER_KEY
        self._blocker_cells = [d.cell for d in self._devices if d.key == BLOCKER_KEY]
        if environment != "off":
            from .environment import FarmlandSystem, PolluteParams
            _p = PolluteParams.from_stage(stage, environment_difficulty)
            if _p is not None and _p.valid:
                self.farmland = FarmlandSystem(stage, _p)
                # 预置阻流阀走装置技能 2（无持续时间）→ **开场即在位**，
                # 它们的格子从第 0 秒起就不算田地。早先统一按 3 秒建成处理，
                # 等于让每一张有田地的图前 3 秒多算了若干格田地。
                for _c in self._blocker_cells:
                    self.farmland.sever(*_c)
                self._blockers_built = True
        #: 环境伤害的每秒结算节拍（与病害值的【实际】更新同拍，都是 1 秒）。
        self._env_timer = 0.0
        #: AuraHit 的"上一帧接触了哪些装置"：`id(敌人) -> {id(装置)}`。
        #: 原文是"**进入**范围时立刻"，是边沿触发，得记住上一帧的位置关系。
        self._aura_touch: dict[int, set[int]] = {}
        #: 天桩链：`id(装置) -> [它召唤出来的甲]`。装置随甲退场而死亡，
        #: 用这张表就不必每帧在"装置 × 敌人"上做笛卡尔积。
        self._pile_children: dict[int, list] = {}

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
        #: 场上所有活着的**贯穿弹道**（焰狐龙梓兰 技3「龙之箭」）。与剑气分开：
        #: 判定是**连续坐标 + 半径**、按距离分段结算、可重复命中同一敌人（带各自
        #: 的推动冷却），而剑气是格子判定 + 一次命中。
        self._arrows: list[dict] = []
        #: 已开技但**还没出弹道**的（抬手＋蓄力要 3 秒上下，见 `_schedule_arrow`）。
        self._pending_arrows: list[dict] = []
        #: 每位干员**上一次**部署的 (x, y, 朝向)——天赋「翔虫机动」要用它算
        #: "上次部署位置周围"（离场留下的静止弹道就停在那一格）。
        self._mobility_spot: dict[str, tuple[int, int, str]] = {}
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

    def plan_summon(self, deployment: "SummonDeployment") -> None:
        """排一次召唤物部署。**与 `plan()` 分开**——两者的归属与上限口径不同。

        能不能真放下去由模拟器在那一刻判（召唤者是否在场、是否已达同时上限），
        判不过就记进 `BattleResult.summon_rejected` 而不是静默丢弃。
        """
        self.summon_deployments.append(deployment)

    def plan_device(self, deployment) -> None:
        """排一次**装置**部署（`DeviceDeployment`）。

        与干员/召唤物都分开：装置不占干员名额、不归属任何干员，但它**要花费用**
        也**要消耗额度**（关卡给的 `tokenCards[].initialCnt` + `DeathPassive.`
        击杀掉落）。放不放得下去由那一刻判，判不过记进
        `BattleResult.device_deploy_rejected`，不静默丢弃。
        """
        self.device_deployments.append(deployment)

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

    def _apply_push(self, op: OperatorUnit, t: float) -> None:
        """推击：「将其中等力度地**朝部署方向**推动」（圣聆初雪技1「铃音吹雪」）。

        只认 `force` 这个键，而且它是**力度等级**（"中等力度" = 中力 = 1），
        **不是距离**。距离要按「受力等级 = 力度等级 − 重量等级」查表，规则全在
        `displace.py`，这里不重复实现。

        推动是**开启瞬间的一次性动作**（描述写"立即……并推动"），不是每次命中的
        附带效果——所以挂在 `_activate` 上，与 `_spawn_qi` 并列。

        **方向取 `op.facing`（部署方向）**，描述写的就是"朝部署方向推动"。

        重量取 `EnemyUnit.weight`（来自 gamedata 的 `massLevel`；敌人库里**没有**
        这一列）。重量为 0 的重装级敌人会被推得最远（约 2 格），重量 3 以上推不动
        ——`push_distance` 自己处理这个下限。
        """
        sk = op.skill
        if sk is None:
            return
        force = float(sk.blackboard.get("force") or 0.0)
        if force <= 0.0:
            return
        level = displace.skill_force_level(force)
        fx, fy = op.facing
        cells = self._range_of(op)
        pushed = 0
        for e in self.enemies:
            if e.hp <= 0 or e.leaked or e.off_map:
                continue
            if e.cell() not in cells:
                continue
            dist = displace.push_distance(level, e.weight)
            e.apply_push(fx * dist, fy * dist)
            pushed += 1
        if pushed and self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 推击 {pushed} 名敌人"
                f"（力度等级 {level}，朝{op.direction}）")

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

    # ------------------------------------------------ 贯穿弹道（焰狐龙梓兰 技3）

    def _schedule_arrow(self, op: OperatorUnit, t: float, *,
                        first: bool, eff) -> None:
        """排一次「龙之箭」的发射（技3）。

        开技之后**先走抬手＋蓄力**才出弹道，时间取 prts.wiki 该页 `|备注=`：

        > 「蓄力 3 秒后」实为从技能开启动画播放完毕后开始 **1.5 秒**蓄力计时……
        > 首次开启时将需要约 **110 帧（≈3.67 秒）**、非首次开启需要约
        > **90 帧（≈3 秒）**才能开始发射龙之箭，随后约 **3 帧（0.1 秒）**后
        > 产生弹道

        两个总时长里都**含**那 1.5 秒蓄力（`wait_duration`），所以动画段是
        3.67 − 1.5 = 2.17 与 3.0 − 1.5 = 1.5。首次更长是**天赋1 改了开启动画**
        （备注里点名），判据就是"这是本局第几次开技"。

        参数在这里**拍快照**：弹道离开她之后就与她的属性/技能状态无关
        （PRTS「弹道」页：「弹道携带着许多完成一次攻击所需的信息」）。
        """
        anim = _ARROW_ANIM_FIRST if first else _ARROW_ANIM_LATER
        delay = anim + float(eff.pierce_charge or 0.0) + _ARROW_PROJECTILE_DELAY
        d = {"Right": (1, 0), "Left": (-1, 0), "Up": (0, -1), "Down": (0, 1)}
        dx, dy = d.get(op.direction, (1, 0))
        self._pending_arrows.append({
            "at": t + delay,
            "op": op,
            # 出弹道点是"自身的弹道受击点"，备注写明**始终向北偏移约 0.2323 格**。
            # MAA 口径 y 向下 ⇒ 北 = −y。
            "x": float(op.position[0]),
            "y": float(op.position[1]) - _ARROW_SPAWN_OFFSET,
            "dx": dx, "dy": dy,
            "atk": float(op.atk),
            "phys": float(eff.atk_scale or 0.0),
            "magic": float(eff.pierce_magic_scale or 0.0),
            "step": float(eff.pierce_step or 0.0),
            "max_dist": float(eff.pierce_max_dist or 0.0),
            "force": float(eff.pierce_force or 0.0),
            "push_cd": float(eff.pierce_push_cd or 0.0),
        })
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 开始蓄力（{delay:.2f}s 后发射龙之箭）")

    def _arrow_tick(self, dt: float, t: float) -> None:
        """推进所有贯穿弹道：到点生成 → **每走 `pierce_step` 格结算一次**。

        结算规则（备注 + 玩家 0.1 倍速慢放实测，出处见 `docs/uncertainties.md`
        §十三之三）：

        * 每走 `dist_interval`（0.25 格）结算一次，**每次对碰撞半径 0.5 内的
          所有敌人**各造成**先物理、后法术**两笔伤害。
        * 所以在半径 0.5 的圆里，一个敌人会吃到 4 次左右的结算——实测原话
          「1.5 萬血閃盾一下判定 4 下死亡」正合这个几何（1.0 格 ÷ 0.25 = 4）。
          敌人**不是质点**时（BOSS 体积大）判定更多，实测歲相是 13 次；
          本项目把敌人当质点，所以对大体型敌人偏少，这条边界记在留档里。
        * 推动沿**弹道方向**，对**每个敌人各自**有 `knockback_duration`
          （1 秒）的冷却。
        """
        if not self._arrows and not self._pending_arrows:
            return
        # 1) 到点的先出弹道
        still_pending = []
        for rec in self._pending_arrows:
            if t + 1e-9 < rec["at"]:
                still_pending.append(rec)
                continue
            rec.pop("at")
            rec["travelled"] = 0.0
            rec["acc"] = 0.0
            rec["life"] = _ARROW_LIFETIME
            rec["push_at"] = {}
            # 碰撞状态：`inside` = 此刻在半径内的，`spent` = 已经**离开过**这条
            # 弹道的。见 `_arrow_probe` 里那条博士裁定。
            rec["inside"] = set()
            rec["spent"] = set()
            self._arrows.append(rec)
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {rec['op'].name} 射出龙之箭")
        self._pending_arrows = still_pending

        # 2) 推进并结算
        speed = _ARROW_SPEED
        alive = []
        for a in self._arrows:
            a["life"] -= dt
            travel = speed * dt
            step = float(a["step"] or 0.25)
            # **按累计距离结算**：每飞满 `pierce_step`（0.25 格）才打一次。
            # 早先的写法是把每帧位移切成 0.25 的整数块、**余数也当成一个结算点**
            # （10 格/秒 ÷ 30 帧 = 0.333 = 0.25 + 0.083），于是每帧多打一次：
            # 一个静止靶子被判定 6 次，而几何上只该有 3~4 次。用累加器就没有这问题。
            a["x"] += a["dx"] * travel
            a["y"] += a["dy"] * travel
            a["travelled"] += travel
            a["acc"] += travel
            while a["acc"] >= step - 1e-9 and a["life"] > 0.0:
                a["acc"] -= step
                self._arrow_probe(a, t)
            if (a["life"] > 0.0
                    and (a["max_dist"] <= 0.0
                         or a["travelled"] < a["max_dist"])
                    and self._on_map(a["x"], a["y"])):
                alive.append(a)
            elif self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  龙之箭消失（飞了 {a['travelled']:.1f} 格）")
        self._arrows = alive

    def _on_map(self, x: float, y: float) -> bool:
        """坐标是否还落在地图范围内（给弹道用）。

        **箭是飞过地形的**：它从"弹道受击点"出去后直线飞行、射程"无限远"，
        所以不能拿 `walkable` 判——干员常常站在**高台**上，而高台格对地面单位
        不可走，用 `walkable` 会让弹道在出膛那一帧就被删掉（这个坑当时真的踩了：
        弹道一条都没活下来，靶子毫发无伤）。真正让它消失的只有三种情况：
        存在 30 秒走完、飞满 `max_dist`（99 格）、或飞出地图。
        """
        tiles = getattr(self.stage.map, "tiles", None)
        if not tiles:
            return True
        h = len(tiles)
        w = len(tiles[0]) if h else 0
        return -1.0 <= x <= w and -1.0 <= y <= h

    # ------------------------------------------------- 天赋：翔虫机动（落位加成）

    def _mobility_cells(self, op: OperatorUnit, prev: tuple[int, int],
                        prev_dir: str, rng: str) -> set[tuple[int, int]]:
        """「上次部署位置周围」的格集合：以 `prev` 为原点、范围代号 `rng`。

        范围代号来自天赋黑板（`x-1`），走的是和技能改写范围同一条路
        （`range_provider(..., range_id=…)`），所以**不另建一套几何**。
        拿不到范围表时退化成"自身格 ＋ 朝向前方三格"，与 `_range_of` 一致。
        """
        if self.range_provider is not None:
            try:
                cells = self.range_provider(op.char_id, op.elite, prev_dir, prev,
                                            range_id=rng)
                if cells:
                    return {(int(x), int(y)) for x, y in cells}
            except Exception:
                pass
        fx, fy = {"Right": (1, 0), "Left": (-1, 0),
                  "Up": (0, -1), "Down": (0, 1)}.get(prev_dir, (1, 0))
        return {(prev[0], prev[1])} | {(prev[0] + fx * i, prev[1] + fy * i)
                                       for i in (1, 2, 3)}

    def _mobility_on_deploy(self, op: OperatorUnit, d, t: float) -> None:
        """部署瞬间结算天赋「翔虫机动」（焰狐龙梓兰 天赋2）。

        prts.wiki 该页 `|备注=` 原文：

        > ※离场后将在原地留下一个静止[[弹道]]，弹道效果范围 `[范围:x-1]`，
        > 持续存在直至下次焰狐龙梓兰部署
        > ※**非首次部署时**……部署于该弹道范围后将获得攻击力加成效果

        所以判据是两段：**她已经部署过一次**，且这次落点在**上次部署点**的
        `x-1` 范围内 ⇒ 攻击力 +15%、持续 30 秒。首次部署没有弹道可落，不给。

        上次的位置在**这次结算完之后**才更新——先算再写，顺序反了就变成
        "拿自己跟自己比"，永远命中（那种 bug 不会报错，只会让加成一直亮着）。
        """
        prev = self._mobility_spot.get(op.char_id)
        self._mobility_spot[op.char_id] = (int(d.position[0]),
                                           int(d.position[1]), d.direction)
        g = find_glider_mobility(op.talents)
        if g is None or prev is None or not g.deploy_range:
            return
        cells = self._mobility_cells(op, (prev[0], prev[1]), prev[2],
                                     g.deploy_range)
        if (int(d.position[0]), int(d.position[1])) not in cells:
            return
        op.mobility_atk_pct = g.atk_bonus
        op.mobility_atk_left = g.atk_duration
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 落在上次部署位置周围（{g.deploy_range}）："
                f"攻击力 +{g.atk_bonus:.0%}，持续 {g.atk_duration:g} 秒")

    def _mobility_tick(self, dt: float) -> None:
        """天赋「翔虫机动」的限时加成倒计时。

        加成是**部署时的一次性授予**，所以这里只管到期收走；`mobility_atk_pct`
        置 0 之后 `current_atk()` 自然回到原面板。
        """
        for op in self.operators:
            if op.mobility_atk_left <= 0.0:
                continue
            op.mobility_atk_left -= dt
            if op.mobility_atk_left <= 0.0:
                op.mobility_atk_left = 0.0
                op.mobility_atk_pct = 0.0

    def _arrow_probe(self, a: dict, t: float) -> None:
        """一次结算：半径内的每个敌人各吃物理＋法术两笔，推动带各自冷却。

        **同一条弹道对同一个敌人只碰一次。**（博士 2026-09-18 裁定）备注写了
        「推动效果对每个敌人具有 1 秒的冷却（每个敌人单独计算）」，而弹道本身
        以 10 格/秒飞行——被推开的敌人在那 1 秒里根本追不上、也回不到碰撞半径
        内，所以**同一条龙之箭不存在第二次接触**。

        实现上不按"碰过就打勾"，而是**离开半径才算用掉**（`spent`）：一次接触
        期间每 0.25 格仍然各结算一次（这正是实测里"閃盾一下判定 4 下"的来源），
        但敌人一旦被推离半径，这条弹道对它就再也不结算了。
        """
        op = a["op"]
        for e in self.enemies:
            if not e.alive or e.leaked or e.off_map:
                continue
            inside = math.hypot(e.position[0] - a["x"],
                                e.position[1] - a["y"]) <= _ARROW_RADIUS
            if not inside:
                if id(e) in a["inside"]:
                    a["inside"].discard(id(e))
                    a["spent"].add(id(e))
                continue
            if id(e) in a["spent"]:
                continue
            a["inside"].add(id(e))
            # **先物理、后法术**（备注原话），两笔各自吃防御/法抗。
            for dtype, scale in ((DamageType.PHYSICAL, a["phys"]),
                                 (DamageType.MAGIC, a["magic"])):
                if scale <= 0.0:
                    continue
                dmg = resolve_damage(a["atk"], damage_type=dtype, scale=scale,
                                     defense=e.defense, res=e.res)
                self._damage_enemy(e, dmg.final, t, dtype, source=op)
            if not e.alive:
                continue
            # 推动：沿弹道方向、每个敌人各自 1 秒冷却。
            last = a["push_at"].get(id(e), float("-inf"))
            if t - last < a["push_cd"]:
                continue
            a["push_at"][id(e)] = t
            level = displace.skill_force_level(
                a["force"], getattr(op, "base_force_level", 0.0) or 0.0)
            dist = displace.push_distance(level, e.weight, ballistic=True)
            if dist > 0.0:
                e.apply_push(a["dx"] * dist, a["dy"] * dist)
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  龙之箭推动 {e.name} {dist:.2f} 格")

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

    def _blessing_tick(self, t: float) -> None:
        """兑现天赋「圣山的祝福」欠下的那次"攻击范围内全体敌人冻结"。

        `OperatorUnit.take()` 只够得着自己，碰不到场上别的单位，所以它免死时
        只把"要冻 N 秒"记在 `blessing_freeze` 上，由这里在**下一帧**兑现。
        差一帧（1/30 秒）在这里无所谓；而把空间查询塞进 `take()`，会让那个
        本来是纯数值的函数反向依赖整张地图，得不偿失。
        """
        for op in self.operators:
            if op.blessing_freeze <= 0.0 or not op.alive:
                continue
            secs = op.blessing_freeze
            op.blessing_freeze = 0.0
            cells = set(self._range_of(op))
            hit = 0
            for e in self.enemies:
                if not e.alive or e.leaked or e.off_map:
                    continue
                cell = (int(round(e.position[0])), int(round(e.position[1])))
                if cell in cells:
                    # **取更大值**而不是覆盖：她已经冻着的敌人不该因为这次
                    # 触发反而被缩短。与 `sluggish_timer` 等的写法保持一致。
                    e.freeze_timer = max(e.freeze_timer, secs)
                    e.frozen = True
                    hit += 1
            self.result.blessing_saves.append((t, op.name, secs, hit))
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {op.name} 圣山的祝福触发：生命值回满、自身冻结，"
                    f"攻击范围内 {hit} 名敌人冻结 {secs:g}s")

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
            e.frozen = e.freeze_timer > 0.0
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
        # ---- 概率晕眩（提丰技2「冰原秩序」：`attack@prob 0.4` / `attack@stun 1.0`）
        #
        # 走**期望占比**而不是掷骰：每次命中给敌人的晕眩计时**加上**
        # `prob × 秒数`（0.4 秒），计时器照常递减。攻击间隔大于单次时长时
        # 占比正好是 `prob × 秒数 / 间隔`；间隔更短时计时持续为正、敌人一直晕
        # ——那正是该有的封顶。
        #
        # **是「加」不是 `max`**：用 `max` 在间隔小于单次时长时会把占比
        # **低估**成单次时长。
        #
        # 键只能按**键名**取、不能按语义猜：`prob` 在同批干员里同名反义
        # （赤刃技2 的 `prob` 是闪避率，这里是控场概率）。
        if source is not None and source.alive and source.skill_active:
            sk = source.skill
            if sk is not None:
                # **直接取属性，绝不用 `getattr(..., None) or {}`**：黑板挂在
                # **`SkillLevel`** 上，不在 `SkillEffects` 上。上一版就是取错了
                # 对象，`getattr` 给回一个空字典、这里永远不上晕——而"没上晕"
                # 与"这个技能本来就无晕"在输出上长得一模一样，只有守卫能发现。
                # 取错时让它直接抛。
                bb = sk.blackboard
                # **三套键名**：提丰技2 写 `attack@prob` + `attack@stun`，
                # 焰狐龙梓兰技1「刚射」写**裸的** `stun_prob` + `stun`
                # （「每支箭矢有 20% 概率使目标晕眩 2 秒」），泥岩技2「岩崩锤」
                # 写**裸的** `buff_prob` + `stun`（「并有 30% 的几率晕眩其 1.2 秒」）。
                # 不能合并成一个键名去认：`prob` 在同批干员里**同名反义**
                # （赤刃技2 的 `prob` 是闪避率，不是控场概率）。
                if "stun_prob" in bb:
                    p = float(bb.get("stun_prob") or 0.0)
                    secs = float(bb.get("stun") or 0.0)
                elif "buff_prob" in bb:
                    # `buff_prob` 全库只有两处：泥岩技2（这条技能）与妖灵
                    # 「精确打击」（「有 25% 的几率使其晕眩 2 秒」）——两处
                    # 都是**概率晕眩**，没有同名反义，故可以安全并进这条通道。
                    p = float(bb.get("buff_prob") or 0.0)
                    secs = float(bb.get("stun") or 0.0)
                else:
                    p = float(bb.get("attack@prob") or 0.0)
                    secs = float(bb.get("attack@stun") or 0.0)
                if p > 0.0 and secs > 0.0:
                    e.stun_timer += p * secs
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
        """在「阻挡自身的单位(被阻挡时)/自身(未被阻挡时)」周围给田地加病害。

        圆心按原文取：被阻挡时是**挡它的那个干员**脚下那一格，否则是敌人
        自己脚下那一格。半径按**圆**算（半径 1.0 恰好够到上下左右四邻、
        够不到斜角，见 `environment.cells_in_radius`）。

        ⚠ 加的是**【缓存】**，不是当场改【实际】/【最大】——「病害值 +N」的
        落地路径是 缓存 →（每 0.2s 释放 1 点）→【最大】 →（每 1s 靠拢）→【实际】。
        所以日志写「记入缓存 N」，不要写成「病害值立刻 +N」。
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
                f"{t:7.1f}s  {e.name} {why} → 田地病害 +{got:.0f} 记入缓存"
                f"（{amount:g} × 范围内田地格，随后每 0.2s 释放 1 点到【最大】）")
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

    def _enemy_stats(self, enemy_id: str, level: int):
        """取敌人数值，**支持关卡自带的敌人定义**（``enemyDbRefs`` 里 ``useDb: false``）。

        那些 id（怀黍离的 ``enemy_1398_dhdcr_b`` / ``enemy_1399_dhtb_b``）不在
        属性库里，整份数据写在关卡文件里，只有 ``prefabKey`` 指向的那个在库里。
        库那一步取不到时，才走本地覆盖；本地也没有就照原样把异常抛出去——
        静默返回一个空数值会让召唤链"看起来跑了、其实什么都没算"。
        """
        try:
            return self.enemy_at(enemy_id, level)
        except Exception:
            local = self.stage.local_enemies().get(enemy_id)
            if not local:
                raise
            owner = getattr(self.enemy_at, "__self__", None)
            if owner is None or not hasattr(owner, "with_overwrite"):
                raise
            return owner.with_overwrite(enemy_id, local, level)

    def _build_enemy(self, enemy_id: str, level: int, pts: list, legs: list,
                     t: float, wait: float) -> EnemyUnit:
        stats = self._enemy_stats(enemy_id, level)
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
            # ---- 天桩链（怀黍离）：CheckAwake 状态机 + 附着伤害 + 嘲讽等级
            awake_hp_ratio=float(getattr(stats, "awake_hp_ratio", 0.0) or 0.0),
            awake_summon_ratio=float(
                getattr(stats, "awake_summon_ratio", 0.0) or 0.0),
            awake_value=float(getattr(stats, "awake_value", 0.0) or 0.0),
            awake_value_eff=float(getattr(stats, "awake_value_eff", 0.0) or 0.0),
            awake_enemy_key=str(getattr(stats, "awake_enemy_key", "") or ""),
            awake_summon_cnt=int(getattr(stats, "awake_summon_cnt", 0) or 0),
            attach_damage=float(getattr(stats, "passive_attach_damage", 0.0) or 0.0),
            taunt_level=float(getattr(stats, "taunt_level", 0.0) or 0.0),
            # ---- 技能攻击（怀黍离「玷 / 勿玷」的技能「污」）
            skill_atk_key=str(getattr(stats, "skill_atk_key", "") or ""),
            skill_atk_scale_phys=float(
                getattr(stats, "skill_atk_scale_phys", 0.0) or 0.0),
            skill_atk_scale_magic=float(
                getattr(stats, "skill_atk_scale_magic", 0.0) or 0.0),
            skill_atk_pollut=float(getattr(stats, "skill_atk_pollut", 0.0) or 0.0),
            skill_atk_targets=int(getattr(stats, "skill_atk_targets", 0) or 0),
            skill_atk_cross=int(getattr(stats, "skill_atk_cross", 0) or 0),
            skill_atk_ground_only=bool(
                getattr(stats, "skill_atk_ground_only", False)),
            skill_atk_no_normal=bool(
                getattr(stats, "skill_atk_no_normal", False)),
            skill_atk_interval=float(
                getattr(stats, "skill_atk_interval", 0.0) or 0.0),
            skill_atk_init=float(getattr(stats, "skill_atk_init", 0.0) or 0.0),
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

    def _steal_aspd(self, op: OperatorUnit, eff: SkillEffects,
                    t: float) -> None:
        """新约能天使技2：**立刻**从一名友方身上偷走攻速，加到自己头上。

        正文：「立即偷取攻击范围内 1 名友方干员 70 点攻击速度（持续至技能结束
        或新约能天使离场）……如果**成功**偷取攻击速度则额外获得 5 发弹药」。

        * **挑谁**：prts.wiki 该技能 `|备注=` 原文是「选择的友方干员为攻击范围内
          **仇恨值最高**的我方干员」。本仓库没有仇恨值模型（唯一的仇恨口径是
          "敌人打**最后部署**者"，见 `_pick_targets`），所以这里按**同一口径**
          取范围内最后部署的那一位；这条近似写进了 `docs/uncertainties.md`。
        * **偷多少**：`steal`（70）夹在 `steal_max`（999）以内——她一次只偷 70、
          够不到上限，所以那个上限在她身上是空转，但夹一下免得别的技能复用
          这条通道时漏掉。
        * **只有成功才加弹药**：范围内没有友方可偷 → 不加那 5 发。反过来，
          加弹药也只给**弹药类**技能加（没有弹药的技能加了不起作用，也不该报错）。
        """
        amt = float(eff.steal_aspd)
        if eff.steal_aspd_max > 0.0:
            # `steal_max` 是**累计**上限（"最多 X 点"），不是单次上限：
            # 她一次只偷 70、上限 999，所以这个夹子在**她身上**是空转；
            # 写成累计式是为了别的技能复用这条通道时不至于偷超。
            amt = min(amt, max(0.0, float(eff.steal_aspd_max)
                               - op.aspd_steal_bonus))
        if amt <= 0.0:
            return
        cells = self._range_of(op)
        victim = None
        for other in self.operators:
            # 「友方**干员**」：召唤物不算（`is_summon`），自己不算，
            # 已经倒下的不算，站在她射程外的也不算。
            if other is op or other.is_summon or not other.alive:
                continue
            if other.position in cells:
                victim = other          # 后部署的覆盖先部署的 → 取到最后部署者
        if victim is None:
            return
        victim.aspd_loss += amt
        op.aspd_steal_bonus += amt
        op.steal_target = victim
        op.steal_amount = amt
        if op.skill is not None and op.skill.duration_type == "AMMO":
            op.ammo_left += int(eff.steal_bonus_ammo)
        # 「自身**与其**获得最大生命值 250% 的屏障，该屏障会持续衰减」——她自己
        # 那一份在 `_activate` 里发了，被偷的这位在这里补（这里才知道偷的是谁）。
        # prts 备注：「屏障均以**自身生命上限**为标准计算」，所以各按各自的上限。
        if eff.barrier_decay_pct > 0.0:
            self._grant_decay_barrier(victim, eff.barrier_decay_pct,
                                      eff.barrier_decay_secs)
        self.result.log.append(
            f"{t:7.1f}s  {op.name} 偷取 {victim.name} 的 {amt:g} 点攻击速度"
            f"（技能结束时归还）")

    def _revert_steal(self, op: OperatorUnit) -> None:
        """把偷来的攻速**还回去**：技能结束、或她离场（倒下）时都走这里。

        两处都要管，是因为正文写的是「持续至技能结束**或新约能天使离场**」——
        只挂 `_deactivate` 的话，她在技能中途倒下就会把那 70 点永久扣在
        队友身上。`_skill_tick` 每帧都会看到"她已经 `alive` 为假"，
        所以那条路也能收尾。
        """
        victim = op.steal_target
        if victim is not None and op.steal_amount > 0.0:
            victim.aspd_loss = max(0.0, victim.aspd_loss - op.steal_amount)
        op.steal_target = None
        op.steal_amount = 0.0
        op.aspd_steal_bonus = 0.0

    def _lock_tick(self, dt: float, t: float) -> None:
        """泥岩技3「秽壤的血脉」前 10 秒的【闭锁】场。

        三件事，都按 prts 该技能 `|备注=` 与正文分开落：

        * **不能行动 + 不受到伤害**——那两个在别处：出手闸门在
          `_operators_attack`、免伤在 `OperatorUnit.take`，这里只管计时；
        * **周围敌人移动速度 −60%**（正文），prts 备注补了一句
          「**减速效果可对飞行单位生效**」——所以这一路**不分**地面/飞行
          （与醒来那一下的晕眩正相反，那个正文明写"地面"）；
        * **醒来那一帧**（计时递减到 0）晕眩周围**地面**敌人 `stun` 秒。

        「周围」取她的**技能范围**（`x-1`）：prts 备注只澄清了飞行那一条，
        没写范围口径；按技能自身范围读与「攻击阻挡的所有敌人」同源，是这里
        能给出的最有依据的一种读法，已连同另一种可能（八格）记进留档。

        减速写进 `e.lock_slow`（**不是** `speed_multiplier`：那一个归积雪所有，
        没有积雪场时整帧不重置，乘上去会逐帧连乘），本函数每帧先全场置 1.0
        再刷，所以技能结束/走出范围都自动恢复。
        """
        for e in self.enemies:
            e.lock_slow = 1.0
        for op in self.operators:
            if op.locked_timer <= 0.0:
                continue
            eff = op.effects
            if eff is None or not op.alive:
                # 技能被关掉/她倒下：闭锁立刻结束，不补"醒来"那一下
                op.locked_timer = 0.0
                continue
            cells = self._range_of(op)
            if eff.move_speed < 0.0:
                for e in self.enemies:
                    if e.hp <= 0 or e.leaked or e.off_map:
                        continue
                    if e.position in cells:
                        e.lock_slow = min(e.lock_slow, 1.0 + eff.move_speed)
            op.locked_timer = max(0.0, op.locked_timer - dt)
            if op.locked_timer <= 0.0:
                # 醒来那一下的时长从**黑板**上取（`stun` 挂在 `SkillLevel` 上，
                # 不在 `SkillEffects` 上——取错对象会静默拿到 0，"不上晕"与
                # "这技能本来就无晕"输出一模一样，只有守卫能发现）。
                secs = float(op.skill.blackboard.get("stun") or 0.0)
                n = 0
                for e in self.enemies:
                    if e.hp <= 0 or e.leaked or e.off_map or e.is_flying:
                        continue          # 正文：「周围**地面**敌人」
                    if e.position in cells:
                        e.stun_timer = max(e.stun_timer, secs)
                        n += 1
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {op.name} 闭锁结束 → 晕眩 {n} 名地面敌人 "
                        f"{secs:g}s")

    def _begin_cost_trickle(self, op: OperatorUnit) -> None:
        """开技时**排**这一轮的"逐渐获得部署费用"（可露希尔那一族）。

        总额三处来：

        1. 解析侧给的 `cost_trickle_total`（技2 = `cost_period` 15、技3 = 18、
           技1 = `cost` 3，见 `skill._cost_semantics` / `_cost_trickle`）；
        2. 「每使用过一次技能 +X，最多提升至 Y」（技1 的 `cost_per_add` /
           `cost_add_max`）——按**本场部署以来**的用次数加；
        3. 有方括号变体（`…[add_cost_period].cost` / `.interval`）就按那个**离散
           节奏**发（技2：1 点 / 2 秒），没有就按技能时长**均分**（技1）。

        技能中途被关掉（手动停、弹药打完）时剩余作废——正文写的是
        "技能持续时间内"，见 `_cost_trickle_tick`。
        """
        eff = op.effects
        if eff is None:
            return
        total = eff.cost_trickle_total
        if eff.cost_per_add > 0.0:
            grown = total + eff.cost_per_add * max(0, op.skill_use_count - 1)
            total = min(grown, eff.cost_add_max) if eff.cost_add_max > 0.0 \
                else grown
        if total <= 0.0:
            return
        dur = float(getattr(op.skill, "duration", 0.0) or 0.0)
        op.cost_trickle_left = total
        op.cost_trickle_per = eff.cost_trickle_per
        op.cost_trickle_interval = eff.cost_trickle_interval
        op.cost_trickle_timer = 0.0
        op.cost_trickle_rate = (total / dur
                                if (eff.cost_trickle_per <= 0.0 and dur > 0.0)
                                else 0.0)
        if self.verbose and total > 0.0:
            self.result.log.append(
                f"{self._t:7.1f}s  {op.name} 技能期间逐渐获得 {total:g} 点费用"
                f"（第 {op.skill_use_count} 次使用）")

    def _cost_trickle_tick(self, dt: float, t: float) -> None:
        """「技能持续时间内逐渐获得 X 点部署费用」的兑现。

        两种节奏：**离散**（有方括号变体，技2/技3——1 点 / 2 秒那种）与
        **均分**（技1——只有总额，按技能时长摊到每一帧）。离散那种不能改成
        均分：1 点费早到 0.9 秒，可能就是一个干员能不能踩上那一拍落地的差别。
        """
        for op in self.operators:
            if op.cost_trickle_left <= 0.0:
                continue
            if not op.alive or not op.skill_active or op.effects is None:
                op.cost_trickle_left = 0.0      # 技能没了，剩余作废
                continue
            per, iv = op.cost_trickle_per, op.cost_trickle_interval
            if per > 0.0 and iv > 0.0:
                op.cost_trickle_timer += dt
                while (op.cost_trickle_timer >= iv
                       and op.cost_trickle_left > 0.0):
                    op.cost_trickle_timer -= iv
                    give = min(per, op.cost_trickle_left)
                    self.cost = min(self.max_cost, self.cost + give)
                    op.cost_trickle_left -= give
            elif op.cost_trickle_rate > 0.0:
                give = min(op.cost_trickle_rate * dt, op.cost_trickle_left)
                self.cost = min(self.max_cost, self.cost + give)
                op.cost_trickle_left -= give

    def _hitrate_tick(self, dt: float) -> None:
        """「使范围内地面敌人**命中率 −X%**」的场（阿斯卡纶技3「残影」/ 艾拉技1）。

        为什么是**每帧重刷**而不是"开技时贴上去、关技时撕下来"：

        * 条件是**位置**——敌人走出她的射程就该恢复，走进来就该生效，
          贴一次就管不了这两个方向；
        * 技能关了、她离场了、她自己被打倒了，也都该恢复——重刷天然覆盖这几种。

        多条同类场同时在时取**最负**的那个（命中率减得最多的赢）。这是**裁定
        前的保守读法**：多条同类减益是取最负、还是相乘、还是相加，正文与备注
        都没写；本批十位里只有她一条，所以这个分歧暂时看不出来，已记进
        `docs/uncertainties.md`。

        「地面敌人」：飞行的不吃（`is_flying`），与正文一致。
        """
        for e in self.enemies:
            e.hitrate_phys = 0.0
            e.hitrate_arts = 0.0
        for op in self.operators:
            if not op.alive or op.effects is None:
                continue
            eff = op.effects
            if eff.enemy_hitrate_phys == 0.0 and eff.enemy_hitrate_arts == 0.0:
                continue
            cells = self._range_of(op)
            for e in self.enemies:
                if e.hp <= 0 or e.leaked or e.is_flying:
                    continue
                if e.position not in cells:
                    continue
                e.hitrate_phys = min(e.hitrate_phys, eff.enemy_hitrate_phys)
                e.hitrate_arts = min(e.hitrate_arts, eff.enemy_hitrate_arts)

    def _hitrate_factor(self, e: EnemyUnit) -> float:
        """敌人这一笔出手的**命中率折扣**——按它自己的伤害类型取那一路。

        只有**普通攻击**（含挂在上面的附加伤害）吃这一项：正文说的是"命中率"，
        而敌人**技能**伤害算不算命中率，正文与 prts 备注都没写，所以这里不碰
        技能那两处（怀黍离的疫病齐射），已记进留档。
        """
        penalty = (e.hitrate_arts if e.attack_type == "MAGIC"
                   else e.hitrate_phys)
        return max(0.0, 1.0 + penalty)

    def _trait_tick(self, dt: float) -> None:
        """每帧的**特性**结算（与技能状态无关的那一类）。

        现在只有一条：怪杰特性「**自身生命会不断流失**」——每秒流失**生命上限**
        的 `hp_drain_per_sec`（三位怪杰都是 0.01，判据见 `traits.read_hp_drain`）。

        它**不能塞进 `_skill_tick`**：那个函数在没有技能的干员上会 `continue`
        （见它自己那句 `if op.skill is None`），而这条特性与有没有技能毫无关系。
        单独一个钩子也说得清"这一帧掉的血从哪来"。

        「流失到 0 会怎样」：照 `alive`（`hp > 0`）的既有口径处理——她会当场
        失去战斗能力，后续的选敌/阻挡/结算都会把她排除在外。prts.wiki
        「新约能天使」页的 `|备注=` **没有提这条特性**，所以"能不能流失致死"
        与"治疗能不能抵消"两点无从查证，这里按最直白的读法落（见
        `docs/uncertainties.md`）。
        """
        for op in self.operators:
            if op.hp_drain_per_sec <= 0.0 or not op.alive:
                continue
            # 封底到 0：生命不会为负（与敌人那边同一口径）。扣到 0 之后
            # `alive` 就是 False，后面几段都会跳过她，不必在这里做撤退。
            op.hp = max(0.0, op.hp - op.max_hp * op.hp_drain_per_sec * dt)

    def _skill_tick(self, dt: float, t: float) -> None:
        """每帧的技能结算：回技力、够不够开、持续到点了没有。"""
        res = self.result
        for op in self.operators:
            if not op.alive:
                # 她**在技能中途倒下**时也要把偷来的攻速还回去——正文写的是
                # 「持续至技能结束或新约能天使离场」，而这条路不走 `_deactivate`
                # （技能还开着），所以在这里兜。只要还欠着，还一次就清空。
                if op.steal_target is not None:
                    self._revert_steal(op)
                continue
            # 自晕倒计时（技能结束后自身晕眩）。递减挂在这里只是因为它
            # 同样按帧走；晕眩本身与技能状态无关。
            if op.stun_timer > 0:
                op.stun_timer = max(0.0, op.stun_timer - dt)
            # 【冻结】同理，也是按帧走的剩余时长。干员侧的冻结 = 缴械，
            # **不动阻挡**，所以它有自己的字段、不能并进 stun_timer。
            if op.freeze_timer > 0:
                op.freeze_timer = max(0.0, op.freeze_timer - dt)
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

            # 未开启：按回复方式攒技力。
            #
            # **上限是 `sp_cost × max_charge`，不是 `sp_cost`。** 可充能 N 次的
            # 技能允许把 N 次的使用额度**攒起来**（技力每满一次 sp_cost 就存下
            # 一次），所以没开技能的时候同样该攒过 sp_cost。
            #
            # 这里原来写死 `sp_cost`，等于"充能"只在技能**开启期间**才攒得动
            # （上面那一支写的就是 `sp_cost * max_charge`）。而圣聆初雪技1 是
            # **瞬发**（`duration = -1`），开启期间只有一两帧——于是"可充能 2 次"
            # 这条对**最需要它的那类技能**从来没生效过。
            # 全库带 `max_charge_time > 1` 的技能有 143 个，不是个小面。
            if sk.sp_type == "INCREASE_WITH_TIME":
                op.sp = min(sk.sp_cost * max(1, sk.max_charge),
                            op.sp + sk.increment * dt)

            ready = op.sp >= sk.sp_cost
            want = op.skill_request or sk.auto_trigger or op.auto_skill
            # 「整场战斗中该技能只能释放一次」（阿米娅技2 影霄·绝影）：
            # 放过一次就不再开，哪怕技力又攒满。`sp_charges` 是累计开启次数。
            if sk.effects.once_per_battle and op.sp_charges >= 1:
                want = False
            if ready and want:
                self._activate(op, t)
            op.skill_request = False

    def _grant_barrier(self, op: OperatorUnit, pct: float, *,
                       to_summons: bool) -> None:
        """把屏障发给 `op`；`to_summons` 时连它的召唤物一起发。

        比例是对**各自的生命上限**算的，不是对主人的——召唤物的生命上限与
        主人无关（戴乌 3230、电弧是另一个数），共用一个数会静默算错。
        """
        op.grant_barrier(pct)
        if not to_summons:
            return
        for sm in self.operators:
            if sm.summon_of == op.char_id and sm.alive:
                sm.grant_barrier(pct)

    def _grant_decay_barrier(self, op: OperatorUnit, pct: float,
                             secs: float) -> None:
        """授予**会持续衰减**的屏障（新约能天使技2「开火成瘾症」）。

        prts 该技能 `|备注=`：「获得的屏障均以**自身生命上限**为标准计算；屏障
        **每秒衰减量为：初始屏障量/30**；**重复获得此屏障时，重置屏障量与衰减
        速度**」。所以：

        * 量走 `grant_barrier` 的既有口径（`pct × 各自的生命上限`，取较大者）；
        * 衰减速率 = **这一次授予的量 ÷ `secs`**，每次授予都重算（"重置"）；
        * 与 `barrier_pct` 那条**分开两个字段**：那个由 `_deactivate` 在技能结束
          时清零，这个是自己按秒掉的，与技能何时结束无关。

        发给谁由调用方决定（她一开技就发给**自己**，偷到攻速时再发给**被偷的那位**
        ——「自身与其获得」）。
        """
        op.grant_barrier(pct)
        op.barrier_decay_per_sec = ((pct * op.max_hp) / secs) if secs > 0.0 else 0.0

    def _barrier_decay_tick(self, dt: float, t: float) -> None:
        """会持续衰减的屏障按秒掉（新约能天使技2：250% / 30 秒）。"""
        for op in self.operators:
            if op.barrier_decay_per_sec <= 0.0:
                continue
            op.barrier = max(0.0, op.barrier - op.barrier_decay_per_sec * dt)
            if op.barrier <= 0.0:
                op.barrier = 0.0
                op.barrier_decay_per_sec = 0.0

    def _bomb_radio_on_ammo(self, consumer: OperatorUnit, rounds: int) -> None:
        """天赋「火力电台」：**友方干员消耗弹药**时触发的自愈与轰炸。

        正文：「在场时，每当有友方干员的**弹药被消耗**就会回复自身 6% 生命值，
        并有 20%/25% 概率立即对**该干员攻击范围**的敌人召唤一次轰炸，造成相当于
        **自身**攻击力 105%…的物理溅射伤害」。

        prts `|备注=`（2026-09-18 取）补了四条正文没写、但决定怎么算的：

        ① 按**本轮消耗数量循环处理**治疗与轰炸概率（一次消耗多发就按发数触发）；
        ② 不论消耗数量，**每轮轰炸仅选取一次目标**，每次成功的概率判定都会增加
           一次本轮的轰炸（单轮多次轰炸之间间隔 0.1s）；
        ③ 轰炸半径 **1.3**，造成**预计算**的物理普通伤害；
        ④ 轰炸时**借用消耗者的攻击范围**，由新约能天使判断该范围内的轰炸目标
           （**始终使用默认索敌逻辑**）。

        实现与**如实记下的取舍**：

        * 自愈是**确定量**（每发 `hp_ratio` × 自身生命上限），直接累加；
        * 轰炸按**期望值**折（每发 `prob` 次），落点在"借来的范围"里按**默认索敌**
          选出的那一个目标身上——`_pick_targets` 就是本仓库的默认索敌；
        * **溅射半径 1.3 没做**：本仓库唯一的溅射实现是撼地者那条按格子判重叠的
          （半径 1.0），形状与判法都不是一回事，硬套会把两个机制搅在一起。
          于是只打选中的目标本人，这条差额记进 `docs/uncertainties.md`；
        * 0.1s 的多次轰炸间隔同样不建模（期望值口径下没有意义）。
        """
        for owner in self.operators:
            if owner is None or not owner.alive:
                continue
            t = find_bomb_radio(owner.talents)
            if t is None:
                continue
            heal_pct = float(t.value("hp_ratio", 0.0) or 0.0)
            if heal_pct > 0.0:
                owner.heal(owner.max_hp * heal_pct * rounds)
            scale = float(t.value("aoe_atk_scale", 0.0) or 0.0)
            prob = float(t.value("prob", 0.0) or 0.0)
            expected = prob * rounds
            if scale <= 0.0 or expected <= 0.0:
                continue
            picks = self._pick_targets(consumer, self._range_of(consumer), 1)
            if not picks:
                continue
            target = picks[0]
            dmg = resolve_damage(owner.current_atk(), scale=scale,
                                 damage_type="PHYSICAL",
                                 defense=target.defense,
                                 res=target.res)
            self._damage_enemy(target, dmg.final * expected, self._t,
                               "PHYSICAL", source=owner)

    def _activate(self, op: OperatorUnit, t: float, *, passive: bool = False) -> None:
        sk = op.skill
        if sk is None:
            return
        # 「刚连射」：技1 开技时若已有 **2 次充能**所需的技力，则**一次吃掉两层**、
        # 多打那 5 支 200%（PRTS `|备注=` 原文：「技能达到 4 级后，若在已有 2 次
        # 充能所需技力的情况下触发技能，焰狐龙梓兰会消耗 2 次充能所需的技力来
        # 释放技能」；博士 2026-09-18 裁定同此）。
        # **判据是开技那一刻的 `op.sp`**（扣之前），不是技能等级——等级只决定
        # 四段机制有没有，而技力够不够是每局的事。被动开技不扣技力，也就不吃。
        eff_now = sk.effects
        op.charge_extra_ready = False
        # 「每攻击 N 次后攻击目标数+1」的计数器**按开技清零**：它算的是
        # "本次技能开启动以来出手几次"，与 `op.hits`（本局总数）分开。
        op.trigger_hits = 0
        if not passive and eff_now.charge_arrows > 0:
            need = float(sk.sp_cost) * (1 + eff_now.charge_layers)
            if op.sp + 1e-9 >= need:
                op.charge_extra_ready = True
                op.charge_extra_arrows = eff_now.charge_arrows
                op.charge_extra_scale = eff_now.charge_scale
        if not passive:
            layers = 1 + (eff_now.charge_layers if op.charge_extra_ready else 0)
            op.sp = max(0.0, op.sp - float(sk.sp_cost) * layers)
        # 天赋「强击瓶专家」：**部署后首次开启技能时**，接下来 50 次攻击的攻击力
        # 倍率提升至 115%。判据是"本局的第几次开技"，而 `op.sp_charges` 在下面
        # 才自增，所以这里读到的 0 就是首次。每次开技都重置一遍也无妨——它只会
        # 在 == 0 时触发。
        if op.sp_charges == 0 and op.power_attack_count > 0:
            op.power_attack_left = op.power_attack_count
        # 技3「龙之箭」：开技只是**开始蓄力**，弹道要 3 秒上下才出（`_schedule_arrow`）。
        # `first` 判据同上面那条——`sp_charges` 还没自增，"0" 就是本局第一次开技，
        # 而首次的开启动画更长（备注点名是天赋1 改的动画）。
        if eff_now.pierce_step > 0.0:
            self._schedule_arrow(op, t, first=(op.sp_charges == 0), eff=eff_now)
        op.skill_active = True
        # 「第二次及以后使用」的取值：黑板用 `[second]` 变体给。怒潮凛冬技2
        # 「绝不罢休」——第 1 次 atk+90% / def+60% / 16 秒；第 2 次起
        # atk+180% / def+120%，且**持续时间无限**。
        #
        # `SkillEffects.with_variant` 早已写好（它的 docstring 就是拿本例当标准
        # 用例），解析层也一直把 `[second]` 收进 `variants`——但**没有任何地方
        # 调用它**，于是模拟器一直按第一次的 90% 算。而这恰恰是真作业用的技能。
        # 全库只有这一个技能带 `[second]`（已逐行核过 986 条 M3），判据写窄即可。
        #
        # `sp_charges` 是累计开启次数（见上方 `once_per_battle` 的用法），
        # 所以「本次是第 2 次及以后」= 自增**之前** `>= 1`。
        second_use = op.sp_charges >= 1
        op.sp_charges += 1
        if second_use and "second" in op.effects.variants:
            # `with_variant` 是**替换**语义（1.8 是 0.9 的两倍，相加会得 2.7，
            # 与描述"变为最初的两倍"不符）。它以 `op.effects` 为底做深拷贝，
            # 所以描述驱动的那一层（`effects_override`）不会被丢掉。
            op.effects_override = op.effects.with_variant("second")
        dur = sk.effective_duration
        if second_use and sk.infinite and dur is not None:
            # 描述是「第二次及以后使用时能力加成变为最初的两倍，**且持续时间
            # 无限**」——"无限"挂在这个从句里，所以 16 秒只是第一次的时长。
            # 不能用 `infinite` 单独判：它对第一次也为真。
            op.skill_timer = _INFINITE
        else:
            op.skill_timer = _INFINITE if dur is None else float(dur)
        op.ammo_left = int(sk.effects.ammo or 0)
        # 【闭锁】（泥岩技3）：开技先闭锁 `sleep` 秒——不能行动、不受伤、
        # 周围敌人减速，醒来那一帧再由 `_lock_tick` 补上晕眩。
        if sk.effects.lock_secs > 0.0:
            op.locked_timer = max(op.locked_timer, sk.effects.lock_secs)
        # 「立即偷取攻击范围内 1 名友方干员 X 点攻击速度」（新约能天使技2）。
        # **在弹药初始化之后**：偷到了就由 `_steal_aspd` 给它添那 5 发。
        if sk.effects.steal_aspd > 0.0:
            self._steal_aspd(op, sk.effects, t)
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
        # 屏障：「获得 N% 最大生命值的屏障，持续至技能结束」（电弧技1）。
        # 主语写「自身和召唤物」时，**同一份也发给主人的召唤物**——召唤物
        # 自己没有技能槽，不发下去它永远拿不到（`SkillEffects.affects_summons`）。
        if sk.effects.barrier_pct > 0.0:
            self._grant_barrier(op, sk.effects.barrier_pct,
                                to_summons=sk.effects.affects_summons)
        # 会**持续衰减**的屏障（新约能天使技2）：先给**她自己**那一份；
        # 「自身**与其**获得」的另一份在 `_steal_aspd` 偷到人时补给被偷的那位
        # ——那里才知道偷的是谁，放在这里要猜。
        if sk.effects.barrier_decay_pct > 0.0:
            self._grant_decay_barrier(op, sk.effects.barrier_decay_pct,
                                      sk.effects.barrier_decay_secs)
        # 回费技能（德克萨斯、桃金娘这一类）：开启时直接给费用
        gain_cost = sk.effects.buffs.get("cost", 0.0)
        # ⚠️ 「技能持续时间内**逐渐**获得」的那一族（可露希尔技1）**不许**在这里
        # 一次性给：一次性给一份、`_begin_cost_trickle` 再摊一份，就是**给双份**。
        # `cost` 一键多义（全表 59 条技能四种写法），闸门按正文关键词在解析侧
        # 定好（`SkillEffects.cost_suppress_immediate`），这里只照办。
        if gain_cost and not sk.effects.cost_suppress_immediate:
            self.cost = min(self.max_cost, self.cost + gain_cost)
        # 用过几次要在发放之前自增：技1 的「每使用过一次 +1」算的是**这一次**。
        op.skill_use_count += 1
        self._begin_cost_trickle(op)
        self.result.skill_activations += 1
        self._spawn_qi(op, t)
        self._apply_push(op, t)
        # 技能**自己**打的伤害（技3「无可抵挡」的五连锤击）：排一张时刻表，
        # 由 `_hammer_tick` 按固定间隔兑现。这一条与普攻循环完全无关——
        # 间隔不吃攻速，见 `battle/hammer.py`。
        self._schedule_hammer(op, t)
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
        # 偷来的攻速要还（「持续至技能结束或她离场」）。另一条路是她在技能
        # **中途倒下**——那一条不走这里，由 `_skill_tick` 每帧兜住。
        self._revert_steal(op)
        op.sp = 0.0
        # 击杀叠层清零：「持续至技能结束」。技能结束就要掉回原样，
        # 不能带到下一次开技能（阿米娅技2 整场只放一次，但机制上如此）。
        op.kill_stacks = 0
        op.slash_pending = False
        # 闪避也是"持续至技能结束"的一类，出技能就掉回去。
        op.dodge_phys = 0.0
        op.dodge_arts = 0.0
        # 屏障同理：「持续至技能结束」——描述写的就是这句。发下去的召唤物
        # 屏障一并清掉，否则技能结束后它还白扛着（那是"技能结束"没生效）。
        if sk is not None and sk.effects.barrier_pct > 0.0:
            op.barrier = 0.0
            if sk.effects.affects_summons:
                for sm in self.operators:
                    if sm.summon_of == op.char_id:
                        sm.barrier = 0.0
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

    @staticmethod
    def _cannot_clear(e: EnemyUnit) -> bool:
        """这个单位**有没有可能被清掉**——要么被打死，要么走到目标点。

        「既打不死、又不会离场」的单位清不掉：只要把它算进完成判据，
        这一局就永远结束不了（跑满时间上限、0 星）。目前只有怀黍离的天桩-甲
        满足，两条依据都写在数据里：

        * **打不死**：监测形态持有「无敌、不死」，落成 `always_invincible`
          （`unit.py` 里那个字段的正文来历就是这个）；激活状态会摘掉它，
          但那时甲会**每秒自损 1% 最大生命**，自己会死——所以照旧算数。
        * **不会离场**：它天赋第一句是「自缚」，模拟器给它的是一条**单点路线**
          （`route_length == 0`；`reached_end` 要求长度 > 0，单点路线永不判漏）。

        两个条件**同时**成立才算"清不掉"。只满足一个的不算：能走的无敌单位
        会自己走掉（照样能结束这一局），会死的自缚单位会被打死。
        """
        return (bool(getattr(e, "always_invincible", False))
                and float(getattr(e, "route_length", 0.0)) == 0.0)

    def run(self, max_time: float = 600.0) -> BattleResult:
        dt = 1.0 / self.fps
        t = 0.0
        res = self.result
        pending = sorted(self.deployments, key=lambda d: d.time)
        pending_summon = sorted(self.summon_deployments, key=lambda d: d.time)
        pending_device = sorted(self.device_deployments, key=lambda d: d.time)

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
            # 0. **费用回复**。必须排在部署**之前**：这一帧落地的干员，能不能
            #    付得起，取决于「到 t 为止攒了多少费」。放在帧尾的话，部署看到
            #    的是 t-dt 那一帧的池子——恰好差一个节拍，于是"刚好攒够"的
            #    落地（1-7 初始 10 费、1 秒回 1 点，拉普兰德 19 费正好第 9 秒
            #    攒够）会被冤枉地判成付不起，模拟器少放一个人。
            #    跳点次数不受本处挪动影响，所以总额不变，只是按时到账。
            self._cost_timer += dt
            if self._cost_timer >= self.cost_time:
                self._cost_timer -= self.cost_time
                self.cost = min(self.max_cost, self.cost + 1.0)
            # 1. 部署
            while pending and pending[0].time <= t:
                self._do_deploy(pending.pop(0), t)
            # 1b. 召唤物部署。排在干员之后：召唤者必须已经入场才谈得上归属。
            while pending_summon and pending_summon[0].time <= t:
                self._do_deploy_summon(pending_summon.pop(0), t)
            # 1c. **装置**部署。排在最后：它要花费用，而费用在同一帧里
            #     已经先被干员与召唤物分过一次（顺序固定 = 复现性有保证）。
            while pending_device and pending_device[0].time <= t:
                self._do_deploy_device(pending_device.pop(0), t)
            for use in [s for s in self.skill_uses if abs(s.time - t) < dt / 2]:
                op = self._alive_op_at(use.position)
                if op is not None:
                    op.skill_request = True
            for rt, cell in [r for r in self.retreats if abs(r[0] - t) < dt / 2]:
                op = self._alive_op_at(cell)
                if op is not None:
                    op.hp = 0
                    # **必须置 `retreated`**：`operator_deaths` 的判据是
                    # 「`not alive and not retreated`」，只清血条的话，玩家
                    # 主动撤退会被算成阵亡（`unit.py` 的字段注释写的就是
                    # 「结算时必须与阵亡分开」，此前这一路漏了）。
                    op.retreated = True
                    for e in list(op.blocking):
                        e.blocked_by = None
                    op.blocking.clear()

            # 1d. **召唤者退场 → 召唤物一并消失**（实机如此）。
            #     排在下面"离场时刻"**之前**，是为了让召唤物的离场时刻由那一处
            #     **统一记账**——分散到三处各写一遍必然漏一处（这条教训在再部署
            #     冷却上已经吃过一次）。
            #     `summon_of` 存的是召唤者的 `char_id`（不是名字）。
            gone = {o.char_id for o in self.operators
                    if not o.summon_of and (o.retreated or o.hp <= 0)}
            if gone:
                for sm in self.operators:
                    if sm.summon_of and sm.alive and sm.summon_of in gone:
                        # **置 `retreated` 而不是只清血条**：`operator_deaths`
                        # 的判据是「not alive and not retreated」，只清血条的话
                        # 每消失一个召唤物都会凭空记成一次**干员阵亡**。
                        sm.hp = 0.0
                        sm.retreated = True
                        self.result.summon_cascaded.append(
                            (t, sm.name, f"召唤者 {sm.summon_of} 已退场"))
                        if self.verbose:
                            self.result.log.append(
                                f"{t:7.1f}s  {sm.name} 随召唤者退场而消失")
            # 离场时刻：撤退 / 阵亡 / 技能强制退场（阿米娅技3）三个口子
            # **统一在这里记一次**。分散到三处各写一遍必然漏一处，
            # 而漏掉的那一处会让再部署冷却悄悄失效（不报错，只是不生效）。
            for op in self.operators:
                if op.left_at < 0.0 and (op.retreated or op.hp <= 0):
                    op.left_at = t
                    if self.verbose:
                        self.result.log.append(
                            f"{t:7.1f}s  {op.name} 离场"
                            f"（{'撤退/强制退场' if op.retreated else '阵亡'}），"
                            f"再部署冷却 {op.redeploy_time:g}s")

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
                # 【迟钝】的层表也在这里减——**逐层**各自计时（可露希尔技3）。
                e.tick_slow(dt)
                # 【束缚】与停顿一样拦移动，所以同样要在这里减——写进
                # `advance()` 里会永远减不动（那两条在开头就 return 了）。
                if e.root_timer > 0:
                    e.root_timer = max(0.0, e.root_timer - dt)
                if e.idle_timer > 0:
                    e.idle_timer = max(0.0, e.idle_timer - dt)
                if e.disarm_timer > 0:
                    e.disarm_timer = max(0.0, e.disarm_timer - dt)
                if e.stun_timer > 0:
                    e.stun_timer = max(0.0, e.stun_timer - dt)
                # 天赋「死亡拘审」的持续伤害：每 `dot_interval` 秒跳一次，
                # 单跳量 = 层数 × 每层每秒。**走累加器，不要用 `dot_timer`
                # 取模**——帧长不整除间隔时会漏跳或多跳，且不报错。
                if e.dot_timer > 0:
                    e.dot_timer = max(0.0, e.dot_timer - dt)
                    e.dot_accum += dt
                    while e.dot_accum >= e.dot_interval and e.dot_stacks > 0:
                        e.dot_accum -= e.dot_interval
                        self._damage_enemy(e, e.dot_stacks * e.dot_per_sec,
                                           t, DamageType.MAGIC)
                    if e.dot_timer <= 0.0:
                        # 时长走完就整体清掉，连层数一起——否则下次挂上时
                        # 会带着上一次的层数，白拿两层。
                        e.dot_stacks = 0
                        e.dot_accum = 0.0
                        e.dot_per_sec = 0.0
                # 【冻结】与【寒冷】也是时限状态，一起在这里减。
                # **必须在这里减而不是在 `advance()` 里**：冻结/停顿的敌人
                # 在 `advance()` 开头就直接返回了，写进去永远减不动。
                if e.freeze_timer > 0:
                    e.freeze_timer = max(0.0, e.freeze_timer - dt)
                if e.cold_timer > 0:
                    e.cold_timer = max(0.0, e.cold_timer - dt)
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
            # 天赋欠下的那次范围冻结（圣山的祝福）在这里兑现
            self._blessing_tick(t)
            self._qi_tick(dt, t)
            # 贯穿弹道（焰狐龙梓兰 技3）：到点生成 + 按距离分段结算
            self._arrow_tick(dt, t)
            # 天赋「翔虫机动」的限时攻击力加成到期收走
            self._mobility_tick(dt)
            # 技能自打的伤害：五连锤击按时刻表兑现（不吃攻速）
            self._hammer_tick(t)

            # 3.6 P3R：刷新倒地 → 全场总攻击装置
            self._p3r_tick(dt, t)

            # 3.7 关卡环境机制：田地/病害值（怀黍离）
            self._environment_tick(dt, t)

            # 3.8 装置：建成进度、田鼷进阻流阀范围的真伤、被拆后地形还原。
            #     排在环境之后：这一帧先按**还没变**的田地几何收完伤害，
            #     装置被拆导致的重划从下一帧起才影响结算（否则同一帧里
            #     "田地已经并回去、但伤害按并回去之后算"会让拆装置这件事
            #     反过来立刻减轻当秒的环境伤害）。
            #     与田地系统**解耦**：没有田地的图（或显式关掉环境）里，
            #     装置该挨的打、该还的地形照样要算。
            self._device_tick(dt, t)

            # 3.9 天桩链：装置 → 甲 → 乙 → 天标。紧跟装置之后，因为第一跳
            #     就是"装置召唤甲"，而甲的生命百分比读的是**本帧刚更新过**的
            #     病害值（排在 `_environment_tick` 之后）。
            self._pile_tick(dt, t)

            # 4. 阻挡
            self._update_blocking()

            # 5. 技能（要排在我方出手之前：刚攒满技力的那一帧得算数）
            # 4.9 特性（怪杰的生命流失）：与技能无关，所以排在技能之前、
            #     但同在"我方出手之前"这一簇里——本帧掉的血本帧就见效。
            self._trait_tick(dt)
            # 4.95「命中率 −X%」的场（阿斯卡纶技3 / 艾拉技1）：它按**位置**刷，
            #      且要在本帧我方出手、敌方出手之前都是最新的，所以放在这里。
            self._hitrate_tick(dt)
            # 4.96【闭锁】场（泥岩技3 的前 10 秒）：减速要排在 `_snow_tick`
            #      之后（那个每帧把 `speed_multiplier` 重置为 1.0），否则会被抹掉。
            self._lock_tick(dt, t)
            # 4.97「技能持续时间内逐渐获得部署费用」（可露希尔那一族）。
            #      排在这里而不是帧首的费用回复那一步：那是**自然回复**，
            #      这是**技能给费**，两者各有各的节奏，混在一起对不上账。
            self._cost_trickle_tick(dt, t)
            # 4.98 会**持续衰减**的屏障按秒掉（新约能天使技2 的 250% / 30 秒）。
            #      与技能结束时清零的那条屏障分开：它自己掉，不看技能死活。
            self._barrier_decay_tick(dt, t)
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

            # 7.2 **敌方技能出手**（怀黍离「玷 / 勿玷」的技能「污」）。
            #     与普攻分开：这一类敌人的天赋是「不进行远程普通攻击」，
            #     伤害全部来自技能（见 `_skill_attack_tick` 的正文来历）。
            self._skill_attack_tick(dt, t)

            # 7.5 敌人侧关卡机制（怀黍离）：移速增益的计时与解除、明识形态的
            #     清水判定与标记退场、以及**被击倒之后**那批一次性效果。
            #     排在两个出手之后：这一帧谁的出手把谁打倒了，这里就看得到。
            self._enemy_mech_tick(dt, t)

            # 8. 结算
            self._resolve(t)
            if self.life <= 0:
                res.won = False
                break
            # **"既打不死又不会离场"的单位不算在完成判据里。**
            #
            # 怀黍离的天桩-甲就是这种东西：监测形态持有「无敌、不死」
            # （`always_invincible`），而它天赋第一句是「自缚」——本模拟器给它的
            # 是一条**单点路线**（`route_length == 0`，`reached_end` 要求长度 > 0），
            # 所以它既不会被杀死、也永远走不到目标点。原先这里写的是"场上还有
            # 活着的敌人在就不算打完"，于是**凡是有天桩的关卡永远结束不了**：
            # 实测 act31side_03 全清 38 杀 0 漏、生命 3/3，只是天桩-甲还站在
            # 原地，一路跑到时间上限、判定成"失败 0 星"。后果直接落在解算上：
            # 所有候选都是 0 星 → 搜索永远搜不到三星方案 → TUI 的 [3] 解算
            # "无论选什么都是 0 条结果"（博士 2026-09-18 报的那个）。
            #
            # ⚠ 判据**不含** `owner_device`：甲进入激活状态后会同时摘掉无敌不死
            # （改成每秒自损 1% 最大生命，见 `_pile_parent_tick`），那时它是会死的、
            # 而且还在分散召唤天桩-乙——那一局**不许**收场，乙会漏、会扣命。
            # 用 `_cannot_clear` 而不是"是不是装置召唤的"，正是为了把这两种状态
            # 分开：清不掉的才忽略。
            if self._spawn_cursor >= len(self._spawns) and not any(
                    (e.alive and not e.leaked and not self._cannot_clear(e))
                    or e.pending_reborn
                    for e in self.enemies):
                res.won = True
                break

            t += dt

        left = [e for e in self.enemies if e.alive and not e.leaked]
        if not res.won and self.life > 0:
            # 走到这里只有两种可能：跑满时间上限，或者循环条件提前退出。
            # 两种情况都不是"打输了"，如实记下来，别让归因去猜。
            res.timed_out = True
            res.leftover_units = [(e.name, e.enemy_id, self._cannot_clear(e))
                                  for e in left]
        res.spawns_placed = self._spawn_cursor
        res.spawns_total = len(self._spawns)

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

    def _summons_alive(self, owner: str) -> int:
        """这名召唤者现在场上有几个自己的召唤物（含正在被阻挡的那些）。"""
        return sum(1 for o in self.operators
                   if o.summon_of == owner and o.alive)

    def _do_deploy_summon(self, d: "SummonDeployment", t: float) -> None:
        """放一个召唤物。放不下就**记录原因并跳过**，绝不静默少放。

        三处判据：
        ① 召唤者**必须在场**——不在场就没有归属，也拿不到天赋里的额度；
        ② 召唤者天赋必须给出额度——`find_summon_allowance` 取不到就说明
           这名干员压根不是召唤者，多半是调用方把 token_key 写错了；
        ③ 场上已有的召唤物个数不得达到**同时部署上限**。

        第四条随 `cost_mode` 而变：`strict` 下还要**付得起**，付不起就记进
        `summon_rejected` 并跳过（与部署干员同一道闸门）。
        """
        owner = None
        for op in self.operators:
            if op.char_id == d.owner and op.alive:
                owner = op
        if owner is None:
            self.result.summon_rejected.append(
                (t, d.token_key, f"召唤者 {d.owner or '（未指定）'} 不在场"))
            return

        allowance = find_summon_allowance(owner.talents)
        if allowance is None:
            self.result.summon_rejected.append(
                (t, d.token_key, f"{owner.name} 的天赋里没有召唤额度"))
            return

        have = self._summons_alive(d.owner)
        if have >= allowance.simultaneous:
            self.result.summon_rejected.append(
                (t, d.token_key,
                 f"已达同时部署上限 {allowance.simultaneous}"
                 f"（来源：{allowance.source}），场上有 {have} 个"))
            return

        unit = build_summon_unit(
            d, book=self.summon_book or SummonBook())
        if not self._affordable(unit.deploy_cost, t, f"召唤物「{unit.name}」"):
            self.result.summon_rejected.append(
                (t, d.token_key,
                 f"费用不足：需 {unit.deploy_cost}，当时只有 {self.cost:.0f}"))
            return
        self.cost = max(0.0, self.cost - unit.deploy_cost)
        self.operators.append(unit)
        # 主人的屏障技能正开着时，新放下的这个**当场拿到一份**——否则技能期间
        # 补一个召唤物就白补了（描述是「自身和召唤物……持续至技能结束」）。
        sk = owner.skill
        if (sk is not None and owner.skill_active
                and sk.effects.barrier_pct > 0.0
                and sk.effects.affects_summons):
            unit.grant_barrier(sk.effects.barrier_pct)
        self.result.summons_deployed += 1
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  召唤 {owner.name} 放下「{unit.name}」于 {d.position} "
                f"朝 {d.direction}（{unit.deploy_cost} 费，"
                f"场上 {have + 1}/{allowance.simultaneous}）")

    def _do_deploy_device(self, d, t: float) -> None:
        """放一个**装置**（玩家手动部署的阻流阀等）。放不下就记原因并跳过。

        判据四条，全是数据或账面上的：

        ① **额度**：关卡开局的 `predefines.tokenCards[].initialCnt` 加上
           `DeathPassive.` 击杀掉落的那一份，就是这一局手里的牌数。
           这正是「田鼷飞贼被击倒时予我方可部署装置」那条机制的落点——
           在此之前它只进账不花，等于没接（`DeathPassive.` 曾因此标 todo）。
        ② **费用**：装置也要花费用（阻流阀 5 费，取自角色表
           `attributesKeyFrames[0].data.cost`），走同一个 `_affordable` 闸门。
        ③ 那一格**不能已经有装置**（装置不叠放）。
        ④ 放下去后按 `BUILD_SECONDS`（3 秒）建成，建成前无敌
           （`DeviceUnit.build_left` / `building_invincible`）。

        ⚠ **地块改写发生在建成那一刻**，不是落下去那一刻：原文「3 秒建成，
        自身地块不再是田地、连片由此重划」。所以这里**不动** `farmland`，
        交给 `_device_tick` 在建成时 `sever()`。落下去就断田会让那 3 秒的
        田地划分提前变形。
        """
        from .devices import (BLOCKER_BUILD_FRACTION, BUILD_SECONDS, DeviceUnit,
                              device_cost, device_hp, make_deployed_device)

        key = d.device_key
        have = int(self.device_token_balance.get(key, 0))
        if have <= 0:
            self.result.device_deploy_rejected.append(
                (t, key, "没有可用的额度（关卡没给这张牌，也还没从击杀里掉到）"))
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  装置「{key}」放不下去：额度为 0 → **拒收**")
            return
        cell = (int(d.position[0]), int(d.position[1]))
        if any(x.alive and x.cell == cell for x in self._devices):
            self.result.device_deploy_rejected.append(
                (t, key, f"那一格 {cell} 已经有装置了"))
            return
        price = device_cost(key)
        if not self._affordable(price, t, f"装置「{key}」"):
            self.result.device_deploy_rejected.append(
                (t, key, f"费用不足：需 {price}，当时只有 {self.cost:.0f}"))
            return
        self.cost = max(0.0, self.cost - price)
        self.device_token_balance[key] = have - 1
        unit = DeviceUnit(make_deployed_device(key, cell, d.direction),
                          max_hp=device_hp(key))
        unit.build_left = BUILD_SECONDS
        unit.building_invincible = True
        unit.hp = unit.max_hp * BLOCKER_BUILD_FRACTION
        self._devices.append(unit)
        self.result.devices_deployed.append((t, key, cell))
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  部署装置「{unit.name}」于 {cell} 朝 {d.direction}"
                f"（{price} 费，额度剩 {have - 1}，{BUILD_SECONDS:g}s 建成）")

    def _affordable(self, price: int, t: float, who: str) -> bool:
        """这一手付得起吗？`cost_mode="legacy"` 下一律为真。

        付不起就**拒收并留痕**，不是把费用夹到 0 硬放下去——后者等于白送，
        而且送得毫无痕迹，复盘时看不出哪一手其实做不出来。
        """
        if self.cost_mode != "strict" or price <= self.cost:
            return True
        self.result.cost_denied.append((t, who, int(price), self.cost))
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {who} 落地需 {price} 费，当时只有 {self.cost:.0f} 费"
                f" → **拒收**（费用不足）")
        return False

    def _can_deploy_again(self, op: OperatorUnit, t: float) -> bool:
        """同一干员还能不能再放一个？`redeploy_mode="legacy"` 下一律为真。

        两条真实的规则，都在这里判：

        ① **同一干员不能同时在场上出现两个**。宽松口径下同一个 `char_id` 被两条
           `Deployment` 摆上两格时，模拟器会当成两个独立单位各打各的——那不是
           "部署了两次"，那是凭空多出一个干员来。
        ② **离场后要等再部署冷却**，长度取 `op.redeploy_time`（默认 70 秒；
           快活类干员在数据里是 20 秒）。三个离场口子（撤退 / 阵亡 / 技能强制
           退场）统一看 `left_at`，不各判各的。

        冷却只跟**同一个 `char_id`** 有关：阿米娅的两种形态是两个 `char_id`，
        互不牵连——这一条不能按名字判。
        """
        if self.redeploy_mode != "strict":
            return True
        same = [o for o in self.operators if o.char_id == op.char_id]
        for o in same:
            if o.alive:
                self._reject_deploy(t, op, f"{o.name} 已在场，同一干员不能同时"
                                          f"部署两个（现有位置 {o.position}）")
                return False
        last = max((o.left_at for o in same if o.left_at >= 0.0), default=None)
        if last is not None and t < last + op.redeploy_time:
            self._reject_deploy(
                t, op, f"{op.name} 再部署冷却中：{last:.1f}s 离场，还要等 "
                       f"{last + op.redeploy_time - t:.1f}s"
                       f"（共 {op.redeploy_time:g}s）")
            return False
        return True

    def _reject_deploy(self, t: float, op: OperatorUnit, why: str) -> None:
        """规则拒收：留痕，绝不静默少放一个。"""
        self.result.deploy_rejected.append((t, op.name or op.char_id, why))
        if self.verbose:
            self.result.log.append(f"{t:7.1f}s  {op.name} 落地被拒：{why}")

    def _do_deploy(self, d: Deployment, t: float) -> None:
        op = d.operator
        if not self._can_deploy_again(op, t):
            return
        if not self._affordable(op.deploy_cost, t, op.name or op.char_id):
            return
        op.position = d.position
        op.direction = d.direction
        op.auto_skill = d.auto_skill
        op.talents = list(d.talents or [])
        self._attach_skill(op, d)
        self.operators.append(op)
        self._mobility_on_deploy(op, d, t)

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
        # 天赋：圣山的祝福（圣聆初雪天赋1）
        #
        # 三个数**在部署时一次读进来**，而不是每次受伤再去翻天赋表：
        # 前者是一次解析，后者是每帧每敌人都要遍历天赋，而且一旦天赋对象
        # 在场上被改（换形态之类）会出现"半场换了规则"的怪事。
        #
        # 没这条天赋时三个数都是 0，`take()` 里的免死判据写的是
        # `blessing_save > 0`，所以**不会误触发**。
        bless = find_blessing(op.talents)
        if bless is not None:
            op.blessing_save = bless.value("c2e_freeze", 0.0)
            op.blessing_self_freeze = bless.value("freeze", 0.0)
            op.blessing_cold = bless.value("cold", 0.0)
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
        # 天赋：全场光环。三种语义（见 `TeamAura` 的类文档）：
        # 「青色怒火」= 常驻 + 主人开技能时加倍；「万众巨潮」= **只在技能期间
        # 生效**，且对【乌萨斯学生自治团】翻倍；「特种作战策略」= **按职业**发，
        # 只给【重装】（`profession == "TANK"`），常驻、不吃倍率。
        # 前两种此前都完全没接。注意 `scale_bonus` 与青色怒火的 `talent_scale`
        # 是两个键，别互相当别名用；`profession`（职业）与 `faction`（阵营）
        # 也是两个量，别混。
        aura = find_team_aura(op.talents)
        if aura is not None:
            if aura.name == FACTION_AURA_NAME:
                self.team_auras.append(TeamAura(
                    owner=op.name,
                    atk_pct=aura.value("atk", 0.0),
                    def_pct=aura.value("def", 0.0),
                    operator=op,
                    skill_only=True,
                    faction=STUDENT_TEAM,
                    faction_scale=aura.value("scale_bonus", 2.0),
                ))
            else:
                self.team_auras.append(TeamAura(
                    owner=op.name,
                    atk_pct=aura.value("atk", 0.0),
                    def_pct=aura.value("def", 0.0),
                    operator=op,
                ))
            self._refresh_auras()
        # 天赋：**按职业**发的全场光环（星熊「特种作战策略」）。
        # 与上面那条是并列的、不是同一件事：同一名干员可能两者都有。
        class_aura = find_class_aura(op.talents)
        if class_aura is not None:
            self.team_auras.append(TeamAura(
                owner=op.name,
                atk_pct=class_aura.value("atk", 0.0),
                def_pct=class_aura.value("def", 0.0),
                operator=op,
                profession=CLASS_AURA_TALENTS[class_aura.name],
            ))
            self._refresh_auras()
        # 天赋：「**携带弹药类技能**的干员攻击力 +9%，对【拉特兰】干员的效果
        # **翻倍**」（新约能天使「铳弹协约」）。按人筛（`ammo_skill_only`）＋
        # 按势力翻倍（`nation_double`）——与上面两条都不重：那条按职业发、
        # 那条按阵营名单翻倍，这条按"装备的是不是弹药技能"筛。
        # `mult`（2.0）就是这个翻倍倍率。
        covenant = find_ammo_covenant(op.talents)
        if covenant is not None:
            self.team_auras.append(TeamAura(
                owner=op.name,
                atk_pct=covenant.value("atk", 0.0),
                def_pct=covenant.value("def", 0.0),
                operator=op,
                double_scale=covenant.value("mult", 2.0),
                ammo_skill_only=True,
                nation_double=LATERANO_NATION,
            ))
            self._refresh_auras()
        # 天赋：**常驻的伤害抵挡**（星熊「战术装甲」）。落到**独立字段**上——
        # 不能塞进 `op.dodge_phys`：那个由技能开关写，`_deactivate` 会清零，
        # 于是星熊一开一关技能抵挡就没了，而且**不报错**。
        block = find_damage_block(op.talents)
        if block is not None:
            d = block.value("prob", 0.0)
            op.talent_dodge_phys = d
            op.talent_dodge_arts = d
        # 天赋「天使的祝福」（能天使）：**自身** +6% 攻击、+10% 生命上限。
        # 「随机友方」那半**未做**（等裁定，见 docs/uncertainties.md）——
        # 所以这条天赋只算做了一半。自身那半借光环通道，self_only 只发自己。
        bless = find_angel_blessing(op.talents)
        if bless is not None:
            self.team_auras.append(TeamAura(
                owner=op.name,
                atk_pct=bless.value("atk", 0.0),
                def_pct=0.0,
                operator=op,
                self_only=True,
            ))
            self._refresh_auras()
            op.apply_max_hp_bonus(bless.value("max_hp", 0.0))
        # 天赋「极限调度」（可露希尔）：【罗德岛】干员攻击力 +4%。
        # **同句的「部署费用下限 -3」不在战斗层**（属名册/费用规则），未做——
        # 所以这条天赋只算做了一半。
        dispatch = find_limit_dispatch(op.talents)
        if dispatch is not None:
            self.team_auras.append(TeamAura(
                owner=op.name,
                atk_pct=dispatch.value("atk", 0.0),
                def_pct=0.0,
                operator=op,
                faction_only=RHODES_NATION,
            ))
            self._refresh_auras()
        # 地形条件：**周围四格有高台**（阿斯卡纶「噬光残影」额外 +6 攻速）。
        # 伏击客不移动，判一次就定死；判据用 `is_highland()`——`tile_wall`
        # 与 `tile_forbidden` 都是高台（后者不可站人，但仍是高台）。
        px, py = op.position
        mp = self.stage.map
        op.high_ground_neighbor = any(
            mp.tile(px + dx, py + dy).is_highland
            for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)))
        if self.verbose:
            sk = f" 带技能「{op.skill.name}」" if op.skill is not None else ""
            tal = "、".join(f"「{x.name}」" for x in op.talents)
            tal = f" 天赋 {tal}" if tal else ""
            self.result.log.append(
                f"{t:7.1f}s  部署 {op.name} 于 {d.position} 朝 {d.direction}{sk}{tal}")

    def _refresh_auras(self) -> None:
        """把全场光环的当前数值刷到每个干员身上。

        每帧做一次，因为「光环主人开技能期间效果加倍」是随时间变的。
        多个光环**相加**（目前只有「青色怒火」与「万众巨潮」两个来源）。

        **按目标逐个算**，不能先算一份再刷给所有人：万众巨潮对
        【乌萨斯学生自治团】翻倍、对其他干员不翻，取值因人而异。
        """
        for op in self.operators:
            atk = def_ = 0.0
            for a in self.team_auras:
                x, y = a.current(op)
                atk += x
                def_ += y
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
            # 【倒地】不可阻挡；飞行单位任何地面干员都挡不住；
            # 天桩-甲的天赋「不可阻挡」是**常驻**的，同样不占阻挡位。
            if (e.hp <= 0 or e.leaked or e.off_map or e.down or e.unblockable
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
        """目标选择：先打自己挡住的，再打离防守点最近的（**嘲讽等级高的优先**）。

        返回最多 `n` 个——`n > 1` 对应技能里的「同时攻击 N 个目标」。

        与 `_update_blocking` 同理，`e.alive` 这类 property 在此就地展开
        （一场 1-7 调 6359 次、每次扫 41 个敌人）。`EnemyUnit` 的 `alive`
        就是 `hp > 0`，没有覆写。

        排序键前面加了 `taunt_level`：绝大多数敌人是 0（不影响任何现有行为），
        负数才是「**非首要目标**」——身上的天标是 −1，干员能打到它时也排在
        所有正常敌人之后。这一条同时是"它不会把火力从甲/乙身上吸走"的保证。
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
        rest.sort(key=lambda e: (-e.taunt_level, -e.progress))
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

    def _apply_dot(self, target: EnemyUnit, op: OperatorUnit, tal) -> None:
        """给目标续一层天赋「死亡拘审」。

        **续层，不是重挂**——三件事都要做，缺一条就不是「效果叠加三层」：
        层数 +1 并封顶、剩余秒数重置为满、每秒伤害按**本次出手**的攻击力
        快照刷新。

        **`dot_accum` 故意不重置**：它是"离下一跳还差多少"的累加器，不是
        状态时长。攻击频率一旦快过 1 秒，每挂一层就清空累加器的话，
        **一跳都不会发生**——而且不报错，只是伤害静静地少掉。
        """
        ratio = tal.value("atk_ratio", 0.0)
        if ratio <= 0:
            return
        top = int(tal.value("max_stack_cnt", 1.0) or 1)
        target.dot_stacks = min(target.dot_stacks + 1, max(top, 1))
        target.dot_timer = tal.value("debuff_duration", 0.0)
        target.dot_per_sec = op.current_atk() * ratio
        step = tal.value("interval", 1.0)
        target.dot_interval = step if step and step > 0 else 1.0

    def _trait_splash(self, op: OperatorUnit, target: EnemyUnit,
                      power: float, t: float) -> None:
        """职业特性溅射 + 天赋「汹涌怒火」的高台溅射。

        依据与几何全在 `battle/traits.py` 的模块文档里（prts.wiki 的原文 +
        撼地者四位共用的特性黑板）。这里只说三条实现上的事：

        1. **圆心取主目标的连续坐标**，不是它的格心。特性溅射走的是
           **重叠判定**（半径圆盖到哪些格），圆心在格内挪半格，斜邻格的
           取舍就会变——守卫里有 `(0.5, -0.5)` 那一例（12 格，且不对称）。
        2. **主目标自己不吃这一份**：正文写的是「目标**周围的其他**敌人」。
           天赋的 1.24 也只乘溅射，不乘主目标（wiki 备注明写「不对特性主目标
           生效」），所以主目标那一下仍是它自己算出来的伤害，不在这里改。
        3. **高台溅射是另一套几何**：由被溅射到的每个高台，对「它自己周围
           四格 + 本格」（`cross_cells`，格子判定）里的**地面**敌人再打一次。
           这句里的「周围四格」正是 `x-5` 那个范围码，与上面的半径圆
           不能互相顶替——照抄任一种到另一段都会错，且错得不显眼。
        """
        cells = splash_tiles(target.position, op.splash_radius)
        if not cells:
            return
        scale = op.splash_scale * op.splash_damage_scale
        for e in self.enemies:
            if e is target or not e.alive or e.leaked:
                continue
            if e.cell() not in cells:
                continue
            dmg = resolve_damage(power, damage_type="PHYSICAL", scale=scale,
                                 defense=e.defense, res=e.res)
            self._damage_enemy(e, dmg.final, t, "PHYSICAL", source=op)
        if op.highland_splash_scale > 0.0:
            triggered = self._highland_splash(op, cells, power, t)
            self._highland_sp(op, triggered, t)

    def _highland_sp(self, op: OperatorUnit, triggered: int, t: float) -> None:
        """「每次有高台触发第一天赋的效果时，获得 N 点技力」（怒潮凛冬技2）。

        三个口径，都得说清，否则这条要么不触发、要么回多了：

        1. **它是常驻的**。这句写在技2 正文的「**被动效果**」段里，不在
           「自动开启」段——所以技能没开时照样回，只要这个技能被装配上。
           把技能黑板里的键一律当成"只在技能期间生效"会漏掉整整一半。
        2. **逐高台计、不逐次出手计**：一次出手触发 k 个高台就回 N × k。
           所以 `_highland_splash` 的返回值是**计数**而不是布尔。
        3. **技能开启期间不回**——沿用本项目已有的那条口径（见
           `_operators_attack` 里「攻击回复的技力按出手算」与天赋「情绪吸收」
           两处同样的判断）。「技能期间 SP 条不涨」本身仍是**未证实假设**，
           记在 `docs/uncertainties.md`；本条与它**共用同一个假设**，
           不另立一套，免得同一个游戏规则在仓库里有两种说法。
        """
        sk = op.skill
        if sk is None or triggered <= 0 or op.skill_active:
            return
        per = float(sk.blackboard.get("sp_per_highland") or 0.0)
        if per <= 0.0:
            return
        before = op.sp
        op.sp = min(float(sk.sp_cost), op.sp + per * triggered)
        if self.verbose and op.sp > before:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 高台触发第一天赋 ×{triggered} → "
                f"技力 +{op.sp - before:g}（{op.sp:g}/{sk.sp_cost:g}）")

    def _highland_splash(self, op: OperatorUnit, cells: set, power: float,
                         t: float, *, bonus: float = 1.0,
                         root: float = 0.0) -> int:
        """天赋「汹涌怒火」的高台那一半，返回**触发的高台数**。

        返回值是留给技能 1/2 的 `sp_per_highland` 的（「每次有高台触发第一
        天赋的效果时，获得 1 点技力」）——那一半属于技能层，等技能 1/2 接线
        时再由调用方消费。

        **闸门放在这里、不放在调用方**：`highland_splash_scale <= 0` 时整段
        静默返回 0（连计数都不给）。放在调用方过一版的反例是"计数照样 +1、
        伤害却是 0"——那种半开状态在接 `sp_per_highland` 时会变成凭空的技力。

        「地面敌人」按 `is_flying` 排除空中单位，依据是天赋正文里那两个字
        （「所有**地面**敌人」）。这与特性溅射本身不同：那句只写「其他敌人」，
        没有地面限定，所以那一层不排除空中。

        `bonus` 乘在高台溅射倍率上（技3 的 `splash_atk_scale_bonus` = 3.5）；
        `root` > 0 时控制效果从【停顿】**替换**为【束缚】并取该秒数
        （技3 的 `unmovable` = 2.0）。两者都只由技3 那条路传进来。
        """
        if op.highland_splash_scale <= 0.0:
            return 0
        m = self.stage.map
        triggered = 0
        for cell in cells:
            if not m.inside(*cell) or not m.tile(*cell).is_highland:
                continue
            triggered += 1
            victims = [e for e in self.enemies
                       if e.alive and not e.leaked and not e.is_flying
                       and e.cell() in cross_cells(cell)]
            for e in victims:
                dmg = resolve_damage(power, damage_type="PHYSICAL",
                                     scale=op.highland_splash_scale * bonus,
                                     defense=e.defense, res=e.res)
                self._damage_enemy(e, dmg.final, t, "PHYSICAL", source=op)
                if root > 0.0:
                    # 技3「控制效果**变为** 2 秒【束缚】」——是替换不是叠加，
                    # 所以这一支只挂 root，不碰 sluggish。
                    e.root_timer = max(e.root_timer, root)
                elif op.highland_splash_sluggish > 0.0:
                    e.sluggish_timer = max(e.sluggish_timer,
                                           op.highland_splash_sluggish)
        return triggered

    # ------------------------------------------------ 技能自打的伤害（技3）

    def _schedule_hammer(self, op: OperatorUnit, t: float) -> None:
        """给「无可抵挡」排一轮五连锤击的时刻表。

        首击**即刻**（手动触发的技能，触发那一刻就落第一锤），此后每
        `HAMMER_INTERVAL` 一次。间隔写进**时刻表**而不是"每帧判一个计时器"，
        是为了让"不吃攻速"这件事在结构上就成立——攻速那条路只在普攻循环里。
        """
        sk = op.skill
        if sk is None:
            return
        strike = read_hammer(sk.blackboard)
        if strike is None:
            return
        op.hammer = strike
        op.hammer_step = 0
        op.hammer_pending = [t + i * HAMMER_INTERVAL for i in range(HAMMER_HITS)]
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 起手五连锤击"
                f"（间隔 {HAMMER_INTERVAL:g}s，不受攻速影响）")

    def _hammer_tick(self, t: float) -> None:
        """兑现到点的锤击。每帧一次，与其它 `*_tick` 同处（推进之后）。"""
        for op in self.operators:
            if not op.hammer_pending:
                continue
            if not op.alive or op.retreated:
                # 中途退场/阵亡：剩下的锤子不落，也不记账。
                op.hammer_pending.clear()
                op.hammer = None
                continue
            while op.hammer_pending and op.hammer_pending[0] <= t:
                op.hammer_pending.pop(0)
                self._hammer_strike(op, t)

    def _hammer_strike(self, op: OperatorUnit, t: float) -> None:
        """落下第 `op.hammer_step` 击。"""
        st = op.hammer
        if st is None:
            return
        fx, fy = op.facing
        # 锤击中心 = **正前方 1.0 距离位置**（不是格心，也不是"前方那一格的
        # 格心"）——与特性溅射同属重叠判定，圆心偏半格会改变斜邻格的取舍。
        center = (op.position[0] + fx * 1.0, op.position[1] + fy * 1.0)
        # 攻击力按 `current_atk()` 的**同一个括号**算，但不用它本身：
        # 本技能在数据里 duration = 0，"开启中"只持续一帧，而五锤要跨 7.2 秒
        # ——拿"这一帧开没开"去决定加不加本技能的加成，必然一半对一半错。
        # 所以裸攻击力 + 全场光环（那部分与开不开技能无关），再加上本技能的
        # `atk_base` 与逐击累加的 `atk_step`：三者同属"攻击力+X%"，**相加**，
        # 最后再由 `st.atk_scale` 乘一次（技能倍率只在 resolve_damage 那一处乘，
        # 2026-09-18 裁定）。
        # （先前的写法用 `current_atk() × atk_multiplier()`：那一版 `current_atk()`
        # 自带 `atk_scale`，于是第一锤被重复计成 4.8 倍——守卫里"五击逐一对账"
        # 正是为抓这类错。）
        buff = st.atk_pct + st.atk_step * op.hammer_step + op.aura_atk_pct
        power = op.atk * (1.0 + buff)
        cells = splash_tiles(center, st.splash_radius)
        main = self._hammer_main_target(center)
        if main is not None:
            dmg = resolve_damage(power, damage_type="PHYSICAL",
                                 scale=st.atk_scale,
                                 defense=main.defense, res=main.res)
            self._damage_enemy(main, dmg.final, t, "PHYSICAL", source=op)
        # 这一锤**也是攻击**，所以「其他敌人吃 50%×1.24」照样生效，
        # 只是半径按技能正文的"溅射范围更大"取 1.5（`st.splash_radius`）。
        scale = op.splash_scale * op.splash_damage_scale
        if scale > 0.0:
            for e in self.enemies:
                if e is main or not e.alive or e.leaked:
                    continue
                if e.cell() not in cells:
                    continue
                dmg = resolve_damage(power, damage_type="PHYSICAL", scale=scale,
                                     defense=e.defense, res=e.res)
                self._damage_enemy(e, dmg.final, t, "PHYSICAL", source=op)
        if op.highland_splash_scale > 0.0:
            triggered = self._highland_splash(op, cells, power, t,
                                              bonus=st.highland_bonus,
                                              root=st.root)
            self._highland_sp(op, triggered, t)
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {op.name} 第 {op.hammer_step + 1} 锤"
                f"（攻击力 ×{1.0 + buff:,.2f}，单次伤害 {power * st.atk_scale:,.0f}）")
        op.hammer_step += 1
        if op.hammer_step >= st.hits:
            op.hammer_pending.clear()
            op.hammer = None

    def _hammer_main_target(self, center: tuple[float, float]) -> "EnemyUnit | None":
        """正前方那一格里的一个单位（wiki：会尝试选择前方 1 格的一个单位）。

        **挑不到不是异常**——备注明写"通常情况下锤击不存在主目标"：这时这一锤
        只剩溅射，主目标那一份没人吃。

        挑法取**进度最大**的那一个，与普攻索敌同一口径（`_pick_targets` 也是
        这个键），免得同一格里有两只时两处给出不同的答案。
        """
        cell = (int(round(center[0])), int(round(center[1])))
        pool = [e for e in self.enemies
                if e.alive and not e.leaked and e.cell() == cell]
        if not pool:
            return None
        pool.sort(key=lambda e: e.progress, reverse=True)
        return pool[0]

    def _operators_attack(self, dt: float, t: float) -> None:
        for op in self.operators:
            if not op.alive:
                continue
            # 技能结束后自身晕眩期间不出手（阿米娅技2 那类的代价）
            if op.stun_timer > 0:
                continue
            # 自身【冻结】期间同样出不了手（冻结 = 缴械）。
            # **不能拿 stun_timer 顶替**：晕眩还会中断阻挡，冻结不会——
            # 用晕眩顶替会让她在冻结那 4 秒里连阻挡一并丢掉，那是另一回事。
            if op.freeze_timer > 0:
                continue
            # 【闭锁】期间不能行动（泥岩技3 的前 10 秒）。同样**不拿晕眩顶替**：
            # prts 备注写明那是「闭锁（非无法行动）」，而且是**反制**眩晕的。
            if op.locked_timer > 0:
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
            # 「每攻击 N 次后攻击目标数+1」：**在选完目标之后**才自增，所以第 9
            # 次出手打的是旧的个数、第 10 次才是多出来的那个——正文写的是
            # 「每攻击 9 次**后**」，顺序就是这个意思。
            op.trigger_hits += 1
            # 「每次攻击时获得 X 点部署费用」（`cost_attack_add`）。可露希尔技3
            # 这个键在 M3 是 0.0，所以这一支**在她身上是空转**——但零值也走
            # 同一条路：不然将来真出现非零值时，这条通道会静默失效。
            if eff is not None and eff.cost_per_attack > 0.0:
                self.cost = min(self.max_cost, self.cost + eff.cost_per_attack)

            scale = skill_scale
            hits = eff.hit_count if eff is not None else 1
            # 「刚连射」：另一次出手，箭数与倍率都另算（她 4 支 160% ＋ 5 支 200%）。
            # 与"末击加倍"分开：末击是同一次连击序列的最后一笔，这是**多花一层
            # 充能换来的另一段**，所以它整段换倍率、且落在最后 5 笔上。
            extra_hits = 0
            extra_scale = 0.0
            if (eff is not None and op.charge_extra_ready
                    and op.charge_extra_arrows > 0
                    and abs(skill_scale - 1.0) > 1e-9):
                extra_hits = op.charge_extra_arrows
                extra_scale = op.charge_extra_scale
                hits += extra_hits
                # 一次性：这一段出手过去就不再算，免得后续普攻也带上。
                op.charge_extra_ready = False
            # 普攻连击（焰狐龙梓兰的隐藏天赋：普通攻击为三连击、每击 100%，
            # **计算防御/法抗之后**再 ×33.3%）。只在**这一次出手是普攻**时生效：
            # 技能自己写了攻击倍率就是技能攻击（她技1 的 4 支、技2 的 13 笔
            # 走 `eff.hit_count`），不能叠。
            # 「是不是普攻」的判据与上面 `deals` 同一套写法：**看技能有没有
            # 改写这一击的攻击倍率**，不看技能开没开——她的技2 是+buff 型、
            # 技1 是改攻击型，两者在这一点上不同。
            combo_hits = 1
            combo_dmg_scale = 1.0
            if op.combo_hits > 1 and abs(skill_scale - 1.0) < 1e-9:
                combo_hits = op.combo_hits
                combo_dmg_scale = op.combo_damage_scale
                hits = combo_hits
                scale = op.combo_hit_scale
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
            # 天赋「强击瓶专家」：接下来 N 次**攻击**（攻击动作 = 一轮，不是箭矢）
            # 的攻击力倍率提升。备注写明"于**弹道脱手前**对当次连击的所有弹道
            # 生效"⇒ 乘在这一轮的全部箭矢上，整轮只扣一层。
            if op.power_attack_left > 0:
                power *= op.power_attack_scale
                # 层数按**轮**扣，而一次出手可能代表多轮：技2 是"三轮齐射 ＋
                # 落地点射"（备注把这四段各算一轮），技1 的刚连射是另一次。
                # 不这么算的话，技2 一次只扣一层——技能放四次就差 12 层。
                rounds = 1
                if eff is not None:
                    if len(eff.volley_arrows) > 1:
                        rounds += len(eff.volley_arrows) - 1
                    if eff.landing_scale:
                        rounds += 1
                    if extra_hits:
                        rounds += 1
                op.power_attack_left = max(0, op.power_attack_left - rounds)

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
                    if extra_hits and i >= hits - extra_hits:
                        hit_scale = extra_scale
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
                    # 普攻连击的 `combo_dmg_scale` **乘在这里**（`dmg.final` 之后）：
                    # 备注写的是「计算防御/法抗后 ×33.3%」，不是倍率菜单里的一项。
                    dealt = self._damage_enemy(target, dmg.final * combo_dmg_scale,
                                               t, used_type, source=op)
                    # 技能附带的【停顿】：不能移动，但照样能开火
                    if eff is not None and eff.control.get("sluggish"):
                        target.sluggish_timer = max(
                            target.sluggish_timer, eff.control["sluggish"])
                    # 技能附带的【迟钝】（可露希尔技3「Q.E.D.」）：**每命中一次
                    # 加一层**，每层各自计时、叠到 `slow_down_max` 封顶。它与
                    # 停顿是两个量，所以走独立的层表，不碰 `sluggish_timer`。
                    if eff is not None and eff.slow_per_stack > 0.0:
                        target.apply_slow(eff.slow_per_stack, eff.slow_max,
                                          eff.slow_time)
                    # 天赋「死亡拘审」（阿斯卡纶）：**每次攻击**给目标续一层
                    # 持续法术伤害。与技能无关，所以不看 `eff`。
                    # `op.talents` 至多三个，逐次扫的开销可以忽略；换来的是
                    # 快照取的是**这一次出手**的攻击力。
                    dot_tal = find_dot_on_hit(op.talents)
                    if dot_tal is not None:
                        self._apply_dot(target, op, dot_tal)
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

                # 特性溅射：**每次出手、每个主目标各一次**，中心是这一击的落点
                # （主目标的连续坐标）。放在连击循环**外面**——一次出手打 N 段
                # 是同一击，溅射不该结算 N 遍。
                # **不判主目标死活**：把主目标打下场的那一击照样砸在地上，
                # 旁边的敌人一样要吃这 50%——早先写过的 `target.alive` 守卫
                # 会把"击杀旁边就少溅一次"这种错悄悄埋进去。
                if op.splash_radius > 0.0:
                    self._trait_splash(op, target, power, t)

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
                # 「火力电台」挂在**弹药被消耗**这一刻（正文的条件就是它）。
                # 耗了几发就传几发：prts 备注①「根据本轮消耗数量循环处理」。
                self._bomb_radio_on_ammo(op, 1)

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
            if e.frozen or e.down or e.stun_timer > 0:
                # 冻结 / 倒地 / 晕眩的敌人不能攻击；计时器也不该偷偷攒着
                continue
            if e.idle_timer > 0 or e.disarm_timer > 0:
                # 【待机】/【缴械】期间不能出手（待机还额外不能移动，见 advance）
                continue
            if e.skill_atk_no_normal:
                # 天赋「不进行远程普通攻击」：这一类敌人的伤害**全部**走技能，
                # 普攻那一路整个关掉（免得将来谁给它补一个射程就双份出手）。
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
            # 「命中率 −X%」的折扣：**乘在最终伤害上**，不是乘在攻击力上。
            # 命中率是"这一击整个打空"的概率，所以是整笔的期望折扣；乘到
            # `e.atk` 上会先减防御再折扣，与"打空"不是一回事（高防目标能差出
            # 成倍），这点与 `resolve_damage` 里 `dodge_*` 的折法一致。
            hit_scale = self._hitrate_factor(e)
            # 明识形态的普攻是 **2 连击**（原文「自身普通攻击变为2连击」）。
            # 逐段结算：两段的防御/法抗各减一次。把 atk 乘 2 再打一次会
            # 少减一次防御，对高防目标能差出成倍的伤害。
            for _seg in range(max(1, int(getattr(e, "attack_times", 1) or 1))):
                dealt += op.take(resolve_damage(
                    e.atk, damage_type=e.attack_type,
                    defense=op.current_defense(), res=op.current_res(),
                    # 闪避走期望值法：把最终伤害乘 `(1 − 闪避率)`，不掷骰。
                    # 掷骰会让同一份作业每次跑出不同结果，搜索与回归都不可复现。
                    dodge_phys=op.dodge_phys + op.talent_dodge_phys,
                dodge_arts=op.dodge_arts + op.talent_dodge_arts,
                ).final * hit_scale)
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
                        bonus, damage_type=DamageType.MAGIC,
                        defense=0.0, res=op.current_res(),
                        dodge_phys=op.dodge_phys + op.talent_dodge_phys,
                dodge_arts=op.dodge_arts + op.talent_dodge_arts,
                    ).final * hit_scale)
            # 受击回复的技力
            if dealt > 0 and op.skill is not None and not op.skill.is_passive \
                    and not op.skill_active:
                gain = op.skill.sp_per_hit()
                if gain:
                    op.sp = min(op.skill.sp_cost, op.sp + gain)

    def _skill_attack_tick(self, dt: float, t: float) -> None:
        """敌方**技能出手**：怀黍离「玷 / 勿玷」的技能「污」。

        【正文来历】prts 图鉴「玷 / 勿玷」天赋与技能 0 原文：

        > 天赋：**不进行远程普通攻击**
        > 技能0「污」（初始 7）：攻击场上**1 名部署于地面**的我方单位，
        > 对**目标及其周围 4 格**的单位造成**攻击力 100% 的物理伤害**；
        > 自身位于病害值 > 0 的田地地块时，当次攻击**额外附加攻击力 80% 的
        > 法术普通伤害**，且**令目标地块病害值 +5**；※此技能不可沉默

        【哪一半是结构化、哪一半是正文】见 `gamedata/enemy.py::skill_attack_fields`：
        `atk_scale_magic`（0.8，ex04 四星档被 rune `enemy_skill_blackb_mul`
        乘成 **1.04**）与 `value`（+5）是黑板里的数；1 名 / 地面 / 十字 /
        100% / 不做普攻五件事只在正文里，写死在 `PROSE_SKILL_ATTACK`。

        【三处按项目口径收口的】

        1. **「全图」= 不看距离**：`rangeRadius` 是 −1（正是"不进行远程普攻"
           的后果），所以挑目标时**不限射程**，按既有的敌方索敌规则取
           **最后部署的那一名地面干员**（见 `_enemy_target` 的说明）。
        2. **「部署于地面」取 `block_cnt > 0`**：本项目的干员模型里，近战位
           阻挡数 ≥1、高台位为 0（`can_block` 用的就是它）。这是代理读法，
           已登记在 `docs/verdicts-pending.md` E16。
        3. **「周围 4 格」= 曼哈顿距离 1 的十字五格**（目标格 + 上下左右），
           与「半径 1.0 的圆」是两回事：斜角**不在**里面。原文写的是「周围
           4 格」，故按格算，不复用 `pollute_area` 的圆。

        ⚠ 附加的法术伤害是「**当次**攻击额外附加」：物理那一段照旧结算，
        法术这一段在物理之后**再减一次法抗**（`resolve_damage` 两次），
        不是把两部分加起来当一次伤害打。
        """
        for e in self.enemies:
            if not e.skill_atk_scale_phys and not e.skill_atk_scale_magic:
                continue
            if e.hp <= 0 or e.leaked or e.off_map or e.reborn_at >= 0.0:
                continue
            if (e.frozen or e.down or e.stun_timer > 0
                    or e.idle_timer > 0 or e.disarm_timer > 0):
                continue
            e.skill_atk_timer += dt
            need = (e.skill_atk_init if e.skill_atk_first
                    else (e.skill_atk_interval or e.attack_interval))
            if e.skill_atk_timer < need:
                continue
            e.skill_atk_timer = 0.0
            e.skill_atk_first = False
            target = self._skill_atk_target(e)
            if target is None:
                continue
            e.attack_pause = max(e.attack_pause, self.enemy_windup)
            cx, cy = int(target.position[0]), int(target.position[1])
            # 十字五格：目标格 + 上下左右（斜角不在内）
            cells = [(cx, cy), (cx + 1, cy), (cx - 1, cy),
                     (cx, cy + 1), (cx, cy - 1)]
            if e.skill_atk_cross <= 0:
                cells = [(cx, cy)]
            polluted = (self.farmland is not None
                        and self.farmland.actual_at(*e.cell()) > 0.0)
            mag = (e.atk * e.skill_atk_scale_magic) if polluted else 0.0
            for c in cells:
                op = self._alive_op_at(c)
                if op is None or op.hp <= 0 or op.retreated:
                    continue
                # ① 基础物理：攻击力 × 100%（正文），逐目标减防
                op.take(resolve_damage(
                    e.atk * e.skill_atk_scale_phys, damage_type="PHYSICAL",
                    defense=op.current_defense(), res=op.current_res(),
                    dodge_phys=op.dodge_phys + op.talent_dodge_phys,
                dodge_arts=op.dodge_arts + op.talent_dodge_arts,
                ).final)
                # ② 附加法术（仅当它自己站在受污染的田地上），单独减一次法抗
                if mag > 0.0:
                    op.take(resolve_damage(
                        mag, damage_type=DamageType.MAGIC,
                        defense=0.0, res=op.current_res(),
                        dodge_phys=op.dodge_phys + op.talent_dodge_phys,
                dodge_arts=op.dodge_arts + op.talent_dodge_arts,
                    ).final)
                if op.skill is not None and not op.skill.is_passive \
                        and not op.skill_active:
                    gain = op.skill.sp_per_hit()
                    if gain:
                        op.sp = min(op.skill.sp_cost, op.sp + gain)
            # ③ 令**目标地块**病害值 +N（记入【缓存】，不是直接改【实际】）
            got = 0.0
            if polluted and e.skill_atk_pollut > 0.0 and self.farmland is not None:
                got = self.farmland.pollute_cell(cx, cy, e.skill_atk_pollut)
            if self.verbose:
                extra = (f"，附加法术 {mag:.0f}（自身田地病害值 "
                         f"{self.farmland.actual_at(*e.cell()):g} > 0）" if mag > 0
                         else "，自身不在受污染的田地上 → 无附加法术")
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 技能「{e.skill_atk_key}」→ "
                    f"{target.name} 及其十字四邻（{len(cells)} 格）"
                    f"物理 {e.atk * e.skill_atk_scale_phys:.0f}{extra}"
                    + (f"，目标地块病害值 +{got:g} 记入缓存" if got else ""))

    def _skill_atk_target(self, e: EnemyUnit) -> OperatorUnit | None:
        """技能攻击挑谁：**全图**（不看射程）、只要地面单位（`block_cnt > 0`）。

        挑法与敌方普攻一致：**最后部署的那一个**（`self.operators` 的顺序就是
        部署顺序）。原文只说「1 名部署于地面的我方单位」，没有说按什么挑——
        这里沿用项目内既有的敌方索敌口径，不另立一套。
        """
        picked: OperatorUnit | None = None
        for op in self.operators:
            if not op.alive or op.retreated or op.hp <= 0:
                continue
            if e.skill_atk_ground_only and op.block_cnt <= 0:
                continue
            picked = op
        return picked

    def _sever_farmland(self, cell: tuple[int, int], t: float) -> None:
        """把一格从田地里摘掉（阻流阀建成的那一刻）。

        预置阻流阀开场即在位，走的是构造里那一遍；
        这里是**玩家手动部署**的那条路：落下去时不动田地，建成时才动。
        """
        if self.farmland is None or not self.farmland.severable:
            return
        self.farmland.sever(*cell)
        if cell not in self._blocker_cells:
            self._blocker_cells.append(cell)
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  阻流阀建成 → {cell} 不再算田地，"
                f"田地重划为 {len(self.farmland.fields)} 片")

    def _device_tick(self, dt: float, t: float) -> None:
        """装置侧的三件事：建成进度、AuraHit 真伤、被拆后把地形还回去。

        顺序是**有意的**：

        1. 先推进建成进度——建成期间无敌（原文：手动部署的阻流阀「3秒内逐渐
           提升至最大值，**期间持有无敌**」），这一帧的 AuraHit 不该打进去；
        2. 再结算 `AuraHit.`——原文是「**进入**阻流阀半径 0.5 范围内时**立刻**对其
           造成目标最大生命值 50%/70% 的真实伤害」，是**进入触发**（边沿），
           不是"站在里面每秒掉血"。所以按 (敌人, 装置) 记下上一帧的接触状态，
           只在"这一帧碰到、上一帧没碰到"时打一下。田鼷沿路线走，进出一次打一下，
           两次经过就能拆掉一个 100 血的阻流阀（50+50），这正是设计意图。
           **只对阻流阀生效**：原文点名的是阻流阀，泵站/天桩不因此挨打
           （天桩另有自己的死法——所在地块的甲退场，见 `_pile_tick`）。
        3. 最后处理被摧毁的装置——**把地形还回田地**。原文那句「自技能结束到
           自身退场，重写自身所在地块的地形标记为阻流阀」是有期限的：装置一没，
           那一格又变回水田，被它切断的田地重新连成一片。

        ⚠ 打的是**目标（装置）最大生命值**的比例，不是田鼷自己的。写反了会得到
        "19000×0.5" 这种一下拆掉一片装置的怪结果。
        """
        cells_before: list[tuple[int, int]] = []
        for d in self._devices:
            if not d.alive:
                continue
            was_building = d.build_left > 0.0
            d.tick_build(dt)
            # 建成**那一刻**才改写地块：原文「3 秒建成，自身地块不再是田地、
            # 连片由此重划」。落下去就断田会让那 3 秒的田地划分提前变形，
            # 而"提前 3 秒少一片田"会实打实地改变病害值的扩散。
            if was_building and d.built and d.key == self._blocker_key:
                self._sever_farmland(d.cell, t)

        # ---- AuraHit（田鼷力士 / 猛士 / 飞贼 / 大盗）
        touched: dict[int, set[int]] = {}
        for e in self.enemies:
            if e.hp <= 0 or e.leaked or e.off_map or e.reborn_at >= 0.0:
                continue
            if e.aura_hit_ratio <= 0.0:
                continue
            key = id(e)
            prev = self._aura_touch.get(key, set())
            now: set[int] = set()
            for d in self._devices:
                if not d.alive or not d.built:
                    continue
                # 原文点名的是**阻流阀**（「进入[[阻流阀]]半径0.5范围内时立刻
                # 对其造成…」），所以泵站/天桩不吃这一条。天桩另有自己的死法
                # ——所在地块的甲退场时它才死（见 `_pile_tick`）。
                if d.key != self._blocker_key:
                    continue
                if math.dist(e.position, d.cell) <= (e.aura_hit_radius or 0.5):
                    now.add(id(d))
                    if id(d) in prev:
                        continue                    # 上一帧就在范围里 → 不是"进入"
                    dmg = e.aura_hit_ratio * d.max_hp
                    dealt = d.take_damage(dmg)
                    if self.verbose and dealt > 0:
                        self.result.log.append(
                            f"{t:7.1f}s  {e.name} 进入 {d.name} 范围 → "
                            f"真伤 {dealt:.0f}（{d.name} {d.hp:.0f}/{d.max_hp:.0f}）")
                    if not d.alive:
                        self.result.devices_lost.append(
                            (t, d.key, d.cell, e.name))
                        # 只有**改写地块**的装置（阻流阀）退场才把地形还回去；
                        # 天桩（重写地块=否）只是站在田地上，拆掉它不改几何。
                        if d.key == self._blocker_key:
                            cells_before.append(d.cell)
            touched[key] = now
        # 只留这一帧还在场的敌人，免得 id 复用串到别的敌人身上
        self._aura_touch = touched

        # ---- 被拆掉的装置：把地形还回去
        for cell in cells_before:
            if self.farmland is not None and self.farmland.severable:
                self.farmland.restore(*cell)
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  装置被摧毁 → {cell} 还回田地，"
                        f"田地重划为 {len(self.farmland.fields)} 片")

    def _pile_spec(self, device) -> tuple[str, object]:
        """装置 → **它召唤的那名天桩-甲**，以及关卡给它指派的那条路径。

        这一段**全是结构化字段**，不用猜正文（原先的 `PILE_CHILD` 表已降级为退路）：

        装置 predefine 的 ``overrideSkillBlackboard[branch_id]``（关卡没写覆盖时
        退回技能默认黑板 ``branch_dhdcr_1``，见 `Stage.branch_for`）
        → 关卡 ``branches[branch_id].phases[].actions[]``
        → ``key`` 是甲（``enemy_1398_dhdcr`` / 失控 ``_2`` / 关卡本地 ``_b``），
        ``routeIndex`` 指向关卡 ``extraRoutes``（**与出怪表用的 ``routes``
        是两个命名空间**）。

        ⚠ 2026-09-16 更正：这条路径**不是甲的行进计划**。甲的天赋第一句就是
        「自缚」（不能移动），它站在原地监测脚下那格的病害值。全活动 32 个天桩
        逐关核过：**每个装置格都等于它那条路径的起点格**，也就是"关卡给这个
        单位指派的路线"（编辑器给每个落场单位都发一条，终点是保护目标）。
        路径因此只作留档与交叉校验用（`tools/check_environment.py` §11 会核
        "起点 == 装置格"），甲不执行它。

        整条都查不到时退回 `PILE_CHILD`（并返回 None），模拟照跑。
        """
        bid = str(getattr(device, "branch_id", "") or "")
        # 装置 key 末段 → 支线前缀（`trap_146_dhdcr` → `branch_dhdcr`）。
        # 这一道把**没有支线语义**的装置挡在外面：阻流阀/泵站推不出
        # `branch_dhtl` / `branch_dhsb`，于是它们不会误领天桩那条支线
        # （踩过：不挡的话 act31side_08 的 26 个装置会各召唤一名甲）。
        # 惰性导入：`battle` 的导入链**不牵 gamedata**（自检与 TUI 只用前者）
        from ..gamedata.stage import branch_prefix
        branch = self.stage.branch_for(bid, prefix=branch_prefix(device.key))
        for act in self.stage.branch_actions(branch):
            if not act.enemy_key:
                continue
            return act.enemy_key, self.stage.extra_route(act.route_index)
        if device.key not in PILE_CHILD:
            return "", None
        return PILE_CHILD[device.key], None

    def _pile_mark_key(self, diver: "EnemyUnit") -> str:
        """天桩-乙 → 它砸下的**身上的天标**。

        乙的天赋黑板是**空的**（`talentBlackboard: []`），"砸下什么"只写在
        正文里，所以走文件头 `PILE_MARK` 那张表；关卡本地的 ``…_dhtb_b``
        先退到它的 ``prefabKey``（``enemy_1399_dhtb``）再查表。
        这是天桩链里**唯一**还需要查表的一跳，已登记在
        `docs/verdicts-pending.md`。
        """
        key = PILE_MARK.get(diver.enemy_id)
        if key:
            return key
        return PILE_MARK.get(self.stage.local_enemy_prefab(diver.enemy_id), "")

    def _pile_tick(self, dt: float, t: float) -> None:
        """天桩链：装置召唤甲 → 甲监测/激活 → 乙扑咬 → 天标附着。

        【正文来历】（prts.wiki 装置页 + 敌人页，原文留档在
        `out/prts-act31side-pages*.txt` 与 `out/prts-special-mechanics.txt`；
        四跳里哪一跳是结构化字段见 `_pile_spec` / `_pile_mark_key` 的说明）

        * **装置「天桩」**：技能「生成」（被动）「登场时，在自身所在位置以预设
          路径召唤一名天桩-甲」；机制「于所在地块的**天桩-甲**（或失控天桩-甲）
          **退场时死亡**」。装置 → 甲这一跳**走结构化字段**（`_pile_spec`）。
        * **天桩-甲**：**监测状态**（初始）——无敌、不死、元素免疫，把自身生命
          百分比**重设**为所在地块病害值（1% 生命 ↔ 1 点，不会因此死亡），
          病害值首次 ≥`CheckAwake.value`（100）后进入**激活状态**；激活后不再
          监测、每秒受自身最大生命 `hp_ratio`（1%）的真实伤害，每损失
          `summon.hp_ratio`（10%）就在 1~1.5s 后召唤 `cnt`（3）个天桩-乙。
        * **天桩-乙**：飞行，登场自缚 1 秒，扑到范围内第一个我方单位身上啃啮；
          攻击**命中时**在目标所在地块中心召唤 1 个身上的天标；**攻击结束时**
          强制击杀自身。
        * **身上的天标**：附着范围半径 0.3，附着对象为**自身登场时**范围内的
          我方单位；附着效果为每秒 `Passive.damage_value`（200）**预计算无途径
          物理伤害**；任一附着对象的效果结束 → 强制击杀自身。

        【四处按项目约定收口，都已登记在 `docs/verdicts-pending.md`】

        1. **「1.0 边长正方形范围内随机位置」的召唤位置取脚下那一格**——
           边长 1.0 的正方形以格心为中心正好只覆盖自身这一格，且模拟器不掷骰
           （与 `_summon_at` 同一处口径）。
        2. **「1~1.5s 随机延迟」取 1.25s**（`PILE_SUMMON_DELAY`）。
        3. **天桩-乙的目标取"直线距离最近的存活干员"**（不设距离上限）。
           它的 `rangeRadius` 是 −1（库里没有射程），「范围内第一个」在数据上
           无法更精确地复现；另加一个凭空的距离上限只会更假。
        4. **乙的「啃啮直至目标倒下」与天赋「攻击结束时强制击杀自身」冲突**，
           按**天赋**实现：咬一口 → 召唤天标 → 自毁（描述那句当风味文本）。

        ⚠ 「自缚」在数据里不是一个字段（它写在天赋正文里），这里靠"召唤时给一条
        **单点路线**"实现：`reached_end` 要求 `route_length > 0`，单点路线长度为
        0，所以甲与乙都既不动、也不会被判成漏怪（见 `unit.reached_end`）。
        甲那条**关卡指派路径**（`extraRoutes`）因此不执行，只留档 + 交叉校验。
        """
        fs = self.farmland
        # ① 装置召唤甲（一次性，模拟器开跑后的第一帧）
        for d in self._devices:
            if not d.alive or d.summoned:
                continue
            key, route = self._pile_spec(d)
            if not key:
                continue
            # 甲**站在原地**：它的天赋第一句就是「自缚」（= 不能移动），
            # 报的路径是关卡给"这个单位"的指派路线（起点逐关核过，就是装置格
            # 本身，见 `check_environment.py` 的 §11），不是它的行进计划。
            # 所以这里给的是**单点路线**：不动、也不会被判成漏怪
            # （`reached_end` 要求 `route_length > 0`）。路径只进日志留档。
            pts = [(float(d.cell[0]), float(d.cell[1]))]
            child = self._build_enemy(key, self._summon_level(key), pts, [], t, 0.0)
            # 监测状态：无敌 + 不死。**不可阻挡与自缚是它的常驻天赋**，
            # 与监测状态无关——全库只有天桩-甲两型带 `CheckAwake.`，故用它当判据。
            child.monitor = child.awake_value > 0.0
            child.always_invincible = child.monitor
            child.unblockable = True
            child.owner_device = d
            d.summoned = True
            self._pile_children.setdefault(id(d), []).append(child)
            self.enemies.append(child)
            if self.verbose:
                tail = (f"，关卡指派路径 {route.start}→{route.end}"
                        f"（{route.length()} 格，自缚不执行）"
                        if route is not None else "（关卡里没有它的指派路径）")
                self.result.log.append(
                    f"{t:7.1f}s  {d.name} 召唤 {child.name} 于 {d.cell}{tail}"
                    f"；监测状态：生命百分比 = 所在地块病害值")

        # ② 三型各自的状态机
        for e in list(self.enemies):
            if e.hp <= 0 or e.leaked or e.off_map or e.reborn_at >= 0.0:
                continue
            if e.awake_value > 0.0:                 # 天桩-甲
                self._pile_parent_tick(e, dt, t, fs)
            elif self._pile_mark_key(e):            # 天桩-乙（含关卡本地 _b）
                self._pile_diver_tick(e, t)
            elif e.attach_damage > 0.0:             # 身上的天标
                self._pile_mark_tick(e, dt, t)

        # ③ 甲退场 → 它那根天桩装置自动死亡
        for d in self._devices:
            if not d.alive:
                continue
            kids = self._pile_children.get(id(d)) or []
            if not kids:
                continue                        # 还没召唤出来（不该发生）
            if any(k.hp > 0 and not k.leaked and not k.off_map for k in kids):
                continue
            d.alive = False
            d.hp = 0.0
            self.result.devices_lost.append((t, d.key, d.cell, kids[0].name))
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {d.name} 随 {kids[0].name} 退场而死亡")

    def _pile_parent_tick(self, e: EnemyUnit, dt: float, t: float, fs) -> None:
        """`CheckAwake.` 的兑现处：天桩-甲监测状态重设生命；激活状态自伤并分批召唤。"""
        if e.monitor:
            pollution = fs.actual_at(*e.cell()) if fs is not None else 0.0
            # 「重设自身生命百分比与所在地块病害值相同（每1%生命值对应1点，
            #  **不会导致死亡**）」→ 下限压到 1 点血。
            e.hp = max(1.0, e.max_hp * min(1.0, pollution / PILE_POLLUT_FULL))
            if e.awake_value > 0.0 and pollution >= e.awake_value:
                e.monitor = False
                e.always_invincible = False
                e.awake_timer = 0.0
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {e.name} 激活（所在地块病害值 "
                        f"{pollution:g} ≥ {e.awake_value:g}）→ 开始每秒自伤")
            return
        if e.awake_hp_ratio <= 0.0 or e.awake_summon_ratio <= 0.0:
            return
        e.awake_timer += dt
        while e.awake_timer >= 1.0:
            e.awake_timer -= 1.0
            # 「每秒受到自身最大生命值1%的真实伤害」：真实伤害不经减伤，
            # 也不该走 `_damage_enemy`（那会把自伤记成"我方造成的伤害"）。
            e.hp = max(0.0, e.hp - e.max_hp * e.awake_hp_ratio)
            e.awake_lost += e.awake_hp_ratio
            while ((e.awake_batches + 1) * e.awake_summon_ratio
                   <= e.awake_lost + 1e-9):
                e.awake_batches += 1
                e.awake_pending.append(t + PILE_SUMMON_DELAY)
                if self.verbose:
                    self.result.log.append(
                        f"{t:7.1f}s  {e.name} 损失达 "
                        f"{e.awake_batches * e.awake_summon_ratio * 100:g}% "
                        f"→ {PILE_SUMMON_DELAY:g}s 后召唤 "
                        f"{e.awake_summon_cnt} 个{e.awake_enemy_key}")
        for due in [x for x in e.awake_pending if x <= t]:
            e.awake_pending.remove(due)
            self._pile_summon(e, e.awake_summon_cnt, t)

    def _pile_summon(self, parent: EnemyUnit, cnt: int, t: float) -> None:
        """甲在**脚下那一格**召唤 `cnt` 个乙（原文的随机落在 1.0 正方形内）。

        乙的**静态刚体**（原文天赋第一句）决定了它也**不走路线**，所以这里给
        单点路线；它动起来只有一种情形——扑向干员（`_pile_diver_tick`）。
        """
        key = parent.awake_enemy_key
        if not key:
            return
        pts = [(float(parent.cell()[0]), float(parent.cell()[1]))]
        for _ in range(int(cnt)):
            e = self._build_enemy(key, self._summon_level(key), pts, [], t, 0.0)
            e.idle_timer = PILE_SELF_BIND           # 「登场时持有1秒自缚」
            self.enemies.append(e)
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {parent.name} 召唤 {e.name} 于 {parent.cell()}")

    def _pile_diver_tick(self, e: EnemyUnit, t: float) -> None:
        """天桩-乙：自缚 1 秒后扑向最近的干员，咬一口、挂天标、自毁。

        「**范围内**第一个我方单位」的范围在数据里是空的：`rangeRadius = −1`、
        攻击方式写「近战 远程」。本项目取「**最近的存活干员**（不设距离上限）」，
        理由是正文写的是「扑到…身上」（要够得着才能扑），而数据里没有任何半径
        可以拿来当上限——加一个上限就是凭空造数。两种读法（含"只扑 1 格内、
        其余原地悬停"）都已登记在 `docs/verdicts-pending.md`。
        """
        if e.self_destruct_at >= 0.0 and t >= e.self_destruct_at:
            # 「攻击结束时…强制击杀自身」。走直接写血：这不是我方击杀，
            # 也不该触发任何"被击倒"类效果（乙自己没有那些效果）。
            e.hp = 0.0
            return
        if e.idle_timer > 0.0 or e.attacked_once:
            return
        target = None
        best = float("inf")
        for op in self.operators:
            if not op.alive or op.retreated:
                continue
            d = math.dist(e.position, op.position)
            if d < best:
                best = d
                target = op
        if target is None:
            return
        # 已经贴到目标格：钉住（换成单点路线，免得"走到路线终点"被判成漏怪）
        if best <= 0.5:
            e.route = [(float(target.position[0]), float(target.position[1]))]
            e.legs = []
            e.progress = 0.0
            e.position = (float(target.position[0]), float(target.position[1]))
            dealt = target.take(resolve_damage(
                e.atk, damage_type=e.attack_type,
                defense=target.current_defense(), res=target.current_res(),
                dodge_phys=target.dodge_phys + target.talent_dodge_phys,
            dodge_arts=target.dodge_arts + target.talent_dodge_arts,
            ).final)
            e.attacked_once = True
            e.self_destruct_at = t + self.enemy_windup
            self._pile_attach_mark(e, target, t)
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 啃啮 {target.name} 造成 {dealt:,.0f}"
                    f"（砸下 1 个天标，随后自毁）")
            return
        # 还没到 → 朝目标扑（目标换人/刚登场时都要指一遍）
        e.route = [(float(e.position[0]), float(e.position[1])),
                   (float(target.position[0]), float(target.position[1]))]
        e.legs = []
        e.progress = 0.0

    def _pile_attach_mark(self, diver: EnemyUnit, target: OperatorUnit,
                          t: float) -> None:
        """在目标所在地块中心召唤 1 个天标，并**当场快照**附着对象。"""
        key = self._pile_mark_key(diver)
        if not key:
            return
        cell = (float(target.position[0]), float(target.position[1]))
        mark = self._build_enemy(key, self._summon_level(key), [cell], [], t, 0.0)
        # 「无法攻击/被阻挡」是它的天赋原文：不可阻挡、也不参与索敌优先级。
        mark.unblockable = True
        # 「附着对象为**自身登场时**附着范围内的我方单位」——半径 0.3 从格心量
        # 出去够不到别格（干员都在格心、相邻 1.0 格），所以快照就是这一格的人。
        mark.attached = [op for op in self.operators
                         if op.alive and not op.retreated
                         and math.dist(op.position, cell) <= 0.3]
        self.enemies.append(mark)
        if self.verbose:
            self.result.log.append(
                f"{t:7.1f}s  {diver.name} 在 {target.position} 挂上 {mark.name}"
                f"（附着 {len(mark.attached)} 人，每秒 "
                f"{mark.attach_damage:g} 无途径物理伤害）")

    def _pile_mark_tick(self, e: EnemyUnit, dt: float, t: float) -> None:
        """身上的天标：每秒按 `Passive.damage_value` 对附着对象结算一次；对象全没了就自毁。"""
        alive = [op for op in e.attached if op.alive and not op.retreated]
        if not alive:
            e.hp = 0.0
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 附着对象全部退场 → 强制击杀自身")
            return
        e.attach_timer += dt
        while e.attach_timer >= 1.0:
            e.attach_timer -= 1.0
            for op in alive:
                # 「预计算无途径物理伤害」= 定额、不吃防御也不吃法抗，
                # 故直接 `take` 而不是 `resolve_damage`。
                op.take(e.attach_damage)

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
          （`token_key` 的装置 × `death_cnt`）。这份额度**记进账也进额度**
          （`res.device_tokens` + `sim.device_token_balance`），能不能真放下去
          由 `_do_deploy_device` 在计划到点那一刻判（放不下记进
          `res.device_deploy_rejected`）。放哪一格数据里没有，所以**只认计划**：
          计划里没写就只攒着，不替博士做战术决定（`docs/verdicts-pending.md` E7）。
        """
        if e.passive_pollut > 0.0:
            self._pollute_around(e, t, e.passive_pollut,
                                 e.passive_radius or 1.0, "被击倒")
        if e.death_token and e.death_cnt:
            self.result.device_tokens.append((t, e.death_token, e.death_cnt))
            self.device_token_balance[e.death_token] = (
                int(self.device_token_balance.get(e.death_token, 0))
                + int(e.death_cnt))
            if self.verbose:
                self.result.log.append(
                    f"{t:7.1f}s  {e.name} 被击倒 → 获得 {e.death_cnt} 个 "
                    f"{e.death_token}（手上共 "
                    f"{self.device_token_balance[e.death_token]} 个）")

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
