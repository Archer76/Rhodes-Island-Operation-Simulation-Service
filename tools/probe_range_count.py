#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""**不需要比对键**的对拍：逐帧统计"有几个敌人落在某位干员的攻击范围里"。

为什么要有它：本会话在 `act31side_09` 上追了两轮，都卡在**敌人身份对齐**上——
`probe_firstdiff.py` 的键是 `(名字, 出怪时刻)`，而「天桩-乙」有 57 条出怪行、
16 个时刻重复，键一撞车，"两台的差"里就混进"拿甲跟乙比"，报告却和真分歧长得一样
（见 `AK-TACTIC-进度.md` §3.5a）。

这个探针换一条路：**要问的问题本身不需要身份**。
"她这一刻有几个目标可选"是一个**标量**，两台各算各的、再比标量即可——
既不需要跨引擎的敌人身份，也就不会被键撞车污染。

两台各自的口径**刻意对齐**（都按"站进范围格、且 hp>0、未漏、未离场"过滤）：

* 原版：包 `_pick_targets`，另按同一判据自己数一遍（`pick` 会被上限截断，
  所以两个数都报：`cnt` 是完整体，`pick` 是真正被选走的）。
* Go：读 `OPATK` 痕迹的 `inrange=` 与 `pick=` 两列（`|` 连接的名字表）。

用法:
    python tools\\probe_range_count.py 1 --op-idx 0 [--from 0 --to 60]
"""
from __future__ import annotations

import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
sys.stdout.reconfigure(encoding="utf-8")

import trace_kv                                                  # noqa: E402
from probe_windup_phase import load_plan, load_roster            # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 1
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    op_idx = int(args[args.index("--op-idx") + 1]) if "--op-idx" in args else 0
    plan, roster = load_plan(k), load_roster()
    want = plan.deploys[op_idx].operator

    # ---- 原版：包 `_pick_targets`，按同判据另数一遍 ----
    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig_pick = cls._pick_targets
    orig_env = cls._environment_tick
    #: `_pick_targets` 拿不到当前时刻（它只收 `op/cells/n`），而它就在
    #: `_operators_attack(dt, t)` 里被调。所以另挂一处帧首钩子把 `t` 记下来
    #: ——帧序是 3.7 `_environment_tick`(2788) → 6 `_operators_attack`(2848)，
    #: 所以读到的就是**本帧**的 `t`，不是上一帧的。
    state = {"t": 0.0}
    py: list[tuple] = []

    def env(self, dt, t):
        state["t"] = float(t)
        return orig_env(self, dt, t)

    def patched(self, op, cells, *rest):
        #: ⚠ 签名照**调用处**写，不照定义处猜：原版是
        #: `self._pick_targets(op, cells, op.current_max_target())`
        #: （`sim.py:4018`）——第三参是上限，`pick` 会被它截断，
        #: 所以"有几个可选"（`cnt`）与"选走了几个"（`pick`）必须分开报。
        out = orig_pick(self, op, cells, *rest)
        if op.name == want:
            #: 自己数一遍：`_pick_targets` 的返回值会被上限截断，
            #: "有几个可选"与"选走了几个"是两件事。
            cnt = 0
            cs = set(cells)
            for e in self.enemies:
                if e.hp <= 0 or e.leaked or e.off_map:
                    continue
                if (int(round(e.position[0])), int(round(e.position[1]))) in cs:
                    cnt += 1
            py.append((state["t"], cnt, len(out)))
        return out

    cls._pick_targets = patched
    cls._environment_tick = env
    try:
        from probe_snow_damage import PyProbe                    # noqa: E402
        v = PyProbe(verbose=False).run(plan, roster=roster)
    finally:
        cls._pick_targets = orig_pick
        cls._environment_tick = orig_env
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s"
          f"｜{want} 范围内可选数："
          f"最大 {max((c for _, c, _ in py), default=0)}"
          f"，非零帧 {sum(1 for _, c, _ in py if c)}/{len(py)}")

    # ---- Go：同一份规格，读 OPATK 的 inrange= / pick= ----
    from probe_snow_damage import Thief                          # noqa: E402
    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    from ak_tactic.simgo import find_binary                      # noqa: E402
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(p.stderr, "OPATK",
                         ("t", "op", "skill", "interval", "timer", "block",
                          "pick", "inrange", "heals"))

    def _n(s):
        s = (s or "").strip()
        return 0 if not s or s == "-" else len(s.split("|"))

    go = [(float(d["t"]), _n(d["inrange"]), _n(d["pick"]))
          for d in rows if d.get("op") == want and lo <= float(d["t"]) <= hi]
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s"
          f"｜{want} 范围内可选数：最大 {max((c for _, c, _ in go), default=0)}"
          f"，非零帧 {sum(1 for _, c, _ in go if c)}/{len(go)}")

    # ---- 比：同一帧的标量（键只有"时刻"，不涉及任何敌人身份）----
    pyat = {round(t, 4): c for t, c, _ in py if lo <= t <= hi}
    goat = {round(t, 4): c for t, c, _ in go}
    both = sorted(set(pyat) & set(goat))
    if not both:
        print("⚠ 两边的时刻没有交集——先确认窗口与出手机制是否一致，"
              "别把它读成'两边都是 0'")
        return 1
    diffs = [(t, pyat[t], goat[t]) for t in both if pyat[t] != goat[t]]
    print(f"\n共 {len(both)} 帧可比；范围内可选数不同的 {len(diffs)} 帧")
    for t, a, b in diffs[:10]:
        print(f"  t={t:9.4f}  原版 {a}    Go {b}")
    if diffs and len(diffs) > 10:
        print(f"  …（共 {len(diffs)} 帧，只列前 10）")
    print(f"\n首个分歧：{diffs[0] if diffs else '无'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
