"""取证：`species_provider` 到底有没有进规格。

⚠ 存在的理由：`--sensitivity` 说这一项"改了 sha 不变"。但**不变有两种**——
① 没被读；② 读了但没进规格。说"没被读"之前必须先证明破坏动作**到达了那一行**
（这是本会话自己立的纪律，正是在这条上抓出过 `fps` 那个假绿）。
本脚本用**带计数与哨兵返回值的 provider** 直接回答，而不是靠推断。
"""
import json
import pathlib
import sys

sys.path.insert(0, ".")
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.frontend.inputs import SpecInputs          # noqa: E402
from ak_tactic.plan import Plan, Roster                   # noqa: E402
from ak_tactic.simgo.spec import build_spec               # noqa: E402
from ak_tactic.verify import Verifier                     # noqa: E402
from tools.golden_go import canonical_sha                 # noqa: E402

MAP = pathlib.Path("out/hsex8_max.json")


def hook(self, *, sim, plan, stage, deployed, title, schedule=None, env=None):
    lib = self.library(stage)
    a = SpecInputs.from_stage(
        stage, env=env, enemy_at=lib.get,
        species_provider=lambda e: "SENTINEL", range_provider=None,
        schedule=schedule)
    spec = build_spec(a, allow_devices=True, schedule=schedule, env=env)
    blob = json.dumps(spec, ensure_ascii=False, default=str)
    print("  规格 JSON 里出现 SENTINEL ?", "SENTINEL" in blob)
    print("  规格 JSON 里出现 species 字样 ?", "species" in blob)
    en = spec.get("enemies") or spec.get("spawns") or []
    print("  顶层键数:", len(spec), " 敌人数:", len(en))
    if en:
        keys = sorted(en[0].keys())
        print("  首个敌人规格的键:", keys[:16])

    #: 第二问：`devices`。`spec.py:176` 是
    #:     `if getattr(inp, "devices", None) and not allow_devices:`
    #: ⇒ 它**只在 `unsupported_reasons` 里、且 `allow_devices=False` 时**才被读。
    #: 全程传 `True` 的话，那个分支根本不执行——所以"改它 sha 不变"**不是**它没被读。
    import dataclasses
    for allow in (True, False):
        r0 = build_spec(a, allow_devices=allow, schedule=schedule, env=env)
        tampered = dataclasses.replace(a, devices=list(a.devices or []) + [object()])
        r1 = build_spec(tampered, allow_devices=allow, schedule=schedule, env=env)
        same = canonical_sha(r0) == canonical_sha(r1)
        print(f"  allow_devices={str(allow):<5} 改 inp.devices ⇒ sha 相同 = {same}")
    raise SystemExit(0)


Verifier._run_other_engine = hook
p = Plan.from_dict(json.loads(MAP.read_text(encoding="utf-8")))
try:
    Verifier(engine="go").run(p, roster=Roster.empty())
except SystemExit:
    pass
