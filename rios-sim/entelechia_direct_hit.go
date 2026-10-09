package main

import (
	"fmt"
	"math"
)

// Applies an externally resolved, uncancelled ordinary direct-damage event.
// Not an attack scheduler, shield/dodge resolver, DoT applier, or full talent.
// Only no-simulation-callback fixtures are supported until callback integration
// and dynamic cancellation ordering are proved.
func (s *entelechiaStealStore) applyDirectHit(t float64, target *enemy, resolved float64, class entelechiaStealTargetClass, exclusive bool) (float64, error) {
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 || math.IsNaN(resolved) || math.IsInf(resolved, 0) || resolved < 0 {
		return 0, fmt.Errorf("萃血直接伤害事件时间或数值非法")
	}
	if s.owner == nil || target == nil || !target.alive() {
		return 0, fmt.Errorf("萃血直接伤害事件缺少活体对象")
	}
	if target.sim != nil {
		return 0, fmt.Errorf("萃血直接伤害取消及真实回调排序尚未接通")
	}
	if target.invincible || resolved == 0 {
		return 0, nil
	}
	if _, e := s.beforeDamage(t, target, class, exclusive); e != nil {
		return 0, e
	}
	got := target.take(resolved, s.owner)
	if got > 0 && !target.alive() && !target.pendingReborn() {
		target.deathTime = t
	}
	return got, nil
}
