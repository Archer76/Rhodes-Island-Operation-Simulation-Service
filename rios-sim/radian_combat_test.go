package main

import (
	"testing"
)

func TestRadianSourceSpecExtraction(t *testing.T) {
	st := &OperatorStats{
		CharID:    radianCharID,
		Elite:     2,
		Level:     90,
		Potential: 1,
	}

	// 1. 测试技能三（手牵手）+ 潜能 1
	spec, err := buildRadianSourceSpec(st, 3, 10)
	if err != nil {
		t.Fatalf("buildRadianSourceSpec failed: %v", err)
	}
	if spec.TokenKey != radianTokenTower3 {
		t.Errorf("expected TokenKey %s, got %s", radianTokenTower3, spec.TokenKey)
	}
	if spec.OperatorSkill.ID != "skchr_radian_3" {
		t.Errorf("expected skill skchr_radian_3, got %s", spec.OperatorSkill.ID)
	}
	if spec.TokenSkill.ID != "sktok_radian_3" {
		t.Errorf("expected token skill sktok_radian_3, got %s", spec.TokenSkill.ID)
	}
	if len(spec.Talents) != 2 {
		t.Fatalf("expected 2 talents, got %d", len(spec.Talents))
	}

	cfg, err := decodeRadianRuntimeConfig(spec)
	if err != nil {
		t.Fatalf("decodeRadianRuntimeConfig failed: %v", err)
	}

	// 验证第一天赋库存：精2为 5
	if cfg.InventoryMax != 5 {
		t.Errorf("expected InventoryMax 5, got %d", cfg.InventoryMax)
	}
	if cfg.FieldMax != 3 {
		t.Errorf("expected FieldMax 3, got %d", cfg.FieldMax)
	}

	// 验证第二天赋加成（潜1：12%）
	if mathAbs(cfg.Talent2HpRatio-0.12) > 1e-4 {
		t.Errorf("expected Talent2HpRatio 0.12, got %.4f", cfg.Talent2HpRatio)
	}
	if mathAbs(cfg.Talent2AtkRatio-0.12) > 1e-4 {
		t.Errorf("expected Talent2AtkRatio 0.12, got %.4f", cfg.Talent2AtkRatio)
	}
	if mathAbs(cfg.Talent2DefRatio-0.12) > 1e-4 {
		t.Errorf("expected Talent2DefRatio 0.12, got %.4f", cfg.Talent2DefRatio)
	}

	// 验证技能三数值 (专三 Lv10)
	// atk: 1.5, damage_scale: 1.35, sluggish: 2.0, weak[magic][limit]: 2.0, cnt: 1.0
	if mathAbs(cfg.S3AtkBuff-1.5) > 1e-4 {
		t.Errorf("expected S3AtkBuff 1.5, got %.4f", cfg.S3AtkBuff)
	}
	if mathAbs(cfg.S3DamageScale-1.35) > 1e-4 {
		t.Errorf("expected S3DamageScale 1.35, got %.4f", cfg.S3DamageScale)
	}
	if mathAbs(cfg.S3SluggishDuration-2.0) > 1e-4 {
		t.Errorf("expected S3SluggishDuration 2.0, got %.4f", cfg.S3SluggishDuration)
	}
	if mathAbs(cfg.S3MagicFragileDuration-2.0) > 1e-4 {
		t.Errorf("expected S3MagicFragileDuration 2.0, got %.4f", cfg.S3MagicFragileDuration)
	}
	if cfg.S3SupplyCnt != 1 {
		t.Errorf("expected S3SupplyCnt 1, got %d", cfg.S3SupplyCnt)
	}

	// 2. 潜能 5 测试（第二天赋提升至 15%）
	stPot5 := &OperatorStats{
		CharID:    radianCharID,
		Elite:     2,
		Level:     90,
		Potential: 5,
	}
	specPot5, err := buildRadianSourceSpec(stPot5, 3, 10)
	if err != nil {
		t.Fatalf("buildRadianSourceSpec Pot5 failed: %v", err)
	}
	cfgPot5, err := decodeRadianRuntimeConfig(specPot5)
	if err != nil {
		t.Fatalf("decodeRadianRuntimeConfig Pot5 failed: %v", err)
	}
	if mathAbs(cfgPot5.Talent2HpRatio-0.15) > 1e-4 {
		t.Errorf("expected Pot5 Talent2HpRatio 0.15, got %.4f", cfgPot5.Talent2HpRatio)
	}
	if mathAbs(cfgPot5.Talent2AtkRatio-0.15) > 1e-4 {
		t.Errorf("expected Pot5 Talent2AtkRatio 0.15, got %.4f", cfgPot5.Talent2AtkRatio)
	}

	// 3. 技能一测试 (专三 Lv10)
	// def: 0.8, hp_ratio: 1.0, cnt: 1.0
	spec1, err := buildRadianSourceSpec(st, 1, 10)
	if err != nil {
		t.Fatalf("buildRadianSourceSpec S1 failed: %v", err)
	}
	if spec1.TokenKey != radianTokenTower1 {
		t.Errorf("expected S1 TokenKey %s, got %s", radianTokenTower1, spec1.TokenKey)
	}
	cfg1, err := decodeRadianRuntimeConfig(spec1)
	if err != nil {
		t.Fatalf("decodeRadianRuntimeConfig S1 failed: %v", err)
	}
	if mathAbs(cfg1.S1DefBuff-0.8) > 1e-4 {
		t.Errorf("expected S1DefBuff 0.8, got %.4f", cfg1.S1DefBuff)
	}
	if mathAbs(cfg1.S1BarrierRatio-1.0) > 1e-4 {
		t.Errorf("expected S1BarrierRatio 1.0, got %.4f", cfg1.S1BarrierRatio)
	}

	// 4. 技能二测试 (专三 Lv10)
	// atk: 0.8, cnt: 1.0
	spec2, err := buildRadianSourceSpec(st, 2, 10)
	if err != nil {
		t.Fatalf("buildRadianSourceSpec S2 failed: %v", err)
	}
	if spec2.TokenKey != radianTokenTower2 {
		t.Errorf("expected S2 TokenKey %s, got %s", radianTokenTower2, spec2.TokenKey)
	}
	cfg2, err := decodeRadianRuntimeConfig(spec2)
	if err != nil {
		t.Fatalf("decodeRadianRuntimeConfig S2 failed: %v", err)
	}
	if mathAbs(cfg2.S2AtkBuff-0.8) > 1e-4 {
		t.Errorf("expected S2AtkBuff 0.8, got %.4f", cfg2.S2AtkBuff)
	}
}

func TestRadianCombatAndTokenDeployment(t *testing.T) {
	st := &OperatorStats{
		CharID:    radianCharID,
		Elite:     2,
		Level:     90,
		Potential: 5,
	}

	// 1. 技能一【律动线】与戴乌部署及屏障加成
	spec1, _ := buildRadianSourceSpec(st, 1, 10)
	cfg1, _ := decodeRadianRuntimeConfig(spec1)
	combat1 := newRadianCombatState("radian_1", cfg1, 466.0, 143.0, 1069.0, 25.0, 15.0)

	// 验证初始库存为 5
	if combat1.Deployment.Inventory != 5 {
		t.Errorf("expected initial inventory 5, got %d", combat1.Deployment.Inventory)
	}

	squadSlots := 8

	// 地面近战位合法部署
	groundCell := RadianDeploymentCell{
		Position:       [2]int{2, 3},
		MapKnown:       true,
		Deployable:     true,
		OccupancyKnown: true,
		RoleOccupied:   false,
		IsHighland:     false,
	}
	token1, err := combat1.Deployment.DeployToken(10.0, groundCell, RadianDirRight, &squadSlots)
	if err != nil {
		t.Fatalf("deploy ground token failed: %v", err)
	}
	if combat1.Deployment.Inventory != 4 {
		t.Errorf("expected inventory 4 after deploy, got %d", combat1.Deployment.Inventory)
	}
	if squadSlots != 7 {
		t.Errorf("expected squadSlots 7, got %d", squadSlots)
	}

	// 反向控制组：高台位置禁止部署戴乌 (S1 仅地面)
	highlandCell := RadianDeploymentCell{
		Position:       [2]int{2, 4},
		MapKnown:       true,
		Deployable:     true,
		OccupancyKnown: true,
		RoleOccupied:   false,
		IsHighland:     true,
	}
	_, err = combat1.Deployment.DeployToken(11.0, highlandCell, RadianDirRight, &squadSlots)
	if err == nil {
		t.Fatalf("expected error deploying S1 token on highland, got nil")
	}

	// 部署满 3 个召唤物后，禁止再部署
	cell2 := groundCell
	cell2.Position = [2]int{3, 3}
	token2, err := combat1.Deployment.DeployToken(12.0, cell2, RadianDirRight, &squadSlots)
	if err != nil {
		t.Fatalf("deploy token2 failed: %v", err)
	}
	cell3 := groundCell
	cell3.Position = [2]int{4, 3}
	token3, err := combat1.Deployment.DeployToken(13.0, cell3, RadianDirRight, &squadSlots)
	if err != nil {
		t.Fatalf("deploy token3 failed: %v", err)
	}
	cell4 := groundCell
	cell4.Position = [2]int{5, 3}
	_, err = combat1.Deployment.DeployToken(14.0, cell4, RadianDirRight, &squadSlots)
	if err == nil {
		t.Fatalf("expected max active token error, got nil")
	}

	// 开启技能一【律动线】：获得 1 个库存，防御提升 +80%，获得最大生命值 100% 护盾/屏障
	combat1.SkillSP = 25.0 // 充满技力
	invBefore := combat1.Deployment.Inventory
	err = combat1.TriggerSkill(15.0)
	if err != nil {
		t.Fatalf("trigger S1 skill failed: %v", err)
	}
	if combat1.Deployment.Inventory != invBefore+1 {
		t.Errorf("expected inventory to increase by 1, got %d -> %d", invBefore, combat1.Deployment.Inventory)
	}
	if combat1.BarrierHp <= 0 {
		t.Errorf("expected owner barrier > 0, got %.1f", combat1.BarrierHp)
	}
	if token1.BarrierHp <= 0 || token2.BarrierHp <= 0 || token3.BarrierHp <= 0 {
		t.Errorf("expected tokens barrier > 0")
	}

	// 验证技能期间防御力提升
	_, effOwnerDef := combat1.EffectiveOwnerStats()
	expectedOwnerDef := combat1.OwnerDef * (1.0 + 0.8)
	if mathAbs(effOwnerDef-expectedOwnerDef) > 1e-4 {
		t.Errorf("expected owner def %.2f, got %.2f", expectedOwnerDef, effOwnerDef)
	}

	// 推进 25 秒直到技能结束，验证屏障消失
	combat1.TickRadian(25.0, 40.0, &squadSlots)
	if combat1.SkillActive {
		t.Errorf("expected skill to finish after 25s")
	}
	if combat1.BarrierHp != 0 || token1.BarrierHp != 0 {
		t.Errorf("expected barrier to expire after skill finish, got owner=%.1f, token=%.1f", combat1.BarrierHp, token1.BarrierHp)
	}

	// 召唤物离场测试，返还团队部署位
	combat1.NotifyTokenRemoval(token1, &squadSlots)
	if token1.Alive {
		t.Errorf("expected token1 dead")
	}
	if squadSlots != 6 {
		t.Errorf("expected squadSlots 6 after token removal, got %d", squadSlots)
	}

	// 2. 技能三【手牵手】与棱镜塔高台部署、停顿、法术脆弱协同打击测试
	spec3, _ := buildRadianSourceSpec(st, 3, 10)
	cfg3, _ := decodeRadianRuntimeConfig(spec3)
	combat3 := newRadianCombatState("radian_3", cfg3, 466.0, 143.0, 1069.0, 40.0, 30.0)

	// 高台部署棱镜塔合法
	tokenS3, err := combat3.Deployment.DeployToken(5.0, highlandCell, RadianDirRight, &squadSlots)
	if err != nil {
		t.Fatalf("deploy S3 token on highland failed: %v", err)
	}
	// 反向控制组：地面禁止部署棱镜塔 (S3 仅高台)
	_, err = combat3.Deployment.DeployToken(6.0, groundCell, RadianDirRight, &squadSlots)
	if err == nil {
		t.Fatalf("expected error deploying S3 token on ground, got nil")
	}

	// 开启技能三【手牵手】
	combat3.SkillSP = 40.0
	if err := combat3.TriggerSkill(10.0); err != nil {
		t.Fatalf("trigger S3 failed: %v", err)
	}

	// 攻击命中敌人，验证法术伤害、停顿 2.0s、法术脆弱 2.0s 与 1.35 伤害倍率加成
	hitResult := combat3.RadianHitTarget(tokenS3, "enemy_1", 20.0) // 敌方法抗 20
	if !hitResult.IsMagic {
		t.Errorf("expected magic damage for S3 token")
	}
	if mathAbs(hitResult.ApplySluggish-2.0) > 1e-4 {
		t.Errorf("expected ApplySluggish 2.0, got %.2f", hitResult.ApplySluggish)
	}
	if mathAbs(hitResult.ApplyFragile-2.0) > 1e-4 {
		t.Errorf("expected ApplyFragile 2.0, got %.2f", hitResult.ApplyFragile)
	}
	if mathAbs(hitResult.FragileScale-1.35) > 1e-4 {
		t.Errorf("expected FragileScale 1.35, got %.2f", hitResult.FragileScale)
	}
	if hitResult.Damage <= 0 {
		t.Errorf("expected damage > 0, got %.2f", hitResult.Damage)
	}
}

func mathAbs(x float64) float64 {
	if x < 0 {
		return -x
	}
	return x
}
