package main

import (
	"os"
	"path/filepath"
	"rios-sim/core"
	"rios-sim/maa"
	"testing"
)

func TestTrainingParentDataRootMatchesEngine(t *testing.T) {
	// The UI may run with arbitrary cwd; RIOS_DB is already resolved to eng/data.
	repo, err := filepath.Abs(filepath.Join("..", "..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	realRoot := filepath.Join(repo, "data")
	t.Setenv("RIOS_DB", realRoot)
	t.Setenv("RIOS_DATA", filepath.Join(t.TempDir(), "wrong"))
	cwd, err := os.Getwd()
	if err != nil {
		t.Fatal(err)
	}
	if err := os.Chdir(t.TempDir()); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { os.Chdir(cwd) })
	if err := resolveDataDir(); err != nil {
		t.Fatal(err)
	}
	if os.Getenv("RIOS_DATA") != engineDataRoot() {
		t.Fatalf("parent=%s engine=%s", os.Getenv("RIOS_DATA"), engineDataRoot())
	}
	roster := &core.RosterRead{Entries: []core.RosterEntry{{Name: "石英", CharID: "char_4063_quartz", Mastery: map[string]int{"skcom_atk_up[2]": 3}}}}
	plan := core.PlayPlan{Deploys: []core.DeployOrder{{Operator: "石英"}}}
	job, err := maa.ToMaa(plan, roster, nil, nil, maa.MaaOptions{})
	if err != nil || job.Opers[0].Requirements.SkillLevel != 10 {
		t.Fatalf("arbitrary cwd export %v %v", job, err)
	}
}
