package core

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

// Training fields are exact integers: never truncate fractional training input.
func trainingInt(raw json.RawMessage, field string, min, max int) (int, error) {
	s := strings.TrimSpace(string(raw))
	var text string
	if json.Unmarshal(raw, &text) == nil {
		s = strings.TrimSpace(text)
	}
	n, err := strconv.Atoi(s)
	if err != nil || n < min || n > max {
		return 0, fmt.Errorf("%s 必须是 %d–%d 的整数，收到 %s", field, min, max, raw)
	}
	return n, nil
}

// ResolveSkillTraining uses roster training as truth. An explicit request may
// confirm that truth, not replace it. Without a roster, saved plans are self-contained.
// Missing ordinary roster training defaults to 7; missing mastery defaults to 0.
func ResolveSkillTraining(d DeployOrder, entry *RosterEntry, skillID string) (level, mastery int, err error) {
	if d.Mastery < 0 || d.Mastery > 3 {
		return 0, 0, fmt.Errorf("%s 的专精 %d 越界（0–3）", d.Operator, d.Mastery)
	}
	if d.SkillLevel != nil && (*d.SkillLevel < 1 || *d.SkillLevel > 10) {
		return 0, 0, fmt.Errorf("%s 的技能等级 %d 越界（1–10）", d.Operator, *d.SkillLevel)
	}
	level, mastery = 7, 0
	if entry != nil {
		if entry.SkillLevel != nil {
			level = *entry.SkillLevel
		}
		mastery = entry.Mastery[skillID]
		if level < 1 || level > 7 || mastery < 0 || mastery > 3 {
			return 0, 0, fmt.Errorf("%s 的名册技能练度非法", d.Operator)
		}
		if mastery > 0 {
			level = 7 + mastery
		}
		if (d.MasterySet || d.Mastery != 0) && d.Mastery != mastery {
			return 0, 0, fmt.Errorf("%s 请求专精%d与名册实际专精%d冲突", d.Operator, d.Mastery, mastery)
		}
		if d.SkillLevel != nil && *d.SkillLevel != level {
			return 0, 0, fmt.Errorf("%s 请求技能等级%d与名册实际等级%d冲突", d.Operator, *d.SkillLevel, level)
		}
	} else {
		mastery = d.Mastery
		if d.SkillLevel != nil {
			level = *d.SkillLevel
		}
		if mastery > 0 {
			if d.SkillLevel != nil && level != 7+mastery {
				return 0, 0, fmt.Errorf("%s 的技能等级与专精冲突", d.Operator)
			}
			level = 7 + mastery
		} else if level > 7 {
			return 0, 0, fmt.Errorf("%s 的技能等级%d缺少对应专精", d.Operator, level)
		}
	}
	return level, mastery, nil
}

func (d *DeployOrder) UnmarshalJSON(blob []byte) error {
	type plain DeployOrder
	var value plain
	if err := json.Unmarshal(blob, &value); err != nil {
		return err
	}
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(blob, &fields); err != nil {
		return err
	}
	*d = DeployOrder(value)
	if raw, ok := fields["mastery"]; ok && strings.TrimSpace(string(raw)) != "null" {
		n, err := trainingInt(raw, "mastery", 0, 3)
		if err != nil {
			return err
		}
		d.Mastery, d.MasterySet = n, true
	}
	return nil
}

// MarshalJSON preserves omitted mastery, so a plan awaiting roster resolution
// does not accidentally request an explicit zero during an internal round trip.
func (d DeployOrder) MarshalJSON() ([]byte, error) {
	type plain DeployOrder
	var mastery *int
	if d.MasterySet || d.Mastery != 0 {
		v := d.Mastery
		mastery = &v
	}
	return json.Marshal(struct {
		plain
		Mastery *int `json:"mastery,omitempty"`
	}{plain(d), mastery})
}
