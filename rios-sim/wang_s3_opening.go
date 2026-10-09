package main

import "sort"

// Opening deployment candidate for S3:
// Prioritizes: Enemy-occupied > Non-deployable ground > Non-deployable highland > Deployable
type wangOpeningCandidate struct {
	Cell               Cell
	HasEnemy           bool
	NonDeployGround    bool
	NonDeployHighland  bool
	Deployable         bool
}

func (c wangOpeningCandidate) Priority() int {
	if c.HasEnemy {
		return 0
	}
	if c.NonDeployGround {
		return 1
	}
	if c.NonDeployHighland {
		return 2
	}
	if c.Deployable {
		return 3
	}
	return 4
}

// Select S3 opening scatter cells. Discards any stones that cannot be placed.
func wangSelectOpeningScatter(candidates []wangOpeningCandidate, count int) []Cell {
	valid := make([]wangOpeningCandidate, 0, len(candidates))
	for _, c := range candidates {
		if c.Priority() <= 3 {
			valid = append(valid, c)
		}
	}
	sort.SliceStable(valid, func(i, j int) bool {
		pi, pj := valid[i].Priority(), valid[j].Priority()
		if pi != pj {
			return pi < pj
		}
		// Tie-breaking by coordinate order
		if valid[i].Cell[1] != valid[j].Cell[1] {
			return valid[i].Cell[1] < valid[j].Cell[1]
		}
		return valid[i].Cell[0] < valid[j].Cell[0]
	})

	if len(valid) > count {
		valid = valid[:count]
	}
	res := make([]Cell, len(valid))
	for i, v := range valid {
		res[i] = v.Cell
	}
	return res
}
