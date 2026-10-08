package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
)

// IntrinsicCountVisibility describes ONLY an exact built-in enemy source.
// It cannot prove absence of external buffs and never replaces CountVisibility.
// Recovery 3s is documented by the normal ba.invisible tooltip, not a raw BB:
// https://prts.wiki/w/隐形弩手组长 (blocking suppresses, unblocking restores in 3s).
type IntrinsicCountVisibility struct {
	UnblockedHidden bool    `json:"unblocked_hidden"`
	RecoveryDelay   float64 `json:"recovery_delay"`
}

func (r *IntrinsicCountVisibility) UnmarshalJSON(raw []byte) error {
	var f map[string]json.RawMessage
	if err := json.Unmarshal(raw, &f); err != nil {
		return err
	}
	var hidden *bool
	var delay *float64
	if json.Unmarshal(f["unblocked_hidden"], &hidden) != nil || json.Unmarshal(f["recovery_delay"], &delay) != nil || hidden == nil || delay == nil || !*hidden || *delay != 3 {
		return fmt.Errorf("固有隐匿规则必须显式unblocked_hidden=true/recovery_delay=3")
	}
	r.UnblockedHidden = *hidden
	r.RecoveryDelay = *delay
	return nil
}
func validIntrinsicRule(r *IntrinsicCountVisibility) bool {
	return r != nil && r.UnblockedHidden && r.RecoveryDelay == 3
}
func intrinsicForSpawn(s SpawnSpec) *IntrinsicCountVisibility {
	return intrinsicCountSource(&EnemyStats{EnemyID: s.EnemyID, Level: s.Level, RawSources: s.RawSources})
}
func intrinsicCountSource(s *EnemyStats) *IntrinsicCountVisibility {
	hashes := map[string]string{"enemy_1019_jshoot": "4eef8a801346d5c8eec0765dcb648c14de2531f5adfe8395b5760c90b0e23a77", "enemy_1019_jshoot_2": "97d0c36585be6ad04f53ed1378150ffe7dd3986f8e7f99d56a0f3dad9804376f"}
	want := hashes[s.EnemyID]
	if want == "" || s.Level != 0 || len(s.RawSources) != 1 {
		return nil
	}
	r := s.RawSources[0]
	if r.Kind != "database_level" || r.EnemyID != s.EnemyID || r.Level != 0 {
		return nil
	}
	var value any
	if json.Unmarshal(r.Raw, &value) != nil {
		return nil
	}
	b, err := json.Marshal(value)
	if err != nil || fmt.Sprintf("%x", sha256.Sum256(b)) != want {
		return nil
	}
	return &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: 3}
}
func cloneIntrinsic(v *IntrinsicCountVisibility) *IntrinsicCountVisibility {
	if v == nil {
		return nil
	}
	c := *v
	return &c
}

// Called after blocking, not lazily by one attacker. All observers see the
// same transition, and skipped/frozen attackers do not delay state progression.
func intrinsicCountTick(enemies []*enemy, t float64) {
	for _, e := range enemies {
		r := e.spec.IntrinsicCountVisibility
		if r == nil {
			continue
		}
		e.countClock = t
		blocked := e.blockedBy != nil && e.blockedBy.alive()
		if e.countWasBlocked && !blocked {
			e.countHiddenRestoreAt = t + r.RecoveryDelay
		}
		e.countWasBlocked = blocked
	}
}
func (e *enemy) effectiveCountVisibility() *CountVisibility {
	if e.spec.CountVisibility == nil {
		return nil
	}
	v := *e.spec.CountVisibility
	if r := e.spec.IntrinsicCountVisibility; r != nil && r.UnblockedHidden {
		blocked := e.blockedBy != nil && e.blockedBy.alive()
		// A blocker can die/retreat after the frame blocking pass. Observe the
		// loss at this same-frame query rather than instantly restoring stealth.
		if e.countWasBlocked && !blocked {
			e.countHiddenRestoreAt = e.countClock + r.RecoveryDelay
			e.countWasBlocked = false
		}
		if blocked {
			e.countWasBlocked = true
		}
		v.Hidden = v.Hidden || !blocked && e.countClock >= e.countHiddenRestoreAt
	}
	return &v
}
