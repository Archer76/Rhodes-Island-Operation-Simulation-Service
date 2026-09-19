package main

import "testing"

// enterPm2 的**幂等守卫**。
//
// 为什么要它：`sim.go:2813` 那处 `if !e.pm2Applied` 是**唯一**拦住"面板被反复改写"的东西，
// 而它此前**没有任何测试钉住**。这一族在本仓已经出过一次事——记忆 `62516898`：
// `pm2Tick` 里多一个 `|| !e.pm2Clean` 导致**防御每帧重置**、抹掉蜕皮。
// 同一 bug 形状再来一次，代价就是 RES 越加越负（UI_2 在深水用例上看到的 `×1.05` 就是那个症状）。
//
// 三条断言各指一件事：
//   - 第一次调用确实按原文改了（攻防乘法、抗性加法——**别"统一"成一种**）；
//   - 第二次调用**一个字段都不许动**；
//   - `applied` 标记本身要立住（否则上面两条都只是巧合）。
func TestEnterPm2RewritesPanelExactlyOnce(t *testing.T) {
	c := &simCtx{}
	e := &enemy{spec: Spec{
		Name: "测试归来", ATK: 100, DEF: 50, RES: 10,
		Pm2Atk: 0.5, Pm2Def: 0.2, Pm2Res: -30, Pm2Move: 0.25,
		AttackRange: 1.5,
	}}
	sp := &e.spec

	c.enterPm2(e, 0)
	if !e.pm2Applied {
		t.Fatal("第一次调用后应置上 applied 标记")
	}
	// 攻防乘法、抗性加法、移速走 haste——逐个照原文，不许"统一"。
	if sp.ATK != 150 {
		t.Fatalf("ATK 应为 100×1.5=150，得到 %v", sp.ATK)
	}
	if sp.DEF != 60 {
		t.Fatalf("DEF 应为 50×1.2=60，得到 %v", sp.DEF)
	}
	if sp.RES != -20 {
		t.Fatalf("RES 应为 10+(-30)=-20（加法，不是乘法），得到 %v", sp.RES)
	}
	if e.haste != 1.25 {
		t.Fatalf("haste 应为 1.25，得到 %v", e.haste)
	}

	atk1, def1, res1, haste1 := sp.ATK, sp.DEF, sp.RES, e.haste
	c.enterPm2(e, 1)
	if sp.ATK != atk1 || sp.DEF != def1 || sp.RES != res1 || e.haste != haste1 {
		t.Fatalf("第二次调用**不该再改面板**：atk %v→%v def %v→%v res %v→%v haste %v→%v",
			atk1, sp.ATK, def1, sp.DEF, res1, sp.RES, haste1, e.haste)
	}
}

// 入口条件：`pm2_atk / pm2_move / pm2_invincible` **全 0 就不进形态**（原版 4229）。
// 少了这条，`pm2_res` 单独有值也会被当成"归来"，把 RES 平白改一次。
func TestEnterPm2SkipsWhenNoTriggerField(t *testing.T) {
	c := &simCtx{}
	e := &enemy{spec: Spec{Name: "测试归来", ATK: 100, RES: 10, Pm2Res: -30}}
	c.enterPm2(e, 0)
	if e.pm2Active || e.pm2Applied {
		t.Fatal("三个触发量全 0 时不该进形态（照原版 4229）")
	}
	if e.spec.RES != 10 {
		t.Fatalf("既然没进形态，RES 就不该被动：得到 %v", e.spec.RES)
	}
}

// `pm2_invincible > 0` 单独也能触发形态——它是三个触发量之一（上一条只试了"全 0"）。
func TestEnterPm2TriggersOnInvincibleAlone(t *testing.T) {
	c := &simCtx{}
	e := &enemy{spec: Spec{Name: "测试归来", ATK: 100, RES: 10, Pm2Invincible: 5}}
	c.enterPm2(e, 3.0)
	if !e.pm2Active {
		t.Fatal("pm2_invincible>0 应单独触发形态")
	}
	if e.invincibleUntil != 8.0 {
		t.Fatalf("无敌应到 t+5=8，得到 %v", e.invincibleUntil)
	}
}
