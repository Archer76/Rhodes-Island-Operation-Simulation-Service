"""天赋在战斗里的落地。

数据层（`ak_tactic.operator.talent`）只能告诉你"这条天赋的黑板长这样"，
不能告诉你它**做什么**——和技能一样，语义活在描述文字里。所以这里对
**已核实**的天赋做显式建模，一条一条写清楚依据；没建模的天赋一概不猜。

目前建模两条：

## 积雪（圣聆初雪「无垠的雪景」）

依据：天赋描述 + 天赋黑板 + 技能2黑板三方对照。

```
天赋黑板（精英2，潜能1 档）：interval 5.5  max_cast_cnt 5
                             move_speed -0.12  talent_magic_scale 0.75
技能2黑板（专精三）：talent@s2_magic_scale 0.2
                     talent@max_cast_tile_count 20   talent@cold 5.0
```

> 攻击范围内的地面每隔 5.5 秒产生一层积雪，地面敌人经过时立即受到相当于攻击力
> 75% 的法术伤害，每层积雪使经过的所有敌人移动速度下降 12%，最多叠加 5 层
> （首个敌人离开该地块时积雪消失）
>
> 技能2 追加：处于积雪上的地面敌人**每秒**受到攻击力 20% 的法术伤害，
> 积雪超过 5 层时向周围扩散一层（最多向外扩散 20 格），敌人离开积雪时获得 5 秒寒冷

落到代码上的四条：

1. **积层**：每隔 `interval` 秒，射程内每个**地面**格 +1 层，上限 `max_cast_cnt`。
2. **踏入伤害**：地面敌人**每次踏入**雪格时受一次 `talent_magic_scale × 攻击力`
   的法术伤害。描述里"每层"只修饰减速（"每层积雪使……移动速度下降"），
   伤害那句没有"每层"，所以**按每次踏入一次**算，不乘层数。
3. **减速**：雪格上的敌人移速 × `(1 + move_speed × 层数)`，即每层 −12%、满 5 层 −60%。
4. **技能2 持续伤害**：技能2 开启期间，雪格上的地面敌人每秒再受
   `s2_magic_scale × 攻击力` 的法术伤害；并把扩散上限提到 `max_cast_tile_count`。

**未建模**（如实记下，别当成 0）：离开积雪的 5 秒寒冷、满 5 层后地块的冻结状态、
冻结带来的控制效果。以及天赋2「圣山的祝福」（受致命伤害时回满血并冻结周围）——
它只在德克萨斯这类"会被打死"的干员身上才有意义，而圣聆初雪在 SR-6 里不掉血。

## 编队加初始费（德克萨斯「战术快递」）

依据：天赋描述与黑板都是单键 `cost`，精英2 为 `cost 2.0`。

> **编入队伍后**，额外获得 2 点初始部署费用

注意是**编队时**就生效，不是部署那一刻才返费——所以它是开局初始费用 +2，
由模拟器在 `run()` 开始时一次性结算，而不是挂在 `_do_deploy` 上。
两者总额相同、**时点不同**：开局就多 2 费意味着第一个干员能早 2 秒落地。

判据：**天赋黑板有且仅有 `cost` 一个键**。键多了就可能是"费用降低／费用上限"之类，
那属于没建模的范畴，宁可返回 0 也不猜。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..operator.talent import Talent

__all__ = [
    "SnowField",
    "SNOW_KEYS",
    "is_snow_talent",
    "find_snow",
    "BLESSING_KEYS",
    "is_blessing_talent",
    "find_blessing",
    "squad_cost_bonus",
    "REGEN_KEYS",
    "find_regen",
    "RegenAura",
    "SP_KEYS",
    "is_sp_talent",
    "find_sp_on_action",
    "SpOnAction",
    "MODELED",
]

#: 认出"积雪天赋"的黑板指纹。三个键同时出现才是，缺一不可。
SNOW_KEYS = ("interval", "max_cast_cnt", "talent_magic_scale")

#: 认出"入场增益治疗"天赋的黑板指纹。
#:
#: 依据：凯尔希·思衡托天赋2 的描述与黑板逐字对应——
#:
#: > 其他友方干员**进入自身攻击范围时**立刻获得 1 层护盾并额外获得一次
#: > **每秒回复 60 点生命值**的增益治疗，持续 **30 秒**（不可叠加），
#: > 增益治疗对【罗德岛】干员的效果翻倍
#:
#: ```
#: 黑板： buff_duration 30   hp_recovery_per_sec 60   rhodes_bonus 2
#: ```
#:
#: 建模的是"每秒回复 + 持续 + 不可叠加"这三条。**护盾那一层没建模**
#: （描述只写"1 层护盾"，没给数值），【罗德岛】翻倍也没建模——
#: 两处都按**偏保守**处理：宁可把治疗算少，不把生存算多。
REGEN_KEYS = ("hp_recovery_per_sec", "buff_duration")

#: 已被显式建模的天赋一览（给 CLI 与文档用）
MODELED = {
    "snow": "积雪：积层 / 踏入伤害 / 每层减速 / 满层冻结 / 技能2 持续伤害",
    "blessing": "圣山的祝福：致命伤免死一次（回满血 + 自身冻结 + 范围冻结）",
    "squad_cost": "编入队伍后额外获得初始部署费用",
    "regen_aura": "友方进入攻击范围时获得每秒回复生命值的增益治疗",
    "sp_on_action": "情绪吸收：攻击敌人额外回技力、消灭敌人额外得技力",
    "team_aura": "青色怒火：全场友方攻击力/防御力提升，光环主人开技能时加倍",
}

#: 认出"情绪吸收"天赋的黑板指纹（阿米娅·**中坚术师**形态）。
#:
#: 依据：天赋描述与黑板逐字对应——
#:
#: > 攻击敌人时额外回复 2 点技力，消灭敌人后额外获得 8 点技力
#:
#: ```
#: 潜能 1–4 档： amiya_t_1[atk].sp 2    amiya_t_1[kill].sp 8
#: 潜能 5–6 档： amiya_t_1[atk].sp 3    amiya_t_1[kill].sp 10
#: ```
#:
#: 两个坑：
#: ① 键名里的 `atk` 指的是**"攻击"这个动作**，与攻击力无关，别被它误导；
#: ② **阿米娅三个形态的天赋各不相同**——中坚术师「情绪吸收」、术战者
#:    「青色怒火」、医疗「诚挚期许」。所以指纹只认这对键、不认干员是谁；
#:    术战者的黑板是 `atk`/`def`，不会误中。
SP_KEYS = ("amiya_t_1[atk].sp", "amiya_t_1[kill].sp")


def is_sp_talent(t: Talent) -> bool:
    return t.has(*SP_KEYS)


@dataclass
class SpOnAction:
    """「情绪吸收」：攻击敌人时额外回技力，消灭敌人后额外获得技力。

    这是**叠加在技能自己的 `sp_type` 之上的第二条 SP 来源**，不是替代：
    技能是"攻击回复"型时两条都记；是"自动回复"型时这条照样记
    （阿米娅技1「战术咏唱·γ型」正是自动回复型，若只认 sp_type 就整条漏掉）。

    「攻击敌人时」按**出手**算一次，不按打中几个目标算——与模拟器里
    `sp_per_attack` 的口径一致（见 `_operators_attack` 的同名注释）。
    """

    per_attack: float = 0.0
    per_kill: float = 0.0


def find_sp_on_action(talents) -> "SpOnAction | None":
    """把「情绪吸收」的黑板翻成 `SpOnAction`，没有这个天赋则返回 None。"""
    for t in talents or ():
        if not is_sp_talent(t):
            continue
        return SpOnAction(per_attack=t.value("amiya_t_1[atk].sp"),
                          per_kill=t.value("amiya_t_1[kill].sp"))
    return None


def is_regen_talent(t: Talent) -> bool:
    return t.has(*REGEN_KEYS)


def find_regen(talents) -> Talent | None:
    for t in talents or ():
        if is_regen_talent(t):
            return t
    return None


#: 「青色怒火」——阿米娅·**术战者**形态的天赋。
#:
#: 为什么只能按**天赋名**认、不能按键名认：它的黑板就是裸 `atk` / `def`，
#: 与技能自己的攻击力/防御力增益**完全同名**，靠键名根本分不出"这是光环"
#: 还是"这是技能给自己加的"。三个形态的天赋名各不相同（中坚术师「情绪吸收」
#: 的键是 `amiya_t_1[atk].sp`，不会误中），所以名字在这里是**可靠判据**。
#:
#: ```
#: 精一： atk 0.04  def 0.04
#: 精二： atk 0.07  def 0.07
#: ```
TEAM_AURA_NAME = "青色怒火"


def is_team_aura_talent(t: Talent) -> bool:
    return t.name == TEAM_AURA_NAME and t.has("atk", "def")


def find_team_aura(talents) -> Talent | None:
    for t in talents or ():
        if is_team_aura_talent(t):
            return t
    return None


@dataclass
class TeamAura:
    """一个干员发给**全场友方**的攻击力/防御力光环。

    描述：「在场时所有友方单位的攻击力和防御力 +7%，**技能开启期间效果加倍**」。
    「加倍」的主语是**光环的主人自己**——博士 2026-09-17 裁定。阿米娅开技能
    的那段时间全场吃到双倍，她不开就只有基础值；别人开不开技能与她无关。
    技2 黑板里的 `talent_scale: 2.0` 正是这个倍率的数据化表达。

    与 `RegenAura` 的关键差别：那个是**射程内**才生效，这个是**全场**，
    不看位置，所以没有 `cells_of`、也没有"进入"那一刻的歧义。
    """

    owner: str
    atk_pct: float
    def_pct: float
    #: 加倍倍率。描述写「加倍」即 2.0。
    double_scale: float = 2.0
    #: 光环主人本体（模拟器填），翻倍与否要看它开着技能没有
    operator: object = None

    def current(self) -> tuple[float, float]:
        """当前生效的 `(攻击力比例, 防御力比例)`。"""
        k = 1.0
        op = self.operator
        if op is not None and getattr(op, "skill_active", False):
            k = self.double_scale
        return self.atk_pct * k, self.def_pct * k


@dataclass
class RegenAura:
    """一个干员光环式发出的"增益治疗"。

    「进入自身攻击范围时」——注意**部署进射程内也算进入**。游戏里干员落地
    那一刻就是在范围里，天赋照样触发，所以这里在部署当帧就判一次，
    不等它"走进来"。
    """

    owner: str
    hp_per_sec: float
    duration: float
    #: 光环干员本体（模拟器填），射程要问它
    operator: object = None
    #: 已经吃过这份增益的友方名字——「不可叠加」= 每人只触发一次
    granted: set = field(default_factory=set)
    granted_count: int = 0

    def tick(self, dt: float, operators, cells_of, *, strict: bool = False) -> float:
        """推进一帧，返回本帧发出的治疗总量。

        :param cells_of: `(op) -> set[(x, y)]`，取干员的攻击范围
        :param strict: 「进入」的严格读法——只算**光环落地之后**才进场的
            友方。宽松读法（默认）把光环落地当帧已在范围内的友方也算"进入"，
            因为游戏里干员落地那一刻就是在范围里。

            **这条歧义是实质性的**：SR-EX-8 里凯尔希 72s 才落地，而圣聆初雪
            35s 就站在范围内了。严格读法下她吃不到这份治疗，本关的最优解
            会从"四人·余量 79%"退回"三人·余量 38%"。故两种都要跑。
        """
        total = 0.0
        give = self.operator is not None and self.operator.alive
        aura_cells = cells_of(self.operator) if give else set()
        # 光环本人在场上的序号：严格读法只认它之后的
        order = {}
        for i, o in enumerate(operators):
            order[o.name] = i
        owner_idx = order.get(self.owner, -1)
        for op in operators:
            if op is self.operator or not op.alive:
                continue
            cell = (int(round(op.position[0])), int(round(op.position[1])))
            eligible = (not strict) or order.get(op.name, -1) > owner_idx
            if give and eligible and op.name not in self.granted and cell in aura_cells:
                self.granted.add(op.name)
                self.granted_count += 1
                op.regen_left = max(op.regen_left, self.duration)
                op.regen_per_sec = max(op.regen_per_sec, self.hp_per_sec)
            if op.regen_left > 0:
                # 增益已经挂在身上了，就算光环本人倒掉也照样跳完
                step = min(dt, op.regen_left)
                got = op.heal(op.regen_per_sec * step)
                op.regen_left = max(0.0, op.regen_left - dt)
                if op.regen_left <= 0:
                    op.regen_per_sec = 0.0
                total += got
                if self.operator is not None:
                    self.operator.healing_done += got
        return total


Cell = tuple[int, int]


def is_snow_talent(t: Talent) -> bool:
    return t.has(*SNOW_KEYS)


def find_snow(talents) -> Talent | None:
    for t in talents or ():
        if is_snow_talent(t):
            return t
    return None


#: 认出「圣山的祝福」天赋的黑板指纹（圣聆初雪天赋1）。
#:
#: 依据：天赋描述与黑板逐字对应——
#:
#: > 受到伤害时使敌人**寒冷** 1.5 秒，若受到**致命伤害**，仅一次立刻回复
#: > 所有生命值并使自身**冻结** 4 秒，使攻击范围内所有敌方单位**冻结** 8 秒
#:
#: ```
#: 精2 潜能 0–4： c2e_freeze 8.0   cold 1.5   freeze 4.0   hp_ratio 1.0
#: 精2 潜能 5–6： c2e_freeze 8.0   cold 2.0   freeze 4.0   hp_ratio 1.0
#: ```
#:
#: **为什么取这两个键，而不是 `cold` 或 `hp_ratio`**：全表核验过命中面——
#: `c2e_freeze` 与 `freeze` 各只命中这 2 条（同一天赋的两档潜能），
#: 而 `cold` 命中 10 条、`hp_ratio` 命中 156 条（`operator_talent` 共 2647 条）。
#: 后两个键单用会把一堆无关天赋认成这条。守卫把它钉成指纹。
BLESSING_KEYS = ("c2e_freeze", "freeze")


def is_blessing_talent(t: Talent) -> bool:
    return t.has(*BLESSING_KEYS)


def find_blessing(talents) -> Talent | None:
    """找出「圣山的祝福」。没建模的技能/天赋一概不猜，这里也只认指纹。"""
    for t in talents or ():
        if is_blessing_talent(t):
            return t
    return None


def squad_cost_bonus(talents) -> float:
    """「编入队伍后，额外获得 N 点初始部署费用」这类天赋的数额，没有就是 0。

    只认**单键 `cost`** 的天赋：键多了就可能是"费用降低 / 费用上限"之类，
    那属于没建模的范畴，宁可返回 0 也不猜。

    时点是**开局**，不是部署时——所以模拟器在 `run()` 起点结算一次，
    而不是在 `_do_deploy` 里返费。
    """
    total = 0.0
    for t in talents or ():
        sig = [k for k in t.blackboard if not k.startswith("$")]
        if sig == ["cost"]:
            total += t.value("cost")
    return total


#: 「可以使用 N 个召唤物（最多同时部署 M 个）」这类天赋的判据。
#:
#: 判据两条**同时**成立才算：
#:   ① 描述里出现「可以使用」且出现「召唤物」或「棋子」（两种叫法，机制同一）；
#:   ② 黑板里有 `cnt` 且大于 0。
#:
#: 为什么不只按黑板键认：`cnt` 是个泛用键名，全表有 100+ 条天赋带它
#: （计数类、层数类都叫这个），只按键名认会大面积误中。描述里的
#: 「可以使用」是这句机制独有的措辞。
#:
#: 逐条出处（2026-09-18 全表核验）：
#:   电弧「卡带里的灵感」：可以使用 3 个召唤物（最多同时部署 3 个）  cnt 3
#:   令  「挑灯问梦」  ：可以使用 3 个召唤物（最多同时部署 3 个）  cnt 3
#:   望  「铸子」      ：可以使用 4 枚棋子（最多拥有 5 枚）        cnt 4  max_cnt 0
#:
#: 望那条的 `max_cnt` 是 0，而文本说「最多拥有 5 枚」——**两个量不是一回事**
#: （一个是同时部署上限，一个是库存上限），本函数只取 `cnt`。
_SUMMON_WORDS = ("召唤物", "棋子")


def is_summon_limit_talent(t: Talent) -> bool:
    if not t.has("cnt") or t.value("cnt") <= 0:
        return False
    desc = t.description or ""
    return "可以使用" in desc and any(w in desc for w in _SUMMON_WORDS)


#: 「最多同时部署 N 个」——**同时**上限，只在描述文字里。
_SIMULTANEOUS_RE = re.compile(r"最多同时部署\s*(\d+)\s*[个枚]")
#: 「最多拥有 N 枚」——望用的是这个措辞（棋子是"摆下去"，不叫部署）。
_OWNED_RE = re.compile(r"最多拥有\s*(\d+)\s*[枚个]")


@dataclass(frozen=True)
class SummonAllowance:
    """一名召唤者的召唤物额度。两个数是**两回事**，别混。

    :param pool: **可动用总量**，取自黑板 `cnt`，等于描述里的「可以使用 N 个」。
        它随**精英阶段**变（电弧/令：E0=3、E1=4、E2=5），是这一场里总共能拿出
        几个召唤物。
    :param simultaneous: **同时部署上限**。这个数**不在黑板里**，只在描述文字里，
        所以只能解析文字（见 `source`）。电弧/令恒为 3——它**不随精英阶段变**，
        与 `pool` 是完全不同的量。
    :param source: `simultaneous` 的出处：`"同时部署"` / `"拥有"` / `"回落 pool"`。
        **回落只发生在文字根本没写的时候**（深池/梅尔/衡沙），那时 `pool` 是
        唯一的数，只能用它，并在 `source` 里如实标出来。
    """

    pool: int
    simultaneous: int
    source: str
    talent: Talent


def find_summon_allowance(talents) -> SummonAllowance | None:
    """解析一名干员的召唤物额度；不是召唤者就返回 `None`。

    **不返回猜的默认值**——调用方要据此判断"这人到底是不是召唤者"，
    猜一个 1 会让非召唤者也悄悄放出东西来。

    为什么同时上限要走文字、不走 `token` 的 `maxDeployCount`：那个字段在
    令/深池/梅尔身上是 **1**（它们明明能放 3-5 个），在电弧身上是 3、望身上
    是 4/5/6——**同一个字段在不同 token 上语义不一致**，取它会**把令错压成 1 个**。
    2026-09-18 全表核验的对照表见 `docs/uncertainties.md` 的待裁定条目。
    """
    for t in talents or ():
        if not is_summon_limit_talent(t):
            continue
        pool = int(t.value("cnt"))
        desc = t.description or ""
        m = _SIMULTANEOUS_RE.search(desc)
        if m:
            return SummonAllowance(pool, int(m.group(1)), "同时部署", t)
        m = _OWNED_RE.search(desc)
        if m:
            return SummonAllowance(pool, int(m.group(1)), "拥有", t)
        return SummonAllowance(pool, pool, "回落 pool", t)
    return None


@dataclass
class SnowField:
    """一个干员铺出来的一片雪。

    :param interval: 每隔多少秒积一层
    :param max_layers: 单格层数上限（`max_cast_cnt`）
    :param slow_per_layer: 每层减速比例（取黑板 `move_speed` 的绝对值）
    :param magic_scale: 踏入伤害倍率（`talent_magic_scale`）
    :param spread_cap: 技能开启后允许的总雪格数（`max_cast_tile_count`）；
        为 0 表示不扩散，只在她射程内积。
    """

    owner: str                        # 干员名，仅用于日志
    interval: float
    max_layers: int
    slow_per_layer: float
    magic_scale: float
    spread_cap: int = 0
    dot_scale: float = 0.0            # 技能2 的每秒伤害倍率
    #: 铺雪的干员本体（模拟器填），射程与攻击力都要问它
    operator: object = None
    timer: float = 0.0
    #: 格 → 层数
    layers: dict[Cell, int] = field(default_factory=dict)
    #: 格 → 第一个踏入的敌人 id；它离开时整格雪消失
    first_enemy: dict[Cell, int] = field(default_factory=dict)
    #: 敌人 id → 它上一帧所在的格（用来判"踏入"与"离开"）
    last_cell: dict[int, Cell] = field(default_factory=dict)
    spawned: int = 0                  # 累计积出的层数，便于核对

    # ------------------------------------------------------------ 积雪

    @property
    def max_tiles(self) -> int:
        return self.spread_cap if self.spread_cap > 0 else 0

    def tick(self, dt: float, ground_cells: list[Cell],
             neighbour_of=None) -> int:
        """推进计时，到点就往射程内的地面格加一层。返回本帧新增层数。"""
        if self.interval <= 0:
            return 0
        self.timer += dt
        added = 0
        while self.timer >= self.interval:
            self.timer -= self.interval
            added += self._cast(ground_cells, neighbour_of)
        return added

    def _cast(self, ground_cells: list[Cell], neighbour_of) -> int:
        added = 0
        for cell in ground_cells:
            added += self._add(cell)
        # 射程内都满层了才向外扩散（描述：超过 5 层时向周围扩散一层）
        if self.spread_cap > 0 and neighbour_of is not None:
            if all(self.layers.get(c, 0) >= self.max_layers for c in ground_cells):
                for cell in self._spread_frontier(neighbour_of):
                    if len(self.layers) >= self.spread_cap:
                        break
                    added += self._add(cell)
        return added

    def _spread_frontier(self, neighbour_of) -> list[Cell]:
        """已有雪格相邻的、还没雪的可走格，按距离由近及远。"""
        seen = set(self.layers)
        frontier: list[Cell] = []
        for cell in list(self.layers):
            for nxt in neighbour_of(cell):
                if nxt not in seen:
                    seen.add(nxt)
                    frontier.append(nxt)
        return frontier

    def _add(self, cell: Cell) -> int:
        cur = self.layers.get(cell, 0)
        if cur >= self.max_layers:
            return 0
        if cell not in self.layers and self.spread_cap > 0 and len(self.layers) >= self.spread_cap:
            return 0
        self.layers[cell] = cur + 1
        self.spawned += 1
        return 1

    # ------------------------------------------------------------ 敌人

    def slow_at(self, cell: Cell) -> float:
        """这一格对移速的乘数（1.0 = 不减速）。"""
        n = self.layers.get(cell, 0)
        if n <= 0:
            return 1.0
        return max(0.05, 1.0 - self.slow_per_layer * n)

    def enter(self, enemy_id: int, cell: Cell, atk: float,
              damage_fn) -> float:
        """敌人踏入某格：判"踏入"、记录首敌、结算踏入伤害。

        :param damage_fn: `(raw_amount) -> 实际伤害`，由模拟器提供（要过法抗）。
        :return: 本次造成的伤害
        """
        prev = self.last_cell.get(enemy_id)
        self.last_cell[enemy_id] = cell
        if prev == cell:
            return 0.0
        # 离开旧格：如果自己是那格的"第一个敌人"，整格雪消失
        if prev is not None and self.first_enemy.get(prev) == enemy_id:
            self.layers.pop(prev, None)
            self.first_enemy.pop(prev, None)
        if self.layers.get(cell, 0) <= 0:
            return 0.0
        self.first_enemy.setdefault(cell, enemy_id)
        return damage_fn(self.magic_scale * atk)

    def leave_all(self, enemy_id: int) -> None:
        """敌人离场（死亡/漏怪）时调用：它踩过的格按首敌规则清雪。"""
        prev = self.last_cell.pop(enemy_id, None)
        if prev is not None and self.first_enemy.get(prev) == enemy_id:
            self.layers.pop(prev, None)
            self.first_enemy.pop(prev, None)

    def draw(self, width: int, height: int) -> str:
        """把雪画出来（层数用数字，空格表示无雪）。y 向下为正，顺序打印即所见。"""
        lines = []
        for y in range(height):
            lines.append(" ".join(str(self.layers.get((x, y), 0)) if (x, y) in self.layers
                                  else "." for x in range(width)))
        return "\n".join(lines)
