package main

import "testing"

// TestTextDerivedTraitTags 盯住一条**实测踩到的坑**：特性正文里的排版标签
// 会**插在词中间**，不剥掉的话整串短语一个字都不差地扫也扫不到。
//
// 原始出处（`akdb`，逐字）：泡普卡的 `trait_text` 是
//
//	同时攻击阻挡的<@ba.kw>所有敌人</>
//
// ⇒ 「同时攻击阻挡的所有敌人」扫不到 ⇒ 那条特性**整条静默不生效**，
// 症状是「她一次只打一个」（与「这条特性没接」一模一样），没有任何报错。
func TestTextDerivedTraitTags(t *testing.T) {
	cases := []struct {
		raw  string
		want TextDerived
	}{
		{"同时攻击阻挡的<@ba.kw>所有敌人</>", TextDerived{DamageType: "PHYSICAL", AttacksAllBlocked: true}},
		{"优先攻击空中单位", TextDerived{DamageType: "PHYSICAL", AirPriority: true}},
		{"恢复友方单位生命", TextDerived{DamageType: "PHYSICAL", Heals: true}},
		{"法术伤害<@ba.kw>且</>停顿", TextDerived{DamageType: "MAGIC"}},
		{"技能可以治疗友方单位", TextDerived{DamageType: "PHYSICAL", HealsOnSkill: true}},
		{"", TextDerived{DamageType: "PHYSICAL"}},
	}
	for _, c := range cases {
		got := textDerived(c.raw, nil)
		if got != c.want {
			t.Errorf("textDerived(%q)\n  得 %+v\n  要 %+v", c.raw, got, c.want)
		}
	}
}

// TestTextDerivedTagStrippingIsWideningOnly 是**反向**那一条：剥标签只会让命中变多，
// 不会把原来命中的变成不命中。若哪天有人在 `stripTraitTags` 里写了个会吃掉正文的
// 正则，这条会红——而那种症状（一批干员同时丢掉特性）极难在判决上定位。
func TestTextDerivedTagStrippingIsWideningOnly(t *testing.T) {
	for _, raw := range []string{
		"恢复友方单位生命", "法术伤害", "优先攻击空中单位", "技能可以治疗友方单位",
	} {
		bare := textDerived(stripTraitTags(raw), nil)
		tagged := textDerived("<@ba.kw>"+raw+"</>", nil)
		if bare != tagged {
			t.Errorf("给 %q 加一层标签后结果变了：裸 %+v ／ 带标签 %+v", raw, bare, tagged)
		}
	}
}

// TestStripTraitTagsKeepsText 是那条正则的**正负对照**：
// 只吃标签本身，不吃正文里的中文与数字。
func TestStripTraitTagsKeepsText(t *testing.T) {
	for _, c := range []struct{ in, want string }{
		{"同时攻击阻挡的<@ba.kw>所有敌人</>", "同时攻击阻挡的所有敌人"},
		{"攻击力<@ba.vup>+50%</>", "攻击力+50%"},
		{"没有标签", "没有标签"},
		{"", ""},
	} {
		if got := stripTraitTags(c.in); got != c.want {
			t.Errorf("stripTraitTags(%q) 得 %q，要 %q", c.in, got, c.want)
		}
	}
}
