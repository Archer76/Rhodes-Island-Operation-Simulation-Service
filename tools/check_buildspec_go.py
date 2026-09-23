#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：**单一入口** —— Go 一次造齐 `build_spec` 的 19 个顶层键。

## 对的是什么

`ak_tactic/simgo/spec.py::build_spec` 的**返回值**：19 个顶层键。Go 侧的命令是
`buildspec`（`rios-sim/buildspec.go`），它**只接线不重算**——每个键都调各自那批
已经过了对拍的函数。

## 三个口径（判据按同一口径取期望值，不手抄任何一个键）

| 口径 | 取证面 | 期望值来源 |
|---|---|---|
| A 计划口径 | **24 份夹具**（带计划） | `check_specgo_go.real_specs()`（生产路径，`allow_devices=True`） |
| B 空计划口径 | **缓存可达的 55 关** | `SpecInputs.from_stage` ＋ `build_spec`（同一口径，无排程） |
| C 计划侧合成 | 3 例（撤退／技能槽／手动开技能） | `check_specgo_go._capture(raw)` |

★ B 与 C 的作用是**补覆盖**：真夹具的 `unsupported` 与 `skill_uses` 全是空的
（实测 24/24 为 0），只比 A 的话这两条支的「一致」是两边都为空的空洞相等。

## 一处**具名**的口径差（不是容差）

Go 判不出雪（要 `find_snow`，Go 侧没有），所以对**带雪的那几关**：

    mechanisms      ：期望 = Go ＋ ['snow.field']（多一个）
    mech_config     ：期望多一个键 `snow.field`；`huai_shu_li.farmland` 那一段必须逐字段相同
    goal_cells      ：期望非空、Go 是 []（那道门是「mechanisms 含 snow.field」⇒ Go 侧恒关）

判据**不写容差、不平均掉**：先把差别**算出来**，再逐条断言它恰好是上面这三项；
多一项少一项都判红。实测 24 份夹具里带雪的 **2 份**（`hsex8_max` / `plan-hs07`），
而 `goal_cells` 非空的**恰好**也是那 2 份。

## 覆盖率纪律

19 个键**逐个**数「有几例非空」。某个键在全部用例里都是空的 ⇒ 那条「一致」是
零信息量的绿 ⇒ 必须登记（`EMPTY_REGISTRY`），否则判红。

用法:
    python tools\\check_buildspec_go.py
    python tools\\check_buildspec_go.py --mutate
"""
from __future__ import annotations

import copy
import json
import os
import re
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
FIXDIR = ROOT / "fixtures"
ROSTER_FIX = str(FIXDIR / "roster_max_modelled.json")

FARMLAND_ID = "huai_shu_li.farmland"
SNOW_ID = "snow.field"

#: 19 个键（顺序照 `build_spec` 的书写顺序；**现算**一份跟它对账，见 main）。
SPEC_KEYS = ("stage", "fps", "max_time", "life", "cost_init", "cost_max",
             "cost_time", "enemy_windup", "ranged_enemies", "speed_scale",
             "highland_cells", "goal_cells", "operators", "deploys", "spawns",
             "skill_uses", "unsupported", "mechanisms", "mech_config")

#: 有雪时**允许**不同的三个键（其余 16 个必须逐键相同）。
SNOW_DIFF_KEYS = ("mechanisms", "mech_config", "goal_cells")

#: 全部用例里都为空的键 —— 必须在这里具名登记（带证据），否则判红。
#: `goal_cells` 在 **Go 口径**下恒空（门是「有雪」而雪判不出），但**期望值**里
#: 有 2 例非空 ⇒ 它不是「零覆盖」，是「具名口径差」；故不进这张表，
#: 由 `diff_spec` 的三条断言盯着。
EMPTY_REGISTRY: dict[str, str] = {}


# ---------------------------------------------------------------- Go 侧

def go_buildspec_batch(levels: list[str], plan: str = "") -> list[tuple[bool, dict]]:
    """一条进程批量问，**如实**回传 `(ok, 整个应答)`。

    ⚠ 不在这里把 `ok=false` 抛掉：单一入口有**三种结局**，其中一种是**具名拒跑**
    （`SpawnsOf` 对未实现的敌人修饰层），那是登记在案的行为、不是本判据的失败。
    把三态压成「成功/失败」会把「拒跑」读成「入口坏了」。
    """
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    body: dict[str, object] = {"roster": ROSTER_FIX, "allow_devices": True}
    if plan:
        body["plan"] = plan
    lines = [json.dumps({"id": i + 1, "cmd": "buildspec", "level": lv,
                         "spec": body}) for i, lv in enumerate(levels)]
    p = subprocess.run([GO_BIN], input=("\n".join(lines) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    rows = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if len(rows) != len(levels):
        raise SystemExit("Go 回了 %d 行、问了 %d 关" % (len(rows), len(levels)))
    out = []
    for lv, row in zip(levels, rows):
        resp = json.loads(row)
        out.append((bool(resp.get("ok")), resp))
    return out


#: 具名拒跑：`SpawnsOf` 对「Go 未实现的敌人修饰层」大声失败（`spawns.go` 的
#: `UnportedRuneMuls`）。那是登记在案的行为——**跟着原版按普通档算**才是错的。
REFUSE_MARK = "未实现的敌人修饰层"


def is_named_refusal(resp: dict) -> bool:
    return REFUSE_MARK in str(resp.get("error", ""))


def go_buildspec_raw(req: dict) -> tuple[bool, dict]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    p = subprocess.run([GO_BIN], input=(json.dumps(req) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    rows = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not rows:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(rows[0])
    return bool(resp.get("ok")), resp


# ---------------------------------------------------------------- 期望值

#: 现算计数：`SpecInputs.from_stage` 那四项静默默认值**实际影响到几例**、
#: 以及受影响的一个样例。★ 这一条**必须印出来**（见 `py_from_stage` 的说明）：
#: 不印的话，下一个人会以为 B 口径测的就是生产路径。
FROM_STAGE_DEFAULTS: dict[str, object] = {"n": 0, "sample": "", "fields": {}}


def py_from_stage(level: str) -> dict:
    """空计划口径的权威：`SpecInputs.from_stage` ＋ `build_spec`。

    ★ **必须把四项补回去**（实测，这是 Python 那个构造器的一处静默默认值）：
    `from_stage` 里写的是 `getattr(env, "fps", 30)` / `getattr(env, "speed_scale", 1.0)`
    …，而 `frontend/stage_env.py` 返回的是**dict** ⇒ `getattr` 取不到，四项**静默落默认**。
    实测 `act31side_05`：`stage_env()["speed_scale"] == 0.5`（1-7 的移速 ×0.5），
    而 `from_stage(...).speed_scale == 1.0`。而且这四项**连传都传不进去**——
    `from_stage(..., speed_scale=…)` 会 `got multiple values for keyword argument`。

    ⇒ 期望值要的是「同一个 `build_spec` 在真实关卡静态下的输出」，所以在这里
    **就地改写这四个字段**（它们是 `SpecInputs` 的 dataclass 字段，可写）。
    ★ 这一改**不是**为了迁就 Go：Go 的 `StageEnv` 与 `stage_env` 有逐字段对拍
    （`check_stageenv_go.py` 126/126），这四项 Go 侧本来就是对的。
    """
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.frontend.schedule import Schedule
    from ak_tactic.frontend.stage_env import stage_env
    from ak_tactic.gamedata.enemy import EnemyLibrary
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import build_spec

    lib = EnemyLibrary()
    stage = load_stage(level)
    inp = SpecInputs.from_stage(stage, enemy_at=lib.get,
                                species_provider=lib.species_of,
                                schedule=Schedule())
    env = stage_env(stage, environment_difficulty=inp.environment_difficulty)
    #: ★ 把「被静默默认掉」的**事实与规模**记下来（现算，印在第二节）：
    #: 只改值不留痕，下一个人会以为这一口径本来就是对的。
    drifted = {"fps": (inp.fps, int(env["fps"])),
               "speed_scale": (inp.speed_scale, float(env["speed_scale"])),
               "ranged_enemies": (inp.ranged_enemies, bool(env["ranged_enemies"])),
               "enemy_windup": (inp.enemy_windup, float(env["enemy_windup"]))}
    if any(a != b for a, b in drifted.values()):
        FROM_STAGE_DEFAULTS["n"] = int(FROM_STAGE_DEFAULTS["n"]) + 1
        if not FROM_STAGE_DEFAULTS["sample"]:
            FROM_STAGE_DEFAULTS["sample"] = (
                "%s：from_stage 给 %s，stage_env 给 %s"
                % (level,
                   {k: a for k, (a, b) in drifted.items() if a != b},
                   {k: b for k, (a, b) in drifted.items() if a != b}))
        for k, (a, b) in drifted.items():
            if a != b:
                d = FROM_STAGE_DEFAULTS["fields"]
                d[k] = d.get(k, 0) + 1
    inp.fps = int(env["fps"])
    inp.speed_scale = float(env["speed_scale"])
    inp.ranged_enemies = bool(env["ranged_enemies"])
    inp.enemy_windup = float(env["enemy_windup"])
    #: `allow_devices=True` 与 A/C 两个口径**同口径**（对拍台的取值）；不加这一句
    #: 时 B 的 `unsupported` 会多一条「关卡装置 ×N」——那是**我的请求与期望值不同口径**，
    #: 不是实现差异（实测：act31side_05/06/07 各差 1 条，正是这一条）。
    return build_spec(inp, allow_devices=True)


def plan_variants() -> list[tuple[str, dict]]:
    """C 口径：三条合成计划（把真夹具零行使的两条支走到）。

    ⚠ 干员名从夹具**自己那一条**里取（`hsex8.json` 部署的是星熊／银灰／阿米娅）：
    写死一个名字会在 `Plan.validate` 的「撤退了没部署过的干员」上炸掉——
    那会看起来像「Go 拒了」，实际是**我这条夹具写错了**。
    """
    base = json.loads((FIXDIR / "hsex8.json").read_text(encoding="utf-8-sig"))
    who = base["deploys"][0]["operator"]
    retreat = copy.deepcopy(base)
    retreat["retreats"] = [{"operator": who, "time": 30.0}]
    slot = copy.deepcopy(base)
    slot["deploys"][0]["skill"] = 1
    skills = copy.deepcopy(base)
    skills["skills"] = [{"operator": who, "time": 30.0, "slot": 0}]
    return [("C1 撤退 ×1", retreat), ("C2 技能槽 1", slot),
            ("C3 手动开技能（skill_uses）", skills)]


# ---------------------------------------------------------------- 比较

#: **已登记的「Go 侧缺这个键」** —— ★ **本批清空**（2026-09-23，第三十八批）。
#:
#:   · `farmland.devices[].child` ⇒ **已搬进 Go**（天桩召唤链四跳），条目已摘；
#:   · `operators[].shield`       ⇒ **已搬进 Go**（天赋侧五个 `shield_*`），条目已摘。
#:
#: 剩下的两条（`operators[].skill`／`active`）**也没有留**：它们在 80 个用例里
#: **一次都没被走到**（24 份夹具的 `deploys[].skill` 全是 0，所以规格里根本
#: 不会出现这两个键）⇒ 留着就是一张**没人走的放行表**，那是真回归最好的藏身处
#: （「又缺了」与「本来就登记着」长得一模一样）。本文件自己的守卫会判红，
#: 这次红得对：**表该空**。
#:
#: ⚠ 于是现在**任何**「Go 缺了权威有的键」都判红。哪天真有夹具用上技能槽，
#: 它会红——那正是要的信号：要么把 `skill` 搬进 Go，要么**连证据一起**登记
#: （「它在这一例里真的被缺到了」），不许只加一行正则。
REGISTERED_MISSING: tuple[tuple[str, str], ...] = ()
REGISTERED_RX = tuple((re.compile(p), src) for p, src in REGISTERED_MISSING)

MISSING = "<缺>"


def diff_paths(a, b, p: str = "") -> list[tuple[str, object, object]]:
    """递归走两侧，只收**真差异**（`a != b`）。

    ⚠ 不用「整块 `!=`」：那样只能印出「这个键不同」，而 `30.0` 与 `30` 在 Python 里
    相等、`json.dumps` 的截断视图又长得不一样 —— 实测第一版就是这么把
    **一处真差异**埋进 2351 条噪声里的（类型噪声与真差异混在一张表）。这里按路径走，
    印的是 `路径 + repr(两侧值)`，一眼能分。
    """
    out: list[tuple[str, object, object]] = []
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append((p + "." + k, MISSING, b[k]))
            elif k not in b:
                out.append((p + "." + k, a[k], MISSING))
            else:
                out += diff_paths(a[k], b[k], p + "." + k)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append((p + ".len", len(a), len(b)))
        for i, (x, y) in enumerate(zip(a, b)):
            out += diff_paths(x, y, "%s[%d]" % (p, i))
    elif a != b:
        out.append((p, a, b))
    return out


def canon_groups(spec: dict) -> list:
    """把 `mech_config.<farmland>.groups` 按「第一个格」排序，**返回排序前的原始次序**。

    ⚠ 这是本判据**唯一**的一处规范化，理由与 `check_mechspec_go.py` 同源：
    Python 的分组种子是 `todo.pop()`（从一个 `set` 里弹），次序由 CPython 集合布局
    决定——复刻不了、也不该复刻。**组内 `cells` 不归一化**（两侧都是 `sorted()`，
    必须逐位相同）；**其余每一张表都保持顺序敏感**（`spawns` / `deploys` /
    `operators` / `actual` / `severed` 的次序全是契约）。

    原始次序取回来是要当成**读数**印出来的：它是「这条规范化是必要的」的证据。
    """
    mc = spec.get("mech_config") or {}
    f = mc.get(FARMLAND_ID)
    if not isinstance(f, dict) or not f.get("groups"):
        return []
    before = [[list(c) for c in g["cells"]] for g in f["groups"]]
    f["groups"] = sorted(f["groups"], key=lambda g: [list(c) for c in g["cells"]])
    return before


def diff_one(py: dict, go: dict, name: str) -> tuple[list[str], dict, bool]:
    """逐**路径**比一份规格。返回 `(问题, 计数, 是否有雪)`。"""
    bad: list[str] = []
    cnt = {"registered_missing": 0, "compared_paths": 0}
    snow = SNOW_ID in (py.get("mechanisms") or [])
    if sorted(py) != sorted(go):
        bad.append("%s：键集不同\n      期望 %s\n      Go   %s"
                   % (name, sorted(py), sorted(go)))
        return bad, cnt, snow
    #: 有雪时先逐条断言那三项**恰好**是雪造成的（多一项少一项都红）。
    if snow:
        pm, gm = list(py.get("mechanisms") or []), list(go.get("mechanisms") or [])
        if pm != gm + [SNOW_ID]:
            bad.append("%s：mechanisms 的差不是「恰好多一个 snow.field」：期望 %s / Go %s"
                       % (name, pm, gm))
        pc, gc = py.get("mech_config") or {}, go.get("mech_config") or {}
        if sorted(pc) != sorted(gc) + [SNOW_ID]:
            bad.append("%s：mech_config 的键差不是「恰好多一个 snow.field」：期望 %s / Go %s"
                       % (name, sorted(pc), sorted(gc)))
        if not py.get("goal_cells"):
            bad.append("%s：带雪却 goal_cells 为空 —— 期望值本身不对（口径变了）" % name)
        if go.get("goal_cells") != []:
            bad.append("%s：Go 的 goal_cells 应为 []（门恒关），实得 %s"
                       % (name, go.get("goal_cells")))
    for path, pv, gv in diff_paths(py, go):
        #: 有雪时这三个键的差另有断言（上面），不在这里重复报。
        if snow and (path.startswith(".mechanisms") or path.startswith(".goal_cells")
                     or path.startswith(".mech_config." + SNOW_ID)):
            continue
        cnt["compared_paths"] += 1
        if gv is MISSING:
            hit = [src for rx, src in REGISTERED_RX if rx.match(path)]
            if hit:
                cnt["registered_missing"] += 1
                continue
        bad.append("%s：路径 %s\n      期望 %s\n      Go   %s"
                   % (name, path, repr(pv)[:220], repr(gv)[:220]))
    return bad, cnt, snow


def check_slots(rec: dict, name: str, *, expect_plan: bool) -> list[str]:
    """`missing_keys` / `gated_keys` / `unported` 三槽的账。

    ⚠ `operators` 那一族来源条目**只在传了计划时**才该出现：空计划口径下
    `BuildOperatorsFor` 根本不被调用，那时要求它有 `operators:` 条目就是**判据错**
    （实测：B 口径 53 例全被这条误报）。
    """
    bad: list[str] = []
    if rec.get("missing_keys") != []:
        bad.append("%s：missing_keys 非空 %s —— 19 键没造齐"
                   % (name, rec.get("missing_keys")))
    if rec.get("gated_keys") != []:
        bad.append("%s：gated_keys 非空 %s —— 单一入口的两道门都该接上了"
                   % (name, rec.get("gated_keys")))
    #: `unported` 必须**并进来了**：各来源至少一条（合并静默为空是最坏的一种，
    #: 因为「没有未搬项」与「忘了并」长得一模一样）。
    unp = rec.get("unported") or []
    srcs = ["spawns", "unsupported", "mechspec"] + (["operators"] if expect_plan else [])
    for src in srcs:
        if not any(u.startswith(src + ": ") for u in unp):
            bad.append("%s：unported 里没有 %s 的来源条目（合并静默为空？）现得 %s"
                       % (name, src, json.dumps(unp, ensure_ascii=False)[:200]))
    for own in ("goal_cells：", "spawns[].p3r_armed："):
        if not any(u.startswith(own) for u in unp):
            bad.append("%s：unported 里缺本入口自己的那条 %s" % (name, own))
    return bad


# ---------------------------------------------------------------- 反向守卫

MUTATIONS = ("改一个标量", "少一条 spawn", "operators 少一个", "mechanisms 少一个",
             "mech_config 挖空", "goal_cells 塞一格")


def mutate(cases: list[dict], which: str):
    """注入做在**期望值**上（比较是纯函数，六处各自落在不同的键上）。"""
    out = copy.deepcopy(cases)
    for c in out:
        py = c["py"]
        if which == "改一个标量":
            py["life"] = py["life"] + 1
            return out
        if which == "少一条 spawn" and py.get("spawns"):
            py["spawns"] = py["spawns"][:-1]
            return out
        if which == "operators 少一个" and py.get("operators"):
            py["operators"] = py["operators"][:-1]
            return out
        if which == "mechanisms 少一个" and py.get("mechanisms"):
            py["mechanisms"] = py["mechanisms"][:-1]
            return out
        if which == "mech_config 挖空" and py.get("mech_config"):
            py["mech_config"] = {}
            return out
        if which == "goal_cells 塞一格" and not py.get("goal_cells"):
            py["goal_cells"] = [[0, 0]]
            return out
    return out


def add_case(cases: list[dict], name: str, py: dict, rec: dict,
             *, expect_plan: bool) -> None:
    """收一条可比用例：**先规范化那一个字段**，再把「原始次序是否不同」记成读数。"""
    gospec = rec["spec"]
    py_before = canon_groups(py)
    go_before = canon_groups(gospec)
    cases.append({"name": name, "py": py, "go": rec, "expect_plan": expect_plan,
                  "groups_order_diff": bool(py_before) and py_before != go_before})


def compare(cases: list[dict]) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {k: 0 for k in SPEC_KEYS}
    cov["_cases"] = 0
    cov["_snow_cases"] = 0
    cov["_registered_missing"] = 0
    cov["_groups_order_diff"] = 0
    for c in cases:
        cov["_cases"] += 1
        bad, cnt, snow = diff_one(c["py"], c["go"]["spec"], c["name"])
        problems += bad
        cov["_snow_cases"] += snow
        cov["_registered_missing"] += cnt["registered_missing"]
        cov["_groups_order_diff"] += c.get("groups_order_diff", False)
        problems += check_slots(c["go"], c["name"], expect_plan=c["expect_plan"])
        for k in SPEC_KEYS:
            v = c["py"].get(k)
            if v not in (None, [], {}, "", 0, 0.0, False):
                cov[k] += 1
    return problems, cov


# ---------------------------------------------------------------- 主流程

def allowance_guards(cases: list[dict]) -> tuple[list[str], dict]:
    """`REGISTERED_MISSING` 这张表**两侧各配一条守卫**（它是个白名单，白名单必须有边界）。

    白名单的危险是**长成"谁都能往里加"的静默容差**。所以：

      · 反向：把一条**没登记**的缺键造出来（删掉 Go 侧的 `operators[0].max_hp`）
        ⇒ 必须判红。**它红不了，这张表就是一块万能挡板。**
      · 正向：**真用例里必须真的出现「登记过、也确实缺」的路径**，而且它**不**判红。

    ⚠ 正向那一条**改过一次**（2026-09-23，第三十八批）：原来写的是
    `pretend("operators[0].shield")` —— 那是个**空转守卫**：`shield` 当时在 Go 侧
    **本来就不存在**（未搬），「从 Go 的规格里删掉它」是**空操作** ⇒ 永远不判红
    ⇒ 守卫恒过，两边都没被证过。本文件自己的 docstring 早就写着「空转的守卫比
    没有守卫更坏」，这条正是那个形状。现在改成**要求证据存在**：
    登记表里至少要有一条路径在真用例里**真的**被用到，否则这条守卫判红
    （空表要么是过期了、要么是没人走 —— 两种都该看，不该绿）。
    """
    problems: list[str] = []
    cnt = {"registered_paths": {}, "unregistered_red": 0, "registered_green": 0,
           "registered_vacuous": 0}
    #: ① 报告：登记缺键**按路径分组**印出来（不让它变成看不见的一坨）。
    #: 条数**现算**，不写死（上一版这里的注释写着 86，那是 child 75 ＋ shield 11）。
    for c in cases:
        py, go = c["py"], c["go"]["spec"]
        _, one, _snow = diff_one(py, go, c["name"])
        for path, pv, gv in diff_paths(py, go):
            if gv is MISSING and any(rx.match(path) for rx, _s in REGISTERED_RX):
                key = re.sub(r"\[\d+\]", "[]", path)
                cnt["registered_paths"][key] = cnt["registered_paths"].get(key, 0) + 1
    if not cases:
        return ["allowance 守卫：没有可比用例，无从取证"], cnt
    base = cases[0]

    def pretend(drop: str) -> bool:
        """在 Go 侧删掉一条路径末尾的键，看判据红不红。返回「红了」。"""
        bad, _c, _s = diff_one(base["py"], _deepdrop(base["go"]["spec"], drop),
                              base["name"])
        return bool(bad)

    if not _deepdrop(base["go"]["spec"], "operators[0].max_hp") != base["go"]["spec"]:
        problems.append("allowance 反向守卫：注入**没落到对象上**（那条路径不存在？）")
    elif pretend("operators[0].max_hp"):
        cnt["unregistered_red"] = 1
    else:
        problems.append("allowance 反向守卫不成立：造了一条**没登记**的缺键"
                        "（operators[0].max_hp）却没判红 —— 这张表成了万能挡板")
    #: 正向：**要证据**。`registered_paths` 是从真用例的 diff 里数出来的，
    #: 它非空才说明这张表**真的被走到过**（而不是空转或过期）。
    #: ★ 本批清空之后这条反向来写：**表必须空**（空表 = 任何缺键都判红）。
    #: 谁要往里加一行，就得同时说明「它在哪一例里真的被缺到了」——只加正则不加
    #: 证据，这条守卫会红。
    if REGISTERED_MISSING:
        cnt["registered_vacuous"] = 1
        problems.append("allowance 表非空（%d 条），但 80 个用例里被走到的只有 %s "
                        "—— 每一行都必须能指着「它真被缺到的那一例」，否则它就是"
                        "真回归的藏身处。本批已清空：child 与 shield 都搬进 Go 了"
                        % (len(REGISTERED_MISSING), sorted(cnt["registered_paths"]) or "无"))
    else:
        cnt["registered_green"] = 1
    return problems, cnt


def _deepdrop(obj, path: str):
    """按 `a.b[0].c` 这种路径**深拷后**删掉末尾那个键（不动原对象）。"""
    import copy as _copy
    node = _copy.deepcopy(obj)
    cur = node
    parts = re.findall(r"[^.\[\]]+|\[\d+\]", path)
    for step in parts[:-1]:
        cur = cur[int(step[1:-1])] if step.startswith("[") else cur[step]
    last = parts[-1]
    if last.startswith("["):
        del cur[int(last[1:-1])]
    else:
        cur.pop(last, None)
    return node


def main() -> int:
    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：`simgo/spec.py::build_spec`（三个口径，见文件头）")

    import check_specgo_go as C
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception as e:                                       # noqa: BLE001
        raise SystemExit("取不到缓存关卡清单：%s" % e)
    rows = C.real_specs()
    print("分母：A 计划口径 %d 份夹具；B 空计划口径 %d 关；C 计划侧合成 %d 例"
          % (len(rows), len(levels), len(plan_variants())))
    if not rows or not levels:
        print("★ 分母是 0 —— 判据瞎了，不给判定")
        return 1
    print()

    cases: list[dict] = []
    problems_early: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="buildspec_"))

    # ---- A：24 份夹具（带计划）----
    #: A 的 plan 逐份不同 ⇒ 只能一份一条请求（B 那 55 关共用空计划，可以批量）。
    for name, spec, err, lv in rows:
        if spec is None:
            raise SystemExit("生产规格抄不到（%s）：%s" % (name, err))
        ok, resp = go_buildspec_raw({
            "id": 1, "cmd": "buildspec", "level": lv,
            "spec": {"plan": str(FIXDIR / name), "roster": ROSTER_FIX,
                     "allow_devices": True}})
        if not ok:
            raise SystemExit("Go 回 error（%s）：%s" % (name, resp.get("error")))
        add_case(cases, "A %s" % name, spec, resp["build_spec"], expect_plan=True)

    # ---- B：55 关（空计划）----
    #: ⚠ 三态：**可比** / **具名拒跑** / 其它错。拒跑不是本判据的失败，
    #: 但必须**逐关具名**列出来——把它算进「比了 N 例」就是把没比的说成比了。
    got_b = go_buildspec_batch(levels)
    n_refused = 0
    refused: list[str] = []
    for lv, (ok, resp) in zip(levels, got_b):
        if ok:
            add_case(cases, "B %s" % lv, py_from_stage(lv), resp["build_spec"],
                     expect_plan=False)
            continue
        if is_named_refusal(resp):
            n_refused += 1
            refused.append(lv)
            continue
        problems_early.append("B %s：Go 回了**非具名**的错误：%s"
                              % (lv, str(resp.get("error"))[:160]))

    # ---- C：计划侧合成 ----
    for label, raw in plan_variants():
        p = tmp / ("plan_%s.json" % label.split()[0])
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        spec, err = C._capture(raw)
        if spec is None:
            raise SystemExit("合成计划抄不到（%s）：%s" % (label, err))
        ok, resp = go_buildspec_raw({
            "id": 1, "cmd": "buildspec", "level": str(raw["stage"]),
            "spec": {"plan": str(p), "roster": ROSTER_FIX,
                     "allow_devices": True}})
        if not ok:
            raise SystemExit("Go 回 error（%s）：%s" % (label, resp.get("error")))
        add_case(cases, "C %s" % label, spec, resp["build_spec"], expect_plan=True)

    print("一 · 三种结局（分母现算：不把「拒跑」算进「比了」）")
    print("  A 计划口径 %d 例：全部可比（实测 24/24）" % len(rows))
    print("  B 空计划口径 %d 关：可比 %d ＋ 具名拒跑 %d %s"
          % (len(levels), len(levels) - n_refused, n_refused, refused))
    print("  C 计划侧合成 %d 例" % len(plan_variants()))
    print("  可比合计 %d 例" % len(cases))
    print()
    print("二 · 逐用例逐路径对拍（%d 例）" % len(cases))
    problems, cov = compare(cases)
    problems = problems_early + problems
    print("  带雪（走具名三项差）%d 例；已登记缺键 %d 处；"
          "groups 原始次序不同的用例 %d 例（那一处已按格集合口径规范化，见 canon_groups）"
          % (cov["_snow_cases"], cov["_registered_missing"], cov["_groups_order_diff"]))
    #: ★ Python 侧那处静默默认值的**规模与样例**（现算）——不印出来，下一个人
    #: 会以为 B 口径测的就是生产路径。
    print("  ⚠ `SpecInputs.from_stage` 的 fps／speed_scale／ranged_enemies／enemy_windup"
          " 四项**静默落默认**（它用 getattr 读一个 dict），本判据就地补回真实值："
          "%d / %d 关受影响 %s" % (FROM_STAGE_DEFAULTS["n"], len(levels),
                                   FROM_STAGE_DEFAULTS["fields"]))
    if FROM_STAGE_DEFAULTS["sample"]:
        print("     样例：%s" % FROM_STAGE_DEFAULTS["sample"])
    #: 白名单两侧的守卫 ＋ 逐条（按路径分组）报告。
    aguard, acnt = allowance_guards(cases)
    problems += aguard
    print("  REGISTERED_MISSING 逐路径分组（%d 条）:" % len(acnt["registered_paths"]))
    for path, n in sorted(acnt["registered_paths"].items()):
        print("    %-52s %d 处" % (path, n))
    print("    两侧守卫：没登记的缺键判红=%s、登记过的缺键不判红=%s"
          % ("✓" if acnt["unregistered_red"] else "✗",
             "✓" if acnt["registered_green"] else "✗"))
    print()

    print("三 · 覆盖率（19 个键逐个：有几例非空）")
    empty: list[str] = []
    for k in SPEC_KEYS:
        n = cov[k]
        if n == 0 and k not in EMPTY_REGISTRY:
            empty.append(k)
        print("  %s %-14s %d 例非空%s" % ("✓" if n else "✗", k, n,
                                          "" if n else "  ← 全空，须登记"))
    for k, why in EMPTY_REGISTRY.items():
        print("  登记 %-14s 全空：%s" % (k, why))
    if empty:
        problems.append("这些键在全部用例里都为空，而『一致』只是两边都为空的空洞相等：%s"
                        % empty)
    print()

    print("四 · 账（missing_keys / gated_keys / unported）")
    n_missing = sum(1 for c in cases if c["go"].get("missing_keys"))
    n_gated = sum(1 for c in cases if c["go"].get("gated_keys"))
    print("  missing_keys 非空的用例 %d / %d" % (n_missing, len(cases)))
    print("  gated_keys  非空的用例 %d / %d" % (n_gated, len(cases)))
    print()

    print("五 · 契约：不认识的 spec 键必须具名失败")
    ok, resp = go_buildspec_raw({"id": 1, "cmd": "buildspec", "level": levels[0],
                                 "spec": {"plans": "x"}})
    if ok:
        problems.append("拼错的键（plans）被静默忽略 —— 会造出一份内容全空的规格"
                        "而看不出错")
    elif "plans" not in str(resp.get("error", "")):
        problems.append("失败信息没点到那个键：%r" % resp.get("error"))
    else:
        print("  D1 传 plans（拼错）→ 具名失败 ✓")

    print()
    print("六 · 仪器的 p3r 可达性（现算；非 0 即红）")
    n_p3r = p3r_reachable(levels)
    print("  缓存 %d 关里 total_attack 非 None 的：%d" % (len(levels), n_p3r))
    if n_p3r:
        problems.append("有 %d 关带 total_attack —— 单一入口必须改成收 p3r_armed 输入"
                        "（现在恒传 false）" % n_p3r)

    if mutate_mode:
        print()
        print("七 · 反向守卫（每处注入都要独立判红）")
        if problems:
            print("★ 基线本身不干净 ⇒ 反向守卫无从成立")
            return 1
        bad_guard = 0
        for which in MUTATIONS:
            m = mutate(cases, which)
            if m == cases:
                print("  ✗ 注入「%s」**没有落到任何对象上**（空转）" % which)
                bad_guard += 1
                continue
            mp, _c = compare(m)
            ok2 = bool(mp)
            if not ok2:
                bad_guard += 1
            print("  %s 注入「%s」→ %s"
                  % ("✓" if ok2 else "✗", which, "判红" if ok2 else "没红（守不住）"))
        if bad_guard:
            print("★ %d / %d 处注入没判红或空转" % (bad_guard, len(MUTATIONS)))
            return 1
        print("  反向守卫成立：%d / %d 处注入都判红" % (len(MUTATIONS), len(MUTATIONS)))
        return 0

    if problems:
        print("★ %d 处不一致：" % len(problems))
        for m in problems[:20]:
            print("  · %s" % m)
        if len(problems) > 20:
            print("  · …（另有 %d 条）" % (len(problems) - 20))
        print("结论：单一入口对拍**未通过**（%d 处）" % len(problems))
        return 1
    print("结论：%d 例逐路径一致（A 计划 %d ＋ B 空计划 %d ＋ C 合成 %d）；"
          "带雪 %d 例走具名三项差；已登记缺键 %d 处；19 键全部造齐"
          "（missing_keys 空、gated_keys 空）；具名拒跑 %d 关（不计入可比分母）"
          % (len(cases), len(rows), len(levels) - n_refused, len(plan_variants()),
             cov["_snow_cases"], cov["_registered_missing"], n_refused))
    return 0


def p3r_reachable(levels: list[str]) -> int:
    """`total_attack is not None` 的关数（现算）——`p3r_armed` 那个输入的可达性。"""
    from ak_tactic.battle.sim import make_total_attack
    from ak_tactic.gamedata.stage import load_stage

    n = 0
    for lv in levels:
        try:
            if make_total_attack(load_stage(lv)) is not None:
                n += 1
        except Exception:                                        # noqa: BLE001
            continue
    return n


if __name__ == "__main__":
    raise SystemExit(main())
