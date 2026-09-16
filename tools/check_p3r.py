"""P3R（伤害相性 / 击破值 / 倒地 / 全场总攻击）的回归检查。

单独成文件是因为 `check_battle.py` 已经很长；这里的每一项都对应一条能从
游戏数据或机制原文核对的断言，改动 P3R 相关代码后必须全绿。

    python tools/check_p3r.py
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle.p3r import (                                        # noqa: E402
    AFFINITY_CN, P3R_IMMUNE, P3R_NORMAL, P3R_REFLECT, P3R_WEAK,
    BreakState, TotalAttackDevice, affinity_multiplier, damage_slot,
)
from ak_tactic.gamedata import (                                          # noqa: E402
    EnemyLibrary, GameDataSource, load_stage,
)
from ak_tactic.gamedata.enemy import affinity_of                          # noqa: E402

PASS = FAIL = 0


def check(label: str, got, want) -> None:
    global PASS, FAIL
    ok = got == want
    if ok:
        PASS += 1
    else:
        FAIL += 1
    mark = "ok  " if ok else "FAIL"
    print(f"  [{mark}] {label}")
    if not ok:
        print(f"         期望 {want!r}")
        print(f"         实得 {got!r}")


def main() -> int:
    src = GameDataSource()
    lib = EnemyLibrary(source=src)

    # ---------------------------------------------------------- [1] 相性表格
    print("[1] 8 种敌人的伤害相性（物 / 法 / 元）")
    WANT = {
        "enemy_10184_pppsbr_2": (0, 0, 0),    # 刺溜冰淇淋：三者皆弱
        "enemy_10185_pppshd_2": (1, 0, 0),    # 沉默收音机：法术弱
        "enemy_10186_ppparc_2": (0, 1, 1),    # 蹒跚羽兽：物理弱
        "enemy_10188_pppdp_2": (1, 1, 0),     # 咆哮铳：**只有元素弱**
        "enemy_10189_pppmag_2": (0, 2, 0),    # 吓人路灯：物理弱 + 法术免疫
        "enemy_10191_pppgst": (1, 0, 1),      # 没办法车：法术弱
        "enemy_10192_ppprpr": (1, 1, 1),      # 挥铳圣像：**无弱点**
        "enemy_1589_pppdth": (1, 1, 1),       # BOSS：TotalAttack 是中性，真档位在 Mode
    }
    for eid, want in WANT.items():
        lv = 1 if eid == "enemy_1589_pppdth" else 0
        st = lib.get(eid, lv)
        got = (st.p3r["physical"], st.p3r["magical"], st.p3r["element"])
        check(f"{st.display_name} {eid}", got, want)

    # ------------------------------------------------- [2] 击破阈值与倒地时长
    print("[2] 击破阈值 / 倒地时长")
    for eid, lv, wmax, fall in (
        ("enemy_10184_pppsbr_2", 0, 2000, 15),
        ("enemy_10188_pppdp_2", 0, 4000, 10),
        ("enemy_10189_pppmag_2", 0, 4000, 10),
        ("enemy_1589_pppdth", 1, 6000, 5),
    ):
        st = lib.get(eid, lv)
        check(f"{st.display_name} weak_max/fall", (st.weak_max, st.fall_duration),
              (wmax, fall))

    # --------------------------------------------- [3] 免疫位跨档合并（真 bug）
    print("[3] 免疫位跨档合并——BOSS 用的是 level 1，必须继承 level 0 的免疫")
    lv0 = lib.get("enemy_1589_pppdth", 0)
    lv1 = lib.get("enemy_1589_pppdth", 1)
    check("BOSS 两档免疫位数量一致", len(lv1.immunities), len(lv0.immunities))
    check("BOSS lv1 免疫位非空", sum(1 for v in lv1.immunities.values() if v), 9)
    check("BOSS lv1 冻结免疫", lv1.immunities.get("frozenImmune"), True)
    check("BOSS lv1 沉默免疫", lv1.immunities.get("silenceImmune"), True)

    # ------------------------------------------------------ [4] BOSS 的形态档
    print("[4] BOSS 的形态相性（Mode_A / Mode_B）")
    check("BOSS Mode_A", lv1.modes.get("Mode_A"),
          {"physical": P3R_WEAK, "magical": P3R_IMMUNE, "element": P3R_NORMAL})
    check("BOSS Mode_B", lv1.modes.get("Mode_B"),
          {"physical": P3R_IMMUNE, "magical": P3R_WEAK, "element": P3R_NORMAL})
    check("BOSS 的 TotalAttack 是中性（故必须读 Mode）",
          (lv1.p3r["physical"], lv1.p3r["magical"], lv1.p3r["element"]), (1, 1, 1))

    # -------------------------------------------------------- [5] 谁能倒地
    print("[5] 能不能倒地——挥铳圣像永不倒，会卡死总攻击")
    check("挥铳圣像 can_fall", lib.get("enemy_10192_ppprpr", 0).can_fall, False)
    check("刺溜冰淇淋 can_fall", lib.get("enemy_10184_pppsbr_2", 0).can_fall, True)
    check("咆哮铳 can_fall（只有元素弱）", lib.get("enemy_10188_pppdp_2", 0).can_fall, True)

    # ------------------------------------------------------ [6] 相性倍率语义
    print("[6] 相性倍率——免疫是**归零**，不是减免")
    check("弱点倍率", affinity_multiplier(P3R_WEAK), 1.0)
    check("正常倍率", affinity_multiplier(P3R_NORMAL), 1.0)
    check("免疫倍率（归零）", affinity_multiplier(P3R_IMMUNE), 0.0)
    check("反射倍率（归零）", affinity_multiplier(P3R_REFLECT), 0.0)
    check("缺数据按正常处理", affinity_multiplier(None), 1.0)
    check("真实伤害不落相性槽", damage_slot("TRUE"), None)
    check("法术伤害落 magical", damage_slot("MAGICAL"), "magical")
    check("物理伤害落 physical", damage_slot("PHYSICAL"), "physical")

    # ------------------------------------------------------ [7] 击破值累积
    print("[7] 击破值累积 → 倒地")
    st = BreakState(weak_max=2000, fall_duration=15)
    check("非弱点不累积", st.add(5000, P3R_NORMAL, 0.0), False)
    check("非弱点后计量仍为 0", st.meter, 0.0)
    check("弱点累积但未满", st.add(1500, P3R_WEAK, 0.0), False)
    check("计量 = 1500", st.meter, 1500.0)
    check("满阈值触发倒地", st.add(500, P3R_WEAK, 0.0), True)
    check("倒地后计量清空", st.meter, 0.0)
    check("倒地中", st.is_down(10.0), True)
    check("倒地已满 15 秒后起身", st.is_down(15.1), False)
    check("倒地期间不再累积", st.add(9999, P3R_WEAK, 1.0), False)
    check("倒地次数累计 1", st.falls, 1)
    check("没有阈值就不算击破", BreakState(weak_max=0).enabled, False)

    # ------------------------------------------------------ [8] 总攻击装置
    print("[8] 全场总攻击装置")
    dev = TotalAttackDevice()
    check("伤害公式 = 15000 + 全队攻击", dev.trigger_value(5000.0), 20000.0)
    check("空场不触发（空集不算\"全部倒地\"）",
          dev.tick(0.0, down_states=[], ally_atk_sum=0.0), (False, False))
    check("空场记一次卡住", dev.blocked_checks >= 1, True)
    # 有敌人在场且全部倒地 → 排两拍
    dev2 = TotalAttackDevice()
    b, h = dev2.tick(0.0, down_states=[(True, "a"), (True, "b")], ally_atk_sum=1000.0)
    check("第一拍不发伤害", (b, h), (False, False))
    check("已排定两拍", dev2.armed, True)
    check("增益排在 0.1s", dev2.buff_at, 0.1)
    check("伤害排在 0.8s", dev2.hit_at, 0.8)
    b, h = dev2.tick(0.1, down_states=[], ally_atk_sum=1000.0)
    check("0.1s 发出增益", b, True)
    check("增益 = 15000 + 1000", dev2.bonus_atk, 16000.0)
    check("触发计数 1", dev2.triggers, 1)
    b, h = dev2.tick(0.8, down_states=[], ally_atk_sum=1000.0)
    check("0.8s 后打出伤害", h, True)
    check("冷却到 8.8s（从打出伤害那刻起算 8 秒）", dev2.cooldown_until, 8.8)
    check("结算完不再处于待发", dev2.armed, False)
    # 冷却是从**打出伤害**那刻起算 8 秒，不是从检测那刻
    dev3 = TotalAttackDevice()
    dev3.tick(0.0, down_states=[(True, "a")], ally_atk_sum=0.0)
    dev3.tick(0.1, down_states=[], ally_atk_sum=0.0)
    dev3.tick(0.8, down_states=[], ally_atk_sum=0.0)
    check("冷却期内不再触发", dev3.tick(5.0, down_states=[(True, "a")], ally_atk_sum=0.0),
          (False, False))
    check("冷却结束（8.8s）后可以再触发",
          dev3.tick(8.8, down_states=[(True, "a")], ally_atk_sum=0.0) != (False, False)
          or dev3.armed, True)
    check("有敌人没倒时不触发", TotalAttackDevice().tick(
        0.0, down_states=[(True, "a"), (False, "b")], ally_atk_sum=0.0), (False, False))

    # ------------------------------------------------------ [9] 关卡接线
    print("[9] 关卡接线——SR-EX-8 有装置，1-7 没有")
    ex8 = load_stage("act54side_ex08", source=src)
    sr6 = load_stage("act54side_06", source=src)
    m17 = load_stage("main_01-07", source=src)
    from ak_tactic.battle.sim import make_total_attack
    check("SR-EX-8 有总攻击装置", make_total_attack(ex8) is not None, True)
    check("SR-6 也有（同一个活动）", make_total_attack(sr6) is not None, True)
    check("1-7 没有", make_total_attack(m17) is None, True)
    check("装置黑板 base_atk", make_total_attack(ex8).base_atk, 15000.0)
    check("装置黑板 trigger_cd", make_total_attack(ex8).trigger_cd, 8.0)

    # ------------------------------------------------------ [10] affinity_of
    print("[10] affinity_of 的\"缺项即整体作废\"规则")
    check("三项齐全", affinity_of({"TotalAttack.PHYSICAL": 0, "TotalAttack.MAGICAL": 1,
                                   "TotalAttack.ELEMENT": 2}),
          {"physical": 0, "magical": 1, "element": 2})
    check("缺一项就返回空（不能默认成弱点）", affinity_of({"TotalAttack.PHYSICAL": 0}), {})
    check("前缀不匹配返回空", affinity_of({"TotalAttack.PHYSICAL": 0}, "Mode_C"), {})

    print(f"\n通过 {PASS} 项，失败 {FAIL} 项。")
    return 1 if FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
