package main

// selfcell_test.go：**自身格判据**（"攻击范围要不要含自身格"）的钉子。
//
// 这条判据反复被改过向（先"阻挡数 > 0"、再说"无条件补"、最后定成"只有要塞"），
// 所以这里把它钉死：**要塞补、攻城手不补**，两边的正反例都摆上。
//
// 判据的来由（wiki 原文、飞行敌人、为什么不是阻挡数）写在
// `operators.go::operatorCoversSelfCell` 的注释里，这里只钉行为。

import (
	"os"
	"path/filepath"
	"testing"
)

// chdirRepoRoot 把 cwd 切到仓根（`data/gamedata` 在那儿），测完切回；
// 干净检出上没有 `data/` ⇒ **具名 skip**（缺件不是红，与 `arrivals_test.go` 同口径）。
//
// ⚠ 与 `arrivals_test.go:126-140` 同一个理由：引擎的 gamedata 路径是**相对 cwd**
// 拼的，而 `go test` 的 cwd 是**包目录** ⇒ 不处置的话数据类用例会被静默 skip，
// 而 skip 出来的绿等于没测。所以这里**主动**找仓根，找不到才 skip。
func chdirRepoRoot(t *testing.T) {
	t.Helper()
	//: `_level_index.json` 直接躺在 `data/gamedata/` 下（`character_table.json` 不，
	//: 它在 `data/gamedata/raw.githubusercontent.com/excel/` 里）——判在场要用这一个。
	probe := filepath.Join("data", "gamedata", "_level_index.json")
	if _, err := os.Stat(probe); err == nil {
		return
	}
	wd, werr := os.Getwd()
	if werr != nil {
		t.Fatalf("取 cwd 失败：%v", werr)
	}
	root := filepath.Dir(wd)
	if _, e := os.Stat(filepath.Join(root, probe)); e != nil {
		t.Skipf("没有 %s（干净检出上没有 data/）⇒ 跳过", probe)
	}
	if cerr := os.Chdir(root); cerr != nil {
		t.Fatalf("切到仓根失败：%v", cerr)
	}
	t.Cleanup(func() { _ = os.Chdir(wd) })
}

// TestOperatorCoversSelfCell 钉住判据本身：只有 `fortress` 为真。
//
// 正反例都是**具名**的：要塞 3 位（4-5/4-6，裸表缺自身格）、攻城手 2 位
// （4-3/4-4，裸表同样缺自身格却**不该**补）、另两位普通干员的代号本来就含
// 自身格（判据也必须是 false —— 补了是恒等，但"要不要补"这件事是 false）。
func TestOperatorCoversSelfCell(t *testing.T) {
	chdirRepoRoot(t)

	cases := []struct {
		charID string
		why    string
		want   bool
	}{
		{"char_4039_horn", "号角 · fortress(4-6) ⇒ 补（wiki 复合范围）", true},
		{"char_493_firwhl", "火哨 · fortress(4-6) ⇒ 补", true},
		{"char_431_ashlok", "灰毫 · fortress(4-6) ⇒ 补", true},
		{"char_2012_typhon", "提丰 · siegesniper(4-3) ⇒ 不补（打不到头顶飞行）", false},
		{"char_4062_totter", "铅踝 · siegesniper(4-4) ⇒ 不补", false},
		{"char_136_hsguma", "星熊 · protector ⇒ 不补（代号本就含自身格）", false},
		{"char_103_angel", "能天使 · fastshot ⇒ 不补（同上）", false},
	}
	for _, c := range cases {
		got, err := operatorCoversSelfCell(c.charID)
		if err != nil {
			t.Errorf("%s（%s）判据报错：%v", c.charID, c.why, err)
			continue
		}
		if got != c.want {
			t.Errorf("%s（%s）：coversSelf = %v，要 %v", c.charID, c.why, got, c.want)
		}
	}

	//: 装置（`trap_*`）在 `character_table` 里**有**，但不在 `loadCharTable()` 的表里
	//: （那里只留 `char_` 前缀，`operator.go:191`）⇒ 判据必须**具名失败**，
	//: 不许静默给 false。它是「装置够不着干员路径」这条的结构性证据。
	if _, err := operatorCoversSelfCell("trap_493_xbabal"); err == nil {
		t.Errorf("装置 trap_493_xbabal 应当查不到（loadCharTable 只留 char_）⇒ 要报错，实得 nil")
	}
}

// TestWithSelfCell 钉住补格本身的三条性质。
func TestWithSelfCell(t *testing.T) {
	bare := []Cell{{1, 0}, {2, 0}} //: 不含自身格（形如 4-6 那种表）
	with := []Cell{{0, 0}, {1, 0}} //: 本来就含自身格

	//: ① 判据为假 ⇒ 原样返回（连切片都不该换）。
	if got := withSelfCell(bare, false); len(got) != 2 || got[0] != (Cell{1, 0}) {
		t.Errorf("coversSelf=false 时不该动：实得 %v", got)
	}

	//: ② 判据为真且表里没有 ⇒ 补上 (0,0)，长度 +1。
	got := withSelfCell(bare, true)
	if len(got) != 3 {
		t.Fatalf("coversSelf=true 应补一格：实得 %v", got)
	}
	found := false
	for _, c := range got {
		if c == (Cell{0, 0}) {
			found = true
		}
	}
	if !found {
		t.Errorf("补完仍没有 (0,0)：%v", got)
	}

	//: ③ 判据为真但表里**已经有** (0,0) ⇒ 恒等，**不加倍**。
	//: 73 个代号里 64 个走这一支，加倍会让 dwell 把同一段时间算两遍。
	got2 := withSelfCell(with, true)
	if len(got2) != 2 {
		t.Errorf("表里已有 (0,0) 时不该加倍：实得 %v", got2)
	}
	n := 0
	for _, c := range got2 {
		if c == (Cell{0, 0}) {
			n++
		}
	}
	if n != 1 {
		t.Errorf("(0,0) 出现 %d 次，要 1", n)
	}

	//: ④ **不许复用入参的底层数组**：`rangeTbl[code]` 是缓存，往它上面写就是污染
	//: 全进程的下一批查询。故意给足 cap —— 就地 `append` 在 cap 够时不会报错，
	//: 只会悄悄改掉缓存。
	orig := make([]Cell, 2, 8)
	orig[0], orig[1] = Cell{1, 0}, Cell{2, 0}
	got3 := withSelfCell(orig, true)
	if len(orig) != 2 || orig[0] != (Cell{1, 0}) || orig[1] != (Cell{2, 0}) {
		t.Errorf("withSelfCell 动了入参：%v", orig)
	}
	if len(got3) == 3 && &got3[0] == &orig[0] {
		t.Errorf("补格时复用了入参的底层数组（会污染 range_table 缓存）")
	}
}
