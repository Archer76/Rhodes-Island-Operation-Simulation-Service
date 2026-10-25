package main

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"testing"
)

// prob_exact_test.go：**引擎级概率事件**从期望值改成精确抽样后的判据（V-2 裁定）。
//
// 两处（改前都乘一次期望）：
//
//	① 天赋「要害瞄准·初级」一族（`talent_proc_*`）：攻击时 N% 几率把**当次攻击**
//	   的攻击力提升至 M% —— 改前 `power *= Π(1 + p(s−1))`；
//	② 天赋「附加治疗」（`attack@prob`）：治疗时 N% 几率**额外**再治一名 ——
//	   改前每次治 `p × 治疗量`。
//
// 改后都用同一套：种子只来自规格（`OperatorSpec.RNGSeed`）、同一台
// `prob_rng.go` 的取数口、`chance(0)/chance(1)` 不取数、命中时写语义事件。
//
// ⚠ 这两处当前在生产上都被 `talent.probability_event` 闸门拦着（见本文件末尾
// 那条"闸门现状"判据）：通用分类器对 `0<prob<1` 的天赋一律报占位。
// 所以本文件的判据用**手工夹具**直接驱动帧函数——那是这两条路今天唯一可达的入口。
// 解除闸门是另一个决定（要逐条审计别的干员），不在这里顺手动。

// probDamageUnit 造一名只关心"概率强化当次攻击"的靶场干员。
func probDamageUnit(p, scale float64, seed uint64) *operator {
	return &operator{
		hp: 1000,
		spec: OperatorSpec{
			Name: "概率射手", CharID: "char_test_prob", MaxHP: 1000,
			ATK: 100, DEF: 0, AttackInterval: 1, DamageType: "MAGIC",
			Range:                   [][2]int{{1, 0}},
			TalentProcProbabilities: []float64{p},
			TalentProcScales:        []float64{scale},
			// 期望倍率也照实填上：它是**证据/自校验**用的，战斗不再读它。
			TalentProcFactor: 1 + p*(scale-1),
			RNGSeed:          seed,
		},
	}
}

func probTarget(hp float64) *enemy {
	return &enemy{hp: hp, position: [2]float64{1, 0},
		spec: SpawnSpec{Name: "靶", HP: hp}}
}

// swingOnce 走一次**真实的出手帧**（`operatorsAttack`），返回这一击造成的伤害。
func swingOnce(op *operator, e *enemy, t float64) float64 {
	before := e.hp
	op.attackTimer = 0
	_ = operatorsAttack([]*operator{op}, []*enemy{e}, 1, t, &Spec{}, &Verdict{})
	return before - e.hp
}

// TestTalentProcExactSameSeedBitIdentical ① 同 seed 两遍，每一击的伤害序列逐位相同。
func TestTalentProcExactSameSeedBitIdentical(t *testing.T) {
	run := func(seed uint64) []float64 {
		op := probDamageUnit(0.4, 2.5, seed)
		e := probTarget(1e9)
		out := make([]float64, 0, 40)
		for i := 0; i < 40; i++ {
			out = append(out, swingOnce(op, e, float64(i)))
		}
		return out
	}
	a, b := run(20261025), run(20261025)
	for i := range a {
		if a[i] != b[i] {
			t.Fatalf("同 seed 的第 %d 击不同：%v vs %v", i, a[i], b[i])
		}
	}
	// 正对照：换 seed 必须**能**跑出不同序列（否则"相同"可能只是闸没在抽）。
	c := run(20261026)
	diff := false
	for i := range a {
		if a[i] != c[i] {
			diff = true
			break
		}
	}
	if !diff {
		t.Fatal("换 seed 后 40 击的伤害序列完全相同：抽样没有生效")
	}
	t.Logf("same-seed identical=true; different-seed differs=true（前 6 击 %v）", a[:6])
}

// TestTalentProcExactAmountsAndBoundaries ② 命中那一击的伤害必须**整份**乘 M，
// 未命中的就是原值；p=0/p=1 两个边界不抽签、结果确定。
func TestTalentProcExactAmountsAndBoundaries(t *testing.T) {
	const atk, scale = 100.0, 2.5

	// p = 1：每一击都加成，且是**整份**乘（不是 1+p(s−1) 的 1.6 倍）。
	opAll := probDamageUnit(1, scale, 7)
	eAll := probTarget(1e9)
	for i := 0; i < 5; i++ {
		if got := swingOnce(opAll, eAll, float64(i)); math.Abs(got-atk*scale) > 1e-9 {
			t.Fatalf("p=1 时第 %d 击应为 %v（整份乘 %v），实得 %v", i, atk*scale, scale, got)
		}
	}
	if opAll.procHits != 5 || opAll.procRolls != 5 {
		t.Fatalf("p=1：抽签/命中应各 5 次，实得 %d/%d", opAll.procRolls, opAll.procHits)
	}

	// p = 0：一击都不加成，而且**不消耗随机数**（序列起点不受影响）。
	opNone := probDamageUnit(0, scale, 7)
	eNone := probTarget(1e9)
	for i := 0; i < 5; i++ {
		if got := swingOnce(opNone, eNone, float64(i)); math.Abs(got-atk) > 1e-9 {
			t.Fatalf("p=0 时第 %d 击应为 %v，实得 %v", i, atk, got)
		}
	}
	if opNone.procHits != 0 {
		t.Fatalf("p=0 时不该命中，实得 %d", opNone.procHits)
	}

	// 中间档：每一击的伤害只能是 atk 或 atk×M 两个值之一（**没有中间值**）。
	opMid := probDamageUnit(0.4, scale, 11)
	eMid := probTarget(1e9)
	for i := 0; i < 30; i++ {
		got := swingOnce(opMid, eMid, float64(i))
		if math.Abs(got-atk) > 1e-9 && math.Abs(got-atk*scale) > 1e-9 {
			t.Fatalf("第 %d 击出现了「中间值」 %v：期望值口径又回来了", i, got)
		}
	}
	if opMid.procHits == 0 || opMid.procHits == 30 {
		t.Fatalf("30 击里命中 %d 次：闸要么恒关要么恒开", opMid.procHits)
	}
	t.Logf("p=0.4、30 击命中 %d 次（抽签 %d 次）", opMid.procHits, opMid.procRolls)
}

// TestTalentProcExactDistributionLoose ③ 大样本命中率落在 p 附近的松界里。
func TestTalentProcExactDistributionLoose(t *testing.T) {
	const n, p = 600, 0.4
	op := probDamageUnit(p, 2.0, 424242)
	e := probTarget(1e12)
	for i := 0; i < n; i++ {
		swingOnce(op, e, float64(i))
	}
	if op.procRolls != n {
		t.Fatalf("抽签次数应为 %d，实得 %d", n, op.procRolls)
	}
	rate := float64(op.procHits) / float64(n)
	// 松界：n=600、p=0.4 ⇒ σ≈0.02 ⇒ 3σ≈0.06，取 ±0.09（不写成必然绿）。
	if math.Abs(rate-p) > 0.09 {
		t.Fatalf("命中率 %.4f 偏离 p=%.2f 超过 0.09（3σ≈0.06 再留余量）", rate, p)
	}
	t.Logf("n=%d hits=%d rate=%.4f p=%.2f", n, op.procHits, rate, p)
}

// TestTalentProcMultipleTalentsIndependent ④ 多条天赋各自独立抽签、命中者相乘
// （这正是期望公式 `Π(1+p_i(s_i−1))` 的精确对应物）。
func TestTalentProcMultipleTalentsIndependent(t *testing.T) {
	op := &operator{
		hp: 1000,
		spec: OperatorSpec{
			Name: "双天赋", CharID: "char_test_prob2", MaxHP: 1000,
			ATK: 100, AttackInterval: 1, DamageType: "MAGIC",
			Range:                   [][2]int{{1, 0}},
			TalentProcProbabilities: []float64{1, 1}, // 两条都必中
			TalentProcScales:        []float64{2, 3},
			RNGSeed:                 5,
		},
	}
	e := probTarget(1e9)
	if got := swingOnce(op, e, 0); math.Abs(got-600) > 1e-9 {
		t.Fatalf("两条天赋都命中时应相乘 2×3=6 ⇒ 600，实得 %v", got)
	}
}

// TestExtraHealExactFullAmount ⑤ 附加治疗：抽中治**整份**、抽不中一名不治。
//
// 判据同时盯着"整份"和"概率"两件事：改前是每次治 `p × 治疗量`（永远有中间值），
// 改后每一笔只能是 0 或整份。
func TestExtraHealExactFullAmount(t *testing.T) {
	build := func(p float64, seed uint64) (*operator, *operator, *operator) {
		medic := hpSpeedUnit()
		medic.spec.HPAttackSpeed = nil
		medic.spec.Heals = true
		medic.spec.TalentExtraHealProb = p
		medic.spec.RNGSeed = seed
		medic.hp = 1000
		a := hpSpeedUnit()
		a.cell = [2]float64{1, 0}
		a.hp = 100
		b := hpSpeedUnit()
		b.cell = [2]float64{1, 0}
		b.hp = 100
		return medic, a, b
	}

	// p = 1：每击都多治一名，且**整份**（ATK=100，不是 50）。
	medic, a, b := build(1, 3)
	for i := 0; i < 3; i++ {
		medic.attackTimer = 0
		a.hp, b.hp = 100, 100
		_ = operatorsAttack([]*operator{medic, a, b}, nil, 1, float64(i), &Spec{}, &Verdict{})
		if a.hp != 200 || b.hp != 200 {
			t.Fatalf("p=1 时两名都该治满 100，实得 %v/%v", a.hp, b.hp)
		}
	}
	if medic.healHits != 3 || medic.healRolls != 3 {
		t.Fatalf("p=1：抽签/命中应各 3 次，实得 %d/%d", medic.healRolls, medic.healHits)
	}

	// p = 0：绝不治第二名（闸门 `TalentExtraHealProb > 0` 之外还要 chance 判）。
	medic0, a0, b0 := build(0, 3)
	medic0.attackTimer = 0
	_ = operatorsAttack([]*operator{medic0, a0, b0}, nil, 1, 0, &Spec{}, &Verdict{})
	if b0.hp != 100 {
		t.Fatalf("p=0 时第二名不该被治，实得 %v", b0.hp)
	}

	// 中间档：每一笔只能是 0 或整份 100（没有 50 这种中间值）。
	medicM, aM, bM := build(0.5, 99)
	gains := map[float64]int{}
	for i := 0; i < 80; i++ {
		medicM.attackTimer = 0
		aM.hp, bM.hp = 100, 100
		_ = operatorsAttack([]*operator{medicM, aM, bM}, nil, 1, float64(i), &Spec{}, &Verdict{})
		gains[bM.hp-100]++
	}
	for g := range gains {
		if math.Abs(g) > 1e-9 && math.Abs(g-100) > 1e-9 {
			t.Fatalf("出现了中间治疗量 %v：期望值口径又回来了（应为 0 或 100）", g)
		}
	}
	rate := float64(gains[100]) / 80
	if math.Abs(rate-0.5) > 0.2 {
		t.Fatalf("80 击里触发率 %.2f 偏离 0.5 超过 0.2", rate)
	}
	t.Logf("p=0.5、80 击：整份治疗 %d 次、零次 %d 次（rate=%.3f）", gains[100], gains[0], rate)
}

// TestProbSeedEventAnnotatedOnce ⑥ 判决上要能看见种子，且**只写一次**；
// 没有概率事件的干员不该凭空多一条标注。
func TestProbSeedEventAnnotatedOnce(t *testing.T) {
	op := probDamageUnit(1, 2, 777)
	e := probTarget(1e9)
	v := &Verdict{}
	for i := 0; i < 3; i++ {
		op.attackTimer = 0
		_ = operatorsAttack([]*operator{op}, []*enemy{e}, 1, float64(i), &Spec{}, v)
	}
	n := 0
	for _, ev := range v.Events {
		if ev.Kind == "prob_rng_seed" {
			n++
			if !containsText(ev.Who, "seed=777") {
				t.Fatalf("种子标注里没写实际 seed：%s", ev.Who)
			}
		}
	}
	if n != 1 {
		t.Fatalf("seed 标注应恰好 1 条，实得 %d 条", n)
	}

	// 没有概率事件的干员：一条都不该有。
	plain := &operator{hp: 1000, spec: OperatorSpec{Name: "无概率", ATK: 100, AttackInterval: 1, DamageType: "MAGIC", Range: [][2]int{{1, 0}}}}
	v2 := &Verdict{}
	plain.attackTimer = 0
	_ = operatorsAttack([]*operator{plain}, []*enemy{probTarget(1e9)}, 1, 0, &Spec{}, v2)
	for _, ev := range v2.Events {
		if ev.Kind == "prob_rng_seed" {
			t.Fatal("没有概率事件的干员不该有 seed 标注")
		}
	}
}

// TestOperatorSeedSurvivesSerialization ⑦ 种子住在规格里：序列化再反序列化后不变。
func TestOperatorSeedSurvivesSerialization(t *testing.T) {
	out := OperatorOut{Name: "X", ATK: 100, RNGSeed: 20261025}
	blob, err := json.Marshal(out)
	if err != nil {
		t.Fatalf("marshal: %v", err)
	}
	var back OperatorSpec
	if err := json.Unmarshal(blob, &back); err != nil {
		t.Fatalf("unmarshal: %v", err)
	}
	if back.RNGSeed != out.RNGSeed {
		t.Fatalf("seed 在序列化后变了：%d → %d", out.RNGSeed, back.RNGSeed)
	}
	// 建规格时会显式写默认值（不靠 omitempty）。
	if defaultProbRNGSeed == 0 {
		t.Fatal("默认种子不该是 0（0 会被当成「未设置」）")
	}
}

// loadCharTalentsForTest 取出该干员在 E2 满级潜能 1 下生效的天赋候选。
//
// 只给"闸门现状"那条判据用：它要问的是**通用分类器**会怎么判，所以必须走
// 与生产同一条 `resolveTalents` → `talentMechanismGaps`，不能自己造载荷。
func loadCharTalentsForTest(t *testing.T, charID string) []resolvedTalent {
	t.Helper()
	blob, err := os.ReadFile(filepath.Join(DataRoot(), "raw.githubusercontent.com",
		"excel", "character_table.json"))
	if err != nil {
		t.Fatalf("读 character_table：%v", err)
	}
	var chars map[string]json.RawMessage
	if err := json.Unmarshal(blob, &chars); err != nil {
		t.Fatalf("解析 character_table：%v", err)
	}
	raw, ok := chars[charID]
	if !ok {
		t.Fatalf("character_table 里没有 %s", charID)
	}
	var char struct {
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(raw, &char); err != nil {
		t.Fatalf("解析 %s 的天赋：%v", charID, err)
	}
	return resolveTalents(char.Talents, 2, 60, 1)
}

// TestTalentProbGateDataDrivenExemption ⑧ **全键集闭合数据驱动豁免**：
// 通用天赋分类器对全键集均有精确消费者的概率天赋（如克洛丝 prob + atk_scale）
// 不再报 talent.probability_event，且无任何未识别黑板缺口；
// 带有未闭合键的天赋（如古米 stun、承曦格雷伊 attack@sluggish）仍然必须拒判。
func TestTalentProbGateDataDrivenExemption(t *testing.T) {
	chdirRepoRootForData(t)

	// 正向：克洛丝全键集闭合，无任何缺口
	talents := loadCharTalentsForTest(t, "char_124_kroos")
	gaps := talentMechanismGaps(talents, "char_124_kroos", "克洛丝")
	for _, g := range gaps {
		if g.ID == "talent.probability_event" {
			t.Fatal("克洛丝全键集已闭合，不应再报 talent.probability_event")
		}
	}
	if len(gaps) != 0 {
		t.Fatalf("克洛丝天赋应完全闭合（0 gaps），实得 %d 条：%v", len(gaps), gaps)
	}

	// 反向：古米带 stun，仍必须报出未识别键缺口
	gummyTalents := loadCharTalentsForTest(t, "char_196_sunbr")
	gummyGaps := talentMechanismGaps(gummyTalents, "char_196_sunbr", "古米")
	stunFound := false
	for _, g := range gummyGaps {
		if g.Key == "stun" {
			stunFound = true
		}
	}
	if !stunFound {
		t.Fatalf("古米带有未识别键 stun，应当报出缺口；实得：%v", gummyGaps)
	}
}
