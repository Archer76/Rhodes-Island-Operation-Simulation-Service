package main

import (
	"fmt"
)

// RadianCombatState 管理电弧本体及其全部召唤物的战斗循环、技能状态与天赋
type RadianCombatState struct {
	Deployment RadianDeploymentState
	OwnerAtk   float64 // 电弧本体基础攻击力
	OwnerDef   float64 // 电弧本体基础防御力
	OwnerMaxHp float64 // 电弧本体基础生命值
	OwnerHp    float64 // 电弧本体当前生命值
	BarrierHp  float64 // 电弧本体护盾/屏障

	// 技能运行时状态
	SkillActive  bool
	SkillTimer   float64 // 技能剩余持续时间
	SkillSP      float64 // 当前 SP
	SkillMaxSP   float64 // 技力消耗
}

func newRadianCombatState(owner string, cfg radianRuntimeConfig, ownerAtk, ownerDef, ownerMaxHp, spCost, initSp float64) RadianCombatState {
	// 基础属性计入第二天赋【加油~】
	effAtk := ownerAtk * (1.0 + cfg.Talent2AtkRatio)
	effDef := ownerDef * (1.0 + cfg.Talent2DefRatio)
	effHp := ownerMaxHp * (1.0 + cfg.Talent2HpRatio)

	return RadianCombatState{
		Deployment:  newRadianDeploymentState(owner, cfg),
		OwnerAtk:    effAtk,
		OwnerDef:    effDef,
		OwnerMaxHp:  effHp,
		OwnerHp:     effHp,
		SkillSP:     initSp,
		SkillMaxSP:  spCost,
	}
}

// EffectiveOwnerStats 返回电弧本体计入第二天赋与技能后的有效攻击与防御
func (c *RadianCombatState) EffectiveOwnerStats() (atk, def float64) {
	atk = c.OwnerAtk
	def = c.OwnerDef
	if c.SkillActive {
		switch c.Deployment.Config.Slot {
		case 1:
			def *= (1.0 + c.Deployment.Config.S1DefBuff)
		case 2:
			atk *= (1.0 + c.Deployment.Config.S2AtkBuff)
		case 3:
			atk *= (1.0 + c.Deployment.Config.S3AtkBuff)
		}
	}
	return atk, def
}

// EffectiveTokenStats 计算召唤物计入技能增益后的当前攻防与攻速
func (c *RadianCombatState) EffectiveTokenStats(t *RadianTokenEntity) (atk, def, aspd float64, isMagic bool) {
	atk = t.Atk
	def = t.Def
	aspd = 100.0

	// 基础伤害类型：戴乌/鳞地 (S1/S2) 为物理伤害；棱镜塔 (S3) 为法术伤害
	if t.TokenKey == radianTokenTower3 {
		isMagic = true
	} else {
		isMagic = false
	}

	if c.SkillActive {
		switch c.Deployment.Config.Slot {
		case 1:
			def *= (1.0 + c.Deployment.Config.S1DefBuff)
		case 2:
			atk *= (1.0 + c.Deployment.Config.S2AtkBuff)
		case 3:
			atk *= (1.0 + c.Deployment.Config.S3AtkBuff)
			isMagic = true
		}
	}
	return atk, def, aspd, isMagic
}

// NotifyTokenRemoval 处理召唤物离场（被击倒/撤退）
func (c *RadianCombatState) NotifyTokenRemoval(t *RadianTokenEntity, availableSquadDeploySlots *int) {
	if !t.Alive {
		return
	}
	t.Alive = false

	// 返还团队部署位
	if availableSquadDeploySlots != nil {
		*availableSquadDeploySlots += t.DeploySlots
	}
}

// TriggerSkill 手动/自动开启技能
func (c *RadianCombatState) TriggerSkill(now float64) error {
	if c.SkillActive {
		return fmt.Errorf("radian skill already active")
	}
	if c.SkillSP < c.SkillMaxSP {
		return fmt.Errorf("insufficient SP (%.1f / %.1f)", c.SkillSP, c.SkillMaxSP)
	}

	c.SkillActive = true
	c.SkillSP = 0.0

	switch c.Deployment.Config.Slot {
	case 1:
		c.SkillTimer = c.Deployment.Config.S1Duration
		c.Deployment.Inventory += c.Deployment.Config.S1SupplyCnt // 技能开启时获得 1 个召唤物

		// S1 护盾/屏障加成：自身与所有场上戴乌获得相当于各自最大生命值 hp_ratio 的屏障
		c.BarrierHp = c.OwnerMaxHp * c.Deployment.Config.S1BarrierRatio
		for _, t := range c.Deployment.ActiveTokens() {
			t.BarrierHp = t.MaxHp * c.Deployment.Config.S1BarrierRatio
		}

	case 2:
		c.SkillTimer = c.Deployment.Config.S2Duration
		c.Deployment.Inventory += c.Deployment.Config.S2SupplyCnt // 技能开启时获得 1 个召唤物

	case 3:
		c.SkillTimer = c.Deployment.Config.S3Duration
		c.Deployment.Inventory += c.Deployment.Config.S3SupplyCnt // 技能开启时获得 1 个召唤物
	}

	return nil
}

// FinishSkill 技能持续时间结束时的收尾结算
func (c *RadianCombatState) FinishSkill(now float64) {
	if !c.SkillActive {
		return
	}
	c.SkillActive = false
	c.SkillTimer = 0.0

	// S1 屏障在技能结束时消失
	if c.Deployment.Config.Slot == 1 {
		c.BarrierHp = 0.0
		for _, t := range c.Deployment.Tokens {
			t.BarrierHp = 0.0
		}
	}
}
