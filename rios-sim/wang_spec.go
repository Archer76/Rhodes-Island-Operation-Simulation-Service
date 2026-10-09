package main

// WangSourceSpec is evidence, not a battle consumer. Raw ranges and user rulings
// deliberately occupy different fields. Producing this object never claims gaps.
import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"rios-sim/mechanisms"
)

const wangCharID = "char_2027_wang"
const wangTokenID = "token_10064_wang_stone1"
const wangModuleID = "uniequip_002_wang"

type WangSourceLevel struct {
	ID    string          `json:"id"`
	Level int             `json:"level"`
	Raw   json.RawMessage `json:"raw"`
}
type WangTalentSource struct {
	Group     int             `json:"group"`
	Candidate int             `json:"candidate"`
	Raw       json.RawMessage `json:"raw"`
}
type WangSourceSpec struct {
	ConsumerImplemented bool               `json:"consumer_implemented"`
	Elite               int                `json:"elite"`
	Level               int                `json:"level"`
	Potential           int                `json:"potential"`
	Slot                int                `json:"slot"`
	SkillLevel          int                `json:"skill_level"`
	Talents             []WangTalentSource `json:"talents"`
	OperatorSkill       WangSourceLevel    `json:"operator_skill"`
	TokenSkill          WangSourceLevel    `json:"token_skill"`
	RawSlot             json.RawMessage    `json:"raw_slot"`
	Module              *WangSourceLevel   `json:"module,omitempty"`
	ModuleCandidates    []json.RawMessage  `json:"module_candidates,omitempty"`
	// Includes all talent candidates, all skill levels, token phases/skills and
	// module phases, so locked evidence remains distinguishable from selected data.
	Evidence    map[string]json.RawMessage `json:"evidence"`
	UserRulings map[string]string          `json:"user_rulings"`
	Unresolved  []string                   `json:"unresolved"`
}

func wangRawRecords(table string, ids ...string) (map[string]json.RawMessage, error) {
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel", table+".json"))
	if err != nil {
		return nil, err
	}
	var records map[string]json.RawMessage
	if err := json.Unmarshal(blob, &records); err != nil {
		return nil, err
	}
	out := make(map[string]json.RawMessage, len(ids))
	for _, id := range ids {
		raw, ok := records[id]
		if !ok || string(raw) == "null" {
			return nil, fmt.Errorf("wang source: %s missing %s", table, id)
		}
		out[id] = append(json.RawMessage(nil), raw...)
	}
	return out, nil
}

func wangSourceLevel(id string, level int, raw json.RawMessage, field string) (WangSourceLevel, error) {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return WangSourceLevel{}, err
	}
	var rows []json.RawMessage
	if err := json.Unmarshal(fields[field], &rows); err != nil {
		return WangSourceLevel{}, err
	}
	if level < 1 || level > len(rows) {
		return WangSourceLevel{}, fmt.Errorf("wang source: %s %s level %d unavailable", id, field, level)
	}
	return WangSourceLevel{ID: id, Level: level, Raw: append(json.RawMessage(nil), rows[level-1]...)}, nil
}

func buildWangSourceSpec(st *OperatorStats, slot, skillLevel int) (*WangSourceSpec, error) {
	if st.CharID != wangCharID {
		return nil, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot < 1 || slot > 3 || st.Elite < 0 || st.Elite > 2 || st.Level < 1 || st.Potential < 1 || st.Potential > 6 {
		return nil, fmt.Errorf("wang source: invalid training or slot")
	}
	if slot > st.Elite+1 {
		return nil, fmt.Errorf("wang source: slot %d locked at E%d", slot, st.Elite)
	}
	chars, err := wangRawRecords("character_table", wangCharID, wangTokenID)
	if err != nil {
		return nil, err
	}
	ids := []string{"skchr_wang_1", "skchr_wang_2", "skchr_wang_3", "sktok_wang_1", "sktok_wang_2", "sktok_wang_3"}
	skills, err := wangRawRecords("skill_table", ids...)
	if err != nil {
		return nil, err
	}
	modules, err := wangRawRecords("battle_equip_table", wangModuleID)
	if err != nil {
		return nil, err
	}
	var char struct {
		Talents []json.RawMessage `json:"talents"`
		Skills  []json.RawMessage `json:"skills"`
	}
	if err := json.Unmarshal(chars[wangCharID], &char); err != nil {
		return nil, err
	}
	if len(char.Skills) != 3 {
		return nil, fmt.Errorf("wang source: expected three raw skill slots")
	}
	ranges, err := wangRawRecords("range_table", "0-1", "3-1", "3-3", "4-12", "x-6")
	if err != nil {
		return nil, err
	}
	out := &WangSourceSpec{Elite: st.Elite, Level: st.Level, Potential: st.Potential, Slot: slot, SkillLevel: skillLevel, RawSlot: char.Skills[slot-1], Evidence: map[string]json.RawMessage{},
		UserRulings: map[string]string{
			"activation":         "orthogonal adjacency only; diagonal and empty gaps do not activate",
			"line_talent":        "longest remaining continuous straight line including self, capped at three; crossed lines never union",
			"s1_tick_assumption": "Doctor authorized provisional instant first tick, then once per second; first tick awaits measurement",
			"s2_cross_center":    "one damage application per enemy, center not doubled",
			"s3_end":             "inventory zero or ammo zero or manual stop ends; remaining ammo returns to inventory capped at maximum",
			"s3_ammo":            "manual stones and successful extra stones consume ammo; failed placement consumes none; up to four extras (three skill plus one talent)",
			"trigger_count":      "one stone each time",
			"s1_trigger":         "enemy steps on stone cell",
			"s2_trigger":         "enemy steps on stone cell",
			"s2_damage":          "seven-cell straight line or thirteen-cell cross",
			"s3_trigger":         "enemy enters stone trigger range",
			"s3_damage":          "thirteen-cell diamond",
		}, Unresolved: []string{"s1 damage geometry pending verification", "event timing not established by raw source", "runtime consumers not implemented"}}
	for _, records := range []map[string]json.RawMessage{chars, skills, modules, ranges} {
		for id, raw := range records {
			out.Evidence[id] = raw
		}
	}
	for _, t := range resolveTalents(char.Talents, st.Elite, st.Level, st.Potential) {
		out.Talents = append(out.Talents, WangTalentSource{Group: t.GroupIndex, Candidate: t.CandidateIndex, Raw: t.RawSource})
	}
	out.OperatorSkill, err = wangSourceLevel(ids[slot-1], skillLevel, skills[ids[slot-1]], "levels")
	if err != nil {
		return nil, err
	}
	out.TokenSkill, err = wangSourceLevel(ids[slot+2], skillLevel, skills[ids[slot+2]], "levels")
	if err != nil {
		return nil, err
	}
	if st.Module != "" && st.ModuleLevel > 0 {
		if st.Module != wangModuleID || st.ModuleLevel > 3 || st.Elite != 2 || st.Level < 60 {
			return nil, fmt.Errorf("wang source: module %s level %d locked or unsupported", st.Module, st.ModuleLevel)
		}
		selected, err := wangSourceLevel(wangModuleID, st.ModuleLevel, modules[wangModuleID], "phases")
		if err != nil {
			return nil, err
		}
		out.Module = &selected
		var phase struct {
			Parts []json.RawMessage `json:"parts"`
		}
		if err := json.Unmarshal(selected.Raw, &phase); err != nil {
			return nil, err
		}
		for _, raw := range phase.Parts {
			var part struct {
				Talent struct {
					Candidates []json.RawMessage `json:"candidates"`
				} `json:"addOrOverrideTalentDataBundle"`
			}
			if err := json.Unmarshal(raw, &part); err != nil {
				return nil, err
			}
			var best json.RawMessage
			rank := -1
			for _, cand := range part.Talent.Candidates {
				var c moduleSpeedCandidate
				if err := json.Unmarshal(cand, &c); err != nil {
					return nil, err
				}
				if phaseOf(c.UnlockCondition.Phase) <= st.Elite && c.UnlockCondition.Level <= st.Level && c.RequiredPotentialRank <= st.Potential-1 && c.RequiredPotentialRank > rank {
					best = cand
					rank = c.RequiredPotentialRank
				}
			}
			if best != nil {
				out.ModuleCandidates = append(out.ModuleCandidates, best)
			}
		}
	}
	return out, nil
}

// The baseline scanner only knew module ASPD and selected character families.
// Preserve every Wang non-panel source as a gap, including token attribute rows.
func wangModuleMechanismGaps(st *OperatorStats) ([]mechanisms.Gap, error) {
	if st.CharID != wangCharID || st.Module == "" || st.ModuleLevel <= 0 {
		return nil, nil
	}
	spec, err := buildWangSourceSpec(st, 1, SkillLevelDefault)
	if err != nil {
		return nil, err
	}
	var phase struct {
		Parts  []json.RawMessage            `json:"parts"`
		Tokens map[string][]json.RawMessage `json:"tokenAttributeBlackboard"`
	}
	if err := json.Unmarshal(spec.Module.Raw, &phase); err != nil {
		return nil, err
	}
	var gaps []mechanisms.Gap
	for _, token := range []string{wangTokenID} {
		for i, raw := range phase.Tokens[token] {
			var b struct {
				Key   string `json:"key"`
				Value any    `json:"value"`
			}
			if err := json.Unmarshal(raw, &b); err != nil {
				return nil, err
			}
			gaps = append(gaps, mechanisms.Gap{ID: "module.token_attribute." + b.Key, Status: "unimplemented", Source: "module", CharID: st.CharID, Operator: st.Name, SourceID: st.Module, Key: b.Key, RawValue: b.Value, RawBlackboard: cloneRawBlackboard(phase.Tokens[token]), RawSource: spec.Module.Raw, RawSlot: raw, Level: st.ModuleLevel, Instance: i, Reason: "棋子模组非面板修正尚无实体消费者"})
		}
	}
	for i, raw := range phase.Parts {
		gaps = append(gaps, mechanisms.Gap{ID: "module.wang_non_panel", Status: "unimplemented", Source: "module", CharID: st.CharID, Operator: st.Name, SourceID: st.Module, Key: "parts", RawSource: spec.Module.Raw, RawSlot: raw, Slot: i, Level: st.ModuleLevel, Reason: "望模组特性与棋子天赋升级尚无完整消费者"})
	}
	return gaps, nil
}
