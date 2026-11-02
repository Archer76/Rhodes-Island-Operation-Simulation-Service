package main

import (
	"testing"
)

func TestLoadStageHS8Smoke(t *testing.T) {
	st, err := LoadStage("act31side_08")
	if err != nil {
		t.Fatalf("LoadStage(act31side_08) failed: %v", err)
	}
	if st.LevelID != "activities/act31side/level_act31side_08" && st.Code != "HS-8" && st.LevelID != "act31side_08" {
		t.Logf("Loaded stage levelID=%s code=%s", st.LevelID, st.Code)
	}
	if st.Map.Width != 13 || st.Map.Height != 9 {
		t.Fatalf("expected 13x9 map, got %dx%d", st.Map.Width, st.Map.Height)
	}
	t.Logf("HS-8 Map loaded successfully: %dx%d, spawns=%d", st.Map.Width, st.Map.Height, len(st.Spawns))
}
