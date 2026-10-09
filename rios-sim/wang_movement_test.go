package main

import "testing"

func TestWangSlowReachesActualMovementAndExpires(t *testing.T) {
	now := 1.
	ctx := &simCtx{time: &now}
	slows := &wangSlowEffects{}
	slows.add(0, 6, .5)
	slows.add(.5, 6, .5)
	e := &enemy{hp: 100, haste: 1, sim: ctx, wangSlows: slows, spec: SpawnSpec{MoveSpeed: 1, Legs: []LegSpec{{Kind: "static"}}}}
	advance(e, 1, 1, 1)
	if e.progress != .25 {
		t.Fatal("actual movement missing slow", e.progress)
	}
	now = 6
	advance(e, 1, 1, 1)
	if e.progress != .75 {
		t.Fatal("first layer expiry", e.progress)
	}
	now = 7
	advance(e, 1, 1, 1)
	if e.progress != 1.75 {
		t.Fatal("restore movement", e.progress)
	}
}
func TestWangNoSlowPreservesMovementBitIdentity(t *testing.T) {
	now := 0.
	ctx := &simCtx{time: &now}
	a := &enemy{haste: 1.4, sim: ctx, spec: SpawnSpec{MoveSpeed: 1.3, Legs: []LegSpec{{Kind: "static"}}}}
	b := *a
	b.wangSlows = &wangSlowEffects{}
	advance(a, .03333333333333333, .7, .873)
	advance(&b, .03333333333333333, .7, .873)
	if a.progress != b.progress {
		t.Fatal("empty slow changes old movement")
	}
}
