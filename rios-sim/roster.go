package main

// 名册侧的 core 垫片，理由与 `plan.go` 顶部那段相同。
//
// 一处细节：`ParseRosterBlob` 在 core 里是**导出**的（跨包必须），
// 而这里保留原来的小写名字 —— 调用点（`buildspec.go`）不该为了搬包而改名，
// 改名会让这次搬迁从「零成本」变成「要重新审一遍调用点」。

import (
	"encoding/json"

	"rios-sim/core"
)

type (
	RosterEntry = core.RosterEntry
	RosterRead  = core.RosterRead
)

// ReadRoster 读一份名册文件。转发到 core。
func ReadRoster(path string) (RosterRead, error) { return core.ReadRoster(path) }

// ParseRoster 解析一份名册 JSON。转发到 core。
func ParseRoster(raw json.RawMessage) (RosterRead, error) { return core.ParseRoster(raw) }

func parseRosterBlob(data []byte, label string) (RosterRead, error) {
	return core.ParseRosterBlob(data, label)
}
