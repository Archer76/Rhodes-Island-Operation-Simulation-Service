"""职业特性（`character_table` 的 `trait`）里**已核实**的机制。

数据出处与 `operator_trait` 表同源，但这里走**原始 JSON**：`OperatorCalculator.
character()` 已经把整张 `character_table` 读在内存里，`verify` 构造战斗单位时
就在手边，再绕一趟库没有好处。结构是：

```
character_table[char_id]["trait"]["candidates"][i]["blackboard"]
    = [{"key": "attack@ability_range_radius", "value": 1.0}, ...]
```

（注意是单数 `trait`，不是 `traits`——`traits` 那张表在当前 gamedata 里是 `null`。
`operator_trait` 表把同一份数据摊平成 `{键: 值}`，两处**互为副本**。）

## 第一条也是唯一一条：撼地者「攻击使目标周围的其他敌人受到 50% 群体物理伤害」

撼地者四位（怒潮凛冬 / 佩佩 / 奥达 / 祐天寺若麦）共用**逐字相同**的特性黑板：

```
{"attack@ability_range_radius": 1.0, "attack@atk_scale_2": 0.5}
```

特性正文（`character_table.description`）：

> 攻击使目标周围的其他敌人受到相当于攻击力 50% 的**群体**物理伤害

`atk_scale_2` 在这里就是那个 50%。**这个键名同名反义**（空弦是"另一组目标"、
雪猎是"对非移动敌人"、丰川祥子是"第 2 个音符"），所以判据不看键名，
看**它和 `ability_range_radius` 同时出现在特性黑板里**这个形状。

### 溅射范围：半径 1.0 的**重叠判定**

prts.wiki「怒潮凛冬」页备注原文（2026-09-18 实取）：

> ※高台溅射效果为独立于攻击的效果，其以该次攻击中心为中心，选择 1.0 半径内的
> 地块触发溅射（**重叠判定**），伤害溅射范围为周围 4 格 + 本格（**格子判定**）

一句话里并列了两种判定，这是**两种不同的几何**，不能互相顶替：

* **重叠判定**（`splash_tiles`）——以攻击中心为圆心、给定半径的圆**盖到**的地块。
  圆心落在格内任意位置时，四个斜邻格的近角距圆心最远也只有 √2/2 ≈ 0.707，
  **仍在半径 1.0 之内**，所以半径 1.0 的溅射实打实是 **3×3 九格**，
  而不是十字五格。半径小于 0.707 时斜邻才会先掉出去。
* **格子判定**（`cross_cells`）——固定范围码。本文件涉及的 `x-5` 在
  `attack_range` 表里是 `[[-1,0],[0,-1],[0,0],[0,1],[1,0]]`，即「周围 4 格 + 本格」
  的十字五格。天赋「汹涌怒火」的高台溅射用的是这**一种**。

两种判定在同一支特性上各管一段：**特性溅射（打到敌人）走重叠判定**，
**天赋的高台溅射（由高台向四周地面扩散）走格子判定**。照抄任意一种到另一段
都会错，而且错得看不出来——两者在"目标站在格心"时只差四个斜邻。

### 天赋「汹涌怒火」的两半

```
怒潮凛冬 天赋1（精2）：damage_scale 1.24  attack@splash_atk_scale 0.24  attack@sluggish 0.5
                       潜能 5 起 splash_atk_scale 变 0.27
```

* `damage_scale`（1.24）——「特性溅射造成的物理伤害提升 24%」，**倍率**提升。
  落点是**特性溅射**：0.5 × 1.24 = **0.62**。
  wiki 备注另有一句「且不对特性主目标生效」——主目标吃的是普攻本身（100%），
  本来就不在这条溅射里，所以这里不需要额外排除，但注释留档以免后来者
  再把 1.24 乘到主目标头上。
* `attack@splash_atk_scale`（0.24）——「溅射到的每个**高台**对周围四格所有**地面**
  敌人造成相当于攻击力 24% 的物理伤害」，这是一次**独立于攻击**的效果。
* `attack@sluggish`（0.5）——同一句尾巴上的「和 0.5 秒停顿」。
  精 1 时该键为 0（那一档正文里没有停顿），所以**读 0 就是没有**，
  不能按"有键就算有停顿"处理。

**未建模**（如实记下）：高台之间的**扩散**（技能 3 才有）、高台溅射 0.1 秒内置延迟、
「被视为远程途径伤害 / 无来源击杀」，以及模组对 `splash_atk_scale_bonus` 的改写。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

__all__ = [
    "SPLASH_RADIUS_KEY",
    "SPLASH_SCALE_KEY",
    "SPLASH_TALENT_KEYS",
    "SPLASH_TALENTS",
    "COMBO_ATTACK_KEYS",
    "COMBO_HITS",
    "HP_DRAIN_TRAIT",
    "HP_DRAIN_KEY",
    "TraitSplash",
    "ComboAttack",
    "read_trait_splash",
    "apply_splash_talent",
    "is_splash_talent",
    "read_combo_attack",
    "read_hp_drain",
    "splash_tiles",
    "cross_cells",
]

#: 怪杰（`geek`）特性正文——**自身生命会不断流失**。它不是"某个干员"的特征，
#: 而是一个**子职业**的特性，所以判据按这段正文 + 黑板键，不按干员名。
#:
#: 为什么非要这段正文一起判：**只按黑板键会多认三条**。全库特性黑板里带
#: `hp_ratio` 的有 4 条——三位怪杰（新约能天使 / 阿 / 空构，都是 0.01），
#: 外加一个工匠的 `token_10027_ironmn_pile3`（它的意思是「可被我方干员攻击但
#: 不受伤害，受到工匠干员攻击时回复生命」，与流失毫无关系）。
#: 两条合起来（正文 + 键）正好落到那三位怪杰身上。
HP_DRAIN_TRAIT = "自身生命会不断流失"
#: 流失速率的键：**每秒**流失**生命上限**的这个比例（三位怪杰都是 0.01）。
HP_DRAIN_KEY = "hp_ratio"

#: 特性溅射的**半径**（格）。撼地者四位都是 1.0。
SPLASH_RADIUS_KEY = "attack@ability_range_radius"

#: 特性溅射的**倍率**（攻击力的比例）。撼地者四位都是 0.5。
SPLASH_SCALE_KEY = "attack@atk_scale_2"

#: 「汹涌怒火」那一族的黑板指纹。`damage_scale` 与 `attack@splash_atk_scale`
#: 同时出现才认——单看 `damage_scale` 会误中别的"伤害倍率"天赋。
SPLASH_TALENT_KEYS = ("damage_scale", "attack@splash_atk_scale")

#: 具名检测器。审计的第三道筛子按**天赋名字**判有没有人读它，
#: 所以名字必须作为字面量留在源码里；但**判据仍然是键**（见上）。
SPLASH_TALENTS = frozenset({"汹涌怒火"})

#: 「普攻连击 + 结算后缩放」的指纹：`attack@atk_scale` 与 `attack@damage_scale`
#: **同时**出现在同一条**隐藏天赋**（`name` 为 null）的黑板里。
COMBO_ATTACK_KEYS = ("attack@atk_scale", "attack@damage_scale")

#: 焰狐龙梓兰一次普攻打几击。
#:
#: **黑板里没有这个 3**——它硬编码在攻击预制体里，黑板只给了每击倍率
#: （`attack@atk_scale` = 1.0）与结算后的缩放（`attack@damage_scale` = 0.333）。
#: 出处是 prts.wiki「焰狐龙梓兰」页的 `|特性备注=` 原文：
#:
#: > 焰狐龙梓兰的普通攻击为**三连击**，每击造成攻击力 100% 的物理伤害。
#: > 在每次输出伤害时会对其进行检测，若为普通攻击的伤害，则使该伤害降低至
#: > 33.3%（也即计算防御/法抗后，伤害 ×33.3%，因此焰狐龙梓兰每轮普通攻击
#: > 会少造成 0.1% 的伤害）
#:
#: 最后那句同时是**交叉验证**：3 × 0.333 = 0.999，恰好少 0.1% ✓。
COMBO_HITS = 3


def _pairs_to_dict(pairs: Any) -> dict[str, float]:
    """把 `[{"key":…, "value":…}]` 摊平成 `{键: 值}`。

    `valueStr` 一律是 `null`（数值都在 `value`），忽略即可；
    取不到 value 的条目直接跳过，不塞 0——0 与"没有这个键"在下面所有
    判据里含义相反。
    """
    out: dict[str, float] = {}
    for item in pairs or ():
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if key and isinstance(value, (int, float)):
            out[str(key)] = float(value)
    return out


def read_trait_splash(char: dict) -> TraitSplash | None:
    """从干员本体里读出「特性溅射」。没有这个形状就返回 None。

    判据只有一条：**特性黑板上同时有 `attack@ability_range_radius` 与
    `attack@atk_scale_2`**。不是按子职业名，也不是按干员名——特性是
    **数据**，子职业名是**文案**，后者会随版本改名而前者不会。
    """
    trait = (char or {}).get("trait") or {}
    for cand in trait.get("candidates") or ():
        if not isinstance(cand, dict):
            continue
        bb = _pairs_to_dict(cand.get("blackboard"))
        if SPLASH_RADIUS_KEY in bb and SPLASH_SCALE_KEY in bb:
            return TraitSplash(radius=bb[SPLASH_RADIUS_KEY],
                               scale=bb[SPLASH_SCALE_KEY])
    return None


def read_hp_drain(char: dict) -> float:
    """读出「自身生命会不断流失」（怪杰特性）的**速率**：每秒流失生命上限的几成。

    没有这条特性就返回 0.0（调用侧不用判 None——这个量"没有"就是 0）。

    判据两段，缺一不可（理由见 `HP_DRAIN_TRAIT` 的注释）：
    ① 特性正文（`char["description"]`）含「自身生命会不断流失」；
    ② 特性黑板里有 `hp_ratio` 且为正。

    出处：prts.wiki「新约能天使」页的 `|备注=` **没有提这条特性**
    （它讲的全是天坠/弹药那套），所以速率只能取黑板那个 0.01；
    与 `docs/uncertainties.md` 里先前的记录一致（「每秒流失 1% 生命上限」）。
    """
    if HP_DRAIN_TRAIT not in str((char or {}).get("description") or ""):
        return 0.0
    for cand in ((char or {}).get("trait") or {}).get("candidates") or ():
        if not isinstance(cand, dict):
            continue
        bb = _pairs_to_dict(cand.get("blackboard"))
        rate = float(bb.get(HP_DRAIN_KEY) or 0.0)
        if rate > 0.0:
            return rate
    return 0.0


def read_combo_attack(char: dict) -> ComboAttack | None:
    """读出「普攻连击 + 结算后缩放」。没有这个形状就返回 None。

    判据：**某一条隐藏天赋**（`name` 为 null）的黑板里**同时**有
    `attack@atk_scale` 与 `attack@damage_scale`。

    为什么按"隐藏天赋 + 键的组合"认，而不按干员名或子职业：

    * 焰狐龙梓兰的 `character_table.trait` 是**空的**、`operator_trait` 表也**没有行**
      （她的特性文字就是猎手共同的「高精度的近距离射击」）。这条机制住在
      **隐藏天赋**里（`is_hide_talent=1`、`name`/`description` 都是 null），
      所以审计的两道筛子都照不到它，第三道（按天赋名）更看不见——
      **PRTS 的 `|特性备注=` 才是它的出处**。
    * `attack@damage_scale` 这个键名**同名反义**（撼地者「汹涌怒火」的
      `damage_scale` 是"溅射伤害 +24%"），单看键名会误中。同时要求
      `attack@atk_scale` 在场，且 `damage_scale < 1`（这里是"降低至"），才是这条。

    每击倍率取自 `attack@atk_scale`（1.0），**击数取 `COMBO_HITS`**（黑板里没有，
    出处见该常量的文档）。
    """
    for tal in (char or {}).get("talents") or ():
        for cand in tal.get("candidates") or ():
            if not isinstance(cand, dict) or cand.get("name"):
                continue
            bb = _pairs_to_dict(cand.get("blackboard"))
            if not all(k in bb for k in COMBO_ATTACK_KEYS):
                continue
            scale = float(bb["attack@damage_scale"])
            if not 0.0 < scale < 1.0:
                # 「提升至」式的大于 1 是别的东西（溅射增伤那一族），不认。
                continue
            return ComboAttack(hits=COMBO_HITS,
                               hit_scale=float(bb["attack@atk_scale"]),
                               damage_scale=scale)
    return None


def is_splash_talent(t: Any) -> bool:
    """这条天赋是不是「汹涌怒火」那一族。"""
    if str(getattr(t, "name", "")) in SPLASH_TALENTS:
        return True
    bb = getattr(t, "blackboard", None) or {}
    return all(k in bb for k in SPLASH_TALENT_KEYS)


def apply_splash_talent(splash: TraitSplash | None, talents) -> TraitSplash | None:
    """把「汹涌怒火」的两半叠到特性溅射上。

    只认**第一条**命中的天赋：这几位都只有一条（另一条是「万众巨潮」，
    键是 `atk`/`def`，不会被指纹误中）。
    """
    if splash is None:
        return None
    for t in talents or ():
        if not is_splash_talent(t):
            continue
        bb = getattr(t, "blackboard", None) or {}
        return TraitSplash(
            radius=splash.radius,
            scale=splash.scale,
            damage_scale=float(bb.get("damage_scale", 1.0)),
            highland_scale=float(bb.get("attack@splash_atk_scale", 0.0)),
            highland_sluggish=float(bb.get("attack@sluggish", 0.0)),
        )
    return splash


def cross_cells(cell: tuple[int, int]) -> set[tuple[int, int]]:
    """「周围 4 格 + 本格」——**格子判定**。范围码 `x-5` 就是它。"""
    x, y = int(cell[0]), int(cell[1])
    return {(x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)}


@dataclass(frozen=True)
class TraitSplash:
    """一条特性溅射的**已解释**参数（纯数据）。

    `damage_scale` 只乘在**溅射**上，不乘主目标（见模块文档）。
    """

    radius: float
    scale: float
    damage_scale: float = 1.0
    highland_scale: float = 0.0
    highland_sluggish: float = 0.0

    @property
    def effective_scale(self) -> float:
        """特性溅射真正用的倍率：`scale × damage_scale`（0.5 × 1.24 = 0.62）。"""
        return self.scale * self.damage_scale


@dataclass(frozen=True)
class ComboAttack:
    """一次普通攻击的**连击结构**（纯数据）。焰狐龙梓兰：3 击 × 100%，结算后 ×33.3%。

    `damage_scale` 的性质与溅射那条相反：它乘在**主目标**上，而且是在
    **计算防御/法抗之后**（`resolve_damage` 的输出上），不是倍率菜单里的一项。
    """

    hits: int
    hit_scale: float
    damage_scale: float


def splash_tiles(center: tuple[float, float], radius: float) -> set[tuple[int, int]]:
    """以 `center` 为心、`radius` 为半径的圆**盖到的地块**——**重叠判定**。

    依据是 prts.wiki「怒潮凛冬」页备注的一句话（原文见模块文档）。落成几何：

    * 地块 `(x, y)` 是以 `(x, y)` 为心、边长 1 的正方形（`EnemyUnit.cell()`
      把连续坐标四舍五入到整数格，说明格心就在整数点上）；
    * 格被盖到 ⟺ 圆心到该正方形的**最近点**距离 ≤ 半径；
    * 「最近点距离」按分量算：`max(|dx| - 0.5, 0)` 是两个轴上的越出量，
      取欧氏范数。

    因此半径 1.0 时斜邻格（近角距 √2/2 ≈ 0.707）**在内**——
    这就是"3×3 九格"的来历，不是十字五格。半径 ≤ 0.707 时斜邻才掉出去。
    """
    x, y = float(center[0]), float(center[1])
    r = float(radius)
    if r < 0.0:
        return set()
    base_x, base_y = math.floor(x), math.floor(y)
    reach = int(math.ceil(r + 0.5))
    out: set[tuple[int, int]] = set()
    for dx in range(-reach, reach + 1):
        for dy in range(-reach, reach + 1):
            tx, ty = base_x + dx, base_y + dy
            gx = max(abs(x - tx) - 0.5, 0.0)
            gy = max(abs(y - ty) - 0.5, 0.0)
            if math.hypot(gx, gy) <= r + 1e-9:
                out.add((int(tx), int(ty)))
    return out
