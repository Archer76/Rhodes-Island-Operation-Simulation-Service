#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：路线生产侧（`StageMap.ground_path` ＋ `Route.legs` ＋ `eta.route_plans`）。

## 对的是什么

* **寻路** `ak_tactic/gamedata/stage.py:172-226`；
* **分段** `ak_tactic/gamedata/stage.py:415-481`（`Route.legs`）；
* **路线计划表** `ak_tactic/eta.py:122`（`route_plans`）＋ `:48`（`leading_wait`）。

三者同属**路线生产侧**——它卡着 `spawns` 与 `unsupported` 两个键。合成一份
判据是因为它们同源同命：`legs` 的 `walk` 段就是靠 `ground_path` 一段段拼出来
的（相邻两段之间还要 `pop()` 掉重复顶点），而 `route_plans` 就是把这两样
**按路线号组装成一张表**（`simgo/spec.py::_route_tables` 的形状，`spawns`
真正消费的就是它）。拆成三份判据只会让同一条路上出现三把尺子。

层次关系（上面那层调下面那层，不是三个并列的实现）：

    route_plans  ──用──>  Route.legs  ──用──>  ground_path

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
`route_plans` 的 `wait` 同样逐位比（它走的是朴素 `+=`，不是 `sum()`）。

## ★ 两个**结构上不可达**的分支：不是「没测到」，是可达性为零

`eta.route_plans` 里有两处兜底，它们在现有数据上永远不执行。它们**照抄了**
（照抄才叫同一个口径），但**不进行使计数**，而是登记成 `STRUCTURAL_ZERO`：

| 分支 | 为什么不可达 | 守卫 |
|---|---|---|
| `if not pts:`（`eta.py:138`） | `ground_path` 的**三条出口全部非空**（同格 `[start]`、端点不可走 `[start, end]`、不连通 `[start, end]`） | 每跑一次就在 55 关上重量「有没有哪个 ground_path 返回空」，非 0 即红 |
| `wait=0.0 if legs else w` 的 `else` 支（`spec.py:912`） | `Route.legs` 的 `flush()` 每次都至少产出 2 个点 ⇒ `legs` 恒非空 | 同上，重量「有没有哪条路线 legs 为空」 |

★ 两条守卫**每跑一次都重算**（不是写死一句「不可达」）。哪天真出现了，
这里会红，而红的意思是「该补合成夹具了」——不是「实现错了」。

## 合成夹具（缓存里一条 `DISAPPEAR` 都没有）

实测 55 关缓存关卡**零条** `DISAPPEAR` ⇒ `vanish` 分支在真夹具上零行使，
而它恰恰是「必须分段、不能连成折线」那一条。故本判据自带一份最小关卡：
Go 走它自己的 `_level_index.json` ＋ `load` 入口，Python 走 `parse_stage`，
两侧都是各自真正的解析路径。夹具**自证行使**：`vanish` 段、`FLY` 路线、
接续去重、非单位步四项，任一为 0 即判红（不是实现错，是夹具不再覆盖它）。

## 反向守卫（`--mutate`）

八处**互相独立**的变异，各自必须被判红，缺一不算成立：

| 变异 | 打在哪 | 证明什么 |
|---|---|---|
| 寻路点列 | 第一条寻路结果多一个点 | 寻路比较是活的 |
| 分段点列 | 第一条 walk 段首点 x+1 | 分段的点列比较是活的 |
| 分段长度 | 第一条 walk 段 `length` **加 1 ulp** | **分辨得出 1 ulp**（贴边界） |
| 分段秒数 | 第一条 vanish 段 `seconds` **加 1 ulp** | 离场时长那一栏是活的 |
| 路线点列 | 第一条路线的 `points` 首点 x+1 | 计划表那一栏是活的（且与上面四条独立） |
| 路线待命 | 第一条路线的 `wait` **加 1 ulp** | 入场待命逐位比 |
| 路线段数 | 第一条路线的 `legs` 砍掉最后一段 | 段数比较是活的（不是只比前几段） |
| 路线段长度 | 第一条路线的首个 walk 段 `length` **加 1 ulp** | 计划表里的段是**另一条命令**答的，独立于「分段长度」 |

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python（`load_stage` / `ground_path` /
  `Route.legs` / `route_plans` / `leading_wait`），**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/寻路.json`，
  **不 import `ak_tactic`**。

★ 这一套的期望值**不是几个数，是一份投影**：一关一条键，值里带这一关
Python 侧的全部产物——寻路问题（`qs`，含 `diagonal`）与点列、分类（只用于计数，
但读数要复现）、分段（`kind/points/length/seconds`）、路线计划表
（`points/wait/legs`）、以及**尺子那一份行使计数** `py_cov`
（它与 Go 自报的 `covered` 是两个来源，比对是判据的一部分）。

★ **输入身份**：键 `("stagepath", 关卡 id, 该关缓存文件内容 sha16)`
＋ 每次跑先 `G.coverage("stagepath", …)` 对账（关卡清单是按缓存现算的、会长大）。
合成夹具那条走 `("stagepath_syn", 合成关卡内容 sha16)`——合成关卡是本文件的
纯函数（不 import `ak_tactic`），所以冻结档也算得出它的身份。

★ **结构不可达的两条与 `STRUCTURAL_ZERO` 守卫照旧每跑一次重算**：它们量的是
「这一批输入下可达性仍为零」（`py_cov` 与 Go 自报两侧同口径），不是写死一句话。

用法:
    python tools\\check_stagepath_go.py
    python tools\\check_stagepath_go.py --mutate
    python tools\\freeze_baseline.py --record 寻路
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
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"

#: 八处独立变异的名字（`--mutate` 下八处都要「注入过 ＋ 判红过」）。
MUT_PATH_PTS = "寻路点列"
MUT_LEG_PTS = "分段点列"
MUT_LEG_LEN = "分段长度"
MUT_LEG_SEC = "分段秒数"
MUT_RP_PTS = "路线点列"
MUT_RP_WAIT = "路线待命"
MUT_RP_LEGS = "路线段数"
MUT_RP_LEN = "路线段长度"
MUT_KEYS = (MUT_PATH_PTS, MUT_LEG_PTS, MUT_LEG_LEN, MUT_LEG_SEC,
            MUT_RP_PTS, MUT_RP_WAIT, MUT_RP_LEGS, MUT_RP_LEN)

#: 两个**结构上不可达**的分支（见文件头）：它们不进行使计数，
#: 但每跑一次都要重量一遍「可达性仍然为零」，非 0 即红。
STRUCTURAL_ZERO = {
    "path_fallback": "ground_path 返回空 ⇒ 退回 [起点]+路点+终点",
    "legs_empty": "route_plans 拿到空 legs ⇒ spawns 侧走 wait=w 那一支",
}

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


# --------------------------------------------------------------- 期望值（可冻）
def _proj_legs(legs) -> list:
    """`Route.legs()` 的投影：四栏全给（`length` / `seconds` 逐位，不是近似）。"""
    return [{"kind": l.kind, "points": [list(p) for p in l.points],
             "length": l.length, "seconds": l.seconds} for l in legs]


def _proj_plan(p) -> dict:
    """`eta.route_plans` 一条路线的投影。"""
    return {"points": [[float(x), float(y)] for x, y in p.points],
            "wait": float(p.wait), "legs": _proj_legs(p.legs)}


def _proj_route_meta(routes) -> list:
    """每条路线的**计数**元数据（`compare_legs` 里那几处 `seen` 用）。"""
    return [{"mode": (r.mode or "WALK").upper(),
             "n_wait": sum(1 for c in r.checkpoints if c.is_wait),
             "n_disappear": sum(1 for c in r.checkpoints
                                if c.type == "DISAPPEAR"),
             "join": join_points(r)} for r in routes]


def py_expect_level(lv: str) -> dict:
    """一关的期望值（**一份投影，不是几个数**）。

    ★ `ak_tactic` 的 import 写在函数体里：冻结档下本函数不会被调到。
    """
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.eta import route_plans
    try:
        st = load_stage(lv)
    except Exception as exc:                                   # noqa: BLE001
        return {"loaded": False, "why": "%s: %s" % (type(exc).__name__, exc)}
    qs, paths, kinds = [], [], []
    for r in st.routes:
        for diag in (True, False):
            s, e = tuple(r.start), tuple(r.end)
            qs.append({"start": [int(s[0]), int(s[1])],
                       "end": [int(e[0]), int(e[1])], "diagonal": diag})
            #: ★ 期望值**无条件**算好（不放进任何分支）。
            paths.append([[int(x), int(y)] for x, y in
                          st.map.ground_path(s, e, diagonal=diag)])
            #: 分类只用于计数（照原样冻住，让行使计数的口径可复现）。
            if s == e:
                kinds.append("同格")
            elif not st.map.walkable(*s) or not st.map.walkable(*e):
                kinds.append("端点不可走")
            else:
                kinds.append("正常寻路")
    return {"loaded": True, "why": "", "qs": qs, "paths": paths, "kinds": kinds,
            "idxs": [r.index for r in st.routes],
            "route_meta": _proj_route_meta(st.routes),
            "legs": [_proj_legs(r.legs(walk_map=st.map)) for r in st.routes],
            "rp": {str(k): _proj_plan(v) for k, v in route_plans(st).items()},
            "py_cov": py_route_plan_coverage(st)}


def py_expect_syn() -> dict:
    """合成夹具的期望值（本文件的 `synthetic_stage()` 是纯函数，冻结档也能算身份）。"""
    from ak_tactic.gamedata.stage import parse_stage
    st_syn = parse_stage(synthetic_stage(), level_id=SYN_LEVEL_ID)
    return {"idxs": [r.index for r in st_syn.routes],
            "route_meta": _proj_route_meta(st_syn.routes),
            "legs": [_proj_legs(r.legs(walk_map=st_syn.map))
                     for r in st_syn.routes]}


def syn_id() -> str:
    """合成关卡的**内容身份**（不 import `ak_tactic`，冻结档也算得出）。"""
    return GB.sh16(json.dumps(synthetic_stage(), sort_keys=True,
                              ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))


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

def compare_legs(tag: str, meta: list, want_legs, got_legs, seen: dict,
                 guard: Guard, printed: list) -> int:
    """逐路线、逐段比 `kind` / `points` / `length` / `seconds`（四栏全精确）。

    调用方已先对过条数（不等就不进这里）。`meta` 是 `_proj_route_meta()` 的投影
    （只用于那几处计数）——**两种模式走同一份形状**。
    """
    bad = 0
    for ri, (wlegs, glegs) in enumerate(zip(want_legs, got_legs)):
        seen["路线"] += 1
        m = meta[ri]
        if m["mode"] == "FLY":
            seen["FLY 路线"] += 1
        seen["WAIT 源"] += m["n_wait"]
        seen["DISAPPEAR 源"] += m["n_disappear"]
        seen["接续去重（pop）"] += m["join"]
        seen["跨格步段"] += sum(1 for wl in wlegs if has_long_step(wl["points"]))
        if len(glegs) != len(wlegs):
            bad += 1
            printed.append("✗ %s 路线 %d 段数：Go=%d Python=%d"
                           % (tag, ri, len(glegs), len(wlegs)))
            continue
        for li, (wl, gl) in enumerate(zip(wlegs, glegs)):
            where = (tag, ri, li)
            seen["段"] += 1
            seen["%s 段" % wl["kind"]] = seen.get("%s 段" % wl["kind"], 0) + 1
            #: ★ 期望值先无条件算好，再谈变异与比较（分类只用来计数）。
            w_kind = wl["kind"]
            w_pts = [list(p) for p in wl["points"]]
            w_len = wl["length"]
            w_sec = wl["seconds"]
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


# --------------------------------------------------------------- 路线计划表

def py_route_plan_coverage(st) -> dict:
    """Python 侧独立数一遍 `route_plans` 的各条分支——用来核对 **Go 自报的计数**。

    计数器本身也是一个断言（「我走到了这条分支」），它必须有两个来源：
    被测方（Go 的 `covered`）与尺子（这里）。两边不等 ⇒ 判红。
    """
    from ak_tactic.eta import leading_wait
    c = {"routes": 0, "has_move": 0, "no_move": 0, "walk_mode": 0,
         "non_walk_mode": 0, "search_used": 0, "search_not_used_no_move": 0,
         "search_empty": 0, "search_single_point": 0,
         "search_straight_fallback": 0, "path_fallback": 0, "legs_empty": 0,
         "wait_positive": 0}
    for r in st.routes:
        c["routes"] += 1
        has_move = any(x.is_move or x.is_appear for x in r.checkpoints)
        c["has_move" if has_move else "no_move"] += 1
        c["walk_mode" if r.mode == "WALK" else "non_walk_mode"] += 1
        pts = list(r.path or [])
        if not has_move and r.mode == "WALK":
            c["search_used"] += 1
            p = st.map.ground_path(r.start, r.end)
            if not p:
                c["search_empty"] += 1
            elif len(p) == 1:
                c["search_single_point"] += 1
            elif len(p) == 2 and (abs(p[1][0] - p[0][0]) > 1
                                  or abs(p[1][1] - p[0][1]) > 1):
                c["search_straight_fallback"] += 1
            pts = p
        elif not has_move:
            c["search_not_used_no_move"] += 1
        if not pts:
            c["path_fallback"] += 1
            pts = ([r.start] + [x.position for x in r.checkpoints if x.position]
                   + [r.end])
        if not r.legs(walk_map=st.map):
            c["legs_empty"] += 1
        if leading_wait(r) != 0:
            c["wait_positive"] += 1
    return c


def compare_route_plans(tag: str, want: dict, rows: dict, seen: dict,
                        guard: Guard, printed: list) -> int:
    """逐路线比 `points` / `wait` / `legs`（三栏全精确）。

    ★ 与 `compare_legs` 同一套纪律：**期望值先无条件算好**，分类只用于计数。
    """
    bad = 0
    for idx in sorted(want):
        before = bad
        p = want[idx]
        seen["路线计划"] += 1
        if p["wait"]:
            seen["计划 wait>0"] += 1
        where = (tag, idx)
        g = rows[idx]
        missing = [k for k in ("index", "points", "wait", "legs") if k not in g]
        if missing:
            bad += 1
            printed.append("✗ %s 路线 %d 缺字段：%s"
                           % (tag, idx, "、".join(missing)))
            continue
        #: ---- 期望值（无条件算好）
        w_pts = [[float(x), float(y)] for x, y in p["points"]]
        w_wait = float(p["wait"])
        #: ---- 变异（每处只注入一次，落在最先走到的那条路线上）
        if guard.want(MUT_RP_PTS) and g["points"]:
            g["points"][0][0] += 1
            guard.put(MUT_RP_PTS, where)
        elif guard.want(MUT_RP_WAIT):
            g["wait"] = math.nextafter(float(g["wait"]), math.inf)
            guard.put(MUT_RP_WAIT, where)
        elif guard.want(MUT_RP_LEGS) and g["legs"]:
            g["legs"] = g["legs"][:-1]
            guard.put(MUT_RP_LEGS, where)
        g_pts = [[float(x), float(y)] for x, y in g["points"]]
        same_pts = g_pts == w_pts
        same_wait = float(g["wait"]) == w_wait
        guard.note(MUT_RP_PTS, where, same_pts)
        guard.note(MUT_RP_WAIT, where, same_wait)
        if not same_pts:
            bad += 1
            if len(printed) < 8:
                printed.append("✗ %s 路线 %d points 不同" % (tag, idx))
                printed.append("    Python %r" % (w_pts,))
                printed.append("    Go     %r" % (g_pts,))
        if not same_wait:
            bad += 1
            if len(printed) < 8:
                printed.append("✗ %s 路线 %d wait：Go=%r Python=%r"
                               % (tag, idx, g["wait"], w_wait))
        #: ---- 分段（与「分段」那一节同一套字段，但**另一条 Go 命令**答的）
        wlegs, glegs = p["legs"], g["legs"]
        if len(glegs) != len(wlegs):
            bad += 1
            guard.note(MUT_RP_LEGS, where, False)
            if len(printed) < 8:
                printed.append("✗ %s 路线 %d 段数：Go=%d Python=%d"
                               % (tag, idx, len(glegs), len(wlegs)))
            continue
        for li, (wl, gl) in enumerate(zip(wlegs, glegs)):
            lwhere = (tag, idx, li)
            seen["计划段"] += 1
            w_kind = wl["kind"]
            w_lpts = [list(q) for q in wl["points"]]
            w_len = wl["length"]
            w_sec = wl["seconds"]
            lmiss = [k for k in ("kind", "points", "length", "seconds")
                     if k not in gl]
            if lmiss:
                bad += 1
                printed.append("✗ %s 路线 %d 第 %d 段缺字段：%s"
                               % (tag, idx, li, "、".join(lmiss)))
                continue
            if gl["kind"] == "walk" and guard.want(MUT_RP_LEN):
                gl["length"] = math.nextafter(float(gl["length"]), math.inf)
                guard.put(MUT_RP_LEN, lwhere)
            g_lpts = [list(map(int, q)) for q in gl["points"]]
            same = {"kind": gl["kind"] == w_kind,
                    "points": g_lpts == w_lpts,
                    "length": float(gl["length"]) == float(w_len),
                    "seconds": float(gl["seconds"]) == float(w_sec)}
            guard.note(MUT_RP_LEN, lwhere, same["length"])
            if all(same.values()):
                seen["计划段逐字段一致"] += 1
                continue
            bad += 1
            diff = [k for k, v in same.items() if not v]
            if len(printed) < 8:
                printed.append("✗ %s 路线 %d 第 %d 段（%s）：不一致的字段 %s"
                               % (tag, idx, li, w_kind, "、".join(diff)))
        if bad == before:
            seen["计划表逐字段一致"] += 1
    return bad

def blank_seen() -> dict:
    return {"关卡": 0, "同格": 0, "端点不可走": 0, "正常寻路": 0, "路径一致": 0,
            "分段关卡": 0, "路线": 0, "段": 0, "walk 段": 0, "wait 段": 0,
            "vanish 段": 0, "FLY 路线": 0, "WAIT 源": 0, "DISAPPEAR 源": 0,
            "接续去重（pop）": 0, "跨格步段": 0, "段逐字段一致": 0,
            "计划表关卡": 0, "路线计划": 0, "计划 wait>0": 0, "计划段": 0,
            "计划段逐字段一致": 0, "计划表逐字段一致": 0}


def main() -> int:
    G = GB.bind("寻路", __file__)

    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：gamedata/stage.py 的 StageMap.ground_path ＋ Route.legs"
          "，以及 eta.py 的 route_plans / leading_wait")
    print()

    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    printed: list[str] = []
    bad = 0
    compared = 0
    seen = blank_seen()
    go_seen: dict = {}
    py_cov: dict = {}
    struct_zero: dict = {k: 0 for k in STRUCTURAL_ZERO}
    cov_mismatch: list[str] = []

    #: ★ 这一批关卡的**输入身份**（公式只有一份：`freeze_baseline.level_inputs()`）。
    batch = GB.level_inputs(DATA, levels)
    if G.mode == GB.RECORD:
        G.expect(("query", "level_batch"), lambda: batch)
    cov = G.coverage("stagepath", [[r["level"], r["sha16"]] for r in batch])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov.ok:
        covered = {tuple(x) for x in cov.covered}
        to_cmp = [r for r in batch if (r["level"], r["sha16"]) in covered]

    for rec in to_cmp:
        lv = rec["level"]
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        E = G.expect(("stagepath", lv, rec["sha16"]),
                     lambda lv=lv: py_expect_level(lv))
        if not E["loaded"]:
            continue

        # ---------------------------------------------------------- 寻路
        qs, wants, kinds = E["qs"], E["paths"], E["kinds"]
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
        idxs = E["idxs"]
        if not idxs:
            continue
        #: ★ 期望值就是权威本身，只是从通道（冻结的那份）拿。
        want_legs = E["legs"]
        got_legs = go_call("legs", lv, idxs)["legs"]
        if len(got_legs) != len(want_legs):
            bad += 1
            printed.append("✗ %s 分段条数：Go=%d Python=%d"
                           % (lv, len(got_legs), len(want_legs)))
            continue
        seen["分段关卡"] += 1
        bad += compare_legs(lv, E["route_meta"], want_legs, got_legs,
                            seen, guard, printed)

        # ---------------------------------------------------------- 路线计划表
        #: ★ 键还原成**整数**：JSON 只认字符串键，不还原的话 `sorted()` 会按
        #: 字典序排（"10" < "2"），变异落点与打印顺序都会变。
        want_rp = {int(k): v for k, v in E["rp"].items()}
        got_rp = go_call("routeplans", lv, {})["route_plans"]
        for k, v in (got_rp.get("covered") or {}).items():
            go_seen[k] = go_seen.get(k, 0) + v
        for k in STRUCTURAL_ZERO:
            struct_zero[k] += int((got_rp.get("covered") or {}).get(k, 0))
        for k, v in E["py_cov"].items():
            py_cov[k] = py_cov.get(k, 0) + v
        rows = {}
        for r in got_rp["routes"]:
            if r["index"] in rows:
                bad += 1
                printed.append("✗ %s 路线号 %d 在 Go 的应答里出现两次"
                               % (lv, r["index"]))
            rows[r["index"]] = r
        if len(rows) != len(want_rp) or set(rows) != set(want_rp):
            bad += 1
            printed.append("✗ %s 路线计划条数：Go %d / Python %d（去重后 %d）"
                           % (lv, len(got_rp["routes"]), len(want_rp), len(rows)))
        else:
            seen["计划表关卡"] += 1
            bad += compare_route_plans(lv, want_rp, rows, seen, guard, printed)

    # ------------------------------------------------------------ 分段（合成夹具）
    syn_seen = blank_seen()
    with tempfile.TemporaryDirectory(prefix="rios-syn-legs-") as td:
        write_synthetic(Path(td))
        #: ★ 合成关卡的期望值也走通道：它的身份是**本文件那个纯函数**的内容 sha16
        #: （不 import `ak_tactic`，所以冻结档照样算得出）。
        syn = G.expect(("stagepath_syn", syn_id()), py_expect_syn)
        syn_ids = syn["idxs"]
        want_syn = syn["legs"]
        got_syn = go_call("legs", SYN_LEVEL_ID, syn_ids, data_root=td)["legs"]
        if len(got_syn) != len(want_syn):
            bad += 1
            printed.append("✗ 合成夹具分段条数：Go=%d Python=%d"
                           % (len(got_syn), len(want_syn)))
        else:
            syn_seen["分段关卡"] = 1
            bad += compare_legs("合成", syn["route_meta"], want_syn, got_syn,
                                syn_seen, guard, printed)
    for line in printed:
        print(line)
    if printed:
        print("（只印前几处失配）")
    print()

    #: 计数器自己也要有两个来源：Go 自报的 `covered` 与尺子独立数的那一份。
    for k in sorted(py_cov):
        if py_cov[k] != go_seen.get(k):
            cov_mismatch.append("%s：Go 自报 %r，尺子数出 %r"
                                % (k, go_seen.get(k), py_cov[k]))
    if cov_mismatch:
        print("★ 行使计数对不上（计数器与尺子是同一个量的两个来源）：")
        for m in cov_mismatch:
            print("    ✗ %s" % m)
        print()

    print("已比：地面寻路 %d 关的全部路线 × {含斜向, 不含斜向} 共 %d 例；"
          "路线分段 %d 关 %d 条路线 %d 段；路线计划表 %d 关 %d 条路线 %d 段"
          % (compared, seen["路径一致"] + bad, seen["分段关卡"],
             seen["路线"], seen["段"], seen["计划表关卡"],
             seen["路线计划"], seen["计划段"]))
    print("★ 行使计数（真夹具）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(seen.items())))
    print("★ 行使计数（Go 自报的 route_plans 分支）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(go_seen.items())))
    print("★ 行使计数（合成夹具）：%s"
          % ", ".join("%s=%d" % (k, v) for k, v in sorted(syn_seen.items())))
    print()
    if G.mode == GB.CHECK and not cov.ok:
        print(cov.report("stagepath", len(batch)))
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if cov_mismatch:
        print("结论：Go 自报的分支行使计数与尺子独立数出的不一致 —— 判红")
        return 1
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
        print("反向守卫：八处独立变异（含三处 1 ulp）各判红 —— 成立 ✓")
        return 0
    if seen["正常寻路"] == 0 or seen["关卡"] == 0:
        print("结论：正常寻路一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    if seen["walk 段"] == 0 or seen["分段关卡"] == 0:
        print("结论：路线分段一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    if seen["路线计划"] == 0 or seen["计划表关卡"] == 0:
        print("结论：路线计划表一例都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    #: ★ 结构不可达的两条：**每跑一次都重量一遍**（不是写死一句「不可达」）。
    #: 哪天真出现了，这里会红；红的意思是「该补合成夹具了」，不是「实现错了」。
    for key, label in STRUCTURAL_ZERO.items():
        if py_cov.get(key) or struct_zero[key]:
            print("结论：%s 这条兜底**变成可达了**（尺子数出 %d 例、Go 自报 %d）"
                  " —— 判红：它现在有行使，必须补一份合成夹具来判它"
                  % (label, py_cov.get(key, 0), struct_zero[key]))
            return 1
    print("★ 结构不可达（现算，非写死）：%s"
          % "；".join("%s=0（尺子与 Go 两侧同口径）" % STRUCTURAL_ZERO[k]
                      for k in sorted(STRUCTURAL_ZERO)))
    #: 合成夹具要**自证行使**：否则它会悄悄退化成「跑过但什么都没覆盖」。
    for key, label in (("vanish 段", "DISAPPEAR→APPEAR 的离场段"),
                       ("FLY 路线", "FLY 不寻路的直线段"),
                       ("接续去重（pop）", "相邻两段之间的接续去重"),
                       ("跨格步段", "退回直线的跨格步")):
        if syn_seen.get(key, 0) == 0:
            print("结论：" + SYN_BAD_MSG % label)
            return 1
    print("结论：寻路 %d 例逐格一致；路线分段 %d 段逐字段一致"
          "（含 length 逐位，另含合成夹具 %d 段）；路线计划表 %d 条路线 "
          "%d 段逐字段一致（points / wait / length / seconds 全精确）"
          % (seen["路径一致"], seen["段逐字段一致"], syn_seen["段逐字段一致"],
             seen["计划表逐字段一致"], seen["计划段逐字段一致"]))
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
