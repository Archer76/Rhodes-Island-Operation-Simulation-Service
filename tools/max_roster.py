"""生成一份**满练度、且已建模干员**的名册，用来解那些真名册打不过的关。

博士裁定（2026-09-19）：「接下来的解算如果无法通过就用完全满练度的干员尝试，
用已经完成建模的那几个」——真名册受练度所限解不出三星时，用这套面板去问
「这一关在模拟器里到底打不打得过」，把**关卡难度**与**名册练度**两件事分开。

两点口径，别混：

* **满练度面板**指 E2 + 满级（6★90 / 5★80 / 4★70）+ 满潜，**不是**某位博士的
  实际练度；导出名册里那些 `elite/level/potential` 会被覆盖，`own` 一律置真。
* **已建模**指 `ak_tactic/battle/` 里有对应结算的那几位（判据见
  `docs/roadmap.md`：`battle/` 里有结算才算已建模）。名单出处是
  `docs/batch3-plan.md` 的第三批十位与它正文列出的第二批十一位——
  **改名单要先去那两份文档核对**，不要凭印象加人。

用法：

    python tools/max_roster.py                        # 写到 out/roster_max_modelled.json
    python tools/max_roster.py --out <路径> --source <导出名册>
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

#: 第三批十位（`docs/batch3-plan.md` 的表）+ 第二批十一位（同文档正文列出的 charId）。
#: 名字只是备注，真正认的是 charId。
MODELLED: tuple[tuple[str, str], ...] = (
    ("char_103_angel", "能天使"),
    ("char_1041_angel2", "新约能天使"),
    ("char_1048_orchd2", "焰狐龙梓兰"),
    ("char_1051_headb2", "怒潮凛冬"),
    ("char_1052_kalts2", "凯尔希·思衡托"),
    ("char_136_hsguma", "星熊"),
    ("char_311_mudrok", "泥岩"),
    ("char_4132_ascln", "阿斯卡纶"),
    ("char_4217_makoto", "结城理"),
    ("char_4228_closur", "可露希尔"),
    ("char_4195_radian", "电弧"),
    ("char_4230_mcnist", "机械师"),
    ("char_2027_wang", "望"),
    ("char_1050_chen3", "赤刃明霄陈"),
    ("char_1046_sbell2", "圣聆初雪"),
    ("char_2023_ling", "令"),
    ("char_002_amiya", "阿米娅"),
    ("char_1001_amiya2", "阿米娅（近卫）"),
    ("char_2012_typhon", "提丰"),
    ("char_4133_logos", "逻各斯"),
    ("char_1015_aglna2", "予愿安洁莉娜"),
)

#: 满级：6★ 90 / 5★ 80 / 4★ 70 / 3★ 55 / 2★ 30 / 1★ 30。
MAX_LEVEL = {6: 90, 5: 80, 4: 70, 3: 55, 2: 30, 1: 30}

DEFAULT_SOURCE = Path("data/operbox/Arknights_OperBox_Export.json")
DEFAULT_OUT = Path("out/roster_max_modelled.json")


def build(source: Path) -> tuple[list[dict], list[str]]:
    """返回（满练度名册, 缺人提示）。名册只保留已建模的那几位。"""
    raw = json.loads(source.read_text(encoding="utf-8-sig"))
    by_id = {c["id"]: c for c in raw}
    out: list[dict] = []
    missing: list[str] = []
    for cid, name in MODELLED:
        c = by_id.get(cid)
        if c is None:
            missing.append(f"{name}({cid})")
            continue
        c = dict(c)
        c.update(own=True, elite=2,
                 level=MAX_LEVEL.get(int(c.get("rarity", 6)), 90), potential=6)
        out.append(c)
    return out, missing


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                    help="源名册（MAA 导出，读得出 UTF-8 BOM）")
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args(argv)

    if not args.source.exists():
        print(f"[skip] 找不到源名册 {args.source}——本脚本只做属性改写，"
              f"不带任何人的练度数据。")
        return 0
    roster, missing = build(args.source)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(roster, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    print(f"满练度已建模名册：{len(roster)} 位 → {args.out}")
    print("名单：" + "、".join(c["name"] for c in roster))
    if missing:
        print("⚠ 源名册里没有（本次缺席）：" + "、".join(missing))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
