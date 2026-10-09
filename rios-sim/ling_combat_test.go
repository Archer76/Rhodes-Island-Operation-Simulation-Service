package main

import (
	"math"
	"testing"
)

func TestLingDeploymentAndFusion(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{CharID: lingCharID, Elite: 2, Level: 90, Potential: 1}
	spec, err := buildLingSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLingSourceSpec failed: %v", err)
	}
	cfg, err := decodeLingRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeLingRuntimeConfig failed: %v", err)
	}

	state := newLingDeploymentState("ling_inst_1", cfg)
	cost := 100.0
	squadSlots := 10

	// 1. 部署第 1 只弦惊在 (2, 2)，朝向 Right
	c1 := LingDeploymentCell{
		Position:       Cell{2, 2},
		MapKnown:       true,
		Deployable:     true,
		OccupancyKnown: true,
		IsHighland:     false,
	}
	tok1, fused1, err := state.DeployToken(1.0, c1, LingDirRight, &cost, &squadSlots)
	if err != nil {
		t.Fatalf("deploy token 1 failed: %v", err)
	}
	if fused1 != nil {
		t.Errorf("token 1 should not trigger fusion")
	}
	if tok1.Form != LingFormNormal || tok1.DeploySlots != 1 {
		t.Errorf("token 1 form or deploySlots wrong: form=%v, slots=%v", tok1.Form, tok1.DeploySlots)
	}
	if state.ActiveTokenCount() != 1 || state.TotalDeploySlotsUsed() != 1 {
		t.Errorf("active tokens / slots mismatch: count=%d, slots=%d", state.ActiveTokenCount(), state.TotalDeploySlotsUsed())
	}

	// 2. 在 (3, 2) 部署第 2 只弦惊，恰好在 tok1 的正前方 (tok1 朝向 Right) -> 触发合体！
	c2 := LingDeploymentCell{
		Position:       Cell{3, 2},
		MapKnown:       true,
		Deployable:     true,
		OccupancyKnown: true,
		IsHighland:     false,
	}
	tok2, fused2, err := state.DeployToken(2.0, c2, LingDirUp, &cost, &squadSlots)
	if err != nil {
		t.Fatalf("deploy token 2 (fusion) failed: %v", err)
	}
	if fused2 == nil {
		t.Fatalf("token 2 should trigger fusion")
	}
	if fused2 != tok1 {
		t.Errorf("fused target should be tok1")
	}
	if tok1.Form != LingFormFused || tok1.DeploySlots != 2 {
		t.Errorf("tok1 did not become fused form with 2 slots: form=%v slots=%v", tok1.Form, tok1.DeploySlots)
	}
	_ = tok2
	// 场上依然只有 1 个实体（融合），但总部署位占用变为 2
	if state.ActiveTokenCount() != 1 || state.TotalDeploySlotsUsed() != 2 {
		t.Errorf("post-fusion count or slots mismatch: count=%d, slots=%d", state.ActiveTokenCount(), state.TotalDeploySlotsUsed())
	}
	// 属性翻倍与阻挡数提升验证
	if tok1.BlockCnt != cfg.TokenBlockCnt+cfg.FusionBlockBonus {
		t.Errorf("fused block count expected %d, got %d", cfg.TokenBlockCnt+cfg.FusionBlockBonus, tok1.BlockCnt)
	}
}

func TestLingCombatTalentAndSkills(t *testing.T) {
	chdirRepoRootForData(t)

	st := &OperatorStats{CharID: lingCharID, Elite: 2, Level: 90, Potential: 1}
	spec, err := buildLingSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildLingSourceSpec failed: %v", err)
	}
	cfg, err := decodeLingRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeLingRuntimeConfig failed: %v", err)
	}

	combat := newLingCombatState("ling_inst_1", cfg, 500.0, 40.0, 15.0)
	cost := 100.0
	squadSlots := 10

	// 部署一只弦惊
	c1 := LingDeploymentCell{
		Position:       Cell{1, 1},
		MapKnown:       true,
		Deployable:     true,
		OccupancyKnown: true,
		IsHighland:     false,
	}
	tok, _, err := combat.Deployment.DeployToken(1.0, c1, LingDirUp, &cost, &squadSlots)
	if err != nil {
		t.Fatalf("deploy token failed: %v", err)
	}

	// 验证第二天赋：击倒召唤物时 SP +3，攻击力叠 1 层 (+3%)
	initSP := combat.SkillSP
	combat.NotifyTokenRemoval(tok, LingRecycleDefeated, &squadSlots)
	if combat.Talent2Stacks != 1 {
		t.Errorf("expected 1 talent stack, got %d", combat.Talent2Stacks)
	}
	if combat.SkillSP != initSP+cfg.Talent2SP {
		t.Errorf("expected SP %v, got %v", initSP+cfg.Talent2SP, combat.SkillSP)
	}
	if squadSlots != 10 {
		t.Errorf("squad slots should be restored to 10, got %d", squadSlots)
	}

	// 开启技3：攻击力与防御力提升
	combat.SkillSP = 40.0
	if err := combat.TriggerSkill(5.0, nil, nil); err != nil {
		t.Fatalf("trigger S3 failed: %v", err)
	}
	if !combat.SkillActive {
		t.Errorf("expected skill active")
	}
	effectiveAtk := combat.EffectiveOwnerAtk()
	// 基础 500 * (1 + 0.03 (叠1层) + 1.0 (S3 buff)) = 500 * 2.03 = 1015
	if math.Abs(effectiveAtk-500.0*2.03) > 1e-6 {
		t.Errorf("expected effective atk 1015, got %v", effectiveAtk)
	}

	// 模拟 30 秒技能结束，获得 1 个召唤物
	invBefore := combat.Deployment.Inventory
	combat.TickCombatFrame(31.0, 36.0, nil, &squadSlots, nil)
	if combat.SkillActive {
		t.Errorf("skill should have ended")
	}
	if combat.Deployment.Inventory != invBefore+1 {
		t.Errorf("inventory should have gained 1 after S3, got %d (before: %d)", combat.Deployment.Inventory, invBefore)
	}
}
