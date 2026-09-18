// Package mech 是**关卡特有机制层**。
//
// 博士 2026-09-18 的裁定：「场地机制等关卡特有机制单独拿出来，不要放在模拟器里」
// （补充：「做成 go 侧的独立层，同时把每个活动的机制分开，按需取用」）。
//
// ## 为什么必须单独一层
//
// 田地/病害值、全场总攻击装置、泵站泵水这些东西的共同点是：**只属于某一关**。
// 把它们写进主循环会有两个后果，而且都是慢性的：
//
//   - 主循环里出现「如果这关是怀黍离就……」这种判断，逐关特判越堆越多，
//     通用关卡（1-1 到 2-1 那批）每跑一帧都要为它们付代价；
//   - 更麻烦的是**归属**：一段逻辑既像"机制"又像"引擎"，谁都不敢动它，
//     对拍出偏差时也说不清该回哪一份权威实现去核。
//
// 所以边界画在这里：**主循环只管"时间怎么走、谁打到谁、死了没有"**，
// 场地与装置的脾气全部由本包的机制实现决定；主循环只按帧的固定位置回调它们。
//
// ## 按需取用
//
// 机制**不在编译期自动全开**，而是由规格点名（`Spec.Mechanisms`）：
// Python 侧知道"这一关有哪几样机制"，就写哪几个名字；Go 侧 `Load` 时按名字取。
// 点名了一个本二进制里没有的机制 → **拒跑**（不是忽略）。这条与 `unsupported`
// 那条同源：**"少挂了一个机制"与"这关本来就没这机制"在判决上分不开**，
// 而对拍台分不开的两种结果，早晚会把偏差固化成基线。
//
// 想知道本二进制里有哪些机制，看 `ping` 的 `mechanisms` 字段（`Available()`）——
// Python 侧据此判断"这批机制能不能交给 Go 跑"，而不是各自维护一份名单。
//
// ## 每个活动一份文件
//
// 一个活动一个文件（如 `huai_shu_li.go` 怀黍离、`sr_device.go` 生息演算的
// 全场总攻击装置），文件里 `init()` 注册自己。这样：
//
//   - 「这关的机制到底做了没有」是一眼可见的（文件在不在）；
//   - 各活动的机制**互相看不见**：它们不共享状态，只共享 `Ctx`；
//   - 删一个活动的机制 = 删一个文件，主循环一个字都不用动。
//
// ## 现在的状态：**空层**
//
// 这一版只有注册表、按需装载、以及帧回调的接线（见 `sim.go` 里的三处调用点）。
// 一个真机制都还没落——所以本层对现有判决的影响必须是**零**：不点名就什么都不会
// 发生，对拍语料（12 关 × 2 阵容）全绿就是这条的证据。
//
// 接口里的 `Ctx` 是照**已知道的**两个机制（田地/病害值、全场总攻击装置）实际要
// 用的那几样列的；写第一个真机制时按它真正需要的补，补的时候把出处（原版
// `ak_tactic/battle/sim.py` 的行号）写上——空接口不许凭想象加。
package mech

import "fmt"

// ID 是机制的稳定标识。
//
// 命名约定：`<活动或机制族>.<东西>`，全小写下划线（`huai_shu_li.farmland`、
// `sr.total_attack`）。**这个名字是 Python 与 Go 之间的契约**，改名等于改协议。
type ID string

// Mechanism 是所有机制都要实现的那一条。
//
// 其余能力是**可选**的：实现了哪个可选接口，主循环就在那个位置回调它
// （Go 的接口断言，见 `Set.Start`/`Set.Frame`）。一个只关心"开场改地图"的机制
// 不必写空着的 `Frame`。
type Mechanism interface {
	ID() ID
}

// Starter 在**这一场开始之前**被调用一次。
//
// 用途：按关卡参数改写场景（怀黍离的阻流阀会把田地由 2 片改成 7 片——那发生在
// 敌人第一只出怪之前）。返回错误 = 这一场拒跑。
type Starter interface {
	Start(ctx Ctx) error
}

// Framer 在**每一帧的末尾**被调用（`t += dt` 之前，即这一帧的伤害、击杀、
// 漏怪都已经结算完）。
//
// 位置是定的，理由与主循环的帧内顺序同源：机制看到的是一个**已经结算完的帧**，
// 它自己造成的影响落在下一帧。放在帧中间会让"谁先谁后"变成机制之间的事。
type Framer interface {
	Frame(ctx Ctx, dt float64)
}

// Ctx 是机制在运行期**能看到的**与**能改的**那一小片世界。
//
// 效果一律走"请求"：机制说"把 3 号干员的血扣掉 200 点真伤"，**由主循环施加**。
// 这样帧内顺序的权威始终只有一处，机制之间也不会直接改彼此的状态。
type Ctx interface {
	// ---- 读 ----
	Time() float64
	Frame() int
	DT() float64
	Operators() []OpView
	Enemies() []EnemyView

	// ---- 写（效果请求）----
	//: 按**单位对象下标**扣血（下标 = `Spec.Operators` 里的位置，再部署时是另一个
	//: 对象，所以同一位干员的不同次部署是不同的下标）。真伤不经防御与法抗。
	DamageOperator(index int, raw float64, trueDamage bool)
	//: 按**出怪顺序下标**改这一只敌人的推进速度乘区（1.0 = 不变）。
	ScaleEnemySpeed(index int, scale float64)
	//: 写一行日志（进判决的 `events`，对拍时能看出机制什么时候动的手）。
	Log(format string, args ...any)
}

// OpView 是一名干员在这一帧的样子（只读）。
type OpView struct {
	Index  int
	CharID string
	Name   string
	Cell   [2]int
	HP     float64
	MaxHP  float64
	Alive  bool
}

// EnemyView 是一只敌人在这一帧的样子（只读）。
type EnemyView struct {
	Index    int //: 出怪顺序（与 `Spec.Spawns` 同序）
	Name     string
	Position [2]float64
	HP       float64
	Alive    bool
	Blocked  bool
}

// ---- 注册表 ----

var registry = map[ID]Mechanism{}

// Register 由各活动文件在自己的 `init()` 里调用。
//
// 重复注册或空名字是**编程错误**，直接 panic：这种错在启动时炸出来最好查，
// 拖到运行期会表现成"某一关的判决偶尔不一样"。
func Register(m Mechanism) {
	if m == nil {
		panic("mech: 注册了 nil 机制")
	}
	id := m.ID()
	if id == "" {
		panic("mech: 机制的 ID 不能是空的")
	}
	if _, dup := registry[id]; dup {
		panic(fmt.Sprintf("mech: 机制 %q 注册了两次", id))
	}
	registry[id] = m
}

// Available 列出本二进制里编译进来的机制（按注册顺序不定，调用方排一下）。
func Available() []ID {
	out := make([]ID, 0, len(registry))
	for id := range registry {
		out = append(out, id)
	}
	return out
}

// Set 是一次运行里**按需取用**到的那一组机制。
//
// 回调表里带上各自的 `id`：`starters` 是机制里的**子集**（只有实现了对应可选接口
// 的那些才在里面），下标与 `ids` 对不上，报错时要报得准就只能自己带着名字。
type Set struct {
	ids      []ID
	starters []hookStarter
	framers  []hookFramer
	all      []Mechanism
}

type hookStarter struct {
	id ID
	m  Starter
}

type hookFramer struct {
	id ID
	m  Framer
}

// Load 按名字取机制。有一个名字取不到就整组失败——见包注释里那条：
// 少挂一个机制与"本来没这机制"分不开，所以不许静默跳过。
func Load(ids []string) (*Set, error) {
	set := &Set{}
	for _, name := range ids {
		id := ID(name)
		m, ok := registry[id]
		if !ok {
			return nil, fmt.Errorf("这一关点名了机制 %q，但本模拟器里没有"+
				"（有的：%v）", name, Available())
		}
		set.ids = append(set.ids, id)
		set.all = append(set.all, m)
		if s, ok := m.(Starter); ok {
			set.starters = append(set.starters, hookStarter{id, s})
		}
		if f, ok := m.(Framer); ok {
			set.framers = append(set.framers, hookFramer{id, f})
		}
	}
	return set, nil
}

// IDs 是这一场挂上的机制名（进判决的日志与自检用）。
func (s *Set) IDs() []ID {
	if s == nil {
		return nil
	}
	return s.ids
}

// Empty 说明这一场没有任何机制——主循环据此整段跳过，通用关卡一帧都不多花。
func (s *Set) Empty() bool { return s == nil || len(s.all) == 0 }

// Start 依次调用各机制的 Start。
func (s *Set) Start(ctx Ctx) error {
	if s == nil {
		return nil
	}
	for _, h := range s.starters {
		if err := h.m.Start(ctx); err != nil {
			return fmt.Errorf("机制 %v 开场失败：%w", h.id, err)
		}
	}
	return nil
}

// Frame 依次调用各机制的 Frame。
//
// 顺序 = `Load` 时点名的顺序（不许按 map 遍历，那样每次运行可能不同）。
func (s *Set) Frame(ctx Ctx, dt float64) {
	if s == nil {
		return
	}
	for _, h := range s.framers {
		h.m.Frame(ctx, dt)
	}
}
