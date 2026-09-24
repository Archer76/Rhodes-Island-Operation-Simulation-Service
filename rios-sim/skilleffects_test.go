package main

import (
	"reflect"
	"testing"
)

// TestApplyBlackboard_三星技能与天赋 用**真实数据里的黑板**锁住这张表的口径。
//
// 每组＝一位三星干员的一条键组合，值取 `akdb` 里那一条（现算，见
// `docs/three-star-modelling.md`）。这样表改坏了会当场响，而不是等到某关判决变了才被发现
// ——本仓的规矩：能变检查的变检查。
func TestApplyBlackboard_三星技能与天赋(t *testing.T) {
	cases := []struct {
		who   string
		bb    map[string]any
		check func(skillMods) bool
		why   string
	}{
		{"玫兰莎 技1（skcom_atk_up）", map[string]any{"atk": 0.5},
			func(m skillMods) bool { return m.ATKPct == 0.5 }, "攻击力 +50%"},
		{"米格鲁 技1（skcom_def_up）", map[string]any{"def": 0.5},
			func(m skillMods) bool { return m.DEFPct == 0.5 }, "防御力 +50%"},
		{"卡缇 技1（skcom_heal_self）", map[string]any{"heal_scale": 0.4},
			func(m skillMods) bool { return m.HealScale == 0.4 }, "自疗 40% 上限"},
		{"炎熔 技1（skcom_magic_rage）", map[string]any{"attack_speed": 50.0},
			func(m skillMods) bool { return m.AttackSpeed == 50 }, "攻速 +50"},
		{"芬 技1（skcom_charge_cost）", map[string]any{"cost": 6.0},
			func(m skillMods) bool { return m.CostGain == 6 }, "立即 +6 费"},
		{"克洛丝 技1（skchr_kroos_1）", map[string]any{"atk_scale": 1.4, "times": 2.0},
			func(m skillMods) bool { return m.AtkScale == 1.4 && m.Times == 2 },
			"连射 2 次、每次 140%"},
		{"安赛尔 技1（skcom_range_extend）",
			map[string]any{"ability_range_forward_extend": 2.0, "atk": 0.4},
			func(m skillMods) bool {
				return m.RangeForwardExtend == 2 && m.ATKPct == 0.4
			}, "射程前移 2 格 ＋ 攻击 +40%"},
		{"空爆 技1（skchr_catap_1）", map[string]any{"attack@range_scale": 2.0},
			func(m skillMods) bool { return m.SplashRangeScale == 2.0 }, "爆炸范围 ×2"},
		{"斑点 技1（skchr_spot_1）", map[string]any{"atk": 0.45, "base_attack_time": 1.3},
			func(m skillMods) bool { return m.ATKPct == 0.45 && m.BaseAttackTime == 1.3 },
			"攻击 +45% ＋ 间隔改 1.3 秒"},
		{"玫兰莎 天赋（攻击提升）", map[string]any{"atk": 0.04},
			func(m skillMods) bool { return m.ATKPct == 0.04 }, "攻击力 +4%"},
		{"克洛丝 天赋（要害瞄准·初级）", map[string]any{"atk_scale": 1.5, "prob": 0.1},
			func(m skillMods) bool { return m.Prob == 0.1 && m.ProcScale == 1.5 },
			"10% 概率把这一击改成 150%"},
		{"炎熔 天赋（快速技能使用）", map[string]any{"sp": 15.0},
			func(m skillMods) bool { return m.SP == 15 }, "部署后 +15 技力"},
		{"芬 天赋（轻量化）", map[string]any{"cost": -1.0},
			func(m skillMods) bool { return m.CostGain == -1 }, "部署费用 -1"},
	}
	for _, c := range cases {
		m, unknown := ApplyBlackboard(c.bb)
		if len(unknown) != 0 {
			t.Errorf("%s：出现了未识别键 %v（首发表应覆盖它）", c.who, unknown)
			continue
		}
		if !c.check(m) {
			t.Errorf("%s：%s —— 解析结果 %+v 不满足预期", c.who, c.why, m)
		}
	}
}

// TestApplyBlackboard_缺省不是零 是这条模块最容易出人命的地方。
//
// `atk_scale` 与 `times` **缺席**时的语义分别是「倍率 1」「连击 1」，
// 写成 0 就是「打不死人」与「不出手」——而且两种都**不报错**。
func TestApplyBlackboard_缺省不是零(t *testing.T) {
	m, unknown := ApplyBlackboard(map[string]any{})
	if len(unknown) != 0 {
		t.Fatalf("空黑板不该有未识别键：%v", unknown)
	}
	if m.AtkScale != 1.0 {
		t.Errorf("空黑板的 atk_scale 应为 1.0（缺省＝不影响），实得 %v", m.AtkScale)
	}
	if m.Times != 1 {
		t.Errorf("空黑板的 times 应为 1（缺省＝打一下），实得 %v", m.Times)
	}
	//: 反向：**写了 0** 就是 0，不许被缺省值盖掉（"没有这条键" 与 "这条键是 0" 是两回事）。
	m2, _ := ApplyBlackboard(map[string]any{"atk_scale": 0.0})
	if m2.AtkScale != 0.0 {
		t.Errorf("显式写 0 必须保留为 0，实得 %v", m2.AtkScale)
	}
}

// TestApplyBlackboard_未识别键必须具名 是覆盖账那一半的判据。
func TestApplyBlackboard_未识别键必须具名(t *testing.T) {
	bb := map[string]any{
		"atk":       0.5,
		"cnt":       3.0, // 全库高频、首发表**没有** ⇒ 必须出现在未识别清单里
		"hp_ratio":  0.1,
		"$some_key": "payload", // valueStr 载荷：**不算漏**
	}
	_, unknown := ApplyBlackboard(bb)
	want := []string{"cnt", "hp_ratio"}
	if !reflect.DeepEqual(unknown, want) {
		t.Errorf("未识别键应为 %v（已排序、不含 $ 载荷），实得 %v", want, unknown)
	}
}

// TestSkillKeyTable_每条都有说明：表是给人读的，空说明等于没写。
func TestSkillKeyTable_每条都有说明(t *testing.T) {
	tab := SkillKeyTable()
	if len(tab) == 0 {
		t.Fatal("首发表不该为空")
	}
	for k, why := range tab {
		if why == "" {
			t.Errorf("键 %q 没有说明；这张表同时也是覆盖账的依据，空说明读不出它管什么", k)
		}
	}
	//: 外部拿到的是**副本**：改它不许影响解析用的那张表（否则一次误改会让判定悄悄变）。
	tab["atk"] = "被改坏了"
	if skillKeyTable["atk"] == "被改坏了" {
		t.Error("SkillKeyTable() 返回的必须是副本")
	}
}

// TestModsUsed_报告真的动了哪几个分量。
func TestModsUsed_报告真的动了哪几个分量(t *testing.T) {
	m, _ := ApplyBlackboard(map[string]any{"atk": 0.5, "times": 2.0})
	got := modsUsed(m)
	want := []string{"atk", "times"}
	if !reflect.DeepEqual(got, want) {
		t.Errorf("modsUsed 应为 %v，实得 %v", want, got)
	}
}
