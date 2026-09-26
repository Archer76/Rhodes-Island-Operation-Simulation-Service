# R.I.O.S. · 罗德岛作战演算服务
**Rhodes Island Operation Simulation Service**

给定战场地图与干员名册，演算出部署位置、技能开启时机与胜负判定，**再导出成 MAA 认得的作业 JSON**。
除了解算，它还能复核一份现成打法、搜索一套能三星的阵容、把漏怪归因到具体哪一只哪一秒。

编号得自游戏内的 PRTS 系统：Primitive Rhodes Island Terminal Service。它曾为一次搜救自行演算，
留下 167 份过程记录与 3,711 个执行节点，而其中仅有两个结果能导向成功。本服务做的是同一件事
——把那类「可能导向胜利的计算」做成可复现的程序。区别只在演算对象：一次是博士的搜救，一次是你自己的作战。

> 约定：本仓库里 **PRTS** 一律指游戏内的终端系统；取数用的资料站一律写作 **prts.wiki**。
> 两者同名不同物，按写法分辨即可。

数据有两条来源，分得很清楚：**文字资料查 prts.wiki 资料站，机器要算的数值查 gamedata**。

---

## 已建模的干员与关卡

**先说清楚一件事：干员与关卡都不是「逐个建模」的。** 引擎是通用的 30fps 逐帧推演，
名册里谁上场都能算；真正要一项一项建起来的，是下面这两张表。

### 干员

| 层 | 覆盖面 | 判据（**已取证到哪**） |
| --- | --- | --- |
| **面板层** | **全部 460 位可部署干员**（`character_table.json` 的 `char_` 段 458 ＋ 补丁 2） | 等级插值 ＋ 信赖 ＋ 潜能 ＋ 模组 → `base`／`trust_bonus`／`potential_bonus`／`module_bonus`／`total` 五份 ＋ 攻速三字段，与参照实现**逐字段一致**。**两栏不同口径，跨栏不可比**：真实练度 **679 次折算**＝fixtures 20 位深扫 **468** ＋ 账号名册 **211** 位；合成练度 **1324 次折算**＝`akdb` 的 `char_` 段**全量 460 位** |
| **干员规格层** | **全部 460 位** | 每人 33 个键（含条件键的存在性）逐位一致：64 / 64 人次 |
| **天赋机制层** | **按机制建，不按干员** | 已建模的机制见下 |
| **技能效果层** | **未搬** | `operators[].skill`／`active` 具名 `unported`，见 [`docs/go-selfsufficiency.md`](docs/go-selfsufficiency.md) 第三节 |

⚠ **看清「实现覆盖面」与「判据取证面」是两件事**：实现是通用的、不按名册枚举，
**460 位都在里**；判据现在也盖到了**全部 460 位**，但是**两栏、两类口径**：

- **真实练度 679 次折算**＝fixtures 20 位深扫 **468** ＋ 账号名册 **211** 位。这一栏吃
  **真实练度三元组**（精英／等级／潜能），证明的是「**真名册上算得对**」。
- **合成练度 1324 次折算**＝`akdb` 的 `char_` 段**全量 460 位**，每位取**自己能到的**
  E0／E1／E2 的**上限等级**（现算）、信赖 100、潜能 6、模组取该干员自己的。
  这一栏证明的是「**每一位的数据都被真跑过**」。

两栏是**不同口径，跨栏不可比**，所以分开写、不加成一个数：合成练度**不是**
「真名册上算得对」的证据；反过来，只跑前两栏那 231 位就宣布 460 位全覆盖，
也是不成立的（**取证范围不许窄于结论范围**）。
这是**判据的取证面**，不是实现的覆盖面。

**完整名单不入库**（它是 `akdb` 的 `char_` 段，随每次建库而变）——要就现算：建库后查 `operator` 表，见 [`docs/database.md`](docs/database.md)。

**被实战打法验证过的干员**（出现在 24 份已验收打法里的 16 位）：

> 凯尔希·思衡托 ・ 可露希尔 ・ 圣聆初雪 ・ 怒潮凛冬 ・ 拉普兰德 ・ 提丰 ・ 新约能天使 ・ 星熊 ・ 机械师 ・ 泥岩 ・ 焰狐龙梓兰 ・ 电弧 ・ 结城理 ・ 能天使 ・ 银灰 ・ 阿米娅

### 关卡

**引擎是关卡无关的**：`data/gamedata` 取得到的关卡都能直接跑（关卡索引 4715 条，含突袭档）。
逐关建起来的只有**活动机制**。

| 类 | 已验收的清单 |
| --- | --- |
| **主线 · 第 0～10 章** | **108 关全部**（`main_00-01` … `main_10-15`，不含 `#f#` 突袭档）：**同一把尺子下一次跑完** —— `108 / 108 关逐字段一致`、`593 只敌人逐字段一致`；逐章读数、口径总表与未核清单见 [`docs/mainline-chapter-audit.md`](docs/mainline-chapter-audit.md) |
| **活动 · 怀黍离**（`act31side`） | **19 关全部**：`01`～`09`、`ex01`～`ex08`、`tr01`、`tr02`（另含 `ex08` 突袭档 `#f#`） |
| 回归基线 | `1-7`、`SR-6`、`SR-EX-8` 三条（见「快速开始」） |

主线那 108 关的读法是：Go 与参照实现**逐字段一致**（地图／路线／出怪／敌人），
并且它们已经落在**关卡静态、格表、寻路、部分规格、机制规格、单一入口**六套判据的取证范围里。

### 已建模的机制

权威清单就是 `ping` 的应答：

```bash
echo '{"cmd":"ping"}' | rios-sim.exe
# → {"...","spec_done":true,"mechanisms":["chain","huai_shu_li.farmland","snow.field"]}
```

| 代号 | 是什么 |
| --- | --- |
| `chain` | 天桩召唤链（天桩-甲／乙／天标，含 `diver` 与落点爆炸） |
| `huai_shu_li.farmland` | 怀黍离的田地与泵站：病害值、层数护盾、装置接入 |
| `snow.field` | 积雪：铺场、扩散、减速与满层冻结 |

另有两类**未实现即具名拒跑**的线（见 `unsupported`）：`devices`（装置通道，目前只装泵站与天桩）
与 `snow_talent`。碰到它们的关卡**不会被静默跑出一个错结果**，而是明确拒跑并给出理由。

## 下载

不想装 Go 的话，用 [Releases](https://github.com/Archer76/Rhodes-Island-Operation-Simulation-Service/releases)
里的预编译引擎（Windows amd64）：

```powershell
$env:RIOS_SIM_BIN = "D:\path\to\rios-sim.exe"     # cmd: set RIOS_SIM_BIN=D:\path\to\rios-sim.exe
```

Python 侧仍是本仓库的 `ak_tactic/`。**Release 里只有代码与二进制，不含任何游戏数据**
——关卡、敌人与干员数值要自己按 [`docs/data-sources.md`](docs/data-sources.md) 取，
或在本机跑 `python tools/rebuild_data.py` 一条命令重建。

## 这个仓库里有什么

**只放「拿它做事的人用得到的东西」。** 这句不是修辞，它是一条会执行的判据：凡是只有在这一台机器上、
只有配上当时那一版引擎与夹具才有意义的文件，一律不进仓库——排障用的一次性探针、逐轮的审计仪器、
在建过程中的工作台账，都属于这一类。它们留在开发机上，且**随时可能与本仓库不同步**。

因此这里**没有**：验证流水线、基准测试框架、逐关闸门台账、进度报告。
下面每一节都只描述**克隆下来就成立**的东西。

| 目录 | 是什么 |
| --- | --- |
| `ak_tactic/` | Python 侧全部产品代码（CLI、取数、属性、正文编译、解算、搜索、终端界面、两个本地库） |
| `rios-sim/` | Go 侧模拟器内核（默认引擎） |
| `tools/` | 面向使用者的脚本：自检套件、三条回归基线、名册与账号、生成物 |
| `fixtures/` | **判据集**：可执行作业与回归基线（按 schema 认，不按文件名）。子目录 `fixtures/golden/` 是**冻结基线**——把每套判据的期望值冻进版本控制，让判据可以「Go 现读 vs 冻结基线」地跑，不再实时对拍 Python（迁移进度见 [`docs/golden-baseline.md`](docs/golden-baseline.md)） |
| `docs/` | 实测报告与口径文档 |

## 它能做什么

| 节点 | 职能 |
| --- | --- |
| 情报整备 | 建立两份离线档案：干员档案（gamedata，**不联网**）与敌人档案（prts.wiki，**要联网**）；地块字典另循 theresa.wiki |
| 属性核定 | 核定一名干员的真实面板：等级插值 ＋ 信赖 ＋ 潜能 ＋ 模组；攻击速度 ＝ 天赋 ＋ 模组特性改写 ＋ 技能 |
| 作战演算 | 30fps 逐帧推演：伤害（物理／法术／真实，含 5% 保底与法抗满值免疫）、阻挡与目标选择（敌人优先攻击最后部署的干员）、伤害相性与击破倒地、全场总攻击装置 |
| 正文编译 | 将技能／天赋／模组／敌技的**中文正文**编译为可结算的公式项——只读黑板会漏算，不读正文会算错 |
| 方案求解 | 复核一份打法、搜索一套可三星的阵容、按该次作战的费用环境编成名册 |
| 记录导出 | 摆位图／时间轴／路线热度／漏怪归因报告，以及 MAA copilot 作业 |

## 终端向导

```
python -m ak_tactic tui
```

四步走完：**选关卡 → 指定编队 → 解算 → 导出**。不用记子命令与参数，算完直接把作业 JSON 落地。

| 屏 | 按键 |
| --- | --- |
| `[0]` 准备 | `Enter` 开始 ・ `D` 改导出目录 ・ `L` 登录 ・ `U` 取账号 uid ・ `O` 退出账号 ・ `Q` 退出程序 |
| 登录 | `L` 扫码登录 ・ `S` 切换已登过的账号 ・ `Esc` 不登录（会问一句是本次还是以后） |
| 选关卡 | `Enter` 选定 ・ `Esc` 返回上一层 |
| 选编队 | 主职业行 / 子职业行挑范围（鼠标点或 `←` `→`）・`Space` 勾选 ・`M` 切模式 ・`Enter` 开始解算 ・`Esc` 返回 |
| 解算 | `Q` 中止（**退回上一步**，不是退出程序） |
| 结果 | `E` 导出 ・ `H` 回主界面 ・ `Q` 退出程序 |

`Esc` 逐层返回，一路退回到 `[0]`。解算屏与结果屏不挂 `Esc`——那两屏的出口是明确的：
解算中止退回上一步，结果屏只留回主界面与退出程序。方案与全部裁定见 [`docs/tui-plan.md`](docs/tui-plan.md)。

## 快速开始

**依赖三个第三方包**（清单见 [`requirements.txt`](requirements.txt)）：
`textual`（含 `rich`，只给终端界面用）、`qrcode`（只给二维码用）、`pycryptodome`（只给数美设备指纹用）。
**三个都是惰性导入**——不装 `textual` 与 `qrcode`，模拟、验证、搜索与全部自检照跑不误。

```bash
pip install -r requirements.txt        # 可选：不装就少一个终端界面与扫码登录
```

本机实测 **Python 3.14.4**；未用版本敏感语法，3.10+ 应当都能跑。

```bash
cd <仓库目录>

# 1) 建两个本地库
python -m ak_tactic db build          # 干员库，不联网，约 3.4s
python -m ak_tactic enemydb build     # 敌人库，要联网，首次约 53s（prts.wiki 限速 1.2s/请求）
#    也可以一条命令把 data/ 下该有的东西全建出来（含上面两步与 prts 备注库、范围表）：
#    python tools/rebuild_data.py --offline   # 只跑不联网的
#    python tools/rebuild_data.py             # 全量

# 2) 跑全套自检 —— 全绿才算没退化
#    套数会随规则增删而变，本文件不写死：ls tools/check_*.py 就是当前清单
#    各套的项数同样不写死，每套末行会自报当前项数
for f in tools/check_*.py; do python "$f" || echo "FAIL $f"; done

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
> （见 [`docs/limitations.md`](docs/limitations.md) 第 14 条），它锚的是地图／路线／伤害的一致性。

**需要联网的两处**：gamedata（关卡与敌人数值，走 `map.ark-nights.com` 与 GitHub 镜像）与
prts.wiki（干员文字资料、敌人页面）。两者的响应都落 `data/cache/`，**7 天 TTL**，重复跑不会重新请求。
干员库建库完全不联网。

### 两个引擎

战斗推演有两套实现，**默认走 Go**：

| | 位置 | 状态 |
| --- | --- | --- |
| Go | `rios-sim/`（由 `ak_tactic/simgo/` 驱动） | **默认引擎**，`Verifier(engine="go")` |
| Python | `ak_tactic/battle/` | 仍在，且 `verify.py` 称之为**权威实现**；`engine="python"` 显式切换 |

★ 这一点必须说清楚，因为它会**静默**改变语义：仓里凡是必须拿到 Python 结果的地方，都要**显式**传
`engine="python"`。裸 `Verifier()` 现在是 Go。

Go 侧由 `RIOS_SIM_BIN` 指定二进制路径。**不设它不会报错，而是静默落到某个预编译的旧 exe 上**
——于是同一条命令在两个时刻给出两个数。测任何东西之前先钉住它。

## 作业规程

- **只搬不推**：档案存原文（关键帧、黑板），插值与加成留在核定层——两处各算一遍，迟早对不上。
- **未知量必须实测标定**：编出来的默认值未必保守，它可能正好落在好看的那一边。
- **数字不写死在文档里**：水位与项数会漂，写查询命令而不是写结果。
- **能重跑就不手写**：裁定表、待裁定清单、敌人字段总账都由脚本生成，手改会在下次再生时丢掉。
- **中文正文的引号一律用「」**：由 `tools/cjk_quote_lint.py` 在提交前拦下，非 0 退出即不许提交。

## 常用命令

```bash
python -m ak_tactic get 银灰                 # 干员数据
python -m ak_tactic stats 银灰 --elite 2 --level 90 --trust 100 --potential 6
python -m ak_tactic stage main_01-07         # 关卡：地图 / 路线 / 波次时间轴
python -m ak_tactic verify main_01-07 --team "…"   # 验证一份打法（退出码 0=三星）
python -m ak_tactic search SR-EX-8 --beam …  # 搜索一套能三星的阵容
python -m ak_tactic team SR-6                # 按角色出名册建议
python tools/export_srx8.py                  # 导出 MAA copilot 作业
python -m ak_tactic tui                      # 终端向导
```

全部子命令、参数与退出码见 [`docs/cli.md`](docs/cli.md)；库表结构与查询示例见
[`docs/database.md`](docs/database.md) 与 [`docs/interfaces.md`](docs/interfaces.md)。

## 代码结构

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
│  ├─ mechanics.py           地图机制 → 公式项（活动术语表 + 关卡页锚点）
│  ├─ activity.py            活动机制完整性盘点（已实现 / 待实现 / 不需要）
│  ├─ skland.py              森空岛登录与名册拉取（凭据按 uid 分文件，可切号）
│  ├─ qrterm.py              终端二维码渲染（▄ 逐格上色，不塞 ANSI 串）
│  ├─ maa_export.py          打法 → MAA copilot JSON（模组编号 / 计时条件口径）
│  ├─ fetchplan.py           取数预估：体积现测、耗时用实测值
│  ├─ tui/                   终端界面（Textual 只在这里惰性导入）
│  │  ├─ app.py              各屏与向导推进（`Esc` 逐层返回靠自记路径）
│  │  ├─ data.py             名册 / 关卡 / 配置的取数（名册按当前账号取）
│  │  └─ theme.py            配色与步骤条
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
│  ├─ verify.py          ★  通用验证器：打法 → 三星判定 + 归因（engine= 在此选）
│  ├─ search.py          ★  搜索器：几何剪枝 → beam search（落位/朝向/顺序）
│  ├─ parallel.py        ★  批量并行：进程池 + 跨调用复用（搜索 / 参数扫描）
│  ├─ team.py            ★  组队建议：按角色位挑人（回费先锋 / 骗伤 / 低费位）
│  ├─ diagram.py         ★  输出：摆位图 / 路线热度图 / 时间轴表格 / 完整报告
│  ├─ simgo/             Go 引擎驱动层（规格编译 client.py + 机制/技能规格 + verifier）
│  └─ battle/                战斗模型（Python 侧；见上文「两个引擎」）
│     ├─ damage.py           物理 / 法术 / 真实 / 治疗
│     ├─ unit.py             干员与敌人在战斗中的可变态
│     ├─ range.py            攻击范围 → 实际覆盖格（朝向旋转）
│     ├─ talents.py          战斗内天赋（积雪、费用加成…）
│     ├─ p3r.py              相性（P3R）与「全场总攻击」装置
│     └─ sim.py              模拟器本体（帧级推进）
├─ rios-sim/                 Go 引擎（默认）。`go build` 出二进制；源码与 go.mod 入库
├─ tools/                    面向使用者的脚本（清单以目录为准，别写死）
│  ├─ check_*.py             自检套件：每套一个主题，非 0 退出即有退化
│  ├─ cjk_quote_lint.py      提交闸门：中文正文的引号必须是「」
│  ├─ gated_commit.py        带闸门的提交助手（检查不过就不提交）
│  ├─ rebuild_data.py        一条命令重建 data/ 下的可再生派生物（见 .gitignore 注释）
│  ├─ golden_go.py           判据集 fixtures/ 的读写：--check 逐项核对 / --extend 追加
│  ├─ run_sr6.py / run_srx8.py / export_srx8.py    三条回归基线与 MAA 导出
│  ├─ skland.py / skland_did.py / roster.py / operbox_path.py / squad.py   名册与账号
│  ├─ unit_audit.py / uncertainty_audit.py / enemy_field_audit.py   三份生成物（非 0 退出即有缺口）
│  ├─ gen_*.py               视图与夹具生成：干员视图 / 敌人视图 / 天赋检测器 / 田地金样
│  ├─ selftest.py / smoke_hsl.py / audit_coverage.py / audit_unmodelled_abilities.py
│  ├─ spec_deps.py / spec_imports.py / simgo_cost.py / trace_kv.py / check_spec_keys.py
│  ├─ gate_ledger.py / mainline_strata.py / parity_plan.py / parity_ledger.py
│  └─ chain_judge_independence.py / check_mech_spec.py
├─ fixtures/                 可执行作业与回归基线（**判据集**，按 schema 认）
├─ docs/                     实测报告与口径文档（全部条目见下方导航）
└─ data/
   ├─ cache/prts/            prts.wiki HTTP 响应缓存（7 天）
   ├─ ranges.json            攻击范围索引
   ├─ gamedata/              gamedata 原始文件缓存（约 17 MB，可随时删）
   ├─ akdb.sqlite            干员库（纯派生物，db build 约 3.4s 重建）
   └─ enemydb.sqlite         敌人库（纯派生物，enemydb build 冷启约 53s）
```

分层只有两个原则：**把上游的脏活关在 `client.py` / `source.py` 里**——403、SSL 抖动、限速、翻页、
15 MB JSON 的内存膨胀，上层一概看不见；**坐标在入口处一次定型**——全项目内部一律 MAA 口径
（原点左上、y 向下），再往下的每一层都不许再翻。

> `tools/` 与 `docs/` 里的**内部件**（一次性探针、逐轮审计仪器、在建台账）不进本仓库。
> 所以你在别处看到的 `tools/xxx.py` 引用，不一定能在克隆里找到——那是有意为之，不是漏了。

## 文档导航

| 想了解 | 看哪份 |
| --- | --- |
| 怎么用命令行、退出码与参数 | [`docs/cli.md`](docs/cli.md)、[`docs/interfaces.md`](docs/interfaces.md) |
| 两个本地库的结构与为什么分成两个 | [`docs/database.md`](docs/database.md)、[`docs/operator-db.md`](docs/operator-db.md)、[`docs/enemy-db.md`](docs/enemy-db.md) |
| 两条数据源的实测结论与坑 | [`docs/prts-wiki.md`](docs/prts-wiki.md)、[`docs/gamedata.md`](docs/gamedata.md) |
| **全部数据源与来源台账** | [`docs/data-sources.md`](docs/data-sources.md) |
| 元素损伤（元素值 / 爆条 / 两列爆发效果） | [`docs/element-damage.md`](docs/element-damage.md)、[`docs/mechanics-dictionary.md`](docs/mechanics-dictionary.md) |
| 闸门条目 × Go 落地状态（静态盘点，含两类假信号） | [`docs/gate-inventory.md`](docs/gate-inventory.md) |
| 正文怎么编译成公式项 | [`docs/formula-model.md`](docs/formula-model.md)、[`docs/formula-maintenance.md`](docs/formula-maintenance.md)、[`docs/enemy-formula.md`](docs/enemy-formula.md) |
| 公式取源对照与量纲 | [`docs/formula-sources.md`](docs/formula-sources.md)、[`docs/formula-units.md`](docs/formula-units.md) |
| 地图机制、关卡环境与装置 | [`docs/mechanics.md`](docs/mechanics.md)、[`docs/environment.md`](docs/environment.md)、[`docs/activity.md`](docs/activity.md) |
| 终端界面的方案与裁定 | [`docs/tui-plan.md`](docs/tui-plan.md) |
| 关卡数据与解法记录 | [`docs/stage-1-7.md`](docs/stage-1-7.md)、[`docs/stage-sr-6.md`](docs/stage-sr-6.md)、[`docs/stage-sr-ex-8.md`](docs/stage-sr-ex-8.md)、[`docs/srx8-qi-solution.md`](docs/srx8-qi-solution.md)、[`docs/real-run-srx8.md`](docs/real-run-srx8.md)、[`docs/mainline-stages.md`](docs/mainline-stages.md) |
| 具体干员／敌人的机制口径 | [`docs/wang-mechanics.md`](docs/wang-mechanics.md)、[`docs/ranged-enemy-rule.md`](docs/ranged-enemy-rule.md)、[`docs/squad-skill-audit.md`](docs/squad-skill-audit.md)、[`docs/enemies-sr-ex-8.md`](docs/enemies-sr-ex-8.md) |
| 实施进度与任务拆分 | [`docs/roadmap.md`](docs/roadmap.md)、[`docs/batch2-plan.md`](docs/batch2-plan.md) |
| **判据怎么退出「实时对拍 Python」**（冻结基线：逐套状态、四种态、信任模型） | [`docs/golden-baseline.md`](docs/golden-baseline.md) |
| **整闸在某一棵树上的读数**（树／仪器／输入／结果四件套） | [`docs/gate-readings.md`](docs/gate-readings.md) |
| Go 自足进度与「哪一层已搬」 | [`docs/go-selfsufficiency.md`](docs/go-selfsufficiency.md) |
| 还没定的事、还在猜的事 | [`docs/uncertainties.md`](docs/uncertainties.md)、[`docs/limitations.md`](docs/limitations.md) |

## 已知局限

挑几条最要紧的说，全部条目见 [`docs/limitations.md`](docs/limitations.md)：

- **属性计算固定走 GitHub 镜像**——`excel/` 三张表只有 GitHub 有。一旦 GitHub 直链不通，`stats` 会整体不可用，而 `stage` / `enemy` 不受影响。
- **三星判定是一条假设**，不是从数据里读出来的（现按「不漏怪 3 星、漏 1 只 2 星、漏 ≥2 只 1 星」判），没有用实机验证过。
- **`Plan` 里的时刻是「请求」不是「保证」**，而且显式部署时刻连付不起费也照办——三条回归基线的开局都靠这个宽松口径，一改全废。
- **验证器不支持同一名干员的二次部署**（撤退再上）。
- 对手侧的抬手与攻击动作时长仍未对齐；prts.wiki 缓存是朴素 7 天 TTL，没做条件请求。

## 许可

**MIT License**，全文见 [LICENSE](LICENSE)。第三方来源、许可与合规说明见
[THIRD-PARTY.md](THIRD-PARTY.md)。

干员数值与关卡数据取自游戏本体 gamedata，敌人资料取自 prts.wiki，地块字典取自 theresa.wiki
——版权归各自权利人所有。两个数据库文件不入库（克隆后自行 `db build` 重建），**仓库里不含
任何游戏数据副本**。本项目与鹰角网络无隶属关系、未获其授权，也不提供游戏资源下载。

⚠️ **代码与数据是两件事**：本仓库的**代码**是 MIT，允许商用；但由 prts.wiki、theresa.wiki
派生的**数据**随其 **CC BY-NC-SA 4.0**（署名—非商业—相同方式共享）走，不在 MIT 覆盖范围内。
要再分发建好的库，请先读 [THIRD-PARTY.md](THIRD-PARTY.md) 第六节的自查清单。
