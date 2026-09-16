"""把干员数据的**自然语言描述**翻译成公式模型。

游戏数据里，一条技能/天赋/特性的效果有两种写法，两种都不能单独信：

1. **描述**（`description`）——人话，写清了"做什么、对谁、什么伤害类型"，
   但数字可能是占位符 `{key:0%}`，也可能干脆是定性词（"攻击间隔**大幅度**缩短"）。
2. **黑板**（`blackboard`）——`{key: value}`，数字精确，但**不写语义**：
   `attack@times` 是连击数还是别的？`trigger_time` 是弹药数还是触发间隔？

于是本模块只做一件事：**从描述里抽出「效果公式」**，每条写清
「形状是什么（加减乘、取大、次数）＋量纲从哪来（哪个黑板键）」。

    from ak_tactic.formula import parse
    for term in parse("造成相当于其当前生命值6%的法术伤害（至少造成自身攻击力580%的法术伤害）",
                      {"hp_ratio": 0.06, "projectile_min_atk_scale": 5.8}):
        print(term.line())
    # 伤害  dmg = max(curHP × 6%, ATK × 580%)  [法术]

## 五条设计原则（都是踩出来的）

* **短语级，不是整句级。** 全库一万多条正文能抽象出两千多种句式，整句模板
  匹配必然覆盖不全；但"相当于攻击力N%的X伤害"这类**效果短语**在全库反复出现。
  所以规则匹配短语，一条描述可以命中多条规则。
* **命中即占位，不许同一段文字被两条规则各算一遍。** 否则"攻击力和防御力+18%"
  会同时被"攻击力和防御力"与"防御力"两条规则抽成两项。故先匹配的规则**消费**
  它的文字区间，后来的规则不得与之重叠。
* **量纲由键名与格式说明符共同判定。** `{atk:0%}`（1412 处）与 `{atk}`（925 处）
  文面一样，含义能差 100 倍——`attack_speed` 是绝对值 8，`atk` 是比例 0.14。
  故 `Num` 记下键名与说明符，由 `RATIO_KEYS`/`FLAT_KEYS` 判定，**判不出就标存疑**。
* **不发明数字。** 黑板里没有的键、或没写数字的定性描述，公式里就写 `⟨key⟩`
  或留 `?`，绝不补 0——补 0 会静默把效果吃掉，比缺项难查得多。
* **中文数字也是数字。** 游戏文案大量写"两连击""阻挡三个敌人""每 3 次"，
  不认中文数字会漏掉一整类次数与阻挡。
"""

from __future__ import annotations

import json
import re
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

__all__ = [
    "Num", "Term", "Rule", "RULES", "parse", "render", "formulas", "scan",
    "load_corpus", "describe_row", "RATIO_KEYS", "FLAT_KEYS", "RULED_FLAT_KEYS",
    "CN_NUM",
    "DAMAGE_TYPE_CN",
]

# ---------------------------------------------------------------- 文本规范化

#: 富文本标签：`<@ba.vup>`、`</>`、`<$ba.stun>`
TAG_RE = re.compile(r"<[^>]{0,24}>")

#: 占位符：`{atk_scale:0%}` / `{atk}` / `{ABILITY_RANGE_FORWARD_EXTEND}`
PLACEHOLDER_RE = re.compile(r"\{([^{}]{1,64})\}")

#: 占位符在规范化文本里换成的哨兵：`«3»`（私有区字符，不会与正文撞）
OPEN, CLOSE = "\u00ab", "\u00bb"
SENTINEL_RE = re.compile(rf"{OPEN}(\d+){CLOSE}")

#: 规则里表示"一个数值"的记号：占位符哨兵，或描述里写死的数字（含中文数字）
N = rf"(?:{OPEN}\d+{CLOSE}|\d+(?:\.\d+)?|一|二|两|三|四|五|六|七|八|九|十)"

#: 百分比符号的两种写法
PCT = r"(?:%|％)?"

#: 中文数字 → 阿拉伯数字
CN_NUM: dict[str, float] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}

#: 数值后面跟的括号增量，如 `27%（+3%）`——是"潜能 / 模组加成后的显示值"，
#: **不是**要再加一次。解析时吃掉，避免把它误当成第二个系数。
PAREN_INC = rf"(?:[（(][+\-]?{N}{PCT}[）)])?"


# ---------------------------------------------------------------- 量纲判定

#: 值是**比例**（0.14 → +14%）的黑板键。判据是键名与实测语料。
RATIO_KEYS: frozenset[str] = frozenset({
    "atk", "def", "max_hp", "talent_scale", "prob", "hp_ratio",
    "ep_damage_ratio", "magic_resistance", "sp_recovery_per_sec",
    "damage_scale", "atk_scale", "heal_scale", "scale",
})

#: 值是**绝对值**（8 就是 8）的黑板键。
#: 注意 `value` 归在绝对值：实测它出现在「回复总共{value}点部署费用」这类
#: 计数语境里，当比例会算出 800%。它同时也是最模棱两可的键名之一。
FLAT_KEYS: frozenset[str] = frozenset({
    "attack_speed", "cost", "block_cnt", "max_target", "times", "cnt", "stun",
    "sluggish", "duration", "interval", "ct", "max_stack_cnt", "max_charge_time",
    "ability_range_forward_extend", "ability_range_radius",
    "projectile_delay_time", "trigger_time", "max_deploy_count",
    "hp_recovery_per_sec", "taunt_level", "max_hp", "value",
})

#: 键名后缀即量纲
RATIO_SUFFIX = ("_scale", "_ratio", "_prob", "_pct", "_percent")

#: **博士逐条裁定**为绝对值的键（2026-09-15）。这批键名与上下文都没线索，
#: 判据是**人给的**而不是从语料里核出来的，所以单列一张表、出处可追溯：
#: 记录见 `docs/formula-units.md` 第二节与第四节的 `裁定` 栏，原文写的
#: 「绝对值」与「固定值」是同一个意思（都是 FLAT，不是 SCALE）。
#: 落地前已逐条核对黑板值域：`damage` 500/1000（阿技3「用500的攻击力攻击」）、
#: `multi_times` 4–12（次数）、`interval_damage` 0.5（秒）、`cost_decrease` −1 …
#: 另：`value` 那 59 次"比例"**全部带 `:0%` 说明符**，说明符判据在本表之前，
#: 故它进绝对值表不会误伤那批。
#:
#: 两条**没有**收进来：`scale_delta_to_one`（巫恋 1.3→1.8）与
#: `talent@prob_scaler`（红隼 1.3→2.3）—— 最初被填成「固定值」，但原文都写
#: 「提升至{…}**倍**」、黑板值是 1.x，收进本表会让 1.3 变成"加 1.3"。
#: 2026-09-15 请博士复核，**按数据判为倍率**，故这里永久不收；那两行在
#: `docs/formula-units.md` 里的裁定已写回「倍率」。
RULED_FLAT_KEYS: frozenset[str] = frozenset({
    # 第二节：判不出量纲、由裁定定案的
    "def_penetrate_fixed", "attack@def_penetrate_fixed", "damage",
    "damage_value", "attack@poison_damage", "attack@damage",
    "magic_resist_penetrate_fixed", "attack@chain.extra_value",
    "cost_decrease", "cost_per_add", "cost_period", "cost_display", "ground",
    "floor", "block_cnt_display", "e_attack_speed", "attack_speed_extra",
    "attack@max_target_heal_add", "max_target_shield_add", "def_steal",
    "def_steal_max", "value",
    # 第四节：本由邻字判为绝对值，裁定确认（含几条会被 _base_key 剥成通用名的，
    # 如 `mitm_s_2[cost].display`、`status_resistance[limit]`——正因如此才要
    # 按**原键**比对，否则会把所有 `xxx.display` 一并卷进来）
    "sleep", "attack@sleep", "levitate", "attack@levitate", "levitate_duration",
    "stun_duration", "attack@s2_stun", "failure.stun", "silence", "success.silence",
    "attack@silence", "constraint", "cold", "attack@cold", "fear", "attack@fear",
    "debuff", "not_combat", "disarm", "cooldown", "time", "duration_2",
    "before_dead_duration", "enhance_duration", "chant_duration",
    "attack@final_duration", "buff_duration", "attack@buff_duration", "buff_time",
    "shield_duration", "interval_damage", "sp", "attack@sp", "sp_cost",
    "ability_range_forward_extend",
    "ABILITY_RANGE_FORWARD_EXTEND", "HP_RECOVERY_PER_SEC",
    "blkngt_s_2.duration", "blackd_s_2[period].trig_cnt", "mitm_s_2[cost].display",
    "status_resistance[limit]", "max_cnt", "max_trigger_cnt", "multi_times",
    "chain_times", "attack@chain.max_target", "attack@projectile_life_time",
    "attack@steal_atk_speed", "attack@steal_atk_speed_max", "attack@frozen_duration",
    "attack@heal_max_target",
})

#: **上下文判据**：键名认不出量纲时，看数值后面紧跟的字。
#: 这是从 2794 次"未定"里救回来的大头——`{sleep}秒`、`{stun_duration}秒`、
#: `{def_penetrate_fixed}`（跟在"无视敌人…的防御"后）在键名上毫无线索，
#: 但单位就写在它后面。
_CTX_AFTER: tuple[tuple[re.Pattern, str], ...] = (
    (re.compile(r"^[\s]*(?:秒|s\b|S\b)"), "FLAT"),           # 时间
    (re.compile(r"^[\s]*(?:点|格|名|个|次|层|枚|发|份|颗|道|条)"), "FLAT"),
    (re.compile(r"^[\s]*倍"), "SCALE"),                       # 「提升至 1.4 倍」
    (re.compile(r"^[\s]*(?:%|％)"), "RATIO"),
)


def _base_key(key: str) -> str:
    """`attack@atk_scale` → `atk_scale`；`amiya_t_1[atk].sp` → `sp`。"""
    if not key:
        return ""
    k = key.split("@")[-1]
    if "]" in k:
        k = k.split("]")[-1].lstrip(".") or k
    return k.lstrip("-")


@dataclass(frozen=True)
class Num:
    """描述里的一个数值，连同它的**出处与量纲**。

    量纲有四态，**不能只分"比例/绝对值"两态**——这是踩过的坑：

    * `PCT`   —— 文面里就写了 `%` 的数字，值**已经是百分数**（210 就是 210%）。
                 再乘 100 会得到 21000%（真的发生过）。
    * `RATIO` —— 黑板里的比例，值域 0–1 或倍率（0.14 → 14%、2.1 → 210%）。
    * `FLAT`  —— 绝对值（8 就是 8 秒/点/个）。
    * `UNKNOWN` —— 键名既不在 `RATIO_KEYS` 也不在 `FLAT_KEYS`，**标存疑不猜**。
    """

    value: float | None
    key: str | None = None          # 黑板键；None = 描述里写死的字面数字
    spec: str = ""                  # 格式说明符，如 `0%` / `#%` / `0.0` / ``
    literal: str = ""               # 字面写法，用于回读
    pct: bool = False               # 文面里直接跟了 `%`
    hint: str = ""                  # 上下文判出的量纲（PCT/RATIO/FLAT/SCALE）

    @property
    def unit(self) -> str:
        """量纲：PCT / RATIO / FLAT / SCALE / UNKNOWN。

        判据优先级：文面百分号 > 格式说明符 > 键名白名单 > **上下文**。
        上下文排最后，是因为键名白名单是从实测语料里核出来的，比字面邻字可信；
        但它必须存在，否则 `{sleep}秒` 这类一律落进"存疑"。

        键名**原样与剥前缀后各比一次、且不比大小写**——三个理由都是踩出来的：
        描述里写的常是全大写（`{ABILITY_RANGE_FORWARD_EXTEND}`）而表里是小写；
        `attack@silence` 剥出来是 `silence`；`mitm_s_2[cost].display` 剥出来只剩
        `display`，那个通用名绝不能进白名单，所以原键也要能命中。
        """
        if self.pct:
            return "PCT"
        if self.spec.endswith("%"):
            return "RATIO"
        if self.key is None:
            return "FLAT"                     # 字面数字没有 % 就是绝对值
        names = {self.key.lower(), _base_key(self.key).lower()}
        if any(n in RATIO_KEYS or n.endswith(RATIO_SUFFIX) for n in names):
            return "RATIO"
        if any(n in FLAT_KEYS or n in RULED_FLAT_KEYS for n in names):
            return "FLAT"
        if self.hint:
            return self.hint
        return "UNKNOWN"

    @property
    def is_ratio(self) -> bool | None:
        u = self.unit
        return True if u == "RATIO" else (None if u == "UNKNOWN" else False)

    @property
    def suspect(self) -> bool:
        """量纲判不出来——要显式标出来，别让下游当绝对值用。"""
        return self.unit == "UNKNOWN"

    @property
    def exists(self) -> bool:
        return self.value is not None

    def text(self) -> str:
        """人读写法。"""
        if not self.exists:
            return f"⟨{self.key}⟩" if self.key else "?"
        v = float(self.value)
        u = self.unit
        if u == "PCT":
            return f"{v:g}%"
        if u == "RATIO":
            return f"{v * 100:g}%"
        if u == "SCALE":
            return f"{v:g}倍"
        return f"{v:g}"

    def signed(self, sign: str = "+") -> str:
        return f"{sign}{self.text()}"

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "key": self.key, "spec": self.spec,
                "unit": self.unit, "text": self.text(), "hint": self.hint or None}


# ---------------------------------------------------------------- 公式项

DAMAGE_TYPE_CN = {"PHYSICAL": "物理", "ARTS": "法术", "TRUE": "真实", "HEAL": "治疗",
                  "ELEMENT": "元素"}
_DT_BY_CN = {"物理": "PHYSICAL", "法术": "ARTS", "真实": "TRUE", "治疗": "HEAL",
             "元素": "ELEMENT"}

_LABEL = {
    "damage": "伤害", "heal": "治疗", "buff": "增益", "debuff": "减益",
    "control": "控制", "count": "次数", "targets": "目标", "cost": "费用",
    "pen": "穿透", "regen": "回复", "sp": "技力", "range": "范围",
    "summon": "召唤", "shield": "护盾", "dodge": "闪避", "prob": "概率",
    "flag": "标记", "trait": "特性",
    # —— 元素损伤体系（四类损伤 + 通用机制）——
    "ep_damage": "损伤", "ep_heal": "损伤回复", "ep_burst": "爆发增伤",
    "ep_fragile": "元素脆弱", "ep_resist": "损伤抗性",
}

#: 四类元素损伤。数据里的别名：`神经损伤` 在键名里写作 `ep_*`，
#: 而「元素损伤」是它们的统称（未指明类别时用它）。
EP_TYPES = ("凋亡", "灼燃", "侵蚀", "神经", "水蚀")
EP_ALT = "(?P<ep>凋亡|灼燃|侵蚀|神经|水蚀)"

#: 这些效果的"全部信息"就是那个数值本身，不需要再写成表达式
_COUNT_KINDS = frozenset({"count", "targets", "cost", "summon", "sp"})


@dataclass
class Term:
    """公式模型里的一项。"""

    kind: str                       # damage / heal / buff / control / ...
    expr: str = ""                  # 右侧表达式
    op: str = ""                    # 作用对象：self / ally / enemy / area / team
    dtype: str = ""                 # 伤害类型（PHYSICAL/ARTS/TRUE/HEAL）
    attr: str = ""                  # 增益/减益的属性
    duration: Num | None = None
    count: Num | None = None        # 次数 / 目标数
    amount: Num | None = None       # 系数本身（`scale` 指向的那个数值）
    amount2: Num | None = None      # 第二个系数（`scale2`，取大式用）
    source: str = ""                # 命中的规则名
    evidence: str = ""              # 原文片段（可溯源）
    context: str = ""               # 命中位置**之前**的一小段，判作用域用
    keys: list[str] = field(default_factory=list)
    note: str = ""
    pos: int = 0                    # 命中位置，仅用于按原文顺序排列
    vars: list[str] = field(default_factory=list)   # 带变量的算式依赖哪些变量
    formula: str = ""               # 算式的规范化写法（`50%×加速层数`）

    def label(self) -> str:
        return _LABEL.get(self.kind, self.kind)

    def line(self) -> str:
        parts = [self.label().ljust(3)]
        if self.expr:
            parts.append(self.expr)
        # 次数类效果的"数值"就在 count 里；其余效果是"表达式 × 次数"
        if self.count is not None and self.count.exists:
            if self.kind in _COUNT_KINDS:
                if not self.expr:
                    parts.append(self.count.text())
            else:
                parts.append(f"× {self.count.text()}")
        if self.dtype:
            parts.append(f"[{DAMAGE_TYPE_CN.get(self.dtype, self.dtype)}]")
        if self.attr:
            parts.append(f"({self.attr})")
        if self.duration is not None and self.duration.exists:
            parts.append(f"{self.duration.text()}s")
        if self.op:
            parts.append(f"→{self.op}")
        if self.vars:
            parts.append(f"⟨变量：{'、'.join(self.vars)}⟩")
        if self.note:
            parts.append(f"// {self.note}")
        return "  ".join(parts)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "expr": self.expr, "op": self.op,
            "damage_type": self.dtype or None, "attr": self.attr or None,
            "count": self.count.to_dict() if self.count else None,
            "duration": self.duration.to_dict() if self.duration else None,
            "rule": self.source, "keys": self.keys, "note": self.note or None,
            "evidence": self.evidence,
            "formula": self.formula or None,
            "vars": self.vars or None,
        }


# ---------------------------------------------------------------- 规则

@dataclass(frozen=True)
class Rule:
    """一条短语规则（声明式）。

    `pattern` 里的 `{N}` 是数值占位，`{INC}` 是"数字后面可能跟的括号增量"，
    `{PCT}` 是百分号。`scale`/`dur`/`count` 指向命中片段内第几个数值；
    `form` 决定右式形状（见 `_expr`）。
    """

    name: str
    pattern: str
    kind: str
    op: str = ""
    dtype: str = ""            # 固定伤害类型，或 `=组名`
    attr: str = ""             # 固定属性，或 `=组名`
    source: str = "ATK"        # damage/heal/regen 的基数
    scale: int = -1
    scale2: int = -1           # 第二个系数（取大用）
    dur: int = -1
    count: int = -1
    form: str = ""             # atk_scale / max_of / flat / ratio / signed / sign_down
    pick: str = "first"        # 系数取命中片段里的第几个数值：first / last
    note: str = ""
    flag: str = ""             # flag/trait 类规则附带的值

    def compile(self) -> re.Pattern:
        p = (self.pattern.replace("{INC}", PAREN_INC)
             .replace("{PCT}", PCT).replace("{N}", N))
        return re.compile(p)


def _r(name: str, pattern: str, kind: str, **kw: Any) -> Rule:
    return Rule(name=name, pattern=pattern, kind=kind, **kw)


#: 规则表。**顺序即优先级**：先匹配的先消费文字区间，后来的不得重叠。
#: 所以"更具体"的规则要写在"更一般"的前面。
RULES: tuple[Rule, ...] = (
    # ================================================= 组合式（必须先匹配）
    # 多段伤害：「造成3次攻击力210%的法术伤害」——次数与系数在同一句里
    _r("damage_multi_hit",
       rf"造成{N}次攻击力{N}{PCT}{{INC}}的(?:群体|范围|溅射)?(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK",
       scale=1, count=0, form="atk_scale", note="连击"),
    # 取大式：「造成相当于其当前生命值6%的法术伤害（至少造成自身攻击力580%的法术伤害）」
    # 括号里那半句也带「的X伤害」——不许省，省了就整条匹配不上。
    _r("damage_max_of",
       rf"造成相当于(?:其)?当前生命(?:值)?{N}{PCT}{{INC}}的(?:群体|范围)?(?P<dt>物理|法术|真实|元素)伤害"
       rf"[（(]至少造成(?:自身)?攻击力{N}{PCT}{{INC}}的(?:群体|范围)?(?:物理|法术|真实)伤害[）)]",
       "damage", op="enemy", dtype="=dt", source="curHP",
       scale=0, scale2=1, form="max_of", note="下限由攻击力决定"),
    # ================================================= 元素爆发期（必须先于"伤害"）
    # 「若目标处于X爆发期间则对其额外造成相当于攻击力N%的元素伤害」如果留给
    # 通用的 `damage_atk`，会被当成一次普通元素伤害——**条件性**就丢了。
    # 所以这四条要排在整张伤害表之前。
    _r("ep_burst_extra",
       rf"对处于(?:{EP_ALT}|元素)(?:损伤)?爆发期间的?(?:目标|敌人)(?:额外)?造成"
       rf"相当于攻击力{N}{PCT}{{INC}}的元素伤害",
       "ep_burst", op="enemy", dtype="ELEMENT", source="ATK", scale=1,
       form="atk_scale", note="仅在爆发期成立"),
    _r("ep_burst_extra2",
       rf"处于(?:{EP_ALT}|元素)(?:损伤)?爆发期间[^，。；]{{0,8}}?额外造成"
       rf"相当于攻击力{N}{PCT}{{INC}}的元素伤害",
       "ep_burst", op="enemy", dtype="ELEMENT", source="ATK", scale=0,
       form="atk_scale", note="仅在爆发期成立"),
    _r("ep_burst_switch",
       rf"处于(?:{EP_ALT}|元素)(?:损伤)?爆发期间则改为造成元素伤害",
       "ep_burst", op="enemy", dtype="ELEMENT", flag="爆发期改为元素伤害"),
    _r("ep_burst_damage_up",
       rf"对处于(?:{EP_ALT}|元素)(?:损伤)?爆发期间的?(?:目标|敌人)造成的伤害提升至{N}{PCT}",
       "ep_burst", op="enemy", scale=0, form="signed", note="仅在爆发期成立"),
    # ================================================= 伤害
    _r("damage_atk_before",
       rf"造成相当于{N}{PCT}{{INC}}攻击力的(?:群体|范围|溅射)?"
       rf"(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=0, form="atk_scale",
       note="数字在「攻击力」之前"),
    _r("damage_atk",
       rf"造成相当于(?:自身|其)?攻击力{N}{PCT}{{INC}}的(?:群体|范围|溅射)?(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=0, form="atk_scale"),
    _r("damage_atk_short",
       rf"造成(?:相当于)?(?:自身|其)?攻击力{N}{PCT}{{INC}}的(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=0, form="atk_scale"),
    _r("damage_curhp",
       rf"造成相当于(?:其)?当前生命(?:值)?{N}{PCT}{{INC}}的(?:群体)?(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="curHP", scale=0, form="atk_scale"),
    _r("damage_maxhp",
       rf"造成相当于(?:其)?最大生命{N}{PCT}{{INC}}的(?:群体)?(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="maxHP", scale=0, form="atk_scale"),
    _r("damage_bare",
       rf"造成相当于(?:自身|其)?攻击力{N}{PCT}{{INC}}的伤害",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale",
       note="伤害类型未写明"),
    # 攻击力倍率（下次攻击 / 当次攻击）
    _r("mult_next_attack",
       rf"下次攻击的攻击力(?:提高|提升)至{N}{PCT}{{INC}}",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale",
       note="单次攻击的倍率"),
    _r("mult_this_attack",
       rf"当次攻击的攻击力(?:提升|提高)至{N}{PCT}{{INC}}",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale"),
    _r("mult_atk_up_to",
       rf"攻击力(?:提升|提高)至{N}{PCT}{{INC}}",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale"),
    _r("damage_scale_up",
       rf"(?:造成的)?(?:物理|法术|真实)?伤害(?:提升|提高|增加){N}{PCT}",
       "buff", op="self", attr="伤害倍率", scale=0, form="signed",
       note="乘在伤害上"),
    _r("damage_taken_up",
       rf"(?:受到|使目标受到|使其受到)的?伤害(?:提升|增加|提高)(?:至)?{N}{PCT}",
       "debuff", op="enemy", attr="受到伤害", scale=0, form="signed",
       note="脆弱类"),
    # ================================================= 元素损伤体系
    # 玩家侧的四类损伤（凋亡/灼燃/侵蚀/神经）+ 爆发/回复/脆弱/抗性。
    # 这与 P3R 的**敌方元素相性**是两条不同的轴，别混。
    # 四条爆发期规则已提到文件更上方（它们会被通用伤害规则抢走）。
    # 其余元素规则在这里即可，但必须早于治疗/回复：文案常写
    # 「每秒回复…的元素损伤」，让通用「每秒回复」先命中会得到空的 "回复 ?"。
    # 造成损伤（`攻击附带造成伤害X%的凋亡损伤` / `附带X%攻击力的神经损伤`）
    _r("ep_damage_attach",
       rf"(?:攻击)?附带(?:造成)?(?:物理|法术|真实)?伤害{N}{PCT}{{INC}}的"
       rf"(?:{EP_ALT}|元素)?损伤",
       "ep_damage", op="enemy", attr="=ep", source="ATK", scale=0, form="atk_scale"),
    _r("ep_damage_atk",
       rf"附带{N}{PCT}{{INC}}攻击力的(?:{EP_ALT}|元素)?损伤",
       "ep_damage", op="enemy", attr="=ep", source="ATK", scale=0, form="atk_scale"),
    _r("ep_damage_flat",
       rf"造成(?:相当于)?攻击力{N}{PCT}{{INC}}的(?:{EP_ALT}|元素)?损伤",
       "ep_damage", op="enemy", attr="=ep", source="ATK", scale=0, form="atk_scale"),
    _r("ep_damage_up",
       rf"(?:造成的)?(?:对精英和领袖敌人造成的)?(?:{EP_ALT}|元素)?损伤"
       rf"(?:提升|增加|提高){N}{PCT}",
       "buff", op="self", attr="元素损伤", scale=0, form="signed"),
    # 回复友方的损伤条（元素医疗的核心手段）。
    # 文案会在"攻击力"前面**夹一个干员名**（"恢复蜜莓攻击力8%的元素损伤"），
    # 所以中间那段要用 `\S{0,10}` 兜住，并放在固定写法之前。
    _r("ep_heal_name",
       rf"(?:回复|恢复)\S{{0,10}}攻击力{N}{PCT}{{INC}}的(?:{EP_ALT}|元素)?损伤",
       "ep_heal", op="ally", attr="=ep", source="ATK", scale=0, form="atk_scale",
       pick="last"),
    _r("ep_heal_ratio",
       rf"回复相当于攻击力{N}{PCT}{{INC}}的(?:{EP_ALT}|元素)?损伤",
       "ep_heal", op="ally", attr="=ep", source="ATK", scale=0, form="atk_scale"),
    _r("ep_heal_up",
       rf"(?:元素损伤回复量|损伤回复量|元素损伤回复量)(?:提升|提高)至{N}{PCT}",
       "ep_heal", op="ally", source="ATK", scale=0, form="atk_scale",
       note="回复量倍率"),
    _r("ep_heal_flat",
       rf"每秒回复{N}点(?:{EP_ALT}|元素)?损伤",
       "ep_heal", op="self", scale=0, form="flat"),
    _r("ep_heal_clear",
       r"清除自身的?(?:{EP_ALT}|元素)?损伤".replace("{EP_ALT}", EP_ALT),
       "ep_heal", op="self", note="清空损伤条"),
    _r("ep_fragile",
       rf"获得{N}{PCT}的(?:【)?(?:元素|法术)?脆弱(?:】)?",
       "ep_fragile", op="enemy", attr="元素脆弱", scale=0, form="signed"),
    _r("ep_shield",
       rf"获得{N}点损伤屏障", "shield", op="self", scale=0, form="flat"),
    _r("ep_resist",
       rf"元素损伤抗性\+?{N}{PCT}", "ep_resist", op="self", attr="元素损伤抗性",
       scale=0, form="signed"),

    # ================================================= 治疗 / 回复
    # 文案会在动词与"相当于"之间塞一长串（"恢复攻击范围内所有友方单位相当于…"），
    # 所以中间那段用 `\S{0,14}` 兜住。
    _r("heal_restore_named",
       rf"(?:恢复|回复)\S{{0,14}}?相当于(?:\S{{0,8}})?(?:自身|其)?攻击力{N}{PCT}{{INC}}的?"
       rf"(?:生命值|生命)",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale",
       pick="last"),
    _r("heal_amount_of",
       rf"(?:回复量|回复量为|治疗量)\S{{0,8}}?攻击力的{N}{PCT}",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale",
       pick="last"),
    _r("heal_maxhp_ratio",
       rf"(?:额外)?回复(?:目标|自身)?最大生命值的{N}{PCT}",
       "heal", op="ally", dtype="HEAL", source="maxHP", scale=0, form="atk_scale",
       pick="last"),
    _r("heal_restore_life",
       rf"恢复(?:相当于)?(?:自身|其)?攻击力{N}{PCT}{{INC}}的?(?:生命值|生命)",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale"),
    _r("heal_restore_maxhp",
       rf"恢复最大生命的{N}{PCT}{{INC}}",
       "heal", op="ally", dtype="HEAL", source="maxHP", scale=0, form="atk_scale"),
    _r("heal_atk",
       rf"治疗相当于{N}{PCT}{{INC}}攻击力",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale"),
    _r("heal_scale",
       rf"治疗量(?:变为|相当于){N}{PCT}",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale"),
    _r("heal_scale_up",
       rf"治疗量(?:提升|提高)至(?:攻击力的)?{N}{PCT}",
       "heal", op="ally", dtype="HEAL", source="ATK", scale=0, form="atk_scale",
       note="治疗量倍率"),
    _r("regen_atk_per_sec",
       rf"每秒(?:回复|恢复)相当于(?:自身|其)?攻击力{N}{PCT}{{INC}}的"
       rf"(?:生命值?|(?:{EP_ALT}|元素)?损伤)",
       "regen", op="ally", source="ATK", scale=0, form="atk_scale"),
    _r("regen_plain_per_sec",
       rf"每秒(?:回复|恢复){N}点生命", "regen", op="ally", scale=0, form="flat"),
    _r("regen_self",
       rf"回复自身{N}{PCT}{{INC}}生命",
       "regen", op="self", source="maxHP", scale=0, form="atk_scale"),
    _r("regen_flat",
       rf"(?:立即)?(?:恢复|回复)(?:全场)?(?:友方单位)?{N}点生命",
       "regen", op="ally", scale=0, form="flat"),
    _r("regen_sp",
       rf"每(?:秒|次)?(?:恢复|回复){N}点(?:技力|SP)",
       "sp", op="self", scale=0, form="flat"),
    # ================================================= 护盾与屏障
    _r("shield_maxhp",
       rf"(?:获得)?(?:可吸收)?相当于(?:自己|自身)?最大生命{N}{PCT}{{INC}}的(?:屏障|护盾)",
       "shield", op="self", source="maxHP", scale=0, form="atk_scale"),
    _r("shield_flat",
       rf"获得{N}点(?:屏障|护盾)",
       "shield", op="self", scale=0, form="flat"),
    # ================================================= 召唤
    _r("summon_cnt",
       rf"(?:可以携带|可以使用|可召唤){N}个", "summon", op="self", count=0),
    _r("summon_deploy",
       rf"最多(?:同时)?(?:可)?部署{N}个", "summon", op="self", count=0),
    # ================================================= 控制（数字在前/在后都认）
    _r("control_stun",
       rf"(?:晕眩|眩晕){N}秒", "control", op="enemy", attr="晕眩", dur=0),
    _r("control_stun_pre",
       rf"{N}秒(?:的)?(?:晕眩|眩晕)", "control", op="enemy", attr="晕眩", dur=0),
    _r("control_sleep",
       rf"沉睡{N}秒", "control", op="enemy", attr="沉睡", dur=0),
    _r("control_bind",
       rf"束缚{N}秒", "control", op="enemy", attr="束缚", dur=0),
    _r("control_silence",
       rf"沉默{N}秒", "control", op="enemy", attr="沉默", dur=0),
    _r("control_slow",
       rf"停顿{N}秒", "control", op="enemy", attr="停顿", dur=0),
    _r("control_slow_pre",
       rf"{N}秒(?:的)?停顿", "control", op="enemy", attr="停顿", dur=0),
    _r("control_fear",
       rf"恐惧{N}秒", "control", op="enemy", attr="恐惧", dur=0),
    _r("control_brief",
       r"造成短暂的?停顿", "control", op="enemy", attr="停顿",
       note="文案未给时长，数值在黑板 sluggish"),
    # ================================================= 次数与目标
    _r("count_lianji_cn",
       r"(?:变为)?(?P<n>[二两三四五])连击", "count", op="enemy",
       count=0, flag=""),
    _r("count_lianji_launch",
       rf"发动(?:一次)?{N}连击", "count", op="enemy", count=0, pick="last",
       note="一次性多段"),
    _r("count_continuos",
       rf"连续攻击{N}次", "count", op="enemy", count=0),
    _r("count_times",
       rf"造成{N}次攻击力", "count", op="enemy", count=0, note="连击次数"),
    _r("count_every_attack",
       rf"每(?:次)?攻击{N}次", "count", op="enemy", count=0),
    _r("targets_max",
       rf"对最多{N}(?:名|个)敌人", "targets", op="enemy", count=0),
    _r("targets_range",
       rf"对(?:周围|范围)?{N}格内", "targets", op="area", count=0),
    _r("targets_jump",
       rf"在{N}个敌人间跳跃", "targets", op="enemy", count=0),
    _r("targets_all_blocked",
       r"同时攻击阻挡的所有敌人", "targets", op="enemy", note="阻挡的全部"),
    # ================================================= 费用
    _r("cost_gain",
       rf"(?:立即)?(?:获得|回复){N}点部署费用", "cost", op="self", count=0),
    _r("cost_gain_total",
       rf"回复总共{N}点部署费用", "cost", op="self", count=0),
    _r("cost_down",
       rf"部署费用-{N}", "buff", op="self", attr="部署费用", scale=0,
       form="sign_down"),
    _r("cost_down2",
       rf"部署费用降低{N}", "buff", op="self", attr="部署费用", scale=0,
       form="sign_down"),
    # ================================================= 面板增益
    _r("buff_atk_def_each",
       rf"攻击力和防御力各\+{N}{PCT}", "buff", op="ally", attr="攻击力/防御力",
       scale=0, form="signed"),
    _r("buff_atk_def",
       rf"攻击力和防御力\+{N}{PCT}", "buff", op="ally", attr="攻击力/防御力",
       scale=0, form="signed"),
    _r("buff_atk",
       rf"攻击力\+{N}{PCT}", "buff", op="self", attr="攻击力", scale=0,
       form="signed"),
    _r("buff_def",
       rf"防御力\+{N}{PCT}", "buff", op="self", attr="防御力", scale=0,
       form="signed"),
    _r("buff_maxhp",
       rf"生命上限\+{N}{PCT}", "buff", op="self", attr="生命上限", scale=0,
       form="signed"),
    _r("buff_aspd",
       rf"攻击速度\+{N}{PCT}", "buff", op="self", attr="攻击速度", scale=0,
       form="signed"),
    _r("buff_res",
       rf"法术抗性\+{N}{PCT}", "buff", op="self", attr="法术抗性", scale=0,
       form="signed"),
    _r("buff_block",
       rf"阻挡数\+{N}", "buff", op="self", attr="阻挡数", scale=0, form="signed"),
    _r("buff_block_down",
       rf"阻挡数-{N}", "buff", op="self", attr="阻挡数", scale=0, form="sign_down"),
    # —— 2026-09-16 补：博士裁定「不保留自然语言」，干员侧缺的属性词一次补齐。
    #
    # 这一批**不是**「接算式 pass」能解决的：`攻击距离+1` 看着像一个代数式
    # （变量「攻击距离」加 1），实际是一条**属性增益**。算式 pass 接上去只会
    # 吐出一堆 `算式 攻击距离+1 ⟨变量：攻击距离⟩` —— 形式忠实、语义全错，
    # 而且比不收更糟：它把一个"没认出来"伪装成"已经解析"。所以补的是规则。
    # 判据是「模拟器会不会因为这个量改变结算」，与敌人侧 `_EXPR_ATTR` 同口径。
    _r("buff_attack_range",
       rf"攻击距离\+{N}(?:格)?", "range", op="self", attr="攻击距离", scale=0,
       form="signed"),
    _r("debuff_attack_range",
       rf"攻击距离-{N}(?:格)?", "range", op="self", attr="攻击距离", scale=0,
       form="sign_down"),
    _r("buff_max_target",
       rf"(?:攻击|治疗)?目标数\+{N}", "targets", op="self", attr="攻击目标数",
       scale=0, form="signed"),
    _r("debuff_max_target",
       rf"(?:攻击|治疗)?目标数-{N}", "targets", op="self", attr="攻击目标数",
       scale=0, form="sign_down"),
    _r("buff_drone",
       rf"浮游单元\+{N}", "buff", op="self", attr="浮游单元", scale=0,
       form="signed"),
    _r("buff_maxhp_full",
       rf"最大生命值\+{N}{PCT}", "buff", op="self", attr="生命上限", scale=0,
       form="signed"),
    _r("debuff_maxhp_full",
       rf"最大生命值-{N}{PCT}", "buff", op="self", attr="生命上限", scale=0,
       form="sign_down"),
    _r("buff_def_gain",
       rf"防御力{N}{PCT}的增益", "buff", op="self", attr="防御力", scale=0,
       form="signed"),
    _r("buff_inspire",
       rf"获得相当于(?:\S{{0,8}})?(?P<who>[\u4e00-\u9fa5]{{1,6}})?攻击力{N}{PCT}{{INC}}的鼓舞效果",
       "buff", op="ally", attr="鼓舞", source="ATK", scale=0, form="atk_scale",
       pick="last"),
    _r("buff_range",
       rf"攻击范围\+{N}格", "range", op="self", scale=0, form="flat"),
    # ================================================= 面板减益
    _r("debuff_res",
       rf"法术抗性-{N}{PCT}", "debuff", op="enemy", attr="法术抗性", scale=0,
       form="sign_down"),
    _r("debuff_def",
       rf"防御力-{N}{PCT}", "debuff", op="enemy", attr="防御力", scale=0,
       form="sign_down"),
    _r("debuff_aspd",
       rf"攻击速度-{N}{PCT}", "debuff", op="enemy", attr="攻击速度", scale=0,
       form="sign_down"),
    _r("debuff_ms",
       rf"移动速度-{N}{PCT}", "debuff", op="enemy", attr="移动速度", scale=0,
       form="sign_down"),
    _r("debuff_ms_down",
       rf"移动速度降低{N}{PCT}", "debuff", op="enemy", attr="移动速度", scale=0,
       form="sign_down"),
    _r("debuff_weight",
       rf"重量-{N}", "debuff", op="enemy", attr="重量", scale=0, form="sign_down"),
    # ================================================= 穿透 / 闪避 / 脆弱
    _r("pen_res",
       rf"无视(?:目标|敌人)?{N}(?:点|%|％)?的?法术抗性", "pen", op="enemy",
       attr="法术抗性", scale=0, form="flat"),
    _r("pen_def",
       rf"无视(?:目标|敌人)?{N}(?:点|%|％)?的?防御力?", "pen", op="enemy",
       attr="防御力", scale=0, form="flat"),
    # 闪避三条：「的」**必须是可选的**。正文里带「的」与不带「的」各占一半
    # （赤刃明霄陈技2 原文就是「获得60%物理和法术闪避」，没有「的」），
    # 写成必须有「的」会让全库一半的闪避正文一条也编不出来——这正是
    # 「闪避」长期没接进战斗层的根因：编译层不吐项，下游自然无事可做。
    # 同文件的 `pen_res` / `pen_def` 早就写的是 `的?`，此处只是补齐。
    # 战斗侧的同一判据在 `operator/skill.py::_wants_dodge`，两处必须同口径。
    _r("dodge_both",
       rf"获得{N}{PCT}的?物理和法术闪避", "dodge", op="self", attr="物理/法术闪避",
       scale=0, form="signed"),
    _r("dodge_phys",
       rf"获得{N}{PCT}的?物理闪避", "dodge", op="self", attr="物理闪避",
       scale=0, form="signed"),
    _r("dodge_arts",
       rf"获得{N}{PCT}的?法术闪避", "dodge", op="self", attr="法术闪避",
       scale=0, form="signed"),
    _r("fragile",
       rf"获得{N}{PCT}的(?:【)?脆弱(?:】)?", "debuff", op="enemy", attr="脆弱",
       scale=0, form="signed"),
    _r("shelter",
       rf"获得{N}{PCT}的(?:【)?庇护(?:】)?", "buff", op="ally", attr="庇护",
       scale=0, form="signed"),
    # ================================================= 概率与持续
    _r("prob_hit",
       rf"{N}{PCT}的?(?:概率|几率)", "prob", op="self", scale=0, form="signed"),
    _r("duration_sec",
       rf"持续{N}秒", "flag", dur=0, flag="持续"),
    _r("range_expand",
       r"攻击范围(?:扩大|改变|增大)", "range", op="self", flag="范围改写"),
    # ================================================= 职业特性（trait_text）
    # 「攻击造成群体法术伤害」要排在「攻击造成X伤害」前面，否则匹配不到
    _r("trait_group_damage",
       r"攻击造成(?:群体|范围)(?P<dt>物理|法术|真实|元素)?伤害", "trait", dtype="=dt",
       flag="群体伤害"),
    _r("trait_damage_type",
       r"攻击造成(?P<dt>物理|法术|真实|元素)伤害", "trait", dtype="=dt",
       flag="攻击伤害类型"),
    _r("trait_block_cn",
       rf"(?:能够)?阻挡{N}个?(?:敌人)?", "trait", count=0, flag="阻挡数"),
    _r("trait_attack_all",
       r"攻击(?:范围内)?(?:的)?所有(?:被阻挡的)?敌人", "trait", flag="群体攻击"),
    _r("trait_air",
       r"可以攻击到?(?:空中|飞行)单位", "trait", flag="可对空"),
    _r("trait_ground_only",
       r"只(?:能)?攻击地面单位", "trait", flag="仅地面"),
    _r("trait_floating_unit",
       r"操作浮游单元", "trait", flag="浮游单元"),
    _r("trait_invisible_off",
       r"隐匿效果失效", "trait", op="enemy", flag="反隐"),
    _r("trait_start_deploy",
       r"战斗开始时一定出现在待部署区", "flag", flag="开局在待部署区"),
    _r("trait_range_extend",
       r"攻击范围视为\S{2,12}攻击范围的延伸", "flag", flag="范围延伸"),
    _r("trait_refund",
       r"撤退时返还(?:大量)?该次部署费用", "flag", flag="撤退返还费用"),
    _r("trait_mode_ranch",
       r"(?:只可部署在|可以圈养在|圈养在)(?:大型)?兽栏", "flag", flag="生息演算专用"),
    # ================================================= 附带伤害与减伤
    _r("damage_extra_hit",
       rf"附带{N}{PCT}{{INC}}攻击力的(?:物理|法术|真实)伤害",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale",
       note="附加伤害"),
    _r("damage_reduce",
       rf"受到(?:的|来自[^，。；]{{0,10}}的)?(?:物理|法术|真实)?伤害(?:减少|降低|-|−){N}{PCT}",
       "buff", op="self", attr="受到伤害减免", scale=0, form="sign_down"),
    _r("damage_dot",
       rf"每秒受到(?:相当于)?\S{{0,8}}?攻击力{N}{PCT}{{INC}}的(?:群体|范围)?"
       rf"(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=0, form="atk_scale",
       pick="last", note="每秒结算一次"),
    _r("damage_dot_mid",
       rf"造成每秒相当于(?:\S{{0,8}})?攻击力{N}{PCT}{{INC}}的(?:群体|范围)?"
       rf"(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=0, form="atk_scale",
       pick="last", note="每秒结算一次"),
    _r("damage_summon_max",
       rf"最高造成干员{N}{PCT}攻击力的伤害",
       "damage", op="enemy", source="ATK", scale=0, form="atk_scale",
       note="召唤物叠满时的伤害"),
    _r("heal_up",
       rf"治疗量(?:提升|增加){N}{PCT}", "buff", op="self", attr="治疗量",
       scale=0, form="signed"),
    _r("damage_distance",
       rf"最高(?:提升|增加){N}{PCT}", "buff", op="self", attr="距离伤害加成",
       scale=0, form="signed"),
    _r("heal_jump",
       rf"在{N}个友方单位间跳跃", "targets", op="ally", count=0),
    _r("sp_recovery_persec",
       rf"技力(?:自然)?(?:恢复|回复)速度\+{N}(?:/秒)?", "sp", op="self",
       scale=0, form="flat"),
    _r("sp_gain",
       rf"(?:获得|回复){N}点技力", "sp", op="self", scale=0, form="flat"),
    _r("control_interval_stun",
       rf"每{N}秒受到一次停顿", "control", op="enemy", attr="停顿", dur=0),
    _r("targets_ally",
       rf"(?:对|为)范围内(?:的|最多){N}名(?:我方)?干员", "targets", op="ally",
       count=0),
    _r("cost_per_sec",
       rf"每{N}秒消耗{N}点部署费用", "cost", op="self", scale=1, dur=0,
       count=1, form="flat", note="持续扣费"),
    _r("hold_limit",
       rf"持有上限\+{N}", "buff", op="self", attr="持有上限", scale=0,
       form="signed"),
    # ================================================= 战斗相关的其余高频句式
    # （风味文案与生息演算专用句式一律不收——博士裁定"只补战斗相关"）
    _r("heal_received_up",
       rf"受到的治疗效果(?:提升|增加){N}{PCT}", "buff", op="self",
       attr="受治疗加成", scale=0, form="signed"),
    _r("fragile_effect",
       rf"受到{N}{PCT}的(?:物理|法术|真实)?脆弱效果", "debuff", op="enemy",
       attr="脆弱", scale=0, form="signed"),
    _r("atk_down_to",
       rf"攻击力降低至{N}{PCT}", "buff", op="self", attr="攻击力(降低)",
       scale=0, form="sign_down"),
    _r("damage_distance_max",
       rf"最高达到{N}{PCT}", "buff", op="self", attr="距离伤害加成", scale=0,
       form="signed"),
    _r("mult_lianji",
       rf"(?:每次攻击)?变为攻击力{N}{PCT}{{INC}}的{N}连击",
       "damage", op="enemy", source="ATK", scale=0, count=1, form="atk_scale",
       note="连击"),
    _r("damage_multi_hit2",
       rf"造成{N}次相当于攻击力{N}{PCT}{{INC}}的(?:群体|范围|溅射)?"
       rf"(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="enemy", dtype="=dt", source="ATK", scale=1, count=0,
       form="atk_scale", note="连击"),
    _r("targets_at_once",
       rf"(?:可以)?同时攻击{N}个?目标", "targets", op="enemy", count=0),
    _r("count_per_target",
       rf"每个目标攻击{N}次", "count", op="enemy", count=0),
)


# ---------------------------------------------------------------- 解析

def normalize(text: str) -> tuple[str, list[tuple[str, str]]]:
    """剥标签、把占位符换成哨兵。返回 (规范化文本, [(键, 说明符)])。"""
    slots: list[tuple[str, str]] = []

    def take(m: re.Match) -> str:
        key, _, spec = m.group(1).partition(":")
        slots.append((key.strip(), spec.strip()))
        return f"{OPEN}{len(slots) - 1}{CLOSE}"

    flat = PLACEHOLDER_RE.sub(take, TAG_RE.sub("", text or ""))
    return flat.replace("\\r\\n", "\n").replace("\\n", "\n"), slots


def _lookup(bb: dict[str, Any], key: str) -> Any:
    """取黑板值。**大小写不敏感**——描述里的键名常是全大写
    （`{ABILITY_RANGE_FORWARD_EXTEND}`），黑板里却是小写。"""
    if not isinstance(bb, dict):        # 传进来的可能是 [{key,value}] 原文
        return None
    if key in bb:
        return bb[key]
    low = key.lower()
    for k, v in bb.items():
        if k.lower() == low:
            return v
    return None


def nums_in(span: str, slots: list[tuple[str, str]],
            blackboard: dict[str, Any]) -> list[Num]:
    """把一段文本里的数值按出现顺序解出来（含中文数字、文面百分号、上下文量纲）。"""
    out: list[Num] = []
    for m in re.finditer(N, span):
        raw = m.group(0)
        after = span[m.end():m.end() + 1]
        pct = after in ("%", "％")
        hint = ""
        if not pct:
            tail = span[m.end():m.end() + 2]
            for pat, unit in _CTX_AFTER:
                if pat.match(tail):
                    hint = unit
                    break
        if raw.startswith(OPEN):
            i = int(SENTINEL_RE.match(raw).group(1))
            key, spec = slots[i] if i < len(slots) else ("", "")
            val = _lookup(blackboard, key)
            if val is None:
                out.append(Num(value=None, key=key, spec=spec, literal=raw,
                               pct=pct, hint=hint))
            else:
                try:
                    out.append(Num(value=float(val), key=key, spec=spec,
                                   literal=str(val), pct=pct, hint=hint))
                except (TypeError, ValueError):
                    out.append(Num(value=None, key=key, spec=spec,
                                   literal=str(val), pct=pct, hint=hint))
        elif raw in CN_NUM:
            out.append(Num(value=CN_NUM[raw], literal=raw, pct=pct, hint=hint))
        else:
            try:
                out.append(Num(value=float(re.sub(r"[^\d.]", "", raw)),
                               literal=raw, pct=pct, hint=hint))
            except ValueError:
                out.append(Num(value=None, literal=raw, pct=pct, hint=hint))
    return out


def _pick(m: re.Match, spec: str) -> str:
    """`=组名` 表示从捕获组取，否则就是字面量。组没参与匹配时返回空串。"""
    if spec.startswith("="):
        try:
            return m.group(spec[1:]) or ""
        except (IndexError, KeyError):
            return ""
    return spec


def _coeff(num: Num | None, source: str) -> str:
    """把系数写进表达式：`ATK × 210%`。"""
    if num is None:
        return "?"
    if not num.exists:
        return f"{source} × ⟨{num.key}⟩" if num.key else f"{source} × ?"
    return f"{source} × {num.text()}"


def _expr(rule: Rule, ns: list[Num]) -> str:
    """按规则声明的形状拼右式。"""
    def at(i: int) -> Num | None:
        return ns[i] if 0 <= i < len(ns) else None

    a, b = at(rule.scale), at(rule.scale2)
    form = rule.form
    if form == "word":
        # 无数值形状：语义全在 `flag` / `note` 里（「无敌」「不可阻挡」这类）。
        # 必须有这一支，否则 `a is None` 会落到末尾返回 `?`，
        # 而 `?` 非空又会让 `flag` 填不进去（parse 只在 expr 为空时才用 flag）。
        return ""
    if form == "max_of":
        return f"max({_coeff(a, rule.source)}, {_coeff(b, 'ATK')})"
    if form in ("atk_scale",):
        return _coeff(a, rule.source)
    if form == "flat":
        return a.text() if a else "?"
    if form == "signed":
        return a.signed("+") if a else "?"
    if form == "sign_down":
        return a.signed("-") if a else "?"
    if rule.kind in _COUNT_KINDS or rule.kind == "control":
        return ""                        # 数值由 count / duration 携带
    return a.text() if a else ""


# ================================================================ 带变量的算式
#
# 正文里有一类**带变量的算式**：`移动速度+(50%×加速层数)`、`防御力+(30×充能层数)%`、
# `每秒受到(层数×300)无来源真实伤害`、`攻击力+（场上的啸叫音响数量×25%）`。
#
# 这一类**不能按常数提取**——不是"漏了"，是**会算错**：常数提取会把 50% 当成系数，
# 得到 `ATK × 50%`。表达式看起来完全合理，实际意思是「**每层** 50%」。
# 这正是本项目记录在案的那类真错误（条件/结构丢失而表达式看着对）。
#
# 所以这里只做**识别与规范化**，不求值：层数、数量、当前SP 这些变量的值在运行时
# 才知道，编译期编不出来。产出 `Term.amount is None`、`Term.expr` 是算式本身、
# `Term.vars` 列出依赖的变量——**结构保留下来，数值留白**。

@dataclass(frozen=True)
class Expr:
    """一段带变量的算式（结构化，未求值）。"""

    text: str                       # 规范化写法：`50%×加速层数`
    vars: tuple[str, ...]           # 依赖的变量名（按出现序去重）
    op: str = "mul"                 # 顶层运算符：add / mul
    pct: bool = False               # 整个算式是百分比（`(30×充能层数)%`）
    lead: str = ""                  # 最外层 `+`/`-` 的**左操作数**（目标属性），裸词才算
    sign: str = ""                  # `+` / `-`

    def label(self) -> str:
        return self.text


#: 裸词：不含数字、运算符、括号。用来判「最外层加号的左边是不是一个属性名」。
_BARE = re.compile(r"^[^\d\s，。；、：:,.（）()\[\]×*/÷+\-＋－%％]+$")


#: 分词。三个坑：
#: ① **不能用 `m.lastgroup` 判类型**——它返回的是最后一个匹配的**子组**，
#:    `50%` 的 `lastgroup` 是 `pct` 而不是 `num`，于是所有含百分号的算式都被
#:    判成非法（这一版真踩过，表现为「(50%×加速层数) → None」）。
#:    改用 `_kind()`：按固定优先级逐个查组是否非 None。
#: ② 数值（含尾随 `%`）优先于词，否则 `50` 会被当变量词吞掉。
#: ③ 独立的 `%` 单列一支：`(30×充能层数)%` 的百分号挂在括号**后面**。
_TOK = re.compile(
    r"(?P<num>\d+(?:\.\d+)?)(?P<pct>[%％])?"
    r"|(?P<op>[×*/÷+\-＋－])"
    r"|(?P<open>[（(])"
    r"|(?P<close>[）)])"
    r"|(?P<bang>[%％])"
    r"|(?P<word>[^\s，。；、：:,.；（）()\[\]×*/÷+\-＋－%％]+)"
)

_GROUPS = ("num", "op", "open", "close", "bang", "word")
_OP_CANON = {"*": "×", "＋": "+", "－": "-"}


def _kind(m: re.Match) -> str:
    """按**固定优先级**判 token 类型；不要用 `m.lastgroup`（见 `_TOK` 注释①）。"""
    for g in _GROUPS:
        if m.group(g) is not None:
            return g
    return ""


def _tokens(text: str) -> list[re.Match]:
    return list(_TOK.finditer(text))


def _var_name(tok: str) -> str | None:
    """把 token 归一成**变量名**；不是变量就返回 None。

    中文没有空格，分词只能按标点切，于是变量名常和前面的散文粘在一起：
    `成功造成伤害后再造成当前移动速度×800` 里的变量是 **当前移动速度**，
    可 token 是整串。所以要按**最后一个动词**切开，取它后面那截。

    切开之后还要剥掉残留的虚词（`降低至已处理目标数量` → `已处理目标数量`）。
    判据有三条：含非数字字符、**不含任何数字**、且不再含动词。

    第二条（含数字者一律不是变量）挡掉的全是散文碎片：
    `附着范围为1×1`、`1层攻击力+10%`、`拥有0/20`、`持有不低于1/15`。
    真正的变量名里没有数字——`当前SP` 是字母，`加速层数`、`载客数` 都不是数字。
    """
    if all(c.isdigit() for c in tok) or any(c.isdigit() for c in tok):
        return None
    last = None
    for m in _VERB.finditer(tok):
        last = m
    if last is not None:
        tok = tok[last.end():]
        tok = _PARTICLE.sub("", tok, count=1)
    if not tok or any(c.isdigit() for c in tok) or _VERB.search(tok):
        return None
    if tok in _PURE_ADVERB:
        return None
    return tok


#: 伤害类型词。`物理` / `法术` / `真实` / `元素` / `神经` 出现在斜杠两侧时，
#: 那个斜杠几乎一定是**并列**（`物理/法术伤害`、`来自正面的物理/法术伤害`），
#: 不是除法。左侧看**词尾**（左边常带一长串定语），右侧看词头。
_DMG_TAIL = re.compile(r"(?:物理|法术|真实|元素|神经)$")
_DMG_HEAD = re.compile(r"^(?:物理|法术|真实|元素|神经)")

#: 量词 / 单位字。`/` 右边整段都是这些字时，它是**单位后缀**不是除号
#: （`速度+0.25/秒`、`回复1/次`）。中文没有词间空格，除号与单位同形。
_UNIT_WORD = re.compile(r"^(?:秒|格|点|名|次|层|个|条|只|道|发|米|帧)+$")


#: 纯副词，不可能是变量。`(最多+6)` 这种要整条丢掉。
_PURE_ADVERB = frozenset({
    "最多", "最少", "至少", "至多", "不低于", "不超过", "则为", "其中",
    "以及", "如果", "若干", "一定", "全部", "所有", "自身", "对方",
})

#: 变量名前面残留的虚词：`降低至**已处理目标数量**`、`受到的**物理**`。
_PARTICLE = re.compile(r"^(?:至|的|后|中|内|时|为|了|再|并|且)+")


def _is_var(tok: str) -> bool:
    return _var_name(tok) is not None


#: 动作动词。变量名里不该出现——出现了就是散文被切出来的碎片。
_VERB = re.compile(
    r"提升|降低|提高|增加|减少|造成|受到|获得|变为|损失|回复|免疫|消耗"
    r"|进入|退出|释放|每秒|持续|立即|同时|分别|以及|或者|开始|结束|触发"
)


class _Parser:
    """算式递归下降。语法：

        expr := mul (('+' | '-') mul)*
        mul  := value (('×' | '*' | '/' | '÷') value)*
        value:= 数值['%'] | 变量 | '(' expr ')' ['%']
    """

    def __init__(self, toks: list[re.Match]) -> None:
        self.t = toks
        self.i = 0
        self.vars: list[str] = []
        self.ops = 0                # 消费掉的运算符个数——**至少 1 个才算算式**
        self.nums = 0               # 消费掉的数值个数——**至少 1 个才算算式**
        self.top = "mul"
        self.pct = False            # 见到过 `(…)%` 这种整体百分号
        self.lead = ""              # 最外层运算符的左操作数（若它是裸词）
        self.sign = ""
        self.depth = 0              # 括号嵌套深度；lead 只在最外层记

    def peek(self) -> re.Match | None:
        return self.t[self.i] if self.i < len(self.t) else None

    def take(self, kind: str) -> re.Match | None:
        m = self.peek()
        if m is not None and _kind(m) == kind:
            self.i += 1
            return m
        return None

    def expr(self) -> str | None:
        left = self.mul()
        if left is None:
            return None
        while True:
            m = self.peek()
            if m is None or _kind(m) != "op" or m.group(0) not in "+-＋－":
                break
            self.i += 1
            self.ops += 1
            right = self.mul()
            if right is None:
                return None
            sym = _OP_CANON.get(m.group(0), m.group(0))
            self._maybe_lead(left, sym)
            self.top = "add"
            left = f"{left}{sym}{right}"
        return left

    def mul(self) -> str | None:
        left = self.value()
        if left is None:
            return None
        while True:
            m = self.peek()
            if m is None or _kind(m) != "op" or m.group(0) not in "×*/÷":
                break
            self.i += 1
            self.ops += 1
            right = self.value()
            if right is None:
                return None
            if m.group(0) in "/÷" and _DMG_TAIL.search(left) and _DMG_HEAD.match(right):
                # 中文里的斜杠常常是**并列分隔符**：`物理/法术伤害-90%` 说的是
                # 「物理和法术伤害都降 90%」，不是「物理 ÷ 法术伤害」。
                # 两侧都是伤害类型词时一律不当除法——认错方向不如不收。
                return None
            if m.group(0) in "/÷" and _UNIT_WORD.match(right):
                # `/秒` `/格` `/次` 是**单位后缀**不是除号：`速度+0.25/秒`
                # 说的是「每秒 +0.25」，不是「速度 + 0.25 ÷ 秒」。
                # 中文没有词间空格，除号与单位同形，只能靠右边是不是量词判。
                # 误读的后果很隐蔽：算式算得出来、数值也像样，只是含义反了。
                return None
            sym = "×" if m.group(0) in "×*" else "/"
            self._maybe_lead(left, sym)
            left = f"{left}{sym}{right}"
        return left

    def _maybe_lead(self, left: str, sym: str) -> None:
        """把**最外层第一个**运算符的左操作数记成目标属性（若它是裸词）。

        `自身移动速度+(50%×加速层数)` → lead `自身移动速度`、sign `+`，
        算式本身是 `(50%×加速层数)`；`阻挡数×0` → lead `阻挡数`、sign `×`。
        这个词**常常**是属性名（该写进 attr），但也可能是算式里的一个因子
        （`当前移动速度×800` 是"以当前移速为系数算伤害"，不是"改移速"），
        **由调用方按 sign 判定**：`+`/`-` 基本就是属性，`×`/`/` 存疑。
        所以这里只如实记录，不把它从 `vars` 里摘掉。

        `depth > 0` 时一律不记：`(层数×300)` 里的 `层数` 是嵌套的，
        它是真变量，不是外层属性。
        """
        if self.lead or self.depth > 0 or not _BARE.match(left):
            return
        self.lead, self.sign = left, sym

    def value(self) -> str | None:
        m = self.peek()
        if m is None:
            return None
        k = _kind(m)
        if k == "num":
            self.i += 1
            self.nums += 1
            return f"{m.group('num')}{'%' if m.group('pct') else ''}"
        if k == "open":
            self.i += 1
            self.depth += 1
            inner = self.expr()
            self.depth -= 1
            if inner is None or self.take("close") is None:
                return None
            if self.take("bang") is not None:
                self.pct = True
            return f"({inner})"
        if k == "word":
            name = _var_name(m.group(0))
            if name is None:
                return None
            self.i += 1
            if name not in self.vars:
                self.vars.append(name)
            return name
        return None


def _parse_prefix(toks: list[re.Match]) -> tuple[Expr | None, int]:
    """解析 token 流的**最长有效前缀**，返回 `(Expr, 消费个数)`。

    用前缀而不是要求整段消费：句子里的算式后面往往还跟着别的词
    （`移动速度+(50%×加速层数)（增益数值…）`），要求整段就一条都收不到。
    """
    if not toks:
        return None, 0
    p = _Parser(toks)
    text = p.expr()
    # 四个必要条件：解析成功、消费了 token、**有运算符**、**有数值**、
    # 且**还有依赖**（变量或目标属性至少有一个）。
    # 「有数值」这条专门挡中文里的并列斜杠：`受到的物理/法术/真实伤害提升至`
    # 语法上是个除法链，可整句一个数字都没有——它不是算式，是散文。
    if text is None or p.i == 0 or p.ops == 0 or p.nums == 0:
        return None, 0
    if not p.vars and not p.lead:
        return None, 0
    return (Expr(text=text, vars=tuple(p.vars), op=p.top, pct=p.pct,
                 lead=p.lead, sign=p.sign), p.i)


def parse_arith(src: str) -> Expr | None:
    """把一整段文本当算式解析；不是合法算式（或没有变量、没有运算符）就返回 None。

    **要求整段被消费**——这是给「我知道这段就是算式」的调用方用的。
    要在句子里找算式请用 `find_exprs`（走的是最长前缀）。
    """
    toks = _tokens(src)
    if not toks:
        return None
    pos = 0
    for m in toks:
        if src[pos:m.start()].strip(" \u3000"):
            return None
        pos = m.end()
    if src[pos:].strip(" \u3000"):
        return None
    ex, n = _parse_prefix(toks)
    if ex is None or n != len(toks):
        return None
    return ex


#: 算式区段的分隔符：这些一出现，算式必然结束（算式不跨句）。
_SEG = re.compile(r"[，。；、：:,\n]")


def find_exprs(text: str) -> list[tuple[int, int, Expr]]:
    """扫出文本里所有带变量的算式，返回 `[(起, 止, Expr)]`。

    做法：先按标点分段，再在每段里找 **token 连续段**（中间有未覆盖的字符就断开），
    对每一段取最长有效前缀。三个必要条件缺一不可：**含变量、含运算符、括号配平**
    ——少了「含运算符」这条，`场上的啸叫音响被摧毁时` 这种裸名词会被当成算式。
    """
    out: list[tuple[int, int, Expr]] = []
    bounds = [0] + [m.end() for m in _SEG.finditer(text)] + [len(text)]
    for a, b in zip(bounds, bounds[1:]):
        chunk = text[a:b]
        cur: list[re.Match] = []
        pos = 0
        runs: list[list[re.Match]] = []
        for m in _tokens(chunk):
            if chunk[pos:m.start()].strip(" \u3000"):
                if cur:
                    runs.append(cur)
                cur = []
            cur.append(m)
            pos = m.end()
        if cur:
            runs.append(cur)
        for run in runs:
            # 收完一段**继续往下扫**，不要 break——同一句里常有两个算式
            # （`每秒受到(10×汲取体数量)的伤害与(25×汲取体数量)的损伤`），
            # 收一个就退出会静默丢掉后面所有。
            while run:
                ex, n = _parse_prefix(run)
                if ex is None:
                    run = run[1:]
                    continue
                out.append((a + run[0].start(), a + run[n - 1].end(), ex))
                run = run[n:]
    return out


def parse(text: str, blackboard: dict[str, Any] | None = None,
          *, rules: Iterable[Rule] | None = None,
          extra: Any = None) -> list[Term]:
    """把一条描述解析成公式项。`blackboard` 里的键值负责填系数。

    规则**按序消费文字区间**：命中过的片段不会被后面的规则重复抽取
    （否则「攻击力和防御力+18%」会被抽成两项）。

    `extra` 是一个可选的回调 `f(flat, used) -> list[Term]`，在规则跑完后调用，
    拿到**洗净文本**与**已被消费的区间表**。它的约定是：只处理与 `used` 不相交
    的文字，因此**只可能让结果变多**，不可能改坏已匹配的项。带变量的算式走这条路
    （见 `enemy_formula.expr_terms`）。
    """
    bb = blackboard or {}
    flat, slots = normalize(text)
    used: list[tuple[int, int]] = []
    out: list[Term] = []

    for rule in (rules if rules is not None else RULES):
        m = rule.compile().search(flat)
        if m is None:
            continue
        s, e = m.span()
        if any(s < ue and us < e for us, ue in used):
            continue
        used.append((s, e))

        ns = nums_in(m.group(0), slots, bb)
        # 片段里可能夹着与效果无关的数字：`发动一次{N}连击` 里的"一"、
        # `回复…一名单位相当于攻击力{N}%` 里的"一名"。这类规则声明 pick="last"，
        # 取片段里最后一个数值——它就贴在关键词旁边。
        if rule.pick == "last":
            ns = list(reversed(ns))
        dur = ns[rule.dur] if 0 <= rule.dur < len(ns) else None
        cnt = ns[rule.count] if 0 <= rule.count < len(ns) else None

        # `dtype` 可以写中文（规则里读得顺）、写 `=组名`（从文本取），
        # 也可以直接写枚举（`ELEMENT` 这类没有中文对应的）。
        if rule.dtype.startswith("="):
            dtype = _DT_BY_CN.get(_pick(m, rule.dtype), "")
        elif rule.dtype in _DT_BY_CN:
            dtype = _DT_BY_CN[rule.dtype]
        else:
            dtype = rule.dtype

        term = Term(
            kind=rule.kind,
            op=rule.op,
            dtype=dtype,
            attr=_pick(m, rule.attr),
            duration=dur,
            count=cnt,
            amount=ns[rule.scale] if 0 <= rule.scale < len(ns) else None,
            amount2=ns[rule.scale2] if 0 <= rule.scale2 < len(ns) else None,
            source=rule.name,
            evidence=re.sub(r"\s+", " ", flat[s:e])[:110],
            context=re.sub(r"\s+", " ", flat[max(0, s - 18):s])[-18:],
            keys=[n.key for n in ns if n.key],
            note=rule.note,
        )
        # 中文数字连击：「二连击」的数值在捕获组 `n` 里，不在 ns 里
        if rule.name == "count_lianji_cn":
            try:
                term.count = Num(value=CN_NUM.get(m.group("n"), None),
                                 literal=m.group("n"))
            except (IndexError, KeyError):
                pass
        term.expr = _expr(rule, ns)
        if rule.flag and not term.expr:
            term.expr = rule.flag
        term.pos = s
        suspect = [n.key for n in ns if n.suspect]
        if suspect:
            mark = "量纲存疑：" + "/".join(dict.fromkeys(suspect))
            term.note = f"{term.note}；{mark}" if term.note else mark
        out.append(term)

    if extra is not None:
        out.extend(extra(flat, used))

    out.sort(key=lambda t: t.pos)        # 按原文顺序，读起来与描述一致
    return out


def render(terms: list[Term]) -> list[str]:
    return [t.line() for t in terms]


def formulas(terms: list[Term], *, name: str = "") -> dict[str, str]:
    """把公式项归并成一组带名字的公式（伤害/治疗各占一条）。"""
    out: dict[str, str] = {}
    dmg = 0
    for t in terms:
        if t.kind == "damage":
            dmg += 1
            key = f"dmg{dmg if dmg > 1 else ''}"
            dt = DAMAGE_TYPE_CN.get(t.dtype, "")
            body = t.expr
            if t.count is not None and t.count.exists:
                body += f" × {t.count.text()}"
            out[key] = f"{body}" + (f"   [{dt}]" if dt else "")
        elif t.kind == "heal":
            out["heal"] = t.expr + "   [治疗]"
        elif t.kind == "regen":
            out["regen"] = t.expr
        elif t.kind in ("buff", "debuff", "control", "pen", "dodge", "shield",
                        "cost", "sp", "targets", "count", "range", "trait",
                        "flag", "prob"):
            base = t.attr or t.kind
            key = base
            n = 2
            while key in out:
                key = f"{base}{n}"
                n += 1
            out[key] = t.expr if t.expr else (t.count.text() if t.count else "—")
    return out


# ---------------------------------------------------------------- 语料与扫描

def load_corpus(db: Path | str) -> list[tuple[str, str, str, dict]]:
    """从本地库读全部描述语料，返回 [(来源, 标识, 文本, 黑板)]。"""
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows: list[tuple[str, str, str, dict]] = []
    try:
        for r in conn.execute(
                "SELECT skill_id, level, name, description, blackboard "
                "FROM skill_level WHERE description IS NOT NULL AND description<>''"):
            rows.append(("skill", f"{r['skill_id']}#L{r['level']}", r["description"],
                         _bb(r["blackboard"])))
        for r in conn.execute(
                "SELECT char_id, group_index, cand_index, description, blackboard "
                "FROM operator_talent WHERE description IS NOT NULL"):
            rows.append(("talent",
                         f"{r['char_id']}:G{r['group_index']}C{r['cand_index']}",
                         r["description"], _bb(r["blackboard"])))
        for r in conn.execute(
                "SELECT char_id, cand_index, override_description, blackboard "
                "FROM operator_trait WHERE override_description IS NOT NULL"):
            rows.append(("trait", f"{r['char_id']}:T{r['cand_index']}",
                         r["override_description"], _bb(r["blackboard"])))
        for r in conn.execute(
                "SELECT char_id, trait_text FROM operator WHERE trait_text IS NOT NULL"):
            rows.append(("trait_text", r["char_id"], r["trait_text"], {}))
        for r in conn.execute("SELECT module_id, parts FROM module_level"):
            for part in json.loads(r["parts"] or "[]"):
                for key in ("overrideTraitDataBundle", "addOrOverrideTalentDataBundle"):
                    bundle = part.get(key)
                    if not isinstance(bundle, dict):
                        continue
                    for cand in bundle.get("candidates") or []:
                        desc = (cand.get("additionalDescription")
                                or cand.get("overrideDescripton")
                                or cand.get("overrideDescription"))
                        if desc:
                            rows.append(("module",
                                         f"{r['module_id']}:{key}",
                                         desc, _bb(cand.get("blackboard"))))
    finally:
        conn.close()
    return rows


def _bb(raw: Any) -> dict[str, Any]:
    """黑板原文 → {键: 值}。三种形态都要认：

    * `dict` —— gamedata 里直接是字典；
    * `str`  —— **从 SQLite 读出来是 JSON 字符串**，可能是字典也可能是列表；
    * `list` —— gamedata 里是 `[{key, value}]`，模块改写里也是。
    """
    if raw is None:
        return {}
    if isinstance(raw, str):
        try:
            raw = json.loads(raw or "{}")
        except ValueError:
            return {}
    if isinstance(raw, dict):
        return raw
    out: dict[str, Any] = {}
    for item in raw or []:
        if isinstance(item, dict) and item.get("key") is not None:
            out[item["key"]] = item.get("value")
    return out


def scan(db: Path | str, *, top: int = 25) -> dict[str, Any]:
    """扫全库：规则覆盖率 + **未命中的高频残句**（用来继续加规则）。"""
    corpus = load_corpus(db)
    by_source: dict[str, list[int]] = {}
    unmatched: Counter[str] = Counter()
    terms_total = 0

    for src, _key, text, bb in corpus:
        got = parse(text, bb)
        terms_total += len(got)
        stat = by_source.setdefault(src, [0, 0])
        stat[0] += 1
        if got:
            stat[1] += 1
        else:
            clean = TAG_RE.sub("", text)
            if len(clean) >= 10:            # 太短的只是提示文字
                unmatched[_skeleton(clean)] += 1

    total = len(corpus)
    parsed = sum(v[1] for v in by_source.values())
    return {
        "total": total,
        "parsed": parsed,
        "ratio": parsed / total if total else 0.0,
        "terms": terms_total,
        "by_source": {k: {"total": v[0], "parsed": v[1]} for k, v in by_source.items()},
        "unmatched": unmatched.most_common(top),
    }


def _skeleton(text: str) -> str:
    """残句骨架：去数字、压空白，便于归并同类。"""
    s = re.sub(r"\d+(?:\.\d+)?", "#", text)
    return re.sub(r"\s+", " ", s)[:46]


def describe_row(db: Path | str, key: str) -> list[dict[str, Any]]:
    """查一个技能或干员的描述与解析结果。`key` 可为技能 id 或干员 id。"""
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    out: list[dict[str, Any]] = []
    try:
        rows = list(conn.execute(
            "SELECT skill_id, level, name, description, blackboard FROM skill_level "
            "WHERE skill_id = ? ORDER BY level", (key,)))
        for r in rows:
            out.append({"kind": "skill", "id": r["skill_id"], "level": r["level"],
                        "name": r["name"], "text": r["description"],
                        "terms": parse(r["description"], _bb(r["blackboard"]))})
        if not rows:
            for r in conn.execute(
                    "SELECT group_index, cand_index, name, description, blackboard "
                    "FROM operator_talent WHERE char_id = ?", (key,)):
                out.append({"kind": "talent", "name": r["name"],
                            "id": f"{key}:G{r['group_index']}C{r['cand_index']}",
                            "text": r["description"],
                            "terms": parse(r["description"], _bb(r["blackboard"]))})
    finally:
        conn.close()
    return out


# ==================================================================== 结算层
#
# 上面是「描述 → 公式项」。这一层把公式项折叠成**战斗能直接读的数**，
# 并提供与黑板路径的逐字段比对。设计上的两条硬约束：
#
#   1. **黑板是引擎真值，描述是给人读的。** 二者冲突时默认听黑板的；
#      描述只补黑板的**空缺**（`merge`）。要强制走描述用 `desc`，
#      要回到旧行为用 `blackboard`。
#   2. **不确定就不写。** 描述里判不出量纲的数值（`Num.suspect`）一律不进
#      结算字段，只记进 `suspect` 供人看——宁可少算，不可算错。


@dataclass
class FormulaEffects:
    """描述推出的效果读数。字段名与 `SkillEffects` 对齐，便于互比与合并。"""

    atk_scale: float | None = None      # 这一击的攻击力倍率（2.1 = 210%）
    #: `max(目标当前生命 X%, 自身攻击力 Y%)` 的两个系数；不是倍率本身
    max_of: tuple[float | None, float | None] | None = None
    hit_count: int | None = None        # 一次攻击打几下
    #: 连击的**作用域**：`attack` = 改的是干员自己的平A（可以并进结算）；
    #: `skill` = 那是技能自己的一次性范围多段，平A不该跟着变。
    #: 这一条是必须分的：全库 49 条"描述独有的连击"里两类混在一起，
    #: 「每次攻击对最多4名敌人造成3次…」（赤刃技3，该并）与
    #: 「对范围内的所有敌人造成2次…」（德克萨斯技2，不该并）写法几乎一样。
    hit_scope: str = ""
    max_target: int | None = None       # 一次打几个目标
    heal_scale: float | None = None     # 治疗倍率
    true_damage: bool = False           # 描述里写明"真实伤害"
    damage_type: str = ""               # PHYSICAL / ARTS / TRUE / ELEMENT
    #: 元素损伤相关：`{"凋亡": 0.15, "神经": 0.15}`，值是**倍率**（攻击力的比例）
    ep_damage: dict[str, float] = field(default_factory=dict)
    #: 爆发期追加伤害：`{"凋亡": 0.5}`
    ep_burst: dict[str, float] = field(default_factory=dict)
    #: 损伤回复倍率（元素医疗）
    ep_heal: float | None = None
    #: 打在自己身上的控制：`{"眩晕": 10.0}`
    self_control: dict[str, float] = field(default_factory=dict)
    #: 打在敌人身上的控制
    enemy_control: dict[str, float] = field(default_factory=dict)
    #: 逐字段的解释（写进战报，便于溯源）
    sources: dict[str, str] = field(default_factory=dict)
    #: 因为量纲判不出来而**没有**采信的键
    suspect: list[str] = field(default_factory=list)
    terms: list[Term] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.terms

    def get(self, name: str, default=None):
        return getattr(self, name, default)


def _hit_scope_of(t: Term) -> str:
    """这段连击说的是"平A变成多段"还是"技能自己的一次性多段"？

    判据是**命中位置之前的上下文**（`Term.context`）：

    * 出现「每次攻击」——那是改写平A（赤刃技3），可以并进结算；
    * 出现「范围内/对所有/周围/至多 N 名」——那是一次性范围多段
      （德克萨斯技2「对范围内的所有敌人造成2次…」），**平A不该跟着变**；
    * `发动…连击`、`每次攻击变为…` 这两条规则的语义本来就是平A。
    """
    if t.source in ("mult_lianji", "count_lianji_launch", "count_lianji_cn",
                    "count_continuos", "count_per_target"):
        return "attack"
    if "每次攻击" in t.context or "攻击变为" in t.context:
        return "attack"
    for marker in ("范围内", "对所有", "周围", "敌人所在"):
        if marker in t.context:
            return "skill"
    return "unknown"


def _ratio_of(num: Num | None) -> float | None:
    """把一个数值归成**倍率**（2.1 表示 210%）。

    `PCT`（文面 210%）要除 100，`RATIO`（黑板 2.1）原样，
    `FLAT` 就按原值当倍率用（`{atk_scale}` 没有说明符时确实是 2.1 这种写法），
    `UNKNOWN` 一律丢弃——宁可少算。
    """
    if num is None or num.value is None:
        return None
    if num.suspect:
        return None
    if num.pct:
        return float(num.value) / 100.0
    return float(num.value)


def _flat_of(num: Num | None) -> float | None:
    if num is None or num.value is None or num.suspect:
        return None
    if num.pct:                     # 文面写了 % 就不可能是个数
        return None
    return float(num.value)


def effects_from_terms(terms: list[Term]) -> FormulaEffects:
    """把公式项折叠成结算读数。同名冲突时**先出现的赢**（规则表内顺序即优先级）。"""
    out = FormulaEffects(terms=list(terms))

    def note(field: str, t: Term) -> None:
        out.sources.setdefault(field, f"{t.source}：{t.evidence[:60]}")

    def set_hits(t: Term, n: int) -> None:
        """记下连击数与它的作用域（见 `hit_scope`）。"""
        if out.hit_count is not None:
            return
        out.hit_count = n
        scope = _hit_scope_of(t)
        out.hit_scope = scope
        note("hit_count", t)

    for t in terms:
        if t.amount is not None and t.amount.suspect and t.amount.key:
            if t.amount.key not in out.suspect:
                out.suspect.append(t.amount.key)

        if t.kind == "damage":
            if t.dtype:
                out.damage_type = out.damage_type or t.dtype
            if t.source == "damage_max_of":
                # `max(目标当前生命 X%, 自身攻击力 Y%)`：**两个都不是这一击的
                # 倍率**——真正要算的是二者的较大值。把 X%（6%）当成倍率会严重
                # 低估，把 Y%（580%）当成倍率会严重高估，所以单独记。
                out.max_of = (_ratio_of(t.amount), _ratio_of(t.amount2))
                note("max_of", t)
                continue
            v = _ratio_of(t.amount)
            if v is not None and out.atk_scale is None:
                out.atk_scale = v
                note("atk_scale", t)
            if t.count is not None:
                n = _flat_of(t.count)
                if n:
                    set_hits(t, int(n))
            if t.dtype == "TRUE":
                out.true_damage = True

        elif t.kind == "count":
            n = _flat_of(t.count) or _flat_of(t.amount)
            if n:
                set_hits(t, int(n))

        elif t.kind == "targets" and t.op == "enemy":
            n = _flat_of(t.count)
            if n and out.max_target is None:
                out.max_target = int(n)
                note("max_target", t)

        elif t.kind in ("heal", "regen"):
            v = _ratio_of(t.amount)
            if v is not None and out.heal_scale is None:
                out.heal_scale = v
                note("heal_scale", t)

        elif t.kind == "ep_damage":
            v = _ratio_of(t.amount)
            if v is not None:
                out.ep_damage.setdefault(t.attr or out.damage_type or "元素", v)
                note("ep_damage", t)

        elif t.kind == "ep_burst":
            v = _ratio_of(t.amount)
            if v is not None:
                out.ep_burst.setdefault(t.attr or "元素", v)
                note("ep_burst", t)

        elif t.kind == "ep_heal":
            v = _ratio_of(t.amount)
            if v is not None and out.ep_heal is None:
                out.ep_heal = v
                note("ep_heal", t)

        elif t.kind == "control" and t.duration is not None:
            secs = _flat_of(t.duration)
            if secs is None:
                continue
            target = out.self_control if t.op in ("self", "ally") else out.enemy_control
            target.setdefault(t.attr or "控制", secs)
            note("control", t)

    return out


#: 逐字段比对的字段表：`(字段名, 判等容差)`
_COMPARE_FIELDS = (
    ("atk_scale", 1e-6),
    ("hit_count", 0),
    ("max_target", 0),
    ("heal_scale", 1e-6),
    ("true_damage", 0),
)


@dataclass
class Difference:
    """一处"黑板说 A、描述说 B"的分歧。"""

    field: str
    blackboard: Any
    description: Any
    verdict: str            # agree / only_blackboard / only_desc / conflict

    def line(self) -> str:
        return (f"{self.field:<14} 黑板={self.blackboard!r:<10} "
                f"描述={self.description!r:<10} {self.verdict}")


def _bb_field(eff, name: str):
    """从 `SkillEffects` 读一个比对字段，**只认黑板里显式存在的键**。

    这一条是踩出来的：`SkillEffects.atk_scale` 在没有黑板键时返回默认值 1.0，
    直接拿来比对，会把「黑板根本没写倍率、描述写了 210%」报成 **conflict**——
    而它其实是描述独有的收获（`only_desc`）。全库 911 行里这样误报 46 处。
    所以这里一律读**原始字典**，缺键就是 `None`。
    """
    if eff is None:
        return None
    if name == "true_damage":
        return bool(eff.true_damage)
    if name == "hit_count":
        n = eff.damage.get("times")
        return int(n) if n else None
    if name == "max_target":
        n = eff.damage.get("max_target")
        return int(n) if n else None
    if name == "atk_scale":
        v = eff.damage.get("atk_scale")
        return float(v) if v is not None else None
    if name == "heal_scale":
        v = eff.damage.get("heal_scale")
        return float(v) if v is not None else None
    return eff.get(name) if hasattr(eff, "get") else None


def compare_effects(bb_effects, desc: FormulaEffects) -> list[Difference]:
    """逐字段比对黑板路径与描述路径。**不改任何东西**，只报告分歧。

    `only_desc` 是**描述独有的收获**（黑板根本没有这个字段），
    `only_blackboard` 是描述没解析出来的部分（多半是文案写法没覆盖），
    `conflict` 才是真分歧——需要人看，通常说明其中一边读错了。
    """
    out: list[Difference] = []
    for name, tol in _COMPARE_FIELDS:
        a = _bb_field(bb_effects, name)
        b = desc.get(name)
        if name == "true_damage":
            a = bool(a)
            b = None if not desc.terms else bool(b)
        if isinstance(b, dict):
            continue
        if a is None and b is None:
            continue
        if a is None:
            verdict = "only_desc"
        elif b is None:
            verdict = "only_blackboard"
        elif isinstance(a, bool) or isinstance(b, bool):
            verdict = "agree" if bool(a) == bool(b) else "conflict"
        else:
            verdict = "agree" if abs(float(a) - float(b)) <= tol else "conflict"
        out.append(Difference(name, a, b, verdict))
    return out


def merge_effects(bb_effects, desc: FormulaEffects, *, policy: str = "merge"):
    """把描述路径并进黑板路径。返回 `(合并后的 SkillEffects, 分歧列表)`。

    * `blackboard` —— 原样返回黑板结果（旧行为）。
    * `merge`（默认）—— 黑板为底，**只补它没有的**：
      连击数（描述写了"造成 N 次"而黑板没 `times`）、治疗倍率、
      真实伤害、元素损伤；
    * `desc` —— 描述写了的就按描述改（用于敏感性与对照）。

    返回的对象是**副本**，不会改到调用方手里的 `SkillEffects`。
    """
    diffs = compare_effects(bb_effects, desc)
    if policy not in ("blackboard", "merge", "desc"):
        raise ValueError(f"policy 只能是 blackboard/merge/desc，收到 {policy!r}")
    if policy == "blackboard" or bb_effects is None:
        return bb_effects, diffs

    import copy as _copy

    out = _copy.deepcopy(bb_effects)
    fill = policy == "merge"        # merge 只填空缺，desc 无条件覆盖

    if desc.true_damage and (fill or not out.true_damage):
        out.true_damage = True

    if desc.atk_scale is not None:
        cur = out.damage.get("atk_scale")
        if cur is None or not fill:
            out.damage["atk_scale"] = desc.atk_scale

    if desc.hit_count and desc.hit_count > 1:
        # 注意要写进 `times` 而不是只写 `repeat_hits`：`SkillEffects.hit_count`
        # 的读取顺序是 `times` → `repeat_hits`，只写后者会被黑板里已有的
        # `times` 盖掉，改了等于没改。
        #
        # 而且**只有改的是平A才并**：技能自己的一次性范围多段（德克萨斯技2
        # 「对范围内的所有敌人造成2次…」）并进来会把平A也翻倍，那是假的。
        if desc.hit_scope == "attack" and (desc.hit_count > out.hit_count or not fill):
            out.repeat_hits = desc.hit_count
            out.damage["times"] = float(desc.hit_count)

    if desc.max_target and desc.max_target > 1:
        if desc.max_target > out.max_target or not fill:
            out.damage["max_target"] = desc.max_target

    if desc.heal_scale is not None:
        if out.damage.get("heal_scale") is None or not fill:
            out.damage["heal_scale"] = desc.heal_scale

    # 元素损伤：黑板路径**完全没有**这条轴，描述给了就有
    for name, value in desc.ep_damage.items():
        out.other.setdefault(f"ep_damage@{name}", value)
    for name, value in desc.ep_burst.items():
        out.other.setdefault(f"ep_burst@{name}", value)
    if desc.ep_heal is not None:
        out.other.setdefault("ep_heal", desc.ep_heal)

    return out, diffs

