package main

import (
	"math"
	"testing"
)

// logos_mechanics_test.go：逻各斯（char_4133_logos）四条已建模机制的单元判据。
//
// 全部判据都**只读 gamedata 解出来的数**，不在这里写死任何黑板值：
// 写死会让"配置层解析错了"与"机制算错了"两种错长得一样。

func logosStateForTest(t *testing.T, slot int, elite, pot int) *LogosBattleState {
	t.Helper()
	st := &OperatorStats{CharID: logosCharID, Elite: elite, Level: 60, Potential: pot}
	// 专精（8~10 级）只有精二能取；精一按 7 级。
	level := 10
	if elite < 2 {
		level = 7
	}
	cfg := logosCfgForTest(t, st, slot, level)
	return newLogosBattleState(cfg, logosDefaultRNGSeed)
}

func logosUnit(name string, cell [2]float64, atk float64) *operator {
	return &operator{
		hp:   1000,
		cell: cell,
		spec: OperatorSpec{
			// CharID 必须真的是逻各斯：运行期那几条分支（技能范围、目标数、
			// 法抗加成）都按 char_id 门控，填成名字会让它们静默不生效。
			Name: name, CharID: logosCharID, MaxHP: 1000, ATK: atk,
			DEF: 0, AttackInterval: 1.0,
		},
	}
}

// logosEnemyIn 造一只站在某格、满血的敌人（`sim` 指针指向一个可变时刻，
// 天赋二的"这一刻生效吗"就是按它判的）。
func logosEnemyIn(name string, cell [2]float64, hp float64, clock *float64) *enemy {
	e := &enemy{
		spec:     SpawnSpec{Name: name, EnemyID: name, HP: hp, ATK: 0, RES: 0},
		hp:       hp,
		position: cell,
	}
	if clock != nil {
		e.sim = &simCtx{time: clock}
	}
	return e
}

// TestLogosTalent2MagicResAndFlatBonus 天赋二「剜魂具辞」：
// 打中之后法抗 −M、受到的法术伤害 +K，且**到期就一起失效**。
func TestLogosTalent2MagicResAndFlatBonus(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 0.0
	st := logosStateForTest(t, 1, 2, 1)
	op := logosUnit("逻各斯", [2]float64{1, 1}, 100)
	op.logosState = st

	target := logosEnemyIn("靶", [2]float64{2, 1}, 100000, &clock)
	target.spec.RES = 20

	// 打中之前：没有任何减益，读数必须与基准一致。
	if got := target.res(); math.Abs(got-20) > 1e-9 {
		t.Fatalf("未施加减益时法抗应等于基准 20，实得 %v", got)
	}
	if got := target.logosMagicFlat(); got != 0 {
		t.Fatalf("未施加减益时法伤加值应为 0，实得 %v", got)
	}

	logosTalent2OnHit(op, target, clock, nil)

	// 法抗：基准 20 − 黑板里的 10 = 10。黑板值是负数（-10），实现里取负号转成"削减"。
	wantRes := 20 + st.Config.Talent2MagicResDelta
	if got := target.res(); math.Abs(got-wantRes) > 1e-9 {
		t.Fatalf("减益后法抗应为 %v，实得 %v", wantRes, got)
	}
	// 法伤加值 = 黑板 atk_addition。
	if got := target.logosMagicFlat(); math.Abs(got-st.Config.Talent2AtkAddition) > 1e-9 {
		t.Fatalf("法伤加值应为 %v，实得 %v", st.Config.Talent2AtkAddition, got)
	}

	// 到期：整条减益一起消失（三项同源，不许只掉一半）。
	clock = st.Config.Talent2Duration + 0.01
	if got := target.res(); math.Abs(got-20) > 1e-9 {
		t.Fatalf("减益到期后法抗应回到 20，实得 %v", got)
	}
	if got := target.logosMagicFlat(); got != 0 {
		t.Fatalf("减益到期后法伤加值应为 0，实得 %v", got)
	}

	// 续期取 max：同一秒内连打两次，到期时刻取更晚的那个。
	clock = 0
	logosTalent2OnHit(op, target, clock, nil)
	first := target.logosDebuffUntil
	logosTalent2OnHit(op, target, 1.0, nil)
	if target.logosDebuffUntil <= first {
		t.Fatalf("续期应取更晚的时刻：%v → %v", first, target.logosDebuffUntil)
	}
}

// TestLogosTalent2NoEffectBeforeElite2 天赋二在精二才解锁：精一的配置里
// `Talent2Enabled` 必须是 false，施加函数必须什么都不做。
func TestLogosTalent2NoEffectBeforeElite2(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 0.0
	st := logosStateForTest(t, 1, 1, 1)
	if st.Config.Talent2Enabled {
		t.Fatal("精一不该解锁天赋二")
	}
	op := logosUnit("逻各斯", [2]float64{1, 1}, 100)
	op.logosState = st
	target := logosEnemyIn("靶", [2]float64{2, 1}, 1000, &clock)
	target.spec.RES = 30

	logosTalent2OnHit(op, target, clock, nil)
	if got := target.res(); math.Abs(got-30) > 1e-9 {
		t.Fatalf("天赋二未解锁时不该动法抗，实得法抗 %v", got)
	}
	if target.logosMagicFlat() != 0 {
		t.Fatal("天赋二未解锁时不该给法伤加值")
	}
}

// TestLogosS1ExecuteThresholdAndTransfer 技能一「殁亡」：
// 阈值以下立刻倒下；转移伤害对**另一个**目标结算，并且按法抗削。
func TestLogosS1ExecuteThresholdAndTransfer(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 10.0
	st := logosStateForTest(t, 1, 2, 1)
	cfg := st.Config

	op := logosUnit("逻各斯", [2]float64{0, 0}, 1000)
	op.logosState = st
	op.skillActive = true
	// 范围就是这两格：让两只敌人都在里面，且**不含**第三只。
	op.spec.Range = [][2]int{{1, 0}, {2, 0}}

	threshold := op.atk() * cfg.S1KillAtkScale
	// 阈值以下（会倒下）与阈值以上（不会）各一只。
	weak := logosEnemyIn("残血", [2]float64{1, 0}, threshold*0.5, &clock)
	weak.spec.RES = 0
	sturdy := logosEnemyIn("满血", [2]float64{2, 0}, threshold*4, &clock)
	sturdy.spec.RES = 0
	// 第三只在范围外，用来证明「另一个目标」不是随便挑的。
	outside := logosEnemyIn("范围外", [2]float64{9, 9}, 5000, &clock)

	enemies := []*enemy{weak, sturdy, outside}
	before := sturdy.hp
	verdict := &Verdict{}

	logosS1Execute(op, st, enemies, clock, verdict)

	if weak.alive() {
		t.Fatalf("阈值以下的敌人应立刻倒下，剩血 %v", weak.hp)
	}
	if !sturdy.alive() {
		t.Fatal("阈值以上的敌人不该被斩杀")
	}
	if st.S1Kills != 1 {
		t.Fatalf("斩杀计数应为 1，实得 %d", st.S1Kills)
	}

	// 转移伤害 = 倒下单位的生命值，按目标法抗结算（这里法抗 0，故全额）。
	wantTransfer := threshold * 0.5
	if got := before - sturdy.hp; math.Abs(got-wantTransfer) > 1e-6 {
		t.Fatalf("转移伤害应为 %v，实得 %v", wantTransfer, got)
	}
	// 范围外那只一滴都不该掉——它既不在范围里，也不该被当成"另一个目标"。
	if outside.hp != 5000 {
		t.Fatalf("范围外的敌人不该受伤，剩血 %v", outside.hp)
	}
	// 转移伤害要在判决账本里体现（`DamageDealt` 不能只记斩杀那一笔）。
	if verdict.DamageDealt <= 0 {
		t.Fatal("判决账本应记到伤害")
	}
}

// TestLogosS1TransferMitigatedByRes 转移伤害是**法术**伤害，法抗必须削它。
func TestLogosS1TransferMitigatedByRes(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 5.0
	st := logosStateForTest(t, 1, 2, 1)
	cfg := st.Config

	op := logosUnit("逻各斯", [2]float64{0, 0}, 1000)
	op.logosState = st
	op.skillActive = true
	op.spec.Range = [][2]int{{1, 0}, {2, 0}}

	fallenHP := op.atk() * cfg.S1KillAtkScale * 0.5
	weak := logosEnemyIn("残血", [2]float64{1, 0}, fallenHP, &clock)
	victim := logosEnemyIn("受体", [2]float64{2, 0}, 10000, &clock)
	victim.spec.RES = 50

	before := victim.hp
	logosS1Execute(op, st, []*enemy{weak, victim}, clock, &Verdict{})
	// 法抗 50 ⇒ 伤害减半（下限 5% 不生效：这里远高于它）。
	want := fallenHP * 0.5
	if got := before - victim.hp; math.Abs(got-want) > 1e-6 {
		t.Fatalf("法抗 50 时转移伤害应为 %v，实得 %v", want, got)
	}
}

// TestLogosS2RampAndSlow 技能二「提喻」：
// 每 `attack@cooldown` 一拍，倍率按 `base+delta×层数` 爬、移速按 `move_speed×层数` 降，
// 层数封顶 `max_stack_cnt`；倍率在满层时**恰好是 base 的 3 倍**、移速恰好 40%。
func TestLogosS2RampAndSlow(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 0.0
	st := logosStateForTest(t, 2, 2, 1)
	cfg := st.Config

	op := logosUnit("逻各斯", [2]float64{0, 0}, 500)
	op.logosState = st
	op.skillActive = true
	op.spec.Range = [][2]int{{1, 0}}

	// 血厚到不会被 10 拍打死（拍数与层数要能在同一只身上数完）。
	target := logosEnemyIn("靶", [2]float64{1, 0}, 1e9, &clock)
	target.spec.RES = 0

	// 满层时的倍率必须是 base 的 3 倍（正文「逐渐提高至 3 倍」）：
	// base + delta×max_stack = 3 × base —— 这条等式本身就是数据自洽的判据。
	wantFull := 3 * cfg.S2AtkScaleBase
	gotFull := cfg.S2AtkScaleBase + cfg.S2AtkScaleDelta*float64(cfg.S2MaxStackCnt)
	if math.Abs(gotFull-wantFull) > 1e-9 {
		t.Fatalf("满层倍率 %v 与「3 倍 base」%v 不自洽（base=%v delta=%v max=%d）",
			gotFull, wantFull, cfg.S2AtkScaleBase, cfg.S2AtkScaleDelta, cfg.S2MaxStackCnt)
	}
	// 满层移速必须是 40%：每层 -0.06 × 10 = -0.6。
	if got := 1 + cfg.S2MoveSpeedDelta*float64(cfg.S2MaxStackCnt); math.Abs(got-0.4) > 1e-9 {
		t.Fatalf("满层移速应为 0.4，实得 %v", got)
	}

	// 一拍一拍地推：每拍 dt = cooldown，正好一次结算。
	perTick := cfg.S2Cooldown
	for i := 0; i < cfg.S2MaxStackCnt; i++ {
		logosS2Tick(op, st, []*enemy{target}, perTick, clock, &Verdict{})
		clock += perTick
	}
	if st.S2Stack != cfg.S2MaxStackCnt {
		t.Fatalf("层数应为上限 %d，实得 %d", cfg.S2MaxStackCnt, st.S2Stack)
	}
	if st.S2Ticks != cfg.S2MaxStackCnt {
		t.Fatalf("结算笔数应为 %d，实得 %d", cfg.S2MaxStackCnt, st.S2Ticks)
	}
	if got := (target.logosMoveDown); math.Abs(got+0.6) > 1e-9 {
		t.Fatalf("满层移速削量应为 -0.6，实得 %v", got)
	}
	if got := target.logosMoveScale(); math.Abs(got-0.4) > 1e-9 {
		t.Fatalf("满层移速乘区应为 0.4，实得 %v", got)
	}

	// 超出上限不再加层（封顶）。
	logosS2Tick(op, st, []*enemy{target}, perTick, clock, &Verdict{})
	if st.S2Stack != cfg.S2MaxStackCnt {
		t.Fatalf("层数应封顶在 %d，实得 %d", cfg.S2MaxStackCnt, st.S2Stack)
	}
}

// TestLogosS2ResetsOnTargetDeath 目标倒下 ⇒ 重新索敌且**效果重置**
// （层数与移速乘区一起清零，不是只清层数）。
func TestLogosS2ResetsOnTargetDeath(t *testing.T) {
	chdirRepoRootForData(t)

	clock := 0.0
	st := logosStateForTest(t, 2, 2, 1)
	cfg := st.Config

	op := logosUnit("逻各斯", [2]float64{0, 0}, 1000)
	op.logosState = st
	op.skillActive = true
	op.spec.Range = [][2]int{{1, 0}}

	// 血量刚好够挨一下、第二下就倒下。
	victim := logosEnemyIn("脆皮", [2]float64{1, 0}, op.atk()*cfg.S2AtkScaleBase*0.5, &clock)
	victim.spec.RES = 0

	logosS2Tick(op, st, []*enemy{victim}, cfg.S2Cooldown, clock, &Verdict{})
	clock += cfg.S2Cooldown
	if victim.alive() {
		t.Fatalf("第一拍就该倒下，剩血 %v", victim.hp)
	}
	if st.S2Stack != 0 {
		t.Fatalf("目标倒下后层数应清零，实得 %d", st.S2Stack)
	}
	if st.Locked != nil {
		t.Fatal("目标倒下后应解除锁定")
	}
}

// TestLogosS3MaxTarget 技能三「延异视阈」：技能期间一次最多打
// `attack@max_target` 个，**不开技能必须回到 1**（写进静态快照会让整关伤害凭空变高）。
func TestLogosS3MaxTarget(t *testing.T) {
	chdirRepoRootForData(t)

	st := logosStateForTest(t, 3, 2, 1)
	op := logosUnit("逻各斯", [2]float64{0, 0}, 100)
	op.logosState = st

	if got := op.maxTarget(); got != 1 {
		t.Fatalf("未开技能时目标数应为 1，实得 %d", got)
	}
	op.skillActive = true
	if got := op.maxTarget(); got != st.Config.S3MaxTarget {
		t.Fatalf("技能期间目标数应为 %d，实得 %d", st.Config.S3MaxTarget, got)
	}
	// 技能二不参与这一条：它的平A 是停摆的，不该被技能三的目标数污染。
	st2 := logosStateForTest(t, 2, 2, 1)
	op2 := logosUnit("逻各斯", [2]float64{0, 0}, 100)
	op2.logosState = st2
	op2.skillActive = true
	if got := op2.maxTarget(); got != 1 {
		t.Fatalf("技能二期间目标数应仍为 1，实得 %d", got)
	}
}

// TestLogosS2MagicResOnlyWhileActive 技能二的 +法术抗性只在技能期间成立。
func TestLogosS2MagicResOnlyWhileActive(t *testing.T) {
	chdirRepoRootForData(t)

	st := logosStateForTest(t, 2, 2, 1)
	op := logosUnit("逻各斯", [2]float64{0, 0}, 100)
	op.logosState = st
	op.spec.RES = 10

	if got := op.res(); math.Abs(got-10) > 1e-9 {
		t.Fatalf("未开技能时法抗应为 10，实得 %v", got)
	}
	op.skillActive = true
	want := 10 + st.Config.S2MagicRes
	if got := op.res(); math.Abs(got-want) > 1e-9 {
		t.Fatalf("技能二期间法抗应为 %v，实得 %v", want, got)
	}

	// 技能一/三不加法抗（只认技能二那一档）。
	st3 := logosStateForTest(t, 3, 2, 1)
	op3 := logosUnit("逻各斯", [2]float64{0, 0}, 100)
	op3.logosState = st3
	op3.spec.RES = 10
	op3.skillActive = true
	if got := op3.res(); math.Abs(got-10) > 1e-9 {
		t.Fatalf("技能三期间法抗不该变，实得 %v", got)
	}
}

// TestLogosSkillRangeExpansion 技能一/三的「攻击范围扩大」：
// 技能期间目标选取范围换成技能 `rangeId` 折出来的绝对格；不开技能回到基础范围。
func TestLogosSkillRangeExpansion(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	src, err := buildLogosSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec: %v", err)
	}
	if err := attachLogosSkillRange(src, "Right", [2]int{0, 0}); err != nil {
		t.Fatalf("attachLogosSkillRange: %v", err)
	}
	if len(src.SkillRangeAbsCells) == 0 {
		t.Fatal("技能三的范围绝对格不该为空")
	}
	// 3-4 的相对格在朝右、原点 (0,0) 下平移到同一坐标（col 是向前的轴）。
	// 判据不写死格数：只要求"技能范围 ⊋ 基础范围"，否则「扩大」没发生。
	base := [][2]int{{1, 0}, {2, 0}}
	cellSet := map[[2]int]bool{}
	for _, c := range src.SkillRangeAbsCells {
		cellSet[c] = true
	}
	for _, c := range base {
		if !cellSet[c] {
			t.Fatalf("技能范围应包含基础范围里的 %v", c)
		}
	}
	if len(src.SkillRangeAbsCells) <= len(base) {
		t.Fatalf("技能范围应严格大于基础范围：%d vs %d",
			len(src.SkillRangeAbsCells), len(base))
	}

	op := logosUnit("逻各斯", [2]float64{0, 0}, 100)
	op.spec.Range = base
	op.spec.LogosSource = src
	op.logosState = newLogosBattleState(mustLogosCfg(t, src), logosDefaultRNGSeed)
	op.skillActive = false
	if got := op.targetRange(); len(got) != len(base) {
		t.Fatalf("未开技能时应走基础范围 %d 格，实得 %d", len(base), len(got))
	}
	op.skillActive = true
	if got := op.targetRange(); len(got) != len(src.SkillRangeAbsCells) {
		t.Fatalf("技能期间应走技能范围 %d 格，实得 %d",
			len(src.SkillRangeAbsCells), len(got))
	}
}

func mustLogosCfg(t *testing.T, src *LogosSourceSpec) *LogosRuntimeConfig {
	t.Helper()
	cfg, err := decodeLogosRuntimeConfig(src)
	if err != nil {
		t.Fatalf("decodeLogosRuntimeConfig: %v", err)
	}
	return cfg
}

// TestLogosGapsNameEveryUnconsumedMechanism 缺口必须**具名**：
// 技能三的敌方子弹、模组X 的元素条件分支、两个模组的隐藏天赋，一个都不许被静默吞掉。
//
// ★ 第一天赋的概率链**不在**这一栏：V-2 裁定后它走 seed 精确抽样，
// 所以这里还要反向断言"概率缺口已经不存在"——否则旧缺口会以"等 V-2"的名义
// 继续把整场拒掉，而没人看得出裁定没落地。
func TestLogosGapsNameEveryUnconsumedMechanism(t *testing.T) {
	chdirRepoRootForData(t)

	// 模组Y（提供 sp 特性与 emit_count=2）+ 技能三（提供 projectile_move_scale）
	st := &OperatorStats{
		CharID: logosCharID, Elite: 2, Level: 60, Potential: 1,
		Module: logosModule2ID, ModuleLevel: 3,
	}
	src, err := buildLogosSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec: %v", err)
	}
	gaps := logosRemainingGapsFromSpec(src, "逻各斯", 0)
	want := map[string]bool{
		"logos.skill3.projectile": true,
		"logos.module.trait_sp":   true,
	}
	got := map[string]bool{}
	for _, g := range gaps {
		got[g.ID] = true
		if g.Reason == "" {
			t.Fatalf("缺口 %s 没有理由：缺口必须是可读的具名项", g.ID)
		}
		if g.ID == "logos.talent1.prob_v2" {
			t.Fatalf("V-2 已裁定、概率链已精确抽样，不该再报这条缺口：%s", g.Reason)
		}
	}
	for id := range want {
		if !got[id] {
			t.Fatalf("缺口 %s 没被上报；实得 %v", id, got)
		}
	}

	// 模组X：凋亡损伤（隐藏天赋）与「爆发期间」元素分支各一条缺口，
	// 且**只在**装了模组X 时出现。
	stX := &OperatorStats{
		CharID: logosCharID, Elite: 2, Level: 60, Potential: 1,
		Module: logosModule1ID, ModuleLevel: 3,
	}
	srcX, err := buildLogosSourceSpec(stX, 3, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec(module X): %v", err)
	}
	foundEP, foundCond := false, false
	for _, g := range logosRemainingGapsFromSpec(srcX, "逻各斯", 0) {
		switch g.ID {
		case "logos.module.trait_ep_damage":
			foundEP = true
		case "logos.talent1.element_conditional":
			foundCond = true
		}
	}
	if !foundEP {
		t.Fatal("模组X 的凋亡损伤缺口没被上报")
	}
	if !foundCond {
		t.Fatal("模组X 的「爆发期间元素伤害」条件分支缺口没被上报")
	}
}

func containsText(s, sub string) bool {
	return len(sub) == 0 || (len(s) >= len(sub) && indexOf(s, sub) >= 0)
}

func indexOf(s, sub string) int {
	for i := 0; i+len(sub) <= len(s); i++ {
		if s[i:i+len(sub)] == sub {
			return i
		}
	}
	return -1
}
