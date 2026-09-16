# 接口总览

> **这份文档覆盖本项目的全部对外接口**：15 个命令行子命令、整个 Python 包的公开面、
> 23 个 `tools/` 脚本、三种交换文件格式、环境变量与退出码。
>
> 分工：本文讲**怎么调用**；某个子系统内部的原理见对应专项文档
> （公式这一层见 [`formula-maintenance.md`](formula-maintenance.md)，
> 其余见文末的文档索引）。
>
> 条目以**实际可调用**为准，都从源码导出核过。改接口请顺手改这里。

---

## 一、分层与调用面

```
                   ┌─────────────────────────────────────────┐
   命令行 ────────►│  ak_tactic.cli（15 个子命令）            │
                   ├─────────────────────────────────────────┤
   Python ───────►│  ak_tactic.*（5 个子包 / 38 个模块）      │──► 两个本地库
                   ├─────────────────────────────────────────┤      data/akdb.sqlite
   脚本 ─────────►│  tools/*.py（23 个：自检 / 试跑 / 取数）  │      data/enemydb.sqlite
                   └─────────────────────────────────────────┘           │
                                     │                                 ▼
                                     └──────────────────► 三个上游取数（运行时、有缓存）
                                                          gamedata 镜像 / prts.wiki / theresa.wiki
```

三种调用方式各有其位：

| 方式 | 适合 | 入口 |
| --- | --- | --- |
| 命令行 | 查数据、跑验证、出报告 | `python -m ak_tactic <子命令>` |
| Python API | 写脚本、做二次开发 | `import ak_tactic.*` |
| `tools/` 脚本 | 回归自检、批量试跑、取账号数据 | `python tools/<脚本>.py` |

**稳定性约定**：不带下划线的名字是公开接口；`_` 开头的函数、模块级常量表
（如 `RULES`、`RATIO_KEYS`）**可以被读**，但改动它们属于内部行为，不保证不破坏兼容。
`ak_tactic.__version__` 当前为 `0.2.0`。

---

## 二、数据来源与两个库

### 两个库（互不引用、结构版本各自独立）

| 库 | 内容 | 来源 | 建库命令 | 联网 |
| --- | --- | --- | --- | --- |
| `data/akdb.sqlite` | 干员（属性/潜能/信赖/天赋/特性/技能/模组/范围）+ 地块字典 | gamedata（`excel/` 六张表）+ theresa.wiki（`tile` 表） | `python -m ak_tactic db build` | 否（tile 表除外，取不到只警告） |
| `data/enemydb.sqlite` | 敌人（图鉴/逐档数值/抗性/敌方技能/天赋黑板） | prts.wiki 的「分类:敌人」 | `python -m ak_tactic enemydb build` | 是（首次约 51s） |

**两个库都是纯派生物**，已 gitignore，随时可重建；查询默认走**只读连接**，
`sql` 动作只允许 `SELECT` / `WITH` / `PRAGMA`。

### 三个上游

| 上游 | 取什么 | 代码入口 | 缓存 |
| --- | --- | --- | --- |
| gamedata（首选 `map.ark-nights.com`，备选 Kengxxiao 镜像） | 关卡地图/路线/敌人数值/攻击范围/属性表 | `gamedata.source.GameDataSource` | `data/gamedata/`（按域名分目录） |
| prts.wiki | 干员页、敌人页正文与模板 | `prts.client.PrtsClient` | `data/cache/prts/`（TTL 7 天） |
| theresa.wiki | 地块字典 95 条 | `db.tiles.fetch_tile_info` | `data/cache/theresa/`（TTL 7 天） |

取数纪律（详见 `THIRD-PARTY.md`）：**仓库不分发任何上游数据**；prts.wiki 与 theresa.wiki
是 CC BY-NC-SA 4.0，若要把派生数据再分发须自行评估。

---

## 三、命令行接口

### 3.0 全局

```
python -m ak_tactic [--no-cache] <子命令> [参数]
```

| 选项 | 含义 |
| --- | --- |
| `--no-cache` | 跳过缓存，强制重新取数（对走网络的子命令有效） |

**退出码**：`0` 成功；`1` 业务失败（查不到、参数非法、数据源缺表、自检有失败项）。
脚本失败时会打印一句**能照做的**提示，而不是堆栈。

---

### 3.1 `get` —— 取一个干员（走 prts.wiki）

`python -m ak_tactic get <name> [选项]`

| 参数 | 含义 |
| --- | --- |
| `name` | 干员名，如 `能天使` |
| `--full` | 展开全部技能等级（默认只留 7 级与专精三） |
| `--range` | 同时打印攻击范围网格 |
| `--json` | 输出 JSON |

> 这是**实时取数**路径，不碰本地库。要查本地库用 `db char`。

---

### 3.2 `list` —— 列干员名录（走 prts.wiki 的 Cargo）

`python -m ak_tactic list [选项]`

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `--profession` | — | 按职业筛，如 `狙击` |
| `--rarity` | — | 按星级筛，如 `6` |
| `--limit` | `1000` | 最多列几条 |
| `--raw-names` | 关 | 改为列分类里的页面名（含消歧义后缀） |
| `--json` | 关 | 输出 JSON |

---

### 3.3 `range` —— 看攻击范围

`python -m ak_tactic range [codes] [选项]`

| 参数/选项 | 含义 |
| --- | --- |
| `codes` | 范围代号，如 `3-3`；不给则用本地索引 |
| `-o` / `--operator` | 按干员名取它的三个精英阶段范围 |
| `--json` | 输出 JSON |

---

### 3.4 `stage` —— 取关卡（地图、路线、波次时间轴）

`python -m ak_tactic stage <level_id> [选项]`

| 参数/选项 | 默认 | 含义 |
| --- | --- | --- |
| `level_id` | — | 关卡号或 levelId：`SR-EX-8` / `1-7` / `act54side_ex08` |
| `--search` | 关 | 按关卡号/区域/levelId 模糊找（只找不取数） |
| `--chapter` | 自动 | 关卡所属章节子目录，默认从 id 前缀推断 |
| `--map` | 关 | 只看地图，不加载敌人数据 |
| `--no-routes` | 关 | 地图上不叠路线 |
| `--timeline` | 关 | 打印完整出怪时间轴 |
| `--limit` | `25` | 时间轴默认只显示前 N 条 |
| `--json` | 关 | 输出 JSON |

> 坐标系是 **MAA 标准**：原点左上、y 向下。口诀「地图不翻、路线翻」。

---

### 3.5 `enemy` —— 取敌人图鉴与数值（走 gamedata，实时）

`python -m ak_tactic enemy <enemy_id> [选项]`

| 参数/选项 | 默认 | 含义 |
| --- | --- | --- |
| `enemy_id` | — | 敌人 id，如 `enemy_1007_slime_2` |
| `--level` | 最高档 | 档位 |
| `--search` | — | 按中文名搜索，如 `--search 源石虫` |
| `--limit` | `30` | 搜索上限 |
| `--json` | 关 | 输出 JSON |

> 与 `enemydb show`（查本地库）是两条路，别混淆。

---

### 3.6 `stats` —— 算干员属性

`python -m ak_tactic stats <char_id> [选项]`

| 参数/选项 | 默认 | 含义 |
| --- | --- | --- |
| `char_id` | — | 干员 id 或中文名 |
| `--elite` | — | 精英阶段 0/1/2 |
| `--level` | `1` | **阶段内**等级（从 1 开始，不是 1–90） |
| `--trust` | — | 信赖 0–100 **内部标度**（= 游戏显示信赖 ÷ 2；100 即满信赖 200%） |
| `--potential` | `1` | 潜能 **1–6**（游戏内编号） |
| `--module` | — | 模组 id，如 `uniequip_002_amiya` |
| `--module-level` | — | 模组等级 1/2/3 |
| `--modules` | 关 | 只列出该干员的模组 |
| `--rounding` | `floor` | 插值取整：`floor` / `round` / `ceil` / `none` |
| `--search` | 关 | 按 id 或中文名找干员（不计算） |
| `--limit` | `20` | 搜索上限 |
| `--json` | 关 | 输出 JSON |

> 属性 = 等级插值 + 信赖 + 潜能 + 模组。**取整方式是唯一未证实的假设**，故做成参数。

---

### 3.7 `skills` —— 看技能

`python -m ak_tactic skills <char_id> [选项]`

| 参数/选项 | 默认 | 含义 |
| --- | --- | --- |
| `char_id` | — | 干员 id 或中文名 |
| `--level` | `7` | 技能等级 1–7 |
| `--mastery` | `0` | 专精等级 0–3 |
| `--all` | 关 | 展开全部十个等级 |
| `--elite` | `2` | 算攻击力用的精英阶段 |
| `--trust` / `--potential` | — / `1` | 同上（影响绝对伤害） |
| `--no-atk` | 关 | 不显示绝对伤害 |
| `--coverage` | 关 | 改为报告黑板键的归类覆盖率 |
| `--search` / `--limit` | 关 / `20` | 按名字找（只列技能名） |
| `--json` | 关 | 输出 JSON |

---

### 3.8 `talents` —— 看天赋

`python -m ak_tactic talents <char_id> [选项]`

| 参数/选项 | 默认 | 含义 |
| --- | --- | --- |
| `char_id` | — | 干员 id 或中文名 |
| `--elite` / `--level` / `--potential` | `2` / `1` / `1` | 练度 |
| `--all-candidates` | 关 | 列出该干员天赋的**全部档位**（含未解锁） |
| `--coverage` | 关 | 报告天赋黑板的规模 |
| `--json` | 关 | 输出 JSON |

---

### 3.9 `db` —— 干员库（gamedata）

`python -m ak_tactic db [action] [key] [选项]`

| action | 含义 |
| --- | --- |
| `info`（默认） | 版本与行数 |
| `build` | 重建库（不联网） |
| `char` | 干员详情 |
| `find` | 找干员 |
| `skill` | 搜技能 |
| `talent` | 搜天赋 |
| `levels` | 一个技能的全等级 |
| `sql` | 只读查询 |
| `schema` | 表说明 |
| `tiles` | 查地块字典 |
| `tile-fetch` | 重取地块字典（theresa.wiki） |

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `key` | — | 动作的对象：干员 id/名字、关键词、技能 id、SQL、地块关键词或 tileKey |
| `--key` | — | 按**黑板键**过滤，如 `atk_scale` / `sluggish` / `ammo`（会自动同时试 `key` 与 `attack@key`） |
| `--limit` | `30` | 上限 |
| `--path` | `data/akdb.sqlite` | 库文件路径 |
| `--include-tokens` | 关 | `find` 时把召唤物与装置也列出来 |
| `--verbose` | 关 | `build` 打印进度 |
| `--force` | 关 | `tile-fetch` 忽略缓存强制重取 |
| `--json` | 关 | 输出 JSON |

---

### 3.10 `enemydb` —— 敌人库（prts.wiki）

`python -m ak_tactic enemydb [action] [key] [选项]`

| action | 含义 |
| --- | --- |
| `info`（默认） | 版本与行数 |
| `build` | 重建库（联网，首次约 51s） |
| `find` | 找敌人 |
| `show` | 敌人详情 |
| `formula` | **把正文编译成公式项**（敌人侧；干员侧走顶层的 `formula`，见 3.11） |
| `sql` | 只读查询 |
| `schema` | 表说明 |

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `--grade` | — | `find` 时按地位级别过滤：`普通` / `精英` / `领袖` |
| `--limit` | `30` | 上限 |
| `--pages` | — | `build` 时只抓前 N 页（试跑用） |
| `--path` | `data/enemydb.sqlite` | 库文件路径 |
| `--verbose` | 关 | `build` 打印进度 |
| `--json` | 关 | 输出 JSON |

---

### 3.11 `formula` —— 正文 → 公式项（干员侧）

`python -m ak_tactic formula [正文] [选项]`

把中文描述编译成**结构化公式项**。这是干员侧的编译入口，与 `enemydb formula`
（敌人侧）对称；**不需要数据库也能用**——给一段文本即可。

| 用法 | 含义 |
| --- | --- |
| `formula "攻击力+50%"` | 编译**任意文本**（干员规则） |
| `formula --enemy "移动速度提升至150%"` | 改用**敌人规则**（含 wiki 模板展开与带变量的算式） |
| `formula --char 望` | 库里某个干员的**全部天赋**（名字或 `char_id`） |
| `formula --skill 取势` | 某个技能的**全部等级**（技能名或 `skill_id`；撞名时报错列出候选） |
| `formula --scan` | 全库覆盖率 + 未命中的高频残句 |
| `formula --scan --enemy` | 同上，统计敌人库 |

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `--bb` | — | 黑板系数，如 `"atk=0.5,sluggish=6.5"`（也接受 JSON 对象） |
| `--top` | `25` | `--scan` 时列几条高频残句/规则 |
| `--path` | `data/akdb.sqlite` | 库路径（`--enemy --scan` 时是 `data/enemydb.sqlite`） |
| `--json` | 关 | 输出 JSON（逐项含 `to_dict()` 的全部字段，可溯源 `evidence`） |

> **只做识别与结构化，不做数值推断。** 带变量的算式只保留结构
> （`expr` 是算式、`vars` 是依赖、`amount` 一律为空）；正文没写幅度就如实标
> 「（幅度未写明）」，不编一个。给算式算出个值就是错的。
>
> 退出码：正常 `0`；缺少参数、`--bb` 格式错、干员/技能查不到或撞名，都返回 `2`。

---

### 3.12 `verify` —— 验证一份打法

`python -m ak_tactic verify <stage> [选项]`

| 参数/选项 | 含义 |
| --- | --- |
| `stage` | 关卡号（如 `main_01-07`）；给了 `--plan` 时可省（以文件里的为准） |
| `--plan` | 打法 JSON 文件 |
| `--team` | 临时打法，如 `"圣聆初雪:5,4:Right:3; 德克萨斯:6,3:Right:0"`——`;` 分隔干员，`,` 留给坐标，格式 `名字:x,y:朝向:技能槽` |
| `--box` | 名册 JSON（MAA OperBox 或森空岛名册） |
| `--save-plan` | 把临时打法存成 JSON 再跑 |
| `--no-range-table` | 不接真实攻击范围（退回 3 格近似，**仅用于回归对照**） |
| `--diagram` | 附上地图摆位图（MAA 坐标，原点左上） |
| `--timeline` | 附上时间轴表格（出怪/落地/开技能/漏怪/到终点） |
| `--report` | 把摆位图 + 热度图 + 时间轴 + 战报写成一份完整报告文件 |
| `--heat-metric` | 路线热度度量：`dwell`（敌人·秒，默认）/ `routes`（路线条数） |
| `--verbose` / `--json` | 详细输出 / JSON |

**三星判定**：`stars_of(won, leaks)`——没打完或漏 1 只以上即掉星。归因报告会指出
「谁没出手、哪条路线热度为 0、装置卡在谁身上」，这是排查打法最有效的一步。

---

### 3.13 `search` —— 搜一套能三星的阵容

`python -m ak_tactic search <stage> [选项]`

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `--box` | **必给** | 名册 JSON |
| `--team` | — | 限定搜索的干员，`;` 或 `,` 分隔；不给则取名册前 `--top` 名 |
| `--top` | `8` | 未指定 `--team` 时取名册前几名 |
| `--max-ops` | `4` | 最多上几个人 |
| `--beam` | `5` | 每层保留几个状态 |
| `--per-op` | `6` | 每个干员留几个候选落位 |
| `--save-plan` | — | 找到的打法写到哪 |
| `--no-range-table` / `--json` | 关 | 同上 |

> 搜索是两层：几何剪枝（谁能覆盖到必经格）→ beam search（按时间轴排部署与开技能）。

---

### 3.14 `team` —— 组队建议

`python -m ak_tactic team [选项]`

| 选项 | 默认 | 含义 |
| --- | --- | --- |
| `--box` | **必给** | 名册 JSON |
| `--size` | `8` | 建议几人 |
| `--stage` | — | 关卡（如 `main_01-07` / `HS-8`）。**给了才判费用环境**——初始费用不够开局下一个人时会加一个低费位 |
| `--no-charger` | 关 | 只要一个回费位，不再搭第二个先锋 |
| `--db` | `data/akdb.sqlite` | 干员库路径 |
| `--json` | 关 | 输出 JSON |

---

### 3.15 `cache` —— 缓存管理

`python -m ak_tactic cache [选项]`

| 选项 | 含义 |
| --- | --- |
| `--clear` | 清空 prts HTTP 缓存 |
| `--drop-ranges` | 删除攻击范围索引 |
| `--clear-gamedata` | 删除 gamedata 缓存（关卡与敌人数据，约 17 MB） |

---

## 四、Python API

> 下列每个名字都是**公开**（不带下划线）的。签名从源码导出；`→` 后为返回类型，
> 省略号表示该处有默认值，以源码为准。

### 4.1 顶层

| 名字 | 说明 |
| --- | --- |
| `ak_tactic.__version__` | 版本串（当前 `0.2.0`） |

### 4.2 `ak_tactic.gamedata` —— 游戏本体数据

| 名字 | 说明 |
| --- | --- |
| `source.GameDataSource` | gamedata 的取数门面（首选 ark-nights，回退 GitHub 镜像） |
| `source.GamedataError` | 取不到数据，或数据长得不像 gamedata |
| `source.LevelEntry` | 关卡索引里的一条 |
| `stage.load_stage(query, *, code='', chapter=…)` | 取一份关卡并解析成 `Stage` |
| `stage.parse_stage(raw, *, level_id='', code='')` | 把一份关卡 JSON 解析成 `Stage` |
| `stage.enemy_refs(raw)` | 关卡引用的敌人清单（含各自要用的等级） |
| `stage.Stage` / `StageMap` / `Tile` / `Route` / `RouteLeg` / `Checkpoint` / `EnemySpawn` / `StageOptions` | 关卡模型；`StageMap` 用 MAA 坐标（原点左上、y 向下） |
| `range.RangeTable` / `range.RangeGrid` | `excel/range_table.json` 的读取入口与格集合 |
| `enemy.EnemyLibrary` | 敌人图鉴与属性的统一入口 |
| `enemy.EnemyStats` | 一个敌人在某一等级下的数值 |
| `enemy.affinity_of(blackboard, prefix='TotalAttack')` | 从黑板取一组伤害相性 |

### 4.3 `ak_tactic.prts` —— prts.wiki 取数

| 名字 | 说明 |
| --- | --- |
| `client.default_client()` | 进程级默认客户端（共享缓存与限速器） |
| `client.PrtsClient` | wiki API 门面：`get_json` / `wikitext` / `try_wikitext` / `search_pages` / `category_members` / `cargo` |
| `client.PrtsError` | 上游不可用或返回结构不符 |
| `client.RateLimiter` / `client.Cache` | 串行限速（≥1.2s）与磁盘缓存 |
| `operator.fetch_operator(name)` / `fetch_operator_by_id(char_id)` | 取一个干员 |
| `operator.list_operators()` / `all_operator_names()` | 干员名录（走 Cargo，一次请求拿全表） |
| `operator.parse_operator(wikitext, *, name='')` | 解析干员页 wikitext |
| `operator.Operator` / `Stats` / `Talent` / `Skill` / `SkillLevel` / `Module` | 干员页模型 |
| `enemy.load_all(client=…)` / `fetch_enemy_pages(titles, …)` / `all_enemy_titles(…)` | 敌人页全量取数 |
| `enemy.parse_page(page, wikitext)` | 解析一个敌人页 → `PrtsEnemy` |
| `enemy.parse_blackboard(comments)` / `strip_comments` / `extract_comments` / `template_params` / `resolve_fixes` / `parse_aliments` | 模板与黑板的解析原语 |
| `enemy.PrtsEnemy` / `EnemyLevel` | 敌人页模型 |
| `grid.parse_svg(code, svg)` / `grid.AttackRange` / `grid.merge_ranges(ranges)` | 攻击范围 SVG 解析（PRTS 侧，常年 403，实际走 gamedata） |
| `ranges.RangeRegistry` / `ranges.fetch_range(code)` | 代号 → 攻击范围的两级缓存 |
| `wikitext.*` | wikitext 原语：`iter_templates` / `find_templates` / `template_name` / `parse_params` / `split_top_level` / `split_multi` / `render` / `render_flat` / `to_number` |

### 4.4 `ak_tactic.operator` —— 干员属性与技能

| 名字 | 说明 |
| --- | --- |
| `stats.OperatorCalculator` | 属性计算器：等级插值 + 信赖 + 潜能 + 模组 |
| `stats.OperatorStats` | 一次计算的完整结果（四份来源分开留着） |
| `stats.interpolate_keyframes(frames, level, *, rounding='floor')` | 关键帧之间线性插值 |
| `stats.parse_rarity(value)` | `"TIER_5"` → 5 |
| `stats.OperatorError` | 查不到干员、等级越界、数据源缺表 |
| `skill.SkillBook` | 技能数据读取入口 |
| `skill.OperatorSkill` / `SkillLevel` / `SkillEffects` | 技能槽 / 某等级 / 解释后的效果 |
| `skill.parse_effects(bb, duration_type='NONE')` | 把黑板归类进四个箱子——**技能与天赋共用这一个入口** |
| `skill.resolve_index(level=7, mastery=0)` | （技能等级, 专精）→ `levels` 下标 |
| `skill.render_description(text, blackboard)` / `format_value(value, spec='')` | 把 `攻击力<@ba.vup>+{atk:0%}</>` 渲染成人话 |
| `talent.TalentBook` / `talent.Talent` | 按练度取天赋 |
| `talent.resolve_talents(char, *, elite=2, level=1, potential=1)` | 挑出真正生效的天赋（每组最多一条） |
| `talent.talent_candidates(char)` | 摊平成候选列表 |
| `attack_speed.attack_speed_bonus(calc, char_id, *, elite=2, level=1, potential=1, module=…)` | 天赋 + 模组的**常驻**攻速加成 |
| `attack_speed.talent_attack_speed(...)` / `module_attack_speed(...)` | 两个来源分开取 |
| `attack_speed.AttackSpeedBonus` | `(flat, when_free, sources)` |

### 4.5 `ak_tactic.battle` —— 战斗模型

| 名字 | 说明 |
| --- | --- |
| `damage.resolve_damage(atk, *, damage_type=PHYSICAL, scale=1.0, defense=0.0, res=0.0, ignore_defense=0.0, ignore_res=0.0, defense_reduce=0.0, res_reduce=0.0, fragile=0.0, final_multiplier=1.0)` | 一次伤害结算 |
| `damage.physical(atk, defense, **kw)` / `arts(atk, res, **kw)` / `true_damage(atk, **kw)` | 三个简写 |
| `damage.DamageResult` | 一次结算的完整账（`raw` / `final` / `floored` / `mitigated` / `type`；`.value` 是面板值） |
| `damage.DamageType` | `PHYSICAL` / `ARTS` / `TRUE` / `HEAL` |
| `range.normalize_direction(direction)` | `right` / `R` / `右` → 四个标准朝向 |
| `range.normalize_cells(cells, self_cell)` | 把格集合平移到「自身格 = (0,0)」 |
| `range.rotate_cells(cells, direction)` / `range.footprint(cells, direction, origin)` | 旋转 / 落到绝对格 |
| `range.RangeProvider` | 干员 + 精英阶段 + 朝向 + 位置 → 实际攻击格集合 |
| `unit.Combatant` / `OperatorUnit` / `EnemyUnit` | 能挨打能出手的东西 / 我方 / 敌方 |
| `unit.path_length(points)` / `unit.point_at(points, travelled)` | 折线长度 / 沿折线走 t 格后的位置 |
| `sim.BattleSimulator` | 关卡模拟器：`.plan(Deployment)` / `.use_skill(pos, time)` / `.retreat(pos, time)` / `.run(max_time=600.0)` |
| `sim.Deployment` / `sim.SkillUse` | 一次部署 / 一次手动开技能 |
| `sim.BattleResult` | `won` / `life` / `kills` / `leaks` / `elapsed` / `deployed` / `damage_dealt` / `operator_deaths` / `skill_activations` / `log` / `leak_events` / `effect_source_used` / `effect_conflicts` |
| `sim.make_total_attack(stage)` | 关卡里有没有「全场总攻击」装置 |
| `p3r.BreakState` | 击破值计量与倒地状态（`.add(dealt, affinity, t)` 按**实际掉血量**累积） |
| `p3r.TotalAttackDevice` | 全场总攻击装置（`.trigger_value(ally_atk_sum)` / `.tick(...)`） |
| `p3r.damage_slot(damage_type)` / `p3r.affinity_multiplier(affinity, *, immune_blocks_damage=True)` | 伤害落到哪个相性槽 / 相性倍率 |
| `talents.find_sp_on_action(talents)` / `find_regen` / `find_team_aura` / `find_snow` | 四类已建模的天赋机制 |
| `talents.TeamAura` / `RegenAura` / `SnowField` / `SpOnAction` | 光环 / 增益治疗 / 雪 / 情绪吸收 |
| `talents.squad_cost_bonus(talents)` | 「编入队伍额外获得 N 点初始费用」 |

### 4.6 `ak_tactic.formula` 与 `enemy_formula` —— 正文 → 公式项

| 名字 | 说明 |
| --- | --- |
| `formula.parse(text, blackboard=…, *, rules=…, extra=…)` | 主入口：一条描述 → `[Term]` |
| `formula.normalize(text)` | 剥标签、占位符换哨兵 → `(文本, [(键, 说明符)])` |
| `formula.parse_arith(src)` / `formula.find_exprs(text)` | 算式解析器（两支语料共用） |
| `formula.render(terms)` / `formula.formulas(terms, *, name='')` | 人读行 / `{公式名: 表达式}` |
| `formula.effects_from_terms(terms)` | 公式项 → `FormulaEffects` 读数 |
| `formula.compare_effects(bb, desc)` / `formula.merge_effects(bb, desc, *, policy='merge')` | 黑板 vs 描述对账 / 合并 |
| `formula.load_corpus(db)` / `formula.scan(db, *, top=…)` / `formula.describe_row(db, key)` | 全库语料 / 覆盖率统计 / 单条报告 |
| `formula.Num` / `Term` / `Rule` / `Expr` / `FormulaEffects` / `Difference` | 模型类 |
| `enemy_formula.detemplate(text)` | PRTS wikitext → 纯文本 |
| `enemy_formula.parse_enemy(text, blackboard=…)` | 敌人侧主入口 |
| `enemy_formula.formulas_enemy(text, blackboard=…, *, name='')` | 敌人侧的 `formulas` |
| `enemy_formula.enemy_formulas(db, key)` | **一个敌人的全部公式项报告**（调试首选） |
| `enemy_formula.enemy_scan(db, *, rules=…)` | 全量语料命中率统计 |
| `enemy_formula.load_enemy_corpus(db)` / `expr_terms(flat, used)` / `CorpusRow` | 语料 / 算式钩子 / 语料行 |

> **命令行入口**：干员侧 `python -m ak_tactic formula`（见 3.11），
> 敌人侧 `python -m ak_tactic enemydb formula`（见 3.10）。
>
> **要改这一层，先读 [`formula-maintenance.md`](formula-maintenance.md)。**

### 4.7 `ak_tactic.db` —— 两个库

| 名字 | 说明 |
| --- | --- |
| `api.connect(path=…)` / `api.db_info(conn)` | 打开干员库（默认只读）/ 版本与行数 |
| `api.find_operators(conn, keyword, *, limit=20, operators_only=True)` | 找干员（空关键词 = 全部） |
| `api.char_detail(conn, key)` | 一个干员的完整战斗数据 |
| `api.skill_levels(conn, skill_id)` | 一个技能的十个等级 |
| `api.search_skills(conn, keyword, *, limit=30, blackboard_key='')` / `api.search_talents(...)` | 按名字/描述搜，或按黑板键搜 |
| `api.run_sql(conn, query, *, limit=200)` | **只读** SQL |
| `build.build_db(path=…)` / `build.BuildReport` | 重建干员库 |
| `enemy_api.connect_enemy(path=…)` / `enemy_db_info` / `find_enemies(conn, keyword, *, limit=30, grade='')` / `enemy_detail(conn, key)` / `effective_resists(conn, page, level=…)` / `enemy_sql(...)` | 敌人库查询 |
| `enemy_build.build_enemy_db(path=…)` / `EnemyBuildReport` | 从 prts.wiki 重建敌人库 |
| `tiles.fetch_tile_info(*, cache_dir=…)` / `current_build_id(*, timeout=45.0)` / `insert_tiles(conn, tiles)` / `load_tiles(conn)` / `tile_name(conn, tile_key)` | 地块字典（theresa.wiki） |
| `store.open_db(path=…)` / `store.db_info(conn, *, expected_version)` / `store.rows(conn, sql, params=())` / `store.run_readonly_sql(...)` | 两库共用的连接与只读守卫 |
| `store.DatabaseMissing` / `tiles.TileTableError` | 库缺失 / 地块字典取不到 |

### 4.8 `plan` / `verify` / `search` / `team` / `eta` / `diagram` —— 打法与求解

| 名字 | 说明 |
| --- | --- |
| `plan.Plan` | 一份完整打法：`stage` / `deploys` / `retreats` / `skills` / `title` / `notes` |
| `plan.DeployOrder` | `operator` / `position` / `direction='Right'` / `skill=0` / `mastery=0` / `elite` / `level` / `potential` / `trust` / `module` / `module_level` / `time` / `auto_skill=True` |
| `plan.RetreatOrder` | `operator` / `time` |
| `plan.SkillOrder` | `operator` / `time` / `slot=0` |
| `plan.Roster` | 练度表：名字 → `{char_id, elite, level, potential, module, module_level}` |
| `plan.PlanError` | 打法文件有问题——**必须是硬错误**，静默纠正一个错坐标会产出假结果 |
| `verify.verify(plan, *, roster=…)` | 跑一次验证 → `Verdict` |
| `verify.Verifier` | 可复用的验证环境（省去每次重建的慢） |
| `verify.stars_of(won, leaks)` | 三星判定 |
| `search.search(stage_id, roster, operators, **kw)` | 一次性搜索入口 |
| `search.Searcher` / `search.Candidate` / `search.SearchResult` | 两层搜索器 / 候选落位 / 结果（`plan is None` = 没找到三星方案） |
| `search.candidates_for(verifier, stage_id, roster, operators, *, index=…)` | 给每个干员挑最值钱的落位 × 朝向 |
| `team.suggest(roster, *, conn=…)` | 组一份建议队伍 → `TeamSuggestion` |
| `team.dp_vanguards(roster, conn)` / `bait_units(roster, conn, *, max_cost=…)` / `low_cost_pick(...)` | 回费先锋 / 骗伤处决者 / 低费位 |
| `team.cost_delay(cost, …)` / `stage_cost_env(level_id)` / `low_cost_env(level_id, …)` | 费用环境与落地延迟 |
| `team.Pick` / `TeamSuggestion` | 一个被推荐的人（含理由）/ 一份建议 |
| `eta.enemy_arrivals(stage, enemy_at, *, speed_scale=1.0, plans=…)` | 每只敌人从入场到终点的全过程 |
| `eta.route_plans(stage)` / `eta.leading_wait(route)` / `eta.enemy_speed(...)` | 路线可执行形态 / 开头的待命秒数 / 推进速度 |
| `eta.ArrivalIndex` | 按格反查「什么时候有敌人经过」与「待了多少敌人·秒」 |
| `eta.EnemyArrival` / `RoutePlan` / `Visit` | 到达记录 / 路线计划 / 某格占用时段 |
| `diagram.placement_diagram(stage, plan=None, *, verdict=…, show_range=True, show_enemy=False, index=…)` | 摆位图 |
| `diagram.route_heat(stage, *, index=…)` | 路线热度图 |
| `diagram.timeline_table(stage, plan=None, *, verdict=…, from_eta=True, …)` | 时间轴表 |
| `diagram.battle_report(stage, plan=None, *, title='', route_metric='dwell', …)` | 完整报告 |

---

## 五、`tools/` 脚本接口（23 个）

全部以 `python tools/<脚本>.py [参数]` 调用。**退出码 0 = 全绿，1 = 有失败项。**

### 自检（11 个）

| 脚本 | 查什么 |
| --- | --- |
| `check_db.py` | 干员库完整性与一致性 |
| `check_enemy_db.py` | 敌人库完整性与一致性 |
| `check_battle.py` | 战斗与技能回归（含三条基线） |
| `check_p3r.py` | 伤害相性 / 击破值 / 倒地 / 全场总攻击 |
| `check_formula.py` | 干员侧公式：锚点、覆盖率、量纲不变量、结算层、序列化冒烟（`-v` 详细） |
| `check_enemy_formula.py` | 敌人侧公式：清洗、语料、锚点、量纲、精度守卫、覆盖率（含与编译器逐行同口径）、算式 |
| `check_verify.py` | 通用验证器 |
| `check_search.py` | 搜索器 |
| `check_eta.py` | 敌人到达时刻 |
| `check_diagram.py` | 输出层：摆位图、热度图、时间轴、报告 |
| `selftest.py` | 抽样把解析器拉到全库上跑（`-n` / `--all` / `--seed` / `--with-range` / `--profession` / `--rarity`） |

**⚠️ `check` 的签名有三个版本，写反不会报错、只会静默空转：**
`check_formula.py` 是 `check(ok, label, detail)`；`check_enemy_formula.py`、`check_db.py`、
`check_battle.py`、`check_verify.py`、`check_search.py`、`check_eta.py`、`check_diagram.py`、
`check_enemy_db.py` 是 `check(label, ok, detail)`；`check_p3r.py` 是 `check(label, got, want)`。
**加自检前先看那个文件的签名。** 条数以各脚本末尾打印的汇总行与 `README` 的总表为准。

### 试跑与导出（4 个）

| 脚本 | 参数 | 用途 |
| --- | --- | --- |
| `run_sr6.py` | — | SR-6 模拟 + 三档练度对照 |
| `run_srx8.py` | `--verbose` `--rank` `--check` | SR-EX-8 试跑台（P3R 与总攻击情况） |
| `search_srx8.py` | `--team` `--top` `--min-cover` | SR-EX-8 落位贪心搜索 |
| `export_srx8.py` | `--plan` `--verbose` | 导出 **MAA copilot JSON** 供实机对照 |

### 取数与审计（6 个）

| 脚本 | 参数 | 用途 |
| --- | --- | --- |
| `skland.py` | `status` / `did` / `send-code` / `login` / `cred` / `fetch` / `opers` / `selftest`（`--home` `--uid` `--full`） | 森空岛取数：**专精与模组等级**的唯一权威来源 |
| `skland_did.py` | `--home` `--fresh` | 生成森空岛要求的真实设备指纹 dId（**唯一需要 `pycryptodome` 的地方**） |
| `roster.py` | `--uid` `--squad` | 名册 → 算符可直接吃的口径，并出人读清单 |
| `unit_audit.py` | `--db` `--out` `--stdout` | 生成 `docs/formula-units.md`（量纲裁定台账，**最后一栏由人填**） |
| `uncertainty_audit.py` | `-o` | 生成 `docs/uncertainties.md`（待裁定清单，同上） |
| `enemy_field_audit.py` | `--pages` `--verbose` | 敌人页字段总账（退出码非 0 即有字段没入库） |

### 库（不单独运行）

| 脚本 | 用途 |
| --- | --- |
| `operbox_path.py` | 定位 MAA OperBox 导出：先认环境变量 `AK_OPERBOX`，缺省 `data/operbox/Arknights_OperBox_Export.json` |
| `squad.py` | 从森空岛名册造干员：把真实专精、模组、信赖接进模拟器 |

---

## 六、交换文件

### 6.1 打法 JSON（`Plan`）

由 `plan.Plan` 序列化，字段即 dataclass 字段名：

```json
{
  "stage": "act54side_ex08",
  "title": "四人剑气方案",
  "notes": "…",
  "deploys": [
    {"operator": "赤刃明霄陈", "position": [4, 6], "direction": "Left",
     "skill": 2, "mastery": 3, "elite": 2, "level": 60, "potential": 2,
     "module": "uniequip_002_chen3", "module_level": 3, "time": 10.0,
     "auto_skill": true}
  ],
  "retreats": [{"operator": "…", "time": 120.0}],
  "skills":   [{"operator": "…", "time": 45.0, "slot": 0}]
}
```

* `position` 是 **MAA 坐标** `[x, y]`，原点左上、y 向下。
* `skill` 是技能槽下标（0 = 一技能）。
* `auto_skill: false` 的干员**不会自动开技能**，必须在 `skills` 里给出时刻。
* `PlanError` 对这一层是**硬错误**：坐标写错宁可报错，不静默纠正。

### 6.2 名册 JSON

两种都被接受（`--box`）：

| 来源 | 内容 | 说明 |
| --- | --- | --- |
| MAA OperBox 导出 | `{id, name, elite, level, own, potential, rarity}` | **没有专精、没有模组** |
| 森空岛名册（`tools/roster.py` 产出） | 加上 `specializeLevel`、`equip[].level`、`favorPercent` | 唯一有专精与模组的来源 |

`Roster` 是查表形态：名字 → `{char_id, elite, level, potential, module, module_level}`。

> 两个标度坑：`favorPercent` 是 **0–200**（200 = 满信赖）；`potentialRank` **0 起算**，显示潜能 = rank + 1。

### 6.3 MAA copilot 导出（`export_srx8.py`）

`requirements` 字段的口径（实机核过）：

* `module` 是模组的**类型编号** X/Y/Z → **1/2/3**（取 `uniequip_table` 的 `typeName2` 字母），**不是** id 里的序号。
* **没有生效模组的干员必须整个省略 `module` 键**；写 `0` 会让 MAA 不识别**整份作业**。
* 键序：`elite → level → skill_level → module → potential`。
* `module_level` / `potential` 在协议里属「保留接口，暂未实现」，机器不校验，须写进 `doc.details`。

### 6.4 报告文件

`verify --report <路径>` 或 `diagram.battle_report(...)` 产出 markdown：
摆位图 + 路线热度图 + 时间轴 + 战报（含漏怪归因与装置触发）。

---

## 七、环境变量

| 变量 | 作用 |
| --- | --- |
| `AK_OPERBOX` | OperBox 导出的路径（覆盖默认 `data/operbox/Arknights_OperBox_Export.json`） |
| `SKLAND_HOME` | 森空岛凭据目录（默认 `~/.skland`） |
| `PYTHONIOENCODING=utf-8` | **中文 Windows 必需**：控制台默认 GBK，输出含 `−`（U+2212）等字符时会 `UnicodeEncodeError` |
| `HTTP_PROXY` / `HTTPS_PROXY` / `NO_PROXY` | 取数走代理时用。注意 `NO_PROXY` 里**不要含带冒号的 IPv6 字面量**（httpx 会解析失败） |

---

## 八、错误与退出码

| 场景 | 表现 |
| --- | --- |
| 查不到干员/敌人/关卡 | 打印一句能照做的提示，退出码 1（**不抛栈**） |
| 库文件不存在或结构版本不符 | `DatabaseMissing`，提示先跑 `db build` |
| 数据源缺表（如 `excel/` 只在 GitHub 镜像有） | `GamedataError`，提示换镜像 |
| prts.wiki 403 / 限速 | `PrtsError`，客户端已内置重试与 ≥1.2s 串行限速 |
| 打法文件非法 | `PlanError`，**硬错误** |
| 自检有失败项 | 打印失败清单，退出码 1 |

---

## 九、文档索引

| 文档 | 讲什么 |
| --- | --- |
| **本文** | 全部接口怎么调用 |
| [`formula-maintenance.md`](formula-maintenance.md) | 公式子系统：维护者操作手册 |
| [`formula-model.md`](formula-model.md) / [`enemy-formula.md`](enemy-formula.md) | 干员侧 / 敌人侧的公式调研记录 |
| [`operator-db.md`](operator-db.md) / [`enemy-db.md`](enemy-db.md) | 两个库的表结构 |
| [`stage-1-7.md`](stage-1-7.md) / [`stage-sr-ex-8.md`](stage-sr-ex-8.md) / [`stage-sr-6.md`](stage-sr-6.md) | 三关的实测报告 |
| [`uncertainties.md`](uncertainties.md) / [`formula-units.md`](formula-units.md) | 待裁定清单 / 量纲裁定台账（两份都**由人回填**） |
| [`../THIRD-PARTY.md`](../THIRD-PARTY.md) | 第三方来源、许可与合规 |
| [`../README.md`](../README.md) | 项目总览与三条战斗基线 |
