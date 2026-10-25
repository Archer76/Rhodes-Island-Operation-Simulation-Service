package main

import (
	"context"
	"encoding/json"
	"math"
	"rios-sim/mechanisms"
	"testing"
)

// logos_prob_test.go：第一天赋「语汇演化」的**精确概率事件**（V-2 裁定落地）。
//
// 裁定原文（博士 2026-10-25）：「只要是能精准判定的都精准判定，很难做精准的才用期望值。」
// 这里的判据分四层，缺一层都会让"随机"退化成"看起来在跑"：
//
//	① 同 seed 两次**逐位相同** —— 复现性；
//	② 换 seed 能跑出不同结果 —— 证明随机真的在起作用（不是恒真/恒假）；
//	③ 大样本命中率落在 prob 附近的**松界**内 —— 证明抽样分布没错；
//	④ 边界 0/1 与"零出手"的负对照 —— 证明计数器本身能收也能拒。

// logosProbOp 造一名**只关心第一天赋**的逻各斯（技能随便给一档，不影响抽签）。
func logosProbOp(t *testing.T, seed uint64, cfgMu func(*LogosRuntimeConfig)) *operator {
	t.Helper()
	st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	src, err := buildLogosSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec: %v", err)
	}
	src.RNGSeed = seed
	cfg := mustLogosCfg(t, src)
	if cfgMu != nil {
		cfgMu(cfg)
	}
	return &operator{
		hp:   2400,
		cell: [2]float64{0, 2},
		spec: OperatorSpec{
			Name: "逻各斯", CharID: logosCharID,
			Cell: [2]int{0, 2}, MaxHP: 2400, ATK: 1000, DEF: 120, RES: 10,
			BlockCnt: 0, AttackInterval: 1.6, DamageType: "MAGIC",
			LogosSource: src,
			Range:       [][2]int{{1, 2}, {2, 2}, {3, 2}},
		},
		logosState: newLogosBattleState(cfg, src.RNGSeed),
	}
}

// logosProbTargets 造三只血厚、站定、无攻的靶子（都在这条攻击范围内）。
func logosProbTargets(n int) []*enemy {
	out := make([]*enemy, 0, n)
	names := []string{"甲", "乙", "丙", "丁"}
	for i := 0; i < n; i++ {
		out = append(out, logosEnemyIn(names[i%len(names)],
			[2]float64{float64(1 + i%3), 2}, 1e9, nil))
	}
	return out
}

// TestLogosTalent1SameSeedBitIdentical ① 同一 seed、同一份规格 ⇒ 判决逐位相同。
//
// 判据是**字节级相等**：只比"伤害相同"会漏掉事件顺序、目标选择、停顿时长这些
// 同样会被随机性影响、但不在汇总数字里的东西。
func TestLogosTalent1SameSeedBitIdentical(t *testing.T) {
	chdirRepoRootForData(t)

	run := func(seed uint64) []byte {
		op := logosProbOp(t, seed, nil)
		op.spec.Skill = logosSkillSpec(t, 1)
		spec := &Spec{
			FPS: 30, MaxTime: 20.0, SpeedScale: 1.0,
			Life: 10, CostInit: 99, CostMax: 99, CostTime: 1.0,
			Operators: []OperatorSpec{op.spec},
			Deploys:   []DeploySpec{{Time: 0.0, CharID: logosCharID, Index: 0}},
			Spawns: []SpawnSpec{
				logosSpawn("甲", 1, 2, 1e6),
				logosSpawn("乙", 2, 2, 1e6),
				logosSpawn("丙", 3, 2, 1e6),
			},
		}
		v, err := runSimContext(context.Background(), spec)
		if err != nil {
			t.Fatalf("runSimContext(seed=%d): %v", seed, err)
		}
		// `sim_ms` 是**墙钟耗时**，与抽样无关，逐位比较时必须剔掉：
		// 留着它会让这条判据永远红（而红的理由与随机性毫无关系）。
		v.SimMS = 0
		blob, err := json.Marshal(v)
		if err != nil {
			t.Fatalf("marshal verdict: %v", err)
		}
		return blob
	}

	a := run(20261025)
	b := run(20261025)
	if string(a) != string(b) {
		// 报**第一处**不同的字节与前后文：只报长度差看不出是哪一栏漂了。
		i := 0
		for i < len(a) && i < len(b) && a[i] == b[i] {
			i++
		}
		lo := i - 80
		if lo < 0 {
			lo = 0
		}
		hiA, hiB := i+80, i+80
		if hiA > len(a) {
			hiA = len(a)
		}
		if hiB > len(b) {
			hiB = len(b)
		}
		t.Fatalf("同一 seed 两次判决不同（长度 %d vs %d，首个差异 @%d）：\nA=…%s…\nB=…%s…",
			len(a), len(b), i, a[lo:hiA], b[lo:hiB])
	}
	// 正对照：换一个 seed 必须**能**跑出不同结果——否则"相同"可能只是
	// 因为整条随机链根本没接（恒真/恒假都会让所有 seed 得出同一结论）。
	c := run(20261026)
	if string(a) == string(c) {
		t.Fatal("换 seed 后判决仍然逐位相同：抽样没有真的在起作用（恒真/恒假？）")
	}
	t.Logf("same-seed bytes=%d identical=true; different-seed differs=true", len(a))
}

// TestLogosTalent1DifferentSeedDiffers ② 换 seed 可产生不同结果（多 seed 扫一遍）。
func TestLogosTalent1DifferentSeedDiffers(t *testing.T) {
	chdirRepoRootForData(t)

	// 直接走机制层（不跑整局），把"随机是否真的影响结果"隔离出来：
	// 60 次出手、3 个目标，统计不同 seed 下命中次数的分布。
	hitsOf := func(seed uint64) int {
		op := logosProbOp(t, seed, nil)
		targets := logosProbTargets(3)
		verdict := &Verdict{}
		for i := 0; i < 60; i++ {
			logosTalent1OnAttack(op, targets, 1000, float64(i)*0.033, verdict)
		}
		return op.logosState.T1Procs
	}

	distinct := map[int]bool{}
	for _, seed := range []uint64{1, 2, 3, 4, 5, 6, 7, 8} {
		distinct[hitsOf(seed)] = true
	}
	if len(distinct) < 2 {
		t.Fatalf("8 个不同 seed 得到同一个命中次数集合 %v：随机没有生效", distinct)
	}
	t.Logf("不同 seed 的命中次数集合：%v", distinct)
}

// TestLogosTalent1DistributionLoose ③ 大样本命中率落在 prob 附近的松界里。
//
// 松界按**二项分布的三倍标准差**给（n=2000、p=0.4 ⇒ σ≈0.011 ⇒ 3σ≈0.033），
// 再留一点余量取 ±0.06。这不是"保证必绿"，也不是精确检验：它只回答
// "抽样器大致是 p 还是别的数"（把 p 写成 0.9 或用错比较方向都会出界）。
func TestLogosTalent1DistributionLoose(t *testing.T) {
	chdirRepoRootForData(t)

	const draws = 2000
	op := logosProbOp(t, 12345, nil)
	cfg := op.logosState.Config
	targets := logosProbTargets(3)
	verdict := &Verdict{}
	for i := 0; i < draws; i++ {
		logosTalent1OnAttack(op, targets, 1000, float64(i)*0.033, verdict)
	}
	if op.logosState.T1Rolls != draws {
		t.Fatalf("抽签次数应为 %d，实得 %d", draws, op.logosState.T1Rolls)
	}
	p := cfg.Talent1Prob
	if p <= 0 || p >= 1 {
		t.Fatalf("这条判据需要 0<p<1 的黑板值，实得 %v", p)
	}
	rate := float64(op.logosState.T1Procs) / float64(draws)
	if math.Abs(rate-p) > 0.06 {
		t.Fatalf("命中率 %.4f 偏离黑板 prob %.4f 超过 0.06（松界按 3σ≈0.033 再留余量）", rate, p)
	}
	t.Logf("draws=%d procs=%d rate=%.4f prob=%.4f", draws, op.logosState.T1Procs, rate, p)
}

// TestLogosTalent1BoundaryAndNoTargetControls ④ 边界与空池的负对照。
//
// 三个对照各挡一类"看起来在跑"：
//   - p=0：一次都不该中（抽签计数照涨，命中为 0）；
//   - p=1：每次都该中（不能因为 `chance` 写成 `>` 而不是 `>=` 就全不中）；
//   - 范围里没人：抽中了也不该崩、不该产生伤害笔数。
func TestLogosTalent1BoundaryAndNoTargetControls(t *testing.T) {
	chdirRepoRootForData(t)

	// p = 0
	op0 := logosProbOp(t, 7, func(c *LogosRuntimeConfig) { c.Talent1Prob = 0 })
	v0 := &Verdict{}
	for i := 0; i < 50; i++ {
		logosTalent1OnAttack(op0, logosProbTargets(3), 1000, float64(i), v0)
	}
	if op0.logosState.T1Procs != 0 {
		t.Fatalf("prob=0 时不该命中，实得 %d 次", op0.logosState.T1Procs)
	}
	if op0.logosState.T1Rolls != 50 {
		t.Fatalf("prob=0 也要记抽签次数（闸门在跑），实得 %d", op0.logosState.T1Rolls)
	}
	if got := countEvents(v0, "logos_talent1"); got != 0 {
		t.Fatalf("prob=0 时不该有额外伤害事件，实得 %d", got)
	}

	// p = 1
	op1 := logosProbOp(t, 7, func(c *LogosRuntimeConfig) { c.Talent1Prob = 1 })
	v1 := &Verdict{}
	for i := 0; i < 50; i++ {
		logosTalent1OnAttack(op1, logosProbTargets(3), 1000, float64(i), v1)
	}
	if op1.logosState.T1Procs != 50 {
		t.Fatalf("prob=1 时应当每次都命中，实得 %d 次", op1.logosState.T1Procs)
	}

	// 范围里没人
	opNone := logosProbOp(t, 7, func(c *LogosRuntimeConfig) { c.Talent1Prob = 1 })
	vNone := &Verdict{}
	outside := []*enemy{logosEnemyIn("远处", [2]float64{9, 9}, 1000, nil)}
	logosTalent1OnAttack(opNone, outside, 1000, 0, vNone)
	if got := countEvents(vNone, "logos_talent1"); got != 0 {
		t.Fatalf("范围外没有候选时不该产生事件，实得 %d", got)
	}
	if outside[0].hp != 1000 {
		t.Fatalf("范围外的敌人不该掉血，剩血 %v", outside[0].hp)
	}
}

// TestLogosTalent1ExactDamageAndSluggish 命中后的**两半结果**都要真行使：
// 额外法术伤害（数值按黑板 atk_scale × 当前攻击力、走目标法抗）与停顿秒数。
func TestLogosTalent1ExactDamageAndSluggish(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosProbOp(t, 99, func(c *LogosRuntimeConfig) { c.Talent1Prob = 1 })
	cfg := op.logosState.Config
	atk := 1000.0

	target := logosEnemyIn("靶", [2]float64{1, 2}, 1e6, nil)
	target.spec.RES = 20

	v := &Verdict{}
	logosTalent1OnAttack(op, []*enemy{target}, atk, 3.0, v)

	// 额外伤害 = atk × atk_scale，再按法抗 20 结算。
	want := atk * cfg.Talent1AtkScale * 0.8
	got := 1e6 - target.hp
	if math.Abs(got-want) > 1e-6 {
		t.Fatalf("额外法术伤害应为 %.4f（atk=%v scale=%v res=20），实得 %.4f",
			want, atk, cfg.Talent1AtkScale, got)
	}
	// 停顿：写进敌人的停顿计时器，秒数就是黑板 `sluggish`。
	if math.Abs(target.sluggishTimer-cfg.Talent1Sluggish) > 1e-9 {
		t.Fatalf("停顿应为 %v 秒，实得 %v", cfg.Talent1Sluggish, target.sluggishTimer)
	}
	// 停顿真的会减速（与全局 80% 口径共用同一状态）。
	if f := target.sluggishFactor(); math.Abs(f-(1-sluggishSlowPct)) > 1e-9 {
		t.Fatalf("停顿期间的移速系数应为 %v，实得 %v", 1-sluggishSlowPct, f)
	}
	if got := countEvents(v, "logos_talent1"); got != 1 {
		t.Fatalf("应产生 1 条天赋一事件，实得 %d", got)
	}
}

// TestLogosTalent1EmitCountDistinctTargets 模组Y 的 `emit_count=2`：
// 一次命中要打**两个不同**的目标，而不是同一个挨两下。
func TestLogosTalent1EmitCountDistinctTargets(t *testing.T) {
	chdirRepoRootForData(t)

	op := logosProbOp(t, 5, func(c *LogosRuntimeConfig) {
		c.Talent1Prob = 1
		c.Talent1EmitCount = 2
	})
	targets := logosProbTargets(3)
	before := make([]float64, len(targets))
	for i, e := range targets {
		before[i] = e.hp
	}
	v := &Verdict{}
	logosTalent1OnAttack(op, targets, 1000, 1.0, v)

	hit := 0
	for i, e := range targets {
		if e.hp < before[i] {
			hit++
		}
	}
	if hit != 2 {
		t.Fatalf("emit_count=2 应打中两个不同目标，实得 %d 个", hit)
	}
	if got := countEvents(v, "logos_talent1"); got != 2 {
		t.Fatalf("应产生 2 条天赋一事件，实得 %d", got)
	}
	// 只有两个目标时也不该重复打同一个：挑的是"两个不同目标"。
	op2 := logosProbOp(t, 5, func(c *LogosRuntimeConfig) {
		c.Talent1Prob = 1
		c.Talent1EmitCount = 3
	})
	two := logosProbTargets(2)
	hpBefore := []float64{two[0].hp, two[1].hp}
	logosTalent1OnAttack(op2, two, 1000, 1.0, &Verdict{})
	hits := 0
	for i, e := range two {
		if e.hp < hpBefore[i] {
			hits++
		}
	}
	if hits != 2 {
		t.Fatalf("候选只有 2 个时每个最多挨一下，实得 %d 个挨打", hits)
	}
}

// TestLogosGenericClassifierExemptsExactProbChain 通用天赋分类器必须认得
// "这条概率链已被精确抽样消费"，否则它会用旧的 `talent.probability_event`
// 把整场重新焊死（与 V-2 撤缺口自相矛盾）。
//
// 正负对照：
//   - 逻各斯「语汇演化」（E1 与 E2 两档）：**不报**概率缺口，且 `sluggish`
//     不再落到 `talent.blackboard.*`；
//   - 编造的"非逻各斯"同形天赋：仍然**要报**（豁免是按 charID + 键集精确开的）。
func TestLogosGenericClassifierExemptsExactProbChain(t *testing.T) {
	chdirRepoRootForData(t)

	gapsFor := func(charID string) map[string]bool {
		st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
		src, err := buildLogosSourceSpec(st, 1, 10)
		if err != nil {
			t.Fatalf("buildLogosSourceSpec: %v", err)
		}
		var char struct {
			Talents []json.RawMessage `json:"talents"`
		}
		if err := json.Unmarshal(src.Evidence["character_table"], &char); err != nil {
			t.Fatalf("unmarshal character_table: %v", err)
		}
		talents := resolveTalents(char.Talents, 2, 60, 1)
		got := map[string]bool{}
		for _, g := range talentMechanismGaps(talents, charID, "逻各斯") {
			got[g.ID] = true
		}
		return got
	}

	got := gapsFor(logosCharID)
	if got["talent.probability_event"] {
		t.Fatal("逻各斯的 prob 链已精确抽样，通用分类器不该再报 talent.probability_event")
	}
	for id := range got {
		if len(id) > len("talent.blackboard.") && id[:len("talent.blackboard.")] == "talent.blackboard.sluggish" {
			t.Fatalf("sluggish 是命中后的停顿秒数、已被消费，不该报 %s", id)
		}
	}

	// 负对照：同一个分类器、同一份载荷，但换个 charID ⇒ 仍然报概率缺口。
	other := gapsFor("char_9999_not_logos")
	if !other["talent.probability_event"] {
		t.Fatalf("对照组（非逻各斯）应当仍报概率缺口；实得 %v", other)
	}
}

// TestLogosExactProbTalentValidatorBoundaries 校验器本身能收也能拒。
func TestLogosExactProbTalentValidatorBoundaries(t *testing.T) {
	base := map[string]any{"prob": 0.4, "atk_scale": 0.6, "sluggish": 0.8}
	if !logosExactProbTalent(logosCharID, base) {
		t.Fatal("审计过的基集应当被认下")
	}
	// 模组的两个附加键也认。
	withModule := map[string]any{"prob": 0.4, "atk_scale": 0.65, "sluggish": 0.8, "emit_count": 2.0}
	if !logosExactProbTalent(logosCharID, withModule) {
		t.Fatal("带 emit_count 的模组改写应当被认下")
	}
	// 反例四个：别的干员 / 多出来的键 / prob 越界 / 缺 sluggish。
	if logosExactProbTalent("char_9999_not_logos", base) {
		t.Fatal("别的 charID 不该被豁免")
	}
	extra := map[string]any{"prob": 0.4, "atk_scale": 0.6, "sluggish": 0.8, "unknown_key": 1.0}
	if logosExactProbTalent(logosCharID, extra) {
		t.Fatal("出现未知键时应退回通用判定")
	}
	if logosExactProbTalent(logosCharID, map[string]any{"prob": 1.0, "atk_scale": 0.6, "sluggish": 0.8}) {
		t.Fatal("prob=1 不是概率事件，不该走这条豁免")
	}
	if logosExactProbTalent(logosCharID, map[string]any{"prob": 0.4, "atk_scale": 0.6}) {
		t.Fatal("缺 sluggish 说明不是我们审计过的那条链")
	}
}

// TestLogosSeedSurvivesSerialization 种子必须**只在规格里**：规格序列化再反序列化
// 之后仍然是同一个 seed，且用它采样得到同一串命中序列。
func TestLogosSeedSurvivesSerialization(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	src, err := buildLogosSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec: %v", err)
	}
	if src.RNGSeed != defaultProbRNGSeed {
		t.Fatalf("建规格时应显式写入默认 seed %d，实得 %d", defaultProbRNGSeed, src.RNGSeed)
	}
	blob, err := json.Marshal(src)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var back LogosSourceSpec
	if err := json.Unmarshal(blob, &back); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if back.RNGSeed != src.RNGSeed {
		t.Fatalf("seed 在序列化后变了：%d → %d", src.RNGSeed, back.RNGSeed)
	}

	// 同一 seed 的两份配置 ⇒ 同一串判定。
	seq := func(seed uint64) []bool {
		cfg := mustLogosCfg(t, &LogosSourceSpec{
			Slot: src.Slot, SkillLevel: src.SkillLevel, Elite: src.Elite,
			Level: src.Level, Potential: src.Potential,
			OperatorSkill: src.OperatorSkill, Talents: src.Talents,
			Evidence: src.Evidence,
		})
		r := newProbRNG(seed)
		out := make([]bool, 0, 64)
		for i := 0; i < 64; i++ {
			out = append(out, r.chance(cfg.Talent1Prob))
		}
		return out
	}
	a, b := seq(back.RNGSeed), seq(src.RNGSeed)
	for i := range a {
		if a[i] != b[i] {
			t.Fatalf("同一 seed 的第 %d 次判定不同", i)
		}
	}
	c := seq(back.RNGSeed + 1)
	same := true
	for i := range a {
		if a[i] != c[i] {
			same = false
			break
		}
	}
	if same {
		t.Fatal("相邻 seed 的 64 次序列完全相同：抽样器没有分开")
	}
}

// TestLogosSpecHasNoProbabilityGapAtFullTraining 满练、不装模组时：
// 规格级闸门对逻各斯**不应**产出任何占位（这是"能跑"的根条件）。
func TestLogosSpecHasNoProbabilityGapAtFullTraining(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{CharID: logosCharID, Elite: 2, Level: 60, Potential: 1}
	src, err := buildLogosSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLogosSourceSpec: %v", err)
	}
	gaps := logosRemainingGapsFromSpec(src, "逻各斯", 0)
	// 技能三自带 `projectile_move_scale`（敌方弹道缺口），所以这里不要求空表；
	// 要求的是「没有概率相关的那条」。
	for _, g := range gaps {
		if g.Key == "prob" || containsText(g.ID, "prob") {
			t.Fatalf("不该再有概率缺口：%s（%s）", g.ID, g.Reason)
		}
	}
	// 而通用分类器那条也不能从别的入口冒出来。
	var char struct {
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(src.Evidence["character_table"], &char); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	for _, g := range talentMechanismGaps(resolveTalents(char.Talents, 2, 60, 1), logosCharID, "逻各斯") {
		if g.Status != "" && g.ID == "talent.probability_event" {
			t.Fatalf("通用分类器仍在报概率缺口：%s", g.Reason)
		}
	}
	var _ = mechanisms.Gap{}
}
