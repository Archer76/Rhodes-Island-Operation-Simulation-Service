package core

// ImplementedOperators 维护当前在 rios-sim 中已完成战斗机制生命周期闭环的干员表。
// 映射键为干员官方中文名与官方 char_id，值为官方唯一规范中文名。
// TUI 选人界面与自动补人逻辑必须且仅能从此表识别已实现的干员。
var ImplementedOperators = map[string]string{
	// 1. 最新活动组
	"塔露拉":           "塔露拉",
	"char_4247_oxi":  "塔露拉",
	"冻河":            "冻河",
	"char_4244_tocka": "冻河",
	"国度":            "国度",
	"char_4246_dminon": "国度",

	// 2. 高练攻坚组
	"机械师":            "机械师",
	"char_4230_mcnist": "机械师",
	"电弧":            "电弧",
	"char_4195_radian": "电弧",
	"圣聆初雪":          "圣聆初雪",
	"char_1046_sbell2": "圣聆初雪",

	// 3. 核心基石组
	"提丰":              "提丰",
	"char_2012_typhon":  "提丰",
	"阿斯卡纶":            "阿斯卡纶",
	"char_4132_ascln":   "阿斯卡纶",
	"黍":               "黍",
	"char_2025_shu":     "黍",
	"乌尔比安":            "乌尔比安",
	"char_4145_ulpia":   "乌尔比安",
	"逻各斯":             "逻各斯",
	"char_4133_logos":   "逻各斯",

	// 4. 原有已实现干员
	"望":                "望",
	"char_2027_wang":    "望",
	"维什戴尔":            "维什戴尔",
	"char_1035_wisdel":  "维什戴尔",
	"令":                "令",
	"char_2023_ling":    "令",
	"赤刃明霄陈":           "赤刃明霄陈",
	"char_1050_chen3":   "赤刃明霄陈",
	"丰川祥子":            "丰川祥子",
	"char_4182_oblvns":  "丰川祥子",
	"隐德来希":            "隐德来希",
	"char_4010_etlchi":  "隐德来希",
}

// IsOperatorImplemented 检查干员（按名称或 char_id）是否属于已完成制作的干员。
func IsOperatorImplemented(identifier string) bool {
	_, ok := ImplementedOperators[identifier]
	return ok
}

// CanonicalImplementedName 获取已实现干员的标准规范中文名。
func CanonicalImplementedName(identifier string) (string, bool) {
	name, ok := ImplementedOperators[identifier]
	return name, ok
}
