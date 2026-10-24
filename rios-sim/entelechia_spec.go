package main

// EntelechiaSourceSpec 声明隐德来希（char_4010_etlchi）的机制来源证据与主战斗循环消费状态。
type EntelechiaSourceSpec struct {
	ConsumerImplemented bool    `json:"consumer_implemented"`
	Elite               int     `json:"elite"`
	Level               int     `json:"level"`
	Potential           int     `json:"potential"`
	ModuleLevel         int     `json:"module_level"`
	Talent1StealHP      float64 `json:"talent_1_steal_hp"`
	Talent1StealHPMax   float64 `json:"talent_1_steal_hp_max"`
	Talent1DOTValue     float64 `json:"talent_1_dot_value"`
	Talent1DOTDuration  float64 `json:"talent_1_dot_duration"`
	Talent2HealRatio    float64 `json:"talent_2_heal_ratio"`
	Talent2DamageResist float64 `json:"talent_2_damage_resist"`
}

func defaultEntelechiaSource() *EntelechiaSourceSpec {
	return &EntelechiaSourceSpec{
		ConsumerImplemented: true,
		Elite:               2,
		Level:               60,
		Potential:           1,
		ModuleLevel:         3,
		Talent1StealHP:      75.0,
		Talent1StealHPMax:   1350.0,
		Talent1DOTValue:     200.0,
		Talent1DOTDuration:  5.0,
		Talent2HealRatio:    0.5,
		Talent2DamageResist: 0.1,
	}
}
