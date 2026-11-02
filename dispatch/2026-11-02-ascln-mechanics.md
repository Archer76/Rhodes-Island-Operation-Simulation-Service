# 工单：阿斯卡纶（char_4132_ascln）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-02-ascln-mechanics.md`
- **目标**：实现六星特种·伏击客阿斯卡纶（char_4132_ascln）的特性、天赋、技能与模组机制全生命周期闭环，遵循零近似与 V-2 精准抽样规范。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4132_ascln-mechanics.md`，完成全量黑板键审计台账与三态结论；
  2. 规格层 `ascln_spec.go`/`ascln_config.go` 与运行时 `ascln_runtime.go`/`ascln_sim_tick.go` 完整落地；
  3. 伏击客范围减速叠层（天赋一）、攻速加成（天赋二）、物理/法术命中率抽样（技能三，遵循 V-2 规格种子伪随机规范）真实行使；
  4. 专项测试套件 `TestAscln*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data`）用例级全绿，无相关失败；
  6. 在独立 worktree `D:\home\DSH\ak-tactic-ascln-20261102`（分支 `wip/ascln-mechanics-20261102`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制或数据冲突时严禁臆测与粗糙折算，必须具名上报 Gap 拒判；
  2. 出现与本次改动相关的非环境测试失败且无法快速定位时立即停手；
  3. 严禁自行合并入主分支 `main`，严禁执行 `git push`。
- **验收档**：必复跑（主会话独立全量复跑：专项测试 4 项全 PASS 0.78s；全包回归 rios-sim 66.2s / maa 19.6s / data 1.8s / tui 5.1s 全 ok）。
- **worker 形态**：新会话（`session-4d6b85b0-d80f-40f0-a10a-3251e94167b5`）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：继承默认工作预设与路由。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：b164f4b）

