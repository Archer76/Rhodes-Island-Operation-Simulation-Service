package main

// enemy.go：**Go 侧自己读敌人数据**（丙阶段二）。
//
// ## 语义逐条对齐 Python
//
// 出处都在 `ak_tactic/gamedata/enemy.py`，行号写在注释里。最容易写错的三条：
//
//  1. **逐档合并、不是取当前档**。`enemy_database.json` 的 `Value` 是按优先级
//     从低到高排的若干档，每一档只写「这一档改了什么」，其余靠 `m_defined: false`
//     表示沿用（`enemy.py:906-921`）。**免疫位也必须一起走合并**——高档位的
//     免疫位常是 `m_defined=false`，直接读当前档会全变成 False，而 BOSS 用的
//     正是高档位。
//
//  2. **`lifePointReduce` / `rangeRadius` / `levelType` / `motion` / `applyWay`
//     挂在 `enemyData` 顶层**，不在 `attributes` 下（`enemy.py:33`）。
//     误去 attributes 里找会永远取到 None。
//
//  3. ★ **黑板的字符串值住 `valueStr`，而且判据必须是「valueStr 非空则取它」**，
//     不能写成「value 没了才看 valueStr」——字符串键的 `value` 列**不是 None 而是 0**
//     （占位值），那样写仍会读到 0，看着有值、实则拿到一个假的敌人 id
//     （`enemy.py:928-948`）。
//
// ## 本轮**没有**移植的（具名，不许当成「没有这项」）
//
// `enemy.py:997` 的 `derive_blackboard_fields()`——从天赋黑板派生的**机制族**
// 字段（相性 P3R、屏障、击杀费用、重生 reborn_*、六个 phit_* 前缀、
// awake_*、aura/passive/death、skill_atk_*）整族未移植。Go 现在只给
// **核心数值**。对拍工具会把这一族按名字列出来，不静默略过。

import (
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
)

// attrFields 是 `enemyData.attributes` 里要参与合并的数值字段（`enemy.py:24-29`）。
var attrFields = []string{
	"maxHp", "atk", "def", "magicResistance",
	"moveSpeed", "attackSpeed", "baseAttackTime",
	"massLevel", "hpRecoveryPerSec", "spRecoveryPerSec", "respawnTime",
	"tauntLevel", "blockCnt", "maxDeployCount",
}

// topFields 挂在 `enemyData` 顶层（`enemy.py:33`）。
var topFields = []string{
	"lifePointReduce", "rangeRadius", "levelType", "motion", "applyWay",
}

// immuneFields 也在 attributes 里，必须一起走合并（`enemy.py:35-39`）。
var immuneFields = []string{
	"stunImmune", "silenceImmune", "sleepImmune", "frozenImmune",
	"levitateImmune", "fearedImmune", "palsyImmune", "attractImmune",
	"teleportImmune", "groundBoundImmune", "disarmedCombatImmune",
}

// EnemyStats 是一个敌人在**某一档**上的数值。
//
// ★ 每个数值都用指针：`null`（这一档没有这个量）与 `0` 是两回事，
// 用零值会让「没有」与「是 0」塌成一个。
type EnemyStats struct {
	EnemyID         string   `json:"enemy_id"`
	Level           int      `json:"level"`
	Name            string   `json:"name"`
	MaxHP           *float64 `json:"max_hp"`
	Atk             *float64 `json:"atk"`
	Defense         *float64 `json:"defense"`
	MagicRes        *float64 `json:"magic_resistance"`
	MoveSpeed       *float64 `json:"move_speed"`
	AttackSpeed     *float64 `json:"attack_speed"`
	BaseAttackTime  *float64 `json:"base_attack_time"`
	Weight          *float64 `json:"weight"`
	LifePointReduce *float64 `json:"life_point_reduce"`
	RangeRadius     *float64 `json:"range_radius"`
	HPRecovery      *float64 `json:"hp_recovery_per_sec"`
	//: 原样透传（可能是数字也可能是字符串代号），所以用 any。
	LevelType  any             `json:"level_type"`
	Immunities map[string]bool `json:"immunities"`
	IsFlying   bool            `json:"is_flying"`
	ApplyWay   string          `json:"apply_way"`
	TauntLevel float64         `json:"taunt_level"`
	//: 逐档合并后的天赋黑板（`enemy.py:922-951`）。
	TalentBlackboard map[string]any `json:"talent_blackboard"`
	//: 逐档沿用的技能原文（`enemy.py:952-962`）：`null` = 这一档没写、接着用低档；
	//: 空列表 `[]` = 显式没有技能，照旧覆盖。
	Skills []any `json:"skills"`

	//: ---- 由黑板/技能派生的字段（`enemy_derive.go`）----
	//: 平铺而不是嵌一个对象：Python 侧就是平铺的，对拍要同形。
	P3R           map[string]int            `json:"p3r"`
	WeakMax       float64                   `json:"weak_max"`
	FallDuration  float64                   `json:"fall_duration"`
	Modes         map[string]map[string]int `json:"modes"`
	ShieldHPRatio float64                   `json:"shield_hp_ratio"`
	KillCost      int                       `json:"kill_cost"`

	RebornCount       int      `json:"reborn_count"`
	RebornDuration    float64  `json:"reborn_duration"`
	RebornHPRatio     float64  `json:"reborn_hp_ratio"`
	RebornPrefix      string   `json:"reborn_prefix"`
	RebornInterval    float64  `json:"reborn_interval"`
	RebornPollut      float64  `json:"reborn_pollut"`
	RebornDefAdd      float64  `json:"reborn_def_add"`
	RebornDamageMagic float64  `json:"reborn_damage_magic"`
	RebornSummons     [][3]any `json:"reborn_summons"`

	SkillAtkKey        string  `json:"skill_atk_key"`
	SkillAtkScalePhys  float64 `json:"skill_atk_scale_phys"`
	SkillAtkScaleMagic float64 `json:"skill_atk_scale_magic"`
	SkillAtkPollut     float64 `json:"skill_atk_pollut"`
	SkillAtkTargets    int     `json:"skill_atk_targets"`
	SkillAtkCross      int     `json:"skill_atk_cross"`
	SkillAtkGroundOnly bool    `json:"skill_atk_ground_only"`
	SkillAtkNoNormal   bool    `json:"skill_atk_no_normal"`
	SkillAtkInterval   float64 `json:"skill_atk_interval"`
	SkillAtkInit       float64 `json:"skill_atk_init"`

	//: ---- 机制前缀那一族（七个前缀，见 `enemy_mech.go`）----
	//: 用匿名嵌入把 36 个字段**平铺**进 JSON：Python 侧就是平铺的，对拍要同形。
	Mechs
}

// EnemyLibrary 是 key → 档位 → 数值。
type EnemyLibrary struct {
	ByKey map[string]map[int]*EnemyStats
}

// cell 是 `{m_defined, m_value}` 包装。
type cell struct {
	Defined *bool           `json:"m_defined"`
	Value   json.RawMessage `json:"m_value"`
}

// unwrap 剥开 `{m_defined, m_value}`：未定义返回 nil。
//
// ⚠ 与 Python 的 `_unwrap`（`enemy.py:811-815`）同口径，但有**一处刻意的差别**：
// Python 对「不是这种包装」的值原样返回，这里是把它当 m_value。
// 关卡数据里这两种形态都出现过，所以两条判据都要在。
func unwrapCell(raw json.RawMessage) (json.RawMessage, bool) {
	if len(raw) == 0 {
		return nil, false
	}
	var c cell
	if err := json.Unmarshal(raw, &c); err == nil && c.Defined != nil {
		if !*c.Defined {
			return nil, false
		}
		if len(c.Value) == 0 || string(c.Value) == "null" {
			return nil, false
		}
		return c.Value, true
	}
	if string(raw) == "null" {
		return nil, false
	}
	return raw, true
}

func asFloat(raw json.RawMessage) *float64 {
	if len(raw) == 0 {
		return nil
	}
	var f float64
	if err := json.Unmarshal(raw, &f); err != nil {
		return nil
	}
	return &f
}

func asAny(raw json.RawMessage) any {
	if len(raw) == 0 {
		return nil
	}
	var v any
	if err := json.Unmarshal(raw, &v); err != nil {
		return nil
	}
	return v
}

// LoadEnemyLibrary 读 `enemy_database.json` 并逐档合并。
func LoadEnemyLibrary() (*EnemyLibrary, error) {
	p := filepath.Join(DataRoot(), "map.ark-nights.com", "levels", "enemydata",
		"enemy_database.json")
	blob, err := os.ReadFile(p)
	if err != nil {
		return nil, fmt.Errorf("读敌人库失败（%s）：%w", p, err)
	}
	var db struct {
		Enemies []struct {
			Key   string            `json:"Key"`
			Value []json.RawMessage `json:"Value"`
		} `json:"enemies"`
	}
	if err := json.Unmarshal(blob, &db); err != nil {
		return nil, fmt.Errorf("敌人库不是合法 JSON（%s）：%w", p, err)
	}
	if len(db.Enemies) == 0 {
		return nil, fmt.Errorf("敌人库里一个条目都没有（%s）", p)
	}
	lib := &EnemyLibrary{ByKey: make(map[string]map[int]*EnemyStats, len(db.Enemies))}
	for _, e := range db.Enemies {
		levels := map[int]*EnemyStats{}
		//: 逐档累积的合并态：低档先写，高档的非 null 覆盖（`enemy.py:906-961`）。
		merged := map[string]json.RawMessage{}
		mergedBB := map[string]any{}
		var mergedSkills json.RawMessage
		for _, itemRaw := range e.Value {
			var item struct {
				Level     *int            `json:"level"`
				EnemyData json.RawMessage `json:"enemyData"`
			}
			if err := json.Unmarshal(itemRaw, &item); err != nil {
				return nil, fmt.Errorf("%s 的某一档解析失败：%w", e.Key, err)
			}
			lv := 0
			if item.Level != nil {
				lv = *item.Level
			}
			var ed map[string]json.RawMessage
			if len(item.EnemyData) > 0 {
				if err := json.Unmarshal(item.EnemyData, &ed); err != nil {
					return nil, fmt.Errorf("%s 档 %d 的 enemyData 解析失败：%w", e.Key, lv, err)
				}
			}
			var attrsRaw map[string]json.RawMessage
			if a, ok := ed["attributes"]; ok && len(a) > 0 {
				_ = json.Unmarshal(a, &attrsRaw)
			}
			// 1) attributes 里的数值字段 ＋ 免疫位，两批都走合并
			for _, f := range append(append([]string{}, attrFields...), immuneFields...) {
				if v, ok := unwrapCell(attrsRaw[f]); ok {
					merged[f] = v
				}
			}
			// 2) 顶层字段
			for _, f := range topFields {
				if v, ok := unwrapCell(ed[f]); ok {
					merged[f] = v
				}
			}
			// 3) 天赋黑板：逐档合并；★ valueStr 非空则取它
			for _, bRaw := range asArray(ed["talentBlackboard"]) {
				var b struct {
					Key      string          `json:"key"`
					Value    json.RawMessage `json:"value"`
					ValueStr *string         `json:"valueStr"`
				}
				if err := json.Unmarshal(bRaw, &b); err != nil {
					continue
				}
				if b.Key == "" {
					continue
				}
				var bv any
				if b.ValueStr != nil && trimSpace(*b.ValueStr) != "" {
					bv = trimSpace(*b.ValueStr)
				} else if v, ok := unwrapCell(b.Value); ok {
					bv = asAny(v)
				}
				if bv != nil {
					mergedBB[b.Key] = bv
				}
			}
			// 4) 技能：null = 沿用低档；[] = 显式没有
			if s, ok := ed["skills"]; ok && string(s) != "null" {
				mergedSkills = s
			}
			st := &EnemyStats{
				EnemyID: e.Key, Level: lv,
				// ⚠ 名字**不参与合并**：原版读的是**当前档**的 `enemyData.name`
				// （`enemy.py:967`），不是逐档累积的那个。下面再取一次。
				Name:             "",
				MaxHP:            asFloat(merged["maxHp"]),
				Atk:              asFloat(merged["atk"]),
				Defense:          asFloat(merged["def"]),
				MagicRes:         asFloat(merged["magicResistance"]),
				MoveSpeed:        asFloat(merged["moveSpeed"]),
				AttackSpeed:      asFloat(merged["attackSpeed"]),
				BaseAttackTime:   asFloat(merged["baseAttackTime"]),
				Weight:           asFloat(merged["massLevel"]),
				LifePointReduce:  asFloat(merged["lifePointReduce"]),
				RangeRadius:      asFloat(merged["rangeRadius"]),
				HPRecovery:       asFloat(merged["hpRecoveryPerSec"]),
				LevelType:        asAny(merged["levelType"]),
				Immunities:       map[string]bool{},
				TalentBlackboard: map[string]any{},
				Skills:           []any{},
			}
			for _, f := range immuneFields {
				b, _ := asBool(merged[f])
				st.Immunities[f] = b
			}
			for k, v := range mergedBB {
				st.TalentBlackboard[k] = v
			}
			if len(mergedSkills) > 0 {
				var arr []any
				if err := json.Unmarshal(mergedSkills, &arr); err == nil {
					st.Skills = arr
				}
			}
			// `enemy.py:985-988` 三条派生
			st.IsFlying = asString(merged["motion"]) == "FLY"
			if aw := asString(merged["applyWay"]); aw != "" {
				st.ApplyWay = aw
			} else {
				st.ApplyWay = "MELEE"
			}
			if t := asFloat(merged["tauntLevel"]); t != nil {
				st.TauntLevel = *t
			}
			// 名字：战斗数据里的 name 也可能是 {m_defined,m_value} 包装
			if v, ok := unwrapCell(ed["name"]); ok {
				if s := asString(v); s != "" {
					st.Name = s
				}
			}
			// ★ 派生字段必须在**黑板合并完之后**算（`enemy.py:997`）。
			st.DeriveBlackboardFields()
			levels[lv] = st
		}
		lib.ByKey[e.Key] = levels
	}
	return lib, nil
}

// Name 复刻 `enemy.py:1124-1139` 的取名链：
// ① 图鉴表（`excel/enemy_handbook_table.json`）——**本镜像不带这个文件**，
// 所以这一步在现有数据上恒为空；② 属性库里**最高的、名字非空的那一档**；
// ③ 都没有就返回 id 本身。
//
// ⚠ ② 是常规路径而不是异常路径：`enemy_1550_dhnzzh`（祟）第 1 档的
// `enemyData.name` 是空的，名字只在第 0 档上——不接这条，Go 会给出空名字。
func (l *EnemyLibrary) Name(key string) string {
	levels, ok := l.ByKey[key]
	if !ok {
		return key
	}
	lvs := make([]int, 0, len(levels))
	for lv := range levels {
		lvs = append(lvs, lv)
	}
	sortIntsDesc(lvs)
	for _, lv := range lvs {
		if levels[lv].Name != "" {
			return levels[lv].Name
		}
	}
	return key
}

func sortIntsDesc(a []int) {
	for i := 1; i < len(a); i++ {
		for j := i; j > 0 && a[j] > a[j-1]; j-- {
			a[j], a[j-1] = a[j-1], a[j]
		}
	}
}

// At 取某 key 的某一档。
//
// ⚠ 档位不存在时**退到最高档**——与 `enemy.py:1026-1028` 逐字同口径
// （那里的注释是「关卡可能引用一个不存在的档位」）。这一条**不是我发明的**：
// Go 第一版写成大声失败，与 Python 分叉，对拍当场就会红。
func (l *EnemyLibrary) At(key string, level int) (*EnemyStats, error) {
	levels, ok := l.ByKey[key]
	if !ok {
		return nil, fmt.Errorf("敌人库里没有 %q", key)
	}
	if st, ok := levels[level]; ok {
		return st, nil
	}
	max := -1 << 31
	for lv := range levels {
		if lv > max {
			max = lv
		}
	}
	if max == -1<<31 {
		return nil, fmt.Errorf("敌人库的 %q 一档都没有", key)
	}
	return levels[max], nil
}

// Clone 深拷贝一份——`WithOverwrite` 要在副本上改，**绝不写回库**。
func (s *EnemyStats) Clone() *EnemyStats {
	c := *s
	c.Immunities = make(map[string]bool, len(s.Immunities))
	for k, v := range s.Immunities {
		c.Immunities[k] = v
	}
	c.TalentBlackboard = make(map[string]any, len(s.TalentBlackboard))
	for k, v := range s.TalentBlackboard {
		c.TalentBlackboard[k] = v
	}
	c.Skills = append([]any{}, s.Skills...)
	//: 派生字段里那两个 map 与那个切片也要深拷——浅拷会让 `WithOverwrite`
	//: 改到库里的那一份。
	c.P3R = copyIntMap(s.P3R)
	c.Modes = map[string]map[string]int{}
	for k, v := range s.Modes {
		c.Modes[k] = copyIntMap(v)
	}
	c.RebornSummons = append([][3]any{}, s.RebornSummons...)
	return &c
}

func copyIntMap(m map[string]int) map[string]int {
	out := make(map[string]int, len(m))
	for k, v := range m {
		out[k] = v
	}
	return out
}

// StatsForSpawn 取一只敌人在某一档的数值 —— **先当它在库里，取不到才走关卡本地定义**。
//
// 这是 `frontend/enemy_stats.py:34-55` 那条回退的**唯一** Go 版：
//
//	try:  return enemy_at(id, level)
//	except: local = stage.local_enemies().get(id)
//	        if not local: raise           ← 本地也没有就**照原样抛**，不静默给空值
//	        return owner.with_overwrite(id, local, level)
//
// ★ 为什么要有它（而不是各处自己写 `lib.At`）：本轮实测，第 14/16/17 章的
// `easy_14-11`/`main_14-11`/`main_16-08`/`main_17-17` 四关的出怪表**真的引用**了
// 关卡本地定义（`enemy_1424_lrboom_3` 等）。出怪那条路（`spawns.go` 的 `spawnCtx.locals`）
// 早就接了，而**闸门**那条路直接调 `lib.At` ⇒ 它对这类敌人**大声失败**。
// 两条路现在共用这一个入口，免得下次只有一条被修好。
//
// ⚠ 与 `EnemiesForStage` 里那段**故意不同**：那一段是按「库里有没有这个 id」
// （`lib.ByKey`）分支，而这里是按「取不取得到」分支。原版是后者（try/except），
// 所以这里跟原版；两者的差别只在「id 在库里但这一档不在」这种形状上。
func StatsForSpawn(lib *EnemyLibrary, st *Stage, id string, level int) (*EnemyStats, error) {
	es, err := lib.At(id, level)
	if err == nil {
		return es, nil
	}
	if st != nil {
		if def, ok := st.LocalEnemies[id]; ok && len(def) > 0 {
			return lib.WithOverwrite(id, level, def)
		}
	}
	return nil, err
}

// WithOverwrite 把关卡自带的敌人定义盖到 prefab 档位上（`enemy.py:1038-1122`）。
//
// 用在 `useDb: false` 的敌人上：它们的 id **不在属性库里**，整份数据写在关卡里，
// 只有 `prefabKey` 指向的那个在库里。怀黍离的 `enemy_1398_dhdcr_b`（天桩-甲）
// 与 `enemy_1399_dhtb_b`（天桩-乙）就是这个形态——不接这条，天桩链在
// 03/04/07/tr01/tr02 五关里整条走不通。
//
// 合并口径与库内逐档合并一致：只认 `m_defined: true` 的那些。
func (l *EnemyLibrary) WithOverwrite(id string, level int,
	overwritten map[string]json.RawMessage) (*EnemyStats, error) {
	prefab := asStringRaw(overwritten["prefabKey"])
	if prefab == "" {
		prefab = id
	}
	base, err := l.At(prefab, level)
	if err != nil {
		return nil, fmt.Errorf("%s 既不在库里，其 prefabKey（%q）也不在：%w",
			id, prefab, err)
	}
	out := base.Clone()
	out.EnemyID = id

	var attrs map[string]json.RawMessage
	if a, ok := overwritten["attributes"]; ok && len(a) > 0 {
		_ = json.Unmarshal(a, &attrs)
	}
	// 顶层字段（`m_defined` 才算）
	for _, f := range topFields {
		if v, ok := unwrapCell(overwritten[f]); ok {
			switch f {
			case "motion":
				out.IsFlying = asString(v) == "FLY"
			case "applyWay":
				if s := asString(v); s != "" {
					out.ApplyWay = s
				}
			case "levelType":
				out.LevelType = asAny(v)
			}
		}
	}
	// 名字：只认本地这一份（`enemy.py:1089`），没有就沿用 prefab 的
	if v, ok := unwrapCell(overwritten["name"]); ok {
		if s := asString(v); s != "" {
			out.Name = s
		}
	}
	// 数值：本地 `attributes` 优先，其次本地顶层，最后沿用 prefab
	pick := func(name string, cur *float64) *float64 {
		for _, src := range []map[string]json.RawMessage{attrs, overwritten} {
			if v, ok := unwrapCell(src[name]); ok {
				if f := asFloat(v); f != nil {
					return f
				}
			}
		}
		return cur
	}
	out.MaxHP = pick("maxHp", out.MaxHP)
	out.Atk = pick("atk", out.Atk)
	out.Defense = pick("def", out.Defense)
	out.MagicRes = pick("magicResistance", out.MagicRes)
	out.MoveSpeed = pick("moveSpeed", out.MoveSpeed)
	out.AttackSpeed = pick("attackSpeed", out.AttackSpeed)
	out.BaseAttackTime = pick("baseAttackTime", out.BaseAttackTime)
	out.Weight = pick("massLevel", out.Weight)
	out.LifePointReduce = pick("lifePointReduce", out.LifePointReduce)
	out.RangeRadius = pick("rangeRadius", out.RangeRadius)
	out.HPRecovery = pick("hpRecoveryPerSec", out.HPRecovery)
	if v, ok := unwrapCell(attrs["tauntLevel"]); ok {
		if f := asFloat(v); f != nil {
			out.TauntLevel = *f
		}
	}
	// 免疫位：本地写了才覆盖，否则沿用 prefab
	for _, f := range immuneFields {
		if v, ok := unwrapCell(attrs[f]); ok {
			b, _ := asBool(v)
			out.Immunities[f] = b
		}
	}
	// 天赋黑板：在 prefab 那份上叠，★ 同一条 valueStr 判据
	for _, bRaw := range asArray(overwritten["talentBlackboard"]) {
		var b struct {
			Key      string          `json:"key"`
			Value    json.RawMessage `json:"value"`
			ValueStr *string         `json:"valueStr"`
		}
		if err := json.Unmarshal(bRaw, &b); err != nil || b.Key == "" {
			continue
		}
		var bv any
		if b.ValueStr != nil && trimSpace(*b.ValueStr) != "" {
			bv = trimSpace(*b.ValueStr)
		} else if v, ok := unwrapCell(b.Value); ok {
			bv = asAny(v)
		}
		if bv != nil {
			out.TalentBlackboard[b.Key] = bv
		}
	}
	// 技能：本地写了就整段替换（`enemy.py:1116-1117`）
	if s, ok := overwritten["skills"]; ok && string(s) != "null" {
		var arr []any
		if err := json.Unmarshal(s, &arr); err == nil {
			out.Skills = arr
		}
	}
	// ⚠ `derive_blackboard_fields()` 那一族里 `mech_fields` 部分**未移植**（见文件头）；
	// 相性/屏障/击杀费用/重生/技能攻击这几支已接，且必须在这里**重算**
	// （`enemy.py:1118-1121`：本地定义换了 prefab，不重算会按老黑板召错单位）。
	out.DeriveBlackboardFields()
	return out, nil
}

// StageEnemyRef 是一关引用的一只敌人。
type StageEnemyRef struct {
	ID    string      `json:"id"`
	Level int         `json:"level"`
	Stats *EnemyStats `json:"stats"`
}

// EnemiesForStage 把一关引用的敌人连同各自那一档取出来。
//
// 与 `frontend/enemy_stats.py:37-55` 同口径：**先当它在库里；取不到才走本地覆盖**；
// 两边都没有就照原样把异常抛出去——静默返回一个空数值会让召唤链
// 「看起来跑了、其实什么都没算」。
func EnemiesForStage(stageID string) (string, []StageEnemyRef, error) {
	idx, err := LoadIndex()
	if err != nil {
		return "", nil, err
	}
	lid, entry, err := ResolveLevel(idx, stageID)
	if err != nil {
		return "", nil, err
	}
	p := filepath.Join(DataRoot(), "map.ark-nights.com", "levels", entry.DataPath)
	blob, err := os.ReadFile(p)
	if err != nil {
		return "", nil, fmt.Errorf("读关卡文件失败（%s）：%w", p, err)
	}
	var raw map[string]json.RawMessage
	if err := json.Unmarshal(blob, &raw); err != nil {
		return "", nil, err
	}
	lib, err := LoadEnemyLibrary()
	if err != nil {
		return "", nil, err
	}
	refs := []StageEnemyRef{}
	for _, rRaw := range asArray(raw["enemyDbRefs"]) {
		var r struct {
			ID              string                     `json:"id"`
			Level           *int                       `json:"level"`
			UseDB           *bool                      `json:"useDb"`
			OverwrittenData map[string]json.RawMessage `json:"overwrittenData"`
		}
		if err := json.Unmarshal(rRaw, &r); err != nil || r.ID == "" {
			continue
		}
		lv := 0
		if r.Level != nil {
			lv = *r.Level
		}
		var st *EnemyStats
		if _, ok := lib.ByKey[r.ID]; ok {
			st, err = lib.At(r.ID, lv)
		} else if r.UseDB != nil && !*r.UseDB && len(r.OverwrittenData) > 0 {
			st, err = lib.WithOverwrite(r.ID, lv, r.OverwrittenData)
		} else {
			err = fmt.Errorf("敌人库里没有 %q，而它在关卡里也不是 useDb:false 的本地定义", r.ID)
		}
		if err != nil {
			return "", nil, err
		}
		// 名字兜底（`enemy.py:1030-1031`：档位名为空时去查图鉴/库）。
		// 在副本上填，避免把库那一份改掉。
		if st.Name == "" {
			c := st.Clone()
			c.Name = lib.Name(r.ID)
			st = c
		}
		refs = append(refs, StageEnemyRef{ID: r.ID, Level: lv, Stats: st})
	}
	return lid, refs, nil
}

// ---------------------------------------------------------------- 小工具

func asArray(raw json.RawMessage) []json.RawMessage {
	if len(raw) == 0 || string(raw) == "null" {
		return nil
	}
	var out []json.RawMessage
	if err := json.Unmarshal(raw, &out); err != nil {
		return nil
	}
	return out
}

func asString(raw json.RawMessage) string {
	if len(raw) == 0 {
		return ""
	}
	var s string
	if err := json.Unmarshal(raw, &s); err != nil {
		return ""
	}
	return s
}

// asStringRaw 读一个**可能带 `{m_value}` 包装**的字符串。
// 关卡本地定义的 `prefabKey` 两种形态都出现过（`stage.py:710-713` 同样兜了一层）。
func asStringRaw(raw json.RawMessage) string {
	if v, ok := unwrapCell(raw); ok {
		return asString(v)
	}
	return ""
}

func asBool(raw json.RawMessage) (bool, bool) {
	if len(raw) == 0 {
		return false, false
	}
	var b bool
	if err := json.Unmarshal(raw, &b); err != nil {
		return false, false
	}
	return b, true
}

func trimSpace(s string) string {
	i, j := 0, len(s)
	for i < j && (s[i] == ' ' || s[i] == '\t' || s[i] == '\n' || s[i] == '\r') {
		i++
	}
	for j > i && (s[j-1] == ' ' || s[j-1] == '\t' || s[j-1] == '\n' || s[j-1] == '\r') {
		j--
	}
	return s[i:j]
}
