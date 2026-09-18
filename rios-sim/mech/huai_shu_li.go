// 怀黍离：田地 / 病害值（活动 `act31side`）。
//
// 权威实现是 `ak_tactic/battle/environment.py`（764 行）。本文件是它的 Go 端口，
// **逐条照抄**，包括三处看起来不对称、但原文就是这么写的地方（见下）。
//
// ## 分工（与技能那一层同一个规矩）
//
// Python 送**几何与参数**：哪些格是田地、分成哪几片、每片的【最大】与【缓存】、
// 每格的【实际】、场上装置的 kind/格子/朝向。Go 跑**时间**：0.2s 释缓存、
// 1s 靠拢、每秒的环境伤害与回复、泵站每秒的增减，以及所有"田地地块病害值 +N"
// 的调用点。
//
// 规格的充分性有两条实测依据（都在仓库里）：
//   - `tools/check_mech_spec.py`：按规格重建的 Python 系统与原系统喂同一串事件，
//     逐帧**精确相等**（含分割/还原/泵水/三个结算读数）；
//   - `farmland_golden_test.go`（由 `tools/gen_farmland_golden.py` 生成）：
//     把同一串事件重放在**本文件**上，逐步比三个量与返回值。
//
// ## 三个量，别合并
//
//   - 【缓存】：污染先落这里。每 0.2 秒释放 1 点，**累加到【最大】上**。
//   - 【最大】：片级的（未被隔断的连片田地共享一个）。0–100 封顶。
//   - 【实际】：**格级**的。每 1 秒向【最大】靠拢一次，步长
//     `ceil(差值/25 + 1)`（`+1` 那项是原文口径的甲种读法，见 environment.py 的
//     `actual_step`：另一种读法是 `ceil(差值/25)`，差 1 点/秒，标为待裁定，
//     改规格里的 `actual_base_step` 即可切换）。
//
// 「按片」与「按格」的区分不是实现细节：阻流阀断开田地之后，各组要
// 「各自取当前最高的【实际】作为新的【最大】」——【实际】不按格存就无从谈起。
//
// ## 三处不对称（原文自己写的，不许"顺手统一"）
//
// 1. 泵站**清澈支只降【最大】**，**污染支既抬【最大】也抬各格【实际】**；
// 2. 抽干（瘴充能）**只动【实际】不动【最大】**；
// 3. 污染**既不直接进【实际】也不直接进【最大】**，先进【缓存】。
package mech

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"
	"strings"
)

// FarmlandID 是这一层的机制名（Python 与 Go 之间的契约，改名等于改协议）。
//
// 已在文件末尾 `init()` 注册。**能注册的那一条判据**是：主循环已经在原版的
// 帧位置回调它（`EnvTicker` = 原版 `sim.py:2164`），而且规格里的每一样东西它
// 都真的用得上——不是"代码写得出来"就算数。还有两处**没接线**，所以 Python 侧
// 的闸门（`simgo/mech.py` 的 `port_reasons`）现在会拒掉用到它们的那几关：
//
//   - 敌人侧的污染来源（被击倒的 `passive_pollut` 等，原版 `sim.py:2221` 的
//     帧位置）——`PostAttacker` 钩子还没加；
//   - 装置的运行期行为（田鼷拆阀 → 地形还原、天桩链）。
//
// 这两件事都只在"点名了本机制、又用到了它们"时才危险，所以闸门按**这一关实际
// 用到的东西**逐条判，而不是一刀切。
const FarmlandID ID = "huai_shu_li.farmland"

// Cell 是一格坐标（MAA 口径：原点左上、y 向下）。
type Cell [2]int

// directions 与 `ak_tactic/battle/devices.py` 的 `DIRECTIONS` 逐字对应。
var directions = map[string]Cell{
	"LEFT":  {-1, 0},
	"RIGHT": {1, 0},
	"UP":    {0, -1},
	"DOWN":  {0, 1},
}

// FarmlandSpec 是 Python 侧送来的田地规格。
//
// 字段名就是 JSON 的键，与 `ak_tactic/simgo/mech.py` 的 `farmland_spec()` 一一对应。
type FarmlandSpec struct {
	Width      int    `json:"width"`
	Height     int    `json:"height"`
	Difficulty string `json:"difficulty"`
	Params     struct {
		BasicDamage      float64 `json:"basic_damage"`
		DamageRatio      float64 `json:"damage_ratio"`
		FirstBasicDamage float64 `json:"first_basic_damage"`
		FirstDamageRatio float64 `json:"first_damage_ratio"`
		HPRecoveryPerSec float64 `json:"hp_recovery_per_sec"`
	} `json:"params"`
	//: 两个节拍与夹取范围**写成规格**而不是 Go 里的常量：它们是原文里的数字，
	//: 改口径时改的是 Python 那一处。
	CacheInterval    float64 `json:"cache_interval"`
	CachePerTick     float64 `json:"cache_per_tick"`
	ActualInterval   float64 `json:"actual_interval"`
	ActualPerDivisor float64 `json:"actual_per_divisor"`
	ActualBaseStep   float64 `json:"actual_base_step"`
	PollutMin        float64 `json:"pollut_min"`
	PollutMax        float64 `json:"pollut_max"`
	PumpRate         float64 `json:"pump_rate"`
	PumpRange        int     `json:"pump_range"`
	PumpRangeBonus   int     `json:"pump_range_bonus"`
	//: 连片田地。**必须带 `maximum` 与 `cache`**：只送格子集合会丢掉
	//: "开局播种把某片【最大】抬到 100"这条信息。
	Groups []SpecGroup `json:"groups"`
	//: 每格的【实际】。**值为 0 的条目也要送**（"存在一个 0"与"没有这一格"
	//: 在状态上是两回事，实测 HS-EX-4 的播种就是 `(1,7): 0.0`）。
	Actual [][3]float64 `json:"actual"`
	//: 被阻流阀等装置占掉、当前不算田地的格子（地形原本是田地）。
	Severed []Cell `json:"-"`
	//: 装置：只送"它是什么 + 在哪 + 朝哪"，不送"它现在做了什么"——
	//: 泵站是每秒动作的，送一个已泵过的结果没有意义。
	Devices []SpecDevice `json:"devices"`
}

// UnmarshalJSON 手写，因为 `severed` 是 `[[x,y], …]`：Go 把 JSON 数字一律解成
// float64，直接解进 `[2]int` 会失败。其余字段走别名类型（不会递归调回本方法）。
func (s *FarmlandSpec) UnmarshalJSON(b []byte) error {
	type alias FarmlandSpec
	aux := struct {
		*alias
		Severed [][2]int `json:"severed"`
	}{alias: (*alias)(s)}
	if err := json.Unmarshal(b, &aux); err != nil {
		return err
	}
	s.Severed = s.Severed[:0]
	for _, c := range aux.Severed {
		s.Severed = append(s.Severed, Cell{c[0], c[1]})
	}
	return nil
}

// SpecGroup 是一片连片田地。
type SpecGroup struct {
	Cells   [][2]int `json:"cells"`
	Maximum float64  `json:"maximum"`
	Cache   float64  `json:"cache"`
}

// SpecDevice 是场上一个与田地有关的装置。
type SpecDevice struct {
	Kind      string `json:"kind"` //: valve / pump / pile
	Key       string `json:"key"`
	Cell      [2]int `json:"cell"`
	Direction string `json:"direction"`
	//: 天桩那一条召唤链的**模板**（甲，甲身上再挂着乙、乙身上挂着天标）。
	//: 保留成原始 JSON 再交给 `Ctx.Summon`：谁造谁是装置配置的一部分，
	//: 什么时候造是机制的事。
	Child json.RawMessage `json:"child,omitempty"`
}

// pileUnit 是机制**自己**对一名召唤物的记账（原版把这些存在单位对象上：
// `monitor` / `awake_timer` / `awake_lost` / `attacked_once` / `attached`…）。
//
// 为什么不放回 `enemy` 结构里：那些字段没有一个是"敌人是什么"，全是**这一条链
// 才知道的状态**。放在机制里，通用关卡一帧都不多花，也不会把怀黍离的概念漏进核心。
type pileUnit struct {
	enemy  int //: 敌人下标（终身有效）
	device int //: 造它的装置下标（甲用；乙/天标是 -1）
	//: 它**自己**的规格（原始 JSON）：血、攻、攻击类型、唤醒阈值、召唤比例……
	//: 一个字段都不必再抄进这个结构里，也不必在 Go 里重写一遍取数口径。
	raw json.RawMessage
	//: "我能造谁"的模板（甲 → 乙，乙 → 天标）。
	tmpl json.RawMessage
	//: 出手用的两个数（只有乙用得上），建的时候顺手从自己的规格里取出来。
	atk        float64
	damageType string

	isParent bool
	isDiver  bool
	isMark   bool

	// ---- 甲 ----
	monitor    bool
	awakeTimer float64
	lost       float64   //: 累计损失的生命比例
	batches    int       //: 已经排过队的批数
	pending    []float64 //: 到点召唤的时刻
	gone       bool      //: 已经不在场（退场/被击倒）

	// ---- 乙 ----
	idleTimer      float64
	attacked       bool
	selfDestructAt float64 //: <0 = 还没安排

	// ---- 天标 ----
	attached    []int //: 干员下标（登场那一刻的快照）
	attachTimer float64
}

// pileTick 是天桩链（原版 `_pile_tick` 3884-4125）。四跳的顺序照原文：
//
//	① 装置召唤甲（跑起来后的第一帧，每装置一名）
//	② 三型各自的状态机（甲监测/激活、乙扑咬、天标每秒伤害）
//	③ 甲退场 → 它那根天桩装置死亡
func (m *farmlandMech) PileTick(ctx Ctx, dt float64) {
	t := ctx.Time()
	if len(m.piles) == 0 && len(m.devices) > 0 {
		m.summonParents(ctx, t)
	}
	for i := 0; i < len(m.piles); i++ {
		u := m.piles[i]
		switch {
		case u.isMark:
			m.markTick(ctx, u, dt, t)
		case u.isDiver:
			m.diverTick(ctx, u, dt, t)
		case u.isParent:
			m.parentTick(ctx, u, dt, t)
		}
	}
	m.deviceDeath(ctx, t)
}

// summonParents 是第①跳：每个天桩装置在**自己那一格**召唤一名甲。
//
// 甲「自缚」（原版天赋第一句），关卡给它指派的那条 `extraRoutes` 路径**不执行**，
// 只作留档——全活动 32 个天桩逐关核过，每个装置格都等于那条路径的起点格。
func (m *farmlandMech) summonParents(ctx Ctx, t float64) {
	for i := range m.devices {
		d := &m.devices[i]
		if d.Kind != "pile" || len(d.Child) == 0 {
			continue
		}
		var child struct {
			Static       bool            `json:"static"`
			Invincible   bool            `json:"invincible"`
			AwakeValue   float64         `json:"awake_value"`
			AwakeHPRatio float64         `json:"awake_hp_ratio"`
			SummonRatio  float64         `json:"awake_summon_ratio"`
			SummonCnt    int             `json:"awake_summon_cnt"`
			SummonDelay  float64         `json:"summon_delay"`
			PollutFull   float64         `json:"pollut_full"`
			Summon       json.RawMessage `json:"summon"`
			Name         string          `json:"name"`
		}
		if err := json.Unmarshal(d.Child, &child); err != nil {
			ctx.Log("天桩 %v 的召唤模板解不开：%v", d.Cell, err)
			continue
		}
		cell := [2]float64{float64(d.Cell[0]), float64(d.Cell[1])}
		idx := ctx.Summon(d.Child, cell)
		ctx.SetEnemyInvincible(idx, child.Invincible)
		m.piles = append(m.piles, &pileUnit{
			enemy:          idx,
			device:         i,
			raw:            d.Child,
			tmpl:           child.Summon,
			isParent:       true,
			monitor:        child.AwakeValue > 0 && child.Invincible,
			selfDestructAt: -1,
		})
		ctx.Log("%s 召唤 %s 于 %v；监测状态：生命百分比 = 所在地块病害值",
			d.Key, child.Name, d.Cell)
	}
}

// parentTick 是甲的状态机（原版 `_pile_parent_tick` 3982-4019）。
//
// ⚠ 两处顺序是照原文的，不是随手写：
//   - **监测态里重设生命用的是"下限 1 点"**（`max(1, 最大生命 × 病害值/100)`）：
//     原文「不会因此死亡」，所以病害值为 0 时它也是 1 点血、不是 0。
//   - **激活那一帧直接 `return`**：不再往下走自伤那一段。少了这个 return，
//     激活的那一秒会白送一次自伤，每次激活都差 1%。
func (m *farmlandMech) parentTick(ctx Ctx, u *pileUnit, dt, t float64) {
	var child struct {
		AwakeValue   float64 `json:"awake_value"`
		AwakeHPRatio float64 `json:"awake_hp_ratio"`
		SummonRatio  float64 `json:"awake_summon_ratio"`
		SummonCnt    int     `json:"awake_summon_cnt"`
		SummonDelay  float64 `json:"summon_delay"`
		PollutFull   float64 `json:"pollut_full"`
	}
	if len(u.raw) == 0 {
		return
	}
	if err := json.Unmarshal(u.raw, &child); err != nil {
		return
	}
	full := child.PollutFull
	if full <= 0 {
		full = 100
	}
	pos := ctx.EnemyPosition(u.enemy)
	cell := Cell{int(math.Round(pos[0])), int(math.Round(pos[1]))}
	if u.monitor {
		pollution := m.field.ActualAt(cell[0], cell[1])
		maxHP := ctx.EnemyMaxHP(u.enemy)
		hp := maxHP * math.Min(1, pollution/full)
		if hp < 1 {
			hp = 1
		}
		ctx.SetEnemyHP(u.enemy, hp)
		if child.AwakeValue > 0 && pollution >= child.AwakeValue {
			u.monitor = false
			u.awakeTimer = 0
			ctx.SetEnemyInvincible(u.enemy, false)
			ctx.Log("天桩-甲 激活（所在地块病害值 %g ≥ %g）→ 开始每秒自伤",
				pollution, child.AwakeValue)
		}
		return
	}
	if child.AwakeHPRatio <= 0 || child.SummonRatio <= 0 {
		return
	}
	u.awakeTimer += dt
	for u.awakeTimer >= 1.0 {
		u.awakeTimer -= 1.0
		maxHP := ctx.EnemyMaxHP(u.enemy)
		hp := ctx.EnemyHP(u.enemy) - maxHP*child.AwakeHPRatio
		if hp < 0 {
			hp = 0
		}
		ctx.SetEnemyHP(u.enemy, hp)
		u.lost += child.AwakeHPRatio
		for float64(u.batches+1)*child.SummonRatio <= u.lost+1e-9 {
			u.batches++
			u.pending = append(u.pending, t+child.SummonDelay)
		}
	}
	due := u.pending[:0]
	for _, at := range u.pending {
		if at <= t {
			m.summonDivers(ctx, u, child.SummonCnt, cell, t)
			continue
		}
		due = append(due, at)
	}
	u.pending = due
}

// summonDivers 是甲在**脚下那一格**召唤 `cnt` 名乙（原版 `_pile_summon` 4021）。
func (m *farmlandMech) summonDivers(ctx Ctx, u *pileUnit, cnt int, cell Cell, t float64) {
	if len(u.tmpl) == 0 || cnt <= 0 {
		return
	}
	var diver struct {
		SelfBind   float64         `json:"self_bind"`
		HitRadius  float64         `json:"hit_radius"`
		Mark       json.RawMessage `json:"mark"`
		Name       string          `json:"name"`
		ATK        float64         `json:"atk"`
		DamageType string          `json:"damage_type"`
	}
	if err := json.Unmarshal(u.tmpl, &diver); err != nil {
		ctx.Log("天桩-甲的召唤模板解不开：%v", err)
		return
	}
	pos := [2]float64{float64(cell[0]), float64(cell[1])}
	for k := 0; k < cnt; k++ {
		idx := ctx.Summon(u.tmpl, pos)
		m.piles = append(m.piles, &pileUnit{
			enemy:          idx,
			device:         -1,
			raw:            u.tmpl,
			tmpl:           diver.Mark,
			atk:            diver.ATK,
			damageType:     diver.DamageType,
			isDiver:        true,
			idleTimer:      diver.SelfBind,
			selfDestructAt: -1,
		})
	}
	ctx.Log("天桩-甲 在 %v 召唤 %d 个%s", cell, cnt, diver.Name)
}

// diverTick 是乙（原版 `_pile_diver_tick` 4039-4090）：自缚 1 秒 → 扑向最近的
// 存活干员 → 贴到（≤0.5）咬一口、挂天标、`enemy_windup` 秒后自毁。
//
// 「范围内第一个我方单位」在数据里是空的（`rangeRadius = −1`），项目取
// 「最近的存活干员、不设距离上限」——两种读法登记在 `docs/verdicts-pending.md`。
func (m *farmlandMech) diverTick(ctx Ctx, u *pileUnit, dt, t float64) {
	if u.selfDestructAt >= 0 && t >= u.selfDestructAt {
		ctx.SetEnemyHP(u.enemy, 0)
		return
	}
	if u.idleTimer > 0 {
		u.idleTimer -= dt
		return
	}
	if u.attacked {
		return
	}
	var cfg struct {
		HitRadius float64         `json:"hit_radius"`
		Mark      json.RawMessage `json:"mark"`
	}
	_ = json.Unmarshal(u.raw, &cfg)
	if cfg.HitRadius <= 0 {
		cfg.HitRadius = 0.5
	}
	pos := ctx.EnemyPosition(u.enemy)
	ops := ctx.Operators()
	target := -1
	best := math.Inf(1)
	var targetPos [2]float64
	for _, op := range ops {
		if !op.Alive || op.HP <= 0 {
			continue
		}
		p := [2]float64{float64(op.Cell[0]), float64(op.Cell[1])}
		d := math.Hypot(p[0]-pos[0], p[1]-pos[1])
		if d < best {
			best, target, targetPos = d, op.Index, p
		}
	}
	if target < 0 {
		return
	}
	if best <= cfg.HitRadius {
		// 贴上去：**换成单点路线**（原版 `e.route = [op.position]` ＋ `e.legs = []`，
		// 从此不动），再咬一口、挂天标、`enemy_windup` 秒后自毁。
		ctx.SetEnemyRoute(u.enemy, [][2]float64{targetPos})
		ctx.HitOperator(target, u.atk, u.damageType)
		u.attacked = true
		u.selfDestructAt = t + ctx.EnemyWindup()
		m.attachMark(ctx, u, u.tmpl, target, targetPos, t)
		return
	}
	// 还没到 → 朝目标扑：**换成一条 `[自己, 目标]` 的路线，交给主循环**（原版
	// 4086-4090 就是这两行）。位移、速度乘区、以及"走完算漏怪要扣命"全部走
	// 通用那一套——自己一步步挪位置会漏掉最后那一步，实测 HS-S-1 就栽在这。
	ctx.SetEnemyRoute(u.enemy, [][2]float64{pos, targetPos})
}

// attachMark 是乙砸下的天标（原版 `_pile_attach_mark` 4092）：
// 在目标所在地块中心造一个，并**当场快照**附着对象（半径 0.3 从格心量出去
// 够不到别格，所以快照就是这一格的人）。
func (m *farmlandMech) attachMark(ctx Ctx, diver *pileUnit, tmpl json.RawMessage,
	target int, cell [2]float64, t float64) {
	if len(tmpl) == 0 {
		return
	}
	var cfg struct {
		AttachRadius float64 `json:"attach_radius"`
		Name         string  `json:"name"`
	}
	_ = json.Unmarshal(tmpl, &cfg)
	radius := cfg.AttachRadius
	if radius <= 0 {
		radius = 0.3
	}
	idx := ctx.Summon(tmpl, cell)
	attached := []int{}
	for _, op := range ctx.Operators() {
		if !op.Alive || op.HP <= 0 {
			continue
		}
		p := [2]float64{float64(op.Cell[0]), float64(op.Cell[1])}
		if math.Hypot(p[0]-cell[0], p[1]-cell[1]) <= radius {
			attached = append(attached, op.Index)
		}
	}
	m.piles = append(m.piles, &pileUnit{
		enemy:          idx,
		device:         -1,
		raw:            tmpl,
		isMark:         true,
		attached:       attached,
		selfDestructAt: -1,
	})
	ctx.Log("%s 在 %v 挂上 %s（附着 %d 人）", "天桩-乙", cell, cfg.Name, len(attached))
}

// markTick 是身上的天标（原版 `_pile_mark_tick` 4114）：附着对象全没了就自毁，
// 否则每秒对每个人结算一次定额伤害。
//
// ⚠ 那是「预计算**无途径**物理伤害」——定额、不吃防御也不吃法抗，所以走的是
// **真伤通道**（原版直接 `op.take(e.attach_damage)`，没走 `resolve_damage`）。
func (m *farmlandMech) markTick(ctx Ctx, u *pileUnit, dt, t float64) {
	ops := ctx.Operators()
	alive := make([]int, 0, len(u.attached))
	for _, i := range u.attached {
		for _, op := range ops {
			if op.Index == i && op.Alive && op.HP > 0 {
				alive = append(alive, i)
			}
		}
	}
	if len(alive) == 0 {
		ctx.SetEnemyHP(u.enemy, 0)
		return
	}
	var dmg float64
	if len(u.raw) > 0 {
		var cfg struct {
			AttachDamage float64 `json:"attach_damage"`
		}
		_ = json.Unmarshal(u.raw, &cfg)
		dmg = cfg.AttachDamage
	}
	u.attachTimer += dt
	for u.attachTimer >= 1.0 {
		u.attachTimer -= 1.0
		for _, i := range alive {
			ctx.DamageOperator(i, dmg, true)
		}
	}
}

// deviceDeath 是第③跳：甲的召唤物全没了 → 那根天桩装置死亡
// （原版 3966-3980）。天桩不改写地块，所以它的死亡不改几何。
func (m *farmlandMech) deviceDeath(ctx Ctx, t float64) {
	for i := range m.piles {
		u := m.piles[i]
		if !u.isParent || u.gone {
			continue
		}
		if ctx.EnemyHP(u.enemy) > 0 {
			continue
		}
		u.gone = true
		if u.device >= 0 && u.device < len(m.devices) {
			ctx.Log("%s 随甲退场而死亡", m.devices[u.device].Key)
		}
	}
}

// Field 是一群连片田地共享的【最大】与【缓存】（对应 Python 的 `Field`）。
type Field struct {
	Cells   map[Cell]bool
	Maximum float64
	Cache   float64
}

func (f *Field) clamp(max, min float64) {
	if f.Maximum > max {
		f.Maximum = max
	}
	if f.Maximum < min {
		f.Maximum = min
	}
}

// IsClear 回答"这一格算不算清水"（原版 `_pm2_tick` 里那一支 + `_in_clear_pump`）。
//
// 两支的先后是**先看自己这一格**再去看泵站：
//  1. 这一格本身是田地且【实际】病害值 ≤ 0 —— 自己就是清水；
//  2. 否则看每一个**泵站**：它的**身后那一格**必须是清水田地（水源地），
//     然后这一格要落在它**前方** `生效范围` 格的射线上（水源地上站着我方单位
//     时再 +`生效范围加成`）。
//
// ⚠ 泵站的朝向是"向前泵"，所以水源地在**身后**（`src = cell − dir`），
// 与 `Pump` 用的是同一套几何——两边不一致的话"泵得动"与"算清水"会各说各话。
func (m *farmlandMech) IsClear(cell [2]int, allies [][2]int) bool {
	fs := m.field
	if fs == nil {
		return false
	}
	if fs.IsFarmland(cell[0], cell[1]) && fs.ActualAt(cell[0], cell[1]) <= 0 {
		return true
	}
	ally := make(map[Cell]bool, len(allies))
	for _, a := range allies {
		ally[Cell{a[0], a[1]}] = true
	}
	for _, d := range m.pumps {
		dir, ok := directions[d.Direction]
		if !ok {
			continue
		}
		src := Cell{d.Cell[0] - dir[0], d.Cell[1] - dir[1]}
		if !fs.IsFarmland(src[0], src[1]) || fs.ActualAt(src[0], src[1]) > 0 {
			continue
		}
		span := fs.spec.PumpRange
		if ally[src] {
			span += fs.spec.PumpRangeBonus
		}
		for k := 1; k <= span; k++ {
			if d.Cell[0]+dir[0]*k == cell[0] && d.Cell[1]+dir[1]*k == cell[1] {
				return true
			}
		}
	}
	return false
}

// Farmland 是运行态的田地系统。
type Farmland struct {
	spec     *FarmlandSpec
	fields   []*Field
	actual   map[Cell]float64
	severed  map[Cell]bool
	allCells map[Cell]bool
	index    map[Cell]*Field
	tCache   float64
	tActual  float64
	//: 已释放/已施加的累计量，进判决日志用（对拍时能看出机制什么时候动的手）。
	Released float64
}

// NewFarmland 按规格建系统。规格自相矛盾（比如某格同时在两片里）时返回错误。
func NewFarmland(spec *FarmlandSpec) (*Farmland, error) {
	fs := &Farmland{
		spec:     spec,
		actual:   map[Cell]float64{},
		severed:  map[Cell]bool{},
		allCells: map[Cell]bool{},
		index:    map[Cell]*Field{},
	}
	for i := range spec.Groups {
		g := &spec.Groups[i]
		f := &Field{Cells: map[Cell]bool{}, Maximum: g.Maximum, Cache: g.Cache}
		for _, c := range g.Cells {
			cell := Cell{c[0], c[1]}
			if _, dup := fs.index[cell]; dup {
				return nil, fmt.Errorf("mech: 田地规格自相矛盾：格子 %v 出现在两片里", cell)
			}
			f.Cells[cell] = true
			fs.index[cell] = f
			fs.allCells[cell] = true
		}
		f.clamp(spec.PollutMax, spec.PollutMin)
		fs.fields = append(fs.fields, f)
	}
	for _, c := range spec.Severed {
		fs.severed[c] = true
		fs.allCells[c] = true
	}
	for _, a := range spec.Actual {
		fs.actual[Cell{int(a[0]), int(a[1])}] = a[2]
	}
	return fs, nil
}

func (fs *Farmland) ID() ID { return FarmlandID }

// ---- 查询 ----

// FieldAt 返回这一格所属的田地片（不是田地则为 nil）。
func (fs *Farmland) FieldAt(x, y int) *Field { return fs.index[Cell{x, y}] }

// IsFarmland 这一格当前是不是田地。
func (fs *Farmland) IsFarmland(x, y int) bool { return fs.index[Cell{x, y}] != nil }

// ActualAt 这一格的【实际】病害值。
func (fs *Farmland) ActualAt(x, y int) float64 { return fs.actual[Cell{x, y}] }

// MaximumAt 这一格所属田地的【最大】病害值。
func (fs *Farmland) MaximumAt(x, y int) float64 {
	if f := fs.index[Cell{x, y}]; f != nil {
		return f.Maximum
	}
	return 0
}

// ---- 装置接口 ----

// AddCache 往该格所属田地的【缓存】里加病害，返回实际加进去的量。
func (fs *Farmland) AddCache(x, y int, amount float64) float64 {
	f := fs.index[Cell{x, y}]
	if f == nil {
		return 0
	}
	f.Cache += amount
	return amount
}

// ZeroCell 把这一格的【实际】清零（阻流阀的行为之一）。
func (fs *Farmland) ZeroCell(x, y int) { delete(fs.actual, Cell{x, y}) }

// DrainCell 从这一格的【实际】里扣 `amount`，返回**实际扣掉的量**。
//
// 三处口径：判据是**这一格**的【实际】> 0（不是所属片的【最大】）；
// 扣的也只有【实际】；不够就按剩余量扣（不写进负数）。
func (fs *Farmland) DrainCell(x, y int, amount float64) float64 {
	c := Cell{x, y}
	cur := fs.actual[c]
	if cur <= 0 {
		return 0
	}
	moved := amount
	if moved > cur {
		moved = cur
	}
	if cur-moved <= 0 {
		delete(fs.actual, c)
	} else {
		fs.actual[c] = cur - moved
	}
	return moved
}

// PolluteCell 把 `amount` 记到这一格所属田地的【缓存】里，返回记入量（非田地给 0）。
func (fs *Farmland) PolluteCell(x, y int, amount float64) float64 {
	f := fs.index[Cell{x, y}]
	if f == nil || amount <= 0 {
		return 0
	}
	f.Cache += amount
	return amount
}

// cellsInRadius 是半径 `radius` 格**圆**内的整数格（含自身）。
//
// 半径 1.0 恰好够到上下左右四邻（斜角 √2 够不到），结果是十字五格。
// 遍历顺序与 Python 的 `cells_in_radius` 一致（先 dy 后 dx，都升序）——
// 同一个片里有多格被加缓存时，浮点加法的顺序会影响最后一位。
func cellsInRadius(x, y int, radius float64) []Cell {
	if radius <= 0 {
		return []Cell{{x, y}}
	}
	span := int(math.Floor(radius))
	out := make([]Cell, 0, (2*span+1)*(2*span+1))
	for dy := -span; dy <= span; dy++ {
		for dx := -span; dx <= span; dx++ {
			if math.Hypot(float64(dx), float64(dy)) <= radius+1e-9 {
				out = append(out, Cell{x + dx, y + dy})
			}
		}
	}
	return out
}

// PolluteArea 把半径 `radius` 格圆内**所有田地格**各 +`amount`，返回记入总量。
//
// 按**地块**算而不是按片算：一片田里有 3 个格在范围内就加 3×amount。
func (fs *Farmland) PolluteArea(x, y int, radius, amount float64) float64 {
	total := 0.0
	for _, c := range cellsInRadius(x, y, radius) {
		total += fs.PolluteCell(c[0], c[1], amount)
	}
	return total
}

// Sever 把这一格从田地里摘掉并重算连通域（阻流阀建成）。
//
// 断开后**各组各自取当前最高的【实际】作为新的【最大】**；切分时**缓存一律归零**
// （建成要么在开场、要么在部署后 3 秒内，那时还没有任何污染）。
func (fs *Farmland) Sever(x, y int) {
	c := Cell{x, y}
	old := fs.index[c]
	if old == nil {
		return
	}
	delete(fs.actual, c)
	fs.severed[c] = true
	rest := map[Cell]bool{}
	for k := range old.Cells {
		if k != c {
			rest[k] = true
		}
	}
	groups := connectedGroups(rest)
	kept := fs.fields[:0:0]
	for _, f := range fs.fields {
		if f != old {
			kept = append(kept, f)
		}
	}
	for _, g := range groups {
		peak := 0.0
		for k := range g {
			if v := fs.actual[k]; v > peak {
				peak = v
			}
		}
		kept = append(kept, &Field{Cells: g, Maximum: peak, Cache: 0})
	}
	fs.fields = kept
	fs.rebuildIndex()
}

// Restore 把这一格还回田地（阻流阀被摧毁/撤回）。
//
// 与 `Sever` 对称，四条边界：
//   - **不是田地的格子什么都不做**（`allCells` 记的是地形原本的田地格）；
//   - 还回来的格子【实际】从 0 起（它从建成起就没被污染记过账）；
//   - **合并时缓存相加**（污染已在缓存里，不该因为合并而消失）；
//   - 【最大】取"旧的最高"与"当前最高的实际"里**更大的那个**——原文那条
//     「各自以当前最高实际作为当前最大」是**切分**时的规矩，合并时照抄会把
//     已经释放进【最大】、【实际】还没爬上去的值抹掉。
func (fs *Farmland) Restore(x, y int) {
	c := Cell{x, y}
	if fs.index[c] != nil || !fs.allCells[c] {
		return
	}
	delete(fs.severed, c)
	delete(fs.actual, c)
	cells := map[Cell]bool{}
	for k := range fs.allCells {
		if !fs.severed[k] {
			cells[k] = true
		}
	}
	groups := connectedGroups(cells)
	fresh := make([]*Field, 0, len(groups))
	for _, g := range groups {
		peak := 0.0
		for k := range g {
			if v := fs.actual[k]; v > peak {
				peak = v
			}
		}
		cache, top := 0.0, 0.0
		for _, f := range fs.fields {
			if intersects(f.Cells, g) {
				cache += f.Cache
				if f.Maximum > top {
					top = f.Maximum
				}
			}
		}
		if peak > top {
			top = peak
		}
		fresh = append(fresh, &Field{Cells: g, Maximum: top, Cache: cache})
	}
	fs.fields = fresh
	fs.rebuildIndex()
}

func (fs *Farmland) rebuildIndex() {
	fs.index = map[Cell]*Field{}
	for _, f := range fs.fields {
		f.clamp(fs.spec.PollutMax, fs.spec.PollutMin)
		for c := range f.Cells {
			fs.index[c] = f
		}
	}
}

// connectedGroups 是四邻连片（斜向相接的两块地不共享病害）。
//
// 返回的顺序**不定**——调用方不许依赖它（Python 那边也是从 set 里 pop 出来的）。
// 状态比较按"格集合排序"做，与顺序无关。
func connectedGroups(cells map[Cell]bool) []map[Cell]bool {
	todo := map[Cell]bool{}
	for c := range cells {
		todo[c] = true
	}
	var out []map[Cell]bool
	for len(todo) > 0 {
		var seed Cell
		for c := range todo { // 取一个种子；顺序不定但不影响结果
			seed = c
			break
		}
		delete(todo, seed)
		group := map[Cell]bool{seed: true}
		stack := []Cell{seed}
		for len(stack) > 0 {
			cur := stack[len(stack)-1]
			stack = stack[:len(stack)-1]
			for _, nb := range [4]Cell{
				{cur[0] + 1, cur[1]}, {cur[0] - 1, cur[1]},
				{cur[0], cur[1] + 1}, {cur[0], cur[1] - 1},
			} {
				if todo[nb] {
					delete(todo, nb)
					group[nb] = true
					stack = append(stack, nb)
				}
			}
		}
		out = append(out, group)
	}
	return out
}

func intersects(a, b map[Cell]bool) bool {
	for c := range a {
		if b[c] {
			return true
		}
	}
	return false
}

// ---- 泵站 ----

// PumpResult 是泵水一次做了什么（便于日志与自检）。
type PumpResult struct {
	Kind   string //: clear / raise / hold
	Source Cell
	Target Cell
	Delta  float64
}

// Pump 让泵站「泵水」一次（每秒结算一次）。
//
// 原文三条边界，这里都按它停住：
//   - **清澈支**（水源地病害值 = 0）只降目标片【最大】，**不动各格【实际】**；
//   - **污染支**既抬【最大】也抬各格【实际】，停止条件是
//     **目标片【最大】≥ 水源地所属片【最大】**（组间比较，不是和水源地那一格的
//     【实际】比）；
//   - `生效范围` 是**前方格数**（默认 1），不是我方单位那种攻击范围几何；
//     水源地有我方单位时 +2。
func (fs *Farmland) Pump(cell Cell, direction string, allyOnSource bool) *PumpResult {
	d, ok := directions[direction]
	if !ok {
		return nil
	}
	src := Cell{cell[0] - d[0], cell[1] - d[1]}
	if !fs.IsFarmland(src[0], src[1]) {
		return nil // 身后一格不是田地 → 不泵水
	}
	span := fs.spec.PumpRange
	if allyOnSource {
		span += fs.spec.PumpRangeBonus
	}
	var target *Cell
	for k := 1; k <= span; k++ {
		cand := Cell{cell[0] + d[0]*k, cell[1] + d[1]*k}
		if fs.IsFarmland(cand[0], cand[1]) {
			target = &cand
			break
		}
	}
	if target == nil {
		return nil // 前方生效范围内没有可用的田地
	}
	g := fs.index[*target]
	if g == nil {
		return nil
	}
	res := &PumpResult{Source: src, Target: *target}
	if fs.ActualAt(src[0], src[1]) <= 0 {
		moved := fs.spec.PumpRate
		if moved > g.Maximum {
			moved = g.Maximum
		}
		g.Maximum -= moved
		g.clamp(fs.spec.PollutMax, fs.spec.PollutMin)
		res.Kind, res.Delta = "clear", -moved
		return res
	}
	srcMax := fs.MaximumAt(src[0], src[1])
	if g.Maximum >= srcMax {
		res.Kind = "hold"
		return res
	}
	g.Maximum += fs.spec.PumpRate
	g.clamp(fs.spec.PollutMax, fs.spec.PollutMin)
	for c := range g.Cells {
		v := fs.actual[c] + fs.spec.PumpRate
		if v > fs.spec.PollutMax {
			v = fs.spec.PollutMax
		}
		fs.actual[c] = v
	}
	res.Kind, res.Delta = "raise", fs.spec.PumpRate
	return res
}

// ---- 演化 ----

// Tick 推进 `dt` 秒：0.2s 释缓存、1s 靠拢，各自累加到点才触发。
func (fs *Farmland) Tick(dt float64) {
	if dt <= 0 {
		return
	}
	fs.tCache += dt
	fs.tActual += dt
	for fs.tCache >= fs.spec.CacheInterval {
		fs.tCache -= fs.spec.CacheInterval
		for _, f := range fs.fields {
			if f.Cache > 0 {
				moved := fs.spec.CachePerTick
				if moved > f.Cache {
					moved = f.Cache
				}
				f.Cache -= moved
				f.Maximum += moved
				f.clamp(fs.spec.PollutMax, fs.spec.PollutMin)
				fs.Released += moved
			}
		}
	}
	for fs.tActual >= fs.spec.ActualInterval {
		fs.tActual -= fs.spec.ActualInterval
		for _, f := range fs.fields {
			for c := range f.Cells {
				cur := fs.actual[c]
				delta := f.Maximum - cur
				if delta == 0 {
					continue
				}
				if delta > 0 {
					cur += actualStep(delta, fs.spec.ActualPerDivisor, fs.spec.ActualBaseStep)
					if cur > f.Maximum {
						cur = f.Maximum
					}
				} else {
					cur -= actualStep(-delta, fs.spec.ActualPerDivisor, fs.spec.ActualBaseStep)
					if cur < f.Maximum {
						cur = f.Maximum
					}
				}
				if cur > fs.spec.PollutMax {
					cur = fs.spec.PollutMax
				}
				if cur < fs.spec.PollutMin {
					cur = fs.spec.PollutMin
				}
				fs.actual[c] = cur
			}
		}
	}
}

// actualStep 是【实际】每秒向【最大】靠拢的步长：`ceil(差值/25 + base)`。
func actualStep(delta, divisor, base float64) float64 {
	if delta <= 0 {
		return 0
	}
	return math.Ceil(delta/divisor + base)
}

// ---- 结算 ----

// DrainPollution 从这一格的【实际】病害值里扣掉 `want`，返回**实际扣掉的量**。
//
// 对应敌人「瘴 / 鄙瘴」的重生期充能（原文：「重生期间每0.5s，若自身所在田地
// 地块病害值>0，则降低此地块10点病害值并获得1层充能」）。
//
// ⚠ 三处口径照原版（`environment.py::drain_cell`），别"顺手统一"：
//   - 判据是**这一格**的病害值 > 0（不是它所属连片的【最大】），扣的也是
//     **这一格**的【实际】；不大于 0 则**不扣、也不给层数**——原文把"降低"
//     与"获得1层充能"写在同一个条件里，调用方拿返回值当那个条件用。
//   - 只动【实际】，**不动【最大】**。这与泵站受污那一支（两者都抬）不对称，
//     但两边原文就是这么写的。
//   - 返回实际扣掉的量而不是请求量：本格不足时按剩余量扣，免得把负数写进去。
func (fs *Farmland) DrainPollution(cell Cell, want float64) float64 {
	cur := fs.actual[cell]
	if cur <= 0 || want <= 0 {
		return 0
	}
	moved := want
	if moved > cur {
		moved = cur
	}
	if left := cur - moved; left <= 0 {
		delete(fs.actual, cell)
	} else {
		fs.actual[cell] = left
	}
	return moved
}

// DrainPollution 是机制层的入口：模拟器在帧序 3.4 问"这一格能扣走多少"。
//
// 参数是**整数格**（原版 `e.cell()`）。调用方传浮点不会报错，只是永远取不到，
// 于是充能永远是 0 层、整条机制静默失效——所以这里签名就定为整数格。
func (m *farmlandMech) DrainPollution(cell [2]int, want float64) float64 {
	if m.field == nil {
		return 0
	}
	return m.field.DrainPollution(Cell{cell[0], cell[1]}, want)
}

// PolluteAround 是田地这一层对 `PollutionAdder` 的回答（「祟」的蜕皮被动）。
//
// 原版 `_pollute_around` 最后调的就是 `farmland.pollute_area(int(cx), int(cy),
// radius, amount)`——**圆心已经在模拟器那边按两种口径取好了**，这里只负责
// "半径内哪些格子是田地、每格加多少"。半径按**圆**算（半径 1.0 恰好够到上下
// 左右四邻、够不到斜角），这一步与击倒污染共用同一份 `PolluteArea`。
func (m *farmlandMech) PolluteAround(cell [2]int, amount float64, radius float64) float64 {
	if m.field == nil || amount <= 0 {
		return 0
	}
	if radius <= 0 {
		radius = 1.0
	}
	return m.field.PolluteArea(cell[0], cell[1], radius, amount)
}

// DeployDamage 是部署瞬间的一次性环境法术伤害（病害值为 0 时不结算）。
func (fs *Farmland) DeployDamage(x, y int) float64 {
	a := fs.ActualAt(x, y)
	if a <= 0 || !fs.IsFarmland(x, y) {
		return 0
	}
	return fs.spec.Params.FirstBasicDamage + a*fs.spec.Params.FirstDamageRatio
}

// DamagePerSecond 是每秒的环境法术伤害。
func (fs *Farmland) DamagePerSecond(x, y int) float64 {
	a := fs.ActualAt(x, y)
	if a <= 0 || !fs.IsFarmland(x, y) {
		return 0
	}
	return fs.spec.Params.BasicDamage + a*fs.spec.Params.DamageRatio
}

// RegenPerSecond 是病害值为 0 时的每秒回复量；不为 0 则为 0。
func (fs *Farmland) RegenPerSecond(x, y int) float64 {
	if !fs.IsFarmland(x, y) || fs.ActualAt(x, y) > 0 {
		return 0
	}
	return fs.spec.Params.HPRecoveryPerSec
}

// ---- 快照（对拍用） ----

// Snapshot 是三个量的一份可比快照。
//
// **片按格集合排序、格按坐标排序**：Go 的 map 遍历顺序是随机的，
// Python 那边的分组顺序也不保证一致，所以比较必须与顺序无关。
type Snapshot struct {
	Fields [][3]float64 //: 每片 [片身份, 最大, 缓存]（片身份 = 格集合的规范编码，与顺序无关）
	Actual [][3]float64 //: 每格 [x, y, 实际]
}

// Snapshot 取当前状态。
func (fs *Farmland) Snapshot() Snapshot {
	frs := make([][3]float64, 0, len(fs.fields))
	for _, f := range fs.fields {
		xs := []int{}
		for c := range f.Cells {
			xs = append(xs, c[0]*1000+c[1])
		}
		sort.Ints(xs)
		sum := 0.0
		for _, v := range xs {
			sum = sum*1000 + float64(v)
		}
		frs = append(frs, [3]float64{sum, f.Maximum, f.Cache})
	}
	sort.Slice(frs, func(i, j int) bool { return frs[i][0] < frs[j][0] })
	out := make([][3]float64, 0, len(fs.actual))
	for c, v := range fs.actual {
		out = append(out, [3]float64{float64(c[0]), float64(c[1]), v})
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i][0] != out[j][0] {
			return out[i][0] < out[j][0]
		}
		return out[i][1] < out[j][1]
	})
	return Snapshot{Fields: frs, Actual: out}
}

// ================================================================ 主循环里的那一半

// farmlandMech 是田地/病害值在**主循环里**的那一半：状态机在上面的 `Farmland`，
// 这里只负责"什么时候动它"。
//
// 分开的理由与整层同源：状态机可以脱离战斗单独验证（`farmland_golden_test.go`
// 就是这么驱的），而帧位置只能对着原版逐行核。
type farmlandMech struct {
	field *Farmland
	pumps []SpecDevice
	//: 全部装置（含天桩）。天桩链要读它们的格子与"我能造谁"的模板，
	//: 所以整份留着；泵站另有 `pumps` 那一份给 `EnvTick` 用。
	devices []SpecDevice
	//: 天桩链的记账（甲/乙/天标三种，按造出来的先后）。
	piles []*pileUnit
	//: 环境伤害的**整秒累加器**（原版 `self._env_timer`）。用整数计数而不是
	//: "≥1 秒就清零"：掉帧时 dt 会一次跨过不止一秒，只结一次等于把伤害漏掉，
	//: 而 `fps=1` 的粗扫正是搜索里用得最多的档（原版 1344-1351 写的就是这个）。
	envTimer float64
	//: 已经结算过"被击倒"效果的那几只（原版每只敌人身上的 `death_done`）。
	dead map[int]bool
	//: 敌方技能出手的计时（键 = 出怪顺序下标），见 `AttackTick`。
	skillTimers map[int]*skillAtkState
}

func newFarmlandMech(cfg json.RawMessage) (Mechanism, error) {
	if len(cfg) == 0 {
		return nil, fmt.Errorf("没收到田地规格（点名了 %s，规格里却没有它的参数）",
			FarmlandID)
	}
	var spec FarmlandSpec
	if err := json.Unmarshal(cfg, &spec); err != nil {
		return nil, fmt.Errorf("田地规格解不开：%w", err)
	}
	fs, err := NewFarmland(&spec)
	if err != nil {
		return nil, err
	}
	m := &farmlandMech{field: fs}
	for _, d := range spec.Devices {
		switch d.Kind {
		case "pump":
			m.pumps = append(m.pumps, d)
		case "pile":
			// 天桩：整条召唤链（装置 → 甲 → 乙 → 天标）。模板住在它的 `child`
			// 里，时间由 `PileTick` 跑。**没有模板就拒跑**——一只不会召唤的
			// 天桩与"这一关没有天桩"在判决上分不开。
			if len(d.Child) == 0 {
				return nil, fmt.Errorf("天桩 %q @%v 没带召唤模板（甲）", d.Key, d.Cell)
			}
		default:
			// 阻流阀**不该出现在规格里**：开场那一次断田已经算进几何，它仅剩的
			// "运行期被拆掉 → 地形还原"住在装置层、本机制不碰（Python 侧
			// `farmland_spec` 不送它）。收到了就拒跑——"本机制不处理的装置"与
			// "这一关没有装置"在判决上分不开。
			return nil, fmt.Errorf("田地规格里有本机制不处理的装置 %q（%s @%v）",
				d.Kind, d.Key, d.Cell)
		}
		m.devices = append(m.devices, d)
	}
	return m, nil
}

func (m *farmlandMech) ID() ID { return FarmlandID }

// EnvTick 对应原版 `sim.py:1327-1375` 的 `_environment_tick`。
// 三个节拍各归各的：【缓存】每 0.2s 释放、【实际】每秒靠拢（都在 `field.Tick`
// 里），而**环境伤害按整秒**结算——因为原文写的是「每秒受到 … 环境法术伤害」。
func (m *farmlandMech) EnvTick(ctx Ctx, dt float64) {
	m.field.Tick(dt)

	m.envTimer += dt
	ticks := int(m.envTimer)
	if ticks <= 0 {
		return
	}
	m.envTimer -= float64(ticks)

	// 泵水必须排在伤害结算**之前**：泵水改的是病害值，而这一秒的伤害要按**泵过
	// 之后**的值算。反过来写的话，玩家用泵站压低病害值的那一秒仍会按旧值挨打，
	// 而且这个偏差每秒都发生（原版 1353-1355 写明了）。
	if len(m.pumps) > 0 {
		ally := map[Cell]bool{}
		for _, o := range ctx.Operators() {
			if o.Alive {
				ally[Cell{o.Cell[0], o.Cell[1]}] = true
			}
		}
		for _, d := range m.pumps {
			dir := directions[d.Direction]
			src := Cell{d.Cell[0] - dir[0], d.Cell[1] - dir[1]}
			m.field.Pump(d.Cell, d.Direction, ally[src])
		}
	}

	for _, o := range ctx.Operators() {
		if !o.Alive {
			continue
		}
		cell := Cell{o.Cell[0], o.Cell[1]}
		if !m.field.IsFarmland(cell[0], cell[1]) {
			continue
		}
		// 环境伤害走 `Combatant.take`（`unit.py:104`）：**只过屏障，不减防御与法抗**，
		// 所以这里按真伤报。
		if dmg := m.field.DamagePerSecond(cell[0], cell[1]); dmg > 0 {
			// 环境伤害也留**逐笔**痕迹，且单独一个前缀：`OPDMG` 只知道"谁掉了
			// 多少血"，看不出是哪一路——HS-EX-8 上两边总量相同而阵亡时刻差 7 秒，
			// 正是"哪一路快了"看不出来才查不下去。`op_cell` 与 `ticks` 一起记，
			// 是为了区分"病害值高"和"这一秒多结算了一次"。
			ctx.Trace("ENV t=%.4f idx=%d cell=%d,%d dmg=%.3f ticks=%d actual=%.4f",
				ctx.Now(), o.Index, cell[0], cell[1], dmg*float64(ticks), ticks,
				m.field.ActualAt(cell[0], cell[1]))
			ctx.DamageOperator(o.Index, dmg*float64(ticks), true)
			continue
		}
		// 病害值为 0 的田地改成回血，回复量与病害值无关（恒 `hp_recovery_per_sec`）。
		// 这是同一个机制的两面，不是两个机制。
		if heal := m.field.RegenPerSecond(cell[0], cell[1]); heal > 0 {
			ctx.HealOperator(o.Index, heal*float64(ticks))
		}
	}
}

func init() { RegisterFactory(FarmlandID, newFarmlandMech) }

// AttackTick 对应原版 `sim.py:3468` 的 `_skill_attack_tick`：怀黍离
// 「玷 / 勿玷」的技能「污」。
//
// 【正文来历】prts 图鉴「玷 / 勿玷」技能 0 原文：
//
//	天赋：**不进行远程普通攻击**
//	技能0「污」（初始 7）：攻击场上**1 名部署于地面**的我方单位，
//	对**目标及其周围 4 格**的单位造成**攻击力 100% 的物理伤害**；
//	自身位于病害值 > 0 的田地地块时，当次攻击**额外附加攻击力 80% 的
//	法术普通伤害**，且**令目标地块病害值 +5**；※此技能不可沉默
//
// 四件事必须与原版一致：
//
//  1. **"全图"= 不看射程**（`rangeRadius` 是 −1，正是"不进行远程普攻"的后果），
//     挑的是**最后部署的那一名地面干员**（`block_cnt > 0` 判"地面"）。
//     ⚠ 挑不到人时**计时器已经清零了**（原版 3513-3517 就是这个顺序）：
//     不是"等人来了马上放"，而是"这一拍空过、重新计 7 秒"。
//  2. **"周围 4 格"是曼哈顿距离 1 的十字五格**（目标格 + 上下左右），
//     **不是**半径 1.0 的圆：斜角不在里面。别复用 `PolluteArea` 的圆。
//  3. **两段各减一次**：物理那段照常结算，法术那段在物理之后**再减一次法抗**
//     （原版 3496-3498 写明了"不是把两部分加起来当一次伤害打"）。
//  4. **法术附加与"目标地块 +5"共用一个条件**：出手者**自己**站在受污染的田地上
//     （`actual_at(自己那格) > 0`）——不是目标那格，也不是"这一关有田地"。
func (m *farmlandMech) AttackTick(ctx Ctx, dt float64) {
	if m.skillTimers == nil {
		m.skillTimers = map[int]*skillAtkState{}
	}
	windup := ctx.EnemyWindup()
	for _, e := range ctx.Enemies() {
		if e.SkillAtkScalePhys == 0 && e.SkillAtkScaleMagic == 0 {
			continue
		}
		if !e.Alive || e.Leaked || e.OffMap {
			continue
		}
		// 原版这条 tick 的闸门（`sim.py:4352-4354`）：
		// `if e.frozen or e.down or e.stun_timer > 0 or e.idle_timer > 0
		//  or e.disarm_timer > 0: continue`。
		//
		// ⚠ 只接了 `frozen`：Go 侧还没有 down / stun / idle / disarm 这四种
		// 状态（它们要靠倒地与控场类效果才会出现）。这里**不写**"假装它们为
		// 假"的占位——留一句说明比留一个恒假的字段更诚实。
		//
		// 少了这道闸门的症状：被冻住的敌人照样按自己的计时器放技能出手。
		// HS-EX-8 上就是「勿玷」在 63.3–71.3 的冻结窗口里多打了一次
		// （原版 70.30 只有一笔 335，Go 有两笔）。
		if e.Frozen {
			continue
		}
		st := m.skillTimers[e.Index]
		if st == nil {
			// 原版每只敌人的 `skill_atk_first` 初值为真（`unit.py` 的字段默认值）。
			st = &skillAtkState{first: true}
			m.skillTimers[e.Index] = st
		}
		st.timer += dt
		if st.timer < st.need(e) {
			continue
		}
		st.timer = 0
		st.first = false
		target, ok := skillAtkTarget(ctx, e)
		if !ok {
			continue
		}
		ctx.PauseEnemy(e.Index, windup)
		cx, cy := target.Cell[0], target.Cell[1]
		cells := [][2]int{{cx, cy}, {cx + 1, cy}, {cx - 1, cy}, {cx, cy + 1}, {cx, cy - 1}}
		if e.SkillAtkCross <= 0 {
			cells = [][2]int{{cx, cy}}
		}
		polluted := m.field.ActualAt(e.Cell[0], e.Cell[1]) > 0
		mag := 0.0
		if polluted {
			mag = e.ATK * e.SkillAtkScaleMagic
		}
		// 一次技能出手的账：出手者、出手者自己的格、目标格、十字五格、中标者。
		// 与 `SPLASH-CENTER` 同一用意——"打到了谁"必须能从痕迹上点数。
		victims := make([]string, 0, len(cells))
		for _, c := range cells {
			op, ok := opAtCell(ctx, c)
			if !ok {
				continue
			}
			victims = append(victims, fmt.Sprintf("%s@%d,%d", op.Name, c[0], c[1]))
			// ① 基础物理（正文 100% → `skill_atk_scale_phys`），逐目标减防
			ctx.HitOperator(op.Index, e.ATK*e.SkillAtkScalePhys, "PHYSICAL")
			// ② 附加法术，单独再减一次法抗
			if mag > 0 {
				ctx.HitOperator(op.Index, mag, "MAGIC")
			}
		}
		ctx.Trace("SKILLATK t=%.4f enemy=%s ecell=%d,%d target=%s tcell=%d,%d polluted=%t mag=%.2f victims=%s",
			ctx.Now(), e.Name, e.Cell[0], e.Cell[1], target.Name, cx, cy, polluted, mag,
			strings.Join(victims, "|"))
		// ③ 令**目标地块**病害值 +N（记入【缓存】，不是直接改【实际】）
		if polluted && e.SkillAtkPollut > 0 {
			if got := m.field.PolluteCell(cx, cy, e.SkillAtkPollut); got > 0 {
				ctx.Log("%s 技能「污」→ (%d,%d) 田地病害 +%g 记入缓存",
					e.Name, cx, cy, got)
			}
		}
	}
}

// skillAtkState 是一只敌人的技能出手计时（原版敌人对象上的
// `skill_atk_timer` 与 `skill_atk_first` 两个字段）。
type skillAtkState struct {
	timer float64
	first bool
}

// need 是这一拍等多久：第一次用**初始**值，之后用间隔；
// 间隔为 0 时回落到普攻间隔（原版 3509-3510）。
func (st *skillAtkState) need(e EnemyView) float64 {
	if st.first {
		return e.SkillAtkInit
	}
	if e.SkillAtkInterval != 0 {
		return e.SkillAtkInterval
	}
	return e.AttackInterval
}

// skillAtkTarget 挑谁（原版 `_skill_atk_target` 3566-3580）：
// **全图**、只要地面单位，取**最后部署**的那一名（与既有敌方索敌口径一致）。
func skillAtkTarget(ctx Ctx, e EnemyView) (OpView, bool) {
	var picked OpView
	found := false
	for _, op := range ctx.Operators() { // 顺序 = 部署顺序，越靠后越晚
		if !op.Alive || op.HP <= 0 {
			continue
		}
		if e.SkillAtkGroundOnly && op.BlockCnt <= 0 {
			continue
		}
		picked, found = op, true
	}
	return picked, found
}

// opAtCell 取这一格上的我方单位（原版 `_alive_op_at`：
// `op.alive and op.position == cell`；同一格不会站两个人）。
func opAtCell(ctx Ctx, cell [2]int) (OpView, bool) {
	for _, op := range ctx.Operators() {
		if op.Alive && op.Cell == cell {
			return op, true
		}
	}
	return OpView{}, false
}

// State 把田地状态交给判决（对拍用，见 `Snapshotter`）。
//
// 形态刻意与 Python 侧的规格**同形**（`groups: [{cells: [[x,y]…], maximum, cache}]`
// + `actual: [[x,y,值]…]`，两边都排序）：对拍台于是能拿它和 `farmland_spec()` 直接
// 逐项比，不必各写一套解析。**不要**用 `Snapshot()` 里那个数字编码当身份——
// 19 格的十进制拼接会超出 float64 的有效位，那是"看起来唯一、实际会撞"的坑。
func (m *farmlandMech) State() any {
	groups := make([]any, 0, len(m.field.fields))
	for _, f := range m.field.fields {
		cells := make([][2]int, 0, len(f.Cells))
		for c := range f.Cells {
			cells = append(cells, [2]int{c[0], c[1]})
		}
		sort.Slice(cells, func(i, j int) bool {
			if cells[i][0] != cells[j][0] {
				return cells[i][0] < cells[j][0]
			}
			return cells[i][1] < cells[j][1]
		})
		groups = append(groups, map[string]any{
			"cells": cells, "maximum": f.Maximum, "cache": f.Cache,
		})
	}
	// 片的顺序不保证（Go 的 map 遍历随机、Python 的分组顺序也不保证），
	// 所以按**格集合的字符串**排一次，让两边的数组可以按下标逐项比。
	sort.Slice(groups, func(i, j int) bool {
		return cellKey(groups[i]) < cellKey(groups[j])
	})
	actual := make([][3]float64, 0, len(m.field.actual))
	for c, v := range m.field.actual {
		actual = append(actual, [3]float64{float64(c[0]), float64(c[1]), v})
	}
	sort.Slice(actual, func(i, j int) bool {
		if actual[i][0] != actual[j][0] {
			return actual[i][0] < actual[j][0]
		}
		return actual[i][1] < actual[j][1]
	})
	return map[string]any{"groups": groups, "actual": actual}
}

// cellKey 把一片的格集合变成可排序的字符串（只用于排序，不参与比较）。
func cellKey(g any) string {
	m, ok := g.(map[string]any)
	if !ok {
		return ""
	}
	cells, _ := m["cells"].([][2]int)
	var b []byte
	for _, c := range cells {
		b = append(b, fmt.Sprintf("%d,%d;", c[0], c[1])...)
	}
	return string(b)
}

// PostAttack 对应原版 `sim.py:3891-3905` 的 `_on_enemy_death`：**被击倒之后**
// 给圆心周围的田地加病害（记入【缓存】）。
//
// 三件事必须与原版逐字一致，否则病害值的量对不上：
//
//  1. **圆心**：被阻挡时是**挡它的那个干员**脚下那一格，否则是敌人自己那一格
//     （`_pollute_around` 1280-1298）。不是"敌人自己那一格"——这是最容易想当然
//     写错的一处：一只被挡在干员身前的敌人倒下时，污染落在**干员**脚下。
//  2. **去重**：原版靠 `e.death_done` 标记，一只敌人只结算一次。这里用出怪顺序
//     下标记，等价（那个标记在整份 `sim.py` 里只有这一处读）。
//  3. **漏掉的不算**：`not e.leaked and not e.off_map`——走到终点扣了命的那一只
//     不是"被击倒"，它不该污染田地。
func (m *farmlandMech) PostAttack(ctx Ctx, dt float64) {
	if m.dead == nil {
		m.dead = map[int]bool{}
	}
	for _, e := range ctx.Enemies() {
		if e.Alive || e.Leaked || e.OffMap || m.dead[e.Index] {
			continue
		}
		m.dead[e.Index] = true
		if e.PollutOnDeath <= 0 {
			continue
		}
		cx, cy := e.Cell[0], e.Cell[1]
		if e.HasBlocker {
			cx, cy = e.BlockerCell[0], e.BlockerCell[1]
		}
		radius := e.PollutRadius
		if radius <= 0 {
			radius = 1.0
		}
		got := m.field.PolluteArea(cx, cy, radius, e.PollutOnDeath)
		if got > 0 {
			ctx.Log("%s 被击倒 → 田地病害 +%g 记入缓存", e.Name, got)
		}
	}
}
