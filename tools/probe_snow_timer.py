#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""原版侧积雪计时器的**逐帧真值**。

为什么非要有这个：Go 侧 `timer` 从 5.5 单调降到 -27.87、`cast` 一次都没发生，
但"该不该发生"取决于那个判据在**浮点上**到底是真是假。原版同一时刻的
`timer` 是多少、第一次 `cast` 落在第几帧，是唯一能定案的东西。

做法：拿同一份 `sim`，在 `SnowField.tick` 外面裹一层，把每帧的
`(时刻, timer, 层数)` 记下来。**不改原版代码**——只包不写。

用法: python tools\probe_snow_timer.py [k] [--from 56.3 --to 56.9]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.battle import talents as T                   # noqa: E402
from ak_tactic.plan import Plan, Roster                      # noqa: E402
from ak_tactic.verify import Verifier                        # noqa: E402


def _fixture(name: str) -> Path:
    for base in (ROOT, ROOT.parent / "ak-tactic-head"):
        p = base / "out" / name
        if p.exists():
            return p
    raise SystemExit(f"找不到 {name}")


def main() -> int:
    args = sys.argv[1:]
    k = int(args[0]) if args and not args[0].startswith("-") else 3
    lo = float(args[args.index("--from") + 1]) if "--from" in args else 0.0
    hi = float(args[args.index("--to") + 1]) if "--to" in args else 9e9
    dbg_lo, dbg_hi = lo, hi

    rows: list[tuple[float, float, int, bool]] = []
    speeds: list[tuple[float, str, float, float, str]] = []
    orig_tick = T.SnowField.tick

    def wrapped(self, *a, **kw):
        #: 包在**外面**：先记"这一帧进来时的 timer"，再让它自己跑，
        #: 然后把"跑完之后"的 timer / 层数也记下来。差值就能看出
        #: 这一帧到底有没有 `cast`（cast 会让 timer 减去一个 interval）。
        before = self.timer
        out = orig_tick(self, *a, **kw)
        t = frame["t"]
        rows.append((t, before, self.timer, len(self.layers)))
        #: 同一帧里顺手记敌人在哪一格、移速乘区是多少。
        #: 这两列就是原版 `speed_multiplier` 的现场，是"差一帧"的唯一判据。
        for e in frame["enemies"]:
            try:
                #: 敌人名字的位置随原版结构变过（`e.name` / `e.spec.name`），
                #: 两个都试，别写死——写死的那次症状是"窗口里一行都没有"。
                nm = (getattr(e, "name", None)
                      or getattr(getattr(e, "spec", None), "name", None)
                      or "?")
                sm = getattr(e, "speed_multiplier", None)
                if sm is None:
                    sm = getattr(getattr(e, "spec", None), "speed_multiplier", -1.0)
                cell = getattr(e, "cell", None) or getattr(e, "pos", None)
                speeds.append((t, str(nm), float(getattr(e, "x", 0.0)),
                               float(sm), str(cell)))
            except Exception:
                pass
        return out

    T.SnowField.tick = wrapped
    #: `layers` 换成一个会记账的字典：**每一次增删都记一笔**。
    #:
    #: 为什么要这么细：`tick` 之后的总格数只告诉你"变了"，而"8→7"这一格到底是
    #: 谁、在哪一帧、按哪条规则拿掉的，只有盯住字典本身才看得见。清雪有两条路
    #: （`enter` 里离开旧格、`leave_all` 离场），包方法只覆盖了其中一条时
    #: 症状就是"改了但没打出来"。
    class Ledger(dict):
        def __setitem__(self, k, v):
            if dbg_lo <= frame["t"] <= dbg_hi and self.get(k) != v:
                print(f"   [层数+] t={frame['t']:.4f} {k} "
                      f"{self.get(k)}→{v}（共 {len(self)}→{len(self) + (0 if k in self else 1)}）")
            super().__setitem__(k, v)

        def __delitem__(self, k):
            if dbg_lo <= frame["t"] <= dbg_hi:
                print(f"   [层数-] t={frame['t']:.4f} {k} 被删（共 {len(self)}→{len(self) - 1}）")
            super().__delitem__(k)

        def pop(self, k, *a):
            if k in self and dbg_lo <= frame["t"] <= dbg_hi:
                print(f"   [层数-pop] t={frame['t']:.4f} {k} 被删（共 {len(self)}→{len(self) - 1}）")
            return super().pop(k, *a)

    orig_init = T.SnowField.__init__

    def init_wrapped(self, *a, **kw):
        orig_init(self, *a, **kw)
        self.layers = Ledger(self.layers or {})

    T.SnowField.__init__ = init_wrapped
    #: 清雪的两条路各包一层：`enter` 里"离开旧格"那一支、以及 `leave_all`。
    #: 只包不写——原版的任何一行都不动。
    orig_enter = T.SnowField.enter
    orig_leave = T.SnowField.leave_all

    def enter_wrapped(self, enemy_id, cell, atk, damage_fn):
        prev = self.last_cell.get(enemy_id)
        out = orig_enter(self, enemy_id, cell, atk, damage_fn)
        if dbg_lo <= frame["t"] <= dbg_hi:
            print(f"   [enter] t={frame['t']:.4f} id={enemy_id} "
                  f"{prev}→{cell} 首敌(prev)={self.first_enemy.get(prev)} "
                  f"层={self.layers.get(cell)} 返回={out}")
        return out

    def leave_wrapped(self, enemy_id):
        prev = self.last_cell.get(enemy_id)
        out = orig_leave(self, enemy_id)
        if dbg_lo <= frame["t"] <= dbg_hi:
            print(f"   [清雪·离场] t={frame['t']:.4f} 敌人id={enemy_id} 上一格 {prev}")
        return out

    T.SnowField.enter = enter_wrapped
    T.SnowField.leave_all = leave_wrapped
    #: `_snow_tick` 每帧调 `sf.tick(dt)`；时刻从 sim 上拿不到，改用帧计数
    #: 换算（30fps）。这样不必改原版的任何一行。
    frame: dict = {"n": 0, "t": 0.0, "enemies": []}
    orig_snow_tick = None
    try:
        from ak_tactic.battle import sim as S
        #: `_snow_tick` 在哪个类上：按名字找，不写死类名（原版换过组织方式）。
        owner_cls = None
        for nm in dir(S):
            obj = getattr(S, nm)
            if isinstance(obj, type) and hasattr(obj, "_snow_tick"):
                owner_cls = obj
                break
        if owner_cls is None:
            raise RuntimeError("没找到挂着 _snow_tick 的类")
        orig_snow_tick = owner_cls._snow_tick

        def snow_tick_wrapped(self, *a, **kw):
            frame["t"] = frame["n"] / 30.0
            frame["n"] += 1
            frame["enemies"] = list(getattr(self, "enemies", []) or [])
            return orig_snow_tick(self, *a, **kw)

        owner_cls._snow_tick = snow_tick_wrapped
        print(f"（已挂在 {owner_cls.__name__}._snow_tick 上）")
    except Exception as exc:  # pragma: no cover - 只为诊断
        print(f"⚠ 包 _snow_tick 失败：{exc}")

    raw = json.loads(_fixture("hsex8_max.json").read_text(encoding="utf-8"))
    raw = dict(raw, deploys=raw["deploys"][:k])
    v = Verifier().run(Plan.from_dict(raw),
                       roster=Roster.from_json(_fixture("roster_max_modelled.json")))
    print(f"原版 {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s"
          f"  `tick` 共被调用 {len(rows)} 次")

    # 找出所有"层数变化"的帧：那才是真正 `cast` 成功的时刻
    casts = [r for i, r in enumerate(rows)
             if i and r[3] != rows[i - 1][3]]
    print(f"层数发生变化 {len(casts)} 次；头 4 次：")
    for t, before, after, n in casts[:4]:
        print(f"   t={t:.4f} timer {before:.6f}→{after:.6f} 层数格数={n}")
    win = [r for r in rows if lo <= r[0] <= hi]
    print(f"\n窗口 [{lo}, {hi}] 内 {len(win)} 帧（t, 进来时timer, 出去时timer, 格数）：")
    for t, before, after, n in win:
        print(f"   t={t:.4f} in={before:.6f} out={after:.6f} 格={n}")

    # ---- 敌人移速乘区逐帧表（与原版 `speed_multiplier` 那一列同源）----
    #
    # 这段才是"两边差一格/差一帧"这类分歧的判据：判决只在偏差累积到改变
    # 胜负时才动，而移速是一帧一步的。
    if "--speed" in args and speeds:
        name = args[args.index("--speed") + 1]
        names = sorted({nm for _, nm, _, _, _ in speeds})
        print(f"\n（记到的敌人名共 {len(names)} 种：{names[:12]}）")
        print(f"敌人「{name}」的移速分量（窗口内）：")
        for t, nm, x, sm, cell in speeds:
            if nm == name and lo <= t <= hi:
                print(f"   t={t:.4f} x={x:.7f} speed_mult={sm:.4f} cell={cell}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
