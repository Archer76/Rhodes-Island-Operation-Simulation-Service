# 建模完成度审计（按名册的 E2 干员全量）

> 生成命令：`python tools/audit_coverage.py`（`--only 名字…` 只看几位；
> `--all` 连非 E2 也看；`--top N` 只看未建模最多的 N 位）。
>
> **这份表不要手抄数字**——它随代码变。要看当前水位就重跑那条命令。

## 判据是什么

一位干员的"建模完成度"用**两个筛子**量，而不是靠印象：

1. **第一道：分类器认不认。** 每个技能（M3）与天赋的黑板键过一遍
   `operator/skill.py` 的 `_classify`。归不了类的键会掉进 `SkillEffects.other`。
2. **第二道：源码里有没有人读它。** 拿全 `ak_tactic/` 里的字符串字面量做索引。

**两道都不成立（既不归类、也没人读）的键 = 真的没建模。** 只有第一道命中
不算欠账：`hp_ratio`、`cnt`、`prob`、`interval` 这些分类器认不了，但模拟器在
**原地**直接读（要靠周围描述消歧），它们在表里单列"仅供核对"。

**这个判据的已知边界**（别把它当全能）：

* 是**启发式**。若某个键是被"按变量名查字典"消费的，会被误报成未建模；
* 只量**黑板键**，量不到"描述里有、黑板里没有"的机制（例如纯靠正文判定的
  真伤改写、无视法抗）。那类要靠 `docs/batch2-plan.md` 与
  `docs/uncertainties.md` 的逐条清单，不能只看这张表；
* 天赋键的取法与技能不完全同源，天赋那部分宁可漏不可错。

## 怎么用它验收一批

1. 跑一次全量，记下每位目标干员的"无人读"计数；
2. 逐个看**未建模键全表**里属于这批的那几行，判它是"真欠账"还是"启发式误报"；
3. 每做完一项机制，**在 `tools/check_battle.py` 里加一节守卫**，并重跑本审计——
   真做完的键会从"无人读"那一栏消失；
4. 收尾时重跑本命令，把表粘回来（或只更新水位）。

---
干员            E/L         键数    未归类    无人读  分桶
--------------------------------------------------------------------------
焰狐龙梓兰         E2 60       30     23     20  buff=1 control=1 damage=5 other=23  ←
可露希尔          E2 60       29     18     12  buff=9 damage=2 other=18  ←
新约能天使         E2 60       26     15     11  buff=3 damage=8 other=15  ←
娜仁图亚          E2 1        20     14     11  control=2 damage=4 other=14  ←
予愿安洁莉娜        E2 60       25     12      9  buff=8 damage=5 other=12  ←
结城理           E2 60       27     13      8  buff=4 control=2 damage=8 other=13  ←
怒潮凛冬          E2 60       18      7      7  buff=7 control=2 damage=2 other=7  ←
逻各斯           E2 60       18     10      6  buff=5 control=1 damage=2 other=10  ←
望             E2 90       19     13      5  buff=1 control=1 damage=4 other=13  ←
死芒            E2 48       31     11      5  buff=15 damage=5 other=11  ←
阿斯卡纶          E2 60       19     11      5  buff=7 damage=1 other=11  ←
赤刃明霄陈         E2 90       13      7      5  buff=3 damage=3 other=7  ←
机械师           E2 90       21     10      4  buff=4 damage=7 other=10  ←
凯尔希·思衡托       E2 60       20      8      4  buff=8 control=1 damage=3 other=8  ←
圣聆初雪          E2 90       25     15      3  buff=4 control=3 damage=3 other=15  ←
泥岩            E2 60       17      6      3  buff=6 control=3 damage=2 other=6  ←
阿米娅           E2 80       12      6      3  buff=3 damage=3 other=6  ←
电弧            E2 90       18      7      2  buff=7 control=2 damage=2 other=7  ←
提丰            E2 60       16      5      2  buff=5 control=3 damage=3 other=5  ←
清流            E2 40        5      2      2  buff=1 damage=2 other=2  ←
阿米娅           E2 80        8      2      2  buff=3 control=1 damage=2 other=2  ←
令             E2 90       17     10      1  buff=5 damage=2 other=10  ←
歌蕾蒂娅          E2 1        18      9      1  buff=4 damage=5 other=9  ←
温蒂            E2 1        15      9      1  buff=2 control=2 damage=2 other=9  ←
调香师           E2 40        4      1      1  buff=3 other=1  ←
嘉维尔           E2 40       14      8      0  buff=2 damage=4 other=8  ·
桃金娘           E2 40        8      5      0  buff=2 damage=1 other=5  ·
豆苗            E2 40        7      3      0  buff=4 other=3  ·
拉普兰德          E2 1         4      2      0  buff=2 other=2  ·
星熊            E2 60        8      1      0  buff=6 damage=1 other=1  ·
德克萨斯          E2 1         5      0      0  buff=3 control=1 damage=1
能天使           E2 60       10      0      0  buff=4 damage=6

==========================================================================
第一道（分类器认不了）：175 种键、263 次
第二道（**源码里也没有任何地方读它**）：126 种键、133 次  ← 这些才是真的没建模
==========================================================================
    3 位  attack@projectile_range            机械师、娜仁图亚
    3 位  $range_id                          新约能天使、结城理
    2 位  attack@kill_atk_scale              逻各斯、结城理
    2 位  attack@kill_damage                 逻各斯、结城理
    2 位  hit_duration                       死芒、歌蕾蒂娅
    1 位  trig_cnt                           圣聆初雪
    1 位  attract_time                       圣聆初雪
    1 位  first_snow                         圣聆初雪
    1 位  chen3_s2[respawn_buff].atk         赤刃明霄陈
    1 位  chen3_s2[respawn_buff].prob        赤刃明霄陈
    1 位  stack_time                         赤刃明霄陈
    1 位  heal_atk_scale_min                 赤刃明霄陈
    1 位  heal_atk_scale_max                 赤刃明霄陈
    1 位  ling_s2_unmovable.duration         令
    1 位  display_move_speed                 望
    1 位  ammo_discard_limit_count           望
    1 位  attack@max_spawn_cnt               望
    1 位  attack@per_atk_scale               望
    1 位  attack@per_magic_resist_penetrate_fixed 望
    1 位  weak[magic][limit]                 电弧
    1 位  attack@weak[magic][limit]          电弧
    1 位  projectile_range                   机械师
    1 位  $attack@projectile_range           机械师
    1 位  amiya_t_1[atk].sp                  阿米娅
    1 位  amiya_t_1[kill].sp                 阿米娅
    1 位  amiya2_s_2[kill].atk               阿米娅
    1 位  amiya2_s_2[kill].magic_resistance  阿米娅
    1 位  amiya2_s_2[kill].max_stack_cnt     阿米娅
    1 位  buff_duration_ground_bound         予愿安洁莉娜
    1 位  buff_duration_levitate             予愿安洁莉娜
    1 位  aglna2_s_3[unblocked].attack_speed 予愿安洁莉娜
    1 位  aglna2_s_3[blocked].attack_speed   予愿安洁莉娜
    1 位  attack@attack_range_id             予愿安洁莉娜
    1 位  attack@max_walk_target             予愿安洁莉娜
    1 位  $attack@attack_range_id            予愿安洁莉娜
    1 位  atk_scale_hi                       予愿安洁莉娜
    1 位  atk_scale_lo                       予愿安洁莉娜
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
    1 位  first_duration                     提丰
    1 位  attack@s3_max_hit_num              提丰
    1 位  buff_prob                          泥岩
    1 位  awake                              泥岩
    1 位  max_times                          泥岩
    1 位  attack@damage_hitrate_physical     阿斯卡纶
    1 位  attack@damage_hitrate_magical      阿斯卡纶
    1 位  atk_ratio                          阿斯卡纶
    1 位  debuff_duration                    阿斯卡纶
    1 位  attack_speed_add                   阿斯卡纶
    1 位  attack@atk_scale_base              逻各斯
    1 位  attack@atk_scale_delta             逻各斯
    1 位  projectile_move_scale              逻各斯
    1 位  atk_addition                       逻各斯
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
    1 位  additional_token_cnt               死芒
    1 位  attack@max_valid_stack_cnt         死芒
    1 位  attack@necras_s_3[attack_cnt].max_stack_cnt 死芒
    1 位  max_token_cnt                      死芒
    1 位  atk_to_hp_recovery_ratio           调香师
    1 位  status_resistance[limit]           清流
    1 位  one_minus_status_resistance        清流
    1 位  dist                               温蒂
    1 位  attack@move_ahead_time             娜仁图亚
    1 位  attack@atk_scale_comeback          娜仁图亚
    1 位  atk_scale_aoe                      娜仁图亚
    1 位  attack@aoe.max_target              娜仁图亚
    1 位  attack@steal_atk                   娜仁图亚
    1 位  attack@steal_atk_max               娜仁图亚
    1 位  attack@steal_def                   娜仁图亚
    1 位  attack@steal_def_max               娜仁图亚
    1 位  damage_hitrate_physical            娜仁图亚
    1 位  damage_hitrate_magical             娜仁图亚

--- 附：第一道命中但源码有人在读的（不是欠账，仅供核对）---
   19 位  cnt                                令、望、电弧、阿斯卡纶、可露希尔、豆苗、温蒂、娜仁图亚、歌蕾蒂娅
   14 位  interval                           圣聆初雪、令、望、泥岩、阿斯卡纶、死芒、桃金娘、嘉维尔、豆苗、温蒂、歌蕾
   12 位  hp_ratio                           圣聆初雪、赤刃明霄陈、令、电弧、机械师、新约能天使、泥岩、死芒、嘉维尔
    7 位  duration                           提丰、逻各斯、嘉维尔、拉普兰德、温蒂
    6 位  force                              圣聆初雪、焰狐龙梓兰、温蒂、歌蕾蒂娅
    6 位  value                              令、桃金娘、豆苗、温蒂、歌蕾蒂娅
    6 位  prob                               阿米娅、新约能天使、星熊、逻各斯、拉普兰德、娜仁图亚
    3 位  max_stack_cnt                      令、提丰、阿斯卡纶
    3 位  range_radius                       机械师、阿斯卡纶、死芒
    3 位  range_id                           新约能天使、结城理
    3 位  attack@prob                        提丰、结城理
    3 位  attack@max_stack_cnt               逻各斯、可露希尔、死芒
    2 位  attack@interval                    机械师、结城理
    2 位  talent_scale                       阿米娅
    2 位  mass_level                         予愿安洁莉娜
    2 位  hp_recovery_per_sec                凯尔希·思衡托、桃金娘
    2 位  attack@hp_ratio                    阿斯卡纶、死芒
    2 位  cost_period                        可露希尔
    2 位  ability_range_forward_extend       温蒂、娜仁图亚
    2 位  attack@force                       歌蕾蒂娅
    1 位  talent@s2_magic_scale              圣聆初雪
    1 位  talent@max_cast_tile_count         圣聆初雪
    1 位  talent@token_key                   圣聆初雪
    1 位  $talent@token_key                  圣聆初雪
    1 位  max_cast_cnt                       圣聆初雪
    1 位  talent_magic_scale                 圣聆初雪
    1 位  freeze                             圣聆初雪
    1 位  c2e_freeze                         圣聆初雪
    1 位  projectile_min_atk_scale           赤刃明霄陈
    1 位  sp                                 令
    1 位  attack@duration                    望
    1 位  max_cnt                            望
    1 位  attack@max_trigger_cnt             望
    1 位  attack@projectile_delay_time       机械师
    1 位  not_combat                         机械师
    1 位  chant_duration                     予愿安洁莉娜
    1 位  attack@sp                          新约能天使
    1 位  atk_scale_magic                    焰狐龙梓兰
    1 位  respawn_time                       焰狐龙梓兰
    1 位  buff_duration                      凯尔希·思衡托
    1 位  attack@buff_duration               凯尔希·思衡托
    1 位  attack@hp_recovery_per_sec         凯尔希·思衡托
    1 位  attack@cooldown                    逻各斯
    1 位  cost_per_add                       可露希尔
    1 位  max_trigger_cnt                    可露希尔
    1 位  attack@ability_range_forward_extend 死芒
    1 位  ct                                 嘉维尔
    1 位  base_force_level                   温蒂
    1 位  projectile_delay_time              歌蕾蒂娅


---

## 与当前批次的对照

批次一/二的目标干员（电弧、机械师、望、赤刃明霄陈、圣聆初雪、令、阿米娅两形态、
提丰、逻各斯、予愿安洁莉娜）做完后仍留在"无人读"栏里的键，都是**明确留档过**
的欠账，不是漏做：

* 圣聆初雪 `trig_cnt` / `attract_time` / `first_snow` —— 技3 的「诱导」与积雪
  首层，属另一套机制；
* 赤刃明霄陈 `chen3_s2[respawn_buff].*` / `stack_time` / `heal_atk_scale_min|max`
  —— 重生 Buff 与自身治疗区间；
* 令 `ling_s2_unmovable.duration` —— 召唤物不可移动的时长；
* 望 `attack@per_*` / `ammo_discard_limit_count` / `attack@max_spawn_cnt`
  —— 陷阱师的逐发系数与弹药丢弃上限；
* 电弧 `weak[magic][limit]` —— 弱化条目；
* 机械师 `attack@projectile_range` —— 弹道射程。

**未建模最多的前列同时就是下一批的自然候选**：焰狐龙梓兰、可露希尔、新约能天使、
结城理、怒潮凛冬、死芒、阿斯卡纶、凯尔希·思衡托。

> **待博士裁定**：您给的"练度前十"（含提丰、逻各斯，不含能天使/新约能天使/
> 焰狐龙梓兰/怒潮凛冬）与 `docs/roster-*.md` 的**行序**对不上——
> 该表的顺序是（精英→等级）降序。所以"下一批"到底是按您的那份排序取下一段，
> 还是按名册行序取，我推不出来，没有替您定。本审计对两种口径都成立：它按
> **未建模键数**排，与批次边界无关。
