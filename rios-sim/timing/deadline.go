package timing

import "math/big"

// Deadline stores frame-origin time separately from its offset. It avoids
// rounded Start+offset becoming the authoritative event clock.
type Deadline struct {
	startFrame int64
	offset     Accumulator
	active     bool
}

func (d *Deadline) Set(startFrame int64, seconds float64) {
	d.startFrame = startFrame
	d.offset.Reset()
	d.offset.sync(seconds, true)
	d.active = true
}
func (d *Deadline) Due(frame int64) bool {
	if !d.active || !d.offset.valid {
		return false
	}
	if d.offset.grid {
		return frame-d.startFrame >= d.offset.frames
	}
	elapsed := new(big.Rat).SetFrac(big.NewInt(frame-d.startFrame), big.NewInt(FPS))
	return elapsed.Cmp(&d.offset.value) >= 0
}
func (d *Deadline) Add(seconds float64) {
	if d.offset.grid {
		if n, ok := gridFrames(seconds); ok {
			d.offset.frames += n
			d.offset.view()
			return
		}
		d.offset.materialize()
	}
	r := scalarRat(seconds, true)
	if r == nil {
		d.active = false
		return
	}
	d.offset.value.Add(&d.offset.value, r)
	d.offset.view()
}
func (d *Deadline) Clear() { d.active = false }

// Reached selects the first frame not earlier than an external request time.
func Reached(frame int64, seconds float64) bool {
	threshold := scalarRat(seconds, true)
	if threshold == nil {
		return false
	}
	now := new(big.Rat).SetFrac(big.NewInt(frame), big.NewInt(FPS))
	return now.Cmp(threshold) >= 0
}
