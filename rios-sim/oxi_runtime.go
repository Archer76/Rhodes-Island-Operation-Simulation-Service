package main

import (
	"math"
)

// OxiFlameCell 表示第二天赋「我即火焰」在地面留下的足迹烈焰地块
type OxiFlameCell struct {
	Cell       [2]int
	ExpiresAt  float64
	NextTickAt float64
}

// OxiWave 表示技能三「日冕重烈」发射的火浪弹道实体
type OxiWave struct {
	WaveID     int
	BirthTime  float64
	Origin     [2]float64
	Pos        [2]float64
	DX         int
	DY         int
	Dist       float64
	MaxDist    float64
	Speed      float64
	HalfWidth  float64
	RangeR     float64
	ProjR      float64
	Scale      float64
	RepeatScl  float64
	Overload   bool
	HitEnemies map[int]bool // 记录本波次已命中的敌人下标
}

// OxiRuntime 封装塔露拉（char_4247_oxi）在仿真中的所有运行时状态与领域状态机
type OxiRuntime struct {
	Config   *OxiRuntimeConfig
	Position [2]int
	Dir      string

	// 天赋一「绝不妥协」
	IdleTimer    float64
	ArcaneStacks int

	// 第二天赋「我即火焰」
	FlameCells       []*OxiFlameCell
	BurstEnemyWindow map[int]float64 // enemy index -> 窗口截止时刻

	// 技能 2「阂断骤雪」
	Charges         int
	InActivePeriod  bool
	ActiveRemaining float64
	BuffStacks      int
	BuffExpiresAt   float64

	// 技能 3「日冕重烈」
	Waves        []*OxiWave
	WaveTimer    float64
	SkillElapsed float64
	NextWaveID   int

	// 统计与事件可观测计数
	TotalRetaliates      int
	TotalHealDealt       float64
	TotalWavesSpawned    int
	TotalWaveHits        int
	TotalFearsApplied    int
	TotalFlameFieldHits  int
	TotalEpDamageDealt   float64
	TotalArcaneBuffBonus float64
}

func newOxiRuntime(cfg *OxiRuntimeConfig) *OxiRuntime {
	rt := &OxiRuntime{
		Config:           cfg,
		BurstEnemyWindow: make(map[int]float64),
		Waves:            make([]*OxiWave, 0),
		FlameCells:       make([]*OxiFlameCell, 0),
	}
	if cfg.Slot == 2 {
		rt.Charges = cfg.InitSP
		if rt.Charges > cfg.S2MaxStackCnt {
			rt.Charges = cfg.S2MaxStackCnt
		}
	}
	return rt
}

// deriveDirectionFromRange 从干员的站位格与绝对攻击范围格精确推导出部署朝向
func deriveDirectionFromRange(cell [2]int, rng [][2]int) string {
	for _, c := range rng {
		if c == cell {
			continue
		}
		dx := c[0] - cell[0]
		dy := c[1] - cell[1]
		if dx > 0 && dy == 0 {
			return "Right"
		}
		if dx < 0 && dy == 0 {
			return "Left"
		}
		if dx == 0 && dy < 0 {
			return "Up"
		}
		if dx == 0 && dy > 0 {
			return "Down"
		}
	}
	return "Right"
}

// GetArcaneDamageMultiplier 返回第一天赋当前提供的伤害加成乘数（1.0 + stacks * step）
func (rt *OxiRuntime) GetArcaneDamageMultiplier() float64 {
	if rt == nil || rt.Config == nil || rt.Config.T1ArcaneStep <= 0 {
		return 1.0
	}
	return 1.0 + float64(rt.ArcaneStacks)*rt.Config.T1ArcaneStep
}

// OnAttack 塔露拉出手攻击命中后的天赋一结算
func (rt *OxiRuntime) OnAttack(target *enemy, t float64) {
	if rt == nil || rt.Config == nil {
		return
	}
	rt.IdleTimer = 0
	if rt.ArcaneStacks > 0 {
		rt.ArcaneStacks--
	}
}

// TickT1 推进第一天赋未攻击计时与增伤层数积蓄
func (rt *OxiRuntime) TickT1(dt float64) {
	if rt == nil || rt.Config == nil || rt.Config.T1ArcaneStep <= 0 {
		return
	}
	rt.IdleTimer += dt
	if rt.IdleTimer >= rt.Config.T1ArcaneIdleDelay {
		afterDelay := rt.IdleTimer - rt.Config.T1ArcaneIdleDelay
		maxStacks := 0
		if rt.Config.T1ArcaneStep > 0 {
			maxStacks = int(math.Round(rt.Config.T1ArcaneMax / rt.Config.T1ArcaneStep))
		}
		if rt.Config.T1ArcaneStepInterval > 0 {
			steps := int(afterDelay/rt.Config.T1ArcaneStepInterval) + 1
			if steps > maxStacks {
				steps = maxStacks
			}
			if steps > rt.ArcaneStacks {
				rt.ArcaneStacks = steps
			}
		}
	}
}

// RecordEnemyBurningBurst 记录场上敌人发生灼燃损伤爆发，开启 5s 留下足迹窗口
func (rt *OxiRuntime) RecordEnemyBurningBurst(enemyIdx int, t float64) {
	if rt == nil || rt.Config == nil || !rt.Config.T2Unlocked {
		return
	}
	rt.BurstEnemyWindow[enemyIdx] = t + 5.0
}

// TryAddFlameField 敌人移动进入新格子时尝试生成足迹烈焰地块
func (rt *OxiRuntime) TryAddFlameField(cell [2]int, t float64) {
	if rt == nil || rt.Config == nil || !rt.Config.T2Unlocked {
		return
	}
	dur := rt.Config.T2FieldDuration
	if dur <= 0 {
		dur = 3.0
	}
	interval := rt.Config.T2FieldInterval
	if interval <= 0 {
		interval = 0.3
	}
	// 检查是否已有该格
	for _, fc := range rt.FlameCells {
		if fc.Cell == cell {
			fc.ExpiresAt = math.Max(fc.ExpiresAt, t+dur)
			return
		}
	}
	maxCnt := rt.Config.T2MaxCount
	if maxCnt <= 0 {
		maxCnt = 25
	}
	if len(rt.FlameCells) >= maxCnt {
		// 淘汰最先生成的格子
		rt.FlameCells = rt.FlameCells[1:]
	}
	rt.FlameCells = append(rt.FlameCells, &OxiFlameCell{
		Cell:       cell,
		ExpiresAt:  t + dur,
		NextTickAt: t + interval,
	})
}

// TickFlameFields 驱动第二天赋烈焰足迹的周期伤害与过期移除
func (rt *OxiRuntime) TickFlameFields(t, dt float64, op *operator, enemies []*enemy, verdict *Verdict) {
	if rt == nil || rt.Config == nil || !rt.Config.T2Unlocked || len(rt.FlameCells) == 0 {
		return
	}
	aliveCells := make([]*OxiFlameCell, 0, len(rt.FlameCells))
	interval := rt.Config.T2FieldInterval
	if interval <= 0 {
		interval = 0.3
	}

	for _, fc := range rt.FlameCells {
		if t >= fc.ExpiresAt {
			continue
		}
		aliveCells = append(aliveCells, fc)
		if t >= fc.NextTickAt {
			fc.NextTickAt = t + interval
			// 对当前站在该格子上的所有地面敌人造成伤害
			for _, e := range enemies {
				if e.hp <= 0 || e.leaked || e.offMap {
					continue
				}
				ecell := [2]int{int(math.RoundToEven(e.position[0])), int(math.RoundToEven(e.position[1]))}
				if ecell == fc.Cell {
					dmg := resolveDamage(op.atk(), "MAGIC", rt.Config.T2FieldAtkScale, 0, e.res(), 0)
					dealt := e.take(dmg, op)
					rt.TotalFlameFieldHits++
					if verdict != nil {
						verdict.Events = append(verdict.Events, Event{
							T:    t,
							Kind: "oxi_t2_field_damage",
							Who:  op.spec.Name,
							Damage: &DamageEventDetail{
								Target:      e.spec.Name,
								TargetIndex: e.index,
								DamageType:  "MAGIC",
								Raw:         op.atk() * rt.Config.T2FieldAtkScale,
								Resolved:    dmg,
								Dealt:       dealt,
								HPAfter:     e.hp,
							},
						})
					}
				}
			}
		}
	}
	rt.FlameCells = aliveCells
}

// OnTakeDamage 技能二受击减伤、反击与生命回复处理
func (rt *OxiRuntime) OnTakeDamage(t float64, attacker *enemy, incomingDamage float64, op *operator, enemies []*enemy, verdict *Verdict) float64 {
	if rt == nil || rt.Config == nil || rt.Config.Slot != 2 {
		return incomingDamage
	}

	// 1. 若当前未在生效期且有可用充能，触发技能二
	if !rt.InActivePeriod && rt.Charges > 0 {
		rt.Charges--
		rt.InActivePeriod = true
		rt.ActiveRemaining = rt.Config.S2SkillDuration
		if rt.ActiveRemaining <= 0 {
			rt.ActiveRemaining = 1.3
		}

		// 叠层攻防加成与阻挡群攻
		maxStacks := rt.Config.S2MaxStackCnt
		if maxStacks <= 0 {
			maxStacks = 5
		}
		if rt.BuffStacks < maxStacks {
			rt.BuffStacks++
		}
		dur := rt.Config.S2StackDuration
		if dur <= 0 {
			dur = 5.0
		}
		rt.BuffExpiresAt = t + dur

		// 范围反击与吸血
		if attacker != nil && attacker.hp > 0 {
			rt.TotalRetaliates++
			retaliateScale := rt.Config.S2RetaliateAtkScale
			radius := rt.Config.S2AbilityRangeRadius
			if radius <= 0 {
				radius = 1.0
			}
			atkCenter := attacker.position
			totalDamageDealt := 0.0

			for _, e := range enemies {
				if e.hp <= 0 || e.leaked || e.offMap {
					continue
				}
				dist := math.Hypot(e.position[0]-atkCenter[0], e.position[1]-atkCenter[1])
				if dist <= radius {
					dmg := resolveDamage(op.atk(), "MAGIC", retaliateScale, 0, e.res(), 0)
					dealt := e.take(dmg, op)
					totalDamageDealt += dealt
					if verdict != nil {
						verdict.Events = append(verdict.Events, Event{
							T:    t,
							Kind: "oxi_s2_retaliate",
							Who:  op.spec.Name,
							Damage: &DamageEventDetail{
								Target:      e.spec.Name,
								TargetIndex: e.index,
								DamageType:  "MAGIC",
								Raw:         op.atk() * retaliateScale,
								Resolved:    dmg,
								Dealt:       dealt,
								HPAfter:     e.hp,
							},
						})
					}
				}
			}

			// 吸血回复生命
			if rt.Config.S2HealRatio > 0 && totalDamageDealt > 0 {
				healAmount := totalDamageDealt * rt.Config.S2HealRatio
				oldHP := op.hp
				op.hp = math.Min(op.maxHP(), op.hp+healAmount)
				rt.TotalHealDealt += (op.hp - oldHP)
				if verdict != nil {
					verdict.Events = append(verdict.Events, Event{
						T:    t,
						Kind: "oxi_s2_heal",
						Who:  op.spec.Name,
						Heal: &HealEventDetail{
							Want:    healAmount,
							Got:     op.hp - oldHP,
							HPAfter: op.hp,
							MaxHP:   op.maxHP(),
						},
					})
				}
			}
		}
	}

	// 2. 计算当前受击减伤比例
	if rt.InActivePeriod {
		skillDur := rt.Config.S2SkillDuration
		if skillDur <= 0 {
			skillDur = 1.3
		}
		elapsed := skillDur - rt.ActiveRemaining
		holdDur := rt.Config.S2ShelterHoldDur
		if holdDur <= 0 {
			holdDur = 0.2
		}
		resist := rt.Config.S2DamageResistance
		if resist <= 0 {
			resist = 0.9
		}
		if elapsed > holdDur && skillDur > holdDur {
			// 线性降低至 0
			decayFraction := (elapsed - holdDur) / (skillDur - holdDur)
			if decayFraction > 1.0 {
				decayFraction = 1.0
			}
			resist *= (1.0 - decayFraction)
		}
		currentScale := 1.0 - resist
		if currentScale < 0.1 {
			currentScale = 0.1
		}
		return incomingDamage * currentScale
	}

	return incomingDamage
}

// TickS2 推进技能二内部时钟
func (rt *OxiRuntime) TickS2(t, dt float64) {
	if rt == nil || rt.Config == nil || rt.Config.Slot != 2 {
		return
	}
	if rt.InActivePeriod {
		rt.ActiveRemaining -= dt
		if rt.ActiveRemaining <= 0 {
			rt.InActivePeriod = false
		}
	}
	if rt.BuffStacks > 0 && t >= rt.BuffExpiresAt {
		rt.BuffStacks = 0
	}
}

// GetS2Buffs 获取技能二当前提供的攻击力加成、防御力加成与阻挡群攻标记
func (rt *OxiRuntime) GetS2Buffs() (atkBonus, defBonus float64, attacksAllBlocked bool) {
	if rt == nil || rt.Config == nil || rt.Config.Slot != 2 || rt.BuffStacks <= 0 {
		return 0, 0, false
	}
	atkBonus = float64(rt.BuffStacks) * rt.Config.S2Atk
	defBonus = float64(rt.BuffStacks) * rt.Config.S2Def
	attacksAllBlocked = true
	return atkBonus, defBonus, attacksAllBlocked
}

// SpawnS3Wave 生成一波技能三火浪
func (rt *OxiRuntime) SpawnS3Wave(t float64, op *operator) {
	if rt == nil || rt.Config == nil || rt.Config.Slot != 3 {
		return
	}
	overload := rt.SkillElapsed >= (rt.Config.Duration / 2.0)
	halfWidth := rt.Config.S3NormalHalfWidth
	if overload {
		halfWidth = rt.Config.S3OverloadHalfWidth
	}
	dx, dy := dirToDelta(rt.Dir)
	rt.NextWaveID++
	w := &OxiWave{
		WaveID:     rt.NextWaveID,
		BirthTime:  t,
		Origin:     [2]float64{float64(rt.Position[0]), float64(rt.Position[1])},
		Pos:        [2]float64{float64(rt.Position[0]), float64(rt.Position[1])},
		DX:         dx,
		DY:         dy,
		Dist:       0,
		MaxDist:    rt.Config.S3WaveExitDistance,
		Speed:      rt.Config.S3WaveSpeed,
		HalfWidth:  halfWidth,
		RangeR:     rt.Config.S3RangeRadius,
		ProjR:      rt.Config.S3ProjectileRange,
		Scale:      rt.Config.S3HeatwaveAtkScale,
		RepeatScl:  rt.Config.S3SameWaveRepeatScale,
		Overload:   overload,
		HitEnemies: make(map[int]bool),
	}
	if w.MaxDist <= 0 {
		w.MaxDist = 5.0
	}
	if w.Speed <= 0 {
		w.Speed = 2.3
	}
	if w.ProjR <= 0 {
		w.ProjR = 0.5
	}
	if w.RangeR <= 0 {
		w.RangeR = 1.5
	}
	if w.RepeatScl <= 0 {
		w.RepeatScl = 0.15
	}
	rt.Waves = append(rt.Waves, w)
	rt.TotalWavesSpawned++
}

// TickS3 推进技能三的火浪推移与碰撞结算
func (rt *OxiRuntime) TickS3(t, dt float64, op *operator, enemies []*enemy, verdict *Verdict) {
	if rt == nil || rt.Config == nil || rt.Config.Slot != 3 {
		return
	}
	if op.skillActive {
		rt.SkillElapsed += dt
		overload := rt.SkillElapsed >= (rt.Config.Duration / 2.0)
		interval := rt.Config.S3NormalInterval
		if overload {
			interval = rt.Config.S3OverloadInterval
		}
		if interval <= 0 {
			interval = 2.67
		}
		rt.WaveTimer += dt
		if rt.WaveTimer >= interval {
			rt.WaveTimer -= interval
			rt.SpawnS3Wave(t, op)
			if verdict != nil {
				verdict.Events = append(verdict.Events, Event{
					T:    t,
					Kind: "oxi_s3_wave_spawn",
					Who:  op.spec.Name,
				})
			}
		}
	} else {
		rt.SkillElapsed = 0
		rt.WaveTimer = 0
	}

	aliveWaves := make([]*OxiWave, 0, len(rt.Waves))
	for _, w := range rt.Waves {
		w.Dist += w.Speed * dt
		w.Pos[0] = w.Origin[0] + float64(w.DX)*w.Dist
		w.Pos[1] = w.Origin[1] + float64(w.DY)*w.Dist

		// 检测沿途碰撞
		for _, e := range enemies {
			if e.hp <= 0 || e.leaked || e.offMap {
				continue
			}
			// 投影距离与横向距离
			projDist := (e.position[0]-w.Origin[0])*float64(w.DX) + (e.position[1]-w.Origin[1])*float64(w.DY)
			lateralDist := math.Abs((e.position[0]-w.Origin[0])*float64(-w.DY) + (e.position[1]-w.Origin[1])*float64(w.DX))

			if math.Abs(projDist-w.Dist) <= w.ProjR && lateralDist <= (w.HalfWidth+0.5) {
				// 发生碰撞！以火浪前锋位置引发爆炸
				explodeCenter := w.Pos
				for _, victim := range enemies {
					if victim.hp <= 0 || victim.leaked || victim.offMap {
						continue
					}
					vDist := math.Hypot(victim.position[0]-explodeCenter[0], victim.position[1]-explodeCenter[1])
					if vDist <= w.RangeR {
						scale := w.Scale
						if w.HitEnemies[victim.index] {
							scale *= w.RepeatScl
						}
						w.HitEnemies[victim.index] = true
						rt.TotalWaveHits++

						// 伤害类型：若敌人处于灼燃损伤爆发冷却期，转为真实/元素伤害
						dmgType := "MAGIC"
						isBursting := false
						if victim.element != nil && victim.element.cooling(elemFire) {
							isBursting = true
						}
						if rt.BurstEnemyWindow[victim.index] > t {
							isBursting = true
						}
						if isBursting {
							dmgType = "TRUE"
						}

						dmg := resolveDamage(op.atk(), dmgType, scale, 0, victim.res(), 0)
						dealt := victim.take(dmg, op)

						if verdict != nil {
							verdict.Events = append(verdict.Events, Event{
								T:    t,
								Kind: "oxi_s3_wave_hit",
								Who:  op.spec.Name,
								Damage: &DamageEventDetail{
									Target:      victim.spec.Name,
									TargetIndex: victim.index,
									DamageType:  dmgType,
									Raw:         op.atk() * scale,
									Resolved:    dmg,
									Dealt:       dealt,
									HPAfter:     victim.hp,
								},
							})
						}
					}
				}
			}
		}

		if w.Dist < w.MaxDist {
			aliveWaves = append(aliveWaves, w)
		}
	}
	rt.Waves = aliveWaves
}
