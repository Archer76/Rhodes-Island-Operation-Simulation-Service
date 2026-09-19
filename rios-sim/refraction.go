package main

// 折射（术语 `ba.refraction`）——**敌人侧独有**的状态层。
//
// ── 取证（2026-09-20，取自 `data/enemydb.sqlite` 的游戏自身数据）──
// 敌人库里有 17 行提到折射，跨 `enemy.ability` / `enemy_level.talent` / `description` /
// `params` / `explicit_params`。三条最关键：
//   · **深池暗影术师 / 队长**（`enemy_level.talent`）：
//     「不会攻击飞行单位<br>折射：**法术抗性增加70**（**可被沉默**）」
//   · **假想敌：镜膜**（`enemy_level.talent`）：
//     「{{术语|ba.refraction|折射}}<br>最大生命值+100%（受{{异常效果|沉默}}影响后失效，**无法恢复**）」
//   · **愤怒的守墓石像 / 深池方阵战士 / 方阵指挥官 / 伙友卫队**：只以 `{{术语|ba.refraction|折射}}`
//     引用（术语，即**命名空间 `ba.refraction`**），各自的天赋正文另说效果。
//
// ── ⚠ 由此推翻了词典 tooltip 的判读 ──
// 词典（`docs/mechanics-dictionary.md:60`）写「折射 = 生效时，法术抗性+70」——
// 那只是**深池术师那一个载体**的效果。折射本身是个**状态/术语**：
//   **它生效时做什么，由载体的天赋正文决定**（术师给 RES，镜膜给最大生命值）。
// ⇒ 所以本层**只建状态，不建"+70"**：`+70` 是**实例**，必须由调用方连同它的量一起给出。
//   把 70 写成常量，就等于把"按键名猜语义"写进了内核（记忆 `db214eb4` 那条纪律）。
//
// ── 另一条取证出来的性质：**可被沉默** ──
// 术师那条明写「（可被沉默）」；镜膜那条明写「受沉默影响后失效，**无法恢复**」。
// ⇒ **两种载体在"沉默之后能不能回来"上不同**，而这一点本层**不许替它们决定**：
//   模式由调用方给出（`refractionMode`），本层只负责按模式执行。
//   术师那条**只写了"可被沉默"、没写沉默结束后是否恢复**——那是**未取证**的，
//   所以这里既不当"会恢复"也不当"锁死"，而是让调用方显式选。
//
// ── 与异常效果的关系 ──
// PRTS `异常效果` 权威页（客户端 2.7.61，43 异常效果 + 2 占位 + 2 异常组合 + 9 种抗性）
// 里**没有"折射"**（本仓已抓的 raw 全文零命中）⇒ 它**不是**异常效果，
// 与脆弱、迷彩、元素脆弱同类：**Buff/特殊逻辑层**的东西。所以它不进 `abnormalFlag`。

// refractionMode 说明"被沉默之后会怎样"——两种载体实测不同，故必须显式给。
type refractionMode uint8

const (
	//: 沉默结束后恢复（**未取证**的默认档：术师那条只写了「可被沉默」）
	refractionSilenceRecovers refractionMode = iota
	//: 沉默后**永久失效、无法恢复**（镜膜那条明写「无法恢复」）
	refractionSilenceLatches
)

// refractionState 是"这一只**这一刻**的折射"。
//
// 三件事分开存，别合成一个布尔：
//
//	· `Active`——身上有没有这个状态（由天赋/机制置位）；
//	· `Silenced`——当前是否被沉默（**这也是折射"可被沉默"那条的落点**）；
//	· `Latched`——已经因沉默**永久失效**（只有 `refractionSilenceLatches` 会置它）。
//
// ⚠ 合成一个布尔的话，「被沉默所以暂时不生效」与「已经永久失效」就再也分不开——
// 而那正好是术师与镜膜的差别（记忆 `a312e69c`：判据要拆到"每种失配只可能有一个原因"）。
type refractionState struct {
	Active   bool
	Silenced bool
	Latched  bool
	Mode     refractionMode
}

// Set 置位/清除这个状态。
//
// ⚠ 已 `Latched` 时**置位无效**——镜膜那条写的是「无法恢复」，
// 所以"再给一次折射"也不能把它救回来。这一条是本层唯一会"吃掉输入"的地方，
// 故写成显式分支而不是靠调用方自觉。
func (r *refractionState) Set(active bool) {
	if !active {
		r.Active = false
		return
	}
	if r.Latched {
		return
	}
	r.Active = true
}

// Silence 施加/解除沉默。
//
// 镜膜模式下，**一旦被沉默就锁定**（此后即使解除沉默、甚至重新置位也不生效）。
func (r *refractionState) Silence(on bool) {
	r.Silenced = on
	if on && r.Mode == refractionSilenceLatches {
		r.Latched = true
	}
}

// Effective 是这一只**这一刻**的折射是否真的在起作用。
func (r *refractionState) Effective() bool {
	return r.Active && !r.Silenced && !r.Latched
}

// ApplyResistance 是"折射落到法术抗性上"这一种**用法**（深池术师那条）。
//
// ★ `delta` 必须由调用方给：`+70` 是**那个载体的实例**，不是折射的定义。
// 换成镜膜，落点就不是抗性而是最大生命值——那时该走它自己的消费点，不该来这里。
// 本函数刻意不引用任何常量：一旦这里出现字面量 70，就等于把"按键名猜语义"写进了内核。
func (r *refractionState) ApplyResistance(base, delta float64) float64 {
	if !r.Effective() {
		return base
	}
	return base + delta
}

// TraceRefraction 打一行 `REFRACT` 痕迹。
//
// 为什么折射也要留痕：它是**动态状态**，而它的效果落在**别的字段的读取**上
// （抗性、最大生命值），所以"折射生效/失效"这件事在伤害与血量痕迹里**看不出来**——
// 只能看到"这一笔怎么算得不一样了"（记忆 `e681022e` 那一类）。
// ⚠ `eff` 与 `active` 分开报：`active=true eff=false` 就是"被沉默吃掉了"，
// 这两列混在一起时，"沉默生效了"与"折射本来就没给"无法区分。
func TraceRefraction(t float64, who string, r refractionState, delta, base, got float64) {
	if !r.Active && !r.Latched {
		return // 完全没有折射的敌人不产生噪声
	}
	trace("REFRACT t=%.4f enemy=%s active=%t silenced=%t latched=%t eff=%t delta=%.2f base=%.2f got=%.2f",
		t, who, r.Active, r.Silenced, r.Latched, r.Effective(), delta, base, got)
}
