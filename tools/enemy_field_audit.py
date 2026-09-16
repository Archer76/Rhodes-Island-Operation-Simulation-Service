# -*- coding: utf-8 -*-
"""敌人页字段审计：PRTS 模板上有哪些参数，我们入了库、哪些没入。

    python tools/enemy_field_audit.py                # 全量（走缓存，不联网）
    python tools/enemy_field_audit.py --pages 200    # 只审前 N 页
    python tools/enemy_field_audit.py --unknown      # 只打未入库的那部分

## 为什么要常驻一个

PRTS 的敌人模板是站内编辑维护的，**随时可能加参数**（比如新出一类抗性、
新加一栏数值）。本项目的解析器是白名单式的（`_NUM_FIELDS` / `_SP_FIELDS`），
上游加了新字段而我们没跟，症状是**静默少数据**——不报错、行数照旧，
只有对着页面逐项点才算得出来。这个脚本就是把"逐项点"固化下来。

判据分三层，别混：
  * **入库**：参数有对应列，值真的进了库；
  * **认出但丢弃**：解析器知道它，但按设计不存（如 `index` 只用来排序）；
  * **未入库** ✗：解析器完全不认识——**这一层才是要看的**。
"""

from __future__ import annotations

import argparse
import collections
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.prts.enemy import (                              # noqa: E402
    ERRATA_FIELD, _NUM_FIELDS, _RESIST_OVERRIDE, _SKILL_RE, _SP_FIELDS,
    all_enemy_titles, extract_comments, fetch_enemy_pages,
    find_templates, strip_comments, template_params,
)
from ak_tactic.prts.wikitext import parse_params as _pp        # noqa: E402

#: common2 参数 → 库里的列（`enemy` 表）
_COMMON_MAP: dict[str, str] = {
    "id": "prts_id",
    "名称": "name",
    "显示名": "display_name",
    "index": "index_code",
    "地位级别": "grade",
    "种类": "category",
    "伤害类型": "damage_type",
    "攻击方式": "attack_way",
    "行动方式": "move_way",
    "阵营": "camp",
    "描述": "description",
    "能力": "ability",
    ERRATA_FIELD: "ability_fixed + ability_errata",   # 站方勘误，另一份文本
    "登场活动": "debut_event",
    "非常规敌人": "is_irregular",
}

#: levelcontent 参数 → 库里的列（`enemy_level` 表）
_LEVEL_MAP: dict[str, str] = {
    "名称": "name",
    "地位": "grade",
    "种类": "category",
    "描述": "description",           # 含内联勘误时另存 description_fixed
    "攻击方式": "attack_way",
    "行动方式": "move_way",
    "天赋": "talent",
    _RESIST_OVERRIDE: "enemy_resist(source=覆写)",
    **{k: v for k, v in _NUM_FIELDS.items()},
    **{k: v for k, v in _SP_FIELDS.items()},
}

#: 解析器认识、但按设计**不进库**的参数（出现了也不算漏）
_IGNORED = {
    "index",      # 档号，只用来排序与合并，主键里已有
    "reindex",    # 模板的排序辅助参数
    "注释", "备注", "编辑备注",
}

#: 确认过、**有意不收**的参数：模板上有，但不是战斗数据。
#: 单列一张表而不是塞进 `_IGNORED`，因为它们和"解析器认识"是两回事——
#: 将来上游若把某一项改成战斗字段，这里要能一眼看出当年为什么没收。
_NOT_BATTLE = {
    "相关敌人": "站内互链（如「变形者集群」→[[解构畸变体]]），图鉴导航，不是数值",
    "无头像": "立绘标记（Y/true/exist），纯展示",
    "特殊分类": "主题标签（如「球员」），足球模式用，普通关不生效",
    "位置": "展示用（取值「未知」），与地图落位无关",
}

#: **档案评级字母块**——只在 `common2` 语境下排除。
#:
#: 个别页面（「“Mechanist”，机械之心」「结构性原理(敌方)」）把敌方档案的
#: S/A/B/C/D/E 评级写在 common2 里：`|攻击力=A`、`|移动速度=D`、`|法术抗性=B+`。
#: 麻烦在于**参数名与逐档数值字段完全同名**，但一个是字母一个是数字。
#: 所以判据必须带语境：common2 里这些是评级（不收），levelcontent 里是真数值（照收）。
#: 图鉴级本来也不参与数值解析，忽略它们不会丢任何战斗数据。
_RATINGS = {
    "攻击力", "防御力", "移动速度", "攻击速度", "法术抗性", "元素抗性",
    "损伤抵抗", "耐久",
}
_RATING_REASON = "档案评级字母（S/A/B/C/D/E），与逐档数值同名的展示字段"


def _bucket(name: str, where: str = "common") -> tuple[str, str]:
    """把一个参数名归类。返回 (分类, 去向)。

    `where` 必须说明这个参数来自哪份模板：**两张表有同名参数而去向不同**——
    `名称`/`种类`/`描述`/`攻击方式`/`行动方式` 在 common2 里是图鉴字段（`enemy.*`），
    在 levelcontent 里是**逐档**字段（`enemy_level.*`）。不分来源就会把档位的
    「描述」错标成图鉴的「描述」，总账上凭空多出一串 `enemy.*`。
    """
    if name in _IGNORED:
        return "认识但丢弃", "—"
    if where == "common" and name in _RATINGS:
        return "非战斗数据", _RATING_REASON
    if name in _NOT_BATTLE:
        return "非战斗数据", _NOT_BATTLE[name]
    if where == "common":
        if name in _COMMON_MAP:
            return "入库", f"enemy.{_COMMON_MAP[name]}"
    else:
        if name in _LEVEL_MAP:
            return "入库", f"enemy_level.{_LEVEL_MAP[name]}"
    if name.endswith("抗性") and name != "抗性":
        return "入库", "enemy_resist.name"
    if _SKILL_RE.match(name):
        return "入库", "enemy_skill.*"
    return "未入库", "✗"


def _is_noise(name: str) -> bool:
    """模板展开残留的匿名/占位参数，不是字段。"""
    s = name.strip()
    if not s:
        return True
    return s.isdigit() or s.startswith(("1=", "2="))


def _wrap(names: str, width: int) -> list[str]:
    """把「甲、乙、丙」按宽度折行，折点只在顿号处。"""
    out: list[str] = []
    line = ""
    for part in names.split("、"):
        piece = part if not line else "、" + part
        if line and len(line) + len(piece) > width:
            out.append(line)
            line = part
        else:
            line += piece
    if line:
        out.append(line)
    return out


def audit(limit: int | None, verbose: bool):
    titles = all_enemy_titles()
    if limit:
        titles = titles[:limit]
    print(f"审计 {len(titles)} 个敌人页（走磁盘缓存）……")
    pages = fetch_enemy_pages(titles)

    common_hits: collections.Counter = collections.Counter()
    level_hits: collections.Counter = collections.Counter()
    hidden_hits: collections.Counter = collections.Counter()
    n_common = n_level = 0

    for title in titles:
    # 逐页扫两份模板
        wt = pages.get(title)
        if not wt:
            continue
        for inner in find_templates(wt, "敌人信息/common2"):
            n_common += 1
            for k in template_params(strip_comments(inner)):
                if not _is_noise(k):
                    common_hits[k] += 1
            break
        for inner in find_templates(wt, "敌人信息/levelcontent"):
            n_level += 1
            for k in template_params(strip_comments(inner)):
                if not _is_noise(k):
                    level_hits[k] += 1
            for c in extract_comments(inner):
                for k in _pp(c)[1]:
                    if not _is_noise(k):
                        hidden_hits[k] += 1

    unknown: list[tuple[str, str, int]] = []
    for label, hits in (("common2", common_hits), ("levelcontent", level_hits)):
        total = n_common if label == "common2" else n_level
        where = "common" if label == "common2" else "level"
        print(f"\n=== {label}：{len(hits)} 种参数（{total} 个模板）")
        # 先把**总账**摆出来：每个字段都去了哪。
        # 只列未入库的话，一眼看去会以为整张表都没认——`移动速度`/`数量` 这类
        # 老老实实入着库的字段全被藏起来了，反而让人怀疑根本没拉取。
        buckets: dict[str, list[tuple[str, int]]] = collections.defaultdict(list)
        for name, n in hits.items():
            kind, dest = _bucket(name, where)
            if kind == "未入库":
                unknown.append((label, name, n))
            buckets[kind].append((name, n))

        ok = sorted(buckets.get("入库", []), key=lambda t: -t[1])
        if ok:
            by_table: collections.Counter = collections.Counter()
            for name, n in ok:
                by_table[_bucket(name, where)[1].split(".")[0].split("(")[0]] += n
            tally = "  ".join(f"{t} {n} 次" for t, n in by_table.most_common())
            print(f"  ▸ 入库 {len(ok)} 种 / {sum(n for _n, n in ok)} 次   →  {tally}")
            names = "、".join(f"{name}" for name, _n in ok)
            for line in _wrap(names, 88):
                print(f"      {line}")
            if verbose:
                for name, n in ok:
                    print(f"        {name:<18} {n:>5}  → {_bucket(name, where)[1]}")
        for kind in ("认识但丢弃", "非战斗数据", "未入库"):
            items = sorted(buckets.get(kind, []), key=lambda t: -t[1])
            if not items:
                continue
            print(f"  ▸ {kind} {len(items)} 种 / {sum(n for _n, n in items)} 次")
            for name, n in items:
                reason = "" if kind != "非战斗数据" else f"   {_bucket(name, where)[1]}"
                print(f"      {name:<18} {n:>5}{reason}")

    if hidden_hits:
        print(f"\n=== HTML 注释里的参数：{len(hidden_hits)} 种")
        for name, n in hidden_hits.most_common():
            kind, dest = _bucket(name)
            print(f"  {name:<20} {n:>5} 档  {kind:<10} {dest}")

    print("\n" + "=" * 60)
    if unknown:
        print(f"\n⚠ {len(unknown)} 种参数**没入库**，逐条确认是否战斗相关：")
        for label, name, n in sorted(unknown, key=lambda t: -t[2]):
            print(f"    [{label}] {name:<20} {n:>5} 次")
        return 1
    print("\n✓ 模板上的每一个参数都有去向，没有静默丢失的字段。")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="敌人页字段审计")
    ap.add_argument("--pages", type=int, default=0, help="只审前 N 页（默认全量）")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="连已入库的参数也打出来")
    args = ap.parse_args()
    return audit(args.pages or None, args.verbose)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
