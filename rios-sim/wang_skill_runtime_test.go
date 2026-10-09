package main

import "testing"

func TestWangSkillStockLockAndReplenishment(t *testing.T) {
	cfg := wangRuntimeConfig{Slot: 1, SPCost: 16, SPIncrement: 1, InitialInventory: 6, InventoryMaximum: 7, Replenish: 2}
	w, err := newWangSkillRuntime(cfg)
	if err != nil {
		t.Fatal(err)
	}
	w.tickSP(16)
	if err = w.activate(); err != nil {
		t.Fatal(err)
	}
	if w.Inventory.Count != 7 || w.SP != 0 || w.Activations != 1 {
		t.Fatal(w)
	}
	w.tickSP(100)
	if w.SP != 0 {
		t.Fatal("full stock does not block SP")
	}
	w.Inventory.Count = 5
	w.tickSP(16)
	if err = w.activate(); err != nil || w.Inventory.Count != 7 {
		t.Fatal(w, err)
	}
	if err = w.stop(); err == nil {
		t.Fatal("instant stock skill manually stopped")
	}
}
func TestWangSkillS3ActiveStopAndOpeningRefusal(t *testing.T) {
	cfg := wangRuntimeConfig{Slot: 3, SPCost: 50, SPIncrement: 1, InitialInventory: 1, InventoryMaximum: 10, Replenish: 8, Ammo: 20}
	w, _ := newWangSkillRuntime(cfg)
	w.tickSP(50)
	if err := w.activate(); err != nil {
		t.Fatal(err)
	}
	w.tickSP(10)
	if w.SP != 0 || w.canOrdinaryAttack() {
		t.Fatal("active S3 attack/SP")
	}
	if err := w.stop(); err != nil || w.Inventory.Count != 10 || w.Inventory.Ammo != 0 || !w.canOrdinaryAttack() {
		t.Fatal(w, err)
	}
	w.Inventory.Count = 6
	w.SP = 50
	before := w.Inventory
	if err := w.activate(); err == nil || w.Inventory != before || w.SP != 50 {
		t.Fatal("unresolved overflow mutated")
	}
}
func TestWangBatchEndNeverSpawnsFreeExtras(t *testing.T) {
	w := wangInventory{Count: 3, Maximum: 7, Ammo: 3, SkillThree: true}
	if err := w.commitPlacementBatch(true, 4); err != nil {
		t.Fatal(err)
	}
	if w.SkillThree || w.Ammo != 0 || w.Count != 2 {
		t.Fatal("ammo zero batch", w)
	}
	w = wangInventory{Count: 1, Maximum: 7, Ammo: 10, SkillThree: true}
	before := w
	if err := w.commitPlacementBatch(true, 4); err == nil || w != before {
		t.Fatal("unknown last inventory order silently guessed")
	}
	w = wangInventory{Count: 3, Maximum: 7, Ammo: 2, SkillThree: true}
	before = w
	if err := w.commitPlacementBatch(true, 4); err == nil || w != before {
		t.Fatal("partial ammo ordering silently guessed")
	}
}
