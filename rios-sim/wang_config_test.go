package main

import (
	"encoding/json"
	"testing"
)

func TestWangConfigSelectedSourcesAndModuleReplacement(t *testing.T) {
	for _, c := range []struct {
		elite, pot, mod, slot int
		cost                  float64
		deploy, deck          int
		damage, pen           float64
	}{{0, 1, 0, 1, 3, 4, 5, 0, 0}, {1, 3, 0, 2, 3, 6, 7, 0, 0}, {2, 1, 0, 3, 3, 6, 7, .1, 9}, {2, 1, 1, 3, 2, 7, 7, .1, 9}, {2, 1, 2, 2, 2, 7, 7, .12, 11}, {2, 5, 3, 1, 2, 8, 8, .15, 13}} {
		st := &OperatorStats{CharID: wangCharID, Elite: c.elite, Level: 60, Potential: c.pot, ModuleLevel: c.mod}
		if c.mod > 0 {
			st.Module = wangModuleID
		}
		source, err := buildWangSourceSpec(st, c.slot, 10)
		if err != nil {
			t.Fatal(err)
		}
		cfg, err := decodeWangRuntimeConfig(source)
		if err != nil {
			t.Fatal(err)
		}
		if cfg.DeployCost != c.cost || cfg.DeployMaximum != c.deploy || cfg.InventoryMaximum != c.deck || cfg.PerDamage != c.damage || cfg.PerResistPenetration != c.pen {
			t.Fatalf("E%d P%d M%d config %+v", c.elite, c.pot, c.mod, cfg)
		}
		if cfg.Slot == 1 && (cfg.DamageScale != 1.35 || cfg.EffectDuration != 6.5 || cfg.Replenish != 2) {
			t.Fatal(cfg)
		}
		if cfg.Slot == 2 && (cfg.DamageScale != 5.8 || cfg.EffectDuration != 6 || cfg.SlowFactor != .5 || cfg.Replenish != 2) {
			t.Fatal(cfg)
		}
		if cfg.Slot == 3 && (cfg.DamageScale != 3.8 || cfg.Ammo != 20 || cfg.Replenish != 8) {
			t.Fatal(cfg)
		}
	}
}
func TestWangConfigMissingOrDuplicateSourceRejected(t *testing.T) {
	if _, err := decodeWangRuntimeConfig(nil); err == nil {
		t.Fatal("nil source accepted")
	}
	if _, err := wangStrictBB(json.RawMessage(`{"blackboard":[{"key":"cnt","value":2},{"key":"cnt","value":3}]}`)); err == nil {
		t.Fatal("duplicate key accepted")
	}
	s, err := buildWangSourceSpec(&OperatorStats{CharID: wangCharID, Elite: 2, Level: 60, Potential: 1}, 1, 10)
	if err != nil {
		t.Fatal(err)
	}
	s.TokenSkill.Raw = json.RawMessage(`{"blackboard":[]}`)
	if _, err := decodeWangRuntimeConfig(s); err == nil {
		t.Fatal("missing damage silently defaulted")
	}
}
