package main

import (
	"fmt"
	"math"
)

type wangSlowLayer struct {
	Until  float64
	Factor float64
}
type wangSlowEffects struct{ Layers []wangSlowLayer }

func (s *wangSlowEffects) add(now, duration, factor float64) error {
	if math.IsNaN(now) || math.IsInf(now, 0) || now < 0 || math.IsNaN(duration) || math.IsInf(duration, 0) || duration <= 0 || math.IsNaN(factor) || math.IsInf(factor, 0) || factor < 0 || factor > 1 {
		return fmt.Errorf("invalid wang slow event")
	}
	s.Layers = append(s.Layers, wangSlowLayer{Until: now + duration, Factor: factor})
	return nil
}
func (s *wangSlowEffects) factor(now float64) float64 {
	product := 1.
	keep := s.Layers[:0]
	for _, l := range s.Layers {
		if now < l.Until {
			product *= l.Factor
			keep = append(keep, l)
		}
	}
	s.Layers = keep
	return product
}

// Apply the 0.1 speed floor only while an actual Wang slow is effective. Calling
// this on an unaffected enemy preserves its speed, including intentional zero.
func (s *wangSlowEffects) speed(base, now float64) float64 {
	factor := s.factor(now)
	if len(s.Layers) == 0 {
		return base
	}
	return math.Max(.1, base*factor)
}

// Damage source calculation, with transient FIXED penetration. Existing generic
// damage's expectation-value dodge is explicitly not used for uncertain events.
func wangResolveMagicDamage(ownerATK, tokenScale float64, stacks int, perDamage, perPen, enemyRES, dodge float64) (float64, error) {
	for _, v := range []float64{ownerATK, tokenScale, perDamage, perPen, enemyRES, dodge} {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return 0, fmt.Errorf("nonfinite wang damage source")
		}
	}
	if ownerATK < 0 || tokenScale <= 0 || stacks < 1 || stacks > 3 || perDamage < 0 || perPen < 0 || dodge < 0 || dodge > 1 {
		return 0, fmt.Errorf("invalid wang damage source")
	}
	if dodge > 0 && dodge < 1 {
		return 0, fmt.Errorf("wang magic dodge requires exact event consumer")
	}
	scale, pen := wangTalentModifiers(stacks, perDamage, perPen)
	return resolveDamage(ownerATK, "MAGIC", tokenScale*scale, 0, enemyRES-pen, dodge), nil
}
