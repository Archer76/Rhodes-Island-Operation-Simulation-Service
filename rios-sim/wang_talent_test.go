package main

import (
	"math"
	"testing"
)

func TestWangTalentSamplesRemainingLongestLine(t *testing.T) {
	a, b, c := Cell{1, 1}, Cell{2, 1}, Cell{3, 1}
	if got := wangTalentStacks(a, []Cell{a, b, c}); got != 3 {
		t.Fatalf("first trigger=%d", got)
	}
	if got := wangTalentStacks(b, []Cell{b, c}); got != 2 {
		t.Fatalf("removed first stone still counted: %d", got)
	}
	if got := wangTalentStacks(c, []Cell{c}); got != 1 {
		t.Fatalf("self missing: %d", got)
	}
	if got := wangTalentStacks(b, []Cell{b, c, Cell{2, 2}}); got != 2 {
		t.Fatalf("cross must not union: %d", got)
	}
	if got := wangTalentStacks(b, []Cell{a, b, c, Cell{4, 1}, Cell{5, 1}}); got != 3 {
		t.Fatalf("cap=%d", got)
	}
}
func TestWangTalentUsesModuleReplacementNotAddition(t *testing.T) {
	scale, pen := wangTalentModifiers(3, 0.13, 12)
	if math.Abs(scale-1.39) > 1e-15 || pen != 36 {
		t.Fatalf("got %g %g", scale, pen)
	}
	scale, pen = wangTalentModifiers(2, 0.15, 13)
	if scale != 1.3 || pen != 26 {
		t.Fatalf("potential/module got %g %g", scale, pen)
	}
}
