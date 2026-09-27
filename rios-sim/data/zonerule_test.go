package data

// zonerule_test.go：活动 zone 的**去留谓词**自己的判据。
//
// 博士 2026-09-27 **两次**裁定：先是「只留代号含 `sre`（复刻）或 `side`（原版）的」，
// 当晚又加回两族 —— `mini`（故事集）与 `dN`（早期活动）；小玩法与联动
// （`bossrush`／`enemyduel`／`multi`／`break`／`vecb`／`autochess`／`arkhub`／`dp`／
// `football`／`lock`／`vhalfidle`／`fun`／`zone` 族）**仍然**不进库也不进菜单。
//
// 这条判据守的不是「现在有几个章节」（那由 `TestChapterCountIs…` 守），
// 而是**谓词本身没被悄悄改宽或改窄**。三段：
//
//	(1) **逐例**判对 —— 喂合成的 `ZoneRecord`，不依赖库里恰好有什么。
//	    负对照占了快一半：`dp`／`duel`／`halfidle` 这三族的 `d` 后面跟的是**字母**，
//	    专门用来证明 `dN` 那条模式**没有**把整个 `d` 字头一网打尽。
//	(2) 标记集必须**恰好**是裁定那三个词 —— 谁往里加第四个（「顺手也留下吧」），
//	    这条当场红，逼他显式来裁定。
//	(3) 库里的实况：留着的每个 ACTIVITY zone 都要命中，且**四个方向**
//	    （side／sre／mini／dN）**都要有活样本** —— 否则「都命中」可能只是因为
//	    库里根本没剩几个活动 zone（零行使的绿）。

import (
	"strings"
	"testing"
)

func TestActivityKeepRuleIsRuledAndClosed(t *testing.T) {
	//: (2) 标记集必须恰好是裁定那三个 —— 加宽要显式。
	want := []string{"sre", "side", "mini"}
	if strings.Join(activityKeepMarkers, ",") != strings.Join(want, ",") {
		t.Fatalf("活动去留的标记集被改过：%v（裁定的是 %v）—— "+
			"加/减标记等于改口径，请先显式裁定再动这里",
			activityKeepMarkers, want)
	}

	//: (1) 逐例：正例覆盖每一族，负例覆盖每一类小玩法。
	cases := []struct {
		zoneID, activityID, typ, why string
		want                         bool
	}{
		{"act20side_zone1", "act20side", "ACTIVITY", "原版活动（side）", true},
		{"act20sre_zone1", "act20sre", "ACTIVITY", "复刻活动（sre）", true},
		{"act18mini_zone1", "", "ACTIVITY", "故事集（mini：我们明日见）", true},
		{"act8mini_zone1", "", "ACTIVITY", "故事集（mini：如我所见）", true},
		{"act9d0_zone1", "", "ACTIVITY", "早期活动（d0）", true},
		{"act17d5_zone1", "", "ACTIVITY", "早期活动（d5：生于黑夜挂在这一族）", true},
		{"act13d2_zone2", "", "ACTIVITY", "早期活动（d2：骑兵与猎人）", true},
		{"act14d7_zone1", "", "ACTIVITY", "早期活动（d7：喧闹法则）", true},
		//: ↓ 负对照：小玩法与联动一律不许进（当年明确排除，第二次裁定没动它们）
		{"act1bossrush_zone1", "", "ACTIVITY", "引航者试炼（bossrush）", false},
		{"act1enemyduel_zone1", "", "ACTIVITY", "争锋频道（enemyduel）", false},
		{"act1multi_zone1", "", "ACTIVITY", "促融共竞（multi）", false},
		{"act2vmulti_zone1", "", "ACTIVITY", "罗德岛促融共竞（vmulti）", false},
		{"act1vecb_zone1", "", "ACTIVITY", "矢量突破（vecb）", false},
		{"act1break_zone1", "", "ACTIVITY", "矢量突破（break）", false},
		{"act1autochess_zone1", "", "ACTIVITY", "卫戍协议（autochess）", false},
		{"act1arkhub_zone1", "", "ACTIVITY", "奇象巡展（arkhub）", false},
		{"act1football_zone1", "", "ACTIVITY", "阵地足球锦标（football）", false},
		{"act1lock_zone1", "", "ACTIVITY", "荷谟伊智境（lock）", false},
		{"act6fun_zone1", "", "ACTIVITY", "愚人节小玩意（fun）", false},
		//: ★ 这三条是 `dN` 模式的**边界**：d 后面跟字母，不许被误收
		{"act1dp_zone1", "", "ACTIVITY", "逐影集趣（dp：d 后面是字母）", false},
		{"act1vhalfidle_zone1", "", "ACTIVITY", "次生预案（halfidle：同上）", false},
		{"act7fun_zone1", "", "ACTIVITY", "黑色博士坠落（fun）", false},
		//: 类型白名单那一侧
		{"main_9", "", "MAINLINE", "主线不看代号，一律留", true},
		{"roguelike_zone1", "", "ROGUELIKE", "肉鸽不在类型白名单里", false},
	}
	for _, c := range cases {
		got := keepsZone(ZoneRecord{ZoneID: c.zoneID, ActivityID: c.activityID, Type: c.typ})
		if got != c.want {
			t.Errorf("keepsZone(%s/%s, type=%s) = %v，应当是 %v —— %s",
				c.zoneID, c.activityID, c.typ, got, c.want, c.why)
		}
	}

	//: (3) 库里的实况 ＋ 四方向活样本。
	_, zones := stageTableForTest(t)
	act := 0
	var nSide, nSre, nMini, nDN, nOther int
	var firstOther string
	for _, z := range zones {
		if z.Type != "ACTIVITY" {
			continue
		}
		act++
		code := strings.ToLower(strings.TrimSpace(z.ActivityID))
		if code == "" {
			code = strings.ToLower(z.ZoneID)
		}
		switch {
		case strings.Contains(code, "side"):
			nSide++
		case strings.Contains(code, "sre"):
			nSre++
		case strings.Contains(code, "mini"):
			nMini++
		case hasDNCode(code):
			nDN++
		default:
			nOther++
			if firstOther == "" {
				firstOther = z.ZoneID + "（activity_id=" + z.ActivityID + "）"
			}
		}
	}
	if act == 0 {
		t.Fatal("库里一个 ACTIVITY zone 都没有 ⇒ 查询没跑成功" +
			"（不是「活动都被清了」那种有意义的 0）")
	}
	if nOther != 0 {
		t.Errorf("库里留着 %d 个四族都不命中的活动 zone，例如 %s —— "+
			"写入口径没落到库，或者有别的路径把它放回来了", nOther, firstOther)
	}
	if nSide == 0 || nSre == 0 || nMini == 0 || nDN == 0 {
		t.Fatalf("四个方向的活样本：side=%d sre=%d mini=%d dN=%d —— 有方向是 0，"+
			"那条「都命中」就没有行使（零行使的绿）", nSide, nSre, nMini, nDN)
	}
	t.Logf("库里 ACTIVITY zone %d 个（side %d／sre %d／mini %d／dN %d），"+
		"全部命中且标记集未被改宽", act, nSide, nSre, nMini, nDN)
}
