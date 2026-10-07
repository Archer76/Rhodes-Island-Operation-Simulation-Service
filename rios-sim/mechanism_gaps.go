package main

import (
	"encoding/json"
	"fmt"
	"rios-sim/mechanisms"
	"strings"
)

func cloneRawBlackboard(raw []json.RawMessage) []json.RawMessage {
	if raw == nil {
		return nil
	}
	out := make([]json.RawMessage, len(raw))
	for i, b := range raw {
		out[i] = append(json.RawMessage(nil), b...)
	}
	return out
}

// Claims are source-aware: a shared blackboard parser recognizing a key does
// not prove that the selected skill/talent has a battle consumer for it.
func skillMechanismGaps(meta SkillMeta, charID, name string, slot int, baseRange string) []mechanisms.Gap {
	var gaps []mechanisms.Gap
	add := func(id, status, key, reason string) {
		gaps = append(gaps, mechanisms.Gap{ID: id, Status: status, Source: "skill", Operator: name, CharID: charID,
			SourceID: meta.SkillID, SourceName: meta.Name, Key: key, RawValue: meta.Blackboard[key], Reason: reason,
			RawBlackboard: cloneRawBlackboard(meta.RawBlackboard), RawSource: append(json.RawMessage(nil), meta.RawSource...), Description: meta.RawDescription, Slot: slot, Level: meta.Level})
	}
	consumed := map[string]bool{"atk": true, "def": true, "max_hp": true, "attack_speed": true, "base_attack_time": true, "cost": true, "atk_scale": true, "times": true}
	if _, exact := instantSelfHealRatio(meta); exact {
		consumed["heal_scale"] = true
	}
	missing := map[string]string{"heal_scale": "该来源的治疗、吸血或治疗修正尚无完整战斗消费者", "ability_range_forward_extend": "技能射程前移未接入战斗", "attack@range_scale": "技能溅射范围缩放未接入战斗", "prob": "技能概率事件未完整建模", "attack@prob": "技能概率事件未完整建模", "sp": "技能黑板技力效果未接入战斗", "duration": "黑板持续时间未有来源明确的战斗消费者"}
	for _, k := range mechanisms.Keys(meta.Blackboard) {
		if consumed[k] {
			continue
		}
		if reason, ok := missing[k]; ok {
			add("skill."+k, "unimplemented", k, reason)
		} else {
			add("skill.blackboard."+k, "unidentified", k, "当前技能载荷尚无已认领的战斗机制")
		}
	}
	if meta.RangeID != nil && *meta.RangeID != "" && *meta.RangeID != baseRange {
		add("skill.range_override", "unimplemented", "range_id", "技能期间范围改写尚未接入战斗")
		gaps[len(gaps)-1].RawValue = *meta.RangeID
	}
	if strings.Contains(meta.Description, "弱点伤害") {
		add("damage.weakness", "unimplemented", "description", "弱点伤害尚未完整建模")
	}
	return mechanisms.Merge(gaps, semanticMechanismGaps("skill", meta.SkillID, meta.Name, charID, name, meta.RawDescription, meta.Blackboard, meta.RawBlackboard, meta.RawSource, meta.OverrideTokenKey, "overrideTokenKey", slot, meta.Level))
}

func talentMechanismGaps(talents []resolvedTalent, charID, name string) []mechanisms.Gap {
	var gaps []mechanisms.Gap
	seenConsumers := map[string]bool{}
	for _, t := range talents {
		bb := t.Blackboard
		claimed := map[string]bool{}
		claim := func(keys ...string) {
			for _, k := range keys {
				claimed[k] = true
			}
		}
		add := func(id, status, key, reason string) {
			gaps = append(gaps, mechanisms.Gap{ID: id, Status: status, Source: "talent", Operator: name, CharID: charID,
				SourceID: fmt.Sprintf("talent:%d:%d", t.GroupIndex, t.CandidateIndex), SourceName: t.Name,
				Key: key, RawValue: bb[key], Reason: reason, RawBlackboard: cloneRawBlackboard(t.RawBlackboard), RawSource: append(json.RawMessage(nil), t.RawSource...), Description: t.RawDescription})
			claim(key)
		}
		firstClaim := func(consumer string, keys ...string) {
			if seenConsumers[consumer] {
				add("talent.additional_"+consumer, "unimplemented", "description", "同类额外来源未被当前首条消费者处理")
				return
			}
			seenConsumers[consumer] = true
			claim(keys...)
		}
		one := []resolvedTalent{t}
		// These finders correspond to existing, separate consumers, not the shared
		// fifteen-key parser. Only this source's recognized mechanism claims keys.
		max, layers, _, _, _ := shieldEffectOf(t)
		if max > 0 || layers > 0 {
			firstClaim("shield", "interval", "max_times", "times", "hp_ratio", "sp")
		}
		if _, ok := tfFindBlessing(one); ok {
			firstClaim("blessing", "c2e_freeze", "freeze")
		}
		if _, ok := tfFindRegen(one); ok {
			firstClaim("regen", "hp_recovery_per_sec", "buff_duration")
			if strings.Contains(t.Description, "护盾") {
				add("talent.regen_shield", "unimplemented", "description", "回血同时授予护盾的行为尚未建模")
			}
		}
		if _, ok := tfFindMedicMonument(one); ok {
			claim("rhodes_bonus")
			add("talent.medic_monument_shield", "unimplemented", "description", "医者丰碑同时授予护盾的行为尚未建模")
		}
		if _, ok, _ := tfFindTeamAura(one); ok {
			firstClaim("team_aura", "atk", "def", "scale_bonus")
		}
		if _, _, ok := tfFindClassAura(one); ok {
			firstClaim("class_aura", "atk", "def")
		}
		if _, ok := tfFindAmmoCovenant(one); ok {
			firstClaim("ammo_covenant", "atk", "def", "mult")
		}
		if _, ok := tfFindAngelBlessing(one); ok {
			firstClaim("angel_blessing", "atk")
		}
		if _, ok := tfFindLimitDispatch(one); ok {
			firstClaim("limit_dispatch", "atk")
		}
		// A pure cost talent is consumed exactly once by the initial squad balance.
		sig := []string{}
		for key := range bb {
			if !strings.HasPrefix(key, "$") {
				sig = append(sig, key)
			}
		}
		if len(sig) == 1 && sig[0] == "cost" {
			if _, ok := toFloat(bb["cost"]); ok {
				claim("cost")
				for key := range bb {
					if strings.HasPrefix(key, "$") {
						claim(key)
					}
				}
			}
		}
		// Baseline panel/redeploy modifiers have dedicated exact consumers.
		claim("atk", "def", "max_hp", "respawn_time", "attack_speed")
		if bbValue(bb, "attack_speed_add", 0) != 0 {
			add("talent.conditional_attack_speed", "unimplemented", "attack_speed_add", "高台条件攻速尚未接入战斗")
		}
		if _, ok := findSnow(one); ok {
			firstClaim("snow", "interval", "max_cast_cnt", "talent_magic_scale", "move_speed")
		}
		if strings.Contains(t.Description, "翔虫") {
			add("talent.glider", "unimplemented", "description", "翔虫机动尚未接入战斗")
		}
		if _, ok := bb["sp"]; ok && !claimed["sp"] {
			claim("sp")
		}
		if p, ok := toFloat(bb["prob"]); ok {
			if _, block := tfFindDamageBlock(one); block || bbHas(bb, "duration") || bbHas(bb, "atk_scale") {
				if block {
					firstClaim("damage_block", "prob")
				} else if bbHas(bb, "duration") && p != 0 {
					firstClaim("heal_dodge", "prob", "duration")
				} else {
					claim("prob", "duration", "atk_scale")
				}
				if p > 0 && p < 1 {
					add("talent.probability_event", "unimplemented", "prob", "概率事件当前仅有期望值消费者；精确事件机制待实现")
				}
			}
		}
		if p, ok := toFloat(bb["attack@prob"]); ok && !bbHas(bb, "atk_scale") {
			claim("attack@prob")
			if p > 0 && p < 1 {
				add("talent.extra_heal_event", "unimplemented", "attack@prob", "额外治疗当前使用期望治疗量；精确事件机制待实现")
			}
		}
		if _, ok := bb["damage_resistance"]; ok {
			// The key alone says nothing about species: Bena's value belongs to
			// her substitute form. Preserve the source without inventing its scope.
			add("talent.damage_resistance", "unimplemented", "damage_resistance", "来源条件减伤尚无完整战斗消费者")
		}
		if strings.Contains(t.Description, "弱点伤害") {
			add("damage.weakness", "unimplemented", "description", "弱点伤害尚未完整建模")
		}
		if strings.Contains(t.Description, "攻击变为物理伤害") {
			add("talent.damage_type_override", "unimplemented", "description", "天赋伤害类型改写未接入战斗")
		}
		semantic := semanticMechanismGaps("talent", fmt.Sprintf("talent:%d:%d", t.GroupIndex, t.CandidateIndex), t.Name, charID, name, t.RawDescription, bb, t.RawBlackboard, t.RawSource, t.TokenKey, "tokenKey", 0, 0)
		// Consumer recognition is source-local, never the generic panel claim.
		// A shield's break SP and an aura's conditional panel are exact consumers.
		_, teamAura, _ := tfFindTeamAura(one)
		_, _, classAura := tfFindClassAura(one)
		_, ammoAura := tfFindAmmoCovenant(one)
		_, angelAura := tfFindAngelBlessing(one)
		_, dispatchAura := tfFindLimitDispatch(one)
		for _, g := range semantic {
			if g.ID == "talent.conditional_panel" && ((teamAura || classAura || ammoAura) && (g.Key == "atk" || g.Key == "def") || (angelAura || dispatchAura) && g.Key == "atk") {
				continue
			}
			if g.ID == "talent.event_sp" && (max > 0 || layers > 0) {
				continue
			}
			gaps = mechanisms.Merge(gaps, []mechanisms.Gap{g})
		}
		for _, k := range mechanisms.Keys(bb) {
			if !claimed[k] {
				add("talent.blackboard."+k, "unidentified", k, "当前天赋载荷尚无已认领的战斗机制")
			}
		}
	}
	return gaps
}

// Raw/prebuilt specs are guarded too: callers cannot bypass the no-approximation
// policy by omitting the producer's placeholder list.
func specMechanismGaps(spec *Spec) []mechanisms.Gap {
	gaps := mechanisms.Merge(spec.Placeholders)
	for _, reason := range spec.Unsupported {
		gaps = mechanisms.Merge(gaps, []mechanisms.Gap{{ID: "spec.unsupported." + reason, Status: "unimplemented", Source: "spec", Key: "unsupported", RawValue: reason, Reason: reason}})
	}
	for i, op := range spec.Operators {
		gaps = mechanisms.Merge(gaps, op.Placeholders)
		add := func(key string, value float64, reason string) {
			gaps = mechanisms.Merge(gaps, []mechanisms.Gap{{ID: "runtime." + key, Status: "unimplemented", Source: "operator_spec", Operator: op.Name, CharID: op.CharID, Key: key, RawValue: value, Reason: reason, Instance: i}})
		}
		if (op.TalentProcFactor != 0 && op.TalentProcFactor != 1) || len(op.TalentProcProbabilities) > 0 || len(op.TalentProcScales) > 0 {
			exact := len(op.TalentProcProbabilities) > 0 && len(op.TalentProcProbabilities) == len(op.TalentProcScales)
			expected := 1.0
			for j, p := range op.TalentProcProbabilities {
				if p != 0 && p != 1 {
					exact = false
				}
				if j < len(op.TalentProcScales) {
					expected *= 1 + p*(op.TalentProcScales[j]-1)
				}
			}
			if expected != op.TalentProcFactor || (expected == 0 && len(op.TalentProcProbabilities) > 0) {
				exact = false
			}
			if !exact {
				add("talent_proc_factor", op.TalentProcFactor, "仅有概率攻击期望倍率，缺少原始精确事件来源")
			}
		}
		if op.Active != nil {
			for _, f := range []struct {
				key   string
				value float64
			}{{"active.dodge_phys", op.Active.DodgePhys}, {"active.dodge_arts", op.Active.DodgeArts}} {
				if f.value > 0 && f.value < 1 {
					add(f.key, f.value, "技能闪避尚无精确概率事件消费者")
				}
			}
		}
		for _, f := range []struct {
			key   string
			value float64
		}{{"talent_extra_heal_prob", op.TalentExtraHealProb}, {"talent_dodge_on_heal", op.TalentDodgeOnHeal}, {"talent_dodge_phys", op.TalentDodgePhys}, {"talent_dodge_arts", op.TalentDodgeArts}} {
			if f.value > 0 && f.value < 1 {
				add(f.key, f.value, "概率事件尚未精确建模，禁止期望值判决")
			}
		}
	}
	return gaps
}

func operatorMechanismGaps(r DeployRow, st *OperatorStats, talents []resolvedTalent) ([]mechanisms.Gap, error) {
	return operatorMechanismGapsWithInputs(r, st, talents, nil)
}
func operatorMechanismGapsWithInputs(r DeployRow, st *OperatorStats, talents []resolvedTalent, inputs *buildInputs) ([]mechanisms.Gap, error) {
	gaps, err := traitMechanismGaps(r.Entry.CharID, st.Name, r.Entry.Elite, r.Entry.Level, r.Entry.Potential)
	if err != nil {
		return nil, err
	}
	gaps = mechanisms.Merge(gaps, talentMechanismGaps(talents, r.Entry.CharID, st.Name))
	if st.AttackSpeedBonus.WhenFree != 0 {
		gaps = append(gaps, mechanisms.Gap{ID: "module.attack_speed_when_free", Status: "unimplemented", Source: "module", Operator: st.Name, CharID: r.Entry.CharID, SourceID: st.Module, Key: "aspd_when_free", RawValue: st.AttackSpeedBonus.WhenFree, Reason: "未阻挡条件攻速尚未接入战斗"})
	}
	id, slot, err := selectedSkillID(r.Entry.CharID, r.Skill)
	if err != nil {
		return nil, err
	}
	level, err := deployRowSkillLevel(r)
	if err != nil {
		return nil, err
	}
	if id != "" {
		meta, err := inputs.skillMeta(id, level)
		if err != nil {
			return nil, err
		}
		baseRange, err := operatorRangeCode(r.Entry.CharID, r.Entry.Elite)
		if err != nil {
			return nil, err
		}
		// A shared skill level is not its character slot: token overrides live
		// on character_table.skills[]. Never mutate the shared cached metadata.
		selected := *meta
		table, err := loadCharTable()
		if err != nil {
			return nil, err
		}
		var char struct {
			Skills []json.RawMessage `json:"skills"`
		}
		if err := json.Unmarshal(table[r.Entry.CharID], &char); err != nil {
			return nil, err
		}
		if slot > 0 && slot <= len(char.Skills) {
			var source struct {
				OverrideTokenKey string `json:"overrideTokenKey"`
			}
			if err := json.Unmarshal(char.Skills[slot-1], &source); err != nil {
				return nil, err
			}
			selected.OverrideTokenKey = source.OverrideTokenKey
			selected.RawSlot = append(json.RawMessage(nil), char.Skills[slot-1]...)
		}
		skillGaps := skillMechanismGaps(selected, r.Entry.CharID, st.Name, slot, baseRange)
		for i := range skillGaps {
			skillGaps[i].RawSlot = append(json.RawMessage(nil), selected.RawSlot...)
		}
		gaps = mechanisms.Merge(gaps, skillGaps)
	}
	return gaps, nil
}
