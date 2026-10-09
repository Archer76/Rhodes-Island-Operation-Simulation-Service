package main

import "testing"

func TestWangAdjacencyRequiresOrthogonalContact(t *testing.T) {
	origin := Cell{5, 5}
	for _, c := range []struct {
		p    Cell
		want wangAxes
	}{{Cell{6, 5}, wangHorizontal}, {Cell{5, 4}, wangVertical}, {Cell{6, 6}, 0}, {Cell{7, 5}, 0}, {origin, 0}} {
		if got := wangAdjacentAxes(origin, c.p); got != c.want {
			t.Errorf("%v: got %v want %v", c.p, got, c.want)
		}
	}
}
func TestWangSkillGeometryDoctorRuling(t *testing.T) {
	origin := Cell{5, 5}
	for _, c := range []struct {
		slot  int
		axes  wangAxes
		count int
	}{{1, 0, 1}, {2, wangHorizontal, 7}, {2, wangVertical, 7}, {2, wangHorizontal | wangVertical, 13}, {3, 0, 13}} {
		cells := wangDamageCells(origin, c.slot, c.axes)
		seen := map[Cell]bool{}
		for _, p := range cells {
			if seen[p] {
				t.Errorf("duplicate %v", p)
			}
			seen[p] = true
		}
		if len(cells) != c.count {
			t.Errorf("slot%d axes%d got %d want%d", c.slot, c.axes, len(cells), c.count)
		}
		if c.slot == 3 {
			if !seen[Cell{6, 6}] || seen[Cell{7, 7}] || seen[Cell{8, 5}] {
				t.Error("S3 must be 13-cell diamond, not 9-cell cross or 7-wide axes")
			}
		}
	}
}
func TestWangAxesPersistAndStraightLinesDoNotTurn(t *testing.T) {
	origin := Cell{5, 5}
	axes := wangActivateAxes(origin, []Cell{{6, 5}, {5, 4}}, 0)
	if axes != wangHorizontal|wangVertical || wangActivateAxes(origin, nil, axes) != axes {
		t.Fatal("activated directions lost")
	}
	h, v := wangStraightLineCounts(origin, []Cell{{6, 5}, {7, 5}, {7, 6}, {5, 4}, {5, 2}})
	if h != 3 || v != 2 {
		t.Fatalf("contiguous straight counts got%d/%d want3/2", h, v)
	}
}
func TestWangExtraLandingPriority(t *testing.T) {
	origin := Cell{5, 5}
	candidates := []wangLandingCandidate{{Cell{5, 4}, true, false, 0}, {Cell{6, 5}, true, true, 2}, {Cell{5, 6}, true, true, 1}, {Cell{4, 5}, true, true, 1}}
	got, ok := wangChooseExtraLanding(origin, candidates)
	if !ok || got != (Cell{5, 6}) {
		t.Fatalf("enemy > terrain > direction got%v %v", got, ok)
	}
	candidates = append(candidates, wangLandingCandidate{Cell{5, 4}, true, true, 1})
	got, ok = wangChooseExtraLanding(origin, candidates)
	if !ok || got != (Cell{5, 4}) {
		t.Fatal("direction tie must choose up")
	}
	if _, ok := wangChooseExtraLanding(origin, []wangLandingCandidate{{Cell{8, 5}, true, true, 0}, {Cell{5, 4}, false, true, 0}, {Cell{6, 5}, true, true, 3}}); ok {
		t.Fatal("invalid/nonadjacent/unknown terrain accepted")
	}
}
