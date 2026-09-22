package main

// spawns.go：`spawns` 那一个键的 Go 版——出怪规格（丙阶段四·第三十批）。
//
// 权威 `ak_tactic/simgo/spec.py`：`_spawn_spec`（`:902`）＋ `_view`（`:869`）
// ＋ `_unit_spec`（`:952`）＋ `_reborn_summons_spec`（`:1106`），
// 以及它们压着的 `frontend/enemy_view.py::enemy_view`（`:46`）、
// `frontend/enemy_stats.py::enemy_stats`（`:37`）、
// `frontend/enemy_rules.py` 的三条规矩（`:58` / `:67` / `:83`）。
//
// ## 它处在哪一层
//
// `build_spec` 的 19 个顶层键里，`spawns` 是**出怪表的那一份规格**：
// 每条出怪指令一名敌人，字段就是「这只敌人是什么」。它**不吃计划**——
// 出怪表是关卡数据（`stage.timeline()`），与打法无关。
//
// ## 三个「看着简单、其实会静默」的地方
//
//  1. **天桩-乙也要从出怪表刷出来**（`spec.py:914-948`）。`diver` 这一位来自
//     `pile_mark_key`，而它查的是 `PROSE_SUMMON_EDGES`（gamedata）推出来的
//     `PILE_MARK` 表——**与装置召唤那条链是同一张表**（Go 侧那份在
//     `pileMarkKeys`；判据每次运行都拿 Python 现推的那张逐条比）。
//     漏掉它的症状极具迷惑性：乙会沿出怪表的腿走到图外漏掉，
//     判决表现为「我方一次都没出手」。
//  2. **`mark` 那一路有 `try/except`**（`spec.py:933-938`）：取不到天标就把
//     `mark` 留空、不算失败。Go 照抄这条，并把「走到过 except」记进行使计数
//     ——静默跳过的症状是规格里少一个键，而少一个键不会有任何判据报警。
//  3. **`enemy_stats` 有关卡本地定义那条回退**（`enemy_stats.py:37-55`）：
//     库里取不到时走 `stage.local_enemies()` ＋ `with_overwrite`。仓库里那
//     9 条 `useDb:false` 的本地定义（`enemy_1398_dhdcr_b` 等）目前都不在
//     出怪表里 ⇒ 真夹具零行使，判据自带一份合成关卡让它行使。
//
// ## `unported`：Go 侧**真的拿不到**的输入
//
// 见 `spawnsUnported`。它们不是「懒得搬」，而是**不在 Go 的数据面上**：
// `species_provider` 要 enemydb（不在 gamedata），`total_attack` 要装置层。
// 两条都具名列出、都由判据带证人（先证明它在 Python 侧真会动，再让 Go 声明算不了）。

import (
	"encoding/json"
	"fmt"
	"math"
	"os"
	"path/filepath"
	"sort"
	"strings"
)

// spawnsUnported 是 Go 侧**拿不到**的两样输入，具名列出、不静默当成空值。
//
// 与 `tools/check_spawns_go.py` 的 `UNPORTED` 是同一份清单的两面：
// 两边不一致时那条判据会红（防「哪天 Go 接上了却没人回头看」）。
var spawnsUnported = []string{
	//: enemydb 的 `lib.species_of`——**不在 gamedata**。它进的是
	//: `enemy_view` 的 `e.species`，而 `_unit_spec` 一个字段都不读它
	//: （实测：把 provider 换成 `None`，24 份夹具的 `spawns` 逐位相同）。
	//: ⇒ 输出不受影响，但「Go 没有这个量」这件事必须写在明面上。
	"species_provider",
	//: 全场总攻击装置（`inp.total_attack`）。它唯一的消费点是
	//: `_view` 里那句 `e.p3r_armed = total_attack is not None`——那是相性
	//: 那一族的**门**。Go 没有装置层，所以 `p3r_armed` 只能由命令参数给定
	//: （判据两侧各跑一次 true/false，证明这个**字段**本身是好的）。
	"total_attack",
}

// pileMarkKeys 是 `PILE_MARK`（`enemy_rules.py:53-55`）：乙的 key → 它砸下的天标 key。
//
// ⚠ 它由 `PROSE_SUMMON_EDGES`（`enemy.py:442-452`）里**以 `enemy_` 开头的那些**
// 取 `v[0]` 得来，不是另写一张名字表。判据每次运行都拿 Python 现推的那张比。
var pileMarkKeys = map[string]string{
	"enemy_1399_dhtb":   "enemy_1400_dhtbgj",
	"enemy_1399_dhtb_2": "enemy_1400_dhtbgj_2",
}

// ---------------------------------------------------------------- 关卡本地敌人

// localEnemyDef 是 `enemyDbRefs` 里的一条。
//
// `useDb: false` 的那些 id **不在属性库里**，整份数据写在关卡文件的
// `overwrittenData` 里，只有 `prefabKey` 指向的那个在库里（`stage.py:690-701`）。
type localEnemyDef struct {
	ID    string
	Level int
	//: 三态：`nil` = 这一条没写 `useDb`。Python 的判据是 `ref.get("useDb") is False`
	//: ——**缺键不算**，压成 bool 会把没写的那几条也当成本地定义。
	UseDB       *bool
	Overwritten map[string]json.RawMessage
	PrefabKey   string
}

// isLocal 是「这一条是不是关卡本地定义」的唯一判据（`useDb is False`）。
func (d localEnemyDef) isLocal() bool { return d.UseDB != nil && !*d.UseDB }

// parseLocalEnemyDefs 把 `enemyDbRefs` 逐条解出来（**保持文件顺序**）。
//
// 顺序是契约的一部分：`summon_level` 取的是**第一条** id 命中的那条
// （`enemy_rules.py:67-80` 是 `for ref in …: if 命中就 return`）。
func parseLocalEnemyDefs(raw map[string]json.RawMessage) ([]localEnemyDef, error) {
	out := []localEnemyDef{}
	refsRaw := raw["enemyDbRefs"]
	if len(refsRaw) == 0 {
		return out, nil
	}
	var raws []struct {
		ID              string                     `json:"id"`
		Level           *int                       `json:"level"`
		UseDB           *bool                      `json:"useDb"`
		OverwrittenData map[string]json.RawMessage `json:"overwrittenData"`
	}
	if err := json.Unmarshal(refsRaw, &raws); err != nil {
		return nil, fmt.Errorf("enemyDbRefs 解不开：%w", err)
	}
	for _, r := range raws {
		if r.ID == "" {
			continue
		}
		d := localEnemyDef{ID: r.ID, Overwritten: r.OverwrittenData}
		if r.Level != nil {
			d.Level = *r.Level
		}
		d.UseDB = r.UseDB
		//: `local_enemy_prefab`：`cell.get("m_value") if isinstance(cell, dict) else cell`
		if v, ok := unwrapCell(r.OverwrittenData["prefabKey"]); ok {
			d.PrefabKey = asString(v)
		}
		out = append(out, d)
	}
	return out, nil
}

// localEnemies 复刻 `Stage.local_enemies`（`stage.py:690`）：只有 `useDb is False`
// 且 id 非空的那几条（`is False` 是**精确判等**，缺键不算）。
func localEnemies(defs []localEnemyDef) map[string]map[string]json.RawMessage {
	out := map[string]map[string]json.RawMessage{}
	for _, d := range defs {
		if d.isLocal() {
			out[d.ID] = d.Overwritten
		}
	}
	return out
}

// localEnemyPrefab 复刻 `Stage.local_enemy_prefab`（`stage.py:703`）。
func localEnemyPrefab(defs []localEnemyDef, enemyID string) string {
	for _, d := range defs {
		if d.ID == enemyID && d.isLocal() {
			return d.PrefabKey
		}
	}
	return ""
}

// summonLevel 复刻 `summon_level`（`enemy_rules.py:67`）：被召唤的敌人用哪一档。
//
// 先看这一关的 `enemyDbRefs` 有没有点名它（**第一条命中的**），
// 没有就用 0 档——**不猜**。召唤体往往不在出怪表里，所以这条回退是常态。
func summonLevel(defs []localEnemyDef, key string) int {
	for _, d := range defs {
		if d.ID == key {
			return d.Level
		}
	}
	return 0
}

// pileMarkKey 复刻 `pile_mark_key`（`enemy_rules.py:83`）：乙 → 它砸下的天标。
//
// 乙的天赋黑板是**空的**，「砸下什么」只写在正文里，所以走 `PILE_MARK`；
// 关卡本地的 `…_dhtb_b` 先退到它的 `prefabKey`（`enemy_1399_dhtb`）再查表。
func pileMarkKey(defs []localEnemyDef, enemyID string) string {
	if k, ok := pileMarkKeys[enemyID]; ok {
		return k
	}
	return pileMarkKeys[localEnemyPrefab(defs, enemyID)]
}

// ---------------------------------------------------------------- 出怪时刻表

// timelineEvent 是摊平之后的一条出怪：`(时刻, 指令)`。
type timelineEvent struct {
	Time  float64
	Spawn EnemySpawn
}

// Timeline 复刻 `Stage.timeline()`（`stage.py:724-728`）。
//
// 两条语义都不能漏：
//
//   - **按数量展开**：`times = [fragment_start + pre_delay + i*interval …]`
//     ——一条 `count: 3` 的指令摊成三条**不同时刻**的事件；
//   - **按 (时刻, wave, fragment) 稳定排序**，不是按它在 `waves` 里的书写顺序。
//     CPython 的 `list.sort` 是稳定的，所以同一 (时刻, wave, fragment) 保持
//     **摊平顺序**（同一个 fragment 里两个动作给同一时刻时，先写的在前）。
//
// ⚠ `unsupported.go` 的 `gateSpawns` 只排「首次出现」（对理由的顺序够用）；
// 这一份要**真展开**——`spawns` 是逐事件一条规格，数量展开直接决定条数。
func (st *Stage) Timeline() []timelineEvent {
	out := make([]timelineEvent, 0, len(st.Spawns))
	for _, sp := range st.Spawns {
		for i := 0; i < sp.Count; i++ {
			t := sp.FragmentStart + sp.PreDelay + float64(i)*sp.Interval
			out = append(out, timelineEvent{Time: t, Spawn: sp})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		a, b := out[i], out[j]
		if a.Time != b.Time {
			return a.Time < b.Time
		}
		if a.Spawn.WaveIndex != b.Spawn.WaveIndex {
			return a.Spawn.WaveIndex < b.Spawn.WaveIndex
		}
		return a.Spawn.FragmentIndex < b.Spawn.FragmentIndex
	})
	return out
}

// EndPointsRowMajor 复刻 `StageMap.end_points`（`stage.py:135-138`）：
// `find("tile_end")` 是**行主序**（y 在外、x 在内），**不是**按 (x, y) 排序。
//
// ⚠ 与 `cells.go::GoalCells` 是**两个不同的量**：那一个是 `sorted(_find_goals)`
// （按 (x, y) 字典序）。`path_from` 用的是**这一个**，而它的平局判据是
// `len(p) < len(best)`（严格小于）⇒ **顺序决定平局取哪一条**，
// 两者混用会让召唤物的路线在平局时换一条（长度相同、点列不同）。
func (m StageMap) EndPointsRowMajor() [][2]int {
	out := [][2]int{}
	for y := 0; y < m.Height; y++ {
		for x := 0; x < m.Width; x++ {
			if m.Tiles[y][x].Key == "tile_end" {
				out = append(out, [2]int{x, y})
			}
		}
	}
	return out
}

// PathFrom 复刻 `geometry.path_from`（`:112-126`）：从 `cell` 走到最近的可达保护目标。
//
// ⚠ 文件里的注释说「最近按路径长度算」，但**代码比的是点数**
// （`len(p) < len(best)`）。这里照代码写，不照注释写——两者的差别在
// 「点数相同、长度不同」的平局上现形。
func (st *Stage) PathFrom(cell [2]int) [][2]int {
	var best [][2]int
	for _, goal := range st.Map.EndPointsRowMajor() {
		p := st.Map.GroundPath(cell, goal, true)
		if len(p) == 0 {
			continue
		}
		if len(best) == 0 || len(p) < len(best) {
			best = p
		}
	}
	return best
}

// viewFields 是**契约**：Python 那边读的 `e.<attr>` → Go 这份视图的字段名。
//
// 它是双向守卫的一半：判据用 ast 把 `_unit_spec` / `_spawn_spec` /
// `cannot_clear` 里对 `e` / `mark` / `unit` 的属性读取点全抽出来，
// 要求**集合相等**（不是包含）：
//
//   - 少了 → Go 在这里静默给零值（本族此前静默的根因就是这个）；
//   - 多了 → Go 搬了一个没人读的字段（「无人读」清单要长的）。
//
// 两个 `getattr(…, 默认值)` 的特殊项写在这里，值是说明文字而不是字段名：
// 权威的 `enemy_view` **不设**这两个 ⇒ `_unit_spec` 取到的是默认值本身。
var viewFields = map[string]string{
	"name":                  "Name",
	"enemy_id":              "EnemyID",
	"level":                 "Level",
	"max_hp":                "MaxHP",
	"atk":                   "Atk",
	"defense":               "Defense",
	"res":                   "Res",
	"move_speed":            "MoveSpeed",
	"attack_interval":       "AttackInterval",
	"life_cost":             "LifeCost",
	"kill_cost":             "KillCost",
	"taunt_level":           "TauntLevel",
	"is_flying":             "IsFlying",
	"apply_way":             "ApplyWay",
	"attack_range":          "AttackRange",
	"route_length":          "RouteLength",
	"always_invincible":     "AlwaysInvincible",
	"unblockable":           "Unblockable",
	"attach_damage":         "AttachDamage",
	"passive_pollut":        "PassivePollut",
	"passive_radius":        "PassiveRadius",
	"phit_cnt":              "PhitCnt",
	"phit_max_stack":        "PhitMaxStack",
	"phit_atk":              "PhitAtk",
	"phit_def":              "PhitDef",
	"phit_res":              "PhitRes",
	"phit_move":             "PhitMove",
	"phit_weight_cnt":       "PhitWeightCnt",
	"phit_pollut":           "PhitPollut",
	"phit_block_pollut":     "PhitBlockPollut",
	"skill_atk_scale_phys":  "SkillAtkScalePhys",
	"skill_atk_scale_magic": "SkillAtkScaleMagic",
	"skill_atk_init":        "SkillAtkInit",
	"skill_atk_interval":    "SkillAtkInterval",
	"skill_atk_cross":       "SkillAtkCross",
	"skill_atk_pollut":      "SkillAtkPollut",
	"skill_atk_ground_only": "SkillAtkGroundOnly",
	"skill_atk_no_normal":   "SkillAtkNoNormal",
	"reborn_left":           "RebornLeft",
	"reborn_delay":          "RebornDelay",
	"reborn_hp_ratio":       "RebornHPRatio",
	"reborn_interval":       "RebornInterval",
	"reborn_pollut":         "RebornPollut",
	"reborn_def_add":        "RebornDefAdd",
	"reborn_damage_magic":   "RebornDamageMagic",
	"reborn_summons":        "RebornSummons",
	"pm2_atk":               "Pm2Atk",
	"pm2_def":               "Pm2Def",
	"pm2_res":               "Pm2Res",
	"pm2_move":              "Pm2Move",
	"pm2_clean_def":         "Pm2CleanDef",
	"pm2_clean_move":        "Pm2CleanMove",
	"pm2_mark_pollut":       "Pm2MarkPollut",
	"pm2_invincible":        "Pm2Invincible",
	//: ⚠ 键名是 `p3r_raw` 而不是 `p3r`：`_unit_spec` 读的是
	//: `getattr(e, "p3r_raw", None)`（那个槽由 `_view` 挂上去），
	//: `e.p3r` 是 `enemy_view` 的 `affinity` 槽、这里从来没人读。
	//: 写错一个名字的症状是「判据说 Go 少一个、多一个」，而那正是这条守卫存在的意义。
	"p3r_raw":           "P3R",
	"p3r_modes":         "P3RModes",
	"p3r_weak_max":      "P3RWeakMax",
	"p3r_fall_duration": "P3RFallDuration",
	"p3r_has":           "P3RHas",
	"p3r_armed":         "P3RArmed",
	"legs":              "Legs",
	"attack_times":      "(常量 1：enemy_view 不设它)",
	"attack_type":       "(常量 PHYSICAL：enemy_view 不设它)",
}

// ViewFields 把上面那张表的 key 排好序交出去（判据拿它与 ast 抽出的读取点比）。
func ViewFields() []string {
	out := make([]string, 0, len(viewFields))
	for k := range viewFields {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}

// ---------------------------------------------------------------- 敌人视图

// enemyView 是 `enemy_view`（`frontend/enemy_view.py:46`）里**被真正读到**的
// 那一半字段，外加 `_view` 挂在后面的 P3R 那几个。
//
// ⚠ 权威那个 `enemy_view` 设了 80 多个字段（它是从 `_build_enemy` 机械生成的），
// 而 `_unit_spec` ＋ `_spawn_spec` 只读下面这些。**这不是「漏搬」**：判据用 ast
// 把两个函数的 `e.<attr>` / `mark.<attr>` 读取点全抽出来，逐条核对这份结构
// 覆盖了它——权威哪天多读一个字段，判据会红，而不是这里静默给零值。
type enemyView struct {
	Name    string
	EnemyID string
	Level   int

	MaxHP          float64
	Atk            float64
	Defense        float64
	Res            float64
	MoveSpeed      float64
	AttackInterval float64
	LifeCost       int
	KillCost       int
	TauntLevel     float64

	IsFlying    bool
	ApplyWay    string
	AttackRange float64

	RouteLength float64
	//: `enemy_view` 里这两个**恒为初值**（它们是运行期由天桩机制写的，
	//: 刚造出来的敌人两者都是 False）⇒ `cannot_clear` 在出怪表这条路上恒假。
	//: 照抄，不做「聪明」的推断。
	AlwaysInvincible bool
	Unblockable      bool

	//: `_spawn_spec` 读的是 `mark.attach_damage`（`passive_attach_damage`），
	//: 它**不在** `_unit_spec` 的输出里，只进天标那一份规格。
	AttachDamage float64

	PassivePollut float64
	PassiveRadius float64

	PhitCnt         int
	PhitMaxStack    int
	PhitAtk         float64
	PhitDef         float64
	PhitRes         float64
	PhitMove        float64
	PhitWeightCnt   int
	PhitPollut      float64
	PhitBlockPollut float64

	SkillAtkScalePhys  float64
	SkillAtkScaleMagic float64
	SkillAtkInit       float64
	SkillAtkInterval   float64
	SkillAtkCross      int
	SkillAtkPollut     float64
	SkillAtkGroundOnly bool
	SkillAtkNoNormal   bool

	RebornLeft        int
	RebornDelay       float64
	RebornHPRatio     float64
	RebornInterval    float64
	RebornPollut      float64
	RebornDefAdd      float64
	RebornDamageMagic float64
	RebornSummons     [][3]any

	Pm2Atk        float64
	Pm2Def        float64
	Pm2Res        float64
	Pm2Move       float64
	Pm2CleanDef   float64
	Pm2CleanMove  float64
	Pm2MarkPollut float64
	Pm2Invincible float64

	P3R             map[string]int
	P3RModes        map[string]map[string]int
	P3RWeakMax      float64
	P3RFallDuration float64
	P3RHas          bool
	P3RArmed        bool

	Legs []RouteLeg
}

// viewOf 复刻 `enemy_view` 的**被读部分** ＋ `_view` 的 P3R 那一段。
//
// `name` 走 Python 的取名链：`stats.name or enemy_id`，而 `stats.name` 本身在
// `EnemyLibrary.get`（`enemy.py:1030-1031`）里已经补过一次「这一档没名字就去
// 查最高档里非空的那个」。Go 的 `At()` **不做那一次回补**（它只读这一档
// 自己那条），所以这里显式走 `lib.Name`——与 `unsupported.go` 的闸门同一条口径。
func viewOf(es *EnemyStats, enemyID string, level int, legs []RouteLeg,
	route [][2]float64, lib *EnemyLibrary, p3rArmed bool) *enemyView {
	v := &enemyView{EnemyID: enemyID, Level: level}
	v.Name = es.Name
	if v.Name == "" {
		v.Name = lib.Name(enemyID)
	}
	if v.Name == "" {
		v.Name = enemyID //: `getattr(stats, 'name', enemy_id) or enemy_id`
	}

	v.MaxHP = deref(es.MaxHP)
	v.Atk = deref(es.Atk)
	v.Defense = deref(es.Defense)
	v.Res = deref(es.MagicRes)
	v.MoveSpeed = derefNone(es.MoveSpeed, 1.0)
	v.AttackInterval = derefOr(es.BaseAttackTime, 1.0)
	if es.LifePointReduce != nil {
		v.LifeCost = int(*es.LifePointReduce)
	} else {
		v.LifeCost = 1
	}
	v.KillCost = es.KillCost
	v.TauntLevel = es.TauntLevel

	v.IsFlying = es.IsFlying
	v.ApplyWay = es.ApplyWay
	if v.ApplyWay == "" {
		v.ApplyWay = "MELEE"
	}
	v.AttackRange = deref(es.RangeRadius)

	v.AttachDamage = es.PassiveAttachDamage
	v.PassivePollut = es.PassivePollut
	v.PassiveRadius = es.PassiveRadius

	v.PhitCnt = es.PhitCnt
	v.PhitMaxStack = es.PhitMaxStack
	v.PhitAtk = es.PhitAtk
	v.PhitDef = es.PhitDef
	v.PhitRes = es.PhitRes
	v.PhitMove = es.PhitMove
	v.PhitWeightCnt = es.PhitWeightCnt
	v.PhitPollut = es.PhitPollut
	v.PhitBlockPollut = es.PhitBlockPollut

	v.SkillAtkScalePhys = es.SkillAtkScalePhys
	v.SkillAtkScaleMagic = es.SkillAtkScaleMagic
	v.SkillAtkInit = es.SkillAtkInit
	v.SkillAtkInterval = es.SkillAtkInterval
	v.SkillAtkCross = es.SkillAtkCross
	v.SkillAtkPollut = es.SkillAtkPollut
	v.SkillAtkGroundOnly = es.SkillAtkGroundOnly
	v.SkillAtkNoNormal = es.SkillAtkNoNormal

	v.RebornLeft = es.RebornCount
	v.RebornDelay = es.RebornDuration
	v.RebornHPRatio = derefOr(&es.RebornHPRatio, 1.0)
	v.RebornInterval = es.RebornInterval
	v.RebornPollut = es.RebornPollut
	v.RebornDefAdd = es.RebornDefAdd
	v.RebornDamageMagic = es.RebornDamageMagic
	v.RebornSummons = es.RebornSummons

	v.Pm2Atk = es.Pm2Atk
	v.Pm2Def = es.Pm2Def
	v.Pm2Res = es.Pm2Res
	v.Pm2Move = es.Pm2Move
	v.Pm2CleanDef = es.Pm2CleanDef
	v.Pm2CleanMove = es.Pm2CleanMove
	v.Pm2MarkPollut = es.Pm2MarkPollut
	v.Pm2Invincible = es.Pm2Invincible

	//: `route_length`（`enemy_view.py:35-43`）：有腿按腿长求和，否则按折线算。
	//: `cannot_clear` 读的正是这个值。
	if len(legs) > 0 {
		ds := make([]float64, 0, len(legs))
		for _, l := range legs {
			ds = append(ds, l.Length)
		}
		v.RouteLength = sumLikePython(ds)
	} else {
		v.RouteLength = pathLengthPy(route)
	}
	v.Legs = legs

	//: ---- `_view` 在 `enemy_view` 之后挂上去的那几个 ----
	v.P3R = es.P3R
	if v.P3R == nil {
		v.P3R = map[string]int{}
	}
	v.P3RModes = es.Modes
	if v.P3RModes == nil {
		v.P3RModes = map[string]map[string]int{}
	}
	v.P3RWeakMax = es.WeakMax
	v.P3RFallDuration = es.FallDuration
	v.P3RHas = len(es.P3R) > 0 //: `stats.has_p3r` 就是 `bool(self.p3r)`
	v.P3RArmed = p3rArmed
	return v
}

// pathLengthPy 复刻 `geometry.path_length`（`:228`）：`sum(math.dist(a, b))`。
//
// ⚠ 又是**内建 `sum()`**（Neumaier），又是 `math.dist`（平方和开方）——
// 与 `stagelegs.go` 那两个 1 ulp 同一对原因，所以直接复用 `sumLikePython`。
func pathLengthPy(pts [][2]float64) float64 {
	ds := make([]float64, 0, len(pts))
	for i := 1; i < len(pts); i++ {
		dx := pts[i][0] - pts[i-1][0]
		dy := pts[i][1] - pts[i-1][1]
		ds = append(ds, math.Sqrt(dx*dx+dy*dy))
	}
	return sumLikePython(ds)
}

// ---------------------------------------------------------------- 单位规格

// unitSpecOf 复刻 `_unit_spec`（`spec.py:952-1079`）。
//
// ★ **每个键无条件写**（不 `omitempty`）：`0` 与「没有这个键」在规格里是
// 两回事——「没送」正是这一族此前静默的根因（见 `wire.go` 里 P3R 那一段的注释）。
func unitSpecOf(v *enemyView, t float64, reborn []map[string]any) map[string]any {
	return map[string]any{
		"time":     t,
		"name":     v.Name,
		"enemy_id": v.EnemyID,
		"level":    v.Level,

		"hp":         v.MaxHP,
		"atk":        v.Atk,
		"def":        v.Defense,
		"res":        v.Res,
		"move_speed": v.MoveSpeed,
		"interval":   v.AttackInterval,
		//: `enemy_view` **不设** `attack_type`，原版取到的就是 `getattr` 的默认值
		//: `PHYSICAL`。同理下面的 `attack_times` 恒 1。
		//: ⚠ 这两条不是「省略」，是**把 getattr 的默认值写实**；
		//: 判据的 ast 守卫会盯着 `_unit_spec` 的读取点有没有变。
		"damage_type":  "PHYSICAL",
		"attack_range": v.AttackRange,
		"apply_way":    v.ApplyWay,
		"attack_times": 1,

		"is_flying":    v.IsFlying,
		"unblockable":  v.Unblockable,
		"taunt_level":  int(v.TauntLevel),
		"life_cost":    v.LifeCost,
		"kill_cost":    v.KillCost,
		"cannot_clear": v.AlwaysInvincible && v.RouteLength == 0.0,

		"passive_pollut": v.PassivePollut,
		"passive_radius": v.PassiveRadius,

		"phit_cnt":          v.PhitCnt,
		"phit_max_stack":    v.PhitMaxStack,
		"phit_atk":          v.PhitAtk,
		"phit_def":          v.PhitDef,
		"phit_res":          v.PhitRes,
		"phit_move":         v.PhitMove,
		"phit_weight_cnt":   v.PhitWeightCnt,
		"phit_pollut":       v.PhitPollut,
		"phit_block_pollut": v.PhitBlockPollut,

		"skill_atk_scale_phys":  v.SkillAtkScalePhys,
		"skill_atk_scale_magic": v.SkillAtkScaleMagic,
		"skill_atk_init":        v.SkillAtkInit,
		"skill_atk_interval":    v.SkillAtkInterval,
		"skill_atk_cross":       v.SkillAtkCross,
		"skill_atk_pollut":      v.SkillAtkPollut,
		"skill_atk_ground_only": v.SkillAtkGroundOnly,
		"skill_atk_no_normal":   v.SkillAtkNoNormal,

		"reborn_left":         v.RebornLeft,
		"reborn_delay":        v.RebornDelay,
		"reborn_hp_ratio":     v.RebornHPRatio,
		"reborn_interval":     v.RebornInterval,
		"reborn_pollut":       v.RebornPollut,
		"reborn_def_add":      v.RebornDefAdd,
		"reborn_damage_magic": v.RebornDamageMagic,
		"reborn_summons":      reborn,

		"p3r":               v.P3R,
		"p3r_modes":         v.P3RModes,
		"p3r_weak_max":      v.P3RWeakMax,
		"p3r_fall_duration": v.P3RFallDuration,
		"p3r_has":           v.P3RHas,
		"p3r_armed":         v.P3RArmed,

		"pm2_atk":         v.Pm2Atk,
		"pm2_def":         v.Pm2Def,
		"pm2_res":         v.Pm2Res,
		"pm2_move":        v.Pm2Move,
		"pm2_clean_def":   v.Pm2CleanDef,
		"pm2_clean_move":  v.Pm2CleanMove,
		"pm2_mark_pollut": v.Pm2MarkPollut,
		"pm2_invincible":  v.Pm2Invincible,

		"legs": legsSpec(v.Legs),
	}
}

// legsSpec 复刻 `_legs_spec`（`spec.py:845-855`）。
//
// ⚠ walk 段送 `points` ＋ `length`，其余段只送 `seconds`——**不是**四栏全送。
// 那不是省略：`kind` 已经决定了哪几栏有意义，多送的栏会让回读方以为
// 「wait 段有长度」。
func legsSpec(legs []RouteLeg) []map[string]any {
	out := []map[string]any{}
	for _, l := range legs {
		item := map[string]any{"kind": l.Kind}
		if l.Kind == "walk" {
			pts := make([][2]float64, 0, len(l.Points))
			for _, p := range l.Points {
				pts = append(pts, [2]float64{float64(p[0]), float64(p[1])})
			}
			item["points"] = pts
			item["length"] = l.Length
		} else {
			item["seconds"] = l.Seconds
		}
		out = append(out, item)
	}
	return out
}

// ---------------------------------------------------------------- 出怪规格

// SpawnsQuery 是 `spawns` 命令的 spec 体。
type SpawnsQuery struct {
	Difficulty string `json:"difficulty,omitempty"`
	//: `inp.total_attack is not None` 的**在场性**（不是它的数值）。
	//: Go 没有装置层（见 `spawnsUnported`），所以这个门由调用方给定；
	//: 判据两侧各跑一次 true / false，证明字段本身是好的。
	P3RArmed bool `json:"p3r_armed,omitempty"`
}

// wireCheck 是**形状自检**：Go 造出来的 `spawns` 能不能被 Go 自己的消费侧
// （`wire.go::SpawnSpec`）解回来。
//
// 为什么值得做：`spawns` 是 map[string]any 拼出来的，字段名打错一个字母
// （`phit_pollut` 写成 `phit_polut`）在**跨实现对拍**里是「两边都少一个键」，
// 只有拿**真消费结构**解一次才照得出来。解回来的聚合量再与原 map 对一遍，
// 证明「解出来了」不是「解成一片零」。
type wireCheck struct {
	Decoded    bool   `json:"decoded"`
	Error      string `json:"error,omitempty"`
	N          int    `json:"n"`
	Diver      int    `json:"diver"`
	Mark       int    `json:"mark"`
	Legs       int    `json:"legs"`
	RebornRows int    `json:"reborn_rows"`
	P3RArmed   int    `json:"p3r_armed"`
	Matched    bool   `json:"matched"`
}

// SpawnsOut 是 `spawns` 的应答。
type SpawnsOut struct {
	Spawns   []map[string]any `json:"spawns"`
	Unported []string         `json:"unported"`
	Covered  map[string]int   `json:"covered"`
	Scanned  map[string]int   `json:"scanned"`
	Params   map[string]any   `json:"params"`
	Wire     wireCheck        `json:"wire"`
	//: Go 这份视图覆盖的 `e.<attr>` 清单（见 `viewFields`）。判据拿它与
	//: ast 从 `_unit_spec` / `_spawn_spec` / `cannot_clear` 抽出的读取点**双向**比。
	ViewFields []string `json:"view_fields"`
}

// spawnCounter 是行使计数的载体（两个 map 一起传太啰嗦）。
type spawnCounter struct {
	Covered map[string]int
	Scanned map[string]int
}

func (c *spawnCounter) hit(k string)  { c.Covered[k]++ }
func (c *spawnCounter) scan(k string) { c.Scanned[k]++ }

// spawnCounterKeys 是**全部**计数器名。它们在应答里一律出现（值 0 也出现）。
//
// ⚠ 「值是 0」与「没有这个键」是两回事：只写 `cnt.hit(k)` 会让 0 次的计数器
// **整个键消失**，而读的人（判据、下一个人）把「键不在」读成「这条线没接」。
// 实测踩过：判据报「Go 没报这个计数器（键被改名或没接？）」五处，
// 而那些键只是这一关**恰好一次都没走到**。
var spawnCounterKeys = []string{
	"attr_mul_applied", "diver_false", "diver_true", "legs_empty",
	"legs_nonempty", "local_override", "mark_found", "mark_missing",
	"p3r_armed_false", "p3r_armed_true", "reborn_row", "reborn_row_failed",
	"reborn_row_ok", "reborn_rows_present", "route_default", "route_found",
}

func initSpawnCounters(c *spawnCounter) {
	for _, k := range spawnCounterKeys {
		c.Covered[k] = 0
	}
}

// maxRebornDepth 是重生召唤**模板**的嵌套上限。
//
// 权威那边 `_unit_spec` → `_reborn_summons_spec` → `_view`＋`_unit_spec` 是
// **无保护的递归**：数据里若出现「模板自己也有 reborn_summons」，Python 会
// `RecursionError`（整份规格造不出来），而 Go 会**栈溢出把进程带走**——
// 那比抛错坏得多。故这里给一个上限，超了返回具名错误。
// 实测：24 份夹具 5 处 `reborn_summons` 的模板都没有自己的 reborn 行（深度 1）。
const maxRebornDepth = 4

// spawnCtx 是一次 `spawns` 调用里那些**不变的东西**（关卡、库、本地定义、开关）。
type spawnCtx struct {
	st       *Stage
	defs     []localEnemyDef
	lib      *EnemyLibrary
	locals   map[string]map[string]json.RawMessage
	muls     []RuneMul
	p3rArmed bool
	cnt      *spawnCounter
	//: 每格路线表**算一次**就够（权威是每次 `_reborn_summons_spec` 都重算，
	//: 因为它没有调用级缓存；这里缓存一份，内容逐字节相同）。
	pathCache map[string][][2]int
}

// statsFor 是**这一关的取数出口**：库（或本地定义）取出来之后再过一遍难度乘数。
//
// ⚠ 顺序不能反：权威那边 `wrap_enemy_at` 包的正是 `lib.get` 这**一个出口**
// （`sim.py:402-411`），所以「先取数、后乘」是唯一的口径。乘在别处会漏掉
// 某个调用点——那种漏法只会让**一部分**敌人变强，而判决照旧给出来。
func (c *spawnCtx) statsFor(id string, level int) (*EnemyStats, error) {
	es, err := enemyStatsFor(c.lib, c.locals, id, level, c.cnt)
	if err != nil {
		return nil, err
	}
	if len(c.muls) == 0 {
		return es, nil
	}
	c.cnt.scan("attr_mul_lookup")
	out := ApplyAttrMuls(es, c.muls)
	if out != es {
		c.cnt.hit("attr_mul_applied")
	}
	return out, nil
}

// unitSpec 是 `_unit_spec` 的入口：先算 `reborn_summons`，再拼字段。
//
// ⚠ 权威的 `_unit_spec` **总是**调 `_reborn_summons_spec`（哪怕这一只没有
// reborn 黑板——那时它立刻返回 `[]`）。所以这里也总是进。
func (c *spawnCtx) unitSpec(v *enemyView, t float64, depth int) (map[string]any, error) {
	reborn, err := c.rebornSummons(v.RebornSummons, depth)
	if err != nil {
		return nil, err
	}
	return unitSpecOf(v, t, reborn), nil
}

// SpawnsOf 造一关的出怪规格。
//
// 关卡走 `level`（关卡号／levelId）或 `path`（合成关卡 JSON 文件），
// 与 `routeplans` / `stageenv` 同一口径。
func SpawnsOf(level, path, difficulty string, p3rArmed bool) (SpawnsOut, error) {
	out := SpawnsOut{
		Spawns:   []map[string]any{},
		Unported: append([]string{}, spawnsUnported...),
		Covered:  map[string]int{},
		Scanned:  map[string]int{},
		Params: map[string]any{"level": level, "path": path,
			"difficulty": difficulty, "p3r_armed": p3rArmed},
		ViewFields: ViewFields(),
	}
	cnt := &spawnCounter{Covered: out.Covered, Scanned: out.Scanned}
	initSpawnCounters(cnt)

	st, raw, err := loadStageWithRaw(level, path, difficulty)
	if err != nil {
		return out, err
	}
	defs, err := parseLocalEnemyDefs(raw)
	if err != nil {
		return out, err
	}
	lib, err := LoadEnemyLibrary()
	if err != nil {
		return out, err
	}
	//: ---- 难度乘数（`stage_mul.py`）：先解析，再决定**要不要拒跑** ----
	defs2 := st.Difficulty
	if defs2 == "" {
		defs2 = "NORMAL"
	}
	muls := ParseRuneMuls(st.Runes, defs2)
	out.Params["stage_difficulty"] = defs2
	out.Params["rune_muls"] = len(muls)
	if bad := UnportedRuneMuls(muls); len(bad) > 0 {
		//: ★ **具名拒跑**：天赋/技能黑板乘数在 Go 里没有实现，
		//: 而它们乘完还必须重跑派生字段（少了那一步，乘数落在没人再读的表上）。
		//: 静默按普通档算会得到一份「看着对」的规格 —— 那正是这一层要防的事。
		names := make([]string, 0, len(bad))
		for _, m := range bad {
			names = append(names, m.Kind)
		}
		return out, fmt.Errorf(
			"这一关在难度 %s 下有 Go 未实现的敌人修饰层（%s）："+
				"`enemy_talent_blackb_mul` / `enemy_skill_blackb_mul` 要改黑板并重跑派生，"+
				"Go 侧一行都没有。**拒跑**而不是按普通档算——"+
				"静默少乘系数会造出一份看着对的规格",
			defs2, strings.Join(names, "、"))
	}
	locals := localEnemies(defs)
	cnt.Scanned["enemy_db_refs"] = len(defs)
	cnt.Scanned["local_defs"] = len(locals)

	_, plans, _ := st.RoutePlans()
	routes := make(map[int]RoutePlan, len(plans))
	for _, p := range plans {
		routes[p.Index] = p
	}
	cnt.Scanned["routes"] = len(plans)

	events := st.Timeline()
	cnt.Scanned["spawns"] = len(events)

	ctx := &spawnCtx{st: st, defs: defs, lib: lib, locals: locals, muls: muls,
		p3rArmed: p3rArmed, cnt: cnt, pathCache: map[string][][2]int{}}

	for _, ev := range events {
		sp := ev.Spawn
		var pts [][2]float64
		var legs []RouteLeg
		plan, ok := routes[sp.RouteIndex]
		if ok {
			cnt.hit("route_found")
			pts, legs = plan.Points, plan.Legs
		} else {
			//: `routes.get(sp.route_index, ([], 0.0, []))` 的**默认支**。
			//: 真夹具 55 关零行使（每一条出怪指令都指向存在的路线），
			//: 判据自带一份合成关卡让它行使。
			cnt.hit("route_default")
		}
		//: `wait = 0.0 if legs else w`——真夹具里 `legs` **恒非空**（`flush()`
		//: 每次至少产出 2 个点），所以这个 `else` 支只在上面那条默认支上才有意义。
		//: ⚠ 而 `wait` 最终只经 `e.wait_remaining`，`_unit_spec` 不输出它 ⇒
		//: 它在 `spawns` 上是**死值**（见 `docs/go-selfsufficiency.md` 那一节）。
		if len(legs) > 0 {
			cnt.hit("legs_nonempty")
		} else {
			cnt.hit("legs_empty")
		}
		if p3rArmed {
			cnt.hit("p3r_armed_true")
		} else {
			cnt.hit("p3r_armed_false")
		}

		es, err := ctx.statsFor(sp.EnemyID, sp.Level)
		if err != nil {
			return out, fmt.Errorf("第 %g 秒的出怪 %q（第 %d 档）取不到数值：%w",
				ev.Time, sp.EnemyID, sp.Level, err)
		}
		v := viewOf(es, sp.EnemyID, sp.Level, legs, pts, lib, p3rArmed)
		spec, err := ctx.unitSpec(v, ev.Time, 0)
		if err != nil {
			return out, err
		}

		//: ---- 天桩-乙（`spec.py:914-948`）----
		mk := pileMarkKey(defs, v.EnemyID)
		spec["diver"] = mk != ""
		if mk == "" {
			cnt.hit("diver_false")
		} else {
			cnt.hit("diver_true")
			cnt.scan("mark_attempt")
			mark, err := ctx.markSpec(mk)
			if err != nil {
				//: 权威在这里是 `except Exception: mark = None`——
				//: 它**不中止**，只是这一条出怪没有天标。照抄，但计数。
				cnt.hit("mark_missing")
			} else {
				cnt.hit("mark_found")
				spec["mark"] = mark
				spec["hit_radius"] = 0.5
			}
		}
		out.Spawns = append(out.Spawns, spec)
	}

	out.Wire = wireCheckOf(out.Spawns)
	return out, nil
}

// enemyStatsFor 复刻 `enemy_stats`（`frontend/enemy_stats.py:37-55`）。
//
// 库里取不到时走**关卡本地定义** ＋ `with_overwrite`；两边都没有就照原样
// 把错误抛出去——静默返回一个空数值会让召唤链「看起来跑了、其实什么都没算」。
func enemyStatsFor(lib *EnemyLibrary, locals map[string]map[string]json.RawMessage,
	id string, level int, cnt *spawnCounter) (*EnemyStats, error) {
	cnt.scan("enemy_lookup")
	st, err := lib.At(id, level)
	if err == nil {
		return st, nil
	}
	local, ok := locals[id]
	if !ok {
		return nil, err
	}
	cnt.hit("local_override")
	return lib.WithOverwrite(id, level, local)
}

// markSpec 复刻 `_spawn_spec` 里造天标那一段（`spec.py:932-948`）。
//
// 三处写死的常量照抄：`unblockable = True`（天赋原文「无法攻击/被阻挡」）、
// `attach_radius = 0.3`、`hit_radius = 0.5`——它们与 `mech.py` 是同一处口径。
func (c *spawnCtx) markSpec(markKey string) (map[string]any, error) {
	level := summonLevel(c.defs, markKey)
	es, err := c.statsFor(markKey, level)
	if err != nil {
		return nil, err
	}
	route := [][2]float64{{0, 0}} //: 权威那三处实参：`route=[(0.0,0.0)], legs=[], t=0.0`
	v := viewOf(es, markKey, level, nil, route, c.lib, c.p3rArmed)
	mspec, err := c.unitSpec(v, 0.0, 0)
	if err != nil {
		return nil, err
	}
	mspec["unblockable"] = true
	mspec["attach_damage"] = v.AttachDamage
	mspec["attach_radius"] = 0.3
	return mspec, nil
}

// rebornSummons 复刻 `_reborn_summons_spec`（`spec.py:1106-1158`）。
//
// 召唤物要走到最近的保护目标，所以需要**一条真路线**；而路线只取决于
// 「倒下那一刻站在哪一格」，那一格出规格时还不知道 ⇒ 把地图上**每一格**
// 的路线都算好（`sim._path_from`，与 `eta.route_plans` 同一个寻路）随规格发过去，
// Go 按召唤那刻的格子查表，查不到当场拒跑（那比随便给一条路好）。
func (c *spawnCtx) rebornSummons(rows [][3]any, depth int) ([]map[string]any, error) {
	out := []map[string]any{}
	if len(rows) == 0 {
		return out, nil
	}
	if depth >= maxRebornDepth {
		return nil, fmt.Errorf(
			"重生召唤的模板嵌套超过 %d 层：权威那边会 RecursionError，"+
				"Go 这里改成具名失败（数据里从未出现，出现即说明建模假设变了）",
			maxRebornDepth)
	}
	c.cnt.hit("reborn_rows_present")
	paths := c.rebornPaths()
	for _, row := range rows {
		c.cnt.hit("reborn_row")
		itv := asF(row[0])
		count := asI(row[1])
		key := asAnyString(row[2])
		level := summonLevel(c.defs, key)
		es, err := c.statsFor(key, level)
		if err != nil {
			//: 权威这里不兜底：`_view` 抛出去 ⇒ 整份规格造不出来。
			//: Go 同样不吞——「造不出来」比「造一份缺召唤物的规格」诚实。
			c.cnt.hit("reborn_row_failed")
			return nil, fmt.Errorf("重生召唤的模板 %q（第 %d 档）取不到数值：%w",
				key, level, err)
		}
		route := [][2]float64{{0, 0}}
		v := viewOf(es, key, level, nil, route, c.lib, c.p3rArmed)
		tmpl, err := c.unitSpec(v, 0.0, depth+1)
		if err != nil {
			return nil, err
		}
		c.cnt.hit("reborn_row_ok")
		out = append(out, map[string]any{
			"interval": itv,
			"count":    count,
			"template": tmpl,
			"paths":    paths,
		})
	}
	return out, nil
}

// rebornPaths 是那张**逐格路线表**：`"x,y"` → 走到最近保护目标的路点。
//
// 遍历顺序是 `for x: for y:`（**x 在外**），与权威一致；键是 `"x,y"`。
// 表在 `spawnCtx` 里缓存一份——内容与「每次重算」逐字节相同，只是省掉重复寻路。
func (c *spawnCtx) rebornPaths() map[string][][2]int {
	if c.pathCache != nil && len(c.pathCache) > 0 {
		return c.pathCache
	}
	m := c.st.Map
	out := map[string][][2]int{}
	for x := 0; x < m.Width; x++ {
		for y := 0; y < m.Height; y++ {
			if !m.Walkable(x, y) {
				continue
			}
			p := c.st.PathFrom([2]int{x, y})
			if len(p) == 0 {
				continue
			}
			pts := make([][2]int, 0, len(p))
			for _, q := range p {
				pts = append(pts, [2]int{q[0], q[1]})
			}
			out[fmt.Sprintf("%d,%d", x, y)] = pts
		}
	}
	c.pathCache = out
	c.cnt.Scanned["reborn_path_cells"] = len(out)
	return out
}

// wireCheckOf 把造好的 `spawns` 送进**真消费结构**解一遍（见 `wireCheck` 的注释）。
func wireCheckOf(specs []map[string]any) wireCheck {
	w := wireCheck{N: len(specs)}
	blob, err := json.Marshal(specs)
	if err != nil {
		w.Error = "序列化失败：" + err.Error()
		return w
	}
	var rt []SpawnSpec
	if err := json.Unmarshal(blob, &rt); err != nil {
		w.Error = "消费侧解不开：" + err.Error()
		return w
	}
	w.Decoded = true
	got := struct{ diver, mark, legs, reborn, armed int }{}
	for _, s := range rt {
		if s.Diver {
			got.diver++
		}
		if s.Mark != nil {
			got.mark++
		}
		got.legs += len(s.Legs)
		got.reborn += len(s.RebornSummons)
		if s.P3RArmed != nil {
			got.armed++
		}
	}
	w.Diver, w.Mark, w.Legs = got.diver, got.mark, got.legs
	w.RebornRows, w.P3RArmed = got.reborn, got.armed

	//: 再从**原 map** 数一遍同样的四个量：两边相等才叫「真解进去了」。
	raw := struct{ diver, mark, legs, reborn, armed int }{}
	for _, s := range specs {
		if b, _ := s["diver"].(bool); b {
			raw.diver++
		}
		if s["mark"] != nil {
			if _, ok := s["mark"].(map[string]any); ok {
				raw.mark++
			}
		}
		if ls, ok := s["legs"].([]map[string]any); ok {
			raw.legs += len(ls)
		}
		if rs, ok := s["reborn_summons"].([]map[string]any); ok {
			raw.reborn += len(rs)
		}
		//: ⚠ 这一条比的是**键在不在**，不是「值是不是 true」：
		//: 解码侧数的是 `P3RArmed != nil`（通道在不在），两侧同形才叫对账。
		//: 第一版拿「true 的个数」去比「非 nil 的个数」，在 p3r_armed=false
		//: 的那 72 条上必然不等 —— 是尺子错，不是对象错。
		if _, ok := s["p3r_armed"]; ok {
			raw.armed++
		}
	}
	w.Matched = w.Diver == raw.diver && w.Mark == raw.mark &&
		w.Legs == raw.legs && w.RebornRows == raw.reborn &&
		w.P3RArmed == raw.armed
	return w
}

// ---------------------------------------------------------------- 取数小工具

func deref(p *float64) float64 {
	if p == nil {
		return 0.0
	}
	return *p
}

// derefNone 复刻 `X if X is not None else dflt`：**只有 None** 落默认值。
func derefNone(p *float64, dflt float64) float64 {
	if p == nil {
		return dflt
	}
	return *p
}

// derefOr 复刻 `getattr(stats, X, dflt) or dflt`：None **与 0** 都落默认值。
func derefOr(p *float64, dflt float64) float64 {
	if p == nil || *p == 0 {
		return dflt
	}
	return *p
}

func asF(v any) float64 {
	if f, ok := v.(float64); ok {
		return f
	}
	return 0.0
}

func asI(v any) int {
	switch n := v.(type) {
	case int:
		return n
	case float64:
		return int(n)
	}
	return 0
}

func asAnyString(v any) string {
	if s, ok := v.(string); ok {
		return s
	}
	return ""
}

// loadStageWithRaw 取一关：**同时**把原始 JSON 交出来。
//
// 为什么需要 raw：`enemyDbRefs` 里 `useDb:false` 的本地定义与 `prefabKey`
// 只住在原始 JSON 里（`Stage` 结构体不带它们）。把 raw 一起带出来，
// 好过让 `Stage` 多背一个只有出怪规格用得上的字段。
func loadStageWithRaw(level, path, difficulty string) (*Stage,
	map[string]json.RawMessage, error) {
	if path != "" {
		blob, err := os.ReadFile(path)
		if err != nil {
			return nil, nil, fmt.Errorf("合成关卡读不出来（%s）：%w", path, err)
		}
		var raw map[string]json.RawMessage
		if err := json.Unmarshal(blob, &raw); err != nil {
			return nil, nil, fmt.Errorf("合成关卡不是合法 JSON（%s）：%w", path, err)
		}
		st, err := ParseStage(raw, "", "", difficulty)
		return st, raw, err
	}
	if level == "" {
		return nil, nil, fmt.Errorf("spawns 少了 level（关卡号或 levelId）或 path（合成关卡 JSON）")
	}
	idx, err := LoadIndex()
	if err != nil {
		return nil, nil, err
	}
	lid, entry, err := ResolveLevel(idx, level)
	if err != nil {
		return nil, nil, err
	}
	p := filepath.Join(DataRoot(), "map.ark-nights.com", "levels", entry.DataPath)
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, nil, fmt.Errorf("读关卡文件失败（%s）：%w", p, err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return nil, nil, fmt.Errorf("关卡文件不是合法 JSON（%s）：%w", p, err)
	}
	st, err := ParseStage(raw, lid, entry.Code, entry.Difficulty)
	return st, raw, err
}
