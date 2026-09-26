// Package maa 把一份打法（`core.PlayPlan`）编译成 MAA copilot JSON。
//
// 它是 `ak_tactic/maa_export.py`（Python，488 行）的 Go 侧对应实现。
// **参照实现一直是那一份**，本包以「与它逐字节相同」为验收标准（判据见
// `maaexport_test.go` 与 `out/zz_maa_export_spec.md` §11）。
//
// 官方协议：<https://docs.maa.plus/zh-cn/protocol/copilot-schema.html>
//
// # 四处口径，都是查文档或实测定下来的，别凭直觉改
//
// 一、`stage_name` 用 **levelId**，不是 code。文档原文说「关卡中文名、code、
// stageId、levelId 等，只要能保证唯一均可」，而 code 恰恰不唯一（`SR-EX-8`
// 同时指着普通版与它的四星版）⇒ 选唯一的那个。
//
// 二、`module` 编号取的是模组**类型字母**：`X`→1、`Y`→2、`A`→3、`D`→4、`B`→5
// （MAA 文档「1-5 依次对应 χ、γ、α、Δ、β」）。原项目写的是 `{"X":1,"Y":2,"Z":3}`，
// 两处错：`Z` 在 905 条模组里一次都没出现（死项），而 `D` 漏了 —— 漏掉会让
// 那 6 条普通专属模组的要求被静默丢弃（实测分布：X 301 / Y 181 / A 20 / D 6 /
// B 1 / NULL 396 / Z 0）。
//
// 三、**没有生效模组时整个省略 `module` 键**。文档说「0 表示不使用模组」，
// 但博士实机确认写 `0` 会让整份作业不被识别（不是忽略这一条，是文件作废）。
// 省略 = 不作要求，在两种读法下都安全 ⇒ 取安全的那一侧。
//
// 四、`difficulty` 按关卡索引的 difficulty 填：`NORMAL`→1、`FOUR_STAR`→2、其余 0
// （0 时该键整个消失）。
//
// # 与 Python 的分道扬镳（**登记在案，不是 bug**）
//
// 干员练度取不到时（名册里没有这名干员、或名册为 nil），**Go 写 0，Python 印
// None**（`null` 与 `精None None  潜None`）。这是博士 2026-09-26 的裁定二：
// 练度取不到就写 0。⇒ 退化路径那条逐字节对拍**红是对的**，
// 判据按「Go 写 0 ∧ Python 印 None」记作登记分歧（见 `maaexport_test.go`）。
//
// # 取数面与渲染面分开
//
// 只有 `maaexport_db.go` 碰 sqlite（`ModuleTable` / `SkillUsage`）；
// 本文件的 `UsedOperators*` 与 `ToMaa` 拿到的都是**已经取好的**表与句柄。
// 这样渲染面可以纯函数式地测（喂一张手搭的表即可），也便于日后把取数面
// 搬去别处 —— 引擎二进制不该替数据层付体积（迁移图 §7.4）。
package maa

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strconv"
	"strings"

	"rios-sim/core"
)

// ErrNoDeploys 是「这份打法里一个部署都没有」——导出没有意义。
// 对应 Python 的 `MaaExportError`（那一侧只在这一处抛）。
var ErrNoDeploys = errors.New("这份打法里一个部署都没有，导出没有意义")

// ModuleSlots 是模组类型字母 → MAA 的 `module` 编号。见包文档第二节。
var ModuleSlots = map[string]int{"X": 1, "Y": 2, "A": 3, "D": 4, "B": 5}

// DifficultyCodes 是关卡索引的 difficulty → MAA 的 difficulty。见包文档第四节。
var DifficultyCodes = map[string]int{"NORMAL": 1, "FOUR_STAR": 2, "EASY": 0}

// DifficultyCode 复刻 `difficulty_code`（`:200-202`）：strip、upper、查不到给 0。
func DifficultyCode(s string) int { return DifficultyCodes[strings.ToUpper(strings.TrimSpace(s))] }

// ---------------------------------------------------------------- 逐项判定

// ModuleInfo 是 `module` 表里用得上的三列。空串表示「没有这一项」。
type ModuleInfo struct {
	ModuleID  string
	Name      string // uniEquipName，游戏里显示的那个名字（如「记忆残页」）
	TypeName2 string // 类型字母 X/Y/A/D/B；证章为空
}

// moduleType 复刻 `module_type`：id 空或不在表里 ⇒ nil。
//
// ⚠ **别解析 id 里的数字**：`uniequip_00N_xxx` 的 N 只是全表序号 ——
// 赤刃明霄陈 `uniequip_002_chen3` 是 X、圣聆初雪 `uniequip_002_sbell2` 是 Y，
// N 同为 2 而型别不同。
func moduleType(tbl map[string]ModuleInfo, moduleID *string) *string {
	if moduleID == nil || *moduleID == "" {
		return nil
	}
	t, ok := tbl[*moduleID]
	if !ok {
		return nil
	}
	letter := strings.ToUpper(strings.TrimSpace(t.TypeName2))
	if letter == "" {
		return nil
	}
	return &letter
}

// moduleName 复刻 `module_name`：取 `uniEquipName`，取不到给 nil。
func moduleName(tbl map[string]ModuleInfo, moduleID *string) *string {
	if moduleID == nil || *moduleID == "" {
		return nil
	}
	t, ok := tbl[*moduleID]
	if !ok {
		return nil
	}
	name := strings.TrimSpace(t.Name)
	if name == "" {
		return nil
	}
	return &name
}

// ModuleType / ModuleName / ModuleSlot 是上面两个函数的导出形态，供界面直接调用。
func ModuleType(tbl map[string]ModuleInfo, moduleID *string) *string {
	return moduleType(tbl, moduleID)
}

// ModuleName 见 moduleName。
func ModuleName(tbl map[string]ModuleInfo, moduleID *string) *string {
	return moduleName(tbl, moduleID)
}

// ModuleSlot 复刻 `module_slot`：模组 id → MAA 的 module 编号。
//
// **返回 nil 时调用方必须把 `module` 键整个省略**，不能写 0（见包文档第三节）。
func ModuleSlot(tbl map[string]ModuleInfo, moduleID *string) *int {
	t := moduleType(tbl, moduleID)
	if t == nil {
		return nil
	}
	n, ok := ModuleSlots[*t]
	if !ok {
		return nil
	}
	return &n
}

// ---------------------------------------------------------------- 用了哪些干员

// pickStr 复刻 `_pick`：打法自带的优先，退回名册。两者都没有 ⇒ nil。
func pickStr(a, b *string) *string {
	if a != nil {
		return a
	}
	return b
}

// pickInt 同 pickStr，整数版。
func pickInt(a, b *int) *int {
	if a != nil {
		return a
	}
	return b
}

// pickFloat 同 pickStr，浮点版。
func pickFloat(a, b *float64) *float64 {
	if a != nil {
		return a
	}
	return b
}

// UsedOperator 是「这份打法用到的某一名干员」及其练度要求。
//
// 字段与 Python `used_operators` 的字典**逐一对应**。其中 `ModuleName` /
// `ModuleType` / `ModuleLevel` 是给人看的（结果屏与 `doc.details` 都走 `ModText`），
// 进机器字段的只有 `ModuleSlot` —— 见 `ToMaa`：它逐键组装，多出来的键不会漏进 JSON。
type UsedOperator struct {
	Name      string
	Position  [2]int
	Direction string
	Skill     int
	Mastery   int
	// ⚠ Elite / Level / Potential 在本实现里**不会是 nil**：名册那侧的类型是
	// 非指针整数，取不到就是 0（裁定二）。这里保留指针是为了与 Python 的
	// `None` 语义对齐、也为了 `requirements` 的 null 分支有地方落。
	Elite      *int
	Level      *int
	Potential  *int
	Trust      *int
	Module     *string
	ModuleName *string
	ModuleType *string
	ModuleSlot *int
	// ⚠ ModuleLevel 在名册缺这个键时 Python 给 None、Go 给 0（0 与 None 在
	// `ModText` 里同样渲染成 `-`，所以只有直接 dump 这个结构体才看得出差别）。
	ModuleLevel *int
	Time        *float64
}

// UsedOperators 按部署顺序列出这份打法用到的干员及其练度要求。
//
// `roster` 可以为 nil（Python 的 `roster=None` 那条退化路）。
// `tbl` 为 nil 表示**没有模组表可用** ⇒ 一切模组字段都当「查不到」（nil）。
// 调用方要么先取好表，要么已经确认这份打法里没人带模组 —— `ToMaa` 就是这么做的
// （它按需惰性加载，复刻 Python `_uniequip` 的懒加载）。
func UsedOperators(plan core.PlayPlan, roster *core.RosterRead,
	tbl map[string]ModuleInfo) ([]UsedOperator, error) {
	byName := map[string]core.RosterEntry{}
	if roster != nil {
		for _, e := range roster.Entries {
			byName[e.Name] = e
		}
	}
	out := make([]UsedOperator, 0, len(plan.Deploys))
	for _, dep := range plan.Deploys {
		entry := byName[dep.Operator] // 名册里没有 ⇒ 零值
		mod := pickStr(dep.Module, entry.Module)
		out = append(out, UsedOperator{
			Name:      dep.Operator,
			Position:  dep.Position,
			Direction: dep.Direction,
			Skill:     dep.Skill,
			// 名册那侧没有 mastery 这一列，`_pick` 的退回永远是空 ⇒ 就是打法自带的值。
			Mastery: dep.Mastery,
			// 裁定二：取不到写 0（Python 写 None）。见包文档。
			Elite:       pickInt(dep.Elite, &entry.Elite),
			Level:       pickInt(dep.Level, &entry.Level),
			Potential:   pickInt(dep.Potential, &entry.Potential),
			Trust:       dep.Trust, // 名册那侧也没有 trust
			Module:      mod,
			ModuleName:  moduleName(tbl, mod),
			ModuleType:  moduleType(tbl, mod),
			ModuleSlot:  ModuleSlot(tbl, mod),
			ModuleLevel: pickInt(dep.ModuleLevel, &entry.ModuleLevel),
			Time:        dep.Time,
		})
	}
	return out, nil
}

// ModText 是一模组一格：`无` / `记忆残页 X 3` —— **模组名 类型字母 等级**。
//
// 两种「没有生效模组」都写 `无`：`module` 为空，或者名册记的是 `uniequip_001_*`
// 那枚**证章**（`typeName2` 为空）。证章不是模组，MAA 那侧同样是整键省略。
// 等级记不到（OperBox 名册没有模组等级）写 `-`，不编一个数。
func ModText(op UsedOperator) string {
	if op.Module == nil || *op.Module == "" || op.ModuleType == nil || *op.ModuleType == "" {
		return "无"
	}
	name := *op.Module
	if op.ModuleName != nil && *op.ModuleName != "" {
		name = *op.ModuleName
	}
	lv := "-"
	if op.ModuleLevel != nil && *op.ModuleLevel != 0 {
		lv = strconv.Itoa(*op.ModuleLevel)
	}
	return fmt.Sprintf("%s %s %s", name, *op.ModuleType, lv)
}

// levelText 复刻 report 那一列：None ⇒ `-`。
//
// ⚠ 在本实现里它几乎总不走 `-` 那一支 —— 练度取不到是 0 而不是空（裁定二）。
// 留着这一支是为了与 Python 的排版逐字对齐，且 `time` 那列仍会用到同样的写法。
func levelText(p *int) string {
	if p == nil {
		return "-"
	}
	return strconv.Itoa(*p)
}

// OperatorsReport 是「这份作业用了哪些干员」的人读表，返回**逐行**（不含表头之外的说明）。
//
// 导出写进 `doc.details`、界面显示在结果屏，用的是同一份文字 ——
// 两处各写一遍必然会漂。
func OperatorsReport(ops []UsedOperator) []string {
	if len(ops) == 0 {
		return []string{"（这份打法里没有部署任何干员）"}
	}
	lines := []string{
		"| # | 干员 | 落位 | 朝向 | 技能 | 精英 | 等级 | 潜能 | 模组 | 部署 |",
		"|---|---|---|---|---|---|---|---|---|---|",
	}
	for i, op := range ops {
		skill := "—"
		if op.Skill != 0 {
			skill = strconv.Itoa(op.Skill)
		}
		if op.Mastery != 0 {
			skill += "（专" + strconv.Itoa(op.Mastery) + "）"
		}
		t := "-"
		if op.Time != nil {
			t = fmt.Sprintf("%.0fs", *op.Time)
		}
		lines = append(lines, fmt.Sprintf(
			"| %d | %s | (%d, %d) | %s | %s | %s | %s | %s | %s | %s |",
			i+1, op.Name, op.Position[0], op.Position[1], op.Direction, skill,
			levelText(op.Elite), levelText(op.Level), levelText(op.Potential), ModText(op), t))
	}
	return lines
}

// OperatorsLines 是人读的编队清单，**终端用**（纯文本，非 Markdown）。
//
// 与 `OperatorsReport` 同源（都吃 `UsedOperators` 的产物），只是排版不同：
// 一个进 `doc.details` 给人看，一个给界面显示。
func OperatorsLines(ops []UsedOperator) []string {
	if len(ops) == 0 {
		return []string{"（这份打法里没有部署任何干员）"}
	}
	out := make([]string, 0, len(ops))
	for i, op := range ops {
		skill := "技—"
		if op.Skill != 0 {
			skill = "技" + strconv.Itoa(op.Skill)
		}
		if op.Mastery != 0 {
			skill += "专" + strconv.Itoa(op.Mastery)
		}
		t := ""
		if op.Time != nil {
			t = fmt.Sprintf("   %5.1fs", *op.Time)
		}
		out = append(out, fmt.Sprintf("%d. %s：(%d,%d) %s  %s  精%s %s  潜%s  模组 %s%s",
			i+1, op.Name, op.Position[0], op.Position[1], op.Direction, skill,
			levelText(op.Elite), levelText(op.Level), levelText(op.Potential),
			ModText(op), t))
	}
	return out
}

// OperatorsBrief 是一句话版：`赤刃明霄陈(精2 90 潜2 技3专3)｜圣聆初雪(…)`。
func OperatorsBrief(ops []UsedOperator) string {
	parts := make([]string, 0, len(ops))
	for _, op := range ops {
		seg := fmt.Sprintf("%s(精%s %s", op.Name, levelText(op.Elite), levelText(op.Level))
		if op.Potential != nil && *op.Potential != 0 {
			seg += " 潜" + strconv.Itoa(*op.Potential)
		}
		if op.Skill != 0 {
			seg += " 技" + strconv.Itoa(op.Skill)
			if op.Mastery != 0 {
				seg += "专" + strconv.Itoa(op.Mastery)
			}
		}
		seg += ")"
		parts = append(parts, seg)
	}
	if len(parts) == 0 {
		return "（无干员）"
	}
	return strings.Join(parts, "｜")
}

// ---------------------------------------------------------------- 组装

// MaaRequirements 是 MAA 的 `requirements`。**键序就是这里的字段序**：
// elite → level → skill_level → module → potential。
//
// ⚠ Elite / Level **没有** omitempty：Python 写的是 `null`，不是省略。
// ⚠ Module 有 omitempty：nil ⇒ 整键省略（**绝不写 0**，见包文档第三节）。
type MaaRequirements struct {
	Elite      *int `json:"elite"`
	Level      *int `json:"level"`
	SkillLevel int  `json:"skill_level"`
	Module     *int `json:"module,omitempty"`
	Potential  *int `json:"potential,omitempty"`
}

// MaaOper 是 `opers` 的一项。
type MaaOper struct {
	Name         string          `json:"name"`
	Skill        int             `json:"skill"`
	SkillUsage   int             `json:"skill_usage"`
	Requirements MaaRequirements `json:"requirements"`

	//: 助战那一格：**只写名字**（博士 2026-09-26：MAA 无法识别助战干员的练度）。
	//:
	//: 用私有标记而不是另立一个类型，是为了让 `[]MaaOper` 的其余消费点 ——
	//: 判据里那些 `job.Opers[i].SkillUsage` —— 不必全改成类型断言；
	//: 序列化交给下面的 `MarshalJSON` 收敛成 `{"name": …}`。
	supportOnly bool
}

// SupportOper 造一个「助战」条目。
//
// 助战是**好友的**干员，不属于本机名册：它的练度玩家填不了、MAA 也不认，
// 所以这一格只有名字。
func SupportOper(name string) MaaOper { return MaaOper{Name: name, supportOnly: true} }

// marshalNoEscape 是**不带 HTML 转义**的序列化。
//
// ⚠ 自定义 `MarshalJSON` 千万不能用 `json.Marshal` 实现：那会把内层重新按**默认**
// 口径转义（`<` `>` `&` 变成 `\u003c` 之类），而外层编码器的 `SetEscapeHTML(false)`
// **管不到已经序列化好的字节**。这不是理论风险 —— 第一版就是这么写的，
// `TestEscapeHTMLOff` 当场判红（干员名里的 `&` 被转义）。默认口径的转义规则见
// `MarshalJob` 的注释：Python 的 `ensure_ascii=False` 不转义它们。
func marshalNoEscape(v any) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	if err := enc.Encode(v); err != nil { // Encode 自带末尾换行，下面去掉
		return nil, err
	}
	return bytes.TrimRight(buf.Bytes(), "\n"), nil
}

// MarshalJSON 让助战条目只输出 `name` 一个键。
//
// ⚠ 用**别名类型**转发默认行为，否则会无限递归（`plain` 不带方法集）。
func (o MaaOper) MarshalJSON() ([]byte, error) {
	if o.supportOnly {
		return marshalNoEscape(struct {
			Name string `json:"name"`
		}{o.Name})
	}
	type plain MaaOper
	return marshalNoEscape(plain(o))
}

// MaaAction 是一条动作：Deploy 用 5 键、Retreat 用 2 键、
// SpeedUp / SkillDaemon 各用 1 键 —— 靠 omitempty 收敛成三种形状。
type MaaAction struct {
	Type      string `json:"type"`
	Name      string `json:"name,omitempty"`
	Location  []int  `json:"location,omitempty"`
	Direction string `json:"direction,omitempty"`
	Doc       string `json:"doc,omitempty"`
}

// MaaDoc 是 `doc`。
type MaaDoc struct {
	Title   string `json:"title"`
	Details string `json:"details"`
}

// MaaJob 是一份 MAA copilot 作业。
//
// ⚠ 字段序就是 JSON 的键序（Go 按声明序输出）。**上位协议的键序在 §9.4 里
// 是逐字节对齐的硬点**，所以这里不许重排、不许用 map 组装。
type MaaJob struct {
	StageName       string      `json:"stage_name"`
	Opers           []MaaOper   `json:"opers"`
	Groups          []any       `json:"groups"` // 必须是空数组而不是 null
	Actions         []MaaAction `json:"actions"`
	MinimumRequired string      `json:"minimum_required"`
	Doc             MaaDoc      `json:"doc"`
	Difficulty      int         `json:"difficulty,omitempty"` // 0 ⇒ 整个键消失
}

// MaaOptions 是导出时可调的那几项。零值即 Python 的缺省。
type MaaOptions struct {
	StageName       string // 空 ⇒ 用 plan.Stage（levelId，见包文档第一节）
	Difficulty      string // 关卡索引里的 difficulty 原文
	Title           string // 空 ⇒ 用 plan.Title ⇒ 再退成「N 人」
	Details         string // 追加在编队表后面的人读说明
	MinimumRequired string // 空 ⇒ v6.0.0（Python 的形参缺省）

	//: 助战干员的名字。非空 ⇒ `opers` 末尾多一格（**只写名字**、不带练度），
	//: 编队总数因此是 12 ＋ 1 = 13。MAA 会自己挑助战，不需要别的写法
	//: （博士 2026-09-26 裁定）。
	//:
	//: ⚠ **未核**：MAA 官方协议原文没有取过（`out/zz_maa_export_spec.md` §12
	//: 早已挂着这一条），所以「一个只有 `name` 的 `opers` 条目能不能被吃下、
	//: 要不要带 `requirements`／`skill_usage`」**没验过** —— 这是本包唯一一处
	//: 没有 Python 参照、也没有官方文档背书的形状。核法：在 MAA 里实机导入一份
	//: 带 13 人的作业（判据比不了它，只能人验）。
	SupportName string
}

// DefaultMinimumRequired 是 Python 形参的缺省值。
const DefaultMinimumRequired = "v6.0.0"

// hasModule 报告这份打法里有没有人带**非空**模组 id。
// 它是惰性加载的判据：一个都没有就**不许碰** `module` 表。
func hasModule(plan core.PlayPlan) bool {
	for _, dep := range plan.Deploys {
		if dep.Module != nil && *dep.Module != "" {
			return true
		}
	}
	return false
}

// ToMaa 组装 MAA copilot JSON。
//
// `stage_name` 缺省用 `plan.Stage`（levelId），**这是刻意的** —— 见包文档第一节。
//
// # 为什么不写每次部署的时刻
//
// 协议里 Deploy 动作**根本没有 `time` 字段**。而 MAA 对 Deploy 的默认行为是
// 「当费用不够时一直等到够」，与本项目解算时排时刻的规则是同一条；
// 写 `pre_delay` 反而会把同一段等待算两遍。`UsedOperator.Time` 只用于给人看。
//
// # 惰性与具名失败
//
// `tbl` 为 nil 且这份打法里有人带模组 ⇒ 调 `ModuleTable(db)` 现取；
// 库不在就**具名失败**（`data.ErrDBMissing`），不许静默退化成「无模组」。
// 反过来，没人带模组时**完全不碰库** —— 这条退化路在 Python 那边也是成功的
// （`module_type(None)` 提前返回）。`db` 为 nil 时同上：有人带模组才报缺库。
func ToMaa(plan core.PlayPlan, roster *core.RosterRead, tbl map[string]ModuleInfo,
	db *sql.DB, opt MaaOptions) (MaaJob, error) {
	if len(plan.Deploys) == 0 {
		return MaaJob{}, ErrNoDeploys
	}
	if tbl == nil && hasModule(plan) {
		t, err := ModuleTable(db)
		if err != nil {
			return MaaJob{}, err
		}
		tbl = t
	}
	ops, err := UsedOperators(plan, roster, tbl)
	if err != nil {
		return MaaJob{}, err
	}

	opers := make([]MaaOper, 0, len(ops)+1)
	for _, op := range ops {
		req := MaaRequirements{
			Elite: op.Elite, Level: op.Level,
			// 官方口径：1–7 是技能等级，8/9/10 即专一/专二/专三
			SkillLevel: 7 + op.Mastery,
		}
		if op.ModuleSlot != nil {
			req.Module = op.ModuleSlot
		}
		if op.Potential != nil {
			req.Potential = op.Potential
		}
		opers = append(opers, MaaOper{
			Name: op.Name, Skill: op.Skill,
			SkillUsage:   SkillUsage(db, charIDOf(roster, op.Name), op.Skill),
			Requirements: req,
		})
	}
	//: 助战那一格加在**末尾**（第 13 位）。它**不进** `doc.details` 的人读编队表 ——
	//: 那一份写的是「这份打法部署了谁」，而助战是**要求**不是部署。
	if opt.SupportName != "" {
		opers = append(opers, SupportOper(opt.SupportName))
	}

	actions := make([]MaaAction, 0, len(ops)+len(plan.Retreats)+2)
	for _, op := range ops {
		skill := "—"
		if op.Skill != 0 {
			skill = strconv.Itoa(op.Skill)
		}
		actions = append(actions, MaaAction{
			Type: "Deploy", Name: op.Name,
			Location:  []int{op.Position[0], op.Position[1]},
			Direction: op.Direction,
			Doc: fmt.Sprintf("%s  技能%s（专%d）  精%s %s  潜%s",
				op.Name, skill, op.Mastery, levelText(op.Elite), levelText(op.Level),
				levelText(op.Potential)),
		})
	}
	for _, r := range plan.Retreats {
		actions = append(actions, MaaAction{Type: "Retreat", Name: r.Operator})
	}
	actions = append(actions, MaaAction{Type: "SpeedUp"}, MaaAction{Type: "SkillDaemon"})

	// 「写明使用了哪些干员」——人读的那一份进 doc.details，机器读的那一份是 opers。
	head := append([]string{"【编队】" + OperatorsBrief(ops), ""}, OperatorsReport(ops)...)
	merged := strings.Join(head, "\n")
	if body := strings.TrimSpace(opt.Details); body != "" {
		merged += "\n\n" + body
	}

	title := opt.Title
	if title == "" {
		title = plan.Title
	}
	if title == "" {
		title = fmt.Sprintf("%d 人", len(plan.Deploys))
	}
	stageName := opt.StageName
	if stageName == "" {
		stageName = plan.Stage
	}
	minimum := opt.MinimumRequired
	if minimum == "" {
		minimum = DefaultMinimumRequired
	}

	job := MaaJob{
		StageName:       stageName,
		Opers:           opers,
		Groups:          []any{},
		Actions:         actions,
		MinimumRequired: minimum,
		Doc:             MaaDoc{Title: title, Details: merged},
	}
	if code := DifficultyCode(opt.Difficulty); code != 0 {
		job.Difficulty = code
	}
	return job, nil
}

// charIDOf 从名册里取某位干员的 char_id。**只从名册取**（与 Python 同口径：
// 打法那侧没有 char_id，只有中文名）。
func charIDOf(roster *core.RosterRead, name string) string {
	if roster == nil {
		return ""
	}
	for _, e := range roster.Entries {
		if e.Name == name {
			return e.CharID
		}
	}
	return ""
}

// ---------------------------------------------------------------- 落盘

// unsafeName 复刻 Python 的 `_SAFE = re.compile(r'[\\/:*?"<>|\x00-\x1f]')`。
var unsafeName = regexp.MustCompile(`[\\/:*?"<>|\x00-\x1f]`)

// MarshalJob 把作业序列化成**与 Python 逐字节相同**的形态。
//
// Python 那侧是 `json.dumps(data, ensure_ascii=False, indent=2) + "\n"`：
// 不转义非 ASCII、缩进两格、末尾一个换行。Go 的 `json.MarshalIndent` 做不到 ——
// 它默认转义 HTML（`<` `>` `&`）⇒ 必须走 Encoder 并关掉 SetEscapeHTML。
func MarshalJob(job MaaJob) ([]byte, error) {
	var buf bytes.Buffer
	enc := json.NewEncoder(&buf)
	enc.SetEscapeHTML(false)
	enc.SetIndent("", "  ")
	if err := enc.Encode(job); err != nil { // Encode 自带末尾换行
		return nil, fmt.Errorf("序列化作业失败：%w", err)
	}
	return buf.Bytes(), nil
}

// JobDir 是 `<guides>/<关卡名>/`。关卡名取全称（`SR-EX-8`），**不缩写、不转小写**。
func JobDir(guidesDir, stageCode string) string {
	return filepath.Join(guidesDir, stageCode)
}

// NextIndex 是已有序号的最大值 + 1。**按加入顺序编号**，不覆盖已有作业。
func NextIndex(dir, stageCode string) int {
	entries, err := os.ReadDir(dir)
	if err != nil {
		return 1
	}
	pat := regexp.MustCompile(`(?i)^` + regexp.QuoteMeta(stageCode) + `-(\d+)\.json$`)
	max := 0
	for _, e := range entries {
		if e.IsDir() {
			continue
		}
		m := pat.FindStringSubmatch(e.Name())
		if m == nil {
			continue
		}
		n, err := strconv.Atoi(m[1])
		if err != nil {
			continue
		}
		if n > max {
			max = n
		}
	}
	return max + 1
}

// WriteJob 写出 `<guides>/<关卡名>/<关卡名>-<序号>.json`，返回路径。
//
// 序号是**追加**的：同一天导出两次会得到 `-1.json` 与 `-2.json`，
// 不会把上一份冲掉。作业文件里写着玩家自己的编队，所以 `Guides/` 在 `.gitignore` 里。
func WriteJob(job MaaJob, guidesDir, stageCode string) (string, error) {
	name := unsafeName.ReplaceAllString(strings.TrimSpace(stageCode), "_")
	if name == "" {
		name = "stage"
	}
	dir := JobDir(guidesDir, name)
	if err := os.MkdirAll(dir, 0o755); err != nil {
		return "", fmt.Errorf("建目录 %s 失败：%w", dir, err)
	}
	path := filepath.Join(dir, fmt.Sprintf("%s-%d.json", name, NextIndex(dir, name)))
	blob, err := MarshalJob(job)
	if err != nil {
		return "", err
	}
	if err := os.WriteFile(path, blob, 0o644); err != nil {
		return "", fmt.Errorf("写 %s 失败：%w", path, err)
	}
	return path, nil
}

// SortedNames 给界面用：名册里的名字按码点序（Python 的 `sorted()`）。
func SortedNames(roster *core.RosterRead) []string {
	if roster == nil {
		return nil
	}
	out := append([]string(nil), roster.Names...)
	sort.Strings(out)
	return out
}
