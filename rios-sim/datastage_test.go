package main

// datastage_test.go：`datastage.go` 那三层的**判别对照**。
//
// 每条都设计成「实现一改坏就红」，不是「跑过就算」：
//   · `zone_id` 精确 vs `zone` 子串 —— 合成一个**两者不同**的用例（`main_1` 会捞出 `main_10`）
//   · `keyword` 是**字面量**不是 LIKE —— 用 `%` 判别（实测参照实现给 0 行，LIKE 给全表）
//   · 排序四元键 —— 断言 `code` 的分段数值序（`2-7` 在 `2-10` 前）
//   · 四星档垫底 —— 断言同 code 下 NORMAL 在 FOUR_STAR 前
//   · 六星档被滤 —— 断言结果里一个 SIX_STAR 都没有
//
// 库不在时**跳过**而不是判红（`data/*.sqlite` 是派生数据，干净检出上本来就不在）。

import (
	"strings"
	"testing"
)

func stageTableForTest(t *testing.T) ([]StageRecord, []ZoneRecord) {
	t.Helper()
	d := dbDirForTest(t)
	if d == "" {
		t.Skip("本机没有 data/akdb.sqlite（派生库）⇒ 跳过")
	}
	t.Setenv("RIOS_DB", d)
	stages, zones, err := LoadStageTable()
	if err != nil {
		t.Fatalf("LoadStageTable 出错：%v", err)
	}
	if len(stages) == 0 {
		t.Fatal("stage 表一行都没读到 ⇒ 查询没跑成功（不是「没有六星档」那种有意义的 0）")
	}
	return stages, zones
}

func TestLoadStageTableExcludesSixStar(t *testing.T) {
	stages, _ := stageTableForTest(t)
	for _, r := range stages {
		if strings.ToUpper(r.Difficulty) == "SIX_STAR" {
			t.Fatalf("六星档没被滤掉：%s（博士 2026-09-26 裁定不做沙盘推演）", r.LevelID)
		}
	}
	//: 正对照：滤的是六星，不是「滤空了」。
	if len(stages) < 3000 {
		t.Fatalf("stage 只剩 %d 行 —— 滤得太多，八成把 NORMAL 也滤了", len(stages))
	}
}

func TestZoneIDExactVsZoneSubstring(t *testing.T) {
	stages, _ := stageTableForTest(t)
	exact := ListStages(stages, StageFilter{ZoneID: "main_1"})
	sub := ListStages(stages, StageFilter{Zone: "main_1"})
	if len(exact) == 0 {
		t.Fatal("精确匹配 main_1 得 0 行 ⇒ 查询没跑成功")
	}
	for _, r := range exact {
		if r.ZoneID != "main_1" {
			t.Fatalf("`zone_id` 应是**精确**匹配，却返回了 %s（zone_id=%s）", r.LevelID, r.ZoneID)
		}
	}
	//: 参照实现 docstring 的原话：「main_1 用子串会连 main_10 一起捞出来」。
	if len(sub) <= len(exact) {
		t.Fatalf("`zone` 是子串匹配，应比精确匹配多（main_10..14）；实得 子串 %d vs 精确 %d",
			len(sub), len(exact))
	}
	hit10 := false
	for _, r := range sub {
		if strings.HasPrefix(r.ZoneID, "main_10") {
			hit10 = true
			break
		}
	}
	if !hit10 {
		t.Fatal("子串 main_1 竟没捞到 main_10 —— 子串语义没生效")
	}
}

func TestKeywordIsLiteralNotLike(t *testing.T) {
	stages, _ := stageTableForTest(t)
	//: `%` 在字面量口径下匹配不到任何一列 ⇒ 0 行。
	if got := ListStages(stages, StageFilter{Keyword: "%"}); len(got) != 0 {
		t.Fatalf("`keyword=%%` 应得 0 行（字面量），实得 %d 行 ⇒ 被当成了通配符", len(got))
	}
	//: 正对照：同一个函数在正常词上必须筛得出，且**大小写不敏感**。
	got := ListStages(stages, StageFilter{Keyword: "MAIN_09-01"})
	if len(got) == 0 {
		t.Fatal("正对照失败：MAIN_09-01 应能筛出（四列之一 + 大小写不敏感）")
	}
	//: 四列都要能命中：拿一个**只在 code 里**出现的词试（`0-1`）。
	byCode := ListStages(stages, StageFilter{Keyword: "0-1"})
	if len(byCode) == 0 {
		t.Fatal("四列匹配少了一列：按 code 搜 `0-1` 得 0 行")
	}
}

func TestCodeSortKeyIsNumericPerChunk(t *testing.T) {
	//: 参照实现 docstring 的原话：「让 `2-7` 排在 `2-10` 前面（纯字符串排序会反）」。
	a, b := codeSortKey("2-7"), codeSortKey("2-10")
	if compareCodeKey(a, b) >= 0 {
		t.Fatal("`2-7` 应排在 `2-10` **前面**（分段数值序）；纯字符串序会给相反结果")
	}
	if !(codeSortKey2Less("main_09-01", "main_09-02")) {
		t.Fatal("同章内 main_09-01 应排在 main_09-02 前")
	}
	//: `#f#` 后缀在 code 键里被去掉（`:788`）⇒ 与本体同键。
	if compareCodeKey(codeSortKey("main_00-01#f#"), codeSortKey("main_00-01")) != 0 {
		t.Fatal("`_code_sort_key` 应把 `#f#` 去掉后再分段")
	}
}

func codeSortKey2Less(x, y string) bool { return compareCodeKey(codeSortKey(x), codeSortKey(y)) < 0 }

func TestFourStarSortsLastAndSortIsStable(t *testing.T) {
	stages, _ := stageTableForTest(t)
	got := ListStages(stages, StageFilter{Keyword: "main_00-01"})
	if len(got) < 2 {
		t.Skip("本机索引里 main_00-01 没有 `#f#` 同胞 ⇒ 这条不适用")
	}
	//: 四元键第一项是「是否四星」= true ⇒ **四星垫底**（不是最先）。
	if strings.HasSuffix(got[0].LevelID, fourStarSuffix) {
		t.Fatalf("四星档应排在最后，实得首行是 %s", got[0].LevelID)
	}
	last := got[len(got)-1]
	if !strings.HasSuffix(last.LevelID, fourStarSuffix) {
		t.Fatalf("四星档应垫底，实得末行是 %s（顺序：%v）", last.LevelID, idsOf(got))
	}
}

func TestLimitZeroMeansNoLimit(t *testing.T) {
	stages, _ := stageTableForTest(t)
	all := ListStages(stages, StageFilter{})
	if len(all) != len(stages) {
		t.Fatalf("Limit=0 应等于不限：全表 %d 行，实得 %d 行", len(stages), len(all))
	}
	two := ListStages(stages, StageFilter{Limit: 2})
	if len(two) != 2 {
		t.Fatalf("Limit=2 应得 2 行，实得 %d 行", len(two))
	}
}

func idsOf(rs []StageRecord) []string {
	out := make([]string, 0, len(rs))
	for _, r := range rs {
		out = append(out, r.LevelID)
	}
	return out
}
