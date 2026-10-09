package core

import (
	"encoding/json"
	"math"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func actionPlanObject(t *testing.T, extra string) map[string]json.RawMessage {
	t.Helper()
	var obj map[string]json.RawMessage
	text := `{"stage":"test","deploys":[{"operator":"Wang","position":[1,2]}]` + extra + `}`
	if err := json.Unmarshal([]byte(text), &obj); err != nil {
		t.Fatal(err)
	}
	return obj
}

func TestEntityActionsParseShapeAndRuntimeGuard(t *testing.T) {
	extra := `,"entity_deploys":[{"owner":"Wang","position":[1,2],"time":0},{"owner":"Wang","position":[1,2],"time":1.5}],"skill_stops":[{"operator":"Wang","time":2}]`
	obj := actionPlanObject(t, extra)
	p, err := ParsePlanShape(obj)
	if err != nil {
		t.Fatal(err)
	}
	if len(p.EntityDeploys) != 2 || p.EntityDeploys[0].Owner != "Wang" || p.EntityDeploys[0].Position != [2]int{1, 2} || p.EntityDeploys[1].Time != 1.5 || len(p.SkillStops) != 1 || p.SkillStops[0].Time != 2 {
		t.Fatalf("lost parsed actions: %+v", p)
	}
	if err := p.ValidateShape(); err != nil {
		t.Fatal(err)
	}
	for _, field := range []string{"entity_deploys", "skill_stops"} {
		if err := p.Validate(); err == nil || !strings.Contains(err.Error(), field) || !strings.Contains(err.Error(), "runtime unsupported") {
			t.Fatalf("missing runtime guard for %s: %v", field, err)
		}
	}
	parsed, err := ParsePlan(obj)
	if err == nil || len(parsed.EntityDeploys) != 2 || len(parsed.SkillStops) != 1 {
		t.Fatalf("production parse silently dropped actions: %+v, %v", parsed, err)
	}
	path := filepath.Join(t.TempDir(), "plan.json")
	data, err := json.Marshal(obj)
	if err != nil {
		t.Fatal(err)
	}
	if err := os.WriteFile(path, data, 0600); err != nil {
		t.Fatal(err)
	}
	if _, err := ReadPlan(path); err == nil || !strings.Contains(err.Error(), "runtime unsupported") {
		t.Fatalf("ReadPlan bypassed guard: %v", err)
	}
}

func TestEntityActionsStrictPresence(t *testing.T) {
	for _, field := range []string{"entity_deploys", "skill_stops"} {
		for _, raw := range []string{"null", "false", "0", `""`, `{}`, `[null]`, `[false]`, `[0]`, `[""]`, `[[]]`} {
			t.Run(field+"/"+raw, func(t *testing.T) {
				_, err := ParsePlanShape(actionPlanObject(t, `,"`+field+`":`+raw))
				if err == nil || !strings.Contains(err.Error(), field) {
					t.Fatalf("invalid presence accepted: %v", err)
				}
			})
		}
	}
	for _, extra := range []string{"", `,"entity_deploys":[],"skill_stops":[]`} {
		if _, err := ParsePlan(actionPlanObject(t, extra)); err != nil {
			t.Fatalf("no actions rejected: %v", err)
		}
	}
}

func TestEntityActionsStrictFields(t *testing.T) {
	cases := []struct{ field, row, bad string }{
		{"entity_deploys", `{"position":[0,0],"time":0}`, "owner"},
		{"entity_deploys", `{"owner":"Wang","time":0}`, "position"},
		{"entity_deploys", `{"owner":"Wang","position":[0,0]}`, "time"},
		{"skill_stops", `{"time":0}`, "operator"},
		{"skill_stops", `{"operator":"Wang"}`, "time"},
	}
	for _, name := range []string{"null", "false", "0", `""`, `"   "`, `[]`, `{}`, `"Unknown"`, `" Wang "`} {
		cases = append(cases, struct{ field, row, bad string }{"entity_deploys", `{"owner":` + name + `,"position":[0,0],"time":0}`, "owner"})
		cases = append(cases, struct{ field, row, bad string }{"skill_stops", `{"operator":` + name + `,"time":0}`, "operator"})
	}
	for _, time := range []string{"null", "false", `"0"`, `"NaN"`, `"Inf"`, "-0.1", "1e309", "[]", "{}"} {
		cases = append(cases, struct{ field, row, bad string }{"entity_deploys", `{"owner":"Wang","position":[0,0],"time":` + time + `}`, "time"})
		cases = append(cases, struct{ field, row, bad string }{"skill_stops", `{"operator":"Wang","time":` + time + `}`, "time"})
	}
	for _, pos := range []string{"null", "false", "0", `""`, `{}`, `[]`, `[0]`, `[0,0,0]`, `[null,0]`, `[false,0]`, `["1",0]`, `[1.5,0]`, `[0,-1.5]`, `[1.00000000000000001,0]`, `[9223372036854775808,0]`, `[1e309,0]`} {
		cases = append(cases, struct{ field, row, bad string }{"entity_deploys", `{"owner":"Wang","position":` + pos + `,"time":0}`, "position"})
	}
	for _, tc := range cases {
		t.Run(tc.field+"/"+tc.row, func(t *testing.T) {
			_, err := ParsePlanShape(actionPlanObject(t, `,"`+tc.field+`":[`+tc.row+`]`))
			if err == nil || !strings.Contains(err.Error(), tc.field) || !strings.Contains(err.Error(), tc.bad) {
				t.Fatalf("expected named %s.%s error: %v", tc.field, tc.bad, err)
			}
		})
	}
}

func TestEntityActionsValidateProgrammatic(t *testing.T) {
	base, err := ParsePlanShape(actionPlanObject(t, ""))
	if err != nil {
		t.Fatal(err)
	}
	for _, time := range []float64{math.NaN(), math.Inf(1), math.Inf(-1), -1} {
		p := base
		p.EntityDeploys = []EntityDeployOrder{{Owner: "Wang", Time: time}}
		if err := p.ValidateShape(); err == nil || !strings.Contains(err.Error(), "entity_deploys[0].time") {
			t.Fatalf("entity time accepted: %v", err)
		}
		p = base
		p.SkillStops = []SkillStopOrder{{Operator: "Wang", Time: time}}
		if err := p.ValidateShape(); err == nil || !strings.Contains(err.Error(), "skill_stops[0].time") {
			t.Fatalf("stop time accepted: %v", err)
		}
	}
	for _, name := range []string{"", " ", "Unknown"} {
		p := base
		p.EntityDeploys = []EntityDeployOrder{{Owner: name}}
		if err := p.ValidateShape(); err == nil {
			t.Fatal("invalid owner accepted")
		}
		p = base
		p.SkillStops = []SkillStopOrder{{Operator: name}}
		if err := p.ValidateShape(); err == nil {
			t.Fatal("invalid operator accepted")
		}
	}
	for _, field := range []string{"entity_deploys", "skill_stops"} {
		p := base
		if field == "entity_deploys" {
			p.EntityDeploys = []EntityDeployOrder{{Owner: "Wang"}}
		} else {
			p.SkillStops = []SkillStopOrder{{Operator: "Wang"}}
		}
		if err := p.Validate(); err == nil || err.Error() != field+": runtime unsupported" {
			t.Fatalf("missing independent guard: %v", err)
		}
	}
}

func TestEntityCoordinatesNoFloatRounding(t *testing.T) {
	for _, pos := range []string{`[0,0]`, `[-1,2.0]`, `[1e2,3]`, `[9007199254740993,0]`} {
		p, err := ParsePlanShape(actionPlanObject(t, `,"entity_deploys":[{"owner":"Wang","position":`+pos+`,"time":0}]`))
		if err != nil {
			t.Fatal(err)
		}
		if pos == `[9007199254740993,0]` && p.EntityDeploys[0].Position[0] != 9007199254740993 {
			t.Fatal("integer rounded via float")
		}
	}
}
