package core

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// SkillCatalog is request-local, read-only data for offline presentation/export.
// Simulation keeps its existing private character/skill caches.
type SkillCatalog struct {
	Characters map[string]json.RawMessage
	Skills     map[string]json.RawMessage
}

func LoadSkillCatalog() (*SkillCatalog, error) {
	root := os.Getenv("RIOS_DATA")
	if root == "" {
		root = filepath.Join("data", "gamedata")
	}
	base := filepath.Join(root, "raw.githubusercontent.com", "excel")
	read := func(name string) (map[string]json.RawMessage, error) {
		blob, err := os.ReadFile(filepath.Join(base, name))
		if err != nil {
			return nil, err
		}
		var values map[string]json.RawMessage
		err = json.Unmarshal(blob, &values)
		return values, err
	}
	chars, err := read("character_table.json")
	if err != nil {
		return nil, fmt.Errorf("技能槽数据不可用：%w", err)
	}
	if patch, err := read("char_patch_table.json"); err == nil {
		var values map[string]json.RawMessage
		if err := json.Unmarshal(patch["patchChars"], &values); err != nil {
			return nil, err
		}
		for id, raw := range values {
			if _, ok := chars[id]; !ok {
				chars[id] = raw
			}
		}
	}
	skills, err := read("skill_table.json")
	if err != nil {
		return nil, fmt.Errorf("技能等级数据不可用：%w", err)
	}
	return &SkillCatalog{chars, skills}, nil
}
func (c *SkillCatalog) Resolve(d DeployOrder, entry *RosterEntry, charID string) (slot, level, mastery int, err error) {
	if d.Skill < 0 || d.Skill > 3 {
		return 0, 0, 0, fmt.Errorf("技能槽%d越界", d.Skill)
	}
	raw, ok := c.Characters[charID]
	if !ok {
		return 0, 0, 0, fmt.Errorf("没有干员%s的技能槽数据", charID)
	}
	var char struct {
		Skills []struct {
			ID string `json:"skillId"`
		} `json:"skills"`
	}
	if err = json.Unmarshal(raw, &char); err != nil {
		return
	}
	slot = d.Skill
	if len(char.Skills) == 0 {
		if slot != 0 || d.Mastery != 0 || d.SkillLevel != nil {
			return 0, 0, 0, fmt.Errorf("%s没有技能，不能请求技能槽/等级/专精", d.Operator)
		}
		return 0, 0, 0, nil
	}
	if slot == 0 {
		slot = 1
	}
	if slot > len(char.Skills) {
		return 0, 0, 0, fmt.Errorf("%s没有技能槽%d", d.Operator, slot)
	}
	id := char.Skills[slot-1].ID
	level, mastery, err = ResolveSkillTraining(d, entry, id)
	if err != nil {
		return
	}
	var skill struct {
		Levels []json.RawMessage `json:"levels"`
	}
	if err = json.Unmarshal(c.Skills[id], &skill); err != nil {
		return
	}
	if level > len(skill.Levels) {
		return 0, 0, 0, fmt.Errorf("%s技能%s等级%d不可用（只有%d级）", d.Operator, id, level, len(skill.Levels))
	}
	return
}
