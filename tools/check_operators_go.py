#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：**干员规格**（`operators`，`ak_tactic/simgo/spec.py::_operator_spec`）。

## 对的是什么

`spec.py:1230-1233` 在 `sorted(sch.deployments, key=d.time)` 的循环里
`operators.append(_operator_spec(inp, d))` —— 每个**部署人次**一份干员规格。
权威是 `_operator_spec`（`spec.py:681-842`）本身，期望值走**生产路径**抄
（`check_specgo_go.real_specs` 的 `SpecCapture` 钩子），不手抄。

## 两把尺子：一把量实现，一把量尺子自己

| 尺子 | 量什么 | 红了说明什么 |
|---|---|---|
| 生产规格 `operators[i]` | Go 产出的那些键（33） | **实现错** |
| 本脚本从**活对象**现取的读数（`op.current_atk()` 等，自己写一遍表达式） | 同一批 33 个键 | **尺子错**（`_operator_spec` 读的属性里有两个说法） |

两条各自独立判定、各自报。这样「红」能归因到实现还是归因到判据
——本项目为此记过：两把相同的尺子互证不构成核对，但**一把尺子量两个对象**
才能把差归给对象。

## 为什么地基要先问一句

`_operator_spec` 的 25 个键里，13 个是 `op.<属性>` 的直接读、12 个是加条件的读。
Go 送的是 `OperatorStats.Total[...]` 那一套。**两者是不是同一个数**不是显然的：
`current_atk()` 是 `self.atk * (1 + aura + mobility + stand)`，四个旋钮任何一个
非零就不再相等。实测 64 人次四个旋钮**全零**（取规格发生在 `sim.run()` 之前），
所以 `Total["atk"] == current_atk()`。§3 每次运行重量这一条。

## 两条**现算**的结构性守卫（非 0 即红，不是「记下来的结论」）

1. `op.current_range_id()` —— 技能改写攻击范围那条。Go 侧**没有**这条路
   （它照干员自己的 `rangeId` 展开）；哪天它非空了，Go 的 range 口径就不成立。
2. `op.redeploy_time` —— `verify.py:314-355` 的 `kw` 里**没有这个键**，所以原版
   读到的恒是 `OperatorView` 的默认值 **70.0**；Go 送的就是这个常量。
   哪天它不再是 70.0（比如 `kw` 里补了 `respawnTime`），Go 必须跟着改。

## 具名 unported（2 个键）

`skill / active`（要 `skills.skill_spec` 那整段技能效果装配）。

与 Go 应答里的 `unported` 做**双向集合比对**，并每次运行重量「Python 那一侧
实际送出了其中几个」＋「Go 是不是偷偷送了一个」。

★ `shield` **已经从这张表里移出**（段 B → 段 A）：它现在**逐位比**（`_shield_of`
的五个字段），并额外配了一条**双向对照**——判据自己数一遍
「shield 非空的人次」（`live_counters`），与 Go 的 `covered.shield_nonzero` 比。
§6 仍然量着 `heals`（拿 `opstats` 的字段与生产规格**逐人次比一次**）。

## 反向守卫（`--mutate`）

九处**互相独立**的注入，每处都要「注入过 ＋ 判红过」，落在**不同字段、不同代码路径**：
① `atk` 加 1 ulp（浮点面板那条读法）；② `splash_damage_scale` 加 1 ulp
（条件块的浮点，且**必须落在真有这条特性的人次上**）；③ `cell` 的 x+1（整数坐标）；
④ 删掉一条 operator（分母由 N 变 N−1）；⑤~⑨ 段 B 那五个键各一处。
每处各自拒绝「已被别处占用的夹具」，所以是九条独立的路，不是同一条 elif 链上的九个分支。

用法:
    python tools\\check_operators_go.py
    python tools\\check_operators_go.py --mutate
"""
from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
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
ROSTER_FIX = ROOT / "fixtures" / "roster_max_modelled.json"

#: Go **产出**的 33 个键（13 无条件 ＋ 12 条件 ＋ 8 天赋派生）。
#: ★ 33 ＋ 2 ＝ **35** ＝ `wire.go::OperatorSpec` 的 json 键数，
#: §7 每次运行现数这三者并断言相等（不写死「35」这几个字）。
PORTED = (
    "char_id", "name", "cell", "max_hp", "atk", "def", "res", "interval",
    "damage_type", "block_cnt", "deploy_cost", "redeploy_time", "range",
    "nation_id", "profession",
    "splash_radius", "splash_scale", "splash_damage_scale",
    "highland_splash_scale", "highland_splash_sluggish",
    "combo_hits", "combo_hit_scale", "combo_damage_scale",
    "power_attack_count", "power_attack_scale",
    #: ---- 天赋派生（段 B 第一批）：九个 finder ＋ `TextDerived.Heals` ----
    "heals", "blessing_save", "blessing_self_freeze", "regen_aura",
    "team_auras", "talent_dodge_phys", "talent_dodge_arts",
    #: ---- 段 B 第二批：`_shield_of`（层数护盾）----
    "shield",
)

#: 仍**不产出**的 2 个键。与 `rios-sim/operators.go::OperatorUnported` 同源。
UNPORTED = ("skill", "active")

#: `unported` 里**其实已经能搬**的那些 → 为什么。★ 现已**清空**：
#: `heals` 这一批已经产出（`TextDerived.Heals`），所以这份表必须为空——
#: 一旦谁再往 `unported` 里塞一条其实能搬的，§6 会红。
UNPORTED_READY: dict = {}

#: 两条现算的结构性守卫。值是「这条守卫答的是什么」。
STRUCTURAL_ZERO = {
    "range_id_rewritten": "`op.current_range_id()` 非 None（技能改写范围那条路）",
    "redeploy_time_nondefault": "`op.redeploy_time` 不是视图默认值 70.0",
}

#: `covered` 的计数器名字——与 `operators.go::OperatorsCoveredKeys` 同名同数。
COVERED_KEYS = (
    "range_code_in_table", "range_code_missing", "range_origin_added",
    "nation_id_empty", "profession_empty",
    "splash_radius_nonzero", "highland_splash_scale_nonzero",
    "highland_splash_sluggish_nonzero",
    "combo_hits_gt1", "power_attack_count_gt0",
    #: ---- 段 B 第一批（天赋派生）----
    "heals_true", "blessing_nonzero", "regen_aura_nonzero",
    "team_auras_nonzero", "talent_dodge_nonzero",
    "regen_strict_true", "regen_strict_false",
    #: ---- 段 B 第二批 ----
    "shield_nonzero",
)

MUT_ATK = "atk 加 1 ulp"
MUT_SPLASH = "splash_damage_scale 加 1 ulp"
MUT_CELL = "cell 的 x+1"
MUT_DROP = "删掉一条 operator"
#: ---- 段 B 第一批新增的四条（各自落在**不同的键**上，不挤在一条 elif 链里）----
MUT_HEALS = "翻转 heals"
MUT_AURA = "team_auras[0].atk_pct 加 1 ulp"
MUT_REGEN = "regen_aura.hp_per_sec 加 1 ulp"
MUT_DODGE = "talent_dodge_phys 加 1 ulp"
MUT_SHIELD = "shield.max_layers 加 1"
MUT_KEYS = (MUT_ATK, MUT_SPLASH, MUT_CELL, MUT_DROP,
            MUT_HEALS, MUT_AURA, MUT_REGEN, MUT_DODGE, MUT_SHIELD)

MIN_INTERVAL = 0.05
ASPD_MIN = 20.0
#: `OperatorView.redeploy_time` 的默认值（`kw` 里没有这个键）。
REDEPLOY_DEFAULT = 70.0


# --------------------------------------------------------------- Go 侧入口

def go_operators(plan: str, roster: str) -> dict:
    """问 Go 要一份 `operators` 应答（整个 resp，判据要看 6 个顶层键）。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "operators",
                      "spec": {"plan": plan, "roster": roster}}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s"
                         % (p.returncode,
                            p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    return resp


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
    """把不同处**指到路径**（比「不一致」三个字有用得多）。"""
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

    def free(self, fixture: str) -> bool:
        """这份夹具还没被**别的**变异占用过。

        ★ 四处变异必须落在**不同夹具**上：同一份夹具塞进两处，第二处会因为
        「断言已经被第一处蕴含」而红得没有独立性（本项目记过这一条）。
        """
        return all(v is None or v[0] != fixture for v in self.at.values())

    def put(self, key: str, where) -> None:
        self.applied[key] = True
        self.at[key] = where

    def note(self, key: str, where, field_same: bool) -> None:
        if self.at[key] is not None and self.at[key] == where and not field_same:
            self.caught[key] = True


# --------------------------------------------------------------- 生产规格 ＋ 活对象

class LiveCapture:
    """走生产路径抄规格，**并把规格读的那个对象那一组读数一并抄下来**。

    `_operator_spec` 读的是 `operator_of(d)`（生产路径里是 `OperatorView`，
    不是活的 `OperatorUnit`——两者同名不同对象，见 `frontend/operator_view.py`）。
    """

    def __init__(self):
        import golden_go as G
        outer = self

        class Cap(G.SpecCapture):
            def _run_other_engine(self, **kw):              # noqa: D102
                from ak_tactic.frontend.inputs import SpecInputs
                from ak_tactic.frontend.schedule import operator_of
                from ak_tactic.simgo.spec import build_spec
                inp = SpecInputs.from_sim(kw["sim"])
                outer.spec = build_spec(inp, allow_devices=True)
                outer.rows = []
                for d in sorted(inp.deployments, key=lambda x: x.time):
                    outer.rows.append((d, operator_of(d)))
                raise _Done()

        self._cls = Cap

    def run(self, plan, roster):
        v = self._cls()
        try:
            v.run(plan, roster=roster)
        except _Done:
            return self.spec, self.rows
        return None, None


class _Done(Exception):
    pass


def ruler_shield_of(d):
    """判据这一侧**自己写一遍** `_shield_of` 的表达式（第二把尺子的那一半）。

    ★ 为什么不直接调 `specgo.spec._shield_of`：那是**权威本人**，而生产规格也是
    它产出的——两边都问同一个人，比出来的永远相等（**零信息量**）。这里读的是
    **下一层**（`tal.effects.shield_*`：`apply_text_rules` 的产物），与
    `_shield_of` 的差别才可能露出「尺子写错了」。
    """
    for tal in getattr(d, "talents", None) or ():
        eff = getattr(tal, "effects", None)
        if eff is None:
            continue
        cap = max(int(eff.shield_max_layers), int(eff.shield_layers_on_deploy))
        if cap <= 0:
            continue
        return {
            "max_layers": cap,
            "layers": int(eff.shield_layers_on_deploy),
            "interval": float(eff.shield_interval),
            "break_heal_ratio": float(eff.shield_break_heal_ratio),
            "break_sp": float(eff.shield_break_sp),
        }
    return None


def live_expect(op, d, prov) -> dict:
    """判据这一侧**自己写一遍**那 25 个键的表达式（第二把尺子）。

    ★ 这是一份**复写**，用途只有一个：把「Go 的 `Total[...]` 与活对象读到的
    是不是同一个数」变成可量的。它**不**被用来质疑生产规格——生产规格是权威
    （本项目记过：对已有权威实现的逻辑，第二份实现只能当对照实验）。
    """
    spd = float(getattr(op, "attack_speed", 100.0) or 100.0)
    cells = prov(op.char_id, op.elite, d.direction,
                 (int(d.position[0]), int(d.position[1])),
                 range_id=op.current_range_id())
    out = {
        "char_id": op.char_id,
        "name": op.name or op.char_id,
        "cell": [int(d.position[0]), int(d.position[1])],
        "max_hp": float(op.max_hp),
        "atk": float(op.current_atk()),
        "def": float(op.current_defense()),
        "res": float(op.current_res()),
        "interval": max(MIN_INTERVAL,
                        float(op.attack_interval) * 100.0 / max(ASPD_MIN, spd)),
        "damage_type": str(op.attack_type),
        "block_cnt": int(op.block_cnt),
        "deploy_cost": int(op.deploy_cost),
        "redeploy_time": float(getattr(op, "redeploy_time", REDEPLOY_DEFAULT)
                               or REDEPLOY_DEFAULT),
        "range": sorted([int(x), int(y)] for x, y in cells),
    }
    if getattr(op, "nation_id", ""):
        out["nation_id"] = str(op.nation_id)
    if getattr(op, "profession", ""):
        out["profession"] = str(op.profession)
    radius = float(getattr(op, "splash_radius", 0.0) or 0.0)
    if radius > 0.0:
        out["splash_radius"] = radius
        out["splash_scale"] = float(getattr(op, "splash_scale", 0.0) or 0.0)
        out["splash_damage_scale"] = float(
            getattr(op, "splash_damage_scale", 1.0) or 1.0)
        high = float(getattr(op, "highland_splash_scale", 0.0) or 0.0)
        if high > 0.0:
            out["highland_splash_scale"] = high
            slu = float(getattr(op, "highland_splash_sluggish", 0.0) or 0.0)
            if slu > 0.0:
                out["highland_splash_sluggish"] = slu
    combo = int(getattr(op, "combo_hits", 1) or 1)
    if combo > 1:
        out["combo_hits"] = combo
        out["combo_hit_scale"] = float(getattr(op, "combo_hit_scale", 1.0) or 1.0)
        out["combo_damage_scale"] = float(
            getattr(op, "combo_damage_scale", 1.0) or 1.0)
    power = int(getattr(op, "power_attack_count", 0) or 0)
    if power > 0:
        out["power_attack_count"] = power
        out["power_attack_scale"] = float(
            getattr(op, "power_attack_scale", 1.0) or 1.0)
    #: ---- 天赋派生（段 B 第一批）----
    #: ★ 用**生产者本人**（`frontend/talent_finders` 的九个 finder），
    #: 不在这里另写一遍判据——那正是这条判据存在的意义。
    from ak_tactic.frontend import talent_finders as _tf
    from ak_tactic.simgo.spec import _talent_dodge, _team_auras_of
    _sh = ruler_shield_of(d)
    if _sh is not None:
        out["shield"] = _sh
    if getattr(op, "heals", False):
        out["heals"] = True
    bless = _tf.find_blessing(getattr(d, "talents", None) or [])
    bsave = float(bless.value("c2e_freeze", 0.0) or 0.0) if bless else 0.0
    if bsave > 0.0:
        out["blessing_save"] = bsave
        out["blessing_self_freeze"] = float(
            (bless.value("freeze", 0.0) or 0.0) if bless else 0.0)
    phys, arts = _talent_dodge(op, d)
    if phys or arts:
        out["talent_dodge_phys"] = phys
        out["talent_dodge_arts"] = arts
    regen = _tf.find_regen(getattr(d, "talents", None) or [])
    if regen is not None:
        mon = _tf.find_medic_monument(getattr(d, "talents", None) or [])
        out["regen_aura"] = {
            "hp_per_sec": float(regen.value("hp_recovery_per_sec", 0.0) or 0.0),
            "duration": float(regen.value("buff_duration", 0.0) or 0.0),
            "nation": (_tf.RHODES_NATION if mon is not None else ""),
            "nation_mult": (float(mon.value("rhodes_bonus", 1.0) or 1.0)
                            if mon is not None else 1.0),
            "strict": False,   #: 生产路径恒 `heal_mode=range`
        }
    auras = _team_auras_of(d, op)
    if auras:
        out["team_auras"] = auras
    return out


def live_counters(op, d, prov, code_ok: bool, origin_added: bool) -> dict:
    """判据这一侧**独立**数一遍 `covered` 那些分支（不看 Go 的读数）。"""
    from ak_tactic.frontend import talent_finders as _tf
    tal = getattr(d, "talents", None) or []
    c = {k: 0 for k in COVERED_KEYS}
    c["range_code_in_table" if code_ok else "range_code_missing"] = 1
    if origin_added:
        c["range_origin_added"] = 1
    if not getattr(op, "nation_id", ""):
        c["nation_id_empty"] = 1
    if not getattr(op, "profession", ""):
        c["profession_empty"] = 1
    if float(getattr(op, "splash_radius", 0.0) or 0.0) > 0.0:
        c["splash_radius_nonzero"] = 1
    if float(getattr(op, "highland_splash_scale", 0.0) or 0.0) > 0.0:
        c["highland_splash_scale_nonzero"] = 1
    if float(getattr(op, "highland_splash_sluggish", 0.0) or 0.0) > 0.0:
        c["highland_splash_sluggish_nonzero"] = 1
    if int(getattr(op, "combo_hits", 1) or 1) > 1:
        c["combo_hits_gt1"] = 1
    if int(getattr(op, "power_attack_count", 0) or 0) > 0:
        c["power_attack_count_gt0"] = 1
    #: ---- 段 B 第一批（天赋派生）：判据独立数一遍同样的分支 ----
    if getattr(op, "heals", False):
        c["heals_true"] = 1
    bless = _tf.find_blessing(tal)
    if bless is not None and float(bless.value("c2e_freeze", 0.0) or 0.0) > 0.0:
        c["blessing_nonzero"] = 1
    blk = _tf.find_damage_block(tal)
    if blk is not None and float(blk.value("prob", 0.0) or 0.0) != 0.0:
        c["talent_dodge_nonzero"] = 1
    if _tf.find_regen(tal) is not None:
        c["regen_aura_nonzero"] = 1
        c["regen_strict_false"] = 1   #: 生产路径恒 `range`
    #: ⚠ 这里必须与 Go 同口径：**五个探测器任一命中**都算（`_team_auras_of`
    #: 里 class / covenant / angel / dispatch 四条各自也能单独产出条目）。
    #: 只判 `find_team_aura` 会让「Go 多算了」被读成计数不一致。
    if (_tf.find_team_aura(tal) is not None or _tf.find_class_aura(tal) is not None
            or _tf.find_ammo_covenant(tal) is not None
            or _tf.find_angel_blessing(tal) is not None
            or _tf.find_limit_dispatch(tal) is not None):
        c["team_auras_nonzero"] = 1
    if ruler_shield_of(d) is not None:
        c["shield_nonzero"] = 1
    return c


# --------------------------------------------------------------- 源码守卫

def operator_reads() -> tuple[set, set]:
    """`ast` 现抽 `_operator_spec` 读 `op` / `d` 的属性名（不手抄）。"""
    src = (ROOT / "ak_tactic" / "simgo" / "spec.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = [n for n in ast.walk(tree)
          if isinstance(n, ast.FunctionDef) and n.name == "_operator_spec"]
    if not fn:
        raise SystemExit("spec.py 里找不到 _operator_spec")
    ops: set = set()
    ds: set = set()

    def add(target: set, name: str) -> None:
        target.add(name)

    for n in ast.walk(fn[0]):
        if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            if n.value.id == "op":
                add(ops, n.attr)
            elif n.value.id == "d":
                add(ds, n.attr)
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                and n.func.id == "getattr" and n.args
                and isinstance(n.args[0], ast.Name) and len(n.args) >= 2
                and isinstance(n.args[1], ast.Constant)
                and isinstance(n.args[1].value, str)):
            if n.args[0].id == "op":
                add(ops, n.args[1].value)
            elif n.args[0].id == "d":
                add(ds, n.args[1].value)
    return ops, ds


def wire_operator_keys() -> list:
    """从 `wire.go::OperatorSpec` 现抽顶层 json 键（那份 35 键的契约）。"""
    text = (ROOT / "rios-sim" / "wire.go").read_text(encoding="utf-8")
    m = re.search(r"type OperatorSpec struct \{(.*?)\n\}", text, re.S)
    if not m:
        raise SystemExit("wire.go 里找不到 OperatorSpec")
    return [mm.group(1) for mm in
            (re.search(r'json:"([a-z_]+)', line) for line in m.group(1).split("\n"))
            if mm]


def exe_identity() -> tuple:
    """仪器身份：sha256 ＋ 「它比本树最新的 .go 旧不旧」。

    ★ 只对**默认路径**判红。显式给了 `RIOS_SIM_BIN` 时那是调用方**有意指定**的
    仪器（另一条会话用冻结 exe 时正是这样），staleness 在那里不是缺陷。
    """
    p = Path(GO_BIN)
    if not p.exists():
        raise SystemExit("仪器不在盘上：%s" % p)
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    newest = max((f.stat().st_mtime for f in (ROOT / "rios-sim").glob("*.go")),
                 default=0.0)
    stale = p.stat().st_mtime < newest
    explicit = "RIOS_SIM_BIN" in os.environ
    return sha, stale, explicit


# --------------------------------------------------------------- 主流程

def main() -> int:
    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    printed: list[str] = []
    bad = 0
    bad_slots = 0
    n_compared = 0
    n_fixtures = 0

    from ak_tactic.battle.range import RangeProvider
    from ak_tactic.gamedata.range import RangeTable
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.plan import Plan, Roster
    import check_specgo_go as C

    calc = OperatorCalculator()
    roster = Roster.from_json(ROSTER_FIX)

    def range_id_of(char_id: str, elite: int) -> str:
        phases = calc.character(char_id).get("phases") or []
        e = max(0, min(elite, len(phases) - 1))
        return (phases[e].get("rangeId") if phases else None) or "1-1"

    rtbl = RangeTable()

    def make_provider():
        return RangeProvider(rtbl, range_id_of, block_of=lambda c, e: 1)

    sha, stale, explicit = exe_identity()
    print("Go 侧仪器：%s" % GO_BIN)
    print("           sha256 %s%s" % (sha, "（**比本树最新的 .go 旧**）" if stale else ""))
    if stale and explicit:
        print("           ⚠ RIOS_SIM_BIN 显式指定 ⇒ 这是**有意选定**的仪器，"
              "staleness 不当缺陷（另一条会话用冻结 exe 时正是这样）")
    print("Python 侧权威：simgo/spec.py 的 _operator_spec"
          "（期望值走生产路径抄，见 check_specgo_go.real_specs）")
    print()

    #: 权威那份规格**另跑一遍**（共享的钩子），与上面的活读数构成两把尺子。
    specs = {n: s for n, s, _e, _l in C.real_specs() if s is not None}
    print("§1 生产规格：抄到 %d 份" % len(specs))

    # ============================================================ 2/3 · 67 人次主循环
    print()
    print("§2 Go 产出的 %d 个键 vs 生产规格；§3 生产规格 vs 活对象读数"
          % len(PORTED))
    real_fixtures = 0
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                   # noqa: BLE001
            continue
        if not isinstance(raw, dict) or ("deploys" not in raw
                                         and "deploy" not in raw):
            continue
        want_spec = specs.get(f.name)
        cap = LiveCapture()
        try:
            live_spec, rows = cap.run(Plan.from_dict(raw), roster)
        except Exception as e:                              # noqa: BLE001
            printed.append("✗ %s 生产路径走不通：%s: %s"
                           % (f.name, type(e).__name__, e))
            bad += 1
            continue
        if want_spec is None or live_spec is None or not rows:
            printed.append("✗ %s 抄不到规格（权威=%s 活抄=%s 人次=%s）"
                           % (f.name, want_spec is not None,
                              live_spec is not None, len(rows or [])))
            bad += 1
            continue
        real_fixtures += 1
        #: ★ 期望值在**循环顶部无条件**算出（不许用海象写在分支里）。
        want_ops = list(want_spec.get("operators") or [])
        prov = make_provider()
        live_ops = []
        live_cov = {k: 0 for k in COVERED_KEYS}
        struct_zero = {k: 0 for k in STRUCTURAL_ZERO}
        for d, op in rows:
            live = live_expect(op, d, prov)
            phases = calc.character(op.char_id).get("phases") or []
            e = max(0, min(op.elite, len(phases) - 1))
            code = (phases[e].get("rangeId") if phases else None) or "1-1"
            try:
                cells = rtbl.cells(code)
                code_ok = True
                origin_added = (0, 0) not in cells
            except Exception:                               # noqa: BLE001
                code_ok, origin_added = False, False
            for k, v in live_counters(op, d, prov, code_ok, origin_added).items():
                live_cov[k] += v
            if op.current_range_id() is not None:
                struct_zero["range_id_rewritten"] += 1
            if live["redeploy_time"] != REDEPLOY_DEFAULT:
                struct_zero["redeploy_time_nondefault"] += 1
            live_ops.append(live)
        #: 两把尺子先自己对齐：活读数与生产规格**逐人次逐键**相同。
        #: 不同 ⇒ 判据这一侧的表达式写错了（**尺子错**，不是实现错）。
        if len(live_ops) != len(want_ops):
            printed.append("✗ %s 两把尺子的条数不同：活 %d / 权威 %d"
                           % (f.name, len(live_ops), len(want_ops)))
            bad += 1
            continue
        ruler_bad = []
        for i, (lv, wt) in enumerate(zip(live_ops, want_ops)):
            for k in PORTED:
                if k in lv or k in wt:
                    if not same(lv.get(k), wt.get(k)):
                        ruler_bad.append("%s[%d].%s：活=%r 权威=%r"
                                         % (f.name, i, k, lv.get(k), wt.get(k)))
        if ruler_bad:
            bad += 1
            printed.append("✗ %s **尺子错**（活读数与生产规格不符）：%d 处"
                           % (f.name, len(ruler_bad)))
            printed.extend("      " + x for x in ruler_bad[:4])

        resp = go_operators(str(ROOT / "fixtures" / f.name), str(ROSTER_FIX))
        got = resp["operators"]

        # ---- 八处独立变异（各自拒绝已被占用的夹具 ⇒ 八条独立的路；
        #      候选面小的先挑，见下面 MUT_DODGE 那一段的说明）
        if guard.want(MUT_ATK) and guard.free(f.name) and got:
            got[0]["atk"] = math.nextafter(float(got[0]["atk"]), math.inf)
            guard.put(MUT_ATK, (f.name, 0))
        if guard.want(MUT_SPLASH) and guard.free(f.name):
            for i, o in enumerate(got):
                if "splash_damage_scale" in o:
                    o["splash_damage_scale"] = math.nextafter(
                        float(o["splash_damage_scale"]), math.inf)
                    guard.put(MUT_SPLASH, (f.name, i))
                    break
        if guard.want(MUT_CELL) and guard.free(f.name) and got:
            got[0]["cell"][0] = int(got[0]["cell"][0]) + 1
            guard.put(MUT_CELL, (f.name, 0))
        if guard.want(MUT_DROP) and guard.free(f.name) and len(got) >= 2:
            got.pop()
            guard.put(MUT_DROP, (f.name, "len"))
        #: ---- 段 B 第一批的四条：各自落在**不同的键**上，且都先在**行内找**
        #: 一个真正带这个键的人次（找不到就不注入，`guard.free` 保证不撞夹具）。
        #:
        #: ⚠ **顺序有讲究**：`talent_dodge_phys` 全 24 份夹具里只有 **2 人次**
        #: 带（实测），所以它必须**先挑**——排在最后时那两份夹具早被前面四条
        #: 占走，`guard.free` 全是 False，它会一次都注入不上（第一版就是这样：
        #: 「注入=否」，反向守卫直接不成立）。候选面小的先挑。
        if guard.want(MUT_DODGE) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("talent_dodge_phys"):
                    o["talent_dodge_phys"] = math.nextafter(
                        float(o["talent_dodge_phys"]), math.inf)
                    guard.put(MUT_DODGE, (f.name, i))
                    break
        #: ⚠ `shield` 的候选面**比 dodge 大、比 heals 小**：24 份夹具里 11 份有它
        #: （每份 1 人次），所以排在 dodge 之后、heals 之前。**顺序仍然是契约**：
        #: 排到最后时那 11 份夹具早被前面几条占走，它会一次都注入不上。
        if guard.want(MUT_SHIELD) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("shield"):
                    o["shield"]["max_layers"] = int(o["shield"]["max_layers"]) + 1
                    guard.put(MUT_SHIELD, (f.name, i))
                    break
        if guard.want(MUT_HEALS) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("heals"):
                    o["heals"] = False
                    guard.put(MUT_HEALS, (f.name, i))
                    break
        if guard.want(MUT_AURA) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("team_auras"):
                    o["team_auras"][0]["atk_pct"] = math.nextafter(
                        float(o["team_auras"][0]["atk_pct"]), math.inf)
                    guard.put(MUT_AURA, (f.name, i))
                    break
        if guard.want(MUT_REGEN) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("regen_aura"):
                    o["regen_aura"]["hp_per_sec"] = math.nextafter(
                        float(o["regen_aura"]["hp_per_sec"]), math.inf)
                    guard.put(MUT_REGEN, (f.name, i))
                    break

        # ---- §2 实现 vs 权威
        if len(got) != len(want_ops):
            bad += 1
            printed.append("✗ %s 人次条数：Go=%d 生产规格=%d"
                           % (f.name, len(got), len(want_ops)))
        guard.note(MUT_DROP, (f.name, "len"), len(got) == len(want_ops))
        if resp.get("scanned") != len(want_ops) and not mutate:
            bad += 1
            printed.append("✗ %s `scanned`=%r 与生产规格的 %d 人次不符"
                           % (f.name, resp.get("scanned"), len(want_ops)))
        for i, (wt, gt) in enumerate(zip(want_ops, got)):
            n_compared += 1
            slot_bad = False
            #: ★ 键集三方对账：Python ＝ Go ∪ （Python 送的段 B 键）。
            py_keys, go_keys = set(wt), set(gt)
            b_present = py_keys & set(UNPORTED)
            if go_keys - set(PORTED):
                slot_bad = True
                printed.append("✗ %s[%d] Go 送了段 A 之外的键：%r"
                               % (f.name, i, sorted(go_keys - set(PORTED))))
            if go_keys & set(UNPORTED):
                slot_bad = True
                printed.append("✗ %s[%d] Go 送了 `unported` 里的键 %r"
                               " —— 那份清单要跟着改（有人得回头看）"
                               % (f.name, i, sorted(go_keys & set(UNPORTED))))
            if py_keys != (go_keys | b_present):
                slot_bad = True
                printed.append("✗ %s[%d] 键集对不上：Python 有而两边都没给的 %r；"
                               "Go 有而 Python 没有的 %r"
                               % (f.name, i, sorted(py_keys - go_keys - b_present),
                                  sorted(go_keys - py_keys)))
            #: 25 个键逐个比（**含存在性**——条件键「该不该出现」也是内容）。
            for k in PORTED:
                g_same = (k in gt) == (k in wt) and same(wt.get(k), gt.get(k))
                guard.note(MUT_ATK, (f.name, i),
                           g_same or k != "atk")
                guard.note(MUT_SPLASH, (f.name, i),
                           g_same or k != "splash_damage_scale")
                guard.note(MUT_CELL, (f.name, i),
                           g_same or k != "cell")
                guard.note(MUT_HEALS, (f.name, i),
                           g_same or k != "heals")
                guard.note(MUT_AURA, (f.name, i),
                           g_same or k != "team_auras")
                guard.note(MUT_REGEN, (f.name, i),
                           g_same or k != "regen_aura")
                guard.note(MUT_DODGE, (f.name, i),
                           g_same or k != "talent_dodge_phys")
                guard.note(MUT_SHIELD, (f.name, i),
                           g_same or k != "shield")
                if g_same:
                    continue
                slot_bad = True
                if len(printed) < 12:
                    printed.append("✗ %s[%d] %s %s"
                                   % (f.name, i, wt.get("char_id"), k))
                    for dd in first_diffs(wt.get(k), gt.get(k), k, [], 3):
                        printed.append("      " + dd)
            if slot_bad:
                bad_slots += 1
                #: ★ **红要落进退出码**（2026-09-23 补）。原本这里只数 `bad_slots`，
                #: 而它只出现在结论行的「N / M 人次逐位一致」里、**不进 rc**——
                #: 实测：把 Go 的 `shield.max_layers` 写死成 99，11 人次印着
                #: `Go=99 Python=3`、结论从 64/64 掉到 53/64，而 **rc 仍然是 0**。
                #: 「判据红了但它不改退出码」＝假绿，正是本仓反复记过的那一类。
                #: ⇒ 人次级的实现错与上面那些结构性错**同权**，一起驱动 rc。
                bad += 1
        # ---- §4 covered：两侧各数一遍（**逐夹具**比，不是只比合计）
        go_cov = resp.get("covered") or {}
        if set(go_cov) != set(COVERED_KEYS):
            bad += 1
            printed.append("✗ %s `covered` 的键集不对：Go=%r"
                           % (f.name, sorted(go_cov)))
        for k in COVERED_KEYS:
            if go_cov.get(k, 0) != live_cov[k]:
                bad += 1
                printed.append("✗ %s `covered.%s`：Go=%r 判据独立数=%d"
                               % (f.name, k, go_cov.get(k), live_cov[k]))
        # ---- §3 结构零（现算）
        for k, v in struct_zero.items():
            if v:
                bad += 1
                printed.append("✗ %s 结构零失守：%s（%d 人次）—— %s"
                               % (f.name, k, v, STRUCTURAL_ZERO[k]))
        # ---- 段 B 的逐人次账（哪些真的被送出过）
        for k in UNPORTED:
            B_COUNT[k] = B_COUNT.get(k, 0) + sum(1 for wt in want_ops if k in wt)
    print("     夹具 %d 份 / 人次 **%d**（分母现算）" % (real_fixtures, n_compared))

    # ============================================================ 5 · unported 双向
    print()
    print("§5 unported 清单（双向集合比对 ＋ Python 实际送出的次数）")
    first = None
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                   # noqa: BLE001
            continue
        if isinstance(raw, dict) and ("deploys" in raw or "deploy" in raw):
            first = f.name
            break
    go_unported = []
    if first:
        go_unported = sorted(go_operators(str(ROOT / "fixtures" / first),
                                          str(ROSTER_FIX)).get("unported") or [])
    if go_unported != sorted(UNPORTED):
        bad += 1
        printed.append("✗ unported 清单：Go=%r 判据=%r" % (go_unported, list(UNPORTED)))
    for k in sorted(UNPORTED):
        note = UNPORTED_READY.get(k, "")
        print("    %-22s Python 送出 %3d 人次%s"
              % (k, B_COUNT.get(k, 0), ("   ← 其实已可搬：" + note) if note else ""))

    # ============================================================ 6 · 「已可搬」的量测
    print()
    print("§6 `unported` 里标了「其实已可搬」的那几个：拿一次量测说话，不是声明")
    ready_measured = {}
    for k, why in sorted(UNPORTED_READY.items()):
        ready_measured[k] = 0
    #: `heals`：Go 的 `opstats` 里就有（`TextDerived.Heals`）。逐人次比一次。
    cfgs, heals_cids = [], set()
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        sp = specs.get(f.name)
        if sp is None:
            continue
        from ak_tactic.verify import Verifier

        class _S:
            _by_name = Verifier._by_name
            _entry = Verifier._entry

            def __init__(self, c):
                self.calc = c

        stub = _S(calc)
        raw = json.loads(f.read_text(encoding="utf-8-sig"))
        for d in Plan.from_dict(raw).deploys:
            e = stub._entry(d, roster)
            cfgs.append({"char_id": e["char_id"], "elite": e["elite"],
                         "level": e["level"], "trust": e.get("trust") or 0,
                         "potential": e.get("potential", 1),
                         "module": e.get("module") or "",
                         "module_level": e.get("module_level") or 0})
        for o in sp.get("operators") or []:
            if o.get("heals"):
                heals_cids.add(str(o["char_id"]))
    if cfgs:
        env = dict(os.environ)
        env["RIOS_DATA"] = str(DATA)
        req = json.dumps({"id": 1, "cmd": "opstats", "spec": cfgs}) + "\n"
        p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
                           stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
        resp = json.loads(p.stdout.decode("utf-8", "replace").splitlines()[0])
        if not resp.get("ok"):
            bad += 1
            printed.append("✗ `opstats` 回 error：%s" % resp.get("error"))
        else:
            mism = 0
            hits = 0
            for c, g in zip(cfgs, resp["opstats"]):
                py_has = c["char_id"] in heals_cids
                if g.get("heals"):
                    hits += 1
                if bool(g.get("heals")) != py_has:
                    mism += 1
            ready_measured["heals"] = mism
            print("    heals：Go `opstats.heals` 与生产规格逐人次比 %d 次，"
                  "不一致 %d 处；Go 侧为真的 %d 次" % (len(cfgs), mism, hits))
            if mism:
                bad += 1
                printed.append("✗ `heals` 的「已可搬」不成立：%d 处不一致" % mism)

    # ============================================================ 7 · 键集总账
    print()
    print("§7 键集总账（段 A ＋ 段 B ＝ wire 的契约）")
    ops_fields, ds_fields = operator_reads()
    wire_keys = wire_operator_keys()
    print("    _operator_spec 读 op %d 个 / d %d 个；wire.OperatorSpec %d 个 json 键"
          % (len(ops_fields), len(ds_fields), len(wire_keys)))
    if len(set(PORTED) | set(UNPORTED)) != len(wire_keys) \
            or set(PORTED) | set(UNPORTED) != set(wire_keys):
        bad += 1
        printed.append("✗ 段 A(%d) ∪ 段 B(%d) ≠ wire 的 %d 个键；差：多 %r / 少 %r"
                       % (len(PORTED), len(UNPORTED), len(wire_keys),
                          sorted((set(PORTED) | set(UNPORTED)) - set(wire_keys)),
                          sorted(set(wire_keys) - set(PORTED) - set(UNPORTED))))
    else:
        print("    段 A %d ＋ 段 B %d ＝ %d ＝ wire 的键数，**逐名相等** ✓"
              % (len(PORTED), len(UNPORTED), len(wire_keys)))
    if set(PORTED) & set(UNPORTED):
        bad += 1
        printed.append("✗ 段 A 与段 B 相交：%r" % sorted(set(PORTED) & set(UNPORTED)))
    #: 两张读取面字段表**双向**比（Go 自报 vs ast 现抽）。
    if first:
        r0 = go_operators(str(ROOT / "fixtures" / first), str(ROSTER_FIX))
        go_ops = set(r0.get("view_fields") or [])
        go_ds = set(r0.get("deploy_fields") or [])
        if go_ops != ops_fields:
            bad += 1
            printed.append("✗ view_fields 不相等：Python 读了但 Go 没报 %r；"
                           "Go 报了但 Python 不读 %r"
                           % (sorted(ops_fields - go_ops), sorted(go_ops - ops_fields)))
        if go_ds != ds_fields:
            bad += 1
            printed.append("✗ deploy_fields 不相等：Python 读了但 Go 没报 %r；"
                           "Go 报了但 Python 不读 %r"
                           % (sorted(ds_fields - go_ds), sorted(go_ds - ds_fields)))
        print("    view_fields %d 个 / deploy_fields %d 个：%s"
              % (len(go_ops), len(go_ds),
                 "双向相等 ✓" if (go_ops == ops_fields and go_ds == ds_fields)
                 else "不等 ✗"))
        pr = r0.get("params") or {}
        if pr.get("plan") != str(ROOT / "fixtures" / first):
            bad += 1
            printed.append("✗ params.plan 回执不对：%r" % (pr.get("plan"),))

    # ============================================================ 输出
    print()
    for line in printed[:40]:
        print(line)
    if len(printed) > 40:
        print("（只印前 40 处）")
    print()
    if stale and not explicit:
        print("✗ 仪器比本树最新的 .go 旧 —— 读数不可信（先按闸门 1 重新 build）")
        return 1
    if mutate:
        for k in MUT_KEYS:
            print("  变异「%s」：注入=%s 判红=%s  落点=%s"
                  % (k, "是" if guard.applied[k] else "否",
                     "是" if guard.caught[k] else "否", guard.at[k]))
        miss = [k for k in MUT_KEYS
                if not (guard.applied[k] and guard.caught[k])]
        if miss:
            print("反向守卫：不成立 ✗（没做到「注入过并且判红」：%s）" % "、".join(miss))
            return 1
        print("反向守卫：%d 处独立变异各判红 —— 成立 ✓（分母 %d 人次）"
              % (len(MUT_KEYS), n_compared))
        return 0
    if n_compared == 0 or not real_fixtures:
        print("结论：一个人次都没比到 —— 判红（不是实现错，是判据自己瞎）")
        return 1
    print("结论：干员规格 %d / %d 人次逐位一致（段 A 的 %d 个键，含条件键的"
          "存在性；段 B 的 %d 个键具名进 unported）"
          % (n_compared - bad_slots, n_compared, len(PORTED), len(UNPORTED)))
    return 1 if bad else 0


#: 段 B 每个键「Python 一共送出过几次」——两层循环都往里加。
B_COUNT: dict = {}

if __name__ == "__main__":
    raise SystemExit(main())
