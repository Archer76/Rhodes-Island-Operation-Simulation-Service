package timing

import (
	"math"
	"testing"
)

func TestFrameAnchoredDeadlineDoesNotAccumulateFloatScheduleError(t *testing.T) {
	var d Deadline
	d.Set(1, 1)
	if d.Due(30) {
		t.Fatal("early")
	}
	if !d.Due(31) {
		t.Fatal("missed startFrame1 plus30")
	}
	d.Add(1)
	if d.Due(60) {
		t.Fatal("early repeat")
	}
	if !d.Due(61) {
		t.Fatal("late repeat")
	}
	d.Set(1, math.Nextafter(1, math.Inf(1)))
	if d.Due(31) {
		t.Fatal("high ULP deadline early")
	}
	if !d.Due(32) {
		t.Fatal("high ULP missed")
	}
	d.Clear()
	if d.Due(100) {
		t.Fatal("cleared schedule fired")
	}
}
