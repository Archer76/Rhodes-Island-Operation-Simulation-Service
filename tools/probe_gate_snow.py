# -*- coding: utf-8 -*-
"""只读取证：闸门漏报「积雪」——`build_spec` 取的是**开局此刻**的 sim。

`Verifier.run` 先把整条排程写进 `sim.deployments`（`sim.py:607` 只 append），
然后才调 `_run_other_engine`；而 `snow_fields` 是在**真正部署那一刻**
（`sim.py:3396-3406`）才创建的。于是：

  * `unsupported_reasons(sim)` 读到的 `sim.snow_fields` 恒为 []（只有预置场地才会非空）
  * 规格里根本没有积雪这一项 → Go 那边没有对应字段，也不会拒跑
  * 结论：**凡是「干员部署之后才出现」的机制，闸门都看不见它**

本脚本用实测把这条钉死，并证明「闸门一旦看见就会退回原版」。
全程只读：不动 ak_tactic/，只在本进程内临时替换函数引用。
（⚠ 要替换的是 `simgo.verifier` 里那个名字——`from . import build_spec`
拿的是函数对象，改 `simgo.spec.build_spec` 对它无效。）
"""
from __future__ import annotations

import copy
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import probe_windup_phase as P                          # noqa: E402
import ak_tactic.simgo.spec as sp                       # noqa: E402
import ak_tactic.simgo.verifier as gvmod                # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier         # noqa: E402

K = int(sys.argv[1]) if len(sys.argv) > 1 else 3
plan = P.load_plan(K)
roster = P.load_roster()

real_build = gvmod.build_spec
marks: dict[str, object] = {}


def build_probe(sim, **kw):                             # noqa: ANN001
    if "at_build" not in marks:
        marks["at_build"] = len(getattr(sim, "snow_fields", []) or [])
        marks["deploys_at_build"] = len(getattr(sim, "deployments", []) or [])
    return real_build(sim, **kw)


# ---- ① GoVerifier 实跑：闸门报什么、真跑还是回退、判决是什么 ----
gvmod.build_spec = build_probe
gv = GoVerifier()
try:
    v_go = gv.run(plan, roster=roster)
finally:
    gv.close()
    gvmod.build_spec = real_build

print(f"k={K}  engine=go（GoVerifier 实跑，非探针自建）")
print(f"  取规格那一刻：已排程部署 {marks.get('deploys_at_build')} 个，"
      f"sim.snow_fields = {marks.get('at_build')}")
print(f"  go_runs={gv.go_runs}  go_fallbacks={gv.go_fallbacks}")
print(f"  Go 判决：{v_go.kills}杀 {v_go.leaks}漏 {v_go.elapsed:.6f}s")
fallback_note = [d for d in v_go.diagnosis if "原版 Python" in d]
print(f"  闸门是否响过：{'响了（退回原版）' if fallback_note else '**没响——真走的 Go**'}")

# ---- ② 同一份排程走原版 ----
py = P.run_python(copy.deepcopy(plan), roster)[1]
print(f"  原版判决：{py.kills}杀 {py.leaks}漏 {py.elapsed:.6f}s")
same = (py.kills, py.leaks) == (v_go.kills, v_go.leaks)
print(f"  判决一致？{'是' if same else '**否**'}")

# ---- ③ 反证：人为让闸门看见「积雪」，必须退回原版 ----
def build_with_gate(sim, **kw):                          # noqa: ANN001
    d = real_build(sim, **kw)
    d["unsupported"] = list(d.get("unsupported") or []) + [
        "【取证】积雪 ×1（人为塞入，用来验证闸门会退回原版）"]
    return d


gvmod.build_spec = build_with_gate
gv2 = GoVerifier()
try:
    v2 = gv2.run(copy.deepcopy(plan), roster=roster)
finally:
    gv2.close()
    gvmod.build_spec = real_build

print(f"  反证（人为让闸门看见积雪）：go_runs={gv2.go_runs} "
      f"go_fallbacks={gv2.go_fallbacks}  判决={v2.kills}杀 {v2.leaks}漏 "
      f"{v2.elapsed:.6f}s")
back = (v2.kills, v2.leaks, round(v2.elapsed, 6)) == (
    py.kills, py.leaks, round(py.elapsed, 6))
print(f"     → 退回原版后与原版一致？{'是（闸门确实生效）' if back else '否'}")
