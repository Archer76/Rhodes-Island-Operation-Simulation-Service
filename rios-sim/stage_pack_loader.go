package main

import (
	"database/sql"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"sort"
	"strings"

	_ "modernc.org/sqlite"
)

// LoadPureEnemyLibrary 从提纯后的 SQLite 敌人库加载所有敌人战斗面板与黑板
func LoadPureEnemyLibrary(dbPath string) (*EnemyLibrary, error) {
	db, err := sql.Open("sqlite", dbPath)
	if err != nil {
		return nil, fmt.Errorf("打开纯敌人库失败 (%s): %w", dbPath, err)
	}
	defer db.Close()

	rows, err := db.Query(`
		SELECT enemy_id, level, max_hp, atk, def, res, move_speed,
		       attack_interval, block_cnt, life_cost, taunt_level,
		       mass_level, is_flying, range_radius, blackboard, skills
		FROM enemy_stats
	`)
	if err != nil {
		return nil, fmt.Errorf("查询敌人属性表失败: %w", err)
	}
	defer rows.Close()

	lib := &EnemyLibrary{ByKey: make(map[string]map[int]*EnemyStats)}

	for rows.Next() {
		var enemyID string
		var level int
		var maxHP, atk, defVal, resVal, moveSpeed, atkInterval, rangeRadius float64
		var blockCnt, lifeCost, tauntLvl, massLvl int
		var isFlying bool
		var bbJSON, skillsJSON string

		err := rows.Scan(
			&enemyID, &level, &maxHP, &atk, &defVal, &resVal, &moveSpeed,
			&atkInterval, &blockCnt, &lifeCost, &tauntLvl,
			&massLvl, &isFlying, &rangeRadius, &bbJSON, &skillsJSON,
		)
		if err != nil {
			return nil, fmt.Errorf("读取敌人数据行失败: %w", err)
		}

		hp := maxHP
		attack := atk
		defense := defVal
		magicRes := resVal
		ms := moveSpeed
		interval := atkInterval
		radius := rangeRadius
		weight := float64(massLvl)
		cost := float64(lifeCost)

		st := &EnemyStats{
			EnemyID:          enemyID,
			Level:            level,
			Name:             enemyID,
			MaxHP:            &hp,
			Atk:              &attack,
			Defense:          &defense,
			MagicRes:         &magicRes,
			MoveSpeed:        &ms,
			BaseAttackTime:   &interval,
			RangeRadius:      &radius,
			Weight:           &weight,
			LifePointReduce:  &cost,
			TauntLevel:       float64(tauntLvl),
			IsFlying:         isFlying,
			ApplyWay:         "MELEE",
			Immunities:       map[string]bool{},
			TalentBlackboard: map[string]any{},
			Skills:           []any{},
		}
		if isFlying {
			st.ApplyWay = "FLY"
		}

		if bbJSON != "" && bbJSON != "{}" {
			var bb map[string]any
			if err := json.Unmarshal([]byte(bbJSON), &bb); err == nil {
				st.TalentBlackboard = bb
			}
		}

		if skillsJSON != "" && skillsJSON != "[]" {
			var sks []any
			if err := json.Unmarshal([]byte(skillsJSON), &sks); err == nil {
				st.Skills = sks
			}
		}

		st.DeriveBlackboardFields()

		if _, ok := lib.ByKey[enemyID]; !ok {
			lib.ByKey[enemyID] = make(map[int]*EnemyStats)
		}
		lib.ByKey[enemyID][level] = st
	}

	return lib, nil
}

// LoadStageFromPack 从活动关卡包 SQLite 数据库加载特定关卡，并严格校验敌人库依赖
func LoadStageFromPack(packPath string, stageID string, difficulty string, enemyLib *EnemyLibrary) (*Spec, error) {
	db, err := sql.Open("sqlite", packPath)
	if err != nil {
		return nil, fmt.Errorf("打开活动关卡包失败 (%s): %w", packPath, err)
	}
	defer db.Close()

	if difficulty == "" {
		difficulty = "NORMAL"
	}

	var code, name, mechsJSON, mechConfigJSON, reqEnemiesJSON string
	var mapW, mapH, life, deployLimit, fps int
	var costInit, costMax, costTime, speedScale float64

	row := db.QueryRow(`
		SELECT code, name, map_width, map_height, life, cost_init, cost_max,
		       cost_time, deploy_limit, speed_scale, fps, mechanisms,
		       mech_config, required_enemies
		FROM stage
		WHERE stage_id = ? AND difficulty = ?
	`, stageID, difficulty)

	err = row.Scan(
		&code, &name, &mapW, &mapH, &life, &costInit, &costMax,
		&costTime, &deployLimit, &speedScale, &fps, &mechsJSON,
		&mechConfigJSON, &reqEnemiesJSON,
	)
	if err != nil {
		return nil, fmt.Errorf("关卡包中未找到关卡 [%s] 难度 [%s]: %w", stageID, difficulty, err)
	}

	// 1. 严格依赖断言：校验所有需要的敌人是否存在于中央敌人库
	var requiredEnemies []string
	if reqEnemiesJSON != "" {
		_ = json.Unmarshal([]byte(reqEnemiesJSON), &requiredEnemies)
	}

	var missingEnemies []string
	for _, eID := range requiredEnemies {
		if enemyLib == nil || enemyLib.ByKey == nil || len(enemyLib.ByKey[eID]) == 0 {
			missingEnemies = append(missingEnemies, eID)
		}
	}
	if len(missingEnemies) > 0 {
		sort.Strings(missingEnemies)
		return nil, fmt.Errorf("关卡 [%s (%s)] 依赖中央敌人库中缺失的敌人: [%s]，严禁静默伪造或占位放行",
			code, stageID, strings.Join(missingEnemies, ", "))
	}

	spec := &Spec{
		Stage:       stageID,
		Life:        life,
		DeployLimit: deployLimit,
		CostInit:    costInit,
		CostMax:     costMax,
		CostTime:    costTime,
		SpeedScale:  speedScale,
		FPS:         fps,
		MechConfig:  make(map[string]json.RawMessage),
	}

	if mechsJSON != "" {
		_ = json.Unmarshal([]byte(mechsJSON), &spec.Mechanisms)
	}
	if mechConfigJSON != "" {
		var mc map[string]any
		if err := json.Unmarshal([]byte(mechConfigJSON), &mc); err == nil {
			for k, v := range mc {
				b, _ := json.Marshal(v)
				spec.MechConfig[k] = b
			}
		}
	}

	// 2. 读取出怪表
	spawnRows, err := db.Query(`
		SELECT enemy_id, time, level, route_index, overwritten_data
		FROM stage_spawns
		WHERE stage_id = ? AND difficulty = ?
		ORDER BY spawn_index ASC
	`, stageID, difficulty)
	if err != nil {
		return nil, fmt.Errorf("读取关卡出怪表失败: %w", err)
	}
	defer spawnRows.Close()

	for spawnRows.Next() {
		var enemyID string
		var spawnTime float64
		var level, routeIdx int
		var owData sql.NullString

		if err := spawnRows.Scan(&enemyID, &spawnTime, &level, &routeIdx, &owData); err != nil {
			return nil, fmt.Errorf("读取出怪行失败: %w", err)
		}

		stats := enemyLib.ByKey[enemyID][level]
		if stats == nil {
			// 若当前等级无显式档位，则取默认最低档
			stats = enemyLib.ByKey[enemyID][0]
		}

		hp := 1000.0
		if stats != nil && stats.MaxHP != nil {
			hp = *stats.MaxHP
		}
		atk := 100.0
		if stats != nil && stats.Atk != nil {
			atk = *stats.Atk
		}
		defVal := 0.0
		if stats != nil && stats.Defense != nil {
			defVal = *stats.Defense
		}
		resVal := 0.0
		if stats != nil && stats.MagicRes != nil {
			resVal = *stats.MagicRes
		}
		ms := 1.0
		if stats != nil && stats.MoveSpeed != nil {
			ms = *stats.MoveSpeed
		}
		interval := 1.0
		if stats != nil && stats.BaseAttackTime != nil {
			interval = *stats.BaseAttackTime
		}
		radius := 1.0
		if stats != nil && stats.RangeRadius != nil {
			radius = *stats.RangeRadius
		}
		cost := 1
		if stats != nil && stats.LifePointReduce != nil {
			cost = int(*stats.LifePointReduce)
		}
		weight := 0.0
		if stats != nil && stats.Weight != nil {
			weight = *stats.Weight
		}

		immunities := map[string]bool{}
		if stats != nil {
			for k, v := range stats.Immunities {
				immunities[k] = v
			}
		}
		sp := SpawnSpec{
			Time:            spawnTime,
			Name:            enemyID,
			EnemyID:         enemyID,
			Level:           level,
			HP:              hp,
			ATK:             atk,
			DEF:             defVal,
			RES:             resVal,
			MoveSpeed:       ms,
			Interval:        interval,
			AttackRange:     radius,
			Weight:          weight,
			LifeCost:        cost,
			DamageType:      "physical",
			ApplyWay:        "MELEE",
			Immunities:      immunities,
			CountVisibility: &CountVisibility{Hidden: false, Camouflage: false},
		}

		spec.Spawns = append(spec.Spawns, sp)
	}

	return spec, nil
}

// LoadStageObjectFromPack 从活动关卡包还原标准 *Stage 结构体，供 TUI load/solve 与几何剪枝使用
func LoadStageObjectFromPack(packPath string, query string, difficulty string) (*Stage, error) {
	db, err := sql.Open("sqlite", packPath)
	if err != nil {
		return nil, fmt.Errorf("打开关卡包失败 (%s): %w", packPath, err)
	}
	defer db.Close()

	if difficulty == "" {
		difficulty = "NORMAL"
	}

	var stageID, code, name string
	var mapW, mapH, life, deployLimit int
	var costInit, costMax, costTime, speedScale float64

	row := db.QueryRow(`
		SELECT stage_id, code, name, map_width, map_height, life, cost_init, cost_max,
		       cost_time, deploy_limit, speed_scale
		FROM stage
		WHERE (stage_id = ? OR code = ?)
		ORDER BY CASE WHEN stage_id = ? THEN 0 ELSE 1 END,
		         CASE WHEN difficulty = ? THEN 0 ELSE 1 END
		LIMIT 1
	`, query, query, query, difficulty)

	err = row.Scan(&stageID, &code, &name, &mapW, &mapH, &life, &costInit, &costMax,
		&costTime, &deployLimit, &speedScale)
	if err != nil {
		return nil, fmt.Errorf("关卡包 (%s) 中未找到关卡 [%s]: %w", packPath, query, err)
	}

	// 1. 地图网格恢复
	tiles := make([][]Tile, mapH)
	for y := 0; y < mapH; y++ {
		tiles[y] = make([]Tile, mapW)
	}

	tileRows, err := db.Query(`
		SELECT col, row, tile_key, buildable_type
		FROM stage_tiles
		WHERE stage_id = ? AND difficulty = ?
		ORDER BY row ASC, col ASC
	`, stageID, difficulty)
	if err == nil {
		defer tileRows.Close()
		for tileRows.Next() {
			var col, row int
			var k, b string
			if scanErr := tileRows.Scan(&col, &row, &k, &b); scanErr == nil {
				if row >= 0 && row < mapH && col >= 0 && col < mapW {
					tiles[row][col] = Tile{
						Key:       k,
						Buildable: b,
					}
				}
			}
		}
	}

	// 2. 路线恢复
	var routes []Route
	routeRows, err := db.Query(`
		SELECT route_index, start_col, start_row, end_col, end_row, checkpoints
		FROM stage_routes
		WHERE stage_id = ? AND difficulty = ?
		ORDER BY route_index ASC
	`, stageID, difficulty)
	if err == nil {
		defer routeRows.Close()
		for routeRows.Next() {
			var rIdx int
			var cpJSON string
			var sx, sy, ex, ey float64
			if scanErr := routeRows.Scan(&rIdx, &sx, &sy, &ex, &ey, &cpJSON); scanErr == nil {
				rt := Route{
					Index: rIdx,
					Mode:  "WALK",
					Start: [2]int{int(sx), int(sy)},
					End:   [2]int{int(ex), int(ey)},
				}
				if cpJSON != "" && cpJSON != "[]" {
					var rawCPs []struct {
						Type any     `json:"type"`
						Time float64 `json:"time"`
						Col  float64 `json:"col"`
						Row  float64 `json:"row"`
					}
					if err := json.Unmarshal([]byte(cpJSON), &rawCPs); err == nil {
						for _, cp := range rawCPs {
							p := [2]int{int(cp.Col), int(cp.Row)}
							rt.Checkpoints = append(rt.Checkpoints, Checkpoint{
								Type:     fmt.Sprintf("%v", cp.Type),
								Position: &p,
								Wait:     cp.Time,
							})
						}
					}
				}
				routes = append(routes, rt)
			}
		}
	}

	// 3. 出怪恢复
	var spawns []EnemySpawn
	spawnRows, err := db.Query(`
		SELECT enemy_id, time, level, route_index
		FROM stage_spawns
		WHERE stage_id = ? AND difficulty = ?
		ORDER BY spawn_index ASC
	`, stageID, difficulty)
	if err == nil {
		defer spawnRows.Close()
		for spawnRows.Next() {
			var eID string
			var t float64
			var lvl, rIdx int
			if scanErr := spawnRows.Scan(&eID, &t, &lvl, &rIdx); scanErr == nil {
				sp := EnemySpawn{
					EnemyID:       eID,
					Count:         1,
					Interval:      0,
					RouteIndex:    rIdx,
					Level:         lvl,
					PreDelay:      t,
					FragmentStart: t,
				}
				spawns = append(spawns, sp)
			}
		}
	}

	st := &Stage{
		LevelID:    stageID,
		Code:       code,
		Difficulty: difficulty,
		Map: StageMap{
			Width:  mapW,
			Height: mapH,
			Tiles:  tiles,
		},
		Routes: routes,
		Spawns: spawns,
		Options: StageOptions{
			CharacterLimit:   deployLimit,
			MaxLifePoint:     life,
			InitialCost:      costInit,
			MaxCost:          costMax,
			CostIncreaseTime: costTime,
			MoveMultiplier:   speedScale,
		},
		Branches: make(map[string][]BranchAction),
	}

	return st, nil
}

// TryLoadStageFromPacks 尝试从已注册的关卡资源包中读取关卡
func TryLoadStageFromPacks(query string) (*Stage, bool, error) {
	// 获取候选资源包目录列表（支持仓根、子目录、发布目录与环境变量）
	var cands []string
	if v := os.Getenv("RIOS_DB"); v != "" {
		cands = append(cands, v)
	}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		cands = append(cands, filepath.Join(dir, "data"), filepath.Join(dir, "eng", "data"), filepath.Join(dir, "..", "data"))
	}
	if cwd, err := os.Getwd(); err == nil {
		dir := cwd
		for i := 0; i < 4; i++ {
			cands = append(cands, filepath.Join(dir, "data"), filepath.Join(dir, "eng", "data"))
			parent := filepath.Dir(dir)
			if parent == dir {
				break
			}
			dir = parent
		}
	}
	cands = append(cands, "data")

	// 目前注册的活动资源包列表
	knownPacks := []string{
		"stages_act31side.sqlite",
	}

	for _, dataDir := range cands {
		for _, packFile := range knownPacks {
			packPath := filepath.Join(dataDir, packFile)
			if _, err := os.Stat(packPath); err != nil {
				continue
			}
			st, err := LoadStageObjectFromPack(packPath, query, "NORMAL")
			if err == nil && st != nil {
				return st, true, nil
			}
		}
	}

	return nil, false, nil
}
