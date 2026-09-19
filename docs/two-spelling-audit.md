# 双写法且有信息 —— 全库清单（第四批选人的「实操可做性」证据）

> **本文件由脚本生成，不要手改**：`python tools/two_spelling_audit.py`。改口径请改脚本（或改题源），改完重生成。

## 生成方式（元数据，便于复核）

* 工具：`tools/two_spelling_audit.py`；运行者：**RIOS后端2**
* 所属树 HEAD：`c72d213`；工作区（`ak_tactic/`＋`tools/`）**dirty**
* 键空间对拍（vs 审计 `keys_of()`）：抽 4 位（等距）逐位相同的 4 位
* **判据来源**：`tools/audit_coverage.py:50-69` 的 `is_read()`（整键 → 方括号条件名 → `key.rsplit('@', 1)[-1]`）；键空间＝DB 黑板行摊平后**另存 `$键名`**（`ak_tactic/operator/talent.py:139-147`）。

## 口径（五档，先说清「这一列数的是什么」）

| 档 | 家族数 | 其中有干员行 | 含义 |
|---|---|---|---|
| **A 干净可做** | 0 | 0 | 有干员行 ＋ 有现成消费点 ＋ `$` 侧与裸侧**不同值** ⇒ 接线＝扩一处已存在的查表，**且会改行为** |
| **B 假欠账（同值）** | 1 | 1 | 有消费点，但 `$` 侧与裸侧**同值** ⇒ 接上**不改行为** |
| **E 口径·后缀读法** | 1 | 1 | 源码用 `k.endswith(…)` 读它，`is_read` 的字面量尺子**看不见**这种读法 |
| **C 要新读点** | 9 | 9 | 本树**没有任何**读点 ⇒ 要新机制／新分支，不是干净件 |
| **D 装置·召唤物** | 26 | 0 | 行都在装置／召唤物上（**无干员行**）⇒ 不属于第四批选人范围 |

**读法**：一个「家族」＝ 同一个 `core` 下的多种写法。`core(X)` ＝ 去 `$` 前缀、取最后一个 `@` 之后——**与 `is_read` 第 ③ 条同一把尺子**，所以在源码里写一个 `core` 字面量会**同时**把这族的成员都判成「有人读」。

## 一、结论先说（三句）

1. **A 档 ＝ 0**：全库（37 族）扫下来，**没有一族**满足「有干员行 ＋ 有现成消费点 ＋ 两侧值不同」。
2. 机械规则本来报了 7 个 A，**逐条看消费点原文行后全部推翻**：5 个根本没有干员行（是装置／召唤物），`key`／`equip`／`unlock` 的命中是解析黑板或取数层的**同名不同义**，`prob`／`token_key` 是**同值**。
3. ⇒ 按「双写法且有信息」这条判据选人：**它不产出干净可做的人**。有干员行的家族只有 11 个，其中 A 档 0 个，其余是 C（要新读点）或口径问题。

## 二、A 档逐条（7 条全部判成假欠账／非干员行，证据在此）

（空）

## 三、B 档：假欠账（有消费点，但两侧同值）

| core | 欠账侧 | 同值/不同值 | 干员行 | 裁定理由 |
|---|---|---|---|---|
| `prob` | `$prob` | 4/0 | 1 | `$prob` 与裸 `attack@prob`/`prob` **同值**（实测 4 处同值、0 处不同值）；而且 `$prob` 只出现在**装置**行，干员侧（Misery）根本没有 `$` 侧 ⇒ 假欠账 |

## 四、E 档：口径·后缀匹配读法（`is_read` 看不见的那一类）

审计的 `is_read()`（`tools/audit_coverage.py:50-69`）只试三种字面量：整键、方括号里的条件名、`key.rsplit('@',1)[-1]`。**后缀匹配读法不在其中**——下面这些键的「没人读」是**尺子的问题**，不是真没人读。

### `token_key`　干员行 1 位 / 总 17 行

* **裁定理由**：裸 `talent@token_key` 的数字是 0、真值在 `valueStr`（真 token id），`$` 侧与它**同值** ⇒ 同一量的两种写法；且 `ak_tactic/gamedata/enemy.py:481` 用 `k.endswith("token_key")` **后缀匹配**读它 ⇒ 审计的字面量尺子看不见这种读法
* **后缀读法命中**：`ak_tactic/gamedata/enemy.py:481`
* **`$` 侧 vs 裸侧**：同值 17 / 不同值 0
* **样例**：圣聆初雪·skchr_sbell2_2 → `talent@token_key`=0.0, `$talent@token_key`='token_10058_sbell2_icetgt'；圣聆初雪·skchr_sbell2_2 → `talent@token_key`=0.0, `$talent@token_key`='token_10058_sbell2_icetgt'

## 五、C 档：要新读点（**有干员行的排前面**——这是第四批会碰到的）

| core | 干员行 | 欠账侧 | 总行数 | 样例干员 | 裁定理由 |
|---|---|---|---|---|---|
| `projectile_range` | **有** | `$attack@projectile_range`、`$projectile_range`、`attack@projectile_range` | 50 | 引星棘刺｜char_1039_thorn2、机械师｜char_4230_mcnist、艾拉｜char_4123_ela | 4 位干员（引星棘刺／机械师／艾拉…）、50 行；本树**没有任何** `projectile_range` 读点 ⇒ 要新读点；弹道机制在 `rios-sim/` 侧（机制层） |
| `atk_magic` | **有** | `atk_magic`、`attack@atk_magic` | 10 | 雷狼龙S空爆｜char_1049_catap2 | 雷狼龙S空爆 1 位、10 行；无读点 ⇒ 要新读点（法术附加伤害那一族） |
| `attack_range_id` | **有** | `$attack@attack_range_id`、`attack@attack_range_id` | 10 | 予愿安洁莉娜｜char_1015_aglna2 | 予愿安洁莉娜 1 位、10 行；**已按判据③判红**：`x-4` ＝ 周围 8 格、接进 `_range_override` 会让范围 19 格 → 9 格，与正文「扩大」**方向相反** ⇒ **不许接**（`docs/uncertainties.md` 第三十节） |
| `burn.atk_scale` | **有** | `attack@burn.atk_scale`、`burn.atk_scale` | 10 | 火哨｜char_493_firwhl | 火哨 1 位、10 行；无读点 ⇒ 要新读点 |
| `chain.atk_scale` | **有** | `attack@chain.atk_scale`、`chain.atk_scale` | 1 | 乌啾｜char_4224_turdus | 乌啾；无读点 ⇒ 要新读点（链式那一家族） |
| `chain.atk_scale_2` | **有** | `attack@chain.atk_scale_2`、`chain.atk_scale_2` | 4 | 乌啾｜char_4224_turdus | 乌啾；无读点 ⇒ 要新读点 |
| `chain.max_target` | **有** | `attack@chain.max_target`、`chain.max_target` | 1 | 乌啾｜char_4224_turdus | 乌啾；无读点 ⇒ 要新读点 |
| `damage_addition` | **有** | `attack@damage_addition`、`damage_addition` | 10 | 戴菲恩｜char_4110_delphn | 戴菲恩 1 位、10 行；无读点 ⇒ 要新读点 |
| `take_extra_enemy_key` | **有** | `$take_extra_enemy_key`、`take_extra_enemy_key` | 1 | 隐德来希｜char_4010_etlchi | 隐德来希 1 位；无读点 ⇒ 要新读点 |

## 六、D 档：装置·召唤物行（非干员，供引擎侧参考）

| core | 总行数 | 欠账侧 | 同值/不同值 | 样例 |
|---|---|---|---|---|
| `ability_name` | 1 | `$ability_name`、`ability_name` | 1/0 | 牙猎犬 |
| `battle_item` | 5 | `$battle_item`、`battle_item` | 5/0 | 冶铸车、大图书馆、插件补给点 |
| `blordreborn.branch_id` | 1 | `$blordreborn.branch_id`、`blordreborn.branch_id` | 1/0 | 沥血王座 |
| `branch_id` | 43 | `$branch_id` | 43/0 | 唤血祭坛、炸弹载荷点、沥血王座 |
| `default_pool` | 2 | `$default_pool`、`default_pool` | 2/0 | 田地、温室拱棚 |
| `dialogue_config_signal_key` | 5 | `$dialogue_config_signal_key`、`dialogue_config_signal_key` | 5/0 | 狮蝎、告示牌、待清理材料 |
| `drop_trap_pool` | 1 | `$drop_trap_pool`、`drop_trap_pool` | 1/0 | 冶铸车 |
| `dynamic` | 1 | `attack@dynamic`、`dynamic` | 0/0 | 阿勒黛的卫护 |
| `enemy_key` | 38 | `$enemy_key` | 40/0 | 唤血祭坛、沥血王座、“宝箱” |
| `equip` | 1 | `$equip` | 1/0 | 废墟 |
| `extra_pool` | 2 | `$extra_pool`、`extra_pool` | 2/0 | 田地、温室拱棚 |
| `gather_type` | 3 | `$gather_type`、`gather_type` | 3/0 | 巨大岩石、奇异矿脉、澄亮矿脉 |
| `halfidle_lhgras_bonus_drop.resource_gras_bonus` | 1 | `$halfidle_lhgras_bonus_drop.resource_gras_bonus`、`halfidle_lhgras_bonus_drop.resource_gras_bonus` | 1/0 | 草丛 |
| `halfidle_lhpark_bonus_drop.resource_park_bonus` | 1 | `$halfidle_lhpark_bonus_drop.resource_park_bonus`、`halfidle_lhpark_bonus_drop.resource_park_bonus` | 1/0 | 花丛 |
| `key` | 1 | `$key` | 1/0 | 先遣侦测器 |
| `killbmbcar.branch_id` | 1 | `$killbmbcar.branch_id`、`killbmbcar.branch_id` | 1/0 | 沥血王座 |
| `range_id1` | 1 | `$range_id1`、`range_id1` | 1/0 | 城市霓虹 |
| `range_id2` | 1 | `$range_id2`、`range_id2` | 1/0 | 城市霓虹 |
| `rangeid` | 1 | `$rangeid`、`rangeid` | 1/0 | 晶簇稳定器 |
| `resource` | 13 | `$resource`、`resource` | 13/0 | 晶簇稳定器、源石回收炉、被污染的回收炉 |
| `summon1.enemy_key` | 1 | `$summon1.enemy_key`、`summon1.enemy_key` | 1/0 | 侦测中心 |
| `summon2.enemy_key` | 1 | `$summon2.enemy_key`、`summon2.enemy_key` | 1/0 | 侦测中心 |
| `toast` | 3 | `$toast`、`toast` | 3/0 | 宝刺金属箱、老练猎手、埋没金属箱 |
| `token_cnt_1` | 2 | `$token_cnt_1`、`token_cnt_1` | 2/0 | “宝箱”、“宝箱” |
| `unlock` | 5 | `$unlock` | 5/0 | 镇岁柱、镇岁柱、镇岁柱 |
| `upgrade_trap_id` | 1 | `$upgrade_trap_id`、`upgrade_trap_id` | 1/0 | 草丛 |

## 七、★ 第四类「读写不到」（单独标出来对账）

`head核查` 报的那一类：范围代号在 `data/ranges.json` 里**没有或为空** —— 那不是「没人读」，是「读了也读不到」。它修完 `grid.py` 后这类应自己消失一批。

（本次扫描没命中）


## 八、按干员聚合（给第四批选人用）

| 干员 | 欠账家族数 | 家族（带档） |
|---|---|---|
| 乌啾｜char_4224_turdus | 3 | `chain.atk_scale`(C)、`chain.atk_scale_2`(C)、`chain.max_target`(C) |
| Misery｜char_615_acspec | 1 | `prob`(B) |
| 圣聆初雪｜char_1046_sbell2 | 1 | `token_key`(E) |
| 引星棘刺｜char_1039_thorn2 | 1 | `projectile_range`(C) |
| 机械师｜char_4230_mcnist | 1 | `projectile_range`(C) |
| 艾拉｜char_4123_ela | 1 | `projectile_range`(C) |
| 酒神｜char_1042_phatm2 | 1 | `projectile_range`(C) |
| 雷狼龙S空爆｜char_1049_catap2 | 1 | `atk_magic`(C) |
| 予愿安洁莉娜｜char_1015_aglna2 | 1 | `attack_range_id`(C) |
| 火哨｜char_493_firwhl | 1 | `burn.atk_scale`(C) |
| 戴菲恩｜char_4110_delphn | 1 | `damage_addition`(C) |
| 隐德来希｜char_4010_etlchi | 1 | `take_extra_enemy_key`(C) |
