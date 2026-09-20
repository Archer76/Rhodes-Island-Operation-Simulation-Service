package main

// skillmeta.go：**技能元数据**（丙阶段四·第一批）。
//
// 注意与既有的 `skill.go` 分工不同：那个是**运行时**的技能激活/停用与最大生命加成，
// 本文件只做**取数**——把 `skill_table.json` 的状态机参数读出来。
//
// `simgo/skills.py` 的文件头把技能切成两件事：
//
//	* 状态机（攒技力、能不能开、持续时间、弹药、被动）→ 交给 Go，
//	  参数是 sp_type / sp_cost / init_sp / increment / max_charge_time /
//	  duration / duration_type / skill_type / range_id；
//	* 数值（攻击力、防御、法抗…）→ 在 Python 侧算好**两套**（未开启 ＋ active）。
//
// 本文件只做前一半。
//
// ⚠ **`spData` 是嵌套对象，不是平铺字段**；按平铺名去顶层找会全部取到零值。
// ⚠ `rangeId` 为 null 是**正常值**（技能不改范围），不是缺数据——用指针分开。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
)

// SkillMeta 是一个技能在某一级上的状态机参数。
type SkillMeta struct {
	SkillID      string  `json:"skill_id"`
	Level        int     `json:"level"`
	Name         string  `json:"name"`
	SkillType    string  `json:"skill_type"`
	DurationType string  `json:"duration_type"`
	SPType       any     `json:"sp_type"`
	SPCost       float64 `json:"sp_cost"`
	InitSP       float64 `json:"init_sp"`
	Increment    float64 `json:"increment"`
	//: ⚠ 默认值是 **1**，不是 0——Python 侧写的是 `sp.get("maxChargeTime") or 1`
	//: （`skill.py:1787`）。数据里这一项为 null 时按 1 算；按 0 算会让「每秒回一次」
	//: 变成「永不回」。
	MaxCharge    float64 `json:"max_charge_time"`
	//: ⚠ **可能是 null**——`-1`（或负值）表示「无限持续」，Python 落成 None
	//: （`skill.py:1769-1774`）。压成 0 会把「无限」变成「持续 0 秒」。
	Duration *float64 `json:"duration"`
	//: `null` 是**正常值**（技能不改范围）。用指针把「没有」与「空串」分开。
	RangeID *string `json:"range_id"`
	//: 这一级有没有 `blackboard`——数值那一半的原料，本批不解析，只报个数。
	BlackboardEntries int `json:"blackboard_entries"`
}

// normalizeSPType 复刻 `_normalize_sp_type`（`skill.py:1988-2008`）：
//
//	if skill_type == "PASSIVE" or sp_type == 8: return "PASSIVE"
//
// ★ `8` 是 **PASSIVE 技能用的哨兵值**（无技力），不是第四种回复方式
// （`skill.py:89` 的原话）。数据里 `spType` 在专精档上就是那个数字 8。
// ★ 判据两半都要留：只看 `sp_type == 8` 对干员是空的（他们的 spType 是名字），
// 只看 `skill_type == "PASSIVE"` 又会漏掉召唤物那半——两边一起才归一得对。
func normalizeSPType(spType any, skillType string) any {
	if skillType == "PASSIVE" {
		return "PASSIVE"
	}
	if f, ok := toFloat(spType); ok && f == 8 {
		return "PASSIVE"
	}
	return spType
}

var skillTableCache map[string]json.RawMessage

// LoadSkillTable 读 `skill_table.json` 并缓存。
func LoadSkillTable() (map[string]json.RawMessage, error) {
	if skillTableCache != nil {
		return skillTableCache, nil
	}
	p := filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel",
		"skill_table.json")
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("读 skill_table 失败（%s）：%w", p, err)
	}
	var tbl map[string]json.RawMessage
	if err := json.Unmarshal(blob, &tbl); err != nil {
		return nil, fmt.Errorf("skill_table 不是合法 JSON（%s）：%w", p, err)
	}
	if len(tbl) == 0 {
		return nil, fmt.Errorf("skill_table 是空的（%s）", p)
	}
	skillTableCache = tbl
	return tbl, nil
}

// SkillIDs 返回全部技能 id（已排序），供判据遍历。
func SkillIDs() ([]string, error) {
	tbl, err := LoadSkillTable()
	if err != nil {
		return nil, err
	}
	out := make([]string, 0, len(tbl))
	for k := range tbl {
		out = append(out, k)
	}
	sort.Strings(out)
	return out, nil
}

// SkillMetaFor 取一个技能某一级的元数据。`level` 是 **1 起算**的普通等级。
func SkillMetaFor(skillID string, level int) (*SkillMeta, error) {
	tbl, err := LoadSkillTable()
	if err != nil {
		return nil, err
	}
	raw, ok := tbl[skillID]
	if !ok {
		return nil, fmt.Errorf("skill_table 里没有 %q", skillID)
	}
	var entry struct {
		Levels []struct {
			Name         string  `json:"name"`
			RangeID      *string `json:"rangeId"`
			SkillType    string  `json:"skillType"`
			DurationType string  `json:"durationType"`
			//: ⚠ `duration` 在数据里是**数字**，且 `-1` 是「无限持续」的哨兵。
			Duration *float64 `json:"duration"`
			SPData       struct {
				//: ⚠ **不总是字符串**——`skchr_acspec_1` 这一条里它是**数字**。
				//: 按 string 解会让整个技能表解析失败（实测踩到）。
				SPType        any      `json:"spType"`
				MaxChargeTime *float64 `json:"maxChargeTime"`
				SPCost        *float64 `json:"spCost"`
				InitSP        *float64 `json:"initSp"`
				Increment     *float64 `json:"increment"`
			} `json:"spData"`
			Blackboard []json.RawMessage `json:"blackboard"`
		} `json:"levels"`
	}
	if err := json.Unmarshal(raw, &entry); err != nil {
		return nil, fmt.Errorf("%s 解析失败：%w", skillID, err)
	}
	if level < 1 || level > len(entry.Levels) {
		return nil, fmt.Errorf("%s 只有 %d 级，收到 %d", skillID, len(entry.Levels), level)
	}
	lv := entry.Levels[level-1]
	out := &SkillMeta{
		SkillID: skillID, Level: level, Name: lv.Name,
		SkillType: lv.SkillType, DurationType: lv.DurationType,
		RangeID: lv.RangeID, SPType: normalizeSPType(lv.SPData.SPType, lv.SkillType),
		BlackboardEntries: len(lv.Blackboard),
	}
	//: `duration < 0` 是「无限持续」的哨兵，落成 nil（`skill.py:1769-1774`）。
	if lv.Duration != nil && *lv.Duration >= 0 {
		out.Duration = lv.Duration
	}
	//: ★ `range_id` 有**两个来源**（`_range_override`，`skill.py:2016-2025`）：
	//: 先看 `levels[].rangeId`（覆盖 2788 处），没有再看黑板里的 `$range_id`
	//: （真值在 `valueStr`，另覆盖 44 处）。只读前者会让那 44 处静默变成「不改范围」。
	if out.RangeID == nil && len(lv.Blackboard) > 0 {
		for _, bRaw := range lv.Blackboard {
			var b struct {
				Key      string  `json:"key"`
				ValueStr *string `json:"valueStr"`
			}
			if err := json.Unmarshal(bRaw, &b); err != nil {
				continue
			}
			if b.Key == "range_id" && b.ValueStr != nil && *b.ValueStr != "" {
				s := *b.ValueStr
				out.RangeID = &s
				break
			}
		}
	}
	//: 这四个在数据里可能是 null——按 Python 的 `or …` 同口径落值。
	//: ★ `maxChargeTime` 的兜底是 **1**（`skill.py:1787`），另外三个是 0。
	if lv.SPData.SPCost != nil {
		out.SPCost = *lv.SPData.SPCost
	}
	if lv.SPData.InitSP != nil {
		out.InitSP = *lv.SPData.InitSP
	}
	if lv.SPData.Increment != nil {
		out.Increment = *lv.SPData.Increment
	}
	out.MaxCharge = 1
	if lv.SPData.MaxChargeTime != nil && *lv.SPData.MaxChargeTime != 0 {
		out.MaxCharge = *lv.SPData.MaxChargeTime
	}
	return out, nil
}

// SkillLevelCount 返回一个技能有几级。
func SkillLevelCount(skillID string) (int, error) {
	tbl, err := LoadSkillTable()
	if err != nil {
		return 0, err
	}
	raw, ok := tbl[skillID]
	if !ok {
		return 0, fmt.Errorf("skill_table 里没有 %q", skillID)
	}
	var entry struct {
		Levels []json.RawMessage `json:"levels"`
	}
	if err := json.Unmarshal(raw, &entry); err != nil {
		return 0, err
	}
	return len(entry.Levels), nil
}
