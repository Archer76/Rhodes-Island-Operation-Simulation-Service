package main

// enemy_mech.go：**机制前缀**那一族（丙阶段二·第三批）。
//
// 对应 Python `mech_fields()`（`enemy.py:276-422`）。七个前缀各管一件事，
// 每一个的正文来历都留在 `enemy.py` 的 docstring 里，这里只复刻读数口径。
//
// ## 三条最容易写错的
//
//  1. ★ **逐前缀判断，不是「有任意一个就全填」**（`_present`，`:425-428`）。
//     混着填会让没有某机制的敌人**凭空带上它的默认值**。
//  2. `phit_block_pollut` 与 `phit_pollut` 是**两个量**：前者是
//     「阻挡自身的单位（被阻挡时）」那一支，键名里带 `[to_block]`。
//  3. `aura_hit_radius` **永远等于常量 0.5**（`AURA_HIT_RADIUS`）——
//     它写在正文里、不在黑板上，AuraHit. 分支只改 `aura_hit_ratio`。
//
// ## 两处读数存疑的键，按原样带出、不擅自解释（`enemy.py:315-320`）
//
//   * `Passive_Hit.extra_value` = -0.001 —— 疑似移速的某种递减项，
//     **没有任何正文提到它**，故只登记不用。
//   * `PassiveM2.value` = 100 —— 与「如梭」的触发条件同值，据此当阈值带出。

import (
	"fmt"
	"strings"
)

// mechPrefixes 是登记粒度：按前缀登记，同一前缀下各键必然同生同死
// （`enemy.py:168-171`）。**每一项都在 gamedata 的怀黍离敌人上逐键核过**，
// 不是照 prts.wiki 的写法抄的——两侧拼法不一致。
var mechPrefixes = []string{
	"Passive.", "DeathPassive.", "AuraHit.", "SpeedUp.",
	"Passive_Hit.", "PassiveM2.", "CheckAwake.",
}

// AuraHit.Radius 是「进入阻流阀半径 0.5 内立刻造成真伤」的那个 0.5
// （`enemy.py:158`）。它**写在正文里、不在黑板上**，只能作为常量记着。
const auraHitRadius = 0.5

// Mechs 是机制前缀那一族字段。
type Mechs struct {
	PassivePollut       float64 `json:"passive_pollut"`
	PassiveRadius       float64 `json:"passive_radius"`
	PassiveAttachDamage float64 `json:"passive_attach_damage"`

	DeathToken string `json:"death_token"`
	DeathCnt   int    `json:"death_cnt"`

	AuraHitRatio  float64 `json:"aura_hit_ratio"`
	AuraHitRadius float64 `json:"aura_hit_radius"`

	SpeedupMove     float64 `json:"speedup_move"`
	SpeedupDuration float64 `json:"speedup_duration"`
	SpeedupCooldown float64 `json:"speedup_cooldown"`

	PhitCnt        int     `json:"phit_cnt"`
	PhitAtk        float64 `json:"phit_atk"`
	PhitDef        float64 `json:"phit_def"`
	PhitRes        float64 `json:"phit_res"`
	PhitMove       float64 `json:"phit_move"`
	PhitPollut     float64 `json:"phit_pollut"`
	PhitBlockPollut float64 `json:"phit_block_pollut"`
	PhitExtra      float64 `json:"phit_extra"`
	PhitMaxStack   int     `json:"phit_max_stack"`
	PhitWeightCnt  int     `json:"phit_weight_cnt"`

	Pm2Atk             float64 `json:"pm2_atk"`
	Pm2Def             float64 `json:"pm2_def"`
	Pm2Res             float64 `json:"pm2_res"`
	Pm2Move            float64 `json:"pm2_move"`
	Pm2CleanDef        float64 `json:"pm2_clean_def"`
	Pm2CleanRes        float64 `json:"pm2_clean_res"`
	Pm2CleanMove       float64 `json:"pm2_clean_move"`
	Pm2MarkPollut      float64 `json:"pm2_mark_pollut"`
	Pm2Invincible      float64 `json:"pm2_invincible"`
	Pm2PollutThreshold float64 `json:"pm2_pollut_threshold"`

	AwakeHPRatio    float64 `json:"awake_hp_ratio"`
	AwakeSummonRatio float64 `json:"awake_summon_ratio"`
	AwakeValue      float64 `json:"awake_value"`
	AwakeValueEff   float64 `json:"awake_value_eff"`
	AwakeEnemyKey   string  `json:"awake_enemy_key"`
	AwakeSummonCnt  int     `json:"awake_summon_cnt"`
}

// emptyMechs 是「缺失的键一律给 0/空串」的那一份默认值（`enemy.py:324-369`）。
// 上层不必再判——**不许给 nil**。
func emptyMechs() Mechs {
	return Mechs{AuraHitRadius: auraHitRadius}
}

// present 复刻 `_present`：黑板里**实际出现**的前缀集合。
func present(bb map[string]any) map[string]bool {
	out := map[string]bool{}
	for _, p := range mechPrefixes {
		for k := range bb {
			if strings.HasPrefix(k, p) {
				out[p] = true
				break
			}
		}
	}
	return out
}

// mechFields 复刻 `mech_fields`。
func mechFields(bb map[string]any) Mechs {
	out := emptyMechs()
	if len(bb) == 0 {
		return out
	}
	has := present(bb)
	if !has["Passive."] && !has["DeathPassive."] && !has["AuraHit."] &&
		!has["SpeedUp."] && !has["Passive_Hit."] && !has["PassiveM2."] &&
		!has["CheckAwake."] {
		return out
	}
	// -- Passive.：被击倒时对田地的病害污染 ＋ 附着效果每秒的预计算伤害
	if has["Passive."] {
		out.PassivePollut = bbFloat(bb, "Passive.extra_value")
		out.PassiveRadius = bbFloat(bb, "Passive.range_radius")
		out.PassiveAttachDamage = bbFloat(bb, "Passive.damage_value")
	}
	// -- DeathPassive.：被击倒时给予可部署装置
	if has["DeathPassive."] {
		if v, ok := bb["DeathPassive.token_key"].(string); ok {
			out.DeathToken = v
		}
		out.DeathCnt = bbInt(bb, "DeathPassive.cnt")
	}
	// -- AuraHit.：进入半径 0.5 内立刻造成的真伤比例（半径恒为常量）
	if has["AuraHit."] {
		out.AuraHitRatio = bbFloat(bb, "AuraHit.hp_ratio")
	}
	// -- SpeedUp.：受击且未被阻挡时的移速增益
	if has["SpeedUp."] {
		out.SpeedupMove = bbFloat(bb, "SpeedUp.move_speed")
		out.SpeedupDuration = bbFloat(bb, "SpeedUp.duration")
		out.SpeedupCooldown = bbFloat(bb, "SpeedUp.cooldown")
	}
	// -- Passive_Hit.：「祟」混沌形态的蜕皮
	if has["Passive_Hit."] {
		out.PhitCnt = bbInt(bb, "Passive_Hit.cnt")
		out.PhitAtk = bbFloat(bb, "Passive_Hit.atk")
		out.PhitDef = bbFloat(bb, "Passive_Hit.def")
		out.PhitRes = bbFloat(bb, "Passive_Hit.magic_resistance")
		out.PhitMove = bbFloat(bb, "Passive_Hit.move_speed")
		out.PhitPollut = bbFloat(bb, "Passive_Hit.value")
		//: ★「阻挡自身的单位（被阻挡时）」那一支另有自己的量
		out.PhitBlockPollut = bbFloat(bb,
			"Passive_Hit.enemy_dhnzzh_passive_m1[to_block].extra_value")
		out.PhitExtra = bbFloat(bb, "Passive_Hit.extra_value")
		out.PhitMaxStack = bbInt(bb, "Passive_Hit.max_stack_cnt")
		out.PhitWeightCnt = bbInt(bb, "Passive_Hit.other_cnt")
	}
	// -- PassiveM2.：「祟」明识形态
	if has["PassiveM2."] {
		out.Pm2Atk = bbFloat(bb, "PassiveM2.atk")
		out.Pm2Def = bbFloat(bb, "PassiveM2.def")
		out.Pm2Res = bbFloat(bb, "PassiveM2.magic_resistance")
		out.Pm2Move = bbFloat(bb, "PassiveM2.move_speed")
		out.Pm2CleanDef = bbFloat(bb, "PassiveM2.dhnzzh_clean_water.def")
		out.Pm2CleanRes = bbFloat(bb, "PassiveM2.dhnzzh_clean_water.magic_resistance")
		out.Pm2CleanMove = bbFloat(bb, "PassiveM2.dhnzzh_clean_water.move_speed")
		out.Pm2MarkPollut = bbFloat(bb, "PassiveM2.dhnzzh_passive_mark[host].value")
		out.Pm2Invincible = bbFloat(bb, "PassiveM2.duration_invic")
		out.Pm2PollutThreshold = bbFloat(bb, "PassiveM2.value")
	}
	// -- CheckAwake.：天桩-甲的监测 / 激活状态机
	if has["CheckAwake."] {
		out.AwakeHPRatio = bbFloat(bb, "CheckAwake.hp_ratio")
		out.AwakeSummonRatio = bbFloat(bb,
			"CheckAwake.enemy_dhdcr_trigger_summon.hp_ratio")
		out.AwakeValue = bbFloat(bb, "CheckAwake.value")
		out.AwakeValueEff = bbFloat(bb, "CheckAwake.value_eff")
		if v, ok := bb["CheckAwake.enemy_dhdcr_trigger_summon.enemy_key"].(string); ok {
			out.AwakeEnemyKey = v
		} else if v, ok := bb["CheckAwake.enemy_dhdcr_trigger_summon.enemy_key"]; ok && v != nil {
			//: 这一列在数据里是 `valueStr`（字符串）。若哪天它以数字形态出现，
			//: 按 Python 的 `str(... or "")` 同口径转一下，不要静默吞掉。
			//: ⚠ 数字→字符串的形态**未在此数据上核过**（现有数据里恒为字符串）。
			out.AwakeEnemyKey = fmt.Sprintf("%v", v)
		}
		out.AwakeSummonCnt = bbInt(bb,
			"CheckAwake.enemy_dhdcr_trigger_summon.cnt")
	}
	return out
}

// bbInt 复刻 `_bb_int`：先按 float 读，再截断成 int（不是四舍五入）。
func bbInt(bb map[string]any, key string) int {
	return int(bbFloat(bb, key))
}
