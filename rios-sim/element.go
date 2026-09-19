package main

import (
	"fmt"
	"math"
	"sort"
	"strings"
)

// 元素损伤（ElementBreak）——元素值／爆条／爆发冷却的状态机与五行爆发表。
//
// 判据出处（全部为 PRTS 原文，2026-09-19 抓取）：
//
//  ① `元素` 页（`元素损伤` 重定向至此）——元素值（EP）小节：
//     「默认情况下，每种不同的元素单独记录一份元素值，且初始为最大值（类似生命值）。
//      默认的最大元素值（MAX_EP）为 1000，每秒元素值恢复（EP_RECOVERY_PER_SEC）为 0，
//      损伤抵抗（EP_RESISTANCE）为 0。对于领袖级的敌人类单位，实际最大元素值
//      （与其属性上限）变为 2000。
//      受到的元素损伤 = 损伤值 × (1 − 损伤抵抗 × 0.01)，后续可应用元素损伤倍率提升/降低等效果。
//      实体受到元素损伤时会扣除元素值。中立阵营的实体无法受到元素损伤。」
//
//  ② 同页「元素损伤爆发（ElementBreak）」小节：
//     「当元素损伤令某一项元素值降低至 0 时，会触发相应的元素爆发，俗称'爆条'。
//      元素损伤爆发开始时会立刻给予单位相应的效果，随后进入爆发冷却状态。
//      爆发冷却状态下，单位所有类型的元素值均无法损失、无法被其他手段回复……
//      元素爆发结束时，爆发冷却也将一并结束，随后单位所有种类的元素值恢复至最大值。」
//
//     ⚠ 这一条否掉了一个很自然的错误实现：**不是"扣掉 1000、余量留着"**，而是
//     "降到 0 → 进入冷却（期间对新的元素损伤免疫）→ 冷却结束再整体归满"。
//     按余量留存的写法，连续两次"刚好爆条"会得到完全不同的第二次时刻。
//
//  ③ 同页「元素损伤爆发」表的**阵营分列**：我方角色类单位与"其他单位"是两套效果；
//     并注明「自 2026 年 4 月 7 日……变动后敌人类单位无论阵营，损伤爆发时均使用
//     '敌方单位受到的爆发效果'」。所以：**目标是敌人 → 用 `burstOnEnemy`**；
//     目标是干员 → 用 `burstOnOperator`。
//
//  ④ `游戏数据基础` §5.2.3 元素伤害：
//     DMG_e = max[ 0.05A, 0.01A · max(0, 100 − D) ]，D 为目标的元素抗性最终结果；
//     同页并注明「目标受到元素损伤时也可以使用该公式计算，只需要将 D 值改为
//     目标的损伤抵抗即可」。**注意 A 与 D 是两件东西**：元素**伤害**吃元素抗性，
//     元素**损伤**吃损伤抵抗——别串。
//
// ⚠ 现状：本文件是**机制内核**（状态机 ＋ 数据表），`sim.go` 侧的接线尚未做，
// 也没有任何调用点——与【寒冷】同一处境（原版两台引擎都零实现）。接线时要在
// 敌人的构造处 `newElementState(maxEP)`，并把 `damage()` 挂到"攻击附带的元素损伤"上。

// elementKind 是 PRTS《元素》页的 ID 1..5；0 是占位的"无"，不参与。
type elementKind int

const (
	elemNone   elementKind = 0
	elemSanity elementKind = 1 // 神经损伤 SANITY
	elemWater  elementKind = 2 // 侵蚀损伤 WATER
	elemFire   elementKind = 3 // 灼燃损伤 FIRE
	elemDark   elementKind = 4 // 凋亡损伤 DARK
	elemAnger  elementKind = 5 // 狂躁损伤 ANGER

	numElements = 5

	//: 默认最大元素值（MAX_EP）
	defaultMaxEP = 1000.0
	//: 领袖级敌人类单位的最大元素值（"与其属性上限"）
	leaderMaxEP = 2000.0
	//: 元素类型的内部分名（报错与留痕用，和 PRTS 的"内部ID"一致）
)

// elementName 返回内部ID名（SANITY/WATER/FIRE/DARK/ANGER）。
func elementName(k elementKind) string {
	switch k {
	case elemSanity:
		return "SANITY"
	case elemWater:
		return "WATER"
	case elemFire:
		return "FIRE"
	case elemDark:
		return "DARK"
	case elemAnger:
		return "ANGER"
	}
	return "NONE"
}

// elementDamage 是"受到的元素损伤"：`损伤值 × (1 − 损伤抵抗 × 0.01)`（PRTS《元素》页原文）。
//
// 负数与非正值一律归零：元素损伤只会扣元素值，没有"回复成负损伤"这回事。
// ⚠ `游戏数据基础` 给出的通用式是 `max(0.05A, 0.01A·max(0,100−D))`，与这一式在
// 损伤抵抗 ≤ 95 时逐位相同，只在抵抗 > 95 处差一个 5% 保底。这里取《元素》页
// 这条**专讲元素损伤**的写法；哪天发现实战中抵抗能过 95，回来改成通用式。
func elementDamage(amount, resist float64) float64 {
	if amount <= 0 {
		return 0
	}
	d := amount * (1.0 - resist*0.01)
	if d < 0 {
		return 0
	}
	return d
}

// resolveElementDamage 是元素**伤害**的结算（爆发打出去的那一笔）：
// `max(0.05A, 0.01A · max(0, 100 − D))`，D 为目标元素抗性最终结果。
//
// 与法术伤害**同式**，区别只在于读的是元素抗性而不是法抗。爆发伤害是"无来源"的，
// 所以这里没有闪避参数——不要为了对称给它加一个。
func resolveElementDamage(a, elementRes float64) float64 {
	if a <= 0 {
		return 0
	}
	kept := math.Max(0.0, 100.0-elementRes)
	return math.Max(0.05*a, 0.01*a*kept)
}

// elementBurst 是一次"爆条"的机械载荷。表里同时收两列（对敌／对干员），
// 字段留空即"该列没有这一项"。伤害一律标类型，交给既有结算入口去算，
// 不在本文件里自己扣血——本文件不知道防御、护盾、减伤那些事。
type elementBurst struct {
	Duration float64 //: 爆发与爆发冷却的持续秒数（两列不同，如侵蚀 10s vs 敌人 8s）

	DefDown     float64 //: 立刻永久降低防御力（侵蚀；"不会被重生清除"）
	ResDown     float64 //: 爆发期间法术抗性降低（灼燃，直接加算）
	WeakPct     float64 //: 虚弱比例（凋亡，攻击力降低，最终乘算）
	PalsyStack  int     //: 直接给予的麻痹层数（神经，敌人列）
	PalsyImmune bool    //: 顺带授予"麻痹免疫"

	Direct     float64 //: 立刻造成的伤害
	DirectType string  //: PHYSICAL / MAGIC / TRUE / ELEMENT

	Dot       float64 //: 每秒持续伤害
	DotType   string  //: 同上
	DotGrowth float64 //: 每次触发该单位"普通攻击/技能能力"时每秒伤害的增量（狂躁）
	DotCap    float64 //: Dot 的上限（狂躁，600）
	AspdUp    float64 //: 爆发期间攻击速度（狂躁，直接加算）
	DotIsTrue bool    //: 狂躁的每秒那笔是真实伤害

	Note string //: 表里那一列的原文要点（留痕，不参与计算）
}

// burstOnEnemy 是"其他单位（敌人类单位）受到的效果"列（PRTS《元素》页表）。
// 按 2026-04-07 之后的规则，**敌人类单位无论阵营都用这一列**。
var burstOnEnemy = [numElements + 1]elementBurst{
	elemSanity: {
		Duration: 10,
		// 「若单位不具有麻痹免疫……普通攻击动作期间即将攻击的瞬间或动作开始一定时间
		//   （默认2秒）后获得0.5s麻痹震颤；麻痹免疫：使自身的麻痹失效，但不会清除
		//   相关Buff，获得3层麻痹……随后受到6000点无来源元素普通伤害」
		PalsyStack:  3,
		PalsyImmune: true,
		Direct:      6000,
		DirectType:  "ELEMENT",
		Note:        "麻痹震颤 0.5s（攻击动作被打断）＋麻痹免疫：3 层麻痹；6000 元素",
	},
	elemWater: {
		// 「持续时间降低至8s；立刻减少120点防御力（永久，可无限叠加，
		//   不会被重生清除，直接加算）；随后受到5000点无来源元素普通伤害」
		Duration:   8,
		DefDown:    120,
		Direct:     5000,
		DirectType: "ELEMENT",
		Note:       "−120 防御（永久、不被重生清除）；5000 元素",
	},
	elemFire: {
		// 「爆发期间法术抗性-20（直接加算）；立即受到7000点无来源元素普通伤害」
		Duration:   10,
		ResDown:    20,
		Direct:     7000,
		DirectType: "ELEMENT",
		Note:       "法抗 −20（爆发期间）；7000 元素",
	},
	elemDark: {
		// 「立即获得等时长的50%的虚弱……该虚弱效果持续期间每秒受到800点
		//   无来源元素持续伤害并使该虚弱效果降为(50%×剩余时间÷总持续时间)」
		Duration: 15,
		WeakPct:  50,
		Dot:      800,
		DotType:  "ELEMENT",
		Note:     "50% 虚弱（随剩余时间衰减）；每秒 800 元素",
	},
	elemAnger: {
		// 「无效果」——狂躁对敌人一格是空的，这是原文，不是漏抄。
		Duration: 15,
		Note:     "无效果（对敌人类单位）",
	},
}

// burstOnOperator 是"我方角色类单位受到的效果"列。用于**敌人给我方**上元素损伤时。
var burstOnOperator = [numElements + 1]elementBurst{
	elemSanity: {
		// 「立刻获得等时长的晕眩……随后受到1000点无来源真实伤害」
		Duration:   10,
		Direct:     1000,
		DirectType: "TRUE",
		Note:       "等时长晕眩；1000 真实伤害",
	},
	elemWater: {
		// 「立刻减少100点防御力（永久，可无限叠加，直接加算）；随后受到800点无来源物理普通伤害」
		Duration:   10,
		DefDown:    100,
		Direct:     800,
		DirectType: "PHYSICAL",
		Note:       "−100 防御（永久可叠）；800 物理",
	},
	elemFire: {
		// 「爆发期间法术抗性-20（直接加算）；立刻受到1200点无来源法术普通伤害（可享受法抗减少效果）」
		Duration:   10,
		ResDown:    20,
		Direct:     1200,
		DirectType: "MAGIC",
		Note:       "法抗 −20（爆发期间）；1200 法术（吃这次减抗）",
	},
	elemDark: {
		// 「立即获得等时长的阻回异常效果……停止技力自然回复，并阻止任何形式的
		//   非强制性技力增加……静默……该阻回、静默持续期间每秒损失1点技力并受到
		//   100点无来源法术持续伤害」
		Duration: 15,
		Dot:      100,
		DotType:  "MAGIC",
		Note:     "阻回＋静默；每秒 −1 技力、100 法术",
	},
	elemAnger: {
		// 「爆发期间攻击速度+50（直接加算）；每秒受到一次X点无来源真实伤害
		//   X初始为100，每次触发狂躁单位使用普通攻击/技能的能力时……+50，上限为600」
		Duration:  15,
		AspdUp:    50,
		Dot:       100,
		DotGrowth: 50,
		DotCap:    600,
		DotIsTrue: true,
		Note:      "攻速 +50；每秒 X 真实伤害（100 起、每次能力 +50、上限 600）",
	},
}

// elementState 是**一个实体**的元素值状态：每种元素一份 EP、一份爆发冷却计时。
//
// 指针语义：爆条会改状态，所以按指针挂在实体上（与 `enemy` 的计时器同款）。
type elementState struct {
	//: 最大元素值。领袖级敌人 2000，其余 1000。
	max float64
	//: 每种元素的当前元素值，下标即 `elementKind`（1..5）。初始为最大值。
	ep [numElements + 1]float64
	//: 爆发冷却剩余秒数（>0 即处于爆发冷却：所有元素值不能损失也不能回复）
	cool [numElements + 1]float64
	//: 损伤抵抗（EP_RESISTANCE，单位 %）
	resist float64
}

// newElementState 按最大元素值建一份状态（每种元素初始为最大值）。
func newElementState(max float64) *elementState {
	s := &elementState{}
	s.reset(max)
	return s
}

// reset 把最大元素值与全部元素值重新设好（"元素爆发结束时所有元素值恢复至最大值"）。
func (s *elementState) reset(max float64) {
	if max <= 0 {
		max = defaultMaxEP
	}
	s.max = max
	for i := 1; i <= numElements; i++ {
		s.ep[i] = max
	}
}

// cooling 报告该元素是否正处于爆发冷却。
func (s *elementState) cooling(k elementKind) bool { return s.cool[k] > 0 }

// anyCooling 报告是否有**任一**元素处于爆发冷却——冷却期间"所有类型的元素值均
// 无法损失"，所以这个判断是全局的，不是按元素各管各的。
func (s *elementState) anyCooling() bool {
	for i := 1; i <= numElements; i++ {
		if s.cool[i] > 0 {
			return true
		}
	}
	return false
}

// damage 施加一次元素损伤，返回是否**因此爆条**。返回值真时调用方必须结算
// `burstFor(目标阵营, kind)` 那张表的效果，并把结算来源记成造成本次损伤的来源。
//
// 规则要点（全部来自前面引的原文）：
//   - 冷却期间：所有元素值无法损失 ⇒ 直接吞掉，不报错也不爆条；
//   - 元素值为 0 才爆条（不是"累计到 1000"，两种写法在初始满值下等价，
//     但一旦有回复/上限差异就会分道扬镳，所以按"降到 0"写）；
//   - 损伤值先过 `elementDamage`（吃损伤抵抗）。
func (s *elementState) damage(k elementKind, amount float64) bool {
	if k < elemSanity || k > elemAnger {
		return false
	}
	if s.anyCooling() {
		return false
	}
	d := elementDamage(amount, s.resist)
	if d <= 0 {
		return false
	}
	s.ep[k] -= d
	if s.ep[k] > 0 {
		return false
	}
	s.ep[k] = 0
	return true
}

// ============================================================ 黑板取值层（B 组）
//
// 元素损伤的**数值不在正文里**。原版敌人侧公式编译器写明：
// 「prts.wiki 手写的敌人正文不写数值（「造成一定侵蚀损伤」），真值在敌人同档黑板上」
// （`ak_tactic/enemy_formula.py:547-557`），所以正文只给**种类**，数值必须从黑板取。
//
// 黑板键的真实形状是 **`<前缀>[.attack]@ep_damage_ratio`**，前缀由该敌人的机制决定，
// 实测 40+ 种（`EpDamage.` / `aura.` / `Wake2Sleep.` / `GetEnmey.` / 纯数字 `1.` …）。
// 所以这一层**不解释前缀、不改写键名**，只按**后缀**找出候选：
//   - `*ep_damage_ratio`  比例式（乘数基由调用方给，见下）
//   - `*ep_damage_value`  绝对值
//   - `*ep_damage_scale`  倍率式
//
// ⚠ **拼写错误原样保留**：`GetEnmey.` 原文如此，不许顺手改成 `GetEnemy.`
// ——键名对不上的后果是**静默取空**，比报错难查得多（通告 #7 二）。
//
// ⚠ **命中多个不同值 = 歧义 = 报错，不许挑一个**：同一敌人可以有多条路带元素损伤
// （`Attack.` 与 `Attack2.` 就是两次攻击各一条），值相同 ⇒ 同机制的两条路，可用；
// 值不同 ⇒ **不止一处施加点**，必须由调用方逐处送，不能在这一层猜一条。
// 这是本层唯一会出错的地方，所以它必须吵。

// epKeyKinds 是本层认识的三种元素损伤键后缀。
var epKeyKinds = []string{"ep_damage_ratio", "ep_damage_value", "ep_damage_scale"}

// keyHasEpSuffix 判一个黑板键是否属于元素损伤键族，并给出它的后缀类别。
//
// 判据是**后缀**，不是子串：`xep_damage_ratio2` 不算，
// `GetEnmey.attack@ep_damage_ratio` 与 `1.ep_damage_value` 算。
func keyHasEpSuffix(key string) (string, bool) {
	for _, suf := range epKeyKinds {
		if key == suf || strings.HasSuffix(key, "."+suf) || strings.HasSuffix(key, "@"+suf) {
			return suf, true
		}
	}
	return "", false
}

// EpCandidates 返回黑板里所有元素损伤候选键（**按键名排序**，便于复现）。
//
// 返回值只用于**登记与报错**，不用于"挑一条来用"——见 `ResolveEpAmount` 的歧义规则。
func EpCandidates(bb map[string]float64) []string {
	out := []string{}
	for k := range bb {
		if _, ok := keyHasEpSuffix(k); ok {
			out = append(out, k)
		}
	}
	sort.Strings(out)
	return out
}

// ResolveEpAmount 把黑板解析成"这一处元素损伤的量"。
//
// base 是比例式与倍率式的乘数基。**调用方给什么就是什么**：本层不假定它一定是面板 ATK
// ——那个口径在原版里**没有对照物**（原版根本没有元素损伤的结算层，全树检索见
// `docs/spec-element-fields.md` §四.1），属于**未裁定项**，本层不许替它做决定。
//
// 语义：
//   - 一条候选都没有 ⇒ (0, nil, nil)：这一处本来就没有元素损伤，**不是错**；
//   - 只有一种**语义类别**（比例/绝对值/倍率各算一类）⇒ 取它。同类多条键时
//     值全相同 ⇒ 同机制的多条路，取值；值不同 ⇒ **报错**；
//   - 混了两种以上类别 ⇒ **报错**：送进来的不是"一处损伤"，调用方该逐处送。
func ResolveEpAmount(bb map[string]float64, base float64) (float64, []string, error) {
	keys := EpCandidates(bb)
	if len(keys) == 0 {
		return 0, nil, nil
	}
	byClass := map[string][]string{}
	for _, k := range keys {
		suf, _ := keyHasEpSuffix(k)
		byClass[suf] = append(byClass[suf], k)
	}
	if len(byClass) > 1 {
		return 0, keys, fmt.Errorf(
			"元素损伤：黑板里同时出现 %d 类候选键（%s）——本层只解析「一处」损伤，请调用方逐处送",
			len(byClass), strings.Join(keys, ", "))
	}
	for suf, ks := range byClass {
		sort.Strings(ks)
		first := bb[ks[0]]
		for _, k := range ks[1:] {
			if bb[k] != first {
				return 0, ks, fmt.Errorf(
					"元素损伤：同类键取值不一致（%s）—— %s=%v 与 %s=%v：这不是同机制的两条路，是不止一处施加点",
					suf, ks[0], first, k, bb[k])
			}
		}
		switch suf {
		case "ep_damage_value":
			return first, ks, nil // 绝对值：**不乘** base
		case "ep_damage_ratio", "ep_damage_scale":
			return base * first, ks, nil
		}
	}
	return 0, keys, nil // 不可达：byClass 非空时必在上面 switch 里返回
}

// burstDuration 返回该元素爆发的持续秒数（对敌列；对干员列由调用方按阵营取表）。
func burstDuration(k elementKind, onEnemy bool) float64 {
	if onEnemy {
		return burstOnEnemy[k].Duration
	}
	return burstOnOperator[k].Duration
}

// startBurst 进入爆发冷却：持续 `secs` 秒，期间对新的元素损伤免疫。
func (s *elementState) startBurst(k elementKind, secs float64) {
	if secs <= 0 {
		secs = burstDuration(k, true)
	}
	s.cool[k] = math.Max(s.cool[k], secs)
}

// tick 推进爆发冷却，返回**本帧结束**的那些元素（调用方据此把它们的元素值归满）。
//
// ⚠ 归满按元素各归各的（"单位所有种类的元素值恢复至最大值"是爆发结束那一刻的
// 整体效果，但两次不同元素的爆发可以重叠，所以按元素收口才不会互相顶掉）。
func (s *elementState) tick(dt float64) []elementKind {
	var done []elementKind
	for i := 1; i <= numElements; i++ {
		if s.cool[i] <= 0 {
			continue
		}
		s.cool[i] = math.Max(0.0, s.cool[i]-dt)
		if s.cool[i] == 0 {
			s.ep[i] = s.max
			done = append(done, elementKind(i))
		}
	}
	return done
}

// current 是"当前损伤元素"：**元素值最低**的那一个，平手按 ID 升序（PRTS《元素》页：
// 「游戏会根据当前相应元素值最低>元素ID的顺序实时更新单位的当前损伤元素」）。
// 全满时返回 `elemNone`。
//
// ⚠ 它只用于索敌与图标显示，「不代表实际发生元素损伤爆发的元素」——爆发取决于
// **首个施加**的那一种。别拿它当爆条判据。
func (s *elementState) current() elementKind {
	best, bestEP := elemNone, 0.0
	for i := 1; i <= numElements; i++ {
		if s.ep[i] >= s.max {
			continue
		}
		if best == elemNone || s.ep[i] < bestEP {
			best, bestEP = elementKind(i), s.ep[i]
		}
	}
	return best
}
