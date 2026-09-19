# -*- coding: utf-8 -*-
"""一次性对账：直接把某个时刻的坐标打出来，看"分歧从哪一帧起"。

`probe_windup_phase.py --first` 报的是**窗口内**最早那条位移差；真要找"位置第一次
分开"，得把两边同一帧的 x/y 直接相减——本脚本就干这一件事。

用法：
    python tools\\probe_firstdiff.py 3                 # 用模块级默认目标（去蚀）
    python tools\\probe_firstdiff.py 3 --idx 11        # 按**规格出怪表的下标**取名

⚠ **为什么要有 `--idx`**：本会话踩过两次同一个坑。① 中文经 PowerShell 进 `argv`
**会掉第一个字**（「厌肮」→「肮」），于是名字门控对不上、痕迹"一条都没有"；
② 就算名字对，**同名同波的敌人有好几只**，按名字比等于把好几只混在一起比。
按下标取名两个问题一起解决：名字由 Python 从 `spec["spawns"][idx]` 里读出来，
不经过 shell；目标也精确定到某一只。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import probe_windup_phase as P                                # noqa: E402
from probe_windup_phase import load_plan, load_roster, run_go, run_python  # noqa: E402

from ak_tactic.simgo import build_spec                         # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                # noqa: E402


class Thief(GoVerifier):
    spec = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None):
        Thief.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True,
                                     schedule=schedule, env=env)
        raise SystemExit(0)


args = sys.argv[1:]
k = int(args[0]) if args and not args[0].startswith("-") else 3
tol = float(args[1]) if len(args) > 1 and not args[1].startswith("-") else 1e-6

plan = load_plan(k)
roster = load_roster()

if "--idx" in args:
    idx = int(args[args.index("--idx") + 1])
    try:
        Thief().run(plan, roster=roster)
    except SystemExit:
        pass
    spec = Thief.spec
    assert spec is not None, "取不到规格，无法按下标取名"
    spawns = spec.get("spawns") or []
    if not (0 <= idx < len(spawns)):
        raise SystemExit(f"出怪表 {len(spawns)} 条，idx={idx} 越界")
    P.TARGET = spawns[idx].get("name") or ""
    print(f"目标 = 出怪表[{idx}] 的「{P.TARGET}」")

py, pv, _pa = run_python(plan, roster)
_got, go, _ga = run_go(plan, roster)

pyat = {(f["key"], round(f["t"], 4)): f for f in py}
goat = {(f["key"], round(f["t"], 4)): f for f in go}

#: ⚠ **先验键再比数**。本会话的比对键是 `(名字, 出怪时刻)`，而**同名同刻的敌人真的存在**：
#: 「天桩-乙」在 `sim._spawns` 里有 57 条出怪行、其中 16 个时刻是重复的
#: （30.0×2、31.0×3、32.0×2…）。键一撞车，后写的那条就把先写的**覆盖**掉，
#: 于是"两台引擎的差"里混进了"我拿甲跟乙比"——而报告长得和真分歧**一模一样**。
#: 项目文档里的比对键本来就带 `occurrence_seq`（名字 + 出怪时刻 + 第几只），
#: 本脚本没带。在补齐它之前，至少要**大声说出这件事**，不能让它悄悄算完。
#: 判据是"同一 (键, 帧) 出现多条记录"——出现了就一定不可信，而不是"可能"。
from collections import Counter as _C                                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs
_pc = _C((f["key"], round(f["t"], 4)) for f in py)
_gc = _C((f["key"], round(f["t"], 4)) for f in go)
_clash = sum(1 for k in set(_pc) | set(_gc) if _pc[k] > 1 or _gc[k] > 1)
if _clash:
    print(f"⛔ **比对键撞车**：{_clash} 个 (键, 帧) 上有不止一条记录"
          f"（原版 {sum(1 for v in _pc.values() if v > 1)} 处 / "
          f"Go {sum(1 for v in _gc.values() if v > 1)} 处）。")
    print("   键 = (名字, 出怪时刻)，**不含 occurrence_seq** ⇒ 下面的差里"
          "可能混着「拿甲跟乙比」，**不可信**。")
    print("   先按 `--idx` 收窄到某一只、或用带序号的键重做，再读结论。")

found = 0
worst = None
last = None
for key in sorted(set(pyat) & set(goat), key=lambda x: (x[1], x[0][1])):
    a, b = pyat[key], goat[key]
    d = abs(a["x"] - b["x"]) + abs(a["y"] - b["y"])
    if d > tol:
        found += 1
        last = (key, a, b, d)
        if worst is None or d > worst[3]:
            worst = (key, a, b, d)
        if found <= 8:
            print(f"{key[0][0]}@{key[0][1]} t={key[1]:.4f}  "
                  f"py ({a['x']:.7f},{a['y']:.4f}) go ({b['x']:.7f},{b['y']:.4f}) "
                  f"差={a['x'] - b['x']:+.7f}  "
                  f"py frozen={str(a['frozen']):<5} hp={a['hp']:.0f} "
                  f"go hp={b['hp']:.0f}  "
                  f"speed_mult={a['speed_mult']:.4f}")
print(f"共 {found} 条坐标分开（容差 {tol:g}）")

#: ⚠ **只看"头 8 条"会把"一个固定的小偏移"误读成"钉死不动"**——这正是本会话
#: 踩过的坑：天桩-乙 在首 3 帧两边的差是 (0.0156,0.0059) vs (0,0)，看着像 Go
#: 让它原地不动；实际上它一直在走，只是**每一帧都差那么一点**。
#: 所以必须同时报**最大的那一条**与**最后一条**：前者给量级，后者给去向。
if worst is not None:
    key, a, b, d = worst
    print(f"最大差 {d:.7f} @ {key[0][0]}@{key[0][1]} t={key[1]:.4f}  "
          f"py ({a['x']:.7f},{a['y']:.7f}) go ({b['x']:.7f},{b['y']:.7f})")
if last is not None and last is not worst:
    key, a, b, d = last
    print(f"最后一条 t={key[1]:.4f}  差={d:.7f}  "
          f"py ({a['x']:.7f},{a['y']:.7f}) go ({b['x']:.7f},{b['y']:.7f})")

# 参考：这只敌人在分歧前后几帧的原版移速分量（看是谁改了速度）
if found:
    key0 = sorted(set(pyat) & set(goat), key=lambda x: (x[1], x[0][1]))
    first = next(k for k in key0
                 if abs(pyat[k]["x"] - goat[k]["x"]) + abs(pyat[k]["y"] - goat[k]["y"]) > tol)
    ident, t0 = first
    print(f"\n{ident[0]}@{ident[1]} 在 t={t0:.4f} 前后各 12 帧的原版移速分量")
    print(f"{'t':>9} {'x':>11} {'speed_mult':>10} {'haste':>7} {'slow_pct':>9} "
          f"{'lock_slow':>10} {'move':>7} {'root':>6} {'idle':>6} {'sluggish':>9}")
    for k in key0:
        if k[0] != ident or not (t0 - 0.45 <= k[1] <= t0 + 0.45):
            continue
        f = pyat[k]
        print(f"{k[1]:9.4f} {f['x']:11.7f} {f['speed_mult']:10.4f} {f['haste']:7.4f} "
              f"{f['slow_pct']:9.4f} {f['lock_slow']:10.4f} {f['move_speed']:7.4f} "
              f"{f['root']:6.3f} {f['idle']:6.3f} {f['sluggish']:9.3f}")
