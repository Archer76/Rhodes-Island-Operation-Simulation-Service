package data

// zonerule_test.go：活动 zone 的**去留谓词**自己的判据。
//
// 博士 2026-09-27 裁：活动只留代号含 `sre`（复刻）或 `side`（原版）的，
// 其余（`mini`／`bossrush`／`enemyduel`… 小玩法与联动）**在建库阶段就舍弃**；
// 且**未来的新活动按同一逻辑决定去留**。
//
// 这条判据守的不是「现在有几个章节」（那由 `TestChapterCountIs69` 守），
// 而是**谓词本身没被悄悄改宽或改窄**：
//
//  1. 库里**留着**的每一个 `ACTIVITY` zone，代号必须命中标记集 —— 写入口径
//     真的落到了库里（`db stage-prune` 跑过、且没被别的路径放回来）；
//  2. 标记集必须**恰好**是裁定的那两个词 —— 谁往里加第三个（「顺手也留下吧」），
//     这条当场红，逼他显式来裁定；
//  3. 正对照：`sre` 与 `side` 两个方向**都要有活的样本**，否则「都命中」
//     可能只是因为库里根本没剩几个活动 zone（零行使的绿）。

import (
	"strings"
	"testing"
)

func TestActivityKeepRuleIsRuledAndClosed(t *testing.T) {
	_, zones := stageTableForTest(t)

	//: (2) 标记集必须恰好是裁定那两个 —— 加宽要显式。
	want := []string{"sre", "side"}
	if strings.Join(activityKeepMarkers, ",") != strings.Join(want, ",") {
		t.Fatalf("活动去留的标记集被改过：%v（裁定的是 %v）—— "+
			"加/减标记等于改口径，请先显式裁定再动这里",
			activityKeepMarkers, want)
	}

	//: (1) 库里留着的 ACTIVITY zone 必须全部命中。
	act := 0
	hasSre, hasSide := 0, 0
	for _, z := range zones {
		if z.Type != "ACTIVITY" {
			continue
		}
		act++
		code := strings.ToLower(strings.TrimSpace(z.ActivityID))
		if code == "" {
			code = strings.ToLower(z.ZoneID)
		}
		if !strings.Contains(code, "sre") && !strings.Contains(code, "side") {
			t.Errorf("库里留着一个既不 sre 也不 side 的活动 zone：%s"+
				"（type=%s activity_id=%q）—— 写入口径没落到库，或者有别的路径把它放回来了",
				z.ZoneID, z.Type, z.ActivityID)
		}
		if strings.Contains(code, "sre") {
			hasSre++
		}
		if strings.Contains(code, "side") {
			hasSide++
		}
	}

	//: (3) 正对照：两个方向都要有活的样本。
	if act == 0 {
		t.Fatal("库里一个 ACTIVITY zone 都没有 ⇒ 查询没跑成功" +
			"（不是「活动都被清了」那种有意义的 0）")
	}
	if hasSre == 0 || hasSide == 0 {
		t.Fatalf("sre 方向 %d 个、side 方向 %d 个 —— 有一个方向没有活样本，"+
			"上面那条「都命中」就没有行使（零行使的绿）", hasSre, hasSide)
	}
	t.Logf("库里 ACTIVITY zone %d 个（sre %d、side %d），全部命中且标记集未被改宽",
		act, hasSre, hasSide)
}
