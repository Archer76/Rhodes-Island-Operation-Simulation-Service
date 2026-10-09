package main

import (
	"fmt"
	"math"
)

// Explicit deployment transaction. Map and effective ground-enemy occupancy are
// supplied by the runtime; absent evidence is not treated as an empty cell.
type wangDeploymentState struct {
	Owner      string
	Config     wangRuntimeConfig
	Inventory  wangInventory
	Field      wangStoneField
	NextDeploy float64
}
type wangDeploymentCell struct {
	Position           Cell
	MapKnown           bool
	Deployable         bool
	OccupancyKnown     bool
	GroundEnemy        bool
	RoleOccupied       bool
	InOwnerActiveRange bool
}

func (w *wangDeploymentState) deployManual(now float64, cell wangDeploymentCell, cost *float64) (uint64, error) {
	if w.Owner == "" || cost == nil || math.IsNaN(now) || math.IsInf(now, 0) || now < 0 {
		return 0, fmt.Errorf("invalid wang deployment identity/time/cost")
	}
	if !cell.MapKnown || !cell.OccupancyKnown {
		return 0, fmt.Errorf("wang map or occupancy source missing")
	}
	if !cell.Deployable || cell.RoleOccupied {
		return 0, fmt.Errorf("wang manual landing not deployable")
	}
	if cell.GroundEnemy && !(w.Inventory.SkillThree && cell.InOwnerActiveRange) {
		return 0, fmt.Errorf("wang trap placement forbids occupied enemy tile")
	}
	if now < w.NextDeploy {
		return 0, fmt.Errorf("wang token deployment cooldown")
	}
	if w.Inventory.Count <= 0 {
		return 0, fmt.Errorf("wang inventory empty")
	}
	if w.Inventory.SkillThree && w.Inventory.Ammo <= 0 {
		return 0, fmt.Errorf("wang ammo empty")
	}
	if math.IsNaN(*cost) || math.IsInf(*cost, 0) || *cost < w.Config.DeployCost {
		return 0, fmt.Errorf("wang insufficient deployment cost")
	}
	deployed := 0
	for _, s := range w.Field.stones {
		if s.Owner == w.Owner && !s.Projectile {
			deployed++
		}
	}
	if deployed >= w.Config.DeployMaximum {
		return 0, fmt.Errorf("wang token deployment maximum")
	}
	id, err := w.Field.add(w.Owner, cell.Position, false, w.Config.Slot)
	if err != nil {
		return 0, err
	}
	// All refusals occur before the transaction; only success changes resources.
	if err := w.Inventory.commitManualPlacement(true); err != nil {
		w.Field.remove(id)
		w.Field.refresh(w.Owner, w.Config.Slot)
		return 0, err
	}
	*cost -= w.Config.DeployCost
	w.NextDeploy = now + w.Config.DeployCooldown
	return id, nil
}
