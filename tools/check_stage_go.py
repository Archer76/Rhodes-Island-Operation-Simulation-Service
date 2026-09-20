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

用法:
    python tools\\check_stage_go.py main_00-01
    python tools\\check_stage_go.py main_00-01 main_01-07 main_02-01
    python tools\\check_stage_go.py 1-7 --mutate      # 反向守卫

    RIOS_SIM_BIN 可指定 Go 二进制（默认 out/acceptance/rios-sim-stage1.exe）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage1.exe"))
DATA = ROOT / "data" / "gamedata"


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


def py_load(level: str) -> dict:
    """Python 那一份，按它自己的 `to_dict()` 出。"""
    from ak_tactic.gamedata.stage import load_stage
    st = load_stage(level)
    return st


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
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    mutate = "--mutate" in sys.argv
    levels = args or ["main_00-01"]
    bad = 0
    for level in levels:
        got = go_load(level)
        st = py_load(level)
        want = go_side(st, level)
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
    if mutate:
        print()
        print("反向守卫：本轮**期望**判红（地图键被人为改动）——"
              "%s" % ("成立 ✓" if bad else "不成立 ✗（判据没有分辨力）"))
        return 0 if bad else 1
    print()
    print("结论：%d / %d 关逐字段一致" % (len(levels) - bad, len(levels)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
