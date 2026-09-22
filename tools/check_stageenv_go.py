#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：构建规格要用的**关卡静态 8 项**。

## 对的是什么

`ak_tactic/frontend/stage_env.py:68-102` 的 `stage_env`，连同它的两个下游
`stage_mul.py` 的 `global_lifepoint` / `cost_recovery_scale` 与
`blackboard.py` 的 `mask_applies` / `find_rune` / `bb_number`。

这是 `build_spec`（`simgo/spec.py:1161-1291`）19 个顶层键里**不依赖 sim／
干员／机制**的那 8 个，所以是「Go 自己构造规格」的第一块。

## 覆盖面

缓存里可达的**全部**关卡（不抽样）× **两档难度**（`NORMAL` 与 `FOUR_STAR`）。

## 为什么非要跑非 NORMAL 那一档

原版自己写明：那两条 rune（`cbuff_cost_recovery` 的费用的回复倍率、
`global_lifepoint` 的生命点改写）**只在非 NORMAL 下才与普通档不同**，
而当前流水线恒为 NORMAL ⇒ 那是**沉默区**。只跑 NORMAL 的话，这两行实现错了
也一声不响——正是「控制组没红时工具自己吼出来」要防的那种绿。

## 三处「0 与 None 一视同仁」

原版到处写 `or`，于是**显式的 0 会被换成缺省值**：`max_cost: 0` → 99.0、
`cost_increase_time: 0` → 1.0、`move_multiplier: 0` → 1.0、`max_life_point: 0`
→ 1。改成 `is None` 会在这些取值上分叉，而现有计划覆盖不到。
本判据用**合成关卡**把这几条钉住（见 `SYNTH`）。

用法:
    python tools\\check_stageenv_go.py
    python tools\\check_stageenv_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

FIELDS = ("fps", "speed_scale", "ranged_enemies", "enemy_windup",
          "cost_init", "cost_max", "cost_time", "life")
DIFFS = ("NORMAL", "FOUR_STAR")


def go_env(level: str, difficulty: str, *, path: bool = False) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = {"id": 1, "cmd": "stageenv", "spec": {"difficulty": difficulty}}
    req["path" if path else "level"] = level
    p = subprocess.run([GO_BIN], input=(json.dumps(req) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        return False, resp.get("error") or ""
    return True, resp["stage_env"]


def py_env(stage, difficulty: str) -> dict:
    from ak_tactic.frontend.stage_env import stage_env

    return stage_env(stage, environment_difficulty=difficulty)


def scan_rune_coverage(levels) -> dict[str, int]:
    """这批关卡的 rune 里，几条要紧的口径各命中几关。

    ★ 这是**取证面**的读数，不是判据：为 0 说明「这批关卡没有这种 rune」，
    不等于实现错。所以它只印出来，只有下面 `REQUIRED` 里那几条才判红。
    """
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.frontend.blackboard import mask_applies

    cov = {k: 0 for k in ("global_lifepoint", "gbuff_lifepoint",
                          "cbuff_cost_recovery", "同键多条且掩码可消歧",
                          "掩码 ALL", "掩码 非NORMAL")}
    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue
        runes = (getattr(st, "raw", None) or {}).get("runes") or []
        keys = [r.get("key") for r in runes]
        for k in ("global_lifepoint", "gbuff_lifepoint", "cbuff_cost_recovery"):
            if k in keys:
                cov[k] += 1
        hit = {}
        for r in runes:
            hit.setdefault(r.get("key"), 0)
            hit[r.get("key")] += 1
        if any(v > 1 for v in hit.values()):
            cov["同键多条且掩码可消歧"] += 1
        if any((r.get("difficultyMask") == "ALL") for r in runes):
            cov["掩码 ALL"] += 1
        if any((r.get("difficultyMask") not in (None, "", "ALL", "NORMAL"))
               for r in runes):
            cov["掩码 非NORMAL"] += 1
    return cov


#: 合成关卡：只为把「显式 0 与缺省同义」那几条钉住。
#:
#: ⚠ **这里有两个键空间，写混了与实现错长得一模一样**（本轮实测两次翻转）：
#:
#: * **数据侧是驼峰**——关卡 JSON 里就是 `maxLifePoint` / `costIncreaseTime`，
#:   所以喂给 Go 的文件必须这么写（Go 直接解析文件）；
#: * **对象属性是蛇形**——`stage_env` 读的是 `stage.options.initial_cost`，
#:   所以给原版造替身时要先映射一次（见 `OPT_MAP`）。
#:
#: 第一版按驼峰写、替身也按驼峰造 ⇒ 原版全读缺省、Go 读到真值；
#: 改成蛇形 ⇒ 两边正好翻转。夹具是**第三处键空间**，它错了会伪装成实现错。
SYNTH = [
    ("显式 0 全部走缺省",
     {"options": {"initialCost": 0, "maxCost": 0, "costIncreaseTime": 0,
                  "moveMultiplier": 0, "maxLifePoint": 0}, "runes": []}),
    ("正常值不被 or 换掉",
     {"options": {"initialCost": 10, "maxCost": 50, "costIncreaseTime": 2.5,
                  "moveMultiplier": 1.5, "maxLifePoint": 3}, "runes": []}),
    ("生命点被 rune 改写",
     {"options": {"maxLifePoint": 3}, "runes": [
         {"key": "global_lifepoint", "difficultyMask": "NORMAL",
          "blackboard": [{"key": "value", "value": 1}]}]}),
    ("老键名 gbuff_lifepoint",
     {"options": {"maxLifePoint": 3}, "runes": [
         {"key": "gbuff_lifepoint", "difficultyMask": "FOUR_STAR",
          "blackboard": [{"key": "value", "value": 1}]}]}),
    ("费用回复倍率要除",
     {"options": {"costIncreaseTime": 2.0}, "runes": [
         {"key": "cbuff_cost_recovery", "difficultyMask": "ALL",
          "blackboard": [{"key": "scale", "value": 2}]}]}),
    ("同键多条取最后一条",
     {"options": {}, "runes": [
         {"key": "global_lifepoint", "difficultyMask": "ALL",
          "blackboard": [{"key": "value", "value": 5}]},
         {"key": "global_lifepoint", "difficultyMask": "ALL",
          "blackboard": [{"key": "value", "value": 2}]}]}),
    ("掩码不对的那条不算",
     {"options": {"maxLifePoint": 3}, "runes": [
         {"key": "global_lifepoint", "difficultyMask": "FOUR_STAR",
          "blackboard": [{"key": "value", "value": 9}]}]}),
    ("倍率为 0 时不除",
     {"options": {"costIncreaseTime": 2.0}, "runes": [
         {"key": "cbuff_cost_recovery", "difficultyMask": "ALL",
          "blackboard": [{"key": "scale", "value": 0}]}]}),
]

#: 数据侧驼峰 → 对象属性蛇形。**只映射 `stage_env` 真读的那五个**。
OPT_MAP = {
    "initialCost": "initial_cost",
    "maxCost": "max_cost",
    "costIncreaseTime": "cost_increase_time",
    "moveMultiplier": "move_multiplier",
    "maxLifePoint": "max_life_point",
}


def synth_env(blob: dict, difficulty: str) -> dict:
    """合成关卡没有 `Stage` 对象，只喂 `stage_env` 真读的那两处。"""
    import types

    from ak_tactic.frontend.stage_env import stage_env

    opts = types.SimpleNamespace(
        **{OPT_MAP[k]: v for k, v in blob["options"].items()})
    stage = types.SimpleNamespace(options=opts, raw={"runes": blob["runes"]})
    return stage_env(stage, environment_difficulty=difficulty)


def main() -> int:
    from ak_tactic.gamedata.stage import load_stage

    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：frontend/stage_env.py 的 stage_env（＋ stage_mul / blackboard）")
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    both_refused = 0
    seen: dict[str, int] = {}

    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue
        for d in DIFFS:
            ok, got = go_env(lv, d)
            try:
                want = py_env(st, d)
                py_ok = True
            except Exception as exc:                        # noqa: BLE001
                want, py_ok = None, False
                py_err = "%s: %s" % (type(exc).__name__, exc)
            if not ok or not py_ok:
                if not ok and not py_ok:
                    both_refused += 1
                    continue
                bad += 1
                print("✗ %s/%s —— Go ok=%s（%s） Python ok=%s（%s）"
                      % (lv, d, ok, got if not ok else "-",
                         py_ok, py_err if not py_ok else "-"))
                continue
            compared += 1
            seen["难度 " + d] = seen.get("难度 " + d, 0) + 1
            if mutate and compared == 1:
                got = dict(got)
                got["life"] = got["life"] + 1
            for f in FIELDS:
                a, b = got[f], want[f]
                if f in ("fps", "life"):
                    same = int(a) == int(b)
                else:
                    same = abs(float(a) - float(b)) < 1e-9
                if not same:
                    bad += 1
                    print("✗ %s/%s %s：Go=%r Python=%r" % (lv, d, f, a, b))

    cov = scan_rune_coverage(levels)
    for k, n in cov.items():
        seen[k] = n

    #: ---- 合成用例 ----
    with tempfile.TemporaryDirectory() as td:
        for i, (label, blob) in enumerate(SYNTH):
            path = Path(td) / ("s%d.json" % i)
            path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
            for d in DIFFS:
                ok, got = go_env(str(path), d, path=True)
                if not ok:
                    bad += 1
                    print("✗ 合成[%s]/%s —— Go 拒了：%s" % (label, d, got))
                    continue
                compared += 1
                if mutate and compared == 1:
                    got = dict(got)
                    got["life"] = got["life"] + 1
                want = synth_env(blob, d)
                for f in FIELDS:
                    a, b = got[f], want[f]
                    same = (int(a) == int(b) if f in ("fps", "life")
                            else abs(float(a) - float(b)) < 1e-9)
                    if not same:
                        bad += 1
                        print("✗ 合成[%s]/%s %s：Go=%r Python=%r"
                              % (label, d, f, a, b))
            seen["合成：" + label] = seen.get("合成：" + label, 0) + 1
            seen["合成用例"] = seen.get("合成用例", 0) + 1

    print()
    print("已比：关卡静态 8 项；%d 关（缓存可达）× %d 档 ＋ %d 例合成，共 %d 例逐字段比"
          % (len(levels), len(DIFFS), len(SYNTH), compared))
    print("★ 行使计数：")
    for k, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-28s %d" % (k, n))
    print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    #: 只要求这两档 + 合成用例真跑过；其余是**取证面**读数，为 0 只说明
    #: 「这批关卡没有那种 rune」，不当缺陷（三态，不压成一个红）。
    must = ["难度 NORMAL", "难度 FOUR_STAR", "合成用例"]
    unchecked = [k for k in must if seen.get(k, 0) == 0]
    if unchecked:
        print("结论：没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    print("结论：%d 例逐字段一致（另 %d 例两边都拒、%d 处失配）"
          % (compared, both_refused, bad))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
