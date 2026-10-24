package main

import (
	"context"
	"testing"
)

func TestSakikoFullBattleLifecycle(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 获取丰川祥子真实模组与天赋（uniequip_002_oblvns 模组 3 级）
	talent, err := resolveExactCountModuleTalent(&OperatorStats{
		CharID:      "char_4182_oblvns",
		Module:      "uniequip_002_oblvns",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err != nil {
		t.Fatalf("resolveExactCountModuleTalent failed: %v", err)
	}

	rangedExemption, err := sakikoSkillRangedExemption(&OperatorStats{
		CharID:      "char_4182_oblvns",
		Module:      "uniequip_002_oblvns",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err != nil {
		t.Fatalf("sakikoSkillRangedExemption failed: %v", err)
	}

	// 2. 构造丰川祥子规格
	opSpec := OperatorSpec{
		Name:                 "丰川祥子",
		CharID:               "char_4182_oblvns",
		Cell:                 [2]int{2, 2},
		MaxHP:                2450,
		ATK:                  720,
		DEF:                  410,
		RES:                  10,
		BlockCnt:             2,
		AttackInterval:       1.3,
		DamageType:           "PHYSICAL",
		ExactModuleTalent:    talent,
		SkillRangedExemption: rangedExemption,
		SakikoSource:         defaultSakikoSource(),
		Range:                [][2]int{{2, 2}, {3, 2}, {4, 2}, {5, 2}},
	}

	// 3. 构造敌人波次：2 只走过祥子身前的敌人
	spawns := []SpawnSpec{
		{
			EnemyID:    "test_slug_1",
			Name:       "源石虫A",
			Time:       0.5,
			HP:         1000,
			ATK:        150,
			DEF:        50,
			RES:        0,
			MoveSpeed:  0.5,
			Interval:   2.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{4, 2}, {2, 2}, {0, 2}},
				},
			},
		},
		{
			EnemyID:    "test_slug_2",
			Name:       "源石虫B",
			Time:       1.0,
			HP:         1000,
			ATK:        150,
			DEF:        50,
			RES:        0,
			MoveSpeed:  0.5,
			Interval:   2.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{
					Kind:   "walk",
					Points: [][2]float64{{4, 2}, {2, 2}, {0, 2}},
				},
			},
		},
	}

	// 4. 构造完整战斗 Spec
	spec := Spec{
		FPS:       30,
		MaxTime:   12.0,
		Life:      3,
		CostInit:  99,
		CostMax:   99,
		CostTime:  1.0,
		Operators: []OperatorSpec{opSpec},
		Deploys: []DeploySpec{
			{
				CharID: "char_4182_oblvns",
				Index:  0,
				Time:   0.0,
			},
		},
		Spawns: spawns,
	}

	// 5. 真实运行模拟器主战斗循环
	verdict, err := runSimContext(context.Background(), &spec)
	if err != nil {
		t.Fatalf("runSim failed: %v", err)
	}

	t.Logf("Total events: %d, DamageDealt: %f", len(verdict.Events), verdict.DamageDealt)
	for _, ev := range verdict.Events {
		t.Logf("Event: t=%.2f kind=%s who=%s", ev.T, ev.Kind, ev.Who)
	}

	if verdict.DamageDealt <= 0 {
		t.Fatalf("expected Sakiko to deal damage, got %f", verdict.DamageDealt)
	}

	// 6. 验证音符发射、索敌、命中与击杀事件
	noteLaunches := 0
	noteAcquires := 0
	noteHits := 0
	kills := 0
	for _, ev := range verdict.Events {
		if ev.Kind == "sakiko_note_launch" {
			noteLaunches++
		}
		if ev.Kind == "sakiko_note_acquire" {
			noteAcquires++
		}
		if ev.Kind == "sakiko_note_hit" {
			noteHits++
		}
		if ev.Kind == "kill" {
			kills++
		}
	}

	t.Logf("Battle summary: DamageDealt=%.1f, Kills=%d, NoteLaunches=%d, NoteAcquires=%d, NoteHits=%d",
		verdict.DamageDealt, kills, noteLaunches, noteAcquires, noteHits)

	if noteLaunches == 0 {
		t.Fatalf("expected at least 1 note launch, got 0")
	}
	if noteAcquires == 0 {
		t.Fatalf("expected at least 1 note acquire, got 0")
	}
	if noteHits == 0 {
		t.Fatalf("expected at least 1 note hit, got 0")
	}
	if kills != 2 {
		t.Fatalf("expected 2 kills, got %d", kills)
	}
}

// TestSakikoSineAcquisitionAndRetreatCleanup 验证持续攻击正弦自由发射、索敌锁定以及撤退清理生命周期
func TestSakikoSineAcquisitionAndRetreatCleanup(t *testing.T) {
	chdirRepoRootForData(t)

	talent, err := resolveExactCountModuleTalent(&OperatorStats{
		CharID:      "char_4182_oblvns",
		Module:      "uniequip_002_oblvns",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err != nil {
		t.Fatalf("resolveExactCountModuleTalent failed: %v", err)
	}

	rangedExemption, err := sakikoSkillRangedExemption(&OperatorStats{
		CharID:      "char_4182_oblvns",
		Module:      "uniequip_002_oblvns",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err != nil {
		t.Fatalf("sakikoSkillRangedExemption failed: %v", err)
	}

	op := &operator{
		spec: OperatorSpec{
			Name:                 "丰川祥子",
			CharID:               "char_4182_oblvns",
			Cell:                 [2]int{2, 2},
			MaxHP:                2450,
			ATK:                  720,
			ExactModuleTalent:    talent,
			SkillRangedExemption: rangedExemption,
			SakikoSource:         defaultSakikoSource(),
		},
		hp: 2450,
	}
	op.sakikoStore = &sakikoOrdinaryStore{owner: op}

	// 1. 无目标自由发射正弦音符
	binding, err := op.sakikoStore.launchSine(0.0, [2]float64{2.0, 2.0}, [2]float64{1.0, 0.0}, true, 720, 1.0)
	if err != nil {
		t.Fatalf("launchSine failed: %v", err)
	}
	op.sakikoSineBindings = append(op.sakikoSineBindings, binding)
	if op.sakikoStore.count() != 1 {
		t.Fatalf("expected 1 note in store, got %d", op.sakikoStore.count())
	}

	// 2. 驱动正弦前进并在敌人接近时锁定与命中
	enemyTarget := &enemy{
		index:    10,
		spec:     SpawnSpec{Name: "远方敌人", DEF: 50, RES: 0},
		hp:       1000,
		position: [2]float64{3.2, 2.1},
	}
	enemies := []*enemy{enemyTarget}
	verdict := &Verdict{}
	sakikoTick([]*operator{op}, enemies, 0.1, 0.5, verdict)

	noteState := op.sakikoStore.notes[0].state
	if noteState.phase != sakikoNoteRemoved {
		t.Fatalf("expected note to hit and be removed, got phase %d", noteState.phase)
	}
	if enemyTarget.hp >= 1000 {
		t.Fatalf("expected enemy to take damage from note hit, got %f", enemyTarget.hp)
	}

	// 3. 再次发射一个正弦音符（无敌人），测试撤退清理
	binding2, err := op.sakikoStore.launchSine(1.0, [2]float64{2.0, 2.0}, [2]float64{1.0, 0.0}, false, 720, 1.0)
	if err != nil {
		t.Fatalf("launchSine 2 failed: %v", err)
	}
	op.sakikoSineBindings = append(op.sakikoSineBindings, binding2)
	note2 := op.sakikoStore.notes[1].state
	if note2.phase != sakikoNoteFree {
		t.Fatalf("expected free phase, got %d", note2.phase)
	}

	// 祥子撤退
	op.retreated = true
	op.hp = 0
	op.sakikoStore.sourceRetreat()
	if note2.phase != sakikoNoteRemoved {
		t.Fatalf("expected free note removed immediately upon retreat, got %d", note2.phase)
	}
}
