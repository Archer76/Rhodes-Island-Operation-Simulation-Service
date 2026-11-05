package main

import (
	"math"
)

// mcnistSimTick 驱动机械师与召唤物在主战斗循环中的时序逻辑
func mcnistSimTick(ops []*operator, enemies []*enemy, dt, t float64, spec *Spec, verdict *Verdict) {
	for _, op := range ops {
		if op == nil || op.spec.CharID != mcnistCharID || op.mcnistRuntime == nil {
			continue
		}
		rt := op.mcnistRuntime
		cfg := rt.Config

		// 若机械师已倒下或撤退，清空所有协同与召唤物
		if !op.alive() {
			if rt.TokenDeployed && rt.TokenOp != nil {
				rt.TokenOp.hp = 0
			}
			rt.ClearAll()
			continue
		}

		// 0. 更新战栗 (Tremble) 与虚弱 (Weaken) 状态计时
		for eIdx, rem := range rt.TrembleDebuffs {
			rem -= dt
			if rem <= 0 {
				delete(rt.TrembleDebuffs, eIdx)
			} else {
				rt.TrembleDebuffs[eIdx] = rem
			}
		}

		// 更新虚弱光环衰减（初始 50%，每秒 -2.5% = 每帧 -0.025 * dt）
		if rt.WeakenAuraActive {
			rt.WeakenAuraRatio -= 0.025 * dt
			if rt.WeakenAuraRatio <= 0 {
				rt.WeakenAuraActive = false
				rt.WeakenAuraRatio = 0
				for eIdx := range rt.WeakenDebuffs {
					delete(rt.WeakenDebuffs, eIdx)
				}
			} else {
				// 刷新光环半径 1.5 范围内的敌人虚弱比例
				for _, e := range enemies {
					if e == nil || e.hp <= 0 || e.offMap {
						continue
					}
					dist := math.Hypot(e.position[0]-float64(rt.WeakenAuraCenter[0]), e.position[1]-float64(rt.WeakenAuraCenter[1]))
					if dist <= cfg.S3ProjectileRange {
						rt.WeakenDebuffs[e.index] = rt.WeakenAuraRatio
					}
				}
			}
		}

		// 1. 结构性原理召唤物生命周期与自动离场
		if rt.TokenDeployed && rt.TokenOp != nil {
			if rt.TokenOp.hp <= 0 {
				rt.TokenDeployed = false
				rt.TokenOp = nil
				rt.TokenBarrier = McnistBarrierHolder{}
				rt.TokenCooldown = 40.0
			} else {
				rt.TokenLifetime -= dt
				if rt.TokenLifetime <= 0 {
					// 持续时间耗尽，自动撤退
					rt.TokenOp.hp = 0
					rt.TokenDeployed = false
					rt.TokenOp = nil
					rt.TokenBarrier = McnistBarrierHolder{}
					rt.TokenCooldown = 40.0
				}
			}
		} else if rt.TokenCooldown > 0 {
			rt.TokenCooldown -= dt
			if rt.TokenCooldown < 0 {
				rt.TokenCooldown = 0
			}
		}

		// 2. 技能释放与状态机处理
		if op.skillActive {
			switch cfg.Slot {
			case 1:
				// S1【聚类分析】
				// 技能激活时装填弹药
				if rt.AmmoRemaining == 0 && !rt.S1Firing {
					rt.AmmoRemaining = cfg.S1TriggerTime
				}

			case 2:
				// S2【协防术式】
				// 技能激活瞬间获得屏障与装填弹药
				if rt.AmmoRemaining == 0 {
					rt.AmmoRemaining = cfg.S2TriggerTime
					barrierVal := op.maxHP() * cfg.S2HPRatio
					rt.OwnerBarrier = McnistBarrierHolder{
						Barrier:         barrierVal,
						OverkillProtect: true,
					}
					if rt.TokenDeployed && rt.TokenOp != nil && rt.TokenOp.alive() {
						tokBarrierVal := rt.TokenOp.maxHP() * cfg.S2HPRatio
						rt.TokenBarrier = McnistBarrierHolder{
							Barrier:         tokBarrierVal,
							OverkillProtect: true,
						}
					}
				}

			case 3:
				// S3【工程学十字星】
				// 技能激活瞬间：若召唤物在场且尚未冲锋，执行结构性原理冲锋
				if !rt.S3DashTriggered && rt.TokenDeployed && rt.TokenOp != nil && rt.TokenOp.alive() {
					rt.S3DashTriggered = true
					performTokenDash(rt, op, enemies, spec)
				}
			}
		} else {
			// 技能关闭时复位弹药与冲锋状态
			if cfg.Slot == 1 || cfg.Slot == 2 {
				rt.AmmoRemaining = 0
				rt.S1Firing = false
			}
			if cfg.Slot == 3 {
				rt.S3DashTriggered = false
			}
		}
	}
}

// performTokenDash 执行结构性原理向前冲锋并施加虚弱光环与 300% 物理范围伤害
func performTokenDash(rt *McnistRuntime, ownerOp *operator, enemies []*enemy, spec *Spec) {
	tokenOp := rt.TokenOp
	if tokenOp == nil || !tokenOp.alive() {
		return
	}

	startX := int(tokenOp.cell[0])
	startY := int(tokenOp.cell[1])
	targetX := startX
	targetY := startY

	// 按部署朝向向前搜寻最远可到达地块（最多 4 格）
	dir := deriveDirectionFromRange([2]int{startX, startY}, tokenOp.spec.Range)
	stepX := 0
	stepY := 0
	switch dir {
	case "Right", "East":
		stepX = 1
	case "Left", "West":
		stepX = -1
	case "Up", "North":
		stepY = -1
	case "Down", "South":
		stepY = 1
	default:
		stepX = 1
	}

	for i := 1; i <= 4; i++ {
		nextX := startX + stepX*i
		nextY := startY + stepY*i

		// 检查地块上是否存在敌人
		hasEnemy := false
		for _, e := range enemies {
			if e != nil && e.hp > 0 && !e.offMap {
				if int(math.Round(e.position[0])) == nextX && int(math.Round(e.position[1])) == nextY {
					hasEnemy = true
					break
				}
			}
		}

		targetX = nextX
		targetY = nextY

		if hasEnemy {
			break // 碰到敌人停下
		}
	}

	// 重新落位
	tokenOp.cell[0] = float64(targetX)
	tokenOp.cell[1] = float64(targetY)

	// 对停下地块半径 1.5 范围内的所有敌人造成 300% 机械师攻击力的物理伤害
	dashDmg := ownerOp.atk() * rt.Config.S3DashAtkScale
	for _, e := range enemies {
		if e == nil || e.hp <= 0 || e.offMap {
			continue
		}
		dist := math.Hypot(e.position[0]-float64(targetX), e.position[1]-float64(targetY))
		if dist <= rt.Config.S3ProjectileRange {
			dealt := e.take(dashDmg, ownerOp)
			if dealt > 0 {
				rt.TotalDashDamageHits++
			}
		}
	}

	// 开启虚弱光环（衰减型，初始 50%）
	rt.WeakenAuraActive = true
	rt.WeakenAuraCenter = [2]int{targetX, targetY}
	rt.WeakenAuraRatio = 0.50
}

// CheckAndHandleS2BarrierBurst 检查屏障是否破裂并触发反击与重装填
func (r *McnistRuntime) CheckAndHandleS2BarrierBurst(isOwner bool, ownerOp *operator, enemies []*enemy) {
	if r.Config.Slot != 2 || !ownerOp.skillActive || r.S2BarrierBurstProcessing {
		return
	}

	var centerCell [2]float64
	var holder *McnistBarrierHolder
	if isOwner {
		holder = &r.OwnerBarrier
		centerCell = ownerOp.cell
	} else if r.TokenOp != nil {
		holder = &r.TokenBarrier
		centerCell = r.TokenOp.cell
	} else {
		return
	}

	// 当屏障归零且技能处于激活状态时触发破裂反击
	if holder.Barrier <= 0 {
		r.S2BarrierBurstProcessing = true
		defer func() { r.S2BarrierBurstProcessing = false }()

		// 对半径 1.5 内的所有敌人造成 200% 法术伤害并施加战栗
		burstDmg := ownerOp.atk() * r.Config.S2AtkScale
		for _, e := range enemies {
			if e == nil || e.hp <= 0 || e.offMap {
				continue
			}
			dist := math.Hypot(e.position[0]-centerCell[0], e.position[1]-centerCell[1])
			if dist <= r.Config.S2RangeRadius {
				dealt := e.take(burstDmg, ownerOp)
				if dealt > 0 {
					r.TotalBurstDamageHits++
				}
				// 施加战栗 (not_combat 秒)
				r.TrembleDebuffs[e.index] = r.Config.S2TrembleSec
			}
		}

		// 消耗 1 发弹药重新获得 10% 屏障
		if r.AmmoRemaining > 0 {
			r.AmmoRemaining--
			var baseTarget *operator = ownerOp
			if !isOwner && r.TokenOp != nil {
				baseTarget = r.TokenOp
			}
			holder.Barrier = baseTarget.maxHP() * r.Config.S2HPRatio
			holder.OverkillProtect = true
		} else {
			// 弹药耗尽且屏障全破，技能结束
			if r.OwnerBarrier.Barrier <= 0 && (!r.TokenDeployed || r.TokenBarrier.Barrier <= 0) {
				ownerOp.skillActive = false
				ownerOp.sp = 0
			}
		}
	}
}
