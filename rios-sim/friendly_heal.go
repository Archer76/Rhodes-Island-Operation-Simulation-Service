package main

import (
	"crypto/sha256"
	"encoding/json"
	"fmt"
	"rios-sim/mechanisms"
)

// FriendlyHealRestriction consumes only the explicitly stated prohibition.
// The same exact source's group attack and per-enemy recovery remain gaps.
type FriendlyHealRestriction struct {
	Trait json.RawMessage `json:"trait"`
}

func validFriendlyHealRestriction(charID string, r *FriendlyHealRestriction) bool {
	if charID != "char_4010_etlchi" || r == nil {
		return false
	}
	var value any
	if json.Unmarshal(r.Trait, &value) != nil {
		return false
	}
	b, err := json.Marshal(value)
	return err == nil && fmt.Sprintf("%x", sha256.Sum256(b)) == "6e2537f65cbe7f35d8b9a9232443d96bce34d3df63f02a98a05da6757d976702"
}
func entelechiaFriendlyHealRestriction(st *OperatorStats) (*FriendlyHealRestriction, error) {
	if st.CharID != "char_4010_etlchi" || st.Elite < 0 || st.Level < 1 || st.Potential < 1 {
		return nil, nil
	}
	tbl, err := loadCharTable()
	if err != nil {
		return nil, err
	}
	var char struct {
		Trait struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"trait"`
	}
	if err = json.Unmarshal(tbl[st.CharID], &char); err != nil {
		return nil, err
	}
	if len(char.Trait.Candidates) != 1 {
		return nil, nil
	}
	r := &FriendlyHealRestriction{Trait: append(json.RawMessage(nil), char.Trait.Candidates[0]...)}
	if !validFriendlyHealRestriction(st.CharID, r) {
		return nil, nil
	}
	return r, nil
}
func (o *operator) acceptsFriendlyHealing() bool {
	return !validFriendlyHealRestriction(o.spec.CharID, o.spec.FriendlyHealRestriction)
}

// Use only for explicit healing by a character. Self recovery and environmental
// recovery retain the existing heal entry, not this character-healing channel.
func (o *operator) healFromCharacter(source *operator, amount float64, v *Verdict) float64 {
	if !o.acceptsFriendlyHealing() {
		if amount > 0 && v != nil {
			v.FriendlyHealsRejected++
		}
		if traceOn && source != nil {
			trace("TRAITNOHEAL source=%s target=%s amount=%.4f", source.spec.Name, o.spec.Name, amount)
		}
		return 0
	}
	return o.heal(amount)
}

// Exact source inventory; no recovery amounts or timings are executed here.
// Public branch notes: https://prts.wiki/w/隐德来希#特性 (2026-10-08).
// The 0.05s accumulation window and 0.12s recovery spacing are not raw BB;
// endpoint, multi-hit and immunity semantics remain unproved.
func entelechiaRemainingTraitGaps(charID, name string, raw json.RawMessage, instance int) []mechanisms.Gap {
	if !validFriendlyHealRestriction(charID, &FriendlyHealRestriction{Trait: raw}) {
		return nil
	}
	base := friendlyHealRestrictionGap(OperatorSpec{CharID: charID, Name: name, FriendlyHealRestriction: &FriendlyHealRestriction{Trait: raw}}, instance)
	var gaps []mechanisms.Gap
	for _, r := range []struct{ id, key, reason string }{
		{"trait.reaper.group_attack", "group_attack", "群体攻击完整目标集合尚未闭合；不能由治疗阻挡数上限反推攻击数"},
		{"trait.reaper.recovery_lifecycle", "recovery_lifecycle", "逐伤害触发恢复、0.05秒累加窗口与0.12秒生效间隔尚无精确事件消费者；窗口端点、多段与免疫边界未证；持续伤害不触发"},
	} {
		g := base
		g.ID = r.id
		g.Key = r.key
		g.Status = "unimplemented"
		g.RawValue = nil
		g.Reason = r.reason
		gaps = append(gaps, g)
	}
	return gaps
}

func friendlyHealRestrictionGap(op OperatorSpec, instance int) mechanisms.Gap {
	r := op.FriendlyHealRestriction
	var c struct {
		Description string            `json:"overrideDescripton"`
		Blackboard  []json.RawMessage `json:"blackboard"`
	}
	_ = json.Unmarshal(r.Trait, &c)
	return mechanisms.Gap{Description: c.Description, RawBlackboard: cloneRawBlackboard(c.Blackboard), ID: "trait.blackboard.value", Status: "unidentified", Source: "trait", SourceID: "trait:0", SourceName: "职业特性", CharID: op.CharID, Operator: op.Name, Key: "value", RawValue: 50, RawSource: append(json.RawMessage(nil), r.Trait...), Instance: instance, Reason: "仅禁止友方角色治疗已消费；该精确特性的群体攻击、逐敌回复及阻挡数上限尚未完成"}
}
