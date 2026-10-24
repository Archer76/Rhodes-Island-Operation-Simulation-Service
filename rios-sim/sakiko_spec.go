package main

// SakikoSourceSpec 声明丰川祥子（char_4182_oblvns）的机制来源证据与主战斗循环消费状态。
type SakikoSourceSpec struct {
	ConsumerImplemented       bool    `json:"consumer_implemented"`
	Elite                     int     `json:"elite"`
	Level                     int     `json:"level"`
	Potential                 int     `json:"potential"`
	ModuleLevel               int     `json:"module_level"`
	MaxNoteCount              int     `json:"max_note_count"`
	DefPenetrateRatio         float64 `json:"def_penetrate_ratio"`
	MagicResistPenetrateRatio float64 `json:"magic_resist_penetrate_ratio"`
	NoteDelay                 float64 `json:"note_delay"`
	AttackAngle               float64 `json:"attack_angle"`
	RangedDamageNoPenalty     bool    `json:"ranged_damage_no_penalty"`
}

func defaultSakikoSource() *SakikoSourceSpec {
	return &SakikoSourceSpec{
		ConsumerImplemented:       true,
		Elite:                     2,
		Level:                     60,
		Potential:                 1,
		ModuleLevel:               3,
		MaxNoteCount:              12,
		DefPenetrateRatio:         0.05,
		MagicResistPenetrateRatio: 0.025,
		NoteDelay:                 1.0,
		AttackAngle:               20.0,
		RangedDamageNoPenalty:     true,
	}
}
