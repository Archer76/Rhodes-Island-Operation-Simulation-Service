package main

import (
	"encoding/json"
	"math"
	"testing"
)

func TestCountIntrinsicRealProducerAndSourceMutations(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	for _, id := range []string{"enemy_1019_jshoot", "enemy_1019_jshoot_2"} {
		s, err := lib.At(id, 0)
		if err != nil {
			t.Fatal(err)
		}
		if s.IntrinsicCountVisibility == nil || s.IntrinsicCountVisibility.RecoveryDelay != 3 {
			t.Fatal("exact source unbound", id)
		}
		v := viewOf(s, id, 0, nil, nil, lib, false)
		raw, err := json.Marshal(unitSpecOf(v, 0, nil))
		if err != nil {
			t.Fatal(err)
		}
		var spec SpawnSpec
		if err := json.Unmarshal(raw, &spec); err != nil {
			t.Fatal(err)
		}
		if spec.IntrinsicCountVisibility == nil || spec.CountVisibility != nil {
			t.Fatal("intrinsic missing or whole visibility guessed")
		}
		scene := deploymentPrimitiveSpec(1)
		scene.Operators = []OperatorSpec{countSpeedUnit().spec}
		scene.Spawns = []SpawnSpec{spec}
		if got, err := runSim(scene); err == nil || got != nil {
			t.Fatal("intrinsic guessed external completeness")
		}
		c := s.Clone()
		c.IntrinsicCountVisibility.RecoveryDelay = 99
		if s.IntrinsicCountVisibility.RecoveryDelay != 3 {
			t.Fatal("clone source rule aliases")
		}
		for _, change := range []func(*EnemyStats){func(c *EnemyStats) { c.EnemyID = "wrong" }, func(c *EnemyStats) { c.Level = 1 }, func(c *EnemyStats) { c.RawSources[0].Kind = "stage_overwrite" }, func(c *EnemyStats) { c.RawSources[0].Raw = json.RawMessage(`{"description":"same name insufficient"}`) }} {
			c := s.Clone()
			change(c)
			if intrinsicCountSource(c) != nil {
				t.Fatal("source mutation recognized")
			}
			mutView := viewOf(c, c.EnemyID, c.Level, nil, nil, lib, false)
			if mutView.IntrinsicCountVisibility != nil {
				t.Fatal("handoff stale source recognized")
			}
			raw, err := json.Marshal(unitSpecOf(mutView, 0, nil))
			if err != nil {
				t.Fatal(err)
			}
			var out SpawnSpec
			if json.Unmarshal(raw, &out) != nil || out.IntrinsicCountVisibility != nil {
				t.Fatal("wire stale source recognized")
			}
			out.IntrinsicCountVisibility = &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: 3}
			out.CountVisibility = &CountVisibility{}
			ctx := &simCtx{spec: &Spec{Operators: []OperatorSpec{countSpeedUnit().spec}}}
			newEnemy(out, 0, [2]float64{}, ctx)
			if ctx.countError == nil {
				t.Fatal("dynamic stale production source admitted")
			}
		}
		local, err := lib.WithOverwrite("local-hidden", 0, map[string]json.RawMessage{"prefabKey": json.RawMessage(`"` + id + `"`)})
		if err != nil || local.IntrinsicCountVisibility != nil {
			t.Fatal("local override inherited unsafe recognition", err)
		}
	}
}
func TestCountIntrinsicBlockedRecoveryExactAndExternalState(t *testing.T) {
	e := countedEnemy(1)
	e.spec.IntrinsicCountVisibility = &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: 3}
	owner := hpSpeedUnit()
	scene := []*enemy{e}
	intrinsicCountTick(scene, 0)
	if !e.effectiveCountVisibility().blocksCount() {
		t.Fatal("initial hidden delayed")
	}
	e.blockedBy = owner
	intrinsicCountTick(scene, 1)
	if e.effectiveCountVisibility().blocksCount() {
		t.Fatal("blocked source not suppressed")
	}
	e.blockedBy = nil
	intrinsicCountTick(scene, 2)
	intrinsicCountTick(scene, math.Nextafter(5, 0))
	if e.effectiveCountVisibility().blocksCount() {
		t.Fatal("recovered early one ulp")
	}
	intrinsicCountTick(scene, 5)
	if !e.effectiveCountVisibility().blocksCount() {
		t.Fatal("deadline not restored")
	}
	e.spec.CountVisibility.InvisibleImmune = true
	if e.effectiveCountVisibility().blocksCount() {
		t.Fatal("immune intrinsic not suppressed")
	}
	e.spec.CountVisibility.InvisibleImmune = false
	if !e.effectiveCountVisibility().blocksCount() {
		t.Fatal("immunity erased source")
	}
	e.blockedBy = owner
	intrinsicCountTick(scene, 6)
	e.spec.CountVisibility.Camouflage = true
	if !e.effectiveCountVisibility().blocksCount() {
		t.Fatal("blocking erased external camouflage")
	}
	e.spec.CountVisibility = nil
	if e.effectiveCountVisibility() != nil {
		t.Fatal("intrinsic proved unknown external state")
	}
}
func TestCountIntrinsicSameFrameDeathAndRawContext(t *testing.T) {
	e := countedEnemy(1)
	e.spec.IntrinsicCountVisibility = &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: 3}
	owner := hpSpeedUnit()
	e.blockedBy = owner
	scene := []*enemy{e}
	intrinsicCountTick(scene, 10)
	owner.hp = 0
	intrinsicCountTick(scene, 10)
	if e.effectiveCountVisibility().blocksCount() || e.countHiddenRestoreAt != 13 {
		t.Fatal("same-frame dead blocker instant hidden/delayed deadline")
	}
	intrinsicCountTick(scene, 13)
	if !e.effectiveCountVisibility().blocksCount() {
		t.Fatal("death recovery not exact")
	}
	for _, raw := range []string{`{"unblocked_hidden":true}`, `{"unblocked_hidden":true,"recovery_delay":null}`, `{"unblocked_hidden":true,"recovery_delay":0}`, `{"unblocked_hidden":true,"recovery_delay":99}`} {
		var r IntrinsicCountVisibility
		if json.Unmarshal([]byte(raw), &r) == nil {
			t.Fatal("raw partial intrinsic accepted", raw)
		}
	}
	for _, delay := range []float64{-1, 0, 99, math.NaN(), math.Inf(1)} {
		s := SpawnSpec{CountVisibility: &CountVisibility{}, IntrinsicCountVisibility: &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: delay}}
		ctx := &simCtx{spec: &Spec{Operators: []OperatorSpec{countSpeedUnit().spec}}}
		newEnemy(s, 0, [2]float64{}, ctx)
		if ctx.countError == nil {
			t.Fatal("dynamic intrinsic escaped", delay)
		}
	}
}
func TestCountIntrinsicActualAttackTimerAndRawRuleGuard(t *testing.T) {
	chdirRepoRootForData(t)
	lib, err := LoadEnemyLibrary()
	if err != nil {
		t.Fatal(err)
	}
	source, err := lib.At("enemy_1019_jshoot", 0)
	if err != nil {
		t.Fatal(err)
	}
	o := countSpeedUnit()
	a := countedEnemy(1)
	b := countedEnemy(1)
	b.spec.EnemyID = source.EnemyID
	b.spec.Level = source.Level
	b.spec.RawSources = cloneEnemySources(source.RawSources)
	b.spec.IntrinsicCountVisibility = &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: 3}
	scene := []*enemy{a, b}
	intrinsicCountTick(scene, 0)
	if err := operatorsAttack([]*operator{o}, scene, .9, .9, &Spec{}, &Verdict{}); err != nil || a.hp != 1000 {
		t.Fatal("hidden source counted")
	}
	b.blockedBy = o
	intrinsicCountTick(scene, 1)
	if err := operatorsAttack([]*operator{o}, scene, .001, 1, &Spec{}, &Verdict{}); err != nil || a.hp != 900 {
		t.Fatal("blocked source failed accumulated timer")
	}
	spec := &Spec{Operators: []OperatorSpec{o.spec}, Spawns: []SpawnSpec{b.spec}}
	spec.Spawns[0].IntrinsicCountVisibility = &IntrinsicCountVisibility{UnblockedHidden: true, RecoveryDelay: -1}
	if len(countTimingGaps(spec)) == 0 {
		t.Fatal("negative recovery accepted")
	}
}
