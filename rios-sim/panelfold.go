package main

// panelfold.go：两套数值 profile 剩下的那五项读数（丙阶段四·第十一批）。
//
// ## 上一轮以为要搭 harness，这一轮发现不必
//
// `simgo/skills.py:_profile` 靠 `op.current_atk()` 一族读两套快照。
// `docs/go-selfsufficiency.md` 的缺口表原先写着：这五项「要驱动原版读数函数」，
// 得先搭一个能起 `sim` 的 harness。**读完 `frontend/operator_view.py:212-350`
// 才发现不必**——这五个方法只读实例属性（`self.effects` / `self.atk` /
// `self.stand_timer` 这一族），不碰引擎、不碰地图、不碰主循环。于是照上一轮
// 同一个办法：造一个只带这些属性的替身对象，把真实方法当纯函数调。
// oracle 依旧是原版实现，harness 省掉了。
//
// ## 一份状态进，一份读数出
//
// 五处读数是**同一帧的干员面板**，所以不写五个各带一长串入参的函数，而是
// `PanelState` 进、`PanelReadings` 出。状态里 `Effects` 是**指针**：
// nil 就是「这一帧没开技能」，与 Python 的 `e is None` 同义。这个三态不许用
// 零值顶替——零值 effects 会让 `atk × (1+0)` 恰好等于 base，缺口自己藏起来。
//
// ## 四处最容易写错的
//
//   - **攻击力那条括号是同层相加**：技能增益 ＋ 击杀叠层 ＋ 全场光环 ＋
//     翔虫机动 ＋ 替身形态，五个都进 `(1 + Σ)`，不是各自乘一遍
//     （三层的 +40% 是 +120%，不是 1.4³）；
//   - **翔虫机动与全场光环在 `effects is None` 的分支照样要加**——前者挂在
//     部署那一刻、后者是发给所有友方的，都不挑对方开不开技能；替身形态的
//     面板增益则要过 `stand_timer > 0` 这道门；
//   - **`max_target` 的替身快照排在 `e is None` 之前**：替身形态里 `effects`
//     已经是空的，不先判就会退回 1；
//   - **间隔那一层是复用**：`current_interval` 与上一轮的 `AttackInterval`
//     是同一个函数（`effects is None` 就是两个 buff 都为零的特例），
//     这里直接调它，不另抄一遍折算。

// PanelEffects 是这一帧技能效果的折平面：只留五处读数用得到的那些。
// 字段名对应 `SkillEffects` 的属性/黑板键，`buffs` 字典的三个键已摊平
// （`def` / `res` / `attack_interval` / `attack_speed`）。
type PanelEffects struct {
	BuffsAtk   float64 `json:"buffs_atk"`   // e.buffs["atk"]（**不含** atk_scale）
	BuffsDef   float64 `json:"buffs_def"`   // e.buffs["def"]
	BuffsRes   float64 `json:"buffs_res"`   // e.buffs["res"]
	BuffsIv    float64 `json:"buffs_iv"`    // e.buffs["attack_interval"]（加算秒）
	BuffsSpd   float64 `json:"buffs_spd"`   // e.buffs["attack_speed"]
	DamageMax  float64 `json:"damage_max"`  // e.damage["max_target"]（**未夹 1**）
	TargetStep int     `json:"target_step"` // e.target_step（每几次出手 +1）
	TargetCap  int     `json:"target_cap"`  // e.target_cap（最多几次，0=没上限）
	KillAtk    float64 `json:"kill_atk"`    // e.variants["kill"]["atk"]
	KillRes    float64 `json:"kill_res"`    // e.variants["kill"]["res"]
}

// PanelState 是折算一份快照需要的全部实时输入。
//
// ⚠ `TriggerHits` 按定义为**非负**（出手计数），所以下面用 Go 的截断除法
// 与 Python 的 floor 除法同值；负数是未定义域，不在这里补。
type PanelState struct {
	Atk            float64 `json:"atk"`             // self.atk（主循环施加后的面板）
	Defense        float64 `json:"defense"`         // self.defense
	Res            float64 `json:"res"`             // self.res
	AttackSpeed    float64 `json:"attack_speed"`    // self.attack_speed（常驻总攻速）
	AttackInterval float64 `json:"attack_interval"` // self.attack_interval（基础间隔）
	AttackType     string  `json:"attack_type"`     // self.attack_type

	AuraAtkPct     float64 `json:"aura_atk_pct"`     // 全场光环（青色怒火）
	AuraDefPct     float64 `json:"aura_def_pct"`     // 全场光环
	MobilityAtkPct float64 `json:"mobility_atk_pct"` // 翔虫机动（限时，挂在部署上）
	StandTimer     float64 `json:"stand_timer"`      // 替身形态剩余时间
	StandAtkPct    float64 `json:"stand_atk_pct"`    // 替身形态面板增益
	StandIvAdd     float64 `json:"stand_iv_add"`     // 替身形态间隔加算（秒）
	StandMaxTarget int     `json:"stand_max_target"` // 替身形态目标数快照

	KillStacks int `json:"kill_stacks"` // 击杀叠层数

	AspdWhenFree       float64 `json:"aspd_when_free"`       // 未阻挡时 +攻速
	Blocking           bool    `json:"blocking"`             // 此刻挡没挡住人
	AspdHighGround     float64 `json:"aspd_high_ground"`     // 周围四格有高台时 +攻速
	HighGroundNeighbor bool    `json:"high_ground_neighbor"` // 部署那刻判一次
	AspdStealBonus     float64 `json:"aspd_steal_bonus"`     // 偷来的
	AspdLoss           float64 `json:"aspd_loss"`            // 被偷走的

	SkillActive     bool   `json:"skill_active"`
	SkillAttackType string `json:"skill_attack_type"`
	TriggerHits     int    `json:"trigger_hits"` // 技能期内的出手次数

	Effects *PanelEffects `json:"effects"` // nil = 这一帧没开技能
}

// PanelReadings 是 `_profile` 要的那五项读数（外加攻速这个中间量）。
type PanelReadings struct {
	Atk         float64 `json:"atk"`
	Defense     float64 `json:"defense"`
	Res         float64 `json:"res"`
	AttackSpeed float64 `json:"attack_speed"`
	Interval    float64 `json:"interval"`
	MaxTarget   int     `json:"max_target"`
	AttackType  string  `json:"attack_type"`
}

// derivedMaxTarget 复刻 `SkillEffects.max_target`（`skill.py:1281-1284`）：
//
//	max(1, int(damage.get("max_target") or 1))
//
// ★ 这不是恒等，而是**两处收拢**：`or 1` 让 0 与「没给」都取 1，`int()` 又把
// (0,1) 区间截断到 0、再被 `max(1, …)` 提到 1。于是 0 / 0.5 / −3 全都落到 1。
// 直接把黑板原值当结果，「攻击目标数」那一族在**没写这条黑板**的技能上会算成
// 0 个目标——而 `max_target` 恰好是「有就改、没有就是 1」的形态，缺省极常见。
func derivedMaxTarget(raw float64) int {
	if raw <= 0 {
		return 1
	}
	if n := int(raw); n >= 1 {
		return n
	}
	return 1
}

// FoldPanel 复刻 `frontend/operator_view.py:212-350` 的五处读数。
func FoldPanel(s PanelState) PanelReadings {
	e := s.Effects

	//: 替身形态的面板增益**只在替身形态里**算——它是形态自己的攻击力改写，
	//: 不设这道门，本体也会吃到 +80%。
	standAtk := 0.0
	if s.StandTimer > 0.0 {
		standAtk = s.StandAtkPct
	}

	var atk float64
	if e == nil {
		//: 这一支**照样要算**全场光环与翔虫机动（早期版本直接 return self.atk）。
		atk = s.Atk * (1.0 + s.AuraAtkPct + s.MobilityAtkPct + standAtk)
	} else {
		killAtk := 0.0
		if s.KillStacks != 0 {
			killAtk = e.KillAtk * float64(s.KillStacks)
		}
		atk = s.Atk * (1.0 + e.BuffsAtk + killAtk + s.AuraAtkPct +
			s.MobilityAtkPct + standAtk)
	}

	var defense float64
	if e == nil {
		defense = s.Defense * (1.0 + s.AuraDefPct)
	} else {
		defense = s.Defense * (1.0 + e.BuffsDef + s.AuraDefPct)
	}

	var res float64
	if e == nil {
		res = s.Res
	} else {
		res = s.Res + e.BuffsRes
		//: 固定值相加，与百分比那条不同层。
		if s.KillStacks != 0 {
			res += e.KillRes * float64(s.KillStacks)
		}
	}

	//: 攻速是**实时**量：模组特性那几点只在没挡住人时才有，高台那一条是
	//: 部署那刻按地形定死的，偷取的两条要一进一出对得上。
	spd := s.AttackSpeed
	if s.AspdWhenFree != 0 && !s.Blocking {
		spd += s.AspdWhenFree
	}
	if s.AspdHighGround != 0 && s.HighGroundNeighbor {
		spd += s.AspdHighGround
	}
	spd += s.AspdStealBonus - s.AspdLoss

	//: 替身的「攻击间隔增大」是**加在基础间隔上**的，不是攻速修正——
	//: 两者在非线性处结果不同，而正文写的是前者。
	baseIv := s.AttackInterval
	if s.StandTimer > 0.0 {
		baseIv += s.StandIvAdd
	}
	var iv float64
	if e == nil {
		iv = AttackInterval(baseIv, spd, 0.0, 0.0)
	} else {
		iv = AttackInterval(baseIv, spd, e.BuffsIv, e.BuffsSpd)
	}

	mt := 1
	switch {
	case s.StandTimer > 0.0 && s.StandMaxTarget > 1:
		//: 替身形态的目标数是**快照**下来的，必须排在 `e == nil` 之前。
		mt = s.StandMaxTarget
	case e == nil:
		mt = 1
	case e.TargetStep <= 0:
		mt = derivedMaxTarget(e.DamageMax)
	default:
		earned := s.TriggerHits / e.TargetStep
		//: 「最多触发 M 次」是**格数**上限，0 或负数表示没写上限。
		if e.TargetCap > 0 && earned > e.TargetCap {
			earned = e.TargetCap
		}
		mt = derivedMaxTarget(e.DamageMax) + earned
	}

	var attackType string
	switch {
	case s.StandTimer > 0.0:
		//: 替身形态的普通攻击**都是法术**（三个形态的 prts 备注逐条写明）。
		attackType = "MAGIC"
	case s.SkillActive && s.SkillAttackType != "":
		attackType = s.SkillAttackType
	default:
		attackType = s.AttackType
	}

	return PanelReadings{
		Atk:         atk,
		Defense:     defense,
		Res:         res,
		AttackSpeed: spd,
		Interval:    iv,
		MaxTarget:   mt,
		AttackType:  attackType,
	}
}
