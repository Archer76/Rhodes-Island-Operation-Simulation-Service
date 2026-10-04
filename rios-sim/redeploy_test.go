package main

// redeploy_test.go：**同一干员的二次部署**（博士 2026-09-29 定的规则）的 Go 侧判据。
//
// 规则原文：「不允许一个干员**同时在场上**出现两次，但如果被击倒／撤退回到待部署区、
// 且再部署冷却结束，则可以再次部署。」
//
// 这条规则的**真值在模拟器**：计划层判不了「此刻在不在场上」（取决于有没有被打死）。
// 所以这里以独立 synthetic primitive Spec → runSim 测三例单元行为。
// 真实生产接线另有测试；不删真实机制标记绕过生产拒判，也不声称实战通过：
//
//	① 正例：撤退 → 冷却过后 → 换个格子再上 ⇒ **真的落地了**；
//	② 负对照一：不撤退、第一次还在场上 ⇒ 拒「同一干员已在场」；
//	③ 负对照二：撤退了但冷却没到 ⇒ 拒「再部署冷却中」。
//
// ⚠ **零行使的绿**：三例都先证明**第一次部署真的落了地**（事件里有 `deploy`），
// 否则「没报拒收」只是因为整局根本没跑到那一刻——那是最像成功的一种失败。
// 正例还要证明**第二次也真的落了地**（两条 `deploy` 事件 ＋ `Deployed` 计数），
// 而不是「被拒了但没记账」。
//
// ⚠ 时刻相对 primitive 首次部署计算，保留撤退与二次部署的原差值。
// 未来普通出怪保证跑到被测时刻，期间无战斗影响；事件断言防止零行使的绿。

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

// redeployRoster 读那 20 人的合成名册（`fixtures/`，与 buildspec 判据同一份）。
func redeployRoster(t *testing.T) json.RawMessage {
	t.Helper()
	raw, err := os.ReadFile(filepath.Join("fixtures", "roster_max_modelled.json"))
	if err != nil {
		t.Fatalf("读名册夹具失败：%v", err)
	}
	return json.RawMessage(raw)
}

// redeploySpec 把一份计划原文造成规格（走**生产那条路**：`BuildSpecFull`）。
//
// `FullSpec` 与 `Spec` 是两个结构体（前者是 19 键契约、后者是模拟器的入参），
// 所以照协议的做法**序列化一次再解回来**——不另写一份转换，免得两处口径分叉。
func redeploySpec(t *testing.T, planJSON string) *Spec {
	t.Helper()
	out, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{
		Plan:        json.RawMessage(planJSON),
		Roster:      redeployRoster(t),
		AllowSkills: true,
	})
	if err != nil {
		t.Fatalf("造规格失败（不是本判据要测的那一层）：%v", err)
	}
	raw, err := json.Marshal(out.Spec)
	if err != nil {
		t.Fatalf("规格序列化失败：%v", err)
	}
	var spec Spec
	if err := json.Unmarshal(raw, &spec); err != nil {
		t.Fatalf("规格解回失败：%v", err)
	}
	return &spec
}

// firstDeployAt 读独立 primitive 首次部署时刻，不依赖真实关卡费用排程。
func firstDeployAt(t *testing.T) float64 {
	t.Helper()
	return redeployPrimitiveSpec(1, -1).Deploys[0].Time
}

// eventsOf 数某类事件里某个名字出现了几次。
func eventsOf(v *Verdict, kind, who string) []float64 {
	var out []float64
	for _, e := range v.Events {
		if e.Kind == kind && e.Who == who {
			out = append(out, e.T)
		}
	}
	return out
}

// rejectionsOf 把拒收明细里某个名字的原因挑出来（`(时刻, 原因)`）。
func rejectionsOf(v *Verdict, who string) [][2]any {
	var out [][2]any
	for _, r := range v.DeployRejected {
		if r[1] == who {
			out = append(out, [2]any{r[0], r[2]})
		}
	}
	return out
}

// TestRedeployAfterRetreatLands 正例：撤退 @+20s，冷却（70s，`opsRedeployDefault`）
// 过后 @+95s **换一格**再上 ⇒ 两条 `deploy` 事件、无拒收、`Deployed` 是 3。
func TestRedeployAfterRetreatLands(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	spec := redeployPrimitiveSpec(at+95, at+20)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	deploys := eventsOf(v, "deploy", "能天使")
	retreats := eventsOf(v, "retreat", "能天使")
	//: ① 先证明**这一局真的走到了那儿**（零行使的绿不算过）
	if len(deploys) < 1 {
		t.Fatalf("第一次部署就没落地（deploy 事件 %v，用时 %.1fs）——"+
			"这一趟没有测到二次部署，读数作废", deploys, v.Elapsed)
	}
	if len(retreats) != 1 {
		t.Fatalf("撤退没有执行（retreat 事件 %v，deploy %v，用时 %.1fs）",
			retreats, deploys, v.Elapsed)
	}
	//: ② 二次部署：**落地了**，而且没有记账说被拒
	if len(deploys) != 2 {
		t.Fatalf("第二次部署没落地（deploy 事件 %v，拒收 %v，用时 %.1fs）",
			deploys, rejectionsOf(v, "能天使"), v.Elapsed)
	}
	if len(v.DeployRejected) != 0 {
		t.Errorf("有拒收明细，应当是空的：%v", v.DeployRejected)
	}
	if v.Deployed != 3 {
		t.Errorf("Deployed = %d，应当是 3（能天使 ×2 ＋ 泥岩 ×1）", v.Deployed)
	}
	//: ③ 换了格子：两条事件之间真的隔了冷却那么久
	if gap := deploys[1] - retreats[0]; gap < 70 {
		t.Errorf("二撤之间只隔了 %.1fs，短于再部署冷却 70s", gap)
	}
}

// TestRedeployRefusedWhileOnField 负对照一：**不撤退**、第一次还在场上就再排一次
// ⇒ 拒「同一干员已在场」，且**只落地一次**。
func TestRedeployRefusedWhileOnField(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	spec := redeployPrimitiveSpec(at+20, -1) //: -1 = 不排撤退
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	deploys := eventsOf(v, "deploy", "能天使")
	if len(deploys) != 1 {
		t.Fatalf("第一次部署没落地（deploy 事件 %v）——这一趟没有测到那条拒收", deploys)
	}
	got := rejectionsOf(v, "能天使")
	if len(got) != 1 || got[0][1] != "同一干员已在场" {
		t.Fatalf("拒收明细 = %v，应当恰好一条「同一干员已在场」", got)
	}
	if len(eventsOf(v, "retreat", "能天使")) != 0 {
		t.Errorf("这一例没排撤退，不该有 retreat 事件")
	}
}

// TestRedeployRefusedDuringCooldown 负对照二：撤退 @+20s，**冷却没到**（70s）就
// 在 @+60s 再排一次 ⇒ 拒「再部署冷却中」。
func TestRedeployRefusedDuringCooldown(t *testing.T) {
	chdirRepoRoot(t)
	at := firstDeployAt(t)
	spec := redeployPrimitiveSpec(at+60, at+20)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	deploys := eventsOf(v, "deploy", "能天使")
	if len(deploys) != 1 {
		t.Fatalf("第一次部署没落地（deploy 事件 %v）——这一趟没有测到那条拒收", deploys)
	}
	if len(eventsOf(v, "retreat", "能天使")) != 1 {
		t.Fatalf("撤退没有执行（用时 %.1fs）——冷却那一条就测不到", v.Elapsed)
	}
	got := rejectionsOf(v, "能天使")
	if len(got) != 1 || got[0][1] != "再部署冷却中" {
		t.Fatalf("拒收明细 = %v，应当恰好一条「再部署冷却中」", got)
	}
}
