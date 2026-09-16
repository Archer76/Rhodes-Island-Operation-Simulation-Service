# R.I.O.S. · 罗德岛作战演算服务
**Rhodes Island Operation Simulation Service**

罗德岛作战演算服务：给定战场地图与干员名册，演算出部署位置、技能开启时机与胜负判定。
——记录已归档。愿每一次作战，都将胜利。

> 权限校验通过。演算申请已受理。

这不是一个小工程。从「情报不足」到「方案成立」，中间隔着四道坎：**把数据收全 → 把数值核定 → 把时间轴推演出来 → 在巨大的方案空间里找到可行解**。四道坎均已跨越，各成一节；节点之间由 **793 项复核**与**三条基线记录**固定——任何一处改动，都必须让那三个数逐字复现。

编号得自游戏内的 PRTS 系统：Primitive Rhodes Island Terminal Service。它曾为一次搜救自行演算，留下 167 份过程记录与 3,711 个执行节点，而其中仅有两个结果能导向成功。本服务做的是同一件事——将那类「可能导向胜利的计算」做成可复现的程序。区别只在演算对象：一次是博士的搜救，一次是你自己的作战。

> 约定：本仓库里 **PRTS** 一律指游戏内的终端系统；取数用的资料站一律写作 **prts.wiki**。两者同名不同物，按写法分辨即可。

数据有两条来源，分得很清楚：**文字资料查 prts.wiki 资料站，机器要算的数值查 gamedata**。

## 已接入模块

| 节点 | 职能 |
| --- | --- |
| 情报整备 | 建立两份离线档案：干员档案（gamedata，**不联网**，3.4 秒）与敌人档案（prts.wiki，首次约 53 秒）；地块字典另循 theresa.wiki |
| 属性核定 | 核定一名干员的真实面板：等级插值 ＋ 信赖 ＋ 潜能 ＋ 模组；攻击速度 ＝ 天赋 ＋ 模组特性改写 ＋ 技能 |
| 作战演算 | 30fps 逐帧推演：伤害（物理／法术／真实，含 5% 保底与法抗满值免疫）、阻挡与目标选择（敌人优先攻击最后部署的干员）、伤害相性与击破倒地、全场总攻击装置 |
| 正文编译 | 将技能／天赋／模组／敌技的**中文正文**编译为可结算的公式项——只读黑板会漏算，不读正文会算错 |
| 方案求解 | 复核一份打法、搜索一套可三星的阵容、按该次作战的费用环境编成名册 |
| 记录导出 | 摆位图／时间轴／路线热度／漏怪归因报告，以及 MAA copilot 作业 |

## 作业规程

- **只搬不推**：档案存原文（关键帧、黑板），插值与加成留在核定层——两处各算一遍，迟早对不上。
- **未知量必须实测标定**：编出来的默认值未必保守，它可能正好落在好看的那一边。

---

## 快速开始

**零第三方依赖。** 全部代码只用 Python 标准库——`urllib` 取数、`sqlite3` 存库、
`re` 解析正文、`argparse` 做 CLI。没有 `requirements.txt`，也不需要 `pip install`。
本机实测 **Python 3.14.4**；未用版本敏感语法，3.10+ 应当都能跑。

```bash
cd <仓库目录>

# 1) 建两个本地库
python -m ak_tactic db build          # 干员库，不联网，约 3.4s
python -m ak_tactic enemydb build     # 敌人库，要联网，首次约 53s（prts.wiki 限速 1.2s/请求）

# 2) 跑全套自检 —— 十套共 793 项，全绿才算没退化
python tools/check_db.py              # 64
python tools/check_enemy_db.py        # 62
python tools/check_battle.py          #117
python tools/check_p3r.py             # 65
python tools/check_formula.py         #100
python tools/check_enemy_formula.py   #162
python tools/check_verify.py          # 68
python tools/check_eta.py             # 35
python tools/check_search.py          # 71
python tools/check_diagram.py         # 49

# 3) 复现三条回归基线（改战斗模型后必须逐字不变）
python -m ak_tactic verify main_01-07 \
    --team "阿米娅:5,2:Left:0@1; 德克萨斯:4,3:Right:0@5; 拉普兰德:2,3:Right:0@9"
python tools/run_sr6.py
python tools/export_srx8.py
```

**三条基线**（任何一处改动后都要重新对这三个数）：

| 关卡 | 配置 | 结果 |
| --- | --- | --- |
| 1-7 | 阿米娅(5,2)朝左 + 德克萨斯(4,3)朝右 + 拉普兰德(2,3)朝右，1/5/9s 落地 | **137.0s / 41 杀 / 0 漏**，总伤害 60,750 |
| SR-6 | `tools/run_sr6.py` 三个档位 | **196.6 / 201.4 / 196.6 s**，21 杀 0 漏剩 3 命，617,000 |
| SR-EX-8 | `tools/export_srx8.py` 四人剑气 | **219.8s / 38 杀 / 1 漏 / 剩 2 命（二星）** |

> 这三条是**回归锚点**，不是可执行作业——1-7 那条的开局三人在费用上其实都做不到
> （见 §七 第 16 条），它锚的是地图/路线/伤害的一致性。

**需要联网的两处**：gamedata（关卡与敌人数值，走 `map.ark-nights.com` 与 GitHub 镜像）
与 prts.wiki（干员文字资料、敌人页面）。两者的响应都落 `data/cache/`，**7 天 TTL**，
重复跑不会重新请求。干员库建库完全不联网。

---

## 一、任务拆分

### 阶段 1 · 干员数据 ✅ 已完成

| 子项 | 状态 | 说明 |
| --- | --- | --- |
| 干员名录 | ✅ | Cargo `chara_data` 全表 461 条；SMW 可按职业/星级筛 |
| 基础信息 | ✅ | 名字（中/英/日）、干员 id、序号、星级、职业、分支、位置、标签、特性、画师、配音 |
| 数值面板 | ✅ | 精英 0/1/2 各阶段的 1 级与满级四维（HP/ATK/DEF/RES）、信赖加成、等级上限 |
| 部署参数 | ✅ | 再部署、部署费用、阻挡数、攻击间隔、所属势力、隐藏势力 |
| 天赋 | ✅ | 每个天赋的各阶段效果，含模组强化版与潜能增强版，条件已结构化 |
| 技能 | ✅ | 每个技能的 7 级 + 专精 1/2/3：描述、初始 SP、消耗 SP、持续、回复/触发类型、开放条件 |
| 模组 | ✅ | 1/2/3 级四维增量、特性追加、天赋改写、解锁等级与信赖 |
| 攻击范围 | ✅ | `Widget:Range` SVG → 相对自身格坐标集合，支持旋转与覆盖判定 |
| 潜能 | ✅ | 潜能 2–6 的效果文本与数值 |

### 阶段 1.5 · 干员属性计算 ✅ 已完成（改走 gamedata + 插值）

任意「精英阶段 × 等级 × 信赖 × 潜能 × 模组」的组合都能算出面板数值。
原来的「数值面板」一栏只有各阶段的 1 级与满级，中间等级是空的；现在补齐了。

| 加成来源 | 数据 | 要点 |
| --- | --- | --- |
| 等级 | `character_table.phases[].attributesKeyFrames` | 只存关键帧，中间靠**线性插值**；阶段内等级从 1 重新开始 |
| 信赖 | `character_table.favorKeyFrames` | level 0–50 ↔ **游戏内显示信赖 0%–200%**；`trust` 参数是 **0–100 内部标度**（= 显示值 ÷ 2，100 即满信赖 200%） |
| 潜能 | `character_table.potentialRanks` | 5 项对应**潜能 2–6**，潜能 1 无加成 |
| 模组 | `battle_equip_table[].phases[].attributeBlackboard` | 取该等级那一份**总加成**，不是增量 |

- 数据源：`excel/` 三张表，**只有 GitHub 镜像提供**（ark-nights 不带 `excel/`，一律 404）
- 六个端点值与 prts.wiki 属性模板逐项核对，**全部一致**
- 产出：`OperatorCalculator` / `OperatorStats`

### 阶段 2 · 敌人数据 ✅ 已完成（改走 gamedata）

- 敌人图鉴：中文名、编号、描述、伤害类型、免疫标签
- 敌人数值：HP/ATK/DEF/法抗、重量等级、移动速度、攻击间隔、漏怪扣血量、多档位
- **决定性发现（第一次）**：prts.wiki 的 Cargo 里没有敌人表、SMW 也不覆盖敌人属性，
  所以这一块先整体改走了 gamedata（`enemy_database.json`，2151 个敌人分档数值）。
- **决定性发现（第二次，2026-09-16）**：prts.wiki 的**敌人页本身**其实带完整结构化数据——
  `{{敌人信息/common2}}` + 每档一个 `{{敌人信息/levelcontent}}`，图鉴文本、
  逐档数值、抗性、敌方技能、天赋黑板（P3R 相性 / 倒地阈值）全在一处。
  于是又建了一个**独立的**敌人库（见"两个本地库为什么分成两个文件"）。
  两条路并存：`EnemyLibrary` 走 gamedata 供模拟器实时取数，
  `data/enemydb.sqlite` 走 prts.wiki 供全量 SQL 查询；9 个锚点已逐项对过账。
- 产出：`EnemyLibrary` / `EnemyStats`（gamedata）+ `data/enemydb.sqlite`（prts.wiki）

### 阶段 3 · 关卡数据 ✅ 已完成（改走 gamedata）

- 地图网格：11×7 的格子类型（高台/地面、可部署近战/远程、可通行）
- 出怪路线：27 条折线的出生点、途经点、防守点
- 波次时间轴：把 fragment/action 摊平成每个敌人的具体出现时刻
- **坐标口径（2026-09-16 改）**：全项目内部一律 **MAA 标准**——原点左上、y 向下，
  与 MAA copilot 的 `location: [x, y]` 完全同口径，导出作业零换算。
  `mapData.map` 的第 0 行本来就在最上面，直接按行读即可；反倒是关卡 JSON 里
  `routes[].row` 是游戏内部口径（自下而上），解析时翻一次。
- 关卡参数：初始费用、费用回复、可部署上限、生命值
- 产出：`Stage` / `StageMap` / `Route` / `EnemySpawn`，报告见
  [docs/stage-1-7.md](docs/stage-1-7.md)（主线教学图）与
  [docs/stage-sr-ex-8.md](docs/stage-sr-ex-8.md)（活动高难图，带传送机制）
- 原计划「用 prts.wiki 的关卡页面」被证伪：那种页面上只有文字攻略，
  真正的地图网格与路线只存在于游戏解包数据里

### 阶段 4 · 战斗模型 ✅ 完成

代码在 `ak_tactic/battle/`（`damage.py` / `unit.py` / `range.py` / `sim.py`，
模拟器本体约 67 KB），自检 `tools/check_battle.py`（117 项）、
`tools/check_p3r.py`（65 项）。

- 伤害结算：物理（ATK−DEF，下限为 ATK×5%）、法术（ATK×(1−RES/100)）、真实、治疗
- 攻速与攻击间隔：干员攻击间隔、**总攻速**（基础 100 + 天赋 + 模组特性改写；
  其中「未阻挡敌人时」是条件加成，按当前是否挡住敌人**逐帧**判定）、技能改间隔
- SP 回转：自动回复/攻击回复/受击回复 + 初始 SP + 消耗 SP + 持续
- 时间轴推进：按帧（1 秒 = 30 帧）离散推进，处理部署/撤退/开技能
- 另外还多做了原计划没写的三块：**天赋与特性**（含从文本推的攻法类型、
  治疗、弱点伤害）、**模组**、**关卡装置**（SR 系列的「全场总攻击」几乎
  是那两关的输出主轴）
- 已知未建模：元素损伤结算、浮游单元叠加、火环 ticks —— 见第七节

### 阶段 5 · 求解与搜索 ✅ 完成

**到达时刻模型**（2026-09-16）：

- `ak_tactic/eta.py` —— 从「移速 + 路线」**解析式**算出「几点到哪一格」。
  走段耗时 = 距离 ÷ 速度，等待/离场段 = 真实秒数；速度
  `格/秒 = moveSpeed × move_multiplier × speed_scale`。
  提供 `ArrivalIndex` 按格反查：某片格子上累计有多少**敌人·秒**（dwell）、
  最早几时被占、时间窗内几次进入。**这是搜索器剪枝的依据**。
- **路线解析与模拟器共用一份实现**（`route_plans()`），不是两处各算一遍；
  模拟器把结果挂在自己的 `route_plans` 上供外部核对，自检里有共源守卫。
- 精度：与模拟器逐只对拍，最大误差 **0.033s = 一帧**（1-7 41 只 / SR-6
  21 只 / SR-EX-8 39 只全对）。
- 顺手修掉一个真 bug：`sim._spawn` 里 `move_speed` 的 `or 1.0` 兜底会把
  **移速 0 的敌人**（库里 23 页）兜成 1.0，让永不移动的敌人满地图跑。
  同一个函数里 `life_cost` 早先因为同样的写法踩过一次。

**验证器**（2026-09-16）：

- `ak_tactic/plan.py` —— 关卡无关的打法表示：阵容 + 落位 + 朝向 + 部署时机
  + 技能时机 + 练度（含信赖/潜能/模组）。JSON 可存可读，`validate()` 拦下
  模拟器**不会替你拦**的错（同一格放两人、同一人下两次、朝向拼错、技能槽越界、
  落点与地形不相容）。
- `ak_tactic/verify.py` —— 给定 Plan 出三星判定与归因：星级、击杀、漏怪
  **明细**（时刻 + 敌人 + 扣血量）、逐人战报（出手数/承伤/阵亡时刻）、
  装置触发情况、以及自动生成的归因文字。带排序键 `Verdict.rank()`。
- CLI：`python -m ak_tactic verify <关卡> --plan p.json`
  或 `--team "阿米娅:5,2:Left:0@1; 德克萨斯:4,3:Right:0@5"`（`--box` 指名册）。

**搜索器**（2026-09-16）：

- `ak_tactic/search.py` —— 两层结构。**第一层几何剪枝**（不算打架）：
  用 dwell × 攻击力给「干员 × 格子 × 朝向」打分，dwell 为零的落位直接丢弃；
  把「460 干员 × 数百格 × 4 朝向」压到每关几十个候选。**第二层 beam search**：
  状态 = 有序部署列表（顺序即落地顺序，因此也决定费用曲线），逐层追加、
  用验证器评估、按 `rank()` 留前 beam 个。部署时机「钱够了就下」，
  技能自动开启；两者都可被 Plan 覆盖。
- CLI：`python -m ak_tactic search <关卡> --box 名册.json [--team "…"]
  [--max-ops 4] [--beam 5] [--per-op 6] [--save-plan out/p.json]`
- 不给 `--team` 时走**组队建议层**（见下条），不再取"名册前 N 名"。
- **实测**：1-7 上 30 秒 / 98 次评估，自己找出一套 **2 人三星方案**
  （拉普兰德(2,3)朝左 + 能天使(3,5)朝上 → 137.1s / 41 杀 / 0 漏），
  比手写的三人基线少一个人。搜索结果存下的打法**自带练度**，不带名册也能复跑。
- 自检 `tools/check_search.py`（71 项）。

**组队建议**（2026-09-16）：

- `ak_tactic/team.py` —— 按**角色**挑人，不是按练度。原先 `search` 不给
  `--team` 就取"名册前 N 名"，而名册里练度最高的五个很可能全是输出：
  开局没人回费、也没人替脆皮挨那一下。
- CLI：`python -m ak_tactic team --box 名册.json [--size 8] [--stage 关卡] [--json]`
- 两个角色位，判据都只用本地数据：

  | 位 | 判据 | 为什么不能只看表面 |
  |---|---|---|
  | 回费先锋 | `tag_list` 含「费用回复」，**执旗手优先** | 「先锋基本都有回费」是统计不是定义（46 名里 43 名，例外 CONFESS-47／夜刀／预备干员-近战） |
  | 骗伤 | 子职业**处决者** 且 `respawn_time ≤ 30s`，按实际费用升序 | 光看「快速复活」标签会收进行商/情报官/傀儡师共 28 名；而 THRM-EX 也是处决者、**只要 3 费**，再部署却是 **200s**——它是反骗伤的，只按费用排会把它排第一 |
  | 低费位（**要 `--stage`**） | 初始费用 < 12 时启用；从名册全部 3★/4★ 里按练度降序取第一个比"练度最高的补齐候选"**早落地 ≥ 4 秒**的人 | 低费用环境里便宜就是先手：初始 10 费、每秒回 1 费时，9 费的 3★ 香草**当场落地**，21 费的 6★ 赤刃明霄陈要等 11 秒、24 费的圣聆初雪要等 14 秒。只按练度排会选出 32 费的远山，所以那道费用门是必需的 |

**低费位的口径**（2026-09-16 博士裁定）：

- 落地延迟 `= max(0, (费用 − 初始费用) × 每点耗时)`。实测 60 关的 `initialCost` 分布
  是 10（41 关）/15（3）/20（6）/50（1）/0（4）/3（3）/5（1）/8（1）——**10 及以下
  才是常态**，所以阈值取 12。
- `costIncreaseTime` 是"每回 1 点费用要几秒"，59/60 关是 1.0；`act31side_mo01` 是
  **999**（给一大笔初始费用、几乎不回费），两者相抵后延迟恒为 0，判为宽裕。
- **不按子职业去重**（博士明确）：判据是"适不适合这一关"，不是"职业有没有撞"。
  多一个同子职业的人未必多余，而为了避开重复去挑更贵或更弱的人，反而把这一位
  的意义（便宜、早落地）丢掉了。曾加过一道子职业去重、把豆苗换成了调香师，已撤。
- 低星池**不设练度门槛**：全部 3★/4★ 都进池，按练度降序、同练度按费用升序。

- 余位按练度补齐——这一层不改变"谁强"，只在上面**加几个位置**。
- **特殊模式专属的干员整批剔除**（`operator.is_not_obtainable`，29 条）：不只是
  「预备干员」（13 条），还包括集成战略／危机合约专属的 Misery、Sharp、Stormeye、
  Pith、Touch、Mechanist、Raidian、郁金香、暮落等——它们**正常关卡用不了**。
  只按名字剔「预备干员」会漏：**Misery 也是处决者、6 星、7 费、再部署 18s**，
  光看角色判据它是个完美的骗伤位。回费位、骗伤位、练度补齐位都要过这道门。
- 三个口径坑：费用随精英段变（砾 精0 是 6 费、精1 是 **8 费**，读基础档会把人算便宜 2 费）；`operator_attr` 里 `kind='trust'` 的行 cost 是 0，不过滤会把所有人算成 0 费；干员天赋写的「自身部署费用-1」**未计入** `operator_attr.cost`，同天赋条件下排序才可信。

**一处必须知道的口径**：显式时刻是**请求**。`sim.use_skill(position, time)`
排的技能技力不够就等够了再开；而**部署**的显式时刻更宽松——模拟器照办并把
费用夹到 0，也就是「付不起也落地」。验证器现在会**如实报出来**（归因里写
「这一手在游戏里做不出来」），但不改行为，否则三条基线全废。详见 §七 第 16 条。

### 阶段 6 · 输出 ✅ 完成

- ✅ 可分享的战报文本：`Verdict.report()` 已是能直接贴给人的成品
  （星级 / 耗时 / 击杀 / 漏怪明细 / 逐人表现 / 归因），`--json` 另有结构化输出
- ✅ MAA copilot 作业导出：`tools/export_srx8.py`（`out/srx8-a.json`）
- ✅ 地图摆位图：`ak_tactic/diagram.py` 的 `placement_diagram()` —— 干员编号
  落在自己那格，方向/时机/技能写进图例，可叠「有敌人经过的可部署格」，另附
  逐人攻击覆盖格数。**坐标即 MAA 口径，从上往下读就是地图的上下**
- ✅ 时间轴表格：`timeline_table()` —— 出怪 / 落地 / 开技能 / 阵亡 / 漏怪 /
  结束按时刻排成一张表，并列出敌人**预估到终点**的时刻（由 ETA 算出，
  与模拟器同源、误差 ≤1 帧）。这一列是摆位判断的依据：它告诉你敌人几点
  会压到防线。带脚注说明它是「无人拦截」前提下的理论值
- ✅ 路线热度图：`route_heat()` —— 每格的敌人·秒（`dwell`）或经过的路线条数
  （`routes`）。**摆位先看这张图**
- ✅ 一键完整报告：`verify --report out/report.md`（摆位 + 热度 + 时间轴 + 战报）
- 自检 `tools/check_diagram.py`（49 项）

---

## 二、现在能做什么

```bash
cd <仓库目录>

# ── 干员（prts.wiki）
python -m ak_tactic get 能天使                          # 人读格式
python -m ak_tactic get 能天使 --range                  # 连攻击范围网格一起画
python -m ak_tactic get 能天使 --full                   # 展开全部 10 个技能等级
python -m ak_tactic get 能天使 --json                   # 结构化 JSON
python -m ak_tactic list                                 # 名录
python -m ak_tactic list --profession 狙击 --rarity 6
python -m ak_tactic range 3-3 1-1 2-1                    # 单看某个范围代号

# ── 干员属性计算（gamedata excel/ 表，默认走 GitHub 镜像）
python -m ak_tactic stats 阿米娅 --elite 2 --level 80     # 精英2 满级
python -m ak_tactic stats 阿米娅 --elite 2 --level 80 --trust 100 --potential 6
python -m ak_tactic stats 阿米娅 --elite 1 --level 35     # 中间等级也能算
python -m ak_tactic stats 银灰 --modules                  # 看它有哪些模组
python -m ak_tactic stats 银灰 --elite 2 --level 90 \
        --module uniequip_002_svrash --module-level 3     # 带模组
python -m ak_tactic stats --search 银灰                   # 按中文名找干员
python -m ak_tactic stats 阿米娅 --elite 0 --level 3 --rounding round   # 换取整方式

# ── 关卡与敌人（gamedata，默认走 map.ark-nights.com）
python -m ak_tactic stage --search SR-EX                # 按关卡号找（索引 4694 条）
python -m ak_tactic stage 1-7                           # 关卡号与 levelId 都收
python -m ak_tactic stage SR-EX-8                       # 活动关一样能取
python -m ak_tactic stage SR-EX-8 --map                 # 只看地图，不加载敌人库（快）
python -m ak_tactic stage SR-EX-8 --timeline            # 打印全部出怪时刻
python -m ak_tactic stage SR-EX-8 --json                # 全量 JSON
python -m ak_tactic enemy enemy_1030_wteeth             # 单看一个敌人
python -m ak_tactic enemy --search 源石虫                # 按中文名搜

# ── 本地库：干员与敌人**两个独立文件**
python -m ak_tactic db build                             # 干员库（gamedata，不联网，~3.4s）
python -m ak_tactic db info                              # 版本戳 + 各表行数
python -m ak_tactic db char 望                            # 干员详情（同名时用 id）
python -m ak_tactic db skill 取势 --key sluggish          # 按技能名 + 黑板键搜
python -m ak_tactic db talent 铸子                        # 按天赋名或描述搜
python -m ak_tactic db sql "SELECT name FROM operator WHERE is_operator=1 LIMIT 5"
python -m ak_tactic db tiles                              # 地块字典（95 条：tileKey → 中文名 + 说明）
python -m ak_tactic db tiles 田                            # 按关键词/键名搜地块
python -m ak_tactic db tile-fetch --force                 # 重取地块字典（缓存 7 天）
python -m ak_tactic enemydb build                        # 敌人库（prts.wiki，首次 ~51s）
python -m ak_tactic enemydb find 死志                     # 找敌人
python -m ak_tactic enemydb find --grade 领袖              # 只列领袖
python -m ak_tactic enemydb show 源石虫                   # 图鉴 + 逐档 + 抗性 + 技能
python -m ak_tactic enemydb show 挥铳圣像 --json           # 原样 JSON
python -m ak_tactic enemydb sql "SELECT page,grade FROM enemy WHERE grade='领袖'"

# ── 验证一份打法（阶段 5 的验证器）
python -m ak_tactic verify --plan p.json --box 名册.json   # 关卡号在文件里
python -m ak_tactic verify act54side_06 \
    --team "圣聆初雪:5,4:Right:2:3; 德克萨斯:6,3:Right:1" --box 名册.json
python -m ak_tactic verify main_01-07 --team "阿米娅:5,2:Left:0@1" --json
#   --team 语法：名字:x,y[:朝向[:技能槽[:专精]]]@时刻，干员之间用 `;`
#   不给 @时刻 就是「钱够了就下」（与 MAA 自动作战同规则）
#   退出码：0 = 三星，1 = 通关但不满星或失败，2 = 打法本身有问题

# ── 搜索一套能三星的阵容（阶段 5 的搜索器）
python -m ak_tactic search main_01-07 --box 名册.json --team "能天使;银灰"
python -m ak_tactic search act54side_06 --box 名册.json --top 10 \
        --max-ops 4 --beam 6 --per-op 8 --save-plan out/p.json
#   不指定 --team 就取名册前 --top 名；--beam/--per-op 是预算旋钮
#   存下来的打法自带练度，之后 verify --plan 不带 --box 也能复跑

# ── 输出：摆位图 / 时间轴 / 完整报告（阶段 6）
python -m ak_tactic verify main_01-07 --team "阿米娅:5,2:Left:0@1" --box 名册.json \
        --diagram --timeline
python -m ak_tactic verify --plan out/p.json --report out/report.md
#   --heat-metric routes 把热度图从「敌人·秒」换成「经过的路线条数」

# ── 自检（十套，共 793 项；全绿才算没退化）
python tools/check_db.py              # 64  干员库（含地块字典）
python tools/check_enemy_db.py        # 62  敌人库
python tools/check_battle.py          #117  战斗模型 + 三关基线 + 攻速链路 + 口径断言
python tools/check_p3r.py             # 65  相性与全场总攻击
python tools/check_formula.py         #100  干员正文 → 公式项（含算式解析器）
python tools/check_enemy_formula.py   #162  敌人正文 → 公式项（含带变量的算式）
python tools/check_verify.py          # 68  验证器（含跨局复用可重复性）
python tools/check_eta.py             # 35  到达时刻（与模拟器逐只对拍）
python tools/check_search.py          # 71  搜索器 + 组队建议
python tools/check_diagram.py         # 49  摆位图 / 热度图 / 时间轴 / 报告
python tools/enemy_field_audit.py     #     敌人字段总账（非 0 退出即有字段没入库）

# ── 缓存
python -m ak_tactic cache                                # 看两个缓存目录的占用
python -m ak_tactic cache --clear                        # 清 prts 缓存
python -m ak_tactic cache --clear-gamedata               # 清 gamedata 缓存（约 17 MB）
```

### 两个本地库为什么分成两个文件

| | 干员库 | 敌人库 |
|---|---|---|
| 文件 | `data/akdb.sqlite` | `data/enemydb.sqlite` |
| 来源 | 游戏本体 gamedata 的 `excel/` | prts.wiki 的「分类:敌人」 |
| 主键 | `char_id` | prts.wiki 页名（`“死志的凝结”`） |
| 数值口径 | 只存**关键帧原文**，面板另算 | 存**算好继承的逐档数值** |
| 建库 | `db build`（不联网） | `enemydb build`（要联网，有 7 天缓存） |
| 自检 | `tools/check_db.py`（64 项） | `tools/check_enemy_db.py`（62 项） |

两者**不共用文件、不共用结构版本、不互相引用**。最要紧的理由不是"来源不同"，
而是**数值口径正好相反**：干员那边只搬原文、插值与潜能留在计算层（两处各算
一遍迟早对不上）；敌人这边没得选——prts.wiki 页面里没有"显式 / 继承"的标志位，
只有"写了 / 没写"，所以继承只能在建库时算好。

### 地块字典（`tile` 表）——本库唯一的非 gamedata 表

`akdb.sqlite` 里有一张 `tile`（95 条），**不是**来自 gamedata：`excel/tile_table.json`
与 `excel/tile_data.json` 在两个镜像上都 404，游戏本体确实没有地块表。改从
**theresa.wiki** 的地图数据接口取（`/_next/data/<buildId>/map/<zoneId>/<stageId>.json`
的 `pageProps.tileInfo`），缓存 7 天，取不到只记一条警告、`tile` 表留空。

它解决的是**只能靠 `tileKey` 名字猜**的那批地块：

| tileKey | 中文名 | 备注 |
|---|---|---|
| `tile_road` / `tile_wall` | 平地 / 高台 | 可部署地面 / 可部署高台 |
| `tile_floor` | **不可放置位** | 与 `tile_forbidden`「禁入区」不是一回事 |
| `tile_infection` | **活性源石** | 增益地块，**不是被污染的田地** |
| `tile_empty` | 空 | 说明里写着「游戏本体未包含该内容」，只在生息演算三关出现 |
| `tile_hole` / `tile_telin` / `tile_telout` | 地穴 / 通道入口 / 通道出口 | 行为不在字段里，必须按 key 判 |

实测三条：① 这张表是**全局**的（`act31side_08` 与 `act54side_ex08` 取回来逐字节相同）；
② 它**不全**——`sandbox1_02` 用到的 `tile_xbdpsea` 不在 95 条里，已记进
`ak_tactic/db/tiles.py` 的 `KNOWN_GAPS`，自检判的是"缺口只有记录在案的"而不是"一个都不缺"；
③ 怀黍离的**田地在字典里查不到**——「田」在 95 条里 0 命中，所以田地判定没有数据可依，
只能回到地形（低地且非特殊地形）。曾据坐标巧合把 `tile_infection` 误判成田地，已纠错并加守卫。

详见 `docs/operator-db.md` 与 `docs/enemy-db.md`。

> ⚠️ `python -m ak_tactic enemy <名字>` 与 `enemydb show` 是两码事：前者**实时**从
> gamedata 取一个敌人的图鉴与数值（不碰本地库），后者查的是可 SQL 的全量库。

作为库用：

```python
from ak_tactic.prts import fetch_operator, RangeRegistry
from ak_tactic.gamedata import load_stage, EnemyLibrary

op = fetch_operator("银灰")
print(op.rarity, op.profession, op.branch)
print(op.stat_at(2, 90))                      # 精英2 满级面板
print(op.skills[2].level(10).description)     # 三技能专精三

rng = RangeRegistry().for_operator(op)["elite2"]
print(rng.draw())          # ★ 是自身，● 是攻击覆盖
print(rng.covers(2, 0))    # 正前方第 2 格在不在范围内

stage = load_stage("main_01-07")
print(stage.map.render())              # 地图
print(stage.map.melee_spots)           # 全部可部署近战位
print(stage.enemy_counts())            # {'enemy_1007_slime_2': 23, ...}
for t, s in stage.timeline()[:5]:      # 出怪时间轴
    print(f"{t:6.1f}s {s.enemy_id} route[{s.route_index}]")

# 活动关：关卡号会被索引换算成 levelId
src = GameDataSource()
print(src.resolve_level("SR-EX-8"))    # LevelEntry(level_id='act54side_ex08', ...)
sr = load_stage("SR-EX-8", source=src)
print(sr.map.find("tile_telin"))       # 传送入口在哪几格
print(sr.used_routes()[1].waits)       # 这条路上有没有等待节点

lib = EnemyLibrary()
print(lib.get("enemy_1030_wteeth").max_hp)   # 5000
print(lib.name("enemy_1029_shdsbr"))         # 机动盾兵
```

自检（抽样跑全库，核对字段完整度）：

```bash
python tools/selftest.py -n 30 --with-range
python tools/selftest.py --all          # 全库 461 个，约 25 分钟（被限速卡着）
```

---

## 三、代码结构

```
ak-tactic/
├─ ak_tactic/
│  ├─ cli.py                 命令行入口（get/list/stats/…/db/enemydb/verify）
│  ├─ prts/                  prts.wiki 接入层（干员的文字资料、敌人页面）
│  │  ├─ client.py           API 客户端：限速、重试、磁盘缓存、批量 titles
│  │  ├─ wikitext.py         模板扫描 / 参数切分 / 内联标记还原
│  │  ├─ operator.py         干员页 → Operator 对象
│  │  ├─ enemy.py            敌人页 → 逐档数值 / 抗性 / 技能（含继承合并）
│  │  ├─ grid.py             攻击范围 SVG → 网格
│  │  └─ ranges.py           攻击范围代号的取数与本地索引
│  ├─ gamedata/              游戏本体数据接入层（机器要算的数值）
│  │  ├─ source.py           取数：远端 raw + 磁盘缓存 + 大文件内存释放
│  │  ├─ stage.py            关卡 JSON → 地图 / 路线 / 时间轴（坐标 = MAA 口径）
│  │  └─ enemy.py            敌人图鉴 + 属性库 → EnemyStats
│  ├─ operator/              干员属性计算
│  │  ├─ stats.py            等级插值 + 信赖 + 潜能 + 模组 → 面板数值
│  │  ├─ skill.py            技能 / 天赋 / 模组 → 战斗效果
│  │  ├─ attack_speed.py     总攻速 = 基础 100 + 天赋 + 模组特性改写（含条件性）
│  │  └─ talent.py           天赋按练度取值（潜能门槛）
│  ├─ formula.py             正文 → 公式项（解析器 + 干员规则表）
│  ├─ enemy_formula.py       正文 → 公式项（敌人规则表 + wiki 模板清洗）
│  ├─ db/                    两个本地库（建库 + 查询，共用 store.py）
│  │  ├─ store.py            连接与公共工具（默认只读连接）
│  │  ├─ schema.py           干员库表结构（含 DB_VERSION）
│  │  ├─ build.py            干员库建库（gamedata 的 excel/ 六张表，不联网）
│  │  ├─ api.py              干员库查询
│  │  ├─ tiles.py            地块字典（theresa.wiki；本库唯一的非 gamedata 表）
│  │  ├─ enemy_schema.py     敌人库表结构（与干员库各自独立）
│  │  ├─ enemy_build.py      敌人库建库（prts.wiki，含逐档继承合并）
│  │  └─ enemy_api.py        敌人库查询
│  ├─ plan.py            ★  关卡无关的「打法」：阵容/落位/朝向/时机 + JSON
│  ├─ eta.py             ★  敌人到达时刻：速度+路线 → 几点到哪一格（解析式）
│  ├─ verify.py          ★  通用验证器：打法 → 三星判定 + 归因
│  ├─ search.py          ★  搜索器：几何剪枝 → beam search（落位/朝向/顺序）
│  ├─ team.py            ★  组队建议：按角色位挑人（回费先锋 / 骗伤 / 低费位）
│  ├─ diagram.py         ★  输出：摆位图 / 路线热度图 / 时间轴表格 / 完整报告
│  └─ battle/                战斗模型
│     ├─ damage.py           物理 / 法术 / 真实 / 治疗
│     ├─ unit.py             干员与敌人在战斗中的可变态
│     ├─ range.py            攻击范围 → 实际覆盖格（朝向旋转）
│     ├─ talents.py          战斗内天赋（积雪、费用加成…）
│     ├─ p3r.py              相性（P3R）与「全场总攻击」装置
│     └─ sim.py              模拟器本体（帧级推进，~67 KB）
├─ tools/
│  ├─ check_*.py             十套自检：db / enemy_db / battle / p3r / formula
│  │                         / enemy_formula / verify / eta / search / diagram
│  ├─ squad.py               森空岛名册 → 战斗单位（保真度基准）
│  ├─ roster.py / skland.py  森空岛登录与名册拉取
│  ├─ run_sr6.py              SR-6 关卡专属跑法（含落位合法性守卫）
│  ├─ run_srx8.py / export_srx8.py / search_srx8.py   SR-EX-8 跑法/导出/搜索
│  ├─ unit_audit.py          量纲裁定表生成（裁定栏可回填、再生不丢）
│  ├─ uncertainty_audit.py   待裁定清单生成 → docs/uncertainties.md（同上机制）
│  └─ enemy_field_audit.py   敌人字段总账（非 0 退出即有字段没入库）
├─ docs/                     各阶段实测报告（关卡、敌人、公式、库结构）
└─ data/
   ├─ cache/prts/            prts.wiki HTTP 响应缓存（7 天）
   ├─ ranges.json            攻击范围索引
   ├─ gamedata/              gamedata 原始文件缓存（约 17 MB，可随时删）
   ├─ akdb.sqlite            干员库（纯派生物，db build 约 3.4s 重建）
   └─ enemydb.sqlite         敌人库（纯派生物，enemydb build 冷启约 53s）
```

分层只有两个原则：**把上游的脏活关在 `client.py` / `source.py` 里**——403、SSL 抖动、限速、翻页、15 MB JSON 的内存膨胀，上层一概看不见；**坐标在入口处一次定型**——全项目内部一律 MAA 口径（原点左上、y 向下），再往下的每一层都不许再翻。

---

## 四、prts.wiki 数据源实测结论

这些是踩出来的，记下来免得下次再踩。

### 取数入口

| 入口 | 可用性 | 说明 |
| --- | --- | --- |
| `action=raw`（`?action=raw`） | ❌ | 这个 wiki 上不返回 wikitext，会给出 API 帮助页 HTML |
| `action=query&prop=revisions&rvslots=main` | ✅ | **唯一可靠的 wikitext 入口** |
| `action=parse&prop=wikitext` | ✅ | 也可用，但参数里带中文时容易被 WAF 误伤 |
| `action=cargoquery` | ✅ | 结构化查询，**只有两张表** |
| `action=ask`（SMW） | ✅ | 语义查询，属性覆盖不全 |
| `Special:Cargo表` | ❌ | 特殊页拿不到 raw，抓 HTML 会 SSL EOF |

### 硬性约束

- **必须带浏览器 User-Agent**。裸 `urllib` 一律 403（Tengine 拦的）。
- **请求间隔 ≥ 1.2 秒**，并发会吃 403。`PrtsClient` 里做了进程级串行限速，并把 403 纳入重试。
- 中文查询参数偶发 403，重试通常能过。

### Cargo：只有两张表（逐个探测确认）

```
chara_data   461 行   ← 干员数值快照
chara        460 行
（chara_talent / chara_skill / stage_data / enemy_data / item_data … 均不存在）
```

`chara_data` 字段：`hp, atk, def, res, cost, block, atkSpeed, reDeploy, potential, trust, ingameFaction`
—— 但**只有满级一档**，且没有职业、稀有度、技能、天赋、攻击范围。
所以 Cargo 只能当名录和交叉校验用，完整数据必须解析 wikitext。

> Cargo API 有个坑：字段别名不能以 `_` 开头。`_pageName` 必须写成 `_pageName=Page`。

### SMW：可用但覆盖有限

挂在干员页上的属性只有：`干员id`、`稀有度`、`职业`、`部署费用`、`阻挡数`、`攻击速度`、`精英0/1/2范围`、`干员序号`。
分级数值（`精英2_满级_攻击` 之类）**不在 SMW 上**，是纯模板参数。

`稀有度` 是 **0 起算**的（0 = 一星，5 = 六星），代码里已统一换算成真实星级。

### 攻击范围图的语义

`精英0范围=3-1` 只是代号，真图在 `Widget:Range/3-1`，是一张 SVG。里面只有两种格子：

- `#1` 蓝色实心 → **干员站位格**（图中恰好一个）
- `#2` 灰色描边 → **攻击覆盖格**

已用近卫三个基准校准过：`1-1` 前方 1 格、`1-2` 前方 1 格带上下、`1-3` 前方 2 格带上下，与游戏内一致。
坐标步长 26px，描边格有 1px 补偿会造成锚点抖动，用「除以步长四舍五入」吸附到格子。

### 页面结构

干员页是模板拼的，一一对应：

```
{{CharinfoV2}}      基础信息（模板名和首个竖线之间夹着注释，取名字前必须先剥注释）
{{干员获得方式}}     获取途径、上线时间
{{属性}}            四维、部署参数、信赖、潜能、模组增量（内含 #cargo_store 与 #set）
{{干员攻击范围}}     三个阶段的代号
{{天赋列表3}} × N    每个天赋
{{技能}} / {{技能2}}  每个技能（技能所属在模板前一行粗体里，如 '''技能1（精英0开放）'''）
{{潜能提升}}
{{模组}} × N
{{后勤技能}}
```

内联模板还原只靠一条规则：**取最后一个位置参数**。

`{{color|#0098DC|3}}` → `3`；`{{*|6%|+6%}}` → `+6%`；`{{变动数值lite|up|蓝|两名}}` → `两名`。一条规则通吃所有展示类模板。

---

## 五、gamedata 数据源实测结论

关卡的地图网格、出怪路线、敌人的数值，**prts.wiki 上都没有**——它是个文字 Wiki，
关卡页面写的是攻略心得，不是可解析的地图。这些东西只存在于游戏解包里。

### 两个镜像，默认走 ark-nights

| 镜像 | 地址 | 说明 |
| --- | --- | --- |
| **map.ark-nights.com**（第一选择） | `https://map.ark-nights.com/data/...` | PRTS.Map 的部署，与 gamedata 同构但更精简（敌人库 6.4 MB vs 14.9 MB），**且附带关卡索引**。源码在 [Houdou/prts-map](https://github.com/Houdou/prts-map) |
| Kengxxiao/ArknightsGameData（备选） | raw.githubusercontent.com/…/zh_CN/gamedata | 站长声明的直链，多一张 `excel/enemy_handbook_table.json`（敌人图鉴） |

换源只要一个参数：

```python
GameDataSource()                     # 默认 ark-nights
GameDataSource(base=GITHUB_BASE)     # 换回 GitHub
```

两个镜像的缓存按**域名分目录**存放——它们的文件路径完全同名，按路径缓存会
互相顶替。

> theresa.wiki 的地图功能读的也是这一套（它的 `.env.example` 里写的就是上面
> 那条 GitHub 直链）。但站点自己的 `s3.theresa.wiki` 目前 **DNS 解析不了**，
> `static.theresa.wiki/gamedata/...` 一律 404，所以没有走它。

### 关卡索引——ark-nights 最值钱的东西

它把一份 **4694 条**的关卡索引直接编译进了 JS bundle：

```json
"act54side_ex08": {"difficulty": "NORMAL", "zone_id": "act54side_zone2",
                   "data_path": "activities/act54side/level_act54side_ex08.json",
                   "code": "SR-EX-8"}
```

有了它，才能把玩家嘴里的「SR-EX-8」换算成 `act54side_ex08`。

**这件事没有别的办法**：活动关的 `levelId` 与显示名之间毫无可推导的关系——
`SR` 这个前缀只存在于活动表里，而 `excel/` 目录两个镜像都没有。主线还能靠
`main_01-07 → 1-7` 猜，活动关一概猜不出来。

索引没有独立的 JSON 端点，只能从 bundle 里扒：拉首页拿到 bundle 文件名
（带 hash，会变）→ 拉 bundle → 把里面那份 `JSON.parse('...')` 里最长的字典抠出来。
首次约 7 MB，之后走本地缓存（7 天 TTL）。

```bash
python -m ak_tactic stage --search SR-EX      # 直接按关卡号找
python -m ak_tactic stage SR-EX-8             # 关卡号或 levelId 都收
```

### 用到的文件

| 文件 | 大小 | 内容 |
| --- | --- | --- |
| `levels/<data_path>` | 47–90 KB | 一份关卡：地图、路线、波次、关卡参数 |
| `levels/enemydata/enemy_database.json` | 6.4 / 14.9 MB | 2151 个敌人的分档数值 |
| `excel/enemy_handbook_table.json` | 1.8 MB | 敌人名字、编号、描述（**仅 GitHub 镜像有**） |

关卡的 `data_path` 由索引给出，形如 `obt/main/level_main_01-07.json`（主线）或
`activities/act54side/level_act54side_ex08.json`（活动）。

### 坑一：两套 y 口径，只有一套在项目里

`mapData.map` 是一个 `行 × 列` 的索引表，指进 `mapData.tiles`。字段本身没有坐标，
**行序才是坐标**，而两块数据的行序是相反的：

- **`mapData.map` 的第 0 行就是最上面那一行**，而 `mapData.tiles` 那段扁平数组
  是自下而上排的。1-7 的索引表能把这件事看死：`row=0` 指向的是 `66…76`，
  `row=6` 指向的是 `0…10`，恰好 `idx(y,x) = (H-1-y)*W + x`。
- **`routes[].row`（起点、途经点、终点）却是游戏内部口径，自下而上。**

2026-09-16 起本项目**内部一律用 MAA 标准**（原点左上、y 向下），于是：

1. 地图直接 `grid[y][x] = mapData.map[y][x]`，**不再翻转**；
2. 路线解析时翻一次 `y = H - 1 - row`。

第 2 条有硬判据：SR-EX-8 的 38 条路线 `APPEAR_AT_POS` 全在 `row=3`，地图高 9，
翻过来是 `y=5`——正好落在 `tile_telout` 上；不翻会落在普通地板上。

> ⚠️ 因为 1-7 **上下对称**，这两条翻错任何一条肉眼都看不出来。判断口诀：
> **地图不翻、路线翻**。踩坑记录见 `docs/stage-sr-6.md` 第二节。

### 坑二：字段是 Unity 序列化的包装形状

`enemy_database.json` 的每一项是 `{"Key": ..., "Value": [...]}`（**大写开头**，
不是 `key`/`value`），而 `Value` 里的每个字段又包一层：

```json
"maxHp": {"m_defined": true, "m_value": 1050}
```

`m_defined: false` 表示这一档没覆写该字段，要沿用更低优先级的值。多个档位之间
就是这样从低到高合并的——theresa.wiki 前端做的也是这件事，本项目在
`EnemyLibrary._ensure_stats` 里复刻了同一套合并。

### 坑三：有几个字段不在 `attributes` 里

`lifePointReduce`（漏怪扣几点生命）、`rangeRadius`、`levelType` 挂在
`enemyData` **顶层**，不在 `attributes` 下面。按属性去 `attributes` 里找，
会永远取到 `None` 而不报错——这种错最安静。已单列 `_TOP_FIELDS`。

### 坑四：同一个敌人，两张表两个名字

`enemy_1029_shdsbr`（1-7 里那只防御 250 的盾）在 `enemy_handbook_table.json`
里叫**机动盾兵**，在 `enemy_database.json` 里却叫**持盾刀兵**。

查证结果：prts.wiki 上「持盾刀兵」是一个 `#redirect [[机动盾兵]]` 的空页面，
而 prts.wiki 记载的机动盾兵攻 240 / 防 250 与本数据分毫不差 —— 所以
**图鉴表的是新名，战斗数据里留着旧名**。

代码以图鉴名为准，旧名落到 `EnemyStats.alias`，不丢。

### 坑五：fragment 是串行的，且有各自的 preDelay

一份关卡的波次长这样：`waves[].fragments[].actions[]`。

- 每个 **action** 有自己的 `preDelay`（相对 fragment 开始）
- 每个 **fragment** 也有自己的 `preDelay`（相对前一个 fragment **结束**之后）
- 所以时间轴要**串行累加**，不能把 fragment 的 preDelay 都当成相对 wave 开始
  ——那样算出来第 2 段会比第 1 段还早开始

`blockFragment` 为 true 时要额外等那批敌人离场（清怪快慢会影响后续波次）；
1-7 全部是 false，所以算出来是精确的。代码在 `EnemySpawn.block_fragment`
上留了这个标记。

### 坑六：途经点有四种，其中两种的坐标是假的

`Route.checkpoints` 每个节点都带 `type`。1-7 那种简单图**全是 `MOVE`**，
所以看不出任何问题；SR-EX-8 把四种都凑齐了：

| 类型 | SR-EX-8 中出现次数 | position 有效？ |
| --- | ---: | --- |
| `MOVE` | 116 | ✅ 真的 |
| `WAIT_FOR_SECONDS` | 75 | ❌ 一律 `(0,0)` 占位 |
| `DISAPPEAR` | 38 | ❌ 一律 `(0,0)` 占位 |
| `APPEAR_AT_POS` | 38 | ✅ **真的**，是传送落点 |

```json
{"type": "WAIT_FOR_SECONDS", "time": 60,
 "position": {"row": 0, "col": 0}}          ← 占位，不是坐标
{"type": "APPEAR_AT_POS", "time": 0,
 "position": {"row": 3, "col": 6}}          ← 真的，敌人在这格出现
```

两个方向都会踩坑：

- 把 `WAIT_FOR_SECONDS` / `DISAPPEAR` 的 `(0,0)` 当坐标读，地图上会凭空多出
  一条穿过左下角、终点还落在地图外的假路径。
- 反过来把 `APPEAR_AT_POS` 也当成无坐标节点丢掉，就看不见传送落点——
  SR-EX-8 的 38 条路线全都落在中央 `(6,5)`（MAA 口径，见坑一），丢了这个就
  完全读不出「所有敌人都汇聚到中央」这个结构。

代码在 `Route.path` 里只收有真坐标的节点，等待秒数记在 `Route.waits` /
`Route.total_wait`，传送落点另开 `Route.teleports`，
`Route.timeline_hint()` 则把整条路线展开成人话：

```python
>>> stage.route(1).timeline_hint()
'等待60s → (0, 2) → 消失 → 等待1s → 传送至(6, 5) → (6, 7)'
```

顺便记一个容易读反的地方：那 60 秒是**入场后就地待命**，不是「走到传送口
再等」——所以敌人的「入场时刻」和「抵达中央防线时刻」之间隔着一分钟。

### 敌人等级怎么取

关卡用 `enemyDbRefs` 声明它引用了哪些敌人、各用哪一档：

```json
{"useDb": true, "id": "enemy_1007_slime_2", "level": 0, "overwrittenData": null}
```

1-7 引用了 6 个敌人，全是 `level 0`。`EnemySpawn.level` 已经带上这个档位，
`EnemyLibrary.get(id, level)` 按它取值。

---

## 六、干员属性计算

### 为什么必须自己算

游戏不为每个等级存一份属性，只存**关键帧**：

```json
"phases": [
  {"maxLevel": 50, "attributesKeyFrames": [
      {"level": 1,  "data": {"maxHp": 699, "atk": 276, ...}},
      {"level": 50, "data": {"maxHp": 958, "atk": 390, ...}}]}
]
```

中间的 48 个等级要靠插值。所以：

```
属性 = 等级插值(基础) + 信赖加成 + 潜能加成 + 模组加成
```

### 数据源

| 表 | 大小 | 用途 |
| --- | --- | --- |
| `excel/character_table.json` | 15 MB | 干员本体：属性关键帧、信赖帧、潜能 |
| `excel/uniequip_table.json` | 3.4 MB | 模组元数据：谁有哪个模组、叫什么 |
| `excel/battle_equip_table.json` | 5.7 MB | 模组的战斗数值：每级的属性加成 |

**这三张表只有 GitHub 镜像有。** `map.ark-nights.com`（关卡数据的首选源）
**不带 `excel/` 目录**，请求一律 404。所以属性计算固定走
`GameDataSource(base=GITHUB_BASE)`，与关卡数据的源分开——这也是本项目里
唯一一处不用首选源的地方。

三张表都是 5 MB 以上，解析后立刻只留下需要的字段并 `release()` 原始对象，
否则内存会膨胀到上百 MB。

### 四个必须记清的点

1. **阶段内等级从 1 重新开始**。精英 1 的关键帧是 `level 1 → 70`，不是 `51 → 70`；
   而「精英 1 1 级」的属性恰好等于「精英 0 50 级」。参数 `level` 一律是**阶段内**等级。
2. **关键帧不一定是两个**。2261 个阶段是 2 帧，但还有 29 个是 3 帧、11 个是 6 帧、
   2 个是 11 帧（都是 `trap_*` 装置，如 `trap_404_xbfortress` 30 级 4 帧）。
   插值按相邻帧通用处理，不硬编码两帧。
3. **模组的 `attributeBlackboard` 是该等级的总加成，不是增量**。
   `uniequip_002_amiya` 三级分别是 `{max_hp:100, atk:30}` / `{max_hp:130, atk:40}` /
   `{max_hp:150, atk:50}`——取对应那一份即可，别再累加。
4. **信赖的 level 是 0–50，对应游戏内**显示**信赖 0%–200%**（每 level 4 点），
   所以 `level = trust / 2`。参数 `trust` 是 **0–100 内部标度**（= 显示信赖 ÷ 2），
   `trust=100` 即满信赖 200%；`tools/roster.py` 的森空岛 `favorPercent/2` 是同一条换算。

顺带一提，`character_table` 里的稀有度是 `"TIER_5"` 这种字符串，
而 prts.wiki 的 SMW 那条路给的是 0 起算的整数（0=一星）。两套别混。

### 模组：只有专属模组带属性

`equipDict` 有 905 条，但 `type` 只有两种：

- `INITIAL` ×396 —— 基础证章（如「阿米娅证章」），**纯文字，无属性加成**
- `ADVANCED` ×509 —— 专属模组，**有属性加成**

而 `battle_equip_table` 恰好 509 条，与 `ADVANCED` **一一对应**。
所以「这个模组有没有属性」等价于「它在不在 `battle_equip_table` 里」，
`OperatorCalculator.modules()` 直接给出 `has_stats` 标记。

阿米娅的升变形态（近卫 / 医疗）是不同的 `charId`（`char_002_amiya2` / `amiya3`），
所以 `charEquip` 里 `char_002_amiya` 只列自己的两个模组，不会串。

### 加成怎么叠加（阿米娅 · 精英 2 · 80 级 · 满配）

| 属性 | 基础 | 信赖100% | 潜能6 | 模组Lv3 | 合计 |
| --- | --- | --- | --- | --- | --- |
| 生命上限 | 1480 | +200 | +200 | +150 | **2030** |
| 攻击 | 612 | +70 | +30 | +50 | **762** |
| 部署费用 | 20 | · | −2 | · | **18** |

### 验证

六个端点值与 prts.wiki 的 `{{属性}}` 模板逐项核对，**全部一致**：

| 阶段 | 等级 | 生命 | 攻击 | 防御 | 法抗 |
| --- | --- | --- | --- | --- | --- |
| 精英 0 | 1 | 699 | 276 | 48 | 10 |
| 精英 0 | 50 | 958 | 390 | 81 | 10 |
| 精英 1 | 1 | 958 | 390 | 81 | 15 |
| 精英 1 | 70 | 1198 | 514 | 110 | 15 |
| 精英 2 | 1 | 1198 | 514 | 110 | 20 |
| 精英 2 | 80 | 1480 | 612 | 121 | 20 |

潜能也与 prts.wiki 一致：潜 2 生命 +200、潜 3 费用 −1、潜 4 攻击 +30、潜 5 费用 −1、
潜 6 天赋增强。`potentialRanks` 只有 5 项，正对应潜能 2–6。

### 取整：唯一没有被证实的假设

关键帧是精确值，但插值出来的中间值几乎都是小数，而面板显示整数。
**取整方式（向下取整还是四舍五入）没有公开资料**，三条路都试过：

- **prts.wiki** —— 属性模板只给端点值，它自己也是靠插值；`Template:` / `Module:`
  命名空间被 WAF **一律 403**（不是限速，是持续的），拿不到 Scribunto 逻辑。
- **`arknights-toolbox`（★694）** —— `Level.vue` 是**经验 / 龙门币**计算器
  （`characterExp`、LS-5、CE-6），`Math.ceil` 全用在经验书上，不碰属性插值。
  它的 `assets/data/character.json` 429 条只有拼音/星级/职业。
- **`ark-dps.com`** —— 全部 6 个 js 里搜不到任何属性数值
  （`699` / `1480` / `958` 命中均为 0），`fetch(` 只有两处且与数据无关。

所以本项目把取整做成**构造参数**，默认 `floor`（Unity 里整数属性的惯例，
也是社区通行写法），可切 `round` / `ceil` / `none`，
另有 `calibrate()` 用一条实测值直接判定：

```python
calc.calibrate("char_002_amiya", elite=0, level=3, attr="atk", observed=280)
# 阿米娅精英0 攻击跨度 259 ÷ 49 级，第 2 级是 10.571 —— floor 与 round 在这里分歧
# → {'verdict': '向下取整（floor）', ...}
```

对整数属性取整，对浮点属性（法抗/移速/攻速/攻击间隔）**不取整**，
否则 0.7 的移速会被压成 0。

**影响有多大**：阿米娅精英 0 攻击跨度 259 ÷ 49 级 = 5.2857/级，
两种取整的偏差上界是**每级 1 点**，且端点完全一致。
对「能不能打掉这只敌人」的判定基本无影响，只有在跨某道伤害阈值时才有意义。

---

## 七、已知局限

1. ~~**技能效果还是自然语言**~~ —— **已解决**（2026-09-15）。`ak_tactic/formula.py`
   把技能/天赋/特性/模组的正文编译成可结算的公式项，另加 `ak_tactic/enemy_formula.py`
   （敌人规则表 + wiki 模板清洗）。**要改这套解析器，先读 `docs/formula-maintenance.md`**
   —— 维护者手册：接口清单、加一条规则的配方、必须守住的不变量、逐条踩过的坑。
   模拟器有 `effect_source` 三档（`blackboard` / `merge` 默认 / `desc`）。
   仍未对齐的是**对手**：抬手 `prepDuration` 与敌人的攻击动作时长（gamedata
   里没有，后者是模拟器给的 0.5s 假设）。**但「攻击间隔要不要动画帧补正」
   已定案否**（2026-09-16 实机核对）：间隔 = 基础间隔 × 100 / 总攻速，
   实测误差 0.07%，帧补正只影响首刀时机、不影响出手周期。
   详见 `docs/formula-model.md`。
2. ~~**移速换算还没校准**~~ —— **已定案**（2026-09-14）：`格/秒 =
   moveSpeed × move_multiplier × speed_scale`，不要再乘任何额外系数。
   用 1-7 实机录像（怒潮凛冬精2 60 单干员、2 倍速回放，战斗区间 140s 游戏时间）
   对齐，模拟 142.0s，误差 1.4%。
3. ~~**干员范围与地图还没联动**~~ —— **已解决**。`battle/range.py` 的
   `RangeProvider` 把「干员 + 精英阶段 + 朝向 + 位置」换算成实际攻击格，
   走 gamedata 的 `excel/range_table.json`（73 个代号，纵向对称、自带自身格）。
   **注意它会影响结果**：1-7 无技能基线给真实范围是 `133.0s`，
   不给（退回到「自身格 + 朝向前方三格」的近似）是 `137.0s`——
   `tools/check_battle.py` 锚的是后者，那条防的是"新代码改坏旧路径"而非精度；
   `tools/check_verify.py` 两条都锚。用 `Verifier(use_range_table=False)` 切换。
4. **传送与等待还没并进时间轴**。SR-EX-8 的路线里有 `WAIT_FOR_SECONDS`（最长一条等 61 秒）和 `tile_telin → tile_telout` 的传送，目前只解析出来、没有并入出怪时刻，所以算不出「某只敌人几点出现在中央那个格子」。
5. **`tile_replace_wall` / `tile_replace_road` 的触发条件未验证**。SR-EX-8 的 13 个可部署格里有 12 个标着 `tile_replace_*`——它们当前可部署，但会被关卡机制改写，改写后是否还站得住人需要对着实机确认。
6. **关卡里还有没解析的字段**：`predefines`（1-7 有预置 token，位置在 `(3,3)` 朝上）、`runes`（四星限定词条）、`levelscripts`（关卡脚本）。目前只取了地图、路线、波次、基本参数。
7. **干员数据只覆盖 prts.wiki 上有的**。新干员上线到 prts.wiki 更新之间有窗口期。
8. **还没做等级经验表**。`arknights-toolbox-data` 的 `assets/data/level.json` 里有完整的
   `characterExp` / `characterUpgradeCost`（按稀有度与精英段逐级列出经验、龙门币消耗），
   要算「从 1 级练到 90 级要多少」时取它就行，但本项目目前只关心战斗数值，没有接入。
9. **属性计算的取整方式仍是假设**（详见第六章末），默认向下取整。若日后用实测值标定出
   是四舍五入，`OperatorCalculator(rounding="round")` 一行即可改，不必动代码。
10. **属性计算固定走 GitHub 镜像**，用不了 ark-nights 那个更精简的首选源——`excel/`
    三张表只有 GitHub 有。所以一旦 GitHub 直链不通，`stats` 会整体不可用，
    而 `stage` / `enemy` 不受影响。
11. **prts.wiki 缓存是朴素的 7 天 TTL**，没有做条件请求（ETag / Last-Modified）；gamedata 缓存则干脆不过期（它是版本化快照，要更新就删）。关卡索引有 7 天 TTL——它跟着游戏版本走，但比游戏本体更新得晚。
12. **prts.wiki 限速 1.2 秒/请求**意味着全库冷启动约 10 分钟（461 个干员）。批量抓取应该放在夜间一次性做完、落到本地仓库，而不是每次现抓。gamedata 没这个问题——关卡按需取，索引一次扒完能用一周。
13. **三星判定是一条假设，不是从数据里读出来的**。`verify.stars_of()` 现在按
    「不漏怪 3 星、漏 1 只 2 星、漏 ≥2 只 1 星、打输 0 星」判，
    **没有用实机验证过这条规则**。所以 `Verdict` 把 `won` / `life` / `max_life` /
    `leaks` 原样带出来——真要按别的口径判，用那几个字段即可，不必改 `stars_of`。
14. **验证器不支持同一名干员的二次部署**。`Plan.validate()` 会把「同一人下两次」
    直接拦下。要支持（撤退再上）得改模拟器的部署表结构，本版没做。
15. **`Plan` 里的技能时刻是"请求"不是"保证"**。`sim.use_skill(position, time)`
    排的是一次请求；技力不够就等够了再开。所以战报里的"出手次数"才是实际发生的事，
    想确认技能到底几点开，要看模拟器日志而不是 Plan。
16. **显式部署时刻是"请求"，而且模拟器照办——包括付不起费的时候。** 部署的显式
    时刻走 `at = time; cost += (at-now)/rate; cost = max(0, cost - deploy_cost)`，
    也就是**费用夹到 0、人照样落地**。后果是「付不起也下」被静默放过。
    验证器现在会在归因里如实写出来（「这一手在游戏里做不出来」），但**不改行为**
    ——三条回归基线的开局都靠这个宽松口径，一改全废。**已知受影响**：1-7 那条
    `133.0s` 基线，三名干员的落地时刻在费用上全都做不到（阿米娅 1.0s 要 18 费、
    当时 13 费；德克萨斯 5.0s 要 12 费、当时 4 费；拉普兰德 9.0s 要 19 费、
    当时 4 费）。它是地图/路线/伤害的**回归锚点**，不是一套可执行的作业。
    真正能执行的方案见搜索器的输出（`out/search-17.json`：拉普兰德 9.0s / 能天使
    23.0s，两人的费用都是刚好够，自动排程保证可行）。
17. **移速为 0 的敌人此前会被兜底成 1.0**（`sim._spawn` 的 `or 1.0`）。库里
    1803 页有 23 页最低档移速为 0，本项目已建模的三关都不含这种敌人，所以一直
    没暴露。已修，并在 `eta.enemy_speed` 与 `tools/check_eta.py` 里留了守卫。
18. **ETA 的「预估到终点」是无人拦截前提下的理论值**。它是摆位判断的依据
    （敌人几点会压到防线），不是实际漏怪——实际漏怪看「漏怪」行。两者同源，
    自检里逐只对拍到一帧以内。

---

## 许可

**MIT License**，全文见 [LICENSE](LICENSE)。第三方来源、许可与合规说明见
[THIRD-PARTY.md](THIRD-PARTY.md)。

干员数值与关卡数据取自游戏本体 gamedata，敌人资料取自 prts.wiki，地块字典取自 theresa.wiki
——版权归各自权利人所有。两个数据库文件不入库（克隆后自行 `db build` 重建），**仓库里不含
任何游戏数据副本**。本项目与鹰角网络无隶属关系、未获其授权，也不提供游戏资源下载。

⚠️ **代码与数据是两件事**：本仓库的**代码**是 MIT，允许商用；但由 prts.wiki、theresa.wiki
派生的**数据**随其 **CC BY-NC-SA 4.0**（署名—非商业—相同方式共享）走，不在 MIT 覆盖范围内。
要再分发建好的库，请先读 [THIRD-PARTY.md](THIRD-PARTY.md) 第六节的自查清单。
