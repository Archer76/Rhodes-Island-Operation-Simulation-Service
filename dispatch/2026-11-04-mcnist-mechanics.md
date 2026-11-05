# 工单：机械师（char_4230_mcnist）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-04-mcnist-mechanics.md`
- **目标**：实现六星重装·哨戒铁卫干员机械师（char_4230_mcnist）的哨戒铁卫分支特性（挡3进行远程攻击）、第一天赋「结构性原理」、第二天赋「生命方程」、S1「聚类分析」、S2「协防术式」、S3「工程学十字星」全生命周期闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4230_mcnist-mechanics.md`，完成全量黑板键审计台账与三态结论；中文名词 100% 遵照官方 gamedata 原文；
  2. 规格层 `mcnist_spec.go`/`mcnist_config.go` 与运行时 `mcnist_runtime.go`/`mcnist_sim_tick.go` 完整落地；
  3. 哨戒铁卫特性（阻挡3且远程攻击）、天赋一/二生命方程生命回复、S1高频多段连射、S2阻挡协防范围护盾、S3十字大范围重炮轰击真实行使；
  4. 专项测试套件 `TestMcnist*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 运行 `python tools/audit_official_terminology.py` 达到 0 违规；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-mcnist-20261104`（分支 `wip/mcnist-mechanics-20261104`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设），不得在业务开发树混用；
  2. 严禁加入任何房间，完工通过定向单播单向推回发起会话；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：专项测试 7 项全 PASS 2.92s；官方术语守护 tools/audit_official_terminology.py 0 违规；全干员综合回归 80.5s 全 ok）。
- **worker 形态**：新会话（`session-6f1383e9-7ba8-48c2-a43f-396cd3a1b130`，无房隔离模式）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：be5a123）
