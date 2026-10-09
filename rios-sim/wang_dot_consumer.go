package main

import (
	"fmt"
	"math"
)

type wangTargetDOT struct {
	Target   *enemy
	Schedule wangDOT
}

// Target is explicit: unresolved same-cell target ties are not guessed here.
// Snapshot resolved damage at application, then tick source-less through the
// actual sink. The first tick remains Doctor-authorized provisional timing.
func (w *wangCombatState) triggerDOT(stoneID uint64, target *enemy, atk, now float64, verdict *Verdict) ([]wangHitWitness, error) {
	cfg := w.Deployment.Config
	if cfg.Slot != 1 || target == nil || !target.alive() || target.leaked || verdict == nil {
		return nil, fmt.Errorf("invalid wang S1 trigger")
	}
	if math.IsNaN(now) || math.IsInf(now, 0) || now < 0 {
		return nil, fmt.Errorf("invalid wang S1 time")
	}
	field := w.Deployment.Field
	field.stones = append([]wangStone(nil), field.stones...)
	x, y := target.cell()
	event, err := field.trigger(stoneID, Cell{x, y}, 1)
	if err != nil {
		return nil, err
	}
	amounts, err := wangPrepareMagicHits([]*enemy{target}, atk, cfg, event.Stacks)
	if err != nil {
		return nil, err
	}
	schedule, err := newWangDOT(target.index, now, cfg.EffectDuration, amounts[0])
	if err != nil {
		return nil, err
	}
	w.Deployment.Field = field
	w.DOTs = append(w.DOTs, wangTargetDOT{Target: target, Schedule: schedule})
	target.sluggishTimer = math.Max(target.sluggishTimer, cfg.EffectDuration)
	return w.tickDOTs(now, verdict)
}
func (w *wangCombatState) tickDOTs(now float64, verdict *Verdict) ([]wangHitWitness, error) {
	if verdict == nil || math.IsNaN(now) || math.IsInf(now, 0) || now < 0 {
		return nil, fmt.Errorf("invalid wang DOT frame")
	}
	var hits []wangHitWitness
	keep := w.DOTs[:0]
	for _, effect := range w.DOTs {
		if effect.Target == nil || !effect.Target.alive() || effect.Target.leaked {
			continue
		}
		for _, at := range effect.Schedule.due(now) {
			if !effect.Target.alive() || effect.Target.leaked {
				break
			}
			hit, err := wangApplyMagicHit(effect.Target, nil, effect.Schedule.Damage, at, verdict)
			if err != nil {
				return hits, err
			}
			hits = append(hits, hit)
		}
		if now < effect.Schedule.Start+effect.Schedule.Duration && effect.Target.alive() && !effect.Target.leaked {
			keep = append(keep, effect)
		}
	}
	w.DOTs = keep
	return hits, nil
}
