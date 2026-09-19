#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**痕迹全键差分**：两枚 exe 在同一规格下，痕迹键与计数差在哪。

## 硬要求（PM 2026-09-20 00:06）

> ⚠ **不许"找 snow 相关的键"——要列出两次运行里出现的【全部痕迹键及计数】，再做差。**

理由：**找一个预先选定的键，找到的是"我预期的那条"，不是"实际变了的那条"**（关键记忆 `875a7e55`：
窗口探针要列窗口内所有键）。所以本工具无条件输出**两张全键表**，再给三类差：
**只在 A 侧出现 / 只在 B 侧出现 / 两侧都有但计数不同**。对 `snow.*` 那一族的判断**放在最后**，
且只是全表的一个子集，不享有任何优先权。

## 仪器纪律（都是今晚栽过的）

* **同一份规格**：规格由 `SpecCapture` 从**当前 Python 侧**构建**一次**，两枚 exe 收到**逐字节同一份**
  （`spec_sha` 打在表头）。**唯一变量＝exe**。
* **环境逐项相同**：两次调用传**同一个 env**；`RIOS_TRACE` 的门控值写在表头（门控不同会被读成"键不同"）。
* **解析不出的行必须报数**：痕迹解析一失配，输出就是"0 笔"，**与"真的没有记录"长得一模一样**
  ⇒ 表头打 `未解析行数`，非零时打印前几行原样。
* **没跑起来的 exe 不算"计数为 0"**：判定回执里 `kills` 等要打出来，跑失败直接报错退出。

用法:
    python tools\\trace_key_diff.py                      # 默认：19:08 留证副本 ↔ 当轮自建自钉
    python tools\\trace_key_diff.py --exe-a <a.exe> --exe-b <b.exe>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                        # noqa: E402
import golden_go as G                                          # noqa: E402
import trace_kv                                                # noqa: E402
from engine_pin import ensure_pinned                           # noqa: E402

LEGACY = ROOT / "out" / "acceptance" / "rios-sim-legacy-1908_b3e4d6b1.exe"


def ident(p: Path) -> dict:
    st = p.stat()
    return {"exe": p.name, "sha16": hashlib.sha256(p.read_bytes()).hexdigest()[:16],
            "bytes": st.st_size, "mtime": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}


def build_spec(plan_file: Path, roster_file: Path) -> tuple[dict, str]:
    """用**当前 Python 侧**构建一份规格；`spec_sha` 就是"两枚 exe 收到的输入是否同一份"的判据。"""
    v = G.SpecCapture()
    plan = Plan.from_dict(json.loads(plan_file.read_text(encoding="utf-8-sig")))
    roster = Roster.from_json(roster_file)
    try:
        v.run(plan, roster=roster)          #: 走到 Go 之前就把规格摘下来了
    except Exception as e:                                     # noqa: BLE001
        if v.spec is None:
            raise RuntimeError(f"规格都没摘到：{type(e).__name__}: {e}") from e
    assert v.spec is not None
    return v.spec, G.canonical_sha(v.spec)


def run_exe(exe: Path, spec: dict, trace_env: dict, window: float | None = None,
            dump: Path | None = None) -> dict:
    """跑一枚 exe，按**全部键**计数；`window` 给定时另出一份"只算 `t <= window`"的计数。

    ⚠ **为什么必须有同窗那一栏**：两次运行的**时长不同**（814.03 s ↔ 221.67 s），
    所以**原始总数不可比**——实测 `SNOWTICKT` A=24422 / B=6651，看着像"雪变少了"，
    除下来**两边都是 30.0 次/秒**。这类差是**时长差**，不是机制差。
    """
    p = subprocess.run([str(exe)], input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, **trace_env))
    out_lines = [ln for ln in (p.stdout or "").strip().splitlines() if ln.strip()]
    if p.returncode != 0 or not out_lines:
        raise RuntimeError(f"{exe.name} 没跑起来：rc={p.returncode} stderr 尾="
                           f"{(p.stderr or '').strip().splitlines()[-1][:200] if (p.stderr or '').strip() else '（空）'}")
    verdict = json.loads(out_lines[-1]).get("verdict") or {}
    if dump is not None:
        #: `--dump-stderr <目录>`：把两侧**原始 stderr** 各落一份盘。
        #: 为什么要有这个出口：本工具交的是**计数级**结论（同窗键计数），
        #: 而"同键同 t 两侧取值不同"这类**坐标级**问题，计数答不了——
        #: 那是另一问，需要原始痕迹。**别让下一个会话为了同样一份 stderr 再跑一遍。**
        dump.mkdir(parents=True, exist_ok=True)
        f = dump / f"stderr-{exe.stem}-{hashlib.sha256(exe.read_bytes()).hexdigest()[:8]}.txt"
        f.write_text(p.stderr or "", encoding="utf-8")
        print(f"  [dump] {f}（{len((p.stderr or '').splitlines())} 行）")
    keys: Counter = Counter()
    keys_w: Counter = Counter()          #: 只算 t <= window（同窗可比的那一栏）
    tags: Counter = Counter()
    unparsed: list[str] = []
    n_lines = n_notrace = 0
    for ln in (p.stderr or "").splitlines():
        if not ln.strip():
            continue
        n_lines += 1
        got = trace_kv.parse_trace(ln)
        if got is None:
            n_notrace += 1
            if len(unparsed) < 5:
                unparsed.append(ln.strip()[:140])
            continue
        tag, d = got
        tags[tag] += 1
        inwin = True
        if window is not None:
            try:
                inwin = float(d.get("t", "0")) <= window + 1e-9
            except ValueError:
                inwin = True
        for k in d:
            keys[(tag, k)] += 1
            if inwin:
                keys_w[(tag, k)] += 1
    return {"verdict": {k: verdict.get(k) for k in
                        ("kills", "leaks", "elapsed", "damage", "won", "deployed", "timed_out")},
            "stderr_lines": n_lines, "unparsed_n": n_notrace,
            "unparsed_sample": unparsed, "tags": dict(tags),
            "keys": {f"{t}.{k}": c for (t, k), c in keys.items()},
            "keys_in_window": {f"{t}.{k}": c for (t, k), c in keys_w.items()}}


def table(title: str, rec: dict, window: float | None) -> None:
    print(f"\n=== {title}：全键表（共 {len(rec['keys'])} 个 键）===")
    el = float(rec["verdict"].get("elapsed") or 0) or 0
    print(f"  判决 {rec['verdict']}　stderr 行 {rec['stderr_lines']}"
          f"　未解析行 {rec['unparsed_n']}" + (f"　例：{rec['unparsed_sample']}" if rec["unparsed_sample"] else ""))
    print(f"  标签计数 {dict(sorted(rec['tags'].items(), key=lambda kv: -kv[1]))}")
    print(f"  （**本表是全程总数**；因为两次运行时长不同，总数不可直接互比——"
          f"本行 elapsed={el:.4f}s，同窗表见下）")
    for k in sorted(rec["keys"]):
        print(f"    {k:<34} {rec['keys'][k]:>9}")


def main() -> int:
    ap = argparse.ArgumentParser(prog="trace_key_diff.py")
    ap.add_argument("--plan", default="fixtures/hsex8_max.json")
    ap.add_argument("--exe-a", default=str(LEGACY), help="A 侧（默认＝19:08 留证副本）")
    ap.add_argument("--exe-b", default="", help="B 侧（默认＝当轮自建自钉）")
    ap.add_argument("--pos-gate", default="", help="RIOS_TRACE_POS 的名字门控（两次都用同一个值）")
    ap.add_argument("--json", default="out/acceptance/trace-key-diff.json")
    ap.add_argument("--dump-stderr", default="", help="把两侧原始 stderr 落盘到这个目录"
                                                    "（给需要按 t 取值对齐的会话直接消费）")
    args = ap.parse_args()

    a = Path(args.exe_a)
    if not a.exists():
        print(f"⛔ A 侧 exe 不在场：{a}")
        return 2
    if args.exe_b:
        b = Path(args.exe_b)
        if not b.exists():
            print(f"⛔ B 侧 exe 不在场：{b}")
            return 2
    else:
        b, _, _ = ensure_pinned(verbose=False)

    plan_file = ROOT / args.plan
    roster_file = G._find("roster_max_modelled")
    spec, spec_sha = build_spec(plan_file, roster_file)
    trace_env = {"RIOS_TRACE": "1"}
    if args.pos_gate:
        trace_env["RIOS_TRACE_POS"] = args.pos_gate

    print(f"计划={plan_file.name}　名册={roster_file}")
    print(f"**同一份规格**：spec_sha={spec_sha}（两枚 exe 收到逐字节同一份）")
    print(f"**同一套环境**：{trace_env}")
    print(f"A＝{ident(a)}")
    print(f"B＝{ident(b)}")

    #: 先跑 B（拿到它的全程时长 W），再跑 A 并**只统计 t <= W** 的那一段。
    dump = Path(args.dump_stderr) if args.dump_stderr else None
    rb = run_exe(b, spec, trace_env, dump=dump)
    w = float(rb["verdict"]["elapsed"] or 0)
    ra = run_exe(a, spec, trace_env, window=w, dump=dump)
    #: B 的全程**就是**同窗那一段（W 取自它自己），所以它的同窗计数＝全程计数。
    rb["keys_in_window"] = dict(rb["keys"])
    print(f"（同窗窗长 W = {w:.4f}s ＝ B 的全程；A 只统计 t <= W 的痕迹）")
    table(f"A · {a.name}", ra, w)
    table(f"B · {b.name}", rb, w)

    ka, kb = ra["keys"], rb["keys"]
    wa, wb = ra["keys_in_window"], rb["keys_in_window"]
    only_a = sorted(set(ka) - set(kb))
    only_b = sorted(set(kb) - set(ka))
    diff = sorted(((k, ka[k], kb[k]) for k in set(ka) & set(kb) if ka[k] != kb[k]),
                  key=lambda kv: -abs(kv[1] - kv[2]))
    el_a, el_b = float(ra["verdict"]["elapsed"]), float(rb["verdict"]["elapsed"])
    win = min(el_a, el_b)
    print(f"\n=== 同窗表（t <= {win:.4f}s ＝ 两次运行里较短的那一次全程）===")
    print("  ⚠ 这一栏才是**可比**的：两次运行时长不同，全程总数会把时长差读成机制差")
    print(f"  {'键':<34}{'A同窗':>9}{'B同窗':>9}{'Δ':>9}　{'A/秒':>9}{'B/秒':>9}")
    allk = sorted(set(wa) | set(wb))
    rows = []
    for k in allk:
        x, y = wa.get(k, 0), wb.get(k, 0)
        if x == y and x == 0:
            continue
        rows.append((k, x, y, y - x))
    rows.sort(key=lambda r: -abs(r[3]))
    for k, x, y, d in rows:
        rx = x / win if win else 0
        ry = y / win if win else 0
        mark = "" if d == 0 else ("　★" if (x == 0 or y == 0) else "")
        print(f"  {k:<34}{x:>9}{y:>9}{d:>+9}　{rx:>9.4f}{ry:>9.4f}{mark}")

    print("\n=== 差（三类；★＝一侧为 0，即「只有一侧有这个键」）===")
    print(f"  只在 A 侧出现（{len(only_a)}）：" + ("、".join(f"{k}({ka[k]})" for k in only_a) or "（无）"))
    print(f"  只在 B 侧出现（{len(only_b)}）：" + ("、".join(f"{k}({kb[k]})" for k in only_b) or "（无）"))
    print(f"  全程计数不同（{len(diff)}）：")
    for k, x, y in diff[:40]:
        pct = (y - x) / x * 100 if x else float("inf")
        print(f"    {k:<34} A={x:>8}  B={y:>8}　Δ={y - x:+d}（{pct:+.1f}%）")
    if len(diff) > 40:
        print(f"    …… 其余 {len(diff) - 40} 条见 JSON")
    #: **同窗仍不同**的那些键，才是"不是时长造成的差"
    survive = [(k, wa.get(k, 0), wb.get(k, 0)) for k in allk
               if wa.get(k, 0) != wb.get(k, 0)]
    survive.sort(key=lambda kv: -abs(kv[2] - kv[1]))
    print(f"\n=== ★ 同窗归一后**仍然不同**的键（{len(survive)} 个）＝不是时长造成的差 ===")
    for k, x, y in survive[:30]:
        print(f"    {k:<34} A={x:>8}  B={y:>8}　Δ={y - x:+d}")
    if len(survive) > 30:
        print(f"    …… 其余 {len(survive) - 30} 条见 JSON")

    snow = [k for k in set(ka) | set(kb) if k.lower().startswith("snow")]
    print(f"\n=== 最后才看 snow 一族（{len(snow)} 个键；它们不享有任何优先权）===")
    for k in sorted(snow):
        print(f"    {k:<34} 全程 A={ka.get(k, '（无此键）')} B={kb.get(k, '（无此键）')}"
              f"　同窗 A={wa.get(k, '—')} B={wb.get(k, '—')}")

    Path(args.json).parent.mkdir(parents=True, exist_ok=True)
    Path(args.json).write_text(json.dumps(
        {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "plan": str(plan_file), "spec_sha": spec_sha,
         "trace_env": trace_env, "window": win,
         "a": ident(a), "b": ident(b), "a_run": ra, "b_run": rb,
         "only_a": only_a, "only_b": only_b,
         "count_diff": [{"key": k, "a": x, "b": y} for k, x, y in diff],
         "count_diff_in_window": [{"key": k, "a": x, "b": y} for k, x, y in survive]},
        ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n落盘：{args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
