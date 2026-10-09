package main

import "testing"

func TestWangInventoryActualGenerationAndEndCap(t *testing.T) {
	w := wangInventory{Count: 5, Maximum: 7, Ammo: 20, SkillThree: true}
	w.commitManualPlacement(false)
	w.commitExtraPlacement(false)
	if w.Count != 5 || w.Ammo != 20 {
		t.Fatal("failed placement consumed resources")
	}
	w.commitManualPlacement(true)
	w.commitExtraPlacement(true)
	if w.Count != 4 || w.Ammo != 18 {
		t.Fatalf("actual placement count %+v", w)
	}
	w.endSkillThree()
	if w.Count != 7 || w.Ammo != 0 || w.SkillThree {
		t.Fatalf("return cap %+v", w)
	}
	w.endSkillThree()
	if w.Count != 7 {
		t.Fatal("return applied twice")
	}
}
func TestWangInventoryEmptyAndAmmoZeroEnd(t *testing.T) {
	w := wangInventory{Count: 1, Maximum: 7, Ammo: 10, SkillThree: true}
	if err := w.commitManualPlacement(true); err != nil {
		t.Fatal(err)
	}
	if w.SkillThree || w.Ammo != 0 || w.Count != 7 {
		t.Fatalf("inventory zero did not return capped ammo %+v", w)
	}
	w = wangInventory{Count: 5, Maximum: 7, Ammo: 1, SkillThree: true}
	w.commitExtraPlacement(true)
	if w.SkillThree || w.Ammo != 0 || w.Count != 5 {
		t.Fatalf("ammo zero %+v", w)
	}
	w = wangInventory{Maximum: 7}
	if err := w.commitManualPlacement(true); err == nil {
		t.Fatal("empty inventory accepted")
	}
}
