package main

import (
	"fmt"
)

// LingDirection 朝向定义
type LingDirection string

const (
	LingDirRight LingDirection = "Right"
	LingDirLeft  LingDirection = "Left"
	LingDirUp    LingDirection = "Up"
	LingDirDown  LingDirection = "Down"
)

// LingPosition 站位类型
type LingPosition string

const (
	LingPosMelee  LingPosition = "MELEE"
	LingPosRanged LingPosition = "RANGED"
)

type LingTokenForm int

const (
	LingFormNormal LingTokenForm = 1 // 基础形态
	LingFormFused  LingTokenForm = 2 // 高级合体形态（仅限弦惊）
)

// LingTokenEntity 代表令召唤的一个具体在场实体（清平 / 逍遥 / 弦惊）
type LingTokenEntity struct {
	ID        uint64
	Owner     string        // 干员实例 ID
	TokenKey  string        // token_10020_ling_soul1 / 2 / 3
	Name      string        // “清平” / “逍遥” / “弦惊”
	Cell      Cell          // 所在坐标 [2]int{x, y}
	Direction LingDirection // 朝向
	Position  LingPosition  // MELEE 或 RANGED
	Form      LingTokenForm // 普通形态 / 高级形态

	// 战斗属性与状态
	MaxHp           float64
	CurrentHp       float64
	Atk             float64
	Def             float64
	MagicResistance float64
	BlockCnt        int
	BaseAttackTime  float64
	AttackTimer     float64
	PulseTimer      float64 // 技3 弦惊周围四格脉冲计时器

	// 部署占位与生命周期
	DeploySlots int     // 占据部署位数（普通: 1, 合体高级: 2）
	DeployTime  float64 // 部署时刻
	Alive       bool
}

// LingDeploymentCell 描述部署格子的环境信息
type LingDeploymentCell struct {
	Position       Cell
	MapKnown       bool
	Deployable     bool
	OccupancyKnown bool
	RoleOccupied   bool
	IsHighland     bool // 高台还是地面
}

// LingDeploymentState 维护令干员的召唤物库存、场上实体列表与部署约束
type LingDeploymentState struct {
	Owner       string
	Config      lingRuntimeConfig
	Inventory   int                // 当前持有召唤物数量
	Tokens      []*LingTokenEntity // 场上所有已部署实体
	NextDeploy  float64            // 部署公共 CD
	NextTokenID uint64
}

func newLingDeploymentState(owner string, cfg lingRuntimeConfig) LingDeploymentState {
	return LingDeploymentState{
		Owner:       owner,
		Config:      cfg,
		Inventory:   cfg.InventoryMax,
		Tokens:      make([]*LingTokenEntity, 0, cfg.FieldMax),
		NextTokenID: 1,
	}
}

// ActiveTokens 返回场上存活的所有召唤物
func (s *LingDeploymentState) ActiveTokens() []*LingTokenEntity {
	var active []*LingTokenEntity
	for _, t := range s.Tokens {
		if t.Alive {
			active = append(active, t)
		}
	}
	return active
}

// ActiveTokenCount 返回场上存活的召唤物数量（按实体个数，而非部署位数）
func (s *LingDeploymentState) ActiveTokenCount() int {
	return len(s.ActiveTokens())
}

// TotalDeploySlotsUsed 返回场上存活召唤物所占用的总部署位数
func (s *LingDeploymentState) TotalDeploySlotsUsed() int {
	slots := 0
	for _, t := range s.Tokens {
		if t.Alive {
			slots += t.DeploySlots
		}
	}
	return slots
}

// AddInventory 补给库存（技1开启、技3结束或回收返还）
func (s *LingDeploymentState) AddInventory(cnt int) {
	s.Inventory += cnt
	if s.Inventory > s.Config.InventoryMax {
		s.Inventory = s.Config.InventoryMax
	}
}

// FindTokenAt 查找指定格子上的存活召唤物
func (s *LingDeploymentState) FindTokenAt(c Cell) *LingTokenEntity {
	for _, t := range s.Tokens {
		if t.Alive && t.Cell == c {
			return t
		}
	}
	return nil
}

// CheckFusionTarget 检查在指定坐标 c 部署弦惊时，是否与攻击范围相交的基础弦惊触发合体
// 弦惊基础形态攻击范围 1-1（自身格 + 正前方1格）。若自身朝向前方是已有的弦惊，或者已有的弦惊正前方是 c，均构成相交。
func (s *LingDeploymentState) CheckFusionTarget(c Cell, dir LingDirection) *LingTokenEntity {
	if s.Config.Slot != 3 {
		return nil
	}
	// 计算新部署位置的前方一格
	dx, dy := 0, 0
	switch dir {
	case LingDirUp:
		dy = -1
	case LingDirDown:
		dy = 1
	case LingDirLeft:
		dx = -1
	case LingDirRight:
		dx = 1
	}
	frontCell := Cell{c[0] + dx, c[1] + dy}

	for _, t := range s.ActiveTokens() {
		// 只有基础形态的弦惊可以参与合体；高级形态不可再合体
		if t.Form != LingFormNormal || t.TokenKey != lingTokenSoul3 {
			continue
		}
		// 1. 新弦惊正前方面向已有弦惊
		if frontCell == t.Cell {
			return t
		}
		// 2. 已有弦惊正前方正对着新弦惊的放置格
		tFront := Cell{t.Cell[0], t.Cell[1]}
		switch t.Direction {
		case LingDirUp:
			tFront[1] -= 1
		case LingDirDown:
			tFront[1] += 1
		case LingDirLeft:
			tFront[0] -= 1
		case LingDirRight:
			tFront[0] += 1
		}
		if tFront == c {
			return t
		}
	}
	return nil
}

// DeployToken 执行部署召唤物事务
func (s *LingDeploymentState) DeployToken(now float64, cell LingDeploymentCell, dir LingDirection, cost *float64, availableSquadDeploySlots *int) (*LingTokenEntity, *LingTokenEntity, error) {
	if s.Owner == "" || cost == nil || availableSquadDeploySlots == nil || now < 0 {
		return nil, nil, fmt.Errorf("invalid ling deployment identity/time/cost")
	}
	if !cell.MapKnown || !cell.OccupancyKnown {
		return nil, nil, fmt.Errorf("ling map or occupancy source missing")
	}
	if !cell.Deployable || cell.RoleOccupied {
		return nil, nil, fmt.Errorf("ling landing not deployable or occupied")
	}

	// 部署位置合法性检查：清平(S1)与弦惊(S3)为近战地面；逍遥(S2)为高台
	if s.Config.Slot == 2 {
		if !cell.IsHighland {
			return nil, nil, fmt.Errorf("ling token soul2 (xiaoyao) requires highland")
		}
	} else {
		if cell.IsHighland {
			return nil, nil, fmt.Errorf("ling token soul1/3 requires low ground")
		}
	}

	if s.Inventory <= 0 {
		return nil, nil, fmt.Errorf("ling token inventory empty")
	}
	if *cost < s.Config.TokenCost {
		return nil, nil, fmt.Errorf("ling insufficient deployment cost: have %v, need %v", *cost, s.Config.TokenCost)
	}

	// 检查是否与既有弦惊合体
	fusionTarget := s.CheckFusionTarget(cell.Position, dir)

	// 计算部署位与场上限制
	if fusionTarget != nil {
		// 合体情况：新弦惊直接融合进入已有的 fusionTarget，不新增场上实体数量。
		// 占用部署位从 1 变为 2，因此需要消耗团队 1 个部署位
		if *availableSquadDeploySlots < 1 {
			return nil, nil, fmt.Errorf("insufficient squad deploy slots for ling fusion (needs 1 extra slot)")
		}
	} else {
		// 普通独立部署
		if s.ActiveTokenCount() >= s.Config.FieldMax {
			return nil, nil, fmt.Errorf("ling token field maximum reached: %d", s.Config.FieldMax)
		}
		if *availableSquadDeploySlots < 1 {
			return nil, nil, fmt.Errorf("insufficient squad deploy slots (needs 1)")
		}
	}

	// 扣减费用与库存
	*cost -= s.Config.TokenCost
	s.Inventory--

	if fusionTarget != nil {
		// 扣减 1 个团队部署位，fusionTarget 升级为高级形态
		*availableSquadDeploySlots -= 1
		fusionTarget.Form = LingFormFused
		fusionTarget.DeploySlots = s.Config.FusionDeploySlots // 2

		// 属性按高级形态黑板倍率提升，并回满生命值
		fusionTarget.MaxHp *= s.Config.FusionHpMult
		fusionTarget.CurrentHp = fusionTarget.MaxHp
		fusionTarget.Atk *= s.Config.FusionAtkMult
		fusionTarget.Def *= s.Config.FusionDefMult
		fusionTarget.MagicResistance *= s.Config.FusionMagicResMult
		fusionTarget.BaseAttackTime *= s.Config.FusionAtkTimeMult
		fusionTarget.BlockCnt += s.Config.FusionBlockBonus

		return fusionTarget, fusionTarget, nil
	}

	// 普通部署新实体
	*availableSquadDeploySlots -= 1
	posType := LingPosMelee
	if s.Config.Slot == 2 {
		posType = LingPosRanged
	}

	token := &LingTokenEntity{
		ID:              s.NextTokenID,
		Owner:           s.Owner,
		TokenKey:        s.Config.TokenKey,
		Cell:            cell.Position,
		Direction:       dir,
		Position:        posType,
		Form:            LingFormNormal,
		MaxHp:           s.Config.TokenMaxHp,
		CurrentHp:       s.Config.TokenMaxHp,
		Atk:             s.Config.TokenAtk,
		Def:             s.Config.TokenDef,
		MagicResistance: s.Config.TokenMagicResist,
		BlockCnt:        s.Config.TokenBlockCnt,
		BaseAttackTime:  s.Config.TokenBaseAtkTime,
		DeploySlots:     1,
		DeployTime:      now,
		Alive:           true,
	}
	s.NextTokenID++
	s.Tokens = append(s.Tokens, token)

	return token, nil, nil
}
