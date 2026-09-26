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

## 这一段还比两样别的东西（`load` 之外的**第二条命令**）

关卡那一栏比的是 Go 的 `load` 应答；本轮加进来的**可部署格**是**另一条命令**
（`spots`，见 `rios-sim/spots.go` 与 `ak_tactic/gamedata/stage.py:84-150`）：

* **两张点列逐元素、含顺序比**：`melee` / `ranged` ↔ `StageMap.melee_spots` /
  `ranged_spots`。★ 顺序**是判据的一部分**：两侧都是行主序（y 在外、x 在内，
  `stage.py:143` ↔ `spots.go:45`），搜索的候选枚举按这个顺序推进 ⇒ 顺序错了，
  `per_op` 截断与平局取谁都会跟着变。
* **`covered` 七栏（两个来源）**：Go **自报**的 `covered` ↔ 尺子**独立数**的一份
  `buildable` 计数（`ruler_counts()`，从 Python 那份 tiles 现数，**不调 Go**）。
  两个来源不等即红——这是本仓那套「Go 自报 vs 尺子独立数」的同一形状。
* **两条恒等式在 Go 自己那份读数上查**：`melee_spots == melee + all`、
  `ranged_spots == ranged + all`，外加「点列长度 == 自报的那两栏」。它们量的是
  **Go 内部两条代码路径**是不是同一个口径（点列走 `spots()`、计数走
  `CountBuildable()`）。`all` 正是那次事故的那一类（`ALL` 落进「两种都不能」⇒
  整图零可部署格），所以这两条恒等式在 `all` 非零时才有分辨力。

★ **覆盖面的两个「0」要分开**：`all` 是这一段的靶子（本批 360 格 / 11 关，非零），
而 `unknown`（第五种取值）在真数据里 0 样本 ⇒ **具名登记为未覆盖**，不判红
（把它判红＝永久假红，本仓：永久假红等于没有判据）。

## ★ 这条判据踩过的两条坑（写在这里防止再犯）

**① Python 的关卡加载器会按需从镜像下载缺失的关卡文件并缓存**到
`data/gamedata/map.ark-nights.com/levels/…`（实测：8 个 `tr_*` 关卡在探针跑的
窗口内落盘）。⇒ 「Go 取不到而 Python 取到了」**不等于** Go 有错，可能只是 Python
顺手把数据补齐了。处置：Go 失败时**也去调一次 Python**，三种情形分开报——
两边都取不到 ⇒ 记「数据缺」，**不算红**；Python 取到 ⇒ **复测一次 Go**，
复测成功记「Python 补齐」（不红），两次都取不到才判红。冻结档下不 import
`ak_tactic`（核实做不到）⇒ 一律判红：不许拿「可能是数据缺」当免罪符。

**② 引擎的 gamedata 根可以被 `RIOS_DATA` 覆盖，没设它时按 cwd 拼。**
实测四种组合（同一枚 exe、同一关 `main_01-07`）：

| cwd | `RIOS_DATA` | 结果 |
|---|---|---|
| 有 `data/` 的那棵树 | 设 | ok |
| 有 `data/` 的那棵树 | 不设 | ok（相对路径落在 cwd 的 junction 上） |
| `C:\\` | 设 | **ok**（本判据走的就是这一格） |
| `C:\\` | 不设 | 失败：`读关卡索引失败（data\\gamedata\\_level_index.json）` |

⇒ 本判据把 `RIOS_DATA` 显式指到 `<ROOT>/data/gamedata`（**绝对路径**），
所以 **cwd 不绑它**；真正的要求是**那棵树在场**（worktree 里靠 junction）。
不在场时**具名拒跑**——否则每一关都以「Go 进程 rc=1」的样子出现，读的人会去查实现。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python 的 `load_stage`，**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/关卡.json`，**不 import `ak_tactic`**。

★ **可部署格那一段走同一套通道、但另一个 tag**：键是
`("spots", 关卡, 缓存 sha16)`，值是 `StageMap.melee_spots` / `ranged_spots` 的投影
＋ 尺子独立数的 `counts`。为什么不并进 `("stage", …)`：那一份是拿去与 Go 的
**`load` 命令**做**递归整块对拍**的（`diff("stage", got, want)` 会把 want 里多出来的
每个键都报成「Go 缺」），而可部署格是**另一条命令**答的 ⇒ 并进去会让每一关都印一条
「Go 缺」的假失配。**两条都进冻结档**：这一段没有一个字段是「只在现场模式比」。

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


def go_spots(level: str) -> dict:
    """问 Go 要可部署格（`spots` 命令）。**失败不抛**——调用方要把「Go 取不到」分三态。

    ★ 为什么与 `go_load` 不一样：`load` 一失败就是整关读不出来，直接判红没有歧义；
      而 `spots` 这一条的失败**先要排除「数据本来就缺」**（坑①：Python 的加载器会
      按需从镜像下载并缓存）。所以这里把错误**原样带出来**给调用方去分类，
      而不是在这里 `raise SystemExit`。
    """
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "spots", "level": level,
                      "spec": {"difficulty": ""}}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        return {"ok": False, "why": "Go 进程 rc=%d：%s" % (
            p.returncode, p.stderr.decode("utf-8", "replace").strip()[:300])}
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        return {"ok": False, "why": "Go 没有回任何东西（stderr：%s）"
                % p.stderr.decode("utf-8", "replace").strip()[:200]}
    resp = json.loads(line[0])
    if not resp.get("ok"):
        return {"ok": False, "why": "Go 回 error：%s" % resp.get("error")}
    return {"ok": True, "spots": resp["spots"]}


def py_stage_expect(level: str) -> dict:
    """期望值入口：Python 那一份，按它自己的口径摊成与 Go 同形的 dict。

    ★ `ak_tactic` 的 import **写在函数体里**：冻结档下本函数不会被调到。
    """
    from ak_tactic.gamedata.stage import load_stage
    return go_side(load_stage(level), level)


# --------------------------------------------------------------- 可部署格（spots）

#: Python 那一次 `load_stage()` 的**单槽备忘**：(关卡, Stage)。
_PY_LAST: list = [None, None]


def _py_stage(level: str):
    """Python 侧的 `load_stage(level)`，**一关只解析一次**（两个键共用同一次解析）。

    ★ 为什么敢备忘：同一次运行里那一关的缓存文件不会变（`level_inputs()` 现算一次
      sha16）。备忘的只是**解析产物**，期望值的来源没变。
    ★ 为什么是**单槽**而不是整批缓存：这个循环对一关连着问两次（先 `("stage",…)`
      再 `("spots",…)`），单槽就够；换成一整批会把 562 关的 Stage 全留在内存里。
    """
    if _PY_LAST[0] != level:
        from ak_tactic.gamedata.stage import load_stage   #: 函数体内 import：冻结档不碰它
        _PY_LAST[0], _PY_LAST[1] = level, load_stage(level)
    return _PY_LAST[1]


def py_probe(level: str) -> tuple:
    """**只问一件事**：Python 取不取得到这一关（坑①：用来把「数据缺」与「Go 错」分开）。

    ★ 调它是有副作用的：Python 的关卡加载器会按需从镜像下载缺失的关卡文件并缓存到
      `data/gamedata/map.ark-nights.com/levels/…`（实测：8 个 `tr_*` 关卡在探针跑的
      窗口内落盘）⇒ 所以「Go 取不到而 Python 取到了」**不一定**是 Go 的错，
      必须**复测一次 Go**（`main()` 里就是这么做的）。
    """
    try:
        _py_stage(level)
        return True, ""
    except Exception as exc:                                   # noqa: BLE001
        return False, "%s: %s" % (type(exc).__name__, str(exc)[:200])


def ruler_counts(tiles) -> dict:
    """**尺子独立数**一遍 `buildable`：四类 ＋ 第五类。

    ★ 它是 **Go 自报的 `covered` 的第二个来源**（与 `check_stagepath_go.py:765`
      那套「Go 自报 vs 尺子独立数」同一形状）：口径照 `stage.py` 的四个取值，
      第五种取值单列一栏（对应 Go 的 `SpotsCounts.unknown`）。
      这里**不调 Go、也不抄 Go 的 `switch`**——抄一遍就是两把相同的尺子互证。
    """
    c = {k: 0 for k in ("none", "melee", "ranged", "all", "unknown")}
    for row in tiles:
        for t in row:
            c[{"NONE": "none", "MELEE": "melee", "RANGED": "ranged",
               "ALL": "all"}.get(t.buildable, "unknown")] += 1
    return c


def py_spots_expect(level: str) -> dict:
    """`spots` 那一段的期望值：**权威属性本身** ＋ 尺子独立数的一份计数。

    * `melee` / `ranged` 就是 `StageMap.melee_spots` / `ranged_spots` 的投影
      （`stage.py:141/147` 那两个属性，**不是**在判据里重写一遍它们的口径）；
    * `counts` 是 `ruler_counts()`，用来核对 Go 自报的 `covered`。

    ★ 见文件头「期望值从哪来」：这一段**进冻结档**（`("spots", 关卡, sha16)`），
      冻结档下本函数不会被调到，所以 `ak_tactic` 的 import 留在函数体里。
    """
    st = _py_stage(level)
    return {"melee": [[int(x), int(y)] for x, y in st.map.melee_spots],
            "ranged": [[int(x), int(y)] for x, y in st.map.ranged_spots],
            "counts": ruler_counts(st.map.tiles)}


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


# --------------------------------------------------------------- 反向守卫与比较

#: 三处**互相独立**的变异（`--mutate` 下三处都要「注入过 ＋ 判红过」）。
MUT_TILE_KEY = "地图键"
MUT_SPOT_CELL = "可部署格"
MUT_RULER_CNT = "尺子计数"
MUT_KEYS = (MUT_TILE_KEY, MUT_SPOT_CELL, MUT_RULER_CNT)

#: `covered` 的七栏：Go 的 `SpotsCounts` 与尺子 `ruler_counts()` 的**同名**七项。
SPOT_COVER_KEYS = ("none", "melee", "ranged", "all", "unknown",
                   "melee_spots", "ranged_spots")

#: 两条恒等式：**在 Go 自己那份读数上**查（左栏必须等于右栏各项之和）。
SPOT_IDENTITIES = (("melee_spots", ("melee", "all")),
                   ("ranged_spots", ("ranged", "all")))


class Guard:
    """反向守卫：每处变异都要「注入过 ＋ 判红过」，缺一不算成立。"""

    def __init__(self, on: bool):
        self.on = on
        self.applied = {k: False for k in MUT_KEYS}
        self.caught = {k: False for k in MUT_KEYS}
        self.at: dict = {k: None for k in MUT_KEYS}

    def want(self, key: str) -> bool:
        return self.on and not self.applied[key]

    def put(self, key: str, where) -> None:
        self.applied[key] = True
        self.at[key] = where

    def note(self, key: str, where, field_same: bool) -> None:
        if self.at[key] is not None and self.at[key] == where and not field_same:
            self.caught[key] = True


def blank_seen() -> dict:
    """行使计数的初值。**键名一次列齐**（读数里逐条印出来，不动态拼）。"""
    s = {"关卡": 0, "地图（stage）逐字段一致": 0, "可部署格（spots）逐关一致": 0,
         "melee 格": 0, "ranged 格": 0,
         "melee 格逐元素一致": 0, "ranged 格逐元素一致": 0,
         "两条恒等式": 0, "点列长度 == 自报栏": 0, "含 all 的关卡": 0,
         "数据缺（两侧都取不到）": 0,
         "Go 取不到·Python 取到·复测成功（判为 Python 补齐缓存）": 0,
         "Go 两次都取不到·Python 取到": 0,
         "Go 取不到（冻结档，无法核实）": 0}
    for k in SPOT_COVER_KEYS:
        s["covered.%s（Go）" % k] = 0
        s["covered.%s（尺子）" % k] = 0
    return s


def _cells(seq) -> list:
    """把一侧的点列规范化成 `[[x, y], …]`（JSON 回来的可能是 list，Python 侧是 tuple）。"""
    return [[int(p[0]), int(p[1])] for p in seq]


def compare_spots(tag: str, want: dict, got: dict, seen: dict, guard: Guard,
                  printed: list, cov_mismatch: list) -> int:
    """比可部署格：两张点列**逐元素、含顺序** ＋ `covered` 七栏（两个来源）＋ 恒等式。

    * `want` = 冻的期望值（`melee` / `ranged` / `counts`）；
    * `got`  = Go `spots` 命令的应答（`melee` / `ranged` / `covered`）。

    ★ 顺序**是判据的一部分**（两侧都是行主序）：所以这里**不比集合**，逐元素比，
      并把**第一个不同**的位置原样印出来——集合比对会把「顺序换了」吞掉。
    """
    bad = 0
    lens: dict = {}
    for name in ("melee", "ranged"):
        w = _cells(want[name])
        g_raw = got.get(name)
        seen["%s 格" % name] += len(w)
        if not isinstance(g_raw, list):
            bad += 1
            lens[name] = None
            printed.append("✗ %s %s：Go 的应答里没有这一栏（实得 %r）"
                           % (tag, name, g_raw))
            continue
        g = _cells(g_raw)
        lens[name] = (len(g), len(w))
        if name == "melee" and guard.want(MUT_SPOT_CELL) and w:
            #: 变异「可部署格」：把**期望值的一个格**改掉（只注入一次）。
            #: 只改本地的副本 `w`（比的是它）——**不写回** `want`：
            #: 在 check 档下 `want` 就是冻档里那个对象，写回等于改基线内存。
            w[0][0] += 1
            guard.put(MUT_SPOT_CELL, tag)
        first = next((i for i in range(min(len(g), len(w))) if g[i] != w[i]), None)
        same = (len(g) == len(w) and first is None)
        guard.note(MUT_SPOT_CELL, tag, same)
        if len(g) != len(w):
            bad += 1
            printed.append("✗ %s %s 格数：Go=%d Python=%d"
                           % (tag, name, len(g), len(w)))
        if first is not None:
            bad += 1
            printed.append("✗ %s %s 第 %d 格起不同：Go=%r Python=%r"
                           % (tag, name, first, g[first], w[first]))
        if same:
            seen["%s 格逐元素一致" % name] += 1

    gc = got.get("covered")
    if not isinstance(gc, dict):
        bad += 1
        printed.append("✗ %s covered：Go 的应答里没有这一栏（实得 %r）" % (tag, gc))
        return bad
    #: 尺子那一份：`counts` 是**独立数**出来的，`melee_spots`/`ranged_spots` 用
    #: 权威属性的**点列长度**（不是 Go 自报的那个数）。
    ruler = dict(want["counts"])
    ruler["melee_spots"] = len(want["melee"])
    ruler["ranged_spots"] = len(want["ranged"])
    if ruler["all"]:
        #: `all` 是这一段的靶子 ⇒ 单独数一遍「有几关真的带 ALL 格」（比格数更有说服力：
        #: 格数可能是同一关的几十格）。**在变异之前**数，免得被 `MUT_RULER_CNT` 影响。
        seen["含 all 的关卡"] += 1
    if guard.want(MUT_RULER_CNT):
        #: 变异「尺子计数」：把尺子那一栏改一个数 ⇒ 两个来源必须不再相等。
        ruler["melee"] += 1
        guard.put(MUT_RULER_CNT, tag)
    n_before = len(cov_mismatch)
    for k in SPOT_COVER_KEYS:
        gv = gc.get(k)
        wv = int(ruler[k])
        seen["covered.%s（Go）" % k] += int(gv or 0)
        seen["covered.%s（尺子）" % k] += wv
        if gv != wv:
            cov_mismatch.append("%s covered.%s：Go 自报 %r，尺子数出 %d"
                                % (tag, k, gv, wv))
    guard.note(MUT_RULER_CNT, tag, len(cov_mismatch) == n_before)

    #: ---- 自洽：两条恒等式 ＋ 「点列长度 == 自报的那两栏」（都在 **Go 自己那份读数**上）
    for tot, parts in SPOT_IDENTITIES:
        seen["两条恒等式"] += 1
        lhs = gc.get(tot)
        rhs = sum(int(gc.get(p) or 0) for p in parts)
        if lhs != rhs:
            bad += 1
            printed.append("✗ %s 恒等式 %s == %s 在 Go 自己那份读数上不成立：%r ≠ %d"
                           % (tag, tot, " + ".join(parts), lhs, rhs))
    for name, tot in (("melee", "melee_spots"), ("ranged", "ranged_spots")):
        seen["点列长度 == 自报栏"] += 1
        ln = lens.get(name)
        if ln is None or gc.get(tot) != ln[0]:
            bad += 1
            printed.append("✗ %s 点列长度与自报的 %s 对不上：Go 点列 %r ／ covered.%s=%r"
                           % (tag, tot, None if ln is None else ln[0], tot, gc.get(tot)))
    return bad


def main() -> int:
    mutate = "--mutate" in sys.argv
    if mutate and GB.mode() != GB.OFF:
        #: ★ `--mutate` 是**把变异直接写进期望值**的（底下那三处）。在 record 档下
        #: 那等于**把变异录进基线**——跑一次守卫就把 oracle 写坏了。本仓记过
        #: 「生成物被静默覆盖，没有历史」⇒ 这里不让它发生，而不是写进文档里提醒。
        #: ⚠ 这道检查**必须排在 `GB.bind()` 之前**：bind 在 record 档下会挂 atexit
        #: 落盘钩子，拒跑之后再触发就是一条「收下来的值无处可去」的通道错噪声。
        print("★ `--mutate` 与冻结通道的 record/check 档**不能同时用**：变异会经 "
              "`expect()` 落进基线。当前 RIOS_GOLDEN=%s。" % GB.mode())
        return 1
    G = GB.bind("关卡", __file__)
    args = [a for a in sys.argv[1:] if not a.startswith("-")]
    levels = args or ["main_00-01"]

    #: ---- 坑②：引擎的取数根。本判据把 `RIOS_DATA` 显式指到**绝对路径**，所以 cwd
    #: 不绑它（四种组合的实测见文件头）；真正的要求是**那棵树在场**（worktree 里靠
    #: junction）。不在场就**具名拒跑**——否则每一关都会以「Go 进程 rc=1」的样子出现，
    #: 而那是判据缺输入，不是 Go 的问题。
    if not (DATA / "_level_index.json").is_file():
        print("★ 引擎的 gamedata 不在场：%s 不存在 ⇒ 这一批读数**作废**"
              "（不是 Go 错，是判据自己缺输入）。" % (DATA / "_level_index.json"))
        print("  worktree 里 `data/` 是 gitignore 的，挂 junction：")
        print("    New-Item -ItemType Junction -Path <worktree>\\data -Target <主仓>\\data")
        return 1

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
    #: ★ 判红的关卡用**集合**记，不用布尔位：下面有三处 `continue` 会跳过循环尾，
    #: 布尔位那种写法实测会把它们漏掉 ⇒ 结论行印「N / N 关逐字段一致」而 rc=1
    #: （同一个数两个意思，本仓禁的那种）。
    bad_levels: set = set()
    seen = blank_seen()
    guard = Guard(mutate)
    cov_mismatch: list[str] = []

    for rec in to_cmp:
        level = rec["level"]
        got = go_load(level)
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由上面那条对账如实报出，
        #: 而不是拿一份旧内容的期望值去比新内容（那会造出一条假红）。
        want = G.expect(("stage", level, rec["sha16"]),
                        lambda level=level: py_stage_expect(level))
        if guard.want(MUT_TILE_KEY):
            # 反向守卫：把**期望值**的一格地图键改掉，判据**必须**红。
            want["map"]["tiles"][0][0]["key"] = "<mutated>"
            guard.put(MUT_TILE_KEY, (level,))
        out: list[str] = []
        diff("stage", got, want, out)
        guard.note(MUT_TILE_KEY, (level,), not out)
        #: ⚠ 这一行与加 spots 之前**逐字相同**（本轮只在下面**追加**，不改既有读数）。
        head = ("  ✓ %-14s 地图 %dx%d，路线 %d，出怪 %d，分支 %d"
                % (level, got["map"]["width"], got["map"]["height"],
                   len(got["routes"]), len(got["spawns"]), len(got["branches"])))
        if out:
            bad += 1
            bad_levels.add(level)
            print("✗ %s —— %d 处不一致" % (level, len(out)))
            for line in out[:40]:
                print("    " + line)
        else:
            seen["地图（stage）逐字段一致"] += 1
            print(head)

        #: ---- 可部署格：**另一条命令**（`spots`）答的，期望值走另一个 tag
        want_s = G.expect(("spots", level, rec["sha16"]),
                          lambda level=level: py_spots_expect(level))
        got_s = go_spots(level)
        if not got_s["ok"]:
            #: 坑①：Go 取不到时**也去调一次 Python**，三种情形分开报。
            if G.mode == GB.CHECK:
                seen["Go 取不到（冻结档，无法核实）"] += 1
                bad += 1
                bad_levels.add(level)
                print("✗ %s spots：Go 取不到，而冻结档**不 import Python**、没法核实"
                      "「数据在不在」 ⇒ 一律判红（不许拿「可能是数据缺」当免罪符）\n"
                      "      %s" % (level, got_s["why"]))
                continue
            py_ok, py_why = py_probe(level)
            if not py_ok:
                seen["数据缺（两侧都取不到）"] += 1
                print("  · %s spots：**两侧都取不到** ⇒ 记「数据缺」，不算红\n"
                      "      Go     %s\n      Python %s" % (level, got_s["why"], py_why))
                continue
            again = go_spots(level)
            if not again["ok"]:
                seen["Go 两次都取不到·Python 取到"] += 1
                bad += 1
                bad_levels.add(level)
                print("✗ %s spots：**Go 两次都取不到，而 Python 取得到** ⇒ 判红"
                      "（原文照抄，两种因分得开）\n"
                      "      Go 第一次 %s\n      Go 第二次 %s\n"
                      "      Python 取到了这一关" % (level, got_s["why"], again["why"]))
                continue
            seen["Go 取不到·Python 取到·复测成功（判为 Python 补齐缓存）"] += 1
            print("  · %s spots：Go 首取失败、Python 取到、**复测 Go 成功** ⇒ 判为"
                  "「Python 顺手把缓存补齐了」——不是 Go 的错（坑①：加载器会按需下载）"
                  % level)
            got_s = again
        seen["关卡"] += 1
        sp_out: list[str] = []
        b0 = bad
        bad += compare_spots(level, want_s, got_s["spots"], seen, guard,
                             sp_out, cov_mismatch)
        if bad > b0:
            bad_levels.add(level)
        else:
            seen["可部署格（spots）逐关一致"] += 1
        for line in sp_out[:40]:
            print(line)
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
    #: ⚠ 下面这一行与加 spots 之前**逐字相同**（新读数一律排在它**后面**）。
    print("已比：%d 关（传入 %d 关%s）"
          % (len(to_cmp), len(batch),
             "" if len(to_cmp) == len(batch) else "；**未覆盖 %d 关**" % (len(batch) - len(to_cmp))))

    #: ---------------------------------------------------------- 本轮新加的读数
    n_missing = seen["数据缺（两侧都取不到）"]
    print("★ 可部署格（spots，本套比的**第二条命令**）：权威＝gamedata/stage.py:141/147 "
          "的 StageMap.melee_spots / ranged_spots")
    print("   取数根（RIOS_DATA）＝%s（绝对路径；引擎没设它时才按 cwd 拼，cwd=%s）"
          % (DATA, os.getcwd()))
    print("★ 行使计数（spots）：比过 %d 关；地面 %d 格 ／ 高台 %d 格**逐元素（含顺序）**"
          "（平均 %.1f 格/关）；两条恒等式查 %d 次、点列长度自洽查 %d 次"
          % (seen["关卡"], seen["melee 格"], seen["ranged 格"],
             (seen["melee 格"] + seen["ranged 格"]) / float(seen["关卡"] or 1),
             seen["两条恒等式"], seen["点列长度 == 自报栏"]))
    print("★ 行使计数（Go 自报的 covered）：%s"
          % ", ".join("%s=%d" % (k, seen["covered.%s（Go）" % k])
                      for k in SPOT_COVER_KEYS))
    print("★ 行使计数（尺子独立数）      ：%s"
          % ", ".join("%s=%d" % (k, seen["covered.%s（尺子）" % k])
                      for k in SPOT_COVER_KEYS))
    cls = ("none", "melee", "ranged", "all", "unknown")
    hit = [k for k in cls if seen["covered.%s（尺子）" % k]]
    zero = [k for k in cls if not seen["covered.%s（尺子）" % k]]
    print("★ buildable 覆盖（尺子数，%d / %d 类）：%s"
          % (len(hit), len(cls),
             " ／ ".join("%s=%d" % (k, seen["covered.%s（尺子）" % k]) for k in cls)))
    print("   · `all`（地面与高台都能放）：%d 格 / %d 关 —— 这一类是这一段的靶子"
          "（`ALL` 落进「两种都不能」那次事故：整图零可部署格、搜索给 0 条结果）"
          % (seen["covered.all（尺子）"], seen["含 all 的关卡"]))
    if zero:
        print("   · ★ **未覆盖（具名）**：%s —— 本批 0 个样本" % "、".join(zero))
    if "unknown" in zero:
        print("     · `unknown` 是**第五种取值**那一栏：真数据里没有它 ⇒ 登记为未覆盖，"
              "**不判红**（判红＝永久假红）。Go 那一栏的比对是活的，只是这一批 0 样本。")
    for k, label in (("数据缺（两侧都取不到）", "两侧都取不到 ⇒ 数据缺（不算红）"),
                     ("Go 取不到·Python 取到·复测成功（判为 Python 补齐缓存）",
                      "Go 首取失败、Python 补齐、复测成功（不算红）"),
                     ("Go 两次都取不到·Python 取到", "两次都取不到而 Python 取到（已判红）"),
                     ("Go 取不到（冻结档，无法核实）", "冻结档无法核实（已判红）")):
        if seen[k]:
            print("   · Go 取不到的分栏「%s」：%d 关" % (label, seen[k]))

    #: ★ `all` 的覆盖守卫**只在全量批次上判红**：单关/抽样调用（脚本文档里那两条
    #: `python tools\check_stage_go.py main_00-01`）本来就常常没有 ALL 格，在那里判红
    #: ＝永久假红（本仓：永久假红等于没有判据）。判别式＝这一批是不是**缓存可达的
    #: 全部关卡**（与总入口 `check_go_all` 同一份清单，不在这里抄第二份）。
    try:
        from check_go_all import cached_levels                   # noqa: PLC0415
        full_batch = sorted(r["level"] for r in batch) == sorted(cached_levels())
    except Exception:                                            # noqa: BLE001
        full_batch = False
    if full_batch and seen["covered.all（尺子）"] == 0:
        print("结论：**全量批次**里 `all` 一个样本都没有 —— 判红"
              "（不是实现错，是这一批不再覆盖它）")
        return 1

    if mutate:
        print()
        print("反向守卫（三处**互相独立**的变异，各自必须「注入过 ＋ 判红过」）：")
        for k in MUT_KEYS:
            print("  变异「%s」：注入=%s 判红=%s"
                  % (k, "是" if guard.applied[k] else "否",
                     "是" if guard.caught[k] else "否"))
        miss = [k for k in MUT_KEYS if not (guard.applied[k] and guard.caught[k])]
        if miss:
            print("反向守卫：不成立 ✗（没做到「注入过并且判红」：%s）" % "、".join(miss))
            return 1
        print("反向守卫：三处变异（地图键／可部署格**一个格**／尺子计数）各判红 —— 成立 ✓")
        return 0

    if cov_mismatch:
        print()
        print("★ 行使计数对不上（Go 自报的 `covered` ↔ 尺子独立数，同一个量的两个来源）：")
        for m in cov_mismatch[:12]:
            print("    ✗ %s" % m)
        print("    共 %d 处" % len(cov_mismatch))
    if seen["关卡"] == 0 and len(to_cmp) > 0:
        #: 「零命中」先证明查询跑成功了：一关都没比到 ⇒ 不是绿，是判据自己瞎
        #: （或 Go 侧整批取不到）。
        print("结论：一关的可部署格都没比到（传入 %d 关）—— 判红"
              "（不是实现错，是判据自己瞎／Go 侧整批取不到）" % len(to_cmp))
        return 1
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if cov_mismatch:
        print("结论：Go 自报的 covered 与尺子独立数出的不一致 —— 判红"
              "（两个来源必须相等；不等说明 Go 的计数与它的点列不是同一个口径）")
        return 1
    print("结论：%d / %d 关逐字段一致%s"
          % (len(to_cmp) - len(bad_levels) - n_missing, len(to_cmp),
             "" if not n_missing else "（另有 %d 关**两侧都取不到**，记数据缺、未比）"
             % n_missing))
    if bad:
        #: 覆盖部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 覆盖部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
