# 工单：国度（char_4246_dminon）机制全生命周期闭环

- **工单编号**：`dispatch/2026-11-04-dminon-mechanics.md`
- **目标**：实现六星特种·伏击客干员国度（char_4246_dminon）的伏击客特性、第一天赋「实质坍缩」（“国度”领域弥漫、地面敌人攻速降低与法术DoT）、第二天赋「此身为界」（撤退/离场全“国度”敌人500%法伤爆破与5秒眩晕）、S1「停步」（踏入停顿）、S2「受戮」（反隐避破闪避与二次开启无限持续）、S3「无人之国度」（全“国度”群攻、受击四格扩散“国度”与反击伤害）机制全生命周期闭环。
- **完成判据**：
  1. 产出干员机制口径文档 `docs/char_4246_dminon-mechanics.md`，完成全量黑板键审计台账与三态结论；中文名词 100% 遵照官方 gamedata 原文；
  2. 规格层 `dminon_spec.go`/`dminon_config.go` 与运行时 `dminon_runtime.go`/`dminon_sim_tick.go` 完整落地；
  3. 伏击客特性（范围全攻、50%双闪避、低嘲讽）、第一天赋“国度”地块生成与属性加成、第二天赋离场终结爆破、S1首次踏入停顿、S2无视闪避与二次开启无限持续、S3全“国度”打击与受击四格地块动态扩散真实行使；
  4. 专项测试套件 `TestDminon*` 全部真实 PASS（输出逐条 `--- PASS` 名称与耗时）；
  5. 全包回归（`RIOS_DATA=D:\home\DSH\ak-tactic\data\gamedata`，`RIOS_DB=D:\home\DSH\ak-tactic\data` 目录）用例级全绿，无相关失败；
  6. 运行 `python tools/audit_official_terminology.py` 达到 0 违规；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-dminon-20261104`（分支 `wip/dminon-mechanics-20261104`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义机制严禁猜想，具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设），不得在业务开发树混用；
  2. 出现与本次改动相关的非环境测试失败且无法定位时立即停手；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（机制数值与战斗循环由主会话在合入前亲自全量复测）。
- **worker 形态**：新会话（`de_session spawn`，满足独立 worktree、长轮次自洽及可唤醒要求）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：在飞
