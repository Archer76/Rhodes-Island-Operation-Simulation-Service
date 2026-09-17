# 两个本地库

> 本文件自 `README.md` 拆出（2026-09-17）：README 只留「是什么 / 怎么用」，实测结论与历史记录按主题收到这里。总览见 [`README.md`](../README.md)。

### 两个本地库为什么分成两个文件

| | 干员库 | 敌人库 |
|---|---|---|
| 文件 | `data/akdb.sqlite` | `data/enemydb.sqlite` |
| 来源 | 游戏本体 gamedata 的 `excel/` | prts.wiki 的「分类:敌人」 |
| 主键 | `char_id` | prts.wiki 页名（`“死志的凝结”`） |
| 数值口径 | 只存**关键帧原文**，面板另算 | 存**算好继承的逐档数值** |
| 建库 | `db build`（不联网） | `enemydb build`（要联网，有 7 天缓存） |
| 自检 | `tools/check_db.py` | `tools/check_enemy_db.py` |

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
