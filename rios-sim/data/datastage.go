package data

// datastage.go：关卡取数的**三层**（`docs/python-to-go-migration.md` §7.5／§7.6）。
//
// 为什么另起一个文件、而不是改 `datadb.go` 里的 `StageRows`：那个函数的**四处偏差**
// 已鉴定（§7.6 的表），但它现在还被测试用着；新实现放在这里，名字不与它冲突，
// 等新的一路验通、TUI 接上之后再把旧的摘掉。**不搞「一边改一边用」的中间态。**
//
// ## 三层（对照 Python 侧）
//
//	[1] 章／活动   ← `ak_tactic/db/stages.py::list_chapters`（:580）    ← 本文件 ListChapters
//	[2] 环境分层   ← `ak_tactic/tui/data.py::zone_envs`（:596）        ← 本文件 ZoneEnvs
//	[3] 关卡列表   ← `ak_tactic/db/stages.py::list_stages`（:746）     ← 本文件 ListStages
//
// ## 三条照抄的口径（不照抄就「看着对、筛错了」）
//
//  1. **`keyword` 是字面量子串、匹配四列、且先 `.upper()`**（`:756`、`:769-772`）。
//     不是 SQL `LIKE` —— `%` 在字面量口径下匹配不到任何东西（实测 Python 给 0 行，
//     而 `LIKE '%'||?||'%'` 会给全表 3055）。列数是四列：level_id／code／zone_id／中文名。
//  2. **排序不能在 SQL 里做**：`_code_sort_key` 是**分段数值序**（让 `2-7` 排在 `2-10` 前面，
//     `:785-790`），SQLite 没有现成表达 ⇒ 取回后在内存按同一个 key 排。
//  3. **`zone_id` 精确、`zone` 子串**（`:763`、`:765`）：`main_1` 用子串会把 `main_10` 捞出来。
//
// ★ 六星档（`SIX_STAR`／`#s`）**要**（博士 2026-09-27 裁定，**推翻** 09-26 那笔）。
//
//	09-26 那次把它当成「沙盘推演」直接排除 —— **弄错了**：15～17 章的六星是
//	**险地作战**，**等效于之前的突袭**，必须加回。模拟器不做沙盘推演 ⇒ 实际打的
//	是它的四星版本（`#s` 与同名普通档**共用同一份 `data_path`**，45/45 实测）。
//	⇒ 装载口**不再**按 `difficulty` 过滤（`datadb.go` 的 SQL 侧同样去掉）。
//
//	⚠ 它会改分母：`stage` 表 45 条回到取数面（详见
//	`docs/python-to-go-migration.md` §8.1 与 §12.10 的登记）。

import (
	"fmt"
	"sort"
	"strings"
)

// : 四星档后缀（`ak_tactic/db/stages.py:89`）。六星档的 `#s` 不走这里 —— 它按 difficulty 认（加回后照旧在表里）。
const fourStarSuffix = "#f#"

// : 难度档的**显示顺序**（`ak_tactic/db/stages.py:92`）。
// : 注意它是四档：`RUNE` 在本仓 `stage` 表里实测未出现（表里只有 NORMAL／FOUR_STAR／SIX_STAR）。
var difficultyOrder = []string{"NORMAL", "FOUR_STAR", "RUNE", "SIX_STAR"}

// : 环境分层的顺序与中文名（`ak_tactic/db/stages.py:116`、`:125`）。
var envOrder = []string{"EASY", "NORMAL", "TOUGH", "ALL"}

var envLabels = map[string]string{
	"EASY": "剧情体验", "NORMAL": "标准实战", "TOUGH": "磨难险地", "ALL": "通用",
	"NONE": "", "": "",
}

// : 只取这几类 zone（`ak_tactic/db/stages.py:137`；博士 2026-09-18 裁定）。
var chapterTypes = []string{"MAINLINE", "BRANCHLINE", "CAMPAIGN", "MAINLINE_ACTIVITY", "ACTIVITY"}

// : 活动 zone 的**去留模式**（博士 2026-09-27 两次裁定；与 `ak_tactic/db/stages.py`
// 的 `ACTIVITY_KEEP_MARKERS` 是**同一份口径**）。
//
// 第一次：原版 `actNNside`、复刻 `actNNsre`。第二次加回两族：
//
//	· `mini` —— 故事集（`act8mini` 如我所见、`act18mini` 我们明日见…共 15 族 249 关）；
//	· `dN`   —— 早期活动（`act9d0`／`act17d5` 生于黑夜、`act14d7` 喧闹法则、
//	  `act11d7` 火蓝之心、`act13d2` 骑兵与猎人、`act10d5` 乌萨斯的孩子们…共 8 族 143 关），
//	  模式是**字母 d 紧跟一个数字**，见 `hasDNCode`。
//
// ★ 为什么第一版漏了它们：这两族的 `activityId` 是空的，谓词退到用 `zone_id` 判，
// 而 `act8mini_zone1`／`act9d0_zone1` 里两个标记都不含 ⇒ 整族被拒。
//
// ★ 仍然不进库的是小玩法与联动：`bossrush`／`enemyduel`／`multi`／`break`／`vecb`／
// `autochess`／`arkhub`／`dp`／`football`／`lock`／`vhalfidle`／`fun`／`zone` 族
// （共 24 族 380 关）。`dp`／`duel`／`halfidle` 里 `d` 后面跟的是**字母**，
// 所以 `hasDNCode` 不会误收 —— 判据里有这三条负对照。
//
// ★ 这是**模式**不是一张清单：将来新增的活动按它自动决定去留，不必回来改这里。
var activityKeepMarkers = []string{"sre", "side", "mini"}

// hasDNCode 判「代号里有没有 `d` 紧跟数字」这一族（`act9d0`／`act17d5`／`act13d2`）。
//
// ★ 不列举 `d0/d2/d3/d5/d7`：将来再出 `d9` 也自动进来。
// ★ 也**不会**误收小玩法 —— `dp`（逐影集趣）、`duel`（争锋频道）、`halfidle`
// （次生预案）里 `d` 后面都是字母（判据把这三个都钉住了）。
func hasDNCode(code string) bool {
	for i := 0; i+1 < len(code); i++ {
		if code[i] == 'd' && code[i+1] >= '0' && code[i+1] <= '9' {
			return true
		}
	}
	return false
}

// keepsZone 是「这个 zone 该不该进菜单」的唯一判定点（`stages.keeps_zone` 的镜像）。
//
// ★ 为什么读侧也要有这一份：库里那份可能是**旧口径时代留下的**，而建库的
// `carry_over` 会整表搬、不清库 —— 参照实现的读侧也筛（`stages.py` 的 `list_zones`，
// 那里写着「菜单不该因为库的状态就把肉鸽、爬塔那些摆出来」）。写侧（`db stage-prune`）
// 已经把库清干净，这一层是**防旧库**的第二道；两道用同一个谓词，口径只有一份。
func keepsZone(z ZoneRecord) bool {
	for _, t := range chapterTypes {
		if z.Type != t {
			continue
		}
		if t != "ACTIVITY" {
			return true
		}
		code := strings.ToLower(strings.TrimSpace(z.ActivityID))
		if code == "" {
			code = strings.ToLower(z.ZoneID)
		}
		for _, m := range activityKeepMarkers {
			if strings.Contains(code, m) {
				return true
			}
		}
		return hasDNCode(code)
	}
	return false
}

// StageRecord 是 `stage` 表的一行（TUI 三层都要的那几列）。
//
// ⚠ `ZoneID` 之外的**分部归属**要看 `ZoneIndex`（`zone` 表），它**可为 NULL**
// —— NULL 不能读成 0（零是合法值，170 个 zone 就是 0，见子代理的读数）。
type StageRecord struct {
	LevelID     string
	Code        string
	Difficulty  string
	ZoneID      string
	DataPath    string
	Name        string
	StageType   string
	DiffGroup   string
	HardLevelID string
}

// ZoneRecord 是 `zone` 表的一行。`ZoneIndex` 用指针：**区分「没有」与「0」**。
type ZoneRecord struct {
	ZoneID       string
	ZoneIndex    *int
	Type         string
	NameFirst    string
	NameSecond   string
	NameTitle    string
	ActivityID   string
	ActivityName string
}

// LoadStageTable 一次把两张表读进来。
//
// ★ 为什么**一次读全表**而不是按条件下 SQL：§7.6 第 2／3 条的排序（分段数值序）
// 在 SQL 里表达不出来；而且三层（章节／环境／列表）都在同一份数据上做不同聚合，
// 分开下 SQL 会变成三份各自实现的口径 —— 「同一件事只许有一份实现」。
//
// ★ 2026-09-27：**不再**按 difficulty 滤任何档（09-26 那笔六星排除已反转，
// 见文件头那条登记）。
func LoadStageTable() ([]StageRecord, []ZoneRecord, error) {
	db, err := OpenReadOnly("akdb")
	if err != nil {
		return nil, nil, err
	}
	defer db.Close()

	rows, err := db.Query(`select level_id, COALESCE(code,''), COALESCE(difficulty,''),
	                              COALESCE(zone_id,''), COALESCE(data_path,''), COALESCE(name,''),
	                              COALESCE(stage_type,''), COALESCE(diff_group,''),
	                              COALESCE(hard_level_id,'')
	                       from stage`)
	if err != nil {
		return nil, nil, fmt.Errorf("查 stage 失败：%w", err)
	}
	defer rows.Close()
	stages := []StageRecord{}
	for rows.Next() {
		var r StageRecord
		if err := rows.Scan(&r.LevelID, &r.Code, &r.Difficulty, &r.ZoneID, &r.DataPath,
			&r.Name, &r.StageType, &r.DiffGroup, &r.HardLevelID); err != nil {
			return nil, nil, fmt.Errorf("读 stage 行失败：%w", err)
		}
		stages = append(stages, r)
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	zrows, err := db.Query(`select zone_id, zone_index, COALESCE(type,''),
	                               COALESCE(name_first,''), COALESCE(name_second,''),
	                               COALESCE(name_title,''), COALESCE(activity_id,''),
	                               COALESCE(activity_name,'')
	                        from zone`)
	if err != nil {
		return nil, nil, fmt.Errorf("查 zone 失败：%w", err)
	}
	defer zrows.Close()
	zones := []ZoneRecord{}
	for zrows.Next() {
		var z ZoneRecord
		var idx *int
		if err := zrows.Scan(&z.ZoneID, &idx, &z.Type, &z.NameFirst, &z.NameSecond,
			&z.NameTitle, &z.ActivityID, &z.ActivityName); err != nil {
			return nil, nil, fmt.Errorf("读 zone 行失败：%w", err)
		}
		z.ZoneIndex = idx
		zones = append(zones, z)
	}
	return stages, zones, zrows.Err()
}

// StageFilter 是 `list_stages` 的入参（`ak_tactic/db/stages.py:746-749`）。
//
// ⚠ 它有**两个**「zone」：`ZoneID` 精确、`Zone` 子串 —— 别合并（`:763`、`:765`）。
type StageFilter struct {
	Keyword         string
	Difficulty      string
	Zone            string //: 子串匹配（命令行用）
	ZoneID          string //: 精确匹配（选关界面按分部下钻用）
	Env             string //: 对 `diff_group`，大小写不敏感
	ExcludeFourStar bool
	Limit           int //: 0 或负数 = 不限（`:782`）
}

// ListStages 复刻 `list_stages`。**筛序**：exclude_four_star → difficulty → zone_id →
// zone → env → keyword，全 AND（`:759-773`）；**排序**见 `lessStage`。
func ListStages(stages []StageRecord, f StageFilter) []StageRecord {
	kw := strings.ToUpper(strings.TrimSpace(f.Keyword))
	out := make([]StageRecord, 0, len(stages))
	for _, r := range stages {
		if f.ExcludeFourStar && strings.HasSuffix(r.LevelID, fourStarSuffix) {
			continue
		}
		if f.Difficulty != "" && strings.ToUpper(r.Difficulty) != strings.ToUpper(f.Difficulty) {
			continue
		}
		if f.ZoneID != "" && r.ZoneID != f.ZoneID { //: 精确
			continue
		}
		if f.Zone != "" && !strings.Contains(strings.ToUpper(r.ZoneID), strings.ToUpper(f.Zone)) {
			continue //: 子串
		}
		if f.Env != "" && strings.ToUpper(r.DiffGroup) != strings.ToUpper(f.Env) {
			continue
		}
		if kw != "" && !stageHasKeyword(r, kw) {
			continue
		}
		out = append(out, r)
	}
	sort.SliceStable(out, func(i, j int) bool { return lessStage(out[i], out[j]) })
	if f.Limit > 0 && len(out) > f.Limit {
		out = out[:f.Limit]
	}
	return out
}

// stageHasKeyword 复刻 `:769-772` 的四列字面量匹配（**列数与大小写都要照抄**）。
func stageHasKeyword(r StageRecord, kw string) bool {
	for _, s := range []string{r.LevelID, r.Code, r.ZoneID, r.Name} {
		if strings.Contains(strings.ToUpper(s), kw) {
			return true
		}
	}
	return false
}

// lessStage 是 `:775-781` 那个四元键：`(是否四星档, 难度序号, code 分段序, level_id)`。
//
// ⚠ 第一项是**布尔**（`endswith("#f#")`），所以**四星档排在最后** —— 不是排在最前。
func lessStage(a, b StageRecord) bool {
	af := strings.HasSuffix(a.LevelID, fourStarSuffix)
	bf := strings.HasSuffix(b.LevelID, fourStarSuffix)
	if af != bf {
		return !af //: false < true ⇒ 非四星在前
	}
	ai, bi := diffRank(a.Difficulty), diffRank(b.Difficulty)
	if ai != bi {
		return ai < bi
	}
	ak, bk := codeSortKey(a.Code), codeSortKey(b.Code)
	if c := compareCodeKey(ak, bk); c != 0 {
		return c < 0
	}
	return a.LevelID < b.LevelID
}

// diffRank 复刻 `DIFFICULTY_ORDER.index(x) if x in ... else len(...)`（`:777-778`）：
// **不在表里的排到最后**（而不是报错）。
func diffRank(d string) int {
	for i, x := range difficultyOrder {
		if x == d {
			return i
		}
	}
	return len(difficultyOrder)
}

// codeKeyPart 是 `_code_sort_key` 的一段：数字段按**数值**比，非数字段按**字符串**比。
type codeKeyPart struct {
	isNum bool
	num   int
	str   string
}

// codeSortKey 复刻 `_code_sort_key`（`:785-790`）：
// 去掉 `#f#`、把 `_` 换成 `-`、按 `-` 分段，数字段 `(0, 数值, "")`、其余 `(1, 0, 串)`。
//
// 它的存在理由写在参照实现的 docstring 里：「让 `2-7` 排在 `2-10` 前面（纯字符串排序会反）」。
func codeSortKey(code string) []codeKeyPart {
	s := strings.ReplaceAll(strings.ReplaceAll(code, fourStarSuffix, ""), "_", "-")
	parts := []codeKeyPart{}
	for _, chunk := range strings.Split(s, "-") {
		if n, ok := atoiStrict(chunk); ok {
			parts = append(parts, codeKeyPart{isNum: true, num: n})
		} else {
			parts = append(parts, codeKeyPart{isNum: false, str: chunk})
		}
	}
	return parts
}

// compareCodeKey 逐段比两个 code 键。
func compareCodeKey(a, b []codeKeyPart) int {
	for i := 0; i < len(a) && i < len(b); i++ {
		x, y := a[i], b[i]
		if x.isNum != y.isNum {
			//: 参照实现的元组里 (0, n, "") < (1, 0, s)：数字段永远排在非数字段前。
			if x.isNum {
				return -1
			}
			return 1
		}
		if x.isNum {
			if x.num != y.num {
				if x.num < y.num {
					return -1
				}
				return 1
			}
			continue
		}
		if x.str != y.str {
			if x.str < y.str {
				return -1
			}
			return 1
		}
	}
	switch {
	case len(a) < len(b):
		return -1
	case len(a) > len(b):
		return 1
	}
	return 0
}

// atoiStrict 只认**纯十进制数字**（Python 的 `chunk.isdigit()`）。
// ⚠ 不用 `strconv.Atoi` 直接判：它会接受 `+7`／`-7`，而 `isdigit()` 不接受。
func atoiStrict(s string) (int, bool) {
	if s == "" {
		return 0, false
	}
	n := 0
	for _, c := range s {
		if c < '0' || c > '9' {
			return 0, false
		}
		n = n*10 + int(c-'0')
	}
	return n, true
}
