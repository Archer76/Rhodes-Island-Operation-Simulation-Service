package main

import (
	"context"
	"errors"
	"rios-sim/core"
	"runtime"
	"sync/atomic"
	"testing"
	"time"
)

func TestP1FirstThreeStarCancelsAndReapsSlowWorker(t *testing.T) {
	old := runtime.GOMAXPROCS(3)
	defer runtime.GOMAXPROCS(old)
	entered := make(chan struct{})
	exited := make(chan struct{})
	finished := make(chan struct{})
	var calls atomic.Int32
	var pool []scoredState
	var stats SolveStats
	go func() {
		pool, stats = evalDepthStreamingContext(context.Background(), progressStates(50), true,
			func(ctx context.Context, s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
				calls.Add(1)
				switch s[0].Operator {
				case "0":
					return nil, &Verdict{}, "", nil
				case "1":
					close(entered)
					<-ctx.Done()
					close(exited)
					return nil, nil, "canceled", ctx.Err()
				case "2":
					<-entered
					return &core.PlayPlan{Stage: "first-winner"}, &Verdict{Won: true, Life: 1}, "", nil
				default:
					<-ctx.Done()
					return nil, nil, "canceled", ctx.Err()
				}
			}, nil)
		close(finished)
	}()
	select {
	case <-finished:
	case <-time.After(3 * time.Second):
		t.Fatal("slow in-flight worker was not canceled/reaped")
	}
	select {
	case <-exited:
	default:
		t.Fatal("returned before worker exited")
	}
	if calls.Load() >= 50 || stats.Stars3 != 1 || stats.Canceled < 1 || stats.SimFailed != 0 || stats.FirstError != "" {
		t.Fatalf("bad cutoff accounting calls=%d stats=%+v", calls.Load(), stats)
	}
	if len(pool) != 2 || pool[1].plan.Stage != "first-winner" {
		t.Fatalf("wrong winner: %+v", pool)
	}
}

func TestP1LateBetterThreeStarCannotReplaceWinner(t *testing.T) {
	old := runtime.GOMAXPROCS(3)
	defer runtime.GOMAXPROCS(old)
	entered := make(chan struct{})
	pool, stats := evalDepthStreamingContext(context.Background(), progressStates(3), true,
		func(ctx context.Context, s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
			switch s[0].Operator {
			case "0":
				return nil, &Verdict{}, "", nil
			case "1":
				close(entered)
				<-ctx.Done()
				return &core.PlayPlan{Stage: "late-better"}, &Verdict{Won: true, Life: 9}, "", nil
			default:
				<-entered
				return &core.PlayPlan{Stage: "first"}, &Verdict{Won: true, Life: 1}, "", nil
			}
		}, nil)
	if stats.Stars3 != 1 || stats.Discarded != 1 || stats.Evaluated != 2 || len(pool) != 2 || pool[1].plan.Stage != "first" {
		t.Fatalf("late reranked: stats=%+v pool=%+v", stats, pool)
	}
}

func TestP1ParentCancelNotSimulationFailure(t *testing.T) {
	old := runtime.GOMAXPROCS(3)
	defer runtime.GOMAXPROCS(old)
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	pool, stats := evalDepthStreamingContext(ctx, progressStates(20), false,
		func(ctx context.Context, s []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
			if s[0].Operator == "0" {
				return nil, &Verdict{}, "", nil
			}
			cancel()
			<-ctx.Done()
			return nil, nil, "canceled", ctx.Err()
		}, nil)
	if len(pool) != 1 || stats.Canceled < 1 || stats.SimFailed != 0 || stats.FirstError != "" || stats.Stars3 != 0 {
		t.Fatalf("cancellation misclassified: %+v", stats)
	}
	canceled, c := context.WithCancel(context.Background())
	c()
	called := false
	_, stats = evalDepthStreamingContext(canceled, progressStates(2), true, func(context.Context, []CandidateRow) (*core.PlayPlan, *Verdict, string, error) {
		called = true
		return nil, nil, "", errors.New("must not run")
	}, nil)
	if called || stats.SimFailed != 0 {
		t.Fatal("pre-canceled layer evaluated")
	}
}
