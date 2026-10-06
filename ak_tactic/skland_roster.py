# -*- coding: utf-8 -*-
"""把森空岛拉回来的 `opers_<uid>.json` 翻成**名册文件** `roster_<uid>.json`。

## 为什么这份实现住在 `ak_tactic` 里（而不是只放在 `tools/roster.py`）

2026-09-29 博士实测：「自动获取名册还是有问题」。在**发布树**里复现到根因：

    LookupError: … 已经试过直接去森空岛取：ModuleNotFoundError: No module named 'roster'

原先那段转换只住在 `tools/roster.py` —— 那是**开发侧脚本**，发布包按
「只放运行时必须的文件」的白名单（`docs/python-to-go-migration.md` §12.6）
**没把它打进去**；于是桥里 `import roster` 直接炸，自动取名册那条路**一次也没走通过**
（而外层报错只说"名册取不到"，看不出是缺文件 —— 这正是本仓最反对的那种"看着正常"）。

⇒ 转换逻辑搬进包里（包随发布走），`tools/roster.py` 改成**薄壳**（开发侧继续用），
桥上调这里的函数。**同一件事只有一份实现**。

## 依赖

* `ak_tactic.operator.OperatorCalculator`（在包里，随发布走）；
* `data/skland/opers_<uid>.json`（`ak_tactic.skland.fetch_all()` 落的那一份）；
* `data/gamedata/**` 的模组/战斗装备表（`OperatorCalculator` 自己会取）。
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .operator import OperatorCalculator

__all__ = ["skland_dir", "roster_file", "load_opers", "build_roster", "write_roster"]

#: 模组不可用的原因（与 `tools/roster.py` 同一份文案，界面上要能读）
STATUS_CN = {
    "ok": "可用",
    "initial": "基础证章·无属性",
    "special": "限定模式专用·不生效",
    "no_data": "无战斗数值",
}

SPEC_LABEL = {0: "-", 1: "一", 2: "二", 3: "三"}


def skland_dir() -> Path:
    """`data/skland/`。

    ★ 口径与 `ak_tactic/tui/data.py::roster_file` **逐字一致**（包根往上两级再拼
    `data/skland`）—— 发布树里包在 `eng/ak_tactic/`，于是它落在 `eng/data/skland/`，
    正是界面认的那个数据根。两处各算一遍是因为 `tui` 那个模块要的重依赖太多，
    不该为一个路径把核心模块拖进 TUI 的依赖里。
    """
    root = Path(__file__).resolve().parent.parent
    return root / "data" / "skland"


def roster_file(uid: str) -> Path:
    return skland_dir() / f"roster_{uid}.json"


def load_opers(uid: str | None = None) -> dict:
    """读 `opers_<uid>.json`（不给 uid 就取最新那一份）。"""
    files = sorted(skland_dir().glob("opers_*.json"))
    if not files:
        raise FileNotFoundError(
            "%s 下没有 opers_*.json —— 先 `python tools/skland.py fetch`" % skland_dir())
    if uid:
        files = [f for f in files if f.stem.endswith(str(uid))]
        if not files:
            raise FileNotFoundError("没有 uid=%s 的 opers 文件" % uid)
    return json.loads(files[-1].read_text(encoding="utf-8"))


def classify(calc: OperatorCalculator, uni: dict, battle: dict, equip_id: str) -> str:
    """判断一件模组能不能算数（原样搬自 `tools/roster.py`）。"""
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
    except Exception:                                     # noqa: BLE001
        return "no_data"
    return "ok"


def build_roster(uid: str | None = None, *, raw: dict | None = None,
                 calc: OperatorCalculator | None = None) -> dict:
    """`opers` → 名册 dict（含 `module` / `module_level` / `mastery`）。

    `raw` 给了就直接用（调用方刚拉回来的那一份），否则按 uid 从盘上读。
    """
    raw = raw if raw is not None else load_opers(uid)
    calc = calc or OperatorCalculator()
    uni = calc._load_uniequip()
    battle = calc._load_battle_equip()
    info = raw.get("charInfo") or {}

    rows: list[dict[str, Any]] = []
    for o in raw["opers"]:
        cid = o["charId"]
        #: 名字优先取 charInfoMap：它带升变形态，character_table 查不到那些
        ci = info.get(cid) or {}
        name = ci.get("name")
        if not name:
            try:
                name = calc.character(cid).get("name") or cid
            except Exception:                             # noqa: BLE001
                name = cid

        #: 逐个模组判可用性，顺带挑一个"已解锁且可用"的替代品
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
            #: 算符该用的
            "module": usable,
            "module_level": usable_lv,
            #: 账号现状（可能是不能用的那种）
            "equipped_module": equipped,
            "equipped_module_level": next(
                (e["level"] for e in o["equips"] if e["id"] == equipped), 0),
            "equipped_status": eq_status,
            "module_alt": best_alt if best_alt != usable else None,
            "module_alt_level": best_alt_lv if best_alt != usable else 0,
            "modules": detail,
            "mainSkillLvl": o.get("mainSkillLvl"),
            "defaultSkillId": o.get("defaultSkillId") or "",
            "mastery": {s["skillId"]: s["specializeLevel"] for s in o["skills"]},
        })
    rows.sort(key=lambda r: (-r["elite"], -r["level"], r["charId"]))
    return {"uid": raw["uid"], "nickName": raw.get("nickName"),
            "count": len(rows), "opers": rows}


def write_roster(data: dict, *, path: Path | None = None) -> Path:
    """把名册写到 `data/skland/roster_<uid>.json`（原子写）。"""
    p = path or roster_file(str(data["uid"]))
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".part")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p
