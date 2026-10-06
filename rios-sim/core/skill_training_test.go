package core

import (
	"encoding/json"
	"testing"
)

func TestTrainingRosterAndPlanRoundTrip(t *testing.T) {
	for _, mastery := range []int{0, 1, 2, 3} {
		entry := RosterEntry{SkillLevel: trainingPtr(4), Mastery: map[string]int{"skill": mastery}}
		d := DeployOrder{Operator: "X"}
		level, m, err := ResolveSkillTraining(d, &entry, "skill")
		want := 4
		if mastery > 0 {
			want = 7 + mastery
		}
		if err != nil || level != want || m != mastery {
			t.Fatalf("level=%d m=%d err=%v", level, m, err)
		}
		d.SkillLevel, d.Mastery, d.MasterySet = &level, m, true
		blob, err := json.Marshal(d)
		if err != nil {
			t.Fatal(err)
		}
		var saved DeployOrder
		if err := json.Unmarshal(blob, &saved); err != nil {
			t.Fatal(err)
		}
		got, _, err := ResolveSkillTraining(saved, nil, "skill")
		if err != nil || got != want || !saved.MasterySet {
			t.Fatalf("saved=%s level=%d err=%v", blob, got, err)
		}
	}
	for _, raw := range []string{`{"mastery":0}`, `{}`} {
		var d DeployOrder
		if err := json.Unmarshal([]byte(raw), &d); err != nil {
			t.Fatal(err)
		}
		blob, _ := json.Marshal(d)
		var fields map[string]json.RawMessage
		json.Unmarshal(blob, &fields)
		_, has := fields["mastery"]
		if has != (raw != `{}`) {
			t.Fatalf("lost presence %s -> %s", raw, blob)
		}
	}
}
func trainingPtr(n int) *int { return &n }

func TestTrainingInvalidAndRosterConflict(t *testing.T) {
	entry := RosterEntry{SkillLevel: trainingPtr(5), Mastery: map[string]int{"skill": 3}}
	for _, d := range []DeployOrder{{Mastery: 0, MasterySet: true}, {Mastery: 1}, {Mastery: -1}, {Mastery: 4}, {SkillLevel: trainingPtr(7)}} {
		if _, _, err := ResolveSkillTraining(d, &entry, "skill"); err == nil {
			t.Fatalf("accepted %+v", d)
		}
	}
	for _, raw := range []string{`[{"name":"X","charId":"x","mainSkillLvl":0}]`, `[{"name":"X","charId":"x","mainSkillLvl":8}]`, `[{"name":"X","charId":"x","mainSkillLvl":3.5}]`, `[{"name":"X","charId":"x","mastery":{"s":4}}]`, `[{"name":"X","charId":"x","mastery":{"s":1.5}}]`} {
		if _, err := ParseRoster(json.RawMessage(raw)); err == nil {
			t.Fatalf("accepted %s", raw)
		}
	}
	rs, err := ParseRoster(json.RawMessage(`[{"name":"X","charId":"x","mainSkillLvl":5,"mastery":{"s":2}}]`))
	if err != nil || *rs.Entries[0].SkillLevel != 5 || rs.Entries[0].Mastery["s"] != 2 {
		t.Fatalf("lost roster %v %v", rs, err)
	}
	level, _, err := ResolveSkillTraining(DeployOrder{}, &RosterEntry{}, "s")
	if err != nil || level != 7 {
		t.Fatalf("default %d %v", level, err)
	}
}
