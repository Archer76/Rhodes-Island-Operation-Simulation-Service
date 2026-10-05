package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"reflect"
	"sync"
	"testing"
)

func TestBuildInputsLibrarySinglePublicationAndNextRequest(t *testing.T) {
	root := t.TempDir()
	dir := filepath.Join(root, "map.ark-nights.com", "levels", "enemydata")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "enemy_database.json")
	write := func(key string) {
		t.Helper()
		if err := os.WriteFile(path, []byte(`{"enemies":[{"Key":"`+key+`","Value":[{"level":0,"enemyData":{"name":{"m_defined":true,"m_value":"test"},"attributes":{}}}]}]}`), 0644); err != nil {
			t.Fatal(err)
		}
	}
	t.Setenv("RIOS_DATA", root)
	write("old")
	inputs := newBuildInputs("", "", "")
	const n = 16
	libs := make([]*EnemyLibrary, n)
	errs := make([]error, n)
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) { defer wg.Done(); libs[i], errs[i] = inputs.enemies() }(i)
	}
	wg.Wait()
	for i := 0; i < n; i++ {
		if errs[i] != nil || libs[i] != libs[0] {
			t.Fatalf("not single publication %d: %v", i, errs[i])
		}
	}
	write("new")
	same, err := inputs.enemies()
	if err != nil || same != libs[0] || same.ByKey["old"] == nil {
		t.Fatal("snapshot changed mid request")
	}
	next, err := newBuildInputs("", "", "").enemies()
	if err != nil || next.ByKey["new"] == nil || next.ByKey["old"] != nil {
		t.Fatalf("next request stale: %v", err)
	}
}

func TestBuildInputsPreservesLoaderError(t *testing.T) {
	t.Setenv("RIOS_DATA", t.TempDir())
	inputs := newBuildInputs("missing", "", "")
	for i := 0; i < 2; i++ {
		lib, err := inputs.enemies()
		if lib != nil || err == nil {
			t.Fatalf("library error lost: %v %v", lib, err)
		}
		st, _, err := inputs.stageData()
		if st != nil || err == nil {
			t.Fatalf("stage error lost: %v %v", st, err)
		}
		st, err = inputs.gateData()
		if st != nil || err == nil {
			t.Fatalf("gate error lost: %v %v", st, err)
		}
	}
}

func TestBuildInputsCacheKeysAndConsumerIsolation(t *testing.T) {
	chdirRepoRootForData(t)
	inputs := newBuildInputs("main_01-07", "", "")
	cfg := OperatorCalcConfig{CharID: "char_208_melan", Elite: 1, Level: 55, Potential: 6}
	a, err := inputs.operatorStats(cfg)
	if err != nil {
		t.Fatal(err)
	}
	b, err := inputs.operatorStats(cfg)
	if err != nil || a != b {
		t.Fatal("same config not reused")
	}
	cfg.Level = 1
	c, err := inputs.operatorStats(cfg)
	if err != nil || c == a || reflect.DeepEqual(c.Total, a.Total) {
		t.Fatal("config key mixed levels")
	}
	sk, err := inputs.skillMeta("skcom_atk_up[1]", 7)
	if err != nil {
		t.Fatal(err)
	}
	sk2, err := inputs.skillMeta("skcom_atk_up[1]", 7)
	if err != nil || sk != sk2 {
		t.Fatal("skill not reused")
	}
	sk3, err := inputs.skillMeta("skcom_atk_up[1]", 1)
	if err != nil || sk == sk3 {
		t.Fatal("skill level mixed")
	}
	roster := json.RawMessage(`[{"name":"玫兰莎","charId":"char_208_melan","elite":1,"level":55,"potential":6}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"玫兰莎","position":[3,5],"direction":"Up"}]}`)
	q := BuildSpecQuery{Plan: plan, Roster: roster, inputs: inputs}
	st, raw, err := inputs.stageData()
	if err != nil {
		t.Fatal(err)
	}
	lib, err := inputs.enemies()
	if err != nil {
		t.Fatal(err)
	}
	before, _ := json.Marshal([]any{st, raw, lib, a, sk})
	first, err := BuildSpecFull("main_01-07", "", q)
	if err != nil {
		t.Fatal(err)
	}
	blob, _ := json.Marshal(first.Spec)
	var runtimeSpec Spec
	if err := json.Unmarshal(blob, &runtimeSpec); err != nil {
		t.Fatal(err)
	}
	if _, err := runSim(&runtimeSpec); err != nil {
		t.Fatal(err)
	}
	// Runtime owns the decoded object. Mutating it cannot mutate request inputs.
	runtimeSpec.Operators[0].ATK = 999999
	second, err := BuildSpecFull("main_01-07", "", q)
	if err != nil {
		t.Fatal(err)
	}
	blob2, _ := json.Marshal(second.Spec)
	if string(blob) != string(blob2) {
		t.Fatal("repeated plan changed spec")
	}
	after, _ := json.Marshal([]any{st, raw, lib, a, sk})
	if string(before) != string(after) {
		t.Fatal("shared immutable input mutated")
	}
	first.Spec.Operators[0].TalentPanelMods["atk"] = 999
	third, err := BuildSpecFull("main_01-07", "", q)
	if err != nil {
		t.Fatal(err)
	}
	if third.Spec.Operators[0].TalentPanelMods["atk"] == 999 {
		t.Fatal("output map polluted cached stats")
	}
	const builders = 8
	outputs := make([][]byte, builders)
	buildErrs := make([]error, builders)
	var group sync.WaitGroup
	for i := 0; i < builders; i++ {
		group.Add(1)
		go func(i int) {
			defer group.Done()
			out, err := BuildSpecFull("main_01-07", "", q)
			if err != nil {
				buildErrs[i] = err
				return
			}
			outputs[i], buildErrs[i] = json.Marshal(out.Spec)
		}(i)
	}
	group.Wait()
	for i := 0; i < builders; i++ {
		if buildErrs[i] != nil || string(outputs[i]) != string(blob) {
			t.Fatalf("concurrent build %d changed output: %v", i, buildErrs[i])
		}
	}
	meta := SkillMeta{SkillID: "probe", Blackboard: map[string]any{"unknown": 1.0}, RawBlackboard: []json.RawMessage{json.RawMessage(`{"key":"unknown","value":1}`)}}
	gaps := skillMechanismGaps(meta, "x", "X", 1, "1-1")
	gaps[0].RawBlackboard[0][0] = '!'
	gaps[0].RawBlackboard[0] = json.RawMessage(`null`)
	again := skillMechanismGaps(meta, "x", "X", 1, "1-1")
	if string(again[0].RawBlackboard[0]) != `{"key":"unknown","value":1}` {
		t.Fatal("output gap bytes polluted meta")
	}
}
