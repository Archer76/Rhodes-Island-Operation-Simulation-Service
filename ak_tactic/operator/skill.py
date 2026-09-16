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


def _wants_true_damage(description: str) -> bool:
    """这一击是不是真实伤害——**只能从描述判**。

    黑板里没有伤害类型字段：`atk_scale 3.8` 只说倍率，不说它是物理、法术
    还是真实。游戏把这件事写进了技能描述的自然语言里，所以这里扫描述。

    保守起见只在出现"真实伤害"时才判真，其余一律交回默认（干员面板的
    `attack_type`），宁可按法术少算也不按真实多算。
    """
    return "真实伤害" in (description or "")


#: 「造成 N 次攻击力 X% 的伤害」——连击数写死在描述里的那一类。
#: 必须先剥掉 `<@ba.vup>3</>` 这层富文本标签，否则 `3` 夹在标签之间扫不到。
_TAG = re.compile(r"<[^>]+>")
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
    # 裸的 `trigger_time` 有 320 处，**绝大多数是"触发间隔"**，只有弹药类
    # 技能里才是弹药数（望「天下劫」：`trigger_time 20` ↔ 描述"装有20发弹药"）。
    # 这里先统一归成 ammo，再由 `_parse_effects` 按 `durationType` 退回去——
    # 判据只有一个，就是 durationType，别在别处再猜一遍。
    "trigger_time": "ammo",
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

    匹配是三级降级：原样 → 去掉 `xxx@` 前缀 → 再去掉 `_s2`/`_2` 尾巴。
    """
    def lookup(k: str):
        if k in BUFF_KEYS:
            return ("buff",) + BUFF_KEYS[k]
        if k in DAMAGE_KEYS:
            return ("damage", DAMAGE_KEYS[k], "scale")
        if k in CONTROL_KEYS:
            return ("control", k, "sec")
        return None

    for cand in (key, key.rsplit("@", 1)[-1], _SUFFIX_RE.sub("", key),
                 _SUFFIX_RE.sub("", key.rsplit("@", 1)[-1])):
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
        黑板没有 `times` 时退到描述里的 `repeat_hits`（见 `_repeat_hits`，
        赤刃明霄陈技3 的 3 连击就写死在正文里）。
        """
        return max(1, int(self.damage.get("times") or self.repeat_hits or 1))

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
        """开技能期间，**一次攻击**的等效攻击力。

        总倍率 = (1 + 攻击力增益) × 技能倍率——两条是相乘的，这有实测依据：
        机械师「工程学十字星」同时给 `atk 2.8` 与 `attack@atk_scale 2.6`，
        (1+2.8) × 2.6 = 9.88，与社区标定的 9.9 倍吻合。
        """
        return base_atk * (1.0 + self.atk_pct) * self.atk_scale

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
        self._chars = {k: v for k, v in raw.items() if k.startswith("char_")}
        self.source.release("excel/character_table.json")
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
            out.append(self._parse_level(i, raw))
        return out

    # -------------------------------------------------------- 解析

    def _parse_level(self, index: int, raw: dict) -> SkillLevel:
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

    `spType` 取 8 时不是"第四种回复"，而是**被动技能用的哨兵值**——
    630 个技能全是 PASSIVE 且 spCost 恒为 0，所以归一成 PASSIVE。
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


def parse_effects(bb: dict[str, float], duration_type: str = "NONE") -> SkillEffects:
    """把一份黑板归类进四个箱子（+ 变体）。**技能与天赋共用这一个入口。**

    天赋黑板与技能黑板同构，所以归类逻辑不必重写；但要注意两条方向性的
    限制，天赋比技能更容易踩：

    * `move_speed: -0.12` 在圣聆初雪的天赋里是「**敌人**减速 12%」，
      而同一把钥匙在别处可能是「自己加速」。归类只能认出这是移速修正，
      **方向读不出来**。
    * `control` 里的寒冷/冻结同理，可能是施加给敌人，也可能是自己承受。

    所以天赋的 `effects` 只作参考，真正驱动模拟的是显式建模的那几个
    （见 `ak_tactic.battle.talents`），别拿 `effects` 直接当结论。
    """
    return _parse_effects(bb, duration_type)


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
