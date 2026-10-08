package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"rios-sim/mechanisms"
	"testing"
)

func TestWangSourceTrainingSlotsAndRawEvidence(t *testing.T) {
	for elite := 0; elite <= 2; elite++ {
		for _, pot := range []int{1, 3, 5, 6} {
			for slot := 0; slot <= elite+1; slot++ {
				for _, sl := range []int{1, 7, 10} {
					t.Run(fmt.Sprintf("E%dP%dS%dL%d", elite, pot, slot, sl), func(t *testing.T) {
						st := &OperatorStats{CharID: wangCharID, Elite: elite, Level: 60, Potential: pot}
						spec, err := buildWangSourceSpec(st, slot, sl)
						if err != nil {
							t.Fatal(err)
						}
						selected := slot
						if selected == 0 {
							selected = 1
						}
						if spec.ConsumerImplemented || spec.Slot != selected || len(spec.Evidence) != 14 {
							t.Fatalf("source context/evidence: %+v", spec)
						}
						wantCnt := float64(4 + elite)
						if pot >= 3 {
							wantCnt++
						}
						var candidate struct {
							Blackboard []json.RawMessage `json:"blackboard"`
						}
						if err := json.Unmarshal(spec.Talents[0].Raw, &candidate); err != nil {
							t.Fatal(err)
						}
						var cnt float64
						for _, raw := range candidate.Blackboard {
							var b struct {
								Key   string  `json:"key"`
								Value float64 `json:"value"`
							}
							json.Unmarshal(raw, &b)
							if b.Key == "cnt" {
								cnt = b.Value
							}
						}
						if cnt != wantCnt {
							t.Fatalf("cnt=%v want=%v", cnt, wantCnt)
						}
						wantTalents := 1
						if elite == 2 {
							wantTalents = 2
						}
						if len(spec.Talents) != wantTalents {
							t.Fatal("locked talent selected")
						}
						blob, err := json.Marshal(spec)
						if err != nil {
							t.Fatal(err)
						}
						var decoded WangSourceSpec
						if err := json.Unmarshal(blob, &decoded); err != nil {
							t.Fatal(err)
						}
						for id, raw := range spec.Evidence {
							var a, b any
							json.Unmarshal(raw, &a)
							json.Unmarshal(decoded.Evidence[id], &b)
							aa, _ := json.Marshal(a)
							bb, _ := json.Marshal(b)
							if string(aa) != string(bb) {
								t.Fatalf("raw lost %s", id)
							}
						}
						sk, active, _, err := bindSkillAtLevelWithInputs(wangCharID, slot, sl, 100, 50, 0, 1000, 100, 1, "PHYSICAL", nil)
						if err != nil {
							t.Fatal(err)
						}
						if sk != nil || active != nil {
							t.Fatal("stone source claimed as owner buff")
						}
					})
				}
			}
		}
	}
	if s, err := buildWangSourceSpec(&OperatorStats{CharID: "char_123_not_wang"}, 1, 7); err != nil || s != nil {
		t.Fatal("other operator affected")
	}
	if _, err := buildWangSourceSpec(&OperatorStats{CharID: wangCharID, Elite: 0, Level: 1, Potential: 1}, 2, 7); err == nil {
		t.Fatal("locked slot accepted")
	}
	sk, active, _, err := bindSkillAtLevelWithInputs("char_4063_quartz", 1, 7, 100, 50, 0, 1000, 100, 1, "PHYSICAL", nil)
	if err != nil || sk == nil || active == nil {
		t.Fatalf("control skill affected: %v", err)
	}
}

func TestWangSourceModuleLevelsAndGaps(t *testing.T) {
	for ml := 1; ml <= 3; ml++ {
		for _, pot := range []int{1, 5} {
			st := &OperatorStats{CharID: wangCharID, Name: "望", Elite: 2, Level: 60, Potential: pot, Module: wangModuleID, ModuleLevel: ml}
			spec, err := buildWangSourceSpec(st, 3, 10)
			if err != nil {
				t.Fatal(err)
			}
			if spec.Module == nil || spec.Module.Level != ml {
				t.Fatal("module lost")
			}
			n := 0
			if ml > 1 {
				n = 1
			}
			if len(spec.ModuleCandidates) != n {
				t.Fatal("module talent selection")
			}
			if ml > 1 {
				var candidate struct {
					Blackboard []struct {
						Key   string  `json:"key"`
						Value float64 `json:"value"`
					} `json:"blackboard"`
				}
				json.Unmarshal(spec.ModuleCandidates[0], &candidate)
				want := float64(9 + ml)
				if pot >= 5 {
					want += 1
				}
				for _, b := range candidate.Blackboard {
					if b.Key == "attack@per_magic_resist_penetrate_fixed" && b.Value != want {
						t.Fatalf("module penetrate=%v want=%v", b.Value, want)
					}
				}
			}
			gaps, err := wangModuleMechanismGaps(st)
			if err != nil {
				t.Fatal(err)
			}
			seen := map[string]bool{}
			for _, g := range gaps {
				seen[g.ID] = true
				if len(g.RawSource) == 0 || len(g.RawSlot) == 0 {
					t.Fatal("module evidence missing")
				}
			}
			if !seen["module.token_attribute.cost"] || !seen["module.token_attribute.max_deploy_count"] || !seen["module.wang_non_panel"] {
				t.Fatal("module non-panel blind spot")
			}
		}
	}
}

func TestWangSourceRulingsAndUnclaimedMechanisms(t *testing.T) {
	st := &OperatorStats{CharID: wangCharID, Elite: 2, Level: 90, Potential: 1}
	spec, err := buildWangSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatal(err)
	}
	var level struct {
		RangeID string `json:"rangeId"`
	}
	json.Unmarshal(spec.TokenSkill.Raw, &level)
	if level.RangeID != "x-6" || spec.UserRulings["s3_damage"] != "thirteen-cell diamond" || spec.UserRulings["s2_damage"] != "seven-cell straight line or thirteen-cell cross" {
		t.Fatal("raw range conflated with user ruling")
	}
	meta, err := SkillMetaFor("skchr_wang_3", 10)
	if err != nil {
		t.Fatal(err)
	}
	selected, err := selectedSkillSource(meta, wangCharID, 3)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, g := range skillMechanismGaps(selected, wangCharID, "望", 3, "3-3") {
		seen[g.ID] = true
	}
	if !seen["skill.blackboard.atk_scale"] || !seen["skill.summon_entity"] {
		t.Fatal("S3 source wrongly claimed")
	}
	gaps, err := traitMechanismGaps(wangCharID, "望", 2, 90, 1)
	if err != nil {
		t.Fatal(err)
	}
	seen = map[string]bool{}
	for _, g := range gaps {
		seen[g.ID] = true
	}
	if !seen["trait.trap_placement"] {
		t.Fatal("placement trait invisible")
	}
	row := DeployRow{Skill: 3, SkillLevel: 7, Position: [2]int{3, 5}, Direction: "Right", Entry: LoadoutEntry{CharID: wangCharID, Elite: 2, Level: 90, Potential: 1}}
	out, err := buildOperatorOut(row, map[string]int{}, "")
	if err != nil {
		t.Fatal(err)
	}
	if out.WangSource == nil || out.Skill != nil || out.Active != nil || len(out.Placeholders) == 0 {
		t.Fatal("production source/gaps lost or ordinary buff remains")
	}
	blob, err := json.Marshal(out)
	if err != nil {
		t.Fatal(err)
	}
	var op OperatorSpec
	if err := json.Unmarshal(blob, &op); err != nil {
		t.Fatal(err)
	}
	if op.WangSource == nil || op.WangSource.ConsumerImplemented {
		t.Fatal("wire evidence lost")
	}
	battle := deploymentPrimitiveSpec(1)
	battle.Operators = []OperatorSpec{op}
	v, err := runSim(battle)
	var incomplete *mechanisms.IncompleteError
	if v != nil || !errors.As(err, &incomplete) {
		t.Fatalf("source spec falsely produced verdict: %v/%v", v, err)
	}
}
