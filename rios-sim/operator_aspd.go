package main

// operator_aspd.go：**攻速加成**（天赋常驻 ＋ 模组特性改写）。
//
// 对应 Python `ak_tactic/operator/attack_speed.py`（`talent_attack_speed` :67-92、
// `module_attack_speed` :95-135）。它折进 `verify.py:326` 的那一行：
//
//	attack_speed = float(t.get("attackSpeed", 100)) + aspd.flat
//
// ## 两侧的形状不一样，别混
//
//   * **天赋**：无条件常驻，按精英/等级/潜能选档（每组天赋最多命中一条）。
//   * **模组**：改写的是**特性**，**可能带条件**——赤刃明霄陈的 `uniequip_002_chen3`
//     三级一致地把特性改成「未阻挡敌人时攻击速度 +8」，这一项**不能并进常驻值**，
//     必须交给战斗单位逐帧按「当前有没有挡住敌人」来判。
//     当常驻会白送；当不存在则少算 8 点攻速（实测差 6% 的出手频率）。
//
// ⚠ `attack_speed_add` 是**另一个量**：同一块黑板里它表示「满足某个条件时再给多少」。
// 全库只有阿斯卡纶「噬光残影」一处用它，正文写明条件是「自身周围四格有高台时」。
// **日后若有第二个人用这个键，必须先看他的正文再决定**，不能默认也是高台。

import (
	"encoding/json"
	"fmt"
	"strings"
)

// phaseIndex 是 `PHASE_0/1/2` → 精英阶段（`talent.py:53`）。
var phaseIndex = map[string]int{"PHASE_0": 0, "PHASE_1": 1, "PHASE_2": 2}

// conditionMarkers 是「条件性加成」的判据词（`attack_speed.py:34`）。
// 带这些字的特性**不能算进常驻值**。
var conditionMarkers = []string{"未阻挡", "未被阻挡", "不阻挡"}

func phaseOf(raw any) int {
	s, ok := raw.(string)
	if !ok {
		return 0
	}
	if v, ok := phaseIndex[strings.ToUpper(s)]; ok {
		return v
	}
	return 0
}

// resolvedTalent 是「这个练度下真正生效的一条天赋」。
type resolvedTalent struct {
	Name      string
	Blackboard map[string]any
}

// resolveTalents 复刻 `resolve_talents`（`talent.py:182-204`）。
//
// 每个天赋组**最多一条**：按 `(阶段, 潜能门槛)` 取最大的那条。
func resolveTalents(talents []json.RawMessage, elite, level, potential int) []resolvedTalent {
	have := potential - 1
	if have < 0 {
		have = 0
	}
	type pick struct {
		Phase, NeedPot int
		Talent         resolvedTalent
	}
	best := map[int]pick{}
	for gi, gRaw := range talents {
		var group struct {
			Candidates []struct {
				Name             string            `json:"name"`
				UnlockCondition  struct {
					Phase any `json:"phase"`
					Level *int `json:"level"`
				} `json:"unlockCondition"`
				RequiredPotentialRank *int              `json:"requiredPotentialRank"`
				Blackboard            []json.RawMessage `json:"blackboard"`
			} `json:"candidates"`
		}
		if err := json.Unmarshal(gRaw, &group); err != nil {
			continue
		}
		for _, cand := range group.Candidates {
			phase := phaseOf(cand.UnlockCondition.Phase)
			needLv := 1
			if cand.UnlockCondition.Level != nil {
				needLv = *cand.UnlockCondition.Level
			}
			needPot := 0
			if cand.RequiredPotentialRank != nil {
				needPot = *cand.RequiredPotentialRank
			}
			if phase > elite || needLv > level || needPot > have {
				continue
			}
			key := [2]int{phase, needPot}
			cur, ok := best[gi]
			if ok && (cur.Phase > key[0] || (cur.Phase == key[0] && cur.NeedPot >= key[1])) {
				continue
			}
			best[gi] = pick{Phase: phase, NeedPot: needPot, Talent: resolvedTalent{
				Name:       cand.Name,
				Blackboard: blackboardOf(cand.Blackboard),
			}}
		}
	}
	out := make([]resolvedTalent, 0, len(best))
	for gi := 0; gi < len(talents); gi++ {
		if p, ok := best[gi]; ok {
			out = append(out, p.Talent)
		}
	}
	return out
}

// blackboardOf 把 `[{key, value, valueStr}]` 摊成一张表。
//
// ⚠ 与 `talent.py:133` 同口径：**`valueStr` 非空时存的是 `$键名`**，
// 这里只需要数值键（`attack_speed` / `attack_speed_add`），但仍按同一条走——
// 字符串键不并进数值表，免得下游把字符串当数用。
func blackboardOf(raws []json.RawMessage) map[string]any {
	out := map[string]any{}
	for _, r := range raws {
		var b struct {
			Key      string   `json:"key"`
			Value    *float64 `json:"value"`
			ValueStr *string  `json:"valueStr"`
		}
		if err := json.Unmarshal(r, &b); err != nil || b.Key == "" {
			continue
		}
		if b.ValueStr != nil && strings.TrimSpace(*b.ValueStr) != "" {
			out["$"+b.Key] = strings.TrimSpace(*b.ValueStr)
			continue
		}
		if b.Value != nil {
			out[b.Key] = *b.Value
		}
	}
	return out
}

// AttackSpeedBonus 是一名干员在某档配置下的攻速加成。
type AttackSpeedBonus struct {
	Flat          float64 `json:"aspd_flat"`
	WhenFree      float64 `json:"aspd_when_free"`
	WhenHighGround float64 `json:"aspd_high_ground"`
	Sources       []string `json:"aspd_sources"`
}

// attackSpeedBonus 复刻 `attack_speed_bonus`（`attack_speed.py:138-158`）。
func attackSpeedBonus(talents []json.RawMessage, elite, level, potential int,
	moduleParts []json.RawMessage) AttackSpeedBonus {
	out := AttackSpeedBonus{Sources: []string{}}
	for _, t := range resolveTalents(talents, elite, level, potential) {
		if v, ok := toFloat(t.Blackboard["attack_speed"]); ok && v != 0 {
			out.Flat += v
			out.Sources = append(out.Sources, fmt.Sprintf("天赋「%s」+%g", t.Name, v))
		}
		if add, ok := toFloat(t.Blackboard["attack_speed_add"]); ok && add != 0 {
			out.WhenHighGround += add
			out.Sources = append(out.Sources,
				fmt.Sprintf("天赋「%s」（周围四格有高台时）+%g", t.Name, add))
		}
	}
	flat, free := moduleAttackSpeed(moduleParts, elite, level, potential)
	out.Flat += flat
	out.WhenFree += free
	return out
}

// moduleAttackSpeed 复刻 `module_attack_speed`（`attack_speed.py:95-135`）。
//
// 每个 candidate 自带 `unlockCondition`（阶段/等级）与 `requiredPotentialRank`，
// **未解锁的不计**——模组的特性改写同样不是一装上就有。
func moduleAttackSpeed(parts []json.RawMessage, elite, level, potential int) (float64, float64) {
	flat, free := 0.0, 0.0
	havePot := potential - 1
	if havePot < 0 {
		havePot = 0
	}
	for _, pRaw := range parts {
		var part struct {
			Bundle struct {
				Candidates []struct {
					UnlockCondition struct {
						Phase any `json:"phase"`
						Level *int `json:"level"`
					} `json:"unlockCondition"`
					RequiredPotentialRank *int              `json:"requiredPotentialRank"`
					Blackboard            []json.RawMessage `json:"blackboard"`
					AdditionalDescription *string           `json:"additionalDescription"`
					OverrideDescription   *string           `json:"overrideDescripton"`
					Description           *string           `json:"description"`
				} `json:"candidates"`
			} `json:"overrideTraitDataBundle"`
		}
		if err := json.Unmarshal(pRaw, &part); err != nil {
			continue
		}
		for _, cand := range part.Bundle.Candidates {
			if phaseOf(cand.UnlockCondition.Phase) > elite {
				continue
			}
			if cand.UnlockCondition.Level != nil && *cand.UnlockCondition.Level > level {
				continue
			}
			if cand.RequiredPotentialRank != nil && *cand.RequiredPotentialRank > havePot {
				continue
			}
			value := 0.0
			for _, bRaw := range cand.Blackboard {
				var b struct {
					Key   string   `json:"key"`
					Value *float64 `json:"value"`
				}
				if err := json.Unmarshal(bRaw, &b); err != nil {
					continue
				}
				if b.Key == "attack_speed" && b.Value != nil && *b.Value != 0 {
					value += *b.Value
				}
			}
			if value == 0 {
				continue
			}
			//: 正文在三个字段里都可能（`attack_speed.py:123-128`）。
			text := ""
			for _, s := range []*string{cand.AdditionalDescription,
				cand.OverrideDescription, cand.Description} {
				if s != nil {
					text += *s + " "
				}
			}
			if hasAnyMarker(text) {
				free += value
			} else {
				flat += value
			}
		}
	}
	return flat, free
}

func hasAnyMarker(text string) bool {
	for _, m := range conditionMarkers {
		if strings.Contains(text, m) {
			return true
		}
	}
	return false
}

// moduleParts 复刻 `module_parts`（`stats.py:519-533`）：
// 该模组**这一等级**的 `parts`——特性/天赋改写那一半，**与属性黑板分开**。
func moduleParts(moduleID string, level int) ([]json.RawMessage, error) {
	if moduleID == "" || level == 0 {
		return nil, nil
	}
	if battleEquipCache == nil {
		if _, err := moduleLevels(moduleID); err != nil {
			return nil, err
		}
	}
	raw, ok := battleEquipCache[moduleID]
	if !ok {
		return nil, nil
	}
	var entry struct {
		Phases []struct {
			EquipLevel *int              `json:"equipLevel"`
			Parts      []json.RawMessage `json:"parts"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(raw, &entry); err != nil {
		return nil, err
	}
	for _, ph := range entry.Phases {
		lv := 0
		if ph.EquipLevel != nil {
			lv = *ph.EquipLevel
		}
		if lv == level {
			return ph.Parts, nil
		}
	}
	return nil, nil
}
