package main

import (
	"fmt"
	"math"
)

// Doctor ruling: game battle logic is fixed at 30 Hz. Presentation / wall-clock
// speed must not change integration or per-frame effect semantics.
const gameLogicFPS = 30
const gameLogicDT = 1.0 / gameLogicFPS

// Round half up for nonnegative skill intervals, not ceil or ties-to-even.
// Zero is retained rather than inventing a one-frame minimum.
func skillIntervalFrames(seconds float64) (int64, error) {
	if math.IsNaN(seconds) || math.IsInf(seconds, 0) || seconds < 0 {
		return 0, fmt.Errorf("技能间隔必须为有限非负秒数")
	}
	frames := math.Round(seconds * gameLogicFPS)
	if frames >= float64(math.MaxInt64) {
		return 0, fmt.Errorf("技能间隔帧数溢出")
	}
	return int64(frames), nil
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
