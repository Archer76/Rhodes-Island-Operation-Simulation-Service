package mech

import (
	"encoding/json"
	"testing"
)

func TestFarmlandFrameCacheAndActualBoundaries(t *testing.T) {
	var spec FarmlandSpec
	if err := json.Unmarshal([]byte(goldenSpecJSON), &spec); err != nil {
		t.Fatal(err)
	}
	fs, err := NewFarmland(&spec)
	if err != nil {
		t.Fatal(err)
	}
	if fs.AddCache(3, 1, 10) != 10 {
		t.Fatal("cache path not exercised")
	}
	for update := 1; update <= 30; update++ {
		fs.TickFrame()
		want := float64(update / 6)
		if fs.Released != want {
			t.Fatalf("update=%d released=%g want=%g", update, fs.Released, want)
		}
		got := fs.ActualAt(3, 1)
		if update < 30 && got != 0 {
			t.Fatalf("early actual at %d: %g", update, got)
		}
		if update == 30 && got <= 0 {
			t.Fatal("actual missed frame30")
		}
	}
}
