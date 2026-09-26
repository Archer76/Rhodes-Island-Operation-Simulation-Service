package main

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
)

// stageenv.go：构建规格要用的**关卡静态 8 项**（丙阶段四·第十六批）。
//
// ## 为什么从这 8 项开刀
//
// `build_spec`（`simgo/spec.py:1161-1291`，131 行）是整个「Go 自己构造规格」
// 的入口，1291 行的 `spec.py` 里它要凑齐 **19 个顶层键**。一次搬完不现实，
// 所以按**依赖**切：哪些键不依赖 sim 状态、不依赖干员、不依赖机制？
//
// 这 8 项就是答案——它们只吃**关卡文件**（`options` ＋ `runes`），
// 而 Go 的 `StageOptions` 早就在读了，只差 `runes` 没留。
//
// 权威是 `ak_tactic/frontend/stage_env.py:68-102` 的 `stage_env`，
// 加上它的两个下游 `stage_mul.py` 的 `global_lifepoint` / `cost_recovery_scale`
// 与 `blackboard.py` 的三个取值原语。
//
// ## 两处必须照抄的「0 与 None 一视同仁」
//
// 原版到处写 `or`（`or 1.0` / `or 99.0` / `or 0.0`），于是一个**显式的 0**
// 会被换成缺省值。改成 `is None` 判断会在 `max_cost: 0` 这类取值上分叉，
// 而现有计划覆盖不到——所以下面每一处 `or` 都照抄成「等于零就取缺省」。
//
// ## 两条只改「每点费用几秒」与「生命点」的 rune
//
// * `cbuff_cost_recovery.scale`（四星档常见 2）——它改的是**每点费用几秒**，
//   所以要**除**。乘除弄反不会有任何判据报警，只会让费用回得快或慢。
// * `global_lifepoint.value`（八关 EX 的四星档都改成 1，而关卡文件自己写的
//   是 3、普通与四星**两份都是 3**）——不接这条，四星档凭空多两条命。
//
// ★ 而这两条**只在非 NORMAL 难度下**才与普通档不同，当前流水线恒为 NORMAL
// ⇒ 那是**沉默区**：重写出错没有任何判据会响。所以这里也是「原样搬」。

// BlackboardEntry 是 rune 黑板上的一条。数值住 `value`、字符串住 `valueStr`
// ——`bb_number` 只认前者（本项目记录在案的一次真错：只读 `valueStr` 会得出
// 「五个参数全是 None」，进而误判「环境系统不在 gamedata 里」）。
type BlackboardEntry struct {
	Key      string          `json:"key"`
	Value    json.RawMessage `json:"value"`
	ValueStr string          `json:"value_str,omitempty"`
}

// Rune 是一条关卡 rune。
type Rune struct {
	Key            string            `json:"key"`
	DifficultyMask *string           `json:"difficulty_mask"`
	Blackboard     []BlackboardEntry `json:"blackboard"`
}

func parseRunes(raw json.RawMessage) ([]Rune, error) {
	if len(raw) == 0 {
		return nil, nil
	}
	var arr []struct {
		Key            string  `json:"key"`
		DifficultyMask *string `json:"difficultyMask"`
		Blackboard     []struct {
			Key      string          `json:"key"`
			Value    json.RawMessage `json:"value"`
			ValueStr string          `json:"valueStr"`
		} `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &arr); err != nil {
		return nil, fmt.Errorf("runes 不是数组：%v", err)
	}
	out := make([]Rune, 0, len(arr))
	for _, r := range arr {
		rn := Rune{Key: r.Key, DifficultyMask: r.DifficultyMask}
		for _, b := range r.Blackboard {
			rn.Blackboard = append(rn.Blackboard, BlackboardEntry{
				Key: b.Key, Value: b.Value, ValueStr: b.ValueStr})
		}
		out = append(out, rn)
	}
	return out, nil
}

// maskApplies 复刻 `blackboard.py:42-47`。
//
// `ALL` 必须认——`act31side_08` 用的就是它，不认则整条环境系统静默消失。
func maskApplies(mask *string, difficulty string) bool {
	if mask == nil {
		return true
	}
	m := *mask
	return m == "ALL" || m == "" || m == difficulty
}

// findRune 复刻 `blackboard.py:50-63`。
//
// 遍历**全部**、命中就覆盖 ⇒ 同键同难度有多条时取**最后一条**。
// 「禁止取第一条」的来由：`act31side_ex08` 的 `env_system_new` 有 NORMAL 与
// FOUR_STAR 两条，黑板数值相同但 `init_pollut_value` 不同（`1,1:0` vs
// `4,4:100`）——取错了不报错，只是污染点画在了别处。
func findRune(runes []Rune, key, difficulty string) *Rune {
	var hit *Rune
	for i := range runes {
		if runes[i].Key == key && maskApplies(runes[i].DifficultyMask, difficulty) {
			hit = &runes[i]
		}
	}
	return hit
}

// bbNumber 复刻 `blackboard.py:66-78`：取**第一条**同键且值是数的条目。
func bbNumber(entries []BlackboardEntry, key string) *float64 {
	for _, e := range entries {
		if e.Key != key {
			continue
		}
		if len(e.Value) == 0 {
			return nil
		}
		var f float64
		if err := json.Unmarshal(e.Value, &f); err != nil {
			return nil
		}
		return &f
	}
	return nil
}

// globalLifepoint 复刻 `stage_mul.py:222-231`。老键名 `gbuff_lifepoint` 同样认。
func globalLifepoint(runes []Rune, difficulty string) *int {
	r := findRune(runes, "global_lifepoint", difficulty)
	if r == nil {
		r = findRune(runes, "gbuff_lifepoint", difficulty)
	}
	if r == nil {
		return nil
	}
	v := bbNumber(r.Blackboard, "value")
	if v == nil {
		return nil
	}
	n := int(*v)
	return &n
}

// costRecoveryScale 复刻 `stage_mul.py:234-246`：没有就是 1.0。
//
// ⚠ 末尾那句原版是 `float(v) if v else 1.0`——**取到的 0 也当「没有」**。
func costRecoveryScale(runes []Rune, difficulty string) float64 {
	r := findRune(runes, "cbuff_cost_recovery", difficulty)
	if r == nil {
		return 1.0
	}
	v := bbNumber(r.Blackboard, "scale")
	if v == nil || *v == 0 {
		return 1.0
	}
	return *v
}

// StageEnvOut 就是规格里那 8 个字段。
type StageEnvOut struct {
	FPS           int     `json:"fps"`
	SpeedScale    float64 `json:"speed_scale"`
	RangedEnemies bool    `json:"ranged_enemies"`
	EnemyWindup   float64 `json:"enemy_windup"`
	CostInit      float64 `json:"cost_init"`
	CostMax       float64 `json:"cost_max"`
	CostTime      float64 `json:"cost_time"`
	Life          int     `json:"life"`
}

// 后四个是 `BattleSimulator.__init__`（`sim.py:324-330`）的构造参数缺省值。
// 不传 switches 那条常见路径得到的就是这几个数。
const (
	stageEnvFPS           = 30
	stageEnvSpeedScale    = 1.0
	stageEnvRangedEnemies = true
	stageEnvEnemyWindup   = 0.5
)

// StageEnv 复刻 `stage_env.py:68-102`。
func StageEnv(opts StageOptions, runes []Rune, difficulty string) StageEnvOut {
	//: 每一处 `or` 都照抄成「等于零就取缺省」——显式 0 与缺省在这个口径下同义。
	moveMul := opts.MoveMultiplier
	if moveMul == 0 {
		moveMul = 1.0
	}
	costInit := opts.InitialCost //: 原版 `or 0.0`，取缺省也是 0，恒等
	costMax := opts.MaxCost
	if costMax == 0 {
		costMax = 99.0
	}
	costTime := opts.CostIncreaseTime
	if costTime == 0 {
		costTime = 1.0
	}
	life := opts.MaxLifePoint
	if life == 0 {
		life = 1
	}

	out := StageEnvOut{
		FPS:           stageEnvFPS,
		SpeedScale:    stageEnvSpeedScale * moveMul,
		RangedEnemies: stageEnvRangedEnemies,
		EnemyWindup:   math.Max(0.0, stageEnvEnemyWindup),
		CostInit:      costInit,
		CostMax:       costMax,
		CostTime:      costTime,
		Life:          life,
	}
	//: ⚠ `if scale and scale != 1.0` ——倍率为 0 时**不除**（那是「没有」）。
	if s := costRecoveryScale(runes, difficulty); s != 0 && s != 1.0 {
		out.CostTime = costTime / s
	}
	if lp := globalLifepoint(runes, difficulty); lp != nil {
		out.Life = *lp
	}
	return out
}

// LoadStageEnv 取一关的静态 8 项。
func LoadStageEnv(level, difficulty string) (StageEnvOut, error) {
	st, err := LoadStage(level)
	if err != nil {
		return StageEnvOut{}, err
	}
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	return StageEnv(st.Options, st.Runes, difficulty), nil
}

// LoadStageEnvFile 同一个口径，但吃**一个关卡 JSON 文件路径**。
//
// 为什么要这条入口：判据要拿**合成关卡**把「显式 0 与缺省同义」那几条钉住
// （`max_cost: 0` → 99.0 之类），而合成关卡不在关卡索引里、`LoadStage` 找不到。
// 只解析 `options` 与 `runes` 两项，不走整份 `Stage` 的构造。
func LoadStageEnvFile(path, difficulty string) (StageEnvOut, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return StageEnvOut{}, fmt.Errorf("关卡读不出来：%v", err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return StageEnvOut{}, fmt.Errorf("关卡不是合法 JSON：%v", err)
	}
	opts, err := parseOptions(raw["options"])
	if err != nil {
		return StageEnvOut{}, fmt.Errorf("options：%w", err)
	}
	runes, err := parseRunes(raw["runes"])
	if err != nil {
		return StageEnvOut{}, fmt.Errorf("runes：%w", err)
	}
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	return StageEnv(opts, runes, difficulty), nil
}
