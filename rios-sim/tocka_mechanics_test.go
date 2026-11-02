package main

import (
	"context"
	"math"
	"testing"
)

// TestTockaSourceSpecCoverage 验证不同精英、潜能、技能等级下的数据驱动规格解析与黑板键消费
func TestTockaSourceSpecCoverage(t *testing.T) {
	// 1. 精英 0 1 级 潜能 1 技能 1 7级
	stE0 := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     0,
		Level:     1,
		Potential: 1,
	}
	specE0, err := buildTockaSourceSpec(stE0, 1, 7)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeTockaRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeTockaRuntimeConfig E0 failed: %v", err)
	}
	if cfgE0.T1Unlocked {
		t.Errorf("E0 should not unlock T1")
	}
	if cfgE0.T2Unlocked {
		t.Errorf("E0 should not unlock T2")
	}
	if cfgE0.S1MaxTarget != 2 {
		t.Errorf("S1 Lv7 S1MaxTarget expected 2, got %d", cfgE0.S1MaxTarget)
	}
	if math.Abs(cfgE0.S1ShieldAtkScale-1.9) > 1e-6 {
		t.Errorf("S1 Lv7 S1ShieldAtkScale expected 1.9, got %f", cfgE0.S1ShieldAtkScale)
	}
	if math.Abs(cfgE0.S1ShieldTime-10.0) > 1e-6 {
		t.Errorf("S1 S1ShieldTime expected 10.0, got %f", cfgE0.S1ShieldTime)
	}
	if math.Abs(cfgE0.S1Stun-3.0) > 1e-6 {
		t.Errorf("S1 S1Stun expected 3.0, got %f", cfgE0.S1Stun)
	}

	// 2. 精英 1 80 级 潜能 1 技能 2 7级
	stE1Pot1 := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     1,
		Level:     80,
		Potential: 1,
	}
	specE1Pot1, err := buildTockaSourceSpec(stE1Pot1, 2, 7)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec E1Pot1 failed: %v", err)
	}
	cfgE1Pot1, err := decodeTockaRuntimeConfig(specE1Pot1)
	if err != nil {
		t.Fatalf("decodeTockaRuntimeConfig E1Pot1 failed: %v", err)
	}
	if !cfgE1Pot1.T1Unlocked {
		t.Errorf("E1 should unlock T1")
	}
	if math.Abs(cfgE1Pot1.T1SP-1.0) > 1e-6 {
		t.Errorf("E1 Pot1 T1SP expected 1.0, got %f", cfgE1Pot1.T1SP)
	}
	if math.Abs(cfgE1Pot1.T1HealScale-0.4) > 1e-6 {
		t.Errorf("E1 Pot1 T1HealScale expected 0.4, got %f", cfgE1Pot1.T1HealScale)
	}
	if cfgE1Pot1.S2MaxTarget != 1 {
		t.Errorf("S2 S2MaxTarget expected 1, got %d", cfgE1Pot1.S2MaxTarget)
	}
	if math.Abs(cfgE1Pot1.S2AttackSpeed-35.0) > 1e-6 {
		t.Errorf("S2 Lv7 S2AttackSpeed expected 35.0, got %f", cfgE1Pot1.S2AttackSpeed)
	}
	if math.Abs(cfgE1Pot1.S2BuffDuration-15.0) > 1e-6 {
		t.Errorf("S2 S2BuffDuration expected 15.0, got %f", cfgE1Pot1.S2BuffDuration)
	}

	// 3. 精英 1 潜能 3：第一天赋治疗量增强 +20%
	stE1Pot3 := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     1,
		Level:     80,
		Potential: 3,
	}
	specE1Pot3, err := buildTockaSourceSpec(stE1Pot3, 2, 7)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec E1Pot3 failed: %v", err)
	}
	cfgE1Pot3, err := decodeTockaRuntimeConfig(specE1Pot3)
	if err != nil {
		t.Fatalf("decodeTockaRuntimeConfig E1Pot3 failed: %v", err)
	}
	if math.Abs(cfgE1Pot3.T1HealScale-0.6) > 1e-6 {
		t.Errorf("E1 Pot3 T1HealScale expected 0.6, got %f", cfgE1Pot3.T1HealScale)
	}

	// 4. 精英 2 90 级 潜能 1 技能 3 10级 (专精 3)
	stE2Pot1 := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}
	specE2Pot1, err := buildTockaSourceSpec(stE2Pot1, 3, 10)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec E2Pot1 failed: %v", err)
	}
	cfgE2Pot1, err := decodeTockaRuntimeConfig(specE2Pot1)
	if err != nil {
		t.Fatalf("decodeTockaRuntimeConfig E2Pot1 failed: %v", err)
	}
	if math.Abs(cfgE2Pot1.T1SP-2.0) > 1e-6 {
		t.Errorf("E2 Pot1 T1SP expected 2.0, got %f", cfgE2Pot1.T1SP)
	}
	if math.Abs(cfgE2Pot1.T1HealScale-0.8) > 1e-6 {
		t.Errorf("E2 Pot1 T1HealScale expected 0.8, got %f", cfgE2Pot1.T1HealScale)
	}
	if !cfgE2Pot1.T2Unlocked {
		t.Errorf("E2 should unlock T2")
	}
	if math.Abs(cfgE2Pot1.T2BuffDuration-6.0) > 1e-6 {
		t.Errorf("E2 Pot1 T2BuffDuration expected 6.0, got %f", cfgE2Pot1.T2BuffDuration)
	}
	if math.Abs(cfgE2Pot1.T2MagicAtkScale-0.8) > 1e-6 {
		t.Errorf("T2MagicAtkScale expected 0.8, got %f", cfgE2Pot1.T2MagicAtkScale)
	}
	if math.Abs(cfgE2Pot1.T2ProjectileRange-1.5) > 1e-6 {
		t.Errorf("T2ProjectileRange expected 1.5, got %f", cfgE2Pot1.T2ProjectileRange)
	}
	if math.Abs(cfgE2Pot1.T2Atk-(-0.2)) > 1e-6 {
		t.Errorf("T2Atk expected -0.2, got %f", cfgE2Pot1.T2Atk)
	}
	// S3 10级数值
	if math.Abs(cfgE2Pot1.S3AttackSpeed-80.0) > 1e-6 {
		t.Errorf("S3 M3 S3AttackSpeed expected 80.0, got %f", cfgE2Pot1.S3AttackSpeed)
	}
	if cfgE2Pot1.S3AttackMaxTarget != 4 {
		t.Errorf("S3 S3AttackMaxTarget expected 4, got %d", cfgE2Pot1.S3AttackMaxTarget)
	}
	if math.Abs(cfgE2Pot1.S3AttackAtkScale-2.2) > 1e-6 {
		t.Errorf("S3 M3 S3AttackAtkScale expected 2.2, got %f", cfgE2Pot1.S3AttackAtkScale)
	}
	if math.Abs(cfgE2Pot1.S3AttackStun-0.5) > 1e-6 {
		t.Errorf("S3 S3AttackStun expected 0.5, got %f", cfgE2Pot1.S3AttackStun)
	}
	if math.Abs(cfgE2Pot1.S3BonusInitAtk-1.2) > 1e-6 {
		t.Errorf("S3 M3 S3BonusInitAtk expected 1.2, got %f", cfgE2Pot1.S3BonusInitAtk)
	}
	if math.Abs(cfgE2Pot1.S3BonusDuration-15.0) > 1e-6 {
		t.Errorf("S3 S3BonusDuration expected 15.0, got %f", cfgE2Pot1.S3BonusDuration)
	}
	if math.Abs(cfgE2Pot1.S3BonusAtkDecPerSec-0.08) > 1e-6 {
		t.Errorf("S3 M3 S3BonusAtkDecPerSec expected 0.08, got %f", cfgE2Pot1.S3BonusAtkDecPerSec)
	}
	if math.Abs(cfgE2Pot1.S3BonusSP-1.0) > 1e-6 {
		t.Errorf("S3 S3BonusSP expected 1.0, got %f", cfgE2Pot1.S3BonusSP)
	}

	// 5. 精英 2 潜能 6：第一天赋治疗 100%，第二天赋持续 8.0s
	stE2Pot6 := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     2,
		Level:     90,
		Potential: 6,
	}
	specE2Pot6, err := buildTockaSourceSpec(stE2Pot6, 3, 10)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec E2Pot6 failed: %v", err)
	}
	cfgE2Pot6, err := decodeTockaRuntimeConfig(specE2Pot6)
	if err != nil {
		t.Fatalf("decodeTockaRuntimeConfig E2Pot6 failed: %v", err)
	}
	if math.Abs(cfgE2Pot6.T1HealScale-1.0) > 1e-6 {
		t.Errorf("E2 Pot6 T1HealScale expected 1.0, got %f", cfgE2Pot6.T1HealScale)
	}
	if math.Abs(cfgE2Pot6.T2BuffDuration-8.0) > 1e-6 {
		t.Errorf("E2 Pot6 T2BuffDuration expected 8.0, got %f", cfgE2Pot6.T2BuffDuration)
	}
}

// TestTockaTalent1NightSilence 验证第一天赋「夜的哑然」触发时自身回技力与攻击范围内友方治疗
func TestTockaTalent1NightSilence(t *testing.T) {
	cfg := &TockaRuntimeConfig{
		T1Unlocked:  true,
		T1SP:        2.0,
		T1HealScale: 0.8,
	}
	rt := newTockaRuntime(cfg)

	// 构造冻河
	tocka := &operator{
		spec: OperatorSpec{
			CharID: tockaCharID,
			Name:   "冻河",
			MaxHP:  1600,
			ATK:    800,
			Range:  [][2]int{{0, 0}, {1, 0}, {2, 0}},
			Skill:  &SkillSpec{SPCost: 20},
		},
		hp:           1600,
		cell:         [2]float64{0, 0},
		sp:           5.0,
		tockaRuntime: rt,
	}

	// 构造友方受伤干员（在范围内）
	injuredAlly := &operator{
		spec: OperatorSpec{
			CharID: "char_ally_1",
			Name:   "队友1",
			MaxHP:  2000,
		},
		hp:   1000, // 50% 血量
		cell: [2]float64{1, 0},
	}

	allOps := []*operator{tocka, injuredAlly}

	// 触发协同效果
	rt.OnTriggered(tocka, allOps)

	// 验证冻河技力增加 2.0 (5.0 -> 7.0)
	if math.Abs(tocka.sp-7.0) > 1e-6 {
		t.Errorf("Tocka SP expected 7.0, got %f", tocka.sp)
	}

	// 验证队友回复生命：800 * 0.8 = 640 (1000 -> 1640)
	if math.Abs(injuredAlly.hp-1640.0) > 1e-6 {
		t.Errorf("Injured ally HP expected 1640.0, got %f", injuredAlly.hp)
	}
	if math.Abs(rt.TotalHeal-640.0) > 1e-6 {
		t.Errorf("TotalHeal expected 640.0, got %f", rt.TotalHeal)
	}
}

// TestTockaTalent2SnowTraces 验证第二天赋「雪的印痕」范围伤害、虚弱减攻与法术 DoT
func TestTockaTalent2SnowTraces(t *testing.T) {
	cfg := &TockaRuntimeConfig{
		T2Unlocked:        true,
		T2BuffDuration:    6.0,
		T2MagicAtkScale:   0.8,
		T2ProjectileRange: 1.5,
		T2Atk:             -0.2,
	}
	rt := newTockaRuntime(cfg)

	tocka := &operator{
		spec: OperatorSpec{
			CharID: tockaCharID,
			Name:   "冻河",
			MaxHP:  1600,
			ATK:    1000,
		},
		hp:           1600,
		tockaRuntime: rt,
	}

	// 构造两个敌人：主目标在 (2, 0)，次目标在 (2.5, 0)（距离 0.5 <= 1.5 溅射范围）
	e1 := &enemy{
		index:    1,
		hp:       5000,
		position: [2]float64{2.0, 0.0},
		spec:     SpawnSpec{Name: "敌人1", ATK: 1000, RES: 20},
	}
	e2 := &enemy{
		index:    2,
		hp:       5000,
		position: [2]float64{2.5, 0.0},
		spec:     SpawnSpec{Name: "敌人2", ATK: 800, RES: 0},
	}
	enemies := []*enemy{e1, e2}

	// 冻河施加触发效果后激活强化普攻
	rt.EmpoweredAttackReady = true

	// 模拟命中：普攻溅射给范围内所有敌人施加虚弱
	for _, e := range enemies {
		dist := math.Hypot(e.position[0]-e1.position[0], e.position[1]-e1.position[1])
		if dist <= cfg.T2ProjectileRange {
			rt.ApplyT2Weaken(e)
		}
	}
	rt.EmpoweredAttackReady = false

	// 验证两名敌人都获得虚弱，攻击力减少 20%
	if math.Abs(rt.EnemyAtkModifier(e1.index)-(-0.2)) > 1e-6 {
		t.Errorf("e1 AtkModifier expected -0.2, got %f", rt.EnemyAtkModifier(e1.index))
	}
	if math.Abs(rt.EnemyAtkModifier(e2.index)-(-0.2)) > 1e-6 {
		t.Errorf("e2 AtkModifier expected -0.2, got %f", rt.EnemyAtkModifier(e2.index))
	}

	// 推进 1.0 秒，验证法术 DoT 跳字
	// e1: RES 20%, 伤害 = 1000 * 0.8 * (1 - 0.2) = 640
	// e2: RES 0%, 伤害 = 1000 * 0.8 * 1.0 = 800
	tockaSimTick([]*operator{tocka}, enemies, 1.0, 1.0, nil, nil)

	if math.Abs(e1.hp-(5000-640)) > 1e-6 {
		t.Errorf("e1 HP expected %f, got %f", 5000.0-640.0, e1.hp)
	}
	if math.Abs(e2.hp-(5000-800)) > 1e-6 {
		t.Errorf("e2 HP expected %f, got %f", 5000.0-800.0, e2.hp)
	}
}

// TestTockaSkill1DecayBarrierAndStun 验证技能一「一无所有之人」衰减屏障与攻击者击晕
func TestTockaSkill1DecayBarrierAndStun(t *testing.T) {
	cfg := &TockaRuntimeConfig{
		T1Unlocked:       true,
		T1SP:             2.0,
		T1HealScale:      0.8,
		S1ShieldAtkScale: 2.5,
		S1ShieldTime:     10.0,
		S1Stun:           3.0,
		S1MaxTarget:      3,
	}
	rt := newTockaRuntime(cfg)

	tocka := &operator{
		spec: OperatorSpec{
			CharID: tockaCharID,
			Name:   "冻河",
			MaxHP:  1600,
			ATK:    1000,
			Range:  [][2]int{{0, 0}, {1, 0}},
			Skill:  &SkillSpec{SPCost: 20},
		},
		hp:           1600,
		sp:           0,
		cell:         [2]float64{0, 0},
		tockaRuntime: rt,
	}

	ally := &operator{
		spec: OperatorSpec{
			CharID: "char_ally",
			Name:   "承伤前锋",
			MaxHP:  2000,
		},
		hp:   2000,
		cell: [2]float64{1, 0},
	}

	attacker := &enemy{
		index: 1,
		spec:  SpawnSpec{Name: "近战敌人", ATK: 500},
		hp:    2000,
	}

	// 施加 S1 标记
	rt.ApplyS1Trigger(ally)

	// 敌方攻击友方：触发 S1
	rt.HandleAllyDamaged(ally, attacker, tocka, []*operator{tocka, ally})

	// 1. 验证屏障初始值 = 1000 * 2.5 = 2500，衰减速率 = 2500 / 10 = 250/s
	st := rt.OpStates[ally]
	if st == nil {
		t.Fatalf("OpState for ally is nil")
	}
	if math.Abs(st.Barrier-2500.0) > 1e-6 {
		t.Errorf("Barrier expected 2500.0, got %f", st.Barrier)
	}
	if math.Abs(st.BarrierDecayRate-250.0) > 1e-6 {
		t.Errorf("BarrierDecayRate expected 250.0, got %f", st.BarrierDecayRate)
	}

	// 2. 验证攻击者被击晕 3.0 秒
	if math.Abs(attacker.stunTimer-3.0) > 1e-6 {
		t.Errorf("Attacker stunTimer expected 3.0, got %f", attacker.stunTimer)
	}

	// 3. 验证第一天赋联动回 SP：冻河技力 0 -> 2
	if math.Abs(tocka.sp-2.0) > 1e-6 {
		t.Errorf("Tocka SP expected 2.0, got %f", tocka.sp)
	}

	// 4. 验证屏障随时间推进衰减：推进 2.0 秒，屏障剩余 2500 - 250*2 = 2000
	tockaSimTick([]*operator{tocka, ally}, []*enemy{attacker}, 2.0, 2.0, nil, nil)
	if math.Abs(st.Barrier-2000.0) > 1e-6 {
		t.Errorf("Barrier after 2s expected 2000.0, got %f", st.Barrier)
	}

	// 5. 验证屏障吸收伤害：受到 800 伤害，屏障从 2000 降为 1200，干员血量不受损失
	remainingDmg := rt.AbsorbDamageWithBarrier(ally, 800.0)
	if remainingDmg != 0.0 {
		t.Errorf("remainingDmg expected 0, got %f", remainingDmg)
	}
	if math.Abs(st.Barrier-1200.0) > 1e-6 {
		t.Errorf("Barrier after absorb expected 1200.0, got %f", st.Barrier)
	}
}

// TestTockaSkill2GlobalAspdAndAutoSkill 验证技能二「意欲呼啸之心」全图协同、就绪攻速与自动开启
func TestTockaSkill2GlobalAspdAndAutoSkill(t *testing.T) {
	cfg := &TockaRuntimeConfig{
		T1Unlocked:     true,
		T1SP:           2.0,
		S2AttackSpeed:  50.0,
		S2BuffDuration: 15.0,
		S2MaxTarget:    1,
	}
	rt := newTockaRuntime(cfg)

	tocka := &operator{
		spec: OperatorSpec{
			CharID: tockaCharID,
			Name:   "冻河",
			MaxHP:  1600,
			ATK:    1000,
			Skill:  &SkillSpec{SPCost: 20},
		},
		hp:           1600,
		sp:           0,
		tockaRuntime: rt,
	}

	// 友方干员：技能需要 10 SP
	ally := &operator{
		spec: OperatorSpec{
			CharID: "char_caster",
			Name:   "术师",
			MaxHP:  1500,
			Skill:  &SkillSpec{SPCost: 10},
		},
		hp: 1500,
		sp: 8, // 尚未就绪
	}

	// 全图施加 S2 效果
	rt.ApplyS2Trigger(ally)

	// 未就绪时检查，不触发
	rt.HandleAllySkillReady(ally, tocka, []*operator{tocka, ally})
	st := rt.OpStates[ally]
	if st.S2AutoTrigger {
		t.Errorf("Should not trigger when SP not full")
	}

	// 友方技力增加至 10（满 SP）
	ally.sp = 10
	rt.HandleAllySkillReady(ally, tocka, []*operator{tocka, ally})

	// 验证触发：攻速 +50，自动开启标记激活，持续 15s
	if !st.S2AutoTrigger {
		t.Errorf("S2AutoTrigger expected true")
	}
	if math.Abs(st.S2AspdBonus-50.0) > 1e-6 {
		t.Errorf("S2AspdBonus expected 50.0, got %f", st.S2AspdBonus)
	}
	if math.Abs(st.S2AspdBuffTime-15.0) > 1e-6 {
		t.Errorf("S2AspdBuffTime expected 15.0, got %f", st.S2AspdBuffTime)
	}

	// 验证第一天赋联动回 SP：冻河技力 0 -> 2
	if math.Abs(tocka.sp-2.0) > 1e-6 {
		t.Errorf("Tocka SP expected 2.0, got %f", tocka.sp)
	}

	// 推进一帧 tick，验证友方技能被自动开启（skillActive = true，sp 清空）
	tockaSimTick([]*operator{tocka, ally}, nil, 0.1, 0.1, nil, nil)
	if !ally.skillActive {
		t.Errorf("ally.skillActive expected true via S2 auto trigger")
	}
	if ally.sp != 0 {
		t.Errorf("ally.sp expected 0 after activation, got %f", ally.sp)
	}
}

// TestTockaSkill3FullCombatCycleAndTransfer 验证技能三「踽踽独行之春」多目标击晕、衰减加成与协同传递转移
func TestTockaSkill3FullCombatCycleAndTransfer(t *testing.T) {
	cfg := &TockaRuntimeConfig{
		Slot:                3,
		T1Unlocked:          true,
		T1SP:                2.0,
		T2Unlocked:          true,
		T2BuffDuration:      6.0,
		S3AttackSpeed:       80.0,
		S3AttackMaxTarget:   4,
		S3AttackAtkScale:    2.2,
		S3AttackStun:        0.5,
		S3BonusInitAtk:      1.2,
		S3BonusDuration:     15.0,
		S3BonusAtkDecPerSec: 0.08,
		S3BonusSP:           1.0,
	}
	rt := newTockaRuntime(cfg)

	tocka := &operator{
		spec: OperatorSpec{
			CharID: tockaCharID,
			Name:   "冻河",
			MaxHP:  1600,
			ATK:    1000,
			Range:  [][2]int{{0, 0}, {1, 0}, {2, 0}},
			Skill:  &SkillSpec{SPCost: 20, Duration: 20.0},
		},
		hp:           1600,
		cell:         [2]float64{0, 0},
		sp:           0,
		skillActive:  true,
		tockaRuntime: rt,
	}

	// 友方队友 A (在范围内，持有 S3 标记)
	allyA := &operator{
		spec: OperatorSpec{
			CharID: "char_ally_a",
			Name:   "队友A",
			MaxHP:  2000,
			ATK:    1000,
			Skill:  &SkillSpec{SPCost: 30},
		},
		hp:   2000,
		cell: [2]float64{1, 0},
		sp:   10,
	}

	// 友方队友 B (在范围内，技力比例最高 20/30 = 66.7%)
	allyB := &operator{
		spec: OperatorSpec{
			CharID: "char_ally_b",
			Name:   "队友B",
			MaxHP:  2000,
			ATK:    1000,
			Skill:  &SkillSpec{SPCost: 30},
		},
		hp:   2000,
		cell: [2]float64{2, 0},
		sp:   20,
	}

	ops := []*operator{tocka, allyA, allyB}

	// 1. 开技能第一帧：向 allyA 施加 S3 标记，激活第二天赋强化普攻
	tockaSimTick(ops, nil, 0.1, 0.1, nil, nil)
	if rt.OpStates[allyA] == nil || rt.OpStates[allyA].TriggerKind != TockaTriggerS3 {
		t.Fatalf("allyA should hold S3 trigger effect")
	}
	if !rt.EmpoweredAttackReady {
		t.Errorf("EmpoweredAttackReady expected true after applying S3")
	}

	// 2. 推进 1.0 秒，验证 allyA 获得额外技力 (10 + 0.1 + 1.0 = 11.1)
	tockaSimTick(ops, nil, 1.0, 1.1, nil, nil)
	if math.Abs(allyA.sp-11.1) > 1e-6 {
		t.Errorf("allyA SP expected 11.1 from S3 bonus, got %f", allyA.sp)
	}

	// 3. allyA 开启技能：触发 S3
	rt.HandleAllySkillActivated(allyA, tocka, ops)

	// 验证加成：allyA 与冻河自身均获得 +120% 衰减攻击力加成
	stA := rt.OpStates[allyA]
	if math.Abs(stA.DecayAtkBuff-1.2) > 1e-6 {
		t.Errorf("allyA DecayAtkBuff expected 1.2, got %f", stA.DecayAtkBuff)
	}
	if math.Abs(rt.SelfDecayAtkBuff-1.2) > 1e-6 {
		t.Errorf("tocka SelfDecayAtkBuff expected 1.2, got %f", rt.SelfDecayAtkBuff)
	}

	// 4. 验证标记转移：由于 allyB 技力最高 (20/30)，标记转移给 allyB
	if rt.OpStates[allyB] == nil || rt.OpStates[allyB].TriggerKind != TockaTriggerS3 {
		t.Errorf("S3 trigger effect should transfer to allyB")
	}
	// allyA 自身的标记已清除
	if stA.TriggerKind != TockaTriggerNone {
		t.Errorf("allyA trigger effect should be consumed")
	}

	// 5. 验证第一天赋联动回 SP：冻河技力 0 -> 2
	if math.Abs(tocka.sp-2.0) > 1e-6 {
		t.Errorf("Tocka SP expected 2.0, got %f", tocka.sp)
	}

	// 6. 验证 S3 多目标与倍率
	if tocka.maxTarget() != 4 {
		t.Errorf("Tocka S3 maxTarget expected 4, got %d", tocka.maxTarget())
	}
	if math.Abs(tocka.atkScale()-2.2) > 1e-6 {
		t.Errorf("Tocka S3 atkScale expected 2.2, got %f", tocka.atkScale())
	}
}

// TestTockaFullBattleLifecycle 验证冻河在真实端到端战斗主循环中的全生命周期（部署、协同施加、受击屏障吸收、攻击者击晕、伤害结算）
func TestTockaFullBattleLifecycle(t *testing.T) {
	st := &OperatorStats{
		CharID:    tockaCharID,
		Elite:     2,
		Level:     90,
		Potential: 6,
	}
	specE2, err := buildTockaSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("buildTockaSourceSpec failed: %v", err)
	}

	tockaSpec := OperatorSpec{
		CharID:         tockaCharID,
		Name:           "冻河",
		Cell:           [2]int{0, 1},
		MaxHP:          1687,
		ATK:            801,
		DEF:            225,
		RES:            0,
		AttackInterval: 2.1,
		DamageType:     "PHYSICAL",
		TockaSource:    specE2,
		Range:          [][2]int{{0, 1}, {1, 1}, {2, 1}},
		Skill: &SkillSpec{
			SPCost:   12,
			InitSP:   8,
			Duration: -1.0,
		},
	}

	allySpec := OperatorSpec{
		CharID:         "char_defender",
		Name:           "防御前锋",
		Cell:           [2]int{1, 1},
		MaxHP:          2500,
		ATK:            500,
		DEF:            400,
		RES:            0,
		AttackInterval: 1.2,
		DamageType:     "PHYSICAL",
		Range:          [][2]int{{1, 1}},
	}

	spawns := []SpawnSpec{
		{
			EnemyID:    "hound_rusher",
			Name:       "突击源石虫",
			Time:       0.5,
			HP:         1200,
			ATK:        200,
			DEF:        50,
			MoveSpeed:  0.2,
			Weight:     1.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{2, 1}, {1, 1}, {0, 1}},
				},
			},
		},
	}

	simSpec := Spec{
		FPS:       30,
		MaxTime:   10.0,
		Life:      3,
		CostInit:  99,
		CostMax:   99,
		CostTime:  1.0,
		Operators: []OperatorSpec{tockaSpec, allySpec},
		Deploys: []DeploySpec{
			{
				CharID: tockaCharID,
				Index:  0,
				Time:   0.0,
			},
			{
				CharID: "char_defender",
				Index:  1,
				Time:   0.0,
			},
		},
		Spawns: spawns,
	}

	verdict, err := runSimContext(context.Background(), &simSpec)
	if err != nil {
		t.Fatalf("runSimContext failed: %v", err)
	}

	t.Logf("Tocka battle lifecycle finished: DamageDealt=%f, Kills=%d, Events=%d",
		verdict.DamageDealt, verdict.Kills, len(verdict.Events))

	if verdict.DamageDealt <= 0 {
		t.Fatalf("Expected damage dealt, got %f", verdict.DamageDealt)
	}
}
