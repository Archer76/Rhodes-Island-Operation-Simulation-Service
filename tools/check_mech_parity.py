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

import json
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

#: 关卡 × 编队。练度按各人可达的最高档（`make_unit`），两边一致即可。
#:
#: 挑关的口径不是"名字好听"，而是**这一关能不能把机制逼出来**：
#:   - HS-EX-2：开盘就有播种（【实际】50），干员落在污染格上 → 每秒环境伤害、
#:     干员按点阵亡；
#:   - HS-1／HS-2／HS-3／HS-6／HS-TR-1／HS-TR-2：敌人带 `passive_pollut`，
#:     被击倒时给田地加病害 → 走**被击倒污染**那一路（帧序 7.5）；
#:   - HS-EX-1：出怪最多（73 只），用来压一压机制在长局里的稳定性。
CASES = [
    # 带「玷 / 勿玷」技能出手的关：编队里**必须有一名近战**（`block_cnt > 0`）。
    # 技能是"只打部署于地面的我方单位"，全高台编队会让它一次都放不出来——
    # 那时对拍全绿也证明不了这段代码（反证会当场报出来）。
    dict(stage="HS-4", chars=["char_002_amiya", "char_123_fang"]),
    # ⚠ HS-EX-3／HS-EX-7 不在这里：它们的**装置有影响**（实测把装置摘掉判决就变），
    # 而装置层（阻流阀被拆 → 地形还原、天桩链）还没移植。放行它们等于把
    # "装置层没做"这件事藏起来，所以那一关的结论是"等装置层"，不是"已对上"。
    dict(stage="HS-EX-2", chars=["char_002_amiya"]),
    dict(stage="HS-EX-2", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-TR-2", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-2", chars=["char_002_amiya"]),
    dict(stage="HS-6", chars=["char_002_amiya", "char_123_fang", "char_124_kroos"]),
    dict(stage="HS-EX-1", chars=["char_124_kroos", "char_123_fang"]),
]

#: **只验"闸门放行 + 判决逐项一致"**的关（不做"田地咬到人"的对照）。
#:
#: 为什么单独一组：目标关卡 HS-EX-4 与 HS-5 的田地机制，在本探针试过的编队×落位下
#: 都咬不到人（开/关环境判决完全相同），而它们又必须留在视野里——那是要拿来做
#: 解算提速基准的关。于是把话说小：这一组只证明"Go 能诚实跑完这一关、判决与原版
#: 逐项一致"，**不证明**田地机制在这一关上被走到了（那一层由上面 8 例负责）。
#: 反过来，一支"没被走到却全绿"的检查比没有更糟：它会把"没测"说成"测过"。
SPEC_ONLY = [
    dict(stage="HS-EX-4", chars=["char_002_amiya", "char_124_kroos"]),
    dict(stage="HS-5", chars=["char_002_amiya", "char_123_fang"]),
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


def negative_controls(go, spec: dict, verdict: dict) -> list[str]:
    """反证：把这一层的东西**摘掉**之后，判决必须跟着变。

    为什么非要有这一条：只比"Go 与原版一致"是**可以被伪造的**——
    Go 那边把 `skill_atk_*` 整组读漏、或者机制根本没挂上，只要那一趟恰好不影响
    胜负，判决照样一模一样，检查全绿。所以每一个新接线的量都要配一条"把它摘掉
    就应当变"的实测（这层已经吃过一次：三条机制零开技却给了绿灯）。

    返回不成立的原因（空 = 反证成立）。
    """
    problems = []
    has_skill_atk = any(s.get("skill_atk_scale_phys") or s.get("skill_atk_scale_magic")
                        for s in spec.get("spawns", []))
    if has_skill_atk:
        mutant = json.loads(json.dumps(spec))
        for s in mutant["spawns"]:
            for key in ("skill_atk_scale_phys", "skill_atk_scale_magic",
                        "skill_atk_pollut"):
                s.pop(key, None)
        got = go.sim(mutant)
        if _same_core(verdict, got):
            problems.append("把敌方技能出手整组清零，判决一字不变"
                            "（这一趟它没落地，用例证明不了它被用上了）")
    has_pollut = any(s.get("passive_pollut") for s in spec.get("spawns", []))
    if has_pollut:
        mutant = json.loads(json.dumps(spec))
        for s in mutant["spawns"]:
            s.pop("passive_pollut", None)
        got = go.sim(mutant)
        if _same_core(verdict, got):
            problems.append("把被击倒污染清零，判决一字不变（这一趟它没落地）")
    if spec.get("mechanisms"):
        mutant = json.loads(json.dumps(spec))
        mutant["mechanisms"] = []
        mutant.pop("mech_config", None)
        got = go.sim(mutant)
        if _same_core(verdict, got):
            problems.append("把机制整层摘掉，判决一字不变（挂没挂上分不出来）")
    return problems


def _same_core(a: dict, b: dict) -> bool:
    """两份判决在**核心指标**上是否相同（与对拍台同一套口径）。"""
    return all(a.get(k) == b.get(k) for k in
               ("won", "kills", "leaks", "elapsed", "damage_dealt"))


def candidate_cells(sim, stage) -> list[tuple[int, int]]:
    """可部署格，**田地上的排前面**（机制只在干员站上去时才咬得到人）。"""
    cells = spots_of(stage)
    farm = getattr(sim, "farmland", None)
    if farm is None or not cells:
        return cells
    on_field = [c for c in cells if farm.is_farmland(*c)]
    rest = [c for c in cells if c not in set(on_field)]
    return on_field + rest


def plan_for(sim, stage, squad, calc, cells: list[tuple[int, int]] | None = None
             ) -> list[Deployment]:
    """排一份计划：按费用排落地时刻，落位从 `cells` 依次取。

    落位是参数而不是写死"地图顺序前几个"：田地机制只在干员站上去时才咬得到人，
    随手取的落位很可能整场没人站在田地上，于是"开环境"与"关环境"判决完全相同
    ——这一关就**测不出机制**。所以 `main` 会逐个落位试到"能区分"为止
    （与技能那一层"弱用例等于不给证据"是同一条教训）。
    """
    cells = cells or candidate_cells(sim, stage)
    plan = []
    rate = float(stage.options.cost_increase_time)
    for i, cid in enumerate(squad):
        unit = make_unit(calc, cid)
        need = max(0.0, float(unit.deploy_cost) - float(stage.options.initial_cost))
        at = round(need * rate, 3) + (1.0 if need else 0.0)
        plan.append(Deployment(at, unit, cells[i % len(cells)], "Right"))
    return plan


def run_py(stage, squad, calc, *, environment: str = "auto", spec_out: bool = False,
           drop_devices: bool = False, cells=None):
    """跑一次原版。

    ⚠ `spec_out=True` 时规格取的是**跑之前**的那个状态（`build_spec` 是纯读，
    但它读的 `sim.life` / `sim.cost` 都是"此刻"的值）：从**跑完之后**的对象上取规格，
    life 已经是 0（漏光了），Go 收到一份 life=0 的规格会当场判负、一帧都不跑——
    实测就是这么撞上的。所以规格与参考结果只能来自**同一份计划的两个对象**。

    `drop_devices=True` 是"装置摘掉结果一字不变"那条证据的实测手段（见 `main`）。
    """
    sim = BattleSimulator(stage, enemy_at=lib_get(stage), environment=environment)
    if drop_devices:
        sim._devices = []
    for d in plan_for(sim, stage, squad, calc, cells):
        sim.plan(d)
    spec = build_spec(sim, allow_devices=True) if spec_out else None
    res = sim.run()
    return (spec, sim, res) if spec_out else (sim, res)


def pick_biting_cells(stage, squad, calc, go=None, *, tries: int = 12):
    """找一个"这一关**真的把这层代码走到了**"的落位。

    两条判据都要成立，缺一不算：

    1. **能区分**：同一个落位、同一套编队，开环境与关环境的判决必须不同。
       相同就说明田地这一场没起作用，那么后面"Go 与 Python 一致"就是一条
       **没有内容的绿灯**——两边都合起来算错也照样通过。
    2. **反证成立**（这一关有对应机制时才要求）：把这一层的数据从规格里摘掉
       （敌方技能出手整组清零 / 被击倒污染清零），Go 的判决必须跟着变。
       不成立就说明**这一趟它压根没落地**——比如 HS-EX-4／HS-5 的技能出手是
       "只打地面单位"，而阿米娅、克洛丝都是高台（阻挡 0），技能一次都没触发：
       这时"Go 与原版一致"证明的是别的东西，不是这段代码。

    返回 (落位表, 开环境结果)；试遍了都不行则返回 (None, None)。
    """
    sim0 = BattleSimulator(stage, enemy_at=lib_get(stage))
    cells = candidate_cells(sim0, stage)
    if not cells:
        return None, None
    for i in range(min(tries, len(cells))):
        pick = cells[i:] + cells[:i]
        _, res_on = run_py(stage, squad, CALC, cells=pick)
        _, res_off = run_py(stage, squad, CALC, environment="off", cells=pick)
        if res_on.won == res_off.won and res_on.kills == res_off.kills \
                and abs(res_on.elapsed - res_off.elapsed) <= 1e-9:
            continue
        if go is not None and _has_negative_control(stage, squad, pick, go):
            return pick, res_on
        elif go is None:
            return pick, res_on
    return None, None


def _has_negative_control(stage, squad, cells, go) -> bool:
    """这一趟的规格在 Go 那边摘掉本层数据后，判决会不会变（见 `pick_biting_cells`）。"""
    spec, _, _ = run_py(stage, squad, CALC, spec_out=True, cells=cells)
    if spec["unsupported"]:
        return False
    try:
        base = go.sim(spec)
    except RuntimeError:
        return False
    return bool(negative_controls(go, spec, base)) is False


def farmland_state_diff(sim, verdict: dict) -> str:
    """机制状态逐项比（比判决更细的那一层）。

    判决是粗指标：病害值累积得不一样、但这一趟恰好没有干员站在那格上时，判决可以
    完全相同——那正是这层最容易藏偏差的地方，所以要直接比状态。

    比较口径与两边**同形**：片的格集合、每片【最大】【缓存】、每格【实际】。
    容差取 1e-9（两边跑的是同一串加法，但事件落在哪一帧取决于各自帧序里那些
    细节，个别量可能差最后几位）；**换行打印最大差值**，免得"容差之内"变成
    看不见的漂移。
    """
    fs = getattr(sim, "farmland", None)
    got = (verdict.get("mech_state") or {}).get("huai_shu_li.farmland")
    if fs is None or got is None:
        return ""
    want_groups = sorted(
        (tuple(sorted(f.cells)), round(float(f.maximum), 9), round(float(f.cache), 9))
        for f in fs.fields)
    got_groups = sorted(
        (tuple(sorted((int(c[0]), int(c[1])) for c in g["cells"])),
         round(float(g["maximum"]), 9), round(float(g["cache"]), 9))
        for g in got["groups"])
    if want_groups != got_groups:
        return f"片不一致：原版 {want_groups[:2]}… vs Go {got_groups[:2]}…"
    want_actual = {c: float(v) for c, v in fs.actual.items()}
    got_actual = {(int(a[0]), int(a[1])): float(a[2]) for a in got["actual"]}
    if set(want_actual) != set(got_actual):
        only_a = sorted(set(want_actual) - set(got_actual))[:3]
        only_b = sorted(set(got_actual) - set(want_actual))[:3]
        return f"格集合不一致：原版多 {only_a}，Go 多 {only_b}"
    worst, where = 0.0, None
    for c, v in want_actual.items():
        d = abs(v - got_actual[c])
        if d > worst:
            worst, where = d, c
    if worst > 1e-9:
        return f"格 {where} 的【实际】差 {worst:.3g}（原版 {want_actual[where]:.6f} vs Go {got_actual[where]:.6f}）"
    if worst > 0:
        print(f"      （机制状态最大差值 {worst:.2g}，在容差内）")
    return ""


def lib_get(stage):
    return LIB.get


def farmland_touched(sim) -> float:
    """这一关打完时，田地上的病害值总量（用来判断机制是否真动过）。"""
    fs = getattr(sim, "farmland", None)
    if fs is None:
        return 0.0
    return sum(float(v) for v in fs.actual.values())


def _spec_only_pass(exe, src) -> int:
    """`SPEC_ONLY` 那一组：只验"闸门放行 + 判决逐项一致 + 机制状态一致"。

    返回失败条数。**不要求**田地机制在这一关被咬到（原因见 `SPEC_ONLY` 的注释）。
    """
    bad = 0
    with Simgo(exe) as go:
        for case in SPEC_ONLY:
            code, squad = case["stage"], case["chars"]
            label = f"{code} {squad}（只验判决）"
            stage = load_stage(code, source=src)
            cells = candidate_cells(BattleSimulator(stage, enemy_at=lib_get(stage)),
                                   stage)
            spec, sim_on, res_on = run_py(stage, squad, CALC, spec_out=True, cells=cells)
            if spec["unsupported"]:
                print(f"❌ {label}：闸门没放行 {spec['unsupported']}")
                bad += 1
                continue
            try:
                verdict = go.sim(spec)
            except RuntimeError as exc:
                print(f"❌ {label}：Go 拒跑 {exc}")
                bad += 1
                continue
            diff = compare(res_on, verdict)
            mech_diff = farmland_state_diff(sim_on, verdict)
            ok = diff["ok"] and not mech_diff
            print(f"{'✅' if ok else '❌'} {label}："
                  f"Go {verdict.get('kills')}杀 {verdict.get('leaks')}漏 "
                  f"{verdict.get('elapsed', 0):.3f}s 伤害 {verdict.get('damage_dealt', 0):.1f}"
                  f"；机制={spec['mechanisms']}")
            if mech_diff:
                print(f"      机制状态不一致：{mech_diff}")
            if not ok:
                bad += 1
    return bad


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
    weak = 0
    with Simgo(exe) as go:
        mechs = go.mechanisms()
        print(f"Go 侧编译进来的机制：{mechs}")
        if "huai_shu_li.farmland" not in mechs:
            print("❌ 机制没注册，本探针没有意义")
            return 1
        for case in CASES:
            code, squad = case["stage"], case["chars"]
            label = f"{code} {squad}"
            stage = load_stage(code, source=SRC)
            cells, res_on_probe = pick_biting_cells(stage, squad, CALC, go)
            if cells is None:
                print(f"⊘ {label}：这套编队在这关**咬不到田地机制**"
                      f"（试遍了可部署格，开/关环境判决都相同）——不计入通过数")
                weak += 1
                continue
            spec, sim_on, res_on = run_py(stage, squad, CALC, spec_out=True, cells=cells)
            _, res_off = run_py(stage, squad, CALC, environment="off", cells=cells)
            key = ("won", "kills", "leaks", "elapsed", "damage_dealt")
            on, off = [getattr(res_on, k) for k in key], [getattr(res_off, k) for k in key]
            if on == off:
                print(f"❌ {label}：选出来的落位反而不区分了（探针自己不一致）")
                bad += 1
                continue
            # `allow_devices` 是**要带证据打开**的口子：先实测"把装置摘掉判决一字
            # 不变"，通过了才敢让 Go 那边只挂开场那道 `sever` 的几何。
            # 不实测就传 True，等于把"装置层还没移植"这件事藏起来。
            _, res_nodev = run_py(stage, squad, CALC, drop_devices=True, cells=cells)
            dev_key = tuple(getattr(res_nodev, k) for k in key)
            if dev_key != tuple(on):
                print(f"❌ {label}：这一关的装置**有影响**"
                      f"（摘掉后 {dev_key} ≠ {tuple(on)}），装置层还没移植，不该放行")
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
            mech_diff = farmland_state_diff(sim_on, verdict)
            weak_controls = negative_controls(go, spec, verdict)
            dirty = farmland_touched(sim_on)
            print(f"{'✅' if diff['ok'] and not mech_diff and not weak_controls else '❌'} "
                  f"{label}：落位 {cells[0]}，"
                  f"开环境 {tuple(round(x, 3) if isinstance(x, float) else x for x in on)} → "
                  f"关环境 {tuple(round(x, 3) if isinstance(x, float) else x for x in off)}；"
                  f"机制={spec['mechanisms']}，收尾病害值合计 {dirty:.1f}")
            if mech_diff:
                print(f"      机制状态不一致：{mech_diff}")
                bad += 1
            for why in weak_controls:
                print(f"      反证不成立：{why}")
                bad += 1
            if mech_diff:
                print(f"      机制状态不一致：{mech_diff}")
                bad += 1
            print(f"      Go 判决 {verdict.get('kills')}杀 {verdict.get('leaks')}漏 "
                  f"{verdict.get('elapsed'):.3f}s 伤害 {verdict.get('damage_dealt'):.1f}")
            if not diff["ok"]:
                print(f"      差异 {diff['diff']}　{diff['note']}")
                bad += 1
    print(f"\n共 {len(CASES)} 例：通过 {len(CASES) - bad - weak}，失败 {bad}，"
          f"咬不到机制（不计入）{weak}")
    if len(CASES) - bad - weak == 0:
        print("❌ 一条有效证据都没有：这不算通过")
        return 1
    bad += _spec_only_pass(exe, SRC)
    return 0 if bad == 0 else 1


#: 数据源与计算器在 `main` 里惰性建（没同步数据的机器上，import 本文件不该炸）。
SRC = None
LIB = None
CALC = OperatorCalculator()

if __name__ == "__main__":
    raise SystemExit(main())
