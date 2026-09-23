#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：生命上限加成那一行（`_max_hp_after_bonus`）。

## 为什么单独验这一行

`simgo/skills.py:239-255` 的注释写明它**曾经整条没送**：规格里的 `max_hp`
只有开场那一个静态值，于是「开技能把生命上限翻倍」的干员在 Go 侧少了一半血
——HS-EX-8 第 3 手圣聆初雪承受 2058 就倒，原版要到 4116（正好一半），
整局因此短了 18 秒。

## 怎么验

它是一个**纯函数**（只读 `_base_max_hp` / `max_hp` / `effects.buffs` 三处），
所以可以用**网格输入**逐点比：期望值从 Python 的 `_max_hp_after_bonus` 直接取
（配一个只带这三个属性的替身对象），不自己重写口径。

★ 网格必须**覆盖三条边界**，否则这条判据很容易变成零信息量的绿：
  ① 基准 > 0 与 `基准 <= 0`（回落那一支）；
  ② `pct` 正 / 零 / 负；
  ③ 基准为 0 与为负**分开**——`<= 0` 与 `< 0` 是两条不同的路。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `_max_hp_after_bonus` —— **现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/生命上限.json`，
  **不 import `ak_tactic`**（`tools/freeze_baseline.py` 的拦截器物理封死）。
  冻结档下那个 import 一次都进不来，因为它住在下面 `py_max_hp()` 的函数体里，
  而该函数在冻结档**根本不会被调到**。

两种模式**必须给同一个结论**——这是「基线录对了」的证明，不是形式要求。

用法:
    python tools\\check_profile_go.py
    python tools\\check_profile_go.py --mutate
    python tools\\freeze_baseline.py --record 生命上限     # 录/重录基线
    python tools\\freeze_baseline.py --status              # 现算几套跑得通
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

BASES = [0.0, -1.0, 1.0, 1000.0, 4116.0]
CURS = [0.0, 500.0, 2058.0, 9999.0]
PCTS = [-0.5, 0.0, 0.5, 1.0, 2.0]


def py_max_hp(base: float, cur: float, pct: float) -> float:
    """期望值入口。★ `ak_tactic` 的 import **写在函数体里**：冻结档下本函数不会
    被调到，于是这个包一次都进不来（顶层 import 会让 `bind()` 当场报 rc=6）。"""
    from ak_tactic.simgo.skills import _max_hp_after_bonus
    op = types.SimpleNamespace(_base_max_hp=base, max_hp=cur)
    eff = types.SimpleNamespace(buffs={"max_hp": pct})
    return _max_hp_after_bonus(op, eff)


def go_maxhp(queries: list[dict]) -> list[float]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "maxhp", "spec": queries}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["maxhp"]


def main() -> int:
    G = GB.bind("生命上限", __file__)

    queries = [{"base": b, "cur": c, "pct": t}
               for b in BASES for c in CURS for t in PCTS]
    got = go_maxhp(queries)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0] = got[0] + 1.0

    bad = 0
    branch = {"基准>0": 0, "基准<=0回落": 0, "pct非零": 0}
    for q, g in zip(queries, got):
        #: ★ 期望值只能从这里来：默认档现调 Python，冻结档读冻的那份。
        want = G.expect(("maxhp", q["base"], q["cur"], q["pct"]),
                        lambda q=q: py_max_hp(q["base"], q["cur"], q["pct"]))
        if q["base"] > 0:
            branch["基准>0"] += 1
        else:
            branch["基准<=0回落"] += 1
        if q["pct"] != 0:
            branch["pct非零"] += 1
        if abs(g - want) > 1e-9:
            bad += 1
            if bad <= 8:
                print("✗ base=%g cur=%g pct=%g —— Go=%r Python=%r"
                      % (q["base"], q["cur"], q["pct"], g, want))
    print()
    print("已比：生命上限加成那一行；网格 %d 点（base %d × cur %d × pct %d）"
          % (len(queries), len(BASES), len(CURS), len(PCTS)))
    print("★ 行使计数（三条边界各走了多少点）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in branch.items()))
    print()
    #: ★ 把「这次是哪一档、吃了没有 Python」印在结论**旁边**：不印的话，
    #: 「绿」这一件事分不出它是默认档的绿还是冻结档的绿。
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    print("结论：%d / %d 个点逐点一致" % (len(queries) - bad, len(queries)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
