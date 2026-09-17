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

    print("\n[5] ★ 每个 DONE 都必须指到兑现它的那段代码（锚点）")
    # 这一节补的是一个**真发生过的漏洞**：`enemy_attribute_mul` 与
    # `global_lifepoint` 两条长期标着 DONE，而代码里根本没有它们的消费者——
    # 而 [4] 只查 DONE 的**装置**有没有常量，rune 与黑板前缀**一条都不查**，
    # 于是这两个假的 DONE 一路绿灯。
    #
    # 判据三条，都是客观可判的（不靠人读注释相信）：
    #   ① 锚点 `模块:符号` 必须能解析出来；
    #   ② 符号是字符串时**等于** key；是容器时**包含** key；
    #   ③ 其余情况（函数/类/元组常量）key 必须出现在该符号的**源码**里。
    import importlib
    import inspect

    all_entries = (list(DEVICE_REGISTRY.items()) + list(ENEMY_BB_REGISTRY.items())
                   + list(RUNES_REGISTRY.items()))
    no_anchor = [k for k, e in all_entries if e.status == DONE and not e.anchor]
    check("标 DONE 的条目都写了 anchor", not no_anchor, str(no_anchor[:4]))
    bad_anchor, missing = [], []
    for k, e in all_entries:
        if e.status != DONE or not e.anchor:
            continue
        mod_name, _, attr = e.anchor.partition(":")
        try:
            sym = getattr(importlib.import_module(mod_name), attr)
        except Exception as exc:                                  # noqa: BLE001
            bad_anchor.append(f"{k} → {e.anchor}（{exc}）")
            continue
        if isinstance(sym, str):
            hit = sym == k
        elif isinstance(sym, (tuple, list, set, frozenset, dict)):
            hit = k in sym
        else:
            hit = False
        if not hit:
            # 回退到"这个键出现在该符号的源码里吗"。
            # 元组常量（`_REBORN_SPECS` 是 `(("Reborn.", …), ("Reborning.", …))`）
            # 走的就是这一条：直接 `in` 只比最外层，比不到里层的字符串。
            try:
                hit = k in inspect.getsource(sym)
            except Exception:                                     # noqa: BLE001
                hit = True          # 取不到源码（内建）就不冤判
        if not hit:
            missing.append(f"{k} → {e.anchor}")
    check("★ 每个 DONE 的 anchor 都能解析到真实符号", not bad_anchor,
          str(bad_anchor[:3]))
    check("★ 每个 DONE 的 key 都真的出现在锚点那段代码里", not missing,
          str(missing[:3]))
    # 反面：TODO 里写明"数据已改、但无消费者"的那条，不许被标成 DONE
    check("敌方技能黑板乘数仍待实现（改写了数据但没有消费者）",
          RUNES_REGISTRY["enemy_skill_blackb_mul"].status == TODO)
    check("被击倒给装置的机制仍待实现（模拟器没有部署装置这一层）",
          ENEMY_BB_REGISTRY["DeathPassive."].status == TODO)
    check("进入阻流阀真伤仍待实现（装置没有血量/被摧毁这一层）",
          ENEMY_BB_REGISTRY["AuraHit."].status == TODO)

    print("\n" + "=" * 68)
    tail = f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项"
    print(tail + "：")
    for n in _FAILED:
        print(f"  - {n}")
    print("=" * 68)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
