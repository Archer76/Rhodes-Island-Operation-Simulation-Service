#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""按**下标**看某一只敌人的逐帧坐标（Go 侧）。

为什么按下标而不是按名字：对拍里同名同波的敌人很多（HS-EX-8 的"去蚀""厌肮"
各有好几只），按名字看会同时捞回好几只，逐帧比就无从比起。Go 的 POS 痕迹里
本来就有 `idx`，按它过筛才分得清是哪一只。

用法: python tools\probe_go_pos.py 3 --idx 9 --from 70 --to 74
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
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace_kv                                               # noqa: E402
from probe_windup_phase import load_plan, load_roster          # noqa: E402

from ak_tactic.plan import Plan, Roster                        # noqa: E402
from ak_tactic.simgo import build_spec, find_binary            # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


class Thief(GoVerifier):
    spec = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        Thief.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
        raise SystemExit(0)


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    idx = int(args[args.index("--idx") + 1]) if "--idx" in args else 9
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    name = args[args.index("--name") + 1] if "--name" in args else ""

    #: 夹具统一走 `probe_windup_phase.load_plan/load_roster`：它们认 `RIOS_PLAN`
    #: 与 `RIOS_ROSTER`，于是换关卡只改环境变量，不必再复制一份探针。
    plan = load_plan(k)
    roster = load_roster()
    try:
        Thief().run(plan, roster=roster)
    except SystemExit:
        pass
    spec = Thief.spec
    assert spec is not None
    #: `RIOS_TRACE_POS` 只按名字门控，所以先按名字收窄，再按 idx 精筛。
    #:
    #: ⚠ `--tag` 那条路**不需要敌人下标**（`OPDMG`/`HITOP`/`DEPLOYDMG` 都是
    #: 干员侧或机制侧的痕迹）。早先这里无条件 `spawns[idx]`，于是拿 `--tag OPDMG`
    #: 看干员承伤时会被 `IndexError` 拦下——**"我想看的东西跟下标无关"这件事，
    #: 探针不该替我做主**。取不到就退成空名字（不做名字门控），而不是崩。
    if not name:
        spawns = spec.get("spawns") or []
        if 0 <= idx < len(spawns):
            name = spawns[idx].get("name") or ""
        else:
            name = ""
            print(f"（出怪表 {len(spawns)} 条，idx={idx} 越界 ⇒ 不做名字门控）")
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1", RIOS_TRACE_POS=name))
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s"
          f"（名字门控={name}，精筛 idx={idx}）")
    #: `--raw`：直接把 Go 的原话打出来，不走解析。
    #:
    #: 为什么要有这个模式：`POS` 那一行的列**会随排查需要增删**，而排查时最想看
    #: 的恰恰是"我没想到的那一列"。解析一失配，输出就是"0 帧"，与"这只敌人真的
    #: 没被记录"长得一模一样——**仪器坏了却报成事实**。
    #: 现在主路径已经走 `trace_kv`（自描述拆键，加列不会再失配），
    #: `--raw` 仍然保留：它是"解析器本身也可疑"时的最后一道退路。
    #: `--tag <痕迹名>`：把某一族痕迹原样打出来（按 `t=` 过时间窗）。
    #:
    #: 为什么需要：`POS` 只是痕迹里的一族，而"属性被改成了多少"这种问题
    #: 根本不产生 POS——它要的是 `PM2` / `PHIT` 这种**只在改写点上打**的痕迹。
    #: 各写一个探针就会漏掉"我没想到的那一族"，所以这里统一按 tag 取。
    if "--tag" in args:
        tag = args[args.index("--tag") + 1]
        hit = 0
        for ln in (p.stderr or "").splitlines():
            s = ln.strip()
            if not s.startswith(tag + " "):
                continue
            m = re.search(r"t=([\d.]+)", s)
            if m and not (lo <= float(m.group(1)) <= hi):
                continue
            print("   " + s)
            hit += 1
        print(f"窗口 [{lo}, {hi}] 内 {tag} 痕迹 {hit} 笔")
        return 0

    if "--raw" in args:
        pat = re.compile(rf"POS t=[\d.]+ idx={idx} ")
        t0 = lo - 1e-9
        hit = 0
        for ln in (p.stderr or "").splitlines():
            if not pat.search(ln):
                continue
            m = re.search(r"POS t=([\d.]+)", ln)
            if m and t0 <= float(m.group(1)) <= hi:
                print("   " + ln.strip())
                hit += 1
        print(f"窗口 [{lo}, {hi}] 内 {hit} 帧（原样）")
        return 0

    #: 走共用解析器（`trace_kv`）：**自描述拆键**，以后加列不必改这里。
    #: 缺列会当场报错，不会退化成"0 帧"。
    rows = []
    for d in trace_kv.pos_rows(p.stderr, "POS"):
        if int(d["idx"]) != idx:
            continue
        t = float(d["t"])
        if lo <= t <= hi:
            rows.append(d)
    #: ⚠ 0 帧分两种：**这只敌人真的不在**，或者**名字门控没覆盖它**。
    #: 两者在这条路上长得一样，所以把"这一轮一共打出多少 POS 行"一并报出来
    #: ——它能把"这一只没有"与"整体没打"分开。
    total = len(trace_kv.pos_rows(p.stderr, "POS"))
    print(f"窗口 [{lo}, {hi}] 内 {len(rows)} 帧（本轮 POS 共 {total} 行）："
          f"t / x / y / hp / blocked / pause / sluggish / freeze / snow / latch / leg / legu")
    for d in rows:
        print(f"   t={float(d['t']):.4f} x={trace_kv.fnum(d, 'x'):.7f} "
              f"y={trace_kv.fnum(d, 'y'):.4f} hp={trace_kv.fnum(d, 'hp'):.1f} "
              f"blocked={d.get('blocked', '-'):<5} "
              f"pause={trace_kv.fnum(d, 'pause'):.2f} "
              f"sluggish={trace_kv.fnum(d, 'sluggish'):.2f} "
              f"freeze={trace_kv.fnum(d, 'freeze'):.4f} "
              f"snow={d.get('snow', '-'):<5} latch={d.get('latch', '-'):<5} "
              f"leg={d.get('leg', '-')} legu={trace_kv.fnum(d, 'legu'):.7f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
