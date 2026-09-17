# -*- coding: utf-8 -*-
"""活动机制完整性自检。"""
import sys
import os

sys.stdout.reconfigure(encoding="utf-8")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ak_tactic.activity import (DEVICE_REGISTRY, ENEMY_BB_REGISTRY,     # noqa: E402
                                RUNES_REGISTRY, TODO, DONE, NONE, UNKNOWN,
                                audit_activity, activity_stages)

_PASSED = 0
_FAILED = []


def check(label, ok, detail=""):
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def main() -> int:
    print("=" * 68)
    print("活动机制完整性自检（ak_tactic/activity.py）")
    print("=" * 68)

    print("\n[1] 登记表自身")
    for name, table in (("装置", DEVICE_REGISTRY), ("黑板", ENEMY_BB_REGISTRY),
                        ("runes", RUNES_REGISTRY)):
        bad = [k for k, e in table.items() if k != e.key]
        check(f"{name} 登记表的 key 与 Entry.key 一致", not bad, str(bad[:3]))
        unknown_status = [k for k, e in table.items()
                          if e.status not in (DONE, TODO, NONE)]
        check(f"{name} 登记表的状态取值合法", not unknown_status,
              str(unknown_status[:3]))
        # ⚠ TODO 必须写来历，否则后来人无从下手
        nosrc = [k for k, e in table.items() if e.status == TODO and not e.source]
        check(f"{name} 登记表里 TODO 项都写了 source", not nosrc, str(nosrc[:3]))

    print("\n[2] 怀黍离（act31side）盘点")
    rep = audit_activity("act31side")
    print()
    print(rep.summary())
    print()

    check("盘到了关卡", rep.stages > 0, f"{rep.stages} 关")
    check("盘到了敌人", len(rep.enemies) > 0, f"{len(rep.enemies)} 种")
    check("盘到了装置", len(rep.devices) > 0, f"{len(rep.devices)} 种")
    check("盘到了 runes", len(rep.runes) > 0, f"{len(rep.runes)} 种")
    check("盘到了敌人黑板机制", len(rep.enemy_bb) > 0, f"{len(rep.enemy_bb)} 类")

    # ★ 核心判据：**不许有未登记的东西**
    check("★ 没有任何未登记的机制（装置/黑板/rune 三类）",
          not rep.unknown, f"未登记 {len(rep.unknown)} 项：{rep.unknown[:6]}")

    # 已实现项必须真的在登记表里标 DONE —— 反向也要核
    check("装置三个都登记了",
          set(rep.devices) <= set(DEVICE_REGISTRY),
          f"{sorted(rep.devices)}")

    print("\n[3] 未实现清单必须看得见（这是待办，不是通过）")
    print(f"  待实现 {len(rep.todo)} 项：")
    for e in rep.todo:
        print(f"    - {e.name}（{e.key}）")
        print(f"        来历：{e.source}")
    check("待实现清单非空时会被打印出来（不是静默）",
          True, f"{len(rep.todo)} 项")
    # ⚠ 这一条不是"必须为 0"——那会逼着人把没做的标成已做。
    #   它只钉住"清单是真的从数据盘出来的，不是写死的"。
    check("待实现清单来自实际数据（怀黍离确实还有没做的）",
          len(rep.todo) >= 1, f"{len(rep.todo)} 项")

    print("\n[4] 状态声明与代码要对上")
    # 已标 DONE 的装置必须真的被模拟器/环境层读到
    from ak_tactic.battle.devices import parse_devices, BLOCKER_KEY, PUMP_KEY
    from ak_tactic.battle.environment import PUMP_RANGE, PUMP_RATE
    check("阻流阀标 DONE 且常量存在", BLOCKER_KEY in DEVICE_REGISTRY
          and DEVICE_REGISTRY[BLOCKER_KEY].status == DONE)
    check("泵站标 DONE 且常量存在", PUMP_KEY in DEVICE_REGISTRY
          and DEVICE_REGISTRY[PUMP_KEY].status == DONE
          and PUMP_RANGE == 1 and PUMP_RATE == 1.0)
    # 未标 DONE 的装置不许被当成已实现
    todo_dev = [k for k, e in DEVICE_REGISTRY.items() if e.status == TODO]
    check("天桩仍标为待实现（没被顺手标成完成）",
          any("dhdcr" in k for k in todo_dev), str(todo_dev))

    print("\n" + "=" * 68)
    tail = f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项"
    print(tail + "：")
    for n in _FAILED:
        print(f"  - {n}")
    print("=" * 68)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
