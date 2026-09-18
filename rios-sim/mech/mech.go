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
// 这一层现在有注册表、按需装载、以及四处帧回调的接线（见 `sim.go` 里的调用点）。
// 落地的第一个真机制是怀黍离的田地/病害值（`huai_shu_li.go`）——它**不点名就
// 什么都不会发生**：通用关卡（1-7 那类）的判决与没有这一层时逐位相同，对拍语料
// （12 关 × 2 阵容）全绿就是这条的证据。
//
// 接口里的 `Ctx` 是照**已知道的**两个机制（田地/病害值、全场总攻击装置）实际要
// 用的那几样列的；写下一个真机制时按它真正需要的补，补的时候把出处（原版
// `ak_tactic/battle/sim.py` 的行号）写上——空接口不许凭想象加。补过的一处：
// `HealOperator`（田地病害值为 0 时每秒回血，`sim.py:1373-1375`）。
package mech

import (
	"encoding/json"
	"fmt"
)

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

// EnvTicker 在**推进之后、阻挡之前**被调用。
//
// 对应原版 `sim.py:2164` 的 `_environment_tick`（帧序 3.7）。位置不能挪到帧末：
// 那一处要算的是"**这一秒**站在田地上的我方单位吃多少环境伤害、回多少血"，
// 而原版把环境伤害排在**阻挡与出手之前**——挪到帧末会让"这一帧刚被阻挡的敌人
// 把干员打退场"与"这一帧的环境伤害"的先后关系反过来，每一秒都差一次。
type EnvTicker interface {
	EnvTick(ctx Ctx, dt float64)
}

// AttackTicker 在**两次出手之间**被调用（原版 `sim.py:2221` 之前那一处
// `_skill_attack_tick`，帧序 7.2）。
//
// 为什么它和 `PostAttacker` 分成两个钩子：这两个回调在**同一帧的两处**，
// 原版把它们排在普攻之后、结算之前，但**先后有别**——技能出手先算（它自己的
// 出手会占住敌人的动作时间），被击倒的一次性效果后算（技能出手可能正好打死人，
// 那个"打死"要等到 7.5 才结算）。合成一个钩子就必须在机制内部自己排序，
// 而那正是"机制之间不许有顺序"想避免的事。
type AttackTicker interface {
	AttackTick(ctx Ctx, dt float64)
}

// PostAttacker 在**两次出手之后、结算之前**被调用。
//
// 对应原版 `sim.py:2221` 的 `_enemy_mech_tick`（帧序 7.5）。这一处专门处理
// **"这一帧谁把谁打倒了"之后的那些一次性效果**：被击倒时给田地加病害
// （`_on_enemy_death` → `passive_pollut`）、标记退场、明识形态清水。
// 位置的理由写在原版那一行上：排在两个出手之后，"这一帧谁的出手把谁打倒了，
// 这里就看得到"；排在结算之前，则"这一帧倒下的"不会漏掉这一次效果。
//
// ⚠ 它**不是**帧末那个 `Framer`：帧末看到的是一整帧都结算完的世界（漏怪、扣命
// 都记过了），而这里要的是"刚被打倒、还没进结算"的那一刻。
type PostAttacker interface {
	PostAttack(ctx Ctx, dt float64)
}

// PileTicker 是天桩链那一层（怀黍离装置「天桩」：装置 → 甲 → 乙 → 天标）。
//
// 排在 `EnvTick` **之后**：原版是 3.7 `_environment_tick` → 3.8 `_device_tick`
// → 3.9 `_pile_tick`，而甲监测的是"**这一帧已经被环境算过**的病害值"。
type PileTicker interface {
	PileTick(ctx Ctx, dt float64)
}

// Summoner 让机制在运行期**造出敌人**（装置造甲、甲造乙、乙造天标）。
//
// 模板是机制从自己那份规格里拿到的**一段 JSON**（"我能造谁"写在造它的人的
// 规格里），模拟器只负责把它变成场上的一个对象：`mech` 包不认 `SpawnSpec`，
// 也不该认——它只递一段规格过去。
//
// 返回的下标与 `Enemies()` 同源且**终身有效**：模拟器只追加、不删除，
// 机制可以拿它记账（谁造的、造出来那个现在是死是活）。
type Summoner interface {
	Summon(template json.RawMessage, cell [2]float64) int
}

// PollutionDrainer 让**模拟器**从机制手里扣走病害值（怀黍离「瘴 / 鄙瘴」的
// 重生期充能：重生窗口里每 0.5s 吸走本格 10 点）。
//
// 方向与 `Summoner` 相反：那是机制要模拟器做事，这是模拟器要机制交数据。
// 之所以由模拟器发起，是因为**"什么时候吸"是敌人侧的行为**（原版写在
// `_reborn_tick` 里，与田地那一步是两个函数），而"病害值住在哪一格、扣多少"
// 是田地这一层的事。谁发起的就由谁那边写循环，机制只回答一个问题。
//
// 返回**实际扣掉的量**（不是请求量）：本格不足时按剩余量扣；本格 ≤ 0 时返回 0。
// 调用方拿这个返回值当条件用——原文把"降低病害值"与"获得1层充能"写在同一个
// 条件里，所以"没扣到"就等于"没给层数"。
type PollutionDrainer interface {
	DrainPollution(cell [2]int, want float64) float64
}

// PollutionAdder 是 `PollutionDrainer` 的反面：**模拟器**请机制在某一格周围
// 给田地**加**病害（怀黍离「祟」的蜕皮被动：每次挨打在圆心半径 1.0 内加）。
//
// 为什么也由模拟器发起：那是敌人侧的行为（原版写在 `_enemy_on_hit` 里），
// 而"哪几格是田地、加的是缓存还是实际"是田地这一层的事。机制只回答
// "加到了多少"。
//
// 返回**实际记入缓存的总量**（范围内每格各加 `amount`，所以通常是若干倍；
// 一格都没命中就返回 0）。调用方只把它写进日志——它不影响判决。
type PollutionAdder interface {
	PolluteAround(cell [2]int, amount float64, radius float64) float64
}

// ClearWaterProbe 回答"这一格算不算**清水**"（怀黍离「祟」明识形态的清水判定，
// 原版 `_pm2_tick` 里那一支与 `_in_clear_pump`）。
//
// 又是模拟器发起、机制回答：要判的两件事都住在田地/装置那一层——
//  1. 这一格是田地，且它的【实际】病害值 ≤ 0；
//  2. 或者这一格在某个泵站的**前向射线**上，且那条射线的水源地是一片清水
//     田地（水源地上站着我方单位时还能多推一段）。
//
// `allies` 是本帧所有**活着**的我方单位脚下的格子——第二条里的"水源地上有人"
// 用它。传格子而不是传单位：这一层不该认识我方单位是什么。
//
// ⚠ 不是清水一律返回 false（原版 `cell not in farmland` 就是假）。
// 不要"取最近的水源"之类的近似——那不是原版的判定。
type ClearWaterProbe interface {
	IsClear(cell [2]int, allies [][2]int) bool
}

// Framer 在**每一帧的末尾**被调用（`t += dt` 之前，即这一帧的伤害、击杀、
// 漏怪都已经结算完）。
//
// 位置是定的，理由与主循环的帧内顺序同源：机制看到的是一个**已经结算完的帧**，
// 它自己造成的影响落在下一帧。放在帧中间会让"谁先谁后"变成机制之间的事。
type Framer interface {
	Frame(ctx Ctx, dt float64)
}

// Snapshotter 让机制把自己的状态交给判决，**供对拍逐项比**。
//
// 为什么需要它：判决（胜负/击杀/漏怪/时刻）是**粗指标**——怀黍离的病害值累积得
// 不一样、但这一趟恰好没有干员站在那格上时，判决可以完全相同。那正是这一层最
// 容易藏住偏差的地方（"病害值涨得快一点"），所以机制状态必须能被原版逐项对照。
//
// 返回值必须是**普通 JSON 值**（数字/字符串/数组/映射）：不许把活的运行时对象
// 塞进来。判决本身不读它，只有对拍台读。
type Snapshotter interface {
	State() any
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
	//: 按**单位对象下标**回血（上限是这名干员的最大生命）。
	//: 对应原版 `unit.py:111` 的 `Combatant.heal`——与"负伤害"不是一回事：
	//: 回血不吃任何减伤、也不该触发受击类效果。怀黍离的田地就是它的第一个使用者
	//: （病害值为 0 的田地每秒回 `hp_recovery_per_sec`，`sim.py:1373-1375`）。
	HealOperator(index int, amount float64)
	//: 按**单位对象下标**打一次**分类型**的伤害（原版 `resolve_damage` 那一路）：
	//: `raw` 是"攻击力 × 倍率"（机制自己算），防御/法抗/闪避与保底由主循环按这名
	//: 干员**这一刻**的数值结算——那些数只有主循环有，机制不该自己抄一份。
	//:
	//: 为什么不是复用 `DamageOperator`：那个是**真伤**（田地每秒伤害就不吃减伤）。
	//: 敌方技能出手的两段是物理 + 法术，**各减一次**（`sim.py:3496-3498` 写明了
	//: "不是把两部分加起来当一次伤害打"），通道必须分类型。
	//:
	//: 返回实际掉的血（含受击回技力那一步，与主循环自己出手时同一套）。
	HitOperator(index int, raw float64, damageType string) float64
	//: 按**出怪顺序下标**把这一只敌人的动作停顿至少推到这个时长
	//: （原版 `e.attack_pause = max(e.attack_pause, self.enemy_windup)`：
	//: 出手要占用一段动作时间，这期间它不走路）。
	PauseEnemy(index int, seconds float64)
	//: 这一关的"出手动作时间"（原版 `self.enemy_windup`）。机制需要它，是因为
	//: 它自己发起的出手同样要占住那一小段时间——但这个数住在规格里，不在机制里。
	EnemyWindup() float64
	//: 按**出怪顺序下标**改这一只敌人的推进速度乘区（1.0 = 不变）。
	ScaleEnemySpeed(index int, scale float64)
	//: 按**出怪顺序下标**读/写一只敌人的血量（天桩链用：甲监测时把生命
	//: 重设成所在地块病害值、激活后每秒自伤、乙到时自毁——全是**直接写血**，
	//: 不是"受到伤害"：原版那三处都是 `e.hp = ...`，既不算我方战果、
	//: 也不该触发受击类效果）。
	EnemyHP(index int) float64
	EnemyMaxHP(index int) float64
	SetEnemyHP(index int, hp float64)
	//: 甲/乙/天标的站位。乙"扑向干员"在原版走的是**普通推进**（把路线换成
	//: `[自己, 目标]` 交给主循环），所以真正该用的是 `SetEnemyRoute`；
	//: 这个 setter 只用于"贴到目标"那一步的钉住。
	EnemyPosition(index int) [2]float64
	SetEnemyPosition(index int, position [2]float64)
	//: 这一只**这一刻**的推进速度（已含关卡乘区与机制请求的乘区），
	//: 与主循环 `advance` 用的是同一个数。
	EnemyMoveSpeed(index int) float64
	//: 给这一只**换一条走位路线**（`points` 是折线，至少两点）。
	//:
	//: ⚠ 乙的追击必须走这里，不能让机制自己一步步挪位置——原版是
	//: `e.route = [自己, 目标]` 之后交给普通推进，**走完即算漏怪、要扣生命**。
	//: 自己挪位置就漏掉了"走完算漏怪"这一步。实测 HS-S-1 的胜负正压在这上面：
	//: 原版有 4 个乙自己走到路线尽头 → 漏怪 4 次 → 扣 4 点生命 → 52.5s 就结束，
	//: 而 Go 侧那 4 个乙停在原地、一命没扣，于是拖到 85s（判决全错）。
	SetEnemyRoute(index int, points [][2]float64)
	//: 甲监测状态的无敌。**挨打掉 0 血但照旧会被索敌**——这正是它在场上
	//: 白吃输出的原因（原版 `always_invincible`，激活时关掉）。
	SetEnemyInvincible(index int, on bool)
	//: 在 `cell` 造一个敌人，`template` 是**造它的人**规格里那段 JSON
	//: （见 `Summoner`：甲/乙/天标三跳都走这里）。返回的下标终身有效。
	Summon(template json.RawMessage, cell [2]float64) int
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
	//: 阻挡数。敌方技能出手的"部署于地面"取它（`block_cnt > 0`，
	//: 原版 `_skill_atk_target` 3566-3580 与 `docs/verdicts-pending.md` E16）。
	BlockCnt int
}

// EnemyView 是一只敌人在这一帧的样子（只读）。
type EnemyView struct {
	Index    int //: 出怪顺序（与 `Spec.Spawns` 同序）
	Name     string
	Position [2]float64
	//: 所在格——**由模拟器按与原版同一个口径算好递进来**
	//: （原版 `EnemyUnit.cell()` = `int(round(x))`，半数进到偶数）。
	//:
	//: ⚠ 机制层**不要**自己 `int(Position[0])`：那是**截断**，站在 9.7 格上
	//: 会得到 9 而原版得到 10。这个差别在"按格查表"的地方会静默换一个答案
	//: （怀黍离「污」的"自己是否站在受污染田地"就是栽在这里的：Go 少算/多算
	//: 一整段法术伤害，40 秒后才显形）。
	Cell    [2]int
	HP      float64
	Alive   bool
	Blocked bool
	//: 这一只**已经漏掉**（走到终点扣命）——被击倒类效果不许作用在它身上。
	Leaked bool
	//: 这一只已经离场（原版 `off_map`）。
	OffMap bool

	//: 挡着它的那个我方单位脚下的格（原版 `_pollute_around` 取的就是这个圆心：
	//: 被阻挡时用**挡它的干员**那一格，否则用敌人自己那一格）。
	//: `HasBlocker` 与它同真同假——用两个字段而不是"查 `Blocked`"：
	//: 击倒那一刻 `Blocked` 可能已经因为阻挡者阵亡而被清掉，而原版在
	//: `_on_enemy_death` 里读的是 `e.blocked_by is not None and e.blocked_by.alive`，
	//: 两者**不是同一件事**（`HasBlocker` 只表示"挡它的那个还活着"）。
	HasBlocker  bool
	BlockerCell [2]int

	//: 被击倒时给它圆心周围田地加多少病害（原版 `passive_pollut`），
	//: 以及半径（原版 `passive_radius`，0 表示按 1.0）。
	PollutOnDeath float64
	PollutRadius  float64

	//: 攻击力与普攻间隔——敌方**技能出手**那一路要用
	//: （`e.atk × skill_atk_scale_*`；间隔在 `skill_atk_interval` 为 0 时回落到它）。
	ATK            float64
	AttackInterval float64

	//: 敌方技能出手（怀黍离「玷 / 勿玷」技能「污」）。全 0 表示这一只没有这个技能，
	//: 机制一帧都不多花。字段名与 `sim.py` 里的那一组同名，语义见
	//: `_skill_attack_tick`（3468）与 `gamedata/enemy.py::skill_attack_fields`。
	SkillAtkScalePhys  float64
	SkillAtkScaleMagic float64
	SkillAtkInit       float64
	SkillAtkInterval   float64
	SkillAtkCross      int
	SkillAtkPollut     float64
	SkillAtkGroundOnly bool
}

// ---- 注册表 ----

// Factory 按这一关的**机制规格**造一个机制实例。
//
// 为什么要工厂而不是单例：机制里有相当一部分是**带本关几何与参数的状态机**
// （田地/病害值就是：哪些格是田地、分成哪几片、每片当前的【最大】与【缓存】，
// 全在这一关的地图里）。这类机制每场都得有一份自己的状态，共用一个单例会把
// 上一场的病害值带到下一场——而且**不会报错**，只会让第二场的判决悄悄不同。
//
// `cfg` 是这个机制的规格原文（Python 侧按名字放在同一个键下）。不吃配置的机制
// 拿到 nil 即可；规格解不开要返回错误（拒跑），不许"解不开就当没有"。
type Factory func(cfg json.RawMessage) (Mechanism, error)

var registry = map[ID]Factory{}

// Register 由**无状态**的机制在自己的 `init()` 里调用。
//
// 反复注册或空名字是**编程错误**，直接 panic：这种错在启动时炸出来最好查，
// 拖到运行期会表现成"某一关的判决偶尔不一样"。
func Register(m Mechanism) {
	if m == nil {
		panic("mech: 注册了 nil 机制")
	}
	RegisterFactory(m.ID(), func(json.RawMessage) (Mechanism, error) { return m, nil })
}

// RegisterFactory 由**带本关规格**的机制在自己的 `init()` 里调用。
func RegisterFactory(id ID, f Factory) {
	if id == "" {
		panic("mech: 机制的 ID 不能是空的")
	}
	if f == nil {
		panic(fmt.Sprintf("mech: 机制 %q 的工厂是 nil", id))
	}
	if _, dup := registry[id]; dup {
		panic(fmt.Sprintf("mech: 机制 %q 注册了两次", id))
	}
	registry[id] = f
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
	envs     []hookEnv
	piles    []hookPile
	attacks  []hookAttack
	posts    []hookPost
	drains   []hookDrain
	adds     []hookAdd
	clears   []hookClear
	framers  []hookFramer
	all      []Mechanism
}

type hookPile struct {
	id ID
	m  PileTicker
}

type hookStarter struct {
	id ID
	m  Starter
}

type hookEnv struct {
	id ID
	m  EnvTicker
}

type hookPost struct {
	id ID
	m  PostAttacker
}

type hookDrain struct {
	id ID
	m  PollutionDrainer
}

type hookAdd struct {
	id ID
	m  PollutionAdder
}

// hookClear 是清水探针的挂点（见 `ClearWaterProbe`）。
type hookClear struct {
	id ID
	m  ClearWaterProbe
}

type hookAttack struct {
	id ID
	m  AttackTicker
}

type hookFramer struct {
	id ID
	m  Framer
}

// Load 按名字取机制，`cfg` 是各机制的规格（键 = 机制名）。
//
// 有一个名字取不到就整组失败——见包注释里那条：少挂一个机制与"本来没这机制"
// 分不开，所以不许静默跳过。规格里带了名字却没有对应条目的机制，也在这里拒绝。
func Load(cfg map[string]json.RawMessage, ids ...string) (*Set, error) {
	set := &Set{}
	known := make(map[string]bool, len(ids))
	for _, name := range ids {
		known[name] = true
	}
	for name := range cfg {
		if !known[name] {
			return nil, fmt.Errorf("规格里带了机制 %q 的参数，但它没被点名"+
				"（点名的：%v）——两边对不上时不许猜", name, ids)
		}
	}
	for _, name := range ids {
		id := ID(name)
		f, ok := registry[id]
		if !ok {
			return nil, fmt.Errorf("这一关点名了机制 %q，但本模拟器里没有"+
				"（有的：%v）", name, Available())
		}
		m, err := f(cfg[name])
		if err != nil {
			return nil, fmt.Errorf("机制 %q 的规格用不了：%w", name, err)
		}
		set.ids = append(set.ids, id)
		set.all = append(set.all, m)
		if s, ok := m.(Starter); ok {
			set.starters = append(set.starters, hookStarter{id, s})
		}
		if e, ok := m.(EnvTicker); ok {
			set.envs = append(set.envs, hookEnv{id, e})
		}
		if p, ok := m.(PileTicker); ok {
			set.piles = append(set.piles, hookPile{id, p})
		}
		if p, ok := m.(PostAttacker); ok {
			set.posts = append(set.posts, hookPost{id, p})
		}
		if d, ok := m.(PollutionDrainer); ok {
			set.drains = append(set.drains, hookDrain{id, d})
		}
		if a, ok := m.(PollutionAdder); ok {
			set.adds = append(set.adds, hookAdd{id, a})
		}
		if a, ok := m.(AttackTicker); ok {
			set.attacks = append(set.attacks, hookAttack{id, a})
		}
		if cp, ok := m.(ClearWaterProbe); ok {
			set.clears = append(set.clears, hookClear{id, cp})
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

// States 收集各机制的**状态快照**（只有实现了 `Snapshotter` 的才有），键 = 机制名。
//
// 进判决、供对拍逐项比；判决本身不依赖它（见 `Snapshotter` 的注释）。
func (s *Set) States() map[string]any {
	if s == nil || len(s.all) == 0 {
		return nil
	}
	out := map[string]any{}
	for i, m := range s.all {
		if sn, ok := m.(Snapshotter); ok {
			out[string(s.ids[i])] = sn.State()
		}
	}
	if len(out) == 0 {
		return nil
	}
	return out
}

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

// EnvTick 依次调用各机制的 EnvTick（位置见 `EnvTicker` 的注释）。
func (s *Set) EnvTick(ctx Ctx, dt float64) {
	if s == nil {
		return
	}
	for _, h := range s.envs {
		h.m.EnvTick(ctx, dt)
	}
}

// PileTick 依次调用各机制的 PileTick（位置见 `PileTicker` 的注释：紧跟 EnvTick）。
func (s *Set) PileTick(ctx Ctx, dt float64) {
	if s == nil {
		return
	}
	for _, h := range s.piles {
		h.m.PileTick(ctx, dt)
	}
}

// DrainPollution 依次问各机制"这一格能扣走多少病害值"，取第一个回答 > 0 的。
//
// 由**模拟器**在帧序 3.4（重生结算）里调用，见 `PollutionDrainer` 的注释。
// 没有机制、或这一格没挂田地 → 返回 0，重生期的充能就一层都拿不到（与原版
// "本格病害值 ≤ 0 则一件都不发生"同义）。
func (s *Set) DrainPollution(cell [2]int, want float64) float64 {
	if s == nil || want <= 0 {
		return 0.0
	}
	for _, h := range s.drains {
		if moved := h.m.DrainPollution(cell, want); moved > 0 {
			return moved
		}
	}
	return 0.0
}

// PolluteAround 依次问各机制"往这一格周围加这么多病害，能加多少"，取**第一个
// 有回答的**（与 `DrainPollution` 同一套：同一格不该有两个机制都认领）。
//
// 一个机制都没挂时返回 0——通用关卡里敌人就算带 `phit_pollut` 也没有田地被加，
// 这正是原版的行为（`self.farmland is None` 时 `_pollute_around` 直接返回 0）。
func (s *Set) PolluteAround(cell [2]int, amount float64, radius float64) float64 {
	if s == nil || amount <= 0 {
		return 0.0
	}
	for _, h := range s.adds {
		if got := h.m.PolluteAround(cell, amount, radius); got > 0 {
			return got
		}
	}
	return 0.0
}

// IsClear 依次问各机制"这一格算不算清水"，取**第一个回答算的**。
//
// 一个机制都没挂、或谁都不认领这一格时返回 false——原版里 `farmland is None`
// 就是"不清水"，明识形态因此不拿那一份防御加成。
func (s *Set) IsClear(ctx Ctx, cell [2]int, allies [][2]int) bool {
	if s == nil {
		return false
	}
	for _, h := range s.clears {
		if h.m.IsClear(cell, allies) {
			return true
		}
	}
	return false
}

// AttackTick 依次调用各机制的 AttackTick（位置见 `AttackTicker` 的注释）。
func (s *Set) AttackTick(ctx Ctx, dt float64) {
	if s == nil {
		return
	}
	for _, h := range s.attacks {
		h.m.AttackTick(ctx, dt)
	}
}

// PostAttack 依次调用各机制的 PostAttack（位置见 `PostAttacker` 的注释）。
func (s *Set) PostAttack(ctx Ctx, dt float64) {
	if s == nil {
		return
	}
	for _, h := range s.posts {
		h.m.PostAttack(ctx, dt)
	}
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
