// Package timing implements explicit 30 Hz updates without repeated rounded dt
// addition. Only time values on the canonical seconds grid are interpreted as
// exact frame multiples; SP and rates retain their exact binary64 input values.
package timing

import (
	"math"
	"math/big"
)

const FPS = 30
const DT = 1.0 / FPS

// Accumulator retains exact arithmetic across frame updates. The scalar is a
// compatibility view, never the threshold authority. A changed scalar value
// resynchronizes on the next update; an intentional same-value replacement must
// use Reset or SetNumeric. Gains must use AddNumeric, not mutate the view.
// Like big.Rat, a populated Accumulator must not be shallow-copied.
type Accumulator struct {
	value  big.Rat
	last   float64
	valid  bool
	grid   bool
	frames int64
}

// Numeric fast path accepts only exact integer binary64 inputs, never grid
// snapping of SP/cost/rate. Restrict range so scaled integers stay exactly viewed.
func integerNumeric(v float64) (int64, bool) {
	if !math.IsNaN(v) && !math.IsInf(v, 0) && math.Abs(v) < float64(int64(1)<<48) && v == math.Trunc(v) {
		return int64(v), true
	}
	return 0, false
}
func gridFrames(v float64) (int64, bool) {
	if math.IsNaN(v) || math.IsInf(v, 0) {
		return 0, false
	}
	n := math.Round(v * FPS)
	if math.Abs(n) < float64(int64(1)<<53) && v == n/FPS {
		return int64(n), true
	}
	return 0, false
}
func (a *Accumulator) materialize() {
	if a.grid {
		a.value.SetFrac(big.NewInt(a.frames), big.NewInt(FPS))
		a.grid = false
	}
}
func scalarRat(v float64, isTime bool) *big.Rat {
	if isTime && !math.IsNaN(v) && !math.IsInf(v, 0) {
		n := math.Round(v * FPS)
		if math.Abs(n) < float64(int64(1)<<53) && v == n/FPS {
			return new(big.Rat).SetFrac(big.NewInt(int64(n)), big.NewInt(FPS))
		}
	}
	return new(big.Rat).SetFloat64(v)
}
func (a *Accumulator) sync(current float64, isTime bool) bool {
	if a.valid && current == a.last {
		return true
	}
	if isTime {
		if n, ok := gridFrames(current); ok {
			a.frames = n
			a.grid = true
			a.valid = true
			a.last = current
			return true
		}
	}
	if !isTime {
		if n, ok := integerNumeric(current); ok {
			a.frames = n * FPS
			a.grid = true
			a.valid = true
			a.last = current
			return true
		}
	}
	a.grid = false
	r := scalarRat(current, isTime)
	if r == nil {
		a.valid = false
		return false
	}
	a.value.Set(r)
	a.valid = true
	a.last = current
	return true
}
func (a *Accumulator) view() float64 {
	if a.grid {
		a.last = float64(a.frames) / FPS
		return a.last
	}
	a.last, _ = a.value.Float64()
	return a.last
}

// StepTime advances one effective frame, with direction +1 or -1. The caller
// explicitly selects this API; arbitrary-dt primitives do not enter it.
func (a *Accumulator) StepTime(current float64, direction int64) float64 {
	if !a.sync(current, true) {
		return current
	}
	if a.grid {
		a.frames += direction
		return a.view()
	}
	a.value.Add(&a.value, new(big.Rat).SetFrac(big.NewInt(direction), big.NewInt(FPS)))
	return a.view()
}
func (a *Accumulator) TimeAtLeast(seconds float64) bool {
	if a.grid {
		if n, ok := gridFrames(seconds); ok {
			return a.valid && a.frames >= n
		}
		a.materialize()
	}
	r := scalarRat(seconds, true)
	return a.valid && r != nil && a.value.Cmp(r) >= 0
}
func (a *Accumulator) TimeAtMost(seconds float64) bool {
	if a.grid {
		if n, ok := gridFrames(seconds); ok {
			return a.valid && a.frames <= n
		}
		a.materialize()
	}
	r := scalarRat(seconds, true)
	return a.valid && r != nil && a.value.Cmp(r) <= 0
}
func (a *Accumulator) ConsumeTime(seconds float64) float64 {
	if a.grid {
		if n, ok := gridFrames(seconds); ok {
			a.frames -= n
			return a.view()
		}
		a.materialize()
	}
	r := scalarRat(seconds, true)
	if !a.valid || r == nil {
		return a.last
	}
	a.value.Sub(&a.value, r)
	return a.view()
}

// StepRate integrates a numeric rate over the exact 1/30-second frame. Rates,
// costs and caps are not snapped to the time grid, rounded, or epsilon-compared.
func (a *Accumulator) StepRate(current, rate, cap float64) float64 {
	if !a.sync(current, false) {
		return current
	}
	if a.grid {
		rateInt, okRate := integerNumeric(rate)
		capInt, okCap := integerNumeric(cap)
		if okRate && okCap && a.frames >= -(int64(1)<<52) && a.frames <= (int64(1)<<52) {
			a.frames += rateInt
			if a.frames > capInt*FPS {
				a.frames = capInt * FPS
			}
			return a.view()
		}
		a.materialize()
	}
	r := scalarRat(rate, false)
	limit := scalarRat(cap, false)
	if r == nil || limit == nil {
		a.valid = false
		return math.Min(cap, current+rate/FPS)
	}
	r.Quo(r, big.NewRat(FPS, 1))
	a.value.Add(&a.value, r)
	if a.value.Cmp(limit) > 0 {
		a.value.Set(limit)
	}
	return a.view()
}
func (a *Accumulator) NumericAtLeast(threshold float64) bool {
	if a.grid {
		if n, ok := integerNumeric(threshold); ok {
			return a.valid && a.frames >= n*FPS
		}
		a.materialize()
	}
	r := scalarRat(threshold, false)
	return a.valid && r != nil && a.value.Cmp(r) >= 0
}

// SpendNumeric retains fractional SP through activation and multi-charge use.
func (a *Accumulator) SpendNumeric(current, cost float64) float64 {
	if !a.sync(current, false) {
		return current
	}
	if a.grid {
		if n, ok := integerNumeric(cost); ok && a.frames >= -(int64(1)<<52) && a.frames <= (int64(1)<<52) {
			a.frames -= n * FPS
			if a.frames < 0 {
				a.frames = 0
			}
			return a.view()
		}
		a.materialize()
	}
	r := scalarRat(cost, false)
	if r == nil {
		a.valid = false
		return current - cost
	}
	a.value.Sub(&a.value, r)
	if a.value.Sign() < 0 {
		a.value.SetInt64(0)
	}
	return a.view()
}

// AddNumeric preserves exact event gains. A +Inf cap means no cap.
func (a *Accumulator) AddNumeric(current, gain, cap float64) float64 {
	if !a.sync(current, false) {
		return current
	}
	if a.grid {
		n, ok := integerNumeric(gain)
		limit, okCap := integerNumeric(cap)
		if ok && (okCap || math.IsInf(cap, 1)) && a.frames >= -(int64(1)<<52) && a.frames <= (int64(1)<<52) {
			a.frames += n * FPS
			if okCap && a.frames > limit*FPS {
				a.frames = limit * FPS
			}
			return a.view()
		}
		a.materialize()
	}
	r := scalarRat(gain, false)
	if r == nil {
		a.valid = false
		return current + gain
	}
	a.value.Add(&a.value, r)
	if !math.IsInf(cap, 1) {
		limit := scalarRat(cap, false)
		if limit != nil && a.value.Cmp(limit) > 0 {
			a.value.Set(limit)
		}
	}
	return a.view()
}

// SetNumeric explicitly replaces even a scalar value equal to the previous view.
func (a *Accumulator) SetNumeric(value float64) float64 {
	a.Reset()
	a.sync(value, false)
	return value
}
func (a *Accumulator) ReadyNumeric(current, threshold float64) bool {
	return a.sync(current, false) && a.NumericAtLeast(threshold)
}
func (a *Accumulator) Reset() { a.valid = false }
