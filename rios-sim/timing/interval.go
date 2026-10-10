package timing

import (
	"fmt"
	"math"
)

// SkillFrames implements the explicit ruling for both allied and enemy skill
// first/repeated intervals. This is not the policy for durations or SP.
func SkillFrames(seconds float64) (int64, error) {
	if math.IsNaN(seconds) || math.IsInf(seconds, 0) || seconds < 0 {
		return 0, fmt.Errorf("技能间隔必须为有限非负秒数")
	}
	n := math.Round(seconds * FPS)
	if n >= float64(math.MaxInt64) {
		return 0, fmt.Errorf("技能间隔帧数溢出")
	}
	return int64(n), nil
}
