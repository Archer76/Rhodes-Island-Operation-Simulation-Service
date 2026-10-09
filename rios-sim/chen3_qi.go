package main

import (
	"fmt"
	"math"
)

// Direction to coordinate step: (dx, dy)
// MAA convention: Right is (+1, 0), Left is (-1, 0), Up is (0, -1), Down is (0, 1)
func dirToDelta(dir string) (int, int) {
	switch dir {
	case "Right":
		return 1, 0
	case "Left":
		return -1, 0
	case "Up":
		return 0, -1
	case "Down":
		return 0, 1
	default:
		return 1, 0
	}
}

// Right turn: (dx, dy) -> (-dy, dx)
func rotateRight(dx, dy int) (int, int) {
	return -dy, dx
}

type chen3Qi struct {
	Owner       string
	Atk         float64
	MinAtkScale float64
	HPRatio     float64
	Speed       float64 // 1.2
	X           float64
	Y           float64
	DX          int
	DY          int
	Hit         map[int]bool // enemy index -> hit during current straight segment
}

func newChen3Qi(owner string, pos Cell, dir string, atk, minAtkScale, hpRatio, speed float64) *chen3Qi {
	dx, dy := dirToDelta(dir)
	return &chen3Qi{
		Owner:       owner,
		Atk:         atk,
		MinAtkScale: minAtkScale,
		HPRatio:     hpRatio,
		Speed:       speed,
		X:           float64(pos[0]),
		Y:           float64(pos[1]),
		DX:          dx,
		DY:          dy,
		Hit:         make(map[int]bool),
	}
}

type chen3QiDamageEvent struct {
	EnemyIndex int
	Damage     float64
	Now        float64
}

// Tick moves qi, turns right when blocked, and collects hits
func (q *chen3Qi) Tick(dt float64, walkable func(x, y int) bool, enemies []*enemy, now float64) ([]chen3QiDamageEvent, error) {
	if dt < 0 {
		return nil, fmt.Errorf("invalid dt for chen3 qi")
	}
	step := q.Speed * dt
	remain := step
	var events []chen3QiDamageEvent

	for remain > 0 {
		move := math.Min(remain, 1.0)
		nx := q.X + float64(q.DX)*move
		ny := q.Y + float64(q.DY)*move

		tx := int(math.Round(nx))
		ty := int(math.Round(ny))

		if walkable != nil && !walkable(tx, ty) {
			// 前方不可走，向右转弯（最多试4次防死循环）
			turned := false
			curDX, curDY := q.DX, q.DY
			for i := 0; i < 4; i++ {
				curDX, curDY = rotateRight(curDX, curDY)
				if walkable(int(math.Round(q.X))+curDX, int(math.Round(q.Y))+curDY) {
					q.DX = curDX
					q.DY = curDY
					q.Hit = make(map[int]bool) // 拐弯刷新命中记录！
					turned = true
					break
				}
			}
			if !turned {
				// 四周皆不可走，停留在原处
				remain = 0
				break
			}
			remain -= move
			continue
		}

		q.X = nx
		q.Y = ny
		remain -= move

		// 检查穿过的敌人
		curCell := Cell{int(math.Round(q.X)), int(math.Round(q.Y))}
		for _, e := range enemies {
			if e == nil || e.hp <= 0 || e.leaked {
				continue
			}
			ex, ey := e.cell()
			if ex == curCell[0] && ey == curCell[1] {
				if !q.Hit[e.index] {
					q.Hit[e.index] = true
					// 伤害：相当于其当前生命值 hp_ratio 的法术伤害，保底自身攻击力 min_atk_scale
					hpDmg := e.hp * q.HPRatio
					minDmg := q.Atk * q.MinAtkScale
					dmg := math.Max(hpDmg, minDmg)
					events = append(events, chen3QiDamageEvent{
						EnemyIndex: e.index,
						Damage:     dmg,
						Now:        now,
					})
				}
			}
		}
	}

	return events, nil
}
