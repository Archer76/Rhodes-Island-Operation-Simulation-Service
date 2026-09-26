package main

import (
	"encoding/json"
	"fmt"
	"math"
	"sort"

	"rios-sim/core"
)

// # 候选生成：`ak_tactic/search.py:48-187` 的 Go 侧对应物
//
// 搜索空间是「格子 × 干员 × 朝向 × 部署时机 × 技能时机」，而一次完整模拟是秒级的，
// **不能拿它当内循环**。所以第一层是**几何剪枝（不算打架）**：
//
//	价值 = dwell × 攻击力
//
// `dwell` 是这片攻击格集合里累计的**敌人·秒**（`arrivals.go` 的 `ArrivalIndex`）——
// 这就是「这个位置能不能接到活」的几何上界，不用跑模拟。乘攻击力是把它粗化成
// 「能打出多少伤害」，否则一个高台奶妈会和一个术师排在同样的名次上。
//
// `dwell` 为零的落位**连试都不必试**（敌人的路线根本不经过那里）——这一条剪掉的
// 候选最多，也是这一层存在的全部理由。
//
// ## 三处顺序不是随便定的
//
//   - **朝向枚举顺序**照 Python 的 `search.DIRECTIONS`（右、左、上、下）；
//   - **同分时的先后**：Python 的 `list.sort` 稳定，所以同价值的候选保持插入序
//     ⇒ Go 这边一律 `sort.SliceStable`（beam 之后要按序切 `uniq[:beam]`，
//     平局顺序变了产物就变）；
//   - **格子集合去掉重复**后才喂给 `dwell`：Python 的 `_range_cells` 返回
//     `frozenset`，而 `dwell` 是**按 visit 累加**的 ⇒ 同一个格子出现两次会把
//     那段时间算两遍。这是 `frozenset` 在语义上真正起作用的地方。

// SearchDirections 照 Python 的 `search.DIRECTIONS`（顺序有意义，见文件头）。
var SearchDirections = []string{"Right", "Left", "Up", "Down"}

// defaultPerOp 是 `candidates_for` 的 `per_op` 缺省（`search.py:122`）。
const defaultPerOp = 6

// CandidateRow 是一个候选落位（`search.py:48` 的 `Candidate`）。
//
// `cells` 在 Python 那边是 `frozenset` ⇒ **顺序无意义**；这里排过序只是为了
// 输出确定（判据要按集合比，不能逐元素比顺序）。
type CandidateRow struct {
	Operator  string   `json:"operator"`
	CharID    string   `json:"char_id"`
	Position  [2]int   `json:"position"`
	Direction string   `json:"direction"`
	Skill     int      `json:"skill"`
	Mastery   int      `json:"mastery"`
	Dwell     float64  `json:"dwell"`
	Visits    int      `json:"visits"`
	Value     float64  `json:"value"`
	Cells     [][2]int `json:"cells"`
}

// CandidateStats 是**行使计数**：这一层把候选从多少压到了多少。
//
// 它是判据的眼睛：`dwell_zero` 与 `not_in_spots` 是两条剪枝分支，它们跑了 0 次
// 与「这份数据本来就走不到」必须长得不一样。
type CandidateStats struct {
	Operators      int `json:"operators"`
	EntryMissing   int `json:"entry_missing"` //: 名册里没有这一位
	NoCharID       int `json:"no_char_id"`    //: 名册没有 char_id 且名字表里也查不到
	UnitFailed     int `json:"unit_failed"`   //: 练度折算失败（照 Python：跳过这一位）
	AtkMissing     int `json:"atk_missing"`   //: 面板里取不到攻击力（形状变了）—— 不许静默按 0 算
	MeleeOps       int `json:"melee_ops"`
	RangedOps      int `json:"ranged_ops"`
	PositionsTried int `json:"positions_tried"`
	NotInSpots     int `json:"not_in_spots"`   //: 那一格不是这位干员能站的（近战/高台）
	RangeMissing   int `json:"range_missing"`  //: 范围代号不在表里
	EmptyRange     int `json:"empty_range"`    //: 算出来一个格都没有
	VisitsZero     int `json:"visits_zero"`    //: **dwell 为零被剪掉** —— 剪得最多的一支
	Kept           int `json:"kept"`           //: 每干员留前 per_op 个之后的总数
	AllCandidates  int `json:"all_candidates"` //: 剪枝之后、按 per_op 截断之前
}

// CandidatesQuery 是 `candidates` 命令的 spec。
type CandidatesQuery struct {
	//: 名册 JSON 的路径（`core.ReadRoster` 读得动的那种）。
	//:
	//: ★ 走**文件**而不是走桥的名册应答：桥那边只送 5 个字段（char_id/name/
	//: profession/elite/level），而这一层要 `potential` 与 `module`/`module_level`
	//: 才算得对攻击力 —— 差这几个字段，价值排序就会与 Python 分叉。
	//: 桥的 `roster` 应答里已经带 `path`，界面把它原样转过来即可。
	Roster     string            `json:"roster"`
	Difficulty string            `json:"difficulty"`
	Operators  []string          `json:"operators"`
	PerOp      int               `json:"per_op"`
	Directions []string          `json:"directions"`
	Skills     map[string][2]int `json:"skills"` //: 名字 → [技能槽, 专精]
	SpeedScale float64           `json:"speed_scale"`
}

// CandidatesOut 是 `candidates` 的应答。
type CandidatesOut struct {
	Rows    []CandidateRow `json:"rows"`
	Covered CandidateStats `json:"covered"`
	Params  map[string]any `json:"params"`
}

// isMeleeChar 复刻 `verify.py:217` 的 `is_melee`：`position == "MELEE"` 即近战。
//
// 判的是**主职业的站位**（`character_table` 里的 `position`），不是职业名 ——
// 与 Python 同一处取数。
func isMeleeChar(charID string) (bool, error) {
	tbl, err := loadCharTable()
	if err != nil {
		return false, err
	}
	raw, ok := tbl[charID]
	if !ok || string(raw) == "null" {
		return false, fmt.Errorf("character_table 里没有 %q", charID)
	}
	var c struct {
		Position string `json:"position"`
	}
	if err := json.Unmarshal(raw, &c); err != nil {
		return false, fmt.Errorf("%s 的 position 解析失败：%w", charID, err)
	}
	return c.Position == "MELEE", nil
}

// atkOf 取面板 `total` 里的攻击力。
//
// ⚠ **不许用 `asF`**（`spawns.go` 那个）：它只认 `float64`，而 `total["atk"]` 实测
// 是 **int**（陈在 精2 90 潜1 模组3 下是 825）⇒ 它会静默取 0，于是
// `value = dwell × 0` 恒为 0、**排序整个失效**，而表面上候选条数、dwell、visit 数
// 全是对的 —— 这正是最难发现的一类假绿（第一版就是这么写的，真跑一次才看见
// `value=0.0`）。照 `deploycost.go:21` 的口径：**类型不认识就报错，不兜底**。
func atkOf(st *OperatorStats) (float64, error) {
	v, ok := st.Total["atk"]
	if !ok {
		return 0, fmt.Errorf("面板 total 里没有 atk")
	}
	switch n := v.(type) {
	case int:
		return float64(n), nil
	case int64:
		return float64(n), nil
	case float64:
		return n, nil
	}
	return 0, fmt.Errorf("atk 的类型不认识：%T", v)
}

// CandidatesFor 给每个干员挑出最值钱的若干落位 × 朝向（`search.py:114`）。
//
// 关卡走 `level` 或合成关卡的 `path`（与 `arrivals`／`spots` 同口径）。
func CandidatesFor(level, path, difficulty string, q CandidatesQuery) (CandidatesOut, error) {
	out := CandidatesOut{Rows: []CandidateRow{},
		Params: map[string]any{"level": level, "path": path,
			"difficulty": difficulty, "per_op": q.PerOp,
			"operators": len(q.Operators)}}
	var st *Stage
	var err error
	if path != "" {
		st, err = loadStageFromFile(path, difficulty)
	} else {
		if level == "" {
			return out, fmt.Errorf("candidates 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
		}
		st, err = LoadStage(level)
	}
	if err != nil {
		return out, err
	}
	//: 名册：给了路径就必须读得动，读不动**具名失败**（空名册与「这个号一个干员
	//: 都没有」长得一模一样，而两者的处置完全不同）。
	var roster *core.RosterRead
	if q.Roster != "" {
		rr, rerr := core.ReadRoster(q.Roster)
		if rerr != nil {
			return out, fmt.Errorf("读名册 %s 失败：%w", q.Roster, rerr)
		}
		roster = &rr
	}
	byName := map[string]core.RosterEntry{}
	if roster != nil {
		for _, e := range roster.Entries {
			byName[e.Name] = e
		}
	}

	lib, err := LoadEnemyLibrary()
	if err != nil {
		return out, err
	}
	arrivals, _, err := EnemyArrivals(st, lib, q.SpeedScale, nil)
	if err != nil {
		return out, err
	}
	index := NewArrivalIndex(arrivals)

	//: 站位的候选池照 Python：`list(melee_spots) + list(ranged_spots)` ——
	//: **先地面后高台**，行主序。顺序影响平局取谁（见文件头）。
	cells := append(st.Map.MeleeSpots(), st.Map.RangedSpots()...)
	meleeSet := map[[2]int]bool{}
	for _, c := range st.Map.MeleeSpots() {
		meleeSet[c] = true
	}
	rangedSet := map[[2]int]bool{}
	for _, c := range st.Map.RangedSpots() {
		rangedSet[c] = true
	}
	rangeTbl, err := LoadRangeTable()
	if err != nil {
		return out, err
	}

	dirs := q.Directions
	if len(dirs) == 0 {
		dirs = SearchDirections
	}
	perOp := q.PerOp
	if perOp <= 0 {
		perOp = defaultPerOp
	}

	var stats CandidateStats
	all := []CandidateRow{}
	for _, name := range q.Operators {
		stats.Operators++
		entry, ok := byName[name]
		if !ok {
			stats.EntryMissing++
			continue
		}
		cid := entry.CharID
		if cid == "" {
			if v, ok := byNameCharID(name); ok {
				cid = v
			}
		}
		if cid == "" {
			stats.NoCharID++
			continue
		}
		//: 练度折算失败 ⇒ 照 Python 跳过这一位（那一侧是 `except: continue`）
		cfg := OperatorCalcConfig{CharID: cid, Elite: entry.Elite,
			Level: entry.Level, Potential: entry.Potential,
			ModuleLevel: entry.ModuleLevel}
		if entry.Module != nil {
			cfg.Module = *entry.Module
		}
		stt, err := OperatorStatsFor(cfg, "")
		if err != nil {
			stats.UnitFailed++
			continue
		}
		atk, err := atkOf(stt)
		if err != nil {
			//: 照 Python 的 `except: continue`（那边 `float(t["atk"])` 抛 KeyError）
			stats.AtkMissing++
			continue
		}

		melee, err := isMeleeChar(cid)
		if err != nil {
			stats.UnitFailed++
			continue
		}
		spots := rangedSet
		if melee {
			stats.MeleeOps++
			spots = meleeSet
		} else {
			stats.RangedOps++
		}

		code, err := operatorRangeCode(cid, entry.Elite)
		if err != nil {
			stats.UnitFailed++
			continue
		}
		base, ok := rangeTbl[code]
		if !ok {
			//: Python 那边 `_range_cells` 吞掉异常给空集合 ⇒ 这一位一个候选都没有
			stats.RangeMissing++
			continue
		}

		slot, mastery := 0, 0
		if v, ok := q.Skills[name]; ok {
			slot, mastery = v[0], v[1]
		}

		local := []CandidateRow{}
		for _, pos := range cells {
			if !spots[pos] {
				stats.NotInSpots++
				continue
			}
			stats.PositionsTried++
			for _, d := range dirs {
				fp, ferr := Footprint(base, d, pos[0], pos[1])
				if ferr != nil {
					continue
				}
				//: 去掉重复格（Python 的 frozenset —— 见文件头第 3 条）
				seen := map[[2]int]bool{}
				cs := make([][2]int, 0, len(fp))
				for _, c := range fp {
					cell := [2]int{c[0], c[1]}
					if seen[cell] {
						continue
					}
					seen[cell] = true
					cs = append(cs, cell)
				}
				if len(cs) == 0 {
					stats.EmptyRange++
					continue
				}
				dwell := index.Dwell(cs, negInf(), posInf())
				if dwell <= 0 {
					//: **几何上就接不到任何敌人** —— 剪掉的最多的一支
					stats.VisitsZero++
					continue
				}
				sort.Slice(cs, func(i, j int) bool {
					if cs[i][0] != cs[j][0] {
						return cs[i][0] < cs[j][0]
					}
					return cs[i][1] < cs[j][1]
				})
				local = append(local, CandidateRow{
					Operator: name, CharID: cid, Position: pos, Direction: d,
					Skill: slot, Mastery: mastery, Dwell: dwell,
					Visits: index.Count(cs, negInf(), posInf()),
					Value:  dwell * atk, Cells: cs,
				})
			}
		}
		stats.AllCandidates += len(local)
		//: 稳定排序（Python 的 `list.sort` 稳定 ⇒ 同价值保持插入序）
		sort.SliceStable(local, func(i, j int) bool { return local[i].Value > local[j].Value })
		//: 同一个站位的四个朝向只留最好的那个：站同一格换朝向不值得各试一遍
		seenPos := map[[2]int]bool{}
		kept := 0
		for _, c := range local {
			if seenPos[c.Position] {
				continue
			}
			seenPos[c.Position] = true
			all = append(all, c)
			kept++
			if kept >= perOp {
				break
			}
		}
		stats.Kept += kept
	}
	sort.SliceStable(all, func(i, j int) bool { return all[i].Value > all[j].Value })
	out.Rows = all
	out.Covered = stats
	return out, nil
}

// negInf / posInf 是 `dwell` 的缺省时间窗（Python 的 `-inf` / `inf`）。
func negInf() float64 { return math.Inf(-1) }

func posInf() float64 { return math.Inf(1) }
