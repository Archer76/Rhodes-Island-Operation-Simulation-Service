#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓 Go 侧积雪的**逐笔**痕迹（`HITENEMY` / `SPEED`）。

为什么要单独一个：`RIOS_TRACE=1` 全开时 stderr 是洪水（几 MB），
而这里只要两类行。也顺手把"第一笔踏入伤害发生在哪一刻、多少点"直接给出来——
那正是与原版日志里 `积雪伤害 626 → 去蚀` 对得上的那个数。

用法: python tools\probe_snow_trace.py [k] [--pos 敌人名]
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


def load_plan(k: int) -> Plan:
    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    if k:
        raw = dict(raw, deploys=raw["deploys"][:k])
    return Plan.from_dict(raw)


class Thief(GoVerifier):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spec = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title):
        self.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True)
        raise SystemExit(0)


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    pos = ""
    if "--pos" in args:
        pos = args[args.index("--pos") + 1]
    #: 抓哪一族痕迹。默认 `HITENEMY`（实际伤害），`SNOWENTER` 看的是
    #: "`enter` 到底被调用了几次、那一刻层数是几"——两族要分开看：
    #: 伤害为 0 既可能是"没被调用"，也可能是"被调用了但那一格没雪"。
    tag = "HITENEMY"
    if "--tag" in args:
        tag = args[args.index("--tag") + 1]

    thief = Thief()
    try:
        thief.run(load_plan(k), roster=Roster.from_json(
            _fixture("roster_max_modelled.json")))
    except SystemExit:
        pass
    spec = thief.spec
    assert spec is not None, "没偷到规格"
    #: 探针只关心机制，把 max_time 收短一点不影响前 100 秒的对拍，
    #: 但能让 stderr 小一个量级。
    exe = find_binary()
    env = dict(os.environ, RIOS_TRACE="1")
    if pos:
        env["RIOS_TRACE_POS"] = pos
    p = subprocess.run([str(exe)],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=env)
    resp = json.loads(p.stdout.strip().splitlines()[-1])
    if not resp.get("ok"):
        raise SystemExit(f"Go 拒跑：{resp.get('error')}")
    got = resp["verdict"]
    print(f"Go 判决 {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"总伤害={float(got.get('damage_dealt') or 0):,.1f}")

    err = p.stderr or ""
    #: `SNOWT` 是 `SNOWTICKT` 的子串，按"行首就是它 + 后面跟空格"过筛，
    #: 否则拿 `--tag SNOWT` 会捞回一堆 `SNOWTICKT`。
    hits = [ln for ln in err.splitlines()
            if re.search(rf"(^|\s){re.escape(tag)}\b", ln)]
    print(f"\n{tag} 共 {len(hits)} 笔（前 20 笔 + 末 3 笔）：")
    for ln in hits[:20]:
        print("   " + ln.strip())
    if len(hits) > 23:
        print("   ……")
        for ln in hits[-3:]:
            print("   " + ln.strip())
    #: 只看某一小段（`--around 56.5` 打它前后各若干笔）。
    #: 为什么要它：`tick` 每帧一行，真正出问题的那一帧埋在几千行里；
    #: "计时器有没有跌破 interval"这种事必须看**那几帧**才判得出来。
    if "--around" in args:
        centre = float(args[args.index("--around") + 1])
        span = 6
        win = [ln for ln in hits
               if re.search(r"t=([\d.]+)", ln)
               and abs(float(re.search(r"t=([\d.]+)", ln).group(1)) - centre) <= span]
        print(f"\n{tag} = {centre:.2f}±{span}s 内共 {len(win)} 笔：")
        for ln in win:
            print("   " + ln.strip())

    # 逐笔伤害的分布：与原版日志里那几个值（626 / 557）对得上吗
    vals: dict[str, int] = {}
    for ln in hits:
        m = re.search(r"raw=[\d.]+.*dealt=([\d.]+)", ln)
        if m:
            vals[m.group(1)] = vals.get(m.group(1), 0) + 1
    if vals:
        top = sorted(vals.items(), key=lambda kv: -kv[1])[:8]
        print(f"\ndealt 值分布（前 8）：{top}")
    spd = [ln for ln in err.splitlines() if "SPEED" in ln]
    print(f"SPEED 变更共 {len(spd)} 笔，前 8 笔：")
    for ln in spd[:8]:
        print("   " + ln.strip())

    # ---- 施放者的"在不在场"：`SNOWSKIP` 是"不在场所以不积层"那条痕迹 ----
    #
    # 面一定要看：雪"一片都没积起来"最常见的原因就是**施放者死了/没部署**，
    # 而那个分支**不产生任何伤害**——判决退回"没有雪"的数值，看起来像
    # "机制没接线"，实际是"人不在场上"。
    ticks, skips = [], []
    for ln in err.splitlines():
        m = re.search(r"(SNOWTICKT|SNOWSKIP) t=([\d.]+)", ln)
        if not m:
            continue
        (ticks if m.group(1) == "SNOWTICKT" else skips).append(float(m.group(2)))
    if skips:
        print(f"\nSNOWSKIP（施放者不在场）共 {len(skips)} 笔："
              f"首 {skips[0]:.4f}s 末 {skips[-1]:.4f}s")
        # 找**第一次**变成"不在场"的时刻：那之前它还在积层
        first = skips[0]
        before = [t for t in ticks if t < first]
        if before:
            print(f"  最后一次成功积层在 t={before[-1]:.4f}s，"
                  f"此后不再积层（施放者已退场）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
