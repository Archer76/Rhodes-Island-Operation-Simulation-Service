package data

// datachapter_golden_test.go：拿 `out/zz_golden.txt` 的 **CH 金标**逐条比。
//
// 这是「没有验证的直接重新验证」那条纪律的落点之一 —— 它一次把三处**未核**验掉：
//  1. `clean_activity_name` 没移植，`title` 的措辞到底一不一样；
//  2. `list_chapters` 的**整表顺序**（四元键）对不对；
//  3. `subtitle` 的「N 个部分」在真实数据上对不对。
//
// ★ 2026-09-27 金标**重取过一次**（两笔裁定同时动了它）：
//   · 建库白名单收紧 ⇒ CH 段 **116 → 69**（只留 18 主线含序章＋剿灭＋sre/side 活动）；
//   · 六星档加回取数面 ⇒ `levels` 与参照实现**同口径**（含 `#s`），
//     原来那条「Go 应比金标少 45」的预期差**作废**（见下面 MatchExactly 那条）。
//   重取脚本：`out/acceptance/_regolden_ch.py`（逐条来自 Python 的 `list_chapters`，
//   不是我手改数字）。
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
	p := filepath.Join("..", "..", "out", "zz_golden.txt")
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

// readGoldenZoneTitleEmpty 从同一份金标里读「zone_title 返回空串的 zone 数」。
//
// ★ 为什么从文件读而不是写在测试里：那是一个**事实**（参照实现量出来的），
// 而建库白名单一动它就变（2026-09-27：zone 352→258 ⇒ 31→15）。写死就是把同一个
// 事实存两份，改一处漏一处 —— 那一轮正是如此（金标改了、测试里还留着 31）。
// 金标不在（干净检出没有 `out/`）⇒ 跳过，与本文件里别的金标测试同一处置。
func readGoldenZoneTitleEmpty(t *testing.T) int {
	t.Helper()
	p := filepath.Join("..", "..", "out", "zz_golden.txt")
	f, err := os.Open(p)
	if err != nil {
		t.Skipf("没有 %s（out/ 不入库）⇒ 跳过", p)
	}
	defer f.Close()
	const pre = "zone_title 为空串的 zone 数 = "
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, pre) {
			continue
		}
		rest := strings.TrimPrefix(line, pre)
		num := rest
		if i := strings.IndexByte(rest, ' '); i > 0 {
			num = rest[:i]
		}
		n, err := strconv.Atoi(num)
		if err != nil {
			t.Fatalf("金标里那一行第 2 段不是数字：%q", line)
		}
		return n
	}
	t.Fatal("金标里没有「zone_title 为空串的 zone 数」那一行 ⇒ 解析没跑成功")
	return 0
}

// TestZoneTitleEmptyCountMatchesGolden：**计数型**金标（整族错一位就红）。
//
// 它守的是「`zoneTitle` 与参照实现的 `zone_title` 在同一批 zone 上给同一批空串」——
// 逐例那条（`TestZoneTitleGolden`）只覆盖样例，这条覆盖全族。
func TestZoneTitleEmptyCountMatchesGolden(t *testing.T) {
	want := readGoldenZoneTitleEmpty(t)
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
	if n != want {
		t.Fatalf("zone_title 返回空串的有 %d 个，金标 %d 个（zone 总数 %d）",
			n, want, len(zones))
	}
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

// TestGoldenChapterLevelsMatchExactly：`levels` 必须与金标**逐条相同**。
//
// ★ 2026-09-27 **反转**：这条原来叫 `…DifferByExactlySixStar`，判的是「Go 的合计
// 比金标少 45（被排除的 `#s` 数）」。博士把那笔「六星档不做」**推翻了** ——
// 15～17 章的六星是**险地作战**（等效突袭），加回取数面 ⇒ 那 45 条回到装载结果里，
// 「差恰好 45」这个前提**不存在了**。断言随之翻成**逐条相等**，比原来更严：
// 原来只判合计差多少，逐条对不对并没管。
func TestGoldenChapterLevelsMatchExactly(t *testing.T) {
	want := readGoldenCH(t)
	got := chaptersForTest(t)
	if len(got) != len(want) {
		t.Fatalf("条数不同：Go %d 条 vs 金标 %d 条", len(got), len(want))
	}
	sumW, sumG := 0, 0
	for i := range want {
		if got[i].Levels != want[i].Levels {
			t.Errorf("第 %d 条 %s：Go 的 levels=%d，金标 %d",
				i+1, want[i].Key, got[i].Levels, want[i].Levels)
		}
		sumW += want[i].Levels
		sumG += got[i].Levels
	}
	if sumW != sumG {
		t.Fatalf("关卡总数之差应为 0（六星已加回）：金标合计 %d、Go 合计 %d",
			sumW, sumG)
	}
}
