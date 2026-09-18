# -*- coding: utf-8 -*-
"""怀黍离田地机制的**真关卡对拍**（机制层的第一块）。

与 `simgo_parity.py` 的区别：那份对拍的是"常规关卡 + 技能"，田地这一关的关键是
**机制真的动了手**——所以本探针除了逐项比判决，还要证明"田地这一层确实起了作用"：

1. **对照组**：同一关、同一编队，在 Python 里把环境关掉（`environment="off"`）
   跑一次。若它与开着环境的判决**完全相同**，那这一关测不出田地机制，
   对拍通过也没有意义（本探针会直接报"这一关测不出田地"，不给绿灯）。
2. **实验组**：Python 开着环境 vs Go 挂着 `huai_shu_li.farmland`，逐项比判决。

只有"对照组能区分、实验组一致"两件同时成立，才算这一块机制在真关卡上对上了。
"""
from __future__ import annotations

import pathlib
import sqlite3
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import BattleSimulator, Deployment          # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                     # noqa: E402
from ak_tactic.gamedata import GameDataSource, EnemyLibrary, load_stage  # noqa: E402
from ak_tactic.operator import OperatorCalculator                  # noqa: E402
from ak_tactic.simgo import Simgo, build_spec, compare, find_binary  # noqa: E402

#: 关卡 × 编队 × 落位。练度按各人可达的最高档（`make_unit`），两边一致即可。
CASES = [
    dict(stage="HS-EX-2", chars=["char_002_amiya"]),
    dict(stage="HS-EX-2", chars=["char_002_amiya", "char_123_fang"]),
]

STATS_KW = dict(elite=2, level=80, trust=100, potential=6)


def make_unit(calc, char_id: str) -> OperatorUnit:
    """练度取这名干员**能到的最高档**。

    低星干员没有精二（芬就精一为止），写死 elite=2 会当场炸——而对拍要比的是
    "两边算同一场战斗"，练度只要**两边一致**即可，不必是最满档。
    """
    last: Exception | None = None
    for kw in (dict(elite=2, level=80), dict(elite=2, level=70),
               dict(elite=1, level=70), dict(elite=1, level=55),
               dict(elite=1, level=1), dict(elite=0, level=1)):
        try:
            st = calc.stats(char_id, trust=100, potential=6, **kw)
            break
        except Exception as exc:                                # noqa: BLE001
            last = exc
    else:
        raise RuntimeError(f"{char_id} 哪个练度档都取不到：{last}")
    t = st.total
    return OperatorUnit(
        name=st.name, char_id=char_id, elite=int(kw["elite"]),
        max_hp=float(t["maxHp"]), atk=float(t["atk"]),
        defense=float(t["def"]), res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100))


def spots_of(stage) -> list[tuple[int, int]]:
    out = []
    for attr in ("melee_spots", "ranged_spots"):
        for c in getattr(stage.map, attr, None) or []:
            out.append((int(c[0]), int(c[1])))
    return out


def plan_for(sim, stage, squad, calc) -> list[Deployment]:
    """按费用排落地时刻，落位取地图顺序的前几个可部署格（与对拍台同口径）。"""
    cells = spots_of(stage)
    plan = []
    rate = float(stage.options.cost_increase_time)
    for i, cid in enumerate(squad):
        unit = make_unit(calc, cid)
        need = max(0.0, float(unit.deploy_cost) - float(stage.options.initial_cost))
        at = round(need * rate, 3) + (1.0 if need else 0.0)
        plan.append(Deployment(at, unit, cells[i % len(cells)], "Right"))
    return plan


def run_py(stage, squad, calc, *, environment: str = "auto", spec_out: bool = False):
    """跑一次原版。

    ⚠ `spec_out=True` 时规格取的是**跑之前**的那个状态（`build_spec` 是纯读，
    但它读的 `sim.life` / `sim.cost` 都是"此刻"的值）：从**跑完之后**的对象上取规格，
    life 已经是 0（漏光了），Go 收到一份 life=0 的规格会当场判负、一帧都不跑——
    实测就是这么撞上的。所以规格与参考结果只能来自**同一份计划的两个对象**。
    """
    sim = BattleSimulator(stage, enemy_at=lib_get(stage), environment=environment)
    for d in plan_for(sim, stage, squad, calc):
        sim.plan(d)
    spec = build_spec(sim, allow_devices=True) if spec_out else None
    res = sim.run()
    return (spec, sim, res) if spec_out else (sim, res)


def lib_get(stage):
    return LIB.get


def farmland_touched(sim) -> float:
    """这一关打完时，田地上的病害值总量（用来判断机制是否真动过）。"""
    fs = getattr(sim, "farmland", None)
    if fs is None:
        return 0.0
    return sum(float(v) for v in fs.actual.values())


def main() -> int:
    exe = find_binary()
    if exe is None:
        print("[skip] 找不到 rios-sim 可执行文件（先 `cd rios-sim; go build`）")
        return 0
    try:
        SRC = GameDataSource()                       # noqa: N806
        LIB = EnemyLibrary(source=SRC)               # noqa: N806
        load_stage(CASES[0]["stage"], source=SRC)
    except Exception as exc:                                       # noqa: BLE001
        # 仓库惯例：这台机器没同步数据就**跳过**，不是失败。
        print(f"[skip] 取不到本地游戏数据（{exc.__class__.__name__}）")
        return 0
    globals()["SRC"], globals()["LIB"] = SRC, LIB
    bad = 0
    with Simgo(exe) as go:
        mechs = go.mechanisms()
        print(f"Go 侧编译进来的机制：{mechs}")
        if "huai_shu_li.farmland" not in mechs:
            print("❌ 机制没注册，本探针没有意义")
            return 1
        for case in CASES:
            code, squad = case["stage"], case["chars"]
            stage = load_stage(code, source=SRC)
            spec, sim_on, res_on = run_py(stage, squad, CALC, spec_out=True)
            _, res_off = run_py(stage, squad, CALC, environment="off")
            key = ("won", "kills", "leaks", "elapsed", "damage_dealt")
            on, off = [getattr(res_on, k) for k in key], [getattr(res_off, k) for k in key]
            label = f"{code} {squad}"
            if on == off:
                print(f"❌ {label}：这一关测不出田地机制（环境开着与关着判决相同）")
                bad += 1
                continue
            if spec["unsupported"]:
                print(f"❌ {label}：闸门没放行 {spec['unsupported']}")
                bad += 1
                continue
            try:
                verdict = go.sim(spec)      # 不支持时**抛异常**，不返回残缺判决
            except RuntimeError as exc:
                print(f"❌ {label}：Go 拒跑 {exc}")
                bad += 1
                continue
            diff = compare(res_on, verdict)
            dirty = farmland_touched(sim_on)
            print(f"{'✅' if diff['ok'] else '❌'} {label}："
                  f"开环境 {tuple(round(x, 3) if isinstance(x, float) else x for x in on)} → "
                  f"关环境 {tuple(round(x, 3) if isinstance(x, float) else x for x in off)}；"
                  f"机制={spec['mechanisms']}，收尾病害值合计 {dirty:.1f}")
            print(f"      Go 判决 {verdict.get('kills')}杀 {verdict.get('leaks')}漏 "
                  f"{verdict.get('elapsed'):.3f}s 伤害 {verdict.get('damage_dealt'):.1f}")
            if not diff["ok"]:
                print(f"      差异 {diff['diff']}　{diff['note']}")
                bad += 1
    print(f"\n共 {len(CASES)} 例，失败 {bad} 例")
    return 0 if bad == 0 else 1


#: 数据源与计算器在 `main` 里惰性建（没同步数据的机器上，import 本文件不该炸）。
SRC = None
LIB = None
CALC = OperatorCalculator()

if __name__ == "__main__":
    raise SystemExit(main())
