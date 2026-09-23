#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：各自练度下的**部署费用**（`deploys[].cost`）。

## 对的是什么

期望值**不是**我另算一遍，而是**生产规格**里 `deploys[].cost`
（`build_spec` 的 `int(operator_of(d).deploy_cost)`）。做法是复用
`check_specgo_go.real_specs()`——那个只抄规格就跑的 `SpecCapture` 子类。

## 为什么这条要单独验

`cost` 其实早就在干员判据的四个整字典里被比过了（679 次折算）。但
`deploys` 要的是**按部署顺序、按各人自己的练度**取出来的那一个数——
顺序与练度来源是新的，而「取错人的费用」在判决上表现为「落地时刻整体偏移」，
不会报错。所以这里按 `char_id` 配对来比。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场跑**生产路径**抄出规格，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/部署费用.json`，
  **不 import `ak_tactic`**（`real_specs()` 与那两个 oracle 都在冻结档不会被调到）。

★ 这一套冻的**两半**都不敢省：

  · **期望值**＝生产规格的 `deploys[].cost`（按 `char_id` 配对），键带输入身份；
  · **问哪些问题**＝每一份夹具的 `cfgs`（那串查询要送的练度字段）——它是
    Python 侧产物（`stub._entry` 按名册解析出来的），不冻住的话 check 档
    根本不知道要问 Go 什么。它落在 `("query", "costof_inputs")` 那条记录里。

## ★ 本套是「乙类」：对象集是**活的**，所以键必须**自带输入身份**

取证范围是 `fixtures/` 里认得出是打法的那些文件，而别的会话会**往里加夹具**。
于是「现读 ≠ 冻结」有两种**完全不同**的因：

* **Go 漂移了** ⇒ 判据红（rc=1），要人去看实现；
* **夹具集/内容/名册变了** ⇒ 读数**不可用**（rc=6，印「输入批次对账」），该重录。

⇒ 键 `("costof", 夹具名, 夹具字节 sha16, 名册字节 sha16)`，并先做
`G.coverage("costof", …)` 对账；只比两边都有的，未覆盖的**不猜**。

用法:
    python tools\\check_costof_go.py
    python tools\\check_costof_go.py --mutate
    python tools\\freeze_baseline.py --record 部署费用
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
sys.path.insert(0, str(ROOT / "tools"))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = ROOT / "fixtures" / "roster_max_modelled.json"

_BATCH = None


def go_costof(cfgs: list[dict]) -> list[int]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "costof", "spec": cfgs}) + "\n"
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
    return resp["cost_of"]


def scan_cost_fixtures() -> list[list]:
    """本套取证范围的**输入身份**：文件名 ＋ 文件字节 sha16。

    ★ **数据侧**取数（只读 json 与文件字节，**不 import `ak_tactic`**）⇒ 冻结档也跑得动。
    ★ 子集口径与 `real_specs()` 同源：字典且带 `deploys`/`deploy`；编码也用
      `utf-8-sig`（原版那一侧就是它，用 utf-8 会把带 BOM 的夹具判成不存在，
      于是「活的那一批」永远少一个 ⇒ 变成永久假红）。
    """
    out: list[list] = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append([f.name, GB.file_sha16(f)])
    return out


def live_batch() -> list[list]:
    """离冻档专用：走**生产路径**，把每一份夹具的输入（cfgs）与期望值（deps）抄出来。

    返回 `[夹具名, 夹具 sha16, 名册 sha16, cfgs, deps]`，其中
    `deps = [[char_id, cost], …]` 按生产规格的次序（`deploys[]` 的顺序）。
    ★ `ak_tactic` 的 import 全写在函数体里：冻结档下本函数**不会被调到**。
    """
    from check_specgo_go import real_specs
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier

    class Stub:
        _by_name = Verifier._by_name
        _entry = Verifier._entry

        def __init__(self, calc):
            self.calc = calc

    stub = Stub(OperatorCalculator())
    roster = Roster.from_json(ROSTER_FIX)
    rsha = GB.file_sha16(ROSTER_FIX)
    out: list[list] = []
    for name, spec, err, _lv in real_specs():
        cfgs: list[dict] = []
        deps: list[list] = []
        if spec is not None:
            plan = Plan.from_dict(json.loads(
                (FIXDIR / name).read_text(encoding="utf-8-sig")))
            for d in plan.deploys:
                e = stub._entry(d, roster)
                cfgs.append({"char_id": e["char_id"], "elite": e["elite"],
                             "level": e["level"], "trust": e.get("trust") or 0,
                             "potential": e.get("potential", 1),
                             "module": e.get("module") or "",
                             "module_level": e.get("module_level") or 0})
            for dep in spec.get("deploys") or []:
                deps.append([str(dep.get("char_id")), dep.get("cost", 0)])
        out.append([name, GB.file_sha16(FIXDIR / name), rsha, cfgs, deps])
    return out


def _batch() -> list[list]:
    """生产路径那一批，全表只算一次（冻结档下**根本不会算**）。"""
    global _BATCH
    if _BATCH is None:
        _BATCH = live_batch()
    return _BATCH


def _deps_of(name: str) -> list:
    for b in _batch():
        if b[0] == name:
            return b[4]
    raise SystemExit("★ 生产路径那一批里没有这份夹具：%s" % name)


def main() -> int:
    G = GB.bind("部署费用", __file__)

    print("Go 侧仪器：%s" % GO_BIN)
    if G.mode == GB.CHECK:
        print("Python 侧权威：**生产规格**的 deploys[].cost"
              "（冻结档不 import：读的是 fixtures/golden/部署费用.json）")
    else:
        print("Python 侧权威：**生产规格**的 deploys[].cost（经 SpecCapture 抄出）")
    print()

    #: 对账用的活对象集：**数据侧**扫出来的那批夹具（带文件身份与名册身份）。
    live = [[n, sha, GB.file_sha16(ROSTER_FIX)]
            for n, sha in scan_cost_fixtures()]
    cov = G.coverage("costof", live)
    #: ★ 查询集（那串 cfgs）也冻住：它是 Python 侧产物，决定了 check 档要问 Go 什么。
    batch = G.expect(("query", "costof_inputs"),
                     lambda: [[b[0], b[1], b[2], b[3]] for b in _batch()])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov.ok:
        #: 只比两边都有的。**未覆盖的不猜**——猜就是自己写一份期望值。
        covered = {tuple(x) for x in cov.covered}
        to_cmp = [b for b in batch if tuple(b[:3]) in covered]

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    seen: dict[str, int] = {}
    for name, fix_sha, rsha, cfgs in to_cmp:
        if not cfgs:
            continue
        got = go_costof(cfgs)
        compared += 1
        if mutate and compared == 1 and got:
            got[0] = got[0] + 1
        want = {}
        for c, g in zip(cfgs, got):
            want[c["char_id"]] = g
        #: ★ 期望值只能从这里来：默认档现跑生产路径，冻结档读冻的那份。
        deps = G.expect(("costof", name, fix_sha, rsha),
                        lambda name=name: _deps_of(name))
        #: 按 char_id 与生产规格配对——同一份计划里干员不重复（`validate` 保证）。
        for cid, cost in deps:
            if cid not in want:
                bad += 1
                print("✗ 夹具 %s：生产规格里的 %s 在计划里找不到" % (name, cid))
                continue
            if want[cid] != int(cost):
                bad += 1
                print("✗ 夹具 %s %s：Go=%r 生产规格=%r"
                      % (name, cid, want[cid], cost))
            else:
                seen["部署费用逐人一致"] = seen.get("部署费用逐人一致", 0) + 1
        seen["夹具"] = seen.get("夹具", 0) + 1

    if G.mode == GB.CHECK and not cov.ok:
        print()
        print(cov.report("costof", len(live)))
    print("已比：部署费用；%d 份夹具 × 生产规格的 deploys[].cost" % compared)
    print("★ 行使计数：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
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
    if not seen.get("部署费用逐人一致"):
        print("结论：一个人都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    print("结论：%d 份夹具、%d 人次的部署费用与生产规格一致"
          % (compared, seen["部署费用逐人一致"]))
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
