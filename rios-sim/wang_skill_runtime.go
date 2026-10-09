package main

import (
	"fmt"
	"math"
)

// Wang skill runtime is separate from ordinary attack profiles. Opening overflow
// placement still requires a supplied, validated transaction; it is not guessed.
type wangSkillRuntime struct {
	Config      wangRuntimeConfig
	Inventory   wangInventory
	SP          float64
	Activations int
}

func newWangSkillRuntime(cfg wangRuntimeConfig) (*wangSkillRuntime, error) {
	if cfg.Slot < 1 || cfg.Slot > 3 || cfg.SPCost <= 0 || cfg.SPIncrement <= 0 || cfg.InitialInventory < 0 || cfg.InventoryMaximum < cfg.InitialInventory {
		return nil, fmt.Errorf("invalid wang skill parameters")
	}
	return &wangSkillRuntime{Config: cfg, Inventory: wangInventory{Count: cfg.InitialInventory, Maximum: cfg.InventoryMaximum}, SP: cfg.InitialSP}, nil
}
func (w *wangSkillRuntime) tickSP(dt float64) error {
	if math.IsNaN(dt) || math.IsInf(dt, 0) || dt < 0 {
		return fmt.Errorf("invalid wang skill dt")
	}
	if w.Inventory.SkillThree {
		return nil
	}
	// Confirmed S1/S2 full-stock SP lock; do not extrapolate it to S3.
	if w.Config.Slot <= 2 && w.Inventory.Count >= w.Inventory.Maximum {
		return nil
	}
	w.SP = math.Min(w.Config.SPCost, w.SP+w.Config.SPIncrement*dt)
	return nil
}
func (w *wangSkillRuntime) activate() error {
	if w.Inventory.SkillThree {
		return fmt.Errorf("wang skill already active")
	}
	if w.SP < w.Config.SPCost {
		return fmt.Errorf("wang skill insufficient SP")
	}
	if w.Config.Slot <= 2 {
		if w.Inventory.Count >= w.Inventory.Maximum {
			return fmt.Errorf("wang inventory full; skill blocked")
		}
		if err := w.Inventory.replenish(w.Config.Replenish); err != nil {
			return err
		}
	} else {
		if w.Config.Ammo <= 0 {
			return fmt.Errorf("wang S3 ammo missing")
		}
		if w.Inventory.Count+w.Config.Replenish > w.Inventory.Maximum {
			return fmt.Errorf("wang S3 opening overflow placement unresolved")
		}
		w.Inventory.Count += w.Config.Replenish
		w.Inventory.Ammo = w.Config.Ammo
		w.Inventory.SkillThree = true
	}
	w.SP -= w.Config.SPCost
	w.Activations++
	return nil
}
func (w *wangSkillRuntime) stop() error {
	if w.Config.Slot != 3 || !w.Inventory.SkillThree {
		return fmt.Errorf("wang manual stop requires active S3")
	}
	w.Inventory.endSkillThree()
	return nil
}
func (w *wangSkillRuntime) canOrdinaryAttack() bool { return !w.Inventory.SkillThree }

// Boundary transaction for a whole successful manual+extra action. Unknown last
// inventory ordering refuses before any resource change, rather than returning
// ammo early and then spawning free extras outside S3.
func (w *wangInventory) commitPlacementBatch(manual bool, extras int) error {
	if extras < 0 || extras > 4 {
		return fmt.Errorf("invalid wang extra generation count")
	}
	if !w.SkillThree {
		if extras > 1 {
			return fmt.Errorf("extra skill stones require active S3")
		}
		if manual {
			return w.commitManualPlacement(true)
		}
		return nil
	}
	// First extra is the free talent stone; extras 2..4 consume ammo only.
    total:=extras-1; if total<0 {total=0}
    if manual && w.Count<=0 {return fmt.Errorf("wang inventory empty")}
	if total > w.Ammo {
		return fmt.Errorf("wang batch exceeds ammo; partial generation order unresolved")
	}
	if manual && w.Count == 1 && extras > 0 {
		return fmt.Errorf("wang final inventory batch end ordering unresolved")
	}
	if manual {
		w.Count--
	}
	w.Ammo -= total
	if w.Ammo == 0 || w.Count == 0 {
		w.endSkillThree()
	}
	return nil
}
