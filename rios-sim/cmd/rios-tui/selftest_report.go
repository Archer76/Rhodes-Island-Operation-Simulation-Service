package main

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
)

const selftestReportPrefix = "RIOS_SELFTEST_REPORT="

// A manifest is a fixed list of required business/callsite IDs supplied by the
// caller, never a list inferred from whichever assertions happened to execute.
type selftestReport struct {
	SchemaVersion int                   `json:"schema_version"`
	Profile       string                `json:"profile"`
	Completed     bool                  `json:"completed"`
	Passed        bool                  `json:"passed"`
	RC            int                   `json:"rc"`
	Manifest      []string              `json:"manifest"`
	Cases         []selftestReportCase  `json:"cases"`
	Summary       selftestReportSummary `json:"summary"`
	Errors        []string              `json:"errors"`
	MinimumChecks map[string]int        `json:"minimum_checks,omitempty"`
	index         map[string]int
	emitted       bool
}

type selftestReportSummary struct {
	Pass      int `json:"pass"`
	Fail      int `json:"fail"`
	Skip      int `json:"skip"`
	Exercised int `json:"exercised"`
}

type selftestReportCase struct {
	ID           string                `json:"id"`
	Name         string                `json:"name"`
	Status       string                `json:"status"`
	Required     bool                  `json:"required"`
	Reason       string                `json:"reason"`
	Exercised    int                   `json:"exercised"`
	CheckCount   int                   `json:"check_count"`
	FailedChecks int                   `json:"failed_checks"`
	Checks       []selftestReportCheck `json:"checks"`
}

type selftestReportCheck struct {
	CaseID        string `json:"case_id"`
	Name          string `json:"name"`
	Status        string `json:"status"`
	Reason        string `json:"reason"`
	Exercised     int    `json:"exercised"`
	Got           string `json:"got"`
	ExpectedFalse bool   `json:"expected_false,omitempty"`
}

func newSelftestReport(manifest []string) *selftestReport {
	r := &selftestReport{SchemaVersion: 1, Profile: "all-required", Manifest: append([]string{}, manifest...), Cases: []selftestReportCase{}, Errors: []string{}, index: make(map[string]int)}
	if len(manifest) == 0 {
		r.Errors = append(r.Errors, "empty required manifest")
	}
	for _, id := range manifest {
		if i, ok := r.index[id]; ok {
			reason := fmt.Sprintf("duplicate manifest ID %q", id)
			r.Errors = append(r.Errors, reason)
			r.record(i, selftestReportCheck{CaseID: id, Name: "manifest", Status: "fail", Reason: reason})
			continue
		}
		r.index[id] = len(r.Cases)
		r.Cases = append(r.Cases, selftestReportCase{ID: id, Name: id, Required: true, Checks: []selftestReportCheck{}})
		if strings.TrimSpace(id) == "" {
			r.Errors = append(r.Errors, "empty manifest ID")
			r.record(r.index[id], selftestReportCheck{CaseID: id, Name: "manifest", Status: "fail", Reason: "empty manifest ID"})
		}
	}
	return r
}

// Unknown IDs produce failing diagnostic cases without changing Manifest.
func (r *selftestReport) caseIndex(id string) (int, bool) {
	if i, ok := r.index[id]; ok {
		// An unknown diagnostic case remains unknown on subsequent calls.
		for _, known := range r.Manifest {
			if known == id {
				return i, true
			}
		}
		return i, false
	}
	i := len(r.Cases)
	r.index[id] = i
	r.Cases = append(r.Cases, selftestReportCase{ID: id, Name: id, Required: true, Checks: []selftestReportCheck{}})
	return i, false
}

func (r *selftestReport) record(i int, check selftestReportCheck) {
	c := &r.Cases[i]
	if len(c.Checks) == 0 && check.Name != "" {
		c.Name = check.Name
	}
	c.Checks = append(c.Checks, check)
	c.CheckCount++
	c.Exercised += check.Exercised
	if check.Status == "fail" {
		c.FailedChecks++
	}
	// Failure and skip are sticky: a later successful assertion cannot erase them.
	if check.Status == "fail" || c.Status == "" || (check.Status == "skip" && c.Status != "fail") {
		c.Status = check.Status
	}
	if check.Reason != "" {
		if c.Reason != "" {
			c.Reason += "; "
		}
		c.Reason += check.Reason
	}
	r.Completed = false
	r.Passed = false
}

func (r *selftestReport) check(id, name string, cond bool, got any, expectedFalse bool) bool {
	i, known := r.caseIndex(id)
	status, reason := "pass", ""
	if !cond {
		status, reason = "fail", fmt.Sprintf("%s: got %v", name, got)
	}
	if !known {
		status, reason = "fail", fmt.Sprintf("unknown required ID %q: %s: got %v", id, name, got)
	}
	r.record(i, selftestReportCheck{CaseID: id, Name: name, Status: status, Reason: reason, Exercised: 1, Got: fmt.Sprint(got), ExpectedFalse: expectedFalse})
	return cond && known
}

func (r *selftestReport) Check(id, name string, cond bool, got any) bool {
	return r.check(id, name, cond, got, false)
}

// An intentional negative control is an assertion that the condition is false,
// not a failure that is recorded and then silently subtracted from a counter.
func (r *selftestReport) CheckExpectedFalse(id, name string, cond bool, got any) bool {
	return r.check(id, name, !cond, got, true)
}

func (r *selftestReport) Skip(id, reason string) {
	i, known := r.caseIndex(id)
	status := "skip"
	if reason == "" {
		reason = "required case skipped"
	}
	if !known {
		status, reason = "fail", fmt.Sprintf("unknown required ID %q: %s", id, reason)
	}
	r.record(i, selftestReportCheck{CaseID: id, Name: r.Cases[i].Name, Status: status, Reason: reason})
}

// Finish is idempotent. Completed means finalized, not successful. A nonzero
// caller exit code is retained; omissions, skips or failures turn zero into one.
func (r *selftestReport) Finish(exitcode int) *selftestReport {
	for i := range r.Cases {
		c := r.Cases[i]
		if min := r.MinimumChecks[c.ID]; min > 0 && c.Status == "pass" && c.Exercised < min {
			r.record(i, selftestReportCheck{CaseID: c.ID, Name: c.Name, Status: "fail", Reason: fmt.Sprintf("required minimum checks %d, exercised %d", min, c.Exercised)})
		}
		if len(r.Cases[i].Checks) == 0 {
			r.record(i, selftestReportCheck{CaseID: r.Cases[i].ID, Name: r.Cases[i].Name, Status: "skip", Reason: "required manifest case not exercised"})
		}
	}
	r.Summary = selftestReportSummary{}
	for _, c := range r.Cases {
		switch c.Status {
		case "pass":
			r.Summary.Pass++
		case "fail":
			r.Summary.Fail++
		case "skip":
			r.Summary.Skip++
		}
		r.Summary.Exercised += c.Exercised
	}
	if exitcode != 0 {
		r.RC = exitcode
	}
	r.Passed = len(r.Errors) == 0 && len(r.Manifest) > 0 && r.Summary.Fail == 0 && r.Summary.Skip == 0 && r.RC == 0
	if !r.Passed && r.RC == 0 {
		r.RC = 1
	}
	r.Completed = true
	return r
}

// Emit writes exactly one prefixed JSON line, with no surrounding human output.
// Repeat successful emission is rejected so stdout has a unique report record.
func (r *selftestReport) Emit(w io.Writer, rc int) error {
	if r.emitted {
		return errors.New("selftest report already emitted")
	}
	if w == nil {
		return errors.New("nil selftest report writer")
	}
	body, err := json.Marshal(r.Finish(rc))
	if err != nil {
		return err
	}
	line := append([]byte(selftestReportPrefix), body...)
	line = append(line, '\n')
	n, err := w.Write(line)
	if err != nil {
		return err
	}
	if n != len(line) {
		return io.ErrShortWrite
	}
	r.emitted = true
	return nil
}
