package main

import "fmt"

// Binds a free sine segment to its actual inventory identity. Ordinary no-target
// launch only. This is not a simulation scheduler or collision detector.
type sakikoFreeSineBinding struct {
	store       *sakikoOrdinaryStore
	id          int
	trajectory  sakikoOrdinarySine
	moduleID    string
	moduleLevel int
}

func (s *sakikoOrdinaryStore) launchSine(t float64, origin, direction [2]float64, positive bool, cachedATK, cachedScale float64) (*sakikoFreeSineBinding, error) {
	if e := s.validateSource(); e != nil {
		return nil, e
	}
	trajectory, e := newSakikoOrdinarySine(s.owner.spec, t, origin, direction, positive)
	if e != nil {
		return nil, e
	}
	id, e := s.launch(t, -1, cachedATK, cachedScale)
	if e != nil {
		return nil, e
	}
	return &sakikoFreeSineBinding{store: s, id: id, trajectory: trajectory, moduleID: s.owner.spec.ExactModuleTalent.ModuleID, moduleLevel: s.owner.spec.ExactModuleTalent.ModuleLevel}, nil
}

// Explicitly dispatched update: evaluate actual free trajectory before choosing
// nearest. Once tracking begins this segment must no longer drive acquisition.
func (b *sakikoFreeSineBinding) acquire(t float64, candidates []sakikoNoteCandidate) ([2]float64, error) {
	if b.store == nil || b.id < 0 || b.id >= len(b.store.notes) {
		return [2]float64{}, fmt.Errorf("祥子正弦库存绑定非法")
	}
	if e := b.store.validateSource(); e != nil {
		return [2]float64{}, e
	}
	p := b.store.owner.spec.ExactModuleTalent
	if p.ModuleID != b.moduleID || p.ModuleLevel != b.moduleLevel {
		return [2]float64{}, fmt.Errorf("祥子正弦发射后来源更换未证")
	}
	if !b.store.notes[b.id].state.firstFree {
		return [2]float64{}, fmt.Errorf("祥子首段自由轨迹已退出，重新入态轨迹须另建")
	}
	position, e := b.trajectory.position(t)
	if e != nil {
		return [2]float64{}, e
	}
	if e = b.store.acquire(b.id, t, position, candidates); e != nil {
		return [2]float64{}, e
	}
	return position, nil
}
