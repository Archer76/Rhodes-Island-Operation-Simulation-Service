# gamedata 数据源实测结论

> 本文件自 `README.md` 拆出（2026-09-17）：README 只留「是什么 / 怎么用」，实测结论与历史记录按主题收到这里。总览见 [`README.md`](../README.md)。

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
