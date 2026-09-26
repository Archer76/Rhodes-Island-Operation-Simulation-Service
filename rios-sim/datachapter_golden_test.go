package main

// datachapter_golden_test.go：拿 `out/zz_golden.txt` 的 **116 条 CH 金标**逐条比。
//
// 这是「没有验证的直接重新验证」那条纪律的落点之一 —— 它一次把三处**未核**验掉：
//  1. `clean_activity_name` 没移植，`title` 的措辞到底一不一样；
//  2. `list_chapters` 的**整表顺序**（四元键）对不对；
//  3. `subtitle` 的「N 个部分」在真实数据上对不对。
//
// ★ 预期差：金标的 `levels` 是参照实现的 `totals`，**含 `#s`**；本实现因博士 2026-09-26
// 裁定排除六星档 ⇒ **每条的 levels 应 ≤ 金标，且总量之差恰好等于被排除的 `#s` 数（45）**。
// 这条断言把「裁定」与「实现」钉在一起：差不是 45 就说明要么裁定没落实、要么多滤了。
//
// 金标在 `out/`（不入库）⇒ 不在就跳过（与 `data/*.sqlite` 同一处置）。

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

type goldenCH struct {
	Key, Title, Subtitle string
	Levels               int
}

func readGoldenCH(t *testing.T) []goldenCH {
	t.Helper()
	p := filepath.Join("..", "out", "zz_golden.txt")
	f, err := os.Open(p)
	if err != nil {
		t.Skipf("没有 %s（out/ 不入库）⇒ 跳过", p)
	}
	defer f.Close()
	out := []goldenCH{}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "CH\t") {
			continue
		}
		f := strings.Split(line, "\t")
		if len(f) < 5 {
			t.Fatalf("CH 行字段不足 %d 个：%q", len(f), line)
		}
		n, err := strconv.Atoi(f[4])
		if err != nil {
			t.Fatalf("CH 行第 5 格不是数字：%q", line)
		}
		out = append(out, goldenCH{Key: f[1], Title: f[2], Subtitle: f[3], Levels: n})
	}
	if len(out) == 0 {
		t.Fatal("金标里一条 CH 都没读到 ⇒ 解析没跑成功（不是「没有章节」那种有意义的 0）")
	}
	return out
}

// TestGoldenChapterOrderTitleSubtitle：**顺序／key／title／subtitle 必须逐条相同**。
func TestGoldenChapterOrderTitleSubtitle(t *testing.T) {
	want := readGoldenCH(t)
	got := chaptersForTest(t)
	if len(got) != len(want) {
		t.Fatalf("条数不同：Go %d 条 vs 金标 %d 条", len(got), len(want))
	}
	bad := 0
	for i := range want {
		w, g := want[i], got[i]
		if w.Key != g.Key || w.Title != g.Title || w.Subtitle != g.Subtitle {
			bad++
			if bad <= 6 {
				t.Errorf("第 %d 条不同：\n  金标 key=%q title=%q subtitle=%q\n  Go   key=%q title=%q subtitle=%q",
					i+1, w.Key, w.Title, w.Subtitle, g.Key, g.Title, g.Subtitle)
			}
		}
	}
	if bad > 0 {
		t.Fatalf("共 %d / %d 条在 key／title／subtitle／顺序 上不同", bad, len(want))
	}
}

// TestGoldenChapterLevelsDifferByExactlySixStar：`levels` 之差**恰好等于被排除的 `#s` 数**。
//
// 这条是把「六星档排除」这条裁定钉在实现上的判据：
//
//	· 差为 0 ⇒ 裁定**没落实**（六星还在数）；
//	· 差 > 45（或某条 Go 比金标还大）⇒ 多滤了别的东西；
//	· 差恰好 45 ⇒ 两边对得上。
func TestGoldenChapterLevelsDifferByExactlySixStar(t *testing.T) {
	want := readGoldenCH(t)
	got := chaptersForTest(t)
	sumW, sumG := 0, 0
	for i := range want {
		if got[i].Levels > want[i].Levels {
			t.Fatalf("第 %d 条 %s：Go 的 levels=%d **大于**金标 %d ⇒ 多算或算错",
				i+1, want[i].Key, got[i].Levels, want[i].Levels)
		}
		sumW += want[i].Levels
		sumG += got[i].Levels
	}
	if d := sumW - sumG; d != 45 {
		t.Fatalf("关卡总数之差应为 45（被排除的 #s 数）：金标合计 %d、Go 合计 %d、差 %d",
			sumW, sumG, d)
	}
}
