package main

// operators.go：规格里 `operators` 那一串——**按部署顺序、每个部署人次一份干员规格**
// （丙阶段四·第二十四批）。
//
// ## 权威
//
// 一处拼起来的：
//
//	spec.py:1230-1233   operators.append(_operator_spec(inp, d))   ← sorted(sch.deployments, key=time)
//	spec.py:681-842     _operator_spec                              ← 顶层 13 键 ＋ 22 个条件键
//
// 之所以与 `deploys` 共用 `BuildDeployRows`：原版这两个键是**同一个循环里的两次
// append**，次序只能有一份口径（见 `specdeploys.go::DeployRow`）。
//
// ## 这一段落地的是哪 33 个键（判据眼里的「段 A」）
//
//	无条件 13：char_id / name / cell / max_hp / atk / def / res / interval /
//	           damage_type / block_cnt / deploy_cost / redeploy_time / range
//	条件 12：  nation_id / profession                                    （取值非空才送）
//	           splash_radius / splash_scale / splash_damage_scale /
//	           highland_splash_scale / highland_splash_sluggish          （radius > 0 才送）
//	           combo_hits / combo_hit_scale / combo_damage_scale         （hits > 1 才送）
//	           power_attack_count / power_attack_scale                   （count > 0 才送）
//	天赋派生 8：heals / blessing_save / blessing_self_freeze / regen_aura /
//	           team_auras / talent_dodge_phys / talent_dodge_arts / shield
//
// ★ **是 33 不是 34**：`_operator_spec` 一共产出 **35** 个键（13 ＋ 22），
// 段 A 33 ＋ 段 B 2 ＝ 35。这一行是现数的，不是抄来的。
//
// ★ 另有 **1 个「Go 独有键」**（判据那一侧的 `GO_ONLY`）：`hp_drain_per_sec`
// ——职业特性「自身生命会不断流失」（怪杰）的速率。Python 的 `_operator_spec`
// **不送**它（它不是「Python 有、Go 没有」的 `unported`，方向正相反），
// 而 `wire.go::OperatorSpec` 里要有它、`sim.go::traitDrainTick` 要读它。
// ⇒ 判据的身份等式是 **段 A 33 ＋ 段 B 2 ＋ GO_ONLY 1 ＝ wire 的 36 个键**。
//
// ★ 标着「段 B」的那个数字是**判据那一侧的**分段（`check_operators_go.py` 的
// `PORTED` / `UNPORTED`），不是本文件的分段——本文件只负责「产出」。
//
// ## 真正要搬的不是 `inp`，是**活对象**
//
// `_operator_spec` 只读三个 `inp.<attr>`（`range_provider` / `heals` / `effect_source`），
// 而它读 `op.<29 个属性> ＋ d.<3 个>`。那 29 ＋ 3 个名字在这里以常量形式
// **自报**（`OperatorViewFields` / `OperatorDeployFields`），判据拿 `ast` 从
// `spec.py` 里抽一遍与它**双向比对**——「我以为的清单」不能当清单用。
//
// ## 两条**现算**的结构性守卫（判据里重量，非 0 即红）
//
//  1. `op.current_range_id()`：技能改写范围那条。取规格发生在跑之前，
//     那时 `skill_active` 恒为 False ⇒ 恒 `None` ⇒ 走干员自己的 rangeId。
//     Go 这一侧**没有**「技能改写范围」这条路；哪天它非空了，这一段就不成立。
//  2. `op.redeploy_time`：`kw` 里**没有**这个键（`verify.py:314-355` 逐行可查），
//     所以它恒等于 `OperatorView` 的默认值 **70.0**。Go 送的就是这个常量——
//     不是 `respawnTime`（面板里那个数**没有**被 `_operator_spec` 读到）。
//
// ## 具名缺口（不许静默）
//
//  * `normalize_direction` 的**别名表**（`right` / `R` / `右` …）未读——与
//    `range.go` 同一口径：四个正名以外的朝向**大声失败**。原版那条路会
//    `except Exception: pass` 悄悄退化成「自身格 ＋ 前方三格」，Go 不照抄那个静默。
//  * 段 B 剩的 2 个键（`skill` / `active`）**不产出**，具名进 `unported`
//    （见 `OperatorUnported`）。

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
)

const (
	//: `spec.py` 的 `MIN_INTERVAL` / `ASPD_MIN`（与 `operator_view.py:42-43` 同源）。
	opsMinInterval = 0.05
	opsAspdMin     = 20.0
	//: `OperatorView.redeploy_time` 的默认值——`kw` 里没有这个键，所以恒是它。
	opsRedeployDefault = 70.0
)

// OperatorUnported 是 `_operator_spec` 会产出、而 Go 这一轮**不产出**的 2 个键。
//
// ★ **逐条写清「为什么是它」**——不写清楚，`unported` 会变成一个没人敢动的黑洞：
//
//	skill / active  要 `skills.skill_spec(inp, d)`（`skills.py:277-317`）：整段
//	                技能效果装配，`op.skill.effects` 那一层 Go 还没有。★ 而且
//	                **24 份夹具的 64 人次里 `deploys[*].skill` 全是 0**
//	                （现数 `{'0': 64}`）⇒ 这一支在真夹具上**零行使**，
//	                接它之前得先造一份绑了 `SkillLevel` 的合成计划。
//
// ★ `shield` **已经产出**（`shieldOf`，见下面那一段的说明）：它读的是
// `d.talents[*].effects` 的五个 `shield_*` 字段（`_shield_of` 取 cap 的较大者），
// 而那一族字段由 `apply_text_rules` 的「护盾破裂」支写出来——判据**只认正文**，
// 天赋侧全库只有两条命中（泥岩「沃土予身」6 档、空弦「铁弦」2 档，现数）。
//
// ★ 上一轮在这里的 `heals` **已经产出**（见 `OperatorUnportedReady` 的说明）。
//
// ★ 这一份是**具名的**：判据会把它与 Go 应答里的 `unported` 做**双向集合比对**
// （像 `check_spawns_go.py` 那样），并每次运行重量一次「Python 那一侧实际送出了
// 其中几个」——哪天 Go 接上了，这里会先红，而不是等到某次对拍少送一个键。
var OperatorUnported = []string{}

// ★ **2026-09-24 起这份清单为空**：`skill` / `active` 两个键 Go 自己产出了
// （`skillbind.go`：槽号 0⇒技 1、等级取 7、黑板走键表算 active 快照）。
// 上面那整段「为什么先不接」的理由因此**整段作废**——尤其是「24 份夹具的
// `deploys[*].skill` 全是 0 ⇒ 这一支零行使」那句：按博士 2026-09-24 的口径，
// `skill: 0` 是**默认技能＝技 1**，那不是零行使，是 **64 / 64 人次都在用**。
// ★ 留一个空切片而不是删掉这个变量：判据那一侧靠它做**双向集合比对**
// （「Go 的 unported 与判据的清单逐名相等」），删掉变量会让那条比对失去对象。

// OperatorUnportedReady 已**清空**（原来只有 `heals`）。
//
// `heals` 现在**已产出**（`TextDerived.Heals`，与 Python 同判据同数据源，
// 64 人次里 9 次被行使）。留着这个空表是为了让判据那边的同名守卫继续存在：
// 它答的是「`unported` 里还有没有**其实已经能搬**的条目」——
// 清空之后那句守卫变成「必须为空」，一旦谁再往里塞一条能搬的，它会红。
var OperatorUnportedReady = []string{}

// OperatorViewFields 是 `_operator_spec` 读 `op` 的 **29** 个属性名（含 4 个方法）。
//
// 判据用 `ast` 从 `spec.py` 的 `_operator_spec` 里现抽一份（`op.<x>` 与
// `getattr(op, "<x>", …)` 两种写法），与这里的**双向**比对。
var OperatorViewFields = []string{
	"attack_interval", "attack_speed", "attack_type", "block_cnt", "char_id",
	"combo_damage_scale", "combo_hit_scale", "combo_hits",
	"current_atk", "current_defense", "current_range_id", "current_res",
	"deploy_cost", "direction", "elite", "heals",
	"highland_splash_scale", "highland_splash_sluggish", "max_hp", "name",
	"nation_id", "position", "power_attack_count", "power_attack_scale",
	"profession", "redeploy_time", "splash_damage_scale", "splash_radius",
	"splash_scale",
}

// OperatorDeployFields 是 `_operator_spec` 读 `d` 的 3 个属性名。
var OperatorDeployFields = []string{"direction", "position", "talents"}

// OperatorOut 是 `operators[i]` 的一条。
//
// ★ 为什么**不**直接用 `wire.go::OperatorSpec`：那个结构体是给模拟器**读**的，
// 它的条件键靠 `omitempty` 表达「不送」——而 `splash_scale` 这一个是
// 「送、且值可以是 `0.0`」：`omitempty` 会把它静默吃掉，症状是 Python 有键、
// Go 没有，而两边的**数值**对得上（判据只看值就抓不到）。
// 所以这里用**指针**表达存在性，键名与 `OperatorSpec` 逐个相同；
// 判据比对「（Go 实际送出的键集 − GO_ONLY）∪ unported ＝ `OperatorSpec`
// 的 36 个键减去 GO_ONLY 的 1 个」——三分类的等式见 `check_operators_go.py` §7。
type OperatorOut struct {
	CharID string `json:"char_id"`
	Name   string `json:"name"`
	Cell   [2]int `json:"cell"`

	MaxHP          float64  `json:"max_hp"`
	ATK            float64  `json:"atk"`
	DEF            float64  `json:"def"`
	RES            float64  `json:"res"`
	AttackInterval float64  `json:"interval"`
	DamageType     string   `json:"damage_type"`
	BlockCnt       int      `json:"block_cnt"`
	DeployCost     int      `json:"deploy_cost"`
	RedeployTime   float64  `json:"redeploy_time"`
	Range          [][2]int `json:"range"`

	NationID   *string `json:"nation_id,omitempty"`
	Profession *string `json:"profession,omitempty"`

	//: ---- 职业特性：生命流失（怪杰那一族）----
	//:
	//: 与上面那两条_条件键_**同一姿势**：用**指针**表达存在性，`> 0` 才送。
	//: 为什么 0 就不送（而不是像 `splash_scale` 那样「送、且值可以是 0」）：
	//: `readHPDrain` 的「没有这条特性」**本来就返回 0.0**（特性正文不含那句话
	//: ⇒ 直接 0），而 Python 那侧**根本不送这个键**（`GO_ONLY`）。也就是说
	//: 「送一个 0」在这条通道里没有任何对应的含义——它只会让「这位没有这条特性」
	//: 与「这位有、速率是 0」长得一样，而后者不存在。
	//:
	//: ⚠ `omitempty` 在这里是**语义的一部分**：它让「没有这条特性」表现为
	//: **键缺席**，与 `wire.go::OperatorSpec.HPDrainPerSec` 的 0 同义
	//: （`sim.go::traitDrainTick` 判的就是 `rate <= 0`）。
	//: ⚠ 别拿 `frontend/operator_view.py:179` 的 `self.hp_drain_per_sec = 0.0`
	//: 当反例：那是**另一条路**的视图，不是模拟器读的这份规格。
	HPDrainPerSec *float64 `json:"hp_drain_per_sec,omitempty"`

	//: ---- 技能那一支（2026-09-24 起由 Go 自己产出）----
	//:
	//: 与 `wire.go::OperatorSpec` 的 `Skill` / `Active` 同名同形。在那之前，
	//: 这两个键在 `OperatorUnported` 里（「Python 有、Go 没有」）——现在是 Go 自己算。
	//: 口径见 `skillbind.go` 的文件头：槽号 `0` ⇒ 技 1；等级取 7。
	Skill  *SkillSpec `json:"skill,omitempty"`
	Active *Profile   `json:"active,omitempty"`

	//: **只在本进程内用**：这一位干员的技能黑板里落在首发表之外的键。
	//: 不出去（`json:"-"`）——出去的那一份是 bundle 上汇总+去重的 `SkillUnknownKeys`，
	//: 逐人一份会把同一个键重复报很多遍，读的人反而看不出「一共缺哪几个键」。
	SkillUnknownKeys []string `json:"-"`

	//: **天赋折进面板的那三个比例**（`talentpanel.go`），原样透出给判据。
	//:
	//: ★ 为什么必须出去：Go 与 Python 在这一点上**有意分道扬镳**
	//: （博士 2026-09-24：不用管 Python，Go 折、Python 不折）。判据要比「两边一致」，
	//: 就得知道**Go 乘了多少**才能把两边还原到同一个量；否则它只能报红，
	//: 而那是把「已登记的口径差」当成缺陷。判据**不猜、不手抄**——这一栏由 Go 自己报。
	TalentPanelMods map[string]float64 `json:"talent_panel_mods,omitempty"`

	//: ---- 天赋的**非面板**效果（2026-09-25，`talenteffects.go`）----
	//:
	//: 每个键以**指针 ＋ omitempty** 出去：「没有这一条」与「有这一条、值是 0」
	//: 必须分得开（本仓记过：用带 `omitempty` 的裸值会让两者长得一样）。
	TalentDeploySP      *float64 `json:"talent_deploy_sp,omitempty"`
	TalentProcFactor    *float64 `json:"talent_proc_factor,omitempty"`
	TalentExtraHealProb *float64 `json:"talent_extra_heal_prob,omitempty"`
	TalentDodgeOnHeal   *float64 `json:"talent_dodge_on_heal,omitempty"`
	TalentDodgeSeconds  *float64 `json:"talent_dodge_seconds,omitempty"`
	//: 这一位的天赋黑板里、**键表之外**的键（排序去重）。与 `SkillUnknownKeys`
	//: 同一个姿势：逐位的这一份只在本进程内用，汇总去重的在 bundle 上。
	TalentUnknownKeys []string `json:"-"`

	SplashRadius           *float64 `json:"splash_radius,omitempty"`
	SplashScale            *float64 `json:"splash_scale,omitempty"`
	SplashDamageScale      *float64 `json:"splash_damage_scale,omitempty"`
	HighlandSplashScale    *float64 `json:"highland_splash_scale,omitempty"`
	HighlandSplashSluggish *float64 `json:"highland_splash_sluggish,omitempty"`

	ComboHits        *int     `json:"combo_hits,omitempty"`
	ComboHitScale    *float64 `json:"combo_hit_scale,omitempty"`
	ComboDamageScale *float64 `json:"combo_damage_scale,omitempty"`

	PowerAttackCount *int     `json:"power_attack_count,omitempty"`
	PowerAttackScale *float64 `json:"power_attack_scale,omitempty"`

	//: ---- 天赋派生（段 B 的第一批）----
	//:
	//: ⚠ 这七个键**不用** `wire.go` 的 `TeamAuraSpec` / `RegenAuraSpec`：
	//: 那两个结构体的 json 标签带 `omitempty`，而 Python 那边 `atk_pct` /
	//: `def_pct` / `nation_mult` 是**每次都送**的（值可以是 0）。用它们会让
	//: 「Go 少一个键」与「Python 送了个 0」长得一样，而**数值本身对得上**
	//: ——判据只比值就抓不到这一类。所以这里用裸 map／指针，键完全由我们写。
	Heals *bool `json:"heals,omitempty"`
	//: 特性正文含「技能可以治疗友方单位」（守护者那一族）：**技能开启期间**平A 变成治疗。
	//: 与 `Heals` 互补，两个键可以同时不出（普通输出手）。
	HealsOnSkill *bool `json:"heals_on_skill,omitempty"`
	//: 特性正文含「优先攻击空中单位」（狙击·速射手那一族）：选目标时**飞行单位优先**。
	//: 「优先」不是「只能」——范围里只有地面单位时照打（过滤掉会让速射手在无空中
	//: 单位的关卡里一次都不出手）。
	AirPriority *bool `json:"air_priority,omitempty"`
	//: 特性正文含「同时攻击阻挡的所有敌人」（泡普卡）：一次出手打**她自己挡住的全部**，
	//: 而不是「范围内所有人」。
	AttacksAllBlocked *bool `json:"attacks_all_blocked,omitempty"`
	//: **天赋**正文含「优先攻击防御力最高的敌人」（史都华德）：选目标时防御力高的优先。
	PreferHighestDef *bool `json:"prefer_highest_def,omitempty"`
	//: **天赋**正文含「优先攻击使用远程武器的敌人」（安德切尔）：`ApplyWay == RANGED` 优先。
	PreferRanged       *bool            `json:"prefer_ranged,omitempty"`
	BlessingSave       *float64         `json:"blessing_save,omitempty"`
	BlessingSelfFreeze *float64         `json:"blessing_self_freeze,omitempty"`
	RegenAura          map[string]any   `json:"regen_aura,omitempty"`
	TeamAuras          []map[string]any `json:"team_auras,omitempty"`
	TalentDodgePhys    *float64         `json:"talent_dodge_phys,omitempty"`
	TalentDodgeArts    *float64         `json:"talent_dodge_arts,omitempty"`

	//: ---- 段 B 第二批：`_shield_of` ----
	//:
	//: ★ 直接用**消费者的** `wire.go::ShieldSpec`，不另立一个同键结构体：
	//: 这五个键（`max_layers` / `layers` / `interval` / `break_heal_ratio` /
	//: `break_sp`）**一个口径一个宿主**——生产侧与消费侧各写一份，
	//: 迟早漂成两个契约（`sim.go:607` 就是读它的那一处）。
	//:
	//: ⚠ 与上面那七个**相反**：那些不能用 `wire` 的类型，是因为那两族结构体的
	//: json 标签带 `omitempty`（值 0 会被静默吃掉）。`ShieldSpec` 的五个内部键
	//: **都没有 `omitempty`**，所以它能原样当生产侧的落点；「没有护盾」由
	//: **指针为 nil** 表达（`omitempty`），与 Python 的 `None` 同义。
	Shield *ShieldSpec `json:"shield,omitempty"`
}

// OperatorsParams 是这次构造的**入参回执**（人读的痕迹，判据不看它）。
type OperatorsParams struct {
	Plan   string `json:"plan"`
	Roster string `json:"roster"`
	//: `getattr(inp, "heal_mode", "range")`——只影响 `regen_aura.strict` 那一位
	//: （`target` = 严格读法：只算光环落地之后才进场的友方）。**生产路径恒
	//: `range`**，所以这一位由调用方给定、判据两侧各跑一次（与 `p3r_armed` 同形）。
	HealMode string `json:"heal_mode,omitempty"`
}

// OperatorsBundle 是 `operators` 命令的一整份应答。
type OperatorsBundle struct {
	Operators    []OperatorOut
	Unported     []string
	Covered      map[string]int
	Scanned      int
	Params       OperatorsParams
	ViewFields   []string
	DeployFields []string
	//: **技能黑板里落在首发表之外的键**（排序去重）。空＝这一批技能恰好都在表里。
	//:
	//: ★ 为什么单独一栏而不是只留一个计数：博士给的验收标准是「落在表外的新键要**具名**
	//: 出现在覆盖账上」。**计数说不出是哪个键**，而「是哪个键」正是下一步要补的东西。
	SkillUnknownKeys []string
	//: **天赋黑板里落在首发表之外的键**（同一套汇总/去重/排序，与技能那一栏分账）。
	//: 空＝这一批天赋恰好都在表里；非空要能**指名**——博士给的验收标准就是这一条。
	TalentUnknownKeys []string
}

// OperatorsCoveredKeys 是 `covered` 的**全部**计数器。
//
// ★ 全部预置为 0 再往上加，不用「有才出现」的 map：漏一个键的症状是
// 「这一档没被行使到」与「这一档的计数器根本不存在」长得一模一样，
// 而后者会让两侧的行使计数对账**静默少比一项**（判据的尺子少一格）。
var OperatorsCoveredKeys = []string{
	"range_code_in_table", "range_code_missing", "range_origin_added",
	"nation_id_empty", "profession_empty",
	"splash_radius_nonzero", "highland_splash_scale_nonzero",
	"highland_splash_sluggish_nonzero",
	"combo_hits_gt1", "power_attack_count_gt0",
	//: ---- 段 B 第一批（天赋派生）----
	"heals_true", "heals_on_skill_true", "air_priority_true",
	"attacks_all_blocked_true", "prefer_highest_def_true", "prefer_ranged_true",
	"blessing_nonzero", "regen_aura_nonzero",
	"team_auras_nonzero", "talent_dodge_nonzero",
	"regen_strict_true", "regen_strict_false",
	//: ---- 段 B 第二批 ----
	//: `shield` 非空的人次（**不是**「字段非空」那种空口径：它数的是
	//: `_shield_of` 真的返回了一份配置的那些人次）。判据那一侧**独立**再数一遍
	//: （`check_operators_go.py::live_counters`），两数不等即红。
	"shield_nonzero",
	//: ---- 技能那一支（2026-09-24）----
	//: 三名会计：绑上的部署人次／没有技能槽的人次／**未识别黑板键的实例数**。
	//: ⚠ 第三个数是**覆盖账**：它回答「这一批技能里有多少个键落在首发表之外」。
	//: 零要有理由（这一批恰好都在表里），非零要能指名——名字走
	//: `OperatorsBundle.SkillUnknownKeys`（同一个响应里）。
	"skill_bound", "skill_none", "skill_unknown_key_instances",
	//: ---- 天赋的非面板效果（`talenteffects.go`，2026-09-25）----
	//: 四个**行使计数器**（不是「字段非空」：每一位都要它这一项真的非零才 +1）＋
	//: 一个**未识别键实例数**。零要有理由，非零要能指名——名字走
	//: `OperatorsBundle.TalentUnknownKeys`（同一个响应里）。
	"talent_deploy_sp", "talent_proc", "talent_extra_heal",
	"talent_dodge_on_heal", "talent_unknown_key_instances",
}

// newOperatorsCovered 造一张**每个键都在、值为 0** 的计数表。
func newOperatorsCovered() map[string]int {
	out := make(map[string]int, len(OperatorsCoveredKeys))
	for _, k := range OperatorsCoveredKeys {
		out[k] = 0
	}
	return out
}

// ---------------------------------------------------------------- 取值小工具

// totalRequire 取一个**必须有**的面板项（原版是 `float(t["atk"])` 这种写法，
// 缺键会 `TypeError`）。缺键在这里也要**大声失败**，不许静默给 0——
// 静默给 0 的症状是「这名干员面板是 0」，而规格看上去是完整的。
func totalRequire(m map[string]any, key string) (float64, error) {
	v, ok := m[key]
	if !ok {
		return 0, fmt.Errorf("面板 total 里没有 %s", key)
	}
	f, ok := toFloat(v)
	if !ok {
		return 0, fmt.Errorf("面板 %s 不是数：%T", key, v)
	}
	return f, nil
}

// totalOrDef 复刻 `float(t.get(k, d) or d)`：键不在用 d，值是 0 也用 d。
func totalOrDef(m map[string]any, key string, def float64) (float64, error) {
	v, ok := m[key]
	if !ok {
		return def, nil
	}
	f, ok := toFloat(v)
	if !ok {
		return 0, fmt.Errorf("面板 %s 不是数：%T", key, v)
	}
	if f == 0 {
		return def, nil
	}
	return f, nil
}

// pyOrOne 复刻 `float(getattr(op, k, 1.0) or 1.0)`——**「没有这条」是 1.0**。
// 写成 0 会让每一位没有这条的干员在 Go 那边被当成 0 倍率。
func pyOrOne(v float64) float64 {
	if v == 0 {
		return 1.0
	}
	return v
}

// ---------------------------------------------------------------- 范围

// operatorRangeCode 复刻 `verify.py:204-207` 的 `range_id_of`：
// `phases[clamp(elite)].rangeId or "1-1"`。
//
// ⚠ 夹取与 `OperatorStatsFor` 的**大声失败**不同口径：原版这里 `min` 到最后一阶，
// 所以 `elite` 越界在取范围这一步不会报错。照抄。
func operatorRangeCode(charID string, elite int) (string, error) {
	tbl, err := loadCharTable()
	if err != nil {
		return "", err
	}
	raw, ok := tbl[charID]
	if !ok || string(raw) == "null" {
		return "", fmt.Errorf("character_table 里没有 %q", charID)
	}
	var c struct {
		Phases []struct {
			RangeID string `json:"rangeId"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(raw, &c); err != nil {
		return "", fmt.Errorf("%s 的 phases 解析失败：%w", charID, err)
	}
	if len(c.Phases) == 0 {
		return "", fmt.Errorf("%s 一个精英阶段都没有", charID)
	}
	e := elite
	if e < 0 {
		e = 0
	}
	if e > len(c.Phases)-1 {
		e = len(c.Phases) - 1
	}
	code := c.Phases[e].RangeID
	if code == "" {
		code = "1-1"
	}
	return code, nil
}

// facingVector 复刻 `geometry.facing`：认不出的一律朝右。
func facingVector(direction string) [2]int {
	switch direction {
	case "Left":
		return [2]int{-1, 0}
	case "Up":
		return [2]int{0, -1}
	case "Down":
		return [2]int{0, 1}
	default:
		return [2]int{1, 0}
	}
}

// degenerateRange 复刻 `range_of` 的退化范围：自身格 ＋ 朝向前方三格。
func degenerateRange(direction string, pos [2]int) [][2]int {
	f := facingVector(direction)
	out := make([][2]int, 0, 4)
	for i := 0; i <= 3; i++ {
		out = append(out, [2]int{pos[0] + f[0]*i, pos[1] + f[1]*i})
	}
	sortRangeCells(out)
	return out
}

// sortRangeCells 复刻 Python 的 `sorted([int(x), int(y)] for …)`：按 (x, y) 字典序。
//
// ⚠ 名字带 `Range` 是**必须的**：本包已经有一个 `sortCells`（`mechspec.go:644`，
// 另一条会话的机制规格在用）。两个都叫 `sortCells` 时 `go build` 直接报
// 「redeclared in this block」——实测撞过一次；这正是「同一个名字在同一个包里
// 只能有一个宿主」在**同一语言内**的样子（跨语言的同名不同义是另一回事）。
func sortRangeCells(cells [][2]int) {
	sort.Slice(cells, func(i, j int) bool {
		if cells[i][0] != cells[j][0] {
			return cells[i][0] < cells[j][0]
		}
		return cells[i][1] < cells[j][1]
	})
}

// operatorRange 复刻 `RangeProvider.__call__` ＋ `geometry.range_of`：
//
//	code = range_id or range_id_of(char_id, elite)
//	cells = 表[code]（本表自身格恒 (0,0)，不必平移）
//	if 取不到 code: 退化范围（自身格 ＋ 前方三格）
//	cells ∪ {(0,0)}          ← block_of 恒为 1（`verify.py:210` 的 lambda）
//	footprint(cells, direction, position)   ← 旋转 ＋ 平移
//
// 返回值第二个是**行使计数**用的两个标记：代号在不在表里、以及这一次是不是
// 靠 `∪ {(0,0)}` 补上的（实测 64 人次里有 1 次真的靠它——`4-3` 那张表不含自身格）。
func operatorRange(code, direction string, pos [2]int) ([][2]int, bool, bool, error) {
	switch direction {
	case "Right", "Up", "Left", "Down":
	default:
		//: 原版走 `normalize_direction` 的别名表，认不出就 `except Exception: pass`
		//: 静默退化成「自身格 ＋ 前方三格」。Go 不照抄那个静默——`range.go` 已经
		//: 把这条定成具名缺口（只认四个正名），在集成处同样大声失败。
		return nil, false, false, fmt.Errorf(
			"认不出的朝向 %q（`operators` 只认 Right/Left/Up/Down 四个正名；"+
				"原版的别名表未读，见 range.go 文件头）", direction)
	}
	tbl, err := LoadRangeTable()
	if err != nil {
		return nil, false, false, err
	}
	raw, inTable := tbl[code]
	if !inTable {
		return degenerateRange(direction, pos), false, false, nil
	}
	rel := make(map[Cell]bool, len(raw)+1)
	for _, c := range raw {
		rel[c] = true
	}
	added := !rel[Cell{0, 0}]
	rel[Cell{0, 0}] = true
	list := make([]Cell, 0, len(rel))
	for c := range rel {
		list = append(list, c)
	}
	fp, err := Footprint(list, direction, pos[0], pos[1])
	if err != nil {
		return nil, false, false, err
	}
	out := make([][2]int, 0, len(fp))
	for _, c := range fp {
		out = append(out, [2]int{c[0], c[1]})
	}
	sortRangeCells(out)
	return out, true, added, nil
}

// ---------------------------------------------------------------- 一条干员规格

// buildOperatorOut 造 `operators[i]`，并把这一次**行使到了哪些条件键**记进
// `covered`（零信息量的绿要防：某个键 64 次一次都没送出去，它的「逐位相等」
// 就是「两边都没有」这种空洞的相等）。
func buildOperatorOut(r DeployRow, covered map[string]int,
	healMode string) (OperatorOut, error) {
	e := r.Entry
	trust := 0.0
	if e.Trust != nil {
		trust = float64(*e.Trust)
	}
	module := ""
	if e.Module != nil {
		module = *e.Module
	}
	modLevel := 0
	if e.ModuleLevel != nil {
		modLevel = *e.ModuleLevel
	}
	cfg := OperatorCalcConfig{
		CharID: e.CharID, Elite: e.Elite, Level: e.Level, Trust: trust,
		Potential: e.Potential, Module: module, ModuleLevel: modLevel,
	}
	st, err := OperatorStatsFor(cfg, "round")
	if err != nil {
		return OperatorOut{}, err
	}
	t := st.Total

	atk, err := totalRequire(t, "atk")
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	def, err := totalRequire(t, "def")
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	maxHP, err := totalRequire(t, "maxHp")
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	res, err := totalOrDef(t, "magicResistance", 0.0)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	base, err := totalOrDef(t, "baseAttackTime", 1.0)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	//: ⚠ 攻速 = 面板 ＋ 天赋/模组特性给的那一份（`verify.py:326` 的 `+ aspd.flat`）。
	//: 漏掉 `AttackSpeedBonus.Flat` 的症状是**间隔整体偏大**：实测 64 人次里
	//: 8 人次非零（能天使一族，面板 100 / 加成后 115，间隔 0.8695652173913043）。
	aspd, err := totalOrDef(t, "attackSpeed", 100.0)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	spd := aspd + st.AttackSpeedBonus.Flat
	interval := math.Max(opsMinInterval, base*100.0/math.Max(opsAspdMin, spd))

	blockCnt, err := totalOrDef(t, "blockCnt", 0.0)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s：%v", e.CharID, err)
	}
	//: 部署费用走**具名入口** `CostOf`（`deploycost.go`），不在这里另取一遍
	//: `total["cost"]`——同一个量两份取法迟早会分叉，而 `deploys[].cost` 用的
	//: 正是 `CostOf`，两处必须是同一个数。
	cost, err := CostOf(cfg)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s（%s）的部署费用：%v",
			r.Operator, e.CharID, err)
	}

	code, err := operatorRangeCode(e.CharID, e.Elite)
	if err != nil {
		return OperatorOut{}, err
	}
	cells, inTable, originAdded, err := operatorRange(code, r.Direction, r.Position)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s（%s）：%v", r.Operator, e.CharID, err)
	}
	if inTable {
		covered["range_code_in_table"]++
	} else {
		covered["range_code_missing"]++
	}
	if originAdded {
		covered["range_origin_added"]++
	}

	out := OperatorOut{
		CharID: e.CharID, Name: st.Name, Cell: r.Position,
		MaxHP: maxHP, ATK: atk, DEF: def, RES: res,
		AttackInterval: interval, DamageType: st.TextDerived.DamageType,
		BlockCnt: int(blockCnt), DeployCost: cost,
		//: ⚠ 常量 70.0，**不是** `total["respawnTime"]`：`verify.py:314-355` 的
		//: `kw` 里没有 `redeploy_time`，所以原版读到的恒是 `OperatorView` 的
		//: 默认值。这一点由判据每次现算（非 0 即红），见文件头第 2 条。
		RedeployTime: opsRedeployDefault,
		Range:        cells,
	}
	//: 势力代号：取不到就是空串（等于不翻倍），原版据此**不送这个键**。
	if st.NationID != "" {
		v := st.NationID
		out.NationID = &v
	} else {
		covered["nation_id_empty"]++
	}
	if st.Profession != "" {
		v := st.Profession
		out.Profession = &v
	} else {
		covered["profession_empty"]++
	}
	//: 职业特性「自身生命会不断流失」（怪杰）：`> 0` 才送，与 `splash_*` 同族。
	//: ★ 这是**段 A 之外的键**（Python 的 `_operator_spec` 不产出它）——
	//: 判据那一侧具名进 `GO_ONLY`，见 `wire.go` 上那一段的说明。
	if st.HPDrainPerSec > 0.0 {
		v := st.HPDrainPerSec
		out.HPDrainPerSec = &v
	}
	//: 职业特性溅射：`radius > 0` 才整族送出去。
	if st.SplashRadius > 0.0 {
		covered["splash_radius_nonzero"]++
		rad, sc := st.SplashRadius, st.SplashScale
		out.SplashRadius, out.SplashScale = &rad, &sc
		ds := pyOrOne(st.SplashDamageScale)
		out.SplashDamageScale = &ds
		if st.HighlandSplashScale > 0.0 {
			covered["highland_splash_scale_nonzero"]++
			hi := st.HighlandSplashScale
			out.HighlandSplashScale = &hi
			if st.HighlandSplashSluggish > 0.0 {
				covered["highland_splash_sluggish_nonzero"]++
				sl := st.HighlandSplashSluggish
				out.HighlandSplashSluggish = &sl
			}
		}
	}
	//: 普攻连击：「没有这条」是 1 / 1.0 / 1.0，原版判的是 `> 1`。
	if st.ComboAttack.Hits > 1 {
		covered["combo_hits_gt1"]++
		h := st.ComboAttack.Hits
		hs := pyOrOne(st.ComboAttack.HitScale)
		ds := pyOrOne(st.ComboAttack.DamageScale)
		out.ComboHits, out.ComboHitScale, out.ComboDamageScale = &h, &hs, &ds
	}
	//: 「强击瓶专家」：`count > 0` 才送，`scale` 的「没有这条」是 1.0。
	if st.PowerAttack.Count > 0 {
		covered["power_attack_count_gt0"]++
		n := st.PowerAttack.Count
		sc := pyOrOne(st.PowerAttack.Scale)
		out.PowerAttackCount, out.PowerAttackScale = &n, &sc
	}

	//: ---- 天赋派生（段 B 第一批）----
	//:
	//: 权威那五段（`_shield_of` 除外）的共同点：**读 `d.talents` 现算，不读运行期
	//: 属性**——`op.blessing_*` / `op.shield_*` / `op.talent_dodge_*` 要到
	//: `_do_deploy` 那一刻才被写上（`sim.py:3417` / `3157` / `2688`），而规格
	//: 正是**在那之前**取的。读运行期只会读到 0，而「规格里是 0」与「这个干员
	//: 本来就没有」在 Go 那边长得一模一样 —— 是**静默**的。
	talents, err := charTalents(e.CharID, e.Elite, e.Level, e.Potential)
	if err != nil {
		return OperatorOut{}, fmt.Errorf("%s（%s）的天赋：%v", r.Operator, e.CharID, err)
	}
	//: `heals`：Python 读 `op.heals`，Go 侧同一判据的现成字段是
	//: `TextDerived.Heals`（特性正文含「恢复友方单位生命」）。
	if st.TextDerived.Heals {
		covered["heals_true"]++
		b := true
		out.Heals = &b
	}
	//: `heals_on_skill`：特性正文含「技能可以治疗友方单位」（守护者那一族）。
	//: 与上面的 `heals` **互补**、不是同一条的强弱——两族的判据在 `sim.go` 里
	//: 分两路走（见 `operator_traits.go::TextDerived.HealsOnSkill` 的注释）。
	if st.TextDerived.HealsOnSkill {
		covered["heals_on_skill_true"]++
		b := true
		out.HealsOnSkill = &b
	}
	//: 特性那两条**只在正文里**的（黑板是空的，见 `operator_traits.go` 的常量注释）：
	//: 「优先攻击空中单位」与「同时攻击阻挡的所有敌人」。
	if st.TextDerived.AirPriority {
		covered["air_priority_true"]++
		b := true
		out.AirPriority = &b
	}
	if st.TextDerived.AttacksAllBlocked {
		covered["attacks_all_blocked_true"]++
		b := true
		out.AttacksAllBlocked = &b
	}
	//: 两条**天赋**正文里的选目标优先（史都华德 铠甲突破／安德切尔 短板突破）——
	//: 与上面两条同族，只是出处是**天赋**正文（黑板里一个字都没写）。
	if st.TextDerived.PreferHighestDef {
		covered["prefer_highest_def_true"]++
		b := true
		out.PreferHighestDef = &b
	}
	if st.TextDerived.PreferRanged {
		covered["prefer_ranged_true"]++
		b := true
		out.PreferRanged = &b
	}
	//: `blessing_save` / `blessing_self_freeze`：判据是 `find_blessing` 的两个
	//: 黑板键**同时**在（`c2e_freeze` / `freeze`），只在 `c2e_freeze > 0` 时送。
	if tb, ok := tfFindBlessing(talents); ok {
		save := bbValue(tb.Blackboard, "c2e_freeze", 0.0)
		if save > 0.0 {
			covered["blessing_nonzero"]++
			fz := bbValue(tb.Blackboard, "freeze", 0.0)
			out.BlessingSave, out.BlessingSelfFreeze = &save, &fz
		}
	}
	//: `talent_dodge_phys` / `_arts`：`find_damage_block` 的 `prob`，**两个键同值**。
	//: 只在任一个非零时送（原版是 `if talent_phys or talent_arts:`）。
	if tb, ok := tfFindDamageBlock(talents); ok {
		v := bbValue(tb.Blackboard, "prob", 0.0)
		if v != 0.0 {
			covered["talent_dodge_nonzero"]++
			out.TalentDodgePhys, out.TalentDodgeArts = &v, &v
		}
	}
	//: `regen_aura`：**五个键一律写**（Python 一个都不省）。
	//: `strict` 跟 `inp.heal_mode` 走——生产路径恒 `range` ⇒ false，
	//: 但这里把两支都计上数，免得「那一支从没跑过」与「那一支跑了 0 次」混成一个。
	if tb, ok := tfFindRegen(talents); ok {
		covered["regen_aura_nonzero"]++
		nation, mult := "", 1.0
		if tm, ok := tfFindMedicMonument(talents); ok {
			nation = tfRhodesNation
			mult = bbValue(tm.Blackboard, "rhodes_bonus", 1.0)
		}
		strict := healMode == "target"
		if strict {
			covered["regen_strict_true"]++
		} else {
			covered["regen_strict_false"]++
		}
		out.RegenAura = map[string]any{
			"hp_per_sec":  bbValue(tb.Blackboard, "hp_recovery_per_sec", 0.0),
			"duration":    bbValue(tb.Blackboard, "buff_duration", 0.0),
			"nation":      nation,
			"nation_mult": mult,
			"strict":      strict,
		}
	}
	//: `team_auras`：五条互不重叠的探测器，**顺序是契约**（Python 那个 list 的顺序）。
	//:
	//: ⚠ `double_scale` **每次都送**：原版那个字段的默认值是 2.0，
	//: 靠 `omitempty` 省掉它，Go 侧读到的就是 0——主人一开技能，加成会被乘成 0。
	if auras := teamAurasOf(talents, out.Name, e.CharID); len(auras) > 0 {
		covered["team_auras_nonzero"]++
		out.TeamAuras = auras
	}
	//: ---- 段 B 第二批：`_shield_of`（层数护盾）----
	//:
	//: 与上面那五段同一个姿势：**读 `d.talents` 现算**，不读 `op.shield_*`
	//: ——那一族属性要到 `_do_deploy` 里 `_attach_talent_shield`
	//: （`sim.py:3157-3182`）才被写上，而规格正是在**那之前**取的。
	if sh := shieldOf(talents); sh != nil {
		covered["shield_nonzero"]++
		out.Shield = sh
	}
	//: ---- 技能那一支（槽号 → 技能 id → 状态机 ＋ active 快照）----
	//:
	//: 口径见 `skillbind.go` 的文件头：计划里的槽号 `0` **不等于「不用技能」**
	//: （博士 2026-09-24），除一二星外 0 即默认技能＝技 1；技能等级取 7。
	//:
	//: ★ 未识别的黑板键**不许静默丢**：计数进 `covered`，名字进 bundle 的
	//: `SkillUnknownKeys`（调用方在 `BuildOperators` 里汇总）。
	if sk, act, unknown, err := bindSkillTo(e.CharID, r.Skill, atk, def, res,
		maxHP, spd, interval, st.TextDerived.DamageType); err != nil {
		return OperatorOut{}, fmt.Errorf("%s（%s）的技能绑定：%v", r.Operator, e.CharID, err)
	} else if sk != nil {
		covered["skill_bound"]++
		//: ★ 伤害类型**不再在这里填**：`bindSkillTo` 已经按博士 2026-09-24 的口径算好了
		//: ——基准由**特性**决定（没写「法术伤害」就一律物理），技能正文写明
		//: 「伤害类型变为 …」时按那句话切换（`DamageTypeFromSkillText`，按短语不按名字）。
		//: 留空串会让技能期间每一次出手都带空类型往下走：`sim.go` 按它选物理/法术，
		//: 空串既不是物理也不是法术，**不报错**，只是伤害算错。
		out.Skill, out.Active = sk, act
		if len(unknown) > 0 {
			covered["skill_unknown_key_instances"] += len(unknown)
			if out.SkillUnknownKeys == nil {
				out.SkillUnknownKeys = []string{}
			}
			out.SkillUnknownKeys = append(out.SkillUnknownKeys, unknown...)
		}
	} else {
		covered["skill_none"]++
	}
	//: **天赋折进面板的三个比例**原样透出（判据靠它把两边还原到同一个量）。
	//: 没有天赋给面板加成时**不送这个键**（`omitempty`）——与「有这条、比例是 0」
	//: 分开：后者不出现（`talentPanelMods` 只在真有非零比例时才写）。
	if len(st.TalentPanelMods) > 0 {
		nonzero := false
		for _, v := range st.TalentPanelMods {
			if v != 0 {
				nonzero = true
			}
		}
		if nonzero {
			out.TalentPanelMods = st.TalentPanelMods
		}
	}
	//: ---- 天赋的**非面板**效果（`talenteffects.go`，2026-09-25）----
	//:
	//: 与上面那三个比例同一个理由透出：这些量**发生在场上**（部署给技力、出手判概率、
	//: 治疗授闪避），判据要能看见「Go 到底送了什么」，否则只能靠判决反推。
	//:
	//: ⚠ 四项各自 `omitempty`：**「没有这一条」与「有这一条、值是 0」必须分得开**
	//: ——后者在语义上等于没有，但把它送出去会让判据以为这一位带了机制。
	te := st.TalentEffects
	if te.DeploySP != 0 {
		covered["talent_deploy_sp"]++
		v := te.DeploySP
		out.TalentDeploySP = &v
	}
	if te.ProcFactor != 1.0 {
		covered["talent_proc"]++
		v := te.ProcFactor
		out.TalentProcFactor = &v
	}
	if te.ExtraHealProb != 0 {
		covered["talent_extra_heal"]++
		v := te.ExtraHealProb
		out.TalentExtraHealProb = &v
	}
	if te.DodgeOnHeal != 0 {
		covered["talent_dodge_on_heal"]++
		v, d := te.DodgeOnHeal, te.DodgeSeconds
		out.TalentDodgeOnHeal, out.TalentDodgeSeconds = &v, &d
	}
	if len(st.TalentUnknownKeys) > 0 {
		covered["talent_unknown_key_instances"] += len(st.TalentUnknownKeys)
		out.TalentUnknownKeys = append([]string{}, st.TalentUnknownKeys...)
	}
	return out, nil
}

// shieldOf 复刻 `_shield_of`（`spec.py:647-678`）：这一次部署的**层数护盾**配置，
// 这个干员没有护盾就返回 `nil`（＝ Python 的 `None`，`_operator_spec` 据此**不送**键）。
//
// ## 三处必须照抄的口径
//
//  1. **只取第一个命中的**：原版那一句是 `return`，不是求并集。所以「同时带两条
//     护盾天赋」时后面的那条被丢掉——Go 也丢掉（`return` 而不是继续扫）。
//  2. **cap 取大者**：`max(shield_max_layers, shield_layers_on_deploy)`，**送的是
//     cap 而不是黑板上的 `max_times`**。实证：空弦「铁弦」的黑板只有 `sp`，
//     `max_times` 缺键 ⇒ `shield_max_layers=0`，可正文写着「获得**一层**护盾」
//     ⇒ `cap = max(0, 1) = 1` ⇒ **这一位仍然有护盾**。写成 `max_times` 会让
//     她整条天赋静默消失（层数 0 ⇒ 跳过 ⇒ Go 少送一个键，而两边的数都对得上）。
//  3. **`cap <= 0` 就跳过**：不是「送一份全 0 的配置」。
//
// ## 五个字段从哪来：`apply_text_rules` 的「护盾破裂」支
//
// 见 `shieldEffectOf`。**判据是正文，不是黑板键**——天赋侧全库（1375 位干员、
// 全部候选）只有 8 条候选命中「正文同时含【护盾】与【破裂】」，落在两个人身上：
// 泥岩「沃土予身」（6 档）与空弦「铁弦」（2 档）。现数，取证见
// `check_operators_go.py` 的同名判据与交付回报。
func shieldOf(talents []resolvedTalent) *ShieldSpec {
	for _, t := range talents {
		maxLayers, layers, interval, healRatio, sp := shieldEffectOf(t)
		cap := maxLayers
		if layers > cap {
			cap = layers
		}
		if cap <= 0 {
			continue
		}
		return &ShieldSpec{
			MaxLayers: cap, Layers: layers, Interval: interval,
			BreakHealRatio: healRatio, BreakSP: sp,
		}
	}
	return nil
}

// shieldEffectOf 复刻 `apply_text_rules` 的「护盾破裂」那一段（`skill.py:2073-2092`）
// **在一条天赋上**求值——不是（全部为 0 的）`SkillEffects` 默认值。
//
// 逐句对应（**原文照抄，故整段包反引号**——代码里的字符串字面量不许改成「」，
// 改了就成了另一段代码）：
//
//	`if "护盾" in description and "破裂" in description:`   ← 两个词**都要在**
//	`    eff.shield_interval        = float(bb.get("interval") or 0.0)`
//	`    eff.shield_max_layers      = int(bb.get("max_times") or 0)`
//	`    layers                     = int(bb.get("times") or 0)`
//	`    if not layers and "一层护盾" in description: layers = 1`
//	`    eff.shield_break_heal_ratio= float(bb.get("hp_ratio") or 0.0)`
//	`    eff.shield_break_sp        = float(bb.get("sp") or 0.0)`
//
// ⚠ 那两个 `or 0.0` 的含义是「**键不在**（`None`）当 0」——`bbValue` 的默认值
// 就是这个口径；键在、值是 0 时也一样是 0，两种写法在这里同值。
func shieldEffectOf(t resolvedTalent) (maxLayers, layers int,
	interval, healRatio, sp float64) {
	if !strings.Contains(t.Description, "护盾") ||
		!strings.Contains(t.Description, "破裂") {
		return 0, 0, 0, 0, 0
	}
	interval = bbValue(t.Blackboard, "interval", 0.0)
	maxLayers = int(bbValue(t.Blackboard, "max_times", 0.0))
	layers = int(bbValue(t.Blackboard, "times", 0.0))
	//: 部署时给几层：泥岩在黑板 `times` 里；空弦的黑板只有 `sp`，层数写在正文
	//: （「获得**一层**护盾」）——**按正文取，不猜**。注意判据是字面「一层护盾」：
	//: 泥岩的正文写的是「1层护盾」，所以走到的是上面那行（`times=1`），不是这里。
	if layers == 0 && strings.Contains(t.Description, "一层护盾") {
		layers = 1
	}
	healRatio = bbValue(t.Blackboard, "hp_ratio", 0.0)
	sp = bbValue(t.Blackboard, "sp", 0.0)
	return maxLayers, layers, interval, healRatio, sp
}

// teamAurasOf 复刻 `_team_auras_of`（`spec.py:551-644`）。
//
// 一名干员可以同时命中多条（「万众巨潮」与「特种作战策略」是并列的两条天赋），
// 所以是 list；**顺序**与权威逐个相同（team → class → covenant → angel → dispatch）。
func teamAurasOf(talents []resolvedTalent, owner, charID string) []map[string]any {
	out := []map[string]any{}
	if tb, ok, faction := tfFindTeamAura(talents); ok {
		atk := bbValue(tb.Blackboard, "atk", 0.0)
		def := bbValue(tb.Blackboard, "def", 0.0)
		if faction {
			//: 「万众巨潮」：只在主人技能期间生效，且对【乌萨斯学生自治团】
			//: **按 char_id 名单**翻倍。
			out = append(out, map[string]any{
				"owner": owner, "atk_pct": atk, "def_pct": def,
				"skill_only":    true,
				"faction":       append([]string{}, tfStudentTeam...),
				"faction_scale": bbValue(tb.Blackboard, "scale_bonus", 2.0),
				"double_scale":  2.0,
			})
		} else {
			//: 「青色怒火」：常驻 ＋ 主人开技能时加倍。
			out = append(out, map[string]any{
				"owner": owner, "atk_pct": atk, "def_pct": def,
				"double_scale": 2.0,
			})
		}
	}
	if tb, prof, ok := tfFindClassAura(talents); ok {
		out = append(out, map[string]any{
			"owner":   owner,
			"atk_pct": bbValue(tb.Blackboard, "atk", 0.0),
			"def_pct": bbValue(tb.Blackboard, "def", 0.0),
			//: ⚠ 这里是**主职业代号**（`TANK`），不是阵营 char_id 名单。
			"profession":   prof,
			"double_scale": 2.0,
		})
	}
	if tb, ok := tfFindAmmoCovenant(talents); ok {
		out = append(out, map[string]any{
			"owner":           owner,
			"atk_pct":         bbValue(tb.Blackboard, "atk", 0.0),
			"def_pct":         bbValue(tb.Blackboard, "def", 0.0),
			"double_scale":    bbValue(tb.Blackboard, "mult", 2.0),
			"ammo_skill_only": true,
			//: 按**势力**翻倍（【拉特兰】），与按名单翻倍是两种数据形态。
			"nation_double": tfLateranoNation,
		})
	}
	if tb, ok := tfFindAngelBlessing(talents); ok {
		out = append(out, map[string]any{
			"owner":        owner,
			"atk_pct":      bbValue(tb.Blackboard, "atk", 0.0),
			"def_pct":      0.0,
			"self_only":    true,
			"double_scale": 2.0,
		})
	}
	if tb, ok := tfFindLimitDispatch(talents); ok {
		out = append(out, map[string]any{
			"owner":   owner,
			"atk_pct": bbValue(tb.Blackboard, "atk", 0.0),
			"def_pct": 0.0,
			//: `faction_only` 是**筛选**（不匹配的一律 0），不是 `nation_double`
			//: 那种「该势力 ×2、别人 ×1」。两个字段别混。
			"faction_only": tfRhodesNation,
			"double_scale": 2.0,
		})
	}
	return out
}

// ---------------------------------------------------------------- 入口

// BuildOperators 造 `operators` 那一串（以及 unported / covered / 两份字段表）。
func BuildOperators(plan PlayPlan, roster RosterRead,
	stage *Stage, params OperatorsParams) (*OperatorsBundle, error) {
	rows, err := BuildDeployRows(plan, roster, stage)
	if err != nil {
		return nil, err
	}
	//: 配对靠 `char_id`：`Plan.validate` 保证同一份计划里干员不重复。
	//: 这一条**要在代码里也拦一次**——静默配错人的症状是「某个干员数字不对」，
	//: 而那是所有症状里最难往「配错」上想的一种。
	seen := make(map[string]bool, len(rows))
	for _, r := range rows {
		if seen[r.Entry.CharID] {
			return nil, fmt.Errorf(
				"同一份计划里 %s 出现了两次——`operators` 按 char_id 配对，"+
					"重复会让两个键的次序口径分叉", r.Entry.CharID)
		}
		seen[r.Entry.CharID] = true
	}
	covered := newOperatorsCovered()
	out := make([]OperatorOut, 0, len(rows))
	for _, r := range rows {
		o, err := buildOperatorOut(r, covered, params.HealMode)
		if err != nil {
			return nil, err
		}
		out = append(out, o)
	}
	//: 技能未识别键：**汇总 ＋ 去重 ＋ 排序**。逐人一份会把同一个键重复报很多遍，
	//: 读的人反而看不出「一共缺哪几个键」——而那正是要补的东西。
	unknownKeys := collectUnknownKeys(out, func(o OperatorOut) []string {
		return o.SkillUnknownKeys
	})
	//: 天赋未识别键：同一套**汇总 ＋ 去重 ＋ 排序**（两族各记一份账，不合并——
	//: 合并之后「技能缺哪个键」与「天赋缺哪个键」就分不开了，而那两族是分开补的）。
	talentUnknownKeys := collectUnknownKeys(out, func(o OperatorOut) []string {
		return o.TalentUnknownKeys
	})
	return &OperatorsBundle{
		Operators: out,
		Unported:  append([]string{}, OperatorUnported...),
		Covered:   covered,
		//: `scanned` 与 `len(Operators)` **同源**（不是第二次计数）：一个量只能
		//: 有一个口径来源，两处各数一遍迟早印出两个数。
		Scanned:           len(out),
		Params:            params,
		ViewFields:        append([]string{}, OperatorViewFields...),
		DeployFields:      append([]string{}, OperatorDeployFields...),
		SkillUnknownKeys:  unknownKeys,
		TalentUnknownKeys: talentUnknownKeys,
	}, nil
}

// collectUnknownKeys 把逐位干员身上的某一份未识别键清单**汇总 ＋ 去重 ＋ 排序**。
//
// ★ 抽出来是因为现在有**两族**（技能／天赋）要同一套动作：写在两处的复制品迟早
// 只改一处。`pick` 是「从这个人身上取哪一份清单」。
func collectUnknownKeys(ops []OperatorOut, pick func(OperatorOut) []string) []string {
	seen := map[string]bool{}
	var out []string
	for _, o := range ops {
		for _, k := range pick(o) {
			if !seen[k] {
				seen[k] = true
				out = append(out, k)
			}
		}
	}
	sort.Strings(out)
	if out == nil {
		out = []string{}
	}
	return out
}

// BuildOperatorsFor 从两条路径读入，造 `operators`（命令用）。
//
// `healMode` 空串按权威的默认值 `range` 走（`getattr(inp, "heal_mode", "range")`）。
func BuildOperatorsFor(planPath, rosterPath, healMode string) (*OperatorsBundle, error) {
	if planPath == "" {
		return nil, fmt.Errorf("operators 少了 plan 路径")
	}
	if healMode == "" {
		healMode = "range"
	}
	plan, err := ReadPlan(planPath)
	if err != nil {
		return nil, err
	}
	var rs RosterRead
	if rosterPath != "" {
		if rs, err = ReadRoster(rosterPath); err != nil {
			return nil, err
		}
	}
	st, err := LoadStage(plan.Stage)
	if err != nil {
		return nil, err
	}
	return BuildOperators(plan, rs, st,
		OperatorsParams{Plan: planPath, Roster: rosterPath, HealMode: healMode})
}
