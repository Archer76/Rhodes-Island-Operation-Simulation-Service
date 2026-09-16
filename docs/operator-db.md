# 本地干员库：`data/akdb.sqlite`

2026-09-15 建立。把 gamedata 的 **6 张战斗表**收进一个可查询的 SQLite 文件，
不必每次再解析 15 MB 的 JSON，也能做"跨干员"的查询（谁有某个黑板键、哪些技能
带停顿、哪些模组改特性）。

```bash
python -m ak_tactic db build        # 从 gamedata 重建（约 4 秒）
python -m ak_tactic db info         # 版本戳与各表行数
python -m ak_tactic db char 阿米娅   # 一个干员的完整战斗数据
python -m ak_tactic db find 术师     # 找干员
python -m ak_tactic db skill --key sluggish     # 按黑板键搜技能
python -m ak_tactic db talent --key splash_atk_scale
python -m ak_tactic db sql "select name,atk from operator_attr where kind='phase' order by atk desc limit 5"
python tools/check_db.py            # 48 项完整性与一致性检查
```

`db char` 的名字会撞车（有个装置也叫「阿米娅」），取舍是：**精确匹配且是真干员
的优先**，其次精确匹配、真干员、全部；仍不唯一就报出候选并让人用 id 指定。

## 装了什么

| 表 | 行数 | 内容 |
|---|---|---|
| `meta` | 6 | 版本戳：结构版本、构建时间、**data_version.txt 原文**、取数源、表清单 |
| `operator` | 1,163 | 干员本体（**真干员 460**，其余是召唤物与装置；**其中 2 个是升变形态**） |
| `operator_phase` | 2,171 | 阶段 → 攻击范围代号、阶段内最高等级 |
| `operator_attr` | 5,301 | 属性**关键帧**（`kind='phase'` 等级帧 / `kind='trust'` 信赖帧） |
| `operator_potential` | 2,140 | 潜能修正器 |
| `operator_talent` | 2,647 | 天赋：组 → 候选，含拍平后的黑板 |
| `operator_trait` | 274 | **结构化**职业特性（只有 157/460 名干员有） |
| `operator_skill` | 1,759 | 干员 → 技能槽位 |
| `skill` / `skill_level` | 1,624 / 10,643 | 技能本体与全等级（倍率、SP、持续、范围、黑板） |
| `module` / `module_level` | 905 / 1,527 | 模组本体与逐级属性、特性/天赋改写 |
| `attack_range` | 73 | 范围代号 → 格集合（`cells` 已是 `(x, y)` 相对格，含自身格） |

版本戳记录的是 `Stream://torappu-data/v077/rel77.0`（`VersionControl 77.2.0`，
2026-09-08）。**库是哪一版数据建的，永远答得上来**——这是把 `data_version.txt`
一起存进 `meta` 的理由。

## 故意不装的

**生息演算的装置**（212 个，如道路、兽栏、采集站、补给车轨道、温室，以及该模式
的 NPC 与道具）。判据取自游戏本体——`excel/sandbox_table.json` 与
`excel/sandbox_perm_table.json` 列出了这个模式引用的**全部**装置 id；**不是**按
id 前缀猜的：按前缀猜既会漏掉 `trap_413_hiddenstone`、`trap_466_tzumama` 这类
没有 `xb` 标记的第一季内容，也会误伤名字里恰好出现 wf/ac 的 `trap_403_wfactory`。
连同它们的**专属技能 186 条**一起不入库（只被剔除装置引用的技能才删；被剔除装置
与别人共用的技能保留）。

另有一批**与主线共用**的通用装置（干扰地雷、便携式补给站、轰隆隆先生、梅什科线圈、
雪雉的安全起重机、高能源石炸弹、特制水上平台、失修舞台雾机、便携气罐、急救包）
虽然也出现在沙盒表里，但不是为生息演算做的，**保留**——删掉会伤到非生息演算的数据。

档案与语音（`handbook_info_table` / `charword_table`）、时装（`skin_table`）、
基建技能（`building_data`）、养成材料（`item_table`、升级与专精消耗）。
理由是这些与战斗无关，收进来只是让库变大。模组的**解锁条件**（精英阶段 +
等级）保留了，因为它是战斗可用性的门槛；材料消耗没保留。

## 库里没有、但战斗上仍需注意的

* **抬手**（AKData 的 `customdata/dps_anim.json` 里的 `prepDuration` 与首刀帧）
  在 gamedata 里没有对应数据，见 [formula-sources.md](formula-sources.md) 第九节。
  注意它管的是**首刀时机**、不是出手周期——后者的公式已实机定案
  （`基础间隔 × 100 / 总攻速`，不需要帧数补正）。
* 升变形态与**原形态的关系**只体现在 `potentialItemId`（两者都是
  `p_char_002_amiya`，共用一个潜能信物）与 `charEquip` 上；库把形态当独立干员
  存（`is_patch = 1`），不额外造一张关系表。

## 建库时才发现的七件事

1. **职业特性没有独立表，也不在 `traits` 字段里。** 特性文本是每个干员的
   `description`（如阿米娅"攻击造成法术伤害"）；另有 157 名干员带**结构化**
   `trait`（含黑板），例如怒潮凛冬的 `attack@atk_scale_2 = 0.5`（群体伤害系数）。
   两者都存：前者进 `operator.trait_text`，后者进 `operator_trait`。
2. **天赋同样没有独立表**：`excel/talent_table.json` 是 404。天赋只在
   `character_table.json` 的 `talents` 里。
3. **升变形态不在 `character_table.json` 里**，而在 `char_patch_table.json` 的
   `patchChars`（全表只 2 条：阿米娅的近卫形态 `char_1001_amiya2`、医疗形态
   `char_1037_amiya3`），结构与干员本体完全相同。**只灌 character_table 会少
   两个可玩形态**，是森空岛名册把它揪出来的——名册引用了 `char_1001_amiya2`，
   而库里查不到。同一个缺口也让 `OperatorCalculator` 报「没有这个干员」，
   所以两边一起补。
4. **模组归属要看 `charEquip`，不能看 `equipDict.charId`。** 后者对升变形态的
   模组一律指回原形态（`uniequip_002_amiya2` 的 `charId` 是 `char_002_amiya`），
   照它写会把「阿米娅(近卫)」的模组挂到本体名下；`charEquip` 才按形态分别列
   （`char_1001_amiya2 → [uniequip_001_amiya2, uniequip_002_amiya2]`）。
   `OperatorCalculator.modules()` 本来就是这个口径，库里现在与它一致——905 条
   模组的归属逐条对得上。
5. **有 32 名"真干员"没有任何潜能数据**：29 名是 `isNotObtainable = 1` 的
   预备干员与模式专属（Sharp / Pith / Touch / Mechanist 那一批），另外 3 名是
   断罪者、罗小黑、九色鹿。这条已钉进检查脚本——多出一个就是异常。
6. **`sktok_cdsoul` 是上游缺口**：`trap_755_cdsoul`（啸叫音响）引用了它，
   而 `skill_table.json` 的 881 条 `sktok_*` 里没有这一条。不是建库漏了。
7. **有些技能槽位的 `skillId` 是 `null`**（59 个，全是 `token_*` 召唤物的占位，
   如凯尔希的 Mon3tr、深海色的触手）。这类行跳过不写，构建时以**一条汇总
   警告**列出，不静默吞掉、也不逐条刷屏。

## 两条设计取舍

* **只搬不推。** 库里存的是**原文**（关键帧、黑板、模组改写），不是算好的面板。
  插值、信赖与潜能的叠加、模组三道门，仍然只由 `ak_tactic.operator` 那套负责——
  两处各算一遍，迟早有一天对不上。`db char` 里显示的是库里的帧，要算面板请用
  `stats` 子命令。
* **库是可重建的派生物。** 每次 `build` 都从零建表（先写 `.part` 再
  `os.replace`，中途失败不会毁掉手上的库）。查询面默认**只读**打开，
  `db sql` 也拒绝写语句——想改就重建，别修。

## 校验

`python tools/check_db.py`——50 项，四类：

1. **出处**：结构版本、`data_version`、以及各表行数与源表条数**逐一对齐**
   （技能等级 10,643 行 = `skill_table` 里各技能 levels 之和减去装置专属的 369 行，
   干员 1,163 = `character_table` 1,373 + `char_patch_table` 2 − 生息演算装置 212），
   并**双向**盯住剔除本身：库里不许再有生息演算装置，与主线共用的 10 个通用装置
   必须还在；
2. **引用完整性**：技能、范围、模组、阶段、天赋、特性六类引用的悬空项，
   外加**模组归属与 `charEquip` 逐条对齐**；
3. **覆盖**：每个真干员都有阶段与两类关键帧；`INITIAL` 证章都没有战斗数值、
   509 条 `ADVANCED` 都有、21 条特限/特勤被标出；范围 `1-1` 必须等于
   `{(0,0),(1,0)}`；
4. **取值**：拿**外部锚点**对——阿米娅六个端点（PRTS 属性模板）与怒潮凛冬
   精2 60（实机录像，落在插值中段），再逐个干员抽查库里的帧与
   `OperatorCalculator` 是否同源一致。

另有 **[3b] 与森空岛名册交叉校验**（`data/skland/roster_*.json`，本地拉一份即可）：
名册是鹰角官方账号数据，**独立于 gamedata**，所以能抓住"库里根本没有这个干员"
这类整块缺口——本次就是它发现了升变形态与模组归属两处问题。逐项验的是：
干员存在、职业与职业分支一致、引用的技能与模组都在库里且属于该干员。
