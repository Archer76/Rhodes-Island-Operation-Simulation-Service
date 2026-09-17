"""干员属性计算：等级插值 · 信赖 · 潜能 · 模组。

## 数据从哪来

三张 `excel/` 表，**只有 GitHub 镜像有**（map.ark-nights.com 不带 `excel/`，
一律 404），所以本模块默认自建一个 GitHub 源的 `GameDataSource`：

| 表 | 内容 |
| --- | --- |
| `character_table.json` | 干员本体：各精英阶段的属性关键帧、信赖关键帧、潜能加成 |
| `uniequip_table.json` | 模组元数据：谁有哪个模组、叫什么、什么类型 |
| `battle_equip_table.json` | 模组的战斗数值：每级的属性加成 |

## 属性到底怎么算

游戏并没有为每个等级存一份属性，它只存**关键帧**，中间靠线性插值：

```json
"phases": [
  {"maxLevel": 50, "attributesKeyFrames": [
      {"level": 1,  "data": {"maxHp": 699, "atk": 276, ...}},
      {"level": 50, "data": {"maxHp": 958, "atk": 390, ...}}]},
  ...
]
```

所以最终属性是四份东西相加：

```
属性 = 等级插值(基础)  +  信赖加成  +  潜能加成  +  模组加成
```

四点必须记清：

1. **阶段内等级从 1 重新开始**。精英 1 的 `attributesKeyFrames` 是 level 1→70，
   不是 51→70；而「精英 1 1 级」的属性恰好等于「精英 0 50 级」。参数
   `level` 一律是**阶段内**的等级。
2. **关键帧不一定是两个**。2261 个阶段是 2 个，但还有 29 个是 3 个、11 个是 6 个、
   2 个是 11 个（都是 `trap_*` 装置）。插值必须按相邻帧通用处理。
3. **模组的 `attributeBlackboard` 是该等级的总加成，不是增量**——1/2/3 级分别是
   `{max_hp:100, atk:30}` / `{max_hp:130, atk:40}` / `{max_hp:150, atk:50}`，
   取对应等级那一份即可，别再累加。
4. **信赖的 level 是 0–50，对应游戏内**显示**信赖 0%–100%**（每 level 2 点，即
   `level = 显示信赖 ÷ 2`）。**显示信赖到 100% 就封顶**，再往上（游戏可显示到
   200%）只解锁资料与语音、不再加属性——prts.wiki「信赖值」页原文：「干员信赖值
   达到100%后，属性加成达到上限」。参数 `trust` 是 **0–100 的内部标度**，等于
   显示信赖 ÷ 2（`tools/roster.py` 把森空岛 `favorPercent` 0–200 直接 `/2`），
   所以**它就是 level 本身，不要再除一次**。`trust >= 50`（显示 100%）即满加成，
   `interpolate_keyframes` 的越界夹取会自然封顶。

   ⚠️ 曾经的写法是 `level = trust / 2`，依据是「level 0–50 对应显示 0%–200%」。
   那是把**助战干员**的换算当成了通用规则——助战的旧规则「信赖值除以 2 再向下
   取整」（200% 的干员以 100% 加成供好友使用）已在 2025/12/5 取消，且从来只管
   助战。连除两次的症状：154% 信赖只算出 +46.2 攻击，而实机是满值 +60。

## 取整——2026-09-17 实测定案：四舍五入

关键帧是精确值，但插值出来的中间值几乎都是小数，而游戏面板显示整数。
取整方式**已由实机定案为四舍五入（`round`）**，三条独立证据：

1. **prts.wiki 干员页内嵌的「属性计算器」用的就是 `Math.round`。**
   它在 `static.prts.wiki/charinfo/charinfo_*.min.js` 注入的内联脚本里，
   核心一行是
   `Math.round(parseInt(v[ve]) + (vl-1)*(v[ve+1]-v[ve])/(ll[ve]-1))`
   ——插值写法与本模块逐字同构，取整是四舍五入。它只对**基础值**取整，
   信赖另算一次 `Math.round`，最后相加时**不再取整**。
2. **红豆 精英1 38级 潜6 信赖154%（显示）→ 实机 攻击 510 / 生命 1185。**
   攻击：`round(425.864)=426` + 满信赖 60 + 潜能 24 = **510**（floor 只能到 509）；
   生命：`round(1184.729)=1185`（floor 是 1184）。生命既不随信赖也不随潜能变
   （红豆的信赖只加攻击、潜4 只加攻击），所以它是**纯基础值的试纸**。
3. **怒潮凛冬 精英2 60级 潜1 信赖200% 模组 Lv1 → 实机 2981 / 1307 / 473。**
   `round(2731.24 + 0 + 0 + 250) = 2981`、
   `round(1193.91 + 50 + 0 + 63) = 1307`、`round(387.10 + 65 + 0 + 21) = 473`
   ——攻击一栏 floor 给 1306，**直接排除 floor**。

⚠️ **别与伤害结算的取整混淆。** wiki 的伤害页写明伤害结算里有 FLOOR，
那是 `battle/damage.py` 的事，**与面板无关**。面板四舍五入、伤害向下取整，
两者各自成立，不矛盾。改造面板取整时不要去动伤害那一侧。

本模块的做法：

* 对**整数属性**（生命/攻击/防御/费用/阻挡数/再部署）默认**四舍五入**；
* 对**浮点属性**（法抗/移速/攻速/攻击间隔）不取整；
* 取整策略仍是构造参数 `rounding`，可切 `"floor"` / `"round"` / `"ceil"` / `"none"`，
  留作日后遇到反例时的校准口。

⚠️ **取整被用了两次**：先在 `interpolate_keyframes()` 里对**等级插值出来的
基础值**取整，再在 `stats()` 里对**加上信赖/潜能/模组之后的总和**取整。
两点留意：

1. `"ceil"` 的结果可能比 `"floor"` **高 2 点**（两处各进一位），
   所以不能拿「插值原值的小数部分」去反推三种取整的差别——那样推必错
   （2026-09-17 就是这么写错一版校准脚本的）。要分辨取整方式，
   **只能直接比各模式算出来的数**。
2. 实际数据里信赖与潜能/模组的贡献各自取整后基本都是整数，故第二次取整
   通常是无操作。**唯一可能被它咬到的是中间值的浮点误差**（如 `x.9999999`）——
   真要排查「端点对得上、中间等级差 1」，先怀疑这里。

末尾的 `calibrate()` 就是为这件事准备的：喂进一条游戏内实测的数值，
它把两种取整方式都算一遍，直接告诉你是哪一种。
"""

from __future__ import annotations

import math
import re
from typing import Any, Iterable

from ..gamedata.source import GITHUB_BASE, GameDataSource, GamedataError

__all__ = [
    "OperatorCalculator",
    "OperatorStats",
    "OperatorError",
    "INT_ATTRS",
    "FLOAT_ATTRS",
    "ATTR_LABELS",
    "MODULE_KEY_MAP",
    "POTENTIAL_ATTR_MAP",
    "interpolate_keyframes",
    "parse_rarity",
]

#: 游戏面板上按整数显示的属性——插值后要取整。
INT_ATTRS = frozenset({
    "maxHp", "atk", "def", "cost", "blockCnt", "respawnTime",
    "maxDeployCount", "maxDeckStackCnt", "tauntLevel", "massLevel",
    "baseForceLevel",
})

#: 浮点属性——不取整，否则 0.7 的移速会被压成 0。
FLOAT_ATTRS = frozenset({
    "magicResistance", "moveSpeed", "attackSpeed", "baseAttackTime",
    "hpRecoveryPerSec", "spRecoveryPerSec",
})

#: 属性英文名 → 中文标签（打印用）
ATTR_LABELS = {
    "maxHp": "生命上限",
    "atk": "攻击",
    "def": "防御",
    "magicResistance": "法术抗性",
    "cost": "部署费用",
    "blockCnt": "阻挡数",
    "moveSpeed": "移动速度",
    "attackSpeed": "攻击速度",
    "baseAttackTime": "攻击间隔",
    "respawnTime": "再部署",
    "hpRecoveryPerSec": "每秒回血",
    "spRecoveryPerSec": "每秒回技力",
    "maxDeployCount": "同时部署数",
    "tauntLevel": "嘲讽等级",
    "massLevel": "重量等级",
    "baseForceLevel": "推力等级",
}

#: 模组 attributeBlackboard 的 key（下划线风格）→ character_table 的属性名
MODULE_KEY_MAP = {
    "max_hp": "maxHp",
    "atk": "atk",
    "def": "def",
    "magic_resistance": "magicResistance",
    "attack_speed": "attackSpeed",
    "cost": "cost",
    "respawn_time": "respawnTime",
    "block_cnt": "blockCnt",
    "move_speed": "moveSpeed",
}

#: 潜能 attributeModifiers 的 attributeType（全大写）→ 属性名
POTENTIAL_ATTR_MAP = {
    "MAX_HP": "maxHp",
    "ATK": "atk",
    "DEF": "def",
    "MAGIC_RESISTANCE": "magicResistance",
    "COST": "cost",
    "ATTACK_SPEED": "attackSpeed",
    "RESPAWN_TIME": "respawnTime",
    "BLOCK_CNT": "blockCnt",
    "MOVE_SPEED": "moveSpeed",
    "MAX_DEPLOY_COUNT": "maxDeployCount",
}

#: 面板上最值得看的几项，按这个顺序打印
PANEL_ORDER = ("maxHp", "atk", "def", "magicResistance",
               "cost", "blockCnt", "baseAttackTime", "attackSpeed", "respawnTime")


class OperatorError(RuntimeError):
    """查不到干员、等级越界，或数据源缺表。"""


#: character_table 里的稀有度是 `"TIER_5"` 这种字符串，不是数字。
#: （顺带一提，PRTS 的 SMW 那条路走的是 0 起算的整数，两套别搞混。）
_TIER_RE = re.compile(r"TIER_(\d+)")


def parse_rarity(value: Any) -> int:
    """`"TIER_5"` → 5。"""
    if isinstance(value, int):
        return value
    m = _TIER_RE.search(str(value or ""))
    return int(m.group(1)) if m else 0


def _apply_rounding(value: float, attr: str, rounding: str) -> float | int:
    """按属性类型与策略收口成面板上的数字。"""
    if attr not in INT_ATTRS or rounding == "none":
        return value
    if rounding == "floor":
        return int(math.floor(value))
    if rounding == "round":
        return int(round(value))
    if rounding == "ceil":
        return int(math.ceil(value))
    raise OperatorError(f"未知的取整方式：{rounding}")


def interpolate_keyframes(
    frames: Iterable[dict],
    level: float,
    *,
    rounding: str = "round",
) -> dict[str, Any]:
    """在关键帧之间按等级线性插值。

    `frames` 形如 `[{"level": 1, "data": {...}}, {"level": 50, "data": {...}}]`，
    **不假定只有两帧**——真实数据里存在 3、4、6 甚至 11 帧的阶段。

    等级落在两帧之间时按比例插值；超出范围则夹到最近的一帧。
    布尔属性不插值，取左侧那一帧的值。
    """
    fr = sorted((f for f in (frames or []) if f.get("data")), key=lambda f: f["level"])
    if not fr:
        return {}
    if len(fr) == 1:
        return dict(fr[0]["data"])

    if level <= fr[0]["level"]:
        lo = hi = fr[0]
    elif level >= fr[-1]["level"]:
        lo = hi = fr[-1]
    else:
        lo, hi = fr[0], fr[-1]
        for a, b in zip(fr, fr[1:]):
            if a["level"] <= level <= b["level"]:
                lo, hi = a, b
                break

    a, b = lo["data"], hi["data"]
    span = hi["level"] - lo["level"]
    t = 0.0 if span == 0 else (level - lo["level"]) / span

    out: dict[str, Any] = {}
    for key in set(a) | set(b):
        va, vb = a.get(key), b.get(key)
        if va is None:
            out[key] = vb
            continue
        if vb is None:
            out[key] = va
            continue
        if isinstance(va, bool) or isinstance(vb, bool):
            out[key] = va if t < 0.5 else vb
            continue
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            out[key] = _apply_rounding(va + (vb - va) * t, key, rounding)
        else:
            out[key] = va
    return out


def _potential_bonus(ranks: list[dict], potential: int) -> dict[str, float]:
    """潜能加成。

    游戏里的潜能是 1–6，而 `potentialRanks` 只有 5 项——**对应潜能 2–6**，
    潜能 1 是干员到手时的状态、没有任何加成。所以取前 `potential - 1` 项。
    """
    out: dict[str, float] = {}
    if potential <= 1:
        return out
    for rank in ranks[: potential - 1]:
        if rank.get("type") != "BUFF":
            continue
        mods = ((rank.get("buff") or {}).get("attributes") or {}).get("attributeModifiers") or []
        for m in mods:
            attr = POTENTIAL_ATTR_MAP.get(m.get("attributeType"))
            if not attr:
                continue
            val = float(m.get("value") or 0.0)
            if m.get("formulaItem") == "MULTIPLIER":
                # 乘算潜能（少数干员有），用负数打标记，最后单独处理
                out[f"x{attr}"] = val
            else:
                out[attr] = out.get(attr, 0.0) + val
    return out


class OperatorStats:
    """一次计算的完整结果，四份来源分开留着，方便看清每个数字从哪来。"""

    def __init__(self, char_id: str, char: dict, *, elite: int, level: int,
                 trust: float, potential: int,
                 module: str | None, module_level: int):
        self.char_id = char_id
        self.name: str = char.get("name") or char_id
        self.elite = elite
        self.level = level
        self.trust = trust
        self.potential = potential
        self.module = module
        self.module_level = module_level
        self.rarity: int = parse_rarity(char.get("rarity"))
        self.profession: str = char.get("profession") or ""
        self.sub_profession: str = char.get("subProfessionId") or ""
        self.base: dict[str, Any] = {}
        self.trust_bonus: dict[str, float] = {}
        self.potential_bonus: dict[str, float] = {}
        self.module_bonus: dict[str, float] = {}
        self.total: dict[str, Any] = {}

    @property
    def phase_name(self) -> str:
        return ("精英 0", "精英 1", "精英 2")[self.elite] if self.elite < 3 else f"阶段 {self.elite}"

    def panel(self) -> list[tuple[str, str, Any]]:
        """(属性名, 中文标签, 值)，按面板顺序。

        只留有信息的项：免疫开关一律是 0/1 的布尔噪音，零值属性也不是
        部署时要看的——真正该看的九项排在最前，其余非零项缀在后面。
        """
        rows = []
        for k in PANEL_ORDER:
            if k in self.total:
                rows.append((k, ATTR_LABELS.get(k, k), self.total[k]))
        for k in sorted(self.total):
            if k in PANEL_ORDER:
                continue
            v = self.total[k]
            if isinstance(v, bool) or k.endswith("Immune"):
                continue
            if v in (0, 0.0):
                continue
            rows.append((k, ATTR_LABELS.get(k, k), v))
        return rows

    def to_dict(self) -> dict:
        return {
            "char_id": self.char_id,
            "name": self.name,
            "rarity": self.rarity,
            "profession": self.profession,
            "sub_profession": self.sub_profession,
            "elite": self.elite,
            "level": self.level,
            "trust": self.trust,
            "potential": self.potential,
            "module": self.module,
            "module_level": self.module_level,
            "base": self.base,
            "trust_bonus": self.trust_bonus,
            "potential_bonus": self.potential_bonus,
            "module_bonus": self.module_bonus,
            "total": self.total,
        }


class OperatorCalculator:
    """干员属性计算器。

    默认自建 GitHub 源——`excel/` 三张表只有它有。也可以塞一个自己的 source：

        calc = OperatorCalculator()                       # GitHub
        calc = OperatorCalculator(rounding="round")       # 换成四舍五入
    """

    def __init__(self, source: GameDataSource | None = None, *, rounding: str = "round"):
        if rounding not in ("floor", "round", "ceil", "none"):
            raise OperatorError(f"未知的取整方式：{rounding}")
        self.source = source or GameDataSource(base=GITHUB_BASE)
        self.rounding = rounding
        self._chars: dict[str, dict] | None = None
        self._uniequip: dict[str, dict] | None = None
        self._equips: dict[str, dict] | None = None
        self._char_equip: dict[str, list[str]] | None = None
        self._battle_equip: dict[str, dict] | None = None

    # ------------------------------------------------------------ 数据装载

    def _excel(self, name: str) -> dict:
        try:
            data = self.source.fetch_json(f"excel/{name}")
        except GamedataError as e:
            raise OperatorError(
                f"取不到 excel/{name}。\n"
                f"  excel/ 目录只有 GitHub 镜像有，map.ark-nights.com 不带。\n"
                f"  换源：GameDataSource(base=GITHUB_BASE)\n  {e}") from e
        return data if isinstance(data, dict) else {}

    def _load_chars(self) -> dict[str, dict]:
        if self._chars is not None:
            return self._chars
        raw = self._excel("character_table.json")
        # 只留真干员（trap_* 是装置/召唤物），并立刻释放原始大对象
        chars = {k: v for k, v in raw.items() if k.startswith("char_")}
        self.source.release("excel/character_table.json")

        # 升变形态（阿米娅的近卫/医疗）**不在 character_table 里**，而在
        # `char_patch_table.json` 的 `patchChars`，结构与干员本体完全相同。
        # 森空岛名册引用的正是这些 charId（char_1001_amiya2 / char_1037_amiya3），
        # 不并进来则 `stats char_1001_amiya2` 直接报「没有这个干员」。
        # 取不到这张表不该让整个计算器哑火——少两个形态而已。
        try:
            patch = self._excel("char_patch_table.json")
        except OperatorError:
            patch = {}
        else:
            for cid, c in (patch.get("patchChars") or {}).items():
                chars.setdefault(cid, c)
            self.source.release("excel/char_patch_table.json")

        self._chars = chars
        return self._chars

    def _load_uniequip(self) -> dict[str, dict]:
        if self._uniequip is not None:
            return self._uniequip
        raw = self._excel("uniequip_table.json")
        self._uniequip = raw.get("equipDict") or {}
        self._char_equip = raw.get("charEquip") or {}
        return self._uniequip

    def _load_battle_equip(self) -> dict[str, dict]:
        if self._battle_equip is not None:
            return self._battle_equip
        self._battle_equip = self._excel("battle_equip_table.json")
        return self._battle_equip

    # ------------------------------------------------------------ 查询接口

    def all_ids(self) -> list[str]:
        return sorted(self._load_chars())

    def exists(self, char_id: str) -> bool:
        return char_id in self._load_chars()

    def character(self, char_id: str) -> dict:
        chars = self._load_chars()
        if char_id not in chars:
            raise OperatorError(f"没有这个干员：{char_id}")
        return chars[char_id]

    def find(self, keyword: str, *, limit: int = 20) -> list[tuple[str, str]]:
        """按 char_id 或中文名模糊找干员，返回 [(char_id, 名字)]。

        完全同名的排在第一位——所以 `stats 银灰` 会直接选中银灰，
        而不会因为还有个「凛御银灰」就让人再选一次。
        """
        kw = keyword.strip().lower()
        exact: list[tuple[str, str]] = []
        partial: list[tuple[str, str]] = []
        for cid, c in self._load_chars().items():
            name = c.get("name") or cid
            if name.lower() == kw or cid.lower() == kw:
                exact.append((cid, name))
            elif kw in cid.lower() or kw in name.lower():
                partial.append((cid, name))
        partial.sort(key=lambda x: (len(x[0]), x[0]))
        return (exact + partial)[:limit]

    def max_level(self, char_id: str, elite: int | None = None) -> Any:
        """各精英阶段的等级上限。"""
        phases = self.character(char_id).get("phases") or []
        caps = [int(p.get("maxLevel") or 0) for p in phases]
        return caps[elite] if elite is not None else caps

    def modules(self, char_id: str) -> list[dict]:
        """这名干员能装哪些模组。带 `has_stats` 标记有没有属性加成。"""
        equips = self._load_uniequip()
        battle = self._load_battle_equip()
        ids = (self._char_equip or {}).get(char_id)
        if ids is None:
            ids = [k for k, v in equips.items() if v.get("charId") == char_id]
        out = []
        for mid in ids:
            meta = equips.get(mid) or {}
            out.append({
                "id": mid,
                "name": meta.get("uniEquipName") or mid,
                "type": meta.get("type") or "",
                "has_stats": mid in battle,
                "unlock_level": meta.get("unlockLevel"),
                "unlock_phase": meta.get("unlockEvolvePhase"),
                "unlock_favor": meta.get("unlockFavors"),
            })
        out.sort(key=lambda m: (not m["has_stats"], m["id"]))
        return out

    def module_levels(self, module_id: str) -> dict[int, dict[str, float]]:
        """模组各等级的属性加成 {等级: {属性: 值}}。

        注意返回的是**该等级的总加成**，不是相对上一级的增量。
        """
        entry = self._load_battle_equip().get(module_id)
        if not entry:
            raise OperatorError(
                f"模组 {module_id} 没有战斗数值（基础证章不带属性加成）")
        out: dict[int, dict[str, float]] = {}
        for ph in entry.get("phases") or []:
            lv = int(ph.get("equipLevel") or 0)
            bb = {}
            for b in (ph.get("attributeBlackboard") or []):
                attr = MODULE_KEY_MAP.get(b.get("key"))
                if attr:
                    bb[attr] = float(b.get("value") or 0.0)
            out[lv] = bb
        return out

    def module_parts(self, module_id: str, level: int) -> list[dict]:
        """模组某一等级的 `parts`——**特性／天赋改写**。

        这是 `attributeBlackboard` **之外**的另一半，别只读属性黑板：
        `uniequip_002_chen3` 的三种等级都只给 `max_hp` 与 `atk`，而它真正
        改写的东西在 `parts` 里——特性变成「未阻挡敌人时攻击速度 +8」。
        没有该模组、或该等级没有 parts 时返回空列表（基础证章即如此）。
        """
        entry = self._load_battle_equip().get(module_id)
        if not entry:
            return []
        for ph in entry.get("phases") or []:
            if int(ph.get("equipLevel") or 0) == int(level):
                return list(ph.get("parts") or [])
        return []

    # ------------------------------------------------------------ 核心计算

    def stats(
        self,
        char_id: str,
        *,
        elite: int = 0,
        level: int = 1,
        trust: float = 0.0,
        potential: int = 1,
        module: str | None = None,
        module_level: int = 0,
    ) -> OperatorStats:
        """算出某一档配置下的属性。

        :param elite: 精英阶段 0/1/2
        :param level: **阶段内**等级，从 1 开始
        :param trust: 内部信赖标度 0–100（= 游戏内**显示**信赖 ÷ 2）。它就是
            favorKeyFrames 的 level（0–50）；**显示信赖 100% 即封顶**，
            再往上不再加属性
        :param potential: 潜能 1–6
        :param module: 模组 id，如 `uniequip_002_amiya`
        :param module_level: 模组等级 1–3，0 表示不装
        """
        char = self.character(char_id)
        phases = char.get("phases") or []
        if not (0 <= elite < len(phases)):
            raise OperatorError(
                f"{char.get('name')} 只有 {len(phases)} 个精英阶段，没有精英 {elite}")
        ph = phases[elite]
        cap = int(ph.get("maxLevel") or 0)
        if not (1 <= level <= cap):
            raise OperatorError(f"精英 {elite} 的等级必须在 1–{cap}，收到 {level}")

        st = OperatorStats(char_id, char, elite=elite, level=level, trust=trust,
                           potential=potential, module=module,
                           module_level=module_level)

        st.base = interpolate_keyframes(ph.get("attributesKeyFrames") or [],
                                        level, rounding=self.rounding)

        # 信赖：favorKeyFrames 的 level 是 0–50，对应游戏内显示信赖 0%–100%，
        # 100% 即封顶（prts.wiki「信赖值」页），故 level = 显示信赖 / 2。
        # 而 trust 本身已是「显示 ÷ 2」的内部标度——**直接当 level 用，不要
        # 再除一次**；超过 50 时由 interpolate_keyframes 的越界夹取封顶。
        st.trust_bonus = {
            k: v for k, v in interpolate_keyframes(
                char.get("favorKeyFrames") or [], trust,
                rounding=self.rounding).items() if v
        }

        st.potential_bonus = _potential_bonus(char.get("potentialRanks") or [],
                                              potential)

        if module and module_level:
            levels = self.module_levels(module)
            if module_level not in levels:
                raise OperatorError(
                    f"模组 {module} 只有 {sorted(levels)} 这几个等级，收到 {module_level}")
            st.module_bonus = dict(levels[module_level])

        total: dict[str, Any] = {}
        for k, v in st.base.items():
            if isinstance(v, bool):
                total[k] = v
                continue
            if not isinstance(v, (int, float)):
                total[k] = v
                continue
            acc = float(v)
            for src_ in (st.trust_bonus, st.potential_bonus, st.module_bonus):
                acc += float(src_.get(k, 0.0))
            # 乘算潜能
            mul = st.potential_bonus.get(f"x{k}")
            if mul:
                acc *= mul
            total[k] = _apply_rounding(acc, k, self.rounding)
        st.total = total
        return st

    # ------------------------------------------------------------ 标定

    def calibrate(
        self,
        char_id: str,
        *,
        elite: int,
        level: int,
        attr: str,
        observed: float,
        trust: float = 0.0,
        potential: int = 1,
        module: str | None = None,
        module_level: int = 0,
    ) -> dict:
        """用一条游戏内实测值，判断插值到底用的是哪种取整。

        喂进「我在游戏里看到精英2 50级的阿米娅攻击是 XXX」，它会分别按
        向下取整与四舍五入算一遍，指出哪个对得上——这是本模块唯一还没
        被证实的一环，所以留了这条标定路径而不是把猜测写死。

        :param attr: 属性名，如 `atk`
        :param observed: 游戏内看到的数值
        """
        results = {}
        for mode in ("floor", "round", "none"):
            saved = self.rounding
            self.rounding = mode
            try:
                v = self.stats(char_id, elite=elite, level=level, trust=trust,
                               potential=potential, module=module,
                               module_level=module_level).total.get(attr)
            finally:
                self.rounding = saved
            results[mode] = v

        exact = [m for m, v in results.items() if v is not None and float(v) == float(observed)]
        if "floor" in exact and "round" not in exact:
            verdict = "向下取整（floor）"
        elif "round" in exact and "floor" not in exact:
            verdict = "四舍五入（round）"
        elif len(exact) >= 2:
            verdict = "两种取整在这条样本上结果相同，换一个属性或等级再试"
        else:
            verdict = "都对不上——可能属性名写错，或实测值来自面板之外（含技能/天赋加成）"
        return {"observed": observed, "computed": results,
                "match": exact, "verdict": verdict}
