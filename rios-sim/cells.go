package main

// cells.go：规格里那两张**格表**——防守点格与高台格（丙阶段四·第十七批）。
//
// 它们属于 `build_spec` 19 个顶层键里的 `goal_cells` 与 `highland_cells`，
// 都只吃**关卡地图**，不碰 sim／干员／机制。
//
// ## 两个函数各有各的遍历方式，不许统一
//
// 原版这两个函数**长得像但不一样**，照抄时必须分开写：
//
//   - `_find_goals`（`spec.py:414-436`）：按 `range(height) × range(width)`
//     走，每格先问 `inside()`，判据是 `tile(x, y).key == "tile_end"`；
//     **整段包在 try 里**，任何异常都退化成**空集**。
//   - `_highland_cells`（`spec.py:1082-1103`）：直接遍历 `m.tiles` 本身
//     （`enumerate` 出行列），**不**问 `inside()`，判据是 `tile.is_highland`
//     （即 `height == "HIGHLAND"`）。
//
// 原版给 `_highland_cells` 的注释写明为什么遍历 `tiles` 而不是按宽高：
// 「地图的行列长度与这两个数并不总是一致」——按宽高取会 `IndexError`，
// 而「取不到就当不是高台」的兜底会把**真的高台格静默吃掉**。实测后果是
// 怒潮凛冬一份作业的伤害从 23260 掉到 22656，判决从「守住」变成「漏怪」。
//
// ★ **Go 这边这个坑不存在**：`parseMap` 建表时已经强制
// `len(Tiles) == Height` 且每行宽 `== Width`，不一致就**报错**而不是静默补。
// 所以下面两个函数不必带那条异常兜底——但**遍历方式仍照各自的原样**，
// 因为顺序是**输出的一部分**（见 `GoalCells` 的排序说明）。

// GoalCells 复刻 `_find_goals`，并按 `build_spec` 的用法**排好序**。
//
// ⚠ 原版返回的是 `set`，调用处是 `sorted(_find_goals(inp))` ⇒ 输出是
// **按 (x, y) 字典序**的，不是地图的行序。这里直接给出排好序的结果，
// 免得调用方再猜一次顺序。
//
// 越界那条（原版靠 `except` 退化成空集）在 Go 走不通：`parseMap` 已经保证了
// 形状，真越界说明表是坏的，那时**什么都不知道**比返回空集更诚实——空集的
// 含义是「这一关没有防守点格」，与原版那次退化的含义并不相同。
func (m StageMap) GoalCells() [][2]int {
	out := [][2]int{}
	for y := 0; y < m.Height; y++ {
		for x := 0; x < m.Width; x++ {
			if m.Tiles[y][x].Key == "tile_end" {
				out = append(out, [2]int{x, y})
			}
		}
	}
	sortIntPairs(out)
	return out
}

// HighlandCells 复刻 `_highland_cells`，**保持 `tiles` 的行序**（它不排序）。
func (m StageMap) HighlandCells() [][2]int {
	out := [][2]int{}
	for y, row := range m.Tiles {
		for x, t := range row {
			if t.Height == "HIGHLAND" {
				out = append(out, [2]int{x, y})
			}
		}
	}
	return out
}

// sortIntPairs 按 (x, y) 字典序排——对齐 Python 对 `(x, y)` 元组的 `sorted`。
func sortIntPairs(v [][2]int) {
	for i := 1; i < len(v); i++ {
		for j := i; j > 0; j-- {
			a, b := v[j-1], v[j]
			if a[0] < b[0] || (a[0] == b[0] && a[1] <= b[1]) {
				break
			}
			v[j-1], v[j] = b, a
		}
	}
}

// CellTables 是 `cells` 的应答。
type CellTables struct {
	GoalCells     [][2]int `json:"goal_cells"`
	HighlandCells [][2]int `json:"highland_cells"`
}

// CellsOf 取一关的两张格表。
func CellsOf(level string) (CellTables, error) {
	st, err := LoadStage(level)
	if err != nil {
		return CellTables{}, err
	}
	return CellTables{
		GoalCells:     st.Map.GoalCells(),
		HighlandCells: st.Map.HighlandCells(),
	}, nil
}
