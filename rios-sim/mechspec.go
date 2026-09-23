// mechspec.go：丙阶段四·第二十九批 —— `mechanisms` 与 `mech_config` 两个顶层键。
//
// ## 这两个键是什么
//
// 它们是 `build_spec`（`simgo/spec.py:1220-1229`）里的**机制层入口**：Go 侧跑不跑
// 田地／积雪，全靠这两个键。之前它们整份由 Python 送来，这个文件开始由 Go 自己造。
//
//	mechanisms  = list(dict.fromkeys([*mech.names_for(inp), *传入的 mechanisms]))
//	mech_config = {FARMLAND_ID: farmland_spec(inp)}            ← 这一批
//	              {SNOW_ID:     snow_mech_spec(inp, …)}        ← 未搬（见 unported）
//
// ## 口径：这一版**不吃计划**
//
// `names_for` 只有两条判据（`simgo/mech.py:66-80`）：
//
//	① 这一关有没有田地   ← 纯关卡（环境 rune ＋ 四个参数齐备）
//	② 雪在不在排程里     ← 要**计划**（`snow_spec` 读 `d.talents` 的「无垠的雪景」）
//
// 本命令只吃 level/path ＋ difficulty ⇒ 第 ② 条恒为「没有」。这不是漏掉，是口径：
// `mechanisms` 与 `mech_config` 在这个口径下**逐字段可比**（判据按同一口径取期望值），
// 而「雪」那一支具名列在 `unported` 里并**计数**。
//
// ⚠ 因为口径是一份**契约**，`spec` 里出现不认识的键一律**具名失败**，不静默忽略：
// 传了 `plan` 却拿到一份没有雪、也没有装置的规格，是这条链上最贵的一种错。
//
// ## 复用了什么（不许出现第二份）
//
//	・田地连通域：`mech.ConnectedGroups`（`mech/huai_shu_li.go` 的同一个实现，
//	  本批把它导出；理由见那里的注释——两份连通域必然有一天不一致）
//	・rune 取值：`findRune` / `bbNumber` / `maskApplies`（`stageenv.go`，与
//	  `frontend/blackboard.py` 逐字同口径）
//	・`mech.FarmlandID` / `mech.SnowID`：机制名的唯一来源
//
// ## 两处必须照抄的历史坑
//
//	① `_seed()` 的歧义（`environment.py:369-393`）：`init_pollut_value` 是
//	   「那一格的初值」还是「整片田地的初值」？本实现照原版取**逐格**，
//	   理由也照抄：数据格式本身就是「单点 + 值」，且 `act31side_ex03` 给了
//	   **两个**点而它们落在**同一片**田地里——整片播种的话第二个点是冗余的。
//	   ★ **这个理由不是定论**，原版自陈「待实机校正」。逐格与整片在开场那一秒
//	   差别很大：有单位的格子里，逐格给 `basic_damage`（20）、整片给
//	   `basic_damage + 100×damage_ratio`（320）。**不要把 20 当成算出来的数。**
//	② 断田（`sim.py:538-543`）：预置阻流阀走装置技能 2（无持续时间）⇒
//	   **开场即在位**，它们的格子从第 0 秒起就不算田地；且这一步在 `_seed` **之后**，
//	   所以 sever 重算分组时用的是**已经播过种**的 `actual`。
package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strconv"
	"strings"

	"rios-sim/mech"
)

// ---------------------------------------------------------------- 常量
//
// 三个装置键照 `frontend/mech_consts.py` 抄（那里是唯一来源，`battle/devices.py`
// 与 `battle/sim.py` 都从它转出）。⚠ 搬常量先读原文件：本项目有过一次
// 「同名不同义的两张表被合并、dict.get 静默落默认值」的教训。
const (
	mechBlockerKey = "trap_139_dhtl" //: 阻流阀：建成后自身地块不再算田地
	mechPumpKey    = "trap_140_dhsb" //: 泵站：每秒在身后格与前方格之间搬病害
	mechPileKey    = "trap_146_dhdcr" //: 天桩：召唤链的起点
)

// 天桩召唤链的三个数，逐条照 `frontend/mech_consts.py` 抄（原文是
// `PILE_SUMMON_DELAY` / `PILE_POLLUT_FULL` / `PILE_SELF_BIND`）。
//
// ⚠ **不许在 Go 里二次推导、也不许给它们兜默认值**：这三个数是「原文里的数字」，
// 甲什么时候召唤乙、病害值到多少算满、乙登场自缚几秒，全靠它们。
// 权威那边曾经写成 `getattr(_sim_mod, "PILE_SUMMON_DELAY", 1.25)`，
// 而那个默认值**恰好等于真值** ⇒ 「取不到」永远看不出来（已改成直取）。
const (
	mechPileSummonDelay = 1.25  //: PILE_SUMMON_DELAY：甲监测满 ⇒ 隔多久召乙
	mechPilePollutFull  = 100.0 //: PILE_POLLUT_FULL：病害值满值（甲监测的分母）
	mechPileSelfBind    = 1.0   //: PILE_SELF_BIND：乙登场自缚秒数
)

// 田地/病害常数，逐条照 `frontend/environment.py:80-102` 抄。
const (
	mechPollutMin      = 0.0
	mechPollutMax      = 100.0
	mechCacheInterval  = 0.2
	mechCachePerTick   = 1.0
	mechActualInterval = 1.0
	mechActualDivisor  = 25.0
	mechActualBaseStep = 1.0
	mechPumpRate       = 1.0
	mechPumpRange      = 1
	mechPumpRangeBonus = 2
)

//: **不是田地**的地块（`environment.py:76-79`）。原文口径是「地形标记为**默认**的
//: 地面地块（传送门出入口／地穴除外）」——不是「高度为低地的全体」。
//: ⚠ 原版自陈「本条待实机校正」，前两版口径都作废过。照搬。
var mechFarmlandExcluded = map[string]bool{
	"tile_telin": true, "tile_telout": true, "tile_hole": true,
}

// ---------------------------------------------------------------- 输入 / 输出

// MechQuery 是 `mechspec` 命令的 spec 体。
type MechQuery struct {
	Difficulty string `json:"difficulty,omitempty"`
	//: ★★ **可选的排程输入**（2026-09-23，第三十九批）：`buildspec` 传、`mechspec`
	//: **不传**（结构取「甲」：机制名的判据仍然只有这一处）。
	//: 带排程才谈得上雪——`snow_spec` 按「谁在哪一手铺雪」判，而那在计划里。
	//:
	//: 为什么不给 `mechspec` 也加一个 `plan`：那条命令的**不吃计划**是一条
	//: **口径契约**（有判据：传了 plan 必须具名失败）。所以两条命令从这个字段起
	//: **故意不同口径**：`mechspec` 的 `unported` 一直列着雪（它确实做不到），
	//: 而 `buildspec` 带上排程、真的做得到时**不再列**。
	//: ⇒ 两边 `unported` 从此**不相等**，那不是漂移，是口径。
	Schedule *MechSchedule `json:"-"`
}

// MechSchedule 是造雪要的那点输入：**已按落地时刻排序**的部署行 ＋ 冻结开关。
type MechSchedule struct {
	Rows   []DeployRow
	Freeze bool
}

// MechOut 是应答体。`Mechanisms` / `MechConfig` 就是 `build_spec` 的同名两键
// （键名相同是**协议**：判据与将来的装配点都按它们取）。
type MechOut struct {
	Mechanisms []string                   `json:"mechanisms"`
	MechConfig map[string]json.RawMessage `json:"mech_config"`
	//: 这一版**造不出来**的部分，具名列出（不静默省略）。
	Unported []string `json:"unported"`
	//: 行使计数：每条线**被喂进去多少输入**。全 0 的那条线不是「通过」，
	//: 是「这一趟没走到它」——判据据此判断覆盖。
	Scanned map[string]int `json:"scanned"`
	//: 口径回显（哪一关、哪一档难度、按什么口径问的）。
	Params map[string]any `json:"params"`
}

//: 未搬的一条线。与判据脚本的 `UNPORTED` 同源，两边不一致时判据会红。
//: ⚠ `farmland.devices[].child` **已搬进 Go**（2026-09-23，第三十八批）。
//: ⚠ 雪这一条**按口径分叉**（第三十九批）：`mechspec` 不传排程 ⇒ **一直列着**；
//: `buildspec` 传了排程且真造出雪 ⇒ `addSnow` 把它从这份清单里**摘掉**。
var mechUnportedLines = []string{
	//: 雪：`snow_mech_spec` 要 `snow_spec` → `d.talents` 的「无垠的雪景」
	//: （`frontend/talent_finders.find_snow`），而且它按**排程**判——
	//: 本命令不吃计划 ⇒ 这一支在**本口径下恒不可达**（判据每次现算并断言为 0）。
	//: ★ 但 `buildspec` 那条路上**不恒空**，见 `snowspec.go` 与 `addSnow`。
	snowUnportedLine,
}

//: 未搬线里雪那一条的**名字**（摘它/认它都只在这一个常量上，免得两处写字符串）。
const snowUnportedLine = "snow.field"

// ---------------------------------------------------------------- 田地规格（生产者侧）
//
// ⚠ **不复用 `mech.FarmlandSpec`**：那是**消费者**，它的 `severed` 带 `json:"-"`
// （自定义 `UnmarshalJSON` 里才接），拿它序列化会**少一个键**。
// 两边的键名必须与 `simgo/mech.py::farmland_spec` 一一对应（19 个键）。
type mechPollutParams struct {
	BasicDamage      float64 `json:"basic_damage"`
	DamageRatio      float64 `json:"damage_ratio"`
	FirstBasicDamage float64 `json:"first_basic_damage"`
	FirstDamageRatio float64 `json:"first_damage_ratio"`
	HPRecoveryPerSec float64 `json:"hp_recovery_per_sec"`
}

type mechGroupOut struct {
	Cells   [][2]int `json:"cells"`
	Maximum float64  `json:"maximum"`
	Cache   float64  `json:"cache"`
}

type mechDeviceOut struct {
	Kind      string   `json:"kind"`
	Key       string   `json:"key"`
	Cell      [2]int   `json:"cell"`
	Direction string   `json:"direction"`
	//: 天桩的召唤链模板。**本版恒不填**（见 `mechUnportedLines`），故 `omitempty`
	//: 会把它整个省掉——判据据此把「缺 child」与「child 是空对象」分开。
	Child json.RawMessage `json:"child,omitempty"`
}

type mechFarmlandOut struct {
	Kind       string           `json:"kind"`
	Width      int              `json:"width"`
	Height     int              `json:"height"`
	Difficulty string           `json:"difficulty"`
	Params     mechPollutParams `json:"params"`

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

	Groups  []mechGroupOut  `json:"groups"`
	Actual  [][3]float64    `json:"actual"`
	Severed [][2]int        `json:"severed"`
	Devices []mechDeviceOut `json:"devices"`
}

// ---------------------------------------------------------------- 田地系统（生产侧）
//
// 只实现 `farmland_spec` 会读到的那些：三个量（每组 maximum/cache、每格 actual）、
// 分组、断田。**不实现 tick** —— 那是机制层运行期（`rios-sim/mech/`）的事。

type mechField struct {
	cells   map[mech.Cell]bool
	maximum float64
	cache   float64
}

type mechFarmland struct {
	fields  []*mechField
	index   map[mech.Cell]*mechField
	actual  map[mech.Cell]float64
	severed map[mech.Cell]bool
}

func (fs *mechFarmland) rebuildIndex() {
	fs.index = map[mech.Cell]*mechField{}
	for _, f := range fs.fields {
		for c := range f.cells {
			fs.index[c] = f
		}
	}
}

// sever 复刻 `environment.py:503-539`（阻流阀把自身地块从田地里摘掉）。
//
// ⚠ 两处语义不能漏：
//   - 摘掉之后**重算连通域**，各新组取「当前最高的【实际】」作为新的【最大】
//     ——这正是 `actual` 必须**按格**存的原因；
//   - 切分时**缓存一律归零**（建成那一刻原文就说「实际病害值/缓存病害值变为0」，
//     而建成要么在开场、要么在部署后 3 秒内，那时必然还没有污染）。
func (fs *mechFarmland) sever(c mech.Cell) {
	old, ok := fs.index[c]
	if !ok {
		return
	}
	delete(fs.actual, c)
	fs.severed[c] = true
	rest := map[mech.Cell]bool{}
	for k := range old.cells {
		if k != c {
			rest[k] = true
		}
	}
	groups := mech.ConnectedGroups(rest)
	if len(groups) == 0 {
		kept := make([]*mechField, 0, len(fs.fields))
		for _, f := range fs.fields {
			if f != old {
				kept = append(kept, f)
			}
		}
		fs.fields = kept
		fs.rebuildIndex()
		return
	}
	kept := make([]*mechField, 0, len(fs.fields)+len(groups))
	for _, f := range fs.fields {
		if f != old {
			kept = append(kept, f)
		}
	}
	for _, g := range groups {
		peak := 0.0
		for k := range g {
			if v, ok := fs.actual[k]; ok && v > peak {
				peak = v
			}
		}
		kept = append(kept, &mechField{cells: g, maximum: peak, cache: 0.0})
	}
	fs.fields = kept
	fs.rebuildIndex()
}

// ---------------------------------------------------------------- 天桩召唤链
//
// 复刻 `mech.py:244 _pile_device_spec`：**装置 → 甲 → 乙 → 天标**四跳。
// 四跳里三跳是「谁造谁」，全在结构化字段里、**不在正文里猜**：
//
//	装置 → 甲：装置 predefine 的 `overrideSkillBlackboard[branch_id]`
//	           → 关卡 `branches[branch].actions[].enemyKey`（`pileChildKeyOf`）
//	甲 → 乙  ：甲自己的 `awake_enemy_key`（读它的天赋黑板）
//	乙 → 天标：`pileMarkKey`（与出怪表那条路**同一个函数**，全链唯一还要查表的一跳）
//
// 三名单位都走 `spawnCtx.unitSpec`（＝`_unit_spec`，与出怪表**同一个口径**），
// 所以这里不新写任何一份单位规格的拼装。
//
// ⚠ **两处必须写死，不能指望从对象上读**：原版是在 `_pile_tick` **运行期**写上的，
// 而规格是**开战前的快照**，此刻对象上还是默认值。
//
//   · 甲的 `unblockable = true`（不可阻挡是它的**常驻天赋**，与监测态无关）。
//     漏了它的后果不是「甲能被挡」这么轻：甲一旦进了 `op.blocking`，
//     索敌的**第一段规则**（先打自己挡住的）就会把主目标判给它 ——
//     `hsex07` 实测 杀 −1／用时 −1.0s。权威在那条注释里自陈踩过一次。
//   · 甲的 `invincible = awake_value > 0`（监测态无敌，原版 `child.monitor`）。

// pileChildFallback 是 `PILE_CHILD`（`enemy_rules.py:46-48`）：装置 key → 甲的 key。
//
// **退路**——正常走上面那条结构化查询；只有整条支线都查不到时才用它
// （权威：`if device.key not in PILE_CHILD: return ("", None)`，即宁可不召唤）。
var pileChildFallback = map[string]string{
	"trap_146_dhdcr": "enemy_1398_dhdcr",
}

// branchPrefixOf 复刻 `gamedata/stage.py:574 branch_prefix`：装置 key 的**末段**
// 就是支线名去掉 `branch_` 之后那部分（`trap_146_dhdcr` → `branch_dhdcr`）。
//
// ⚠ 空串的含义是「**这个装置没有支线语义**」，不是「取不到」：阻流阀
// （`trap_139_dhtl`）与泵站（`trap_140_dhsb`）就靠它挡在门外——不挡的话
// 它们会误领一条天桩的支线（权威实测：`act31side_08` 的 26 个装置各召一名甲）。
func branchPrefixOf(deviceKey string) string {
	i := strings.LastIndex(deviceKey, "_")
	if i < 0 {
		return ""
	}
	tail := deviceKey[i+1:]
	if tail == "" || tail == deviceKey {
		return ""
	}
	return "branch_" + tail
}

// branchFor 复刻 `Stage.branch_for`（`stage.py:654`）：把装置的 `branch_id`
// 解析成**本关真实存在**的支线名。判据按可靠性从高到低：
//
//  1. 装置自己写了 `branch_id` 且本关有这条支线 → 直接用它（本活动 8 个带天桩的
//     关卡全走这条）；
//  2. 没写 → 先试 `{prefix}_1`（技能默认黑板 `sktok_dhdcr` 写的正是它）；
//  3. 还找不到 → 本关**只有一条**以该前缀开头的支线时用它（`act31side_ex08`）；
//  4. 都不成立 → 空串：**宁可不召唤，也不猜错一条路**。
//
// ⚠ 第 2、3 条是**推断**，已登记在 `docs/verdicts-pending.md`。
func branchFor(branches map[string][]BranchAction, branchID, prefix string) string {
	if branchID != "" {
		if _, ok := branches[branchID]; ok {
			return branchID
		}
	}
	if prefix == "" {
		return ""
	}
	if _, ok := branches[prefix+"_1"]; ok {
		return prefix + "_1"
	}
	hits := make([]string, 0, 2)
	for b := range branches {
		if b == prefix || strings.HasPrefix(b, prefix+"_") {
			hits = append(hits, b)
		}
	}
	if len(hits) == 1 {
		return hits[0]
	}
	return ""
}

// pileChildKeyOf 复刻 `enemy_rules.py:96 pile_spec`：装置 → **它召唤的那名甲**。
//
// 返回 (甲的 key, 走的是哪条路)。第二条只是**取证口径**（结构化／退路／没有），
// 它不进规格：权威那边 `_pile_spec` 同时返回一条 `extraRoutes` 路径，但那**不是
// 甲的行进计划**——甲的天赋第一句就是「自缚」，那条路径只作留档
// （全活动 32 个天桩逐关核过：每个装置格都等于它那条路径的起点格）。
func pileChildKeyOf(st *Stage, deviceKey, branchID string) (string, string) {
	branch := branchFor(st.Branches, branchID, branchPrefixOf(deviceKey))
	for _, act := range st.Branches[branch] {
		if act.EnemyKey == "" {
			continue
		}
		return act.EnemyKey, "structured"
	}
	if k, ok := pileChildFallback[deviceKey]; ok {
		return k, "fallback"
	}
	return "", "none"
}

// pileChain 造一条天桩召唤链。取数口径与 `SpawnsOf` **逐字相同**
// （`statsFor`：先取数、后过难度乘数），因为两名单位必须是**同一种口径**下的
// 同一只敌人——两边各算一遍必然有一天走散。
type pileChain struct {
	ctx  *spawnCtx
	defs []localEnemyDef
}

func newPileChain(st *Stage, raw map[string]json.RawMessage, difficulty string,
	covered map[string]int) (*pileChain, error) {
	defs, err := parseLocalEnemyDefs(raw)
	if err != nil {
		return nil, err
	}
	lib, err := LoadEnemyLibrary()
	if err != nil {
		return nil, err
	}
	defs2 := st.Difficulty
	if defs2 == "" {
		defs2 = "NORMAL"
	}
	muls := ParseRuneMuls(st.Runes, defs2)
	cnt := &spawnCounter{Covered: covered, Scanned: map[string]int{}}
	return &pileChain{
		defs: defs,
		ctx: &spawnCtx{st: st, defs: defs, lib: lib, locals: localEnemies(defs),
			muls: muls, p3rArmed: false, cnt: cnt, pathCache: map[string][][2]int{}},
	}, nil
}

// specAt 造一名单位在**某一格**上的规格（`_view` ＋ `_unit_spec` 那一对）。
// `route` 只给一个点：甲自缚、乙与天标都是原地出现，权威三处实参都这么传。
//
// ⚠ 三个返回值都要：**规格**进输出，而 `awake_*` 那几个在 `EnemyStats` 上、
// `attach_damage` 只在 `enemyView` 上（它不在 `_unit_spec` 的输出里，
// 只进天标那一份规格）——少拿一个就得回去重造一遍。
func (c *pileChain) specAt(key string, cell [2]float64) (map[string]any, *enemyView, *EnemyStats, error) {
	level := summonLevel(c.defs, key)
	es, err := c.ctx.statsFor(key, level)
	if err != nil {
		return nil, nil, nil, err
	}
	route := [][2]float64{cell}
	v := viewOf(es, key, level, nil, route, c.ctx.lib, c.ctx.p3rArmed)
	spec, err := c.ctx.unitSpec(v, 0.0, 0)
	if err != nil {
		return nil, nil, nil, err
	}
	return spec, v, es, nil
}

// chainOf 复刻 `_pile_device_spec` 的组装那一段（权威同一个键序、同一个层级）。
//
// 返回 nil 表示**这一只天桩没有模板**——权威在那里是 `return None`（`try/except`
// 包着整段），于是规格里没有 `child` 键。**照抄，但计数**：静默少一个键不会有
// 任何判据报警，所以调用方必须把「建不出来」与「建得出来」分开记。
func (c *pileChain) chainOf(st *Stage, d mechDevice, covered map[string]int) map[string]any {
	key, how := pileChildKeyOf(st, d.key, d.branchID)
	covered["pile_child_"+how]++
	if key == "" {
		return nil
	}
	cell := [2]float64{float64(d.cell[0]), float64(d.cell[1])}
	pspec, _, pes, err := c.specAt(key, cell)
	if err != nil {
		covered["pile_parent_failed"]++
		return nil
	}
	pspec["static"] = true
	pspec["unblockable"] = true // 常驻天赋：**必须写死**，见上面那段注释
	awake := pes.AwakeValue
	pspec["invincible"] = awake > 0
	pspec["awake_value"] = awake
	pspec["awake_hp_ratio"] = pes.AwakeHPRatio
	pspec["awake_summon_ratio"] = pes.AwakeSummonRatio
	pspec["awake_summon_cnt"] = pes.AwakeSummonCnt
	pspec["awake_enemy_key"] = pes.AwakeEnemyKey
	pspec["summon_delay"] = mechPileSummonDelay
	pspec["pollut_full"] = mechPilePollutFull

	diverKey := pes.AwakeEnemyKey
	if diverKey == "" {
		return pspec
	}
	dspec, _, _, err := c.specAt(diverKey, cell)
	if err != nil {
		covered["pile_diver_failed"]++
		return pspec
	}
	dspec["static"] = false // 乙会扑向干员，不是自缚
	dspec["self_bind"] = mechPileSelfBind
	dspec["hit_radius"] = 0.5 //: 原版「贴到目标格」的判据
	mk := pileMarkKey(c.defs, diverKey)
	covered["pile_diver"]++
	if mk != "" {
		if mspec, mv, _, err := c.specAt(mk, cell); err == nil {
			mspec["static"] = true
			mspec["unblockable"] = true
			//: ⚠ `attach_damage` **不在** `_unit_spec` 的输出里，只进天标这一份规格
			//: （`enemyView.AttachDamage`）——照 `markSpec` 那处的口径。
			mspec["attach_damage"] = mv.AttachDamage
			mspec["attach_radius"] = 0.3
			dspec["mark"] = mspec
			covered["pile_mark"]++
		} else {
			//: 权威这里也是 `if mark is not None`——取不到就**没有 mark 键**，
			//: 不算整条链失败。计数，不静默。
			covered["pile_mark_failed"]++
		}
	}
	pspec["summon"] = dspec
	return pspec
}

// ---------------------------------------------------------------- 装置
//
// 复刻 `frontend/devices.py:201-233` 的 `parse_devices`：唯一来源是
// `stage.raw["predefines"]["tokenInsts"]`（**不要**退到 `characterInsts`，
// 那里是预置的**干员**，混进来会凭空多出几个装置）。
type mechDevice struct {
	key       string
	cell      mech.Cell
	direction string
	//: 装置 predefine 的 `overrideSkillBlackboard` 里那一项 `branch_id`
	//: （`devices.py:186 branch_id_of`）：它是「这只装置属于哪条支线」的唯一来源，
	//: 天桩靠它找到自己召唤的甲。取不到就是空串——**空串是「没写」**，
	//: 由 `branchFor` 的第 2/3 条推断接手，不是「读失败」。
	branchID string
}

// branchIDOf 复刻 `frontend/devices.py:186 branch_id_of`：从装置 predefine 里取
// `branch_id`（`overrideSkillBlackboard` 的一项，值是 `valueStr`）。
func branchIDOf(kb []struct {
	Key      string `json:"key"`
	ValueStr string `json:"valueStr"`
}) string {
	for _, it := range kb {
		if it.Key == "branch_id" {
			return it.ValueStr
		}
	}
	return ""
}

func parseMechDevices(raw map[string]json.RawMessage, height int) ([]mechDevice, error) {
	var pre struct {
		TokenInsts []struct {
			Inst struct {
				CharacterKey string `json:"characterKey"`
			} `json:"inst"`
			Position struct {
				Row *int `json:"row"`
				Col *int `json:"col"`
			} `json:"position"`
			Direction string `json:"direction"`
			//: ⚠ 键名是 `overrideSkillBlackboard`（**不是** `skillBlackboard`），
			//: 且它是一个**数组**、`branch_id` 藏在 `key`／`valueStr` 里。
			//: 读错的名字不会报错——它只会让 `branchID` 恒空，于是天桩找不到甲。
			OverrideSkillBlackboard []struct {
				Key      string `json:"key"`
				ValueStr string `json:"valueStr"`
			} `json:"overrideSkillBlackboard"`
		} `json:"tokenInsts"`
	}
	if r, ok := raw["predefines"]; ok && len(r) > 0 {
		if err := json.Unmarshal(r, &pre); err != nil {
			return nil, fmt.Errorf("predefines 解析失败：%v", err)
		}
	}
	out := []mechDevice{}
	for _, it := range pre.TokenInsts {
		if it.Inst.CharacterKey == "" || it.Position.Row == nil || it.Position.Col == nil {
			continue
		}
		out = append(out, mechDevice{
			key: it.Inst.CharacterKey,
			//: ⚠ row 是游戏内部口径（自下而上），**翻一次**
			cell:      mech.Cell{*it.Position.Col, height - 1 - *it.Position.Row},
			direction: strings.ToUpper(it.Direction),
			branchID:  branchIDOf(it.OverrideSkillBlackboard),
		})
	}
	return out, nil
}

// mechKindOf 是 `mech_consts.KINDS` 的键→种类映射（**用 key 判，不用名字**：
// 名字是中文、会随版本改）。
func mechKindOf(key string) string {
	switch key {
	case mechBlockerKey:
		return "valve"
	case mechPumpKey:
		return "pump"
	case mechPileKey:
		return "pile"
	}
	return ""
}

// ---------------------------------------------------------------- 主流程

// ParseMechQuery 解 `mechspec` 的 spec，并**拒绝不认识的键**。
//
// ⚠ 为什么不直接 `json.Unmarshal` 进 `MechQuery`：那样多出来的键会被**静默忽略**，
// 而本命令的「不吃计划」是一条**口径契约**——调用方传了 `plan`、却拿到一份没有雪
// 也没有天桩链的规格，是这条链上最贵的一种错（判决照样给出来）。
// 宁可当场具名失败。
func ParseMechQuery(raw json.RawMessage) (MechQuery, error) {
	var q MechQuery
	if len(raw) == 0 {
		return q, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return q, fmt.Errorf("spec 不是对象：%v", err)
	}
	for k := range m {
		if k != "difficulty" {
			return q, fmt.Errorf(
				"mechspec 不认识的 spec 键 %q（只收 difficulty）。★ 本命令**不吃计划**："+
					"雪那一支按排程判，而排程在计划里——要用它得先把 find_snow 与 "+
					"snow_mech_spec 搬进 Go（见 mechspec.go 的 unported）", k)
		}
	}
	if r, ok := m["difficulty"]; ok {
		if err := json.Unmarshal(r, &q.Difficulty); err != nil {
			return q, fmt.Errorf("difficulty 不是字符串：%v", err)
		}
	}
	return q, nil
}

// MechSpecBuild 造 `mechanisms` 与 `mech_config`。
func MechSpecBuild(level, path string, q MechQuery) (MechOut, error) {
	out := MechOut{
		Mechanisms: []string{},
		MechConfig: map[string]json.RawMessage{},
		Unported:   append([]string{}, mechUnportedLines...),
		Scanned:    map[string]int{},
		Params: map[string]any{
			"level": level, "path": path, "difficulty": q.Difficulty,
		},
	}
	st, raw, err := loadStageWithRaw(level, path, q.Difficulty)
	if err != nil {
		return out, err
	}
	difficulty := q.Difficulty
	if difficulty == "" {
		difficulty = st.Difficulty
	}
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	out.Params["difficulty"] = difficulty
	out.Params["level_id"] = st.LevelID
	out.Params["code"] = st.Code

	// ---- ① 田地：这一关有没有环境系统 ----
	params, bb, hasEnv, err := mechPolluteFromRunes(st, raw, difficulty)
	if err != nil {
		return out, err
	}
	if hasEnv {
		out.Scanned["env_rune"] = 1
	} else {
		out.Scanned["env_rune"] = 0
	}
	if !hasEnv {
		//: 没有环境系统 ⇒ `inp.farmland is None` ⇒ 田地那一条不给。
		//: 这一支在 26 个主线关卡上真会被走到（判据里有计数）。
		out.Scanned["farmland"] = 0
		//: ⚠ **雪与田地从这里就分道**：权威的 `names_for` 里两条各判各的
		//: （田地看 `inp.farmland`、雪看 `snow_spec`），所以没有环境系统
		//: **不等于**没有雪。原先这里直接 `return`，会把雪一并漏掉。
		return out, out.addSnow(st, q)
	}
	farm, scanned, err := buildMechFarmland(st, raw, difficulty, params, bb)
	if err != nil {
		return out, err
	}
	for k, v := range scanned {
		out.Scanned[k] = v
	}
	out.Scanned["farmland"] = 1
	out.Scanned["snow_fields"] = 0
	out.Mechanisms = append(out.Mechanisms, string(mech.FarmlandID))
	cfg, err := json.Marshal(farm)
	if err != nil {
		return out, fmt.Errorf("田地规格序列化失败：%v", err)
	}
	//: ★ **生产者造的东西，消费者必须收得下**：拿 `mech` 包那份 `UnmarshalJSON`
	//: 走一遍。形状一旦漂了，这里当场失败，而不是等到某一局跑出别的结果。
	//: （它是**消费侧**的唯一权威解析器，比我在这里另写一份字段校验可靠。）
	var consumable mech.FarmlandSpec
	if err := json.Unmarshal(cfg, &consumable); err != nil {
		return out, fmt.Errorf("田地规格消费者收不下（形状漂了）：%v", err)
	}
	out.MechConfig[string(mech.FarmlandID)] = cfg
	return out, out.addSnow(st, q)
}

// addSnow 是**雪那一条**（与田地在 `names_for` 里并列、各判各的）。
//
// 三层口径，写清楚免得下一个人把它当漏项：
//
//  1. **没有排程 ⇒ 不判也不报**：`mechspec` 这条命令不吃计划（口径契约），
//     于是 `snow_spec` 无从算起 —— `unported` 里那条雪**留着**（它确实做不到），
//     `snow_fields` 记 0。0 在这里的含义是「这一趟没有输入」，不是「查过没有」。
//  2. **有排程但没有雪**（谁都没带「无垠的雪景」）⇒ 同样记 0，`mechanisms` 不加雪。
//     这一支与上一条的**读数一样**，所以判据要能把两者分开 —— 靠的是
//     `scanned["snow_input"]`（有没有排程）另记一栏，见下。
//  3. **有排程且有雪** ⇒ 造规格、加 `mechanisms`、把 `unported` 里那条**摘掉**
//     （这一趟真做得到，就不再列它）。
//
// ⚠ 消费者核对：形状漂了要**当场**失败（与田地那一支同一条规矩），
// 所以这里也拿 `mech.SnowSpec` 走一遍反序列化。
func (o *MechOut) addSnow(st *Stage, q MechQuery) error {
	if q.Schedule == nil {
		o.Scanned["snow_input"] = 0
		o.Scanned["snow_fields"] = 0
		return nil
	}
	o.Scanned["snow_input"] = 1
	blob, n, err := SnowOf(st, q.Schedule.Rows, q.Schedule.Freeze)
	if err != nil {
		return err
	}
	o.Scanned["snow_fields"] = n
	//: ★ **有排程就摘掉那条「未搬」**，与这一关有没有雪无关：`unported` 的语义是
	//: 「**这个口径**造不出来的部分」，而带上排程之后雪是**判得了**的 ——
	//: 某一关碰巧没有雪，那是「算过了，没有」，不是「做不到」。
	//: （判据据此把两种口径分开断言，见 `check_buildspec_go.py` 的 `check_slots`。）
	dropUnported(o, snowUnportedLine)
	if blob == nil {
		return nil
	}
	var consumable mech.SnowSpec
	if err := json.Unmarshal(blob, &consumable); err != nil {
		return fmt.Errorf("积雪规格消费者收不下（形状漂了）：%v", err)
	}
	o.Mechanisms = append(o.Mechanisms, string(mech.SnowID))
	o.MechConfig[string(mech.SnowID)] = blob
	return nil
}

// dropUnported 从「未搬」清单里摘掉一条（原地，保序）。
func dropUnported(o *MechOut, line string) {
	kept := o.Unported[:0]
	for _, u := range o.Unported {
		if u != line {
			kept = append(kept, u)
		}
	}
	o.Unported = kept
}

// mechPolluteFromRunes 复刻 `environment.PolluteParams.from_stage`（`environment.py:269-289`）。
//
// 两道门都要走：① rune 在不在（`find_rune`，同键同难度取**最后一条**）；
// ② 四个参数**齐备**（`valid`：任何一个 ≤ 0 都说明 rune 没取对 ⇒ 这一关没有田地）。
//
// ★ 同时把**取到的那一条 rune 的黑板**交回去：`_seed` 读 `init_pollut_value` 用的是
// **同一个对象**（`PolluteParams.init_pollut` 就是在这一行里算出来的）。
// 拿键名按难度再找一次会在「同键多条、其中一条难度不匹配」时分叉
// ——`act31side_ex08` 的 `env_system_new` 就有 NORMAL 与 FOUR_STAR 两条。
func mechPolluteFromRunes(st *Stage, raw map[string]json.RawMessage,
	difficulty string) (mechPollutParams, []BlackboardEntry, bool, error) {
	runes, err := parseRunes(raw["runes"])
	if err != nil {
		return mechPollutParams{}, nil, false, fmt.Errorf("runes：%w", err)
	}
	r := findRune(runes, "env_system_new", difficulty)
	if r == nil {
		return mechPollutParams{}, nil, false, nil
	}
	num := func(k string) float64 {
		if v := bbNumber(r.Blackboard, k); v != nil {
			return *v
		}
		return 0.0
	}
	p := mechPollutParams{
		BasicDamage:      num("basic_damage"),
		DamageRatio:      num("damage_ratio"),
		FirstBasicDamage: num("first_basic_damage"),
		FirstDamageRatio: num("first_damage_ratio"),
		HPRecoveryPerSec: 50.0,
	}
	if v := bbNumber(r.Blackboard, "hp_recovery_per_sec"); v != nil {
		p.HPRecoveryPerSec = *v
	}
	if !(p.DamageRatio > 0 && p.BasicDamage > 0 &&
		p.FirstDamageRatio > 0 && p.FirstBasicDamage > 0) {
		return mechPollutParams{}, nil, false, nil
	}
	return p, r.Blackboard, true, nil
}

// mechBBText 复刻 `blackboard.bb_text`：值住 `valueStr`，**只认第一条同键**，
// 取不到就 None（不往后找），且取回的是 `strip()` 过的串。
func mechBBText(entries []BlackboardEntry, key string) (string, bool) {
	for _, e := range entries {
		if e.Key != key {
			continue
		}
		s := strings.TrimSpace(e.ValueStr)
		if s == "" {
			return "", false
		}
		return s, true
	}
	return "", false
}

// parseInitPollut 复刻 `environment.parse_init_pollut`（`environment.py:133-152`）。
//
// `"row,col:value|row,col:value"` → `{cell: value}`；row 翻一次
// （`y = 高 - 1 - row`）。格式坏的条目**跳过**而不是抛异常：关卡数据里偶有占位串，
// 整条失败会让「这一关没有污染点」与「解析炸了」分不出来。
//
// ⚠ 三个数用 `strconv` 而不是 `fmt.Sscanf` 解析：`Sscanf("%d")` 对 `12x` 会
// **返回 12 且不报错**，而 Python 的 `int()` 会抛 `ValueError` 走进 `continue`。
// 这一条差别只在坏数据上分叉，但坏数据正是这个函数存在的理由。
func parseInitPollut(text string, mapHeight int) map[mech.Cell]float64 {
	out := map[mech.Cell]float64{}
	if strings.TrimSpace(text) == "" {
		return out
	}
	for _, chunk := range strings.Split(text, "|") {
		chunk = strings.TrimSpace(chunk)
		if chunk == "" || !strings.Contains(chunk, ":") || !strings.Contains(chunk, ",") {
			continue
		}
		pos, val, _ := strings.Cut(chunk, ":")
		rs, cs, ok := strings.Cut(pos, ",")
		if !ok {
			continue
		}
		row, err1 := strconv.Atoi(strings.TrimSpace(rs))
		col, err2 := strconv.Atoi(strings.TrimSpace(cs))
		v, err3 := strconv.ParseFloat(strings.TrimSpace(val), 64)
		if err1 != nil || err2 != nil || err3 != nil {
			continue
		}
		out[mech.Cell{col, mapHeight - 1 - row}] = v
	}
	return out
}

// buildMechFarmland 复刻 `mech.farmland_spec`（`mech.py:360-438`）＋ 它依赖的
// `FarmlandSystem.__init__` / `_seed` / `sever`。
//
// `bb` 是**已经取到的那一条 `env_system_new` rune** 的黑板（见
// `mechPolluteFromRunes` 的说明）：`_seed` 读 `init_pollut_value` 用的就是它。
func buildMechFarmland(st *Stage, raw map[string]json.RawMessage, difficulty string,
	params mechPollutParams, bb []BlackboardEntry) (mechFarmlandOut, map[string]int, error) {
	scanned := map[string]int{}

	// ---- 田地格（`is_farmland`：低地 且 tileKey 不在排除集里）----
	cells := map[mech.Cell]bool{}
	for y := 0; y < st.Map.Height; y++ {
		for x := 0; x < st.Map.Width; x++ {
			t := st.Map.Tiles[y][x]
			if t.Height == "LOWLAND" && !mechFarmlandExcluded[t.Key] {
				cells[mech.Cell{x, y}] = true
			}
		}
	}
	scanned["cells"] = len(cells)

	// ---- 分组（`farmland_groups`：四邻连片）----
	groups := mech.ConnectedGroups(cells)
	fs := &mechFarmland{
		actual:  map[mech.Cell]float64{},
		severed: map[mech.Cell]bool{},
	}
	for _, g := range groups {
		fs.fields = append(fs.fields, &mechField{cells: g})
	}
	fs.rebuildIndex()
	scanned["groups"] = len(fs.fields)

	// ---- 播种（`_seed`，见文件头那处歧义的照抄说明）----
	initPollut, _ := mechBBText(bb, "init_pollut_value")
	seeds := parseInitPollut(initPollut, st.Map.Height)
	scanned["init_pollut_pts"] = len(seeds)
	for c, v := range seeds {
		f := fs.index[c]
		if f == nil {
			continue //: 污染点落在非田地上 ⇒ 忽略（关卡数据不多管）
		}
		fs.actual[c] = clampMech(v, mechPollutMin, mechPollutMax)
		if v > f.maximum {
			f.maximum = v
		}
	}
	for _, f := range fs.fields {
		f.maximum = clampMech(f.maximum, mechPollutMin, mechPollutMax)
	}

	// ---- 断田：预置阻流阀开场即在位（`sim.py:538-543`）----
	devices, err := parseMechDevices(raw, st.Map.Height)
	if err != nil {
		return mechFarmlandOut{}, scanned, err
	}
	//: 召唤链那一串**行使计数**。本命令的口径里 `scanned` 就是行使计数
	//: （见 `MechOut.Scanned` 的注释「每条线被喂进去多少输入」），所以最后并回
	//: 同一张表；键一律 `pile_` 开头，与既有的键不撞。
	covered := map[string]int{}
	scanned["devices"] = len(devices)
	blockers := 0
	for _, d := range devices {
		if d.key == mechBlockerKey {
			blockers++
			fs.sever(d.cell)
		}
	}
	scanned["blockers"] = blockers

	// ---- 出规格 ----
	out := mechFarmlandOut{
		Kind: "farmland", Width: st.Map.Width, Height: st.Map.Height,
		Difficulty: difficulty, Params: params,
		CacheInterval: mechCacheInterval, CachePerTick: mechCachePerTick,
		ActualInterval: mechActualInterval, ActualPerDivisor: mechActualDivisor,
		ActualBaseStep: mechActualBaseStep,
		PollutMin:      mechPollutMin, PollutMax: mechPollutMax,
		PumpRate: mechPumpRate, PumpRange: mechPumpRange,
		PumpRangeBonus: mechPumpRangeBonus,
		Groups: []mechGroupOut{}, Actual: [][3]float64{},
		Severed: [][2]int{}, Devices: []mechDeviceOut{},
	}
	for _, f := range fs.fields {
		if len(f.cells) == 0 {
			continue //: 空格子组不送（`mech.py:373-374`）
		}
		cellsOut := make([][2]int, 0, len(f.cells))
		for c := range f.cells {
			cellsOut = append(cellsOut, [2]int{c[0], c[1]})
		}
		sortCells(cellsOut)
		out.Groups = append(out.Groups, mechGroupOut{
			Cells: cellsOut, Maximum: f.maximum, Cache: f.cache})
	}
	//: ⚠ **不要把值为 0 的条目滤掉**：`actual` 里「存在一个 0」与「没有这一格」
	//: 在状态上是两回事（HS-EX-4 的播种就是 `(1,7): 0.0`）。
	for c, v := range fs.actual {
		out.Actual = append(out.Actual, [3]float64{float64(c[0]), float64(c[1]), v})
	}
	sortActual(out.Actual)
	for c := range fs.severed {
		out.Severed = append(out.Severed, [2]int{c[0], c[1]})
	}
	sortCells(out.Severed)
	//: 装置：只送**运行期真的会动**的两类（泵站每秒泵水、天桩走召唤链）；
	//: 阻流阀不送——它只剩「被拆还原」一条动作，而开场那次断田**已经算进
	//: 上面的 groups/severed 里了**（`mech.py:380-404` 的注释说的就是这件事）。
	pileCount := 0
	pileChild := 0
	pileNoChild := 0
	var chain *pileChain
	for _, d := range devices {
		kind := mechKindOf(d.key)
		if kind != "pile" && kind != "pump" {
			continue
		}
		outd := mechDeviceOut{
			Kind: kind, Key: d.key, Cell: [2]int{d.cell[0], d.cell[1]},
			Direction: d.direction,
		}
		if kind == "pile" {
			pileCount++
			//: 天桩的召唤链模板：**规格要在开战前把整条链备好**，因为甲/乙/天标
			//: 都是「谁造谁」推出来的、运行期临时算不出来（权威 `_pile_device_spec`）。
			//: 建不出来就**不填** `child`（权威 `return None` 那条），由运行期
			//: 具名拒跑 —— 一只不会召唤的天桩与「这一关没有天桩」在判决上分不开。
			if chain == nil {
				c, err := newPileChain(st, raw, difficulty, covered)
				if err != nil {
					return mechFarmlandOut{}, scanned, err
				}
				chain = c
			}
			if cs := chain.chainOf(st, d, covered); cs != nil {
				blob, err := json.Marshal(cs)
				if err != nil {
					return mechFarmlandOut{}, scanned, err
				}
				outd.Child = blob
				pileChild++
			} else {
				pileNoChild++
			}
		}
		out.Devices = append(out.Devices, outd)
	}
	scanned["devices_pile"] = pileCount
	scanned["devices_pump"] = len(out.Devices) - pileCount
	//: ★ 两个计数**必须分开**：`device_pile_child` 是「真产出了几例」（行使证据），
	//: `devices_pile_nochild` 是「建不出来几只」。压成一个数的话，
	//: 「链建好了」与「链全是空的」长得一模一样。
	scanned["devices_pile_child"] = pileChild
	scanned["devices_pile_nochild"] = pileNoChild
	for k, v := range covered {
		scanned[k] = v
	}
	return out, scanned, nil
}

func clampMech(v, lo, hi float64) float64 {
	if v < lo {
		return lo
	}
	if v > hi {
		return hi
	}
	return v
}

func sortCells(cs [][2]int) {
	sort.Slice(cs, func(i, j int) bool {
		if cs[i][0] != cs[j][0] {
			return cs[i][0] < cs[j][0]
		}
		return cs[i][1] < cs[j][1]
	})
}

func sortActual(rows [][3]float64) {
	sort.Slice(rows, func(i, j int) bool {
		if rows[i][0] != rows[j][0] {
			return rows[i][0] < rows[j][0]
		}
		return rows[i][1] < rows[j][1]
	})
}

func parseIntStrict(s string) (int, error) {
	return strconv.Atoi(strings.TrimSpace(s))
}

func parseFloatStrict(s string) (float64, error) {
	return strconv.ParseFloat(strings.TrimSpace(s), 64)
}

// 关卡取数：**直接用 `spawns.go` 的 `loadStageWithRaw`**。
//
// ⚠ 这一处**曾经是本文件里自己写的一份**（读文件 ＋ 解 `map[string]RawMessage`
// ＋ `ParseStage`）。它跟 `spawns.go` 那份逐行等价，而「同一个取数口径有两份实现」
// 正是本项目立过规矩要防的事（两份必然有一天不一致，且不一致时两边都看着对）。
// ⇒ 删掉自己那份：`loadStageWithRaw(level, path, difficulty)` 返回的
// `(*Stage, raw, error)` 正好是这里要的两样。
