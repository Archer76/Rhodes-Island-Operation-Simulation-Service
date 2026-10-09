package main

import (
	"testing"
)

func TestChen3QiMovementAndTurning(t *testing.T) {
	// 地图模拟：在 (2, 0) 处有障碍
	walkable := func(x, y int) bool {
		if x == 2 && y == 0 {
			return false // 前方障碍
		}
		return true
	}

	qi := newChen3Qi("chen3", Cell{0, 0}, "Right", 1000, 5.8, 0.06, 1.0)
	e1 := &enemy{index: 1, position: [2]float64{1, 0}, hp: 10000}
	enemies := []*enemy{e1}

	// 走 1 秒，到达 (1, 0)，命中 e1
	events, err := qi.Tick(1.0, walkable, enemies, 1.0)
	if err != nil {
		t.Fatalf("Tick failed: %v", err)
	}
	if len(events) != 1 {
		t.Fatalf("expected 1 hit on e1, got %d", len(events))
	}
	// e1 受到伤害：max(10000*0.06=600, 1000*5.8=5800) = 5800
	if events[0].Damage != 5800 {
		t.Fatalf("expected damage 5800, got %v", events[0].Damage)
	}

	// 再走 1 秒，遇到 (2, 0) 障碍，向右拐弯 (dx=0, dy=1) 并继续前进
	events2, err := qi.Tick(1.0, walkable, enemies, 2.0)
	if err != nil {
		t.Fatalf("Tick 2 failed: %v", err)
	}
	if qi.DX != 0 || qi.DY != 1 {
		t.Fatalf("expected turned down (0, 1), got (%d, %d)", qi.DX, qi.DY)
	}
	// 转弯后命中集合已刷新
	if len(qi.Hit) != 0 {
		t.Fatalf("expected hit set cleared on turn")
	}
	_ = events2
}
