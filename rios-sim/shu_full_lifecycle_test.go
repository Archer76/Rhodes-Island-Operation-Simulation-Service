package main

import (
	"context"
	"testing"
)

// TestShuFullBattleLifecycle 是一次真正走主循环的集成测试：
//
//	黍（E2P5 模组三级，技能三）部署 → 技能开启 → 敌人经过**部署播种格**
//	获得锚点 → 走远超过 max_distance 被传送回该地块。
//
// 技能由引擎 `skillTick` 驱动（黍不再自建一套技力时钟）；测试夹具把
// `AutoTrigger` 打开只是为了不必写手动开技请求，生产路径里三技能是 MANUAL。
func TestShuFullBattleLifecycle(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{
		CharID: shuCharID, Elite: 2, Level: 60, Potential: 5,
		Module: shuModuleID, ModuleLevel: 3,
	}
	shuSource, err := buildShuSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildShuSourceSpec failed: %v", err)
	}

	ops := []OperatorSpec{
		{
			Name:           "黍",
			CharID:         shuCharID,
			Cell:           [2]int{2, 2},
			MaxHP:          3800,
			ATK:            550,
			DEF:            680,
			RES:            10,
			BlockCnt:       0, // 不阻挡：让敌人能经过部署播种格
			AttackInterval: 1.2,
			DamageType:     "PHYSICAL",
			ShuSource:      shuSource,
			Range:          [][2]int{{2, 2}, {3, 2}, {4, 2}, {1, 2}, {2, 3}, {2, 1}},
			Skill: &SkillSpec{
				SPType: spAuto, SPCost: 45, InitSP: 45, Increment: 1,
				Duration: 30, DurationType: "NONE", MaxCharge: 1, AutoTrigger: true,
			},
		},
		{
			Name:           "友方",
			CharID:         "char_208_melan",
			Cell:           [2]int{3, 1},
			MaxHP:          1500,
			ATK:            300,
			DEF:            200,
			RES:            0,
			BlockCnt:       0,
			AttackInterval: 1.0,
			DamageType:     "PHYSICAL",
			Range:          [][2]int{{3, 1}},
		},
	}

	spawns := []SpawnSpec{
		{
			EnemyID:    "test_runner",
			Name:       "穿梭者",
			Time:       0.5,
			HP:         50000,
			ATK:        0,
			DEF:        0,
			RES:        0,
			MoveSpeed:  1.0,
			Interval:   2.0,
			DamageType: "PHYSICAL",
			Legs: []LegSpec{
				{Kind: "walk", Points: [][2]float64{{0, 2}, {9, 2}}, Length: 9},
			},
		},
	}

	spec := &Spec{
		FPS:        30,
		MaxTime:    30.0,
		SpeedScale: 1.0,
		Life:       10,
		CostInit:   50,
		CostMax:    99,
		CostTime:   1.0,
		Operators:  ops,
		Deploys: []DeploySpec{
			{Time: 0.0, CharID: shuCharID, Index: 0},
			{Time: 0.1, CharID: "char_208_melan", Index: 1},
		},
		Spawns: spawns,
	}

	verdict, err := runSimContext(context.Background(), spec)
	if err != nil {
		t.Fatalf("runSimContext failed: %v", err)
	}
	if verdict == nil {
		t.Fatal("verdict is nil")
	}

	var skillStarts, teleports int
	for _, ev := range verdict.Events {
		switch ev.Kind {
		case "shu_skill_start":
			skillStarts++
		case "shu_teleport":
			teleports++
		}
	}
	if skillStarts == 0 {
		t.Fatalf("技能未开启：事件 %+v", verdict.Events)
	}
	if teleports == 0 {
		t.Fatalf("未发生传送：事件 %+v", verdict.Events)
	}
	t.Logf("skill_starts=%d teleports=%d kills=%d elapsed=%.2f",
		skillStarts, teleports, verdict.Kills, verdict.Elapsed)
}
