package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"io"
	"strings"
	"testing"
)

func TestSelftestReportComplete(t *testing.T) {
	manifest := []string{"business", "control"}
	r := newSelftestReport(manifest)
	manifest[0] = "mutated"
	if !r.Check("business", "first", true, 42) || !r.Check("business", "second", true, "detail") {
		t.Fatal("positive checks rejected")
	}
	if !r.CheckExpectedFalse("control", "intentional negative", false, "rejected") {
		t.Fatal("negative control not accepted")
	}
	r.Finish(0)
	if !r.Completed || !r.Passed || r.RC != 0 || r.SchemaVersion != 1 || r.Profile != "all-required" {
		t.Fatalf("header: %+v", r)
	}
	if r.Manifest[0] != "business" || r.Summary != (selftestReportSummary{Pass: 2, Exercised: 3}) {
		t.Fatalf("manifest/summary: %+v", r)
	}
	c := r.Cases[0]
	if !c.Required || c.CheckCount != 2 || c.Exercised != 2 || len(c.Checks) != 2 || c.Checks[1].Got != "detail" {
		t.Fatalf("details: %+v", c)
	}
	if !r.Cases[1].Checks[0].ExpectedFalse || r.Cases[1].FailedChecks != 0 {
		t.Fatal("control was recorded as failure")
	}
}

func TestSelftestReportMissingManifestCase(t *testing.T) {
	r := newSelftestReport([]string{"covered", "missing"})
	r.Check("covered", "done", true, "ok")
	r.Finish(0)
	c := r.Cases[1]
	if r.Passed || r.RC == 0 || c.Status != "skip" || c.Exercised != 0 || !c.Required || !strings.Contains(c.Reason, "not exercised") {
		t.Fatalf("missing case: %+v / %+v", r, c)
	}
	before := len(c.Checks)
	r.Finish(0)
	if len(r.Cases[1].Checks) != before || r.Summary != (selftestReportSummary{Pass: 1, Skip: 1, Exercised: 1}) {
		t.Fatal("Finish is not idempotent")
	}
}

func TestSelftestReportSkipSticky(t *testing.T) {
	for _, skipFirst := range []bool{false, true} {
		t.Run(map[bool]string{false: "pass-then-skip", true: "skip-then-pass"}[skipFirst], func(t *testing.T) {
			r := newSelftestReport([]string{"required"})
			if skipFirst {
				r.Skip("required", "dependency absent")
			}
			r.Check("required", "partial", true, "ok")
			if !skipFirst {
				r.Skip("required", "dependency absent")
			}
			r.Skip("required", "another omission")
			r.Finish(0)
			c := r.Cases[0]
			if r.Passed || r.RC == 0 || c.Status != "skip" || c.Exercised != 1 || len(c.Checks) != 3 || !strings.Contains(c.Reason, "another omission") {
				t.Fatalf("skip erased: %+v", r)
			}
			for _, check := range c.Checks {
				if check.Status == "skip" && check.Exercised != 0 {
					t.Fatal("skip exercised")
				}
			}
		})
	}
	r := newSelftestReport([]string{"only-skip"})
	r.Skip("only-skip", "")
	r.Finish(0)
	if r.Cases[0].Reason == "" || r.Summary.Exercised != 0 || r.Passed {
		t.Fatal("empty skip accepted")
	}
}

func TestSelftestReportFalseSticky(t *testing.T) {
	r := newSelftestReport([]string{"repeat"})
	r.Check("repeat", "pass1", true, 1)
	if r.Check("repeat", "bad1", false, "specific failure") {
		t.Fatal("false check accepted")
	}
	r.Skip("repeat", "also skipped")
	r.Check("repeat", "pass2", true, 2)
	r.Check("repeat", "bad2", false, "second failure")
	r.Finish(0)
	c := r.Cases[0]
	if r.Passed || r.RC != 1 || c.Status != "fail" || c.FailedChecks != 2 || c.CheckCount != 5 || c.Exercised != 4 {
		t.Fatalf("failed aggregate: %+v", r)
	}
	if !strings.Contains(c.Reason, "specific failure") || !strings.Contains(c.Reason, "second failure") || r.Summary != (selftestReportSummary{Fail: 1, Exercised: 4}) {
		t.Fatalf("failure detail lost: %+v", c)
	}
}

func TestSelftestReportDuplicateManifest(t *testing.T) {
	r := newSelftestReport([]string{"duplicate", "duplicate"})
	r.Check("duplicate", "would pass", true, "ok")
	r.Finish(0)
	if r.Passed || r.RC == 0 || len(r.Errors) != 1 || len(r.Manifest) != 2 || len(r.Cases) != 1 || r.Cases[0].Status != "fail" || r.Summary.Exercised != 1 {
		t.Fatalf("duplicate accepted: %+v", r)
	}
}

func TestSelftestReportUnknownIDs(t *testing.T) {
	r := newSelftestReport([]string{"known"})
	r.Check("known", "ok", true, "ok")
	if r.Check("unknown", "not registered", true, "ok") || r.Check("unknown", "still unknown", true, "ok") {
		t.Fatal("unknown check accepted")
	}
	r.Skip("unknown-skip", "absent")
	r.Finish(0)
	if r.Passed || r.RC == 0 || len(r.Manifest) != 1 || r.Summary.Fail != 2 || r.Summary.Exercised != 3 {
		t.Fatalf("manifest expanded: %+v", r)
	}
	for _, c := range r.Cases {
		if !c.Required {
			t.Fatal("optional case created")
		}
	}
	if r.Cases[2].Status != "fail" || r.Cases[2].Exercised != 0 {
		t.Fatal("unknown skip not failing")
	}
}

func TestSelftestReportExpectedFalse(t *testing.T) {
	r := newSelftestReport([]string{"control"})
	if !r.CheckExpectedFalse("control", "negative control", false, false) {
		t.Fatal("true negative failed")
	}
	if r.CheckExpectedFalse("control", "broken control", true, true) {
		t.Fatal("false negative accepted")
	}
	r.CheckExpectedFalse("control", "later negative", false, false)
	r.Finish(0)
	if r.Passed || r.Cases[0].FailedChecks != 1 || r.Cases[0].Status != "fail" || r.Summary.Exercised != 3 {
		t.Fatalf("control failure cleared: %+v", r)
	}
}

func TestSelftestReportExitCodeAndEmptyManifest(t *testing.T) {
	for _, manifest := range [][]string{nil, {}, {""}, {" "}} {
		r := newSelftestReport(manifest).Finish(0)
		if r.Passed || r.RC == 0 || len(r.Errors) == 0 {
			t.Fatalf("invalid manifest accepted: %+v", r)
		}
	}
	r := newSelftestReport([]string{"ok"})
	r.Check("ok", "ok", true, "ok")
	r.Finish(3)
	if r.Passed || r.RC != 3 || !r.Completed {
		t.Fatalf("caller rc ignored: %+v", r)
	}
	r.Finish(0)
	if r.Passed || r.RC != 3 {
		t.Fatal("nonzero rc cleared")
	}
}

func TestSelftestReportEmit(t *testing.T) {
	r := newSelftestReport([]string{"emit"})
	r.Check("emit", "multiline", true, "line1\nline2")
	var out bytes.Buffer
	if err := r.Emit(&out, 0); err != nil {
		t.Fatal(err)
	}
	line := out.String()
	if strings.Count(line, selftestReportPrefix) != 1 || strings.Count(line, "\n") != 1 || !strings.HasPrefix(line, selftestReportPrefix) {
		t.Fatalf("not a single machine line: %q", line)
	}
	var decoded selftestReport
	if err := json.Unmarshal([]byte(strings.TrimPrefix(strings.TrimSuffix(line, "\n"), selftestReportPrefix)), &decoded); err != nil {
		t.Fatal(err)
	}
	if !decoded.Passed || !decoded.Completed || decoded.Cases[0].Checks[0].Got != "line1\nline2" {
		t.Fatalf("roundtrip failed: %+v", decoded)
	}
	if err := r.Emit(&out, 0); err == nil || strings.Count(out.String(), selftestReportPrefix) != 1 {
		t.Fatal("duplicate emission allowed")
	}
}

type selftestReportErrorWriter struct{}

func (selftestReportErrorWriter) Write([]byte) (int, error) { return 0, errors.New("write failed") }

type selftestReportShortWriter struct{}

func (selftestReportShortWriter) Write(p []byte) (int, error) { return len(p) - 1, nil }

func TestSelftestReportEmitErrors(t *testing.T) {
	r := newSelftestReport([]string{"missing"})
	if err := r.Emit(nil, 0); err == nil {
		t.Fatal("nil writer accepted")
	}
	if err := r.Emit(selftestReportErrorWriter{}, 0); err == nil {
		t.Fatal("writer failure ignored")
	}
	if err := r.Emit(selftestReportShortWriter{}, 0); !errors.Is(err, io.ErrShortWrite) {
		t.Fatalf("short write ignored: %v", err)
	}
	var out bytes.Buffer
	if err := r.Emit(&out, 0); err != nil {
		t.Fatal(err)
	}
	if r.Passed || r.RC != 1 || r.Summary.Skip != 1 {
		t.Fatal("Emit did not finalize omission")
	}
}
