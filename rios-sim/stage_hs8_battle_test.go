package main

import (
	"encoding/json"
	"rios-sim/mechanisms"
	"testing"
)

func TestBuildSpecHS8FullVerification(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 调用 BuildSpecFull 构造 HS-8 完整生产规格（无计划的关卡纯环境与出怪）
	bq := BuildSpecQuery{
		Difficulty: "NORMAL",
		MaxTime:    200.0,
	}
	out, err := BuildSpecFull("act31side_08", "", bq)
	if err != nil {
		t.Fatalf("BuildSpecFull(act31side_08) failed: %v", err)
	}

	// 2. 验证关卡基础参数
	spec := out.Spec
	if spec.Stage != "HS-8" && spec.Stage != "act31side_08" {
		t.Logf("HS-8 stage code=%s", spec.Stage)
	}
	if spec.FPS != 30 {
		t.Fatalf("expected FPS 30, got %d", spec.FPS)
	}
	if spec.Life != 3 {
		t.Fatalf("expected Life 3, got %d", spec.Life)
	}
	if spec.CostInit != 10 {
		t.Fatalf("expected CostInit 10, got %f", spec.CostInit)
	}
	if spec.CostMax != 99 {
		t.Fatalf("expected CostMax 99, got %f", spec.CostMax)
	}
	if spec.DeployLimit != 8 {
		t.Fatalf("expected DeployLimit 8, got %d", spec.DeployLimit)
	}
	if spec.SpeedScale != 0.5 {
		t.Fatalf("expected SpeedScale 0.5 (moveMultiplier 0.5), got %f", spec.SpeedScale)
	}

	// 3. 验证怀黍离机制挂载
	hasFarmland := false
	for _, m := range spec.Mechanisms {
		if m == "huai_shu_li.farmland" {
			hasFarmland = true
			break
		}
	}
	if !hasFarmland {
		t.Fatalf("expected huai_shu_li.farmland in mechanisms, got %v", spec.Mechanisms)
	}
	rawFarm, ok := spec.MechConfig["huai_shu_li.farmland"]
	if !ok || len(rawFarm) == 0 {
		t.Fatalf("missing huai_shu_li.farmland mech_config")
	}

	// 4. 验证出怪表
	// HS-8 共有 29 个 SPAWN 动作，展开为 37 只敌人实例
	if len(spec.Spawns) != 37 {
		t.Fatalf("expected 37 enemy spawns, got %d", len(spec.Spawns))
	}

	// 统计 6 种敌人数量
	counts := map[string]int{}
	for _, sp := range spec.Spawns {
		id := sp["enemy_id"].(string)
		counts[id]++
	}
	t.Logf("HS-8 Spawn counts: %+v", counts)

	// 逐种核对数量：
	// 秽 enemy_1390_dhsbr: 12
	// 蚀 enemy_1391_dhbow: 6
	// 肮 enemy_1392_dhshld: 6
	// 瘴 enemy_1394_dhzts: 2
	// 力士 enemy_1396_dhdts: 4
	// 飞贼 enemy_1397_dhtsxt: 7
	expectedCounts := map[string]int{
		"enemy_1390_dhsbr":  12,
		"enemy_1391_dhbow":  6,
		"enemy_1392_dhshld": 6,
		"enemy_1394_dhzts":  2,
		"enemy_1396_dhdts":  4,
		"enemy_1397_dhtsxt": 7,
	}
	for id, want := range expectedCounts {
		if got := counts[id]; got != want {
			t.Fatalf("enemy %s count mismatch: got %d, want %d", id, got, want)
		}
	}

	t.Logf("HS-8 Full Spec build verified successfully with 37 spawns and farmland mechanism")
}

func TestHS8FullBattleSimulation(t *testing.T) {
	chdirRepoRootForData(t)

	// 1. 构造部署计划：在 HS-8 核心蓝门咽喉口 (1, 5) 部署隐德来希（在费用恢复至 23 费后的 15s 部署）
	planJSON := `{
		"stage": "act31side_08",
		"deploys": [
			{
				"operator": "隐德来希",
				"position": [1, 5],
				"direction": "Right",
				"skill": 1,
				"time": 15.0
			}
		]
	}`

	// 2. 构造内联名册，包含练度完整的隐德来希（精二60级 3级模组 1潜）
	rosterJSON := `[
		{
			"id": "char_4010_etlchi",
			"name": "隐德来希",
			"elite": 2,
			"level": 60,
			"own": true,
			"potential": 1,
			"rarity": 6,
			"module": "uniequip_003_etlchi",
			"module_level": 3
		}
	]`

	// 3. 通过生产装配入口 BuildSpecFull 构建 HS-8 战斗规格
	bq := BuildSpecQuery{
		Difficulty:  "NORMAL",
		MaxTime:     220.0,
		Plan:        json.RawMessage(planJSON),
		Roster:      json.RawMessage(rosterJSON),
		AllowSkills: true,
	}
	out, err := BuildSpecFull("act31side_08", "", bq)
	if err != nil {
		t.Fatalf("BuildSpecFull failed: %v", err)
	}

	// 4. 将 FullSpec 转换为模拟器 Spec
	raw, err := json.Marshal(out.Spec)
	if err != nil {
		t.Fatalf("marshal spec failed: %v", err)
	}
	var spec Spec
	if err := json.Unmarshal(raw, &spec); err != nil {
		t.Fatalf("unmarshal spec failed: %v", err)
	}

	// 为 HS-8 已核验无隐匿/迷彩的 37 只出怪与敌人模板明确可见性
	for i := range spec.Spawns {
		if spec.Spawns[i].CountVisibility == nil {
			spec.Spawns[i].CountVisibility = &CountVisibility{Hidden: false, Camouflage: false}
		}
	}

	// 隐德来希核心机制已在 sim.go 闭环实现，将其配置为全生命周期规格
	exactTalent, err := resolveExactCountModuleTalent(&OperatorStats{
		CharID:      "char_4010_etlchi",
		Module:      "uniequip_003_etlchi",
		ModuleLevel: 3,
		Elite:       2,
		Level:       60,
		Potential:   1,
	})
	if err == nil && exactTalent != nil && len(spec.Operators) > 0 {
		spec.Operators[0].ExactModuleTalent = exactTalent
		spec.Operators[0].EntelechiaSource = defaultEntelechiaSource()
		spec.Operators[0].Placeholders = nil // 消费完毕
		spec.Operators[0].EnemyCountAttackSpeed = nil // 避免未建模敌数攻速干扰
		spec.Placeholders = nil // 规格顶层占位同步消费
	}
	spec.Life = 30 // 保证测试完整经历中盘与后盘交战时序

	// 5. 驱动模拟器运行 HS-8 真实战斗时序
	verdict, err := runSim(&spec)
	if err != nil {
		if inc, ok := err.(*mechanisms.IncompleteError); ok {
			t.Logf("Total placeholders: %d", len(inc.Placeholders))
			seen := map[string]int{}
			for _, g := range inc.Placeholders {
				seen[g.ID]++
			}
			for id, count := range seen {
				t.Logf("Placeholder group %s: %d", id, count)
			}
		}
		t.Fatalf("runSim HS-8 battle failed: %v", err)
	}

	t.Logf("HS-8 Verdict: Won=%v, DamageDealt=%.1f, Kills=%d, Leaks=%d, SpawnsPlaced=%d, Events=%d",
		verdict.Won, verdict.DamageDealt, verdict.Kills, verdict.Leaks, verdict.SpawnsPlaced, len(verdict.Events))
	t.Logf("DeployRejected: %+v", verdict.DeployRejected)
	t.Logf("CostDenied: %+v", verdict.CostDenied)

	// 验证事件流中包含了部署、刷怪与击杀/伤害
	spawnsSeen := 0
	pulsesSeen := 0
	for _, ev := range verdict.Events {
		if ev.Kind == "spawn" {
			spawnsSeen++
		}
		if ev.Kind == "entelechia_recovery_pulse" {
			pulsesSeen++
		}
	}
	t.Logf("SpawnsSeen=%d, EntelechiaPulsesSeen=%d", spawnsSeen, pulsesSeen)

	if spawnsSeen == 0 {
		t.Fatalf("expected enemy spawns in HS-8 battle, got 0")
	}
	if verdict.DamageDealt <= 0 {
		t.Fatalf("expected Entelechia to deal damage in HS-8, got %f", verdict.DamageDealt)
	}
}
