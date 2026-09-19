# -*- coding: utf-8 -*-
"""Go 版模拟器（`rios-sim/`）的门口自检。

三件事：**能不能编译、协议版本对不对、出错时会不会说假话**；再加一组
**对拍**——同一场战斗在 Python 原版与 Go 版上各跑一遍，逐项比判决。

## 对拍用例怎么挑

* 只收**最小版本覆盖范围内**的局：常规关卡、无技能生效、装置实测无影响
  （`build_spec` 会把这些写成 `unsupported` 拒跑，对拍台一条都不跳过——
  跳过的用例等于没测）；
* 部署时刻按真实费用算，避免"两边都因付不起而没放人"这种假绿；
* 用例数刻意压小（3 关 × 1 阵容），这个文件要能常在 CI 心态下跑；全量对拍
  在 `_proto/simgo_parity.py`（12 关 × 2 阵容）。

## 本机没装 Go / 没有数据库时**跳过**，不是失败

克隆仓库的人不该被一个新组件拦在门外。判据同 `ak_tactic` 的其它工具：
`shutil.which("go")` 与 `go env` 都活着才算装了。

用法：`python tools/check_simgo.py`
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import subprocess
import sys
from ak_tactic.frontend.inputs import SpecInputs

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIMDIR = ROOT / "rios-sim"
EXE = SIMDIR / ("rios-sim.exe" if os.name == "nt" else "rios-sim")

#: 对拍用例：`(关卡, 干员, 练度)`。三关的敌人形态不同（直路/多路线/远程敌人），
#: 单人阵容能把"出手计时器"与"索敌"两条细节单独逼出来。
PARITY_CASES = [
    ("1-7", "char_002_amiya", dict(elite=2, level=80, trust=100, potential=6)),
    ("0-1", "char_002_amiya", dict(elite=2, level=80, trust=100, potential=6)),
    ("2-1", "char_102_texas", dict(elite=2, level=1)),
]

#: 技能契约那一组检查用的用例：`(关卡, 干员, 练度, 技能槽, 技能等级, 专精)`。
#: 挑的是**窄子集里的技能**（只改攻速、不改范围/不加状态），它的作用不是"证明
#: 技能都对"，而是把"送过界的规格长什么样"钉成一份可回归的样本。
SKILL_CASE = ("TR-1", "char_002_amiya", dict(elite=2, level=80, trust=100,
                                             potential=6), 1, 7, 3)

_PASSED = 0
_FAILED: list[str] = []
_SKIPPED: list[str] = []


def check(what: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {what}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(what)
        print(f"  [FAIL] {what}" + (f"   {detail}" if detail else ""))


def skip(what: str, why: str) -> None:
    _SKIPPED.append(what)
    print(f"  [skip] {what}   {why}")


def _env() -> dict:
    env = dict(os.environ)
    # 本机 Go 是 1.26；`GOTOOLCHAIN=local` 挡住"发现工具链版本不够就去联网下一份"
    # 的默认行为——自检不该在背后下载东西。
    env["GOTOOLCHAIN"] = "local"
    return env


def _run(args: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=str(SIMDIR), env=_env(),
                          capture_output=True, text=True,
                          encoding="utf-8", errors="replace", **kw)


def _proto(args: list[str], stdin: str) -> tuple[int, list[dict], str]:
    """跑一次二进制，把 stdout 的 JSON 行解出来。"""
    p = subprocess.run([str(EXE), *args], input=stdin, capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    rows: list[dict] = []
    for line in (p.stdout or "").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            rows.append({"__bad_json__": line})
    return p.returncode, rows, p.stderr or ""


def main() -> int:
    print("检查 Go 版模拟器（rios-sim/）")

    if shutil.which("go") is None:
        skip("rios-sim 全部检查", "本机没装 Go（新组件，不拦别人）")
        print(f"\n通过 {_PASSED} 项，跳过 {len(_SKIPPED)} 项。")
        return 0

    check("rios-sim 目录在（go.mod / main.go 都在）",
          (SIMDIR / "go.mod").is_file() and (SIMDIR / "main.go").is_file())
    if not (SIMDIR / "go.mod").is_file():
        print("\nrios-sim 目录不完整，后面的检查没有意义。")
        return 1

    ver = _run(["go", "mod", "edit", "-json"])
    mod = ver.stdout or ""
    check("go.mod 用的是本机 Go 能编的版本",
          ver.returncode == 0 and "rios-sim" in mod,
          mod.splitlines()[1].strip() if mod.count("\n") > 0 else mod[:40])

    # 构建产物不入库：它是可再生的（.gitignore 已挡）
    gi = (ROOT / ".gitignore").read_text(encoding="utf-8")
    check("构建产物被 .gitignore 挡住（可再生的东西不入库）",
          "rios-sim/rios-sim" in gi or "rios-sim/*.exe" in gi, gi[:0])

    b = _run(["go", "build", "-o", EXE.name, "."])
    check("go build 能编译出二进制", b.returncode == 0 and EXE.is_file(),
          (b.stderr or "").strip()[-120:])
    if not EXE.is_file():
        print(f"\n通过 {_PASSED} 项，失败 {len(_FAILED)} 项。")
        return 1

    vet = _run(["go", "vet", "./..."])
    check("go vet 干净", vet.returncode == 0, (vet.stderr or "").strip()[-120:])

    # ---- 协议：ping / 未知命令 / 坏 JSON / 未实现的 sim
    rc, rows, _ = _proto([], '{"id":1,"cmd":"ping"}\n')
    ping = rows[0] if rows else {}
    check("ping 回一行合法 JSON、且 ok:true",
          rc == 0 and len(rows) == 1 and ping.get("ok") is True, json.dumps(ping)[:90])
    check("ping 带回协议版本（调用方要先核对它）",
          isinstance(ping.get("pong", {}).get("version"), int),
          str(ping.get("pong", {}).get("version")))
    check("ping 里的版本与本文件认的一致（v1）",
          ping.get("pong", {}).get("version") == 1)

    # ---- 关卡特有机制层（mech 包）：按需取用、取不到就拒跑
    mechs = ping.get("pong", {}).get("mechanisms")
    check("ping 报出本二进制编译进来的机制名单（Python 据此判断能不能交给 Go 跑）",
          isinstance(mechs, list), f"{mechs!r}")

    rc, rows, _ = _proto([], '{"id":9,"cmd":"sim","spec":{"fps":30,'
                             '"mechanisms":["没有这个机制"]}}\n')
    check("点名了一个没有的机制 → **拒跑**，不是静默忽略"
          "（少挂一个机制与本来没这机制在判决上分不开）",
          len(rows) == 1 and rows[0].get("ok") is False
          and "没有这个机制" in rows[0].get("error", "")
          and "verdict" not in rows[0], json.dumps(rows[:1])[:130])

    rc, rows, _ = _proto([], '{"id":10,"cmd":"sim","spec":{"fps":30,'
                              '"mechanisms":[],"max_time":1}}\n')
    check("机制名单空着时照常跑（空层对判决的影响必须是零）",
          len(rows) == 1 and rows[0].get("ok") is True
          and "verdict" in rows[0], json.dumps(rows[:1])[:110])

    rc, rows, _ = _proto([], '{"id":2,"cmd":"nope"}\n')
    check("不认识的命令 → ok:false 并说清支持什么",
          len(rows) == 1 and rows[0].get("ok") is False
          and "ping" in rows[0].get("error", ""), json.dumps(rows[:1])[:100])

    rc, rows, _ = _proto([], 'not json\n')
    check("坏 JSON → 一行错误，不崩、不静默",
          rc == 0 and len(rows) == 1 and rows[0].get("ok") is False
          and "JSON" in rows[0].get("error", ""), json.dumps(rows[:1])[:100])

    rc, rows, _ = _proto([], '{"id":3,"cmd":"sim","spec":{}}\n')
    check("坏规格（缺 fps）→ 拒跑，绝不返回假判决",
          len(rows) == 1 and rows[0].get("ok") is False
          and "verdict" not in rows[0], json.dumps(rows[:1])[:110])

    rc, rows, _ = _proto([], json.dumps({
        "id": 4, "cmd": "sim",
        "spec": {"fps": 30, "unsupported": ["技能 ×1"]}}) + "\n")
    check("**有 unsupported 就拒跑**（缺了机制的「对齐」比「没实现」更坏）",
          len(rows) == 1 and rows[0].get("ok") is False
          and "技能" in rows[0].get("error", "")
          and "verdict" not in rows[0], json.dumps(rows[:1])[:120])

    # ---- 一批多条：应答与请求同序
    rc, rows, _ = _proto([], '{"id":1,"cmd":"ping"}\n{"id":2,"cmd":"ping"}\n'
                             '{"id":3,"cmd":"nope"}\n')
    check("一批多条按序应答（id 与请求一一对应）",
          [r.get("id") for r in rows] == [1, 2, 3], str([r.get("id") for r in rows]))

    check_parity()
    check_skill_contract()

    print(f"\n通过 {_PASSED} 项", end="")
    if _SKIPPED:
        print(f"，跳过 {len(_SKIPPED)} 项", end="")
    if _FAILED:
        print(f"，失败 {len(_FAILED)} 项：")
        for f in _FAILED:
            print(f"  - {f}")
        return 1
    print("，无失败。")
    return 0


def check_parity() -> None:
    """对拍：原版 vs Go，逐项比判决。

    这段要连数据库（`GameDataSource`），所以整段包在 try 里——取不到数据就
    **跳过**，不是失败：自检不该因为"这台机器没同步数据"而变红。
    """
    print("\n对拍：原版 Python vs rios-sim（Go）")
    sys.path.insert(0, str(ROOT))
    try:
        from ak_tactic.battle import BattleSimulator, Deployment
        from ak_tactic.battle.unit import OperatorUnit
        from ak_tactic.gamedata import (EnemyLibrary, GameDataSource,
                                        load_stage)
        from ak_tactic.operator import OperatorCalculator
        from ak_tactic.simgo import Simgo, build_spec, compare
    except Exception as exc:                                        # noqa: BLE001
        skip("对拍", f"导入失败：{exc.__class__.__name__}: {exc}")
        return
    try:
        src = GameDataSource()
        lib = EnemyLibrary(source=src)
        calc = OperatorCalculator()
        load_stage(PARITY_CASES[0][0], source=src)
    except Exception as exc:                                        # noqa: BLE001
        skip("对拍", f"取不到本地数据（{exc.__class__.__name__}）")
        return

    green = 0
    for code, char_id, kw in PARITY_CASES:
        try:
            ok, detail = _parity_one(src, lib, calc, code, char_id, kw,
                                     BattleSimulator, Deployment, OperatorUnit,
                                     load_stage, Simgo, build_spec, compare)
        except Exception as exc:                                    # noqa: BLE001
            ok, detail = False, f"{exc.__class__.__name__}: {exc}"
        if ok:
            green += 1
        check(f"对拍 {code} {kw.get('level')}级：判决逐项一致", ok, detail)
    if green == len(PARITY_CASES):
        print(f"  （{green} 例全绿：won/击杀/漏怪/部署/阵亡/耗时/伤害/漏怪明细）")


def _parity_one(src, lib, calc, code, char_id, kw, BattleSimulator, Deployment,
                OperatorUnit, load_stage, Simgo, build_spec, compare):
    """一场对拍。返回 `(是否一致, 一句话摘要)`。"""
    stage = load_stage(code, source=src)
    stats = calc.stats(char_id, **kw).total
    unit = OperatorUnit(
        name=calc.stats(char_id, **kw).name, char_id=char_id,
        elite=kw.get("elite", 2), max_hp=float(stats["maxHp"]),
        atk=float(stats["atk"]), defense=float(stats["def"]),
        res=float(stats.get("magicResistance", 0) or 0),
        attack_interval=float(stats.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(stats.get("blockCnt", 0) or 0),
        deploy_cost=int(stats.get("cost", 0) or 0),
        attack_speed=float(stats.get("attackSpeed", 100) or 100))
    cells: list[tuple[int, int]] = []
    for group in ("melee_spots", "ranged_spots"):
        for cell in getattr(stage.map, group, []) or []:
            pos = (int(cell[0]), int(cell[1]))
            if pos not in cells:
                cells.append(pos)
    if not cells:
        return False, "这一关没有可部署格"
    # 按真实费用排时刻 + 1 秒余量（与 verify.py 同一个模型）
    rate = float(stage.options.cost_increase_time)
    need = max(0.0, float(unit.deploy_cost) - float(stage.options.initial_cost))
    at = need * rate + (1.0 if need else 0.0)

    def fresh():
        s = BattleSimulator(stage, enemy_at=lib.get)
        s.plan(Deployment(at, unit, cells[0], "Right"))
        return s

    res = fresh().run()
    if getattr(res, "skill_activations", 0):
        return False, "原版开了技能（最小实现没有技能，用例不该带技能）"
    sim_nd = fresh()
    # "装置运行期对本局无影响"的证据：**只关** `_device_tick`（建成/进入触发/被拆还原）
    # 与 `_pile_tick`（天桩链），**不碰** `_devices`——开场的断田几何是构造时算进
    # `sim.farmland` 的，Go 的规格带着它。早先写 `sim_nd._devices = []` 是问错了问题：
    # 那一清连几何一起摘了，于是把"Go 已经有几何"的关也判成"装置有影响"。
    sim_nd._device_tick = lambda dt, t: None
    sim_nd._pile_tick = lambda dt, t: None
    r_nd = sim_nd.run()
    dev_ok = (r_nd.kills, r_nd.leaks, round(r_nd.elapsed, 6)) == (
        res.kills, res.leaks, round(res.elapsed, 6))
    spec = build_spec(SpecInputs.from_sim(fresh()), stage_label=code, allow_devices=dev_ok,
                      allow_skills=True)
    if spec["unsupported"]:
        return False, f"规格里有不支持项：{spec['unsupported']}"
    with Simgo(EXE) as gosim:
        go = gosim.sim(spec)
    got = compare(res, go)
    head = (f"{res.kills}杀/{res.leaks}漏/{res.elapsed:.1f}s "
            f"伤害 {res.damage_dealt:,.0f}；Go {go['sim_ms']:.1f}ms")
    return got["ok"], head if got["ok"] else f"{head} 差异 {got['diff']}"


def _walk_none(node, path: str = "spec") -> list[str]:
    """规格里所有 `None` 的位置。

    **这不是洁癖，是一条咬过人的契约**：Go 那边的数值字段是 `float64`，
    JSON 的 `null` 到了那边就是 **0**，而 0 在数值位置上全是合法值
    （0 倍率 = 打不死人、0 秒 = 瞬发、0 间隔 = 每帧出手），没有一种能在
    下游看出来。实测被 `final_hit_scale` 咬过一口：Python 送 `null`，
    Go 把"单发攻击的最后一击倍率"当成 0，整局只表现为"这名干员打不死人"。

    所以可选数值的规矩是：**没有就整个键不出现**（Go 侧用指针接）。
    """
    out: list[str] = []
    if node is None:
        out.append(path)
    elif isinstance(node, dict):
        for k, v in node.items():
            out += _walk_none(v, f"{path}.{k}")
    elif isinstance(node, (list, tuple)):
        for i, v in enumerate(node):
            out += _walk_none(v, f"{path}[{i}]")
    return out


def check_skill_contract() -> None:
    """技能那一层送过界的**契约**（不跑战斗，只看生成出来的规格）。"""
    print("\n技能规格契约（状态机参数 + 两套数值）")
    sys.path.insert(0, str(ROOT))
    try:
        from ak_tactic.battle import BattleSimulator, Deployment
        from ak_tactic.battle.unit import OperatorUnit
        from ak_tactic.gamedata import (EnemyLibrary, GameDataSource,
                                        load_stage)
        from ak_tactic.operator import OperatorCalculator, SkillBook
        from ak_tactic.simgo import build_spec
        from ak_tactic.simgo import skills as sk_mod
    except Exception as exc:                                        # noqa: BLE001
        skip("技能规格契约", f"导入失败：{exc.__class__.__name__}: {exc}")
        return
    try:
        src = GameDataSource()
        lib = EnemyLibrary(source=src)
        calc = OperatorCalculator()
        book = SkillBook()
        stage = load_stage(SKILL_CASE[0], source=src)
    except Exception as exc:                                        # noqa: BLE001
        skip("技能规格契约", f"取不到本地数据（{exc.__class__.__name__}）")
        return

    code, char_id, kw, slot, slevel, mastery = SKILL_CASE
    stats = calc.stats(char_id, **kw)
    cells: list[tuple[int, int]] = []
    for group in ("melee_spots", "ranged_spots"):
        for cell in getattr(stage.map, group, []) or []:
            pos = (int(cell[0]), int(cell[1]))
            if pos not in cells:
                cells.append(pos)
    if not cells:
        skip("技能规格契约", "这一关没有可部署格")
        return

    def make(skill):
        u = OperatorUnit(
            name=stats.name, char_id=char_id, elite=kw.get("elite", 2),
            max_hp=float(stats.total["maxHp"]), atk=float(stats.total["atk"]),
            defense=float(stats.total["def"]),
            res=float(stats.total.get("magicResistance", 0) or 0),
            attack_interval=float(stats.total.get("baseAttackTime", 1.0) or 1.0),
            block_cnt=int(stats.total.get("blockCnt", 0) or 0),
            deploy_cost=int(stats.total.get("cost", 0) or 0),
            attack_speed=float(stats.total.get("attackSpeed", 100) or 100))
        s = BattleSimulator(stage, enemy_at=lib.get, skill_book=book)
        s.plan(Deployment(5.0, u, cells[0], "Right", skill=skill,
                          auto_skill=True))
        return s

    lv = next(x for x in book.for_operator(char_id) if x.slot == slot)
    lv = lv.level(slevel, mastery)
    spec = build_spec(SpecInputs.from_sim(make(lv)), stage_label=code, allow_skills=True)
    op = (spec.get("operators") or [{}])[0]

    check("技能落在已移植子集里就放行（这一例是窄子集内的技能）",
          not spec["unsupported"] and "skill" in op and "active" in op,
          str(spec["unsupported"])[:130])
    if "skill" not in op:
        return
    need = {"sp_type", "passive", "auto_trigger", "sp_cost", "init_sp",
            "increment", "max_charge", "duration", "infinite", "ammo",
            "once_per_battle", "cost_gain"}
    check("状态机参数齐（Go 只跑状态机，缺一项就是静默少一条规则）",
          need <= set(op["skill"]), str(sorted(need - set(op["skill"]))))
    _check_duration_rule(book)
    act = op.get("active") or {}
    check("技能期间的数值是**一整套**（不是「哪几项改了」）",
          {"atk", "def", "res", "interval", "damage_type", "max_target",
           "atk_scale", "hit_count"} <= set(act), str(sorted(act)))
    check("部署必定显式带 auto_skill（Go 的零值是 False，原版默认是 True）",
          all("auto_skill" in d for d in spec["deploys"]),
          str([d for d in spec["deploys"] if "auto_skill" not in d])[:80])

    # 咬过人的那一口：可选数值送 None → Go 收到 0。整份规格不许有 None。
    bad = _walk_none(spec)
    check("规格里**没有一处 None**（null 到 Go 就是 0，而 0 全是合法数值）",
          not bad, "、".join(bad[:5]))

    # 反向守卫：**白名单必须"逐字段"成立**，不是"我记得的那几个"
    #
    # 做法是拿真技能的效果对象，把一个**在白名单外、且真的存在**的字段改掉，
    # 看扫描认不认。改 `self_stun`（技能自我眩晕）而不改一个不存在的属性：
    # 扫描是 `dataclasses.fields()` 驱动的，凭空塞一个类外属性它根本看不到
    # ——用那种手法写出来的"守卫"永远绿，等于没写。
    stray = _stray_reason()
    check("把白名单外的真字段改掉 → 拒跑（新字段会自动落进不支持）",
          stray is not None and "self_stun" in stray, str(stray))


def _check_duration_rule(book) -> None:
    """持续时间那一条口径：**无限**的三种来路都必须报成 `infinite`。

    原版判的是 `SkillLevel.effective_duration is None`，它有三种来路：
    弹药类（打光才结束）、描述里明写「持续时间无限」、durationType 就是
    INFINITE。只看 `sk.infinite` 会把**弹药类读成 0 秒**（＝瞬发，开启那一帧
    就结束），而且不报错、不崩，只表现为"开了技能但伤害没变"。

    这一段不建舞台、不跑战斗：只需干员对象与技能等级，所以很快。
    """
    from ak_tactic.battle.unit import OperatorUnit
    from ak_tactic.simgo import skills as sk_mod

    class _Sim:
        effect_source = "blackboard"

    class _Dep:
        operator = None

    def state_of(lv, cid):
        op = OperatorUnit(name=cid, char_id=cid, elite=2, max_hp=1.0, atk=1.0,
                          defense=0.0, res=0.0, attack_interval=1.0,
                          block_cnt=1, deploy_cost=0)
        op.skill = lv
        d = _Dep()
        d.operator = op
        return sk_mod.skill_spec(_Sim(), d)[0]

    # 弹药类技能从**库里查一个**（一条 SQL），不要靠遍历名册去碰运气：
    # 遍遍历在自检里太慢，而"没扫到"与"真没有"是两件事。
    ammo = None
    try:
        import sqlite3
        row = sqlite3.connect(ROOT / "data" / "akdb.sqlite").execute(
            "select os.char_id, os.slot from operator_skill os "
            "join skill_level sl on sl.skill_id = os.skill_id "
            "where sl.duration_type = 'AMMO' order by os.char_id limit 1"
        ).fetchone()
        if row:
            slot0 = next(s for s in book.for_operator(row[0]) if s.slot == row[1])
            ammo = (row[0], slot0.level(7, 0))
    except Exception:                                              # noqa: BLE001
        ammo = None
    if ammo is None:
        skip("弹药类的持续时间口径", "库里查不到弹药类技能（或数据不可用）")
    else:
        st = state_of(ammo[1], ammo[0]) or {}
        check("弹药类技能报成「无限持续 + 有弹药数」（不是 0 秒瞬发）",
              st.get("infinite") is True and int(st.get("ammo") or 0) > 0,
              f"{ammo[0]} infinite={st.get('infinite')} ammo={st.get('ammo')}")

    # 反向：有真实持续时间的技能不许被报成无限
    try:
        lv = next(s for s in book.for_operator("char_002_amiya")
                  if s.slot == 1).level(7, 3)
        st = state_of(lv, "char_002_amiya") or {}
        check("有限持续时间的技能报成 `infinite=False`（反向守卫）",
              st.get("infinite") is False and float(st.get("duration") or 0) > 0,
              f"infinite={st.get('infinite')} duration={st.get('duration')}")
    except Exception as exc:                                        # noqa: BLE001
        skip("有限持续时间的反向守卫", f"{exc.__class__.__name__}: {exc}")


def _stray_reason() -> str | None:
    """改一个白名单外的真字段，返回 `port_reasons` 给出的理由。"""
    from ak_tactic.simgo import skills as sk_mod

    class _Skill:
        effects = None
        range_id = None
        duration_type = "NONE"
        description = ""

    class _Sim:
        effect_source = "blackboard"

    eff = sk_mod_effects()
    eff.self_stun = 5.0
    op = type("_Op", (), {})()
    op.skill = _Skill()
    op.skill.effects = eff
    return "、".join(sk_mod.port_reasons(_Sim(), op))


def sk_mod_effects():
    from ak_tactic.operator.skill import SkillEffects

    return SkillEffects()


if __name__ == "__main__":
    sys.exit(main())
