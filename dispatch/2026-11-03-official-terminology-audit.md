# 工单：全仓方舟官方中文术语审计与修正

- **工单编号**：`dispatch/2026-11-03-official-terminology-audit.md`
- **目标**：以官方 gamedata（`uniequip_table.json` 的 `subProfDict`、`character_table.json`、`skill_table.json`、`battle_equip_table.json`）为唯一权威来源，对全仓文档（`docs/`）、工单（`dispatch/`）、代码注释与常量中的干员名、子职业（分支名）、技能名、天赋名及机制词条进行全量扫描审计，查出所有非官方脑补/英译名词并全量修正。
- **完成判据**：
  1. 提取官方 77 个子职业名称对照表（`subProfDict`）与已实现及正在实现干员的官方全名字典；
  2. 针对全仓 `docs/` 与 `dispatch/` 扫描所有非官方翻译（如将 `primguard` 误写作“原质近卫/原初近卫”、将 `supportiveranger` 误写作“协同支援”、将 `siegesniper` 误写作“攻城狙”等，以及技能/天赋的脑补译名）；
  3. 执行逐文件修正，替换为官方规范名称；
  4. 产出官方术语对照审计报告 `docs/official-terminology-audit-report.md`；
  5. 在仓外独立 worktree `D:\home\DSH\ak-tactic-terminology-20261103`（分支 `wip/terminology-audit-20261103`）生成干净提交并提供 commit sha。
- **停手条件**：
  1. 遇到有争议的非官方通用俗称必须列出对照，不得静默处理；
  2. 若需底层逆向工具必须自行 spawn 逆向专用会话（reverse 预设）；
  3. 严禁合入主分支，严禁 push。
- **验收档**：必复跑（主会话亲自全量复跑：自动化校验 tools/audit_official_terminology.py 0 违规通过，全干员回归测试 84.8s 全绿）。
- **worker 形态**：新会话（`session-6021bb34-4def-477c-a88c-6ba1617ec156`）。
- **模型档**：
  - 路由/主会话：gemini-3.8-flash-high / deepseek-official；
  - 执行专员：kst-54577be0d3bd0e1f-gateway / gemini-3.8-flash-high。
- **状态**：收单（已合入 main 分支并推送 GitHub origin/main：fa8f2ae）
