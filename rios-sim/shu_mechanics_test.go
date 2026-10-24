package main

import (
	"math"
	"testing"
)

func shuUnit(name string, cell [2]float64) *operator {
	return &operator{
		hp:   1000,
		cell: cell,
		spec: OperatorSpec{Name: name, CharID: name, MaxHP: 1000, ATK: 100, DEF: 0, AttackInterval: 1.0},
	}
}

func shuStateForTest(t *testing.T, slot int) *ShuBattleState {
	t.Helper()
	st := &OperatorStats{
		CharID: shuCharID, Elite: 2, Level: 60, Potential: 5,
		Module: shuModuleID, ModuleLevel: 3,
	}
	cfg := shuCfgForTest(t, st, slot, 10)
	return newShuBattleState(cfg)
}

// TestShuSowingGeometry 天赋一播种的是「目标格 + 上下左右四格」，共 5 格；
// 模组三的出生播种只播自身格（range 0-1 = 单格）。
func TestShuSowingGeometry(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)

	added := st.sowAround([2]int{2, 2}, "黍")
	if added != 5 {
		t.Fatalf("sowAround 新增 %d 格，期望 5", added)
	}
	for _, c := range [][2]int{{2, 2}, {1, 2}, {3, 2}, {2, 1}, {2, 3}} {
		if !st.isSown(c) {
			t.Fatalf("(%d,%d) 应当被播种", c[0], c[1])
		}
	}
	// 重复播种不叠加、也不新增。
	if again := st.sowAround([2]int{2, 2}, "黍"); again != 0 {
		t.Fatalf("重复播种新增了 %d 格，期望 0", again)
	}
	if st.isSown([2]int{4, 4}) {
		t.Fatal("(4,4) 不该被播种")
	}

	born := shuStateForTest(t, 3)
	if !born.sowSelf([2]int{5, 5}, "黍") {
		t.Fatal("sowSelf 应当播下 (5,5)")
	}
	if born.isSown([2]int{6, 5}) {
		t.Fatal("部署播种只播自身格，不该扩四邻")
	}
}

// TestShuSownTileRegenAndProtect 地块效果：每秒回血 + 庇护减伤。
func TestShuSownTileRegenAndProtect(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{2, 2}, "黍")
	if got := st.protectAt([2]int{2, 2}); math.Abs(got-0.17) > 1e-9 {
		t.Fatalf("模组三级庇护应为 0.17，got %v", got)
	}

	shu := shuUnit("黍", [2]float64{2, 2})
	shu.spec.CharID = shuCharID
	shu.shuState = st
	ally := shuUnit("友方", [2]float64{3, 2})
	ally.hp = 100
	ops := []*operator{shu, ally}
	spec := &Spec{Operators: []OperatorSpec{shu.spec, ally.spec}}
	for i := range spec.Operators {
		spec.Operators[i].Cell = [2]int{int(ops[i].cell[0]), int(ops[i].cell[1])}
	}

	// 1 秒的地块回血 = hp_recovery_per_sec（85）。
	shuTick(ops, nil, 1.0, 1.0, spec, &Verdict{})
	if math.Abs(ally.hp-185) > 1e-6 {
		t.Fatalf("地块回血后 hp=%.4f，期望 185", ally.hp)
	}

	// 庇护：100 点伤害 → 100 × (1−0.17) = 83。
	ctx := &simCtx{objs: &ops}
	ally.sim = ctx
	ally.hp = 1000
	ally.take(100)
	if math.Abs(ally.hp-(1000-83)) > 1e-6 {
		t.Fatalf("庇护后 hp=%.4f，期望 %.4f", ally.hp, float64(1000-83))
	}
}

// TestShuSeasonThreeTiers 天赋二三档：不同职业加生命上限、相同职业加攻速、
// 编队四岁加攻击力并每 4 秒给 1 点技力。
func TestShuSeasonThreeTiers(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 1)
	cfg := st.Config
	if !cfg.SeasonEnabled {
		t.Fatal("E2 应启用天有四时")
	}

	mk := func(name, prof string) *operator {
		op := shuUnit(name, [2]float64{0, 0})
		op.spec.Profession = prof
		return op
	}

	// 3 名不同职业。
	ops := []*operator{mk("a", "TANK"), mk("b", "MEDIC"), mk("c", "SNIPER")}
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if math.Abs(op.maxHP()-1000*1.12) > 1e-6 {
			t.Fatalf("%s 生命上限 = %.4f，期望 1120", op.spec.Name, op.maxHP())
		}
		if math.Abs(op.interval()-1.0) > 1e-9 {
			t.Fatalf("%s 不同职业不该加攻速，interval=%.4f", op.spec.Name, op.interval())
		}
	}

	// 3 名相同职业 → 攻速 +12（间隔 100/112）。
	ops = []*operator{mk("a", "TANK"), mk("b", "TANK"), mk("c", "TANK")}
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if op.shuAspd != 12 {
			t.Fatalf("%s 攻速加成 = %v，期望 12", op.spec.Name, op.shuAspd)
		}
		if math.Abs(op.interval()-1.0*100.0/112.0) > 1e-9 {
			t.Fatalf("%s 间隔 = %.6f，期望 %.6f", op.spec.Name, op.interval(), 100.0/112.0)
		}
	}

	// 编队 4 岁 → 攻击力 +12% 且 4 秒 1 点技力。
	st.SeasonSuiCount = 4
	ops = []*operator{mk("a", "TANK"), mk("b", "MEDIC"), mk("c", "SNIPER"), mk("d", "TANK")}
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if math.Abs(op.atk()-112) > 1e-6 {
			t.Fatalf("%s 攻击力 = %.4f，期望 112", op.spec.Name, op.atk())
		}
	}
	st.SeasonSPTimer = 3.9
	applyShuSeason(ops, st, 0.2)
	// 3.9 + 0.2 = 4.1 ⇒ 发放一次 1 点技力，余 0.1 秒。
	if math.Abs(st.SeasonSPTimer-0.1) > 1e-9 {
		t.Fatalf("4 秒计时余量 = %v，期望 0.1", st.SeasonSPTimer)
	}
	for _, op := range ops {
		if math.Abs(op.sp-1) > 1e-9 {
			t.Fatalf("%s 技力 = %v，期望 1", op.spec.Name, op.sp)
		}
	}
}

// TestShuS1ChargedHeal 技能一：攻击时消耗一层充能，治疗范围内血量不足一半的友方，
// 并因「治疗干员」触发天赋一播种。
func TestShuS1ChargedHeal(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 1)
	shu := shuUnit("黍", [2]float64{2, 2})
	shu.spec.CharID = shuCharID
	shu.spec.ATK = 500
	shu.shuState = st
	st.Charges = 1

	ally := shuUnit("友方", [2]float64{3, 2})
	ally.hp = 400 // 40% < 50%
	healthy := shuUnit("健康", [2]float64{1, 2})
	healthy.hp = 900

	applyShuS1Heal(shu, []*operator{shu, ally, healthy}, &Verdict{})
	if st.Charges != 0 {
		t.Fatalf("充能应消耗 1 层，剩 %d", st.Charges)
	}
	if ally.hp <= 400 {
		t.Fatalf("友方未被治疗，hp=%.2f", ally.hp)
	}
	if healthy.hp != 900 {
		t.Fatalf("满血友方不该被治疗，hp=%.2f", healthy.hp)
	}
	// 治疗量 = 攻击力 × heal_scale（1.8）= 900，夹在 1000 上限。
	if math.Abs(ally.hp-1000) > 1e-6 {
		t.Fatalf("治疗量不对：hp=%.2f", ally.hp)
	}
	for _, c := range [][2]int{{3, 2}, {2, 2}, {4, 2}, {3, 1}, {3, 3}} {
		if !st.isSown(c) {
			t.Fatalf("(%d,%d) 应在治疗后被播种", c[0], c[1])
		}
	}
}

// TestShuModuleLowHealBonus 模组特性：治疗生命低于 50% 的友方时治疗量 ×1.15。
func TestShuModuleLowHealBonus(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 2)
	if st.Config.LowHealScale != 1.15 || st.Config.LowHealRatio != 0.5 {
		t.Fatalf("模组特性未解析：%v/%v", st.Config.LowHealScale, st.Config.LowHealRatio)
	}
	shu := shuUnit("黍", [2]float64{2, 2})
	shu.spec.CharID = shuCharID
	shu.shuState = st

	low := shuUnit("低血", [2]float64{3, 2})
	low.hp = 400 // 40% < 50%
	if got := low.healFromCharacter(shu, 100, &Verdict{}); got != 115 {
		t.Fatalf("低血目标治疗量 = %v，期望 115（×1.15）", got)
	}
	healthy := shuUnit("高血", [2]float64{1, 2})
	healthy.hp = 600 // 60% ≥ 50%
	if got := healthy.healFromCharacter(shu, 100, &Verdict{}); got != 100 {
		t.Fatalf("高血目标治疗量 = %v，期望 100", got)
	}
}

// TestShuS3TeleportRestoresRouteSnapshot 技能三传送：锚点记的是完整路线快照，
// 传送后 legIndex/legU/position/progress 一起回到锚点。
func TestShuS3TeleportRestoresRouteSnapshot(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{3, 2}, "黍")

	e := &enemy{spec: SpawnSpec{Name: "e"}, hp: 100, index: 7}
	e.legIndex = 2
	e.legU = 1.25
	e.position = [2]float64{3, 2}
	e.progress = 1.25
	st.anchorIfSown(e, [2]int{3, 2})

	// 未超过 2 格：不传送。
	e.position = [2]float64{5, 2}
	if _, ok := st.shouldTeleport(e); ok {
		t.Fatal("距离 2 格不该触发传送")
	}
	// 超过 2 格：触发并恢复快照。
	e.position = [2]float64{6, 2}
	a, ok := st.shouldTeleport(e)
	if !ok {
		t.Fatal("距离 3 格应当触发传送")
	}
	st.restore(e, a)
	if e.legIndex != 2 || e.legU != 1.25 || e.position != [2]float64{3, 2} || e.progress != 1.25 {
		t.Fatalf("快照未完整恢复：leg=%d legU=%v pos=%v progress=%v",
			e.legIndex, e.legU, e.position, e.progress)
	}
	if _, still := st.TeleportAnchors[e.index]; still {
		t.Fatal("传送后锚点应被消耗")
	}
}
