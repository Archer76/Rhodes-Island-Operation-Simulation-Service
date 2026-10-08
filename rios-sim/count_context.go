package main

import (
	"encoding/json"
	"fmt"
)

// Only count-enabled JSON specs impose presence here. Legitimate zero/negative
// ASPD must not be confused with omission, and legacy protocol stays unchanged.
func (o *OperatorSpec) UnmarshalJSON(raw []byte) error {
	type plain OperatorSpec
	decoded := plain(*o)
	if err := json.Unmarshal(raw, &decoded); err != nil {
		return err
	}
	if decoded.EnemyCountAttackSpeed != nil {
		var fields map[string]json.RawMessage
		if err := json.Unmarshal(raw, &fields); err != nil {
			return err
		}
		var cells *[][2]int
		if err := json.Unmarshal(fields["range"], &cells); err != nil || cells == nil {
			return fmt.Errorf("敌数攻速必须显式提供基准range数组（允许空数组，不允许省略或null）")
		}
		if err := requireCountTimingJSON(fields["attack_timing"]); err != nil {
			return err
		}
		if decoded.Active != nil {
			var active map[string]json.RawMessage
			if err := json.Unmarshal(fields["active"], &active); err != nil {
				return err
			}
			if err := requireCountTimingJSON(active["attack_timing"]); err != nil {
				return err
			}
		}
	}
	*o = OperatorSpec(decoded)
	return nil
}
func requireCountTimingJSON(raw json.RawMessage) error {
	var fields map[string]json.RawMessage
	if err := json.Unmarshal(raw, &fields); err != nil {
		return fmt.Errorf("敌数攻速原始timing缺失: %w", err)
	}
	for _, key := range []string{"base_attack_time", "aspd"} {
		var value *float64
		if err := json.Unmarshal(fields[key], &value); err != nil || value == nil {
			return fmt.Errorf("敌数攻速原始timing必须显式提供数值%s", key)
		}
	}
	return nil
}
