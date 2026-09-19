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

    ⚠ **袋语义（bag semantics）**：同一 `(标签, t)` **可以有多行**（同帧多段伤害），
`(t, enemy, idx, src)` **也不是唯一键**（实测 A 有 224 组重复、B 有 188 组，且组内行不全同）。
⇒ 逐帧值对必须比"该键下 `dealt` 的**多重集**"，**不许拿 `t` 当行键**（`dict.setdefault(t,{})`
会把多行静默合并 ⇒ 造假点＋漏点）。本工具按 `(标签,键)` 计数＝袋计数，并在开头打印
每个 exe 的"同 t 多行"组数，使这件事在读数里可见。

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
    #: ★ **袋语义的可见化**（UI_2b 2026-09-20 00:53 报的同族假信号）：同一 `(标签, t)` **可以有多行**
    #: （同帧多段伤害）。若拿 `t` 当行键做逐帧值对，`dict.setdefault(t,{})` 会把多行**静默合并**
    #: ⇒ **造假点 ＋ 漏点**（实测他那版：得 9 处不同，其中 1 处是假点、另漏 3 处）。
    #: 本工具按 `(标签,键)` **计数**，计数本身就是袋计数（所以躲过了这一枪）；
    #: 但**一旦做逐帧值对就会撞上** ⇒ 这里把"每 t 有多少行"量出来打印，
    #: 让"我在做袋比较"这件事**在读数里看得见**，而不是靠读代码才知道。
    rows_per_t: Counter = Counter()
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
        rows_per_t[(tag, str(d.get("t", "?")))] += 1
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
    _dup = [c for c in rows_per_t.values() if c > 1]
    return {"bag": {"groups": len(rows_per_t), "multi_row_groups": len(_dup),
                    "max_rows_in_one_t": max(rows_per_t.values()) if rows_per_t else 0,
                    "rows_in_multi": sum(_dup),
                    "note": "同 (标签,t) 多行 ⇒ 逐帧值对必须比多重集（袋），不可拿 t 当行键"},
            "verdict": {k: verdict.get(k) for k in
                        ("kills", "leaks", "elapsed", "damage", "won", "deployed", "timed_out")},
            "stderr_lines": n_lines, "unparsed_n": n_notrace,
            "unparsed_sample": unparsed, "tags": dict(tags),
            "keys": {f"{t}.{k}": c for (t, k), c in keys.items()},
            "keys_in_window": {f"{t}.{k}": c for (t, k), c in keys_w.items()}}


#: ── 值序列（袋语义）逐点分类 ────────────────────────────────────────────────
#: UI_2b 2026-09-20 01:23 要的第三件事：**不能归类的差异点逐处列出**。
#: 口径写在表头里，因为「(t, idx)」与「(t, enemy, idx, src)」不是同一件事。
FACTORS = ((1.18750, "0.95/0.80"), (1.16667, "1.05/0.90"), (0.84211, "0.80/0.95"),
           (0.85714, "0.90/1.05"), (1.10000, "1.10"), (0.90909, "1.00/1.10"))


def num(d: dict, k: str):
    """取数值字段：取不到就回 None（**不假装成 0**——0 会静默参与比较）。"""
    try:
        return float(d.get(k))
    except (TypeError, ValueError):
        return None


def _bags(evs, tag: str, t0: float, t1: float, group_by):
    """按 `group_by` 建 **袋**（多重集）：同键多行**不合并**，行数本身是信息。"""
    out = {}
    for t, tg, d in evs:
        if tg != tag or not (t0 - 1e-9 <= t <= t1 + 1e-9):
            continue
        k = group_by(t, d)
        if k is None:
            continue
        out.setdefault(k, []).append(d)
    return out


def series_report(ea, eb, tag: str, t0: float, t1: float) -> list:
    """逐点分类，**未归类逐处打印**（不许给它一个像的名字）。返回未归类清单。"""
    def gb(t, d):
        idx = d.get("idx")
        return None if idx in (None, "") else (round(t, 4), str(idx))

    ba = _bags(ea, tag, t0, t1, gb)
    bb = _bags(eb, tag, t0, t1, gb)
    keys = sorted(set(ba) | set(bb))
    cls = {"相同": 0, "截断": [], "因子族": [], "换目标": [], "袋不可配对": [], "未归类": []}
    for k in keys:
        la, lb = ba.get(k, []), bb.get(k, [])
        if not la or not lb:
            cls["换目标"].append((k, len(la), len(lb)))
            continue
        da = sorted(num(x, "dealt") or 0 for x in la)
        db = sorted(num(x, "dealt") or 0 for x in lb)
        if da == db:
            cls["相同"] += 1
            continue
        hps = [num(x, "hp") or 0 for x in la + lb]
        if min(hps) <= 0:
            cls["截断"].append((k, da, db))
            continue
        if len(da) != len(db):
            cls["袋不可配对"].append((k, da, db))
            continue
        sa, sb = sum(da), sum(db)
        hit = None
        if sb:
            r = sa / sb
            for f, why in FACTORS:
                if abs(r - f) < 1e-4:
                    hit = why
                    break
        if hit is None and len(da) == len(db):
            #: ★ **多行袋里只有一个成员差一个因子**（实测 5 处：`[17.577,17.577,40.362,696.0]`
            #: 对 `[…,826.5]`）——按**总和**比是抓不到的（其余成员相同会把比值稀释掉），
            #: 所以按**逐成员配对**再判一次。两条规则都写在这儿，谁命中就标谁。
            diffs = [(x, y) for x, y in zip(da, db) if abs(x - y) > 1e-9]
            if len(diffs) == 1:
                x, y = diffs[0]
                if y:
                    rr = x / y
                    for f, why in FACTORS:
                        if abs(rr - f) < 1e-4:
                            hit = why + "（袋内单成员）"
                            break
        if hit:
            cls["因子族"].append((k, hit, da, db))
        else:
            cls["未归类"].append((k, da, db))

    print(f"\n=== 值序列（袋语义）逐点分类：标签 {tag}，窗 [{t0:g}, {t1:g}] ===")
    print("  口径：键 = (t, idx)；同一 (t,idx) 的 dealt 取**多重集**（同 t 多行不合并）；"
          "分类优先级＝截断 → 袋不可配对 → 因子族 → 未归类")
    print(f"  点数：相同 {cls['相同']}　截断 {len(cls['截断'])}　袋不可配对 {len(cls['袋不可配对'])}"
          f"　因子族 {len(cls['因子族'])}　换目标(一侧无此 idx) {len(cls['换目标'])}"
          f"　**未归类 {len(cls['未归类'])}**")
    for k, why, da, db in cls["因子族"][:10]:
        print(f"    [因子族 {why}] t={k[0]:.4f} idx={k[1]}　A={da}　B={db}")
    if len(cls["因子族"]) > 10:
        print(f"    …… 其余 {len(cls['因子族']) - 10} 处因子族")
    for k, da, db in cls["袋不可配对"][:10]:
        print(f"    [袋不可配对 ⚠] t={k[0]:.4f} idx={k[1]}　A={da}　B={db}（行数不同 ⇒ 不许按序硬对）")
    for k, n, m in cls["换目标"][:10]:
        print(f"    [换目标] t={k[0]:.4f} idx={k[1]}　A 行数={n}　B 行数={m}（一侧无此 idx）")
    print(f"  ★ **未归类（逐处列出，不给它一个像的名字）** {len(cls['未归类'])} 处：")
    for k, da, db in cls["未归类"]:
        print(f"    未归类 t={k[0]:.4f} idx={k[1]}　A 袋={da}　B 袋={db}")
    return cls["未归类"]


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


ROOT_DEFAULT = Path(__file__).resolve().parent.parent / "out" / "acceptance" / "trace-stderr"


def main() -> int:
    ap = argparse.ArgumentParser(prog="trace_key_diff.py")
    ap.add_argument("--plan", default="fixtures/hsex8_max.json")
    ap.add_argument("--exe-a", default=str(LEGACY), help="A 侧（默认＝19:08 留证副本）")
    ap.add_argument("--exe-b", default="", help="B 侧（默认＝当轮自建自钉）")
    ap.add_argument("--pos-gate", default="", help="RIOS_TRACE_POS 的名字门控（两次都用同一个值）")
    ap.add_argument("--series", action="store_true",
                    help="只做值序列（袋语义）逐点分类：截断/袋不可配对/因子族/换目标/未归类逐处列出")
    ap.add_argument("--series-tag", default="DMGENEMY", help="--series 用哪个标签（默认 DMGENEMY）")
    ap.add_argument("--series-a", help="--series：A 侧 dump 路径（缺省按 --dump-stderr 目录＋exe 名＋sha16 推导）")
    ap.add_argument("--series-b", help="--series：B 侧 dump 路径")
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

    if args.series:
        #: ⚠ **只读 dump、不跑 exe**，而且**缺文件就拒跑**：
        #: `run_exe` 只回汇总、不回原始行 ⇒ 早先那版会拿到空列表，于是"逐点分类 0 处"
        #: 长得和"两侧完全一致"一模一样——**静默空＝最坏的一类假绿**。
        dump_dir = Path(args.dump_stderr) if args.dump_stderr else ROOT_DEFAULT
        want = []
        for _f, _explicit in ((a, args.series_a), (b, args.series_b)):
            if _explicit:
                want.append(Path(_explicit))
                continue
            _h = hashlib.sha256(_f.read_bytes()).hexdigest()[:8]
            want.append(dump_dir / f"stderr-{_f.stem}-{_h}.txt")
        missing = [x for x in want if not x.is_file()]
        if missing:
            print("⛔ 拒跑（rc=3）：逐点分类需要的原始痕迹不在场：")
            for x in missing:
                print(f"    缺 {x}")
            print("  取得方式：python tools/trace_key_diff.py --dump-stderr out/acceptance/trace-stderr"
                  "（先跑一次计数级，它会顺手把两侧 stderr 各落一份盘）")
            return 3
        _loaded = []
        for _f in want:
            _lst = []
            for _ln in _f.read_text(encoding="utf-8", errors="replace").splitlines():
                _g = trace_kv.parse_trace(_ln)
                if _g:
                    try:
                        _lst.append((float(_g[1].get("t", "nan")), _g[0], _g[1]))
                    except ValueError:
                        pass
            _loaded.append(_lst)
        if len(_loaded) != 2 or not _loaded[0] or not _loaded[1]:
            print(f"⛔ 拒跑（rc=3）：一侧事件数为 0（A={len(_loaded[0]) if _loaded else 0}"
                  f"／B={len(_loaded[1]) if len(_loaded) > 1 else 0}）⇒ 不许把空读成'两侧一致'。")
            return 3
        _ea, _eb = _loaded
        _w = max([t for t, _tg, _d in _eb], default=0.0)
        print(f"== 逐点分类（袋语义）：A={want[0].name}（{len(_ea)} 事件）"
              f"　B={want[1].name}（{len(_eb)} 事件）　窗 [0, {_w:.4f}] ==")
        series_report(_ea, _eb, args.series_tag, 0.0, _w)
        return 0

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
    for _lab, _rec in (("A", ra), ("B", rb)):
        _b = _rec.get("bag") or {}
        print(f"  [袋语义 {_lab}] {_b.get('groups')} 个 (标签,t) 组，其中**同 t 多行** "
              f"{_b.get('multi_row_groups')} 组（最多 {_b.get('max_rows_in_one_t')} 行，"
              f"共 {_b.get('rows_in_multi')} 行）"
              f" ⇒ {'⚠ 有同帧多行：做逐帧值对必须比多重集' if _b.get('multi_row_groups') else '无同帧多行'}")
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
