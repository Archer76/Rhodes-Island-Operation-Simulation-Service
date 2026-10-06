package main

import (
	"encoding/json"
	"fmt"
	"rios-sim/core"
)

func validateSkillsJSON(blob []byte) error {
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(blob, &obj); err != nil {
		return err
	}
	raw, ok := obj["skills"]
	if !ok || string(raw) == "null" {
		return nil
	}
	var values map[string]json.RawMessage
	if err := json.Unmarshal(raw, &values); err != nil {
		return fmt.Errorf("skills必须是名字到[技能槽,专精]映射：%w", err)
	}
	for name, value := range values {
		var pair []json.RawMessage
		if err := json.Unmarshal(value, &pair); err != nil || len(pair) != 2 {
			return fmt.Errorf("skills[%s]必须是两个整数[技能槽,专精]", name)
		}
		for _, raw := range pair {
			var n *int
			if err := json.Unmarshal(raw, &n); err != nil || n == nil || *n < 0 || *n > 3 {
				return fmt.Errorf("skills[%s]技能槽/专精必须是0–3整数", name)
			}
		}
	}
	return nil
}
func (q *CandidatesQuery) UnmarshalJSON(blob []byte) error {
	if err := validateSkillsJSON(blob); err != nil {
		return err
	}
	type plain CandidatesQuery
	var value plain
	if err := json.Unmarshal(blob, &value); err != nil {
		return err
	}
	*q = CandidatesQuery(value)
	return nil
}
func (q *SolveQuery) UnmarshalJSON(blob []byte) error {
	if err := validateSkillsJSON(blob); err != nil {
		return err
	}
	type plain SolveQuery
	var value plain
	if err := json.Unmarshal(blob, &value); err != nil {
		return err
	}
	*q = SolveQuery(value)
	return nil
}

func selectedSkillID(charID string, slot int) (string, int, error) {
	if slot < 0 || slot > 3 {
		return "", 0, fmt.Errorf("%s 的技能槽%d越界（0–3）", charID, slot)
	}
	ids, err := OperatorSkillIDs(charID)
	if err != nil {
		return "", 0, err
	}
	if len(ids) == 0 {
		if slot != 0 {
			return "", 0, fmt.Errorf("%s 没有技能，不能选择槽%d", charID, slot)
		}
		return "", 0, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot > len(ids) {
		return "", 0, fmt.Errorf("%s 没有%d号技能槽（只有%d个），不截断", charID, slot, len(ids))
	}
	return ids[slot-1], slot, nil
}

func deployRowSkillLevel(r DeployRow) (int, error) {
	d := DeployOrder{Operator: r.Operator, Skill: r.Skill, Mastery: r.Mastery}
	if r.SkillLevel != 0 {
		v := r.SkillLevel
		d.SkillLevel = &v
	}
	_, level, _, err := resolveDeploymentSkill(d, RosterRead{}, r.Entry.CharID, nil)
	return level, err
}

func resolveDeploymentSkill(d DeployOrder, roster RosterRead, charID string, inputs *buildInputs) (slot, level, mastery int, err error) {
	id, slot, err := selectedSkillID(charID, d.Skill)
	if err != nil {
		return 0, 0, 0, err
	}
	var entry *core.RosterEntry
	for i := range roster.Entries {
		if roster.Entries[i].Name == d.Operator {
			entry = &roster.Entries[i]
			break
		}
	}
	level, mastery, err = core.ResolveSkillTraining(d, entry, id)
	if err != nil {
		return 0, 0, 0, err
	}
	if id == "" {
		if mastery != 0 || d.SkillLevel != nil {
			return 0, 0, 0, fmt.Errorf("%s 没有技能，不能请求技能等级/专精", d.Operator)
		}
		return 0, 0, 0, nil
	}
	if _, err := inputs.skillMeta(id, level); err != nil {
		return 0, 0, 0, fmt.Errorf("%s 技能%s等级%d不可用：%w", d.Operator, id, level, err)
	}
	return slot, level, mastery, nil
}
