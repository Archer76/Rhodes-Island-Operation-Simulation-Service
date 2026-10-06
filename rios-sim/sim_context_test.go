package main

import (
	"context"
	"errors"
	"reflect"
	"testing"

	"rios-sim/mechanisms"
)

// A normal, fully supported synthetic battle; no business DB or gamedata is
// needed. The future spawn keeps multiple frames running, and deployment on the
// first frame gives the cancelled run a real event that must not escape.
func simContextTinyFixture() *Spec {
	s := deploymentPrimitiveSpec(1)
	s.FPS = 4
	addDeploymentPrimitive(s, "context-unit", "context unit", [2]int{0, 0}, 0, 0)
	return s
}

// Cancellation is driven by checks, not goroutines, sleeps, or wall-clock timing.
// Embedding a real cancellable context also preserves Done/Err consistency.
type simCancelAfterChecks struct {
	context.Context
	cancel   context.CancelFunc
	checks   int
	cancelAt int
}

func (c *simCancelAfterChecks) Err() error {
	c.checks++
	if c.checks >= c.cancelAt {
		c.cancel()
	}
	return c.Context.Err()
}

func TestRunSimContextPreCancelled(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	v, err := runSimContext(ctx, simContextTinyFixture())
	if v != nil || err != context.Canceled {
		t.Fatalf("verdict=%+v err=%v; want nil, context.Canceled", v, err)
	}
	// The entry check must precede any access to spec, even its validation.
	v, err = runSimContext(ctx, nil)
	if v != nil || err != context.Canceled {
		t.Fatalf("entry verdict=%+v err=%v", v, err)
	}
}

func TestRunSimContextDeterministicCancellation(t *testing.T) {
	for _, tc := range []struct {
		name     string
		cancelAt int
	}{
		{"before-mechanism-start", 2},
		{"after-mechanism-start", 3},
		{"first-frame-top", 4},
		// Checks 4 and 5 allow two frames (including deployment) to complete;
		// check 6 must abort before a third frame and discard the partial verdict.
		{"during-simulation", 6},
	} {
		t.Run(tc.name, func(t *testing.T) {
			base, cancel := context.WithCancel(context.Background())
			defer cancel()
			ctx := &simCancelAfterChecks{Context: base, cancel: cancel, cancelAt: tc.cancelAt}
			v, err := runSimContext(ctx, simContextTinyFixture())
			if v != nil || err != context.Canceled {
				t.Fatalf("verdict=%+v err=%v; want nil, context.Canceled", v, err)
			}
			if ctx.checks != tc.cancelAt {
				t.Fatalf("checks=%d; want %d", ctx.checks, tc.cancelAt)
			}
		})
	}
}

func TestRunSimContextBackgroundMatchesWrapper(t *testing.T) {
	got, err := runSimContext(context.Background(), simContextTinyFixture())
	if err != nil {
		t.Fatal(err)
	}
	want, err := runSim(simContextTinyFixture())
	if err != nil {
		t.Fatal(err)
	}
	if got == nil || want == nil || !got.TimedOut || len(got.Events) == 0 || got.Elapsed < 1 {
		t.Fatalf("tiny fixture did not exercise frames and deployment: got=%+v want=%+v", got, want)
	}
	// SimMS measures runtime, not battle semantics.
	got.SimMS, want.SimMS = 0, 0
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("background verdict=%+v; wrapper verdict=%+v", got, want)
	}
}

func TestRunSimContextPreservesPlaceholderRefusal(t *testing.T) {
	s := simContextTinyFixture()
	s.Placeholders = []mechanisms.Gap{{ID: "context-test-missing", Status: "unimplemented", Source: "skill", Reason: "not built"}}
	for _, run := range []func(*Spec) (*Verdict, error){
		runSim,
		func(s *Spec) (*Verdict, error) { return runSimContext(context.Background(), s) },
	} {
		v, err := run(s)
		var incomplete *mechanisms.IncompleteError
		if v != nil || !errors.As(err, &incomplete) || !reflect.DeepEqual(incomplete.Placeholders, s.Placeholders) {
			t.Fatalf("placeholder refusal changed: verdict=%+v err=%v", v, err)
		}
	}
}
