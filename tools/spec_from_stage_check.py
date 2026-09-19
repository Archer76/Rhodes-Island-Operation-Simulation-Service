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

    def __init__(self, *, sensitivity: bool = False, sabotage: str | None = None) -> None:
        self.rows: list[dict] = []
        self.sensitivity = sensitivity
        self.sabotage = sabotage
        self.sens: dict[str, int] = {}

    def hook(self, verifier, sim, plan, stage, schedule, env):
        a = build_spec(SpecInputs.from_sim(sim), allow_devices=True,
                       schedule=schedule, env=env)
        #: 三个查询函数与 `verify.py:366-375` 同源——不向 sim 要，
        #: 免得"独立性判据"被它自己破坏。
        lib = verifier.library(stage)
        provider = (verifier.range_provider(stage)
                    if getattr(verifier, "use_range_table", True) else None)
        base = SpecInputs.from_stage(
            stage, env=env, enemy_at=lib.get,
            species_provider=lib.species_of, range_provider=provider,
            schedule=schedule)
        if self.sabotage:
            #: ⚠ **反向守卫**：故意让 `from_stage` 少算一样 ⇒ 两侧 sha **必须**不同。
            #: 看不到红，说明这条判据比的根本不是这两份规格（或比的是同一个对象）。
            import dataclasses as _dc
            base = _dc.replace(base, **{self.sabotage: _perturb(getattr(base, self.sabotage))})
        b = build_spec(base, allow_devices=True, schedule=schedule, env=env)
        sha_a, sha_b = canonical_sha(a), canonical_sha(b)
        self.rows.append({"sim": sha_a, "stage": sha_b, "same": sha_a == sha_b})

        if self.sensitivity:
            #: ⚠ **逐字段敏感性**：把一个字段改掉，规格的 sha **应当**变。
            #: 不变的字段只有两种解释——要么它根本没被规格读过（死字段 / 未接线），
            #: 要么 `build_spec` 是用别的东西算出来的。**两种都必须有人答**。
            #: 这是"判据红得起来吗"的最强形态：不是红一次，而是**逐项红**。
            self.sens = _sensitivity(base, schedule, env, sha_b)
        raise SystemExit(0)


def _perturb(value):
    """把一个字段改成"另一个合法值"。绝不喂不可能的输入（记忆 `6e20b44e`）。"""
    if isinstance(value, bool):
        return not value
    if isinstance(value, (int, float)):
        return value + 1.0 if value else 1.0
    if isinstance(value, str):
        return value + "_X" if value else "X"
    if isinstance(value, list):
        return list(value) + [object()]
    if value is None:
        return object()
    return None


def _sensitivity(base, schedule, env, base_sha: str) -> dict[str, int]:
    """逐字段改一个，看 sha 变不变。返回 {字段: 1=会变 / 0=不变}。"""
    import dataclasses
    out: dict[str, int] = {}
    for f in dataclasses.fields(base):
        if f.name == "stage":
            #: stage 是关卡对象，换掉它等于换一关——不是"同一个规格里的扰动"。
            #: 显式跳过并留名，别让它静默消失在表里。
            out[f.name] = -1
            continue
        try:
            tweaked = dataclasses.replace(base, **{f.name: _perturb(getattr(base, f.name))})
            got = canonical_sha(build_spec(tweaked, allow_devices=True,
                                           schedule=schedule, env=env))
        except Exception:                             # noqa: BLE001
            #: 改一个字段就炸 = 这个字段**确实被读**（而且读法不容忍这个值）。
            out[f.name] = 2
            continue
        out[f.name] = 1 if got != base_sha else 0
    return out


def main() -> int:
    args = sys.argv[1:]
    only = None
    if "--plan" in args:
        only = pathlib.Path(args[args.index("--plan") + 1]).resolve()

    golden = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    plans = sorted(FIXTURES.glob("plan-*.json"))
    if only is not None:
        plans = [only]
    #: (c) 逐字段敏感性：只跑一份就够了（23 个字段 × 每份 = 太贵），
    #: 默认挑**最小的那份**——字段敏感性是规格的性质，不是某一关的性质。
    if "--sensitivity" in args and only is None:
        plans = [min(plans, key=lambda p: p.stat().st_size)] if plans else []
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
    sens: dict[str, int] = {}
    want_sens = "--sensitivity" in args
    sabotage = None
    if "--negative-control" in args:
        sabotage = args[args.index("--negative-control") + 1]
    print(f"  {'夹具':<22} {'from_sim':<12} {'from_stage':<12} {'金标准':<12} 判定")
    for path in plans:
        plan = Plan.from_dict(json.loads(path.read_text(encoding="utf-8")))
        probe = Probe(sensitivity=want_sens, sabotage=sabotage)

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
        if probe.sens:
            sens = probe.sens

    print()
    print(f"  from_sim ≡ from_stage ：{n_same}/{n_tot}")
    if n_gold:
        print(f"  from_sim ≡ 金标准     ：{n_gold}/{n_gold and n_tot}")

    if sens:
        #: (c) 逐字段敏感性表。**红得起来吗**的最强形态：不是红一次，而是逐项红。
        #: ⚠ 不变（0）的字段有两种解释，**都必须有人答**：
        #:   ① 它根本没被规格读过（死字段 / 未接线）——如 `goal_cells`（已知死字段）；
        #:   ② `build_spec` 用别的东西算出了同一个结果（例：显式 `schedule` 在场时
        #:      五个排程列表是**兜底**，`spec.py:141` 优先用 `schedule`）。
        #: ⇒ 这张表只报事实，**不下"字段没用"的结论**。
        print()
        print("  逐字段敏感性（改这一个字段，`spec_sha` 变不变）：")
        #: ⚠⚠ **这张表是与夹具相关的**：实测同一套代码下，`snow_freeze` 在
        #: `plan-hstr02`（无敌人）上判"不变"、在 `hsex8_max`（72 出怪）上判"会变"；
        #: `goal_cells` 更是从"不变"变成"抛异常"。⇒ 单跑一份**不能**得出"这项没用"。
        print(f"     ⚠ 本表基于 {len(plans)} 份夹具（{plans[0].name}）——"
              "**换一份夹具结论会变**，")
        print("       所以'不变'只能读作'**在这份夹具上**没被读到'，不能读成'没用'。")
        hot = sorted(k for k, v in sens.items() if v == 1)
        warm = sorted(k for k, v in sens.items() if v == 2)
        cold = sorted(k for k, v in sens.items() if v == 0)
        skip = sorted(k for k, v in sens.items() if v == -1)
        print(f"    会变（=真被读）{len(hot):>2} 项：{hot}")
        if warm:
            print(f"    改了就抛异常（=被读且不容忍）{len(warm)} 项：{warm}")
        if cold:
            print(f"    ⚠ 不变 {len(cold)} 项：{cold}")
            print("       （不变 ≠ 没用：也可能是显式排程在场时它只是兜底，见 `spec.py:141`。）")
        if skip:
            print(f"    跳过 {len(skip)} 项：{skip}（`stage` 是关卡对象，换掉它等于换一关）")
        if not hot:
            print("  ⛔ **空洞的绿**：没有任何字段能让 sha 变化 ⇒ 这条判据根本没在比规格。")
            return 1

    control_ineffective = (sabotage is not None and not bad)
    if control_ineffective:
        #: ⚠ **陷阱**：`--negative-control <字段>` 挑了一个"改它 sha 也不变"的字段
        #: （本工具实测：23 项里有 16 项如此，例如 `fps`——静态 8 项走 `env` 不走 `inp`）。
        #: 那时两侧仍然一致，**一片绿**，但这个绿**什么都没证明**——
        #: 反向守卫没验成，只是挑错了输入。必须吼出来，不能静默放过。
        print()
        print(f"  ⛔ **反向守卫没生效**：sabotage `{sabotage}` 之后两侧**仍然一致** ⇒")
        print("     说明这个字段改了也不影响 `spec_sha`（见上面那张敏感性表的「不变」那一行）。")
        print("     ⇒ **这不是通过，是控制组挑错了字段。** 换一个「会变」的字段重跑，")
        print("       例如 `max_time` / `snow_fields` / `farmland`。")
        return 1

    if bad:
        print(f"  ⛔ 不一致：{bad}")
        if sabotage:
            print(f"  ✅ 反向守卫生效：故意改 `{sabotage}` ⇒ 判据**确实红了**"
                  f"（这正是一次成功的控制组）。")
            return 0            #: 控制组本来就**应该**红；红=成功。
        print("  ⇒ **17/17 之前不许切**（PM #5 §五）。")
        return 1
    print("  ✅ 可以进入切换评审。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
