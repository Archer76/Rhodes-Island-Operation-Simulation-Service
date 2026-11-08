# 工单：本期活动《时间啊，向前！》高难关卡（TL-EX-1 至 TL-EX-8）关卡包与引擎集成

- **工单编号**：`dispatch/2026-11-05-act55side-tlex-stages.md`
- **目标**：实现本期活动《时间啊，向前！》（act55side，代号 TL）最新开放的高难度关卡 TL-EX-1 至 TL-EX-8（普通 NORMAL 与突袭 FOUR_STAR 档位，共 16 档）关卡数据包更新（`data/stages_act55side.sqlite`），升级 `tools/build_stages_act55side.py`，并在 Go 仿真引擎中完成 TL-EX 关卡装配与端到端回归测试验证。
- **完成判据**：
  1. 升级关卡打包脚本 `tools/build_stages_act55side.py`，支持 TL-1~10 与 TL-EX-1~8（含突袭档）的统一构建，兼容 `actionType` 数字/字符串格式；
  2. 关卡包 `data/stages_act55side.sqlite` 完整收录 TL-1 至 TL-10 与 TL-EX-1 至 TL-EX-8（共 26 关卡档位）；
  3. 扩充 `rios-sim/stage_tl_test.go`，遍历测试 TL-EX-1 至 TL-EX-8 全部 16 档位加载、Spawns 解析、突袭词条与端到端仿真；
  4. 专项测试 `TestSqliteResourcePackAct55Side` 与全干员回归测试用例级真实 PASS；
  5. 官方术语守卫 `python tools/audit_official_terminology.py` 达到 0 违规；
  6. 在仓外独立 worktree `D:\home\DSH\ak-tactic-tlex-stages-20261105`（分支 `wip/tlex-stages-20261105`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到未定义关卡机制具名上报 Gap 拒判；若需逆向工具必须自行 spawn 逆向专用会话（reverse 预设）；
  2. 严禁加入任何房间，完工通过定向单播单向推回发起会话；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：关卡包构建 26 关全量就绪，TestSqliteResourcePackAct55Side 专项测试 0.22s PASS，全包回归 56.5s 全绿，术语守卫 0 违规）。
- **worker 形态**：新会话（`session-942f0b5b-f210-4142-93a1-d83649038abd`，无房隔离模式）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：59b2b2e）
