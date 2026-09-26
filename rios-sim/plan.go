package main

// core 垫片：打法与名册的类型、解析都搬进了可导入的包 `rios-sim/core`，
// 这里只留类型别名与函数转发。
//
// **为什么要搬**：根目录全是 `package main`，别的包 import 不了它
// ⇒ MAA 导出（它唯一的 Go 调用方是界面）只能二选一：复制一份类型
// （迟早要漂），或者绕道子进程 IPC。纯数据类型提到 `core` 之后两条都不用。
//
// **为什么根包可以一行不改**：别名与转发都是编译期无成本的 ——
// `PlayPlan` 就是 `core.PlayPlan`（类型身份不变，方法照旧可用），
// 函数只是把调用点转进去。原先引用这些名字的 8 个文件因此一个字都不用动。
//
// **实测代价（别照抄「零成本」这句话）**：引擎 exe 由 5,077,504 变成
// 5,080,576 字节（+3,072，+0.06%）——那 5 个转发函数在符号表里各多了一份名字。
// 真正要守的那条性质没丢：`go version -m` 里**没有** `modernc.org/sqlite`
// （正对照：链了数据层的 TUI 有这一行）⇒ §7.4「最热的路径不替最冷的付钱」
// 仍然成立，多出来的是 3 KB，不是 5.6 MB。
//
// ⚠ 别在这里加方法：Go 不许给**外部类型**的别名定义方法。
// 要给 `PlayPlan` 添行为，去 `core` 里写（`Validate` 就是这么过去的）。

import (
	"encoding/json"

	"rios-sim/core"
)

type (
	PlayPlan     = core.PlayPlan
	DeployOrder  = core.DeployOrder
	RetreatOrder = core.RetreatOrder
	SkillOrder   = core.SkillOrder
)

// ReadPlan 读一份打法文件。转发到 core。
func ReadPlan(path string) (PlayPlan, error) { return core.ReadPlan(path) }

// ParsePlan 解析一份打法的 JSON 对象。转发到 core。
func ParsePlan(obj map[string]json.RawMessage) (PlayPlan, error) { return core.ParsePlan(obj) }
