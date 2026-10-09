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
	generation  uint64
	reentered   bool
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

// Bind a newly entered free segment after a dispatched tracking-loss update.
// Caller provides exact current position/direction; no tracking integrator is inferred.
func (b *sakikoFreeSineBinding) reenter(t float64, position, direction [2]float64, positive bool) (*sakikoFreeSineBinding, error) {
	s, id := b.store, b.id
	if s == nil {
		return nil, fmt.Errorf("祥子正弦重入无库存绑定")
	}

	if b.reentered {
		return nil, fmt.Errorf("祥子自由段已重入，不重复抽取轨迹")
	}
	if id < 0 || id >= len(s.notes) {
		return nil, fmt.Errorf("祥子重入音符身份不存在")
	}
	if e := s.validateSource(); e != nil {
		return nil, e
	}
	note := s.notes[id]
	n := note.state
	p := s.owner.spec.ExactModuleTalent
	if n.phase != sakikoNoteFree || n.target >= 0 || n.firstFree || n.freeGeneration != b.generation+1 || t != n.freeEntered || n.lastUpdate != n.freeEntered {
		return nil, fmt.Errorf("祥子正弦重入须对应追踪失效的入态时刻")
	}
	if note.moduleID != p.ModuleID || note.moduleLevel != p.ModuleLevel {
		return nil, fmt.Errorf("祥子音符重入来源更换未证")
	}
	trajectory, e := newSakikoOrdinarySine(s.owner.spec, t, position, direction, positive)
	if e != nil {
		return nil, e
	}
	b.reentered = true
	return &sakikoFreeSineBinding{store: s, id: id, trajectory: trajectory, moduleID: p.ModuleID, moduleLevel: p.ModuleLevel, generation: n.freeGeneration}, nil
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
	n := b.store.notes[b.id].state
	if n.freeGeneration != b.generation || n.phase != sakikoNoteFree || (b.generation == 0 && !n.firstFree) {
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
