// simquery.go：`sim` 的**第二种入参形式** —— 查询形式（Go 自造规格）。
//
// ## 它是什么（增量的第一步，**不删旧路径**）
//
// 在此之前 `sim` 只认一种入参：**造好的规格**（`req.Spec` 里有 `stage` 那一整套，
// 由 Python 侧的 `build_spec` 算完之后送来）。这一批让 `sim` **也**接受
// 「关卡 ＋ 计划 ＋ 名册」这种查询，内部调 `buildspec`（`buildspec.go::BuildSpecFull`）
// 把规格造出来再跑。
//
// ★ 旧路径**一个字都没改**：`req.Spec` 里有 `stage` 就照旧直接 Unmarshal 进 `Spec`。
//   对拍台与历史脚本继续走它。这一批**不做删除**。
//
// ## 四条约束（前三条对应 `verifier.py` 里读出来的三个坑）
//
//  1. **判别不许猜**（`ClassifySimSpec`）：有 `plan`／`roster` ⇒ 查询形式；
//     有 `stage` ⇒ 旧形式；**两种都像、或两种都不像 ⇒ 具名失败**，并说清
//     「我看到了哪些键、两种形式各要什么」。静默选一个的症状是
//     「用一份空规格跑出一场零帧的战斗，双方还都以为跑了」。
//
//  2. ★ **响应必须把 `unsupported` 带回来**。Python 侧 `verifier.py:176-186` 用它
//     决定**是否退回原版**（`go_fallbacks`）。当规格是 Go 自己造的时，Python 手上
//     **没有**那份 `unsupported` —— 响应不带它 ⇒ 闸门静默失效：本该退回的关卡直接
//     跑 Go、`go_fallbacks` 变 0，而本仓早有定论「`go_fallbacks==0` 不算放行」。
//     ⇒ 走查询形式时，**成功与失败两条路都把理由带回来**，并且用**指针**装
//     （空的 `[]` 与「没带这个字段」是两件事：前者是「查过了，没有理由」）。
//
//  3. **`allow_devices` / `allow_skills` 必须显式在场**（`ParseSimQuery`）。
//     它们是 PM 裁定④「走乙」的口径（`verifier.py:172-175` 从两个常量读）。
//     缺了就**大声失败**、绝不兜底：写死一组默认值会静默改掉近一半主线关的
//     可跑性（`verifier.py:166` 记着：改成按证据开 ⇒ 196 行 / 45.3% 从可跑变拒跑）。
//
//  4. **规格必须在跑之前取**。权威那边 `build_spec` 读的是 `sim.life`／`sim.cost`
//     这类「此刻」的字段，跑完 `life=0`，再取就会造出一份「一帧不跑就判负」的规格
//     （`verifier.py` 的注释自陈实测撞过）。本实现里顺序是**结构上**保证的：
//     规格由**关卡数据 ＋ 计划**造出（根本不碰模拟器状态），且造完**先**做一次
//     `life > 0` 的断言，**再**进 `runSim`。
package main

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// SimForm 是 `sim` 入参的两种形式。
type SimForm int

const (
	//: 判别失败（两种都像／都不像）——调用方必须原样报错，不许挑一个。
	simFormUnknown SimForm = iota
	//: 旧形式：造好的规格（有 `stage`）。
	simFormBuilt
	//: 增量：查询形式（有 `plan`／`roster`）。
	simFormQuery
)

func (f SimForm) String() string {
	switch f {
	case simFormBuilt:
		return "built"
	case simFormQuery:
		return "query"
	}
	return "unknown"
}

func hasKey(m map[string]json.RawMessage, k string) bool {
	_, ok := m[k]
	return ok
}

// ClassifySimSpec 判别 `sim` 的入参形式。**不许猜**。
//
// 判据是**键的存在性**（不是值、不是「看着像」）：
//
//	有 `stage`                     → 旧形式（造好的规格）
//	有 `plan` 或 `roster`          → 查询形式
//	两者都有 / 两者都没有           → 具名失败
//
// 失败信息里必须同时说清**看到了什么**与**两种形式各要什么**：只说「spec 不合法」
// 会让下一个人去猜是哪一个键写错了。
func ClassifySimSpec(raw json.RawMessage) (SimForm, map[string]json.RawMessage, error) {
	var m map[string]json.RawMessage
	if err := json.Unmarshal(raw, &m); err != nil {
		return simFormUnknown, nil, fmt.Errorf(
			"sim 的 spec 不是对象（%v）。两种形式都要一个 JSON 对象："+
				"旧形式＝造好的规格（含 stage），查询形式＝关卡＋计划＋名册", err)
	}
	keys := make([]string, 0, len(m))
	for k := range m {
		keys = append(keys, k)
	}
	sort.Strings(keys)
	seen := "[" + strings.Join(keys, " ") + "]"

	hasStage := hasKey(m, "stage")
	hasQuery := hasKey(m, "plan") || hasKey(m, "roster")
	switch {
	case hasStage && hasQuery:
		//: ⚠ 这一支是**危险的**：造好的规格里恰好也有 `plan`／`roster` 这类名字时，
		//: 猜错一边的症状是「拿一份只有 plan/roster 的对象当规格跑」。
		return simFormUnknown, m, fmt.Errorf(
			"sim 的 spec **两种形式都像**：既有造好规格的 `stage`，又有查询形式的 "+
				"`plan`/`roster`。看到的键 %s。★ 不许猜——两种形式**各发一套键**："+
				"旧形式只给规格那一套（stage/fps/max_time/…），"+
				"查询形式只给 `plan`/`roster` ＋ `allow_devices` ＋ `allow_skills`"+
				"（关卡走同级的 level 或 path）", seen)
	case hasStage:
		return simFormBuilt, m, nil
	case hasQuery:
		return simFormQuery, m, nil
	default:
		return simFormUnknown, m, fmt.Errorf(
			"sim 的 spec **两种形式都不像**：既没有造好规格的 `stage`，"+
				"也没有查询形式的 `plan`/`roster`。看到的键 %s。★ 两种形式要什么："+
				"旧形式＝一份完整规格（stage 起头）；查询形式＝`plan` 或 `roster` "+
				"＋**必须**带 `allow_devices` 与 `allow_skills`（关卡走同级的 level 或 path）",
			seen)
	}
}

// ParseSimQuery 解查询形式，并**要求** `allow_devices` / `allow_skills` 显式在场。
//
// ⚠ 这两个是**口径**，不是可选项：它们是 PM 裁定④「走乙」的取值，权威那边由
// `verifier.py:172-175` 从两个常量读出来送。缺了就在 Go 里兜一个默认值，
// 等于**替调用方改了半个主线关的可跑性**——而症状只是「某些关突然能跑／不能跑」。
// ⇒ 缺一个就具名失败。
func ParseSimQuery(raw json.RawMessage, m map[string]json.RawMessage) (BuildSpecQuery, error) {
	for _, k := range []string{"allow_devices", "allow_skills"} {
		if !hasKey(m, k) {
			return BuildSpecQuery{}, fmt.Errorf(
				"查询形式的 sim 少了 `%s`：它是**口径**不是可选项（PM 裁定④「走乙」，"+
					"权威那边由 verifier.py 从常量读出后显式送）。"+
					"★ 在 Go 里兜一个默认值会静默改掉近一半主线关的可跑性"+
					"（改成按证据开 ⇒ 196 行，占 45.3 个百分点，从可跑变拒跑）", k)
		}
	}
	//: 键集与类型交给那一份既有的解析器（它也拒绝不认识的键）。
	return ParseSpecRequest(raw)
}

// SelfSpecEcho 是查询形式回给调用方的**规格身份**：规格是从哪两条路径造的、
// 按什么口径造的、键造齐没有、这一关挂了哪些机制。它是给对账用的，不参与判定。
//
// ★ `AllowDevices`／`AllowSkills` **必须回显**：这两个口径参数在 Go 侧目前
// **没有可观测效果**（闸门里 `关卡装置 ×N` 那一行是 unported —— Go 没有装置层），
// 于是「参数被原样带进去了」这件事**只能靠回显取证**。不回显的话，调用方
// 分不出「按 dev 口径算了」与「这个参数被静默丢了」。
type SelfSpecEcho struct {
	Level     string   `json:"level,omitempty"`
	Path      string   `json:"path,omitempty"`
	Plan      string   `json:"plan,omitempty"`
	Roster    string   `json:"roster,omitempty"`
	AllowDevices bool  `json:"allow_devices"`
	AllowSkills  bool  `json:"allow_skills"`
	KeyCount  int      `json:"key_count"`
	Missing   []string `json:"missing_keys"`
	Gated     []string `json:"gated_keys"`
	Mechanisms []string `json:"mechanisms"`
}

// BuildSimSpecFromQuery 是查询形式的完整实现：**先造规格、再跑**。
//
// 返回的三样：能跑的 `*Spec`、回给调用方的规格身份、以及**必须带回去的**
// `unsupported`（见文件头第 2 条）。
func BuildSimSpecFromQuery(level, path string, raw json.RawMessage,
	m map[string]json.RawMessage) (*Spec, SelfSpecEcho, []string, error) {
	q, err := ParseSimQuery(raw, m)
	if err != nil {
		return nil, SelfSpecEcho{}, nil, err
	}
	if level == "" && path == "" {
		return nil, SelfSpecEcho{}, nil, fmt.Errorf(
			"查询形式的 sim 少了关卡：给同级的 `level`（关卡号或 levelId）或 `path`（合成关卡 JSON）")
	}
	out, err := BuildSpecFull(level, path, q)
	if err != nil {
		return nil, SelfSpecEcho{}, nil, err
	}
	echo := SelfSpecEcho{
		Level: level, Path: path, Plan: q.Plan, Roster: q.Roster,
		AllowDevices: q.AllowDevices, AllowSkills: q.AllowSkills,
		KeyCount:   len(specKeysAll) - len(out.MissingKeys),
		Missing:    append([]string{}, out.MissingKeys...),
		Gated:      append([]string{}, out.GatedKeys...),
		Mechanisms: append([]string{}, out.Spec.Mechanisms...),
	}
	if len(out.MissingKeys) > 0 {
		//: 键没造齐就不许跑：少一个键的规格跑出来的是**另一场战斗**。
		return nil, echo, out.Spec.Unsupported, fmt.Errorf(
			"Go 自造的规格缺 %d 个顶层键 %s —— 拒跑（少一个键的规格不是同一场战斗）",
			len(out.MissingKeys), out.MissingKeys)
	}
	//: 把自造的规格**序列化一次再解进 `Spec`**：这一步同时是「生产者造的东西，
	//: 消费者收得下吗」的检查（字段名／类型漂了会当场失败，而不是跑出别的结果）。
	blob, err := json.Marshal(out.Spec)
	if err != nil {
		return nil, echo, out.Spec.Unsupported, fmt.Errorf("自造规格序列化失败：%v", err)
	}
	var spec Spec
	if err := json.Unmarshal(blob, &spec); err != nil {
		return nil, echo, out.Spec.Unsupported, fmt.Errorf(
			"自造规格消费者（wire.Spec）收不下：%v", err)
	}
	//: ★ 约束 4：**跑之前**的那道断言。规格若是在跑过之后取的，`life` 会是 0，
	//: 而那份规格在 `runSim` 里表现为「一帧不跑就判负」——这里当场拦住并说清原因。
	if spec.Life <= 0 {
		return nil, echo, out.Spec.Unsupported, fmt.Errorf(
			"自造规格的 `life`=%d ≤ 0：规格**必须在跑之前取**（权威那边 build_spec 读的是 "+
				"sim.life／sim.cost 这类此刻字段，跑完 life=0）——本实现从关卡数据造，"+
				"走到这里说明取规格的时机错了", spec.Life)
	}
	return &spec, echo, append([]string{}, out.Spec.Unsupported...), nil
}
