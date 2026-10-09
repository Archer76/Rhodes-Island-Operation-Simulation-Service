package main

import (
	"testing"
)

func TestChen3CombatStateAndTalent2(t *testing.T) {
	cfg := chen3RuntimeConfig{
		Slot:              1,
		S1AtkScale:        1.2,
		Talent1Atk:        0.16,
		Talent1ASPD:       16.0,
		Talent2Interval:   6.0,
		Talent2HealMinAtk: 50.0,
		Talent2HealMaxAtk: 200.0,
	}
	c := newChen3CombatState("chen3", Cell{1, 1}, "Right", cfg)

	// 经过 5 秒，未达 6 秒，不应触发天赋2
	heal, dodge := c.TickTalent2(5.0, 1000)
	if heal != 0 || dodge || c.HasDodgeCharge {
		t.Fatalf("talent2 triggered prematurely")
	}

	// 再经过 1.5 秒，总计 6.5 秒，触发天赋2
	heal, dodge = c.TickTalent2(1.5, 1000)
	if heal <= 0 || !dodge || !c.HasDodgeCharge {
		t.Fatalf("talent2 should trigger after 6s")
	}

	// 受到攻击时消耗闪避
	if !c.CheckAndConsumeDodge(true) {
		t.Fatalf("expected dodge to succeed")
	}
	// 再次受击应不再闪避
	if c.CheckAndConsumeDodge(true) {
		t.Fatalf("expected dodge charge already consumed")
	}

	// 开启技1
	if err := c.ActivateSkill(1000); err != nil {
		t.Fatalf("activate skill failed: %v", err)
	}
	if !c.SkillActive {
		t.Fatalf("skill should be active")
	}
	// 攻击倍率应为 1 + 0.16 + 1.2 = 2.36
	if effAtk := c.EffectiveATKMultiplier(); effAtk < 2.35 || effAtk > 2.37 {
		t.Fatalf("expected effective atk around 2.36, got %v", effAtk)
	}
}

func TestChen3S2StateFlow(t *testing.T) {
	cfg := chen3RuntimeConfig{
		Slot:          2,
		S2AtkScale:    4.8,
		S2Strikes:     10,
		S2Duration:    6.0,
		S2RespawnAtk:  3.0,
		S2RespawnProb: 0.6,
	}
	c := newChen3CombatState("chen3", Cell{2, 2}, "Right", cfg)
	if err := c.ActivateSkill(1000); err != nil {
		t.Fatalf("activate S2 failed: %v", err)
	}
	if !c.S2Slashing || c.S2StrikesLeft != 10 {
		t.Fatalf("S2 slashing state mismatch")
	}

	// 模拟目标存活且可部署，斩击结束位移至 (3, 2)
	c.S2Target = &enemy{position: [2]float64{3, 2}, hp: 500}
	c.EndSkill(true)

	if c.Position != (Cell{3, 2}) {
		t.Fatalf("expected displaced to (3, 2), got %v", c.Position)
	}
	if !c.S2RespawnBuff {
		t.Fatalf("expected S2 respawn buff active")
	}
	// 攻击倍率加上 respawn buff 3.0
	if effAtk := c.EffectiveATKMultiplier(); effAtk < 4.0 {
		t.Fatalf("expected respawn buff atk multiplier >= 4.0, got %v", effAtk)
	}
}
