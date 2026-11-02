# 工单：塔露拉（char_4247_oxi）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-02-talulah-mechanics.md`
- **目标**：实现六星近卫·原质近卫塔露拉（char_4247_oxi）的特性真实伤害/元素损伤、第一天赋不息之火、第二天赋原初烈焰力场、S1熔火恐惧、S2高额减伤反击与自愈、S3天火焚原火浪推移与过载焚原全闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4247_oxi-mechanics.md`，完成全量黑板键审计台账与三态结论；
  2. 规格层 `oxi_spec.go`/`oxi_config.go` 与运行时 `oxi_runtime.go`/`oxi_sim_tick.go` 完整落地；
  3. 原质近卫特性（阻挡所有敌人、攻击造成真实伤害/元素损伤）、S1 战栗/恐惧（`fear`）、S2 受击减伤反击与生命汲取、S3 停攻火浪弹道推进与过载全宽焚原真实行使；
  4. 专项测试套件 `TestOxi*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 在仓外独立 worktree `D:\home\DSH\ak-tactic-talulah-20261102`（分支 `wip/talulah-mechanics-20261102`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；
  2. 出现与本次改动相关的非环境测试失败且无法定位时立即停手；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（机制数值与战斗循环由主会话在合入前亲自全量复测）。
- **worker 形态**：新会话（`de_session spawn`，满足独立 worktree、长轮次自洽及可唤醒要求）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：在飞
