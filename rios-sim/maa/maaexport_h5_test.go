package maa

import (
	"database/sql"
	"errors"
	"rios-sim/core"
	"rios-sim/data"
	"strings"
	"testing"
)

func h5PlanRoster() (core.PlayPlan, *core.RosterRead) {
	return core.PlayPlan{Stage: "synthetic", Deploys: []core.DeployOrder{{Operator: "石英", Skill: 1}}}, &core.RosterRead{Entries: []core.RosterEntry{{Name: "石英", CharID: "char_4063_quartz", Module: ptr("mod_x"), ModuleLevel: 3}}}
}

func h5DB(t *testing.T, withTable bool) *sql.DB {
	t.Helper()
	db, err := sql.Open("sqlite", ":memory:")
	if err != nil {
		t.Fatal(err)
	}
	db.SetMaxOpenConns(1)
	t.Cleanup(func() { db.Close() })
	if withTable {
		if _, err := db.Exec(`create table module(module_id text,name text,type_name2 text); insert into module values ('mod_x','继承模组','X'),('mod_y','覆盖模组','Y'),('badge','证章',NULL)`); err != nil {
			t.Fatal(err)
		}
	}
	return db
}

func TestH5EffectiveModuleLazyLoading(t *testing.T) {
	plan, roster := h5PlanRoster()
	if _, err := ToMaa(plan, roster, nil, nil, MaaOptions{}); !errors.Is(err, data.ErrDBMissing) {
		t.Fatalf("inherited module must require DB: %v", err)
	}
	job, err := ToMaa(plan, roster, nil, h5DB(t, true), MaaOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if job.Opers[0].Requirements.Module == nil || *job.Opers[0].Requirements.Module != 1 {
		t.Fatalf("lost inherited requirement: %+v", job.Opers[0])
	}
	if !strings.Contains(job.Doc.Details, "继承模组 X 3") {
		t.Fatalf("lost inherited text: %s", job.Doc.Details)
	}
	if _, err := ToMaa(plan, roster, nil, h5DB(t, false), MaaOptions{}); err == nil || !strings.Contains(err.Error(), "module") {
		t.Fatalf("missing table accepted: %v", err)
	}
}

func TestH5OverridesAndUnusedRoster(t *testing.T) {
	plan, roster := h5PlanRoster()
	db := h5DB(t, true)
	plan.Deploys[0].Module = ptr("mod_y")
	plan.Deploys[0].ModuleLevel = ptr(2)
	job, err := ToMaa(plan, roster, nil, db, MaaOptions{})
	if err != nil {
		t.Fatal(err)
	}
	if job.Opers[0].Requirements.Module == nil || *job.Opers[0].Requirements.Module != 2 || !strings.Contains(job.Doc.Details, "覆盖模组 Y 2") {
		t.Fatalf("override lost: %+v", job)
	}
	plan.Deploys[0].Module = ptr("")
	job, err = ToMaa(plan, roster, nil, nil, MaaOptions{})
	if err != nil || job.Opers[0].Requirements.Module != nil {
		t.Fatalf("explicit empty must suppress inheritance without DB: %v", err)
	}
	plan.Deploys[0].Module = nil
	roster.Entries[0].Name = "未部署干员"
	job, err = ToMaa(plan, roster, nil, nil, MaaOptions{})
	if err != nil || job.Opers[0].Requirements.Module != nil {
		t.Fatalf("unused roster module must not trigger DB: %v", err)
	}
}

func TestH5UnknownModuleRequirementsFailNamed(t *testing.T) {
	for _, tc := range []struct {
		name, id string
		table    map[string]ModuleInfo
	}{
		{name: "missing inherited ID", id: "mod_x", table: map[string]ModuleInfo{}},
		{name: "unmapped type", id: "mod_x", table: map[string]ModuleInfo{"mod_x": {TypeName2: "Z"}}},
	} {
		t.Run(tc.name, func(t *testing.T) {
			plan, roster := h5PlanRoster()
			_, err := ToMaa(plan, roster, tc.table, nil, MaaOptions{})
			if !errors.Is(err, ErrModuleRequirement) || !strings.Contains(err.Error(), "石英") || !strings.Contains(err.Error(), tc.id) {
				t.Fatalf("not named: %v", err)
			}
			if _, err := UsedOperators(plan, roster, tc.table); !errors.Is(err, ErrModuleRequirement) {
				t.Fatalf("renderer silently lost module: %v", err)
			}
		})
	}
	plan, roster := h5PlanRoster()
	plan.Deploys[0].Module = ptr("unknown_explicit")
	if _, err := ToMaa(plan, roster, map[string]ModuleInfo{}, nil, MaaOptions{}); !errors.Is(err, ErrModuleRequirement) || !strings.Contains(err.Error(), "unknown_explicit") {
		t.Fatalf("explicit unknown accepted: %v", err)
	}
	plan.Deploys[0].Module = nil
	if _, err := UsedOperators(plan, roster, nil); !errors.Is(err, ErrModuleRequirement) {
		t.Fatalf("missing renderer table accepted inherited ID: %v", err)
	}
	roster.Entries[0].Module = ptr("badge")
	job, err := ToMaa(plan, roster, nil, h5DB(t, true), MaaOptions{})
	if err != nil || job.Opers[0].Requirements.Module != nil {
		t.Fatalf("known badge should omit: %v", err)
	}
}
