package data

// datachapter2_test.go：章节层**归并**的端到端金标对照。
//
// 最要紧的一条是总数：**69 条 chapter**（博士 2026-09-27 裁后的口径 —— 只留
// 18 主线（含序章）＋ 剿灭 ＋ 代号带 `sre`／`side` 的活动；其余 47 条**在建库
// 阶段就舍弃**）。这条一红就说明分组整族错了。
//
// ★ 2026-09-27 两条同时改了，别再按旧数读：
//   · 条数 **116 → 69**（建库白名单收紧，见 `ak_tactic/db/stages.py` 的 `keeps_zone`）；
//   · `levels` 现在**与参照实现同口径**（含 `#s`）—— 09-26 那笔「六星档不做」
//     已**反转**：15～17 章的六星是**险地作战**（等效突袭），加回取数面。
//     旧注释里那条「别拿本实现的 levels 与 Python 对」的限定**作废**。

import (
	"strings"
	"testing"
)

func chaptersForTest(t *testing.T) []Chapter {
	t.Helper()
	stages, zones := stageTableForTest(t)
	ch := ListChapters(stages, zones)
	if len(ch) == 0 {
		t.Fatal("一条 chapter 都没算出来 ⇒ 查询没跑成功（不是「没有章节」那种有意义的 0）")
	}
	return ch
}

// TestChapterCountIs69：2026-09-27 裁后的口径（旧金标 116 已过期）。
func TestChapterCountIs69(t *testing.T) {
	ch := chaptersForTest(t)
	if len(ch) != 69 {
		ids := make([]string, 0, len(ch))
		for _, c := range ch {
			ids = append(ids, c.Key)
		}
		t.Fatalf("应有 69 条 chapter（2026-09-27 裁后的口径：18 主线含序章＋剿灭＋sre/side 活动），实得 %d 条：%v", len(ch), ids)
	}
}

func TestChapterLevelsConsistentAndNoEmptyPart(t *testing.T) {
	for _, c := range chaptersForTest(t) {
		sum := 0
		for _, p := range c.Parts {
			if p.Levels <= 0 {
				t.Fatalf("chapter %s 的分部 %s 关卡数为 %d ⇒ counts==0 的 zone 不该进菜单",
					c.Key, p.ZoneID, p.Levels)
			}
			sum += p.Levels
		}
		if sum != c.Levels {
			t.Fatalf("chapter %s 的 levels=%d 与各分部之和 %d 不等", c.Key, c.Levels, sum)
		}
		if len(c.Parts) == 0 {
			t.Fatalf("chapter %s 一个分部都没有", c.Key)
		}
	}
}

// TestCampaignGroupIsOneAndNumericallyOrdered：剿灭作战那 15 个 zone **整类并成一条**，
// 且分部按**尾号数值序**排（参照实现在 `:642-645` 交代了理由：它们的 zone_index 全是 0，
// 只按它会退化成字符串序 camp_zone_1, camp_zone_10, …, camp_zone_2）。
func TestCampaignGroupIsOneAndNumericallyOrdered(t *testing.T) {
	var camp *Chapter
	for i := range chaptersForTest(t) {
		if c := chaptersForTest(t)[i]; c.Key == campaignTitle {
			camp = &c
			break
		}
	}
	if camp == nil {
		t.Fatal("没有 key=剿灭作战 的那一条 ⇒ 剿灭整类并一条的规则没生效")
	}
	if len(camp.Parts) < 2 {
		t.Fatalf("剿灭应含多个分部，实得 %d 个", len(camp.Parts))
	}
	if !strings.Contains(camp.Subtitle, "个部分") {
		t.Fatalf("剿灭的副标题应是「N 个部分」，实得 %q", camp.Subtitle)
	}
	//: 尾号必须**数值递增**（字符串序会给出 1,10,11,…,2）。
	prev := -1
	for _, p := range camp.Parts {
		n := campaignTailNum(ZoneRecord{ZoneID: p.ZoneID, Type: "CAMPAIGN"})
		if n <= prev {
			t.Fatalf("剿灭分部未按尾号数值序：%s（尾号 %d，前一个 %d）", p.ZoneID, n, prev)
		}
		prev = n
	}
}

// TestMain9ChapterTitle：`main_9` 所在的那条标题以「第九章」开头
// （规格 §4.3 实测：`zoneTitle(main_9)` = 第九章，**不带副标题**，因为 name_first 就是「第九章」）。
func TestMain9ChapterTitle(t *testing.T) {
	for _, c := range chaptersForTest(t) {
		for _, p := range c.Parts {
			if p.ZoneID != "main_9" {
				continue
			}
			if !strings.HasPrefix(c.Title, "第九章") {
				t.Fatalf("含 main_9 的 chapter 标题应以「第九章」开头，实得 %q", c.Title)
			}
			return
		}
	}
	t.Fatal("没有哪个 chapter 含 main_9 ⇒ 分组漏了这个 zone")
}

// TestMultiPartChaptersHaveSubtitle：多 zone 组的副标题是「N 个部分」，单 zone 组是空串。
func TestMultiPartChaptersHaveSubtitle(t *testing.T) {
	for _, c := range chaptersForTest(t) {
		if c.Key == campaignTitle {
			continue //: 剿灭单独测
		}
		if len(c.Parts) > 1 && !strings.Contains(c.Subtitle, "个部分") {
			t.Fatalf("多分部 chapter %s 的副标题应为「N 个部分」，实得 %q", c.Key, c.Subtitle)
		}
		if len(c.Parts) == 1 && c.Subtitle != "" {
			t.Fatalf("单分部 chapter %s 的副标题应为空，实得 %q", c.Key, c.Subtitle)
		}
	}
}
