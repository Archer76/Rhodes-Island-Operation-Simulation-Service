package main

import (
	"encoding/json"
	"fmt"
	"math"
)

// Exact source-to-runtime parameters. This does not claim a battle consumer.
type wangRuntimeConfig struct {
	Slot                                                            int
	InitialInventory, InventoryMaximum, DeployMaximum, ExtraMaximum int
	DeployCost, DeployCooldown                                      float64
	PerDamage, PerResistPenetration                                 float64
	DamageScale, EffectDuration, SlowFactor                         float64
	SPCost, InitialSP, SPIncrement                                  float64
	Replenish, Ammo                                                 int
}

func wangStrictBB(raw json.RawMessage) (map[string]float64, error) {
	var x struct {
		Blackboard []struct {
			Key      string  `json:"key"`
			Value    float64 `json:"value"`
			ValueStr *string `json:"valueStr"`
		} `json:"blackboard"`
	}
	if err := json.Unmarshal(raw, &x); err != nil {
		return nil, err
	}
	out := map[string]float64{}
	for _, r := range x.Blackboard {
		if r.Key == "" || r.ValueStr != nil || math.IsNaN(r.Value) || math.IsInf(r.Value, 0) {
			return nil, fmt.Errorf("invalid wang blackboard")
		}
		if _, ok := out[r.Key]; ok {
			return nil, fmt.Errorf("duplicate wang key %s", r.Key)
		}
		out[r.Key] = r.Value
	}
	return out, nil
}
func wangRequired(bb map[string]float64, key string) (float64, error) {
	v, ok := bb[key]
	if !ok {
		return 0, fmt.Errorf("missing wang parameter %s", key)
	}
	return v, nil
}
func decodeWangRuntimeConfig(s *WangSourceSpec) (wangRuntimeConfig, error) {
	var out wangRuntimeConfig
	if s == nil || s.Elite < 0 || s.Elite > 2 || s.Potential < 1 || s.Potential > 6 || s.Slot < 1 || s.Slot > 3 {
		return out, fmt.Errorf("invalid wang selected source")
	}
	out.Slot = s.Slot
	var token struct {
		Phases []struct {
			Frames []struct {
				Data map[string]json.RawMessage `json:"data"`
			} `json:"attributesKeyFrames"`
		} `json:"phases"`
	}
	if err := json.Unmarshal(s.Evidence[wangTokenID], &token); err != nil {
		return out, err
	}
	if s.Elite >= len(token.Phases) || len(token.Phases[s.Elite].Frames) == 0 {
		return out, fmt.Errorf("missing wang token phase")
	}
	rawAttrs := token.Phases[s.Elite].Frames[0].Data
	attrs := map[string]float64{}
	for _, k := range []string{"cost", "respawnTime", "maxDeployCount", "maxDeckStackCnt"} {
		raw, ok := rawAttrs[k]
		if !ok || string(raw) == "null" {
			return out, fmt.Errorf("missing token attribute %s", k)
		}
		var value float64
		if err := json.Unmarshal(raw, &value); err != nil {
			return out, fmt.Errorf("invalid token attribute %s: %w", k, err)
		}
		attrs[k] = value
	}
	out.DeployCost = attrs["cost"]
	out.DeployCooldown = attrs["respawnTime"]
	out.DeployMaximum = int(attrs["maxDeployCount"])
	out.InventoryMaximum = int(attrs["maxDeckStackCnt"])
	if s.Potential >= 3 {
		out.DeployMaximum++
		out.InventoryMaximum++
	}
	for _, t := range s.Talents {
		bb, err := wangStrictBB(t.Raw)
		if err != nil {
			return out, err
		}
		if t.Group == 0 {
			cnt, err := wangRequired(bb, "cnt")
			if err != nil {
				return out, err
			}
			extra, err := wangRequired(bb, "attack@max_spawn_cnt")
			if err != nil {
				return out, err
			}
			out.InitialInventory = int(cnt)
			out.ExtraMaximum = int(extra)
		}
		if t.Group == 1 {
			out.PerDamage, err = wangRequired(bb, "attack@per_atk_scale")
			if err != nil {
				return out, err
			}
			out.PerResistPenetration, err = wangRequired(bb, "attack@per_magic_resist_penetrate_fixed")
			if err != nil {
				return out, err
			}
			max, e := wangRequired(bb, "attack@max_trigger_cnt")
			if e != nil {
				return out, e
			}
			if max != 3 {
				return out, fmt.Errorf("unsupported wang talent stack cap %g", max)
			}
		}
	}
	if s.Module != nil {
		var phase struct {
			Tokens map[string][]struct {
				Key   string  `json:"key"`
				Value float64 `json:"value"`
			} `json:"tokenAttributeBlackboard"`
		}
		if err := json.Unmarshal(s.Module.Raw, &phase); err != nil {
			return out, err
		}
		for _, r := range phase.Tokens[wangTokenID] {
			switch r.Key {
			case "cost":
				out.DeployCost += r.Value
			case "max_deploy_count":
				out.DeployMaximum += int(r.Value)
			default:
				return out, fmt.Errorf("unconsumed wang module token %s", r.Key)
			}
		}
		for _, raw := range s.ModuleCandidates {
			bb, err := wangStrictBB(raw)
			if err != nil {
				return out, err
			}
			if v, ok := bb["attack@per_atk_scale"]; ok {
				out.PerDamage = v
			}
			if v, ok := bb["attack@per_magic_resist_penetrate_fixed"]; ok {
				out.PerResistPenetration = v
			}
		}
	}
	bb, err := wangStrictBB(s.TokenSkill.Raw)
	if err != nil {
		return out, err
	}
	out.DamageScale, err = wangRequired(bb, "atk_scale")
	if err != nil {
		return out, err
	}
	switch s.Slot {
	case 1:
		out.EffectDuration, err = wangRequired(bb, "sluggish")
	case 2:
		out.EffectDuration, err = wangRequired(bb, "duration")
		v, e := wangRequired(bb, "move_speed")
		if e != nil {
			return out, e
		}
		out.SlowFactor = 1 + v
	}
	if err != nil {
		return out, err
	}
	owner, err := wangStrictBB(s.OperatorSkill.Raw)
	if err != nil {
		return out, err
	}
	n, err := wangRequired(owner, "cnt")
	if err != nil {
		return out, err
	}
	out.Replenish = int(n)
	if s.Slot == 3 {
		ammo, e := wangRequired(owner, "trigger_time")
		if e != nil {
			return out, e
		}
		out.Ammo = int(ammo)
	}
	var skill struct {
		SP struct {
			Cost      float64 `json:"spCost"`
			Init      float64 `json:"initSp"`
			Increment float64 `json:"increment"`
		} `json:"spData"`
	}
	if err = json.Unmarshal(s.OperatorSkill.Raw, &skill); err != nil {
		return out, err
	}
	out.SPCost = skill.SP.Cost
	out.InitialSP = skill.SP.Init
	out.SPIncrement = skill.SP.Increment
	if out.InitialInventory <= 0 || out.InventoryMaximum < out.InitialInventory || out.DeployCost < 0 || out.DeployCooldown < 0 || out.DamageScale <= 0 || out.SPCost <= 0 {
		return out, fmt.Errorf("invalid wang runtime parameters")
	}
	return out, nil
}
