package main

import "math"

// SownTile 是一块被播种的地块。
//
// 数值在**播种那一刻**从施加者的配置快照进来：模组会改写「百谷长青」的
// 回血与庇护值，用施加时的值而不是每帧回查，才能保证「先播的地用旧值、
// 后播的地用新值」与技能2 的 ×倍率各算各的。
type SownTile struct {
	Cell     [2]int
	Sower    string
	Recovery float64
	Protect  float64
}

// ShuTeleportAnchor 是敌人经过播种地块那一刻的**完整路线快照**。
//
// 传送要「回到该地块」，只记格心是不够的：敌人的位置由
// `legIndex/legU/position/progress` 四个量共同决定，而 `progress` 还是
// 索敌排序键。半截状态会让敌人在传送后"站在地块上、progress 却还在远处"，
// 表现为它继续按原来的顺序挨打、或者走向错误的分段。
type ShuTeleportAnchor struct {
	AnchorCell [2]int
	LegIndex   int
	LegU       float64
	Position   [2]float64
	Progress   float64
}

// ShuBattleState 是黍在主战斗循环里的全部动态状态。
type ShuBattleState struct {
	Config *ShuRuntimeConfig

	// 播种地块集合（键：格坐标）。
	SownTiles map[[2]int]*SownTile

	// 技能3 的传送锚点（键：敌人 index）。
	TeleportAnchors map[int]*ShuTeleportAnchor

	// 技能1「化被草木」当前充能层数（每次开技 +1，攻击治疗时 -1）。
	Charges int

	// 技能2 的治疗节奏（与普攻计时分开：它的间隔是技能给的 base_attack_time）。
	S2Timer float64

	// 天赋二「天有四时」：编队里的【岁】干员数在开局算一次。
	SeasonSuiCount int

	// 天赋二每 4 秒发 1 点技力。
	SeasonSPTimer float64
}

func newShuBattleState(cfg *ShuRuntimeConfig) *ShuBattleState {
	return &ShuBattleState{
		Config:          cfg,
		SownTiles:       make(map[[2]int]*SownTile),
		TeleportAnchors: make(map[int]*ShuTeleportAnchor),
	}
}

// sow 对单个地块播种；同一格重复播种**不叠加**，取更强的效果（回血与
// 庇护分别取大）。天赋原文只说"播种施加如下效果"，没有任何叠加说明。
func (s *ShuBattleState) sow(cell [2]int, sower string, recovery, protect float64) bool {
	if t, ok := s.SownTiles[cell]; ok {
		if recovery > t.Recovery {
			t.Recovery = recovery
		}
		if protect > t.Protect {
			t.Protect = protect
		}
		return false
	}
	s.SownTiles[cell] = &SownTile{Cell: cell, Sower: sower, Recovery: recovery, Protect: protect}
	return true
}

// sowAround 播种**中心格与其上下左右四格**（天赋一原文：「对其与周围四格地块」）。
func (s *ShuBattleState) sowAround(center [2]int, sower string) int {
	cfg := s.Config
	added := 0
	for _, d := range [][2]int{{0, 0}, {1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
		if s.sow([2]int{center[0] + d[0], center[1] + d[1]}, sower, cfg.SowRecoveryPerSec, cfg.SowProtect) {
			added++
		}
	}
	return added
}

// sowSelf 只播自身所处的那一格（模组三级的「部署时立即给所处地块播种该效果」）。
// `0-1` 范围在 range_table 里就是单格 `(0,0)`——不是四邻。
func (s *ShuBattleState) sowSelf(cell [2]int, sower string) bool {
	return s.sow(cell, sower, s.Config.SowRecoveryPerSec, s.Config.SowProtect)
}

func (s *ShuBattleState) isSown(cell [2]int) bool {
	_, ok := s.SownTiles[cell]
	return ok
}

// protectAt 是站在该格的友方拿到的庇护（伤害减免比例）。没播种就是 0。
func (s *ShuBattleState) protectAt(cell [2]int) float64 {
	if t, ok := s.SownTiles[cell]; ok {
		return t.Protect
	}
	return 0
}

// cellOf 把浮点位置落在格子上。与引擎其余部分同一口径：四舍五入到整数格。
func cellOf(pos [2]float64) [2]int {
	return [2]int{int(math.RoundToEven(pos[0])), int(math.RoundToEven(pos[1]))}
}

// anchorIfSown 在敌人**站在**播种地块上时记下锚点。
// 同一名敌人至多一个锚点（`e_max_stack_cnt = 1`）：已有锚点时不覆盖。
func (s *ShuBattleState) anchorIfSown(e *enemy, cell [2]int) {
	if _, ok := s.TeleportAnchors[e.index]; ok {
		return
	}
	s.TeleportAnchors[e.index] = &ShuTeleportAnchor{
		AnchorCell: cell,
		LegIndex:   e.legIndex,
		LegU:       e.legU,
		Position:   e.position,
		Progress:   e.progress,
	}
}

// shouldTeleport 判断敌人是否远离锚点地块超过 max_distance 格。
//
// 距离口径：格子距离用**八方向格数**（切比雪夫距离）——"远离该地块 N 格"
// 在游戏里是格子计数，不是欧氏长度。该口径与"传送后是否可再触发"一起
// 登记为待证（`Unresolved`），不写成"已确认"。
func (s *ShuBattleState) shouldTeleport(e *enemy) (*ShuTeleportAnchor, bool) {
	a, ok := s.TeleportAnchors[e.index]
	if !ok {
		return nil, false
	}
	// 引擎的敌人位置与干员落点都以**整数格心**表示（`cellOf` 直接四舍五入），
	// 所以距离直接按格坐标差算，不要加 0.5 变成"格角"。
	cx := float64(a.AnchorCell[0])
	cy := float64(a.AnchorCell[1])
	dx := math.Abs(e.position[0] - cx)
	dy := math.Abs(e.position[1] - cy)
	if math.Max(dx, dy) <= s.Config.S3MaxDistance {
		return nil, false
	}
	return a, true
}

// restore 把敌人送回锚点快照，并消耗锚点（可再次经过地块重新获得）。
func (s *ShuBattleState) restore(e *enemy, a *ShuTeleportAnchor) {
	e.legIndex = a.LegIndex
	e.legU = a.LegU
	e.position = a.Position
	e.progress = a.Progress
	delete(s.TeleportAnchors, e.index)
}

// sownProtect 是这名干员这一刻从「播种地块」拿到的庇护（取所有在场地块里
// 最强的一份）。它判的是**地块**，不是施加者：黍撤退后地块效果仍在。
//
// 多块重叠时取最大而不是相加：天赋只写「获得 N% 庇护」，没有叠加说明。
func (o *operator) sownProtect() float64 {
	if o.sim == nil || o.sim.objs == nil {
		return 0
	}
	best := 0.0
	cell := cellOf(o.cell)
	for _, other := range *o.sim.objs {
		if other.spec.CharID != shuCharID || other.shuState == nil {
			continue
		}
		if p := other.shuState.protectAt(cell); p > best {
			best = p
		}
	}
	return best
}
