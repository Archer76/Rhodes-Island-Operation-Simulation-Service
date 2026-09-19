#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""⚠ **已废弃（2026-09-19）**：任意关卡 / 任意作业的 **Go ↔ 原版** 判决对拍（通用入口）。

## 为什么标注废弃

博士 2026-09-19 裁定把默认模拟器切到 Go 版，并弃用 Python 那份模拟器。对拍这条路的
**存在前提是"两台引擎并存、要互相对账"**；这个前提没有了，对拍就不再是验收手段。

* **不要再拿它的输出去做验收**。现在的验收手段是 `tools/check_battle.py`
  （自检套件，跟随默认引擎 = Go）。
* 本文件**保留而不删**：它是"切换前 17 份计划四项全归零"这条结论的**唯一可复现证据**，
  删掉之后那份账就只剩叙述、没有工具能重算。
* ⚠ 但要清楚它现在**能证明什么、不能证明什么**：`PyCapture` 仍然显式钉住
  `engine="python"`（下面有注释说明理由），而 `ak_tactic/battle/` 那份原版实现
  **没有被删除**——它是 Go 的排程器与规格源（`build_spec(sim)` 读的就是它）。
  所以这个工具**仍然跑得动、仍然是真的两台引擎对账**，只是**不再是交付门槛**。

---

（以下为废弃前的原文）任意关卡 / 任意作业的 **Go ↔ 原版** 判决对拍（通用入口）。

为什么需要它：`probe_snow_damage.py` 之类的水位工具都**写死在 `hsex8_max.json` 上**，
而"怀黍离全部关卡的 Go/Python 对拍"要求的是**换一份作业就能跑、换一个关卡就能跑**。
每换个关卡就复制一份脚本，筛选逻辑会各自漂移——那种漂移比 bug 更难查。

三道判据里这一条工具负责**第一道（一致）**，并把另外两道要看的量一起摆出来：
  * **一致**：杀 / 漏 / 用时 / 伤害 四项差
  * **能不能算数**：`spec.unsupported` 非空 ⇒ Go 当场拒跑退回原版，
    那次"一致"**不作数**（记忆 `ed34c994`）。所以这里把闸门状态摆在最前面。
  * **落位**：把规格里挂上的机制名与残余单位列出来，一眼看出这一局的作业
    到底踩到了哪些机制——"四数对上"不等于"机制被验过"。

用法:
    python tools\\parity_plan.py hsex8_max            # ak-tactic-head/out 里的夹具名
    python tools\\parity_plan.py ..\\out\\plan.json     # 或直接给路径
    python tools\\parity_plan.py hs8_b --deploys 3     # 只取前 3 手
    python tools\\parity_plan.py hs7 --roster roster_max_modelled
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.simgo import build_spec, find_binary            # noqa: E402
from ak_tactic.simgo.client import Simgo                       # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402
from ak_tactic.verify import Verifier                          # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def resolve(name: str) -> Path:
    p = Path(name)
    if p.exists():
        return p
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        for cand in (base / "out" / name, base / "out" / f"{name}.json"):
            if cand.exists():
                return cand
    raise SystemExit(f"找不到作业文件：{name}")


class PyCapture(Verifier):
    """跑原版并扣住 `sim` / `res`——判决之外还要读机制状态。

    ⚠ **必须显式钉住 `engine="python"`**。`Verifier` 的默认引擎已经切成 `"go"`
    （博士 2026-09-19 裁定），而这一类是**对拍基准**：它要的就是原版那一份。
    不钉住的话，默认值一改，`PyCapture` 会静默走到 Go 那条路上去——
    于是"对拍"变成"Go 与 Go 比"，两边永远一致，全绿，而且没人看得出来。
    """ 

    def __init__(self, *a, **kw):
        kw.setdefault("engine", "python")
        super().__init__(*a, **kw)
        self.sim = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.sim = sim
        res = sim.run(max_time=900.0)
        self.res = res
        return self._verdict(plan, stage, sim, res, deployed, title=title)


class GoCapture(GoVerifier):
    """不跑 Go 二进制，只把 `build_spec` 的结果扣下来。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.held = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.held = (sim, build_spec(SpecInputs.from_sim(sim), allow_devices=True))
        raise SystemExit(0)


def compare(plan_path, roster_path="roster_max_modelled", *, deploys=0,
            quiet=False) -> dict:
    """跑一台对拍，返回结构化结果（供批量驱动复用，不再拼字符串）。"""
    src = resolve(str(plan_path))
    raw = json.loads(src.read_text(encoding="utf-8"))
    if deploys:
        raw = dict(raw, deploys=raw["deploys"][:deploys])
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve(str(roster_path)))

    pv = PyCapture()
    v = pv.run(plan, roster=roster)
    py_dmg = float(getattr(v.result, "damage_dealt", 0.0) or 0.0)

    thief = GoCapture()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    if thief.held is None:
        return {"ok": False, "why": "拿不到规格", "plan": src.name,
                "stage": raw.get("stage")}

    sim2, spec = thief.held
    uns = list(spec.get("unsupported") or [])
    mechs = spec.get("mechanisms")
    with Simgo(find_binary()) as cli:
        got = cli.sim(spec)
    go_dmg = float(got.get("damage_dealt") or 0.0)

    d = (got["kills"] - v.kills, got["leaks"] - v.leaks,
         got["elapsed"] - v.elapsed, go_dmg - py_dmg)
    zero = (d[0] == 0 and d[1] == 0 and abs(d[2]) < 1e-6 and abs(d[3]) < 1e-6)
    out = {
        "ok": zero, "plan": src.name, "stage": raw.get("stage"),
        "unsupported": uns, "mechanisms": mechs, "fallback": got.get("fallback"),
        "py": (v.kills, v.leaks, v.elapsed, py_dmg),
        "go": (got["kills"], got["leaks"], got["elapsed"], go_dmg),
        "diff": d,
    }
    if not quiet:
        print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s  总伤害={py_dmg:,.1f}")
        if uns:
            print(f"[闸门]  ⛔ 非空 unsupported ×{len(uns)} —— Go 会拒跑退回原版，"
                  f"本次对拍**不作数**：")
            for u in uns:
                print(f"         · {u}")
        else:
            print("[闸门]  ✅ unsupported 为空（Go 会真跑）")
        print(f"[落位]  机制={mechs}  出怪表={len(spec.get('spawns') or [])} 条")
        if got.get("fallback"):
            print(f"[go]     ⚠ **回退了原版**：{got.get('fallback')}")
        print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s"
              f"  总伤害={go_dmg:,.1f}")
        for r in (got.get("verdict") or {}).get("remnants") or []:
            print(f"[残余]   {r[0]}  清不掉={r[1]}")
        print(f"[判决]   杀 {d[0]:+d}  漏 {d[1]:+d}  用时 {d[2]:+.6f}s  伤害 {d[3]:+,.1f}"
              f"   →  {'✅ 四项全归零' if zero else '❌ 有差'}")
    return out


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print(__doc__)
        return 2
    target = args[0]
    k = int(args[args.index("--deploys") + 1]) if "--deploys" in args else 0
    roster_name = (args[args.index("--roster") + 1]
                   if "--roster" in args else "roster_max_modelled")
    r = compare(target, roster_name, deploys=k)
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
