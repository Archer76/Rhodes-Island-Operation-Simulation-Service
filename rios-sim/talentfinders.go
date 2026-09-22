package main

// talentfinders.go：干员**天赋派生装配**要用的那套「认得出来 + 取黑板值」。
//
// 权威 `ak_tactic/frontend/talent_finders.py`（290 行）——**不是** `battle/talents.py`
// （973 行里一个 finder 都没有，本仓踩过「同名非同一张表」）。逐条照抄，
// 常量后面括号里是那一行的行号。
//
// ## 为什么这一份能搬
//
// 九个 finder 的判据**只有两种形状**，而两种都落在 Go 已经有的
// `resolvedTalent{Name, Blackboard}`（`operator_aspd.go:47/55/113`）上：
//
//	① 名字 ∈ 常量表             （`is_angel_blessing` / `is_class_aura_talent` /
//	                              `is_damage_block_talent` / `is_limit_dispatch`）
//	② 黑板**同时**含某几个键     （`is_blessing_talent` / `is_regen_talent`）
//	③ 名字 ＋ 黑板键（复合）      （`is_ammo_covenant_talent` / `is_medic_monument_talent` /
//	                              `is_team_aura_talent` / `is_faction_aura_talent`）
//
// 值一律经 `Talent.value(key, default)`（`operator/talent.py:86-89`）：
// **键不存在给 default，键在就是它的值**（`0` 不是「没有」）。
//
// ## 两个形状坑（照抄时最容易走散的）
//
//  1. `has(*keys)` 是「**全部**命中」（`talent.py:91-93` 的 `all(...)`），
//     不是「任一命中」。写成任一命中会把别的天赋误认成祝福/回血那两条。
//  2. `find_team_aura`（`talent_finders.py:250-254`）返回的是
//     **两条不同形状里的同一条**：`青色怒火`（常驻＋开技能加倍）与
//     `万众巨潮`（只在技能期间、且对乌萨斯学生自治团翻倍）。拿到之后还要
//     按 `aura.name == FACTION_AURA_NAME` 再分叉——**两个名字都要判**。

import (
	"encoding/json"
)

// ---------------------------------------------------------------- 常量表
//
// ⚠ 全部是**天赋的中文名**与势力/职业代号，来源是 `talent_finders.py` 而不是
// gamedata：它们不是数据表里的列，是「哪一条天赋是它」的判据。

const (
	tfAmmoCovenantName  = "铳弹协约"     // talent_finders.py:59
	tfFactionAuraName   = "万众巨潮"     // :113
	tfTeamAuraName      = "青色怒火"     // :188
	tfMedicMonumentName = "医者丰碑"     // :137
	tfRhodesNation      = "rhodes"   // :158
	tfLateranoNation    = "laterano" // :121
)

// tfAngelBlessingTalents 是「天使的祝福」（能天使）：**自身** +6% 攻击。
var tfAngelBlessingTalents = map[string]bool{"天使的祝福": true} // :69

// tfClassAuraTalents 是名字 → **主职业代号**（`TANK` = 重装）。
//
// ⚠ 是职业代号，不是阵营 char_id 名单（`_team_auras_of` 的注释专门点了这一处）。
var tfClassAuraTalents = map[string]string{"特种作战策略": "TANK"} // :89

// tfDamageBlockTalents 是「战术装甲」（星熊）：天赋常驻闪避。
var tfDamageBlockTalents = map[string]bool{"战术装甲": true} // :108

// tfLimitDispatchTalents 是「极限调度」（可露希尔）。
var tfLimitDispatchTalents = map[string]bool{"极限调度": true} // :128

// tfBlessingKeys 是「圣山的祝福」的黑板指纹：**两个键同时出现**才算。
var tfBlessingKeys = []string{"c2e_freeze", "freeze"} // :87

// tfRegenKeys 是「医者丰碑」回血那一半的黑板指纹：**两个键同时出现**才算。
var tfRegenKeys = []string{"hp_recovery_per_sec", "buff_duration"} // :154

// tfStudentTeam 是【乌萨斯学生自治团】的成员（`operator.team_id == 'student'`）。
//
// ⚠ 原版用 char_id 常量而不是查库：**战斗层不连数据库**，而阵营是稳定的游戏数据
// （`talent_finders.py:163-166` 就是这么写的）。复核命令在那一段的注释里。
var tfStudentTeam = []string{ // :167-175
	"char_1051_headb2", // 怒潮凛冬
	"char_115_headbr",  // 凛冬
	"char_194_leto",    // 烈夏
	"char_195_glassb",  // 真理
	"char_196_sunbr",   // 古米
	"char_197_poca",    // 早露
	"char_405_absin",   // 苦艾
}

// ---------------------------------------------------------------- 取黑板

// bbHas 复刻 `Talent.has`（`talent.py:91-93`）：这些键**都在**（`all`，不是 `any`）。
func bbHas(bb map[string]any, keys ...string) bool {
	for _, k := range keys {
		if _, ok := bb[k]; !ok {
			return false
		}
	}
	return true
}

// bbValue 复刻 `Talent.value`（`talent.py:86-89`）：键不存在给默认值，
// **键在就取它的值**（`0` 是真值，不许被默认值顶掉）。
func bbValue(bb map[string]any, key string, def float64) float64 {
	v, ok := bb[key]
	if !ok || v == nil {
		return def
	}
	f, ok := toFloat(v)
	if !ok {
		return def
	}
	return f
}

// ---------------------------------------------------------------- 九个 finder

// tfFindBlessing 复刻 `find_blessing` ＋ `is_blessing_talent`（`:207` / `:262`）。
func tfFindBlessing(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if bbHas(t.Blackboard, tfBlessingKeys...) {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindRegen 复刻 `find_regen` ＋ `is_regen_talent`（`:238` / `:281`）。
func tfFindRegen(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if bbHas(t.Blackboard, tfRegenKeys...) {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindMedicMonument 复刻 `find_medic_monument` ＋ 谓词（`:232` / `:278`）。
func tfFindMedicMonument(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if t.Name == tfMedicMonumentName && bbHas(t.Blackboard, "rhodes_bonus") {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindDamageBlock 复刻 `find_damage_block` ＋ `is_damage_block_talent`（`:220` / `:268`）。
func tfFindDamageBlock(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if tfDamageBlockTalents[t.Name] {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindTeamAura 复刻 `find_team_aura`（`:250-254`）：**两条形状里的同一条**。
//
// 第二个返回值是「这条是不是万众巨潮那一支」——`_team_auras_of` 据此分叉。
func tfFindTeamAura(ts []resolvedTalent) (resolvedTalent, bool, bool) {
	for _, t := range ts {
		if t.Name == tfTeamAuraName && bbHas(t.Blackboard, "atk", "def") {
			return t, true, false
		}
		if t.Name == tfFactionAuraName && bbHas(t.Blackboard, "atk", "def") {
			return t, true, true
		}
	}
	return resolvedTalent{}, false, false
}

// tfFindClassAura 复刻 `find_class_aura` ＋ 谓词（`:214` / `:265`）。
func tfFindClassAura(ts []resolvedTalent) (resolvedTalent, string, bool) {
	for _, t := range ts {
		if prof, ok := tfClassAuraTalents[t.Name]; ok {
			return t, prof, true
		}
	}
	return resolvedTalent{}, "", false
}

// tfFindAmmoCovenant 复刻 `find_ammo_covenant` ＋ 谓词（`:195` / `:256`）。
func tfFindAmmoCovenant(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if t.Name == tfAmmoCovenantName && bbHas(t.Blackboard, "atk", "mult") {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindAngelBlessing 复刻 `find_angel_blessing` ＋ 谓词（`:201` / `:259`）。
func tfFindAngelBlessing(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if tfAngelBlessingTalents[t.Name] {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfFindLimitDispatch 复刻 `find_limit_dispatch` ＋ 谓词（`:226` / `:275`）。
func tfFindLimitDispatch(ts []resolvedTalent) (resolvedTalent, bool) {
	for _, t := range ts {
		if tfLimitDispatchTalents[t.Name] {
			return t, true
		}
	}
	return resolvedTalent{}, false
}

// tfInStudentTeam 判一个 char_id 是不是乌萨斯学生自治团成员。
func tfInStudentTeam(charID string) bool {
	for _, c := range tfStudentTeam {
		if c == charID {
			return true
		}
	}
	return false
}

// charTalents 取一名干员在**练度生效**下的天赋列表（`resolvedTalent`）。
//
// 数据源与 `OperatorStatsFor`（`operator.go:362-375`）同一处：
// `character_table.json` 的 `talents`，再经 `resolveTalents`（`operator_aspd.go:55`）。
// 这里**另读一次表**而不是改 `OperatorStats`——那个结构体有跨实现对拍判据
// （`check_operator_go.py` 逐字段比它的 json 键），往里塞字段会让那份判据的
// 键集对不上，红出来却与真正的改动无关。
func charTalents(charID string, elite, level, potential int) ([]resolvedTalent, error) {
	tbl, err := loadCharTable()
	if err != nil {
		return nil, err
	}
	raw, ok := tbl[charID]
	if !ok || string(raw) == "null" {
		return nil, nil //: 取不到当**没有天赋**：与 `resolve_talents` 的退化一致
	}
	var char struct {
		Talents []json.RawMessage `json:"talents"`
	}
	if err := json.Unmarshal(raw, &char); err != nil {
		return nil, err
	}
	return resolveTalents(char.Talents, elite, level, potential), nil
}
