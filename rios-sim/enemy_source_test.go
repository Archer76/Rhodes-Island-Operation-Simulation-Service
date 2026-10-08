package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"reflect"
	"rios-sim/mechanisms"
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
func equalSourceJSON(a, b []byte) bool {
	var x, y any
	if json.Unmarshal(a, &x) != nil || json.Unmarshal(b, &y) != nil {
		return false
	}
	return reflect.DeepEqual(x, y)
}
func TestEnemyRawSourcesProductionSpawnGapProvenance(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	es, err := lib.At("enemy_10031_cnvsld", 0)
	if err != nil {
		t.Fatal(err)
	}
	view := viewOf(es, es.EnemyID, 0, nil, nil, lib, false)
	source := append([]byte(nil), es.RawSources[0].Raw...)
	specMap := unitSpecOf(view, 0, nil)
	blob, err := json.Marshal(specMap)
	if err != nil {
		t.Fatal(err)
	}
	var spawn SpawnSpec
	if err := json.Unmarshal(blob, &spawn); err != nil {
		t.Fatal(err)
	}
	if len(spawn.RawSources) != len(es.RawSources) || !equalSourceJSON(spawn.RawSources[0].Raw, source) || spawn.CountVisibility != nil {
		t.Fatal("source lost or implicit visibility produced")
	}
	// Mutating each handoff must not alter the prior owner/template.
	view.RawSources[0].Raw[0] = 'x'
	if !bytes.Equal(es.RawSources[0].Raw, source) {
		t.Fatal("view changed source cache")
	}
	scene := deploymentPrimitiveSpec(1)
	scene.Operators = []OperatorSpec{countSpeedUnit().spec}
	scene.Spawns = []SpawnSpec{spawn}
	v, err := runSim(scene)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatal("real hidden unknown source not refused")
	}
	var found bool
	for _, g := range incomplete.Placeholders {
		if g.ID == "runtime.enemy_count_visibility" {
			found = true
			var layers []EnemyRawSource
			if g.SourceID != es.EnemyID || g.Level != 0 || json.Unmarshal(g.RawSource, &layers) != nil || len(layers) != len(es.RawSources) || !equalSourceJSON(layers[0].Raw, source) {
				t.Fatal("refusal lost real source provenance")
			}
		}
	}
	if !found {
		t.Fatal("enemy-specific gap absent")
	}
	ctx := &simCtx{spec: scene}
	a := newEnemy(spawn, 4, [2]float64{}, ctx)
	b := newEnemy(spawn, 5, [2]float64{}, nil)
	a.spec.RawSources[0].Raw[0] = 'x'
	if !equalSourceJSON(b.spec.RawSources[0].Raw, source) || !equalSourceJSON(spawn.RawSources[0].Raw, source) {
		t.Fatal("instance source aliases template")
	}
	if !errors.As(ctx.countError, &incomplete) || len(incomplete.Placeholders) != 1 {
		t.Fatal("runtime generated unknown not refused")
	}
	g := incomplete.Placeholders[0]
	var runtimeLayers []EnemyRawSource
	if g.SourceID != spawn.EnemyID || g.Level != spawn.Level || g.Instance != 4 || json.Unmarshal(g.RawSource, &runtimeLayers) != nil || len(runtimeLayers) != len(spawn.RawSources) || !equalSourceJSON(runtimeLayers[0].Raw, source) {
		t.Fatal("generated refusal lost source identity")
	}
	var realtimeIncomplete *mechanisms.IncompleteError
	_, err = countSpeedUnit().intervalForEnemies([]*enemy{b})
	if !errors.As(err, &realtimeIncomplete) || realtimeIncomplete.Placeholders[0].Instance != 5 || realtimeIncomplete.Placeholders[0].SourceID != spawn.EnemyID {
		t.Fatal("realtime missing visibility misattributed")
	}
	// The production map owns independent bytes, not the now-mutated view.
	mapSources := specMap["raw_sources"].([]EnemyRawSource)
	if !bytes.Equal(mapSources[0].Raw, source) {
		t.Fatal("unitSpec map aliases view")
	}
	mapSources[0].Raw[0] = 'x'
	if !bytes.Equal(es.RawSources[0].Raw, source) {
		t.Fatal("unitSpec map changed database")
	}
	var altered map[string]any
	if err := json.Unmarshal(source, &altered); err != nil {
		t.Fatal(err)
	}
	altered["description"] = "changed witness"
	changed, err := json.Marshal(altered)
	if err != nil || equalSourceJSON(changed, source) {
		t.Fatal("semantic comparator accepted altered source")
	}
	t.Log("real enemy source survives producer JSON, unknown preflight and generated-enemy refusals; no visibility inferred")
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
