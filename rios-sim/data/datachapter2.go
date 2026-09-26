package data

// datachapter2.go：章节层的**归并**（TUI 第一屏的数据本体）。
//
// 参照实现 `ak_tactic/db/stages.py:580-689`（`list_chapters`），逐段口径见
// `out/zz_tui_data_spec.md` §4.2。
//
// ## 一句话算法
//
// 把「有关卡的 zone」按 `activity_id` 并成 **chapter**（剿灭作战那 15 个 zone **整类并成一条**），
// 每个 chapter 里的 zone 按上线顺序排成 `parts`，整表再按四元键排序。
//
// ## ★ 一处**因裁定而与 Python 不同**的地方（必须登记）
//
// §4.2 记的是：`totals[zone_id]` **不过滤任何后缀** ⇒ 「这一层报的关数」含 `#f#` **与 `#s`**。
// 但博士 2026-09-26 裁定**六星档（沙盘推演）不做**（`rios-sim/datadb.go` 的装载口已滤掉）。
// ⇒ **本实现的 `levels` 会比 Python 少**，少的正是落在这些 zone 里的 `#s` 关。
//
// **这不是缺陷，是裁定的必然结果**，但它是「Go 与 Python 分道扬镳」的一处，
// 按最高优先级口径 1② 要具名：红的会是「章节目录与 Python 逐字段对拍」那条，
// **红是对的**（我们**故意**不数那 45 关）。凡引用章节目录的关卡数，都要带这句限定。
//
// ⚠ **一处未核**：参照实现会先过一道 `clean_activity_name`（`stages.py:259-274`，
// 只改名字、不动归并）—— 本实现**没有**移植它，用的是 `activity_name` 原值。
// 它只影响 `title` 的措辞，不影响分组与计数；**在真实数据上是否逐字一致未核**，
// 要拿 `out/zz_golden.txt` 的 116 条 `CH` 行逐条比才知道。

import (
	"sort"
	"strconv"
	"strings"
)

// : 剿灭作战整类并成一条时的 key／标题（`stages.py` 的 `CAMPAIGN_TITLE`）。
const campaignTitle = "剿灭作战"

// : 菜单第一层的排列顺序（`stages.py:145` 附近）。与筛选用那份 `chapterTypes` 是**两份**，
// : 注释里写明了「口径那一份不承担顺序，所以单列一份」。
var chapterOrder = []string{"MAINLINE", "MAINLINE_ACTIVITY", "CAMPAIGN", "BRANCHLINE", "ACTIVITY"}

// ChapterPart 是 chapter 底下的一个分部（一个 zone）。
type ChapterPart struct {
	ZoneID string
	Title  string
	Levels int
}

// Chapter 是菜单第一层的一条。
type Chapter struct {
	Key      string
	Title    string
	Subtitle string
	Levels   int
	Parts    []ChapterPart
	//: 整表排序用的三个键（都取 `parts[0]` 的 zone），导出只为测试与对拍。
	SortType     string
	SortTitleNum int
	SortZoneIdx  int
}

// ListChapters 复刻 `list_chapters` 的归并与排序（`stages.py:580-689`）。
//
// `stages` 应是 `LoadStageTable` 的产物（**六星档已在装载时滤掉**，见文件头那条登记）。
func ListChapters(stages []StageRecord, zones []ZoneRecord) []Chapter {
	//: ---- 步 1：zone 侧再筛一遍白名单 ----
	//: 参照实现在读侧也筛（`:603-609`）：库里可能是旧口径时代留下的，
	//: 而建库的 `carry_over` 会整表搬、不清库。⇒ 不在白名单里的直接不进菜单。
	allowed := map[string]bool{}
	for _, t := range chapterTypes {
		allowed[t] = true
	}
	zoneByID := map[string]ZoneRecord{}
	for _, z := range zones {
		if allowed[z.Type] {
			zoneByID[z.ZoneID] = z
		}
	}

	//: ---- 步 2：一趟同时算三样 ----
	totals := map[string]int{}     //: 不过滤后缀 ⇒ 「这一层报的关数」（**已不含六星**）
	counts := map[string]int{}     //: 跳过 `#f#`（`#s` 不跳）⇒ 「真实关卡数」
	names := map[string][]string{} //: 非空且未出现过的中文名（`#f#` 与普通版同名，去重）
	seen := map[string]map[string]bool{}
	for _, r := range stages {
		zid := r.ZoneID
		if _, ok := zoneByID[zid]; !ok {
			continue //: 不属于白名单 zone 的行不进菜单
		}
		totals[zid]++
		if strings.HasSuffix(r.LevelID, fourStarSuffix) {
			continue
		}
		counts[zid]++
		if r.Name == "" {
			continue
		}
		if seen[zid] == nil {
			seen[zid] = map[string]bool{}
		}
		if !seen[zid][r.Name] {
			seen[zid][r.Name] = true
			names[zid] = append(names[zid], r.Name)
		}
	}

	//: ---- 步 3：分组（key 是 activity_id；剿灭整类并一条）----
	groups := map[string][]string{}
	order := []string{}
	for _, z := range zones {
		if !allowed[z.Type] {
			continue
		}
		if counts[z.ZoneID] == 0 {
			continue //: 没有关卡的 zone 不进菜单（`:630-631`）
		}
		key := strings.TrimSpace(z.ActivityID)
		if z.Type == "CAMPAIGN" {
			key = campaignTitle
		} else if key == "" {
			key = z.ZoneID
		}
		if _, ok := groups[key]; !ok {
			order = append(order, key)
		}
		groups[key] = append(groups[key], z.ZoneID)
	}

	out := make([]Chapter, 0, len(groups))
	for _, key := range order {
		zids := groups[key]
		sort.SliceStable(zids, func(i, j int) bool {
			return zoneKeyLess(zoneByID[zids[i]], zoneByID[zids[j]])
		})
		parts := make([]ChapterPart, 0, len(zids))
		total := 0
		for _, zid := range zids {
			z := zoneByID[zid]
			lv := totals[zid]
			parts = append(parts, ChapterPart{
				ZoneID: zid,
				Title:  partTitle(z, names[zid]),
				Levels: lv,
			})
			total += lv
		}
		first := zoneByID[zids[0]]
		isCampaign := first.Type == "CAMPAIGN"
		multi := len(zids) > 1

		ch := Chapter{Key: key, Parts: parts, Levels: total}
		switch {
		case isCampaign:
			ch.Title = campaignTitle
			ch.Subtitle = pluralParts(len(zids))
		case multi:
			//: 多 zone 组：`act_name or zone_title(first) or key`
			ch.Title = firstNonEmpty(first.ActivityName, zoneTitle(first), key)
			ch.Subtitle = pluralParts(len(zids))
		default:
			//: 单 zone 组：`chapter_label(first) or zone_title(first) or act_name or key`
			//: ★ 注意 `chapter_label` **排在 `act_name` 前面**（`:669`）——
			//: 实测 `main_14` 的 `activity_id='act1mainss'`，菜单标题仍是「第十四章　慈悲灯塔」。
			ch.Title = firstNonEmpty(chapterLabel(first), zoneTitle(first),
				first.ActivityName, key)
			ch.Subtitle = ""
		}
		ch.SortType = first.Type
		ch.SortTitleNum = titleNum(first.NameTitle)
		ch.SortZoneIdx = zoneIdxOr99(first)
		out = append(out, ch)
	}

	//: ---- 步 6：整表四元键排序（`sort_key`，`:678-688`）----
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		ai, bi := chapterRank(a.SortType), chapterRank(b.SortType)
		if ai != bi {
			return ai < bi
		}
		if a.SortTitleNum != b.SortTitleNum {
			return a.SortTitleNum < b.SortTitleNum
		}
		if a.SortZoneIdx != b.SortZoneIdx {
			return a.SortZoneIdx < b.SortZoneIdx
		}
		return a.Key < b.Key
	})
	return out
}

// pluralParts 是「N 个部分」（剿灭与多 zone 组才有副标题）。
func pluralParts(n int) string { return strconv.Itoa(n) + " 个部分" }

// firstNonEmpty 取第一个非空（参照实现那串 `or` 链的 Go 写法；空串算「没有」）。
func firstNonEmpty(ss ...string) string {
	for _, s := range ss {
		if s != "" {
			return s
		}
	}
	return ""
}

// zoneIdxOr99 复刻 `_zkey` 的第一项：`zone_index` 为 NULL 时算 99。
// ⚠ NULL **不能读成 0** —— 0 是合法值（实测 170 个 zone 就是 0），读成 0 会把它们排到最前。
func zoneIdxOr99(z ZoneRecord) int {
	if z.ZoneIndex == nil {
		return 99
	}
	return *z.ZoneIndex
}

// titleNum 复刻 sort_key 的第二项：`int(name_title)`，取不到算 99。
func titleNum(s string) int {
	if !isAllDigits(s) {
		return 99
	}
	return atoiLoose(s)
}

// campaignTailNum 复刻 `_zkey` 的第二项：**只对 CAMPAIGN** 取 `zone_id` 尾号，其余恒 99。
//
// 参照实现给的理由（`:642-645`）：剿灭那 15 个 zone 的 `zone_index` **全是 0**，
// 只按它会退化成字符串序（`camp_zone_1, camp_zone_10, …, camp_zone_2`），尾号才是真实上线顺序。
func campaignTailNum(z ZoneRecord) int {
	if z.Type != "CAMPAIGN" {
		return 99
	}
	id := z.ZoneID
	i := strings.LastIndex(id, "_")
	if i < 0 {
		return 99
	}
	tail := id[i+1:]
	if !isAllDigits(tail) {
		return 99
	}
	return atoiLoose(tail)
}

// zoneKeyLess 是 parts 内的排序：`_zkey = (zone_index|99, 尾号, zone_id)`。
func zoneKeyLess(a, b ZoneRecord) bool {
	ai, bi := zoneIdxOr99(a), zoneIdxOr99(b)
	if ai != bi {
		return ai < bi
	}
	an, bn := campaignTailNum(a), campaignTailNum(b)
	if an != bn {
		return an < bn
	}
	return a.ZoneID < b.ZoneID
}

// chapterRank 复刻 `CHAPTER_ORDER.index(type) 或 9`：不在表里的排到最后。
func chapterRank(t string) int {
	for i, x := range chapterOrder {
		if x == t {
			return i
		}
	}
	return 9
}
