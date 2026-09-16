# 本队技能的建模审计（从本地库取真值逐键核对）

> 生成工具：一次性脚本，逐键在 `ak_tactic/battle/*.py` 里找有没有人认它。
> **只说明『这个词出现了』，不说明用得对**——语义对不对要另看。


## 赤刃明霄陈（char_1050_chen3）

### 技1「赤霄·奔夜」 `skchr_chen3_1`
- durationType=NONE duration=18.0 sp=20.0/10.0 range=None
- 原文：攻击力+{atk:0%}，攻击变为二连击，攻击使目标敌人特殊能力失效持续至技能结束
- 黑板：atk✓

### 技2「赤霄·绝影-驰」 `skchr_chen3_2`
- durationType=NONE duration=6.0 sp=20.0/15.0 range=x-1
- 原文：对周围最近的1名敌人发动10次斩击，每次造成攻击力{atk_scale:0%}的法术伤害，敌人被击倒时转移至目标周围最近的其他敌人并使剩余攻击次数+1；斩击结束时，若目标未被击倒且其位置可部署则移动至该位置，否则返回原位置。接下来攻击力+{chen3_s2[respawn_buff].atk:0%}，获得{chen3_s2[respawn_buff].prob:0%}物理和法术闪避
- 黑板：atk_scale✓  chen3_s2[respawn_buff].atk✗  chen3_s2[respawn_buff].prob✗
- **模拟器完全没提过的键**：chen3_s2[respawn_buff].atk, chen3_s2[respawn_buff].prob

### 技3「赤霄·天喟」 `skchr_chen3_3`
- durationType=NONE duration=20.0 sp=25.0/18.0 range=3-12
- 原文：技能开启时向前释放一道可转向的剑气，对穿过的敌人造成相当于其当前生命值{hp_ratio:0%}的法术伤害（至少造成自身攻击力{projectile_min_atk_scale:0%}的法术伤害）；攻击范围扩大，每次攻击对最多{attack@max_target}名地面敌人造成3次攻击力{attack@atk_scale:0%}的法术伤害
- **专门实现**：剑气 `_spawn_qi`／`_qi_tick`（向前·遇障碍右转·刷新命中）
- 黑板：attack@atk_scale✓  attack@max_target✓  hp_ratio✓  projectile_min_atk_scale✗
- **模拟器完全没提过的键**：projectile_min_atk_scale

## 予愿安洁莉娜（char_1015_aglna2）

### 技1「极速送达」 `skchr_aglna2_1`
- durationType=NONE duration=60.0 sp=0.0/0.0 range=3-6
- 原文：部署后立刻起飞，攻击范围扩大，攻击力+{atk:0%}，同时攻击两个目标
- 黑板：atk✓  attack@max_target✓

### 技2「重力自定义」 `skchr_aglna2_2`
- durationType=NONE duration=22.0 sp=25.0/21.0 range=3-10
- 原文：攻击范围扩大并向前方滑翔起飞，使掠过的攻击范围内的地面敌人浮空{buff_duration_levitate}秒、飞行敌人缚地{buff_duration_ground_bound}秒，随后攻击间隔较大幅缩短，攻击力+{atk:0%}，攻击变为法术伤害且同时攻击{attack@max_target}个目标
- 黑板：atk✓  attack@max_target✓  base_attack_time✓  buff_duration_ground_bound✗  buff_duration_levitate✗  chant_duration✗  mass_level✗
- **模拟器完全没提过的键**：buff_duration_ground_bound, buff_duration_levitate, chant_duration, mass_level

### 技3「酸橙的心事」 `skchr_aglna2_3`
- durationType=AMMO duration=-1.0 sp=30.0/24.0 range=3-9
- 原文：立刻起飞，攻击力+{atk:0%}，获得{damage_resistance:0%}的对空庇护，攻击范围扩大，且周围8格视作予愿安洁莉娜的额外攻击范围，攻击对{attack@max_walk_target}个敌人造成攻击力{attack@atk_scale:0%}的物理伤害且额外攻击1个飞行敌人；范围内飞行敌人移动速度{move_speed:0%}，原技能范围内有未被阻挡的可阻挡飞行敌人，且自身未阻挡时，移动至该敌人所在格\n攻击装有{attack@trigger_time}发弹药，打完后技能结束（期间可随时停止技能）
- **专门实现**：弹药技 + 起飞（只建模了射程与目标数，未建模飞行/减速）
- 黑板：aglna2_s_3[blocked].attack_speed✗  aglna2_s_3[unblocked].attack_speed✗  atk✓  attack@atk_scale✓  attack@attack_range_id✗  attack@max_target✓  attack@max_walk_target✗  attack@trigger_time✗  damage_resistance✗  move_speed✓
- **模拟器完全没提过的键**：aglna2_s_3[blocked].attack_speed, aglna2_s_3[unblocked].attack_speed, attack@attack_range_id, attack@max_walk_target, attack@trigger_time, damage_resistance

## 凯尔希·思衡托（char_1052_kalts2）

### 技1「应急肃正防线」 `skchr_kalts2_1`
- durationType=NONE duration=35.0 sp=35.0/28.0 range=None
- 原文：攻击力+{atk:0%}，攻击速度+{attack_speed}，所有其他起飞的友方干员阻挡范围扩大
- 黑板：atk✓  attack@block_radius_scale✗  attack_speed✓
- **模拟器完全没提过的键**：attack@block_radius_scale

### 技2「保护性拒止」 `skchr_kalts2_2`
- durationType=AMMO duration=-1.0 sp=35.0/28.0 range=y-11
- 原文：攻击范围扩大，攻击力+{atk:0%}，攻击变为射出医疗单元（优先选择敌人），击中时对目标周围所有敌人造成相当于攻击力{attack@atk_scale:0%}的真实伤害，使其停顿{attack@sluggish}秒并回复目标周围所有友方干员相当于攻击力{attack@heal_scale:0%}的生命\n攻击装有10发弹药，可以随时停止技能
- **专门实现**：弹药技：`duration_type == 'AMMO'` + 真实伤害 + 治疗
- 黑板：atk✓  attack@atk_scale✓  attack@heal_scale✓  attack@sluggish✓  attack@trigger_time✗
- **模拟器完全没提过的键**：attack@trigger_time

### 技3「破梏重生」 `skchr_kalts2_3`
- durationType=NONE duration=35.0 sp=50.0/35.0 range=None
- 原文：立刻获得战术锚点，攻击力+{atk:0%}，攻击间隔大幅缩小，额外治疗1个目标，部署战术锚点后，自身移动至该位置，并使攻击范围内最多2名友方干员可以部署至自身攻击范围的另一位置
- 黑板：atk✓  base_attack_time✓

## 圣聆初雪（char_1046_sbell2）

### 技1「铃音吹雪」 `skchr_sbell2_1`
- durationType=NONE duration=-1.0 sp=12.0/12.0 range=None
- 原文：立即对范围内所有敌人造成相当于攻击力{atk_scale:0%}的法术伤害及{cold}秒寒冷并将其中等力度地朝部署方向推动，之后积雪向前方地面扩散（最多向前扩散5格）\n可充能2次
- 黑板：atk_scale✓  cold✓  force✗  trig_cnt✗
- **模拟器完全没提过的键**：force, trig_cnt

### 技2「霜涛覆岭」 `skchr_sbell2_2`
- durationType=NONE duration=-1.0 sp=45.0/0.0 range=None
- 原文：每次攻击造成相当于攻击力{attack@atk_scale_s2:0%}的法术伤害，积雪超过5层时会向周围扩散一层（最多向外扩散20格），处于积雪上的地面敌人每秒受到攻击力{talent@s2_magic_scale:0%}的法术伤害，敌人离开积雪时获得5秒寒冷，积雪在目标点积累至5层时，使目标点变为冻结状态\n持续时间无限，可主动关闭技能（期间可随时停止技能）
- **专门实现**：积雪 `_snow_tick`（含冻结与离开积雪的寒冷）
- 黑板：attack@atk_scale_s2✗  talent@cold✓  talent@max_cast_tile_count✓  talent@s2_magic_scale✓  talent@token_key✗
- **模拟器完全没提过的键**：attack@atk_scale_s2, talent@token_key

### 技3「群山俯首」 `skchr_sbell2_3`
- durationType=NONE duration=35.0 sp=50.0/42.0 range=x-2
- 原文：攻击范围扩大，立即诱导攻击范围内的所有敌人至自身周围的可达地面，持续{attract_time}秒，积雪生成速度加快，攻击力+{atk:0%}，攻击速度+{attack_speed}，攻击无视目标10点法术抗性，每次攻击造成相当于攻击力{attack@atk_scale_s3:0%}的法术伤害
- 黑板：atk✓  attack@atk_scale_s3✗  attack_speed✓  attract_time✗  interval✓  magic_resist_penetrate_fixed✗
- **模拟器完全没提过的键**：attack@atk_scale_s3, attract_time, magic_resist_penetrate_fixed

## 望（char_2027_wang）

### 技1「取势」 `skchr_wang_1`
- durationType=NONE duration=-1.0 sp=16.0/0.0 range=None
- 原文：被动效果：棋子触发时使目标敌人停顿且每秒受到相当于望攻击力的{attack@atk_scale:0%}的法术伤害，持续{attack@sluggish}秒\n主动效果：立即获得两枚棋子
- 黑板：attack@atk_scale✓  attack@sluggish✓  cnt✓

### 技2「连星」 `skchr_wang_2`
- durationType=NONE duration=-1.0 sp=15.0/0.0 range=None
- 原文：被动效果：棋子触发时，对连线方向上两侧3格范围内的敌人造成相当于攻击力的{attack@atk_scale:0%}的法术伤害，并使其{attack@duration}秒内移动速度降低{display_move_speed:0%}\n主动效果：立即获得两枚棋子
- 黑板：attack@atk_scale✓  attack@duration✓  attack@move_speed✓  cnt✓  display_move_speed✗
- **模拟器完全没提过的键**：display_move_speed

### 技3「天下劫」 `skchr_wang_3`
- durationType=AMMO duration=-1.0 sp=50.0/38.0 range=4-12
- 原文：被动效果：棋子的触发和伤害范围扩大，造成相当于攻击力{atk_scale:0%}的法术伤害\n主动效果：停止攻击但攻击范围扩大；立即获得{cnt}枚棋子，然后将超出上限的棋子优先部署在范围内敌人所在位置；在攻击范围内手动部署棋子时可部署至敌人所在位置，且第一天赋额外至多部署3枚棋子并消耗等量弹药\n装有{trigger_time}发弹药，手动停止或棋子耗尽后技能结束，剩余的弹药返还为棋子
- 黑板：ammo_discard_limit_count✗  atk_scale✓  cnt✓  trigger_time✗
- **模拟器完全没提过的键**：ammo_discard_limit_count, trigger_time

## 逻各斯（char_4133_logos）

### 技1「殁亡」 `skchr_logos_1`
- durationType=NONE duration=-1.0 sp=60.0/0.0 range=3-3
- 原文：攻击范围扩大，攻击力+{atk:0%}，使攻击范围内生命值低于逻各斯攻击力{attack@kill_atk_scale:0%}的敌人立刻倒下、并对另一个随机目标造成与倒下单位生命值相等的法术伤害\n持续时间无限
- 黑板：atk✓  attack@kill_atk_scale✗  attack@kill_damage✗
- **模拟器完全没提过的键**：attack@kill_atk_scale, attack@kill_damage

### 技2「提喻」 `skchr_logos_2`
- durationType=NONE duration=20.0 sp=30.0/20.0 range=None
- 原文：法术抗性+{magic_resistance}，攻击改为锁定一个目标对其每{attack@cooldown}秒造成一次相当于攻击力{attack@atk_scale_base:0%}的法术伤害，对相同目标的伤害逐渐提高至3倍并使其移动速度逐渐降低至40%(锁定5秒后达到上限)，被打断或目标倒下时重新索敌且效果重置
- 黑板：attack@atk_scale_base✗  attack@atk_scale_delta✗  attack@cooldown✓  attack@max_stack_cnt✗  attack@move_speed✓  magic_resistance✓
- **模拟器完全没提过的键**：attack@atk_scale_base, attack@atk_scale_delta, attack@max_stack_cnt

### 技3「延异视阈」 `skchr_logos_3`
- durationType=NONE duration=30.0 sp=45.0/30.0 range=3-4
- 原文：攻击范围扩大，攻击力+{atk:0%}，同时攻击{attack@max_target}个目标，使攻击范围内敌方子弹的飞行速度大幅降低、并在技能结束时将其全部清除
- 黑板：atk✓  attack@max_target✓  projectile_move_scale✗
- **模拟器完全没提过的键**：projectile_move_scale

## 提丰（char_2012_typhon）

### 技1「迅捷打击·γ型」 `skcom_quickattack[3]`
- durationType=NONE duration=35.0 sp=35.0/15.0 range=None
- 原文：攻击力+{atk:0%}，攻击速度+{attack_speed}
- 黑板：atk✓  attack_speed✓

### 技2「冰原秩序」 `skchr_typhon_2`
- durationType=NONE duration=20.0 sp=50.0/42.0 range=None
- 原文：攻击力+{atk:0%}，每次攻击发射两支箭矢（优先攻击不同目标），并有{attack@prob:0%}概率晕眩目标{attack@stun}秒\n第二次及以后使用时持续时间无限
- 黑板：atk✓  attack@prob✗  attack@stun✗  first_duration✗
- **模拟器完全没提过的键**：attack@prob, attack@stun, first_duration

### 技3「“永恒狩猎”」 `skchr_typhon_3`
- durationType=AMMO duration=-1.0 sp=40.0/25.0 range=None
- 原文：立刻标记攻击范围内的一名目标，攻击间隔大幅增大，攻击变为对标记目标发射一轮箭雨；箭雨会随机攻击标记目标周围的敌人，共造成{attack@s3_max_hit_num}次相当于攻击力{attack@s3_atk_scale:0%}的物理伤害并使目标晕眩{attack@s3_stun}秒\n攻击装有{attack@s3_trigger_time}发弹药，打完后结束（可随时停止技能）
- 黑板：attack@s3_atk_scale✗  attack@s3_max_hit_num✗  attack@s3_stun✗  attack@s3_trigger_time✗  base_attack_time✓
- **模拟器完全没提过的键**：attack@s3_atk_scale, attack@s3_max_hit_num, attack@s3_stun, attack@s3_trigger_time

## 阿米娅（char_002_amiya）

### 技1「战术咏唱·γ型」 `skcom_magic_rage[3]`
- durationType=NONE duration=30.0 sp=30.0/15.0 range=None
- 原文：攻击速度+{attack_speed}
- 黑板：attack_speed✓

### 技2「精神爆发」 `skchr_amiya_2`
- durationType=NONE duration=25.0 sp=100.0/0.0 range=None
- 原文：每次攻击变为攻击力{attack@atk_scale:0%}的{attack@times}连发，随机攻击范围内的目标\n技能自动开启，持续时间结束后阿米娅晕眩{stun}秒
- 黑板：attack@atk_scale✓  attack@times✗  stun✗
- **模拟器完全没提过的键**：attack@times, stun

### 技3「奇美拉」 `skchr_amiya_3`
- durationType=NONE duration=30.0 sp=120.0/0.0 range=3-4
- 原文：攻击力+{atk:0%}，生命上限+{max_hp:0%}，攻击范围扩大，伤害类型变为真实\n技能结束后阿米娅强制退出战场
- 黑板：atk✓  max_hp✓

## 清流（char_385_finlpp）

### 技1「治愈水波」 `skchr_finlpp_1`
- durationType=NONE duration=0.0 sp=20.0/10.0 range=None
- 原文：立即恢复攻击范围内所有友方单位相当于攻击力{heal_scale:0%}的生命
- 黑板：heal_scale✓

### 技2「涌泉」 `skchr_finlpp_2`
- durationType=NONE duration=25.0 sp=60.0/30.0 range=None
- 原文：攻击间隔大幅度缩短，每次随机回复攻击范围内已受伤的一名单位相当于攻击力{attack@heal_scale:0%}的生命值
- 黑板：attack@heal_scale✓  base_attack_time✓

## 调香师（char_181_flower）

### 技1「治疗强化·β型」 `skcom_heal_up[2]`
- durationType=NONE duration=25.0 sp=30.0/10.0 range=None
- 原文：攻击力+{atk:0%}
- 黑板：atk✓

### 技2「精调」 `skchr_flower_2`
- durationType=NONE duration=30.0 sp=60.0/20.0 range=None
- 原文：攻击速度-{-attack_speed}，攻击力+{atk:0%}
- 黑板：atk✓  attack_speed✓

## 嘉维尔（char_187_ccheal）

### 技1「活力再生」 `skchr_ccheal_1`
- durationType=NONE duration=-1.0 sp=8.0/0.0 range=None
- 原文：下次治疗时为目标增加一个增益，每秒持续恢复相当于嘉维尔攻击力{heal_scale:0%}（血量低于一半时为{heal_scale_2:0%}）的生命，持续{duration}秒\n可充能{ct}次
- 黑板：ct✓  duration✓  heal_scale✓  heal_scale_2✗  hp_ratio✓  interval✓
- **模拟器完全没提过的键**：heal_scale_2

### 技2「活力再生·广域」 `skchr_ccheal_2`
- durationType=NONE duration=-1.0 sp=60.0/50.0 range=None
- 原文：立即为攻击范围内所有友方单位增加一个增益，每秒持续恢复相当于嘉维尔攻击力{heal_scale:0%}（血量低于一半时为{heal_scale_2:0%}）的生命，持续{duration}秒
- 黑板：duration✓  heal_scale✓  heal_scale_2✗  hp_ratio✓  interval✓
- **模拟器完全没提过的键**：heal_scale_2

## 机械师（char_4230_mcnist）

### 技1「聚类分析」 `skchr_mcnist_1`
- durationType=AMMO duration=-1.0 sp=7.0/0.0 range=None
- 原文：攻击间隔增大，攻击变为五连击的群体攻击，每次造成攻击力{attack@atk_scale:0%}的范围物理伤害\n攻击装有{attack@trigger_time}发弹药，打完后结束（可随时停止技能）
- 黑板：attack@atk_scale✓  attack@interval✓  attack@projectile_delay_time✗  attack@projectile_range✗  attack@times✗  attack@trigger_time✗  base_attack_time✓
- **模拟器完全没提过的键**：attack@projectile_delay_time, attack@projectile_range, attack@times, attack@trigger_time

### 技2「协防术式」 `skchr_mcnist_2`
- durationType=AMMO duration=-1.0 sp=50.0/35.0 range=None
- 原文：攻击力+{atk:0%}，自身和结构性原理立刻获得最大生命{hp_ratio:0%}的屏障，屏障被摧毁时对周围敌人造成攻击力{atk_scale:0%}的法术伤害和{not_combat}秒的战栗，并消耗1发弹药再次获得屏障\n攻击装有{trigger_time}发弹药，打完后结束（可随时停止技能）
- 黑板：atk✓  atk_scale✓  hp_ratio✓  not_combat✗  range_radius✓  trigger_time✗
- **模拟器完全没提过的键**：not_combat, trigger_time

### 技3「工程学十字星」 `skchr_mcnist_3`
- durationType=NONE duration=40.0 sp=35.0/25.0 range=None
- 原文：攻击力+{atk:0%}，攻击间隔大幅增大，攻击变为对十字范围内所有敌人造成攻击力{attack@atk_scale:0%}的法术伤害，可攻击结构性原理阻挡的目标\n结构性原理向前方冲锋，碰到敌人或高台时对范围内所有敌人造成机械师攻击力{atk_scale:0%}的物理伤害并停下，周围的敌人获得逐渐衰减的50%的虚弱效果
- 黑板：atk✓  atk_scale✓  attack@atk_scale✓  attack@projectile_range✗  base_attack_time✓  projectile_range✗
- **模拟器完全没提过的键**：attack@projectile_range, projectile_range

## 星熊（char_136_hsguma）

### 技1「战意」 `skchr_hsguma_1`
- durationType=NONE duration=30.0 sp=40.0/20.0 range=None
- 原文：防御力+{def:0%}，攻击力+{atk:0%}
- 黑板：atk✓  def✓

### 技2「荆棘」 `skchr_hsguma_2`
- durationType=NONE duration=0.0 sp=0.0/0.0 range=None
- 原文：防御力+{def:0%}\n每次受到攻击时对目标造成相当于星熊攻击力{atk_scale:0%}的物理伤害
- 黑板：atk_scale✓  def✓

### 技3「力之锯」 `skchr_hsguma_3`
- durationType=NONE duration=25.0 sp=50.0/30.0 range=None
- 原文：攻击力+{atk:0%}，防御力+{def:0%}，对前方一格的所有敌人使用盾牌进行切割
- 黑板：atk✓  def✓
