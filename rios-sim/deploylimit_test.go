package main

// deploylimit_test.go：**同时部署上限**（博士 2026-09-29 定的规则）的 Go 侧判据。
//
// 规则原文：「即时关卡部署上限是 9 人或更少，**编队中的 12 人依旧都可以上场**，
// 只要**同时在场**的部署位占用不超过关卡上限即可。此处有一个例子是令，她的召唤物
// 会占用部署位。」
//
// 拆成三条判据，逐条对着规则的三个分句：
//
//	① 上限**接进来了**：`main_01-07` 的 `spec.deploy_limit` 是 8（界面那条
//	   `deployLimit` 判据用的同一个数）；
//	② 满位就**具名拒**，不是静默不部署；
//	③ 撤退**释放**部署位（所以「撤一个再上一个」在满位时照样成立），
//	   而计划里排几个人**不管**（编队 12 人那一句）。
//
// ⚠ ②③ 用**只翻一个字段**的控制实验：规格照生产路径造（`BuildSpecFull`），
// 只把 `DeployLimit` 改成 1，让两条部署必然撞上限。翻的是**输入数据**，不是代码分支
// ——判决随它改，才说明这条判据真的读了它。
//
// ⚠ 每一例都先证明**前一次部署真的落了地**（事件里有 `deploy`）：否则「第二条被拒」
// 可能只是整局根本没跑到那一刻，那是零行使的绿。

import (
	"fmt"
	"testing"
)

// limitPlan 造一份两人（能天使 ＋ 泥岩）的计划：第二条给死时刻。
func limitPlan(secondAt float64, retreatAt float64) string {
	retreats := "[]"
	if retreatAt >= 0 {
		retreats = fmt.Sprintf(`[{"operator":"能天使","time":%.3f}]`, retreatAt)
	}
	return fmt.Sprintf(`{
		"stage": "main_01-07",
		"deploys": [
			{"operator": "能天使", "position": [3,5], "direction": "Up", "skill": 0},
			{"operator": "泥岩", "position": [2,3], "direction": "Left", "skill": 0, "time": %.3f}
		],
		"retreats": %s
	}`, secondAt, retreats)
}

// limitSpec 按生产路径造规格，然后把**同时部署上限**翻成 `limit`。
func limitSpec(t *testing.T, limit int, secondAt float64, retreatAt float64) *Spec {
	t.Helper()
	spec := redeploySpec(t, limitPlan(secondAt, retreatAt))
	spec.DeployLimit = limit
	return spec
}

// TestDeployLimitWiredFromStage ① 上限从关卡接进规格（改动前这个字段根本不存在）。
func TestDeployLimitWiredFromStage(t *testing.T) {
	chdirRepoRoot(t)
	spec := redeploySpec(t, limitPlan(30, -1))
	if spec.DeployLimit != 8 {
		t.Fatalf("main_01-07 的 deploy_limit = %d，应当是 8（关卡 `options.characterLimit`）",
			spec.DeployLimit)
	}
}

// TestDeployLimitRefusesBeyondCap ② 上限＝1 时，第二条**具名拒**，且第一条真的落了地。
func TestDeployLimitRefusesBeyondCap(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	spec := limitSpec(t, 1, at+8, -1)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	//: 先证明第一条**真的落了地**（否则这一趟什么都没测到）
	if got := eventsOf(v, "deploy", "能天使"); len(got) != 1 {
		t.Fatalf("能天使没落地（deploy 事件 %v，用时 %.1fs）⇒ 上限那条判据没被行使",
			got, v.Elapsed)
	}
	got := rejectionsOf(v, "泥岩")
	if len(got) != 1 || got[0][1] != "部署位已满（同时上限 1）" {
		t.Fatalf("泥岩的拒收明细 = %v，应当恰好一条「部署位已满（同时上限 1）」", got)
	}
	if n := len(eventsOf(v, "deploy", "泥岩")); n != 0 {
		t.Errorf("泥岩的 deploy 事件有 %d 条，上限＝1 时应当是 0 条", n)
	}
}

// costDeniedFor 数「费用不足」那一栏里某个名字出现了几次。
//
// ⚠ 为什么两例正例都要查它：第二条部署排在**费够了之后**才可能落地，排早了会被
// 「费用不足」挡下——那是**另一条**拒收（`verdict.cost_denied`，与 `deploy_rejected`
// 分开记账）。只查 `deploy_rejected` 为空会把「费不够所以没上」读成「上限够了所以上了」。
func costDeniedFor(v *Verdict, who string) int {
	n := 0
	for _, r := range v.CostDenied {
		if r[1] == who {
			n++
		}
	}
	return n
}

// TestDeployLimitRefusesOnlyWhileOccupied ② 的反向对照：**上限够了就不拒**。
//
// 只翻上限这一个字段（1 → 8），同一份计划、同一批时刻 ⇒ 两条都落地。
// 没有这一条，上面那个红可能只是「计划本身有问题」，与上限无关。
func TestDeployLimitRefusesOnlyWhileOccupied(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	//: 第二条排到 +50s：**费够**才落得了地（泥岩 ~20 费，+8s 时账上不够，
	//: 会被「费用不足」挡下——那与上限无关）。
	spec := limitSpec(t, 8, at+50, -1)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	if len(v.DeployRejected) != 0 {
		t.Errorf("上限＝8 时有拒收明细，应当是空的：%v", v.DeployRejected)
	}
	for _, who := range []string{"能天使", "泥岩"} {
		if n := len(eventsOf(v, "deploy", who)); n != 1 {
			t.Errorf("上限＝8 时 %s 的 deploy 事件 = %d 条，应当是 1 条"+
				"（费用不足 %d 次，用时 %.1fs）",
				who, n, costDeniedFor(v, who), v.Elapsed)
		}
	}
}

// TestDeployLimitFreedByRetreat ③ 撤退**释放**部署位：上限＝1，撤了之后第二个人能上。
func TestDeployLimitFreedByRetreat(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	spec := limitSpec(t, 1, at+50, at+4)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	if got := eventsOf(v, "deploy", "能天使"); len(got) != 1 {
		t.Fatalf("能天使没落地（deploy 事件 %v）⇒ 这一趟什么都没测到", got)
	}
	if got := eventsOf(v, "retreat", "能天使"); len(got) != 1 {
		t.Fatalf("撤退没执行（用时 %.1fs）⇒ 释放部署位这件事没被行使", v.Elapsed)
	}
	if got := eventsOf(v, "deploy", "泥岩"); len(got) != 1 {
		t.Fatalf("撤退之后泥岩仍没落地（deploy 事件 %v，拒收 %v，费用不足 %d 次，"+
			"用时 %.1fs）——「撤退释放部署位」这一条不成立",
			got, rejectionsOf(v, "泥岩"), costDeniedFor(v, "泥岩"), v.Elapsed)
	}
	if len(v.DeployRejected) != 0 {
		t.Errorf("有拒收明细，应当是空的：%v", v.DeployRejected)
	}
}
