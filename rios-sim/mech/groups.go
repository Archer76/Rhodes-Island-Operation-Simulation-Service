// groups.go：把**四邻连片**导出给规格的**生产侧**（`rios-sim/mechspec.go`）。
//
// 为什么单独一个文件、而不是在 `huai_shu_li.go` 里加一行导出：
//
//   - 那份文件 1600 行，是本层的主要实现；为了一个 3 行的包装去动它，会让
//     「这一笔改了谁」变得难读，也会跟同时在改它的会话撞车；
//   - 导出的理由只有一个，值得单独立档：**连通域实现不许出现第二份**
//     （`environment.py:174-196` 是权威）。两份实现必然有一天不一致，而
//     「分组不一样」在下游表现为「病害值涨得不一样」——很难查。
//
// ⚠ 返回的组**顺序仍然不定**（见 `connectedGroups` 的说明）：连 Python 那边的
// 分组顺序都是从 `set` 里 `pop()` 出来的，复刻不了、也不该复刻。
// 判据按**格集合**比，并把两侧原始顺序不同的关数当成一个读数印出来。
package mech

// ConnectedGroups 是 `connectedGroups` 的导出包装（同一份实现）。
func ConnectedGroups(cells map[Cell]bool) []map[Cell]bool { return connectedGroups(cells) }
