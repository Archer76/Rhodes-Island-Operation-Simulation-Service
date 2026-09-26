package main

// classify.go：技能黑板的**分类表**（丙阶段四·第五批）。
//
// 对应 `operator/skill.py` 的四张表与三个正则：
//
//	BUFF_KEYS    :772-791   面板增益（比例 / 绝对值在第二位标明）
//	DAMAGE_KEYS  :794-817   「这一次攻击怎么打」的量
//	CONTROL_KEYS :838-841   施加的控制效果，**值是持续时间（秒）**
//	_FLIGHT_KEYS :826-830   起飞/降落的**演出参数**（本身不进战斗结算）
//	_SUFFIX_RE / _INFIX_RE / _VARIANT_RE :845-869
//
// ## 本轮**只做查表与拆变体**，不做 `_classify` 的降级序列
//
// `_classify`（`:880`）在查表之前还有一段**降级**：原样 → 去 `xxx@` 前缀 →
// 去 `_s2`/`_2` 尾巴 → 去夹在 `@` 后面的技能槽标记。那一段**本轮未接**，
// 判据也只比「表里有没有这个名字」与「变体拆得对不对」——两件都已确定的事，
// 不把没读全的东西混进来。
//
// ## 两张表的量纲不是一回事
//
// 增益是**比例**（0.5 = +50%）还是**绝对值**，住在第二个字段里；
// 而 `CONTROL_KEYS` 的值是**秒**（量纲写 `sec`）。混用会让 10 秒的晕眩变成 +1000%。

import (
	"regexp"
	"strings"
)

// BUFF_KEYS 复刻 `skill.py:772-791`。
var BUFF_KEYS = map[string][2]string{
	"atk":                                 {"atk", "pct"},
	"atk_base":                            {"atk", "pct"},
	"attack@atk":                          {"atk", "pct"},
	"def":                                 {"def", "pct"},
	"max_hp":                              {"max_hp", "pct"},
	"magic_resistance":                    {"res", "flat"},
	"attack_speed":                        {"attack_speed", "flat"},
	"base_attack_time":                    {"attack_interval", "flat_sec"},
	"cost":                                {"cost", "flat"},
	"block_cnt":                           {"block_cnt", "flat"},
	"def_penetrate":                       {"def_penetrate", "pct"},
	"def_penetrate_fixed":                 {"def_penetrate_fixed", "flat"},
	"magic_resist_penetrate":              {"res_penetrate", "pct"},
	"magic_resist_penetrate_fixed":        {"res_penetrate_fixed", "flat"},
	"damage_resistance":                   {"damage_resistance", "pct"},
	"move_speed":                          {"move_speed", "pct"},
	"taunt_level":                         {"taunt_level", "flat"},
	"hp_recovery_per_sec_by_max_hp_ratio": {"hp_regen_pct", "pct"},
}

// DAMAGE_KEYS 复刻 `skill.py:794-817`。
var DAMAGE_KEYS = map[string]string{
	"atk_scale":             "atk_scale",
	"attack@atk_scale":      "atk_scale",
	"atk_scale_2":           "atk_scale_2",
	"damage_scale":          "damage_scale",
	"times":                 "times",
	"attack@times":          "times",
	"max_target":            "max_target",
	"attack@max_target":     "max_target",
	"heal_scale":            "heal_scale",
	"attack@heal_scale":     "heal_scale",
	"attack@trigger_time":   "ammo",
	"attack@atk_scale_loop": "atk_scale",
	"attack@atk_scale_end":  "atk_scale_end",
	//: 裸的 `trigger_time` 有 320 处，绝大多数是「触发间隔」；统一归 ammo，
	//: 再由 `_parse_effects` 按 `durationType` 退回去——判据只有一个。
	"trigger_time": "ammo",
}

// CONTROL_KEYS 复刻 `skill.py:838-841`。**值是持续时间（秒）。**
//
// ⚠ 黑板分不出这些控制打在敌人身上还是自己身上（阿米娅「精神爆发」的
// `stun 10` 是**自晕**）。用之前必须看描述。
var CONTROL_KEYS = []string{
	"stun", "sluggish", "sleep", "levitate", "bind", "cold", "frozen",
	"silence", "fear", "unmovable",
}

// FLIGHT_KEYS 复刻 `skill.py:826-830`。**演出参数，本身不进战斗结算。**
var FLIGHT_KEYS = map[string]string{
	"fly_height":       "airborne_height",
	"fly_duration":     "airborne_rise",
	"fly_end_duration": "airborne_fall",
}

// SplitVariant 复刻 `_split_variant`（`skill.py:872-877`）与 `_VARIANT_RE`。
//
// 只认「方括号后面**跟着 `.属性名`**」的形态：`headb2_s_2[second].atk`。
// `weak[limit]`、`ep_damage_ratio[trigger]` 这类是把方括号当限定词整体用的，
// **不适用本条**，别一起吞了。
//
// ★ **双括号键要取「紧贴 `.属性名` 的那一个」**，不是第一个。
// Python 的 `^(?P<head>.*?)\[(?P<variant>[^\]]+)\]\.(?P<attr>[^.]+)$` 里
// `head` 是**懒惰**的：它从最小的 head 开始试，`[withdraw]` 后面跟的是 `[`
// 而不是 `.`，于是继续展开 head，直到 `[combo].respawn_time` 这段匹配上。
// 所以 `nearl2_s_2[withdraw][combo].respawn_time` 的变体是 **`combo`**，
// 去掉变体后是 `respawn_time`。
//
// 第一版取的是**第一个** `[`，于是在全表 **192 个带变体的键**里有 11 个判错
// ——判据当场照出来了（1045/1056）。
func SplitVariant(key string) (string, string, bool) {
	for i := 0; i < len(key); i++ {
		if key[i] != '[' {
			continue
		}
		closeIdx := -1
		for j := i + 1; j < len(key); j++ {
			if key[j] == ']' {
				closeIdx = j
				break
			}
		}
		if closeIdx < 0 || closeIdx+1 >= len(key) || key[closeIdx+1] != '.' {
			continue
		}
		attr := key[closeIdx+2:]
		//: 属性名里**不许再有点**（`[^.]+$`）——否则 `x[a].b.c` 会被误拆。
		if attr == "" || containsByte(attr, '.') {
			continue
		}
		return key[i+1 : closeIdx], attr, true
	}
	return "", key, false
}

func containsByte(s string, b byte) bool {
	for i := 0; i < len(s); i++ {
		if s[i] == b {
			return true
		}
	}
	return false
}

// Lookup 复刻 `_classify` 里的 `lookup`（`skill.py:886-893`）。
//
// ⚠ control 的量纲是 **`sec`**（不是 `secs`）。
// ⚠ **`_FLIGHT_KEYS` 不在这张查表里**——`_classify` 根本不看它，
// 所以飞行键的分类结果是 `None`，不是 "flight"。（表本身仍留着：它是
// 描述驱动那半的登记，出处见 `skill.py:819-825`。）
func Lookup(k string) (string, string, string, bool) {
	if b, ok := BUFF_KEYS[k]; ok {
		return "buff", b[0], b[1], true
	}
	if f, ok := DAMAGE_KEYS[k]; ok {
		return "damage", f, "scale", true
	}
	for _, c := range CONTROL_KEYS {
		if c == k {
			return "control", k, "sec", true
		}
	}
	return "", "", "", false
}

// suffixRE / infixRE 复刻 `skill.py:845` 与 `:858`。
var (
	suffixRE = regexp.MustCompile(`_(?:s\d+|\d+)$`)
	infixRE  = regexp.MustCompile(`@s\d+_`)
)

func rsplitAt(k string) string {
	if i := strings.LastIndex(k, "@"); i >= 0 {
		return k[i+1:]
	}
	return k
}

// Classify 复刻 `_classify`（`skill.py:880-904`）的**降级序列**：
//
//	原样 → 去 `xxx@` 前缀 → 去 `_s2`/`_2` 尾巴 → 去掉夹在 @ 后面的技能槽标记
//
// 七个候选按顺序试，第一个命中的胜出；都不中就返回 false。
func Classify(key string) (string, string, string, bool) {
	stripped := suffixRE.ReplaceAllString(key, "")
	infixed := infixRE.ReplaceAllString(key, "@")
	for _, cand := range []string{
		key, rsplitAt(key),
		stripped, rsplitAt(stripped),
		infixed, rsplitAt(infixed),
		suffixRE.ReplaceAllString(infixed, ""),
	} {
		if kind, field, unit, ok := Lookup(cand); ok {
			return kind, field, unit, true
		}
	}
	return "", "", "", false
}

// KeyClass 是一个黑板键的归类结果。
type KeyClass struct {
	Key     string `json:"key"`
	Kind    string `json:"kind"`  //: buff / damage / control / ""
	Field   string `json:"field"` //: 规范名
	Unit    string `json:"unit"`  //: 量纲（buff 专用；control 是 sec）
	Variant string `json:"variant"`
	NoVar   string `json:"no_variant"` //: 去掉变体限定后的键
	HasVar  bool   `json:"has_variant"`
}

// ClassifyKey 做**拆变体 ＋ 降级序列**（与 `_classify` 同口径）。
//
// ⚠ `_split_variant` 与 `_classify` 在 Python 里是**两条独立的路径**：
// `_classify` 不去方括号（它拿到的键已经去过）。这里把两者都算出来，
// 但 `kind/field/unit` **只按原键**走降级，不先拆变体——
// 混起来会让带变体的键归类结果与 Python 分叉。
func ClassifyKey(key string) KeyClass {
	out := KeyClass{Key: key, NoVar: key}
	if v, rest, ok := SplitVariant(key); ok {
		out.Variant, out.NoVar, out.HasVar = v, rest, true
	}
	if kind, field, unit, ok := Classify(key); ok {
		out.Kind, out.Field, out.Unit = kind, field, unit
	}
	return out
}
