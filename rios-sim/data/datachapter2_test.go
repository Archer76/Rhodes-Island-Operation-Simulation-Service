package data

// datachapter2_test.go：章节层**归并**的端到端金标对照。
//
// 最要紧的一条是总数：参照实现实测 **116 条 chapter**（规格 §4.1：
// 352 个 zone、222 个有关卡的 zone 并成 116 条）—— 这条一红就说明分组整族错了。
//
// ⚠ **计数口径的限定（必读）**：本实现的 `levels` **不含六星档**（博士 2026-09-26 裁定
// 排除沙盘推演），而参照实现的 `totals` 含 `#s`。所以**别拿本实现的 levels 与 Python 对**；
// 能对的是**条数（116）与结构**。这条限定是裁定的必然结果，见 datachapter2.go 的文件头。

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

// TestChapterCountIs116：参照实现实测 116 条（352 zone／222 有关卡的 zone）。
func TestChapterCountIs116(t *testing.T) {
	ch := chaptersForTest(t)
	if len(ch) != 116 {
		ids := make([]string, 0, len(ch))
		for _, c := range ch {
			ids = append(ids, c.Key)
		}
		t.Fatalf("应有 116 条 chapter（规格 §4.1 实测），实得 %d 条：%v", len(ch), ids)
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
