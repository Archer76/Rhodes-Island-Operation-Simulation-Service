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
    sim_nd._devices = []
    r_nd = sim_nd.run()
    dev_ok = (r_nd.kills, r_nd.leaks, round(r_nd.elapsed, 6)) == (
        res.kills, res.leaks, round(res.elapsed, 6))
    spec = build_spec(fresh(), stage_label=code, allow_devices=dev_ok,
                      allow_skills=True)
    if spec["unsupported"]:
        return False, f"规格里有不支持项：{spec['unsupported']}"
    with Simgo(EXE) as gosim:
        go = gosim.sim(spec)
    got = compare(res, go)
    head = (f"{res.kills}杀/{res.leaks}漏/{res.elapsed:.1f}s "
            f"伤害 {res.damage_dealt:,.0f}；Go {go['sim_ms']:.1f}ms")
    return got["ok"], head if got["ok"] else f"{head} 差异 {got['diff']}"


if __name__ == "__main__":
    sys.exit(main())
