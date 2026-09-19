# 数据源总台账（所有外部来源与博士交办的页面）

> 为什么单开这份：**来源本身就是资产**，而它最容易随上下文压缩丢掉。
> 本文件是索引，细节在各分主题文档里（见末节导航）。
> 记录日期：2026-09-19。

## 一、博士交办的页面（逐次记录，含从中拿到了什么）

| 日期 | 页面 | 交办口径 | 从中拿到的东西 | 取证留存 |
|---|---|---|---|---|
| 2026-09-19 | [`prts.wiki/w/游戏数据基础`](https://prts.wiki/w/游戏数据基础) | 「阅读这两个页面，可能有用」 | ① **修饰器四型**：`ADDTION` / `MULTIPLIER` / `FINAL_ADDITION` / `FINAL_SCALER`；② **最终属性** \(A_f=F_t[(A+D_p)(1+D_t)+F_p]\)；③ **最终乘算相乘**（各个 FINAL_SCALER 彼此相乘）；④「**倍率不是属性**」——倍率初始 1.0、同种倍率叠乘，「受到的法术伤害+55%」是**法术伤害倍率 155%**。这四条支撑了 `current_atk()`（只给面板）与 `resolve_damage(scale=)`（只在这里乘一次）的分工 | `tmp/prts/游戏数据基础.txt` |
| 2026-09-19 | [`prts.wiki/w/作战机制`](https://prts.wiki/w/作战机制) | 同上（与上页一起给） | ① 地块字段语义：`buildableType`（不可部署 / 仅近战 / 仅远程 / 全部）、`passableMask`（无 / 仅飞行 / 全部）；② §3.4.1 部署类型与合法部署行为；③ 地形 TAG；④ 顺着页内链接取到 `部署费用` 页（**注意**：源链接标题里含一个零宽空格，按名字直取会 404，要手工去掉） | `tmp/prts/作战机制.txt`、`tmp/prts/部署费用.txt` |
| 2026-09-19 | [`prts.wiki/w/敌人一览/数据`](https://prts.wiki/w/敌人一览/数据) | 「这个页面有寒冷减速多少的数据，可能也有其他有用内容」 | ① 页面内嵌**全敌人 JSON**：`enemyIndex / sortId / name / enemyLink / enemyRace / enemyLevel / attackType / damageType / motion / endure / attack / defence / moveSpeed / attackSpeed / resistance / enemyRes / enemyDamageRes / ability`；② 正文里 `mc-tooltips` 形如「词条 + 定义」的**机制词典 26 条**——解开了一批项目此前记为"拿不到"的数：**寒冷 = 攻击速度下降 30**（且「持续时间内再次受到寒冷则变为冻结」）、**冻结 = 敌方被冻结时法术抗性 −15**、**抵抗 = 异常状态持续减半 / 麻痹每 5 秒流失 1 层**、**停顿 = 移速降低 80%**、`屏障 / 脆弱 / 元素脆弱 / 浮空 / 麻痹 / 战栗 / 恐惧 / 迷彩 / 折射 / 近地悬浮 / 起飞 / 隐匿 / 沉睡 / 晕眩 / 束缚` 的定义，以及**五种元素损伤**（神经 / 侵蚀 / 灼燃 / 凋亡 / 狂躁）的 1000 阈值与各自结算 | `tmp/prts/敌人一览-数据.txt`、`tmp/prts/敌人tooltip词典.txt` |

由第三页派生的落地产物：`docs/mechanics-dictionary.md`（机制词典现状与实施顺序）。

> 取证留存目录 `../tmp/prts/` **在仓库之外**（第三方页面正文不入库），
> 需要时可按上表 URL 重抓；抓取方法与限速见第三节。

## 二、全部数据源

| # | 来源 | 入口 / 地址 | 拿到什么 | 硬约束 | 本地落点 | 抓取入口 |
|---|---|---|---|---|---|---|
| 1 | **prts.wiki** | `action=query&prop=revisions&rvslots=main`（唯一可靠的 wikitext 入口）、`action=parse&prop=wikitext`、`action=cargoquery`、`action=ask`(SMW) | 干员页（属性/天赋/技能/模组/范围代号）、敌人页（`分类:敌人` 约 1800 页）、**干员备注**、机制类页面（本文件第一节） | 必带浏览器 UA（裸 urllib 一律 403）；请求间隔 **≥ 1.2 s**；中文查询参数偶发 403（重试可过）；Cargo **只有 `chara_data`(461) 与 `chara`(460) 两张表**；SMW 稀有度 **0 起算** | `data/enemydb.sqlite`（敌人库）、`data/prts-notes.sqlite`（备注库 459 页 / 948 条）、`data/cache/prts/` | `ak_tactic/prts/client.py`（`PrtsClient`，进程级串行限速 + 403 重试）、`tools/fetch_prts_notes.py` |
| 2 | **map.ark-nights.com**（**第一选择**） | `https://map.ark-nights.com/data/...` | 关卡地图/路线/波次、敌人分档数值 `levels/enemydata/enemy_database.json`、**4694 条关卡索引**（编进 JS bundle，含 `levelId ↔ 关卡号`） | 索引没有独立端点，只能从 bundle 里扒（首页 → bundle → 最长字典）；缓存 7 天 TTL | `data/gamedata/map.ark-nights.com/`、`data/cache/_fetch_stats.json` | `ak_tactic/gamedata/`（`GameDataSource`，默认源） |
| 3 | **Kengxxiao/ArknightsGameData**（备选镜像） | `https://raw.githubusercontent.com/.../zh_CN/gamedata` | `excel/` 六张表（`character_table` / `uniequip_table` / `battle_equip_table` / `skill_table` / `range_table` / `char_patch_table`）；多一张 `excel/enemy_handbook_table.json`（敌人图鉴名与描述） | **`excel/` 只有这个镜像有**（ark-nights 不带）；两镜像文件路径同名，缓存必须**按域名分目录** | `data/gamedata/raw.githubusercontent.com/excel/` | `GameDataSource(base=GITHUB_BASE)` |
| 4 | **theresa.wiki** | 地图数据接口（其地图前端同源于 #3） | **地块字典 95 条**（`tile_floor`/`tile_forbidden`/`tile_infection`/`tile_empty`…）——`excel/tile_table.json` 与 `tile_data.json` 两镜像都 404，只能从这里取 | 站点自己的 `s3.` / `static.` 域名 **DNS 解析不了**，只能走接口；字典**不全**（`sandbox1_02` 的 `tile_xbdpsea` 缺，记在 `ak_tactic/db/tiles.py` 的 `KNOWN_GAPS`） | `data/cache/theresa/` | `python -m ak_tactic db tiles`、`db tile-fetch --force` |
| 5 | **xulai1001/akdata**（社区主力 DPS 计算器） | GitHub：`resources/dpsv2.js`、`npm/src/attributes.js`、`npm/customdata/dps_anim.json` | 伤害 / 攻速 / SP 三式的实现与帧数补正（可信度最高） | 与 wiki 冲突处以博士裁定为准（例：**攻速下限 wiki 写 20、akdata 写 10 → 取 20**） | —（对照用） | 见 `docs/formula-sources.md` |
| 6 | **wxhwwla/calc-framework** | GitHub：`framework/adapters/arknights/...`、`skill_parser.py` | 公式结构交叉验证 | 方舟部分较新、细节少于 #5 | —（对照用） | 同上 |
| 7 | **MAA OperBox 导出 / 森空岛名册** | 本地导出文件 | 玩家"有什么干员、什么练度"（名册） | MAA 不带专精与模组 ⇒ 模组信息必须走森空岛；模组编号取 `typeName2` 字母（`X/Y/A/D/B`→1-5，`Z` 是死项） | `data/operbox/`、`data/skland/` | `ak_tactic` 名册三来源按可信度退（见项目记忆） |
| 8 | **游戏本体 `enemy_database.json`** | 随 #2 / #3 一起下载 | 与 PRTS 解析结果**跨源对账**（两侧独立来源，一起错的概率远低于单侧错） | 字段是 Unity 序列化包装（`{"Key":…,"Value":…}`，`{"m_defined":…,"m_value":…}`） | `data/gamedata/*/levels/enemydata/` | `ak_tactic.gamedata.EnemyLibrary` |
| 9 | **prts.wiki `Widget:Range/*`** | 攻击范围 SVG（如 `Widget:Range/3-1`） | 攻击范围真图（`#1` 站位格、`#2` 覆盖格） | 坐标步长 26 px，描边有 1 px 补偿 ⇒ 用"除以步长四舍五入"吸附 | `data/ranges.json` | `ak_tactic/prts/`（两条取数路并存，见 `docs/prts-wiki.md`） |

## 三、抓取纪律（所有来源通用）

* **UA 必带**：`ak-tactic/0.1 (personal research)` 一类标识；裸请求会被 WAF 拦。
* **限速**：prts.wiki ≥ 1.2 s/请求，串行；并发直接吃 403。其它来源首次抓取后走本地缓存
  （prts 7 天、theresa 7 天、ark-nights 7 天）。
* **渲染页 vs wikitext**：需要**正文散文**时（如本文件第一节的词典）必须取**渲染后的 HTML**
  再剥标签——`{{子模板}}` 骨架里没有散文；需要**模板参数**时反过来取 wikitext。
* **零宽空格**：页面标题里可能夹 `U+200B`（如「部署费用和待部署区」），按名字直取会 404。
* **第三方正文不入库**：抓到的页面文本只留在 `tmp/` 下作取证，仓库里只放结论与出处。

## 四、本地落点一览

```
data/akdb.sqlite          25.3 MB  干员库（源 #3 的 excel/，建库不联网）
data/enemydb.sqlite       20.8 MB  敌人库（源 #1 的「分类:敌人」，建库要联网）
data/prts-notes.sqlite    0.9 MB   干员备注库（源 #1，459 页 / 948 条 / fact 3247 条）
data/op-briefs.txt        561 KB   备注语料展平（3249 行）
data/ranges.json          5.9 KB   攻击范围（源 #9）
data/gamedata/                     关卡与敌人本体（源 #2 / #3，按域名分目录缓存）
data/cache/{prts,prts_calc,theresa}/ 各来源的原始响应缓存
```

## 五、prts.wiki 全站检索：可用页面清单（2026-09-19）

检索方法（可复现）：`list=search` 24 个机制/数据关键词 ＋ `list=allpages` 17 个前缀
＋ `list=categorymembers` 7 个分类，去重后 **86 个命中页**。
脚本 `tmp/prts_sweep.py`，原始结果 `tmp/prts/全站检索.{txt,json}`。

### 5.1 已抓并已用上的（本轮新发现）

| 页面 | 大小 | 里面有什么 | 对我们的用途 |
|---|---|---|---|
| `异常效果` | 23.7 KB | **43 个异常效果 ＋ 2 个异常组合 ＋ 9 种抗性**的总表；分节：异常效果(AbnormalFlag) / 异常组合(AbnormalCombo) / 异常免疫 / 反隐（隐匿免疫） | 机制词典那 25 条的**总目录**，防漏 |
| `异常效果图鉴/*`（15 页） | 冻结 37.5 KB、眩晕 84 KB、沉默 62 KB、恐惧 25 KB、束缚 20 KB、战栗 5.1 KB、浮空 / 迷彩 / 缚地 / 诱导 / 失衡 / 失衡免疫 / 不死 / 组合·沉睡 / 主页 | 逐状态的**定义 ＋ 载体清单**（谁能使我方中、谁能使敌方中、各自几秒）；主页注明"敌人数据均为等级 0、干员技能均为专精三" | 机制落地时的**权威口径**与"这一条到底有哪些来源"的清单 |
| `可抵抗状态` | 3.9 KB | 抵抗的**精确口径**：每个 Buff 自带 `statusResistable`，三态＝不可抵抗(默认)/可抵抗/自动识别；标为可抵抗时按干员的 **`ONE_MINUS_STATUS_RESISTANCE`** 加速其剩余时长流逝 | 直接服务 P1 的「抵抗」——**不是简单的"时长减半"**，是个倍率 |
| `作战机制/sandbox/动画时长` | 33 KB | 逐干员的**帧数**（Start 等），数据源标注为 cznull 的实测 | 直接服务待裁定 §四 的「干员抬手 prepDuration 与动画帧补正」与「敌人攻击动作时长」 |
| `数值范围` | 5.4 KB | 每个角色/敌人类单位 **38 个属性**（其中 4 个占位未实装） | 夹取与保底那类口径的上位依据 |
| `随机数` | 7.5 KB | 随机方式（骰子 Dice 等） | 服务既有的「概率类期望值法」 |
| `常见同名状态` | 2.0 KB | 同名不同义的状态 | 我们踩过同名不同义的坑，这是清单 |
| `术语释义` | 12.8 KB | 战斗术语：状态 / 技能相关 / **元素相关** / 干员分类 / 杂项 | 术语对齐 |

> ⚠ **一个重要的否定发现**：`异常效果图鉴/寒冷` 与 `异常效果图鉴/组合/寒冷` **都不存在**（404）。
> 寒冷与冻结的**数值**口径因此只有 `敌人一览/数据` 的 tooltip 词典一处来源——
> 那条 tooltip 恰恰写着「寒冷：攻击速度下降 30」。这也解释了项目此前为什么记"拿不到数"：
> 找错了页面。

### 5.2 已定位、还没抓的（按价值排序）

| 页面 | 大小 | 为什么值得抓 |
|---|---|---|
| `天赋生效条件一览` | 359 KB | 天赋的**生效条件**总表——我们有"条件加成逐帧判"这条口径，正缺一份对照 |
| `关卡一览/活动关卡` | 303 KB | 活动关卡总表，与 ark-nights 那份 4694 条索引**交叉校验** |
| `特殊机制` | 60 KB | 各活动专属机制的集中页（怀黍离／R.I.O.S. 之外的） |
| `游戏数据基础/属性计算例子` | 3.5 KB | 属性计算的**算例**，可直接验我们那条公式链 |
| `游戏数据基础/en/Abnormal Effects`、`/en/Status Effects` | — | 英文版，表格通常更干净，适合机械解析 |
| `失衡位移机制` | 2.7 KB | 位移（推/拉已建模）的对账依据 |
| `干员升级数值` | 7.8 KB | 升级数值表 |
| `敌人一览/总览`、`敌人一览/filters`、`敌人图鉴`、`敌人入口` | — | 敌人侧的索引入口 |
| `干员一览/干员id`、`干员分支`、`干员专精`、`干员信赖` | — | 干员侧索引入口 |
| `作战机制/sandbox/待测机制`、`作战机制/sandbox2` | 3.9 KB / — | 站方自己标"待测"的机制，可当待验证清单 |

### 5.3 分类入口（比页面更好用的两条）

* **`分类:游戏数据`**（15 项）：`常见同名状态`、`仇恨`、`符文`、`干员等级上限`、
  `可抵抗状态`、`数值范围`、`随机数`、`特殊地形`、`特殊地形/sandbox`、`特殊机制`…
* `分类:敌人`（300+ 项，敌人库的取数入口）、`分类:干员`（300+ 项）。

## 六、相关文档导航

| 主题 | 文档 |
|---|---|
| prts.wiki 入口实测、模板结构、攻击范围图语义 | `docs/prts-wiki.md` |
| gamedata 两镜像、关卡索引、六个坑（y 口径 / 字段包装 / 名字不一致 / fragment / 途经点） | `docs/gamedata.md` |
| 两个本地库为什么分开、口径差异 | `docs/database.md`、`docs/enemy-db.md` |
| 公式取源对照与量纲 | `docs/formula-sources.md`、`docs/formula-units.md` |
| 机制词典现状与实施顺序（本文件第一节第三页的产物） | `docs/mechanics-dictionary.md` |
| 还没定的事、还在猜的事 | `docs/uncertainties.md`、`docs/limitations.md` |
