// buildspec.go：**单一入口** —— 一次造齐 `build_spec` 的 19 个顶层键。
//
// ## 它做的事
//
// 19 个键在这之前**各自都有生产者**（骨架 12 ＋ `deploys`/`skill_uses` ＋ `spawns`
// ＋ `unsupported` ＋ `operators` ＋ `mechanisms`/`mech_config`），但**没有一个入口**
// 把它们按 `build_spec` 的样子串起来 —— 串起来这件事本身就是 `closeout_selfsufficiency.py`
// 收口条件①要的那个入口。
//
// 本文件**只做接线，不重算**：每个键都调它自己那一批已经过了对拍的函数。
// 复算第二份实现是这一路最贵的错法（两份必然有一天不一致，且不一致时两边都看着对）。
//
//	stage/fps/max_time/life/cost_*／enemy_windup/ranged_enemies/speed_scale
//	                          ← StageEnv（stageenv.go）
//	highland_cells             ← st.Map.HighlandCells()（**有门**，见下）
//	goal_cells                 ← st.Map.GoalCells()（**有门**，见下）
//	operators                  ← BuildOperatorsFor（operators.go）
//	deploys                    ← BuildDeploysFor（specdeploys.go）
//	spawns                     ← SpawnsOf（spawns.go）
//	skill_uses                 ← BuildSkillUses（specdeploys.go）
//	unsupported                ← UnsupportedGate（unsupported.go）
//	mechanisms/mech_config     ← MechSpecBuild（mechspec.go）
//
// ## 两道门（照 `spec.py:1273-1281`，**这一版接上了**）
//
//   - `highland_cells`：只有**某个干员带 `highland_splash_scale`（> 0）**时才送。
//     输入在 `operators` 那一份里（`OperatorOut.HighlandSplashScale`）⇒ 门接得上。
//   - `goal_cells`：只有**积雪机制在场**时才送。门写成 `mechanisms 含 snow.field`
//     —— 与权威同一句表达式，**在 Go 自己的 mechanisms 上求值**。
//
//     ⚠ 但 Go 的 `mechanisms` **判不出雪**（要 `find_snow`，见 mechspec.go 的
//     `unported`）⇒ 这道门在 Go 这一侧**恒为关**。于是「有雪的那几关」
//     `goal_cells` 会是 `[]` 而原版有值 —— 这个差**不是门没接**，是**雪的输入没有**，
//     所以它记在 `unported` 里并逐关计数，不记成「门未接」。
//     实测本仓夹具：24 份里 2 份带雪（`hsex8_max` / `plan-hs07`），而 `goal_cells`
//     非空的**恰好**也是那 2 份。
//
// `specgo.go` 的 `gatedKeys` 是**骨架**（`BuildSpecPart`）的口径：它不吃 operators，
// 那两个门它确实接不上，所以那边照旧登记；本入口的 `gated_keys` 是空的。
//
// ## 两处口径差（具名，不静默省略）
//
//   - `p3r_armed`（`spawns[].p3r_armed`）：原版是 `inp.total_attack is not None`，
//     要装置层。Go 没有 ⇒ 本入口传 `false`。实测缓存 55 关里 `total_attack`
//     **非 None 的有 0 关**，所以这个 false 在当前取证范围内与原版同值；
//     判据每次**现算**这个可达性，非 0 即红（那时本入口必须改成收这个输入）。
//   - 雪那一支（`mechanisms` / `mech_config` / `goal_cells` 三键），同上。
package main

import (
	"encoding/json"
	"fmt"
	"sort"

	"rios-sim/mech"
)

// BuildSpecQuery 是 `buildspec` 命令的 spec 体。
//
// `plan` / `roster` 给了才造 `operators` / `deploys` / `skill_uses` 里**有内容**的那几份；
// 键本身**永远在**（原版空排程给的是空列表，不是缺键）。
type BuildSpecQuery struct {
	Plan       string  `json:"plan,omitempty"`
	Roster     string  `json:"roster,omitempty"`
	Difficulty string  `json:"difficulty,omitempty"`
	MaxTime    float64 `json:"max_time,omitempty"`
	HealMode   string  `json:"heal_mode,omitempty"`
	//: 透传给闸门（`unsupported_reasons` 的两个口子）。对拍台用 `allow_devices=true`。
	AllowDevices bool `json:"allow_devices,omitempty"`
	AllowSkills  bool `json:"allow_skills,omitempty"`
}

// FullSpec 是 `build_spec` 的 19 个顶层键，**一个不多一个不少**。
//
// ⚠ **不许用 `omitempty`**：原版的空排程给的是 `[]`／`{}`，不是缺键。
// 「我没造这个键」与「这个键的值是空的」是两件事，压成一个值会让键集账失明
// （`specgo.go` 的 `SpecPart` 是**另一份契约**：那份是「我能造哪几个键」的账，
// 所以那边 `omitempty` 承担语义；两者不要互相抄）。
type FullSpec struct {
	Stage         string  `json:"stage"`
	FPS           int     `json:"fps"`
	MaxTime       float64 `json:"max_time"`
	Life          int     `json:"life"`
	CostInit      float64 `json:"cost_init"`
	CostMax       float64 `json:"cost_max"`
	CostTime      float64 `json:"cost_time"`
	EnemyWindup   float64 `json:"enemy_windup"`
	RangedEnemies bool    `json:"ranged_enemies"`
	SpeedScale    float64 `json:"speed_scale"`

	HighlandCells [][2]int `json:"highland_cells"`
	GoalCells     [][2]int `json:"goal_cells"`

	Operators []OperatorOut `json:"operators"`
	Deploys   []SpecDeploy  `json:"deploys"`
	//: `spawns` 每一条是 65 个键的 dict ⇒ 用 `any` 而不是再定义一遍结构
	//: （`spawns.go` 那份是权威，抄一遍就是第二份实现）。
	Spawns    []map[string]any `json:"spawns"`
	SkillUses []SpecSkillUse   `json:"skill_uses"`

	Unsupported []string `json:"unsupported"`

	Mechanisms []string                   `json:"mechanisms"`
	MechConfig map[string]json.RawMessage `json:"mech_config"`
}

// BuildSpecOut 是应答体：`spec` 就是那 19 个键，其余三槽是**这一趟的身份与口径**。
//
// ⚠ 那三个槽**不能塞进 `spec`**：`build_spec` 的键集是 Python 与 Go 之间的契约，
// 多一个键就是改了协议（`check_specgo_go.py` 拿 ast 从源文件核对这份键集）。
type BuildSpecOut struct {
	Spec FullSpec `json:"spec"`
	//: 这一版造不出／判不了的部分，具名（各生产者的 unported 并集，带来源前缀）。
	Unported []string `json:"unported"`
	//: 各生产者的行使计数并集（带来源前缀）。全 0 的那条线不是「通过」。
	Scanned map[string]int `json:"scanned"`
	//: 19 键里**实际没造出来**的（由真正序列化出来的键集算，不是照表抄）。
	MissingKeys []string `json:"missing_keys"`
	//: 产出但**本入口**没接上的门。接齐了两个 ⇒ 空表（对比 `specgo.go` 的 `gatedKeys`）。
	GatedKeys []string       `json:"gated_keys"`
	Params    map[string]any `json:"params"`
}

// buildSpecUnported 是本入口**自己**那两条口径差（各生产者的另计，带前缀并入）。
var buildSpecUnported = []string{
	//: `goal_cells` 的门是「mechanisms 含 snow.field」，而 Go 的 mechanisms 判不出雪
	//: ⇒ 这道门恒关。差的是**雪的输入**，不是门本身（见文件头）。
	"goal_cells：门（积雪在场）在 Go 侧恒关（雪判不出，见 mechspec 的 unported）",
	//: `spawns[].p3r_armed` 要 `total_attack is not None`（装置层）。实测缓存 55 关
	//: 里非 None 的 0 关 ⇒ 传 false 与原版同值；判据每次现算这个可达性。
	"spawns[].p3r_armed：total_attack 要装置层，Go 没有 ⇒ 恒传 false",
}

// ParseSpecRequest 解 `buildspec` 的 spec，并**拒绝不认识的键**。
//
// ⚠ 为什么不像别的命令那样直接 `json.Unmarshal` 进结构体：多出来的键会被
// **静默忽略**，而这里最要命的一种静默是 `plan` 拼错成 `plans`（或 `plan_path`）
// ——那会造出一份**没有 operators／deploys／skill_uses 内容**的规格，
// 而它看起来完全正常（键都在、值都是空的），判决照样给出来。
// 宁可当场具名失败。
func ParseSpecRequest(raw json.RawMessage) (BuildSpecQuery, error) {
	var q BuildSpecQuery
	if len(raw) == 0 {
		return q, nil
	}
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return q, fmt.Errorf("spec 不是对象：%v", err)
	}
	allowed := map[string]bool{
		"plan": true, "roster": true, "difficulty": true, "max_time": true,
		"heal_mode": true, "allow_devices": true, "allow_skills": true,
	}
	for k := range m {
		if !allowed[k] {
			return q, fmt.Errorf(
				"buildspec 不认识的 spec 键 %q（只收 plan／roster／difficulty／max_time／"+
					"heal_mode／allow_devices／allow_skills）。★ 拼错一个键会造出一份"+
					"内容全空的规格而看不出错", k)
		}
	}
	if r, ok := m["plan"]; ok {
		if err := json.Unmarshal(r, &q.Plan); err != nil {
			return q, fmt.Errorf("plan 不是字符串：%v", err)
		}
	}
	if r, ok := m["roster"]; ok {
		if err := json.Unmarshal(r, &q.Roster); err != nil {
			return q, fmt.Errorf("roster 不是字符串：%v", err)
		}
	}
	if r, ok := m["difficulty"]; ok {
		if err := json.Unmarshal(r, &q.Difficulty); err != nil {
			return q, fmt.Errorf("difficulty 不是字符串：%v", err)
		}
	}
	if r, ok := m["heal_mode"]; ok {
		if err := json.Unmarshal(r, &q.HealMode); err != nil {
			return q, fmt.Errorf("heal_mode 不是字符串：%v", err)
		}
	}
	if r, ok := m["max_time"]; ok {
		if err := json.Unmarshal(r, &q.MaxTime); err != nil {
			return q, fmt.Errorf("max_time 不是数：%v", err)
		}
	}
	if r, ok := m["allow_devices"]; ok {
		if err := json.Unmarshal(r, &q.AllowDevices); err != nil {
			return q, fmt.Errorf("allow_devices 不是布尔：%v", err)
		}
	}
	if r, ok := m["allow_skills"]; ok {
		if err := json.Unmarshal(r, &q.AllowSkills); err != nil {
			return q, fmt.Errorf("allow_skills 不是布尔：%v", err)
		}
	}
	return q, nil
}

// BuildSpecFull 是单一入口。
func BuildSpecFull(level, path string, q BuildSpecQuery) (BuildSpecOut, error) {
	out := BuildSpecOut{
		Spec: FullSpec{
			//: 空列表一律显式初始化：`nil` 会 marshal 成 `null`，而原版是 `[]`。
			HighlandCells: [][2]int{},
			GoalCells:     [][2]int{},
			Operators:     []OperatorOut{},
			Deploys:       []SpecDeploy{},
			Spawns:        []map[string]any{},
			SkillUses:     []SpecSkillUse{},
			Unsupported:   []string{},
			Mechanisms:    []string{},
			MechConfig:    map[string]json.RawMessage{},
		},
		Unported:    append([]string{}, buildSpecUnported...),
		Scanned:     map[string]int{},
		MissingKeys: []string{},
		GatedKeys:   []string{},
		Params: map[string]any{
			"level": level, "path": path, "plan": q.Plan, "roster": q.Roster,
			"difficulty": q.Difficulty, "max_time": q.MaxTime,
			"heal_mode": q.HealMode,
			"allow_devices": q.AllowDevices, "allow_skills": q.AllowSkills,
		},
	}
	st, _, err := loadStageWithRaw(level, path, q.Difficulty)
	if err != nil {
		return out, err
	}
	//: ⚠ 难度的兜底照原版那一句（`environment_difficulty or stage.difficulty or NORMAL`）。
	//: 写成恒 NORMAL 会让四星档关卡丢掉 `global_lifepoint` 的生命点改写
	//: ——`specgo.go:97-103` 记着这条是怎么被抓出来的。
	difficulty := q.Difficulty
	if difficulty == "" {
		difficulty = st.Difficulty
	}
	if difficulty == "" {
		difficulty = "NORMAL"
	}
	maxTime := q.MaxTime
	if maxTime == 0 {
		maxTime = 900.0
	}
	out.Params["difficulty"] = difficulty
	out.Params["max_time"] = maxTime

	// ---- 关卡静态 8 项 ----
	env := StageEnv(st.Options, st.Runes, difficulty)
	out.Spec.Stage = st.Code
	out.Spec.FPS = env.FPS
	out.Spec.MaxTime = maxTime
	out.Spec.Life = env.Life
	out.Spec.CostInit = env.CostInit
	out.Spec.CostMax = env.CostMax
	out.Spec.CostTime = env.CostTime
	out.Spec.EnemyWindup = env.EnemyWindup
	out.Spec.RangedEnemies = env.RangedEnemies
	out.Spec.SpeedScale = env.SpeedScale

	// ---- operators / deploys / skill_uses：有输入才有内容 ----
	if q.Plan != "" {
		bundle, err := BuildOperatorsFor(q.Plan, q.Roster, q.HealMode)
		if err != nil {
			return out, err
		}
		out.Spec.Operators = bundle.Operators
		out.Unported = append(out.Unported, prefixAll("operators", bundle.Unported)...)
		for k, v := range bundle.Covered {
			out.Scanned["operators."+k] = v
		}
		out.Scanned["operators.n"] = bundle.Scanned

		rows, err := BuildDeploysFor(q.Plan, q.Roster)
		if err != nil {
			return out, err
		}
		out.Spec.Deploys = rows

		plan, err := ReadPlan(q.Plan)
		if err != nil {
			return out, err
		}
		out.Spec.SkillUses = BuildSkillUses(plan)
		out.Scanned["deploys"] = len(rows)
		out.Scanned["skill_uses"] = len(out.Spec.SkillUses)
	}

	// ---- 两道门：highland_cells（有干员带高台溅射才送）----
	highlandOn := false
	for _, o := range out.Spec.Operators {
		if o.HighlandSplashScale != nil && *o.HighlandSplashScale > 0 {
			highlandOn = true
			break
		}
	}
	if highlandOn {
		out.Spec.HighlandCells = st.Map.HighlandCells()
		out.Scanned["gate_highland_open"] = 1
	} else {
		out.Scanned["gate_highland_open"] = 0
	}

	// ---- spawns ----
	//: `p3rArmed` 恒 false：见 `buildSpecUnported` 第二条（判据现算可达性）。
	sp, err := SpawnsOf(level, path, difficulty, false)
	if err != nil {
		return out, err
	}
	out.Spec.Spawns = sp.Spawns
	out.Unported = append(out.Unported, prefixAll("spawns", sp.Unported)...)
	for k, v := range sp.Scanned {
		out.Scanned["spawns."+k] = v
	}

	// ---- unsupported ----
	gate, err := UnsupportedGate(level, path, GateQuery{
		Plan: q.Plan, Difficulty: difficulty,
		AllowDevices: q.AllowDevices, AllowSkills: q.AllowSkills,
	})
	if err != nil {
		return out, err
	}
	out.Spec.Unsupported = gate.Reasons
	out.Unported = append(out.Unported, prefixAll("unsupported", gate.Unported)...)
	for k, v := range gate.Scanned {
		out.Scanned["unsupported."+k] = v
	}

	// ---- mechanisms / mech_config ----
	m, err := MechSpecBuild(level, path, MechQuery{Difficulty: difficulty})
	if err != nil {
		return out, err
	}
	out.Spec.Mechanisms = m.Mechanisms
	out.Spec.MechConfig = m.MechConfig
	out.Unported = append(out.Unported, prefixAll("mechspec", m.Unported)...)
	for k, v := range m.Scanned {
		out.Scanned["mechspec."+k] = v
	}

	// ---- goal_cells 的门：与权威同一句表达式，在 Go 自己的 mechanisms 上求值 ----
	if containsStr(out.Spec.Mechanisms, string(mech.SnowID)) {
		out.Spec.GoalCells = st.Map.GoalCells()
		out.Scanned["gate_goal_open"] = 1
	} else {
		out.Scanned["gate_goal_open"] = 0
	}

	// ---- 键集自检：拿**真正序列化出来的**键集跟契约比 ----
	missing, err := fullSpecMissingKeys(out.Spec)
	if err != nil {
		return out, err
	}
	out.MissingKeys = missing
	return out, nil
}

// fullSpecMissingKeys 把 `FullSpec` 序列化一次，用**真实键集**跟 `specKeysAll` 比。
//
// 为什么不照 `specKeysProduced` 那张表抄一遍：那张表说的是「我打算造哪几个键」，
// 而这里要的是「我**造出来的 JSON** 里真有哪几个键」。写错一个 json tag
// （拼错、忘了去 omitempty、字段名重复）只有真序列化一次才看得见——
// 而它的症状恰好是「键集账说我造了、消费者读不到」。
func fullSpecMissingKeys(s FullSpec) ([]string, error) {
	raw, err := json.Marshal(s)
	if err != nil {
		return nil, fmt.Errorf("规格序列化失败：%v", err)
	}
	var got map[string]json.RawMessage
	if err := json.Unmarshal(raw, &got); err != nil {
		return nil, fmt.Errorf("规格反序列化失败：%v", err)
	}
	missing := []string{}
	for _, k := range specKeysAll {
		if _, ok := got[k]; !ok {
			missing = append(missing, k)
		}
	}
	//: 反向也要查：**多出来的键**同样是改了协议（原版没有这个键）。
	known := map[string]bool{}
	for _, k := range specKeysAll {
		known[k] = true
	}
	extra := []string{}
	for k := range got {
		if !known[k] {
			extra = append(extra, k)
		}
	}
	if len(extra) > 0 {
		sort.Strings(extra)
		return nil, fmt.Errorf(
			"规格里多出了契约之外的键 %s —— `build_spec` 的键集是协议，多一个就是改了协议",
			extra)
	}
	sort.Strings(missing)
	return missing, nil
}

func prefixAll(prefix string, items []string) []string {
	out := make([]string, 0, len(items))
	for _, s := range items {
		out = append(out, prefix+": "+s)
	}
	return out
}

func containsStr(list []string, want string) bool {
	for _, s := range list {
		if s == want {
			return true
		}
	}
	return false
}
