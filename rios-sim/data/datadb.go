package data

// datadb.go：**只读取数面** —— `data/akdb.sqlite` / `data/enemydb.sqlite`。
//
// ## 它为什么存在
//
// 2026-09-26 博士裁定「走甲，有现成的数据库当然直接用」。TUI 第 [1] 步（选关卡）与
// 缺口 ② MAA 导出要的关卡表／技能表／模组表都住在 `akdb.sqlite` 里，而在这之前
// Go 侧**一行都不碰数据库**（`main.go:31-33` 那条 2026-09-18 的裁定）。详见
// `docs/python-to-go-migration.md` §七。
//
// ## ★ 两条入口**分开命名、不许混**
//
//   - `DataRoot()` → `data/gamedata/**`：**非派生**数据（要下载），缺了得重新取；
//   - 本文件 → `data/*.sqlite`：**派生**库（`python -m ak_tactic db build` 几秒重建），
//     缺了的处置是**重建**，不是下载。
//
// 两者的失效处置不同 ⇒ 合成一个入口会让「缺哪一种」在报错里分不出来。
//
// ## 三条纪律
//
//  1. **只读**：连接串一律 `mode=ro`。库是多个工具共享的，写坏它等于污染建库产物。
//  2. **缺库不是崩溃**：返回**具名**错误（`ErrDBMissing`），由调用方决定是提示重建
//     还是这条支路不走。**不许**静默返回空列表 —— 那与「这一关没有关卡」长得一样。
//  3. **不做折算**：这里只把库里已经算好的行取出来。练度折算那一整条链在别处，
//     搬进来只会多一处会漂的实现。

import (
	"database/sql"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	_ "modernc.org/sqlite" // 纯 Go 驱动，免 CGO（选型与体积实测见迁移图 §7.1）
)

// ErrDBMissing 是「库不在」这一种失败。调用方据此区分「该重建」与「查询本身有问题」。
var ErrDBMissing = errors.New("sqlite 库不在")

// DataDBDir 返回放 sqlite 库的目录。`RIOS_DB` 可覆盖（测试与外部树要用）。
func DataDBDir() string {
	if v := os.Getenv("RIOS_DB"); v != "" {
		return v
	}
	return "data"
}

// DBPath 拼出库的完整路径。`name` 传 `akdb` / `enemydb`。
func DBPath(name string) string {
	return filepath.Join(DataDBDir(), name+".sqlite")
}

// OpenReadOnly 以**只读**方式打开一个库；库不在时返回包着 ErrDBMissing 的错误。
//
// ⚠ 用 `?mode=ro` 而不是建好连接再设只读：前者是**打开那一刻**就只读，
// 后者有一段可写窗口。本仓的库是派生数据，写坏它不会有任何人立刻发现。
func OpenReadOnly(name string) (*sql.DB, error) {
	p := DBPath(name)
	if _, err := os.Stat(p); err != nil {
		return nil, fmt.Errorf("%w：%s（要重建就跑 `python -m ak_tactic db build`；"+
			"这一条是**派生**库，处置与 data/gamedata 那种非派生的不同）", ErrDBMissing, p)
	}
	db, err := sql.Open("sqlite", "file:"+p+"?mode=ro")
	if err != nil {
		return nil, fmt.Errorf("打开 %s 失败：%w", p, err)
	}
	return db, nil
}

// StageRow 是 `stage` 表里 TUI 选关卡要用的那几列。
//
// ⚠ 列名照 `docs/python-to-go-migration.md` §7.3 的**真 schema**（现查），不照命名习惯猜
// ——第一次探针把 `stage_id` 当列名，就是这么错的。
type StageRow struct {
	LevelID    string
	Code       string
	Difficulty string
	ZoneID     string
	DataPath   string
	Name       string
	StageType  string
}

// StageRows 取关卡行。`zoneID` 非空则按章节筛，`keyword` 非空则按 level_id／name 子串筛。
//
// 排序固定 `zone_id, level_id`：**有稳定顺序**，读数才可复核（否则 SQLite 的返回顺序
// 在没有 ORDER BY 时是实现细节）。
func StageRows(zoneID, keyword string) ([]StageRow, error) {
	db, err := OpenReadOnly("akdb")
	if err != nil {
		return nil, err
	}
	defer db.Close()
	//: 可空列一律 COALESCE：让下面 Scan 不必逐个用 sql.NullString，
	//: 也让「这一列是空的」与「这一列没取到」在读数上长得一样（都变成空串）——
	//: 对本函数的用途（列表展示）足够，且少一层分支。
	q := `select level_id, COALESCE(code,''), COALESCE(difficulty,''), COALESCE(zone_id,''),
	             COALESCE(data_path,''), COALESCE(name,''), COALESCE(stage_type,'')
	      from stage`
	where := []string{}
	args := []any{}
	if zoneID != "" {
		where = append(where, "zone_id = ?")
		args = append(args, zoneID)
	}
	//: ⚠ **`keyword` 不进 SQL**（2026-09-26 修的一处真 bug）：参照实现
	//: （`ak_tactic/db/stages.py:756`、`:769-772`）做的是**字面量子串**匹配
	//: （`kw = keyword.strip().upper()` 之后 `in` 四列），而 SQL `LIKE '%'||?||'%'`
	//: 会把 `%`／`_` 当**通配符**。判别实测：`keyword="%"` 时 Python 给 **0 行**，
	//: 而 LIKE 会给**全表 3055 行** —— 那等于把筛选悄悄关掉，属最坏的一类静默。
	//: ⇒ 在 Go 侧按同一口径筛（四列、统一 upper、字面量）。
	//: ★★ 2026-09-26 博士裁定：**六星档（`SIX_STAR`）不做**
	//: —— 它是游戏内的「沙盘推演」模式，本项目不模拟这些关卡，**直接排除**。
	//: 实测这 45 关全是第 15～17 章的 `#s` 险地作战变体（`act2mainss_zone1` 16 ＋
	//: `act3mainss_zone1` 15 ＋ `act4mainss_zone1` 14）。
	//: ⚠ 排除**按 `difficulty` 列**、不按 `#s` 后缀：难度是数据里的一等字段，
	//: 而后缀是命名约定（已有 `#f#`／`#s` 两种，将来还可能有别的）。
	//: ⚠ 这一条**会改分母**：原先「缓存可达 562 个关卡键」里含这 45 个 ⇒ 凡按关卡数报的
	//: 读数都要跟着改，且必须具名登记（见 `docs/python-to-go-migration.md` §8.1）。
	q += " where COALESCE(difficulty,'') <> 'SIX_STAR'"
	if len(where) > 0 {
		q += " and " + strings.Join(where, " and ")
	}
	q += " order by zone_id, level_id"
	rows, err := db.Query(q, args...)
	if err != nil {
		return nil, fmt.Errorf("查 stage 失败：%w", err)
	}
	defer rows.Close()
	kw := strings.ToUpper(strings.TrimSpace(keyword))
	out := []StageRow{}
	for rows.Next() {
		var r StageRow
		if err := rows.Scan(&r.LevelID, &r.Code, &r.Difficulty, &r.ZoneID,
			&r.DataPath, &r.Name, &r.StageType); err != nil {
			return nil, fmt.Errorf("读 stage 行失败：%w", err)
		}
		if kw != "" && !stageRowHasKeyword(r, kw) {
			continue
		}
		out = append(out, r)
	}
	return out, rows.Err()
}

// stageRowHasKeyword 复刻参照实现的 keyword 口径：**四列**（level_id / code / zone_id / 中文名），
// 统一 `upper()` 之后做**字面量**子串匹配（`ak_tactic/db/stages.py:769-772`）。
//
// ⚠ 两处都必须照抄，少一处就是「筛少了」：**列数**（少一个 `zone_id` 就搜不到按分部写的词）
// 与**大小写**（Python 先 `.upper()`，不照抄则大小写不同的写法会漏）。
func stageRowHasKeyword(r StageRow, kw string) bool {
	for _, s := range []string{r.LevelID, r.Code, r.ZoneID, r.Name} {
		if strings.Contains(strings.ToUpper(s), kw) {
			return true
		}
	}
	return false
}

// ZoneRow 是 `zone` 表里章节／活动要用的那几列。
type ZoneRow struct {
	ZoneID       string
	Type         string
	NameFirst    string
	NameSecond   string
	NameTitle    string
	ActivityID   string
	ActivityName string
}

// ZoneRows 取全部章节／活动行，固定按 `zone_index, zone_id` 排序。
func ZoneRows() ([]ZoneRow, error) {
	db, err := OpenReadOnly("akdb")
	if err != nil {
		return nil, err
	}
	defer db.Close()
	rows, err := db.Query(`select zone_id, COALESCE(type,''), COALESCE(name_first,''),
	                              COALESCE(name_second,''), COALESCE(name_title,''),
	                              COALESCE(activity_id,''), COALESCE(activity_name,'')
	                       from zone order by zone_index, zone_id`)
	if err != nil {
		return nil, fmt.Errorf("查 zone 失败：%w", err)
	}
	defer rows.Close()
	out := []ZoneRow{}
	for rows.Next() {
		var r ZoneRow
		if err := rows.Scan(&r.ZoneID, &r.Type, &r.NameFirst, &r.NameSecond,
			&r.NameTitle, &r.ActivityID, &r.ActivityName); err != nil {
			return nil, fmt.Errorf("读 zone 行失败：%w", err)
		}
		out = append(out, r)
	}
	return out, rows.Err()
}
