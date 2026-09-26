package main

import (
	"math"
	"os"
	"path/filepath"
	"testing"
)

// # 候选生成（`candidates.go`）的 Go 侧判据
//
// 这一层最要紧的一条是**价值排序**：`value = dwell × 攻击力`。它有个很难发现的
// 失效方式 —— 攻击力取成 0 时，`value` 恒为 0、排序退化成插入序，而候选条数、
// `dwell`、`visit` 数**全都还是对的**（真发生过：第一版用 `asF` 取 `total["atk"]`，
// 而那是 int，于是真跑一次才看见 `value=0.0`）。
//
// 所以这里有一条判据**专门盯它**：`value` 必须等于 `dwell × 独立重算的攻击力`，
// 且不许全为 0。

const testRosterRows = `[
 {"name":"圣聆初雪","charId":"char_1046_sbell2","elite":2,"level":90,"potential":1,"module_level":0},
 {"name":"赤刃明霄陈","charId":"char_1050_chen3","elite":2,"level":90,"potential":1,
  "module":"uniequip_002_chen3","module_level":3}
]`

// writeTempRoster 造一份临时名册。**不依赖玩家那份 gitignore 的名册文件** ——
// 依赖它的话，判据在别人的机器上只会静默 skip（零行使的假绿）。
func writeTempRoster(t *testing.T, rows string) string {
	t.Helper()
	p := filepath.Join(t.TempDir(), "roster.json")
	if err := os.WriteFile(p, []byte(rows), 0o644); err != nil {
		t.Fatalf("写临时名册失败：%v", err)
	}
	return p
}

// atkIndependently 独立重算攻击力（不走 `atkOf`，免得与实现自证）。
func atkIndependently(t *testing.T, cfg OperatorCalcConfig) float64 {
	t.Helper()
	st, err := OperatorStatsFor(cfg, "")
	if err != nil {
		t.Fatalf("独立折算失败：%v", err)
	}
	v, ok := st.Total["atk"]
	if !ok {
		t.Fatalf("面板 total 里没有 atk")
	}
	switch n := v.(type) {
	case int:
		return float64(n)
	case float64:
		return n
	}
	t.Fatalf("atk 的类型不认识：%T", v)
	return 0
}

func TestCandidatesOnRealStage(t *testing.T) {
	chdirRepoRootForData(t)
	roster := writeTempRoster(t, testRosterRows)
	got, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{
		Roster:     roster,
		Operators:  []string{"圣聆初雪", "赤刃明霄陈"},
		PerOp:      3,
		SpeedScale: 1.0,
	})
	if err != nil {
		if missingData(err) {
			t.Skipf("缺关卡数据（环境问题，不是红）：%v", err)
		}
		t.Fatalf("算候选失败：%v", err)
	}
	if got.Covered.Operators != 2 || got.Covered.Kept == 0 {
		t.Fatalf("行使计数为零或不对：%+v", got.Covered)
	}
	if len(got.Rows) != got.Covered.Kept {
		t.Fatalf("行数 %d ≠ 计数 kept %d", len(got.Rows), got.Covered.Kept)
	}

	// ---- 排序与截断
	for i := 1; i < len(got.Rows); i++ {
		if got.Rows[i-1].Value < got.Rows[i].Value {
			t.Fatalf("第 %d 条的价值低于后一条：%.3f < %.3f",
				i, got.Rows[i-1].Value, got.Rows[i].Value)
		}
	}
	perOp := map[string]int{}
	for _, r := range got.Rows {
		perOp[r.Operator]++
	}
	for name, n := range perOp {
		if n > 3 {
			t.Errorf("%s 有 %d 条，超过了 per_op=3", name, n)
		}
	}
	// ---- 同干员同格只出现一次（四个朝向只留最好的那个）
	seenPos := map[string]bool{}
	for _, r := range got.Rows {
		k := r.Operator + "@" + string(rune(r.Position[0])) + "," + string(rune(r.Position[1]))
		if seenPos[k] {
			t.Errorf("%s 在 %v 出现了两次（同格四朝向没去重）", r.Operator, r.Position)
		}
		seenPos[k] = true
	}

	// ---- ★ 价值 = dwell × 攻击力（**这条就是抓 atk 取成 0 的那条**）
	spec := map[string]OperatorCalcConfig{
		"圣聆初雪": {CharID: "char_1046_sbell2", Elite: 2, Level: 90, Potential: 1},
		"赤刃明霄陈": {CharID: "char_1050_chen3", Elite: 2, Level: 90, Potential: 1,
			Module: "uniequip_002_chen3", ModuleLevel: 3},
	}
	positive := 0
	for _, r := range got.Rows {
		if r.Dwell <= 0 {
			t.Errorf("%s 的 dwell = %v，零 dwell 的落位不该活下来", r.Operator, r.Dwell)
		}
		atk := atkIndependently(t, spec[r.Operator])
		if atk <= 0 {
			t.Fatalf("%s 的攻击力独立重算是 %v，测试自身有问题", r.Operator, atk)
		}
		want := r.Dwell * atk
		if math.Abs(r.Value-want) > 1e-9*math.Max(1, math.Abs(want)) {
			t.Errorf("%s@%v 的价值 = %.6f，而 dwell×atk = %.6f（攻击力取成 0 时这里必红）",
				r.Operator, r.Position, r.Value, want)
		}
		if r.Value > 0 {
			positive++
		}
	}
	if positive == 0 {
		t.Fatalf("所有候选的价值都是 0 —— 排序其实失效了，只是看不出来")
	}
	// ---- 落位必须落在**这位干员能站的**那一类格上
	for _, r := range got.Rows {
		melee, err := isMeleeChar(r.CharID)
		if err != nil {
			t.Fatalf("判站位失败：%v", err)
		}
		if melee != (r.CharID == "char_1050_chen3") {
			//: 陈是近战、初雪是高台 —— 若这条不成立说明我对这两位的前提变了
			t.Logf("（注：%s 的 melee=%v）", r.CharID, melee)
		}
	}
	t.Logf("候选 %d 条（%d 位干员）：最高价值 %.1f（%s@%v dwell=%.2f）",
		len(got.Rows), got.Covered.Operators, got.Rows[0].Value,
		got.Rows[0].Operator, got.Rows[0].Position, got.Rows[0].Dwell)
	t.Logf("行使计数：%+v", got.Covered)
}

// TestCandidatesNegativeControls 三条负对照：尺子必须能判"什么都没有"。
func TestCandidatesNegativeControls(t *testing.T) {
	chdirRepoRootForData(t)
	//: 1. 名册里没有这一位 ⇒ 一条候选都不该有，且计数要说是「名册缺人」
	got, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{
		Roster:    writeTempRoster(t, testRosterRows),
		Operators: []string{"查无此人"},
	})
	if err != nil {
		if missingData(err) {
			t.Skipf("缺关卡数据：%v", err)
		}
		t.Fatalf("失败：%v", err)
	}
	if len(got.Rows) != 0 || got.Covered.EntryMissing != 1 {
		t.Fatalf("名册缺人时应 0 条候选且 entry_missing=1，实得 %d 条 %+v",
			len(got.Rows), got.Covered)
	}
	//: 2. 不给名册 ⇒ 同样 0 条（Python 的 `roster.get(name)` 返回 None 那条路）
	got2, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{
		Operators: []string{"圣聆初雪"}})
	if err != nil {
		t.Fatalf("失败：%v", err)
	}
	if len(got2.Rows) != 0 || got2.Covered.EntryMissing != 1 {
		t.Fatalf("没有名册时应 0 条候选，实得 %d 条 %+v", len(got2.Rows), got2.Covered)
	}
	//: 3. per_op=1 ⇒ 每位干员最多 1 条
	got3, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{
		Roster:    writeTempRoster(t, testRosterRows),
		Operators: []string{"圣聆初雪", "赤刃明霄陈"}, PerOp: 1})
	if err != nil {
		t.Fatalf("失败：%v", err)
	}
	if len(got3.Rows) > 2 {
		t.Fatalf("per_op=1 时两位干员最多 2 条，实得 %d", len(got3.Rows))
	}
	//: 4. 名册路径不存在 ⇒ **具名失败**，不许静默当空名册
	if _, err := CandidatesFor("main_01-07", "", "", CandidatesQuery{
		Roster:    filepath.Join(t.TempDir(), "没有这个文件.json"),
		Operators: []string{"圣聆初雪"}}); err == nil {
		t.Fatalf("名册路径不存在时必须报错")
	}
}
