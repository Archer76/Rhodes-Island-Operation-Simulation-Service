package main

import (
	"bytes"
	"encoding/json"
	"testing"
)

func TestEnemyRawSourcesRealHiddenDescriptionAndClone(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	st, err := lib.At("enemy_10031_cnvsld", 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(st.RawSources) == 0 {
		t.Fatal("real source missing")
	}
	last := st.RawSources[len(st.RawSources)-1]
	if last.Kind != "database_level" || last.EnemyID != st.EnemyID || last.Level != 0 {
		t.Fatal("source identity lost")
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(last.Raw, &raw); err != nil {
		t.Fatal(err)
	}
	description, ok := unwrapCell(raw["description"])
	if !ok || !bytes.Contains(description, []byte("隐匿")) {
		t.Fatalf("hidden real source not preserved %s", description)
	}
	original := append([]byte(nil), st.RawSources[0].Raw...)
	clone := st.Clone()
	clone.RawSources[0].Raw[0] = 'x'
	if !bytes.Equal(st.RawSources[0].Raw, original) {
		t.Fatal("clone mutated source cache")
	}
	t.Logf("real hidden source %s preserved %d source layers; no visibility inferred", st.EnemyID, len(st.RawSources))
}
func TestEnemyRawSourcesOrderedLevelsIndependent(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	var lower, higher *EnemyStats
	for _, levels := range lib.ByKey {
		for _, h := range levels {
			if len(h.RawSources) > 1 {
				higher = h
				lower = levels[h.RawSources[0].Level]
				break
			}
		}
		if higher != nil {
			break
		}
	}
	if higher == nil || lower == nil {
		t.Fatal("no real inherited levels exercised")
	}
	if len(lower.RawSources) != 1 {
		t.Fatal("earlier snapshot grew with later levels")
	}
	before := append([]byte(nil), lower.RawSources[0].Raw...)
	higher.RawSources[0].Raw[0] = 'x'
	if !bytes.Equal(lower.RawSources[0].Raw, before) {
		t.Fatal("higher source aliases lower")
	}
	higher.RawSources[0].Raw = append(json.RawMessage(nil), before...)
	for _, layer := range higher.RawSources {
		if layer.Kind != "database_level" || layer.EnemyID != higher.EnemyID || !json.Valid(layer.Raw) {
			t.Fatal("source layer identity/data invalid")
		}
	}
}
func TestEnemyRawSourcesStageOverwriteIndependent(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	base, err := lib.At("enemy_10031_cnvsld", 0)
	if err != nil {
		t.Fatal(err)
	}
	input := map[string]json.RawMessage{"prefabKey": json.RawMessage(`"enemy_10031_cnvsld"`), "description": json.RawMessage(`{"m_defined":true,"m_value":"local source evidence"}`)}
	out, err := lib.WithOverwrite("local-hidden-provenance", 0, input)
	if err != nil {
		t.Fatal(err)
	}
	if len(out.RawSources) != len(base.RawSources)+1 {
		t.Fatal("overwrite source missing")
	}
	last := out.RawSources[len(out.RawSources)-1]
	if last.Kind != "stage_overwrite" || last.EnemyID != "local-hidden-provenance" || !bytes.Contains(last.Raw, []byte("local source evidence")) {
		t.Fatal("override source identity lost")
	}
	input["description"][0] = 'x'
	if !json.Valid(last.Raw) {
		t.Fatal("input mutation aliased source")
	}
	out.RawSources[0].Raw[0] = 'x'
	if !json.Valid(base.RawSources[0].Raw) {
		t.Fatal("overwrite changed database cache")
	}
}
