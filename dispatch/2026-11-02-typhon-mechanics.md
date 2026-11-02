# 工单：提丰（char_2012_typhon）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-02-typhon-mechanics.md`
- **目标**：实现六星狙击·攻城狙击手提丰（char_2012_typhon）的特性重量优先索敌、天赋破甲叠层、二技能无限持续与概率晕眩（V-2 规范）及三技能全图锁定弹药生命周期全闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_2012_typhon-mechanics.md`，完成全量黑板键审计台账与三态结论；
  2. 规格层 `typhon_spec.go`/`typhon_config.go` 与运行时 `typhon_runtime.go`/`typhon_sim_tick.go` 完整落地；
  3. 攻城狙击手特性重量优先索敌（`Weight` 权重判定）、连续攻击破甲叠层（天赋一）、未阻挡增伤（天赋二）真实行使；
  4. S2 概率晕眩（遵循 V-2 规格种子伪随机规范）与二次开启无限持续状态机、S3 全图锁定与弹药生命周期（`attack@s3_max_hit_num`）真实行使；
  5. 专项测试套件 `TestTyphon*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  6. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data`）用例级全绿，无相关失败；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-typhon-20261102`（分支 `wip/typhon-mechanics-20261102`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；
  2. 出现与本次改动相关的非环境测试失败且无法定位时立即停手；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（机制数值与战斗循环由主会话在合入前亲自全量复测）。
- **worker 形态**：新会话（`de_session spawn`，满足独立 worktree、长轮次自洽及可唤醒要求）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：继承默认工作预设与路由。
- **状态**：在飞
