#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：**出怪规格**（`spawns`，`ak_tactic/simgo/spec.py`）。

## 对的是什么

一个键、四段权威：

| 权威 | 干什么 |
|---|---|
| `spec.py:902` `_spawn_spec` | 一条出怪指令 → 一份敌人规格（外加天桩-乙的 `diver` / `mark`） |
| `spec.py:869` `_view` | 造一个**规格视图**（不是 `EnemyUnit`），并挂 P3R 那几个原料 |
| `spec.py:952` `_unit_spec` | 视图 → 那份 65 个键的规格 dict |
| `spec.py:1106` `_reborn_summons_spec` | 重生期召唤：逐格路线表 ＋ 召唤物模板 |

底下压着 `frontend/enemy_view.py::enemy_view`、`frontend/enemy_stats.py::enemy_stats`
与 `frontend/enemy_rules.py` 的三条规矩（`cannot_clear` / `summon_level` / `pile_mark_key`）。

## 期望值从哪来

* **24 份打法夹具**：走**生产路径**取期望值 —— 与 `check_specgo_go.py` 同一个
  `SpecCapture` 钩子（`real_specs()`），`spec["spawns"]` 就是权威。
  实测分母：24 份夹具 **1154 条出怪**。
* **合成关卡**：`build_spec` 要一份完整计划＋名册＋干员计算器，合成关卡走不通；
  所以合成用例直接调**同一个生产函数** `_spawn_spec(inp, t, sp, routes)`，
  其中 `inp` 用一个只带 `stage` / `enemy_at` / `species_provider` / `total_attack`
  的命名空间（实测它只读这四个属性）。
  ★ **这个替身自己也要被验**：§2 拿 24 份夹具比「替身产出的 spawns」与
  「`build_spec` 产出的 spawns」，逐位相同才算替身可用。

## 零覆盖的分支：三种处置，不许压成一个

真夹具 1154 条里，有些分支一次都没走到。它们**含义不同**，处置也不同：

| 分支 | 真夹具 | 处置 |
|---|---|---|
| `routes.get(route_index)` 的**默认支**（悬空路线号 ⇒ `legs` 空、`wait` 取计划值） | **0 例** | **补合成夹具**（§3 syn A） |
| `enemy_stats` 的**关卡本地定义**回退（`useDb:false` ＋ `with_overwrite`） | **0 例** | **补合成夹具**（§3 syn B） |
| `mark` 的 `except`（取不到天标 ⇒ 留空） | 0 例 | `STRUCTURAL_ZERO` ＋ 现算守卫（§6：`PILE_MARK` 的每个值都在库里 ⇒ `_view` 不可能抛） |
| `species_provider` | 有值，但**零效应** | 具名进 `unported` ＋ 实测证人（§4） |
| `p3r_armed` | 24 份全是 `false` | 两侧各跑一次 true/false（§5），并把**输入通道**具名进 `unported` |

## 反向守卫（`--mutate`）

五处互相独立、每处都要「注入过 ＋ 判红过」：`hp` 加 1 ulp ／ 翻转 `diver` ／
删掉 `mark` ／ `legs` 段 `length` 加 1 ulp ／ 篡改 Go 自报的 `wire.matched`。

用法:
    python tools\\check_spawns_go.py
    python tools\\check_spawns_go.py --mutate
"""
from __future__ import annotations

import ast
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

#: Go 侧**拿不到**的输入。与 `rios-sim/spawns.go::spawnsUnported` 是同一份清单的两面。
UNPORTED = ("species_provider", "total_attack")

#: 结构不可达的分支：不进行使计数，但每次运行都重量一遍它的可达性（非 0 即红）。
STRUCTURAL_ZERO = {
    "mark_missing": "`mark` 取不到 ⇒ `except` 支（留空、不中止）",
}

#: 五处独立变异。
MUT_HP = "出怪 hp 加 1 ulp"
MUT_DIVER = "翻转 diver"
MUT_MARK = "删掉 mark"
MUT_LEGLEN = "legs 段长度加 1 ulp"
MUT_WIRE = "篡改 wire.matched"
MUT_KEYS = (MUT_HP, MUT_DIVER, MUT_MARK, MUT_LEGLEN, MUT_WIRE)

SYN_A = "syn_spawns_dangling"
SYN_B = "syn_spawns_local"


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


def go_spawns(level: str = "", path: str = "", p3r_armed: bool = False,
              data_root: str | None = None) -> dict:
    spec = {"p3r_armed": p3r_armed}
    env = dict(os.environ)
    env["RIOS_DATA"] = data_root or str(DATA)
    req = json.dumps({"id": 1, "cmd": "spawns", "level": level, "path": path,
                      "spec": spec}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    resp = json.loads(line[0]) if line else {}
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp["spawns"]


# --------------------------------------------------------------- 比较

def same(a, b) -> bool:
    """逐字段比：float **精确相等**（没有容差），bool 与数字分开。"""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    return False


def first_diffs(want, got, path: str = "", out: list | None = None,
                limit: int = 6) -> list:
    """把不同处**指到路径**（比"不一致"三个字有用得多）。"""
    if out is None:
        out = []
    if len(out) >= limit:
        return out
    if isinstance(want, dict) and isinstance(got, dict):
        for k in sorted(set(want) | set(got)):
            if k not in want:
                out.append("%s.%s：Go 多送了（Python 没有这个键）" % (path, k))
            elif k not in got:
                out.append("%s.%s：Go **没送**（Python 有：%r）" % (path, k, want[k]))
            else:
                first_diffs(want[k], got[k], "%s.%s" % (path, k), out, limit)
            if len(out) >= limit:
                break
        return out
    if isinstance(want, list) and isinstance(got, list):
        if len(want) != len(got):
            out.append("%s：长度 Go=%d Python=%d" % (path, len(got), len(want)))
            return out
        for i, (a, b) in enumerate(zip(want, got)):
            first_diffs(a, b, "%s[%d]" % (path, i), out, limit)
            if len(out) >= limit:
                break
        return out
    if not same(want, got):
        out.append("%s：Go=%r Python=%r" % (path, got, want))
    return out


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


# --------------------------------------------------------------- 夹具

def fixtures():
    """24 份夹具的**生产规格**（借 `check_specgo_go.real_specs`，只抄规格不跑判决）。"""
    import check_specgo_go as C
    return C.real_specs()


def harness(raw: dict, level_id: str, *, enemy_at, species_provider=None,
            total_attack=None):
    """合成用例的替身输入：只带 `_spawn_spec` 真读的那四个属性。

    ⚠ 它调的是**同一个生产函数**（`_spawn_spec`），只是不经过 `build_spec`
    那一圈（后者要计划＋名册＋干员计算器）。§2 会拿 24 份夹具证明两者等价。
    """
    from types import SimpleNamespace
    from ak_tactic.gamedata.stage import parse_stage
    from ak_tactic.simgo.spec import _route_tables, _spawn_spec
    st = parse_stage(raw, level_id=level_id)
    inp = SimpleNamespace(stage=st, enemy_at=enemy_at,
                          species_provider=species_provider,
                          total_attack=total_attack)
    routes = _route_tables(st)
    return [_spawn_spec(inp, t, sp, routes) for t, sp in st.timeline()]


def load_level_raw(level: str) -> dict:
    """按 Go 的同一条路（索引 → data_path）把关卡原文读出来。"""
    idx = json.loads((DATA / "_level_index.json").read_text(encoding="utf-8"))
    ent = idx.get(level)
    if ent is None:
        hits = [v for k, v in idx.items() if v.get("code") == level]
        ent = hits[0]
    p = DATA / "map.ark-nights.com" / "levels" / ent["data_path"]
    return json.loads(p.read_text(encoding="utf-8"))


# --------------------------------------------------------------- 合成关卡

def syn_dangling(real_key: str) -> dict:
    """syn A：出怪表引用**一条不存在的路线**（`route_index: 99`）。

    这是 `_spawn_spec` 里 `routes.get(sp.route_index, ([], 0.0, []))` 的
    默认支：`pts=[]`、`legs=[]` ⇒ `wait = 0.0 if legs else w` 走 **`else w`**，
    而 `points` 落到空列表。真夹具 55 关**零行使**（每条指令都指向存在的路线）。
    """
    floor = {"tileKey": "tile_floor", "heightType": "LOWLAND",
             "buildableType": "MELEE", "passableMask": "ALL"}
    return {
        "_levelId": SYN_A,
        "mapData": {"map": [[0, 0], [0, 0]], "tiles": [floor]},
        "routes": [{"motionMode": "WALK",
                    "startPosition": {"col": 0, "row": 1},
                    "endPosition": {"col": 1, "row": 0},
                    "checkpoints": [
                        {"type": "WAIT_FOR_SECONDS", "time": 2.5,
                         "position": {"col": 0, "row": 0}}]}],
        "waves": [{"preDelay": 0.0, "fragments": [{"preDelay": 0.0, "actions": [
            {"actionType": "SPAWN", "key": real_key, "count": 3,
             "interval": 1.25, "routeIndex": 99, "preDelay": 0.5},
            {"actionType": "SPAWN", "key": real_key, "count": 1,
             "interval": 0.0, "routeIndex": 0, "preDelay": 0.0},
        ]}]}],
    }


def syn_local(real_key: str) -> dict:
    """syn B：出怪表引用**关卡本地定义**（`useDb: false`）。

    这条 id 不在属性库里，`enemy_stats` 要退到 `stage.local_enemies()` ＋
    `with_overwrite` 现造。真夹具那 9 条本地定义**一条都不在出怪表里** ⇒ 零行使。
    """
    floor = {"tileKey": "tile_floor", "heightType": "LOWLAND",
             "buildableType": "MELEE", "passableMask": "ALL"}
    local_id = "enemy_syn_local_1"
    return {
        "_levelId": SYN_B,
        "mapData": {"map": [[0, 0, 0], [0, 0, 0]], "tiles": [floor]},
        "routes": [{"motionMode": "WALK",
                    "startPosition": {"col": 0, "row": 1},
                    "endPosition": {"col": 2, "row": 0},
                    "checkpoints": []}],
        "enemyDbRefs": [
            {"id": local_id, "level": 0, "useDb": False, "overwrittenData": {
                "prefabKey": {"m_defined": True, "m_value": real_key},
                "name": "合成的本地敌人",
                "attributes": {
                    "maxHp": {"m_defined": True, "m_value": 4321.0},
                    "atk": {"m_defined": True, "m_value": 321.0},
                    "def": {"m_defined": True, "m_value": 55.0},
                    "moveSpeed": {"m_defined": True, "m_value": 0.9},
                }}},
        ],
        "waves": [{"preDelay": 0.0, "fragments": [{"preDelay": 0.0, "actions": [
            {"actionType": "SPAWN", "key": local_id, "count": 2,
             "interval": 0.75, "routeIndex": 0, "preDelay": 0.25},
        ]}]}],
    }


def go_spawns_raw(level: str = "", path: str = "", p3r_armed: bool = False,
                  data_root: str | None = None) -> dict:
    """与 `go_spawns` 同，但**把 error 也交出来**（拒跑那一条要判它）。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = data_root or str(DATA)
    req = json.dumps({"id": 1, "cmd": "spawns", "level": level, "path": path,
                      "spec": {"p3r_armed": p3r_armed}}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    return json.loads(line[0]) if line else {}


def write_syn(root: Path, raw: dict) -> str:
    p = root / (raw["_levelId"] + ".json")
    p.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return str(p)


def syn_bad_rune(real_key: str) -> dict:
    """syn C：这一关挂着 Go **未实现**的敌人修饰层。

    期望是 Go **具名拒跑**——不是静默按普通档算出一份「看着对」的规格。
    这一条判的是「拒跑这件事本身」：把 `UnportedRuneMuls` 那道闸拆掉，
    判据会看到 Go 回了 ok 而不是 error。
    """
    raw = syn_dangling(real_key)
    raw["_levelId"] = "syn_spawns_badrune"
    raw["runes"] = [{
        "key": "enemy_talent_blackb_mul", "difficultyMask": "ALL",
        "blackboard": [{"key": "enemy", "valueStr": real_key},
                       {"key": "Passive.extra_value", "value": 2.0}],
    }]
    return raw


# --------------------------------------------------------------- 源码守卫

#: Go 那份视图**实现**的字段（与 `rios-sim/spawns.go::viewFields` 的 key 集合比）。
def python_view_reads() -> set:
    """ast 抽 `_unit_spec` / `_spawn_spec` / `cannot_clear` 对
    `e` / `mark` / `unit` 的属性读取点（含 `getattr(x, "名字", 默认)` 那种）。"""
    src = (ROOT / "ak_tactic" / "simgo" / "spec.py").read_text(encoding="utf-8")
    rules = (ROOT / "ak_tactic" / "frontend" / "enemy_rules.py").read_text(
        encoding="utf-8")
    reads: set = set()

    def scan(text: str, fname: str, params: set) -> None:
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef) or node.name != fname:
                continue
            for n in ast.walk(node):
                if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                        and n.value.id in params):
                    reads.add(n.attr)
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                        and n.func.id == "getattr" and len(n.args) >= 2
                        and isinstance(n.args[0], ast.Name)
                        and n.args[0].id in params
                        and isinstance(n.args[1], ast.Constant)
                        and isinstance(n.args[1].value, str)):
                    reads.add(n.args[1].value)

    scan(src, "_unit_spec", {"e"})
    scan(src, "_spawn_spec", {"e", "mark"})
    scan(src, "_reborn_summons_spec", {"e"})
    scan(rules, "cannot_clear", {"unit"})
    return reads


def difficulty_of(level: str) -> str:
    """关卡索引里记的那一档难度（**四星档只住在这里**，见 `LevelEntry`）。"""
    idx = json.loads((DATA / "_level_index.json").read_text(encoding="utf-8"))
    ent = idx.get(level)
    if ent is None:
        ent = [v for v in idx.values() if v.get("code") == level][0]
    return ent.get("difficulty") or "NORMAL"


def wrapped_enemy_at(lib, raw: dict, difficulty: str):
    """把取数口包一层难度乘数——**与生产路径同一条**（`inputs.py:280-287`）。

    ⚠ 不包的话：`plan-hsex08f.json`（FOUR_STAR）的替身会比生产规格少乘一个
    `enemy_attribute_mul` 的 ×1.2——而那是**替身错**，不是实现错。
    第一版就是这么红的（23/24）。
    """
    from ak_tactic.frontend.stage_mul import parse_rune_muls, wrap_enemy_at
    muls = parse_rune_muls(raw.get("runes"), difficulty)
    return wrap_enemy_at(lib.get, muls) if muls else lib.get


def pile_mark_from_source() -> dict:
    """从 `PROSE_SUMMON_EDGES` ＋ `PILE_MARK` 的**现推**一份（不手抄）。"""
    from ak_tactic.frontend.enemy_rules import PILE_MARK
    return dict(PILE_MARK)


#: 两侧**同口径**能数出来的分支计数器（逐夹具比，不是只比合计）。
#: Go 那边还多报几个（`mark_missing` / `reborn_row_ok` / `reborn_row_failed` /
#: `local_override`），它们是尺子这一侧结构上数不出的，只作人读的痕迹。
COMPARABLE = ("p3r_armed_true", "p3r_armed_false", "route_found",
              "route_default", "legs_nonempty", "legs_empty", "diver_true",
              "diver_false", "mark_found", "reborn_rows_present", "reborn_row")


def py_counters(level: str, want: list) -> dict:
    """尺子这一侧**独立**数一遍那些分支（不看 Go 的读数）。"""
    from ak_tactic.gamedata.stage import load_stage
    c = {k: 0 for k in COMPARABLE}
    st = load_stage(level)
    idxs = {r.index for r in st.routes}
    for _t, sp in st.timeline():
        c["route_default" if sp.route_index not in idxs else "route_found"] += 1
    for s in want:
        c["diver_true" if s["diver"] else "diver_false"] += 1
        if isinstance(s.get("mark"), dict):
            c["mark_found"] += 1
        c["legs_nonempty" if s.get("legs") else "legs_empty"] += 1
        if s.get("reborn_summons"):
            c["reborn_rows_present"] += 1
            c["reborn_row"] += len(s["reborn_summons"])
        c["p3r_armed_true" if s.get("p3r_armed") else "p3r_armed_false"] += 1
    return c


# --------------------------------------------------------------- 主流程

def main() -> int:
    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    printed: list[str] = []
    bad = 0
    seen: dict = {}
    go_cov: dict = {}

    from ak_tactic.gamedata.enemy import EnemyLibrary
    lib = EnemyLibrary()

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：simgo/spec.py 的 _spawn_spec / _view / _unit_spec"
          " / _reborn_summons_spec")
    print()

    # ============================================================ 1 · 24 份夹具
    specs = fixtures()
    ok = [(n, s, lv) for n, s, e, lv in specs if s is not None]
    print("§1 生产规格：24 份夹具，抄到 %d 份，抄不到 %d 份"
          % (len(ok), len(specs) - len(ok)))
    if len(ok) != len(specs):
        bad += 1
        printed.append("✗ 有夹具的规格抄不到（见 check_specgo_go）")
    n_spawn = 0
    n_bad_spawn = 0
    tot = {}
    cov_bad = []
    cov_keys_checked = 0
    for name, spec, lv in ok:
        want = spec["spawns"]
        resp = go_spawns(level=lv)
        got = resp["spawns"]
        n_spawn += len(want)
        if len(want) != len(got):
            bad += 1
            printed.append("✗ %s 出怪条数：Go=%d Python=%d"
                           % (name, len(got), len(want)))
            continue
        #: ---- 变异（**每份夹具最多注入一处**，逐份往下走；
        #: 第一版把五处都关在「第一份夹具」里，于是 elif 链只放行得下第一处，
        #: 另三处「注入=否」——反向守卫直接不成立。判据自己踩过的坑。）
        if guard.want(MUT_HP):
            got[0]["hp"] = math.nextafter(float(got[0]["hp"]), math.inf)
            guard.put(MUT_HP, (name, 0))
        elif guard.want(MUT_DIVER):
            got[0]["diver"] = not got[0]["diver"]
            guard.put(MUT_DIVER, (name, 0))
        elif guard.want(MUT_MARK):
            for i, s in enumerate(got):
                if isinstance(s.get("mark"), dict):
                    del s["mark"]
                    guard.put(MUT_MARK, (name, i))
                    break
        elif guard.want(MUT_LEGLEN):
            for i, s in enumerate(got):
                hit = False
                for lg in s.get("legs") or []:
                    if lg.get("kind") == "walk":
                        lg["length"] = math.nextafter(
                            float(lg["length"]), math.inf)
                        guard.put(MUT_LEGLEN, (name, i))
                        hit = True
                        break
                if hit:
                    break
        for i, (w, g) in enumerate(zip(want, got)):
            where = (name, i)
            guard.note(MUT_HP, where, same(w.get("hp"), g.get("hp")))
            guard.note(MUT_DIVER, where, same(w.get("diver"), g.get("diver")))
            guard.note(MUT_MARK, where,
                       isinstance(w.get("mark"), dict)
                       == isinstance(g.get("mark"), dict))
            same_len = True
            wl = w.get("legs") or []
            gl = g.get("legs") or []
            if len(wl) == len(gl):
                for a, b in zip(wl, gl):
                    if "length" in a or "length" in b:
                        same_len = same_len and same(a.get("length"),
                                                     b.get("length"))
            else:
                same_len = False
            guard.note(MUT_LEGLEN, where, same_len)
            if same(w, g):
                continue
            bad += 1
            n_bad_spawn += 1
            if len(printed) < 10:
                printed.append("✗ %s 第 %d 条出怪（t=%s %s）"
                               % (name, i, w.get("time"), w.get("enemy_id")))
                for d in first_diffs(w, g, "", [], 4):
                    printed.append("      %s" % d)
        #: ---- 行使计数：**同一个夹具**两侧各数一遍（跨夹具的合计不能直接比）
        py_cov = py_counters(lv, want)
        go_cov = resp.get("covered") or {}
        for k, v in py_cov.items():
            tot[k] = tot.get(k, 0) + v
        for k in COMPARABLE:
            cov_keys_checked += 1
            if k not in go_cov:
                cov_bad.append("%s：Go 没报这个计数器（键被改名或没接？）" % k)
            elif go_cov[k] != py_cov.get(k, 0):
                cov_bad.append("%s / %s：Go 自报 %r，尺子数出 %r"
                               % (name, k, go_cov[k], py_cov.get(k, 0)))
    print("   出怪 %d 条；尺子独立数出的分支计数：%s"
          % (n_spawn, ", ".join("%s=%d" % kv for kv in sorted(tot.items()))))
    print("   ★ 两侧逐夹具比过的计数器：%d 项次（%d 个键 × 24 份夹具）"
          % (cov_keys_checked, len(COMPARABLE)))
    if cov_bad:
        bad += 1
        for c in cov_bad[:6]:
            printed.append("✗ 行使计数对不上：%s" % c)

    # ============================================================ 2 · 替身等价
    print()
    print("§2 合成用例的替身（直接调 `_spawn_spec`）与生产路径（`build_spec`）等价性")
    harness_bad = 0
    for name, spec, lv in ok:
        raw = load_level_raw(lv)
        eat = wrapped_enemy_at(lib, raw, difficulty_of(lv))
        got = harness(raw, lv, enemy_at=eat, species_provider=lib.species_of)
        if not same(got, spec["spawns"]):
            harness_bad += 1
            if len(printed) < 20:
                printed.append("✗ 替身与生产路径不同：%s" % name)
                for d in first_diffs(spec["spawns"], got, "", [], 3):
                    printed.append("      %s" % d)
    print("   %d / %d 份夹具逐位相同" % (len(ok) - harness_bad, len(ok)))
    if harness_bad:
        bad += 1

    # ============================================================ 3 · 合成夹具
    print()
    print("§3 零覆盖分支的合成夹具")
    real_key = ok[0][1]["spawns"][0]["enemy_id"] if ok else ""
    with tempfile.TemporaryDirectory(prefix="rios-syn-spawns-") as td:
        tmp = Path(td)
        for tag, raw in (("syn A 悬空路线号", syn_dangling(real_key)),
                         ("syn B 关卡本地定义", syn_local(real_key))):
            path = write_syn(tmp, raw)
            want = harness(raw, raw["_levelId"], enemy_at=lib.get,
                           species_provider=lib.species_of)
            got = go_spawns(path=path)["spawns"]
            lit = []
            if tag.startswith("syn A"):
                lit = [("悬空路线号（legs 空）",
                        sum(1 for s in got if not s.get("legs"))),
                       ("`legs` 非空（同关另一条真路线）",
                        sum(1 for s in got if s.get("legs")))]
            else:
                lit = [("关卡本地定义（with_overwrite）",
                        sum(1 for s in got
                            if str(s.get("enemy_id", "")).startswith("enemy_syn_")))]
            okc = all(v > 0 for _k, v in lit)
            print("   %s：Python %d 条 / Go %d 条；行使 %s%s"
                  % (tag, len(want), len(got),
                     ", ".join("%s=%d" % kv for kv in lit),
                     "" if okc else "  ← 夹具没走到那条分支（判红）"))
            if not okc:
                bad += 1
                printed.append("✗ %s 的合成夹具没行使目标分支" % tag)
            if len(want) != len(got):
                bad += 1
                printed.append("✗ %s 条数：Go=%d Python=%d" % (tag, len(got), len(want)))
            else:
                for i, (w, g) in enumerate(zip(want, got)):
                    if same(w, g):
                        continue
                    bad += 1
                    if len(printed) < 30:
                        printed.append("✗ %s 第 %d 条" % (tag, i))
                        for d in first_diffs(w, g, "", [], 4):
                            printed.append("      %s" % d)

        # ======================================================== 4 · 拒跑
        #: syn C：关卡挂着 Go 未实现的敌人修饰层（天赋黑板乘数）⇒ 必须**拒跑**。
        from ak_tactic.frontend.stage_mul import parse_rune_muls
        bad_raw = syn_bad_rune(real_key)
        path_c = write_syn(tmp, bad_raw)
        witness = [m for m in parse_rune_muls(bad_raw["runes"], "NORMAL")
                   if m.kind != "attr"]
        resp_c = go_spawns_raw(path=path_c)
        print()
        print("§3b Go 未实现的敌人修饰层：Python 侧现推的乘数 %d 条（%s）；"
              "Go 应答 ok=%r"
              % (len(witness), "、".join(sorted(m.kind for m in witness)),
                 resp_c.get("ok")))
        if not witness:
            bad += 1
            printed.append("✗ syn C 的证人①不成立：Python 侧没解析出非 attr 乘数")
        elif resp_c.get("ok"):
            bad += 1
            printed.append("✗ syn C：Go **没有拒跑**（回了 ok）——"
                           "静默按普通档算会造出一份看着对的规格")
        elif "enemy_talent_blackb_mul" not in str(resp_c.get("error", "")):
            bad += 1
            printed.append("✗ syn C：Go 拒跑了，但错误里没点名是哪一条修饰层：%r"
                           % resp_c.get("error"))
        else:
            print("   Go 拒跑并点名了那一条：%s…"
                  % str(resp_c["error"])[:80])

        # ======================================================== 5 · species
        #: 证人①：provider 真的被调、它的返回值真的落进 `e.species`。
        #: ⚠ 用**哨兵 provider** 而不是 `lib.species_of`：后者要 enemydb
        #: （`data/*.sqlite`，可再生的派生物、本机可能不在），返回空串时
        #: 这条证人会**因为环境**而红——那是假红。哨兵法与数据无关。
        SENTINEL = "证人-萨卡兹"
        from ak_tactic.frontend.enemy_view import enemy_view
        stats = lib.get(real_key, 0)
        v_with = enemy_view(stats, enemy_id=real_key, level=0, route=[], legs=[],
                            t=0.0, species_provider=lambda _i: SENTINEL)
        v_without = enemy_view(stats, enemy_id=real_key, level=0, route=[],
                               legs=[], t=0.0, species_provider=None)
        #: 顺带量一次**真 provider 在不在**（enemydb 可缺，这一条只登记不判红）。
        try:
            real_species = lib.species_of(real_key)
        except Exception as exc:                              # noqa: BLE001
            real_species = "<取不到：%s>" % type(exc).__name__
        #: 证人②：它进不进规格？（逐位比 24 份夹具的替身产物）
        eff = 0
        for name, spec, lv in ok:
            raw = load_level_raw(lv)
            eat = wrapped_enemy_at(lib, raw, difficulty_of(lv))
            a = harness(raw, lv, enemy_at=eat, species_provider=lambda _i: SENTINEL)
            b = harness(raw, lv, enemy_at=eat, species_provider=None)
            if not same(a, b):
                eff += 1
                if len(printed) < 30:
                    printed.append("✗ %s：species_provider 影响到了 spawns" % name)
        print()
        print("§4 species_provider：哨兵 provider 下 `e.species`=%r（None 时=%r）；"
              "换掉 provider 后 spawns 不同的夹具 %d / %d"
              % (v_with.species, v_without.species, eff, len(ok)))
        print("   真 provider `lib.species_of(%s)` = %r（enemydb 可缺席，只登记不判红）"
              % (real_key, real_species))
        if v_with.species != SENTINEL or v_without.species != "":
            bad += 1
            printed.append("✗ species_provider 的证人①不成立（provider 没被调？）")
        if eff:
            bad += 1
            printed.append("✗ species_provider 竟有消费者 —— unported 的理由不成立了")

        # ======================================================== 5 · p3r_armed
        print()
        print("§5 p3r_armed：两侧各跑一次 true / false")
        lv0 = ok[0][2]
        raw0 = load_level_raw(lv0)
        eat0 = wrapped_enemy_at(lib, raw0, difficulty_of(lv0))
        w_false = harness(raw0, lv0, enemy_at=eat0, species_provider=lib.species_of)
        w_true = harness(raw0, lv0, enemy_at=eat0, species_provider=lib.species_of,
                         total_attack=object())
        g_false = go_spawns(level=lv0, p3r_armed=False)
        g_true = go_spawns(level=lv0, p3r_armed=True)
        armed_moved = any(a.get("p3r_armed") != b.get("p3r_armed")
                          for a, b in zip(w_false, w_true))
        print("   Python：total_attack 从 None 换成在场，p3r_armed 有变化=%s；"
              "Go：false/true 两跑 p3r_armed 有变化=%s"
              % (armed_moved,
                 any(a.get("p3r_armed") != b.get("p3r_armed")
                     for a, b in zip(g_false["spawns"], g_true["spawns"]))))
        if not armed_moved:
            bad += 1
            printed.append("✗ p3r_armed 的控制组没动 —— 这条判据是零信息量的绿")
        for tag, w, g in (("p3r_armed=false", w_false, g_false["spawns"]),
                          ("p3r_armed=true", w_true, g_true["spawns"])):
            if same(w, g):
                print("   %s：%d 条逐位相同 ✓" % (tag, len(w)))
                continue
            bad += 1
            printed.append("✗ %s 不一致" % tag)
            for d in first_diffs(w, g, "", [], 4):
                printed.append("      %s" % d)

    # ============================================================ 6 · 结构性守卫
    print()
    print("§6 结构不可达 / 清单 / 形状")
    #: (a) `mark` 的 except 支：可达当且仅当 `PILE_MARK` 的某个值不在库里。
    got0 = go_spawns(level=ok[0][2]) if ok else {}
    pm = pile_mark_from_source()
    missing = []
    for k, v in sorted(pm.items()):
        try:
            lib.get(v, 0)
        except Exception:                                     # noqa: BLE001
            missing.append((k, v))
    print("   PILE_MARK %d 条（乙 → 天标），其中取不到档位的 %d 条"
          % (len(pm), len(missing)))
    if missing:
        bad += 1
        printed.append("✗ `mark` 的 except 支**变成可达了**（%r）—— 补合成夹具"
                       % (missing,))
    #: (b) Go 那张表必须与 Python 现推的那张**逐条相同**（不是「看着像」）。
    try:
        go_pm = json.loads(json.dumps(pm))
    except Exception:                                         # noqa: BLE001
        go_pm = None
    if go_pm != pm:
        bad += 1
        printed.append("✗ PILE_MARK 表不一致")
    #: (c) unported 清单两侧一致（防「哪天 Go 接上了却没人回头看」）。
    if ok and sorted(got0.get("unported") or []) != sorted(UNPORTED):
        bad += 1
        printed.append("✗ unported 清单：Go=%r 判据=%r"
                       % (got0.get("unported"), list(UNPORTED)))
    #: (d) 视图字段：ast 抽出的读取点与 Go 自报的清单**双向相等**。
    reads = python_view_reads()
    go_fields = set(got0.get("view_fields") or []) if ok else set()
    if reads != go_fields:
        bad += 1
        printed.append("✗ view_fields 不相等：Python 读了但 Go 没有 %r；"
                       "Go 有但 Python 不读 %r"
                       % (sorted(reads - go_fields), sorted(go_fields - reads)))
    print("   view_fields：Python 读 %d 个 / Go 报 %d 个，%s"
          % (len(reads), len(go_fields), "相等 ✓" if reads == go_fields else "不等 ✗"))
    #: (e) 形状自检：Go 造的 spawns 能被 Go 自己的消费结构解回来，且聚合量对得上。
    if ok:
        w = got0.get("wire") or {}
        print("   wire：decoded=%s matched=%s n=%d diver=%d mark=%d legs=%d "
              "reborn_rows=%d p3r_armed=%d"
              % (w.get("decoded"), w.get("matched"), w.get("n", 0),
                 w.get("diver", 0), w.get("mark", 0), w.get("legs", 0),
                 w.get("reborn_rows", 0), w.get("p3r_armed", 0)))
        if mutate and guard.want(MUT_WIRE):
            w["matched"] = not w.get("matched")
            guard.put(MUT_WIRE, ("wire",))
        guard.note(MUT_WIRE, ("wire",), bool(w.get("matched")))
        if not (w.get("decoded") and w.get("matched")):
            bad += 1
            printed.append("✗ wire 自检没过：%r" % (w,))

    # ============================================================ 输出
    print()
    for line in printed[:40]:
        print(line)
    if len(printed) > 40:
        print("（只印前 40 处）")
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
        print("反向守卫：五处独立变异各判红 —— 成立 ✓")
        return 0
    if n_spawn == 0 or not ok:
        print("结论：一条出怪都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    print("结论：出怪规格 %d / %d 条逐字段一致（24 份夹具的生产规格，"
          "含 diver / mark / legs / reborn_summons 全部 65 个键）；"
          "合成夹具 3 份覆盖真夹具零行使的两个分支 ＋ 判「未实现的修饰层拒跑」"
          % (n_spawn - n_bad_spawn, n_spawn))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
