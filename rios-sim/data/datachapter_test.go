package data

// datachapter_test.go：章节层四函数的**金标对照**。
//
// 金标来源：`out/zz_tui_data_spec.md` §4.3 的 [实测] 行（子代理把参照实现与
// `out/zz_golden.txt` 的 17 条 `LBL` 逐条对齐过）。**这些不是我自己编的期望值**，
// 是读参照实现跑出来的读数 —— 所以它们红的时候，先怀疑我的实现，不要先怀疑期望。
//
// 两条**计数型**金标最要紧：它们一条就能查出「整族错了」：
//   · `zone_title` 返回空串的 zone = **31** 个（含全部 `camp_zone_*`）
//   · `chapter_label` 非空的 = **18** 条

import "testing"

func TestCnNumGolden(t *testing.T) {
	cases := []struct {
		in   int
		want string
	}{
		{1, "一"}, {9, "九"}, {10, "十"}, {11, "十一"}, {14, "十四"},
		{17, "十七"}, {20, "二十"}, {99, "九十九"},
		{0, "0"}, {-3, "-3"}, //: Python 的 `n <= 0` 分支是 `str(n)`
	}
	for _, c := range cases {
		got, ok := cnNum(c.in)
		if !ok || got != c.want {
			t.Errorf("cnNum(%d) = %q（ok=%v），期望 %q", c.in, got, ok, c.want)
		}
	}
}

// TestCnNumHundredIsRegisteredDivergence：Python 在 100 上会
// `IndexError: string index out of range`（规格 §4.3 有实测），Go **不照抄这个崩**。
// 这条测试就是那条「具名登记」的落点：**Go 返回 ok=false，并退回阿拉伯数字**。
func TestCnNumHundredIsRegisteredDivergence(t *testing.T) {
	if s, ok := cnNum(100); ok {
		t.Fatalf("cnNum(100) 不该成功（Python 在此越界崩）；实得 %q", s)
	}
	if got := cnNumOrDigits(100); got != "100" {
		t.Fatalf("越界时应退回阿拉伯数字，实得 %q", got)
	}
}

func TestZoneTitleGolden(t *testing.T) {
	_, zones := stageTableForTest(t)
	byID := map[string]ZoneRecord{}
	for _, z := range zones {
		byID[z.ZoneID] = z
	}
	//: 规格 §4.3 的四条 [实测]：main_9 不带副标题、main_0 是序章、
	//: act3mainss_zone1 带副标题（因为 name_first 是英文）、act54side_zone1 是分部名。
	for id, want := range map[string]string{
		"main_9":           "第九章",
		"main_0":           "序章",
		"act3mainss_zone1": "第十六章　反常光谱",
		"act54side_zone1":  "通学路",
		"camp_zone_1":      "",
	} {
		z, ok := byID[id]
		if !ok {
			t.Fatalf("库里没有 zone %s ⇒ 这条金标不适用（不是「它算错了」）", id)
		}
		if got := zoneTitle(z); got != want {
			t.Errorf("zoneTitle(%s) = %q，期望 %q（name_first=%q second=%q title=%q type=%q）",
				id, got, want, z.NameFirst, z.NameSecond, z.NameTitle, z.Type)
		}
	}
}

// TestZoneTitleEmptyCountIsThirtyOne 是**计数型**金标：规格 §4.3 实测
// 「352 个 zone 里 31 个 zone_title 返回空串」。整族错一位这条就会红。
func TestZoneTitleEmptyCountIsThirtyOne(t *testing.T) {
	_, zones := stageTableForTest(t)
	if len(zones) == 0 {
		t.Fatal("zone 表一行都没读到 ⇒ 查询没跑成功")
	}
	n := 0
	for _, z := range zones {
		if zoneTitle(z) == "" {
			n++
		}
	}
	if n != 31 {
		t.Fatalf("zone_title 返回空串的应有 31 个（实测金标），实得 %d 个（zone 总数 %d）",
			n, len(zones))
	}
}

// TestChapterLabelOnlyMainline 是另一条**计数型**金标：规格 §4.3 实测
// 「18 条非空」＋「非主线 zone 的 chapter_label 全为空串 → True」。
func TestChapterLabelOnlyMainline(t *testing.T) {
	_, zones := stageTableForTest(t)
	n := 0
	for _, z := range zones {
		s := chapterLabel(z)
		if s != "" {
			n++
		}
		if s != "" && z.Type != "MAINLINE" && z.Type != "MAINLINE_ACTIVITY" {
			t.Fatalf("非主线 zone %s（type=%s）的 chapter_label 竟非空：%q", z.ZoneID, z.Type, s)
		}
	}
	if n != 18 {
		t.Fatalf("chapter_label 非空的应有 18 条（实测金标），实得 %d 条", n)
	}
}

// TestCampaignPartTitleJoinsStageNames：`camp_zone_1` 的分部名是三个图名用顿号连起来
// （规格 §4.3 实测：`龙门外环、龙门市区、龙门商业街`，levels=3）。
func TestCampaignPartTitleJoinsStageNames(t *testing.T) {
	_, zones := stageTableForTest(t)
	var z ZoneRecord
	found := false
	for _, x := range zones {
		if x.ZoneID == "camp_zone_1" {
			z, found = x, true
			break
		}
	}
	if !found {
		t.Skip("库里没有 camp_zone_1 ⇒ 这条不适用")
	}
	got := partTitle(z, []string{"龙门外环", "龙门市区", "龙门商业街"})
	if got != "龙门外环、龙门市区、龙门商业街" {
		t.Fatalf("CAMPAIGN 分部名应是关卡名顿号相连，实得 %q", got)
	}
	//: 没有关卡名时退回第二级（这里是空串 —— 照实测，`zone_title(camp_zone_1)` 就是空）。
	if got := partTitle(z, nil); got != "" {
		t.Fatalf("没有关卡名时应退回 chapter_label→name_second→zone_title，camp_zone_1 三级都是空 ⇒ 期望空串，实得 %q", got)
	}
}
