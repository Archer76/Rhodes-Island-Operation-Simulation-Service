"""PRTS 的敌人页取数与解析。

## 数据长什么样

`分类:敌人` 下约 1800 个页面，每页两份模板：

* `{{敌人信息/common2}}` —— **图鉴级**：`id` / `名称` / `index`（编号，如 `B1`、`SD13`）/
  `地位级别`（普通·精英·领袖）/ `种类` / `描述` / `伤害类型` / `攻击方式` / `行动方式` /
  `能力` / `登场活动` / `阵营`。
* `{{敌人信息/levelcontent}}` —— **逐档数值**，一档一个（`index=0/1/2…`）：
  生命、攻击、防御、法抗、移速、攻速、攻击间隔、重量、攻击范围半径、目标价值、
  损伤抵抗、元素抗性、基础嘲讽等级、十余项 `*抗性`，以及 `天赋` 与
  `技能N/技能N初始/技能N消耗/技能N技力/技能N效果`。

## 三个必须知道的坑

1. **高档位只写被改写的字段，其余靠继承。** 模板里每个字段都写成
   `{{{字段|{{#ask:[[<页名>#LEVEL<index-1>]]|?字段}}}}}`，即向**上一档**取。
   所以 `级别1` 常常只有 `index` 与 `最大生命值` 两行。本模块按 index 升序逐档合并
   （与 gamedata 那条 `m_defined` 合并是同一件事）。
2. **黑板数值藏在 HTML 注释里。** `levelcontent` 末尾常有一段
   `<!--[ {"key": "Mode_A.PHYSICAL", "value": 0.0}, … ]-->`——那正是游戏本体的
   `talentBlackboard`（P3R 相性、倒地阈值、重生参数全在里面）。
   **解析参数前必须先剥注释**，否则会被注释里的 `|` 干扰。
3. **注释掉的参数是"不可见"的，但往往是真的。** BOSS 页写着
   `|index=1<!--\n|名称=死志暗影-->`——PRTS 页面上这一档仍显示「“死志的凝结”」，
   而游戏数据里的名字是「死志暗影」。两者都留：生效参数进 `params`，
   注释里的参数进 `hidden`，谁也不替谁下判断。

## 三处容易读反的字段

* `技能N初始` = **首次就绪的冷却时间**（秒），`技能N消耗` = **之后每次就绪的冷却时间**，
  `技能N技力` 才是**技力消耗**。模板表头写得很清楚，别按"初始技力/消耗"理解。
* `数量` 这一项在模板里被 `#vardefine` 成了 `目标价值`——即**漏掉它扣几点关卡生命**，
  不是"场上有几个"。
* `攻击范围半径` 空值表示近战（半径 0），不是"没有数据"。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from .client import PrtsClient
from .wikitext import (
    find_templates, iter_templates, parse_params, template_name,
)
from .wikitext import parse_params as _parse_template

__all__ = [
    "ENEMY_CATEGORY", "PrtsEnemy", "EnemyLevel", "parse_page",
    "fetch_enemy_pages", "all_enemy_titles", "load_all",
    "extract_comments", "strip_comments", "template_params", "parse_blackboard",
    "resolve_fixes", "ERRATA_FIELD",
]

#: 敌人页面所在的分类
ENEMY_CATEGORY = "敌人"

#: levelcontent 里的数值字段 → 库里的列名
_NUM_FIELDS: dict[str, str] = {
    "最大生命值": "hp",
    "攻击力": "atk",
    "防御力": "defense",
    "法术抗性": "res",
    "移动速度": "move_speed",
    "攻击速度": "attack_speed",
    "攻击间隔": "base_attack_time",
    "生命恢复速度": "hp_recovery",
    "sp恢复速度": "sp_recovery",
    "重量等级": "weight",
    "攻击范围半径": "range_radius",
    "数量": "target_value",          # 模板里叫「目标价值」，即漏掉扣几点生命
    "损伤抵抗": "damage_resistance",
    "元素抗性": "element_resistance",
    "基础嘲讽等级": "taunt_level",
}

#: 某一档的 SP 槽（技力槽）信息。
#: `技力初始` 是 `初始技力` 的**词序颠倒**写法，全站只有 1 个敌人这么写
#: （「反巫术变位炸弹」），但白名单式解析会因此静默丢掉它的 init_sp——
#: 少一个字段不报错，只有逐字段核对才算得出来。两种词序都收。
_SP_FIELDS: dict[str, str] = {
    "初始技力": "init_sp",
    "技力初始": "init_sp",          # 词序颠倒的异体，见上
    "技力上限": "max_sp",
    "技力槽回复类型": "sp_recovery_type",
    "技力回复速度": "sp_recovery_value",
}

#: 以 `抗性` 结尾的参数一律当抗性收（不写死名单，模板加一项这里自动跟上）
_RESIST_SUFFIX = "抗性"

#: `技能N` / `技能N初始` / `技能N消耗` / `技能N技力` / `技能N效果` / `技能N类型`
_SKILL_RE = re.compile(r"^技能(\d+)(初始|消耗|技力|效果|类型)?$")

#: 存"未被模板消耗"的文本（数值字段的注释）时用的字段名，见 `template_params` 的说明。
#: 这里只用来给 `_RESIST_OVERRIDE` 起个名字，避免魔法字符串散落。
ERRATA_FIELD = "能力修正"

#: `{{异常效果|眩晕|免疫}}` —— `抗性覆写` 里用的记法
_AILMENT_TPL = "异常效果"
#: 单参数形态（`{{异常效果|失衡免疫}}`）里可当后缀切掉的部分
_AILMENT_SUFFIXES = ("免疫", "抵抗", "无效", "减免")

#: `抗性覆写`：**覆盖**同档的 `*抗性` 字段，而不是与它们并列
_RESIST_OVERRIDE = "抗性覆写"

_COMMENT_RE = re.compile(r"<!--(.*?)-->", re.S)
#: 数字字段里可能夹的富文本：`{{变动数值|350%|+}}`、`{{color|#fff|文字}}`、`[[页|显示]]`
_VARY_RE = re.compile(r"\{\{\s*变动数值\s*\|([^|}]*)[^}]*\}\}")
_TEMPLATE_RE = re.compile(r"\{\{[^{}]*\}\}")
_LINK_RE = re.compile(r"\[\[[^\[\]|]*\|([^\[\]]*)\]\]")
_TAG_RE = re.compile(r"<[^>]+>")
_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


# ------------------------------------------------------------------ 文本工具

def extract_comments(text: str) -> list[str]:
    """取出所有 HTML 注释的**内容**（不含 `<!--` / `-->`）。"""
    return _COMMENT_RE.findall(text or "")


def strip_comments(text: str) -> str:
    """删掉所有 HTML 注释。解析参数前**必须**先做这一步。"""
    return _COMMENT_RE.sub("", text or "")


def template_params(inner: str) -> dict[str, str]:
    """从一个模板调用片段里取命名参数（`{{名|k=v|…}}` 的 `k=v` 那部分）。

    复用 `wikitext.parse_params`——它按**顶层**竖线切分，嵌套模板与
    `[[a|b]]` 里的竖线骗不到它，值里的换行也原样保留。
    **调用前必须剥注释**：注释里可能整段藏着 `|名称=死志暗影` 这种参数，
    而那条注释本身带顶层竖线，不剥就会把参数切碎。
    """
    return _parse_template(inner)[1]


def resolve_fixes(text: str | None) -> str | None:
    """把 `{{修正lite|修正后内容|原文=…|原因=N}}` 展开成**站方勘误后的正文**。

    这不是"清洗富文本"，而是**换一份文本**：

    * `{{{1}}}`（位置参数）= 站方修正后的内容；
    * `原文=` = **游戏内原文**；
    * `原因=` = 勘误理由码（1 笔误 / 2 日服变更 / 3 用语未统一 / 4 误译 / 5 漏译 /
      6 **描述与游戏实际表现不符合** / 7 游戏文本存在疏漏 / 8 表述歧义）。

    模板自带说明写得很直白：「此处游戏内原文是X，因<原因>，我们对其进行了修正。」

    **两种文本都要留**——勘误是站方判断，不是游戏真值。本函数只负责把两边
    都还原成可读正文；采信哪一边由调用方决定（本项目的取法是：`能力` 存游戏
    原文、`ability_fixed` 另存勘误后文本，谁也不覆盖谁）。
    """
    if not text or "{{" not in text:
        return text
    out: list[str] = []
    last = 0
    for start, end, raw in iter_templates(text):
        inner = raw[2:-2]
        if template_name(inner) != "修正lite":
            continue
        _name, _named, positional = _parse_template(inner)
        if not positional:
            continue
        out.append(text[last:start])
        out.append(positional[0])
        last = end
    if not out:
        return text
    out.append(text[last:])
    return "".join(out)


def parse_aliments(text: str | None) -> list[tuple[str, str]]:
    """解析 `抗性覆写` 里的 `{{异常效果|…}}` 串，返回 `[(异常名, 取值)]`。

    两种写法都要认：

    * `{{异常效果|眩晕|免疫}}` —— 两个位置参数：异常名 + 效果；
    * `{{异常效果|失衡免疫}}` —— 一个位置参数，效果后缀直接焊在名字上。

    第二种形态里的 `失衡`／`强制缴械` **不在标准 `*抗性` 字段表里**，这正是
    `抗性覆写` 存在的意义：它能表达标准字段表达不了的免疫项。
    """
    if not text:
        return []
    out: list[tuple[str, str]] = []
    for inner in find_templates(text, _AILMENT_TPL):
        _name, _named, positional = _parse_template(inner)
        positional = [p.strip() for p in positional if p.strip()]
        if not positional:
            continue
        if len(positional) >= 2:
            out.append((positional[0], positional[1]))
            continue
        s = positional[0]
        for suf in _AILMENT_SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf):
                out.append((s[: -len(suf)], suf))
                break
        else:
            out.append((s, "有"))
    return out


def parse_blackboard(comments: list[str]) -> tuple[dict[str, Any], list]:
    """从注释里挖黑板。返回 `({键: 值}, 原文列表)`。

    注释是 `[…]` 或 `{…}` 形状的 JSON；不是 JSON 的注释直接跳过
    （页脚注释、编辑备注之类）。
    """
    for body in comments:
        s = body.strip()
        if not s or s[0] not in "[{":
            continue
        try:
            data = json.loads(s)
        except ValueError:
            continue
        if isinstance(data, dict):
            data = [data]
        if not isinstance(data, list) or not data:
            continue
        flat: dict[str, Any] = {}
        for item in data:
            if not isinstance(item, dict):
                continue
            k = item.get("key")
            if not k:
                continue
            v = item.get("value")
            flat[k] = v if v is not None else item.get("valueStr")
        if flat:
            return flat, data
    return {}, []


def _num(value: Any) -> float | None:
    """从可能带富文本的值里抠出一个数。取不到就 None（**不要**退化成 0）。"""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s or s in {"-", "—", "无", "/"}:
        return None
    s = _VARY_RE.sub(r"\1", s)
    s = _TEMPLATE_RE.sub(" ", s)
    s = _LINK_RE.sub(r"\1", s)
    s = _TAG_RE.sub(" ", s)
    m = _NUM_RE.search(s)
    return float(m.group()) if m else None


def _text(value: Any) -> str | None:
    """文本字段：空串与占位符 `-` 一律归 None。"""
    if value is None:
        return None
    s = str(value).strip()
    return None if s in {"", "-", "—"} else s


# ------------------------------------------------------------------ 结构

@dataclass
class EnemyLevel:
    """一个敌人的某一档。"""

    index: int
    #: 生效参数（本档显式值 + 从低档继承来的），**已剥注释**
    params: dict[str, str] = field(default_factory=dict)
    #: 本档**显式**写出的参数（不含继承），便于分辨"这一档真的改了没有"
    explicit: dict[str, str] = field(default_factory=dict)
    #: 注释里的参数（如 `|名称=死志暗影`）——页面上不显示，但往往是游戏本体的真值
    hidden: dict[str, str] = field(default_factory=dict)
    blackboard: dict[str, Any] = field(default_factory=dict)
    blackboard_raw: list = field(default_factory=list)

    def get(self, name: str) -> str | None:
        v = self.params.get(name)
        return v if v not in ("", None) else None

    def num(self, name: str) -> float | None:
        return _num(self.params.get(name))

    @property
    def name(self) -> str | None:
        return _text(self.params.get("名称"))

    @property
    def grade(self) -> str | None:
        return _text(self.params.get("地位"))

    @property
    def category(self) -> str | None:
        return _text(self.params.get("种类"))

    @property
    def description(self) -> str | None:
        return _text(self.params.get("描述"))

    @property
    def description_fixed(self) -> str | None:
        """档位描述里若有 `修正lite` 勘误标记，给出**展开后**的正文。

        `描述` 本身是原文（含标记），这里是站方勘误后的读法。两者都在库里。
        与 `能力` 的差别：`能力` 的勘误写在**另一个参数**（`能力修正`）里，
        而档位描述的勘误是**内联**在同一个值里的，没有平行参数可存。
        """
        raw = _text(self.params.get("描述"))
        if not raw or "修正lite" not in raw:
            return None
        return _text(resolve_fixes(raw))

    @property
    def attack_way(self) -> str | None:
        return _text(self.params.get("攻击方式"))

    @property
    def move_way(self) -> str | None:
        return _text(self.params.get("行动方式"))

    @property
    def talent(self) -> str | None:
        return _text(self.params.get("天赋"))

    def numbers(self) -> dict[str, float | None]:
        """数值字段 → 库列名。"""
        return {col: _num(self.params.get(f)) for f, col in _NUM_FIELDS.items()}

    def sp_slot(self) -> dict[str, Any]:
        # 两种词序都试：`初始技力` 是标准写法，`技力初始` 是个别页面的颠倒写法
        init = self.params.get("初始技力")
        if init in ("", None):
            init = self.params.get("技力初始")
        return {
            "init_sp": _num(init),
            "max_sp": _num(self.params.get("技力上限")),
            "sp_recovery_type": _text(self.params.get("技力槽回复类型")),
            "sp_recovery_value": _num(self.params.get("技力回复速度")),
        }

    def resists(self) -> list[tuple[str, str, bool, str]]:
        """`*抗性` 与 `抗性覆写` → `[(名字, 原文, 是否免疫, 来源)]`。

        取值是「有 / 无」这种中文，`有` 才是免疫；数值型也照收不误，
        判据只认 `有`，别把 `2` 当成免疫等级。

        来源有两种，**语义不同、不能混排**：

        * `字段`：标准的 `眩晕抗性=有` 那一批；
        * `覆写`：`抗性覆写={{异常效果|眩晕|免疫}} …`，**压过同名的字段值**。

        「蔓德拉」就是活例：她的 `*抗性` 字段全写「无」，而 `抗性覆写` 写七项免疫。
        只读字段会把她记成"什么都不免疫"。两条都返回，由调用方按 `覆写` 优先。
        """
        out: list[tuple[str, str, bool, str]] = []
        for k, v in self.params.items():
            if not k.endswith(_RESIST_SUFFIX) or k == _RESIST_SUFFIX:
                continue
            if k == _RESIST_OVERRIDE:
                continue
            val = (v or "").strip()
            if not val:
                continue
            out.append((k, val, val == "有", "字段"))
        for name, val in parse_aliments(self.get(_RESIST_OVERRIDE)):
            out.append((f"{name}抗性", val, val in ("有", "免疫"), "覆写"))
        return sorted(out)

    def skills(self) -> list[dict[str, Any]]:
        """`技能N*` 参数 → 每条技能的字典。

        名字与效果为空、且三档冷却/技力全是空的条目不算数（有的是占位）。
        """
        by_slot: dict[int, dict[str, Any]] = {}
        for k, v in self.params.items():
            m = _SKILL_RE.match(k)
            if not m:
                continue
            slot = int(m.group(1))
            suffix = m.group(2) or "name"
            by_slot.setdefault(slot, {"slot": slot})[suffix] = v
        out: list[dict[str, Any]] = []
        for slot in sorted(by_slot):
            d = by_slot[slot]
            rec = {
                "slot": slot,
                "name": _text(d.get("name")),
                "effect": _text(d.get("效果")),
                # 表头：play-circle = 首次就绪冷却，circle-slice-5 = 之后每次就绪冷却
                "init_cooldown": _num(d.get("初始")),
                "cooldown": _num(d.get("消耗")),
                "sp_cost": _num(d.get("技力")),
                "kind": _text(d.get("类型")),
            }
            if any(rec[k] is not None for k in
                   ("name", "effect", "init_cooldown", "cooldown", "sp_cost")):
                out.append(rec)
        return out


@dataclass
class PrtsEnemy:
    """一个敌人页的解析结果。"""

    page: str
    common: dict[str, str] = field(default_factory=dict)
    levels: list[EnemyLevel] = field(default_factory=list)
    raw_wikitext: str = ""

    # ---------------------------------------------------------- 图鉴级
    @property
    def prts_id(self) -> int | None:
        n = _num(self.common.get("id"))
        return int(n) if n is not None else None

    @property
    def name(self) -> str:
        return _text(self.common.get("名称")) or self.page

    @property
    def display_name(self) -> str | None:
        return _text(self.common.get("显示名"))

    @property
    def index_code(self) -> str | None:
        return _text(self.common.get("index"))

    @property
    def grade(self) -> str | None:
        return _text(self.common.get("地位级别"))

    @property
    def category(self) -> str | None:
        return _text(self.common.get("种类"))

    @property
    def damage_type(self) -> str | None:
        return _text(self.common.get("伤害类型"))

    @property
    def attack_way(self) -> str | None:
        return _text(self.common.get("攻击方式"))

    @property
    def move_way(self) -> str | None:
        return _text(self.common.get("行动方式"))

    @property
    def camp(self) -> str | None:
        return _text(self.common.get("阵营"))

    @property
    def description(self) -> str | None:
        """图鉴「描述」——**风味文本，按裁定不入库**。

        解析器照旧读出来（它确实是页面的一部分），但 `enemy_build` 不写进
        `enemy` 表，`enemy_field_audit` 把它列在 `_NOT_BATTLE` 里。
        逐档的那个 `描述`（`EnemyLevel.description`）是另一回事——里面混着
        能力正文，照旧入库，别一起删了。
        """
        return _text(self.common.get("描述"))

    @property
    def ability(self) -> str | None:
        """图鉴「能力」一栏——**游戏内原文**。"""
        return _text(self.common.get("能力"))

    @property
    def ability_errata_raw(self) -> str | None:
        """`能力修正` 的**原始** wikitext（带 `修正lite` 标记），留作追溯。"""
        return _text(self.common.get(ERRATA_FIELD))

    @property
    def ability_fixed(self) -> str | None:
        """图鉴「能力」的**站方勘误后**文本（展开 `修正lite` 后）。

        与 `ability` 是**两份不同的文本**，不是"清洗前后"的关系：

        * 全站 114 页有勘误，179 处新文本**不存在于** `能力` 里，
          77 处旧文本**存在于** `能力` 里——即 `能力` 是过期的游戏原文；
        * 最刺眼的是「大总统」汉科：原文「并使其中所有单位的隐匿和迷彩失效」，
          勘误插入「不会」→「并**不会**使……」——语义整个反转。

        勘误理由是站方判断（原因码 6 = 描述与游戏实际表现不符合），所以两份都留，
        由调用方按用途选。返回 None 表示这一页没有勘误。
        """
        raw = self.ability_errata_raw
        if not raw:
            return None
        return _text(resolve_fixes(raw))

    @property
    def debut_event(self) -> str | None:
        return _text(self.common.get("登场活动"))

    @property
    def is_irregular(self) -> bool:
        """非常规敌人：通常没有图鉴，也不会进游戏内的敌方档案库。"""
        return bool(_text(self.common.get("非常规敌人")))

    @property
    def has_handbook(self) -> bool:
        """有 `index` 才算有图鉴；没有的话 PRTS 页面上写的是「该敌人不具有图鉴」。"""
        return self.index_code is not None


# ------------------------------------------------------------------ 解析

def parse_page(page: str, wikitext: str) -> PrtsEnemy:
    """解析一个敌人页。"""
    enemy = PrtsEnemy(page=page, raw_wikitext=wikitext or "")

    for inner in find_templates(wikitext or "", "敌人信息/common2"):
        enemy.common = template_params(strip_comments(inner))
        break

    raw_levels: list[tuple[int, dict[str, str], dict[str, str], dict, list]] = []
    for order, inner in enumerate(
            find_templates(wikitext or "", "敌人信息/levelcontent")):
        comments = extract_comments(inner)
        explicit = template_params(strip_comments(inner))
        hidden: dict[str, str] = {}
        for c in comments:
            hidden.update(template_params(c))
        bb, bb_raw = parse_blackboard(comments)
        idx = _num(explicit.get("index"))
        raw_levels.append((int(idx) if idx is not None else order,
                           explicit, hidden, bb, bb_raw))

    # 按 index 升序逐档合并——模板就是这么写的（向 index-1 那条 subobject 取）
    #
    # **空串不覆盖继承值。** 模板把每个字段写成 `{{{字段|{{#ask:…}}}}}`，而
    # MediaWiki 的 `{{{x|默认}}}` 在 x **为空**时同样采用默认值——所以
    # `|技力初始=` 的语义是"继承上一档"，不是"置空"。原实现 `{**merged, **carry}`
    # 让空串顶掉了继承值，实测 4 个页面 8 处静默少数据，且都咬在战斗字段上：
    # 杜卡雷档 2 的 `攻击范围半径` 2.2 被抹成 None（读出来就是近战半径 0），
    # 「反巫术变位炸弹」档 1 整个技力槽与技能名「爆炸」消失。
    # 空值仍原样留在 `explicit` 里，追溯得到"这一档确实写了空"。
    raw_levels.sort(key=lambda t: t[0])
    merged: dict[str, str] = {}
    for idx, explicit, hidden, bb, bb_raw in raw_levels:
        carry = {k: v for k, v in explicit.items()
                 if k not in ("index", "reindex") and (v or "").strip()}
        merged = {**merged, **carry}
        enemy.levels.append(EnemyLevel(
            index=idx,
            params=dict(merged),
            explicit=dict(explicit),
            hidden=hidden,
            blackboard=bb,
            blackboard_raw=bb_raw,
        ))
    return enemy


# ------------------------------------------------------------------ 取数

def all_enemy_titles(client: PrtsClient | None = None,
                     limit: int = 20000) -> list[str]:
    """`分类:敌人` 的全部页名。"""
    c = client or PrtsClient()
    return c.category_members(ENEMY_CATEGORY, limit=limit)


def fetch_enemy_pages(titles: list[str], client: PrtsClient | None = None,
                      batch: int = 50, *, progress=None) -> dict[str, str]:
    """批量取页面正文。

    MediaWiki 一次 `titles=` 最多 50 个（机器人 500），所以 1800 页只要 36 次
    请求；每次请求都被 `PrtsClient` 的缓存按 URL 收下，重跑不重复打网。
    """
    c = client or PrtsClient()
    out: dict[str, str] = {}
    for i in range(0, len(titles), batch):
        chunk = titles[i:i + batch]
        data = c.get_json({
            "action": "query", "prop": "revisions", "rvprop": "content",
            "rvslots": "main", "titles": "|".join(chunk),
        })
        for page in data.get("query", {}).get("pages", []):
            revs = page.get("revisions") or []
            if not revs:
                continue
            out[page.get("title") or ""] = revs[0]["slots"]["main"]["content"]
        if progress:
            progress(min(i + batch, len(titles)), len(titles))
    return out


def load_all(client: PrtsClient | None = None, *,
             titles: list[str] | None = None, progress=None
             ) -> list[PrtsEnemy]:
    """取全量敌人并解析。返回按页名排序的列表。"""
    c = client or PrtsClient()
    names = titles if titles is not None else all_enemy_titles(c)
    pages = fetch_enemy_pages(names, c, progress=progress)
    out = [parse_page(t, pages[t]) for t in names if t in pages]
    return out
