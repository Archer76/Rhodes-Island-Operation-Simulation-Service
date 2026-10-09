package main

import (
	"fmt"
	"math"
)

// Explicit eligible-target snapshot. Eligibility must be established outside
// this geometry kernel; hidden/camouflage and other selectors are not inferred.
type sakikoNoteCandidate struct {
	index    int
	position [2]float64
}

func nearestSakikoOrdinaryNoteTarget(position [2]float64, candidates []sakikoNoteCandidate) (int, error) {
	for _, x := range position {
		if math.IsNaN(x) || math.IsInf(x, 0) {
			return -1, fmt.Errorf("祥子音符位置非法")
		}
	}
	seen := map[int]bool{}
	best := -1
	distance := math.Inf(1)
	tie := false
	for _, c := range candidates {
		if c.index < 0 || seen[c.index] {
			return -1, fmt.Errorf("祥子音符候选身份非法或重复")
		}
		seen[c.index] = true
		for _, x := range c.position {
			if math.IsNaN(x) || math.IsInf(x, 0) {
				return -1, fmt.Errorf("祥子音符候选位置非法")
			}
		}
		d := math.Hypot(c.position[0]-position[0], c.position[1]-position[1])
		if d == 1 {
			return -1, fmt.Errorf("祥子音符追踪半径边界包含关系未证")
		}
		if d > 1 {
			continue
		}
		if d < distance {
			distance = d
			best = c.index
			tie = false
		} else if d == distance {
			tie = true
		}
	}
	if tie {
		return -1, fmt.Errorf("祥子音符等距最近目标优先级未证")
	}
	return best, nil
}

// A dispatched free-state update with explicitly certified eligible targets.
// Tracking invalidation remains the state update's responsibility, not a search.
func (s *sakikoOrdinaryStore) acquire(id int, t float64, position [2]float64, candidates []sakikoNoteCandidate) error {
	if id < 0 || id >= len(s.notes) {
		return fmt.Errorf("祥子音符身份不存在")
	}
	n := s.notes[id].state
	if n.phase != sakikoNoteFree || n.target >= 0 {
		return fmt.Errorf("祥子音符索敌须自由状态且无目标")
	}
	if e := s.validateSource(); e != nil {
		return e
	}
	target, e := nearestSakikoOrdinaryNoteTarget(position, candidates)
	if e != nil {
		return e
	}
	return s.update(id, t, false, target)
}
