# MAA 地块 JSON 独立第三源交叉校验

- 生成时间：2026-09-19 23:19:10；执行者：验收与守卫会话 `session-1a45cfee-9a65-4830-a327-03ac84285bfb`
- 第三源：本机 MAA 资源目录的 `Arknights-Tile-Pos\`（**只读**；本回合实测 **4203 份** `.json`；其数据不入仓、不进报告正文）
- 我们侧：`data/gamedata/levels/**/level_*.json` 经 `ak_tactic.gamedata.stage.load_stage()`（**只读**；地图层不是我的单写者文件，发现分歧只报不改）

## 一、计数（先说清「数了谁」）

- 第三源目录下**地块 JSON 4203 份**（本回合实测；逐份都是关卡图）
- 去重后**唯一关卡 3141**（同 id 多份 1062 关：其中**内容不同** **1062** 关——`act1multi_*` 一类是多难度变体，**不是重复文件**，本工具全部留下当候选）
- 我们侧**本地缓存** 105 份 → 去重 **83 关**（`GameDataSource` 是**按需下载**，磁盘上只有跑过的关；**这不是我们的关卡全集**）
- **交集 80 关**（下面逐关比的就是这些）；只有第三源有 **3061** 关；只有我们有 **3** 关

**同一关多镜像缓存内容不一致**（21 关，按**语义**比、键序空白不算差）——镜像之间也会打架：

- `a001_01`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_01.json；raw.githubusercontent.com/levels/activities/a001/level_a001_01.json
- `a001_02`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_02.json；raw.githubusercontent.com/levels/activities/a001/level_a001_02.json
- `a001_03`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_03.json；raw.githubusercontent.com/levels/activities/a001/level_a001_03.json
- `a001_04`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_04.json；raw.githubusercontent.com/levels/activities/a001/level_a001_04.json
- `a001_05`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_05.json；raw.githubusercontent.com/levels/activities/a001/level_a001_05.json
- `a001_06`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_06.json；raw.githubusercontent.com/levels/activities/a001/level_a001_06.json
- `a001_ex01`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_ex01.json；raw.githubusercontent.com/levels/activities/a001/level_a001_ex01.json
- `a001_ex02`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_ex02.json；raw.githubusercontent.com/levels/activities/a001/level_a001_ex02.json
- `a001_ex03`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_ex03.json；raw.githubusercontent.com/levels/activities/a001/level_a001_ex03.json
- `a001_ex04`（mapData.tiles 逐格不同 0 格）：map.ark-nights.com/levels/activities/a001/level_a001_ex04.json；raw.githubusercontent.com/levels/activities/a001/level_a001_ex04.json

> 这 16 关的差异**不在 `mapData.tiles` 上**（逐格 0 格不同）⇒ **与本条判据无关**；但**镜像之间确实不同**这件事仍要登记——别的层（路线/出怪/机制读的是同一份 JSON）引用时得知道自己在读哪一份。

> ⚠ 「交集只有几十关」是**我们本地缓存稀疏**所致，**不是**「我们的地图少」——两个方向的读数都必须先看覆盖口径。**总数什么都证明不了**，下面逐关分歧才是结论。

**去重口径**：关卡 id 取文件名里**最后那个 `level_<id>` 段**（**不许按第一个 `-` 切**——那样会把 `main_01-01`…`main_01-07` 塌成 `main_01`，整族 `main_*` 被静默排除；这条是**抽样人工复核**抓出来的：1-7 被报成「第三源没有这一关」）。带 `#f#` 的与不带的是**同一关的两份**；同 id 多份**不丢**——逐份比，取**最接近**的那份为结论，并报出「该关它有几份、最接近的是第几份」。

## 二、取值映射（**实测出来的，不是猜的**）

| MAA | 我们 | 判据 |
| --- | --- | --- |
| `buildableType` 0 / 1 / 2 | `NONE` / `MELEE` / `RANGED` | `main_01-07` 计数 38 / 23 / 16 与逐格比对同时吻合 |
| `buildableType` **3** | **`ALL`** | `act31side_ex05` 上 **33 格一一同位对上**（第一版没写这一条 ⇒ 当场「报出 33 格分歧」，而那 33 格恰好就是我们的 `ALL` 格） |
| `heightType` 0 / 1 | `LOWLAND` / `HIGHLAND` | 31 / 46 逐项吻合 |
| `tileKey` | `Tile.key` | 同名同义（`tile_forbidden` 等） |

**它那套 `isStart` / `isEnd` 不比**（另一层概念，不是 `tile_start`/`tile_end`）：实测我们的 `tile_start` 格**总是它 `isStart` 的真子集**——`act31side_07` **2 vs 10**、`act31side_ex03` **3 vs 9**，且差集落在普通路面格上。它标的是**路线端点**（含路面），要真比得拿**我们的路线层**去对 ⇒ **本轮登记为未覆盖**，**不拿它凑地块分歧**（否则会出现「概念不同」被记成「地图不一致」的假红）。

## 三、朝向（不靠猜：用同概念的起点/终点格实测）

- 两边都是 `tiles[y][x]`（原点左上、y 向下），且**同概念**对齐（都取 `tileKey == tile_start/tile_end`）。实测 **72/72** 关的起点格完全一致 ⇒ **同向，未翻转**。
- **没有一关**起点格不一致。

> ⚠ 这一节第一版是错的：我用 `find("start")` 取我们的起点格——`find()` 按 **tileKey 精确匹配**，于是返回**空**，34/34 关全被报成「起点不一致」。**发现它的路是仪器自相矛盾**：同一份地图的 key 分布里明明有 `tile_start × 3`。教训：**「它和我不同」与「我读错了」长得一模一样**，判据先要自己不打架。

## 四、总账

比了 **72** 关（交集里全部）：**完全一致 72**、有分歧 **0**、我们侧加载失败 8。

**分歧类型（按关计数）**：无

## 五、逐关分歧

| 关卡 | 尺寸（我们/它） | 分歧类型 | 前几格（x, y, 我们, 它） |
| --- | --- | --- | --- |

**我们侧加载失败 8 关**（⇒ 这 8 关**本轮未跑**，不是「一致」也不是「不一致」）：

- `act31side_sub-1-1`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/act31side/level_act31s
- `act31side_sub-1-2`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/act31side/level_act31s
- `act31side_sub-1-3`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/act31side/level_act31s
- `act31side_sub-1-4`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/act31side/level_act31s
- `act3d0_01`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/act3d0/level_act3d0_01
- `sandbox1_01`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/sandbox1/level_sandbox
- `sandbox1_02`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/sandbox1/level_sandbox
- `sandbox1_03`：GamedataError: 镜像里没有这个文件：https://map.ark-nights.com/data/levels/obt/sandbox1/level_sandbox

> 给**后端**的线索（**只报不改**）：这 8 关在本机的 `stage` 表里**查不到**（`level_id like 'act31side_sub%'` / `'act3d0_0%'` **零行**），而磁盘上却**有**对应的地图文件（如 `map.ark-nights.com/levels/activities/act31side/level_act31side_sub-1-1.json`）⇒ **「本机有地图文件」≠「我们索引里有这一关」**，本报告的覆盖计数按**前者**算，引用时请注意这个口径差。

## 六、抽样人工复核（至少 5 关，含 1-7 与我们已有定论的 SR-EX-8）

做法：把两边**同一概念**渲染成同一套字符网格（`可部署首字母 + 高低地首字母`，N/M/R/A + L/H），**逐行肉眼对照**。朝向或单位一旦错位，网格会立刻错开——所以这一节是**给人看的**，不是脚本自说自话。

### `main_01-07`（11×7，154 格；取它第 1/2 份）

逐格比对：**完全一致**（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）

```
我们：
NHNHNHNHNHNHNHNHNHNHNH
NHRHRHRHMLMLMLMLMLNLNL
NHRHMLMLMLRHRHRHRHNHNH
NLMLMLNLMLMLMLMLMLNLNL
NHRHMLMLMLRHRHRHRHNHNH
NHRHRHRHMLMLMLMLMLNLNL
NHNHNHNHNHNHNHNHNHNHNH
它：
NHNHNHNHNHNHNHNHNHNHNH
NHRHRHRHMLMLMLMLMLNLNL
NHRHMLMLMLRHRHRHRHNHNH
NLMLMLNLMLMLMLMLMLNLNL
NHRHMLMLMLRHRHRHRHNHNH
NHRHRHRHMLMLMLMLMLNLNL
NHNHNHNHNHNHNHNHNHNHNH
```

### `act31side_ex08`（13×8，208 格；取它第 1/2 份）

逐格比对：**完全一致**（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）

```
我们：
NHNHNHNHNHNHNHNHNHNHNHNHNH
NHRHRHNHNLNLMLMLMLMLRHMLNL
NHNLNLRHNLNLMLRHMLMLMLMLNH
NHNLNLRHNLNLMLRHMLRHRHMLNH
NHMLMLNHNLNLMLMLMLMLMLMLNH
NHNLNLRHNHNHRHNHRHRHNHMLNH
NHMLMLMLMLNLMLMLNLMLMLNLNH
NHNHNHNHNHNHNHNHNHNHNHNHNH
它：
NHNHNHNHNHNHNHNHNHNHNHNHNH
NHRHRHNHNLNLMLMLMLMLRHMLNL
NHNLNLRHNLNLMLRHMLMLMLMLNH
NHNLNLRHNLNLMLRHMLRHRHMLNH
NHMLMLNHNLNLMLMLMLMLMLMLNH
NHNLNLRHNHNHRHNHRHRHNHMLNH
NHMLMLMLMLNLMLMLNLMLMLNLNH
NHNHNHNHNHNHNHNHNHNHNHNHNH
```

### `act31side_07`（10×8，160 格；取它第 1/1 份）

逐格比对：**完全一致**（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）

```
我们：
NHNHNHNHNHNHNHNHNLNH
NLMLMLMLMLMLRHNHMLNH
NHNHRHRHRHMLMLRHMLNH
NLMLMLMLMLMLMLRHMLNH
NHMLMLMLMLMLMLRHMLNH
NHRHRHNHRHRHMLMLMLNH
NLMLMLMLMLMLMLMLMLNH
NHNHNHNHNHNHNHNHNHNH
它：
NHNHNHNHNHNHNHNHNLNH
NLMLMLMLMLMLRHNHMLNH
NHNHRHRHRHMLMLRHMLNH
NLMLMLMLMLMLMLRHMLNH
NHMLMLMLMLMLMLRHMLNH
NHRHRHNHRHRHMLMLMLNH
NLMLMLMLMLMLMLMLMLNH
NHNHNHNHNHNHNHNHNHNH
```

### `a001_01`（10×7，140 格；取它第 1/1 份）

逐格比对：**1 格不同**（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）

```
我们：
NHNHNHNHNHNHNHNHNHNH
NHNHRHMLMLMLMLNLNLNL
NLMLMLMLRHMLNHNHRHNH
NHRHMLMLMLMLNLNLNLNL
NHNHRHNHRHMLNLNLNLNH
NLMLMLMLMLMLNLNLNLNL
NHNHNHNHNHNHNHNHNHNH
它：
MHNHNHNHNHNHNHNHNHNH
NHNHRHMLMLMLMLNLNLNL
NLMLMLMLRHMLNHNHRHNH
NHRHMLMLMLMLNLNLNLNL
NHNHRHNHRHMLNLNLNLNH
NLMLMLMLMLMLNLNLNLNL
NHNHNHNHNHNHNHNHNHNH
```

### `act31side_ex05`（12×8，192 格；取它第 1/2 份）

逐格比对：**完全一致**（人工核对：两边行数与每行宽度相同，第 0 行左端起字符相同 ⇒ 无翻转、无列偏移）

```
我们：
NHNHNHNLNHNHNHNHNHNHNHNH
NHNHALALNHALNHALNHNHNHNH
NHALALALALALALALALALNLNL
NLALALALALALALALALALNLNL
NHALALALALALALNHNHNHNHNH
NHNHALALALNHALALNLNLNHNH
NHNHNHNLNHNHNHNHNHNHNHNH
NHNHNHNHNHNHNHNHNHNHNHNH
它：
NHNHNHNLNHNHNHNHNHNHNHNH
NHNHALALNHALNHALNHNHNHNH
NHALALALALALALALALALNLNL
NLALALALALALALALALALNLNL
NHALALALALALALNHNHNHNHNH
NHNHALALALNHALALNLNLNHNH
NHNHNHNLNHNHNHNHNHNHNHNH
NHNHNHNHNHNHNHNHNHNHNHNH
```

## 七、反向守卫（**判据先写死再跑**）

- 做法：把 `a001_01` 的 (0, 0) buildableType 0→1（1/1 份变体都改）（**只动这一格**），再跑一次全套比对，与**未改动的那一次** A/B 相差。
- 判据（先写死）：**只有那一关的 `buildable` 分歧集恰好多了那一格，其它关一切不动**。➜ ✅ 成立
- A/B 实测差异：`[('a001_01', "新增 {'buildable': [(0, 0)]}｜消失 {}")]`

> ⚠ 这里**不能**用「恰好 1 关红」当判据：本轮比对里本来就可能存在真分歧（第一版就吃过这个亏：当时 `a001_01` 与 `act31side_ex05` 都「有分歧」，而那两处**全是我自己读错**，见第九节）。判据必须建立在「与未改动那一版的**差值**」上。

## 九、工具自身的三处自纠（**这一条比结论更重要**）

本轮这条比对**第一版报了 34 关分歧，全是假的**。三处成因各不同，全部记在这里，因为它们正是「它错了」与「我读错了」同形的三种典型：

| # | 我第一版的写法 | 症状 | 真根因 | 修法 |
| --- | --- | --- | --- | --- |
| 1 | `m.find("start")` 取我们起点格 | **34/34 关**都「起点不一致」 | `find()` 按 **tileKey 精确匹配**，`"start"` 匹配不到 `tile_start` ⇒ 返回**空** | 改成 `find("tile_start")`；并让**仪器自相矛盾**成为检查项（key 分布里有 3 个 `tile_start` 却报 0 个起点） |
| 2 | 映射表只写 `buildableType` 0/1/2 | `act31side_ex05` **33 格分歧** | 漏了第四取值：它的 **3 ↔ 我们的 `ALL`**（33 格一一同位） | 补进映射表；并在工具里写死「**对不上的取值原样报出来，不许拿最像的去凑**」 |
| 3 | 守卫在基线之前就改了数据 | 守卫报「❌ 没红」 | 两次跑的都是**改过的那份**，A/B 恒等 | 顺序改成**先跑基线 → 再改 → 再跑**；并**结论只取未改动那一版**（否则守卫自己的改动会污染结论，凭空多出「某关 1 格分歧」） |

> 三条的共同教训：**判据要先能证明「它红得起来」，再谈它绿得可不可信**；而「红得起来」本身还要分两层——**先敏感性**（改坏一处，红不红）、**再控制组**（不改的时候红不红、红的到底是什么）。

## 十、边界（本条不覆盖什么）

- 比的是**地块层**（尺寸/可部署/高度/地块键/起点终点格），**不比**出怪表、路线、装置、机制——那些不在这一层里。
- 它那套 `isStart`/`isEnd`（**路线端点**）**本轮没比**：要拿我们的**路线层**去对，属未覆盖项（见第二节的实测理由）。
- 「一致」只说明**两个来源互相印证**，**不等于**「地图层一定对」：若两源同错（同源的错误抄写），本条看不见。
- 覆盖面上：**交集只有几十关**是因为我们本地只有跑过的关有缓存，**不是**我们的地图少；反过来，只有第三源有的关卡也**不构成**我们的缺口。
