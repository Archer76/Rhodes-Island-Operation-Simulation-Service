# 工单：电弧（char_4195_radian）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-04-radian-mechanics.md`
- **目标**：实现六星辅助·召唤师干员电弧（char_4195_radian）的召唤师分支特性、第一天赋「卡带里的灵感」、第二天赋「加油~」、S1「律动线」、S2「环形鳄地」、S3「手牵手」全生命周期闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4195_radian-mechanics.md`，完成全量黑板键审计台账与三态结论；中文名词 100% 遵照官方 gamedata 原文；
  2. 规格层 `radian_spec.go`/`radian_config.go` 与运行时 `radian_runtime.go`/`radian_sim_tick.go` 完整落地；
  3. 召唤物库存管理、第二天赋全属性加成、S1护盾防御加成、S2常驻强化攻击、S3大范围减速法术脆弱与召唤物协同打击真实行使；
  4. 专项测试套件 `TestRadian*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 运行 `python tools/audit_official_terminology.py` 达到 0 违规；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-radian-20261104`（分支 `wip/radian-mechanics-20261104`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设），不得在业务开发树混用；
  2. 严禁加入任何房间，完工通过定向单播单向推回发起会话；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：专项测试 2 项全 PASS 2.00s；官方术语守护 tools/audit_official_terminology.py 0 违规；全干员综合回归 83.6s 全 ok）。
- **worker 形态**：新会话（`session-c0a692f1-3ecd-4f3f-87cd-89e5f3877210`，无房隔离模式）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：cf5b588）
