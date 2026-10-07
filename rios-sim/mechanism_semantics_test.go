package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"strings"
	"testing"
)

func requireSemanticGap(t *testing.T, gaps []mechanisms.Gap, id, sourceID string) mechanisms.Gap {
	t.Helper()
	for _, g := range gaps {
		if g.ID == id && g.SourceID == sourceID {
			return g
		}
	}
	t.Fatalf("missing named source %s/%s: %+v", id, sourceID, gaps)
	return mechanisms.Gap{}
}

func realSemanticTalents(t *testing.T, id string, elite, potential int) []resolvedTalent {
	t.Helper()
	table, err := loadCharTable()
	if err != nil {
		t.Fatal(err)
	}
	var char struct {
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(table[id], &char); err != nil {
		t.Fatal(err)
	}
	return resolveTalents(char.Talents, elite, 1, potential)
}

func TestMechanismSemanticRealEmptyAndClaimedTalents(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, source string
		elite, pot   int
		key          string
	}{
		{"char_1035_wisdel", "talent:1:0", 2, 1, "tokenKey"},
		{"char_4230_mcnist", "talent:0:0", 1, 1, "tokenKey"},
		{"char_4230_mcnist", "talent:0:1", 2, 1, "tokenKey"},
		{"char_4215_buddy", "talent:0:0", 0, 1, "tokenKey"},
		{"char_4195_radian", "talent:1:0", 2, 1, "description"},
		{"char_4195_radian", "talent:1:1", 2, 5, "description"},
	} {
		t.Run(c.char+"/"+c.source, func(t *testing.T) {
			talents := realSemanticTalents(t, c.char, c.elite, c.pot)
			g := requireSemanticGap(t, talentMechanismGaps(talents, c.char, c.char), "talent.summon_entity", c.source)
			if g.Key != c.key || len(g.RawSource) == 0 {
				t.Fatalf("metadata lost: %+v", g)
			}
			var candidate map[string]any
			if err := json.Unmarshal(g.RawSource, &candidate); err != nil {
				t.Fatal(err)
			}
			if c.key == "tokenKey" && candidate["tokenKey"] != g.RawValue {
				t.Fatalf("token lost: %+v", g)
			}
			spec := Spec{Placeholders: []mechanisms.Gap{g}}
			v, err := runSim(&spec)
			var incomplete *mechanisms.IncompleteError
			if v != nil || !errors.As(err, &incomplete) {
				t.Fatalf("produced verdict: %v/%v", v, err)
			}
		})
	}
}

func TestMechanismSemanticRealSkills(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct{ id, gap string }{
		{"skchr_iana_1", "skill.form_switch"},
		{"skchr_akafyu_1", "skill.block_override"},
		{"skchr_akafyu_1", "skill.hit_count_override"},
		{"skchr_weedy_2", "skill.displacement"},
		{"skchr_rope_1", "skill.displacement"},
		{"skchr_f12yin_3", "skill.displacement"},
		{"skchr_ulpia_3", "skill.displacement"},
		{"skchr_f12yin_2", "skill.form_switch"},
		{"skchr_thorns_3", "skill.variant"},
	} {
		t.Run(c.id+"/"+c.gap, func(t *testing.T) {
			meta, err := SkillMetaFor(c.id, 7)
			if err != nil {
				t.Fatal(err)
			}
			g := requireSemanticGap(t, skillMechanismGaps(*meta, "char_test", "test", 2, ""), c.gap, c.id)
			if g.Slot != 2 || g.Level != 7 || len(g.RawSource) == 0 || g.Description != meta.RawDescription {
				t.Fatalf("lost training/source %+v", g)
			}
			if c.id == "skchr_weedy_2" && c.gap == "skill.displacement" {
				found := false
				for _, g := range skillMechanismGaps(*meta, "x", "x", 2, "") {
					if g.ID == c.gap && g.Key == "base_force_level" && g.RawValue == float64(0) {
						found = true
					}
				}
				if !found {
					t.Fatal("zero strength lost")
				}
			}
		})
	}
}

func TestMechanismSemanticPositiveControls(t *testing.T) {
	chdirRepoRootForData(t)
	for _, id := range []string{"skcom_atk_up[2]", "skchr_huang_1", "skchr_skadi_3", "skchr_midn_1"} {
		meta, err := SkillMetaFor(id, 7)
		if err != nil {
			t.Fatal(err)
		}
		if g := skillMechanismGaps(*meta, "x", "x", 1, ""); len(g) != 0 {
			t.Fatalf("complete skill %s blocked %+v", id, g)
		}
	}
	for _, desc := range []string{"召唤陨石对目标造成伤害", "攻击距离前移一格", "伤害类型变为法术", "优先攻击防御力最低的敌人"} {
		if g := semanticMechanismGaps("skill", "x", "x", "x", "x", desc, nil, nil, nil, "", "", 1, 7); len(g) != 0 {
			t.Fatalf("overbroad text guard %s: %+v", desc, g)
		}
	}
	// Force is recognized even when negative; numerical magnitude is not absence.
	g := semanticMechanismGaps("skill", "x", "x", "x", "x", "", map[string]any{"force": -1.0}, nil, nil, "", "", 1, 7)
	requireSemanticGap(t, g, "skill.displacement", "x")
}

func TestMechanismSemanticConditionalAndConsumerSources(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		char, source, id string
		elite            int
	}{
		{"char_497_ctable", "talent:0:0", "talent.conditional_panel", 1},
		{"char_4051_akkord", "talent:0:0", "talent.conditional_panel", 1},
		{"char_107_liskam", "talent:0:0", "talent.event_sp", 1},
		{"char_214_kafka", "talent:0:3", "talent.conditional_panel", 2},
		{"char_369_bena", "talent:0:3", "talent.form_switch", 2},
	} {
		ts := realSemanticTalents(t, c.char, c.elite, 1)
		requireSemanticGap(t, talentMechanismGaps(ts, c.char, c.char), c.id, c.source)
	}
	for _, c := range []struct {
		char  string
		elite int
	}{
		{"char_1051_headb2", 2}, {"char_332_archet", 2}, {"char_311_mudrok", 0}, {"char_1052_kalts2", 2}, {"char_208_melan", 1},
	} {
		ts := realSemanticTalents(t, c.char, c.elite, 1)
		for _, g := range talentMechanismGaps(ts, c.char, c.char) {
			if g.ID == "talent.conditional_panel" || g.ID == "talent.event_sp" {
				t.Fatalf("complete consumer misclaimed %s: %+v", c.char, g)
			}
		}
	}
	plain := talentMechanismGaps(realSemanticTalents(t, "char_208_melan", 1, 1), "char_208_melan", "玫兰莎")
	if len(plain) != 0 {
		t.Fatalf("ordinary exact panel blocked %+v", plain)
	}
	// A recognized aura cannot claim a different conditional field merely by name.
	aura := resolvedTalent{Name: tfTeamAuraName, RawDescription: "技能期间攻击力、防御力和最大生命提高", Blackboard: map[string]any{"atk": .1, "def": .1, "max_hp": .2}}
	requireSemanticGap(t, talentMechanismGaps([]resolvedTalent{aura}, "x", "x"), "talent.conditional_panel", "talent:0:0")
	for _, c := range []struct{ char, key string }{{"char_1035_wisdel", "attack@enable_third_attack"}, {"char_4226_veen", "merge_cnt"}} {
		g, err := traitMechanismGaps(c.char, c.char, 2, 1, 1)
		if err != nil {
			t.Fatal(err)
		}
		requireSemanticGap(t, g, "trait.blackboard."+c.key, "trait:0")
	}
}

func TestMechanismSemanticSlotTokenProduction(t *testing.T) {
	chdirRepoRootForData(t)
	for _, c := range []struct {
		slot  int
		token string
	}{{1, "token_10020_ling_soul1"}, {2, "token_10020_ling_soul2"}} {
		row := DeployRow{Skill: c.slot, SkillLevel: 7, Entry: LoadoutEntry{CharID: "char_2023_ling", Elite: 2, Level: 1, Potential: 1}}
		st, err := OperatorStatsFor(OperatorCalcConfig{CharID: row.Entry.CharID, Elite: 2, Level: 1, Potential: 1}, "round")
		if err != nil {
			t.Fatal(err)
		}
		gaps, err := operatorMechanismGaps(row, st, realSemanticTalents(t, row.Entry.CharID, 2, 1))
		if err != nil {
			t.Fatal(err)
		}
		found := false
		for _, g := range gaps {
			if g.ID == "skill.summon_entity" && g.Key == "overrideTokenKey" {
				if g.RawValue != c.token || g.Slot != c.slot || g.Level != 7 || len(g.RawSlot) == 0 {
					t.Fatalf("slot identity lost %+v", g)
				}
				blob, err := json.Marshal(g)
				if err != nil {
					t.Fatal(err)
				}
				var copy mechanisms.Gap
				if err := json.Unmarshal(blob, &copy); err != nil {
					t.Fatal(err)
				}
				var slot map[string]any
				if err := json.Unmarshal(copy.RawSlot, &slot); err != nil {
					t.Fatal(err)
				}
				if slot["overrideTokenKey"] != c.token {
					t.Fatalf("raw slot lost %+v", copy)
				}
				found = true
			}
		}
		if !found {
			t.Fatalf("slot %d missing token %+v", c.slot, gaps)
		}
	}
}

func TestMechanismSemanticTalentProduction(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, `[{"name":"维什戴尔","charId":"char_1035_wisdel","elite":2,"level":1,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"维什戴尔","position":[3,5],"direction":"Up","skill":1}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	g := requireSemanticGap(t, spec.Operators[0].Placeholders, "talent.summon_entity", "talent:1:0")
	if g.RawValue != "token_10035_wisdel_wward" || len(g.RawSource) == 0 || g.Instance != 0 {
		t.Fatalf("talent runtime provenance lost %+v", g)
	}
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("talent produced verdict %v/%v", v, err)
	}
}

func TestMechanismSemanticTraitSelectionAndProduction(t *testing.T) {
	chdirRepoRootForData(t)
	gaps, err := traitMechanismGaps("char_369_bena", "贝娜", 2, 1, 1)
	if err != nil {
		t.Fatal(err)
	}
	g := requireSemanticGap(t, gaps, "trait.form_switch", "trait:0")
	if !strings.Contains(g.Description, "<替身>") || len(g.RawBlackboard) == 0 || len(g.RawSource) == 0 {
		t.Fatalf("trait provenance lost %+v", g)
	}
	roster := writeTempRoster(t, `[{"name":"双月","charId":"char_4124_iana","elite":2,"level":1,"potential":1}]`)
	plan := json.RawMessage(`{"stage":"main_01-07","deploys":[{"operator":"双月","position":[3,5],"direction":"Up","skill":1}]}`)
	built, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{Plan: plan, Roster: json.RawMessage(`"` + strings.ReplaceAll(roster, `\`, `\\`) + `"`), AllowSkills: true})
	if err != nil {
		t.Fatal(err)
	}
	blob, err := json.Marshal(built.Spec)
	if err != nil {
		t.Fatal(err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		t.Fatal(err)
	}
	requireSemanticGap(t, spec.Placeholders, "skill.form_switch", "skchr_iana_1")
	requireSemanticGap(t, spec.Operators[0].Placeholders, "trait.form_switch", "trait:0")
	v, err := runSim(&spec)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("incomplete production verdict %v/%v", v, err)
	}
}
