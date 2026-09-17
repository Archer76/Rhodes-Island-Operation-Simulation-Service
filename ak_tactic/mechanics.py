"""地图机制：语料获取 + 正文格式化。

为什么单独一层
--------------
干员正文在 gamedata、敌人正文在 prts.wiki，两者已各有编译器
（`formula.py` / `enemy_formula.py`）。地图机制是**第三种语料**，每个活动/章节
都会引入新的一批，所以既要能取回来，也要能像另外两层那样形式化：:

    prts.wiki wikitext --detemplate--> 纯文本 --formula.parse--> Term

【三个事实来源，必须能分辨】
1. **全局术语表**：prts.wiki 的「特殊机制」页，87 条、分 9 节
   （单位类型／阵营／职业／额外术语／战场效果／引擎机制／伤害机制／复用机制／
   特殊计算方式）。条目形如 ``{{特殊机制表格|名称|说明|备注|图标}}``。
   ⚠ 说明正文里**嵌着同层模板与 `|`**（``{{特殊机制|伤害相性（P3R）}}``），
   所以①切参数要按嵌套深度、②找模板结尾要按花括号配平——用非贪婪正则
   收到第一个 ``}}`` 会在嵌套模板处提前截断（见 `_iter_templates`）。
2. **单关实数**：写在关卡页的「特殊地形效果」「关卡描述」「情报」字段里。
   怀黍离已实证：HS-8 页的「每秒受到20+病害值×3法术环境伤害」与关卡 JSON
   ``runes[key=env_system_new]`` 的 basic_damage=20 / damage_ratio=3 逐项吻合。
3. **gamedata 侧**：``runes[].blackboard``（数值住 `value`，见
   `ak_tactic.gamedata.stage`）、``predefines.tokenInsts``、``environmentSe``。

本模块只负责**取回来并整理成可编译的文本**，不臆造数值；某一项到底出自哪一条
来源，由 `Mechanic.origin` 与 `StageMechanics.fields` 标明。

【与另两层共用纪律】
* 规则**顺序即优先级**，命中即消费区间；干员规则在前、敌人规则居中、
  机制新词在最后（粗粒度规则不得抢在细粒度之前把系数吃掉）。
* 量纲、带变量的算式、`detemplate` 全部复用，不另写一套。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Iterator

from .prts.wikitext import parse_params          # noqa: F401  (对外复用)
from .enemy_formula import detemplate, expr_terms, ENEMY_RULES
from . import formula as _formula
from .formula import N, Rule, Term, _r

__all__ = [
    "GLOSSARY_PAGE",
    "SECTIONS",
    "Mechanic",
    "StageMechanics",
    "STAGE_FIELDS",
    "split_args",
    "ref_name",
    "parse_glossary",
    "fetch_glossary",
    "parse_stage_fields",
    "stage_mechanics",
    "MECHANIC_RULES",
    "RULES_MECHANIC",
    "parse_mechanic",
    "mechanic_terms",
    "scan_glossary",
]

#: 全局术语表所在页面。
GLOSSARY_PAGE = "特殊机制"

#: 术语表的九个节，按页面出现顺序。用于自检"节没漏"。
SECTIONS: tuple[str, ...] = (
    "单位类型", "阵营", "职业", "额外术语", "战场效果",
    "引擎机制", "伤害机制", "复用机制", "特殊计算方式",
)

#: 关卡页里承载机制正文的字段（按可读性排序）。
STAGE_FIELDS: tuple[str, ...] = ("特殊地形效果", "关卡描述", "情报", "附加条件")


# ================================================================ 一、解析 wikitext

def split_args(inner: str) -> list[str]:
    """按**嵌套深度**切模板参数：只有第 0 层的 `|` 才是分隔符。

    `{{异常效果|晕眩|免疫}}` 里的 `|` 属于内层模板，裸 `str.split("|")`
    会把它算成本条目的字段，于是「说明」被切碎、后面几栏整体错位。
    """
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    k = 0
    while k < len(inner):
        two = inner[k:k + 2]
        if two in ("{{", "[["):
            depth += 1
            buf.append(two)
            k += 2
            continue
        if two in ("}}", "]]"):
            depth -= 1
            buf.append(two)
            k += 2
            continue
        if inner[k] == "|" and depth == 0:
            out.append("".join(buf))
            buf = []
            k += 1
            continue
        buf.append(inner[k])
        k += 1
    out.append("".join(buf))
    return out


def _iter_templates(text: str, name: str) -> Iterator[tuple[int, str]]:
    """产出 ``{{name|…}}`` 的 **(起始位置, 参数部分)**，按花括号配平收尾。

    ⚠ 这里**不能**用非贪婪正则 ``\\{\\{name\\|(.*?)\\}\\}``：说明正文里嵌着
    同层模板，非贪婪会在嵌套模板的 ``}}`` 处提前截断，把后半句丢掉，
    而截出来的前半句看着完全正常（本项目记录在案的那类静默错误）。
    """
    head = "{{" + name
    i = 0
    while True:
        s = text.find(head, i)
        if s < 0:
            return
        k = s + 2
        depth = 1
        while k < len(text) and depth:
            if text.startswith("{{", k):
                depth += 1
                k += 2
            elif text.startswith("}}", k):
                depth -= 1
                k += 2
            else:
                k += 1
        if depth:                       # 花括号不配平，放弃
            return
        body = text[s + 2 + len(name): k - 2]
        yield s, body[1:] if body.startswith("|") else body
        i = k


_HEADER = re.compile(r"^(={2,})\s*([^=\n]+?)\s*\1\s*$", re.M)


def _section_at(text: str, pos: int) -> str:
    """`pos` 之前的最后一个小节路径，形如 `战场效果` 或 `常用的基础机制/阵营`。"""
    path: list[str] = []
    for m in _HEADER.finditer(text, 0, pos):
        # 真页面把 `===` 当作**顶层**节（`==` 是页面标题级），其 `====` 才是子节。
        # 故取 `max(0, 层数 - 3)` 作嵌套深度——写成 `层数 - 2` 时 `==` 会算出负深度，
        # `while len(path) > depth` 变成永真、当场 pop 空列表。
        depth = max(0, len(m.group(1)) - 3)
        while len(path) > depth:
            path.pop()
        path.append(m.group(2).strip())
    return "/".join(path)


@dataclass(frozen=True)
class Mechanic:
    """术语表里的一条机制。"""

    name: str
    section: str
    body: str                       # 原始 wikitext（未展开）
    note: str = ""                  # 站方备注
    icons: tuple[str, ...] = ()
    origin: str = GLOSSARY_PAGE     # 事实来源，永远是页面名，便于溯源

    @property
    def text(self) -> str:
        """展开模板后的纯文本正文——喂给规则扫描的就是它。"""
        return detemplate(self.body)

    @property
    def note_text(self) -> str:
        return detemplate(self.note) if self.note else ""


def parse_glossary(text: str) -> list[Mechanic]:
    """把「特殊机制」页的 wikitext 解析成机制列表（保持页面顺序）。"""
    out: list[Mechanic] = []
    for pos, inner in _iter_templates(text, "特殊机制表格"):
        args = split_args(inner)
        if not args or not args[0].strip():
            continue
        name = detemplate(args[0]).strip()
        body = args[1].strip() if len(args) > 1 else ""
        note = args[2].strip() if len(args) > 2 else ""
        icons = tuple(a.strip() for a in args[3:] if a.strip())
        out.append(Mechanic(name=name, section=_section_at(text, pos),
                            body=body, note=note, icons=icons))
    return out


def fetch_glossary(client: Any = None) -> list[Mechanic]:
    """从 prts.wiki 取回术语表（走 `PrtsClient` 的缓存与限速）。"""
    if client is None:
        from .prts import PrtsClient
        client = PrtsClient()
    return parse_glossary(client.wikitext(GLOSSARY_PAGE))


# ================================================================ 二、关卡页的机制字段

@dataclass(frozen=True)
class StageMechanics:
    """一个关卡页上承载机制的那几个字段。"""

    title: str
    fields: dict[str, str] = field(default_factory=dict)   # 字段名 -> 原始 wikitext
    refs: tuple[str, ...] = ()      # 正文引用到的机制名（{{特殊机制|X}}）

    @property
    def texts(self) -> dict[str, str]:
        return {k: detemplate(v) for k, v in self.fields.items()}

    def plain(self) -> str:
        return "\n".join(self.texts.values())


#: `{{特殊机制|…}}` 的**全部**顶层参数（不只是第一个）。取整串是因为
#: 第一个参数**可能是命名参数**：
#: `{{特殊机制|名称=病害|病害值|color=yellowgreen}}`（怀黍离活动页原文）——
#: 这里的机制名是第 0 个**位置**参数「病害值」，而「名称=病害」只是显示用的
#: 标签。原先只取第一个参数，会把机制名读成 `名称=病害`：既不匹配术语表，
#: 也把"这条正文引用了哪个机制"整个搞错。
_REF_RE = re.compile(r"\{\{\s*特殊机制\s*\|([^|{}]+(?:\|[^|{}]+)*)")


def ref_name(args: str) -> str:
    """从 `{{特殊机制|…}}` 的参数串里取出**机制名**。

    规则：跳过命名参数（含 `=`），取第一个位置参数。全为命名参数时返回空串。
    例：`名称=病害|病害值|color=yellowgreen` → `病害值`；
        `敌方单位|名称=敌方` → `敌方单位`（`名称` 只是显示标签）；
        `附着：` → `附着：`（页面上确实这么写，名字带冒号，交由调用方处理）。

    ⚠ **页面上的写法与术语表的名字并不总是一一对应**，将来若要写"引用 → 条目"
    的解析器，下面三类都得先处理（2026-09-17 全量缓存页扫描的结果）：

    * **合并条目**：页面按单个属性引用 `{{特殊机制|明}}` / `{{特殊机制|晦}}`，
      表里却只有一条「**明晦属性**」（引用得最多的表外名就是这两个）。
    * **带标点**：`{{特殊机制|附着：}}`（带全角冒号）↔ 表里的「附着」。
    * **子名**：`{{特殊机制|弱点（P3R）}}` / `{{特殊机制|免疫（P3R）}}` ↔
      表里的「伤害相性（P3R）」——前两者是后者的两种取值，本身**不是**条目。
      我自己取的敌人「死志的凝结」正文里就是这么引用的。

    现在不做归一化：这几类名字目前只用于 CLI 展示，没有消费者按它查表；
    真做归一化时得连带决定"一个引用能不能对上多条"，不该在这里悄悄定。
    """
    for part in args.split("|"):
        p = part.strip()
        if p and "=" not in p:
            return p
    return ""


def parse_stage_fields(text: str) -> dict[str, str]:
    """从关卡页 wikitext 里取出机制相关字段（按嵌套深度切参数）。"""
    out: dict[str, str] = {}
    for _pos, inner in _iter_templates(text, "关卡信息"):
        for arg in split_args(inner):
            if "=" not in arg:
                continue
            k, v = arg.split("=", 1)
            k = k.strip()
            if k in STAGE_FIELDS and v.strip():
                out.setdefault(k, v.strip())
    if out:
        return out
    # 有些关卡页不用 {{关卡信息}}，字段直接平铺在正文里
    for k in STAGE_FIELDS:
        m = re.search(rf"^\s*\|\s*{k}\s*=(.+)$", text, re.M)
        if m and m.group(1).strip():
            out[k] = m.group(1).strip()
    return out


def parse_stage_mechanics(title: str, text: str) -> StageMechanics:
    fields = parse_stage_fields(text)
    refs: list[str] = []
    for v in fields.values():
        for m in _REF_RE.finditer(v):
            n = ref_name(m.group(1))
            if n and n not in refs:
                refs.append(n)
    return StageMechanics(title=title, fields=fields, refs=tuple(refs))


def stage_mechanics(title: str, client: Any = None) -> StageMechanics:
    """按关卡页标题取回其机制字段（标题形如 `HS-8 种因`）。"""
    if client is None:
        from .prts import PrtsClient
        client = PrtsClient()
    return parse_stage_mechanics(title, client.wikitext(title))


# ================================================================ 三、格式化

_MECH_LABELS = {
    "mech_ignore": "无视",
    "mech_immune": "免疫",
    "mech_env": "环境",
}
_formula._LABEL.update(_MECH_LABELS)

#: 机制自带的新词汇。**排在干员与敌人规则之前**——顺序即优先级。
#:
#: 口径：机制的效果来源是**关卡**而非任何单位，故 `op="area"`；
#: 落到谁身上由正文的主语写明（「我方单位」「敌方地面单位」）。
#:
#: ⚠ 规则一律锚**正文里的原话**，绝不锚条目名：条目名常常不在正文中出现
#: （「停顿免疫」的正文里压根没有「免疫」二字，它写的是「使停顿无法生效」）。
#: 按名字写规则会得到一条永不命中的死规则——而它看着非常合理。
MECHANIC_RULES: tuple[Rule, ...] = (
    # ---------------------------------------------------- 环境伤害 / 回复
    #
    # 怀黍离田地/病害的原始措辞，逐字取自 HS-8 与 HS-EX-8 关卡页：
    #   「位于病害值>0低地的我方单位，每秒受到20+病害值×3法术环境伤害」
    #   「我方单位部署于位于病害值>0的低地时，立刻受到100+病害值×9的法术环境伤害」
    # 两处都是「基础值 + 系数×变量」的**加法**，把 `20+病害值×3` 当常数取会得到
    # 看着对、其实错的表达式，所以这里只锚尾巴，数值形状交给算式通道。
    #
    # ⚠ **两个来源的词序不一样，两条都要有**：
    #   关卡页（HS-8 / HS-EX-8）写「法术**环境伤害**」——伤害类型在前；
    #   术语表「病害值」条目写「**环境法术伤害**」——环境在前。
    # 只写一条会得到一条永不命中的死规则（本模块第一次提交就是这样，
    # 而它看着毫无问题）。两条规则的 flag 相同，产出可归并。
    _r("mech_env_damage",
       r"(?P<dt>物理|法术|真实|元素)环境伤害",
       "damage", op="area", dtype="=dt", source="ENV", form="word",
       note="环境伤害：来源是关卡而非任何单位（关卡页词序）"),
    _r("mech_env_damage_alt",
       r"环境(?P<dt>物理|法术|真实|元素)伤害",
       "damage", op="area", dtype="=dt", source="ENV", form="word",
       note="环境伤害：来源是关卡而非任何单位（术语表词序）"),
    _r("mech_env_regen",
       rf"每秒(?:恢复|回复)(?P<amt>{N}){{PCT}}(?:点)?(?:的)?生命值",
       "heal", op="area", dtype="HEAL", source="ENV", scale=0, form="flat",
       note="清水田地对我方单位的每秒回复"),

    # ---------------------------------------------------- 无数值的效果标记
    _r("mech_ignore_dodge",
       r"无视(?P<dt>物理|法术)?闪避",
       "mech_ignore", dtype="=dt", form="word", flag="无视闪避",
       note="该次伤害跳过目标的闪避判定（概率直接降至 0，不做判定）"),
    _r("mech_uncancellable",
       r"反制该次取消",
       "mech_ignore", form="word", flag="无法被取消",
       note="闪避/格挡/未命中只能触发判定，无法真正取消这次伤害"),
    _r("mech_unchangeable",
       r"此伤害不可被改变",
       "mech_ignore", form="word", flag="不可改变",
       note="任何伤害倍率增减（脆弱、庇护、归零）都改不动它"),
    _r("mech_undying",
       r"阻止当次生命归0",
       "mech_ignore", form="word", flag="免死",
       note="受到致命伤害时阻止生命归零；多个免死按优先级单次最多触发一个"),
    _r("mech_no_heavy_wound",
       r"无法被施加重伤",
       "mech_immune", form="word", flag="不可重伤"),
    _r("mech_disable_stun",
       r"使停顿无法生效",
       "mech_immune", form="word", flag="停顿免疫",
       note="持有一个同名可叠加的占位 Buff 覆盖停顿，而非真的免疫"),
    _r("mech_no_alert",
       r"不扣除关卡生命值[，,]?不触发警报",
       "flag", form="word", flag="无害目标",
       note="到达路径终点时不扣关卡生命值、不触发警报"),

    # ---------------------------------------------------- 带数值的机制
    _r("mech_minghui_same",
       rf"对同属性的单位造成伤害时[^。]{{0,16}}?攻击力倍率降低至(?P<amt>{N}){{PCT}}",
       "debuff", attr="atk", source="ATK", scale=0, form="flat",
       note="明晦属性：对同属性目标造成伤害时的攻击力倍率"),
    _r("mech_minghui_diff",
       rf"对异属性的单位造成伤害时[^。]{{0,16}}?攻击力倍率提高至(?P<amt>{N}){{PCT}}",
       "buff", attr="atk", source="ATK", scale=0, form="flat",
       note="明晦属性：对异属性目标造成伤害时的攻击力倍率"),
    _r("mech_hp_floor",
       rf"令生命值只降低(?P<amt>{N})点",
       "damage", op="enemy", source="FLAT", scale=0, form="flat",
       note="特殊生命值机制：不论伤害多少，生命值只降这一点（不影响伤害本身）"),
    _r("mech_engage_radius",
       rf"进入自身(?P<amt>{N})半径范围",
       "range", op="self", source="GRID", scale=0, form="flat",
       note="交战：按半径做碰撞判定，不影响攻击索敌"),
)

#: 机制语料的规则表。机制词在前（锚点独特），干员规则居中，敌人规则在最后。
RULES_MECHANIC: tuple[Rule, ...] = (
    MECHANIC_RULES + tuple(_formula.RULES) + tuple(ENEMY_RULES)
)

#: **本就不该编译出公式项**的条目——定义与计算方式说明，不是效果。
#:
#: 这几节在覆盖率里低是**对的**，与敌人侧 `desc` 只该到 55% 是同一回事：
#: 「阵营为我方的单位」是在定义术语，不是在描述一个可结算的效果。
#: 自检里有一条断言它们**仍然**编不出东西——防止日后有人"顺手"让它们命中。
#:
#: ⚠ 名单**必须逐条读过正文再写**，不能按名字猜。第一版凭名字往里放了
#: 「角色类单位」与「可空降」，实际两条都有可结算的效果（前者带地形改造、
#: 后者是召唤/空降落点）——按名字猜会把真效果划成"不该编译"，
#: 而自检只会照着这份名单断言，于是错误被自己的守卫背了书。
NON_EFFECT_NAMES: frozenset[str] = frozenset({
    # 单位类型 / 阵营 / 职业：纯粹的术语定义
    "敌人类单位", "我方单位", "敌方单位", "中立单位",
    "无职业", "干员",
    # 特殊计算方式：说明"距离怎么算"，不是某个单位的效果
    "曼哈顿距离", "切比雪夫距离", "“无限远”",
    # 额外术语里的纯定义
    "切换模式", "载客", "锁定在待部署区中", "封印在待部署区中",
    "失衡移动阻尼", "动态持续时间",
})

#: **已知误读**：条目确实是定义、本不该编译，但当前会被**同一条敌人规则**咬走，
#: 产出「看着对、其实错」的项。记在这里而不是塞进 `NON_EFFECT_NAMES`——
#: 后者断言的是"编不出东西"，这两条编得出，硬塞进去会让守卫自己骗自己。
#:
#: 两类错误的区别很要紧：*编不出来*是漏，*编错了*是错，错比漏糟。
#: 自检里有一条盯着它们**仍在被误读**；哪天有人把规则收紧了，那条会红，
#: 红了就把它从这里删掉、移进 `NON_EFFECT_NAMES`。
KNOWN_MISPARSE: dict[str, str] = {
    "角色类单位":
        "定义条目。正文「以地图格为单位部署或初始放置在场上」被 e_place 的「放置」"
        "咬走，产出「放置物/地形改造」——原文没有这层意思。",
    "可空降":
        "定义条目。正文「在不是战斗开始即生成的场合」被 e_summon 的「生成」咬走，"
        "产出「召唤」——原文讲的是入场动画与路径起点，与召唤无关。",
}


def parse_mechanic(text: str, blackboard: dict[str, Any] | None = None) -> list[Term]:
    """一条机制正文 → `Term` 列表。

    与 `enemy_formula.parse_enemy` 同构：先 `detemplate` 展开 wiki 模板，
    再走 `formula.parse` 的区间消费，最后让算式通道收走带变量的复合式。
    """
    flat = detemplate(text)
    return _formula.parse(flat, blackboard, rules=RULES_MECHANIC,
                          extra=expr_terms)


def mechanic_terms(mechanics: Iterable[Mechanic]) -> list[tuple[Mechanic, list[Term]]]:
    """逐条编译，返回 (机制, 公式项) 对。"""
    return [(m, parse_mechanic(m.text)) for m in mechanics]


# ================================================================ 四、扫描

def scan_glossary(mechanics: Iterable[Mechanic] | None = None, *,
                  client: Any = None, rules: Iterable[Rule] | None = None) -> dict[str, Any]:
    """全表编译一遍，报覆盖率与未命中的高频残句。

    `rules` 只影响**统计口径**，不改变真编译路径——统计函数必须与
    `parse_mechanic` 逐行同口径，否则会把成绩报低（本项目踩过：
    统计函数漏挂 expr 通道，报 68.4% 而实为 69.3%）。
    """
    ms = list(mechanics) if mechanics is not None else fetch_glossary(client)
    rs = tuple(rules) if rules is not None else RULES_MECHANIC
    hit = 0
    per_section: dict[str, list[int]] = {}
    residual: dict[str, int] = {}
    samples: dict[str, str] = {}
    for m in ms:
        flat = detemplate(m.body)
        terms = _formula.parse(flat, None, rules=rs, extra=expr_terms)
        ok = 1 if terms else 0
        hit += ok
        per_section.setdefault(m.section, [0, 0])
        per_section[m.section][0] += ok
        per_section[m.section][1] += 1
        if not ok:
            key = _skeleton(flat)
            residual[key] = residual.get(key, 0) + 1
            samples.setdefault(key, m.name)
    total = len(ms)
    return {
        "total": total,
        "hit": hit,
        "rate": (hit / total) if total else 0.0,
        "sections": {k: {"hit": v[0], "total": v[1]} for k, v in per_section.items()},
        "residual": sorted(residual.items(), key=lambda kv: -kv[1]),
        "samples": samples,
    }


_SKEL_PUNCT = re.compile(r"[，。；、：:,.（）()\[\]【】<>《》\s]+")


def _skeleton(text: str) -> str:
    """把一条残句压成便于归并的骨架（去标点、数字归一）。"""
    s = _SKEL_PUNCT.sub("/", text)
    s = re.sub(r"\d+(?:\.\d+)?", "#", s)
    return s.strip("/")[:60]
