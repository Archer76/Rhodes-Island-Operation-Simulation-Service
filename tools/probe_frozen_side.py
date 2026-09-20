# -*- coding: utf-8 -*-
"""两侧同看一只敌人的 frozen 状态（雪冻/冻结两半都看）。

用法：
    python tools\\probe_frozen_side.py 8 81.1 62.0
                              ↑ k  ↑ 时刻  ↑ 出怪时刻（定位是哪一只）

背景：深水定位到 `t=81.1333`，同一次 `SNOWENTRY` 的减伤因子原版 ×0.9、Go ×1.05。
Go 侧 `sim.go:2645 res()` 写着"冻结期间 −15"，且注释明确
「积雪那一半恒定是干员造成的，所以**无条件算友方**」⇒ `10 − 15 = −5` ⇒ ×1.05，逐位吻合。
所以问题变成：**这一帧这只到底冻没冻？两侧看法一样吗？**

⚠ 判据纪律：两侧的 `frozen` 都不是我算的，是各自引擎自己状态里的值
（原版 `EnemyUnit.frozen`；Go 痕迹的 `freeze=`/`latch=` 两列）。这里只做并排，
**不从"血少打了多少"反推冻结状态**。
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
    pos = [a for a in args if not a.startswith("-")]
    k = int(pos[0]) if pos else 8
    when = float(pos[1]) if len(pos) > 1 else 81.1
    at = float(pos[2]) if len(pos) > 2 else 62.0
    key = (P.TARGET, at, 0)

    plan = P.load_plan(k)
    roster = P.load_roster()
    py, _pv, _ = P.run_python(plan, roster)
    _g, go, _ = P.run_go(plan, roster)

    def pick(frames):
        return {round(f["t"], 4): f for f in frames if f["key"] == key}

    pyi, goi = pick(py), pick(go)
    ts = sorted(set(pyi) & set(goi))
    if not ts:
        print(f"  ⚠ 两侧没有共同的帧——键 {key} 可能不对（改用 --idx 或换出怪时刻）")
        return 1

    lo, hi = when - 4 / 30.0, when + 4 / 30.0
    win = [t for t in ts if lo <= t <= hi]
    print(f"  键 = {key}    窗口 t∈[{lo:.4f}, {hi:.4f}]    共 {len(win)} 帧\n")
    print("        t          py_frozen  py_hp      py_x        go_块? go_hp      go_x")
    for t in win:
        a, b = pyi[t], goi[t]
        mark = "  ←" if abs(t - when) < 1e-9 else ""
        print(f"    {t:9.4f}  {str(a['frozen']):9s}  {a['hp']:9.1f}  {a['x']:11.7f}  "
              f"{b['hp']:9.1f}  {b['x']:11.7f}{mark}")

    #: 该键上两侧 frozen 首次不同的帧——这才是"冻结判定"本身的分岔
    diff = [t for t in ts if pyi[t]["frozen"] != goi[t]["frozen"]]
    print()
    if diff:
        print(f"  ⛔ 两侧 frozen 不同的帧共 {len(diff)} 帧，最早 t={diff[0]}")
        for t in diff[:6]:
            print(f"       t={t:9.4f}   py={pyi[t]['frozen']}   go={goi[t]['frozen']}"
                  f"   py_hp={pyi[t]['hp']:.1f} go_hp={goi[t]['hp']:.1f}")
    else:
        print("  ✅ 该键上全程 frozen 两测一致——那减伤因子的差不在冻结判定上。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
