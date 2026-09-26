package main

// enemy_derive.go：由**天赋黑板/技能**派生的敌人字段（丙阶段二·第二批）。
//
// 对应 Python 的 `EnemyStats.derive_blackboard_fields()`（`enemy.py:656-679`）
// 与 `derive_skill_fields()`（`:681-689`）。出处行号写在注释里。
//
// ## 为什么单独一个文件
//
// 这些字段**不是**从 `enemyData.attributes` 读的，而是从那张平铺的黑板
// （`talent_blackboard`）推出来的；关卡 runes 会把黑板键乘系数，乘完**必须重算**
// （`rescale_talent_blackboard`，`:691-711`）——所以它是「黑板的一个纯函数」，
// 与属性层分开摆。
//
// ## 本轮**仍未**移植的
//
// `mech_fields()`（`enemy.py:276-424`）那一族——`Passive.` / `DeathPassive.` /
// `AuraHit.` / `SpeedUp.` / `Passive_Hit.` / `PassiveM2.` / `CheckAwake.`
// 七个前缀派生的 `aura_hit_*` / `passive_*` / `death_*` / `speedup_*` /
// `phit_*` / `awake_*`。对拍工具会继续把它们按名字列出来。

import (
	"math"
	"strings"
)

// P3R 相性的三个槽位 ↔ 黑板键后缀（`enemy.py:828`）。
var p3rSlots = [][2]string{
	{"physical", "PHYSICAL"}, {"magical", "MAGICAL"}, {"element", "ELEMENT"},
}

// AffinityOf 从黑板取一组伤害相性（`enemy.py:834-846`）。
//
// ★ **三个槽位缺一不可才算数**；缺了就返回空——否则会把「没有这项数据」
// 当成「相性为 0（弱点）」，让敌人凭空多出弱点。
func AffinityOf(bb map[string]any, prefix string) map[string]int {
	out := map[string]int{}
	for _, slot := range p3rSlots {
		v, ok := bb[prefix+"."+slot[1]]
		if !ok || v == nil {
			return map[string]int{}
		}
		f, ok := toFloat(v)
		if !ok {
			return map[string]int{}
		}
		out[slot[0]] = int(f)
	}
	return out
}

// rebornSpec 是 `_REBORN_SPECS` 的一项（`enemy.py:71-74`）。
//
// ⚠ 两套拼法在真实数据里并存，且**只收在 gamedata 里逐条核过的**：
// 写死成单个键会漏掉整整一类敌人（瘴 / 鄙瘴 / 「祟」用的是 `Reborning.`）。
type rebornSpec struct {
	prefix   string
	durKey   string
	ratioKey string //: 空串 = 没有比率键
}

var rebornSpecs = []rebornSpec{
	{"Reborn.", "Reborn.reborn_duration", "Reborn.max_hp_ratio"},
	{"Reborning.", "Reborning.duration", ""},
}

// RebornFields 是重生与充能那一组字段（`enemy.py:77-118`）。
//
// 取不到就是「不重生」，一律给默认值而不是 nil——上层不必再判。
type RebornFields struct {
	Count       int      `json:"reborn_count"`
	Duration    float64  `json:"reborn_duration"`
	HPRatio     float64  `json:"reborn_hp_ratio"`
	Prefix      string   `json:"reborn_prefix"`
	Interval    float64  `json:"reborn_interval"`
	Pollut      float64  `json:"reborn_pollut"`
	DefAdd      float64  `json:"reborn_def_add"`
	DamageMagic float64  `json:"reborn_damage_magic"`
	Summons     [][3]any `json:"reborn_summons"`
}

func emptyReborn() RebornFields {
	return RebornFields{HPRatio: 1.0, Summons: [][3]any{}}
}

// rebornFields 复刻 `reborn_fields`。
func rebornFields(bb map[string]any) RebornFields {
	for _, sp := range rebornSpecs {
		if _, ok := bb[sp.durKey]; !ok {
			continue
		}
		out := emptyReborn()
		//: 数据里没有明写重生次数，按「一次」建模（`enemy.py:92-95`）。
		out.Count = 1
		out.Duration = bbFloat(bb, sp.durKey)
		if sp.ratioKey != "" {
			if v, ok := toFloat(bb[sp.ratioKey]); ok {
				out.HPRatio = v
			}
		}
		out.Prefix = sp.prefix
		//: 充能四项挂在同一前缀下；**少任何一项就当没有充能机制**，
		//: 不做「缺一项按 0 算」——那会产出「每次扣 0 点病害值却照拿层数」。
		_, hasItv := bb[sp.prefix+"interval"]
		_, hasVal := bb[sp.prefix+"value"]
		if hasItv && hasVal {
			out.Interval = bbFloat(bb, sp.prefix+"interval")
			//: `value` 存的是 **-10**，取绝对值当正数用，方向由调用方决定。
			out.Pollut = math.Abs(bbFloat(bb, sp.prefix+"value"))
			out.DefAdd = bbFloat(bb, sp.prefix+"def_add")
			out.DamageMagic = bbFloat(bb, sp.prefix+"damage_magic")
		}
		//: 另一支：重生期间**按间隔召唤**。与充能那支互不相干——
		//: 「祟」两样都有 interval 但没有 `value`，若按「有 interval 就是充能」
		//: 去读，它会被算成充能怪，召唤整支消失。
		out.Summons = rebornSummons(bb, sp.prefix)
		return out
	}
	return emptyReborn()
}

// rebornSummons 复刻 `_reborn_summons`（`enemy.py:121-152`）。
//
// 主召唤写在 `{prefix}interval`/`{prefix}cnt`/`{prefix}enemy_key`；
// 第二路写在 `{prefix}dhnzzh_reborn_c2.*`。**没有 `enemy_key` 就没有召唤**。
func rebornSummons(bb map[string]any, prefix string) [][3]any {
	out := [][3]any{}
	for _, pre := range []string{prefix, prefix + "dhnzzh_reborn_c2."} {
		key, ok := bb[pre+"enemy_key"].(string)
		if !ok || strings.TrimSpace(key) == "" {
			continue
		}
		itv, ok := toFloat(bb[pre+"interval"])
		if !ok || itv <= 0 {
			continue
		}
		cntF, ok := toFloat(bb[pre+"cnt"])
		if !ok {
			continue
		}
		cnt := int(cntF)
		if cnt <= 0 {
			continue
		}
		out = append(out, [3]any{itv, cnt, strings.TrimSpace(key)})
	}
	return out
}

// proseSkillAttack 是 `PROSE_SKILL_ATTACK`（`enemy.py:193-201`）。
//
// 技能黑板只给得出两个数，而「打几个、打谁、怎么分摊」全在正文里。
// 项目纪律是**不编数**：正文写了就按正文写死，并让自检去核那段正文。
type proseSkillAttack struct {
	ScalePhys  float64
	Targets    int
	Cross      int
	GroundOnly bool
	NoNormal   bool
}

var proseSkillAttacks = map[string]proseSkillAttack{
	"Drink": {
		ScalePhys:  1.0,  // 「攻击力100%的物理伤害」
		Targets:    1,    // 「攻击场上1名…我方单位」
		Cross:      1,    // 「目标及其周围4格」= 十字（曼哈顿距离 1）
		GroundOnly: true, // 「部署于地面的我方单位」
		NoNormal:   true, // 天赋「不进行远程普通攻击」
	},
}

// SkillAttackFields 是「技能攻击」那一组（`enemy.py:208-273`）。
type SkillAttackFields struct {
	Key        string  `json:"skill_atk_key"`
	ScalePhys  float64 `json:"skill_atk_scale_phys"`
	ScaleMagic float64 `json:"skill_atk_scale_magic"`
	Pollut     float64 `json:"skill_atk_pollut"`
	Targets    int     `json:"skill_atk_targets"`
	Cross      int     `json:"skill_atk_cross"`
	GroundOnly bool    `json:"skill_atk_ground_only"`
	NoNormal   bool    `json:"skill_atk_no_normal"`
	Interval   float64 `json:"skill_atk_interval"`
	Init       float64 `json:"skill_atk_init"`
}

// skillAttackFields 复刻 `skill_attack_fields`。
func skillAttackFields(skills []any) (SkillAttackFields, bool) {
	for _, skAny := range skills {
		sk, ok := skAny.(map[string]any)
		if !ok {
			continue
		}
		key, _ := sk["prefabKey"].(string)
		spec, ok := proseSkillAttacks[key]
		if !ok {
			continue
		}
		//: ⚠ 带 `valueStr` 的键是**字符串参数**，不当数字用（`enemy.py:243-253`）。
		num := func(k string) float64 {
			for _, bAny := range asAnySlice(sk["blackboard"]) {
				b, ok := bAny.(map[string]any)
				if !ok {
					continue
				}
				bk, _ := b["key"].(string)
				if bk != k {
					continue
				}
				if vs, ok := b["valueStr"].(string); ok && vs != "" {
					return 0
				}
				if f, ok := toFloat(b["value"]); ok {
					return f
				}
				return 0
			}
			return 0
		}
		out := SkillAttackFields{
			Key: key, ScalePhys: spec.ScalePhys,
			ScaleMagic: num("atk_scale_magic"), Pollut: num("value"),
			Targets: spec.Targets, Cross: spec.Cross,
			GroundOnly: spec.GroundOnly, NoNormal: spec.NoNormal,
		}
		if f, ok := toFloat(sk["baseAttackTime"]); ok {
			out.Interval = f
		}
		if f, ok := toFloat(sk["initCooldown"]); ok {
			out.Init = f
		}
		return out, true
	}
	return SkillAttackFields{}, false
}

// DeriveBlackboardFields 把上面这些一次性算好写进 stats。
//
// 对应 `enemy.py:656-689`：先相性/屏障/击杀费用，再重生那一支，
// 最后是技能那一支（`derive_skill_fields`）。**它的输出是纯函数**——
// 只依赖 `TalentBlackboard` 与 `Skills`，所以关卡 runes 改了黑板之后
// 这里必须能被再调一次。
func (s *EnemyStats) DeriveBlackboardFields() {
	bb := s.TalentBlackboard
	s.P3R = AffinityOf(bb, "TotalAttack")
	if v, ok := toFloat(bb["TotalAttack.weak_max"]); ok {
		s.WeakMax = v
	} else {
		s.WeakMax = 0
	}
	if v, ok := toFloat(bb["TotalAttack.fall_duration"]); ok {
		s.FallDuration = v
	} else {
		s.FallDuration = 0
	}
	modes := map[string]map[string]int{}
	for _, m := range []string{"Mode_A", "Mode_B"} {
		if a := AffinityOf(bb, m); len(a) > 0 {
			modes[m] = a
		}
	}
	s.Modes = modes
	if v, ok := toFloat(bb["Shield.shield_hp_ratio"]); ok {
		s.ShieldHPRatio = v
	} else {
		s.ShieldHPRatio = 0
	}
	if v, ok := toFloat(bb["Talent1.cost"]); ok {
		s.KillCost = int(v)
	} else {
		s.KillCost = 0
	}
	rb := rebornFields(bb)
	s.RebornCount = rb.Count
	s.RebornDuration = rb.Duration
	s.RebornHPRatio = rb.HPRatio
	s.RebornPrefix = rb.Prefix
	s.RebornInterval = rb.Interval
	s.RebornPollut = rb.Pollut
	s.RebornDefAdd = rb.DefAdd
	s.RebornDamageMagic = rb.DamageMagic
	s.RebornSummons = rb.Summons
	//: 机制前缀那一族（`mech_fields`，七个前缀）。★ 它**逐前缀判断**，
	//: 不是「有任意一个就全填」——混着填会让没有某机制的敌人凭空带上默认值。
	s.Mechs = mechFields(bb)
	if sa, ok := skillAttackFields(s.Skills); ok {
		s.SkillAtkKey = sa.Key
		s.SkillAtkScalePhys = sa.ScalePhys
		s.SkillAtkScaleMagic = sa.ScaleMagic
		s.SkillAtkPollut = sa.Pollut
		s.SkillAtkTargets = sa.Targets
		s.SkillAtkCross = sa.Cross
		s.SkillAtkGroundOnly = sa.GroundOnly
		s.SkillAtkNoNormal = sa.NoNormal
		s.SkillAtkInterval = sa.Interval
		s.SkillAtkInit = sa.Init
	} else {
		//: 没有这条技能就全清零——注意 `Cross` 的「没有这条」也是 0，
		//: 与 Python 侧 dataclass 默认值一致（不是 -1）。
		s.SkillAtkKey = ""
		s.SkillAtkScalePhys = 0
		s.SkillAtkScaleMagic = 0
		s.SkillAtkPollut = 0
		s.SkillAtkTargets = 0
		s.SkillAtkCross = 0
		s.SkillAtkGroundOnly = false
		s.SkillAtkNoNormal = false
		s.SkillAtkInterval = 0
		s.SkillAtkInit = 0
	}
}

// ---------------------------------------------------------------- 小工具

func bbFloat(bb map[string]any, key string) float64 {
	if v, ok := toFloat(bb[key]); ok {
		return v
	}
	return 0
}

// toFloat 复刻 `float(v)` 的宽松度：数字直接收，字符串尽力解析，其余算取不到。
func toFloat(v any) (float64, bool) {
	switch t := v.(type) {
	case float64:
		return t, true
	case float32:
		return float64(t), true
	case int:
		return float64(t), true
	case int64:
		return float64(t), true
	case bool:
		return 0, true
	default:
		return 0, false
	}
}

func asAnySlice(v any) []any {
	if a, ok := v.([]any); ok {
		return a
	}
	return nil
}
