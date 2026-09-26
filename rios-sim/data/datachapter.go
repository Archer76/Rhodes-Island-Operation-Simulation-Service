package data

// datachapter.go：章节层（TUI 第一屏）的**排版四函数**。
//
// 参照实现：`ak_tactic/db/stages.py:277-357`（`_cn_num`／`_chapter_head`／`zone_title`／
// `chapter_label`）与 `:692-708`（`_part_title`）。逐条口径见
// `out/zz_tui_data_spec.md` §4.3（那份规格把它与 `out/zz_golden.txt` 的 17 条 `LBL` 金标对齐过）。
//
// ⚠ **照抄实现，别照抄 docstring**：规格记了一处实测反例 —— `_part_title` 的 docstring 说
// 「关卡名也拿不到时才退回 `zone_title`，那一步会露出 `camp_zone_7` 这种内部 id」，
// 而实测（`out/zz_probe3.txt`）拿到的是**空串**：`zone_title` 的第三级回退
// （`zone.get("zone_id")`）在 Python 里是**死代码**（`load_zones` 的 value 没有这个键）。
// 本实现**照实测**：第三级回退返回空串，并把「为什么」写在这里。

import (
	"fmt"
	"strings"
)

// cnDigits 是 `_CN_DIGITS`（`stages.py:277` 附近，0–9 十个字符）。
const cnDigits = "零一二三四五六七八九"

// cnNum 复刻 `_cn_num`（`stages.py:277-287`）：中文数字，**只处理到 99**。
//
// ★ **与 Python 的一处显式分道扬镳（必须登记）**：Python 对 `n >= 100` 会
// `IndexError: string index out of range`（`_CN_DIGITS[10]` 越界，规格 §4.3 有实测）。
// Go 侧**不照抄这个崩**：返回 `ok=false`，由调用方退回 `strconv.Itoa(n)` 并把这件事
// 写进读数。理由：本仓口径是「不许静默」，但「静默」指的是**不报**，不是**跟着崩**——
// 一个上游数据里冒出三位数章号就把整个界面带走，代价远大于收益。
//
// 今天的数据触发不到：`name_title` 实测取值只有 `'00'`…`'17'`（18 个 ASCII 两位）。
func cnNum(n int) (string, bool) {
	if n <= 0 {
		return fmt.Sprint(n), true
	}
	if n < 10 {
		return string([]rune(cnDigits)[n]), true
	}
	if n >= 100 {
		return "", false
	}
	tens, ones := n/10, n%10
	var head string
	if tens == 1 {
		head = "十"
	} else {
		head = string([]rune(cnDigits)[tens]) + "十"
	}
	if ones == 0 {
		return head, true
	}
	return head + string([]rune(cnDigits)[ones]), true
}

// cnNumOrDigits 是 `cnNum` 的宽容版：越界时退回阿拉伯数字（对应上面那条登记）。
func cnNumOrDigits(n int) string {
	if s, ok := cnNum(n); ok {
		return s
	}
	return fmt.Sprint(n)
}

// isAllDigits 复刻 Python 的 `str.isdigit()`（**只认纯十进制数字**，
// 不接受 `+7`／`-7`／空格 —— 与 `strconv.Atoi` 的宽松度不同）。
func isAllDigits(s string) bool {
	if s == "" {
		return false
	}
	for _, c := range s {
		if c < '0' || c > '9' {
			return false
		}
	}
	return true
}

// chapterHead 复刻 `_chapter_head`（`stages.py:290-307`）：**只出章号**，非主线返回空串。
//
// 四个分支的**顺序不可换**（规格 §4.3 明写「分支 1 优先于分支 2」）：
//  1. `name_first` 以「第」开头且以「章」结尾 → 原样返回（第 1–14 章本来写着「第一章」…）；
//  2. 否则 `name_title` 是**纯数字且 != "00"** → `第<中文数字>章`（第 15–17 章是
//     `MAINLINE_ACTIVITY`，`name_first` 是英文，章号只在 `name_title`）；
//  3. 否则 `name_title == "00"` → `name_first` 或 `序章`；
//  4. 都不中 → `""`。
func chapterHead(z ZoneRecord) string {
	f, t := z.NameFirst, z.NameTitle
	if strings.HasPrefix(f, "第") && strings.HasSuffix(f, "章") {
		return f
	}
	if isAllDigits(t) && t != "00" {
		return "第" + cnNumOrDigits(atoiLoose(t)) + "章"
	}
	if t == "00" {
		if f != "" {
			return f
		}
		return "序章"
	}
	return ""
}

// atoiLoose 把「已确认全是数字」的串转 int（`isAllDigits` 已挡住非法输入）。
func atoiLoose(s string) int {
	n := 0
	for _, c := range s {
		n = n*10 + int(c-'0')
	}
	return n
}

// zoneTitle 复刻 `zone_title`（`stages.py:310-331`）：**通用**章节名。
//
// 规则：`head` 非空时，若 `head` 以「第」开头 **且** `name_second` 非空 **且**
// `name_first` **不**以「第」开头 ⇒ `head ＋ 全角空格 ＋ second`，否则只给 `head`；
// `head` 为空 ⇒ `second or first or ""`。
//
// ★ 第三级（Python 原文是 `zone.get("zone_id")`）**是死代码**：`load_zones` 返回的 value
// 没有 `zone_id` 键（规格 §4.3 [实现+实测]）⇒ 实测 352 个 zone 里 **31 个返回空串**
// （含全部 `camp_zone_*`）。本实现照实测：返回空串。
func zoneTitle(z ZoneRecord) string {
	head := chapterHead(z)
	if head != "" {
		if strings.HasPrefix(head, "第") && z.NameSecond != "" &&
			!strings.HasPrefix(z.NameFirst, "第") {
			return head + "　" + z.NameSecond
		}
		return head
	}
	if z.NameSecond != "" {
		return z.NameSecond
	}
	return z.NameFirst //: 再往下 Python 还有一级，但那级是死代码 ⇒ 到此为止
}

// chapterLabel 复刻 `chapter_label`（`stages.py:334-357`）：**菜单第一层**的写法
// `第七章　苦难摇篮`。只认 `MAINLINE`／`MAINLINE_ACTIVITY`，其余返回空串（调用方退回 zoneTitle）。
//
// ⚠ **未核一处**：规格 §4.3 只写了「否则 `head` 或 `head ＋ 全角空格 ＋ second`」，
// **没给出那半句的判别条件**。本实现按同族的 `zoneTitle` 取同一条规则
// （`second` 非空就拼、否则只给 `head`），**并用 `out/zz_golden.txt` 的 18 条 `LBL` 金标核**。
func chapterLabel(z ZoneRecord) string {
	if z.Type != "MAINLINE" && z.Type != "MAINLINE_ACTIVITY" {
		return ""
	}
	head := chapterHead(z)
	if head == "" {
		return ""
	}
	if z.NameSecond != "" {
		return head + "　" + z.NameSecond
	}
	return head
}

// partTitle 复刻 `_part_title`（`stages.py:692-708`）：**第二层（分部）**显示名。
//
//  1. `type == "CAMPAIGN"` **且** `stageNames` 非空 → `、` 连起来的关卡名
//     （参照实现的注释交代：15 个分部的关卡名两两不重复，所以天然不撞名）；
//  2. 否则 `chapter_label or name_second.strip() or zone_title`。
//
// ★ 实测有 **2 个多分部 zone 的 part title 是空串**（`act1vecb_zone2`／`act1vecb_zone3`）
// ⇒ 第二层菜单会出现空白行。**这是照抄的结果，不是本实现的缺陷**。
func partTitle(z ZoneRecord, stageNames []string) string {
	if z.Type == "CAMPAIGN" && len(stageNames) > 0 {
		return strings.Join(stageNames, "、")
	}
	if s := chapterLabel(z); s != "" {
		return s
	}
	if s := strings.TrimSpace(z.NameSecond); s != "" {
		return s
	}
	return zoneTitle(z)
}
