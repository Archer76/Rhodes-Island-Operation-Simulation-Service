#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自读的关卡 vs Python 的 `load_stage()`。

## 它为什么存在

丙阶段一（把取数链搬进 Go）只有「两边逐字段一致」才算过。
**Python 在这一步是 oracle，不是依赖**——它最终要被删掉，
但在迁移期它是唯一一份已验证过的实现（`ak_tactic/battle/` 那条链）。

## 判据

逐字段比，任一处不等即红并打印到字段级；**并给一条正负对照**：
控制组不许红，且人为改动 Go 的一项必须能变红（`--mutate`）。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `load_stage`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/关卡.json`，**不 import `ak_tactic`**。

## ★ 本套是「乙类」：对象集是**活的**，所以键必须**自带输入身份**

取证范围由调用方（`check_go_all` 的 `cached_levels()`）喂进来，而它按**缓存**现算
——缓存被别的会话逐章取数时会**长大**（实测 2026-09-24 当晚 72 → 320）。
于是「现读 ≠ 冻结」有两种**完全不同**的因：

* **Go 漂移了** ⇒ 判据红（rc=1），要人去看实现；
* **对象集/对象内容变了** ⇒ 读数**不可用**（rc=6，印「输入批次对账」），基线该重录。

⇒ 两个动作：
① **键里带输入身份** `("stage", 关卡 id, 该关缓存文件内容 sha16)`——只记关卡名，
   缓存内容变了就分不出「对象变了」；
② 每次跑先做 `G.coverage("stage", …)` 对账：只比两边都有的，未覆盖的**不猜**
   （猜＝自己写一份期望值，正是本仓禁止的），并把未覆盖的**具名印出来**。

用法:
    python tools\\check_stage_go.py main_00-01
    python tools\\check_stage_go.py main_00-01 main_01-07 main_02-01
    python tools\\check_stage_go.py 1-7 --mutate      # 反向守卫
    python tools\\freeze_baseline.py --record 关卡     # 录/重录（缓存长大之后要重录）

    RIOS_SIM_BIN 可指定 Go 二进制（默认 out/acceptance/rios-sim-stage3.exe）
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"


def level_batch(levels: list[str]) -> list[dict]:
    """这一批关卡的**输入身份**：关卡 id ＋ 缓存文件路径 ＋ **内容 sha16**。

    ★ 公式只有一份，在 `freeze_baseline.level_inputs()` 里——**敌人那套用同一份**。
      本仓记过：同一个公式两处各写一份，一改就对不上。
    """
    return GB.level_inputs(DATA, levels)


def go_load(level: str) -> dict:
    """问 Go 要一份关卡。子进程输出按 bytes 收、自己解码（别让 PowerShell 插手）。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "load", "level": level}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go 进程 rc=%d：%s" % (
            p.returncode, p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西（stderr：%s）"
                         % p.stderr.decode("utf-8", "replace")[:400])
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["stage"]


def py_stage_expect(level: str) -> dict:
    """期望值入口：Python 那一份，按它自己的口径摊成与 Go 同形的 dict。

    ★ `ak_tactic` 的 import **写在函数体里**：冻结档下本函数不会被调到。
    """
    from ak_tactic.gamedata.stage import load_stage
    return go_side(load_stage(level), level)


def diff(prefix: str, a, b, out: list[str]) -> None:
    """递归比。`a` = Go，`b` = Python。"""
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append("%s.%s：Go 缺（Python=%r）" % (prefix, k, _short(b[k])))
            elif k not in b:
                out.append("%s.%s：Python 缺（Go=%r）" % (prefix, k, _short(a[k])))
            else:
                diff("%s.%s" % (prefix, k), a[k], b[k], out)
        return
    if isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append("%s：长度 Go=%d Python=%d" % (prefix, len(a), len(b)))
        for i in range(min(len(a), len(b))):
            diff("%s[%d]" % (prefix, i), a[i], b[i], out)
        return
    if isinstance(a, float) and isinstance(b, float):
        if a != b:
            out.append("%s：Go=%r Python=%r（差 %g）" % (prefix, a, b, a - b))
        return
    if a != b:
        out.append("%s：Go=%r Python=%r" % (prefix, _short(a), _short(b)))


def _short(v):
    s = repr(v)
    return s if len(s) <= 60 else s[:57] + "..."


def go_side(st, level: str) -> dict:
    """把 Python 的 Stage 摊成与 Go 同形的 dict（键序无所谓，比的是值）。"""
    return {
        "level_id": st.level_id,
        "code": st.code,
        "difficulty": st.difficulty,
        "map": {
            "width": st.map.width,
            "height": st.map.height,
            "tiles": [[{"key": t.key, "height": t.height,
                        "buildable": t.buildable, "passable": t.passable}
                       for t in row] for row in st.map.tiles],
        },
        "options": {
            "character_limit": st.options.character_limit,
            "max_life_point": st.options.max_life_point,
            "initial_cost": st.options.initial_cost,
            "max_cost": st.options.max_cost,
            "cost_increase_time": st.options.cost_increase_time,
            "move_multiplier": st.options.move_multiplier,
            "is_training": st.options.is_training,
            "is_hard_training": st.options.is_hard_training,
        },
        "routes": [_route(r) for r in st.routes],
        "extra_routes": [_route(r) for r in st.extra_routes],
        "branches": {
            k: [{"enemy_key": a.enemy_key, "route_index": a.route_index,
                 "count": a.count, "interval": a.interval,
                 "pre_delay": a.pre_delay} for a in v]
            for k, v in st.branches.items()
        },
        "spawns": [{
            "enemy_id": s.enemy_id, "count": s.count, "interval": s.interval,
            "route_index": s.route_index, "wave_index": s.wave_index,
            "fragment_index": s.fragment_index, "action_index": s.action_index,
            "pre_delay": s.pre_delay, "fragment_start": s.fragment_start,
            "level": s.level, "block_fragment": s.block_fragment,
            #: ★ 原样给，**不要 `or ""`**：`None`（没有这个键）与空串是两态，
            #: 压成一个就再也分不出来（本项目记过的坑）。
            "hidden_group": s.hidden_group,
        } for s in st.spawns],
    }


def _route(r) -> dict:
    return {
        "index": r.index, "mode": r.mode,
        "start": list(r.start), "end": list(r.end),
        "checkpoints": [{
            "type": c.type,
            "position": list(c.position) if c.position is not None else None,
            "wait": c.wait,
        } for c in r.checkpoints],
    }


def main() -> int:
    G = GB.bind("关卡", __file__)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    mutate = "--mutate" in sys.argv
    levels = args or ["main_00-01"]

    batch = level_batch(levels)
    if G.mode == GB.RECORD:
        #: 把「这一次录的是哪一批关卡」记成一条**可读的**记录（含每关的内容 sha16）。
        #: 冻结档**不读它**用来判定——它回答的是「这份基线录的是哪一批」，
        #: 而 `--check` 的「改值」栏会量到它：缓存一变，这里第一个显形。
        G.expect(("query", "level_batch"), lambda: batch)
    cov = G.coverage("stage", [(r["level"], r["sha16"]) for r in batch])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov.ok:
        #: 只比两边都有的。**未覆盖的不猜**——猜就是自己写一份期望值，
        #: 那正是本仓记过的那条（两把相同的尺子互证）。
        covered = {tuple(x) for x in cov.covered}
        to_cmp = [r for r in batch if (r["level"], r["sha16"]) in covered]

    bad = 0
    for rec in to_cmp:
        level = rec["level"]
        got = go_load(level)
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由上面那条对账如实报出，
        #: 而不是拿一份旧内容的期望值去比新内容（那会造出一条假红）。
        want = G.expect(("stage", level, rec["sha16"]),
                        lambda level=level: py_stage_expect(level))
        if mutate:
            # 反向守卫：把 Go 的一格地图键改掉，判据**必须**红。
            want["map"]["tiles"][0][0]["key"] = "<mutated>"
        out: list[str] = []
        diff("stage", got, want, out)
        head = ("  ✓ %-14s 地图 %dx%d，路线 %d，出怪 %d，分支 %d"
                % (level, got["map"]["width"], got["map"]["height"],
                   len(got["routes"]), len(got["spawns"]), len(got["branches"])))
        if out:
            bad += 1
            print("✗ %s —— %d 处不一致" % (level, len(out)))
            for line in out[:40]:
                print("    " + line)
        else:
            print(head)
    print()
    if G.mode == GB.CHECK and not cov.ok:
        print(cov.report("stage", len(batch)))
        #: ★ 把两种因**分开列**：不分开的话，「同一关卡换了内容」与「多/少了几关」
        #: 长得一模一样（都是 extra/missing 两栏），而下一个人要靠那句话决定
        #: 「重录」还是「查对象集」。判法：按**关卡名**求交/求差。
        ex_ids = {g[0] for g in cov.extra}
        ms_ids = {g[0] for g in cov.missing}
        chg = sorted(ex_ids & ms_ids)          # 同一个关卡、内容 sha 变了
        add = sorted(ex_ids - ms_ids)          # 只在这一批里有
        gone = sorted(ms_ids - ex_ids)         # 只在冻的那批里有
        if chg:
            print("  · ★ **内容变了**（同一关卡、缓存文件内容 sha 变了，%d 关）：%s"
                  % (len(chg), "、".join(chg[:8])))
        if add:
            print("  · **对象集变了**（新增，%d 关）：%s" % (len(add), "、".join(add[:8])))
        if gone:
            print("  · **对象集变了**（这次没问、但冻着，%d 关）：%s"
                  % (len(gone), "、".join(gone[:8])))
        print()
    print("已比：%d 关（传入 %d 关%s）"
          % (len(to_cmp), len(batch),
             "" if len(to_cmp) == len(batch) else "；**未覆盖 %d 关**" % (len(batch) - len(to_cmp))))
    if mutate:
        print()
        print("反向守卫：本轮**期望**判红（地图键被人为改动）——"
              "%s" % ("成立 ✓" if bad else "不成立 ✗（判据没有分辨力）"))
        return 0 if bad else 1
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    print("结论：%d / %d 关逐字段一致" % (len(to_cmp) - bad, len(to_cmp)))
    if bad:
        #: 覆盖部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 覆盖部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
