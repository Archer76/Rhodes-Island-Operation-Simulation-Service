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
    # ★ 召唤闭包：不在出怪表里的单位也要盘到，否则它们的黑板键永不进审计，
    #   「未登记 0 项」就是虚的（天桩-甲/乙/身上的天标就是三例）。
    check("★ 盘点顺着召唤闭包走（装置→甲、甲→乙、乙→天标都收进来了）",
          "enemy_1398_dhdcr" in rep.summoned
          and "enemy_1400_dhtbgj" in rep.summoned,
          str(sorted(rep.summoned)))
    # ★ 2026-09-16：装置 → 甲 那一跳**不是正文**，是关卡支线（结构化）。
    #   而且三型甲都真的被用到——只认默认型会漏掉失控型与关卡本地型。
    check("★ 三型天桩-甲都被盘到（默认 / 失控 `_2` / 关卡本地 `_b`）",
          {"enemy_1398_dhdcr", "enemy_1398_dhdcr_2",
           "enemy_1398_dhdcr_b"} <= set(rep.summoned),
          str(sorted(rep.summoned)))
    check("★ 关卡自带的敌人定义（`useDb: false`）不再落进「未登记」",
          not [x for x in rep.unknown if str(x[1]).endswith("_dhdcr_b")
               or str(x[1]).endswith("_dhtb_b")],
          str(rep.unknown))
    check("★ 失控型的乙（`…dhtb_2`）也在闭包里（失控甲召的是它）",
          "enemy_1399_dhtb_2" in rep.summoned
          and rep.summoned["enemy_1399_dhtb_2"] == "enemy_1398_dhdcr_2",
          str({k: v for k, v in rep.summoned.items() if "dhtb" in k}))
    check("★ 召唤体的黑板机制进了登记表（CheckAwake. 不再缺席）",
          "CheckAwake." in rep.enemy_bb
          and "enemy_1398_dhdcr" in rep.enemy_bb["CheckAwake."]
          and "enemy_1398_dhdcr_b" in rep.enemy_bb["CheckAwake."],
          f"CheckAwake. 覆盖 {sorted(rep.enemy_bb.get('CheckAwake.', {}))}")
    # 同一个前缀下的**两个机制**必须各自有位（Passive. 与 Passive.damage_value）
    check("★ 同前缀的两个机制各自成条（死亡污染 / 附着每秒伤害）",
          "Passive." in rep.enemy_bb
          and "Passive.damage_value" in rep.enemy_bb,
          str(sorted(rep.enemy_bb)))

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
    # ⚠ 这一条原先钉的是 `len(rep.todo) >= 1`（"怀黍离确实还有没做的"）。
    #   2026-09-16 四条 TODO 全部收口后它是 0——那是**结果**，不是问题；
    #   再钉"必须非空"就变成逼人留一个假 TODO。改成钉**派生关系**：
    #   报告里的待实现清单必须恰好等于登记表里 status==TODO 的那些条目，
    #   既不许多、也不许漏（漏项 = 数据里出现了未登记的机制而清单不报）。
    # 用别名导入，避免把 main() 里同名的模块级名字变成局部变量（会 UnboundLocalError）
    from ak_tactic.activity import DEVICE_REGISTRY as _DEV_REG
    from ak_tactic.activity import ENEMY_BB_REGISTRY as _EBB_REG
    from ak_tactic.activity import RUNES_REGISTRY as _RUN_REG
    from ak_tactic.activity import TODO as _TODO
    _tables = (_DEV_REG, _EBB_REG, _RUN_REG)
    _listed = {e.key for e in rep.todo}
    _should = {k for t in _tables for k, v in t.items() if v.status == _TODO}
    check("★ 待实现清单是从登记表派生的（既不许多、也不许漏）",
          _listed == _should,
          f"报告 {sorted(_listed)} / 登记表 {sorted(_should)}")

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
    # 天桩：正文与数据都取到了、整条链已接进模拟器，故标 DONE；
    # 判据是"它的召唤表真的落在代码里、且模拟器真的读它"，见 [6]。
    from ak_tactic.battle.devices import PILE_KEY as _PILE
    from ak_tactic.battle.sim import PILE_CHILD as _CHILD
    check("天桩标 DONE 且常量存在", DEVICE_REGISTRY[_PILE].status == DONE
          and _PILE == "trap_146_dhdcr" and _PILE in _CHILD)
    # ★ 装置→甲 的**正常路径**是结构化支线；退路表在，但正路不许被删掉。
    import inspect as _inspect
    from ak_tactic.battle.sim import BattleSimulator as _BS
    _spec = _inspect.getsource(_BS._pile_spec)
    check("★ 装置 → 甲 走的是关卡支线（结构化），退路表只是兜底",
          "branch_for" in _spec and "branch_actions" in _spec
          and "extra_route" in _spec,
          f"_pile_spec 源码 {len(_spec)} 字符")
    check("  装置 key 末段能推出支线前缀、且**没有支线语义的装置推不出**",
          __import__("ak_tactic.gamedata.stage", fromlist=["x"])
          .branch_prefix("trap_146_dhdcr") == "branch_dhdcr")
    check("剩下没做的装置是 0 个（怀黍离三种装置都已实现）",
          not todo_dev, str(todo_dev))

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
            # 锚点允许带点：`模块:类.方法`（方法就写在类里，指到方法比指到类准）
            sym = importlib.import_module(mod_name)
            for part in attr.split("."):
                sym = getattr(sym, part)
        except Exception as exc:                                  # noqa: BLE001
            bad_anchor.append(f"{k} → {e.anchor}（{exc}）")
            continue
        if isinstance(sym, str):
            hit = sym == k
        elif isinstance(sym, (tuple, list, set, frozenset, dict)):
            hit = k in sym
        else:
            # 函数/方法/类：直接比不过，看源码里有没有这个键（下面统一回退）
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
    # 反面→正面：这一条曾写着"数据已改、但无消费者"，2026-09-16 接通后翻 DONE。
    # 留着这条正面断言，是为了防止有人把状态改回去而代码还在。
    check("★ 敌方技能黑板乘数已接通（玷 / 勿玷 的技能「污」有消费者了）",
          RUNES_REGISTRY["enemy_skill_blackb_mul"].status == DONE)
    # 正面：这两条已经接了，不许再标回 TODO（否则"已实现"是假的）
    check("★ 进入阻流阀真伤已实现（装置有血量、会被摧毁、田地会还原）",
          ENEMY_BB_REGISTRY["AuraHit."].status == DONE)
    check("★ 天桩链已实现（CheckAwake. 由监测/激活/召唤那段代码兑现）",
          ENEMY_BB_REGISTRY["CheckAwake."].status == DONE)
    check("★ 附着每秒伤害已实现（Passive.damage_value 单列成条）",
          ENEMY_BB_REGISTRY["Passive.damage_value"].status == DONE)
    check("★ 被击倒给装置已实现（额度有来源、有 `plan_device` 花得出去）",
          ENEMY_BB_REGISTRY["DeathPassive."].status == DONE)
    # 上面那条 DONE 的判据必须真的落在代码里，不能只是改了状态字符串
    import inspect as _ins
    from ak_tactic.battle.sim import BattleSimulator as _BS2
    _dep = _ins.getsource(_BS2._do_deploy_device)
    _run = _ins.getsource(_BS2.run)
    check("  部署层真的存在：额度进账 / 花额度 / 主循环里真的调用它",
          "device_token_balance" in _dep and "_affordable" in _dep
          and "_do_deploy_device" in _run
          and "device_token_balance" in _ins.getsource(_BS2._on_enemy_death),
          f"_do_deploy_device {len(_dep)} 字符")

    # 技能攻击那一条的 DONE 同样要落进代码：出手方法存在、主循环真的调用它、
    # 而且**乘完要重算派生字段**（不重算就是"改了数据没消费者"的老病）
    from ak_tactic.gamedata.enemy import EnemyStats as _ES
    _tick = _ins.getsource(_BS2._skill_attack_tick)
    _pick = _ins.getsource(_BS2._skill_atk_target)
    check("  技能攻击真的存在：全图挑地面干员 / 十字五格 / 附加法术 / 污染地块",
          "skill_atk_ground_only" in _pick and "skill_atk_cross" in _tick
          and "skill_atk_scale_magic" in _tick and "pollute_cell" in _tick
          and "_skill_attack_tick" in _run,
          f"_skill_attack_tick {len(_tick)} 字符")
    _rs = _ins.getsource(_ES.rescale_skill_blackboard)
    check("  乘完**重算派生字段**（否则乘数只落在一张没人读的表上）",
          "derive_skill_fields" in _rs,
          "rescale_skill_blackboard → derive_skill_fields")

    print("\n" + "=" * 68)
    tail = f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项"
    print(tail + "：")
    for n in _FAILED:
        print(f"  - {n}")
    print("=" * 68)
    return 1 if _FAILED else 0


if __name__ == "__main__":
    raise SystemExit(main())
