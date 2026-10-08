package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
)

// ExactModuleTalent is an analysis result, NOT an authorized combat effect.
// Eligible inventory gaps remain intact even when a single override is selected.
type ExactModuleTalent struct {
	ModuleID                                            string
	ModuleLevel, PartIndex, CandidateIndex, TalentIndex int
	UpgradeDescription                                  string
	Blackboard                                          map[string]any
	RawPart, RawCandidate                               json.RawMessage
}

func resolveExactCountModuleTalent(st *OperatorStats) (*ExactModuleTalent, error) {
	if st.ModuleLevel < 2 || st.ModuleLevel > 3 || st.Elite < 2 || st.Level < 60 || st.Potential < 1 || st.Potential > 6 {
		return nil, nil
	}
	parts, e := moduleParts(st.Module, st.ModuleLevel)
	if e != nil {
		return nil, e
	}
	if len(parts) < 2 {
		return nil, nil
	}
	return resolveExactCountModuleTalentPart(st, parts[1])
}
func resolveExactCountModuleTalentPart(st *OperatorStats, raw json.RawMessage) (*ExactModuleTalent, error) {
	if st.ModuleLevel < 2 || st.ModuleLevel > 3 || st.Elite < 2 || st.Level < 60 || st.Potential < 1 || st.Potential > 6 {
		return nil, nil
	}
	want := ""
	if st.CharID == "char_4182_oblvns" && st.Module == "uniequip_002_oblvns" {
		want = map[int]string{2: "13dbd63de1baf7b6e5c944aeda777a96bfa7da94b32e8f17ab81d4fa373f90c1", 3: "150880c247b986ed398106372cec1dbc868bb82cd9b3f8026c11f7247915b44e"}[st.ModuleLevel]
	}
	if st.CharID == "char_4010_etlchi" && st.Module == "uniequip_003_etlchi" {
		want = map[int]string{2: "c10bcaf1193a15f34e3963a41f338f70e3c941190d706473724c34a7d56173c5", 3: "0eaccb41dad1f5c003fc5b7f4edbe308ade6aa36349be66b0dbfa5536715ceb0"}[st.ModuleLevel]
	}
	if want == "" {
		return nil, nil
	}
	var value any
	if e := json.Unmarshal(raw, &value); e != nil {
		return nil, e
	}
	b, e := json.Marshal(value)
	if e != nil {
		return nil, e
	}
	if fmt.Sprintf("%x", sha256.Sum256(b)) != want {
		return nil, nil
	}
	var part struct {
		Bundle struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"addOrOverrideTalentDataBundle"`
	}
	if e = json.Unmarshal(raw, &part); e != nil {
		return nil, e
	}
	best := -1
	need := -1
	for ci, craw := range part.Bundle.Candidates {
		var c struct {
			Rank int `json:"requiredPotentialRank"`
		}
		if e = json.Unmarshal(craw, &c); e != nil {
			return nil, e
		}
		// Exact source hashes lock all candidates to E2L60 and talentIndex0.
		if c.Rank <= st.Potential-1 && c.Rank > need {
			best = ci
			need = c.Rank
		}
	}
	if best < 0 {
		return nil, nil
	}
	craw := part.Bundle.Candidates[best]
	var c struct {
		Index       int               `json:"talentIndex"`
		Description string            `json:"upgradeDescription"`
		Blackboard  []json.RawMessage `json:"blackboard"`
	}
	if e = json.Unmarshal(craw, &c); e != nil {
		return nil, e
	}
	return &ExactModuleTalent{ModuleID: st.Module, ModuleLevel: st.ModuleLevel, PartIndex: 1, CandidateIndex: best, TalentIndex: c.Index, UpgradeDescription: c.Description, Blackboard: blackboardOf(c.Blackboard), RawPart: append(json.RawMessage(nil), raw...), RawCandidate: append(json.RawMessage(nil), craw...)}, nil
}
