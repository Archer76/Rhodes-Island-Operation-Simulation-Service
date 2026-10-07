// Package mechanisms defines actionable placeholders for incomplete modelling.
// A gap is not an approximation warning: any gap on the evaluated plan prevents
// a combat verdict. Unknown semantics and known-but-unimplemented behaviours
// remain separate so future implementations can claim an exact source.
package mechanisms

import (
	"encoding/json"
	"fmt"
	"sort"
)

type Gap struct {
	ID            string            `json:"id"`
	Status        string            `json:"status"`
	Source        string            `json:"source"`
	Operator      string            `json:"operator,omitempty"`
	CharID        string            `json:"char_id,omitempty"`
	SourceID      string            `json:"source_id,omitempty"`
	SourceName    string            `json:"source_name,omitempty"`
	Key           string            `json:"key,omitempty"`
	RawValue      any               `json:"raw_value,omitempty"`
	Reason        string            `json:"reason"`
	RawBlackboard []json.RawMessage `json:"raw_blackboard,omitempty"`
	RawSource     json.RawMessage   `json:"raw_source,omitempty"`
	RawSlot       json.RawMessage   `json:"raw_slot,omitempty"`
	Description   string            `json:"description,omitempty"`
	Slot          int               `json:"slot,omitempty"`
	Level         int               `json:"level,omitempty"`
	Instance      int               `json:"instance"`
}

type IncompleteError struct{ Placeholders []Gap }

func (e *IncompleteError) Error() string {
	if len(e.Placeholders) == 0 {
		return "机制未完成，未产生战斗判决"
	}
	g := e.Placeholders[0]
	return fmt.Sprintf("机制未完成，未产生战斗判决：%s %s %s（%s）；共 %d 项占位", g.Operator, g.SourceName, g.Key, g.Reason, len(e.Placeholders))
}

// Merge is stable and de-duplicates by source identity, never by key alone.
func Merge(groups ...[]Gap) []Gap {
	var out []Gap
	seen := map[string]bool{}
	for _, group := range groups {
		for _, g := range group {
			key := g.ID + "\x00" + g.CharID + "\x00" + g.Operator + "\x00" + g.SourceID + "\x00" + g.SourceName + "\x00" + g.Key + fmt.Sprintf("\x00%d:%d:%d", g.Instance, g.Slot, g.Level)
			if !seen[key] {
				seen[key] = true
				out = append(out, g)
			}
		}
	}
	return out
}
func Keys(bb map[string]any) []string {
	keys := make([]string, 0, len(bb))
	for k := range bb {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	return keys
}
