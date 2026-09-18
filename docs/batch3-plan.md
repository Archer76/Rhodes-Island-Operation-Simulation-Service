# 第三批：下一批十位的建模计划

## 怎么选出这十位的（可复算，不是印象）

**练度序的定义在代码里**：`tools/roster.py:150`

```python
rows.sort(key=lambda r: (-r["elite"], -r["level"], r["charId"]))
```

即**精英降序 → 等级降序 → charId 升序**。名册 `docs/roster-*.md` 的行序就是按它排的。

第二批发完之后，把**第二批已经做过的十一位**（`char_4195_radian`、`char_4230_mcnist`、
`char_2027_wang`、`char_1050_chen3`、`char_1046_sbell2`、`char_2023_ling`、
`char_002_amiya`、`char_1001_amiya2`、`char_2012_typhon`、`char_4133_logos`、
`char_1015_aglna2`）从练度序里剔除，**取剩下的前十位**——正好是练度序的第
10–15 与 17–18、20–21 行。

| # | 干员 | charId | 练度序位次 | 子职业 |
|---|---|---|---|---|
| 1 | 能天使 | `char_103_angel` | 10 | 速射手 |
| 2 | 新约能天使 | `char_1041_angel2` | 11 | 怪杰 |
| 3 | 焰狐龙梓兰 | `char_1048_orchd2` | 12 | 重射手 |
| 4 | 怒潮凛冬 | `char_1051_headb2` | 13 | 撼地者 |
| 5 | 凯尔希·思衡托 | `char_1052_kalts2` | 14 | 守望者 |
| 6 | 星熊 | `char_136_hsguma` | 15 | 铁卫 |
| 7 | 泥岩 | `char_311_mudrok` | 17 | 不屈者 |
| 8 | 阿斯卡纶 | `char_4132_ascln` | 18 | 伏击客 |
| 9 | 结城理 | `char_4217_makoto` | 20 | 傀儡师 |
| 10 | 可露希尔 | `char_4228_closur` | 21 | 战术家 |

> 这条推导有一个**独立旁证**：第一批做完后跑的建模完成度审计里，「未建模最多」的
> 前列恰好就是焰狐龙梓兰、可露希尔、新约能天使、结城理、怒潮凛冬——与练度序算出来
> 的这十位高度重合。两套口径互不依赖，却指向同一批人。

## 摸底：这一批要建什么

判据同 `docs/modeling-coverage.md`：**两道筛子**——`_classify` 认不认这个黑板键，
以及源码字面量里有没有人读它；两道都不成立才是真的没建模。

**这一批明显比第二批重**：十位总计 184 个键，无人读 70 个。

### 两位是零欠账，可以直接核验收口

* **能天使**（10 键，无人读 0）
* **星熊**（8 键，无人读 0，未归类 1 但源码有人在读）

这两位不需要新机制，只需**核对建模正确性**（属性/技能/天赋逐项对照数据源），
并在守卫里钉住。

### 已经现成的两个接口

* **新约能天使**带 `shield_max_hp_ratio` 与 `shield_max_duration`——正是
  `docs/uncertainties.md` 第十一节里留档「未做」的**屏障叠加上限与衰减**；
* **焰狐龙梓兰**带 `knockback_duration`（击退）——正好接上刚落地的位移接线
  （`EnemyUnit.displaced` / `sim._apply_push`）。

### 按干员的欠账（音序即上表）

* **焰狐龙梓兰 20**：`attack@fly_height` / `attack@fly_duration` /
  `attack@fly_end_duration`（起飞滞留——**位移的第二形态**）、`knockback_duration`、
  `attack@atk_scale_loop` / `attack@atk_scale_end`（循环段与收尾段不同倍率）、
  `power_attack_count` / `power_attack_scale`、`wait_duration` / `dist_interval` /
  `max_dist`（**射程随距离分段**）、`projectile` / `$projectile`、
  `ignore_build_type_target_range` / `ignore_build_type_target`、`stun_prob`、
  `atk_duration`
* **可露希尔 12**：18 个未归类键里的 12 个无人读——以 buff 类为主（9 个 buff 桶），
  需要逐条看是不是「战术家」召唤物侧的量
* **新约能天使 11**：`steal` / `steal_max`（偷取属性）、`addtional_ammo_each`、
  `recover_each_cnt`、`shield_max_hp_ratio` / `shield_max_duration`、
  `attack@cannon_atk_scale`、`aoe_atk_scale`、`mult`、`max_deploy_character`
* **结城理 8**：`$range_id`、以及傀儡师（`char_4217_makoto`）的傀儡机制
* **怒潮凛冬 7**：撼地者，且**它是博士真作业里用的那一位**（见
  `docs/uncertainties.md` 与 1-7 基线）——优先级最高
* **阿斯卡纶 5**、**凯尔希·思衡托 4**、**泥岩 3**

### 可能被推进的两条留档欠账

1. **屏障的叠加上限与衰减**（新约能天使给到了键）；
2. **位移的第二形态**：起飞滞留与击退（焰狐龙梓兰给到了键）。

## 建议的推进顺序

1. **怒潮凛冬**——真作业用员，先核它（返工代价最高）；
2. **能天使 + 星熊**——零欠账，快速核验收口，给这一批定一个「已完成」的样板；
3. **焰狐龙梓兰**——欠账最多，且会顺带把屏障/位移那两条留档欠账推进；
4. 其余按欠账数从多到少。

## 摸底原始输出

以下由 `python tools/audit_coverage.py --only <这十位>` 生成，**不要手抄数字**。

```
干员            E/L         键数    未归类    无人读  分桶
--------------------------------------------------------------------------
焰狐龙梓兰         E2 60       30     23     20  buff=1 control=1 damage=5 other=23  ←
可露希尔          E2 60       29     18     12  buff=9 damage=2 other=18  ←
新约能天使         E2 60       26     15     11  buff=3 damage=8 other=15  ←
结城理           E2 60       27     13      8  buff=4 control=2 damage=8 other=13  ←
怒潮凛冬          E2 60       18      7      7  buff=7 control=2 damage=2 other=7  ←
阿斯卡纶          E2 60       19     11      5  buff=7 damage=1 other=11  ←
凯尔希·思衡托       E2 60       20      8      4  buff=8 control=1 damage=3 other=8  ←
泥岩            E2 60       17      6      3  buff=6 control=3 damage=2 other=6  ←
星熊            E2 60        8      1      0  buff=6 damage=1 other=1  ·
能天使           E2 60       10      0      0  buff=4 damage=6

==========================================================================
第一道（分类器认不了）：90 种键、102 次
第二道（**源码里也没有任何地方读它**）：68 种键、70 次  ← 这些才是真的没建模
==========================================================================
    3 位  $range_id                          新约能天使、结城理
    1 位  addtional_ammo_each                新约能天使
    1 位  recover_each_cnt                   新约能天使
    1 位  shield_max_hp_ratio                新约能天使
    1 位  shield_max_duration                新约能天使
    1 位  steal                              新约能天使
    1 位  steal_max                          新约能天使
    1 位  attack@cannon_atk_scale            新约能天使
    1 位  max_deploy_character               新约能天使
    1 位  aoe_atk_scale                      新约能天使
    1 位  mult                               新约能天使
    1 位  stun_prob                          焰狐龙梓兰
    1 位  attack@atk_scale_loop              焰狐龙梓兰
    1 位  attack@atk_scale_end               焰狐龙梓兰
    1 位  attack@fly_height                  焰狐龙梓兰
    1 位  attack@fly_duration                焰狐龙梓兰
    1 位  attack@fly_end_duration            焰狐龙梓兰
    1 位  wait_duration                      焰狐龙梓兰
    1 位  dist_interval                      焰狐龙梓兰
    1 位  max_dist                           焰狐龙梓兰
    1 位  knockback_duration                 焰狐龙梓兰
    1 位  power_attack_count                 焰狐龙梓兰
    1 位  power_attack_scale                 焰狐龙梓兰
    1 位  atk_duration                       焰狐龙梓兰
    1 位  projectile                         焰狐龙梓兰
    1 位  $projectile                        焰狐龙梓兰
    1 位  ignore_build_type_target_range     焰狐龙梓兰
    1 位  $ignore_build_type_target_range    焰狐龙梓兰
    1 位  ignore_build_type_target           焰狐龙梓兰
    1 位  ignore_build_type_target_dir       焰狐龙梓兰
    1 位  not_add_respawn_cost_cnt           焰狐龙梓兰
    1 位  headb2_s_2[second].atk             怒潮凛冬
    1 位  headb2_s_2[second].def             怒潮凛冬
    1 位  sp_per_highland                    怒潮凛冬
    1 位  atk_step                           怒潮凛冬
    1 位  splash_atk_scale_bonus             怒潮凛冬
    1 位  attack@splash_atk_scale            怒潮凛冬
    1 位  scale_bonus                        怒潮凛冬
    1 位  attack@block_radius_scale          凯尔希·思衡托
    1 位  block_radius_scale                 凯尔希·思衡托
    1 位  rhodes_bonus                       凯尔希·思衡托
    1 位  attack@rhodes_bonus                凯尔希·思衡托
    1 位  buff_prob                          泥岩
    1 位  awake                              泥岩
    1 位  max_times                          泥岩
    1 位  attack@damage_hitrate_physical     阿斯卡纶
    1 位  attack@damage_hitrate_magical      阿斯卡纶
    1 位  atk_ratio                          阿斯卡纶
    1 位  debuff_duration                    阿斯卡纶
    1 位  attack_speed_add                   阿斯卡纶
    1 位  attack@kill_atk_scale              结城理
    1 位  attack@kill_damage                 结城理
    1 位  attack@max_target_heal             结城理
    1 位  max_hp_t1                          结城理
    1 位  multi_attack_total_cnt             结城理
    1 位  final_damage_different_ratio       结城理
    1 位  cost_add_max                       可露希尔
    1 位  shield_cnt                         可露希尔
    1 位  cost_return                        可露希尔
    1 位  closur_s_2[add_cost_period].cost   可露希尔
    1 位  closur_s_2[add_cost_period].interval 可露希尔
    1 位  cost_attack_add                    可露希尔
    1 位  attack_trigger_cnt                 可露希尔
    1 位  attack@slow_down                   可露希尔
    1 位  attack@slow_down_time              可露希尔
    1 位  attack@slow_down_max               可露希尔
    1 位  closur_s_3[add_cost_period].cost   可露希尔
    1 位  closur_s_3[add_cost_period].interval 可露希尔

--- 附：第一道命中但源码有人在读的（不是欠账，仅供核对）---
    3 位  range_id                           新约能天使、结城理
    3 位  hp_ratio                           新约能天使、泥岩
    3 位  cnt                                阿斯卡纶、可露希尔
    2 位  prob                               新约能天使、星熊
    2 位  interval                           泥岩、阿斯卡纶
    2 位  attack@prob                        结城理
    2 位  cost_period                        可露希尔
    1 位  attack@sp                          新约能天使
    1 位  atk_scale_magic                    焰狐龙梓兰
    1 位  force                              焰狐龙梓兰
    1 位  respawn_time                       焰狐龙梓兰
    1 位  buff_duration                      凯尔希·思衡托
    1 位  hp_recovery_per_sec                凯尔希·思衡托
    1 位  attack@buff_duration               凯尔希·思衡托
    1 位  attack@hp_recovery_per_sec         凯尔希·思衡托
    1 位  range_radius                       阿斯卡纶
    1 位  attack@hp_ratio                    阿斯卡纶
    1 位  max_stack_cnt                      阿斯卡纶
    1 位  attack@interval                    结城理
    1 位  cost_per_add                       可露希尔
    1 位  max_trigger_cnt                    可露希尔
    1 位  attack@max_stack_cnt               可露希尔
```

## 纪律（沿用前两批）

* 每做完一项机制，**在 `tools/check_battle.py` 里加一节守卫**，并重跑本审计——
  真做完的键会从「无人读」那一栏消失；
* 不确定的先去数据源查证；确实查不到的写进 `docs/uncertainties.md` 并继续做别的，
  **不要停在原地**；
* **仅在博士明确要求上传 GitHub 时才跑全套基线自检**。
