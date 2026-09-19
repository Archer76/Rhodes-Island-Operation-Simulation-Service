#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把某一帧的移速分量**逐帧并排**：原版 vs Go。

判据（与对拍纪律一致）：同一时间线、只比可观测量。这里看的可观测量是
"这一刻这一只敌人在哪一格、移速乘区是多少、x 走了多远"。

为什么必须并排：判决只在偏差累积到改变胜负时才动；而"两边差一帧开始减速"
这种分歧，先表现为**几毫米的 x 差**，几百帧之后才变成"少杀一只"。
单独看任何一侧都读不出"谁先谁后"。

用法: python tools\probe_speed_side.py 3 --enemy 去蚀 --from 71.5 --to 73.0
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle import talents as T                   # noqa: E402
from ak_tactic.plan import Plan, Roster                      # noqa: E402
from ak_tactic.simgo import build_spec, find_binary          # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier              # noqa: E402
from ak_tactic.verify import Verifier                        # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


def load(k: int) -> tuple[Plan, Roster]:
    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    return (Plan.from_dict(dict(raw, deploys=raw["deploys"][:k])),
            Roster.from_json(_fixture("roster_max_modelled.json")))


def py_rows(plan: Plan, roster: Roster, enemy: str, spawn: float,
            lo: float, hi: float) -> list[str]:
    """原版逐帧：x、所在格、speed_multiplier。"""
    rows: list[tuple[float, float, str, float, float]] = []
    frame = {"t": 0.0, "n": 0, "enemies": []}
    orig_tick = T.SnowField.tick

    def wrapped(self, *a, **kw):
        out = orig_tick(self, *a, **kw)
        t = frame["t"]
        for e in frame["enemies"]:
            if getattr(e, "name", None) == enemy and \
                    abs(getattr(e, "spawn_time", -1) - spawn) < 1e-6:
                x, y = float(e.position[0]), float(e.position[1])
                rows.append((t, x, f"({int(round(x))},{int(round(y))})",
                             float(getattr(e, "speed_multiplier", -1)),
                             float(getattr(e, "leg_u", -1))))
        return out

    T.SnowField.tick = wrapped
    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_snow_tick"))
    orig = cls._snow_tick

    def st(self, *a, **kw):
        frame["t"] = frame["n"] / 30.0
        frame["n"] += 1
        frame["enemies"] = list(getattr(self, "enemies", []) or [])
        return orig(self, *a, **kw)

    cls._snow_tick = st
    try:
        Verifier().run(plan, roster=roster)
    finally:
        T.SnowField.tick = orig_tick
        cls._snow_tick = orig
    return [f"t={t:.4f} x={x:.7f} cell={c} speed_mult={sm:.4f} legu={lu:.5f}"
            for t, x, c, sm, lu in rows if lo <= t <= hi]


def go_rows(plan: Plan, roster: Roster, enemy: str,
            lo: float, hi: float) -> list[str]:
    """Go 逐帧：从 `RIOS_TRACE_POS` 的坐标痕迹 + 机制的乘区痕迹并起来。"""
    class Thief(GoVerifier):
        spec = None

        def _run_other_engine(self, *, sim, plan, stage, deployed, title):
            Thief.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
            raise SystemExit(0)

    try:
        Thief().run(plan, roster=roster)
    except SystemExit:
        pass
    spec = Thief.spec
    assert spec is not None
    env = dict(os.environ, RIOS_TRACE="1", RIOS_TRACE_POS=enemy,
               RIOS_SNOW_DBG=f"{lo},{hi}")
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8", env=env)
    want_spawn = None
    slow: dict[float, float] = {}
    for ln in (p.stderr or "").splitlines():
        if "SNOWSLOW" in ln:
            m = re.search(r"t=([\d.]+).*?mult=([\d.]+)", ln)
            if m:
                slow[round(float(m.group(1)), 4)] = float(m.group(2))
    out = []
    for ln in (p.stderr or "").splitlines():
        m = re.search(r"\bPOS t=([\d.]+).*x=([-\d.]+) y=([-\d.]+).*legu=([\d.]+)", ln)
        if not m:
            continue
        t = float(m.group(1))
        if not (lo <= t <= hi):
            continue
        out.append((t, float(m.group(2)), float(m.group(3)), float(m.group(4))))
    out.sort()
    return out, slow


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    enemy = args[args.index("--enemy") + 1] if "--enemy" in args else "去蚀"
    spawn = float(args[args.index("--spawn") + 1]) if "--spawn" in args else 54.0
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    plan, roster = load(k)

    py = py_rows(plan, roster, enemy, spawn, lo, hi)
    print(f"=== 原版 {enemy}@{spawn} 共 {len(py)} 帧 ===")
    for ln in py:
        print("   " + ln)
    go, slow = go_rows(plan, roster, enemy, lo, hi)
    print(f"\n=== Go 逐帧（窗口内 {len(go)} 帧）===")
    for t, x, y, legu in go[:60]:
        print(f"   t={t:.4f} x={x:.7f} y={y:.4f} legu={legu:.7f}")
    print(f"\n=== Go 乘区变化（窗口内 {len(slow)} 笔）===")
    for t in sorted(slow):
        print(f"   t={t:.4f} mult={slow[t]:.4f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
