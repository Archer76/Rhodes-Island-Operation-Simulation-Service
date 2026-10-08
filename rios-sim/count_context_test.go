package main

import (
	"encoding/json"
	"testing"
)

func TestCountJSONRawContextPresence(t *testing.T) {
	base := `{"range":[],"enemy_count_attack_speed":{"scope":"current","minimum":2,"bonus":12},"attack_timing":{"base_attack_time":1,"aspd":0}}`
	for _, raw := range []string{base, `{"range":[],"enemy_count_attack_speed":{"scope":"base","minimum":2,"bonus":12},"attack_timing":{"base_attack_time":1,"aspd":-5},"active":{"attack_timing":{"base_attack_time":0.7,"aspd":0}}}`} {
		var op OperatorSpec
		if err := json.Unmarshal([]byte(raw), &op); err != nil {
			t.Fatal("explicit zero/negative ASPD or empty range rejected", err)
		}
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal([]byte(base), &fields); err != nil {
		t.Fatal(err)
	}
	for _, mutate := range []func(map[string]json.RawMessage){func(f map[string]json.RawMessage) { delete(f, "range") }, func(f map[string]json.RawMessage) { f["range"] = json.RawMessage(`null`) }, func(f map[string]json.RawMessage) { f["attack_timing"] = json.RawMessage(`{"base_attack_time":1}`) }, func(f map[string]json.RawMessage) { f["attack_timing"] = json.RawMessage(`{"aspd":100}`) }, func(f map[string]json.RawMessage) {
		f["attack_timing"] = json.RawMessage(`{"base_attack_time":1,"aspd":null}`)
	}, func(f map[string]json.RawMessage) {
		f["active"] = json.RawMessage(`{"attack_timing":{"base_attack_time":1}}`)
	}} {
		f := map[string]json.RawMessage{}
		for k, v := range fields {
			f[k] = v
		}
		mutate(f)
		raw, err := json.Marshal(f)
		if err != nil {
			t.Fatal(err)
		}
		var op OperatorSpec
		if err := json.Unmarshal(raw, &op); err == nil {
			t.Fatal("missing raw count context accepted", string(raw))
		}
	}
	legacyMerge := OperatorSpec{Name: "kept", ATK: 123}
	if err := json.Unmarshal([]byte(`{"max_hp":500}`), &legacyMerge); err != nil || legacyMerge.Name != "kept" || legacyMerge.ATK != 123 || legacyMerge.MaxHP != 500 {
		t.Fatal("legacy partial decode reset previous values")
	}
	if err := json.Unmarshal([]byte(`null`), &legacyMerge); err != nil || legacyMerge.Name != "kept" {
		t.Fatal("legacy null reset object")
	}
	var legacy OperatorSpec
	if err := json.Unmarshal([]byte(`{"attack_timing":{"base_attack_time":1}}`), &legacy); err != nil {
		t.Fatal("legacy raw protocol changed", err)
	}
}
