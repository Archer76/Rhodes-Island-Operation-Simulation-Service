package main

import (
	"math"
	"testing"
)

func TestSkillIntervalRoundsToLogicFrames(t *testing.T) {
	for _, tc := range []struct {
		seconds float64
		frames  int64
	}{
		{0, 0}, {.78, 23}, {.75, 23}, {.8, 24}, {.2, 6}, {1, 30},
	} {
		got, e := skillIntervalFrames(tc.seconds)
		if e != nil || got != tc.frames {
			t.Fatalf("%g seconds: %d frames, %v", tc.seconds, got, e)
		}
		duration, e := quantizedSkillInterval(tc.seconds)
		if e != nil || duration != float64(tc.frames)/30 {
			t.Fatal("quantized interval", duration, e)
		}
	}
	for _, seconds := range []float64{-1, math.NaN(), math.Inf(1), math.MaxFloat64} {
		if _, e := skillIntervalFrames(seconds); e == nil {
			t.Fatal("accepted invalid interval", seconds)
		}
	}
}

func TestSkillAttackIntervalRuntimeRoundsDown(t *testing.T) {
	op := hpSpeedUnit()
	op.spec.HPAttackSpeed = nil
	op.skillActive = true
	op.spec.Active = &Profile{ATK: 100, AtkScale: 1, Interval: .78, DamageType: "PHYSICAL"}
	target := countedEnemy(1)
	verdict := &Verdict{}
	for frame := 0; frame < 22; frame++ {
		if e := operatorsAttackFrame([]*operator{op}, []*enemy{target}, float64(frame)*gameLogicDT, &Spec{}, verdict); e != nil {
			t.Fatal(e)
		}
	}
	if verdict.DamageDealt != 0 {
		t.Fatal("attack before 23rd frame", verdict.DamageDealt)
	}
	if e := operatorsAttackFrame([]*operator{op}, []*enemy{target}, 22*gameLogicDT, &Spec{}, verdict); e != nil {
		t.Fatal(e)
	}
	if verdict.DamageDealt <= 0 {
		t.Fatal("23.4 frames rounded up rather than to23")
	}
}

func TestBattleLogicClockFixed30Hz(t *testing.T) {
	if e := validateLogicFPS(30); e != nil {
		t.Fatal(e)
	}
	for _, fps := range []int{-1, 0, 1, 15, 60, 120} {
		if e := validateLogicFPS(fps); e == nil {
			t.Fatalf("accepted variable logic fps %d", fps)
		}
	}
	ctx := simCtx{spec: &Spec{FPS: 120}}
	if ctx.DT() != 1.0/30 {
		t.Fatal("mechanism context follows external FPS", ctx.DT())
	}
}
