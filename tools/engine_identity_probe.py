#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**引擎身份探针**：一串判决到底是谁算的——报引擎名、实际加载的模块、以及**消费者计数器**。

## 为什么需要它

2026-09-19 那件事的形状是"**标签**可疑，不是数字可疑"：台账的「旧读法 vs 原版 Python」一栏写着
`83杀/1漏/814.0333s/591046.1`，而 19:08 那枚老 Go 二进制测出的**逐位相同**——
看上去像"把 Go 的读数贴成了 Python 的标签"（本项目有过同型事故：引擎切 Go 之后裸 `Verifier()`
其实跑 Go 却照打 `[python]` 前缀）。**数字对不上只是难查，标签错是更坏的一类。**

而"应该是 Python"这句话是不算证据的。本工具给的是三样硬证据：
  ① **声明的引擎名**（`v.engine`）；
  ② **实际加载的模块文件路径**（`inspect.getsourcefile`）；
  ③ **消费者计数器**：Go 客户端被调用几次、原版 Python 入口被调用几次——
     计数为 0 的那一侧就是**没跑**，不管它叫什么名字。

另有一条已知的**静默退回**必须一并报出来（`ak_tactic/simgo/verifier.py:95`）：
规格里有 `unsupported` 字段时，**走 Go 的那条路会直接跑原版 Python** 并 `go_fallbacks += 1`，
判决里附一句「本判决来自原版 Python」。⇒ 只报 `go_fallbacks` 不够，**计数器才是主证**。

用法:
    python tools\\engine_identity_probe.py --plan fixtures/hsex8_max.json
    python tools\\engine_identity_probe.py --plan fixtures/hsex8_max.json --exe <另一个二进制>
"""
from __future__ import annotations

import argparse
import inspect
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.verify import Verifier                          # noqa: E402
import ak_tactic.simgo.client as C                             # noqa: E402
import golden_go as G                                          # noqa: E402
from engine_pin import EngineBuildError, ensure_pinned         # noqa: E402

GO_CALLS = {"n": 0}
PY_CALLS = {"n": 0}
_orig_sim = C.Simgo.sim


def _counted_sim(self, spec, *a, **kw):
    GO_CALLS["n"] += 1
    return _orig_sim(self, spec, *a, **kw)


C.Simgo.sim = _counted_sim
PY_ENTRY = "（找不到原版入口）"
try:
    from ak_tactic.battle.sim import BattleSimulator as _BS
    _orig_run = _BS.run

    def _counted_run(self, *a, **kw):
        PY_CALLS["n"] += 1
        return _orig_run(self, *a, **kw)

    _BS.run = _counted_run
    PY_ENTRY = f"{_BS.__module__}.BattleSimulator.run @ {inspect.getsourcefile(_BS)}"
except Exception as e:                                         # noqa: BLE001
    PY_ENTRY = f"（找不到原版入口：{type(e).__name__}: {e}）"


def one(tag: str, engine: str, plan: Plan, roster, exe: Path | None) -> dict:
    GO_CALLS["n"] = PY_CALLS["n"] = 0
    if exe is not None:
        os.environ["RIOS_SIM_BIN"] = str(exe)
    else:
        os.environ.pop("RIOS_SIM_BIN", None)
        try:
            ensure_pinned(verbose=False)
        except EngineBuildError as e:
            print(f"\n--- {tag} ---\n  ⛔ 自建自钉失败：{e}")
            return {"tag": tag, "error": str(e)}
    used = os.environ.get("RIOS_SIM_BIN")
    t0 = time.perf_counter()
    v = Verifier(engine=engine)
    r = v.run(plan, roster=roster)
    dt = time.perf_counter() - t0
    diag = [d for d in (getattr(r, "diagnosis", None) or []) if "Python" in d or "Go" in d]
    out = {"tag": tag, "engine": getattr(v, "engine", None), "exe": used,
           "kills": r.kills, "leaks": r.leaks, "elapsed": round(float(r.elapsed), 4),
           "damage": round(float(r.damage), 1),
           "go_calls": GO_CALLS["n"], "py_calls": PY_CALLS["n"],
           "go_runs": getattr(v, "go_runs", None),
           "go_fallbacks": getattr(v, "go_fallbacks", None),
           "seconds": round(dt, 1), "diagnosis": diag}
    print(f"\n--- {tag} ---")
    print(f"  声明的引擎 v.engine={out['engine']!r}　实际用的 exe={used}")
    print(f"  判决：{out['kills']}杀 {out['leaks']}漏 {out['elapsed']}s {out['damage']}"
          f"　（{out['seconds']}s）")
    #: 主证：哪一侧的计数器是 0，那一侧就**没跑**——与它叫什么名字无关
    who = ("原版 Python" if out["py_calls"] and not out["go_calls"]
           else "Go（rios-sim 可执行文件）" if out["go_calls"] and not out["py_calls"]
           else "**两边都跑了**" if out["go_calls"] and out["py_calls"] else "**两边都没跑**")
    print(f"  计数器：Go 被调用 {out['go_calls']} 次 / 原版 Python 被调用 {out['py_calls']} 次"
          f"　⇒ **这串数是 {who} 算的**")
    print(f"  go_runs={out['go_runs']}　go_fallbacks={out['go_fallbacks']}"
          + ("　⚠ **静默退回**：这串数来自原版 Python" if (out["go_fallbacks"] or 0) > 0 else ""))
    if diag:
        print(f"  判决附注：{diag[0][:110]}")
    return out


def main() -> int:
    ap = argparse.ArgumentParser(prog="engine_identity_probe.py")
    ap.add_argument("--plan", required=True, help="计划 JSON（如 fixtures/hsex8_max.json）")
    ap.add_argument("--exe", default="", help="另一个二进制（可选；会给它单独跑一次）")
    ap.add_argument("--json", default="", help="把三方读数写到这个文件")
    args = ap.parse_args()

    plan_path = Path(args.plan)
    if not plan_path.is_absolute():
        plan_path = ROOT / plan_path
    plan = Plan.from_dict(json.loads(plan_path.read_text(encoding="utf-8-sig")))
    roster_file = G._find("roster_max_modelled")
    roster = Roster.from_json(roster_file)

    print("=== 身份：我实际加载的文件 ===")
    print(f"  原版 Python 入口：{PY_ENTRY}")
    print(f"  Go 客户端入口　：{C.Simgo.__module__}.Simgo.sim @ {inspect.getsourcefile(C.Simgo)}")
    print(f"  Verifier　　　　：{Verifier.__module__}.Verifier @ {inspect.getsourcefile(Verifier)}")
    print(f"  计划被夹具　　　：{plan_path.name}（{plan_path.stat().st_size}B）")
    print(f"  名册（输入身份）：{roster_file}")

    res = [one("A · 钉 engine='python'", "python", plan, roster, None)]
    if args.exe:
        res.append(one(f"B · engine='go' + 指定的另一枚（{Path(args.exe).name}）",
                       "go", plan, roster, Path(args.exe)))
    res.append(one("C · engine='go' + 当轮自建自钉", "go", plan, roster, None))

    print("\n=== 汇总 ===")
    for r in res:
        if "error" in r:
            continue
        print(f"  {r['tag'][:34]:<36} {r['kills']}杀 {r['leaks']}漏 {r['elapsed']}s "
              f"{r['damage']}　计数器=Go{r['go_calls']}/Py{r['py_calls']}"
              f"　fallbacks={r['go_fallbacks']}")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "plan": str(plan_path),
             "roster": str(roster_file), "runs": res}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"  落盘：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
