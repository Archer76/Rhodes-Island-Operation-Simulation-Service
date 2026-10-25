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

// TestShuTeleportManhattanNotChebyshev 距离口径反例：站位 (2,2) 距锚点 (0,0)
// 在切比雪夫口径下是 2 格（不传），在曼哈顿口径下是 4 格（传）。
func TestShuTeleportManhattanNotChebyshev(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{0, 0}, "黍")

	e := &enemy{spec: SpawnSpec{Name: "e"}, hp: 100, index: 7}
	st.TeleportAnchors[e.index] = &ShuTeleportAnchor{AnchorCell: [2]int{0, 0}}

	// 斜向 2 格：切比雪夫 2（≤2 不传）、曼哈顿 4（>2 传）。
	if _, ok := st.shouldTeleportOnEnter(e, [2]int{2, 2}); !ok {
		t.Fatal("斜向 (2,2) 在曼哈顿口径下应触发（4 > 2）；不触发说明还在用切比雪夫")
	}
	// 阈值边界：曼哈顿 2（未超过）不传——游戏原文「超过」，严格大于。
	if _, ok := st.shouldTeleportOnEnter(e, [2]int{1, 1}); ok {
		t.Fatal("曼哈顿 2 等于阈值，不该触发（严格大于）")
	}
}

// TestShuTeleportOnEnterNotPerFrame 触发时机：站在远处但不换格时**不判定**，
// 只有进入新地块的那一帧才判定。逐帧扫距离会在第一帧就传。
func TestShuTeleportOnEnterNotPerFrame(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{0, 0}, "黍")

	shu := shuUnit("黍", [2]float64{0, 0})
	shu.spec.CharID = shuCharID
	shu.shuState = st

	e := &enemy{spec: SpawnSpec{Name: "e"}, hp: 100, index: 3}
	st.TeleportAnchors[e.index] = &ShuTeleportAnchor{AnchorCell: [2]int{0, 0}}
	e.position = [2]float64{5, 0}
	// 已经站在这格里（LastCells 记录同格）：这一帧不算「进入」。
	st.LastCells[e.index] = [2]int{5, 0}

	applyShuTeleport(shu, st, []*enemy{e}, &Verdict{}, 1.0)
	if e.position != [2]float64{5, 0} {
		t.Fatalf("没换格却触发了传送：pos=%v", e.position)
	}
	// 进入下一格：这一帧判定，曼哈顿 6 > 2 → 传回 (0,0)。
	e.position = [2]float64{6, 0}
	applyShuTeleport(shu, st, []*enemy{e}, &Verdict{}, 1.1)
	if e.position != [2]float64{0, 0} {
		t.Fatalf("进入新格后应传送回记录地块中心，pos=%v", e.position)
	}
}

// TestShuTeleportKeepsPathAndMarker 传送只改位置、回地块中心；路径进度
// （legIndex/legU/progress）不变，播种标记保留可再次触发。
func TestShuTeleportKeepsPathAndMarker(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{0, 0}, "黍")

	shu := shuUnit("黍", [2]float64{0, 0})
	shu.spec.CharID = shuCharID
	shu.shuState = st

	e := &enemy{spec: SpawnSpec{Name: "e"}, hp: 100, index: 5}
	st.TeleportAnchors[e.index] = &ShuTeleportAnchor{AnchorCell: [2]int{0, 0}}
	e.legIndex = 2
	e.legU = 1.25
	e.progress = 1.25
	e.position = [2]float64{5, 0}

	applyShuTeleport(shu, st, []*enemy{e}, &Verdict{}, 1.0)
	if e.position != [2]float64{0, 0} {
		t.Fatalf("落点应为记录地块中心 (0,0)，got %v", e.position)
	}
	if e.legIndex != 2 || e.legU != 1.25 || e.progress != 1.25 {
		t.Fatalf("传送不应重置路径进度：leg=%d legU=%v progress=%v", e.legIndex, e.legU, e.progress)
	}
	if _, ok := st.TeleportAnchors[e.index]; !ok {
		t.Fatal("传送后标记应保留（PRTS：仅敌人消失时清除）")
	}
}

// TestShuTeleportImmuneEnemyNotMarked 免疫传送(黍) 的敌人不会被施加标记。
func TestShuTeleportImmuneEnemyNotMarked(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{0, 0}, "黍")

	shu := shuUnit("黍", [2]float64{0, 0})
	shu.spec.CharID = shuCharID
	shu.shuState = st

	e := &enemy{spec: SpawnSpec{Name: "e", Immunities: map[string]bool{"teleportImmune": true}}, hp: 100, index: 9}
	e.position = [2]float64{0, 0}
	applyShuTeleport(shu, st, []*enemy{e}, &Verdict{}, 1.0)
	if _, ok := st.TeleportAnchors[e.index]; ok {
		t.Fatal("免疫传送的敌人不应被施加播种标记")
	}
}

// TestShuS3HealsWithoutTargets 技能三「无攻击目标时普通攻击可直接进行治疗」。
// 旧实现里没有目标就 continue，这条会红。
func TestShuS3HealsWithoutTargets(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)

	shu := &operator{
		hp:   1000,
		cell: [2]float64{2, 2},
		spec: OperatorSpec{
			Name: "黍", CharID: shuCharID, MaxHP: 1000, ATK: 500, AttackInterval: 1.0,
			Range: [][2]int{{2, 2}, {3, 2}, {2, 3}, {1, 2}, {2, 1}},
			Skill: &SkillSpec{SPType: spAuto, SPCost: 45, InitSP: 45, Duration: 30, MaxCharge: 1},
		},
	}
	shu.shuState = st
	shu.skillActive = true

	ally := &operator{
		hp:   400,
		cell: [2]float64{3, 2},
		spec: OperatorSpec{Name: "友方", CharID: "char_208_melan", MaxHP: 1000, ATK: 100, AttackInterval: 1.0},
	}
	ops := []*operator{shu, ally}
	spec := &Spec{FPS: 30, Operators: []OperatorSpec{shu.spec, ally.spec}}

	for i := 0; i < 40; i++ {
		if err := operatorsAttackFrame(ops, nil, float64(i)/30.0, spec, &Verdict{}); err != nil {
			t.Fatalf("attack frame: %v", err)
		}
	}
	if ally.hp <= 400 {
		t.Fatalf("无攻击目标时技能三应直接治疗友方，hp=%.2f", ally.hp)
	}
}

func TestShuSownClearedOnRetreat(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 3)
	st.sowAround([2]int{2, 2}, "黍")

	shu := shuUnit("黍", [2]float64{2, 2})
	shu.spec.CharID = shuCharID
	shu.shuState = st
	shu.hp = 0 // 阵亡/撤退
	ally := shuUnit("友方", [2]float64{3, 2})
	ally.hp = 100
	ops := []*operator{shu, ally}
	spec := &Spec{}
	shuTick(ops, nil, 1.0, 1.0, spec, &Verdict{})

	if len(st.SownTiles) != 0 {
		t.Fatalf("退场后地块应被清空，剩 %d 块", len(st.SownTiles))
	}
	if ally.hp != 100 {
		t.Fatalf("退场后不该再有地块回血，hp=%.2f", ally.hp)
	}
	ctx := &simCtx{objs: &ops}
	ally.sim = ctx
	if p := ally.sownProtect(); p != 0 {
		t.Fatalf("退场后不该再有庇护，p=%v", p)
	}
}

// TestShuS2SpecialInterval 技能二「特殊间隔」= 当前攻击间隔 + 1.3（PRTS 备注
// 「攻击间隔1.3+1.3」）。技能期间 profile.Interval 是 1.3，所以结果应为 2.6。
func TestShuS2SpecialInterval(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 2)

	shu := &operator{
		hp:   1000,
		cell: [2]float64{2, 2},
		spec: OperatorSpec{
			Name: "黍", CharID: shuCharID, MaxHP: 1000, ATK: 100, AttackInterval: 1.2,
			Active: &Profile{Interval: 1.3},
		},
	}
	shu.shuState = st
	shu.skillActive = true
	if got := shu.interval(); math.Abs(got-2.6) > 1e-9 {
		t.Fatalf("技能二治疗间隔 = %v，期望 2.6（1.3 + 1.3）", got)
	}

	// 关掉技能后回到普通间隔，不能被这条规则残留影响。
	shu.skillActive = false
	if got := shu.interval(); math.Abs(got-1.2) > 1e-9 {
		t.Fatalf("技能关闭后间隔 = %v，期望 1.2", got)
	}
}

// TestShuSowingRespectsSowableCells 播种限制：只播「可部署我方单位或可通行
// 地块」。SowableCells 只给两格时，四邻里另外三格必须被拒。
func TestShuSowingRespectsSowableCells(t *testing.T) {
	chdirRepoRootForData(t)
	st := shuStateForTest(t, 1)
	// 只允许 (2,2) 与 (3,2)。
	st.SowableCells = [][2]int{{2, 2}, {3, 2}}

	added := st.sowAround([2]int{2, 2}, "黍")
	if added != 2 {
		t.Fatalf("可播种格限制下应新增 2 格，实得 %d", added)
	}
	if !st.isSown([2]int{2, 2}) || !st.isSown([2]int{3, 2}) {
		t.Fatal("允许的两格应被播种")
	}
	if st.isSown([2]int{1, 2}) || st.isSown([2]int{2, 3}) {
		t.Fatal("不在可播种格列表里的格不该被播种")
	}
}

// shuYStateForTest 造一份 Y 模组三级（好时节）的运行期状态。
func shuYStateForTest(t *testing.T, slot int) *ShuBattleState {
	t.Helper()
	st := &OperatorStats{
		CharID: shuCharID, Elite: 2, Level: 60, Potential: 1,
		Module: shuYModuleID, ModuleLevel: 3,
	}
	cfg := shuCfgForTest(t, st, slot, 10)
	return newShuBattleState(cfg)
}

// TestShuSeasonBonusAtkConditions Y 模组的「三条件达成两种或以上时额外攻击力
// +5%」（Lv3）：只满足一种不触发（反例）、满足两种触发 +0.05、三种满足时
// 叠加为 0.16+0.05=0.21。
func TestShuSeasonBonusAtkConditions(t *testing.T) {
	chdirRepoRootForData(t)
	mk := func(name, prof string) *operator {
		op := shuUnit(name, [2]float64{0, 0})
		op.spec.Profession = prof
		return op
	}

	// 只满足「相同职业≥3」（3 个 TANK，不同职业只有 1 种，岁 0）。
	st := shuYStateForTest(t, 1)
	ops := []*operator{mk("a", "TANK"), mk("b", "TANK"), mk("c", "TANK")}
	st.SeasonSuiCount = 0
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if op.shuAtkPct != 0 {
			t.Fatalf("只满足一种条件不该触发额外攻击力，got %v", op.shuAtkPct)
		}
	}

	// 满足两种（3 同职业 + 3 种不同职业）：额外 +5%。
	st = shuYStateForTest(t, 1)
	ops = []*operator{
		mk("a", "TANK"), mk("b", "TANK"), mk("c", "TANK"),
		mk("d", "MEDIC"), mk("e", "SNIPER"),
	}
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if math.Abs(op.shuAtkPct-0.05) > 1e-9 {
			t.Fatalf("两种条件应给额外 0.05，got %v", op.shuAtkPct)
		}
	}

	// 三种（+ 编队四岁）：0.16 + 0.05 = 0.21。
	st = shuYStateForTest(t, 1)
	st.SeasonSuiCount = 4
	applyShuSeason(ops, st, 0)
	for _, op := range ops {
		if math.Abs(op.shuAtkPct-0.21) > 1e-9 {
			t.Fatalf("三种条件应给 0.16+0.05=0.21，got %v", op.shuAtkPct)
		}
	}
}
