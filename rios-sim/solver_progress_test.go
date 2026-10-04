package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"reflect"
	"runtime"
	"testing"
	"time"

	"rios-sim/core"
	"rios-sim/progress"
)

func progressStates(n int) [][]CandidateRow {
	states := make([][]CandidateRow, n)
	for i := range states {
		states[i] = []CandidateRow{{Operator: fmt.Sprint(i), Position: [2]int{i, 0}}}
	}
	return states
}

// A worker cannot finish its second evaluation until the consumer reports its
// first. This fails deterministically if consumption moves behind wg.Wait.
func TestSolveProgressStreamsBeforeLayerCompletes(t *testing.T) {
	old := runtime.GOMAXPROCS(2)
	defer runtime.GOMAXPROCS(old)
	release := make(chan struct{})
	workerEntered := make(chan struct{})
	result := make(chan SolveStats, 1)
	go func() {
		_, sub := evalDepthStreaming(progressStates(4), false,
			func(s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
				switch s[0].Operator {
				case "0":
					return nil, &Verdict{Won: false, Life: 0}, "", nil
				case "1":
					return nil, nil, "spec_failed", errors.New("synthetic refusal")
				default:
					if s[0].Operator == "2" {
						close(workerEntered)
					}
					<-release
					return nil, &Verdict{Won: false, Life: 0}, "", nil
				}
			}, func(sub SolveStats, completed int, got *scoredState) {
				if completed == 2 {
					if sub.SpecFailed != 1 || sub.Evaluated != 1 || got != nil {
						panic("failed attempt not counted")
					}
					close(release)
				}
			})
		result <- sub
	}()
	select {
	case sub := <-result:
		if sub.Evaluated != 3 || sub.SpecFailed != 1 {
			t.Fatalf("stats: %+v", sub)
		}
	case <-time.After(3 * time.Second):
		t.Fatal("progress did not release in-flight layer")
	}
	<-workerEntered
}

func TestSolveProgressNonFirstThreeStarStopsScheduling(t *testing.T) {
	old := runtime.GOMAXPROCS(2)
	defer runtime.GOMAXPROCS(old)
	pool, sub := evalDepthStreaming(progressStates(100), true,
		func(s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
			return nil, &Verdict{Won: s[0].Operator != "0", Life: 1}, "", nil
		}, nil)
	if sub.Stars3 == 0 || sub.Evaluated >= 100 || len(pool) != sub.Evaluated {
		t.Fatalf("non-first success did not stop: %+v pool=%d", sub, len(pool))
	}
	for i, got := range pool {
		if got.state[0].Operator != fmt.Sprint(i) {
			t.Fatalf("index order: %v", got.state)
		}
	}
}

func TestSolveProgressMinOpsAndStableIndexOrder(t *testing.T) {
	old := runtime.GOMAXPROCS(4)
	defer runtime.GOMAXPROCS(old)
	firstWorker := make(chan struct{})
	pool, sub := evalDepthStreaming(progressStates(6), false,
		func(s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
			switch s[0].Operator {
			case "1":
				<-firstWorker
			case "2":
				close(firstWorker)
			}
			return nil, &Verdict{Won: true, Life: 1}, "", nil
		}, nil)
	if sub.Evaluated != 6 || sub.Stars3 != 6 {
		t.Fatalf("below min depth stopped: %+v", sub)
	}
	for i, got := range pool {
		if got.state[0].Operator != fmt.Sprint(i) {
			t.Fatalf("unstable tie order at %d: %v", i, got.state)
		}
	}
}

func TestSolveProgressNilCompatibilityAndFailure(t *testing.T) {
	legacy, legacyErr := Solve("", "", SolveQuery{})
	plain, plainErr := SolveWithProgress("", "", SolveQuery{}, nil)
	var events []progress.Snapshot
	got, err := SolveWithProgress("", "", SolveQuery{}, func(s progress.Snapshot) { events = append(events, s) })
	if legacyErr == nil || plainErr == nil || err == nil || legacyErr.Error() != err.Error() || plainErr.Error() != err.Error() ||
		!reflect.DeepEqual(legacy, got) || !reflect.DeepEqual(plain, got) {
		t.Fatal("legacy/nil callback result changed")
	}
	if len(events) != 2 || events[0].Phase != "preparing" || events[1].Phase != "failed" || events[1].ElapsedSeconds < 0 {
		t.Fatalf("failure progress: %+v", events)
	}
}

func TestSolveProgressCompletedEmptyCandidates(t *testing.T) {
	chdirRepoRootForData(t)
	var events []progress.Snapshot
	out, err := SolveWithProgress("main_01-07", "", SolveQuery{}, func(s progress.Snapshot) { events = append(events, s) })
	if err != nil {
		t.Fatal(err)
	}
	if out.OK || len(events) < 3 || events[len(events)-1].Phase != "completed" || events[len(events)-1].Candidates != 0 {
		t.Fatalf("empty candidate result: %+v progress: %+v", out, events)
	}
}

func TestSolveProgressRealLayerSnapshot(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, testRosterRows)
	var events []progress.Snapshot
	out, err := SolveWithProgress("main_01-07", "", SolveQuery{
		Roster: roster, Operators: []string{"圣聆初雪"}, PerOp: 2, MaxOps: 1,
	}, func(s progress.Snapshot) { events = append(events, s) })
	if err != nil {
		t.Fatal(err)
	}
	var partial, filtered bool
	for _, s := range events {
		if s.Phase == "evaluating" && s.Completed > 0 && s.Completed < s.Total {
			partial = true
		}
		if s.Phase == "filtering" {
			filtered = true
		}
	}
	last := events[len(events)-1]
	if !partial || !filtered || last.Phase != "completed" || last.Evaluated != out.Evaluated ||
		last.Total != 2 || last.Completed < 1 || last.Candidates != 2 || last.BestLine == "" || last.BestStars != out.Stars {
		t.Fatalf("real layer snapshots: %+v output: %+v", events, out)
	}
}

func TestSolveProgressProtocolStdoutCompatibility(t *testing.T) {
	if os.Getenv("RIOS_PROGRESS_PROTOCOL_HELPER") == "1" {
		main()
		os.Exit(0)
	}
	cmd := exec.Command(os.Args[0], "-test.run=^TestSolveProgressProtocolStdoutCompatibility$")
	cmd.Env = append(os.Environ(), "RIOS_PROGRESS_PROTOCOL_HELPER=1")
	cmd.Stdin = bytes.NewBufferString("{\"id\":41,\"cmd\":\"solve\"}\n{\"id\":42,\"cmd\":\"ping\"}\n")
	var stdout, stderr bytes.Buffer
	cmd.Stdout, cmd.Stderr = &stdout, &stderr
	if err := cmd.Run(); err != nil {
		t.Fatalf("helper: %v stderr=%s", err, stderr.String())
	}
	dec := json.NewDecoder(&stdout)
	var one, two response
	if err := dec.Decode(&one); err != nil {
		t.Fatal(err)
	}
	if err := dec.Decode(&two); err != nil {
		t.Fatal(err)
	}
	if one.ID != 41 || one.OK || two.ID != 42 || !two.OK || len(one.Solve) != 0 {
		t.Fatalf("stdout: %+v %+v", one, two)
	}
	var extra response
	if err := dec.Decode(&extra); err != io.EOF {
		t.Fatalf("extra stdout record or noise: %v %+v", err, extra)
	}
	pd := json.NewDecoder(&stderr)
	var phases []string
	for {
		var envelope struct {
			Type     string            `json:"type"`
			Progress progress.Snapshot `json:"progress"`
		}
		err := pd.Decode(&envelope)
		if err == io.EOF {
			break
		}
		if err != nil {
			t.Fatalf("non-JSON stderr: %v", err)
		}
		if envelope.Type != "solve_progress" || envelope.Progress.RequestID != 41 {
			t.Fatalf("envelope: %+v", envelope)
		}
		phases = append(phases, envelope.Progress.Phase)
	}
	if !reflect.DeepEqual(phases, []string{"preparing", "failed"}) {
		t.Fatalf("phases: %v", phases)
	}
}
