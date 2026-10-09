package main

import "fmt"

// Transaction helper, separate from SP/runtime frame ordering. Caller must
// validate the map and entity limits before committing placement.
type wangInventory struct {
	Count      int
	Maximum    int
	Ammo       int
	SkillThree bool
}

func (w *wangInventory) replenish(n int) error {
	if n < 0 || w.Maximum < 0 || w.Count < 0 || w.Count > w.Maximum {
		return fmt.Errorf("invalid wang inventory")
	}
	w.Count += n
	if w.Count > w.Maximum {
		w.Count = w.Maximum
	}
	return nil
}
func (w *wangInventory) endSkillThree() {
	if !w.SkillThree {
		return
	}
	w.Count += w.Ammo
	if w.Count > w.Maximum {
		w.Count = w.Maximum
	}
	w.Ammo = 0
	w.SkillThree = false
}
func (w *wangInventory) commitManualPlacement(success bool) error {
	if !success {
		return nil
	}
	if w.Count <= 0 {
		return fmt.Errorf("wang inventory empty")
	}
	if w.SkillThree && w.Ammo <= 0 {
		return fmt.Errorf("wang ammo empty")
	}
	w.Count--
	if w.SkillThree {
		// Manual stone consumes inventory only (Doctor corrected 2026-10-09).
		if w.Count == 0 || w.Ammo == 0 {
			w.endSkillThree()
		}
	}
	return nil
}

// Skill-three extras: only actual successful generation consumes ammunition.
// The base talent projectile alone is not S3 ammo consumption outside S3.
func (w *wangInventory) commitExtraPlacement(success bool) error {
	if !success {
		return nil
	}
	if !w.SkillThree {
		return nil
	}
	if w.Ammo <= 0 {
		return fmt.Errorf("wang ammo empty")
	}
	w.Ammo--
	if w.Ammo == 0 {
		w.endSkillThree()
	}
	return nil
}
