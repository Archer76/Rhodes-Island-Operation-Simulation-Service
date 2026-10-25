package main

// prob_rng.go：逻各斯概率事件的**确定性伪随机**（V-2 裁定落地）。
//
// ## 为什么不用 `math/rand`
//
// 判决要与计划一一对应、要能反查、要能进对拍台。`math/rand` 的全局源在
// Go 1.20 之后被运行时随机播种，`rand.Seed` 也已被移除；`rand.New(rand.NewSource(seed))`
// 虽然在当前版本可用，但那是**包内实现细节**——升级 Go 时它变了，历史读数就
// 无法复现，而症状是"同一份规格两次跑出两个判决"，最难查的一种。
//
// 所以这里自带一个**写死的** splitmix64：算法只有三行、与语言版本无关、
// 输出序列可以逐位重放。规格里的 `rng_seed` 是**唯一**的随机性来源——
// 运行期不许有任何"隐式播种"（时间、地址、全局计数都不许）。
//
// ## 判决语义（博士 2026-10-25 裁定的第 2 条）
//
// 这样算出来的是「**该 seed 下的一次采样**」，**不是**胜率、也不是期望值。
// 同一 (计划, seed) ⇒ 同一时间线；换 seed 只是换一条同样合法的时间线。
// 事件流里 `logos_rng_seed` 会把用到的 seed 写在判决上，便于事后反查。

// defaultProbRNGSeed 是规格没给 seed 时的**固定**默认值。
//
// 它不是"随机挑一个"，而是一个写死的常量：因此"没给 seed"与"给了 1"
// 是同一份采样，仍然可复现。搜索侧共用同一个 seed 才有可比性（裁定第 1 条）。
const defaultProbRNGSeed uint64 = 1

// probRNG 是 splitmix64 的定长状态机。
//
// 只暴露两个取数口：`float()`（[0,1) 均匀）与 `chance(p)`（伯努利判定）。
// 抽目标用 `pick(n)`——它是 `float()` 的一次映射，**不额外消耗**随机性，
// 于是"抽几个目标"不会因为实现方式不同而改变后续序列。
type probRNG struct {
	state uint64
	// draws 是已取数次数（只作留痕/测试用，不参与判定）。
	draws int
}

func newProbRNG(seed uint64) *probRNG {
	if seed == 0 {
		seed = defaultProbRNGSeed
	}
	return &probRNG{state: seed}
}

// next 是 splitmix64 的一步（Steele/Lea/Flood 的公开算法，常量固定）。
func (r *probRNG) next() uint64 {
	r.state += 0x9E3779B97F4A7C15
	z := r.state
	z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9
	z = (z ^ (z >> 27)) * 0x94D049BB133111EB
	return z ^ (z >> 31)
}

// float 返回 [0,1) 的均匀读数。
//
// 取高 53 位：float64 的有效位数就是 53，这样每个可表示的 [0,1) 值都等概率，
// 不引入额外的偏置（用低 53 位也一样，但高位是 splitmix64 混合最充分的部分）。
func (r *probRNG) float() float64 {
	r.draws++
	return float64(r.next()>>11) / float64(uint64(1)<<53)
}

// chance 报告一次概率判定是否命中（p<=0 恒不中，p>=1 恒中）。
//
// ⚠ 两个边界**不取数**：把 0/1 也走一遍 `float()` 会让"这条天赋没有概率"
// 与"有概率但恰好命中"在序列上分叉，历史读数就对不上了。
func (r *probRNG) chance(p float64) bool {
	if p <= 0 {
		return false
	}
	if p >= 1 {
		return true
	}
	return r.float() < p
}

// pick 返回 [0,n) 的均匀下标（n<=0 返回 0）。
func (r *probRNG) pick(n int) int {
	if n <= 1 {
		return 0
	}
	return int(r.float() * float64(n))
}
