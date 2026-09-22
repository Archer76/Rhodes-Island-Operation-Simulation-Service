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

用法:
    python tools\\check_specgo_go.py
    python tools\\check_specgo_go.py --mutate
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


def go_specgo(level: str, difficulty: str = "") -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    #: 难度传空 = 让 Go 走它与原版同一句兜底（关卡自己的档 → NORMAL）。
    req = {"id": 1, "cmd": "specgo", "level": level}
    if difficulty:
        req["spec"] = {"difficulty": difficulty}
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
    try:
        from check_go_all import cached_levels
        levels = cached_levels()
    except Exception:                                       # noqa: BLE001
        levels = []
    from ak_tactic.frontend.stage_env import stage_env
    from ak_tactic.gamedata.stage import load_stage
    from ak_tactic.simgo.spec import _find_goals, _highland_cells

    all_keys = build_spec_keys()
    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：simgo/spec.py 的 build_spec 返回字面量（ast 抽出 %d 个键）"
          % len(all_keys))
    print()

    mutate = "--mutate" in sys.argv
    bad = 0
    compared = 0
    seen: dict[str, int] = {}

    for lv in levels:
        try:
            st = load_stage(lv)
        except Exception:                                   # noqa: BLE001
            continue
        ok, got = go_specgo(lv)
        if not ok:
            bad += 1
            print("✗ %s —— Go 拒了：%s" % (lv, got))
            continue
        compared += 1
        inp = types.SimpleNamespace(stage=st)
        #: 期望值同样走原版那句兜底（`spec.py:1209-1212`），不是写死 NORMAL
        #: ——写死会让四星档关卡两边一起错。
        diff = str(getattr(st, "difficulty", "") or "NORMAL")
        want = dict(stage_env(st, environment_difficulty=diff))
        want["stage"] = str(getattr(st, "code", "") or "")
        want["max_time"] = DEFAULT_MAX_TIME
        want["goal_cells"] = [[x, y] for x, y in sorted(_find_goals(inp))]
        want["highland_cells"] = _highland_cells(inp)
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
    for name, spec, err, lv_id in real_specs():
        if spec is None:
            real_err += 1
            print("· 夹具 %s —— 生产路径没抄到规格：%s" % (name, err))
            continue
        level = lv_id or str(spec.get("stage") or "")
        ok, got = go_specgo(level)
        if not ok:
            bad += 1
            print("✗ 夹具 %s（关卡 %s）—— Go 拒了：%s" % (name, level, got))
            continue
        real_cmp += 1
        for k in REAL_KEYS:
            if k not in spec:
                continue
            a, b = got[k], spec[k]
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
    seen["夹具 × 真规格"] = real_cmp

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
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
