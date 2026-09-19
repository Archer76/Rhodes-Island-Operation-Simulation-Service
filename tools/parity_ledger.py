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
import os
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
              spec_capture_cls, simgo_cls, find_binary, compare,
              base: dict | None = None, canon=None) -> dict:
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

    #: Go 自身基线（`fixtures/golden_go.json` 里钉住的那一份）——**新判据的参照物**。
    entry = (base or {}).get(plan_file.name) or {}

    # ---- 原版（**历史参考列**，博士 2026-09-19 裁定后不再作判据）----
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
        rec["spec_sha"] = canon(v.spec) if (canon and v.spec is not None) else None
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
    #: ⚠ 博士 2026-09-19 裁定：**基线改用 Go**（「过往和未来会新增的基线全部用 go 重跑」）。
    #: 于是「四项差 vs 原版」**退出判据**，降为**历史参考列**；判据换成
    #: **Go 自身的基线漂移**——拿本次 Go 的观测量对比 `fixtures/golden_go.json` 里钉住的
    #: Go 数，漂了才是红。原版那一列仍照跑、照留，但**不再定生死**。
    if unsupported:
        #: ⚠ 闸门开着时 Go 退回原版，四项差必然是 0 —— 那是**假绿**，不能说"归零"。
        rec["state_py_ref"] = "闸门拒跑"
    elif zero and cmp_out.get("ok"):
        rec["state_py_ref"] = "归零（旧读法：vs 原版）"
    else:
        rec["state_py_ref"] = "真差（旧读法：vs 原版）"
    drift = {}
    if entry:
        for k in ("kills", "leaks", "elapsed", "damage", "spec_sha"):
            now = (rec.get("spec_sha") if k == "spec_sha"
                   else rec["go_verdict"].get(k))
            if k == "elapsed" and isinstance(now, (int, float)) and isinstance(entry.get(k), (int, float)):
                same = abs(float(now) - float(entry[k])) <= 1e-4
            else:
                same = entry.get(k) == now
            if not same:
                drift[k] = {"基线": entry.get(k), "现在": now}
    rec["go_baseline_drift"] = drift
    rec["go_baseline_present"] = bool(entry)
    if unsupported:
        rec["state"] = "闸门拒跑"
    elif not entry:
        rec["state"] = "无基线可比"
    elif drift:
        rec["state"] = "Go 漂移"
    else:
        rec["state"] = "正常（与 Go 基线一致）"
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
    #: ⚠ 2026-09-20 后端2：本产物的「执行者」栏原先把「验收与守卫会话」**写死在题源里**，
    #: 于是**谁跑都署那个名**——实测我跑了一次，产物第 3 行照样写着那个会话（**假署名**）。
    #: 谁跑的就写谁：跑的人自己传，题源不许再写死某个会话。
    ap.add_argument("--actor", default="",
                    help="本次运行的署名（会话名／角色）；缺省读环境变量 AK_LEDGER_ACTOR，"
                         "两者都没有则产物写「未署名」")
    args = ap.parse_args()
    if args.actor and not os.environ.get("AK_LEDGER_ACTOR"):
        os.environ["AK_LEDGER_ACTOR"] = args.actor

    from ak_tactic.plan import Plan, Roster
    from ak_tactic.verify import Verifier
    from ak_tactic.simgo import find_binary
    from ak_tactic.simgo.client import Simgo, compare
    import golden_go as G
    from engine_pin import EngineBuildError, ensure_pinned

    #: ⚠ **自建自钉**：`find_binary()` 在 `52c89a4` 之后未设 `RIOS_SIM_BIN` 即抛。
    #: 在它之前，未钉时台账会把 `str(find_binary())` 记成字符串 `"None"`——**那是账本里的一笔假账**
    #: （栏位名像路径、值是 "None"，读的人会以为"这台机器上的引擎在 None 路径"）。
    #: 本工具要跑 Go 读数，就必须自己造一枚再钉住；构建失败**直接失败**，绝不退回既有 exe。
    try:
        exe, exe_sha_now, src_sig = ensure_pinned()
    except EngineBuildError as e:
        print(f"⛔ {e}")
        return 3

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

    #: 判据的参照物＝**Go 自身基线**（`fixtures/golden_go.json`），博士 2026-09-19 裁定。
    try:
        B = json.loads(Path(G.GOLDEN).read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        B = {}
    print(f"口径：Go 二进制 {find_binary()}")
    print(f"判据＝Go 自身基线漂移（{G.GOLDEN}，{len(B)} 份）；"
          f"原版数字仅作**历史参考列**，不进判据（博士 2026-09-19 裁定）")
    print(f"计划 {len(names)} 份；闸门读 spec['unsupported']")
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
                            find_binary, compare, base=B, canon=G.canonical_sha)
        except Exception as e:                                   # noqa: BLE001
            rec = {"plan": name, "stage": PLAN2STAGE.get(name, "?"), "state": "未跑",
                   "why": f"{type(e).__name__}: {e}",
                   "trace": traceback.format_exc()[-800:]}
        rec["seconds"] = round(time.time() - t1, 1)
        recs.append(rec)
        mark = {"正常（与 Go 基线一致）": "✅", "Go 漂移": "❌", "闸门拒跑": "⛔",
                "未跑": "⊘", "无基线可比": "◻"}.get(rec["state"], "?")
        detail = (", ".join(rec["unsupported"])[:80] if rec.get("unsupported")
                  else fingerprint_text(rec)[:80])
        print(f"{rec['stage']:<18} {mark} {rec['state']:<12} "
              f"{rec.get('diff') if rec.get('diff') else rec.get('why', '')}"
              f"  [{detail}]")

    okay = [r for r in recs if r["state"].startswith("正常")]
    drift = [r for r in recs if r["state"] == "Go 漂移"]
    gate = [r for r in recs if r["state"] == "闸门拒跑"]
    norun = [r for r in recs if r["state"] == "未跑"]
    print("=" * 100)
    print(f"【新判据】与 Go 基线一致 {len(okay)} / Go 漂移 {len(drift)} / "
          f"闸门拒跑 {len(gate)} / 未跑 {len(norun)}　耗时 {(time.time() - t0) / 60:.1f} 分钟")
    z = [r for r in recs if str(r.get("state_py_ref", "")).startswith("归零")]
    print(f"【旧读法，仅留档】vs 原版归零 {len(z)} / 真差 "
          f"{len([r for r in recs if str(r.get('state_py_ref', '')).startswith('真差')])}"
          f"（此列已退出判据，博士 2026-09-19 裁定）")

    OUT.mkdir(parents=True, exist_ok=True)
    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    exe_path = Path(find_binary())
    try:
        import hashlib
        exe_sha = hashlib.sha256(exe_path.read_bytes()).hexdigest()[:16]
        exe_size = exe_path.stat().st_size
    except Exception:                                            # noqa: BLE001
        exe_sha, exe_size = "未知", 0
    #: **基线自身记着的那枚仪器**：这一栏能被人看懂，全靠"基线那枚是哪个"写在旁边
    base_engine = {}
    try:
        _b = json.loads((ROOT / "fixtures" / "golden_go.json").read_text(encoding="utf-8"))
        _one = next(iter(_b.values()))
        base_engine = {"engine_bin": _one.get("engine_bin"),
                       "engine_bin_sha16": _one.get("engine_bin_sha16"),
                       "engine_bin_mtime": _one.get("engine_bin_mtime"),
                       "roster_sha16": _one.get("roster_sha16")}
    except Exception:                                            # noqa: BLE001
        pass
    dirty = source_dirty()
    Path(args.json).write_text(json.dumps(
        {"at": time.strftime("%Y-%m-%d %H:%M:%S"),
         "engine_env_bin": str(exe_path), "engine_env_bin_sha16": exe_sha,
         "engine_env_bin_bytes": exe_size, "source_dirty": dirty,
         "engine_source_sig": src_sig, "baseline_engine": base_engine,
         "tree": str(ROOT), "tree_head": tree_head(ROOT / "out" / "x.json"),
         "counts": {"ok": len(okay), "drift": len(drift), "gate": len(gate),
                    "norun": len(norun),
                    "old_zero_vs_py": len([r for r in recs if str(r.get("state_py_ref", "")).startswith("归零")]),
                    "old_real_vs_py": len([r for r in recs if str(r.get("state_py_ref", "")).startswith("真差")])},
         "records": recs}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    write_md(recs, Path(args.out), exe_path, exe_sha, exe_size, dirty, args.actor)
    print(f"台账：{Path(args.out)}")
    return 0


def write_md(recs: list[dict], path: Path, exe, exe_sha: str = "?", exe_size: int = 0,
             dirty: int = -1, actor: str = "") -> None:
    zero = [r for r in recs if str(r.get("state_py_ref", "")).startswith("归零")]
    gate = [r for r in recs if r["state"] == "闸门拒跑"]
    real = [r for r in recs if str(r.get("state_py_ref", "")).startswith("真差")]
    norun = [r for r in recs if r["state"] == "未跑"]
    okay = [r for r in recs if r["state"].startswith("正常")]
    drift = [r for r in recs if r["state"] == "Go 漂移"]
    L: list[str] = []
    L.append("# 怀黍离逐关台账（判据＝**Go 自身基线漂移**）")
    L.append("")
    _actor = (actor or os.environ.get("AK_LEDGER_ACTOR", "")).strip()
    _actor_txt = _actor or ("**未署名**（跑的人请传 `--actor` 或设 `AK_LEDGER_ACTOR`；"
                            "本栏 2026-09-20 之前把某个会话写死在题源里，已去掉——"
                            "写死等于给别人的运行签假名）")
    L.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}；执行者：{_actor_txt}")
    L.append(f"- 工具：`tools/parity_ledger.py`（通告 #3 派工；**不复用跑不起来的** "
             f"`parity_plan.py`，见 `docs/acceptance-claims.md`）")
    L.append(f"- Go 二进制：`{exe}`（私有构建，`RIOS_SIM_BIN` 指定，不写回共享树）")
    L.append(f"  - **仪器身份**：`RIOS_SIM_BIN` 已显式设上，其 sha256 前 16 位 "
             f"**`{exe_sha}`**、{exe_size:,} 字节（未设变量的轮次一律标「二进制身份未知」，"
             f"不得与本表混用）")
    L.append(f"  - **来源三件套**：每条带 `plan_path`（绝对）／所属检出树／该树 HEAD，见下一节")
    L.append("  - **基线自身记着的那枚仪器**：`fixtures/golden_go.json` 每条都带 "
             "`engine_bin` / `engine_bin_sha16` / `engine_bin_mtime` / `roster_sha16`"
             "（**与基线记录不同时只报不判**：那是仪器差，不是模型漂移；"
             "同一份源码两次构建哈希就不同 ⇒ `sha16` 只能证明「是不是那一次构建」，"
             "源码身份要看 `source_sig`）")
    L.append("  - **留证仪器（历史读数用）**：身份与它复现的读数**唯一登记处**＝"
             "`tools/guard_engine_bin.py::LEGACY_INSTRUMENTS`（入库、可 diff、随守卫逐位核对）；"
             "本表**只放指针不复制数字**——两处各写一份，一改就对不上")
    L.append(f"  - **`source_dirty`**：本轮 **{dirty}** 条未提交改动"
             f"（实测同一棵树在两次运行之间从 60 变 61 ⇒ **本表只对当时那份工作树成立，"
             f"不对任何提交成立**）")
    L.append(f"- 本轮实测（**新判据**）：**与 Go 基线一致 {len(okay)} / Go 漂移 {len(drift)} "
             f"/ 闸门拒跑 {len(gate)} / 未跑 {len(norun)}**（共 {len(recs)} 份作业）")
    L.append(f"- 旧读法留档（**已退出判据**）：vs 原版归零 {len(zero)} / 真差 {len(real)}"
             f"——变更前的数字原样留在 git 历史（`eae2fc1`），此处只作对照")
    L.append("")
    L.append("## 〇、判据变更声明（博士 2026-09-19 裁定：**基线改用 Go 重跑**）")
    L.append("")
    L.append("> 裁定原文：「走第一项，**过往和未来会新增的基线全部用 go 重跑**」。"
             "`frozenResDown`（冻结期间法抗 −15，原版标「未建模」、Go 实现了）**Go 保留**"
             "⇒ 这是**修正基线**，不是越界。**基线从「原版输出」换成「Go 输出」"
             "——原版退出基线地位。**")
    L.append(">")
    L.append("> 由此本表的判据换成：**Go 自身的基线漂移即红**（拿本轮 Go 的观测量对比 "
             "`fixtures/golden_go.json` 里钉住的 Go 数）。原版数字仍照跑、照留，"
             "但**只作历史参考列，不进判据**。")
    L.append(">")
    L.append("> ⚠ **深水 `hsex8_max` 那条「真差 1」随之作废**——它本就是 Go 对原版的差。"
             "但要说清一句：**该差异只是退出判据，并没有被解释**。"
             "`frozenResDown` 一条不足以解释「35 杀之差、8 名干员全灭」。"
             "它现在是一条**已知但未归因的 Go 侧行为**，与终端UI_2 那条 `t=81.1333` 的定位"
             "一样，保留为**独立说明**，不得读成「已确认正确」。")
    L.append("")
    L.append("### 〇之二、「与对方一致」类判据的逐列点名（参照物换人后必须重估）")
    L.append("")
    L.append("| 判据 | 原形态 | 参照物换人后 | 处置 |")
    L.append("| --- | --- | --- | --- |")
    L.append("| 本表「四项差」列 | Go 与原版逐项相等 | **原版已不是基线** | **降为历史参考列**；"
             "新判据＝Go 与 `golden_go.json` 的漂移 |")
    L.append("| `golden_go.py --check` | — | 它本就是 **Go 对 Go 金标准** | **保留为判据**"
             "（换成 Go 基线后语义反而更纯） |")
    L.append("| 门的第 2 项「闸门放行抽查」 | 问 Go 是否亲手跑（`go_fallbacks`） | "
             "不涉及「与对方一致」 | **保留** |")
    L.append("| 门的第 3 项 `check_battle`（816） | **直接 import `ak_tactic.battle` 断言原版的数**"
             "（24 处 `Verifier()` 零 `.run()`） | 原版已退出产品路径 | ⚠ **点名**：它测的是"
             "**原版引擎自身**，绿只说明「原版没退化」，**不说明 Go 如何**——"
             "是留作历史水位还是撤下，**等裁定** |")
    L.append("| 门的第 4 项 `check_verify`（71） | 裸 `Verifier().run()`，09-19 起主体已是 Go | "
             "主体 Go = 产品默认引擎 | **正当主体**（不必再写「不替原版背书」免责句） |")
    L.append("| `tools/parity_plan.py`（后端） | Go 对 Python 对拍 | 参照物没了 | **退出判据**，"
             "复职为**修复期诊断工具**（博士裁定 `4b124070`） |")
    L.append("| 门的第 5/6 项（盲区审计、能力清单） | 静态，不涉及参照物 | — | **保留** |")
    L.append("")
    L.append("### 〇之三、本树**无用例、当前无法验收**（照 `act31side_07` 先例逐条登记）")
    L.append("")
    L.append("| # | 事项 | 账面事实（本轮取证） | 状态 |")
    L.append("| --- | --- | --- | --- |")
    L.append("| 1 | `act31side_07` 关卡 | 本树判据集中**无该关夹具**（旁支树有，"
             "按通告 #5 二不得拿来凑数） | **本关当前无法验收** |")
    L.append("| 2 | `Schedule.diff`（`verify.py` 同时写两份排程） | 全仓**零调用点**，"
             "只有三处注释提到它 ⇒ 这件事**至今从未被证明过** | **已裁定「不接线」**（见下） |")
    L.append("| 3 | `Plan` 的 `retreats` / `skill_uses` / 装置 / 召唤 | `Plan` 支持 `retreats`，"
             "但两棵树 **25 个作业全部只有 `deploys` 键** ⇒ `Schedule` 五个列表里"
             "**有三个今天没有任何计划格式能填上** | **本树无用例，当前无法验收** |")
    L.append("| 3b | `Schedule.diff` 的**裁定结论**（承上表第 2 行） | 生产路径**不接**；"
             "`Schedule` 类保留；`sched_parity_check.py` 保留为**诊断工具形态**"
             "（零运行期代价、零 `sim` 依赖） | **已决（不是待办）** |")
    L.append("")
    L.append("> ⚠ **绝不把「四列全绿」读成「四条路没问题」**——那四列的绿是 `[] == []`。"
             "上面第 2/3 条正是「有实现、有测试、零调用点」那一类（记忆 `68a8a308` 同型）："
             "**判据集的缺口仍在**，工具修好了也不改变这一点。")
    L.append("")
    L.append("### 〇之四、**验过了、且证明确实是惰性**（与上面三条性质不同：不是「没验过」）")
    L.append("")
    L.append("| # | 事项 | 取证（终端UI_2 `cf5472b`） | 状态 |")
    L.append("| --- | --- | --- | --- |")
    L.append("| 4 | `devices`（规格输入字段） | **被读，但在一道门后面**：`simgo/spec.py:176` 的 "
             "`if getattr(inp, \"devices\", None) and not allow_devices:` 只在 `allow_devices=False` "
             "时才执行。实测：**门开时改 `inp.devices` ⇒ 规格 sha 不变；门关时改同一字段 ⇒ sha 变** | "
             "**该字段的可观测性取决于调用方开的门；敏感性扫描必须把门两边都跑** |")
    L.append("| 5 | `species_provider` | **上游喂得进、中游写了、下游没有，整链惰性**："
             "① 带计数哨兵跑 `hsex8_max` ⇒ **被调用 149 次**；② 哨兵返回 `'SENTINEL'` 后"
             "规格 sha 与真实值**完全相同**；③ 规格 JSON 里 `SENTINEL` 不存在，且 **`species` "
             "字样在整份规格里一次都没出现**（72 个敌人 / 19 个顶层键）。"
             "根因：`enemy_view.py:9` 把 `e.species` 写在**内存视图对象**上，"
             "`_spawn_spec` 那条序列化路径**没抄进规格 dict** ⇒ Go 永远收不到"
             "（Go 侧也无消费点） | **逐段都「被读过」，整链惰性** |")
    L.append("")
    L.append("> ⚠ 第 5 条钉死了一句方法论：**「字段被读了」与「字段送到了」第一次被分开证明**。"
             "**「被读过」是过程的证据，「送到了」是结果的证据**；两者之间隔着序列化，"
             "而**它不报错**。（同族：记忆 `af967c90` 闸门型规格字段、`9659644b` 注释被当证据。）")
    L.append("")
    L.append("> ⚠ 上面第 2 行的裁定与理由（终端UI_2 `59748cd`）：接线的**唯一理由**是「拿活 `sim` "
             "当参照」——基线改用 Go 之后**已消失**（`sim` 已无权威性）；代价是 `verify.py` "
             "每次要**同时写两份**、把 `sim` 依赖**永久留在生产路径上**（**越接越拆不掉**）；"
             "收益**零**（全仓零调用点 ⇒ 一次都没报过警）；替代品**已在跑**（`spec_sha` 金标准"
             "验的是「自己的规格有没有漂移」）。⇒ **生产路径不接；`Schedule` 类保留；"
             "`sched_parity_check.py` 保留为诊断工具形态（零运行期代价、零 `sim` 依赖）**。"
             "「两边同时写 → 只写 Schedule」属**结构性改动，收尾期不动**。")
    L.append("")
    L.append("### 〇之五、**「看不到变化」是一族假信号——真根因各不相同**（务必分开记）")
    L.append("")
    L.append("| 现象（改了值却没反应） | **真根因** | 出处 |")
    L.append("| --- | --- | --- |")
    L.append("| `devices` 改值、规格 `sha` 不变（门开时） | **门关了**——字段的可观测性取决于"
             "调用方开的门（门关时同一次改动 `sha` 会变） | `cf5472b` |")
    L.append("| `species_provider` 哨兵返回也没反应 | **没送下去**——上游喂得进、中游写了内存视图、"
             "序列化那条路没抄进规格 ⇒ **整链惰性** | `cf5472b` |")
    L.append("| `environment_difficulty` 换值 `stage_env` 一字不变 | **这一关用不到**"
             "（该关只有 NORMAL 一档）——**不是「没送」** | `59748cd` |")
    L.append("| `fps` 同型 | 同「这一关用不到」 | `59748cd` |")
    L.append("| `goal_cells` | **字段是活的，但 `from_sim` 永远传 `None`**"
             "——「从来没被填过」≠「不会被消费」 | `59748cd` |")
    L.append("")
    L.append("> ⚠ 配套判据（一并入账）：**凡「某字段改了没反应」，第一问是「它被读了吗」，"
             "第二问才是「读了有用吗」；而 `sha` 只能回答第二问。**"
             "分辨法＝**给消费者装计数器＋哨兵返回值**（只喂哨兵：被调用了多少次、"
             "送出去的规格里有没有它）。另：`cost_init`/`cost_max`/`cost_time`/`life` "
             "**根本不是 `SpecInputs` 的字段**（23 项里没有）⇒ 从来不在**这一段所讲的**范围内——"
             "这一段讲的是「**`env` 缺席时**由 `inp` 供上的那几项」，**实测 5 项**"
             "（`enemy_windup`/`fps`/`ranged_enemies`/`speed_scale`/`environment_difficulty`）。"
             "⚠ **别把这 5 项读成「`env` 里只有 5 项」**：`env` 承载并被 `spec.py` 消费的是 **8 项**"
             "（`stage_env.ENV_KEYS`；取用点 `spec.py:1197`／`:1206-1212`）——"
             "「8」与「5」量的是**两个不同的量**（2026-09-20 后端2 复核：本条原措辞「写成 8 是错的」"
             "按 8 项那一读是假的，账已撤回、措辞按此收窄）。")
    L.append("")
    L.append("### 〇之六、措辞更正：`goal_cells` **不是「死字段」**")
    L.append("")
    L.append("> 准确说法：**「字段是活的，但 `from_sim` 永远传 `None`」**"
             "（`spec.py:405` 左边真会消费——传 truthy 对象会让 `build_spec` 抛异常）。"
             "**「从来没有被填过」≠「不会被消费」**。本台账未按「死字段」记过；"
             "迁移表 §三 里若有此措辞，按这一句更正。")
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
    L.append("> ⚠ **【留档】深水用例 `hsex8_max` 的差异＝「成立」**（三台仪器一致，含我这台）。"
             "⚠ 这条记的是**裁定前**的认定过程；裁定后该差异**已退出判据**（见〇），"
             "但它的读法仍有效：这是**已知但未归因的 Go 侧行为**。"
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
    L.append("| 关卡 | 计划 | **判据：与 Go 基线** | 杀 | 漏 | 用时(s) | 伤害 | ①闸门（unsupported 原文） | ④机制族 | ⑤机制咬到了吗 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in recs:
        d = r.get("diff") or {}
        uns = "<br>".join(r.get("unsupported") or []) or "—"
        fam = "<br>".join(r.get("families") or []) or "—"
        fmt = (lambda v, n=0: "—" if v is None else f"{v:+.{n}f}")
        gv = r.get("go_verdict") or {}
        dr = r.get("go_baseline_drift")
        judge = ("✅ 一致" if r["state"].startswith("正常")
                 else ("❌ 漂移：" + ", ".join(f"{k} {v['基线']}→{v['现在']}"
                                              for k, v in (dr or {}).items())[:60]
                       if r["state"] == "Go 漂移" else r["state"]))
        L.append(f"| {r['stage']} | `{r['plan']}` | {judge} | "
                 f"{gv.get('kills', '—')} | {gv.get('leaks', '—')} | {gv.get('elapsed', '—')} | "
                 f"{gv.get('damage', '—')} | {uns} | {fam} | {r.get('touched', '—')} |")
    L.append("")
    L.append("**说明**：上表四数是 **Go 自己的数**（判据量）；右边的 `①闸门`／`④机制族`／"
             "`⑤机制咬到了吗` 三列都不依赖参照物，故**在换基线后依然成立**。"
             "旧读法（Go − 原版）的差值挪到下一节明细里，**只作历史参考**。")
    L.append("")
    _ok_act = [r for r in okay if r.get("touched") == "有动作"]
    _ok_lay = [r for r in okay if str(r.get("touched", "")).startswith("只落位")]
    _ok_none = [r for r in okay if r.get("touched") == "无机制"]
    L.append(f"**与 Go 基线一致的 {len(okay)} 份的构成**（为了记住记忆 8a1ec6d6"
             f"「无回归 ≠ 已验证」）：运行期有机制动作 **{len(_ok_act)}**、"
             f"只落位零事件 **{len(_ok_lay)}**、规格里也没有机制 **{len(_ok_none)}**。"
             f"后两类只能说「两条路算得一样」，**不能**说「该踩的机制被验过了」；"
             f"换成 Go 基线后这句话**更要紧**——因为「与基线一致」比「与两台引擎互等」更弱。")
    L.append("")
    L.append(f"**计数口径**：作业数按 `plan_path` 计、关卡数按 `stage` 去重"
             f"（此处 {len(recs)} 份作业 / {len({r.get('stage') for r in recs})} 个关卡）；"
             f"⚠ 别的台账按**作业条数**计数会虚高（同一关可能挂多份作业，实测 "
             f"`act31side_08` 曾出现 4 次）——**门判据必须是去重后的关卡数**。")
    L.append("")
    L.append("## 一之四、**改判据前后对照**（通告要求的「前后」两栏；变更前数字照旧留档）")
    L.append("")
    L.append("> 变更前判据＝「Go 与原版四项归零」（旧读法，留档于 `eae2fc1`）；"
             "变更后判据＝「Go 与 `fixtures/golden_go.json` 一致（漂移即红）」。")
    L.append("")
    L.append("| 关卡 | 计划 | 变更前（vs 原版） | 变更后（vs Go 基线） | Go 四数（判据量） "
             "| 原版四数（历史参考） | 判据换人后发生了什么 |")
    L.append("|---|---|---|---|---|---|---|")
    _flip = []
    for r in recs:
        old = str(r.get("state_py_ref") or "—")
        new = ("✅ 一致" if r["state"].startswith("正常")
               else ("❌ 漂移" if r["state"] == "Go 漂移" else r["state"]))
        gv, py = r.get("go_verdict") or {}, r.get("py") or {}
        if old.startswith("归零"):
            what = "数没变，只是参照物从原版换成 Go"
        elif old.startswith("真差"):
            what = "⚠ **由红转绿——换的是参照物，不是修好了什么**"
            _flip.append(r["plan"])
        else:
            what = f"（{old}）"
        L.append(f"| {r['stage']} | `{r['plan']}` | {old} | {new} | "
                 f"{gv.get('kills', '—')}/ {gv.get('leaks', '—')}/ {gv.get('elapsed', '—')}/"
                 f"{gv.get('damage', '—')} | {py.get('kills', '—')}/ {py.get('leaks', '—')}/"
                 f"{py.get('elapsed', '—')}/{py.get('damage', '—')} | {what} |")
    L.append("")
    if _flip:
        L.append(f"> ⚠ **判据换人后由红转绿的共 {len(_flip)} 份：{', '.join('`' + n + '`' for n in _flip)}**。"
                 "**它们一条也没有被修复**——变的只是「跟谁比」。"
                 "按裁定，原版退出基线地位，所以绿灯本身成立；"
                 "但**那条差异仍然存在、仍然未被归因**（见〇），"
                 "凡引用这盏绿灯的人必须同时引用这一句。")
        L.append("")
    L.append("## 二、逐关明细（① 能不能跑 / ② 判据 / ③ 差异指纹 / ④ 机制族）")
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
        L.append(f"- ② **历史参考列**（Go − 原版，**已退出判据**）：杀 {r['diff']['kills']:+d}、漏 {r['diff']['leaks']:+d}、"
                 f"用时 {r['diff']['elapsed']:+.4f}s、伤害 {r['diff']['damage']:+,.1f}")
        _dr = r.get("go_baseline_drift")
        L.append(f"- ②' **判据：与 Go 基线（`fixtures/golden_go.json`）**："
                 f"{'✅ 一致' if not _dr else '❌ 漂移 ' + str(_dr)}"
                 f"（基线存在：{r.get('go_baseline_present')}）")
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
    #: ⚠ **2026-09-20 修（后端2 发现、PM 转验收处置）**：本节原来**硬写**
    #: 「同一关…深水用例（如 8 人满练度 814 秒那条线）本台账**一份都没跑到**」，
    #: 而**同一份产物**的 §一 计划表（列着 `hsex8_max.json` 8 人）与 §二 逐关读数
    #: （`act31side_ex08` 那一节给了原版 83杀/1漏/814.0333s）**就跑到了它**
    #: ⇒ 同一份产物里同一件事两个口径（同族于 45fab0e7）。现在这句话**由本轮实跑数据决定**，
    #: 不再手写；**下游结论不变**：没跑到的仍是**别的树/别的练度**下的同类用例。
    _deep_ran = [r for r in recs
                 if r.get("plan") == "hsex8_max.json" and r.get("state") != "未跑"]
    _gap = (("★ **2026-09-20 更正（后端2 发现）**：本节原来写「深水用例…本台账"
             "**一份都没跑到**」——**与本产物 §一、§二 矛盾**：本轮**跑到了** 8 人满练度深水夹具"
             "`hsex8_max.json`（原版 83杀/1漏/814.0333s，见 §二 `act31side_ex08` 那一节）。"
             "**仍然没跑到的**是**别的树（如 `ak-tactic-head`）/别的练度**下的同类深水用例")
            if _deep_ran else
            ("同一关在别的树/别的练度下的**深水用例**（如 8 人满练度 814 秒那条线）"
             "本台账**一份都没跑到**"))
    L.append("- **覆盖缺口（最重要的一条）**：「归零」只说明**本树现有的这份作业**上两条路"
             "算得一样。" + _gap + " —— 记忆 8a1ec6d6「无回归 ≠ 已验证」说的就是这个。")
    L.append("- ③ 的「时刻」粒度到**事件级**（漏事件第几笔、用时差几帧），"
             "**没有**逐帧事件流比对（那要开两侧 trace 通道，属下一层）。")
    L.append(f"- 本轮实跑 **{len(recs)} 份计划**（§一 末表逐条列出；其中含 8 人满练度深水夹具"
             f"`hsex8_max.json`：**{'是' if _deep_ran else '否'}**）——**份数按实际跑到的计，不写死**；"
             f"怀黍离其它关卡（若作业不在树上）未覆盖。")
    L.append("- 闸门拒跑的关卡**没有**绕开闸门强跑——绕开需要改规格送法，不在我的权限内。")
    L.append("- 名册：本轮用 `roster_max_modelled`（满练度名册，落在旁支树）；换名册会换掉"
             "「能不能走到分歧点」，所以数字只在同名册间可比。")
    L.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
