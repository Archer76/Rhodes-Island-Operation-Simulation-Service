# 工单：冻河（char_4244_tocka）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-03-tocka-mechanics.md`
- **目标**：实现六星辅助·游击手冻河（char_4244_tocka）的游击手特性协同机制、第一天赋「夜的哑然」、第二天赋「雪的印痕」、S1「一无所有之人」、S2「意欲呼啸之心」、S3「踯躅独行之春」全生命周期闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4244_tocka-mechanics.md`，完成全量黑板键审计台账与三态结论；中文名词 100% 遵照官方 gamedata 原文；
  2. 规格层 `tocka_spec.go`/`tocka_config.go` 与运行时 `tocka_runtime.go`/`tocka_sim_tick.go` 完整落地；
  3. 游击手特性（触发协同施加与生效）、天赋一（受击 SP 回复与生命汲取恢复）、天赋二（范围协同增伤与虚弱持续法术伤害）、S1（衰减屏障与击晕）、S2（全图协同与常态攻速提升）、S3（多目标击晕打击、全队衰减攻击力加成与协同传递转移）真实行使；
  4. 专项测试套件 `TestTocka*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 在仓外独立 worktree `D:\home\DSH\ak-tactic-tocka-20261103`（分支 `wip/tocka-mechanics-20261103`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设），不得在业务开发树混用；
  2. 出现与本次改动相关的非环境测试失败且无法定位时立即停手；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：专项测试 7 项全 PASS 1.90s；官方术语守护 tools/audit_official_terminology.py 0 违规；全干员综合回归 71.5s 全 ok）。
- **worker 形态**：新会话（`session-628657dc-b5d8-4521-8487-e860d921554b`）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：649485f）
