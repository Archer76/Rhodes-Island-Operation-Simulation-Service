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

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `stage_env`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/关卡静态.json`，
  **不 import `ak_tactic`**。

★ 这套冻的**两半 ＋ 一份取证面读数**：

  · **查询集**：关卡清单（与总入口同源、现算）＋ 两档难度 —— 清单是调用方
    按**缓存**现算的，会随别的会话逐章取数而长大（实测 72 → 320）；
  · **期望值**：一关一条键，值里带**两档难度各自的**结果
    （`py_ok` / 8 项 / 拒收理由）——一关一条是**必需**的：原版对
    `load_stage` 抛错的那些关是**整关跳过**的，若按难度拆键，冻结档就会去问
    那些本来没有期望值的问题（缺键 ⇒ rc=6 假红）；
  · **输入身份**：键 `("stageenv", 关卡 id, 该关缓存文件内容 sha16)`
    ＋ 每次跑先 `G.coverage("stageenv", …)` 对账（对象集是活的）；
  · **取证面读数**（`scan_rune_coverage` 的六个计数）**不参与判定**，
    走 `("stageenv_scope", "rune_coverage")` 冻住——它由 `mask_applies` 现算，
    不冻住冻结档连这几个数都印不出来。⚠ 它**不随批次重算**：缓存长大那一刻
    由 `coverage` 先响（rc=6），不会让旧读数冒充新读数。
  · 两个 tag（`stageenv_scope` / 合成用例键的 `"%d/%s"` 第二段）的**形状是
    给控制组挑的**：P3 会删「按前两段分组后最大的一组」并要求报成「对象变了」，
    所以每一族都必须**每组只有一条键**、且非关卡族的组排在关卡族之后。
    改这两个 tag 的写法会让 P3 从「对账」退化成「缺键」，探针失效。

用法:
    python tools\\check_stageenv_go.py
    python tools\\check_stageenv_go.py --mutate
    python tools\\freeze_baseline.py --record 关卡静态
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
import freeze_baseline as GB                                   # noqa: E402

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


def _norm(env: dict) -> dict:
    """8 项**先规范化成 JSON 形状**（两种模式共用这一个口）。"""
    return {f: (int(env[f]) if f in ("fps", "life") else float(env[f]))
            for f in FIELDS}


def py_env_level(lv: str) -> dict:
    """一关的期望值：**两档难度各自的结果**一次收齐。

    ★ 一关一条键（而不是「一关 × 一档」一条）：原版对 `load_stage` 抛错的关是
      **整关跳过**的，按难度拆键会让冻结档去问那些本来没有期望值的问题。
    ★ `ak_tactic` 的 import 住在函数体里：冻结档下本函数不会被调到。
    """
    from ak_tactic.gamedata.stage import load_stage
    try:
        st = load_stage(lv)
    except Exception as exc:                                   # noqa: BLE001
        return {"loaded": False, "why": "%s: %s" % (type(exc).__name__, exc),
                "env": {}}
    out: dict = {"loaded": True, "why": "", "env": {}}
    for d in DIFFS:
        try:
            out["env"][d] = {"py_ok": True, "why": "", "env": _norm(py_env(st, d))}
        except Exception as exc:                               # noqa: BLE001
            out["env"][d] = {"py_ok": False, "why": "%s: %s"
                             % (type(exc).__name__, exc), "env": None}
    return out


def py_rune_coverage(levels) -> dict:
    """取证面读数（**不是判据**）：这批关卡的 rune 里几条口径各命中几关。

    ★ 它由 `mask_applies` 现算 ⇒ 冻结档必须走 `G.expect` 才印得出来。
    """
    return scan_rune_coverage(levels)


def py_synth_env(blob: dict, difficulty: str) -> dict:
    """合成关卡的期望值（同样规范化成 JSON 形状）。"""
    return _norm(synth_env(blob, difficulty))


def blob_id(blob: dict) -> str:
    """合成用例的**输入身份**：内容 sha16（数据侧算，不 import `ak_tactic`）。"""
    return GB.sh16(json.dumps(blob, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))


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
    G = GB.bind("关卡静态", __file__)

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

    #: ★ 这一批关卡的**输入身份**：关卡 id ＋ 缓存文件内容 sha16（公式只有一份，
    #: 在 `freeze_baseline.level_inputs()` 里——关卡/敌人两套用的是同一份）。
    batch = GB.level_inputs(DATA, levels)
    if G.mode == GB.RECORD:
        G.expect(("query", "level_batch"), lambda: batch)
    cov = G.coverage("stageenv", [[r["level"], r["sha16"]] for r in batch])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov.ok:
        #: 只比两边都有的。**未覆盖的不猜**——猜就是自己写一份期望值。
        covered = {tuple(x) for x in cov.covered}
        to_cmp = [r for r in batch if (r["level"], r["sha16"]) in covered]

    for rec in to_cmp:
        lv = rec["level"]
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由对账如实报出，
        #: 而不是拿一份旧内容的期望值去比新内容（那会造出一条假红）。
        E = G.expect(("stageenv", lv, rec["sha16"]),
                     lambda lv=lv: py_env_level(lv))
        if not E["loaded"]:
            continue
        for d in DIFFS:
            rd = E["env"].get(d) or {"py_ok": False,
                                     "why": "（基线里没有这一档）", "env": None}
            ok, got = go_env(lv, d)
            py_ok = rd["py_ok"]
            want = rd["env"]
            py_err = rd["why"]
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

    if G.mode == GB.CHECK and not cov.ok:
        print()
        print(cov.report("stageenv", len(batch)))

    #: 取证面读数（不是判据）：不冻住的话冻结档印不出这几个数。
    #: ⚠ 这条键的**名字选过**：控制组的 P3 会把「每对象一组」的键按前两段分组、
    #: 挑**最大**的一组删掉，删完要求冻结档报成「对象变了」（rc=6 ＋ 印对账）。
    #: 所以（a）它不能与前缀更小的组同名到成为「第一个最大组」——用
    #: `stageenv_scope` 让它排在 `stageenv` 关卡键**之后**；（b）每组只能有 1 条键。
    cov_rune = G.expect(("stageenv_scope", "rune_coverage"),
                        lambda: py_rune_coverage(levels))
    for k, n in cov_rune.items():
        seen[k] = n

    #: ---- 合成用例 ----
    with tempfile.TemporaryDirectory() as td:
        for i, (label, blob) in enumerate(SYNTH):
            path = Path(td) / ("s%d.json" % i)
            path.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")
            bid = blob_id(blob)
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
                #: ★ 期望值只能从这里来：默认档现调 Python，冻结档读冻的那份。
                #: 键里带**这一例的内容身份**（改用例表 ⇒ 键配不上，不是静默复用）。
                #: ⚠ 键的**第二段**把例号与难度合成一个元素：分成两段会让这一族
                #: 出现「每对象 2 条键」的组，而控制组的 P3 专挑**最大的**那组删
                #: ——它就会挑到合成用例，删完由缺键（而非对账）报 rc=6，探针失效。
                want = G.expect(("stageenv_synth", "%d/%s" % (i, d), bid),
                                lambda blob=blob, d=d: py_synth_env(blob, d))
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
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
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
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
