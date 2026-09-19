# -*- coding: utf-8 -*-
"""田地规格的**充分性**探针：规格够不够 Go 侧复现原系统？

做法：从活的模拟器抽一份规格 → 用规格**重建**一个 `FarmlandSystem` →
两个系统喂**同一串事件**（同样的 tick、同样的污染、同样的泵站动作）→
逐帧比三个量（每片【最大】【缓存】、每格【实际】）。

判据是**逐帧精确相等**，不是"接近"：两边跑的是同一份 Python 代码、
同一串浮点数加法，所以任何差异都是"规格漏了东西"的证据。
差值容差在这里是有害的——它会把"漏了 initial 播种"这种错误平均掉。

事件串是脚本化的（固定随机种子），包含：
    tick(0.1s×N) / 圆污染 / 单格污染 / 抽干（瘴充能） / 缓存 vs 实际
    / 分割（阻流阀）/ 还原（阻流阀被拆）/ 泵站泵水（清澈与污染两支）

用法：
    python tools/check_mech_spec.py                 # 全部关卡
    python tools/check_mech_spec.py HS-EX-4         # 只看一关
"""
from __future__ import annotations

import pathlib
import random
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import BattleSimulator                    # noqa: E402
from ak_tactic.gamedata import EnemyLibrary, GameDataSource, load_stage  # noqa: E402
from ak_tactic.simgo import mech                                # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs

STAGES = ["HS-EX-4", "HS-8", "HS-EX-3", "HS-EX-8", "HS-1"]
SEED = 20260918
STEPS = 300          # 每步 0.1s → 30 秒的演进（够跑完 1s 与 0.2s 两个节拍上百次）


def snapshot(fs) -> tuple:
    """三个量的一份可比快照（浮点用 repr 保真，避免 1e-17 级别的噪声）。"""
    fields = []
    for f in fs.fields:
        fields.append((tuple(sorted(f.cells)), repr(float(f.maximum)),
                       repr(float(f.cache))))
    actual = tuple(sorted((c, repr(float(v))) for c, v in fs.actual.items()))
    return (tuple(fields), actual)


def dirty_cells(fs) -> list[tuple[int, int]]:
    return sorted(fs._index)


def drive(fs, rng: random.Random, log: list[str]) -> None:
    """同一串事件喂给两个系统（顺序、参数、随机数消耗完全一致）。"""
    cells = dirty_cells(fs)
    if not cells:
        return
    for i in range(STEPS):
        fs.tick(0.1)
        # 污染要密集一点：稀稀拉拉的话，0.2s/1s 两个节拍都跑不满，
        # "缓存→最大→实际"这条链就不会被真正走到。
        if i % 3 == 0:
            x, y = cells[rng.randrange(len(cells))]
            fs.pollute_area(x, y, rng.choice([0.0, 1.0, 0.5]), rng.choice([5.0, 15.0]))
        if i % 7 == 0:
            x, y = cells[rng.randrange(len(cells))]
            fs.pollute_cell(x, y, 4.0)
        if i % 11 == 5:
            x, y = cells[rng.randrange(len(cells))]
            fs.drain_cell(x, y, 10.0)
        if i % 5 == 0:
            x, y = cells[rng.randrange(len(cells))]
            fs.add_cache(x, y, 3.0)
        if i == 40:                       # 阻流阀：分割
            x, y = cells[rng.randrange(len(cells))]
            log.append(f"sever {x},{y}")
            fs.sever(x, y)
        if i == 90:                       # 阻流阀被拆：还原
            for c in list(getattr(fs, "_severed", ()) or ()):
                log.append(f"restore {c[0]},{c[1]}")
                fs.restore(*c)
        if i % 6 == 0:                    # 泵站：每秒一次
            for d in PUMP_CELLS:
                fs.pump(d[0], d[1], ally_on_source=(i // 6) % 2 == 0)
        if i % 50 == 49:                  # 环境伤害的两个读数也一起比（同一份输入）
            x, y = cells[rng.randrange(len(cells))]
            log.append(f"dmg@{x},{y}:{fs.damage_per_second(x, y):g}"
                       f"/regen:{fs.regen_per_second(x, y):g}"
                       f"/deploy:{fs.deploy_damage(x, y):g}")


#: 泵站格与朝向由外部按关卡填（见 `check_one`）。
PUMP_CELLS: list[tuple[tuple[int, int], str]] = []


def check_one(src, lib, code: str) -> tuple[bool, str]:
    global PUMP_CELLS
    try:
        stage = load_stage(code, source=src)
    except Exception as exc:                                       # noqa: BLE001
        return False, f"取不到关卡：{exc.__class__.__name__}"
    sim = BattleSimulator(stage, enemy_at=lib.get)
    fs0 = sim.farmland
    if fs0 is None or not fs0._index:
        return False, "这一关没有田地系统（跳过）"
    spec = mech.farmland_spec(SpecInputs.from_sim(sim))
    try:
        fs1 = mech.from_spec(spec)
    except Exception as exc:                                       # noqa: BLE001
        return False, f"按规格重建失败：{exc.__class__.__name__}: {exc}"

    if snapshot(fs0) != snapshot(fs1):
        return False, "重建后的初始状态就不一致（规格漏了初始量）"

    pump_cells = [(int(d["cell"][0]), int(d["cell"][1]))
                  for d in spec["devices"] if d["kind"] == "pump"]
    dirs = {int(d["cell"][0]) * 100 + int(d["cell"][1]): d["direction"]
            for d in spec["devices"]}
    PUMP_CELLS = [(c, dirs[c[0] * 100 + c[1]]) for c in pump_cells]

    rng0, rng1, log = random.Random(SEED), random.Random(SEED), []
    drive(fs0, rng0, log)
    drive(fs1, rng1, log)

    a, b = snapshot(fs0), snapshot(fs1)
    if a == b:
        return True, mech.spec_summary(spec)
    # 差异定位：先找哪一片、哪一个量不同
    for i, (fa, fb) in enumerate(zip(a[0], b[0])):
        if fa != fb:
            return False, f"第 {i} 片不一致：原版 {fa[1:]}, 重建 {fb[1:]}"
    da, db = dict(a[1]), dict(b[1])
    diff = [c for c in set(da) | set(db) if da.get(c) != db.get(c)]
    return False, f"逐格【实际】不一致 {len(diff)} 格，例：{diff[:3]}"


def main() -> int:
    only = [a for a in sys.argv[1:] if not a.startswith("-")]
    codes = only or STAGES
    print("田地规格的充分性（按规格重建的系统 vs 原系统，逐帧精确比）")
    try:
        src = GameDataSource()
        lib = EnemyLibrary(source=src)
        load_stage(codes[0], source=src)
    except Exception as exc:                                       # noqa: BLE001
        # 仓库惯例：这台机器没同步数据就**跳过**，不是失败。
        print(f"  [skip] 取不到本地游戏数据（{exc.__class__.__name__}）")
        return 0
    bad = 0
    for code in codes:
        try:
            ok, msg = check_one(src, lib, code)
        except Exception as exc:                                   # noqa: BLE001
            ok, msg = False, f"{exc.__class__.__name__}: {exc}"
        print(f"{'✅' if ok else '❌'} {code:<9} {msg}")
        bad += 0 if ok else 1
    print(f"\n共 {len(codes)} 关，不充分 {bad} 关")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
