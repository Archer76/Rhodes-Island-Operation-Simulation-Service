package main

import (
	"fmt"
	"math"
)

// Ordinary no-target launch profile only: amplitude .3 and x-speed 1.3.
// Public 特殊机制#扩张正弦方向 defines local sin(x), first three periods.
// Sign is an explicit external random outcome, not an expected-value path.
type sakikoOrdinarySine struct {
	origin, axis [2]float64
	entered      float64
	sign         float64
}

func newSakikoOrdinarySine(source OperatorSpec, t float64, origin, direction [2]float64, positive bool) (sakikoOrdinarySine, error) {
	if !validSkillRangedExemption(source.CharID, source.SkillRangedExemption) {
		return sakikoOrdinarySine{}, fmt.Errorf("祥子正弦运动缺少精确模组来源")
	}
	if math.IsNaN(t) || math.IsInf(t, 0) || t < 0 {
		return sakikoOrdinarySine{}, fmt.Errorf("祥子正弦入态时间非法")
	}
	for _, v := range [][2]float64{origin, direction} {
		for _, x := range v {
			if math.IsNaN(x) || math.IsInf(x, 0) {
				return sakikoOrdinarySine{}, fmt.Errorf("祥子正弦坐标非法")
			}
		}
	}
	length := math.Hypot(direction[0], direction[1])
	if length == 0 || math.IsInf(length, 0) {
		return sakikoOrdinarySine{}, fmt.Errorf("祥子正弦方向未定义")
	}
	sign := -1.0
	if positive {
		sign = 1
	}
	return sakikoOrdinarySine{origin: origin, axis: [2]float64{direction[0] / length, direction[1] / length}, entered: t, sign: sign}, nil
}
func (p sakikoOrdinarySine) position(t float64) ([2]float64, error) {
	if p.sign != 1 && p.sign != -1 {
		return [2]float64{}, fmt.Errorf("祥子正弦随机分支未给定")
	}
	if math.IsNaN(t) || math.IsInf(t, 0) || t < p.entered {
		return [2]float64{}, fmt.Errorf("祥子正弦求值时间非法")
	}
	x := (t - p.entered) * 1.3
	if x > 6*math.Pi {
		return [2]float64{}, fmt.Errorf("祥子扩张正弦第三周期之后轨迹未证")
	}
	period := math.Min(3, math.Floor(x/(2*math.Pi))+1)
	y := p.sign * .3 * period * math.Sin(x)
	out := [2]float64{p.origin[0] + p.axis[0]*x - p.axis[1]*y, p.origin[1] + p.axis[1]*x + p.axis[0]*y}
	for _, v := range out {
		if math.IsNaN(v) || math.IsInf(v, 0) {
			return [2]float64{}, fmt.Errorf("祥子正弦位置溢出")
		}
	}
	return out, nil
}
