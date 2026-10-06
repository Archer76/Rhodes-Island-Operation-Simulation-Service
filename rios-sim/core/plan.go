package core

import (
	"encoding/json"
	"fmt"
	"os"
	"strconv"
	"strings"
)

// plan.go：Go 直读打法（计划）（丙阶段四·第十三批）。
//
// ## 为什么还要读它
//
// 目标里写的是「Go 直读 `data/gamedata` ＋ 名册 ＋ **计划**」。名册上一轮进来了，
// 计划这一层在 Go 侧同样是零入口——没有它，就算折算与名册都齐了，Go 也不知道
// **谁在什么时候站到哪一格、什么时刻开技能**，规格仍然构造不出来。
//
// 权威是 `ak_tactic/plan.py:249-354` 的 `Plan.from_dict` ＋ `:262-289` 的
// `validate`。下面逐条复刻，几处容易读错：
//
//   - `elite` / `level` / `potential` / `trust` / `module_level` / `time` 走的是
//     **`is None`**，不是 `or`：`"elite": 0` 就是 **0**，不是「没给」。
//     而 `skill` / `mastery` 走 `or 0`。同一个文件里两种兜底方式并存，别抄混。
//   - `module` 是**原样收下**（`d.get("module")`），空串就是空串、**不是** None。
//     这一点与名册那边（`or None`）相反。
//   - `auto_skill` 的缺省是 **True**（`d.get("auto_skill", True)`），但 `bool()`
//     作用在取到的值上 ⇒ `"auto_skill": null` 是 **False**（缺省 True、
//     显式 null 却 False）。
//   - `position` 走 `or` 链（`position` → `pos` → `location`），而
//     `[0, 0]` 是非空列表、**取真**，不会被跳过。
//   - **`from_dict` 之外还有 `__post_init__`**（`plan.py:128-141`），它做三件事，
//     只读 `from_dict` 会**三处全漏**：
//     ① 坐标 `int()` **截断**（`5.7` → `5`，不是保留小数）；
//     ② 朝向必须 ∈ `DIRECTIONS = (Right, Left, Up, Down)`，表外**报错**；
//     ③ 技能槽必须 `0 ≤ skill ≤ 3`，越界**报错**。
//     ②③ 尤其要紧：漏了它们，Go 会在**放宽**的方向上与原版分叉——原版拒收的
//     东西 Go 收下了，症状是「这名干员的朝向/技能槽没人认得」而一路不报错。
//   - `validate` 拦两条会**静默出错**的事：同一干员部署两次（要再上一次得先
//     撤退）、两个干员挤在同一格（模拟器不校验，会让两个单位重叠着跑完，
//     产出一个「看着对」的结果）。
//     ★ **第一条按博士 2026-09-29 的裁定放宽了**（第二条仍拦），见
//     `Validate` 的说明——那不是漏改，是刻意与原版分道。
//
// ## 一条本轮**没有**接的分支（具名拒收，不静默）
//
// `skill` 除了整数还可以是**对象**（丙方案，PM 2026-09-20 批准），那一支要
// `_skill_from_json` 去查技能书、把槽位/等级解成技能 id。本轮未接，所以碰到
// 对象就**具名报错**——不假装读懂了。24 份夹具的 `skill` 全是整数，
// 走的是与改动前逐字节同一条路。
//
// ## 一处类型纪律（与名册同一套）
//
// 凡原版**不约束类型**就原样收下的字符串字段（`operator` / `name` /
// `direction` / `facing` / `module` / `stage` / `title` / `notes`），Go 一律
// 拒收非字符串并具名报错：那种值到了下游只会变成取不到的键或不认识的朝向，
// 静默收下比报错危险。判据对每一处都要求「Go 拒 ∧ 原版收」同时成立。

// DeployOrder 是一条部署。
//
// `Position` 是**整数**格：原版 `__post_init__` 头一件事就是
// `int(self.position[0]), int(self.position[1])`，小数会被向零截断。
type DeployOrder struct {
	Operator    string   `json:"operator"`
	Position    [2]int   `json:"position"`
	Direction   string   `json:"direction"`
	Skill       int      `json:"skill"`
	Mastery     int      `json:"mastery"`
	MasterySet  bool     `json:"-"`
	SkillLevel  *int     `json:"skill_level,omitempty"`
	Elite       *int     `json:"elite"`
	Level       *int     `json:"level"`
	Potential   *int     `json:"potential"`
	Trust       *int     `json:"trust"`
	Module      *string  `json:"module"`
	ModuleLevel *int     `json:"module_level"`
	Time        *float64 `json:"time"`
	AutoSkill   bool     `json:"auto_skill"`
}

// RetreatOrder 是一条撤退。
type RetreatOrder struct {
	Operator string  `json:"operator"`
	Time     float64 `json:"time"`
}

// SkillOrder 是一条开技能。
type SkillOrder struct {
	Operator string  `json:"operator"`
	Time     float64 `json:"time"`
	Slot     int     `json:"slot"`
}

// PlayPlan 是一份完整的打法。
//
// ⚠ 不叫 `Plan`：本包里 `Spec` 一族已经在用「规格」这个词，而「计划」是它的
// 上游输入，两个名字混在一起读代码时会分不清谁喂谁。
type PlayPlan struct {
	Stage    string         `json:"stage"`
	Deploys  []DeployOrder  `json:"deploys"`
	Retreats []RetreatOrder `json:"retreats"`
	Skills   []SkillOrder   `json:"skills"`
	Title    string         `json:"title"`
	Notes    string         `json:"notes"`
}

// pyIntOrNil 复刻 `None if d.get(k) is None else int(d[k])`。
//
// ★ 与 `pyIntOr` 的区别是**判空的方式**：这里只认「键不在」与「值是 null」，
// `0` / `""` 都不算空。`"elite": 0` 必须得 0。
func pyIntOrNil(m map[string]json.RawMessage, key string) (*int, error) {
	raw, ok := m[key]
	if !ok || strings.TrimSpace(string(raw)) == "null" {
		return nil, nil
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err == nil {
		n := int(f)
		return &n, nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		n, err2 := strconv.Atoi(strings.TrimSpace(s))
		if err2 != nil {
			return nil, fmt.Errorf("字段 %s 不是整数：%q", key, s)
		}
		return &n, nil
	}
	return nil, fmt.Errorf("字段 %s 不是整数：%s", key, string(raw))
}

// pyFloatOrNil 复刻 `None if d.get(k) is None else float(d[k])`。
func pyFloatOrNil(m map[string]json.RawMessage, key string) (*float64, error) {
	raw, ok := m[key]
	if !ok || strings.TrimSpace(string(raw)) == "null" {
		return nil, nil
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err == nil {
		return &f, nil
	}
	var s string
	if err := json.Unmarshal(raw, &s); err == nil {
		f, err2 := strconv.ParseFloat(strings.TrimSpace(s), 64)
		if err2 != nil {
			return nil, fmt.Errorf("字段 %s 不是数：%q", key, s)
		}
		return &f, nil
	}
	return nil, fmt.Errorf("字段 %s 不是数：%s", key, string(raw))
}

// pyStrOr 复刻 `d.get(a) or d.get(b) or dflt`（只接两个键的那种）。
func pyStrOr(m map[string]json.RawMessage, a, b, dflt string) (string, error) {
	s, ok, err := pyStrStrict(m, a)
	if err != nil {
		return "", err
	}
	if ok {
		return s, nil
	}
	s, ok, err = pyStrStrict(m, b)
	if err != nil {
		return "", err
	}
	if ok {
		return s, nil
	}
	return dflt, nil
}

// directions 是原版 `plan.py:31` 的 `DIRECTIONS`——`__post_init__` 会拒掉表外的值。
var directions = map[string]bool{
	"Right": true, "Left": true, "Up": true, "Down": true,
}

func readPosition(raw json.RawMessage) ([2]int, error) {
	var out [2]int
	var parts []json.RawMessage
	if err := json.Unmarshal(raw, &parts); err != nil {
		return out, fmt.Errorf("坐标 %s 不是数组", string(raw))
	}
	if len(parts) != 2 {
		return out, fmt.Errorf("坐标 %s 不是 [x, y] 两元组", string(raw))
	}
	for i, p := range parts {
		var f float64
		if err := json.Unmarshal(p, &f); err == nil {
			out[i] = int(f) //: 向零截断，与 Python 的 int() 同义
			continue
		}
		var s string
		if err := json.Unmarshal(p, &s); err == nil {
			n, err2 := strconv.Atoi(strings.TrimSpace(s))
			if err2 != nil {
				return out, fmt.Errorf("坐标 %s 的第 %d 个元素不是整数",
					string(raw), i+1)
			}
			out[i] = n
			continue
		}
		return out, fmt.Errorf("坐标 %s 的第 %d 个元素不是整数", string(raw), i+1)
	}
	return out, nil
}

// ReadPlan 直读一份打法文件。
func ReadPlan(path string) (PlayPlan, error) {
	var plan PlayPlan
	data, err := os.ReadFile(path)
	if err != nil {
		return plan, fmt.Errorf("打法读不出来：%v", err)
	}
	//: ⚠ **不清 BOM**。`Plan.load`（`plan.py:356-358`）读的是 `encoding="utf-8"`，
	//: 带 BOM 的文件在原版那边 `json.loads` 就会抛——清了 BOM 等于比原版宽容，
	//: 于是「Go 能跑而原版跑不了」这种分歧会在最不该有分歧的地方冒出来。
	//: 对比：**名册那边是 `utf-8-sig`**，必须清。两份权威在这一点上口径不同，
	//: 谁也不能照谁抄。
	var obj map[string]json.RawMessage
	if err := json.Unmarshal(data, &obj); err != nil {
		return plan, fmt.Errorf("打法文件的顶层必须是一个对象：%v", err)
	}
	return ParsePlan(obj)
}

// ParsePlan 复刻 `Plan.from_dict`，末尾照样跑一遍 `validate`。
func ParsePlan(obj map[string]json.RawMessage) (PlayPlan, error) {
	var plan PlayPlan

	//: `data.get("deploys") or data.get("deploy") or []`——注意 `or`，空数组会落到下一个键。
	var rawDeploys []json.RawMessage
	if raw, ok := obj["deploys"]; ok && !pyFalsy(raw) {
		if err := json.Unmarshal(raw, &rawDeploys); err != nil {
			return plan, fmt.Errorf("deploys 不是数组：%v", err)
		}
	} else if raw, ok := obj["deploy"]; ok && !pyFalsy(raw) {
		if err := json.Unmarshal(raw, &rawDeploys); err != nil {
			return plan, fmt.Errorf("deploy 不是数组：%v", err)
		}
	}

	for i, row := range rawDeploys {
		var m map[string]json.RawMessage
		if err := json.Unmarshal(row, &m); err != nil {
			return plan, fmt.Errorf("第 %d 条部署不是对象", i+1)
		}
		name, err := pyStrOr(m, "operator", "name", "")
		if err != nil {
			return plan, fmt.Errorf("第 %d 条部署的 %v", i+1, err)
		}
		//: 坐标走 `or` 链；`[0, 0]` 是非空列表、取真，不会被跳过。
		var posRaw json.RawMessage
		for _, key := range []string{"position", "pos", "location"} {
			if raw, ok := m[key]; ok && !pyFalsy(raw) {
				posRaw = raw
				break
			}
		}
		if name == "" || posRaw == nil {
			return plan, fmt.Errorf("第 %d 条部署缺 operator 或 position", i+1)
		}
		pos, err := readPosition(posRaw)
		if err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		dir, err := pyStrOr(m, "direction", "facing", "Right")
		if err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		//: `__post_init__` 第 ② 条：朝向必须在表里。漏了它，Go 会在**放宽**的
		//: 方向上与原版分叉（原版拒收的朝向 Go 收下了，一路不报错）。
		if !directions[dir] {
			return plan, fmt.Errorf("%s 的朝向 %q 不认识，只能是 Right/Left/Up/Down 之一",
				name, dir)
		}
		d := DeployOrder{Operator: name, Position: pos, Direction: dir}

		//: `skill` 为对象那一支（丙方案）要查技能书，本轮未接——具名拒收。
		if raw, ok := m["skill"]; ok && !pyFalsy(raw) &&
			strings.TrimSpace(string(raw))[0] == '{' {
			return plan, fmt.Errorf(
				"%s 的 skill 是对象：`_skill_from_json` 那一支（按槽位/等级解成技能 id）本轮未接",
				name)
		}
		if raw, ok := m["skill"]; ok && strings.TrimSpace(string(raw)) != "null" {
			if d.Skill, err = trainingInt(raw, "skill", 0, 3); err != nil {
				return plan, fmt.Errorf("%s 的%v", name, err)
			}
		}
		//: `__post_init__` 第 ③ 条：技能槽 0–3。
		if d.Skill < 0 || d.Skill > 3 {
			return plan, fmt.Errorf("%s 的技能槽 %d 越界（0–3）", name, d.Skill)
		}
		if raw, ok := m["mastery"]; ok && strings.TrimSpace(string(raw)) != "null" {
			d.MasterySet = true
			if d.Mastery, err = trainingInt(raw, "mastery", 0, 3); err != nil {
				return plan, fmt.Errorf("%s 的%v", name, err)
			}
		}
		if raw, ok := m["skill_level"]; ok && strings.TrimSpace(string(raw)) != "null" {
			v, e := trainingInt(raw, "skill_level", 1, 10)
			if e != nil {
				return plan, fmt.Errorf("%s 的%v", name, e)
			}
			d.SkillLevel = &v
		}
		if d.Elite, err = pyIntOrNil(m, "elite"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		if d.Level, err = pyIntOrNil(m, "level"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		if d.Potential, err = pyIntOrNil(m, "potential"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		if d.Trust, err = pyIntOrNil(m, "trust"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		//: `module` 是**原样收下**：空串就是空串，**不是** None（与名册相反）。
		if raw, ok := m["module"]; ok && strings.TrimSpace(string(raw)) != "null" {
			var s string
			if err := json.Unmarshal(raw, &s); err != nil {
				return plan, fmt.Errorf("%s 的 module 不是字符串：%s", name, string(raw))
			}
			d.Module = &s
		}
		if d.ModuleLevel, err = pyIntOrNil(m, "module_level"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		if d.Time, err = pyFloatOrNil(m, "time"); err != nil {
			return plan, fmt.Errorf("%s 的%v", name, err)
		}
		//: 缺省 True；但值取到了就 `bool()` 它 ⇒ 显式 null 是 **False**。
		d.AutoSkill = true
		if raw, ok := m["auto_skill"]; ok {
			d.AutoSkill = !pyFalsy(raw)
		}
		plan.Deploys = append(plan.Deploys, d)
	}

	stage, err := pyStrOr(obj, "stage", "__none__", "")
	if err != nil {
		return plan, err
	}
	plan.Stage = stage
	if plan.Title, err = pyStrOr(obj, "title", "__none__", ""); err != nil {
		return plan, err
	}
	if plan.Notes, err = pyStrOr(obj, "notes", "__none__", ""); err != nil {
		return plan, err
	}

	if raw, ok := obj["retreats"]; ok && !pyFalsy(raw) {
		var rows []map[string]json.RawMessage
		if err := json.Unmarshal(raw, &rows); err != nil {
			return plan, fmt.Errorf("retreats 不是数组：%v", err)
		}
		for i, r := range rows {
			op, err := pyStrOr(r, "operator", "__none__", "")
			if err != nil || op == "" {
				return plan, fmt.Errorf("第 %d 条撤退缺 operator", i+1)
			}
			t, err := pyFloatOrNil(r, "time")
			if err != nil || t == nil {
				return plan, fmt.Errorf("第 %d 条撤退缺 time", i+1)
			}
			plan.Retreats = append(plan.Retreats, RetreatOrder{Operator: op, Time: *t})
		}
	}
	if raw, ok := obj["skills"]; ok && !pyFalsy(raw) {
		var rows []map[string]json.RawMessage
		if err := json.Unmarshal(raw, &rows); err != nil {
			return plan, fmt.Errorf("skills 不是数组：%v", err)
		}
		for i, r := range rows {
			op, err := pyStrOr(r, "operator", "__none__", "")
			if err != nil || op == "" {
				return plan, fmt.Errorf("第 %d 条开技能缺 operator", i+1)
			}
			t, err := pyFloatOrNil(r, "time")
			if err != nil || t == nil {
				return plan, fmt.Errorf("第 %d 条开技能缺 time", i+1)
			}
			slot, err := pyIntOr(r, "slot", 0)
			if err != nil {
				return plan, fmt.Errorf("第 %d 条开技能的 %v", i+1, err)
			}
			plan.Skills = append(plan.Skills,
				SkillOrder{Operator: op, Time: *t, Slot: slot})
		}
	}

	if err := plan.Validate(); err != nil {
		return plan, err
	}
	return plan, nil
}

// Validate 复刻 `Plan.validate`（`plan.py:262-289`），**其中一条按博士 2026-09-29
// 的裁定放宽**（下面「放宽的那一处」）。
//
// # 放宽的那一处：同一干员的二次部署
//
// 博士 2026-09-29 定的规则：「不允许一个干员**同时在场上**出现两次，但如果被击倒
// ／撤退回到待部署区、且再部署冷却结束，则可以再次部署。」
//
// 这条规则**是运行期的**，计划层判不了：要知道「这位此刻在不在场上」（取决于有没有
// 被打死）与「离场多久了」（取决于撤退／阵亡的时刻）。所以计划层**不再拦**，把真值
// 交给模拟器——它本来就有那两道具名拒收（`sim.go` 的 `_can_deploy_again` 复刻），
// 落进 `verdict.deploy_rejected` 的 `(时刻, 名字, 原因)` 里，**不是静默**：
//
//	· sim.go:609  「同一干员已在场」   —— 活着且在场上 ⇒ 拒；
//	· sim.go:615  「再部署冷却中」     —— 离场未满 `RedeployTime` ⇒ 拒。
//
// ⚠ **两件事不能混**：`Sim` 里那条「同一干员已在场」判的是 `cur.alive()`——阵亡的
// 不算在场，所以「落地→阵亡→冷却过后再落」这条路**走得通**；而计划层想表达同样的
// 意思就必须知道死没死，静态文本里没有这个信息。**拦在计划层是把该模拟器判的事
// 提前判死**（`docs/retreat-audit.md` §2.4 里那条 `SYNTHETIC-redeploy-twice` 的
// 症状就是它：真值由模拟器给，计划层却先拒了）。
//
// ⚠ **这是与 Python 侧的一处刻意分歧**：`plan.py:270-274` 仍无条件拒收。
// `tools/check_plan_go.py` 的「同一人部署两次」一条因此从 `both-refuse` 改判为
// `go-accept-only`（Go 收下、模拟器判），见该文件里那条守卫的说明。
//
// # 仍拦的那一处：同一格
//
// 两个干员挤在同一格**仍然拒收**——**两个模拟器都不校验占格**，放行会让两个单位
// 重叠着跑完，产出「看着对」的结果。要按同一套运行期语义放开它，得先在模拟器里加
// 一条具名占格拒收（现在没有），所以这里**先不放开**：**这是能力缺口，不是裁定**。
// 副作用要具名——**同一干员在同一格「撤了再上」也会撞到这条**。
func (p PlayPlan) Validate() error {
	if p.Stage == "" {
		return fmt.Errorf("打法必须有关卡号（stage）")
	}
	if len(p.Deploys) == 0 {
		return fmt.Errorf("打法里一个部署都没有")
	}
	seen := map[string]bool{}
	//: 同一格判重用坐标做键——原版就是这么判的（元组相等）。
	occupied := map[[2]int]string{}
	for _, d := range p.Deploys {
		seen[d.Operator] = true
		if who, dup := occupied[d.Position]; dup {
			return fmt.Errorf("两个干员挤在同一格 %v：%s 与 %s",
				d.Position, who, d.Operator)
		}
		occupied[d.Position] = d.Operator
	}
	for _, r := range p.Retreats {
		if _, ok := seen[r.Operator]; !ok {
			return fmt.Errorf("撤退了没部署过的干员：%s", r.Operator)
		}
	}
	for _, s := range p.Skills {
		if _, ok := seen[s.Operator]; !ok {
			return fmt.Errorf("给没部署的干员开技能：%s", s.Operator)
		}
	}
	return nil
}
