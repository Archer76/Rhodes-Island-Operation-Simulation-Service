package main

import (
	"testing"
)

func TestWisdelWardCreationAndCamouflage(t *testing.T) {
	st := newWisdelCombatState("wisdel", Cell{2, 2}, "Right", wisdelRuntimeConfig{}, 1000.0)
	if st.HasCamouflage() {
		t.Fatalf("expected no camouflage before ward deploy")
	}

	// Deploy ward adjacent
	err := st.DeployWard(Cell{2, 3}, 500, 400, 50, 3500)
	if err != nil {
		t.Fatalf("deploy ward failed: %v", err)
	}
	if !st.HasCamouflage() {
		t.Fatalf("expected camouflage when ward is adjacent")
	}

	// Move far away
	st.Pos = Cell{5, 5}
	if st.HasCamouflage() {
		t.Fatalf("expected no camouflage when ward is far")
	}
}

func TestWisdelWardAttackAndSPGrant(t *testing.T) {
	ward := newWisdelWard(1, "wisdel", Cell{2, 2}, 500, 400, 50, 3500, 1.0, 0.0, 3.0)
	e := &enemy{hp: 1000, position: [2]float64{2.0, 3.0}, progress: 10.0}

	// Range predicate
	inRange := func(p Cell) bool {
		return p[0] == 2 && p[1] == 3
	}

	// Tick less than 5s
	events, err := ward.Tick(3.0, inRange, []*enemy{e})
	if err != nil || len(events) > 0 {
		t.Fatalf("unexpected events on tick 3s: %v, %v", err, events)
	}

	// Tick 2.5s more -> SP full
	events, err = ward.Tick(2.5, inRange, []*enemy{e})
	if err != nil {
		t.Fatalf("tick failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 attack event, got %d", len(events))
	}
	ev := events[0]
	if ev.Damage != 500.0 || !ev.IsMagic || ev.SluggishTime != 1.0 || !ev.AttachMark {
		t.Fatalf("unexpected event values: %+v", ev)
	}
	if ev.SPGranted < 1.0 {
		t.Fatalf("expected SPGranted >= 1, got %v", ev.SPGranted)
	}
}

func TestWisdelCombatSkill3AmmoAndExplosion(t *testing.T) {
	cfg := wisdelRuntimeConfig{
		Slot:               3,
		S3Atk:              1.8,
		S3AtkScale3:        2.2,
		S3Prob:             1.0,
		S3TriggerTime:      6,
		S3BaseAttackTime:   2.9,
		S3MaxCnt:           2,
		TalentBombAtkScale: 1.85,
		TalentBombStun:     1.0,
		TalentBombRadius:   1.1,
		AppendAtkScale:     0.5,
		EnableThirdAttack:  true, // X-module
	}

	st := newWisdelCombatState("wisdel", Cell{0, 0}, "Right", cfg, 1000.0)

	// Activate S3
	candidateCells := []Cell{{0, 1}, {1, 0}}
	err := st.ActivateSkill(candidateCells, 500, 400, 50, 3500)
	if err != nil {
		t.Fatalf("activate S3 failed: %v", err)
	}
	if !st.SkillActive || st.SkillAmmo != 6 {
		t.Fatalf("expected S3 active with 6 ammo")
	}
	if len(st.Wards) != 2 {
		t.Fatalf("expected 2 wards deployed, got %d", len(st.Wards))
	}

	// Effective ATK should be 1000 * 2.8 = 2800
	if st.EffectiveATK() != 2800.0 {
		t.Fatalf("expected effective ATK 2800, got %v", st.EffectiveATK())
	}
	// Interval should be 2.1 + 2.9 = 5.0
	if st.BaseAttackInterval() != 5.0 {
		t.Fatalf("expected interval 5.0, got %v", st.BaseAttackInterval())
	}

	// Perform 1 attack
	primary := &enemy{hp: 50000}
	splash := &enemy{hp: 50000}

	instances, err := st.Attack(primary, []*enemy{splash}, 0.5)
	if err != nil {
		t.Fatalf("attack failed: %v", err)
	}
	if st.SkillAmmo != 5 {
		t.Fatalf("expected 5 ammo left, got %d", st.SkillAmmo)
	}

	// Verify instances: primary main hit + 2 aftershocks + bomb explosions
	hasBomb := false
	for _, inst := range instances {
		if inst.IsBombAOE {
			hasBomb = true
			if inst.Damage != 2800.0*1.85 {
				t.Fatalf("expected bomb damage %v, got %v", 2800.0*1.85, inst.Damage)
			}
		}
	}
	if !hasBomb {
		t.Fatalf("expected bomb explosion during S3")
	}

	// Consume remaining 5 ammo
	for i := 0; i < 5; i++ {
		_, _ = st.Attack(primary, []*enemy{splash}, 0.5)
	}
	if st.SkillActive || st.SkillAmmo != 0 {
		t.Fatalf("expected S3 ended after ammo depleted")
	}
}

func TestWisdelCombatSkill2Overdrive(t *testing.T) {
	cfg := wisdelRuntimeConfig{
		Slot:             2,
		S2Atk:            0.35,
		S2BaseAttackTime: -0.7,
		S2AtkScaleOl:     0.8,
	}
	st := newWisdelCombatState("wisdel", Cell{0, 0}, "Right", cfg, 1000.0)

	_ = st.ActivateSkill(nil, 0, 0, 0, 0)
	if !st.SkillActive || st.OverdrivePhase {
		t.Fatalf("expected S2 active, not yet overdrive")
	}

	// Tick 10s (half of 25s is 12.5s)
	st.Tick(10.0)
	if st.OverdrivePhase {
		t.Fatalf("expected not overdrive at 10s")
	}

	// Tick 3s more -> 13s -> Overdrive!
	st.Tick(3.0)
	if !st.OverdrivePhase {
		t.Fatalf("expected overdrive active at 13s")
	}

	primary := &enemy{hp: 10000}
	instances, err := st.Attack(primary, nil, 0.5)
	if err != nil {
		t.Fatalf("attack failed: %v", err)
	}
	// Overdrive should produce 4 hits
	if len(instances) != 4 {
		t.Fatalf("expected 4 overdrive hits, got %d", len(instances))
	}
	for _, inst := range instances {
		if inst.Damage != 1350.0*0.8 {
			t.Fatalf("expected overdrive damage %v, got %v", 1350.0*0.8, inst.Damage)
		}
	}

	// Tick until 25s
	st.Tick(13.0)
	if st.SkillActive {
		t.Fatalf("expected S2 ended after 25s")
	}
}
