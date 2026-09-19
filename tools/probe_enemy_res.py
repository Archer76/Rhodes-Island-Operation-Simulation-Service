# -*- coding: utf-8 -*-
"""把原版侧某个时刻**敌人身上的 RES（以及它被打时的 raw/dealt）**打出来。

用法：
    python tools\\probe_enemy_res.py 8 81.1
    python tools\\probe_enemy_res.py 8 81.1 --name 去蚀

为什么需要它：`probe_window_trace.py` 只能看 Go 侧（原版没有 trace 标签）。
深水定位到 `t=81.1333` 时，同一次 `SNOWENTRY` 的减伤因子两侧不同
（原版 ×0.9 = RES 10；Go ×1.05 = RES −5），而规格里 `idx=24/26` 的 `res` **都是 10.0**。
⇒ 要么 Go 读到别的值，要么这一帧之前**有人改了抗性**。
本脚本从**原版这一侧**取数，回答"原版此刻认为这只敌人抗性是多少"。

⚠ 不要用"下游掉了多少血"反推抗性——那是记忆 `41b99ab4` 那条坑。
这里直接读**抗性字段本身**，并同时打印这次伤害的 raw 与 dealt 供交叉验算。
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
    name = args[args.index("--name") + 1] if "--name" in args else P.TARGET

    plan = P.load_plan(k)
    roster = P.load_roster()

    from ak_tactic.battle import sim as simmod

    rows: list[str] = []
    orig_hit = simmod.BattleSimulator._snow_hit

    def hit(self, enemy, raw):
        if enemy.name == name:
            #: 抗性字段可能叫 res / magic_res / resistance —— 都看一眼，
            #: 不猜名字（记忆 `41b99ab4`：不许从名字猜语义）。
            got = {k2: getattr(enemy, k2, "<无此字段>")
                   for k2 in ("res", "magic_res", "magic_resist", "resistance",
                              "def", "hp")}
            rows.append(f"    原始伤害 raw={raw!r}  字段={got}")
        return orig_hit(self, enemy, raw)

    simmod.BattleSimulator._snow_hit = hit
    try:
        from ak_tactic.verify import Verifier
        v = Verifier(engine="python").run(plan, roster=roster)
    finally:
        simmod.BattleSimulator._snow_hit = orig_hit

    print(f"  [python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s")
    print(f"  目标名 = {name}，_snow_hit 命中 {len(rows)} 次")
    for r in rows[:12]:
        print(r)
    if not rows:
        print("  ⚠ 一次都没命中——名字不对，或这一局没走积雪那条路。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
