package timing

import (
	"math"
	"math/big"
	"testing"
)

func TestTimeFrameBoundariesAndStrictNeighbors(t *testing.T) {
	for _, n := range []int{6, 15, 30, 60, 270} {
		threshold := float64(n) / FPS
		var a Accumulator
		v := 0.0
		for i := 1; i <= n; i++ {
			v = a.StepTime(v, 1)
			if a.TimeAtLeast(threshold) != (i == n) {
				t.Fatalf("n=%d i=%d", n, i)
			}
		}
		if a.TimeAtLeast(math.Nextafter(threshold, math.Inf(1))) {
			t.Fatal("accepted high ULP threshold")
		}
		if !a.TimeAtLeast(math.Nextafter(threshold, math.Inf(-1))) {
			t.Fatal("lost low ULP threshold")
		}
	}
	var a Accumulator
	v := 0.0
	for i := 1; i <= 15; i++ {
		v = a.StepTime(v, 1)
	}
	if a.TimeAtLeast(.51) {
		t.Fatal("rounded non-grid duration")
	}
	v = a.StepTime(v, 1)
	if !a.TimeAtLeast(.51) {
		t.Fatal("non-grid duration missed")
	}
}

// Independent exact-binary reference also exercises integer-to-rational
// transitions in the optimized clock, not just canonical frame examples.
func TestTimeFastPathMatchesRationalReference(t *testing.T) {
	for _, start := range []float64{0, .5, math.Nextafter(.5, math.Inf(1)), .51} {
		var a Accumulator
		v := start
		var reference big.Rat
		if n, ok := gridFrames(start); ok {
			reference.SetFrac(big.NewInt(n), big.NewInt(FPS))
		} else {
			reference.SetFloat64(start)
		}
		for i := 0; i < 1000; i++ {
			direction := int64(1)
			if i%7 == 0 {
				direction = -1
			}
			v = a.StepTime(v, direction)
			reference.Add(&reference, big.NewRat(direction, FPS))
			if i%11 == 0 {
				v = a.ConsumeTime(.51)
				reference.Sub(&reference, new(big.Rat).SetFloat64(.51))
			}
			want, _ := reference.Float64()
			if v != want {
				t.Fatalf("start=%g step%d got=%g want=%g", start, i, v, want)
			}
			threshold := float64(i%30) / FPS
			exact := big.NewRat(int64(i%30), FPS)
			if a.TimeAtLeast(threshold) != (reference.Cmp(exact) >= 0) {
				t.Fatal("comparison differs")
			}
		}
	}
}

func TestRateKeepsRealULPDifference(t *testing.T) {
	for _, rate := range []float64{1, math.Nextafter(1, 0)} {
		var a Accumulator
		v := 0.0
		for i := 0; i < 30; i++ {
			v = a.StepRate(v, rate, 2)
		}
		if a.NumericAtLeast(1) != (rate == 1) {
			t.Fatalf("rate=%g wrongly crossed threshold", rate)
		}
	}
	var a Accumulator
	v := 0.0
	for i := 0; i < 15; i++ {
		v = a.StepRate(v, 1, 2)
	}
	for i := 0; i < 15; i++ {
		v = a.StepRate(v, 0, 2)
	}
	if a.NumericAtLeast(1) {
		t.Fatal("zero rate advanced")
	}
	for i := 0; i < 15; i++ {
		v = a.StepRate(v, 1, 2)
	}
	if !a.NumericAtLeast(1) {
		t.Fatal("rate resumption lost")
	}
	v = .1
	v = a.StepRate(v, 0, 2)
	if v != .1 {
		t.Fatal("external write ignored")
	}
}
func TestNumericFastPathFallbackMatchesExactReference(t *testing.T) {
	var a Accumulator
	v := 0.0
	var ref big.Rat
	cap := big.NewRat(10, 1)
	for i := 0; i < 600; i++ {
		rate := 1.0
		if i%19 == 0 {
			rate = math.Nextafter(1, 0)
		}
		v = a.StepRate(v, rate, 10)
		increment := new(big.Rat).SetFloat64(rate)
		increment.Quo(increment, big.NewRat(FPS, 1))
		ref.Add(&ref, increment)
		if ref.Cmp(cap) > 0 {
			ref.Set(cap)
		}
		if i%31 == 0 {
			v = a.SpendNumeric(v, 1)
			ref.Sub(&ref, big.NewRat(1, 1))
			if ref.Sign() < 0 {
				ref.SetInt64(0)
			}
		}
		if i%23 == 0 {
			v = a.AddNumeric(v, .1, 10)
			ref.Add(&ref, new(big.Rat).SetFloat64(.1))
			if ref.Cmp(cap) > 0 {
				ref.Set(cap)
			}
		}
		want, _ := ref.Float64()
		if v != want {
			t.Fatalf("step%d got=%g want=%g", i, v, want)
		}
		if a.ReadyNumeric(v, 1) != (ref.Cmp(big.NewRat(1, 1)) >= 0) {
			t.Fatal("readiness diverged")
		}
	}
}

func TestNonGridCycleRetainsRemainder(t *testing.T) {
	var a Accumulator
	v := 0.0
	events := []int{}
	for i := 1; i <= 46; i++ {
		v = a.StepTime(v, 1)
		for a.TimeAtLeast(.51) {
			v = a.ConsumeTime(.51)
			events = append(events, i)
		}
	}
	if len(events) != 3 || events[0] != 16 || events[1] != 31 || events[2] != 46 {
		t.Fatal(events)
	}
}
