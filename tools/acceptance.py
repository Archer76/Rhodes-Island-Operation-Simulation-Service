#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ak-tactic 验收入口：把散落的验收资产收成**一条命令**，顺序执行、末尾汇总。

    python tools\\acceptance.py              # 全套
    python tools\\acceptance.py --quick      # 跳过「闸门放行抽查」（省一趟金标准的量级）
    python tools\\acceptance.py --strict-parity   # 把「对拍入口缺失」算作判定项（默认只登记）

产物（固定文件名，便于逐轮比对）：

* `docs/acceptance-report.md`        人读报告：通过/失败 + 每项实测数字 + 与上次比对
* `docs/acceptance-baseline.json`    水位基线表：只在有解释（谁改的/为什么）时更新
* `out/acceptance/report-latest.json` 机器可读明细（out/ 已 gitignore）
* `out/acceptance/logs/*.log`        每项的原始输出（留痕，便于复核）

## 退出码

| 码 | 含义 |
|---|---|
| 0 | 全部通过 |
| 1 | 有失败或水位下降 |
| 2 | 有项**未跑**（跑不起来不许算通过） |

## 判定的七项（依项目经理通告 #2 第四节：金标准 / check_battle / 闸门审计 / 能力清单
## 为四项核心，另保留 check_verify（博士原始交办的第二条自检水位）与仪器、对拍登记）

| # | 项 | 判据 |
|---|---|---|
| 0 | 仪器自检 | 当前源码能构建出 Go 二进制；共享 exe 是否落后于源码（只报不判） |
| 1 | 金标准 | 与 `out/golden_go.json` 逐项一致（含 spec_sha），且基线文件未被改写 |
| 2 | 闸门放行抽查 | 每份计划 `go_runs≥1` 且 `go_fallbacks==0` 且 `spec_error` 为空 |
| 3 | 自检 check_battle | 无失败项，且项数不低于基线 |
| 4 | 自检 check_verify | 同上 |
| 5 | 闸门盲区审计 | 未登记=0、守卫失效=0，且 `--selftest` 反向守卫成立 |
| 6 | 闸门能力清单 | 三态进水位；「已定义未读」每条须能对上登记理由 |
| 7 | 对拍入口 | **已退役**，只登记不判定（通告 #2） |

## 三条纪律（都是本项目吃过的亏，写进代码而不是写进口号）

1. **先验仪器，再读数字**。第 0 项在 `out/acceptance/` 下用**当前源码**新构建一份私有
   `rios-sim`，并用 `RIOS_SIM_BIN` 指过去——共享的 `rios-sim/rios-sim.exe` 可能是旧的
   （曾实测：二进制 19:08 而源码 21:33）。⚠ 绝不覆盖共享二进制：别人在途的工作树被
   回写会造成假红（记忆 `ed34c994`）。
2. **绿要绿得起来，红要红得明白**。工具**没跑起来**（沙箱拒管道、tempfile 被拒、
   控制台编码）一律记「未跑」，不许写成通过；`golden_go.py` 的 `spec_error` 这条通道
   会把"工具坏了"和"代码坏了"压成同一种颜色（进度 3.39），所以这里把它单独判。
3. **比数量之前先确认工作树没被别人动过**。测前测后各取一次 HEAD / 脏文件清单 /
   热点文件哈希；期间变了就在报告里打「数字不对应单一版本」（进度里那 +3 归因不了
   的那次，就是缺这一步）。

⚠ 本工具**只读**：不跑不带 `--check` 的 `golden_go.py`（那会覆盖基线文件），
不改任何产品代码，只写 `docs/` 与 `out/` 下属于自己的验收工件。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
OUT = ROOT / "out" / "acceptance"
LOGS = OUT / "logs"
REPORT = ROOT / "docs" / "acceptance-report.md"
BASELINE = ROOT / "docs" / "acceptance-baseline.json"
CLAIMS = ROOT / "docs" / "acceptance-claims.md"
GOLDEN = ROOT / "out" / "golden_go.json"
SHARED_EXE = ROOT / "rios-sim" / "rios-sim.exe"
SESSION = "session-1a45cfee-9a65-4830-a327-03ac84285bfb"

#: 热点文件：这些一变，"同一套数字"就不再指同一件事。
HOT = [
    "ak_tactic/simgo/spec.py", "ak_tactic/simgo/skills.py",
    "ak_tactic/simgo/verifier.py", "ak_tactic/verify.py",
    "ak_tactic/battle/sim.py", "ak_tactic/battle/unit.py",
    "rios-sim/sim.go", "rios-sim/wire.go", "rios-sim/skill.go",
    "rios-sim/mech/mech.go", "rios-sim/mech/huai_shu_li.go",
]

PASS, FAIL, NORUN = "通过", "失败", "未跑"


# ---------------------------------------------------------------- 基础设施

def sha256_file(p: Path) -> str | None:
    if not p.exists():
        return None
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def run(cmd: list[str], *, cwd: Path | None = None, env_extra: dict | None = None,
        timeout: int = 1800) -> dict:
    """跑一条外部命令。**不吞异常**：超时与环境拒绝要能区分出来。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"      # 否则 GBK 控制台下打印 ⇒ 直接崩（实测过）
    env.setdefault("PYTHONUTF8", "1")
    env.update(env_extra or {})
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(cwd or ROOT), env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout)
        return {"rc": p.returncode, "out": p.stdout or "", "err": p.stderr or "",
                "seconds": time.time() - t0, "timeout": False}
    except subprocess.TimeoutExpired as e:
        return {"rc": None, "out": (e.stdout or "") if isinstance(e.stdout, str) else "",
                "err": f"超时（>{timeout}s）", "seconds": time.time() - t0,
                "timeout": True}
    except OSError as e:
        return {"rc": None, "out": "", "err": f"{type(e).__name__}: {e}",
                "seconds": time.time() - t0, "timeout": False}


def log_raw(key: str, r: dict) -> None:
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f"{key}.log").write_text(
        f"$ {' '.join(str(c) for c in r.get('cmd', []))}\n"
        f"rc={r['rc']}  seconds={r['seconds']:.1f}  超时={r['timeout']}\n"
        f"{'=' * 70}\n[stdout]\n{r['out']}\n{'-' * 70}\n[stderr]\n{r['err']}\n",
        encoding="utf-8")


def fingerprint() -> dict:
    head = run(["git", "rev-parse", "HEAD"], timeout=60)
    stat = run(["git", "status", "--porcelain"], timeout=60)
    files = {}
    for rel in HOT:
        p = ROOT / rel
        files[rel] = {
            "sha256": (sha256_file(p) or "")[:16],
            "mtime": p.stat().st_mtime if p.exists() else None,
        }
    return {
        "head": (head["out"].strip() or "(取不到)")[:12],
        "dirty_n": len([ln for ln in stat["out"].splitlines() if ln.strip()]),
        "dirty_sig": hashlib.sha256(stat["out"].encode("utf-8")).hexdigest()[:12],
        "files": files,
    }


def fingerprint_diff(a: dict, b: dict) -> list[str]:
    """两次指纹的差异（用于「测量期间工作树被改动」判定）。"""
    diffs: list[str] = []
    if a["head"] != b["head"]:
        diffs.append(f"HEAD {a['head']} → {b['head']}")
    if a["dirty_sig"] != b["dirty_sig"]:
        diffs.append(f"脏文件清单变化（{a['dirty_n']} → {b['dirty_n']} 条）")
    for rel, av in a["files"].items():
        bv = b["files"].get(rel, {})
        if av["sha256"] != bv.get("sha256"):
            diffs.append(f"{rel} 内容变化")
    return diffs


# ---------------------------------------------------------------- 第 0 项：仪器

def instrument(fresh_exe: Path) -> dict:
    """仪器自检：用当前源码新构建私有 Go 二进制，并核共享二进制是否陈旧。"""
    src = sorted((ROOT / "rios-sim").glob("**/*.go"))
    src_blob = "".join(f"{p.name}:{p.stat().st_size}:{int(p.stat().st_mtime)}"
                       for p in src)
    src_sig = hashlib.sha256(src_blob.encode()).hexdigest()[:8]
    target = fresh_exe.with_name(f"rios-sim-{src_sig}.exe")
    OUT.mkdir(parents=True, exist_ok=True)

    r = run(["go", "build", "-buildvcs=false", "-o", str(target), "."],
            cwd=ROOT / "rios-sim", timeout=600)
    r["cmd"] = ["go", "build", "-buildvcs=false", "-o", str(target), "."]
    log_raw("instrument-build", r)

    measured: dict = {"src_sig": src_sig, "build_rc": r["rc"], "build_s": round(r["seconds"], 1)}
    note_bits: list[str] = []

    if target.exists() and r["rc"] == 0:
        measured["fresh_exe"] = target.name
        measured["fresh_sha256"] = (sha256_file(target) or "")[:16]
        measured["fresh_bytes"] = target.stat().st_size
        status = PASS
    else:
        status = NORUN
        note_bits.append(f"私有构建失败：{(r['err'] or '').strip().splitlines()[-1][:160] if (r['err'] or '').strip() else '未知'}")
        #: 构建失败时退回共享二进制继续跑，但要在报告里说清楚用的是哪一个。
        measured["fresh_exe"] = None

    #: 共享二进制是否落后于源码——"直接拿它跑的人测的是旧引擎"。
    if SHARED_EXE.exists():
        newest = max(src, key=lambda p: p.stat().st_mtime)
        stale = SHARED_EXE.stat().st_mtime < newest.stat().st_mtime
        measured["shared_sha256"] = (sha256_file(SHARED_EXE) or "")[:16]
        measured["shared_mtime"] = time.strftime("%m-%d %H:%M:%S",
                                                 time.localtime(SHARED_EXE.stat().st_mtime))
        measured["shared_stale"] = stale
        if stale:
            behind = (newest.stat().st_mtime - SHARED_EXE.stat().st_mtime) / 60
            note_bits.append(
                f"共享 rios-sim.exe 落后于源码 {behind:.0f} 分钟（最新源码 {newest.name} "
                f"{time.strftime('%H:%M:%S', time.localtime(newest.stat().st_mtime))}）"
                f"——本门用私有构建，不覆盖它")
    else:
        measured["shared_sha256"] = None
        note_bits.append("共享 rios-sim.exe 不存在")

    return {
        "key": "instrument", "name": "仪器自检（Go 二进制）", "status": status,
        "measured": measured, "seconds": round(r["seconds"], 1),
        "judge": "当前源码能构建出 Go 引擎二进制（-buildvcs=false）",
        "note": "；".join(note_bits),
        "exe": str(target) if status == PASS else None,
    }


# ---------------------------------------------------------------- 第 1 项：金标准

GOLDEN_OK = re.compile(r"全部\s*(\d+)\s*份与基线逐项一致")
GOLDEN_BAD = re.compile(r"有\s*(\d+)\s*份不一致")
PER_PLAN_ERR = re.compile(r"^\s+plan-\S+\.json\s+❌\s+(?P<err>\S+)", re.M)


def golden_check(exe: str | None) -> dict:
    exe_sha = sha256_file(GOLDEN) or ""

    def once() -> dict:
        env = {"RIOS_SIM_BIN": exe} if exe else {}
        r = run([sys.executable, str(TOOLS / "golden_go.py"), "--check"], env_extra=env,
                timeout=3600)
        r["cmd"] = ["python", "tools/golden_go.py", "--check"]
        return r

    r = once()
    ok = GOLDEN_OK.search(r["out"])
    bad = GOLDEN_BAD.search(r["out"])
    errs = PER_PLAN_ERR.findall(r["out"])
    retried = None
    #: ⚠ **在途重构期的瞬时断裂**：实测过 `SpecInputs` 收口那半小时里，
    #: 金标准 17 份同报 `AttributeError: ... has no attribute 'skill_uses'`
    #: （`spec.py` 兜底分支正被改写），两分钟后再跑就是 17/17 全绿。
    #: 同一台仪器、同一份基线 —— 那不是"数字变了"，是**接缝当时是开的**。
    #: 所以：全部计划报同一种异常时，重跑一次再定性；重跑结果照样写进报告。
    if not ok and errs and len(set(errs)) == 1:
        first = r
        r = once()
        retried = (first, r)
        ok = GOLDEN_OK.search(r["out"])
        bad = GOLDEN_BAD.search(r["out"])
        errs = PER_PLAN_ERR.findall(r["out"])
    log_raw("golden", r)
    if retried is not None:
        log_raw("golden-first-attempt", retried[0])

    base = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    measured = {"baseline_plans": len(base),
                "baseline_sha256": exe_sha[:16] if exe_sha else None,
                "exe_used": Path(exe).name if exe else "(共享 rios-sim.exe)"}

    measured["consistent"] = int(ok.group(1)) if ok else None
    measured["mismatched"] = int(bad.group(1)) if bad else None
    measured["plan_errors"] = len(errs)
    if retried is not None:
        measured["first_attempt"] = (retried[0]["out"].strip().splitlines() or [""])[-1][:120]

    if ok and bad:
        status, note = FAIL, f"同一次输出里既有通过行又有 {bad.group(1)} 份不一致"
    elif ok:
        status = PASS
        note = (f"（⚠ 首次尝试曾 17 份同报 `{errs[0] if errs else '?'}`，重跑即一致"
                f"——在途重构的接缝，不是数字变了）" if retried is not None else "")
    elif errs and len(set(errs)) == 1:
        #: 同一种异常 ×全部计划 ⇒ 仪器/接口断了，不是代码的红。
        status = NORUN
        note = (f"⛔ 仪器跑不动：17 份全部同报 `{errs[0]}`（重跑一次仍如此）"
                f"——这是接缝断，不是判决变了。最小复现见 out/acceptance/logs/golden.log")
    elif bad:
        status = FAIL
        note = "与基线不一致，逐项差异见 out/acceptance/logs/golden.log"
    else:
        status = NORUN
        note = f"没有识别到判定行（rc={r['rc']}）：{(r['err'] or r['out'])[-200:]}"


    #: ⚠ 基线文件本身被改写 = 有人偷偷重设了标准。不报出来的话，下一次 --check 必绿。
    prev_sha = None
    if BASELINE.exists():
        try:
            prev_sha = json.loads(BASELINE.read_text(encoding="utf-8"))["water"].get(
                "golden_baseline_sha256")
        except Exception:                                        # noqa: BLE001
            prev_sha = None
    if prev_sha and exe_sha and exe_sha[:16] != prev_sha[:16]:
        status = FAIL
        note = (note + "；" if note else "") + (
            f"⛔ 金标准基线文件 out/golden_go.json 已被改写"
            f"（{prev_sha[:16]} → {exe_sha[:16]}）——须解释谁改的、为什么")
    measured["baseline_changed"] = bool(prev_sha and exe_sha and exe_sha[:16] != prev_sha[:16])

    return {"key": "golden", "name": "金标准（规格哈希 + 判决四数）", "status": status,
            "measured": measured, "seconds": round(r["seconds"], 1),
            "judge": "与 out/golden_go.json 逐项一致（含 spec_sha），且基线文件未被改写",
            "note": note}


# ---------------------------------------------------------------- 第 2 项：闸门放行
#:
#: ⚠ 为什么要单独一项：`golden_go.py --check` **不打印** `go_fallbacks`。
#: 闸门不放行时 GoVerifier 会静默代跑原版（记忆 ed34c994），那时"一致"是假绿。
#: 这里复用 golden_go 的 `SpecCapture`（只 import，不改它的文件），把这三个量读出来。

def gate_probe(exe: str | None, sample: int | None) -> dict:
    sys.path.insert(0, str(TOOLS))
    sys.path.insert(0, str(ROOT))
    try:
        import golden_go as G
        from ak_tactic.plan import Plan, Roster
    except Exception as e:                                       # noqa: BLE001
        return {"key": "gate", "name": "闸门放行抽查（go_fallbacks）", "status": NORUN,
                "measured": {}, "seconds": 0.0,
                "judge": "每份计划 go_runs≥1、go_fallbacks==0、spec_error 为空",
                "note": f"import 失败：{type(e).__name__}: {e}"}
    if exe:
        os.environ["RIOS_SIM_BIN"] = exe

    try:
        roster_file = G._find("roster_max_modelled")
        plans = sorted((ROOT / "out").glob("plan-*.json"))
        if sample:
            plans = plans[:sample]
    except Exception as e:                                       # noqa: BLE001
        return {"key": "gate", "name": "闸门放行抽查（go_fallbacks）", "status": NORUN,
                "measured": {}, "seconds": 0.0,
                "judge": "每份计划 go_runs≥1、go_fallbacks==0、spec_error 为空",
                "note": f"夹具找不到：{type(e).__name__}: {e}"}

    base = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    roster = Roster.from_json(roster_file)
    rows, bad_fb, bad_spec, drift = [], [], [], []
    t0 = time.time()
    for p in plans:
        try:
            v = G.SpecCapture()
            r = v.run(Plan.from_dict(json.loads(p.read_text(encoding="utf-8-sig"))),
                      roster=roster)
            row = {"plan": p.name, "kills": r.kills, "leaks": r.leaks,
                   "elapsed": round(float(r.elapsed), 4),
                   "damage": round(float(r.damage), 1),
                   "go_runs": getattr(v, "go_runs", None),
                   "go_fallbacks": getattr(v, "go_fallbacks", None),
                   "spec_error": v.spec_error,
                   "spec_sha": G.canonical_sha(v.spec) if v.spec is not None else None}
        except Exception as e:                                   # noqa: BLE001
            row = {"plan": p.name, "error": f"{type(e).__name__}: {e}"}
        rows.append(row)
        if row.get("error"):
            bad_spec.append(f"{p.name}: {row['error'][:60]}")
            continue
        if not row["go_runs"] or row["go_fallbacks"]:
            bad_fb.append(f"{p.name}: go_runs={row['go_runs']} "
                          f"go_fallbacks={row['go_fallbacks']}")
        if row["spec_error"]:
            bad_spec.append(f"{p.name}: {row['spec_error'][:60]}")
        b = base.get(p.name)
        if b and any(b.get(k) != row.get(k) for k in
                     ("kills", "leaks", "elapsed", "damage", "spec_sha")):
            drift.append(p.name)

    measured = {"plans": len(rows), "sampled": bool(sample),
                "go_fallbacks_total": sum((r.get("go_fallbacks") or 0) for r in rows),
                "spec_error_n": len(bad_spec), "baseline_drift": len(drift),
                "rows": rows}
    if bad_fb or bad_spec or drift:
        status = FAIL
        note = "；".join(x for x in [
            ("⛔ 闸门不放行/退回原版：" + "; ".join(bad_fb[:3])) if bad_fb else "",
            ("⛔ 规格抄不到：" + "; ".join(bad_spec[:3])) if bad_spec else "",
            ("⛔ 与基线四数/spec_sha 有差：" + ", ".join(drift[:5])) if drift else "",
        ] if x)
    else:
        status, note = PASS, ("（抽样）" if sample else "")
    return {"key": "gate", "name": "闸门放行抽查（go_fallbacks）", "status": status,
            "measured": measured, "seconds": round(time.time() - t0, 1),
            "judge": "每份计划 go_runs≥1、go_fallbacks==0、spec_error 为空、与基线四数一致",
            "note": note}


# ---------------------------------------------------------------- 第 3/4 项：自检水位

CB_OK = re.compile(r"通过\s*(\d+)\s*项")
CB_BAD = re.compile(r"失败\s*(\d+)\s*项")
TRACEBACK = re.compile(r"^(?P<kind>\w*(?:Error|Exception)):\s*(?P<msg>.+)$", re.M)


def water_item(key: str, name: str, script: str, baseline_key: str,
               timeout: int = 3600) -> dict:
    r = run([sys.executable, str(TOOLS / script)], timeout=timeout)
    r["cmd"] = ["python", f"tools/{script}"]
    log_raw(key, r)
    ok, bad = CB_OK.search(r["out"]), CB_BAD.search(r["out"])
    measured = {"passed": int(ok.group(1)) if ok else None,
                "failed": int(bad.group(1)) if bad else 0,
                "rc": r["rc"]}

    if ok and (not bad or int(bad.group(1)) == 0):
        status, note = PASS, ""
    elif ok and bad:
        status = FAIL
        note = f"套件自报失败 {bad.group(1)} 项，见 out/acceptance/logs/{key}.log"
    else:
        tb = TRACEBACK.findall(r["err"] or r["out"])
        status = NORUN
        note = ("套件没跑完（没有判定行）："
                + (f"{tb[-1][0]}: {tb[-1][1][:120]}" if tb
                   else f"rc={r['rc']}，{(r['err'] or r['out'])[-160:].strip()}"))
    return {"key": key, "name": name, "status": status, "measured": measured,
            "seconds": round(r["seconds"], 1),
            "judge": "套件全过（无失败项），且项数不低于基线",
            "note": note, "_baseline_key": baseline_key}


# ---------------------------------------------------------------- 第 5 项：闸门盲区审计

AUDIT_LINE = re.compile(r"已登记且守卫成立：(\d+) 条；\*\*未登记：(\d+)\*\*；"
                        r"\*\*守卫失效：(\d+)\*\*")


def audit_item() -> dict:
    def once() -> dict:
        rr = run([sys.executable, str(TOOLS / "audit_gate_blindspot.py"), "--all"],
                 timeout=600)
        rr["cmd"] = ["python", "tools/audit_gate_blindspot.py", "--all"]
        return rr

    r = once()
    retried = None
    #: ⚠ 实测踩过：审计要读 `ak_tactic/activity.py`，而那一刻后端会话正在写它
    #: ⇒ `PermissionError: [Errno 13]`（Windows 写独占），**不是审计发现了盲区**。
    #: 这类"别人正在写文件"的瞬时失败重跑一次就好；仍失败才算未跑。
    if r["rc"] != 0 and "PermissionError" in (r["err"] or ""):
        first = r
        r = once()
        retried = (first, r)
    log_raw("audit", r)
    if retried is not None:
        log_raw("audit-first-attempt", retried[0])
    s = run([sys.executable, str(TOOLS / "audit_gate_blindspot.py"), "--selftest"],
            timeout=300)
    s["cmd"] = ["python", "tools/audit_gate_blindspot.py", "--selftest"]
    log_raw("audit-selftest", s)

    m = AUDIT_LINE.search(r["out"])
    active = len(re.findall(r"^\s+· \w+", r["out"], re.M))
    known = None
    try:
        sys.path.insert(0, str(TOOLS))
        import audit_gate_blindspot as A                          # noqa: PLC0415
        known = len(A.KNOWN)
    except Exception:                                            # noqa: BLE001
        known = None
    measured = {"registered_known": known, "registered_active": active,
                "unregistered": int(m.group(2)) if m else None,
                "guard_broken": int(m.group(3)) if m else None,
                "selftest_ok": "✅" in s["out"]}

    if not m:
        tb = TRACEBACK.findall(r["err"] or "")
        status = NORUN
        note = ("审计没跑完（没有判定行）："
                + (f"{tb[-1][0]}: {tb[-1][1][:120]}" if tb else f"rc={r['rc']}"))
        if retried is not None:
            note = "⚠ 首次尝试撞上别人正在写文件（" + note + "），重跑仍失败"
    elif measured["unregistered"] or measured["guard_broken"]:
        status = FAIL
        note = f"未登记 {measured['unregistered']} 条 / 守卫失效 {measured['guard_broken']} 条"
    elif not measured["selftest_ok"]:
        status = FAIL
        note = "⛔ 反向守卫自检没过：这台仪器本身不可信，它的绿不能算绿"
    else:
        status = PASS
        note = (f"（⚠ 首次尝试被 `activity.py` 的写锁撞成 PermissionError，重跑即过）"
                if retried is not None else "")
    return {"key": "audit", "name": "闸门盲区审计", "status": status,
            "measured": measured, "seconds": round(r["seconds"] + s["seconds"], 1),
            "judge": "未登记=0 且 守卫失效=0，且 --selftest 反向守卫成立",
            "note": note, "_baseline_key": "audit"}


# ---------------------------------------------------------------- 第 6 项：闸门能力清单
#:
#: 依项目经理通告 #2 第一节「对拍项退役」：不再用逐关对拍做验收手段，
#: 第四项改成**闸门条目的能力清单**（`tools/gate_inventory.py`，静态、不需要作业）。
#: 三态里「已定义未读」是最危险的一态（字段有、没人读，闸门却以为落地了）。

INV_LINE = re.compile(r"合计：已读取 (\d+) / 已定义未读 (\d+) / 未送 (\d+)")
INV_UNREAD = re.compile(r"\[\*\*已定义未读\*\*\]\s+(\S+)")

#: 「已定义未读」每条都必须有登记理由——照 `audit_gate_blindspot.KNOWN` 的做法，
#: 理由要能被下一轮复核。没有理由的就是新缺口 ⇒ 红。
KNOWN_DEFINED_UNREAD = {
    "积雪": "已登记：`build_spec` 在部署**之前**算，而雪层是部署时才建的 ⇒ 闸门那一刻"
            "永远是空（记忆 9b14e2c4；`audit_gate_blindspot` 亦登记 `snow_fields`）。"
            "判据：不是「没人读」，是「读的时机早于建」",
}


def capability_item() -> dict:
    tool = TOOLS / "gate_inventory.py"
    if not tool.exists():
        return {"key": "capability", "name": "闸门能力清单（static）", "status": NORUN,
                "measured": {}, "seconds": 0.0,
                "judge": "闸门条目三态盘点：已读取 / 已定义未读（须有登记理由）/ 未送",
                "note": f"工具不存在：{tool.name}（由后端会话维护）"}
    r = run([sys.executable, str(tool)], timeout=600)
    r["cmd"] = ["python", "tools/gate_inventory.py"]
    log_raw("capability", r)
    m = INV_LINE.search(r["out"])
    unread = INV_UNREAD.findall(r["out"])
    if not m:
        return {"key": "capability", "name": "闸门能力清单（static）", "status": NORUN,
                "measured": {}, "seconds": round(r["seconds"], 1),
                "judge": "闸门条目三态盘点：已读取 / 已定义未读（须有登记理由）/ 未送",
                "note": f"没有识别到合计行（rc={r['rc']}）：{(r['err'] or r['out'])[-160:]}"}
    measured = {"read": int(m.group(1)), "defined_unread": int(m.group(2)),
                "unsent": int(m.group(3)), "unread_names": unread,
                "total": int(m.group(1)) + int(m.group(2)) + int(m.group(3))}
    unexplained = [n for n in unread if n not in KNOWN_DEFINED_UNREAD]
    measured["unexplained_unread"] = unexplained
    if unexplained:
        status = FAIL
        note = f"⛔ 「已定义未读」里有未登记条目：{unexplained}"
    else:
        status = PASS
        note = ("；".join(f"{n}：{KNOWN_DEFINED_UNREAD[n]}" for n in unread)
                if unread else "")
    return {"key": "capability", "name": "闸门能力清单（static）", "status": status,
            "measured": measured, "seconds": round(r["seconds"], 1),
            "judge": "未送/已定义未读的条目数进水位；「已定义未读」每条须能对上登记理由",
            "note": note, "_baseline_key": "capability"}


def parity_retired_item() -> dict:
    """对拍项：**已按通告 #2 退役**，只登记、不判定、不为它写新仪器。"""
    tool = TOOLS / "parity_plan.py"
    importers = []
    for p in sorted(TOOLS.glob("*.py")):
        try:
            if "parity_plan" in p.read_text(encoding="utf-8", errors="replace"):
                importers.append(p.name)
        except OSError:
            pass
    measured = {"tool_exists": tool.exists(),
                "tracked": None,
                "importers": len([n for n in importers if n != "parity_plan.py"])}
    return {"key": "parity", "name": "对拍入口（已退役·仅登记）", "status": NORUN,
            "measured": measured, "seconds": 0.0,
            "judge": "不作为验收手段（通告 #2 裁定；博士 2026-09-19 19:56 弃用 Python 模拟器）",
            "note": "对拍项退役：不作验收手段、不修 `sweep_hsl_parity` 那条路、不为它写新仪器。"
                    "「8 关闸门拦下 / 3 关真差」改读**能力清单**（见上一项）。"
                    "历史水位（不可复算）：怀黍离 20 关 = 9 关四项归零、8 关被闸门拦下、"
                    "3 关真差根因未定",
            "blocking": False}



# ---------------------------------------------------------------- 基线比对

def load_baseline() -> dict:
    if not BASELINE.exists():
        return {}
    try:
        return json.loads(BASELINE.read_text(encoding="utf-8"))
    except Exception:                                            # noqa: BLE001
        return {}


def current_water(items: list[dict]) -> dict:
    by = {i["key"]: i for i in items}
    g, cb, cv, au = by["golden"]["measured"], by["battle"]["measured"], \
        by["verify"]["measured"], by["audit"]["measured"]
    cap = by["capability"]["measured"] if "capability" in by else {}
    return {
        "golden_plans": g.get("baseline_plans"),
        "golden_consistent": g.get("consistent"),
        "golden_baseline_sha256": g.get("baseline_sha256"),
        "check_battle_passed": cb.get("passed"),
        "check_verify_passed": cv.get("passed"),
        "audit_registered_known": au.get("registered_known"),
        "audit_registered_active": au.get("registered_active"),
        "audit_unregistered": au.get("unregistered"),
        "audit_guard_broken": au.get("guard_broken"),
        "cap_read": cap.get("read"),
        "cap_defined_unread": cap.get("defined_unread"),
        "cap_unsent": cap.get("unsent"),
    }


#: 每个水位的方向：+1 = 越大越好，-1 = 越小越好。方向搞反，"回归"就报不出来。
#:
#: ⚠ `audit_registered_active` **不进水位**：它是我从审计输出里数出来的**打印行数**
#: （实测 7 → 2 只因为该工具的展示口径变了，未登记/守卫失效始终是 0）。
#: 拿"展示细节"当水位，会把别人的排版改动报成回归——那正是本项目最贵的那类假信号。
DIRECTION = {
    "golden_consistent": +1,
    "check_battle_passed": +1,
    "check_verify_passed": +1,
    "cap_read": +1,
    "audit_unregistered": -1,
    "audit_guard_broken": -1,
    "cap_defined_unread": -1,
    "cap_unsent": -1,
}


def worse(direction: int, was, now) -> bool:
    return (now < was) if direction > 0 else (now > was)


def compare_water(now: dict, base: dict) -> tuple[list[dict], list[dict]]:
    """返回 (回归项, 变化项)。基线不存在时两边都空。

    ⚠ 方向按 `DIRECTION` 走：`cap_unsent`（未送）**降**才是进步，
    若照 `HIGHER_IS_BETTER` 一刀切，闸门能力清单的回归会被读成改善。
    """
    old = (base or {}).get("water") or {}
    if not old:
        return [], []
    drops, changes = [], []
    for k, v in now.items():
        d = DIRECTION.get(k)
        o = old.get(k)
        if d is None or o is None or v is None or o == v:
            continue
        row = {"key": k, "was": o, "now": v,
               "dir": "越好" if d > 0 else "越少越好"}
        (drops if worse(d, o, v) else changes).append(row)
    return drops, changes



def explained(base: dict, key: str, value) -> str | None:
    """上升/变化能不能解释：历史里有同值且带 why 的记录就算已解释。"""
    for h in (base.get("history") or []):
        if (h.get("water") or {}).get(key) == value and (h.get("why") or "").strip():
            return f"{h.get('at', '?')} {h.get('by', '?')}：{h['why']}"
    return None


# ---------------------------------------------------------------- 报告

def fmt(v) -> str:
    return "—" if v is None else (f"{v:,}" if isinstance(v, int) else str(v))


def write_report(items: list[dict], drops: list[dict], changes: list[dict],
                 base: dict, fp0: dict, fp1: dict, args, seconds: float) -> int:
    fails = [i for i in items if i["status"] == FAIL]
    noruns = [i for i in items if i["status"] == NORUN]
    blocking_norun = [i for i in noruns if i.get("blocking", True)]
    rc = 1 if (fails or drops) else (2 if blocking_norun else 0)

    now = current_water(items)
    old = (base or {}).get("water") or {}
    drift = fingerprint_diff(fp0, fp1)
    L: list[str] = []
    L.append("# ak-tactic 验收报告")
    L.append("")
    L.append(f"- 生成时间：{time.strftime('%Y-%m-%d %H:%M:%S')}")
    L.append(f"- 执行者：验收与守卫会话 `{SESSION}`"
             f"（命令：`python tools/acceptance.py{' --quick' if args.quick else ''}`）")
    L.append(f"- 判定：**通过 {len(items) - len(fails) - len(noruns)} / 失败 {len(fails)} / "
             f"未跑 {len(noruns)}**，退出码 **{rc}**，总耗时 {seconds / 60:.1f} 分钟")
    L.append(f"- 测量对象：HEAD `{fp1['head']}`，脏文件 {fp1['dirty_n']} 条")
    if drift:
        L.append("")
        L.append("> ⚠ **测量期间工作树被改动**：" + "；".join(drift)
                 + " ⇒ 本轮数字不对应单一版本，跨轮次比数量之前必须重跑。")
    L.append("")
    L.append("## 一、逐项实测")
    L.append("")
    L.append("| # | 项 | 状态 | 本轮实测 | 上次基线 | 判据 |")
    L.append("|---|---|---|---|---|---|")
    for i, it in enumerate(items, 1):
        m = it["measured"]
        if it["key"] == "golden":
            cur, prev = (f"一致 {fmt(m.get('consistent'))}/{fmt(m.get('baseline_plans'))} 份"
                         f"（spec_sha 含在内）"), fmt(old.get("golden_consistent"))
        elif it["key"] == "gate":
            cur = (f"{fmt(m.get('plans'))} 份 go_fallbacks={fmt(m.get('go_fallbacks_total'))}，"
                   f"spec_error {fmt(m.get('spec_error_n'))}，与基线有差 {fmt(m.get('baseline_drift'))}")
            prev = "—"
        elif it["key"] in ("battle", "verify"):
            cur = f"通过 {fmt(m.get('passed'))} 项，失败 {fmt(m.get('failed'))}"
            prev = fmt(old.get("check_battle_passed" if it["key"] == "battle"
                               else "check_verify_passed"))
        elif it["key"] == "instrument":
            cur = (f"私有构建 `{m.get('fresh_exe') or '失败'}`（`{m.get('fresh_sha256')}`）；"
                   f"共享 exe 落后源码={m.get('shared_stale')}")
            prev = "—"
        elif it["key"] == "audit":
            cur = (f"登记 {fmt(m.get('registered_known'))} 条（本轮扫出 "
                   f"{fmt(m.get('registered_active'))}），未登记 {fmt(m.get('unregistered'))}，"
                   f"守卫失效 {fmt(m.get('guard_broken'))}，自检{'过' if m.get('selftest_ok') else '不过'}")
            prev = f"未登记 {fmt(old.get('audit_unregistered'))}"
        elif it["key"] == "capability":
            cur = (f"已读取 {fmt(m.get('read'))} / 已定义未读 {fmt(m.get('defined_unread'))} / "
                   f"未送 {fmt(m.get('unsent'))}"
                   + (f"（未读：{'、'.join(m.get('unread_names') or [])}）"
                      if m.get("unread_names") else ""))
            prev = (f"未送 {fmt(old.get('cap_unsent'))} / 未读 "
                    f"{fmt(old.get('cap_defined_unread'))}")
        elif it["key"] == "parity":
            cur = "退役（仅登记）"
            prev = "—"
        else:
            cur = "见下方未跑说明"
            prev = "—"
        L.append(f"| {i} | {it['name']} | {it['status']} | {cur} | {prev} | {it['judge']} |")
    L.append("")
    L.append("## 二、仪器身份（先验仪器，再谈结论）")
    L.append("")
    ins = next(i for i in items if i["key"] == "instrument")["measured"]
    L.append(f"- 私有构建（本门使用）：`{ins.get('fresh_exe') or '（构建失败）'}` "
             f"sha256 `{ins.get('fresh_sha256')}`，{fmt(ins.get('fresh_bytes'))} 字节")
    L.append(f"- 共享二进制：sha256 `{ins.get('shared_sha256')}`，构建于 "
             f"{ins.get('shared_mtime')}，落后于源码：**{ins.get('shared_stale')}**")
    L.append(f"- 规则：本门一律用私有构建（`RIOS_SIM_BIN` 指过去），**绝不覆盖共享二进制**"
             f"——回写共享树会造成假红。")
    L.append("")
    L.append("## 三、版本指纹（本轮数字属于哪一版）")
    L.append("")
    L.append("| 文件 | sha256 前 16 位 |")
    L.append("|---|---|")
    for rel, v in fp1["files"].items():
        L.append(f"| `{rel}` | `{v['sha256']}` |")
    L.append("")
    L.append("## 四、水位比对（与上一次报告比）")
    L.append("")
    if not old:
        L.append("- 尚无基线（首次运行）。本轮实测值可用 `--update-baseline --why ...` 固化为基线。")
    if drops:
        L.append("⛔ **水位下降（回归）**：")
        for d in drops:
            L.append(f"- `{d['key']}`：{d['was']} → **{d['now']}**")
    if changes:
        L.append("")
        L.append("水位变化（须能解释是谁改的、为什么）：")
        for c in changes:
            why = explained(base, c["key"], c["now"])
            L.append(f"- `{c['key']}`：{c['was']} → {c['now']} —— "
                     + (f"已解释：{why}" if why else "⚠ **无解释**，须查明是谁改的、为什么"))
    if old and not drops and not changes:
        L.append("- 无下降、无变化。")
    L.append("")
    L.append("## 五、未跑项与原因（未跑 ≠ 通过）")
    L.append("")
    if not noruns:
        L.append("- 无")
    for it in noruns:
        tag = "" if it.get("blocking", True) else "（已登记，默认不参与判定）"
        L.append(f"- **{it['name']}**{tag}：{it['note'] or '未说明'}")
    L.append("")
    L.append("## 六、独立复核台账（「它说的」vs「我测的」）")
    L.append("")
    if CLAIMS.exists():
        #: 台账文件自带一级标题，嵌进来要降一级，免得报告里出现两个 H1。
        body = "\n".join(
            ("#" + ln) if ln.startswith("#") else ln
            for ln in CLAIMS.read_text(encoding="utf-8").strip().splitlines())
        L.append(body)
    else:
        L.append("- 尚无记录。每有会话广播某阶段完成，独立复跑相关验收项后登记于此。")
    L.append("")
    L.append("## 七、水位历史")
    L.append("")
    hist = (base.get("history") or [])[-8:]
    if not hist:
        L.append("- 本轮为首轮，基线表由本轮实测建立。")
    for h in hist:
        L.append(f"- {h.get('at')} `{h.get('head')}` {h.get('by')}：{h.get('why')}")
    L.append("")
    L.append("## 八、本门**不覆盖**什么（别把绿读成全绿）")
    L.append("")
    L.append("- **逐关对拍**：已按项目经理通告 #2 **退役**（博士 2026-09-19 19:56 弃用"
             "Python 模拟器），本门不再把它当验收手段、不为它写新仪器；"
             "「8 关闸门拦下 / 3 关真差」改读**闸门能力清单**（第六项）。"
             "⚠ 已入库的 `tools/parity_plan.py`（4fe187b）实测**跑不起来**"
             "（`GoCapture._run_other_engine` 不接受 `schedule`，见台账）——"
             "谁要引它当证据，先自己跑通。")
    L.append("- **17 份计划没走到的路径**：金标准只覆盖这些计划上真跑出来的路径；"
             "没被走到的分支，它不说话——**覆盖不到机制的判据只会沉默，不会否证**。"
             "所以金标准绿 ≠ 所有机制都对。")
    L.append("- **保真**（两台引擎一起错）：本门问的是「Go 与基线一致」，"
             "**不问**「像不像真游戏」。`UNMODELLED_ENEMY_ABILITIES` 那 5 条属保真课题，"
             "不在本门判定内（裁定 `77fce667` 设的门槛只在一致性这一层）。")
    L.append("- **未跑到的自检分支**：`check_battle` / `check_verify` 报的是它们自己"
             "声明的项数；项数没降只说明「没变少」，不等于「新加的路径被考到了」。")
    L.append("")
    L.append("## 九、怎么用这条门")
    L.append("")
    L.append("```")
    L.append("python tools\\acceptance.py            # 全套（金标准两趟 + 自检两项 + 审计 + 能力清单）")
    L.append("python tools\\acceptance.py --quick    # 省掉「闸门放行抽查」那一趟（退出码记 2）")
    L.append("python tools\\acceptance.py --update-baseline --by <会话> --why \"<为什么>\"")
    L.append("```")
    L.append("")
    L.append("⚠ 三条铁律：① 未跑不许写成通过；② 水位降了就是红；③ 比数量前先确认工作树"
             "没被别人动过——报告头部的指纹差异段就是干这个的。")
    L.append("")

    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")

    detail = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": fp1["head"],
              "rc": rc, "water": now, "items": items,
              "fingerprint_before": fp0, "fingerprint_after": fp1, "drift": drift}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "report-latest.json").write_text(
        json.dumps(detail, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return rc


def update_baseline(now: dict, base: dict, by: str, why: str, head: str) -> None:
    hist = list(base.get("history") or [])
    hist.append({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "head": head,
                 "by": by, "why": why, "water": now})
    doc = base or {}
    doc["established"] = doc.get("established") or {
        "at": time.strftime("%Y-%m-%d %H:%M:%S"), "by": by,
        "head": head, "reason": why}
    doc["water"] = now
    doc["history"] = hist
    doc["rule"] = ("水位不写死：本轮实测值写在这里，下一轮拿实测值比它。"
                   "降了（HIGHER_IS_BETTER 那几项）= 回归，必须红；"
                   "上升或变化须在 history 里留下 who/why，否则报告标『无解释』。")
    BASELINE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE.write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- main

def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:                                            # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(description="ak-tactic 验收入口")
    ap.add_argument("--quick", action="store_true",
                    help="跳过「闸门放行抽查」（省一趟金标准的量级）")
    ap.add_argument("--sample", type=int, default=None,
                    help="闸门放行抽查只跑前 N 份计划（默认全部）")
    ap.add_argument("--update-baseline", action="store_true")
    ap.add_argument("--force-baseline", action="store_true",
                    help="这一轮不是全绿时也强行覆盖基线（会留下 history 记录）")
    ap.add_argument("--by", default=SESSION)
    ap.add_argument("--why", default="")
    args = ap.parse_args()

    t0 = time.time()
    fp0 = fingerprint()
    print(f"ak-tactic 验收入口　测量对象 HEAD {fp0['head']}"
          f"（脏文件 {fp0['dirty_n']} 条）")
    print("=" * 78)

    items: list[dict] = []
    fresh = OUT / "rios-sim-fresh.exe"
    ins = instrument(fresh)
    items.append(ins)
    exe = ins.get("exe")
    print(f"[0] 仪器：私有构建 {'✅ ' + Path(exe).name if exe else '❌ 失败'}"
          f"；共享二进制落后于源码={ins['measured'].get('shared_stale')}")

    it = golden_check(exe)
    items.append(it)
    print(f"[1] 金标准：{it['status']}　一致 {it['measured'].get('consistent')}/"
          f"{it['measured'].get('baseline_plans')}　{it['seconds']:.0f}s"
          + (f"　{it['note']}" if it["note"] else ""))

    if args.quick:
        items.append({"key": "gate", "name": "闸门放行抽查（go_fallbacks）",
                      "status": NORUN, "measured": {}, "seconds": 0.0,
                      "judge": "每份计划 go_runs≥1、go_fallbacks==0、spec_error 为空",
                      "note": "⛔ --quick 跳过了这一项 ⇒ 这次**不是完整的门**，"
                              "退出码按「未跑」记 2", "blocking": True})
        print("[2] 闸门放行抽查：未跑（--quick）")
    else:
        it = gate_probe(exe, args.sample)
        items.append(it)
        print(f"[2] 闸门放行抽查：{it['status']}　"
              f"{it['measured'].get('plans', 0)} 份　go_fallbacks="
              f"{it['measured'].get('go_fallbacks_total')}　{it['seconds']:.0f}s"
              + (f"　{it['note']}" if it["note"] else ""))

    for key, name, script, bkey in (
            ("battle", "自检 check_battle（战斗与技能回归）", "check_battle.py",
             "check_battle_passed"),
            ("verify", "自检 check_verify（验证器）", "check_verify.py",
             "check_verify_passed")):
        it = water_item(key, name, script, bkey)
        items.append(it)
        print(f"[{len(items) - 1}] {name}：{it['status']}　通过 "
              f"{it['measured'].get('passed')} 项　{it['seconds']:.0f}s"
              + (f"　{it['note']}" if it["note"] else ""))

    it = audit_item()
    items.append(it)
    print(f"[5] 闸门盲区审计：{it['status']}　未登记 "
          f"{it['measured'].get('unregistered')}　守卫失效 "
          f"{it['measured'].get('guard_broken')}　自检="
          f"{it['measured'].get('selftest_ok')}")

    it = capability_item()
    items.append(it)
    print(f"[6] 闸门能力清单：{it['status']}　已读取 {it['measured'].get('read')} / "
          f"已定义未读 {it['measured'].get('defined_unread')} / "
          f"未送 {it['measured'].get('unsent')}")

    it = parity_retired_item()
    items.append(it)
    print(f"[7] 对拍入口：{it['status']}（已退役，仅登记）")

    fp1 = fingerprint()
    base = load_baseline()
    now = current_water(items)
    drops, changes = compare_water(now, base)

    #: ⛔ **基线不许由红的那一轮建立**。本轮实测踩到过：在途重构让金标准瞬时断裂，
    #: 我带着 `--update-baseline` 跑，于是把 `golden_consistent=None` 写成了新基线——
    #: 等于亲手把标准降下来，下一轮反而全绿。基线只能由**全绿**的那一轮覆盖。
    fails_ = [i for i in items if i["status"] == FAIL]
    noruns_ = [i for i in items if i["status"] == NORUN and i.get("blocking", True)]
    rc_preview = 1 if (fails_ or drops) else (2 if noruns_ else 0)
    if args.update_baseline:
        if not args.why.strip():
            print("\n⛔ --update-baseline 必须带 --why（写清是谁改的、为什么）")
            return 1
        if rc_preview != 0 and not args.force_baseline:
            print(f"\n⛔ 拒绝更新基线：这一轮不是全绿（rc={rc_preview}，"
                  f"失败 {len(fails_)} 项、未跑 {len(noruns_)} 项）。"
                  f"基线只由全绿的那一轮建立；确实要覆盖请显式 --force-baseline")
        else:
            update_baseline(now, base, args.by, args.why, fp1["head"])
            print(f"\n基线已更新（by={args.by}）")

    rc = write_report(items, drops, changes, base, fp0, fp1, args, time.time() - t0)
    print("=" * 78)
    fails = [i for i in items if i["status"] == FAIL]
    noruns = [i for i in items if i["status"] == NORUN and i.get("blocking", True)]
    print(f"通过 {len(items) - len([i for i in items if i['status'] != PASS])}"
          f" / 失败 {len(fails)} / 未跑 {len([i for i in items if i['status'] == NORUN])}"
          f"　退出码 {rc}　总耗时 {(time.time() - t0) / 60:.1f} 分钟")
    if drops:
        print("⛔ 水位下降：" + "；".join(f"{d['key']} {d['was']}→{d['now']}" for d in drops))
    for i in fails:
        print(f"⛔ {i['name']}：{i['note']}")
    for i in noruns:
        print(f"⊘ {i['name']} 未跑：{i['note'][:120]}")
    print("⚠ 本门不覆盖：逐关对拍（工具已删除）、17 份计划未走到的路径、保真层"
          "（两台引擎一起错）——详见报告第八节")
    print(f"报告：{REPORT.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
