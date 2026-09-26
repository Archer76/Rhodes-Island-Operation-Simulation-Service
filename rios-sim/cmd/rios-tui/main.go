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
		selftest  = flag.Bool("selftest", false, "无终端自检：逐层渲染并断言，退出码即判据")
		preflight = flag.Bool("preflight", false, "启动前自检：逐项查发布目录是否完整（启动.cmd 第一步就是它）")
		setup     = flag.Bool("setup", false, "首次运行准备：缺什么就自动补齐（装 Python 要你点头，其余全自动）")
		dumpCh    = flag.Bool("chapters", false, "打印章节表后退出")
		dumpEnv   = flag.String("envs", "", "打印该 zone 的环境分层后退出")
		dumpSt    = flag.String("stages", "", "打印该 zone 的关卡列表后退出（可配 -env 再筛）")
		env       = flag.String("env", "", "与 -stages 连用：按环境分层筛（EASY/NORMAL/TOUGH/ALL）")
	)
	flag.Parse()

	//: ★ 自检与首次运行准备都要跑在 `resolveDataDir` **之前**：新装好的树本来就没有
	//: sqlite（§12.5：data 不随包），先跑那个的话会在它们有机会动手之前就退出。
	//: `-setup` 尤其如此 —— 它的**全部工作**就是「缺的时候补上」，而那个函数报的正是「缺」。
	if *preflight {
		os.Exit(runPreflight())
	}
	if *setup {
		os.Exit(runSetup())
	}

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
	tried := dataDirCandidates()
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

// dataDirCandidates 给出「data 目录」的候选，按优先级：exe 同级的 `data/` →
// exe 同级 `eng/data/` → cwd 下的 `data/`。
//
// ★ 一处口径两处用：`resolveDataDir`（真正定下 RIOS_DB）与启动前自检
// （`preflight.go` 找 gamedata）必须看**同一批位置** —— 两处各写一遍，迟早会出现
// 「自检说数据在位、真跑起来说找不到」这种最难查的不一致。
//
// ★ 为什么要有 `eng/data`（发布树形态，2026-09-27 实测定下来的）：迁移图 §12.2 把
// 工程侧 Python 单放 `eng/`，而 Python 那边的数据根是**硬编码**的
// `Path(__file__).resolve().parents[2] / "data"`（`ak_tactic/db/build.py:40`、
// `ak_tactic/tui/data.py:239`）—— 在发布树里 `parents[2]` 正好是 `eng/`，所以
// Python 认的是 `eng/data/`。Go 侧若只认 `<发布根>/data/`，两边就会各看一个目录，
// 症状是「python -m ak_tactic db build 说建好了，界面说找不到库」。
// 认下 `eng/data` 之后两边指向同一处，且**双击 exe 不靠环境变量也能跑**。
func dataDirCandidates() []string {
	out := []string{}
	if exe, err := os.Executable(); err == nil {
		dir := filepath.Dir(exe)
		out = append(out, filepath.Join(dir, "data"), filepath.Join(dir, "eng", "data"))
	}
	return append(out, "data")
}

// findDataDir 找**存在的** data 目录（`RIOS_DB` 优先 → exe 同级 → exe 同级 eng/ → cwd），
// 找不到返回空串。
//
// ★ 为什么必须认 `RIOS_DB`：那是**显式指令**（判据与外部树都用它，取数子包与
// `resolveDataDir` 都认）。少了这一条就会出现「`RIOS_DB` 指着的库明明在、预检却说
// 没有数据 ⇒ 自动准备又会去建一份」这种自相矛盾 —— 与 `findEngineExe` 那条
// 「显式指定了却不认」是同一族错。
//
// 与 `resolveDataDir` 的差别：那个认「里面有 akdb.sqlite 的才算数」，这个只认目录在
// 不在 —— 启动前自检要分得清两种缺法，它们的提示**不一样**：
// 目录在而 `gamedata/` 缺 ⇒ 要**下载**；目录在而 sqlite 缺 ⇒ 要**构建**。
func findDataDir() (string, []string) {
	tried := dataDirCandidates()
	if v := os.Getenv("RIOS_DB"); v != "" {
		tried = append([]string{v}, tried...)
	}
	for _, c := range tried {
		if st, err := os.Stat(c); err == nil && st.IsDir() {
			return c, tried
		}
	}
	return "", tried
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
