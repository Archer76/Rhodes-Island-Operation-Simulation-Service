package main

// stagelegacy_test.go：**旧版枚举编码**的归一化判据（2026-09-27）。
//
// 背景：缓存里 169 个关卡文件（当天新取回来的故事集那一族：`act10d5`／`act10mini`／
// `act8mini`…）用的是**旧编码** —— `mapData.tiles[]` 的 height/buildable/passable、
// `routes[].motionMode`、`routes[].checkpoints[].type`、
// `waves[].fragments[].actions[].actionType`、`runes[].difficultyMask`
// **全是整数**。旧代码把这些字段声明成 `string`，`json.Unmarshal` 直接报
// 「cannot unmarshal number … of type string」⇒ 那些关卡**整个读不出来**
// （界面 load 失败、部署人数上限取不到）。
//
// 这一节盯三件事：
//  1. 实测取值逐条归一**对**（映射是拿结构证据推的，见 stage.go 的注释）；
//  2. **负对照**：认不出的检查点整数**必须报错**（不许静默当成缺省 MOVE）；
//  3. **负对照**：认不出的 `difficultyMask` **不许回 nil** —— `maskApplies(nil)`
//     是"对所有难度都适用"，回 nil 会把一条来路不明的 rune 应用得到处都是。

import (
	"encoding/json"
	"testing"
)

func raw(v string) json.RawMessage { return json.RawMessage(v) }

func TestLegacyEnumNormalizers(t *testing.T) {
	cases := []struct {
		what, got, want string
	}{
		//: tiles：heightType（序数枚举）
		{"heightType 0", heightOf(raw("0")), "LOWLAND"},
		{"heightType 1", heightOf(raw("1")), "HIGHLAND"},
		{"heightType 字符串原样", heightOf(raw(`"HIGHLAND"`)), "HIGHLAND"},
		//: tiles：buildableType（序数枚举）
		{"buildableType 0", buildableOf(raw("0")), "NONE"},
		{"buildableType 1", buildableOf(raw("1")), "MELEE"},
		{"buildableType 2", buildableOf(raw("2")), "RANGED"},
		{"buildableType 3", buildableOf(raw("3")), "ALL"},
		//: tiles：passableMask（**位掩码**）
		{"passableMask 2（仅飞行）", passableOf(raw("2")), "FLY_ONLY"},
		{"passableMask 3（地面+飞行）", passableOf(raw("3")), "ALL"},
		{"passableMask 字符串原样", passableOf(raw(`"FLY_ONLY"`)), "FLY_ONLY"},
		{"passableMask null", passableOf(raw("null")), ""},
		//: routes
		{"motionMode 0", motionModeOf(raw("0")), "WALK"},
		{"motionMode 1", motionModeOf(raw("1")), "E_NUM"},
		{"checkpoints.type 0", mustCp(t, raw("0")), "MOVE"},
		{"checkpoints.type 1", mustCp(t, raw("1")), "WAIT_FOR_SECONDS"},
		{"checkpoints.type 5", mustCp(t, raw("5")), "DISAPPEAR"},
		{"checkpoints.type 6", mustCp(t, raw("6")), "APPEAR_AT_POS"},
		{"checkpoints.type 字符串原样", mustCp(t, raw(`"PATROL_MOVE"`)), "PATROL_MOVE"},
		//: waves
		{"actionType 0", actionTypeOf(raw("0")), "SPAWN"},
		{"actionType 字符串原样", actionTypeOf(raw(`"SPAWN"`)), "SPAWN"},
		//: runes：difficultyMask（位掩码）
		{"difficultyMask 1", derefStr(difficultyMaskOf(raw("1"))), "NORMAL"},
		{"difficultyMask 2", derefStr(difficultyMaskOf(raw("2"))), "FOUR_STAR"},
		{"difficultyMask 3", derefStr(difficultyMaskOf(raw("3"))), "ALL"},
		{"difficultyMask 字符串原样", derefStr(difficultyMaskOf(raw(`"FOUR_STAR"`))), "FOUR_STAR"},
	}
	for _, c := range cases {
		if c.got != c.want {
			t.Errorf("%s：实得 %q，应为 %q", c.what, c.got, c.want)
		}
	}

	//: 负对照①：认不出的检查点整数 ⇒ **报错**（不静默当 MOVE）
	if s, err := checkpointTypeOf(raw("99")); err == nil {
		t.Errorf("负对照：检查点整数 99 认不出，却答了 %q 而不报错 —— "+
			"静默当成 MOVE 会改路线", s)
	}
	//: 负对照②：`actionType` 认不出的整数 ⇒ 空串（≠ "SPAWN"，调用方跳过）
	if got := actionTypeOf(raw("3")); got == "SPAWN" {
		t.Errorf("负对照：actionType=3 认不出，却被当成 SPAWN（那会凭空多出出怪）")
	}
	//: 负对照③：`difficultyMask` 认不出的整数 ⇒ **不是 nil**（nil = 对所有难度适用）
	if m := difficultyMaskOf(raw("4")); m == nil {
		t.Error("负对照：difficultyMask=4 认不出却回了 nil —— " +
			"maskApplies(nil) 是「对所有难度都适用」，会把来路不明的 rune 用得到处都是")
	} else if maskApplies(m, "NORMAL") || maskApplies(m, "FOUR_STAR") {
		t.Errorf("负对照：认不出的 mask %q 不该匹配任何难度", *m)
	}
}

func mustCp(t *testing.T, r json.RawMessage) string {
	t.Helper()
	s, err := checkpointTypeOf(r)
	if err != nil {
		t.Fatalf("checkpointTypeOf(%s) 报错：%v", r, err)
	}
	return s
}

// derefStr 只给这一节用：把 `*string` 显示成人看得懂的样子
// （包内已有一个 `deref` 是给 `*float64` 的，名字不能撞）。
func derefStr(p *string) string {
	if p == nil {
		return "(nil)"
	}
	return *p
}
