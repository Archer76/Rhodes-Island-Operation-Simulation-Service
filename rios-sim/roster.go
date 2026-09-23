package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"sort"
	"strconv"
	"strings"
)

// roster.go：Go 直读练度名册（丙阶段四·第十二批）。
//
// ## 为什么这是自足路上的必经一件
//
// 目标里写着「Go 直读 `data/gamedata` ＋**名册**＋计划」。前三层（关卡／敌人／
// 干员）已经搬完，而**名册在本树里一个 Go 入口都没有**——规格里的练度全靠
// Python 送进来。没有名册，Go 就算把折算全部搬完也构造不出规格。
//
// ## 权威是 `ak_tactic/plan.py:186-238` 的 `Roster.from_json`
//
// 吃两种外形：**MAA OperBox 导出**（顶层数组）与**森空岛名册**（顶层字典、
// 干员在 `opers` / `chars` 下）。下面逐条复刻，几处看着像笔误但**都是口径**：
//
//   - **跳过的条件是 `own is False`（恒等）**，不是「own 为假」。`"own": 0`
//     取真值也是假，可是 `0 is False` 为假 ⇒ **留着**。写成真值判断会
//     把 `own: 0` 的干员整批丢掉（MAA 导出里 `own` 是布尔，但别的产物不一定）。
//   - **`level` / `potential` 的缺省是 1，靠 `or` 兜底**：`0 or 1` 得 1，
//     所以 `"level": 0` 这一行**不是** 0 级而是 1 级。`elite` 的缺省是 0，
//     于是 `elite: 0` 就是 0。
//   - **表按 `name` 做键**，不是 charId：同名两行**后写覆盖前写**，而位置留在
//     第一次插入的地方（Python dict 的语义）。丢名字或丢 id 的行整条跳过。
//   - `charId` 取不到才退到 `id`；两者都空才跳过。
//   - `module` 走 `or None`：空串与缺省都是「没带模组」，**不是空串**。
//   - 读文件用 `utf-8-sig`，BOM 必须先去。
//
// ## 两份顺序都要
//
// `entries` 按**插入序**（就是源文件里的行序），`names` 是排过序的
// （Python 的 `sorted()`，即码点序）。两个都给，是因为消费点两边都有：
// 顺序敏感的取数要前者，选人/展示要后者。Go 的 map 迭代是随机的，
// 所以顺序一律从**原始数组**来，不从 map 来。

// RosterEntry 是名册里一名干员的练度那一行。
type RosterEntry struct {
	Name        string  `json:"name"`
	CharID      string  `json:"char_id"`
	Elite       int     `json:"elite"`
	Level       int     `json:"level"`
	Potential   int     `json:"potential"`
	Module      *string `json:"module"` // nil = 没带模组（**不用空串顶替**）
	ModuleLevel int     `json:"module_level"`
}

// RosterRead 是 `roster` 的应答。
type RosterRead struct {
	Entries []RosterEntry `json:"entries"`
	Names   []string      `json:"names"`
}

// pyFalsy 复刻 Python 在 `or` / `if not x` 语境下的真假：None、false、0、""、
// 空容器都是假。`or` 兜底的每一条（level/potential/elite/module_level/module）
// 都靠它，所以它必须是**Python 的真假**，不是 Go 的零值判断。
func pyFalsy(raw json.RawMessage) bool {
	s := strings.TrimSpace(string(raw))
	if s == "" || s == "null" || s == "false" {
		return true
	}
	switch s[0] {
	case '"':
		return s == `""`
	case '[', '{':
		if len(s) < 2 {
			return false
		}
		return strings.TrimSpace(s[1:len(s)-1]) == ""
	default:
		f, err := strconv.ParseFloat(s, 64)
		if err != nil {
			return false
		}
		return f == 0
	}
}

// pyStr 取一个字符串字段，空/缺省/非字符串都算「没有」。
func pyStr(m map[string]json.RawMessage, key string) (string, bool) {
	raw, ok := m[key]
	if !ok || pyFalsy(raw) {
		return "", false
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return "", false
	}
	return s, true
}

// pyStrStrict 与 `pyStr` 同，但**非字符串要报错**，不许静默当成「没有」。
//
// ⚠ 这是一处**声明过的分歧**：原版对 `name` / `charId` / `module` 不做类型约束，
// `{"id": 5, "name": "丁"}` 会被原版收下、`char_id` 就是数字 5。Go 侧拒收——
// 一个下游认不出的 id 混进名册，症状是「这名干员的面板取不到」而**不报错**；
// 大声失败优于静默收下。判据 `check_roster_go.py` 把这处分歧单列，
// 要求「Go 拒 ∧ 原版收」同时成立才算登记到。
func pyStrStrict(m map[string]json.RawMessage, key string) (string, bool, error) {
	raw, ok := m[key]
	if !ok || pyFalsy(raw) {
		return "", false, nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return "", false, fmt.Errorf("字段 %s 不是字符串：%s", key, string(raw))
	}
	return s, true, nil
}

// pyIntOr 复刻 `int(r.get(k) or dflt)`。`int()` 对浮点向零截断，Go 的 int()
// 同义；数字写在字符串里（`"2"`）Python 也认，这里一并认。
func pyIntOr(m map[string]json.RawMessage, key string, dflt int) (int, error) {
	raw, ok := m[key]
	if !ok || pyFalsy(raw) {
		return dflt, nil
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err == nil {
		return int(f), nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		if n, err2 := strconv.Atoi(strings.TrimSpace(s)); err2 == nil {
			return n, nil
		}
		return 0, fmt.Errorf("名册字段 %s 不是整数：%q", key, s)
	}
	return 0, fmt.Errorf("名册字段 %s 不是整数：%s", key, string(raw))
}

// rosterRows 复刻 `data.get("opers") or data.get("chars") or []`。
//
// ⚠ **一处声明过的分歧**：原版对 `opers` 取到非数组（比如一个对象）时不报错，
// 而是拿它去 `for`、把每个键（字符串）当行、再被 `isinstance(r, dict)` 全过滤掉，
// 于是**静默得到一份空名册**。Go 侧改成大声报错——空名册与「名册里没人」在
// 下游是同一种表现（每人退回默认练度），正是最难查的那种。
func rosterRows(obj map[string]json.RawMessage) ([]json.RawMessage, error) {
	for _, key := range []string{"opers", "chars"} {
		raw, ok := obj[key]
		if !ok || pyFalsy(raw) {
			continue
		}
		var rows []json.RawMessage
		if err := json.Unmarshal(raw, &rows); err != nil {
			return nil, fmt.Errorf("名册的 %s 不是数组：%v", key, err)
		}
		return rows, nil
	}
	return nil, nil
}

// ReadRoster 直读一份名册文件。
func ReadRoster(path string) (RosterRead, error) {
	data, err := os.ReadFile(path)
	if err != nil {
		return RosterRead{}, fmt.Errorf("名册读不出来：%v", err)
	}
	//: 原版是 `encoding="utf-8-sig"`——BOM 不清掉，第一个字节就成了对象外的字符。
	data = bytes.TrimPrefix(data, []byte{0xEF, 0xBB, 0xBF})
	return parseRosterBlob(data, path)
}

// ParseRoster 解一份**内联**名册（JSON 原样，不经文件）。
//
// 为什么要它：`sim` 的**查询形式**（Go 自己造规格）里，调用方手上是
// **名册对象**而不是文件路径——`ak_tactic/plan.py` 的 `Roster.from_json(path)`
// **不保留来源路径**，`Plan.load(path)` 同理。Python 侧要么写临时文件（搜索路径
// 每场一次，不可接受），要么把对象原样送过来。这里走后者。
//
// ⚠ 与 `ReadRoster` **共用同一份解析**（`parseRosterBlob`）：两份实现必然有一天
// 不一致，而「名册少读了一行」在下游只是「某个干员退回默认练度」。
func ParseRoster(raw json.RawMessage) (RosterRead, error) {
	data := bytes.TrimPrefix(raw, []byte{0xEF, 0xBB, 0xBF})
	return parseRosterBlob(data, "（内联）")
}

// parseRosterBlob 是两种入参形式**共用的那一段**（`label` 只进错误消息）。
func parseRosterBlob(data []byte, label string) (RosterRead, error) {
	var out RosterRead
	var rows []json.RawMessage
	head := bytes.TrimLeft(data, " \t\r\n")
	switch {
	case len(head) == 0:
		return out, fmt.Errorf("名册 %s 是空的", label)
	case head[0] == '[':
		if err := json.Unmarshal(data, &rows); err != nil {
			return out, fmt.Errorf("名册 %s 不是数组：%v", label, err)
		}
	case head[0] == '{':
		var obj map[string]json.RawMessage
		if err := json.Unmarshal(data, &obj); err != nil {
			return out, fmt.Errorf("名册 %s 不是对象：%v", label, err)
		}
		var err error
		if rows, err = rosterRows(obj); err != nil {
			return out, fmt.Errorf("名册 %s：%v", label, err)
		}
	default:
		return out, fmt.Errorf("名册 %s 的形状不认识：首字符 %q", label, head[0])
	}

	//: 按 name 做键：值后写覆盖，位置留在第一次插入的地方——Python dict 的语义。
	var order []string
	byName := map[string]RosterEntry{}
	for i, row := range rows {
		var m map[string]json.RawMessage
		if err := json.Unmarshal(row, &m); err != nil {
			continue // 原版 `if not isinstance(r, dict): continue`
		}
		if raw, ok := m["own"]; ok && strings.TrimSpace(string(raw)) == "false" {
			continue // ★ 恒等判断，不是真值判断
		}
		name, ok, err := pyStrStrict(m, "name")
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行：%v", i, err)
		}
		if !ok {
			continue
		}
		cid, ok, err := pyStrStrict(m, "charId")
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		}
		if !ok {
			if cid, ok, err = pyStrStrict(m, "id"); err != nil {
				return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
			}
		}
		if !ok {
			continue
		}
		elite, err := pyIntOr(m, "elite", 0)
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		}
		level, err := pyIntOr(m, "level", 1)
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		}
		potential, err := pyIntOr(m, "potential", 1)
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		}
		modLevel, err := pyIntOr(m, "module_level", 0)
		if err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		}
		var module *string
		if s, has, err := pyStrStrict(m, "module"); err != nil {
			return out, fmt.Errorf("名册第 %d 行（%s）：%v", i, name, err)
		} else if has {
			module = &s
		}
		if _, seen := byName[name]; !seen {
			order = append(order, name)
		}
		byName[name] = RosterEntry{
			Name: name, CharID: cid, Elite: elite, Level: level,
			Potential: potential, Module: module, ModuleLevel: modLevel,
		}
	}

	out.Entries = make([]RosterEntry, 0, len(order))
	for _, name := range order {
		out.Entries = append(out.Entries, byName[name])
	}
	out.Names = append([]string{}, order...)
	sort.Strings(out.Names)
	return out, nil
}
