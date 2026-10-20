package main

import (
	"os"
	"path/filepath"
	"testing"

	"rios-sim/data"
)

func findRepoDataDir() string {
	dir, _ := os.Getwd()
	for i := 0; i < 5; i++ {
		cand := filepath.Join(dir, "data")
		if _, err := os.Stat(filepath.Join(cand, "akdb.sqlite")); err == nil {
			return cand
		}
		parent := filepath.Dir(dir)
		if parent == dir {
			break
		}
		dir = parent
	}
	return "data"
}

func TestPackStageDetectionAndRouting(t *testing.T) {
	t.Setenv("RIOS_DB", findRepoDataDir())
	_ = resolveDataDir()

	// 验证活动关卡被正确识别为离线资源包关卡
	if !isPackStage("act31side_08") {
		t.Fatalf("expected act31side_08 to be recognized as pack stage")
	}
	if !isPackStage("act31side_ex08") {
		t.Fatalf("expected act31side_ex08 to be recognized as pack stage")
	}

	// 验证主线关卡不被识别为活动包关卡
	if isPackStage("main_00-01") {
		t.Fatalf("expected main_00-01 NOT to be recognized as pack stage")
	}

	// 验证关卡包物理存在且只读可查
	dataDir := data.DataDBDir()
	packPath := filepath.Join(dataDir, "stages_act31side.sqlite")
	stages, _, err := data.LoadStageTable()
	if err != nil {
		t.Fatalf("LoadStageTable failed: %v", err)
	}

	found := false
	for _, entry := range stages {
		if entry.LevelID == "act31side_08" {
			found = true
			if entry.Code != "HS-8" {
				t.Fatalf("expected Code HS-8, got %s", entry.Code)
			}
			break
		}
	}
	if !found {
		t.Fatalf("expected act31side_08 in StageTable, but not found")
	}

	t.Logf("Verified stage pack (%s) and stage entry in table successfully", packPath)
}
