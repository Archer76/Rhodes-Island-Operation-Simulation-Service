package main

import (
	"encoding/json"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestSqliteResourcePackFullValidation(t *testing.T) {
	chdirRepoRootForData(t)

	dbRoot := "D:\\home\\DSH\\ak-tactic\\data"
	enemyDBPath := filepath.Join(dbRoot, "enemydb_pure.sqlite")
	stagePackPath := filepath.Join(dbRoot, "stages_act31side.sqlite")

	// 1. 测试纯中央敌人库加载
	enemyLib, err := LoadPureEnemyLibrary(enemyDBPath)
	if err != nil {
		t.Fatalf("LoadPureEnemyLibrary failed: %v", err)
	}
	if len(enemyLib.ByKey) < 2000 {
		t.Fatalf("expected >= 2000 enemies in pure db, got %d", len(enemyLib.ByKey))
	}
	t.Logf("Loaded %d enemies from %s", len(enemyLib.ByKey), enemyDBPath)

	// 验证怀黍离核心怪均已收录
	for _, eID := range []string{"enemy_1390_dhsbr", "enemy_1396_dhdts", "enemy_1397_dhtsxt", "enemy_1399_dhtb", "enemy_1550_dhnzzh"} {
		if len(enemyLib.ByKey[eID]) == 0 {
			t.Fatalf("expected enemy %s in enemyLib, but not found", eID)
		}
	}

	// 2. 验证怀黍离关卡包全部 36 个关卡档位装配
	for _, item := range allHuaiShuLiStages {
		t.Run("Pack_"+item.Code+"_"+item.Difficulty, func(t *testing.T) {
			spec, err := LoadStageFromPack(stagePackPath, item.ID, item.Difficulty, enemyLib)
			if err != nil {
				t.Fatalf("LoadStageFromPack failed for %s (%s): %v", item.Code, item.Difficulty, err)
			}
			if spec.Life <= 0 {
				t.Fatalf("[%s] expected positive Life, got %d", item.Code, spec.Life)
			}
			if len(spec.Spawns) == 0 && item.Code != "HS-TR-1" && item.Code != "HS-TR-2" {
				t.Fatalf("[%s] expected non-empty spawns from pack, got 0", item.Code)
			}
			t.Logf("[%s %s] Loaded from SQLite: Spawns=%d, Life=%d, CostInit=%.0f",
				item.Code, item.Difficulty, len(spec.Spawns), spec.Life, spec.CostInit)
		})
	}

	// 3. 严格依赖断言测试（负向守卫）：当敌人库缺失关卡依赖的敌人时，必须具名阻断
	t.Run("MissingEnemyStrictRefusal", func(t *testing.T) {
		// 构造一个故意缺少 enemy_1399_dhtb 的敌人库副本
		incompleteLib := &EnemyLibrary{ByKey: make(map[string]map[int]*EnemyStats)}
		for k, v := range enemyLib.ByKey {
			if k != "enemy_1399_dhtb" {
				incompleteLib.ByKey[k] = v
			}
		}

		// HS-9 依赖天桩-乙 (enemy_1399_dhtb)
		_, err := LoadStageFromPack(stagePackPath, "act31side_09", "NORMAL", incompleteLib)
		if err == nil {
			t.Fatalf("expected failure when enemy_1399_dhtb is missing, but got success")
		}
		if !strings.Contains(err.Error(), "enemy_1399_dhtb") {
			t.Fatalf("expected error to name missing enemy enemy_1399_dhtb, got: %v", err)
		}
		t.Logf("Strict missing enemy refusal verified: %v", err)
	})

	// 4. 端到端仿真验证：直接使用关卡包生成的 Spec 驱动 runSim
	t.Run("RunSimFromSqlitePack", func(t *testing.T) {
		spec, err := LoadStageFromPack(stagePackPath, "act31side_08", "NORMAL", enemyLib)
		if err != nil {
			t.Fatalf("LoadStageFromPack act31side_08 failed: %v", err)
		}
		spec.Life = 30
		spec.MaxTime = 30.0
		// 基础战斗模拟时验证出怪与时序推进
		spec.Mechanisms = nil
		spec.MechConfig = nil

		verdict, err := runSim(spec)
		if err != nil {
			t.Fatalf("runSim with sqlite pack spec failed: %v", err)
		}
		if verdict == nil {
			t.Fatalf("expected non-nil verdict")
		}
		t.Logf("Simulation from SQLite pack completed: SpawnsPlaced=%d, Events=%d, Won=%v",
			verdict.SpawnsPlaced, len(verdict.Events), verdict.Won)
		if verdict.SpawnsPlaced == 0 {
			t.Fatalf("expected SpawnsPlaced > 0, got 0")
		}
	})
}

// TestStageLoadFromPackForTUI 验证 TUI 发起 load 关卡查询时，能直接由 SQLite 资源包命中并返回完整的 StageOptions 和地图路线
func TestStageLoadFromPackForTUI(t *testing.T) {
	chdirRepoRootForData(t)

	// 测试直接查询关卡 ID
	st, err := LoadStage("act31side_08")
	if err != nil {
		t.Fatalf("LoadStage(act31side_08) failed: %v", err)
	}

	if st.LevelID != "act31side_08" {
		t.Fatalf("expected LevelID act31side_08, got %s", st.LevelID)
	}
	if st.Code != "HS-8" {
		t.Fatalf("expected Code HS-8, got %s", st.Code)
	}
	if st.Options.CharacterLimit <= 0 {
		t.Fatalf("expected positive CharacterLimit, got %d", st.Options.CharacterLimit)
	}
	if st.Map.Width <= 0 || st.Map.Height <= 0 || len(st.Map.Tiles) != st.Map.Height {
		t.Fatalf("invalid map dimensions: %dx%d (tiles rows=%d)", st.Map.Width, st.Map.Height, len(st.Map.Tiles))
	}
	if len(st.Routes) == 0 {
		t.Fatalf("expected non-empty routes, got 0")
	}
	if len(st.Spawns) == 0 {
		t.Fatalf("expected non-empty spawns, got 0")
	}

	t.Logf("LoadStage successfully recovered stage from pack: %s (%s), deployLimit=%d, tiles=%dx%d, routes=%d, spawns=%d",
		st.Code, st.LevelID, st.Options.CharacterLimit, st.Map.Width, st.Map.Height, len(st.Routes), len(st.Spawns))

	// 测试模拟 TUI 协议层的 handle {"cmd": "load", "level": "act31side_08"}
	reqJSON := `{"id": 101, "cmd": "load", "level": "act31side_08"}`
	var req request
	if err := json.Unmarshal([]byte(reqJSON), &req); err != nil {
		t.Fatalf("unmarshal request failed: %v", err)
	}

	resp := handle(&req, time.Now().Format(time.RFC3339))
	if !resp.OK {
		t.Fatalf("handle(load) failed: %s", resp.Error)
	}
	if len(resp.Stage) == 0 {
		t.Fatalf("handle(load) returned empty stage payload")
	}

	var respStage struct {
		Options struct {
			CharacterLimit int `json:"character_limit"`
			MaxLifePoint   int `json:"max_life_point"`
		} `json:"options"`
	}
	if err := json.Unmarshal(resp.Stage, &respStage); err != nil {
		t.Fatalf("unmarshal resp.Stage failed: %v", err)
	}
	if respStage.Options.CharacterLimit != st.Options.CharacterLimit {
		t.Fatalf("character_limit mismatch: resp=%d, st=%d",
			respStage.Options.CharacterLimit, st.Options.CharacterLimit)
	}

	t.Logf("TUI protocol load test verified: CharacterLimit=%d, MaxLifePoint=%d",
		respStage.Options.CharacterLimit, respStage.Options.MaxLifePoint)
}

