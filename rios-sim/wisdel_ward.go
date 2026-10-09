package main

import (
	"fmt"
	"math"
)

type wisdelWard struct {
	ID        int
	Owner     string
	Pos       Cell
	HP        float64
	MaxHP     float64
	ATK       float64
	DEF       float64
	RES       float64
	SP        float64
	MaxSP     float64
	Sluggish  float64
	SpMin     float64
	SpMax     float64
	Alive     bool
}

func newWisdelWard(id int, owner string, pos Cell, atk, def, res, hp, sluggish, spMin, spMax float64) *wisdelWard {
	if hp <= 0 {
		hp = 3500.0
	}
	if atk <= 0 {
		atk = 521.0
	}
	if def <= 0 {
		def = 457.0
	}
	if res <= 0 {
		res = 50.0
	}
	return &wisdelWard{
		ID:       id,
		Owner:    owner,
		Pos:      pos,
		HP:       hp,
		MaxHP:    hp,
		ATK:      atk,
		DEF:      def,
		RES:      res,
		SP:       0.0,
		MaxSP:    5.0,
		Sluggish: sluggish,
		SpMin:    spMin,
		SpMax:    spMax,
		Alive:    true,
	}
}

type wisdelWardAttackEvent struct {
	WardID       int
	TargetEnemy  *enemy
	Damage       float64
	IsMagic      bool
	SluggishTime float64
	AttachMark   bool
	SPGranted    float64
}

func (w *wisdelWard) Tick(dt float64, inOwnerRange func(pos Cell) bool, enemies []*enemy) ([]wisdelWardAttackEvent, error) {
	if !w.Alive {
		return nil, nil
	}
	if dt <= 0 {
		return nil, fmt.Errorf("invalid dt for wisdel ward")
	}

	w.SP += dt
	if w.SP < w.MaxSP {
		return nil, nil
	}

	// SP is full, find an enemy in owner's attack range
	var target *enemy
	maxProgress := -1.0
	for _, e := range enemies {
		if e == nil || e.hp <= 0 {
			continue
		}
		eCell := Cell{int(math.Round(e.position[0])), int(math.Round(e.position[1]))}
		if inOwnerRange(eCell) {
			if e.progress > maxProgress {
				maxProgress = e.progress
				target = e
			}
		}
	}

	if target == nil {
		// Keep SP capped, wait for enemies
		w.SP = w.MaxSP
		return nil, nil
	}

	// Trigger skill
	w.SP -= w.MaxSP
	spGranted := 1.0 // typical average/fixed 1 SP granted to Wisdel (range 0~2)
	if w.SpMax > w.SpMin {
		spGranted = math.Floor((w.SpMin + w.SpMax) / 2.0)
	}

	event := wisdelWardAttackEvent{
		WardID:       w.ID,
		TargetEnemy:  target,
		Damage:       w.ATK,
		IsMagic:      true,
		SluggishTime: w.Sluggish,
		AttachMark:   true,
		SPGranted:    spGranted,
	}

	return []wisdelWardAttackEvent{event}, nil
}

func isWisdelNearWard(wisdelPos Cell, wards []*wisdelWard) bool {
	for _, w := range wards {
		if w == nil || !w.Alive {
			continue
		}
		dx := math.Abs(float64(wisdelPos[0] - w.Pos[0]))
		dy := math.Abs(float64(wisdelPos[1] - w.Pos[1]))
		if dx <= 1 && dy <= 1 {
			return true
		}
	}
	return false
}
