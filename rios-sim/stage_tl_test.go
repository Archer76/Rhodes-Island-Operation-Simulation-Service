package main

import (
	"path/filepath"
	"strings"
	"testing"
)

type tlStageItem struct {
	ID         string
	Code       string
	Difficulty string
	Name       string
}

var allTLStages = []tlStageItem{
	{ID: "act55side_01", Code: "TL-1", Difficulty: "NORMAL", Name: "庸俗的实践"},
	{ID: "act55side_02", Code: "TL-2", Difficulty: "NORMAL", Name: "孑遗的道路"},
	{ID: "act55side_03", Code: "TL-3", Difficulty: "NORMAL", Name: "苦难的历程"},
	{ID: "act55side_04", Code: "TL-4", Difficulty: "NORMAL", Name: "刻板的争论"},
	{ID: "act55side_05", Code: "TL-5", Difficulty: "NORMAL", Name: "轰鸣的沉默"},
	{ID: "act55side_06", Code: "TL-6", Difficulty: "NORMAL", Name: "元音的长度"},
	{ID: "act55side_07", Code: "TL-7", Difficulty: "NORMAL", Name: "滚烫的双眸"},
	{ID: "act55side_08", Code: "TL-8", Difficulty: "NORMAL", Name: "潮湿的火焰"},
	{ID: "act55side_09", Code: "TL-9", Difficulty: "NORMAL", Name: "自由的黄昏"},
	{ID: "act55side_10", Code: "TL-10", Difficulty: "NORMAL", Name: "活着的重量"},

	// 高难关卡 TL-EX-1 ~ TL-EX-8 (普通与突袭)
	{ID: "act55side_ex01", Code: "TL-EX-1", Difficulty: "NORMAL", Name: "致我的陛下……"},
	{ID: "act55side_ex01", Code: "TL-EX-1", Difficulty: "FOUR_STAR", Name: "致我的陛下……"},
	{ID: "act55side_ex02", Code: "TL-EX-2", Difficulty: "NORMAL", Name: "致拉·尼·苏沃林"},
	{ID: "act55side_ex02", Code: "TL-EX-2", Difficulty: "FOUR_STAR", Name: "致拉·尼·苏沃林"},
	{ID: "act55side_ex03", Code: "TL-EX-3", Difficulty: "NORMAL", Name: "致马特维"},
	{ID: "act55side_ex03", Code: "TL-EX-3", Difficulty: "FOUR_STAR", Name: "致马特维"},
	{ID: "act55side_ex04", Code: "TL-EX-4", Difficulty: "NORMAL", Name: "致谢尔戈·卡拉泽"},
	{ID: "act55side_ex04", Code: "TL-EX-4", Difficulty: "FOUR_STAR", Name: "致谢尔戈·卡拉泽"},
	{ID: "act55side_ex05", Code: "TL-EX-5", Difficulty: "NORMAL", Name: "致雷尔金"},
	{ID: "act55side_ex05", Code: "TL-EX-5", Difficulty: "FOUR_STAR", Name: "致雷尔金"},
	{ID: "act55side_ex06", Code: "TL-EX-6", Difficulty: "NORMAL", Name: "致雷德先生"},
	{ID: "act55side_ex06", Code: "TL-EX-6", Difficulty: "FOUR_STAR", Name: "致雷德先生"},
	{ID: "act55side_ex07", Code: "TL-EX-7", Difficulty: "NORMAL", Name: "致瓦伊凡小姑娘"},
	{ID: "act55side_ex07", Code: "TL-EX-7", Difficulty: "FOUR_STAR", Name: "致瓦伊凡小姑娘"},
	{ID: "act55side_ex08", Code: "TL-EX-8", Difficulty: "NORMAL", Name: "致……"},
	{ID: "act55side_ex08", Code: "TL-EX-8", Difficulty: "FOUR_STAR", Name: "致……"},
}

func TestSqliteResourcePackAct55Side(t *testing.T) {
	chdirRepoRootForData(t)

	dbRoot := "data"
	enemyDBPath := filepath.Join(dbRoot, "enemydb_pure.sqlite")
	stagePackPath := filepath.Join(dbRoot, "stages_act55side.sqlite")

	// 1. 纯中央敌人库加载与核心敌人断言
	enemyLib, err := LoadPureEnemyLibrary(enemyDBPath)
	if err != nil {
		t.Fatalf("LoadPureEnemyLibrary failed: %v", err)
	}

	tlRequiredCoreEnemies := []string{
		"enemy_10253_dsjxb",
		"enemy_10254_dsjarc",
		"enemy_10255_dsjmgc",
		"enemy_10256_dsjsld",
		"enemy_10257_dsjtsz",
		"enemy_10258_dsjccs",
		"enemy_10259_dsjpgg",
		"enemy_10260_dsjzds",
		"enemy_10261_dsjcmd",
		"enemy_10261_dsjcmd_2",
		"enemy_10262_dsjred",
		"enemy_10263_dsjblk",
		"enemy_1602_blksnk",
		"enemy_1602_blksnk2_1",
		"enemy_1603_hlystp",
		"enemy_1603_hlystp2_1",
	}

	for _, eID := range tlRequiredCoreEnemies {
		if len(enemyLib.ByKey[eID]) == 0 {
			t.Fatalf("expected enemy %s in pure enemyLib, but not found", eID)
		}
	}
	t.Logf("Pure enemy library validated: %d total enemies, all act55side core enemies present", len(enemyLib.ByKey))

	// 2. 遍历测试 TL-1 至 TL-10 与 TL-EX-1 至 TL-EX-8 全部 26 个关卡档位装配
	for _, item := range allTLStages {
		t.Run("Pack_"+item.Code+"_"+item.Difficulty, func(t *testing.T) {
			spec, err := LoadStageFromPack(stagePackPath, item.ID, item.Difficulty, enemyLib)
			if err != nil {
				t.Fatalf("LoadStageFromPack failed for %s (%s): %v", item.Code, item.Difficulty, err)
			}
			if spec.Life <= 0 {
				t.Fatalf("[%s] expected positive Life, got %d", item.Code, spec.Life)
			}
			if spec.CostInit < 0 {
				t.Fatalf("[%s] expected non-negative CostInit, got %.1f", item.Code, spec.CostInit)
			}
			if spec.DeployLimit <= 0 {
				t.Fatalf("[%s] expected positive DeployLimit, got %d", item.Code, spec.DeployLimit)
			}
			if len(spec.Spawns) == 0 {
				t.Fatalf("[%s] expected non-empty spawns from pack, got 0", item.Code)
			}

			t.Logf("[%s %s] Loaded from SQLite: Spawns=%d, Life=%d, CostInit=%.0f, DeployLimit=%d",
				item.Code, item.Difficulty, len(spec.Spawns), spec.Life, spec.CostInit, spec.DeployLimit)
		})
	}

	// 3. 严格依赖断言测试（负向守卫）：当敌人库缺少关卡依赖敌人时，必须具名阻断
	t.Run("MissingEnemyStrictRefusal", func(t *testing.T) {
		incompleteLib := &EnemyLibrary{ByKey: make(map[string]map[int]*EnemyStats)}
		for k, v := range enemyLib.ByKey {
			if k != "enemy_10263_dsjblk" {
				incompleteLib.ByKey[k] = v
			}
		}

		// TL-3 (act55side_03) 依赖 enemy_10263_dsjblk
		_, err := LoadStageFromPack(stagePackPath, "act55side_03", "NORMAL", incompleteLib)
		if err == nil {
			t.Fatalf("expected failure when enemy_10263_dsjblk is missing, but got success")
		}
		if !strings.Contains(err.Error(), "enemy_10263_dsjblk") {
			t.Fatalf("expected error to name missing enemy enemy_10263_dsjblk, got: %v", err)
		}
		t.Logf("Strict missing enemy refusal verified: %v", err)
	})

	// 4. 端到端短回合仿真验证：分别对 TL-1 与 TL-10 运行仿真，验证无 panic、无死锁
	t.Run("RunSimFromSqlitePack_TL1", func(t *testing.T) {
		spec, err := LoadStageFromPack(stagePackPath, "act55side_01", "NORMAL", enemyLib)
		if err != nil {
			t.Fatalf("LoadStageFromPack act55side_01 failed: %v", err)
		}
		spec.Life = 30
		spec.MaxTime = 30.0
		spec.Mechanisms = nil
		spec.MechConfig = nil

		verdict, err := runSim(spec)
		if err != nil {
			t.Fatalf("runSim with act55side_01 failed: %v", err)
		}
		if verdict == nil {
			t.Fatalf("expected non-nil verdict")
		}
		if verdict.SpawnsPlaced == 0 {
			t.Fatalf("expected SpawnsPlaced > 0, got 0")
		}
		t.Logf("TL-1 Simulation completed: SpawnsPlaced=%d, Events=%d, Won=%v",
			verdict.SpawnsPlaced, len(verdict.Events), verdict.Won)
	})

	t.Run("RunSimFromSqlitePack_TL10", func(t *testing.T) {
		spec, err := LoadStageFromPack(stagePackPath, "act55side_10", "NORMAL", enemyLib)
		if err != nil {
			t.Fatalf("LoadStageFromPack act55side_10 failed: %v", err)
		}
		spec.Life = 30
		spec.MaxTime = 30.0
		spec.Mechanisms = nil
		spec.MechConfig = nil

		verdict, err := runSim(spec)
		if err != nil {
			t.Fatalf("runSim with act55side_10 failed: %v", err)
		}
		if verdict == nil {
			t.Fatalf("expected non-nil verdict")
		}
		if verdict.SpawnsPlaced == 0 {
			t.Fatalf("expected SpawnsPlaced > 0, got 0")
		}
		t.Logf("TL-10 Simulation completed: SpawnsPlaced=%d, Events=%d, Won=%v",
			verdict.SpawnsPlaced, len(verdict.Events), verdict.Won)
	})

	t.Run("RunSimFromSqlitePack_TLEX1", func(t *testing.T) {
		spec, err := LoadStageFromPack(stagePackPath, "act55side_ex01", "NORMAL", enemyLib)
		if err != nil {
			t.Fatalf("LoadStageFromPack act55side_ex01 failed: %v", err)
		}
		spec.Life = 30
		spec.MaxTime = 30.0
		spec.Mechanisms = nil
		spec.MechConfig = nil

		verdict, err := runSim(spec)
		if err != nil {
			t.Fatalf("runSim with act55side_ex01 failed: %v", err)
		}
		if verdict == nil {
			t.Fatalf("expected non-nil verdict")
		}
		if verdict.SpawnsPlaced == 0 {
			t.Fatalf("expected SpawnsPlaced > 0, got 0")
		}
		t.Logf("TL-EX-1 Simulation completed: SpawnsPlaced=%d, Events=%d, Won=%v",
			verdict.SpawnsPlaced, len(verdict.Events), verdict.Won)
	})

	t.Run("RunSimFromSqlitePack_TLEX8", func(t *testing.T) {
		spec, err := LoadStageFromPack(stagePackPath, "act55side_ex08", "NORMAL", enemyLib)
		if err != nil {
			t.Fatalf("LoadStageFromPack act55side_ex08 failed: %v", err)
		}
		spec.Life = 30
		spec.MaxTime = 30.0
		spec.Mechanisms = nil
		spec.MechConfig = nil

		verdict, err := runSim(spec)
		if err != nil {
			t.Fatalf("runSim with act55side_ex08 failed: %v", err)
		}
		if verdict == nil {
			t.Fatalf("expected non-nil verdict")
		}
		if verdict.SpawnsPlaced == 0 {
			t.Fatalf("expected SpawnsPlaced > 0, got 0")
		}
		t.Logf("TL-EX-8 Simulation completed: SpawnsPlaced=%d, Events=%d, Won=%v",
			verdict.SpawnsPlaced, len(verdict.Events), verdict.Won)
	})

	// 5. 战壕地块（tile_trench）支持专项测试
	t.Run("TileTrenchProperties", func(t *testing.T) {
		st, err := LoadStageObjectFromPack(stagePackPath, "act55side_01", "NORMAL")
		if err != nil {
			t.Fatalf("LoadStageObjectFromPack(act55side_01) failed: %v", err)
		}

		trenchCount := 0
		for y := 0; y < st.Map.Height; y++ {
			for x := 0; x < st.Map.Width; x++ {
				tile := st.Map.Tiles[y][x]
				if tile.Key == "tile_trench" {
					trenchCount++
					// 必须支持地面干员部署
					if !tile.DeployableMelee() {
						t.Fatalf("tile_trench at (%d, %d) must be DeployableMelee", x, y)
					}
					// 必须支持敌人通行
					if !st.Map.Walkable(x, y) {
						t.Fatalf("tile_trench at (%d, %d) must be Walkable for enemies", x, y)
					}
				}
			}
		}
		if trenchCount == 0 {
			t.Fatalf("expected tile_trench in act55side_01, got 0")
		}
		t.Logf("Validated %d tile_trench tiles in TL-1: all DeployableMelee and Walkable", trenchCount)
	})

	// 6. TUI 顶层 LoadStage 查询与 StageOptions 恢复
	t.Run("LoadStageTUIQuery", func(t *testing.T) {
		for _, q := range []string{"act55side_01", "TL-1", "act55side_10", "TL-10", "act55side_ex01", "TL-EX-1", "act55side_ex08", "TL-EX-8"} {
			st, err := LoadStage(q)
			if err != nil {
				t.Fatalf("LoadStage(%q) failed: %v", q, err)
			}
			if st.Map.Width <= 0 || st.Map.Height <= 0 {
				t.Fatalf("[%s] invalid map dimensions: %dx%d", q, st.Map.Width, st.Map.Height)
			}
			if len(st.Routes) == 0 {
				t.Fatalf("[%s] expected non-empty routes, got 0", q)
			}
			if len(st.Spawns) == 0 {
				t.Fatalf("[%s] expected non-empty spawns, got 0", q)
			}
			t.Logf("LoadStage(%q) succeeded: Code=%s, LevelID=%s, Map=%dx%d, Spawns=%d",
				q, st.Code, st.LevelID, st.Map.Width, st.Map.Height, len(st.Spawns))
		}
	})
}
