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
import copy
import dataclasses
import pathlib
import subprocess
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
from ak_tactic.plan import Plan, Roster                              # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                      # noqa: E402
from ak_tactic.verify import Verifier                                # noqa: E402

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
    # HS-EX-3（15 个天桩装置）与 HS-EX-7（16 个阻流阀）曾经被判"装置有影响"而挡在
    # 门外——那是**对照问错了问题**（清空 `_devices` 连开场断田几何一起摘了）。
    # 改成只关运行期（建成/进入触发/被拆还原、天桩链）之后，这两关的判决一字不变，
    # 也就是 Go 那份"带着几何、不带运行期"的规格对它们已经够了。
    dict(stage="HS-EX-3", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-EX-7", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-8", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-TR-1", chars=["char_002_amiya", "char_123_fang"]),
    # ⚠ HS-EX-3／HS-EX-7 不在这里：它们的**装置有影响**（实测把装置摘掉判决就变），
    # 而装置层（阻流阀被拆 → 地形还原、天桩链）还没移植。放行它们等于把
    # "装置层没做"这件事藏起来，所以那一关的结论是"等装置层"，不是"已对上"。
    dict(stage="HS-EX-2", chars=["char_002_amiya"]),
    dict(stage="HS-EX-2", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-TR-2", chars=["char_002_amiya", "char_123_fang"]),
    dict(stage="HS-2", chars=["char_002_amiya"]),
    dict(stage="HS-6", chars=["char_002_amiya", "char_123_fang", "char_124_kroos"]),
    dict(stage="HS-EX-1", chars=["char_124_kroos", "char_123_fang"]),
    # HS-S-1：第一关**判决真的压在天桩链上**的。它当初在闸门上是"放行"的
    # （甲是装置召唤物、不在敌人字段表里），所以"放行 ≠ 判决一致"这句话就是
    # 从它身上量出来的：链条没接线时 Go 给 `0杀/86.1s`，原版 `8杀/52.533s`。
    # 现在四跳接线后逐位一致（`8杀/4漏/52.533s/伤害 0.0`），连 `damage_dealt`
    # 都对上了——那一笔曾经是 1.2，根因是"乙贴住目标后旧路线还挂着、下一帧
    # 又往前挪了一格"，于是它在自毁前多挨了一下（见 `sim.go::SetEnemyRoute`）。
    dict(stage="HS-S-1", chars=["char_002_amiya", "char_123_fang"]),
    # ---- 重生（`Reborn.*` / 怀黍离「瘴 / 鄙瘴」的 `Reborning.*`）
    #
    # 这一族关卡原先整批被"重生吸病害值"挡在闸门外，现在闸门放行了。但**放行不等于
    # 验过**——本工具试过的编队（阿米娅/芬/克洛丝，精2 lv80）在任何落位下都打不死
    # 「瘴 / 鄙瘴」，所以"重生那一段"在这些用例里**一次都没跑到**：HS-7 之所以算数，
    # 靠的是**环境层**咬到了判决（开/关环境 2杀/75.433s → 6杀/97.9s）。
    #
    # ⚠ 因此这一条是**在视野里**，不是**已证过**：重生那条分支要有"咬得到重生"的
    # 用例才算数（`pick_biting_cells` 的第三层就是为此加的，它现在报的是"三层都不咬
    # 重生"）。下一步要么换一支打得死它的编队，要么给它单独搭一个能走到那条分支的
    # 用例——在那之前，别把这一族的绿灯读成"重生已经对齐"。
    dict(stage="HS-7", chars=["char_002_amiya", "char_123_fang"]),
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
    # HS-EX-5（「鄙瘴」那一支）：闸门已经放行，但三名干员在 12 个落位下都打不死它，
    # 于是**三层对照一个都不咬**——那不是我漏了哪一层，是这一场压根走不到那些代码。
    # 留在这里只证明"Go 能诚实跑完、判决与原版逐项一致"，别读成"重生验过了"。
    dict(stage="HS-EX-5", chars=["char_002_amiya", "char_123_fang"]),
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


def negative_controls(go, spec: dict, verdict: dict, *, layer: str = "") -> list[str]:
    """反证：把这一层的东西**摘掉**之后，判决必须跟着变。

    为什么非要有这一条：只比"Go 与原版一致"是**可以被伪造的**——
    Go 那边把 `skill_atk_*` 整组读漏、或者机制根本没挂上，只要那一趟恰好不影响
    胜负，判决照样一模一样，检查全绿。所以每一个新接线的量都要配一条"把它摘掉
    就应当变"的实测（这层已经吃过一次：三条机制零开技却给了绿灯）。

    `layer` 是**这一关声明要证的那一层**（"environment" / "pile"）。要求**只有
    那一层**必须咬：一个用例只证得动一件事，硬要它同时把每一层都咬到，结果要么
    是给不出用例，要么是逼着人放宽判据。HS-S-1 就是这种情形——它的胜负有
    影响的是天桩链，而"被击倒污染"摘掉一字不变（那一关的敌人身上有这条键，
    但这一趟它没落地），两者不该互相拖累。

    返回不成立的原因（空 = 反证成立）。
    """
    problems = []

    def differs(mutant) -> bool:
        """摘掉数据之后判决变了没有。

        **Go 拒跑也算"变了"**：把这一层的数据摘掉后规格自相矛盾（例如天桩没了
        召唤模板），Go 会照约定拒跑而不是硬算——这恰好说明这一层真的在被消费。
        不这么算的话，工具会被自己的拒跑门撞崩（实测就是这么崩的）。
        """
        try:
            got = go.sim(mutant)
        except RuntimeError:
            return True
        return not _same_core(verdict, got)

    has_skill_atk = any(s.get("skill_atk_scale_phys") or s.get("skill_atk_scale_magic")
                        for s in spec.get("spawns", []))
    if has_skill_atk and layer in ("", "environment"):
        mutant = json.loads(json.dumps(spec))
        for s in mutant["spawns"]:
            for key in ("skill_atk_scale_phys", "skill_atk_scale_magic",
                        "skill_atk_pollut"):
                s.pop(key, None)
        if not differs(mutant):
            problems.append("把敌方技能出手整组清零，判决一字不变"
                            "（这一趟它没落地，用例证明不了它被用上了）")
    has_pollut = any(s.get("passive_pollut") for s in spec.get("spawns", []))
    if has_pollut and layer in ("", "environment"):
        mutant = json.loads(json.dumps(spec))
        for s in mutant["spawns"]:
            s.pop("passive_pollut", None)
        if not differs(mutant):
            problems.append("把被击倒污染清零，判决一字不变（这一趟它没落地）")
    # 天桩链的反证：把**召唤模板**（甲／它身上的乙／乙身上的天标）摘掉。
    # 摘模板而不是摘装置：装置的"存在"还要撑起开场的断田几何，一起摘会把
    # 几何也带走（这是装置层那一次踩过的坑，见 `run_py` 的说明）。
    devices = (spec.get("mech_config", {}).get("huai_shu_li.farmland", {})
               .get("devices", []))
    if any(d.get("kind") == "pile" for d in devices) and layer in ("", "pile"):
        mutant = json.loads(json.dumps(spec))
        for d in mutant["mech_config"]["huai_shu_li.farmland"]["devices"]:
            d.pop("child", None)
        if not differs(mutant):
            problems.append("把天桩链的召唤模板整组摘掉，判决一字不变"
                            "（这一趟链条没落地，用例证明不了它被用上了）")
    # 重生的反证：把重生整组摘掉（还能重生几次 = 0），判决必须跟着变。
    # 这一层要证的是"多一条命"与"重生期充能"都被用上了——两者都住在
    # `_reborn_tick` 那一段里，所以一处摘干净就覆盖整族。
    has_reborn = any(s.get("reborn_left") for s in spec.get("spawns", []))
    if has_reborn and layer in ("", "reborn"):
        mutant = json.loads(json.dumps(spec))
        for s in mutant["spawns"]:
            for key in ("reborn_left", "reborn_interval", "reborn_pollut",
                        "reborn_def_add", "reborn_damage_magic"):
                s.pop(key, None)
        if not differs(mutant):
            problems.append("把重生整组摘掉（还能重生几次 = 0），判决一字不变"
                            "（这一趟重生没落地，用例证明不了它被用上了）")
    if spec.get("mechanisms") and layer in ("", "environment"):
        mutant = json.loads(json.dumps(spec))
        mutant["mechanisms"] = []
        mutant.pop("mech_config", None)
        if not differs(mutant):
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
           drop_device_runtime: bool = False, drop_pile_runtime: bool = False,
           drop_reborn: bool = False, weaken_reborn: float | None = None,
           plan_file=None, cells=None):
    """跑一次原版。

    ⚠ `spec_out=True` 时规格取的是**跑之前**的那个状态（`build_spec` 是纯读，
    但它读的 `sim.life` / `sim.cost` 都是"此刻"的值）：从**跑完之后**的对象上取规格，
    life 已经是 0（漏光了），Go 收到一份 life=0 的规格会当场判负、一帧都不跑——
    实测就是这么撞上的。所以规格与参考结果只能来自**同一份计划的两个对象**。

    `drop_device_runtime=True` 是"装置运行期对判决没有影响"那条证据的实测手段。

    ⚠ 这里**只关运行期那两段**（`_device_tick` 建成/进入触发/被拆还原、
    `_pile_tick` 天桩链），**不碰 `_devices`**——开场的断田几何是构造时算进
    `sim.farmland` 的，Go 的规格**带着**它。早先写成 `sim._devices = []` 是问错了
    问题：那连几何一起摘了，于是把"Go 已经有几何"的关也判成"装置有影响"
    （HS-EX-3 就这么被误挡了一轮）。

    `drop_pile_runtime=True` 只关天桩链那一段（`_pile_tick`），阻流阀的建成/被拆
    还原照旧。**天桩链的对照必须用它，不能拿"开/关环境"顶替**：HS-S-1 的胜负
    压在链条上，而病害值开关对它一字不变——拿环境当对照就会把这一关报成
    "咬不到机制"（⊘），那是**对照问错了问题**，不是"这一关没有内容"。

    `drop_reborn=True` 关的是**重生**那一段（`_reborn_tick`）：BOSS 的"多一条命"
    与「瘴 / 鄙瘴」的重生期充能都住在那儿。同一课又上了一遍——HS-EX-5 的胜负
    压在这一层上，开/关环境与开/关天桩链都一字不变，于是它被报成 ⊘。

    `plan_file` 给的是**解算器存下来的真作业**（`search --save-plan`）。为什么需要它：
    本工具自己那套 `plan_for` 把第 i 个人摆在候选格里的第 i 个，而候选格按地图顺序
    排——除头一格，其余都在路线之外。实测 HS-8 加到 5 个人，伤害一字不变；逐格扫 50
    格、四个朝向，没有一格能碰到「瘴」。也就是说"打到瘴"这件事**不是调参能凑出来的**，
    它要一份真作业。给了 `plan_file` 就用它，`squad`/`cells` 都不再看。
    """
    sim = BattleSimulator(stage,
                          enemy_at=(lib_get(stage) if weaken_reborn is None
                                    else weakened_lib(stage, weaken_reborn)),
                          environment=environment)
    if drop_device_runtime:
        sim._device_tick = lambda dt, t: None
        sim._pile_tick = lambda dt, t: None
    if drop_pile_runtime:
        sim._pile_tick = lambda dt, t: None
    if drop_reborn:
        # ⚠ 只关这一帧的结算：重生期充能与"多一条命"都住在这里，所以
        # `reborn_charge` 会一直是 0，普攻附加伤害（在敌方出手里）也跟着没了——
        # 一处关掉就覆盖了整族，不必再去动 `_enemies_attack`。
        #
        # ⚠ 签名是 `_reborn_tick(self, t)`——**只收一个 t**，别照抄上面
        # `_device_tick`/`_pile_tick` 的 `(dt, t)`：写成两个参数会在第一帧就
        # `missing 1 required positional argument: 't'`（实测踩过）。
        sim._reborn_tick = lambda t: None
    if plan_file is not None:
        for d in load_plan(pathlib.Path(plan_file), calc):
            sim.plan(d)
    else:
        for d in plan_for(sim, stage, squad, calc, cells):
            sim.plan(d)
    spec = build_spec(sim, allow_devices=True) if spec_out else None
    res = sim.run()
    return (spec, sim, res) if spec_out else (sim, res)


def pick_biting_cells(stage, squad, calc, go=None, *, tries: int = 12):
    """找一个"这一关**真的把这层代码走到了**"的落位。

    两条判据都要成立，缺一不算：

    1. **能区分**：同一个落位、同一套编队，**任一层**对照的判决必须不同——
       开环境 / 关环境的判决不同（田地那一层），**或**开天桩链 / 关天桩链的判决
       不同（装置召唤那一层）。两条都相同，才说明这一场压根没走到代码，
       那么后面"Go 与 Python 一致"就是一条**没有内容的绿灯**——两边都合起来算错
       也照样通过。
       ⚠ HS-S-1 是"只咬链条、不咬环境"的那种：它是本工具的第二个对照来源，
       不能拿环境一个开关去顶替（顶替的结果是把它误报成 ⊘）。
    2. **反证成立**（这一关有对应机制时才要求）：把这一层的数据从规格里摘掉
       （敌方技能出手整组清零 / 被击倒污染清零 / 天桩的召唤模板摘掉），Go 的判决
       必须跟着变。不成立就说明**这一趟它压根没落地**——比如 HS-EX-4／HS-5 的
       技能出手是"只打地面单位"，而阿米娅、克洛丝都是高台（阻挡 0），技能一次都
       没触发：这时"Go 与原版一致"证明的是别的东西，不是这段代码。

    返回 (落位表, 开环境结果, 咬到的是哪一层)；试遍了都不行则返回 (None, None, None)。
    """
    sim0 = BattleSimulator(stage, enemy_at=lib_get(stage))
    cells = candidate_cells(sim0, stage)
    if not cells:
        return None, None, None
    for i in range(min(tries, len(cells))):
        pick = cells[i:] + cells[:i]

        def core(res):
            return (res.won, res.kills, round(res.elapsed, 9))

        _, res_on = run_py(stage, squad, CALC, cells=pick)
        _, res_off = run_py(stage, squad, CALC, environment="off", cells=pick)
        _, res_nopile = run_py(stage, squad, CALC, drop_pile_runtime=True, cells=pick)
        _, res_noreborn = run_py(stage, squad, CALC, drop_reborn=True, cells=pick)
        # 三层分别报"有没有影响"：**三层都可能咬**（HS-S-1 咬链条、HS-EX-5 咬
        # 重生），而一个用例只证得动一件事——所以下面按层各试一次反证，
        # 谁过就算谁咬到了。每多一层就多一次原版实跑，所以顺序按"最常咬到的"
        # 排在前面（先环境、再链条、最后重生）。
        layers = []
        if core(res_on) != core(res_off):
            layers.append("environment")
        if core(res_on) != core(res_nopile):
            layers.append("pile")
        if core(res_on) != core(res_noreborn):
            layers.append("reborn")
        if not layers:
            continue
        for layer in layers:
            if go is not None:
                _LAST_CONTROL_PROBLEMS.clear()
                if not _has_negative_control(stage, squad, pick, go, layer):
                    continue
            return pick, res_on, layer
    return None, None, None


def _has_negative_control(stage, squad, cells, go, layer: str = "") -> bool:
    """这一趟的规格在 Go 那边摘掉本层数据后，判决会不会变（见 `pick_biting_cells`）。"""
    spec, _, _ = run_py(stage, squad, CALC, spec_out=True, cells=cells)
    if spec["unsupported"]:
        return False
    try:
        base = go.sim(spec)
    except RuntimeError:
        return False
    problems = negative_controls(go, spec, base, layer=layer)
    if problems:
        _LAST_CONTROL_PROBLEMS[:] = problems
    return not problems


#: 最近一次反证不成立的原因（只为把 ⊘ 的措辞说准：是"没走到"还是"反证不过"）。
_LAST_CONTROL_PROBLEMS: list[str] = []


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


#: 受控重生用例：把「瘴」的血按**同一个数**调低，两边收到同一份规格。
#:
#: 为什么需要它：真关卡里走到"重生"那段要求**打得死瘴**（15000 血、400 防），而现有
#: 编队×落位下伤害只有三五千、瘴全程满血；本工具给每个人摆的是候选格里的第 i 个，
#: 而候选格按地图顺序排——除头一格，其余都在路线之外（实测加人到 5 个，伤害一字不变）。
#: 要真打，得有解算器给出的作业。在那之前，这条用例证的是**那段代码的逐位一致**：
#: 敌人血少 → 会倒下 → 会进重生窗口 → 会归来 → 击杀数只能算 1 次。
#:
#: ⚠ 它**不是**这一关真实判决的证据，读数时别混。所以在输出里单独成行、写明"受控"。
REBORN_CASE = dict(stage="HS-8", weaken_reborn=1500.0)

#: 受控用例让解算器先找一份作业时限定的人选（**只影响找作业**，不影响判决口径）。
#: 名册本身是个人数据，不进仓库：这一条要用 `--box <名册>` 才跑。
REBORN_TEAM = "史尔特尔,能天使,阿米娅,星熊,闪灵,夜莺,塞雷娅,银灰,白面鸮,凯尔希"


def _with_max_hp(e, hp):
    """把一份敌人数值的血改掉（原对象不动）。"""
    try:
        return dataclasses.replace(e, max_hp=float(hp))
    except Exception:                                         # noqa: BLE001
        clone = copy.copy(e)
        object.__setattr__(clone, "max_hp", float(hp))
        return clone


def weakened_lib(stage, hp):
    """`lib_get` 的变体：会把**会重生**的敌人血量改成 `hp`（其余不动）。"""
    base = lib_get(stage)

    def get(key, level):
        e = base(key, level)
        if getattr(e, "reborn_count", 0):
            e = _with_max_hp(e, hp)
        return e

    return get


def _reborn_pass(exe, src, box=None) -> int:
    """受控重生用例：**真作业 + 把「瘴」的血按同一个数调低**，走两条引擎对拍。

    返回失败条数（0 = 通过；`None` 语义上不在这里——跳过由调用方报）。

    为什么非得这么绕（每一步都是量出来的）：

    1. **真作业**。本工具自己那套 `plan_for` 把第 i 个人摆在候选格里的第 i 个，
       而候选格按地图顺序排——除头一格，其余都在路线之外：实测 HS-8 加到 5 个人
       伤害一字不变，逐格扫 50 格 × 四个朝向没有一格能碰到「瘴」。也就是说，
       "打到瘴"不是调参能凑出来的，要一份解算器给的作业。
    2. **走 Verifier 而不是手搓 sim**。`Verifier` 默认接**真实攻击范围表**；
       本工具早先手搓的 `BattleSimulator` 没接，范围退化，落位普遍接不到人。
    3. **受控血量**。瘴 15000 血／400 防，现有名册与解算器在 HS-7／HS-8／HS-MO-1
       上都撑不到打死它（解算器到不了三星，最好一次 3 杀 3 漏 73s）。于是把
       **会重生的敌人**血量按同一个数调低——**两边收到同一份规格**，公平；证的
       是那段代码的逐位一致，**不是**这一关的真实判决。所以输出里写明"受控"。

    三件事一起报：① 关掉原版 `_reborn_tick` 判决必须变（咬到）；② Go 与原版逐项
    一致；③ Go 侧确实记下了重生事件（"这条路被走过"的直接证据）。
    """
    case = REBORN_CASE
    code, hp = case["stage"], case["weaken_reborn"]
    label = f"{code}（受控：瘴血量 → {hp:.0f}，两边同规格）"
    if not box or not pathlib.Path(box).exists():
        # ⚠ 跳过**不算通过**：说清楚缺什么，别让一行 ⚠ 被读成绿灯。
        print(f"⚠ {label}：没有名册（`--box`），这一条**没跑**——不计入通过数")
        return 0
    plan_path = pathlib.Path("out") / "mech_parity_reborn_plan.json"
    if not plan_path.exists():
        level_id = load_stage(code, source=src).level_id
        plan_path.parent.mkdir(exist_ok=True)
        print(f"   受控用例要先解一份真作业（{level_id}），可能要几分钟……")
        r = subprocess.run(
            [sys.executable, "-m", "ak_tactic", "search", level_id,
             "--box", box, "--team", REBORN_TEAM, "--max-ops", "8",
             "--save-plan", str(plan_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if not plan_path.exists():
            print(f"❌ {label}：解算器没给出作业（退出码 {r.returncode}），"
                  f"这一条跑不了——不是通过")
            return 1

    plan = Plan.load(plan_path)
    roster = Roster.from_json(box)
    orig_get = EnemyLibrary.get

    def weakened(self, key, level=None, *a, **kw):
        e = orig_get(self, key, level, *a, **kw)
        if getattr(e, "reborn_count", 0):
            e = _with_max_hp(e, hp)
        return e

    def key(res):
        return (getattr(res, "stars", None), getattr(res, "kills", None),
                getattr(res, "leaks", None),
                round(getattr(res, "elapsed", 0.0), 6),
                round(getattr(res, "damage_dealt", 0.0), 6))

    EnemyLibrary.get = weakened
    try:
        py_on = Verifier(source=src).run(plan, roster=roster)
        orig_tick = BattleSimulator._reborn_tick
        BattleSimulator._reborn_tick = lambda self, t: None
        try:
            py_off = Verifier(source=src).run(plan, roster=roster)
        finally:
            BattleSimulator._reborn_tick = orig_tick
        go_res = GoVerifier(source=src).run(plan, roster=roster)
    except Exception as exc:                                  # noqa: BLE001
        print(f"❌ {label}：跑不起来 {type(exc).__name__}: {exc}")
        return 1
    finally:
        EnemyLibrary.get = orig_get

    bad = 0
    if key(py_on) == key(py_off):
        print(f"❌ {label}：关掉重生之后判决一字不变——这一段还是没跑到"
              f"（那条用例证明不了它）")
        return 1
    print(f"✅ {label}：真作业 {len(plan.deploys)} 手；"
          f"原版开重生 {key(py_on)} → 关重生 {key(py_off)}（**击杀数差 1** = 那只"
          f"倒下进窗口、既不算活也不算死）；Go {key(go_res)}")
    if key(go_res) != key(py_on):
        print(f"❌ {label}：Go 与原版不一致（见上两行）")
        bad += 1
    got = go_res.result if isinstance(getattr(go_res, "result", None), dict) else {}
    reborn = [e for e in (got.get("events") or []) if e.get("kind") == "reborn"]
    if not reborn:
        print(f"❌ {label}：Go 侧一次重生都没记到——那条路没被走过")
        bad += 1
    else:
        who = ", ".join(f"{e.get('who')}@{e.get('t'):.2f}s" for e in reborn[:3])
        print(f"   Go 侧重重生事件 {len(reborn)} 次：{who}")
    return bad


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
    #: `--box <名册>` 只给**受控重生用例**用：它要先让解算器找一份真作业。
    #: 名册是个人数据、不进仓库，所以缺了就如实报"这一条没跑"，不算通过。
    box = ""
    argv = sys.argv[1:]
    for i, a in enumerate(argv):
        if a == "--box" and i + 1 < len(argv):
            box = argv[i + 1]
        elif a.startswith("--box="):
            box = a.split("=", 1)[1]
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
            cells, res_on_probe, layer = pick_biting_cells(stage, squad, CALC, go)
            if cells is None:
                why = "；".join(_LAST_CONTROL_PROBLEMS) or (
                    "试遍了可部署格：三层对照（环境 / 天桩链 / 重生）判决都一字不变")
                print(f"⊘ {label}：{why}——不计入通过数")
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
            # `allow_devices` 是**要带证据打开**的口子：先实测"**只关装置运行期**
            # （建成/进入触发/被拆还原、天桩链）、保留开场断田几何"判决一字不变，
            # 通过了才敢让 Go 那边只挂几何。不实测就传 True，等于把"装置运行期
            # 与天桩链还没移植"这件事藏起来。
            #
            # ⚠ 这条门槛在**天桩链移植之后**改了口径（原来一律要求"关掉不变"）：
            # 链条现在真的接线了，所以"有影响"本身不再是拦路的理由，而是变成了
            # **必须带着证据**的理由——有影响就要求规格里真的带着天桩模板，
            # 然后由下面的逐项对拍来判决。少了这一条，HS-S-1 那种"胜负有影响、
            # 规格却没带链条"的情形会被静默放行（判决自然对不上，但报错会指向
            # 别处）；而"有影响 + 规格带链条 + 对拍一致"才是我们要的证据。
            _, res_nodev = run_py(stage, squad, CALC, drop_device_runtime=True,
                                  cells=cells)
            dev_key = tuple(getattr(res_nodev, k) for k in key)
            if dev_key != tuple(on):
                piles = [d for d in (spec.get("mech_config", {})
                                     .get("huai_shu_li.farmland", {})
                                     .get("devices", []))
                         if d.get("kind") == "pile"]
                if not piles:
                    print(f"❌ {label}：装置运行期/天桩链**对判决有影响**"
                          f"（只关它们后 {dev_key} ≠ {tuple(on)}），而规格里"
                          f"一个天桩模板都没带——那层没接线，判决必然对不上")
                    bad += 1
                    continue
                print(f"   ↳ 这一关的装置/天桩链对判决**有影响**"
                      f"（关掉后 {dev_key} ≠ {tuple(on)}），规格已带 {len(piles)} "
                      f"个天桩模板 → 交给下面的逐项对拍")
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
            weak_controls = negative_controls(go, spec, verdict, layer=layer)
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
    bad += _reborn_pass(exe, SRC, box)
    return 0 if bad == 0 else 1


#: 数据源与计算器在 `main` 里惰性建（没同步数据的机器上，import 本文件不该炸）。
SRC = None
LIB = None
CALC = OperatorCalculator()

if __name__ == "__main__":
    raise SystemExit(main())
