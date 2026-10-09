package main

import (
	"fmt"
	"math"
)

// Ordinary-note launch branch is immutable: acquisition/loss later does not
// select another launch profile. No random launch angle or motion integration.
type sakikoOrdinaryTurn struct{ weight float64 }

func newSakikoOrdinaryTurn(source OperatorSpec, hadTargetAtLaunch bool) (sakikoOrdinaryTurn, error) {
	if !validSkillRangedExemption(source.CharID, source.SkillRangedExemption) {
		return sakikoOrdinaryTurn{}, fmt.Errorf("祥子音符转向缺少精确模组来源")
	}
	weight := 7.0 / 30
	if hadTargetAtLaunch {
		weight = 1.0 / 6
	}
	return sakikoOrdinaryTurn{weight: weight}, nil
}

// One explicitly supplied frame of tracking. PRTS 弹道#转向速度 specifies a
// weighted direction and its example explicitly keeps the resulting magnitude.
// Do NOT renormalize current or output. Target direction alone is unit length.
func (p sakikoOrdinaryTurn) next(current, position, target [2]float64) ([2]float64, error) {
	if p.weight != 1.0/6 && p.weight != 7.0/30 {
		return [2]float64{}, fmt.Errorf("祥子普通音符转向分支非法")
	}
	for _, v := range [][2]float64{current, position, target} {
		for _, x := range v {
			if math.IsNaN(x) || math.IsInf(x, 0) {
				return [2]float64{}, fmt.Errorf("祥子音符转向向量非有限")
			}
		}
	}
	dx, dy := target[0]-position[0], target[1]-position[1]
	length := math.Hypot(dx, dy)
	if length == 0 || math.IsInf(length, 0) {
		return [2]float64{}, fmt.Errorf("祥子音符重合或溢出目标方向未定义，须先处理命中")
	}
	return [2]float64{current[0]*(1-p.weight) + dx/length*p.weight, current[1]*(1-p.weight) + dy/length*p.weight}, nil
}
