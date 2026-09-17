"""干员数据的解析：wikitext 模板 → 结构化对象。

一个干员页面由固定几个模板拼成，各司其职：

| 模板 | 拿到什么 |
| --- | --- |
| `CharinfoV2` | 名字、稀有度、职业、分支、标签、特性、画师、配音 |
| `干员获得方式` | 上线时间、获取途径 |
| `属性` | 再部署、费用、阻挡、攻击间隔、各精英阶段四维、信赖、潜能、模组增量 |
| `干员攻击范围` | 三个精英阶段各自的攻击范围代号（如 `3-3`） |
| `天赋列表3` | 每个天赋的各阶段效果（含模组强化与潜能增强） |
| `技能` / `技能2` | 每个技能的 7 级 + 3 专精：描述、初始 SP、消耗 SP、持续 |
| `潜能提升` | 潜能 2–6 各提升什么 |
| `模组` | 每个模组的四维增量、特性追加、天赋改写 |

数值只解析**模板参数**，不去猜描述里的自然语言——描述原文原样保留，
结构化留到"效果解析"阶段（见 README 的任务拆分）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .client import PrtsClient, default_client
from .wikitext import (
    find_templates,
    parse_params,
    render,
    render_flat,
    split_multi,
    to_number,
)

#: 精英阶段的档位，"精英2_满级_攻击" 这类键由它拼出来。
ELITE_STAGES = (0, 1, 2)

STAT_KEYS = {
    "生命上限": "hp",
    "攻击": "atk",
    "防御": "defense",
    "法术抗性": "res",
}

MODULE_STAT_KEYS = {
    "生命": "hp",
    "攻击": "atk",
    "防御": "defense",
    "法术抗性": "res",
}

_COND_ELITE_RE = re.compile(r"精英\s*([012])")
_COND_LEVEL_RE = re.compile(r"(\d+)\s*级")
_MODULE_COND_RE = re.compile(r"([XY])\s*模组\s*(\d+)\s*级", re.IGNORECASE)


class OperatorNotFound(LookupError):
    """页面上没有这个干员。"""


class OperatorParseError(ValueError):
    """页面存在，但结构不是我们认识的干员页。"""


# ----------------------------------------------------------------- 数据模型

@dataclass
class Stats:
    """某一精英阶段某一等级的裸数值（不含信赖、潜能、模组）。"""

    elite: int
    level: int
    hp: int | None = None
    atk: int | None = None
    defense: int | None = None
    res: int | None = None

    @property
    def label(self) -> str:
        return f"精英{self.elite} {self.level}级"

    def to_dict(self) -> dict:
        return {"elite": self.elite, "level": self.level, "hp": self.hp,
                "atk": self.atk, "defense": self.defense, "res": self.res}


@dataclass
class Talent:
    """一个天赋。`stages` 里是它的各版本（精英阶段 / 模组强化）。"""

    slot: str                      # 第一天赋 / 第二天赋
    name: str = ""
    stages: list[dict[str, Any]] = field(default_factory=list)
    potentials: list[dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def to_dict(self) -> dict:
        return {"slot": self.slot, "name": self.name,
                "stages": self.stages, "potential_boost": self.potentials,
                "note": self.note}


@dataclass
class SkillLevel:
    """一个技能的一个等级。`level` 1–7 为常规，8–10 为专精一/二/三。"""

    level: int
    description: str = ""
    sp_init: float | None = None
    sp_cost: float | None = None
    duration: float | None = None

    @property
    def label(self) -> str:
        return f"专精{self.level - 7}" if self.level > 7 else str(self.level)

    @property
    def numbers(self) -> list[float]:
        """描述里出现的全部数字——后续做效果结构化时的第一手线索。"""
        return [float(m) for m in re.findall(r"-?\d+(?:\.\d+)?", self.description)]

    def to_dict(self) -> dict:
        return {"level": self.level, "label": self.label,
                "description": self.description, "sp_init": self.sp_init,
                "sp_cost": self.sp_cost, "duration": self.duration}


@dataclass
class Skill:
    index: int
    name: str = ""
    name_en: str = ""
    recovery: str = ""            # 自动回复 / 攻击回复 / 受击回复
    trigger: str = ""             # 手动触发 / 自动触发 / 被动
    unlock: str = ""              # 精英0开放 / 精英1开放 / 精英2开放
    levels: list[SkillLevel] = field(default_factory=list)

    def level(self, n: int) -> SkillLevel | None:
        for lv in self.levels:
            if lv.level == n:
                return lv
        return None

    def to_dict(self) -> dict:
        return {"index": self.index, "name": self.name, "name_en": self.name_en,
                "recovery": self.recovery, "trigger": self.trigger,
                "unlock": self.unlock,
                "levels": [lv.to_dict() for lv in self.levels]}


@dataclass
class Module:
    name: str = ""
    kind: str = ""                # 证章 / MAR-X / MAR-Y …
    is_badge: bool = False        # 是否是基础证章（无属性加成）
    stats: list[dict[str, Any]] = field(default_factory=list)   # 1/2/3 级增量
    trait_addon: str = ""
    talent_updates: list[str] = field(default_factory=list)
    unlock_level: int | None = None
    unlock_trust: list[int] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"name": self.name, "kind": self.kind, "is_badge": self.is_badge,
                "stats": self.stats, "trait_addon": self.trait_addon,
                "talent_updates": self.talent_updates,
                "unlock_level": self.unlock_level,
                "unlock_trust": self.unlock_trust}


@dataclass
class Operator:
    name: str
    name_en: str = ""
    name_jp: str = ""
    char_id: str = ""
    index: int | None = None
    rarity: int = 0
    profession: str = ""
    branch: str = ""
    position: str = ""
    tags: list[str] = field(default_factory=list)
    trait: str = ""               # 特性
    info_no: str = ""
    nation: str = ""
    org: str = ""
    team: str = ""
    artists: list[str] = field(default_factory=list)
    voice_actors: list[str] = field(default_factory=list)
    obtain: list[str] = field(default_factory=list)
    release_time: str = ""
    redeploy: str = ""
    cost: str = ""
    block: int | None = None
    attack_interval: float | None = None
    factions: list[str] = field(default_factory=list)
    hidden_factions: list[str] = field(default_factory=list)
    stats: list[Stats] = field(default_factory=list)
    trust_bonus: dict[str, int] = field(default_factory=dict)
    potentials: list[str] = field(default_factory=list)
    potential_effects: dict[str, str] = field(default_factory=dict)
    range_codes: dict[str, str] = field(default_factory=dict)
    talents: list[Talent] = field(default_factory=list)
    skills: list[Skill] = field(default_factory=list)
    modules: list[Module] = field(default_factory=list)
    logistics: list[dict[str, str]] = field(default_factory=list)
    raw_url: str = ""

    # ------------------------------------------------------------ 便捷访问

    def stat_at(self, elite: int, level: int) -> Stats | None:
        for s in self.stats:
            if s.elite == elite and s.level == level:
                return s
        return None

    def max_stat(self) -> Stats | None:
        """最高精英阶段的满级数值。"""
        best: Stats | None = None
        for s in self.stats:
            if s.level < 0:      # 等级上限标记不走这里
                continue
            if best is None or (s.elite, s.level) > (best.elite, best.level):
                best = s
        return best

    def summary(self) -> str:
        lines = [
            f"{self.name}（{self.name_en}）  ★{self.rarity}  {self.profession}·{self.branch}",
            f"  特性：{self.trait or '—'}",
            f"  再部署 {self.redeploy or '—'} / 费用 {self.cost or '—'} / "
            f"阻挡 {self.block if self.block is not None else '—'} / "
            f"攻击间隔 {self.attack_interval if self.attack_interval is not None else '—'}s",
        ]
        for s in sorted(self.stats, key=lambda x: (x.elite, x.level)):
            lines.append(
                f"  {s.label:12s} HP {_fmt(s.hp):>5s}  ATK {_fmt(s.atk):>5s}  "
                f"DEF {_fmt(s.defense):>5s}  RES {_fmt(s.res):>4s}")
        if self.trust_bonus:
            tb = "  ".join(f"{k}+{v}" for k, v in self.trust_bonus.items() if v)
            if tb:
                lines.append(f"  信赖加成：{tb}")
        for t in self.talents:
            lines.append(f"  {t.slot}：{t.name}")
            for st in t.stages:
                lines.append(f"      [{st.get('condition') or '基础'}] {st.get('effect')}")
        for sk in self.skills:
            lv7 = sk.level(7)
            lines.append(f"  技能{sk.index}「{sk.name}」({sk.recovery}/{sk.trigger}, "
                         f"{sk.unlock or '—'})")
            if lv7:
                lines.append(f"      7级：{lv7.description}  "
                             f"[SP {_fmt(lv7.sp_init)}/{_fmt(lv7.sp_cost)}"
                             + (f" 持续 {_fmt(lv7.duration)}s]" if lv7.duration else "]"))
        if self.modules:
            lines.append("  模组：" + "、".join(m.name for m in self.modules))
        if self.range_codes:
            lines.append("  攻击范围：" + "  ".join(
                f"精英{k[-1]}={v}" for k, v in sorted(self.range_codes.items())))
        return "\n".join(lines)

    def to_dict(self, *, include_raw_url: bool = True) -> dict:
        d: dict[str, Any] = {
            "name": self.name,
            "name_en": self.name_en,
            "name_jp": self.name_jp,
            "char_id": self.char_id,
            "index": self.index,
            "rarity": self.rarity,
            "profession": self.profession,
            "branch": self.branch,
            "position": self.position,
            "tags": self.tags,
            "trait": self.trait,
            "info_no": self.info_no,
            "nation": self.nation,
            "org": self.org,
            "team": self.team,
            "artists": self.artists,
            "voice_actors": self.voice_actors,
            "obtain": self.obtain,
            "release_time": self.release_time,
            "redeploy": self.redeploy,
            "cost": self.cost,
            "block": self.block,
            "attack_interval": self.attack_interval,
            "factions": self.factions,
            "hidden_factions": self.hidden_factions,
            "stats": [s.to_dict() for s in self.stats],
            "trust_bonus": self.trust_bonus,
            "potentials": self.potentials,
            "potential_effects": self.potential_effects,
            "range_codes": self.range_codes,
            "talents": [t.to_dict() for t in self.talents],
            "skills": [s.to_dict() for s in self.skills],
            "modules": [m.to_dict() for m in self.modules],
            "logistics": self.logistics,
        }
        if include_raw_url and self.raw_url:
            d["source"] = self.raw_url
        return d


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)


# ------------------------------------------------------------------- 解析

def _params_of(wikitext: str, name: str) -> list[dict[str, str]]:
    """取出页面里所有名为 name 的顶层模板的命名参数字典。"""
    out = []
    for inner in find_templates(wikitext, name):
        _, named, _ = parse_params(inner)
        out.append(named)
    return out


def _params_strict(wikitext: str, name: str) -> list[tuple[dict[str, str], dict[str, str]]]:
    """同上，但同时返回位置参数（`技能` 模板的开放式标签靠它）。"""
    out = []
    for inner in find_templates(wikitext, name):
        _, named, positional = parse_params(inner)
        out.append((named, positional))
    return out


def _num(v: str | None) -> int | None:
    if v is None:
        return None
    n = to_number(v)
    return int(n) if isinstance(n, (int, float)) else None


def parse_operator(wikitext: str, *, name: str = "") -> Operator:
    """把一份干员页面 wikitext 解析成 Operator。"""
    charinfo = _params_of(wikitext, "CharinfoV2")
    if not charinfo:
        raise OperatorParseError("页面上没有 {{CharinfoV2}}，这大概不是干员页")
    ci = charinfo[0]

    op = Operator(name=name or render_flat(ci.get("干员名", "")))
    op.name_en = render_flat(ci.get("干员外文名", ""))
    op.name_jp = render_flat(ci.get("干员名jp", ""))
    op.char_id = render_flat(ci.get("干员id", ""))
    op.index = _num(ci.get("干员序号"))
    # 页面上的「稀有度」是 0 起算的（0=一星 … 5=六星），对外统一成真实星级。
    op.rarity = (_num(ci.get("稀有度")) or 0) + 1
    op.profession = render_flat(ci.get("职业", ""))
    op.branch = render_flat(ci.get("分支", ""))
    op.position = render_flat(ci.get("位置", ""))
    op.tags = split_multi(render_flat(ci.get("标签", "")))
    op.trait = render_flat(ci.get("特性", ""))
    op.info_no = render_flat(ci.get("情报编号", ""))
    op.nation = render_flat(ci.get("所属国家", ""))
    op.org = render_flat(ci.get("所属组织", ""))
    op.team = render_flat(ci.get("所属团队", ""))
    op.artists = split_multi(render_flat(ci.get("画师", "")))
    for lang in ("中文配音", "日文配音", "韩文配音", "英文配音"):
        va = render_flat(ci.get(lang, ""))
        if va:
            op.voice_actors.append(va)

    # 获得方式
    for obtain in _params_of(wikitext, "干员获得方式"):
        way = render_flat(obtain.get("获得方式", ""))
        op.obtain.extend(split_multi(way, " 　"))
        op.release_time = render_flat(obtain.get("上线时间", ""))

    # 属性
    attrs = _params_of(wikitext, "属性")
    if attrs:
        at = attrs[0]
        op.redeploy = render_flat(at.get("再部署", ""))
        op.cost = render_flat(at.get("部署费用", ""))
        op.block = _num(at.get("阻挡数"))
        interval = to_number(render_flat(at.get("攻击速度", "")))
        op.attack_interval = float(interval) if interval is not None else None
        op.factions = split_multi(render_flat(at.get("所属势力", "")))
        op.hidden_factions = split_multi(render_flat(at.get("隐藏势力", "")))
        op.stats = _parse_stats(at)
        op.trust_bonus = {
            field_name: (_num(at.get(f"信赖加成_{cn}")) or 0)
            for cn, field_name in STAT_KEYS.items()
            if at.get(f"信赖加成_{cn}") is not None
        }
        op.potentials = split_multi(at.get("潜能", ""), ",")

    # 攻击范围
    for rng in _params_of(wikitext, "干员攻击范围"):
        for elite in ELITE_STAGES:
            code = render_flat(rng.get(f"精英{elite}范围", ""))
            if code:
                op.range_codes[f"elite{elite}"] = code

    # 天赋
    op.talents = _parse_talents(wikitext)

    # 技能
    op.skills = _parse_skills(wikitext)

    # 潜能提升
    for pot in _params_of(wikitext, "潜能提升"):
        for i in range(2, 7):
            eff = render_flat(pot.get(f"潜能{i}", ""))
            if eff:
                op.potential_effects[f"潜能{i}"] = eff

    # 模组
    op.modules = _parse_modules(wikitext)

    # 后勤技能
    for log in _params_of(wikitext, "后勤技能"):
        for i in ("1", "2", "3"):
            skill_name = render_flat(log.get(f"后勤技能{i}-1", ""))
            if not skill_name:
                continue
            op.logistics.append({
                "name": skill_name,
                "stage": render_flat(log.get(f"后勤技能{i}-1阶段", "")),
            })
            upgraded = render_flat(log.get(f"后勤技能{i}-2", ""))
            if upgraded:
                op.logistics.append({
                    "name": upgraded,
                    "stage": render_flat(log.get(f"后勤技能{i}-2阶段", "")),
                })

    return op


def _parse_stats(at: dict[str, str]) -> list[Stats]:
    """从 `{{属性}}` 的参数里抽出各精英阶段的四维。

    页面里给的是「精英N_1级」和「精英N_满级」，其中 `精英N_满级` 单键
    存的是该阶段的**等级上限**（如 50 / 80 / 90）。
    """
    caps: dict[int, int] = {}
    for elite in ELITE_STAGES:
        cap = _num(at.get(f"精英{elite}_满级"))
        if cap:
            caps[elite] = cap

    out: list[Stats] = []
    for elite in ELITE_STAGES:
        for tier, level in (("1级", 1), ("满级", caps.get(elite, 0))):
            s = Stats(elite=elite, level=level)
            any_value = False
            for cn, field_name in STAT_KEYS.items():
                raw = at.get(f"精英{elite}_{tier}_{cn}")
                if raw is not None:
                    setattr(s, field_name, _num(raw))
                    any_value = True
            if any_value:
                out.append(s)
    return out


def _parse_talents(wikitext: str) -> list[Talent]:
    talents: list[Talent] = []
    for named, _ in _params_strict(wikitext, "天赋列表3"):
        slot = render_flat(named.get("天赋", "")) or "天赋"
        t = Talent(slot=slot)
        enhanced = named.get("潜能增强")
        for i in range(1, 8):
            effect_key = f"天赋{i}效果"
            name_key = f"天赋{i}"
            if name_key not in named and effect_key not in named:
                continue
            t.name = t.name or render_flat(named.get(name_key, ""))
            condition = render_flat(named.get(f"天赋{i}条件", ""))
            effect = render_flat(named.get(effect_key, ""))
            if effect:
                t.stages.append({
                    "condition": condition,
                    "effect": effect,
                    **_condition_meta(condition),
                })
            # 潜能增强版
            pot_effect = named.get(f"潜能增强_{effect_key}")
            if pot_effect:
                t.potentials.append({
                    "condition": render_flat(named.get(f"潜能增强_天赋{i}条件", condition)),
                    "effect": render_flat(pot_effect),
                })
        t.note = render_flat(named.get("备注", ""))
        if enhanced:
            t.note = t.note or f"潜能{render_flat(enhanced)}增强"
        talents.append(t)
    return talents


def _condition_meta(condition: str) -> dict[str, Any]:
    """把 "精英2 Y模组3级" 这类条件拆成结构化字段。"""
    meta: dict[str, Any] = {}
    m = _COND_ELITE_RE.search(condition)
    if m:
        meta["elite"] = int(m.group(1))
    m = _MODULE_COND_RE.search(condition)
    if m:
        meta["module"] = m.group(1).upper()
        meta["module_level"] = int(m.group(2))
    else:
        m = _COND_LEVEL_RE.search(condition)
        if m:
            meta["level"] = int(m.group(1))
    return meta


_SKILL_LEVEL_SUFFIXES: list[tuple[str, int]] = [
    ("技能专精3", 10), ("技能专精2", 9), ("技能专精1", 8),
    ("技能7", 7), ("技能6", 6), ("技能5", 5), ("技能4", 4),
    ("技能3", 3), ("技能2", 2), ("技能1", 1),
]


def _parse_skills(wikitext: str) -> list[Skill]:
    """解析技能。

    prts.wiki 用两个模板名：`{{技能}}` 和 `{{技能2}}`（后者多几个参数，如技能范围），
    但字段命名一致。技能所属的开放条件写在模板**之前**的一行粗体里，
    形如 `'''技能1（精英0开放）'''`，所以这里按出现顺序把两者对齐。
    """
    skills: list[Skill] = []
    unlock_map = _skill_unlock_map(wikitext)

    hits: list[tuple[int, str, str]] = []   # (位置, 模板名, 内部片段)
    from .wikitext import iter_templates, template_name
    for start, _, raw in iter_templates(wikitext):
        inner = raw[2:-2]
        tname = template_name(inner)
        if tname in ("技能", "技能2", "技能3"):
            hits.append((start, tname, inner))
    hits.sort(key=lambda x: x[0])

    for idx, (_, _, inner) in enumerate(hits, start=1):
        _, named, _ = parse_params(inner)
        sk = Skill(index=idx)
        sk.name = render_flat(named.get("技能名", ""))
        sk.name_en = render_flat(named.get("技能名en", ""))
        sk.recovery = render_flat(named.get("技能类型1", ""))
        sk.trigger = render_flat(named.get("技能类型2", ""))
        sk.unlock = unlock_map.get(idx, "")
        for key, level in _SKILL_LEVEL_SUFFIXES:
            desc = named.get(f"{key}描述")
            init = named.get(f"{key}初始")
            cost = named.get(f"{key}消耗")
            dur = named.get(f"{key}持续")
            if desc is None and init is None and cost is None and dur is None:
                continue
            sk.levels.append(SkillLevel(
                level=level,
                description=render_flat(desc) if desc else "",
                sp_init=to_number(init) if init else None,
                sp_cost=to_number(cost) if cost else None,
                duration=to_number(dur) if dur else None,
            ))
        sk.levels.sort(key=lambda x: x.level)
        if sk.name or sk.levels:
            skills.append(sk)
    return skills


_SKILL_UNLOCK_RE = re.compile(r"'''\s*技能\s*(\d+)\s*[（(]([^）)]*)[）)]\s*'''")


def _skill_unlock_map(wikitext: str) -> dict[int, str]:
    return {int(m.group(1)): m.group(2).strip()
            for m in _SKILL_UNLOCK_RE.finditer(wikitext)}


def _parse_modules(wikitext: str) -> list[Module]:
    modules: list[Module] = []
    for named, _ in _params_strict(wikitext, "模组"):
        m = Module()
        m.name = render_flat(named.get("名称", ""))
        m.kind = render_flat(named.get("类型", ""))
        m.is_badge = render_flat(named.get("基础证章", "")).lower() == "yes"
        for tier in (1, 2, 3):
            suffix = "" if tier == 1 else str(tier)
            entry: dict[str, Any] = {"level": tier}
            has = False
            for cn, field_name in MODULE_STAT_KEYS.items():
                raw = named.get(f"{cn}{suffix}")
                if raw is not None:
                    entry[field_name] = _num(raw)
                    has = True
            if has:
                m.stats.append(entry)
        m.trait_addon = render_flat(named.get("特性", "")) if \
            render_flat(named.get("特性追加", "")).lower() == "yes" else ""
        for key in ("天赋2", "天赋3", "天赋4"):
            v = render_flat(named.get(key, ""))
            if v:
                m.talent_updates.append(v)
        m.unlock_level = _num(named.get("解锁等级"))
        for key in ("解锁信赖", "解锁信赖2", "解锁信赖3"):
            v = _num(named.get(key))
            if v is not None:
                m.unlock_trust.append(v)
        modules.append(m)
    return modules


# ------------------------------------------------------------------- 取数

def fetch_operator(name: str, *, client: PrtsClient | None = None,
                   use_cache: bool | None = None) -> Operator:
    """按名字取一个干员（一次网络往返，之后走缓存）。"""
    c = client or default_client()
    title = name.strip()
    wt = c.wikitext(title, use_cache=use_cache)
    op = parse_operator(wt, name=title)
    op.raw_url = f"https://prts.wiki/w/{title.replace(' ', '_')}"
    return op


def fetch_operator_by_id(char_id: str, *, client: PrtsClient | None = None) -> Operator:
    """按 `char_103_angel` 这种游戏内 id 反查干员。

    走 SMW 的 `干员id` 属性——Cargo 的 `chara_data` 表里**没有** id 列
    （字段只有数值、费用、阻挡、势力那些），拿 `charaId` 去查会撞上
    "A database query error has occurred"。
    """
    c = client or default_client()
    data = c.get_json({"action": "ask", "query": f"[[干员id::{char_id}]]|limit=1"})
    results = data.get("query", {}).get("results", {})
    if not results:
        raise OperatorNotFound(f"没有找到 char_id = {char_id} 的干员")
    return fetch_operator(next(iter(results)), client=c)


def list_operators(*, client: PrtsClient | None = None, profession: str = "",
                   rarity: int | None = None) -> list[dict]:
    """列出干员名录（走 Cargo，一次请求拿全表，比翻分类快得多）。

    Cargo 里没有职业与稀有度两列，需要筛这两项时再叠一次 SMW 查询。
    """
    c = client or default_client()
    fields = ("_pageName=Page,hp,atk,def,res,cost,block,atkSpeed,reDeploy,"
              "potential,trust,ingameFaction")
    rows = c.cargo("chara_data", fields, order_by="_pageName", limit=1000)
    if profession or rarity is not None:
        keep = {o["title"] for o in _smw_operators(c, profession=profession,
                                                   rarity=rarity)}
        rows = [r for r in rows if r.get("Page") in keep]
    return rows


def _smw_operators(client: PrtsClient, *, profession: str = "",
                   rarity: int | None = None, limit: int = 1000) -> list[dict]:
    """用 SMW 语义查询拿「页面 + 职业 + 稀有度」——Cargo 里没有这两列。

    注意口径：SMW 上的 `稀有度` 也是 0 起算的，入参和出参都按真实星级来。
    """
    query = "[[分类:干员]]"
    if profession:
        query += f"[[职业::{profession}]]"
    if rarity is not None:
        query += f"[[稀有度::{rarity - 1}]]"
    query += f"|?干员id|?职业|?稀有度|limit={limit}"
    data = client.get_json({"action": "ask", "query": query})
    results = data.get("query", {}).get("results", {})
    out = []
    for page, payload in results.items():
        po = payload.get("printouts", {})
        raw_rarity = (po.get("稀有度") or [""])[0]
        try:
            stars = int(raw_rarity) + 1
        except (TypeError, ValueError):
            stars = 0
        out.append({
            "title": page,
            "char_id": (po.get("干员id") or [""])[0],
            "profession": (po.get("职业") or [""])[0],
            "rarity": stars,
        })
    return out


def all_operator_names(*, client: PrtsClient | None = None) -> list[str]:
    """全部干员页面名（含 `阿米娅(近卫)` 这类消歧义后缀）。"""
    c = client or default_client()
    return c.category_members("分类:干员")
