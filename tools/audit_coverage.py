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
import re
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
_LITERAL = re.compile(r"""["']([A-Za-z_@][A-Za-z0-9_@]*)["']""")


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


def keys_of(cid: str) -> tuple[list[tuple[str, str]], list[tuple[str, str]]]:
    """返回 (技能键, 天赋键)，元素是 (来源说明, 键名)。"""
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
    return sk_keys, t_keys


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
    rows = []
    unclass_global: Counter[str] = Counter()
    unclass_who: defaultdict[str, list[str]] = defaultdict(list)
    dead_global: Counter[str] = Counter()
    dead_who: defaultdict[str, list[str]] = defaultdict(list)
    for name, cid, elite, lvl in roster:
        sk_keys, t_keys = keys_of(cid)
        allk = sk_keys + t_keys
        if not allk:
            continue
        bad = [(src, k) for src, k in allk if _classify(k) is None]
        # 第二道：源码里没人读过 = 真的没建模
        dead = [(src, k) for src, k in bad if not is_read(k, lits)]
        for _src, k in bad:
            unclass_global[k] += 1
            unclass_who[k].append(name)
        for _src, k in dead:
            dead_global[k] += 1
            dead_who[k].append(name)
        buckets = Counter((_classify(k) or ("other",))[0] for _s, k in allk)
        rows.append((len(dead), len(bad), len(allk), name, cid, elite, lvl,
                     buckets, dead))

    rows.sort(key=lambda r: (-r[0], -r[1], r[3]))
    if a.top:
        rows = rows[:a.top]

    print(f"{'干员':<14}{'E/L':<9}{'键数':>5}{'未归类':>7}{'无人读':>7}  分桶")
    print("-" * 74)
    for ndead, nbad, ntot, name, cid, elite, lvl, buckets, _d in rows:
        b = " ".join(f"{k}={v}" for k, v in sorted(buckets.items()))
        flag = "  ←" if ndead else ("  ·" if nbad else "")
        print(f"{name:<14}{elite + ' ' + lvl:<9}{ntot:>5}{nbad:>7}{ndead:>7}  {b}{flag}")

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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
