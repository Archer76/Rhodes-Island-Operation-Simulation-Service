package main

// stagemul_bb.go：难度修饰层的**黑板乘数**两支
// （`enemy_talent_blackb_mul` / `enemy_skill_blackb_mul`）。
//
// 复刻对象是两侧的合体：
//   · 解析与分发：`ak_tactic/frontend/stage_mul.py::apply_rune_muls`（`:173-202`）；
//   · 天赋支：`ak_tactic/gamedata/enemy.py::rescale_talent_blackboard`（`:691-711`）；
//   · 技能支：`ak_tactic/gamedata/enemy.py::rescale_skill_blackboard`（`:713-752`）。
//
// ## 为什么必须「乘完重跑派生」
//
// 派生字段（`passive_pollut` / `shield_hp_ratio` / `kill_cost` …）是从黑板**算出来**的
// （`enemy_derive.go::DeriveBlackboardFields`）。只改黑板不重跑，乘数就落在**一张没人再读的表**上
// ——读数上看不出任何变化，而 `stage_mul.py` 开头第 2 条纪律写的正是这件事。
//
// ## 两条纪律（`stage_mul.py:23-29`）
//
//  1. **不许改库里的对象**：`EnemyLibrary` 是按敌人全库缓存的，乘数是按关生效的
//     ⇒ 真正要改第一处时才 `Clone()`（没命中就原样返回同一个指针，零拷贝）。
//  2. **有命中就调一次 `DeriveBlackboardFields()`**。
//
// ## 与 Python 的两处**有意的形状差**（都不改可观察行为，登记在此免得下一个人以为是漏搬）
//
//  1. Python 的 `apply_rune_muls` 在**选择器命中时**就 `clone()`（哪怕一个键都没改到）；
//     Go 这里改成**真正要改第一处时才 clone**。对象身份不进规格、**不可观察**；
//     换来的是「`out != es`」这个「有没有真改到」的判据保持干净。
//  2. Python 每个 `rescale_*` 各调一次 derive；Go 只在**全部命中之后**调一次。
//     derive 是**纯函数**、只依赖 `TalentBlackboard` 与 `Skills`
//     （`enemy_derive.go:236-242` 的原文就是这么写的）⇒ 中间那次派生必被最后一次整份覆盖，
//     末态逐字段相同。已核：它**不读** `Atk` / `Defense` / `MaxHP`，
//     所以与 `ApplyAttrMuls` 的先后顺序也不影响结果。

import "sort"

// BBMulHits 是黑板乘数这一支的**行使账**。
//
// ★ 存在的理由（本仓反复吃过的教训）：**键非空 ≠ 行使过**。
// 「乘数一次都没命中」与「乘数根本没接」在读数上长得一模一样，
// 所以这里把四件不同的事分开记：命中了几条键／键不在黑板上／选择器为空／点名的技能不在身上。
type BBMulHits struct {
	//: 真的乘上的天赋黑板键（按名字排序，便于对拍）
	TalentKeys []string
	//: 命中条数（与 `len(TalentKeys)` 同值，单列是因为它对拍时读起来更直接）
	TalentApplied int
	//: 选择器命中了敌人，但这条键**不在**他的天赋黑板上。
	//: 权威 `rescale_talent_blackboard` 的口径：那是「数据与敌人对不上」，**不是错误**，
	//: 但**必须能被计数看见**（该函数 docstring 明写「静默忽略等于把守卫关掉」）。
	TalentMissing []string
	//: 真的改到的技能黑板键
	SkillKeys    []string
	SkillApplied int
	//: `skill` 类但**没有** `skill` 选择器 ⇒ 必然空转
	//: （权威第一句就是 `if not prefab_key: return []`）
	SkillEmptySelector int
	//: 点名的 `prefabKey` 在这个敌人身上一个都没有
	SkillNoMatch int
}

// Hit 报「这一份敌人身上到底有没有东西被改到」——重跑派生的唯一依据。
func (h BBMulHits) Hit() bool { return h.TalentApplied > 0 || h.SkillApplied > 0 }

// bbFloatFaithful 比 `bbToFloat` 再贴一层：Python 的 `float()` 收 `bool`
// （`float(True) == 1.0`），而 `bbToFloat` 不收。黑板上出现布尔值很罕见，
// 但它是一条**真实存在**的语义差，放在这里比留在黑板上当静默零值好。
func bbFloatFaithful(v any) (float64, bool) {
	if b, ok := v.(bool); ok {
		if b {
			return 1, true
		}
		return 0, true
	}
	return bbToFloat(v)
}

// ApplyBBMuls 复刻 `apply_rune_muls` 的 **talent 与 skill 两支**。
//
// 只处理这两类：`attr` 那一支由 `ApplyAttrMuls` 负责（两者都挂在 `statsFor` 这个**取数出口**上，
// 与权威把三条依次作用在 `wrap_enemy_at` 的出口上是同一个口径）。
// 选择器判据与 `ApplyAttrMuls` 逐字同一套：`Enemies` 为空 = 该关全部敌人。
func ApplyBBMuls(es *EnemyStats, muls []RuneMul) (*EnemyStats, BBMulHits) {
	out := es
	hits := BBMulHits{}
	for _, m := range muls {
		if len(m.Enemies) > 0 && !m.Enemies[es.EnemyID] {
			continue
		}
		switch m.Kind {
		case "talent":
			keys := []string{}
			for key, factor := range m.Factors {
				//: ⚠ 读 `out` 不读 `es`：同一个键可能被**两条** mul 先后打到，
				//: 读 `es` 会让第二条把第一条的乘积**整个盖掉**。
				cur, ok := out.TalentBlackboard[key]
				if !ok {
					hits.TalentMissing = append(hits.TalentMissing, key)
					continue
				}
				f, ok := bbFloatFaithful(cur)
				if !ok {
					hits.TalentMissing = append(hits.TalentMissing, key)
					continue
				}
				if out == es {
					out = es.Clone() //: 纪律 1
				}
				out.TalentBlackboard[key] = f * factor
				keys = append(keys, key)
			}
			sort.Strings(keys)
			hits.TalentKeys = append(hits.TalentKeys, keys...)
			hits.TalentApplied += len(keys)
		case "skill":
			if m.Skill == "" {
				//: 权威侧同样直接返回空 ⇒ 这是**空操作**，不是「算不了」。
				//: 但它必须被计数看见，否则「写了却空转」会被读成「已生效」。
				hits.SkillEmptySelector++
				continue
			}
			newSkills, keys, matched := rescaleSkillBlackboard(out.Skills, m.Skill, m.Factors)
			if !matched {
				hits.SkillNoMatch++
			}
			if len(keys) > 0 {
				if out == es {
					out = es.Clone() //: 纪律 1
				}
				out.Skills = newSkills
			}
			sort.Strings(keys)
			hits.SkillKeys = append(hits.SkillKeys, keys...)
			hits.SkillApplied += len(keys)
		}
	}
	if hits.Hit() {
		out.DeriveBlackboardFields() //: 纪律 2
	}
	return out, hits
}

// rescaleSkillBlackboard 复刻 `rescale_skill_blackboard` 的循环体。
//
// ⚠ **必须重建**那一项，不许就地改：`Clone()` 对 `Skills` 只做**切片浅拷**
// （`enemy.go:398`），而切片里的 `map` 与它下面的 `blackboard` 列表都是**库里共享的对象**
// ⇒ 就地改会污染全库缓存。带 `valueStr` 的条目是**字符串参数**（不当数字用），跳过。
//
// 返回 `(重建后的 skills, 真的改到的键, 有没有点中这个 prefabKey)`。
func rescaleSkillBlackboard(skills []any, prefab string,
	factors map[string]float64) ([]any, []string, bool) {
	out := make([]any, 0, len(skills))
	keys := []string{}
	matched := false
	for _, skAny := range skills {
		sk, ok := skAny.(map[string]any)
		if !ok {
			out = append(out, skAny)
			continue
		}
		key, _ := sk["prefabKey"].(string)
		if key != prefab {
			out = append(out, skAny)
			continue
		}
		matched = true
		newBB := []any{}
		for _, bAny := range asAnySlice(sk["blackboard"]) {
			b, ok := bAny.(map[string]any)
			if !ok {
				newBB = append(newBB, bAny)
				continue
			}
			bk, _ := b["key"].(string)
			factor, want := factors[bk]
			if vs, _ := b["valueStr"].(string); !want || vs != "" {
				newBB = append(newBB, bAny)
				continue
			}
			f, ok := bbFloatFaithful(b["value"])
			if !ok {
				newBB = append(newBB, bAny)
				continue
			}
			nb := make(map[string]any, len(b)+1)
			for k2, v2 := range b {
				nb[k2] = v2
			}
			nb["value"] = f * factor
			newBB = append(newBB, nb)
			keys = append(keys, bk)
		}
		nsk := make(map[string]any, len(sk)+1)
		for k2, v2 := range sk {
			nsk[k2] = v2
		}
		nsk["blackboard"] = newBB
		out = append(out, nsk)
	}
	return out, keys, matched
}

// EmptySelectorSkillMuls 挑出「`skill` 类但 `Skill` 选择器为空」的乘数。
//
// 这一类的性质要**分两层说清**，因为很容易被读成两件相反的事：
// 它**不是**「Go 算不了」⇒ **不该拒跑**（权威也只当它是空操作）；
// 它**也什么都没做** ⇒ 必须**具名计数**（`skill_mul_empty_selector`），
// 并在痕迹通道里点名是哪一条，否则「写了但空转」会被当成「已生效」。
func EmptySelectorSkillMuls(muls []RuneMul) []RuneMul {
	out := []RuneMul{}
	for _, m := range muls {
		if m.Kind == "skill" && m.Skill == "" {
			out = append(out, m)
		}
	}
	return out
}
