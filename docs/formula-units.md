# 描述里黑板键的量纲清单

> 由 `python tools/unit_audit.py` 生成，勿手改；判据定义见 `ak_tactic/formula.py` 的 `Num.unit`。
>
> **最后一栏 `裁定` 是给人填的**，重新生成时会被读回续用，不会冲掉。填 `绝对值` / `固定值`（两者同义，都是 FLAT）、`比例` / `倍率` / `存疑`，也可写自由文本。`所属干员` 是那条例句的出处（先回它的原文核对）；只出现在召唤物/生息演算建筑上的键标作 `装置「…」`，那不是人。
>
> 已落地的裁定会并入 `ak_tactic/formula.py` 的 `RULED_FLAT_KEYS`（判据是人给的，与从语料核出来的 `FLAT_KEYS` 分开放）。**填了却没被采纳的会列在文末**——那是因为数据与裁定相反，需要复核。

语料 14967 条，描述里出现的**占位符键 535 种、共 23753 次**。

## 一、判定结果总览

| 量纲 | 键数 | 出现次数 | 含义 |
|---|---:|---:|---|
| RATIO | 290 | 14745 | 黑板里的比例/倍率，0.14 → 14%、2.1 → 210% |
| FLAT | 233 | 8895 | 绝对值，8 就是 8（秒/点/格/个/层） |
| SCALE | 9 | 110 | 「提升至 N 倍」的倍率，1.4 → 1.4 倍 |
| UNKNOWN | 3 | 3 | **判不出**，需人工裁定（见第二节） |

其中靠**上下文邻字**（`秒 / 点 / 格 / 名 / 个 / 次 / 层 / 枚 / 发 / 份 / 颗 / 倍`）救回的有 172 种、2272 次——这些键名本身毫无线索，单位写在它后面那个字里。

## 二、仍需博士裁定的键（判不出量纲）

共 3 种、3 次。下表按出现次数降序；`我的建议` 一栏为空即表示键名与上下文都没线索，`裁定` 一栏请填。

| 键名 | 次数 | 说明符 | 来源 | 所属干员 | 出现语境 | 我的建议 | 裁定 |
|---|---:|---|---|---|---|---|---|
| `sell_card_gold` | 1 | (空)×1 | skill×1 | 装置「改派发讯器」 | num}名单位使其消失（本场战斗不再出现）且转换为{sell_card_gold}调用凭证。\n |  |  |
| `exp` | 1 | (空)×1 | skill×1 | 装置「祭坛式雷达」 | 从周围每个敌方单位获取{exp}调查熟练度（同一个敌方单位只触发一次 |  |  |
| `attack@exp` | 1 | (空)×1 | skill×1 | 装置「“二踢脚”型数据收集装置」 | ck@damage}法术伤害，并对每个敌方单位获取{attack@exp}调查熟练度 |  |  |

## 三、**同一键被判出两种量纲**的键（最该先看）

共 1 种。这类键要么是**同键不同义**（数据侧的问题），要么是我的判据在某个语境下判错了——两种都必须由人看一眼。

| 键名 | 各量纲出现次数 | 次数 | 所属干员 | 语境 | 裁定 |
|---|---|---:|---|---|---|
| `value` | FLAT×246/RATIO×59 | 305 | 桃金娘（共 41 人） | 停止攻击，持续时间内回复总共{value}点部署费用 | 固定值 |

## 四、上下文判定的键（抽查用）

这些键的量纲是**按邻字**定的，不是按键名。请重点抽查有没有「邻字是点、实际却是比例」这类反例。

| 键名 | 判为 | 邻字 | 次数 | 所属干员 | 语境 | 裁定 |
|---|---|---|---:|---|---|---|
| `sleep` | FLAT | FLAT | 50 | 爱丽丝（共 5 人） | 范围内的至多{max_target}个敌人陷入沉睡{sleep}秒，在其醒来时会对周围小范围内所 | 固定值 |
| `levitate` | FLAT | FLAT | 50 | 岳羽由加莉（共 3 人） | k_scale:0%}的范围法术伤害并浮空所有目标{levitate}秒 | 固定值 |
| `sp` | FLAT | FLAT | 47 | 莱伊（共 12 人） | tion}秒\n技能期间若击倒敌人，技能结束时获得{sp}点技力 | 固定值 |
| `attack@silence` | FLAT | FLAT | 40 | 孑（共 4 人） | 攻击力+{atk:0%}，攻击目标失去特殊能力{attack@silence}秒\n持续时间 | 固定值 |
| `constraint` | FLAT | FLAT | 40 | 罗宾（共 2 人） | {atk_scale:0%}的物理伤害，并使其束缚{constraint}秒\n主动效果：立即获 | 固定值 |
| `cold` | FLAT | FLAT | 34 | 凛御银灰（共 3 人） | 攻击力{atk_scale:0%}的物理伤害，使其{cold}秒内寒冷且隐匿失效；待部署区中距离 | 固定值 |
| `multi_times` | FLAT | FLAT | 30 | 火龙S黑角（共 2 人） | 一次受到攻击时抵挡此次伤害并选择范围内一名敌人造成{multi_times}次相当于攻击力{mu | 固定值 |
| `attack@cold` | FLAT | FLAT | 30 | 耶拉（共 3 人） | 击有{attack@prob:0%}概率对敌人造成{attack@cold}秒寒冷。\n浮游单元 | 固定值 |
| `scale_delta_to_one` | SCALE | SCALE | 30 | 巫恋（共 3 人） | 攻击力+{atk:0%}，天赋的伤害加成提升至{scale_delta_to_one:0.0 | 倍率 |
| `attack@sp` | FLAT | FLAT | 30 | 掠风（共 2 人） | e:0%}的物理伤害，并为所有可靠电池的装备者回复{attack@sp}点技力\n可充能{ct} | 固定值 |
| `attack@fear` | FLAT | FLAT | 30 | 荒芜拉普兰德（共 2 人） | 时有{attack@prob:0%}几率使目标恐惧{attack@fear}秒\n浮游单元在锁定 | 固定值 |
| `ABILITY_RANGE_FORWARD_EXTEND` | FLAT | FLAT | 27 | 安赛尔（共 3 人） | 攻击范围+{ABILITY_RANGE_FORWARD_ | 固定值 |
| `buff_duration` | FLAT | FLAT | 22 | 响石 | hp_ratio:0%}最大生命值的屏障（屏障持续{buff_duration}秒，最多不超过生 | 固定值 |
| `shield_duration` | FLAT | FLAT | 21 | 摩根（共 2 人） | 大生命{hp_ratio:0%}的屏障（该屏障会在{shield_duration}秒内持续衰减 | 固定值 |
| `HP_RECOVERY_PER_SEC` | FLAT | FLAT | 20 | 角峰（共 2 人） | 生命上限+{max_hp:0%}，每秒恢复{HP_RECOVERY_PER_SEC}点生 | 固定值 |
| `blkngt_s_2.duration` | FLAT | FLAT | 20 | 夜半 | 立即使战术点周围的所有地面敌人陷入{blkngt_s_2.duration}秒沉 | 固定值 |
| `attack@frozen_duration` | FLAT | FLAT | 20 | 奥斯塔（共 2 人） | 增大，攻击力+{atk:0%}且每次攻击令目标束缚{attack@frozen_duration | 固定值 |
| `levitate_duration` | FLAT | FLAT | 20 | 雪绒（共 2 人） | ger_atk_scale:0%}的法术伤害并浮空{levitate_duration}秒，目标 | 固定值 |
| `attack@buff_duration` | FLAT | FLAT | 20 | 录武官（共 2 人） | atk:0%}，治疗干员后为其施加一个增益，使其在{attack@buff_duration}秒 | 固定值 |
| `status_resistance[limit]` | FLAT | FLAT | 20 | 絮雨（共 2 人） | 优先选择处于异常状态中的单位）并使其获得抵抗，持续{status_resistance[limi | 固定值 |
| `silence` | FLAT | FLAT | 20 | 槐琥（共 2 人） | ale:0%}的物理伤害，并使命中目标失去特殊能力{silence}秒 | 固定值 |
| `not_combat` | FLAT | FLAT | 20 | 折桠（共 2 人） | 技能开启时使自身周围的地面敌人战栗{not_combat}秒；攻击力+{atk: | 固定值 |
| `max_cnt` | FLAT | FLAT | 20 | 守林人（共 2 人） | 立即对攻击范围内随机投下{max_cnt}枚炸弹进行轰炸（优先选择有敌 | 固定值 |
| `attack@projectile_life_time` | FLAT | FLAT | 20 | 假日威龙陈 | 攻击力+{atk:0%}，每次攻击在范围内生成持续{attack@projectile_life | 固定值 |
| `cost_period` | FLAT | FLAT | 20 | 可露希尔 | 立即获得{cost}点部署费用，持续时间内逐渐获得{cost_period}点部署费用，自身的援 | 固定值 |
| `max_trigger_cnt` | FLAT | FLAT | 20 | 可露希尔（共 2 人） | rigger_cnt}次后攻击目标数+1（最多触发{max_trigger_cnt}次） | 固定值 |
| `attack@steal_atk_speed` | FLAT | FLAT | 20 | 伊内丝（共 2 人） | 隐匿，每次攻击获得{cost}点部署费用并偷取目标{attack@steal_atk_speed | 固定值 |
| `attack@steal_atk_speed_max` | FLAT | FLAT | 20 | 伊内丝（共 2 人） | @steal_atk_speed}点攻击速度（最多{attack@steal_atk_speed | 固定值 |
| `sp_cost` | FLAT | FLAT | 20 | 玛露西尔 | 短暂吟唱后开启技能，每次攻击消耗{sp_cost}点魔力，攻击力+{atk:0 | 固定值 |
| `chant_duration` | FLAT | FLAT | 20 | 玛露西尔 | 吟唱{chant_duration}秒后，消耗{s | 固定值 |
| `attack@levitate` | FLAT | FLAT | 20 | 霍尔海雅 | 有{attack@prob:0%}的概率使目标浮空{attack@levitate}秒 | 固定值 |
| `chain_times` | FLAT | FLAT | 20 | 真言 | @atk_scale:0%}的法术伤害并跳跃至其他{chain_times}名敌人造成攻击力{a | 固定值 |
| `buff_time` | FLAT | FLAT | 20 | 酒神 | 领袖）10秒，首个目标到达后撤退并使周围所有敌人在{buff_time}秒内停顿、每{inter | 固定值 |
| `interval_damage` | FLAT | FLAT | 20 | 酒神 | 使周围所有敌人在{buff_time}秒内停顿、每{interval_damage}秒受到酒神攻 | 固定值 |
| `duration_2` | FLAT | FLAT | 20 | 多萝西 | ation}秒,如果陷阱只命中1名敌人，则使其束缚{duration_2}秒\n主动效果：立即获 | 固定值 |
| `cooldown` | FLAT | FLAT | 20 | 焰影苇草（共 2 人） | 先使一名部署在地面的干员获得三颗火球，效果如下：每{cooldown}秒对一名敌人造成相当于焰影 | 固定值 |
| `attack@sleep` | FLAT | FLAT | 20 | 缇缇 | 击有{attack@prob:0%}概率使目标沉睡{attack@sleep}秒 | 固定值 |
| `before_dead_duration` | FLAT | FLAT | 20 | 斩业星熊 | ck@max_target}名敌人；主动关闭技能后{before_dead_duration}秒 | 固定值 |
| `stun_duration` | FLAT | FLAT | 15 | 维什戴尔 | 下次攻击额外造成2次余震并使所有目标晕眩{stun_duration}秒，此次攻击的溅 | 固定值 |
| `attack@chain.max_target` | FLAT | FLAT | 15 | 溯光星源（共 2 人） | {atk:0%}，攻击可在敌人间重复跳跃，最多跳跃{attack@chain.max_targe | 固定值 |
| `magic_resist_penetrate_fixed` | FLAT | FLAT | 15 | 艾雅法拉（共 5 人） | 无视目标{magic_resist_penetrate | 固定值 |
| `enhance_duration` | FLAT | FLAT | 12 | 龙舌兰 | 蓄力额外效果：改为同时攻击3名敌人，持续时间延长为{enhance_duration}秒\n可主 | 固定值 |
| `attack@damage` | FLAT |  | 12 | 赫德雷 | }点生命，并使自身攻击过和攻击过自身的敌人每秒受到{attack@damage}点真实伤害；攻击 | 固定值 |
| `time` | FLAT | FLAT | 10 | 远山 | 击攻击范围内所有敌人\n技能时间结束后远山停止攻击{time}秒 | 固定值 |
| `blackd_s_2[period].trig_cnt` | FLAT | FLAT | 10 | 讯使 | ].cost}点部署费用\n技能持续期间内逐渐获得{blackd_s_2[period].tri | 固定值 |
| `success.silence` | FLAT | FLAT | 10 | 断罪者 | atk_scale:0%}的法术伤害并失去特殊能力{success.silence}秒\n有{p | 固定值 |
| `failure.stun` | FLAT | FLAT | 10 | 断罪者 | %}的几率失败，失败时范围内的所有友方单位全部晕眩{failure.stun}秒 | 固定值 |
| `debuff` | FLAT | FLAT | 10 | 霜叶 | ed:0%}，并有{prob:0%}的几率使其束缚{debuff}秒 | 固定值 |
| `attack@s2_stun` | FLAT | FLAT | 10 | 石英 | ck@s2_buff_prob:0%}概率晕眩目标{attack@s2_stun}秒 | 固定值 |
| `cost_display` | FLAT | FLAT | 10 | 裁度 | scale:0%}的物理伤害；技能开启期间逐渐消耗{cost_display}点部署费用 | 固定值 |
| `attack@final_duration` | FLAT | FLAT | 10 | 瑰盐 | uce_scale_display:0%}变为持续{attack@final_duration} | 固定值 |
| `disarm` | FLAT | FLAT | 10 | 古米 | 开始烹饪，{disarm}秒内停止攻击敌人，防御力+{d | 固定值 |
| `talent@prob_scaler` | SCALE | SCALE | 10 | 红隼 | ttack_speed}，第一天赋的触发几率提升至{talent@prob_scaler:0.0 | 倍率 |
| `attack@heal_max_target` | FLAT | FLAT | 10 | 嘉辛塔 | alent_scale}倍，并每秒治疗天赋范围内的{attack@heal_max_target | 固定值 |
| `mitm_s_2[cost].display` | FLAT | FLAT | 10 | 渡桥 | 技能持续时间内逐渐获得{mitm_s_2[cost].display | 固定值 |
| `floor` | FLAT | FLAT | 10 | 齐尔查克 | 停止攻击，技能结束后随机获得{ground}-{floor}点部署费用 | 固定值 |
| `def_steal` | FLAT | FLAT | 10 | 寻澜 | }，每次攻击获得{cost}点部署费用，并偷取目标{def_steal}点防御力。（最多{def | 固定值 |
| `def_steal_max` | FLAT | FLAT | 10 | 寻澜 | ，并偷取目标{def_steal}点防御力。（最多{def_steal_max}点，持续至技能结 | 固定值 |
| `attack@levitate_duration` | FLAT | FLAT | 10 | 奥达 | :0%}，攻击溅射到重量小于等于3的单位会使其浮空{attack@levitate_durati |  |
| `attack@max_stack_count` | FLAT | FLAT | 10 | 寒芒克洛丝 | 攻击间隔略微缩短，攻击变为2连射，击中目标{attack@max_stack_count |  |
| `skill_max_trigger_time` | FLAT | FLAT | 10 | 淬羽赫默 | ration}秒内不低于1\n同一次作战中最多使用{skill_max_trigger_time | 固定值 |

## 五、已采纳的裁定台账（判据已进 `RULED_FLAT_KEYS`）

这些键的量纲已按裁定定死，故不再出现在上面三节里。**原文留在此处**，改判据时按这张表回查。

| 键名 | 量纲 | 语料出现次数 | 所属干员 | 裁定 |
|---|---|---:|---|---|
| `ABILITY_RANGE_FORWARD_EXTEND` | FLAT | 27 | 安赛尔（共 3 人） | 固定值 |
| `HP_RECOVERY_PER_SEC` | FLAT | 20 | 角峰（共 2 人） | 固定值 |
| `ability_range_forward_extend` | FLAT | 150 | 安比尔（共 14 人） | （并入时原文未留） |
| `attack@buff_duration` | FLAT | 20 | 录武官（共 2 人） | 固定值 |
| `attack@chain.extra_value` | FLAT | 30 | 明椒（共 3 人） | 绝对值 |
| `attack@chain.max_target` | FLAT | 15 | 溯光星源（共 2 人） | 固定值 |
| `attack@cold` | FLAT | 30 | 耶拉（共 3 人） | 固定值 |
| `attack@damage` | FLAT | 12 | 赫德雷 | 固定值 |
| `attack@def_penetrate_fixed` | FLAT | 10 | 罗小黑 | 绝对值 |
| `attack@fear` | FLAT | 30 | 荒芜拉普兰德（共 2 人） | 固定值 |
| `attack@final_duration` | FLAT | 10 | 瑰盐 | 固定值 |
| `attack@frozen_duration` | FLAT | 20 | 奥斯塔（共 2 人） | 固定值 |
| `attack@heal_max_target` | FLAT | 10 | 嘉辛塔 | 固定值 |
| `attack@levitate` | FLAT | 20 | 霍尔海雅 | 固定值 |
| `attack@max_target_heal_add` | FLAT | 4 | 遥 | 固定值 |
| `attack@poison_damage` | FLAT | 10 | 伊桑 | 固定值 |
| `attack@projectile_life_time` | FLAT | 20 | 假日威龙陈 | 固定值 |
| `attack@s2_stun` | FLAT | 10 | 石英 | 固定值 |
| `attack@silence` | FLAT | 40 | 孑（共 4 人） | 固定值 |
| `attack@sleep` | FLAT | 20 | 缇缇 | 固定值 |
| `attack@sp` | FLAT | 30 | 掠风（共 2 人） | 固定值 |
| `attack@steal_atk_speed` | FLAT | 20 | 伊内丝（共 2 人） | 固定值 |
| `attack@steal_atk_speed_max` | FLAT | 20 | 伊内丝（共 2 人） | 固定值 |
| `attack_speed_extra` | FLAT | 10 | 佩佩 | 固定值 |
| `before_dead_duration` | FLAT | 20 | 斩业星熊 | 固定值 |
| `blackd_s_2[period].trig_cnt` | FLAT | 10 | 讯使 | 固定值 |
| `blkngt_s_2.duration` | FLAT | 20 | 夜半 | 固定值 |
| `block_cnt_display` | FLAT | 10 | 渡桥 | 固定值 |
| `buff_duration` | FLAT | 22 | 响石 | 固定值 |
| `buff_time` | FLAT | 20 | 酒神 | 固定值 |
| `chain_times` | FLAT | 20 | 真言 | 固定值 |
| `chant_duration` | FLAT | 20 | 玛露西尔 | 固定值 |
| `cold` | FLAT | 34 | 凛御银灰（共 3 人） | 固定值 |
| `constraint` | FLAT | 40 | 罗宾（共 2 人） | 固定值 |
| `cooldown` | FLAT | 20 | 焰影苇草（共 2 人） | 固定值 |
| `cost_decrease` | FLAT | 10 | 松桐 | 绝对值，原文此处是固定的“费用-1” |
| `cost_display` | FLAT | 10 | 裁度 | 固定值 |
| `cost_per_add` | FLAT | 10 | 可露希尔 | 固定值 |
| `cost_period` | FLAT | 20 | 可露希尔 | 固定值 |
| `damage` | FLAT | 27 | 阿 | 绝对值（攻击力） |
| `damage_value` | FLAT | 10 | 和弦 | 固定值 |
| `debuff` | FLAT | 10 | 霜叶 | 固定值 |
| `def_penetrate_fixed` | FLAT | 67 | 松果（共 13 人） | 绝对值 |
| `def_steal` | FLAT | 10 | 寻澜 | 固定值 |
| `def_steal_max` | FLAT | 10 | 寻澜 | 固定值 |
| `disarm` | FLAT | 10 | 古米 | 固定值 |
| `duration_2` | FLAT | 20 | 多萝西 | 固定值 |
| `e_attack_speed` | FLAT | 10 | 黍 | 固定值 |
| `enhance_duration` | FLAT | 12 | 龙舌兰 | 固定值 |
| `failure.stun` | FLAT | 10 | 断罪者 | 固定值 |
| `fear` | FLAT | 10 | 妮芙 | （并入时原文未留） |
| `floor` | FLAT | 10 | 齐尔查克 | 固定值 |
| `ground` | FLAT | 10 | 齐尔查克 | 固定值 |
| `interval_damage` | FLAT | 20 | 酒神 | 固定值 |
| `levitate` | FLAT | 50 | 岳羽由加莉（共 3 人） | 固定值 |
| `levitate_duration` | FLAT | 20 | 雪绒（共 2 人） | 固定值 |
| `magic_resist_penetrate_fixed` | FLAT | 15 | 艾雅法拉（共 5 人） | 固定值 |
| `max_cnt` | FLAT | 20 | 守林人（共 2 人） | 固定值 |
| `max_target_shield_add` | FLAT | 4 | 遥 | 固定值 |
| `max_trigger_cnt` | FLAT | 20 | 可露希尔（共 2 人） | 固定值 |
| `mitm_s_2[cost].display` | FLAT | 10 | 渡桥 | 固定值 |
| `multi_times` | FLAT | 30 | 火龙S黑角（共 2 人） | 固定值 |
| `not_combat` | FLAT | 20 | 折桠（共 2 人） | 固定值 |
| `shield_duration` | FLAT | 21 | 摩根（共 2 人） | 固定值 |
| `silence` | FLAT | 20 | 槐琥（共 2 人） | 固定值 |
| `sleep` | FLAT | 50 | 爱丽丝（共 5 人） | 固定值 |
| `sp` | FLAT | 47 | 莱伊（共 12 人） | 固定值 |
| `sp_cost` | FLAT | 20 | 玛露西尔 | 固定值 |
| `status_resistance[limit]` | FLAT | 20 | 絮雨（共 2 人） | 固定值 |
| `stun_duration` | FLAT | 15 | 维什戴尔 | 固定值 |
| `success.silence` | FLAT | 10 | 断罪者 | 固定值 |
| `time` | FLAT | 10 | 远山 | 固定值 |
| `value` | FLAT | 305 | 桃金娘（共 41 人） | 固定值 |
