#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现对拍：Go 直读打法（计划）。

## 对的是什么

`ak_tactic/plan.py:249-354` 的 `Plan.from_dict` ＋ `:262-289` 的 `validate`。
期望值直接调它们，不自己重写口径。

## 覆盖面

**`fixtures/` 下的全部打法夹具逐份对拍**（不抽样：26 份 JSON 里认得出 24 份
带 `deploys`/`deploy` 的），另加一组合成用例逐条走各道口径。

## 原版里几处容易抄混的

* `elite` / `level` / `potential` / `trust` / `module_level` / `time` 走
  **`is None`**（`"elite": 0` 就是 0）；而 `skill` / `mastery` 走 **`or 0`**。
  同一个文件里两种兜底并存。
* `module` 是**原样收下**：空串就是空串，不是 None——与名册那边相反。
* `auto_skill` 缺省 **True**，可是取到值后要 `bool()` 它 ⇒ **显式 null 得 False**。
* 坐标走 `or` 链（`position` → `pos` → `location`），而 `[0, 0]` 取真、不会被跳过。
* **`Plan.load` 读的是 `encoding="utf-8"`，不吃 BOM**（名册那边才是 `utf-8-sig`）。
  两份权威在这一点上口径不同。

## 两条只判单向的用例（写明，不当对拍算）

* **`skill` 为对象**（丙方案那一支，要 `_skill_from_json` 查技能书）：本轮未接，
  Go 具名拒收。这里只断言「Go 拒」——原版那一侧要能解出技能 id 才算成立，
  而造那个用例要拖进技能书，本轮不断言。
* 同族的类型纪律（非字符串的 `operator` / `name` / `facing` / `module` / `stage`）：
  Go 一律拒收，原版则会原样收下。逐条要求「Go 拒 ∧ 原版收」同时成立。
  ⚠ `direction` **不属于**这一族：原版 `__post_init__` 有「朝向必须在
  `DIRECTIONS` 里」的校验，随便给个 `7` 或 `Sideways` 两边都拒。

用法:
    python tools\\check_plan_go.py
    python tools\\check_plan_go.py --mutate
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
DATA = ROOT / "data" / "gamedata"
FIXDIR = ROOT / "fixtures"

BOM = b"\xef\xbb\xbf"

#: 部署上逐字段比的那几项（`position` 单独比，因为是数组）。
DEPLOY_FIELDS = ("operator", "direction", "skill", "mastery", "elite", "level",
                 "potential", "trust", "module", "module_level", "time",
                 "auto_skill")


def j(text: str) -> bytes:
    return text.encode("utf-8")


CASES: list[tuple[str, bytes, str, tuple[str, ...]]] = [
    ("最小打法（全靠缺省）",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,2]}]}'),
     "parity", ("缺省方向", "auto_skill 缺省 True", "elite 等缺省为 None")),
    ("deploy 单数键与 name/pos/facing 退路",
     j('{"stage":"1-7","deploy":[{"name":"乙","pos":[3,4],"facing":"Left"}]}'),
     "parity", ("deploy 单数键", "name 退路", "pos 退路", "facing 退路")),
    ("location 退路（pos 为 null）",
     j('{"stage":"1-7","deploys":[{"operator":"甲","pos":null,"location":[5,6]}]}'),
     "parity", ("location 退路",)),
    ("坐标 [0,0] 仍取真",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[0,0]}]}'),
     "parity", ("坐标全零取真",)),
    ("显式零与显式 null",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],'
       '"elite":0,"level":0,"potential":0,"trust":0,"module_level":0,'
       '"time":0,"auto_skill":null,"module":""}]}'),
     "parity", ("显式 0 不是 None", "time 显式 0", "auto_skill 显式 null 得 False",
                "module 空串保留")),
    ("skill/mastery 写成字符串数字",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],'
       '"skill":"2","mastery":"1"}]}'),
     "parity", ("字符串数字",)),
    ("撤退与开技能",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]}],'
       '"retreats":[{"operator":"甲","time":5}],'
       '"skills":[{"operator":"甲","time":3,"slot":1}],'
       '"title":"标题","notes":"备注"}'),
     "parity", ("撤退", "开技能带槽位")),
    ("带 BOM（原版也不吃）", BOM + j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]}]}'),
     "both-refuse", ("BOM 两边都拒",)),
    ("顶层不是对象", j('[1,2]'), "both-refuse", ("顶层非对象",)),
    ("缺 stage",
     j('{"deploys":[{"operator":"甲","position":[1,1]}]}'),
     "both-refuse", ("校验：缺关卡号",)),
    ("一个部署都没有", j('{"stage":"1-7","deploys":[]}'),
     "both-refuse", ("校验：无部署",)),
    ("同一人部署两次",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]},'
       '{"operator":"甲","position":[2,2]}]}'),
     "both-refuse", ("校验：同一人两次",)),
    ("两人挤同一格",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]},'
       '{"operator":"乙","position":[1,1]}]}'),
     "both-refuse", ("校验：同格重叠",)),
    ("撤退没部署过的人",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]}],'
       '"retreats":[{"operator":"丙","time":1}]}'),
     "both-refuse", ("校验：撤退未部署者",)),
    ("给没部署的人开技能",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1]}],'
       '"skills":[{"operator":"丙","time":1}]}'),
     "both-refuse", ("校验：给未部署者开技能",)),
    ("部署不是对象", j('{"stage":"1-7","deploys":[42]}'),
     "both-refuse", ("部署非对象",)),
    ("部署缺 operator", j('{"stage":"1-7","deploys":[{"position":[1,1]}]}'),
     "both-refuse", ("部署缺名字",)),
    ("坐标是三元组",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,2,3]}]}'),
     "both-refuse", ("坐标非二元",)),
    ("skill 为对象（本轮未接）",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],'
       '"skill":{"id":"skchr_acspec_1","level":7}}]}'),
     "go-refuse-only", ("skill 对象分支只验拒收",)),
    ("operator 不是字符串",
     j('{"stage":"1-7","deploys":[{"operator":5,"position":[1,1]}]}'),
     "go-refuse", ("非字符串 operator（分歧）",)),
    ("direction 不是字符串",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],'
       '"direction":7}]}'),
     "both-refuse", ("非法 direction 两边都拒",)),
    ("direction 不在四个朝向里",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],'
       '"direction":"Sideways"}]}'),
     "both-refuse", ("朝向表外",)),
    ("技能槽越界",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[1,1],"skill":4}]}'),
     "both-refuse", ("技能槽越界",)),
    ("坐标写成小数",
     j('{"stage":"1-7","deploys":[{"operator":"甲","position":[5.7,-4.2]}]}'),
     "parity", ("坐标向零截断",)),
]


def go_plan(path: Path) -> tuple[bool, object]:
    env = dict(os.environ)
    env["RIOS_DATA"] = str(DATA)
    req = json.dumps({"id": 1, "cmd": "plan", "path": str(path)}) + "\n"
    p = subprocess.run([GO_BIN], input=req.encode("utf-8"),
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
    return True, resp["plan"]


def py_plan(path: Path):
    from ak_tactic.plan import Plan

    return Plan.load(path)


def diff_plan(got: dict, plan) -> list[str]:
    """逐字段比。返回差异清单（空 = 一致）。"""
    out: list[str] = []
    for f in ("stage", "title", "notes"):
        if got[f] != getattr(plan, f):
            out.append("%s：Go=%r Python=%r" % (f, got[f], getattr(plan, f)))
    if len(got["deploys"]) != len(plan.deploys):
        out.append("部署条数：Go=%d Python=%d"
                   % (len(got["deploys"]), len(plan.deploys)))
        return out
    for i, (g, w) in enumerate(zip(got["deploys"], plan.deploys)):
        if [float(x) for x in g["position"]] != [float(x) for x in w.position]:
            out.append("第 %d 条 position：Go=%r Python=%r"
                       % (i, g["position"], list(w.position)))
        for f in DEPLOY_FIELDS:
            if g[f] != getattr(w, f):
                out.append("第 %d 条 %s：Go=%r Python=%r"
                           % (i, f, g[f], getattr(w, f)))
    #: Go 的空切片出 `null`、原版是 `[]`——形状不同、语义相同，这里按语义比。
    gret = [(r["operator"], float(r["time"])) for r in (got["retreats"] or [])]
    wret = [(r.operator, float(r.time)) for r in plan.retreats]
    if gret != wret:
        out.append("撤退：Go=%r Python=%r" % (gret, wret))
    gsk = [(s["operator"], float(s["time"]), s["slot"])
           for s in (got["skills"] or [])]
    wsk = [(s.operator, float(s.time), s.slot) for s in plan.skills]
    if gsk != wsk:
        out.append("开技能：Go=%r Python=%r" % (gsk, wsk))
    return out


def collect_fixtures() -> list[Path]:
    """`fixtures/` 下认得出是打法的那些（字典且带 deploys/deploy）。"""
    out = []
    for f in sorted(FIXDIR.glob("*.json")):
        try:
            d = json.loads(f.read_text(encoding="utf-8"))
        except Exception:                                  # noqa: BLE001
            continue
        if isinstance(d, dict) and ("deploys" in d or "deploy" in d):
            out.append(f)
    return out


def main() -> int:
    import ak_tactic.plan as P

    print("Go 侧仪器：%s" % GO_BIN)
    print("Python 侧权威：ak_tactic.plan.Plan.from_dict/validate（%s）"
          % Path(P.__file__).name)
    print()

    mutate = "--mutate" in sys.argv
    seen: dict[str, int] = {}
    bad = 0
    compared = 0
    diverged: list[str] = []

    #: ---- 全量夹具 ----
    fixtures = collect_fixtures()
    seen["全量夹具对拍"] = len(fixtures)
    for k, f in enumerate(fixtures):
        ok, got = go_plan(f)
        try:
            plan = py_plan(f)
            py_ok = True
        except Exception as exc:                           # noqa: BLE001
            plan, py_ok = None, False
        if not ok or not py_ok:
            bad += 1
            print("✗ 夹具 %s —— Go ok=%s Python ok=%s%s"
                  % (f.name, ok, py_ok, "" if ok else "：%s" % got))
            continue
        compared += 1
        if mutate and compared == 1:
            got = json.loads(json.dumps(got))
            got["deploys"][0]["level"] = 99
        for d in diff_plan(got, plan):
            bad += 1
            print("✗ 夹具 %s %s" % (f.name, d))

    #: ---- 合成用例 ----
    with tempfile.TemporaryDirectory() as td:
        for i, (label, blob, expect, brs) in enumerate(CASES):
            path = Path(td) / ("case%d.json" % i)
            path.write_bytes(blob)
            for b in brs:
                seen[b] = seen.get(b, 0) + 1
            ok, got = go_plan(path)
            try:
                plan = py_plan(path)
                py_ok, py_err = True, ""
            except Exception as exc:                       # noqa: BLE001
                plan, py_ok = None, False
                py_err = "%s: %s" % (type(exc).__name__, exc)

            if expect == "both-refuse":
                if ok or py_ok:
                    bad += 1
                    print("✗ %s —— 期望两边都拒：Go ok=%s Python ok=%s"
                          % (label, ok, py_ok))
                continue
            if expect == "go-refuse":
                if ok or not py_ok:
                    bad += 1
                    print("✗ %s —— 期望「Go 拒 ∧ 原版收」：Go ok=%s Python ok=%s"
                          % (label, ok, py_ok))
                else:
                    diverged.append("%s（Go: %s）" % (label, got))
                continue
            if expect == "go-refuse-only":
                if ok:
                    bad += 1
                    print("✗ %s —— 期望 Go 拒（原版那一侧本轮不断言）" % label)
                continue

            if not ok:
                bad += 1
                print("✗ %s —— Go 拒了：%s" % (label, got))
                continue
            if not py_ok:
                bad += 1
                print("✗ %s —— 原版拒了：%s" % (label, py_err))
                continue
            compared += 1
            if mutate and compared == 1:
                got = json.loads(json.dumps(got))
                got["deploys"][0]["level"] = 99
            for d in diff_plan(got, plan):
                bad += 1
                print("✗ %s %s" % (label, d))

    print()
    print("已比：打法（计划）；全量夹具 %d 份 ＋ 合成 %d 例，共 %d 例逐字段比"
          % (len(fixtures), len(CASES), compared))
    print("★ 行使计数（每道口径各走了几例）：")
    for b, n in sorted(seen.items(), key=lambda kv: kv[0]):
        print("    %-24s %d" % (b, n))
    unchecked = [b for _, _, _, brs in CASES for b in brs if seen.get(b, 0) == 0]
    print()
    if diverged:
        print("★ 已登记的分歧（要求「Go 拒 ∧ 原版收」同时成立，不算对拍失败）：")
        for d in diverged:
            print("    %s" % d)
        print()
    if mutate:
        if bad:
            print("反向守卫：合成一处不一致 → 判红 —— 成立 ✓")
            return 0
        print("反向守卫：不成立 ✗")
        return 1
    if unchecked:
        print("结论：用例表没覆盖到 %s —— 判红（不是实现错，是判据自己瞎）"
              % "、".join(unchecked))
        return 1
    if not diverged:
        print("结论：登记分歧那几例没同时成立「Go 拒 ∧ 原版收」—— 判红")
        return 1
    print("结论：%d 例逐字段一致（另含 %d 例登记分歧）" % (compared, len(diverged)))
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
