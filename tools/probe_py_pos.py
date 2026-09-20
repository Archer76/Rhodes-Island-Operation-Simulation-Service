# -*- coding: utf-8 -*-
"""盯住**原版**某一只敌人的逐帧状态（`probe_go_pos.py` 的原版孪生）。

为什么必须有它：Go 侧一直有 POS 痕迹可以逐帧看，原版只能靠 `probe_firstdiff`
在**已经分开之后**回头看一眼。本轮就吃过这个亏——残差的表现是"Go 那一格一直冻着"，
而真因是"那一格的首敌在 Go 里晚了 42 秒才离场"，**在原版侧看一眼就能认出来**。

比对键是 **(名字, 出怪时刻)**，与原版列表下标不是一回事。

用法: python tools\probe_py_pos.py 5 --name 去蚀 --spawn 164.0 --from 700 --to 790
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

from probe_windup_phase import load_plan, load_roster            # noqa: E402
import probe_windup_phase as pwp                                  # noqa: E402

args = sys.argv[1:]
k = int(args[0]) if args and not args[0].startswith("-") else 5


def opt(flag, default):
    return args[args.index(flag) + 1] if flag in args else default


name = opt("--name", None)
spawn = float(opt("--spawn", "nan"))
lo = float(opt("--from", "0"))
hi = float(opt("--to", "1e9"))

#: ⚠ `run_python` 的帧表有一句"只记 `TARGET` 那一只"，而 `TARGET` 是
#: `probe_windup_phase` 里**写死的常数**（默认「去蚀」）。不改它就只能看那一种名字，
#: 而"拿它去问场上还有谁"会得到"只有 TARGET"这种**看起来像数据、其实是筛子**的答案。
#: 名字里带全角引号的（`“祟”`）**不要从命令行传**——会被 PowerShell 吃掉，
#: 症状是"帧记录=0"。用 `--spawn` 传时刻，这里换成一个按时刻匹配的谓词。
if name is not None:
    pwp.TARGET = name
    want = None
elif spawn == spawn:
    want = lambda e: abs(float(e.spawn_time) - spawn) < 1e-6   # noqa: E731
else:
    want = None

plan = load_plan(k)
roster = load_roster()
py, pv, _pa = pwp.run_python(plan, roster, target=want)

print(f"原版判决 {pv.kills}杀 {pv.leaks}漏 {pv.elapsed:.6f}s")

if name is None and spawn != spawn:  # nan
    keys = sorted({f["key"] for f in py}, key=lambda x: (x[1], x[0]))
    print(f"共 {len(keys)} 只：")
    for nm, sp in keys:
        print(f"   {nm}  出怪 {sp}")
    raise SystemExit(0)

#: ⚠ 原版**不把死掉的对象移出 `self.enemies`**，所以"最后一帧"往往是死后几百秒
#: 的空转记录。真正的"它什么时候离场"要看**最后一条 hp > 0 的帧**——
#: 本轮就因为这个假信号，把一个 t=735.03 就死了的敌人当成活到 820.1。
if name is None:
    key = next(k for k in {f["key"] for f in py} if abs(k[1] - spawn) < 1e-6)
else:
    key = (name, round(spawn, 3)) if spawn == spawn else \
        next(k for k in {f["key"] for f in py} if k[0] == name)
rows = [f for f in py if f["key"] == key and lo <= f["t"] <= hi]
alive_row = [f for f in py if f["key"] == key]
live_frames = [f for f in alive_row if f["hp"] > 0]
if alive_row:
    last = live_frames[-1] if live_frames else None
    print(f"{key[0]}@{key[1]} 记录 {len(alive_row)} 帧；"
          f"最后存活帧 "
          + (f"t={last['t']:.4f} x={last['x']:.7f} hp={last['hp']:.0f}"
             if last else "（一条都没有）")
          + f"；死后空转到 t={alive_row[-1]['t']:.4f}")
print(f"窗口 [{lo}, {hi}] 内 {len(rows)} 帧"
      f"（t / x / y / hp / pause / atk_timer / interval / blocked / frozen / sluggish）")
for f in rows:
    print(f"   t={f['t']:.4f} x={f['x']:.7f} y={f['y']:.7f} hp={f['hp']:.1f} "
          f"pause={f['pause']:.2f} atk_timer={f['atk_timer']:.4f} "
          f"interval={f['interval']:.4f} blocked={str(f['blocked']):<5} "
          f"frozen={str(f['frozen']):<5} sluggish={f['sluggish']:.3f} "
          f"idle={f['idle']:.3f} root={f['root']:.3f}")
