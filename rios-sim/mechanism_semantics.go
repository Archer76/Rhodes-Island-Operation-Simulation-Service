package main

// Semantic guards run independently of numeric-key claims. Reading atk or sp
// does not consume a summon lifecycle, a conditional trigger or a form switch.
// These are placeholders only; no approximate combat behaviour is introduced.
import (
	"encoding/json"
	"fmt"
	"regexp"
	"rios-sim/mechanisms"
	"strings"
)

// Only game formatting tags are removed. <替身> is an entity, not markup.
var mechanismFormatTag = regexp.MustCompile(`<[@$][^>]*>|</>`)
var mechanismWhitespace = regexp.MustCompile(`\s+`)
var displacementText = regexp.MustCompile(`推开|击退|拖拽|拉至|拉向|拉到|推动|推力|移动到|返回到初始|返回原(?:来)?位置`)
var formText = regexp.MustCompile(`切换(?:成|为)<替身>|替换<替身>|切换(?:成|为)[^，。\n]*形态|状态(?:和|与)初始状态间切换|融合成|高级形态|第二次及以后使用`)
var blockText = regexp.MustCompile(`阻挡数(?:降至|变为|为|[+＋-－])`)
var hitsText = regexp.MustCompile(`攻击变为(?:二|三|四|五|六|七|八|九|十|[0-9]+)连击`)
var conditionalPanelText = regexp.MustCompile(`未阻挡|阻挡敌人时|未被阻挡|不阻挡|技能(?:开启|期间|触发)|被动技能触发期间|攻击范围内至少|周围.*(?:时|有)|每次.*叠加|生命值.*(?:高于|低于)|生命.*(?:高于|低于)`)
var eventSPText = regexp.MustCompile(`受到攻击时|受(?:到)?伤害时|攻击时|攻击后|每次回复|每次治疗|击杀|死亡|回收|吸收|破裂|每(?:隔)?[0-9一二三四五六七八九十]*秒`)
var entityText = regexp.MustCompile(`召唤物|召唤援军|复制体|流形|蓄水炮|虚影|魂灵之影|全息幻影|小自在|召唤[^，。\n]*(?:作战|部署|阻挡)|可以使用[^，。\n]*再部署`)

func mechanismText(raw string) string {
	return mechanismWhitespace.ReplaceAllString(mechanismFormatTag.ReplaceAllString(raw, ""), "")
}

func semanticMechanismGaps(source, sourceID, sourceName, charID, name, desc string, bb map[string]any, rawBB []json.RawMessage, rawSource json.RawMessage, tokenKey, tokenField string, slot, level int) []mechanisms.Gap {
	var out []mechanisms.Gap
	// RenderDescription uses the legacy broad tag stripper; protect the entity
	// marker before substituting blackboard placeholders.
	protected := strings.ReplaceAll(desc, "<替身>", "MECHANISM_SUBSTITUTE")
	text := mechanismText(strings.ReplaceAll(RenderDescription(protected, bb), "MECHANISM_SUBSTITUTE", "<替身>"))
	add := func(id, key string, value any, reason string) {
		out = append(out, mechanisms.Gap{ID: source + "." + id, Status: "unimplemented", Source: source, SourceID: sourceID, SourceName: sourceName, CharID: charID, Operator: name, Key: key, RawValue: value, Reason: reason, Description: desc, RawBlackboard: cloneRawBlackboard(rawBB), RawSource: append(json.RawMessage(nil), rawSource...), Slot: slot, Level: level})
	}
	if tokenKey != "" {
		add("summon_entity", tokenField, tokenKey, "召唤/装置实体来源已识别，实体部署与生命周期尚未建模")
	} else if entityText.MatchString(text) {
		add("summon_entity", "description", desc, "召唤实体或召唤物作用对象尚无完整战斗消费者")
	}
	if displacementText.MatchString(text) {
		add("displacement", "description", desc, "推拉或自身位移尚未接入战斗位置与路径")
	}
	if formText.MatchString(text) || strings.Contains(text, "<替身>") {
		add("form_switch", "description", desc, "替身、融合或状态/激活次数变体尚未建模")
	}
	if blockText.MatchString(text) {
		add("block_override", "description", desc, "条件或技能阻挡数改写尚未接入战斗")
	}
	if hitsText.MatchString(text) && !bbHas(bb, "times") {
		add("hit_count_override", "description", desc, "描述连击次数尚无技能命中次数消费者")
	}
	if strings.Contains(text, "迷彩") {
		add("camouflage", "description", desc, "迷彩选靶与状态生命周期尚未建模")
	}
	// Key existence is the evidence: zero and negative force are real strengths.
	for _, key := range mechanisms.Keys(bb) {
		plain := strings.TrimPrefix(key, "$")
		tail := plain
		if i := strings.LastIndex(tail, "@"); i >= 0 {
			tail = tail[i+1:]
		}
		if tail == "force" || tail == "base_force_level" || tail == "force_level" {
			add("displacement", key, bb[key], "位移力度来源已识别，推拉尚未接入战斗")
		}
		// Variant namespaces have a bracket in the KEY, not merely the skill ID.
		if strings.Contains(plain, "[") && strings.Contains(plain, "].") {
			add("variant", key, bb[key], "黑板变体分支尚无来源明确的状态消费者")
		}
		if strings.Contains(plain, "token") {
			add("summon_entity", key, bb[key], "召唤实体黑板来源尚无完整生命周期消费者")
		}
	}
	// Baseline talents only consume unconditional own-panel modifiers and deploy SP.
	// Specific shield/regen/aura consumers remain handled by talentMechanismGaps.
	if source == "talent" {
		conditional := conditionalPanelText.MatchString(text)
		if conditional {
			for _, key := range []string{"atk", "def", "max_hp", "attack_speed", "respawn_time"} {
				if bbHas(bb, key) {
					add("conditional_panel", key, bb[key], "条件面板/叠层来源不能由常驻面板消费者认领")
				}
			}
		}
		if strings.Contains(text, "回复") && strings.Contains(text, "技力") && (entityText.MatchString(text) || eventSPText.MatchString(text)) {
			add("event_sp", "description", desc, "条件/周期事件回技力尚无完整事件消费者")
		}
	}
	return out
}

// Character traits were previously absent from the gap producer altogether.
// Resolve the actually unlocked candidate, preserving original (misspelled in
// gamedata) overrideDescripton and raw candidate, rather than scanning locked rows.
func traitMechanismGaps(charID, name string, elite, level, potential int) ([]mechanisms.Gap, error) {
	table, err := loadCharTable()
	if err != nil {
		return nil, err
	}
	var char struct {
		Description string `json:"description"`
		Trait       struct {
			Candidates []json.RawMessage `json:"candidates"`
		} `json:"trait"`
	}
	if err := json.Unmarshal(table[charID], &char); err != nil {
		return nil, err
	}
	converted := make([]json.RawMessage, 0, len(char.Trait.Candidates))
	for _, raw := range char.Trait.Candidates {
		var cand map[string]json.RawMessage
		if err := json.Unmarshal(raw, &cand); err != nil {
			return nil, err
		}
		var desc string
		_ = json.Unmarshal(cand["overrideDescripton"], &desc)
		if desc == "" {
			desc = char.Description
		}
		cand["description"], _ = json.Marshal(desc)
		cand["name"] = json.RawMessage(`"职业特性"`)
		b, err := json.Marshal(cand)
		if err != nil {
			return nil, err
		}
		converted = append(converted, b)
	}
	if len(converted) == 0 {
		return semanticMechanismGaps("trait", "trait:base", "职业特性", charID, name, char.Description, nil, nil, table[charID], "", "tokenKey", 0, 0), nil
	}
	group, err := json.Marshal(struct {
		Candidates []json.RawMessage `json:"candidates"`
	}{converted})
	if err != nil {
		return nil, err
	}
	var gaps []mechanisms.Gap
	for _, t := range resolveTalents([]json.RawMessage{group}, elite, level, potential) {
		raw := char.Trait.Candidates[t.CandidateIndex]
		sourceID := fmt.Sprintf("trait:%d", t.CandidateIndex)
		gaps = mechanisms.Merge(gaps, semanticMechanismGaps("trait", sourceID, "职业特性", charID, name, t.RawDescription, t.Blackboard, t.RawBlackboard, raw, t.TokenKey, "tokenKey", 0, 0))
		// Only exact existing trait consumers may claim a key. Unknown trait keys
		// must not disappear merely because numeric panel parsing recognizes them.
		claimed := map[string]bool{}
		text := mechanismText(RenderDescription(t.RawDescription, t.Blackboard))
		if strings.Contains(text, rangedAttackTrait) && strings.Contains(text, rangedLowerPhrase) && bbValue(t.Blackboard, "atk_scale", 1) > 0 && bbValue(t.Blackboard, "atk_scale", 1) < 1 {
			claimed["atk_scale"] = true
		}
		if bbValue(t.Blackboard, "cost", 0) > 0 && strings.Contains(text, "击杀敌人后获得") {
			claimed["cost"] = true
		}
		if bbValue(t.Blackboard, "sluggish", 0) > 0 {
			claimed["sluggish"] = true
		}
		if strings.Contains(text, hpDrainTrait) && bbValue(t.Blackboard, "hp_ratio", 0) > 0 {
			claimed["hp_ratio"] = true
		}
		if bbHas(t.Blackboard, splashRadiusKey) && bbHas(t.Blackboard, splashScaleKey) {
			claimed[splashRadiusKey] = true
			claimed[splashScaleKey] = true
		}
		for _, key := range mechanisms.Keys(t.Blackboard) {
			if !claimed[key] {
				gaps = append(gaps, mechanisms.Gap{ID: "trait.blackboard." + key, Status: "unidentified", Source: "trait", SourceID: sourceID, SourceName: "职业特性", CharID: charID, Operator: name, Key: key, RawValue: t.Blackboard[key], Description: t.RawDescription, RawBlackboard: cloneRawBlackboard(t.RawBlackboard), RawSource: append(json.RawMessage(nil), raw...), Reason: "当前特性载荷尚无来源明确的已认领战斗机制"})
			}
		}
	}
	return gaps, nil
}
