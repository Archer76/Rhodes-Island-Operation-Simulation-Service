"""SR-EX-8 落位贪心搜索。

思路来自这一关的真实胜负手：**伤害主要不来自干员，而来自「全场总攻击」装置**。
装置每 8 秒最多触发一次，条件苛刻——场上**所有**带伤害相性的敌人必须**同时**
处于【倒地】。倒地只需要「对应弱点的实际伤害累计到 2000~6000」，所以

    覆盖面 > 单体输出

一个能同时碰到十个敌人的低倍率干员，比一个只能打一个的高倍率干员更有价值。
评分因此以**装置触发次数**为第一权重，总伤害与漏怪次之。

    python tools/search_srx8.py                 # 默认队伍，贪心 6 位
    python tools/search_srx8.py --team "圣聆初雪,逻各斯,提丰,能天使,机械师"
    python tools/search_srx8.py --top 5         # 每位只看前 5 个候选落点
"""

from __future__ import annotations

import argparse
import itertools
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from ak_tactic.battle import BattleSimulator, Deployment, RangeProvider   # noqa: E402
from ak_tactic.battle.talents import squad_cost_bonus                     # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                            # noqa: E402
from ak_tactic.gamedata import (                                          # noqa: E402
    EnemyLibrary, GameDataSource, RangeTable, load_stage,
)
from ak_tactic.operator import (                                          # noqa: E402
    OperatorCalculator, SkillBook, TalentBook,
)

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_srx8 import GROUND, HIGHLAND, build, load_box, make_provider     # noqa: E402

DIRS = ("Right", "Left", "Up", "Down")

#: 值得争夺的格子：13 个出生点 + 传送落点 + 中央咽喉 + 两个防守点。
#: 坐标为项目口径（= MAA 口径，原点左上、y 向下），13×9 的图。
KEY_CELLS = [
    (2, 2), (1, 3), (3, 3), (2, 6), (1, 5), (3, 5),        # 左侧出生簇
    (10, 2), (11, 3), (9, 3), (10, 6), (11, 5), (9, 5),    # 右侧出生簇
    (6, 2),                                                 # 中路出生点
    (6, 5), (6, 6), (6, 7), (5, 7), (4, 7), (7, 7), (8, 7),  # 传送落点→咽喉→防守点
]

DEFAULT_TEAM = ["圣聆初雪", "逻各斯", "提丰", "能天使", "机械师", "凯尔希·思衡托"]


def placements(provider, calc, cid, elite, spots, *, min_cover=2, top=None):
    """给一个干员列出「覆盖至少 min_cover 个关键格」的落点，按覆盖数降序。"""
    out = []
    for pos in spots:
        for d in DIRS:
            try:
                cells = provider(cid, elite, d, pos)
            except Exception:
                continue
            hit = sum(1 for k in KEY_CELLS if k in cells)
            if hit >= min_cover:
                out.append((hit, pos, d))
    out.sort(key=lambda x: -x[0])
    return out[:top] if top else out


def evaluate(stage, lib, provider, box, calc, book, talents, picks, *, verbose=False):
    """`picks` = [(entry, pos, dir), ...]，按下标顺序部署（费用不够就等）。"""
    sim = BattleSimulator(stage, enemy_at=lib.get, range_provider=provider,
                          skill_book=book, verbose=verbose)
    rate = float(stage.options.cost_increase_time)
    cost = float(stage.options.initial_cost)
    now = 0.0
    for entry, pos, d in picks:
        tal = talents.for_operator(entry["id"], elite=entry["elite"],
                                   level=entry["level"], potential=entry["potential"])
        cost += squad_cost_bonus(tal)
    for entry, pos, d in picks:
        tal = talents.for_operator(entry["id"], elite=entry["elite"],
                                   level=entry["level"], potential=entry["potential"])
        op = build(calc, entry)
        wait = max(0.0, (op.deploy_cost - cost) * rate)
        now += wait
        cost = cost + wait / rate - op.deploy_cost
        sim.plan(Deployment(now, op, pos, d, skill=2, skill_mastery=0,
                            auto_skill=True, talents=tal))
    r = sim.run(max_time=900)
    dev = sim.total_attack
    triggers = dev.triggers if dev else 0
    return r, triggers, dev


def score(r, triggers) -> tuple:
    """先看赢没赢，再看装置触发次数（这是这关的真正输出），最后看漏怪。"""
    return (1 if r.won else 0, triggers, -r.leaks, r.damage_dealt)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--team", default=",".join(DEFAULT_TEAM))
    ap.add_argument("--top", type=int, default=6, help="每位干员只看前 N 个落点")
    ap.add_argument("--min-cover", type=int, default=2)
    args = ap.parse_args()

    src = GameDataSource()
    stage = load_stage("act54side_ex08", source=src)
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    book = SkillBook()
    talents = TalentBook()
    box = load_box()
    provider = make_provider(calc, RangeTable())

    team = [n.strip() for n in args.team.split(",") if n.strip()]
    missing = [n for n in team if n not in box]
    if missing:
        print("导出里没有这些干员：", missing)
        return 2

    print(f"=== SR-EX-8 落位贪心搜索（{len(team)} 位，每位前 {args.top} 个落点）===")
    print("队伍：" + "、".join(f"{n}(精{box[n]['elite']}{box[n]['level']})" for n in team))

    # 每位干员的候选落点：地面干员只给地面位，高台只给高台位
    # profession 是英文枚举（CASTER/SNIPER/MEDIC/SUPPORT），不是中文职介名
    RANGED = ("SNIPER", "CASTER", "MEDIC", "SUPPORT")
    cands: dict[str, list] = {}
    for name in team:
        e = box[name]
        prof = calc.character(e["id"]).get("profession")
        spots = HIGHLAND if prof in RANGED else GROUND
        cs = placements(provider, calc, e["id"], e["elite"], spots,
                        min_cover=args.min_cover, top=args.top)
        cands[name] = cs
        print(f"  {name:<12} {len(cs):2d} 个候选  " +
              "、".join(f"{p}朝{d}({h})" for h, p, d in cs[:4]))
    print()

    picks: list = []
    used_tiles: set = set()
    t0 = time.time()
    for step, name in enumerate(team, 1):
        entry = box[name]
        best = None
        for hit, pos, d in cands[name]:
            if pos in used_tiles:
                continue
            trial = picks + [(entry, pos, d)]
            r, trig, dev = evaluate(stage, lib, provider, box, calc, book, talents, trial)
            s = score(r, trig)
            if best is None or s > best[0]:
                best = (s, pos, d, r, trig, dev)
        if best is None:
            print(f"第 {step} 位 {name}：没有可用落点，跳过")
            continue
        s, pos, d, r, trig, dev = best
        picks.append((entry, pos, d))
        used_tiles.add(pos)
        blocker = dev.to_dict()["last_blocker"] if dev else "—"
        print(f"第 {step} 位 {name:<12} → {pos} 朝{d}   "
              f"{'胜' if r.won else '败'} {r.elapsed:5.1f}s 杀{r.kills:2d} 漏{r.leaks} "
              f"生命{r.life} 伤害{r.damage_dealt:9,.0f} 装置×{trig}  卡在:{blocker}"
              f"   [{time.time()-t0:.0f}s]")
        if r.won:
            print("\n已取胜，停止加人。")
            break

    print("\n=== 最终方案 ===")
    for entry, pos, d in picks:
        print(f"  {entry['name']} @ {pos} 朝{d}")
    r, trig, dev = evaluate(stage, lib, provider, box, calc, book, talents, picks)
    print(f"结果：{'胜利' if r.won else '失败'}  {r.elapsed:.1f}s  击杀 {r.kills}  "
          f"漏怪 {r.leaks}  剩余生命 {r.life}  总伤害 {r.damage_dealt:,.0f}")
    if dev:
        print("装置：" + str(dev.to_dict()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
