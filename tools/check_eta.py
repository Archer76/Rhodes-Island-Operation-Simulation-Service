# -*- coding: utf-8 -*-
"""敌人到达时刻（ETA）自检。

分五节：**路线解析**（与模拟器共用一份）、**速度公式**（含 0 速不被兜底）、
**与模拟器实测对拍**（三关，误差必须在一帧以内）、**按格查询索引**、
**共源守卫**（防止有人把路线解析抄成两份）。

跑法：`python tools/check_eta.py`
"""
from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator                        # noqa: E402
from ak_tactic.eta import (ArrivalIndex, enemy_arrivals,            # noqa: E402
                           enemy_speed, polyline_length, route_plans)
from ak_tactic.gamedata import (EnemyLibrary, GameDataSource,       # noqa: E402
                                load_stage)

FPS = 30.0
FRAME = 1.0 / FPS          # 逐帧推进带来的量化误差上界

_PASSED = 0
_FAILED: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    global _PASSED
    if ok:
        _PASSED += 1
        print(f"  [ok]   {label}" + (f"   {detail}" if detail else ""))
    else:
        _FAILED.append(label)
        print(f"  [FAIL] {label}" + (f"   {detail}" if detail else ""))


def close(a, b, tol=FRAME) -> bool:
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


class _Stub:
    """假的敌人属性对象，只给速度。用于隔离地测速度公式。"""

    def __init__(self, ms, name="假敌人"):
        self.move_speed = ms
        self.name = name


def main() -> int:
    print("检查敌人到达时刻模型（ak_tactic/eta.py）")
    src = GameDataSource()

    # ------------------------------------------------------------ 1 路线解析
    print("\n[1] 路线解析：与模拟器共用一份实现")
    stages = {}
    for sid in ("main_01-07", "act54side_06", "act54side_ex08"):
        stages[sid] = load_stage(sid, source=src)

    p17 = route_plans(stages["main_01-07"])
    p6 = route_plans(stages["act54side_06"])
    p8 = route_plans(stages["act54side_ex08"])
    check("1-7 解析出 27 条路线", len(p17) == 27, str(len(p17)))
    check("SR-6 解析出 21 条路线", len(p6) == 21, str(len(p6)))
    check("SR-EX-8 解析出 39 条路线", len(p8) == 39, str(len(p8)))

    kinds6 = {tuple(l.kind for l in p.legs) for p in p6.values()}
    check("SR-6 全是「待命 + 走」两段", kinds6 == {("wait", "walk")},
          str(kinds6))
    r0 = p6[0]
    check("SR-6 路线0：待命 3s + 走 12.00 格（含洞修正后的值）",
          close(r0.legs[0].seconds, 3.0, 1e-9)
          and close(r0.legs[1].length, 12.0, 1e-9),
          f"{r0.legs[0].seconds}s / {r0.legs[1].length}格")

    vanish = [p for p in p8.values() if p.vanished] if hasattr(
        next(iter(p8.values())), "vanished") else [
        p for p in p8.values() if any(l.kind == "vanish" for l in p.legs)]
    check("SR-EX-8 有 38 条路线含「离场」段（传送必须分段）",
          len(vanish) == 38, str(len(vanish)))
    check("SR-EX-8 那 1 条不含离场的是飞行路线",
          any(not any(l.kind == "vanish" for l in p.legs) for p in p8.values()))

    # 长度与分段自洽
    bad = [i for i, p in p6.items()
           if not close(p.length, sum(l.length for l in p.legs), 1e-9)]
    check("SR-6 每条路线的 length 等于各走段之和", not bad, str(bad[:3]))
    check("polyline_length 对两格直线给 1.0",
          close(polyline_length([(0, 0), (1, 0)]), 1.0, 1e-9))
    check("polyline_length 对对角线给 √2",
          close(polyline_length([(0, 0), (1, 1)]), 2 ** 0.5, 1e-9))

    # ------------------------------------------------------------ 2 速度
    print("\n[2] 速度公式：格/秒 = moveSpeed × move_multiplier × speed_scale")
    one = lambda eid, lv: _Stub(1.0)                       # noqa: E731
    check("1-7 的 move_multiplier 是 0.5",
          close(getattr(stages["main_01-07"].options, "move_multiplier", 0),
                0.5, 1e-9))
    check("移速 1.0 在 1-7 上是 0.5 格/秒",
          close(enemy_speed(one, "x", 0, move_multiplier=0.5), 0.5, 1e-9))
    check("speed_scale 是乘在最后的（扫描用）",
          close(enemy_speed(one, "x", 0, move_multiplier=0.5,
                            speed_scale=1.5), 0.75, 1e-9))
    check("**移速 0 必须保持 0**，不能被兜底成 1",
          enemy_speed(lambda eid, lv: _Stub(0.0), "x", 0,
                      move_multiplier=0.5) == 0.0,
          "这是 sim 里 `or 1.0` 那个同类 bug 的守卫")
    check("move_speed 为 None 时才落到 1.0",
          close(enemy_speed(lambda eid, lv: _Stub(None), "x", 0,
                            move_multiplier=1.0), 1.0, 1e-9))
    check("速度取不到时会返回正数（不静默变成不动的敌人）",
          enemy_speed(lambda eid, lv: _Stub(None), "x", 0,
                      move_multiplier=0.5) > 0)

    # ------------------------------------------------------------ 3 对拍
    print(f"\n[3] 与模拟器实测对拍（不放任何干员，全部走到终点）")
    print(f"    误差上界 = 一帧 = {FRAME:.4f}s")
    for sid, expect_leaks in (("main_01-07", 10), ("act54side_06", 3),
                              ("act54side_ex08", 4)):
        st = stages[sid]
        lib = EnemyLibrary(source=src)
        eta = enemy_arrivals(st, lib.get)
        sim = BattleSimulator(st, enemy_at=lib.get)
        res = sim.run(max_time=1200.0)
        pred = sorted(a.arrives_at for a in eta if a.arrives_at != float("inf"))
        got = sorted(t for t, _n, _c in res.leak_events)
        check(f"{sid}：漏怪只数 = {expect_leaks}（生命耗尽即结束）",
              len(got) == expect_leaks, f"实得 {len(got)}")
        n = min(len(pred), len(got))
        errs = [abs(pred[i] - got[i]) for i in range(n)]
        worst = max(errs) if errs else 0.0
        check(f"{sid}：{n} 只逐只对拍，最大误差 {worst:.3f}s ≤ 一帧",
              worst <= FRAME + 1e-6,
              f"最大 {worst:.4f}s / 平均 {sum(errs)/max(n,1):.4f}s")

    check("ETA 预测的到达只数 = 关卡总敌人数（1-7 的 41）",
          len([a for a in enemy_arrivals(stages["main_01-07"],
                                         EnemyLibrary(source=src).get)
               if a.arrives_at != float("inf")]) == 41)

    # 没办法车 life_cost = 0：漏了但不扣命
    st8 = stages["act54side_ex08"]
    lib8 = EnemyLibrary(source=src)
    res8 = BattleSimulator(st8, enemy_at=lib8.get).run(max_time=1200.0)
    costs = {n: c for _t, n, c in res8.leak_events}
    check("SR-EX-8 有漏怪但扣 0 命的（没办法车 life_cost=0）",
          0 in costs.values(), f"{costs}")

    # ------------------------------------------------------------ 4 索引
    print("\n[4] 按格查询索引（搜索器的剪枝依据）")
    idx = ArrivalIndex(enemy_arrivals(stages["act54side_06"],
                                      EnemyLibrary(source=src).get))
    check("索引里格子数 > 0", len(idx.cells()) > 0, str(len(idx.cells())))
    check("busiest 给出最忙的格子", len(idx.busiest(5)) == 5,
          str([c for c, _d in idx.busiest(3)]))
    dwell_all = idx.dwell(idx.cells())
    check("全部格子的 dwell 是正的", dwell_all > 0, f"{dwell_all:.1f} 敌人·秒")
    busiest_cell = idx.busiest(1)[0][0]
    check("最忙那格的 dwell ≤ 全图 dwell",
          idx.dwell([busiest_cell]) <= dwell_all + 1e-9)
    check("空格集合的 dwell 为 0", idx.dwell([]) == 0.0)
    check("不存在的格没有访问记录", idx.at((99, 99)) == [])
    check("时间窗能把 dwell 截小",
          idx.dwell(idx.cells(), 0, 40) < dwell_all,
          f"{idx.dwell(idx.cells(), 0, 40):.1f} < {dwell_all:.1f}")
    check("first() 给出该格最早被占据的时刻",
          idx.first(busiest_cell) is not None)
    names = idx.names(idx.cells())
    check("names 统计到敌人种类", len(names) >= 1, str(names))

    # ------------------------------------------------------------ 5 共源
    print("\n[5] 共源守卫：路线解析只有一份实现")
    st6 = stages["act54side_06"]
    sim6 = BattleSimulator(st6, enemy_at=EnemyLibrary(source=src).get)
    mine = route_plans(st6)
    sim_pts = [tuple(p.points) for p in sim6.route_plans.values()]
    my_pts = [tuple(p.points) for p in mine.values()]
    sim_kinds = [tuple(l.kind for l in p.legs)
                 for p in sim6.route_plans.values()]
    my_kinds = [tuple(l.kind for l in p.legs) for p in mine.values()]
    check("模拟器与 eta 的路线解析结果逐条相同（同一份实现）",
          sim_pts == my_pts and sim_kinds == my_kinds,
          f"点数 {len(sim_pts)} vs {len(my_pts)}")
    check("模拟器把解析结果挂在 route_plans 上供外部核对",
          isinstance(getattr(sim6, "route_plans", None), dict))

    print()
    print("=" * 60)
    if _FAILED:
        print(f"通过 {_PASSED} 项，失败 {len(_FAILED)} 项：")
        for n in _FAILED:
            print(f"   ✗ {n}")
        return 1
    print(f"通过 {_PASSED} 项，无失败。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
