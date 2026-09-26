package main

// datadb_test.go：`datadb.go` 那两条取数口的**正负对照**。
//
// 判据的形状（本仓纪律：报「0 命中／计数 0」之前先证明查询跑成功了）：
//   - **正对照**：一个**已知存在**的关卡（`main_00-01`）必须取到，且它的名字与章节非空；
//   - **负对照**：一个**肯定不存在**的 level_id 必须取到 0 行（证明「筛」这一步真的在筛，
//     而不是永远返回全表）；
//   - **缺库那一路**：库不在时必须是 `ErrDBMissing`，**不是**空列表也不是崩。
//
// ⚠ 库不在时**跳过**而不是判红：`data/*.sqlite` 是派生数据、在干净检出上本来就不在
// （`.gitignore` 里有它）。判红会把「没建库」读成「代码坏了」。
// ⚠ 断言里**不写死行数**（3055 那种）：库是派生的，重建一次内容就可能变；
// 写死行数会造出一条「数据一变就红」的假判据。要钉的是**行为**，不是**内容快照**。

import (
	"errors"
	"os"
	"path/filepath"
	"testing"
)

// dbDirForTest 找到本机那份库；找不到就跳过（返回空串）。
func dbDirForTest(t *testing.T) string {
	t.Helper()
	for _, d := range []string{filepath.Join("..", "data"), "data"} {
		if _, err := os.Stat(filepath.Join(d, "akdb.sqlite")); err == nil {
			return d
		}
	}
	return ""
}

func TestStageRowsPositiveAndNegative(t *testing.T) {
	d := dbDirForTest(t)
	if d == "" {
		t.Skip("本机没有 data/akdb.sqlite（派生库，干净检出上本来就不在）⇒ 跳过")
	}
	t.Setenv("RIOS_DB", d)

	got, err := StageRows("", "main_00-01")
	if err != nil {
		t.Fatalf("StageRows 出错：%v", err)
	}
	//: ⚠ **关键字是子串筛，不是精确匹配**（`StageRows` 的 docstring 就是这么写的）。
	//: 实测：`%main_00-01%` **同时命中 `main_00-01#f#`（突袭档）** ⇒ 期望是 **2 行**，不是 1 行。
	//: 第一版测试写成「恰有 1 行」而红 —— 那是**测试的假设错**，不是取数错（SQL 精确匹配只有 1 行）。
	//: 这条语义留在断言里，免得下一个人重踩。
	if len(got) != 2 {
		t.Fatalf("正对照失败：`main_00-01` 作为**子串**应命中 2 行（本体 ＋ `#f#` 突袭档），实得 %d 行：%v",
			len(got), got)
	}
	seen := map[string]bool{}
	for _, r := range got {
		seen[r.LevelID] = true
	}
	for _, want := range []string{"main_00-01", "main_00-01#f#"} {
		if !seen[want] {
			t.Errorf("正对照：%q 不在结果里（实得 %v）", want, got)
		}
	}
	for _, r := range got {
		if r.Name == "" || r.ZoneID == "" {
			t.Errorf("正对照：%q 的 name=%q zone_id=%q —— 两列都不该是空的",
				r.LevelID, r.Name, r.ZoneID)
		}
	}

	miss, err := StageRows("", "no_such_level_id_zzz")
	if err != nil {
		t.Fatalf("负对照 StageRows 出错：%v", err)
	}
	if len(miss) != 0 {
		t.Fatalf("负对照失败：不存在的 id 应得 0 行，实得 %d 行 ⇒ 筛这一步没在筛", len(miss))
	}

	all, err := StageRows("", "")
	if err != nil {
		t.Fatalf("全表 StageRows 出错：%v", err)
	}
	if len(all) <= len(got) {
		t.Fatalf("全表应比单条筛更多：全表 %d 行 vs 单条 1 行", len(all))
	}
	for i := 1; i < len(all); i++ {
		if all[i-1].LevelID > all[i].LevelID {
			//: 排序键是 (zone_id, level_id)：同 zone 内 level_id 必须非降。
			if all[i-1].ZoneID == all[i].ZoneID {
				t.Fatalf("排序不稳：%q 排在 %q 之前", all[i-1].LevelID, all[i].LevelID)
			}
		}
	}
}

func TestZoneRows(t *testing.T) {
	d := dbDirForTest(t)
	if d == "" {
		t.Skip("本机没有 data/akdb.sqlite ⇒ 跳过")
	}
	t.Setenv("RIOS_DB", d)
	zs, err := ZoneRows()
	if err != nil {
		t.Fatalf("ZoneRows 出错：%v", err)
	}
	if len(zs) == 0 {
		t.Fatal("负对照失败：zone 表一行都没有 ⇒ 查询没跑成功")
	}
	for _, z := range zs {
		if z.ZoneID == "" {
			t.Fatalf("有 zone_id 为空的行：%+v", z)
		}
	}
}

// TestOpenReadOnlyMissingDB 是**缺库那一路**的对照：库不在 ⇒ 具名错误，不是空、不是崩。
func TestOpenReadOnlyMissingDB(t *testing.T) {
	t.Setenv("RIOS_DB", filepath.Join(t.TempDir(), "definitely-not-here"))
	_, err := OpenReadOnly("akdb")
	if err == nil {
		t.Fatal("库不在时 OpenReadOnly 竟然成功了")
	}
	if !errors.Is(err, ErrDBMissing) {
		t.Fatalf("库不在时应给 ErrDBMissing，实得：%v", err)
	}
}

// TestStageRowsKeywordIsLiteral 是 2026-09-26 那处 **LIKE 通配符 bug 的判别对照**。
//
// 参照实现做的是**字面量子串**匹配（`ak_tactic/db/stages.py:769-772`）：
// `keyword="%"` 在它那里**匹配不到任何一列** ⇒ **0 行**。
// 而旧实现把它交给 SQL `LIKE '%'||?||'%'` ⇒ `%` 是通配符 ⇒ **全表**。
//
// 这正是「一条能红得起来的判据」：把 `stageRowHasKeyword` 换回 `LIKE`，这条立刻红。
// 顺带钉住 `_`（LIKE 里同样是通配符）。
//
// ⚠ **`_` 不是判别用例**（第一版把它写进来，测试当场红，是我的期望错）：`_` **真实出现**在
// 几乎每一个 `level_id` 里（`main_00-01`、`easy_09-01`、`act31side_ex04`…）⇒ 字面量匹配下
// 它**本来就该命中全表 3055 行**。判别的只有 `%`（全库没有哪个 `level_id` 含 `%`）。
// 这条留在这里，免得下一个人再把它当 bug 修一遍。
func TestStageRowsKeywordIsLiteral(t *testing.T) {
	d := dbDirForTest(t)
	if d == "" {
		t.Skip("本机没有 data/akdb.sqlite ⇒ 跳过")
	}
	t.Setenv("RIOS_DB", d)
	for _, kw := range []string{"%", "%zz%"} {
		got, err := StageRows("", kw)
		if err != nil {
			t.Fatalf("StageRows(%q) 出错：%v", kw, err)
		}
		if len(got) != 0 {
			t.Fatalf("`keyword=%q` 应得 0 行（字面量匹配），实得 %d 行 ⇒ "+
				"筛选被当成了通配符，等于把筛悄悄关掉", kw, len(got))
		}
	}
	//: 正对照：同一个函数在正常词上**必须**能筛出来，否则上面那个 0 可能是「查询没跑成功」。
	ok, err := StageRows("", "MAIN_09-01")
	if err != nil {
		t.Fatalf("正对照出错：%v", err)
	}
	if len(ok) == 0 {
		t.Fatal("正对照失败：`MAIN_09-01` 应能筛出（大小写不敏感），实得 0 行")
	}
}
