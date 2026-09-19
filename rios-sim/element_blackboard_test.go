package main

import (
	"strings"
	"testing"
)

// 守卫：B 组「黑板原样映射」的**消费端**取值层。
//
// 这一层的风险与别处不同：它错的时候**不报错**——键名对不上就静默取 0，
// 机制被关掉而对拍仍然全绿（记忆 9b14e2c4 那类）。所以守卫要盯的不是"算得对不对"，
// 而是"**该吵的时候有没有吵**"。

func TestKeyHasEpSuffixIsSuffixNotSubstring(t *testing.T) {
	ok := []string{
		"attack@ep_damage_ratio",
		"EpDamage.attack@ep_damage_ratio",
		"1.ep_damage_value",
		"aura.ep_damage_scale",
		"ep_damage_ratio",
	}
	for _, k := range ok {
		if _, hit := keyHasEpSuffix(k); !hit {
			t.Errorf("应识别为元素损伤键：%s", k)
		}
	}
	bad := []string{
		"xep_damage_ratio2",       // 子串不是后缀
		"ep_damage_ratio_extra",   // 后面还有东西
		"my_ep_damage_values",     // 复数/延长
		"attack@ep_damage",        // 少了 ratio/value/scale
		"ep_damage_ratio_normal2", // 变体名不算本层三类
	}
	for _, k := range bad {
		if suf, hit := keyHasEpSuffix(k); hit {
			t.Errorf("不该识别为元素损伤键：%s（被判成 %s）", k, suf)
		}
	}
}

func TestEpCandidatesIsSortedAndComplete(t *testing.T) {
	bb := map[string]float64{
		"Attack2.attack@ep_damage_ratio": 0.6,
		"Attack.attack@ep_damage_ratio":  0.6,
		"EpDamage.ep_damage_value":       30,
		"atk":                            1.1,
	}
	got := EpCandidates(bb)
	want := []string{
		"Attack.attack@ep_damage_ratio",
		"Attack2.attack@ep_damage_ratio",
		"EpDamage.ep_damage_value",
	}
	if len(got) != len(want) {
		t.Fatalf("候选数应为 %d，得到 %d：%v", len(want), len(got), got)
	}
	for i := range want {
		if got[i] != want[i] {
			t.Fatalf("候选应按键名排序：第 %d 个应为 %s，得到 %s", i, want[i], got[i])
		}
	}
}

// 没有候选**不是错**：这一处本来就没有元素损伤。
func TestResolveEpAmountNoCandidateIsNotAnError(t *testing.T) {
	amt, keys, err := ResolveEpAmount(map[string]float64{"atk": 1.1, "stun": 3}, 1000)
	if err != nil {
		t.Fatalf("没有候选时不该报错，得到：%v", err)
	}
	if amt != 0 || keys != nil {
		t.Fatalf("没有候选时应为 (0, nil)，得到 (%v, %v)", amt, keys)
	}
}

// 同机制的两条路（值相同）⇒ 可用，取值一次。
func TestResolveEpAmountAcceptsTwinsWithSameValue(t *testing.T) {
	bb := map[string]float64{
		"Attack.attack@ep_damage_ratio":  0.6,
		"Attack2.attack@ep_damage_ratio": 0.6,
	}
	amt, keys, err := ResolveEpAmount(bb, 500)
	if err != nil {
		t.Fatalf("同值孪生键不该报错：%v", err)
	}
	if amt != 300 {
		t.Fatalf("比例式应为 base×ratio＝500×0.6＝300，得到 %v", amt)
	}
	if len(keys) != 2 {
		t.Fatalf("应报出两条来源键，得到 %v", keys)
	}
}

// 同类键取值不同 ⇒ **必须吵**：那是不止一处施加点，不是同机制的两条路。
func TestResolveEpAmountRejectsDivergentValues(t *testing.T) {
	bb := map[string]float64{
		"aura.ep_damage_ratio":   0.4,
		"aura2.ep_damage_ratio":  0.9,
		"killed.ep_damage_ratio": 0.4,
	}
	amt, keys, err := ResolveEpAmount(bb, 100)
	if err == nil {
		t.Fatalf("同类键取值不一致时必须报错，却返回 (%v, %v)", amt, keys)
	}
	if !strings.Contains(err.Error(), "不一致") {
		t.Errorf("报错要说清是取值不一致，得到：%v", err)
	}
	// 报错里必须带上**两个具体键与值**，否则接手者无法定位
	for _, want := range []string{"aura.ep_damage_ratio", "aura2.ep_damage_ratio"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("报错应点名 %s：%v", want, err)
		}
	}
}

// 混类 ⇒ **必须吵**：送进来的不是"一处损伤"。
func TestResolveEpAmountRejectsMixedClasses(t *testing.T) {
	bb := map[string]float64{
		"EpDamage.ep_damage_ratio": 0.1,
		"Scream.ep_damage_value":   30, // 绝对值与比例混在一起
	}
	if _, _, err := ResolveEpAmount(bb, 1000); err == nil {
		t.Fatal("混类时必须报错")
	}
}

// 绝对值**不乘**乘数基——这是与比例式唯一的分道处，错了会差好几个数量级。
func TestResolveEpAmountValueIsAbsolute(t *testing.T) {
	bb := map[string]float64{"ScreamDebuff.ep_damage_value": 30}
	amt, _, err := ResolveEpAmount(bb, 1000)
	if err != nil {
		t.Fatalf("单键绝对值不该报错：%v", err)
	}
	if amt != 30 {
		t.Fatalf("绝对值应为 30（不乘 base），得到 %v", amt)
	}
}

// **拼写错误原样保留**：`GetEnmey.` 是数据里的真实拼写。
// 谁若"顺手改正"成 GetEnemy.，这条守卫会红——不红就说明守卫失效了。
func TestResolveEpAmountKeepsMisspelledPrefix(t *testing.T) {
	bb := map[string]float64{"GetEnmey.attack@ep_damage_ratio": 1.5}
	amt, keys, err := ResolveEpAmount(bb, 100)
	if err != nil {
		t.Fatalf("单键不该报错：%v", err)
	}
	if amt != 150 {
		t.Fatalf("1.5 是比例式（实测有 >1 的值，不许假定 ≤1），100×1.5=150，得到 %v", amt)
	}
	if len(keys) != 1 || keys[0] != "GetEnmey.attack@ep_damage_ratio" {
		t.Fatalf("键名必须原样保留（含拼写错误），得到 %v", keys)
	}
}
