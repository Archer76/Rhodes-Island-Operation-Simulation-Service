package main

import (
	"context"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

// ulpiaLifecycleOp 造一名真实的乌尔比安操作员对象
func ulpiaLifecycleOp(t *testing.T, slot int, cell [2]int, dir string, modID string, modLvl int) *operator {
	t.Helper()
	st := &OperatorStats{
		CharID:      ulpiaCharID,
		Elite:       2,
		Level:       60,
		Potential:   1,
		Module:      modID,
		ModuleLevel: modLvl,
	}
	src, err := buildUlpiaSourceSpec(st, slot, 10)
	if err != nil {
		t.Fatalf("buildUlpiaSourceSpec slot %d: %v", slot, err)
	}
	if err := attachUlpiaSkillRange(src, dir, cell); err != nil {
		t.Fatalf("attachUlpiaSkillRange slot %d: %v", slot, err)
	}
	cfg, err := decodeUlpiaRuntimeConfig(src)
	if err != nil {
		t.Fatalf("decodeUlpiaRuntimeConfig: %v", err)
	}

	return &operator{
		hp:   6022,
		cell: [2]float64{float64(cell[0]), float64(cell[1])},
		spec: OperatorSpec{
			Name:        "乌尔比安",
			CharID:      ulpiaCharID,
			Cell:        cell,
			MaxHP:       6022,
			ATK:         1569,
			DEF:         0,
			RES:         0,
			BlockCnt:    2,
			AttackInterval: 2.5,
			DamageType:  "PHYSICAL",
			Range:       [][2]int{{cell[0], cell[1]}, {cell[0] + 1, cell[1]}},
			UlpiaSource: src,
		},
		ulpiaState: newUlpiaBattleState(cfg),
	}
}

// 判据一：乌尔比安规格闸门拒判验证（只要有未实现 Gap 如 force/位移/深海猎人光环，整场必定具名拒判）
func TestUlpiaRefusedByMechanismGaps(t *testing.T) {
	op := ulpiaLifecycleOp(t, 1, [2]int{0, 2}, "Right", "", 0)
	spec := &Spec{
		FPS:       30,
		MaxTime:   10,
		Operators: []OperatorSpec{op.spec},
		Deploys:   []DeploySpec{{Time: 0.0, CharID: ulpiaCharID, Index: 0}},
		Spawns: []SpawnSpec{{
			EnemyID: "test_dummy", Name: "靶", Time: 0,
			HP: 10000, ATK: 100, DEF: 0, RES: 0, MoveSpeed: 0.1, Interval: 2.0, DamageType: "PHYSICAL",
			Legs: []LegSpec{{Kind: "walk", Points: [][2]float64{{1, 2}, {0, 2}}, Length: 1.0}},
		}},
	}

	_, err := runSimContext(context.Background(), spec)
	if err == nil {
		t.Fatal("乌尔比安因存在未闭环位移等Gap，未发生拒判，违反零近似纪律")
	}
	var inc *mechanisms.IncompleteError
	if !errors.As(err, &inc) {
		t.Fatalf("expected IncompleteError, got %T: %v", err, err)
	}

	hasForceGap := false
	hasAuraGap := false
	for _, g := range inc.Placeholders {
		if g.CharID == ulpiaCharID && g.Key == "force" {
			hasForceGap = true
		}
		if g.CharID == ulpiaCharID && g.Key == "ulpia_t_1[abyssal].max_hp" {
			hasAuraGap = true
		}
	}
	if !hasForceGap || !hasAuraGap {
		t.Fatalf("拒判理由中缺少 force 或 abyssal 占位项: %v", inc.Placeholders)
	}
	t.Logf("成功按规范具名拒判: %v", err)
}

// 判据二：帧序内行使乌尔比安受击自愈（天赋一）与击倒敌人叠加属性（天赋二）
func TestUlpiaFrameWiringTalent1AndTalent2(t *testing.T) {
	op := ulpiaLifecycleOp(t, 2, [2]int{1, 1}, "Right", "", 0)
	verdict := &Verdict{}
	sim := &simCtx{verdict: verdict}
	simTime := 1.0
	sim.time = &simTime
	op.sim = sim

	// 1. 模拟受到伤害，断言触发 ulpia_talent1_heal 事件
	op.hp = 6000
	op.hurt(200) // 受到 200 伤害 -> 剩 5800 -> 触发自愈 100 -> 回到 5900
	if op.hp != 5900 {
		t.Fatalf("expected hp 5900 after hurt and talent1 heal, got %.1f", op.hp)
	}
	if countEvents(verdict, "ulpia_talent1_heal") != 1 {
		t.Fatalf("expected 1 ulpia_talent1_heal event, got %d", countEvents(verdict, "ulpia_talent1_heal"))
	}

	// 2. 模拟击倒敌人，调用 resolve 路径上的 ulpiaTalent2OnKill
	dummyEnemy := &enemy{
		hp:        0,
		lastHitBy: op,
		spec:      SpawnSpec{Name: "倒下的敌人"},
	}
	ulpiaTalent2OnKill(op, dummyEnemy, simTime, verdict)

	if op.ulpiaState.KillStack != 1 {
		t.Fatalf("expected kill stack 1, got %d", op.ulpiaState.KillStack)
	}
	if countEvents(verdict, "ulpia_talent2_stack") != 1 {
		t.Fatalf("expected 1 ulpia_talent2_stack event, got %d", countEvents(verdict, "ulpia_talent2_stack"))
	}
	// 验证生命上限与攻击力面板增长
	if op.maxHP() != 6022+120 {
		t.Fatalf("expected maxHP %v, got %v", 6022+120, op.maxHP())
	}
	if op.atk() != 1569+30 {
		t.Fatalf("expected atk %v, got %v", 1569+30, op.atk())
	}
}

// 判据三：技能二帧内激活与多阻挡行使
func TestUlpiaFrameWiringSkill2Active(t *testing.T) {
	op := ulpiaLifecycleOp(t, 2, [2]int{1, 1}, "Right", "", 0)
	verdict := &Verdict{}
	op.skillActive = true

	ulpiaTick([]*operator{op}, nil, 0.1, 5.0, verdict)

	if countEvents(verdict, "ulpia_s2_active") != 1 {
		t.Fatalf("expected ulpia_s2_active event on skill2 tick, got %d", countEvents(verdict, "ulpia_s2_active"))
	}
	// 阻挡数应从 2 提升至 3
	if limit := op.spec.BlockCnt + op.ulpiaBlockCntBonus(); limit != 3 {
		t.Fatalf("expected block limit 3 under skill 2, got %d", limit)
	}
}
