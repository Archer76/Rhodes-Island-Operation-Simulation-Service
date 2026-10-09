package main

import "testing"

func TestWangDeploymentTransactionRefusesBeforeMutation(t *testing.T) {
	base := wangDeploymentState{Owner: "instance-1", Config: wangRuntimeConfig{Slot: 2, DeployMaximum: 2, DeployCost: 3, DeployCooldown: 2}, Inventory: wangInventory{Count: 3, Maximum: 7}}
	valid := wangDeploymentCell{Position: Cell{1, 1}, MapKnown: true, Deployable: true, OccupancyKnown: true}
	for _, which := range []string{"map", "occupancy", "enemy", "role", "cost", "cooldown", "max"} {
		w := base
		cell := valid
		cost := 10.
		switch which {
		case "map":
			cell.MapKnown = false
		case "occupancy":
			cell.OccupancyKnown = false
		case "enemy":
			cell.GroundEnemy = true
		case "role":
			cell.RoleOccupied = true
		case "cost":
			cost = 2
		case "cooldown":
			w.NextDeploy = 1
		case "max":
			w.Config.DeployMaximum = 0
		}
		before := cost
		if _, err := w.deployManual(0, cell, &cost); err == nil {
			t.Fatal("accepted", which)
		}
		if cost != before || w.Inventory.Count != 3 || len(w.Field.stones) != 0 {
			t.Fatal("refusal mutated", which)
		}
	}
	w := base
	cost := 10.
	if _, err := w.deployManual(0, valid, &cost); err != nil {
		t.Fatal(err)
	}
	if cost != 7 || w.Inventory.Count != 2 || w.NextDeploy != 2 || len(w.Field.stones) != 1 {
		t.Fatal("success resources", w, cost)
	}
}
func TestWangDeploymentS3OccupiedTileExceptionIsRangeBound(t *testing.T) {
	w := wangDeploymentState{Owner: "instance", Config: wangRuntimeConfig{Slot: 3, DeployMaximum: 7, DeployCost: 2}, Inventory: wangInventory{Count: 3, Maximum: 7, Ammo: 20, SkillThree: true}}
	cell := wangDeploymentCell{Position: Cell{1, 1}, MapKnown: true, Deployable: true, OccupancyKnown: true, GroundEnemy: true}
	cost := 10.
	if _, err := w.deployManual(0, cell, &cost); err == nil {
		t.Fatal("S3 exception outside range")
	}
	cell.InOwnerActiveRange = true
	if _, err := w.deployManual(0, cell, &cost); err != nil {
		t.Fatal(err)
	}
	if cost != 8 || w.Inventory.Ammo != 20 || w.Inventory.Count != 2 {
		t.Fatal("wrong S3 cost")
	}
}
