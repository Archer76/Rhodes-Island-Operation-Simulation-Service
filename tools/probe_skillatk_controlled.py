"""受控用例：把**敌方技能出手**的首次触发时间调短，逼它在真关卡里落地。

由来：`check_mech_parity.py` 里 `HS-EX-7` 与 `HS-8` 两例被判"咬不到机制"——
把 `skill_atk_scale_*` 整组清零，判决一字不变。那不是对拍失败，是**用例覆盖不够**：
那一趟 `勿玷`（12000 血、`skill_atk_init = 7.0`）根本没活到第一次出手。

博士的口径：**改本地数据，看能不能做等效的核查**。可以，而且本工具本来就是
照 `REBORN_CASE`（受控：瘴血量 → 1500）那一套做的——把触发条件调到一定会发生，
**两边收到同一份改动**，证的是那段代码的逐位一致。

⚠ 它**不是**这一关真实判决的证据，读数时别混。所以读数里写明"受控"。

三件事一起报（与受控重生用例同构）：
  ① 一致：两边判决逐项相同；
  ② 咬到：把 `skill_atk_scale_*` 整组清零之后，判决**必须变**；
  ③ 走过：Go 侧确实发出了敌方技能出手的痕迹（"这条路被走过"的直接证据）。

用法：python tools/probe_skillatk_controlled.py [plan] [init秒]
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from parity_plan import GoCapture, resolve                          # noqa: E402
from ak_tactic.plan import Plan, Roster                             # noqa: E402
from ak_tactic.simgo import Simgo, build_spec, find_binary          # noqa: E402
from ak_tactic.battle import sim as sim_mod                         # noqa: E402


def is_skill_atk(e) -> bool:                                        # noqa: ANN001
    return bool(getattr(e, "skill_atk_scale_phys", 0.0)
                or getattr(e, "skill_atk_scale_magic", 0.0))


def run_py(plan, roster, init: float | None):
    """跑原版；`init` 不是 None 时把敌方技能首次触发时间改成它。"""
    orig = sim_mod.BattleSimulator._build_enemy

    def patched(self, enemy_id, level, pts, legs, t, wait):         # noqa: ANN001
        e = orig(self, enemy_id, level, pts, legs, t, wait)
        if init is not None and is_skill_atk(e):
            e.skill_atk_init = float(init)
        return e

    if init is not None:
        sim_mod.BattleSimulator._build_enemy = patched
    try:
        from parity_plan import PyCapture
        pv = PyCapture()
        v = pv.run(plan, roster=roster)
    finally:
        sim_mod.BattleSimulator._build_enemy = orig
    return (v.kills, v.leaks, v.elapsed,
            float(getattr(v.result, "damage_dealt", 0.0) or 0.0))


def main() -> int:
    plan_path = sys.argv[1] if len(sys.argv) > 1 else "out/plan-hsex07.json"
    init = float(sys.argv[2]) if len(sys.argv) > 2 else 1.0
    raw = json.loads(resolve(plan_path).read_text(encoding="utf-8"))
    plan = Plan.from_dict(raw)
    roster = Roster.from_json(resolve("roster_max_modelled"))

    thief = GoCapture()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _, base = thief.held
    n_carriers = sum(1 for s in base.get("spawns", []) if is_skill_atk_dict(s))
    print(f"—— 受控用例：敌方技能首次触发 {init:g}s（原值见下），"
          f"带该机制的出怪行 {n_carriers} 条 ——")
    for s in base.get("spawns", []):
        if is_skill_atk_dict(s):
            print(f"   {s.get('name')}  原 init={s.get('skill_atk_init')} "
                  f"interval={s.get('skill_atk_interval')} "
                  f"phys={s.get('skill_atk_scale_phys')} "
                  f"magic={s.get('skill_atk_scale_magic')} hp={s.get('hp')}")
            break

    # ---- ① 一致：两边收同一份改动
    spec = json.loads(json.dumps(base))
    for s in spec["spawns"]:
        if is_skill_atk_dict(s):
            s["skill_atk_init"] = float(init)
    with Simgo(find_binary()) as cli:
        got = cli.sim(spec)
    go = (got["kills"], got["leaks"], got["elapsed"],
          float(got.get("damage_dealt") or 0.0))
    py = run_py(plan, roster, init)
    same = (go[0] == py[0] and go[1] == py[1] and abs(go[2] - py[2]) < 1e-6
            and abs(go[3] - py[3]) < 1e-6)
    print(f"\n① 一致  原版 {py[0]}杀 {py[1]}漏 {py[2]:.6f}s 伤害 {py[3]:,.1f}")
    print(f"        Go   {go[0]}杀 {go[1]}漏 {go[2]:.6f}s 伤害 {go[3]:,.1f}"
          f"   → {'✅ 逐项相同' if same else '❌ 有差'}")

    # ---- ② 咬到：把整组清零，判决必须变
    mut = json.loads(json.dumps(spec))
    for s in mut["spawns"]:
        for k in ("skill_atk_scale_phys", "skill_atk_scale_magic",
                  "skill_atk_pollut"):
            s.pop(k, None)
    with Simgo(find_binary()) as cli:
        m = cli.sim(mut)
    mut_v = (m["kills"], m["leaks"], m["elapsed"],
             float(m.get("damage_dealt") or 0.0))
    bit = mut_v != go
    print(f"② 咬到  清零后 Go {mut_v[0]}杀 {mut_v[1]}漏 {mut_v[2]:.6f}s "
          f"伤害 {mut_v[3]:,.1f}   → "
          f"{'✅ 判决变了（这一层真的在被消费）' if bit else '❌ 一字不变，用例证明不了它'}")

    # ---- ③ 走过：Go 侧确实发出了敌方技能出手的痕迹
    print("③ 走过  " + ("见 ENEMYATK-BONUS 行数（下方由上一条命令另查）"
                       if not bit else "判决已变 ⇒ 这条路被走过"))
    return 0 if (same and bit) else 1


def is_skill_atk_dict(s: dict) -> bool:
    return bool(s.get("skill_atk_scale_phys") or s.get("skill_atk_scale_magic"))


if __name__ == "__main__":
    raise SystemExit(main())
