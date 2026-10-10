package main

import "testing"

func TestAttackFrameReevaluatesHPAndPausesForFreeze(t *testing.T) {
	op := hpSpeedUnit()
	op.hp = 500
	target := &enemy{hp: 1000, position: [2]float64{1, 0}, spec: SpawnSpec{Name: "frame-target"}}
	v := &Verdict{}
	s := &Spec{}
	for i := 0; i < 27; i++ {
		if err := operatorsAttackFrame([]*operator{op}, []*enemy{target}, float64(i)/30, s, v); err != nil {
			t.Fatal(err)
		}
	}
	if target.hp != 1000 {
		t.Fatal("early normal attack")
	}
	before := op.attackTimer
	op.freezeTimer = 1
	op.heal(1)
	if err := operatorsAttackFrame([]*operator{op}, []*enemy{target}, 1, s, v); err != nil {
		t.Fatal(err)
	}
	if op.attackTimer != before || target.hp != 1000 {
		t.Fatal("freeze advanced attack")
	}
	op.freezeTimer = 0
	if err := operatorsAttackFrame([]*operator{op}, []*enemy{target}, 2, s, v); err != nil {
		t.Fatal(err)
	}
	if target.hp != 900 {
		t.Fatal("dynamic threshold cached or progress lost")
	}
	op.hp = 500
	for i := 1; i <= 29; i++ {
		if err := operatorsAttackFrame([]*operator{op}, []*enemy{target}, 2+float64(i)/30, s, v); err != nil {
			t.Fatal(err)
		}
	}
	if target.hp != 900 {
		t.Fatal("lower speed still latched high")
	}
	if err := operatorsAttackFrame([]*operator{op}, []*enemy{target}, 3, s, v); err != nil {
		t.Fatal(err)
	}
	if target.hp != 800 {
		t.Fatal("normal interval missed 30 updates")
	}
}
