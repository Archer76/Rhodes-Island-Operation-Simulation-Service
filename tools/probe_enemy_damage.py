#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""敌人承伤**逐账对拍**：两边各自按 (名字, 出怪时刻) 汇总，"谁多挨了多少"一眼可见。

## 为什么是这个口径

第 3 手的位移已经**逐帧零差异**、杀/漏/用时也全同，可总伤害仍差 1,392 点。
位移相同说明"谁在哪一帧站在哪"没错；杀漏相同说明"谁在什么时候死"没错。
那这 1,392 只能是**承伤账**上的差——而它分散在好几条路径里
（普攻 / 溅射 / 机制直伤 / 积雪踏入），单看任何一条的痕迹都拼不出总数。

两边都从**唯一汇点**取数：
* 原版：钩 `Combatant.take`（`unit.py:104`，敌人受伤的唯一入口）；
* Go：`DMGENEMY` 痕迹（打在同名的唯一汇点上，`sim.go` 的 `enemy.take`）。

按 (名字, 出怪时刻) 汇总后**逐项比**，差在哪一只身上就直接指出来了。

⚠ 汇总键为什么不用下标：下标的赋值在两台引擎里可能不同源（召唤物走另一套编号），
而 (名字, 出怪时刻) 是两边都有的、且是既定的对拍键。

用法: python tools\\probe_enemy_damage.py 3
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import trace_kv                                                # noqa: E402
from probe_windup_phase import load_plan, load_roster          # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    plan, roster = load_plan(k), load_roster()

    # ---- 原版：钩唯一汇点 ----
    from ak_tactic.battle import unit as U
    py: dict[tuple[str, float], float] = defaultdict(float)
    #: 逐笔清单：定位到"哪一只"之后还要看"哪一笔"——差 1,392.00 这种整数
    #: 多半是**某一笔整个多出来/少掉**，逐笔并排一眼就能认出来。
    pyhits: dict[tuple, list] = defaultdict(list)
    pyname: dict[int, tuple[str, float]] = {}
    pstate = {"t": -1.0, "seq": {}}
    orig_take = U.Combatant.take

    def take(self, amount):
        r = orig_take(self, amount)
        key = getattr(self, "_probe_key", None)
        if key is not None and r > 0:
            py[key] += r
            pyhits[key].append((pstate["t"], r, self.hp))
        return r

    U.Combatant.take = take

    from ak_tactic.battle import sim as S
    cls = next(o for o in (getattr(S, n) for n in dir(S))
               if isinstance(o, type) and hasattr(o, "_environment_tick"))
    orig_env = cls._environment_tick

    def env(self, dt, t):
        pstate["t"] = t
        for e in getattr(self, "enemies", ()) or ():
            if id(e) not in pyname:
                #: ⚠ 键必须带**同名同刻的出现次序**：`(名字, 出怪时刻)` 本身
                #: 会合并重名（厌肮@12.0 在出怪表里是 idx 6 与 idx 7 两只），
                #: 合并之后就只剩"这一族总共挨了多少"，定位不到具体那一只。
                #: 出怪表按排期顺序展开，出现次序因此与 Go 侧的下标同序。
                base = (getattr(e, "name", "?"), round(float(e.spawn_time), 3))
                seq = pstate["seq"].get(base, 0)
                pstate["seq"][base] = seq + 1
                key = (base[0], base[1], seq)
                pyname[id(e)] = key
                #: 挂在实例上比查表快，也避免 id() 复用导致的错配。
                try:
                    e._probe_key = key
                except Exception:
                    pass
        return orig_env(self, dt, t)

    cls._environment_tick = env

    from probe_snow_damage import PyProbe                    # noqa: E402
    v = PyProbe(verbose=False).run(plan, roster=roster)
    U.Combatant.take = orig_take
    cls._environment_tick = orig_env
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s "
          f"承伤账合计 {sum(py.values()):,.2f}（{len(py)} 只）"
          f"  回执 damage_dealt={v.result.damage_dealt:,.2f}")

    # ---- Go：同规格，读 DMGENEMY ----
    from probe_snow_damage import Thief                      # noqa: E402
    thief = Thief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    _sim, spec = thief.held
    from ak_tactic.simgo import find_binary                   # noqa: E402
    p = subprocess.run([str(find_binary())],
                       input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8",
                       env=dict(os.environ, RIOS_TRACE="1"))
    rows = trace_kv.rows(p.stderr, "DMGENEMY", ("t", "enemy", "dealt"))
    #: 出怪时刻不在痕迹里——用同名字的在原版侧的出怪时刻配对会串（同名同刻有重复）。
    #: 所以 Go 侧只按**名字**汇总，够用来定位"是哪一族敌人"，再往下才需要逐只。
    go: dict[str, float] = defaultdict(float)
    goidx: dict[tuple[str, str], float] = defaultdict(float)
    for d in rows:
        go[d["enemy"]] += float(d["dealt"])
        goidx[(d["enemy"], d["idx"])] += float(d["dealt"])
    pyby: dict[str, float] = defaultdict(float)
    for (n, _s, _q), val in py.items():
        pyby[n] += val
    got = json.loads(p.stdout.strip().splitlines()[-1])["verdict"]
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"承伤账合计 {sum(go.values()):,.2f}（{len(rows)} 笔）"
          f"  回执 damage_dealt={float(got.get('damage_dealt') or 0):,.2f}")

    print(f"\n{'敌人':<10} {'原版承伤':>14} {'Go 承伤':>14} {'差':>12}")
    bad = 0
    for name in sorted(set(pyby) | set(go), key=lambda n: -abs(pyby.get(n, 0) - go.get(n, 0))):
        a, b = pyby.get(name, 0.0), go.get(name, 0.0)
        flag = ""
        if abs(a - b) > 0.5:
            flag = "  ← 差"
            bad += 1
        print(f"{name:<10} {a:>14,.2f} {b:>14,.2f} {b - a:>+12,.2f}{flag}")
    print(f"\n合计差 {sum(go.values()) - sum(py.values()):+,.2f}；"
          f"承伤不同的敌人 {bad} 类")

    #: 差在某一族身上时，继续往**具体那几只**缩：Go 侧按痕迹里的 `idx`
    #: （= 出怪表排期位置），原版侧按 (名字, 出怪时刻)。两列并排看谁对不上。
    #: ⚠ 原版侧同名同刻会有**多只**（厌肮@12.5 就是 idx 8/9 两只），
    #: 所以这里只能看出"这一族里哪几只的账不对"，逐只对齐要靠位置痕迹。
    for name in sorted(set(pyby) | set(go)):
        if abs(pyby.get(name, 0.0) - go.get(name, 0.0)) <= 0.5:
            continue
        print(f"\n—— 「{name}」逐只（原版：名字+出怪时刻 / Go：下标）——")
        pyrows = sorted([(s, q, t) for (n, s, q), t in py.items() if n == name])
        gorows = sorted([(int(i), t) for (n, i), t in goidx.items() if n == name],
                        key=lambda x: x[0])
        for j in range(max(len(pyrows), len(gorows))):
            a = pyrows[j] if j < len(pyrows) else None
            b = gorows[j] if j < len(gorows) else None
            sa = f"@{a[0]:<7.3f}#{a[1]} {a[2]:>11,.2f}" if a else " " * 22
            sb = f"idx={b[0]:<4d} {b[1]:>12,.2f}" if b else " " * 22
            d = "" if (a and b) else "   ← 只有一边有"
            if a and b and abs(a[2] - b[1]) > 0.5:
                d = f"   ← 差 {b[1] - a[2]:+,.2f}"
            print(f"  {sa}   | {sb}{d}")

    #: 再往下一层：把**逐笔**并排列出来。差一个整数（如 1,392.00）时，
    #: 逐笔清单能直接指出"是某一笔整个多了"，而不是"每一笔都大了 3%"。
    #:
    #: ⚠ **两种给法，优先用 `--hits-idx`**：敌人名在 PowerShell 里往返会**掉字符**
    #: （「厌肮」变成「肮」、「除秽」变成「秽」——恰好各少第一个字），
    #: 于是 `--hits 厌肮@0.0#0` 会安静地匹配到 0 笔，看着像"两边都没有这一笔"。
    #: `--hits-idx N` 只传一个整数：取**第一条承伤不同的敌人**，再取它第 N 行，
    #: 名字全程不出命令行。
    key = want_idx = None
    if "--hits-idx" in args:
        j = int(args[args.index("--hits-idx") + 1])
        nm = next((n for n in sorted(set(pyby) | set(go))
                   if abs(pyby.get(n, 0.0) - go.get(n, 0.0)) > 0.5), None)
        if nm is None:
            print("\n（没有承伤不同的敌人，`--hits-idx` 无从取）")
        else:
            pyrows = sorted([(k[1], k[2], k) for k in py if k[0] == nm])
            gorows = sorted([(int(i), t) for (n, i), t in goidx.items() if n == nm])
            if j >= min(len(pyrows), len(gorows)):
                print(f"\n（「{nm}」只有 {len(pyrows)}/{len(gorows)} 行，取不到第 {j} 行）")
            else:
                key = (nm, pyrows[j][0], pyrows[j][1])
                want_idx = gorows[j][0]
    elif "--hits" in args:
        want = args[args.index("--hits") + 1]          # 形如 厌肮@12.0#0
        nm, rest = want.split("@")
        sp, sq = rest.split("#")
        key = (nm, float(sp), int(sq))
        #: ⚠ **不要**用"这一族第 sq 个下标"去推 Go 的下标：同名的敌人可能来自
        #: 不同的出怪时刻（厌肮@0.0 与 @12.0 在同一族里），推出来的会是另一只。
        #: 下标要**显式给**（来自 `probe_enemy_index.py`）。
        want_idx = int(args[args.index("--go-idx") + 1]) if "--go-idx" in args else None

    if key is not None:
        gohits = [(float(d["t"]), float(d["dealt"]), float(d["hp"]), d["idx"])
                  for d in rows if d["enemy"] == key[0] and int(d["idx"]) == want_idx]
        ph = pyhits.get(key, [])
        print(f"\n—— 逐笔：「{key[0]}@{key[1]:.3f}#{key[2]}」（Go idx={want_idx}）"
              f"原版 {len(ph)} 笔 / Go {len(gohits)} 笔 ——")
        for j in range(max(len(ph), len(gohits))):
            a = ph[j] if j < len(ph) else None
            b = gohits[j] if j < len(gohits) else None
            sa = f"t={a[0]:8.4f} dealt={a[1]:9.2f} hp={a[2]:9.2f}" if a else " " * 36
            sb = f"t={b[0]:8.4f} dealt={b[1]:9.2f} hp={b[2]:9.2f}" if b else " " * 36
            d = ""
            if a and b and (abs(a[0] - b[0]) > 1e-4 or abs(a[1] - b[1]) > 0.01):
                d = f"   ← 差 {b[1] - a[1]:+,.2f} / Δt {b[0] - a[0]:+.4f}"
            elif a is None or b is None:
                d = "   ← 只有一边有"
            print(f"  {j:>3} {sa} | {sb}{d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


