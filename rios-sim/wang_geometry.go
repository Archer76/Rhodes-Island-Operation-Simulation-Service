package main

// Wang geometry is independent of operator targeting. Rules confirmed by the
// Doctor on 2026-10-08: orthogonal adjacent connections only; S2 +/-3 along
// activated axes; S3 Manhattan radius 2. Geometry alone is not a battle consumer.

type wangAxes uint8

const (
	wangHorizontal wangAxes = 1 << iota
	wangVertical
)

func wangAdjacentAxes(a, b Cell) wangAxes {
	dx, dy := a[0]-b[0], a[1]-b[1]
	if dy == 0 && (dx == 1 || dx == -1) {
		return wangHorizontal
	}
	if dx == 0 && (dy == 1 || dy == -1) {
		return wangVertical
	}
	return 0
}

// Axis activation persists for S2 even after its connecting counterpart is
// removed (PRTS Wang skill notes). The caller owns lifetime/reset semantics.
func wangActivateAxes(origin Cell, peers []Cell, previous wangAxes) wangAxes {
	axes := previous
	for _, c := range peers {
		axes |= wangAdjacentAxes(origin, c)
	}
	return axes
}

func wangDamageCells(origin Cell, slot int, axes wangAxes) []Cell {
	switch slot {
	case 1:
		return []Cell{origin}
	case 2:
		cells := []Cell{origin}
		for d := -3; d <= 3; d++ {
			if d == 0 {
				continue
			}
			if axes&wangHorizontal != 0 {
				cells = append(cells, Cell{origin[0] + d, origin[1]})
			}
			if axes&wangVertical != 0 {
				cells = append(cells, Cell{origin[0], origin[1] + d})
			}
		}
		return cells
	case 3:
		var cells []Cell
		for dy := -2; dy <= 2; dy++ {
			for dx := -2; dx <= 2; dx++ {
				ax, ay := dx, dy
				if ax < 0 {
					ax = -ax
				}
				if ay < 0 {
					ay = -ay
				}
				if ax+ay <= 2 {
					cells = append(cells, Cell{origin[0] + dx, origin[1] + dy})
				}
			}
		}
		return cells
	}
	return nil
}

// Count only contiguous straight lines; never flood-fill an L-shaped component.
// The origin is included once per line. Both lengths are returned because the
// cross-axis talent combination still requires an explicit rule, not a guess.
func wangStraightLineCounts(origin Cell, peers []Cell) (horizontal, vertical int) {
	occupied := make(map[Cell]bool, len(peers)+1)
	occupied[origin] = true
	for _, c := range peers {
		occupied[c] = true
	}
	horizontal, vertical = 1, 1
	for _, sign := range []int{-1, 1} {
		for d := 1; occupied[Cell{origin[0] + sign*d, origin[1]}]; d++ {
			horizontal++
		}
		for d := 1; occupied[Cell{origin[0], origin[1] + sign*d}]; d++ {
			vertical++
		}
	}
	return
}

// Extra stones are projectiles, not trap entities. This selects the first valid
// adjacent landing cell, with enemy presence, terrain class, then U/R/D/L ties.
// Missing map or enemy qualification data must be refused by the caller.
type wangLandingCandidate struct {
	Cell        Cell
	Valid       bool
	GroundEnemy bool
	Terrain     int
}

func wangChooseExtraLanding(origin Cell, candidates []wangLandingCandidate) (Cell, bool) {
	directions := []Cell{{origin[0], origin[1] - 1}, {origin[0] + 1, origin[1]}, {origin[0], origin[1] + 1}, {origin[0] - 1, origin[1]}}
	bestRank := 100
	var best Cell
	found := false
	for _, pos := range directions {
		for _, c := range candidates {
			if !c.Valid || c.Cell != pos || c.Terrain < 0 || c.Terrain > 2 {
				continue
			}
			rank := c.Terrain
			if !c.GroundEnemy {
				rank += 3
			}
			if rank < bestRank {
				bestRank, best, found = rank, pos, true
			}
		}
	}
	return best, found
}
