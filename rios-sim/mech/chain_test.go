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
//	已知盲区  「每次乘基准」（第 3 跳 = 0.75）本判据**抓不到**——第 3 跳未定，故判据不覆盖它；
//	          本文件把它**显式登记为绿**，这样将来收紧判据时这条会主动提醒改文档。
//
// 数据来源（DB 实测，2026-09-20）：`char_4224_turdus`／`char_4071_peper`／`char_4139_papyrs`
// 特性黑板 = `{"attack@chain.atk_scale": 0.75, "attack@chain.max_target": 3.0}`；
// 正文「恢复友方单位生命，且会在 3 个友方单位间跳跃，每次跳跃治疗量降低 25%」。

import (
	"errors"
	"fmt"
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
		{"丢掉衰减（第 2 跳仍满量）", []float64{100, 100}},             //: 断言 1＋方向
		{"方向弄反（越跳越高）", []float64{100, 125}},                  //: 断言 1＋方向
		{"把「降低 25%」读成「降到 25%」", []float64{100, 25}},           //: 断言 1
		{"只算一跳就返回（序列不足）", []float64{100}},                   //: 断言 1
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

	// ── 已知盲区：显式登记为绿（不是漏网，是「判据按裁定的范围不覆盖它」）
	//: 这个「坏实现」就是**候选 ③（每跳倍率）**：第 3 跳 75，而非等比 56.25／等差 50。
	blind := []float64{100, 75, 75}
	if err := assertDecayFirstTwo(blind, chainScale); err != nil {
		t.Errorf("已知盲区用例应当通过（判据只看前两跳），实际红了：%v\n"+
			"若判据已被收紧，请同步更新 docs/chain-skeleton-plan.md 的 §四／§七", err)
	} else {
		t.Logf("⚠ 已知盲区（**有意**）：%v 通过本判据——它是**候选 ③（每跳倍率）**；"+
			"其它实现若落到这一形态，只有第 3 跳读数到位后才能判", blind)
	}
	//: ★ 盲区**是有理由的**，把理由也做成断言：候选 ③ 与本实现在 n=2 **同值** ⇒
	//: 第 2 跳对「区分读法」零信息量。这一条如果红了，说明「盲区」的说法不成立（那才是真漏网）。
	if blind[1] != seq[1] {
		t.Errorf("候选 ③ 的第 2 跳 %v 与本实现的 %v 不同 ⇒ 判据本该能区分它，"+
			"「已知盲区」的说法不成立（这是真漏网，不是边界）", blind[1], seq[1])
	} else {
		t.Logf("✓ 盲区有理由：候选 ③ 与本实现在 n=2 **同值**（%v）⇒ 第 2 跳对区分读法零信息量；"+
			"分岔点只有 n=3 一处（0.5625 ／ 0.5 ／ 0.75）", seq[1])
	}
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
