package main

import (
	"fmt"
)

// RadianDirection 朝向定义
type RadianDirection string

const (
	RadianDirRight RadianDirection = "Right"
	RadianDirLeft  RadianDirection = "Left"
	RadianDirUp    RadianDirection = "Up"
	RadianDirDown  RadianDirection = "Down"
)

// RadianPosition 站位类型
type RadianPosition string

const (
	RadianPosMelee  RadianPosition = "MELEE"
	RadianPosRanged RadianPosition = "RANGED"
)

// RadianTokenEntity 代表电弧召唤的一个具体在场实体（戴乌 / 鳞地 / 棱镜塔）
type RadianTokenEntity struct {
	ID        uint64
	Owner     string          // 干员实例 ID
	TokenKey  string          // token_10051_radian_tower1 / 2 / 3
	Name      string          // 戴乌 / 鳞地 / 棱镜塔
	Cell      Cell            // 所在坐标 [2]int{x, y}
	Direction RadianDirection // 朝向
	Position  RadianPosition  // MELEE 或 RANGED

	// 战斗属性与状态
	MaxHp           float64
	CurrentHp       float64
	BarrierHp       float64 // 技能一屏障/护盾
	Atk             float64
	Def             float64
	MagicResistance float64
	BlockCnt        int
	BaseAttackTime  float64
	AttackTimer     float64

	// 部署占位与生命周期
	DeploySlots int     // 占据部署位数（1）
	DeployTime  float64 // 部署时刻
	Alive       bool
}

// RadianDeploymentCell 描述部署格子的环境信息
type RadianDeploymentCell struct {
	Position       Cell
	MapKnown       bool
	Deployable     bool
	OccupancyKnown bool
	RoleOccupied   bool
	IsHighland     bool // 高台还是地面
}

// RadianDeploymentState 维护电弧干员的召唤物库存、场上实体列表与部署约束
type RadianDeploymentState struct {
	Owner       string
	Config      radianRuntimeConfig
	Inventory   int                  // 当前持有召唤物数量
	Tokens      []*RadianTokenEntity // 场上所有已部署实体
	NextDeploy  float64              // 部署公共 CD
	NextTokenID uint64
}

func newRadianDeploymentState(owner string, cfg radianRuntimeConfig) RadianDeploymentState {
	return RadianDeploymentState{
		Owner:       owner,
		Config:      cfg,
		Inventory:   cfg.InventoryMax,
		Tokens:      make([]*RadianTokenEntity, 0, cfg.FieldMax),
		NextTokenID: 1,
	}
}

// ActiveTokens 返回场上存活的所有召唤物
func (s *RadianDeploymentState) ActiveTokens() []*RadianTokenEntity {
	var active []*RadianTokenEntity
	for _, t := range s.Tokens {
		if t.Alive {
			active = append(active, t)
		}
	}
	return active
}

// CheckDeployable 校验指定地块是否可放置电弧召唤物
func (s *RadianDeploymentState) CheckDeployable(cell RadianDeploymentCell) error {
	if !cell.MapKnown {
		return fmt.Errorf("cell %v is not on map", cell.Position)
	}
	if !cell.Deployable {
		return fmt.Errorf("cell %v is not deployable tile", cell.Position)
	}
	if !cell.OccupancyKnown {
		return fmt.Errorf("cell %v occupancy unknown", cell.Position)
	}
	if cell.RoleOccupied {
		return fmt.Errorf("cell %v is already occupied", cell.Position)
	}

	// 高台/地面限制：戴乌/鳞地 (S1/S2) 必须放近战位（地面），棱镜塔 (S3) 必须放远程位（高台）
	switch s.Config.Slot {
	case 1, 2:
		if cell.IsHighland {
			return fmt.Errorf("radian token %s requires melee ground tile", s.Config.TokenKey)
		}
	case 3:
		if !cell.IsHighland {
			return fmt.Errorf("radian token %s requires ranged highland tile", s.Config.TokenKey)
		}
	}
	return nil
}

// DeployToken 执行部署召唤物
func (s *RadianDeploymentState) DeployToken(now float64, cell RadianDeploymentCell, dir RadianDirection, availableSquadDeploySlots *int) (*RadianTokenEntity, error) {
	if now < s.NextDeploy {
		return nil, fmt.Errorf("deploy cooldown active until %.2f", s.NextDeploy)
	}
	if s.Inventory <= 0 {
		return nil, fmt.Errorf("no radian tokens remaining in inventory")
	}
	active := s.ActiveTokens()
	if len(active) >= s.Config.FieldMax {
		return nil, fmt.Errorf("max active radian tokens reached (%d)", s.Config.FieldMax)
	}
	if availableSquadDeploySlots != nil && *availableSquadDeploySlots < 1 {
		return nil, fmt.Errorf("insufficient squad deployment slots")
	}

	if err := s.CheckDeployable(cell); err != nil {
		return nil, err
	}

	pos := RadianPosMelee
	name := "戴乌"
	if s.Config.Slot == 2 {
		name = "鳞地"
	} else if s.Config.Slot == 3 {
		pos = RadianPosRanged
		name = "棱镜塔"
	}

	// 基础属性计入第二天赋【加油~】（若已解锁）
	maxHp := s.Config.TokenMaxHp * (1.0 + s.Config.Talent2HpRatio)
	atk := s.Config.TokenAtk * (1.0 + s.Config.Talent2AtkRatio)
	def := s.Config.TokenDef * (1.0 + s.Config.Talent2DefRatio)

	token := &RadianTokenEntity{
		ID:              s.NextTokenID,
		Owner:           s.Owner,
		TokenKey:        s.Config.TokenKey,
		Name:            name,
		Cell:            cell.Position,
		Direction:       dir,
		Position:        pos,
		MaxHp:           maxHp,
		CurrentHp:       maxHp,
		Atk:             atk,
		Def:             def,
		MagicResistance: s.Config.TokenMagicResist,
		BlockCnt:        s.Config.TokenBlockCnt,
		BaseAttackTime:  s.Config.TokenBaseAtkTime,
		DeploySlots:     1,
		DeployTime:      now,
		Alive:           true,
	}
	s.NextTokenID++
	s.Inventory--
	s.Tokens = append(s.Tokens, token)

	if availableSquadDeploySlots != nil {
		*availableSquadDeploySlots--
	}
	return token, nil
}
