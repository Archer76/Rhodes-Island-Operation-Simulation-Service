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

## 雪：**已搬进 Go**（第三十九批），不再是口径差

第三十八批以前这里有一条具名放行：Go 判不出雪（要 `find_snow`），于是带雪的
那几关允许 `mechanisms` 少一条、`mech_config` 少一个键、`goal_cells` 恒空。
**雪搬进 Go 之后那三项逐字段相同**，放行段整段删掉（见 `diff_one`）——
留着它等于把一条已经造对的路径重新放行。

★ 但「带雪几例」这个**计数**留着，而且第五节要求它 **> 0**：24 份夹具里带雪的
是 **2 份**（`hsex8_max` / `plan-hs07`）。若哪天变成 0，那条绿就是零信息量的。

## `freeze` 那条的现算可达性（与 `p3r_armed` 同一规矩）

`snow.field.freeze` 是可选入参，**没送就是 true**（权威的默认值）。这条缺省
**不是靠注释担保**的：第五节每次现算两件事 ——
① 扫 `fixtures/ data/ tools/` 有没有人真的送 `freeze`（当前零命中）；
② 现读一次**不送 `freeze`** 的产物，断言它真是 `true`。
哪天有人真送 `false`，缺省路径就得重新证明自己。

## 覆盖率纪律

19 个键**逐个**数「有几例非空」。某个键在全部用例里都是空的 ⇒ 那条「一致」是
零信息量的绿 ⇒ 必须登记（`EMPTY_REGISTRY`），否则判红。

## 冻结基线（`tools/freeze_baseline.py`，套名「单一入口」）

三个口径的期望值全部走 `G.expect()` 冻住；**问题集也一起冻**（A 的夹具清单与关卡号、
B 的缓存关卡批次、C 的计划原文）——只冻答案不冻问题，分母会静默缩水。

* **冻**：A／B／C 三个口径的期望值（键自带输入身份：夹具内容 sha16／关卡 id ＋
  缓存文件 sha16／计划原文 sha16）、四类问题集（`("query", …)`）、一个判定参数键
  （`("consts", "A_fixture_levels")`，`§六·b` 拿它去问 Go）、
  `from_stage_defaults`（那四项静默默认值的**唯一痕迹**）与 `p3r_reachable`
  （Python 侧的可达关数）；
* **不冻**（`SECTIONS` 里逐段具名）：槽账（§二·四）、allowance 白名单两侧守卫、
  §五 契约、§六·b 的 freeze 可达性 —— 它们的宾语是**活 Go** 的产物，
  冻住就没有宾语（冻 Go 自己的产物＝两条同源读数互证，证不了「参数真被读」）。
  ⇒ 这一套的状态是**部分覆盖**，**不进「跑通」的分子**。

跑法：
    python tools\\freeze_baseline.py --record 单一入口
    $env:RIOS_GOLDEN="check"
    python tools\\freeze_baseline.py --run-script tools\\check_buildspec_go.py

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
import freeze_baseline as GB                                   # noqa: E402

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

#: 逐段声明覆盖面（第四态「部分覆盖」的依据）。★ **只有真不适用等值冻结的段才写上来**：
#: 全可冻的段不许声明 —— 声明了就把这一套变成「部分覆盖」，永远不进「跑通」的分子。
SECTIONS = [
    {"id": "§二 A 计划口径（24 份夹具）", "class": "frozen",
     "why": "Python 的生产规格（check_specgo_go.real_specs 里那句 build_spec）"
            "↔ Go buildspec 的 19 键，逐路径比"},
    {"id": "§二 B 空计划口径（缓存可达的关卡）", "class": "frozen",
     "why": "py_from_stage（SpecInputs.from_stage ＋ build_spec）↔ Go buildspec"},
    {"id": "§二 C 计划侧合成（3 例）", "class": "frozen",
     "why": "check_specgo_go._capture(raw) ↔ Go buildspec（把真夹具零行使的两条支走到）"},
    {"id": "§二·四 槽账 missing_keys／gated_keys／unported", "class": "live_both",
     "why": "断言打的是**活 Go 记录自己**那三个槽（非空即红、每条来源至少一条）——"
            "脚本侧只有结构规则，没有可冻的 Python 期望值；冻住等于把 Go 自己的产物"
            "跟它自己比（恒等假绿）"},
    {"id": "§二 allowance 白名单两侧守卫", "class": "live_both",
     "why": "反向注入用 _deepdrop 删**活 Go 规格**里的一条路径"
            "（operators[0].max_hp）再看判据红不红 —— 冻住就没有宾语，"
            "而「有宾语」正是这一段要证的事"},
    {"id": "§三 19 键行使计数", "class": "frozen",
     "why": "计数现算自**冻的**期望值（每个键在全部用例里几例非空）：某个键全空 ⇒ "
            "那条「一致」是两边都为空的空洞相等 ⇒ 判红（EMPTY_REGISTRY 的纪律）"},
    {"id": "§五 认不得的 spec 键必须具名失败", "class": "live_both",
     "why": "宾语是**活 Go** 的应答（传拼错的 plans 必须拒跑并点到那个键）；"
            "脚本侧没有可取期望值的 Python 产物 ⇒ 冻住没有宾语"},
    {"id": "§六 p3r 可达性", "class": "frozen",
     "why": "Python 侧 make_total_attack 的**可达关数**（现算值冻住；非 0 即红）"},
    {"id": "§六·b 积雪 freeze 缺省可达性", "class": "live_both",
     "why": "两次都读**活 Go** 的产物（不送 freeze ↔ 送 freeze=false）＋一次仓库扫描；"
            "冻 Go 自己的产物＝两条同源读数互证，证不了「参数真被读」"},
    {"id": "§七 反向守卫（--mutate）", "class": "frozen",
     "why": "8 处注入打在**冻的**期望值上，判红来源是活 Go 的逐路径比；"
            "注入空转即判红"},
]


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


# ---------------------------------------------------------------- 冻结通道的取数口

_A_BATCH = None


def fixture_records() -> list[dict]:
    """夹具批次的**输入身份**：文件名 ＋ 文件字节 sha16（数据侧算，冻结档也跑得动）。

    ★ 入选条件与 `check_specgo_go.real_specs()` **逐字同口径**（带 deploys／deploy
    的那几份）：判据侧要能**独立**数出「这一批该问几份」，否则分母只能照抄 Python。
    """
    out: list[dict] = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append({"name": f.name, "sha16": GB.file_sha16(f)})
    return out


def _a_batch() -> list:
    """A 口径的 Python 侧取数（★ **只在非冻结档调**）：`real_specs()` 的原样。

    ★ 缓存一份：`real_specs()` 每份夹具要走一次生产路径（排程 ＋ `build_spec`），
    不缓存的话 24 个键会各跑一遍。
    """
    global _A_BATCH
    if _A_BATCH is None:
        import check_specgo_go as C                              # noqa: PLC0415
        _A_BATCH = list(C.real_specs())
    return _A_BATCH


def _a_query() -> list:
    """A 口径的问题集：夹具名 ＋ 关卡 id（★ 关卡 id 只有 Python 侧算得出来）。"""
    return [[r[0], r[3]] for r in _a_batch()]


def _a_lv_map() -> dict:
    """A 口径的**判定参数**：夹具名 → 关卡 id（`§六·b` 要拿它去问 Go）。"""
    return {r[0]: r[3] for r in _a_batch()}


def _a_expect(name: str) -> dict:
    """A 口径的期望值：一份夹具的生产规格；抄不到就连具名错因一起交上去。"""
    for n, spec, err, _lv in _a_batch():
        if n == name:
            if spec is None:
                return {"spec": None, "why": err or ""}
            return {"spec": spec, "why": ""}
    raise SystemExit("★ 生产规格那一批里没有这份夹具：%s" % name)


def _c_query() -> list:
    """C 口径的问题集：标签 ＋ 计划原文 ＋ 计划原文 sha16。

    ★ 计划原文**必须一起冻**：冻结档写不出喂给 Go 的那份计划文件就没有宾语
    （与 `check_specgo_go` 的 syn 那批同一条规矩）。
    """
    out: list = []
    for label, raw in plan_variants():
        out.append([label, raw,
                    GB.sh16(json.dumps(raw, sort_keys=True, ensure_ascii=False,
                                       separators=(",", ":")).encode("utf-8"))])
    return out


def _c_capture(raw: dict) -> dict:
    """C 口径的期望值：把一份打法 dict 走生产路径抄成规格。★ import 住函数里。"""
    import check_specgo_go as C                                  # noqa: PLC0415
    spec, err = C._capture(raw)
    return {"spec": spec, "why": err or ""}


def _fsd_snapshot() -> dict:
    """`FROM_STAGE_DEFAULTS` 的现算快照（`py_from_stage` 逐关累加出来的）。

    ★ **一个读数之所以要冻，不是因为它是个数，而是因为它是某件事的唯一痕迹**
    （出处：本轮交付方给的逐段审计）：那四项静默默认值**只在 Python 侧**算得出来，
    它是「B 口径与真实关卡静态差在哪」这件事的唯一痕迹。冻结档里 `py_from_stage`
    不会被调用（期望值直接读冻的那份）——不冻这一行，第二节那句「N / M 关受影响」
    就会退化成恒为 0 的空话。
    """
    return {"n": int(FROM_STAGE_DEFAULTS["n"]),
            "sample": str(FROM_STAGE_DEFAULTS["sample"]),
            "fields": dict(FROM_STAGE_DEFAULTS["fields"])}


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
    #: ⚠ 2026-09-23（第三十九批）：**这里原先有一段「有雪时按具名三项差放行」** ——
    #: 那时 Go 判不出雪（`mechanisms` 少一条、`mech_config` 少一个键、
    #: `goal_cells` 因门恒关而为空）。雪搬进 Go 之后那三项**必须逐字段相同**，
    #: 所以整段删掉：现在雪那一路与别的路**同一条判据**，不再有特例。
    #: 下面只剩一条**断言性的**计数用途：`snow` 用来数「带雪几例」，
    #: 免得「没有一份带雪」这种零行使的绿蒙混过去（见第五节）。
    for path, pv, gv in diff_paths(py, go):
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
    #
    #: ★★ 2026-09-23（第三十九批）**按口径改了这一条**：`mechspec` 那一路（田地 ＋ 雪）
    #: 现在**有排程就全造得出来**，于是带计划的用例里 `mechspec:` **应当一条都没有**。
    #: 「至少一条」那条老规矩在这里会变成**假红**。改成两条各自可判的：
    #:   · 带计划（有排程）⇒ `mechspec` 必须**零条**（全造得出来）；
    #:   · 不带计划（`mechspec` 命令那条口径）⇒ 必须**恰有雪那一条**（它确实做不到）。
    #: 这样「合并静默为空」照样盖得住：真静默丢时，前者会出现不该有的条目、
    #: 后者会少一条。
    unp = rec.get("unported") or []
    mech_entries = [u for u in unp if u.startswith("mechspec: ")]
    if expect_plan:
        if mech_entries:
            bad.append("%s：带计划的用例里 `mechspec` 还有未搬条目 %s —— "
                       "有排程时田地与雪都该造得出来" % (name, mech_entries))
    else:
        if len(mech_entries) != 1:
            bad.append("%s：不带计划的用例里 `mechspec` 的未搬条目应恰有 1 条"
                       "（雪），实得 %d 条：%s" % (name, len(mech_entries),
                                                  mech_entries))
    srcs = ["spawns", "unsupported"] + (["operators"] if expect_plan else [])
    for src in srcs:
        if not any(u.startswith(src + ": ") for u in unp):
            bad.append("%s：unported 里没有 %s 的来源条目（合并静默为空？）现得 %s"
                       % (name, src, json.dumps(unp, ensure_ascii=False)[:200]))
    #: 本入口自己那条：★ `goal_cells：` **已删**（第三十九批，雪搬进来之后那道门
    #: 会开、不再需要放行），所以这里只剩 `p3r_armed` 一条。
    for own in ("spawns[].p3r_armed：",):
        if not any(u.startswith(own) for u in unp):
            bad.append("%s：unported 里缺本入口自己的那条 %s" % (name, own))
    return bad


# ---------------------------------------------------------------- 反向守卫

MUTATIONS = ("改一个标量", "少一条 spawn", "operators 少一个", "mechanisms 少一个",
             "mech_config 挖空", "goal_cells 塞一格",
             "雪 interval 改一个数", "雪 ground 排序打乱")


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
        #: ★ 第三十九批：**雪那一支**的两处注入（PM 指定）。
        #: ① 改一个数：`interval` 是「每几秒铺一层」，逐字段比必须看见它；
        #: ② 排序打乱：`ground` 的顺序是**硬约束**（扩散上限先被谁占掉）——
        #:    它被打乱而判据不红的话，「顺序一致」这句话就没人证过。
        if which.startswith("雪 "):
            cfg = (py.get("mech_config") or {}).get(SNOW_ID)
            if not cfg or not cfg.get("fields"):
                continue
            f0 = cfg["fields"][0]
            if which == "雪 interval 改一个数":
                f0["interval"] = float(f0.get("interval", 0.0)) + 1.0
                return out
            if which == "雪 ground 排序打乱" and f0.get("ground"):
                f0["ground"] = list(reversed(f0["ground"]))
                return out
            continue
    return out


def add_case(cases: list[dict], name: str, py: dict, rec: dict,
             *, expect_plan: bool) -> None:
    """收一条可比用例：**先规范化那一个字段**，再把「原始次序是否不同」记成读数。"""
    gospec = rec["spec"]
    py_before = canon_groups(py)
    go_before = canon_groups(gospec)
    cases.append({"name": name, "py": py, "go": rec, "expect_plan": expect_plan,
                  "groups_order_diff": bool(py_before) and py_before != go_before})


def freeze_reachability(cases: list[dict], lv_map: dict) -> tuple[list[str], dict]:
    """`freeze` 缺省值的**现算可达性** —— 与 `p3r_reachable` 同一条规矩。

    ⚠ `lv_map`（夹具名 → 关卡号）是**参数**：它只有 Python 侧算得出来，冻结档
    读的是冻的那一份（`("consts", "A_fixture_levels")`）—— 本函数自己**不 import
    `ak_tactic`**，冻的是参数不是宾语。

    三件事都要真做，缺一条这段就是零信息量的绿：

      ① **缺省面**：**不送** `freeze` 时产物里 `snow.field.freeze` 必须是 `true`
         （与权威的默认值同值）；
      ② **正对照**：**送** `freeze: false` 必须**翻成 false** —— 没有这一条，
         「缺省 true」可能只是**参数根本没被读**（那种绿最像真的）；
      ③ **仓库面**：`git grep -n snow_freeze -- fixtures data tools` 在**排除本文件**
         之后必须**零命中**（rc=1）。有人在夹具/工具里真送 `snow_freeze`，
         这条缺省就得重新证明。
         ⚠ 排除本文件是**必须的**：判据自己的正文里就有这四个字（上面这两行、
         以及下面那条 `git grep` 的实参）—— 不排除的话它**扫到自己**、
         永远命中，那条断言就成了恒假红。本仓为此记过一条：
         「在文档里写名字去证明『它不在仓库里』会自指」（`9d74eab8`）。
    """
    import subprocess

    bad: list[str] = []
    cov = {"snow_cases": 0, "default_true": 0, "flip_false": 0, "scan_hits": 0,
           "scan_excluded": 0}
    snow = [c for c in cases if SNOW_ID in (c["py"].get("mechanisms") or [])]
    cov["snow_cases"] = len(snow)
    if not snow:
        bad.append("没有一份带雪的用例 —— `freeze` 这条**无从取证**（要么雪没造出来，"
                   "要么 24 份里真的没雪，两种都要看）")
        return bad, cov
    #: ③ 仓库面：用 `git grep`（快且只扫在库文件；`data/` 很大不能 rglob）。
    #: ⚠ **排除本文件**，原因见 docstring 的 ③（不排除就是自指、恒假红）。
    self_rel = str(Path(__file__).resolve().relative_to(ROOT)).replace("\\", "/")
    p = subprocess.run(["git", "-C", str(ROOT), "grep", "-n", "snow_freeze",
                        "--", "fixtures", "data", "tools"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    hits = []
    for ln in p.stdout.decode("utf-8", "replace").splitlines():
        f = ln.split(":", 1)[0].replace("\\", "/")
        if f == self_rel:
            cov["scan_excluded"] += 1
            continue
        hits.append(ln)
    if hits:
        cov["scan_hits"] = len(hits)
        bad.append("仓库里有 %d 处真的写了 `snow_freeze`（取证范围：fixtures/ data/ "
                   "tools/，**已排除本判据自己** %d 处）——缺省 true 这条要重证：\n      %s"
                   % (cov["scan_hits"], cov["scan_excluded"],
                      "\n      ".join(hits)[:400]))
    #: ① ② 现读两次产物（同一关同一计划，只差一个 `freeze`）。
    #: ⚠ 用例名带口径前缀（`A hsex8_max.json`／`C …`）——**取末段**当夹具名，
    #: 别直接拿它去查表（第一版就 `KeyError: 'A hsex8_max.json'`）。
    name = snow[0]["name"].split()[-1]
    if name not in lv_map:
        #: ★ 具名失败，不猜：冻结档的判定参数键里没有它 ⇒ 这一段的宾语不见了。
        bad.append("冻结档的判定参数键里没有这份夹具的关卡号（%s）—— "
                   "`§六·b` 无从取证" % name)
        return bad, cov
    for tag, extra, want, key in (("不送 freeze", {}, True, "default_true"),
                                  ("送 freeze=false", {"freeze": False}, False,
                                   "flip_false")):
        ok, resp = go_buildspec_raw({"id": 1, "cmd": "buildspec",
                                     "level": lv_map[name],
                                     "spec": {"plan": str(FIXDIR / name),
                                              "roster": ROSTER_FIX,
                                              "allow_devices": True, **extra}})
        if not ok:
            bad.append("%s：buildspec 失败 %s" % (tag, resp.get("error")))
            continue
        got = (((resp["build_spec"]["spec"].get("mech_config") or {})
                .get(SNOW_ID) or {}).get("freeze"))
        if got is not want:
            if key == "flip_false":
                bad.append("%s：`freeze` 送 false 却没翻（实得 %r）—— 参数**根本没被读**，"
                           "那条「缺省 true」的绿是假的" % (tag, got))
            else:
                bad.append("%s：`snow.field.freeze`=%r，应为 true（权威默认值）" % (tag, got))
        else:
            cov[key] = 1
        print("  %-18s（%s）→ freeze=%r %s" % (tag, name, got,
                                               "✓" if got is want else "✗"))
    return bad, cov


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
    G = GB.bind("单一入口", __file__)
    #: ★ **逐段声明覆盖面**（第四态「部分覆盖」的依据）。工具按 `class` 计数，
    #: 不按形容词：声明过的段里只要有一段不适用等值冻结，这一套就不进「跑通」的分子。
    G.sections(SECTIONS)
    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：`simgo/spec.py::build_spec`（三个口径，见文件头）")

    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception as e:                                       # noqa: BLE001
        raise SystemExit("取不到缓存关卡清单：%s" % e)

    # ============================================================ 问题集（都走通道）
    #: ★ 「**问哪些问题**」本身就是 Python 侧的产物：A 的**关卡号**只有
    #: `real_specs()` 算得出来（四星档 `#f#` 住在 id 上，不在显示代号上），
    #: C 的**计划原文**要一起带走才写得出发给 Go 的那份文件。只冻答案不冻问题，
    #: 冻结档要么当场响，要么有人「顺手」把查询集改小、分母静默缩水而全绿。
    live_a = fixture_records()
    fsha = {r["name"]: r["sha16"] for r in live_a}
    cov_a = G.coverage("A_plan", [(r["name"], r["sha16"]) for r in live_a])
    if G.mode == GB.CHECK:
        a_batch = G.expect(("query", "A_fixtures"), lambda: live_a)
        lv_map = G.expect(("consts", "A_fixture_levels"), lambda: {})
        covered_a = {tuple(x) for x in cov_a.covered}
        #: ⚠ 未覆盖的**不比**（对账里会具名）——猜＝自己写一份期望值。
        rows = [(r["name"], lv_map[r["name"]]) for r in a_batch
                if r["name"] in lv_map
                and (r["name"], fsha.get(r["name"], "")) in covered_a]
    else:
        if G.mode == GB.RECORD:
            G.expect(("query", "A_fixtures"), lambda: live_a)
            G.expect(("consts", "A_fixture_levels"), lambda: _a_lv_map())
        lv_map = _a_lv_map()
        rows = [(r[0], r[3]) for r in _a_batch()]

    #: B 的批次身份＝「关卡 id ＋ 缓存文件内容 sha16」两件：`cached_levels()` 只决定
    #: 「问哪些」，内容身份另算（数据侧算，冻结档也跑得动）。
    batch = GB.level_inputs(DATA, levels)
    #: 批次**记录**：`--check` 拿现读与它对账。★ 它**不参与判定**（内容身份住在**键**
    #: 里）⇒ 本套**不声明** `batch_consumed`，`--control` 的 P4 因此不适用（具名印出）。
    #: ⚠ 它的**值**还有第二个用处：记下「录基线时问过哪几个对象」，好让冻结档把
    #: 「录完才出现的新对象」与「录过、现在答不上来的对象」分开（见 B 那一圈）。
    q_b = G.expect(("query", "B_level_batch"), lambda: batch)
    asked_b = {(r["level"], r["sha16"]) for r in q_b}

    c_q = G.expect(("query", "C_plans"), lambda: _c_query())

    print("分母：A 计划口径 %d 份夹具；B 空计划口径 %d 关；C 计划侧合成 %d 例"
          % (len(rows), len(levels), len(c_q)))
    if not rows or not levels:
        print("★ 分母是 0 —— 判据瞎了，不给判定")
        return 1
    print()

    cases: list[dict] = []
    problems_early: list[str] = []
    tmp = Path(tempfile.mkdtemp(prefix="buildspec_"))

    # ---- A：24 份夹具（带计划）----
    #: A 的 plan 逐份不同 ⇒ 只能一份一条请求（B 那批共用空计划，可以批量）。
    #: ★ 期望值键自带**夹具内容 sha16**：夹具一改内容，键就配不上（由对账如实报出）。
    for name, lv in rows:
        want = G.expect(("A_plan", name, fsha.get(name, "")),
                        lambda n=name: _a_expect(n))
        if want["spec"] is None:
            raise SystemExit("生产规格抄不到（%s）：%s" % (name, want["why"]))
        ok, resp = go_buildspec_raw({
            "id": 1, "cmd": "buildspec", "level": lv,
            "spec": {"plan": str(FIXDIR / name), "roster": ROSTER_FIX,
                     "allow_devices": True}})
        if not ok:
            raise SystemExit("Go 回 error（%s）：%s" % (name, resp.get("error")))
        add_case(cases, "A %s" % name, want["spec"], resp["build_spec"],
                 expect_plan=True)

    # ---- B：缓存可达的关卡（空计划）----
    #: ⚠ 三态：**可比** / **具名拒跑** / 其它错。拒跑不是本判据的失败，
    #: 但必须**逐关具名**列出来——把它算进「比了 N 例」就是把没比的说成比了。
    #: ★ 对账里的「这一批问过的对象」＝**真的比得到的那些**：具名拒跑是**登记在案的
    #: 结局**，不是覆盖面的洞——把它算成「未覆盖」，这一套在冻结档就永久 rc=6，
    #: 那正是本仓记过的「永久假红等于没有判据」。
    b_levels = [r["level"] for r in batch]
    b_sha = {r["level"]: r["sha16"] for r in batch}
    got_b = go_buildspec_batch(b_levels)
    n_refused = 0
    refused: list[str] = []
    cmp_b: list[tuple[str, dict]] = []
    for lv, (ok, resp) in zip(b_levels, got_b):
        if ok:
            cmp_b.append((lv, resp["build_spec"]))
            continue
        if is_named_refusal(resp):
            n_refused += 1
            refused.append(lv)
            continue
        if G.mode == GB.CHECK and (lv, b_sha[lv]) not in asked_b:
            #: ★ 录基线时**没问过**这个对象（缓存长大了、或那份内容换了）⇒ 判据对它
            #: **没有期望值**：既不比、也不判红。它的出现由下面的批次对账具名报出
            #: （rc=6 ＝「读数不可用、该重录」）。把它的 Go 应答当成**判据红**，
            #: 就是本仓禁的「把两种因压成一个数」——下一个人会去查实现，而真因是
            #: 对象集变了。
            continue
        problems_early.append("B %s：Go 回了**非具名**的错误：%s"
                              % (lv, str(resp.get("error"))[:160]))
    cov_b = G.coverage("B_plan", [(lv, b_sha[lv]) for lv, _g in cmp_b])
    covered_b = {tuple(x) for x in cov_b.covered}
    for lv, gspec in cmp_b:
        if G.mode == GB.CHECK and (lv, b_sha[lv]) not in covered_b:
            #: ⚠ 未覆盖的**不比**（对账里会具名）——猜＝自己写一份期望值。
            continue
        add_case(cases, "B %s" % lv,
                 G.expect(("B_plan", lv, b_sha[lv]),
                          lambda lv=lv: py_from_stage(lv)),
                 gspec, expect_plan=False)

    #: ★ 那四项静默默认值的**唯一痕迹**：`py_from_stage` 在 B 那一圈里逐关累加，
    #: 累完就地**冻住**（口径见 `_fsd_snapshot` 的 docstring）。
    fsd = G.expect(("from_stage_defaults",), _fsd_snapshot)

    # ---- C：计划侧合成 ----
    for label, raw, c_sha in c_q:
        p = tmp / ("plan_%s.json" % label.split()[0])
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        want = G.expect(("C_plan", label, c_sha),
                        lambda raw=raw: _c_capture(raw))
        if want["spec"] is None:
            raise SystemExit("合成计划抄不到（%s）：%s" % (label, want["why"]))
        ok, resp = go_buildspec_raw({
            "id": 1, "cmd": "buildspec", "level": str(raw["stage"]),
            "spec": {"plan": str(p), "roster": ROSTER_FIX,
                     "allow_devices": True}})
        if not ok:
            raise SystemExit("Go 回 error（%s）：%s" % (label, resp.get("error")))
        add_case(cases, "C %s" % label, want["spec"], resp["build_spec"],
                 expect_plan=True)

    print("一 · 三种结局（分母现算：不把「拒跑」算进「比了」）")
    print("  A 计划口径 %d 例：全部可比（实测 24/24）" % len(rows))
    print("  B 空计划口径 %d 关：可比 %d ＋ 具名拒跑 %d %s"
          % (len(b_levels), len(b_levels) - n_refused, n_refused, refused))
    print("  C 计划侧合成 %d 例" % len(c_q))
    print("  可比合计 %d 例" % len(cases))
    print()
    print("二 · 逐用例逐路径对拍（%d 例）" % len(cases))
    problems, cov = compare(cases)
    problems = problems_early + problems
    print("  带雪（**已逐字段比**）%d 例；已登记缺键 %d 处；"
          "groups 原始次序不同的用例 %d 例（那一处已按格集合口径规范化，见 canon_groups）"
          % (cov["_snow_cases"], cov["_registered_missing"], cov["_groups_order_diff"]))
    #: ★ Python 侧那处静默默认值的**规模与样例**（现算）——不印出来，下一个人
    #: 会以为 B 口径测的就是生产路径。
    print("  ⚠ `SpecInputs.from_stage` 的 fps／speed_scale／ranged_enemies／enemy_windup"
          " 四项**静默落默认**（它用 getattr 读一个 dict），本判据就地补回真实值："
          "%d / %d 关受影响 %s" % (fsd["n"], len(b_levels), fsd["fields"]))
    if fsd["sample"]:
        print("     样例：%s" % fsd["sample"])
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
    #: ★ 那条可达性是**只有 Python 侧算得出来**的读数（`make_total_attack` 的宾语），
    #: 非冻结档现算、冻结档读冻的那份 —— 它的输入集就是 B 那批缓存关卡，
    #: 那一批变了由上面的批次对账具名报出。
    n_p3r = G.expect(("p3r_reachable",), lambda: p3r_reachable(levels))
    print("  缓存 %d 关里 total_attack 非 None 的：%d" % (len(levels), n_p3r))
    if n_p3r:
        problems.append("有 %d 关带 total_attack —— 单一入口必须改成收 p3r_armed 输入"
                        "（现在恒传 false）" % n_p3r)

    print()
    print("六·b · 积雪的 `freeze` 缺省值可达性（现算；三件都要真做）")
    fbad, fcov = freeze_reachability(cases, lv_map)
    problems += fbad
    for m in fbad:
        print("  ✗ %s" % m)
    print("  分母：带雪用例 %d 份；缺省 true=%d；送 false 会翻=%d；"
          "仓库面 `snow_freeze` 命中 %d 处"
          % (fcov["snow_cases"], fcov["default_true"], fcov["flip_false"],
             fcov["scan_hits"]))

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

    #: ★ **先给这一跑定性**：工具（`freeze_baseline.named_reason`）认「输出里第一句 ★
    #: 且提到冻结基线的行」当这一套的原因，而下面那行通道读数正是这种行——不先定性，
    #: 它会把「判据红」或「该重录」读成同一句话（那正是两个不同的意思压成一个值，
    #: 本仓记过的那类假信号）。
    if problems:
        print("★ 这一跑是**判据红**（rc=1，%d 处不一致）：宾语是活 Go 的应答，"
              "与通道、与对象集对账都无关（那两者各有自己的码与具名消息）"
              % len(problems))
        print()
    elif G.mode == GB.CHECK and not (cov_a.ok and cov_b.ok):
        print("★ 这一跑是**通道自己的 6**（rc=6）：录的是哪一批对象变了 ⇒ 这读数不可用、"
              "该重录；它与「Go 漂移了」那条判据红分开（对账明细见下）")
        print()

    #: 通道自己的读数：record 档「收下 N 个期望值」／check 档「取期望值 N 次全部命中
    #: 冻的那份，零次吃 Python」。★ 这一行是「这一套真的走通道了吗」的现场证据。
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
        print()

    #: ★ **输入批次对账**：只在冻结档、且两边对不齐时印。它把两种因分开：
    #: 「对象集变了（多了／少了／换了内容）」是**读数不可用**（rc=6，该重录），
    #: 「Go 漂移了」才是判据红（rc=1）——压成一个数，下一个人就无从处置。
    if G.mode == GB.CHECK and not (cov_a.ok and cov_b.ok):
        for _tag, _cov, _n in (("A_plan", cov_a, len(live_a)),
                               ("B_plan", cov_b, len(batch))):
            if _cov.ok:
                continue
            print(_cov.report(_tag, _n))
            _ex = {g[0] for g in _cov.extra}
            _ms = {g[0] for g in _cov.missing}
            _chg, _add, _gone = sorted(_ex & _ms), sorted(_ex - _ms), sorted(_ms - _ex)
            if _chg:
                print("  · ★ **内容变了**（同一个对象的内容 sha 变了，%d 个）：%s"
                      % (len(_chg), "、".join(_chg[:8])))
            if _add:
                print("  · **对象集变了**（新增、基线里没有，%d 个）：%s"
                      % (len(_add), "、".join(_add[:8])))
            if _gone:
                print("  · **对象集变了**（这次没问、但冻着，%d 个）：%s"
                      % (len(_gone), "、".join(_gone[:8])))
        print()

    if problems:
        print("★ %d 处不一致：" % len(problems))
        for m in problems[:20]:
            print("  · %s" % m)
        if len(problems) > 20:
            print("  · …（另有 %d 条）" % (len(problems) - 20))
        print("结论：单一入口对拍**未通过**（%d 处）" % len(problems))
        return 1
    if G.mode != GB.CHECK:
        #: ⚠ 默认档这一档「一致」的宾语是**现算的 Python 期望值**，不是冻的那份：
        #: 不许把它印成「与冻结的基线一致」——本档没有冻的那份，那句话是恒等的、
        #: 零信息量（本仓记过的那类假信号）。
        print("⊘ 默认档不适用「与冻结的基线一致」这一句：本档没有冻的那份，"
              "期望值现取自 Python（这一跑只用来录基线）")
    #: ★ **结论行带上覆盖面**：读这一行的人当场就知道这一档没覆盖哪几段，
    #: 不用另外去跑 `--status`。
    print("结论：%d 例逐路径一致（A 计划 %d ＋ B 空计划 %d ＋ C 合成 %d）；"
          "带雪 %d 例已逐字段比；已登记缺键 %d 处；19 键全部造齐"
          "（missing_keys 空、gated_keys 空）；具名拒跑 %d 关（不计入可比分母）%s"
          % (len(cases), len(rows), len(b_levels) - n_refused, len(c_q),
             cov["_snow_cases"], cov["_registered_missing"], n_refused,
             G.uncovered_sections_text()))
    if G.mode == GB.CHECK and not (cov_a.ok and cov_b.ok):
        #: 比过的部分一致，但**对象集/内容变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
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
