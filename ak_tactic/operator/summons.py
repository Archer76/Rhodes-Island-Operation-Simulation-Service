# -*- coding: utf-8 -*-
"""召唤物：哪个干员能带出哪个 token，它的属性与技能从哪来。

## 为什么单开一个模块

`OperatorCalculator` **明确不认**召唤物——`stats.py` 的 `_load_chars` 只留
`char_*`（注释：「只留真干员（trap_* 是装置/召唤物）」）。那条路走不通，也不该
硬塞：把 `token_*` 并进 `_load_chars` 会连带改掉 `all_ids()` / `find()` 的行为，
于是 CLI 的选人与 `team` 命令都会开始列出召唤物。

所以这里另起一条只做三件事：

1. **谁召唤了谁**——干员技能槽的 `overrideTokenKey` 与天赋候选项的 `tokenKey`；
2. **它的属性**——token 自己的 `phases[].attributesKeyFrames`；插值**复用**
   `stats.interpolate_keyframes`，不另写一套（避免与真编译器口径分叉）；
3. **它的技能与范围**——技能走 `skill_table`，范围取**阶段上**的 `rangeId`。

## 两个查错表就一条都取不到的点

- `overrideTokenKey` 挂在 **`character_table` 里干员的技能槽**上，
  **不在** `skill_table` 的技能条目上——后者一律是 `None`。查错表会得到
  「这些干员没有召唤物」的假结论。
- `rangeId` 在 **phase** 上，`character_table` 的顶层没有 `rangeId`。

## 一处尚未实机确认的假设

召唤物用哪个 phase，本模块按「**跟召唤者同精英阶段**」处理（`elite=0/1/2`
直接当 phase 用），默认取 2。这是从数据形态推的，**未见实机确认**，
在写进 `docs/uncertainties.md` 之前不算结论。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..gamedata.source import GITHUB_BASE, GameDataSource, GamedataError
from .stats import interpolate_keyframes

__all__ = [
    "SummonError",
    "SummonSpec",
    "SummonAttributes",
    "SummonBook",
]


class SummonError(Exception):
    """召唤物数据取不到，或数据本身不合法。"""


@dataclass(frozen=True)
class SummonSpec:
    """一条「某干员能带出某个召唤物」的记录。"""

    token_key: str
    name: str
    origins: tuple[str, ...]
    #: token 在表里找不到时为 True。此时 `name` 等于 `token_key`——
    #: **如实暴露，不静默跳过**。已知一例：`token_10057_svash2_eagle`
    #: 被 `tokenKey` 引用，但表里只有 eagle1/2/3。
    missing: bool = False

    @property
    def origin_text(self) -> str:
        return "、".join(self.origins)


@dataclass(frozen=True)
class SummonAttributes:
    """召唤物在某个阶段与等级下的属性（`attrs` 的键与 gamedata 一致）。"""

    token_key: str
    name: str
    phase: int
    level: float
    attrs: dict[str, Any]
    range_id: str | None = None

    def get(self, key: str, default: float = 0.0) -> float:
        value = self.attrs.get(key)
        return default if value is None else value

    @property
    def max_hp(self) -> float:
        return float(self.get("maxHp"))

    @property
    def atk(self) -> float:
        return float(self.get("atk"))

    @property
    def defense(self) -> float:
        return float(self.get("def"))

    @property
    def res(self) -> float:
        return float(self.get("magicResistance"))

    @property
    def cost(self) -> float:
        return float(self.get("cost"))

    @property
    def block_cnt(self) -> int:
        return int(self.get("blockCnt"))

    @property
    def attack_interval(self) -> float:
        return float(self.get("baseAttackTime", 1.0))

    @property
    def attack_speed(self) -> float:
        return float(self.get("attackSpeed", 100.0))

    @property
    def respawn_time(self) -> float:
        return float(self.get("respawnTime"))

    @property
    def max_deploy_count(self) -> int:
        return int(self.get("maxDeployCount"))

    @property
    def max_deck_stack(self) -> int:
        """待部署区的库存上限。

        表格里的键是 `maxDeckStackCnt`（**不是** `maxDeckStack`——库里的列名
        是后者，容易顺手套错）。
        """
        return int(self.get("maxDeckStackCnt"))


class SummonBook:
    """召唤物的读取入口。

        book = SummonBook()
        for spec in book.for_operator("char_4195_radian"):
            a = book.attributes(spec.token_key, phase=2)
            print(spec.token_key, spec.name, spec.origin_text, a.max_hp, a.cost)
    """

    def __init__(self, source: GameDataSource | None = None):
        self.source = source or GameDataSource(base=GITHUB_BASE)
        self._chars: dict[str, dict] | None = None

    # ------------------------------------------------------------ 数据装载

    def _load(self) -> dict[str, dict]:
        if self._chars is not None:
            return self._chars
        try:
            raw = self.source.fetch_json("excel/character_table.json")
        except GamedataError as e:
            raise SummonError(
                f"取不到 excel/character_table.json。\n"
                f"  这张表只有 GitHub 镜像有，map.ark-nights.com 不带。\n"
                f"  换源：GameDataSource(base=GITHUB_BASE)\n  {e}") from e
        if not isinstance(raw, dict):
            raise SummonError("character_table.json 的结构不是字典")

        # 干员（char_*）与召唤物/装置（token_* / trap_*）都在这一张表里，
        # 这里**一并留下**：本模块正是要处理后者。
        chars: dict[str, dict] = {k: v for k, v in raw.items()
                                  if isinstance(v, dict)}

        # 升变形态（阿米娅的近卫/医疗）不在 character_table 里。它们目前没有
        # 召唤物，但并进来成本极低，免得日后报「表里没有这一条」时又要查一遍。
        try:
            patch = self.source.fetch_json("excel/char_patch_table.json")
        except GamedataError:
            patch = {}
        for cid, c in (patch.get("patchChars") or {}).items():
            if isinstance(c, dict):
                chars.setdefault(cid, c)

        self.source.release("excel/character_table.json")
        self._chars = chars
        return self._chars

    # ------------------------------------------------------------ 查询接口

    def exists(self, char_id: str) -> bool:
        return char_id in self._load()

    def character(self, char_id: str) -> dict:
        chars = self._load()
        if char_id not in chars:
            raise SummonError(f"表里没有这一条：{char_id}")
        return chars[char_id]

    def name_of(self, char_id: str) -> str:
        return (self._load().get(char_id) or {}).get("name") or char_id

    def for_operator(self, char_id: str) -> list[SummonSpec]:
        """这名干员能带出的召唤物。

        来源两条：技能槽的 `overrideTokenKey`、天赋候选项的 `tokenKey`。
        同一个 token 被多处引用时（望的棋子被 3 个技能槽 + 6 个天赋候选项
        同时引用）**按 token 去重、来源合并**——它是一件召唤物，不是九件。
        """
        ch = self.character(char_id)
        origins: dict[str, list[str]] = {}

        for slot, entry in enumerate(ch.get("skills") or [], start=1):
            key = (entry or {}).get("overrideTokenKey")
            if key:
                origins.setdefault(key, []).append(f"技{slot}")

        for t in ch.get("talents") or []:
            for cand in (t or {}).get("candidates") or []:
                key = (cand or {}).get("tokenKey")
                if key:
                    origins.setdefault(key, []).append(
                        f"天赋「{cand.get('name') or '?'}」")

        out: list[SummonSpec] = []
        for key in sorted(origins):
            seen: list[str] = []
            for o in origins[key]:
                if o not in seen:
                    seen.append(o)
            missing = key not in self._load()
            out.append(SummonSpec(token_key=key,
                                  name=self.name_of(key),
                                  origins=tuple(seen),
                                  missing=missing))
        return out

    def attributes(self, token_key: str, *, phase: int = 2,
                   level: float | None = None,
                   rounding: str = "round") -> SummonAttributes:
        """召唤物在 `phase` 下的属性。`level=None` 取该阶段的满级。

        `phase` 越界会**夹到**可用范围（数据里 63 号 token 只有 1 个阶段），
        不抛错——召唤物按召唤者的精英阶段取档，低星召唤者天然取不到高档。
        """
        ch = self.character(token_key)
        phases = ch.get("phases") or []
        if not phases:
            raise SummonError(f"{token_key} 的 phases 是空的，没有属性可取")
        idx = max(0, min(int(phase), len(phases) - 1))
        ph = phases[idx] or {}
        frames = ph.get("attributesKeyFrames") or []
        if not frames:
            raise SummonError(f"{token_key} 的 phase {idx} 没有属性帧")

        max_level = ph.get("maxLevel") or (frames[-1] or {}).get("level") or 1
        lv = float(max_level) if level is None else float(level)
        data = interpolate_keyframes(frames, lv, rounding=rounding)
        return SummonAttributes(token_key=token_key,
                                name=ch.get("name") or token_key,
                                phase=idx, level=lv, attrs=data,
                                range_id=ph.get("rangeId"))

    def skills(self, token_key: str) -> list[str]:
        """召唤物自己的技能 id（多数有，少数没有）。

        注意槽位去重：电弧的三座塔各自只有一个技能，但表里把同一个 skillId
        写进了三个槽——这里**保留槽位顺序**，因为我们不合并，去重交给调用方。
        """
        ch = self.character(token_key)
        return [e["skillId"] for e in (ch.get("skills") or [])
                if (e or {}).get("skillId")]

    def is_token(self, char_id: str) -> bool:
        """是不是"干员附带单位"。

        判据用 `profession == 'TOKEN'`，**不是** id 前缀——`trap_*` 是装置，
        与召唤物不是一回事。
        """
        return (self._load().get(char_id) or {}).get("profession") == "TOKEN"
