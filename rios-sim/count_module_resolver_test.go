package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestCountModuleExactUpgradeSelectionAndInventory(t *testing.T) {
	chdirRepoRootForData(t)
	for _, owner := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		for _, ml := range []int{2, 3} {
			for _, pot := range []int{1, 4, 5, 6} {
				st := &OperatorStats{CharID: owner.char, Module: owner.module, ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot}
				picked, e := resolveExactCountModuleTalent(st)
				if e != nil || picked == nil {
					t.Fatal("exact upgrade not selected", e)
				}
				ci := 0
				if owner.char == "char_4010_etlchi" && pot >= 5 {
					ci = 1
				}
				if picked.CandidateIndex != ci || picked.PartIndex != 1 || picked.TalentIndex != 0 || picked.UpgradeDescription == "" || len(picked.RawCandidate) == 0 || len(picked.RawPart) == 0 {
					t.Fatal("wrong selection/provenance")
				}
				expected := map[string]float64{}
				if owner.char == "char_4182_oblvns" {
					def, res := .04, .02
					if ml == 3 {
						def, res = .05, .025
					}
					expected = map[string]float64{"def_penetrate_ratio": def, "magic_resist_penetrate_ratio": res, "attack@angle": 20, "delay": 1, "max_cnt": 12}
					if !strings.Contains(picked.UpgradeDescription, "技能期间远程攻击不再降低攻击力") {
						t.Fatal("upgrade-only description lost")
					}
				} else {
					steal, cap, magic, ratio, dur := 100.0, 1800.0, 350.0, .025, 5.0
					if ml == 3 {
						steal, cap, magic, ratio, dur = 120, 2160, 450, .035, 6
					}
					if ci == 1 {
						magic += 50
					}
					expected = map[string]float64{"attack@steal_hp": steal, "attack@steal_hp_max": cap, "magic_value": magic, "hp_recovery_per_sec_by_max_hp_ratio": ratio, "interval": 1, "dot_duration": dur}
				}
				if len(picked.Blackboard) != len(expected) {
					t.Fatal("unexpected selected BB")
				}
				for k, v := range expected {
					if bbValue(picked.Blackboard, k, -1) != v {
						t.Fatalf("%s ml%d pot%d %s wrong", owner.char, ml, pot, k)
					}
				}
				gaps, e := countCharacterModuleGaps(st)
				if e != nil {
					t.Fatal(e)
				}
				want := 2
				if owner.char == "char_4010_etlchi" && pot < 5 {
					want = 1
				}
				if len(gaps) != want {
					t.Fatal("selection erased eligible inventory")
				}
				st.Potential = 0
				if p, e := resolveExactCountModuleTalent(st); e != nil || p != nil {
					t.Fatal("invalid potential authorized")
				}
				st.Potential = pot
				st.Level = 59
				if p, e := resolveExactCountModuleTalent(st); e != nil || p != nil {
					t.Fatal("locked source authorized")
				}
			}
		}
	}
}
func TestCountModuleExactUpgradeMutationsRefused(t *testing.T) {
	chdirRepoRootForData(t)
	for _, owner := range []struct{ char, module string }{{"char_4182_oblvns", "uniequip_002_oblvns"}, {"char_4010_etlchi", "uniequip_003_etlchi"}} {
		for _, ml := range []int{2, 3} {
			st := &OperatorStats{CharID: owner.char, Module: owner.module, ModuleLevel: ml, Elite: 2, Level: 60, Potential: 5}
			parts, e := moduleParts(owner.module, ml)
			if e != nil {
				t.Fatal(e)
			}
			// Full source mutation, not a new eligibility rule inferred from a loose BB.
			var part map[string]any
			if e = json.Unmarshal(parts[1], &part); e != nil {
				t.Fatal(e)
			}
			part["isToken"] = true
			bad, e := json.Marshal(part)
			if e != nil {
				t.Fatal(e)
			}
			if p, e := resolveExactCountModuleTalentPart(st, bad); e != nil || p != nil {
				t.Fatal("mutated complete part accepted")
			}
			st.CharID = "wrong"
			if p, e := resolveExactCountModuleTalentPart(st, parts[1]); e != nil || p != nil {
				t.Fatal("wrong owner accepted")
			}
		}
	}
}
