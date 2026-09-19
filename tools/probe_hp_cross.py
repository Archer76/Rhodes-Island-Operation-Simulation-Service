# -*- coding: utf-8 -*-
"""找**上一个完全一致点**：先问"谁先塌"，再问"谁少打了"。

用法：
    python tools\\probe_hp_cross.py 8                 # k=8，默认目标「去蚀」
    python tools\\probe_hp_cross.py 8 --seq 0         # 只看同名同刻里的第 0 只

背景：`probe_firstdiff.py` 报出首条分岔在 `t=160.6333`，那一刻
**原版 `hp=1145` 还活着、Go `hp=0` 已经塌了**。
本脚本不去看"坐标差了多少"，而是把**两条 hp 时间线并排**摆出来，回答：

  * Go 的这只 **hp 从哪一帧起变 0**？
  * **在同一帧上**原版的 hp 是多少？
  * 再往前，**最后一次两边 hp 相等**是什么时候？（= 上一个完全一致点）

⚠ 纪律：`pos` 痕迹里 Go 侧的 `hp` 列**确实打了**（`sim.go:787` 的 `hp=%.1f` ← `e.hp`），
所以 `hp=0` 是**真死**，不是"这一列没输出"。这和记忆 `223402c9` 的
「POS 按名字门控 ⇒ 不设开关一行不打」是两类不同的坑，用之前先分开验。
"""
from __future__ import annotations

import sys
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

import probe_windup_phase as P                                    # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 8
    seq = int(args[args.index("--seq") + 1]) if "--seq" in args else None
    #: ⚠ **hp 的容差必须 ≥ Go 痕迹的打印精度**：`sim.go:787` 打的是 `hp=%.1f`
    #: （1 位小数），而原版是全精度 ⇒ 两边根本不是一个精度。
    #: 不设容差时"第一次 hp 不等"会停在 `4198.46 vs 4198.5`（差 0.04）这种地方，
    #: 看着像分岔、其实是**打印位数**（记忆 `8970df2a` 同型：`%.7f` 假象误了一轮）。
    #: 默认 0.5 = 半个打印刻度，比它小的差一律不算差。
    tol = float(args[args.index("--hp-tol") + 1]) if "--hp-tol" in args else 0.5

    plan = P.load_plan(k)
    roster = P.load_roster()
    py, pv, _ = P.run_python(plan, roster)
    _got, go, _ = P.run_go(plan, roster)

    def index(frames, want_seq):
        out = {}
        for f in frames:
            key = f["key"]
            if len(key) < 3:
                raise SystemExit(f"键还是老的二元组 {key}——occurrence_seq 没生上")
            if want_seq is not None and key[2] != want_seq:
                continue
            out[(key, round(f["t"], 4))] = f
        return out

    pyi, goi = index(py, seq), index(go, seq)
    common = sorted(set(pyi) & set(goi), key=lambda kk: kk[1])
    if not common:
        print("  没有共同的 (键,帧) —— 目标名字或 seq 挑错了")
        return 1

    keys = sorted({kk[0] for kk in common})
    print(f"  参与比对的键 {len(keys)} 个：{keys[:4]}{' …' if len(keys) > 4 else ''}")
    print(f"  两边的共同帧 {len(common)} 条    hp 容差 {tol}（Go 痕迹精度 %.1f）\n")

    #: 第一次**超出容差**的 hp 差（这才是真分岔；容差内的差是打印位数）
    first_hp = None
    for kk, t in common:
        a, b = pyi[(kk, t)], goi[(kk, t)]
        if abs(a["hp"] - b["hp"]) > tol:
            first_hp = (kk, t, a["hp"], b["hp"])
            break
    if first_hp is None:
        print(f"  ✅ 全程 hp 逐帧相同（在 {tol} 容差内）——分歧不在血量上")
        return 0
    key, t, ph, gh = first_hp
    print(f"  ⛔ 第一次超出容差的 hp 不等：{key}  t={t}")
    print(f"       原版 hp={ph}   Go hp={gh}   差={ph - gh:+.2f}")

    #: 该键上"最后一次在容差内相等"的帧 = 上一个完全一致点
    prev = None
    for kk, tt in common:
        if kk != key or tt >= t:
            continue
        if abs(pyi[(kk, tt)]["hp"] - goi[(kk, tt)]["hp"]) <= tol:
            prev = (tt, pyi[(kk, tt)]["hp"], goi[(kk, tt)]["hp"])
    if prev:
        print(f"  ⬅ 上一个完全一致点：t={prev[0]}  两边 hp 都是 ≈{prev[1]:.1f}")
    else:
        print("  ⬅ 该键上从第一帧起就不在容差内")

    #: 分岔前后各 14 帧并排。⚠ 窗口按**帧时刻**取，不按"第几条"取（条数受别的键影响）；
    #: 并且把窗口内**所有键**都列出来——只看分岔那一个键会看不到"是不是两只搞混了"。
    #: 上一版这里写错了：拿 `key[1]`（出怪时刻）当帧时刻，于是表一行都打不出来。
    print(f"\n  分岔点 {key} t={t} 前后各 14 帧（窗口内所有键，hp / x）")
    print("        t          键                        py_hp      go_hp      py_x        go_x")
    lo = t - 14 / 30.0 - 1e-9
    hi = t + 14 / 30.0 + 1e-9
    shown = 0
    for kk, tt in common:
        if not (lo <= tt <= hi):
            continue
        a, b = pyi[(kk, tt)], goi[(kk, tt)]
        if abs(a["hp"] - b["hp"]) <= tol and abs(a["x"] - b["x"]) <= 1e-9:
            continue                      # 这一帧这一只两边一致，不必占行
        mark = "  ← 分岔" if abs(tt - t) < 1e-9 and kk == key else ""
        print(f"    {tt:9.4f}  {str(kk):24s} {a['hp']:9.1f}  {b['hp']:9.1f}  "
              f"{a['x']:11.7f}  {b['x']:11.7f}{mark}")
        shown += 1
    print(f"    （窗口内不一致的行 {shown} 条）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
