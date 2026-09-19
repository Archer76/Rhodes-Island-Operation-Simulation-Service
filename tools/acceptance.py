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
| 1 | 金标准 | 与 `fixtures/golden_go.json` 逐项一致（含 spec_sha），且**已有条目**未被改写 |
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
GIT = "git"
LOGS = OUT / "logs"
REPORT = ROOT / "docs" / "acceptance-report.md"
BASELINE = ROOT / "docs" / "acceptance-baseline.json"
CLAIMS = ROOT / "docs" / "acceptance-claims.md"
GOLDEN = ((ROOT / "fixtures" / "golden_go.json") if (ROOT / "fixtures").is_dir()
          else (ROOT / "out" / "golden_go.json"))
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
    #: ⚠ **不许自己再算一份源码身份**（实测栽过）：这里原先用 `名字:大小:mtime` 摘要，
    #: 而 `tools/engine_pin.py` 用**内容**摘要 ⇒ 同一棵树、同一时刻算出两个不同的值
    #: （`2a9c381a` vs `9b81f2d5`），还把后者当成"别人复现不出来的数"查了半轮。
    #: **两处各写一份，一改就对不上**——现在统一复用 `engine_pin`（它另分 disk/HEAD 两个身份）。
    sys.path.insert(0, str(TOOLS))
    from engine_pin import source_identity as _src_ident                 # noqa: PLC0415
    _ident = _src_ident()
    src_sig = _ident["disk"]            #: 磁盘此刻（＝本次构建实际摘到的那份内容）
    head_sig = _ident["head"]           #: HEAD 那份（判"是不是 HEAD 的构建"只能用这个）
    target = fresh_exe.with_name(f"rios-sim-{src_sig}.exe")
    OUT.mkdir(parents=True, exist_ok=True)

    r = run(["go", "build", "-buildvcs=false", "-o", str(target), "."],
            cwd=ROOT / "rios-sim", timeout=600)
    r["cmd"] = ["go", "build", "-buildvcs=false", "-o", str(target), "."]
    log_raw("instrument-build", r)

    measured: dict = {"src_sig": src_sig, "head_src_sig": head_sig,
                      "src_sig_same_as_head": src_sig == head_sig,
                      "src_dirty_n": _ident["dirty_n"],
                      "src_dirty_files": _ident["dirty_files"][:8],
                      "build_rc": r["rc"], "build_s": round(r["seconds"], 1)}
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


def baseline_audit() -> dict:
    """把 `fixtures/golden_go.json` 与**版本控制里那一份**逐条目比。

    为什么不用 sha：sha 只能报"变了"，报不出**改了什么**——而"新增了两份夹具"与
    "已有 17 份的数被改了"是性质完全相反的两件事（前者是判据集长大，后者是标准被挪）。
    通告 #6 四要堵的洞正是后者：「有人重跑覆盖基线，没有任何人会发现」。
    """
    import subprocess
    out = {"tracked": False, "added": [], "removed": [], "changed": []}
    rel = GOLDEN.relative_to(ROOT).as_posix()
    try:
        p = subprocess.run(["git", "-C", str(ROOT), "show", f"HEAD:{rel}"],
                           capture_output=True, encoding="utf-8", timeout=60)
        if p.returncode != 0:
            return out
        committed = json.loads(p.stdout)
    except Exception:                                            # noqa: BLE001
        return out
    out["tracked"] = True
    cur = json.loads(GOLDEN.read_text(encoding="utf-8")) if GOLDEN.exists() else {}
    keys = ["kills", "leaks", "elapsed", "damage", "spec_sha"]
    out["added"] = sorted(set(cur) - set(committed))
    out["removed"] = sorted(set(committed) - set(cur))
    out["changed"] = sorted(n for n in set(cur) & set(committed)
                            if any(committed[n].get(k) != cur[n].get(k) for k in keys))
    out["plans"] = len(cur)
    return out


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


    #: sha 仍然记着（跨轮次看"基线文件动过没有"最省事），但**判定不再只看它**。
    prev_sha = None
    if BASELINE.exists():
        try:
            prev_sha = json.loads(BASELINE.read_text(encoding="utf-8"))["water"].get(
                "golden_baseline_sha256")
        except Exception:                                        # noqa: BLE001
            prev_sha = None
    #: ⚠ "基线文件被改写"这条护栏只比 sha 是不够的——本轮实测它把**我自己按通告 #6 四
    #: 做的合法迁移**（判据集迁进 `fixtures/`、新增两份夹具）报成了失败，而它只说
    #: "哈希变了"，说不出**改了什么**。改法：直接与**版本控制里那一份**比条目
    #: ——**新增**与**已有条目被改**是两件性质完全不同的事，必须分开报。
    measured["baseline_audit"] = baseline_audit()
    ba = measured["baseline_audit"]
    if ba["changed"]:
        status = FAIL
        note = (note + "；" if note else "") + (
            f"⛔ 金标准基线里**已有 {len(ba['changed'])} 份条目的数被改了**"
            f"（{', '.join(ba['changed'][:4])}{'…' if len(ba['changed']) > 4 else ''}）"
            f"——须解释谁改的、为什么；判据是「改动必须被解释」，不是「哈希不许变」")
    elif ba["added"] or ba["removed"]:
        extra = (f"（判据集变动：新增 {len(ba['added'])} 份"
                 f"{'、少了 ' + str(len(ba['removed'])) + ' 份' if ba['removed'] else ''}）")
        note = (note + extra) if note else extra
    measured["baseline_changed"] = bool(ba["changed"])
    measured["baseline_sha_changed"] = bool(
        prev_sha and exe_sha and exe_sha[:16] != prev_sha[:16])

    return {"key": "golden", "name": "金标准（规格哈希 + 判决四数）", "status": status,
            "measured": measured, "seconds": round(r["seconds"], 1),
            "judge": "与 fixtures/golden_go.json 逐项一致（含 spec_sha），且已有条目未被改写",
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
        #: 与金标准**同一份判据集**（`G.plan_files()` 会优先 `fixtures/`，按 schema 认，
        #: 不按文件名）——两处口径不一致时，"金标准 19 份 vs 抽查 17 份"会让人以为是回归。
        plans = G.plan_files()
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
               timeout: int = 3600, counted: bool = True) -> dict:
    """`counted=False` ⇒ **只跑不判**：照跑、照打印、照进报告，但**不进通过/失败/未跑计数**，
    也不参与 rc 与水位下降判定（`check_battle` 用：它测的是**已退出产品路径的原版引擎自身**，
    留痕有价值、当判据会被误读成产品的绿——PM 2026-09-19 裁定）。"""
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
            "note": note, "_baseline_key": baseline_key, "counted": counted}


# ---------------------------------------------------------------- 第 5 项：闸门盲区审计

AUDIT_LINE = re.compile(r"已登记且守卫成立：(\d+) 条；\*\*未登记：(\d+)\*\*；"
                        r"\*\*守卫失效：(\d+)\*\*")


def fresh_checkout_item(guard: bool = False) -> dict:
    """**从 HEAD 干净解出一棵树** → `go build ./...` + `go test ./...` 必须 rc=0。

    为什么必须有这一条：`rios-sim.exe` 在 `.gitignore` 里，**各会话都从工作树构建** ⇒
    每一道门看到的永远是一棵**能编译的树**。**HEAD 本身坏掉，没有任何判据看得见**——
    实测：`mech/snow.go` 引用的 `var Trace` 在 HEAD 的 `mech/mech.go` 里 0 次出现。
    **这一条看不见的不是一个字段，是整个仓库。**

    反向守卫（`guard=True`）：在这棵临时树里把 `var Trace` 那一行拿走 ⇒ **必须红**。
    临时树**用完即删**（`git worktree remove --force`，失败也不留）。
    """
    import shutil
    import tempfile

    go = shutil.which("go") or "go"
    tmp = Path(tempfile.mkdtemp(prefix="ak-fresh-"))
    tree = tmp / "tree"
    got: dict = {"guard": guard}
    try:
        r = run([GIT, "worktree", "add", "--detach", str(tree), "HEAD"], timeout=300)
        got["worktree_rc"] = r["rc"]
        if r["rc"] != 0:
            return {"key": "fresh", "name": "从 HEAD 干净解树构建（fresh_checkout_build）",
                    "status": NORUN, "measured": got, "seconds": 0.0, "blocking": True,
                    "judge": "`git worktree add --detach <tmp> HEAD` → `go build ./...` + "
                             "`go test ./...` 均 rc=0",
                    "note": f"解不出树：{(r['err'] or r['out'])[-200:]}"}
        t0 = time.time()
        if guard:
            #: 反向守卫：把 `var Trace` 那行拿走（它就是 snow.go 编不过的原因）
            mech = tree / "rios-sim" / "mech" / "mech.go"
            if mech.exists():
                lines = mech.read_text(encoding="utf-8").splitlines(keepends=True)
                keep = [ln for ln in lines if not ln.lstrip().startswith("var Trace")]
                got["guard_removed_lines"] = len(lines) - len(keep)
                mech.write_text("".join(keep), encoding="utf-8")
        b = run([go, "build", "./..."], cwd=tree / "rios-sim", timeout=1800)
        got["build_rc"] = b["rc"]
        got["build_err"] = (b["err"] or "")[-800:]
        t = None
        if b["rc"] == 0:
            t = run([go, "test", "./..."], cwd=tree / "rios-sim", timeout=3600)
            got["test_rc"] = t["rc"]
            got["test_err"] = (t["err"] or "")[-800:]
        else:
            got["test_rc"] = None
            got["test_err"] = "build 未过，跳过 test"
        log_raw("fresh-guard" if guard else "fresh", b if b["rc"] != 0 else (t or b))
        ok = got["build_rc"] == 0 and got.get("test_rc") == 0
        msg = (got["build_err"] or got["test_err"] or "").strip().splitlines()
        status = PASS if ok else FAIL
        return {"key": "fresh", "name": "从 HEAD 干净解树构建（fresh_checkout_build）",
                "status": status, "measured": got, "seconds": round(time.time() - t0, 1),
                "judge": "`git worktree add --detach <tmp> HEAD` → `go build ./...` + "
                         "`go test ./...` 均 rc=0（**判的是提交，不是工作树**）",
                "note": "" if ok else (f"build rc={got['build_rc']} / test rc={got.get('test_rc')}；"
                                       + ("；".join(msg[:3])[:300] if msg else ""))}
    finally:
        run([GIT, "worktree", "remove", "--force", str(tree)], timeout=300)
        shutil.rmtree(tmp, ignore_errors=True)


def exe_staleness_item(exe: str | None, src_sig: str | None = None) -> dict:
    """**判据：任何一次读数，所用 exe 的 mtime 若早于本树最新的 `.go` 源，即红。**

    根因一句话：**`RIOS_SIM_BIN` 未设 ⇒ 静默落到一枚预编译的旧 exe**。实测那次事故里，
    两份"全绿/一处红"的读数**只差一个环境变量**：共享 exe（构建于 19:08、落后 16 个提交）
    报 `hsex8_max` 814.0333s/591046.1，当轮私有构建报 221.6667s/282276.8。
    ⇒ 这条判据看不见的既不是某个字段、也不是整个仓库，而是
    **「我手里的尺子是不是我造的那把」**。

    四个数一起打印：**exe 路径 / sha16 / mtime / 本树最新 `.go` 的 mtime**。
    """
    src = sorted((ROOT / "rios-sim").glob("**/*.go"))
    newest = max(src, key=lambda p: p.stat().st_mtime) if src else None
    nm = newest.stat().st_mtime if newest else 0.0
    cands: list[tuple[str, Path]] = []
    if exe:
        cands.append(("本次门读数所用（私有构建）", Path(exe)))
    envb = (os.environ.get("RIOS_SIM_BIN") or "").strip()
    if envb and Path(envb).exists():
        cands.append(("RIOS_SIM_BIN", Path(envb)))
    shared = ROOT / "rios-sim" / "rios-sim.exe"
    if shared.exists():
        cands.append(("**未钉时的默认路径**（共享 exe）", shared))
    rows, stale = [], []
    for label, p in cands:
        try:
            m = p.stat().st_mtime
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
        except OSError:
            rows.append({"label": label, "path": str(p), "error": "读不到"})
            continue
        behind = (nm - m) / 60.0
        row = {"label": label, "path": str(p), "sha16": h,
               "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(m)),
               "behind_min": round(behind, 1), "stale": m < nm}
        rows.append(row)
        if row["stale"]:
            stale.append(row)
    return {"key": "exe", "name": "仪器新鲜度：所用 exe 不得早于本树最新 `.go`（exe_staleness）",
            "status": FAIL if stale else PASS,
            "measured": {"newest_go": newest.name if newest else None,
                         "newest_go_mtime": time.strftime("%Y-%m-%d %H:%M:%S",
                                                          time.localtime(nm)) if newest else None,
                         "rows": rows, "stale_n": len(stale), "source_sig": src_sig},
            "seconds": 0.0,
            "judge": "所用 exe 的 mtime **不早于**本树最新 `.go` 源；否则这次的读数**不可归因**"
                     "（先钉/重建二进制再读红绿）。⚠ `sha16` 只能证明「**是不是那一次构建**」，"
                     "**不能证明「是哪份源码」**——实测同一份源码两次构建哈希就不同"
                     "（`b88b28ce6d0ca14f` ↔ `98fe111bce6c4ff0`）；源码身份看 `source_sig`",
            "note": "" if not stale else "；".join(
                f"{r['label']} {r['sha16']} 构建于 {r['mtime']}，"
                f"落后最新 .go（{newest.name} {time.strftime('%H:%M:%S', time.localtime(nm))}）"
                f"{r['behind_min']} 分钟" for r in stale)}


def roster_identity_item(path: Path | str | None = None,
                         expected: str | None = None) -> dict:
    """**名册身份**：本次读数所用的那名册，`sha16` 必须等于**基线里记的那个**。

    为什么要有这条：2026-09-20 实测，名册实物（`out/roster_max_modelled.json`）随旁支检出废弃而消失，
    而它**从未入库** ⇒ **19 份基线读数当场不可复现**，而门里**没有任何一条判据会说话**。
    读数的输入与读数本身一样需要身份——**"丢了就再也量不出来"的东西不该只住在易失目录里。**

    PM 2026-09-20 00:21 三条硬要求：
      * **实物缺失必须判红，不许判"跳过"**（"找不到"会被读成"通过"）；
      * **"名册不在"与"名册不对"要分开报**——前者是**缺口**，后者是**结论**；
      * 反向守卫必须**注入式**：改名册 ⇒ 红；删名册 ⇒ 红。
    """
    import golden_go as _G                       #: 与 `golden_check()` 用同一个夹具定位口径
    #: ⚠ 记录值住在**金标准基线**（`fixtures/golden_go.json` 每条一栏），**不是** `load_baseline()`
    #: 读的那份水位基线。第一版我写成了后者 ⇒ 反向守卫的**控制组当场没绿**
    #: （`记录值=None`，判据会永远红）——**"控制组必须绿"这一层替我把空判据挡住了**。
    gp = Path(_G.BASELINE) if hasattr(_G, "BASELINE") else ROOT / "fixtures" / "golden_go.json"
    recorded: list[str] = []
    try:
        gj = json.loads(gp.read_text(encoding="utf-8-sig"))
        recorded = sorted({v.get("roster_sha16") for v in gj.values()
                           if isinstance(v, dict) and v.get("roster_sha16")})
    except Exception as e:                                       # noqa: BLE001
        recorded = []
        gp = Path(f"{gp}（读失败：{type(e).__name__}: {e}）")
    exp = expected or (recorded[0] if len(recorded) == 1 else None)
    target = Path(path) if path is not None else _G._find("roster_max_modelled")
    measured: dict = {"path": str(target), "recorded_sha16": recorded,
                      "expected_sha16": exp}
    if not Path(target).exists():
        #: **缺口，不是结论**：实物不在场 ⇒ 红（且不许退化成"跳过"）。
        return {"key": "roster_identity", "name": "名册身份（输入实物 sha16 == 基线记录）",
                "status": FAIL, "seconds": 0.0, "measured": measured,
                "judge": "本次读数所用名册的 sha16 必须等于基线里记的那个；"
                         "**实物缺失即红**——它不是'跳过'，是'这份读数已不可复现'",
                "note": f"**名册不在场**（缺口）：{target} 不存在 ⇒ 缺了输入实物，"
                        f"基线记的是 {exp}；这不是'没得比'，是'比不了'"}
    got = (sha256_file(Path(target)) or "")[:16]
    measured["got_sha16"] = got
    measured["bytes"] = Path(target).stat().st_size
    if exp is None:
        return {"key": "roster_identity", "name": "名册身份（输入实物 sha16 == 基线记录）",
                "status": FAIL, "seconds": 0.0, "measured": measured,
                "judge": "基线里没有登记 `roster_sha16` ⇒ 无法断言输入身份（**登记缺失也是缺口**）",
                "note": "**基线没记名册身份**：`fixtures/golden_go.json` 里没有 `roster_sha16` 栏"}
    if got != exp:
        return {"key": "roster_identity", "name": "名册身份（输入实物 sha16 == 基线记录）",
                "status": FAIL, "seconds": 0.0, "measured": measured,
                "judge": "名册实物 sha16 必须等于基线记录值；不等即红（**换名册就是换输入，数字不可比**）",
                "note": f"**名册不对**（结论）：实物 sha16={got}，基线记的是 {exp}"
                        f"（{Path(target).name}，{measured['bytes']} B）"}
    return {"key": "roster_identity", "name": "名册身份（输入实物 sha16 == 基线记录）",
            "status": PASS, "seconds": 0.0, "measured": measured,
            "judge": "名册实物 sha16 ＝ 基线记录值 ⇒ 输入身份成立；"
                     "⚠ **换了名册必须换基线**（「能不能走到分歧点」会随名册变）",
            "note": ""}


#: **输入身份登记处**：`sha16` ＋ 来源约定（命令/路径/权威）。写在 `docs/`、**不写进 `fixtures/`**
#: （PM 2026-09-20 00:29 裁定：森空岛名册是博士自己的账号数据，**实物不入库**，但身份要能核）。
#: 登记表里那一块是 `key = value` 行，**机器可读**；判据读不到登记就报缺口，不猜。
IDENTITY_DOC = ROOT / "docs" / "input-identities.md"
IDENTITY_BLOCK = "identity"
SKLAND_GLOB = "data/skland/roster_*.json"


def load_input_identities() -> dict:
    """读 `docs/input-identities.md` 里 ```identity 块内的 `key = value`（机器可读的那一块）。"""
    if not IDENTITY_DOC.exists():
        return {}
    txt = IDENTITY_DOC.read_text(encoding="utf-8")
    m = re.search(rf"```{IDENTITY_BLOCK}\n(.*?)```", txt, re.S)
    if not m:
        return {}
    out: dict = {}
    for ln in m.group(1).splitlines():
        ln = ln.strip()
        if not ln or ln.startswith("#") or "=" not in ln:
            continue
        k, _, v = ln.partition("=")
        out[k.strip()] = v.strip()
    return out


def skland_identity_item(paths: list[Path] | None = None,
                         expected: str | None = None) -> dict:
    """**森空岛名册身份**（`data/skland/roster_*.json`）：在不在、对不对，**分开报**。

    PM 2026-09-20 00:29 裁定的三态（缺一不可）：
      * **"输入不在" ⇒ 明确报"未跑＋原因"**——它是账号导出、**不入库**（隐私口径），
        在别人机器上不在场是**常态**，所以**不许算红**，但也**绝不许退化成"通过/跳过"**；
      * **"输入在但换了" ⇒ 红**（sha16 与登记值不等）；
      * 登记值本身缺失（实物在场却没登记）⇒ **红**——那是**我方文件**的缺陷（`docs/input-identities.md`）。
    """
    exp = expected if expected is not None else load_input_identities().get("skland_roster_sha16")
    reg = load_input_identities()
    if paths is None:
        paths = sorted(ROOT.glob(SKLAND_GLOB))
    src = reg.get("skland_roster_source", "（未登记来源约定）")
    measured = {"glob": SKLAND_GLOB, "glob_n": len(paths),
                "files": [str(p) for p in paths], "expected_sha16": exp,
                "registry": str(IDENTITY_DOC), "source_convention": src}
    judge = ("① 实物不在 ⇒ **未跑＋原因**（账号导出不入库，不在场是常态，不计红也不许记成通过）；"
             "② 实物在而 sha16 ≠ 登记值 ⇒ **红**（换了输入就是换了口径）；"
             "③ 实物在而登记缺失 ⇒ **红**（登记处是我方文件，缺项是缺陷）")
    if not paths:
        return {"key": "skland_identity", "name": "森空岛名册身份（输入实物 sha16 == 登记值）",
                "status": NORUN, "seconds": 0.0, "measured": measured, "blocking": False,
                "judge": judge,
                "note": f"**输入不在场**（缺口，不计入判定）：`{SKLAND_GLOB}` 下没有文件。"
                        f"它是账号导出、不入库 ⇒ 别人机器上不在场是常态。取回：{src}"}
    if not exp or exp in ("未登记", "(未登记)"):
        return {"key": "skland_identity", "name": "森空岛名册身份（输入实物 sha16 == 登记值）",
                "status": FAIL, "seconds": 0.0, "measured": measured, "blocking": True,
                "judge": judge,
                "note": f"**登记缺失**（缺口）：实物在场（{len(paths)} 份）而 `{IDENTITY_DOC.name}` "
                        f"里没有 `skland_roster_sha16` ⇒ 无法断言输入身份。"
                        f"登记命令：`python tools/acceptance.py --register-roster`"}
    got = {p.name: (sha256_file(p) or "")[:16] for p in paths}
    measured["got_sha16"] = got
    bad = {n: h for n, h in got.items() if h != exp}
    if bad:
        return {"key": "skland_identity", "name": "森空岛名册身份（输入实物 sha16 == 登记值）",
                "status": FAIL, "seconds": 0.0, "measured": measured, "blocking": True,
                "judge": judge,
                "note": f"**输入在但换了**（结论）：{bad} ≠ 登记值 {exp}"
                        f" ⇒ 换了名册就是换了口径，**数字与基线不可比**"}
    return {"key": "skland_identity", "name": "森空岛名册身份（输入实物 sha16 == 登记值）",
            "status": PASS, "seconds": 0.0, "measured": measured, "blocking": True,
            "judge": judge,
            "note": ""}


def register_roster_identity() -> int:
    """把当场的实物 sha16 写进登记表（**只写 `docs/`，不碰实物、不进 `fixtures/`**）。"""
    paths = sorted(ROOT.glob(SKLAND_GLOB))
    if not paths:
        print(f"⛔ 实物不在场（`{SKLAND_GLOB}` 为空）⇒ **没有可登记的值**。"
              f"登记需要一个在场值，不能凭空写一个数。")
        return 2
    got = {p.name: (sha256_file(p) or "")[:16] for p in paths}
    vals = sorted(set(got.values()))
    if len(vals) != 1:
        print(f"⛔ 实物不唯一（{got}）⇒ 不登记：登记值必须唯一，否则判据没有意义。")
        return 3
    txt = IDENTITY_DOC.read_text(encoding="utf-8") if IDENTITY_DOC.exists() else ""
    new, n = re.subn(r"(?m)^skland_roster_sha16\s*=\s*.*$", f"skland_roster_sha16 = {vals[0]}", txt)
    if n == 0:
        print(f"⛔ 登记表里没有 `skland_roster_sha16` 那一行（{IDENTITY_DOC}）⇒ 不擅自新增，先补表。")
        return 4
    IDENTITY_DOC.write_text(new, encoding="utf-8")
    print(f"✅ 已登记：skland_roster_sha16 = {vals[0]}（{len(paths)} 份实物，{got}）")
    return 0


def guard_new_items(exe: str | None = None) -> int:
    """两条新判据的**反向守卫**：逐条人为破坏 ⇒ **必须红，且红得指得准**。

    * `fresh_checkout_build`：在临时树里把 `var Trace` 那行拿走 ⇒ 必须变红。
    * `exe_staleness`：`touch` 一个 `.go`（**只改 mtime、一个字节都不改**）⇒ 必须变红
      **并点名那枚落后 exe**；跑完把 mtime 还原。
    """
    bad = 0
    print("=" * 88)
    print("【反向守卫 1/2】fresh_checkout_build：临时树里拿掉 `var Trace` ⇒ 必须红")
    it = fresh_checkout_item(guard=True)
    ok1 = it["status"] == FAIL
    bad += 0 if ok1 else 1
    print(f"  {it['status']}　build rc={it['measured'].get('build_rc')}　"
          f"拿掉行数={it['measured'].get('guard_removed_lines')}")
    print(f"  ⇒ {'✅ 红得起来' if ok1 else '❌ **没红**——这条判据是空的'}")
    if it["note"]:
        print(f"  错误首行：{[ln for ln in it['note'].split('；') if ln][:2]}")

    print("【反向守卫 2/2】exe_staleness：**自带做旧夹具**（不依赖仓库里恰好躺着一枚旧 exe）")
    #: ⚠ 老写法依赖"共享树里那枚 19:08 的旧 exe 存在"——那枚后来被删了。
    #: **依赖外部文件存在**的守卫会从"红得起来"退化成"找不到文件"，而**"找不到"会被读成"通过"**
    #: （PM 与后端2 2026-09-19 23:38 点名）。改成：夹具自己造、路径自己钉，三种情形逐条断言。
    import shutil as _sh
    import tempfile
    tmpd = Path(tempfile.mkdtemp(prefix="ak-stale-"))
    src_exe = Path(exe) if exe and Path(exe).exists() else None
    if src_exe is None:
        _m = sorted((OUT).glob("rios-sim-*.exe"), key=lambda p: p.stat().st_mtime)
        src_exe = _m[-1] if _m else None
    if src_exe is None:
        print("  ⚠ 本机没有可复制的 exe 做夹具 ⇒ 这条守卫**未跑**（不冒充通过）")
        _sh.rmtree(tmpd, ignore_errors=True)
        return bad + 1
    fresh = tmpd / "fixture-fresh.exe"
    stale = tmpd / "fixture-stale.exe"
    _sh.copy2(src_exe, fresh)
    _sh.copy2(src_exe, stale)
    now = time.time()
    os.utime(fresh, (now, now))                       # 新的：应与源码齐平
    os.utime(stale, (now - 3 * 3600, now - 3 * 3600))  # 做旧 3 小时
    victim_src = sorted((ROOT / "rios-sim").glob("**/*.go"))
    victim = max(victim_src, key=lambda p: p.stat().st_mtime)
    st = victim.stat()
    try:
        #: 控制组：**夹具本身必须是"不旧"的**，否则下面那条红证明不了任何事
        it_c = exe_staleness_item(str(fresh))
        okc = it_c["status"] == PASS
        bad += 0 if okc else 1
        print(f"  [控制组] 新夹具、不动 .go ⇒ {it_c['status']}"
              f"　{'✅ 绿得起来（说明判据不是恒红）' if okc else '❌ 恒红 ⇒ 判据没有分辨力'}")
        #: 敏感性：同一枚夹具 + touch 一个 .go（内容一字不改）⇒ 必须红并点名**那枚夹具**
        #: ⚠ 第一版把 .go 的 mtime 也设成同一个 `now`，于是两边**恰好相等** ⇒ 判据（"早于"）
        #: 正确地不红，而这个**假红**是我自己的守卫写错了（守卫也要有分辨力，不能靠"差不多"）。
        #: 改成把 .go 的 mtime 明确设成 `now + 60s`：**时间关系确定**，不依赖浮点分辨率。
        os.utime(victim, (now + 60, now + 60))
        it_s = exe_staleness_item(str(fresh))
        named = [r for r in it_s["measured"].get("rows", []) if r.get("stale")]
        ok_s = it_s["status"] == FAIL and any(str(fresh) == r.get("path") for r in named)
        bad += 0 if ok_s else 1
        print(f"  [敏感性] 同一枚夹具 + `touch {victim.name}` ⇒ {it_s['status']}"
              f"　点名夹具={'✅' if any(str(fresh) == r.get('path') for r in named) else '❌'}"
              f"　⇒ {'✅ 红得起来且指得准' if ok_s else '❌ 没红/没点名'}")
        for r in named:
            print(f"      ⛔ {r['label']}　{r['sha16']}　{r['mtime']}（落后 {r['behind_min']} 分钟）")
    finally:
        os.utime(victim, (st.st_atime, st.st_mtime))
        #: 做旧夹具：**不做 touch 也应该红**（它自己就旧于源码）——这一条不依赖任何仓库状态
        it_st = exe_staleness_item(str(stale))
        ok_st = it_st["status"] == FAIL and any(
            str(stale) == r.get("path") for r in it_st["measured"].get("rows", []) if r.get("stale"))
        bad += 0 if ok_st else 1
        print(f"  [做旧夹具本身] {stale.name}（mtime 回拨 3 小时）⇒ {it_st['status']}"
              f"　{'✅ 旧即红、且点名夹具' if ok_st else '❌ 没红/没点名'}")
        _sh.rmtree(tmpd, ignore_errors=True)
        back = victim.stat().st_mtime
        print(f"  [还原] {victim.name} mtime "
              f"{'✅ 与起始一致' if abs(back - st.st_mtime) < 1e-6 else '❌ 不一致'}")
        it3 = exe_staleness_item(exe)
        print(f"  [还原后复跑] {it3['status']}（应与破坏前一致）")
    print("【反向守卫 3/3】roster_identity：**注入式**三态——控制组必须绿、改名册必须红、删名册也必须红")
    #: PM 2026-09-20 00:21 的硬要求：**"名册不在"与"名册不对"要分开报**（前者缺口、后者结论），
    #: 且**实物缺失不许判"跳过"**（"找不到"会被读成"通过"）。
    #: ⚠ 守卫**自己造夹具**（复制一份真名册再改一个字节），不依赖"仓库里恰好躺着一份坏名册"。
    it_ctl = roster_identity_item()
    ok_ctl = it_ctl["status"] == PASS
    bad += 0 if ok_ctl else 1
    print(f"  [控制组] 真名册 ⇒ {it_ctl['status']}　sha16={it_ctl['measured'].get('got_sha16')}"
          f"　记录值={it_ctl['measured'].get('expected_sha16')}　"
          f"⇒ {'✅ 该绿就绿' if ok_ctl else '❌ 控制组没绿：判据本身坏了'}")
    tmpd2 = Path(tempfile.mkdtemp(prefix="ak-roster-"))
    try:
        real = Path(it_ctl["measured"]["path"])
        if not real.exists():
            print("  ⚠ 真名册不在场 ⇒ 这条守卫**未跑**（不冒充通过）")
            bad += 1
        else:
            fake = tmpd2 / real.name
            raw = bytearray(real.read_bytes())
            #: 只改**一个字节**（且改在文件里而非末尾空白），证明判据看的是内容而不是"文件在不在"
            raw[len(raw) // 2] = (raw[len(raw) // 2] + 1) % 256
            fake.write_bytes(bytes(raw))
            it_bad = roster_identity_item(path=fake)
            ok_bad = it_bad["status"] == FAIL and "不对" in it_bad["note"]
            bad += 0 if ok_bad else 1
            print(f"  [改名册 1 字节] ⇒ {it_bad['status']}　{it_bad['note'][:88]}")
            print(f"      ⇒ {'✅ 红得起来且报「不对」' if ok_bad else '❌ 没红/没报对'}")
            it_miss = roster_identity_item(path=tmpd2 / "这里没有这个名册.json")
            ok_miss = it_miss["status"] == FAIL and "不在场" in it_miss["note"]
            bad += 0 if ok_miss else 1
            print(f"  [删名册（路径不存在）] ⇒ {it_miss['status']}　{it_miss['note'][:88]}")
            print(f"      ⇒ {'✅ 红得起来且报「不在场」（缺口），而不是跳过' if ok_miss else '❌ 没红/退化成跳过'}")
            distinct = ("不在场" in it_miss["note"]) and ("不对" in it_bad["note"]) and \
                       ("不在场" not in it_bad["note"])
            bad += 0 if distinct else 1
            print(f"  [两态可分] 「不在」与「不对」措辞不同：{'✅ 分开报' if distinct else '❌ 混成一态'}")
    finally:
        _sh.rmtree(tmpd2, ignore_errors=True)
    print("【反向守卫 4/4】skland_identity：三态**全测**——在场且对⇒绿／在场但换了⇒红／不在⇒未跑（≠通过）")
    #: ⚠ 这条守卫**自带夹具**：真名册（`data/skland/roster_*.json`）是账号导出、**不入库**，
    #: 本机**不在场是常态** ⇒ 守卫**不许依赖它存在**（否则守卫自己会退化成"找不到"）。
    #: 三态逐条断言，其中第 ③ 态要断言的正是 PM 那句：**"不在"绝不许退化成"通过/跳过"**。
    tmpd3 = Path(tempfile.mkdtemp(prefix="ak-skland-"))
    try:
        real = tmpd3 / "roster_fixture.json"
        real.write_text(json.dumps({"uid": "fixture", "opers": [{"charId": "char_103_angel"}]},
                                   ensure_ascii=False), encoding="utf-8")
        own = (sha256_file(real) or "")[:16]
        it_ok = skland_identity_item(paths=[real], expected=own)
        ok_ok = it_ok["status"] == PASS
        bad += 0 if ok_ok else 1
        print(f"  [在场且对] ⇒ {it_ok['status']}　sha16={own}　⇒ {'✅ 该绿就绿' if ok_ok else '❌ 控制组没绿'}")
        it_ch = skland_identity_item(paths=[real], expected="0" * 16)
        ok_ch = it_ch["status"] == FAIL
        bad += 0 if ok_ch else 1
        print(f"  [在场但换了] ⇒ {it_ch['status']}　{it_ch['note'][:70]}")
        print(f"      ⇒ {'✅ 红得起来（换了输入＝换了口径）' if ok_ch else '❌ 没红'}")
        it_no = skland_identity_item(paths=[], expected=own)
        ok_no = it_no["status"] == NORUN and "不在场" in it_no["note"] and \
            not it_no.get("blocking", True)
        bad += 0 if ok_no else 1
        print(f"  [不在场] ⇒ {it_no['status']}（blocking={it_no.get('blocking')}）"
              f"　{it_no['note'][:66]}")
        print(f"      ⇒ {'✅ 未跑＋原因，且不计红——但它不是「通过」' if ok_no else '❌ 退化成了通过/跳过'}")
        it_reg = skland_identity_item(paths=[real], expected="未登记")
        ok_reg = it_reg["status"] == FAIL and "登记缺失" in it_reg["note"]
        bad += 0 if ok_reg else 1
        print(f"  [在场但登记缺失] ⇒ {it_reg['status']}　{it_reg['note'][:66]}")
        print(f"      ⇒ {'✅ 红得起来（登记处是我方文件）' if ok_reg else '❌ 没红'}")
    finally:
        _sh.rmtree(tmpd3, ignore_errors=True)
    print("=" * 88)
    print("✅ 四条守卫都成立" if bad == 0 else f"❌ {bad} 条不成立")
    return 0 if bad == 0 else 1


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
        elif it["key"] in ("roster_identity", "skland_identity"):
            cur = (f"实物 `{Path(str(m.get('path'))).name}`　sha16={fmt(m.get('got_sha16'))}"
                   f"　登记值={('、'.join(m.get('recorded_sha16') or []) or fmt(m.get('expected_sha16')))}")
            prev = "—"
        else:
            #: ⚠ 原文这里写死"见下方未跑说明"——于是**通过**的项（如 `exe_staleness`、`fresh_checkout_build`）
            #: 在报告里带着一句"未跑说明"，**文字与状态互相打脸**。缺渲染分支不等于"未跑"。
            #: 改成：把 `measured` 里的标量照原样铺出来（宁可是原始键值，也不要说一句假话）。
            _scal = [(k, v) for k, v in m.items()
                     if isinstance(v, (str, int, float, bool)) and v not in (None, "", [])]
            cur = "；".join(f"{k}={v}" for k, v in _scal[:4]) if _scal else "（本项无标量实测栏）"
            prev = "—"
        if it["status"] == NORUN and it["key"] in ("battle", "verify", "roster_identity",
                                                   "skland_identity"):
            cur = "未跑：" + (it["note"].split("；")[0][:90] or "（无说明）")
        _st = it["status"] + ("（**不计入判定**）" if not it.get("counted", True) else "")
        L.append(f"| {i} | {it['name']} | {_st} | {cur} | {prev} | {it['judge']} |")
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
    L.append("> ⚠ **判据变更（博士 2026-09-19 裁定：基线改用 Go）**：本门第 1 项的参照物本就是 "
             "**Go 自身基线**（`fixtures/golden_go.json`），裁定后语义更纯："
             "**红＝Go 自己漂了**。原版数字**退出判据**，任何「与 Python 一致」类判据"
             "要么报废、要么改判据，逐列点名见 `docs/parity-ledger.md` 〇之二。")
    L.append("")
    L.append("- **逐关对拍**：已按项目经理通告 #2 **退役**（博士 2026-09-19 19:56 弃用"
             "Python 模拟器），本门不再把它当验收手段、不为它写新仪器；"
             "「8 关闸门拦下 / 3 关真差」改读**闸门能力清单**（第六项）。"
             "⚠ 已入库的 `tools/parity_plan.py`（4fe187b）实测**跑不起来**"
             "（`GoCapture._run_other_engine` 不接受 `schedule`，见台账）——"
             "谁要引它当证据，先自己跑通。")
    _g = next((it for it in items if it["key"] == "golden"), None)
    n_plans = ((_g or {}).get("measured") or {}).get("baseline_plans") or 0
    L.append(f"- **判据集里 {n_plans or '全部'} 份作业没走到的路径**：金标准只覆盖这些作业上真跑出来的路径；"
             "没被走到的分支，它不说话——**覆盖不到机制的判据只会沉默，不会否证**。"
             "所以金标准绿 ≠ 所有机制都对。")
    L.append("- **深水限定语**：「本树现有用例全绿」**不等于**「这些关没问题」——"
             "能走到长线的只有迁入的 `hsex8_max`（八人满练度），其余大多是几十秒的浅用例。")
    L.append("- **深水差异成立**（`hsex8_max`）：原版 83杀/1漏/814.0333s vs Go 48杀/3漏/"
             "221.6667s，三台仪器一致。⚠ 它**不是**本门判定项**之一**（本门只问"
             "「Go 与基线一致」，而这条差是**已知且已登记**的），但**深水限定语照带**："
             "「现有用例全绿」≠「这些关没问题」。")
    L.append("- **仪器切换的静默假绿已自查**：本门链上（本文件 / `golden_go.py` / "
             "`parity_ledger.py`）**无裸 `Verifier()`**——唯一要原版的地方显式钉了 "
             "`engine=\"python\"`。两处**相关但不是缺陷**的留痕见 `docs/acceptance-claims.md`："
             "`check_battle.py` 24 处裸 `Verifier()` 但**零 `.run()`**（引擎不参与）；"
             "`check_verify.py` 6 处裸 `Verifier().run()` ⇒ **自 09-19 起它断言的主体是 Go**"
             "（它测的是验证器自身，跑 Go 是对的，但那 71 项**不替原版背书**）。")
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
    ap.add_argument("--guard-new-items", action="store_true",
                    help="跑四条新判据（fresh_checkout_build / exe_staleness / roster_identity / "
                         "skland_identity）的反向守卫，不跑整道门")
    ap.add_argument("--register-roster", action="store_true",
                    help="把当场的森空岛名册 sha16 写进 docs/input-identities.md 的登记块"
                         "（需要一个在场值；实物不在场时拒绝登记，不凭空写数）")
    ap.add_argument("--force-baseline", action="store_true",
                    help="这一轮不是全绿时也强行覆盖基线（会留下 history 记录）")
    ap.add_argument("--by", default=SESSION)
    ap.add_argument("--why", default="")
    args = ap.parse_args()

    if args.guard_new_items:
        return guard_new_items(None)

    if getattr(args, "register_roster", False):
        return register_roster_identity()

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
    _m0 = ins.get("measured") or {}
    print(f"      源码身份：disk={_m0.get('src_sig')}（glob rios-sim/**/*.go，"
          f"dirty {_m0.get('src_dirty_n')} 条{(': ' + str(_m0.get('src_dirty_files'))) if _m0.get('src_dirty_files') else ''}）"
          f"　HEAD={_m0.get('head_src_sig')}"
          + ("　✅ 两者相同" if _m0.get("src_sig_same_as_head") else
             "　⚠ **磁盘 ≠ HEAD**：这份读数只对当时那份工作树成立、不对任何提交成立"))

    it = golden_check(exe)
    items.append(it)
    print(f"[1] 金标准：{it['status']}　一致 {it['measured'].get('consistent')}/"
          f"{it['measured'].get('baseline_plans')}　{it['seconds']:.0f}s"
          + (f"　{it['note']}" if it["note"] else ""))
    #: PM 2026-09-20 00:21 批准：**输入身份**也必须是一条会说话的判据。
    #: 缘起：名册实物曾随旁支检出废弃而消失（住在易失 `out/`、从未入库）⇒ 19 份读数当场不可复现，
    #: 而门里**没有一条判据会说话**。判据本体只问一件事：**这次读数的输入，是不是基线里那一个。**
    it = roster_identity_item()
    items.append(it)
    _m = it["measured"]
    print(f"[1c] 名册身份：{it['status']}　实物 {_m.get('path')}"
          f"　sha16={_m.get('got_sha16')}　基线记录={_m.get('expected_sha16')}"
          + (f"　{it['note']}" if it["note"] else ""))
    #: PM 2026-09-20 00:29 裁定：森空岛名册**登记身份、不入库**，三态（不在⇒未跑＋原因／在但换了⇒红／
    #: 不许退化成跳过）。它与 check_verify 是两份不同的输入，却同一个病：**只住在易失目录里**。
    it = skland_identity_item()
    items.append(it)
    _m = it["measured"]
    print(f"[1d] 森空岛名册身份：{it['status']}（{'不计入判定' if not it.get('blocking', True) else '计入判定'}）"
          f"　实物 {_m.get('glob_n')} 份　登记值={_m.get('expected_sha16')}"
          f"　实物 sha16={_m.get('got_sha16') or '—'}"
          + (f"　{it['note']}" if it["note"] else ""))
    #: PM 2026-09-19 23:27 新增：**仪器新鲜度**——"我手里的尺子是不是我造的那把"
    it = exe_staleness_item(exe, (ins.get("measured") or {}).get("src_sig"))
    items.append(it)
    print(f"[1b] 仪器新鲜度：{it['status']}　本树最新 .go="
          f"{it['measured'].get('newest_go')} {it['measured'].get('newest_go_mtime')}"
          f"　源码身份 source_sig={it['measured'].get('source_sig')}")
    for row in it["measured"].get("rows", []):
        if "error" in row:
            print(f"      {row['label']}：读不到 {row['path']}")
        else:
            print(f"      {row['label']}　{row['sha16']}　{row['mtime']}"
                  + (f"　⛔ 落后 {row['behind_min']} 分钟" if row["stale"] else "　✅ 不旧于源码"))

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
            #: ⚠ 点名（博士 2026-09-19 裁定「基线改用 Go」后必须说清）：
            #: `check_battle.py` **直接 import `ak_tactic.battle`** 并断言**原版自己的数**
            #: （24 处 `Verifier()` **零 `.run()`** ⇒ 引擎根本不参与）。原版已退出产品路径，
            #: 所以这 816 项的绿**只说明「原版没退化」，不说明 Go 如何**。
            #: **PM 2026-09-19 23:22 裁定「只跑不判」**：打印数、留在报告里、**不进判定**。
            ("battle", "自检 check_battle（**原版引擎自身**的回归套件，已退出产品路径）",
             "check_battle.py", "check_battle_passed"),
            ("verify", "自检 check_verify（验证器，主体＝Go）", "check_verify.py",
             "check_verify_passed")):
        it = water_item(key, name, script, bkey, counted=(key != "battle"))
        if key == "battle":
            it["judge"] = ("**本项不计入判定**（PM 2026-09-19 裁定「只跑不判」）：测的是"
                           "**原版引擎自身**的回归；⚠ **不替 Go 背书**——原版已退出基线地位"
                           "（博士 2026-09-19 裁定）。留下只为留痕：原版有没有退化仍需看得见")
        items.append(it)
        print(f"[{len(items) - 1}] {name}：{it['status']}"
              f"{'（本项不计入判定）' if not it.get('counted', True) else ''}"
              f"　通过 {it['measured'].get('passed')} 项　{it['seconds']:.0f}s"
              + (f"　{it['note']}" if it["note"] else ""))

    it = fresh_checkout_item()
    items.append(it)
    print(f"[{len(items) - 1}] 从 HEAD 干净解树构建（fresh_checkout_build）：{it['status']}　"
          f"build rc={it['measured'].get('build_rc')}　test rc={it['measured'].get('test_rc')}"
          f"　{it['seconds']:.0f}s" + (f"　{it['note'][:160]}" if it["note"] else ""))

    it = audit_item()
    items.append(it)
    print(f"[{len(items) - 1}] 闸门盲区审计：{it['status']}　未登记 "
          f"{it['measured'].get('unregistered')}　守卫失效 "
          f"{it['measured'].get('guard_broken')}　自检="
          f"{it['measured'].get('selftest_ok')}")

    it = capability_item()
    items.append(it)
    print(f"[{len(items) - 1}] 闸门能力清单：{it['status']}　已读取 {it['measured'].get('read')} / "
          f"已定义未读 {it['measured'].get('defined_unread')} / "
          f"未送 {it['measured'].get('unsent')}")

    it = parity_retired_item()
    items.append(it)
    print(f"[{len(items) - 1}] 对拍入口：{it['status']}（已退役，仅登记）")

    fp1 = fingerprint()
    base = load_baseline()
    now = current_water(items)
    drops_all, changes = compare_water(now, base)
    #: **「只跑不判」的项不进判定**：既不算通过/失败/未跑，也不产生水位下降
    #: （PM 2026-09-19 裁定：`check_battle` 测的是已退出产品路径的原版引擎）。
    #: ⚠ 但它**仍然记进基线**（留痕：原版有没有退化要看得见），只是不参与红绿。
    uncounted = {i["key"] for i in items if not i.get("counted", True)}
    drops = [d for d in drops_all if d["key"] not in uncounted]

    #: ⛔ **基线不许由红的那一轮建立**。本轮实测踩到过：在途重构让金标准瞬时断裂，
    #: 我带着 `--update-baseline` 跑，于是把 `golden_consistent=None` 写成了新基线——
    #: 等于亲手把标准降下来，下一轮反而全绿。基线只能由**全绿**的那一轮覆盖。
    fails_ = [i for i in items if i["status"] == FAIL and i.get("counted", True)]
    noruns_ = [i for i in items if i["status"] == NORUN and i.get("counted", True)
               and i.get("blocking", True)]
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
    fails = [i for i in items if i["status"] == FAIL and i.get("counted", True)]
    noruns = [i for i in items if i["status"] == NORUN and i.get("counted", True)
              and i.get("blocking", True)]
    counted = [i for i in items if i.get("counted", True)]
    print(f"通过 {len([i for i in counted if i['status'] == PASS])}"
          f" / 失败 {len(fails)} / 未跑 {len([i for i in counted if i['status'] == NORUN])}"
          f"　（**判定项 {len(counted)} 项**）　退出码 {rc}　总耗时 {(time.time() - t0) / 60:.1f} 分钟")
    if uncounted:
        for i in items:
            if i["key"] in uncounted:
                print(f"⊘ **本项不计入判定**：{i['name']}（跑出 {i['measured'].get('passed')} 项，"
                      f"仅留痕、不进红绿）")
    if drops:
        print("⛔ 水位下降：" + "；".join(f"{d['key']} {d['was']}→{d['now']}" for d in drops))
    for i in fails:
        print(f"⛔ {i['name']}：{i['note']}")
    for i in noruns:
        print(f"⊘ {i['name']} 未跑：{i['note'][:120]}")
    _gi = next((it for it in items if it["key"] == "golden"), None)
    n_plans = ((_gi or {}).get("measured") or {}).get("baseline_plans") or 0
    print(f"⚠ 本门不覆盖：{n_plans or '判据集'} 份作业未走到的路径、保真层（两台引擎一起错）、"
          f"深水限定语——详见报告第八节")
    print(f"报告：{REPORT.relative_to(ROOT)}")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
