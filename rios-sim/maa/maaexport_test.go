package maa

import (
	"bytes"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"rios-sim/core"
	"rios-sim/data"
)

// firstDiff 报出**首处**不同及其上下文 —— 逐字节判据红的时候，
// 光看两份 2 KB 的 JSON 找不出是哪一处，这条能一句话定位。
func firstDiff(got, want []byte) string {
	n := len(got)
	if len(want) < n {
		n = len(want)
	}
	for i := 0; i < n; i++ {
		if got[i] != want[i] {
			lo := i - 70
			if lo < 0 {
				lo = 0
			}
			ghi, whi := i+70, i+70
			if ghi > len(got) {
				ghi = len(got)
			}
			if whi > len(want) {
				whi = len(want)
			}
			return fmt.Sprintf("首处差异在第 %d 字节（共 got %d / want %d）\n  got  前:%q\n  got  后:%q\n  want 前:%q\n  want 后:%q",
				i, len(got), len(want), got[lo:i], got[i:ghi], want[lo:i], want[i:whi])
		}
	}
	return fmt.Sprintf("前缀全同，长度不同：got %d / want %d", len(got), len(want))
}

// 本文件是 MAA 导出（`maaexport.go`）的判据。**参照实现是 Python 的
// `ak_tactic/maa_export.py`**，黄金夹具由 `out/zz_maa_golden.py` 真跑一遍 Python 产出，
// 逐字节搬进 `testdata/`（`out/` 不是持久目录，判据不许依赖它）。
//
// 判据分三层，缺一层就会有一条看不见的假绿：
//   - **负对照**（尺子必须能判红）——`TestGoldenRulerCanFail`；
//   - **逐字节**（最强的形状判据）——两条 golden；
//   - **具名分歧**（红是对的那一条）——练度取不到时 Go 写 0、Python 印 None。

func ptr[T any](v T) *T { return &v }

// goldenPlan 与 `out/zz_maa_golden.py` 里那份 Plan 逐字段相同。
func goldenPlan() core.PlayPlan {
	return core.PlayPlan{
		Stage: "act54side_ex08",
		Deploys: []core.DeployOrder{
			{Operator: "赤刃明霄陈", Position: [2]int{4, 2}, Direction: "Left", Skill: 3,
				Mastery: 3, Elite: ptr(2), Level: ptr(90), Potential: ptr(2),
				Module: ptr("uniequip_002_chen3"), Time: ptr(10.0)},
			{Operator: "予愿安洁莉娜", Position: [2]int{1, 4}, Direction: "Right", Skill: 3,
				Mastery: 3, Elite: ptr(2), Level: ptr(60), Potential: ptr(1),
				Time: ptr(28.0)},
			{Operator: "圣聆初雪", Position: [2]int{10, 4}, Direction: "Right", Skill: 2,
				Mastery: 3, Elite: ptr(2), Level: ptr(90), Potential: ptr(1),
				Module: ptr("uniequip_002_sbell2"), Time: ptr(71.0)},
		},
	}
}

// goldenRoster 与生成脚本里那份名册逐字段相同（注意 potential 与 plan 不同：
// 陈 名册 3 / 打法 2 ⇒ `_pick` 取打法的 2，黄金里 `"potential": 2` 就是这么来的）。
func goldenRoster() *core.RosterRead {
	return &core.RosterRead{Entries: []core.RosterEntry{
		{Name: "赤刃明霄陈", CharID: "char_1050_chen3", Elite: 2, Level: 90, Potential: 3,
			Module: ptr("uniequip_002_chen3"), ModuleLevel: 3},
		{Name: "予愿安洁莉娜", CharID: "char_1015_aglna2", Elite: 2, Level: 60, Potential: 1},
		{Name: "圣聆初雪", CharID: "char_1046_sbell2", Elite: 2, Level: 90, Potential: 1,
			Module: ptr("uniequip_002_sbell2"), ModuleLevel: 0},
	}}
}

// handTable 是一张**手搭的**模组表，只给不需要证明「库里的值」的那些用例用
// （值抄自 `testdata/operator_texts.txt`，所以它不能用来证明模组名本身）。
func handTable() map[string]ModuleInfo {
	return map[string]ModuleInfo{
		"uniequip_002_chen3":  {ModuleID: "uniequip_002_chen3", Name: "记忆残页", TypeName2: "X"},
		"uniequip_002_sbell2": {ModuleID: "uniequip_002_sbell2", Name: "千分之一的心", TypeName2: "Y"},
	}
}

func readFixture(t *testing.T, name string) []byte {
	t.Helper()
	blob, err := os.ReadFile(filepath.Join("testdata", name))
	if err != nil {
		t.Fatalf("读夹具 %s 失败：%v", name, err)
	}
	// ⚠ 夹具在盘上是 **CRLF**：它们由 `out/zz_maa_golden.py` 用 Python 的
	// `Path.write_text` 写出，而 Windows 上文本模式会把 `\n` 翻成 `\r\n`。
	// 那是**写盘产物**，不是 Python 生成的那份 JSON 正文本身 ⇒ 归一成 LF 再比。
	// 文件级的那条分歧（Python 写 CRLF / Go 写 LF）单独立了判据，见
	// `TestLineEndingDivergence` —— 归一化不许把那条分歧一起藏掉。
	return bytes.ReplaceAll(blob, []byte("\r\n"), []byte("\n"))
}

// openDB 打开只读库；库不在就跳过（照 `datadb_test.go` 的范式：缺库不是红）。
func openDB(t *testing.T) *sql.DB {
	t.Helper()
	db, err := data.OpenReadOnly("akdb")
	if err != nil {
		if errors.Is(err, data.ErrDBMissing) {
			t.Skipf("缺 data/akdb.sqlite，跳过需要库的用例（%v）", err)
		}
		t.Fatalf("开库失败：%v", err)
	}
	t.Cleanup(func() { db.Close() })
	return db
}

// sections 把 `=== 名字 ===` 分节的夹具切成块。
func sections(t *testing.T, name string) map[string][]string {
	t.Helper()
	out := map[string][]string{}
	cur := ""
	for _, line := range strings.Split(string(readFixture(t, name)), "\n") {
		if strings.HasPrefix(line, "=== ") && strings.HasSuffix(line, " ===") {
			cur = strings.TrimSuffix(strings.TrimPrefix(line, "=== "), " ===")
			out[cur] = []string{}
			continue
		}
		if cur != "" && line != "" {
			out[cur] = append(out[cur], line)
		}
	}
	return out
}

// ------------------------------------------------------------------ 负对照

// TestGoldenRulerCanFail 是**尺子的负对照**：把黄金文件改动一个字节，
// 逐字节比较必须判红。它不通过就说明下面那些「相同」全是假的。
func TestGoldenRulerCanFail(t *testing.T) {
	want := readFixture(t, "maajob_golden.json")
	job, err := ToMaa(goldenPlan(), nil, handTable(), nil,
		MaaOptions{Difficulty: "NORMAL", Title: "测试", Details: "详情"})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	got, err := MarshalJob(job)
	if err != nil {
		t.Fatalf("序列化失败：%v", err)
	}
	// 正：与黄金不同（因为这一份没带名册，skill_usage 那处就不同）
	if bytes.Equal(got, want) {
		t.Fatalf("负对照失效：不带名册的输出竟然与带名册的黄金逐字节相同，说明尺子没在比")
	}
	// 再证「同一份输入比得出相同」：把 want 自己当输入，比较器必须给真。
	if !bytes.Equal(want, want) {
		t.Fatalf("比较器本身坏了")
	}
	// 改一个字节 ⇒ 必须判红
	mutated := append([]byte(nil), want...)
	if mutated[0] != '{' {
		t.Fatalf("黄金首字节不是 {，夹具形状可疑：%q", mutated[0])
	}
	mutated[0] = '['
	if bytes.Equal(mutated, want) {
		t.Fatalf("改了一个字节之后竟然还判相同 —— 逐字节判据是假的")
	}
	t.Logf("负对照成立：黄金 %d 字节，改首字节后判不同；不带名册时输出 %d 字节亦不同",
		len(want), len(got))
}

// ------------------------------------------------------------------ 逐字节

// TestGoldenNoRoster 走 `roster=None` 那条退化路，**不需要库**
// （模组表由 handTable 提供；这也意味着它证明的是排版与组装，不是库里的值）。
func TestGoldenNoRoster(t *testing.T) {
	want := readFixture(t, "maajob_golden_noroster.json")
	job, err := ToMaa(goldenPlan(), nil, handTable(), nil,
		MaaOptions{Difficulty: "NORMAL", Title: "测试", Details: "详情"})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	got, err := MarshalJob(job)
	if err != nil {
		t.Fatalf("序列化失败：%v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("与黄金不逐字节相同：%s", firstDiff(got, want))
	}
}

// TestGoldenWithRoster 是**最强的那条**：真库取模组表、真库查 skill_usage，
// 与 Python 的黄金逐字节相同。
func TestGoldenWithRoster(t *testing.T) {
	db := openDB(t)
	want := readFixture(t, "maajob_golden.json")
	job, err := ToMaa(goldenPlan(), goldenRoster(), nil, db,
		MaaOptions{Difficulty: "NORMAL", Title: "测试", Details: "详情"})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	got, err := MarshalJob(job)
	if err != nil {
		t.Fatalf("序列化失败：%v", err)
	}
	if !bytes.Equal(got, want) {
		t.Fatalf("与黄金不逐字节相同：%s", firstDiff(got, want))
	}
	// 顺带把那条**登记的**分歧钉在明处：黄金里 skill_usage 是 1/1/0，
	// 第三位（圣聆初雪技2，AUTO）必须是 0 —— 写成 1 就说明分流坏了。
	if job.Opers[2].SkillUsage != 0 {
		t.Fatalf("圣聆初雪技2 是 AUTO，skill_usage 必须是 0，实得 %d", job.Opers[2].SkillUsage)
	}
}

// ------------------------------------------------------------------ 文本三件

// TestTexts 用**真库**的模组表渲染三份人读文字，与 Python 的原样输出逐行相同。
func TestTexts(t *testing.T) {
	db := openDB(t)
	tbl, err := ModuleTable(db)
	if err != nil {
		t.Fatalf("取模组表失败：%v", err)
	}
	ops, err := UsedOperators(goldenPlan(), goldenRoster(), tbl)
	if err != nil {
		t.Fatalf("取干员失败：%v", err)
	}
	sec := sections(t, "operator_texts.txt")

	if got, want := OperatorsReport(ops), sec["operators_report"]; !equalLines(got, want) {
		t.Fatalf("operators_report 不一致。\n--- got ---\n%s\n--- want ---\n%s",
			strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if got, want := OperatorsLines(ops), sec["operators_lines"]; !equalLines(got, want) {
		t.Fatalf("operators_lines 不一致。\n--- got ---\n%s\n--- want ---\n%s",
			strings.Join(got, "\n"), strings.Join(want, "\n"))
	}
	if got, want := OperatorsBrief(ops), sec["operators_brief"][0]; got != want {
		t.Fatalf("operators_brief 不一致。\n got=%s\nwant=%s", got, want)
	}
	// 四个特殊串逐一点名（它们分别是空表、空打法、带等级的模组、无等级的模组）
	report := strings.Join(OperatorsReport(ops), "\n")
	for _, s := range []string{"记忆残页 X 3", "千分之一的心 Y -", "无"} {
		if !strings.Contains(report, s) {
			t.Fatalf("人读表里少了特殊串 %q：\n%s", s, report)
		}
	}
}

// TestEmptyPlanTexts 空打法的两句固定文字（夹具里是 Python 的 repr，这里比字面量）。
func TestEmptyPlanTexts(t *testing.T) {
	sec := sections(t, "operator_texts.txt")
	joined := strings.Join(sec["空打法"], "\n")
	for _, s := range []string{"（这份打法里没有部署任何干员）", "（无干员）"} {
		if !strings.Contains(joined, s) {
			t.Fatalf("夹具里没有 %q，取材错了", s)
		}
	}
	if got := OperatorsReport(nil); len(got) != 1 || got[0] != "（这份打法里没有部署任何干员）" {
		t.Fatalf("空表的 report 不对：%v", got)
	}
	if got := OperatorsLines(nil); len(got) != 1 || got[0] != "（这份打法里没有部署任何干员）" {
		t.Fatalf("空表的 lines 不对：%v", got)
	}
	if got := OperatorsBrief(nil); got != "（无干员）" {
		t.Fatalf("空表的 brief 不对：%q", got)
	}
}

func equalLines(a, b []string) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

// ------------------------------------------------------------------ difficulty

// TestDifficultyCodes 八路逐条对齐夹具（含 `SIX_STAR` 与 `EASY` 都是 0）。
func TestDifficultyCodes(t *testing.T) {
	cases := []struct {
		in   string
		want int
	}{
		{"NORMAL", 1}, {"FOUR_STAR", 2}, {"EASY", 0}, {"SIX_STAR", 0},
		{"normal", 1}, {"", 0}, {" four_star ", 2},
	}
	for _, c := range cases {
		if got := DifficultyCode(c.in); got != c.want {
			t.Fatalf("DifficultyCode(%q) = %d，要 %d", c.in, got, c.want)
		}
	}
	// 负对照：夹具里八路的读数必须与我这份表逐条相符，否则是我抄错了期望值
	sec := sections(t, "operator_texts.txt")
	joined := strings.Join(sec["difficulty 各路"], "\n")
	for _, s := range []string{"difficulty_code('NORMAL') = 1", "difficulty_code('SIX_STAR') = 0",
		"difficulty_code(' four_star ') = 2", "difficulty_code('') = 0"} {
		if !strings.Contains(joined, s) {
			t.Fatalf("夹具里没有 %q，我的期望值来源不明", s)
		}
	}
	// `difficulty` 为 0 时整个键消失（写 0 会让 MAA 那边的读法变味）
	job, err := ToMaa(goldenPlan(), goldenRoster(), handTable(), nil, MaaOptions{})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	blob, _ := MarshalJob(job)
	if bytes.Contains(blob, []byte(`"difficulty"`)) {
		t.Fatalf("difficulty 为 0 时这个键必须整个消失，实得：\n%s", blob)
	}
}

// ------------------------------------------------------------------ 模组编号

// TestModuleNumbers 正负对照：真库里那 5 个已知 id 的读数与夹具逐条相同。
//
// 正：chen3→X/1、sbell2→Y/2、logos→D/4（D 是原项目**漏掉**的那一类）。
// 负：两枚 `uniequip_001_*` 证章（typeName2 为空）⇒ type/slot 都是 nil，
//
//	不存在的 id ⇒ 全 nil。
func TestModuleNumbers(t *testing.T) {
	db := openDB(t)
	tbl, err := ModuleTable(db)
	if err != nil {
		t.Fatalf("取模组表失败：%v", err)
	}
	type want struct {
		typ  string // "" 表示 nil
		name string
		slot int // 0 表示 nil
	}
	cases := map[string]want{
		"uniequip_002_chen3":  {"X", "记忆残页", 1},
		"uniequip_001_chen3":  {"", "赤刃明霄陈证章", 0},
		"uniequip_002_sbell2": {"Y", "千分之一的心", 2},
		"uniequip_002_logos":  {"D", "来自河谷的笔盒", 4},
		"uniequip_001_angel":  {"", "能天使证章", 0},
		"uniequip_999_nope":   {"", "", 0},
	}
	for id, w := range cases {
		gotType := ModuleType(tbl, &id)
		gotName := ModuleName(tbl, &id)
		gotSlot := ModuleSlot(tbl, &id)
		if (gotType == nil) != (w.typ == "") || (gotType != nil && *gotType != w.typ) {
			t.Errorf("%s 的 type = %v，要 %q", id, derefStr(gotType), w.typ)
		}
		if (gotName == nil) != (w.name == "") || (gotName != nil && *gotName != w.name) {
			t.Errorf("%s 的 name = %v，要 %q", id, derefStr(gotName), w.name)
		}
		if (gotSlot == nil) != (w.slot == 0) || (gotSlot != nil && *gotSlot != w.slot) {
			t.Errorf("%s 的 slot = %v，要 %d", id, derefInt(gotSlot), w.slot)
		}
	}
	// 空与 nil 也是「取不到」，不是「查得到但为空」
	empty := ""
	if ModuleType(tbl, &empty) != nil || ModuleName(tbl, &empty) != nil || ModuleSlot(tbl, &empty) != nil {
		t.Fatalf("空串 module id 必须全取不到")
	}
	if ModuleType(tbl, nil) != nil || ModuleName(tbl, nil) != nil || ModuleSlot(tbl, nil) != nil {
		t.Fatalf("nil module id 必须全取不到")
	}
}

func derefStr(p *string) string {
	if p == nil {
		return "<nil>"
	}
	return *p
}

func derefInt(p *int) int {
	if p == nil {
		return -1
	}
	return *p
}

// TestModuleDistribution 现查类型分布：既证明查询真跑成功了（X=301 必须出现），
// 又证明 `Z` 确实是死项（0 条）。
func TestModuleDistribution(t *testing.T) {
	db := openDB(t)
	var total int
	if err := db.QueryRow(`select count(*) from module`).Scan(&total); err != nil {
		t.Fatalf("数 module 行失败：%v", err)
	}
	if total == 0 {
		t.Fatalf("module 表 0 行 —— 查询跑成功了但库是空的，分布判据无从谈起")
	}
	for _, c := range []struct {
		letter string
		want   int
	}{{"X", 301}, {"Y", 181}, {"A", 20}, {"D", 6}, {"B", 1}, {"Z", 0}} {
		var n int
		if err := db.QueryRow(
			`select count(*) from module where type_name2 = ?`, c.letter).Scan(&n); err != nil {
			t.Fatalf("数 %s 失败：%v", c.letter, err)
		}
		if n != c.want {
			t.Errorf("type_name2 = %s 有 %d 条，规格记的是 %d（库变了就重取并改规格）",
				c.letter, n, c.want)
		}
	}
	var nulls int
	if err := db.QueryRow(`select count(*) from module where type_name2 is null`).Scan(&nulls); err != nil {
		t.Fatalf("数 NULL 失败：%v", err)
	}
	if nulls != 396 {
		t.Errorf("type_name2 为 NULL 的有 %d 条，规格记的是 396", nulls)
	}
	// 正对照：五个字母加起来必须小于全表（否则说明有的行没字母，与 396 那条冲突）
	sum := 301 + 181 + 20 + 6 + 1
	if sum+nulls != total {
		t.Errorf("五个字母 %d + NULL %d ≠ 全表 %d —— 有一类既没字母也没被算成 NULL", sum, nulls, total)
	}
}

// ------------------------------------------------------------------ skill_usage

// TestSkillUsage 全部期望值来自夹具（它们由 `out/zz_schema_probe5.txt` 的 SQL
// **独立算出**，不是拿 Python 的输出当期望值）。
func TestSkillUsage(t *testing.T) {
	db := openDB(t)
	cases := []struct {
		charID string
		slot   int
		want   int
	}{
		{"char_1050_chen3", 3, 1},  // MANUAL
		{"char_1050_chen3", 1, 1},  // MANUAL
		{"char_1046_sbell2", 2, 0}, // AUTO —— 唯一填 0 的那一类
		{"char_1046_sbell2", 1, 1}, // MANUAL
		{"char_1015_aglna2", 1, 1}, // PASSIVE ⇒ 不是 AUTO ⇒ 1
		{"char_1050_chen3", 0, 0},  // slot 0 先于一切
		{"char_zzz_nope", 1, 1},    // 查不到的干员
		{"", 3, 1},                 // 名册里缺 char_id
		{"char_1046_sbell2", 9, 1}, // 越界槽号
	}
	for _, c := range cases {
		if got := SkillUsage(db, c.charID, c.slot); got != c.want {
			t.Errorf("SkillUsage(%q, %d) = %d，要 %d", c.charID, c.slot, got, c.want)
		}
	}
	// 负对照：库里确实同时存在 AUTO 与 MANUAL 两种，否则上面「0 只出现在一处」
	// 可能只是因为整库都没有 AUTO。
	var nAuto, nManual int
	if err := db.QueryRow(`select count(*) from skill_level where level = 7 and skill_type = 'AUTO'`).Scan(&nAuto); err != nil {
		t.Fatalf("数 AUTO 失败：%v", err)
	}
	if err := db.QueryRow(`select count(*) from skill_level where level = 7 and skill_type = 'MANUAL'`).Scan(&nManual); err != nil {
		t.Fatalf("数 MANUAL 失败：%v", err)
	}
	if nAuto == 0 || nManual == 0 {
		t.Fatalf("AUTO=%d MANUAL=%d —— 两类必须都有，否则这条判据分不出好坏", nAuto, nManual)
	}
	t.Logf("库里 level=7 的 AUTO %d 条 / MANUAL %d 条", nAuto, nManual)
}

// ------------------------------------------------------------------ 惰性

// TestLazyModuleTable 复刻 Python 的懒加载，并配一条**反例**。
//
// 正：没人带模组 ⇒ 连库都不需要（这里干脆给 nil），导出照样成功。
// 反：有人带模组且没有库 ⇒ 必须**具名失败**（`data.ErrDBMissing`），
//
//	不许静默退化成「无模组」—— 那会让 MAA 少一条要求。
func TestLazyModuleTable(t *testing.T) {
	plan := core.PlayPlan{Stage: "s", Deploys: []core.DeployOrder{
		{Operator: "甲", Position: [2]int{1, 1}, Direction: "Right", Skill: 0},
	}}
	job, err := ToMaa(plan, nil, nil, nil, MaaOptions{})
	if err != nil {
		t.Fatalf("没人带模组时不该碰库，却失败了：%v", err)
	}
	blob, _ := MarshalJob(job)
	if bytes.Contains(blob, []byte(`"module"`)) {
		t.Fatalf("没人带模组时 requirements 里不该出现 module 键：\n%s", blob)
	}

	plan.Deploys[0].Module = ptr("uniequip_002_chen3")
	if _, err := ToMaa(plan, nil, nil, nil, MaaOptions{}); !errors.Is(err, data.ErrDBMissing) {
		t.Fatalf("有人带模组且没有库时必须报 ErrDBMissing，实得 %v", err)
	}
	// 负对照：同一份有人带模组的 plan，给了表就必须成功
	if _, err := ToMaa(plan, nil, handTable(), nil, MaaOptions{}); err != nil {
		t.Fatalf("给了模组表之后必须成功，实得 %v", err)
	}
}

// TestNoDeploys 空打法导出没有意义（对齐 Python 的 MaaExportError）。
func TestNoDeploys(t *testing.T) {
	if _, err := ToMaa(core.PlayPlan{Stage: "s"}, nil, nil, nil, MaaOptions{}); !errors.Is(err, ErrNoDeploys) {
		t.Fatalf("空打法必须报 ErrNoDeploys，实得 %v", err)
	}
}

// ------------------------------------------------------------------ 落盘

// TestWriteJob 序号追加、非法字符替换、空关卡名退路，以及**写出去能被读回来**。
func TestWriteJob(t *testing.T) {
	dir := t.TempDir()
	job, err := ToMaa(goldenPlan(), goldenRoster(), handTable(), nil, MaaOptions{})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	p1, err := WriteJob(job, dir, "SR-EX-8")
	if err != nil {
		t.Fatalf("第一次写失败：%v", err)
	}
	p2, err := WriteJob(job, dir, "SR-EX-8")
	if err != nil {
		t.Fatalf("第二次写失败：%v", err)
	}
	if filepath.Base(p1) != "SR-EX-8-1.json" || filepath.Base(p2) != "SR-EX-8-2.json" {
		t.Fatalf("序号不对：%s / %s", filepath.Base(p1), filepath.Base(p2))
	}
	p3, err := WriteJob(job, dir, "EX/8")
	if err != nil {
		t.Fatalf("斜杠关卡名写失败：%v", err)
	}
	if filepath.Base(filepath.Dir(p3)) != "EX_8" || filepath.Base(p3) != "EX_8-1.json" {
		t.Fatalf("非法字符没被替换成下划线：%s", p3)
	}
	p4, err := WriteJob(job, dir, "")
	if err != nil {
		t.Fatalf("空关卡名写失败：%v", err)
	}
	if filepath.Base(filepath.Dir(p4)) != "stage" || filepath.Base(p4) != "stage-1.json" {
		t.Fatalf("空关卡名没有退成 stage：%s", p4)
	}
	// 读回来：键序与内容都要能还原（JSON 对象比对是键序无关的，所以只比结构）
	blob, err := os.ReadFile(p1)
	if err != nil {
		t.Fatalf("读回失败：%v", err)
	}
	var back MaaJob
	if err := json.Unmarshal(blob, &back); err != nil {
		t.Fatalf("写出去的文件读不回来：%v", err)
	}
	if len(back.Opers) != len(job.Opers) || len(back.Actions) != len(job.Actions) {
		t.Fatalf("读回来的 opers/actions 条数不一致：%d/%d vs %d/%d",
			len(back.Opers), len(back.Actions), len(job.Opers), len(job.Actions))
	}
	if back.Opers[0].Name != job.Opers[0].Name || back.Doc.Details != job.Doc.Details {
		t.Fatalf("读回来的内容与内存里不一致")
	}
	// 末尾必须有换行，且不该有 BOM（Python 是 write_text 不带 BOM）
	if !bytes.HasSuffix(blob, []byte("\n")) {
		t.Fatalf("写出的文件末尾没有换行")
	}
	if bytes.HasPrefix(blob, []byte{0xEF, 0xBB, 0xBF}) {
		t.Fatalf("写出的文件带了 BOM，Python 那边没有")
	}
}

// TestEscapeHTMLOff HTML 字符不许被转义（Python 的 ensure_ascii=False 不转义它们）。
//
// 这条是 `MarshalJob` 为什么必须走 Encoder 而不是 `json.MarshalIndent` 的理由，
// 单独立一条，免得日后有人「顺手简化」成 MarshalIndent。
func TestEscapeHTMLOff(t *testing.T) {
	plan := core.PlayPlan{Stage: "s", Deploys: []core.DeployOrder{
		{Operator: "甲&乙", Position: [2]int{1, 1}, Direction: "Right"},
	}}
	job, err := ToMaa(plan, nil, nil, nil, MaaOptions{Details: "a<b>c"})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	blob, _ := MarshalJob(job)
	for _, bad := range []string{`\u0026`, `\u003c`, `\u003e`} {
		if bytes.Contains(blob, []byte(bad)) {
			t.Fatalf("被转义成了 %s（Python 不转义）：\n%s", bad, blob)
		}
	}
	if !bytes.Contains(blob, []byte("a<b>c")) {
		t.Fatalf("原文没原样落进去：\n%s", blob)
	}
}

// TestLineEndingDivergence 把「落盘行尾」这条**分道扬镳**钉成判据。
//
// Python 的 `write_job` 走 `Path.write_text` ⇒ Windows 上写出 CRLF；
// Go 的 `WriteJob` 写 LF。**JSON 内容一模一样，MAA 两种都读**，差别只在换行字节
// —— 但它是可观测的字节差，按口径必须具名登记，不许因为「反正能读」就装作没有。
//
// 上面 `readFixture` 会把 CRLF 归一化掉，所以这条判据是那条归一化**唯一**的见证：
// 它红了就说明要么 Python 侧变了、要么 Go 侧变了，登记该跟着改。
func TestLineEndingDivergence(t *testing.T) {
	raw, err := os.ReadFile(filepath.Join("testdata", "maajob_golden.json"))
	if err != nil {
		t.Fatalf("读夹具失败：%v", err)
	}
	// ⚠ 夹具**盘上**的行尾不固定：仓库开了 core.autocrlf，blob 里永远是 LF，
	// Windows 检出是 CRLF、别处是 LF。所以这里只判「整齐」（不许混合 ——
	// 混合说明复制或编辑时被改坏了），真正的分歧判在 Go 那一侧。
	crlf := bytes.Count(raw, []byte("\r\n"))
	lf := bytes.Count(raw, []byte("\n"))
	if crlf != 0 && crlf != lf {
		t.Fatalf("夹具行尾是混合的（CRLF %d / 总 LF %d）—— 夹具被改坏了", crlf, lf)
	}
	job, err := ToMaa(goldenPlan(), nil, handTable(), nil, MaaOptions{})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	path, err := WriteJob(job, t.TempDir(), "s")
	if err != nil {
		t.Fatalf("写盘失败：%v", err)
	}
	blob, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("读回失败：%v", err)
	}
	if bytes.Contains(blob, []byte("\r\n")) {
		t.Fatalf("Go 侧写出的是 CRLF —— 与登记的「Go 写 LF」不符，登记要改")
	}
	if !bytes.Contains(blob, []byte("\n")) {
		t.Fatalf("Go 侧一个换行都没有，形态可疑")
	}
	where := "LF（非 Windows 检出）"
	if crlf > 0 {
		where = "CRLF（Windows 检出：Python 的 write_text 走文本模式翻出来的）"
	}
	t.Logf("夹具盘上行尾 %s；Go 侧落盘恒为 LF（与平台无关）⇒ 这条分歧只在"+
		"「同一台机器上 Python 写盘 vs Go 写盘」时可见", where)
}

// TestSupportOperIsNameOnly 是「助战那一格只写名字」的判据。
//
// ★ 不信任我自己的 `MarshalJSON`：把整份作业**解析回来**，断言第 13 项**恰好只有
// 一个键、且键名是 name** —— 这才叫「只写名字」。
//
// 配两条负对照：不带助战时必须还是 3 条（多了说明那一格被无条件加上）；助战那条
// **不许**出现 requirements／skill／skill_usage 三个键。
func TestSupportOperIsNameOnly(t *testing.T) {
	base := MaaOptions{Difficulty: "NORMAL", Title: "测试", Details: "详情"}
	withSup := base
	withSup.SupportName = "令"
	job, err := ToMaa(goldenPlan(), nil, handTable(), nil, withSup)
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	if len(job.Opers) != 4 {
		t.Fatalf("带助战时 opers 应为 3 ＋ 1 = 4 条，实得 %d", len(job.Opers))
	}
	blob, err := MarshalJob(job)
	if err != nil {
		t.Fatalf("序列化失败：%v", err)
	}
	var back struct {
		Opers []map[string]any `json:"opers"`
	}
	if err := json.Unmarshal(blob, &back); err != nil {
		t.Fatalf("解析失败：%v", err)
	}
	last := back.Opers[len(back.Opers)-1]
	if len(last) != 1 || last["name"] != "令" {
		t.Fatalf("助战那一格应**只有名字**：%v", last)
	}
	for _, k := range []string{"requirements", "skill", "skill_usage"} {
		if _, ok := last[k]; ok {
			t.Fatalf("助战那一格不该有 %q 键：%v", k, last)
		}
	}
	//: 负对照：不带助战 ⇒ 仍然 3 条
	noSup, err := ToMaa(goldenPlan(), nil, handTable(), nil, base)
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	if len(noSup.Opers) != 3 {
		t.Fatalf("不带助战时 opers 必须还是 3 条，实得 %d（那一格被无条件加上了？）",
			len(noSup.Opers))
	}
	//: 正对照：前 12 条（这里 3 条）的形状**没被**自定义序列化带偏
	var plain struct {
		Opers []map[string]any `json:"opers"`
	}
	noBlob, _ := MarshalJob(noSup)
	if err := json.Unmarshal(noBlob, &plain); err != nil {
		t.Fatalf("解析失败：%v", err)
	}
	if len(plain.Opers[0]) != 4 {
		t.Fatalf("普通干员那一条应有 4 个键（name/skill/skill_usage/requirements），实得 %v",
			plain.Opers[0])
	}
}

// TestDegenerateDivergence 把那条**登记的**分道扬镳钉成判据。
//
// Python 在练度取不到时印 `null` / `精None None  潜None`；Go 按博士 2026-09-26 的
// 裁定二写 0。⇒ 这一条**不是**逐字节对拍（那一条红是对的），而是把它记成
// 「Go 写 0 ∧ Python 印 None」，哪天口径变了这条会当场变红，提醒改登记。
func TestDegenerateDivergence(t *testing.T) {
	plan := core.PlayPlan{Stage: "main_01-07", Deploys: []core.DeployOrder{
		{Operator: "甲", Position: [2]int{1, 1}, Direction: "Right"},
		{Operator: "乙", Position: [2]int{2, 1}, Direction: "Right", Skill: 2, Mastery: 1},
	}}
	job, err := ToMaa(plan, nil, nil, nil, MaaOptions{})
	if err != nil {
		t.Fatalf("组装失败：%v", err)
	}
	if job.Opers[0].Requirements.Elite == nil || *job.Opers[0].Requirements.Elite != 0 {
		t.Fatalf("Go 侧取不到练度要写 0（裁定二），实得 %v", job.Opers[0].Requirements.Elite)
	}
	if job.Opers[1].Requirements.SkillLevel != 8 {
		t.Fatalf("技2 专1 ⇒ skill_level 必须是 8，实得 %d", job.Opers[1].Requirements.SkillLevel)
	}
	blob, _ := MarshalJob(job)
	if bytes.Contains(blob, []byte(`"elite": null`)) {
		t.Fatalf("Go 不该写 null（那是 Python 那一侧的形态）：\n%s", blob)
	}
	if !bytes.Contains(blob, []byte("精0 0  潜0")) {
		t.Fatalf("退化形态的 doc 该是 `精0 0  潜0`（Python 印的是 `精None None  潜None`）：\n%s", blob)
	}
}
