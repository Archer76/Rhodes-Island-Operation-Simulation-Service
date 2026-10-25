package main

import (
	"fmt"
)

// ulpia_runtime.go：乌尔比安（char_4145_ulpia）在主战斗循环里的状态与机制内核。
//
// 分工：
//   - `ulpia_spec.go`   只存 gamedata 原文（证据链）；
//   - `ulpia_config.go` 把原文解析成强类型字段（黑板书）；
//   - **本文件**是运行期：
//       1. 天赋一「本性的坚守」受击生命回复（受 hp_ratio 与技能二 talent_scale、模组X heal_scale 影响）；
//       2. 天赋二「血脉的哺养」击杀叠加生命上限与攻击力（模组Y 满层阻挡数+1）；
//       3. 技能二「必须维系的界限」常态攻击力/生命上限提升、阻挡数+1、天赋一治疗翻倍；
//       4. 模组特性：模组X 受治疗+20%（heal_scale=1.2），模组Y 攻击被阻挡敌人伤害+10%（damage_scale=1.1）；
//   - `ulpia_sim_tick.go` 是帧内驱动（`ulpiaTick`）。
//
// ⚠ 零近似原则：
//   - 技能一位移 force 具名 Gap 拒判；
//   - 技能三船锚位移与落点转移具名 Gap 拒判；
//   - 天赋二跨干员深海猎人光环增益（ulpia_t_1[abyssal].*）具名 Gap 登记。

// UlpiaBattleState 是一名场上乌尔比安的可变状态。
type UlpiaBattleState struct {
	Config *UlpiaRuntimeConfig

	// ---- 天赋二「血脉的哺养」击倒敌人叠加层数 ----
	KillStack int // 当前击杀层数，上限 Config.Talent2MaxStackCnt (9 或 10)

	// ---- 运行期事件计数（判决与单测取证用） ----
	T1HealTriggers int     // 天赋一受击自疗触发次数
	T1HealAmount   float64 // 天赋一累计回复生命值
	T2StackGains   int     // 天赋二层数提升次数
	S2Activated    bool    // 技能二是否已开启过
}

func newUlpiaBattleState(cfg *UlpiaRuntimeConfig) *UlpiaBattleState {
	return &UlpiaBattleState{Config: cfg}
}

// ulpiaTalent1OnHit 在乌尔比安受到伤害（dealt > 0）时触发自疗。
//
// 原文：「每次受到伤害时，治疗自身 value1 点生命值；生命值低于 hp_ratio 时，治疗效果提升至 value2 点生命值」。
//
// 加成影响：
// 1. 技能二开启时，效果提升至 talent_scale (2.0) 倍；
// 2. 模组X「乌尔比安的新晨」特性：受到的治疗效果提升至 heal_scale (1.2) 倍。
func ulpiaTalent1OnHit(op *operator, dealt float64, t float64, verdict *Verdict) {
	if op == nil || dealt <= 0 || op.ulpiaState == nil || !op.alive() {
		return
	}
	cfg := op.ulpiaState.Config
	if !cfg.Talent1Enabled {
		return
	}

	// 基础回复值判定：当前生命值百分比是否低于阈值 hp_ratio
	// ⚠ 此时已经在 hurt 之后，op.hp 是扣减后的当前生命值
	maxHp := op.maxHP()
	var baseHeal float64
	if maxHp > 0 && (op.hp/maxHp) < cfg.Talent1HPRatio {
		baseHeal = cfg.Talent1Value2
	} else {
		baseHeal = cfg.Talent1Value1
	}

	// 技能二倍率
	if op.skillActive && cfg.Slot == 2 && cfg.S2TalentScale > 0 {
		baseHeal *= cfg.S2TalentScale
	}

	// 模组特性：受治疗效果提升 (heal_scale)
	if cfg.ModTraitHealScale > 0 {
		baseHeal *= cfg.ModTraitHealScale
	}

	got := op.heal(baseHeal)
	op.ulpiaState.T1HealTriggers++
	op.ulpiaState.T1HealAmount += got

	if verdict != nil {
		verdict.Events = append(verdict.Events, Event{
			T:    t,
			Kind: "ulpia_talent1_heal",
			Who:  op.spec.Name,
		})
	}
}

// ulpiaTalent2OnKill 在乌尔比安击倒敌人时调用，叠加自身生命上限与攻击力层数。
//
// 原文：「每次击倒一名敌人时，自身的生命上限提高 max_hp，攻击力提高 atk，最多叠加 max_stack_cnt 次」。
//
// 模组Y 加成：叠加 9 层后阻挡数 +1 (block_cnt=1, add_block_cnt_stack_cnt=9)。
func ulpiaTalent2OnKill(op *operator, victim *enemy, t float64, verdict *Verdict) {
	if op == nil || op.ulpiaState == nil || !op.alive() {
		return
	}
	cfg := op.ulpiaState.Config
	if !cfg.Talent2Enabled {
		return
	}

	st := op.ulpiaState
	if st.KillStack >= cfg.Talent2MaxStackCnt {
		return
	}

	st.KillStack++
	st.T2StackGains++

	if verdict != nil {
		verdict.Events = append(verdict.Events, Event{
			T:    t,
			Kind: "ulpia_talent2_stack",
			Who:  fmt.Sprintf("%s (stack=%d)", op.spec.Name, st.KillStack),
		})
	}
}

// ulpiaTalent2Bonus 返回天赋二当前层数赋予乌尔比安自身的生命上限与攻击力绝对加值。
func (st *UlpiaBattleState) ulpiaTalent2Bonus() (hpBonus float64, atkBonus float64) {
	if st == nil || !st.Config.Talent2Enabled || st.KillStack <= 0 {
		return 0, 0
	}
	hpBonus = float64(st.KillStack) * st.Config.Talent2MaxHPPerStack
	atkBonus = float64(st.KillStack) * st.Config.Talent2AtkPerStack
	return hpBonus, atkBonus
}

// ulpiaBlockCntBonus 返回乌尔比安当前的阻挡数加成（技能二 + 模组Y 满层）。
func (o *operator) ulpiaBlockCntBonus() int {
	if o == nil || o.ulpiaState == nil {
		return 0
	}
	bonus := 0
	cfg := o.ulpiaState.Config
	// 技能二「必须维系的界限」阻挡数 +1
	if o.skillActive && cfg.Slot == 2 {
		bonus += cfg.S2BlockCnt
	}
	// 模组Y 天赋二改写：达到 add_block_cnt_stack_cnt 层后阻挡数 +1
	if cfg.Talent2ModAddBlockCnt > 0 && cfg.Talent2ModAddBlockStack > 0 &&
		o.ulpiaState.KillStack >= cfg.Talent2ModAddBlockStack {
		bonus += cfg.Talent2ModAddBlockCnt
	}
	return bonus
}

// ulpiaDamageScale 返回模组Y的特性加成：对被自身阻挡的敌人伤害提升 10% (damage_scale=1.1)。
func (o *operator) ulpiaDamageScale(target *enemy) float64 {
	if o == nil || o.ulpiaState == nil || target == nil {
		return 1.0
	}
	cfg := o.ulpiaState.Config
	if cfg.ModTraitDamageScale <= 0 {
		return 1.0
	}
	// 检查 target 是否被当前干员阻挡
	for _, b := range o.blocking {
		if b == target {
			return cfg.ModTraitDamageScale
		}
	}
	return 1.0
}
