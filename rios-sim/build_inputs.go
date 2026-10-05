package main

import (
	"encoding/json"
	"sync"
)

// buildInputs is owned by one build request or one Solve invocation. It is never
// global: a subsequent request observes its own data root and file contents.
// Published stage/raw/roster/library data are read-only; builders own outputs.
// Separate stage paths preserve the historical gate loader's difficulty rules.
type buildInputs struct {
	level, path, difficulty string
	stageOnce               sync.Once
	stage                   *Stage
	raw                     map[string]json.RawMessage
	stageErr                error
	gateOnce                sync.Once
	gateStage               *Stage
	gateErr                 error
	libraryOnce             sync.Once
	library                 *EnemyLibrary
	libraryErr              error
	roster                  *RosterRead
	statsMu                 sync.Mutex
	stats                   map[OperatorCalcConfig]*statsEntry
	skillsMu                sync.Mutex
	skills                  map[skillCacheKey]*skillEntry
}

type statsEntry struct {
	once  sync.Once
	value *OperatorStats
	err   error
}
type skillCacheKey struct {
	id    string
	level int
}
type skillEntry struct {
	once  sync.Once
	value *SkillMeta
	err   error
}

// Cached objects are private read-only inputs. Do not expose them directly as
// mutable command results. Map locks only locate entries; loading uses per-key Once.
func (in *buildInputs) operatorStats(cfg OperatorCalcConfig) (*OperatorStats, error) {
	if in == nil {
		return OperatorStatsFor(cfg, "round")
	}
	in.statsMu.Lock()
	if in.stats == nil {
		in.stats = map[OperatorCalcConfig]*statsEntry{}
	}
	entry := in.stats[cfg]
	if entry == nil {
		entry = &statsEntry{}
		in.stats[cfg] = entry
	}
	in.statsMu.Unlock()
	entry.once.Do(func() { entry.value, entry.err = OperatorStatsFor(cfg, "round") })
	return entry.value, entry.err
}
func (in *buildInputs) skillMeta(id string, level int) (*SkillMeta, error) {
	if in == nil {
		return SkillMetaFor(id, level)
	}
	key := skillCacheKey{id, level}
	in.skillsMu.Lock()
	if in.skills == nil {
		in.skills = map[skillCacheKey]*skillEntry{}
	}
	entry := in.skills[key]
	if entry == nil {
		entry = &skillEntry{}
		in.skills[key] = entry
	}
	in.skillsMu.Unlock()
	entry.once.Do(func() { entry.value, entry.err = SkillMetaFor(id, level) })
	return entry.value, entry.err
}

func newBuildInputs(level, path, difficulty string) *buildInputs {
	return &buildInputs{level: level, path: path, difficulty: difficulty}
}
func (in *buildInputs) stageData() (*Stage, map[string]json.RawMessage, error) {
	in.stageOnce.Do(func() { in.stage, in.raw, in.stageErr = loadStageWithRaw(in.level, in.path, in.difficulty) })
	return in.stage, in.raw, in.stageErr
}
func (in *buildInputs) gateData() (*Stage, error) {
	in.gateOnce.Do(func() { in.gateStage, in.gateErr = loadGateStage(in.level, in.path, in.difficulty) })
	return in.gateStage, in.gateErr
}
func (in *buildInputs) enemies() (*EnemyLibrary, error) {
	in.libraryOnce.Do(func() { in.library, in.libraryErr = LoadEnemyLibrary() })
	return in.library, in.libraryErr
}
