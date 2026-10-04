package main

import (
	"encoding/json"
	"fmt"
	"strings"

	"rios-sim/mechanisms"
)

const mechanismIncompleteMessage = "机制未完成，未产生战斗判决"

// Only the selected result can block export. Search placeholders on a complete
// response describe excluded candidates, not gaps in the selected plan.
func finalMechanismGaps(c *appCtx) (bool, []mechanisms.Gap) {
	var v struct {
		Status       string           `json:"status"`
		Placeholders []mechanisms.Gap `json:"mechanism_placeholders"`
	}
	var p struct {
		Placeholders []mechanisms.Gap `json:"mechanism_placeholders"`
	}
	_ = json.Unmarshal(c.solveVerdict, &v)
	_ = json.Unmarshal(c.solvePlan, &p)
	blocked := c.solveStatus == "incomplete" || v.Status == "incomplete" || len(p.Placeholders) > 0
	gaps := append([]mechanisms.Gap(nil), v.Placeholders...)
	gaps = append(gaps, p.Placeholders...)
	if c.solveStatus == "incomplete" {
		gaps = append(append([]mechanisms.Gap(nil), c.solvePlaceholders...), gaps...)
	}
	return blocked, gaps
}

func mechanismGapLines(gaps []mechanisms.Gap) string {
	var b strings.Builder
	for _, g := range gaps {
		identity := []string{"id=" + g.ID, "status=" + g.Status, "source=" + g.Source}
		for _, part := range []struct{ name, value string }{
			{"operator", g.Operator}, {"char_id", g.CharID}, {"source_id", g.SourceID}, {"source_name", g.SourceName},
		} {
			if part.value != "" {
				identity = append(identity, part.name+"="+part.value)
			}
		}
		identity = append(identity, fmt.Sprintf("instance=%d", g.Instance))
		if g.Slot != 0 {
			identity = append(identity, fmt.Sprintf("slot=%d", g.Slot))
		}
		if g.Level != 0 {
			identity = append(identity, fmt.Sprintf("level=%d", g.Level))
		}
		fmt.Fprintf(&b, "  %s\n    key=%s；reason=%s\n", strings.Join(identity, " / "), g.Key, g.Reason)
		if g.Description != "" {
			fmt.Fprintf(&b, "    %s\n", g.Description)
		}
	}
	return b.String()
}
