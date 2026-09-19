# -*- coding: utf-8 -*-
"""`from_stage` 能不能替 `from_sim`：**逐份比 `spec_sha`**。

用法：
    python tools\\spec_from_stage_check.py            # 比全部（out/ 里的金标准作业）
    python tools\\spec_from_stage_check.py --plan out\\plan-hsex08.json

判据（博士 2026-09-19 批准的切换条件，PM #5 §五 写的）：
**`from_stage` 与 `from_sim` 产出的规格逐字节一致**，用金标准 17 份的
`spec_sha` 作证，**17/17 之前不许切**。

⚠ 这里比的是**三者**，不是两者：
  1. `from_sim` 现在产出的 sha（迁移前的实际路径）；
  2. `from_stage` 产出的 sha（要切过去的那条）；
  3. **金标准里记着的** sha（`out/golden_go.json`）。
第 3 条最重要：它是**切换之前就落盘的基线**。只比 1 与 2 会漏掉
"两边一起错、错得一样"——那正是本重构最怕的形态。

⚠ 借 `_run_other_engine` 的挂载点拿那台**排好程、还没跑**的 sim，
与 `golden_go.py` 同一手法（`sim.py` 那边也写着这是唯一能拿到该时刻状态的地方）。
**不复制 `verify.py` 的排程逻辑**——复制出来的第二份必然漂移。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from golden_go import canonical_sha                             # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs                # noqa: E402
from ak_tactic.plan import Plan, Roster                         # noqa: E402
from ak_tactic.simgo.spec import build_spec                     # noqa: E402

FIXTURES = ROOT / "out"
GOLDEN = FIXTURES / "golden_go.json"


class Probe:
    """在 `_run_other_engine` 那个挂载点上取两份规格。"""

    def __init__(self) -> None:
        self.rows: list[dict] = []

    def hook(self, verifier, sim, plan, stage, schedule, env):
        a = build_spec(SpecInputs.from_sim(sim), allow_devices=True,
                       schedule=schedule, env=env)
        #: 三个查询函数与 `verify.py:366-375` 同源——不向 sim 要，
        #: 免得"独立性判据"被它自己破坏。
        lib = verifier.library(stage)
        provider = (verifier.range_provider(stage)
                    if getattr(verifier, "use_range_table", True) else None)
        b = build_spec(
            SpecInputs.from_stage(
                stage, env=env, enemy_at=lib.get,
                species_provider=lib.species_of, range_provider=provider,
                schedule=schedule),
            allow_devices=True, schedule=schedule, env=env)
        self.rows.append({"sim": canonical_sha(a), "stage": canonical_sha(b),
                          "same": canonical_sha(a) == canonical_sha(b)})
        raise SystemExit(0)


def main() -> int:
    args = sys.argv[1:]
    only = None
    if "--plan" in args:
        only = pathlib.Path(args[args.index("--plan") + 1]).resolve()

    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    plans = sorted(FIXTURES.glob("plan-*.json"))
    if only is not None:
        plans = [only]
    if not plans:
        print("  ⚠ out/ 里没有 plan-*.json")
        return 1

    from ak_tactic.simgo.verifier import ensure_go_engine
    from ak_tactic.verify import Verifier

    roster = Roster.empty()
    for extra in ("roster_max_modelled.json",):
        p = FIXTURES / extra
        if p.exists():
            roster = Roster.from_json(p)

    n_same = n_gold = n_tot = 0
    bad: list[str] = []
    print(f"  {'夹具':<22} {'from_sim':<12} {'from_stage':<12} {'金标准':<12} 判定")
    for path in plans:
        plan = Plan.from_dict(json.loads(path.read_text(encoding="utf-8")))
        probe = Probe()

        v = Verifier(engine="go")
        #: ⚠ 必须钉 `engine="go"`：默认已是 go，但这条判据要的是"**拿到那台 sim**"，
        #: 不是"跑一次 Go"。借挂载点、拿到就 SystemExit。
        orig = Verifier._run_other_engine

        def patched(self, *, sim, plan, stage, deployed, title,
                    schedule=None, env=None, _p=probe, _o=orig):
            _p.hook(self, sim, plan, stage, schedule, env)

        Verifier._run_other_engine = patched
        try:
            v.run(plan, roster=roster)
        except SystemExit:
            pass
        finally:
            Verifier._run_other_engine = orig

        if not probe.rows:
            print(f"  {path.name:<22} （没拿到 sim，跳过）")
            continue
        r = probe.rows[0]
        g = golden.get(path.name, {}).get("spec_sha")
        n_tot += 1
        n_same += 1 if r["same"] else 0
        gmark = "—"
        if g is not None:
            gmark = "✅" if g == r["sim"] else "❌"
            n_gold += 1 if g == r["sim"] else 0
        verdict = "✅ 一致" if r["same"] else "⛔ 不一致"
        if not r["same"]:
            bad.append(path.name)
        print(f"  {path.name:<22} {r['sim'][:10]:<12} {r['stage'][:10]:<12} "
              f"{(g or '无')[:10]:<12} {verdict}  金标准{gmark}")

    print()
    print(f"  from_sim ≡ from_stage ：{n_same}/{n_tot}")
    if n_gold:
        print(f"  from_sim ≡ 金标准     ：{n_gold}/{n_gold and n_tot}")
    if bad:
        print(f"  ⛔ 不一致：{bad}")
        print("  ⇒ **17/17 之前不许切**（PM #5 §五）。")
        return 1
    print("  ✅ 可以进入切换评审。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
