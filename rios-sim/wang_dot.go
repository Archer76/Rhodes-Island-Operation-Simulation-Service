package main

import "fmt"

// Each S1 application owns a snapshotted amount and independent schedule.
// FIRST TICK IS PROVISIONAL: Doctor requested immediate on 2026-10-08 pending
// measurement. This flag is evidence metadata, not a claim of verified timing.
type wangDOT struct {
	TargetID           int
	Start              float64
	Duration           float64
	Damage             float64
	NextTick           int
	ImmediateFirstTick bool
}

func newWangDOT(target int, start, duration, damage float64) (wangDOT, error) {
	if duration <= 0 || damage < 0 {
		return wangDOT{}, fmt.Errorf("invalid wang DOT payload")
	}
	return wangDOT{TargetID: target, Start: start, Duration: duration, Damage: damage, ImmediateFirstTick: true}, nil
}

// Consume integer-second events, not DPS*dt. Catch-up emits every elapsed event
// exactly once. End is exclusive: 6.5 seconds with an immediate first tick has
// ticks at 0,1,2,3,4,5,6; no invented half tick at expiration.
func (d *wangDOT) due(now float64) []float64 {
	var ticks []float64
	for {
		offset := float64(d.NextTick)
		if !d.ImmediateFirstTick {
			offset++
		}
		if offset >= d.Duration || d.Start+offset > now {
			break
		}
		ticks = append(ticks, d.Start+offset)
		d.NextTick++
	}
	return ticks
}
