package main

// effects.go：`_parse_effects` 的**效果对象内容**（丙阶段四·第八批）。
//
// 对应 `ak_tactic/operator/skill.py:2110-2192`。计数账在第七批（`EffectsAccount`），
// 本文件补上五个箱子的**内容**：buffs / damage / control / variants / other。
//
// ## ★ 为什么必须吃**有序**原料
//
// 尾部两趟是「按**下标取第一个**」：
//
//	own = [v for k, v in scales.items() if k.startswith("attack@")]
//	if own: eff.damage["atk_scale"] = own[0]
//
// `scales` 是按黑板**插入顺序**建的（Python dict 保序），所以 `own[0]` 是
// 「第一个 `attack@*` 倍率」。Go 的 map 迭代是**随机**的——照 map 写，
// 同一条技能每次跑都可能选到不同的倍率，而且**看不出来**（值都是合法值）。
// 所以这里收 `[]json.RawMessage`（JSON 数组的原始顺序），不吃 map。
//
// ## 其余口径
//
//	* `[kill].max_stack_cnt` → `kill_max_stack`，**不 `classified += 1`**；
//	* 起飞/降落演出参数在 `_classify` 之前收走，`classified += 1`；
//	* 变体键落 `variants[variant][name]`，**不并进基础的那一份**；
//	* `buff` 累加（`+=`）、`control` 取最大（`max`）、`damage` 直接覆盖；
//	* `ammo` 在 `durationType != "AMMO"` 时退回 `other` 并 `classified -= 1`。

import (
	"encoding/json"
	"math"
	"strings"
)

// Effects 是五个箱子的内容 ＋ 两个计数。
type Effects struct {
	Total        int                `json:"eff_total"`
	Classified   int                `json:"eff_classified"`
	Buffs        map[string]float64 `json:"eff_buffs"`
	Units        map[string]string  `json:"eff_units"`
	Damage       map[string]float64 `json:"eff_damage"`
	Control      map[string]float64 `json:"eff_control"`
	Variants     map[string]map[string]float64 `json:"eff_variants"`
	VariantUnits map[string]map[string]string  `json:"eff_variant_units"`
	Other        map[string]float64 `json:"eff_other"`
	//: 演出参数（不进结算）。
	AirborneHeight *float64 `json:"eff_airborne_height,omitempty"`
	AirborneRise   *float64 `json:"eff_airborne_rise,omitempty"`
	AirborneFall   *float64 `json:"eff_airborne_fall,omitempty"`
	//: 击杀叠层层数上限（`[kill].max_stack_cnt`）。
	KillMaxStack int `json:"eff_kill_max_stack"`
}

// ParseEffects 复刻 `_parse_effects`。`raw` 是那一级黑板的**原始 JSON 数组**
// （保序），不是 map。
func ParseEffects(raw []json.RawMessage, durationType string) *Effects {
	eff := &Effects{
		Buffs: map[string]float64{}, Units: map[string]string{},
		Damage: map[string]float64{}, Control: map[string]float64{},
		Variants: map[string]map[string]float64{},
		VariantUnits: map[string]map[string]string{},
		Other: map[string]float64{},
	}
	type kv struct {
		Key string
		Val float64
	}
	scales := map[string]float64{}
	scaleOrder := []string{}
	ammos := []kv{}

	for _, bRaw := range raw {
		var b struct {
			Key   string   `json:"key"`
			Value *float64 `json:"value"`
		}
		if err := json.Unmarshal(bRaw, &b); err != nil || b.Key == "" {
			continue
		}
		key := b.Key
		value := 0.0
		if b.Value != nil {
			value = *b.Value
		}
		eff.Total++
		variant, bare := "", key
		if v, rest, ok := SplitVariant(key); ok {
			variant, bare = v, rest
		}
		if variant == "kill" && bare == "max_stack_cnt" {
			eff.KillMaxStack = int(value)
			continue
		}
		if field, ok := FLIGHT_KEYS[rsplitAt(bare)]; ok {
			v := value
			switch field {
			case "airborne_height":
				eff.AirborneHeight = &v
			case "airborne_rise":
				eff.AirborneRise = &v
			case "airborne_fall":
				eff.AirborneFall = &v
			}
			eff.Classified++
			continue
		}
		kind, name, unit, hit := Classify(bare)
		if !hit {
			eff.Other[key] = value
			continue
		}
		eff.Classified++
		if variant != "" {
			if eff.Variants[variant] == nil {
				eff.Variants[variant] = map[string]float64{}
				eff.VariantUnits[variant] = map[string]string{}
			}
			eff.Variants[variant][name] = value
			eff.VariantUnits[variant][name] = kind + "/" + unit
			continue
		}
		switch kind {
		case "buff":
			eff.Buffs[name] += value
			eff.Units[name] = unit
		case "damage":
			if name == "ammo" {
				if durationType != "AMMO" {
					eff.Classified--
					eff.Other[key] = value
					continue
				}
				ammos = append(ammos, kv{key, value})
				continue
			}
			if name == "atk_scale" {
				if _, seen := scales[key]; !seen {
					scaleOrder = append(scaleOrder, key)
				}
				scales[key] = value
			} else {
				eff.Damage[name] = value
			}
		default: // control
			eff.Control[name] = math.Max(eff.Control[name], value)
		}
	}

	//: 尾部两趟：**按插入顺序取第一个**（`skill.py:2177-2191`）。
	var own, bareScales []float64
	for _, k := range scaleOrder {
		if strings.HasPrefix(k, "attack@") {
			own = append(own, scales[k])
		} else {
			bareScales = append(bareScales, scales[k])
		}
	}
	if len(own) > 0 {
		eff.Damage["atk_scale"] = own[0]
	} else if len(bareScales) > 0 {
		eff.Damage["atk_scale"] = bareScales[0]
	}
	if len(own) > 0 && len(bareScales) > 0 {
		eff.Damage["atk_scale_other"] = bareScales[0]
	}
	var ownAmmo []float64
	for _, a := range ammos {
		if strings.HasPrefix(a.Key, "attack@") {
			ownAmmo = append(ownAmmo, a.Val)
		}
	}
	if len(ownAmmo) > 0 {
		eff.Damage["ammo"] = ownAmmo[0]
	} else if len(ammos) > 0 {
		eff.Damage["ammo"] = ammos[0].Val
	}
	return eff
}
