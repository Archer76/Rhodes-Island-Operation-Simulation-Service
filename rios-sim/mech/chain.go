package mech

// chain 族（跳跃／链式）机制骨架 —— C 档乙第一轮。
//
// 键族身份（DB 实测，2026-09-20）：`chain` 族在库里**只有 3 个键、两种写法**
// （`attack@` 前缀与裸键并存）：
//
//	chain.max_target   3.0 / 4.0   特性 5 位 ＋ 技能 skchr_halo_1
//	chain.atk_scale    0.75        特性 4 位
//	chain.atk_scale_2  1.1/1.15/1.2/1.25   天赋「久病良医」四档（乌啾）
//
// 正文两支（判据的地基，从正文写起）：
//
//	治疗链（对友方）：恢复友方单位生命，且会在 3 个友方单位间跳跃，每次跳跃治疗量降低 25%
//	伤害链（对敌人）：攻击造成法术伤害，且会在 N 个敌人间跳跃，每次跳跃伤害降低 15% 并造成短暂停顿
//
// ★ 本轮**只落治疗链这一支**（PM 裁定：第一轮不建第二族）；伤害链登记不建。
//
// ★★ 本轮**只判 `chain.atk_scale` 一条键**，且只判到第 2 跳：
// 第 3 跳是等比（0.75² = 0.5625）还是等差（1 − 0.25×2 = 0.5），语料只给了 `0.75`
// 一个数、n=2 两读法完全同值 ⇒ **未定**。判错的代价是把某一读法**焊进实现**（不可逆，
// 同族 `b97c4132`），所以本文件**不实现第 3 跳**：算到那一跳就返回
// `ErrJumpUndetermined`。**未定是一个带出口的状态**，出口写在 `docs/chain-skeleton-plan.md`。

import (
	"encoding/json"
	"errors"
	"fmt"
)

// ChainSpec 是本机制的规格（键名与 Python 侧黑板键同名，去掉 `attack@` 前缀）。
type ChainSpec struct {
	MaxTarget int     `json:"max_target"`
	AtkScale  float64 `json:"atk_scale"`
	AtkScale2 float64 `json:"atk_scale_2"`
}

// ErrJumpUndetermined 是「第 3 跳及以后的读法未定」。
//
// ★ 它的存在**就是本轮的交付内容之一**：没有读数支撑时，唯一诚实的输出是「未定」，
// 而不是选一个读法先跑起来（`fe63d832`：没有读数就判＝赌读数）。
var ErrJumpUndetermined = errors.New(
	"chain: 第 3 跳及以后的读法未定（等比 0.75²=0.5625 vs 等差 1-0.25×2=0.5 在 n=3 分岔，" +
		"而语料只给了 0.75 一个数）；按纪律不猜，出口见 docs/chain-skeleton-plan.md §五")

// chainMech 是本机制的实例。**本轮不接任何钩子**：它不实现 Starter／*Ticker，
// 所以即使被点名也只会被 `Load` 建出来、不参与逐帧推进（骨架的最小形态）。
type chainMech struct {
	spec ChainSpec
}

func (m *chainMech) ID() ID { return "chain" }

// Spec 供判据与后续接线读取本关规格。
func (m *chainMech) Spec() ChainSpec { return m.spec }

// newChain 解规格。**解不开就报错（拒跑），不许「解不开就当没有」**（包注释里的那条）。
func newChain(cfg json.RawMessage) (Mechanism, error) {
	if len(cfg) == 0 {
		return nil, errors.New("chain: 规格为空——本机制不吃默认值，缺规格就是配置错")
	}
	var s ChainSpec
	if err := json.Unmarshal(cfg, &s); err != nil {
		return nil, fmt.Errorf("chain: 规格解不开: %w", err)
	}
	if s.MaxTarget < 1 {
		return nil, fmt.Errorf("chain: max_target 必须 ≥1，收到 %d", s.MaxTarget)
	}
	if s.AtkScale <= 0 {
		return nil, fmt.Errorf("chain: atk_scale 必须 >0，收到 %v", s.AtkScale)
	}
	if s.AtkScale2 < 0 {
		return nil, fmt.Errorf("chain: atk_scale_2 不许为负，收到 %v", s.AtkScale2)
	}
	return &chainMech{spec: s}, nil
}

func init() { RegisterFactory("chain", newChain) }

// chainJumpScale 返回第 n 跳（n 从 1 起）相对首跳的**倍率**。
//
// 本轮有断言支撑的只有前两跳：
//
//	n = 1  ⇒ 1.0           首跳满量（正文「恢复友方单位生命」）
//	n = 2  ⇒ scale         正文「每次跳跃治疗量降低 25%」＋ 黑板 chain.atk_scale = 0.75
//	n ≥ 3  ⇒ ErrJumpUndetermined（**未定，不猜**）
//
// ★ 关于 n = 2 为什么可以断言：等比与等差两个读法在 n=2 恰好重合（都是 1−0.25 = 0.75
// 或 0.75¹），**分岔从 n=3 才开始**（0.5625 vs 0.5）。这也是判据只判到第 2 跳的全部理由。
func chainJumpScale(n int, scale float64) (float64, error) {
	if n < 1 {
		return 0, fmt.Errorf("chain: 跳数从 1 起，收到 %d", n)
	}
	switch n {
	case 1:
		return 1.0, nil
	case 2:
		return scale, nil
	default:
		return 0, ErrJumpUndetermined
	}
}

// chainHealJumps 返回逐跳治疗量（首跳 ＝ base）。
//
// 只要 maxTarget > 2 就返回 `ErrJumpUndetermined`——**这是有意的「早阶段大声失败」**：
// 乌啾/明椒的特性 max_target 正是 3，所以本骨架**现在跑不了它们**。这是第 3 跳未定的
// 直接后果，不是缺陷；等读数到位，改的只有这一个函数（出口见 §五）。
func chainHealJumps(base float64, maxTarget int, scale float64) ([]float64, error) {
	if maxTarget < 1 {
		return nil, fmt.Errorf("chain: max_target 必须 ≥1，收到 %d", maxTarget)
	}
	if maxTarget > 2 {
		return nil, fmt.Errorf("chain: max_target=%d：%w", maxTarget, ErrJumpUndetermined)
	}
	out := make([]float64, 0, maxTarget)
	for n := 1; n <= maxTarget; n++ {
		k, err := chainJumpScale(n, scale)
		if err != nil {
			return nil, err
		}
		out = append(out, base*k)
	}
	return out, nil
}
