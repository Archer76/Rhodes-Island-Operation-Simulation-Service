package main

import (
	"fmt"
)

type wisdelCombatState struct {
	Owner   string
	Pos     Cell
	Dir     string
	Config  wisdelRuntimeConfig
	BaseATK float64

	// Active status
	SkillActive    bool
	SkillTimer     float64
	SkillDuration  float64
	SkillAmmo      int
	OverdrivePhase bool

	// Wards
	Wards      []*wisdelWard
	NextWardID int

	// Marked enemies (*enemy -> true)
	MarkedEnemies map[*enemy]bool
}

func newWisdelCombatState(owner string, pos Cell, dir string, cfg wisdelRuntimeConfig, baseATK float64) *wisdelCombatState {
	return &wisdelCombatState{
		Owner:         owner,
		Pos:           pos,
		Dir:           dir,
		Config:        cfg,
		BaseATK:       baseATK,
		Wards:         make([]*wisdelWard, 0),
		MarkedEnemies: make(map[*enemy]bool),
	}
}

func (c *wisdelCombatState) HasCamouflage() bool {
	return isWisdelNearWard(c.Pos, c.Wards)
}

func (c *wisdelCombatState) EffectiveATK() float64 {
	atk := c.BaseATK
	if c.SkillActive {
		switch c.Config.Slot {
		case 2:
			atk *= (1.0 + c.Config.S2Atk)
		case 3:
			atk *= (1.0 + c.Config.S3Atk)
		}
	}
	return atk
}

func (c *wisdelCombatState) BaseAttackInterval() float64 {
	interval := 2.1
	if c.SkillActive {
		switch c.Config.Slot {
		case 2:
			interval += c.Config.S2BaseAttackTime // -0.5 ~ -0.7 -> 1.4s~1.6s
		case 3:
			interval += c.Config.S3BaseAttackTime // +2.9 -> 5.0s
		}
	}
	if interval < 0.2 {
		interval = 0.2
	}
	return interval
}

func (c *wisdelCombatState) DeployWard(pos Cell, atk, def, res, hp float64) error {
	if len(c.Wards) >= 3 {
		// Cap at 3
		return fmt.Errorf("ward limit reached")
	}
	c.NextWardID++
	ward := newWisdelWard(c.NextWardID, c.Owner, pos, atk, def, res, hp, c.Config.WardSluggish, c.Config.WardSpMin, c.Config.WardSpMax)
	c.Wards = append(c.Wards, ward)
	return nil
}

func (c *wisdelCombatState) ActivateSkill(candidateCells []Cell, wardATK, wardDEF, wardRES, wardHP float64) error {
	if c.SkillActive {
		return fmt.Errorf("wisdel skill already active")
	}
	c.SkillActive = true
	c.SkillTimer = 0.0
	c.OverdrivePhase = false

	switch c.Config.Slot {
	case 1:
		c.SkillDuration = 0.0 // Instant attack modifier
	case 2:
		c.SkillDuration = 25.0
	case 3:
		c.SkillDuration = -1.0
		c.SkillAmmo = c.Config.S3TriggerTime // 6 ammo
		// Summon wards up to max_cnt
		summonCount := c.Config.S3MaxCnt
		for _, cell := range candidateCells {
			if summonCount <= 0 || len(c.Wards) >= 3 {
				break
			}
			_ = c.DeployWard(cell, wardATK, wardDEF, wardRES, wardHP)
			summonCount--
		}
	}
	return nil
}

func (c *wisdelCombatState) EndSkill() {
	c.SkillActive = false
	c.SkillTimer = 0.0
	c.SkillAmmo = 0
	c.OverdrivePhase = false
}

func (c *wisdelCombatState) Tick(dt float64) {
	if !c.SkillActive {
		return
	}
	c.SkillTimer += dt
	if c.Config.Slot == 2 {
		if c.SkillTimer >= c.SkillDuration/2.0 {
			c.OverdrivePhase = true
		}
		if c.SkillTimer >= c.SkillDuration {
			c.EndSkill()
		}
	}
}

type WisdelDamageInstance struct {
	TargetEnemy   *enemy
	Damage        float64
	IsAftershock  bool
	IsBombAOE     bool
	StunDuration  float64
}

func (c *wisdelCombatState) Attack(primaryTarget *enemy, nearbyGroundEnemies []*enemy, rngRoll float64) ([]WisdelDamageInstance, error) {
	if primaryTarget == nil || primaryTarget.hp <= 0 {
		return nil, fmt.Errorf("nil or dead target")
	}

	effAtk := c.EffectiveATK()
	var instances []WisdelDamageInstance

	// Determine number of hits & aftershocks
	// Primary hit:
	primaryScale := c.Config.TalentMainAtkScale
	if c.SkillActive && c.Config.Slot == 3 {
		primaryScale = c.Config.S3AtkScale3
	}
	primaryDamage := effAtk * primaryScale

	// Skill 2 Overdrive special
	if c.SkillActive && c.Config.Slot == 2 && c.OverdrivePhase {
		// 4-hit overdrive
		for i := 0; i < 4; i++ {
			instances = append(instances, WisdelDamageInstance{
				TargetEnemy:  primaryTarget,
				Damage:       effAtk * c.Config.S2AtkScaleOl,
				IsAftershock: false,
			})
		}
		// Overdrive attacks also trigger marks on primary target
		c.MarkedEnemies[primaryTarget] = true
		return instances, nil
	}

	// 1. Primary main hit
	instances = append(instances, WisdelDamageInstance{
		TargetEnemy:  primaryTarget,
		Damage:       primaryDamage,
		IsAftershock: false,
	})

	// Attach mark to main target
	c.MarkedEnemies[primaryTarget] = true

	// 2. Splash ground enemies
	allGround := append([]*enemy{primaryTarget}, nearbyGroundEnemies...)

	// Determine aftershock count:
	aftershockCount := 1
	if c.Config.EnableThirdAttack {
		aftershockCount = 2
	}
	if c.SkillActive && c.Config.Slot == 1 {
		aftershockCount += 2
	}

	// Determine aftershock scale:
	aftershockScale := c.Config.AppendAtkScale
	s1Stun := 0.0
	if c.SkillActive && c.Config.Slot == 1 {
		aftershockScale = c.Config.S1AppendAtkScale
		s1Stun = c.Config.S1StunDuration
	}

	// 3. Process aftershocks
	for a := 0; a < aftershockCount; a++ {
		for _, e := range allGround {
			if e == nil || e.hp <= 0 {
				continue
			}
			instances = append(instances, WisdelDamageInstance{
				TargetEnemy:  e,
				Damage:       effAtk * aftershockScale,
				IsAftershock: true,
				StunDuration: s1Stun,
			})

			// Check talent 1 bomb explosion on marked enemies affected by aftershock
			if c.MarkedEnemies[e] {
				bombProb := c.Config.TalentBombProb
				if c.SkillActive && c.Config.Slot == 3 {
					bombProb = c.Config.S3Prob // 1.0 (100%)
				}
				if rngRoll <= bombProb {
					bombDmg := effAtk * c.Config.TalentBombAtkScale
					// Bomb explodes on e and nearby ground enemies
					for _, ne := range allGround {
						instances = append(instances, WisdelDamageInstance{
							TargetEnemy:  ne,
							Damage:       bombDmg,
							IsBombAOE:    true,
							StunDuration: c.Config.TalentBombStun,
						})
					}
				}
			}
		}
	}

	// Ammo consumption for Skill 3
	if c.SkillActive && c.Config.Slot == 3 {
		c.SkillAmmo--
		if c.SkillAmmo <= 0 {
			c.EndSkill()
		}
	}

	return instances, nil
}
