# 闸门条目 × Go 落地状态（静态盘点）

> 生成工具：`tools/gate_inventory.py`（**静态，不需要作业**）。
> 表格由该工具的 `--md` 直接产出；本文件是它的一次实测留存 + 人工核对结论。
> 盘点对象：`ak_tactic/simgo/spec.py::unsupported_reasons` 里的 `bad.append(...)`——
> 也就是"Go 拒跑整关"的那些条目。

## 一、为什么要有这张表

项目经理交办的优先级是「先落**能解开 8 关闸门的机制**」。
要回答"哪些机制能解闸门"，有两条路：

1. **逐关跑**：搜出作业 → `build_spec` → 读 `unsupported_reasons`。
   这条路是**权威**的，但卡在两处：作业要解算（慢）；`tools/sweep_hsl_parity.py`
   依赖的 `parity_plan` 模块**已从仓库消失**（见第四节）。
2. **静态盘点**（本表）：闸门条目本身是静态可穷举的，直接对 Go 树做静态匹配。
   快，但**粗**——只回答"这一条在 Go 侧有没有落脚点"，不回答"哪一关被它挡住"。

## 二、三态判据

| 态 | 含义 | 危险度 |
|---|---|---|
| 未送 | `wire.go` 与消费树里都找不到该名 | 低（本来就知道没做） |
| **已定义未读** | 字段/类型有，消费树里一处读都没有 | **最高**：闸门以为落地了 |
| 已读取 | 消费树里至少一处字段访问 | 低（但见第三节） |

"定义" = json tag / 结构体字段声明 / `type X` 声明 / `[]X`；
"读取" = 字段访问 `.Name`。

## 三、两类**已证实**的假信号（本工具第一版都踩过）

1. **注释被当成证据**。第一版不排除注释行，于是 `sim.go:1918` 那句
   「那三样（`volley_arrows` / `landing_scale` / `charge_arrows`）**还没进** Go 的
   `Profile`」与 `sim.go:2041` 那句「已知未接：`sp_per_highland`」**都被读成"已消费"**
   ——结论与事实**正好相反**。现已排除 `//` 与 `*` 开头的行。
2. **同名不同义**。`撤退` 那一行报"已读取"，命中的是 `sim.go:364 retreated bool`
   ——那是**干员撤退状态**，而闸门判的是**排程里的撤退时刻表**（`sch.retreats`）。
   两者不是一件事；这一行**不能**据此判定"撤退已落地"。

另有一条**判据适用性**问题：`积雪` 报"已定义未读"，因为 `SnowFieldSpec` 是**类型**，
它的消费点在 `rios-sim/mech/snow.go` 内部（访问的是结构体里的字段，不会写
`.SnowFieldSpec`）。**类型项不适用"字段访问"这一读法**，必须人工核。

## 四、已知未知（比表格本身更重要）

* **没有现役的逐关闸门台账**。`tools/sweep_hsl_parity.py` 依赖的 `parity_plan`
  全树无命中（`tools/` 下也没有 `def compare(`），该流水线目前跑不起来。
* `docs/tui-plan.md` 里「闸门从放行 8 关变成 14 关（HS-1/2/3/4/5/6/EX-1/EX-2/EX-3/
  EX-4/EX-7/S-1/TR-1/TR-2）」那段**已过期**：它引用的对拍工具
  `tools/check_mech_parity.py` 已在提交 `7b19f9e`（博士裁定后）删除。
  **不要把 8 / 14 这两个数字当现状引用。**
* 本表只覆盖 `unsupported_reasons`；`mech.port_reasons(sim)` 报的
  「敌人侧污染 / 天桩链 / 拆阀还原」不在其中，要另看 `rios-sim/mech/`。

## 五、表格（实测留存）

| 闸门条目 | 规格判据 | Go 侧状态 | 证据 |
|---|---|---|---|
| 召唤物部署 | `sch.summon_deployments` | 已读取 | huai_shu_li.go:266、272、327 等 8 处 |
| 装置部署 | `sch.device_deployments` | 未送 |  |
| 撤退 | `sch.retreats` | 已读取 | ⚠ 见第三节第 2 条，**同名不同义，需人工核** |
| 关卡装置 | `sim._devices` | 已读取 | huai_shu_li.go:197、244、245 等 6 处 |
| 全场总攻击装置 | `sim.total_attack` | 未送 | 无代码命中（仅注释提过） |
| 积雪 | `sim.snow_fields` | 已定义未读 | ⚠ 见第三节末条，是**类型**项；`mech/snow.go` 内有消费 |
| 田地 | `sim.farmland` | 已读取 | huai_shu_li.go:59 |
| 技能（未放行时整条拒跑） | `op.skill` | 已读取 | huai_shu_li.go:1364 等 51 处 |
| 技能效果覆盖 | `op.effects_override` | 未送 |  |
| 技能治疗倍率 heal_scale | `op.heals + eff.heal_scale` | 未送 |  |
| 高台触发回技力 sp_per_highland | `skill.blackboard` | 未送 | 无代码命中（仅注释提过） |
| 锤击 | `op.hammer` | 未送 |  |
| 天赋回技力（出手） | `op.sp_per_attack_talent` | 未送 |  |
| 天赋回技力（击杀） | `op.sp_per_kill_talent` | 未送 |  |
| 物理闪避 | `op.dodge_phys` | 已读取 | skill.go:333 |
| 法术闪避 | `op.dodge_arts` | 已读取 | skill.go:331 |
| 攻击力光环 | `op.aura_atk_pct` | 已读取 | sim.go:2288、2289 |
| 防御光环 | `op.aura_def_pct` | 已读取 | sim.go:2288、2289 |
| 免死 | `op.blessing_save` | 已读取 | sim.go:3021、3027 |
| 弱点伤害 | `op.weakness_damage` | 未送 |  |
| 天赋攻速（空闲时） | `op.aspd_when_free` | 未送 |  |
| 天赋攻速（高台） | `op.aspd_high_ground` | 未送 |  |
| 天赋回技力 find_sp_on_action | 天赋表 | 未送 |  |
| 翔虫机动 find_glider_mobility | 天赋表 | 未送 |  |
| 强击瓶专家·多轮 volley_arrows | `eff.volley_arrows` | 未送 | 无代码命中（仅注释提过） |
| 强击瓶专家·多轮 landing_scale | `eff.landing_scale` | 未送 | 同上 |
| 强击瓶专家·多轮 charge_arrows | `eff.charge_arrows` | 未送 | 同上 |

**合计：已读取 10 / 已定义未读 1 / 未送 16。**

## 六、下一步（把"粗"变"准"）

1. 修或废 `tools/sweep_hsl_parity.py`（要一个不依赖已消失模块的对拍入口），
   才能拿到**逐关**闸门原因 —— 这件事要项目经理指派归属。
2. 本表里"未送"的 16 条就是 Go 侧的**机制缺口清单**；
   哪几条能解开最多关卡，仍要等第 1 条落地后才能逐关问出来。
3. 类型项（积雪/田地/装置族）与同名不同义项（撤退）必须**人工核**，
   不许直接拿本表的"已读取"当验收依据。
