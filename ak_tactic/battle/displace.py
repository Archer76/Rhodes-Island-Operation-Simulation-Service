"""位移：推与拉的判定规则（受力等级 → 理想位移）。

## 为什么单独一个模块

位移的**规则**与位移的**接线**是两件事。规则是查数据源查出来的定值表，
可以纯函数化、可以逐值证伪；接线要动敌人"沿路线推进"的表示（`unit.py`
里位置是从 `progress` 算出来的），那是另一件事。先把规则钉死，接线才有
可依据的东西。

## 出处

**PRTS「推与拉」页**（`作战机制#敌方的位移` 嵌入的就是它）：

* 受力等级 = 「力度对应表」与目标重量的**差值**。
  原文：「由[[游戏数据基础#重量公式|力度对应表]]和目标的重量可以得到一个
  差值，这个差值为受力等级。」
* 推力**作用时间瞬间**，「可以直接视为目标得到了一个大小等于"实际受力×1s"
  的动量」。
* 推力分**方向力**（沿设定方向，如推击手）与**径向力**（沿干员→目标的射线），
  两者都**不做修正**。
* **特殊修正**：在方向力的前提下，「如果目标与干员的连线和部署方向的夹角
  **大于 45°** 或**距离小于 0.25 格**，该方向力会被修正为径向力，且
  **受力等级 -2**」。
* 理想位移表见下（`PUSH_IDEAL`）——**弹道类与特效类不同**，因为命中帧的
  失衡位移结算顺序差一帧：「通常弹道类技能会比同力度下的特效类技能推出更
  远的距离」。

**PRTS「游戏数据基础」页**另有一张**近似**表（`PUSH_APPROX`，1.7 / 2.14 /
2.96 / 3.53），标注为"以力学模型计算出的近似值"。两张表并存：
精度取 `PUSH_IDEAL`，**时间**取 `PUSH_APPROX`（前者不带时间）。

## 量纲

位移是**格**，且是**连续值**（0 级力度对 0 重量 = 1.6958 格，不是 1 格也不是
2 格）。把它当整数格处理会系统性偏错，尤其 ≥3 那一档的 3.52 与 3.33。
"""

from __future__ import annotations

__all__ = [
    "FORCE_BY_DESC", "PUSH_IDEAL", "PUSH_APPROX", "PULL_APPROX",
    "needs_radial_correction", "pull_offset", "pull_time", "push_distance",
    "push_time", "skill_force_level", "source_note",
]

#: 「力度对应表」：描述 → 力度等级。
#: 出自 PRTS「游戏数据基础#力度对应表」。技能黑板里的 `force` 用的就是这套。
FORCE_BY_DESC: dict[str, int] = {
    "微小力": -1,   # 稍微
    "小力": 0,
    "中力": 1,
    "较大力": 2,
    "大力": 3,
    "大力+1": 4,
    "特大力": 5,
}

#: 推力理想位移（格），按**受力等级**查。值为 `(弹道类, 特效类)`。
#: 出自 PRTS「推与拉#推力：推开」。比 `PUSH_APPROX` 精确，且区分弹道/特效。
PUSH_IDEAL: dict[int, tuple[float, float]] = {
    -2: (0.11825, 0.08492),
    -1: (0.44030, 0.37363),
    0: (1.69580, 1.56247),
    1: (2.13705, 1.98705),
    2: (2.95013, 2.77347),
    3: (3.52392, 3.33058),
}

#: 推力位移**时间**（秒），按受力等级查。出自 PRTS「游戏数据基础
#: #推力-位移近似对应表」——精确表不带时间，这里只能取近似表的时间。
PUSH_APPROX: dict[int, tuple[float, float]] = {
    # 受力等级: (位移长度格, 位移时间秒)
    -2: (0.12, 0.2),
    -1: (0.44, 0.4),
    0: (1.70, 0.8),
    1: (2.14, 0.9),
    2: (2.96, 1.0667),
    3: (3.53, 1.1667),
}

#: 拉力，按受力等级查 `(拉力, 位移描述, 时间秒)`。
#: 出自 PRTS「游戏数据基础#拉力-位移近似对应表」。
#: 注意 0 级及以上是**必定拉至身前**（初始距离 < 89 时），不是"走固定格数"。
PULL_APPROX: dict[int, tuple[float, float | None, float | None]] = {
    -2: (2.0, 0.03, 0.5),     # 拉力小于摩擦力，敌人只会缓慢蠕动
    -1: (10.0, None, None),   # 0.35 倍初始距离，时间 max(0.65*sqrt(d), 1.0)
    0: (40.0, None, None),    # 必定拉至身前
    1: (42.0, None, None),
    2: (44.0, None, None),
    3: (46.0, None, None),
}

_FLOOR = -3   # 受力等级 ≤ 此值时完全不位移
_CEIL = 3     # 受力等级 ≥ 此值时取最高档


def source_note() -> str:
    """一句话说明这些数从哪来——给报错信息和文档用，避免数被搬走后失传。"""
    return "PRTS「推与拉#推力：推开」与「游戏数据基础#力度对应表」"


def _bucket(level: int) -> int:
    """把受力等级夹到查表用的档位（表里只有 -2..3，两端是开区间）。"""
    return max(_FLOOR, min(_CEIL, int(level)))


def skill_force_level(force: float, base_force_level: float = 0.0) -> int:
    """由技能黑板的 `force` 与干员的**基础力度**得到力度等级。

    推击手一类干员本身带 `baseForceLevel`，技能的 `force` 是**加在它上面**的；
    其余干员基础力度为 0，`force` 即力度等级。两类都用这一个式子，差别只在
    传不传 `base_force_level`。
    """
    return int(round(float(force) + float(base_force_level)))


def needs_radial_correction(*, angle_deg: float, distance: float) -> bool:
    """方向力是否被「特殊修正」成径向力（并因此 **受力等级 -2**）。

    原文条件：方向力、且（与部署方向夹角 > 45° 或 距离 < 0.25 格）时成立。
    两者是**或**关系——近到 0.25 格以内也会被改判，这一条容易漏。
    """
    return distance < 0.25 or angle_deg > 45.0


def push_distance(force_level: int, weight: float, *,
                  ballistic: bool = False) -> float:
    """推力的**理想**位移（格）。

    :param force_level: 力度等级（`skill_force_level` 的结果）
    :param weight: 目标重量等级（gamedata 的 `massLevel`，`enemy.weight`）
    :param ballistic: True = 弹道类（如温蒂、阿消的技能），False = 特效类
        （如食铁兽、见行者）。**弹道类比同力度特效类推得更远**：命中帧多一帧
        以初速度做的失衡位移。

    受力等级 = 力度等级 − 重量等级。
    """
    level = _bucket(force_level - int(round(float(weight))))
    if level <= _FLOOR:
        return 0.0
    return PUSH_IDEAL[level][0 if ballistic else 1]


def push_time(force_level: int, weight: float) -> float:
    """推力位移的持续时间（秒）。取自近似表——精确表不带时间。"""
    level = _bucket(force_level - int(round(float(weight))))
    if level <= _FLOOR:
        return 0.0
    return PUSH_APPROX[level][1]


def pull_offset(force_level: int, weight: float, distance: float) -> float | None:
    """拉力的位移（格）。**返回 None 表示"必定拉至身前"**。

    `distance` 是目标与拉力起点的初始距离（格）。0 级及以上一律拉至身前，
    此时返回值是 None 而不是某个格数——用 0.0 或 `distance` 顶替都会把
    "拉过来"静默变成"没拉动"。

    -1 级是 **0.35 倍初始距离**（初始距离 0-4 格内近似成立）。
    -2 级只蠕动 0.03 格。
    """
    level = _bucket(force_level - int(round(float(weight))))
    if level <= -3:
        return 0.0
    if level >= 0:
        return None
    if level == -2:
        return 0.03
    return 0.35 * float(distance)


def pull_time(force_level: int, weight: float, distance: float) -> float:
    """拉力持续时间（秒）。0 级及以上无固定值（拉至身前即止），返回 0.0。

    原文：作用时间默认 1s；**受力等级 < -1 时改为 0.5s**；-1 级为
    ``max(0.65 * sqrt(初始距离), 1.0)``。
    """
    level = _bucket(force_level - int(round(float(weight))))
    if level >= 0:
        return 0.0
    if level <= -2:
        return 0.5
    return max(0.65 * (float(distance) ** 0.5), 1.0)
