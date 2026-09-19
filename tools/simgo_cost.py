# -*- coding: utf-8 -*-
"""量规格生成（Python 侧）与模拟（Go 侧）各占多少——决定端到端上限在哪。

对拍是逐位一致了，但"一次解算几千场"的瓶颈可能从"跑战斗"挪到"每场都要序列化
一份规格 + 走一次子进程"。这一步把它量出来，好决定接进搜索时要不要**按关卡缓存
出怪段**（那部分是逐场不变的）。

    python tools/simgo_cost.py
"""
from __future__ import annotations

import pathlib
import statistics
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import BattleSimulator, Deployment            # noqa: E402
from ak_tactic.battle.unit import OperatorUnit                      # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.operator import OperatorCalculator                   # noqa: E402
from ak_tactic.simgo import (EngineBinaryUnpinned, Simgo, build_spec,
                             require_binary)                         # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs

STAGES = ["1-7", "2-1", "SR-6", "HS-EX-4"]


def _force_utf8_stdout() -> None:
    """输出重定向时消息也必须可读（口径⑤）：否则报错里的中文路径按 GBK 落盘、看的人读不出来。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")     # type: ignore[union-attr]
        except Exception:                            # noqa: BLE001
            pass


def make_unit(calc, char_id: str, **kw) -> OperatorUnit:
    st = calc.stats(char_id, **kw)
    t = st.total
    return OperatorUnit(
        name=st.name, char_id=char_id, elite=kw.get("elite", 2),
        max_hp=float(t["maxHp"]), atk=float(t["atk"]), defense=float(t["def"]),
        res=float(t.get("magicResistance", 0) or 0),
        attack_interval=float(t.get("baseAttackTime", 1.0) or 1.0),
        block_cnt=int(t.get("blockCnt", 0) or 0),
        deploy_cost=int(t.get("cost", 0) or 0),
        attack_speed=float(t.get("attackSpeed", 100) or 100),
    )


def main() -> int:
    _force_utf8_stdout()
    try:
        exe = require_binary()
    except EngineBinaryUnpinned as e:
        # ⚠ 这里原本是「跳过：没有 rios-sim 二进制 → return 0」。那是一条**rc=0 的假绿出口**：
        #    什么都没跑，而在读数上与「跑过了、一致」长得一模一样（PM 2026-09-19）。
        #    现在**没有"跳过"这条出口**：未钉住/钉错 ⇒ 报出那条能直接粘的命令、点名路径，rc=2。
        print(f"⛔ {e}", file=sys.stderr)
        return 2
    src = GameDataSource()
    lib = EnemyLibrary(source=src)
    calc = OperatorCalculator()
    print(f"{'关卡':<9}{'出怪':>5}{'干员':>5}{'原版跑':>9}{'建规格':>9}"
          f"{'Go 跑':>8}{'合计(Go)':>10}  加速")
    for code in STAGES:
        try:
            stage = load_stage(code, source=src)
        except Exception as exc:                                     # noqa: BLE001
            print(f"{code:<9}  取不到：{exc.__class__.__name__}")
            continue
        cells: list[tuple[int, int]] = []
        for group in ("melee_spots", "ranged_spots"):
            for cell in getattr(stage.map, group, []) or []:
                pos = (int(cell[0]), int(cell[1]))
                if pos not in cells:
                    cells.append(pos)
        rate = float(stage.options.cost_increase_time)
        cost = float(stage.options.initial_cost)
        now = 0.0
        squad = ["char_002_amiya", "char_102_texas", "char_140_whitew"]
        plan: list[Deployment] = []
        for i, char_id in enumerate(squad):
            op = make_unit(calc, char_id, elite=2, level=60)
            need = max(0.0, op.deploy_cost - cost)
            at = now + need * rate + (1.0 if need else 0.0)
            cost = cost + need - op.deploy_cost
            now = at
            plan.append(Deployment(at, op, cells[min(i * 3, len(cells) - 1)], "Right"))

        py = BattleSimulator(stage, enemy_at=lib.get)
        for d in plan:
            py.plan(d)
        t0 = time.perf_counter()
        py.run()
        py_ms = (time.perf_counter() - t0) * 1000

        spec_sim = BattleSimulator(stage, enemy_at=lib.get)
        for d in plan:
            spec_sim.plan(d)
        runs = []
        for _ in range(5):
            t0 = time.perf_counter()
            spec = build_spec(SpecInputs.from_sim(spec_sim), stage_label=code, allow_devices=True,
                              allow_skills=True)
            runs.append((time.perf_counter() - t0) * 1000)
        build_ms = statistics.median(runs)

        with Simgo(exe) as g:
            g.ping()
            gos: list[float] = []
            refused = ""
            for _ in range(5):
                t0 = time.perf_counter()
                try:
                    g.sim(spec)
                except RuntimeError as exc:
                    refused = f"  （最小版本拒跑：{exc}）"
                    break
                gos.append((time.perf_counter() - t0) * 1000)
            go_ms = statistics.median(gos) if gos else float("nan")
        head = (f"{code:<9}{len(spec['spawns']):>5}{len(spec['operators']):>5}"
                f"{py_ms:>8.0f}ms{build_ms:>8.1f}ms")
        if refused:
            print(head + f"{'—':>8}{'—':>10}" + refused)
            continue
        total = build_ms + go_ms
        print(head + f"{go_ms:>7.1f}ms{total:>9.1f}ms  {py_ms / total:>5.1f}×")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
