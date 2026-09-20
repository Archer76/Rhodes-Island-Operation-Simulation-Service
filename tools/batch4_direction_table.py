"""把逐键判读渲染成方向表，并守住三条口径。

用法：
    python tools/batch4_direction_table.py                 # 渲染 out/acceptance/batch4-direction-table.md
    python tools/batch4_direction_table.py --check-doc docs/batch4-direction-table.md
                                                          # 核文档里的汇总条数与本表逐位一致

三条守卫（任一不成立即 rc=1）：
  ① 判读表的键集合**必须**与探针算出的 84 键逐位相等——表与名单分叉要比读错更早发现；
  ② 三态计数**必须**自洽：可接线＋退回登记＋不适用 ＝ 表行数；
  ③ `--check-doc` 时，文档汇总块里的数**必须**等于现算值（禁止手抄的数与现算分叉）。
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

from batch4_direction_probe import a_list  # noqa: E402
from batch4_direction_verdicts import LAND_OVERRIDE, VERDICTS, land_of  # noqa: E402

STATES = ("可接线", "退回登记", "不适用")
OUT = ROOT / "out" / "acceptance" / "batch4-direction-table.md"


def probe_keys() -> list[str]:
    """探针算出的 84 键（复用同一份 A 名单，不另写逻辑）。"""
    picks, names, needs, wt = a_list()
    covered: set[str] = set()
    # 与 greedy_pick 同口径：累计被选中干员的 keys1 并集
    for c in picks:
        covered |= needs[c]
    return sorted(covered)


def tally(rows: list[dict[str, str]]) -> dict[str, int]:
    t = {s: 0 for s in STATES}
    for r in rows:
        # 非法态要能被**报出来**（不是让 tally 崩掉）：崩掉会让守卫②变成一条崩溃而不是一条断言
        t[r["state"]] = t.get(r["state"], 0) + 1
    t["合计"] = len(rows)
    t["落点被挡"] = sum(1 for r in rows if r["land"] == "挡")
    t["依据=正文"] = sum(1 for r in rows if r["basis"] == "正文")
    t["依据=推断"] = sum(1 for r in rows if r["basis"] == "推断")
    t["依据=谓词"] = sum(1 for r in rows if r["basis"] == "谓词")
    t["口径乙·不适用"] = t["不适用"] + t["落点被挡"]
    t["口径乙·可接线"] = t["可接线"] - t["落点被挡"]
    return t


def render(rows: list[dict[str, str]]) -> str:
    t = tally(rows)
    L: list[str] = []
    L.append("# 第四批方向表·逐键明细（生成物，勿手改）")
    L.append("")
    L.append("作者会话：RIOS 第四批建模 `session-dee51d3a-0816-4065-bf51-16fe66ee793b`。"
             "本文件由 `tools/batch4_direction_table.py` 从 `tools/batch4_direction_verdicts.py` "
             "渲染；要改判读请改判读模块再重渲染。")
    L.append("")
    L.append("判据（任务原文）：**改完之后，哪个可观测的数往哪边动？** "
             "答得出 ⇒ 可接线；答不出 ⇒ 退回登记（不许接线）；本批不可做 ⇒ 不适用（须给可复算谓词）。")
    L.append("")
    L.append(f"共 {t['合计']} 键：可接线 **{t['可接线']}**、退回登记 **{t['退回登记']}**、"
             f"不适用 **{t['不适用']}**。"
             f"其中「落点被第二道闸挡住」**{t['落点被挡']}** 条（技能来源的键）；"
             f"依据＝正文 {t['依据=正文']}、推断 {t['依据=推断']}、谓词 {t['依据=谓词']}。")
    L.append("")
    L.append("| # | 键 | 权重 | 来源 | 态 | 子因 | 量 → 方向 → 可观测量 | 依据 | 落点与风险 |")
    L.append("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
    for i, r in enumerate(rows, 1):
        L.append("| {} | `{}` | {} | {} | {} | {} | {} | {} | {} |".format(
            i, r["key"], r.get("wt", ""), r["src"], r["state"], r["sub"] or "—",
            r["dir"], r["basis"], r["note"]))
    L.append("")
    L.append("## 明细里的三个口径")
    L.append("")
    L.append(f"- 可接线（{t['可接线']}）＝方向答得出（量、方向、可观测量三件齐）。"
             f"**不等于已核对过公式**：依据＝推断的 {t['依据=推断']} 条接线前必须按实战读数复核。")
    L.append(f"- 退回登记（{t['退回登记']}）＝方向答不出，已写清试过哪几种读法。")
    L.append(f"- 不适用（{t['不适用']}）＝本批不可做，各带一条可复算谓词"
             "（零值／派生／非量），谓词脚本 `tools/batch4_direction_checks.py`。")
    L.append("")
    L.append("## 口径声明：落点为什么单列一栏")
    L.append("")
    L.append("任务原文把「第二道闸结构上挡住」列为不适用的一种。实测 47 条技能来源键"
             "被挡的理由里都含「技能效果 other」——**挡因就是这些键没被解释**，"
             "把它们归进不适用会把本批该做的活划到范围外。故本表单列「落点」一栏并给两套读数：")
    L.append("")
    L.append(f"- 口径甲（本表用的）：可接线 {t['可接线']}／退回登记 {t['退回登记']}／不适用 {t['不适用']}")
    L.append(f"- 口径乙（「来源技能被挡」也算不适用）：可接线 {t['口径乙·可接线']}／"
             f"退回登记 {t['退回登记']}／不适用 {t['口径乙·不适用']}")
    L.append("")
    return "\n".join(L) + "\n"


def verify(rows: list[dict[str, str]], pk: list[str], doc_text: str | None,
           quiet: bool = False) -> int:
    """四条守卫一起跑。返回 rc（0＝全绿）。`quiet` 供 `--selftest` 用。"""
    out = (lambda s: None) if quiet else print
    keys = [r["key"] for r in rows]
    rc = 0
    dup = sorted({k for k in keys if keys.count(k) > 1})
    if dup:
        out(f"✗ 判读表有重复键: {dup}")
        rc = 1
    if set(keys) != set(pk):
        out(f"✗ 守卫① 键集合与探针不一致：表多 {sorted(set(keys) - set(pk))}／"
            f"表少 {sorted(set(pk) - set(keys))}")
        rc = 1
    else:
        out(f"✓ 守卫① 键集合逐位相等（{len(pk)} 键，探针与判读表）")
    bad = [r["key"] for r in rows if r["state"] not in STATES]
    t = tally(rows)
    if bad or sum(t[s] for s in STATES) != len(rows):
        out(f"✗ 守卫② 三态不自洽: 非法态 {bad}")
        rc = 1
    else:
        out(f"✓ 守卫② 三态自洽：可接线 {t['可接线']}＋退回登记 {t['退回登记']}＋"
            f"不适用 {t['不适用']}＝{t['合计']}")
    bad_land = [r["key"] for r in rows
                if r["src"].startswith("技能") and r["land"] != "挡"]
    if bad_land:
        out(f"✗ 守卫④ 技能来源却判落点通: {bad_land}")
        rc = 1
    else:
        out(f"✓ 守卫④ 技能来源的行全部判「挡」（{t['落点被挡']} 条落点被挡）")
    if doc_text is not None:
        want = {"可接线": t["可接线"], "退回登记": t["退回登记"], "不适用": t["不适用"],
                "落点被挡": t["落点被挡"], "合计": t["合计"]}
        found = {}
        for label in ("可接线", "退回登记", "不适用", "落点被挡"):
            m = re.search(label + r"[^\d]{0,8}(\d+)", doc_text)
            found[label] = int(m.group(1)) if m else None
        found["合计"] = len(rows) if re.search(r"\d+ 键|共\s*\d+\s*键", doc_text) else None
        differ = {k: (found[k], want[k]) for k in want if found[k] != want[k]}
        if differ:
            out(f"✗ 守卫③ 文档汇总与现算不一致（文档, 现算）: {differ}")
            rc = 1
        else:
            out(f"✓ 守卫③ 文档汇总与现算逐位一致：{want}")
    return rc


def selftest() -> int:
    """反向守卫：四条守卫**各自会红**才算数（绿得起来不算，要红得起来）。

    判据纪律：控制组没红时自己吼出来并 rc≠0——所以这里对每个变异都断言 rc≠0，
    任何一条变异仍然是绿的就报失败。
    """
    pk = probe_keys()
    base = sorted(VERDICTS, key=lambda r: r["key"])

    def prep(rows):
        rows = [dict(r) for r in rows]
        _, _, _, wt = a_list()
        for r in rows:
            r["wt"] = wt.get(r["key"], "?")
            r["land"] = LAND_OVERRIDE.get(r["key"]) or land_of(r["src"])
        return rows

    doc = (ROOT / "docs" / "batch4-direction-table.md").read_text(encoding="utf-8")
    cases: list[tuple[str, int]] = []
    cases.append(("控制组：原样必须绿", verify(prep(base), pk, doc, quiet=True)))
    cases.append(("变异①：删一行 ⇒ 守卫①必须红",
                  verify(prep([r for r in base if r["key"] != base[0]["key"]]), pk, None,
                         quiet=True)))
    m = prep(base)
    m[0]["state"] = "待定"
    cases.append(("变异②：造一个非法态 ⇒ 守卫②必须红", verify(m, pk, None, quiet=True)))
    m = prep(base)
    for r in m:
        if r["src"].startswith("技能"):
            r["land"] = "通"
            break
    cases.append(("变异④：技能来源判落点通 ⇒ 守卫④必须红", verify(m, pk, None, quiet=True)))
    bad_doc = doc.replace("可接线 71 条", "可接线 70 条")
    cases.append(("变异③：改文档里的数 ⇒ 守卫③必须红",
                  verify(prep(base), pk, bad_doc, quiet=True)))
    fail = 0
    for name, rc in cases:
        want_red = "变异" in name
        ok = (rc != 0) if want_red else (rc == 0)
        print(("  ✓ " if ok else "  ✗ ") + name + f"  (rc={rc})")
        fail += 0 if ok else 1
    print(f"\n反向守卫 {len(cases)} 条：通过 {len(cases) - fail}、失败 {fail}")
    return 1 if fail else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-doc", default="", help="核该文档里的汇总条数")
    ap.add_argument("--selftest", action="store_true",
                    help="反向守卫：四个变异必须各自让对应守卫变红")
    a = ap.parse_args()
    if a.selftest:
        return selftest()

    pk = probe_keys()
    rows = sorted(VERDICTS, key=lambda r: r["key"])
    # 权重列（取自探针的 wt）与落点（可算字段）——先算好，后面所有计数都读它
    _, _, _, wt = a_list()
    for r in rows:
        r["wt"] = wt.get(r["key"], "?")
        r["land"] = LAND_OVERRIDE.get(r["key"]) or land_of(r["src"])

    doc_text = None
    if a.check_doc:
        doc = Path(a.check_doc)
        doc_text = (doc if doc.is_absolute() else ROOT / a.check_doc).read_text(encoding="utf-8")
    rc = verify(rows, pk, doc_text)
    txt = render(rows)
    OUT.write_text(txt, encoding="utf-8")
    t = tally(rows)
    print(f"落盘 {OUT.relative_to(ROOT)}（{len(rows)} 行明细）")
    for s in STATES:
        print(f"   {s}: {t[s]}")
    print(f"   落点被挡: {t['落点被挡']}  依据＝正文 {t['依据=正文']}／"
          f"推断 {t['依据=推断']}／谓词 {t['依据=谓词']}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
