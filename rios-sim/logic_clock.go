package main

import (
	"fmt"
	"rios-sim/timing"
)

// Doctor ruling: game battle logic is fixed at 30 Hz. Presentation / wall-clock
// speed must not change integration or per-frame effect semantics.
const gameLogicFPS = 30
const gameLogicDT = 1.0 / gameLogicFPS

// Round half up for nonnegative skill intervals, not ceil or ties-to-even.
// Zero is retained rather than inventing a one-frame minimum.
func skillIntervalFrames(seconds float64) (int64, error) {
	return timing.SkillFrames(seconds)
}
func quantizedSkillInterval(seconds float64) (float64, error) {
	frames, err := skillIntervalFrames(seconds)
	if err != nil {
		return 0, err
	}
	return float64(frames) / gameLogicFPS, nil
}

func validateLogicFPS(fps int) error {
	if fps != gameLogicFPS {
		return fmt.Errorf("战斗逻辑帧固定为30帧/秒，收到fps=%d；不能改变逻辑步长", fps)
	}
	return nil
}
