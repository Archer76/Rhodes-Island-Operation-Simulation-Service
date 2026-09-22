package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// loadout.go：把**名册与计划接起来**——练度的解析（丙阶段四·第十四批）。
//
// ## 为什么这一步才是「接上了」
//
// 名册与计划各自读进来之后，两份都是**没人用的数据**：规格里要的不是
// 「这个人练到 90 级」或「这条指令让他站 5,4」，而是**合起来之后**的那一组
// 面板入参（精英／等级／潜能／信赖／模组）。这一层不落地，「读进来了」就只是
// 半句真话。
//
// 权威是 `ak_tactic/verify.py:548-569` 的 `Verifier._entry(d, roster)`：
//
//   - 基准取 `roster.get(d.operator)`（**按名字**查，与名册的键口径一致）；
//   - 两边都拿不到练度就报错（名册里没这个人，且打法里没把 elite/level 写全）；
//   - 六项（elite/level/potential/trust/module/module_level）**打法里写了就覆盖**
//     （判据是 `is not None`，所以 `elite: 0` 是一次**有效的覆盖**，不是「没写」）；
//   - 三条 `setdefault`（elite→0、level→1、potential→1）只在**键整个不存在**
//     时生效——基准来自名册时那三个键一定在，所以它们只对「名册里没有这个人」
//     的那条路有意义；
//   - `char_id` 缺失时按**名字**回数据里找：`character_table` 里 `char_` 开头的
//     条目 ＋ `char_patch_table` 的 `patchChars`，跳过 `TRAP` / `TOKEN`，
//     取**第一个**匹配。⚠ 「第一个」是**表内行序**上的第一个，所以下面
//     `loadCharOrder` 走 Token 流取键序，**不用 map 迭代**（Go 的 map 迭代是
//     随机的，同一份数据换一次跑就可能挑到另一个同名的 id）。

var charOrderCache []string

// jsonKeysInOrder 按**文件行序**取出顶层对象的键（可选前缀过滤）。
//
// 用 `json.Decoder` 的 Token 流而不是 `map[string]json.RawMessage`：
// Go 的 map 没有顺序，而这里要的正是顺序。
func jsonKeysInOrder(path, prefix string) ([]string, error) {
	blob, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}
	dec := json.NewDecoder(bytes.NewReader(blob))
	tok, err := dec.Token()
	if err != nil {
		return nil, err
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil, fmt.Errorf("顶层不是对象")
	}
	var out []string
	for dec.More() {
		kt, err := dec.Token()
		if err != nil {
			return nil, err
		}
		key, ok := kt.(string)
		if !ok {
			return nil, fmt.Errorf("键不是字符串")
		}
		var skip json.RawMessage
		if err := dec.Decode(&skip); err != nil {
			return nil, err
		}
		if prefix == "" || strings.HasPrefix(key, prefix) {
			out = append(out, key)
		}
	}
	return out, nil
}

// jsonSubKeysInOrder 取某个子对象里的键，同样按行序。
func jsonSubKeysInOrder(path, sub string) []string {
	blob, err := os.ReadFile(path)
	if err != nil {
		return nil
	}
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(blob, &obj); err != nil {
		return nil
	}
	inner, ok := obj[sub]
	if !ok {
		return nil
	}
	dec := json.NewDecoder(bytes.NewReader(inner))
	tok, err := dec.Token()
	if err != nil {
		return nil
	}
	if d, ok := tok.(json.Delim); !ok || d != '{' {
		return nil
	}
	var out []string
	for dec.More() {
		kt, err := dec.Token()
		if err != nil {
			return nil
		}
		key, _ := kt.(string)
		var skip json.RawMessage
		if err := dec.Decode(&skip); err != nil {
			return nil
		}
		out = append(out, key)
	}
	return out
}

// loadCharOrder 复刻 `stats.py:400-423` 的 `_load_chars()` 的**键序**：
// `character_table` 里 `char_` 开头的条目（表内行序）＋ `patchChars` 里
// **没出现过**的（`setdefault`，接在后面）。
//
// 补丁表取不到不算错误——与 `loadCharTable` 同一口径（「少两个形态而已」）。
func loadCharOrder() ([]string, error) {
	if charOrderCache != nil {
		return charOrderCache, nil
	}
	base := filepath.Join(DataRoot(), "raw.githubusercontent.com", "excel")
	ids, err := jsonKeysInOrder(filepath.Join(base, "character_table.json"), "char_")
	if err != nil {
		return nil, fmt.Errorf("读 character_table 的键序失败：%v", err)
	}
	if len(ids) == 0 {
		return nil, fmt.Errorf("character_table 里一个 char_ 条目都没有")
	}
	seen := make(map[string]bool, len(ids))
	for _, id := range ids {
		seen[id] = true
	}
	for _, id := range jsonSubKeysInOrder(
		filepath.Join(base, "char_patch_table.json"), "patchChars") {
		if !seen[id] {
			ids = append(ids, id)
			seen[id] = true
		}
	}
	charOrderCache = ids
	return ids, nil
}

// byNameCharID 复刻 `verify.py:571-577` 的 `_by_name`：按名字找 charId，
// 跳过装置/召唤物，取**行序上的第一个**。
func byNameCharID(name string) (string, bool) {
	ids, err := loadCharOrder()
	if err != nil {
		return "", false
	}
	tbl, err := loadCharTable()
	if err != nil {
		return "", false
	}
	for _, id := range ids {
		raw, ok := tbl[id]
		if !ok {
			continue
		}
		var c struct {
			Name       string `json:"name"`
			Profession string `json:"profession"`
		}
		if json.Unmarshal(raw, &c) != nil {
			continue
		}
		if c.Name == name && c.Profession != "TRAP" && c.Profession != "TOKEN" {
			return id, true
		}
	}
	return "", false
}

// LoadoutEntry 是一名干员**合起来之后**的那组练度。
type LoadoutEntry struct {
	CharID      string  `json:"char_id"`
	Elite       int     `json:"elite"`
	Level       int     `json:"level"`
	Potential   int     `json:"potential"`
	Trust       *int    `json:"trust"`
	Module      *string `json:"module"`
	ModuleLevel *int    `json:"module_level"`
}

// ResolveLoadout 复刻 `Verifier._entry`。
func ResolveLoadout(d DeployOrder, roster RosterRead) (LoadoutEntry, error) {
	var base *RosterEntry
	for i := range roster.Entries {
		if roster.Entries[i].Name == d.Operator {
			base = &roster.Entries[i]
			break
		}
	}
	if base == nil && (d.Elite == nil || d.Level == nil) {
		return LoadoutEntry{}, fmt.Errorf(
			"「%s」的练度没着落：打法里没写 elite/level，名册里也没有这个人",
			d.Operator)
	}

	e := LoadoutEntry{}
	have := map[string]bool{}
	if base != nil {
		e.CharID = base.CharID
		e.Elite, e.Level, e.Potential = base.Elite, base.Level, base.Potential
		e.Module = base.Module
		ml := base.ModuleLevel
		e.ModuleLevel = &ml
		for _, k := range []string{"elite", "level", "potential", "module",
			"module_level"} {
			have[k] = true
		}
	}
	//: 打法里写了就覆盖。判据是 `is not None` ⇒ `elite: 0` 是一次**有效覆盖**。
	if d.Elite != nil {
		e.Elite, have["elite"] = *d.Elite, true
	}
	if d.Level != nil {
		e.Level, have["level"] = *d.Level, true
	}
	if d.Potential != nil {
		e.Potential, have["potential"] = *d.Potential, true
	}
	if d.Trust != nil {
		e.Trust, have["trust"] = d.Trust, true
	}
	if d.Module != nil {
		e.Module, have["module"] = d.Module, true
	}
	if d.ModuleLevel != nil {
		e.ModuleLevel, have["module_level"] = d.ModuleLevel, true
	}
	//: 三条 setdefault **只在键不存在时**生效——所以判的是 `have`，不是零值。
	if !have["elite"] {
		e.Elite = 0
	}
	if !have["level"] {
		e.Level = 1
	}
	if !have["potential"] {
		e.Potential = 1
	}
	if e.CharID == "" {
		cid, ok := byNameCharID(d.Operator)
		if !ok {
			return LoadoutEntry{}, fmt.Errorf("干员「%s」在数据里找不到", d.Operator)
		}
		e.CharID = cid
	}
	return e, nil
}
