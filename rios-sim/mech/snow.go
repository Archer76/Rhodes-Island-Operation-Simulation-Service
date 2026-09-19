// snow.go：**积雪**（圣聆初雪 `char_1046_sbell2` 天赋「无垠的雪景」）。
//
// 权威实现：`ak_tactic/battle/sim.py::_snow_tick`（1096-1180）、
// `_snow_hit`（1174）、以及状态机 `ak_tactic/battle/talents.py::SnowField`
// （1002-1118）。本文件是它逐条的重写，**每个数都从规格里来**，一个都不自己发明。
//
// ## 为什么它是一层机制，而不是 `OperatorSpec` 上的几个字段
//
// 因为它有**跨帧、跨单位**的状态：一张"格 → 层数"的表、每一格"首个站上去的敌人"
// （离场时要按首敌规则整格清雪）、以及"射程内是否已全满"（那决定要不要扩散）。
// 这与田地同源，照 `huai_shu_li.farmland` 的规矩办。
//
// ⚠ 但与田地有一处关键不同：**田地是开局就有的，雪是干员部署那一刻才建的**
// （`sim.py:3396`）。闸门原来读 `sim.snow_fields`，于是**永远读到空列表**——
// 闸门不报、规格里也没这项，Go 静默跑出另一场战斗。修法在 Python 侧
// （`simgo/spec.py::snow_spec` 改读排程的 `d.talents`）；这里记一笔，是因为
// **下一个"部署时才建"的机制还会踩同一个坑**。
//
// ## 语义清单（逐条对应原版）
//
//  1. **积层**（`SnowField.tick`）：每 `interval` 秒给射程内**可行走格**各加一层，
//     单格上限 `max_cast_cnt`。计时器是**减法**（`self.timer -= dt`，
//     到 ≤0 才施放并回加上一个 `interval`），不是累加到阈值——两者在小 dt 下
//     会漂，而 30fps 正好是"永远除不尽"的那种 dt。
//  2. **扩散**（`_spread_frontier`）：`spread_cap > 0` 时，从**已有雪**的格出发
//     往相邻格各加一层；`spread_cap` 是**这一跳的上限**，每次 tick 重置。
//     顺序由 `neighbours` 的给定顺序决定（Python 侧已排序）——顺序不同，
//     上限先被谁占掉就不同，雪会落在不同的格上。
//  3. **减速**（`slow_at`）：`max(0.05, 1 - slow_per_layer × 层数)`，多片雪相乘。
//  4. **踏入伤害**（`enter`）：**只在层数从 0 变正**的那一次（不是每帧都打），
//     伤害 = `magic_scale × 干员当前攻击力`，走正规法抗结算。
//  5. **满层冻结**：满层的格子上，敌人**既不推进也不出手**；**终点格豁免**。
//  6. **首敌离场整格清雪**（`leave_all`）：死亡/漏怪/离场的敌人踩过的格，
//     若它是该格的"首敌"，整格雪清空（层数与归属一起清）。
//  7. **非可行走格不减速**：原版每帧先 `speed_multiplier = 1.0`，再判
//     "不在可行走格上就 `continue`"——所以离格的那一帧速度即复原。
//
// ## 没有移植的一处（如实记，不要假装完整）
//
// **技能2 期间**：原版把 `spread_cap` 提到 `talent@max_cast_tile_count`、
// 并给雪格上的敌人每秒追加 `talent@s2_magic_scale × atk × dt`
// （`sim.py:1120-1127`、1167-1172）。那两个数住在**技能黑板**上，而 Go 侧的
// `SkillSpec` 目前没有送它们——所以只实现了技能关闭时的形态。
// 现在无影响：作业里圣聆初雪那一手 `skill=0`。**要接技能2 时，
// 先把这两个键加进 `skills.skill_spec` 送过来**，再在这里读。
package mech

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"sort"
	"strconv"
	"strings"
)

// SnowID 是这一层的机制名（Python 与 Go 之间的契约，改名等于改协议）。
const SnowID ID = "snow.field"

// 排障开关：把"施放者不在场所以不积层"这条也打进痕迹（`RIOS_TRACE=1` 才输出）。
//
// 平时是噪声（每帧每片雪一行），但"雪一片都没积起来"这种症状只能靠它定位——
// 那个分支**不产生任何伤害**，判决退回"没有雪"的数值，看起来像机制没接线，
// 实际是"人不在场上"。与 `timer` 方向写反那次是同一类：都是**静默的**。
const debugSnowOwner = true

// 减速乘区痕迹的时间窗口（秒）。默认空窗口 = 不打。
//
// 为什么要窗口：这一条**逐帧每敌一行**，全程是几万行；而它要回答的问题
// 总是"某一小段里两边差在哪一帧"。窗口一收，输出就只剩那几帧。
//
// 改窗口不必改代码：`RIOS_SNOW_DBG=71.9,72.6`（`from,to`，逗号分隔）。
// 排障里"为了看一眼再编一次二进制"是最浪费时间的一步。
var (
	dbgSnowFrom, dbgSnowTo = parseSnowDbgWindow(os.Getenv("RIOS_SNOW_DBG"))
)

func parseSnowDbgWindow(raw string) (float64, float64) {
	lo, hi := 1e18, -1e18
	parts := strings.SplitN(strings.TrimSpace(raw), ",", 2)
	if len(parts) != 2 {
		return lo, hi
	}
	a, err1 := strconv.ParseFloat(strings.TrimSpace(parts[0]), 64)
	b, err2 := strconv.ParseFloat(strings.TrimSpace(parts[1]), 64)
	if err1 != nil || err2 != nil {
		return lo, hi
	}
	return a, b
}

// 只对某一格打"首敌归属"痕迹：`RIOS_SNOW_CELL=9,2`。空 = 不打。
//
// 首敌归属决定"这一格的雪什么时候被清掉"，而它只在某个敌人**第一次**踏入
// 那一格时定下——那一刻往往在几百帧之前。不单独盯住一格，那一刻翻不回来。
// （同一个事实也进判决的 `mech_state`，见 `DebugState`；痕迹是为了看时刻。）
var dbgSnowCellWant = parseSnowCell(os.Getenv("RIOS_SNOW_CELL"))

func parseSnowCell(raw string) [2]int {
	none := [2]int{-1 << 30, -1 << 30}
	parts := strings.SplitN(strings.TrimSpace(raw), ",", 2)
	if len(parts) != 2 {
		return none
	}
	x, e1 := strconv.Atoi(strings.TrimSpace(parts[0]))
	y, e2 := strconv.Atoi(strings.TrimSpace(parts[1]))
	if e1 != nil || e2 != nil {
		return none
	}
	return [2]int{x, y}
}

func dbgSnowCell(cell [2]int) bool { return cell == dbgSnowCellWant }

// SnowFieldSpec 是**一片**雪的参数（对应一个带该天赋的干员）。
type SnowFieldSpec struct {
	Owner  string   `json:"owner"`
	CharID string   `json:"char_id"`
	Cell   [2]int   `json:"cell"`
	Ground [][2]int `json:"ground"`
	//: 施放者在 `Spec.Operators` 里的下标（与 `deploys[].index` 同一个计数器）。
	//: `Start` 会核对它与 `char_id`/`cell` 对得上，见 `OWNER_INDEX_NOTE`。
	Index        int     `json:"operator_index"`
	Interval     float64 `json:"interval"`
	MaxLayers    int     `json:"max_layers"`
	SlowPerLayer float64 `json:"slow_per_layer"`
	MagicScale   float64 `json:"magic_scale"`
}

// SnowSpec 是整层的规格。
type SnowSpec struct {
	//: 这一关"满层即冻结"的开关（原版 `self.snow_freeze`）。false 时只减速不冻。
	Freeze bool            `json:"freeze"`
	Fields []SnowFieldSpec `json:"fields"`
	//: 相邻可行走格：键 = "x,y"，值 = 该格的四邻与四对角里**可行走**的格。
	//: Go 没有地图（见 `wire.go` 文件头），所以这份几何由 Python 算好送来。
	Neighbours map[string][][2]int `json:"neighbours"`
	//: 防守点格（原版 `_is_goal`：`tile_end`）。满层的雪**不冻终点格**。
	GoalCells [][2]int `json:"goal_cells"`
}

// UnmarshalJSON 把 `null` 的 `neighbours` 归一成空映射：Python 侧没有雪格时
// 会送 `null`，而 `range nil-map` 是合法的，这里不必特判——写出来是为了让
// "为什么允许 null"这件事有出处，免得下次有人加个 `if s.Neighbours == nil` 的守卫。

// OWNER_INDEX_NOTE：`SnowFieldSpec.Index` 由 Python 送（`snow_mech_spec` 里
// 与 `spec.deploys[].index` **同一个计数器**产出的那个下标）。
//
// 为什么不在这里按 `(char_id, cell)` 自己找：下标是"规格与干员数组之间的位置
// 关系"，而**两边数组的顺序由 Python 一并决定**（`build_spec` 里
// `sorted(sim.deployments, key=time)` 那一次排序同时产出 `operators` 与
// `deploys`）。让 Go 再按名字找一遍，等于把这个关系实现了两次——两次实现迟早
// 会分家，而分家的症状是"某个干员的雪算在别人头上"，**不会报错**。
//
// 但"信任"必须落在某处：`Snow.Start` 里会**核对**下标指向的那一位就是
// `char_id` + `cell` 都对得上的那个（错位就拒跑）。这样顺序契约一旦被破坏，
// 是**当场拒绝**，不是静默算错。

// SnowField 是**一片雪**在运行期的状态（对应原版 `SnowField`）。
type SnowField struct {
	spec SnowFieldSpec
	//: 格 → 层数（原版 `self.layers`）。**只放层数 > 0 的格**。
	layers map[[2]int]int
	//: 格 → 这一格的**首敌**下标（原版 `self.first_enemy`）。离场/离格时由它
	//: 决定要不要整格清雪。
	//:
	//: ⚠ 与 `lastCell` 是**两张方向相反的表**，缺一不可：`leave_all(enemy_id)`
	//: 问的是"哪些格的首敌是它"（按格查），`enter` 问的是"它上一格在哪"
	//: （按敌人查）。
	firstOn map[[2]int]int
	//: 敌人下标 → 它**上一次所在的格**（原版 `self.last_cell`）。
	//:
	//: ⚠ 这一张表是"踏入只结算一次"的**唯一**依据：踏入伤害判的是
	//: `prev != cell`（原版 `enter` 的 `if prev == cell: return 0.0`）。
	//: 少了它，敌人站在雪格上的**每一帧**都会吃一次踏入伤害——实测就是这样：
	//: Go 侧 207 笔 vs 原版 28 笔，Go 反而比原版多打 8.4 万点伤害，
	//: 最终 35杀/149s 对 18杀/99s。**判决方向是"Go 更强"**，这种偏差
	//: 不会让人怀疑"机制多打了一次"，只会以为"两边的作业强度不同"。
	//:
	//: ⚠ 它**在没有雪的格上也要更新**（原版 1101 行无条件写）："从雪格走进
	//: 非雪格"必须被记下来，否则再走回那片雪时会被判成"没动过"而不吃伤害。
	lastCell map[int][2]int
	//: 本帧的模拟时刻，只给痕迹用。
	//:
	//: ⚠ `leaveAll` 是从两条路被调到的（帧首的"离场摘记账"与被打死那一刻），
	//: 两条路都没有 `ctx`——所以时刻只能由 `Frame` 每帧写进来。
	//: 少了它，`SNOWDROP` 就**没有时刻**，而"这一格什么时候被清的"恰恰是
	//: 唯一要问的问题（本轮就因此把它当成了"什么都没发生"）。
	now float64
	//: 相邻可行走格（原版 `_ground_neighbours` 回调）。**每片各自持一份引用**：
	//: 表住在规格上，片只读它。
	nbrs  map[string][][2]int
	timer float64
	//: 技能期才非 0（见文件头"没有移植的一处"）。
	spreadCap int
	dotScale  float64
}

// Snow 是这一层的全部雪片（一片 = 一个带该天赋的干员）。
type Snow struct {
	spec   SnowSpec
	fields []*SnowField
	goals  map[[2]int]bool
}

func newSnow(cfg json.RawMessage) (Mechanism, error) {
	if len(cfg) == 0 {
		return nil, fmt.Errorf("snow: 点名叫了积雪，但没有规格——" +
			"两边对不上时不许猜（原版建对象在 sim.py:3396，参数得由 Python 送）")
	}
	var spec SnowSpec
	if err := json.Unmarshal(cfg, &spec); err != nil {
		return nil, fmt.Errorf("snow: 规格解不开：%w", err)
	}
	if len(spec.Fields) == 0 {
		return nil, fmt.Errorf("snow: 规格里一片雪都没有")
	}
	s := &Snow{spec: spec, goals: map[[2]int]bool{}}
	for _, g := range spec.GoalCells {
		s.goals[g] = true
	}
	for _, f := range spec.Fields {
		if len(f.Ground) == 0 {
			// 射程内一格可行走都没有 = 这片雪永远不会积起来。原版也会这样
			// （`ground` 为空 → `tick` 什么都不做），所以**不是错误**；
			// 但要拒掉"规格本来就是空的"那种情况（上面那条）。
			continue
		}
		if f.Interval <= 0 {
			return nil, fmt.Errorf("snow: %s 的 interval = %g，不是正数"+
				"（原版 tick 会除零/永远不施放）", f.Owner, f.Interval)
		}
		s.fields = append(s.fields, &SnowField{
			spec:     f,
			layers:   map[[2]int]int{},
			firstOn:  map[[2]int]int{},
			lastCell: map[int][2]int{},
			nbrs:     spec.Neighbours,
			//: `timer` 从 **0** 开始往上攒（原版 `SnowField.timer: float = 0.0`）。
			//: 部署后第一层雪要等满一个 `interval`——E2 的 5.5s 就是实测的那些
			//: 首铺时刻（56.5s = 部署 51.0s + 5.5s）。
			timer: 0,
		})
	}
	return s, nil
}

func (s *Snow) ID() ID { return SnowID }

// Start 核对"下标 ↔ (char_id, cell)"这条隐含契约（见 `OWNER_INDEX_NOTE`）。
//
// 核对不过就**拒跑**：错位的症状是"某个干员的雪算在别人头上"，判决上看不出，
// 只有核对能拦。这一处刻意不写"找不到就跳过"——跳过等于把错位变成静默。
func (s *Snow) Start(ctx Ctx) error {
	ops := ctx.Operators()
	for _, f := range s.fields {
		i := f.spec.Index
		if i < 0 || i >= len(ops) {
			return fmt.Errorf("snow: %s 的施放者下标 %d 越界（干员共 %d 位）",
				f.spec.Owner, i, len(ops))
		}
		if ops[i].CharID != f.spec.CharID || ops[i].Cell != f.spec.Cell {
			return fmt.Errorf("snow: 施放者下标 %d 指向的是 %s@%v，"+
				"但这一片雪属于 %s@%v——规格的顺序契约被破坏了",
				i, ops[i].CharID, ops[i].Cell, f.spec.CharID, f.spec.Cell)
		}
	}
	return nil
}

// SnowTick 是帧序 3.5 的那一次（原版 `_snow_tick`）。
func (s *Snow) SnowTick(ctx Ctx, dt float64) {
	if s == nil || len(s.fields) == 0 {
		ctx.Trace("SNOWTICKT 空：fields=%d（这一层被挂上了但没有雪片）",
			len(s.fields))
		return
	}
	ctx.Trace("SNOWTICKT t=%.4f 片数=%d 敌人=%d interval=%.4f timer=%.4f 格数=%d",
		ctx.Now(), len(s.fields), len(ctx.Enemies()),
		s.fields[0].spec.Interval, s.fields[0].timer, len(s.fields[0].spec.Ground))

	// 干员视图**这一帧只取一次**：施放者的"在不在场"与"这一刻攻击力"两个问题
	// 都从它回答。取一次而不是每片雪各取一次——`Operators()` 每调一次就重建
	// 整个切片，而这里每帧都要问。
	ops := ctx.Operators()
	opAt := func(i int) (OpView, bool) {
		if i < 0 || i >= len(ops) {
			return OpView{}, false
		}
		return ops[i], true
	}
	alive := func(i int) bool {
		v, ok := opAt(i)
		return ok && v.Alive
	}
	// 敌人视图同样**这一帧只取一次**：清雪、减速、冻结、踏入四段都要用它，
	// 而且必须用**同一份**（中途重取会让"这一帧的现场"在四段之间漂）。
	enemies := ctx.Enemies()

	// ---- 已经不在场上的敌人：按"首敌离场"规则清掉它踩过的雪 ----
	//
	// 位置照原版：**在积层之前**（`sim.py:1107-1112`，比 1114 的积层早）。
	// 反过来会让"这一帧刚死的敌人"踩过的格在同帧立刻被重新积一层。
	//
	// 判据是"它**这一刻**还在不在场上"（原版 1108 行的 `live` 集合：
	// `e.alive and not e.leaked and not e.off_map`），而不是"列表里还有没有它"
	// ——死亡与漏怪都不把对象移出列表。
	live := map[int]bool{}
	for _, e := range enemies {
		if e.Alive && !e.Leaked && !e.OffMap {
			live[e.Index] = true
		}
	}
	for _, f := range s.fields {
		f.now = ctx.Now()
		for idx := range f.lastCell {
			if !live[idx] {
				// 内联 `leave_all`：摘掉这一位的记账，并把"它是首敌的那一格"
				// 整格清雪。见 `SnowField.leaveAll` 的注释。
				f.leaveAll(idx)
			}
		}
	}

	// ---- 积层 ----
	for _, f := range s.fields {
		// 技能期的那两个数（见文件头"没有移植的一处"）：Go 侧没有送，
		// 所以恒为 0 —— 也就是"技能关闭"的形态。原版每帧重置这两个值
		// （`sim.py:1121-1122`），所以这里也每帧重置。
		f.spreadCap = 0
		f.dotScale = 0.0
		if !alive(f.spec.Index) {
			// 施放者不在场（未部署 / 已退场）→ 这片雪**不积层**。
			// 原版判的是 `op is None or not op.alive`（`sim.py:1117`）。
			if debugSnowOwner {
				ctx.Trace("SNOWSKIP t=%.4f idx=%d 不在场 alive=%v（这片雪不积层）",
					ctx.Now(), f.spec.Index, ops[f.spec.Index].Alive)
			}
			continue
		}
		f.tick(dt)
	}

	// ---- 敌人：减速、冻结、踏入伤害 ----
	for _, e := range enemies {
		if !e.Alive || e.Leaked || e.OffMap {
			continue
		}
		cell := e.Cell

		// ⚠ 原版每帧**先重置** `frozen`（`sim.py:1139`）：`e.frozen = e.freeze_timer > 0`。
		// 于是"上一帧被雪冻住"不会粘到这一帧——冻结是**逐帧重新判定**的。
		// 少这一句的后果是敌人被冻住就再也解不开（离格了还在冻）。
		ctx.SetEnemyFrozen(e.Index, false)

		// ⚠ `speed_multiplier` 也要**每帧重置成 1.0**（`sim.py:1141/1143`）：
		// 它是"本帧重算"的量，不是"累积衰减"。而且**不在可行走格上就整段跳过**
		// ——所以离开雪格的下一帧速度立刻复原。
		//
		// ⚠ 这一句与下面那句的**位置**与原版不同，是刻意的：原版在
		// `if not m.walkable(*cell): speed = 1.0; continue` 里**整段跳过**，
		// 于是非可行走格上的敌人**不会被满层冻结**（它连 frozen 都不判）。
		// Go 没有"可行走格"这张表（见 `wire.go`），但雪只积在可行走格上，
		// 所以 `layers[cell] == 0` 就是"这一格不在雪里"的等价判据——
		// 下面用 `mult == 1.0 && 没有一片雪覆盖这一格` 复现"整段跳过"。
		mult := 1.0
		frozen := false
		dotTotal := 0.0
		var dotAtk float64
		// 施放者下标 → 它的视图（下面两个循环都要用）。
		//
		// ⚠ **必须在这里就把"施放者已阵亡/已撤退"的雪片滤掉**（`!v.Alive`）。
		// 原版在这两处的判据是同一个：敌人循环开头就是
		// `if op is None or not op.alive: continue`（`sim.py:1146`），
		// 一 `continue` 掉，**减速、冻结、踏入结算三件事一起停**——
		// 雪层还留在 `layers` 里，但没有任何效果，直到有人把它清掉。
		//
		// 少这个 `!v.Alive` 的后果不是"算慢一点"，是**机制在该失效的时候继续生效**：
		// 积层那段用的是 `alive()`（查了 `v.Alive`），于是"不再积新雪"是对的——
		// 两段判据不一致，症状就变成"施放者已经倒下，雪还在冻人"，
		// 而且**判决上只表现为时间偏长**，看不出是机制没停。
		// HS-EX-8 第 3 手实测：原版圣聆初雪 84.3667 阵亡 → 雪立刻失效；
		// Go 漏了这一句，她倒下之后那 8 格雪又冻了十几秒，多出 1.167 秒。
		owner := map[int]OpView{}
		for _, f := range s.fields {
			v, ok := opAt(f.spec.Index)
			if !ok || !v.Alive {
				continue
			}
			owner[f.spec.Index] = v
		}

		// ---- 减速与冻结：**只对"有雪的格"** ----
		//
		// ⚠ 原版在这里的判据是 `if not m.walkable(*cell): speed = 1.0; continue`
		// ——**不可行走格整段跳过**。Go 没有"可行走格"这张表，但雪只积在
		// 可行走格上，所以"这一格有雪吗"与"这一格可行走吗"在**雪已经积起来
		// 之后**是同一个问题。
		//
		// 两者唯一的差别出现在"可行走但还没积起雪"的那段时间：原版**照走
		// `enter`**（层数为 0 → 不结算伤害，但会记 `last_cell`），而按
		// "有雪吗"判会把它整段跳掉。所以下面把**减速/冻结**按有雪判、
		// **踏入结算**按原版的"不可行走才跳"判——两件事分开，不能合并。
		covered := false
		layersHere := 0
		for _, f := range s.fields {
			if _, ok := owner[f.spec.Index]; !ok {
				continue
			}
			if f.layers[cell] > 0 {
				covered = true
			}
			if n := f.layers[cell]; n > layersHere {
				layersHere = n
			}
			if slow := f.slowAt(cell); slow < 1.0 {
				mult *= slow
			}
			if s.spec.Freeze && f.spec.MaxLayers > 0 &&
				f.layers[cell] >= f.spec.MaxLayers && !s.goals[cell] {
				frozen = true
			}
			if f.dotScale > 0 && f.layers[cell] > 0 {
				dotAtk = owner[f.spec.Index].ATK
				dotTotal += f.dotScale * dotAtk * dt
			}
		}
		// ⚠ **无条件上报**，这是本文件里最容易写错的一处。
		//
		// `Ctx.ScaleEnemySpeed` 的语义是"**一直有效，直到改口**"（不是只管一帧）。
		// 原版那边 `speed_multiplier` 是每帧**先重置成 1.0**、再由积雪乘上去的
		// （`sim.py:1143` 起），所以敌人一离开雪格，当帧就恢复全速。
		//
		// 把上报塞进 `if covered` 里（本文件原来的写法）会得到完全相反的语义：
		// **离开雪格那一次减速永远粘住**，那一片雪没了、敌人却一直以 0.64 走。
		// 症状是判决上"杀漏都对、就是慢一点"——HS-EX-8 第 3 手实测多 7.233 秒。
		//
		// 安全性：`mult < 1.0` 蕴含 `covered`（`slowAt` 在层数 ≤ 0 时返回 1.0），
		// 所以无条件上报在"没雪"时上报的**恰好就是 1.0**；而这条通道全仓只有
		// 积雪一个使用者（`grep ScaleEnemySpeed` 只有这里），不会覆盖别人的请求。
		ctx.ScaleEnemySpeed(e.Index, mult)
		if covered {
			//: 定点痕迹：减速乘区**变化即记一笔**（不逐帧打）。
			//: 与原版 `speed_multiplier` 那一列逐帧对比时，靠它指认"是哪一格、
			//: 哪一个时刻"两边开始不一致——判决（杀/漏/用时）只在偏差累积到
			//: 改变胜负时才动，看不出"慢了一帧"这种程度。
			if ctx.Now() >= dbgSnowFrom && ctx.Now() <= dbgSnowTo {
				ctx.Trace("SNOWSLOW t=%.4f idx=%d enemy=%s cell=%v mult=%.6f 层=%d",
					ctx.Now(), e.Index, e.Name, cell, mult, layersHere)
			}
			if frozen {
				ctx.SetEnemyFrozen(e.Index, true)
			}
		}

		// ---- 踏入结算（原版 `sim.py:1144-1172`）----
		//
		// ⚠ **每一片雪都要调**，哪怕这一格没有雪：`enter` 里那两笔记账
		// （`last_cell`）是"同一个敌人同一格只结算一次"的依据，也负责
		// "离开旧格时按首敌规则清雪"。第一次写的时候把这段塞在
		// `if !covered { continue }` 后面，于是**踏入伤害一次都没发生**
		// （Go 判决退回"没有雪"的 17杀/90.167s，而雪明明积着）。
		for _, f := range s.fields {
			v, ok := owner[f.spec.Index]
			if !ok {
				continue
			}
			hit := f.enter(ctx, cell, e, f.spec.MagicScale*v.ATK)
			//: 踏入伤害**必须留痕**：它是这一层最主要的可观测量，而在此之前
			//: 它是**静默**的（`enter` 直接 `return ctx.HitEnemy(...)`，什么也不打）。
			//: 原版那边每次踏入都会往 `result.log` 写一行
			//: `{t}s {owner} 积雪伤害 {hit} → {name}`，两边因此**对不上账**：
			//: 判决只报"总伤害 +1,392.0"，看不出是哪一笔多的。
			//: 有了这条，两边可以**逐笔**比（时刻 / 敌人 / 数值），
			//: 而不是拿一个总数去猜。
			if hit > 0 {
				ctx.Trace("SNOWENTRY t=%.4f enemy=%s idx=%d cell=%v atk=%.4f dmg=%.4f",
					ctx.Now(), e.Name, e.Index, cell, v.ATK, hit)
			}
			// 原版 `if not e.alive: sf.leave_all(key); break`：被打死就
			// **摘掉这一片雪对这个敌人的记账**，并跳出这一只敌人的雪片循环
			// （后面还有 dot 那一段，而它读的是已经被清掉的 `layers`）。
			//
			// ⚠ `break` 跳出的是**雪片**循环，不是敌人循环——原版 `break` 也在
			// 同一个 `for sf in self.snow_fields` 里。搞错这一层会让后面每一只
			// 敌人都不再结算踏入。
			if hit > 0 && !e.Alive {
				f.leaveAll(e.Index)
				break
			}
		}
		if !e.Alive {
			continue
		}
		// 技能2 的每秒伤害（当前恒不触发，见文件头"没有移植的一处"）。
		if dotTotal > 0 {
			ctx.HitEnemy(e.Index, dotTotal, "MAGIC", -1)
		}
	}
}

// tick 是原版 `SnowField.tick`（talents.py:1038）。**逐行照抄，一行都不能想当然**：
//
//	if self.interval <= 0:
//	    return 0
//	self.timer += dt                    ← **往上攒**，不是往下减！
//	added = 0
//	while self.timer >= self.interval:
//	    self.timer -= self.interval
//	    added += self._cast(ground_cells, neighbour_of)
//
// ⚠ 两处踩过的坑，都属于"读原文时想当然"：
//
//  1. **方向**。`timer` 初值 0（`SnowField.timer: float = 0.0`），每帧 `+= dt`
//     往上攒，攒够一个 `interval` 才施放一次、并扣掉一个 `interval`。
//     第一版把它写成"倒计时"（初值 = interval、每帧 `-= dt`），于是
//     `timer >= interval` 只在初值那一刻成立一次、此后**永远为假**——
//     雪一片都没积起来：`timer` 从 5.5 单调降到 −27.87、`cast` 零次调用、
//     判决退回"没有雪"的 17杀/90.167s。Go 侧不报任何错，这才是最坏的一种。
//  2. **`while` 不是 `if`**：一帧里可以施放多次（dt 比 interval 大时）。
//     30fps 下 dt=1/30 远小于 5.5s，现网永远只转一圈——但"现在只转一圈"
//     不是把它写成 `if` 的理由。
//
// 返回值在原版是"这一帧新增层数"（只用于 verbose 日志），Go 侧不记日志，
// 故不返回。
func (f *SnowField) tick(dt float64) {
	if f.spec.Interval <= 0 {
		return
	}
	f.timer += dt
	for f.timer >= f.spec.Interval {
		f.timer -= f.spec.Interval
		f.cast()
		if f.spreadCap > 0 {
			f.spreadFrontier()
		}
	}
}

// DebugState 把这一片的**内部状态**交出来（进判决的 `mech_state`，供对拍逐项比）。
//
// 为什么要它：`layers` 与 `lastCell` 是整层最容易出错、也最难看见的两个量。
// 判决（杀/漏/用时）只在偏差累积到改变胜负时才动，而"雪积到了哪些格、积了几层"
// 是**任何时刻都能直接比**的——实测就是靠它把两个 bug 逼出来的：
// 先是"踏入伤害每帧结算一次"（207 笔 vs 28 笔），后是"减速判据把踏入结算
// 一起跳掉"（判决退回没有雪时的 17杀/90.167s）。
func (f *SnowField) DebugState() map[string]any {
	cells := make([]string, 0, len(f.layers))
	for c, n := range f.layers {
		cells = append(cells, fmt.Sprintf("%d,%d=%d", c[0], c[1], n))
	}
	sort.Strings(cells)
	//: **首敌归属**一并交出来：它是"这一格的雪什么时候被清掉"的唯一依据，
	//: 而它只在某个敌人**第一次**踏入那一格时定下——那一刻往往在几百帧之前，
	//: 靠痕迹翻不回来。判决与层数都看不出它，所以必须进快照。
	owners := make([]string, 0, len(f.firstOn))
	for c, idx := range f.firstOn {
		owners = append(owners, fmt.Sprintf("%d,%d→%d", c[0], c[1], idx))
	}
	sort.Strings(owners)
	return map[string]any{
		"owner":     f.spec.Owner,
		"cells":     cells,
		"owners":    owners,
		"timer":     f.timer,
		"spreadCap": f.spreadCap,
	}
}

// State 让整层进判决的 `mech_state`（见 `DebugState` 的说明）。
func (s *Snow) State() any {
	out := make([]map[string]any, 0, len(s.fields))
	for _, f := range s.fields {
		out = append(out, f.DebugState())
	}
	return map[string]any{"fields": out}
}

// cast 是原版 `SnowField._cast`（talents.py:1050）：先给射程内每一格加层，
// **射程内全满了才**向外扩散。
//
// ⚠ 两处与原版逐字对齐，两处都曾经写错过：
//
//  1. **扩散的条件是"射程内每一格都满层"**（`all(layers.get(c,0) >= max_layers
//     for c in ground_cells)`），不是"射程内全积起了雪"。按后者写，只要
//     8 格各有一层就会往外扩散——雪会铺到原版根本不会铺的格上。
//  2. **扩散的上限在整个 `_cast` 里数一层**（`len(self.layers) >= spread_cap`
//     直接 break），而不是"这一跳加了几格"。前者数的是**总格数**。
//
// 而扩散只在 `spread_cap > 0` 时发生，`spread_cap` 只在**技能开启期间**由
// `_snow_tick` 设上（`sim.py:1121-1126` 读技能黑板的 `talent@max_cast_tile_count`）。
// 所以技能关闭时这两段整段不发生——那是当前作业的情形，但它**不是**"这段可以
// 随便写"的理由：技能一开，两处理解错都会静默地把雪铺错地方。
func (f *SnowField) cast() {
	for _, cell := range f.spec.Ground {
		f.add(cell)
	}
	if f.spreadCap <= 0 {
		return
	}
	allFull := true
	for _, cell := range f.spec.Ground {
		if f.layers[cell] < f.spec.MaxLayers {
			allFull = false
			break
		}
	}
	if !allFull {
		return
	}
	for _, cell := range f.spreadFrontier() {
		// ⚠ `>=` 且看的是**总格数**：到了上限就停止扩散，本轮剩下的格全不加。
		if len(f.layers) >= f.spreadCap {
			break
		}
		f.add(cell)
	}
}

// spreadFrontier 是原版 `SnowField._spread_frontier`（talents.py:1063）：
// **已有雪格**相邻的、还没雪的可走格，按距离由近及远。
//
// 顺序由 `neighbours` 里给的顺序决定（Python 侧已按 `(dx,dy)` 字典序排好）——
// 顺序不同，上限先被谁占掉就不同，雪会落在不同的格上。
//
// 返回值是**候选格列表**，加层由调用方做（与原来的分工一致：`_add` 那边
// 有"总格数到上限就拒加"的保护）。这里**不去重**：原版 `seen` 只用来
// 排除"已有雪的格"，同一格被两个已有雪格同时相邻时会在列表里出现两次，
// 第二次 `_add` 因为层数已 +1 而**照加**（原版就是这样，不是 bug）。
func (f *SnowField) spreadFrontier() [][2]int {
	seen := map[[2]int]bool{}
	for c := range f.layers {
		seen[c] = true
	}
	// 先取快照：扩散过程中 `layers` 会变，而原版遍历的是
	// `list(self.layers)` 的副本。
	cells := make([][2]int, 0, len(f.layers))
	for c := range f.layers {
		cells = append(cells, c)
	}
	out := make([][2]int, 0, len(cells)*2)
	for _, c := range cells {
		for _, n := range f.neighboursOf(c) {
			if seen[n] {
				continue
			}
			seen[n] = true
			out = append(out, n)
		}
	}
	return out
}

// neighboursOf 取这一格的相邻可行走格（规格里带来的表；没有就是空）。
func (f *SnowField) neighboursOf(cell [2]int) [][2]int {
	return f.nbrs[key(cell)]
}

// add 给一格加一层（原版 `SnowField._add`，talents.py:1074）。
//
// 三件事：满层不加；**扩散期**（`spread_cap > 0`）总格数到上限不加；
// 否则层数 +1。
//
// ⚠ 第二条的判据是 `cell not in layers` **且** 总格数已达上限——也就是说
// 上限管的是"**新格**"，已经在表里的格照加不误。按"总格数到上限就一格也不加"
// 写会把射程内的格一起冻住，那是另一回事。
func (f *SnowField) add(cell [2]int) {
	cur := f.layers[cell]
	if cur >= f.spec.MaxLayers {
		return
	}
	if _, existed := f.layers[cell]; !existed &&
		f.spreadCap > 0 && len(f.layers) >= f.spreadCap {
		return
	}
	f.layers[cell] = cur + 1
}

// slowAt 是这一格上的减速乘区（原版 `SnowField.slow_at`）：
// `max(0.05, 1 - slow_per_layer × 层数)`。没有雪 → 1.0。
func (f *SnowField) slowAt(cell [2]int) float64 {
	n := f.layers[cell]
	if n <= 0 {
		return 1.0
	}
	return math.Max(0.05, 1.0-f.spec.SlowPerLayer*float64(n))
}

// enter 是"敌人踏入这一格"的判定与伤害（原版 `SnowField.enter`，talents.py:1093）。
//
// 三件事，**顺序不能换**（原版 1100-1111 逐行）：
//
//	prev = last_cell.get(enemy_id)
//	last_cell[enemy_id] = cell        ← 无条件写，**没有雪的格也要写**
//	if prev == cell: return 0.0       ← 同一格不重复结算（这是"每帧只算一次"的关键）
//	if prev 是 prev 格的首敌: 整格清雪  ← 离格时按首敌规则清掉旧格
//	if layers[cell] <= 0: return 0.0  ← 踏进没雪的格：什么都不发生
//	first_enemy.setdefault(cell, enemy_id)
//	return damage_fn(magic_scale × atk)
//
// ⚠ 第一版漏了 `prev` 那两条，症状是**每一帧都结算一次踏入伤害**：
// Go 207 笔 vs 原版 28 笔、多打 8.4 万点伤害、判决从 18杀/99s 变成 35杀/149s。
// 这类偏差的方向是"Go 更强"，最容易被读成"作业强度不同"而不是"机制算错了"。
func (f *SnowField) enter(ctx Ctx, cell [2]int, e EnemyView, raw float64) float64 {
	prev, had := f.lastCell[e.Index]
	f.lastCell[e.Index] = cell
	if had && prev == cell {
		return 0
	}
	// 离开旧格：如果自己是那格的"第一个敌人"，整格雪消失。
	//
	// ⚠ 判据必须用**双值**形式：原版是 `self.first_enemy.get(prev) == enemy_id`，
	// 键不存在时 `.get` 给 `None`，与任何 `enemy_id` 都不等。Go 若写成
	// `f.firstOn[prev] == e.Index`，**键不存在会给出 0**，于是**下标 0 的敌人
	// 走过任何一格都会把那一格的雪清掉**——一键之差，症状是"莫名其妙少了一片雪"。
	if owner, ok := f.firstOn[prev]; had && ok && owner == e.Index {
		if dbgSnowCell(prev) || os.Getenv("RIOS_SNOW_ALL") != "" {
			ctx.Trace("SNOWCLEAR t=%.4f idx=%d/%s 离开 %v→%v 时清掉整格"+
				"（它是那一格的首敌，原有 %d 层）",
				ctx.Now(), e.Index, e.Name, prev, cell, f.layers[prev])
		}
		delete(f.layers, prev)
		delete(f.firstOn, prev)
	} else if had && prev != cell && (dbgSnowCell(prev) ||
		os.Getenv("RIOS_SNOW_ALL") != "") {
		//: 有雪、但自己**不是**那一格的首敌 → 按原版规则**不清雪**。
		//: 这一支什么都不做，因此看不见；可它正是"雪留得比预期久"的常见解释。
		ctx.Trace("SNOWKEEP t=%.4f idx=%d/%s 离开 %v（层 %d）→ %v："+
			"它不是那一格的首敌（首敌=%d/%t），**不清雪**",
			ctx.Now(), e.Index, e.Name, prev, f.layers[prev], cell, owner, ok)
	}
	if f.layers[cell] <= 0 {
		return 0
	}
	// ⚠ `setdefault` 的语义：**先到的那只占住**，后来的不覆盖。
	if _, ok := f.firstOn[cell]; !ok {
		f.firstOn[cell] = e.Index
	}
	return ctx.HitEnemy(e.Index, raw, "MAGIC", -1)
}

// leaveAll 把一个**离场**（死亡/漏怪/传送离场）的敌人从这一片雪里摘掉
// （原版 `SnowField.leave_all`，talents.py:1113）。
//
// ⚠ 原版判的是"它**上一格**的首敌是不是它"——**不是首敌就不清**：两拨敌人先后
// 走过同一格时，先走的那只离场不能把后来的那只脚下的雪清掉。
func (f *SnowField) leaveAll(index int) {
	prev, had := f.lastCell[index]
	delete(f.lastCell, index)
	if !had {
		return
	}
	//: 离场摘记账：这条**没有对应的可观测量**（它不改层数、不产生伤害），
	//: 但它能整格清雪——所以"雪比预期留得久"时要先看它有没有按预期触发。
	if dbgSnowCell(prev) || os.Getenv("RIOS_SNOW_ALL") != "" {
		owner, ok := f.firstOn[prev]
		Trace("SNOWDROP t=%.4f idx=%d 离场摘记账：上一格=%v，那一格首敌=%d/%t（层=%d）%s",
			f.now, index, prev, owner, ok, f.layers[prev],
			map[bool]string{true: "  ← 整格清雪", false: ""}[ok && owner == index])
	}
	// 同 `enter`：必须双值判，否则下标 0 的敌人离场会清掉不属于它的格。
	if owner, ok := f.firstOn[prev]; ok && owner == index {
		delete(f.layers, prev)
		delete(f.firstOn, prev)
	}
}

func key(c [2]int) string { return fmt.Sprintf("%d,%d", c[0], c[1]) }

func init() { RegisterFactory(SnowID, newSnow) }
