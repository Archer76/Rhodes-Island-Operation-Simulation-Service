# -*- coding: utf-8 -*-
"""**前端层**：从 gamedata + 计划算出"这一场战斗长什么样"，交给 Go 去跑。

## 它要解决什么

`ak_tactic/battle/`（10548 行）是 Python 的原版模拟器。博士已裁定弃用它，
默认引擎切到了 Go。但 `build_spec` 现在仍读一个**活的 `BattleSimulator`**
（`stage` / `deployments` / `_spawn` / `_range_of` / `_path_from` … 20+ 项），
所以 `battle/` 删不掉——它是 Go 的**排程器 + 规格源**。

本包就是那部分**要留下来的东西**的新家。

## 边界

* **进这里**：`build_spec` 真正可达的那些计算。实测**只有 10 个函数、268 行**
  （工具 `tools/spec_deps.py`，逐条见 `docs/spec-extraction-surface.md`）——
  整台战斗引擎（`_enemies_attack` / 伤害 / 位移 / 索敌…）**不在路上**，因为跑帧归 Go。
* **不进这里**：任何**跑帧**相关的东西。这里算的是"开场长什么样"，不是"接下来发生什么"。
* **不依赖**：`ak_tactic/battle/`、`ak_tactic/simgo/`。
  ⚠ 放在 `ak_tactic/frontend/` 而不是 `ak_tactic/simgo/frontend/`，是因为后者会踩到
  `simgo/__init__` → `spec` → `battle.talents` 的循环导入。

## 迁移纪律

1. **原样搬（move），不许重写**。原版在迁移期是基线；而且有些分支是**沉默区**
   （非 NORMAL 难度经当前流水线不可达 —— `Verifier` 不传 `environment_difficulty`），
   重写错了没有任何判据会响。
2. **每搬一步都要过金标准**：`python tools\\golden_go.py --check`
   —— 它比 17 份计划的**判决四数 ＋ 整份规格的 SHA-256**。
3. 搬完之前，`battle/` 里的那份**保持不动**（除了必要的 import 改写，
   那不改行为）。
"""
