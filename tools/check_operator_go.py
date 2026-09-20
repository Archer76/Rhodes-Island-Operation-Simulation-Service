#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自算的干员面板 vs Python 的 `OperatorCalculator.stats()`。

## 比什么

四份来源**逐份比**（只比 `total` 会让「base 错、抵消后 total 对」溜过去）：
`base` / `trust_bonus` / `potential_bonus` / `total`。

## 覆盖面（★ 不许窄于结论）

名册 20 位 × 每位的 `(精英, 等级)` × 信赖 {0, 50, 100} × 潜能 {1, 6}
——**信赖与潜能要真的扫**，否则那两条支路等于没测。
等级取「底、顶、中间」三档（`interpolate_keyframes` 的夹取/插值/多帧三种情形）。

## 本轮的**具名缺口**

模组那一支（`module_levels`，读 `battle_equip_table.json`）**未接入 Go**——
那份表不在本机 `excel/` 缓存里。工具会把「名册里带模组的干员」逐个列出来，
不静默略过。

用法:
    python tools\\check_operator_go.py
    python tools\\check_operator_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER = ROOT / "fixtures" / "roster_max_modelled.json"

TRUSTS = [0.0, 50.0, 100.0]
POTENTIALS = [1, 6]


def go_opstats(configs: list[dict]) -> list[dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "opstats", "spec": configs}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西（stderr：%s）"
                         % p.stderr.decode("utf-8", "replace")[:400])
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["opstats"]


def norm(v):
    """dict 里 int/float 互通：`0` 与 `0.0` 是同一个读数，别当成不一致。"""
    if isinstance(v, dict):
        return {k: norm(x) for k, x in v.items()}
    if isinstance(v, list):
        return [norm(x) for x in v]
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return float(v)
    return v


def main() -> int:
    from ak_tactic.operator import OperatorCalculator, TalentBook
    from ak_tactic.operator.attack_speed import attack_speed_bonus
    from ak_tactic.battle.traits import (read_combo_attack, read_trait_splash,
                                         apply_splash_talent, read_hp_drain)
    from ak_tactic.battle.talents import find_power_attack
    calc = OperatorCalculator()
    tbook = TalentBook()
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))

    configs: list[dict] = []
    for e in roster:
        cid, elite, level = e["id"], int(e["elite"]), int(e["level"])
        #: 等级的底/顶/中间三档：分别走夹取、夹取、插值（多帧阶段还会走中间帧）
        cap = calc.max_level(cid, elite)
        if not cap:
            continue
        lvls = sorted({1, int(cap), (1 + int(cap)) // 2})
        for lv in lvls:
            for tr in TRUSTS:
                for pot in POTENTIALS:
                    configs.append({
                        "char_id": cid, "elite": elite, "level": lv,
                        "trust": tr, "potential": pot,
                        "module": "", "module_level": 0,
                    })
    #: 模组一支：每位带数值模组的干员、每个等级都扫一遍。
    #: ★ 不扫模组＝那 18/20 位干员的面板**根本没被这条判据覆盖**。
    mod_cfg = 0
    mod_ops: list[str] = []
    for e in roster:
        cid = e["id"]
        try:
            mods = [m for m in calc.modules(cid) if m.get("has_stats")]
        except Exception:                                        # noqa: BLE001
            mods = []
        if not mods:
            continue
        mid = mods[0]["id"]
        try:
            levels = sorted(calc.module_levels(mid))
        except Exception:                                        # noqa: BLE001
            continue
        mod_ops.append("%s(%s:%s)" % (e["name"], mid, levels))
        for mlv in levels:
            for tr in (0.0, 100.0):
                configs.append({
                    "char_id": cid, "elite": int(e["elite"]),
                    "level": int(e["level"]), "trust": tr,
                    "potential": int(e["potential"]),
                    "module": mid, "module_level": mlv,
                })
                mod_cfg += 1

    got = go_opstats(configs)

    mutate = "--mutate" in sys.argv
    if mutate:
        #: ★ **合成一处不一致**：不改任何东西就宣称「守卫成立」是假守卫
        #: （本项目记过：反向守卫必须真换策略/真注入）。
        #: 这里把第一次折算的 `total` 改掉一个键，判据**必须**红。
        k0 = sorted(got[0]["total"])[0]
        got[0]["total"][k0] = got[0]["total"][k0] + 1

    bad = 0
    compared = 0
    #: ★ 行使计数：三个 aspd 字段**各有几次非零**。全零的绿是零信息量的绿——
    #: 若三条都是 0，这条判据什么也没证明（本项目记过「必然绿」这一类）。
    aspd_hits = {"aspd_flat": 0, "aspd_when_free": 0, "aspd_high_ground": 0}
    #: 连击三字段的行使计数：这三条「没有这条」是 1/1.0/1.0，
    #: 所以要数的是**非 1** 的次数（非零判据在这里会数成「全员命中」）。
    combo_hits = {"combo_hits": 0, "combo_hit_scale": 0, "combo_damage_scale": 0}
    #: 这条连击天赋**命中**的次数与它实际的 hit_scale 取值。
    #: ⚠ 不能靠「字段值 ≠ 默认值」来数命中：`combo_hit_scale` 的**真值就是 1.0**，
    #: 与「没有这条」的默认值相同 ⇒ 按值判会永远数成 0（那是尺子的毛病）。
    combo_seen = [0, 0.0]
    #: 「强击瓶专家」的行使计数（`count` 非 0、`scale` 非 1.0）。
    pa_hits = {"power_attack_count": 0, "power_attack_scale": 0}
    #: 特性的行使计数（三项各自非零次数）。「没有这条」都是 0，所以非零即命中。
    tr_hits = {"splash_radius": 0, "splash_scale": 0, "splash_damage_scale": 0,
               "highland_splash_scale": 0, "highland_splash_sluggish": 0,
               "hp_drain_per_sec": 0}
    for cfg, g in zip(configs, got):
        py = calc.stats(cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
                        trust=cfg["trust"], potential=cfg["potential"],
                        module=cfg.get("module") or None,
                        module_level=cfg.get("module_level") or 0)
        compared += 1
        out = []
        for part in ("base", "trust_bonus", "potential_bonus", "total"):
            a = norm(g.get(part) or {})
            b = norm(getattr(py, part, None) or {})
            if a != b:
                for k in sorted(set(a) | set(b)):
                    if a.get(k) != b.get(k):
                        out.append("%s.%s：Go=%r Python=%r"
                                   % (part, k, a.get(k), b.get(k)))
        #: 攻速加成那一支（天赋常驻/高台条件 ＋ 模组特性改写/未阻挡条件）。
        #: 模组那一项**只有在这次折算带了模组时**才可能非零。
        aspd = attack_speed_bonus(
            calc, cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
            potential=cfg["potential"],
            module=cfg.get("module") or None,
            module_level=cfg.get("module_level") or 0)
        for gk, pk in (("aspd_flat", "flat"), ("aspd_when_free", "when_free"),
                       ("aspd_high_ground", "when_high_ground")):
            a, b = norm(g.get(gk)), norm(getattr(aspd, pk, 0.0))
            if b:
                aspd_hits[gk] += 1
            if a != b:
                out.append("%s：Go=%r Python=%r" % (gk, a, b))
        #: 普攻连击（隐藏天赋的键组合）。Python 侧 `verify.py:342-344` 的三行
        #: 是「没有这条 1 / 1.0 / 1.0」，Go 侧同口径。
        combo = read_combo_attack(calc.character(cfg["char_id"]))
        if combo is not None:
            combo_seen[0] += 1
            combo_seen[1] = combo.hit_scale
        py_combo = {"combo_hits": combo.hits if combo else 1,
                    "combo_hit_scale": combo.hit_scale if combo else 1.0,
                    "combo_damage_scale": combo.damage_scale if combo else 1.0}
        for k, b in py_combo.items():
            if b != 1 and b != 1.0:
                combo_hits[k] += 1
            a = norm(g.get(k))
            if a != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, a, b))
        #: 「强击瓶专家」。★ `scale` 的「没有这条」是 **1.0**，`count` 是 0。
        pa = find_power_attack(tbook.for_operator(
            cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
            potential=cfg["potential"]))
        py_pa = {"power_attack_count": pa.count if pa else 0,
                 "power_attack_scale": pa.scale if pa else 1.0}
        for k, b in py_pa.items():
            if (k == "power_attack_count" and b) or (k == "power_attack_scale" and b != 1.0):
                pa_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, norm(g.get(k)), b))
        #: 特性那两支：溅射（几何 ＋ 天赋「汹涌怒火」叠三项）与生命流失速率。
        #: ★ 有天赋叠层时 `damage_scale` 的「没有这条」是 **1.0**（它是乘数），
        #: 两个 highland 是 0.0——不能一律按 0 判。
        ch = calc.character(cfg["char_id"])
        sp = apply_splash_talent(
            read_trait_splash(ch),
            tbook.for_operator(cfg["char_id"], elite=cfg["elite"],
                               level=cfg["level"], potential=cfg["potential"]))
        py_tr = {"splash_radius": sp.radius if sp else 0.0,
                 "splash_scale": sp.scale if sp else 0.0,
                 "splash_damage_scale": sp.damage_scale if sp else 1.0,
                 "highland_splash_scale": sp.highland_scale if sp else 0.0,
                 "highland_splash_sluggish": sp.highland_sluggish if sp else 0.0,
                 "hp_drain_per_sec": read_hp_drain(ch)}
        for k, b in py_tr.items():
            if (k == "splash_damage_scale" and b != 1.0) or (k != "splash_damage_scale" and b):
                tr_hits[k] += 1
            if norm(g.get(k)) != norm(b):
                out.append("%s：Go=%r Python=%r" % (k, norm(g.get(k)), b))
        if out:
            bad += 1
            print("✗ %s E%d L%d trust=%g pot=%d mod=%s —— %d 处不一致"
                  % (cfg["char_id"], cfg["elite"], cfg["level"],
                     cfg["trust"], cfg["potential"], cfg.get("module") or "-", len(out)))
            for line in out[:10]:
                print("    " + line)
    print()
    print("已比：base / trust_bonus / potential_bonus / module_bonus / total 五份逐字段，"
          "另加**攻速**三字段（aspd_flat / aspd_when_free / aspd_high_ground）；"
          "共 %d 次折算" % compared)
    print("覆盖面：名册 %d 位 × (底/顶/中 三档等级) × 信赖 %s × 潜能 %s，"
          "另加**模组** %d 次（%d 位带数值模组的干员）"
          % (len(roster), TRUSTS, POTENTIALS, mod_cfg, len(mod_ops)))
    print("★ 攻速三字段的**行使计数**（Python 侧非零次数／共 %d 次折算）：" % compared)
    for k, n in aspd_hits.items():
        flag = "" if n else "   ← 零信息量的绿：这一档本轮没被行使到"
        print("    %-18s %d%s" % (k, n, flag))
    print("★ 特性三字段行使计数（非零／共 %d 次）：" % compared)
    for k, n in tr_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-18s %d%s" % (k, n, flag))
    print()
    print("★「强击瓶专家」行使计数（count 非 0 / scale 非 1.0）：")
    for k, n in pa_hits.items():
        flag = "" if n else "   ← 这一档本轮没被行使到"
        print("    %-20s %d%s" % (k, n, flag))
    print()
    print("★ 连击三字段的行使计数（**非 1** 的次数；这三条的「没有这条」就是 1）：")
    for k, n in combo_hits.items():
        flag = "" if n else "   ← 该字段的值与默认值相同（见下）"
        print("    %-18s %d%s" % (k, n, flag))
    print("    连击天赋命中 %d 次，其 hit_scale 实测 = %g" % (combo_seen[0], combo_seen[1]))
    print("    ⚠ hit_scale 的**真值就是 1.0**，与默认值无法按值区分 ⇒ 上面那一行 0")
    print("      是尺子的口径所限，不是「没被走到」；命中次数看这两行。")
    print()
    if mod_ops:
        print("    模组清单（取每位的第一个带数值模组，全等级扫）：")
        for line in mod_ops:
            print("        " + line)
    else:
        print("★ 名册里**没有**带数值模组的干员 —— 模组那一支这一轮没被行走到")
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗（注入了改动却没红，判据没有分辨力）")
        return 1
    print("结论：%d / %d 次折算逐字段一致" % (compared - bad, compared))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
