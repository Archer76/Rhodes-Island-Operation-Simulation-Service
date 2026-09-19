# `build_spec` 的摘除面：要搬的不到 `battle/` 的 3%

目标是把 `ak_tactic/battle/`（**10548 行**）整体摘除。这份文档是**测量结果**，
不是估计——工具是 `tools/spec_deps.py`（可重算）。

## 一、结论先说

| | 量 |
|---|---|
| `battle/` 全部 | **10548 行** |
| 从 `build_spec` 出发**可达的函数** | **10 个，合计 268 行** |
| 它们**引用到的类** | **3 个**（且只用到属性，不用战斗方法） |
| `build_spec` 读 `sim` 的**属性** | **17 项**（没有函数体 → 改成显式入参即可） |
| 一份敌人规格实际需要的东西 | **~40 个标量字段** |

⇒ **整台战斗引擎（`_enemies_attack` / 伤害 / 位移 / 索敌……）根本不在 Go 这条路上**
——因为打仗那部分已经归 Go 了。要搬的不到 3%，其余 97% 随 `battle/` 一起消失。

## 二、可达的 10 个函数（全在 `sim.py`，除了最后一条）

| 函数 | 行数 | 它是什么 |
|---|---|---|
| `_build_enemy` | 132 | 按 key+level 造一个敌人（含天桩链那几跳） |
| `_note_mode_skill` | 26 | 形态技能记账 |
| `_range_of` | 21 | 干员的攻击范围格集 |
| `_cannot_clear` | 18 | 静态「清不掉」判据 |
| `_enemy_stats` | 18 | 敌人面板（关卡乘区、难度档） |
| `_path_from` | 15 | 某一格的寻路 |
| `_summon_level` | 14 | 召唤物档位 |
| `_pile_mark_key` | 13 | 「这只算不算乙」的唯一查表处 |
| `_spawn` | 6 | 出怪表的入口（转调 `_build_enemy`） |
| `unit.py::OperatorUnit.current_range_id` | 5 | 当前范围代号 |

## 三、引用的 3 个类

`EnemyUnit`（`unit.py`，618 行）、`OperatorUnit`（`unit.py`，844 行）、
`BreakState`（`p3r.py`，47 行）。

⚠ **但只用到它们的属性，不用它们的战斗方法**。`EnemyUnit` 里最重的几个方法
（`advance` 49 行、`_advance_legs` 52 行、`apply_slow` 24 行……）全是**跑帧**用的，
而跑帧归 Go。真正需要的只是**造面板**那一段（`_enemy_stats` 已在上表里）。

## 四、17 项属性读 → 显式入参

```
stage          deployments     retreats        skill_uses
device_deployments            summon_deployments
_devices       _spawns         snow_fields
life  cost  max_cost  cost_time  fps
enemy_windup   ranged_enemies  speed_scale
```

分两类：

* **排程产物**：`deployments` / `retreats` / `skill_uses` / `device_deployments` /
  `summon_deployments` / `snow_fields` / `_devices` —— 由 `verify.py` 排程时产生，
  可以**直接当数据传**，不必再经过一个模拟器对象。
* **关卡静态**：`stage` / `life` / `cost` / `max_cost` / `cost_time` / `fps` /
  `enemy_windup` / `ranged_enemies` / `speed_scale` / `_spawns` —— 全部来自
  gamedata 与关卡对象，**本来就不需要模拟器**。

## 五、一份敌人规格真正读的字段（~40 个标量）

`_unit_spec` 从敌人对象上只取标量，不取对象：

```
name enemy_id level max_hp atk defense res move_speed attack_interval
attack_type attack_range apply_way attack_times is_flying unblockable
taunt_level life_cost kill_cost
passive_pollut passive_radius
phit_cnt phit_max_stack phit_atk phit_def phit_res phit_move
phit_weight_cnt phit_pollut phit_block_pollut
skill_atk_*  reborn_*  pm2_*  …（按机制成族）
```

另外一个**算出来的**：`sim._cannot_clear(e)`。
加上 `sim._pile_mark_key(e)`（判「是不是乙」）与 `sim._summon_level(key)`。

⇒ 把 `_spawn` / `_build_enemy` 换成**纯函数** `enemy_stats(enemy_id, level, route_index, t)`
→ 返回上面那组标量，`EnemyUnit` 就不再需要了。

## 六、怎么用这份测量（给下一轮的执行顺序）

1. **先把不依赖引擎的 17 项改成入参**（尤其「关卡静态」那 10 项）——它们与引擎无关，
   改完 `golden_go.py --check` 必须逐项一致（含规格哈希）。风险最低、先摘掉一半。
2. **再搬那 10 个函数**：搬进 `ak_tactic/simgo/frontend.py`（不 import `battle/`），
   逐个搬、逐个跑金标准。⚠ 搬的是**逻辑**，不是文件——原版在迁移期必须保持不变，
   它是基线。
3. **最后处置 `check_battle.py`**（5957 行）：它测的是**机制**（田地/雪/护盾/相性），
   那些机制 Go 都实现了 ⇒ 改成考 Go，而不是跟着 `battle/` 一起删。
4. 15 个引用已删对拍工具的探针，在第 2 步做完后统一处置。

## 七、第一批要摘的 8 项：推导已经查清（下一轮照抄即可）

`spec.py:1062-1078` 那 8 项读的全是 `sim` 的**派生属性**，而派生源头在
`sim.py:418-489`，**与战斗无关**：

| 规格字段 | 源头 | 依赖 |
|---|---|---|
| `fps` | 构造参数（`sim.py:418`） | 调用方给的 |
| `speed_scale` | 构造参数 × `stage.options.move_multiplier`（419） | `stage` |
| `ranged_enemies` | 构造参数（428） | 调用方给的 |
| `enemy_windup` | `max(0, 构造参数)`（440） | 调用方给的 |
| `cost_init` | `stage.options.initial_cost`（474） | `stage` |
| `cost_max` | `stage.options.max_cost`（475） | `stage` |
| `cost_time` | `stage.options.cost_increase_time` **÷** `cost_recovery_scale(stage, environment_difficulty)`（476/479-481） | `stage` + `stage_mul` |
| `life` | `global_lifepoint(stage, environment_difficulty)` 优先，否则 `stage.options.max_life_point`（483/487-489） | `stage` + `stage_mul` |

⚠ 两处**容易漏的派生**（它们正是"四星档"那一档的来历，不接就会凭空多两条命 /
费用回错速度）：

* `cost_time` 要被 `cbuff_cost_recovery.scale` **除**（四星档常见 2）；
* `life` 要被关卡级的 `global_lifepoint` **改写**（八关 EX 的四星档都改成 1，
  而关卡文件自己的 `maxLifePoint` 是 3、普通与四星**两份都是 3**）。

两者都住在 `battle/stage_mul.py`（209 行，**纯函数**：`(stage, environment_difficulty) → 值`），
**没有任何引擎状态** ⇒ 可以整模块搬走，不必重写。

⚠ **但它不是自足的**（实测）：`stage_mul.py:42` 有一句
`from .environment import bb_number, find_rune, mask_applies`，
而 `environment.py` 是 626 行、同时装着怀黍离的田地/病害逻辑。
所以"搬 `stage_mul`"会**拖上 `environment` 的三个小助手**。

下一轮要先判这三件事，再动手：

1. 那三个助手是不是**纯函数**（若纯——把它们与 `stage_mul` 一起搬进新家，
   或者搬进一个更底层的 `blackboard.py`）；
2. 若它们与田地状态纠缠，就在新家里**只重实现这三个**（很小），
   而不是把 `environment` 整块拖过来；
3. ⚠ 无论走哪条，都要先确认**金标准能不能覆盖到这条路径**——
   `global_lifepoint` / `cost_recovery_scale` 只对**四星档（环境难度）**起作用，
   若 17 份计划里没有一份是非普通档，那么"搬错了"在哈希上**看不出来**。
   这一条必须在动手**之前**查（这正是本项目"覆盖不到机制的判据只会沉默"的老坑）。

### 已查：结论是「可达路径覆盖到了，不可达的那半必须原样搬」

* 17 份计划的 keys 只有 `stage` / `title` / `deploys`——**没有任何难度档字段**；
* 难度来自 `BattleSimulator(..., environment_difficulty="NORMAL")`（`sim.py:381`，**构造参数**）；
* 而 `Verifier` 建模拟器时（`verify.py:343`）**不传它** ⇒ 经由本流水线**恒为 `NORMAL`**。

⇒ 两件事同时成立：

1. **金标准对可达路径是够用的**：`stage_mul` 那两条函数在 `NORMAL` 下的返回值也被
   哈希进去了（`life` / `cost_time` 是规格字段），所以搬错会翻红 ✓；
2. **非 `NORMAL` 那条分支在当前流水线里不可达** ⇒ 它是**沉默区**。
   所以搬迁的口径只能是**原样搬（move）**，不是"照 `NORMAL` 的行为重写"
   ——重写会把这半条分支悄悄改掉，而且没有任何判据会响。

⇒ **第一批的搬法**：`stage_mul.py` 整体搬到新家；`build_spec` 的这 8 项改成
从 `stage` + 构造参数 + `stage_mul` 直接算。改完 `golden_go.py --check` 必须逐项一致
（含规格哈希）——这 8 项一旦算错，四星档与 EX 关会立刻对不上，哈希会当场翻红。

## 八、工具口径的边界（别把它当运行期真值）

`tools/spec_deps.py` 做的是**静态名字可达性**：`self._foo()` / `sim._foo()` / `foo()`
解析到 `battle/` 包里的同名定义就算一条边。它回答"这个名字有没有被提到"，
**不回答"运行期真的走到没有"**。所以口径是**上界**——宁可多算，不可少算。
真值仍以 `golden_go.py` 的逐项比对为准。
