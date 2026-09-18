// wire.go：`sim` 请求的**规格**与应答的**判决**。
//
// 这份结构是 Python 与 Go 之间唯一的契约，设计原则只有一条：
// **数字由 Python 算完送来，Go 只负责把它们推成结果。**
//
// 于是这里读不到数据库、读不到名册、也读不到技能表——一个字段都没有"再去查一下"
// 的余地。练度折算、技能效果解析、寻路，全都在 Python 侧完成（那条链已经有三关
// 基线与 793 项自检钉着）；Go 侧只保留"时间怎么走、谁打到谁、死了没有"。
//
// 规格里 `unsupported` 一旦非空，Go 就**拒跑**（返回错误而不是判决）：这一版是
// 最小版本，只覆盖"常规关卡 + 无手动开技能 + 无装置/召唤/位移/控制"。宁可让
// 对拍台看见一句"这一局还不支持"，也不能让它拿一份缺了机制的结果去和原版对齐
// ——那种"对齐"会把 bug 固化成基线。
package main

// Spec 是一场战斗的完整输入。
type Spec struct {
	Stage    string  `json:"stage"`
	FPS      int     `json:"fps"`
	MaxTime  float64 `json:"max_time"`
	Life     int     `json:"life"`
	CostInit float64 `json:"cost_init"`
	CostMax  float64 `json:"cost_max"`
	//: 每回 1 点费用的秒数（`1 / costRecoverySpeed`，已折算关卡的回复速度乘区）
	CostTime float64 `json:"cost_time"`
	//: 敌人出手后原地停顿的秒数（`enemy_windup`）
	EnemyWindup   float64 `json:"enemy_windup"`
	RangedEnemies bool    `json:"ranged_enemies"`
	//: 位移速度乘区（`speed_scale`，含关卡 `move_multiplier`）
	SpeedScale float64 `json:"speed_scale"`

	Operators []OperatorSpec `json:"operators"`
	Deploys   []DeploySpec   `json:"deploys"`
	Spawns    []SpawnSpec    `json:"spawns"`

	//: 这一局用到了最小版本没覆盖的机制时，Python 侧在这里逐条写明。
	//: 非空即拒跑——见文件头。
	Unsupported []string `json:"unsupported,omitempty"`

	//: 这一局要挂上的**关卡特有机制**（博士 2026-09-18：机制单独成层、按需取用）。
	//: 由 Python 点名——它知道"这一关有哪几样机制"；Go 侧按名字从 `mech` 包里取。
	//:
	//: 取不到 → **拒跑**，不是忽略：少挂一个机制与"这关本来就没这机制"在判决上
	//: 分不开，而对拍台分不开的两种结果早晚会把偏差固化成基线。
	//: 本二进制里有哪些机制，看 `ping` 的 `mechanisms`。
	Mechanisms []string `json:"mechanisms,omitempty"`
}

// OperatorSpec 是一名**已经在场上**的干员的全部数值。
//
// 数值是"无技能状态下"的定值：技能激活在最小版本里不支持（`unsupported` 会挡住），
// 被动技能与常驻天赋/光环的影响**已经折进这些数字**（`atk` 就是
// `OperatorUnit.current_atk()` 在无技能帧的值），所以 Go 这边不需要任何再计算。
type OperatorSpec struct {
	CharID string `json:"char_id"`
	Name   string `json:"name"`
	Cell   [2]int `json:"cell"`

	MaxHP          float64 `json:"max_hp"`
	ATK            float64 `json:"atk"`
	DEF            float64 `json:"def"`
	RES            float64 `json:"res"`
	AttackInterval float64 `json:"interval"`
	DamageType     string  `json:"damage_type"`
	BlockCnt       int     `json:"block_cnt"`
	DeployCost     int     `json:"deploy_cost"`
	RedeployTime   float64 `json:"redeploy_time"`

	//: 攻击范围（**绝对格**，已按落点与朝向展开；技能改范围在最小版本里不支持）
	Range [][2]int `json:"range"`
}

// DeploySpec 是一次排定的部署。
//
// `Index` 指向 `operators[]` 里的**那一个单位对象**——同一个干员再部署时是**另一个
// 对象**（原版里每条 `Deployment` 自带一个 `OperatorUnit`；共用对象会让"撤退后
// 重放"的血量与冷却都算错）。**能不能落下由 Go 在那一刻判**（费用与再部署冷却），
// 判不过就照着原版的做法记一笔并不放——两边都得判，否则"排了但没落地"这一路会
// 悄悄分成两种结果。
type DeploySpec struct {
	Time   float64 `json:"time"`
	Index  int     `json:"index"`
	CharID string  `json:"char_id"`
	Cost   int     `json:"cost"`
}

// LegSpec 是路线的一段：走段（`walk`）、等待段（`wait`）或离场段（`vanish`）。
//
// 路线的分段计划由 Python 侧算好（`eta.route_plans` 那套），Go 只按段推进。
// 这样做的代价是规格里要带一份折线，换来的是**寻路不会成为第二个实现**。
type LegSpec struct {
	Kind    string       `json:"kind"`
	Points  [][2]float64 `json:"points,omitempty"`
	Length  float64      `json:"length,omitempty"`
	Seconds float64      `json:"seconds,omitempty"`
}

// SpawnSpec 是一个**已经建好**的敌人实例（数值、路线、机制标记都在这里）。
//
// 注意用的是 `sim._spawn()` 建出来的那份对象里的字段，不是重新按 id 查一遍：
// 「按 id 再查一次」就等于在 Go 侧重写一遍 `_build_enemy`，而它里面有关卡乘区、
// 难度档位、召唤体默认档这些东西——多一处就会漂。
type SpawnSpec struct {
	Time    float64 `json:"time"`
	Name    string  `json:"name"`
	EnemyID string  `json:"enemy_id"`
	Level   int     `json:"level"`

	HP         float64 `json:"hp"`
	ATK        float64 `json:"atk"`
	DEF        float64 `json:"def"`
	RES        float64 `json:"res"`
	MoveSpeed  float64 `json:"move_speed"`
	Interval   float64 `json:"interval"`
	DamageType string  `json:"damage_type"`

	AttackRange float64 `json:"attack_range"`
	ApplyWay    string  `json:"apply_way"`
	AttackTimes int     `json:"attack_times"`

	IsFlying    bool `json:"is_flying"`
	Unblockable bool `json:"unblockable"`
	TauntLevel  int  `json:"taunt_level"`
	LifeCost    int  `json:"life_cost"`
	KillCost    int  `json:"kill_cost"`
	CannotClear bool `json:"cannot_clear"`

	Legs []LegSpec `json:"legs"`
}

// Verdict 是一场战斗的结果。字段名与 `BattleResult` 对齐，便于逐项对拍。
type Verdict struct {
	Won            bool    `json:"won"`
	Elapsed        float64 `json:"elapsed"`
	Life           int     `json:"life"`
	Kills          int     `json:"kills"`
	Leaks          int     `json:"leaks"`
	Deployed       int     `json:"deployed"`
	OperatorDeaths int     `json:"operator_deaths"`
	DamageDealt    float64 `json:"damage_dealt"`
	SpawnsPlaced   int     `json:"spawns_placed"`
	SpawnsTotal    int     `json:"spawns_total"`
	TimedOut       bool    `json:"timed_out"`

	//: 漏怪的逐笔明细 `(时刻, 名字, 扣命)`——与 `BattleResult.leak_events` 同形
	LeakEvents [][3]any `json:"leak_events"`
	//: 拒收明细 `(时刻, 名字, 原因)`，与 `BattleResult.deploy_rejected` 同形
	DeployRejected [][3]any `json:"deploy_rejected"`
	//: 费用不足明细 `(时刻, 名字, 需要, 当时)`，与 `cost_denied` 同形
	CostDenied [][4]any `json:"cost_denied"`

	//: 时间线（时刻, 事件, 名字）——对拍"哪一帧开始不一样"就靠它。
	//: 只记四类：部署 / 出现 / 击杀 / 漏怪。
	Events []Event `json:"events"`
	//: 这一场跑了多少毫秒（性能对照用）
	SimMS float64 `json:"sim_ms"`
}

// Event 是时间线上的一笔。
type Event struct {
	T    float64 `json:"t"`
	Kind string  `json:"kind"`
	Who  string  `json:"who"`
}
