package main

// stage.go：**Go 侧自己读关卡数据**（丙阶段一）。
//
// ## 它为什么存在
//
// 在此之前，关卡数据的解析整条住在 Python（`ak_tactic/gamedata/stage.py`，41 KB），
// Go 只收一份已经算好的 spec（`main.go:31-33` 写明「Go 侧不做任何数据源访问」）。
// 这一份把**关卡那一层**接过来：读 `_level_index.json` 与 `level_*.json`，
// 自己摊平波次、翻路线坐标、解地图网格。
//
// ## 语义逐条对齐 Python，不许自己发明
//
// 每一条规则都写着它在 `stage.py` 里的出处行号。跨实现对拍（`tools/` 下的
// `check_stage_go.py`）比的就是这些字段，**任何一条自作主张都会被比出来**。
//
// 三条最容易写错的：
//
//  1. **地图不翻、路线翻一次**。`mapData.map` 的第 0 行就是最上面（MAA 口径）；
//     而路线的 `row` 是游戏内部口径（自下而上），故 `y = height - 1 - row`。
//  2. **只有 MOVE / APPEAR_AT_POS 的坐标是真的**；`WAIT_FOR_SECONDS` 与
//     `DISAPPEAR` 的 position 一律是 (0,0) 占位，当坐标读会在图上画出一条
//     穿过原点的假路径（`stage.py:828-834`）。
//  3. **fragment 是串行的**：下一个 fragment 的起点 = 上一个 fragment 起点 +
//     它自己的 span，而 span 只算 SPAWN 动作（`stage.py:845-856`）。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
)

// ---------------------------------------------------------------- 类型

// Tile 是地图上的一格。四个字段全按原文抄，不做归一化。
type Tile struct {
	Key       string `json:"key"`
	Height    string `json:"height"`
	Buildable string `json:"buildable"`
	Passable  string `json:"passable"`
}

// StageMap 是网格。`Tiles[y][x]`，y 向下（MAA 口径）。
type StageMap struct {
	Width  int      `json:"width"`
	Height int      `json:"height"`
	Tiles  [][]Tile `json:"tiles"`
}

// Checkpoint 是路线上的一个检查点。
//
// `Position` 用指针：`WAIT_FOR_SECONDS` / `DISAPPEAR` **没有**坐标，
// 「没有坐标」与「坐标是 (0,0)」是两回事，不能压成零值。
//
// ⚠ `Wait` **不许 `omitempty`**：`0.0` 是「这个检查点不等待」这条读数，
// 省略它会让「不等待」与「没有这个字段」在序列化回来时长得一样
// ——本项目在相性规格那次吃过同一个亏（空值三态要用指针接）。
type Checkpoint struct {
	Type     string  `json:"type"`
	Position *[2]int `json:"position"`
	Wait     float64 `json:"wait"`
}

// Route 是一条出怪路线。
type Route struct {
	Index       int          `json:"index"`
	Mode        string       `json:"mode"`
	Start       [2]int       `json:"start"`
	End         [2]int       `json:"end"`
	Checkpoints []Checkpoint `json:"checkpoints"`
}

// EnemySpawn 是摊平之后的一条出怪指令。
type EnemySpawn struct {
	EnemyID       string  `json:"enemy_id"`
	Count         int     `json:"count"`
	Interval      float64 `json:"interval"`
	RouteIndex    int     `json:"route_index"`
	WaveIndex     int     `json:"wave_index"`
	FragmentIndex int     `json:"fragment_index"`
	ActionIndex   int     `json:"action_index"`
	PreDelay      float64 `json:"pre_delay"`
	FragmentStart float64 `json:"fragment_start"`
	Level         int     `json:"level"`
	BlockFragment bool    `json:"block_fragment"`
	//: `nil` = 这条指令没有 `hiddenGroup`；空串 = 有键但是空。
	//: **不要用 `omitempty`**：那样两者会塌成一个。
	HiddenGroup *string `json:"hidden_group"`
}

// BranchAction 是支线里的一条出怪动作。
type BranchAction struct {
	EnemyKey   string  `json:"enemy_key"`
	RouteIndex int     `json:"route_index"`
	Count      int     `json:"count"`
	Interval   float64 `json:"interval"`
	PreDelay   float64 `json:"pre_delay"`
}

// StageOptions 是关卡参数。默认值与 `stage.py:898-909` 逐项一致。
type StageOptions struct {
	CharacterLimit   int     `json:"character_limit"`
	MaxLifePoint     int     `json:"max_life_point"`
	InitialCost      float64 `json:"initial_cost"`
	MaxCost          float64 `json:"max_cost"`
	CostIncreaseTime float64 `json:"cost_increase_time"`
	MoveMultiplier   float64 `json:"move_multiplier"`
	IsTraining       bool    `json:"is_training"`
	IsHardTraining   bool    `json:"is_hard_training"`
}

// Stage 是一份解析好的关卡。
type Stage struct {
	LevelID     string                    `json:"level_id"`
	Code        string                    `json:"code"`
	Difficulty  string                    `json:"difficulty"`
	Map         StageMap                  `json:"map"`
	Routes      []Route                   `json:"routes"`
	ExtraRoutes []Route                   `json:"extra_routes"`
	Branches    map[string][]BranchAction `json:"branches"`
	Spawns      []EnemySpawn              `json:"spawns"`
	Options     StageOptions              `json:"options"`
	//: 关卡 rune（`runes` 数组）。构建规格的静态 8 项要用它，见 `stageenv.go`。
	//:
	//: ⚠ 标签是 `json:"-"`：这个字段**只在 Go 内部用**，不许出门。原版
	//: `load_stage` 的处理结果里**没有** `runes` 这个键（它住在 `st.raw` 里），
	//: 所以带上键名会让 `load` 应答多送一个键——`tools/check_stage_go.py` 的
	//: 键集比对会判红（实测 55/55 关）。
	//:
	//: 去掉键名**不影响读入**：加载器是**手工构造** `Stage` 的（`runes` 走
	//: `parseRunes(raw["runes"])`，见本文件 `Load` 那一段），不经过结构体反序列化。
	Runes []Rune `json:"-"`
	//: 关卡自带的敌人定义：`id → overwrittenData`（只有 `enemyDbRefs` 里
	//: `useDb:false` 的那些）。与 Python 的 `stage.local_enemies()` 同口径。
	//:
	//: ⚠ 标签同样是 `json:"-"`：原版 `load_stage` 的返回值里**没有**这个键
	//: （它住在 `st.raw` 里），带上键名会让 `load` 应答多送一个键而判红。
	LocalEnemies map[string]map[string]json.RawMessage `json:"-"`
}

// EnemyRef 是 `enemyDbRefs` 的一条：这一关引用了哪个敌人、用哪一档。
type EnemyRef struct {
	ID    string `json:"id"`
	Level int    `json:"level"`
}

// ---------------------------------------------------------------- 索引

// LevelEntry 是 `_level_index.json` 里的一条。
//
// ★ 难度**不在关卡文件里**，只有这条记着它（`stage.py:960-961`）：
// `act31side_ex08` 与它的 `#f#` 读同一个 `data_path`，区别只在这里。
type LevelEntry struct {
	Difficulty string `json:"difficulty"`
	ZoneID     string `json:"zone_id"`
	DataPath   string `json:"data_path"`
	Code       string `json:"code"`
}

// LevelIndex 是关卡索引：levelId → 条目。键序无所谓，查找走 map。
type LevelIndex map[string]LevelEntry

// DataRoot 返回数据根目录。可用 `RIOS_DATA` 覆盖（测试与外部树要用）。
func DataRoot() string {
	if v := os.Getenv("RIOS_DATA"); v != "" {
		return v
	}
	return filepath.Join("data", "gamedata")
}

// LoadIndex 读关卡索引。
func LoadIndex() (LevelIndex, error) {
	p := filepath.Join(DataRoot(), "_level_index.json")
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("读关卡索引失败（%s）：%w", p, err)
	}
	var idx LevelIndex
	if err := json.Unmarshal(blob, &idx); err != nil {
		return nil, fmt.Errorf("关卡索引不是合法 JSON（%s）：%w", p, err)
	}
	if len(idx) == 0 {
		return nil, fmt.Errorf("关卡索引是空的（%s）", p)
	}
	return idx, nil
}

// ResolveLevel 把一个查询串解析成条目。
//
// 与 `stage.py:966-980` 同口径：**先按 levelId 精确查，再按玩家写的关卡号（code）查**。
// code 可能对应多档（`main_00-01` 与 `main_00-01#f#` 的 code 都是 `0-1`），
// 此时**取不带 `#` 后缀的那个**——普通档；要突袭档请直接把 `#f#` 写进查询串。
func ResolveLevel(idx LevelIndex, query string) (string, LevelEntry, error) {
	if e, ok := idx[query]; ok {
		return query, e, nil
	}
	var hits []string
	for lid, e := range idx {
		if e.Code == query {
			hits = append(hits, lid)
		}
	}
	if len(hits) == 0 {
		return "", LevelEntry{}, fmt.Errorf("找不到关卡 %q（既不是 levelId 也不是关卡号）", query)
	}
	sort.Strings(hits)
	for _, lid := range hits { // 排好序之后先找没有 `#` 的
		if !strings.Contains(lid, "#") {
			return lid, idx[lid], nil
		}
	}
	return hits[0], idx[hits[0]], nil
}

// LoadStage 读一份关卡并解析。`code`/`difficulty` 由索引那条给（见 LevelEntry）。
func LoadStage(query string) (*Stage, error) {
	idx, err := LoadIndex()
	if err != nil {
		return nil, err
	}
	lid, entry, err := ResolveLevel(idx, query)
	if err != nil {
		return nil, err
	}
	p := filepath.Join(DataRoot(), "map.ark-nights.com", "levels", entry.DataPath)
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("读关卡文件失败（%s）：%w", p, err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return nil, fmt.Errorf("关卡文件不是合法 JSON（%s）：%w", p, err)
	}
	return ParseStage(raw, lid, entry.Code, entry.Difficulty)
}

// ---------------------------------------------------------------- 解析

// ParseStage 把一份关卡 JSON 解析成 Stage。
//
// 用 `map[string]json.RawMessage` 收顶层：**缺键与坏键要能分开**——
// 直接把整份解进结构体会让「没有这个键」与「键是空的」长得一样。
func ParseStage(raw map[string]json.RawMessage, levelID, code, difficulty string) (*Stage, error) {
	mdRaw, ok := raw["mapData"]
	if !ok {
		return nil, fmt.Errorf("这份数据里没有 mapData，不像关卡文件")
	}
	world, err := parseMap(mdRaw)
	if err != nil {
		return nil, err
	}
	if code == "" {
		code = levelID
	}
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	routes, err := parseRoutes(raw["routes"], world.Height)
	if err != nil {
		return nil, fmt.Errorf("routes：%w", err)
	}
	extra, err := parseRoutes(raw["extraRoutes"], world.Height)
	if err != nil {
		return nil, fmt.Errorf("extraRoutes：%w", err)
	}
	spawns, err := parseSpawns(raw["waves"], raw["enemyDbRefs"])
	if err != nil {
		return nil, fmt.Errorf("waves：%w", err)
	}
	branches, err := parseBranches(raw["branches"])
	if err != nil {
		return nil, fmt.Errorf("branches：%w", err)
	}
	opts, err := parseOptions(raw["options"])
	if err != nil {
		return nil, fmt.Errorf("options：%w", err)
	}
	runes, err := parseRunes(raw["runes"])
	if err != nil {
		return nil, fmt.Errorf("runes：%w", err)
	}
	//: ★ 关卡**自带的**敌人定义（`enemyDbRefs` 里 `useDb:false` 的那些）挂在这里，
	//: 与 Python 的 `stage.local_enemies()`（`gamedata/stage.py:690-701`）同口径。
	//: 为什么必须有它：这些 id **不在属性库里**，整份数据写在关卡文件里，只有
	//: `prefabKey` 指向的那个在库里。取敌人时**先当它在库里，取不到才走本地覆盖**
	//: （`frontend/enemy_stats.py:37-55`）——少这一条回退，闸门会在
	//: `unsupported.go` 那里对这类敌人**大声失败**（本轮实测：第 14/16/17 章的
	//: `easy_14-11`/`main_14-11`/`main_16-08`/`main_17-17` 四关的出怪表真的引用了）。
	defs, err := parseLocalEnemyDefs(raw)
	if err != nil {
		return nil, fmt.Errorf("enemyDbRefs：%w", err)
	}
	locals := localEnemies(defs)
	return &Stage{
		LevelID: levelID, Code: code, Difficulty: difficulty,
		Map: world, Routes: routes, ExtraRoutes: extra,
		Branches: branches, Spawns: spawns, Options: opts,
		Runes: runes, LocalEnemies: locals,
	}, nil
}

// checkpointByInt / motionByInt / actionByInt：**旧版枚举编码**的整数 → 字符串。
//
// ★ 2026-09-27：实测缓存里 169 个关卡文件用旧编码（`mapData.tiles[].passableMask`
// 是整数），它们的 `routes[].checkpoints[].type`、`routes[].motionMode`、
// `waves[].fragments[].actions[].actionType` 也一并是整数。映射**不是猜的**：
//
//	checkpoints.type  0→MOVE（13022 个带真坐标、全落在可走格）
//	                  6→APPEAR_AT_POS（469 个里 467 个落在 tile_telout 传送落点）
//	                  5→DISAPPEAR（469 次，与 6 一一配对：先消失再在别处出现）
//	                  1→WAIT_FOR_SECONDS（3558 个 (0,0) 占位，等待类里的多数）
//	                  3/4→两个等待类（纯占位）
//	motionMode        0→WALK（字符串侧 92%、整数侧 96%，优势项一致）
//	actionType        0→SPAWN（字符串侧 86.7%、整数侧 91%；三处代码都只判 SPAWN）
//
// ★ 我们只对 `MOVE`／`APPEAR_AT_POS` 分支（`etaroutes.go` 的 `has_move`），
// 而这两个恰好被证据钉死；其余取值只影响 `type` 那一栏的字面。
// 与 `ak_tactic/gamedata/stage.py` 的三张表**同一份口径**。
var (
	checkpointByInt = map[int]string{
		0: "MOVE", 1: "WAIT_FOR_SECONDS", 3: "WAIT_CURRENT_FRAGMENT_TIME",
		4: "WAIT_CURRENT_WAVE_TIME", 5: "DISAPPEAR", 6: "APPEAR_AT_POS",
	}
	motionByInt = map[int]string{0: "WALK", 1: "E_NUM"}
	actionByInt = map[int]string{0: "SPAWN"}
)

// checkpointTypeOf 归一检查点类型。**认不出的整数报错**（不静默当 MOVE）——
// 与参照实现同处置：新取值必须先显式裁定。
func checkpointTypeOf(raw json.RawMessage) (string, error) {
	if isJSONString(raw) {
		return rawString(raw), nil
	}
	n := rawInt(raw)
	if s, ok := checkpointByInt[n]; ok {
		return s, nil
	}
	return "", fmt.Errorf("路线里出现没见过的检查点整数取值 %d"+
		"（已知映射见 stage.go 的 checkpointByInt；新取值要显式裁定后再放行，"+
		"猜错会静默改变路线与到达时刻）", n)
}

func motionModeOf(raw json.RawMessage) string {
	if isJSONString(raw) {
		return rawString(raw)
	}
	return motionByInt[rawInt(raw)]
}

func actionTypeOf(raw json.RawMessage) string {
	if isJSONString(raw) {
		return rawString(raw)
	}
	return actionByInt[rawInt(raw)]
}

// passableOf 把 `passableMask` 归一成字符串。
//
// ★ 2026-09-27：**新地图里它是整数掩码**。实测全量缓存 1764 个关卡文件里
// 7553 个格子的 `passableMask` 是整数，取值只有 `2` 与 `3`（例关
// `activities/act10d5/level_act10d5_01.json` —— 当天新加回来的故事集那一族）。
// 旧写法把这个字段声明成 `string`，`json.Unmarshal` 会直接报
// 「cannot unmarshal number into Go struct field … of type string」⇒
// **那些关卡整个解不开**（界面里 load 不出来、部署人数上限也取不到）。
//
// 位义（与 `ak_tactic/gamedata/stage.py` 的 `normalize_passable_mask` 同一份口径）：
// bit0 地面可走 ⇒ `ALL`；bit1 仅飞行 ⇒ `FLY_ONLY`；两位都没有 ⇒ `NONE`。
// 认不出的形状返回空串（与旧行为一致，**不猜**）。
// heightOf / buildableOf 把这两个字段也归一成字符串（**序数枚举**，名字里是 Type
// 不是 Mask）。
//
// 依据（2026-09-27 实测全量缓存 1764 个关卡文件，整数形态共 7553 个格子，都在
// `act10d5`／`act10mini` 这些新加回来的故事集关卡里）：
//
//	heightType    字符串 HIGHLAND 53.6% / LOWLAND 46.4%
//	              整数      1: 53.8% / 0: 46.2%      ⇒ 1=HIGHLAND、0=LOWLAND
//	buildableType 字符串 NONE 66% / MELEE 24% / RANGED 11% / ALL 1.7%
//	              整数   0: 64% / 1: 24% / 2: 11.6% / 3: 0.7% ⇒ 序数一一对应
//
// 与 `ak_tactic/gamedata/stage.py` 的 `normalize_height_type` /
// `normalize_buildable_type` 是同一份口径。
func heightOf(raw json.RawMessage) string {
	if s := rawString(raw); s != "" || isJSONString(raw) {
		return s
	}
	switch rawInt(raw) {
	case 0:
		return "LOWLAND"
	case 1:
		return "HIGHLAND"
	}
	return ""
}

func buildableOf(raw json.RawMessage) string {
	if s := rawString(raw); s != "" || isJSONString(raw) {
		return s
	}
	switch rawInt(raw) {
	case 0:
		return "NONE"
	case 1:
		return "MELEE"
	case 2:
		return "RANGED"
	case 3:
		return "ALL"
	}
	return ""
}

// isJSONString 判这个原始值是不是 JSON 字符串（空串也是合法字符串，所以不能只看
// `rawString` 返不返空）。
func isJSONString(raw json.RawMessage) bool {
	s := strings.TrimSpace(string(raw))
	return len(s) > 0 && s[0] == '"'
}

func rawString(raw json.RawMessage) string {
	var out string
	if err := json.Unmarshal(raw, &out); err != nil {
		return ""
	}
	return out
}

func rawInt(raw json.RawMessage) int {
	n, err := strconv.Atoi(strings.TrimSpace(string(raw)))
	if err != nil {
		return -1
	}
	return n
}

func passableOf(raw json.RawMessage) string {
	s := strings.TrimSpace(string(raw))
	if s == "" || s == "null" {
		return ""
	}
	if s[0] == '"' { //: 字符串形态：原样解出来
		var out string
		if err := json.Unmarshal(raw, &out); err != nil {
			return ""
		}
		return out
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return ""
	}
	switch {
	case n&1 != 0:
		return "ALL"
	case n&2 != 0:
		return "FLY_ONLY"
	default:
		return "NONE"
	}
}

func parseMap(mdRaw json.RawMessage) (StageMap, error) {
	var md struct {
		Map   [][]int `json:"map"`
		Tiles []struct {
			TileKey       string          `json:"tileKey"`
			HeightType    json.RawMessage `json:"heightType"`
			BuildableType json.RawMessage `json:"buildableType"`
			PassableMask  json.RawMessage `json:"passableMask"`
		} `json:"tiles"`
	}
	if err := json.Unmarshal(mdRaw, &md); err != nil {
		return StageMap{}, fmt.Errorf("mapData 解析失败：%w", err)
	}
	h := len(md.Map)
	w := 0
	if h > 0 {
		w = len(md.Map[0])
	}
	// ★ 不翻 y：第 0 行就是最上面那一行（`stage.py:785`）。
	grid := make([][]Tile, h)
	for y := 0; y < h; y++ {
		if len(md.Map[y]) != w {
			return StageMap{}, fmt.Errorf("mapData.map 第 %d 行宽 %d，与第 0 行的 %d 不等",
				y, len(md.Map[y]), w)
		}
		row := make([]Tile, w)
		for x := 0; x < w; x++ {
			i := md.Map[y][x]
			if i < 0 || i >= len(md.Tiles) {
				return StageMap{}, fmt.Errorf("mapData.map[%d][%d]=%d 越出 tiles（共 %d 项）",
					y, x, i, len(md.Tiles))
			}
			t := md.Tiles[i]
			row[x] = Tile{Key: t.TileKey, Height: heightOf(t.HeightType),
				Buildable: buildableOf(t.BuildableType),
				Passable:  passableOf(t.PassableMask)}
		}
		grid[y] = row
	}
	return StageMap{Width: w, Height: h, Tiles: grid}, nil
}

func parseRoutes(routesRaw json.RawMessage, height int) ([]Route, error) {
	if len(routesRaw) == 0 {
		return []Route{}, nil
	}
	var raws []struct {
		MotionMode    json.RawMessage `json:"motionMode"`
		StartPosition struct {
			Col *int `json:"col"`
			Row *int `json:"row"`
		} `json:"startPosition"`
		EndPosition struct {
			Col *int `json:"col"`
			Row *int `json:"row"`
		} `json:"endPosition"`
		Checkpoints []struct {
			Type     json.RawMessage `json:"type"`
			Time     float64         `json:"time"`
			Position struct {
				Col *int `json:"col"`
				Row *int `json:"row"`
			} `json:"position"`
		} `json:"checkpoints"`
	}
	if err := json.Unmarshal(routesRaw, &raws); err != nil {
		return nil, err
	}
	// ★ 路线要翻一次 y（`stage.py:800-807`）。
	flip := func(col, row *int) [2]int {
		c, r := 0, 0
		if col != nil {
			c = *col
		}
		if row != nil {
			r = *row
		}
		return [2]int{c, height - 1 - r}
	}
	out := make([]Route, 0, len(raws))
	for i, r := range raws {
		cps := make([]Checkpoint, 0, len(r.Checkpoints))
		for _, c := range r.Checkpoints {
			ctype, err := checkpointTypeOf(c.Type)
			if err != nil {
				return nil, err
			}
			if ctype == "" {
				ctype = "MOVE"
			}
			if ctype == "MOVE" || ctype == "APPEAR_AT_POS" {
				p := flip(c.Position.Col, c.Position.Row)
				cps = append(cps, Checkpoint{Type: ctype, Position: &p})
			} else {
				// ★ 这两种的 position 是 (0,0) 占位，当坐标读会画出假路径。
				cps = append(cps, Checkpoint{Type: ctype, Position: nil, Wait: c.Time})
			}
		}
		out = append(out, Route{
			Index: i, Mode: motionModeOf(r.MotionMode),
			Start:       flip(r.StartPosition.Col, r.StartPosition.Row),
			End:         flip(r.EndPosition.Col, r.EndPosition.Row),
			Checkpoints: cps,
		})
	}
	return out, nil
}

// fragSpan 复刻 `_fragment_span`（`stage.py:845-856`）：只算 SPAWN。
func fragSpan(frag waveFragment) float64 {
	end := 0.0
	for _, a := range frag.Actions {
		if actionTypeOf(a.ActionType) != "SPAWN" {
			continue
		}
		span := a.PreDelay + float64(maxInt(0, a.count()-1))*a.interval()
		if span > end {
			end = span
		}
	}
	return end
}

type waveAction struct {
	ActionType    json.RawMessage `json:"actionType"`
	Key           string          `json:"key"`
	Count         *int            `json:"count"`
	Interval      *float64        `json:"interval"`
	RouteIndex    *int            `json:"routeIndex"`
	PreDelay      float64         `json:"preDelay"`
	BlockFragment bool            `json:"blockFragment"`
	HiddenGroup   *string         `json:"hiddenGroup"`
}

// count 返回这一条动作的出怪数。`nil`（键缺失或显式 null）与 0 都当 1——
// 与 `stage.py:882` 的 `int(a.get("count", 1) or 1)` 同口径。
func (a waveAction) count() int {
	if a.Count == nil || *a.Count == 0 {
		return 1
	}
	return *a.Count
}

// interval 默认 1.0（`stage.py::_parse_spawns`）。注意 `or 0.0`：显式 0 也是 0。
func (a waveAction) interval() float64 {
	if a.Interval == nil {
		return 1.0
	}
	return *a.Interval
}

// branchInterval 复刻 `stage.py::_parse_branches` 那一行：
//
//	interval=float(a.get("interval", 1.0) or 1.0)
//
// ★ 它**与出怪那一支不是同一个口径**：出怪是 `or 0.0`（显式 0 保留 0），
// 支线是 `or 1.0`（显式 0 被 `or` 顶成 1.0）。实测依据：`act26side_ex08`
// 的 `branches.cledub_summon[0]` 与 `act49side_10` 的
// `branches.left_hand_room_branch[5]` 里都**明写着** `"interval": 0`，
// Python 参照读出来是 1.0，而 Go 原来直接抄了 0 ⇒ 判据上三处各红一处
// （`act26side_ex08` 与它的 `#f#` 别名是同一份内容）。
func (a waveAction) branchInterval() float64 {
	if a.Interval == nil || *a.Interval == 0 {
		return 1.0
	}
	return *a.Interval
}

type waveFragment struct {
	PreDelay float64      `json:"preDelay"`
	Actions  []waveAction `json:"actions"`
}

func parseSpawns(wavesRaw, refsRaw json.RawMessage) ([]EnemySpawn, error) {
	levelOf := map[string]int{}
	if len(refsRaw) > 0 {
		var refs []EnemyRef
		if err := json.Unmarshal(refsRaw, &refs); err != nil {
			return nil, fmt.Errorf("enemyDbRefs：%w", err)
		}
		for _, r := range refs {
			levelOf[r.ID] = r.Level
		}
	}
	out := []EnemySpawn{}
	if len(wavesRaw) == 0 {
		return out, nil
	}
	var waves []struct {
		PreDelay  float64        `json:"preDelay"`
		Fragments []waveFragment `json:"fragments"`
	}
	if err := json.Unmarshal(wavesRaw, &waves); err != nil {
		return nil, err
	}
	// ★ 波次内部：fragment 串行；★ 波次之间：`t` 是**赋值**不是累加（`stage.py:872`）。
	for wi, wave := range waves {
		t := wave.PreDelay
		for fi, frag := range wave.Fragments {
			t += frag.PreDelay
			start := t
			for ai, a := range frag.Actions {
				if actionTypeOf(a.ActionType) != "SPAWN" {
					continue
				}
				ri := 0
				if a.RouteIndex != nil {
					ri = *a.RouteIndex
				}
				out = append(out, EnemySpawn{
					EnemyID: a.Key, Count: a.count(), Interval: a.interval(),
					RouteIndex: ri, WaveIndex: wi, FragmentIndex: fi,
					ActionIndex: ai, PreDelay: a.PreDelay, FragmentStart: start,
					Level: levelOf[a.Key], BlockFragment: a.BlockFragment,
					HiddenGroup: a.HiddenGroup,
				})
			}
			t = start + fragSpan(frag)
		}
	}
	return out, nil
}

func parseBranches(raw json.RawMessage) (map[string][]BranchAction, error) {
	out := map[string][]BranchAction{}
	if len(raw) == 0 {
		return out, nil
	}
	var blks map[string]struct {
		Phases []struct {
			Actions []waveAction `json:"actions"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(raw, &blks); err != nil {
		return nil, err
	}
	for name, blk := range blks {
		acts := []BranchAction{}
		for _, ph := range blk.Phases {
			for _, a := range ph.Actions {
				if strings.ToUpper(actionTypeOf(a.ActionType)) != "SPAWN" {
					continue
				}
				ri := 0
				if a.RouteIndex != nil {
					ri = *a.RouteIndex
				}
				//: ★ 支线用 `or 1.0` 口径（出怪那支是 `or 0.0`）——见 branchInterval 的注释。
				iv := a.branchInterval()
				acts = append(acts, BranchAction{
					EnemyKey: a.Key, RouteIndex: ri, Count: a.count(),
					Interval: iv, PreDelay: a.PreDelay,
				})
			}
		}
		if len(acts) > 0 {
			out[name] = acts
		}
	}
	return out, nil
}

func parseOptions(raw json.RawMessage) (StageOptions, error) {
	o := StageOptions{CostIncreaseTime: 1.0, MoveMultiplier: 1.0}
	if len(raw) == 0 {
		return o, nil
	}
	var src struct {
		CharacterLimit   *int     `json:"characterLimit"`
		MaxLifePoint     *int     `json:"maxLifePoint"`
		InitialCost      *float64 `json:"initialCost"`
		MaxCost          *float64 `json:"maxCost"`
		CostIncreaseTime *float64 `json:"costIncreaseTime"`
		MoveMultiplier   *float64 `json:"moveMultiplier"`
		IsTraining       bool     `json:"isTrainingLevel"`
		IsHardTraining   bool     `json:"isHardTrainingLevel"`
	}
	if err := json.Unmarshal(raw, &src); err != nil {
		return o, err
	}
	if src.CharacterLimit != nil {
		o.CharacterLimit = *src.CharacterLimit
	}
	if src.MaxLifePoint != nil {
		o.MaxLifePoint = *src.MaxLifePoint
	}
	if src.InitialCost != nil {
		o.InitialCost = *src.InitialCost
	}
	if src.MaxCost != nil {
		o.MaxCost = *src.MaxCost
	}
	// `or 1.0`：显式 0 也当 1.0（`stage.py:905`）。
	if src.CostIncreaseTime != nil && *src.CostIncreaseTime != 0 {
		o.CostIncreaseTime = *src.CostIncreaseTime
	}
	if src.MoveMultiplier != nil && *src.MoveMultiplier != 0 {
		o.MoveMultiplier = *src.MoveMultiplier
	}
	o.IsTraining = src.IsTraining
	o.IsHardTraining = src.IsHardTraining
	return o, nil
}

func maxInt(a, b int) int {
	if a > b {
		return a
	}
	return b
}
