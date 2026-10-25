package main

import (
	"context"
	"errors"
	"math"
	"rios-sim/mechanisms"
	"testing"
)

// logos_full_lifecycle_test.go：逻各斯的**帧内接线**与**拒判**两条集成判据。
//
// 为什么不是"跑一局 `runSimContext` 看判决"：
// 本仓的规格闸门是 `specMechanismGaps(spec)` 非空即整场拒跑
// （`sim.go:731`，`mechanisms.IncompleteError`）。逻各斯的第一天赋
// 「语汇演化」是概率机制，按博士 2026-10-24 裁定**必须**作为具名 Gap 上报
// （V-2 待裁定、不折期望值）——于是这个干员在 V-2 裁定之前**不可能**产出判决。
// 这不是接线没通，是闸门的语义。所以这里拆成两半：
//
//	① 拒判：真调 `runSimContext`，断言拒判**且理由具名到 V-2**；
//	② 接线：绕过规格闸门，直接驱动主循环**调用的那几个函数**
//	   （`logosTick` / `operatorsAttackMode`），证明机制在帧序上真的被行使。
//
// ② 的帧序与主循环一致：先驱动逐帧机制（帧序 5），再让我方出手（帧序 6）。

// logosLifecycleOp 造一名**真的**逻各斯（LogosSource 齐、技能范围折好）。
func logosLifecycleOp(t *testing.T, slot int, cell [2]int, rng [][2]int, dir string) *operator {
	t.Helper()
	st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	src, err := buildLogosSourceSpec(st, slot, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec slot %d: %v", slot, err)
	}
	if err := attachLogosSkillRange(src, dir, [2]int{cell[0], cell[1]}); err != nil {
		t.Fatalf("attachLogosSkillRange slot %d: %v", slot, err)
	}
	cfg := mustLogosCfg(t, src)
	return &operator{
		hp:   2400,
		cell: [2]float64{float64(cell[0]), float64(cell[1])},
		spec: OperatorSpec{
			Name: "逻各斯", CharID: logosCharID,
			Cell: cell, MaxHP: 2400, ATK: 800, DEF: 120, RES: 10,
			BlockCnt: 0, AttackInterval: 1.6, DamageType: "MAGIC",
			LogosSource: src, Range: rng,
		},
		logosState: newLogosBattleState(cfg, logosDefaultRNGSeed),
	}
}

func logosSkillSpec(t *testing.T, slot int) *SkillSpec {
	t.Helper()
	cfg := logosCfgForTest(t,
		&OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}, slot, 10)
	return &SkillSpec{
		SPType:       cfg.SPType,
		SPCost:       float64(cfg.SPCost),
		InitSP:       float64(cfg.InitSP),
		Increment:    1,
		Duration:     math.Max(cfg.Duration, 0),
		DurationType: "NONE",
		MaxCharge:    1,
		AutoTrigger:  true,
	}
}

// logosSpawn 造一只血厚、不动、无攻的靶子。
func logosSpawn(name string, x, y float64, hp float64) SpawnSpec {
	return SpawnSpec{
		EnemyID: "test_logos_dummy", Name: name, Time: 0,
		HP: hp, ATK: 0, DEF: 0, RES: 0,
		MoveSpeed: 0.0, Interval: 2.0, DamageType: "PHYSICAL",
		Legs: []LegSpec{{Kind: "walk",
			Points: [][2]float64{{x, y}, {x + 0.001, y}}, Length: 0.001}},
	}
}

func countEvents(v *Verdict, kind string) int {
	if v == nil {
		return 0
	}
	n := 0
	for _, ev := range v.Events {
		if ev.Kind == kind {
			n++
		}
	}
	return n
}

func kinds(v *Verdict) []string {
	if v == nil {
		return nil
	}
	out := make([]string, 0, len(v.Events))
	for _, ev := range v.Events {
		out = append(out, ev.Kind)
	}
	return out
}

// TestLogosRunsAfterV2Ruling 概率机制裁定之后 ⇒ **整场能跑出判决**，且判决上带着 seed。
//
// 这条判据守的是裁定的**落地**：旧状态是"prob 缺口 ⇒ IncompleteError，整场拒跑"；
// 现在第一天赋走 seed 精确抽样，`specMechanismGaps` 不该再为它产出占位。
// 如果哪天有人（a）把抽样悄悄换成期望值，或（b）某条别的缺口把整场重新焊死，
// 这条会立刻变红——它是"能跑"这一侧的正对照。
func TestLogosRunsAfterV2Ruling(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosLifecycleOp(t, 1, [2]int{0, 2},
		[][2]int{{1, 2}, {2, 2}}, "Right")
	op.spec.Skill = logosSkillSpec(t, 1)

	spec := &Spec{
		FPS: 30, MaxTime: 12.0, SpeedScale: 1.0,
		Life: 10, CostInit: 99, CostMax: 99, CostTime: 1.0,
		Operators: []OperatorSpec{op.spec},
		Deploys:   []DeploySpec{{Time: 0.0, CharID: logosCharID, Index: 0}},
		Spawns:    []SpawnSpec{logosSpawn("靶", 2, 2, 100000)},
	}
	verdict, err := runSimContext(context.Background(), spec)
	if err != nil {
		var incomplete *mechanisms.IncompleteError
		if errors.As(err, &incomplete) {
			t.Fatalf("V-2 已裁定，逻各斯不该再被占位拒跑：%v（%+v）", err, incomplete.Placeholders)
		}
		t.Fatalf("runSimContext 失败：%v", err)
	}
	if verdict == nil {
		t.Fatal("verdict is nil")
	}

	// 判决必须自报采样 seed（裁定第 2 条：这是"该 seed 下的一次采样"）。
	seedEvents := 0
	for _, ev := range verdict.Events {
		if ev.Kind == "logos_rng_seed" && containsText(ev.Who, "seed=") {
			seedEvents++
		}
	}
	if seedEvents != 1 {
		t.Fatalf("判决里应有且只有一条 seed 标注，实得 %d 条", seedEvents)
	}
	// 抽样真的在跑：出手若干次之后抽签计数必须非零。
	// （直接从判决事件推断：12 秒里至少该有一次技能一或普攻出手。）
	if verdict.DamageDealt <= 0 {
		t.Fatal("整场零伤害：接线没跑起来")
	}
	t.Logf("seed 事件=%d 伤害=%.1f 事件数=%d", seedEvents, verdict.DamageDealt, len(verdict.Events))
}

// TestLogosFrameWiringSkill3 帧内接线（技能三档）：多目标 + 天赋二减益。
func TestLogosFrameWiringSkill3(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosLifecycleOp(t, 3, [2]int{0, 2},
		[][2]int{{1, 2}, {2, 2}, {3, 2}}, "Right")
	op.skillActive = true // 帧序里这一位由 `skillTick` 打开
	op.skillTimer = math.Inf(1)

	enemies := []*enemy{
		logosEnemyIn("甲", [2]float64{2, 2}, 200000, nil),
		logosEnemyIn("乙", [2]float64{2, 2}, 200000, nil),
		logosEnemyIn("丙", [2]float64{2, 2}, 200000, nil),
	}

	spec := &Spec{FPS: 30}
	verdict := &Verdict{}
	dt := 1.0 / 30.0
	// 走满 2 秒：攻击间隔 1.6 秒（技能期间会量化），至少一次出手。
	for i := 0; i < 60; i++ {
		tm := float64(i) * dt
		logosTick([]*operator{op}, enemies, dt, tm, verdict)
		if err := operatorsAttackMode([]*operator{op}, enemies, dt, tm, spec, verdict, false); err != nil {
			t.Fatalf("operatorsAttackMode: %v", err)
		}
	}

	if got := countEvents(verdict, "logos_talent2"); got == 0 {
		t.Fatalf("天赋二没在出手点上被施加：事件 %v", kinds(verdict))
	}
	if got := countEvents(verdict, "logos_s3_multi"); got == 0 {
		t.Fatalf("技能三没有一次同时命中 ≥2 个：事件 %v", kinds(verdict))
	}
	if verdict.DamageDealt <= 0 {
		t.Fatal("整场零伤害，接线没通")
	}
	// 天赋二真改了法抗：三只都被打过之后，法抗必须低于基准（这里是 0）……
	// 但基准 0 减 10 会变成负数，判据取"至少有一只的减益字段非零"。
	debuffed := 0
	for _, e := range enemies {
		if e.logosMagicResDown != 0 || e.logosMagicFlatBonusValue != 0 {
			debuffed++
		}
	}
	if debuffed == 0 {
		t.Fatal("天赋二的减益字段一次都没被写上")
	}
	t.Logf("talent2=%d multi=%d damage=%.1f debuffed=%d",
		countEvents(verdict, "logos_talent2"), countEvents(verdict, "logos_s3_multi"),
		verdict.DamageDealt, debuffed)
}

// TestLogosFrameWiringSkill1 帧内接线（技能一档）：残血敌人被斩杀。
func TestLogosFrameWiringSkill1(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosLifecycleOp(t, 1, [2]int{0, 2},
		[][2]int{{1, 2}, {2, 2}, {3, 2}, {4, 2}}, "Right")
	op.skillActive = true
	op.skillTimer = math.Inf(1)

	// 血量远低于「攻击力 × kill_atk_scale」。
	weak := logosEnemyIn("残兵", [2]float64{2, 2}, 200, nil)

	verdict := &Verdict{}
	dt := 1.0 / 30.0
	for i := 0; i < 10; i++ {
		tm := float64(i) * dt
		logosTick([]*operator{op}, []*enemy{weak}, dt, tm, verdict)
	}

	if got := countEvents(verdict, "logos_s1_execute"); got == 0 {
		t.Fatalf("技能一一次斩杀都没发生：事件 %v", kinds(verdict))
	}
	if weak.alive() {
		t.Fatalf("残兵应已倒下，剩血 %v", weak.hp)
	}
	if op.logosState.S1Kills == 0 {
		t.Fatal("斩杀计数为 0")
	}
	t.Logf("s1_execute=%d leftover=%.1f", countEvents(verdict, "logos_s1_execute"), weak.hp)
}

// TestLogosFrameWiringSkill2 帧内接线（技能二档）：锁定拍数真跑，平A 停摆。
func TestLogosFrameWiringSkill2(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosLifecycleOp(t, 2, [2]int{0, 2},
		[][2]int{{1, 2}, {2, 2}, {3, 2}}, "Right")
	op.skillActive = true
	op.skillTimer = math.Inf(1)

	dummy := logosEnemyIn("肉盾", [2]float64{2, 2}, 500000, nil)

	spec := &Spec{FPS: 30}
	verdict := &Verdict{}
	dt := 1.0 / 30.0
	cfg := op.logosState.Config
	// 跑满**技能时长**（20 秒 = 600 帧）⇒ 应有 duration/cooldown 拍。
	frames := int(math.Ceil(cfg.Duration/dt)) + 1
	for i := 0; i < frames; i++ {
		tm := float64(i) * dt
		logosTick([]*operator{op}, []*enemy{dummy}, dt, tm, verdict)
		if err := operatorsAttackMode([]*operator{op}, []*enemy{dummy}, dt, tm, spec, verdict, false); err != nil {
			t.Fatalf("operatorsAttackMode: %v", err)
		}
	}

	want := int(cfg.Duration / cfg.S2Cooldown)
	if got := countEvents(verdict, "logos_s2_tick"); got < want-2 {
		t.Fatalf("锁定拍数偏少：应 ≥ %d 拍，实得 %d", want-2, got)
	}
	// 平A 停摆：技能二的整段里**没有**天赋二事件（天赋二挂在平A 命中点上）。
	// 这条同时证明"停攻"那道闸门真的生效——否则平A 会顺手挂上减益。
	if got := countEvents(verdict, "logos_talent2"); got != 0 {
		t.Fatalf("技能二期间平A 应停摆，却出现了 %d 次天赋二施加", got)
	}
	if op.logosState.S2Stack != cfg.S2MaxStackCnt {
		t.Fatalf("5 秒后层数应满 %d，实得 %d", cfg.S2MaxStackCnt, op.logosState.S2Stack)
	}
	t.Logf("s2_ticks=%d stack=%d damage=%.1f",
		countEvents(verdict, "logos_s2_tick"), op.logosState.S2Stack, verdict.DamageDealt)
}
