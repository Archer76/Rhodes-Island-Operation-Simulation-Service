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

## 具名 GO_ONLY（1 个键，**方向与 unported 相反**）

`hp_drain_per_sec`（职业特性「自身生命会不断流失」／怪杰那一族的速率）。

`_operator_spec` **不送**它，所以它既不是段 A 也不是段 B：§7 的身份等式因此是
**段 A ＋ 段 B ＋ GO_ONLY ＝ wire 的键数**（三类两两不交，各配一条断言）。
§2 的逐人次键集比对各处都要**先从 Go 的键集里摘掉它**再比——不摘会报成
「Go 多送了」（假红），塞进 `PORTED` 又会把「Python 没有」当成「Python 该有」。
§7 另配两条**现算**断言：Go 真的送出过它（0 人次＝死登记）、Python 一次都没送过
（送过＝这一分类要重做）。

★ `shield` **已经从这张表里移出**（段 B → 段 A）：它现在**逐位比**（`_shield_of`
的五个字段），并额外配了一条**双向对照**——判据自己数一遍
「shield 非空的人次」（`live_counters`），与 Go 的 `covered.shield_nonzero` 比。
§6 仍然量着 `heals`（拿 `opstats` 的字段与生产规格**逐人次比一次**）。

## 反向守卫（`--mutate`）

十处**互相独立**的注入，每处都要「注入过 ＋ 判红过」，落在**不同字段、不同代码路径**：
① `atk` 加 1 ulp（浮点面板那条读法）；② `splash_damage_scale` 加 1 ulp
（条件块的浮点，且**必须落在真有这条特性的人次上**）；③ `cell` 的 x+1（整数坐标）；
④ 删掉一条 operator（分母由 N 变 N−1）；⑤~⑨ 段 B 那五个键各一处；
⑩ **删掉 `GO_ONLY` 的 `hp_drain_per_sec`**（验 §7 那条「Go 真的送出过它」**红得起来**）。
每处各自拒绝「已被别处占用的夹具」，所以是十条独立的路，不是同一条 elif 链上的十个分支。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场跑 Python（`real_specs` 生产路径 ＋
  `LiveCapture` 的活对象读数 ＋ `talent_finders`），**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/干员规格.json`，
  **不 import `ak_tactic`**。

★ 一夹具一条键 `("operators", 夹具名, 夹具字节 sha16, 名册字节 sha16)`
＋ `G.coverage("operators", …)` 对账（夹具批是活的），值里装**这一份夹具的
全部 Python 侧产物**：权威的 `want_ops`、第二把尺子的 `live_ops`、判据独立
数的 `live_cov`、两条结构零的 `struct_zero`，以及三种「抄不到」的状态
（生产路径抛错 / 权威缺 / 活抄缺）——**它们各自有各自的判词**，不许压成一个
布尔（原版对这三种情形印的是三句不同的话）。

★ 另外两处期望值与身份：

  · §6 那一批 `opstats` 的入参（逐夹具的练度配置）与「生产规格里 `heals`
    为真的人」：键 `("opstats", "cfgs", 夹具批 sha16)`；
  · §7 的键集总账（`ast` 抽 `_operator_spec` 读了哪些属性、正则抽
    `wire.OperatorSpec` 的 json 键）**不进冻**：它们读的是**源文件正文**、
    不 import、不跑 Python——抽出来冻住反而让「源改了」这件事不再响。

用法:
    python tools\\check_operators_go.py
    python tools\\check_operators_go.py --mutate
    python tools\\freeze_baseline.py --record 干员规格
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
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
ROSTER_FIX = ROOT / "fixtures" / "roster_max_modelled.json"

#: Go **产出的** 33 个键（13 无条件 ＋ 12 条件 ＋ 8 天赋派生）。
#: ★ 33 ＋ 2 ＋ 1 ＝ **36** ＝ `wire.go::OperatorSpec` 的 json 键数，
#: §7 每次运行现数这三者并断言相等（不写死「36」这几个字）。
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
UNPORTED = ()          # ★ 2026-09-24：`skill` / `active` 已由 Go 产出，见 PORTED
#: 段 A 新收进来的两个键（原来是「Python 有、Go 没有」的段 B）。
#: ⚠ 它们进的是 `PORTED`（上面那条），不是这里——这里保持为空。
UNPORTED_NEW = ("skill", "active")

#: **Go 独有**的 1 个键：`_operator_spec` **不送**它，而 Go 送、模拟器也读它。
#:
#: ⚠ 它与 `UNPORTED` **方向相反**，别混：
#:   * `UNPORTED` ＝ 「Python 有、Go 没有」（`skill` / `active`）；
#:   * `GO_ONLY`  ＝ 「Go 有、Python 没有」。
#: 把 `hp_drain_per_sec` 塞进 `UNPORTED` 会让 §5 的双向比对当场红（Go 应答里的
#: `unported` 里没有它），而且语义全错。
#:
#: 为什么它是 Go 独有而不是两边都有：`ak_tactic/simgo/spec.py::_operator_spec`
#: 逐行可查，**不读也不写** `hp_drain_per_sec`。
#: ⚠ `ak_tactic/frontend/operator_view.py:179` 里那句 `self.hp_drain_per_sec = 0.0`
#: **不是**反例——那是 `OperatorView`（前端视图）的字段，`_operator_spec` 读的是
#: `op.<属性>` 那 29 个，其中没有它；而且就算有，写死的 0.0 也带不出真速率。
#:
#: 它为什么必须进 Go 的规格：干员特性「自身生命会不断流失」（怪杰那一族）在 Go 里
#: 原来**只有取数、没有消费**——`OperatorStats.HPDrainPerSec` 算出来了
#: （`operator.go:473` 的 `readHPDrain`），但值到不了模拟器读的那份规格、
#: `sim.go` 也没有按秒扣血的那一步。修法就是这一个键 ＋ `sim.go::traitDrainTick`。
GO_ONLY = ("hp_drain_per_sec",)

#: **Go 比 Python 多送**的键（方向与 `UNPORTED` 相反，与 `GO_ONLY` 同向但**成因不同**）：
#:
#:   * `GO_ONLY`   —— Python **从来**不送（那是另一条路的字段）；
#:   * `EXTRA_OPS` —— Python **有条件**不送：博士 2026-09-24 口径「计划里的 `skill: 0`
#:     等于默认技能＝技 1」之后，Go 为每一名有技能槽的干员都绑技能并送出
#:     `skill`/`active`；而 Python 那条路在槽号 0 上**不绑** ⇒ 它没有这两个键。
#:
#: ⇒ 逐人次键集比对里把这两个键**从 Go 的键集里摘掉**再比（不摘会造一条永久假红），
#: 并另配两条现算守卫：**Go 真的送出过它**（0 人次＝死登记）、**Python 一次都没送过**
#: （送过 ⇒ 口径变了，这条登记要重做）。
EXTRA_OPS = ("skill", "active", "talent_panel_mods")
EXTRA_OPS_SEEN: dict = {}
EXTRA_OPS_FROM_PY: dict = {}

#: `GO_ONLY` 两个方向的现算计数（§7 印出来并各自配断言）：
#:   · `SEEN`    —— Go 真的把这个键送出去过几次（0 ⇒ 这是一张**死的登记**）；
#:   · `FROM_PY` —— Python 那一侧送出过几次（>0 ⇒ 它不是 Go 独有，分类要重做）。
GO_ONLY_SEEN: dict = {}
#: Go 独有计数器的**累计**（跨夹具），给「至少非零过一次」那条守卫用。
GO_ONLY_COUNTERS_SEEN: dict = {}

#: Go 独有计数器里**当前夹具集行使不到**的那些 → 具名理由。
#:
#: ⚠ 处置是**登记**，不是删计数器：删掉之后「这一档没人走过」这件事就没人记得了；
#: 而放宽守卫会让真正的死账（一个从头到尾没数到东西的计数器）一起溜过去。
#: 判据每次把这一栏印出来，所以它不会沉进注释里。
GO_ONLY_COUNTERS_ZERO_OK = {
    "skill_none": "一二星／预备干员才没有技能槽，而两个名册夹具（20 位 6★ ＋ 460 位"
                  "char_ 段）里一位都没有 ⇒ 这一档在当前夹具集上**必然为 0**。"
                  "要真行使它，得另造一份含一二星的名册夹具（不在本批范围）。",
}

#: **Go 独有**的 `covered` 计数器：它们量的是 Go 自己那条**技能绑定链**的账，
#: Python 侧**没有独立来源**可比（Python 的技能绑定走的是另一条路，不经这份规格）。
#:
#: ⚠ 与 `UNPORTED` / `GO_ONLY` 都不同：那两个讲**键**，这一个讲**计数器**。
#: 处置与 `GO_ONLY` 同一姿势——**具名列出来**，然后：
#:   · 逐键相等那一条**跳过**它们（拿没有的东西去比，只会造一条永久假红）；
#:   · 另配一条「**至少非零过一次**」的死账守卫（全部为 0 ⇒ 这套会计没被行使 ⇒ 判红），
#:     否则它们会变成「看着在数、其实没数到任何东西」的装饰。
GO_ONLY_COUNTERS = {
    "skill_bound": "绑上技能的部署人次（Go 自己的绑定链）",
    "skill_none": "没有技能槽的部署人次（一二星／预备干员）",
    "skill_unknown_key_instances": "技能黑板里落在首发表之外的键的**实例数**（覆盖账）",
}
GO_ONLY_FROM_PY: dict = {}

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
    #: ---- 技能那一支（2026-09-24）----
    #: 与 `rios-sim/operators.go::OperatorsCoveredKeys` **同名同数**。
    #: 第三个是**覆盖账**：这一批技能里有几个黑板键落在首发表之外。
    "skill_bound", "skill_none", "skill_unknown_key_instances",
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
#: ★ 第九处（本批新增）：**删掉 `GO_ONLY` 的那个键**。它验的是 §7 那条
#: 「Go 真的送出过它」的断言**红得起来**——不装这条，SEEN>0 只是一句自我声明
#: （本项目记过：「守卫看不见＝没有守卫」）。
#: ⚠ 它是**候选面最小**的一处（全部 24 份夹具里只有 plan-main-00-01 有），
#: 所以注入顺序排在**最前**（与 MUT_DODGE／MUT_SHIELD 同一条纪律）。
MUT_DRAIN = "删掉 hp_drain_per_sec（GO_ONLY 键）"
MUT_KEYS = (MUT_ATK, MUT_SPLASH, MUT_CELL, MUT_DROP,
            MUT_HEALS, MUT_AURA, MUT_REGEN, MUT_DODGE, MUT_SHIELD, MUT_DRAIN)

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


# --------------------------------------------------------------- 期望值（可冻）
_SPECS = None


def _specs_batch() -> dict:
    """§1 那一份生产规格（**离冻档专用**）：`name → spec`，只跑一次。"""
    global _SPECS
    if _SPECS is None:
        import check_specgo_go as C
        _SPECS = {n: s for n, s, _e, _l in C.real_specs() if s is not None}
    return _SPECS


def scan_plan_fixtures() -> list[list]:
    """夹具批次的输入身份（数据侧；与判据同一套子集口径）。"""
    out: list[list] = []
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append([f.name, GB.file_sha16(f)])
    return out


def batch_id(rows: list[list]) -> str:
    """夹具批 ＋ 名册的**批次身份**（给 §6 那条键用）。"""
    return GB.sh16(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))


def py_operators_expect(name: str) -> dict:
    """一份夹具的两把尺子 ＋ 判据独立数的计数（**离冻档专用**）。

    ★ `ak_tactic` 的 import 全在函数体里：冻结档下本函数不会被调到。
    """
    from ak_tactic.battle.range import RangeProvider
    from ak_tactic.gamedata.range import RangeTable
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.plan import Plan, Roster

    want_spec = _specs_batch().get(name)
    raw = json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8-sig"))
    calc = OperatorCalculator()
    roster = Roster.from_json(ROSTER_FIX)

    def range_id_of(char_id: str, elite: int) -> str:
        phases = calc.character(char_id).get("phases") or []
        e = max(0, min(elite, len(phases) - 1))
        return (phases[e].get("rangeId") if phases else None) or "1-1"

    rtbl = RangeTable()
    prov = RangeProvider(rtbl, range_id_of, block_of=lambda c, e: 1)
    out = {"want_ok": want_spec is not None, "live_raised": False, "why": "",
           "live_spec_ok": False, "n_rows": 0,
           "want_ops": list((want_spec or {}).get("operators") or []),
           "live_ops": [], "live_cov": {k: 0 for k in COVERED_KEYS},
           "struct_zero": {k: 0 for k in STRUCTURAL_ZERO}}
    cap = LiveCapture()
    try:
        live_spec, rows = cap.run(Plan.from_dict(raw), roster)
    except Exception as e:                                     # noqa: BLE001
        out["live_raised"] = True
        out["why"] = "%s: %s" % (type(e).__name__, e)
        return out
    out["live_spec_ok"] = live_spec is not None
    out["n_rows"] = len(rows or [])
    if live_spec is None or not rows:
        return out
    for d, op in rows:
        live = live_expect(op, d, prov)
        phases = calc.character(op.char_id).get("phases") or []
        e = max(0, min(op.elite, len(phases) - 1))
        code = (phases[e].get("rangeId") if phases else None) or "1-1"
        try:
            cells = rtbl.cells(code)
            code_ok = True
            origin_added = (0, 0) not in cells
        except Exception:                                      # noqa: BLE001
            code_ok, origin_added = False, False
        for k, v in live_counters(op, d, prov, code_ok, origin_added).items():
            out["live_cov"][k] += v
        if op.current_range_id() is not None:
            out["struct_zero"]["range_id_rewritten"] += 1
        if live["redeploy_time"] != REDEPLOY_DEFAULT:
            out["struct_zero"]["redeploy_time_nondefault"] += 1
        out["live_ops"].append(live)
    return out


def py_opstats_batch() -> dict:
    """§6 的入参：逐夹具的练度配置 ＋「生产规格里 `heals` 为真的人」。"""
    from ak_tactic.operator import OperatorCalculator
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier

    class _S:
        _by_name = Verifier._by_name
        _entry = Verifier._entry

        def __init__(self, c):
            self.calc = c

    calc = OperatorCalculator()
    roster = Roster.from_json(ROSTER_FIX)
    stub = _S(calc)
    cfgs: list = []
    heals_cids: set = set()
    for f in sorted((ROOT / "fixtures").glob("*.json")):
        sp = _specs_batch().get(f.name)
        if sp is None:
            continue
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
    return {"cfgs": cfgs, "heals_cids": sorted(heals_cids)}


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
    """从 `wire.go::OperatorSpec` 现抽顶层 json 键（那份 36 键的契约）。"""
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
    G = GB.bind("干员规格", __file__)

    mutate = "--mutate" in sys.argv
    guard = Guard(mutate)
    printed: list[str] = []
    bad = 0
    bad_slots = 0
    n_compared = 0
    n_fixtures = 0

    sha, stale, explicit = exe_identity()
    print("Go 侧仪器：%s" % GO_BIN)
    print("           sha256 %s%s" % (sha, "（**比本树最新的 .go 旧**）" if stale else ""))
    if stale and explicit:
        print("           ⚠ RIOS_SIM_BIN 显式指定 ⇒ 这是**有意选定**的仪器，"
              "staleness 不当缺陷（另一条会话用冻结 exe 时正是这样）")
    print("Python 侧权威：simgo/spec.py 的 _operator_spec"
          "（期望值走生产路径抄，见 check_specgo_go.real_specs）")
    print()

    #: 权威那份规格 ＋ 活读数：**两种模式各取各的**（冻结档读冻的那份）。
    if G.mode == GB.CHECK:
        print("§1 生产规格：冻结档不跑生产路径"
              "（期望值读 fixtures/golden/干员规格.json）")
    else:
        print("§1 生产规格：抄到 %d 份" % len(_specs_batch()))

    #: ★ 夹具批是**活的**（别的会话会往里加夹具）⇒ 键带输入身份 ＋ 先对账。
    rsha = GB.file_sha16(ROSTER_FIX)
    live_batch = [[n, sha1, rsha] for n, sha1 in scan_plan_fixtures()]
    bid = batch_id(live_batch)
    cov = G.coverage("operators", live_batch)
    fixtures_iter = live_batch
    if G.mode == GB.CHECK and not cov.ok:
        #: 只比两边都有的。**未覆盖的不猜**。
        covered = {tuple(x) for x in cov.covered}
        fixtures_iter = [x for x in fixtures_iter if tuple(x) in covered]

    # ============================================================ 2/3 · 人次主循环
    print()
    print("§2 Go 产出的 %d 个键 vs 生产规格；§3 生产规格 vs 活对象读数"
          % len(PORTED))
    real_fixtures = 0
    for name, ident, _rs in fixtures_iter:
        f = ROOT / "fixtures" / name
        #: ★ 键自带输入身份：夹具或名册变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        E = G.expect(("operators", name, ident, rsha),
                     lambda name=name: py_operators_expect(name))
        #: ⚠ 三种「抄不到」各自有各自的判词（原版印的就是三句不同的话）。
        if E["live_raised"]:
            printed.append("✗ %s 生产路径走不通：%s" % (name, E["why"]))
            bad += 1
            continue
        if not E["want_ok"] or not E["live_spec_ok"] or not E["n_rows"]:
            printed.append("✗ %s 抄不到规格（权威=%s 活抄=%s 人次=%s）"
                           % (name, E["want_ok"], E["live_spec_ok"],
                              E["n_rows"]))
            bad += 1
            continue
        real_fixtures += 1
        #: ★ 期望值在**循环顶部无条件**算出（不许用海象写在分支里）。
        want_ops = list(E["want_ops"])
        live_ops = list(E["live_ops"])
        live_cov = dict(E["live_cov"])
        struct_zero = dict(E["struct_zero"])
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

        talent_panel_seen: list[str] = []
        resp = go_operators(str(ROOT / "fixtures" / f.name), str(ROSTER_FIX))
        got = resp["operators"]

        # ---- 十处独立变异（各自拒绝已被占用的夹具 ⇒ 十条独立的路；
        #      候选面小的先挑，见下面 MUT_DODGE 那一段的说明）
        #: ★ `MUT_DRAIN` **排在最前**：它的候选面最小（全部夹具里只有 1 个人次带
        #: 这个键）。排到后面时那一位所在的夹具可能已被前面某条占走，
        #: 它会一次都注入不上（反向守卫直接不成立）。
        if guard.want(MUT_DRAIN) and guard.free(f.name):
            for i, o in enumerate(got):
                if o.get("hp_drain_per_sec"):
                    o.pop("hp_drain_per_sec")
                    guard.put(MUT_DRAIN, (f.name, i))
                    break
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
            #: ★ 键集对账：Python ＝ （Go − GO_ONLY）∪（Python 送的段 B 键）。
            #: `GO_ONLY` 那一类**先从 Go 的键集里摘掉**再比——它是「Go 独有」，
            #: 不是「Go 多送了」；不摘的话这里会报成实现错（假红），
            #: 而把它塞进 `PORTED` 又会把「Python 没有」当成「Python 该有」。
            py_keys, go_keys = set(wt), set(gt)
            b_present = py_keys & set(UNPORTED)
            go_only = go_keys & set(GO_ONLY)
            if go_keys - set(PORTED) - set(GO_ONLY) - set(EXTRA_OPS):
                slot_bad = True
                printed.append("✗ %s[%d] Go 送了段 A／GO_ONLY 之外的键：%r"
                               % (f.name, i,
                                  sorted(go_keys - set(PORTED) - set(GO_ONLY)
                                            - set(EXTRA_OPS))))
            if go_keys & set(UNPORTED):
                slot_bad = True
                printed.append("✗ %s[%d] Go 送了 `unported` 里的键 %r"
                               " —— 那份清单要跟着改（有人得回头看）"
                               % (f.name, i, sorted(go_keys & set(UNPORTED))))
            if py_keys != ((go_keys - set(GO_ONLY) - set(EXTRA_OPS)) | b_present):
                slot_bad = True
                printed.append("✗ %s[%d] 键集对不上：Python 有而两边都没给的 %r；"
                               "Go 有而 Python 没有的 %r"
                               % (f.name, i,
                                  sorted(py_keys - (go_keys - set(GO_ONLY)
                                                    - set(EXTRA_OPS))
                                         - b_present),
                                  sorted(go_keys - py_keys - set(GO_ONLY))))
            #: ★ `GO_ONLY` 的**两个方向**逐人次累加（§7 拿它们配断言）：
            #: ① Go 真的送过它；② Python 一次都没送过。
            #: ⚠ 这里的 `seen_here` 同时是 `MUT_DRAIN` 的判红点：注入把这一位
            #: 的键删掉之后，它必须变 False（§7 那条「Go 送出过它」于是判红）。
            seen_here = bool(go_only)
            guard.note(MUT_DRAIN, (f.name, i), seen_here)
            for k in sorted(go_only):
                GO_ONLY_SEEN[k] = GO_ONLY_SEEN.get(k, 0) + 1
            for k in sorted(py_keys & set(GO_ONLY)):
                GO_ONLY_FROM_PY[k] = GO_ONLY_FROM_PY.get(k, 0) + 1
            #: ★ **2026-09-24 口径变更（有意与 Python 分道扬镳）**：Go 把**天赋的面板倍率**
            #: 折进了 `atk`／`def`／`max_hp`（`rios-sim/talentpanel.go`），Python 一个都不折
            #: ——实测 212 / 460 位干员带这类天赋，所以这一处差值**必然**出现。
            #:
            #: 处置：把两边**还原到同一个量**再比 —— `期望 = Python 的值 × (1 + 比例)`，
            #: 比例取自 **Go 自己报出来的 `talent_panel_mods`**（判据不猜、不手抄），
            #: 两边都按整数四舍五入（Go 的 `applyRounding` 也取整）
            #: ⇒ **这不是容差**。`g("total")` 不在 PORTED 里（它比的是规格顶层键），
            #: 所以这一处只牵动这三个键。
            wt = dict(wt)
            _mods = gt.get("talent_panel_mods") or {}
            _adj = []
            for _mk, _tk in (("atk", "atk"), ("def", "def"), ("max_hp", "max_hp")):
                _pct = float(_mods.get(_mk) or 0.0)
                if not _pct or _tk not in wt:
                    continue
                _v = wt.get(_tk)
                if isinstance(_v, (int, float)):
                    wt[_tk] = float(round(_v * (1.0 + _pct)))
                    _adj.append("%s+%.0f%%" % (_tk, _pct * 100.0))
            if _adj:
                talent_panel_seen.append("、".join(_adj))
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
            if k in GO_ONLY_COUNTERS:
                #: Go 独有计数器：Python 侧没有可比数（见 GO_ONLY_COUNTERS 的说明）。
                #: 它们由下面那条「至少非零过一次」的守卫看着。
                GO_ONLY_COUNTERS_SEEN[k] = (GO_ONLY_COUNTERS_SEEN.get(k, 0)
                                        + int(go_cov.get(k, 0) or 0))
                continue
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
    #: ★ 入参（逐夹具的练度配置）是 Python 侧产物 ⇒ 走通道冻住；键里带批次身份。
    _p = G.expect(("opstats", "cfgs", bid), py_opstats_batch)
    cfgs, heals_cids = list(_p["cfgs"]), set(_p["heals_cids"])
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

        # ---- Go 独有计数器：**至少非零过一次**（死账守卫）
    #
    # 理由：这几个计数器 Python 侧没有可比数（见 GO_ONLY_COUNTERS），逐键相等那一条
    # 对它们**跳过**。跳过之后必须换一条守卫顶上，否则它们会退化成「看着在数、
    # 其实没数到任何东西」的装饰——本仓：零行使的绿是零信息量的绿。
    for k, why in sorted(GO_ONLY_COUNTERS.items()):
        if GO_ONLY_COUNTERS_SEEN.get(k, 0) > 0:
            continue
        if k in GO_ONLY_COUNTERS_ZERO_OK:
            #: 零是**预料之中**、且有具名理由 ⇒ 印出来但不判红（登记 ≠ 装看不见）。
            printed.append("⊘ Go 独有计数器 %s 全程为 0（已登记）：%s"
                           % (k, GO_ONLY_COUNTERS_ZERO_OK[k]))
            continue
        bad += 1
        printed.append("✗ Go 独有计数器 %s 全程为 0：%s —— 这套会计没被行使"
                       % (k, why))

# ============================================================ 7 · 键集总账
    print()
    print("§7 键集总账（段 A ＋ 段 B ＋ GO_ONLY ＋ EXTRA_OPS ＝ wire 的契约）")
    ops_fields, ds_fields = operator_reads()
    wire_keys = wire_operator_keys()
    print("    _operator_spec 读 op %d 个 / d %d 个；wire.OperatorSpec %d 个 json 键"
          % (len(ops_fields), len(ds_fields), len(wire_keys)))
    #: ★ **四分类**的并集必须**逐名**等于 wire 的键集：
    #:   段 A 33（Go 产出、Python 也产出）
    #: ＋ 段 B 0（Python 产出、Go 不产出——2026-09-24 起清空：`skill`/`active` 已由 Go 产出）
    #: ＋ GO_ONLY 1（Go 产出、Python **从来**不产出）
    #: ＋ EXTRA_OPS 2（Go 产出、Python **有条件**不产出：槽号 0 上 Python 不绑技能）
    #: 四类**两两不交**（下面各配一条），否则一个键会被两边同时认领。
    three_way = set(PORTED) | set(UNPORTED) | set(GO_ONLY) | set(EXTRA_OPS)
    if three_way != set(wire_keys):
        bad += 1
        printed.append("✗ 段 A(%d) ∪ 段 B(%d) ∪ GO_ONLY(%d) ∪ EXTRA_OPS(%d) ≠ wire 的 %d 个键；"
                       "差：多 %r / 少 %r"
                       % (len(PORTED), len(UNPORTED), len(GO_ONLY), len(EXTRA_OPS),
                          len(wire_keys),
                          sorted(three_way - set(wire_keys)),
                          sorted(set(wire_keys) - three_way)))
    else:
        print("    段 A %d ＋ 段 B %d ＋ GO_ONLY %d ＋ EXTRA_OPS %d ＝ %d ＝ wire 的键数，"
              "**逐名相等** ✓"
              % (len(PORTED), len(UNPORTED), len(GO_ONLY), len(EXTRA_OPS), len(wire_keys)))
    for a, b in ((set(PORTED), set(UNPORTED)), (set(PORTED), set(GO_ONLY)),
                 (set(UNPORTED), set(GO_ONLY)), (set(EXTRA_OPS), set(PORTED)),
                 (set(EXTRA_OPS), set(UNPORTED)), (set(EXTRA_OPS), set(GO_ONLY))):
        if a & b:
            bad += 1
            printed.append("✗ 三分类有两类相交：%r" % sorted(a & b))
    #: ★ `GO_ONLY` 的两条**现算**断言（这一分类不能只靠声明）：
    #:   ① Go 真的送过它（0 人次 ⇒ 这张表是死的登记，与「功能没做」长得一样）；
    #:   ② Python **一次都没送过**（送过 ⇒ 它不是 Go 独有，分类要重做）。
    #: 数的是**人次**，不是「字段非空」——本项目记过：行使＝运行期计数，
    #: 不是「结构体里有这个字段」。
    for k in GO_ONLY:
        seen, from_py = GO_ONLY_SEEN.get(k, 0), GO_ONLY_FROM_PY.get(k, 0)
        print("    GO_ONLY %-18s Go 送出 %d 人次；Python 送出 %d 人次"
              % (k, seen, from_py))
        if seen <= 0:
            bad += 1
            printed.append("✗ GO_ONLY 的 `%s` 在 %d 人次里**一次都没被 Go 送出**"
                           " —— 这张登记是死的（要么取数断了，要么发送那一段没接上）"
                           % (k, n_compared))
        if from_py:
            bad += 1
            printed.append("✗ `%s` 被 Python 送出了 %d 人次 —— 它不是 Go 独有，"
                           "这一分类要重做（先看 `_operator_spec` 为什么开始送它）"
                           % (k, from_py))
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
    if G.mode == GB.CHECK and not cov.ok:
        print(cov.report("operators", len(live_batch)))
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
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
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


#: 段 B 每个键「Python 一共送出过几次」——两层循环都往里加。
B_COUNT: dict = {}

if __name__ == "__main__":
    raise SystemExit(main())
