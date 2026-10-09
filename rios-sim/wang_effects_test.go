package main

import (
	"math"
	"testing"
)

func TestWangSlowIndependentExpiryAndFloor(t *testing.T) {
	var s wangSlowEffects
	if got := s.speed(0, 0); got != 0 {
		t.Fatal("unaffected zero speed changed")
	}
	s.add(0, 6, .5)
	s.add(1, 6, .5)
	if got := s.speed(1, 2); got != .25 {
		t.Fatalf("layers not multiplicative %g", got)
	}
	if got := s.speed(1, 6); got != .5 {
		t.Fatalf("first layer not independently expired %g", got)
	}
	if got := s.speed(1, 7); got != 1 || len(s.Layers) != 0 {
		t.Fatal("expiry did not restore")
	}
	for i := 0; i < 8; i++ {
		s.add(10, 6, .5)
	}
	if got := s.speed(1, 11); got != .1 || len(s.Layers) != 8 {
		t.Fatal("floor or unbounded layer count", got)
	}
	if err := s.add(0, 0, .5); err == nil {
		t.Fatal("zero duration accepted")
	}
}
func TestWangDamageFixedPenetrationAndNoDodgeApproximation(t *testing.T) {
	res := 50.
	got, err := wangResolveMagicDamage(1000, 1, 3, .1, 9, res, 0)
	if err != nil || math.Abs(got-1001) > 1e-12 || res != 50 {
		t.Fatalf("damage %g %v res%g", got, err, res)
	}
	if _, err := wangResolveMagicDamage(1000, 1, 3, .1, 9, 50, .5); err == nil {
		t.Fatal("expectation dodge accepted")
	}
	if got, err := wangResolveMagicDamage(1000, 1, 3, .1, 9, 50, 1); err != nil || got != 0 {
		t.Fatal("certain dodge", got, err)
	}
	if _, err := wangResolveMagicDamage(1000, 1, 4, .1, 9, 50, 0); err == nil {
		t.Fatal("stack overflow accepted")
	}
}
