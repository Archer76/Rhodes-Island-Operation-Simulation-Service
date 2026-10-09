package main

import (
	"reflect"
	"testing"
)

func TestWangSelectOpeningScatterPriority(t *testing.T) {
	cands := []wangOpeningCandidate{
		{Cell: Cell{0, 0}, Deployable: true},
		{Cell: Cell{1, 0}, NonDeployGround: true},
		{Cell: Cell{2, 0}, HasEnemy: true},
		{Cell: Cell{3, 0}, NonDeployHighland: true},
		{Cell: Cell{4, 0}, HasEnemy: true},
	}
	// With count 3: should take two enemies (2,0), (4,0), and one non-deploy ground (1,0)
	got := wangSelectOpeningScatter(cands, 3)
	want := []Cell{{2, 0}, {4, 0}, {1, 0}}
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("got %v, want %v", got, want)
	}

	// With count 10: should take all 5 valid, sorted by priority then coordinates
	gotAll := wangSelectOpeningScatter(cands, 10)
	wantAll := []Cell{{2, 0}, {4, 0}, {1, 0}, {3, 0}, {0, 0}}
	if !reflect.DeepEqual(gotAll, wantAll) {
		t.Fatalf("gotAll %v, wantAll %v", gotAll, wantAll)
	}
}
