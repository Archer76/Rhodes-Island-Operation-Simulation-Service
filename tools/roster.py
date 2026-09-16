# -*- coding: utf-8 -*-
"""把森空岛名册翻成**算符可直接吃的口径**，并导出一份人看的清单。

四件必须处理的事
----------------
1. `data.chars` 里**没有名字**，只有 `charId`；名字要回 `character_table` 查。
2. **三种模组不算数**，必须剔掉：
   - `type == "INITIAL"` —— 基础证章，只有文字描述，`battle_equip_table` 里没有；
   - `isSpecialEquip == True` —— `specialEquipDesc` 一律是「适配限定模式」，
     涵盖**特限证章 / 特勤证章 / 新起点**（全表 21 个）。这类模组**有**战斗数值，
     所以「查得到数值就当模组装」是错的，必须靠这个标志位挡。
     实测踩坑：能天使装的是 `uniequip_001_angel`（基础证章），
     机械师装的是 `uniequip_002_mcnist`（**特勤**证章），
     提丰装的是 `uniequip_004_typhon`（**特限**证章）——后两个都白给了属性。
3. 潜能：`potentialRank` 是 **0 起算**，显示潜能 = rank + 1。
4. 信赖：`favorPercent` 是 **0–200** 标度（200 = 满信赖），显示信赖 = /2。

产出
----
    data/skland/roster_<uid>.json   算符口径（含专精与可用模组）
    docs/roster-<uid>.md            人看的全量清单

用法
----
    python tools/roster.py
    python tools/roster.py --uid 10404662
    python tools/roster.py --squad 机械师 圣聆初雪 ...   # 顺带打印指定编队
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.operator import OperatorCalculator  # noqa: E402

SKLAND_DATA = ROOT / "data" / "skland"
DOCS = ROOT / "docs"

SPEC_LABEL = {0: "-", 1: "一", 2: "二", 3: "三"}

#: 模组不可用的原因
STATUS_CN = {
    "ok": "可用",
    "initial": "基础证章·无属性",
    "special": "限定模式专用·不生效",
    "no_data": "无战斗数值",
}


def load_skland(uid: str | None = None) -> dict:
    files = sorted(SKLAND_DATA.glob("opers_*.json"))
    if not files:
        raise SystemExit(f"{SKLAND_DATA} 下没有 opers_*.json，先跑 tools/skland.py fetch")
    if uid:
        files = [f for f in files if f.stem.endswith(uid)]
        if not files:
            raise SystemExit(f"没有 uid={uid} 的名册")
    return json.loads(files[-1].read_text(encoding="utf-8"))


def classify(calc, uni: dict, battle: dict, equip_id: str) -> str:
    """判断一件模组能不能算数。"""
    v = uni.get(equip_id)
    if v is None:
        return "no_data"
    if v.get("type") == "INITIAL":
        return "initial"
    if v.get("isSpecialEquip"):
        return "special"          # 适配限定模式：特限/特勤证章、新起点
    if equip_id not in battle:
        return "no_data"
    try:
        if not calc.module_levels(equip_id):
            return "no_data"
    except Exception:
        return "no_data"
    return "ok"


def build(uid: str | None = None) -> dict:
    raw = load_skland(uid)
    calc = OperatorCalculator()
    uni = calc._load_uniequip()
    battle = calc._load_battle_equip()
    info = raw.get("charInfo") or {}

    rows = []
    for o in raw["opers"]:
        cid = o["charId"]
        # 名字优先取 charInfoMap：它带升变形态，character_table 查不到那些
        ci = info.get(cid) or {}
        name = ci.get("name")
        if not name:
            try:
                name = calc.character(cid).get("name") or cid
            except Exception:
                name = cid

        # 逐个模组判可用性，顺带挑一个"已解锁且可用"的替代品
        detail = []
        best_alt, best_alt_lv = None, 0
        for e in o["equips"]:
            eid, elv = e["id"], e["level"]
            status = classify(calc, uni, battle, eid)
            detail.append({
                "id": eid,
                "level": elv,
                "locked": e["locked"],
                "status": status,
                "name": (uni.get(eid) or {}).get("uniEquipName") or "",
            })
            if status == "ok" and not e["locked"] and elv > best_alt_lv:
                best_alt, best_alt_lv = eid, elv

        equipped = o.get("defaultEquipId") or None
        eq_status = classify(calc, uni, battle, equipped) if equipped else "ok"
        usable = equipped if eq_status == "ok" else None
        usable_lv = next((e["level"] for e in o["equips"] if e["id"] == usable), 0)

        rows.append({
            "charId": cid,
            "name": name,
            "subProfession": ci.get("subProfessionName") or "",
            "profession": ci.get("profession") or "",
            "elite": o["elite"],
            "level": o["level"],
            "potentialRank": o["potentialRank"],
            "potential": o["potential"],
            "trust": o["favorPercent"] / 2.0,
            # 算符该用的
            "module": usable,
            "module_level": usable_lv,
            # 账号现状（可能是不能用的那种）
            "equipped_module": equipped,
            "equipped_module_level": next(
                (e["level"] for e in o["equips"] if e["id"] == equipped), 0),
            "equipped_status": eq_status,
            "module_alt": best_alt if best_alt != usable else None,
            "module_alt_level": best_alt_lv if best_alt != usable else 0,
            "modules": detail,
            "defaultSkillId": o.get("defaultSkillId") or "",
            "mastery": {s["skillId"]: s["specializeLevel"] for s in o["skills"]},
        })
    rows.sort(key=lambda r: (-r["elite"], -r["level"], r["charId"]))
    return {"uid": raw["uid"], "nickName": raw.get("nickName"),
            "count": len(rows), "opers": rows}


def _spec_cell(r: dict) -> str:
    byslot = {}
    for sid, m in r["mastery"].items():
        tail = sid.rsplit("_", 1)[-1]
        slot = int(tail) if tail.isdigit() else len(byslot) + 1
        byslot.setdefault(slot, m)
    return "/".join(SPEC_LABEL.get(byslot.get(i, 0), "-") for i in (1, 2, 3))


def _mod_cell(r: dict) -> str:
    if not r["equipped_module"]:
        return "—"
    s = r["equipped_status"]
    txt = f"{r['equipped_module']} Lv{r['equipped_module_level']}"
    if s != "ok":
        txt += f" **({STATUS_CN[s]})**"
        if r["module_alt"]:
            txt += f" → 可用替代 {r['module_alt']} Lv{r['module_alt_level']}"
    return txt


def write_json(data: dict) -> Path:
    p = SKLAND_DATA / f"roster_{data['uid']}.json"
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


def write_md(data: dict) -> Path:
    ops = data["opers"]
    L = [f"# 干员名册（森空岛 uid={data['uid']} / {data.get('nickName') or '?'}）", ""]
    L.append(f"共 **{len(ops)}** 名。信赖 = `favorPercent/2`，潜能 = `potentialRank+1`。")
    L.append("")
    L.append("**模组判定**：只有「专属模组」算数。基础证章（无属性）与"
             "**限定模式专用**（特限证章 / 特勤证章 / 新起点，`isSpecialEquip`）"
             "一律不计入属性。")
    L.append("")
    n_spec = sum(1 for r in ops if any(r["mastery"].values()))
    bad = [r for r in ops if r["equipped_module"] and r["equipped_status"] != "ok"]
    L.append(f"- 有专精的：**{n_spec}** 名")
    L.append(f"- 装了**不生效**模组的：**{len(bad)}** 名"
             f"（基础证章 {sum(1 for r in bad if r['equipped_status']=='initial')}、"
             f"限定模式专用 {sum(1 for r in bad if r['equipped_status']=='special')}）")
    L.append(f"- 其中**有可用替代模组**的："
             f"**{sum(1 for r in bad if r['module_alt'])}** 名")
    L.append("")
    L.append("| 干员 | charId | 子职业 | 精英 | 等级 | 潜能 | 信赖 | 专精(1/2/3) | 已装备模组（判定） |")
    L.append("|---|---|---|---|---|---|---|---|---|")
    for r in ops:
        star = "★" if r["elite"] >= 2 else ""
        L.append("| {n}{s} | `{c}` | {sub} | E{e} | {lv} | {p} | {t:g}% | {sp} | {m} |".format(
            n=r["name"], s=star, c=r["charId"], sub=r.get("subProfession") or "—",
            e=r["elite"], lv=r["level"],
            p=r["potential"], t=r["trust"], sp=_spec_cell(r), m=_mod_cell(r)))
    p = DOCS / f"roster-{data['uid']}.md"
    p.write_text("\n".join(L) + "\n", encoding="utf-8")
    return p


def print_squad(data: dict, names: list[str]) -> None:
    calc = OperatorCalculator()
    # 一个名字可能对应多个 charId（阿米娅有近卫/术师等升变形态），
    # 优先取算符算得出来的那个基础形态。
    byname: dict[str, dict] = {}
    for r in data["opers"]:
        n = r["name"]
        if n not in byname:
            byname[n] = r
        elif not calc.exists(byname[n]["charId"]) and calc.exists(r["charId"]):
            byname[n] = r
    hdr = f"{'干员':<13}{'E/L':<9}{'潜':<3}{'信赖':<8}{'专精':<9}{'算符用模组':<30}{'atk'}"
    print(hdr)
    print("-" * len(hdr))
    for n in names:
        r = byname.get(n)
        if not r:
            print(f"{n:<13} 名册里没有")
            continue
        try:
            new = calc.stats(r["charId"], elite=r["elite"], level=r["level"],
                             trust=r["trust"], potential=r["potential"],
                             module=r["module"], module_level=r["module_level"]).total["atk"]
        except Exception:
            new = None
        old = calc.stats(r["charId"], elite=r["elite"], level=r["level"],
                         trust=100.0, potential=r["potential"]).total["atk"]
        mod = r["module"] or "—(无可用模组)"
        if r["module"]:
            mod += f" Lv{r['module_level']}"
        if r["equipped_module"] and r["equipped_status"] != "ok":
            mod += f"  [装着{STATUS_CN[r['equipped_status']]}]"
        print(f"{n:<13}E{r['elite']} L{r['level']:<5}{r['potential']:<3}{r['trust']:g}%"
              f"{'':<4}{_spec_cell(r):<9}{mod:<30}{old}→{new}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="roster", description="森空岛名册 → 算符口径")
    p.add_argument("--uid")
    p.add_argument("--squad", nargs="*", default=[])
    args = p.parse_args(argv)

    data = build(args.uid)
    jp = write_json(data)
    mp = write_md(data)
    print(f"uid={data['uid']} [{data.get('nickName')}]  {data['count']} 名")
    print(f"  算符口径 -> {jp}")
    print(f"  人看清单 -> {mp}")
    if args.squad:
        print()
        print_squad(data, args.squad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
