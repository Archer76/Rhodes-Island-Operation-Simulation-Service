package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

func TestCountTemplatesUnknownBeforeBirthRefusesVerdict(t *testing.T) {
	for _, link := range []string{"reborn", "summon", "mark"} {
		s := deploymentPrimitiveSpec(1)
		s.Operators = []OperatorSpec{countSpeedUnit().spec}
		s.Spawns[0].CountVisibility = &CountVisibility{}
		template := &SpawnSpec{EnemyID: "unknown-hidden-template", Level: 2, RawSources: []EnemyRawSource{{Kind: "database_level", EnemyID: "unknown-hidden-template", Level: 2, Raw: json.RawMessage(`{"description":"unimplemented state witness"}`)}}}
		switch link {
		case "reborn":
			s.Spawns[0].RebornSummons = []RebornSummonSpec{{Template: template}}
		case "summon":
			s.Spawns[0].Summon = template
		case "mark":
			s.Spawns[0].Mark = template
		}
		v, err := runSim(s)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) {
			t.Fatal("future hidden template escaped count preflight", link)
		}
		found := false
		for _, g := range incomplete.Placeholders {
			if g.ID == "runtime.enemy_count_visibility" && g.SourceID == template.EnemyID {
				found = true
				if g.Level != 2 || g.Instance != 0 || g.Key == "" || len(g.RawSource) == 0 {
					t.Fatal("nested template gap lost source/path")
				}
			}
		}
		if !found {
			t.Fatal("template gap absent", link)
		}
		template.CountVisibility = &CountVisibility{}
		if got := countTimingGaps(s); len(got) != 0 {
			t.Fatal("explicit nested state rejected", got)
		}
		template.CountVisibility = nil
		s.Operators[0].EnemyCountAttackSpeed = nil
		if got := countTimingGaps(s); len(got) != 0 {
			t.Fatal("legacy templates require unused counting state")
		}
	}
}
func TestCountTemplatesFarmlandChildBeforeBirth(t *testing.T) {
	s := deploymentPrimitiveSpec(1)
	s.Operators = []OperatorSpec{countSpeedUnit().spec}
	s.Spawns[0].CountVisibility = &CountVisibility{}
	s.MechConfig = map[string]json.RawMessage{"huai_shu_li.farmland": json.RawMessage(`{"devices":[{"child":{"enemy_id":"future-pile","level":1,"count_visibility":{"hidden":false,"camouflage":false},"summon":{"enemy_id":"future-diver"}}}]}`)}
	gaps := countTimingGaps(s)
	if len(gaps) != 1 || gaps[0].SourceID != "future-diver" || gaps[0].Key != "mech_config.huai_shu_li.farmland.devices[0].child.summon" {
		t.Fatalf("config nested template unchecked %+v", gaps)
	}
	v, err := runSim(s)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatal("config template bypassed before mechanism init")
	}
	s.MechConfig["huai_shu_li.farmland"] = json.RawMessage(`{"devices":[{"child":false}]}`)
	gaps = countTimingGaps(s)
	if len(gaps) != 1 || gaps[0].ID != "runtime.enemy_count_template" {
		t.Fatal("unparseable known config ignored")
	}
	s.Operators[0].EnemyCountAttackSpeed = nil
	if len(countTimingGaps(s)) != 0 {
		t.Fatal("legacy config gained unused count guard")
	}
}
func TestCountTemplatesDeepPathAndCycleBound(t *testing.T) {
	root := SpawnSpec{CountVisibility: &CountVisibility{}}
	shared := &SpawnSpec{CountVisibility: &CountVisibility{}}
	missing := &SpawnSpec{EnemyID: "missing-deep"}
	root.Mark = shared
	root.Summon = shared
	shared.Mark = missing
	shared.Summon = shared
	s := &Spec{Operators: []OperatorSpec{countSpeedUnit().spec}, Spawns: []SpawnSpec{root}}
	gaps := countTimingGaps(s)
	if len(gaps) != 1 || gaps[0].SourceID != "missing-deep" || gaps[0].Key != "spawns[0].summon.mark" {
		t.Fatalf("cycle/shared nested scan %v", gaps)
	}
	// Direct Go cycle is scanned safely. It is not claimed as JSON serializable.
}
