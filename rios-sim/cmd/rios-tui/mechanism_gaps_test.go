package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"rios-sim/data"
	"rios-sim/mechanisms"
)

func testGap() mechanisms.Gap {
	return mechanisms.Gap{ID: "skill:test", Status: "unimplemented", Source: "skill", Operator: "测试干员", CharID: "char_test", SourceID: "skill_test", SourceName: "测试技能", Key: "damage_scale", Reason: "伤害机制尚未完整建模"}
}

func TestIncompleteOverridesStarsAndStopsLadder(t *testing.T) {
	s := newSolveScreen(solveParams{}, []int{4, 6, 8})
	c := &appCtx{solveStatus: "complete", solvePlan: json.RawMessage(`{"deploys":[]}`), solveVerdict: json.RawMessage(`{"won":true}`), exportPath: "old-job"}
	r := newRoot(c, s)
	s.best, s.haveBest = solveOutView{OK: true, Stars: 3, Plan: c.solvePlan, Verdict: c.solveVerdict}, true
	out := solveOutView{Status: "incomplete", OK: true, Stars: 3, Plan: c.solvePlan, Verdict: c.solveVerdict, Placeholders: []mechanisms.Gap{testGap()}}
	// Stale task and stale round cannot clear the current result.
	s.onMsg(r, solveRoundMsg{taskID: s.taskID + 1, out: out})
	s.onMsg(r, solveRoundMsg{taskID: s.taskID, round: 1, out: out})
	if c.solveStatus != "complete" {
		t.Fatal("stale incomplete accepted")
	}
	a := s.onMsg(r, solveRoundMsg{taskID: s.taskID, depth: 4, out: out})
	if a.kind != actPush || a.cmd != nil || s.running || !s.done || s.idx != 0 || s.haveBest || s.err != "" {
		t.Fatalf("incomplete did not terminate without victory/failure: %+v", s)
	}
	if c.solveStatus != "incomplete" || c.solveStars != -1 || len(c.solvePlan) > 0 || len(c.solveVerdict) > 0 || c.exportPath != "" || len(c.solvePlaceholders) != 1 {
		t.Fatalf("unsafe result retained: %+v", c)
	}
	view := newResultScreen().view(c)
	for _, want := range []string{mechanismIncompleteMessage, "char_test", "skill_test", "damage_scale", testGap().Reason, "导出已禁用"} {
		if !strings.Contains(view, want) {
			t.Fatalf("missing %q: %s", want, view)
		}
	}
	for _, bad := range []string{"解算失败", "评价", "胜利", "找到三星方案"} {
		if strings.Contains(view, bad) || strings.Contains(strings.Join(s.lines, "\n"), bad) {
			t.Fatalf("incomplete presented as battle result: %s", view)
		}
	}
	rs := newResultScreen()
	rs.export(c)
	if !strings.Contains(rs.msg, "导出已禁用") || c.exportPath != "" {
		t.Fatal("incomplete export allowed")
	}
}

func TestCompleteWithExcludedCandidatesDisplaysAndExports(t *testing.T) {
	dir := t.TempDir()
	roster := filepath.Join(dir, "roster.json")
	if err := os.WriteFile(roster, []byte(`[]`), 0600); err != nil {
		t.Fatal(err)
	}
	c := &appCtx{roster: &rosterData{Path: roster}, guidesDir: dir, stage: &data.StageRecord{Code: "TEST", LevelID: "test"}}
	s := newSolveScreen(solveParams{}, []int{4, 6})
	out := solveOutView{Status: "complete", OK: true, Stars: 3, Plan: json.RawMessage(`{"stage":"test","deploys":[{"operator":"测试干员","position":[1,2],"direction":"right","skill":1}]}`), Verdict: json.RawMessage(`{"status":"complete","won":true,"leaks":0}`), Placeholders: []mechanisms.Gap{testGap()}}
	a := s.onMsg(newRoot(c, s), solveRoundMsg{taskID: s.taskID, depth: 4, out: out})
	if a.kind != actPush || c.solveStatus != "complete" || c.solveStars != 3 || len(c.solvePlan) == 0 {
		t.Fatal("complete plan not retained")
	}
	if blocked, _ := finalMechanismGaps(c); blocked {
		t.Fatal("excluded candidate blocked selected plan")
	}
	rs := newResultScreen()
	view := rs.view(c)
	for _, want := range []string{"排除候选，非结果缺口", "胜利", "用到的干员", "测试干员"} {
		if !strings.Contains(view, want) {
			t.Fatalf("missing %q: %s", want, view)
		}
	}
	rs.export(c)
	if c.exportPath == "" {
		t.Fatalf("complete export failed: %s", rs.msg)
	}
	if _, err := os.Stat(c.exportPath); err != nil {
		t.Fatal(err)
	}
}

func TestFinalResultMechanismExportGuards(t *testing.T) {
	for _, tc := range []struct {
		name          string
		status        string
		plan, verdict string
		blocked       bool
	}{
		{"solve", "incomplete", `{}`, `{}`, true},
		{"verdict", "complete", `{}`, `{"status":"incomplete"}`, true},
		{"plan", "complete", `{"mechanism_placeholders":[{"id":"final","reason":"not modeled"}]}`, `{"status":"complete"}`, true},
		{"empty final gaps", "complete", `{"mechanism_placeholders":[]}`, `{"status":"complete"}`, false},
	} {
		t.Run(tc.name, func(t *testing.T) {
			c := &appCtx{solveStatus: tc.status, solvePlan: json.RawMessage(tc.plan), solveVerdict: json.RawMessage(tc.verdict), solvePlaceholders: []mechanisms.Gap{testGap()}}
			if got, _ := finalMechanismGaps(c); got != tc.blocked {
				t.Fatalf("blocked=%v want %v", got, tc.blocked)
			}
			if tc.blocked {
				rs := newResultScreen()
				rs.export(c)
				if !strings.Contains(rs.msg, "导出已禁用") || c.exportPath != "" {
					t.Fatal("final mechanism gap exported")
				}
			}
		})
	}
}

func TestFullPlaceholderListPreserved(t *testing.T) {
	s := newSolveScreen(solveParams{}, []int{4})
	gaps := make([]mechanisms.Gap, 40)
	for i := range gaps {
		gaps[i] = testGap()
	}
	c := &appCtx{}
	s.onMsg(newRoot(c, s), solveRoundMsg{taskID: s.taskID, out: solveOutView{Status: "incomplete", Placeholders: gaps}})
	if len(c.solvePlaceholders) != 40 {
		t.Fatal("placeholder list truncated like solve logs")
	}
}
