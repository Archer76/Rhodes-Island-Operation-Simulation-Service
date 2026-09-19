package mech

// chain 族第一轮的**唯一一条键判据**：`chain.atk_scale`（PM 裁定：第一轮只交一条，
// 且只判方向 ＋ 第 2 跳；第 3 跳记未定，见 docs/chain-skeleton-plan.md §四／§五）。
//
// 判据（**先写后跑**，预注册在 `docs/chain-skeleton-plan.md`，本文件只是它的可执行形态）：
//
//	断言 1  第 2 跳 = scale × 第 1 跳，且严格递减（方向）
//	断言 2  真实参数（max_target=3）下**必须拒绝**并给出 ErrJumpUndetermined（未定不猜）
//	断言 3  合成反例：坏实现必须被**同一条断言**抓住（抓 0 个即判失败）
//	断言 4  反向守卫：实现对 scale 不敏感（忽略 0.75 恒返回满量）时必须红
//	断言 5  读法判别器（**与实现解耦**）：三个候选读法做成**真读器**后——
//	        候选③ 的形态能过本判据（盲区**本体**，实测）＋ 三读法在 n=2 **同值**
//	        （第 2 跳对区分读法零信息量，这是盲区的**理由**）
//	断言 6  分岔点：三读法在 n=3 **两两不等** ⇒ §7.2 那张表是**测出来**的，不是写出来的
//
// ★ 独立性纪律（验收顶回、PM 提成通则 `msg-mu903tfp-g0`）：**「一个改动红几条」就是独立性的判据**。
// 上一版我用「字面量 75」比「实现算出的 100×0.75」——两个数由**同一对常量**决定，
// 判词「若不同值 ⇒ 判据本可区分它」是**推断**而不是**测到的东西**；而且那条被前两条算术**蕴含**
// （`d8706dc5`：判据被算术必然满足＝零信息量）。现在候选③ 是一个**真读法**，
// 判据比的是**生成器的输出**，并与实现解耦：**每个最小变异只红一条**（逐条实测见
// `tools/chain_judge_independence.py`）。
//
// 数据来源（DB 实测，2026-09-20）：`char_4224_turdus`／`char_4071_peper`／`char_4139_papyrs`
// 特性黑板 = `{"attack@chain.atk_scale": 0.75, "attack@chain.max_target": 3.0}`；
// 正文「恢复友方单位生命，且会在 3 个友方单位间跳跃，每次跳跃治疗量降低 25%」。

import (
	"errors"
	"fmt"
	"math"
	"testing"
)

// 真实数据（乌啾/明椒/papyrs 特性）
const (
	chainScale     = 0.75 //: chain.atk_scale
	chainMaxTarget = 3    //: chain.max_target（正文里那个 3）
	chainBase      = 100.0
)

// assertDecayFirstTwo 是**本判据的唯一断言入口**——判据与反例走同一条路，
// 这样「能抓住反例」证明的就是这条判据本身，而不是另写的一段代码。
func assertDecayFirstTwo(seq []float64, scale float64) error {
	if len(seq) < 2 {
		return fmt.Errorf("序列不足两跳（拿到 %d 跳：%v）", len(seq), seq)
	}
	if seq[0] <= 0 {
		return fmt.Errorf("第 1 跳应满量为正，拿到 %v", seq[0])
	}
	want := seq[0] * scale
	if d := seq[1] - want; d > 1e-9 || d < -1e-9 {
		return fmt.Errorf("第 2 跳 = %v，应为 %v × %v = %v（差 %v）", seq[1], seq[0], scale, want, d)
	}
	if !(seq[1] < seq[0]) {
		return fmt.Errorf("方向错：第 2 跳 %v 未严格小于第 1 跳 %v", seq[1], seq[0])
	}
	return nil
}

// ── 三个候选读法，各做成一个**真读器**（生成器）────────────────────────────
//
// 为什么要有它们：上一版把候选③ 写成字面量 `[]float64{100, 75, 75}`——
// 那样判据比的是「字面量 vs 实现算出的数」，两者由同一对常量决定 ⇒ 恒等式，零信息量。
// 现在候选③ 是一个**独立实现**：判据比的是**两个生成器的输出**；变异任一侧，
// 只红它自己那一条。
//
//	下标 :  0        1             2               3
//	n    :  1 跳     2 跳          3 跳            4 跳
func candSeqGeom(base float64, n int, scale float64) []float64 {
	// ① 等比衰减：第 k 跳 = base × scale^(k−1)
	seq := make([]float64, n)
	for k := 1; k <= n; k++ {
		seq[k-1] = base * math.Pow(scale, float64(k-1))
	}
	return seq
}

func candSeqArith(base float64, n int, scale float64) []float64 {
	// ② 等差衰减：第 k 跳 = base × (1 − (k−1)(1−scale))
	seq := make([]float64, n)
	for k := 1; k <= n; k++ {
		seq[k-1] = base * (1 - float64(k-1)*(1-scale))
	}
	return seq
}

func candSeqPerJump(base float64, n int, scale float64) []float64 {
	// ③ 每跳倍率：第 1 跳满量，其后**每一跳**都是 base × scale（这是「降低 25%」的另一种读法）
	seq := make([]float64, n)
	for k := 1; k <= n; k++ {
		if k == 1 {
			seq[k-1] = base
		} else {
			seq[k-1] = base * scale
		}
	}
	return seq
}

func TestChainJudge_AtkScale_FirstTwoJumps(t *testing.T) {
	// ── 观察：逐跳治疗量（计数可见——只印一个数就看不出「衰减发生在哪一跳」）
	seq, err := chainHealJumps(chainBase, 2, chainScale)
	if err != nil {
		t.Fatalf("两跳调用不该失败：%v", err)
	}
	t.Logf("逐跳治疗量（base=%v, scale=%v）：1 跳 %v → 2 跳 %v（倍率 %v）",
		chainBase, chainScale, seq[0], seq[1], seq[1]/seq[0])

	// ── 断言 1：实现过判据
	if err := assertDecayFirstTwo(seq, chainScale); err != nil {
		t.Errorf("实现未过判据：%v", err)
	}

	// ── 断言 2：真实参数必须拒绝（未定不猜）
	if _, err := chainHealJumps(chainBase, chainMaxTarget, chainScale); !errors.Is(err, ErrJumpUndetermined) {
		t.Errorf("max_target=%d 时必须返回 ErrJumpUndetermined，实际拿到 %v", chainMaxTarget, err)
	} else {
		t.Logf("max_target=%d ⇒ 拒绝并说明：%v", chainMaxTarget, err)
	}

	// ── 断言 3＋4：合成反例（坏实现必须被同一条断言抓住）
	mutants := []struct {
		name string
		seq  []float64
	}{
		{"丢掉衰减（第 2 跳仍满量）", []float64{100, 100}},    //: 断言 1＋方向
		{"方向弄反（越跳越高）", []float64{100, 125}},        //: 断言 1＋方向
		{"把「降低 25%」读成「降到 25%」", []float64{100, 25}}, //: 断言 1
		{"只算一跳就返回（序列不足）", []float64{100}},          //: 断言 1
	}
	caught := 0
	for _, m := range mutants {
		if err := assertDecayFirstTwo(m.seq, chainScale); err != nil {
			caught++
			t.Logf("✓ 抓住「%s」：%v", m.name, err)
		} else {
			t.Errorf("✗ 没抓住「%s」：%v —— 判据有洞", m.name, m.seq)
		}
	}
	if caught == 0 {
		t.Fatalf("一个反例都没抓住 ⇒ 这条判据是空架子（总数 0 即判失败）")
	}
	t.Logf("合成反例 %d/%d 被抓", caught, len(mutants))

	// ── 断言 5：读法判别器（**只用生成器，不碰实现**）
	//:
	//: 这三句话是**同一件事的三个面**（候选③ 与本判据在 n=2 无法区分），
	//: 故**合成一条断言**：否则一个变异会同时红三行，而「一个改动红几条」本身是独立性的判据
	//: （红三条 ⇒ 那是同一判据的三份副本）。三个面各自都要过，红哪面就在判词里说清。
	readings := []struct {
		name string
		gen  func(float64, int, float64) []float64
	}{
		{"① 等比衰减", candSeqGeom},
		{"② 等差衰减", candSeqArith},
		{"③ 每跳倍率", candSeqPerJump},
	}
	seqs := make([][]float64, len(readings))
	for i, r := range readings {
		seqs[i] = r.gen(chainBase, 4, chainScale)
		t.Logf("读法 %s：n=1..4 ⇒ %v", r.name, seqs[i])
	}
	{
		var bad []string
		// (a) 盲区**本体**：候选③ 的形态确实过本判据（这是实测，不是推断）
		if err := assertDecayFirstTwo(seqs[2], chainScale); err != nil {
			bad = append(bad, fmt.Sprintf("(a) 候选③ 形态应当过本判据（盲区本体），实际红了：%v", err))
		}
		// (b) n=2 三读法**同值** ⇒ 第 2 跳对区分读法零信息量（这是盲区的**理由**）
		for i := 1; i < len(seqs); i++ {
			if d := seqs[i][1] - seqs[0][1]; d > 1e-9 || d < -1e-9 {
				bad = append(bad, fmt.Sprintf("(b) n=2 三读法不再同值：%s=%v vs %s=%v ⇒ "+
					"「n=2 零信息量」不成立（那判据本该能区分它们）",
					readings[i].name, seqs[i][1], readings[0].name, seqs[0][1]))
			}
		}
		if len(bad) > 0 {
			t.Errorf("读法判别器红：\n  %s", joinLines(bad))
		} else {
			t.Logf("✓ 盲区本体＋理由（实测）：候选③ 形态 %v 过本判据，且三读法 n=2 **同值**（%v）"+
				"⇒ 第 2 跳对区分读法零信息量", seqs[2][:3], seqs[0][1])
		}
	}

	// ── 断言 6：分岔点只有 n=3（三读法两两不等）——§7.2 的表由此**被测出来**
	{
		n3 := []float64{seqs[0][2], seqs[1][2], seqs[2][2]}
		okAll := true
		for i := 0; i < len(n3); i++ {
			for j := i + 1; j < len(n3); j++ {
				if d := n3[i] - n3[j]; d < 1e-9 && d > -1e-9 {
					okAll = false
					t.Errorf("n=3 的 %s 与 %s 同值（%v）⇒ 「分岔点只有 n=3」不成立，"+
						"§7.2 的三联判决要改", readings[i].name, readings[j].name, n3[i])
				}
			}
		}
		if okAll {
			t.Logf("✓ 分岔点（实测）：n=3 ⇒ ① %v ／ ② %v ／ ③ %v（两两不等）",
				n3[0], n3[1], n3[2])
		}
	}
}

// joinLines 把多条判词拼成一段（只给测试用，避免引第三方包）。
func joinLines(ss []string) string {
	out := ""
	for i, s := range ss {
		if i > 0 {
			out += "\n  "
		}
		out += s
	}
	return out
}

// TestChainSpec_RefusesBadConfig 校验「解不开就拒跑」而不是静默当没有（包注释那条纪律）。
func TestChainSpec_RefusesBadConfig(t *testing.T) {
	cases := []struct {
		name string
		cfg  string
	}{
		{"空规格", ``},
		{"max_target=0", `{"max_target":0,"atk_scale":0.75}`},
		{"atk_scale=0", `{"max_target":3,"atk_scale":0}`},
		{"atk_scale_2 为负", `{"max_target":3,"atk_scale":0.75,"atk_scale_2":-1}`},
		{"不是 JSON", `{`},
	}
	refused := 0
	for _, c := range cases {
		if _, err := newChain([]byte(c.cfg)); err != nil {
			refused++
			t.Logf("✓ 拒跑「%s」：%v", c.name, err)
		} else {
			t.Errorf("✗ 「%s」应被拒跑，实际放行", c.name)
		}
	}
	if refused == 0 {
		t.Fatalf("一条坏规格都没拒 ⇒ 拒跑是空架子")
	}

	// 正例：真规格必须放行（否则「拒跑」只是把一切都拒了）
	m, err := newChain([]byte(`{"max_target":3,"atk_scale":0.75,"atk_scale_2":1.1}`))
	if err != nil {
		t.Fatalf("真规格应放行：%v", err)
	}
	cm, ok := m.(*chainMech)
	if !ok {
		t.Fatalf("工厂应返回 *chainMech，拿到 %T", m)
	}
	if cm.ID() != "chain" {
		t.Errorf("ID 应为 chain，拿到 %q", cm.ID())
	}
	if cm.Spec().MaxTarget != 3 || cm.Spec().AtkScale != 0.75 {
		t.Errorf("规格读回不对：%+v", cm.Spec())
	}
	t.Logf("✓ 真规格放行：ID=%q spec=%+v（拒跑 %d/%d 例）", cm.ID(), cm.Spec(), refused, len(cases))
}
