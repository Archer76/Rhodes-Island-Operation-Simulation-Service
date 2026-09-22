#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：路线生产侧（`StageMap.ground_path` ＋ `Route.legs`）。

## 对的是什么

* **寻路** `ak_tactic/gamedata/stage.py:172-226`；
* **分段** `ak_tactic/gamedata/stage.py:415-481`（`Route.legs`）。

两者同属**路线生产侧**——它卡着 `spawns` 与 `unsupported` 两个键。合成一份
判据是因为它们同源同命：`legs` 的 `walk` 段就是靠 `ground_path` 一段段拼出来
的（相邻两段之间还要 `pop()` 掉重复顶点），拆成两份判据只会让同一条路上出现
两把尺子。

## ★ 这条判据自己踩过的两个坑（写在这里防止再犯）

**① 「分类」与「期望值」混在同一个 if/elif 链里。** 第一版把「这个用例属于
哪一类」的统计与期望值写在一条链上，期望值用**海象运算符只在一个分支内赋值**，
于是用例落进前两支（同格／端点不可走）时，`wm` 留的是**上一轮的期望值**——
拿陈旧值去比，必然不等，报出一串 `[0,6]→[0,6]：Go 长 1 / Python 长 12`
的假失配（四轮悬案，根因是尺子不是对象）。
⇒ 规矩：**分类与期望值是两件事**。期望值在循环开头**无条件**算好；
分类只用来计数，绝不给期望值赋值。

**② `length` 是逐位比，不是「差不多」。** 权威 `_polyline_length` 走内建
`sum()`，而 **CPython 3.12 起 `sum()` 对浮点走 Neumaier 补偿求和**
（`Objects/bltinmodule.c` 的 `builtin_sum`）；Go 侧若用朴素 `total += …`，
`act31side_05` 的 5 条路线就差 **1 ulp**（`…287` vs `…284`）。
同一段路上还有**第二个、与求和无关的 1 ulp**：`math.dist` 是**平方和开方**，
不是缩放式（见 `rios-sim/stagelegs.go` 的 `gridDist`）。
⇒ 这里比的是 float **精确相等**，**没有容差**：加了容差就再也看不见那 1 ulp，
而那正是花了四轮、先排除公式再排除仪器才逼出来的东西。

## 合成夹具（缓存里一条 `DISAPPEAR` 都没有）

实测 55 关缓存关卡**零条** `DISAPPEAR` ⇒ `vanish` 分支在真夹具上零行使，
而它恰恰是「必须分段、不能连成折线」那一条。故本判据自带一份最小关卡：
Go 走它自己的 `_level_index.json` ＋ `load` 入口，Python 走 `parse_stage`，
两侧都是各自真正的解析路径。夹具**自证行使**：`vanish` 段、`FLY` 路线、
接续去重、非单位步四项，任一为 0 即判红（不是实现错，是夹具不再覆盖它）。

## 反向守卫（`--mutate`）

四处**互相独立**的变异，各自必须被判红，缺一不算成立：

| 变异 | 打在哪 | 证明什么 |
|---|---|---|
| 寻路点列 | 第一条寻路结果多一个点 | 寻路比较是活的 |
| 分段点列 | 第一条 walk 段首点 x+1 | 分段的点列比较是活的 |
| 分段长度 | 第一条 walk 段 `length` **加 1 ulp** | **分辨得出 1 ulp**（贴边界） |
| 分段秒数 | 第一条 vanish 段 `seconds` **加 1 ulp** | 离场时长那一栏是活的 |

用法:
    python tools\\check_stagepath_go.py
    python tools\\check_stagepath_go.py --mutate
"""
from __future__ import annotations

import json
import math
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

#: 四处独立变异的名字（`--mutate` 下四处都要「注入过 ＋ 判红过」）。
MUT_PATH_PTS = "寻路点列"
MUT_LEG_PTS = "分段点列"
MUT_LEG_LEN = "分段长度"
MUT_LEG_SEC = "分段秒数"
MUT_KEYS = (MUT_PATH_PTS, MUT_LEG_PTS, MUT_LEG_LEN, MUT_LEG_SEC)

#: 合成夹具：`synthetic_stage()` 造关卡，`write_synthetic()` 落成 Go 读得到的树。
SYN_LEVEL_ID = "syn_legs_01"
SYN_BAD_MSG = "合成夹具没走到 %s —— 判红（不是实现错，是夹具不再覆盖它）"


# --------------------------------------------------------------- Go 侧入口

def go_call(cmd: str, level: str, spec, data_root: str | None = None) -> dict:
    env = dict(os.environ)
    env["RIOS_DATA"] = data_root or str(DATA)
    req = json.dumps({"id": 1, "cmd": cmd, "level": level, "spec": spec}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    resp = json.loads(line[0]) if line else {}
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp


# --------------------------------------------------------------- 计数与守卫

def join_points(r) -> int:
    """**只用于计数**：`flush()` 里 `pts.pop()` 真正执行过几次。

    一次 `flush()` 拼 k 个路点时 `pop()` 执行 k-2 次；路点序列在
    `WAIT*`／`DISAPPEAR` 处断开（断点后重新算一个路点）。
    这个数证明「接续去重」那条分支被走到了——**不参与任何期望值**。
    """
    n, cur = 0, 1                      #: cur = 本段已积累的路点数（起点算一个）
    for c in r.checkpoints:
        if c.is_move:
            cur += 1
        elif c.type == "DISAPPEAR" or c.is_wait:
            n += max(0, cur - 2)
            cur = 1
    return n + max(0, cur - 1)         #: 结尾还有一次 `walk.append(self.end)`


def has_long_step(pts) -> bool:
    """这一段里有没有**跨格**的一步（端点不可走/不连通时 `ground_path` 退回直线）。

    跨格步是 `gridDist` 的靶子：单位步下「平方和开方」与缩放式逐位相同，
    只有它能把两者的差别照出来。
    """
    return any(abs(b[0] - a[0]) > 1 or abs(b[1] - a[1]) > 1
               for a, b in zip(pts, pts[1:]))


class Guard:
    """反向守卫：每处变异都要「注入过 ＋ 判红过」，缺一不算成立。"""

    def __init__(self, on: bool):
        self.on = on
        self.applied = {k: False for k in MUT_KEYS}
        self.caught = {k: False for k in MUT_KEYS}
        self.at: dict[str, object] = {k: None for k in MUT_KEYS}

    def want(self, key: str) -> bool:
        return self.on and not self.applied[key]

    def put(self, key: str, where) -> None:
        self.applied[key] = True
        self.at[key] = where

    def note(self, key: str, where, field_same: bool) -> None:
        if self.at[key] is not None and self.at[key] == where and not field_same:
            self.caught[key] = True


# --------------------------------------------------------------- 合成夹具

def synthetic_stage() -> dict:
    """一份最小关卡：把 `legs` 的每条分支都摆上去。

    | 路线 | 模式 | 摆的是什么 |
    |---|---|---|
    | 0 | WALK | 多路点 ＋ `WAIT_FOR_SECONDS`（两段 walk 被 wait 隔开） |
    | 1 | FLY  | 直线（`FLY` 不寻路，路点落在墙上也不绕） |
    | 2 | WALK | `DISAPPEAR` ＋ 两个 `WAIT*` ＋ `APPEAR_AT_POS`（vanish） |
    | 3 | WALK | `DISAPPEAR` 之后**没有** `APPEAR_AT_POS`（后面的 MOVE 被吞） |
    | 4 | WALK | 重复路点（`a == b` 的 else 分支） |
    | 5 | WALK | 终点不可走 ⇒ 退回直线（**跨格步**，`gridDist` 的靶子） |
    | 6 | WALK | 空路线（起点＝终点、无途经点 ⇒ 零段） |

    `route`/`row` 是游戏内部口径（自下而上），两侧解析各自翻一次 y。
    """
    floor = {"tileKey": "tile_floor", "heightType": "LOWLAND",
             "buildableType": "MELEE", "passableMask": "ALL"}
    wall = {"tileKey": "tile_wall", "heightType": "HIGHLAND",
            "buildableType": "NONE", "passableMask": "FLY_ONLY"}

    def mv(col: int, row: int) -> dict:
        return {"type": "MOVE", "position": {"col": col, "row": row}}

    def wait(t: float, kind: str = "WAIT_FOR_SECONDS") -> dict:
        return {"type": kind, "time": t, "position": {"col": 0, "row": 0}}

    def appear(col: int, row: int) -> dict:
        return {"type": "APPEAR_AT_POS", "position": {"col": col, "row": row}}

    def route(mode: str, srow: int, scol: int, erow: int, ecol: int,
              cps: list[dict]) -> dict:
        return {"motionMode": mode,
                "startPosition": {"col": scol, "row": srow},
                "endPosition": {"col": ecol, "row": erow},
                "checkpoints": cps}

    return {
        "_levelId": SYN_LEVEL_ID,
        "mapData": {
            #: y=0 在最上面（MAA 口径）；x=2 那一列是墙，只有 y=2 有缺口。
            "map": [[0, 0, 1, 0, 0],
                    [0, 0, 1, 0, 0],
                    [0, 0, 0, 0, 0],
                    [0, 0, 1, 0, 0],
                    [0, 0, 1, 0, 0]],
            "tiles": [floor, wall],
        },
        "routes": [
            route("WALK", 4, 0, 0, 4, [mv(1, 1), wait(2.5), mv(1, 2)]),
            route("FLY", 4, 0, 4, 4, [mv(2, 4), wait(1.0)]),
            route("WALK", 4, 0, 0, 4, [mv(1, 1),
                                       {"type": "DISAPPEAR", "time": 9.0,
                                        "position": {"col": 0, "row": 0}},
                                       wait(3.0), wait(0.5, "WAIT_CUSTOM"),
                                       appear(3, 2), mv(3, 1)]),
            route("WALK", 4, 0, 0, 4, [mv(1, 1),
                                       {"type": "DISAPPEAR", "time": 0.0,
                                        "position": {"col": 0, "row": 0}},
                                       mv(2, 2)]),
            route("WALK", 4, 0, 0, 4, [mv(1, 1), mv(1, 1), mv(2, 2)]),
            route("WALK", 4, 0, 1, 2, []),                 #: 终点 (2,3) 是墙
            route("WALK", 4, 0, 4, 0, []),                 #: 起点＝终点
        ],
    }


def write_synthetic(root: Path) -> None:
    """把合成关卡落成 Go 的取数入口认的那棵树（索引 ＋ `map.ark-nights.com`）。"""
    lvdir = root / "map.ark-nights.com" / "levels"
    lvdir.mkdir(parents=True, exist_ok=True)
    idx = {SYN_LEVEL_ID: {"difficulty": "NORMAL", "zone_id": "syn",
                          "data_path": SYN_LEVEL_ID + ".json", "code": "SYN-1"}}
    (root / "_level_index.json").write_text(
        json.dumps(idx, ensure_ascii=False), encoding="utf-8")
    (lvdir / (SYN_LEVEL_ID + ".json")).write_text(
        json.dumps(synthetic_stage(), ensure_ascii=False), encoding="utf-8")


# --------------------------------------------------------------- 比较

def compare_legs(tag: str, routes, want_legs, got_legs, seen: dict,
                 guard: Guard, printed: list) -> int:
    """逐路线、逐段比 `kind` / `points` / `length` / `seconds`（四栏全精确）。

    调用方已先对过条数（不等就不进这里）。
    """
    bad = 0
    for ri, (wlegs, glegs) in enumerate(zip(want_legs, got_legs)):
        seen["路线"] += 1
        r = routes[ri]
        if (r.mode or "WALK").upper() == "FLY":
            seen["FLY 路线"] += 1
        seen["WAIT 源"] += sum(1 for c in r.checkpoints if c.is_wait)
        seen["DISAPPEAR 源"] += sum(
            1 for c in r.checkpoints if c.type == "DISAPPEAR")
        seen["接续去重（pop）"] += join_points(r)
        seen["跨格步段"] += sum(1 for wl in wlegs if has_long_step(wl.points))
        if len(glegs) != len(wlegs):
            bad += 1
            printed.append("✗ %s 路线 %d 段数：Go=%d Python=%d"
                           % (tag, ri, len(glegs), len(wlegs)))
            continue
        for li, (wl, gl) in enumerate(zip(wlegs, glegs)):
            where = (tag, ri, li)
            seen["段"] += 1
            seen["%s 段" % wl.kind] = seen.get("%s 段" % wl.kind, 0) + 1
            #: ★ 期望值先无条件算好，再谈变异与比较（分类只用来计数）。
            w_kind = wl.kind
            w_pts = [list(p) for p in wl.points]
            w_len = wl.length
            w_sec = wl.seconds
            missing = [k for k in ("kind", "points", "length", "seconds")
                       if k not in gl]
            if missing:
                bad += 1
                printed.append("✗ %s 路线 %d 第 %d 段缺字段：%s"
                               % (tag, ri, li, "、".join(missing)))
                continue
            #: 变异（每处只注入一次，落在不同的段上）。
            if gl["kind"] == "walk" and gl["points"]:
                if guard.want(MUT_LEG_PTS):
                    gl["points"][0][0] += 1
                    guard.put(MUT_LEG_PTS, where)
                elif guard.want(MUT_LEG_LEN):
                    gl["length"] = math.nextafter(gl["length"], math.inf)
                    guard.put(MUT_LEG_LEN, where)
            elif gl["kind"] in ("vanish", "wait") and guard.want(MUT_LEG_SEC):
                gl["seconds"] = math.nextafter(gl["seconds"], math.inf)
                guard.put(MUT_LEG_SEC, where)
            g_pts = [list(map(int, p)) for p in gl["points"]]
            same = {"kind": gl["kind"] == w_kind,
                    "points": g_pts == w_pts,
                    "length": float(gl["length"]) == float(w_len),
                    "seconds": float(gl["seconds"]) == float(w_sec)}
            for key, name in ((MUT_LEG_PTS, "points"), (MUT_LEG_LEN, "length"),
                              (MUT_LEG_SEC, "seconds")):
                guard.note(key, where, same[name])
            if all(same.values()):
                seen["段逐字段一致"] += 1
                continue
            bad += 1
            diff = [k for k, v in same.items() if not v]
            if len(printed) < 6:
                printed.append("✗ %s 路线 %d 第 %d 段（%s）：不一致的字段 %s"
                               % (tag, ri, li, w_kind, "、".join(diff)))
                if "points" in diff:
                    printed.append("    Python 点列 %r" % (w_pts,))
                    printed.append("    Go     点列 %r" % (g_pts,))
                if "length" in diff:
                    printed.append("    Python length=%r（朴素累加会是 %r）"
                                   % (w_len, sum_naive(w_pts)))
                    printed.append("    Go     length=%r" % (gl["length"],))
    return bad


def sum_naive(pts: list[list[int]]) -> float:
    """**只用于报错信息**：朴素左到右累加（1 ulp 那件事的对照读数）。"""
    tot = 0.0
    for a, b in zip(pts, pts[1:]):
        tot += math.dist(a, b)
    return tot


def blank_seen() -> dict:
    return {"关卡": 0, "同格": 0, "端点不可走": 0, "正常寻路": 0, "路径一致": 0,
            "分段关卡": 0, "路线": 0, "段": 0, "walk 段": 0, "wait 段": 0,
            "vanish 段": 0, "FLY 路线": 0, "WAIT 源": 0, "DISAPPEAR 源": 0,
            "接续去重（pop）": 0, "跨格步段": 0, "段逐字段一致": 0}


def main() -> int:
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []
    from ak_tactic.gamedata.stage import load_stage, parse_stage

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：gamedata/stage.py 的 StageMap.ground_path ＋ Route.legs")
    print()

    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    printed: list[str] = []
    bad = 0
    compared = 0
    seen = blank_seen()
    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue

        # ---------------------------------------------------------- 寻路
        qs, wants, kinds = [], [], []
        for r in st.routes:
            for diag in (True, False):
                s, e = tuple(r.start), tuple(r.end)
                qs.append({"start": [int(s[0]), int(s[1])],
                           "end": [int(e[0]), int(e[1])],
                           "diagonal": diag})
                #: ★ 期望值**无条件**算好（不放进任何分支）。
                wants.append([[int(x), int(y)] for x, y in
                              st.map.ground_path(s, e, diagonal=diag)])
                #: 分类只用于计数。
                if s == e:
                    kinds.append("同格")
                elif not st.map.walkable(*s) or not st.map.walkable(*e):
                    kinds.append("端点不可走")
                else:
                    kinds.append("正常寻路")
        if qs:
            got = go_call("path", lv, qs)["paths"]
            if len(got) != len(wants):
                bad += 1
                printed.append("✗ %s 寻路条数：Go=%d Python=%d"
                               % (lv, len(got), len(wants)))
            else:
                compared += 1
                seen["关卡"] += 1
                if guard.want(MUT_PATH_PTS):
                    #: 变异：第一条结果末尾多一个点（只注入一次）。
                    got = json.loads(json.dumps(got))
                    got[0] = got[0] + [[99, 99]]
                    guard.put(MUT_PATH_PTS, (lv,))
                for i, (q, g, w) in enumerate(zip(qs, got, wants)):
                    seen[kinds[i]] += 1
                    gm = [list(map(int, p)) for p in g]
                    guard.note(MUT_PATH_PTS, (lv,), gm == w)
                    if gm == w:
                        seen["路径一致"] += 1
                    else:
                        bad += 1
                        if len(printed) < 6:
                            printed.append(
                                "✗ %s 寻路 %s→%s（diagonal=%s，%s）："
                                "Go 长 %d / Python 长 %d"
                                % (lv, q["start"], q["end"], q["diagonal"],
                                   kinds[i], len(gm), len(w)))
                            if len(gm) == len(w):
                                for k, (a, b) in enumerate(zip(gm, w)):
                                    if a != b:
                                        printed.append(
                                            "    首个不同在第 %d 步：Go=%r Python=%r"
                                            % (k, a, b))
                                        break

        # ---------------------------------------------------------- 分段（真夹具）
        idxs = [r.index for r in st.routes]
        if not idxs:
            continue
        #: ★ 期望值**无条件**算好：`Route.legs` 就是权威本身。
        want_legs = [r.legs(walk_map=st.map) for r in st.routes]
        got_legs = go_call("legs", lv, idxs)["legs"]
        if len(got_legs) != len(want_legs):
            bad += 1
            printed.append("✗ %s 分段条数：Go=%d Python=%d"
                           % (lv, len(got_legs), len(want_legs)))
            continue
        seen["分段关卡"] += 1
        bad += compare_legs(lv, st.routes, want_legs, got_legs, seen, guard, printed)

    # ------------------------------------------------------------ 分段（合成夹具）
    syn_seen = blank_seen()
    with tempfile.TemporaryDirectory(prefix="rios-syn-legs-") as td:
        write_synthetic(Path(td))
        raw = synthetic_stage()
        st_syn = parse_stage(raw, level_id=SYN_LEVEL_ID)
        syn_ids = [r.index for r in st_syn.routes]
        want_syn = [r.legs(walk_map=st_syn.map) for r in st_syn.routes]
        got_syn = go_call("legs", SYN_LEVEL_ID, syn_ids, data_root=td)["legs"]
        if len(got_syn) != len(want_syn):
            bad += 1
            printed.append("✗ 合成夹具分段条数：Go=%d Python=%d"
                           % (len(got_syn), len(want_syn)))
        else:
            syn_seen["分段关卡"] = 1
            bad += compare_legs("合成", st_syn.routes, want_syn, got_syn,
                                syn_seen, guard, printed)
    for line in printed:
        print(line)
    if printed:
        print("（只印前几处失配）")
    print()

    print("已比：地面寻路 %d 关的全部路线 × {含斜向, 不含斜向} 共 %d 例；"
          "路线分段 %d 关 %d 条路线 %d 段"
          % (compared, seen["路径一致"] + bad, seen["分段关卡"],
             seen["路线"], seen["段"]))
    print("★ 行使计数（真夹具）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
    print("★ 行使计数（合成夹具）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(syn_seen.items())))
    print()
    if mutate:
        for k in MUT_KEYS:
            print("  变异「%s」：注入=%s 判红=%s"
                  % (k, "是" if guard.applied[k] else "否",
                     "是" if guard.caught[k] else "否"))
        miss = [k for k in MUT_KEYS
                if not (guard.applied[k] and guard.caught[k])]
        if miss:
            print("反向守卫：不成立 ✗（没做到「注入过并且判红」：%s）"
                  % "、".join(miss))
            return 1
        print("反向守卫：四处独立变异（含两处 1 ulp）各判红 —— 成立 ✓")
        return 0
    if seen["正常寻路"] == 0 or seen["关卡"] == 0:
        print("结论：正常寻路一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    if seen["walk 段"] == 0 or seen["分段关卡"] == 0:
        print("结论：路线分段一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    #: 合成夹具要**自证行使**：否则它会悄悄退化成「跑过但什么都没覆盖」。
    for key, label in (("vanish 段", "DISAPPEAR→APPEAR 的离场段"),
                       ("FLY 路线", "FLY 不寻路的直线段"),
                       ("接续去重（pop）", "相邻两段之间的接续去重"),
                       ("跨格步段", "退回直线的跨格步")):
        if syn_seen.get(key, 0) == 0:
            print("结论：" + SYN_BAD_MSG % label)
            return 1
    print("结论：寻路 %d 例逐格一致；路线分段 %d 段逐字段一致"
          "（含 length 逐位，另含合成夹具 %d 段）"
          % (seen["路径一致"], seen["段逐字段一致"], syn_seen["段逐字段一致"]))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
