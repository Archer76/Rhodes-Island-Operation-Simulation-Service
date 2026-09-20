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
    from ak_tactic.operator import OperatorCalculator
    calc = OperatorCalculator()
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
    mod_ops = []
    for cfg, g in zip(configs, got):
        py = calc.stats(cfg["char_id"], elite=cfg["elite"], level=cfg["level"],
                        trust=cfg["trust"], potential=cfg["potential"])
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
        if out:
            bad += 1
            print("✗ %s E%d L%d trust=%g pot=%d —— %d 处不一致"
                  % (cfg["char_id"], cfg["elite"], cfg["level"],
                     cfg["trust"], cfg["potential"], len(out)))
            for line in out[:10]:
                print("    " + line)
    #: 具名缺口：名册里带模组的干员
    for e in roster:
        try:
            ms = [m for m in calc.modules(e["id"]) if m.get("has_stats")]
        except Exception:                                        # noqa: BLE001
            continue
        if ms:
            mod_ops.append("%s(%d 个)" % (e["name"], len(ms)))

    print()
    print("已比：base / trust_bonus / potential_bonus / total 四份逐字段；共 %d 次折算"
          % compared)
    print("覆盖面：名册 %d 位 × (底/顶/中 三档等级) × 信赖 %s × 潜能 %s"
          % (len(roster), TRUSTS, POTENTIALS))
    if mod_ops:
        print("★ 本轮**未接入**的：模组那一支（battle_equip_table.json 不在本机缓存）。"
              "名册里带数值模组的干员 %d 位：%s" % (len(mod_ops), "、".join(mod_ops[:8])))
    else:
        print("★ 模组那一支未接入；名册里**没有**带数值模组的干员 ⇒ 本次覆盖面不受它影响")
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
