#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：规格闸门（`simgo/spec.py::unsupported_reasons`）vs Go 的 `unsupported`。

## 对的是什么

**生产规格里那个 `unsupported` 键**。它由 `build_spec` 在「排好程、还没跑」那一刻填好，
是「这一局能不能交给 Go 跑」的判据。期望值**不手抄**：照 `check_specgo_go.py` 的
`real_specs()` / `_capture(raw)` 写法，借 `golden_go.SpecCapture` 的钩子点抄完规格就抛哨兵
（`allow_devices=True`，与对拍台同一口径）。

## 这个闸门为什么值钱

在它出现之前，「敌人有技能出手／会重生／会换形态」这种关会**原样交给 Go**，而 Go 那边
这些行为一行都没有，判决却照样给出来——那正是「对拍通过但两边算的不是同一场战斗」。

## ⚠ 24 份真夹具的 `unsupported` **全是空列表**（实测，合计 0 条）

所以「24 份逐条一致」本身是**零信息量的绿**：两边都吐空表也能过。本判据为此做了三件事：

1. **先数分母再报绿**：每条已搬线各被行使几次。**行使 0 次的线必须进 `STRUCTURAL_ZERO`
   登记（带证据 ＋ 重算守卫）**，否则判红——防「判据看起来在覆盖，其实那一支从没走到」。
2. **补合成夹具**：计划侧的「撤退／技能槽号」换计划 dict、走同一套生产路径；
   敌人侧的「觉醒／形态」造**合成关卡**——真关卡里 55 关的出怪表**这两种敌人一个都没有**
   （`awake_value` 非零的只有 2 个 id、`modes` 非空的只有 1 个 id，都不在出怪表里），
   不造就永远走不到。
3. **负对照**：不报的三种情形也要走到（技能槽 0／只有掉装置额度而没有装置部署／普通敌人），
   否则「会报」证明不了「不该报时不报」。

## 未搬线为什么是一个**具名清单**而不是省略

Go 这一版没搬完（干员侧那一圈要的 `operator_view` 与 `SkillEffects` 组装不在 Go 里）。
裸数组只能把它们**静默省略**——那正是这条闸门立规矩要防的事。所以应答分三个槽
（`reasons` / `unported` / `covered`），本脚本对两侧的清单做**双向漂移守卫**：

* Go 的 `unported` 必须**恰好**等于本文件的 `UNPORTED`（哪边改了都会红）；
* 每一条 `UNPORTED` 都要有**证人**（见 `witnesses()`）——证不出来就说明这条登记是假的，
  而「登记了一个其实不存在的线」与「漏登记一条真线」同样是坏账。

★ 两条实测「结构上不可达」的线**不算 unported**（那会谎称 Go 少了一条）：

* `持续自伤`（`hp_drain_per_sec`）：它是**干员**字段（`unit.py:721`），`enemy_view`
  从不设它 ⇒ 两侧都恒不报；
* `被击倒给可部署装置` 的第三个合取项 `inp.device_deployments` 在两个生产路径上恒空
  ——它仍在 `UNPORTED` 里（Go 确实没有这条渠道），由证人 W3 证明它在给定输入下真会报。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场跑 Python（`real_specs` / `SpecCapture` 钩子 /
  `SpecInputs.from_stage` / `unsupported_reasons`），**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/闸门.json`，
  **不 import `ak_tactic`**。

★ 三类读数 ＋ 证人，各自的身份：

  · **A** 24 份真夹具：键 `("unsup_a", 夹具名, 夹具字节 sha16, 名册字节 sha16)`
    ＋ `G.coverage("unsup_a", …)` 对账（夹具集是活的）；
  · **B** 计划侧合成（只换 dict、同一条生产路径）：键 `("unsup_b", 标签, 计划 sha16)`；
  · **C** 敌人侧合成：键 `("unsup_c", 标签, 合成关卡 sha16)`；
  · **证人**：键 `("unsup_w", 证人名)`——每条未搬线都要有证人，所以证人的
    **证据**（Python 真报出来的那几条理由）也冻住，「证不出来」照旧判红；
    W2/W5 那两条只看**源文件正文**（不 import、不运行 Python），照旧每跑一次现算
    ——登记会过期，所以它必须能拿源文件重算。

★ **顺序语义原样保住**：期望值一条一条入冻，**不排序**（原版按 `timeline()` 排，
「顺序对调」是 `--mutate` 的一个注入）。⚠ 冻的是**换行拼起来的一整串**而不是列表：
控制组 P1 会把值里改坏一处，值是列表时哨兵元素会让尺子的正则撞上非字符串而**崩**
（那是 rc=1，形态是崩溃不是判决）；拼成字符串后 P1 得到一条**干净的判据红**
（多出一条切不出线的理由）。

用法:
    python tools\\check_unsupported_go.py
    python tools\\check_unsupported_go.py --mutate
    python tools\\freeze_baseline.py --record 闸门
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
ROSTER_FIX = FIXDIR / "roster_max_modelled.json"

# ---------------------------------------------------------------- 尺子：理由文本 → 线
#
# ⚠ 尺子自己也要有正负对照（`ruler_selftest`）：既认得全，也对**认不出**的当场判红
# ——否则新加一条闸门线时它会安静地漏过去。

LINES: tuple[tuple[str, str], ...] = (
    ("summon_deploy", r"^召唤物部署 ×\d+$"),
    ("device_deploy", r"^装置部署 ×\d+$"),
    ("retreat", r"^撤退 ×\d+$"),
    ("snow_fields", r"^积雪 ×\d+$"),
    ("snow_talent", r"^积雪（天赋「无垠的雪景」）：.+$"),
    ("awake", r"^按田地病害值觉醒：.+$"),
    ("modes", r"^BOSS 换弱点形态：.+$"),
    ("death_token", r"^被击倒给可部署装置：.+$"),
    ("hp_drain", r"^持续自伤：.+$"),
    ("devices", r"^关卡装置 ×\d+$"),
    ("total_attack", r"^全场总攻击装置$"),
    ("skill_name", r"^技能：.+$"),
    ("skill_slot", r"^技能槽号 \d+（.+）：调用方要先把 SkillLevel 绑好再生成规格$"),
    #: ⚠ 长的排在短的前面：`天赋回技力（出手）：X` 会被裸的 `天赋回技力` 前缀吃掉。
    ("operator_side",
     r"^(召唤物|锤击|技能效果覆盖|天赋回技力（出手）|天赋回技力（击杀）|高台触发回技力"
     r"|天赋「强击瓶专家」一次出手多轮|物理闪避|法术闪避|攻击力光环|防御光环|免死"
     r"|弱点伤害|天赋攻速|技能治疗倍率（heal_scale）|天赋回技力|天赋「翔虫机动」)：.+$"),
)

LINE_RX = tuple((name, re.compile(rx)) for name, rx in LINES)

#: Go 已搬的线（＝ Go **会**把它当理由报出来的那些）。
#:
#: ★★ 2026-09-25：**`retreat` 从这张表里移出去了**，这是本仓第一处
#: 「Go 比参照实现**多做了一步**」造成的分道扬镳：
#: 博士「你现在把撤退机制做了吧」⇒ Go 侧实现了撤退（规格多一个 `retreats` 键、
#: `sim.go` 帧序 1c 按时刻执行）⇒ **不再把「撤退 ×N」当拒跑理由**；
#: 而参照实现（`ak_tactic/simgo/spec.py:146-151`）仍然报它。
#: ⇒ 判据这一侧若还把 `retreat` 当「已搬的线」，就会把「Go 多做了」读成红。
#: ⚠ 这不是放宽：`LINES` 里那条正则**留着**（尺子仍认得出它，正负对照仍跑它），
#: 只是**不再期望 Go 报它**。若哪一天 Go 又把它报出来，`reasons` 会多一条 ⇒ 判红。
PORTED = ("summon_deploy", "device_deploy", "skill_slot", "snow_fields",
          "awake", "modes")

#: Go **算不了**的线（与 `rios-sim/unsupported.go::unportedLines` 同源，双向守卫）。
UNPORTED = ("skill_name", "snow_talent", "devices", "total_attack", "death_token",
            "operator_side")

#: 已搬、但**任何生产路径都点不着**的线：行使计数必然是 0，故带证据登记。
#: 每条都写清「为什么点不着」，并由 `structural_guards()` 拿代码重算一遍
#: ——理由会过期而没人知道，所以登记必须配一个会红的守卫。
STRUCTURAL_ZERO: dict[str, str] = {
    "summon_deploy": "计划（`plan.Plan`）没有召唤物部署通道；`verify.py` 也不调 "
                     "`plan_summon`（只有直接建 sim 的工具脚本才调）",
    "device_deploy": "同上：计划没有装置通道，`verify.py` 从不调 `plan_device`",
    "snow_fields": "`inp.snow_fields` 是**部署那一刻**才 append 的，规格取的是开局态 ⇒ 恒空",
}

#: **两侧都不报**的线：连 Python 都点不着，所以 Go 不实现它**不是缺口**。
#: 若哪天 Python 真报出来了，Go 没搬 ⇒ 那就是真缺口 ⇒ 判红（见 compare）。
BOTH_SIDE_ZERO: dict[str, str] = {
    "hp_drain": "`hp_drain_per_sec` 是**干员**字段（`unit.py:721`、`operator_view.py:179`），"
                "而 `enemy_view` 从不设它 ⇒ 24 份夹具 1154 个出怪对象命中 0",
}

#: `operator_side` 这条登记的依据：这些属性字面量必须仍在 `unsupported_reasons` 里。
#: 少一个就说明那条线被删/改名了 ⇒ 登记过期 ⇒ 判红。
OPERATOR_ATTRS = (
    "summon_of", "hammer", "effects_override", "sp_per_attack_talent",
    "sp_per_kill_talent", "dodge_phys", "dodge_arts", "aura_atk_pct",
    "aura_def_pct", "blessing_save", "weakness_damage", "aspd_when_free",
    "aspd_high_ground", "power_attack_count", "heals",
)

#: 尺子自检的已知答案（正例）。留在这里而不是写死在函数里，是为了让它可被引用核对。
RULER_KNOWN: tuple[tuple[str, str], ...] = (
    ("撤退 ×3", "retreat"),
    ("装置部署 ×1", "device_deploy"),
    ("召唤物部署 ×2", "summon_deploy"),
    ("积雪 ×4", "snow_fields"),
    ("积雪（天赋「无垠的雪景」）：圣聆初雪(char_1046_sbell2)", "snow_talent"),
    ("按田地病害值觉醒：天桩-甲", "awake"),
    ("BOSS 换弱点形态：“死志的凝结”", "modes"),
    ("被击倒给可部署装置：田鼷飞贼", "death_token"),
    ("持续自伤：某干员", "hp_drain"),
    ("关卡装置 ×8", "devices"),
    ("全场总攻击装置", "total_attack"),
    ("技能：泥岩", "skill_name"),
    ("技能槽号 1（泥岩）：调用方要先把 SkillLevel 绑好再生成规格", "skill_slot"),
    ("天赋回技力（出手）：泥岩", "operator_side"),
    ("天赋回技力：泥岩", "operator_side"),
    ("天赋「翔虫机动」：泥岩", "operator_side"),
)

#: 尺子自检的负例：这些**必须**认不出（认出来说明尺子宽到会把别的理由吞掉）。
RULER_UNKNOWN: tuple[str, ...] = ("这条理由不存在", "撤退×1", "", "撤退 ×")


def line_of(reason: str) -> str | None:
    """理由文本 → 线名；认不出返回 None（调用方必须判红，不许当空）。"""
    for name, rx in LINE_RX:
        if rx.match(reason):
            return name
    return None


def ruler_selftest() -> list[str]:
    """尺子的正负对照：不依赖被测对象，就地给结论。"""
    bad = []
    for text, want in RULER_KNOWN:
        got = line_of(text)
        if got != want:
            bad.append("尺子自检：%r 切成 %r，应为 %r" % (text, got, want))
    for text in RULER_UNKNOWN:
        if line_of(text) is not None:
            bad.append("尺子自检：%r 本该认不出，却切成了 %r" % (text, line_of(text)))
    #: 覆盖面对账：每条登记在册的线都要在正例里出现过（防「线加了、尺子没加」）。
    seen = {want for _t, want in RULER_KNOWN}
    missing = [ln for ln, _rx in LINES if ln not in seen]
    if missing:
        bad.append("尺子自检：这些线没有正例（尺子的覆盖面窄于登记）：%s" % missing)
    return bad


# ---------------------------------------------------------------- 两侧读数

def go_unsupported_raw(req: dict) -> tuple[bool, dict]:
    """调 Go 并**如实**回传 `(ok, 整个应答)` —— 给「必须失败」那条控制组用。"""
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    p = subprocess.run([GO_BIN], input=(json.dumps(req) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    lines = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not lines:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(lines[0])
    return bool(resp.get("ok")), resp


def go_unsupported(*, level: str = "", path: str = "", plan: str = "",
                   allow_devices: bool = True, allow_skills: bool = False) -> dict:
    """调 Go 的 `unsupported`。关卡走 level（关卡号／levelId）或 path（合成关卡）。"""
    spec: dict[str, object] = {"allow_devices": allow_devices,
                               "allow_skills": allow_skills}
    if plan:
        spec["plan"] = plan
    req: dict[str, object] = {"id": 1, "cmd": "unsupported", "spec": spec}
    if level:
        req["level"] = level
    if path:
        req["path"] = path
    ok, resp = go_unsupported_raw(req)
    if not ok:
        raise SystemExit("Go 回 error：%s" % resp.get("error"))
    out = resp["unsupported"]
    #: 口径回显核对：Go 必须按**我要求的那一档**答（口径只活在散文里最危险）。
    par = out.get("params") or {}
    if bool(par.get("allow_devices")) != bool(allow_devices) or \
            bool(par.get("allow_skills")) != bool(allow_skills):
        raise SystemExit("Go 回显的口径与请求不符：%s" % json.dumps(par, ensure_ascii=False))
    return out


def py_from_stage(level_path: Path, *, device_deploys: int = 0) -> list[str]:
    """合成关卡的**权威期望值**：`SpecInputs.from_stage`（不碰模拟器的那个构造器）
    ＋ `unsupported_reasons`。理由文案由权威函数产出，本脚本一个都不手写。"""
    inp = build_inp_from_stage(level_path, device_deploys=device_deploys)
    from ak_tactic.simgo.spec import unsupported_reasons
    return unsupported_reasons(inp, allow_devices=True)


def build_inp_from_stage(level_path: Path, *, device_deploys: int = 0):
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.frontend.schedule import Schedule
    from ak_tactic.gamedata.enemy import EnemyLibrary
    from ak_tactic.gamedata.stage import parse_stage

    raw = json.loads(level_path.read_text(encoding="utf-8"))
    stage = parse_stage(raw, level_id=str(raw.get("_levelId") or "syn"),
                        code="SYN-UNSUP", difficulty="NORMAL")
    lib = EnemyLibrary()
    sched = Schedule()
    for _ in range(device_deploys):
        sched.plan_device(object())
    return SpecInputs.from_stage(stage, enemy_at=lib.get,
                                 species_provider=lib.species_of, schedule=sched)


def capture_inp(raw: dict):
    """借 `SpecCapture` 的钩子点抄一份**活的输入快照**（不跑判决）。"""
    import check_specgo_go as C
    import golden_go as G
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.plan import Plan, Roster

    class Only(G.SpecCapture):
        def _run_other_engine(self, **kw):
            self.inp = SpecInputs.from_sim(kw["sim"])
            raise C._Captured()

    v = Only()
    try:
        v.run(Plan.from_dict(raw), roster=Roster.from_json(ROSTER_FIX))
    except C._Captured:
        pass
    except Exception as e:                                       # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
    return getattr(v, "inp", None), None


# ---------------------------------------------------------------- 期望值（可冻）
_A_BATCH = None


def join_lines(rows) -> str:
    """理由清单 → 一串（**顺序原样**）。带换行的理由当场响（拼串会静默吞结构）。"""
    out = []
    for x in rows:
        if not isinstance(x, str) or "\n" in x:
            raise SystemExit("★ 闸门的理由不是单行字符串：%r" % (x,))
        out.append(x)
    return "\n".join(out)


def split_lines(text) -> list:
    """一串 → 理由清单（`join_lines` 的逆运算，**两种模式共用这一个口**）。"""
    return [x for x in (text or "").split("\n") if x]


def blob_id(blob: dict) -> str:
    """合成用例的**内容身份**（数据侧算，不 import `ak_tactic`）。"""
    return GB.sh16(json.dumps(blob, sort_keys=True, ensure_ascii=False,
                              separators=(",", ":")).encode("utf-8"))


def scan_plan_fixtures() -> list[list]:
    """夹具批次的输入身份（数据侧；`utf-8-sig` 与 `real_specs()` 同源）。"""
    out: list[list] = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append([f.name, GB.file_sha16(f)])
    return out


def stage_of(name: str) -> str:
    """夹具里的关卡 id（**数据侧**）：A 段调 Go 用的就是它（`real_specs()` 同源）。"""
    d = json.loads((FIXDIR / name).read_text(encoding="utf-8-sig"))
    return str(d.get("stage") or "")


def py_unsup_a() -> list[list]:
    """A：24 份真夹具的期望值（**离冻档专用**；import 全在 `real_specs` 里）。"""
    import check_specgo_go as C
    rsha = GB.file_sha16(ROSTER_FIX)
    out: list[list] = []
    for name, spec, err, _lv in C.real_specs():
        if spec is None:
            raise SystemExit("生产规格抄不到（%s）：%s" % (name, err))
        out.append([name, GB.file_sha16(FIXDIR / name), rsha,
                    join_lines(list(spec.get("unsupported") or []))])
    return out


def _a_batch() -> list[list]:
    global _A_BATCH
    if _A_BATCH is None:
        _A_BATCH = py_unsup_a()
    return _A_BATCH


def _a_expect(name: str) -> str:
    for b in _a_batch():
        if b[0] == name:
            return b[3]
    raise SystemExit("★ 生产规格那一批里没有这份夹具：%s" % name)


def py_unsup_plan(raw: dict) -> str:
    """B：换计划 dict、走**同一条生产路径**。"""
    import check_specgo_go as C
    spec, err = C._capture(raw)
    if spec is None:
        raise SystemExit("合成计划抄不到（%s）：%s" % (raw.get("title"), err))
    return join_lines(list(spec.get("unsupported") or []))


def py_unsup_level(path) -> str:
    """C：合成关卡的期望值（`from_stage` ＋ 权威函数）。"""
    return join_lines(py_from_stage(path))


def py_w1() -> str:
    """W1 的证据：`allow_devices=False` 时 Python 真报出来的那几条。"""
    from ak_tactic.simgo import spec as S
    fx = json.loads((FIXDIR / "hsex8.json").read_text(encoding="utf-8-sig"))
    inp, err = capture_inp(fx)
    if inp is None:
        raise SystemExit("W1 抄不到 hsex8 的输入：%s" % err)
    return join_lines(S.unsupported_reasons(inp, allow_devices=False))


def py_w2() -> str:
    """W2 的证据：计划的 `skill` 写成对象时 Python 报出来的那几条。"""
    from ak_tactic.simgo import spec as S
    obj = {"stage": BASE_PLAN["stage"], "title": "w",
           "deploys": [base_deploy({"id": "skchr_mudrok_2", "level": 7})]}
    inp2, err2 = capture_inp(obj)
    if inp2 is None:
        raise SystemExit("W2 抄不到对象技能的计划：%s" % err2)
    return join_lines(S.unsupported_reasons(inp2, allow_devices=True))


def py_w3(path) -> str:
    """W3 的证据：给排程塞一条装置部署时 Python 报出来的那几条。"""
    from ak_tactic.simgo import spec as S
    return join_lines(S.unsupported_reasons(
        build_inp_from_stage(path, device_deploys=1), allow_devices=True))


def py_w4() -> dict:
    """W4 的证据：`ALLOW_SNOW` 的现读 ＋ `hsex8_max` 的 snow_spec 片数。"""
    from ak_tactic.simgo import spec as S
    maxplan = json.loads((FIXDIR / "hsex8_max.json").read_text(encoding="utf-8-sig"))
    inp4, err4 = capture_inp(maxplan)
    return {"allow_snow": getattr(S, "ALLOW_SNOW", None) is True,
            "n_fields": len(S.snow_spec(inp4)) if inp4 is not None else -1,
            "why": err4 or ""}


# ---------------------------------------------------------------- 合成夹具

def synth_level(*, awake_at: float | None = None, modes_at: float | None = None,
                token_at: float | None = None, slime_at: float | None = None) -> dict:
    """一份最小关卡：把敌人侧那几条线按**指定的出怪时刻**摆上去。

    时刻决定**理由的顺序**（原版按 `timeline()` 的 (t, wave, fragment) 排），
    所以时刻做成参数——顺序对调的那一例就是靠它照出来的。

    四只都是**真敌人库里的 id**（不是造的）：
    `enemy_1398_dhdcr`（天桩-甲，`CheckAwake.value=100`）、
    `enemy_1589_pppdth`（`“死志的凝结”`，`modes` 有 Mode_A/Mode_B）、
    `enemy_1397_dhtsxt`（田鼷飞贼，`death_token=trap_139_dhtl`）、
    `enemy_1007_slime_3`（源石虫·β，四个字段全空 —— 负对照）。
    """
    floor = {"tileKey": "tile_floor", "heightType": "LOWLAND",
             "buildableType": "MELEE", "passableMask": "ALL"}
    want = (("enemy_1398_dhdcr", awake_at), ("enemy_1589_pppdth", modes_at),
            ("enemy_1397_dhtsxt", token_at), ("enemy_1007_slime_3", slime_at))
    actions = []
    for key, t in want:
        if t is None:
            continue
        actions.append({"actionType": "SPAWN", "key": key, "count": 1,
                        "preDelay": float(t), "interval": 1.0, "routeIndex": 0,
                        "blockFragment": False, "hiddenGroup": None})
    return {
        "_levelId": "syn_unsup_01",
        "mapData": {"map": [[0] * 5 for _ in range(5)], "tiles": [floor]},
        "routes": [{"motionMode": "WALK",
                    "startPosition": {"col": 0, "row": 4},
                    "endPosition": {"col": 4, "row": 0},
                    "checkpoints": [{"type": "MOVE",
                                     "position": {"col": 4, "row": 4}}]}],
        "enemyDbRefs": [{"useDb": True, "id": k, "level": 1,
                         "overwrittenData": None} for k, _ in want],
        "waves": [{"preDelay": 0, "postDelay": 0,
                   "maxTimeWaitingForNextWave": -1,
                   "fragments": [{"preDelay": 0, "actions": actions}]}],
        "options": {},
    }


#: 一份跑得通的真关卡＋真干员计划，用来派生计划侧的用例（只换计划 dict）。
BASE_PLAN: dict = {
    "stage": "act31side_ex08", "title": "闸门判据用",
    "deploys": [{"operator": "泥岩", "position": [9, 4], "direction": "Left",
                 "skill": 0, "elite": 2, "level": 90, "potential": 6,
                 "module_level": 0}],
}


def base_deploy(skill: object = 0) -> dict:
    d = copy.deepcopy(BASE_PLAN["deploys"][0])
    d["skill"] = skill
    return d


def plan_variants() -> list[tuple[str, dict]]:
    """计划侧：已搬的那两条线 ＋ 两个负对照。"""
    return [
        ("计划：一个理由都没有（负对照）",
         {"stage": BASE_PLAN["stage"], "title": "w", "deploys": [base_deploy(0)]}),
        ("计划：撤退 ×1",
         {"stage": BASE_PLAN["stage"], "title": "w", "deploys": [base_deploy(0)],
          "retreats": [{"operator": "泥岩", "time": 30.0}]}),
        ("计划：技能槽 1",
         {"stage": BASE_PLAN["stage"], "title": "w", "deploys": [base_deploy(1)]}),
        ("计划：撤退 ×2 ＋ 技能槽 3（排程在前）",
         {"stage": BASE_PLAN["stage"], "title": "w", "deploys": [base_deploy(3)],
          "retreats": [{"operator": "泥岩", "time": 30.0},
                       {"operator": "泥岩", "time": 60.0}]}),
        ("计划：技能槽 0（负对照：不报）",
         {"stage": BASE_PLAN["stage"], "title": "w", "deploys": [base_deploy(0)]}),
    ]


def level_variants() -> list[tuple[str, dict]]:
    """敌人侧：两条已搬线 ＋ 顺序对调 ＋ 两个负对照。"""
    return [
        ("关卡：觉醒＋形态（形态更早 ⇒ 形态在前）",
         synth_level(awake_at=5.0, modes_at=2.0)),
        ("关卡：顺序对调（觉醒更早 ⇒ 觉醒在前）",
         synth_level(awake_at=2.0, modes_at=5.0)),
        ("关卡：只有觉醒", synth_level(awake_at=3.0)),
        ("关卡：只有掉装置额度、没有装置部署（负对照：不报）",
         synth_level(token_at=3.0)),
        ("关卡：普通敌人（负对照：不报）", synth_level(slime_at=3.0)),
    ]


# ---------------------------------------------------------------- 读数（各跑一次）

class Reading:
    def __init__(self, name: str, expected, go: dict, note: str = ""):
        self.name = name
        #: 期望值是**一串**（见文件头：拼串是为了让 P1 得到干净的判据红），
        #: 这里拆回逐条；传列表也接受（`mutate` 走的就是那条）。
        self.expected = (split_lines(expected) if isinstance(expected, str)
                         else list(expected))
        self.go = go
        self.note = note


def build_readings(tmp: Path, G, rows_a: list[list]) -> list[Reading]:
    """把两侧读数**各跑一次**收齐。后面所有比较（含 --mutate）都在内存里做。"""
    out: list[Reading] = []
    rsha = GB.file_sha16(ROSTER_FIX)
    # ---- A. 24 份真夹具：生产路径（`real_specs` 与对拍台同一口径）----
    for name, ident, _rs in rows_a:
        #: ★ 键自带输入身份：夹具或名册变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        exp = G.expect(("unsup_a", name, ident, rsha),
                       lambda name=name: _a_expect(name))
        out.append(Reading(
            "真夹具 %s" % name, exp,
            go_unsupported(level=stage_of(name), plan=str(FIXDIR / name)),
            note="生产路径 allow_devices=True"))

    # ---- B. 计划侧合成：换 dict、不换关卡，走同一套生产路径 ----
    for label, raw in plan_variants():
        exp = G.expect(("unsup_b", label, blob_id(raw)),
                       lambda raw=raw: py_unsup_plan(raw))
        p = tmp / ("plan_%d.json" % len(out))
        p.write_text(json.dumps(raw, ensure_ascii=False, indent=1), encoding="utf-8")
        out.append(Reading(label, exp,
                           go_unsupported(level=str(raw["stage"]), plan=str(p)),
                           note="生产路径（SpecCapture 钩子）"))

    # ---- C. 敌人侧合成：期望值由 `from_stage` ＋ 权威函数给 ----
    for label, blob in level_variants():
        p = tmp / ("level_%d.json" % len(out))
        p.write_text(json.dumps(blob, ensure_ascii=False, indent=1), encoding="utf-8")
        exp = G.expect(("unsup_c", label, blob_id(blob)),
                       lambda p=p: py_unsup_level(p))
        out.append(Reading(label, exp, go_unsupported(path=str(p)),
                           note="合成关卡（from_stage）"))
    return out


# ---------------------------------------------------------------- 比较（纯函数）

def compare(readings: list[Reading]) -> tuple[list[str], dict[str, int]]:
    """返回 `(问题清单, 每条已搬线被行使的次数)`。"""
    problems: list[str] = []
    fired = {ln: 0 for ln, _ in LINES}
    for r in readings:
        lines = [line_of(x) for x in r.expected]
        unknown = [x for x, l in zip(r.expected, lines) if l is None]
        if unknown:
            problems.append("%s：有理由切不出线（尺子漏了）：%s" % (r.name, unknown))
        #: `BOTH_SIDE_ZERO` 的线若真报出来了 ⇒ Go 没搬它 ⇒ 真缺口。
        for x, l in zip(r.expected, lines):
            if l in BOTH_SIDE_ZERO:
                problems.append("%s：`%s` 本来两侧都不报，现在报了：%s（Go 没搬这条线）"
                                % (r.name, l, x))
        go = r.go or {}
        exp_ported = [x for x, l in zip(r.expected, lines) if l in PORTED]
        if go.get("reasons") != exp_ported:
            problems.append("%s：reasons 不一致\n      Go   =%s\n      期望 =%s"
                            % (r.name, json.dumps(go.get("reasons"), ensure_ascii=False),
                               json.dumps(exp_ported, ensure_ascii=False)))
        #: Go 自报的 `covered` 是**第二来源**：它必须与期望逐线计数相同。
        want_cov: dict[str, int] = {}
        for l in lines:
            if l in PORTED:
                want_cov[l] = want_cov.get(l, 0) + 1
                fired[l] += 1
        if go.get("covered") != want_cov:
            problems.append("%s：covered 对不上（Go 自报 %s，期望 %s）"
                            % (r.name, json.dumps(go.get("covered"), ensure_ascii=False),
                               json.dumps(want_cov, ensure_ascii=False)))
        #: `unported` 是常量清单：两侧任一处改动都要在这里露出来。
        if sorted(go.get("unported") or []) != sorted(UNPORTED):
            problems.append("%s：unported 与判据的清单不一致\n      Go   =%s\n      判据 =%s"
                            % (r.name, json.dumps(go.get("unported"), ensure_ascii=False),
                               json.dumps(sorted(UNPORTED), ensure_ascii=False)))
        sc = go.get("scanned") or {}
        if sc.get("spawn_skipped"):
            problems.append("%s：Go 有 %d 个出怪项取不到敌人（被静默跳过）"
                            % (r.name, sc["spawn_skipped"]))
        #: 「查询跑成功了没有」：这几条线的分母必须真的非 0，否则那个 0 不是读数。
        if "关卡：" in r.name or r.name.startswith("真夹具"):
            if not sc.get("spawn"):
                problems.append("%s：Go 扫到的出怪项是 0 —— 那个「不报」是空扫描，不是读数"
                                % r.name)
    return problems, fired


def coverage_report(fired: dict[str, int]) -> list[str]:
    """覆盖率纪律：行使 0 次的已搬线必须**登记**，登记过的必须**真是 0**。"""
    problems = []
    for ln in PORTED:
        n = fired.get(ln, 0)
        if n == 0 and ln not in STRUCTURAL_ZERO:
            problems.append(
                "已搬线 %s 一次都没被行使（分母 0 ⇒ 这条覆盖是零信息量的绿）。"
                "要么补合成夹具走到它，要么写进 STRUCTURAL_ZERO 并给证据。" % ln)
        if n > 0 and ln in STRUCTURAL_ZERO:
            problems.append("STRUCTURAL_ZERO 登记过期：%s 登记为「点不着」，实测行使 %d 次"
                            % (ln, n))
    for ln in BOTH_SIDE_ZERO:
        if fired.get(ln, 0):
            problems.append("BOTH_SIDE_ZERO 登记过期：%s 登记为「两侧都不报」，实测 %d 次"
                            % (ln, fired[ln]))
    return problems


def structural_guards() -> list[str]:
    """`STRUCTURAL_ZERO` 的**重算守卫**：登记理由必须能被重算，过期即红。"""
    problems = []
    verify_src = (ROOT / "ak_tactic" / "verify.py").read_text(encoding="utf-8")
    if "plan_device(" in verify_src:
        problems.append("STRUCTURAL_ZERO.device_deploy 过期：`verify.py` 里出现了 plan_device(")
    if "plan_summon(" in verify_src:
        problems.append("STRUCTURAL_ZERO.summon_deploy 过期：`verify.py` 里出现了 plan_summon(")
    plan_src = (ROOT / "ak_tactic" / "plan.py").read_text(encoding="utf-8")
    for key in ("device_deployments", "summon_deployments"):
        if key in plan_src:
            problems.append("STRUCTURAL_ZERO 过期：`plan.py` 里出现了 %s 通道" % key)
    inputs_src = (ROOT / "ak_tactic" / "frontend" / "inputs.py").read_text(encoding="utf-8")
    if "snow_fields=[]," not in inputs_src:
        problems.append("STRUCTURAL_ZERO.snow_fields 过期：`from_stage` 不再把 snow_fields 置空")
    return problems


def witnesses(tmp: Path, G) -> list[str]:
    """每条 `UNPORTED` 都要有证人：证明它在 Python 侧**真会报**（或真被开关关着）。

    ⚠ 证不出来 ⇒ 判红。防「登记了一个其实不存在的线」——那种条目会让 `unported`
    变成一个永远为真的清单，而永远为真的判据是零信息量的。
    ★ 证人的**证据**（Python 报出来的那几条理由）走 `G.expect` 冻住；W2/W5 那两条
    只看源文件正文（不 import），照旧现算。
    """
    problems: list[str] = []

    # ---- W1 `devices`：allow_devices=False 时必须报 ----
    w1 = split_lines(G.expect(("unsup_w", "W1_devices"), py_w1))
    hit1 = [x for x in w1 if line_of(x) == "devices"]
    if not hit1:
        problems.append("W1（devices）证不出来：allow_devices=False 也没报，实测 %s" % w1)
    else:
        print("  W1 devices       证人成立：%s" % hit1[0])

    # ---- W2 `skill_name`：计划的 skill 写成对象时报 ----
    w2 = split_lines(G.expect(("unsup_w", "W2_skill_name"), py_w2))
    if not any(line_of(x) == "skill_name" for x in w2):
        problems.append("W2（skill_name）证不出来，实测 %s" % w2)
    else:
        print("  W2 skill_name    证人成立：%s" % w2)
    #: ⚠ 顺带钉住 Go 为什么搬不了它：Go 的计划读取器**故意**拒收对象形态
    #: （`tools/check_plan_go.py` 把这条登记为「Go 拒 ∧ 原版收」的分歧）。
    plan_go = (ROOT / "rios-sim" / "plan.go").read_text(encoding="utf-8")
    if "skill 是对象" not in plan_go:
        problems.append("W2：`rios-sim/plan.go` 不再具名拒收对象 skill —— "
                        "那条 unported 登记的依据变了：要么把它搬进 Go，要么改登记")

    # ---- W3 `device_deploy` ＋ `death_token`：给排程塞一条装置部署时报 ----
    lv = tmp / "w3_level.json"
    lv.write_text(json.dumps(synth_level(token_at=3.0), ensure_ascii=False),
                  encoding="utf-8")
    w3 = split_lines(G.expect(("unsup_w", "W3_devices"),
                              lambda: py_w3(lv)))
    got3 = {line_of(x) for x in w3}
    for need in ("device_deploy", "death_token"):
        if need not in got3:
            problems.append("W3（%s）证不出来，实测 %s" % (need, w3))
        else:
            print("  W3 %-14s 证人成立" % need)

    # ---- W4 `snow_talent`：开关关着 ⇒ 闸门不报，但必须证出「本来会报」 ----
    e4 = G.expect(("unsup_w", "W4_snow_talent"), py_w4)
    if not e4["allow_snow"]:
        problems.append("W4：`spec.ALLOW_SNOW` 不是 True（现读 %r）—— 积雪线已启用，"
                        "Go 侧得能算 snow_spec 才算搬完" % e4["allow_snow"])
    elif e4["n_fields"] <= 0:
        problems.append("W4（snow_talent）证不出来：hsex8_max 的 snow_spec 是空的"
                        "（抄不到：%s）——那条登记的依据没了" % e4["why"])
    else:
        print("  W4 snow_talent   证人成立：snow_spec 报 %d 片（ALLOW_SNOW=True 故闸门不报）"
              % e4["n_fields"])

    # ---- W5 `total_attack` / `operator_side`：源码守卫（没有可跑的证人）----
    src = (ROOT / "ak_tactic" / "simgo" / "spec.py").read_text(encoding="utf-8")
    if "全场总攻击装置" not in src:
        problems.append("W5（total_attack）证不出来：`spec.py` 里找不到那条文案")
    else:
        print("  W5 total_attack  证人成立（源码里那条文案还在；本次取证范围内报不出）")
    body = src.split("def unsupported_reasons", 1)[1].split("\ndef ", 1)[0]
    miss = [a for a in OPERATOR_ATTRS if a not in body]
    if miss:
        problems.append("W5（operator_side）登记过期：`unsupported_reasons` 里少了这些属性 %s"
                        % miss)
    else:
        print("  W5 operator_side 证人成立（%d 个属性字面量都还在那个函数里）"
              % len(OPERATOR_ATTRS))
    return problems


def divergences(tmp: Path, G) -> list[str]:
    """**已登记的分歧**：Go 在这里**故意**不跟原版走，且必须是「Go 大声失败」那一侧。

    照 `tools/check_plan_go.py` 的 `go-refuse-only` 那一类办：分歧要具名登记、
    要两侧同时断言，不能让它悄悄变成「Go 少算一层却照样给判决」。

    实测的口子：出怪表引用了一个**敌人库里没有、也不是关卡本地定义**的 key 时，
    原版 `mech._spawns_of` 的 `except: continue` **静默跳过**那一项——那只敌人
    一条理由都不贡献，而规格里照样有它。Go 侧选择**当场失败**。
    """
    problems: list[str] = []
    blob = synth_level(awake_at=3.0)
    blob["enemyDbRefs"] = blob["enemyDbRefs"] + [
        {"useDb": True, "id": "enemy_0000_nope", "level": 1, "overwrittenData": None}]
    blob["waves"][0]["fragments"][0]["actions"].append(
        {"actionType": "SPAWN", "key": "enemy_0000_nope", "count": 1,
         "preDelay": 7.0, "interval": 1.0, "routeIndex": 0,
         "blockFragment": False, "hiddenGroup": None})
    p = tmp / "div_nope.json"
    p.write_text(json.dumps(blob, ensure_ascii=False), encoding="utf-8")

    #: 原版那一侧：**静默跳过** ⇒ 只剩觉醒那一条，绝不报「取不到」。
    #: ★ 它也是期望值（Python 才产得出来）⇒ 走通道冻结。
    py_side = split_lines(G.expect(("unsup_d", "nope", blob_id(blob)),
                                   lambda: py_unsup_level(p)))
    if [x for x in py_side if line_of(x) == "awake"] == []:
        problems.append("分歧控制组：原版那一侧没报觉醒，夹具不对（%s）" % py_side)
    if any("取不到" in x for x in py_side):
        problems.append("分歧控制组：原版竟然报了「取不到」—— 那一支的写法变了")
    #: Go 那一侧：必须 ok=false，且错误里点到那个 key。
    ok, resp = go_unsupported_raw({"id": 1, "cmd": "unsupported", "path": str(p),
                                   "spec": {"allow_devices": True}})
    if ok:
        problems.append("分歧控制组：Go 对取不到的出怪项**没有失败**（跟着原版沉默了）"
                        " —— 那条闸门对这只敌人会永远沉默")
    elif "enemy_0000_nope" not in str(resp.get("error", "")):
        problems.append("分歧控制组：Go 失败了但错误里没点到那个 key：%r"
                        % resp.get("error"))
    else:
        print("  D1 取不到的出怪项  分歧成立：原版静默跳过（%d 条理由）、Go 具名失败"
              % len(py_side))
    return problems


# ---------------------------------------------------------------- 反向守卫

MUTATIONS = ("丢一条期望理由", "期望理由顺序对调", "篡改 Go 自报的 covered",
             "清单漂移：Go 的 unported 少一条")


def mutate(readings: list[Reading], which: str) -> list[Reading]:
    out = [Reading(r.name, list(r.expected), copy.deepcopy(r.go), r.note)
           for r in readings]
    if which == "丢一条期望理由":
        for r in out:
            if r.expected:
                r.expected.pop(0)
                return out
    elif which == "期望理由顺序对调":
        for r in out:
            if len(r.expected) >= 2:
                r.expected = list(reversed(r.expected))
                return out
    elif which == "篡改 Go 自报的 covered":
        for r in out:
            if r.go and r.go.get("covered"):
                k = sorted(r.go["covered"])[0]
                r.go["covered"][k] += 1
                return out
    elif which == "清单漂移：Go 的 unported 少一条":
        for r in out:
            if r.go and r.go.get("unported"):
                r.go["unported"] = list(r.go["unported"])[:-1]
                return out
    return out


def main() -> int:
    G = GB.bind("闸门", __file__)

    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：`simgo/spec.py::unsupported_reasons`"
          "（经 `SpecCapture` 钩子抄的生产规格 ＋ `SpecInputs.from_stage`）")
    ruler = ruler_selftest()
    for m in ruler:
        print("  ✗ %s" % m)
    if ruler:
        print("★ 尺子自检没过 —— 下面的读数一律不作数")
        return 1
    print("尺子自检：%d 条已知理由切分正确、%d 条负对照不被误认、%d 条线都有正例"
          % (len(RULER_KNOWN), len(RULER_UNKNOWN), len(LINES)))
    print()

    tmp = Path(tempfile.mkdtemp(prefix="unsup_"))
    print("一 · 证人（每条未搬线都要证出「它在 Python 侧真会报」）")
    wbad = witnesses(tmp, G)
    for m in wbad:
        print("  ✗ %s" % m)
    print()

    #: ★ 夹具批是**活的**（别的会话会往里加夹具）⇒ 键带输入身份 ＋ 先对账。
    rsha = GB.file_sha16(ROSTER_FIX)
    live_a = [[n, sha, rsha] for n, sha in scan_plan_fixtures()]
    cov = G.coverage("unsup_a", live_a)
    rows_a = live_a
    if G.mode == GB.CHECK and not cov.ok:
        #: 只比两边都有的。**未覆盖的不猜**。
        covered = {tuple(x) for x in cov.covered}
        rows_a = [x for x in rows_a if tuple(x) in covered]

    readings = build_readings(tmp, G, rows_a)
    print("二 · 逐例对拍（%d 例；合成夹具落点 %s）" % (len(readings), tmp))
    problems, fired = compare(readings)
    for r in readings:
        got = (r.go or {}).get("reasons") or []
        want = [x for x in r.expected if line_of(x) in PORTED]
        print("  %s %-48s 期望 %d 条 / Go %d 条"
              % ("✓" if got == want else "✗", r.name, len(want), len(got)))
    print()

    print("三 · 覆盖率（分母先数出来；行使 0 次的已搬线必须登记）")
    for ln in PORTED:
        n = fired.get(ln, 0)
        if ln in STRUCTURAL_ZERO:
            print("  登记 %-14s 行使 0 次（结构上点不着：%s）"
                  % (ln, STRUCTURAL_ZERO[ln][:38] + "…"))
        else:
            print("  %s %-14s 行使 %d 次" % ("✓" if n else "✗", ln, n))
    for ln in BOTH_SIDE_ZERO:
        print("  登记 %-14s 行使 %d 次（两侧都不报：%s）"
              % (ln, fired.get(ln, 0), BOTH_SIDE_ZERO[ln][:38] + "…"))
    cbad = coverage_report(fired)
    print()

    print("四 · 登记的守卫（理由会过期，所以每条登记都要能拿代码重算）")
    gbad = structural_guards()
    for m in gbad:
        print("  ✗ %s" % m)
    if not gbad:
        print("  ✓ STRUCTURAL_ZERO 的 4 条重算守卫全过")
    dbad = divergences(tmp, G)
    for m in dbad:
        print("  ✗ %s" % m)
    problems = problems + wbad + cbad + gbad + dbad

    if G.mode == GB.CHECK and not cov.ok:
        print()
        print(cov.report("unsup_a", len(live_a)))
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)

    if mutate_mode:
        print()
        print("五 · 反向守卫（每处人为改动都必须判红）")
        if problems:
            print("★ 基线本身就不干净 ⇒ 反向守卫无从成立"
                  "（拿一个已经红的东西证明不了红得起来）")
            return 1
        bad_guard = 0
        for which in MUTATIONS:
            mp, _f = compare(mutate(readings, which))
            ok = bool(mp)
            if not ok:
                bad_guard += 1
            print("  %s 注入「%s」→ %s"
                  % ("✓" if ok else "✗", which, "判红" if ok else "没红（守不住）"))
        if bad_guard:
            print("★ %d / %d 处注入没被判红" % (bad_guard, len(MUTATIONS)))
            return 1
        print("  反向守卫成立：%d / %d 处注入都判红" % (len(MUTATIONS), len(MUTATIONS)))
        return 0

    if problems:
        print()
        print("★ %d 处不一致：" % len(problems))
        for m in problems:
            print("  · %s" % m)
        print("结论：闸门对拍**未通过**（%d 处）" % len(problems))
        return 1
    total = sum(len([x for x in r.expected if line_of(x) in PORTED]) for r in readings)
    nonzero = sum(1 for r in readings
                  if any(line_of(x) in PORTED for x in r.expected))
    print()
    print("结论：%d 例逐条同序一致（其中 %d 例有理由、共 %d 条）；"
          "已搬线 %d 条（行使 %d 条 ＋ 登记 %d 条）、两侧都不报 %d 条、"
          "未搬线 %d 条各有证人"
          % (len(readings), nonzero, total, len(PORTED),
             sum(1 for ln in PORTED if fired.get(ln)), len(STRUCTURAL_ZERO),
             len(BOTH_SIDE_ZERO), len(UNPORTED)))
    if G.mode == GB.CHECK and not cov.ok:
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
