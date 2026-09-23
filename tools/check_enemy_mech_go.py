#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敌人机制建模判据（第 27 套）：把「Go 到底实现了哪些敌人机制」做成一可重复的判据。

## 为什么要有它

`spec.py::_enemy_reasons` 那道闸门是**字段驱动**的：`EnemyUnit` 上哪个字段非零，
就说明那段代码这一局会跑，于是拒跑。设计本身是对的——判据不看名字、不看描述关键词。

但它有一处**结构性**的盲：**字段表里没有的能力，闸门永远沉默**。
而「沉默」与「查过了没问题」在输出上长得一模一样。

已有的两件工具都补不上这一块：

* `tools/check_enemy_go.py` 是**字段级对拍**：它证明 Go 与 `EnemyLibrary` 的字段
  逐位一致，**不证明机制被实现**。两侧同样地「读了黑板、填了字段、没人用」，
  它照样全绿——那正是最该被看见的一种状态。
* `tools/audit_unmodelled_abilities.py` 扫的是**一张手写登记表**里那 5 条
  「原版也没建模」的能力，它不是通用的「Go 有没有建模」。

本套件换了取证方向：**从数据侧现算键空间，从两侧源码现算消费面，两面求差。**

## ★ 判据是**两条腿**的（2026-09-24 父会话裁定后重挑）

只量「Go 读不读」会把**两台引擎共同的边界**记成 Go 的欠账。
`tools/audit_unmodelled_abilities.py` 的开头就立过这条规矩：

> 原版战斗层也零命中 ⇒ 两台引擎同样不建模 ⇒ 对拍成立 ⇒ 不该进闸门。

于是判据改成**两边同构地量**，再求差。设 K 是一个敌人机制键
（天赋黑板或敌方技能黑板里的 `key`）：

| 状态 | 判据 | 进不进 rc |
|---|---|---|
| **已消费** | Go 有读取点 **且** Go 有行为落点 | 否 |
| **真红** | ¬Go消费 **且 Python 侧有落点** | **是**（Go 的欠账） |
| **共同边界** | 两侧都没有落点 | 否（**登记**，逐条落盘） |
| **仅 Go** | Go 有落点而 Python 没有（反向，罕见） | 否（登记） |
| **判不了** | 正文是自然语言、没有具名判据 | 否（逐条落盘，**不装作已查**） |

**两侧的消费面同构地现算**：

* **读取点** = 键的**字面串**出现在「填充侧」的**代码行**里
  （Go：`bbFloat/bbInt/bbValue(bb,"K")`、`bb["K"]`；Python：`ak_tactic/gamedata/enemy.py`
  里的 `_bb_float(bb,"K")`、`bb.get("K")`）。
* **行为落点** = 它下游落到的那个字段在「行为侧」被读
  （Go：`rios-sim/*.go` 去掉 填充／规格／闸门之后剩下的文件；
   Python：`ak_tactic/battle/*.py`）。源字段与规格字段之间的改名靠
  `v.RebornDelay = es.RebornDuration` 这类搬移语句现算成同义名一起找
  （不过这一层会造出假红：`RebornDuration` 在 `sim.go` 里一处都没有）。
* **两条具名族**：重生族（`Reborn.`／`Reborning.`，后缀集从**源码**现算，
  含 `prefix + "…"` 拼接出来的那些）与相性族（`AffinityOf(bb,"P")` × `p3rSlots` 槽位）。
  族判定要**连后缀一起看**：`Reborn.invincible` 与 `Reborn.reborn_duration`
  同前缀不同命，按前缀一律放行会把红洗成绿。
* **技能读取器**：`proseSkillAttacks`（Go）／`PROSE_SKILL_ATTACK`（Python）那张表里的
  `prefabKey`，它读的黑板键**两侧**都算消费。该表实测**只有 `Drink` 一项**。

★ 要害仍是那一条：**「读了黑板、填进字段、模拟里没人读」不算建模**。
本批 17 条真红全是这个形状（Go 只填不用、Python 有落点）。

⚠ **Python 面的盲区**（写在这里，不藏在注释里）：它看不见「同一机制换了个键名实现」，
那是**未核**，不是没建。输出里另印一列 `py_token`（键的机制名在 Python 代码行里
出现与否）**只当线索、不参与判定**，让这处盲区可复核。

## 字段级看不见的那一面（第二部分）

有四类东西键级扫不到，逐只敌人看：

* `enemyData.description` 正文里写的机制；
* `talentBlackboard` 里有键但**值全为 0／空**（有意图没数值）——本工具把它做成
  `ZERO` 标记并单独计数；
* prts 侧 `enemy_level.talent` 与 `enemy.ability`（`data/enemydb.sqlite`）——
  这一侧经常写着 gamedata 里没有的机制；
* 敌方技能的 `blackboard` 键（并入键空间，走同一套判据）。

正文/图鉴那一侧是**自然语言**，本工具只有三条具名判据：

* **C1** 命中 `UNMODELLED_ENEMY_ABILITIES` 的 `py_tokens` **且该敌人在它的 `carriers` 里**
  ⇒ 具名 unported（已登记）；命中词元但不在载体里 ⇒ 判不了（不许把别人的登记记到它头上）；
* **C2** 命中 `unportedLines` 的字面线名 ⇒ 具名 unported（已登记）；
* **C3** 该敌人在 gamedata 侧**一个机制键都没有**（天赋黑板空且无技能）而正文提到了机制
  ⇒ `PROSE_NO_KEY`：**登记为共同边界**（两侧连字段都没有 ⇒ 闸门对它永远沉默），
  **不计红**——那不是 Go 的欠账，是两台引擎共同的边界。

三条都不命中的，**判不了**（`PROSE_NO_CRITERION`）：正文是中文散文，
本工具没有把中文机制名映射到键名的具名判据。**判不了不做成红**——
永久假红等于没有判据（本仓记过），但它**逐条落盘、并在汇总行里带数**，
不许被当成「查过了没问题」。

## 退出码

* `0` 全绿（无**真红**）；
* `1` 有真红（Go 的欠账）；共同边界与判不了**都不计入**；
* `3` 仪器缺输入（数据文件缺失、关卡清单为空、Go 源码目录为空）；
* `5` 本判据自己崩了（与业务态不重叠，本仓惯例）。

用法：
    python tools\\check_enemy_mech_go.py                      # 缓存可达的全部关卡
    python tools\\check_enemy_mech_go.py main_00-01 main_02-07
    python tools\\check_enemy_mech_go.py --mutate              # 反向守卫（四条腿）
    python tools\\check_enemy_mech_go.py --md out/x.md         # 另写一份逐章 markdown
"""
from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_DIR = ROOT / "rios-sim"
GDATA = ROOT / "data" / "gamedata"
ENEMY_DB = GDATA / "map.ark-nights.com" / "levels" / "enemydata" / "enemy_database.json"
LEVEL_INDEX = GDATA / "_level_index.json"
LEVELS_DIR = GDATA / "map.ark-nights.com" / "levels"
ENEMY_SQLITE = ROOT / "data" / "enemydb.sqlite"

RC_OK, RC_RED, RC_NO_INPUT, RC_CRASH = 0, 1, 3, 5

#: 文件角色（**这一栏是判据的一部分，不是注释**）。
#: 一个派生字段出现在哪些文件里，决定它算不算「被消费」。
FILL_FILES = {"enemy_mech.go", "enemy_derive.go"}      # 从黑板推字段
SPEC_FILES = {"spawns.go", "wire.go", "mechspec.go", "buildspec.go", "specgo.go",
              "enemy.go"}                              # 规格构造／序列化／结构定义
GATE_FILES = {"unsupported.go"}                        # 闸门
#: 别的**键空间**：这些文件里的黑板读取属于干员天赋／机制规格，不是敌人天赋黑板。
#: 同名键在那里被读到**不构成消费**，但必须打印出来（不许静默丢掉一处真命中）。
OTHER_KEYSPACE = {"operators.go", "operators_go.go", "operator.go", "operator_traits.go",
                  "operator_aspd.go", "talentfinders.go", "snowspec.go", "skill.go",
                  "skillmeta.go", "loadout.go", "profile.go", "panelfold.go"}

RE_HIT = re.compile(r"\bbb(?:Float|Int|Value)\([^,\n]*,\s*\"([^\"]+)\"")
RE_HIT2 = re.compile(r"\bbb\[\"([^\"]+)\"\]")
RE_FIELD = re.compile(r"\b(?:out|s|c)\s*\.\s*([A-Z]\w*)\s*=")
RE_AFFINITY = re.compile(r"([a-zA-Z_]\w*)\s*=\s*AffinityOf\(bb,\s*\"([^\"]+)\"\)")
RE_PREFIX_CAT = re.compile(r"(?:sp\.)?(?:prefix|pre)\s*\+\s*\"([^\"]*)\"")
RE_GO_LITERAL = re.compile(r"\"([^\"\\\n]{1,80})\"")
#: 源字段 → 规格字段的搬移（`v.RebornDelay = es.RebornDuration`）。
#: ★ 不过这一层会造出**假红**：`RebornDuration` 这个名字在 `sim.go` 里一处都没有，
#: 真正被读的是规格侧的名字 `RebornDelay`（`sim.go:868`）。同义名要一起找。
RE_SPEC_MOVE = re.compile(r"\bv\.([A-Z]\w*)\s*=\s*(?:derefOr\(&)?es\.([A-Z]\w*)")

#: 重生族「后缀 → 下游字段」。**每条都带锚**：锚定字面量必须在 Go 源码里现算到，
#: 否则本工具报错退出（缺输入），不许带着一条没根据的映射往下跑。
#: 理由：`Reborn.invincible` 与 `Reborn.reborn_duration` 同前缀不同命，
#: 按前缀一律放行会把红洗成绿。
REBORN_SUFFIX_FIELD: dict[str, tuple[tuple[str, ...], str]] = {
    "reborn_duration": (("RebornDuration",), "Reborn.reborn_duration"),
    "max_hp_ratio": (("RebornHPRatio",), "Reborn.max_hp_ratio"),
    "duration": (("RebornDuration",), "Reborning.duration"),
    "interval": (("RebornInterval", "RebornSummons"), "interval"),
    "value": (("RebornPollut",), "value"),
    "def_add": (("RebornDefAdd",), "def_add"),
    "damage_magic": (("RebornDamageMagic",), "damage_magic"),
    "enemy_key": (("RebornSummons",), "enemy_key"),
    "cnt": (("RebornSummons",), "cnt"),
}


#: 「这段正文在描述机制」的词表（**判据的一部分，随输出一起印**）。
#: 它的唯一职责是把**风味文案**（「野生的被感染生物。」）与**机制正文**分开；
#: 命中不了的条目**不做静默丢弃**：另记为 `FLAVOR` 并把全文写进落盘文档。
#:
#: ⚠ 三个泛词**故意不收**：`攻击力`／`防御力`／`造成`／`受到`／`伤害`／`范围`／`层`。
#: 实测它们会把风味文案判成机制正文（「整合运动的近身作战人员，**以高攻击力见长**。」
#: 会因此翻红）。收窄的代价写在文档第七节：词表窄了会把机制正文错判成风味，
#: 那一节列全文就是为了让这件事**可复核**，而不是靠词表自己说自己对。
MECH_KEYWORDS = (
    "免疫", "阻挡", "攻击速度", "移动速度", "攻速", "每秒", "召唤", "半径",
    "眩晕", "冻结", "寒冷", "沉睡", "沉默", "隐匿", "无敌", "自缚", "缴械",
    "恐惧", "麻痹", "浮空", "束缚", "迷彩", "失衡", "嘲讽", "法术抗性",
    "生命值", "退场", "重生", "复活", "回复", "吸取", "叠加", "技力", "停顿",
    "脆弱", "附着", "弹道", "索敌", "标记", "特殊机制", "不进行普通攻击",
    "强制触发", "召唤物", "天赋",
)


def looks_mech(text: str) -> bool:
    return any(k in text for k in MECH_KEYWORDS)


def strip_line_comments(name: str, text: str) -> str:
    """去掉 `//` 注释（Go 源码里的注释会带引号，不剥会把注释抄成字面量）。"""
    out = []
    for line in text.splitlines():
        i = line.find("//")
        out.append(line if i < 0 else line[:i])
    return "\n".join(out)


RE_KEYLIKE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.\[\]@:-]*$")


def sha16(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()[:16]


def ascii_only(s: str) -> str:
    """机读行一律 ASCII：非 ASCII 一律退化成 \\uXXXX（信息不丢）。"""
    return "".join(ch if 32 <= ord(ch) < 127 else "\\u%04x" % ord(ch) for ch in str(s))


def snake(name: str) -> str:
    """Go 的 CamelCase 字段名 → Python 的 snake_case（两张登记表用后者写）。"""
    return re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower()


class PyFace:
    """**Python 侧**的消费面——判据要与 Go 面**同构**，才谈得上「两边求差」。

    ★ 为什么要两边：只量「Go 读不读」会把**两台引擎共同的边界**记成 Go 的欠账。
    `tools/audit_unmodelled_abilities.py` 的开头就立过这条规矩
    （「原版战斗层也零命中 ⇒ 两台引擎同样不建模 ⇒ 对拍成立 ⇒ 不该进闸门」）。

    结构上与 `GoFace` 一一对应：

    * **填充侧**（对应 Go 的 FILL）＝ `ak_tactic/gamedata/enemy.py`——
      它读黑板、推字段（`_bb_float(bb, "Passive_Hit.cnt")`、`bb.get("Shield.shield_hp_ratio")`）。
    * **行为侧**（对应 Go 的行为文件）＝ `ak_tactic/battle/*.py`。
    * **读取点**＝键的**字面串**出现在这两侧的**代码行**里（docstring 与注释不算，
      口径与 `audit_unmodelled_abilities.py` 同）。
    * **具名族**＝ `_REBORN_SPECS` 的前缀与后缀（从源码现算，含 `f"{prefix}…"` 拼接）。
    * **技能读取器**＝ `PROSE_SKILL_ATTACK` 的 prefabKey ＋ `num("…")` 读的黑板键。

    ⚠ 它的**盲区**（写在这里，不藏在注释里）：Python 若把同一机制实现**在
    完全不同的键名下**，本类看不见——那是「未核」，不是「没建」。
    ⇒ 输出里另印一列 `py_token`（键的机制名在 Python 代码行里出现与否），
       **只当线索、不参与判定**，让这一处盲区可复核。
    """

    def __init__(self, root: Path) -> None:
        self.fill = [root / "ak_tactic" / "gamedata" / "enemy.py"]
        self.behaviour_files = sorted((root / "ak_tactic" / "battle").glob("*.py"))
        self.reads: dict[str, list[tuple[str, int]]] = {}
        self._beh: dict[str, list[tuple[str, int]]] = {}
        self._code: dict[str, list[tuple[int, str]]] = {}
        for p in self.fill + self.behaviour_files:
            self._code[p.relative_to(root).as_posix()] = _code_lines(p)
        self._collect_reads()
        self._collect_families(root)

    def _collect_reads(self) -> None:
        self.keyfield: dict[str, str] = {}
        for p in self.fill:
            name = p.relative_to(ROOT).as_posix()
            lines = [ln for _i, ln in self._code[name]]
            for i, line in self._code[name]:
                for lit in RE_GO_LITERAL.findall(line):
                    if lit and "." in lit:
                        self.reads.setdefault(lit, []).append((name, i))
                m = re.search(r"(?:out\[\"(\w+)\"\]|self\.(\w+))\s*=", line)
                if m:
                    fld = m.group(1) or m.group(2)
                    for lit in RE_GO_LITERAL.findall(line):
                        if lit and "." in lit:
                            self.keyfield.setdefault(lit, fld)

    def _collect_families(self, root: Path) -> None:
        text = "\n".join(line for _i, line in self._code["ak_tactic/gamedata/enemy.py"])
        self.reborn_suffixes: dict[str, set[str]] = {"Reborn.": set(), "Reborning.": set()}
        self.reborn_site: list[tuple[str, int]] = []
        for i, line in self._code["ak_tactic/gamedata/enemy.py"]:
            for lit in RE_GO_LITERAL.findall(line):
                if not RE_KEYLIKE.match(lit):
                    continue
                for pre in self.reborn_suffixes:
                    if lit.startswith(pre):
                        self.reborn_suffixes[pre].add(lit[len(pre):])
                        self.reborn_site.append(("ak_tactic/gamedata/enemy.py", i))
        fsuf = set(re.findall(r"\{prefix\}([A-Za-z0-9_.\[\]]*)", text))
        fsuf |= set(re.findall(r"\{pre\}([A-Za-z0-9_.\[\]]*)", text))
        for pre in self.reborn_suffixes:
            self.reborn_suffixes[pre] |= fsuf
            base = set(self.reborn_suffixes[pre]) - fsuf
            for c in fsuf:
                if c.endswith("."):
                    self.reborn_suffixes[pre] |= {c + s for s in base}
        #: 技能读取器：`PROSE_SKILL_ATTACK` 的 prefabKey ＋ `num("…")` 的键
        self.prose_prefabs = set(re.findall(r"^\s*\"([^\"]+)\":\s*\{", text, re.M))
        self.prose_keys = set(re.findall(r'\bnum\("([^"]+)"\)', text))

    def read(self, key: str) -> list[tuple[str, int]]:
        return self.reads.get(key, [])

    def token_hit(self, token: str) -> list[tuple[str, int]]:
        out = []
        for name, lines in self._code.items():
            for i, line in lines:
                if token and token in line:
                    out.append((name, i))
        return out

    def behaviour(self, field: str) -> list[tuple[str, int]]:
        if field in self._beh:
            return self._beh[field]
        rx = re.compile(r"\b%s\b" % re.escape(snake(field)))
        out = []
        for p in self.behaviour_files:
            name = p.relative_to(ROOT).as_posix()
            for i, line in self._code[name]:
                if rx.search(line):
                    out.append((name, i))
        self._beh[field] = out
        return out

    def family_of(self, key: str) -> tuple[tuple[str, ...], str, list] | None:
        for pre in self.reborn_suffixes:
            if key.startswith(pre):
                suf = key[len(pre):]
                if suf not in self.reborn_suffixes[pre]:
                    return (), "SUFFIX_NOT_READ", []
                base = suf
                for c in self.reborn_suffixes[pre]:
                    if c.endswith(".") and base.startswith(c):
                        base = base[len(c):]
                ent = REBORN_SUFFIX_FIELD.get(base)
                if ent is None:
                    return (), "SUFFIX_UNMAPPED", []
                return ent[0], "reborn", self.reborn_site[:1]
        return None

    def consumes(self, key: str, kind: str, prefab: str, fields) -> tuple[bool, str]:
        """Python 侧到底有没有落点。返回 (是否有, 证据串)。"""
        if kind == "skill":
            if prefab in self.prose_prefabs and key in self.prose_keys:
                for fd in fields:
                    b = self.behaviour(fd)
                    if b:
                        return True, "%s:%d" % b[0]
            return False, ""
        sites = self.read(key)
        fam = self.family_of(key)
        if fam is not None and fam[1] in ("SUFFIX_NOT_READ", "SUFFIX_UNMAPPED"):
            return False, ""
        if not sites and fam is None:
            return False, ""
        probe = list(fields)
        if not probe:
            probe = [self.keyfield.get(key, "")]
        if fam is not None and fam[0]:
            probe = list(fam[0])
        for fd in probe:
            if not fd:
                continue
            b = self.behaviour(fd)
            if b:
                return True, "%s:%d" % b[0]
        return False, ""


def _code_lines(path: Path) -> list[tuple[int, str]]:
    """一个 .py 的**代码行**（跨行字符串与注释行不算）——口径同 audit_unmodelled_abilities.py。"""
    import ast
    src = path.read_text(encoding="utf-8")
    try:
        skip = _docstring_lines(ast.parse(src))
    except SyntaxError:
        skip = set()
    out = []
    for i, line in enumerate(src.splitlines(), 1):
        s = line.strip()
        if i in skip or s.startswith("#"):
            continue
        out.append((i, line))
    return out


def _docstring_lines(tree) -> set:
    import ast
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.end_lineno and node.end_lineno > node.lineno):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


# --------------------------------------------------------------- Go 消费面

class GoFace:
    """Go 侧的黑板消费面，全部从 `rios-sim/*.go` 现算。"""

    def __init__(self, srcs: dict[str, str]) -> None:
        self.srcs = srcs
        self.reads: dict[str, list[tuple[str, int, str]]] = {}
        self.keyfield: dict[str, str] = {}
        self.other_keyspace: dict[str, list[tuple[str, int]]] = {}
        self._beh_cache: dict[str, list[tuple[str, int]]] = {}
        self.aliases: dict[str, set[str]] = {}
        self.line_field: dict[str, int] = {}
        self._collect_reads()
        self._collect_aliases()
        self._collect_families()

    # ---- 读取点
    def _collect_reads(self) -> None:
        """**只把 `FILL_FILES` 里的黑板读取当成「敌人天赋黑板的读者」。**

        判据不是"看起来像"：敌人天赋黑板的**唯一**入口是
        `bb := s.TalentBlackboard`（`enemy_derive.go:243`），而 `s.TalentBlackboard`
        只在这两个文件里被当黑板用。别的文件里的 `bbFloat(bb,"…")`／`bb["…"]`
        读的是**别的黑板**（关卡 runes、干员天赋、机制规格）——把那些算成消费，
        就会用一个同名键把红洗成绿（本仓记过这一类假清账）。
        它们照样登记进 `other_keyspace`，在需要时**打印出来**，只是不改变判定。
        """
        for name, text in self.srcs.items():
            lines = text.splitlines()
            for i, line in enumerate(lines, 1):
                keys = RE_HIT.findall(line) + RE_HIT2.findall(line)
                if not keys:
                    continue
                if name not in FILL_FILES:
                    for k in keys:
                        self.other_keyspace.setdefault(k, []).append((name, i))
                    continue
                for k in keys:
                    self.reads.setdefault(k, []).append((name, i, line.strip()))
                # 字段关联：本行起 4 行内第一处 `out.X =` / `s.X =`
                fld = None
                for j in range(i - 1, min(i + 3, len(lines))):
                    m = RE_FIELD.search(lines[j])
                    if m:
                        fld = m.group(1)
                        break
                if fld:
                    for k in keys:
                        self.keyfield.setdefault(k, fld)

    # ---- 同义名（源字段 → 规格字段）
    def _collect_aliases(self) -> None:
        for name, text in self.srcs.items():
            if name not in SPEC_FILES:
                continue
            for line in text.splitlines():
                m = RE_SPEC_MOVE.search(line)
                if m:
                    self.aliases.setdefault(m.group(2), set()).add(m.group(1))

    # ---- 具名族（重生族 / 相性族）
    def _collect_families(self) -> None:
        # 重生族：字面键里的后缀 ＋ `prefix + "X"` 拼接出来的后缀
        self.reborn_suffixes: dict[str, set[str]] = {"Reborn.": set(), "Reborning.": set()}
        self.reborn_site: list[tuple[str, int]] = []
        self.reborn_anchor: set[str] = set()
        #: ⚠ 只扫 `enemy_derive.go`：别的文件里也有叫 `prefix` 的局部变量
        #: （`mechspec.go` 的分支名、`buildspec.go` 的打印串），扫全仓会把
        #: `": "`／`"_1"`／`"."` 这类东西抄成「重生族后缀」，把红洗成绿。
        text = strip_line_comments("enemy_derive.go", self.srcs.get("enemy_derive.go", ""))
        for i, line in enumerate(text.splitlines(), 1):
            for m in RE_GO_LITERAL.finditer(line):
                lit = m.group(1)
                if not RE_KEYLIKE.match(lit):
                    continue
                for pre in self.reborn_suffixes:
                    if lit.startswith(pre):
                        self.reborn_suffixes[pre].add(lit[len(pre):])
                        self.reborn_anchor.add(lit)
                        self.reborn_site.append(("enemy_derive.go", i))
        cat: set[str] = set()
        for line in text.splitlines():
            for m in RE_PREFIX_CAT.finditer(line):
                if RE_KEYLIKE.match(m.group(1)) or not m.group(1):
                    cat.add(m.group(1))
        self.concat_suffixes = set(cat)
        for pre in self.reborn_suffixes:
            self.reborn_suffixes[pre] |= cat
        # 二级前缀（`prefix + "dhnzzh_reborn_c2."`）：其后又拼了同一套后缀
        for pre in list(self.reborn_suffixes):
            base = set(self.reborn_suffixes[pre]) - cat
            for c in cat:
                if c.endswith("."):
                    self.reborn_suffixes[pre] |= {c + s for s in base}
        # 相性族：AffinityOf 的前缀实参（同行给字段）与 p3rSlots 的槽位
        self.p3r_prefixes: dict[str, str] = {}
        self.p3r_site: list[tuple[str, int]] = []
        self.p3r_slots: set[str] = set()
        for name, text in self.srcs.items():
            lines = text.splitlines()
            in_slots = False
            for i, line in enumerate(lines, 1):
                m = RE_AFFINITY.search(line)
                if m:
                    self.p3r_prefixes[m.group(2)] = m.group(1)
                    self.p3r_site.append((name, i))
                if "p3rSlots" in line and "[]" in line:
                    in_slots = True
                if in_slots:
                    for lit in RE_GO_LITERAL.findall(line):
                        if lit.isupper() and len(lit) > 3:
                            self.p3r_slots.add(lit)
                    if re.match(r"^\}", line.strip()):
                        in_slots = False
        # Mode_A / Mode_B：`for _, m := range []string{` 那一行的字面量，
        # 且本文件里确有 `s.Modes = modes` 这句（两处都要在，否则族不成立）。
        self.modes_prefixes: set[str] = set()
        self.modes_site: list[tuple[str, int]] = []
        for name, text in self.srcs.items():
            if not re.search(r"\bs\.Modes\s*=\s*modes\b", text):
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if "[]string{" in line and "Mode_" in line:
                    self.modes_prefixes |= {x for x in RE_GO_LITERAL.findall(line)
                                            if x.startswith("Mode_")}
                    self.modes_site.append((name, i))
        for p in self.modes_prefixes:
            self.p3r_prefixes.setdefault(p, "Modes")
        # 重生族映射的锚：每一条的锚定字面量都要在源码里
        self.reborn_missing = [anchor for (_f, anchor) in REBORN_SUFFIX_FIELD.values()
                               if anchor not in self.reborn_anchor
                               and anchor not in self.concat_suffixes]

    # ---- 行为落点
    def behaviour(self, field: str) -> list[tuple[str, int]]:
        if field in self._beh_cache:
            return self._beh_cache[field]
        names = {field} | self.aliases.get(field, set())
        rxs = [re.compile(r"\.%s\b" % re.escape(n)) for n in sorted(names)]
        out: list[tuple[str, int]] = []
        for name, text in self.srcs.items():
            if name in FILL_FILES or name in SPEC_FILES or name in GATE_FILES:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                if any(rx.search(line) for rx in rxs):
                    out.append((name, i))
        self._beh_cache[field] = out
        return out

    def family_of(self, key: str):
        """具名族归属。返回 (字段元组, 族名, 出处)；不属于任何族返回 None。

        后缀不在 Go 现算的后缀集里时返回 `((), "SUFFIX_NOT_READ", [])`——
        那是**红**，不是「不属于族」。
        """
        for pre in self.reborn_suffixes:
            if key.startswith(pre):
                suf = key[len(pre):]
                if suf not in self.reborn_suffixes[pre]:
                    return (), "SUFFIX_NOT_READ", []
                base = suf
                for c in self.concat_suffixes:
                    if c.endswith(".") and base.startswith(c):
                        base = base[len(c):]
                ent = REBORN_SUFFIX_FIELD.get(base)
                if ent is None:
                    return (), "SUFFIX_UNMAPPED", []
                return ent[0], "reborn", self.reborn_site[:1]
        if "." in key:
            p, s = key.rsplit(".", 1)
            if p in self.p3r_prefixes and s in self.p3r_slots:
                return (self.p3r_prefixes[p],), "p3r", self.p3r_site[:1]
        return None


REBORN_FAMILY = ("RebornCount", "RebornDuration", "RebornHPRatio", "RebornPrefix",
                 "RebornInterval", "RebornPollut", "RebornDefAdd", "RebornDamageMagic",
                 "RebornSummons")   #: 只在文档里用（人读的族名）


# --------------------------------------------------------------- 登记表

def named_unported() -> tuple[dict[str, str], dict[str, str], dict[str, list[str]]]:
    """三张具名登记表，出处＝源码行号（**现读 mech.py 的原文行**，不是抄下来的）。"""
    from ak_tactic.simgo import mech
    text = Path(mech.__file__).read_text(encoding="utf-8").splitlines()
    by_field: dict[str, str] = {}
    for dictname in ("ENEMY_BEHAVIOR_FIELDS", "ENEMY_BEHAVIOR_ATTRS"):
        table = getattr(mech, dictname)
        line = 0
        for i, src in enumerate(text, 1):
            if re.match(r"%s\s*[:=]" % re.escape(dictname), src):
                line = i
                break
        for k in table:
            by_field[k] = "ak_tactic/simgo/mech.py:%d(%s)" % (line, dictname)
    tok_carrier: dict[str, list[str]] = {}
    for _name, spec in mech.UNMODELLED_ENEMY_ABILITIES.items():
        for t in spec["py_tokens"]:
            tok_carrier.setdefault(t, []).extend(spec["carriers"])
    return by_field, {}, tok_carrier


def unsupported_lines(srcs: dict[str, str]) -> tuple[set[str], dict[str, int]]:
    """`rios-sim/unsupported.go` 里的具名未搬线（线名 → 行号）。"""
    text = srcs.get("unsupported.go", "")
    out: dict[str, int] = {}
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        m = re.match(r'"([a-z_]+)"\s*,', s)
        if m:
            out.setdefault(m.group(1), i)
    return set(out), out


def camel(name: str) -> str:
    """`death_token` → `DeathToken`（具名未搬线 ↔ 派生字段名的机械换算）。"""
    return "".join(p[:1].upper() + p[1:] for p in name.split("_"))


def line_field_map(names: dict[str, int]) -> dict[str, tuple[str, int]]:
    """具名未搬线（线名 → 行号）→ 它对应的 Go 派生字段名（只认对得上的）。"""
    return {camel(n): (n, ln) for n, ln in names.items()}


#: ★ **具名 unported 登记**（第 27 套自己的登记表，2026-09-24 父会话裁定走「登记」）。
#:
#: 登记的是**真红**里那些「Go 读了黑板、填进了 `EnemyStats`、模拟里没人读」的键：
#: 它们是**已知行为分歧**，**不是已修复**；登记的目的是让汇总行的绿**盖不住**它们。
#:
#: 每条四样，缺一不算：
#:   * `field` —— Go 侧的派生字段名（与源码对不上 ⇒ 当场判为**仪器错**，rc=3）；
#:   * `why`   —— 一句人话：这条机制是什么；
#:   * `gate`  —— **哪条判据判它「没有行为落点」**：本判据的 `go.behaviour(field)`
#:     在行为文件集（`rios-sim/*.go` 去掉 填充／规格／闸门）里为空；
#:   * `corrobor` —— 引擎自己承认过的出处（有就写，没有就不写）。
#: 读取点（文件:行）不写死，由 `registry_status()` 从源码**现算**。
#:
#: ★ **出处不许过期**（父会话第 4 条附加条件：这是守卫，不是说明）：
#: `registry_status()` 每次现算——读取点还在不在、字段名还对不对、字段**是否已经有了
#: 行为落点**。任何一条不成立，这条登记**当场失效**（键退回真红）并印
#: `MECH-STALE-REGISTRY`。**登记表退化成永久的假绿**是这条守卫唯一要防的东西。
#:
#: ★ 这些**不**进 `rios-sim/unsupported.go` 的拒跑线：进了会把整个怀黍离
#: （以及任何含这些敌人的关卡）全部拒跑，代价远大于收益。理由写在文档第八节。
NAMED_UNPORTED_KEYS: dict[str, dict[str, str]] = {
    "AuraHit.hp_ratio": {
        "field": "AuraHitRatio",
        "why": "进入阻流阀半径 0.5 内立刻造成真伤（田鼷力士 / 猛士 / 飞贼 / 大盗）",
        "gate": "go.behaviour(AuraHitRatio) 为空",
        "corrobor": "",
    },
    "DeathPassive.cnt": {
        "field": "DeathCnt",
        "why": "被击倒时给予可部署装置的个数",
        "gate": "go.behaviour(DeathCnt) 为空",
        "corrobor": "装置那一半另有 unsupported.go:121 的 death_token 线",
    },
    "SpeedUp.move_speed": {
        "field": "SpeedupMove",
        "why": "受击且未被阻挡时的移速增益",
        "gate": "go.behaviour(SpeedupMove) 为空",
        "corrobor": "rios-sim/sim.go:2789-2790（引擎自己写着「速度提升（SpeedUp.*）还没接，"
                    "接的时候加在这里，不要另开调用点」）",
    },
    "SpeedUp.duration": {
        "field": "SpeedupDuration",
        "why": "受击且未被阻挡时的加速持续时间",
        "gate": "go.behaviour(SpeedupDuration) 为空",
        "corrobor": "rios-sim/sim.go:2789-2790（同上）",
    },
    "SpeedUp.cooldown": {
        "field": "SpeedupCooldown",
        "why": "受击且未被阻挡时的加速冷却",
        "gate": "go.behaviour(SpeedupCooldown) 为空",
        "corrobor": "rios-sim/sim.go:2789-2790（同上）",
    },
    "Passive_Hit.extra_value": {
        "field": "PhitExtra",
        "why": "蜕皮那一路里读数存疑的额外项（`enemy.py:315-320` 也登记为只读不用）",
        "gate": "go.behaviour(PhitExtra) 为空",
        "corrobor": "",
    },
    "Passive_Hit.other_cnt": {
        "field": "PhitWeightCnt",
        "why": "蜕皮时按层数减重量等级的计数",
        "gate": "go.behaviour(PhitWeightCnt) 为空",
        "corrobor": "rios-sim/sim.go:2826-2829（Go 侧没有重量字段、故不减，"
                    "写在 `docs/uncertainties.md` 的口径里）",
    },
    "PassiveM2.value": {
        "field": "Pm2PollutThreshold",
        "why": "明识形态的病害值阈值",
        "gate": "go.behaviour(Pm2PollutThreshold) 为空",
        "corrobor": "",
    },
    "PassiveM2.dhnzzh_clean_water.magic_resistance": {
        "field": "Pm2CleanRes",
        "why": "明识形态处于「清水」时的法术抗性",
        "gate": "go.behaviour(Pm2CleanRes) 为空",
        "corrobor": "",
    },
    "PassiveM2.dhnzzh_clean_water.move_speed": {
        "field": "Pm2CleanMove",
        "why": "明识形态处于「清水」时的移速",
        "gate": "go.behaviour(Pm2CleanMove) 为空",
        "corrobor": "",
    },
    "DeathPassive.token_key": {
        "field": "DeathToken",
        "why": "被击倒时给的是哪个可部署装置",
        "gate": "go.behaviour(DeathToken) 为空",
        "corrobor": "rios-sim/unsupported.go:121（unportedLines 的 death_token）",
    },
}


def registry_status(go: GoFace) -> tuple[dict[str, dict], list[str], list[str]]:
    """现算登记表的三条腿：读取点还在 ／ 字段名还对 ／ 字段**还没有**行为落点。

    返回 `(有效登记, 过期条目, 破损条目)`。过期与破损都**必须被印出来**：
    过期＝该登记的机制已经被接上（登记必须消失）；破损＝登记与源码脱节（仪器错）。
    """
    ok: dict[str, dict] = {}
    stale: list[str] = []
    broken: list[str] = []
    for key, ent in NAMED_UNPORTED_KEYS.items():
        sites = go.reads.get(key, [])
        if not sites:
            broken.append("%s：读取点不见了（现算为空）" % key)
            continue
        fld = ent["field"]
        got = go.keyfield.get(key, "")
        if got != fld:
            broken.append("%s：字段名对不上（源码现算 %r，登记 %r）" % (key, got, fld))
            continue
        beh = go.behaviour(fld)
        if beh:
            stale.append("%s：字段 %s 已有行为落点 %s:%d —— 登记失效"
                         % (key, fld, beh[0][0], beh[0][1]))
            continue
        ok[key] = dict(ent, read="%s:%d" % (sites[0][0], sites[0][1]))
    return ok, stale, broken


# --------------------------------------------------------------- 数据侧

def cached_levels() -> list[str]:
    idx = json.loads(LEVEL_INDEX.read_text(encoding="utf-8"))
    return sorted(lid for lid, e in idx.items()
                  if (LEVELS_DIR / e["data_path"]).exists())


def content_count(levels: list[str]) -> int:
    """这些**关卡键**对应几份**不同的关卡内容**。

    ⚠ 与 `len(levels)` **不是同一个数**：`main_XX-YY#f#`（四星档）与普通档共用同一个
    `data_path`，差别只在标签字段。同一口径在 `tools/check_go_all.py` 的
    「取证范围」那一行也印（两个数并排），两处口径必须一致。
    """
    try:
        idx = json.loads(LEVEL_INDEX.read_text(encoding="utf-8"))
    except Exception:                                       # noqa: BLE001
        return len(levels)
    return len({idx[l]["data_path"] for l in levels if l in idx})


def chapter_of(level: str) -> str:
    m = re.match(r"^([A-Za-z]+_\d+)-", level)
    return m.group(1) if m else level


def unwrap(x):
    return x.get("m_value") if isinstance(x, dict) and "m_value" in x else x


def load_gamedata() -> tuple[dict, dict]:
    """读原始 enemy_database：返回 (描述表, 旁支信息表)。

    描述表键是 `(enemy_key, level)`；旁支表给出每个键**最高档**的名字。
    """
    raw = json.loads(ENEMY_DB.read_text(encoding="utf-8"))
    descs: dict[tuple[str, int], str] = {}
    names: dict[str, str] = {}
    for entry in raw["enemies"]:
        key = entry.get("Key", "")
        best = -1
        for item in entry.get("Value", []):
            lv = int(item.get("level", 0) or 0)
            ed = item.get("enemyData") or {}
            d = unwrap(ed.get("description"))
            if isinstance(d, str) and d.strip():
                descs[(key, lv)] = d.strip()
            nm = unwrap(ed.get("name"))
            if isinstance(nm, str) and nm.strip() and lv >= best:
                names[key] = nm.strip()
                best = lv
    return descs, names


def desc_for(descs: dict, key: str, lv: int) -> str:
    if (key, lv) in descs:
        return descs[(key, lv)]
    same = sorted(l for (k, l) in descs if k == key)
    if not same:
        return ""
    near = [l for l in same if l <= lv] or same
    return descs[(key, max(near) if near else same[0])]


def prts_rows() -> dict[str, list[tuple[int, str, str]]]:
    """prts 侧：页码 → [(level, talent, ability)]。只读打开（不许静默建 0 字节库）。"""
    con = sqlite3.connect("file:%s?mode=ro" % ENEMY_SQLITE.as_posix(), uri=True)
    out: dict[str, list[tuple[int, str, str]]] = {}
    ability = {}
    for page, txt in con.execute("select name, ability from enemy"):
        if txt and txt.strip():
            ability[page] = txt.strip()
    for page, lv, talent in con.execute(
            "select name, level, talent from enemy_level"):
        out.setdefault(page, []).append(
            (int(lv or 0), (talent or "").strip(), ability.get(page, "")))
    con.close()
    return out


# --------------------------------------------------------------- 取证与判定

class Findings:
    def __init__(self) -> None:
        self.chapters: dict[str, dict] = {}
        self.rows: list[dict] = []

    def chapter(self, ch: str) -> dict:
        return self.chapters.setdefault(ch, {
            "enemies": set(), "go": {}, "unported": {}, "red": {}, "common": {},
            "go_only": {}, "prose_unported": {}, "prose_nokey": {}, "prose_und": {},
            "flavor": [], "zero": {}, "items": [], "keyn": 0,
        })


def run(face: GoFace, py: PyFace, levels: list[str], descs, names, prts, r_a, r_b,
        mutate: bool, carriers, named_keys: dict) -> Findings:
    from ak_tactic.gamedata import load_stage, EnemyLibrary
    from ak_tactic.gamedata.source import GameDataSource

    src = GameDataSource()
    lib = EnemyLibrary(src)
    f = Findings()

    seen: dict[tuple[str, int], str] = {}
    for lv in levels:
        st = load_stage(lv, source=src)
        for sp in getattr(st, "spawns", []) or []:
            eid = getattr(sp, "enemy_id", None)
            if not eid:
                continue
            seen.setdefault((eid, getattr(sp, "level", 1) or 1), lv)

    if mutate:
        pass   #: 反向守卫现在**不改取证面**（见 `_mutate_verdict`：它直接调判据本体）

    # prts 只按**这次取证范围里的敌人名**去查
    by_name: dict[str, list[tuple[int, str, str]]] = {}
    for page, rows in prts.items():
        by_name[page] = rows

    for (eid, lv), src_level in sorted(seen.items()):
        ch = chapter_of(src_level)
        c = f.chapter(ch)
        try:
            e = lib.get(eid, level=lv)
        except Exception:                                  # noqa: BLE001
            continue
        name = e.name or names.get(eid, eid)
        bb = dict(e.talent_blackboard or {})
        skills = tuple(getattr(e, "skills_raw", None) or ())
        c["enemies"].add((eid, lv))

        # ---- 键级：天赋黑板
        for k, v in sorted(bb.items()):
            it = judge_key(face, py, k, "talent", "", r_a, r_b, named_keys)
            if v in (0, "", None, 0.0):
                c["zero"].setdefault(k, 0)
                c["zero"][k] += 1
                it["zero"] = True
            record(c, ch, name, eid, k, it)
        # ---- 键级：敌方技能黑板
        for sk in skills:
            if not isinstance(sk, dict):
                continue
            pk = unwrap(sk.get("prefabKey")) or ""
            for b in (sk.get("blackboard") or []):
                k = unwrap(b.get("key")) if isinstance(b, dict) else None
                if not k:
                    continue
                it = judge_key(face, py, str(k), "skill", str(pk), r_a, r_b, named_keys)
                record(c, ch, name, eid, "%s@%s" % (pk, k), it)

        if eid == "__MUTANT__":
            continue  #: 不再使用合成敌人（守卫改为直接调判据本体）

        # ---- 正文级：gamedata 描述 ／ prts 天赋 ／ prts 能力
        has_keys = bool(bb) or bool(skills)
        prose: list[tuple[str, str, str]] = []
        d = desc_for(descs, eid, lv)
        if d:
            prose.append(("gamedata.description", eid, d))
        rows = by_name.get(name)
        if rows:
            exact = [r for r in rows if r[0] == lv] or [r for r in rows if r[0] == 0]
            pick = exact[0] if exact else rows[0]
            if pick[1]:
                prose.append(("prts.enemy_level.talent", "%s@%d" % (name, pick[0]), pick[1]))
            if pick[2]:
                prose.append(("prts.enemy.ability", name, pick[2]))
        for kind, src_id, text in prose:
            if not looks_mech(text):
                c["flavor"].append({"chapter": ch, "enemy": name, "key": src_id,
                                    "kind": kind, "verdict": "FLAVOR", "why": "NO_MECH_KEYWORD",
                                    "evidence": "", "text": text})
                continue
            v, why, ev = judge_prose(carriers, r_b, name, text, has_keys, carriers)
            slot = {"UNPORTED": "prose_unported", "NOKEY": "prose_nokey",
                    "UNDECIDABLE": "prose_und"}.get(v, "prose_und")
            dedup = (name, kind, v)
            if dedup in c[slot]:
                continue
            c[slot][dedup] = 1
            c["items"].append({"chapter": ch, "enemy": name, "key": src_id,
                               "kind": kind, "verdict": v, "why": why,
                               "evidence": ev, "text": text})
    return f


def go_lookup(go: GoFace, key: str, kind: str, prefab: str):
    """Go 侧：这一条键**读没读**、读到哪个字段。返回 (read, sites, fields, why, note)。"""
    if kind == "skill":
        ok = prefab in go.prose_prefabs and key in go.prose_keys
        fld = go.skill_keyfield.get(key, "")
        if not ok:
            coll = go.other_keyspace.get(key, []) or go.reads.get(key, [])
            return (False, [], (), "SKILL_KEY_OTHER_KEYSPACE" if coll
                    else "SKILL_KEY_NO_READER", list(coll)[:1])
        return True, list(go.prose_site[:1]), (fld,) if fld else (), "SKILL_READER", []
    sites = list(go.reads.get(key, []))
    fields: tuple[str, ...] = ()
    fam = go.family_of(key)
    if fam is not None:
        fields, famname, fsite = fam
        if famname in ("SUFFIX_NOT_READ", "SUFFIX_UNMAPPED"):
            return False, [], (), famname, []
        if not sites:
            sites = [(s[0], s[1], "family:%s" % famname) for s in fsite]
    if not sites:
        return False, [], fields, "NO_READ_SITE", []
    fld = go.keyfield.get(key, "") or (fields[0] if fields else "")
    if not fld:
        #: 有读取点却认不出下游字段——**不许当成绿**（假绿比假红贵得多）。
        return False, sites[:1], fields, "READ_NO_FIELD", []
    return True, sites[:1], (fld,) if not fields else fields, "READ", []


def judge_key(go: GoFace, py: PyFace, key: str, kind: str, prefab: str,
              r_a, r_b, named_keys: dict | None = None) -> dict:
    """两腿判据。返回 dict(verdict, why, evidence, field, named, py_token)。"""
    named_keys = named_keys or {}
    read, gsites, gfields, why, note = go_lookup(go, key, kind, prefab)
    gbeh: list[tuple[str, int]] = []
    for fd in gfields:
        gbeh += go.behaviour(fd)
    go_consumed = bool(read and gbeh)

    named = ""
    if gfields:
        named = r_a.get(snake(gfields[0]), "")
        if not named and go.line_field.get(gfields[0]):
            ln = go.line_field[gfields[0]]
            named = "rios-sim/unsupported.go:%d(unportedLines[%s])" % (ln[1], ln[0])
    py_ok, py_ev = py.consumes(key, kind, prefab, gfields)
    token = prefab if kind == "skill" else key.split(".")[0]
    py_tok = bool(py.token_hit(token)[:1])

    base = {"field": gfields[0] if gfields else "", "named": named,
            "py_token": py_tok}
    if go_consumed:
        if py_ok:
            return dict(base, verdict="GO", why="BOTH", evidence=gbeh[:1])
        return dict(base, verdict="GO_ONLY", why="GO_ONLY", evidence=gbeh[:1])
    if py_ok:
        #: 真红。**先看有没有具名出处**——有出处的登记为「具名 unported」，
        #: 但登记只改分类、**不改事实**：它仍是一条**已知行为分歧**，
        #: 汇总行必须把条数与「真红 0」印在同一屏上。
        if named:
            return dict(base, verdict="UNPORTED", why="NAMED_LINE",
                        evidence=gsites[:1] or [(named, 0)], py_evidence=py_ev)
        ent = named_keys.get(key)
        if ent:
            return dict(base, verdict="UNPORTED", why="NAMED_KEY",
                        evidence=[("%s(%s)" % (ent["read"], ent["field"]), 0)],
                        py_evidence=py_ev, ent=ent)
        return dict(base, verdict="RED", why=why, evidence=gsites[:1] or [(py_ev, 0)],
                    py_evidence=py_ev)
    return dict(base, verdict="COMMON", why=why, evidence=gsites[:1] or note)


def judge_prose(r_a_tok, r_b, name: str, text: str, has_keys: bool, carriers):
    """正文级判据：三条具名 ＋ 一条风味筛，其余判不了。"""
    for tok, who in r_a_tok.items():
        if tok and tok in text:
            if name in carriers.get(tok, ()):
                return ("UNPORTED", "PROSE_TOKEN",
                        "ak_tactic/simgo/mech.py UNMODELLED_ENEMY_ABILITIES[%s] token=%s"
                        % ("/".join(who), tok))
            return ("UNDECIDABLE", "PROSE_TOKEN_NOT_CARRIER",
                    "命中登记表词元 %s，但该条的载体是 %s，本敌人不在其中"
                    % (tok, "/".join(who)))
    for line in r_b:
        if len(line) > 4 and re.search(r"\b%s\b" % re.escape(line), text):
            return ("UNPORTED", "PROSE_LINE", "rios-sim/unsupported.go line=%s" % line)
    if not has_keys:
        return ("NOKEY", "PROSE_NO_KEY", "")
    return ("UNDECIDABLE", "PROSE_NO_CRITERION", "")


def record(c: dict, ch: str, name: str, eid: str, key: str, it: dict) -> None:
    v = it["verdict"]
    slot = {"GO": "go", "RED": "red", "COMMON": "common",
            "GO_ONLY": "go_only", "UNPORTED": "unported"}[v]
    c[slot].setdefault(key, (name, eid, it))
    c["keyn"] += 1
    c["items"].append({"chapter": ch, "enemy": name, "eid": eid, "key": key,
                       "kind": "key", "verdict": v, "why": it["why"],
                       "evidence": it["evidence"], "zero": it.get("zero", False),
                       "field": it.get("field", ""), "named": it.get("named", ""),
                       "ent": it.get("ent") or {},
                       "py_token": it.get("py_token", False),
                       "py_evidence": it.get("py_evidence", "")})


# --------------------------------------------------------------- 主流程

def main() -> int:
    argv = list(sys.argv[1:])
    mutate = "--mutate" in argv
    md_path = None
    if "--md" in argv:
        i = argv.index("--md")
        md_path = Path(argv[i + 1])
        del argv[i:i + 2]
    levels = [a for a in argv if not a.startswith("-")]

    if not ENEMY_DB.is_file():
        print("MECH-ERROR missing=%s" % ENEMY_DB.as_posix())
        return RC_NO_INPUT
    if not GO_DIR.is_dir() or not list(GO_DIR.glob("*.go")):
        print("MECH-ERROR no_go_source=%s" % GO_DIR.as_posix())
        return RC_NO_INPUT
    if not levels:
        levels = cached_levels()
        given = False
    else:
        given = True
    if not levels:
        print("MECH-ERROR level_list_empty=1")
        return RC_NO_INPUT

    srcs = {p.name: p.read_text(encoding="utf-8") for p in sorted(GO_DIR.glob("*.go"))}
    src_sig = hashlib.sha256("".join("%s\n%s" % (n, srcs[n]) for n in sorted(srcs))
                             .encode("utf-8")).hexdigest()[:16]
    face = GoFace(srcs)
    face.prose_prefabs, face.prose_keys, face.prose_site, _kf = prose_reader(srcs)
    face.skill_keyfield = {v: k for k, v in _kf.items()}
    py = PyFace(ROOT)
    r_a, _, r_a_tok = named_unported()
    r_b_set, r_b_line = unsupported_lines(srcs)
    r_b = sorted(r_b_set)
    face.line_field = line_field_map(r_b_line)

    descs, names = load_gamedata()
    prts = prts_rows()

    print("=== 第 27 套：敌人机制建模判据（Go 侧） ===")
    print("仪器：%s（%d 个 .go）source_sig=%s" % (GO_DIR.relative_to(ROOT), len(srcs), src_sig))
    print("数据：%s sha256(16)=%s" % (ENEMY_DB.relative_to(ROOT), sha16(ENEMY_DB)))
    if ENEMY_SQLITE.is_file():
        print("      %s sha256(16)=%s" % (ENEMY_SQLITE.relative_to(ROOT), sha16(ENEMY_SQLITE)))
    else:
        print("      %s **不在盘上**（prts 那一侧本轮为 0）" % ENEMY_SQLITE.relative_to(ROOT))
    print("取证范围：关卡**键** %d 个（＝不同关卡**内容** %d 份 × 难度与别名标签；%s）"
          % (len(levels), content_count(levels),
             "清单由调用方给出" if given else "缺省：缓存可达的全部"))
    print("口径（两腿求差）：")
    print("  已消费 ＝ Go 有读取点 **且** Go 有行为落点；")
    print("  真红   ＝ ¬Go消费 **且 Python 侧有落点**（Go 的欠账，进 rc）；")
    print("  共同边界 ＝ 两侧都没有落点（**登记、不计红**——"
          "`audit_unmodelled_abilities.py` 立过这条规矩）；")
    print("  仅 Go  ＝ Go 有落点而 Python 没有（反向，登记）；判不了不进 rc。")
    print("      Go 行为文件＝rios-sim/*.go 去掉 填充%s／规格%s／闸门%s"
          % (sorted(FILL_FILES), sorted(SPEC_FILES), sorted(GATE_FILES)))
    print("      Go 键空间外读取点（不采信、仅登记）：%s" % sorted(OTHER_KEYSPACE))
    print("      Python 读取点＝`ak_tactic/gamedata/enemy.py` 的**字面键**"
          "（代码行，docstring 不算）；Python 行为文件＝`ak_tactic/battle/*.py`。")
    print("      ⚠ Python 面看不见「同一机制换了个键名实现」——那是**未核**，"
          "不是没建；输出里另印 `py_token` 线索列。")
    print()
    print("Go 消费面（现算）：")
    print("  字面读取点 %d 个键（%d 处）；重生族前缀 %s；相性族前缀 %s × 槽位 %s"
          % (len(face.reads), sum(len(v) for v in face.reads.values()),
             sorted(face.reborn_suffixes), sorted(face.p3r_prefixes),
             sorted(face.p3r_slots)))
    print("  敌方技能读取器：prefabKey %s → 黑板键 %s（出处 %s）"
          % (sorted(face.prose_prefabs), sorted(face.prose_keys),
             ["%s:%d" % s for s in face.prose_site[:1]]))
    print("  具名登记表：ENEMY_BEHAVIOR_FIELDS/ATTRS %d 项；unportedLines %d 条"
          % (len(r_a), len(r_b_set)))
    named_keys, stale, broken = registry_status(face)
    print("  ★ 第 27 套自己的**具名 unported 登记**：%d 条有效 ／ %d 条过期 ／ %d 条破损"
          % (len(named_keys), len(stale), len(broken)))
    for line in broken:
        print("!! MECH-BROKEN-REGISTRY %s" % ascii_only(line))
    for line in stale:
        print("!! MECH-STALE-REGISTRY %s（该条登记当场失效，键退回真红）" % ascii_only(line))
    for k in sorted(named_keys):
        e = named_keys[k]
        print("     %-46s → %-20s 读取点 %-24s 判定没有行为落点：%s"
              % (k, e["field"], e["read"], e["gate"]))
    if broken:
        print("★ 登记与源码脱节（仪器错）：修登记或修源码，**不许放着**。")
        return RC_NO_INPUT
    if face.reborn_missing:
        print("MECH-ERROR reborn_anchor_missing=%s"
              % ascii_only(",".join(face.reborn_missing)))
        return RC_NO_INPUT
    print("  重生族后缀（现算）：%s；拼接后缀 %s"
          % (sorted(face.reborn_suffixes["Reborn."] | face.reborn_suffixes["Reborning."]),
             sorted(face.concat_suffixes)))
    print("  同义名（源字段→规格字段，来自 %s）：%d 组"
          % ("/".join(sorted(SPEC_FILES)), len(face.aliases)))
    print("Python 消费面（现算，与 Go 面同构）：")
    print("  填充侧 %s；行为侧 ak_tactic/battle/*.py（%d 个）"
          % ("/".join(p.relative_to(ROOT).as_posix() for p in py.fill),
             len(py.behaviour_files)))
    print("  字面读取点 %d 个键（%d 处）；重生族前缀 %s"
          % (len(py.reads), sum(len(v) for v in py.reads.values()),
             sorted(py.reborn_suffixes)))
    print()

    f = run(face, py, levels, descs, names, prts, r_a, r_b, mutate, r_a_tok, named_keys)
    if mutate:
        return _mutate_verdict(face, py, f, srcs, r_a, r_b, named_keys)

    print("--- 逐章 ---")
    tot = {"go": 0, "unported": 0, "red": 0, "common": 0, "go_only": 0,
           "und": 0, "nokey": 0}
    for ch in sorted(f.chapters):
        c = f.chapters[ch]
        ng, nu, nr, nc = (len(c["go"]), len(c["unported"]), len(c["red"]),
                          len(c["common"]))
        ngo = len(c["go_only"])
        pu, pnk, pund = (len(c["prose_unported"]), len(c["prose_nokey"]),
                         len(c["prose_und"]))
        tot["go"] += ng
        tot["unported"] += nu
        tot["red"] += nr
        tot["common"] += nc
        tot["go_only"] += ngo
        tot["und"] += pund
        tot["nokey"] += pnk
        nkeys = len(set(c["go"]) | set(c["unported"]) | set(c["red"])
                    | set(c["common"]) | set(c["go_only"]))
        print("%-10s 敌人 %-4d 机制键 %-4d（出现 %-4d 次）  已消费 %-3d／"
              "**具名 unported %-3d**／真红 %-3d／共同边界 %-3d／仅 Go %-2d  ｜ "
              "正文 已登记 %-3d／无键 %-3d／判不了 %-3d／风味 %-3d"
              % (ch, len(c["enemies"]), nkeys, c["keyn"], ng, nu, nr, nc, ngo,
                 pu, pnk, pund, len(c["flavor"])))
        print("MECH-CH chapter=%s enemies=%d keys=%d keyitems=%d go=%d unported=%d "
              "red=%d common=%d go_only=%d prose_named=%d prose_nokey=%d "
              "prose_undecidable=%d flavor=%d zero=%d"
              % (ch, len(c["enemies"]), nkeys, c["keyn"], ng, nu, nr, nc, ngo,
                 pu, pnk, pund, len(c["flavor"]), len(c["zero"])))
        for cls, n, why in (
                ("GO", ng, "本章一个机制键都没有" if nkeys == 0 else
                 "本章的键没有一条压在 Go 的读取点＋行为落点上"),
                ("UNPORTED", nu, "本章一个机制键都没有" if nkeys == 0 else
                 "本章没有一条「Go 只填不用、Python 有落点」的键命中第 27 套的具名登记表"),
                ("RED", nr, "本章一个机制键都没有（不是「都建模了」）" if nkeys == 0 else
                 "本章每一条「Go 只填不用、Python 有落点」的键都已具名登记 ⇒ "
                 "没有未登记的真红（**登记 ≠ 已修复**）"),
                ("COMMON", nc, "本章每个键要么被 Go 消费、要么 Python 侧有落点")):
            if n == 0:
                print("!! ZERO-ROW chapter=%s class=%s reason=%s"
                      % (ch, cls, ascii_only(why)))
                print("   ★ 零行使：%s 这一类在本章为 0 —— %s" % (cls, why))
        if c["go"]:
            k = sorted(c["go"])[0]
            nm, eid, it = c["go"][k]
            print("   已消费样例：%s 键 %s ← 字段 %s，Go 行为落点 %s（Python 侧也有落点）"
                  % (nm, k, it.get("field") or "?", _ev(it["evidence"])))
        if c["go_only"]:
            k = sorted(c["go_only"])[0]
            nm, eid, it = c["go_only"][k]
            print("   ★ 仅 Go 有落点（Python 侧没有）：%s 键 %s ← %s"
                  % (nm, k, _ev(it["evidence"])))
        if c["zero"]:
            print("   有意图没数值（键在、值全为 0／空）：%s"
                  % "、".join(sorted(c["zero"])))
        if nu:
            print("   **具名 unported（已知行为分歧，登记在案、不修）逐条**：")
            for k in sorted(c["unported"]):
                nm, eid, it = c["unported"][k]
                e = it.get("ent") or {}
                print("     - %-16s %-46s 字段 %-18s 读取点 %-22s Python %s"
                      % (nm[:16], k, e.get("field") or it.get("field") or "?",
                         e.get("read") or _ev(it["evidence"]),
                         it.get("py_evidence", "")))
                print("MECH-ITEM verdict=UNPORTED chapter=%s enemy=%s key=%s field=%s "
                      "read=%s py=%s why=%s"
                      % (ch, ascii_only(eid), ascii_only(k),
                         ascii_only(e.get("field") or it.get("field") or ""),
                         ascii_only(e.get("read") or ""),
                         ascii_only(it.get("py_evidence", "")), it["why"]))
        if nr:
            print("   **真红（未登记的 Go 欠账）逐条**：")
            for k in sorted(c["red"]):
                nm, eid, it = c["red"][k]
                z = " [值全为 0／空]" if it.get("zero") else ""
                print("     - %-16s %-46s %s%s" % (nm[:16], k, it["why"], z))
                print("MECH-ITEM verdict=RED chapter=%s enemy=%s key=%s why=%s src=%s "
                      "py=%s" % (ch, ascii_only(eid), ascii_only(k), it["why"],
                                 ascii_only(_ev(it["evidence"])),
                                 ascii_only(it.get("py_evidence", ""))))
        for it in [x for x in c["items"] if x["kind"] != "key"]:
            if it["verdict"] in ("NOKEY", "UNPORTED"):
                print("     · [%s] %s %s（%s）"
                      % (it["kind"], it["enemy"], it["verdict"], it["why"]))
                print("MECH-ITEM verdict=%s chapter=%s enemy=%s kind=%s why=%s"
                      % (it["verdict"], ch, ascii_only(it["enemy"]), it["kind"], it["why"]))
            elif it["verdict"] == "UNDECIDABLE":
                print("     · [%s] %s **判不了**：%s"
                      % (it["kind"], it["enemy"], it["why"]))
        print()
    print("--- 汇总 ---")
    print("MECH-SUM go=%d unported=%d red=%d common=%d go_only=%d prose_named=%d "
          "prose_nokey=%d undecidable=%d registry=%d registry_stale=%d "
          "registry_broken=%d chapters=%d"
          % (tot["go"], tot["unported"], tot["red"], tot["common"], tot["go_only"],
             sum(len(c["prose_unported"]) for c in f.chapters.values()),
             tot["nokey"], tot["und"], len(named_keys), len(stale), len(broken),
             len(f.chapters)))
    if tot["und"]:
        print("!! MECH-WARN undecidable=%d —— 这些**没有**被本判据覆盖，"
              "不计入 rc；逐条落在落盘文档里" % tot["und"])
    if tot["unported"]:
        print("!! MECH-UNPORTED-REGISTERED n=%d —— **登记 ≠ 已修复**：这些是**已知行为分歧**，"
              "Go 读了黑板、填了字段、模拟里没人读。逐条见落盘文档的「具名 unported 登记」一节。"
              % tot["unported"])
    if md_path:
        md_path.parent.mkdir(parents=True, exist_ok=True)
        _write_md(md_path, f, tot, named_keys)
        print("已写 %s" % md_path)
    print()
    print("结论：已消费 %d ／ 具名 unported %d（逐条见文档「具名 unported 登记」一节）／ "
          "真红 %d" % (tot["go"], tot["unported"], tot["red"]))
    print("      （另：共同边界 %d 个键、仅 Go %d 个键、判不了 %d 条 —— 均不计入 rc）"
          % (tot["common"], tot["go_only"], tot["und"]))
    print("MECH-VERDICT red=%d unported=%d common=%d go=%d go_only=%d undecidable=%d"
          % (tot["red"], tot["unported"], tot["common"], tot["go"], tot["go_only"],
             tot["und"]))
    return RC_RED if tot["red"] else RC_OK


def _ev(ev) -> str:
    if not ev:
        return "（无出处）"
    e = ev[0]
    if isinstance(e, tuple):
        return "%s:%s" % (e[0], e[1])
    return str(e)


def prose_reader(srcs: dict[str, str]):
    """现算 Go 的**敌方技能**读取器：prefabKey、它读的黑板键、键→字段、出处。"""
    text = srcs.get("enemy_derive.go", "")
    pre: set = set()
    keys: set = set()
    keyfield: dict[str, str] = {}
    site: list = []
    inside = False
    for i, line in enumerate(text.splitlines(), 1):
        if "proseSkillAttacks" in line and "map[string]" in line:
            inside = True
            site.append(("enemy_derive.go", i))
        if inside:
            m = re.match(r'\s*"([^"]+)":\s*\{', line)
            if m:
                pre.add(m.group(1))
            if re.search(r"^}", line):
                inside = False
        #: `ScaleMagic: num("atk_scale_magic")` → SkillAtkScaleMagic ← atk_scale_magic
        for m in re.finditer(r'(\w+):\s*num\("([^"]+)"\)', line):
            keys.add(m.group(2))
            keyfield["SkillAtk" + m.group(1)] = m.group(2)
    return pre, keys, site, keyfield


def _mutate_verdict(face: GoFace, py: PyFace, f: Findings, srcs: dict[str, str],
                    r_a, r_b, named_keys: dict) -> int:
    """反向守卫：**两条腿都要证明有分辨力**，且**不依赖取证范围**。

    用合成键在四个方向上各注入一次，每一步都印出来：

    * `③`  合成「共同边界」⇒ 判共同边界；**注入 Go 消费** ⇒ **须变绿，不许变红**
           （「把共同边界错当欠账」这件事必须会被判出来）；
    * `②`  同一条键，**打开 Python 落点** ⇒ **须变真红**；关掉 ⇒ 回到共同边界；
    * `①a` 合成「真红」（Python 有落点、Go 有读取点但无行为）⇒ 判红；
           **抹掉** Go 的读取点 ⇒ **仍须判红**；
    * `①b` 同上一条，改为**补上** Go 的行为落点 ⇒ **须变绿**。

    四条都成立才 rc=0。★ 2026-09-24 父会话裁定的重挑：原来那条只抹一条「已消费」的键，
    **只证明 Go 腿**——那正是会把假红放过去的那一侧。
    """
    K = "__guard__.probe"
    F = "GuardProbe"
    rows: list[tuple[str, str, str]] = []          # (腿, 期望, 实得)

    def verdict() -> str:
        return judge_key(face, py, K, "talent", "", r_a, r_b, named_keys)["verdict"]

    def go_on(beh: bool = False) -> None:
        """注入 Go 读取点；`beh=True` 时连行为落点一起注入（＝「Go 消费」的完整形态）。"""
        face.reads[K] = [("__guard__", 0, "injected")]
        face.keyfield[K] = F
        if beh:
            face._beh_cache[F] = [("sim.go", 0)]

    def go_off() -> None:
        face.reads.pop(K, None)
        face.keyfield.pop(K, None)
        face._beh_cache.pop(F, None)

    def py_on() -> None:
        py.reads[K] = [("__guard__.py", 0)]
        py.keyfield[K] = F
        py._beh[F] = [("ak_tactic/battle/sim.py", 0)]

    def py_off() -> None:
        py.reads.pop(K, None)
        py.keyfield.pop(K, None)
        py._beh.pop(F, None)

    go_off()
    py_off()
    rows.append(("基线：两侧都没有落点", "COMMON", verdict()))

    go_on(beh=True)
    rows.append(("③ 给共同边界注入 Go 消费（⇒ 绿，不许红）", "GO_ONLY", verdict()))
    go_off()

    py_on()
    rows.append(("② 打开 Python 落点（共同边界 ⇒ 真红）", "RED", verdict()))
    py_off()
    rows.append(("② 关掉后回到共同边界", "COMMON", verdict()))

    py_on()
    go_on(beh=False)
    rows.append(("①a 真红（Go 有读取点、无行为落点）", "RED", verdict()))
    go_off()
    rows.append(("①a 抹掉 Go 读取点后仍为红", "RED", verdict()))
    go_on(beh=True)
    rows.append(("①b 补上 Go 行为落点后转绿", "GO", verdict()))
    go_off()
    py_off()

    # ---- ④ 登记保活：**哪天有人补上了行为落点，这条登记必须消失**
    if named_keys:
        k4 = sorted(named_keys)[0]
        f4 = named_keys[k4]["field"]
        rows.append(("④ 登记键 %s 起初有效" % k4, "True",
                     str(k4 in registry_status(face)[0])))
        face._beh_cache[f4] = [("sim.go", 0)]          # 假装有人把行为落点补上了
        ok4, stale4, _broken4 = registry_status(face)
        rows.append(("④ 补上行为落点后该登记**消失**", "True",
                     str(k4 not in ok4 and any(s.startswith(k4 + "：") for s in stale4))))
        rows.append(("④ 同一步不得再判 unported", "GO",
                     judge_key(face, py, k4, "talent", "", r_a, r_b, ok4)["verdict"]))
        face._beh_cache.pop(f4, None)
        rows.append(("④ 撤掉后登记恢复", "True",
                     str(k4 in registry_status(face)[0])))

    print("反向守卫（合成键 %s ＋ 登记保活，四条腿，**不依赖取证范围**）：" % K)
    ok = True
    for leg, want, got in rows:
        good = want == got
        ok &= good
        print("   %s %-36s 期望 %-6s 实得 %s" % ("✓" if good else "✗", leg, want, got))
    print("MECH-MUTATE guard=%s legs=%d failed=%d red_in_scope=%d common_in_scope=%d"
          % ("OK" if ok else "FAIL", len(rows), sum(1 for r in rows if r[1] != r[2]),
             sum(len(c["red"]) for c in f.chapters.values()),
             sum(len(c["common"]) for c in f.chapters.values())))
    if ok:
        print("结论：反向守卫四条腿都成立（Go 腿两个方向都有分辨力、Python 腿能把"
              "共同边界翻成真红、共同边界不会被错当欠账）")
    else:
        print("结论：反向守卫**不成立** —— 至少一条腿没有分辨力")
    return 0 if ok else 1


def _write_md(path: Path, f: Findings, tot: dict, named_keys: dict) -> None:
    out = ["# 敌人机制建模：逐章读数（由 tools/check_enemy_mech_go.py --md 生成）", "",
           "两腿口径：`已消费` ＝ Go 有读取点 ∧ Go 有行为落点；"
           "**`真红` ＝ Python 侧有落点而 Go 没有（未登记的 Go 欠账）**；"
           "`具名 unported` ＝ 真红但已在第 27 套的登记表里有出处（**登记 ≠ 已修复**）；"
           "`共同边界` ＝ 两侧都没有落点（登记，不计红）。", "",
           "| 章 | 敌人只数 | 机制键 | 已消费 | 具名 unported | 真红 | 共同边界 | 仅 Go | "
           "正文已登记 | 正文无键 | 正文判不了 | 风味跳过 |",
           "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        c = f.chapters[ch]
        out.append("| %s | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d | %d |" % (
            ch, len(c["enemies"]),
            len(set(c["go"]) | set(c["unported"]) | set(c["red"])
                | set(c["common"]) | set(c["go_only"])),
            len(c["go"]), len(c["unported"]), len(c["red"]), len(c["common"]),
            len(c["go_only"]), len(c["prose_unported"]), len(c["prose_nokey"]),
            len(c["prose_und"]), len(c["flavor"])))
    out += ["", "## 具名 unported 登记（第 27 套自己的表，`NAMED_UNPORTED_KEYS`）", "",
            "| 键 | Go 字段 | 读取点 | 为什么没有行为落点（判据） | 旁证 |",
            "|---|---|---|---|---|"]
    for k in sorted(named_keys):
        e = named_keys[k]
        out.append("| `%s` | `%s` | `%s` | %s | %s |" % (
            k, e["field"], e["read"], e["gate"], e.get("corrobor", "") or "—"))
    out += ["", "## 具名 unported 的**出现处**（逐条，键 × 章 × 敌人）", "",
            "| 章 | 敌人 | 键 | Go 字段 | Python 落点 |", "|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for k in sorted(f.chapters[ch]["unported"]):
            nm, eid, it = f.chapters[ch]["unported"][k]
            e = it.get("ent") or {}
            out.append("| %s | %s | `%s` | %s | %s |" % (
                ch, nm, k, e.get("field") or it.get("field") or "?",
                it.get("py_evidence", "")))
    out += ["", "## 真红（未登记的 Go 欠账）——逐条", "",
            "| 章 | 敌人 | 键 | 原因 | 下游字段 | Go 侧 | Python 落点 |",
            "|---|---|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for k in sorted(f.chapters[ch]["red"]):
            nm, eid, it = f.chapters[ch]["red"][k]
            out.append("| %s | %s | `%s` | %s | %s | %s | %s |" % (
                ch, nm, k, it["why"], it.get("field") or "?",
                _ev(it["evidence"]), it.get("py_evidence", "")))
    out += ["", "已消费键（样例，逐章前三条）：", "",
            "| 章 | 敌人 | 键 | 下游字段 | Go 行为落点 |", "|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for k in sorted(f.chapters[ch]["go"])[:3]:
            nm, eid, it = f.chapters[ch]["go"][k]
            out.append("| %s | %s | `%s` | %s | %s |" % (
                ch, nm, k, it.get("field") or "?", _ev(it["evidence"])))
    out += ["", "共同边界键（**两台引擎都没有落点**，登记、不计红）——逐条：", "",
            "| 章 | 敌人 | 键 | 原因 | Python 同名词根（线索，不参与判定） |",
            "|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for k in sorted(f.chapters[ch]["common"]):
            nm, eid, it = f.chapters[ch]["common"][k]
            out.append("| %s | %s | `%s` | %s | %s |" % (
                ch, nm, k, it["why"], "是" if it.get("py_token") else ""))
    out += ["", "仅 Go 有落点的键（Python 侧没有——反向的欠账，逐条）：", "",
            "| 章 | 敌人 | 键 | 下游字段 | Go 行为落点 |", "|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for k in sorted(f.chapters[ch]["go_only"]):
            nm, eid, it = f.chapters[ch]["go_only"][k]
            out.append("| %s | %s | `%s` | %s | %s |" % (
                ch, nm, k, it.get("field") or "?", _ev(it["evidence"])))
    out += ["", "正文级（具名登记与「一个键都没有」）：", "",
            "| 章 | 敌人 | 来源 | 判定 | 原因 | 正文 |", "|---|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for it in f.chapters[ch]["items"]:
            if it["kind"] != "key" and it["verdict"] in ("NOKEY", "UNPORTED"):
                out.append("| %s | %s | %s | %s | %s | %s |" % (
                    ch, it["enemy"], it["kind"], it["verdict"], it["why"],
                    it["text"][:120].replace("|", "/")))
    out += ["", "正文级判不了（**判不了 ≠ 没问题**；本工具没有把中文机制名映射到键名的具名判据）：",
            "", "| 章 | 敌人 | 来源 | 原因 | 正文 |", "|---|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for it in f.chapters[ch]["items"]:
            if it["kind"] != "key" and it["verdict"] == "UNDECIDABLE":
                out.append("| %s | %s | %s | %s | %s |" % (
                    ch, it["enemy"], it["kind"], it["why"],
                    it["text"][:120].replace("|", "/")))
    out += ["", "被判为**风味文案**而跳过（词表见工具内 `MECH_KEYWORDS`；不命中即不入判据，"
            "但全文留在这里供人复核）：", "",
            "| 章 | 敌人 | 来源 | 正文 |", "|---|---|---|---|"]
    for ch in sorted(f.chapters):
        for it in f.chapters[ch]["flavor"]:
            out.append("| %s | %s | %s | %s |" % (
                ch, it["enemy"], it["kind"], it["text"][:120].replace("|", "/")))
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


if __name__ == "__main__":
    try:
        _rc = main()
    except SystemExit:
        raise
    except BaseException as e:                              # noqa: BLE001
        print("MECH-CRASH %s: %s" % (type(e).__name__, ascii_only(e)))
        _rc = RC_CRASH
    raise SystemExit(_rc)
