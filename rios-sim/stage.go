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
	LevelID     string                  `json:"level_id"`
	Code        string                  `json:"code"`
	Difficulty  string                  `json:"difficulty"`
	Map         StageMap                `json:"map"`
	Routes      []Route                 `json:"routes"`
	ExtraRoutes []Route                 `json:"extra_routes"`
	Branches    map[string][]BranchAction `json:"branches"`
	Spawns      []EnemySpawn            `json:"spawns"`
	Options     StageOptions            `json:"options"`
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
	return &Stage{
		LevelID: levelID, Code: code, Difficulty: difficulty,
		Map: world, Routes: routes, ExtraRoutes: extra,
		Branches: branches, Spawns: spawns, Options: opts,
		Runes: runes,
	}, nil
}

func parseMap(mdRaw json.RawMessage) (StageMap, error) {
	var md struct {
		Map   [][]int  `json:"map"`
		Tiles []struct {
			TileKey       string `json:"tileKey"`
			HeightType    string `json:"heightType"`
			BuildableType string `json:"buildableType"`
			PassableMask  string `json:"passableMask"`
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
			row[x] = Tile{Key: t.TileKey, Height: t.HeightType,
				Buildable: t.BuildableType, Passable: t.PassableMask}
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
		MotionMode    string `json:"motionMode"`
		StartPosition struct {
			Col *int `json:"col"`
			Row *int `json:"row"`
		} `json:"startPosition"`
		EndPosition struct {
			Col *int `json:"col"`
			Row *int `json:"row"`
		} `json:"endPosition"`
		Checkpoints []struct {
			Type     string  `json:"type"`
			Time     float64 `json:"time"`
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
			ctype := c.Type
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
			Index: i, Mode: r.MotionMode,
			Start: flip(r.StartPosition.Col, r.StartPosition.Row),
			End:   flip(r.EndPosition.Col, r.EndPosition.Row),
			Checkpoints: cps,
		})
	}
	return out, nil
}

// fragSpan 复刻 `_fragment_span`（`stage.py:845-856`）：只算 SPAWN。
func fragSpan(frag waveFragment) float64 {
	end := 0.0
	for _, a := range frag.Actions {
		if a.ActionType != "SPAWN" {
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
	ActionType    string   `json:"actionType"`
	Key           string   `json:"key"`
	Count         *int     `json:"count"`
	Interval      *float64 `json:"interval"`
	RouteIndex    *int     `json:"routeIndex"`
	PreDelay      float64  `json:"preDelay"`
	BlockFragment bool     `json:"blockFragment"`
	HiddenGroup   *string  `json:"hiddenGroup"`
}

// count 返回这一条动作的出怪数。`nil`（键缺失或显式 null）与 0 都当 1——
// 与 `stage.py:882` 的 `int(a.get("count", 1) or 1)` 同口径。
func (a waveAction) count() int {
	if a.Count == nil || *a.Count == 0 {
		return 1
	}
	return *a.Count
}

// interval 默认 1.0（`stage.py:883`）。注意 `or 0.0`：显式 0 也是 0。
func (a waveAction) interval() float64 {
	if a.Interval == nil {
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
				if a.ActionType != "SPAWN" {
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
				if strings.ToUpper(a.ActionType) != "SPAWN" {
					continue
				}
				ri := 0
				if a.RouteIndex != nil {
					ri = *a.RouteIndex
				}
				iv := 1.0
				if a.Interval != nil {
					iv = *a.Interval
				}
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
