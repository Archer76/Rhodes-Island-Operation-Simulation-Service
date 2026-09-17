# -*- coding: utf-8 -*-
"""敌人正文 → 公式项：语料加载与预清洗。

与 `ak_tactic/formula.py`（干员侧）的关系是**共用解析器、另加一层清洗**：

* 干员侧的正文来自 **gamedata**，本来就是游戏内文本，只有 `<$ba.xxx>` 标签与
  `{key:spec}` 占位符，`formula.normalize` 直接吃得下。
* 敌人侧的正文来自 **prts.wiki 的 wikitext**，还夹着一层 wiki 模板
  （`{{术语|ba.stun|晕眩}}`、`{{color|#FF4F0B|第一形态}}`、
  `{{异常效果|晕眩|免疫}}`、`{{修正lite|…}}`）。**必须先展开成纯文本**，
  否则规则匹配到的是模板名而不是机制名。

所以本模块只做两件事：`detemplate()` 把 wikitext 正文洗成纯文本，
`load_enemy_corpus()` 从 `data/enemydb.sqlite` 读全部正文并配上黑板。
解析本身仍交给 `formula.parse`，规则集将来按敌人机制另扩。
"""
from __future__ import annotations

import json
import re
import sqlite3
from pathlib import Path
from typing import Any, Iterable

from .prts.wikitext import parse_params

__all__ = ["detemplate", "load_enemy_corpus",
           "enemy_scan", "CorpusRow", "ENEMY_RULES", "RULES_ENEMY",
           "parse_enemy", "formulas_enemy"]

#: **最内层**模板：花括号内不含花括号。
#:
#: 不能用 `iter_templates` 逐层剥——它给的是**顶层**片段，而正文里模板会嵌套
#: （`{{color|#FFF|{{术语|ba.stun|晕眩}}}}`）。按"跳过含 `{{` 的顶层片段"处理，
#: 遇到整段只有嵌套模板时（如「{{特殊机制|{{术语|…}}}}」）会一条都展不开就退出。
#: 从最内层往外替换则天然收敛：每轮必定消掉一层花括号。
_INNERMOST = re.compile(r"\{\{([^{}]*)\}\}")

#: wiki 内链 `[[页名|显示文字]]` → `显示文字`
_WIKILINK = re.compile(r"\[\[(?:[^\[\]|]*\|)?([^\[\]|]*)\]\]")

#: 换行标记 → 逗号，避免两个语义片段粘成一个词
_BREAK = re.compile(r"<br\s*/?>", re.IGNORECASE)

#: 粗体/斜体标记
_EMPH = re.compile(r"'{2,5}")

#: 注释
_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)

# 这里曾经有过 `split_clauses()`：按 `·`/`※`/`。`/`、` 把正文切成条目再逐条解析，
# 期望救回「一串机制写成清单」的长文本。**它是恒等变换，已删除**，理由如下：
#
#   规则表全是**无锚定的子串正则**（`re.search`，不是 `fullmatch`）。若整句里
#   任何位置都没命中任何规则，那么整句的任意子串（=任一条目）里也不可能命中。
#   所以「整句为空 → 逐条重试」**必然还是空**，切分对召回率是恒等变换。
#
# 实测坐实：语料里整句为空的 2208 条中，612 条可切分，逐条救回 **0** 条。
# 反过来「有条目就直接逐条解析」（不先试整句）覆盖**一样**，却改动了 7 条原本
# 已覆盖文本的旧项——零收益、纯风险。
#
# 真正涨覆盖的是**新规则**（60.5% → 68.2%）。若将来加入**锚定**规则
# （要求整条匹配，如 `^…$`），切分才会重新有意义。

#: **单位/事物引用**：`<无谓>`、`<大君之触>`、`<R系列动力装甲>`、`<“超惊喜信件”>`。
#:
#: 必须在下游 `formula.normalize` 之前**换成可见的引号**，否则会被它的
#: `TAG_RE = <[^>]{0,24}>` 当成富文本标签整段剥掉——`召唤1个<无谓>` 变成
#: `召唤1个`，**召唤的是什么都丢了**，而"召唤出了什么"恰恰是这条语料唯一的语义。
#:
#: 判据是"像不像真标签"，不是"有没有尖括号"：真标签以 `$` / `@` / `/` 开头
#: （`<$ba.stun>`、`<@ba.vup>`、`</>`），或是 `br` / `color=…` 这类 HTML。
#: 中文名、带引号的名字、字母数字混排的型号名都不会有这个前缀。
_UNIT_REF = re.compile(r"<(?![$@/]|br\s*/?>|/?color\b)([^<>=]{1,30})>",
                       re.IGNORECASE)

#: `{{模板名|参数…}}` 里，**取第几个位置参数作为正文**。
#: 键是模板名，值是位置参数的索引（0 起）。
_TPL_ARG: dict[str, int] = {
    "术语": 1,        # {{术语|ba.stun|晕眩}} → 晕眩（第 0 个是内部术语 id）
    "color": 1,       # {{color|#FF4F0B|第一形态}} → 第一形态
    "特殊机制": 0,     # {{特殊机制|伤害相性（P3R）}}
    "异常效果": 0,     # {{异常效果|眩晕|免疫}} → 眩晕（后缀另行合成，见下）
    "修正lite": 0,    # 站方勘误 → 修正后内容（与 enemy.ability_fixed 同义）
    "释义": 1,
    "名词": 1,
    "悬浮": 1,
}

#: 这几个模板的位置参数要**拼成一个词**：
#: `{{异常效果|失衡|免疫}}` 合成「失衡免疫」，取第 0 个会丢掉「免疫」。
_CONCAT_TPL = {"异常效果"}


def _expand_one(name: str, named: dict[str, str],
                positional: list[str]) -> str | None:
    """把一个模板展开成纯文本；不认识就返回 None（由调用方拍平参数）。"""
    if name in _CONCAT_TPL:
        return "".join(p.strip() for p in positional if p.strip())
    if name in _TPL_ARG:
        i = _TPL_ARG[name]
        if i < len(positional):
            return positional[i].strip()
        return positional[0].strip() if positional else None
    return None


def detemplate(text: str) -> str:
    """prts.wiki wikitext 正文 → 纯文本。

    依次做五件事：展开模板（最内层往外，嵌套自然收敛）→ 摊平内链 →
    **保住单位引用**（`<无谓>` → `「无谓」`，见 `_UNIT_REF`）→
    换行标记变逗号 → 去粗斜体与注释。

    不认识的模板取**最后一个非空位置参数**（通常是显示文字），
    宁可留下词也不要让 `{{ }}` 混进正文——规则匹配到模板名等于没匹配。
    """
    out = _COMMENT.sub("", text or "")
    for _ in range(200):
        m = _INNERMOST.search(out)
        if m is None:
            break
        name, _named, positional = parse_params(m.group(1))
        piece = _expand_one(name, _named, positional)
        if piece is None:
            vals = [v.strip() for v in positional if v.strip()]
            piece = vals[-1] if vals else ""
        out = out[:m.start()] + piece + out[m.end():]
    out = _WIKILINK.sub(r"\1", out)
    out = _UNIT_REF.sub(r"「\1」", out)
    out = _BREAK.sub("，", out)
    out = _EMPH.sub("", out)
    return out


# ---------------------------------------------------------------- 语料

class CorpusRow(dict):
    """一条语料：`source` / `key` / `text` / `blackboard`。"""


def load_enemy_corpus(db: Path | str) -> list[CorpusRow]:
    """从敌人库读全部正文语料，返回 [(来源, 标识, 文本, 黑板)] 形态的字典。

    五类来源，覆盖敌人侧所有带机制的正文：

    | source | 表 | 说明 |
    |---|---|---|
    | `ability` | `enemy` | 图鉴「能力」段（游戏内原文） |
    | `ability_fixed` | `enemy` | 同上，站方勘误后读法（仅 114 页有） |
    | `talent` | `enemy_level` | 逐档天赋正文 |
    | `desc` | `enemy_level` | 逐档描述（含弱点/形态说明） |
    | `skill` | `enemy_skill` | 敌方技能效果正文 |

    黑板一律取**同档**的 `enemy_level.blackboard`（图鉴级没有黑板）。
    """
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    rows: list[CorpusRow] = []
    try:
        lv_bb: dict[tuple[str, int], dict[str, Any]] = {}
        for r in conn.execute(
                "SELECT page, level, blackboard FROM enemy_level"):
            lv_bb[(r["page"], r["level"])] = _bb(r["blackboard"])

        def lv(page: str, level: int, source: str, key: str,
               text: str | None) -> None:
            if text and text.strip():
                rows.append(CorpusRow(source=source, key=key, text=text,
                                      blackboard=lv_bb.get((page, level), {})))

        for r in conn.execute(
                "SELECT page, ability, ability_fixed FROM enemy WHERE "
                "COALESCE(ability, '')<>'' OR COALESCE(ability_fixed, '')<>''"):
            lv(r["page"], 0, "ability", r["page"], r["ability"])
            if r["ability_fixed"]:
                lv(r["page"], 0, "ability_fixed", r["page"], r["ability_fixed"])
        for r in conn.execute(
                "SELECT page, level, talent, description, description_fixed "
                "FROM enemy_level"):
            tag = f"{r['page']}#L{r['level']}"
            lv(r["page"], r["level"], "talent", tag, r["talent"])
            lv(r["page"], r["level"], "desc", tag, r["description"])
            if r["description_fixed"]:
                lv(r["page"], r["level"], "desc", tag + ":fix",
                   r["description_fixed"])
        for r in conn.execute(
                "SELECT page, level, slot, name, effect FROM enemy_skill "
                "WHERE COALESCE(effect, '')<>''"):
            tag = f"{r['page']}#L{r['level']}S{r['slot']}"
            lv(r["page"], r["level"], "skill", tag, r["effect"])
    finally:
        conn.close()
    return rows


def _bb(raw: Any) -> dict[str, Any]:
    """黑板列 → 扁平字典。库里存的是 JSON 字符串。"""
    if isinstance(raw, dict):
        return dict(raw)
    if isinstance(raw, str) and raw.strip():
        try:
            obj = json.loads(raw)
        except ValueError:
            return {}
        return obj if isinstance(obj, dict) else {}
    return {}


# ---------------------------------------------------------------- 敌人规则

from . import formula as _formula                      # noqa: E402
from .formula import Rule, _r                          # noqa: E402

_FORMULA_N = _formula.N
_FORMULA_PCT = _formula.PCT

#: 敌人侧的数值占位：**只要阿拉伯数字**（外加 normalize 的哨兵形式）。
#:
#: 与干员侧的 `{N}` 不同——那个还接受「一/二/两/三」等中文数字。差别来自语料：
#: gamedata 的游戏内正文会写「造成二次伤害」，中文数字是真数值；而 prts.wiki 的敌人
#: 正文是**人写的散文**，中文数字几乎只出现在习语里——「蓄力**一**段时间」
#: 「**两**个阶段」「**一**定幅度」。用 `{N}` 会把这些「一」当成 1，
#: 实测产出过 `蓄力一 → 持续 1s` 这种**看起来完全合理、实际是编的**的公式项。
_DNUM = r"(?:\d+(?:\.\d+)?|«\d+»)"

#: **序数**占位：`第一形态`「切换至第二形态」。这里的中文数字是合法的——
#: 序数就该写中文，与量词的习语问题正好相反，所以单独一个占位符。
_DORD = rf"(?:{_DNUM}|[一二三四五六七八九十两])"

#: 敌人侧新立的 kind → 中文标签。**只增不改**：干员侧的键原样留着。
#:
#: 为什么敌人需要自己的 kind 而不是硬塞进现有那几个：敌人有一整套
#: 干员身上不存在的概念——不可阻挡、无敌、重生、形态切换、相性弱点、
#: 每秒自伤。把它们塞进 `buff`/`flag` 会让"按 kind 查所有无敌敌人"变成
#: 一次全文搜索。
_ENEMY_LABELS = {
    "block": "阻挡", "invincible": "无敌", "immune": "免疫",
    "revive": "重生", "form": "形态", "movespeed": "移速",
    "reflect": "反射", "stealth": "隐匿", "dot": "持续伤害",
    "selfharm": "自伤", "aura": "光环", "fly": "移动方式",
    "taunt": "嘲讽", "channel": "蓄力", "fragile": "脆弱",
    "debuff_ms_down": "减速", "debuff": "减益",
    "formula": "算式",
}

#: 异常状态词表。`免疫X` / `X免疫` 两种语序共用，改这里一处即可。
#:
#: 末尾几个是**场地/元素**类（沼泽、水蚀），措辞来自真实页面：
#: 「免疫沼泽地段影响」「免疫水蚀」。
_AILMENT = (
    "失衡|晕眩|眩晕|停顿|沉默|冻结|浮空|战栗|恐惧|麻痹|诱导|传送|缚地|"
    "睡眠|沉睡|缴械|强制缴械|庇护|元素|水蚀|沼泽|灼燃|侵蚀|凋亡|神经|"
    "中毒|灼烧|寒冷|冰冻|晕眩"
)

#: 敌人规则集。**接在干员规则之后**跑（见 `parse_enemy`）：
#: 干员那 130 条已把数值与量纲的活干得很熟，敌人规则只补它不认识的概念。
ENEMY_RULES: tuple[Rule, ...] = (
    # ================================================ 相性（P3R）
    # 这两条必须在最前：「弱点：物理」「免疫：元素」是 P3R 相性表的口径，
    # 若被后面的通用规则先咬掉，相性就丢了。
    _r("e_weakness",
       r"弱点[：:](?P<a>物理|法术|元素)",
       "trait", op="self", attr="=a", form="word", note="P3R 相性：弱点"),
    _r("e_negate",
       r"免疫[：:](?P<a>[^，。；\n]{1,20})",
       "immune", op="self", attr="=a", form="word", note="P3R 相性：免疫"),

    # ================================================ 阻挡
    _r("e_unblockable",
       r"(?:无法|不可|不能)(?:被)?(?:攻击/)?阻挡|不可被阻挡",
       "block", op="self", form="word", flag="不可阻挡"),
    _r("e_self_bind",
       r"自缚",
       "block", op="self", form="word", flag="自缚（不移动不攻击）"),
    _r("e_block_count",
       rf"阻挡数(?:为|＝|=|\+)?{_DNUM}",
       "block", op="self", scale=0, form="flat", attr="阻挡数"),
    _r("e_block_cond_effect",
       rf"被阻挡时(?:立即)?(?P<a>防御力|法术抗性|攻击力|攻击速度|移动速度)?"
       rf"(?:短暂|大幅|显著)?(?:提升|提高|增加|降低|下降)",
       "buff", op="self", attr="=a", form="word", note="条件：被阻挡时"),
    # 这两条必须早于通用的 `e_shelter`：庇护在「未被阻挡时」是**条件性减伤**，
    # 而单独出现的 `40%庇护` 是无条件减伤。分开了才查得清来源。
    _r("e_unblocked_dodge",
       rf"未被阻挡时(?:有几率)?(?:获得)?(?:{_DNUM}{_FORMULA_PCT}的?)?"
       rf"(?P<a>物理闪避|法术闪避|闪避)",
       "dodge", op="self", attr="=a", scale=0, form="word",
       note="条件：未被阻挡时"),
    _r("e_unblocked_shelter",
       rf"未被阻挡时(?:有几率)?(?:获得)?(?:{_DNUM}{_FORMULA_PCT}的?)?庇护",
       "buff", op="self", attr="庇护", scale=0, form="word",
       note="减伤；条件：未被阻挡时"),

    # ================================================ 无敌
    _r("e_invincible_dur",
       rf"(?:获得|赋予|给予)?{_DNUM}s?(?:的)?无敌",
       "invincible", op="self", dur=0, form="word"),
    _r("e_invincible",
       r"(?:永久)?无敌",
       "invincible", op="self", form="word", flag="无敌"),

    # ================================================ 免疫 / 异常
    _r("e_immune_damage",
       r"免疫(?P<a>物理|法术|真实|元素)(?:伤害|类型)?",
       "immune", op="self", attr="=a", form="word", note="免疫该伤害类型"),
    _r("e_immune_suffix",
       rf"(?P<a>{_AILMENT})免疫",
       "immune", op="self", attr="=a", form="word"),
    _r("e_immune_prefix",
       rf"免疫(?P<a>{_AILMENT})(?:地段|区域|效果|影响)?",
       "immune", op="self", attr="=a", form="word"),

    # ================================================ 移动速度
    _r("e_movespeed_times",
       rf"移动速度(?:变为|提升至|乘以){_DNUM}倍",
       "movespeed", op="self", scale=0, form="flat", attr="移动速度"),
    _r("e_movespeed_down",
       rf"移动速度(?:大幅|短暂|显著)?(?:降低|下降|减少|-){_DNUM}{_FORMULA_PCT}",
       "movespeed", op="self", scale=0, form="sign_down", attr="移动速度"),
    # 「提升**至**N%」是**设为目标值**，不是 +N%。必须早于 `e_movespeed_up`：
    # 那条把「提升」当增量、按 `base×(1+N%)` 结算，而「最终提升至500%」的
    # 真意是 `base×500%`——两者差 6 倍，且**表达式看起来完全合理**。
    _r("e_movespeed_to",
       rf"移动速度(?:最终)?(?:提升|提高|增加|上升)至{_DNUM}{_FORMULA_PCT}",
       "movespeed", op="self", scale=0, form="flat", attr="移动速度最终值",
       note="「提升至N%」= 设为目标值（base×N%），不是 +N%"),
    _r("e_movespeed_up",
       rf"移动速度(?:最终)?(?:提升|提高|增加|上升|\+|大幅提升){_DNUM}{_FORMULA_PCT}",
       "movespeed", op="self", scale=0, form="signed", attr="移动速度"),
    _r("e_movespeed_word_up",
       r"移动速度(?:会)?(?:短暂|大幅|显著|逐渐)?(?:提升|提高|增加|上升|加快)",
       "movespeed", op="self", form="word", attr="移动速度",
       flag="移动速度提升（幅度未写明）"),
    _r("e_movespeed_word_down",
       r"移动速度(?:会)?(?:短暂|大幅|显著|逐渐)?(?:降低|下降|减少|减慢)",
       "movespeed", op="self", form="word", attr="移动速度",
       flag="移动速度降低（幅度未写明）"),

    # ================================================ 每秒 / 自伤 / 回复
    _r("e_self_dot",
       rf"自身每秒受到{_DNUM}(?:点)?(?:无来源)?(?P<dt>物理|法术|真实)?伤害",
       "selfharm", op="self", dtype="=dt", scale=0, form="flat", attr="生命值"),
    _r("e_per_sec_damage",
       rf"每秒(?:对其)?(?:持续)?造成{_DNUM}(?:点)?"
       rf"(?P<dt>物理|法术|真实|元素)?伤害",
       "dot", op="enemy", dtype="=dt", scale=0, form="flat"),
    _r("e_per_sec_damage_word",
       r"每秒(?:对其)?(?:持续)?造成(?:一定|少量|大量|高额)(?:的)?"
       r"(?P<dt>物理|法术|真实|元素)?伤害",
       "dot", op="enemy", dtype="=dt", form="word"),
    _r("e_per_sec_regen",
       rf"每秒(?:恢复|回复)(?:相当于(?:自身)?(?:最大)?生命值)?{_DNUM}{_FORMULA_PCT}?"
       rf"(?:的)?(?:生命值|生命)",
       "regen", op="self", scale=0, form="flat", attr="生命值"),
    _r("e_per_sec_regen_word",
       r"每秒(?:恢复|回复|流失)(?:一定|少量|大量)?(?:的)?(?:生命值|生命)",
       "regen", op="self", form="word", attr="生命值"),
    _r("e_aura_heal",
       r"持续(?:为|给)[^，。；\n]{1,20}(?:回复|恢复)(?:一定)?(?:的)?(?:生命值|生命)",
       "aura", op="ally", form="word", note="范围内持续回复"),

    # ================================================ 召唤 / 生成
    # **只认「召唤」「生成」**。曾把「释放」「放下」也算作召唤，实测 1007 次命中
    # 里绝大多数是「释放源石技艺」「释放当前波次」「放下结晶」这类**不是召唤**
    # 的动作——覆盖率上去了，正确率塌了。放置类另立一条。
    _r("e_summon",
       rf"(?:按预设路径|以预设路径|在预设位置|在地图预设位置|在场上预设位置|"
       rf"在自身所在格|在指定位置|在场上|在地图)*(?:召唤|生成)"
       rf"(?:{_DNUM}(?:个|名|只|批|次))?",
       "summon", op="ally", count=0, form="word",
       note="召唤物的名字见原文片段"),
    _r("e_place",
       rf"(?:放下|放置|布置|埋设)(?:{_DNUM}(?:个|枚|处))?",
       "flag", op="ally", count=0, form="word", note="放置物/地形改造"),

    # ================================================ 重生 / 分裂
    _r("e_revive_after",
       r"(?:首次)?(?:倒下|被击倒|死亡|退场)后(?:重生|复活|变为|生成|分裂)",
       "revive", op="self", form="word"),
    _r("e_revive_dur",
       rf"进入持续{_DNUM}s?的(?:重生|复活)",
       "revive", op="self", dur=0, form="word"),
    _r("e_revive",
       r"(?:重生|复活)(?:状态|阶段|形态)?",
       "revive", op="self", form="word"),
    _r("e_split",
       r"分裂自身|分裂为[^，。；\n]{0,12}",
       "revive", op="self", form="word", flag="分裂"),

    # ================================================ 形态
    _r("e_form_switch",
       rf"(?:切换|变更|转移|回到)(?:至|为|到)(?:第{_DORD})?(?P<a>形态|阶段|模式)",
       "form", op="self", attr="=a", form="word"),
    _r("e_form_become",
       rf"(?:变为|变成|转为)(?:第{_DORD})?"
       rf"(?P<a>形态|阶段|模式|近战|远程|飞行|不可阻挡|随机敌人|其他敌人)",
       "form", op="self", attr="=a", form="word"),
    _r("e_form_phase",
       rf"第{_DORD}(?:形态|阶段)",
       "form", op="self", form="word"),

    # ================================================ 隐匿 / 迷彩
    _r("e_stealth",
       r"(?:获得|拥有|处于|进入)?(?P<a>隐匿|迷彩|隐身)(?:状态)?",
       "stealth", op="self", attr="=a", form="word"),

    # ================================================ 护盾 / 减伤 / 脆弱
    _r("e_shield_maxhp",
       rf"获得可吸收相当于(?:当前)?最大生命值{_DNUM}{_FORMULA_PCT}的"
       rf"(?:全伤害|全类型|所有伤害)?(?:屏障|护盾)",
       "shield", op="self", scale=0, form="flat", attr="最大生命值"),
    _r("e_shield",
       r"(?:获得|拥有|持有|提供)?(?:特殊|元素|全伤害)?(?:护盾|屏障)",
       "shield", op="self", form="word"),
    _r("e_shelter",
       rf"{_DNUM}{_FORMULA_PCT}(?:的)?庇护",
       "buff", op="self", scale=0, form="flat", attr="庇护", note="减伤"),
    _r("e_damage_reduce_pct",
       rf"(?P<a>物理与法术|物理/法术|物理和法术|全部|所有|近战|远程|物理|法术)?"
       rf"伤害(?:倍率)?(?:大幅|显著)?(?:降低|减少|下降){_DNUM}{_FORMULA_PCT}",
       "buff", op="self", attr="=a", scale=0, form="sign_down", note="减伤"),
    # 同一个机制的**减号写法**：`受到的物理/法术伤害-80%`。此前只认动词写法
    # （降低/减少/下降），写成减号就**整条不匹配**——然后被算式 pass 兜住，
    # 吐出一条看着对、其实是错的项（把「法术伤害」当成变量名）。
    # 博士 2026-09-16 裁定：`受到的物理伤害与法术伤害都降低80%`，即两者同减。
    # 共 91 处，是唯一会**伪装成已解析**的一类，故单列一条规则。
    _r("e_damage_reduce_sign",
       rf"(?P<a>物理与法术|物理/法术|物理和法术|全部|所有|近战|远程|物理|法术)?"
       rf"伤害(?:倍率)?(?:大幅|显著)?[-－−]{_DNUM}{_FORMULA_PCT}",
       "buff", op="self", attr="=a", scale=0, form="sign_down", note="减伤"),
    _r("e_damage_reduce_word",
       r"伤害(?:倍率)?(?:大幅|显著|少量)?(?:降低|减少)",
       "buff", op="self", form="word", note="减伤（幅度未写明）"),
    _r("e_fragile",
       rf"(?P<a>元素|物理|法术)?脆弱(?:{_DNUM}{_FORMULA_PCT})?",
       "fragile", op="enemy", attr="=a", scale=0, form="word"),
    # 「使目标受到来自自身的伤害+100%」——这是**易伤**（增伤），不是减伤。
    # 此前规则表没有这一类，于是被算式 pass 兜住，吐出一条 `算式 100%
    # ⟨变量：来自自身的伤害⟩`：字符串忠实，但语义完全错（它根本不是算式）。
    _r("e_damage_amp",
       rf"受到(?:来自[^，。；、]{{0,12}}的)?伤害[+＋]{_DNUM}{_FORMULA_PCT}",
       "fragile", op="enemy", attr="受到伤害", scale=0, form="signed",
       note="易伤（受到伤害提高）"),

    # ================================================ 反射 / 折射
    _r("e_reflect",
       rf"(?:反弹|反射|折射)(?:部分)?(?:本应受到的)?(?:{_DNUM}{_FORMULA_PCT})?"
       rf"(?:的)?(?:伤害)?",
       "reflect", op="enemy", scale=0, form="word"),

    # ================================================ 属性增减（「提升N」写法）
    # 干员侧的 `buff_atk` / `buff_aspd` 只认游戏内的 `攻击力+50` 记法——
    # gamedata 的正文本来就是那样写的。**prts.wiki 的敌人正文是手写的**，
    # 用的是「攻击力提升50」这种自然语句，实测漏掉一大片。
    # 移动速度不在其中，它有自己的 `e_movespeed_*`（分幅度/倍率/词句三种）。
    _r("e_attr_up",
       rf"(?P<a>攻击力|防御力|法术抗性|攻击速度|生命值)"
       rf"(?:大幅|显著|短暂|逐渐)?(?:提升|提高|增加|上升)(?:至)?"
       rf"{_DNUM}{_FORMULA_PCT}",
       "buff", op="self", attr="=a", scale=0, form="signed"),
    _r("e_attr_down",
       rf"(?P<a>攻击力|防御力|法术抗性|攻击速度|生命值)"
       rf"(?:大幅|显著|短暂|逐渐)?(?:降低|下降|减少)(?:至)?"
       rf"{_DNUM}{_FORMULA_PCT}",
       "debuff", op="self", attr="=a", scale=0, form="sign_down"),
    # 无数值的那一档：「·攻击速度提升，·弱点：物理」——真数据在 Blackboard 里，
    # 正文只说了方向。**必须排在 e_attr_up 之后**，否则「提升50」会被它先咬走。
    _r("e_attr_word_up",
       r"(?P<a>攻击力|防御力|法术抗性|攻击速度|生命值)(?:大幅|显著|短暂)?"
       r"(?:提升|提高|增加|上升)",
       "buff", op="self", attr="=a", form="word", flag="提升（幅度未写明）"),
    _r("e_attr_word_down",
       r"(?P<a>攻击力|防御力|法术抗性|攻击速度|生命值)(?:大幅|显著|短暂)?"
       r"(?:降低|下降|减少)",
       "debuff", op="self", attr="=a", form="word", flag="降低（幅度未写明）"),

    # ================================================ 移动方式 / 嘲讽 / 蓄力
    _r("e_fly",
       r"(?:变为|成为|进入)?飞行(?:单位|状态|形态)?",
       "fly", op="self", form="word"),
    _r("e_taunt_level",
       rf"嘲讽(?:等级)?(?:提升|\+)?{_DNUM}",
       "taunt", op="self", scale=0, form="flat", attr="嘲讽等级"),
    _r("e_taunt_word",
       r"更容易受到攻击|更难被(?:我方)?(?:单位)?选中",
       "taunt", op="self", form="word", flag="嘲讽提升"),
    _r("e_channel",
       rf"(?:蓄力|吟唱|持续施法)(?:{_DNUM}s?)?",
       "channel", op="self", dur=0, form="word"),

    # ================================================ 触发条件 / 撤退 / 不攻击
    _r("e_hp_trigger",
       rf"生命值首次(?:低于|降至|降到|降为)(?:{_DNUM}{_FORMULA_PCT}|一半|{_DNUM})",
       "flag", op="self", scale=0, form="flat", note="生命值阈值触发"),
    _r("e_retreat_forced",
       r"强制退场",
       "flag", op="self", form="word", flag="强制退场"),
    _r("e_no_attack",
       r"(?:不进行|无法进行|不能|无法|不可)(?:普通)?攻击",
       "flag", op="self", form="word", flag="不进行普通攻击"),
    _r("e_steal_cost",
       rf"偷取我方{_DNUM}(?:点)?(?:费用|cost)",
       "cost", op="enemy", count=0, form="word"),

    # ================================================ 第二轮补充（长尾里成簇的家族）
    #
    # 补这批之前先把水位量了一遍：未覆盖的**去重**条目 873 条（非 desc），
    # 切开以后是 **1876 个互不相同的短句**，最高频的只有 20 次、多数 2–4 次。
    # 也就是说剩下的主体是**长尾**，不是「差几条规则」。所以这里只补
    # **成簇的家族**——同一机制反复出现、且措辞收敛的那几类。逐条去凑长尾
    # 等于手工录入，收益也不对：覆盖率的分子涨了，正确率不会涨。

    # ---- 阻挡门槛：把「谁能挡住我」写成数值门槛。三条是同一个家族。
    # 必须早于 `e_block_count`（那条读的是「阻挡数为N」= 自己占几格），
    # 否则「只能被阻挡数大于等于3的单位阻挡」会被读成它自己的阻挡数。
    _r("e_block_threshold",
       rf"只能被(?:守门员或)?阻挡数(?:大于等于|不小于|≥|>=){_DNUM}的单位阻挡",
       "block", op="self", attr="阻挡数门槛", scale=0, form="flat",
       note="只有阻挡数达标的单位能挡住它"),
    _r("e_block_occupy",
       rf"占用{_DNUM}个阻挡数",
       "block", op="self", scale=0, form="flat", attr="占用阻挡数"),

    # ---- 不可选中 / 不可沉默 / 不可对空。三个都是「否定式属性」，彼此独立。
    # `e_unattackable` 必须早于 `e_no_attack`：后者若把动词表放宽到「无法」，
    # 「无法被攻击」会被它先咬掉，读成「它不攻击」——**主语整个反了**。
    _r("e_unattackable",
       r"(?:无法|不可|不能)(?:被)?(?:攻击|选中)|无法被选择",
       "invincible", op="self", form="word", flag="不可被选中"),
    _r("e_silence_immune",
       r"(?:此技能)?(?:不可|无法|不会)(?:被)?沉默|免疫沉默",
       "immune", op="self", attr="沉默", form="word"),
    _r("e_no_air",
       r"(?:不可|无法|不能)(?:攻击)?(?:对)?空中|不可对空|无法攻击空中单位",
       "targets", op="self", form="word", flag="不能攻击空中单位"),

    # ---- 索敌
    _r("e_target_ignore_block",
       r"索敌不受阻挡影响|不受阻挡影响",
       "targets", op="self", form="word", flag="索敌不受阻挡影响"),
    _r("e_target_priority",
       r"优先攻击(?P<a>[^，。；、\n]{1,10})",
       "targets", op="self", attr="=a", form="word"),

    # ---- 元素损伤。**prts.wiki 手写的敌人正文不写数值**（「造成一定侵蚀损伤」），
    # 真值在敌人同档黑板上——所以这里只认种类、量纲记 word，
    # 与数值口径的干员侧 ep_damage 规则分工不同。
    _r("e_ep_damage",
       r"(?:额外)?造成(?:一定|少量|大量)?(?P<a>侵蚀|灼燃|凋亡|神经|水蚀|元素)(?:损伤|伤害)",
       "ep_damage", op="enemy", attr="=a", form="word",
       note="数值在同档黑板；正文只给种类"),
    _r("e_ep_damage_attack",
       r"攻击(?:时)?(?:额外)?(?:造成|附带)(?:一定)?(?P<a>侵蚀|灼燃|凋亡|神经|水蚀)"
       r"(?:损伤|伤害)",
       "ep_damage", op="enemy", attr="=a", form="word"),

    # ---- 生命流失 / 移动加速
    _r("e_lose_hp",
       r"(?:会)?(?:逐渐|持续|缓慢)(?:地)?(?:损失|失去|消耗)生命",
       "selfharm", op="self", form="word", flag="持续损失生命"),
    _r("e_speed_accel",
       r"移动时逐渐加速|逐渐加速|越走越快",
       "movespeed", op="self", form="word", flag="移动时逐渐加速"),

    # ---- 溅射与范围伤害。「溅射伤害」不一定带类型前缀（「造成伤害」），
    # 所以 dtype 的分组可空——**为空就是类型不明**，不要替它填「物理」。
    _r("e_splash_damage",
       r"(?P<a>物理|法术|真实)?溅射伤害",
       "damage", op="enemy", dtype="=a", form="word", note="溅射"),
    _r("e_around_damage",
       r"对(?:周围|目标及其周围)(?:四格内|范围内)?(?:的)?(?:所有)?(?:我方单位)?"
       r"造成(?P<a>物理|法术|真实)?(?:伤害)?",
       "damage", op="enemy", dtype="=a", form="word", note="范围伤害"),

    # ---- 漏掉不扣生命：与 `enemy_level.target_value` 相反的口径，
    # 直接影响三星判定，必须能查出来。
    _r("e_no_life_cost",
       r"(?:消失|退场|离场)时(?:并)?不会?扣除目标生命|不计入歼灭数|不扣除目标生命",
       "flag", op="self", form="word", flag="漏掉不扣生命"),
    _r("e_death_life_cost",
       r"死亡时扣除目标生命",
       "flag", op="self", form="word", flag="死亡时扣生命"),
)

#: 敌人侧完整规则表：**干员规则在前**。
#:
#: 干员那 130 条已经把"数值 + 量纲（PCT/RATIO/FLAT）+ 表达式成形"这套练熟了，
#: 敌人规则只该补它不认识的概念。反过来（敌人规则在前）会让
#: 「造成攻击力210%的法术伤害」被粗粒度的敌人规则先咬走，丢掉系数。
RULES_ENEMY: tuple[Rule, ...] = tuple(_formula.RULES) + ENEMY_RULES

#: 把敌人的 kind 中文标签并进共用表。`Term.label()` 只读这一个字典，
#: 加键是纯增量，不影响干员侧任何已有 kind。
_formula._LABEL.update(_ENEMY_LABELS)


# ---------------------------------------------------------------- 带变量的算式
#
# 见 `formula.py` 里「带变量的算式」那一段：`移动速度+(50%×加速层数)` 这类
# **不能按常数提取**——常数提取会把 50% 当成系数，得到 `ATK × 50%`，
# 表达式看着完全合理，实际意思是「**每层** 50%」。
#
# 这一层负责把算式**认到哪个属性/效果上**，方式是读算式最外层运算符的左操作数
# （`formula.Expr.lead`）与它前面的几个字。

#: 目标属性。`+`/`-` 时 lead 基本就是属性名；`×`/`/` 时 lead 可能只是算式里的
#: 一个因子（`当前移动速度×800` 是"以移速为系数算伤害"），故那种情况不当属性用。
#:
#: **收录口径（博士 2026-09-16 裁定）：只留战斗结算真正用得到的。**
#: 这不是"词表越全越好"——表越宽，把散文里的名词误认成属性名的机会越多。
#: 没进表的一律留空（`kind=formula`、`attr=""`），算式与变量照旧保留给人看。
#: 判据是「模拟器会不会因为这个量而改变结算」：
#:
#: * 进表：阻挡/移速/攻防/攻速/攻免/重量/生命/再部署/费用/优先级/嘲讽——
#:   这十来个量直接决定出手、命中、伤害与部署；
#: * 不进表：范围、视野、半径、角度、计数、阈值——要么是派生量，
#:   要么根本没进结算，收进来只是噪声。
_EXPR_ATTR: tuple[tuple[str, str, str], ...] = (
    ("移动速度", "movespeed", "移动速度"),
    ("攻击速度", "buff", "攻击速度"),
    ("攻击间隔", "buff", "攻击间隔"),
    ("攻击力", "buff", "攻击力"),
    ("防御力", "buff", "防御力"),
    ("法术抗性", "buff", "法术抗性"),
    ("生命值", "buff", "生命值"),
    ("最大生命值", "buff", "生命值"),
    ("阻挡数", "block", "阻挡数"),
    ("重量", "buff", "重量"),
    ("闪避", "dodge", "闪避"),
    ("减伤", "buff", "减伤"),
    # —— 以下为 2026-09-16 按「战斗结算有用」新增 ——
    ("技能优先级", "buff", "技能优先级"),
    ("优先级", "buff", "技能优先级"),
    ("嘲讽等级", "taunt", "嘲讽等级"),
    ("攻击距离", "buff", "攻击距离"),
    ("攻击半径", "buff", "攻击距离"),
    ("攻击范围半径", "buff", "攻击距离"),
    ("目标影响半径", "buff", "攻击距离"),
    ("速度倍率", "buff", "速度倍率"),
    ("速度", "movespeed", "移动速度"),          # 裸「速度」在本语料里都指移速
    ("可抵抗状态生效时间倍率", "buff", "状态生效时间倍率"),
    ("退场时本次再部署时间", "buff", "再部署时间"),
    ("再部署时间", "buff", "再部署时间"),
    ("部署费用", "buff", "部署费用"),
    ("我方费用上限", "buff", "费用上限"),
    ("SP", "buff", "SP"),
    # 怀黍离（sidesstory）的田地病害值、红丝绒的摄影区域/飞行速度：博士裁定保留
    ("田地地块病害值", "buff", "田地病害值"),
    ("地块病害值", "buff", "田地病害值"),
    ("飞行速度", "movespeed", "飞行速度"),
    # 作用于**我方**的减阻挡（`短暂使我方干员阻挡-1`）
    ("我方干员阻挡", "block", "阻挡数"),
)

#: lead 前面的修饰语，剥掉之后才好与 `_EXPR_ATTR` 对上。
#:
#: **`当前` / `当前的` 刻意不在表里**：`当前移动速度×800` 是「以移速为系数
#: 算伤害」，写的是「移速的**当前值**」——那是算式里的一个量，不是被改的属性。
#: 剥掉它就会把这条误记成「改移速」，表达式还看着对。
_EXPR_PREFIX = ("使其", "使自身", "使", "自身的", "自身", "其")

#: lead 为空时，往算式**前面**看这几个词来定 kind。
_EXPR_BEFORE: tuple[tuple[str, str, str], ...] = (
    ("每秒受到", "dot", ""),
    ("每秒", "dot", ""),
    ("受到", "dot", ""),
    ("造成", "damage", ""),
    ("闪避", "dodge", "闪避"),
)

#: 「…提升至(算式)」这种写法：算式紧跟在「提升至」后面，属性在更前面。
_EXPR_SET_TO = re.compile(r"(提升|提高|增加|上升|降低|下降|减少|变更为|变为)至?$")

#: `+`/`-` 的属性增益/减益翻转：这些 kind 在减号下要变成对立面。
_DOWN_KINDS = {"buff": "debuff", "movespeed": "debuff_ms_down"}


def _strip_prefix(word: str) -> str:
    for p in _EXPR_PREFIX:
        if word.startswith(p) and len(word) > len(p):
            return word[len(p):]
    return word


def _split_lead(ex: Any) -> tuple[str, str, list[str]]:
    """把算式拆成 `(lead, 值算式, 值表达式依赖的变量)`。

    `自身移动速度+(50%×加速层数)` → `("自身移动速度", "(50%×加速层数)", ["加速层数"])`。
    lead 是**最外层运算符的左操作数**，由解析器记下；拆开之后才知道
    「哪些是属性名、哪些是算式真正依赖的变量」。
    """
    lead = ex.lead or ""
    value = ex.text
    if lead:
        value = ex.text[len(lead) + len(ex.sign):]
    stripped = _strip_prefix(lead) if lead else ""
    vars_ = [v for v in ex.vars if v != lead and _strip_prefix(v) != stripped]
    return lead, value, vars_


def _expr_kind(ex: Any, lead: str, value_vars: list[str],
               flat: str, start: int) -> tuple[str, str, str, str]:
    """把一段算式认到 `(kind, attr, op, 附注)` 上；认不出就是 `("formula", "", "", "")`。

    **宁可留白也不猜**：认不出属性时 `attr` 留空、kind 记 `formula`，
    表达式与变量照旧保留，读的人自己看 `context`。
    """
    stripped = _strip_prefix(lead) if lead else ""
    # `当前X` 是「X 的当前值」，是算式里的一个量，不是被改的属性——
    # `当前移动速度×800` 是「以移速为系数算伤害」。剥 `当前` 会把这条误记成
    # 「改移速」，而表达式还看着对。
    if stripped.startswith("当前"):
        stripped = ""
    # `×` 也算属性，但**只在右边没有变量时**：`阻挡数×0` = 阻挡数归零；
    # 而 `移动速度×加速层数` 是拿两个量算一个值，不是改属性。
    attr_ok = ex.sign in ("+", "×") or (ex.sign == "-") or (
        ex.sign == "/" and not value_vars and _has_attr(stripped))
    if ex.sign == "×" and value_vars:
        attr_ok = False
    # `防御力/法术抗性最终×0`：外层算子是 `/`，可这里的斜杠是**并列**不是除法。
    # 博士裁定原话：「在计算防御力和法术抗性时在算式最末尾乘 0」，即两侧都归零。
    # 判据取严：**两侧都以属性名开头**才算并列。只判「右侧含属性名」不够——
    # `攻击力/已处理目标数量/待处理目标总数量×100%` 的右侧也含别的东西，
    # 那种要按普通除法留着（它的幅度由切段重试那条路径接住）。
    if ex.sign == "/" and lead:
        # 右值不在入参里（只有 value_vars），从完整算式文本里按第一个 `/` 切出来。
        _pos = ex.text.find("/")
        _right = _strip_prefix(ex.text[_pos + 1:]) if _pos >= 0 else ""
        la = _attr_of(lead)
        ra = ""
        for word, _k, attr in _EXPR_ATTR:
            if _right.startswith(word):
                ra = attr
                break
        if la and ra and ra != la:
            return "debuff", f"{la}/{ra}", "self", "（并列，非除法）"
    if stripped and attr_ok:
        # 与下面 `_EXPR_SET_TO` 那段同一口径：一个 lead 里可能**并列**出现多个
        # 属性名（`防御力/法术抗性最终×0`）。博士裁定这里的斜杠是并列——
        # 「在计算防御力和法术抗性时在算式最末尾乘 0」，两侧都归零。
        # 只取表序第一个会把 `法术抗性` 整条丢掉。
        hits: list[tuple[int, str, str]] = []
        for word, kind, attr in _EXPR_ATTR:
            i = stripped.find(word)
            if i >= 0 and all(a != attr for _, a, _ in hits):
                hits.append((i, attr, kind))
        if hits:
            hits.sort()
            kind = hits[0][2]
            if ex.sign == "-" and kind in _DOWN_KINDS:
                kind = _DOWN_KINDS[kind]
            # `使其阻挡数…` = 作用于**我方**；其余默认作用于它自己
            op = "enemy" if lead.startswith(("使其", "使")) else "self"
            extra = "（乘算）" if ex.sign == "×" else ""
            return kind, "/".join(a for _, a, _ in hits), op, extra
    before = flat[max(0, start - 8):start]
    for word, kind, attr in _EXPR_BEFORE:
        if word in before:
            return kind, attr, "self", ""
    # 「移动速度最终提升至(100%+增益层数×25%)」：算式前面的「提升至」把属性
    # 和值隔开了，往更远处找属性名，用提升/降低定方向。
    wide = flat[max(0, start - 20):start]
    m = _EXPR_SET_TO.search(wide)
    if m is not None:
        down = m.group(1) in ("降低", "下降", "减少")
        # 回看段里可能**同时**出现多个属性名（`攻击力/防御力降低至…`）。
        # 博士裁定这里的斜杠是**并列**——「防御力和法术抗性都归零」那种含义，
        # 不是除法。原先按表序取第一个命中的，于是 `攻击力/防御力` 只记成
        # `攻击力`：**另一侧的幅度就丢了**，而且看起来还挺合理。
        # 现在按出现位置把命中的属性全收下来、用 `/` 连起来。
        head = wide[:m.start()]
        found: list[tuple[int, str, str]] = []
        for word, kind, attr in _EXPR_ATTR:
            i = head.find(word)
            if i >= 0 and all(a != attr for _, a, _ in found):
                found.append((i, attr, kind))
        if found:
            found.sort()
            kind = found[0][2]
            if down and kind in _DOWN_KINDS:
                kind = _DOWN_KINDS[kind]
            return kind, "/".join(a for _, a, _ in found), "self", ""
    # 整段被**一层括号**包住的算式（`(优先级-3000)`）最外层没有运算符，
    # `_maybe_lead` 一次也不会被调用，于是 lead 为空、`优先级` 掉进 vars 里。
    # 这种情况**不能靠"剥一层括号再解析"解决**——`(层数×300)` 同样被包住，
    # 而 `层数` 是真变量，剥了就会把它误认成属性（试过，测试立刻红）。
    # 唯一站得住的判据是「这个名字在不在属性表里」，而属性表在这一层，
    # 所以兜底补在这里，不在通用解析器里。
    if not lead and len(ex.vars) == 1:
        word = _strip_prefix(ex.vars[0])
        for w, kind, attr in _EXPR_ATTR:
            if w in word:
                if ex.sign == "-" and kind in _DOWN_KINDS:
                    kind = _DOWN_KINDS[kind]
                return kind, attr, "self", "（乘算）" if ex.sign == "×" else ""
    return "formula", "", "", ""


def _attr_of(word: str) -> str:
    """这个变量名对应哪个属性；不在属性表里就返回空串。"""
    w = _strip_prefix(word)
    for token, _kind, attr in _EXPR_ATTR:
        if token in w:
            return attr
    return ""


def _has_attr(word: str) -> bool:
    return any(w in word for w, _, _ in _EXPR_ATTR)


def expr_terms(flat: str, used: list[tuple[int, int]]) -> list[Any]:
    """`formula.parse` 的 `extra` 钩子：把**带变量的算式**收成公式项。

    约定是只处理与 `used` 不相交的文字——已经被规则咬走的片段（例如
    `移动速度+110%` 会被 `e_movespeed_up` 正常收走）不再重复出一项。
    """
    out: list[Any] = []
    for s, e, ex in _formula.find_exprs(flat):
        if any(s < ue and us < e for us, ue in used):
            # 算式**跨过了**规则已咬走的一段时不整条放弃，而是把那一刀切掉再试。
            #
            # 博士裁定「不保留自然语言，写成算式」对应的正是这一类：
            # `攻击力/防御力降低至已处理目标数量/待处理目标总数量×100%` 里，
            # 规则只收走 `防御力降低` 并留下「降低（幅度未写明）」，
            # 而算式从 `攻击力` 起算、整条与它重叠 → 原先直接 continue，
            # **幅度就丢在正文里了**。切到 `至` 之后重新找，就能拿回
            # `已处理目标数量/待处理目标总数量×100%`。
            # 注意只切一次、只取切后**第一个**结果：这里是补漏，不是扩张。
            cut = max(ue for us_, ue in used if s < ue and us_ < e)
            retry = _formula.find_exprs(flat[cut:e])
            if not retry:
                continue
            rs, re_, rex = retry[0]
            s, e, ex = cut + rs, cut + re_, rex
        lead, value, vars_ = _split_lead(ex)
        kind, attr, op, extra = _expr_kind(ex, lead, vars_, flat, s)
        # `_split_lead` 把 lead 从变量里摘了出来——**只有当 lead 真的被当作属性时**
        # 才能摘。认不出属性时 lead 就是算式依赖的那个量（`当前移动速度×800`），
        # 摘掉就等于把这条算式唯一的变量扔了。
        if not attr:
            vars_ = list(ex.vars)
        elif not lead:
            # 属性是从 vars 里认出来的（上面那条括号兜底）→ 把它从 vars 摘掉，
            # 否则同一个词既当属性又当变量，读的人会以为算式还额外依赖它。
            vars_ = [v for v in vars_ if _attr_of(v) != attr]
        if not vars_ and not attr:
            # 既认不出属性、也没剩下变量——那它根本不是「带变量的算式」，
            # 只是一个被斜杠/乘号切出来的裸数值（如 `…数量×100%` 尾巴上的 100%）。
            # 出一项只会是噪声，丢掉。
            continue
        note = "带变量的算式，编译期不求值"
        if ex.pct:
            note += "（整体为百分比）"
        out.append(_formula.Term(
            kind=kind,
            expr=value,
            op=op,
            attr=attr,
            source="expr_var",
            evidence=flat[s:e],
            context=flat[max(0, s - 18):s],
            formula=ex.text,
            vars=vars_,
            note=note + extra,
            pos=s,
        ))
    return out


def parse_enemy(text: str, blackboard: dict[str, Any] | None = None) -> list[Any]:
    """把一条敌人正文解析成公式项。

    与 `formula.parse` 的区别只有两处：规则表是 `RULES_ENEMY`，
    以及额外挂了一个 `expr_terms` 钩子收「带变量的算式」。
    解析器本身完全共用（文本规范化、量纲判定、区间消费、表达式成形都不另写）。
    """
    return _formula.parse(text, blackboard, rules=RULES_ENEMY,
                          extra=expr_terms)


def formulas_enemy(text: str, blackboard: dict[str, Any] | None = None,
                   *, name: str = "") -> dict[str, str]:
    """解析并渲染成 `{公式名: 表达式}`，供 battle 层直接取用。"""
    return _formula.formulas(parse_enemy(text, blackboard), name=name)


# ---------------------------------------------------------------- 单页编译

def enemy_formulas(db: Path | str, key: str) -> dict[str, Any]:
    """取一个敌人的全部正文并编译成公式项。

    返回 `{"page", "name", "sections": [...]}`，每节含
    `source`（ability / ability_fixed / talent / desc / skill）、
    `level` 或 `skill`、`text`（原文）、`flat`（洗净后的文本）、
    `terms`（公式项列表）。

    与 `enemy_scan` 的区别：那个是**统计全库**，这个是**给一个敌人出报告**。
    """
    conn = sqlite3.connect(f"file:{Path(db).as_posix()}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cand = conn.execute(
            "SELECT page, name FROM enemy WHERE page = ? OR name = ? "
            "OR name LIKE ? ORDER BY (page = ?) DESC, (name = ?) DESC LIMIT 5",
            (key, key, f"%{key}%", key, key)).fetchall()
        if not cand:
            raise KeyError(f"敌人库里没有「{key}」")
        page, name = cand[0]["page"], cand[0]["name"]
        sections: list[dict[str, Any]] = []

        def add(source: str, text: str | None, bb: Any,
                level: int | None = None, skill: str = "") -> None:
            if not text or not text.strip():
                return
            flat = detemplate(text)
            sections.append({
                "source": source, "level": level, "skill": skill,
                "text": text, "flat": flat,
                "terms": parse_enemy(flat, _bb(bb)),
            })

        e = conn.execute("SELECT * FROM enemy WHERE page = ?", (page,)).fetchone()
        if e is not None:
            add("ability", e["ability"], None)
            if "ability_fixed" in e.keys():
                add("ability_fixed", e["ability_fixed"], None)

        lv_bb: dict[int, dict[str, Any]] = {}
        for r in conn.execute(
                "SELECT * FROM enemy_level WHERE page = ? ORDER BY level", (page,)):
            bb = _bb(r["blackboard"])
            lv_bb[r["level"]] = bb
            add("talent", r["talent"], bb, level=r["level"])
            desc = r["description"]
            if "description_fixed" in r.keys() and r["description_fixed"]:
                desc = r["description_fixed"]
            add("desc", desc, bb, level=r["level"])

        # 敌方技能的正文列叫 `effect`（不是 description），黑板取**同档**的，
        # 与 `load_enemy_corpus` 的口径保持一致——否则同一句话两处解析出不同结果。
        for r in conn.execute(
                "SELECT * FROM enemy_skill WHERE page = ? ORDER BY level, slot",
                (page,)):
            add("skill", r["effect"], lv_bb.get(r["level"], {}),
                level=r["level"], skill=r["name"] or f"技能{r['slot'] + 1}")
        return {"page": page, "name": name, "sections": sections,
                "candidates": [dict(c) for c in cand]}
    finally:
        conn.close()


# ---------------------------------------------------------------- 基线扫描

def enemy_scan(db: Path | str, *, rules: Iterable | None = None,
               top: int = 20) -> dict[str, Any]:
    """跑一遍全量语料，统计命中率与规则使用频次。

    `rules` 默认是**敌人完整规则表**（干员 130 条 + 敌人规则），此时
    与 `parse_enemy` 逐条等价（含 `expr_terms` 那个算式钩子）。传
    `formula.RULES` 可单独看"只靠干员规则能覆盖多少"——这是衡量敌人规则
    到底补了多少的基准线，**基准线不挂算式钩子**（那是敌人侧自己的追加，
    挂上就不再是"只靠干员规则"了）。
    """
    from . import formula

    use = RULES_ENEMY if rules is None else rules
    extra = expr_terms if rules is None else None
    corpus = load_enemy_corpus(db)
    by_source: dict[str, list[int]] = {}
    terms: dict[str, int] = {}
    misses: dict[str, list[str]] = {}
    for row in corpus:
        flat = detemplate(row["text"])
        got = formula.parse(flat, row["blackboard"], rules=use, extra=extra)
        hit, tot = by_source.setdefault(row["source"], [0, 0])
        by_source[row["source"]] = [hit + (1 if got else 0), tot + 1]
        for t in got:
            terms[t.source] = terms.get(t.source, 0) + 1
        if not got:
            misses.setdefault(row["source"], []).append(flat)
    return {
        "rows": len(corpus),
        "hit_rows": sum(v[0] for v in by_source.values()),
        "by_source": {k: {"hit": v[0], "total": v[1]} for k, v in by_source.items()},
        "top_rules": sorted(terms.items(), key=lambda kv: -kv[1])[:top],
        "misses": misses,
    }
