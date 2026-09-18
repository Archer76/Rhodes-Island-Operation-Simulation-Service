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
import sys
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
_LITERAL = re.compile(r"""["']([A-Za-z_@$][A-Za-z0-9_@$]*)["']""")
# 字符集里的 `$` 是必须的：解析层把黑板里 `valueStr` 的字符串值存成 **`$键名`**
# （`operator/talent._blackboard`，技能那边同理），源码里读的就是 `"$projectile"`
# 这样的字面量。不收 `$` 会让这一类键**永远**落在"无人读"栏里——2026-09-18
# 焰狐龙梓兰的 `$projectile` / `$ignore_build_type_target_range` 就是这种假欠账
# （当时两位数字都齐了、代码也确实在读，仍旧报"没人读"）。


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
    out: list[tuple[str, str]] = []
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
            for k in d:
                out.append(("特性", k))
    finally:
        conn.close()
    return out


def keys_of(cid: str) -> tuple[list[tuple[str, str]],
                              list[tuple[str, str]],
                              list[tuple[str, str]]]:
    """返回 (技能键, 天赋键, **特性键**)，元素是 (来源说明, 键名)。"""
    sk_keys: list[tuple[str, str]] = []
    for sk in SkillBook().for_operator(cid):
        try:
            lv = sk.level(level=7, mastery=3)
        except Exception:  # noqa: BLE001
            continue
        for k in (lv.blackboard or {}):
            sk_keys.append((f"{sk.skill_id}·{lv.name}", k))
    t_keys: list[tuple[str, str]] = []
    try:
        for t in TalentBook().for_operator(cid):
            for k in (getattr(t, "blackboard", None) or {}):
                t_keys.append((getattr(t, "name", "?"), k))
    except Exception:  # noqa: BLE001
        pass
    return sk_keys, t_keys, trait_keys_of(cid)


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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=0)
    ap.add_argument("--only", nargs="*", default=None)
    ap.add_argument("--all", action="store_true",
                    help="连非 E2 的也看（默认只看 E2）")
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
    elif not a.all:
        roster = [r for r in roster if r[2] == "E2"]

    lits = source_literals()
    det = detector_text()
    rows = []
    unclass_global: Counter[str] = Counter()
    unclass_who: defaultdict[str, list[str]] = defaultdict(list)
    dead_global: Counter[str] = Counter()
    dead_who: defaultdict[str, list[str]] = defaultdict(list)
    nodet_global: Counter[str] = Counter()
    nodet_who: defaultdict[str, list[str]] = defaultdict(list)
    for name, cid, elite, lvl in roster:
        sk_keys, t_keys, tr_keys = keys_of(cid)
        allk = sk_keys + t_keys + tr_keys
        if not allk:
            continue
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
