#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：`build_spec` 的 `mechanisms` 与 `mech_config` 两个顶层键。

## 对的是什么

`spec.py:1220-1229` 的组装：

    mechanisms  = list(dict.fromkeys([*mech.names_for(inp), *mechanisms]))
    mech_config = {FARMLAND_ID: farmland_spec(inp)}   ← 本判据
                  {SNOW_ID:     snow_mech_spec(inp)}  ← 未搬，见第五节

## 口径（判据与实现必须是同一个）

Go 的 `mechspec` 命令**不吃计划**，所以期望值也在**同一个口径**上取：
`SpecInputs.from_stage(stage, …, schedule=Schedule())` —— 空排程。

★ 这不是把困难绕过去：`names_for` 的两条判据里只有**第 ② 条**（雪）按排程走，
而它在空排程下恒为「没有」。为了证明这个口径**没有把别的东西一起丢掉**，
第六节拿 24 份夹具的**生产规格**（`from_sim`，带计划）逐关对了一遍：
`mech_config[FARMLAND_ID]` 在两个口径下必须**逐字段相同**（田地与计划无关），
`mechanisms` 的差必须**恰好**是 `snow.field`——多一个少一个都判红。

## 两个坑（都在判据里显式处理）

1. **`groups` 这个列表的次序复刻不了**：Python 的种子是 `todo.pop()`（从一个
   `set` 里弹），顺序由 CPython 的集合布局决定。判据**按格集合口径比**
   （两边各自按「第一个格」排序后逐组比），并把**两侧原始顺序不同的关数**
   当成一个读数印出来——不是用容差把它平均掉。
   组内格子的顺序是 `sorted()`，两侧都必须逐位相同。
2. **`_seed()` 那处歧义**（`environment.py:369-393`，原文自陈「待实机校正」）：
   照原版取**逐格**。判据不去判它哪种读法对，只判「Go 与原版一致」；
   差别是实的（逐格给 20、整片给 320），所以实现文件里把这段理由照抄了。

用法:
    python tools\\check_mechspec_go.py
    python tools\\check_mechspec_go.py --mutate
"""
from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = FIXDIR / "roster_max_modelled.json"

FARMLAND_ID = "huai_shu_li.farmland"
SNOW_ID = "snow.field"

#: Go 报的**未搬**线（与 `rios-sim/mechspec.go::mechUnportedLines` 同源，双向守卫）。
UNPORTED = ("farmland.devices[].child", "snow.field")

#: **本命令口径下**结构不可达的线：名字 ＋ 为什么。
#: 判据第五节每次现算可达性——非 0 即红（那时说明口径变了，登记要重写）。
STRUCTURAL_ZERO = {
    SNOW_ID: "雪按**排程**判（`snow_spec` 读 `d.talents`），而本命令不吃计划 ⇒ "
             "空排程下恒无雪；判据每次拿同一口径现算并断言为 0",
}

#: 田地规格里那些「纯常量」的字段（`environment.py:80-102` 的六个 ＋ 三个泵站量），
#: 单独列出来是为了让失配信息能指名到字段。
CONST_KEYS = ("cache_interval", "cache_per_tick", "actual_interval",
              "actual_per_divisor", "actual_base_step", "pollut_min", "pollut_max",
              "pump_rate", "pump_range", "pump_range_bonus")
SCALAR_KEYS = ("kind", "width", "height", "difficulty")
PARAM_KEYS = ("basic_damage", "damage_ratio", "first_basic_damage",
              "first_damage_ratio", "hp_recovery_per_sec")


# ---------------------------------------------------------------- 两侧读数

def go_mechspec_batch(levels: list[str]) -> dict[str, dict]:
    """**一条进程**批量问（协议本来就是「一次进程、批量作业」）。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    lines = [json.dumps({"id": i + 1, "cmd": "mechspec", "level": lv})
             for i, lv in enumerate(levels)]
    p = subprocess.run([GO_BIN], input=("\n".join(lines) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    out: dict[str, dict] = {}
    rows = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if len(rows) != len(levels):
        raise SystemExit("Go 回了 %d 行、问了 %d 关" % (len(rows), len(levels)))
    for lv, row in zip(levels, rows):
        resp = json.loads(row)
        if not resp.get("ok"):
            raise SystemExit("Go 回 error（%s）：%s" % (lv, resp.get("error")))
        out[lv] = resp["mech_spec"]
    return out


def go_mechspec_raw(req: dict) -> tuple[bool, dict]:
    """**如实**回传 `(ok, 应答)` —— 给「必须失败」那条控制组用。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    p = subprocess.run([GO_BIN], input=(json.dumps(req) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    rows = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not rows:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(rows[0])
    return bool(resp.get("ok")), resp


def py_expected(level: str) -> tuple[list[str], dict]:
    """**权威**：`build_spec` 自己，在「关卡 ＋ 空排程」这个口径上。

    ⚠ 不手抄组装逻辑（那会变成第二份实现）：直接调生产函数，取它那两个键。
    """
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.frontend.schedule import Schedule
    from ak_tactic.gamedata.enemy import EnemyLibrary
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import build_spec

    lib = EnemyLibrary()
    stage = load_stage(level)
    inp = SpecInputs.from_stage(stage, enemy_at=lib.get,
                                species_provider=lib.species_of,
                                schedule=Schedule())
    spec = build_spec(inp)
    return list(spec["mechanisms"]), dict(spec["mech_config"])


# ---------------------------------------------------------------- 比较

def canon_groups(groups: list) -> list:
    """按「组内格子列表」排序——这一层是**集合口径**（顺序复刻不了，见文件头坑①）。

    组内格子顺序**不**在这里归一化：它两侧都该是 `sorted()`，必须逐位相同。
    """
    return sorted(groups, key=lambda g: [list(c) for c in g["cells"]])


def diff_farmland(want: dict, got: dict) -> list[str]:
    """逐字段比一份田地规格；返回失配描述（空 = 一致）。"""
    bad: list[str] = []
    for k in SCALAR_KEYS:
        if want.get(k) != got.get(k):
            bad.append("%s：期望 %r，Go %r" % (k, want.get(k), got.get(k)))
    wp, gp = want.get("params") or {}, got.get("params") or {}
    if sorted(wp) != sorted(gp):
        bad.append("params 键集不同：期望 %s，Go %s" % (sorted(wp), sorted(gp)))
    for k in PARAM_KEYS:
        if wp.get(k) != gp.get(k):
            bad.append("params.%s：期望 %r，Go %r" % (k, wp.get(k), gp.get(k)))
    for k in CONST_KEYS:
        if want.get(k) != got.get(k):
            bad.append("%s：期望 %r，Go %r" % (k, want.get(k), got.get(k)))
    if want.get("actual") != got.get("actual"):
        bad.append("actual：期望 %d 条，Go %d 条%s" % (
            len(want.get("actual") or []), len(got.get("actual") or []),
            "" if len(want.get("actual") or []) != len(got.get("actual") or [])
            else "（条数相同、内容不同）"))
    if want.get("severed") != got.get("severed"):
        bad.append("severed：期望 %r，Go %r" % (want.get("severed"), got.get("severed")))
    wg, gg = canon_groups(want.get("groups") or []), canon_groups(got.get("groups") or [])
    if len(wg) != len(gg):
        bad.append("groups 组数：期望 %d，Go %d" % (len(wg), len(gg)))
    else:
        for i, (a, b) in enumerate(zip(wg, gg)):
            if a != b:
                bad.append("groups（按格集合排序后第 %d 组）：期望 %s，Go %s"
                           % (i, json.dumps(a, ensure_ascii=False),
                              json.dumps(b, ensure_ascii=False)))
    #: devices：`child` 是**具名未搬**（天桩召唤链要 `_unit_spec` 之外的
    #: `_pile_device_spec` 模板，见第六节），其余字段逐条比。
    wd, gd = want.get("devices") or [], got.get("devices") or []
    if len(wd) != len(gd):
        bad.append("devices 条数：期望 %d，Go %d" % (len(wd), len(gd)))
    else:
        for i, (a, b) in enumerate(zip(wd, gd)):
            for k in ("kind", "key", "cell", "direction"):
                if a.get(k) != b.get(k):
                    bad.append("devices[%d].%s：期望 %r，Go %r" % (i, k, a.get(k), b.get(k)))
    return bad


def compare(levels: list[str], exp: dict, got: dict) -> tuple[list[str], dict]:
    """返回 `(问题清单, 覆盖计数)`。期望值在循环顶部**无条件**算好。"""
    problems: list[str] = []
    cov = {"关卡": 0, "有田地": 0, "无田地": 0, "多组": 0, "有 actual": 0,
           "有 severed": 0, "有 pump": 0, "有 pile": 0, "有 valve": 0,
           "groups 顺序不同": 0, "child 缺失条数": 0, "比到的字段数": 0}
    for lv in levels:
        w_mechs, w_cfg = exp[lv]           # ← 循环顶部、无条件算出
        g = got[lv]
        cov["关卡"] += 1
        if g.get("mechanisms") != w_mechs:
            problems.append("%s：mechanisms 期望 %s，Go %s"
                            % (lv, json.dumps(w_mechs, ensure_ascii=False),
                               json.dumps(g.get("mechanisms"), ensure_ascii=False)))
        if sorted(g.get("mech_config") or {}) != sorted(w_cfg):
            problems.append("%s：mech_config 键集 期望 %s，Go %s"
                            % (lv, sorted(w_cfg), sorted(g.get("mech_config") or {})))
        if not w_cfg:
            cov["无田地"] += 1
        else:
            cov["有田地"] += 1
            wf = w_cfg.get(FARMLAND_ID) or {}
            gf = (g.get("mech_config") or {}).get(FARMLAND_ID) or {}
            bad = diff_farmland(wf, gf)
            cov["比到的字段数"] += len(SCALAR_KEYS) + len(PARAM_KEYS) + len(CONST_KEYS) + 4
            for m in bad:
                problems.append("%s：%s" % (lv, m))
            if len(wf.get("groups") or []) > 1:
                cov["多组"] += 1
            if wf.get("actual"):
                cov["有 actual"] += 1
            if wf.get("severed"):
                cov["有 severed"] += 1
            kinds = [d.get("kind") for d in (wf.get("devices") or [])]
            for k in ("pump", "pile"):
                if k in kinds:
                    cov["有 %s" % k] += 1
            if len(wf.get("groups") or []) != len(gf.get("groups") or []) or \
                    [ [list(c) for c in x["cells"]] for x in (wf.get("groups") or [])] != \
                    [ [list(c) for c in x["cells"]] for x in (gf.get("groups") or [])]:
                cov["groups 顺序不同"] += 1
            wp = [d for d in (wf.get("devices") or []) if d.get("kind") == "pile"]
            gp = [d for d in (gf.get("devices") or []) if d.get("kind") == "pile"]
            for a, b in zip(wp, gp):
                if "child" in a and "child" not in b:
                    cov["child 缺失条数"] += 1
                elif ("child" in a) != ("child" in b):
                    problems.append("%s：pile 的 child 存在性不一致（期望 %s，Go %s）"
                                    % (lv, "child" in a, "child" in b))
        #: `unported` 是常量清单：两侧任一处改动都要在这里露出来。
        if sorted(g.get("unported") or []) != sorted(UNPORTED):
            problems.append("%s：unported 与判据的清单不一致\n      Go   =%s\n      判据 =%s"
                            % (lv, json.dumps(g.get("unported"), ensure_ascii=False),
                               json.dumps(sorted(UNPORTED), ensure_ascii=False)))
        #: 结构性不可达那条：**每次现算**（口径没变时它必须还是 0）。
        if g.get("scanned", {}).get("snow_fields"):
            problems.append("%s：scanned.snow_fields=%r —— 空排程口径下雪不该可达，"
                            "口径变了，STRUCTURAL_ZERO 的登记要重写"
                            % (lv, g["scanned"]["snow_fields"]))
        if "snow.field" in (w_cfg or {}):
            problems.append("%s：空排程口径下 mech_config 不该有 %s（口径变了）"
                            % (lv, SNOW_ID))
    return problems, cov


def coverage_report(cov: dict) -> list[str]:
    """每条支都要真被走到，否则那一条覆盖是零信息量的绿。"""
    need = ("关卡", "有田地", "无田地", "多组", "有 actual", "有 severed",
            "有 pump", "有 pile", "groups 顺序不同")
    bad = [("覆盖为零：%s" % k) for k in need if not cov.get(k)]
    if not cov.get("比到的字段数"):
        bad.append("一个字段都没比到 —— 判据瞎了（不是实现错）")
    return bad


# ---------------------------------------------------------------- 第五节：口径与证人

def contract_checks(levels: list[str], exp: dict, got: dict) -> list[str]:
    """口径回显 ＋「不吃计划」这条契约的两面。"""
    problems: list[str] = []
    # ① 回显：Go 必须按我要求的那一关／那一档答。
    for lv in levels[:5]:
        par = got[lv].get("params") or {}
        if par.get("level") != lv:
            problems.append("口径回显：问了 %s，Go 说 %r" % (lv, par.get("level")))
    # ② 传计划必须**具名失败**（静默忽略 = 调用方会以为规格是全的）。
    ok, resp = go_mechspec_raw({"id": 1, "cmd": "mechspec", "level": levels[0],
                                "spec": {"plan": str(FIXDIR / "hsex8.json")}})
    if ok:
        problems.append("「不吃计划」这条契约没被守住：传了 plan 却回了 ok —— "
                        "调用方会拿到一份没有雪也没有天桩链的规格却以为它是全的")
    elif "plan" not in str(resp.get("error", "")):
        problems.append("传 plan 失败了，但错误里没点到那个键：%r" % resp.get("error"))
    else:
        print("  D1 传计划 → 具名失败 ✓（%s）" % str(resp["error"])[:60])
    # ③ 难度那一档要真的下传：换个难度必须换一套 rune（四星档 vs 普通档）。
    four = [lv for lv in levels if lv.endswith("#f#")]
    if four:
        lv = four[0]
        ok2, resp2 = go_mechspec_raw({"id": 1, "cmd": "mechspec", "level": lv,
                                      "spec": {"difficulty": "FOUR_STAR"}})
        ok3, resp3 = go_mechspec_raw({"id": 1, "cmd": "mechspec", "level": lv,
                                      "spec": {"difficulty": "NORMAL"}})
        if not (ok2 and ok3):
            problems.append("四星档：Go 拒了（%s / %s）"
                            % (resp2.get("error"), resp3.get("error")))
        else:
            a = json.dumps(resp2["mech_spec"], sort_keys=True)
            b = json.dumps(resp3["mech_spec"], sort_keys=True)
            if a == b:
                problems.append("难度那一档没生效：%s 的 FOUR_STAR 与 NORMAL 逐字节相同"
                                % lv)
            else:
                print("  D2 难度下传 ✓（%s：FOUR_STAR 与 NORMAL 的规格不同）" % lv)
    return problems


# ---------------------------------------------------------------- 第六节：与生产口径对账

def production_crosscheck() -> tuple[list[str], dict]:
    """拿 24 份夹具的**生产规格**（`from_sim`，带计划）对账。

    要证两件事，各自都是可判的：
      * `mech_config[FARMLAND_ID]` 在两个口径下**逐字段相同**（田地与计划无关）
        —— 若不同，说明本判据挑的口径把别的东西也丢了，整张表作废；
      * `mechanisms` 的差**恰好**是 `snow.field`（多一个少一个都红）。
    """
    import check_specgo_go as C
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.frontend.schedule import Schedule
    from ak_tactic.gamedata.enemy import EnemyLibrary
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import build_spec

    problems: list[str] = []
    cov = {"夹具": 0, "生产口径带雪": 0, "田地逐字段相同": 0, "mechanisms 差恰为雪": 0}
    lib = EnemyLibrary()
    for name, spec, err, lv in C.real_specs():
        if spec is None:
            problems.append("生产规格抄不到（%s）：%s" % (name, err))
            continue
        cov["夹具"] += 1
        w_mechs = list(spec["mechanisms"])
        w_farm = (spec["mech_config"] or {}).get(FARMLAND_ID)
        stage = load_stage(lv)
        inp = SpecInputs.from_stage(stage, enemy_at=lib.get,
                                    species_provider=lib.species_of,
                                    schedule=Schedule())
        s2 = build_spec(inp)
        if "snow.field" in w_mechs:
            cov["生产口径带雪"] += 1
        #: ① 差必须恰好是雪
        diff = [x for x in w_mechs if x not in s2["mechanisms"]] + \
               [x for x in s2["mechanisms"] if x not in w_mechs]
        if diff != ([SNOW_ID] if SNOW_ID in w_mechs else []):
            problems.append("%s：两个口径的 mechanisms 差不是「恰好雪」：%s（生产 %s / 空排程 %s）"
                            % (name, diff, w_mechs, s2["mechanisms"]))
        else:
            cov["mechanisms 差恰为雪"] += 1
        #: ② 田地规格必须逐字段相同
        f2 = (s2["mech_config"] or {}).get(FARMLAND_ID)
        if (w_farm is None) != (f2 is None):
            problems.append("%s：一边有田地一边没有（生产 %s / 空排程 %s）"
                            % (name, w_farm is not None, f2 is not None))
        elif w_farm is None:
            cov["田地逐字段相同"] += 1
        else:
            bad = diff_farmland(f2, w_farm)
            if bad:
                problems.append("%s：**两个口径的田地规格不同**（说明口径选错了）：%s"
                                % (name, bad[:3]))
            else:
                cov["田地逐字段相同"] += 1
    return problems, cov


# ---------------------------------------------------------------- 反向守卫

MUTATIONS = ("改一个常量", "少一组", "actual 抹掉一格", "severed 少一格",
             "devices 顺序对调", "unported 漂移")


def mutate(exp: dict, got: dict, which: str):
    """把注入做在**期望值或 Go 读数**上（比较是纯函数，注入点各自独立）。"""
    e2 = copy.deepcopy(exp)
    g2 = copy.deepcopy(got)
    for lv in e2:
        w_mechs, w_cfg = e2[lv]
        f = w_cfg.get(FARMLAND_ID)
        if which == "改一个常量" and f is not None:
            f["pump_range"] = f.get("pump_range", 1) + 1
            return e2, g2
        if which == "少一组" and f is not None and len(f.get("groups") or []) > 1:
            f["groups"] = f["groups"][:-1]
            return e2, g2
        if which == "actual 抹掉一格" and f is not None and f.get("actual"):
            f["actual"] = f["actual"][:-1]
            return e2, g2
        if which == "severed 少一格" and f is not None and f.get("severed"):
            f["severed"] = f["severed"][:-1]
            return e2, g2
    for lv in g2:
        gf = (g2[lv].get("mech_config") or {}).get(FARMLAND_ID)
        if which == "devices 顺序对调" and gf is not None and len(gf.get("devices") or []) > 1:
            gf["devices"] = list(reversed(gf["devices"]))
            return e2, g2
        if which == "unported 漂移":
            g2[lv]["unported"] = list(g2[lv].get("unported") or [])[:-1]
            return e2, g2
    return e2, g2


def main() -> int:
    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：`simgo/spec.py::build_spec`（空排程口径："
          "`SpecInputs.from_stage` ＋ `schedule=Schedule()`）")
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception as e:                                       # noqa: BLE001
        raise SystemExit("取不到缓存关卡清单：%s" % e)
    print("分母：缓存可达的关卡 %d 个（现算，来自 check_go_all.cached_levels）" % len(levels))
    if not levels:
        print("★ 分母是 0 —— 判据瞎了，不给判定")
        return 1
    print()

    exp: dict[str, tuple[list[str], dict]] = {}
    for lv in levels:
        exp[lv] = py_expected(lv)          # ← 循环顶部无条件算
    got = go_mechspec_batch(levels)

    print("一 · 口径与契约")
    d_ok = contract_checks(levels, exp, got)
    for m in d_ok:
        print("  ✗ %s" % m)
    print()

    problems, cov = compare(levels, exp, got)
    print("二 · 逐关逐字段对拍（%d 关）" % len(levels))
    print("  比到的字段：每关 %d 个（%d 标量 ＋ %d 参数 ＋ %d 常量 ＋ groups/actual/"
          "severed/devices 四张表）" % (
              cov["比到的字段数"] // max(1, cov["有田地"]),
              len(SCALAR_KEYS), len(PARAM_KEYS), len(CONST_KEYS)))
    print()

    print("三 · 覆盖率（每条支都要真被走到）")
    for k in ("关卡", "有田地", "无田地", "多组", "有 actual", "有 severed",
              "有 pump", "有 pile", "groups 顺序不同", "child 缺失条数"):
        print("  %-16s %d" % (k, cov.get(k, 0)))
    cbad = coverage_report(cov)
    for m in cbad:
        print("  ✗ %s" % m)
    print()

    print("四 · 登记的守卫")
    gbad: list[str] = []
    mech_src = (ROOT / "rios-sim" / "mechspec.go").read_text(encoding="utf-8")
    for line in UNPORTED:
        if line not in mech_src:
            gbad.append("Go 侧 unported 清单里没有 %r —— 两侧漂了" % line)
    if "STRUCTURAL_ZERO" not in mech_src and "snow_fields" not in mech_src:
        gbad.append("Go 侧不再记录 snow_fields 的行使计数 —— 那条登记的守卫没了")
    if not gbad:
        print("  ✓ 未搬线与结构零两侧同源")
    for m in gbad:
        print("  ✗ %s" % m)
    print()

    print("五 · 与**生产口径**对账（24 份夹具，带计划）")
    p_bad, pcov = production_crosscheck()
    for k, v in pcov.items():
        print("  %-22s %d" % (k, v))
    for m in p_bad:
        print("  ✗ %s" % m)
    print()

    problems = problems + d_ok + cbad + gbad + p_bad

    if mutate_mode:
        print("六 · 反向守卫（每处注入都要独立判红）")
        if problems:
            print("★ 基线本身就不干净 ⇒ 反向守卫无从成立")
            return 1
        bad_guard = 0
        for which in MUTATIONS:
            e2, g2 = mutate(exp, got, which)
            if e2 == exp and g2 == got:
                print("  ✗ 注入「%s」**没有落到任何对象上**（这一处是空转）" % which)
                bad_guard += 1
                continue
            mp, _c = compare(levels, e2, g2)
            ok = bool(mp)
            if not ok:
                bad_guard += 1
            print("  %s 注入「%s」→ %s"
                  % ("✓" if ok else "✗", which, "判红" if ok else "没红（守不住）"))
        if bad_guard:
            print("★ %d / %d 处注入没判红或空转" % (bad_guard, len(MUTATIONS)))
            return 1
        print("  反向守卫成立：%d / %d 处注入都判红" % (len(MUTATIONS), len(MUTATIONS)))
        return 0

    if problems:
        print("★ %d 处不一致：" % len(problems))
        for m in problems[:20]:
            print("  · %s" % m)
        if len(problems) > 20:
            print("  · …（另有 %d 条）" % (len(problems) - 20))
        print("结论：mechanisms / mech_config 对拍**未通过**（%d 处）" % len(problems))
        return 1
    print("结论：%d 关逐字段一致（有田地 %d 关 / 无田地 %d 关）；"
          "生产口径对账 24 份夹具：田地逐字段相同 %d 份、mechanisms 差恰为雪 %d 份；"
          "未搬 %d 条（其中 pile 的 child 缺失 %d 条，已逐条计数）"
          % (len(levels), cov["有田地"], cov["无田地"], pcov["田地逐字段相同"],
             pcov["mechanisms 差恰为雪"], len(UNPORTED), cov["child 缺失条数"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
