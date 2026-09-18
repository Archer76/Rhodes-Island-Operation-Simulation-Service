"""干员技能：从 `skill_table.json` 取出可用的技能数据。

## 数据在哪

`excel/skill_table.json`（11.4 MB，1810 条）——**只有 GitHub 镜像有**，
和属性计算用的是同一批表，所以这里沿用 `OperatorCalculator` 的取数方式。

表是**扁平**的：顶层键就是 skillId，不是 `{"skills": {...}}` 那种包一层。
三种前缀：

| 前缀 | 条数 | 是什么 |
| --- | --- | --- |
| `skchr_` | 901 | 干员技能，`skchr_<代号>_<1/2/3>` |
| `sktok_` | 881 | 召唤物/装置技能 |
| `skcom_` | 28 | 通用技能，敌人与 BOSS 在用 |

**哪几个技能属于谁**要去 `character_table.json` 查：干员的 `skills` 数组就是
技能槽 1/2/3，每项带 `skillId` 与 `unlockCond.phase`。同名干员的升变形态是
不同 charId（阿米娅 → `char_002_amiya` / `amiya2` / `amiya3`），技能不串。

## 等级的编号——两套数字，别混

`levels` 恒为 10 项（少数内部技能是 1 项）：索引 0–6 是 Lv1–Lv7，
索引 7/8/9 是专精一/二/三。所以：

```
索引 = level - 1                (level 1..7)
索引 = 6 + mastery              (mastery 1..3)
```

本模块统一用 `resolve_index(level, mastery)` 换算，对外只暴露人看得懂的
`Lv7` / `专精三`。

## 三个必须小心的地方

**一、`base_attack_time` 是加算秒数，不是倍率。** 实测取值散布在
−2.4 到 +3.1 之间，且**负值远远居多**（−0.5 出现 65 次、−0.7 出现 44 次），
与描述里的「攻击间隔缩短」一致；正值如斑马的 +1.3 对应「停止攻击并专心治疗」，
机械师的 +2.3 对应「攻击间隔大幅增大」。所以它是 `间隔 += 该值`。

**二、范围改写有两个来源。** 大多数技能写在 `levels[].rangeId`（2788 处），
但有 **44 处只写在黑板里**：`{"key":"range_id","value":0,"valueStr":"3-3"}`——
真值在 `valueStr` 而不是 `value`。只读 `rangeId` 会漏掉史尔特尔、圣约送葬人
这类"技能期间攻击范围扩大"的干员。本模块两个都查。

**三、`attack@trigger_time` 只在弹药类技能里是"弹药数"。** 它总共有 320 处，
大部分是"触发间隔"；只有 `durationType == "AMMO"` 时才是弹药数
（圣约送葬人：「攻击装有{attack@trigger_time}发弹药」）。判据是 durationType，
不能只看键名。

## 效果字段——只解析能确定的，其余原样留着

黑板有 **1020 个不同的键**，想全部赋予战斗语义是不现实的。本模块的做法是
把键分成四类装箱（`buffs` / `damage` / `control` / `other`），只对能确定
语义的做解释，剩下的进 `other` 原样保留。`SkillEffects.coverage()` 会报告
"有多少次使用被成功归类"，所以覆盖面是可量化的，而不是假装全懂。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable

from ..gamedata.source import GITHUB_BASE, GameDataSource, GamedataError

__all__ = [
    "SkillBook",
    "SkillError",
    "OperatorSkill",
    "SkillLevel",
    "SkillEffects",
    "SP_TYPE_CN",
    "SKILL_TYPE_CN",
    "LEVEL_LABELS",
    "resolve_index",
    "render_description",
    "format_value",
    "parse_effects",
]

#: `levels` 的 10 个位置对应的人话
LEVEL_LABELS = ("Lv1", "Lv2", "Lv3", "Lv4", "Lv5", "Lv6", "Lv7",
                "专精一", "专精二", "专精三")

#: 技能的触发方式
SKILL_TYPE_CN = {"AUTO": "自动触发", "MANUAL": "手动触发", "PASSIVE": "被动"}

#: 技力回复方式。`8` 是 PASSIVE 技能用的哨兵值（无技力），不是第四种回复。
SP_TYPE_CN = {
    "INCREASE_WITH_TIME": "自动回复",
    "INCREASE_WHEN_ATTACK": "攻击回复",
    "INCREASE_WHEN_TAKEN_DAMAGE": "受击回复",
    "PASSIVE": "被动（无技力）",
}

#: 归一化后的技力回复方式
SP_AUTO = "INCREASE_WITH_TIME"
SP_ATTACK = "INCREASE_WHEN_ATTACK"
SP_HIT = "INCREASE_WHEN_TAKEN_DAMAGE"
SP_NONE = "PASSIVE"

#: `durationType` 的两种取值
DURATION_CN = {"NONE": "计时", "AMMO": "弹药"}

#: 攻速（攻速属性，基准 100）的下限。2026-09-16 博士裁定取 20
#: （wiki 写 20、xulai1001/akdata 写 10）。不夹的话减速叠满会把间隔拉到无穷大。
ASPD_MIN = 20.0


class SkillError(RuntimeError):
    """查不到技能，或数据源缺表。"""


# ---------------------------------------------------------------- 等级换算

def resolve_index(level: int = 7, mastery: int = 0) -> int:
    """把（技能等级, 专精）换算成 `levels` 的下标。

    :param level: 1–7，技能的普通等级
    :param mastery: 0–3，专精等级；0 表示未专精
    """
    if mastery:
        if not (1 <= mastery <= 3):
            raise SkillError(f"专精等级只能是 1/2/3，收到 {mastery}")
        return 6 + mastery
    if not (1 <= level <= 7):
        raise SkillError(f"技能等级只能是 1–7，收到 {level}")
    return level - 1


# ------------------------------------------------------ 描述文本的变量替换

_PLACEHOLDER_RE = re.compile(r"\{([^{}]+)\}")
_TAG_RE = re.compile(r"</?[^>]+>")


def format_value(value: float, spec: str = "") -> str:
    """按描述里的格式串渲染一个数值。

    游戏里只有五种格式：`0%`、`0.0%`、`0.0`、`0`，以及**不写格式串**。
    前四种按 .NET 的数值格式理解（`%` 会乘 100）；不写格式串时按
    "整数就不显示小数点"处理。
    """
    if spec == "0%":
        return f"{value * 100:.0f}%"
    if spec == "0.0%":
        return f"{value * 100:.1f}%"
    if spec == "0.0":
        return f"{value:.1f}"
    if spec == "0":
        return f"{value:.0f}"
    if value == int(value):
        return str(int(value))
    return f"{value:g}"


#: 富文本标签。**扫描描述前必须先剥掉它**——标签会插在词中间，例如
#: 影霄·绝影的 `为<@ba.vup>真实</>伤害`，原样扫「真实伤害」是扫不到的。
_TAG = re.compile(r"<[^>]+>")


def _wants_true_damage(description: str) -> bool:
    """这一击是不是真实伤害——**只能从描述判**。

    黑板里没有伤害类型字段：`atk_scale 3.8` 只说倍率，不说它是物理、法术
    还是真实。游戏把这件事写进了技能描述的自然语言里，所以这里扫描述。

    判据是**「伤害类型变为真实」**，不是「真实伤害」。这两个措辞在数据里
    指向完全不同的东西：

    - 「伤害类型变为真实」= **这一击的类型被改写**，整条技能的攻击都变真实。
      标本：阿米娅技3「奇美拉」、Mon3tr、耀骑士临光（「攻击时伤害类型变为真实」）。
      原文写作 `伤害类型变为<@ba.vup>真实</>`，所以必须先剥标签。
    - 「造成 N 点真实伤害」= **一次附加伤害**，与本身是什么类型无关。
      标本：装置自爆、脉冲波、「移动时受到正比于距离的真实伤害」、
      「攻击时额外造成相当于 50% 攻击力的真实伤害」，以及敌人对**我方**
      造成的真实伤害。

    用「真实伤害」当判据会**双向出错**（2026-09-16 实测，全表 1590 条去重
    技能等级描述）：旧写法命中 29 条，其中 **28 条是上述附加伤害的误判**
    （会把整条技能的攻击都算成真实，严重高估），同时漏掉 8 条真正的类型
    改写。改用下面这条后命中 9 条，逐条核对皆真。

    **2026-09-18 补第二条**：凯尔希·思衡托技2「保护性拒止」原文是

        攻击变为射出医疗单元（优先选择敌人），击中时对目标周围所有敌人
        造成相当于攻击力 380% 的真实伤害

    她的**攻击本身**就是那枚医疗单元，所以这一击的伤害整条都是真实的；
    只是措辞带了「击中时」，被上一条判据漏掉——她那一击此后还要吃防御与法抗。
    补的判据要求三个条件**同时**成立（「攻击变为」+「相当于攻击力」+「真实伤害」），
    因为「攻击变为…」才说明"这一击被换掉了、下面写的就是它的伤害"。
    全表（level=10 去重）核对：新增命中**只有她这一条**；另外三条含
    「真实伤害」的——微尘「碰撞敌方单位时造成」、敌人「每秒受到 X 点」、
    耀阳「部署时对周围四格敌人造成」——都不含「攻击变为」，保持不认。
    """
    plain = _TAG.sub("", description or "")
    if "伤害类型变为真实" in plain:
        return True
    return ("攻击变为" in plain and "相当于攻击力" in plain
            and "真实伤害" in plain)
_REPEAT_HITS = re.compile(r"造成(\d+)次攻击力")


def _repeat_hits(description: str) -> int:
    """从描述里取连击数——**黑板里没有这条**。

    标本：赤刃明霄陈技3「赤霄·天喟」的原文是

        每次攻击对最多 4 名地面敌人造成 **3 次**攻击力 210% 的法术伤害

    而它的黑板只有 `attack@atk_scale 2.1` 与 `attack@max_target 4`，
    **没有 `times`**：那个 3 是硬写在描述正文里的。只读黑板会把这一击
    按 210%×1 算，**少算三分之二**。

    判据收得很紧（`造成N次攻击力`，且只在黑板没有 `times` 时兜底）：
    全表 1.1 万个技能里只有这一条命中，所以它不会波及其它干员。
    """
    m = _REPEAT_HITS.search(_TAG.sub("", description or ""))
    return int(m.group(1)) if m else 0


#: 中文数字。语料里「攻击变为二连击」与「攻击变为2连击」两种写法并存。
_CN_DIGIT = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
_MULTI_HIT = re.compile(r"攻击变为(?:特殊的)?([一二两三四五六七八九十]|\d{1,2})连击")


def _wants_multi_hit(description: str) -> int:
    """「攻击变为 N 连击」——技能期间每次普通攻击打 N 下。0 = 不是这一类。

    **判据必须锚在"攻击变为"这四个字上**：数据里另有几种形近写法，语义
    各不相同（2026-09-16 实测，全表 343 条含「连击」的技能描述）：

    * 「攻击变为二连击」——每次普攻打两下。**这才是本函数要收的**。
      标本：阿米娅(术战者)技1 影霄·奔夜、赤刃明霄陈技1。两者黑板里
      **都没有 `times`**，只读黑板会把二连击按单发算，伤害少一半。
    * 「……有 20% 概率**变成**二连击」——概率触发，不是稳定 N 连。
      锚在"变为"（而非"变成"）即可避开。
    * 「**下次**攻击变为三连击」——只作用于下一次攻击。当前也收：对
      模拟器而言与"每次攻击"是同一件事（那次出手打 N 下）。
    * 「攻击变为**{attack@times}连击**」——数值在黑板里，由 `times` 键
      先行覆盖，本函数不必管（机械师技1 就是这一种，`attack@times=5`）。

    `hit_count` 的优先级因此是：黑板 `times` → 本函数 → `repeat_hits`。
    黑板里有确切数值时，不去猜描述。
    """
    m = _MULTI_HIT.search(_TAG.sub("", description or ""))
    if not m:
        return 0
    tok = m.group(1)
    return int(tok) if tok.isdigit() else _CN_DIGIT.get(tok, 0)


#: 「射击 N 次，分别射出 a、b、c 支」——**一轮技能放几轮、每轮几支**。
#: 全表实测（986 条 M3 逐条核过）：这个措辞只出现在焰狐龙梓兰技2「飞翔瞪射」。
_ARROW_VOLLEYS = re.compile(r"射击(\d+)次[，,]?分别射出([\d、,，]+)支")

#: 「发射 N 支…箭矢」——单轮齐射的箭数。全表实测只出现在同一位的技1「刚射」。
_ARROW_SHOT = re.compile(r"发射(\d+)支")


def _volley_arrows(description: str) -> tuple[int, ...]:
    """每轮射出的箭数，取不到就是空元组。

    **为什么箭数要按"支"算**：能天使「过载模式」的 5 连发是既有口径——
    N 支 / N 连发 = N 次独立命中，各自吃防御（守卫 `[38]` 钉的就是这条）。
    焰狐龙梓兰技2 一次技能放三轮、每轮 3/4/5 支，共 12 支，沿用同一口径。

    她技1 的「刚连射」那 5 支**不在这里**：那一段是"额外消耗一层充能才放"，
    是否为真要看充能而不是描述，故整段留档（见 `docs/uncertainties.md`
    第十三节），本函数取到的 `(4,)` 只是基础那 4 支。

    全表逐条核过 986 条 M3：两处措辞都只出现在她身上，零波及。
    """
    text = _TAG.sub("", description or "")
    m = _ARROW_VOLLEYS.search(text)
    if m:
        nums = [int(x) for x in re.findall(r"\d+", m.group(2))]
        return tuple(nums) if nums else ()
    m = _ARROW_SHOT.search(text)
    return (int(m.group(1)),) if m else ()


def _charge_volley(description: str, bb: dict[str, float]):
    """「额外消耗 N 层施展 X：发射 M 支攻击力 P% 的箭矢」——取不到返回 None。

    返回 `(额外层数, M, P)`：她是 `(1, 5, 2.0)`。

    **为什么单独一段**：这 M 支不是"末击"、也不是"每轮"，而是**另一次出手**
    （多花一层充能换来的），所以既不能并进 `hit_count`（有没有那一层要看开技时
    的 `op.sp`），也不能塞进 `final_hit_scale`（它只管最后一笔）。模拟器里由
    `op.charge_extra_ready` + 逐笔倍率接力，见 `sim._activate` 与出手循环。

    `P` 取自 `atk_scale_2`（她 200%）——**这里可以按这个键名取**，因为判据先
    要求"描述里写了额外消耗 N 层"这个形状，键名只是取值用；单看键名会误中
    空弦/雪猎/丰川祥子等人（那个键有六种含义）。

    全表实测（986 条 M3）：这个措辞只出现在焰狐龙梓兰技1 上。
    """
    text = _TAG.sub("", description or "")
    if "额外消耗" not in text:
        return None
    m = re.search(r"额外消耗(\d+)层", text)
    if not m:
        return None
    tail = text[m.end():]
    shot = _ARROW_SHOT.search(tail)
    # 键名两种写法都要收：技1 的黑板是**裸的** `atk_scale_2`（1.6/2.0/晕眩都在
    # 裸键上），技2 那批才带 `attack@` 前缀。只看一种会把 2.0 读成 0
    # ⇒ 整段返回 None，**静默失效**——所以判据写宽、命中面靠描述那句兜住。
    scale = float(bb.get("atk_scale_2") or bb.get("attack@atk_scale_2") or 0.0)
    if not shot or scale <= 0.0:
        return None
    return int(m.group(1)), int(shot.group(1)), scale


def _hitrate_values(bb: dict[str, float]) -> tuple[float, float]:
    """读出「使敌人物理/法术**命中率**下降」的两个值（都是**负数**）。

    ⚠️ 这个键名有**两种写法**，全库各占一半，只认一种就会漏：

    * 带前缀——阿斯卡纶技3「残影」：`attack@damage_hitrate_physical` /
      `attack@damage_hitrate_magical`（−0.5 @M3）；
    * **裸键**——艾拉技1（`skchr_ela_1`）与她的两个 `sktok_ela_1` /
      `sktok_pirene_1`：`damage_hitrate_physical` / `damage_hitrate_magical`
      （−0.4 @M3）。

    这与迟钝那边踩过的是**同一个坑**（同一个量、一半带前缀一半不带），
    所以这里一次把两种都收进来。没有这个形状就返回 (0.0, 0.0)。
    """
    phys = float(bb.get("damage_hitrate_physical",
                        bb.get("attack@damage_hitrate_physical", 0.0)) or 0.0)
    arts = float(bb.get("damage_hitrate_magical",
                        bb.get("attack@damage_hitrate_magical", 0.0)) or 0.0)
    return phys, arts


def _cost_semantics(description: str, bb: dict[str, float]) -> dict[str, float]:
    """把"给费用"这条技能拆成四个互不相同的量（可露希尔那一族）。

    ⚠️ `cost` 这个键**一键多义**，全表（等级10）有 **59 条**技能带费用键，
    语义至少四种：

    | 正文写法 | 含义 | 样本 |
    | --- | --- | --- |
    | 「**立即/立刻获得**{cost}点部署费用」 | 开技**一次**给 | 德克萨斯、桃金娘、可露希尔技2 |
    | 「技能持续时间内**逐渐获得**{cost}点」 | 整个技能期**摊开**给 | 可露希尔技1 |
    | 「**每次攻击时**获得{cost}点」 | 每次命中给 | 冬时技2 |
    | 「**消耗**{cost}点部署费用」 | 反过来**扣** | 轰击术师那一族 |

    本函数只做**分类**，不改任何既有数值：返回四个量（未命中就是 0），
    由调用方决定怎么用。**不动那 59 条的全局口径**——把"消耗"误读成"获得"
    这类事超出本批十位的范围，另记留档。

    第四个量 `per_attack` 是 `cost_attack_add`（可露希尔技3 写 0.0，即"每次
    攻击额外获得 0 点"）。
    """
    text = _TAG.sub("", description or "")
    cost = float(bb.get("cost") or 0.0)
    period = float(bb.get("cost_period") or 0.0)
    gradual_text = "逐渐获得" in text
    immediate_text = ("立即获得" in text) or ("立刻获得" in text)
    # ⚠️ 判据只能用**关键词**，不能用占位符：`SkillLevel.description` 是
    # **渲染后**的正文（占位符已经代成数字，实测技2 是「立即获得10点部署费用，
    # 持续时间内逐渐获得15点部署费用」），所以 `{cost}` 那种写法根本读不到。
    # 关键词这一层足够把四义分开：一时俱在时，`cost` 归"立即"、`cost_period`
    # 归"逐渐"（技2/技3），只有"逐渐"时 `cost` 归"逐渐"（技1）。
    return {
        # 开技一次给：正文有「立即/立刻获得」才算
        "immediate": cost if (immediate_text and not gradual_text) else 0.0,
        # 开技**不许**一次性给：只有"逐渐"、没有"立即/立刻"的那些（技1）
        "suppress_immediate": gradual_text and not immediate_text,
        # 「逐渐获得」的总额：有 `cost_period` 用它（技2/技3），否则用 `cost`（技1）
        "gradual_total": period if (gradual_text and period > 0.0)
        else (cost if gradual_text else 0.0),
        # 「每次攻击时获得」这一类（`cost_attack_add`，技3 写 0.0）
        "per_attack": float(bb.get("cost_attack_add") or 0.0),
    }


#: 「逐渐获得部署费用」的发放节奏挂在哪个**变体条件**下。
#: 这是运行时真正用来选变体的名字（`effects.variants[条件名]`），
#: 不是那个 `closur_s_2[add_cost_period].interval` 全键——全键在源码里根本
#: 不会整串出现（审计 `is_read` 第 3 条也是按条件名判的）。
_ADD_COST_PERIOD = "add_cost_period"


def _cost_trickle(bb: dict[str, float],
                  variants: dict[str, dict[str, float]]) -> tuple[float, float, float]:
    """「逐渐获得」的**发放节奏**：返回（总额, 每次给多少, 间隔秒）。

    节奏取自**方括号变体** `…[add_cost_period].cost` / `.interval`——它是正文
    里「逐渐」两个字的具体兑现方式（技2：1 点 / 2.0 秒；技3：1 点 / 1.66 秒，
    乘上 30 秒正好等于 `cost_period` 的 15 / 18，两处自洽）。没有变体时返回
    `(总额, 0, 0)`，由调用方按时长均分。

    ⚠️ 两半的**住处不一样**：`.cost` 已被 `_parse_effects` 拆括号收进
    `variants["add_cost_period"]`，而 `.interval` **没有**收进去，仍以原始键名
    `closur_s_2[add_cost_period].interval` 留在 `other` 里——所以这里按条件名取
    前半、按同一个条件名拼后缀找后半。**这是个解析侧的缺口**（`interval` 那一族
    没进 variants），已记进 `docs/uncertainties.md`；先在读取侧绕过，不去改
    `_parse_effects` 的归类口径（那会影响全库同族键）。
    """
    own = variants.get(_ADD_COST_PERIOD)
    if not own:
        return (0.0, 0.0, 0.0)
    per = float(own.get("cost") or 0.0)
    suffix = f"[{_ADD_COST_PERIOD}].interval"
    found = [float(val or 0.0) for key, val in bb.items()
             if key.endswith(suffix)]
    interval = found[0] if found else 0.0
    if per <= 0.0 or interval <= 0.0:
        return (0.0, 0.0, 0.0)
    return (float(bb.get("cost_period") or 0.0), per, interval)


def _wants_lock_awake(description: str, bb: dict[str, float]) -> bool:
    """是否「开技后先「闭锁」若干秒、醒来再打」的两段式技能（泥岩技3）。

    判据两段：正文里有「无法行动」**且**黑板上有 `awake`。全表实测（全等级）：
    `awake` 只出现在 `skchr_mudrok_3` 一条技能上，且它与 `sleep` 同时出现；
    另外四条带 `sleep` 的技能（早露/深律/iris/titi）都是「让**敌人**沉睡」，
    语义完全相反——所以**不能**按 `sleep` 单独认，必须由 `awake` 定性。

    ⚠️ 这里也顺手修掉一个审计假账：`sleep` 本来被算作"有人在读"，那个读点是
    `CONTROL_KEYS` 那张**键名词表**（`skill.py` 里列键名的地方），并不是消费点。
    本函数落地之后 `sleep` 才真的有消费点。
    """
    text = _TAG.sub("", description or "")
    if "无法行动" not in text:
        return False
    return float(bb.get("awake") or 0.0) > 0.0


def _wants_enemy_hitrate(description: str, bb: dict[str, float]) -> bool:
    """是否「使（攻击范围内的）敌人物理与法术**命中率** −X%」。

    判据两段：正文里有「命中率」**且**黑板上有那两个键之一且为负。
    全表实测（全等级）：带这两个键的技能只有 4 条——阿斯卡纶技3（带前缀）、
    艾拉技1 与她的两个装置（裸键），正是这条机制的两家写法。
    """
    text = _TAG.sub("", description or "")
    if "命中率" not in text:
        return False
    phys, arts = _hitrate_values(bb)
    return phys < 0.0 or arts < 0.0


def _stand_form_of(description: str, bb: dict[str, float]) -> str:
    """结城理技1/2/3 各自进入哪个〈替身〉形态——判据是"召唤谁"。

    * **技1** → `orpheus`（〈替身·俄耳甫斯〉：治疗优先、不可对空）；
    * **技2** → `thanatos`（〈替身·塔纳托斯〉：斩杀光环、不可对空）；
    * **技3** → `thanatos_kai`（〈替身·塔纳托斯·改〉：**可对空**、弱点伤害默认
      法术；切换完毕后还能再点一次技能键换成〈俄耳甫斯·改〉——**那一次手动
      切换没有建模**，见 `docs/uncertainties.md`）。

    技3 与技2 的正文都写「塔纳托斯」，分不开，所以用**形态专属键**分开：只有技3
    带 `attack@max_target_heal`（俄耳甫斯·改的每次治疗目标数）。
    """
    if "塔纳托斯" in description:
        if float(bb.get("attack@max_target_heal") or 0.0) > 0.0:
            return "thanatos_kai"
        return "thanatos"
    if "俄耳甫斯" in description:
        return "orpheus"
    return ""


def _wants_steal_aspd(description: str, bb: dict[str, float]) -> bool:
    """是否「**立即偷取**攻击范围内 1 名**友方干员** X 点攻击速度」。

    新约能天使技2「开火成瘾症」——这是**一次性**的偷取：开技瞬间挑一名友方，
    从那一位身上**拿走** 70 点攻速给自己，持续到技能结束或她离场。

    ⚠️ 与另外三位**同族但不同机制**的技能要分开（伊内丝技2、薇薇安娜技2、
    寻澜技2）：他们写的是「每次攻击…偷取**目标**（敌人）X 点攻击速度」，
    黑板键是 `attack@steal_atk_speed` + `attack@steal_atk_speed_max`（带
    `attack@` 前缀、逐次叠层、偷敌人）；她的是**裸键** `steal` / `steal_max`、
    一次、偷友方。所以判据按**裸键**认，前缀那一家一概不认。

    全表实测：带裸键 `steal` 的技能只有她这一条。
    """
    text = _TAG.sub("", description or "")
    return ("偷取" in text and "攻击速度" in text
            and float(bb.get("steal") or 0.0) > 0.0)


def _wants_target_growth(description: str, bb: dict[str, float]) -> bool:
    """是否「每攻击 N 次后**攻击目标数 +1**（最多触发 M 次）」。

    与「攻击目标数 +1/+3」那一族**不是一回事**：那些是**静态**改写
    （落进 `max_target`，开技即生效），这一条是**按出手次数递增**的，
    所以要额外一个计数器。判据两段，缺一不可：

    ① 正文里有「攻击目标数」（全表还有 5 条写死 +1/+3 的技能，靠第 ② 段筛掉）；
    ② 黑板里有 `attack_trigger_cnt`（**每多少次出手涨一格**）。

    全表实测（level=10）：带 `attack_trigger_cnt` 的只有可露希尔技3「Q.E.D.」
    一条（9 次 / 最多 6 次），所以这条判据的命中面是 1。
    """
    text = _TAG.sub("", description or "")
    return "攻击目标数" in text and float(bb.get("attack_trigger_cnt") or 0.0) > 0.0


def _slowdown_values(bb: dict[str, float]) -> tuple[float, float, float]:
    """从黑板里取迟钝的三个数：每层比例 / 每层秒数 / 封顶。

    **两种写法都收**（`slow_down` 与 `attack@slow_down`）：技能槽标记有时
    保留前缀、有时被拆掉，这是同一个坑的第三次（贯穿弹道那条也踩过）。
    """
    def _get(name: str) -> float:
        return float(bb.get(name) or bb.get(f"attack@{name}") or 0.0)

    return (_get("slow_down"), _get("slow_down_time"), _get("slow_down_max"))


def _wants_stackable_slow(description: str, bb: dict[str, float]) -> bool:
    """是否「施加持续 X 秒的 Y% **迟钝**效果（**可叠加**，最高 Z%）」。

    迟钝是【移动速度】那一路的量（不是「停顿」，两者不可合并——既有裁定），
    而且它**按层叠加**：每层各自计时。判据三段：

    ① 正文里有「迟钝」（prts.wiki 该页 `|备注=` 把它点名为 `术语|ba.slowdown`
       ——「仅能对敌人类敌方单位施加迟钝」）；
    ② 黑板里有 `slow_down`（**每层**的减速比例）；
    ③ 黑板里有 `slow_down_time`（每层的持续秒数）。

    全表实测（level=10）：带 `slow_down` 的技能有两条，但**正文含「迟钝」的
    只有可露希尔技3「Q.E.D.」**——另一条（`skchr_bdhkgt_2`）只有
    `slow_down_duration`，是族里另一个键，不认。

    上限 `slow_down_max` 与叠层上限 `max_stack_cnt` 是同一件事的两种写法
    （0.06 × 10 = 0.6），守卫里两头对过。
    """
    text = _TAG.sub("", description or "")
    per_stack, duration, _cap = _slowdown_values(bb)
    return "迟钝" in text and per_stack > 0.0 and duration > 0.0


def _wants_pierce_arrow(description: str, bb: dict[str, float]) -> bool:
    """是否「直线飞行的**贯穿**箭矢，每飞行一段距离都会对周围所有敌人造成…」。

    判据两段：正文里有「贯穿」、且黑板里有 `dist_interval`（**每段结算的距离**）。
    缺一段都不认——`dist_interval` 单独出现说明不了什么，而「贯穿」在别的干员
    身上也可能只是形容。

    全表实测（986 条 M3）：这个形状只出现在焰狐龙梓兰技3「龙之箭」上。
    实机规格（prts.wiki 该页 `|备注=` 原文 + 玩家 0.1 倍速慢放实测）见
    `docs/uncertainties.md` §十三之三。
    """
    text = _TAG.sub("", description or "")
    return "贯穿" in text and float(bb.get("dist_interval") or 0.0) > 0.0


def _wants_landing_hit(description: str, bb: dict[str, float]) -> bool:
    """是否「之后降落并对…造成攻击力 X%」——落地那一击算**独立的一次出手**。

    两段判据，缺一不可：描述里写「之后降落」、黑板里有 `attack@atk_scale_end`。
    **不按 `atk_scale_2` 键名认**：那个键是"第二个倍率槽"，在十个干员身上有
    六种互不相同的含义（见 `SkillEffects.final_hit_scale` 的注释）。

    全表实测：这个措辞与 `attack@atk_scale_end` 都只出现在焰狐龙梓兰技2 上。
    """
    text = _TAG.sub("", description or "")
    return "之后降落" in text and bool(bb.get("attack@atk_scale_end"))


def _wants_final_double(description: str) -> bool:
    """是否「最后一击系数加倍」——**只认这一个措辞**。

    为什么不认 `atk_scale_2` 键名：那个键是"第二个倍率槽"，十个干员有
    六种互不相同的含义（另一个目标组、对非移动敌人、音符序号、第二段
    攻击、灼痕那一段……），详见 `SkillEffects.final_hit_scale` 的注释。
    描述里写明了才用，没写就一律按单倍率算。

    全表实测：该措辞只出现在阿米娅(术战者)技2 影霄·绝影上，零波及。
    """
    return "最后一击系数加倍" in _TAG.sub("", description or "")


def _wants_self_stun(description: str, bb: dict[str, float]) -> float:
    """技能结束时**自身**晕眩的秒数，0 = 不是这一类。

    两段判据，缺一不可：
    ① 描述里「结束后」之后 30 字内出现「晕眩」——把"施加给敌人的晕眩"
       （通常写在前半句，如"对范围内敌人造成伤害并晕眩 3 秒"）排除掉；
    ② 黑板里有**裸** `stun` 键。对敌晕眩的值写在 `attack@stun` 上，
       裸键往往是 None（卡达技2 即是）。

    标本：阿米娅技2 精神爆发「技能自动开启，持续时间结束后自身晕眩 10 秒」。
    同类的还有幽灵鲨、稀音、布洛卡、苍苔、森蚺、埃癸斯、极光、蚀清等。
    """
    text = _TAG.sub("", description or "")
    if "晕眩" not in text:
        return 0.0
    for marker in ("技能结束后", "技能结束时", "持续时间结束后", "结束后"):
        if marker in text:
            tail = text.split(marker, 1)[1]
            if "晕眩" in tail[:30]:
                return float(bb.get("stun") or 0.0)
            break
    return 0.0


#: 「技能结束后…强制退出战场」。锚在「技能结束后」上——另有
#: 「N 秒后强制退出战场」是**别的**语义（阶段性的持续技能），不能一起收。
_SELF_RETREAT = re.compile(r"技能结束后[^。\n]{0,16}?强制退出战场")


def _wants_self_retreat(description: str) -> bool:
    """技能结束后是否**强制退出战场**。标本：阿米娅技3 奇美拉。"""
    return bool(_SELF_RETREAT.search(_TAG.sub("", description or "")))


def _wants_true_from_final_hit(description: str) -> bool:
    """是否「**末击起**为真实」而不是整条技能都真实。

    判据要三个条件同时成立：写了「最后一击」、写了「真实伤害」、又写了
    「伤害类型变为真实」。第三个条件把它与「最后一击系数加倍且为真实伤害」
    这类**只描述末击**的写法分开——那种情况整条技能并不改类型。

    全表 6 个命中「伤害类型变为真实」的技能里，只有阿米娅(术战者)技2
    影霄·绝影同时带末击限定；其余 5 条（Mon3tr 技3、凯尔希技3、维娜技3、
    耀骑士临光技3、阿米娅技3）都是整条技能，`true_damage` 对它们是对的。
    """
    t = _TAG.sub("", description or "")
    return "最后一击" in t and "真实伤害" in t and "伤害类型变为真实" in t


def _wants_once_per_battle(description: str) -> bool:
    """「整场战斗中该技能只能释放一次」。标本：阿米娅技2 影霄·绝影。"""
    return "整场战斗中该技能只能释放一次" in _TAG.sub("", description or "")


#: 「获得 N%[的]（物理和法术|物理|法术）闪避」。
#:
#: ⚠️ **「的」必须是可选的**。规则按「有『的』」写会漏掉正文的真实写法：
#: 赤刃明霄陈技2 的原文是「获得 60%<标签>物理和法术闪避」——**没有「的」**，
#: 而全库同族正文里带「的」与不带「的」**各占一半**。这正是「闪避」此前
#: 从未接进战斗层的根因：判据写窄了，编译层一个项都没吐出来，下游自然无事可做。
#:
#: 三处**故意不认**的写法（宁可少认，不要认错）：
#: * `获得 30% 的**近战**物理闪避`（火神）——「近战」是**限定**，只挡近战攻击。
#:   当成普通物理闪避会高估，而 `SkillEffects` 没有表达限定范围的字段。
#: * `有 15% 的概率闪避敌人的近战物理攻击`（因陀罗）——结构完全不同（有概率、
#:   限定近战、且成功后还给下一次攻击加成），不是单纯发一个闪避状态。
#: * `治疗友方单位后为其**提供**持续 3 秒的 10% 物理闪避`（斑点）——作用对象是
#:   **被治疗者**而不是自己，本项目的 `SkillEffects` 只描述"给自己"的那一类。
#: 三种都已记进 `docs/uncertainties.md`，等后续批次处理。
_DODGE = re.compile(
    r"获得(?P<val>\d+(?:\.\d+)?)%"
    r"(?:（[^）]*）)?"          # 潜能展示值，如 `获得19%（+4%）的物理闪避`
    r"(?:的)?"
    r"(?P<kind>物理和法术|物理|法术)闪避")


def _wants_dodge(description: str) -> tuple[float, float]:
    """从描述里取技能给的闪避，返回 `(物理闪避, 法术闪避)`，比例量纲。

    为什么只能按描述判：赤刃明霄陈技2 的闪避值在黑板键
    `chen3_s2[respawn_buff].prob` 上，而**同一个 `prob` 名字**在提丰技2 里
    是 `attack@prob` = 40% 概率晕眩。键名同名反义，只有正文说得清是哪一个。

    描述传入的应是 `render_description` **渲染后**的文本（占位符已换成数字），
    所以这里直接取数字即可，不必再去黑板里找键。
    """
    m = _DODGE.search(_TAG.sub("", description or ""))
    if m is None:
        return 0.0, 0.0
    val = float(m.group("val")) / 100.0
    kind = m.group("kind")
    if kind == "物理和法术":
        return val, val
    if kind == "物理":
        return val, 0.0
    return 0.0, val


#: 紧邻「最大生命 / 生命上限」的**前一个字符必须是这些**——它们都表明这个量是
#: **自己的**：己（自己）/ 身（自身）/ 得（获得）/ 的 / 于（相当于）/ 并 / 和 /
#: 即（立即）/ % / 数字。
#:
#: 别人的量写的是**名字或第三人称**，前一个字符就是那个名字的末字：
#:   相当于「娜斯提」生命上限 80%    → 提 ✗
#:   相当于「凯瑟琳」生命上限  6%    → 琳 ✗
#:   添加相当于「其」生命上限 100%   → 其 ✗
#: 2026-09-18 全表核验：这一条把 14 个命中里「给别人」的摘干净，真自己的一个
#: 都没误伤。**方向是宁可漏、不可错**——漏了顶多少算一个屏障，错了会把队友的
#: 屏障算到自己头上。
_BARRIER_SELF_LEAD = r"[己身得的于并和即%\d]"

#: 屏障：「自己最大生命值 N%」的两种语序，都锚在「最大生命 / 生命上限」上。
#:
#: **只能按渲染后的描述取数，不能按黑板键取**——2026-09-18 全表核验过：
#: `hp_ratio` 这个键在 47 个技能里与屏障毫无关系（它是「流失/回复/治疗目标
#: X% 生命」），而且**即便同时出现「屏障」，它也不一定就是屏障的量**：
#: 摩根 `hp_ratio=1.5` 确是屏障 150%，左乐 `hp_ratio=0.5` 却是**流失量**，
#: 屏障 120% 只写在正文里。键名同名反义，与 `prob` 那条是同一类坑。
#:
#:   「获得70%最大生命值的屏障」                    电弧技1      → 序②
#:   「立刻获得最大生命10%的屏障」                  机械师技2    → 序①
#:   「可吸收相当于自己最大生命180%的屏障」          砾技2        → 序①
#:   「获得相当于生命上限100%的屏障」                斥罪技3      → 序①
_BARRIER_RATIO = re.compile(
    # 序①：百分号在「最大生命」**之后**
    r"(?<=" + _BARRIER_SELF_LEAD + r")"
    r"(?:最大生命(?:值|上限)?|生命上限)\s*(\d+(?:\.\d+)?)\s*%\s*的?\s*屏障"
    # 序②：百分号在「最大生命」**之前**（此时前一字是 %，天然合规）
    r"|(\d+(?:\.\d+)?)\s*%\s*(?:最大生命(?:值|上限)?|生命上限)\s*的?\s*屏障"
)

#: **故意不认**的屏障写法（2026-09-18 全表核验后逐条登记）。它们的共同点是
#: "屏障"这个词都在，但**量与归属都不是"自己最大生命值的比例"**：
#:
#: * 按施法者攻击力：「屏障能吸收相当于闪灵攻击力 300% 的伤害」——量纲是攻击力；
#: * 固定点数：「施加可吸收 800 点伤害的屏障」——没有比例；
#: * 只吸某一系：「可吸收相当于自己最大生命 80% **物理伤害**的屏障」（傀影技1）
#:   ——隔了「物理伤害」，正则不收，这一条是**故意**的：它只挡物理；
#: * 给别人的：「部署后获得相当于**凛御银灰**最大生命值 50% 的屏障」（凛御银灰技1）
#:   ——屏障给的是**新部署的那名干员**，不是银灰自己。这条语序与电弧的完全一样，
#:   正则**分不出来**，只能靠这条名单把它摘掉；
#: * 损伤屏障：「获得 200 点损伤屏障」——另一套机制（元素损伤），不是生命屏障；
#: * 叠加上限：「屏障最高叠加至最大生命值的 100%」——那是**上限**不是授予量。
_BARRIER_NOT_SELF = frozenset({
    "skchr_svash2_1",   # 屏障给待部署区新下的那名干员，不是自己
})

#: 「自身和召唤物……」这类**主语是集合**的写法。命中意味着这条技能的效果
#: 要发一份给主人的召唤物（召唤物自己没有技能槽）。
_SELF_AND_SUMMON = re.compile(r"自身和(?:召唤物|结构性原理)")


def _wants_barrier(description: str) -> float:
    """从描述里取技能给**自己**的屏障量，返回**最大生命值的比例**，没有就是 0。

    描述传入的应是 `render_description` **渲染后**的文本（占位符已换成数字）。
    """
    text = _TAG.sub("", description or "")
    m = _BARRIER_RATIO.search(text)
    if m is None:
        return 0.0
    return float(m.group(1) or m.group(2)) / 100.0


def render_description(text: str, blackboard: dict[str, float]) -> str:
    """把 `攻击力<@ba.vup>+{atk:0%}</>` 渲染成 `攻击力+50%`。

    查不到的键**原样留着**（连花括号一起），这样漏了什么一眼能看见，
    比悄悄替换成 0 或者空字符串诚实。

    换行有两种写法：10881 个等级用真实换行，3168 个等级写的是**字面**的
    反斜杠加 n（游戏数据没解码）。两种都还原成真实换行，否则打印时会
    把 `\\n` 当正文显示出来。
    """
    def repl(m: re.Match) -> str:
        key, _, spec = m.group(1).partition(":")
        key = key.strip()
        if key not in blackboard:
            return m.group(0)
        return format_value(blackboard[key], spec.strip())

    out = _TAG_RE.sub("", _PLACEHOLDER_RE.sub(repl, text or ""))
    return out.replace("\\r\\n", "\n").replace("\\n", "\n")


# ---------------------------------------------------------------- 效果解析

#: 面板增益。值是**比例**（0.5 = +50%）还是**绝对值**，在第二位标明。
BUFF_KEYS: dict[str, tuple[str, str]] = {
    "atk": ("atk", "pct"),
    "atk_base": ("atk", "pct"),
    "attack@atk": ("atk", "pct"),
    "def": ("def", "pct"),
    "max_hp": ("max_hp", "pct"),
    "magic_resistance": ("res", "flat"),
    "attack_speed": ("attack_speed", "flat"),
    "base_attack_time": ("attack_interval", "flat_sec"),
    "cost": ("cost", "flat"),
    "block_cnt": ("block_cnt", "flat"),
    "def_penetrate": ("def_penetrate", "pct"),
    "def_penetrate_fixed": ("def_penetrate_fixed", "flat"),
    "magic_resist_penetrate": ("res_penetrate", "pct"),
    "magic_resist_penetrate_fixed": ("res_penetrate_fixed", "flat"),
    "damage_resistance": ("damage_resistance", "pct"),
    "move_speed": ("move_speed", "pct"),
    "taunt_level": ("taunt_level", "flat"),
    "hp_recovery_per_sec_by_max_hp_ratio": ("hp_regen_pct", "pct"),
}

#: 改变"这一次攻击怎么打"的量
DAMAGE_KEYS: dict[str, str] = {
    "atk_scale": "atk_scale",
    "attack@atk_scale": "atk_scale",
    "atk_scale_2": "atk_scale_2",
    "damage_scale": "damage_scale",
    "times": "times",
    "attack@times": "times",
    "max_target": "max_target",
    "attack@max_target": "max_target",
    "heal_scale": "heal_scale",
    "attack@heal_scale": "heal_scale",
    "attack@trigger_time": "ammo",
    # 焰狐龙梓兰技2「飞翔瞪射」那一段的两条倍率：`loop` 是三连射每支的倍率、
    # `end` 是**落地那一击**的倍率。`loop`/`end` 既不是 `_s2` 那种尾缀、
    # 也不是 `@s3_` 那种中缀，四级降级全都够不着——于是整块黑板五个键
    # 此前一个都没解析，技2 在模型里退化成一发 100% 的普攻。
    "attack@atk_scale_loop": "atk_scale",
    "attack@atk_scale_end": "atk_scale_end",
    # 裸的 `trigger_time` 有 320 处，**绝大多数是"触发间隔"**，只有弹药类
    # 技能里才是弹药数（望「天下劫」：`trigger_time 20` ↔ 描述"装有20发弹药"）。
    # 这里先统一归成 ammo，再由 `_parse_effects` 按 `durationType` 退回去——
    # 判据只有一个，就是 durationType，别在别处再猜一遍。
    "trigger_time": "ammo",
}

#: 起飞/降落的**演出参数**（焰狐龙梓兰技2 的黑板）：抬升高度、起飞那一瞬、
#: 落地那一瞬。收成显式字段而不是留在 `other`，是为了让「这两条到底有没有
#: 人读」有答案（审计的第二道筛子只看源码里有没有字面量读过它）。
#:
#: **它们本身不进战斗结算**：干员侧的「起飞」在模拟器里不做机制处理
#: （与予愿安洁莉娜技3「滑翔起飞」的既有处理一致——那一句也只当演出）。
#: 留档与待裁定见 `docs/uncertainties.md` 第十三节。
_FLIGHT_KEYS: dict[str, str] = {
    "fly_height": "airborne_height",
    "fly_duration": "airborne_rise",
    "fly_end_duration": "airborne_fall",
}

#: 施加的控制效果，值是持续时间（秒）。
#:
#: **警告：黑板分不出这些控制是打在敌人身上还是自己身上。** 阿米娅「精神爆发」
#: 的黑板是 `stun 10`，而描述写的是"技能自动开启，持续时间结束后阿米娅晕眩
#: 10 秒"——那是**自晕**，不是控敌。极少数技能会用 `attack@stun` 这类前缀
#: 暗示"由攻击施加"，但不能作为普遍判据。用之前必须看描述。
CONTROL_KEYS: tuple[str, ...] = (
    "stun", "sluggish", "sleep", "levitate", "bind", "cold", "frozen",
    "silence", "fear", "unmovable",
)

#: 后缀噪声：`attack@atk_scale_s2` 里的 `_s2` 是"技能二自己的那条"，
#: 语义与 `attack@atk_scale` 一致，去掉后缀再查表。
_SUFFIX_RE = re.compile(r"_(?:s\d+|\d+)$")

#: **中缀**的技能槽标记：`attack@s3_atk_scale` → `attack@atk_scale`。
#:
#: 同一件事有两种写法：`attack@atk_scale_s2`（槽号在**尾巴**，上面那条正则管）
#: 与 `attack@s3_atk_scale`（槽号**夹在 @ 后面**，原先四级降级全都够不着）。
#: 提丰技3「永恒狩猎」整块黑板就是后一种写法，于是 `atk_scale` / `stun` /
#: `trigger_time`（弹药数）**四个键一起落进 `other`**，技能一开就因为弹药为 0
#: 而立刻结束。判据取自描述本身——「共造成 5 次相当于攻击力 {attack@s3_atk_scale}
#: 的物理伤害并使目标晕眩 {attack@s3_stun} 秒 / 装有 {attack@s3_trigger_time} 发
#: 弹药」，三个键的语义与不带槽号的同名键一致。
#:
#: 影响面很小且已核验：全库 `前缀@sN_属性` 形态只有 6 个技能、11 个键。
_INFIX_RE = re.compile(r"@s\d+_")

#: 带变体限定的键：`headb2_s_2[second].atk` → 变体 `second`、属性 `atk`。
#:
#: 这是**同一个属性的另一个场合取值**，不是新属性。方括号里可以出现
#: `second`（第二次及以后）、`crit`（暴击）、`damage`（伤害那一段）、
#: `period`（周期）、`debuff`、`once`、`a`/`b`/`c`/`d`（并列的几段）等。
#: 全表 208 种这样的键、涉及 97 个技能。
#:
#: 注意必须**要求方括号后面跟着 `.属性名`**：`weak[limit]`、`ep_damage_ratio[trigger]`
#: 这类是把方括号当限定词整体用的，不适用本条规则，别一起吞了。
_VARIANT_RE = re.compile(r"^(?P<head>.*?)\[(?P<variant>[^\]]+)\]\.(?P<attr>[^.]+)$")


def _split_variant(key: str) -> tuple[str | None, str]:
    """拆出变体限定。返回 `(变体, 去掉变体后的键)`，没有变体则返回 `(None, key)`。"""
    m = _VARIANT_RE.match(key)
    if not m:
        return None, key
    return m.group("variant"), m.group("attr")


def _classify(key: str) -> tuple[str, str, str] | None:
    """把一个黑板键归到 (类别, 规范名, 量纲)，归不了返回 None。

    匹配是降级序列：原样 → 去掉 `xxx@` 前缀 → 去掉 `_s2`/`_2` 尾巴 →
    **去掉夹在 @ 后面的技能槽标记**（`attack@s3_atk_scale` → `attack@atk_scale`）。
    """
    def lookup(k: str):
        if k in BUFF_KEYS:
            return ("buff",) + BUFF_KEYS[k]
        if k in DAMAGE_KEYS:
            return ("damage", DAMAGE_KEYS[k], "scale")
        if k in CONTROL_KEYS:
            return ("control", k, "sec")
        return None

    stripped = _SUFFIX_RE.sub("", key)
    infixed = _INFIX_RE.sub("@", key)
    for cand in (key, key.rsplit("@", 1)[-1],
                 stripped, stripped.rsplit("@", 1)[-1],
                 infixed, infixed.rsplit("@", 1)[-1],
                 _SUFFIX_RE.sub("", infixed)):
        hit = lookup(cand)
        if hit:
            return hit
    return None


@dataclass
class SkillEffects:
    """一次技能的黑板被解释之后的样子。

    四个箱子分开装，是因为它们的用法完全不同：`buffs` 改的是**面板**，
    `damage` 改的是**这一击怎么结算**，`control` 打在**敌人**身上，
    `other` 是还没解释的部分。混在一起会写出"把眩晕时长当攻击力"这种错。
    """

    buffs: dict[str, float] = field(default_factory=dict)
    #: 每个增益的量纲：pct / flat / flat_sec
    units: dict[str, str] = field(default_factory=dict)
    damage: dict[str, float] = field(default_factory=dict)
    control: dict[str, float] = field(default_factory=dict)
    other: dict[str, float] = field(default_factory=dict)
    #: 这一击是不是**真实伤害**。黑板里没有这个信息——`atk_scale` 只说倍率，
    #: 不说伤害类型——只能从技能描述里判（见 `_wants_true_damage`）。
    #: 标本：凯尔希·思衡托「保护性拒止」写的是"造成相当于攻击力380%的真实
    #: 伤害"，而它的黑板只有 `atk_scale 3.8`，按法术算会把 99 法抗的吓人路灯
    #: 从 4,512 削成 45，差两个数量级。
    true_damage: bool = False
    #: 连击数——描述里写"造成 N 次攻击力 X%"而黑板没有 `times` 时用，
    #: 由 `_repeat_hits` 从描述里取。0 = 不是这一类。
    repeat_hits: int = 0
    #: 「攻击变为 N 连击」——技能期间**每次普通攻击**打 N 下，由
    #: `_wants_multi_hit` 从描述里取。0 = 不是这一类。
    #: 与 `repeat_hits` 的区别在出处：那个是"技能自己一次打 N 下"
    #: （赤刃技3 的 3 连击），这个是"把普通攻击改造成 N 连击"
    #: （阿米娅影霄·奔夜、赤刃技1）。对模拟器而言都是"一次出手打 N 下"，
    #: 但刻意分开存——两者的判据与标本完全不同，合并会让追溯变难。
    multi_hit: int = 0
    #: 「最后一击系数加倍」——最后一击改用的倍率，没有就是 None。
    #:
    #: **只能按描述判，不能按 `atk_scale_2` 这个键名判。** 那个键在数据里
    #: 是"第二个倍率槽"，含义随技能而变：空弦用它表示**另一个目标组**
    #: （周围敌人）、雪猎表示**对非移动敌人**的加成、丰川祥子表示 8 个
    #: 音符里的第 2 个、焰狐龙梓兰表示第二段攻击（刚连射）、菲亚梅塔
    #: 表示灼痕那一段。照键名统一当成末击倍率会**同时搞错十个干员**。
    #: 标本：阿米娅(术战者)技2 影霄·绝影，描述明写「最后一击系数加倍且为
    #: 真实伤害」，其 `atk_scale_2` 恰为 `atk_scale` 的两倍（1.6 → 3.2）。
    final_hit_scale: float | None = None
    #: 「之后降落并对…造成攻击力 X%」——**技能演完之后的另一段伤害**的倍率，
    #: 没有就是 None。与 `final_hit_scale` 分开：那是"同一个连击序列的末击"，
    #: 这是"另一段出手"，只是恰好也排在最后，模拟器里按末击结算。
    #:
    #: 标本：焰狐龙梓兰技2 飞翔瞪射——三连射每支 180%（3+4+5 支），
    #: 落地再补一击 300%（`attack@atk_scale_end`）。
    landing_scale: float | None = None
    #: 每轮射出的箭数（`(3, 4, 5)` = 三轮共 12 支）。见 `_volley_arrows`。
    #: 总数进 `hit_count`；轮次结构留给守卫与文档，模拟器按"一次技能 N 段
    #: 独立命中"结算（与能天使 5 连发同一口径）。
    volley_arrows: tuple[int, ...] = ()
    #: 「若还有充能则额外消耗 N 层施展…：发射 M 支攻击力 P 倍的箭矢」那一组。
    #: 三个数一起用：`charge_layers` 是**额外**层数（她 1 = 一共吃 2 层）、
    #: `charge_arrows` 是那一段的箭数（5）、`charge_scale` 是它的倍率（2.0）。
    #: **不进 `hit_count`**：打不打要看开技时的充能，模拟器在出手时接力
    #: （`op.charge_extra_ready`，见 `sim._activate`）。判据见 `_charge_volley`。
    #: 标本：焰狐龙梓兰技1「刚射」。
    charge_layers: int = 0
    charge_arrows: int = 0
    charge_scale: float = 0.0
    #: 贯穿弹道（焰狐龙梓兰技3「龙之箭」）的六个参数。判据见 `_wants_pierce_arrow`；
    #: **物理那一半走 `atk_scale`**（3.6），法术那一半在 `pierce_magic_scale`。
    #:
    #: * `pierce_magic_scale`——「攻击力 60% 的法术伤害」（`atk_scale_magic`）。
    #:   备注写明**先物理、后法术**，所以是两笔独立伤害、各自吃防御/法抗。
    #: * `pierce_step`——每飞行**这么多格**结算一次（`dist_interval` 0.25）。
    #:   玩家 0.1 倍速慢放实测：「閃盾一下判定 4 下死亡」——0.5 碰撞半径内
    #:   恰好跨 4 个 0.25 步，与这个数自洽。
    #: * `pierce_max_dist`——最大飞行距离（`max_dist` 99，即"无限远"的占位）。
    #: * `pierce_force`——推力**力度等级**（`force` 2.0 = 较大力度）。
    #: * `pierce_push_cd`——推动对**每个敌人各自**的冷却（`knockback_duration` 1.0）。
    #: * `pierce_charge`——抬手后的蓄力计时（`wait_duration` 1.5）。
    pierce_magic_scale: float = 0.0
    pierce_step: float = 0.0
    pierce_max_dist: float = 0.0
    pierce_force: float = 0.0
    pierce_push_cd: float = 0.0
    pierce_charge: float = 0.0
    #: **可叠加的迟钝**（移动速度降低）——可露希尔技3「Q.E.D.」那一条。
    #: 判据见 `_wants_stackable_slow`，prts.wiki 把「迟钝」点名为 `ba.slowdown`。
    #:
    #: * `slow_per_stack`——**每层**降多少移速（`slow_down` 0.06）；
    #: * `slow_time`——**每层各自**持续多少秒（`slow_down_time` 3.0）；
    #: * `slow_max`——叠满封顶（`slow_down_max` 0.6）。
    #:
    #: ⚠️ 它与「停顿」（`control["sluggish"]`）是**两个量**：停顿是关键词、
    #: 走 `sluggish_timer`；迟钝是**可叠加的百分比移速降低**、走独立的层表。
    #: 既有裁定明写两者不可合并（见 `docs/uncertainties.md` 的速度那几条）。
    slow_per_stack: float = 0.0
    slow_time: float = 0.0
    slow_max: float = 0.0
    #: **按出手次数递增**的攻击目标数——可露希尔技3「Q.E.D.」的
    #: 「每攻击 9 次后攻击目标数+1（最多触发 6 次）」。判据见
    #: `_wants_target_growth`。
    #:
    #: * `target_step`——每多少次**出手**涨一格（`attack_trigger_cnt` 9）；
    #: * `target_cap`——最多涨几格（`max_trigger_cnt` 6）。
    #:
    #: 与 `max_target`（开技即生效的**静态**改写）分开：那个是"这一击打几个"，
    #: 这个是"打了几次之后能多打一个"，静态字段表达不了。
    target_step: int = 0
    target_cap: int = 0
    #: **一次性偷取友方攻速**——新约能天使技2「开火成瘾症」的「立即偷取攻击
    #: 范围内 1 名友方干员 70 点攻击速度（持续至技能结束或新约能天使离场）」。
    #: 判据见 `_wants_steal_aspd`（**裸键** `steal`，与伊内丝那族带 `attack@`
    #: 前缀的"每次攻击偷敌人"严格分开）。
    #:
    #: * `steal_aspd`——一次拿走多少点（她这里 70）；
    #: * `steal_aspd_max`——累计上限（她这里 999，一次拿 70 够不到，等于没有）。
    steal_aspd: float = 0.0
    steal_aspd_max: float = 0.0
    #: 偷取**成功**时额外获得的弹药数（`addtional_ammo_each`，5）。
    #: 「如果成功偷取攻击速度则额外获得 5 发弹药」——**只有真的偷到了**才加，
    #: 范围内没有友方就不加（这是它的判据，守卫里两头都钉了）。
    steal_bonus_ammo: int = 0
    #: 「使（范围内的地面）敌人**物理/法术命中率 −X%**」——阿斯卡纶技3「残影」
    #: 与艾拉技1 的同一机制（前者带前缀、后者裸键，见 `_hitrate_values`）。
    #: 两个值都是**负数**（−0.5 / −0.4 @M3），0.0 表示这一路没有。
    #:
    #: 落点在**敌人**身上：它出手打我方时按类型乘 `(1 + 该值)`。这是概率事件的
    #: **期望值折法**（与闪避同一套口径）——掷骰会让同一份作业每次跑出不同结果，
    #: 搜索与回归都不可复现。
    enemy_hitrate_phys: float = 0.0
    enemy_hitrate_arts: float = 0.0
    #: 「开技后先闭锁 N 秒（不能行动、不受伤）、醒来再打」的两段式技能
    #: ——泥岩技3「秽壤的血脉」：`sleep` 10 秒是**闭锁**段，`awake` 20 秒是
    #: 醒来后的窗（10 + 20 = 技能总时长 30，两处都对得上）。
    #:
    #: prts 该技能 `|备注=` 写明：「技能生效的**前10秒**，实际将会进入
    #: **闭锁**状态（**非**无法行动），且持有眩晕/冻结/沉默**反制**」——
    #: 所以那 10 秒是"不能行动 + 不受伤 + 不被控"，不是晕眩。
    #:
    #: ⚠️ `awake_secs` 在本模型里**没有独立可观测量**：闭锁期间她既不能出手
    #: （攻击/攻速增益测不出），也不掉血（防御增益测不出），所以"增益放在哪
    #: 一段"在现模型里等价。它被用作**两段式的判据**与时长自洽（见守卫），
    #: 这一限制如实记在 `docs/uncertainties.md`。
    lock_secs: float = 0.0
    awake_secs: float = 0.0
    #: 「周围敌人移动速度 −X%」的 X（负数）。泥岩技3 写 `move_speed: -0.6`。
    #:
    #: ⚠️ `BUFF_KEYS` 里**早就**有 `"move_speed": ("move_speed", "pct")` 这一行，
    #: 但 `SkillEffects` 上一直**没有同名字段**，于是解析结果被静默丢掉——
    #: 落一个字段在这里，那一行才真的兑现（否则它在表里挂着，看着像"已支持"）。
    move_speed: float = 0.0
    #: 「给费用」的四个量（可露希尔那一族；见 `_cost_semantics` 与
    #: `_cost_trickle`）。`cost` 这个键**一键多义**，全表 59 条技能四种写法，
    #: 所以这里按**正文**分门别类，谁也不许顶替谁：
    #:
    #: * `cost_grant`：开技**一次**给的那一份（正文「立即/立刻获得」）；
    #: * `cost_gradual`：整个技能期**摊开**给的那一份（正文「逐渐获得」，
    #:   技1 那一族总额写在 `cost` 上）；
    #: * `cost_trickle_total` / `_per` / `_interval`：摊开的**节奏**
    #:   （技2/技3 的总额写在 `cost_period` 上，节奏来自方括号变体）；
    #: * `cost_per_attack`：每次命中给（`cost_attack_add`，技3 为 0）。
    cost_grant: float = 0.0
    #: 开技时**不许**一次性给 `cost`（正文只有「逐渐获得」的那些，如技1）。
    #: 这一条是给模拟器的一个"别重复给"的闸门——`cost` 那条既有通道是
    #: 无条件在开技时给的，两种写法混在一起就会**给双份**。
    cost_suppress_immediate: bool = False
    cost_gradual: float = 0.0
    cost_trickle_total: float = 0.0
    cost_trickle_per: float = 0.0
    cost_trickle_interval: float = 0.0
    cost_per_attack: float = 0.0
    #: 主「部署后每使用过一次技能，获得的部署费用 +X（最多提升至 Y 点）」
    #: （可露希尔技1 的 `cost_per_add` / `cost_add_max`）。
    cost_per_add: float = 0.0
    cost_add_max: float = 0.0
    #: 技2「开火成瘾症」那一族：**会持续衰减**的屏障，比例对**各自的生命上限**算。
    #:
    #: ⚠️ 不能复用 `barrier_pct`：那一个由 `_deactivate` 在**技能结束时清零**，
    #: 而这一种正文写的是「该屏障会持续衰减」——衰减自有节奏，与技能何时结束
    #: 无关。prts 该技能备注：「获得的屏障均以自身生命上限为标准计算；屏障
    #: **每秒衰减量为：初始屏障量/30**；**重复获得此屏障时，重置屏障量与衰减
    #: 速度**」——`shield_max_duration` 那 30 秒正好就是这个分母。
    #:
    #: ⚠️ 判据用**正文**（「该屏障会持续衰减」）而不是键名：`shield_max_hp_ratio`
    #: 在 cairn 技2 上是 **0.9，含义是"最多不超过生命上限的 90%"这个上限**，
    #: 属性同名反义——按键名认会把上限当成授予量。
    barrier_decay_pct: float = 0.0
    barrier_decay_secs: float = 0.0
    #: 结城理那三条技能：**切换〈替身〉形态**（傀儡师特性）。
    #: 取值 `orpheus` / `thanatos` / `thanatos_kai` / `orpheus_kai`；空 = 不是这种技能。
    #:
    #: ⚠️ 他的技能**在同一帧就结束**（prts 备注：「因切换〈替身〉会终止技能，
    #: 故技能开启后会立刻在同一帧内结束，可以触发『技能结束』事件」），
    #: 所以形态参数必须在**切换那一刻快照**到单位上——下一帧 `effects` 已经没了，
    #: 从 effects 现读会读到空（那是一处**静默**失效）。
    stand_form: str = ""
    #: 形态专属参数，随 `stand_form` 一起快照。
    #: * `stand_heal_scale`——俄耳甫斯的治疗倍率（`attack@heal_scale` 0.6）；
    #: * `stand_kill_scale` / `stand_kill_damage`——塔纳托斯的**斩杀光环**
    #:   （`attack@kill_atk_scale` 2.8 是"生命值低于攻击力 280%"这个阈值，
    #:   `attack@kill_damage` 9999999 是斩杀伤害本身）；
    #: * `stand_heal_targets`——俄耳甫斯·改每次治疗的目标数
    #:   （`attack@max_target_heal` 4）。
    stand_heal_scale: float = 0.0
    stand_kill_scale: float = 0.0
    stand_kill_damage: float = 0.0
    stand_heal_targets: int = 0
    #: 「阻挡范围扩大」——提升「**阻挡半径倍率**」属性（凯尔希·思衡托技1）。
    #:
    #: 语义有 prts 备注作准：「阻挡范围加成为提升受益者的『阻挡半径倍率』属性，
    #: **可以对凯尔希自身生效，但与天赋间同名效果取最高**」。所以它与天赋
    #: 「遗尘守望」上的同名键之间**取最高、不相加**（两边都是 0.23，相加会算成
    #: 0.46）。它的作用对象是「持有【对地规避】的友方」——也就是"起飞"的那一族，
    #: 见 `docs/uncertainties.md`。
    block_radius_scale: float = 0.0
    #: 「返还部署费用」的比例（可露希尔技2「模型扩展」= 0.4）。
    #:
    #: prts 备注把**基数**钉死了：「下一帧立刻回复干员**当前部署费用属性**的 40%
    #: （向上取整）」，并特意补一句「由新约能天使投递干员时（或类似情况下），即使
    #: 玩家没有实际消耗费用，干员仍可能拥有非 0 的部署费用属性。本技能仍然可以
    #: 就这一情况进行回费」——所以基数取该干员自己的 `deploy_cost`，**不是**这次
    #: 实际扣掉多少费。触发条件是「在**战术点效果范围**内部署干员」（见
    #: `sim._refund_on_deploy`）。
    cost_return: float = 0.0
    #: 「投递坐标处的炮击」（新约能天使技3「使命必达！」）。
    #:
    #: 正文「若存在投递坐标，立即对该处造成一次相当于攻击力 250% 的物理溅射
    #: 伤害并将一名再部署时间最长的地面干员部署至该处，使其获得 6 点技力」
    #: → 黑板 `attack@cannon_atk_scale = 2.5`、`attack@sp = 6`、
    #: `max_deploy_character = 99`（这一技能的**投递名额**）。
    #:
    #: ⚠️ 溅射**半径无数据**（正文只说"溅射"，黑板里没有半径类键），
    #: 暂用仓库既有的 3×3 重叠判定口径（半径 1.0），已记 `docs/uncertainties.md`。
    cannon_atk_scale: float = 0.0
    #: 被投递到坐标处的干员获得的技力（`attack@sp`）。
    cannon_sp: float = 0.0
    #: 这次技能**最多投递几个干员**（`max_deploy_character`，她这里是 99）。
    cannon_deploy_cap: int = 0
    #: 「每 N 秒获得 1 层护盾（最多 M 层），每层护盾破裂时恢复自身 X% 最大生命」
    #: ——泥岩天赋「沃土予身」。
    #:
    #: **这组量里没有"护盾值"，而且本来就不该有**：博士 2026-09-19 裁定
    #: 「泥岩的护盾**只要受到伤害就会破裂**」。这与数据自洽——全库天赋黑板里
    #: 没有任何 shield 类键（逐条扫过，见 `docs/uncertainties.md` §二十九）。
    #: 所以护盾是一层**记号**，不是一段可以吸收的血条：
    #: `interval` 秒加一层、上限 `max_times` 层、部署时给 `times` 层，
    #: 任何一次受伤消耗一层并按 `hp_ratio` 回血。**不吸收伤害**（无值可吸）。
    shield_interval: float = 0.0
    shield_layers_on_deploy: int = 0
    shield_max_layers: int = 0
    shield_break_heal_ratio: float = 0.0
    #: 破裂后给的技力（空弦「铁弦」的 `sp`=7）。
    shield_break_sp: float = 0.0
    #: 起飞/降落的**演出参数**：抬升高度、起飞用时、落地用时（黑板的
    #: `fly_height` / `fly_duration` / `fly_end_duration`）。**不进战斗结算**
    #: ——干员侧的「起飞」目前不做机制，与予愿安洁莉娜技3 的既有处理一致，
    #: 留档见 `docs/uncertainties.md` 第十三节。
    airborne_height: float | None = None
    airborne_rise: float | None = None
    airborne_fall: float | None = None
    #: 技能结束时**自身**晕眩的秒数，0 = 无。
    #:
    #: 与 `control["stun"]` **不是一回事**：那个归在"控制敌人"里，而
    #: **黑板根本分不出控制打在谁身上**（见 `CONTROL_KEYS` 上方的警告）。
    #: 实测规律（2026-09-16，全表 100 条「技能结束后…晕眩」去重描述）：
    #: **裸 `stun` 键 = 己方自身晕眩，`attack@stun` = 对敌晕眩**——
    #: 幽灵鲨技2 `stun 10`「技能结束后干员晕眩10秒」、稀音技2 `stun 5`
    #: 「技能结束后所有摄影车晕眩5秒」、阿米娅技2 `stun 10`「技能结束后
    #: 自身晕眩10秒」；反例卡达技2 对敌晕眩时裸 `stun` 是 **None**，
    #: 值在 `attack@stun` 里。
    self_stun: float = 0.0
    #: 技能结束后干员**强制退出战场**（阿米娅技3 奇美拉）。
    #: 结算时令 `op.alive = False`——技能是"最后一搏"，用完全场即离场。
    self_retreat: bool = False
    #: 「**末击起**直到技能结束，伤害类型变为真实」——与 `true_damage` 区分：
    #: 那个是整条技能的**每一次**都真实，这个只有末击与之后的普攻是真实。
    #: 标本：阿米娅(术战者)技2 影霄·绝影。原文「进行 10 次攻击力 220% 的
    #: **法术**斩击（最后一击系数加倍且为真实伤害）；……并且接下来的伤害类型
    #: 变为真实」。博士 2026-09-17 裁定：「第十次斩击是真实伤害，之后直到
    #: 技能结束都是真实伤害的普攻，技能结束后恢复正常算法」——所以
    #: **前 9 次仍是法术**，不能按整条技能算真实。
    #: 全表命中「伤害类型变为真实」的 6 个技能里，只有这一条带末击限定。
    true_from_final_hit: bool = False
    #: 「整场战斗中该技能只能释放一次」（阿米娅技2 影霄·绝影）。
    once_per_battle: bool = False
    #: 技能期间获得的闪避，**比例**量纲（0.6 = 60%），物理与法术分开。
    #:
    #: 为什么按描述判而不是按黑板：赤刃明霄陈技2 的值在
    #: `chen3_s2[respawn_buff].prob` 上，而**同一个 `prob` 名字**在提丰技2
    #: 里是 `attack@prob` = 40% 概率晕眩。键名同名反义，只有正文说得清。
    #: 见 `_wants_dodge`（那里同时列了三种**故意不认**的限定写法）。
    dodge_phys: float = 0.0
    #: 技能给的**自身**屏障，量纲是**最大生命值的比例**（1.0 = 100%）。
    #: 判据见 `_wants_barrier`：只能按描述取，黑板键 `hp_ratio` 同名反义。
    barrier_pct: float = 0.0
    #: 这条技能的效果**也发给召唤物**。判据是描述里的主语写的是
    #: 「自身和召唤物」（电弧技1/2/3）或「自身和结构性原理」（机械师技2）。
    #: 召唤物自己没有技能槽，所以要由主人开技能时**发下去**。
    affects_summons: bool = False
    dodge_arts: float = 0.0
    #: 击杀叠层的**层数上限**（0 = 没有这类效果）。数值来自
    #: `<前缀>[kill].max_stack_cnt`；每层的加成在 `variants["kill"]` 里
    #: （`atk` 是比例、`res` 是绝对值）。标本：阿米娅技2 影霄·绝影——
    #: 「斩击期间每击败一个敌人获得攻击力+40%和法术抗性+20（最多叠加 3 次）」，
    #: 博士 2026-09-17 裁定「整个技能持续期叠层、技能结束时清零」，
    #: 与游戏内注释「斩击杀敌获得的增益效果持续至技能结束」一致。
    kill_max_stack: int = 0
    #: 变体取值：`{"second": {"atk": 1.8, "def": 1.2}}`。见 `with_variant`。
    variants: dict[str, dict[str, float]] = field(default_factory=dict)
    #: 变体里每项的量纲与归属类别
    variant_units: dict[str, dict[str, str]] = field(default_factory=dict)
    #: 归类统计：(成功次数, 总次数)
    classified: int = 0
    total: int = 0

    # -------------------------------------------------------- 便捷读数

    @property
    def atk_pct(self) -> float:
        """技能带来的攻击力提升（比例，0.5 = +50%）。"""
        return self.buffs.get("atk", 0.0)

    @property
    def atk_scale(self) -> float:
        """技能把**干员自己这一击**的攻击力乘上的倍率，没有就是 1。

        黑板里可能同时存在 `attack@atk_scale` 与裸 `atk_scale`，两者指的
        往往不是一回事。机械师「工程学十字星」就是标本：

        * `attack@atk_scale 2.6` —— 描述里"攻击变为对十字范围内所有敌人
          造成攻击力{attack@atk_scale}的法术伤害"，**这才是平A**；
        * `atk_scale 3.0` —— 描述里"结构性原理向前方冲锋……造成机械师
          攻击力300%的物理伤害"，那是一次独立冲锋，不是每次攻击。

        所以 `attack@` 前缀的那条优先；两者都有时，裸的那条另存到
        `atk_scale_other`，不丢。按这条规则机械师是 (1+2.8)×2.6 = 9.88 倍，
        与社区标定的 9.9 倍吻合，反过来若取 3.0 会算成 11.4 倍。
        """
        return self.damage.get("atk_scale") or 1.0

    @property
    def atk_scale_other(self) -> float | None:
        """不属于平A的那条攻击力倍率（如冲锋、棋子、爆炸），没有就是 None。"""
        return self.damage.get("atk_scale_other")

    @property
    def hit_count(self) -> int:
        """一次攻击打几下（连击）。

        只认 `times` / `attack@times`——`cnt` 有 696 处使用，多数是
        "召唤 N 个""棋子 N 枚"，当成连击数会算出几倍的伤害。
        黑板没有 `times` 时依次退到描述里的 `multi_hit`（「攻击变为
        N 连击」，阿米娅影霄·奔夜）、`repeat_hits`（「造成 N 次攻击力」，
        赤刃明霄陈技3 的 3 连击）与 `volley_arrows`（「分别射出 3、4、5 支」，
        焰狐龙梓兰技2 的 12 支）。

        箭数那一路**还要再加上落地点射那一下**（焰狐龙梓兰技2 是 12 + 1 = 13）：
        落地是技能演完之后的另一段出手，模拟器按末击结算（`landing_scale`）。
        """
        total = int(self.damage.get("times") or self.multi_hit
                    or self.repeat_hits or 0)
        if not total and self.volley_arrows:
            total = sum(self.volley_arrows)
            if self.landing_scale:
                total += 1
        return max(1, total)

    @property
    def max_target(self) -> int:
        """一次攻击能打几个目标，没有就是 1。"""
        return max(1, int(self.damage.get("max_target") or 1))

    @property
    def ammo(self) -> int | None:
        """弹药类技能的总发数，非弹药技能为 None。"""
        n = self.damage.get("ammo")
        return int(n) if n else None

    @property
    def heal_scale(self) -> float | None:
        """这一击附带的治疗倍率（治疗量 = 攻击力 × 该倍率），没有就是 None。

        医疗干员的**普通攻击**也是治疗，但那条不在黑板里，靠特性判定，
        见 `OperatorUnit.heals`；这里只报技能自己写的 `heal_scale`。
        标本：凯尔希·思衡托技2 `heal_scale 2.0` 与 `atk_scale 3.8` 并存
        ——同一击既打伤害又治疗，两者不是二选一。
        """
        v = self.damage.get("heal_scale")
        return float(v) if v else None

    @property
    def coverage(self) -> float:
        return 1.0 if not self.total else self.classified / self.total

    # -------------------------------------------------------- 变体

    def variant_names(self) -> list[str]:
        return sorted(self.variants)

    def with_variant(self, variant: str, *, mode: str = "replace") -> "SkillEffects":
        """返回一份把某个变体取值叠上去的**副本**（原对象不动）。

        怒潮凛冬「绝不罢休」是标准用例：黑板给 `atk 0.9` / `def 0.6`，
        另外用 `headb2_s_2[second].atk 1.8` / `[second].def 1.2` 给出
        "第二次及以后使用"的数值。所以

            esc = lv.effects.with_variant("second")

        拿到的是 `atk 1.8 / def 1.2` 那份，可以直接替换进战斗。

        **默认是替换而不是相加**，因为变体表达的是"同一属性在另一个场合
        的取值"，不是额外的一份加成。本用例可以验算：描述写"加成变为最初
        的两倍"，而 1.8 恰好是 0.9 的两倍、1.2 恰好是 0.6 的两倍——相加会
        得到 2.7，与描述不符。

        但并非所有变体都是替换语义——`peacok_s_1[crit].atk_scale` 那种
        暴击倍率是叠加上去的。机械判不出来，所以留了 `mode="add"`，由调用方
        按具体技能决定。**这条是推断，不是实测**，用之前请对照技能描述。
        """
        import copy as _copy

        if mode not in ("replace", "add"):
            raise SkillError(f"mode 只能是 replace / add，收到 {mode!r}")
        if variant not in self.variants:
            raise SkillError(
                f"没有名为 {variant!r} 的变体；"
                f"这个技能有 {self.variant_names() or '（无）'}")
        out = _copy.deepcopy(self)
        for name, value in self.variants[variant].items():
            kind = self.variant_units.get(variant, {}).get(name, "buff/")
            cls, _, unit = kind.partition("/")
            if cls == "buff":
                if mode == "replace":
                    out.buffs[name] = value
                else:
                    out.buffs[name] = out.buffs.get(name, 0.0) + value
                out.units[name] = unit
            elif cls == "damage":
                out.damage[name] = value
            else:
                out.control[name] = (value if mode == "replace"
                                     else max(out.control.get(name, 0.0), value))
        return out

    # -------------------------------------------------------- 战斗接口

    def attack_power(self, base_atk: float) -> float:
        """开技能期间，**面板口径**的等效攻击力 = `面板 × (1 + 攻击力增益)`。

        **这里不含技能倍率**（`atk_scale`）——2026-09-18 博士裁定。倍率只在
        `damage.resolve_damage(scale=…)` 那一处乘，一次出手的总伤害是
        `attack_power(面板) × atk_scale`。

        裁定前这里把 `atk_scale` 也乘了进来（口径是"一次攻击的等效攻击力"），
        而平A 循环同时又按 `resolve_damage(scale=eff.atk_scale)` 乘了一次，
        于是**同一条倍率乘了两次**：零防目标上实得/正文 = 倍率本身
        （能天使技1 实测 1.4500）。两侧各自都自洽（本函数有机械师
        「工程学十字星」`(1+2.8) × 2.6 = 9.88` 的社区标定值撑腰，`resolve_damage`
        的契约也是"`atk` 给最终攻击力、`scale` 给技能倍率"），合起来才错——
        所以改的是**含义**那一侧，不是把某一处删掉了事：
        `attack_power` 从"一次攻击"退回"面板"，9.88 那条断言改写成
        `attack_power(1.0) × atk_scale`（见 `check_battle [3]`）。
        """
        return base_atk * (1.0 + self.atk_pct)

    def attack_interval(self, base_interval: float,
                        base_attack_speed: float = 100.0) -> float:
        """开技能期间的实际攻击间隔。

        两条修正是叠加的，顺序为**先加算秒数，再按攻速折算**：

        * `base_attack_time` 直接加在间隔上（加算秒数，见模块开头的说明）；
        * `base_attack_speed` 是**总攻速**（基础 100 + 天赋 + 模组特性，
          由 `operator/attack_speed.py` 取数），技能自己的攻速加成再叠上去，
          实际间隔 = 间隔 × 100 / 总攻速。

        折算**无条件执行**，不再以"技能带不带攻速 buff"为条件：常驻攻速
        来自天赋与模组，技能不给攻速时它们照样要生效。`base_attack_speed`
        仍是 100 且无 buff 时，折算恒等，与旧行为一致。

        攻速有**下限**，`ASPD_MIN = 20`（2026-09-16 博士裁定；wiki 写 20、
        xulai1001/akdata 写 10，取 20）。不夹的话，减速叠满会把间隔拉到无穷大、
        或者反过来加速叠满打出游戏里打不出的频率。
        """
        interval = base_interval + self.buffs.get("attack_interval", 0.0)
        spd = max(ASPD_MIN, base_attack_speed + self.buffs.get("attack_speed", 0.0))
        return max(0.05, interval * 100.0 / spd)

    def describe(self) -> list[str]:
        """给人看的几行——只列解释得了的部分。"""
        rows: list[str] = []
        for k, v in sorted(self.buffs.items()):
            unit = self.units.get(k, "")
            if unit == "pct":
                rows.append(f"{k} {v * 100:+.0f}%")
            elif unit == "flat_sec":
                rows.append(f"{k} {v:+.2f}s")
            else:
                rows.append(f"{k} {v:+g}")
        for k, v in sorted(self.damage.items()):
            if k == "atk_scale_other":
                rows.append(f"（非平A的倍率）{v:g}")
            elif "scale" in k:
                rows.append(f"{k} ×{v:g}")
            else:
                rows.append(f"{k} {v:g}")
        for k, v in sorted(self.control.items()):
            rows.append(f"{k} {v:g}s")
        for name in self.variant_names():
            body = "  ".join(f"{k}={v:g}" for k, v in sorted(self.variants[name].items()))
            rows.append(f"[{name}] {body}")
        return rows


# ---------------------------------------------------------------- 技能等级

@dataclass
class SkillLevel:
    """技能的一个等级。"""

    index: int
    name: str
    description: str            #: 渲染过变量之后
    raw_description: str        #: 原样，带 `{atk:0%}` 与 `<@ba.vup>` 标签
    skill_type: str             #: AUTO / MANUAL / PASSIVE
    duration_type: str          #: NONE / AMMO
    sp_type: str                #: 归一化之后的技力回复方式
    sp_cost: float
    init_sp: float
    increment: float
    max_charge: int
    duration: float | None      #: None = 无限持续
    range_id: str | None        #: 技能改写后的攻击范围代号
    blackboard: dict[str, float]
    effects: SkillEffects
    #: 描述路径的惰性缓存（见 `formula_effects` / `resolved_effects`）
    _formula_effects: object | None = None
    _resolved_cache: dict = field(default_factory=dict)

    # -------------------------------------------------------- 描述驱动的效果

    def formula_effects(self):
        """把描述编译成 `FormulaEffects`（`ak_tactic.formula`）。

        与 `_wants_true_damage` / `_repeat_hits` 那两条钩子是同一件事的
        一般化：那两个只认"真实伤害"和"造成 N 次"两种写法，这一个走完整的
        130 条规则，还多出元素损伤/爆发/损伤回复这条**黑板完全没有的轴**。
        """
        from .. import formula as _formula

        if self._formula_effects is None:
            terms = _formula.parse(self.raw_description, self.blackboard)
            self._formula_effects = _formula.effects_from_terms(terms)
        return self._formula_effects

    def resolved_effects(self, policy: str = "merge"):
        """按策略给出**用于战斗结算**的效果。返回 `(effects, 分歧列表)`。

        * `blackboard` —— 原样（黑板 + 上面两条钩子），旧行为；
        * `merge`（默认）—— 再用描述补黑板的缺（倍率/连击/治疗/元素）；
        * `desc` —— 只信描述，用于敏感性与对照。
        """
        if policy == "blackboard":
            return self.effects, []
        from .. import formula as _formula

        hit = self._resolved_cache.get(policy)
        if hit is None:
            hit = _formula.merge_effects(self.effects, self.formula_effects(),
                                         policy=policy)
            self._resolved_cache[policy] = hit
        return hit

    # -------------------------------------------------------- 读数

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.index] if self.index < len(LEVEL_LABELS) \
            else f"#{self.index}"

    @property
    def skill_type_cn(self) -> str:
        return SKILL_TYPE_CN.get(self.skill_type, self.skill_type)

    @property
    def sp_type_cn(self) -> str:
        return SP_TYPE_CN.get(self.sp_type, self.sp_type)

    @property
    def is_passive(self) -> bool:
        """被动技能：常驻生效，不耗技力。"""
        return self.skill_type == "PASSIVE" or self.sp_type == SP_NONE

    @property
    def auto_trigger(self) -> bool:
        """技力满了会不会自己开。"""
        return self.skill_type == "AUTO"

    @property
    def infinite(self) -> bool:
        """持续时间无限——**不能**用 `duration is None` 判。

        `duration is None` 在游戏数据里是歧义的，两种截然不同的技能都长这样
        （都是 `durationType = NONE`、黑板里没有 `duration`）：

        * 「**无限持续**」——圣聆初雪技2「霜涛覆岭」，描述里明写"持续时间无限"；
        * 「**瞬发**」——她的技1「铃音吹雪」，描述开头就是"**立即**对范围内
          所有敌人造成……可充能2次"，根本没有持续时间。

        把后者当成前者，会让一个 12 秒攒一次、一次打 520% 的爆发技能，
        变成**永续 520% 倍率平A**：991×5.2/2.0 ≈ 2577 每秒，而真实是
        991×5.2/12 ≈ 430 每秒——**高估六倍**。只能靠描述文本区分。
        """
        return (self.duration_type == "INFINITE"
                or "持续时间无限" in (self.description or ""))

    @property
    def is_instant(self) -> bool:
        """瞬发：开启当拍打一次，随即结束（没有持续时间，也不是无限）。"""
        if self.duration_type == "AMMO":
            return False
        return not self.infinite and self.duration is None

    @property
    def effective_duration(self) -> float | None:
        """技能实际能持续多久。

        弹药类技能没有时间上限——它靠"打够 N 发"结束，所以返回 None
        并让上层用 `effects.ammo` 计数。瞬发返回 0：开启后立刻结束，
        但**当拍的攻击仍然要打出去**（出手环节在同帧的技能环节之后）。
        """
        if self.duration_type == "AMMO":
            return None
        if self.is_instant:
            return 0.0
        return self.duration

    def sp_per_second(self) -> float:
        """自动回复类技能每秒回多少技力（其余类型返回 0）。"""
        return self.increment if self.sp_type == SP_AUTO else 0.0

    def sp_per_attack(self) -> float:
        return self.increment if self.sp_type == SP_ATTACK else 0.0

    def sp_per_hit(self) -> float:
        return self.increment if self.sp_type == SP_HIT else 0.0

    def time_to_ready(self) -> float | None:
        """从 0 技力到能开，需要多少秒。非自动回复类给不出。"""
        rate = self.sp_per_second()
        if rate <= 0 or self.is_passive:
            return None
        return max(0.0, (self.sp_cost - self.init_sp) / rate)

    def to_dict(self) -> dict:
        return {
            "index": self.index,
            "label": self.label,
            "name": self.name,
            "description": self.description,
            "skill_type": self.skill_type,
            "duration_type": self.duration_type,
            "sp_type": self.sp_type,
            "sp_cost": self.sp_cost,
            "init_sp": self.init_sp,
            "increment": self.increment,
            "max_charge": self.max_charge,
            "duration": self.duration,
            "range_id": self.range_id,
            "blackboard": self.blackboard,
            "effects": {
                "buffs": self.effects.buffs,
                "damage": self.effects.damage,
                "control": self.effects.control,
                "other": self.effects.other,
                "variants": self.effects.variants,
                "coverage": round(self.effects.coverage, 3),
            },
        }


@dataclass
class OperatorSkill:
    """一个技能槽：属于谁、什么时候解锁、各等级什么样。"""

    skill_id: str
    char_id: str
    slot: int                   #: 1/2/3
    unlock_phase: int           #: 需要精英几（0/1/2）
    unlock_level: int           #: 需要阶段内等级
    levels: list[SkillLevel] = field(default_factory=list)

    @property
    def name(self) -> str:
        return self.levels[0].name if self.levels else self.skill_id

    @property
    def max_index(self) -> int:
        return len(self.levels) - 1

    def level(self, level: int = 7, mastery: int = 0) -> SkillLevel:
        idx = resolve_index(level, mastery)
        if idx >= len(self.levels):
            raise SkillError(
                f"{self.skill_id} 只有 {len(self.levels)} 个等级，"
                f"取不到索引 {idx}")
        return self.levels[idx]

    def unlocked_at(self, elite: int) -> bool:
        return elite >= self.unlock_phase

    def to_dict(self, *, level: int = 7, mastery: int = 0) -> dict:
        lv = self.level(level, mastery) if self.levels else None
        return {
            "skill_id": self.skill_id,
            "slot": self.slot,
            "unlock_phase": self.unlock_phase,
            "unlock_level": self.unlock_level,
            "name": self.name,
            "levels": len(self.levels),
            "current": lv.to_dict() if lv else None,
        }


# ---------------------------------------------------------------- 技能书

class SkillBook:
    """技能数据的读取入口。

        book = SkillBook()
        for sk in book.for_operator("char_002_amiya"):
            lv = sk.level(level=7, mastery=3)
            print(sk.slot, sk.name, lv.description)
    """

    def __init__(self, source: GameDataSource | None = None):
        self.source = source or GameDataSource(base=GITHUB_BASE)
        self._table: dict[str, dict] | None = None
        self._chars: dict[str, dict] | None = None

    # -------------------------------------------------------- 装载

    def _load(self) -> dict[str, dict]:
        if self._table is not None:
            return self._table
        try:
            raw = self.source.fetch_json("excel/skill_table.json")
        except GamedataError as e:
            raise SkillError(
                f"取不到 excel/skill_table.json。\n"
                f"  这张表只有 GitHub 镜像有，map.ark-nights.com 不带。\n  {e}") from e
        if not isinstance(raw, dict):
            raise SkillError("skill_table.json 的结构不是字典")
        # 顶层就是 skillId → 技能，没有包一层
        self._table = raw
        return self._table

    def _load_chars(self) -> dict[str, dict]:
        if self._chars is not None:
            return self._chars
        try:
            raw = self.source.fetch_json("excel/character_table.json")
        except GamedataError as e:
            raise SkillError(f"取不到 excel/character_table.json：{e}") from e
        chars = {k: v for k, v in raw.items() if k.startswith("char_")}
        self.source.release("excel/character_table.json")

        # 升变形态（阿米娅的近卫/医疗）**不在 character_table 里**，而在
        # `char_patch_table.json` 的 `patchChars`，结构与干员本体完全相同。
        # 不并进来则 `for_operator('char_1001_amiya2')` 直接报「没有这个干员」
        # ——而森空岛名册引用的正是这些 charId，于是**术战者阿米娅的技能
        # 一条也查不出来**。`OperatorCalculator` 与 `db/build.py` 早就并了，
        # 这里是最后漏掉的一处（2026-09-16 补）。
        # 取不到这张表不该让技能书哑火——少两个形态而已。
        try:
            patch = self.source.fetch_json("excel/char_patch_table.json")
        except GamedataError:
            patch = {}
        else:
            for cid, c in (patch.get("patchChars") or {}).items():
                chars.setdefault(cid, c)
            self.source.release("excel/char_patch_table.json")

        self._chars = chars
        return self._chars

    # -------------------------------------------------------- 查询

    def all_ids(self) -> list[str]:
        return sorted(self._load())

    def exists(self, skill_id: str) -> bool:
        return skill_id in self._load()

    def slots(self, char_id: str) -> list[dict]:
        """干员的技能槽原始条目（`character_table.skills`）。"""
        chars = self._load_chars()
        if char_id not in chars:
            raise SkillError(f"没有这个干员：{char_id}")
        return chars[char_id].get("skills") or []

    def for_operator(self, char_id: str, *,
                     max_phase: int | None = None) -> list[OperatorSkill]:
        """这名干员的技能，按技能槽顺序。

        :param max_phase: 只返回这个精英阶段已解锁的技能；None = 全给
        """
        out: list[OperatorSkill] = []
        for i, entry in enumerate(self.slots(char_id), start=1):
            sid = entry.get("skillId") or ""
            if not sid:
                continue
            cond = entry.get("unlockCond") or {}
            phase = _phase_to_int(cond.get("phase"))
            if max_phase is not None and phase > max_phase:
                continue
            out.append(OperatorSkill(
                skill_id=sid,
                char_id=char_id,
                slot=i,
                unlock_phase=phase,
                unlock_level=int(cond.get("level") or 1),
                levels=self.levels(sid),
            ))
        return out

    def skill(self, skill_id: str) -> dict:
        table = self._load()
        if skill_id not in table:
            raise SkillError(f"没有这个技能：{skill_id}")
        return table[skill_id]

    def levels(self, skill_id: str) -> list[SkillLevel]:
        """把一条技能的全部等级解析出来。"""
        entry = self.skill(skill_id)
        out: list[SkillLevel] = []
        for i, raw in enumerate(entry.get("levels") or []):
            out.append(self._parse_level(i, raw, skill_id))
        return out

    # -------------------------------------------------------- 解析

    def _parse_level(self, index: int, raw: dict,
                     skill_id: str = "") -> SkillLevel:
        bb = {b.get("key"): float(b.get("value") or 0.0)
              for b in (raw.get("blackboard") or []) if b.get("key")}
        # 真值可能在 valueStr 里（range_id 就是典型：value 恒为 0）
        for b in (raw.get("blackboard") or []):
            if b.get("valueStr"):
                bb[f"${b.get('key')}"] = b["valueStr"]

        st = raw.get("skillType") or ""
        sp = raw.get("spData") or {}
        sp_type = _normalize_sp_type(sp.get("spType"), st)

        raw_dur = raw.get("duration")
        duration: float | None
        if raw_dur is None or float(raw_dur) < 0:
            duration = None          # -1 = 无限持续
        else:
            duration = float(raw_dur)

        lv = SkillLevel(
            index=index,
            name=raw.get("name") or "",
            description=render_description(raw.get("description") or "", bb),
            raw_description=raw.get("description") or "",
            skill_type=st,
            duration_type=raw.get("durationType") or "NONE",
            sp_type=sp_type,
            sp_cost=float(sp.get("spCost") or 0.0),
            init_sp=float(sp.get("initSp") or 0.0),
            increment=float(sp.get("increment") or 0.0),
            max_charge=int(sp.get("maxChargeTime") or 1),
            duration=duration,
            range_id=_range_override(raw, bb),
            blackboard=bb,
            effects=_parse_effects(bb, raw.get("durationType") or "NONE"),
        )
        # 真实伤害只能从描述里判（黑板没有伤害类型字段）
        lv.effects.true_damage = _wants_true_damage(lv.description)
        # 连击数同理：黑板没有 `times` 时，描述正文里的"造成 3 次攻击力…"
        # 是唯一出处（赤刃明霄陈技3）。
        lv.effects.repeat_hits = _repeat_hits(lv.description)
        # 「攻击变为 N 连击」同理：黑板没有 `times` 时，描述是唯一出处
        # （阿米娅影霄·奔夜、赤刃明霄陈技1 都只写在正文里）。
        lv.effects.multi_hit = _wants_multi_hit(lv.description)
        # 「最后一击系数加倍」：末击改用 `damage` 里的 `atk_scale_2`。
        # 判据是**描述**（见 `_wants_final_double`），不是键名——键名在
        # 别的干员身上另有含义，不能通用。
        if _wants_final_double(lv.description):
            lv.effects.final_hit_scale = lv.effects.damage.get("atk_scale_2")
        # 每轮箭数（「分别射出 3、4、5 支」/「发射 4 支」）与**落地点射**。
        # 落地的倍率**借末击那条路**（`final_hit_scale`）：它确实排在最后，
        # 但出处与语义是另一回事，所以 `landing_scale` 另存一份。
        lv.effects.volley_arrows = _volley_arrows(lv.description)
        # 「刚连射」那一组（技1）：额外层数 / 箭数 / 倍率。是否真的打，看开技
        # 时的充能，所以这里只落参数。
        charge = _charge_volley(lv.description, bb)
        if charge is not None:
            lv.effects.charge_layers, lv.effects.charge_arrows, \
                lv.effects.charge_scale = charge
        # 贯穿弹道（技3「龙之箭」）：六个参数一次收齐。物理那一半已经在
        # `atk_scale` 上（3.6），这里补法术与几何/推力。
        if _wants_pierce_arrow(lv.description, bb):
            e3 = lv.effects
            # 法术那一半**从黑板直接取**：`atk_scale_magic` 归不了类（它落在
            # `other` 里），所以 `damage` 桶里没有它。两种前缀都收，理由同
            # `_charge_volley`：她技3 的这条是裸键。
            e3.pierce_magic_scale = float(
                bb.get("atk_scale_magic") or bb.get("attack@atk_scale_magic") or 0.0)
            e3.pierce_step = float(bb.get("dist_interval") or 0.0)
            e3.pierce_max_dist = float(bb.get("max_dist") or 0.0)
            e3.pierce_force = float(bb.get("force") or 0.0)
            e3.pierce_push_cd = float(bb.get("knockback_duration") or 0.0)
            e3.pierce_charge = float(bb.get("wait_duration") or 0.0)
        if _wants_landing_hit(lv.description, bb):
            lv.effects.landing_scale = lv.effects.damage.get("atk_scale_end")
            lv.effects.final_hit_scale = lv.effects.landing_scale
        # 可叠加的迟钝（技3「Q.E.D.」）：三个数一次收齐。**每命中一次加一层**，
        # 上限从两个地方各写了一遍——`slow_down_max` 0.6 与 `slow_down ×
        # max_stack_cnt` 0.06 × 10 是同一个封顶，守卫里两头对过。
        if _wants_stackable_slow(lv.description, bb):
            (lv.effects.slow_per_stack, lv.effects.slow_time,
             lv.effects.slow_max) = _slowdown_values(bb)
        # 按出手次数递增的攻击目标数（技3「Q.E.D.」）：两个整数。
        if _wants_target_growth(lv.description, bb):
            lv.effects.target_step = int(bb.get("attack_trigger_cnt") or 0)
            lv.effects.target_cap = int(bb.get("max_trigger_cnt") or 0)
        # 一次性偷取友方攻速（技2「开火成瘾症」）。
        if _wants_steal_aspd(lv.description, bb):
            lv.effects.steal_aspd = float(bb.get("steal") or 0.0)
            lv.effects.steal_aspd_max = float(bb.get("steal_max") or 0.0)
            # 「如果成功偷取攻击速度则额外获得 5 发弹药」——弹药数写死在正文里，
            # 但键是 `addtional_ammo_each`（5，全表只有她）。正文那句是**条件**
            # （成功才给），不是无条件，所以判据要留给模拟器，不能在这里加。
            lv.effects.steal_bonus_ammo = int(bb.get("addtional_ammo_each") or 0)
            # `recover_each_cnt` 是同一件事的**另一个官方键**：她技2 的黑板里
            # `addtional_ammo_each` 与 `recover_each_cnt` 都是 5.0，而正文只写了
            # 一处「额外获得 5 发弹药」。两个键都读，后者只在前者缺席时兜底——
            # 这样任一个键单独出现都不会让这条通道静默失效。
            if lv.effects.steal_bonus_ammo <= 0:
                lv.effects.steal_bonus_ammo = int(
                    bb.get("recover_each_cnt") or 0)
        # 「使敌人命中率 −X%」（技3「残影」）：两个负数，按类型分。
        if _wants_enemy_hitrate(lv.description, bb):
            (lv.effects.enemy_hitrate_phys,
             lv.effects.enemy_hitrate_arts) = _hitrate_values(bb)
        # 两段式（泥岩技3）：先闭锁 `sleep` 秒，`awake` 秒是醒来后的窗。
        if _wants_lock_awake(lv.description, bb):
            lv.effects.lock_secs = float(bb.get("sleep") or 0.0)
            lv.effects.awake_secs = float(bb.get("awake") or 0.0)
            # `move_speed` 从黑板上**显式**取：`BUFF_KEYS` 里那一行虽然写着
            # `("move_speed", "pct")`，但落到效果上时并不兑现（实测她的技3
            # 解析出来是 0.0，而黑板是 −0.6）。这一条是本节"减速"那半的来源。
            lv.effects.move_speed = float(bb.get("move_speed") or 0.0)
        # 「给费用」四个量（可露希尔那一族）。`cost` 一键多义，所以按正文分：
        # 这一处只**分类**，不替既有口径做决定（那 59 条不动）。
        _cs = _cost_semantics(lv.description, bb)
        lv.effects.cost_grant = _cs["immediate"]
        lv.effects.cost_suppress_immediate = _cs["suppress_immediate"]
        lv.effects.cost_gradual = _cs["gradual_total"]
        lv.effects.cost_per_attack = _cs["per_attack"]
        (_total, _per, _iv) = _cost_trickle(bb, lv.effects.variants)
        if _cs["gradual_total"] > 0.0 and _total <= 0.0:
            # 技1 那一族：正文绑的是 `{cost}`、没有 `cost_period`，
            # 总额就是 `gradual_total`（`cost_per_add` 的成长在运行时加）
            _total = _cs["gradual_total"]
        lv.effects.cost_trickle_total = _total
        lv.effects.cost_trickle_per = _per
        lv.effects.cost_trickle_interval = _iv
        lv.effects.cost_per_add = float(bb.get("cost_per_add") or 0.0)
        lv.effects.cost_add_max = float(bb.get("cost_add_max") or 0.0)
        # 技2 那一族：**会持续衰减**的屏障。判据靠正文那一句，见字段上的注释
        # （`shield_max_hp_ratio` 在 cairn 技2 上同名反义，是"上限"而非"授予量"）。
        if ("该屏障会持续衰减" in lv.description
                and float(bb.get("shield_max_hp_ratio") or 0.0) > 0.0):
            lv.effects.barrier_decay_pct = float(bb["shield_max_hp_ratio"])
            lv.effects.barrier_decay_secs = float(
                bb.get("shield_max_duration") or 0.0)
        # 结城理那三条技能：**切换〈替身〉形态**。
        #
        # ⚠️ 判据是渲染后的正文——`SkillLevel.description` 已经把术语标记
        # **剥掉**了：原文「立即切换为〈替身〉状态作战」在这里是
        # 「立即切换为**状态作战**」（那对尖括号和里面的"替身"一起没了）。
        # 照原文写 `"切换为<替身>状态作战" in desc` 会**一条都不中**，
        # 而且是静默的。这是"描述是渲染后的"这一类坑的第四次现身，
        # 形态名（俄耳甫斯/塔纳托斯）倒是留着的，所以按它们分形态。
        if "切换为状态作战" in lv.description:
            lv.effects.stand_form = _stand_form_of(lv.description, bb)
            lv.effects.stand_heal_scale = float(
                bb.get("attack@heal_scale") or 0.0)
            lv.effects.stand_kill_scale = float(
                bb.get("attack@kill_atk_scale") or 0.0)
            lv.effects.stand_kill_damage = float(
                bb.get("attack@kill_damage") or 0.0)
            lv.effects.stand_heal_targets = int(
                bb.get("attack@max_target_heal") or 0)
        # 「阻挡范围扩大」（凯尔希·思衡托技1）：正文那一句 + 黑板
        # `attack@block_radius_scale`。它改的是「阻挡半径倍率」属性，与天赋上的
        # 同名键**取最高**（prts 备注原话），消费点在 `sim._update_blocking`。
        if "阻挡范围扩大" in lv.description:
            lv.effects.block_radius_scale = float(
                bb.get("attack@block_radius_scale") or 0.0)
        # 「返还部署费用」（可露希尔技2「模型扩展」）：正文那一句 + 黑板
        # `cost_return`。消费点在 `sim._refund_on_deploy`（部署当帧结算）。
        if "返还部署费用" in lv.description:
            lv.effects.cost_return = float(bb.get("cost_return") or 0.0)
        # 只按渲染后正文才能判的规则（投递坐标 / 护盾破裂）。与天赋那条路
        # **共用同一个函数**——两处各写一份就是"技能里生效、天赋里静默失效"。
        apply_text_rules(lv.effects, lv.description, bb)
        # 技能结束时的**自身**效果：晕眩与强制退场。两者的数值/语义都
        # 只在描述里，且都与"打在敌人身上"的那套（`control`）无关。
        lv.effects.self_stun = _wants_self_stun(lv.description, bb)
        lv.effects.self_retreat = _wants_self_retreat(lv.description)
        # 「末击起为真实」要**从 `true_damage` 里摘出来**：两者都靠
        # 「伤害类型变为真实」这句话命中，但覆盖范围不同。前 9 次斩击是法术。
        if _wants_true_from_final_hit(lv.description):
            lv.effects.true_from_final_hit = True
            lv.effects.true_damage = False
        lv.effects.once_per_battle = _wants_once_per_battle(lv.description)
        # 闪避：值写在黑板（键名可能是 `prob`，与"概率晕眩"同名），
        # **认哪个键只能靠描述**，所以这里判的是描述、拿的是渲染后的数字。
        lv.effects.dodge_phys, lv.effects.dodge_arts = _wants_dodge(lv.description)
        # 屏障：值只在**渲染后的描述**里（黑板 `hp_ratio` 同名反义，见
        # `_wants_barrier`）。凛御银灰技1 语序与电弧的一模一样但屏障是给别人的，
        # 用 `_BARRIER_NOT_SELF` 摘掉。
        if skill_id not in _BARRIER_NOT_SELF:
            lv.effects.barrier_pct = _wants_barrier(lv.description)
        lv.effects.affects_summons = bool(
            _SELF_AND_SUMMON.search(_TAG.sub("", lv.description or "")))
        return lv

    # -------------------------------------------------------- 概览

    def coverage(self) -> dict:
        """整张表的黑板键归类覆盖率——用来衡量"解释了多少"。

        判据必须和 `_parse_effects` 完全一致（含变体拆分），否则这里报的
        数字会和实际解析结果对不上。
        """
        total = classified = 0
        unknown: dict[str, int] = {}
        for entry in self._load().values():
            for raw in entry.get("levels") or []:
                for b in (raw.get("blackboard") or []):
                    key = b.get("key")
                    if not key:
                        continue
                    total += 1
                    _, bare = _split_variant(key)
                    if _classify(bare):
                        classified += 1
                    else:
                        unknown[key] = unknown.get(key, 0) + 1
        return {
            "total": total,
            "classified": classified,
            "coverage": classified / total if total else 0.0,
            "distinct_unknown": len(unknown),
            "top_unknown": sorted(unknown.items(), key=lambda kv: -kv[1])[:25],
        }


# ---------------------------------------------------------------- 内部工具

def _phase_to_int(phase: Any) -> int:
    """`"PHASE_2"` → 2。"""
    if isinstance(phase, int):
        return phase
    m = re.search(r"(\d+)", str(phase or ""))
    return int(m.group(1)) if m else 0


def _normalize_sp_type(sp_type: Any, skill_type: str) -> str:
    """技力回复方式归一化。

    `spType` 取 8 时不是"第四种回复"，而是**被动技能用的哨兵值**。

    实测（2026-09-17 全表核过；条数会随技能更新而漂，别抄这里的整数）：
    `sp_type='8'` 共 523 个技能，其中 PASSIVE 451（`skchr_` 56 + `sktok_` 395），
    **非 PASSIVE 72 个、全部是 `sktok_`**（AUTO 62 + MANUAL 10）；且 spCost
    **并非**恒为 0（PASSIVE 最大 999、AUTO 最大 100，如 `sktok_cjbtow_1`
    「灶火灭」cost=10、`sktok_dublst`「爆破」cost=25）。

    所以这个分支的真实作用域是**召唤物技能**：干员侧 `sp_type=8` 的技能
    （`skchr_aglna2_1`「极速送达」等 30 个）**全部是 PASSIVE**，
    靠 `skill_type == "PASSIVE"` 那半边就已正确归一，`sp_type == 8` 半边对干员是空的。

    ⚠️ **批次二做召唤物时会撞上这里**：`sktok_` 里那 72 个是**真的要攒技力并
    自动/手动触发**的，一并归一成 PASSIVE 会让"该攒技力的召唤物"永远常亮。
    届时应改为「只有 `skill_type == PASSIVE` 才归一，`sp_type == 8` 单独判」，
    并用召唤物用例回归 SR-EX-8 的装置链路。
    """
    if skill_type == "PASSIVE" or sp_type == 8:
        return SP_NONE
    s = str(sp_type or "")
    if s in (SP_AUTO, SP_ATTACK, SP_HIT):
        return s
    return SP_NONE


def _range_override(raw: dict, bb: dict[str, float]) -> str | None:
    """技能改写后的攻击范围代号。

    两个来源都要查：`levels[].rangeId` 覆盖 2788 处，
    黑板里的 `range_id`（真值在 `valueStr`）覆盖另外 44 处。
    """
    if raw.get("rangeId"):
        return str(raw["rangeId"])
    v = bb.get("$range_id")
    return str(v) if v else None


def parse_effects(bb: dict[str, float], duration_type: str = "NONE",
                  description: str = "") -> SkillEffects:
    """把一份黑板归类进四个箱子（+ 变体）。**技能与天赋共用这一个入口。**

    天赋黑板与技能黑板同构，所以归类逻辑不必重写；但要注意两条方向性的
    限制，天赋比技能更容易踩：

    * `move_speed: -0.12` 在圣聆初雪的天赋里是「**敌人**减速 12%」，
      而同一把钥匙在别处可能是「自己加速」。归类只能认出这是移速修正，
      **方向读不出来**。
    * `control` 里的寒冷/冻结同理，可能是施加给敌人，也可能是自己承受。

    所以天赋的 `effects` 只作参考，真正驱动模拟的是显式建模的那几个
    （见 `ak_tactic.battle.talents`），别拿 `effects` 直接当结论。

    `description` 是**渲染后正文**。有一批规则只能靠正文判（黑板里没有那个
    意思），例如新约能天使技3 的「投递坐标」、泥岩「沃土予身」的「护盾破裂」。
    技能那条路自己会传；**天赋那条路必须显式传**——不传的话黑板明明有
    `interval/times/max_times/hp_ratio` 也认不出来（踩过：解析全 0，静默）。
    """
    eff = _parse_effects(bb, duration_type)
    if description:
        apply_text_rules(eff, description, bb)
    return eff


def apply_text_rules(eff: SkillEffects, description: str,
                     bb: dict[str, float]) -> None:
    """只按**渲染后正文**才能判的那些规则（技能与天赋共用一份）。

    分开成函数是因为它有两个入口：技能按等级建 `SkillLevel` 时调用一次，
    天赋走 `parse_effects(bb, description=…)` 时再调用一次。两处逻辑必须同一份，
    否则就是"技能里生效、天赋里静默失效"那类最难查的错。
    """
    # 「投递坐标」（新约能天使技3「使命必达！」）：判据锚正文里那三个字。
    if "投递坐标" in description:
        eff.cannon_atk_scale = float(bb.get("attack@cannon_atk_scale") or 0.0)
        eff.cannon_sp = float(bb.get("attack@sp") or 0.0)
        eff.cannon_deploy_cap = int(bb.get("max_deploy_character") or 0)
    # 「护盾破裂」：泥岩天赋「沃土予身」与空弦天赋「铁弦」。
    # 判据锚正文里**同时**出现「护盾」与「破裂」——两者都只在天赋里出现，
    # 技能正文里一条都没有（扫过全库）。
    #
    # 语义按 PRTS「伤判效果」页：**护盾属"抵挡"，是次数制**（页内原话把
    # "护盾次数"列为伤判条件之一）——所以没有"护盾值"这个量，一层护盾就是
    # **整层挡下一次伤害**。那一页还专门写了干员泥岩：「护盾不是重新获得，
    # 而是在已有的护盾之上**补充层数**（即使剩余 0 层也如此）……不会改变
    # Buff 的获取顺序——它几乎永远是最先被获得的」。
    if "护盾" in description and "破裂" in description:
        eff.shield_interval = float(bb.get("interval") or 0.0)
        eff.shield_max_layers = int(bb.get("max_times") or 0)
        # 部署时给几层：泥岩在黑板 `times` 里；空弦的黑板只有 `sp`，
        # 层数写在正文（"获得**一层**护盾"）——按正文取，不猜。
        layers = int(bb.get("times") or 0)
        if not layers and "一层护盾" in description:
            layers = 1
        eff.shield_layers_on_deploy = layers
        eff.shield_break_heal_ratio = float(bb.get("hp_ratio") or 0.0)
        eff.shield_break_sp = float(bb.get("sp") or 0.0)


def _parse_effects(bb: dict[str, float], duration_type: str) -> SkillEffects:
    """把黑板分装进五个箱子（四个类别 + 变体）。

    两处需要两趟处理：

    * **攻击力倍率**：先收集所有 `*atk_scale*`，再决定哪条代表干员自己的
      平A（`attack@` 优先，见 `SkillEffects.atk_scale` 的说明）。一趟到底
      会变成"后写的赢"，而黑板的枚举顺序是不保证的。
    * **变体键**：`[second].atk` 不能覆盖基础的 `atk`，得单独收进
      `variants`，否则"第二次起加成翻倍"会把第一次的数值也改掉。

    变体键的属性名照常归类（所以 `[second].atk` 认得出来是攻击力增益），
    只是落点换到 `variants[variant]` 里。
    """
    eff = SkillEffects()
    scales: dict[str, float] = {}
    ammos: list[tuple[str, float]] = []
    for key, value in bb.items():
        if key.startswith("$"):          # valueStr 标记，不是数值
            continue
        eff.total += 1
        variant, bare = _split_variant(key)
        # 击杀叠层的层数上限：属性名 `max_stack_cnt` 不在任何分类表里，
        # `_classify` 归不了，否则会带着**全名**（`amiya2_s_2[kill].max_stack_cnt`）
        # 落进 `other`，用起来得靠字符串匹配。这里收成规范字段。
        if variant == "kill" and bare == "max_stack_cnt":
            eff.kill_max_stack = int(value)
            continue
        # 起飞/降落的演出参数（焰狐龙梓兰技2）：收成规范字段，**不进结算**。
        # 归在 `_classify` 之前，是因为它们本来就不属于 buff/damage/control
        # 任何一类，靠分类表永远进不来。
        flight = bare.rsplit("@", 1)[-1]
        if flight in _FLIGHT_KEYS:
            setattr(eff, _FLIGHT_KEYS[flight], float(value))
            eff.classified += 1
            continue
        hit = _classify(bare)
        if hit is None:
            eff.other[key] = value
            continue
        kind, name, unit = hit
        eff.classified += 1

        if variant is not None:
            eff.variants.setdefault(variant, {})[name] = value
            eff.variant_units.setdefault(variant, {})[name] = f"{kind}/{unit}"
            continue

        if kind == "buff":
            eff.buffs[name] = eff.buffs.get(name, 0.0) + value
            eff.units[name] = unit
        elif kind == "damage":
            if name == "ammo":
                if duration_type != "AMMO":
                    # 子弹药数只在弹药类技能里认，别把"触发间隔"当弹药
                    eff.classified -= 1
                    eff.other[key] = value
                    continue
                ammos.append((key, value))
                continue
            if name == "atk_scale":
                scales[key] = value
            else:
                eff.damage[name] = value
        else:
            eff.control[name] = max(eff.control.get(name, 0.0), value)

    own = [v for k, v in scales.items() if k.startswith("attack@")]
    bare_scales = [v for k, v in scales.items() if not k.startswith("attack@")]
    if own:
        eff.damage["atk_scale"] = own[0]
    elif bare_scales:
        eff.damage["atk_scale"] = bare_scales[0]
    if own and bare_scales:
        eff.damage["atk_scale_other"] = bare_scales[0]
    # 弹药数同样两趟：`attack@trigger_time`（圣约送葬人 8 发）优先于裸
    # `trigger_time`（望「天下劫」20 发），两个都写时才不会"后写的赢"。
    own_ammo = [v for k, v in ammos if k.startswith("attack@")]
    if own_ammo:
        eff.damage["ammo"] = own_ammo[0]
    elif ammos:
        eff.damage["ammo"] = ammos[0][1]
    return eff
