# rios-sim 模拟核心与求解器优化方案文档

本文档针对 `ak-tactic` 项目的 Go 原生战斗模拟器（`rios-sim`）及其解算链路（`solver.go` / `buildspec.go` / `simquery.go`）整理系统性的性能瓶颈与逻辑严谨性优化方案。

---

## 一、 整体优化原则

1. **绝对保证战斗时序与判决确定性**：
   - 严禁擅自修改已裁定的帧内处理顺序（推进 -> 阻挡 -> 技能 -> 出手 -> 结算等）。
   - 严禁引入浮点近似导致 1 ulp 差异改变索敌、平局排序或落格边界。
2. **零侵权与只读口径不变**：
   - 数据加载保持只读模式（`mode=ro`），规格生成遵循契约自检。
3. **逐步落地与对照验证**：
   - 每一阶段优化必须通过 `go test . -run "TestEntelechia|TestStageHs8|TestSqliteResourcePack"` 以及怀黍离 36 关全量仿真验证（`TestRunSimHuaiShuLiRepresentativeStages`），确保 0 回归。

---

## 二、 优化领域与具体实施细则

### 阶段一：帧内高频热路径减负（Hot Path Zero-Allocation & Fast Path）

目标：消除 30fps 主循环中每次攻击、技能与环境判定带来的无门控堆分配与冗余计算。

#### 1.1 消除日志调用中的无门控参数装箱与字符串格式化
- **现状定位**：
  - `rios-sim/sim.go:2569-2571`：每次干员攻击命中敌人，直接执行 `trace(" 打 %s 攻=%.1f ...", ...)`，外层未包裹 `if traceOn`，每次命中无条件将 9 个参数装箱进堆接口切片。
  - `rios-sim/mech/huai_shu_li.go:1498-1514`：敌方技能「污」出手时，无论是否开启 trace，无条件循环分配 `victims` 切片并调用 `fmt.Sprintf` 和 `strings.Join`。
  - `rios-sim/sim.go:906-911`：`DEPLOYDMG` trace 缺少 `if traceOn` 守卫。
- **改法**：
  - 在所有涉及格式化或切片拼接的 `trace()` / `ctx.Trace()` 调用处添加外层 `if traceOn` 守卫，杜绝生产模式下的堆逃逸与字符串计算。

#### 1.2 敌数攻速的冗余 JSON 重序列化与哈希校验移出主循环
- **现状定位**：
  - `rios-sim/count_aspd.go:149`（`intervalForEnemies`）：干员攻击时若具有敌数攻速规则，每帧遍历敌人时调用 `intrinsicForSpawn` -> `intrinsicCountSource`。
  - `rios-sim/count_intrinsic.go:38-56`：每次检查都会触发 `json.Unmarshal`、`json.Marshal` 与 `sha256.Sum256`。
  - `intrinsicCountTick` 在单帧内被无条件调用 4 次（`sim.go:1265, 1304, 1343, 1368`），即使当前对局中没有任何干员拥有 `EnemyCountAttackSpeed`。
- **改法**：
  - 将 `intrinsicCountSource` 的有效性校验固化在 `newEnemy` 创建阶段或 `SpawnSpec` 准备阶段，运行时直接读取 `spec.IntrinsicCountVisibility` 的解析结果（或布尔标记）。
  - 在 `simCtx` 中标记 `sceneUsesCount`，当本局无相关特性时，单帧 4 次的 `intrinsicCountTick` 快速短路返回。

#### 1.3 `simCtx.enemyAt` 与 `PauseEnemy` 查找优化
- **现状定位**：
  - `rios-sim/sim.go:1708-1725`：`enemyAt(index)` 与 `PauseEnemy(index)` 每帧被田地减速、天桩血量同步、积雪冻结频繁调用，每次都线性遍历 `*c.enemies`。
- **改法**：
  - `index` 在 `simCtx` 中由出怪表与召唤计数顺序单调递增。在 `simCtx` 中维护按 `index` 直接寻址的索引切片 `enemyByIndex []*enemy`（在 `newEnemy` 入场时注册，`offMap`/清理时不移动槽位），将查找时间由 $O(N)$ 降至 $O(1)$。

#### 1.4 高台溅射地块静态缓存与折线长度预计算
- **现状定位**：
  - `rios-sim/sim.go:2721-2724`：每次溅射触发时都实时创建 `highland := map[[2]int]bool{}` 并遍历填充。
  - `rios-sim/sim.go:2182-2203`（`pointAt`）：折线步进每帧都从第 0 个点重新累加 `num.Hypot` 计算折线段长度。
- **改法**：
  - `spec.HighlandCells` 在战斗生命周期内为只读常量，在 `simCtx` 初始化时构建一次 `highlandMap` 并复用。
  - 在 `setRoute` 或 `LegSpec` 构建时预计算各分段长度累计数组 `cumLens []float64`，推进时通过二分或顺序段索引直接定位，省去每帧重复的开方运算。

---

### 阶段二：机制层切片分配与视图复用（Zero-Allocation View Buffers）

目标：消除机制包（`mech`）与主循环之间每帧多次全量分配拷贝 `mech.EnemyView` 与 `mech.OpView` 的 GC 压力。

#### 2.1 `simCtx.Enemies()` 与 `simCtx.Operators()` 缓冲复用
- **现状定位**：
  - `rios-sim/sim.go:1477-1522`：单帧内机制层多次调用 `ctx.Enemies()` 与 `ctx.Operators()`，每次都执行 `make([]mech.EnemyView, 0, len(*c.enemies))` 并逐个赋值，随后立即丢弃。
- **改法**：
  - 在 `simCtx` 结构体中持有预分配的 `enemyViewBuf []mech.EnemyView` 与 `opViewBuf []mech.OpView`，每次调用复用底层数组（`buf = buf[:0]`），避免每帧向 Go 运行时堆申请大量短命切片。

#### 2.2 怀黍离 `AttackTickFrame` 双重扫描合并
- **现状定位**：
  - `rios-sim/mech/huai_shu_li.go:1413-1430`：`AttackTickFrame` 内部首先调用一次 `ctx.Enemies()` 构造临时 `skillAtkState` 校验首拍帧数合法性，紧接着进入 `attackTickMode` 再次调用 `ctx.Enemies()` 执行战斗结算。
- **改法**：
  - 将静态的首拍与间隔合法性检查移至关卡装配期（`BuildSpec` / `MechSpecBuild`），运行时主循环单次扫描直接推进计时器与攻击逻辑。

---

### 三：Beam 搜索与规格构建链路优化（Solver & BuildSpec Acceleration）

目标：大幅降低在 `Solve`（Beam 搜索）过程中对成百上千个状态评估时的冗余开销。

#### 3.1 关卡级静态规格多级缓存（`buildInputs` 静态复用）
- **现状定位**：
  - 在 `solver.go:301-364` 中，对搜索树中每个候选状态（仅干员部署位置和顺序不同），`buildSimSpecFromQueryWithInputs` 都会重复执行：
    1. `spawnsOfWithInputs`：重新遍历波次时间轴与所有敌人数据（完全与计划无关）。
    2. `UnsupportedGate`：重新遍历全关所有敌人的未支持特性。
    3. `MechSpecBuild`：重新计算田地连通域、初始播种地块与天桩召唤链。
- **改法**：
  - 在 `buildInputs` 中加入关卡级纯静态规格的缓存：`spawnsOnce`、`gateStaticOnce`、`farmlandStaticOnce`。
  - 单次搜索任务中，只在第一手状态装配时解析一次全关静态数据；后续各状态的评估只组装当前候选方案的 `operators`、`deploys` 与计划相关的雪地配置。

#### 3.2 消除内部评估通道的多重 JSON 编解码往返
- **现状定位**：
  - 搜索内部 `evalStateWithInputsContext`：
    `plan -> json.Marshal -> 拼入qj -> json.Marshal -> ClassifySimSpec(json.Unmarshal) -> ParseSimQuery(json.Unmarshal) -> BuildSpecFull -> json.Marshal -> json.Unmarshal(wire.Spec)`。
- **改法**：
  - 保持外部 CLI 入口契约不变（严格校验 JSON 输入与顶层键完整性）。
  - 为内部调用（`solver` 引擎内部）提供纯内存的装配路径 `buildSimSpecDirect(inputs, plan, st)`，直接在 Go 结构体层面流转，免去每个状态 4 次全量序列化/反序列化。

---

## 三、 执行里程碑与验收标准

| 阶段 | 任务目标 | 核心修改文件 | 验收判据 |
| :--- | :--- | :--- | :--- |
| **M1** | 帧内热路径与日志零装箱 | `sim.go`, `huai_shu_li.go`, `count_aspd.go` | 全量单测通过，`TestRunSimHuaiShuLiRepresentativeStages` 逐位同序通过，基准耗时下降 |
| **M2** | 机制层视图切片缓冲化 | `sim.go`, `huai_shu_li.go` | 内存分配速率（allocs/op）显著减少，怀黍离与隐德来希测试 100% 绿 |
| **M3** | 规格构建静态缓存与 JSON 旁路 | `build_inputs.go`, `buildspec.go`, `solver.go` | Beam 搜索评估千级状态耗时显著减少，搜索产出与决策排程逐字一致 |
