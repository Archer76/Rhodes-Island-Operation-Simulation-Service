package maa

import (
	"database/sql"
	"fmt"
	"strings"

	"rios-sim/data"
)

// 本文件是**唯一碰 sqlite 的地方**。渲染面（`maaexport.go`）拿到的都是
// 已经取好的数据，这样它可以纯函数式地测，也便于日后把取数面搬去别处 ——
// 引擎二进制不该替数据层付体积（迁移图 §7.4）。

// ModuleTable 把 `module` 表整表读进 map（实测 905 行）。
//
// 对应 Python 的 `_uniEquip` 全局缓存：**惰性**，只有出现非空 module id 时才该调用
// —— 复刻 `maa_export.py:141-142` 的提前返回，否则「没有库、也没人带模组」
// 这条本来能成功的路会被判错。
//
// `db` 为 nil ⇒ 具名失败（`data.ErrDBMissing`），**不许静默成空表**：
// 空表会让「有人带了模组」静默退化成「无模组」，而 MAA 那侧会因此少一条要求。
func ModuleTable(db *sql.DB) (map[string]ModuleInfo, error) {
	if db == nil {
		return nil, fmt.Errorf("%w：这一份打法里有人带了模组 id，导出需要模组表，"+
			"但调用方没给出库句柄", data.ErrDBMissing)
	}
	rows, err := db.Query(`select module_id, name, type_name2 from module`)
	if err != nil {
		return nil, fmt.Errorf("读 module 表失败：%w", err)
	}
	defer rows.Close()
	out := map[string]ModuleInfo{}
	for rows.Next() {
		var id string
		var name, typeName2 sql.NullString
		if err := rows.Scan(&id, &name, &typeName2); err != nil {
			return nil, fmt.Errorf("扫 module 行失败：%w", err)
		}
		out[id] = ModuleInfo{ModuleID: id, Name: name.String, TypeName2: typeName2.String}
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("遍历 module 表失败：%w", err)
	}
	return out, nil
}

// SkillUsage 复刻 `maa_export.py:172-197`：MAA 的 `skill_usage` 该填 0 还是 1。
//
// 文档口径：`1` = 好了就用；`0` = 不自动使用（交给 `actions`），并注明
// 「**如果是全自动的技能，填 0**」。所以按技能的触发方式分流：
// `AUTO`（自动触发）填 0，游戏自己会开；`MANUAL` / `PASSIVE` 填 1，让 MAA 点。
//
// 取不到技能信息时返回 1。理由：`1`（好了就用）在「其实该手动」时会频繁开技能、
// 结果偏激进；返回 0 则会让一份依赖技能的打法**根本不开技能**，是更坏的一侧。
// **吞掉查询异常是口径不是疏忽**（Python 那侧 `:180-183` 的注释写明了同一句话）。
//
// 三条前提：
//   - `slot == 0` ⇒ 直接 0（Python `:184-185`，**先于一切**）；
//   - 触发方式不随专精变化（实测 level=7 与 level=max 的 skill_type 逐条相同），
//     所以固定查 level = 7；
//   - 用 `operator_skill.slot` 定位技能，而不是任何 char_id 拼接出来的东西。
func SkillUsage(db *sql.DB, charID string, slot int) int {
	if slot == 0 {
		return 0
	}
	if charID == "" || db == nil {
		return 1
	}
	const q = `select l.skill_type from operator_skill s
	             join skill_level l on l.skill_id = s.skill_id and l.level = 7
	            where s.char_id = ? and s.slot = ?`
	var skillType sql.NullString
	if err := db.QueryRow(q, charID, slot).Scan(&skillType); err != nil {
		// 没有这个槽号 / 查不到这名干员 / 库本身有问题 —— 一律 1，与 Python 同侧。
		return 1
	}
	if strings.ToUpper(strings.TrimSpace(skillType.String)) == "AUTO" {
		return 0
	}
	return 1
}
