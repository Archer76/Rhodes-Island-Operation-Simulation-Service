// wire.go：`sim` 请求的**规格**与应答的**判决**。
//
// 这份结构是 Python 与 Go 之间唯一的契约，设计原则只有一条：
// **数字由 Python 算完送来，Go 只负责把它们推成结果。**
//
// 于是这里读不到数据库、读不到名册、也读不到技能表——一个字段都没有"再去查一下"
// 的余地。练度折算、技能效果解析、寻路，全都在 Python 侧完成（那条链已经有三关
// 基线与 793 项自检钉着）；Go 侧只保留"时间怎么走、谁打到谁、死了没有"。
//
// 规格里 `unsupported` 一旦非空，Go 就**拒跑**（返回错误而不是判决）：这一版是
// 最小版本，只覆盖"常规关卡 + 无手动开技能 + 无装置/召唤/位移/控制"。宁可让
// 对拍台看见一句"这一局还不支持"，也不能让它拿一份缺了机制的结果去和原版对齐
// ——那种"对齐"会把 bug 固化成基线。
package main

import "encoding/json"

// Spec 是一场战斗的完整输入。
type Spec struct {
	Stage    string  `json:"stage"`
	FPS      int     `json:"fps"`
	MaxTime  float64 `json:"max_time"`
	Life     int     `json:"life"`
	CostInit float64 `json:"cost_init"`
	CostMax  float64 `json:"cost_max"`
	//: 每回 1 点费用的秒数（`1 / costRecoverySpeed`，已折算关卡的回复速度乘区）
	CostTime float64 `json:"cost_time"`
	//: 敌人出手后原地停顿的秒数（`enemy_windup`）
	EnemyWindup   float64 `json:"enemy_windup"`
	RangedEnemies bool    `json:"ranged_enemies"`
	//: 位移速度乘区（`speed_scale`，含关卡 `move_multiplier`）
	SpeedScale float64 `json:"speed_scale"`
	//: 高台格（`[x, y]` 列表）。Go 没有地图，而天赋「汹涌怒火」的高台那一半
	//: 要判"被溅射到的格是不是高台"——这份几何由 Python 随规格送来。
	//: 不在表里就当没高台（高台溅射那一段因此整段不发生）。
	HighlandCells [][2]int `json:"highland_cells,omitempty"`

	//: 防守点格（`tile_end`）。Go 没有地图，而积雪的**满层冻结**要判
	//: "这一格是不是终点"——终点格豁免（原版 `sim.py:1155` 的 `not self._is_goal`）。
	//: 不在表里就当没有终点格（见 `simCtx.IsGoalCell`）。
	//:
	//: ⚠ 只有真会用到它的机制在场时才需要送：通用关卡送空列表的代价是
	//: `IsGoalCell` 每次线性扫一个空切片，可忽略；**漏送**的代价是"终点格也被
	//: 冻"，那会让漏怪数变少——方向明确、但仍是判决级偏差。
	GoalCells [][2]int `json:"goal_cells,omitempty"`

	Operators []OperatorSpec `json:"operators"`
	Deploys   []DeploySpec   `json:"deploys"`
	Spawns    []SpawnSpec    `json:"spawns"`
	//: 手动开技能的请求（时刻 + 格子），见 `SkillUseSpec`
	SkillUses []SkillUseSpec `json:"skill_uses,omitempty"`

	//: 这一局用到了最小版本没覆盖的机制时，Python 侧在这里逐条写明。
	//: 非空即拒跑——见文件头。
	Unsupported []string `json:"unsupported,omitempty"`

	//: 这一局要挂上的**关卡特有机制**（博士 2026-09-18：机制单独成层、按需取用）。
	//: 由 Python 点名——它知道"这一关有哪几样机制"；Go 侧按名字从 `mech` 包里取。
	//:
	//: 取不到 → **拒跑**，不是忽略：少挂一个机制与"这关本来就没这机制"在判决上
	//: 分不开，而对拍台分不开的两种结果早晚会把偏差固化成基线。
	//: 本二进制里有哪些机制，看 `ping` 的 `mechanisms`。
	Mechanisms []string `json:"mechanisms,omitempty"`

	//: 各机制的**规格**，键 = 机制名（与 `Mechanisms` 里的名字一一对应）。
	//:
	//: 类型是 `json.RawMessage`：规格长什么样是**那个机制自己的事**，由它自己的
	//: 工厂去解（`mech.Factory`）。放在这里而不是写成一堆具名字段，是因为机制会
	//: 一个一个加，每加一个就往协议顶层塞一段字段，协议迟早变成一堆互不相干的
	//: 平铺字段，而且删掉一个机制还会留下没人读的键。
	//:
	//: 点名了却没有对应规格（或反过来）→ 拒跑，见 `mech.Load`。
	MechConfig map[string]json.RawMessage `json:"mech_config,omitempty"`
}

// RegenAuraSpec 是天赋「医者丰碑」的增益治疗光环（原版 `talents.RegenAura`）。
//
// 「进入自身攻击范围」**包括部署进射程**——游戏里干员落地那一刻就是在范围里，
// 天赋照样触发，所以原版在部署当帧就判一次，不等它"走进来"。
type RegenAuraSpec struct {
	//: 每秒回复量（黑板 `hp_recovery_per_sec`）。
	HPPerSec float64 `json:"hp_per_sec"`
	//: 增益持续秒数（黑板 `buff_duration`）。**从吃到那一刻起算**。
	Duration float64 `json:"duration"`
	//: 对某个势力翻倍时，该势力的代号（`rhodes` = 【罗德岛】）。空 = 不翻倍。
	Nation string `json:"nation,omitempty"`
	//: 翻倍倍率（黑板 `rhodes_bonus`），**不写死 2.0**。
	NationMult float64 `json:"nation_mult,omitempty"`
	//: 「进入」的严格读法：只算**光环落地之后**才进场的友方。
	//: 跟着原版的 `heal_mode` 一起切（`sim.py:2837-2838`）。
	//:
	//: ⚠ 这条歧义是**实质性**的，不是实现细节：严格读法下"本来就在范围里"的人
	//: 吃不到这份治疗。SR-EX-8 上它会决定最优解是四人还是三人。
	Strict bool `json:"strict,omitempty"`
}

// TeamAuraSpec 是一条**全场光环**（原版 `talents.TeamAura`，`talents.py:646`）。
//
// 与 `RegenAuraSpec` 的关键差别：那个是**射程内**才生效、要问主人的 `Range`；
// 这个是**全场**、不看位置，所以没有"进入"那一刻的歧义，判定只需要"目标是谁"。
//
// 生效与否则是主人**开不开技能**的函数（有的常驻、有的只在技能期间），
// 所以每帧都要重算一次——不能像 `regen_aura` 那样在吃到的那一刻一次定死。
type TeamAuraSpec struct {
	//: 光环主人的名字（只用于日志与对拍，判定按 `operator` 对象走）。
	Owner string `json:"owner,omitempty"`
	//: 攻击力 / 防御力比例。**同层相加**（进 `(1 + Σ%)` 那个括号），不连乘。
	AtkPct float64 `json:"atk_pct"`
	DefPct float64 `json:"def_pct"`
	//: 「技能期间**才**生效」。false = 常驻（青色怒火）。
	SkillOnly bool `json:"skill_only,omitempty"`
	//: 只发给主人**自己**（能天使「天使的祝福」的自身那半）。
	//: 判等用**同一对象**，**不按 char_id**——同一关里可以有同名干员。
	SelfOnly bool `json:"self_only,omitempty"`
	//: **筛选**：只发给这个势力的人（`rhodes` = 【罗德岛】）。空 = 不按势力筛。
	//: ⚠ 与 `NationDouble`（翻倍：该势力 ×2、别人 ×1）**是两种语义**，别合并。
	FactionOnly string `json:"faction_only,omitempty"`
	//: **筛选**：只发给这个主职业的人（`TANK` = 重装）。**不吃倍率**，
	//: 也不看主人开不开技能（星熊那条是常驻的）。
	Profession string `json:"profession,omitempty"`
	//: **筛选**：只发给「携带弹药类技能」的人（新约能天使「铳弹协约」）。
	//: 判据是那个人**当前装备的技能**是 `AMMO` 型，与技能开没开无关。
	AmmoSkillOnly bool `json:"ammo_skill_only,omitempty"`
	//: **翻倍**：对某个势力的人效果 ×`DoubleScale`（`laterano` = 【拉特兰】）。
	NationDouble string `json:"nation_double,omitempty"`
	//: 主人**开着技能**时的加倍倍率（描述写「加倍」即 2.0）。
	//: ⚠ 它是**默认值**（原版 `double_scale: float = 2.0`），不是"没有就不翻倍"——
	//: 所以规格里**每次都要显式送**，不能靠 omitempty 省掉。
	DoubleScale float64 `json:"double_scale"`
	//: 按 **char_id 名单**翻倍（万众巨潮的【乌萨斯学生自治团】）。
	//: 与 `NationDouble` 是两种数据形态：那个按势力字段判、成员随新干员增加，
	//: 这个是写死的名单。
	Faction []string `json:"faction,omitempty"`
	//: 名单内那批人的翻倍倍率（黑板 `scale_bonus`）。
	FactionScale float64 `json:"faction_scale,omitempty"`
}

// OperatorSpec 是一名**已经在场上**的干员的全部数值。
//
// 数值是"无技能状态下"的定值：技能激活在最小版本里不支持（`unsupported` 会挡住），
// 被动技能与常驻天赋/光环的影响**已经折进这些数字**（`atk` 就是
// `OperatorUnit.current_atk()` 在无技能帧的值），所以 Go 这边不需要任何再计算。
type OperatorSpec struct {
	CharID string `json:"char_id"`
	Name   string `json:"name"`
	Cell   [2]int `json:"cell"`

	MaxHP float64 `json:"max_hp"`
	//: 「圣山的祝福」（圣聆初雪的天赋）：**受到致命伤害时不撤退**——免死一次、
	//: 满血复活。判在干员掉血的唯一入口里（原版判在 `take()`，unit.py:643）。
	BlessingSave float64 `json:"blessing_save,omitempty"`
	//: 触发时**自身**冻结秒数（原版 `blessing_self_freeze`，黑板 `freeze`）。
	//
	//: ⚠ 同一天赋的另一半——触发时**冻结攻击范围内全体敌人** N 秒
	//: （黑板 `c2e_freeze`）——**未移植**：Go 侧还没有敌人冻结状态。所以这条
	//: 天赋在 Go 里只兑现了"免死+自冻结"，两边不必一致。
	BlessingSelfFreeze float64 `json:"blessing_self_freeze,omitempty"`
	//: 层数护盾（泥岩「沃土予身」/ 空弦「铁弦」）。没有就是 `nil`——
	//: 与"有护盾但层数是 0"是两回事，所以用指针而不是零值。
	Shield         *ShieldSpec `json:"shield,omitempty"`
	ATK            float64     `json:"atk"`
	DEF            float64     `json:"def"`
	RES            float64     `json:"res"`
	AttackInterval float64     `json:"interval"`
	DamageType     string      `json:"damage_type"`
	BlockCnt       int         `json:"block_cnt"`
	DeployCost     int         `json:"deploy_cost"`
	RedeployTime   float64     `json:"redeploy_time"`

	//: 天赋给的**常驻闪避比例**（原版 `op.talent_dodge_phys/arts`，
	//: 来源是 `battle/talents.py::find_damage_block`——库里目前只有星熊「战术装甲」）。
	//:
	//: 为什么单独一项：它**不随技能开关变**，而技能给的闪避随 `Active` 那套走
	//: （原版刻意分了两个字段，`sim.py:2682-2689` 写明了不能混）。两个都是
	//: "削掉多少比例"的期望值，不是概率掷骰。
	TalentDodgePhys float64 `json:"talent_dodge_phys,omitempty"`
	TalentDodgeArts float64 `json:"talent_dodge_arts,omitempty"`

	//: 攻击范围（**绝对格**，已按落点与朝向展开；技能改范围在最小版本里不支持）
	Range [][2]int `json:"range"`
	//: 干员**所属势力**（`operator.nation_id`，如 `rhodes`）。与 `team_id` 不是
	//: 一回事：那是**小队**。消费者有两个：「医者丰碑」的"对【罗德岛】
	//: 干员的效果翻倍"，以及全场光环里"只发给/翻倍某个势力"那两条
	//: ——**两者判的都是吃效果那个人的势力**，所以每位干员都要带。
	NationID string `json:"nation_id,omitempty"`
	//: 主职业代号（`operator.profession`，如 `TANK` = 重装）。**只有一个消费者**：
	//: 按职业发的全场光环（星熊「特种作战策略」，`talents.CLASS_AURA_TALENTS`）。
	//: 与 `nation_id`（势力）是两回事：那个是"哪个势力"，这个是"哪个职业"。
	Profession string `json:"profession,omitempty"`
	//: 这一位干员自己带出去的**全场光环**（天赋）。一个干员可以有多条
	//: （「万众巨潮」与「特种作战策略」是并列的两条天赋，不是同一件事）。
	//:
	//: ⚠ 与 `regen_aura` 不同：那个是**射程内**才生效、要问 `Range`；
	//: 这个是**全场**、不看位置，所以判定只需要"目标是谁"。
	TeamAuras []TeamAuraSpec `json:"team_auras,omitempty"`
	//: 天赋「医者丰碑」（凯尔希 / 凯尔希·思衡托）的**增益治疗光环**。
	//: 原文：「其他友方干员**进入自身攻击范围时**立刻获得 1 层护盾并额外获得一次
	//: **每秒回复 N 点生命值**的增益治疗，持续 M 秒（**不可叠加**），增益治疗对
	//: 【罗德岛】干员的效果**翻倍**。」
	//:
	//: ⚠ 原文里的「1 层护盾」**没有黑板键**，原版 `RegenAura` 也只兑现回血那一半
	//: （`talents.py:620`）——这里同样只做回血，两边一致。
	//:
	//: 帧位在**技能之后、我方出手之前**（原版 5.5，`sim.py:2834-2840`）：
	//: 本帧刚上场的干员当帧就能吃到，本帧刚吃到的治疗也在本帧出手前落账。
	RegenAura *RegenAuraSpec `json:"regen_aura,omitempty"`
	//: 医疗：这个人的**平A 是治疗**（原版 `OperatorUnit.heals`）。
	//: 但技能可以把这一击改成伤害（凯尔希·思衡托技2「攻击变为射出医疗单元」）——
	//: 判据是技能自己有没有写攻击倍率，见 `operatorsAttack`。
	Heals bool `json:"heals,omitempty"`
	//: 普攻连击（焰狐龙梓兰的**隐藏天赋**）：一次普攻打 `ComboHits` 击，每击倍率
	//: `ComboHitScale`，**计算防御/法抗之后**再整笔乘 `ComboDamageScale`。
	//:
	//: ⚠ 两个"不是 1"的判据必须按原版抄：`ComboHits` 的"没有这条"是 **1**
	//: （原版判 `> 1`），`ComboHitScale` 是 **1.0**。按 0 判会把每一位没有连击
	//: 的干员都当成三连击。
	//:
	//: 只在**这一次出手是普攻**时生效——判据看技能有没有改写这一击的攻击倍率
	//: （`abs(atkScale − 1.0) < 1e-9`），不看技能开没开。
	ComboHits        int     `json:"combo_hits,omitempty"`
	ComboHitScale    float64 `json:"combo_hit_scale,omitempty"`
	ComboDamageScale float64 `json:"combo_damage_scale,omitempty"`
	//: 天赋「强击瓶专家」（焰狐龙梓兰 天赋1）：部署后**首次**开技起，接下来
	//: `PowerAttackCount` **轮**攻击的攻击力乘 `PowerAttackScale`。
	//:
	//: ⚠ `Count` 数的是**攻击动作（一轮）**，不是箭矢：prts 备注写明"于弹道脱手
	//: 前对当次连击的所有弹道生效"，且"每轮技能三/四/五连击、每次二技能的降落
	//: 攻击、每次三技能的龙之箭均消耗 1 次"。所以一轮只扣一层。
	PowerAttackCount int     `json:"power_attack_count,omitempty"`
	PowerAttackScale float64 `json:"power_attack_scale,omitempty"`
	//: 职业特性溅射（撼地者那四位共用的一条特性；判据是特性黑板上同时有
	//: `attack@ability_range_radius` 与 `attack@atk_scale_2`，已由 Python 解好）。
	//:
	//: `SplashScale` 是特性给的倍率、`SplashDamageScale` 是天赋「汹涌怒火」
	//: 叠上来的（溅射真正用的是**两者相乘**），`HighlandSplashScale` 是高台
	//: 那一半的倍率。三者都为 0 = 没有这条特性。
	SplashRadius        float64 `json:"splash_radius,omitempty"`
	SplashScale         float64 `json:"splash_scale,omitempty"`
	SplashDamageScale   float64 `json:"splash_damage_scale,omitempty"`
	HighlandSplashScale float64 `json:"highland_splash_scale,omitempty"`
	//: 高台那一半溅到之后挂的【停顿】秒数（原版 `highland_splash_sluggish`，
	//: 取自天赋黑板的 `attack@sluggish`）。**它不只是个计时器**：原版
	//: `EnemyUnit.advance` 在停顿期间**整帧不移动**，所以这个值会实打实地
	//: 拖慢敌人——漏了它，敌人会一路走得比原版快。
	HighlandSplashSluggish float64 `json:"highland_splash_sluggish,omitempty"`

	//: 技能（没有技能槽就是 nil）。数值由 Python 算完送来，Go 只跑状态机：
	//: 攒技力、什么时候能开、开多久、结束。
	Skill *SkillSpec `json:"skill,omitempty"`
	//: **技能开启期间**的那一套数值。`Skill != nil` 时必须有。
	//: 与 `OperatorSpec` 顶层的（＝未开启的那一套）成对使用：Go 只负责在
	//: 技能开/关的那一刻整套换过去，**不算任何一个数**。
	Active *Profile `json:"active,omitempty"`
}

// Profile 是"这一刻的数值"。
//
// 为什么是**整套快照**而不是"改了哪几项"：原版 `OperatorUnit` 的那些
// `current_*()` 读的是 `op.effects`，而 `effects` 一开一关会同时改攻击力、
// 攻速、防御、法抗、伤害类型、目标数……逐项传"改了什么"就等于在 Go 侧
// 重写一遍效果模型，而效果模型正是最容易漂的那一层。Python 那边有两套
// 数值（无技能帧 / 技能帧）——它已经把这两套算得清清楚楚，直接送过来。
type Profile struct {
	ATK        float64 `json:"atk"`
	DEF        float64 `json:"def"`
	RES        float64 `json:"res"`
	Interval   float64 `json:"interval"`
	DamageType string  `json:"damage_type"`

	//: 一次出手打几个目标（`current_max_target()`）
	MaxTarget int `json:"max_target"`
	//: 这一击的攻击力倍率（`effects.atk_scale`）；无技能时是 1
	AtkScale float64 `json:"atk_scale"`
	//: 一次出手打几下（`effects.hit_count`）；无技能时是 1
	HitCount int `json:"hit_count"`
	//: 技能开启期间的**生命上限**（原版 `apply_max_hp_bonus`，unit.py:947）。
	//:
	//: 用指针的理由与 `FinalHitScale` 同族，但方向相反：这里"没有这个键"
	//: 与"上限正好是 0"都能区分，而 Go 侧只在**有值**时才照着改上限、
	//: 并在 `deactivate` 里还原。静态的 `max_hp`（干员规格里那个）始终是
	//: 基准值，两个都不能少。
	MaxHP *float64 `json:"max_hp,omitempty"`
	//: 最后一击改用的倍率（`effects.final_hit_scale`）；**没有就整个键不出现**。
	//:
	//: 这里必须是**指针**：写成 `float64` 时，Python 送来的 `null` 会被
	//: `encoding/json` 变成 0，而 0 在下游看起来就是"有一份末击倍率、值是 0"
	//: ——单发攻击的最后一击（也就是唯一那一击）会被它改成 0 倍率、打出 0 伤害，
	//: 而且不报错、不崩，只表现为"这名干员打不死人"。实测就是这么咬了一口。
	//: 判"有没有"只能看 `nil`（NaN 不行：JSON 里写不出 NaN）。
	FinalHitScale *float64 `json:"final_hit_scale"`

	//: **技能给的**闪避（原版 `sk.effects.dodge_phys/arts`，由技能描述驱动）。
	//: 只在技能开启期间有效——所以它住在 `Profile`（"这一刻的数值"）里，
	//: 而天赋那份常驻抵挡住在 `OperatorSpec` 上（见那里的注释）。
	DodgePhys float64 `json:"dodge_phys,omitempty"`
	DodgeArts float64 `json:"dodge_arts,omitempty"`
}

// SkillSpec 是一个技能槽的**状态机参数**。
//
// 只放"时间怎么走"需要的东西；写在谁身上的百分比、倍率、类型全在 `Profile` 里。
type SkillSpec struct {
	//: INCREASE_WITH_TIME（自动回复）/ INCREASE_WHEN_ATTACK（攻击回复）/
	//: INCREASE_WHEN_TAKEN_DAMAGE（受击回复）/ PASSIVE（被动，无技力）
	SPType string `json:"sp_type"`
	//: 被动技能：部署即生效、不耗技力、永不关闭
	Passive bool `json:"passive"`
	//: 技力满了会不会自己开（`skill_type == "AUTO"`）
	AutoTrigger bool `json:"auto_trigger"`

	SPCost    float64 `json:"sp_cost"`
	InitSP    float64 `json:"init_sp"`
	Increment float64 `json:"increment"`
	//: 可充能次数（`maxChargeTime`）：没开技能时技力上限是 `sp_cost × max(1, N)`
	MaxCharge int `json:"max_charge"`

	//: 持续时间（秒）。`Infinite` 为真时忽略它
	Duration float64 `json:"duration"`
	//: 无限持续：开启后**不会自然结束**，只有弹药打光才结束。
	//: 三种来路都落在这里：描述明写「持续时间无限」、「持续时间类型 = INFINITE」、
	//: 以及**弹药类**（`effective_duration` 给 None）——原版`_activate` 判的是
	//: "`dur is None`"，不是某一个字段。
	Infinite bool `json:"infinite"`
	//: 弹药类的总发数（0 = 不是弹药类）；打光就结束
	Ammo int `json:"ammo"`
	//: 持续时间类型（`NONE` / `AMMO` / …）。**唯一的消费者**是全场光环里那条
	//: 「**携带**弹药类技能的干员 +9%」（`TeamAuraSpec.AmmoSkillOnly`）——
	//: 它判的是"装备的是不是弹药技能"，**与技能开没开无关**，所以不能拿
	//: `Ammo > 0` 顶替：那个是"打光就结束"的运行时表现。
	DurationType string `json:"duration_type,omitempty"`
	//: 整场只能开一次（开过就不再开，哪怕技力又满了）
	OncePerBattle bool `json:"once_per_battle"`

	//: 开启那一刻回的费用（德克萨斯、桃金娘这一类）
	CostGain float64 `json:"cost_gain"`
}

// SkillUseSpec 是一次**手动开技能**的请求。
//
// 与 `DeploySpec` 同样按"那一刻"判：时刻到了，找**站在这一格上的、活着的**
// 干员记一笔请求（`sim.use_skill` → `_alive_op_at(position)`，原版 2006-2009）。
// 找不到人（已经阵亡/撤退/格子上的不是它）就什么也不发生——请求不是命令。
//
// 为什么不按"干员对象下标"传：原版就是按**格子**找人的，改成下标等于换一套
// 判据；同一格上换了人（撤了重放）时两者的结果会不同。
type SkillUseSpec struct {
	Time float64 `json:"time"`
	Cell [2]int  `json:"cell"`
}

// DeploySpec 是一次排定的部署。
//
// `Index` 指向 `operators[]` 里的**那一个单位对象**——同一个干员再部署时是**另一个
// 对象**（原版里每条 `Deployment` 自带一个 `OperatorUnit`；共用对象会让"撤退后
// 重放"的血量与冷却都算错）。**能不能落下由 Go 在那一刻判**（费用与再部署冷却），
// 判不过就照着原版的做法记一笔并不放——两边都得判，否则"排了但没落地"这一路会
// 悄悄分成两种结果。
// ShieldSpec 是干员的**层数护盾**（原版 `OperatorUnit.shield_*` 那一族，
// `unit.py:412-421`；授予与节拍见 `sim.py:3157-3205`，伤判见 `unit.py:613-620`）。
//
// ⚠ **送的是比例不是回血量**：原版 `op.shield_break_heal = ratio × op.max_hp`
// 是在**部署那一刻**用当时的生命上限算死的。送比例、由 Go 在同一个时刻乘它
// 自己的 `maxHP()`，两边才会用同一个上限——送绝对值就等于把那个时刻的 `max_hp`
// 固化进规格，日后任何改上限的机制（如「天使的祝福」）都会让两边对不上。
type ShieldSpec struct {
	//: 上限（原版 `max(max_times, times)`：泥岩有黑板 `max_times`，
	//: 空弦只有正文里的"一层"，取两者的**大**者，见 `sim.py:3172`）。
	MaxLayers int `json:"max_layers"`
	//: **部署时**给几层（原版 `shield_layers_on_deploy`）。
	Layers int `json:"layers"`
	//: 「每 N 秒加一层」的间隔；0 = 不再补层。
	Interval float64 `json:"interval"`
	//: 破裂回血比例（原版 `shield_break_heal_ratio`，泥岩「沃土予身」是 0.2）。
	BreakHealRatio float64 `json:"break_heal_ratio"`
	//: 破裂给技力（空弦「铁弦」的 `sp`=7）。
	BreakSP float64 `json:"break_sp"`
}

type DeploySpec struct {
	Time   float64 `json:"time"`
	Index  int     `json:"index"`
	CharID string  `json:"char_id"`
	Cost   int     `json:"cost"`
	//: 手动技能在技力满了之后要不要**自动**开（`Deployment.auto_skill`，
	//: 原版默认 True）。它属于**这一次部署**而不是干员：同一个人两次部署
	//: 可以带不同的值。
	AutoSkill bool `json:"auto_skill"`
}

// LegSpec 是路线的一段：走段（`walk`）、等待段（`wait`）或离场段（`vanish`）。
//
// 路线的分段计划由 Python 侧算好（`eta.route_plans` 那套），Go 只按段推进。
// 这样做的代价是规格里要带一份折线，换来的是**寻路不会成为第二个实现**。
type LegSpec struct {
	Kind    string       `json:"kind"`
	Points  [][2]float64 `json:"points,omitempty"`
	Length  float64      `json:"length,omitempty"`
	Seconds float64      `json:"seconds,omitempty"`
}

// RebornSummonSpec 是重生期召唤的一"拍"（见 `SpawnSpec.RebornSummons`）。
//
// `Template` 是**完整的敌人规格**（不是 id）：Go 侧没有敌人图鉴，只有规格，
// 所以 Python 把要召唤的那只的整份规格塞进来——和天桩链的 summons 同一个套路。
type RebornSummonSpec struct {
	Interval float64    `json:"interval"`
	Count    int        `json:"count"`
	Template *SpawnSpec `json:"template,omitempty"`
	//: 召唤物从**哪一格**出发时走哪条路：键是 `"x,y"`（原版 `e.cell()` 的口径，
	//: 四舍五入到整数格），值是那串路点。地图上每一格都算了一遍——包括召唤者
	//: 被推挤/被阻挡而停在半路的情况，免得"只在常规路线上才找得到"。
	Paths map[string][][2]float64 `json:"paths,omitempty"`
}

// SpawnSpec 是一个**已经建好**的敌人实例（数值、路线、机制标记都在这里）。
//
// 注意用的是 `sim._spawn()` 建出来的那份对象里的字段，不是重新按 id 查一遍：
// 「按 id 再查一次」就等于在 Go 侧重写一遍 `_build_enemy`，而它里面有关卡乘区、
// 难度档位、召唤体默认档这些东西——多一处就会漂。
type SpawnSpec struct {
	Time    float64 `json:"time"`
	Name    string  `json:"name"`
	EnemyID string  `json:"enemy_id"`
	Level   int     `json:"level"`

	HP         float64 `json:"hp"`
	ATK        float64 `json:"atk"`
	DEF        float64 `json:"def"`
	RES        float64 `json:"res"`
	MoveSpeed  float64 `json:"move_speed"`
	Interval   float64 `json:"interval"`
	DamageType string  `json:"damage_type"`

	AttackRange float64 `json:"attack_range"`
	ApplyWay    string  `json:"apply_way"`
	AttackTimes int     `json:"attack_times"`

	IsFlying    bool `json:"is_flying"`
	Unblockable bool `json:"unblockable"`
	TauntLevel  int  `json:"taunt_level"`
	LifeCost    int  `json:"life_cost"`
	KillCost    int  `json:"kill_cost"`
	CannotClear bool `json:"cannot_clear"`

	//: 被击倒时给"圆心周围田地"加多少病害（原版 `passive_pollut`），
	//: 以及半径（原版 `passive_radius`，0 表示按 1.0 算）。
	//:
	//: 这两项是**每一只敌人自己的**黑板数值，所以住在敌人的规格里；但只有机制层
	//: 会读它们（怀黍离的田地被击倒污染）。圆心**不是**这一只脚下那一格——
	//: 被阻挡时取挡它的那个干员脚下那一格（原版 `_pollute_around` 1280-1298）。
	PassivePollut float64 `json:"passive_pollut,omitempty"`
	PassiveRadius float64 `json:"passive_radius,omitempty"`

	//: 重生（原版 `Reborn.*`，怀黍离的 `Reborning.*` 共用这一套状态；见
	//: `sim.go` 帧序 3.4）：`RebornLeft` = 还能重生几次，`RebornDelay` =
	//: 倒下到归来之间的秒数，`RebornHPRatio` = 归来时的生命比例。
	//:
	//: ⚠ BOSS 的"多一条命"在数据里与普通敌人没有任何区别——只有把这条算上，
	//: "打完了没有"才是可信的。它曾经整条没进规格：Go 那边**静默**少算一条命，
	//: 只有恰好因此改变判决的关卡才会露馅，而那正是对拍台最难抓到的一类。
	RebornLeft    int     `json:"reborn_left,omitempty"`
	RebornDelay   float64 `json:"reborn_delay,omitempty"`
	RebornHPRatio float64 `json:"reborn_hp_ratio,omitempty"`

	//: 重生期**充能**（怀黍离「瘴 / 鄙瘴」）：窗口内每 `RebornInterval` 秒，
	//: 若自身所在**整数格**的病害值 > 0，则扣掉 `RebornPollut` 点并获得 1 层；
	//: 归来时防御力 +(RebornDefAdd × 层数)%，普攻**附加**
	//: (RebornDamageMagic × 层数)% 攻击力的无途径法术伤害。
	//:
	//: 充能只在重生窗口里增长（原文「重生期间每0.5s」），重生完成即定住。
	RebornInterval    float64 `json:"reborn_interval,omitempty"`
	RebornPollut      float64 `json:"reborn_pollut,omitempty"`
	RebornDefAdd      float64 `json:"reborn_def_add,omitempty"`
	RebornDamageMagic float64 `json:"reborn_damage_magic,omitempty"`

	//: 蜕皮（原版 `Passive_Hit.*`，「祟」的混沌形态）：**每挨打 `PhitCnt` 次**
	//: 叠 1 层（上限 `PhitMaxStack`），每层改一次属性；同时每次挨打都在
	//: 「挡它的干员 / 它自己」脚下那一格半径 1.0 内给田地加病害。
	//:
	//: ⚠ 加病害的两个数不一样：被阻挡时用 `PhitBlockPollut`，没被挡用
	//: `PhitPollut`（原版 1263-1265 的整个判据就是这两支）。层满之后整段
	//: 都不再发生——连病害也不加了（原版把加病害写在同一个 `if` 里）。
	PhitCnt         int     `json:"phit_cnt,omitempty"`
	PhitMaxStack    int     `json:"phit_max_stack,omitempty"`
	PhitAtk         float64 `json:"phit_atk,omitempty"`
	PhitDef         float64 `json:"phit_def,omitempty"`
	PhitRes         float64 `json:"phit_res,omitempty"`
	PhitMove        float64 `json:"phit_move,omitempty"`
	PhitWeightCnt   int     `json:"phit_weight_cnt,omitempty"`
	PhitPollut      float64 `json:"phit_pollut,omitempty"`
	PhitBlockPollut float64 `json:"phit_block_pollut,omitempty"`

	//: 重生期**召唤**（「祟」）：窗口内每 `Interval` 秒在自己脚下召唤 `Count` 个
	//: `Template`（模板就是一份普通的敌人规格，见 `Summon`）。
	//:
	//: ⚠ 它不是"一共召唤 Count 个"：`Count` 是**每一拍**几个，拍数由窗口长度
	//: 决定（窗口 = `RebornDelay` 秒）。窗口一结束就停（原版 4214 行把它清空）。
	//:
	//: 召唤物要**走到最近的保护目标**，所以得有一条真路线；而路线只取决于
	//: "倒下那一刻站在哪一格"，那一格在出规格时还不知道。做法：Python 把地图上
	//: 每一格的路线都算好随规格发来（`Paths`），Go 按召唤那一刻的格子查表；
	//: 查不到就**当场拒跑**，绝不"随便给条路"——那会让判决悄悄偏。
	RebornSummons []RebornSummonSpec `json:"reborn_summons,omitempty"`

	//: 明识形态（原版 `PassiveM2.*`，「祟」重生归来后的第二形态）：归来那一刻
	//: 改一次属性，并给一段无敌。
	//:
	//: `Pm2Clean*` 是"清水"（站在病害值 0 的田地、或在清澈泵站范围内）时**叠在
	//: 上面**的可开关项：防御按 `基准 × (1 + pm2_def + clean_def)` **重算**，
	//: 移速加成被清零。重算而不是加减——清水进出能来回切，累乘会指数漂。
	Pm2Atk        float64 `json:"pm2_atk,omitempty"`
	Pm2Def        float64 `json:"pm2_def,omitempty"`
	Pm2Res        float64 `json:"pm2_res,omitempty"`
	Pm2Move       float64 `json:"pm2_move,omitempty"`
	Pm2CleanDef   float64 `json:"pm2_clean_def,omitempty"`
	Pm2CleanMove  float64 `json:"pm2_clean_move,omitempty"`
	Pm2MarkPollut float64 `json:"pm2_mark_pollut,omitempty"`
	Pm2Invincible float64 `json:"pm2_invincible,omitempty"`

	//: 敌方**技能出手**（怀黍离「玷 / 勿玷」技能「污」，原版
	//: `sim.py:3468` 的 `_skill_attack_tick`）。全 0 = 这一只没有这个技能。
	//:
	//: `SkillAtkCross` 是"周围 4 格"的开关（1 = 十字五格），**不是半径**：
	//: 原文写的是"目标及其周围 4 格"，斜角不在内，与半径 1.0 的圆不是一回事。
	SkillAtkScalePhys  float64 `json:"skill_atk_scale_phys,omitempty"`
	SkillAtkScaleMagic float64 `json:"skill_atk_scale_magic,omitempty"`
	SkillAtkInit       float64 `json:"skill_atk_init,omitempty"`
	SkillAtkInterval   float64 `json:"skill_atk_interval,omitempty"`
	SkillAtkCross      int     `json:"skill_atk_cross,omitempty"`
	SkillAtkPollut     float64 `json:"skill_atk_pollut,omitempty"`
	SkillAtkGroundOnly bool    `json:"skill_atk_ground_only,omitempty"`
	//: 天赋「不进行远程普通攻击」：**关掉普攻那整条路**（原版
	//: `sim.py::_enemies_attack` 的 `if e.skill_atk_no_normal: continue`）。
	//: 它不是数值而是一道闸门——当成"没用的标记"删掉，这只敌人就会技能与
	//: 普攻双份出手（HS-EX-8 第 2 手就是这么多出两笔 192 的）。
	SkillAtkNoNormal bool `json:"skill_atk_no_normal,omitempty"`

	//: ---- 伤害相性 P3R（原版 `TotalAttack.*` / `Mode_A|B`，`battle/p3r.py`）
	//:
	//: 取值 `0 弱点 / 1 正常 / 2 免疫 / 3 反射`，**逐伤害类型**给（`physical`/
	//: `magical`/`element`）。这一族此前**两端都缺**：Go 侧 0 落点，规格侧也
	//: 一个字段都不送（`enemy_view` 有 `affinity` 槽，但 `_view` 从没传过它）。
	//: 本段只开**通道**——字段到了 Go，**怎么作用**还没实现。
	//:
	//: ⚠ **故意不用 `omitempty`，而且用可判 `nil` 的类型**：三个空值含义不同，
	//: 压成一个就是本族静默的根因。
	//:   * **键缺席** → 解出来是 `nil`：这份规格是开通道之前写的，压根没有这一路；
	//:   * **`{}` / 显式 0** → **非 nil** 的空 map ／ 非 nil 指针：通道在，
	//:     这只敌人（或这一关）没有相性；
	//:   * **有内容** → 真的带相性。
	//: 用 `omitempty` 会让"没送"和"送了空"在**序列化回来**时长得一样。
	P3R map[string]int `json:"p3r"`
	//: 形态相性（BOSS 专用）`{"Mode_A": {...}, "Mode_B": {...}}`。
	//:
	//: ★ BOSS 的**真档位**在这里，它的 `P3R` 反而是 `1/1/1`（无弱点）。
	//: ⚠ "选哪一档"是**运行期**的事：原版按当时的 `sim.boss_mode` 选
	//: （`sim.py:1554`），并在档位切换时**改写** `e.affinity`（`sim.py:3640`）。
	//: 规格是出怪之前算好的，所以**整份送过来**、由 Go 在同一时刻自己选。
	P3RModes map[string]map[string]int `json:"p3r_modes"`
	//: 击破值阈值（`TotalAttack.weak_max`）：累积到这个**实际掉血量**就倒地。
	P3RWeakMax *float64 `json:"p3r_weak_max"`
	//: 倒地持续秒数（`TotalAttack.fall_duration`）。
	P3RFallDuration *float64 `json:"p3r_fall_duration"`
	//: 原版建 `BreakState` 的判据（`stats.has_p3r`）。
	P3RHas *bool `json:"p3r_has"`
	//: 原版的**门**：`sim.py:1552` 的 `if self.total_attack is not None` ——
	//: **装置不在时相性恒不生效**（`aff` 恒 `{}`），与"这只敌人有没有相性"
	//: 是两件事、不同源，所以单独一个键。
	P3RArmed *bool `json:"p3r_armed"`

	Legs []LegSpec `json:"legs"`

	//: **天桩-乙**（原版 `sim._pile_mark_key(e)` 非空）。
	//:
	//: ⚠ 关键事实：乙**也会从出怪表刷出来**（`act31side_09` 的 38 条出怪行里
	//: 有 24 条是 `enemy_1399_dhtb`），而原版对它们照样跑 `_pile_diver_tick`
	//: ——`_pile_tick` 的第 ② 段是**遍历全体敌人**按类型分派
	//: （`sim.py:4651-4659`），`_pile_mark_key` 不区分"装置召唤的"还是
	//: "出怪表刷的"。实测：`act31side_09` 里 `_pile_diver_tick` 被调了
	//: **15802** 次，全部落在 `enemy_1399_dhtb` 身上。
	//:
	//: 这一段的行为是**每帧重设路线**——丢掉出怪表给的腿，直线扑向最近的
	//: 存活干员（`sim.py:4781-4785`）。没移植时的症状极具迷惑性：
	//: 乙会老老实实沿出怪表的腿走到图外**漏掉**，判决表现为"我方一次都没出手"
	//: ——看着像索敌坏了，其实是敌人压根没走到。
	//:
	//: 只给**出怪表**这条路上的敌人打标。装置召唤的甲/乙/天标由机制层的
	//: `pileUnit` 管（`huai_shu_li.go`），两边都打会**同一只被推两遍**。
	Diver bool `json:"diver,omitempty"`

	//: ---- 天桩链（怀黍离装置「天桩」的四跳，原版 `_pile_tick` 3884-4130）
	//:
	//: 这一组里没有一条是新口径：四跳全部照原版的代码路径来，数值一律从规格
	//: 送过来（`ak_tactic/simgo/mech.py::_pile_device_spec` 从原版常量读），
	//: 免得 Go 里再写死一遍"原文里的数字"。
	//:
	//: * `Static` —— 自缚：站在原地不动。原版靠"单点路线 + `reached_end` 要求
	//:   路线长度 > 0"实现；这里对应一条 `kind: "static"` 的腿（既不推进、
	//:   也不会被判成走到路线终点而漏怪）。
	//: * `Invincible` —— 甲**监测状态**下的无敌（挨打掉 0 血，但照旧会被索敌，
	//:   这正是它在场上白吃输出的原因）。激活时机制会把它关掉。
	//: * `Awake*` —— 甲激活后的自伤与分批召唤（`CheckAwake` 与 `summon` 两组黑板）。
	//: * `SelfBind` / `HitRadius` —— 乙的登场自缚秒数与"贴到目标"的判据。
	//: * `AttachDamage` / `AttachRadius` —— 天标的每秒伤害与附着半径。
	//: * `Summon` / `Mark` —— 下一跳的**模板**（甲→乙、乙→天标）。用模板而不是
	//:   让机制自己拼规格：谁造谁写在装置配置里，机制只管"什么时候造"。
	Static     bool `json:"static,omitempty"`
	Invincible bool `json:"invincible,omitempty"`

	AwakeValue       float64 `json:"awake_value,omitempty"`
	AwakeHPRatio     float64 `json:"awake_hp_ratio,omitempty"`
	AwakeSummonRatio float64 `json:"awake_summon_ratio,omitempty"`
	AwakeSummonCnt   int     `json:"awake_summon_cnt,omitempty"`
	AwakeEnemyKey    string  `json:"awake_enemy_key,omitempty"`

	SummonDelay float64 `json:"summon_delay,omitempty"`
	PollutFull  float64 `json:"pollut_full,omitempty"`

	SelfBind     float64 `json:"self_bind,omitempty"`
	HitRadius    float64 `json:"hit_radius,omitempty"`
	AttachDamage float64 `json:"attach_damage,omitempty"`
	AttachRadius float64 `json:"attach_radius,omitempty"`

	Summon *SpawnSpec `json:"summon,omitempty"`
	Mark   *SpawnSpec `json:"mark,omitempty"`
}

// Verdict 是一场战斗的结果。字段名与 `BattleResult` 对齐，便于逐项对拍。
type Verdict struct {
	Won            bool    `json:"won"`
	Elapsed        float64 `json:"elapsed"`
	Life           int     `json:"life"`
	Kills          int     `json:"kills"`
	Leaks          int     `json:"leaks"`
	Deployed       int     `json:"deployed"`
	OperatorDeaths int     `json:"operator_deaths"`
	DamageDealt    float64 `json:"damage_dealt"`
	SpawnsPlaced   int     `json:"spawns_placed"`
	SpawnsTotal    int     `json:"spawns_total"`
	TimedOut       bool    `json:"timed_out"`

	//: **跑满时间上限时场上还剩谁**，`(名字, 清不掉)` —— 与
	//: `BattleResult.leftover_units` 同形。
	//:
	//: 为什么必须有：结束判据是「出怪表走完 **且** 场上没有活跃敌人」。
	//: 一旦某只敌人**既打不死、又不会离场**，这一局就永远收不了场——
	//: 症状是**杀、漏、伤害全对，只有用时等于时间上限**。
	//: 没有这一项，那种局面在 Go 的判决里**一个字的线索都没有**，
	//: 只能看到"用时 +80 秒"然后去猜。
	Remnants [][2]any `json:"remnants,omitempty"`

	//: 漏怪的逐笔明细 `(时刻, 名字, 扣命)`——与 `BattleResult.leak_events` 同形
	LeakEvents [][3]any `json:"leak_events"`
	//: 拒收明细 `(时刻, 名字, 原因)`，与 `BattleResult.deploy_rejected` 同形
	DeployRejected [][3]any `json:"deploy_rejected"`
	//: 费用不足明细 `(时刻, 名字, 需要, 当时)`，与 `cost_denied` 同形
	CostDenied [][4]any `json:"cost_denied"`

	//: 时间线（时刻, 事件, 名字）——对拍"哪一帧开始不一样"就靠它。
	//: 只记四类：部署 / 出现 / 击杀 / 漏怪。
	Events []Event `json:"events"`

	//: 各机制的**状态快照**（键 = 机制名，见 `mech.Snapshotter`）。
	//:
	//: **判决本身不依赖它**，它是给对拍台用的：判决是粗指标，机制状态累积得不一样
	//: 却恰好没影响胜负时，只有逐项比这块才看得出来。
	MechState map[string]any `json:"mech_state,omitempty"`

	//: 这一场跑了多少毫秒（性能对照用）
	SimMS float64 `json:"sim_ms"`
}

// Event 是时间线上的一笔。
type Event struct {
	T    float64 `json:"t"`
	Kind string  `json:"kind"`
	Who  string  `json:"who"`
}
