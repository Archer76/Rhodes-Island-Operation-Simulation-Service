package main

import (
	"fmt"
	"math"
	"reflect"
)

// Local ordinary-note inventory. Events are explicitly dispatched; no trajectory,
// collision discovery, random launch angle or timeout schedule is inferred.
type sakikoStoredNote struct {
	state       *sakikoOrdinaryNote
	raw         float64
	moduleID    string
	moduleLevel int
}
type sakikoOrdinaryStore struct {
	owner *operator
	notes []*sakikoStoredNote
}

// Both independent authenticated payloads must name the same module tier.
// Their validators already bind each tier to the same canonical part hash.
func (s *sakikoOrdinaryStore) validateSource() error {
	if s.owner == nil {
		return fmt.Errorf("祥子音符库存无来源")
	}
	r, p := s.owner.spec.SkillRangedExemption, s.owner.spec.ExactModuleTalent
	if !validSkillRangedExemption(s.owner.spec.CharID, r) || p == nil || r.ModuleID != p.ModuleID || r.ModuleLevel != p.ModuleLevel {
		return fmt.Errorf("祥子音符库存来源混档或缺失")
	}
	exact, e := resolveExactCountModuleTalentPart(&OperatorStats{CharID: s.owner.spec.CharID, Module: p.ModuleID, ModuleLevel: p.ModuleLevel, Elite: p.Elite, Level: p.Level, Potential: p.Potential}, p.RawPart)
	if e != nil || exact == nil || !reflect.DeepEqual(exact, p) {
		return fmt.Errorf("祥子音符库存天赋来源非法")
	}
	return nil
}
func (s *sakikoOrdinaryStore) launch(t float64, target int, cachedATK, cachedScale float64) (int, error) {
	if s.owner == nil || !s.owner.alive() {
		return -1, fmt.Errorf("祥子音符库存无持有者")
	}
	if math.IsNaN(cachedATK) || math.IsInf(cachedATK, 0) || cachedATK < 0 || math.IsNaN(cachedScale) || math.IsInf(cachedScale, 0) || cachedScale < 0 || math.IsInf(cachedATK*cachedScale, 0) {
		return -1, fmt.Errorf("祥子音符缓存攻击或倍率非法")
	}
	if e := s.validateSource(); e != nil {
		return -1, e
	}
	n, e := newSakikoOrdinaryNote(s.owner.spec, t, target)
	if e != nil {
		return -1, e
	}
	s.notes = append(s.notes, &sakikoStoredNote{state: n, raw: cachedATK * cachedScale, moduleID: s.owner.spec.ExactModuleTalent.ModuleID, moduleLevel: s.owner.spec.ExactModuleTalent.ModuleLevel})
	return len(s.notes) - 1, nil
}
func (s *sakikoOrdinaryStore) count() int {
	n := 0
	for _, v := range s.notes {
		if v.state.phase != sakikoNoteRemoved {
			n++
		}
	}
	return n
}
func (s *sakikoOrdinaryStore) update(id int, t float64, valid bool, nearest int) error {
	if id < 0 || id >= len(s.notes) {
		return fmt.Errorf("祥子音符身份不存在")
	}
	return s.notes[id].state.update(t, valid, nearest)
}
func (s *sakikoOrdinaryStore) hit(t float64, id int, target *enemy, otherDefPen, otherResPen float64) (float64, error) {
	if s.owner == nil || id < 0 || id >= len(s.notes) {
		return 0, fmt.Errorf("祥子音符命中身份不存在")
	}
	if e := s.validateSource(); e != nil {
		return 0, e
	}
	n := s.notes[id]
	if n.moduleID != s.owner.spec.ExactModuleTalent.ModuleID || n.moduleLevel != s.owner.spec.ExactModuleTalent.ModuleLevel {
		return 0, fmt.Errorf("祥子音符发射后来源更换未证")
	}
	if n.state.phase != sakikoNoteTracking || target == nil || !target.alive() || target.index != n.state.target {
		return 0, fmt.Errorf("祥子音符命中目标或状态不一致")
	}
	if t < n.state.lastUpdate {
		return 0, fmt.Errorf("祥子音符命中早于状态更新")
	}
	// Count BEFORE removal, including this hitting note. Ordinary notes are physical.
	got, e := s.owner.consumeSakikoNoteDamage(t, target, n.raw, "PHYSICAL", s.count(), otherDefPen, otherResPen)
	if e != nil {
		return 0, e
	}
	if e = n.state.hit(); e != nil {
		return 0, e
	}
	return got, nil
}
func (s *sakikoOrdinaryStore) sourceRetreat() {
	for _, v := range s.notes {
		v.state.sourceRetreat()
	}
}
