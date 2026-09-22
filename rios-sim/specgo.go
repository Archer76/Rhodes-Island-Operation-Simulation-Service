package main

import "sort"

// specgo.go：**Go 自己造规格**的第一份可执行骨架（丙阶段四·第十八批）。
//
// ## 它现在是什么
//
// `build_spec`（`simgo/spec.py:1161-1291`）返回 **19 个顶层键**。前两批把其中
// **12 个**做到了「不依赖 sim／干员／机制」就能算出来，这一批把它们**装配**起来，
// 并让这份骨架**自己报出还差哪 7 个键**。
//
// 为什么要在只有一半的时候先装配：键名、类型、单位是 Python 与 Go 之间的契约，
// 分开造完再拼最容易出的错是**名字对不上而两边都不报**。先拼一次、让判据把
// 「键集 == 源文件里的键集」当成断言，后面每落一个键就少一个缺项，红绿自己会说话。
//
// ## 「19」不是我数出来的
//
// `MissingKeys` 由下面 `specKeysProduced` 与 `specKeysAll` 两张表的差算出来，
// 而 `specKeysAll` 的判据是**从 `spec.py` 的 `build_spec` 返回字面量里用 ast
// 抽出来的**（见 `tools/check_specgo_go.py`）。所以上游哪天加了一个键，
// 判据会先红——而不是等到某次对拍发现少送了一个字段。
//
// ## 一处**没有**跟着搬的判据
//
// `goal_cells` 与 `highland_cells` 在原版里是**有条件的**：前者只有积雪机制在场
// 才送、后者只有某个干员带 `highland_splash_scale` 才送（见 `spec.py:1273-1281`）。
// 那两条门要机制层与干员层，本轮都没有——所以这里**无条件**产出，
// 并在 `gatedKeys` 里具名登记「这两个键的门还没接」。空的 `goal_cells` 与
// 「这一关没有防守点格」在原版里长得一样，所以这个差异必须写在明面上。

// specKeysProduced 是这份骨架**已经能算出**的键（顺序照 `build_spec` 的书写顺序）。
var specKeysProduced = []string{
	"stage", "fps", "max_time", "life", "cost_init", "cost_max", "cost_time",
	"enemy_windup", "ranged_enemies", "speed_scale", "highland_cells",
	"goal_cells",
}

// specKeysAll 是 `build_spec` 返回的**全部**顶层键。
// ⚠ 手抄自 `spec.py:1255-1291`，并由判据拿 ast 从源文件里核对。
var specKeysAll = []string{
	"stage", "fps", "max_time", "life", "cost_init", "cost_max", "cost_time",
	"enemy_windup", "ranged_enemies", "speed_scale", "highland_cells",
	"goal_cells", "operators", "deploys", "spawns", "skill_uses",
	"unsupported", "mechanisms", "mech_config",
}

// gatedKeys 是**已经产出、但原版那道门还没接**的键。
var gatedKeys = []string{"highland_cells", "goal_cells"}

// SpecPart 是 Go 现在能造出的那部分规格。
type SpecPart struct {
	Stage     string     `json:"stage"`
	FPS       int        `json:"fps"`
	MaxTime   float64    `json:"max_time"`
	Life      int        `json:"life"`
	CostInit  float64    `json:"cost_init"`
	CostMax   float64    `json:"cost_max"`
	CostTime  float64    `json:"cost_time"`
	EnemyWindup   float64 `json:"enemy_windup"`
	RangedEnemies bool    `json:"ranged_enemies"`
	SpeedScale    float64 `json:"speed_scale"`

	HighlandCells [][2]int `json:"highland_cells"`
	GoalCells     [][2]int `json:"goal_cells"`

	//: 19 个键里 Go **还造不出**的（判据会拿它跟 `spec.py` 的返回字面量对账）。
	MissingKeys []string `json:"missing_keys"`
	//: 产出但原版的门未接的键，见 `gatedKeys`。
	GatedKeys []string `json:"gated_keys"`
	//: 本次用的难度档（`environment_difficulty`）。
	Difficulty string `json:"difficulty"`
}

// BuildSpecPart 造这一份骨架。
//
// `maxTime` 传 0 时取 **900**：原版那句是
// `float(getattr(inp, "max_time", 0.0) or 900.0)`，而 900 就是验证那一路
// （`verifier.py:93` 与 `verify.py:410`）实际调 `sim.run` 用的值。
// ⚠ 不能写死 600：`BattleSimulator.run` 的 600 只是默认值，写死会让
// 「打到 814 秒才赢」的作业在 Go 侧被截断，判决从胜利变成超时。
func BuildSpecPart(level, difficulty string, maxTime float64) (SpecPart, error) {
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	st, err := LoadStage(level)
	if err != nil {
		return SpecPart{}, err
	}
	env := StageEnv(st.Options, st.Runes, difficulty)
	if maxTime == 0 {
		maxTime = 900.0
	}
	missing := []string{}
	produced := map[string]bool{}
	for _, k := range specKeysProduced {
		produced[k] = true
	}
	for _, k := range specKeysAll {
		if !produced[k] {
			missing = append(missing, k)
		}
	}
	gated := append([]string{}, gatedKeys...)
	sort.Strings(gated)
	return SpecPart{
		Stage:         st.Code,
		FPS:           env.FPS,
		MaxTime:       maxTime,
		Life:          env.Life,
		CostInit:      env.CostInit,
		CostMax:       env.CostMax,
		CostTime:      env.CostTime,
		EnemyWindup:   env.EnemyWindup,
		RangedEnemies: env.RangedEnemies,
		SpeedScale:    env.SpeedScale,
		HighlandCells: st.Map.HighlandCells(),
		GoalCells:     st.Map.GoalCells(),
		MissingKeys:   missing,
		GatedKeys:     gated,
		Difficulty:    difficulty,
	}, nil
}
