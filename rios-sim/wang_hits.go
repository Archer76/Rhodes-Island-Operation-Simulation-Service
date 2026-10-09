package main

import "fmt"

// Explicit-target bridge to the real enemy damage sink. Candidate selection and
// event ordering remain the simulator's responsibility; callers may not infer
// target qualification from enemy-count visibility.
type wangHitWitness struct {
	EnemyIndex       int
	Requested, Dealt float64
	Rejected         bool
}

func wangApplyMagicHit(target *enemy, source *operator, amount float64, now float64, verdict *Verdict) (wangHitWitness, error) {
	if target == nil || verdict == nil {
		return wangHitWitness{}, fmt.Errorf("wang damage sink missing")
	}
	witness := wangHitWitness{EnemyIndex: target.index, Requested: amount}
	if !target.alive() || target.leaked {
		witness.Rejected = true
		return witness, fmt.Errorf("wang damage target dead or leaked")
	}
	if amount < 0 {
		return witness, fmt.Errorf("negative wang damage")
	}
	wasAlive := target.alive()
	witness.Dealt = target.take(amount, source)
	verdict.DamageDealt += witness.Dealt
	if wasAlive && !target.alive() && !target.pendingReborn() {
		target.deathTime = now
		verdict.Events = append(verdict.Events, Event{T: now, Kind: "kill", Who: target.spec.Name})
	}
	return witness, nil
}

// Every simultaneous target is preflighted before any hit. Pending unresolved
// dodge events cannot create a partially applied AOE or consume its stone.
func wangPrepareMagicHits(targets []*enemy, ownerATK float64, cfg wangRuntimeConfig, stacks int) ([]float64, error) {
	amounts := make([]float64, len(targets))
	seen := map[*enemy]bool{}
	for i, e := range targets {
		if e == nil || !e.alive() || e.leaked {
			return nil, fmt.Errorf("wang target not live")
		}
		if seen[e] {
			return nil, fmt.Errorf("wang same enemy supplied twice; cross center must hit once")
		}
		seen[e] = true
		amount, err := wangResolveMagicDamage(ownerATK, cfg.DamageScale, stacks, cfg.PerDamage, cfg.PerResistPenetration, e.res(), e.dodgeVs("MAGIC"))
		if err != nil {
			return nil, err
		}
		amounts[i] = amount
	}
	return amounts, nil
}
