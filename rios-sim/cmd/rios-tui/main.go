// rios-tui —— R.I.O.S. 的界面本体（Go ＋ bubbletea）。
//
// # 为什么住在子目录
//
// `rios-sim` 根目录那批 .go 全是 `package main`，界面与引擎**无法同进程**
// （迁移图 §6 的硬事实）。把它放进 `cmd/rios-tui` 之后：界面这边可以
// `import "rios-sim/data"` 直接取数，引擎那边照旧走**子进程 JSON 行协议**。
// 也正因为这个，`data` 当初才从根包搬成可导入的子包。
//
// # 三种跑法
//
//	rios-tui                 交互（需要终端）
//	rios-tui -selftest       无终端自检：逐层渲染并断言，退出码即判据
//	rios-tui -chapters 等    一次性打印取数结果（给判据与排障用）
package main

import (
	"flag"
	"fmt"
	"os"
	"path/filepath"
	"strings"

	tea "github.com/charmbracelet/bubbletea"

	"rios-sim/data"
)

func main() {
	var (
		selftest = flag.Bool("selftest", false, "无终端自检：逐层渲染并断言，退出码即判据")
		dumpCh   = flag.Bool("chapters", false, "打印章节表后退出")
		dumpEnv  = flag.String("envs", "", "打印该 zone 的环境分层后退出")
		dumpSt   = flag.String("stages", "", "打印该 zone 的关卡列表后退出（可配 -env 再筛）")
		env      = flag.String("env", "", "与 -stages 连用：按环境分层筛（EASY/NORMAL/TOUGH/ALL）")
	)
	flag.Parse()

	if err := resolveDataDir(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(3)
	}

	stages, zones, err := data.LoadStageTable()
	if err != nil {
		fmt.Fprintf(os.Stderr, "★ 读关卡表失败：%v\n", err)
		os.Exit(3)
	}

	switch {
	case *selftest:
		os.Exit(runSelftest(stages, zones))
	case *dumpCh:
		printChapters(stages, zones)
		return
	case *dumpEnv != "":
		printEnvs(stages, *dumpEnv)
		return
	case *dumpSt != "":
		printStages(stages, *dumpSt, *env)
		return
	}

	p := tea.NewProgram(newRoot(newAppCtx(stages, zones), welcomeScreen{}), tea.WithAltScreen())
	if _, err := p.Run(); err != nil {
		fmt.Fprintf(os.Stderr, "★ 界面退出：%v\n", err)
		os.Exit(1)
	}
}

// newAppCtx 组装共享态。尺寸先给一个常见默认值，真值由 `tea.WindowSizeMsg` 补上。
func newAppCtx(stages []data.StageRecord, zones []data.ZoneRecord) *appCtx {
	return &appCtx{
		stages:    stages,
		zones:     zones,
		chapters:  data.ListChapters(stages, zones),
		w:         90,
		h:         26,
		dataDir:   data.DataDBDir(),
		guidesDir: guidesDir(),
		mode:      "auto", //: 照 Python 的 `State.__init__`（缺省「允许程序补充」）
		//: 助战开关的初值：**不用**。上限跟着它走（口径 1：不用 12、用 13），
		//: 只有这一处给出初值，屏上读的是它。
		squadLimit: squadLimitOf(false),
	}
}

// resolveDataDir 把 `RIOS_DB` 指到放 sqlite 的那个目录。
//
// ★ 这里补的是**取数包的缺口，不是另立口径**：`data.DataDBDir()` 缺省返回
// 相对的 `data`，那是相对 **cwd** 的 —— 而发布形态是「双击 启动.cmd / exe」，
// cwd 未必等于 exe 所在目录。所以缺省先找「与 exe 同级」的 `data/`，
// 再退到 cwd 下的 `data/`；**两处都没有就具名失败**（缺件要说清缺什么、
// 怎么补，不许静默跑出一个空列表 —— 那与「这游戏没有关卡」长得一样）。
func resolveDataDir() error {
	if v := os.Getenv("RIOS_DB"); v != "" {
		return nil
	}
	tried := []string{}
	if exe, err := os.Executable(); err == nil {
		tried = append(tried, filepath.Join(filepath.Dir(exe), "data"))
	}
	tried = append(tried, "data")
	for _, c := range tried {
		if st, err := os.Stat(filepath.Join(c, "akdb.sqlite")); err == nil && !st.IsDir() {
			return os.Setenv("RIOS_DB", c)
		}
	}
	return fmt.Errorf("★ 找不到 akdb.sqlite，找过这两处：\n    %s\n"+
		"  它是**派生**库（数据源本身要另外取，见 docs/data-sources.md）：\n"+
		"    python -m ak_tactic db build        # 约 14 秒\n"+
		"  或显式指定：RIOS_DB=<放 sqlite 的目录>",
		strings.Join(tried, "\n    "))
}

func printChapters(stages []data.StageRecord, zones []data.ZoneRecord) {
	for i, c := range data.ListChapters(stages, zones) {
		fmt.Printf("%3d  %-10s %-22s %-14s 关数=%-4d 部=%d\n",
			i, c.Key, c.Title, c.Subtitle, c.Levels, len(c.Parts))
	}
}

func printEnvs(stages []data.StageRecord, zone string) {
	envs := data.ZoneEnvs(zone, stages)
	fmt.Printf("zone=%s 环境分层 %d 档，界面是否展示=%v\n", zone, len(envs), data.ZoneEnvsShown(envs))
	for _, e := range envs {
		fmt.Printf("  %-8s %-12s 关数=%d\n", e.Env, e.Label, e.Levels)
	}
}

func printStages(stages []data.StageRecord, zone, env string) {
	got := data.ListStages(stages, data.StageFilter{ZoneID: zone, Env: env})
	fmt.Printf("zone=%s env=%q ⇒ %d 关\n", zone, env, len(got))
	for _, s := range got {
		fmt.Printf("  %-18s %-10s %-12s %-10s %s\n", s.LevelID, s.Code, s.Difficulty, s.DiffGroup, s.Name)
	}
}
