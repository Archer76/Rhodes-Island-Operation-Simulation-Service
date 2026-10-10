package mech

import (
	"encoding/json"
	"math"
	"rios-sim/timing"
	"testing"
)

type clockMechCtx struct {
	Ctx     // Any unexpected request panics instead of silently passing.
	frame   int
	enemies []EnemyView
	hits    int
	heals   int
}

func (c *clockMechCtx) Time() float64        { return float64(c.frame) * timing.DT }
func (c *clockMechCtx) Now() float64         { return c.Time() }
func (c *clockMechCtx) Frame() int           { return c.frame }
func (c *clockMechCtx) DT() float64          { return timing.DT }
func (c *clockMechCtx) Enemies() []EnemyView { return c.enemies }
func (c *clockMechCtx) Operators() []OpView {
	return []OpView{{Index: 0, Alive: true, HP: 1000, MaxHP: 1000, Cell: [2]int{3, 1}, BlockCnt: 1}}
}
func (c *clockMechCtx) EnemyWindup() float64                     { return 0 }
func (c *clockMechCtx) PauseEnemy(int, float64)                  {}
func (c *clockMechCtx) HitOperator(int, float64, string) float64 { c.hits++; return 1 }
func (c *clockMechCtx) HealOperator(int, float64)                { c.heals++ }
func (c *clockMechCtx) Trace(string, ...any)                     {}
func farmlandClockMech(t *testing.T) *farmlandMech {
	t.Helper()
	var s FarmlandSpec
	if e := json.Unmarshal([]byte(goldenSpecJSON), &s); e != nil {
		t.Fatal(e)
	}
	f, e := NewFarmland(&s)
	if e != nil {
		t.Fatal(e)
	}
	return &farmlandMech{field: f}
}
func TestEnemySkillFrameFirstAndRepeatRounded(t *testing.T) {
	m := farmlandClockMech(t)
	c := &clockMechCtx{enemies: []EnemyView{{Index: 0, Alive: true, ATK: 1, Cell: [2]int{2, 4}, SkillAtkScalePhys: 1, SkillAtkInit: .78, SkillAtkInterval: .75}}}
	for i := 1; i <= 46; i++ {
		c.frame = i - 1
		if err := m.AttackTickFrame(c); err != nil {
			t.Fatal(err)
		}
		want := 0
		if i >= 23 {
			want = 1
		}
		if i >= 46 {
			want = 2
		}
		if c.hits != want {
			t.Fatalf("update=%d hits=%d want=%d", i, c.hits, want)
		}
	}
	c.enemies[0].SkillAtkInit = math.NaN()
	before := c.hits
	if err := m.AttackTickFrame(c); err == nil || c.hits != before {
		t.Fatal("invalid first interval accepted or produced side effect")
	}
}
func TestFarmlandEnvironmentFrameBoundary(t *testing.T) {
	m := farmlandClockMech(t)
	c := &clockMechCtx{}
	for i := 1; i <= 30; i++ {
		c.frame = i - 1
		m.EnvTickFrame(c)
		want := 0
		if i == 30 {
			want = 1
		}
		if c.heals != want {
			t.Fatalf("update=%d heals=%d want=%d", i, c.heals, want)
		}
	}
}
