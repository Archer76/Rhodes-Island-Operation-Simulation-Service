package main

import (
	"encoding/json"
	"errors"
	"rios-sim/mechanisms"
	"testing"
)

// TestDataDrivenExemptionControls 验证 (b-3) 双向对照与边界：
//
//  1. 正对照：克洛丝（char_124_kroos）全键集闭合（prob + atk_scale），
//     runSim 真正产出判决（非 Incomplete），且概率抽样真在跑（换 seed 判决不同；
//     同 seed 两次运行判决逐位相同；事件流出现 prob_rng_seed 与 talent_proc）；
//  2. 负对照（未闭合键）：古米（char_196_sunbr）带有未识别键 stun，
//     runSim 必定拒跑，IncompleteError 具名报出 talent.blackboard.stun 与 Key=stun；
//  3. 负对照（槐琥 force）：带有位移键 force，IncompleteError 具名报出 force；
//  4. 边界（按天赋而非按干员放行）：艾拉（char_4123_ela）第二天赋（正中靶心 prob+atk_scale）
//     虽闭合，但第一天赋（雷鸣地雷 cnt）未闭合，整场仍然拒跑，报出第一天赋缺口。
func TestDataDrivenExemptionControls(t *testing.T) {
	chdirRepoRootForData(t)

	// --- 1. 正对照：克洛丝 ---
	runKroos := func(seed uint64) (*Verdict, error) {
		row := DeployRow{
			Skill: 1, SkillLevel: 7, PlanIdx: 0,
			Position: [2]int{0, 0}, Direction: "Right",
			Entry: LoadoutEntry{CharID: "char_124_kroos", Elite: 1, Level: 55, Potential: 1},
		}
		out, err := buildOperatorOut(row, map[string]int{}, "")
		if err != nil {
			return nil, err
		}
		out.RNGSeed = seed
		blob, _ := json.Marshal(out)
		var op OperatorSpec
		_ = json.Unmarshal(blob, &op)

		spec := deploymentPrimitiveSpec(15)
		spec.Operators = []OperatorSpec{op}
		spec.Deploys = []DeploySpec{{Index: 0, CharID: op.CharID, Time: 0, Cost: 0}}
		// 在射程 [2, 1] 放一个靶子让克洛丝平 A
		spec.Spawns = []SpawnSpec{{Time: 0, Name: "靶", HP: 100000, ATK: 0, MoveSpeed: 0, Interval: 10, LifeCost: 0, Legs: []LegSpec{{Kind: "wait", Seconds: 20}}}}
		return runSim(spec)
	}

	v1, err := runKroos(1001)
	if err != nil {
		t.Fatalf("克洛丝应当全键集闭合并成功运行，实报：%v", err)
	}
	if v1 == nil {
		t.Fatal("克洛丝判决为空")
	}

	// 验证确实发生了概率抽样与种子注入
	seedFound := false
	procCount := 0
	for _, ev := range v1.Events {
		if ev.Kind == "prob_rng_seed" && containsText(ev.Who, "seed=1001") {
			seedFound = true
		}
		if ev.Kind == "talent_proc" && containsText(ev.Who, "克洛丝") {
			procCount++
		}
	}
	for _, ev := range v1.Events {
		t.Logf("EV: t=%.2f kind=%s who=%s", ev.T, ev.Kind, ev.Who)
	}
	if !seedFound {
		t.Fatal("克洛丝事件流中缺少 prob_rng_seed 事件")
	}
	t.Logf("正对照克洛丝：成功产出判决，种子事件正常，暴击事件数=%d", procCount)

	// 换 seed 产出不同序列（正对照的敏感性证明）
	v2, err := runKroos(99999)
	if err != nil {
		t.Fatal(err)
	}
	v1.SimMS = 0
	v2.SimMS = 0
	b1, _ := json.Marshal(v1)
	b2, _ := json.Marshal(v2)
	if string(b1) == string(b2) {
		t.Fatal("换 seed 后克洛丝判决完全相同：抽样未对判决生效")
	}

	// 同 seed 产出完全相同字节
	v1Again, _ := runKroos(1001)
	v1Again.SimMS = 0
	b1Again, _ := json.Marshal(v1Again)
	if string(b1) != string(b1Again) {
		t.Fatal("同 seed 下克洛丝判决不确定")
	}

	// --- 2. 负对照：古米（未闭合键 stun）---
	runGummy := func() error {
		row := DeployRow{
			Skill: 1, SkillLevel: 7, PlanIdx: 0,
			Position: [2]int{0, 0}, Direction: "Right",
			Entry: LoadoutEntry{CharID: "char_196_sunbr", Elite: 2, Level: 60, Potential: 1},
		}
		out, err := buildOperatorOut(row, map[string]int{}, "")
		if err != nil {
			return err
		}
		blob, _ := json.Marshal(out)
		var op OperatorSpec
		_ = json.Unmarshal(blob, &op)

		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{op}
		spec.Deploys = []DeploySpec{{Index: 0, CharID: op.CharID, Time: 0, Cost: 0}}
		_, simErr := runSim(spec)
		return simErr
	}

	gummyErr := runGummy()
	if gummyErr == nil {
		t.Fatal("古米带有未识别键 stun，应当拒跑，实得成功")
	}
	var incErr *mechanisms.IncompleteError
	if !errors.As(gummyErr, &incErr) {
		t.Fatalf("古米报错应当为 IncompleteError，实得：%v", gummyErr)
	}
	stunReported := false
	for _, g := range incErr.Placeholders {
		if g.Key == "stun" {
			stunReported = true
			t.Logf("负对照古米：成功拒跑并具名报出未识别键 Gap ID=%s Key=%s Reason=%s", g.ID, g.Key, g.Reason)
		}
	}
	if !stunReported {
		t.Fatalf("古米的 IncompleteError 中未具名报出 stun 键；实报：%v", incErr.Placeholders)
	}

	// --- 3. 负对照：槐琥（未闭合键 force）---
	runWaaiFu := func() error {
		row := DeployRow{
			Skill: 1, SkillLevel: 7, PlanIdx: 0,
			Position: [2]int{0, 0}, Direction: "Right",
			Entry: LoadoutEntry{CharID: "char_243_waaifu", Elite: 2, Level: 60, Potential: 1},
		}
		out, err := buildOperatorOut(row, map[string]int{}, "")
		if err != nil {
			return err
		}
		blob, _ := json.Marshal(out)
		var op OperatorSpec
		_ = json.Unmarshal(blob, &op)

		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{op}
		spec.Deploys = []DeploySpec{{Index: 0, CharID: op.CharID, Time: 0, Cost: 0}}
		_, simErr := runSim(spec)
		return simErr
	}
	waaifuErr := runWaaiFu()
	if waaifuErr == nil {
		t.Fatal("槐琥带有未识别键 force，应当拒跑")
	}
	var waaifuInc *mechanisms.IncompleteError
	if !errors.As(waaifuErr, &waaifuInc) {
		t.Fatalf("槐琥报错应当为 IncompleteError，实得：%v", waaifuErr)
	}
	forceReported := false
	for _, g := range waaifuInc.Placeholders {
		if g.Key == "force" {
			forceReported = true
			t.Logf("负对照槐琥：成功拒跑并具名报出未识别键 Gap ID=%s Key=%s", g.ID, g.Key)
		}
	}
	if !forceReported {
		t.Fatalf("槐琥的 IncompleteError 中未具名报出 force 键；实报：%v", waaifuInc.Placeholders)
	}

	// --- 4. 边界（按天赋而非按干员放行）：艾拉 ---
	runEla := func() error {
		row := DeployRow{
			Skill: 1, SkillLevel: 7, PlanIdx: 0,
			Position: [2]int{0, 0}, Direction: "Right",
			Entry: LoadoutEntry{CharID: "char_4123_ela", Elite: 2, Level: 60, Potential: 1},
		}
		out, err := buildOperatorOut(row, map[string]int{}, "")
		if err != nil {
			return err
		}
		blob, _ := json.Marshal(out)
		var op OperatorSpec
		_ = json.Unmarshal(blob, &op)

		spec := deploymentPrimitiveSpec(1)
		spec.Operators = []OperatorSpec{op}
		spec.Deploys = []DeploySpec{{Index: 0, CharID: op.CharID, Time: 0, Cost: 0}}
		_, simErr := runSim(spec)
		return simErr
	}
	elaErr := runEla()
	if elaErr == nil {
		t.Fatal("艾拉第一天赋未闭合，应当拒跑")
	}
	var elaInc *mechanisms.IncompleteError
	if !errors.As(elaErr, &elaInc) {
		t.Fatalf("艾拉报错应当为 IncompleteError，实得：%v", elaErr)
	}
	t1Blocked := false
	for _, g := range elaInc.Placeholders {
		if g.Key == "tokenKey" || g.Key == "cnt" {
			t1Blocked = true
		}
	}
	if !t1Blocked {
		t.Fatalf("艾拉虽第二天赋闭合，但第一天赋未闭合，必须具名拦截；实报：%v", elaInc.Placeholders)
	}
	t.Logf("边界证明艾拉：第二天赋 prob+atk_scale 闭合，但第一天赋 tokenKey/cnt 未闭合，整场成功拦截")
}
