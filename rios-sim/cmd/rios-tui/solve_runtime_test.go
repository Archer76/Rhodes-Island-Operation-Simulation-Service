package main

import (
	"context"
	"encoding/json"
	"fmt"
	"os"
	"strings"
	"testing"
	"time"

	tea "github.com/charmbracelet/bubbletea"
	"rios-sim/progress"
)

func TestSolveProtocolPeer(t *testing.T) {
	mode := os.Getenv("RIOS_TEST_PEER")
	if mode == "" {
		return
	}
	fmt.Fprintln(os.Stderr, `{"type":"solve_progress","progress":{"request_id":1,"phase":"evaluating","depth":1,"max_depth":4,"evaluated":2,"completed":3,"total":20,"candidates":8,"kept":0,"best_stars":2,"best_line":"working"}}`)
	if mode == "wait" {
		time.Sleep(30 * time.Second)
	}
	fmt.Println(`{"id":1,"ok":true,"solve":{"ok":true,"stars":3,"evaluated":4}}`)
	os.Exit(0)
}

func testPeer(t *testing.T, mode string) *engineClient {
	t.Helper()
	t.Setenv("RIOS_TEST_PEER", mode)
	exe, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	return &engineClient{path: exe, args: []string{"-test.run=^TestSolveProtocolPeer$"}}
}

func TestSolveStreamBeforeFinalAndCancel(t *testing.T) {
	ec := testPeer(t, "wait")
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	arrived := make(chan progress.Snapshot, 1)
	finished := make(chan error, 1)
	go func() {
		_, err := ec.solveStreaming(ctx, solveParams{}, 4, func(s progress.Snapshot) { arrived <- s })
		finished <- err
	}()
	select {
	case s := <-arrived:
		if s.Completed != 3 || s.Total != 20 || s.BestStars != 2 {
			t.Fatalf("bad snapshot: %+v", s)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("no live progress before final")
	}
	select {
	case err := <-finished:
		t.Fatalf("returned before cancel: %v", err)
	default:
	}
	cancel()
	select {
	case err := <-finished:
		if err != context.Canceled {
			t.Fatalf("cancel error: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("cancel did not reap subprocess")
	}
}

func TestSolveStreamFinalResponse(t *testing.T) {
	ec := testPeer(t, "finish")
	var updates int
	out, err := ec.solveStreaming(context.Background(), solveParams{}, 4, func(progress.Snapshot) { updates++ })
	if err != nil || !out.OK || out.Evaluated != 4 || updates != 1 {
		t.Fatalf("out=%+v updates=%d err=%v", out, updates, err)
	}
}

func TestSolveStaleMessagesAndLiveValues(t *testing.T) {
	a := newSolveScreen(solveParams{}, []int{4})
	b := newSolveScreen(solveParams{beam: 5, perOp: 6}, []int{4})
	c := &appCtx{w: 90, h: 26}
	r := newRoot(c, b)
	a.close()
	old := []tea.Msg{solveTickMsg{taskID: a.taskID}, solveRoundMsg{taskID: a.taskID, out: solveOutView{OK: true, Stars: 3}}, solveProgressMsg{taskID: a.taskID, snapshot: progress.Snapshot{Evaluated: 99}}}
	for _, m := range old {
		b.onMsg(r, m)
	}
	if b.evals != 0 || b.elapsed != 0 || b.done || len(c.solvePlan) > 0 {
		t.Fatal("old task mutated current task")
	}
	b.onMsg(r, solveProgressMsg{taskID: b.taskID, round: 0, snapshot: progress.Snapshot{Phase: "evaluating", Depth: 2, MaxDepth: 4, Evaluated: 7, Completed: 9, Total: 12, Candidates: 20, Kept: 3, BestStars: 2, BestLine: "best"}})
	if b.evals != 7 || b.progress() != 75 {
		t.Fatalf("live not applied: %+v", b.live)
	}
	view := b.view(c)
	for _, s := range []string{"7 个候选", "2/4", "9/12", "保留 3", "最佳 2 星", "best"} {
		if !strings.Contains(view, s) {
			t.Fatalf("missing %q in %s", s, view)
		}
	}
	b.onMsg(r, solveProgressMsg{taskID: b.taskID, round: 1, snapshot: progress.Snapshot{Evaluated: 999}})
	if b.evals != 7 {
		t.Fatal("old round accepted")
	}
	b.onMsg(r, solveTickMsg{taskID: b.taskID})
	if b.elapsed != 1 {
		t.Fatal("current heartbeat rejected")
	}
}

func TestProgressWriterChunkedAndDiagnostics(t *testing.T) {
	var got []progress.Snapshot
	w := &progressWriter{requestID: 1, emit: func(s progress.Snapshot) { got = append(got, s) }}
	line, _ := json.Marshal(map[string]any{"type": "solve_progress", "progress": progress.Snapshot{RequestID: 1, Evaluated: 5}})
	w.Write([]byte("plain diagnostic\n"))
	w.Write(line[:7])
	w.Write(append(line[7:], '\n'))
	wrong, _ := json.Marshal(map[string]any{"type": "solve_progress", "progress": progress.Snapshot{RequestID: 2}})
	w.Write(append(wrong, '\n'))
	if len(got) != 1 || got[0].Evaluated != 5 || !strings.Contains(w.diagnostic(), "plain diagnostic") {
		t.Fatalf("got=%v diagnostic=%s", got, w.diagnostic())
	}
}

func TestSolveFinalSnapshotBeforeResult(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	task := &solveTask{ctx: ctx, updates: make(chan solveProgressMsg, 1), result: make(chan solveRoundMsg, 1)}
	task.updates <- solveProgressMsg{snapshot: progress.Snapshot{Phase: "completed"}}
	msg := task.finalMessage(solveRoundMsg{depth: 4})
	if _, ok := msg.(solveProgressMsg); !ok {
		t.Fatal("final snapshot lost")
	}
	if _, ok := task.next()().(solveRoundMsg); !ok {
		t.Fatal("final result lost")
	}
}

func TestSolveScreenExitCancelsTask(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	s := newSolveScreen(solveParams{}, []int{4})
	s.task = &solveTask{ctx: ctx, cancel: cancel, exited: make(chan struct{})}
	r := newRoot(&appCtx{}, welcomeScreen{})
	r.push(s, nil)
	r.pop(nil)
	if ctx.Err() != context.Canceled || s.running {
		t.Fatal("pop did not cancel task")
	}
	done := make(chan struct{})
	go func() { r.shutdown(); close(done) }()
	select {
	case <-done:
		t.Fatal("shutdown did not wait for process exit")
	default:
	}
	close(s.task.exited)
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("shutdown stuck after process exit")
	}
}
