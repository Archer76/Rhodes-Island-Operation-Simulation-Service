package main

import (
	"encoding/json"
	"testing"
)

// talentWithDesc 造一条**带正文**的天赋组（`talentJSON` 的 description 是空的，
// 而这一组判据恰恰**只看正文**）。
func talentWithDesc(desc string) json.RawMessage {
	raw, err := json.Marshal(map[string]any{
		"candidates": []any{map[string]any{
			"name":            "某条天赋",
			"unlockCondition": map[string]any{"phase": "PHASE_1", "level": 1},
			"blackboard":      []any{},
			"description":     desc,
		}},
	})
	if err != nil {
		panic(err)
	}
	return raw
}

// TestTextDerivedTalentTargeting 盯住**天赋正文**里那两条选目标优先。
//
// ★ 为什么它们不在特性那条判据里：史都华德／安德切尔的黑板里**一个字都没写**
// 选目标（史都华德只有 `{"atk": 0.03}`），正面判据只在天赋正文里。
// 取数口与 `weakness_damage` 同一个（`talentText`，**所有候选**的正文拼接）。
func TestTextDerivedTalentTargeting(t *testing.T) {
	cases := []struct {
		desc string
		want TextDerived
	}{
		{"攻击力+3%，优先攻击防御力最高的敌人",
			TextDerived{DamageType: "PHYSICAL", PreferHighestDef: true}},
		{"攻击速度+8，优先攻击使用远程武器的敌人",
			TextDerived{DamageType: "PHYSICAL", PreferRanged: true}},
		{"攻击力+4%", TextDerived{DamageType: "PHYSICAL"}},
	}
	for _, c := range cases {
		got := textDerived("", []json.RawMessage{talentWithDesc(c.desc)})
		if got != c.want {
			t.Errorf("天赋正文 %q\n  得 %+v\n  要 %+v", c.desc, got, c.want)
		}
	}
}

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
