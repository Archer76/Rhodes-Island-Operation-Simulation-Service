# -*- coding: utf-8 -*-
"""A/B：`frontend/enemy_view.py` 与真的 `_build_enemy` 造出来的敌人**逐字段比**。

## 它回答什么问题

新家的 `enemy_view` 是**生成**出来的（`tools/gen_enemy_view.py` 从 `_build_enemy`
的 AST 抽实参），理论上逐字对齐。但"理论上"不算数——这个工具把它变成可复算的证据：
对每一份计划的**每一行出怪**，同时造两边，比较**规格真正会读的那些字段**。

## 比哪些字段

与 `simgo/spec.py::_unit_spec` 实际读的那一组**一一对应**（不是"随便挑几个"）。
判据能看见什么，必须与结论要说的东西对齐——这是本项目反复吃亏的地方。

⚠ **不比 `affinity` / `break_state`**：它们取决于 `total_attack` / `boss_mode`，
而这两个在当前流水线里是关的（`aff` 恒为空 dict、`bk` 恒为 None），
`_unit_spec` 也**不读**它们。比了只会把"两个都是空"当成通过，是假信号。

## 跑法

    python tools\\check_enemy_view.py            # 扫 out/plan-*.json
    python tools\\check_enemy_view.py --limit 3  # 只跑前 3 份（快）

退出码 0 = 全部一致；1 = 有差异（会打印前若干条）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.frontend.enemy_view import enemy_view            # noqa: E402
from ak_tactic.plan import Plan, Roster                         # noqa: E402
from ak_tactic.verify import Verifier                           # noqa: E402

OUT = ROOT / "out"

#: `spec.py::_unit_spec` 实际读的字段（含两个判据用的）。
#:
#: 前一组是逐字抄规格里那些键；后三个是 `cannot_clear` / 路线要用的。
FIELDS = [
    "name", "enemy_id", "level", "max_hp", "atk", "defense", "res",
    "move_speed", "attack_interval", "attack_type", "attack_range",
    "apply_way", "is_flying", "unblockable", "taunt_level", "life_cost",
    "kill_cost", "passive_pollut", "passive_radius",
    "phit_cnt", "phit_max_stack", "phit_atk", "phit_def", "phit_res",
    "phit_move", "phit_weight_cnt", "phit_pollut", "phit_block_pollut",
    "pm2_atk", "pm2_def", "pm2_res", "pm2_move", "pm2_invincible",
    "pm2_clean_def", "pm2_clean_move", "pm2_mark_pollut",
    "reborn_left", "reborn_delay", "reborn_hp_ratio", "reborn_interval",
    "reborn_pollut", "reborn_def_add", "reborn_damage_magic",
    "skill_atk_scale_phys", "skill_atk_scale_magic", "skill_atk_pollut",
    "skill_atk_cross", "skill_atk_ground_only", "skill_atk_no_normal",
    "skill_atk_interval", "skill_atk_init",
    # ---- 判据/路线
    "route_length", "always_invincible", "legs",
]


class _Done(Exception):
    """比完就撤——不必真跑那一局。"""


def _find(name: str) -> Path:
    names = [name] if name.endswith(".json") else [name, f"{name}.json"]
    for n in names:
        for cand in (OUT / n, ROOT.parent / "ak-tactic-head" / "out" / n,
                     ROOT / n, ROOT / "data" / "skland" / n):
            if cand.exists():
                return cand
    raise SystemExit(f"找不到：{name}（试过 {names}）")


def compare_one(plan_path: Path, roster: Roster) -> tuple[int, list[str]]:
    """返回 (比过的敌人行数, 差异列表)。"""
    diffs: list[str] = []
    seen = 0

    class Probe(Verifier):
        def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                              schedule=None, **kw):
            #: ⚠ 收 `**kw`：基类这个钩子加过参数（`schedule`），写死签名会让
            #: 本工具在基类一变就 `TypeError`——那是**工具的红**，别读成代码的红。
            nonlocal seen
            for t, sp in sim._spawns:
                seen += 1
                want = sim._spawn(sp.enemy_id, sp.level, sp.route_index, float(t))
                stats = sim._enemy_stats(sp.enemy_id, sp.level)
                route = sim._route_points.get(sp.route_index) or []
                legs = sim._route_legs.get(sp.route_index) or []
                wait = 0.0 if legs else sim._route_wait.get(sp.route_index, 0.0)
                got = enemy_view(
                    stats, enemy_id=sp.enemy_id, level=sp.level,
                    route=route, legs=legs, t=float(t), wait=wait,
                    species_provider=sim.species_provider)
                for f in FIELDS:
                    a = getattr(want, f, "<缺>")
                    b = getattr(got, f, "<缺>")
                    if a != b:
                        diffs.append(
                            f"{plan_path.stem} t={t:.4f} {sp.enemy_id} "
                            f"字段 {f}: 原版={a!r} 新家={b!r}")
            raise _Done()

    plan = Plan.load(str(plan_path))
    v = Probe()
    try:
        v.run(plan, roster=roster)
    except _Done:
        pass
    return seen, diffs


def main() -> int:
    argv = sys.argv[1:]
    limit = None
    if "--limit" in argv:
        limit = int(argv[argv.index("--limit") + 1])
    plans = sorted(OUT.glob("plan-*.json"))
    if limit:
        plans = plans[:limit]
    if not plans:
        raise SystemExit("out/ 下没有 plan-*.json")
    roster = Roster.from_json(_find("roster_max_modelled"))
    total = 0
    bad = 0
    all_diffs: list[str] = []
    for p in plans:
        n, d = compare_one(p, roster)
        total += n
        print("  %-22s 出怪 %3d 行  差异 %d" % (p.name, n, len(d)))
        if d:
            bad += 1
            all_diffs.extend(d)
    print()
    print("合计 %d 份计划、%d 行出怪；有差异的计划 %d 份" % (len(plans), total, bad))
    if all_diffs:
        print()
        print("差异（前 20 条）：")
        for line in all_diffs[:20]:
            print("   " + line)
        return 1
    print("✅ 规格真正会读的那 %d 个字段，%d 行出怪**逐个一致**" % (len(FIELDS), total))
    return 0


if __name__ == "__main__":
    sys.exit(main())
