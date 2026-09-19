# -*- coding: utf-8 -*-
"""对拍台：一批常规关卡上，原版 Python vs rios-sim（Go）逐项比。

## 用例是怎么挑的

* **没有装置**的关卡（有装置的会被最小版本拒跑；1-7 那个 `trap_002_emp` 由
  "摘掉它重跑一遍、结果一字不变"实测无影响，所以也收进来了）；
* 部署时刻按**真实费用**算（`初始费用 + 需要攒的费 × 回复间隔 + 1 秒余量`），
  这样两边都不会因为"排了一手付不起的部署"而各拒各的；
* 每关两个阵容：单人（只摆第一个可部署格）与双人（近战位 + 远程位各一个）。
  单人用例能把"没有目标时要不要重置出手计时器"这类细节单独逼出来。

    python tools/check_simgo_parity.py            # 全量
    python tools/check_simgo_parity.py 1-7 0-1    # 只跑这两关

退出码 0 = 全绿。
"""
from __future__ import annotations

import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import BattleSimulator, Deployment            # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                      # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.operator import OperatorCalculator                   # noqa: E402
from ak_tactic.simgo import (EngineBinaryUnpinned, Simgo, build_spec,
                             compare, require_binary)                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs

#: 对拍用的关卡（都不带装置、都不是活动中那些特殊机制关）
STAGES = ["1-1", "1-2", "1-3", "1-4", "1-5", "1-6", "1-7",
          "0-1", "0-4", "TR-1", "TR-2", "2-1"]

#: 阵容：`(char_id, 练度)`。`(2, 80)` 是"精英二 80 级"，够在这些早期关里站住。
SQUADS = {
    "单人": [("char_002_amiya", dict(elite=2, level=80, trust=100, potential=6))],
    "双人": [("char_002_amiya", dict(elite=2, level=80, trust=100, potential=6)),
             ("char_102_texas", dict(elite=2, level=1))],
}


def make_unit(calc, char_id: str, **kw) -> OperatorUnit:
    st = calc.stats(char_id, **kw)
    t = st.total
    return OperatorUnit(
        name=st.name, char_id=char_id, elite=kw.get("elite", 2),
        max_hp=float(t["maxHp"]), atk=float(t["atk"]), defense=float(t["def"]),
        res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100),
    )


def spots_of(stage) -> list[tuple[int, int]]:
    """可部署格：近战位在前、远程位在后（同一关里顺序固定 ⇒ 可复现）。"""
    out: list[tuple[int, int]] = []
    for group in ("melee_spots", "ranged_spots"):
        for cell in getattr(stage.map, group, []) or []:
            pos = (int(cell[0]), int(cell[1]))
            if pos not in out:
                out.append(pos)
    return out


def plan_for(stage, squad, calc) -> list[Deployment]:
    """按**真实费用**排时刻（与 `verify.py` 同一个模型 + 1 秒余量）。

    时刻算得对，两边才都放得下去；算错的话会出现"原版拒收、Go 也拒收"这种
    **看着一致其实没测到东西**的假绿。
    """
    rate = float(stage.options.cost_increase_time)
    cost = float(stage.options.initial_cost)
    now = 0.0
    cells = spots_of(stage)
    out: list[Deployment] = []
    for i, (char_id, kw) in enumerate(squad):
        op = make_unit(calc, char_id, **kw)
        need = max(0.0, op.deploy_cost - cost)
        at = now + need * rate + (1.0 if need else 0.0)
        cost = cost + need - op.deploy_cost
        now = at
        cell = cells[min(i, len(cells) - 1)]
        out.append(Deployment(at, op, cell, "Right"))
    return out


def run_case(src, lib, calc, code: str, label: str, squad) -> tuple[bool, str]:
    stage = load_stage(code, source=src)
    plan = plan_for(stage, squad, calc)

    py = BattleSimulator(stage, enemy_at=lib.get)
    for d in plan:
        py.plan(d)
    t0 = time.perf_counter()
    res = py.run()
    py_ms = (time.perf_counter() - t0) * 1000
    if getattr(res, "skill_activations", 0):
        return False, "原版开了技能（这一版最小实现没有技能，用例不该带技能）"

    # 装置运行期：不假设没用——但**只关** `_device_tick`／`_pile_tick` 重跑，
    # 一字不变才算它没参与这一局。⚠ 不能写 `nd._devices = []`：那一清连开场断田
    # 的几何一起摘了，而几何 Go 的规格里**有**，照那个口径量到的是"几何有影响"。
    nd = BattleSimulator(stage, enemy_at=lib.get)
    for d in plan:
        nd.plan(d)
    nd._device_tick = lambda dt, t: None
    nd._pile_tick = lambda dt, t: None
    res_nd = nd.run()
    dev_ok = (res_nd.kills, res_nd.leaks, round(res_nd.elapsed, 6)) == (
        res.kills, res.leaks, round(res.elapsed, 6))

    spec_sim = BattleSimulator(stage, enemy_at=lib.get)
    for d in plan:
        spec_sim.plan(d)
    spec = build_spec(SpecInputs.from_sim(spec_sim), stage_label=code, allow_devices=dev_ok)
    if spec["unsupported"]:
        return False, f"规格里有不支持项：{spec['unsupported']}"

    with Simgo(find_binary()) as gosim:
        go = gosim.sim(spec)
    got = compare(res, go)
    head = (f"{res.kills:>3}杀/{res.leaks:>2}漏/{res.elapsed:>6.1f}s "
            f"伤害 {res.damage_dealt:>9,.0f}　原版 {py_ms:>6.0f}ms　"
            f"Go {go['sim_ms']:>6.1f}ms　加速 {py_ms / max(go['sim_ms'], 0.001):>5.1f}×")
    if got["ok"]:
        return True, head
    return False, f"{head}\n        差异：{got['diff']}"


def _force_utf8_stdout() -> None:
    """输出重定向时消息也必须可读（口径⑤）：否则报错里的中文路径按 GBK 落盘、看的人读不出来。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except Exception:                            # noqa: BLE001
            pass


def main() -> int:
    _force_utf8_stdout()
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    codes = only or STAGES
    try:
        exe = require_binary()
    except EngineBinaryUnpinned as e:
        # ⚠ 这里原本是「跳过：没找到 rios-sim 的可执行文件 → return 0」。那是一条**rc=0 的假绿出口**：
        #    一台都没跑，而在读数上与「全部对拍一致」长得一模一样（PM 2026-09-19）。
        #    现在**没有"跳过"这条出口**：未钉住/钉错 ⇒ 报出那条能直接粘的命令、点名路径，rc=2。
        print(f"⛔ {e}", file=sys.stderr)
        return 2

    src = GameDataSource()
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    print(f"对拍台：{len(codes)} 关 × {len(SQUADS)} 阵容　"
          f"（原版 {sys.version.split()[0]} vs rios-sim {exe.name}）\n")

    ok_all, bad, speeds = True, [], []
    for code in codes:
        for label, squad in SQUADS.items():
            try:
                ok, msg = run_case(src, lib, calc, code, label, squad)
            except Exception as exc:                                 # noqa: BLE001
                ok, msg = False, f"{exc.__class__.__name__}: {exc}"
            mark = "✅" if ok else "❌"
            print(f"{mark} {code:<6}{label}  {msg}")
            if ok:
                # 只统计完整的"加速"数字（msg 里带 × 的那种）
                if "加速" in msg:
                    try:
                        speeds.append(float(msg.rsplit("×", 1)[0].rsplit()[-1]))
                    except ValueError:
                        pass
            else:
                bad.append(f"{code}/{label}")
                ok_all = False

    print()
    if ok_all:
        avg = sum(speeds) / len(speeds) if speeds else 0.0
        print(f"全部一致（{len(codes) * len(SQUADS)} 例）　单场平均加速 {avg:.1f}×")
        return 0
    print(f"不一致：{bad}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
