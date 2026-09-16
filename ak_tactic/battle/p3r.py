"""伤害相性（P3R）与关卡装置「全场总攻击」。

这套机制来自《女神异闻录３ Reload》联动（act54side / SR 系列），是 SR-EX-8
真正的主轴——**不是属性对拼，而是「把全场敌人同时打倒在地」的计时游戏**。

## 三个部件

1. **伤害相性**（弱点 / 正常 / 免疫 / 反射）。数据在敌人 `talentBlackboard` 的
   `TotalAttack.PHYSICAL / MAGICAL / ELEMENT`，取值 `0 弱点 / 1 正常 / 2 免疫`。
   本关 8 种敌人的相性都已 `EnemyStats.p3r` 读出。
2. **击破值 → 倒地**。相性为**弱点**时，受到的伤害按**实际掉血量**累积击破值
   （被 DEF/RES 吃掉的部分不算），累积到 `TotalAttack.weak_max` 就清空计量并
   **倒地** `TotalAttack.fall_duration` 秒。倒地期间：**眩晕**（不能动、不能攻击）
   + **不可阻挡** + 嘲讽 −1。
3. **「全场总攻击」装置**（`trap_335_totalattack`）。每 0.1 秒检查一次：场上
   所有带相性的敌人**全部倒地**时触发——0.1 秒后自身获得
   `(15000 + 全队角色类干员攻击力总和) × 1.0` 的攻击力增益，再过 0.8 秒对
   **全场所有敌人**造成等量**真实伤害**，然后解除全场倒地，进入 8 秒冷却。

## 两个反直觉但决定胜负的点

* **相性「免疫」是把伤害归零，不是减免。** 吓人路灯是 `0/2/0`，法术伤害直接
  变成 0——和「法抗 99 只剩 1%」是两回事，量级差 12500。
* **没有弱点的敌人永远不倒，会把整条链路卡死。** 挥铳圣像 `1/1/1`，
  `can_fall` 为假。只要它活着，总攻击**一次都触发不了**。

数据侧只负责把相性/阈值/时长读出来；真正的判定（谁弱、几时倒地、装置何时开火）
都在这里，模拟器每帧调一次 `tick()`。
"""

from __future__ import annotations

from dataclasses import dataclass, field

__all__ = [
    "P3R_WEAK", "P3R_NORMAL", "P3R_IMMUNE", "P3R_REFLECT",
    "AFFINITY_CN", "DamageSlot", "BreakState", "TotalAttackDevice",
    "damage_slot", "affinity_multiplier",
]

P3R_WEAK, P3R_NORMAL, P3R_IMMUNE, P3R_REFLECT = 0, 1, 2, 3

AFFINITY_CN = {P3R_WEAK: "弱点", P3R_NORMAL: "正常",
               P3R_IMMUNE: "免疫", P3R_REFLECT: "反射"}

#: 伤害类型 → 相性槽位。真实伤害不吃相性（它不走物理/法术/元素任何一条）。
_SLOT_OF_TYPE = {"PHYSICAL": "physical", "MAGIC": "magical", "MAGICAL": "magical"}

DamageSlot = str          # "physical" | "magical" | "element"


def damage_slot(damage_type: str) -> DamageSlot | None:
    """伤害类型落到哪个相性槽。真实伤害返回 None（不受相性影响）。"""
    return _SLOT_OF_TYPE.get(str(damage_type or "").upper())


def affinity_multiplier(affinity: int | None, *, immune_blocks_damage: bool = True) -> float:
    """相性对伤害的倍率。

    **免疫与反射都是把伤害归零**，不是减免——所以这里返回 0.0 而不是某个小数。
    相性缺数据（None）时按正常处理，免得把"没这项数据"当成免疫。

    2026-09 补记：我曾据「Mode_A 标着法术免疫、法抗却只有 20」推断免疫只挡击破值
    而不减免伤害。**用户实机确认那是错的**——免疫就是免疫该类型的全部伤害。
    法抗与免疫并存不是冗余：免疫决定"完全打不动"，法抗只在非免疫类型上生效。默认值已改回 True。
    """
    if not immune_blocks_damage:
        return 1.0
    if affinity in (P3R_IMMUNE, P3R_REFLECT):
        return 0.0
    return 1.0


@dataclass
class BreakState:
    """一个敌人的击破值计量与倒地状态。"""

    weak_max: float = 0.0
    fall_duration: float = 0.0
    #: 已累积的击破值
    meter: float = 0.0
    #: 倒地到什么时候为止（-1 = 没倒地）
    down_until: float = -1.0
    #: 累计倒地次数——用来判断装置"全场倒地"是否成立
    falls: int = 0

    @property
    def enabled(self) -> bool:
        """有阈值才谈得上击破。阈值 0 表示这个敌人没有相性计量。"""
        return self.weak_max > 0

    def is_down(self, t: float) -> bool:
        return t < self.down_until

    def add(self, dealt: float, affinity: int | None, t: float) -> bool:
        """按**实际掉血量**累积击破值，够了就倒地。返回本次是否触发倒地。

        三条守则，都对得上机制原文：
        * 只有**弱点**才累积；
        * **已经倒地**期间不再累积（原文"未【倒地】的情况下"）；
        * 累积的是掉血量，所以调用方传进来的必须是结算后的实际伤害。
        """
        if dealt <= 0 or affinity != P3R_WEAK or not self.enabled:
            return False
        if self.is_down(t):
            return False
        self.meter += dealt
        if self.meter >= self.weak_max:
            self.meter = 0.0
            self.down_until = t + self.fall_duration
            self.falls += 1
            return True
        return False

    def clear(self) -> None:
        """被总攻击解除倒地（计量已经在倒地时清空过，这里只解除状态）。"""
        self.down_until = -1.0

    def to_dict(self) -> dict:
        return {"weak_max": self.weak_max, "fall_duration": self.fall_duration,
                "meter": round(self.meter, 1), "falls": self.falls}


@dataclass
class TotalAttackDevice:
    """关卡装置「全场总攻击」——P3R 的结算端。

    黑板（`character_table.json` 里 `trap_335_totalattack` 的天赋
    `TalentTotalAttack`）：`trigger_cd 8.0` / `attack@base_atk 15000.0` /
    `attack@atk_scale 1.0` / `attack@all_atk_scale 1.0`。

    **只要场上还有一只有相性、且没倒地的敌人，就不触发。** 所以「挥铳圣像」
    这类 `1/1/1`（无弱点、永不倒）的敌人是本关的死结。
    """

    base_atk: float = 15000.0
    trigger_cd: float = 8.0
    atk_scale: float = 1.0
    check_interval: float = 0.1
    buff_delay: float = 0.1
    hit_delay: float = 0.8

    #: 冷却到什么时候
    cooldown_until: float = 0.0
    #: 待结算的两拍（-1 = 没有待办）
    buff_at: float = -1.0
    hit_at: float = -1.0
    #: 本次增益数值
    bonus_atk: float = 0.0
    #: 触发次数与累计伤害——报告里要用
    triggers: int = 0
    total_damage: float = 0.0
    #: 因为"有敌人没倒地"而错过的检测次数（诊断用）
    blocked_checks: int = 0

    _next_check: float = 0.0
    _last_blocker: str = ""

    @property
    def armed(self) -> bool:
        """有没有正在等待结算的触发。"""
        return self.buff_at >= 0.0 or self.hit_at >= 0.0

    def trigger_value(self, ally_atk_sum: float) -> float:
        """一次总攻击的伤害 = 15000 + 全队角色类干员攻击力总和。"""
        return (self.base_atk + ally_atk_sum) * self.atk_scale

    def tick(self, t: float, *, down_states: list[tuple[bool, str]],
             ally_atk_sum: float) -> tuple[bool, bool]:
        """推进一拍。返回 `(本拍发出增益, 本拍打出伤害)`。

        `down_states` 是场上所有**带相性**敌人的 `(是否倒地, 名字)`。
        空列表表示场上没有带相性的敌人——按机制"全部倒地"在空集上不成立，
        所以也**不触发**（避免清完场反而刷伤害）。
        """
        fired_buff = fired_hit = False

        # --- 结算已经排定的两拍 ---
        if self.buff_at >= 0.0 and t >= self.buff_at:
            self.bonus_atk = self.trigger_value(ally_atk_sum)
            self.buff_at = -1.0
            self.triggers += 1
            fired_buff = True
        if self.hit_at >= 0.0 and t >= self.hit_at:
            self.hit_at = -1.0
            self.cooldown_until = t + self.trigger_cd
            fired_hit = True

        if self.armed or t < self.cooldown_until:
            return fired_buff, fired_hit

        # --- 每 0.1 秒检测一次全场是否都倒地 ---
        # 用时间戳而不是累加固定帧长：调用方的帧长不是契约的一部分，
        # 累加会在第一帧就漏掉一次判定，也会随帧率漂移。
        if t < self._next_check:
            return fired_buff, fired_hit
        self._next_check = t + self.check_interval

        if not down_states:
            self.blocked_checks += 1
            self._last_blocker = "场上没有带相性的敌人"
            return fired_buff, fired_hit
        standing = [name for down, name in down_states if not down]
        if standing:
            self.blocked_checks += 1
            self._last_blocker = standing[0]
            return fired_buff, fired_hit

        # 全场倒地 → 排两拍
        self.buff_at = t + self.buff_delay
        self.hit_at = t + self.hit_delay
        return fired_buff, fired_hit

    def to_dict(self) -> dict:
        return {"triggers": self.triggers,
                "total_damage": round(self.total_damage, 1),
                "bonus_atk": round(self.bonus_atk, 1),
                "blocked_checks": self.blocked_checks,
                "last_blocker": self._last_blocker}
