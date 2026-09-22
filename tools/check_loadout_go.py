#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：练度解析（名册与计划合起来之后的那一组面板入参）。

## 对的是什么

`ak_tactic/verify.py:548-569` 的 `Verifier._entry(d, roster)`，外加它的
`_by_name`（`:571-577`）。这是「名册／计划读进来了」到「有面板入参可用」之间的
那一步——也就是两份输入**第一次被真的用上**的地方。

## 为什么不用起 sim 当 oracle

`_entry` 只读 `roster` / `d` 两样，另一处是 `self._by_name`。所以拿一个只带
`calc` 的替身对象把**真实方法**当纯函数调即可，oracle 依旧是原版。

## 覆盖面

* `fixtures/` 下**全部 24 份打法夹具** × 真夹具名册，逐条部署对拍；
* 另加一组合成用例，逐条走 `_entry` 的各道口径。

## 原版里几处容易抄混的

* 基准**按名字**查名册（与名册的键口径一致），六项练度**打法里写了就覆盖**，
  判据是 `is not None`——所以 `elite: 0` 是一次**有效覆盖**，不是「没写」。
* 三条 `setdefault`（elite→0、level→1、potential→1）只在**键整个不存在**时
  生效；基准来自名册时那三个键一定在，所以它们只对「名册里没有这个人」的
  那条路有意义。
* `char_id` 缺失时按**名字**回数据里找，跳过 `TRAP`/`TOKEN`，取**行序上的
  第一个**。这一步是 Go 侧最容易做错的地方：用 map 迭代会随机挑到同名 id。
* `trust` **只有打法能给**（名册那一份结构里没有 trust 这一项）。

用法:
    python tools\\check_loadout_go.py
    python tools\\check_loadout_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = FIXDIR / "roster_max_modelled.json"

KEYS = ("char_id", "elite", "level", "potential", "trust", "module",
        "module_level")


def j(text: str) -> bytes:
    return text.encode("utf-8")


def plan_text(op: str, extra: str = "") -> bytes:
    return j('{"stage":"1-7","deploys":[{"operator":"%s","position":[1,1]%s}]}'
             % (op, extra))


def go_loadout(plan: Path, roster: Path | None) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    spec = {"plan": str(plan), "roster": str(roster) if roster else ""}
    req = json.dumps({"id": 1, "cmd": "loadout", "spec": spec}) + "\n"
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
        return False, resp.get("error") or ""
    return True, resp["loadout"]


def make_authority():
    """一个只带 `calc` 的替身 + 真实方法。"""
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.verify import Verifier

    class Stub:
        _by_name = Verifier._by_name
        _entry = Verifier._entry

        def __init__(self, calc):
            self.calc = calc

    return Stub(OperatorCalculator())


def main() -> int:
    import ak_tactic.verify as V
    from ak_tactic.plan import Plan, Roster

    stub = make_authority()
    calc = stub.calc
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：ak_tactic.verify 的 Verifier._entry/_by_name（%s）"
          % Path(V.__file__).name)
    print()

    mutate = "--mutate" in sys.argv
    seen: dict[str, int] = {}
    bad = 0
    compared = 0
    both_refused = 0

    def check(label: str, plan_path: Path, roster_path: Path | None):
        nonlocal bad, compared, both_refused
        ok, got = go_loadout(plan_path, roster_path)
        try:
            plan = Plan.load(plan_path)
            ros = Roster.from_json(roster_path) if roster_path else Roster.empty()
            wants = [stub._entry(d, ros) for d in plan.deploys]
            py_ok, py_err = True, ""
        except Exception as exc:                            # noqa: BLE001
            wants, py_ok = None, False
            py_err = "%s: %s" % (type(exc).__name__, exc)
        if not ok or not py_ok:
            if not ok and not py_ok:
                both_refused += 1
                return
            bad += 1
            print("✗ %s —— Go ok=%s（%s） Python ok=%s（%s）"
                  % (label, ok, got if not ok else "-",
                     py_ok, py_err if not py_ok else "-"))
            return
        compared += 1
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got[0]["level"] = 999
        if len(got) != len(wants):
            bad += 1
            print("✗ %s —— 条数 Go=%d Python=%d" % (label, len(got), len(wants)))
            return
        for i, (g, w) in enumerate(zip(got, wants)):
            for k in KEYS:
                if g.get(k) != w.get(k):
                    bad += 1
                    print("✗ %s 第 %d 条 %s：Go=%r Python=%r"
                          % (label, i, k, g.get(k), w.get(k)))

    #: ---- 全量夹具 × 真夹具名册 ----
    plans = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                   # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            plans.append(f)
    seen["全量夹具 × 真名册"] = len(plans)
    for f in plans:
        check("夹具 %s" % f.name, f, ROSTER_FIX)

    #: ---- 合成用例 ----
    ros = Roster.from_json(ROSTER_FIX)
    in_roster = ros.names()[0]
    #: 一个**在数据里、但不在名册里**的真干员名——用来走 `_by_name` 那条回退。
    chars = calc._load_chars()
    outside = None
    for cid, c in chars.items():
        nm = c.get("name")
        if nm and nm not in ros and c.get("profession") not in ("TRAP", "TOKEN"):
            outside = nm
            break
    if outside is None:
        raise SystemExit("找不到「在数据里但不在名册里」的干员名，合成用例造不出来")
    print("合成用例用的两个名字：名册里有的「%s」、只在数据里的「%s」"
          % (in_roster, outside))
    print()

    with tempfile.TemporaryDirectory() as td:
        tdp = Path(td)

        def case(label: str, blob: bytes, roster_path: Path | None, br: str):
            seen[br] = seen.get(br, 0) + 1
            case.n += 1
            p = tdp / ("c%d.json" % case.n)
            p.write_bytes(blob)
            check(label, p, roster_path)

        case.n = 0

        case("名册有人 / 打法不写", plan_text(in_roster), ROSTER_FIX,
             "基准来自名册")
        case("名册有人 / 打法覆盖 elite+level",
             plan_text(in_roster, ',"elite":1,"level":55'), ROSTER_FIX,
             "打法覆盖练度")
        case("名册有人 / 打法写 elite:0",
             plan_text(in_roster, ',"elite":0'), ROSTER_FIX,
             "elite:0 是有效覆盖")
        case("名册有人 / 打法覆盖 module",
             plan_text(in_roster, ',"module":"uniequip_001","module_level":3'),
             ROSTER_FIX, "打法覆盖模组")
        case("名册有人 / 打法把 module 覆盖成空串",
             plan_text(in_roster, ',"module":""'), ROSTER_FIX,
             "module 空串是有效覆盖")
        case("名册有人 / 打法写 trust", plan_text(in_roster, ',"trust":100'),
             ROSTER_FIX, "trust 只有打法能给")
        case("名册没人 / 打法写全 elite+level",
             plan_text(outside, ',"elite":2,"level":80'), ROSTER_FIX,
             "char_id 走 _by_name 回退")
        case("名册没人 / 打法写全且带 potential",
             plan_text(outside, ',"elite":0,"level":1,"potential":6'), ROSTER_FIX,
             "名册没人时 setdefault 生效")
        case("名册没人 / 名字数据里也找不到",
             plan_text("不存在的干员", ',"elite":1,"level":1'), ROSTER_FIX,
             "两边都找不到 → 报错")
        case("名册没人 / 打法只写 elite",
             plan_text(outside, ',"elite":2'), ROSTER_FIX,
             "练度没着落 → 报错")
        case("没有名册文件 / 打法写全",
             plan_text(outside, ',"elite":2,"level":80'), None,
             "无名册文件仍可解析")
        case("没有名册文件 / 打法不写",
             plan_text(in_roster), None, "无名册且打法没写 → 报错")

    print()
    print("已比：练度解析；全量夹具 %d 份（× 真名册）＋合成 %d 例，"
          "共 %d 例逐字段比、%d 例两边都拒"
          % (len(plans), len(seen) - 1, compared, both_refused))
    print("★ 行使计数（每道口径各走了几例）：")
    for b, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-24s %d" % (b, n))
    expect = ("基准来自名册", "打法覆盖练度", "elite:0 是有效覆盖", "打法覆盖模组",
              "module 空串是有效覆盖", "trust 只有打法能给",
              "char_id 走 _by_name 回退", "名册没人时 setdefault 生效",
              "两边都找不到 → 报错", "练度没着落 → 报错", "无名册文件仍可解析",
              "无名册且打法没写 → 报错", "全量夹具 × 真名册")
    unchecked = [b for b in expect if seen.get(b, 0) == 0]
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        print("结论：用例表没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d 例逐字段一致（另 %d 例两边都拒）" % (compared, both_refused))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
