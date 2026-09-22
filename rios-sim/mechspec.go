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

//: 未搬的两条线。与判据脚本的 `UNPORTED` 同源，两边不一致时判据会红。
var mechUnportedLines = []string{
	//: `mech_config.farmland.devices[].child`：天桩那一条召唤链的四跳模板
	//: （装置→甲→乙→天标）住在 `mech._pile_device_spec`，它要 `spec._unit_spec`
	//: ——敌人规格那一层还没进 Go。**顶层的 kind/key/cell/direction 照造**，
	//: 缺的只有 `child`；它的条数逐关现算，记在 `scanned.devices_pile`。
	"farmland.devices[].child",
	//: 雪：`snow_mech_spec` 要 `snow_spec` → `d.talents` 的「无垠的雪景」
	//: （`frontend/talent_finders.find_snow`），而且它按**排程**判——
	//: 本命令不吃计划 ⇒ 这一支在**本口径下恒不可达**（判据每次现算并断言为 0）。
	"snow.field",
}

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

// ---------------------------------------------------------------- 装置
//
// 复刻 `frontend/devices.py:201-233` 的 `parse_devices`：唯一来源是
// `stage.raw["predefines"]["tokenInsts"]`（**不要**退到 `characterInsts`，
// 那里是预置的**干员**，混进来会凭空多出几个装置）。
type mechDevice struct {
	key       string
	cell      mech.Cell
	direction string
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
		//: 没有环境系统 ⇒ `inp.farmland is None` ⇒ `names_for` 一条都不给。
		//: 这一支在 26 个主线关卡上真会被走到（判据里有计数）。
		out.Scanned["farmland"] = 0
		//: 雪：本命令不吃计划 ⇒ `snow_spec` 恒空 ⇒ 这一档的分母恒为 0。
		//: 它**不是**「查过了没问题」，是「这一趟没有输入」——判据按同一口径
		//: 取期望值，并对「生产口径里带雪的关数」另印一个数（见判据第五节）。
		out.Scanned["snow_fields"] = 0
		return out, nil
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
	return out, nil
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
	for _, d := range devices {
		kind := mechKindOf(d.key)
		if kind != "pile" && kind != "pump" {
			continue
		}
		if kind == "pile" {
			pileCount++
		}
		out.Devices = append(out.Devices, mechDeviceOut{
			Kind: kind, Key: d.key, Cell: [2]int{d.cell[0], d.cell[1]},
			Direction: d.direction,
			//: ← `Child` 不填：天桩的召唤链模板要 `_unit_spec`（见 unported）。
		})
	}
	scanned["devices_pile"] = pileCount
	scanned["devices_pump"] = len(out.Devices) - pileCount
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
