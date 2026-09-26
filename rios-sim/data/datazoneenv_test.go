package data

// datazoneenv_test.go：第二层的**金标对照**（`out/zz_golden.txt` 的 6 条 `ENV` 行）。
//
// ★ 这 6 个 zone 全在第 9～14 章，而那 45 个 `#s` 全在第 15～17 章
// ⇒ **六星档排除对这 6 条没有影响，应当逐格精确相同**。
// 这条正好把「裁定」与「本函数」分开验：若这里出现差值，那就**不是**裁定的必然结果，
// 而是本实现算错了。
//
// 另断言「本机库里没有表外的 diff_group」—— 那是对「未知值不静默丢」那条的**正对照**：
// 表外值一旦出现，这里会红，而不是悄悄排在后面没人知道。

import (
	"bufio"
	"os"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
)

type goldenENV struct {
	Zone  string
	Parts []ZoneEnv //: 顺序即金标顺序
}

func readGoldenENV(t *testing.T) []goldenENV {
	t.Helper()
	p := filepath.Join("..", "..", "out", "zz_golden.txt")
	f, err := os.Open(p)
	if err != nil {
		t.Skipf("没有 %s（out/ 不入库）⇒ 跳过", p)
	}
	defer f.Close()
	out := []goldenENV{}
	sc := bufio.NewScanner(f)
	sc.Buffer(make([]byte, 1<<20), 1<<20)
	for sc.Scan() {
		line := sc.Text()
		if !strings.HasPrefix(line, "ENV\t") {
			continue
		}
		f := strings.Split(line, "\t")
		if len(f) < 3 {
			t.Fatalf("ENV 行字段不足：%q", line)
		}
		parts := []ZoneEnv{}
		for _, cell := range strings.Split(f[2], "|") {
			//: 形如 `EASY:剧情体验:15`
			tri := strings.Split(cell, ":")
			if len(tri) != 3 {
				t.Fatalf("ENV 单元格格式不对：%q", cell)
			}
			n, err := strconv.Atoi(tri[2])
			if err != nil {
				t.Fatalf("ENV 单元格第三段不是数字：%q", cell)
			}
			parts = append(parts, ZoneEnv{Env: tri[0], Label: tri[1], Levels: n})
		}
		out = append(out, goldenENV{Zone: f[1], Parts: parts})
	}
	if len(out) == 0 {
		t.Fatal("金标里一条 ENV 都没读到 ⇒ 解析没跑成功")
	}
	return out
}

// TestZoneEnvsMatchesGolden：6 个 zone 的**内容、顺序、标签、条数**逐格相同。
func TestZoneEnvsMatchesGolden(t *testing.T) {
	want := readGoldenENV(t)
	stages, _ := stageTableForTest(t)
	for _, w := range want {
		got := ZoneEnvs(w.Zone, stages)
		if len(got) != len(w.Parts) {
			t.Fatalf("%s：分层数不同 Go=%d 金标=%d（Go=%v）", w.Zone, len(got), len(w.Parts), got)
		}
		for i := range w.Parts {
			if got[i] != w.Parts[i] {
				t.Fatalf("%s 第 %d 层不同：\n  Go   %+v\n  金标 %+v", w.Zone, i+1, got[i], w.Parts[i])
			}
		}
	}
	if len(want) != 6 {
		t.Fatalf("金标里应有 6 条 ENV（规格 §5 实测：6 个 zone 有分层），实得 %d", len(want))
	}
}

// TestZoneEnvsOnlyForThoseSixWithTwoOrMore：**界面那道闸是 `> 1` 不是 `> 0`** ——
// 除了金标那 6 个，其余 zone 要么空表、要么只有一个分层（不该显示这一层菜单）。
func TestZoneEnvsOnlyForThoseSixWithTwoOrMore(t *testing.T) {
	want := readGoldenENV(t)
	isGolden := map[string]bool{}
	for _, w := range want {
		isGolden[w.Zone] = true
	}
	stages, zones := stageTableForTest(t)
	shown := 0
	for _, z := range zones {
		envs := ZoneEnvs(z.ZoneID, stages)
		if ZoneEnvsShown(envs) {
			shown++
			if !isGolden[z.ZoneID] {
				t.Fatalf("zone %s 的分层 >=2（%v）却不在金标里 ⇒ 金标那 6 条不是全集", z.ZoneID, envs)
			}
		}
	}
	if shown != len(want) {
		t.Fatalf("显示这一层菜单的 zone 数应为 %d（金标条数），实得 %d", len(want), shown)
	}
}

// TestNoUnknownDiffGroup：本机库里**没有**表外的 `diff_group` 值。
//
// 这是「未知值不静默丢」那条的**正对照**：ZoneEnvs 会把表外值排在末尾，
// 所以这里一旦出现表外值就红 —— 而不是悄悄排在后面没人知道。
func TestNoUnknownDiffGroup(t *testing.T) {
	stages, _ := stageTableForTest(t)
	known := map[string]bool{}
	for _, e := range envOrder {
		known[e] = true
	}
	known["NONE"] = true
	known[""] = true
	seen := map[string]bool{}
	for _, r := range stages {
		g := strings.ToUpper(strings.TrimSpace(r.DiffGroup))
		if !known[g] && !seen[g] {
			seen[g] = true
			t.Errorf("库里出现了表外的 diff_group=%q ⇒ 要么补进 envOrder/envLabels，要么登记它", g)
		}
	}
}
