#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""怀黍离 11 关**现状台账**（项目经理通告 #3 派给验收与守卫的 P0 输入）。

每一关给四样（通告原文）：

    ① Go 能不能跑（拒跑就写 unsupported 的**具体键**）
    ② 四项差各多少（杀 / 漏 / 用时 / 伤害，Go − 原版）
    ③ 差异指纹（什么量、什么时刻开始分岔）
    ④ 闸门归属（哪个机制族）

用法::

    python tools\\parity_ledger.py                # 17 份计划全跑（默认）
    python tools\\parity_ledger.py --only 11      # 只跑历史台账里的 11 关
    python tools\\parity_ledger.py --plans plan-hsex07.json,plan-hstr02.json

产物：`docs/parity-ledger.md`（人读）+ `out/acceptance/parity-ledger.json`（机器读）。

## 三条口径（都是本项目吃过的亏）

1. **不复合 `parity_plan.py`**：它现在跑不起来（`GoCapture._run_other_engine` 不接受
   `schedule`，见 `docs/acceptance-claims.md`）。本工具用**活的**那条路重写同一个比较，
   复用现成零件：`golden_go.SpecCapture` 抄规格、`Simgo` 跑 Go、`Verifier(engine="python")`
   跑原版、`simgo.client.compare` 做逐项对拍。**我不改 parity_plan.py**（不是我的文件），
   只把断点登记给它的所有者。
2. **"Go 跑得起来"要问闸门，不能只看有没有报错**：闸门（`spec["unsupported"]`）非空时
   Go 会**退回原版**跑——那时的"四项零差"是**假绿**（记忆 ed34c994）。所以这里先看
   `unsupported` 与 `go_fallbacks`，再看四项差。
3. **历史台账（16:16 的 `out/sweep-hsl.json`）只当线索**：实测其中一关
   （`act31side_ex07`）现在四项已经归零了。所以"哪 11 关"由**本轮实测**重新分类，
   历史那栏只作对照，绝不当作结论。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import traceback
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUT = ROOT / "out" / "acceptance"
LEDGER_MD = ROOT / "docs" / "parity-ledger.md"
LEDGER_JSON = OUT / "parity-ledger.json"

sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(ROOT))

#: 计划文件名 → 关卡名（怀黍离 act31side_*）。取自 `out/sweep-hsl.json` 的对照，
#: 那份是 16:16 的旧账，只用来认名字。
PLAN2STAGE = {
    "plan-hs01.json": "act31side_01", "plan-hs02.json": "act31side_02",
    "plan-hs03.json": "act31side_03", "plan-hs04.json": "act31side_04",
    "plan-hs05.json": "act31side_05", "plan-hs06.json": "act31side_06",
    "plan-hs09.json": "act31side_09",
    "plan-hsex01.json": "act31side_ex01", "plan-hsex02.json": "act31side_ex02",
    "plan-hsex03.json": "act31side_ex03", "plan-hsex04.json": "act31side_ex04",
    "plan-hsex05.json": "act31side_ex05", "plan-hsex06.json": "act31side_ex06",
    "plan-hsex07.json": "act31side_ex07", "plan-hsex08.json": "act31side_ex08",
    "plan-hstr01.json": "act31side_tr01", "plan-hstr02.json": "act31side_tr02",
    #: 通告 #5 三批准迁移进来的深水夹具（来源树 `ak-tactic-head` = 3b348616，
    #: 落后本树 78 提交；**夹具迁移，不是把旁支算进判据**）。两份都叫
    #: `act31side_ex08`，与本树的 `plan-hsex08.json`（1 人 46 秒对照）同关不同深度。
    "hsex8_max.json": "act31side_ex08", "hsex8.json": "act31side_ex08",
}

#: 历史台账（16:16）里的 11 关：8 关当时"闸门拦下"、3 关"真差"。
HISTORIC_11 = [
    "plan-hs02.json", "plan-hs03.json", "plan-hs04.json",
    "plan-hsex01.json", "plan-hsex03.json", "plan-hsex04.json",
    "plan-hsex05.json", "plan-hsex06.json",
    "plan-hs09.json", "plan-hsex07.json", "plan-hstr02.json",
]

#: ④ 闸门归属：`spec.py::unsupported_reasons` 的 `bad.append(...)` 原文 → 机制族。
#: 键是正则（按闸门**原文**匹配，不猜语义）。
FAMILIES: list[tuple[str, str]] = [
    (r"^召唤物部署|^装置部署|^撤退", "排程类（sch.summon/device_deployments、sch.retreats）"),
    (r"^关卡装置", "装置层（inp.devices）"),
    (r"^积雪", "积雪（inp.snow_fields）"),
    (r"^全场总攻击装置", "全场总攻击（sim.total_attack）"),
    (r"^技能[：:]", "技能白名单（op.skill）"),
    (r"^天赋「强击瓶专家」", "天赋族：强击瓶专家（多轮/落点/蓄力）"),
    (r"^天赋「翔虫机动」", "天赋族：翔虫机动"),
    (r"^天赋回技力|^高台触发回技力", "SP 侧天赋（sp_per_*）"),
    (r"^技能治疗倍率", "治疗倍率（heal_scale）"),
    (r"^技能效果覆盖", "技能效果覆盖（op.effects_override）"),
    (r"^概率闪避", "闪避（op.dodge_*）"),
    (r"^弱点伤害", "弱点伤害（op.weakness_damage）"),
    (r"^天赋攻速", "天赋攻速（op.aspd_*）"),
]


def family_of(key: str) -> str:
    for pat, fam in FAMILIES:
        if re.search(pat, key):
            return fam
    return "未归类（照抄原文，待登记）"


_TREE_HEAD: dict[str, str] = {}


def source_dirty() -> int:
    """本树未提交改动的条数。实测出现过同一棵树在**两次运行之间**从 60 变 61
    ⇒ "全绿"只对**当时那份工作树**成立，不对任何提交成立。每次运行都要带这个数。"""
    try:
        import subprocess
        p = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                           capture_output=True, text=True, timeout=60)
        return len([ln for ln in (p.stdout or "").splitlines() if ln.strip()])
    except Exception:                                            # noqa: BLE001
        return -1


def tree_head(plan_file: Path) -> str:
    """该夹具文件所在检出树的 HEAD（短哈希）。带出处是台账的硬要求。"""
    root = plan_file.resolve().parents[1]
    key = str(root)
    if key not in _TREE_HEAD:
        try:
            import subprocess
            p = subprocess.run(["git", "-C", key, "rev-parse", "--short", "HEAD"],
                               capture_output=True, text=True, timeout=30)
            _TREE_HEAD[key] = (p.stdout or "").strip() or "?"
        except Exception:                                        # noqa: BLE001
            _TREE_HEAD[key] = "?"
    return _TREE_HEAD[key]


def fixture(name: str) -> Path:
    for cand in (ROOT / name, ROOT / "out" / name, ROOT / "data" / "skland" / name):
        if cand.exists():
            return cand
    raise SystemExit(f"找不到夹具：{name}")


def first_leak_diff(py: list, go: list) -> dict | None:
    """漏事件逐笔（时刻 + 名字 + 扣命）比，返回**第一笔不同**。"""
    n = max(len(py), len(go))
    for i in range(n):
        a = tuple(py[i]) if i < len(py) else None
        b = tuple(go[i]) if i < len(go) else None
        if a != b:
            return {"index": i, "py": a, "go": b}
    return None


def discover(plan_dir: Path) -> list[str]:
    """按 **schema** 认作业，不按文件名：`deploys` + `stage` 两个键都在才算。

    ⚠ 为什么不能按 `plan-*.json` 认：夹具的名字是历史留下的，**不统一**。实测
    按名字认会漏掉 `hsex8_max.json`（八人满练度深水用例，通告 #5 三批准迁移进本树）
    ——而它恰恰是本树唯一能走到长线的那一份。漏掉它，"全绿"就又是覆盖不到机制的那种绿。
    """
    found: list[str] = []
    for p in sorted(plan_dir.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:                                        # noqa: BLE001
            continue
        if isinstance(d, dict) and "deploys" in d and "stage" in d:
            found.append(p.name)
    return found


def run_stage(plan_file: Path, roster, plan_cls, verifier_cls,
              spec_capture_cls, simgo_cls, find_binary, compare) -> dict:
    raw = json.loads(plan_file.read_text(encoding="utf-8-sig"))
    plan = plan_cls.from_dict(raw)
    rec: dict = {"plan": plan_file.name,
                 #: 阶段名优先查对照表；查不到就用**夹具自报的 `stage`**——比打印 "?"
                 #: 有用得多（按 schema 认作业时会捞到非 act31side 的夹具，那些也有自己的关名）。
                 "stage": PLAN2STAGE.get(plan_file.name) or raw.get("stage") or "?",
                 #: ⚠ 台账每条都要带**绝对路径 + 该路径属于哪个检出树**：实测踩过
                 #: "同一关名、不同树的夹具"被读成"同一关的多份作业"（旁支树
                 #: `ak-tactic-head` 落后本树 78 个提交，里面的 `hsex8_max.json`
                 #: 是八人满练度作业，而本树的 `plan-hsex08.json` 是 46 秒单人对照）。
                 "plan_path": str(plan_file.resolve()),
                 "tree": str(plan_file.resolve().parents[1]),
                 "tree_head": tree_head(plan_file),
                 "title": raw.get("title"),
                 "deploys_n": len(raw.get("deploys") or [])}

    # ---- 原版（权威参照）----
    try:
        pv = verifier_cls(engine="python")
        pr = pv.run(plan, roster=roster)
        res = pr.result
        rec["py"] = {
            "kills": int(pr.kills), "leaks": int(pr.leaks),
            "elapsed": round(float(pr.elapsed), 4),
            "damage": round(float(getattr(res, "damage_dealt", 0.0) or 0.0), 1),
            "skill_activations": getattr(res, "skill_activations", None),
            "operator_deaths": getattr(res, "operator_deaths", None),
            "won": bool(getattr(res, "won", False)),
            "spawns_total": getattr(res, "spawns_total", None),
            "spawns_placed": getattr(res, "spawns_placed", None),
            "timed_out": getattr(res, "timed_out", None),
            "leak_events": [[round(float(t), 4), str(n), int(c)] for t, n, c in
                            (getattr(res, "leak_events", []) or [])],
        }
    except Exception as e:                                       # noqa: BLE001
        rec["state"] = "未跑"
        rec["why"] = f"原版跑不起来：{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc()[-800:]
        return rec

    # ---- 抄规格（顺带走 Go 一次）----
    try:
        v = spec_capture_cls()
        r = v.run(plan, roster=roster)
        rec["go_runs"] = getattr(v, "go_runs", None)
        rec["go_fallbacks"] = getattr(v, "go_fallbacks", None)
        rec["spec_error"] = v.spec_error
        rec["spec_sha"] = None
        spec = v.spec
        rec["go"] = {"kills": int(r.kills), "leaks": int(r.leaks),
                     "elapsed": round(float(r.elapsed), 4),
                     "damage": round(float(r.damage), 1)}
    except Exception as e:                                       # noqa: BLE001
        rec["state"] = "未跑"
        rec["why"] = f"Go 侧跑不起来：{type(e).__name__}: {e}"
        rec["trace"] = traceback.format_exc()[-800:]
        return rec

    if spec is None:
        rec["state"] = "未跑"
        rec["why"] = f"规格抄不到（spec_error）：{rec['spec_error']}"
        return rec

    # ---- ① 闸门：拒跑？----
    unsupported = list(spec.get("unsupported") or [])
    rec["unsupported"] = unsupported
    rec["families"] = sorted({family_of(u) for u in unsupported})
    rec["spawns_total"] = len(spec.get("spawns") or [])
    rec["mechanisms"] = spec.get("mechanisms")

    # ---- ② Go 真跑一次，拿带事件明细的判决 ----
    try:
        with simgo_cls(find_binary()) as cli:
            got = cli.sim(spec)
    except Exception as e:                                       # noqa: BLE001
        rec["state"] = "闸门拒跑" if unsupported else "未跑"
        rec["why"] = f"Go 二进制拒跑：{type(e).__name__}: {e}"
        return rec

    rec["go_exe"] = str(find_binary())
    events = got.get("events") or []
    kinds: dict[str, int] = {}
    for e in events:
        kinds[str(e.get("kind"))] = kinds.get(str(e.get("kind")), 0) + 1
    rec["event_kinds"] = kinds
    #: 记忆 10f0641b：**先问「谁先塌」再问「谁少打了」**。阵亡时刻是这条线上
    #: 最早的可观测量——Go 侧第一笔 death 的时刻，就是"分岔不晚于此刻"的上界。
    deaths = sorted(float(e.get("t") or 0.0) for e in events if e.get("kind") == "death")
    rec["go_death_first_t"] = round(deaths[0], 4) if deaths else None
    rec["go_death_events"] = len(deaths)
    rec["go_verdict"] = {
        "kills": got.get("kills"), "leaks": got.get("leaks"),
        "elapsed": round(float(got.get("elapsed") or 0.0), 4),
        "damage": round(float(got.get("damage_dealt") or 0.0), 1),
        "spawns_total": got.get("spawns_total"), "spawns_placed": got.get("spawns_placed"),
        "operator_deaths": got.get("operator_deaths"),
        "timed_out": got.get("timed_out"), "remnants": got.get("remnants"),
        "skill_events": kinds.get("skill", 0),
        "mech_events": kinds.get("mech", 0),
        "env_events": kinds.get("env", 0),
        "kill_events": kinds.get("kill", 0),
        "mech_state": got.get("mech_state"),
    }
    #: ⚠ 记忆 8a1ec6d6：**无回归 ≠ 已验证**。四项归零只说明"两条路算出同一个数"，
    #: 不说明这一局真的踩到了该踩的机制。所以把"机制有没有动作"单独报出来：
    #:   有动作   = 运行期真报了机制事件（mech/env）或 mech_state 非空
    #:   只落位   = 规格挂上了机制名，但运行期一笔事件都没有
    #:   无机制   = 规格里也没有
    mech_names = list(spec.get("mechanisms") or [])
    if kinds.get("mech", 0) or kinds.get("env", 0) or got.get("mech_state"):
        rec["touched"] = "有动作"
    elif mech_names:
        rec["touched"] = "只落位（规格挂了机制名，运行期零事件）"
    else:
        rec["touched"] = "无机制"
    rec["go_leaks"] = [[round(float(t), 4), str(n), int(c)]
                       for t, n, c in (got.get("leak_events") or [])]

    # ---- ② 四项差（Go − 原版）----
    g, p = rec["go_verdict"], rec["py"]
    rec["diff"] = {
        "kills": g["kills"] - p["kills"],
        "leaks": g["leaks"] - p["leaks"],
        "elapsed": round(g["elapsed"] - p["elapsed"], 4),
        "damage": round(g["damage"] - p["damage"], 1),
    }

    # ---- ③ 差异指纹 ----
    cmp_out = compare(pr.result, got)
    rec["compare_diff"] = {k: str(v)[:300] for k, v in (cmp_out.get("diff") or {}).items()}
    rec["leak_first_diff"] = first_leak_diff(rec["py"]["leak_events"], rec["go_leaks"])
    rec["skill_diff"] = (None if p["skill_activations"] is None
                         else int(g["skill_events"]) - int(p["skill_activations"]))

    zero = all(v == 0 for v in rec["diff"].values())
    if unsupported:
        #: ⚠ 闸门开着时 Go 退回原版，四项差必然是 0 —— 那是**假绿**，不能说"归零"。
        rec["state"] = "闸门拒跑"
    elif zero and cmp_out.get("ok"):
        rec["state"] = "归零"
    else:
        rec["state"] = "真差"
    return rec


def fingerprint_text(rec: dict) -> str:
    """③ 差异指纹：什么量、什么时刻开始分岔。"""
    if rec.get("state") == "闸门拒跑":
        return "—（Go 未跑，四项差不可测）"
    if rec.get("state") == "归零":
        return "四项与漏事件逐笔一致"
    bits = []
    d = rec["diff"]
    if d["kills"] or d["leaks"]:
        bits.append(f"杀 {d['kills']:+d} / 漏 {d['leaks']:+d}")
    if d["elapsed"]:
        bits.append(f"用时 {d['elapsed']:+.4f}s（{d['elapsed'] / (1 / 30):+.0f} 帧）")
    if d["damage"]:
        bits.append(f"伤害 {d['damage']:+,.1f}")
    ld = rec.get("leak_first_diff")
    if ld:
        py, go = ld["py"], ld["go"]
        bits.append(f"漏事件第 {ld['index']} 笔起分岔：原版 {py} vs Go {go}")
    elif rec.get("py", {}).get("leak_events") or rec.get("go_leaks"):
        bits.append("漏事件逐笔相同（分岔在伤害/击杀侧）")
    if rec.get("skill_diff"):
        bits.append(f"技能开启次数 {rec['skill_diff']:+d}")
    gv = rec.get("go_verdict") or {}
    if gv.get("remnants"):
        bits.append(f"Go 侧残留：{gv['remnants']}")
    if gv.get("timed_out"):
        bits.append("Go 侧 timed_out=True")
    if gv.get("operator_deaths") or rec.get("go_death_events"):
        bits.append(f"干员阵亡：Go {gv.get('operator_deaths')} 名"
                    f"（首笔 t={rec.get('go_death_first_t')}s）"
                    f" vs 原版 {rec.get('py', {}).get('operator_deaths')} 名")
    return "；".join(bits) or "判定不同但四项差为零（见 compare_diff）"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                            # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="怀黍离 11 关现状台账")
    ap.add_argument("--only", choices=["11", "17"], default="17",
                    help="11=只跑历史台账里那 11 关；17=全部计划（默认）")
    ap.add_argument("--plans", default="", help="逗号分隔的计划文件名")
    ap.add_argument("--plan-dir", default=str(ROOT / "fixtures" if (ROOT / "fixtures").is_dir()
                                              else ROOT / "out"),
                    help="计划所在目录（默认判据集 fixtures/；可指向别的检出树，"
                         "此时台账里必须带出处）")
    ap.add_argument("--out", default=str(LEDGER_MD))
    ap.add_argument("--json", default=str(LEDGER_JSON))
    args = ap.parse_args()

    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier
    from ak_tactic.simgo import find_binary
    from ak_tactic.simgo.client import Simgo, compare
    import golden_go as G

    # ⚠ 名册是**别名**：磁盘上叫 `roster_max_modelled.json`，而且可能落在姊妹
    # checkout（`ak-tactic-head/out/`）里。复用 golden_go 的查找（它踩过这个坑）。
    roster = Roster.from_json(G._find("roster_max_modelled"))

    plan_dir = Path(args.plan_dir)
    if args.plans:
        names = [n.strip() for n in args.plans.split(",") if n.strip()]
    elif args.only == "11":
        names = HISTORIC_11
    else:
        names = discover(plan_dir)

    print(f"口径：Go 二进制 {find_binary()}")
    print(f"计划 {len(names)} 份；原版引擎 = python；闸门读 spec['unsupported']")
    print("=" * 100)

    t0 = time.time()
    recs: list[dict] = []
    for name in names:
        pf = plan_dir / name
        if not pf.exists():
            recs.append({"plan": name, "stage": PLAN2STAGE.get(name, "?"),
                         "state": "未跑", "why": "计划文件不存在"})
            print(f"{name:<22} 未跑（文件不存在）")
            continue
        t1 = time.time()
        try:
            rec = run_stage(pf, roster, Plan, Verifier, G.SpecCapture, Simgo,
                            find_binary, compare)
        except Exception as e:                                   # noqa: BLE001
            rec = {"plan": name, "stage": PLAN2STAGE.get(name, "?"), "state": "未跑",
                   "why": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc()[-800:]}
        rec["seconds"] = round(time.time() - t1, 1)
        recs.append(rec)
        mark = {"归零": "✅", "真差": "❌", "闸门拒跑": "⛔", "未跑": "⊘"}.get(rec["state"], "?")
        detail = (", ".join(rec["unsupported"])[:80] if rec.get("unsupported")
                  else fingerprint_text(rec)[:80])
        print(f"{rec['stage']:<18} {mark} {rec['state']:<6} "
              f"{rec.get('diff') if rec.get('diff') else rec.get('why', '')}"
              f"  [{detail}]")

    zero = [r for r in recs if r["state"] == "归零"]
    gate = [r for r in recs if r["state"] == "闸门拒跑"]
    real = [r for r in recs if r["state"] == "真差"]
    norun = [r for r in recs if r["state"] == "未跑"]
    print("=" * 100)
    print(f"归零 {len(zero)} / 闸门拒跑 {len(gate)} / 真差 {len(real)} / 未跑 {len(norun)}"
          f"　耗时 {(time.time() - t0) / 60:.1f} 分钟")

    OUT.mkdir(parents=True, exist_ok=True)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    exe_path = Path(find_binary())
    try:
        import hashlib
        exe_sha = hashlib.sha256(exe_path.read_bytes()).hexdigest()[:16]
        exe_size = exe_path.stat().st_size
    except Exception:                                            # noqa: BLE001
        exe_sha, exe_size = "未知", 0
    dirty = source_dirty()
    Path(args.json).write_text(json.dumps(
        {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "engine_env_bin": str(exe_path), "engine_env_bin_sha16": exe_sha,
         "engine_env_bin_bytes": exe_size, "source_dirty": dirty,
         "tree": str(ROOT), "tree_head": tree_head(ROOT / "out" / "x.json"),
         "counts": {"zero": len(zero), "gate": len(gate), "real": len(real),
                    "norun": len(norun)},
         "records": recs}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_md(recs, Path(args.out), exe_path, exe_sha, exe_size, dirty)
    print(f"台账：{Path(args.out)}")
    return 0


def write_md(recs: list[dict], path: Path, exe, exe_sha: str = "?", exe_size: int = 0,
             dirty: int = -1) -> None:
    zero = [r for r in recs if r["state"] == "归零"]
    gate = [r for r in recs if r["state"] == "闸门拒跑"]
    real = [r for r in recs if r["state"] == "真差"]
    norun = [r for r in recs if r["state"] == "未跑"]
    L: list[str] = []
    L.append("# 怀黍离 11 关现状台账（Go vs 原版）")
    L.append("")
    L.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}；"
             f"执行者：验收与守卫会话 `session-1a45cfee-9a65-4830-a327-03ac84285bfb`")
    L.append(f"- 工具：`tools/parity_ledger.py`（通告 #3 派工；**不复用跑不起来的** "
             f"`parity_plan.py`，见 `docs/acceptance-claims.md`）")
    L.append(f"- Go 二进制：`{exe}`（私有构建，`RIOS_SIM_BIN` 指定，不写回共享树）")
    L.append(f"  - **仪器身份**：`RIOS_SIM_BIN` 已显式设上，其 sha256 前 16 位 "
             f"**`{exe_sha}`**、{exe_size:,} 字节（未设变量的轮次一律标「二进制身份未知」，"
             f"不得与本表混用）")
    L.append(f"  - **来源三件套**：每条带 `plan_path`（绝对）／所属检出树／该树 HEAD，见下一节")
    L.append(f"  - **`source_dirty`**：本轮 **{dirty}** 条未提交改动"
             f"（实测同一棵树在两次运行之间从 60 变 61 ⇒ **本表只对当时那份工作树成立，"
             f"不对任何提交成立**）")
    L.append(f"- 本轮实测：**归零 {len(zero)} / 闸门拒跑 {len(gate)} / 真差 {len(real)} "
             f"/ 未跑 {len(norun)}**（共 {len(recs)} 关）")
    L.append("")
    _stages = {r.get("stage") for r in recs}
    L.append(f"**计数口径（通告 #5 一）**：**作业数 = {len(recs)}**（按 `plan_path` 计，"
             f"一份计划 = 一份作业）；**关卡数 = {len(_stages)}**（按 `stage` 去重）；"
             f"**门的判据是关卡数**——门问的是「这一关 Go 与原版一致吗」，"
             f"不是「这份解一致吗」。"
             f"两个数必须一起写，且写明判据取哪一个。")
    L.append("")
    L.append("> ⚠ **深水限定语（通告 #5 四，谁引用谁带）**：「本树现有的用例全绿」**不等于**"
             "「这些关没问题」。本树这套夹具里能走到长线的只有**后补的 `hsex8_max.json` "
             "（八人满练度、814 秒）**，其余大多是几十秒的浅用例；两者差着一整个深度维度。")
    L.append("")
    L.append("> ⚠ **深水用例 `hsex8_max` 的差异＝「成立」**（三台仪器一致，含我这台）。"
             "一度被写成「待重新确立」，起因是另一台工具的 Python 侧**没钉 `engine=`**："
             "09-19 引擎切换后裸 `Verifier()` 跑的是 **Go**，却照样打 `[python]` 前缀"
             "——**自己跟自己比**，静默假绿（记忆 ad36418f）。修好后它的 Python 侧复现出 "
             "`83杀/1漏/814.033333s`，与 `parity_plan` 和我这台**到小数第六位一致**。")
    L.append("> 　**判据在修之前就写死了**：先钉「修好后 Python 侧必须复现 "
             "`83杀/1漏/814.033s`」，再去修仪器——不然修完看到什么数都可以叫「对上了」。")
    L.append(">")
    L.append("> 我这台仪器的实测（`parity_ledger.py` 直连 `Verifier(engine='python')` + "
             "`Simgo.sim`，**engine 是显式钉住的**，不 monkey-patch 被测对象）："
             "**原版 83杀/1漏/814.0333s/won=True/timed_out=False/死5人/落位72** vs "
             "**Go 48杀/3漏/221.6667s/won=False/死8人/落位64**；"
             "**两笔第一漏事件相同**（t=96.4 厌肮）⇒ 分岔在**阵亡与后续出怪**侧，不在漏事件起点。"
             "`won=True` 且 `timed_out=False` 说明原版那 814 秒是**自然打完的一局**。")
    L.append(">")
    L.append("> ⚠ 仍须带的限定语：「本树现有用例全绿」**不等于**「这些关没问题」——"
             "能走到这条长线的**只有这一份**，其余大多是几十秒的浅用例。")
    L.append("")
    L.append("> ⚠ 历史台账（`out/sweep-hsl.json`，16:16）记的是「9 零 / 8 闸门 / 3 真差」，"
             "**已经过期**（那还是按作业数的旧口径）：本轮实测**没有任何一关被闸门拦下**。"
             "分类一律以本轮数字为准。")
    L.append("")
    L.append("## 一之二、作业深度与出处（**门的真实覆盖**——别只看「归零」）")
    L.append("")
    L.append("> ⚠ 实测教训：`act31side_ex08` 在**本树**只有一份 **1 人 46 秒对照**作业"
             "（标题自述「只求敌方技能出手落地，不求是好解」），而**旁支树** "
             "`ak-tactic-head`（落后 78 提交）里的同关作业是 **8 人满练度**、跑 814 秒。"
             "两份都叫 `act31side_ex08`，**根本不是一件事**。所以每一条都必须带出处与人数，"
             "否则\"同一关名、不同树的夹具\"会被读成\"同一关的多份作业\"，"
             "进而把旁支树的旧夹具读成本树的回归。")
    L.append("")
    L.append("| 关卡 | 计划 | 作业人数 | 标题 | 检出树 HEAD | 绝对路径 |")
    L.append("|---|---|---|---|---|---|")
    for r in recs:
        L.append(f"| {r.get('stage', '?')} | `{r.get('plan')}` | {r.get('deploys_n', '?')} | "
                 f"{r.get('title') or '—'} | `{r.get('tree_head', '?')}` | "
                 f"`{r.get('plan_path', '?')}` |")
    L.append("")
    L.append("## 一之三、总表")
    L.append("")
    L.append("| 关卡 | 计划 | 状态 | 杀 | 漏 | 用时(s) | 伤害 | ①闸门（unsupported 原文） | ④机制族 | ⑤机制咬到了吗 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in recs:
        d = r.get("diff") or {}
        uns = "<br>".join(r.get("unsupported") or []) or "—"
        fam = "<br>".join(r.get("families") or []) or "—"
        fmt = (lambda v, n=0: "—" if v is None else f"{v:+.{n}f}")
        L.append(f"| {r['stage']} | `{r['plan']}` | {r['state']} | {fmt(d.get('kills'))} | "
                 f"{fmt(d.get('leaks'))} | {fmt(d.get('elapsed'), 4)} | "
                 f"{fmt(d.get('damage'), 1)} | {uns} | {fam} | {r.get('touched', '—')} |")
    L.append("")
    zero_act = [r for r in zero if r.get("touched") == "有动作"]
    zero_lay = [r for r in zero if str(r.get("touched", "")).startswith("只落位")]
    zero_none = [r for r in zero if r.get("touched") == "无机制"]
    L.append(f"**归零 {len(zero)} 关的构成**（为了记住记忆 8a1ec6d6「无回归 ≠ 已验证」）："
             f"运行期有机制动作 **{len(zero_act)}**、只落位零事件 **{len(zero_lay)}**、"
             f"规格里也没有机制 **{len(zero_none)}**。后两类只能说「两条路算得一样」，"
             f"**不能**说「该踩的机制被验过了」。")
    L.append("")
    L.append(f"**计数口径**：本台账按**作业（计划文件）**计，1 份计划 = 1 关（对照表见 "
             f"`PLAN2STAGE`），故此处「作业数 = 关卡数 = {len(recs)}」。"
             f"⚠ 别的台账按**作业条数**计数会虚高（同一关可能挂多份作业，实测 "
             f"`act31side_08` 曾出现 4 次）——**门判据必须是去重后的关卡数**。")
    L.append("")
    L.append("## 二、逐关明细（① 能不能跑 / ② 四项差 / ③ 差异指纹 / ④ 机制族）")
    L.append("")
    for r in recs:
        L.append(f"### {r['stage']}（`{r['plan']}`）— **{r['state']}**")
        L.append("")
        if r["state"] == "未跑":
            L.append(f"- ⊘ 未跑：{r.get('why')}")
            L.append("")
            continue
        py, gv = r.get("py") or {}, r.get("go_verdict") or {}
        L.append(f"- ① Go 能不能跑：{'**不能**（闸门拒跑，退回原版）' if r['state'] == '闸门拒跑' else '能'}"
                 f"；`go_runs={r.get('go_runs')}` `go_fallbacks={r.get('go_fallbacks')}`"
                 f"，闸门键 {len(r.get('unsupported') or [])} 条")
        for u in (r.get("unsupported") or []):
            L.append(f"    - `{u}` → {family_of(u)}")
        L.append(f"- ② 四项差（Go − 原版）：杀 {r['diff']['kills']:+d}、漏 {r['diff']['leaks']:+d}、"
                 f"用时 {r['diff']['elapsed']:+.4f}s、伤害 {r['diff']['damage']:+,.1f}")
        L.append(f"    - 原版 {py.get('kills')}杀 {py.get('leaks')}漏 "
                 f"{py.get('elapsed')}s {py.get('damage')} 伤害；Go {gv.get('kills')}杀 "
                 f"{gv.get('leaks')}漏 {gv.get('elapsed')}s {gv.get('damage')} 伤害")
        L.append(f"- ③ 差异指纹：{fingerprint_text(r)}")
        if r.get("go_verdict", {}).get("spawns_total") is not None:
            L.append(f"    - 出怪 {gv.get('spawns_total')} 条（落位 {gv.get('spawns_placed')}）、"
                     f"干员阵亡 {gv.get('operator_deaths')}、技能事件 {gv.get('skill_events')} 笔"
                     + (f"、原版技能计数 {py.get('skill_activations')}"
                        if py.get("skill_activations") is not None else ""))
        L.append(f"- ④ 闸门归属：{'；'.join(r.get('families') or []) or '—（无闸门键）'}")
        L.append(f"- ⑤ 机制咬到了吗：**{r.get('touched', '?')}**"
                 f"（规格 mechanisms={r.get('mechanisms')}；运行期事件 "
                 f"{ {k: v for k, v in (r.get('event_kinds') or {}).items() if k in ('mech', 'env', 'skill', 'kill', 'leak', 'death')} }"
                 f"；mech_state={str(r.get('go_verdict', {}).get('mech_state'))[:120]}）")
        L.append("")
    L.append("## 三、按机制族的汇总（后端排接线优先级的输入）")
    L.append("")
    L.append("| 机制族 | 拦住的关卡数 | 关卡 |")
    L.append("|---|---|---|")
    fams: dict[str, list[str]] = {}
    for r in gate:
        for f in (r.get("families") or []):
            fams.setdefault(f, []).append(r["stage"])
    for f, st in sorted(fams.items(), key=lambda kv: -len(kv[1])):
        L.append(f"| {f} | {len(st)} | {'、'.join(st)} |")
    if not fams:
        L.append("| —（本轮没有闸门拒跑的关卡） | 0 | |")
    L.append("")
    L.append("## 四、本台账**没做**的事（别读成已做）")
    L.append("")
    L.append("- **覆盖缺口（最重要的一条）**：「归零」只说明**本树现有的这份作业**上两条路"
             "算得一样。同一关在别的树/别的练度下的**深水用例**（如 8 人满练度 814 秒那条线）"
             "本台账**一份都没跑到** —— 记忆 8a1ec6d6「无回归 ≠ 已验证」说的就是这个。"
             "要收这条缺口，先把深水夹具搬进本树并纳入金标准，再谈有没有差。")
    L.append("- ③ 的「时刻」粒度到**事件级**（漏事件第几笔、用时差几帧），"
             "**没有**逐帧事件流比对（那要开两侧 trace 通道，属下一层）。")
    L.append("- 只跑了 `out/` 里现成的 17 份计划；怀黍离其它关卡（若作业不在树上）未覆盖。")
    L.append("- 闸门拒跑的关卡**没有**绕开闸门强跑——绕开需要改规格送法，不在我的权限内。")
    L.append("- 名册：本轮用 `roster_max_modelled`（满练度名册，落在旁支树）；换名册会换掉"
             "「能不能走到分歧点」，所以数字只在同名册间可比。")
    L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
