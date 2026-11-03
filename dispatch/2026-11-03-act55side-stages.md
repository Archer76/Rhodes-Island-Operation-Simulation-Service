# 工单：本期活动《时间啊，向前！》（TL-1 至 TL-10）关卡包与引擎集成

- **工单编号**：`dispatch/2026-11-03-act55side-stages.md`
- **目标**：实现本期活动《时间啊，向前！》（act55side，代号 TL）目前开放的普通关卡 TL-1 至 TL-10 及训练关 TL-TR-1 关卡数据包（`data/stages_act55side.sqlite`）打包构建，并在 Go 仿真引擎中完成关卡包注册、战壕地块（`tile_trench`）接入与全关卡端到端加载及战斗生命周期回归验证。
- **完成判据**：
  1. 编写打包脚本 `tools/build_stages_act55side.py`，从本地逐关 JSON（`levels/activities/act55side/`）构建生成 `data/stages_act55side.sqlite`（涵盖 TL-1 ~ TL-10 及 TL-TR-1 共 11 关）；
  2. 在 Go 引擎 `stage_pack_loader.go` 与 `cmd/rios-tui/pick.go` 注册 `stages_act55side.sqlite`；
  3. 确认并接入战壕地块（`tile_trench`）与预定义装置（`trap_342_dsjhye`, `trap_347_dsjfye`, `trap_355_dsjsye`）；
  4. 编写专项测试套件 `TestSqliteResourcePackAct55Side`，断言 TL-1 至 TL-10 全量关卡地块宽长、生命值、初始费用与出怪 Spawns 100% 正确装配；
  5. 专项测试与全干员回归测试用例级真实 PASS；
  6. 官方术语守卫 `python tools/audit_official_terminology.py` 达到 0 违规；
  7. 在仓外独立 worktree `D:\home\DSH\ak-tactic-tl-stages-20261103`（分支 `wip/tl-stages-20261103`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义关卡机制具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设）；
  2. 出现非环境测试失败立即停手；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：关卡包构建 10 关就绪，TestSqliteResourcePackAct55Side 专项测试 0.33s PASS，全包回归 73.9s 全绿，术语守卫 0 违规）。
- **worker 形态**：新会话（`session-145a564c-07da-400d-8041-db48a454b392`）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：3de6c37）
