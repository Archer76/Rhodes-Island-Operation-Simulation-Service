#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：开技能的攻击间隔那一行（`SkillEffects.attack_interval`）。

## 为什么单独验这一行

`simgo/skills.py:_profile`（`:202-256`）造两份快照——不开启那套与开启那套。
其中「间隔」这一项，两侧**是同一条公式**：

    无技能帧  `simgo/spec.py:695-696`：op.attack_interval × 100 / max(20, 总攻速)
    开技能帧  `operator/skill.py:1379-1400`：同一式，再加 buffs 的两个修正

所以两套快照的间隔只差那一对 buff。这里就把它当**一个纯函数**逐点比，
`base_interval` / `base_attack_speed` / 两个 buff 全部走入参。

## 为什么不用起 sim 当 oracle

`SkillEffects` 是全字段带默认值的 dataclass，`SkillEffects(buffs={...})` 这个
裸对象就能调 `attack_interval`——不需要 `sim`、不需要干员、不需要关卡。
期望值直接取它的返回值，不自己重写口径。

## 怎么验

★ 网格必须**覆盖三条边界**，否则这条判据很容易变成零信息量的绿：

  ① 攻速下限 `ASPD_MIN=20` 生效（`base_spd + spd_buff <= 20`）；
  ② 间隔下限 `MIN_INTERVAL=0.05` 生效（折算后低于它才会夹）；
  ③ 加算秒数 `interval_buff` 为负——它**不夹零**，负值要照样算进去；
  ④ 无技能帧那一侧是 iv_buff=0 且 spd_buff=0 的特例，网格里必须有这一点。

三条边界**各自都记行使计数**，任何一条为 0 就判红：不是「比过 600 点」，
而是「这 600 点真的走到过那三条路」。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `SkillEffects.attack_interval`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/攻击间隔.json`，**不 import `ak_tactic`**。

★ 这一套冻的**两半**：逐点期望值，以及 `ASPD_MIN` / `MIN_INTERVAL` 两个
**行使计数的口径常量**（下面的行使计数要用它们判「这一支有没有走到」——
常量不冻，check 档连计数都算不出来）。

⚠ 这两个常量**不进比法**（比法是 `abs(g - want) > 1e-9`），所以**改它们不会翻转判决**
——实测：`--control` 的 P1 改坏 `("consts","interval")` 后 rc 仍为 0。
因此控制组的敏感性探针只拿**期望值**做（见 `freeze_baseline.py --control`）；
常量冻住的目的只是让行使计数的口径可复现。

★ **第三态**：本文件开头那条「`spec.ASPD_MIN` 与 `skill.ASPD_MIN` 必须相等」是
**Python 侧自身的自检**。冻结档下两侧同源、恒等 ⇒ **不适用于冻结**，会显式印出来，
不当作通过（把它读成绿就是又造了一条「预先被决定的绿」）。

用法:
    python tools\\check_interval_go.py
    python tools\\check_interval_go.py --mutate
    python tools\\freeze_baseline.py --record 攻击间隔
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

#: 0.2 那一档是为了撞上间隔下限（配高速攻速时折算值低于 0.05）。
BASE_IV = [0.2, 0.85, 1.0, 1.3, 2.3, 3.5]
#: 7.0 / 20.0 是为了撞上攻速下限（前者加负 buff 后仍是 7）。
BASE_SPD = [7.0, 20.0, 100.0, 107.0, 220.0]
IV_BUFF = [-0.1, 0.0, 0.25, 1.0]
SPD_BUFF = [-95.0, -30.0, 0.0, 30.0, 500.0]


def py_interval_consts() -> dict:
    """判定参数（**判定时要用到的 Python 常量**，必须与期望值一起冻住）。

    ⚠ `MIN_INTERVAL` 这个名字在仓里有**两处不同含义**：`prts/client.py:31`
    的 1.2 是抓站限速，跟攻击间隔无关。这里取与 spec 构造同一处的那 0.05。
    """
    from ak_tactic.operator.skill import ASPD_MIN
    from ak_tactic.simgo.spec import ASPD_MIN as SPEC_ASPD_MIN
    from ak_tactic.simgo.spec import MIN_INTERVAL
    return {"ASPD_MIN": ASPD_MIN, "SPEC_ASPD_MIN": SPEC_ASPD_MIN,
            "MIN_INTERVAL": MIN_INTERVAL}


def py_interval_want(base_iv: float, base_spd: float,
                     iv_buff: float, spd_buff: float) -> float:
    """期望值入口。★ import 写在函数体里：冻结档下本函数不会被调到。"""
    from ak_tactic.operator.skill import SkillEffects
    eff = SkillEffects(buffs={"attack_interval": iv_buff, "attack_speed": spd_buff})
    return eff.attack_interval(base_iv, base_spd)


def go_interval(queries: list[dict]) -> list[float]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "interval", "spec": queries}) + "\n"
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
    return resp["interval"]


def main() -> int:
    G = GB.bind("攻击间隔", __file__)

    C = G.expect(("consts", "interval"), py_interval_consts)
    ASPD_MIN = C["ASPD_MIN"]
    MIN_INTERVAL = C["MIN_INTERVAL"]
    if G.mode == GB.CHECK:
        #: ★ **第三态**（不适用于冻结）：这一条量的是「Python 两处常量一不一致」，
        #: 冻结档下两侧都来自同一份记录 ⇒ 恒等、不可能失败。**不许静默当作通过**。
        print("⚠ 不适用于冻结：`spec.ASPD_MIN` 与 `skill.ASPD_MIN` 的一致性自检"
              "（两侧现在同源，恒真、零信息量）——本档不拿它当判据")
    elif C["SPEC_ASPD_MIN"] != ASPD_MIN:
        raise SystemExit("攻速下限两处不同值：spec=%g skill=%g"
                         % (C["SPEC_ASPD_MIN"], ASPD_MIN))

    queries = [{"base_iv": bi, "base_spd": bs, "iv_buff": ib, "spd_buff": sb}
               for bi in BASE_IV for bs in BASE_SPD
               for ib in IV_BUFF for sb in SPD_BUFF]
    got = go_interval(queries)
    mutate = "--mutate" in sys.argv
    if mutate and got:
        got[0] = got[0] + 1.0

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：SkillEffects.attack_interval"
          "（ASPD_MIN=%g、MIN_INTERVAL=%g%s）"
          % (ASPD_MIN, MIN_INTERVAL,
             "，**这两个数来自冻结基线**" if G.mode == GB.CHECK else ""))
    print()

    bad = 0
    branch = {"攻速下限生效": 0, "间隔下限生效": 0, "加算秒数为负": 0, "无技能帧特例": 0}
    for q, g in zip(queries, got):
        #: ★ 期望值只能从这里来：默认档现调 Python，冻结档读冻的那份。
        want = G.expect(("interval", q["base_iv"], q["base_spd"],
                         q["iv_buff"], q["spd_buff"]),
                        lambda q=q: py_interval_want(
                            q["base_iv"], q["base_spd"], q["iv_buff"], q["spd_buff"]))
        spd = max(ASPD_MIN, q["base_spd"] + q["spd_buff"])
        if q["base_spd"] + q["spd_buff"] <= ASPD_MIN:
            branch["攻速下限生效"] += 1
        if (q["base_iv"] + q["iv_buff"]) * 100.0 / spd < MIN_INTERVAL:
            branch["间隔下限生效"] += 1
        if q["iv_buff"] < 0:
            branch["加算秒数为负"] += 1
        if q["iv_buff"] == 0.0 and q["spd_buff"] == 0.0:
            branch["无技能帧特例"] += 1
        if abs(g - want) > 1e-9:
            bad += 1
            if bad <= 8:
                print("✗ base_iv=%g base_spd=%g iv_buff=%g spd_buff=%g"
                      " —— Go=%r Python=%r"
                      % (q["base_iv"], q["base_spd"], q["iv_buff"],
                         q["spd_buff"], g, want))
    print()
    print("已比：开技能的攻击间隔那一行；网格 %d 点"
          "（base_iv %d × base_spd %d × iv_buff %d × spd_buff %d）"
          % (len(queries), len(BASE_IV), len(BASE_SPD),
             len(IV_BUFF), len(SPD_BUFF)))
    print("★ 行使计数（四条边界各走了多少点）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in branch.items()))
    unchecked = [k for k, v in branch.items() if v == 0]
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        # 网格丢了边界 ⇒ 这一片绿是零信息量的，不许当通过。
        print("结论：网格没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d / %d 个点逐点一致" % (len(queries) - bad, len(queries)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
