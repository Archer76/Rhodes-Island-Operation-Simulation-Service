package main

import "fmt"

// Run-local stone collection. No guessed frame timing or target eligibility is
// embedded here; simulation must provide qualified enemies and event ordering.
type wangStone struct {
	ID         uint64
	Owner      string
	Position   Cell
	Projectile bool // extra stone; not a deployed character/token unit
	Axes       wangAxes
	Activated  bool
}
type wangStoneField struct {
	stones []wangStone
	nextID uint64
}

func (f *wangStoneField) add(owner string, pos Cell, projectile bool, slot int) (uint64, error) {
	if owner == "" {
		return 0, fmt.Errorf("wang stone requires owner deployment identity")
	}
	for _, s := range f.stones {
		if s.Position == pos {
			return 0, fmt.Errorf("wang stone position occupied; overlap rule unverified")
		}
	}
	f.nextID++
	f.stones = append(f.stones, wangStone{ID: f.nextID, Owner: owner, Position: pos, Projectile: projectile})
	f.refresh(owner, slot)
	return f.nextID, nil
}
func (f *wangStoneField) refresh(owner string, slot int) {
	var peers []Cell
	for _, s := range f.stones {
		if s.Owner == owner {
			peers = append(peers, s.Position)
		}
	}
	for i := range f.stones {
		s := &f.stones[i]
		if s.Owner != owner {
			continue
		}
		previous := wangAxes(0)
		if slot == 2 {
			previous = s.Axes
		}
		s.Axes = wangActivateAxes(s.Position, peers, previous)
		s.Activated = s.Axes != 0
	}
}
func (f *wangStoneField) remove(id uint64) bool {
	for i, s := range f.stones {
		if s.ID == id {
			f.stones = append(f.stones[:i], f.stones[i+1:]...)
			return true
		}
	}
	return false
}
func (f *wangStoneField) removeOwner(owner string) {
	keep := f.stones[:0]
	for _, s := range f.stones {
		if s.Owner != owner {
			keep = append(keep, s)
		}
	}
	f.stones = keep
}

type wangTrigger struct {
	Stone       wangStone
	Stacks      int
	DamageCells []Cell
}

// The caller explicitly chooses ONE stone and target per event. It must not
// silently resolve simultaneous candidate ties via slice order.
func (f *wangStoneField) trigger(id uint64, enemyCell Cell, slot int) (wangTrigger, error) {
	for _, s := range f.stones {
		if s.ID != id {
			continue
		}
		if !s.Activated {
			return wangTrigger{}, fmt.Errorf("wang stone not activated")
		}
		eligible := s.Position == enemyCell
		cells := wangDamageCells(s.Position, slot, s.Axes)
		if slot == 3 {
			eligible = false
			for _, c := range cells {
				if c == enemyCell {
					eligible = true
					break
				}
			}
		}
		if !eligible {
			return wangTrigger{}, fmt.Errorf("enemy outside wang trigger geometry")
		}
		var peers []Cell
		for _, p := range f.stones {
			if p.Owner == s.Owner {
				peers = append(peers, p.Position)
			}
		}
		result := wangTrigger{Stone: s, Stacks: wangTalentStacks(s.Position, peers), DamageCells: cells}
		f.remove(id) // sample talent BEFORE removal; subsequent event samples remaining field
		f.refresh(s.Owner, slot)
		return result, nil
	}
	return wangTrigger{}, fmt.Errorf("unknown or already consumed wang stone %d", id)
}
