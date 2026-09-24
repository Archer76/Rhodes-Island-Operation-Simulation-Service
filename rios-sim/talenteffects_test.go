package main

import (
	"encoding/json"
	"fmt"
	"reflect"
	"testing"
)

// talentJSON 造一条**只有一个候选**的天赋组（character_table 的形状）。
//
// bb 用 `"键": 值` 的偶数字段传：写成 map 会让同一个键在多次调用里顺序不定，
// 而本模块的判据是**按键的组合**认的，顺序不该影响结果——用参数列表顺带把这一点也钉住。
func talentJSON(name string, phase, level, needPot int, bb ...any) json.RawMessage {
	pairs := make([]map[string]any, 0, len(bb)/2)
	for i := 0; i+1 < len(bb); i += 2 {
		pairs = append(pairs, map[string]any{
			"key": bb[i].(string), "value": bb[i+1],
		})
	}
	raw, err := json.Marshal(map[string]any{
		"candidates": []any{map[string]any{
			"name": name,
			//: ⚠ `phase` 必须是**字符串** `"PHASE_n"`（`phaseOf` 只认这一种写法）：
			//: 写成整数会被静默读成 0 阶段 ⇒ 这一条天赋**一级都不生效**，
			//: 而症状是「所有用例都得零值」——正是本文件第一次跑出来的样子。
			"unlockCondition":       map[string]any{"phase": fmt.Sprintf("PHASE_%d", phase), "level": level},
			"requiredPotentialRank": needPot,
			"blackboard":            pairs,
			"description":           "",
		}},
	})
	if err != nil {
		panic(err)
	}
	return raw
}

// TestTalentEffectsRealBlackboards 用的是**从 akdb 抄下来的真实黑板**（原文见
// `docs/three-star-modelling.md` §十）。逐位对：这一位该出哪一项、值是多少。
func TestTalentEffectsRealBlackboards(t *testing.T) {
	cases := []struct {
		who    string
		talent json.RawMessage
		elite  int
		level  int
		pot    int
		want   talentEffects
	}{
		{
			who: "炎熔 E1L1 快速技能使用（sp 15）", elite: 1, level: 1, pot: 6,
			talent: talentJSON("快速技能使用", 1, 1, 0, "sp", 15.0),
			want:   talentEffects{ProcFactor: 1.0, DeploySP: 15},
		},
		{
			who: "炎熔 E1L55 快速技能使用（sp 30）", elite: 1, level: 55, pot: 6,
			talent: talentJSON("快速技能使用", 1, 55, 0, "sp", 30.0),
			want:   talentEffects{ProcFactor: 1.0, DeploySP: 30},
		},
		{
			//: 「攻击时，10% 几率当次攻击的攻击力提升至 150%」
			//: ⇒ 期望倍率 1 + 0.1×(1.5−1) = 1.05
			who: "克洛丝 E1L1 要害瞄准·初级", elite: 1, level: 1, pot: 6,
			talent: talentJSON("要害瞄准·初级", 1, 1, 0, "atk_scale", 1.5, "prob", 0.1),
			want:   talentEffects{ProcFactor: 1.05},
		},
		{
			//: E1L55：20% 几率提升至 150% ⇒ 1 + 0.2×0.5 = 1.10
			who: "克洛丝 E1L55 要害瞄准·初级", elite: 1, level: 55, pot: 6,
			talent: talentJSON("要害瞄准·初级", 1, 55, 0, "atk_scale", 1.5, "prob", 0.2),
			want:   talentEffects{ProcFactor: 1.10},
		},
		{
			who: "安赛尔 E1L1 附加治疗（7%）", elite: 1, level: 1, pot: 6,
			talent: talentJSON("附加治疗", 1, 1, 0, "attack@prob", 0.07),
			want:   talentEffects{ProcFactor: 1.0, ExtraHealProb: 0.07},
		},
		{
			who: "安赛尔 E1L55 附加治疗（15%）", elite: 1, level: 55, pot: 6,
			talent: talentJSON("附加治疗", 1, 55, 0, "attack@prob", 0.15),
			want:   talentEffects{ProcFactor: 1.0, ExtraHealProb: 0.15},
		},
		{
			//: ★ 这一条把两个键**拆开**的判据钉住：`prob` ＋ `duration` 是**闪避**，
			//: 不是「额外治疗 10%」——两个键在 `ApplyBlackboard` 里都归进同一个 `Prob`。
			who: "斑点 E1L1 烟雾加装（10%/3秒）", elite: 1, level: 1, pot: 6,
			talent: talentJSON("烟雾加装", 1, 1, 0, "duration", 3.0, "prob", 0.1),
			want:   talentEffects{ProcFactor: 1.0, DodgeOnHeal: 0.1, DodgeSeconds: 3.0},
		},
		{
			who: "斑点 E1L55 烟雾加装（20%/3秒）", elite: 1, level: 55, pot: 6,
			talent: talentJSON("烟雾加装", 1, 55, 0, "duration", 3.0, "prob", 0.2),
			want:   talentEffects{ProcFactor: 1.0, DodgeOnHeal: 0.2, DodgeSeconds: 3.0},
		},
		{
			//: 纯面板天赋（玫兰莎「攻击提升」）：本模块**什么都不该出**，
			//: 而且**一个未识别键都不该有**（`atk` 在键表里，只是归 `talentpanel.go` 管）。
			who: "玫兰莎 E1L1 攻击提升（只折面板）", elite: 1, level: 1, pot: 6,
			talent: talentJSON("攻击提升", 1, 1, 0, "atk", 0.04),
			want:   talentEffects{ProcFactor: 1.0},
		},
	}
	for _, c := range cases {
		got, unknown := talentEffectsFrom([]json.RawMessage{c.talent}, c.elite, c.level, c.pot)
		if !reflect.DeepEqual(got, c.want) {
			t.Errorf("%s：得 %+v，要 %+v", c.who, got, c.want)
		}
		if len(unknown) != 0 {
			t.Errorf("%s：不该有未识别键，得 %v", c.who, unknown)
		}
	}
}

// TestTalentEffectsUnknownKeysNamed 盯住那条**覆盖账**：表外的键必须**具名**回来。
//
// 为什么这一条不能省：本仓在「静默忽略」上栽过不止一次——一个不认识的键被丢掉，
// 症状是「这位干员少了一条机制」而不是任何报错，判决上只表现为「数字小一点」。
func TestTalentEffectsUnknownKeysNamed(t *testing.T) {
	raw := talentJSON("某个将来的天赋", 1, 1, 0,
		"atk", 0.1, "brand_new_key", 1.0, "another_one", 2.0)
	_, unknown := talentEffectsFrom([]json.RawMessage{raw}, 1, 1, 6)
	want := []string{"another_one", "brand_new_key"}
	if !reflect.DeepEqual(unknown, want) {
		t.Fatalf("未识别键得 %v，要 %v（要**排序去重**且点名）", unknown, want)
	}
}

// TestTalentEffectsDollarKeysNotUnknown 钉住一条例外：`$` 开头的键是 valueStr 的落点
// （字符串载荷），由别的层负责，不算「漏掉的数值键」。
func TestTalentEffectsDollarKeysNotUnknown(t *testing.T) {
	raw := talentJSON("带字符串载荷的天赋", 1, 1, 0, "sp", 5.0, "$projectile", 0.0)
	got, unknown := talentEffectsFrom([]json.RawMessage{raw}, 1, 1, 6)
	if len(unknown) != 0 {
		t.Fatalf("`$` 开头的键不该进未识别清单，得 %v", unknown)
	}
	if got.DeploySP != 5.0 {
		t.Fatalf("sp 应取到 5，得 %v", got.DeploySP)
	}
}

// TestTalentEffectsDefaultIsOneNotZero 是**反向**那一条：`ProcFactor` 的
// 「没有这条」必须是 **1.0**。给 0 会让每一位没带这条天赋的干员伤害归零——
// 而「伤害归零」与「这一支没接」在判决上长得完全不一样，前者是把好的弄坏了。
func TestTalentEffectsDefaultIsOneNotZero(t *testing.T) {
	got, _ := talentEffectsFrom(nil, 1, 1, 6)
	if got.ProcFactor != 1.0 {
		t.Fatalf("没有天赋时 ProcFactor 必须是 1.0，得 %v", got.ProcFactor)
	}
	if got.DeploySP != 0 || got.ExtraHealProb != 0 || got.DodgeOnHeal != 0 {
		t.Fatalf("其余三项「没有这条」是 0，得 %+v", got)
	}
}

// TestClamp01 是守卫本身的正负对照：夹住了说明数据与假设不符，但不许造出
// 大于 1 的倍率或负概率。
func TestClamp01(t *testing.T) {
	for _, c := range []struct{ in, want float64 }{
		{0.1, 0.1}, {-0.5, 0.0}, {1.5, 1.0}, {1.0, 1.0}, {0.0, 0.0},
	} {
		if got := clamp01(c.in); got != c.want {
			t.Errorf("clamp01(%v) 得 %v，要 %v", c.in, got, c.want)
		}
	}
}

// TestTalentEffectsUsed 盯住痕迹/覆盖账用的那份「哪几项真的非零」。
func TestTalentEffectsUsed(t *testing.T) {
	empty := talentEffectsUsed(defaultTalentEffects())
	if len(empty) != 0 {
		t.Fatalf("全默认时应空，得 %v", empty)
	}
	got := talentEffectsUsed(talentEffects{
		ProcFactor: 1.05, DeploySP: 15, ExtraHealProb: 0.07,
		DodgeOnHeal: 0.1, DodgeSeconds: 3.0,
	})
	if len(got) != 5 {
		t.Fatalf("五项都非零时应报五项，得 %v", got)
	}
}
