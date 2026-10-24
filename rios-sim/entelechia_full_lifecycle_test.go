package main

import (
	"context"
	"testing"
)

func TestEntelechiaFullBattleLifecycle(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 获取隐德来希模组与天赋
	talent, err := resolveExactCountModuleTalent(&OperatorStats{
		CharID:      "char_4010_etlchi",
		Module:      "uniequip_003_etlchi",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err != nil {
		t.Fatalf("resolveExactCountModuleTalent failed: %v", err)
	}

	// 2. 构造隐德来希规格
	opSpec := OperatorSpec{
		Name:              "隐德来希",
		CharID:            "char_4010_etlchi",
		Cell:              [2]int{2, 2},
		MaxHP:             2038,
		ATK:               581,
		DEF:               388,
		RES:               0,
		BlockCnt:          2,
		AttackInterval:    1.3,
		DamageType:        "PHYSICAL",
		ExactModuleTalent: talent,
		EntelechiaSource:  defaultEntelechiaSource(),
		Range:             [][2]int{{2, 2}, {3, 2}, {4, 2}},
	}

	// 3. 构造敌人波次：2 只走过隐德来希身前的敌人
	spawns := []SpawnSpec{
		{
			EnemyID:    "test_slug_1",
			Name:       "源石虫A",
			Time:       0.5,
			HP:         1500,
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
			HP:         1500,
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

	// 4. 构造完整 Spec
	spec := Spec{
		FPS:      30,
		MaxTime:  12.0,
		Life:     3,
		CostInit: 99,
		CostMax:  99,
		CostTime: 1.0,
		Operators: []OperatorSpec{opSpec},
		Deploys: []DeploySpec{
			{
				CharID: "char_4010_etlchi",
				Index:  0,
				Time:   0.0,
			},
		},
		Spawns: spawns,
	}

	// 5. 真实运行模拟器
	verdict, err := runSimContext(context.Background(), &spec)
	if err != nil {
		t.Fatalf("runSim failed: %v", err)
	}

	t.Logf("Total events: %d, DamageDealt: %f", len(verdict.Events), verdict.DamageDealt)
	for _, ev := range verdict.Events {
		t.Logf("Event: t=%.2f kind=%s who=%s", ev.T, ev.Kind, ev.Who)
	}

	if verdict.DamageDealt <= 0 {
		t.Fatalf("expected Entelechia to deal damage, got %f", verdict.DamageDealt)
	}

	// 验证恢复脉冲事件与击杀事件
	recoveryPulses := 0
	dotPulses := 0
	kills := 0
	for _, ev := range verdict.Events {
		if ev.Kind == "entelechia_recovery_pulse" {
			recoveryPulses++
		}
		if ev.Kind == "entelechia_dot_pulse" {
			dotPulses++
		}
		if ev.Kind == "kill" {
			kills++
		}
	}

	t.Logf("Battle summary: DamageDealt=%.1f, Kills=%d, RecoveryPulses=%d, DotPulses=%d",
		verdict.DamageDealt, kills, recoveryPulses, dotPulses)

	if recoveryPulses == 0 {
		t.Fatalf("expected at least 1 recovery pulse from module, got 0")
	}
	if dotPulses == 0 {
		t.Fatalf("expected at least 1 DoT pulse on damaged enemies, got 0")
	}
	if kills != 2 {
		t.Fatalf("expected 2 kills, got %d", kills)
	}
}
