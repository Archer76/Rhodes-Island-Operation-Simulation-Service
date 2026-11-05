# 工单：圣聆初雪（char_1046_sbell2）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-04-sbell2-mechanics.md`
- **目标**：实现六星术师·阵法术师干员圣聆初雪（char_1046_sbell2）的阵法术师分支特性（常态高防抗不攻、开技群法）、第一天赋「无垠的雪景」、第二天赋「圣山的祝福」（免死满血复活 `blessing_save`）、S1「铃音吹雪」、S2「霜涛覆岭」、S3「群山俯首」全生命周期闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_1046_sbell2-mechanics.md`，完成全量黑板键审计台账与三态结论；中文名词 100% 遵照官方 gamedata 原文；
  2. 规格层 `sbell2_spec.go`/`sbell2_config.go` 与运行时 `sbell2_runtime.go`/`sbell2_sim_tick.go` 完整落地；
  3. 阵法术师特性（常态大额物法抗性增益与停攻、技能开启群攻）、第一天赋寒冷减速与雪景力场、第二天赋受致命伤免死满血复活与周围敌人大额冻结、S1多目标寒冷推动、S2冻结蔓延、S3法抗削弱牵引与爆发真实行使；
  4. 专项测试套件 `TestSbell2*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 运行 `python tools/audit_official_terminology.py` 达到 0 违规；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-sbell2-20261104`（分支 `wip/sbell2-mechanics-20261104`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设），不得在业务开发树混用；
  2. 严禁加入任何房间，完工通过定向单播单向推回发起会话；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：专项测试 5 项全 PASS 0.98s；官方术语守护 tools/audit_official_terminology.py 0 违规；全干员综合回归 77.2s 全 ok）。
- **worker 形态**：新会话（`session-1862a370-3c17-4dc2-8c91-b251142d909b`，无房隔离模式）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：d715b24）
