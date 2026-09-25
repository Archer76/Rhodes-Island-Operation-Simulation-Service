package main

// stagemul.go：关卡 `runes` 里的**敌人修饰层**（`ak_tactic/frontend/stage_mul.py`）。
//
// ## 为什么它必须在这里
//
// `spawns` 的数值全部来自「取敌人属性」这一出口。而原版那个出口是**包过的**：
// `sim.py:402-411` 在构造时做 `parse_rune_muls(...)` ＋ `wrap_enemy_at(...)`，
// 于是每一个出库的 `EnemyStats` 都过一遍难度乘数。`spec.py` 拿的正是那个包过的
// `enemy_at`（`SpecInputs.from_sim` 从模拟器上抄）。
//
// ⚠ **不接它的后果不是「覆盖率差一点」，是算错**：四星档会以**普通档属性**
// 进规格，而模拟照常给出判决。实测：`plan-hsex08f.json`（`act31side_ex08#f#`，
// `Stage.difficulty='FOUR_STAR'`）的 `spawns[i].{atk,def,hp}` 每一处**少乘一个 ×1.2**。
// 这条是 `frontend/inputs.py:264-287` 自己写下来的教训。
//
// ## 三条 rune，Go 现在三条都搬了（2026-09-26 补齐后两条）
//
// | rune | 作用 | Go |
// |---|---|---|
// | `enemy_attribute_mul` | 属性乘数（`atk` / `def` / `max_hp`），可点名敌人 | **已搬**（本文件 `ApplyAttrMuls`） |
// | `enemy_talent_blackb_mul` | 天赋黑板乘数，乘完还要**重跑派生**（`derive_blackboard_fields`） | **已搬**（`stagemul_bb.go` `ApplyBBMuls`） |
// | `enemy_skill_blackb_mul` | 技能黑板乘数，同上，另按 `prefabKey` 点名技能 | **已搬**（同上，技能支） |
//
// ★ 后两条**不是**「忽略就好」：黑板乘完不重跑派生，乘数会落在**一张没人再读的表**上
// （`stage_mul.py` 开头第 2 条写的就是这个）。在补齐之前，本文件的选择是**具名拒跑**
// 而不是静默按普通档算——「静默跑出另一场战斗」正是这一层存在的理由。
// 补齐之后拒跑撤销，但那条守卫**换了形状留下**（行使计数器 ＋ 反例守卫），
// 详见 `stagemul_bb.go` 的文件头与本目录 `spawns.go::statsFor`。
//
// ⚠ 老键名（`ebuff_attribute`）要认：`main_01-07`（1-7）的四星档用的就是那一套，
// 结构与新名一模一样。

import (
	"encoding/json"
	"fmt"
	"strconv"
	"strings"
)

const (
	attrMulKey   = "enemy_attribute_mul"
	talentMulKey = "enemy_talent_blackb_mul"
	skillMulKey  = "enemy_skill_blackb_mul"
)

// runeMulAliases 是**同一机制的两代键名**（`stage_mul.py:60-63`）。
// 键名归一化到新名；不认老名字的后果是那条乘数整条消失。
var runeMulAliases = map[string]string{
	"ebuff_attribute": attrMulKey,
}

// runeAttrFields 是 `enemy_attribute_mul` 的黑板键 → `EnemyStats` 上的字段名。
//
// 黑板用数据侧的 `def`，类里叫 `defense`；别的同名。**表里没有的键**一律记进
// `RuneMul.Unknown`，不静默丢弃——上游加了新属性（比如 `move_speed`）时报告里能看见。
var runeAttrFields = map[string]string{
	"atk":    "atk",
	"def":    "defense",
	"max_hp": "max_hp",
}

// RuneMul 是一条乘数 rune 解析后的样子（`stage_mul.py:80-100` 的 `RuneMul`）。
type RuneMul struct {
	//: `attr` / `talent` / `skill`
	Kind string
	//: 点名了哪些敌人（空 = 该关全部敌人）
	Enemies map[string]bool
	//: 点名了哪个技能（仅 `skill` 类）
	Skill string
	//: 键 → 系数
	Factors map[string]float64
	//: 表里没有的键（属性类才有）——非空即上游加了新属性
	Unknown []string
}

// runeBBPairs 复刻 `_bb_pairs`：数值在 `value`、文本在 `valueStr`，
// 判据是「`valueStr` **非空**才用它」（写成 `is not None` 会让空串顶掉真数值）。
func runeBBPairs(r Rune) [][2]any {
	out := [][2]any{}
	for _, b := range r.Blackboard {
		if b.Key == "" {
			continue
		}
		if strings.TrimSpace(b.ValueStr) != "" {
			out = append(out, [2]any{b.Key, b.ValueStr})
			continue
		}
		var v any
		if len(b.Value) > 0 {
			_ = json.Unmarshal(b.Value, &v)
		}
		out = append(out, [2]any{b.Key, v})
	}
	return out
}

// bbToFloat 复刻 Python 的 `float(raw)`（含它接受数字串这一点）。
func bbToFloat(v any) (float64, bool) {
	switch n := v.(type) {
	case float64:
		return n, true
	case int:
		return float64(n), true
	case string:
		f, err := strconv.ParseFloat(strings.TrimSpace(n), 64)
		if err != nil {
			return 0, false
		}
		return f, true
	}
	return 0, false
}

func bbToStr(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	if v == nil {
		return ""
	}
	return fmt.Sprint(v)
}

// parseOneRuneMul 复刻 `_parse_one`：把一条 rune 的黑板拆成「选择器 ＋ 系数表」。
func parseOneRuneMul(r Rune, kind string) *RuneMul {
	m := &RuneMul{Kind: kind, Enemies: map[string]bool{},
		Factors: map[string]float64{}}
	for _, kv := range runeBBPairs(r) {
		key, raw := kv[0].(string), kv[1]
		if key == "enemy" {
			for _, x := range strings.Split(bbToStr(raw), "|") {
				x = strings.TrimSpace(x)
				if x != "" {
					m.Enemies[x] = true
				}
			}
			continue
		}
		if key == "skill" {
			m.Skill = strings.TrimSpace(bbToStr(raw))
			continue
		}
		f, ok := bbToFloat(raw)
		if !ok {
			m.Unknown = append(m.Unknown, key)
			continue
		}
		m.Factors[key] = f
		if kind == "attr" {
			if _, known := runeAttrFields[key]; !known {
				m.Unknown = append(m.Unknown, key)
			}
		}
	}
	if len(m.Factors) == 0 {
		return nil
	}
	return m
}

// ParseRuneMuls 复刻 `parse_rune_muls`：把关卡 `runes` 里的乘数 rune 按难度解析出来。
//
// ⚠ 返回**列表**而不是单条：同一个键可能有多条（全局条 ＋ 点名条），
// `find_rune` 那种「取最后一条」会把全局那条整个吃掉（`act31side_ex02` 就是这么用的）。
func ParseRuneMuls(runes []Rune, difficulty string) []RuneMul {
	out := []RuneMul{}
	for _, r := range runes {
		key := r.Key
		if a, ok := runeMulAliases[key]; ok {
			key = a
		}
		var kind string
		switch key {
		case attrMulKey:
			kind = "attr"
		case talentMulKey:
			kind = "talent"
		case skillMulKey:
			kind = "skill"
		default:
			continue
		}
		if !maskApplies(r.DifficultyMask, difficulty) {
			continue
		}
		if one := parseOneRuneMul(r, kind); one != nil {
			out = append(out, *one)
		}
	}
	return out
}

// ★ 2026-09-26：`UnportedRuneMuls` 已**退休**（函数删除，不是注释掉）。
//
// 它当初只有一个用途：挑出 talent / skill 两类乘数，让 `spawns` 据此**具名拒跑**。
// 那两支现在已在 `stagemul_bb.go` 实现（`ApplyBBMuls`），拒跑失去对象。
// **留一条痕迹在这里**，是为了让「`spawns.go` 里那段拒跑代码哪去了」这个问题
// 有一个可查的答案——撤掉的是**守卫的实现方式**，不是**守卫本身**：
// 顶替它的是行使计数器 ＋ `check_spawns_go.py` 的反例守卫（Go 必须真的乘上、
// 且派生字段必须跟着变）。两者的差别写清了：拒跑是**静态**的「我做不到」，
// 计数器与反例守卫是**运行期**的「我做了没有、做对了没有」。

// ApplyAttrMuls 复刻 `apply_rune_muls` 的 **attr 那一支**。
//
// 两条纪律（`stage_mul.py` 开头）：
//
//  1. **不许改到库里的对象**——`EnemyLibrary` 是按敌人全库缓存的，乘数是按关生效的；
//     所以命中任何一条时才 `Clone()`（没命中就原样返回同一个指针，零拷贝）。
//  2. **没这个属性就不凭空造一个 0**（`if cur is None: continue`）。
func ApplyAttrMuls(es *EnemyStats, muls []RuneMul) *EnemyStats {
	out := es
	for _, m := range muls {
		if len(m.Enemies) > 0 && !m.Enemies[es.EnemyID] {
			continue
		}
		if out == es {
			out = es.Clone()
		}
		if m.Kind != "attr" {
			continue //: 另两类由调用方在更早处拒跑
		}
		for key, factor := range m.Factors {
			fname, known := runeAttrFields[key]
			if !known {
				continue //: 上游加了个新属性：记在 Unknown 里，不在这里崩
			}
			scale := func(p *float64) *float64 {
				if p == nil {
					return nil
				}
				v := *p * factor
				return &v
			}
			switch fname {
			case "atk":
				out.Atk = scale(out.Atk)
			case "defense":
				out.Defense = scale(out.Defense)
			case "max_hp":
				out.MaxHP = scale(out.MaxHP)
			}
		}
	}
	return out
}
