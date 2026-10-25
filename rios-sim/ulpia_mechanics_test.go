package main

import (
	"math"
	"testing"
)

func ulpiaUnit(name string, cell [2]float64, maxHP, atk float64, blockCnt int) *operator {
	return &operator{
		cell: cell,
		hp:   maxHP,
		spec: OperatorSpec{
			Name:       name,
			CharID:     ulpiaCharID,
			MaxHP:      maxHP,
			ATK:        atk,
			BlockCnt:   blockCnt,
			DamageType: "PHYSICAL",
			Range:      [][2]int{{0, 0}, {1, 0}},
		},
	}
}

func ulpiaEnemy(name string, cell [2]float64, hp float64) *enemy {
	return &enemy{
		position: cell,
		hp:       hp,
		spec: SpawnSpec{
			Name:        name,
			HP:          hp,
			AttackRange: 1.0,
		},
	}
}

// 1. 验证天赋一在常规血量与低于阈值（50% / 模组 60%）时的自愈数值
func TestUlpiaTalent1SelfHealThresholds(t *testing.T) {
	st := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}
	cfg := ulpiaCfgForTest(t, st, 1, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)

	// 高于 50%：受到 100 伤害（剩 5900），自愈 100 点
	op.hp = 6000
	op.hurt(100)
	if op.hp != 6000 {
		t.Fatalf("expected hp healed back to 6000, got %.1f", op.hp)
	}
	if op.ulpiaState.T1HealTriggers != 1 || op.ulpiaState.T1HealAmount != 100 {
		t.Fatalf("expected 1 trigger and 100 healed, got %d / %.1f", op.ulpiaState.T1HealTriggers, op.ulpiaState.T1HealAmount)
	}

	// 低于 50%：受大伤降到 2000（2000/6000 = 33.3% < 50%），受击自愈应为 160 点
	op.hp = 2000
	op.hurt(10) // 受到 10 点伤害降到 1990，低于 50% 触发自愈 160 -> 2150
	if op.hp != 2150 {
		t.Fatalf("expected hp healed to 2150, got %.1f", op.hp)
	}
	if op.ulpiaState.T1HealTriggers != 2 || op.ulpiaState.T1HealAmount != 260 {
		t.Fatalf("expected 2 triggers and 260 healed, got %d / %.1f", op.ulpiaState.T1HealTriggers, op.ulpiaState.T1HealAmount)
	}
}

// 2. 验证技能二开启时天赋一自愈翻倍（2.0倍）
func TestUlpiaTalent1Skill2Scale(t *testing.T) {
	st := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}
	cfg := ulpiaCfgForTest(t, st, 2, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)
	op.skillActive = true

	// 技能二开启时，低于 50% 自愈点数应为 160 * 2.0 = 320
	op.hp = 2000
	op.hurt(10) // 1990 + 320 = 2310
	if op.hp != 2310 {
		t.Fatalf("expected hp healed to 2310 under skill 2, got %.1f", op.hp)
	}
}

// 3. 验证模组X特性（受治疗效果提升 1.2倍）与天赋一数值强化（130/175/60%）
func TestUlpiaModuleXHealEnhance(t *testing.T) {
	st := &OperatorStats{
		CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1,
		Module: ulpiaModule1ID, ModuleLevel: 3,
	}
	cfg := ulpiaCfgForTest(t, st, 1, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)

	// 高于 60%：常态 130 * 1.2 = 156
	op.hp = 5000 // 5000/6000 = 83.3% > 60%
	op.hurt(10)  // 4990 + 156 = 5146
	if math.Abs(op.hp-5146) > 1e-6 {
		t.Fatalf("expected hp 5146, got %.1f", op.hp)
	}

	// 低于 60%：常态 175 * 1.2 = 210
	op.hp = 3000 // 3000/6000 = 50% < 60%
	op.hurt(10)  // 2990 + 210 = 3200
	if math.Abs(op.hp-3200) > 1e-6 {
		t.Fatalf("expected hp 3200, got %.1f", op.hp)
	}
}

// 4. 验证天赋二击倒敌人叠加层数、生命上限与攻击力提升、以及上限封顶
func TestUlpiaTalent2KillStackRamp(t *testing.T) {
	st := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}
	cfg := ulpiaCfgForTest(t, st, 1, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)

	// 初始状态
	if op.maxHP() != 6000 || op.atk() != 1500 {
		t.Fatalf("initial stats mismatch: hp=%.1f, atk=%.1f", op.maxHP(), op.atk())
	}

	// 击杀敌人叠加
	e := ulpiaEnemy("小怪", [2]float64{0, 0}, 100)
	for i := 1; i <= 15; i++ {
		ulpiaTalent2OnKill(op, e, float64(i), nil)
	}

	// 潜能 1 上限应为 9 层：每层 +120 HP, +30 ATK
	// 9层: +1080 HP, +270 ATK => maxHP=7080, atk=1770
	if op.ulpiaState.KillStack != 9 {
		t.Fatalf("expected stack capped at 9, got %d", op.ulpiaState.KillStack)
	}
	if op.maxHP() != 7080 {
		t.Fatalf("expected maxHP 7080, got %.1f", op.maxHP())
	}
	if op.atk() != 1770 {
		t.Fatalf("expected atk 1770, got %.1f", op.atk())
	}
}

// 5. 验证模组Y 达到 9 层击杀后阻挡数 +1，以及对被自身阻挡敌人的 1.1倍伤害
func TestUlpiaModuleYBlockAndDamageScale(t *testing.T) {
	st := &OperatorStats{
		CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1,
		Module: ulpiaModule2ID, ModuleLevel: 3,
	}
	cfg := ulpiaCfgForTest(t, st, 1, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)

	// 8 层时无阻挡加成
	op.ulpiaState.KillStack = 8
	if op.ulpiaBlockCntBonus() != 0 {
		t.Fatalf("expected 0 block bonus at 8 stacks, got %d", op.ulpiaBlockCntBonus())
	}

	// 9 层时阻挡数 +1
	op.ulpiaState.KillStack = 9
	if op.ulpiaBlockCntBonus() != 1 {
		t.Fatalf("expected 1 block bonus at 9 stacks, got %d", op.ulpiaBlockCntBonus())
	}

	// 模组特性对阻挡目标伤害提升
	targetA := ulpiaEnemy("被阻挡者", [2]float64{0, 0}, 1000)
	targetB := ulpiaEnemy("未被阻挡者", [2]float64{1, 0}, 1000)
	op.blocking = []*enemy{targetA}

	if scale := op.ulpiaDamageScale(targetA); scale != 1.1 {
		t.Fatalf("expected 1.1 damage scale for blocked target, got %v", scale)
	}
	if scale := op.ulpiaDamageScale(targetB); scale != 1.0 {
		t.Fatalf("expected 1.0 damage scale for unblocked target, got %v", scale)
	}
}

// 6. 验证技能二开启时阻挡数 +1
func TestUlpiaSkill2BlockBonus(t *testing.T) {
	st := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}
	cfg := ulpiaCfgForTest(t, st, 2, 10)
	op := ulpiaUnit("乌尔比安", [2]float64{0, 0}, 6000, 1500, 2)
	op.ulpiaState = newUlpiaBattleState(cfg)

	if op.ulpiaBlockCntBonus() != 0 {
		t.Fatalf("expected 0 bonus before active")
	}
	op.skillActive = true
	if op.ulpiaBlockCntBonus() != 1 {
		t.Fatalf("expected 1 bonus after skill 2 active, got %d", op.ulpiaBlockCntBonus())
	}
}

// 7. 验证机制缺口具名上报（force、位移、深海猎人光环）
func TestUlpiaGapsReported(t *testing.T) {
	st := &OperatorStats{CharID: ulpiaCharID, Elite: 2, Level: 60, Potential: 1}

	// 技能一应上报 force 缺口与深海猎人光环
	specS1, err := buildUlpiaSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("build S1 spec: %v", err)
	}
	gapsS1 := ulpiaRemainingGapsFromSpec(specS1, "乌尔比安", 0)
	hasForce := false
	hasAura := false
	for _, g := range gapsS1 {
		if g.ID == "ulpia.skill1.displacement_force" {
			hasForce = true
		}
		if g.ID == "ulpia.talent2.abyssal_aura" {
			hasAura = true
		}
	}
	if !hasForce {
		t.Fatalf("expected displacement_force gap in S1, got %v", gapsS1)
	}
	if !hasAura {
		t.Fatalf("expected abyssal_aura gap, got %v", gapsS1)
	}

	// 技能三应上报 projectile_displacement 缺口
	specS3, err := buildUlpiaSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("build S3 spec: %v", err)
	}
	gapsS3 := ulpiaRemainingGapsFromSpec(specS3, "乌尔比安", 0)
	hasS3Disp := false
	for _, g := range gapsS3 {
		if g.ID == "ulpia.skill3.projectile_displacement" {
			hasS3Disp = true
		}
	}
	if !hasS3Disp {
		t.Fatalf("expected projectile_displacement gap in S3, got %v", gapsS3)
	}
}
