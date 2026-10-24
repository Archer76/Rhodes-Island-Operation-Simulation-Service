package main

import (
	"encoding/json"
	"testing"
)

type hsStageItem struct {
	ID         string
	Code       string
	Difficulty string
}

var allHuaiShuLiStages = []hsStageItem{
	// 主线 HS-1 ~ HS-9
	{ID: "act31side_01", Code: "HS-1", Difficulty: "NORMAL"},
	{ID: "act31side_02", Code: "HS-2", Difficulty: "NORMAL"},
	{ID: "act31side_03", Code: "HS-3", Difficulty: "NORMAL"},
	{ID: "act31side_04", Code: "HS-4", Difficulty: "NORMAL"},
	{ID: "act31side_05", Code: "HS-5", Difficulty: "NORMAL"},
	{ID: "act31side_06", Code: "HS-6", Difficulty: "NORMAL"},
	{ID: "act31side_07", Code: "HS-7", Difficulty: "NORMAL"},
	{ID: "act31side_08", Code: "HS-8", Difficulty: "NORMAL"},
	{ID: "act31side_09", Code: "HS-9", Difficulty: "NORMAL"},

	// 遭遇与支线 HS-S-1 ~ HS-S-4, MO-1, TR-1, TR-2
	{ID: "act31side_s01", Code: "HS-S-1", Difficulty: "NORMAL"},
	{ID: "act31side_s01", Code: "HS-S-1 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_s02", Code: "HS-S-2", Difficulty: "NORMAL"},
	{ID: "act31side_s02", Code: "HS-S-2 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_s03", Code: "HS-S-3", Difficulty: "NORMAL"},
	{ID: "act31side_s03", Code: "HS-S-3 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_s04", Code: "HS-S-4", Difficulty: "NORMAL"},
	{ID: "act31side_s04", Code: "HS-S-4 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_mo01", Code: "HS-MO-1", Difficulty: "NORMAL"},
	{ID: "act31side_tr01", Code: "HS-TR-1", Difficulty: "NORMAL"},
	{ID: "act31side_tr02", Code: "HS-TR-2", Difficulty: "NORMAL"},

	// 高难/突袭 HS-EX-1 ~ HS-EX-8
	{ID: "act31side_ex01", Code: "HS-EX-1", Difficulty: "NORMAL"},
	{ID: "act31side_ex01", Code: "HS-EX-1 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex02", Code: "HS-EX-2", Difficulty: "NORMAL"},
	{ID: "act31side_ex02", Code: "HS-EX-2 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex03", Code: "HS-EX-3", Difficulty: "NORMAL"},
	{ID: "act31side_ex03", Code: "HS-EX-3 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex04", Code: "HS-EX-4", Difficulty: "NORMAL"},
	{ID: "act31side_ex04", Code: "HS-EX-4 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex05", Code: "HS-EX-5", Difficulty: "NORMAL"},
	{ID: "act31side_ex05", Code: "HS-EX-5 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex06", Code: "HS-EX-6", Difficulty: "NORMAL"},
	{ID: "act31side_ex06", Code: "HS-EX-6 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex07", Code: "HS-EX-7", Difficulty: "NORMAL"},
	{ID: "act31side_ex07", Code: "HS-EX-7 (突袭)", Difficulty: "FOUR_STAR"},
	{ID: "act31side_ex08", Code: "HS-EX-8", Difficulty: "NORMAL"},
	{ID: "act31side_ex08", Code: "HS-EX-8 (突袭)", Difficulty: "FOUR_STAR"},
}

func TestBuildSpecAllHuaiShuLiStages(t *testing.T) {
	chdirRepoRootForData(t)

	for _, item := range allHuaiShuLiStages {
		t.Run(item.Code+"_"+item.Difficulty, func(t *testing.T) {
			planJSON := `{
				"stage": "` + item.ID + `",
				"deploys": [
					{
						"operator": "芬",
						"position": [0, 0],
						"direction": "Right",
						"skill": 1,
						"time": 0.0,
						"elite": 0,
						"level": 30,
						"potential": 1
					}
				]
			}`
			bq := BuildSpecQuery{
				Difficulty:  item.Difficulty,
				MaxTime:     10.0,
				Plan:        json.RawMessage(planJSON),
				AllowSkills: true,
			}
			out, err := BuildSpecFull(item.ID, "", bq)
			if err != nil {
				t.Fatalf("BuildSpecFull %s (%s) failed: %v", item.Code, item.ID, err)
			}
			// 检查基础规格
			spec := out.Spec
			t.Logf("[%s %s] Stage: %s, Life: %d, CostInit: %.0f, Spawns: %d, Mechs: %v, Unsupported: %v",
				item.Code, item.Difficulty, spec.Stage, spec.Life, spec.CostInit,
				len(spec.Spawns), spec.Mechanisms, spec.Unsupported)

			if len(spec.Spawns) == 0 && item.Code != "HS-TR-1" && item.Code != "HS-TR-2" {
				t.Fatalf("[%s] expected spawns, got 0", item.Code)
			}
		})
	}
}

func TestRunSimHuaiShuLiRepresentativeStages(t *testing.T) {
	chdirRepoRootForData(t)

	for _, item := range allHuaiShuLiStages {
		t.Run(item.Code+"_"+item.Difficulty, func(t *testing.T) {
			planJSON := `{
				"stage": "` + item.ID + `",
				"deploys": [
					{
						"operator": "芬",
						"position": [0, 0],
						"direction": "Right",
						"skill": 1,
						"time": 0.0,
						"elite": 0,
						"level": 30,
						"potential": 1
					}
				]
			}`
			bq := BuildSpecQuery{
				Difficulty:  item.Difficulty,
				MaxTime:     30.0,
				Plan:        json.RawMessage(planJSON),
				AllowSkills: true,
			}
			out, err := BuildSpecFull(item.ID, "", bq)
			if err != nil {
				t.Fatalf("BuildSpecFull %s failed: %v", item.Code, err)
			}

			raw, err := json.Marshal(out.Spec)
			if err != nil {
				t.Fatalf("marshal spec failed: %v", err)
			}
			var spec Spec
			if err := json.Unmarshal(raw, &spec); err != nil {
				t.Fatalf("unmarshal spec failed: %v", err)
			}

			// 为未显式标注的普通敌人填充无隐匿可见性
			for i := range spec.Spawns {
				if spec.Spawns[i].CountVisibility == nil {
					spec.Spawns[i].CountVisibility = &CountVisibility{Hidden: false, Camouflage: false}
				}
			}
			// 确保有足够的命数跑满测试观测窗口
			spec.Life = 50

			verdict, err := runSim(&spec)
			if err != nil {
				t.Fatalf("[%s] runSim failed: %v", item.Code, err)
			}
			if verdict == nil {
				t.Fatalf("[%s] runSim returned nil verdict", item.Code)
			}

			spawnsSeen := 0
			for _, ev := range verdict.Events {
				if ev.Kind == "spawn" {
					spawnsSeen++
				}
			}
			t.Logf("[%s %s] Simulated successfully: SpawnsPlaced=%d, SpawnsSeen=%d, Events=%d, Won=%v",
				item.Code, item.Difficulty, verdict.SpawnsPlaced, spawnsSeen, len(verdict.Events), verdict.Won)
			if spawnsSeen == 0 {
				t.Fatalf("[%s] expected spawns seen, got 0", item.Code)
			}
		})
	}
}
