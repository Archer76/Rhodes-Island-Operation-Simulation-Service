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
	"math"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"
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
	//: ★ 完整黑板（`skill.py:1758-1763` 的口径）：
	//: **每个有 key 的项都落一个数值键**（`float(value or 0)`，所以 value 是 null
	//: 也照样落 0），**另有 `$key` 落 valueStr**（只有当它非空时）。
	//: 两套都要——字符串键是「召唤什么/给哪个装置」唯一的住处，丢掉不报错，
	//: 只是上层把它当「没这项机制」。
	Blackboard map[string]any `json:"blackboard"`
	//: 级号：**0 起算**（`SkillLevel.index`）。级别用的是 1 起算的 `Level`，
	//: 两个都在——混用会让「第 3 级」与「index 3」差一位。
	Index int `json:"index"`
	//: 正文**原样**（`raw_description`）。
	RawDescription string `json:"raw_description"`
	//: 正文**渲染后**（`description`）：`{key}` 按黑板代入、富文本标签剥掉、
	//: 两种换行写法都还原。**查不到的键原样留着**（连花括号一起）。
	Description string `json:"description"`
	//: `_parse_effects` 的**计数账**（`effects.go:EffectsAccount`）：
	//: `total` / `classified` 两个计数与 `other` 的键集。
	//: ⚠ `buffs` / `damage` / `variants` 的**内容**（含尾部两趟收尾）**未接**。
	EffectsTotal      int      `json:"effects_total"`
	EffectsClassified int      `json:"effects_classified"`
	EffectsOther      []string `json:"effects_other"`
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

// placeholderRE / tagRE 复刻 `skill.py:134-135`。
//
// ⚠ 先剥标签再替占位符（`render_description` 的顺序是 `_PLACEHOLDER_RE.sub`
// 之后才 `_TAG_RE.sub`——两件都要做，且**标签会插在词中间**：
// 「伤害类型变为<@ba.vup>真实</>」原样扫「真实伤害」是扫不到的。
var (
	placeholderRE = regexp.MustCompile(`\{([^{}]+)\}`)
	tagRE         = regexp.MustCompile(`</?[^>]+>`)
)

// FormatValue 复刻 `format_value`（`skill.py:138-155`）。
//
// 游戏里只有五种格式：`0%` / `0.0%` / `0.0` / `0`，以及**不写格式串**。
// 前四种按 .NET 的数值格式理解（`%` 会乘 100）；不写时按「整数就不显示小数点」。
//
// ⚠ 兜底那一支是 Python 的 `f"{value:g}"` —— 6 位有效数字。
// Go 要用 `FormatFloat(v,'g',6,64)` 才是同一个数；用精度 -1（最短表示）
// 会在 0.153846… 这类值上多出好几位。
func FormatValue(value float64, spec string) string {
	switch spec {
	case "0%":
		return strconv.FormatFloat(value*100, 'f', 0, 64) + "%"
	case "0.0%":
		return strconv.FormatFloat(value*100, 'f', 1, 64) + "%"
	case "0.0":
		return strconv.FormatFloat(value, 'f', 1, 64)
	case "0":
		return strconv.FormatFloat(value, 'f', 0, 64)
	}
	if value == math.Trunc(value) {
		return strconv.FormatFloat(value, 'f', 0, 64)
	}
	return strconv.FormatFloat(value, 'g', 6, 64)
}

// RenderDescription 复刻 `render_description`（`skill.py:748-766`）。
//
// **查不到的键原样留着**（连花括号一起）——漏了什么一眼能看见，
// 比悄悄替换成 0 或空串诚实。
//
// 换行有两种写法（10881 个等级用真实换行、3168 个等级写字面 `\n`），
// 两种都还原成真实换行。
func RenderDescription(text string, bb map[string]any) string {
	out := placeholderRE.ReplaceAllStringFunc(text, func(m string) string {
		inner := placeholderRE.FindStringSubmatch(m)[1]
		key, spec := inner, ""
		if i := strings.Index(inner, ":"); i >= 0 {
			key, spec = inner[:i], inner[i+1:]
		}
		key = strings.TrimSpace(key)
		v, ok := bb[key]
		if !ok {
			return m
		}
		f, ok := toFloat(v)
		if !ok {
			return m
		}
		return FormatValue(f, strings.TrimSpace(spec))
	})
	out = tagRE.ReplaceAllString(out, "")
	out = strings.ReplaceAll(out, "\\r\\n", "\n")
	out = strings.ReplaceAll(out, "\\n", "\n")
	return out
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
			Description  string  `json:"description"`
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
		//: `index` 是**0 起算**的级号；`Level` 是 1 起算的那个，两个都留。
		Index: level - 1, RawDescription: lv.Description,
	}	//: `duration < 0` 是「无限持续」的哨兵，落成 nil（`skill.py:1769-1774`）。
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
	//: 黑板：数值键全落（null 也落 0），`$key` 只在 valueStr 非空时落。
	out.Blackboard = map[string]any{}
	for _, bRaw := range lv.Blackboard {
		var b struct {
			Key      string   `json:"key"`
			Value    *float64 `json:"value"`
			ValueStr *string  `json:"valueStr"`
		}
		if err := json.Unmarshal(bRaw, &b); err != nil || b.Key == "" {
			continue
		}
		v := 0.0
		if b.Value != nil {
			v = *b.Value
		}
		out.Blackboard[b.Key] = v
		if b.ValueStr != nil && *b.ValueStr != "" {
			out.Blackboard["$"+b.Key] = *b.ValueStr
		}
	}
	//: 渲染正文要**在黑板建好之后**做——它吃的就是这张表。
	out.Description = RenderDescription(lv.Description, out.Blackboard)
	//: 效果账（两个计数 ＋ other 键集）。`$` 键由 EffectsAccount 自己跳过，
	//: 这里把整张黑板（含 `$` 键）交给它，与 Python 同一入口。
	out.EffectsTotal, out.EffectsClassified, out.EffectsOther =
		EffectsAccount(out.Blackboard, out.DurationType)
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
