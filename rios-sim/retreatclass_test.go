package main

// retreatclass_test.go：撤退分类（博士 2026-09-29 的三类口径）的判据。
//
// 三类各自的**正例**与三类边界上的**负对照**都摆上——这是「解算器只给这三类排撤退」
// 这条口径的立足点：分类错了，后面排出来的撤退就是错的。
//
// ⚠ 用**真再部署时间**喂分类（`OperatorStatsFor` 现算），不手抄常数：
// 焰狐龙梓兰裸装 51s（不够格）、挂模组 26s（够格）——同一名干员两种结论，
// 差别只在那一列上，正好当一对正反例。

import "testing"

// classOf 现算某位干员在给定练度下的分类（练度决定再部署时间）。
func classOf(t *testing.T, charID string, elite, level, potential int,
	module string, modLevel int) RetreatClass {
	t.Helper()
	rt := respawnOf(t, charID, elite, level, potential, module, modLevel)
	c, err := retreatClassOf(charID, rt)
	if err != nil {
		t.Fatalf("分类 %s 失败：%v", charID, err)
	}
	return c
}

// TestRetreatClassTable 一张表钉住三类 ＋ 各自的负对照。
func TestRetreatClassTable(t *testing.T) {
	chdirRepoRoot(t)
	cases := []struct {
		name   string
		charID string
		elite  int
		level  int
		pot    int
		module string
		modLv  int
		want   RetreatClass
		why    string
	}{
		//: ---- ① 三四星回费先锋 ----
		{"香草（3★ 先锋）", "char_240_wyvern", 1, 55, 6, "", 0, ClassPioneerDP,
			"三星先锋 ＋ 标签「费用回复」⇒ 撤一次把钱拿回来"},
		{"芬（3★ 先锋）", "char_123_fang", 1, 55, 6, "", 0, ClassPioneerDP, "同上"},
		{"桃金娘（4★ 执旗手）", "char_151_myrtle", 2, 60, 6, "", 0, ClassPioneerDP,
			"四星执旗手：回费效率最高那一档，同样只撤一次"},
		{"德克萨斯（5★ 先锋）", "char_102_texas", 2, 80, 6, "", 0, ClassNone,
			"★负对照：**五六星**先锋不进这一类（口径是三四星）"},
		{"风笛（6★ 先锋）", "char_222_bpipe", 2, 90, 6, "", 0, ClassNone,
			"★负对照：同上（费用回落是她的用法，但不走这条撤退维度）"},
		{"史都华德（3★ 术师）", "char_210_stward", 1, 55, 6, "", 0, ClassNone,
			"★负对照：三星但**不是先锋**"},
		//: ---- ② 快速复活·技能型 ----
		{"麒麟R夜刀", "char_1029_yato2", 2, 90, 6, "", 0, ClassFastSkill,
			"处决者 ＋ 标签「爆发」＋ 再部署 18s"},
		{"缄默德克萨斯", "char_1028_texas2", 2, 90, 6, "", 0, ClassFastSkill,
			"处决者 ＋ 标签「输出」"},
		{"红（控场）", "char_144_red", 2, 80, 6, "", 0, ClassFastSkill,
			"处决者 ＋ 控场：同样要开技能，归到技能型"},
		{"焰狐龙梓兰（挂模组）", "char_1048_orchd2", 2, 90, 6,
			"uniequip_002_orchd2", 3, ClassFastSkill,
			"非处决者：靠天赋 −15 与模组 −25 把再部署压到 26s 才够格"},
		{"焰狐龙梓兰（裸装）", "char_1048_orchd2", 2, 90, 6, "", 0, ClassNone,
			"★负对照：**同一名干员**裸装 51s ⇒ 进不了这一类"},
		//: ---- ③ 快速复活·骗伤型 ----
		{"砾（骗伤）", "char_237_gravel", 2, 1, 6, "", 0, ClassFastBait,
			"处决者 ＋ 标签「防护」＋ 再部署 16s ⇒ 落地挨一刀就死"},
		{"THRM-EX（200s）", "char_376_therex", 0, 30, 6, "", 0, ClassNone,
			"★负对照：**是处决者**、只要 3 费，但再部署 200s ⇒ 送不起第二次"},
		//: ---- 反例：与三类都不沾 ----
		{"能天使", "char_103_angel", 2, 90, 6, "", 0, ClassNone,
			"★负对照：狙击、无「快速复活」，再部署 70s"},
	}
	for _, c := range cases {
		got := classOf(t, c.charID, c.elite, c.level, c.pot, c.module, c.modLv)
		if got != c.want {
			t.Errorf("%s 的分类 = %v，应当是 %v（%s）", c.name, got, c.want, c.why)
		}
	}
}

// TestRetreatClassExercise 正负两侧**各被行使过**：没有这一条，上面那张表可能整表恒等。
func TestRetreatClassExercise(t *testing.T) {
	chdirRepoRoot(t)
	counts := map[RetreatClass]int{}
	for _, c := range []struct {
		charID string
		elite  int
		level  int
		pot    int
	}{
		{"char_240_wyvern", 1, 55, 6}, // ①
		{"char_1029_yato2", 2, 90, 6}, // ②
		{"char_237_gravel", 2, 1, 6},  // ③
		{"char_103_angel", 2, 90, 6},  // 反例
	} {
		counts[classOf(t, c.charID, c.elite, c.level, c.pot, "", 0)]++
	}
	for _, want := range []RetreatClass{ClassPioneerDP, ClassFastSkill,
		ClassFastBait, ClassNone} {
		if counts[want] == 0 {
			t.Errorf("三类＋反例里，%v 一类都没被走到过（零行使的绿不算过）", want)
		}
	}
}
