package main

import "testing"

func TestWangDOTProvisionalImmediateDiscreteTicks(t *testing.T) {
	d, err := newWangDOT(7, 10, 6.5, 900)
	if err != nil {
		t.Fatal(err)
	}
	if !d.ImmediateFirstTick {
		t.Fatal("provisional first-tick choice not visible")
	}
	if got := d.due(9.9); len(got) != 0 {
		t.Fatal("tick before application")
	}
	if got := d.due(10); len(got) != 1 || got[0] != 10 {
		t.Fatalf("immediate %v", got)
	}
	if got := d.due(10.99); len(got) != 0 {
		t.Fatal("continuous DPS approximation")
	}
	if got := d.due(16.5); len(got) != 6 || got[0] != 11 || got[5] != 16 {
		t.Fatalf("remaining %v", got)
	}
	if got := d.due(100); len(got) != 0 {
		t.Fatal("expired/duplicate tick")
	}
}
func TestWangDOTApplicationsRemainIndependent(t *testing.T) {
	a, _ := newWangDOT(7, 0, 6.5, 900)
	b, _ := newWangDOT(7, 0.5, 6.5, 700)
	if len(a.due(1)) != 2 || len(b.due(1)) != 1 || a.Damage != 900 || b.Damage != 700 {
		t.Fatal("effects overwritten or layers resampled")
	}
	b.ImmediateFirstTick = false
	b.NextTick = 0
	if len(b.due(1)) != 0 || len(b.due(1.5)) != 1 {
		t.Fatal("alternate first-tick phase cannot be verified independently")
	}
}
