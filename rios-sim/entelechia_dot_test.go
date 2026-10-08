package main

import (
	"encoding/json"
	"strings"
	"testing"
)

func TestEntelechiaDOTPulseActualDamageAndNoRecursiveRecovery(t *testing.T) {
	chdirRepoRootForData(t)
	for _, ml := range []int{2, 3} {
		for _, pot := range []int{1, 5} {
			for _, res := range []float64{0, 50} {
				r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: ml, Elite: 2, Level: 60, Potential: pot})
				if e != nil || r == nil {
					t.Fatal(e)
				}
				o := selfHealUnit(100)
				o.spec.CharID = "char_4010_etlchi"
				o.spec.ExactModuleTalent = r
				target := countedEnemy(1)
				target.spec.HP = 1000
				target.rebornAt = -1
				target.spec.DEF = 9999
				target.spec.RES = res
				amount := 350.0
				if ml == 3 {
					amount = 450
				}
				if pot == 5 {
					amount += 50
				}
				want := amount * (1 - res/100)
				v := &Verdict{}
				got, e := o.consumeEntelechiaDOTPulse(2, target, v)
				if e != nil || got != want || target.hp != 1000-want || v.DamageDealt != want || target.lastHitBy != o {
					t.Fatal("periodic magical damage wrong", got, e)
				}
				if o.hp != 100 || o.spec.MaxHP != 1000 || target.spec.HP != 1000 || len(v.Events) != 1 || v.Events[0].Kind != "entelechia_dot_pulse" || v.Events[0].T != 2 {
					t.Fatal("DoT recursively stole/healed or event wrong")
				}
				target.hp = 10
				got, e = o.consumeEntelechiaDOTPulse(3, target, v)
				if e != nil || got != 10 || target.hp != 0 || target.deathTime != 3 || len(v.Events) != 3 || v.Events[2].Kind != "kill" {
					t.Fatal("kill/actual cap wrong")
				}
			}
		}
	}
}
func TestEntelechiaDOTReportIndependentStateAndWireWitness(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 5})
	if e != nil || r == nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4010_etlchi"
	o.spec.ExactModuleTalent = r
	for _, report := range []bool{false, true} {
		for _, blocked := range []bool{false, true} {
			enemy := countedEnemy(1)
			enemy.index = 42
			enemy.rebornAt = -1
			enemy.hp = 10
			enemy.spec.RES = 50
			enemy.invincible = blocked
			var v *Verdict
			if report {
				v = &Verdict{}
			}
			got, e := o.consumeEntelechiaDOTPulse(7, enemy, v)
			want := 10.0
			if blocked {
				want = 0
			}
			if e != nil || got != want || enemy.hp != 10-want {
				t.Fatal("report changed damage")
			}
			if !blocked && enemy.deathTime != 7 {
				t.Fatal("nil report suppressed death state")
			}
			if report {
				if len(v.Events) == 0 || v.Events[0].Damage == nil {
					t.Fatal("damage witness missing")
				}
				d := v.Events[0].Damage
				if d.TargetIndex != 42 || d.Target != enemy.spec.Name || d.Raw != 500 || d.Resolved != 250 || d.Dealt != want || d.HPAfter != enemy.hp || d.DamageType != "MAGIC" || d.ModuleLevel != 3 || d.CandidateIndex != 1 || d.ModuleID != r.ModuleID {
					t.Fatal("damage witness wrong")
				}
				blob, e := json.Marshal(v.Events[0])
				if e != nil {
					t.Fatal(e)
				}
				var event Event
				if e = json.Unmarshal(blob, &event); e != nil || event.Damage == nil || *event.Damage != *d {
					t.Fatal("witness JSON lost")
				}
				n := 2
				if blocked {
					n = 1
				}
				if len(v.Events) != n {
					t.Fatal("zero damage recorded kill")
				}
			}
		}
	}
	b, e := json.Marshal(Event{T: 1, Kind: "kill", Who: "old"})
	if e != nil || strings.Contains(string(b), "damage") {
		t.Fatal("old event JSON changed")
	}
	v := &Verdict{}
	if got, e := o.consumeEntelechiaDOTPulse(1, nil, v); e != nil || got != 0 || len(v.Events) != 0 {
		t.Fatal("nil target emitted pulse")
	}
}

func TestEntelechiaDOTActualHitCallbackOrdering(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 5})
	if e != nil || r == nil {
		t.Fatal(e)
	}
	o := selfHealUnit(100)
	o.spec.CharID = "char_4010_etlchi"
	o.spec.ExactModuleTalent = r
	o.deploySeq = 17
	now := 2.0
	v := &Verdict{}
	ctx := &simCtx{time: &now, verdict: v}
	target := countedEnemy(1)
	target.sim = ctx
	target.rebornAt = -1
	target.spec.HP = 1000
	target.spec.RES = 50
	target.pm2Active = true
	target.spec.PhitCnt = 1
	target.spec.PhitMaxStack = 1
	target.spec.PhitRes = -20
	got, e := o.consumeEntelechiaDOTPulse(now, target, v)
	if e != nil || got != 250 || target.hp != 750 || target.phitStacks != 1 || target.spec.RES != 30 || !target.marked[17] || target.lastHitBy != o {
		t.Fatal("real onEnemyHit was not exercised in order", got, e)
	}
	if len(v.Events) != 1 || v.Events[0].Damage.ResBefore != 50 || v.Events[0].Damage.Resolved != 250 {
		t.Fatal("witness incorrectly read post-hit resistance")
	}
	now = 3
	got, e = o.consumeEntelechiaDOTPulse(now, target, v)
	if e != nil || got != 350 || target.hp != 400 || target.spec.RES != 30 || len(v.Events) != 2 || v.Events[1].Damage.ResBefore != 30 {
		t.Fatal("next damage failed to consume callback state")
	}
	if o.hp != 100 || o.spec.MaxHP != 1000 {
		t.Fatal("callback path recursively recovered/stole")
	}
}

func TestEntelechiaDOTPulseRefusesUnprovedSourceLifetime(t *testing.T) {
	chdirRepoRootForData(t)
	r, e := resolveExactCountModuleTalent(&OperatorStats{CharID: "char_4010_etlchi", Module: "uniequip_003_etlchi", ModuleLevel: 3, Elite: 2, Level: 60, Potential: 5})
	if e != nil || r == nil {
		t.Fatal(e)
	}
	for _, mode := range []string{"dead", "retreated", "wrong_source", "invincible", "dead_target"} {
		o := selfHealUnit(100)
		o.spec.CharID = "char_4010_etlchi"
		clone := *r
		o.spec.ExactModuleTalent = &clone
		target := countedEnemy(1)
		switch mode {
		case "dead":
			o.hp = 0
		case "retreated":
			o.retreated = true
		case "wrong_source":
			clone.CandidateIndex = 9
		case "invincible":
			target.invincible = true
		case "dead_target":
			target.hp = 0
		}
		before := target.hp
		v := &Verdict{}
		got, e := o.consumeEntelechiaDOTPulse(1, target, v)
		invalid := mode == "dead" || mode == "retreated" || mode == "wrong_source"
		if (e != nil) != invalid || got != 0 || target.hp != before || v.DamageDealt != 0 {
			t.Fatal("guard changed state", mode, e)
		}
		if (mode == "dead" || mode == "retreated") && (e == nil || !strings.Contains(e.Error(), "存续未证")) {
			t.Fatal("lifetime ambiguity silently ignored")
		}
	}
}
