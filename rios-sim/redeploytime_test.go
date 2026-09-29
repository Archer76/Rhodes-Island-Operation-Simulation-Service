package main

// redeploytime_test.go：**再部署时间取真值**（博士 2026-09-29 裁定）。
//
// 裁定原文：「连天赋／模组的再部署减免一起算」。原先 Go 与 Python 同口径：所有干员恒
// `opsRedeployDefault` = **70s**（照 `verify.py` 的 `kw` 里没有这个键）。而真值在关卡表的
// **相位属性**里（`phases[].attributesKeyFrames[].data.respawnTime`，见
// `out/acceptance/_chartable_phase_probe.py` 的实测）：
//
//	· 处决者（砾／红／卡夫卡／缄默德克萨斯／麒麟R夜刀）基础 **18s**；
//	· 潜能里还有「再部署时间-2秒」这类（砾第 3 档 −2、焰狐龙梓兰第 2 档 −4）⇒ 满潜更低；
//	· THRM-EX ＝ **200s**（特性「再部署时间极长」，且它**只有精英 0 一段**）；
//	· 普通干员（能天使）＝ **70s**；
//	· 焰狐龙梓兰（满潜）＝ 70 − 4（潜能）− 15（天赋「翔虫机动」，黑板原样
//	  `{"respawn_time": -15.0}`，**是秒不是比例**）＝ **51s**；再挂上「梓兰特制箭靶」
//	  （模组 `uniequip_002_orchd2`，−25）＝ **26s**。
//
// 判据分三层：
//
//	① 面板层：上面这些数逐个数出来（含**负对照**：普通干员仍是 70，不是「全变 18」）；
//	② 规格层：规格里 `operators[].redeploy_time` 真的带着真实值（两次部署两个对象）；
//	③ 行为层：砾撤退后 **rt+1 秒**再上 ⇒ 落地；**rt−1 秒**再上 ⇒ 具名拒「再部署冷却中」
//	   （rt 从规格里现读，不写死）。这一对是**回归防线**：老口径下这两个时刻都会被拒
//	   （冷却 70s），所以正例不可能靠偶然通过。
//
// ⚠ 名册是**内联**的（`fixtures/roster_max_modelled.json` 里没有砾，而这一条必须要她）：
// 名册两形态里内联那一份是正式入口（`BuildSpecQuery.Roster` 收数组），不是测试旁路。

import (
	"encoding/json"
	"fmt"
	"testing"
)

// gravelRoster 三名干员：砾（被测，**满潜**）＋ 能天使／泥岩（撑住这一局，别让它提前收场）。
const gravelRoster = `[
	{"id":"char_103_angel","name":"能天使","elite":2,"level":90,"own":true,"potential":6,"rarity":6},
	{"id":"char_311_mudrok","name":"泥岩","elite":2,"level":90,"own":true,"potential":6,"rarity":6},
	{"id":"char_237_gravel","name":"砾","elite":2,"level":1,"own":true,"potential":6,"rarity":4}
]`

// respawnOf 现算一名干员在给定练度（可选模组）下的**再部署时间**（面板那一层）。
func respawnOf(t *testing.T, charID string, elite, level, potential int,
	module string, modLevel int) float64 {
	t.Helper()
	st, err := OperatorStatsFor(OperatorCalcConfig{
		CharID: charID, Elite: elite, Level: level, Potential: potential,
		Module: module, ModuleLevel: modLevel,
	}, "round")
	if err != nil {
		t.Fatalf("算 %s 的面板失败：%v", charID, err)
	}
	v, ok := st.Total["respawnTime"]
	if !ok {
		t.Fatalf("%s 的面板里没有 respawnTime 这一项（相位属性或键表没接上）", charID)
	}
	f, ok2 := toFloat(v)
	if !ok2 {
		t.Fatalf("%s 的 respawnTime 不是数：%#v", charID, v)
	}
	return f
}

// TestRedeployTimeTruth ① 面板层：具名真值 ＋ 负对照 ＋ 潜能／天赋／模组三支各一例。
func TestRedeployTimeTruth(t *testing.T) {
	chdirRepoRoot(t)
	cases := []struct {
		name      string
		charID    string
		elite     int
		level     int
		potential int
		module    string
		modLevel  int
		want      float64
		why       string
	}{
		{"砾（潜0）", "char_237_gravel", 2, 1, 0, "", 0, 18,
			"处决者：快速复活那一族的**基础**再部署时间"},
		{"砾（潜6）", "char_237_gravel", 2, 1, 6, "", 0, 16,
			"潜能的第 3 档写着「再部署时间-2秒」（`RESPAWN_TIME` −2.0）"},
		{"THRM-EX", "char_376_therex", 0, 30, 6, "", 0, 200,
			"机器人处决者：特性「再部署时间极长」，且只有精英 0 一段"},
		{"能天使", "char_103_angel", 2, 90, 6, "", 0, 70,
			"★负对照：普通干员仍是 70（不是「全都变成 18」）"},
		{"焰狐龙梓兰（天赋）", "char_1048_orchd2", 2, 90, 6, "", 0, 51,
			"基础 70 − 潜能第 2 档「再部署时间-4秒」− 天赋「翔虫机动」15（天赋黑板是**秒**，不是比例）"},
		{"焰狐龙梓兰（天赋＋模组）", "char_1048_orchd2", 2, 90, 6,
			"uniequip_002_orchd2", 3, 26,
			"再减模组「梓兰特制箭靶」的 −25 ⇒ 70−4−15−25"},
	}
	for _, c := range cases {
		got := respawnOf(t, c.charID, c.elite, c.level, c.potential, c.module, c.modLevel)
		if got != c.want {
			t.Errorf("%s 的再部署时间 = %v，应当是 %v（%s）", c.name, got, c.want, c.why)
		}
	}
}

// gravelPlan 造一份计划：能天使／泥岩撑场，砾上**两次**（第一次与撤退、第二次都写死时刻）。
//
// ⚠ 时刻全写死是**故意的**：费用模型按计划顺序推算「最早能落地的时刻」，顺序一变
// 算出来的时刻就变（第一版就是这样让撤退落在「这个人还没部署」上、静默不撤）。
// 写死之后每一步都能被事件流核出来。
func gravelPlan(retreatAt, secondAt float64) string {
	return fmt.Sprintf(`{
		"stage": "main_01-07",
		"deploys": [
			{"operator": "能天使", "position": [3,5], "direction": "Up", "skill": 0, "time": 2},
			{"operator": "泥岩", "position": [2,3], "direction": "Left", "skill": 0, "time": 24},
			{"operator": "砾", "position": [2,4], "direction": "Right", "skill": 0, "time": 30},
			{"operator": "砾", "position": [3,4], "direction": "Right", "skill": 0, "time": %.3f}
		],
		"retreats": [{"operator": "砾", "time": %.3f}]
	}`, secondAt, retreatAt)
}

// gravelSpec 造规格（走生产路径 `BuildSpecFull`，名册是内联那份）。
func gravelSpec(t *testing.T, retreatAt, secondAt float64) *Spec {
	t.Helper()
	out, err := BuildSpecFull("main_01-07", "", BuildSpecQuery{
		Plan:        json.RawMessage(gravelPlan(retreatAt, secondAt)),
		Roster:      json.RawMessage(gravelRoster),
		AllowSkills: true,
	})
	if err != nil {
		t.Fatalf("造规格失败：%v", err)
	}
	raw, err := json.Marshal(out.Spec)
	if err != nil {
		t.Fatalf("规格序列化失败：%v", err)
	}
	var spec Spec
	if err := json.Unmarshal(raw, &spec); err != nil {
		t.Fatalf("规格解回失败：%v", err)
	}
	return &spec
}

// gravelRedeployTime 从规格里读砾的再部署时间（行为层那两个时刻由它现算）。
func gravelRedeployTime(t *testing.T, spec *Spec) float64 {
	t.Helper()
	for _, o := range spec.Operators {
		if o.CharID == "char_237_gravel" {
			return o.RedeployTime
		}
	}
	t.Fatalf("规格里没有砾：%+v", spec.Operators)
	return 0
}

// TestRedeployTimeInSpec ② 规格层：`operators[].redeploy_time` 真的带真值，两次部署两个对象。
func TestRedeployTimeInSpec(t *testing.T) {
	chdirRepoRoot(t)
	spec := gravelSpec(t, 34, 51)
	seen := 0
	for _, o := range spec.Operators {
		if o.CharID != "char_237_gravel" {
			continue
		}
		seen++
		if o.RedeployTime != 16 {
			t.Errorf("砾（满潜）的 redeploy_time = %v，应当是 16（18 − 潜能 2）——"+
				"模拟器那条冷却判据读的就是它", o.RedeployTime)
		}
	}
	if seen != 2 {
		t.Fatalf("规格里砾有 %d 个对象，应当是 2 个（二次部署各一个，见 DeploySpec.Index）", seen)
	}
}

// TestRedeployAfterRealCooldownLands ③ 行为层正例：撤退后 **rt+1 秒**再上 ⇒ 落地。
func TestRedeployAfterRealCooldownLands(t *testing.T) {
	chdirRepoRoot(t)
	const retreatAt = 34.0
	probe := gravelSpec(t, retreatAt, retreatAt+1)
	rt := gravelRedeployTime(t, probe)
	if rt >= 70 {
		t.Fatalf("被测对象的再部署时间是 %v——它必须**小于**老口径的 70，"+
			"否则这一对时刻证明不了「真值被用上了」", rt)
	}
	spec := gravelSpec(t, retreatAt, retreatAt+rt+1)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	if got := eventsOf(v, "deploy", "砾"); len(got) < 1 {
		t.Fatalf("砾第一次就没落地（deploy 事件 %v，费用不足 %d 次，用时 %.1fs）"+
			"⇒ 这一趟什么都没测到",
			got, costDeniedFor(v, "砾"), v.Elapsed)
	}
	if got := eventsOf(v, "retreat", "砾"); len(got) != 1 {
		t.Fatalf("撤退没执行（retreat 事件 %v，拒收 %v，用时 %.1fs）",
			got, rejectionsOf(v, "砾"), v.Elapsed)
	}
	got := eventsOf(v, "deploy", "砾")
	if len(got) != 2 {
		t.Fatalf("砾的部署事件 %v（%d 条），应当 2 条——撤退后 %.0fs 已过 %.0fs 冷却；"+
			"拒收 %v，费用不足 %d 次，用时 %.1fs",
			got, len(got), rt+1, rt, rejectionsOf(v, "砾"),
			costDeniedFor(v, "砾"), v.Elapsed)
	}
	if len(v.DeployRejected) != 0 {
		t.Errorf("有拒收明细，应当是空的：%v", v.DeployRejected)
	}
}

// TestRedeployBeforeRealCooldownRefused ③ 行为层负对照：撤退后 **rt−1 秒** ⇒ 具名拒。
func TestRedeployBeforeRealCooldownRefused(t *testing.T) {
	chdirRepoRoot(t)
	const retreatAt = 34.0
	probe := gravelSpec(t, retreatAt, retreatAt+1)
	rt := gravelRedeployTime(t, probe)
	spec := gravelSpec(t, retreatAt, retreatAt+rt-1)
	v, err := runSim(spec)
	if err != nil {
		t.Fatalf("跑不起来：%v", err)
	}
	if got := eventsOf(v, "retreat", "砾"); len(got) != 1 {
		t.Fatalf("撤退没执行（retreat 事件 %v）⇒ 冷却那一条测不到", got)
	}
	if got := eventsOf(v, "deploy", "砾"); len(got) != 1 {
		t.Fatalf("砾的部署事件 %v（%d 条），差 %.0f 秒没到冷却时应当只有第一次",
			got, len(got), rt)
	}
	got := rejectionsOf(v, "砾")
	if len(got) != 1 || got[0][1] != "再部署冷却中" {
		t.Fatalf("拒收明细 = %v，应当恰好一条「再部署冷却中」", got)
	}
}
