#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 自己造的**部分规格**骨架，以及它的键集账。

## 对的是什么

* 12 个已经能算出来的键的**值**：`stage_env`（静态 8 项）＋ `st.code` ＋
  `max_time` ＋ `_find_goals` / `_highland_cells`（两张格表）。
* **键集本身**：`build_spec` 返回的 19 个顶层键是 Python 与 Go 之间的契约。
  这里不手抄这 19 个——用 `ast` 从 `simgo/spec.py` 的 `build_spec` 返回字面量里
  **抽出来**，再断言
  `Go 已产出的 ∪ Go 自报缺的 == 源文件里的键集` 且两者**不相交**。

  为什么这条比逐字段对拍还重要：分开造完再拼，最容易出的错是**键名对不上而
  两边都不报**。上游哪天加了一个键，这条会先红，而不是等某次对拍发现少送字段。

## 一张要盯着的表

`gated_keys` 里的键 Go **已经产出、但原版那道门还没接**：原版里
`goal_cells` 只有积雪机制在场才送、`highland_cells` 只有某个干员带
`highland_splash_scale` 才送。空的两张格表与「这一关没有」在原版里长得一样，
所以这个差异必须写在明面上，不能靠「反正值是空的」糊过去。

## 期望值从哪来（**两种模式**）

* 默认（`RIOS_GOLDEN` 未设）：现场调 Python（`stage_env` / `_find_goals` /
  `build_spec` 的三条路径），**现状不变**；
* **冻结**（`RIOS_GOLDEN=check`）：只读 `fixtures/golden/部分规格.json`，
  **不 import `ak_tactic`**。

★ 这一套有**三个来源不同**的部件，各自的身份不一样：

  ① **逐关 12 个值键**（缓存可达的关卡）：键 `("specgo", 关卡 id, 缓存文件
     内容 sha16)`，先 `G.coverage("specgo", …)` 对账；
  ② **生产规格**（`real_specs()`，夹具 × 名册）：键
     `("specgo_real", 夹具名, 夹具字节 sha16, 名册字节 sha16)`——它同时冻
     `skill_uses` 与 `deploys` 两串；
  ③ **合成 `skill_uses` 用例**（原版从夹具里挑「≥2 个部署」的前 6 例**成功**抄到
     规格的）：问题（`raw3` 与关卡号）走 `("query", "specgo_syn_cases")` 冻住
     —— **必须连 raw3 一起冻**，否则冻结档写不出喂给 Go 的那份文件。

★ **键集账**（`build_spec_keys()` 用 `ast` 从 `simgo/spec.py` 的返回字面量里抽）
**不进冻结**：它读的是**源文件正文**，不是 Python 运行期产物——抽出来冻住反而会
让「源加了键」这件事不再响。它在冻结档照跑（只是读文件，不用 import）。

用法:
    python tools\\check_specgo_go.py
    python tools\\check_specgo_go.py --mutate
    python tools\\freeze_baseline.py --record 部分规格
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import types
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
import freeze_baseline as GB                                   # noqa: E402

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
DEFAULT_MAX_TIME = 900.0

VALUE_KEYS = ("stage", "fps", "max_time", "life", "cost_init", "cost_max",
              "cost_time", "enemy_windup", "ranged_enemies", "speed_scale",
              "highland_cells", "goal_cells")

#: 两张格表在原版是**有条件的**（积雪机制／`highland_splash_scale`），Go 无条件
#: 产出 ⇒ 对**真规格**时只比其余 10 个键，两张格表另记一行。
REAL_KEYS = tuple(k for k in VALUE_KEYS if not k.endswith("cells"))

FIXDIR = ROOT / "fixtures"
ROSTER_FIX = FIXDIR / "roster_max_modelled.json"


class _Captured(Exception):
    """哨兵：规格抄到了就停，不必把那一局跑完。"""


def real_specs():
    """用**生产路径**产规格：`SpecCapture` 的钩子里抄完就抛，不跑判决。

    ⚠ `SpecCapture`（`tools/golden_go.py:94`）本身会把那一局交给 Go 跑完，
    对判据来说太慢；这里只借它的钩子点——`_run_other_engine` 正是
    「排好程、还没跑」那一刻，`build_spec` 就在那一行被调用。
    """
    sys.path.insert(0, str(ROOT / "tools"))
    import golden_go as G
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.simgo.spec import build_spec

    class CaptureOnly(G.SpecCapture):
        def _run_other_engine(self, **kw):
            try:
                self.spec = build_spec(SpecInputs.from_sim(kw["sim"]),
                                       allow_devices=True)
            except Exception as e:                          # noqa: BLE001
                self.spec_error = "%s: %s" % (type(e).__name__, e)
            raise _Captured()

    roster = Roster.from_json(ROSTER_FIX)
    out = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                   # noqa: BLE001
            continue
        if not isinstance(raw, dict) or ("deploys" not in raw
                                         and "deploy" not in raw):
            continue
        v = CaptureOnly()
        try:
            v.run(Plan.from_dict(raw), roster=roster)
        except _Captured:
            pass
        except Exception as e:                              # noqa: BLE001
            out.append((f.name, None, "%s: %s" % (type(e).__name__, e), None))
            continue
        #: ⚠ 第三个返回值必须是**计划里的关卡 id**，不是规格里的 `stage`：
        #: 规格的 `stage` 是**显示代号**（`HS-EX-8`），而 `#f#` 那道四星档只住在
        #: id（`act31side_ex08#f#`）上。拿代号去查关卡会落到普通档，
        #: 症状是 `life` 得 3 而生产规格是 1——**判据自己把难度弄丢了**。
        out.append((f.name, v.spec, v.spec_error, str(raw.get("stage") or "")))
    return out


def build_spec_keys() -> list[str]:
    """从源文件里抽 `build_spec` 返回字面量的键——**不手抄**。"""
    tree = ast.parse((ROOT / "ak_tactic" / "simgo" / "spec.py").read_text(
        encoding="utf-8"))
    fn = next(n for n in tree.body
              if isinstance(n, ast.FunctionDef) and n.name == "build_spec")
    dicts = [n.value for n in ast.walk(fn)
             if isinstance(n, ast.Return) and isinstance(n.value, ast.Dict)]
    if not dicts:
        raise SystemExit("spec.py 的 build_spec 里找不到返回字面量")
    best = max(dicts, key=lambda d: len(d.keys))
    return [k.value for k in best.keys if isinstance(k, ast.Constant)]


def _capture(raw: dict):
    """把一份打法 dict 走生产路径抄成规格（合成用例用）。"""
    import golden_go as G
    from ak_tactic.frontend.inputs import SpecInputs
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.simgo.spec import build_spec

    class Only(G.SpecCapture):
        def _run_other_engine(self, **kw):
            try:
                self.spec = build_spec(SpecInputs.from_sim(kw["sim"]),
                                       allow_devices=True)
            except Exception as e:                          # noqa: BLE001
                self.spec_error = "%s: %s" % (type(e).__name__, e)
            raise _Captured()

    v = Only()
    try:
        v.run(Plan.from_dict(raw), roster=Roster.from_json(ROSTER_FIX))
    except _Captured:
        pass
    except Exception as e:                                  # noqa: BLE001
        return None, "%s: %s" % (type(e).__name__, e)
    return v.spec, v.spec_error


# --------------------------------------------------- 期望值（可冻的三个部件）
_BATCH_REAL = None
_BATCH_SYN = None


def py_specgo_level(lv: str) -> dict:
    """逐关的 12 个值键。★ import 住函数体里：冻结档下本函数不会被调到。"""
    from ak_tactic.frontend.stage_env import stage_env
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import _find_goals, _highland_cells
    try:
        st = load_stage(lv)
    except Exception as exc:                                   # noqa: BLE001
        return {"loaded": False, "why": "%s: %s" % (type(exc).__name__, exc),
                "env": {}}
    inp = types.SimpleNamespace(stage=st)
    #: 期望值同样走原版那句兜底（`spec.py:1209-1212`），不是写死 NORMAL
    #: ——写死会让四星档关卡两边一起错。
    diff = str(getattr(st, "difficulty", "") or "NORMAL")
    want = dict(stage_env(st, environment_difficulty=diff))
    want["stage"] = str(getattr(st, "code", "") or "")
    want["max_time"] = DEFAULT_MAX_TIME
    want["goal_cells"] = [[int(x), int(y)] for x, y in sorted(_find_goals(inp))]
    want["highland_cells"] = [[int(x), int(y)] for x, y in _highland_cells(inp)]
    #: ⚠ 这一格叫 `env` 不是 `want`：控制组 P1 会把值里的**第一个键**改坏，而
    #: 改到 `loaded` 上会让整关被跳过（等于没进判决路径 ⇒ 报出一条假的「没红」）。
    #: `env` 排在 `loaded` 前面，改坏它就落在被比的 12 个值上。
    return {"loaded": True, "why": "", "env": want}


def scan_plan_fixtures() -> list[list]:
    """夹具批次的**输入身份**：文件名 ＋ 文件字节 sha16（数据侧，不 import）。"""
    out: list[list] = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append([f.name, GB.file_sha16(f)])
    return out


def _proj_su(spec) -> list:
    """`skill_uses` 投影：`[{"time", "cell"}]`（判据侧再拼成 `[time]+cell`）。"""
    return [{"time": w.get("time"),
             "cell": [int(v) for v in (w.get("cell") or [])]}
            for w in ((spec or {}).get("skill_uses") or [])]


def _proj_dep(spec) -> list:
    """`deploys` 投影：逐条五个字段（判据侧按字段逐个比）。"""
    return [{"time": w.get("time"), "index": w.get("index"),
             "char_id": w.get("char_id"), "cost": w.get("cost"),
             "auto_skill": w.get("auto_skill")}
            for w in ((spec or {}).get("deploys") or [])]


def py_specgo_real() -> list[list]:
    """生产规格那批（**离冻档专用**）：`[夹具名, 夹具 sha16, 名册 sha16, 期望值]`。

    ★ `ak_tactic` 的 import 全在 `real_specs()` 里：冻结档下本函数不会被调到。
    """
    rsha = GB.file_sha16(ROSTER_FIX)
    out: list[list] = []
    for name, spec, err, lv_id in real_specs():
        ident = GB.file_sha16(FIXDIR / name)
        if spec is None:
            out.append([name, ident, rsha,
                        {"spec_ok": False, "why": err or "", "lv_id": lv_id}])
            continue
        out.append([name, ident, rsha, {
            "spec_ok": True, "why": "", "lv_id": lv_id,
            "level": lv_id or str(spec.get("stage") or ""),
            "real": {k: spec[k] for k in REAL_KEYS if k in spec},
            "skill_uses": _proj_su(spec), "deploys": _proj_dep(spec)}])
    return out


def _compute_syn() -> list[dict]:
    """合成用例的扫描（与原版同序、同口径）。

    ⚠ 一处**口径差**要写明：原版按「抄到规格 **且** 比对一致（`okk`）」计数到 6，
    这里按「抄到规格」计数——两种计数在**绿局**下必然相等（绿 ⇒ 无反例 ⇒
    `okk` 恒真）；红局下扫描面可能不同（而红局本来就是红的）。
    ★ `_capture` 用 Python：冻结档下本函数不会被调到。
    """
    out: list[dict] = []
    cases = 0
    for f in sorted(FIXDIR.glob("*.json")):
        if cases >= 6:
            break
        try:
            raw = json.loads(f.read_text(encoding="utf-8-sig"))
        except Exception:                                      # noqa: BLE001
            continue
        if not isinstance(raw, dict) or "deploys" not in raw:
            continue
        if len(raw.get("deploys") or []) < 2:
            continue
        ops = [d.get("operator") or d.get("name") for d in raw["deploys"]]
        raw3 = dict(raw, skills=[
            {"operator": ops[0], "time": 5.0, "slot": 1},
            {"operator": ops[1], "time": 2.0, "slot": 2},
            {"operator": ops[0], "time": 1.0, "slot": 3},
        ])
        spec3, err3 = _capture(raw3)
        out.append({
            "name": f.name, "raw3": raw3,
            "level3": str(raw3.get("stage") or ""),
            "sha": GB.sh16(json.dumps(raw3, sort_keys=True, ensure_ascii=False,
                                      separators=(",", ":")).encode("utf-8")),
            "spec_ok": spec3 is not None, "why": err3 or "",
            "skill_uses": _proj_su(spec3)})
        if spec3 is not None:
            cases += 1
    return out


def _real_batch() -> list[list]:
    global _BATCH_REAL
    if _BATCH_REAL is None:
        _BATCH_REAL = py_specgo_real()
    return _BATCH_REAL


def _real_expect(name: str) -> dict:
    for b in _real_batch():
        if b[0] == name:
            return b[3]
    raise SystemExit("★ 生产规格那一批里没有这份夹具：%s" % name)


def _syn_batch() -> list[dict]:
    global _BATCH_SYN
    if _BATCH_SYN is None:
        _BATCH_SYN = _compute_syn()
    return _BATCH_SYN


def _syn_expect(name: str) -> dict:
    for b in _syn_batch():
        if b["name"] == name:
            return {"spec_ok": b["spec_ok"], "why": b["why"],
                    "skill_uses": b["skill_uses"]}
    raise SystemExit("★ 合成用例那一批里没有这份夹具：%s" % name)


def go_specgo(level: str, difficulty: str = "", plan: str = "",
              roster: str = "") -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    #: 难度传空 = 让 Go 走它与原版同一句兜底（关卡自己的档 → NORMAL）。
    req = {"id": 1, "cmd": "specgo", "level": level}
    body = {}
    if difficulty:
        body["difficulty"] = difficulty
    if plan:
        body["plan"] = plan
        body["roster"] = roster
    if body:
        req["spec"] = body
    p = subprocess.run([GO_BIN], input=(json.dumps(req) + "\n").encode("utf-8"),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env)
    if p.returncode != 0:
        raise SystemExit("Go rc=%d：%s" % (p.returncode,
                                           p.stderr.decode("utf-8", "replace")[:400]))
    line = p.stdout.decode("utf-8", "replace").strip().splitlines()
    if not line:
        raise SystemExit("Go 没有回任何东西")
    resp = json.loads(line[0])
    if not resp.get("ok"):
        return False, resp.get("error") or ""
    return True, resp["spec_go"]


def main() -> int:
    G = GB.bind("部分规格", __file__)

    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []

    all_keys = build_spec_keys()
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：simgo/spec.py 的 build_spec 返回字面量（ast 抽出 %d 个键）"
          % len(all_keys))
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    seen: dict[str, int] = {}

    #: ---- ① 逐关 12 个值键（对象集是活的：清单按缓存现算）----
    batch = GB.level_inputs(DATA, levels)
    if G.mode == GB.RECORD:
        G.expect(("query", "level_batch"), lambda: batch)
    cov_lv = G.coverage("specgo", [[r["level"], r["sha16"]] for r in batch])
    to_cmp = batch
    if G.mode == GB.CHECK and not cov_lv.ok:
        covered_lv = {tuple(x) for x in cov_lv.covered}
        to_cmp = [r for r in batch if (r["level"], r["sha16"]) in covered_lv]
    for rec in to_cmp:
        lv = rec["level"]
        #: ★ 键自带输入身份：缓存内容变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        E = G.expect(("specgo", lv, rec["sha16"]),
                     lambda lv=lv: py_specgo_level(lv))
        if not E["loaded"]:
            continue
        ok, got = go_specgo(lv)
        if not ok:
            bad += 1
            print("✗ %s —— Go 拒了：%s" % (lv, got))
            continue
        compared += 1
        want = E["env"]
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got["life"] = got["life"] + 1
        for k in VALUE_KEYS:
            a, b = got[k], want[k]
            #: ⚠ 比较阶梯要**按类型**写全：漏掉字符串那一路时，
            #: `float("HS-1")` 会抛 ValueError，看起来像实现崩了。
            if k == "stage":
                same = (a == b)
            elif k in ("fps", "life"):
                same = int(a) == int(b)
            elif k.endswith("cells"):
                same = ([list(map(int, p)) for p in a]
                        == [list(map(int, p)) for p in b])
            elif isinstance(b, bool):
                same = bool(a) == b
            else:
                same = abs(float(a) - float(b)) < 1e-9
            if same:
                seen["值 " + k] = seen.get("值 " + k, 0) + 1
            else:
                bad += 1
                print("✗ %s %s：Go=%r Python=%r" % (lv, k, a, b))
        #: 键集账：已产出 ∪ 自报缺的 == 源文件里的全集，且不相交。
        produced = {k for k in got if k not in ("missing_keys", "gated_keys",
                                                "difficulty")}
        missing = set(got["missing_keys"])
        if produced & missing:
            bad += 1
            print("✗ 键集：已产出与自报缺的交集非空：%s" % sorted(produced & missing))
        if produced | missing != set(all_keys):
            bad += 1
            print("✗ 键集：并集 != 源文件里的 %d 个键（多 %s／少 %s）"
                  % (len(all_keys), sorted((produced | missing) - set(all_keys)),
                     sorted(set(all_keys) - (produced | missing))))
        want_missing = sorted(set(all_keys) - produced)
        if sorted(missing) != want_missing:
            bad += 1
            print("✗ 自报缺项不对：Go=%s 应为 %s" % (sorted(missing), want_missing))
        if got["gated_keys"] != ["goal_cells", "highland_cells"]:
            bad += 1
            print("✗ gated_keys 变了：%r" % got["gated_keys"])

    #: ---- 第二部分：拿**生产规格**当期望值（夹具全量）----
    real_bad_before = bad
    real_cmp = 0
    real_err = 0
    rsha = GB.file_sha16(ROSTER_FIX)
    real_live = [[n, sha, rsha] for n, sha in scan_plan_fixtures()]
    cov_real = G.coverage("specgo_real", real_live)
    real_rows = real_live
    if G.mode == GB.CHECK and not cov_real.ok:
        covered_real = {tuple(x) for x in cov_real.covered}
        real_rows = [x for x in real_live if tuple(x) in covered_real]
    for name, ident, _rs in real_rows:
        #: ★ 键自带输入身份：夹具或名册变了 ⇒ 键配不上 ⇒ 由对账如实报出。
        E = G.expect(("specgo_real", name, ident, rsha),
                     lambda name=name: _real_expect(name))
        if not E["spec_ok"]:
            real_err += 1
            print("· 夹具 %s —— 生产路径没抄到规格：%s" % (name, E["why"]))
            continue
        level = E["level"]
        ok, got = go_specgo(level)
        if not ok:
            bad += 1
            print("✗ 夹具 %s（关卡 %s）—— Go 拒了：%s" % (name, level, got))
            continue
        real_cmp += 1
        for k in REAL_KEYS:
            if k not in E["real"]:
                continue
            a, b = got[k], E["real"][k]
            if k == "stage":
                same = (a == b)
            elif k in ("fps", "life"):
                same = int(a) == int(b)
            elif isinstance(b, bool):
                same = bool(a) == b
            else:
                same = abs(float(a) - float(b)) < 1e-9
            if same:
                seen["真规格 " + k] = seen.get("真规格 " + k, 0) + 1
            else:
                bad += 1
                print("✗ 夹具 %s %s：Go=%r 生产规格=%r" % (name, k, a, b))
        #: ---- `deploys` 那一串：**装配后**的整条链 ----
        plan_path = str(ROOT / "fixtures" / name)
        ok2, got2 = go_specgo(level, "", plan_path, str(ROSTER_FIX))
        if not ok2:
            bad += 1
            print("✗ 夹具 %s 带计划调用 —— Go 拒了：%s" % (name, got2))
            continue
        if "deploys" in (got2.get("missing_keys") or []):
            bad += 1
            print("✗ 夹具 %s —— 传了计划却仍把 deploys 报成缺项" % name)
        else:
            seen["传计划后 deploys 不再缺"] = \
                seen.get("传计划后 deploys 不再缺", 0) + 1
        if "skill_uses" in (got2.get("missing_keys") or []):
            bad += 1
            print("✗ 夹具 %s —— 传了计划却仍把 skill_uses 报成缺项" % name)
        #: ---- `skill_uses`：按**计划顺序**，`cell` 取该干员的落点 ----
        wsu = E["skill_uses"]
        gsu = got2.get("skill_uses") or []
        if len(gsu) != len(wsu):
            bad += 1
            print("✗ 夹具 %s skill_uses 条数：Go=%d 生产规格=%d"
                  % (name, len(gsu), len(wsu)))
        else:
            for k, (g, w) in enumerate(zip(gsu, wsu)):
                gm = [float(g.get("time"))] + [int(v) for v in (g.get("cell") or [])]
                wm = [float(w.get("time"))] + [int(v) for v in (w.get("cell") or [])]
                if gm == wm:
                    seen["真规格 skill_uses 逐条"] = \
                        seen.get("真规格 skill_uses 逐条", 0) + 1
                else:
                    bad += 1
                    print("✗ 夹具 %s skill_uses[%d]：Go=%r 生产规格=%r"
                          % (name, k, gm, wm))
        wd = E["deploys"]
        gd = got2.get("deploys") or []
        if len(gd) != len(wd):
            bad += 1
            print("✗ 夹具 %s deploys 条数：Go=%d 生产规格=%d"
                  % (name, len(gd), len(wd)))
            continue
        for k, (g, w) in enumerate(zip(gd, wd)):
            for f in ("time", "index", "char_id", "cost", "auto_skill"):
                a, b = g.get(f), w.get(f)
                ok_f = (a == b if f in ("index", "char_id", "auto_skill")
                        else abs(float(a) - float(b)) < 1e-9)
                if ok_f:
                    seen["真规格 deploys." + f] = \
                        seen.get("真规格 deploys." + f, 0) + 1
                else:
                    bad += 1
                    print("✗ 夹具 %s deploys[%d].%s：Go=%r 生产规格=%r"
                          % (name, k, f, a, b))
    seen["夹具 × 真规格"] = real_cmp

    #: ---- 第三部分：`skill_uses` ----
    #: ⚠ 24 份夹具里**一条开技能都没有**（实测 0 份），所以第二部分那条
    #: 只在比「两边都是空」。这一部分**合成**带开技能的计划，而且故意
    #: **乱序**（计划里的先后 ≠ 时刻先后）——那正是要区分的那一点：
    #: 原版按计划顺序产出，按时刻重排就会分叉。
    import tempfile
    skill_cases = 0
    with tempfile.TemporaryDirectory() as td:
        #: ★ 这一批的**问题**（含 raw3 与关卡号）从通道来：冻结档也要写得出
        #: 喂给 Go 的那份文件，所以 raw3 必须一起冻。
        cases = G.expect(("query", "specgo_syn_cases"),
                         lambda: [[b["name"], b["raw3"], b["level3"], b["sha"]]
                                  for b in _syn_batch()])
        for name, raw3, level3, sha in cases:
            p3 = Path(td) / name
            p3.write_text(json.dumps(raw3, ensure_ascii=False), encoding="utf-8")
            ok3, got3 = go_specgo(level3, "", str(p3), str(ROSTER_FIX))
            if not ok3:
                bad += 1
                print("✗ 合成 %s —— Go 拒了：%s" % (name, got3))
                continue
            E = G.expect(("specgo_syn", name, sha),
                         lambda name=name: _syn_expect(name))
            if not E["spec_ok"]:
                print("· 合成 %s 没抄到规格：%s" % (name, E["why"]))
                continue
            gsu, wsu = got3.get("skill_uses") or [], E["skill_uses"]
            if len(gsu) != len(wsu):
                bad += 1
                print("✗ 合成 %s skill_uses 条数：Go=%d 生产规格=%d"
                      % (name, len(gsu), len(wsu)))
                continue
            okk = True
            for k, (g, w) in enumerate(zip(gsu, wsu)):
                gm = [float(g["time"])] + [int(v) for v in g["cell"]]
                wm = [float(w["time"])] + [int(v) for v in w["cell"]]
                if gm != wm:
                    okk = False
                    bad += 1
                    print("✗ 合成 %s skill_uses[%d]：Go=%r 生产规格=%r"
                          % (name, k, gm, wm))
            if okk:
                seen["合成 skill_uses 逐条"] = \
                    seen.get("合成 skill_uses 逐条", 0) + len(gsu)
                skill_cases += 1
    seen["合成 fixture 数"] = skill_cases

    if G.mode == GB.CHECK:
        for _tag, _cov, _n in (("specgo", cov_lv, len(batch)),
                               ("specgo_real", cov_real, len(real_live))):
            if not _cov.ok:
                print()
                print(_cov.report(_tag, _n))
    print()
    print("已比：部分规格骨架；%d 关（缓存可达）× %d 个值键 ＋ 键集账"
          % (compared, len(VALUE_KEYS)))
    print("      另：%d 份夹具 × **生产规格**的 %d 个非门控键"
          % (real_cmp, len(REAL_KEYS)))
    print("★ 行使计数：")
    for k, n in sorted(seen.items()):
        print("    %-20s %d" % (k, n))
    print("    键集账                 %d（每个值键都各查一次，共 %d 次断言）"
          % (1, len(VALUE_KEYS) + 3))
    print()
    _sum = GB.channel_summary()
    if _sum:
        print(_sum)
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    missingc = [k for k in VALUE_KEYS if seen.get("值 " + k, 0) == 0]
    if missingc:
        print("结论：没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(missingc))
        return 1
    print("结论：%d 关的 %d 个值键逐项一致，键集账 %d 个键对得上"
          % (compared, len(VALUE_KEYS), len(all_keys)))
    if bad:
        #: 比过的部分**真的不一致** ⇒ 判据红，优先于「基线该重录」。
        return 1
    if G.mode == GB.CHECK and not (cov_lv.ok and cov_real.ok):
        #: 比过的部分一致，但**对象集变了** ⇒ 读数不可用（rc=6），不是判据红。
        return GB.RC_CHANNEL
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
