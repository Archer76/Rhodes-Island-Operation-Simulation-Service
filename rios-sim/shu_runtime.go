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

// ShuTeleportAnchor 是敌人身上「播种标记」记录的地块。
//
// 按 PRTS 整页取证（revision 442689）：标记记录的是**当前所在地块**，
// 已有标记不会重复施加；传送时回到**记录地块的中心**，而且
// 「不重置该敌人已经过的路径点」。所以这里只留地块坐标——
// 旧实现保存 legIndex/legU/position/progress 四元组并在传送时整体恢复，
// 那等于把敌人的路径进度倒回去，与证据相反。
type ShuTeleportAnchor struct {
	AnchorCell [2]int
}

// ShuBattleState 是黍在主战斗循环里的全部动态状态。
type ShuBattleState struct {
	Config *ShuRuntimeConfig

	// 播种地块集合（键：格坐标）。
	SownTiles map[[2]int]*SownTile

	// 技能3 的播种标记（键：敌人 index）。标记**不会**在传送后清除，
	// 只有敌人消失（阵亡/漏出/离场）时清。
	TeleportAnchors map[int]*ShuTeleportAnchor

	// 上一帧敌人所在格（键：敌人 index）。触发时机是「每次进入地块时」，
	// 所以必须知道这一帧是不是刚换格——逐帧按距离扫是旧实现，与证据不符。
	LastCells map[int][2]int

	// 技能3 期间被黍作为主目标治疗过的地块。PRTS 备注：第一天赋无法播种的
	// 地块，若其周围四格上部署的我方干员被黍作为主目标治疗过，该地块也可
	// 正常检查并施加播种标记。该集合记录「被治疗过的格」，可行性过滤在
	// B 批（播种限制）接入后再收紧。
	S3HealedTiles map[[2]int]bool

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
		LastCells:       make(map[int][2]int),
		S3HealedTiles:   make(map[[2]int]bool),
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

// clearSown 清空全部播种效果。PRTS 天赋备注：「本天赋效果为永久地块
// 效果，**自身退场时清空所有地块的播种效果**」。
func (s *ShuBattleState) clearSown() {
	s.SownTiles = make(map[[2]int]*SownTile)
	// 播种标记的判定依赖地块存在性与「被治疗过的格」集合，退场后一并失效。
	s.TeleportAnchors = make(map[int]*ShuTeleportAnchor)
	s.S3HealedTiles = make(map[[2]int]bool)
}

func (s *ShuBattleState) isSown(cell [2]int) bool {
	_, ok := s.SownTiles[cell]
	return ok
}

// markable 回答「这一格是否可检查播种标记」：本身是播种格，或技能三期间
// 被黍作为主目标治疗过（PRTS 备注的补播种规则）。
func (s *ShuBattleState) markable(cell [2]int) bool {
	if _, ok := s.SownTiles[cell]; ok {
		return true
	}
	return s.S3HealedTiles[cell]
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

// manhattan 是 PRTS 明写的距离口径：∣行差∣+∣列差∣。
//
// 旧实现用切比雪夫（八方向格数），会把斜向 2 格的站位算成"2 格"；
// 曼哈顿口径下同一站位是 4 格，两者在阈值上结论相反。
func manhattan(a, b [2]int) int {
	dx := a[0] - b[0]
	dy := a[1] - b[1]
	if dx < 0 {
		dx = -dx
	}
	if dy < 0 {
		dy = -dy
	}
	return dx + dy
}

// anchorOnEnter 在敌人**进入一个可标记地块**时施加播种标记。
//
// 三条判据（PRTS）：① 已有【播种标记】不会重复施加；② 免疫传送(黍) 的
// 敌人不会被施加标记；③ 标记只看地块，不看敌人是否可被选中（不受隐匿、
// 无敌影响）——所以这里不调用任何选择器。
func (s *ShuBattleState) anchorOnEnter(e *enemy, cell [2]int) {
	if e.spec.Immunities["teleportImmune"] {
		return
	}
	if _, ok := s.TeleportAnchors[e.index]; ok {
		return
	}
	if !s.markable(cell) {
		return
	}
	s.TeleportAnchors[e.index] = &ShuTeleportAnchor{AnchorCell: cell}
}

// shouldTeleportOnEnter 判定「这一帧刚进入的格」与记录地块的曼哈顿距离是否
// 超过标注距离（游戏原文是「超过」，严格大于；PRTS 的「达到」只作分歧记录）。
//
// 触发时机是**每次进入地块时**，不是逐帧按距离扫：调用方只在 entered 为真时
// 调用本函数。
func (s *ShuBattleState) shouldTeleportOnEnter(e *enemy, enteredCell [2]int) (*ShuTeleportAnchor, bool) {
	a, ok := s.TeleportAnchors[e.index]
	if !ok {
		return nil, false
	}
	if manhattan(enteredCell, a.AnchorCell) <= int(s.Config.S3MaxDistance) {
		return nil, false
	}
	// 「最终传送处理对持有被传送/放逐的敌人无效」：引擎目前没有这两类
	// 异常状态的字段（只有 teleportImmune），无法判定；登记在机制缺口里。
	return a, true
}

// teleportToAnchor 把敌人送回记录地块的**中心**，且**不重置已经过的路径点**。
//
// 只改 position：legIndex/legU/progress 全部保留，所以敌人的速度、下一段
// 走向与索敌顺序都不被打断（PRTS：「不打断当前速度，不会重置该敌人已经过
// 的路径点」）。标记保留，可再次触发。
func (s *ShuBattleState) teleportToAnchor(e *enemy, a *ShuTeleportAnchor) {
	e.position = [2]float64{float64(a.AnchorCell[0]), float64(a.AnchorCell[1])}
}

// markS3Healed 记录「技能三期间被黍作为主目标治疗过」的格与四邻。
//
// PRTS 备注：第一天赋无法播种的地块，若该地块及其周围四格上部署的我方
// 干员被黍作为主目标治疗过，则此地块也可正常检查并施加【播种标记】。
// 可行性过滤（哪些地块原本不可播种）依赖 B 批的播种限制，这里先记集合。
func (s *ShuBattleState) markS3Healed(center [2]int) {
	for _, d := range [][2]int{{0, 0}, {1, 0}, {-1, 0}, {0, 1}, {0, -1}} {
		s.S3HealedTiles[[2]int{center[0] + d[0], center[1] + d[1]}] = true
	}
}

// sownProtect 是这名干员这一刻从「播种地块」拿到的庇护（取所有在场地块里
// 最强的一份）。
//
// PRTS 天赋备注：「自身退场时清空所有地块的播种效果」——所以施加者必须
// 活着；`shuTick` 退场时会清表，这里是同一口径的第二道闸（部署瞬间或
// 调用顺序变化时不会漏）。
func (o *operator) sownProtect() float64 {
	if o.sim == nil || o.sim.objs == nil {
		return 0
	}
	best := 0.0
	cell := cellOf(o.cell)
	for _, other := range *o.sim.objs {
		if other.spec.CharID != shuCharID || other.shuState == nil || !other.alive() {
			continue
		}
		if p := other.shuState.protectAt(cell); p > best {
			best = p
		}
	}
	return best
}
