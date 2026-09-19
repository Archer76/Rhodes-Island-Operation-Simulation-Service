# -*- coding: utf-8 -*-
"""活动盘点**锚点**的壳依赖自检：解析得到 ≠ 跑起来还对。

【为什么要有这一条】
`tools/check_activity.py` 已经检查了"标 DONE 的条目都写了 anchor，且 anchor 解析得到"。
但 `battle/` 被拆掉的这轮里出现了一种它**看不见**的坏法：

    锚点仍写 `ak_tactic.battle.devices:BLOCKER_KEY`，
    而 devices 的正主已经搬到 `ak_tactic.frontend.devices` ——
    解析之所以还成功，只是因为 `battle/devices.py` 变成了一层**兼容壳**（re-export）。

只要壳还在，`check_activity.py` 全绿；壳一删，这些锚点集体失效，而**盘点的输出一个字都不会变**
（`DONE` 还是 `DONE`），于是没人会立刻发现"它其实已经指不到实现了"。
这就是"解析得到"与"跑起来还对"之间的缝。

【本工具查四件事】
1. **可解析**：模块导得进来、属性取得到（与 check_activity 同层，冗余但便宜）。
2. **不依赖壳**：若同名模块在 `ak_tactic.frontend` 也存在、且两处符号是**同一个对象**，
   则锚点指 `battle.*` 属于**壳依赖** —— 记 FAIL，并给出应改成的目标。
3. **壳没自造副本**：若两处符号**不是**同一个对象，问题更重（壳里复制了一份定义），
   本工具按 FAIL 报出并打印两边的值，便于人工判断哪边是真。
4. **端到端**：`audit_activity("act31side")` 真跑一遍，数字须与冻结基线一致
   （未登记必须为 0 —— 那是本模块自己的纪律：未登记 → UNKNOWN → 自检红）。

【已知边界】
* 「正主在哪」本工具**不靠猜**：判据是"两处都有同名模块且符号同一"，不是"名字里带 battle"。
  因此 `battle.sim` 这类**还没搬**的模块不会被误报（`frontend/sim.py` 尚不存在）。
* 本工具只查**壳依赖**，不查锚点语义是否与条目的正文相符——那件事要人读。
"""
from __future__ import annotations

import importlib
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ak_tactic.activity import (DEVICE_REGISTRY, ENEMY_BB_REGISTRY,  # noqa: E402
                               RUNES_REGISTRY, DONE, audit_activity)

#: 端到端冻结基线。数字变了就要人工确认是**机制增多**（好）还是**盘点漏了**（坏）。
BASELINE = {
    "activity": "act31side",
    "stages": 20,
    "devices": 3,
    "runes": 8,
    "enemies": 20,
    "unknown": 0,
}

#: 搬运期的两个家。判据只认"两处都有同名模块"，不认名字里有没有 battle。
OLD_ROOT = "ak_tactic.battle."
NEW_ROOT = "ak_tactic.frontend."

_passed = 0
_failed: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _passed
    if ok:
        _passed += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _failed.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def resolve(anchor: str):
    """按 `模块:属性` 解析锚点，返回 (对象, 异常)。属性支持点号分层。"""
    mod_name, _, attr = anchor.partition(":")
    try:
        obj = importlib.import_module(mod_name)
    except Exception as exc:  # noqa: BLE001
        return None, exc
    for part in attr.split("."):
        try:
            obj = getattr(obj, part)
        except Exception as exc:  # noqa: BLE001
            return None, exc
    return obj, None


def all_entries():
    """全部登记条目（装置 / runes / 敌人黑板），带来源表名。"""
    out = []
    for table, reg in (("device", DEVICE_REGISTRY), ("runes", RUNES_REGISTRY),
                       ("enemy_bb", ENEMY_BB_REGISTRY)):
        for key, entry in reg.items():
            out.append((table, key, entry))
    return out


def main() -> int:
    print("活动盘点锚点自检（壳依赖 + 端到端）")
    print("=" * 78)

    entries = all_entries()
    print(f"  登记条目 {len(entries)} 条（装置/runes/敌人黑板）")
    with_anchor = [(t, k, e) for t, k, e in entries if getattr(e, "anchor", "")]
    print(f"  其中带 anchor 的 {len(with_anchor)} 条")

    print()
    print("-- 1/2/3 锚点可解析、不依赖壳、壳没自造副本 --")
    broken, shell_dep, shell_copy = [], [], []
    for table, key, entry in with_anchor:
        obj, exc = resolve(entry.anchor)
        if exc is not None:
            broken.append(f"{table}:{key} → {entry.anchor}（{type(exc).__name__}: {exc}）")
            continue
        mod_name = entry.anchor.partition(":")[0]
        if not mod_name.startswith(OLD_ROOT):
            continue
        new_name = NEW_ROOT + mod_name[len(OLD_ROOT):]
        try:
            new_mod = importlib.import_module(new_name)
        except Exception:  # noqa: BLE001
            continue  # 正主还没搬过来（如 battle.sim）⇒ 不算壳依赖
        attr = entry.anchor.partition(":")[2]
        new_obj = new_mod
        ok_attr = True
        for part in attr.split("."):
            if not hasattr(new_obj, part):
                ok_attr = False
                break
            new_obj = getattr(new_obj, part)
        if not ok_attr:
            continue
        if new_obj is obj:
            shell_dep.append(f"{table}:{key} → {entry.anchor}（应改为 {new_name}:{attr}）")
        else:
            shell_copy.append(
                f"{table}:{key} → {entry.anchor}\n"
                f"           壳={obj!r}\n           正主={new_obj!r}")

    check("锚点都解析得到", not broken, "" if not broken else f"{len(broken)} 条坏：{broken[:3]}")
    check("锚点不依赖兼容壳", not shell_dep,
          "" if not shell_dep else f"{len(shell_dep)} 条指向壳：{shell_dep[:3]}")
    check("壳没有自造副本（两处符号同一）", not shell_copy,
          "" if not shell_copy else f"{len(shell_copy)} 条不同：{shell_copy[:2]}")

    print()
    print("-- 4 端到端：audit_activity 真跑一遍，数字对冻结基线 --")
    try:
        rep = audit_activity(BASELINE["activity"], with_enemies=True)
    except Exception as exc:  # noqa: BLE001
        check("audit_activity 跑得起来", False, f"{type(exc).__name__}: {exc}")
        rep = None
    if rep is not None:
        check("audit_activity 跑得起来", True)
        got = {
            "activity": rep.activity,
            "stages": rep.stages,
            "devices": len(rep.devices),
            "runes": len(rep.runes),
            "enemies": len(rep.enemies),
            "unknown": len(rep.unknown),
        }
        print(f"       实测 {got}")
        print(f"       基线 {BASELINE}")
        for field, want in BASELINE.items():
            check(f"基线一致：{field}", got.get(field) == want,
                  f"实测={got.get(field)} 基线={want}")
        # 「未登记 → UNKNOWN → 自检红」是本模块自己的纪律，这里把它变成退出码
        check("未登记数为 0（本模块纪律）", got["unknown"] == 0, f"unknown={got['unknown']}")
        if rep.todo:
            print(f"       （待实现 {len(rep.todo)} 条：是给人看的待办，不影响退出码）")

    print()
    print("=" * 78)
    print(f"通过 {_passed} 项；失败 {len(_failed)} 项")
    for label in _failed:
        print(f"  FAIL: {label}")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
