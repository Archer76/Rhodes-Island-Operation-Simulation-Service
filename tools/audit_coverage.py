# -*- coding: utf-8 -*-
"""建模完成度审计：把每位干员的黑板键过一遍分类器。

判据很简单，但很硬：**`_classify` 归不了类的键会掉进 `SkillEffects.other`**，
而 `other` 里的东西模拟器**一个都不消费**——那就是"还没建模的机制"。
提丰技3 的 `attack@s3_atk_scale` 当初就是这么静默丢掉的（技能一开启就结束）。

用法：
    python tools/audit_coverage.py                 # 名册里所有 E2 干员
    python tools/audit_coverage.py --top 20        # 只看未归类最多的 20 位
    python tools/audit_coverage.py --only 电弧 提丰  # 只看指定干员（按名册里的名字）
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from ak_tactic.operator import SkillBook, TalentBook  # noqa: E402
from ak_tactic.operator.skill import _classify  # noqa: E402

TABLE_ROW = re.compile(
    r"^\|\s*([^|]+?)\s*\|\s*`(char_[^`]+)`\s*\|\s*([^|]*?)\s*\|\s*([^|]*?)\s*"
    r"\|\s*([^|]*?)\s*\|")

#: 源码里出现过的字符串字面量。用来判第二道：**这个键有没有被任何代码读过**。
#:
#: 「未归类」只是第一道筛子——`hp_ratio`、`cnt`、`prob`、`interval` 这些键
#: 分类器认不了，但模拟器在**原地**直接读（因为要靠周围描述消歧），它们不是欠账。
#: 两道都不成立（既不归类、也没人读）的键，才是**真的没建模**。
_LITERAL = re.compile(r"""["']([A-Za-z_@$][A-Za-z0-9_@$.]*)["']""")
# 字符集里的 `$` 是必须的：解析层把黑板里 `valueStr` 的字符串值存成 **`$键名`**
# （`operator/talent._blackboard`，技能那边同理），源码里读的就是 `"$projectile"`
# 这样的字面量。不收 `$` 会让这一类键**永远**落在"无人读"栏里——2026-09-18
# 焰狐龙梓兰的 `$projectile` / `$ignore_build_type_target_range` 就是这种假欠账
# （当时两位数字都齐了、代码也确实在读，仍旧报"没人读"）。
#
# 字符集里的 `.` 也**同样是尺子缺陷**（2026-09-20 补，RIOS后端2 报、PM 裁定）：
# 键名带点的（`attack@chain.max_target`、`blkngt_s_2.duration`…）在补点号之前**恒判
# "无人读"**——不是键的性质，是**尺子的性质**。两个读数合起来才是证明：
# ① 旧尺子从 `ak_tactic/**` 全部文本提出 2396 个字面量、**含点的 0 个**（它必然漏）；
# ② 补点号后 2474 个（+78，**全部含点、丢失 0**），`is_read` 翻转 **5 键 / 12 需求对**。
# ★ 翻转的 5 处**全部**落在 `formula.py` 的 `RULED_FLAT_KEYS`（量纲裁定表，119-145 行）
#   ——那是**键名表、零消费者**：补点号修掉了"结构性看不见"，同时会让这 5 键被
#   **假清账**（从"无人读"里划掉，而它们确实没人读）。要保住这一列的含义，需要
#   **另加一条"名字表不算读"的排除**（未做，待裁定；清单见 `docs/literal-dot-fix.md`）。
# 仍未收 `[` / `]`：`blackd_s_2[period].trig_cnt`、`peacok_s_1[crit].atk_scale` 这类
# 含方括号的键**依旧提不出来**——**未核**，不当作已修。


_VARIANT_RE = re.compile(r"\[([^\]]+)\]")


def is_read(key: str, lits: set[str]) -> bool:
    """这个键在源码里有人读吗？——三种写法都算"有人读"。

    1. **全键字面量**：`bb["atk"]` 这类直接按键名取的；
    2. **去掉 `xxx@` 前缀**：`attack@atk_scale` 在源码里写的是 `"atk_scale"`；
    3. **方括号变体键改判条件名**：`headb2_s_2[second].atk` 在源码里**根本不会
       整串出现**——运行时是按条件名选的（`effects.with_variant("second")`）。
       拿全键去找必然找不到，于是被误报成"无人读"。

    第 3 条是被误报逼出来的：怒潮凛冬技2 的 `[second]` 明明已经接好线
    （2026-09-18 提交），审计却仍把它列在欠账里，因为源码里出现的是
    `"second"` 而不是那个全键。**判据必须跟着"运行时怎么选"走，而不是跟着
    "键长什么样"走。**
    """
    if key in lits:
        return True
    m = _VARIANT_RE.search(key)
    if m is not None:
        return m.group(1) in lits
    return key.rsplit("@", 1)[-1] in lits


def source_literals() -> set[str]:
    out: set[str] = set()
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        out.update(_LITERAL.findall(p.read_text(encoding="utf-8")))
    return out


#: 三态里的**第二态**：`仅名字表提到`（PM 2026-09-20 裁定「丙」：报表加 `name_table_only` 列，
#: 三态可分，**不动 `source_literals()`**）。
#:
#: 起因：`_LITERAL` 补点号（提交 `d9e0512`）后，`is_read()` 清掉了 5 键/12 对，而那 5 处的字面量
#: **全在 `ak_tactic/formula.py:119-145` 的 `RULED_FLAT_KEYS`**——公式编译器的**量纲裁定键名表**
#: （按原键比对、不读值）。⇒ **「读过这个名字」与「消费了这个键」之间有一道缝**，这一列就是那道缝。
#:
#: ★ **这是判据（启发式），不是事实**：判别式原文＝「**该字面量所在行去掉字符串与注释后只剩分隔符**
#: （无调用 `(`、无属性访问 `.`、无下标 `[`）」。已知窄口：**单行**写的集合/字典
#: （如 `_X = {"a", "b"}`）**不会**被判为名字表 ⇒ 落回「真有人读」；反过来，将来若出现
#: 「集合构造 ＋ 动态取键」，这一列会**静默**判错。三态里**前两者不许压成一个**。
_STR_ANY = re.compile(r"""["'][^"']*["']""")


def _member_of_collection(line: str) -> bool:
    """该行去掉字符串与注释后只剩分隔符（逗号/空白）⇒ 它是某个多行集合/字典的**成员行**。"""
    body = _STR_ANY.sub("", line).split("#", 1)[0]
    return re.fullmatch(r"[\s,]*", body) is not None


def name_table_literals() -> set[str]:
    """**只**出现在集合/字典成员行上的字面量（`RULED_FLAT_KEYS` 那类键名表）。"""
    out: set[str] = set()
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            if _member_of_collection(line):
                out.update(_LITERAL.findall(line))
    return out


def name_table_only(key: str, lits: set[str], nt: set[str]) -> bool:
    """三态判据：`True` ＝ **拿掉名字表之后就没人读它**（即它只被名字表提到）。

    三个条件缺一不可：`is_read` 认了它（全量）／名字表那一份也认它／**去掉名字表就不认**。
    第三个条件是关键：同时有真消费点与名字表的键，**不算**这一态。
    """
    return is_read(key, lits) and is_read(key, nt) and not is_read(key, lits - nt)


def detector_text() -> str:
    """`ak_tactic/` 全部源码的**文本**（不做字面量提取）。

    **为什么不能拿 `source_literals()` 查天赋名**：那个提取器只认 ASCII 字符串
    ——`"atk"` 提得出来，`"万众巨潮"` 提不出来。拿它查中文天赋名会**一律查不到**，
    第三道筛子就变成一台"所有天赋都没有检测器"的误报机器（第一版正是如此，
    连已经接好线的「万众巨潮」都被报成没有检测器）。

    **查名字用文本包含，查键用字面量**——两件事的量纲不同，不能共用一个提取器。
    """
    out: list[str] = []
    for p in (ROOT / "ak_tactic").rglob("*.py"):
        if "__pycache__" in p.parts:
            continue
        out.append(p.read_text(encoding="utf-8"))
    return "\n".join(out)


def load_roster() -> list[tuple[str, str, str, str]]:
    """按名册文件的**行序**（= 练度序）返回 (名字, charId, 精英, 等级)。"""
    hits = sorted((ROOT / "docs").glob("roster-*.md"))
    if not hits:
        raise SystemExit("找不到 docs/roster-*.md")
    out: list[tuple[str, str, str, str]] = []
    for line in hits[-1].read_text(encoding="utf-8").splitlines():
        m = TABLE_ROW.match(line)
        if m:
            name = m.group(1).rstrip("★").strip()
            # 列序：干员 | charId | 子职业 | 精英 | 等级 | …——**别把子职业当成精英**
            # （第一版少认了一列，于是 `r[2] == "E2"` 一个都没匹配上，
            #   全量扫描静默地跑了个空集。列错位不会报错，只会给你 0。）
            out.append((name, m.group(2), m.group(4).strip(), m.group(5).strip()))
    return out


def trait_kv_of(cid: str) -> list[tuple[str, str, object]]:
    """特性黑板的 `(来源, 键, 值)`——`trait_keys_of` 是它的丢值外壳。"""
    out: list[tuple[str, str, object]] = []
    db = ROOT / "data" / "akdb.sqlite"
    if not db.exists():
        return out
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        for (bb,) in conn.execute(
                "SELECT blackboard FROM operator_trait WHERE char_id=?"
                " AND blackboard IS NOT NULL AND blackboard NOT IN ('', '{}')",
                (cid,)):
            try:
                d = json.loads(bb)
            except Exception:  # noqa: BLE001
                continue
            for k, v in d.items():
                out.append(("特性", k, v))
    finally:
        conn.close()
    return out


def trait_keys_of(cid: str) -> list[tuple[str, str]]:
    """**特性**的黑板键——审计的第三处键源。

    2026-09-18 之前审计只扫了**技能**与**天赋**两处黑板，于是**特性黑板整个没被
    看见**：怒潮凛冬的 `attack@atk_scale_2 = 0.5`（特性溅射的底数）和
    `attack@ability_range_radius = 1.0`（溅射半径）就在这一处，两道筛子都照不到。
    全库 `operator_trait` 里带黑板的行中，光 `atk_scale` 就出现 39 次。

    特性**不在独立表里**：`talent_table.json` 404、`character_table` 也没有
    `traits` 字段；结构化特性只属 156/458 名干员，落在 `operator_trait`
    （正文进 `override_description`，系数进 `blackboard`）。
    """
    return [(s, k) for s, k, _v in trait_kv_of(cid)]


#: 每位干员的 `(技能键, 天赋键, 特性键)` 三份 (来源, 键, 值)——同一趟里会被取两遍，
#: 缓存一次即可（只读缓存：调用方不得原地改返回的列表）。
_KV_CACHE: dict[str, tuple] = {}


def keys_kv_of(cid: str) -> tuple[list[tuple[str, str, object]],
                                 list[tuple[str, str, object]],
                                 list[tuple[str, str, object]]]:
    """(技能键, 天赋键, 特性键)，元素是 `(来源说明, 键名, 值)`。

    ⚠ **2026-09-20 加**：第四批选人要把"缺失"分四类（PM 转后端2 的实测口径），
    其中「第二写法（`$X` 与裸键成对、裸键恒 0）」「两表述」「读写不到（范围代号
    在 `ranges.json` 里为空）」**都要看值**，只看键名分不出来。
    `keys_of()` 保留为**丢掉值的外壳**，两处仍是同一份口径。
    """
    hit = _KV_CACHE.get(cid)
    if hit is not None:
        return hit
    sk_keys: list[tuple[str, str, object]] = []
    for sk in SkillBook().for_operator(cid):
        try:
            lv = sk.level(level=7, mastery=3)
        except Exception:  # noqa: BLE001
            continue
        for k, v in (lv.blackboard or {}).items():
            sk_keys.append((f"{sk.skill_id}·{lv.name}", k, v))
    t_keys: list[tuple[str, str, object]] = []
    try:
        for t in TalentBook().for_operator(cid):
            for k, v in (getattr(t, "blackboard", None) or {}).items():
                t_keys.append((getattr(t, "name", "?"), k, v))
    except Exception:  # noqa: BLE001
        pass
    out = (sk_keys, t_keys, trait_kv_of(cid))
    #: 同一趟里 `screens_of()` 也会取一遍键 ⇒ 不缓存就是**每位干员扫两遍**
    #: （实测全库 431 位一轮 ≈6 分钟）。调用方只读，不许改这三个列表。
    _KV_CACHE[cid] = out
    return out


def keys_of(cid: str) -> tuple[list[tuple[str, str]],
                              list[tuple[str, str]],
                              list[tuple[str, str]]]:
    """返回 (技能键, 天赋键, **特性键**)，元素是 (来源说明, 键名)。"""
    sk_keys, t_keys, tr_keys = keys_kv_of(cid)
    return ([(s, k) for s, k, _v in sk_keys],
            [(s, k) for s, k, _v in t_keys],
            [(s, k) for s, k, _v in tr_keys])


#: 这些黑板键有**通用消费链路**：不靠天赋名，只按键名统一读走。
#:
#: `attack_speed` —— `ak_tactic/operator/attack_speed.py` 会把天赋黑板里的它读
#: 出来加到攻速上。实测能天使「快速弹匣」：`sources=('天赋「快速弹匣」+12',)`，
#: 潜 5 自动变 +15。所以这个天赋**看着没有具名检测器，机制却是好的**。
#:
#: 第三道筛子据此豁免：**一个天赋的全部键都落在这张表里**才豁免；只要还有别的
#: 键（如「天使的祝福」的 `atk` / `max_hp`），照报不误。
GENERIC_TALENT_KEYS = frozenset({"attack_speed"})


def talent_names_of(cid: str) -> list[str]:
    """该干员的天赋名（去重保序）。

    **第三道筛子**要用它。前两道筛子都是**按黑板键**判的，于是漏掉了一整类：

    * 第一道问"`_classify` 认不认"——`atk` / `def` / `max_hp` /
      `attack_speed` / `prob` 这些**都认**；
    * 第二道只在**第一道失败**的键上跑——所以这些键**根本进不了第二道**。

    结果是：一个天赋哪怕**整个没有检测器**，只要它的键都归得了类，就会被报成
    "零欠账"。能天使的「天使的祝福」「快速弹匣」、星熊的「特种作战策略」
    「战术装甲」四个天赋就是这么被漏掉的——源码里一个字都没有，审计却报 0。

    天赋的机制是靠 `ak_tactic/battle/talents.py` 里一个个**具名检测器**
    （`is_*_talent` / `find_*`）落地的，所以"这个名字有没有出现在源码里"
    就是"有没有检测器"的可用代理。这是**天赋级**的判据，不是键级的。

    **方法边界（2026-09-18 记）**：按**名字**查，所以**无名天赋一律看不见**
    ——全库无名且带黑板的天赋有 322 行 / 213 位干员。这一类**并没有漏掉**：
    它们的键照样进 `allk`，第一、二道筛子照常管；只是"按名字找检测器"这种
    判法对无名者无从下手。若日后要覆盖，得换一套判据（例如按
    `(group_index, 键集合)` 反查源码），而不是在名字上做文章。
    """
    out: list[str] = []
    try:
        for t in TalentBook().for_operator(cid):
            n = getattr(t, "name", "")
            if n and n not in out:
                out.append(n)
    except Exception:  # noqa: BLE001
        pass
    return out


def screens_of(cid: str, lits: set[str], det: str) -> tuple[
        list[tuple[str, str]], list[tuple[str, str]],
        list[tuple[str, str]], list[str]]:
    """该干员的三道筛子：返回 (全部键, 第一道·未归类, 第二道·无人读, 第三道·无检测器天赋名)。

    ⚠ **2026-09-20 从 `main()` 里原样抽出**（PM 派单：第四批选人要复用这套口径）。
    抽出的目的是**只留一处口径来源**：`--select` 模式下"缺什么"必须与这份审计
    逐字同义，另写一份必然漂。抽出时**逐行照搬**，并用同一份输入比对输出未变。
    """
    sk_keys, t_keys, tr_keys = keys_of(cid)
    allk = sk_keys + t_keys + tr_keys
    if not allk:
        return [], [], [], []
    bad = [(src, k) for src, k in allk if _classify(k) is None]
    # 第二道：源码里没人读过 = 真的没建模
    dead = [(src, k) for src, k in bad if not is_read(k, lits)]
    # 第三道：**天赋整个没有检测器**（见 `talent_names_of` 的说明）。
    # 但要豁免"键有通用消费链路"的那些——它们的机制是好的（见
    # `GENERIC_TALENT_KEYS`）。豁免条件是"全部键都落在通用表里"，
    # 空键表不算（空集对任何集合都是子集，会把没键的天赋全放过）。
    keys_by_name: defaultdict[str, list[str]] = defaultdict(list)
    for _src, k in t_keys:
        keys_by_name[_src].append(k)
    no_det = []
    for n in talent_names_of(cid):
        if n in det:
            continue
        own = set(keys_by_name.get(n, ()))
        if own and own <= GENERIC_TALENT_KEYS:
            continue
        no_det.append(n)
    return allk, bad, dead, no_det


#: ═══════════════════════════════════════════════════════════════════════════
#: 选人模式（`--select`）：第四批「缺失内容最多 ＋ 一批做完通用最多」
#: ═══════════════════════════════════════════════════════════════════════════
#: 博士 2026-09-20 改策略：**不按练度**，先做缺失内容最多的，尽量让一批做完能通用
#: 最多的其他干员 ⇒ 后半句是**集合覆盖**（max-coverage），不是排序问题。
#:
#: 口径（全部可复算，不写死）：
#:   · 行＝干员；列＝**本项目既有的键空间**里"未建模的键"（第二道：`_classify` 认不了
#:     且源码里没有任何字面量读它）——不另造一套键名；
#:   · 权重 `wt[k]`＝**需要这个键的干员数**（「缺失内容最多」的量化版）；
#:   · 选一位＝把它需要的键全部算作已覆盖，于是**顺手解锁**那些"所有缺失键都已被覆盖"
#:     的其他干员 —— 后者才是"通用"；
#:   · 覆盖率两个数分开报：**(干员×键) 需求对** 与 **完全解锁的干员数**；
#:   · 第三道（天赋整个没有检测器）**单列一层、不进覆盖目标**：它的列是**天赋名**，
#:     而检测器是**具名**的（`is_<名字>_talent`）⇒ 按定义**不可跨干员共享**，
#:     选人策略在这一层没有杠杆（理由与数字都写进报告，不藏）；
#:   · 反向守卫（必须能红）：① 控制组＝**合成宇宙**（造一个共享键，看贪心认不认）；
#:     ② 换起点重跑（练度序 / charId 序 / 随机）；若另一策略**高于**贪心 ⇒ 贪心实现
#:     有问题，**落退出码非 0**；若**相当** ⇒ 报「缺口分布均匀、这个杠杆不存在」。
WORKSPACE_OPS_SQL = ("SELECT char_id, name FROM operator "
                     "WHERE is_operator=1 AND is_not_obtainable=0")


def all_operators() -> list[tuple[str, str]]:
    """全库**可用**干员（特殊模式专属的 29 位按 `is_not_obtainable` 剔掉）。"""
    db = ROOT / "data" / "akdb.sqlite"
    conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
    try:
        rows = list(conn.execute(WORKSPACE_OPS_SQL))
    finally:
        conn.close()
    return [(str(cid), str(nm)) for cid, nm in rows]


def port_reasons_best(cid: str) -> list[str] | None:
    """该干员**最好那一个技能**能不能进 Go（`simgo/skills.py` 白名单）。

    返回理由最少的那次扫描结果；一个技能都没有 ⇒ `None`（不拿"没技能"当"能进"）。
    做法照 `tools/check_simgo.py::_stray_reason` 的测试替身：`effect_source` 用
    默认的 `blackboard`，`op.skill` 直接挂一个真实的技能等级对象。
    """
    from ak_tactic.simgo import skills as sk_mod

    class _Sim:
        effect_source = "blackboard"

    best: list[str] | None = None
    for sk in SkillBook().for_operator(cid):
        try:
            lv = sk.level(level=7, mastery=3)
        except Exception:  # noqa: BLE001
            continue
        op = type("_Op", (), {})()
        op.skill = lv
        op.effects_override = None
        try:
            rs = list(sk_mod.port_reasons(_Sim(), op))
        except Exception as exc:  # noqa: BLE001
            rs = [f"扫描失败 {exc.__class__.__name__}"]
        if best is None or len(rs) < len(best):
            best = rs
    return best


#: ★ 后端2 2026-09-20 实测：「无人读」这一列**至少混了四类**（PM 已采纳并转达）。
#: 覆盖收益**只算第 1 类**——第 2 类接上去是零收益（裸键恒 0）、第 3 类有**反向
#: 回归**风险（实测两例：`attack@attack_range_id` 接上去范围反而缩小、
#: `attack@max_walk_target` 接上去会把已解析的 4 改成 3）、第 4 类属**数据层**缺口
#: （要先补数据，不是建模）。
#: 规则全部可复算、写在报告里；第 1 类是**残差**（三类都不成立的那些）。
GAP_CLASSES = {
    1: "真没建模（该做的）",
    2: "同一量的第二写法（$X 与裸键成对、裸键恒 0）⇒ 零收益",
    3: "同一量的两表述（别名，本体已建模）⇒ 反向回归风险",
    4: "读写不到（范围代号在 data/ranges.json 里缺失或为空）⇒ 数据层缺口",
    5: "后缀读法（`.endswith(…)` 读的）⇒ 实际有人读，属**假欠账**",
}

_SUFFIXES: list[str] | None = None


def read_suffixes() -> list[str]:
    """`ak_tactic/**/*.py` 里 `.endswith("…")` 的后缀模式——与 `source_literals()` **同范围**。

    `gamedata/enemy.py:466/481` 用 `k.endswith("enemy_key"/"token_key")` 读键，
    **字面量尺子看不见这类读法**（它只认整键、不认后缀）⇒ 这类键会被误报成「无人读」。
    PM 2026-09-20 转达的第五类。
    ⚠ **边界**（后端2 自己标的）：那两处读的是**裸键**，**不覆盖 `$` 写法** ⇒
    第五类只能解释一部分，**不是"剩下的都是它"**；下面也只对裸键套用这一类。
    """
    global _SUFFIXES
    if _SUFFIXES is None:
        pat = re.compile(r'\.endswith\(\s*"([^"]{2,})"\s*\)')
        sfx: set[str] = set()
        for p in (ROOT / "ak_tactic").rglob("*.py"):
            if "__pycache__" in p.parts:
                continue
            sfx.update(pat.findall(p.read_text(encoding="utf-8")))
        _SUFFIXES = sorted(sfx)
    return _SUFFIXES

RANGES_JSON = ROOT / "data" / "ranges.json"
_RANGE_IDS: set[str] | None = None


def range_ids() -> set[str]:
    """`data/ranges.json` 里**有内容**的范围代号（空的不算有）。

    `head核查` 正在改 `grid.py`（会重写这个文件）⇒ 报告里必须带它的 sha/mtime，
    否则"这一轮取的是哪个版本"就说不清（PM 2026-09-20 特别要求声明）。
    """
    global _RANGE_IDS
    if _RANGE_IDS is None:
        _RANGE_IDS = set()
        if RANGES_JSON.exists():
            try:
                d = json.loads(RANGES_JSON.read_text(encoding="utf-8"))
            except Exception:  # noqa: BLE001
                d = {}
            if isinstance(d, dict):
                for code, cells in d.items():
                    if cells:
                        _RANGE_IDS.add(str(code))
    return _RANGE_IDS


def gap_class(key: str, value: object, sib: set[str]) -> tuple[int, str]:
    """把一个「无人读」的键分到四类之一。`sib`＝该干员**全部**键（含 `$` 侧）。"""
    if key.startswith("$"):
        return 2, "键名带 $ 前缀（`valueStr` 那一侧）"
    if ("$" + key) in sib:
        return 2, "同一黑板里并存 $" + key + "（裸键那一侧恒 0）"
    base = re.sub(r"^(attack@|talent@|enemy@)", "", key)
    if base != key and _classify(base) is not None:
        return 3, f"别名：本体 {base} 已建模（接上去可能反向回归）"
    if isinstance(value, str) and re.fullmatch(r"\d+-\d+", value):
        if value not in range_ids():
            return 4, f"范围代号 {value} 在 ranges.json 里缺失或为空"
    if not key.startswith("$"):
        #: ★ 第五类：后缀读法。**只对裸键套用**（后端2 标的边界：那两处 `endswith`
        #: 读的是裸键，不覆盖 `$` 写法）⇒ 别把"剩下的都是它"读成结论。
        for s in read_suffixes():
            if key.endswith(s):
                return 5, '后缀读法 `.endswith("' + s + '")` ⇒ 实际有人读（假欠账）'
    return 1, "五类都不成立 ⇒ 真的没建模"


def classify_gaps(data: dict) -> None:
    """就地给每位干员的缺失键打四类，并算出**第 1 类子集**（覆盖收益只用它）。"""
    for d in data.values():
        sib = {k for _s, k, _v in d["kv"]}
        val: dict[str, object] = {}
        for _s, k, v in d["kv"]:
            val.setdefault(k, v)
        cls: dict[str, int] = {}
        why: dict[str, str] = {}
        for k in d["keys"]:
            c, w = gap_class(k, val.get(k), sib)
            cls[k], why[k] = c, w
        d["class"] = cls
        d["why"] = why
        d["keys1"] = {k for k, c in cls.items() if c == 1}


def ident_of() -> dict:
    """口径三件套＋**来源三件套**（库／范围表／名册的 sha16，加树 HEAD 与工作区状态）。

    ★ 补 HEAD 的理由（验收 2026-09-20）：这份读数的分母会随**源码**变（尺子字符类改一次，
    599→594），只记输入三件套**不足以**说明"这两个数能不能比"——跨提交比较必须带树身份。
    取不到就写「不可得」，**不许留空**（留空会被读成"没有这回事"）。
    """
    import hashlib

    def h(p: Path) -> str:
        try:
            return hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except Exception:  # noqa: BLE001
            return "?"

    def git(*args: str) -> str:
        try:
            r = subprocess.run(["git", *args], cwd=ROOT, capture_output=True,
                               text=True, timeout=30)
            return r.stdout.strip() or "(空)"
        except Exception:  # noqa: BLE001
            return "不可得"

    dirty = git("status", "--porcelain", "--", ".")
    ros = sorted((ROOT / "docs").glob("roster-*.md"))
    db = ROOT / "data" / "akdb.sqlite"
    return {"akdb": h(db), "akdb_mtime": time.strftime(
        "%Y-%m-%d %H:%M:%S", time.localtime(db.stat().st_mtime)) if db.exists() else "?",
        "ranges": h(RANGES_JSON),
        "ranges_mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                      time.localtime(RANGES_JSON.stat().st_mtime))
        if RANGES_JSON.exists() else "?",
        "roster": h(ros[0]) if ros else "?", "roster_file": ros[0].name if ros else "?",
        "head": git("rev-parse", "--short", "HEAD"),
        "src_dirty": "干净" if dirty in ("", "(空)") else f"有未提交改动（{len(dirty.splitlines())} 项）"}


def scan_ops(cids: list[str], lits: set[str], det: str, want_port: bool = True) -> dict:
    """一趟扫完：每位干员的 (键层缺失, 天赋层缺失, 全部键数, 白名单理由)。"""
    out: dict[str, dict] = {}
    for cid in cids:
        allk, _bad, dead, no_det = screens_of(cid, lits, det)
        sk_kv, t_kv, tr_kv = keys_kv_of(cid)
        out[cid] = {
            "kv": sk_kv + t_kv + tr_kv,
            "keys": {k for _s, k in dead},
            "talents": set(no_det),
            "n_allk": len(allk),
            "port": port_reasons_best(cid) if want_port else None,
        }
    return out


def coverage_of(needs: dict[str, set[str]], covered: set[str]) -> tuple[int, int, int]:
    """(已覆盖需求对, 需求对总数, **完全解锁**的干员数)。"""
    pairs = sum(len(v & covered) for v in needs.values())
    total = sum(len(v) for v in needs.values())
    full = sum(1 for v in needs.values() if v and v <= covered)
    return pairs, total, full


def greedy_pick(needs: dict[str, set[str]], wt: dict[str, int],
                order: list[str], k: int, worst: bool = False) -> tuple[list[str], list[tuple]]:
    """贪心（或"最差"控制）选 k 位；返回 (名单, 每步轨迹)。

    每步的收益＝该干员**尚未覆盖**的那些键的权重和（权重＝需要这个键的干员数），
    平局按"自身缺失更多"、再按 `order` 里的先后定序（**确定性**，可复现）。
    """
    covered: set[str] = set()
    picks: list[str] = []
    trace: list[tuple] = []
    while len(picks) < k:
        best: str | None = None
        best_key: tuple | None = None
        for cid in order:
            if cid in picks:
                continue
            gain = sum(wt[x] for x in needs.get(cid, ()) if x not in covered)
            key = (-gain if worst else gain, len(needs.get(cid, ())))
            if best_key is None or key > best_key:
                best, best_key = cid, key
        if best is None:
            break
        new = needs.get(best, set()) - covered
        picks.append(best)
        covered |= needs.get(best, set())
        pairs, total, full = coverage_of(needs, covered)
        trace.append((best, len(new), sum(wt[x] for x in new), len(covered), pairs, total, full))
    return picks, trace


def control_group_ok() -> tuple[bool, str]:
    """控制组：**合成宇宙**里造一个共享键，贪心必须认出来。

    为什么必须有它：真实数据里若"每个键只被一位干员需要"，贪心与乱序**长得一样**
    ——那时"两种策略差不多"既可能是"杠杆不存在"，也可能是"收益算法根本没生效"。
    合成宇宙把这两个成因分开：这里**共享是构造出来的**，贪心不利用它 ⇒ 算法坏了。
    """
    needs: dict[str, set[str]] = {}
    for i in range(20):
        needs[f"op{i:02d}"] = {f"solo_{i}"}
    for i in range(10):
        needs[f"op{i:02d}"].add("shared")
    order = list(needs)
    wt = {k: sum(1 for v in needs.values() if k in v) for k in {x for v in needs.values() for x in v}}
    picks, trace = greedy_pick(needs, wt, order, 1)
    first_gain = trace[0][2] if trace else 0
    ok = bool(trace) and "shared" in needs.get(picks[0], set()) and first_gain >= 10
    return ok, (f"合成宇宙：20 位干员／1 个被 10 位共享的键；贪心第一手＝{picks[0] if picks else '—'}"
                f"、收益 {first_gain}（须 ≥10 且落在共享键持有者上）")


def cross_mode(a) -> int:
    """★ 同口径对比（PM 2026-09-20 裁 A 时要求）：两套行空间 × 两份名单。

    「214/773」算在 **431 位**行空间上、「112/253」算在 **169 位**行空间上——
    **分母不同，并列会被读成"A 比 B 小"**。这一档把两份名单**都**放到**两个**行空间上
    各算一遍：同一行内的两列才可比，跨行比就是换分母、**不可比**。
    """
    if not a.from_cache:
        raise SystemExit("--cross 必须配 --from-cache（要用带白名单读数的缓存）")
    blob = json.loads(Path(a.from_cache).read_text(encoding="utf-8"))
    data = {cid: {"keys": set(d["keys"]), "talents": set(d["talents"]),
                  "n_allk": d["n_allk"], "port": d["port"],
                  "kv": [tuple(x) for x in d["kv"]]}
            for cid, d in blob["data"].items()}
    classify_gaps(data)
    names: dict[str, str] = {}
    try:
        db = ROOT / "data" / "akdb.sqlite"
        conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        names = {str(c): str(n) for c, n in conn.execute("SELECT char_id,name FROM operator")}
        conn.close()
    except Exception:  # noqa: BLE001
        pass
    port_ok = {cid for cid, d in data.items() if d["port"] == []}
    spaces = {"全库（431 位那一档）": set(data), f"过闸（{len(port_ok)} 位那一档）": port_ok}
    space_needs: dict[str, tuple[dict, Counter]] = {}
    for sname, space in spaces.items():
        needs = {c: d["keys1"] for c, d in data.items() if c in space}
        wt: Counter[str] = Counter()
        for v in needs.values():
            for kk in v:
                wt[kk] += 1
        space_needs[sname] = (needs, wt)
    batches: dict[str, list[str]] = {}
    for label, sname in (("B：全库贪心", "全库（431 位那一档）"),
                         ("A：过闸贪心（--only-port）", f"过闸（{len(port_ok)} 位那一档）")):
        needs, wt = space_needs[sname]
        batches[label] = greedy_pick(needs, wt, sorted(needs), a.batch)[0]
    print("=" * 78)
    print("同口径对比：两套行空间 × 两份名单（同一行内的两列才可比）")
    print("=" * 78)
    for sname, (needs, wt) in space_needs.items():
        total = sum(wt.values())
        print(f"\n行空间 {sname}：{len(needs)} 位干员、{len(wt)} 种键、{total} 个需求对")
        print(f"  {'名单':<28}{'覆盖需求对':>12}{'占比':>8}{'完全解锁':>9}{'可进 Go':>9}{'覆盖键':>8}")
        for label, picks in batches.items():
            cov = {x for c in picks for x in needs.get(c, ())}
            pairs, _tot, _full = coverage_of(needs, cov)
            if not cov or pairs == 0:
                print(f"  {label:<28}{'—':>12}{'不可比':>8}（名单落在这个行空间之外）")
                continue
            full = sum(1 for c, v in needs.items() if v and v <= cov)
            usable = sum(1 for c, v in needs.items() if v and v <= cov and c in port_ok)
            print(f"  {label:<28}{pairs:>7}/{total:<4}{pairs / total * 100:>7.1f}%"
                  f"{full:>9}{usable:>9}{len(cov):>8}")
    print("\n注：跨行比＝换分母，**不可比**；同一行内 A 与 B 才可比。")
    for label, picks in batches.items():
        print(f"  {label}：{'、'.join(names.get(c, c) for c in picks)}")
    return 0


def select_mode(a, lits: set[str], det: str) -> int:
    import random

    ops = all_operators()
    if len(ops) < 50:
        raise SystemExit(f"全库可用干员只查到 {len(ops)} 位，明显不对")
    roster = load_roster()
    roster_cids = [cid for _n, cid, _e, _l in roster]
    names = dict(ops)

    want_port = not a.no_port
    ident = ident_of()
    if a.from_cache:
        blob = json.loads(Path(a.from_cache).read_text(encoding="utf-8"))
        print(f"（复用扫描缓存 `{a.from_cache}`，生成于 {blob.get('generated_at')}）")
        print(f"  缓存身份：{blob.get('ident')}")
        print(f"  本轮身份：{ident}")
        if blob.get("ident") != ident:
            print("  ⚠ 身份不一致：库／范围表／名册有变，读数不可与缓存同日而语")
        data = {cid: {"keys": set(d["keys"]), "talents": set(d["talents"]),
                      "n_allk": d["n_allk"], "port": d["port"],
                      "kv": [tuple(x) for x in d["kv"]]}
                for cid, d in blob["data"].items()}
        classify_gaps(data)
    else:
        data = scan_ops([cid for cid, _n in ops], lits, det, want_port)
        classify_gaps(data)
    if a.cache and not a.from_cache:
        Path(a.cache).write_text(json.dumps({
            "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"), "ident": ident,
            "data": {cid: {"keys": sorted(d["keys"]), "talents": sorted(d["talents"]),
                           "n_allk": d["n_allk"], "port": d["port"], "kv": d["kv"],
                           "class": d["class"], "keys1": sorted(d["keys1"])}
                     for cid, d in data.items()}}, ensure_ascii=False), encoding="utf-8")
        print(f"扫描缓存已落盘：{a.cache}")
    needs = {cid: d["keys1"] for cid, d in data.items()}
    needs_raw = {cid: d["keys"] for cid, d in data.items()}
    if a.only_port and not a.no_port:
        #: ★ 第二道闸当**前提**：白名单过不了的干员，键族补齐了他也进不了 Go
        #: （实测批次内 10 位只有 2 位过闸）⇒ 这一档的读数才是"做完就能用"的口径。
        keep = {cid for cid, d in data.items() if d["port"] == []}
        print(f"（--only-port：行空间收窄到「至少一个技能能进 Go」的 **{len(keep)}** 位）")
        #: ★ 收窄**前**留一份全库快照：第二态「仅名字表提到」要按「全库／过闸」两档分列报数
        #: （只报一档会让人把两个分母并列，2026-09-20 实测踩过）。
        data_all = data
        data = {cid: d for cid, d in data.items() if cid in keep}
        needs = {cid: d["keys1"] for cid, d in data.items()}
        needs_raw = {cid: d["keys"] for cid, d in data.items()}
    wt: Counter[str] = Counter()
    for v in needs.values():
        for k in v:
            wt[k] += 1

    order_all = [cid for cid, _n in ops]
    order_roster = [cid for cid in roster_cids if cid in needs]
    order_cid = sorted(needs)
    rnd = random.Random(20260920)
    order_rnd = list(order_cid)
    rnd.shuffle(order_rnd)

    k = a.batch
    picks, trace = greedy_pick(needs, wt, order_all, k)
    base_greedy = coverage_of(needs, {x for cid in picks for x in needs[cid]})

    print("=" * 78)
    print("选人模式：缺失内容最多 ＋ 一批做完通用最多（博士 2026-09-20 改的策略）")
    print("=" * 78)
    print(f"行空间：全库可用干员 **{len(ops)}** 位（`is_operator=1` 且 `is_not_obtainable=0`）；"
          f"名册 **{len(roster_cids)}** 位（能实机验证的那个子集）")
    nkeys = len(wt)
    ntal = sum(len(d["talents"]) for d in data.values())
    raw_wt: Counter[str] = Counter()
    for v in needs_raw.values():
        for kk in v:
            raw_wt[kk] += 1
    print(f"输入身份（口径三件套）：库 `{ident['akdb']}`（{ident['akdb_mtime']}）／"
          f"范围表 `{ident['ranges']}`（{ident['ranges_mtime']}）／"
          f"名册 `{ident['roster_file']}` `{ident['roster']}`")
    print(f"列空间（键层，**分层前**）：**{len(raw_wt)}** 种「无人读」键、"
          f"**{sum(raw_wt.values())}** 个 (干员×键) 位次")
    print("★ 分层（后端2 2026-09-20 实测、PM 已采纳）——**覆盖收益只算第 1 类**：")
    cls_cnt: Counter[int] = Counter()
    for d in data.values():
        for c in d["class"].values():
            cls_cnt[c] += 1
    for c in (1, 2, 3, 4, 5):
        print(f"   第 {c} 类 {cls_cnt[c]:>5} 位次  {GAP_CLASSES[c]}")
    print(f"   ⇒ **可做的（第 1 类）＝ {cls_cnt[1]} 位次 / {len(wt)} 种键**；"
          f"第 2/3/4/5 类共 "
          f"{cls_cnt[2] + cls_cnt[3] + cls_cnt[4] + cls_cnt[5]} 位次**不进覆盖收益**")
    print(f"覆盖目标据此只用第 1 类：**{nkeys}** 种键、**{sum(wt.values())}** 个 (干员×键) 需求对")
    print(f"另列一层（**不进覆盖目标**）：第三道「天赋整个没有检测器」"
          f"**{len({n for d in data.values() for n in d['talents']})}** 个天赋名、{ntal} 位次"
          f"——检测器是**具名**的，按定义不可跨干员共享，选人策略在这一层没有杠杆")
    print()

    nt = name_table_literals()
    nt_keys: Counter[str] = Counter()
    nt_gate_keys: set[str] = set()
    nt_gate_pairs = 0
    gate_all = {cid for cid, d in data_all.items() if d.get("port") == []}
    for cid, d in data_all.items():
        # ★ 用**摊平键集** `kv`，不要用 `d["keys"]`——后者是**筛后**集合，被名字表清掉的键
        # 已经不在里面了（用它会恒得 0，2026-09-20 实测踩过）；也别复用 `k`（本函数里 `k = a.batch`
        # 是切片上界，覆盖它会崩在 `[:k]`）。
        for _key in {kk for _s, kk, _v in (d.get("kv") or [])}:
            if name_table_only(_key, lits, nt):
                nt_keys[_key] += 1
                if cid in gate_all:
                    nt_gate_keys.add(_key)
                    nt_gate_pairs += 1
    print("★ 三态之第二态「仅名字表提到」（**判据**，不是事实）——**覆盖收益不算它**：")
    print(f"  全库（{len(data_all)} 位）：**{len(nt_keys)}** 种键、{sum(nt_keys.values())} 个 (干员×键) 位次；"
          f"其中过闸 **{len(nt_gate_keys)}** 种键、**{nt_gate_pairs}** 个位次"
          f"（过闸 {len(gate_all)} 位）")
    print("  判别式（启发式，原文）：该字面量**所在行去掉字符串与注释后只剩分隔符**"
          "（无调用、无属性访问、无下标）")
    print("  ⇒ 它只是集合/字典里的一个键名，**没人拿它去取值**；三态里**前两者不许压成一个**")
    print("  已知窄口：单行写的集合/字典（键名与赋值同行）落回「真有人读」")
    if nt_keys:
        print("  明细（前 8）：" + "、".join(f"{k}（{n} 位）" for k, n in nt_keys.most_common(8)))
    print()

    print("--- 一、缺失内容最多的键族（**只算第 1 类**；权重＝需要它的干员数）---")
    who: defaultdict[str, list[str]] = defaultdict(list)
    for cid, v in needs.items():
        for kk in v:
            who[kk].append(names.get(cid, cid))
    for kk, n in wt.most_common(20):
        w = "、".join(who[kk][:6]) + ("…" if len(who[kk]) > 6 else "")
        print(f"  {n:>3} 位  {kk:<36} {w}")
    print()

    print(f"--- 二、贪心名单（k={k}，博士策略）---")
    print(f"  {'步':>3} {'干员':<14}{'本步新增键':>10}{'新增需求对':>11}"
          f"{'累计键':>8}{'累计需求对':>11}{'完全解锁干员':>13}")
    for i, (cid, nnew, wnew, ncov, pairs, total, full) in enumerate(trace, 1):
        print(f"  {i:>3} {names.get(cid, cid):<14}{nnew:>10}{wnew:>11}"
              f"{ncov:>8}{pairs:>7}/{total:<4}{full:>13}")
    print(f"  ⇒ 名单：{'、'.join(names.get(c, c) for c in picks)}")
    print()

    print("--- 三、反向守卫：换**选人策略**（不是换平局顺序）---")
    #: ⚠ 2026-09-20 自纠：第一版把「换起点重跑」实现成"给同一个贪心喂不同的 order"
    #: ——而贪心每一步扫的是**整个 order**，order 只影响平局 ⇒ 三行读数**必然相同**
    #: （实测 charId 序/随机序/贪心 都是 222/783）。那是**结构上无法有差异的空判据**
    #: （同族 key 3854af6b：先问"判据红得起来吗"）。现在的基线＝**直接取该序列的前 k 位**。
    def _prefix(order: list[str]) -> list[str]:
        return [c for c in order if c in needs][:k]

    by_debt = sorted(needs, key=lambda c: (-len(needs[c]), c))[:k]
    rows = []
    for label, pk in (("贪心（博士策略）", picks),
                      ("练度序取前 k", _prefix(order_roster)),
                      ("charId 序取前 k", _prefix(order_cid)),
                      ("随机序取前 k（seed 20260920）", _prefix(order_rnd)),
                      ("按欠账条数排序取前 k", by_debt)):
        cov = {x for cid in pk for x in needs.get(cid, ())}
        pairs, total, full = coverage_of(needs, cov)
        rows.append((label, pk, pairs, total, full, len(cov)))
        print(f"  {label:<26} 需求对 {pairs:>5}/{total:<5} 完全解锁干员 {full:>3}  覆盖键 {len(cov):>3}")
    _tie_pk, _tie_tr = greedy_pick(needs, wt, order_rnd, k)
    print(f"  （附：同一贪心只换平局顺序 ⇒ "
          f"{coverage_of(needs, {x for c in _tie_pk for x in needs[c]})[0]} 需求对，"
          f"与贪心相同是**设计如此**，它不能当反向守卫）")
    worst_label, worst_row = None, None
    for label, _pk, pairs, _t, _f, _c in rows[1:]:
        if pairs > base_greedy[0]:
            worst_label, worst_row = label, pairs
    print()
    lead = rows[0][2] - max(r[2] for r in rows[1:])
    same = [r[0] for r in rows[1:] if abs(r[2] - rows[0][2]) <= max(1, rows[0][2] * 0.05)]
    if lead <= 0 and same:
        print(f"  ⇒ **结论：这个选人策略的杠杆不存在（或缺口的可共享性≈0）**——"
              f"贪心 {rows[0][2]}/{base_greedy[1]} 需求对，与 {('、'.join(same))} 相差 ≤5%。"
              f"\n     成因是结构性的：需求对里绝大多数键**只被一位干员需要**"
              f"（见下表），选谁都在各自补自己的账，通用不了别人。")
    else:
        print(f"  ⇒ 贪心领先最强的另一策略 {lead} 个需求对（≈{lead / max(1, base_greedy[1]) * 100:.1f}%）。")
    print()

    print("--- 四、控制组（合成宇宙，判「收益算法有没有生效」）---")
    ok, msg = control_group_ok()
    print(f"  {'✅' if ok else '❌'} {msg}")
    print()

    print("--- 五、需求对的「可共享性」分布（解释上面那个结论）---")
    dist: Counter[int] = Counter(wt.values())
    for n in sorted(dist, reverse=True):
        print(f"  被 {n:>2} 位干员需要的键：{dist[n]:>3} 种")
    print()

    print("--- 六、换成「按族选」的覆盖曲线（族＝键，权重＝跨干员位数）---")
    tot = sum(wt.values())
    cum = 0
    for i, (kk, n) in enumerate(wt.most_common(), 1):
        cum += n
        if i in (5, 10, 20, 30, 50, 100, 200, 300):
            print(f"  前 {i:>3} 个键族 ⇒ 覆盖 {cum:>4}/{tot} 需求对（{cum / tot * 100:.1f}%）")
    _cov_keys = len({x for cid in picks for x in needs[cid]})
    print(f"  （对照：贪心选 {k} 位干员覆盖 {base_greedy[0]}/{base_greedy[1]}"
          f"＝{base_greedy[0] / base_greedy[1] * 100:.1f}%，覆盖 {_cov_keys} 个族）")
    print()

    if want_port:
        print("--- 七、第二道闸：能不能进 Go（`simgo/skills.py` 白名单）---")
        ported = {cid for cid, d in data.items() if d["port"] == []}
        failed = {cid: d["port"] for cid, d in data.items() if d["port"]}
        noskill = {cid for cid, d in data.items() if d["port"] is None}
        print(f"  至少一个技能能进 Go：**{len(ported)}**/{len(ops)} 位"
              f"（另有 {len(noskill)} 位没有技能、{len(failed)} 位每个技能都被白名单挡）")
        cov = {x for cid in picks for x in needs[cid]}
        unlocked = [cid for cid, v in needs.items() if v and v <= cov]
        unl_ok = [cid for cid in unlocked if cid in ported]
        print(f"  ★ 边界诚实：「能通用」≠「做完就能用」——完全解锁 **{len(unlocked)}** 位，"
              f"其中真能进 Go 的只有 **{len(unl_ok)}** 位")
        if unlocked:
            blocked = [cid for cid in unlocked if cid not in ported]
            if blocked:
                print(f"     被白名单挡住的 {len(blocked)} 位（前 6）："
                      + "、".join(f"{names.get(c, c)}[{(failed.get(c) or ['无技能'])[0]}]"
                                  for c in blocked[:6]))
        inbatch = [(cid, data[cid]["port"]) for cid in picks]
        print(f"  批次内 10 位：能进 Go {sum(1 for _c, r in inbatch if r == [])} 位；"
              f"其余理由（前 5）："
              + "；".join(f"{names.get(c, c)}[{(r or ['无技能'])[0]}]" for c, r in inbatch if r != [])[:300])
        print()

    if a.json:
        Path(a.json).write_text(json.dumps({
            "ident": ident, "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "rows": len(ops), "roster": len(roster_cids),
            "class_counts": {str(c): cls_cnt[c] for c in (1, 2, 3, 4)},
            "name_table_only": {
                "判据": "启发式：该字面量所在行去掉字符串与注释后只剩分隔符"
                        "（无调用、无属性访问、无下标）⇒ 只是集合/字典里的键名",
                "keys": sorted(nt_keys), "pairs": sum(nt_keys.values()),
                "gate_keys": sorted(nt_gate_keys), "gate_pairs": nt_gate_pairs,
            },
            "raw_keys": len(raw_wt), "raw_pairs": sum(raw_wt.values()),
            "keys": nkeys, "pairs": sum(wt.values()), "batch": picks,
            "trace": [{"step": i + 1, "cid": t[0], "name": names.get(t[0], t[0]),
                       "new_keys": t[1], "new_pairs": t[2], "keys_covered": t[3],
                       "pairs": t[4], "total": t[5], "full": t[6]} for i, t in enumerate(trace)],
            "strategies": [{"label": r[0], "batch": r[1], "pairs": r[2], "total": r[3],
                            "full": r[4], "keys": r[5]} for r in rows],
            "weight_hist": {str(n): c for n, c in dist.items()},
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"JSON：{a.json}")

    if worst_row is not None:
        print(f"❌ 反向守卫失败：{worst_label} 的覆盖率 {worst_row} 高于贪心 {base_greedy[0]}"
              f" ⇒ 贪心的收益算法有问题")
        return 1
    if not ok:
        print("❌ 控制组失败：合成宇宙里贪心没利用共享键 ⇒ 收益算法没生效")
        return 1
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--all", action="store_true",
                    help="连非 E2 的也看（默认只看 E2）")
    ap.add_argument("--select", action="store_true",
                    help="第四批选人模式：集合覆盖（缺失最多＋通用最多），不看 E2 限制")
    ap.add_argument("--batch", type=int, default=10, help="--select：这批要选几位（默认 10）")
    ap.add_argument("--json", default=None, help="--select：把结果落成 JSON")
    ap.add_argument("--no-port", action="store_true",
                    help="--select：跳过 `simgo/skills.py` 白名单扫描（省时间）")
    ap.add_argument("--cache", default=None,
                    help="--select：把全库扫描落成 JSON（含四类分层，便于复核与复算）")
    ap.add_argument("--from-cache", default=None,
                    help="--select：复用上一轮的扫描缓存（只跑选人与守卫，秒级）")
    ap.add_argument("--only-port", action="store_true",
                    help="--select：行空间先收窄到「至少一个技能能进 Go」的干员（第二道闸）")
    ap.add_argument("--cross", action="store_true",
                    help="--select：同口径对比（两套行空间 × 两份名单，配 --from-cache）")
    a = ap.parse_args()

    roster = load_roster()
    # 守卫：名册解析出错**不会报错**，只会静默变成空集或全错位——那次全量扫描
    # 就是这么跑出"0 种键"的。宁可在这里炸，也不要给出一份看着像结论的空表。
    if len(roster) < 50:
        raise SystemExit(f"名册只解析出 {len(roster)} 行，明显不对（211 名的表）")
    n_e2 = sum(1 for r in roster if r[2] == "E2")
    if n_e2 < 20:
        raise SystemExit(f"E2 只认出 {n_e2} 位，列很可能错位了")

    if a.only:
        roster = [r for r in roster if r[0] in set(a.only)]
        if not roster:
            raise SystemExit(f"--only 的 {a.only} 在名册里一个都没找到")
    elif not a.all and not a.select:
        roster = [r for r in roster if r[2] == "E2"]

    lits = source_literals()
    nt = name_table_literals()
    det = detector_text()
    if a.select:
        #: 选人模式走**全体名册**（不受 `--all`/E2 过滤影响），行空间另按全库可用干员取。
        if a.cross:
            return cross_mode(a)
        return select_mode(a, lits, det)
    rows = []
    unclass_global: Counter[str] = Counter()
    unclass_who: defaultdict[str, list[str]] = defaultdict(list)
    dead_global: Counter[str] = Counter()
    dead_who: defaultdict[str, list[str]] = defaultdict(list)
    nt_global: Counter[str] = Counter()
    nt_who: defaultdict[str, list[str]] = defaultdict(list)
    nodet_global: Counter[str] = Counter()
    nodet_who: defaultdict[str, list[str]] = defaultdict(list)
    for name, cid, elite, lvl in roster:
        allk, bad, dead, no_det = screens_of(cid, lits, det)
        if not allk:
            continue
        for _src, _key in allk:
            if name_table_only(_key, lits, nt):
                nt_global[_key] += 1
                nt_who[_key].append(name)
        for _src, k in bad:
            unclass_global[k] += 1
            unclass_who[k].append(name)
        for _src, k in dead:
            dead_global[k] += 1
            dead_who[k].append(name)
        for n in no_det:
            nodet_global[n] += 1
            nodet_who[n].append(name)
        buckets = Counter((_classify(k) or ("other",))[0] for _s, k in allk)
        rows.append((len(dead), len(bad), len(allk), name, cid, elite, lvl,
                     buckets, dead, no_det))

    rows.sort(key=lambda r: (-(len(r[9]) * 1000 + r[0]), -r[1], r[3]))
    if a.top:
        rows = rows[:a.top]

    print(f"{'干员':<14}{'E/L':<9}{'键数':>5}{'未归类':>7}{'无人读':>7}"
          f"{'无检测器':>8}  分桶")
    print("-" * 84)
    for ndead, nbad, ntot, name, cid, elite, lvl, buckets, _d, nodet in rows:
        b = " ".join(f"{k}={v}" for k, v in sorted(buckets.items()))
        flag = "  ←" if (ndead or nodet) else ("  ·" if nbad else "")
        print(f"{name:<14}{elite + ' ' + lvl:<9}{ntot:>5}{nbad:>7}{ndead:>7}"
              f"{len(nodet):>8}  {b}{flag}")

    print()
    print("=" * 74)
    print(f"第一道（分类器认不了）：{len(unclass_global)} 种键、"
          f"{sum(unclass_global.values())} 次")
    print(f"第二道（**源码里也没有任何地方读它**）：{len(dead_global)} 种键、"
          f"{sum(dead_global.values())} 次  ← 这些才是真的没建模")
    print("=" * 74)
    if not dead_global:
        print("  （空）")
    for k, n in dead_global.most_common():
        who = "、".join(dict.fromkeys(dead_who[k]))[:36]
        print(f"  {n:>3} 位  {k:<34} {who}")
    print()
    print("=" * 74)
    print(f"★ 三态之第二态「仅名字表提到」（**判据**，不是事实）：{len(nt_global)} 种键、"
          f"{sum(nt_global.values())} 位次")
    print("=" * 74)
    print("  三态＝`真有人读` ／ `仅名字表提到`（本节）／ `无人读`（上一节）——**前两者不许压成一个**。")
    print("  判别式（启发式，原文）：该字面量**所在行去掉字符串与注释后只剩分隔符**（无调用 `(`、")
    print("  无属性访问 `.`、无下标 `[`）⇒ 它只是集合/字典里的一个键名，**没人拿它去取值**。")
    print("  已知窄口：**单行**写的集合/字典（键名与赋值写在同一行）不会被判为名字表 ⇒ 落回「真有人读」。")
    if not nt_global:
        print("  （空）")
    for k, n in nt_global.most_common():
        who = "、".join(dict.fromkeys(nt_who[k]))[:36]
        print(f"  {n:>3} 位  {k:<34} {who}")
    print()
    print("--- 附：第一道命中但源码有人在读的（不是欠账，仅供核对）---")
    for k, n in unclass_global.most_common():
        if k not in dead_global:
            who = "、".join(dict.fromkeys(unclass_who[k]))[:36]
            print(f"  {n:>3} 位  {k:<34} {who}")

    print()
    print("=" * 74)
    print(f"第三道（**天赋整个没有检测器**）：{len(nodet_global)} 个天赋、"
          f"{sum(nodet_global.values())} 位次  ← 前两道看不见的那一类")
    print("=" * 74)
    print("  前两道筛子都是按**黑板键**判的，所以它们看不见这样一个事实：一个")
    print("  天赋哪怕**整个没有检测器**，只要它的键都归得了类（`atk` / `def` /")
    print("  `max_hp` / `attack_speed` / `prob` 都归得了），就会被报成零欠账。")
    print("  能天使的「天使的祝福」「快速弹匣」、星熊的「特种作战策略」「战术")
    print("  装甲」就是这么被漏掉的。这一栏补的就是这个盲区。")
    if not nodet_global:
        print("  （空）")
    for k, n in nodet_global.most_common():
        who = "、".join(dict.fromkeys(nodet_who[k]))[:36]
        print(f"  {n:>3} 位  {k:<34} {who}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
