# `SpecInputs` 去模拟器化：逐字段迁移表

- 建立：2026-09-19（RIOS 终端 UI_2 / `session-4aa40539`）
- 结论一句话：**`SpecInputs` 的 23 项全部有"不依赖活模拟器"的来源** ⇒ `from_sim()` 可以断。
- 证据口径：每一条都给出**原版里的赋值行**（`ak_tactic/battle/sim.py`）或**已有的免 sim 实现**，
  不是推断出来的"应该可以"。

---

## 一、为什么这张表存在

`ak_tactic/frontend/inputs.py::SpecInputs.from_sim()` 是 round19 有意留下的**迁移期桥**——
名字里带 `sim` 就是让这笔欠账**可 grep**、不被忘掉。本表回答的是：

> 这 23 项，各自在**没有模拟器**的时候从哪里来？

答完之后，`from_sim` 就该消失，`build_spec` 也就彻底与 `battle/` 脱钩（目标 ①）。

---

## 二、四类来源（按"要不要现算"分）

### A 类：**三个 provider —— 本来就在 sim 之前存在**

关键事实：**它们不是模拟器算出来的，是构造模拟器时喂进去的。**

`ak_tactic/verify.py:369-377`：

```python
sim = BattleSimulator(
    stage, enemy_at=lib.get, range_provider=provider,
    species_provider=lib.species_of,
    skill_book=self.skill_book, verbose=self.verbose,
    effect_source=self.effect_source, **switches)
```

而 `provider` 来自上一行 `verify.py:366`：

```python
provider = self.range_provider(stage) if self.use_range_table else None
```

⇒ 三项的**真来源**是：

| 字段 | 真来源 | 性质 |
|---|---|---|
| `enemy_at` | `lib.get`（`self.library(stage)` 的敌人图鉴查询） | gamedata 查询函数 |
| `species_provider` | `lib.species_of`（enemydb 的 `enemy.category`） | gamedata 查询函数 |
| `range_provider` | `self.range_provider(stage)`（`Verifier` 自己的方法，`verify.py:201`） | 从 stage 现造 |

⇒ **这一类的迁移成本是零**：把同样的三个对象直接给 `SpecInputs` 即可，一行都不用新写。

### B 类：**八个关卡静态量 —— 已经有现成的免 sim 实现**

`ak_tactic/frontend/stage_env.py::stage_env(stage, ...) -> dict`（96 行，已经存在且已被使用）：

```
fps / speed_scale / ranged_enemies / enemy_windup / cost_init / cost_max / cost_time / life
```

⚠ 而且 **`verify.py:410` 已经在调用它**，把结果当 `env` 传给换引擎那一侧。
⇒ 规格层要这八项时，**应该读 `env`，不该回头问 `sim`**。

> 为什么这件事必须写清楚：`verify.py:404-405` 那段注释记着原来的坑 ——
> `build_spec` 过去是回头问模拟器要 `sim.speed_scale`，那是**派生后**的结果
> （已经乘过关卡的 `move_multiplier`、夹过零），而参数**只有 `run()` 手上有**。

### C 类：**三件机制状态 —— 都只用 `stage` 构造**

原版里的赋值行（`ak_tactic/battle/sim.py`）：

| 字段 | 行 | 原版写法 | 是否用运行期状态 |
|---|---|---|---|
| `devices`（原 `_devices`） | 525 | `self._devices = make_devices(stage)` | **否**，只用 stage |
| `farmland` | 538 | `self.farmland = FarmlandSystem(stage, _p)` | **否**，只用 stage |
| `total_attack` | 583 | `self.total_attack = make_total_attack(stage)` | **否**，只用 stage |

⇒ 三个工厂/构造器**都只收 `stage`**。规格层照着调即可。

### D 类：**两个"开局恒为空"的列表**

| 字段 | 行 | 原版写法 | 含义 |
|---|---|---|---|
| `snow_fields` | 573 | `self.snow_fields: list[SnowField] = []` | 积雪**部署时才建**，开局恒空 |
| `team_auras` | 578 | `self.team_auras: list[TeamAura] = []` | 光环**入场时才挂**，开局恒空 |

⚠ **这两个"空"正是"闸门盲区"的来源**（`build_spec` 取开局态 ⇒ 部署时才建的机制，
闸门永远看不见；见技能/记忆 `9b14e2c4`）。⇒ 迁移时**必须保持"开局为空"这个语义**，
不能顺手去问模拟器"现在有哪些雪"——那会在别的调用场景下拿到**跑了几帧之后**的值。

### E 类：排程五件套 —— **调用方已经递进来了**

`deployments` / `device_deployments` / `skill_uses` / `retreats` / `summon_deployments`

`verify.py` 在 `run()` 里同时写两份（`verify.py:393-396` 的注释说得很清楚）：

```python
sched = Schedule()      # 新家，不依赖 battle/
...
sched.plan(dep); sim.plan(dep)
sched.retreat(pos, r.time); sim.retreat(pos, r.time)
sched.use_skill(pos, s.time); sim.use_skill(pos, s.time)
```

并把 `sched` 作为 `schedule=sched` 递下去（`verify.py:487`）。
⇒ `from_sim` 里那五行**是冗余抄写**：显式排程在的时候，`spec.py` 用的是 `schedule` 而不是 `inp`。

### F 类：常量与其余

| 字段 | 值 | 来源 |
|---|---|---|
| `stage` | — | `self.stage(plan.stage)`，`verify.py:364` |
| `environment_difficulty` | `"NORMAL"` | `run()` 的参数 |
| `max_time` | `0.0` | 常量 |
| `snow_freeze` | `True` | 常量 |
| `heal_mode` | `"range"` | 常量 |

---

## 三、一个**死字段**（顺手查出来的）

`SpecInputs.from_sim` 里有这一行：

```python
goal_cells=_get("_goal_cells", None),
```

但 `_goal_cells` **在 `ak_tactic/battle/sim.py` 里 0 命中**（本表建立时实测）。
⇒ 这一项**永远是 `None`**，也就是说 `spec.py:405` 的

```python
(inp.goal_cells or _find_goals(inp))
```

**一直在走兜底 `_find_goals(inp)`**，那条 `or` 的左手边从未生效过。

⚠ 这不是 bug（行为正确），但它是一条**假的可选项**：看起来"可以外部指定防守点格"，
实际外部无论传什么都进不去。迁移时要么**真正接通**（从 stage 地图算），要么**删掉这个字段**，
不要原样搬过去——否则新读者会以为它有来源。

---

## 四、迁移的**形状**（不是本表要做的，但要说清）

不建议在 `SpecInputs` 内部写"没有 sim 就想办法"，而建议加一个**平级的构造函数**：

```python
SpecInputs.from_stage(stage, lib, range_provider, *, env, schedule, switches, ...)
```

理由与本项目一贯的纪律一致：**欠账要可数**。两个构造函数并存时，
`grep -c "SpecInputs.from_sim"` 就是"还剩几处没搬"的计数；
一旦藏在函数体里，这个数就没了。

⚠ 而且这个改动落在 `ak_tactic/verify.py` 与 `ak_tactic/simgo/verifier.py`，
**不在 `ak_tactic/simgo/spec.py`** —— 后者按项目经理通告 #4 一正在后端的写窗口里，
本表**一行都没有动它**。

---

## 五、本表的验证状态

| 项 | 状态 |
|---|---|
| A 类三个 provider | ✅ 已读 `verify.py:366/369-377` 原文 |
| B 类八个静态量 | ✅ 已读 `frontend/stage_env.py` 全文；`verify.py:410` 已在用 |
| C 类三件机制 | ✅ 已读 `sim.py:525/538/583` 赋值行（**未**验证三个工厂是否真的只收 stage，需在实现时逐个打开确认） |
| D 类两个空列表 | ✅ 已读 `sim.py:573/578` |
| E 类排程五件套 | ✅ 已读 `verify.py:393-397/465-479/487` |
| F 类常量 | ✅ 已读 `frontend/inputs.py:112-138` |
| 死字段 `_goal_cells` | ✅ 已实测 `sim.py` 0 命中；**未**验证是否有别处给 sim 补设该属性 |
| **端到端"不靠 sim 造出同一份规格"** | ❌ **未做**。本表只是来源盘点，**不是**"已经能断"的证明 |

⚠ **最后一行是本表的边界**：盘点完来源 ≠ 迁移完成。真正的判据是
"用 `from_stage` 造出的规格与用 `from_sim` 造出的**逐字节相同**"，
那要用 17 份金标准做证据（`out/golden_go.json` 的 `spec_sha`）。
