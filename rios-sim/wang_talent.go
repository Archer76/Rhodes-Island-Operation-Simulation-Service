package main

// Doctor ruling 2026-10-08: include the triggering stone itself, use the
// longest contiguous straight line (not a union of crossed lines), cap at 3.
// This is sampled at each trigger: a removed predecessor no longer contributes.
func wangTalentStacks(origin Cell, peers []Cell) int {
	h, v := wangStraightLineCounts(origin, peers)
	if v > h {
		h = v
	}
	if h > 3 {
		h = 3
	}
	return h
}

func wangTalentModifiers(stacks int, perDamage, perResistPenetration float64) (damageScale, resistPenetration float64) {
	return 1 + float64(stacks)*perDamage, float64(stacks) * perResistPenetration
}
