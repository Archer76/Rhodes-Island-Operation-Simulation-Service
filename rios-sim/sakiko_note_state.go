package main

import (
	"fmt"
	"math"
)

// Ordinary (non-skill) notes only. Public movement-state rules:
// https://prts.wiki/w/丰川祥子#天赋 . This kernel does not schedule updates,
// pick nearest targets, integrate motion, detect hits or authorize combat.
type sakikoNotePhase uint8

const (
	sakikoNoteFree sakikoNotePhase = iota
	sakikoNoteTracking
	sakikoNoteRemoved
)

type sakikoOrdinaryNote struct {
	phase            sakikoNotePhase
	born, lastUpdate float64
	freeEntered      float64
	firstFree        bool
	freeGeneration   uint64
	target           int // -1 is explicitly no target; index 0 is a valid identity.
}

func newSakikoOrdinaryNote(source OperatorSpec, t float64, target int) (*sakikoOrdinaryNote, error) {
	if !validSkillRangedExemption(source.CharID, source.SkillRangedExemption) {
		return nil, fmt.Errorf("祥子音符状态缺少精确模组来源")
	}
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 || target < -1 {
		return nil, fmt.Errorf("祥子音符初态参数非法")
	}
	return &sakikoOrdinaryNote{phase: sakikoNoteFree, born: t, lastUpdate: t, freeEntered: t, firstFree: true, target: target}, nil
}

// An already-dispatched update. Caller provides target validity and, only when
// there is no target, the independently selected nearest eligible target.
func (n *sakikoOrdinaryNote) update(t float64, valid bool, nearest int) error {
	if math.IsNaN(t) || math.IsInf(t, 0) || t < n.lastUpdate || nearest < -1 {
		return fmt.Errorf("祥子音符更新时间或目标非法")
	}
	if valid && n.target < 0 {
		return fmt.Errorf("祥子音符不存在目标却声明有效")
	}
	n.lastUpdate = t
	switch n.phase {
	case sakikoNoteFree:
		if n.target < 0 {
			n.target = nearest
			valid = nearest >= 0
		}
		if valid && (!n.firstFree || t-n.born >= .1) {
			n.phase = sakikoNoteTracking
			n.firstFree = false
		}
	case sakikoNoteTracking:
		if !valid {
			n.phase = sakikoNoteFree
			n.freeGeneration++
			n.freeEntered = t
			n.target = -1
		}
	}
	return nil
}

// Ordinary notes have no post-hit state. No damage is applied by this method.
func (n *sakikoOrdinaryNote) hit() error {
	if n.phase != sakikoNoteTracking {
		return fmt.Errorf("祥子普通音符非追踪状态不能认领命中")
	}
	n.phase = sakikoNoteRemoved
	return nil
}

// Source retreat removes all notes except those currently tracking. This does
// not decide the subsequent lifetime of retained notes or their cached damage.
func (n *sakikoOrdinaryNote) sourceRetreat() {
	if n.phase != sakikoNoteTracking {
		n.phase = sakikoNoteRemoved
	}
}
