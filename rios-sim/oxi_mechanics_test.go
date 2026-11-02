package main

import (
	"context"
	"math"
	"testing"
)

// TestOxiSourceSpecCoverage 验证不同精英、潜能、技能等级组合下的数据驱动规格解析
func TestOxiSourceSpecCoverage(t *testing.T) {
	stBase := &OperatorStats{
		CharID:    oxiCharID,
		Elite:     0,
		Level:     50,
		Potential: 1,
	}
	specE0, err := buildOxiSourceSpec(stBase, 1, 7)
	if err != nil {
		t.Fatalf("buildOxiSourceSpec E0 failed: %v", err)
	}
	cfgE0, err := decodeOxiRuntimeConfig(specE0)
	if err != nil {
		t.Fatalf("decodeOxiRuntimeConfig E0 failed: %v", err)
	}
	if math.Abs(cfgE0.T1EpDamageRatio-0.03) > 1e-6 {
		t.Errorf("E0 Pot1 T1EpDamageRatio expected 0.03, got %f", cfgE0.T1EpDamageRatio)
	}
	if cfgE0.T2Unlocked {
		t.Errorf("E0 should not unlock T2")
	}

	// 精英 1 潜能 5 技能 2 等级 7
	stE1 := &OperatorStats{
		CharID:    oxiCharID,
		Elite:     1,
		Level:     80,
		Potential: 5,
	}
	specE1, err := buildOxiSourceSpec(stE1, 2, 7)
	if err != nil {
		t.Fatalf("buildOxiSourceSpec E1 failed: %v", err)
	}
	cfgE1, err := decodeOxiRuntimeConfig(specE1)
	if err != nil {
		t.Fatalf("decodeOxiRuntimeConfig E1 failed: %v", err)
	}
	if math.Abs(cfgE1.T1ArcaneStep-0.02) > 1e-6 {
		t.Errorf("E1 Pot5 T1ArcaneStep expected 0.02, got %f", cfgE1.T1ArcaneStep)
	}
	if math.Abs(cfgE1.T1ArcaneMax-0.12) > 1e-6 {
		t.Errorf("E1 Pot5 T1ArcaneMax expected 0.12, got %f", cfgE1.T1ArcaneMax)
	}
	if math.Abs(cfgE1.T1EpDamageRatio-0.08) > 1e-6 {
		t.Errorf("E1 Pot5 T1EpDamageRatio expected 0.08, got %f", cfgE1.T1EpDamageRatio)
	}
	if math.Abs(cfgE1.S2RetaliateAtkScale-2.3) > 1e-6 {
		t.Errorf("S2 L7 RetaliateAtkScale expected 2.3, got %f", cfgE1.S2RetaliateAtkScale)
	}

	// 精英 2 满潜能 技能 3 专精 3
	stE2Max := &OperatorStats{
		CharID:    oxiCharID,
		Elite:     2,
		Level:     90,
		Potential: 6,
	}
	specE2Max, err := buildOxiSourceSpec(stE2Max, 3, 10)
	if err != nil {
		t.Fatalf("buildOxiSourceSpec E2Max failed: %v", err)
	}
	cfgE2Max, err := decodeOxiRuntimeConfig(specE2Max)
	if err != nil {
		t.Fatalf("decodeOxiRuntimeConfig E2Max failed: %v", err)
	}
	if !cfgE2Max.T2Unlocked {
		t.Errorf("E2 should unlock T2")
	}
	if math.Abs(cfgE2Max.T1ArcaneStep-0.03) > 1e-6 {
		t.Errorf("E2 Pot6 T1ArcaneStep expected 0.03, got %f", cfgE2Max.T1ArcaneStep)
	}
	if math.Abs(cfgE2Max.T1ArcaneMax-0.18) > 1e-6 {
		t.Errorf("E2 Pot6 T1ArcaneMax expected 0.18, got %f", cfgE2Max.T1ArcaneMax)
	}
	if math.Abs(cfgE2Max.T1EpDamageRatio-0.13) > 1e-6 {
		t.Errorf("E2 Pot6 T1EpDamageRatio expected 0.13, got %f", cfgE2Max.T1EpDamageRatio)
	}
	if math.Abs(cfgE2Max.T2FieldDuration-4.0) > 1e-6 {
		t.Errorf("E2 Pot6 T2FieldDuration expected 4.0, got %f", cfgE2Max.T2FieldDuration)
	}
	if math.Abs(cfgE2Max.T2FieldAtkScale-0.15) > 1e-6 {
		t.Errorf("E2 Pot6 T2FieldAtkScale expected 0.15, got %f", cfgE2Max.T2FieldAtkScale)
	}
	if math.Abs(cfgE2Max.S3Atk-1.4) > 1e-6 {
		t.Errorf("S3 L10 S3Atk expected 1.4, got %f", cfgE2Max.S3Atk)
	}
	if math.Abs(cfgE2Max.S3HeatwaveAtkScale-2.5) > 1e-6 {
		t.Errorf("S3 L10 S3HeatwaveAtkScale expected 2.5, got %f", cfgE2Max.S3HeatwaveAtkScale)
	}
	if math.Abs(cfgE2Max.S3NormalHalfWidth-2.0) > 1e-6 {
		t.Errorf("S3 NormalHalfWidth expected 2.0, got %f", cfgE2Max.S3NormalHalfWidth)
	}
	if math.Abs(cfgE2Max.S3OverloadHalfWidth-6.0) > 1e-6 {
		t.Errorf("S3 OverloadHalfWidth expected 6.0, got %f", cfgE2Max.S3OverloadHalfWidth)
	}
}

// TestOxiT1ArcaneStackingAndDecay 验证第一天赋未攻击时随时间延迟积蓄增伤层数，出手攻击后衰减 1 层并重置未攻击计时
func TestOxiT1ArcaneStackingAndDecay(t *testing.T) {
	cfg := &OxiRuntimeConfig{
		T1ArcaneIdleDelay:    3.0,
		T1ArcaneStepInterval: 0.5,
		T1ArcaneStep:         0.03,
		T1ArcaneMax:          0.18,
	}
	rt := newOxiRuntime(cfg)

	// 前 2.5s 未达到 delay，不增伤
	rt.TickT1(2.5)
	if rt.ArcaneStacks != 0 {
		t.Fatalf("expected 0 stacks at 2.5s, got %d", rt.ArcaneStacks)
	}
	if math.Abs(rt.GetArcaneDamageMultiplier()-1.0) > 1e-6 {
		t.Fatalf("expected multiplier 1.0, got %f", rt.GetArcaneDamageMultiplier())
	}

	// 达到 3.0s + 0.5s = 3.5s，积蓄 2 步 (3.0s 算第 1 步，3.5s 算第 2 步)
	rt.TickT1(1.0) // 此时总未攻击时间 3.5s
	if rt.ArcaneStacks != 2 {
		t.Fatalf("expected 2 stacks at 3.5s, got %d", rt.ArcaneStacks)
	}
	expectedMul := 1.0 + 2*0.03
	if math.Abs(rt.GetArcaneDamageMultiplier()-expectedMul) > 1e-6 {
		t.Fatalf("expected multiplier %f, got %f", expectedMul, rt.GetArcaneDamageMultiplier())
	}

	// 持续未攻击直至达到上限 (max 0.18 / 0.03 = 6 步)
	rt.TickT1(10.0)
	if rt.ArcaneStacks != 6 {
		t.Fatalf("expected capped at 6 stacks, got %d", rt.ArcaneStacks)
	}
	if math.Abs(rt.GetArcaneDamageMultiplier()-1.18) > 1e-6 {
		t.Fatalf("expected multiplier 1.18, got %f", rt.GetArcaneDamageMultiplier())
	}

	// 攻击一次，衰减 1 层至 5 层，未攻击时间归零
	rt.OnAttack(nil, 13.5)
	if rt.ArcaneStacks != 5 {
		t.Fatalf("expected 5 stacks after attack, got %d", rt.ArcaneStacks)
	}
	if rt.IdleTimer != 0 {
		t.Fatalf("expected IdleTimer 0 after attack, got %f", rt.IdleTimer)
	}
}

// TestOxiT1EpDamageBurning 验证造成法术伤害时附带灼燃损伤并触发爆条
func TestOxiT1EpDamageBurning(t *testing.T) {
	cfg := &OxiRuntimeConfig{
		T1EpDamageRatio: 0.13,
		T2Unlocked:      true,
	}
	rt := newOxiRuntime(cfg)
	foe := &enemy{
		hp:      10000,
		element: newElementState(1000.0),
		index:   1,
	}

	dealtDamage := 5000.0
	epDmg := dealtDamage * rt.Config.T1EpDamageRatio // 650
	burst := foe.element.damage(elemFire, epDmg)
	if burst {
		t.Fatalf("first hit should not burst (ep remaining 350)")
	}
	if math.Abs(foe.element.ep[elemFire]-350.0) > 1e-6 {
		t.Fatalf("expected ep 350, got %f", foe.element.ep[elemFire])
	}

	// 第二击 5000 法伤，附带 650 损伤，触发爆条
	burst2 := foe.element.damage(elemFire, epDmg)
	if !burst2 {
		t.Fatalf("second hit should trigger burst")
	}
	rt.RecordEnemyBurningBurst(foe.index, 10.0)
	if rt.BurstEnemyWindow[foe.index] != 15.0 {
		t.Fatalf("expected burst window to 15.0, got %f", rt.BurstEnemyWindow[foe.index])
	}
}

// TestOxiT2FlameFieldFootprint 验证第二天赋敌人灼燃爆发后 5s 留下足迹烈焰地块及周期伤害
func TestOxiT2FlameFieldFootprint(t *testing.T) {
	cfg := &OxiRuntimeConfig{
		T2Unlocked:      true,
		T2FieldDuration: 4.0,
		T2FieldInterval: 0.3,
		T2FieldAtkScale: 0.15,
		T2MaxCount:      25,
	}
	rt := newOxiRuntime(cfg)
	op := &operator{
		spec: OperatorSpec{
			Name: "塔露拉",
			ATK:  1000,
		},
		hp: 2000,
	}
	foe := &enemy{
		hp:       1000,
		position: [2]float64{2.0, 3.0},
		index:    1,
		spec:     SpawnSpec{Name: "小怪", RES: 10.0},
	}

	// 登记敌人爆条窗口至 15.0
	rt.RecordEnemyBurningBurst(foe.index, 10.0)

	// 敌人移动在 (2, 3) 留下足迹
	rt.TryAddFlameField([2]int{2, 3}, 10.0)
	if len(rt.FlameCells) != 1 {
		t.Fatalf("expected 1 flame cell, got %d", len(rt.FlameCells))
	}
	if rt.FlameCells[0].ExpiresAt != 14.0 {
		t.Fatalf("expected flame cell expires at 14.0, got %f", rt.FlameCells[0].ExpiresAt)
	}

	verdict := &Verdict{}
	// 前进 0.35s，触发一次跳伤
	rt.TickFlameFields(10.35, 0.35, op, []*enemy{foe}, verdict)
	if rt.TotalFlameFieldHits != 1 {
		t.Fatalf("expected 1 flame field hit, got %d", rt.TotalFlameFieldHits)
	}
	if foe.hp >= 1000 {
		t.Fatalf("expected foe hp reduced, got %f", foe.hp)
	}

	// 超过持续时间 14.0s，足迹地块过期移除
	rt.TickFlameFields(14.5, 0.5, op, []*enemy{foe}, verdict)
	if len(rt.FlameCells) != 0 {
		t.Fatalf("expected flame cells cleared after expiry, got %d", len(rt.FlameCells))
	}
}

// TestOxiS1FearAndStrike 验证 S1 高倍率斩击并对地面敌人施加恐惧
func TestOxiS1FearAndStrike(t *testing.T) {
	foe := &enemy{
		hp:        2000,
		index:     1,
		blockedBy: &operator{},
		spec:      SpawnSpec{Name: "地面敌人"},
	}
	if foe.blockedBy == nil {
		t.Fatalf("foe should be blocked initially")
	}

	foe.applyFear(3.0, [2]int{1, 1})
	if foe.fearTimer != 3.0 {
		t.Fatalf("expected fear timer 3.0, got %f", foe.fearTimer)
	}
	if foe.blockedBy != nil {
		t.Fatalf("fear should unblock the enemy")
	}
}

// TestOxiS2ShelterRetaliateAndBuff 验证 S2 受击消耗充能、前 0.2s 90% 减伤后线性衰减、反击范围法伤并吸血回复
func TestOxiS2ShelterRetaliateAndBuff(t *testing.T) {
	cfg := &OxiRuntimeConfig{
		Slot:                 2,
		S2SkillDuration:      1.3,
		S2DamageResistance:   0.9,
		S2ShelterHoldDur:     0.2,
		S2RetaliateAtkScale:  3.0,
		S2HealRatio:          0.05,
		S2Atk:                0.6,
		S2Def:                0.6,
		S2MaxStackCnt:        5,
		S2StackDuration:      5.0,
		S2AbilityRangeRadius: 1.0,
		InitSP:               3,
	}
	rt := newOxiRuntime(cfg)
	op := &operator{
		spec: OperatorSpec{
			Name:  "塔露拉",
			ATK:   1000,
			DEF:   500,
			MaxHP: 3000,
		},
		hp: 2000,
	}
	attacker := &enemy{
		hp:       5000,
		position: [2]float64{1.0, 1.0},
		spec:     SpawnSpec{Name: "攻击者", RES: 0},
		index:    1,
	}
	enemies := []*enemy{attacker}
	verdict := &Verdict{}

	if rt.Charges != 3 {
		t.Fatalf("expected 3 charges, got %d", rt.Charges)
	}

	// 第一次受击：触发技能二，消耗 1 次充能，受到伤害减免 90%（承伤 10%）
	incoming := 1000.0
	taken := rt.OnTakeDamage(10.0, attacker, incoming, op, enemies, verdict)
	if math.Abs(taken-100.0) > 1e-3 {
		t.Fatalf("expected initial damage 100 (90%% reduction), got %f", taken)
	}
	if rt.Charges != 2 {
		t.Fatalf("expected 2 charges remaining, got %d", rt.Charges)
	}
	if !rt.InActivePeriod {
		t.Fatalf("expected InActivePeriod to be true")
	}
	if rt.BuffStacks != 1 {
		t.Fatalf("expected 1 buff stack, got %d", rt.BuffStacks)
	}

	// 检查反击伤害：3.0 * 1000 = 3000，目标扣血 3000
	if attacker.hp != 2000 {
		t.Fatalf("expected attacker hp 2000 after 3000 retaliate, got %f", attacker.hp)
	}
	// 检查吸血回血：3000 * 0.05 = 150
	if op.hp != 2150 {
		t.Fatalf("expected op hp 2150 (healed 150), got %f", op.hp)
	}

	// 检查 S2 增益
	atkBonus, defBonus, allBlocked := rt.GetS2Buffs()
	if math.Abs(atkBonus-0.6) > 1e-6 || math.Abs(defBonus-0.6) > 1e-6 || !allBlocked {
		t.Fatalf("expected S2 buffs +0.6 ATK, +0.6 DEF, allBlocked=true")
	}

	// 推进 0.75s (经过 0.2s hold 之后衰减中)，此时减伤线性衰减
	rt.TickS2(10.55, 0.55) // activeRemaining 剩余 1.3 - 0.55 = 0.75s，已过 0.55s
	// elapsed = 0.55s, hold = 0.2s, remaining = 1.1s
	// decay = (0.55 - 0.2) / 1.1 = 0.35 / 1.1 ≈ 0.318
	// resist = 0.9 * (1 - 0.318) ≈ 0.6136 -> 承伤 ≈ 38.6%
	takenMid := rt.OnTakeDamage(10.55, attacker, 1000.0, op, enemies, verdict)
	if takenMid <= 100.0 || takenMid >= 900.0 {
		t.Fatalf("expected decaying damage between 100 and 900, got %f", takenMid)
	}
}

// TestOxiS3HeatwaveLifecycleAndOverdrive 验证 S3 停攻火浪弹道推进、常规与过载范围、碰撞爆炸与同波次衰减
func TestOxiS3HeatwaveLifecycleAndOverdrive(t *testing.T) {
	cfg := &OxiRuntimeConfig{
		Slot:                  3,
		Duration:              36.0,
		S3Atk:                 1.4,
		S3HeatwaveAtkScale:    2.5,
		S3NormalInterval:      2.67,
		S3OverloadInterval:    2.0,
		S3WaveSpeed:           2.3,
		S3NormalHalfWidth:     2.0,
		S3OverloadHalfWidth:   6.0,
		S3ProjectileRange:     0.5,
		S3RangeRadius:         1.5,
		S3WaveExitDistance:    5.0,
		S3SameWaveRepeatScale: 0.15,
	}
	rt := newOxiRuntime(cfg)
	rt.Position = [2]int{2, 5}
	rt.Dir = "Right" // dx=1, dy=0

	op := &operator{
		spec: OperatorSpec{
			Name: "塔露拉",
			ATK:  1000,
		},
		skillActive: true,
	}

	// 1. 常规阶段发射火浪 (半宽 2.0)
	rt.SpawnS3Wave(1.0, op)
	if len(rt.Waves) != 1 {
		t.Fatalf("expected 1 wave, got %d", len(rt.Waves))
	}
	w1 := rt.Waves[0]
	if w1.Overload {
		t.Fatalf("first wave should be normal phase")
	}
	if w1.HalfWidth != 2.0 {
		t.Fatalf("expected normal half width 2.0, got %f", w1.HalfWidth)
	}

	// 2. 模拟火浪推移并碰撞敌人
	// 塔露拉在 (2, 5)，朝右。敌人在 (4, 5)
	foe := &enemy{
		hp:       10000,
		position: [2]float64{4.0, 5.0},
		spec:     SpawnSpec{Name: "阻挡敌", RES: 0},
		index:    1,
	}
	enemies := []*enemy{foe}
	verdict := &Verdict{}

	// 火浪速度 2.3 格/秒，经过约 0.87s 推移至 x=4.0
	rt.TickS3(1.87, 0.87, op, enemies, verdict)
	if rt.TotalWaveHits != 1 {
		t.Fatalf("expected 1 wave hit, got %d", rt.TotalWaveHits)
	}
	// 伤害为 1000 * 2.5 = 2500
	if math.Abs(foe.hp-7500.0) > 1e-3 {
		t.Fatalf("expected foe hp 7500 after 2500 damage, got %f", foe.hp)
	}

	// 3. 过载阶段火浪 (半宽 6.0)
	rt.SkillElapsed = 19.0 // 超过 18.0s 进入过载
	rt.SpawnS3Wave(20.0, op)
	w2 := rt.Waves[len(rt.Waves)-1]
	if !w2.Overload {
		t.Fatalf("wave at 19s should be overload phase")
	}
	if w2.HalfWidth != 6.0 {
		t.Fatalf("expected overload half width 6.0, got %f", w2.HalfWidth)
	}

	// 4. 同一波次重复命中衰减测试
	w2.HitEnemies[foe.index] = true
	// 再次命中时 scale 应乘 0.15: 2.5 * 0.15 = 0.375 -> 伤害 375
	foeBefore := foe.hp
	scale := w2.Scale
	if w2.HitEnemies[foe.index] {
		scale *= w2.RepeatScl
	}
	dmg := resolveDamage(op.atk(), "MAGIC", scale, 0, foe.res(), 0)
	foe.take(dmg, op)
	if math.Abs((foeBefore-foe.hp)-375.0) > 1e-3 {
		t.Fatalf("expected repeated damage 375, got %f", foeBefore-foe.hp)
	}
}

// TestOxiDirectionDerivation 验证从站位与绝对攻击范围推导部署朝向
func TestOxiDirectionDerivation(t *testing.T) {
	cell := [2]int{3, 4}
	// 朝右: [3,4], [4,4]
	if dir := deriveDirectionFromRange(cell, [][2]int{{3, 4}, {4, 4}}); dir != "Right" {
		t.Errorf("expected Right, got %s", dir)
	}
	// 朝左: [3,4], [2,4]
	if dir := deriveDirectionFromRange(cell, [][2]int{{3, 4}, {2, 4}}); dir != "Left" {
		t.Errorf("expected Left, got %s", dir)
	}
	// 朝上: [3,4], [3,3]
	if dir := deriveDirectionFromRange(cell, [][2]int{{3, 4}, {3, 3}}); dir != "Up" {
		t.Errorf("expected Up, got %s", dir)
	}
	// 朝下: [3,4], [3,5]
	if dir := deriveDirectionFromRange(cell, [][2]int{{3, 4}, {3, 5}}); dir != "Down" {
		t.Errorf("expected Down, got %s", dir)
	}
}

// TestOxiFullSimulationIntegration 验证塔露拉在完整战斗循环 runSimContext 中的部署、普攻法伤与事件产出
func TestOxiFullSimulationIntegration(t *testing.T) {
	st := &OperatorStats{
		CharID:    oxiCharID,
		Elite:     2,
		Level:     90,
		Potential: 6,
	}
	specE2, err := buildOxiSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("buildOxiSourceSpec failed: %v", err)
	}

	opSpec := OperatorSpec{
		CharID:         oxiCharID,
		Name:           "塔露拉",
		Cell:           [2]int{1, 2},
		MaxHP:          3000,
		ATK:            1000,
		DEF:            450,
		RES:            10,
		AttackInterval: 1.2,
		DamageType:     "MAGIC",
		BlockCnt:       2,
		OxiSource:      specE2,
		Range:          [][2]int{{1, 2}, {2, 2}},
	}

	spawns := []SpawnSpec{
		{
			EnemyID:    "test_enemy",
			Name:       "普通感染生物",
			Time:       0.5,
			HP:         2000,
			ATK:        100,
			DEF:        50,
			RES:        10,
			MoveSpeed:  1.0,
			Weight:     1.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{2, 2}, {0, 2}},
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
		Operators: []OperatorSpec{opSpec},
		Deploys: []DeploySpec{
			{
				CharID: oxiCharID,
				Index:  0,
				Time:   0.0,
			},
		},
		Spawns: spawns,
	}

	verdict, err := runSimContext(context.Background(), &simSpec)
	if err != nil {
		t.Fatalf("runSimContext failed: %v", err)
	}

	for _, ev := range verdict.Events {
		t.Logf("Event: T=%f, Kind=%s, Who=%s", ev.T, ev.Kind, ev.Who)
	}
	t.Logf("Talulah full simulation: DamageDealt=%f, Kills=%d, Events=%d",
		verdict.DamageDealt, verdict.Kills, len(verdict.Events))

	if verdict.DamageDealt <= 0 {
		t.Fatalf("Expected Talulah to deal damage, got %f", verdict.DamageDealt)
	}
}
