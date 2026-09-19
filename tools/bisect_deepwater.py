#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**深水漂移二分**：`hsex8_max` 从 83杀/1漏/814.0333s 变成 48杀/3漏/221.6667s，是哪一笔提交改的。

## 前提（PM 2026-09-20 00:02 更正后的口径）

19:08 那枚 `rios-sim-legacy-1908_b3e4d6b1.exe` 来自**「HEAD@19:08 ＋ 五个未提交文件」的混合树**，
那棵树**不存在了** ⇒ **没有任何提交能复现它**。所以本工具**不把 83/814 当既定左端点**，而是：

1. **二分只在"可复现的提交"之间做**：每一步 `git worktree add --detach <tmp> <sha>` → `go build` →
   钉 `RIOS_SIM_BIN` 跑该 plan，报**仪器三件套**（exe sha16 / 该树的 `source_sig` / 该树 HEAD）；
2. **单独回答一个可证伪的问题**：**「83杀/1漏/814.0333s」能否从任何已提交状态复现？**
   * 能 ⇒ 两个可复现端点都在，二分成立（左端点就是第一个能复现 83/814 的提交）；
   * 不能 ⇒ **这本身就是合格结论**：「与权威实现 Python 一致的 Go 行为，只出现在那个不可复现的混合态里」。
3. **硬约束**：不许为了凑出端点改引擎、补提交或放宽判据；只读交付。

## 用法

    # 单点：某个提交的 Go 读数（自建自钉，临时树用完即删）
    python tools\\bisect_deepwater.py --at 6b1173c
    # 直接测一枚现成的 exe（留证副本、或本树私有构建）
    python tools\\bisect_deepwater.py --exe out/acceptance/rios-sim-legacy-1908_b3e4d6b1.exe
    # 在 [lo, hi] 之间逐提交二分（lo 读数=83/814 那一侧，hi=48/221 那一侧）
    python tools\\bisect_deepwater.py --range 6b1173c..0dc0c14
    # 复核：在区间两端各构建一次，与文档记载比对
    python tools\\bisect_deepwater.py --verify docs/deepwater-drift.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                          # noqa: E402
from ak_tactic.verify import Verifier                            # noqa: E402
import golden_go as G                                            # noqa: E402

OUTDIR = ROOT / "out" / "acceptance"
#: 两个已知读数的指纹（用于自动判"这一点的读数属于哪一侧"）
PY_SIDE = (83, 1, 814.0333)
GO_SIDE = (48, 3, 221.6667)


def run_git(args: list[str], cwd: Path | None = None) -> str:
    r = subprocess.run(["git", *args], cwd=str(cwd or ROOT), capture_output=True,
                       text=True, encoding="utf-8")
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} ⇒ rc={r.returncode}: {(r.stderr or '').strip()[:200]}")
    return r.stdout


def tree_sig(tree: Path) -> str:
    """**那棵树**里 `rios-sim/**/*.go` 的内容摘要（与 `engine_pin.source_sig` 同一算法）。"""
    src = sorted((tree / "rios-sim").glob("**/*.go"))
    blob = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in src)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:8]


def build_at(sha: str, keep: bool = False) -> tuple[Path, Path]:
    """在**临时树**里构建该提交的 Go 引擎（不动共享工作树）。返回 (exe, 树根)。"""
    tmp = Path(tempfile.mkdtemp(prefix=f"bisect-{sha[:8]}-"))
    tree = tmp / "t"
    run_git(["worktree", "add", "--detach", str(tree), sha])
    sig = tree_sig(tree)
    exe = (OUTDIR / f"bisect-{sha[:8]}-{sig}.exe") if keep else (tmp / f"rios-sim-{sig}.exe")
    OUTDIR.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(["go", "build", "-buildvcs=false", "-o", str(exe), "."],
                       cwd=str(tree / "rios-sim"), capture_output=True, text=True,
                       encoding="utf-8")
    if r.returncode != 0 or not exe.exists():
        raise RuntimeError(f"构建失败 rc={r.returncode}: {(r.stderr or '').strip()[:300]}")
    return exe, tree


def drop_tree(tree: Path) -> None:
    try:
        run_git(["worktree", "remove", "--force", str(tree)])
    except Exception:                                            # noqa: BLE001
        pass
    shutil.rmtree(tree.parent, ignore_errors=True)


def read_point(exe: Path, plan_path: Path, roster_file: Path) -> dict:
    """钉住这枚 exe 跑一次该 plan，返回读数 + 仪器身份（**计数器是主证**）。"""
    os.environ["RIOS_SIM_BIN"] = str(exe)
    plan = Plan.from_dict(json.loads(plan_path.read_text(encoding="utf-8-sig")))
    roster = Roster.from_json(roster_file)
    v = Verifier(engine="go")
    r = v.run(plan, roster=roster)
    return {"kills": int(r.kills), "leaks": int(r.leaks),
            "elapsed": round(float(r.elapsed), 4), "damage": round(float(r.damage), 1),
            "go_runs": getattr(v, "go_runs", None),
            "go_fallbacks": getattr(v, "go_fallbacks", None),
            "engine": getattr(v, "engine", None)}


def side_of(rec: dict) -> str:
    got = (rec["kills"], rec["leaks"], rec["elapsed"])
    if got == PY_SIDE:
        return "PY 侧（83/1/814.0333）"
    if got == GO_SIDE:
        return "GO 侧（48/3/221.6667）"
    return "**两侧都不是**"


def point(sha: str | None, exe: Path | None, plan: Path, roster_file: Path,
          keep: bool, label: str = "") -> dict:
    t0 = time.perf_counter()
    tree = None
    if exe is None:
        exe, tree = build_at(sha, keep=keep)
    sha16 = hashlib.sha256(exe.read_bytes()).hexdigest()[:16]
    rec = read_point(exe, plan, roster_file)
    rec.update({"at": sha or label, "exe": exe.name, "exe_sha16": sha16,
                "tree_sig": tree_sig(tree) if tree else None,
                "sha16_is_kept": bool(keep), "seconds": round(time.perf_counter() - t0, 1)})
    if tree is not None:
        drop_tree(tree)
    print(f"  {rec['at']:<12} {rec['kills']:>3}杀 {rec['leaks']}漏 {rec['elapsed']:>9.4f}s "
          f"{rec['damage']:>8.1f}　sha16={sha16}　tree_sig={rec['tree_sig']}　"
          f"go_runs={rec['go_runs']} fallbacks={rec['go_fallbacks']}　⇒ {side_of(rec)}"
          f"　({rec['seconds']}s)")
    return rec


def scan(lo: str, hi: str, plan: Path, roster_file: Path, keep: bool,
         json_out: str = "") -> list[dict]:
    """把 `[lo, hi]` 之间**改过 `rios-sim` 的提交**逐条分类（只读；每笔一个临时树，用完即删）。

    三态（**"建不了"与"拒跑"都不是读数，必须与读数分开记**）：
      `建不了`   —— 该提交自己编译不过（半落地的多文件改动）；
      `拒跑`     —— 建得起来，但这枚 exe 里没有当前规格点名的机制（错误文本里点名是哪一个）；
      `读数`     —— 建得起来且跑得出来 ⇒ 记 kills/leaks/elapsed/damage + 仪器三件套。
    """
    shas = [s for s in run_git(["rev-list", "--reverse", f"{lo}..{hi}", "--", "rios-sim"]).split()]
    shas = [lo] + shas
    print(f"扫描 {len(shas)} 笔提交（{lo}..{hi} 之间改过 rios-sim 的）：")
    recs: list[dict] = []
    for sha in shas:
        short = run_git(["rev-parse", "--short", sha]).strip()
        subj = run_git(["log", "-1", "--format=%cI %s", sha]).strip()
        rec: dict = {"at": short, "date": subj.split(" ")[0], "subject": subj.split(" ", 1)[1]}
        try:
            exe, tree = build_at(sha, keep=keep)
        except RuntimeError as e:
            msg = str(e)
            first = [ln for ln in msg.splitlines() if ln.strip() and not ln.startswith("构建失败")]
            rec.update({"kind": "建不了", "detail": (first[0] if first else msg)[:120]})
            print(f"  {short:<9} ⊘ 建不了：{rec['detail']}")
            recs.append(rec)
            continue
        try:
            r = read_point(exe, plan, roster_file)
            rec.update({"kind": "读数", **r, "exe_sha16": hashlib.sha256(exe.read_bytes()).hexdigest()[:16],
                        "tree_sig": tree_sig(tree)})
            print(f"  {short:<9} ✅ {r['kills']}杀 {r['leaks']}漏 {r['elapsed']}s {r['damage']}"
                  f"　sha16={rec['exe_sha16']} tree_sig={rec['tree_sig']}"
                  f"　⇒ {side_of(r)}")
        except Exception as e:                                    # noqa: BLE001
            msg = str(e)
            rec.update({"kind": "拒跑", "detail": msg[:160]})
            print(f"  {short:<9} ⛔ 拒跑：{msg[:110]}")
        finally:
            drop_tree(tree)
        recs.append(rec)
    n_build, n_ref, n_read = (sum(1 for r in recs if r["kind"] == k)
                              for k in ("建不了", "拒跑", "读数"))
    print(f"\n汇总：建不了 {n_build} / 拒跑 {n_ref} / 读数 {n_read}（共 {len(recs)} 笔）")
    for r in recs:
        if r["kind"] == "读数":
            print(f"  {r['at']:<9} {r['kills']}杀 {r['leaks']}漏 {r['elapsed']}s ⇒ {side_of(r)}")
    if json_out:
        p = Path(json_out)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"at": time.strftime("%Y-%m-%d %H:%M:%S"), "plan": str(plan),
                                 "range": f"{lo}..{hi}", "commits": recs},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  落盘：{json_out}")
    return recs


def main() -> int:
    ap = argparse.ArgumentParser(prog="bisect_deepwater.py")
    ap.add_argument("--plan", default="fixtures/hsex8_max.json")
    ap.add_argument("--at", default="", help="某个提交 sha")
    ap.add_argument("--exe", default="", help="现成的 exe（留证副本或本树私有构建）")
    ap.add_argument("--range", default="", help="lo..hi：两端各测一次（lo 应为 PY 侧）")
    ap.add_argument("--scan", default="", help="lo..hi：逐提交分类（建不了/拒跑/读数）")
    ap.add_argument("--verify", default="", help="复核文档记载（暂未实现，见 --help 说明）")
    ap.add_argument("--keep", action="store_true", help="把构建出的 exe 留在 out/acceptance/")
    ap.add_argument("--json", default="", help="落盘 JSON")
    args = ap.parse_args()

    plan = ROOT / args.plan if not Path(args.plan).is_absolute() else Path(args.plan)
    roster_file = G._find("roster_max_modelled")
    print(f"计划={plan.name}　名册={roster_file}　（两枚留证仪器：legacy b3e4d6b1 / 基线 b88b28ce6d0ca14f）")
    recs: list[dict] = []

    if args.scan:
        lo, hi = args.scan.split("..")
        scan(lo.strip(), hi.strip(), plan, roster_file, args.keep, args.json)
        return 0
    if args.exe:
        recs.append(point(None, Path(args.exe), plan, roster_file, args.keep, label="exe"))
    if args.at:
        for sha in args.at.split(","):
            recs.append(point(sha.strip(), None, plan, roster_file, args.keep))
    if args.range:
        lo, hi = args.range.split("..")
        for sha in (lo.strip(), hi.strip()):
            recs.append(point(sha, None, plan, roster_file, args.keep))
    if not (args.exe or args.at or args.range):
        ap.error("至少给 --at / --exe / --range 之一")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(json.dumps(
            {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "plan": str(plan),
             "roster": str(roster_file), "points": recs}, ensure_ascii=False, indent=2),
            encoding="utf-8")
        print(f"  落盘：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
