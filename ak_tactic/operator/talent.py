"""干员天赋的数据层。

天赋的骨架和技能很像（一棵候选树 + 一块黑板 + 一段带占位符的描述），但有三处
**必须区别对待**：

## 一、候选是「同一件事的不同档位」，不是不同技能

`character_table` 的 `talents` 是**天赋组**的列表，每组里一长串 `candidates`：

```
天赋组1  精0 1级 潜0   interval 10.0  talent_magic_scale 0.20
         精0 1级 潜4   interval 10.0  talent_magic_scale 0.25   ← 潜能5 强化
         精1 1级 潜0   interval  7.5  talent_magic_scale 0.50
         精1 1级 潜4   interval  7.5  talent_magic_scale 0.55
         精2 1级 潜0   interval  5.5  talent_magic_scale 0.75
         精2 1级 潜4   interval  5.5  talent_magic_scale 0.80
```

同一组里**只能生效一条**：取「精英阶段 ≤ 当前、解锁等级 ≤ 当前、潜能要求满足」
里档位最高的那条。所以第 2 天赋在精0/精1 是**没有的**（没有对应候选），而不是
"数值为 0"——这个区别会影响 `has_talent()` 这类判断。

## 二、`requiredPotentialRank` 是 0 起算

`requiredPotentialRank = 4` 表示**需要潜能 5**（潜能 N 提供 0..N-1 共 N 档）。
判据是 `required_potential <= potential - 1`。圣聆初雪潜能 1 拿不到那 +5% 的档位。

## 三、`prefabKey` 对干员天赋**不是语义键**

装置的天赋里它是 `TalentTotalAttack` 这种有意义的名字，但干员天赋里它只是
`"1"` / `"2"`——**天赋组序号**。所以不能靠它分派行为，只能靠黑板钥匙的组合
（例如「同时有 `interval`／`max_cast_cnt`／`talent_magic_scale`」＝积雪天赋）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..gamedata.source import GITHUB_BASE, GameDataSource, GamedataError
from .skill import SkillEffects, parse_effects, render_description

__all__ = [
    "Talent",
    "TalentError",
    "TalentBook",
    "PHASE_INDEX",
    "PHASE_CN",
    "talent_candidates",
    "resolve_talents",
]

PHASE_INDEX = {"PHASE_0": 0, "PHASE_1": 1, "PHASE_2": 2}
PHASE_CN = {0: "精英0", 1: "精英1", 2: "精英2"}


class TalentError(RuntimeError):
    """天赋取数或解析失败。"""


@dataclass(frozen=True)
class Talent:
    """一条**已判定生效**的天赋。"""

    char_id: str
    group: int                       # 天赋组，从 1 起（游戏里叫「第一天赋」）
    name: str
    description: str                 # 已把 {key} 填成数值
    raw_description: str
    blackboard: dict[str, float]
    phase: int                       # 生效所需的最低精英阶段
    unlock_level: int
    required_potential: int          # 0 起算：4 表示需潜能 5
    range_id: str | None
    #: 这条天赋**附带的召唤物/战术点**（`operator_talent.token_key`）。
    #:
    #: 全库 37 位干员有它：凯尔希的 Mon3tr、深海色的触手、可露希尔的「指挥中心」……
    #: 战斗层要判"某个单位是不是我的战术点"就得有这个名字（按 char_id 判，
    #: 不能按名字或描述猜）。
    token_key: str
    is_hidden: bool
    effects: SkillEffects

    # ------------------------------------------------------------ 读黑板

    def value(self, key: str, default: float = 0.0) -> float:
        """读一个黑板值。键不存在时给 default（**不抛异常**）。"""
        v = self.blackboard.get(key)
        return default if v is None else float(v)

    def has(self, *keys: str) -> bool:
        """这些黑板键是不是都在。用于识别天赋的"形状"。"""
        return all(k in self.blackboard for k in keys)

    def signature(self) -> tuple[str, ...]:
        return tuple(sorted(k for k in self.blackboard if not k.startswith("$")))

    @property
    def label(self) -> str:
        cn = PHASE_CN.get(self.phase, f"精英{self.phase}")
        pot = "" if self.required_potential <= 0 else f" 潜能{self.required_potential + 1}"
        return f"{cn}{self.unlock_level}级{pot}"

    @property
    def title(self) -> str:
        return f"第{'一二三'[self.group - 1] if 1 <= self.group <= 3 else self.group}天赋"

    def to_dict(self) -> dict:
        return {
            "char_id": self.char_id, "group": self.group, "name": self.name,
            "label": self.label, "description": self.description,
            "blackboard": dict(self.blackboard),
            "required_potential": self.required_potential,
            "effects": {"buffs": dict(self.effects.buffs),
                        "units": dict(self.effects.units),
                        "damage": dict(self.effects.damage),
                        "control": dict(self.effects.control),
                        "other": dict(self.effects.other)},
        }

    def __str__(self) -> str:
        return f"{self.title}「{self.name}」（{self.label}）{self.description}"


# ---------------------------------------------------------------- 解析

def _phase_of(raw: Any) -> int:
    if isinstance(raw, int):
        return raw
    return PHASE_INDEX.get(str(raw or "PHASE_0").upper(), 0)


def _blackboard(raw: Any) -> dict[str, float]:
    """天赋黑板 → 扁平字典。

    沿用技能那边的约定：数值键直接放，`valueStr`（字符串表达的值，如
    `range_id` 的标记）另外存成 `$key`，`parse_effects` 会跳过 `$` 开头的键。
    """
    out: dict[str, float] = {}
    for item in raw or []:
        key = item.get("key")
        if not key:
            continue
        out[key] = float(item.get("value") or 0.0)
        if item.get("valueStr") is not None:
            out[f"${key}"] = item["valueStr"]
    return out


def talent_candidates(char: dict) -> list[dict]:
    """把一个干员的 `talents` 摊平成候选列表（附 char_id / group）。"""
    char_id = char.get("charId") or ""
    out: list[dict] = []
    for gi, group in enumerate(char.get("talents") or [], start=1):
        for cand in group.get("candidates") or []:
            out.append({"char_id": char_id, "group": gi, "cand": cand})
    return out


def _build(char_id: str, group: int, cand: dict) -> Talent:
    uc = cand.get("unlockCondition") or {}
    bb = _blackboard(cand.get("blackboard"))
    raw_desc = cand.get("description") or ""
    rendered = render_description(raw_desc, bb)
    return Talent(
        char_id=char_id,
        group=group,
        name=cand.get("name") or "（未命名天赋）",
        description=rendered,
        raw_description=raw_desc,
        blackboard=bb,
        phase=_phase_of(uc.get("phase")),
        unlock_level=int(uc.get("level") or 1),
        required_potential=int(cand.get("requiredPotentialRank") or 0),
        range_id=cand.get("rangeId"),
        token_key=cand.get("tokenKey") or "",
        is_hidden=bool(cand.get("isHideTalent")),
        effects=parse_effects(bb, description=rendered),
    )


def resolve_talents(char: dict, *, elite: int = 2, level: int = 1,
                    potential: int = 1) -> list[Talent]:
    """挑出这个练度下真正生效的天赋（每个天赋组最多一条）。

    :param level: **阶段内**等级（精英2 的 1~90），与属性计算一致。
    :param potential: 潜能 1~6。
    """
    char_id = char.get("charId") or ""
    have = max(0, potential - 1)          # 潜能 N 开放 0..N-1 档
    best: dict[int, tuple[tuple[int, int], Talent]] = {}
    for entry in talent_candidates(char):
        cand = entry["cand"]
        uc = cand.get("unlockCondition") or {}
        phase = _phase_of(uc.get("phase"))
        need_lv = int(uc.get("level") or 1)
        need_pot = int(cand.get("requiredPotentialRank") or 0)
        if phase > elite or need_lv > level or need_pot > have:
            continue
        key = (phase, need_pot)
        cur = best.get(entry["group"])
        if cur is None or key > cur[0]:
            best[entry["group"]] = (key, _build(char_id, entry["group"], cand))
    return [best[g][1] for g in sorted(best)]


# ---------------------------------------------------------------- 入口

class TalentBook:
    """按干员与练度取天赋。

        book = TalentBook()
        for t in book.for_operator("char_1046_sbell2", elite=2, level=90, potential=1):
            print(t.title, t.name, t.value("interval"))
    """

    def __init__(self, source: GameDataSource | None = None):
        self.source = source or GameDataSource(base=GITHUB_BASE)
        self._chars: dict[str, dict] | None = None

    def _load(self) -> dict[str, dict]:
        if self._chars is not None:
            return self._chars
        try:
            raw = self.source.fetch_json("excel/character_table.json")
        except GamedataError as e:
            raise TalentError(
                f"取不到 excel/character_table.json（只有 GitHub 镜像有）：{e}") from e
        # 天赋只关心干员，token/trap 不算；但要留着 charId 字段供解析
        chars: dict[str, dict] = {}
        for k, v in raw.items():
            if not isinstance(v, dict):
                continue
            v = dict(v)
            v.setdefault("charId", k)
            chars[k] = v
        self.source.release("excel/character_table.json")

        # 升变形态（阿米娅的近卫/医疗）**不在 character_table 里**，而在
        # `char_patch_table.json` 的 `patchChars`，结构与干员本体完全相同。
        # 不并进来则 `for_operator('char_1001_amiya2')` 报「没有这个干员」，
        # 于是**术战者阿米娅的天赋「青色怒火」整条查不出来**。
        # `OperatorCalculator` / `SkillBook` / `db/build.py` 都已并了，
        # 这是最后漏掉的一处（2026-09-16 补）——三处同源漏洞至此收口。
        # 取不到这张表只少两个形态，不该让天赋书哑火。
        try:
            patch = self.source.fetch_json("excel/char_patch_table.json")
        except GamedataError:
            patch = {}
        else:
            for cid, c in (patch.get("patchChars") or {}).items():
                if not isinstance(c, dict):
                    continue
                c = dict(c)
                c.setdefault("charId", cid)
                chars.setdefault(cid, c)
            self.source.release("excel/char_patch_table.json")

        self._chars = chars
        return self._chars

    def character(self, char_id: str) -> dict:
        chars = self._load()
        if char_id not in chars:
            raise TalentError(f"没有这个干员：{char_id}")
        return chars[char_id]

    def for_operator(self, char_id: str, *, elite: int = 2, level: int = 1,
                     potential: int = 1) -> list[Talent]:
        return resolve_talents(self.character(char_id), elite=elite,
                               level=level, potential=potential)

    def all_candidates(self, char_id: str) -> list[Talent]:
        """这个干员天赋的**全部档位**（含未解锁的），用来核对数据。"""
        char = self.character(char_id)
        return [_build(char_id, e["group"], e["cand"])
                for e in talent_candidates(char)]

    def coverage(self) -> dict[str, int]:
        """全干员天赋黑板键的分布——用得上的少数，剩下的如实留着。"""
        from collections import Counter
        keys: Counter = Counter()
        total = 0
        for char_id, char in self._load().items():
            if not char_id.startswith("char_"):
                continue
            for e in talent_candidates(char):
                total += 1
                for k in (e["cand"].get("blackboard") or []):
                    if k.get("key"):
                        keys[k["key"]] += 1
        return {"candidates": total, "distinct_keys": len(keys),
                "uses": sum(keys.values())}
