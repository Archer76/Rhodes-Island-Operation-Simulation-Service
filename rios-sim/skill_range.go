package main

import (
	"encoding/json"
	"fmt"
	"math"
	"strings"
)

// Audited fixed targeting ranges; never infer the purpose from rangeId alone.
func exactSkillTargetRange(meta SkillMeta) (string, bool) {
	if meta.RangeID == nil || meta.OverrideTokenKey != "" {
		return "", false
	}
	text := mechanismText(strings.ReplaceAll(meta.RawDescription, `\n`, ""))
	keys := map[string]bool{}
	switch meta.SkillID {
	case "skchr_spot_1":
		if *meta.RangeID != "x-4" || meta.SkillType != "MANUAL" || meta.Duration == nil || *meta.Duration <= 0 || text != "攻击力+{atk:0%}，停止攻击并专心对周围的友方角色进行治疗" {
			return "", false
		}
		keys["atk"] = true
		keys["base_attack_time"] = true
		if bbFloat(meta.Blackboard, "base_attack_time") != 1.3 {
			return "", false
		}
	case "skchr_nearl2_1":
		if *meta.RangeID != "2-2" || meta.SkillType != "AUTO" || meta.Duration != nil || text != "攻击范围扩大，攻击力+{atk:0%}，攻击速度+{attack_speed}持续时间无限" {
			return "", false
		}
		keys["atk"] = true
		keys["attack_speed"] = true
	default:
		return "", false
	}
	if meta.DurationType != "NONE" || meta.MaxCharge != 1 || meta.SPType != spAuto || len(meta.Blackboard) != len(keys) || len(meta.RawBlackboard) != len(keys) || meta.BlackboardEntries != len(keys) {
		return "", false
	}
	for _, raw := range meta.RawBlackboard {
		var e struct {
			Key      string  `json:"key"`
			Value    float64 `json:"value"`
			ValueStr *string `json:"valueStr"`
		}
		if json.Unmarshal(raw, &e) != nil || !keys[e.Key] || e.ValueStr != nil || math.IsNaN(e.Value) || math.IsInf(e.Value, 0) || e.Value <= 0 {
			return "", false
		}
		v, ok := toFloat(meta.Blackboard[e.Key])
		if !ok || v != e.Value {
			return "", false
		}
		delete(keys, e.Key)
	}
	if len(keys) != 0 {
		return "", false
	}
	tbl, err := LoadRangeTable()
	if err != nil {
		return "", false
	}
	cells, ok := tbl[*meta.RangeID]
	if !ok || len(cells) == 0 {
		return "", false
	}
	var expected []Cell
	if *meta.RangeID == "2-2" {
		expected = []Cell{{0, 0}, {1, 0}, {2, 0}}
	} else {
		for x := -1; x <= 1; x++ {
			for y := -1; y <= 1; y++ {
				expected = append(expected, Cell{x, y})
			}
		}
	}
	if len(cells) != len(expected) {
		return "", false
	}
	seen := map[Cell]bool{}
	for _, cell := range cells {
		seen[cell] = true
	}
	if len(seen) != len(expected) {
		return "", false
	}
	for _, cell := range expected {
		if !seen[cell] {
			return "", false
		}
	}
	return *meta.RangeID, true
}

func selectedSkillSource(meta *SkillMeta, charID string, slot int) (SkillMeta, error) {
	selected := *meta
	table, err := loadCharTable()
	if err != nil {
		return SkillMeta{}, err
	}
	var char struct {
		Skills []json.RawMessage `json:"skills"`
	}
	if err := json.Unmarshal(table[charID], &char); err != nil {
		return SkillMeta{}, err
	}
	if slot <= 0 || slot > len(char.Skills) {
		return SkillMeta{}, fmt.Errorf("%s的技能来源槽%d不可用", charID, slot)
	}
	var source struct {
		SkillID string `json:"skillId"`
		Token   string `json:"overrideTokenKey"`
	}
	if err := json.Unmarshal(char.Skills[slot-1], &source); err != nil {
		return SkillMeta{}, err
	}
	if source.SkillID != meta.SkillID {
		return SkillMeta{}, fmt.Errorf("%s槽%d技能来源与%s不一致", charID, slot, meta.SkillID)
	}
	selected.OverrideTokenKey = source.Token
	selected.RawSlot = append(json.RawMessage(nil), char.Skills[slot-1]...)
	return selected, nil
}

func bindSkillTargetRange(r DeployRow, inputs *buildInputs) (*TargetRangeSpec, error) {
	id, _, err := selectedSkillID(r.Entry.CharID, r.Skill)
	if err != nil || id == "" {
		return nil, err
	}
	level, err := deployRowSkillLevel(r)
	if err != nil {
		return nil, err
	}
	meta, err := inputs.skillMeta(id, level)
	if err != nil {
		return nil, err
	}
	_, slot, err := selectedSkillID(r.Entry.CharID, r.Skill)
	if err != nil {
		return nil, err
	}
	selected, err := selectedSkillSource(meta, r.Entry.CharID, slot)
	if err != nil {
		return nil, err
	}
	code, exact := exactSkillTargetRange(selected)
	if !exact {
		return nil, nil
	}
	// Unknown codes are never converted into a guessed fallback footprint.
	tbl, err := LoadRangeTable()
	if err != nil {
		return nil, err
	}
	fp, err := Footprint(tbl[code], r.Direction, r.Position[0], r.Position[1])
	if err != nil {
		return nil, err
	}
	cells := make([][2]int, 0, len(fp))
	seen := map[[2]int]bool{}
	for _, c := range fp {
		v := [2]int{c[0], c[1]}
		if !seen[v] {
			cells = append(cells, v)
			seen[v] = true
		}
	}
	sortRangeCells(cells)
	return &TargetRangeSpec{Cells: cells}, nil
}

// targetRange only changes normal attack/heal geometry. A skill's field,
// aura, one-shot area or token range is not implied by its targeting range.
func (o *operator) targetRange() [][2]int {
	if p := o.profile(); p != nil && p.TargetRange != nil {
		return p.TargetRange.Cells
	}
	return o.spec.Range
}
