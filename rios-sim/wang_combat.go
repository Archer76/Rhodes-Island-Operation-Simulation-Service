package main

import (
	"fmt"
	"math"
)

// Executable bridge for one explicitly selected S2/S3 trigger. Qualified targets
// and their cell membership are verified BEFORE stone consumption. Missing
// simulation-frame selection is still an incomplete production capability.
type wangCombatState struct {
	Deployment wangDeploymentState
	Slows      map[*enemy]*wangSlowEffects
	DOTs       []wangTargetDOT
}

func (w *wangCombatState) triggerAOE(stoneID uint64, entering *enemy, targets []*enemy, atk, now float64, verdict *Verdict) ([]wangHitWitness, error) {
	cfg := w.Deployment.Config
	if math.IsNaN(now) || math.IsInf(now, 0) || now < 0 {
		return nil, fmt.Errorf("invalid wang event time")
	}
	if cfg.Slot != 2 && cfg.Slot != 3 {
		return nil, fmt.Errorf("wang AOE requires slot2 or3")
	}
	if entering == nil || !entering.alive() || entering.leaked || verdict == nil {
		return nil, fmt.Errorf("wang entering target or verdict missing")
	}
	// Copy the field: preflight must not mutate production state on any refusal.
	field := w.Deployment.Field
	field.stones = append([]wangStone(nil), field.stones...)
	x, y := entering.cell()
	event, err := field.trigger(stoneID, Cell{x, y}, cfg.Slot)
	if err != nil {
		return nil, err
	}
	area := map[Cell]bool{}
	for _, c := range event.DamageCells {
		area[c] = true
	}
	for _, e := range targets {
		if e == nil {
			return nil, fmt.Errorf("wang nil target")
		}
		x, y := e.cell()
		if !area[Cell{x, y}] {
			return nil, fmt.Errorf("wang target outside damage cells")
		}
	}
	amounts, err := wangPrepareMagicHits(targets, atk, cfg, event.Stacks)
	if err != nil {
		return nil, err
	}
	if cfg.Slot == 2 && (cfg.EffectDuration <= 0 || math.IsNaN(cfg.EffectDuration) || math.IsInf(cfg.EffectDuration, 0) || math.IsNaN(cfg.SlowFactor) || math.IsInf(cfg.SlowFactor, 0) || cfg.SlowFactor < 0 || cfg.SlowFactor > 1) {
		return nil, fmt.Errorf("wang slow parameters missing")
	}
	w.Deployment.Field = field
	var hits []wangHitWitness
	for i, e := range targets {
		hit, err := wangApplyMagicHit(e, nil, amounts[i], now, verdict)
		if err != nil {
			return hits, err
		}
		hits = append(hits, hit)
		if cfg.Slot == 2 {
			if w.Slows == nil {
				w.Slows = map[*enemy]*wangSlowEffects{}
			}
			if e.wangSlows == nil {
				e.wangSlows = &wangSlowEffects{}
			}
			w.Slows[e] = e.wangSlows
			if err := w.Slows[e].add(now, cfg.EffectDuration, cfg.SlowFactor); err != nil {
				return hits, err
			}
		}
	}
	return hits, nil
}
