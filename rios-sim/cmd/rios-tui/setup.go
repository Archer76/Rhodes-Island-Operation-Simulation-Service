package main

import (
	"bufio"
	"errors"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

// # 首次运行准备（`-setup`）：把「装完 Python 之后的事」一次做完
//
// 发布裁定里 `data/` 与 Python 运行时不随包，于是玩家装完安装包还要自己走几步。
// 这个命令把**除 Python 本身以外**的每一步都自动做掉：
//
//	① 解释器       缺 ⇒ 给下载链接，并**问一句**要不要代跑 winget 装上（博士 2026-09-27 裁：
//	                      给链接 ＋ 确认后可以代装）
//	② 游戏数据     缺 ⇒ 交给 `tools/rebuild_data.py`（它自己按离线／联网把该取的都取了，
//	                      含引擎要的 `_level_index.json` 缓存）
//	③ 派生库       缺 ⇒ 同一条命令建出来
//	④ 复检         做完再跑一遍预检，通过了才返回 0（调用方接着起界面）
//
// ## 三条纪律
//
//  1. **不重复实现数据逻辑**：②③ 一律走 `rebuild_data.py`，Go 侧只负责「什么时候跑、跑哪个、
//     失败了怎么说」。本仓的口径是「同一件事只许有一份实现」，而那份实现在 Python 侧
//     （建库／抓取是保留在 Python 的工程侧工作，见迁移图 §11.2）。
//  2. **子进程的输出实时透传**：下 94 MB 数据不是一瞬间的事，不能等它跑完再一次性打印
//     （那与卡死长得一样）。所以 Stdout/Stderr 直接接给终端，不走 capture。
//  3. **无人在场也不挂住**：那条 y/n 问句读 stdin；读不到（EOF，例如从 NUL 启动或无人值守）
//     就按「不代装」处理 —— 安全的那一侧。
//
// ★ 静默的常规路径：什么都不缺时**一个字节都不打印**、立刻返回 0。入口每次都会调它，
// 所以这条路径必须是哑的（否则每次启动都刷一屏）。

// : winget 里 Python 的候选 id，**从新到旧**试。写死一个版本号迟早会过期，写一串则能撑一段；
// : 哪一个都不认时给下载页链接，让人自己装（这条退路永远可用）。
var wingetPythonIDs = []string{
	"Python.Python.3.14",
	"Python.Python.3.13",
	"Python.Python.3.12",
}

// : 官方下载页。**不代装**那条路也走它。
const pythonURL = "https://www.python.org/downloads/"

// pythonTestedMin 是**实测过**的最低版本，按它判「太旧」。
//
// 2026-09-27 的两条读数（不是「应当能跑」那种自述）：
//
//	· 3.11.9 实测：`compileall ak_tactic tools` 全包通过、`python -m ak_tactic db info` rc=0；
//	· AST 扫全仓 298 个 .py：**3.11／3.12 独占特性各 0 处**（`match`／`except*`／
//	  `tomllib`／`StrEnum`／`Self`／`TaskGroup`／`zip(strict=)`／`bit_count`／`pairwise`
//	  逐个查过；粗扫报出来的两处「运行期联合类型」与一处 `strict=` 复核后是集合运算与
//	  领域参数，不是版本要求），且 280/298 个文件带 `from __future__ import annotations`
//	  ⇒ 注解里的 `X | Y` 不构成版本要求。
//
// ⇒ 判据取**保守**的一侧：**只把实测过的 3.11 当作「确定能跑」**，低于它给一条具名提示
// 而**不拦**（3.10 很可能也行，但我没有那个解释器实测 —— 未核就不许说成「支持」）。
const (
	pythonTestedMinMajor = 3
	pythonTestedMinMinor = 11
)

// parsePyVersion 把 `3.11.9` 这类版本串拆成主次版本号。
func parsePyVersion(v string) (int, int, bool) {
	digits := func(s string) (int, bool) {
		t := strings.TrimFunc(s, func(r rune) bool { return r < '0' || r > '9' })
		if t == "" {
			return 0, false
		}
		n, err := strconv.Atoi(t)
		return n, err == nil
	}
	parts := strings.Split(strings.TrimSpace(v), ".")
	if len(parts) < 2 {
		return 0, 0, false
	}
	maj, ok1 := digits(parts[0])
	min, ok2 := digits(parts[1])
	if !ok1 || !ok2 {
		return 0, 0, false
	}
	return maj, min, true
}

// pythonTooOld 判「比实测过的还旧」。**解析不出来时返回 false** —— 不拿猜的东西当判据。
func pythonTooOld(version string) bool {
	maj, min, ok := parsePyVersion(version)
	if !ok {
		return false
	}
	if maj != pythonTestedMinMajor {
		return maj < pythonTestedMinMajor
	}
	return min < pythonTestedMinMinor
}

// setupStep 是准备计划里的一步。
type setupStep struct {
	key  string // python / data / derived
	what string // 给人看的一句话
	why  string // 缺的是什么（具名）
}

// setupPlanFrom 是**纯函数**：给定三项的在位情况，给出这次要做什么。
//
// 单独抽出来是为了能被判据直接喂四种组合走一遍 —— 真跑一遍 `-setup` 会下载 94 MB，
// 那是「长等待」，不该塞进无终端自检里。
// `pythonOld` 单独一项而不是并进 `pythonOK`：**「没有」与「太旧」是两回事** ——
// 前者非装不可，后者只是「很可能跑得动、但没实测过」。混成一个布尔，提示就只能说一句
// 含糊话；而本仓的口径是缺件要具名到「缺什么、怎么办」。
func setupPlanFrom(pythonOK, pythonOld, dataOK, derivedOK bool) []setupStep {
	out := []setupStep{}
	switch {
	case !pythonOK:
		out = append(out, setupStep{key: "python", what: "装 Python 解释器",
			why: "没找到可用的解释器（登录、名册、建库三条路都靠它）"})
	case pythonOld:
		out = append(out, setupStep{key: "python", what: "换一个新一点的 Python",
			why: fmt.Sprintf("本机版本低于实测过的 %d.%d（实测跑通的是 3.11 与 3.14）",
				pythonTestedMinMajor, pythonTestedMinMinor)})
	}
	if !dataOK {
		out = append(out, setupStep{key: "data", what: "取游戏数据（关卡／敌人／干员表）",
			why: "没找到 data/gamedata/_level_index.json"})
	}
	if !derivedOK {
		out = append(out, setupStep{key: "derived", what: "建派生库（干员库／敌人库／范围索引）",
			why: "没找到 data/akdb.sqlite"})
	}
	return out
}

// setupPlan 读真实环境，给出这次要做什么。
func setupPlan() []setupStep {
	py, ver := probeInterpreter()
	ddir, _ := findDataDir()
	dataOK := ddir != "" && fileExists(filepath.Join(ddir, "gamedata", "_level_index.json"))
	derivedOK := ddir != "" && fileExists(filepath.Join(ddir, "akdb.sqlite"))
	return setupPlanFrom(py != "", py != "" && pythonTooOld(ver), dataOK, derivedOK)
}

// probeInterpreter 探一次解释器：能用就返回它的路径（或名字）与版本号，否则都空。
func probeInterpreter() (string, string) {
	py := interpreterName()
	if ver, _, err := probePython(py); err == nil {
		return py, ver
	}
	return "", ""
}

// engRoot 给出「工程侧 Python 的根」：`tools/` 的上一层。
//
// 开发树里它是仓库根，发布树里它是 `eng/`（迁移图 §12.2）—— 靠**桥脚本的位置**推出来，
// 而不是各写一套判断（那两套迟早会漂）。
func engRoot() string {
	if script, _ := findBridgeScript(); script != "" {
		return filepath.Dir(filepath.Dir(script))
	}
	return ""
}

// rebuildScript 是那条「把数据与派生库一次做齐」的命令。
func rebuildScript() string {
	root := engRoot()
	if root == "" {
		return ""
	}
	return filepath.Join(root, "tools", "rebuild_data.py")
}

// runSetup 是 `-setup` 的入口。返回码即判据：0 = 可以起界面。
func runSetup() int {
	plan := setupPlan()

	//: ★ 常规路径：什么都不缺 ⇒ 立刻返回、不打印（入口每次都会调它）。
	if len(plan) == 0 {
		return 0
	}

	fmt.Println("R.I.O.S. 首次运行准备")
	fmt.Println(strings.Repeat("─", 64))
	fmt.Println("按当前状态，需要做这几件：")
	for i, st := range plan {
		fmt.Printf("  %d. %s\n     （%s）\n", i+1, st.what, st.why)
	}
	fmt.Println(strings.Repeat("─", 64))
	fmt.Println("这几步由本程序自动完成；只有 Python 要你点头（也可以自己去装）。")
	fmt.Println()

	py, ver := probeInterpreter()
	//: 「太旧」也走代装那条路（装上一个新的就盖过旧的），但它**不拦** —— 见 pythonTooOld。
	if py == "" || pythonTooOld(ver) {
		if got := offerPythonInstall(ver); got != "" {
			py = got
		}
	}
	needData := false
	for _, st := range plan {
		if st.key == "data" || st.key == "derived" {
			needData = true
		}
	}
	if needData {
		if py == "" {
			fmt.Println("★ 没有可用的 Python ⇒ 数据与派生库都建不出来。")
			fmt.Printf("  装好之后（%s）再双击一次 rios-tui.exe 即可。\n", pythonURL)
			return 3
		}
		if rc := runRebuildData(py); rc != 0 {
			return rc
		}
	}

	//: 复检：做完再问一遍「现在能不能起」。
	left := setupPlan()
	if len(left) == 0 {
		fmt.Println()
		fmt.Println("准备完成，接着启动界面。")
		return 0
	}
	//: 只剩 Python 这一项、而数据齐了 ⇒ 界面照常能起（登录／名册受限，界面自己会具名）。
	onlyPython := true
	for _, st := range left {
		if st.key != "python" {
			onlyPython = false
		}
	}
	if onlyPython {
		fmt.Println()
		fmt.Println("★ 还差 Python（登录／名册不可用），界面其余部分照常。")
		return 0
	}
	fmt.Println()
	fmt.Println("★ 还有没做完的：")
	for _, st := range left {
		fmt.Printf("  · %s（%s）\n", st.what, st.why)
	}
	return 3
}

// offerPythonInstall 走博士 2026-09-27 裁的那条路：**给链接 ＋ 问一句要不要代装**。
//
// `cur` 是现有解释器的版本（空串 = 没找到）。带上它是为了把话说准：**「没有」与「太旧」
// 是两句话** —— 对后者说「没找到 Python」是错话，而玩家会照着错话去查一个根本不缺的东西。
func offerPythonInstall(cur string) string {
	if cur == "" {
		fmt.Printf("没找到 Python 解释器（%s 起不来）。两种办法：\n", interpreterName())
	} else {
		fmt.Printf("本机 Python 是 %s，低于**实测过**的 %d.%d（实测跑通的是 3.11 与 3.14）。\n",
			cur, pythonTestedMinMajor, pythonTestedMinMinor)
		fmt.Println("它很可能也能跑；但既然要装，建议直接装个新的。两种办法：")
	}
	fmt.Printf("  · 你自己装：%s\n", pythonURL)
	fmt.Println("  · 或者我来装：用 winget 装官方包（约 30 MB，装到你的用户目录，不需要管理员）")
	fmt.Print("回车 = 我自己装；输入 y 再回车 = 你替我装： ")
	line, _ := bufio.NewReader(os.Stdin).ReadString('\n')
	ans := strings.ToLower(strings.TrimSpace(line))
	if ans != "y" && ans != "yes" {
		fmt.Println("（好的，那这一步留给你。）")
		return ""
	}
	//: 候选 id 从新到旧试；winget 自己会说哪个 id 不认。
	for _, id := range wingetPythonIDs {
		fmt.Printf("\n$ winget install --id %s -e\n", id)
		rc := runStreaming("winget", []string{
			"install", "--id", id, "-e",
			"--accept-package-agreements", "--accept-source-agreements",
			"--disable-interactivity",
		}, "")
		if rc != 0 {
			fmt.Printf("（%s 没装成，换下一个候选。）\n", id)
			continue
		}
		//: 装完 PATH **未必**在本进程里刷新 ⇒ 直接去标准位置找它，找到就当场接着用，
		//: 免得玩家还得多开一次终端。
		if found := findFreshPython(); found != "" {
			_ = os.Setenv(envPython, found)
			fmt.Printf("已装好，本次就用它：%s\n", found)
			return found
		}
		fmt.Println("装好了，但本次进程还没看到它（PATH 要刷新）—— 关掉窗口再双击一次 rios-tui.exe。")
		return ""
	}
	fmt.Printf("（winget 没装成；请自行安装：%s）\n", pythonURL)
	return ""
}

// findFreshPython 在标准安装位置找刚装上的 python.exe（PATH 没刷新时的兜底）。
func findFreshPython() string {
	pats := []string{}
	if la := os.Getenv("LOCALAPPDATA"); la != "" {
		pats = append(pats, filepath.Join(la, "Programs", "Python", "Python3*", "python.exe"))
	}
	pats = append(pats,
		filepath.Join("C:", "Python3*", "python.exe"),
		filepath.Join("C:", "Program Files", "Python3*", "python.exe"))
	hits := []string{}
	for _, pat := range pats {
		if got, err := filepath.Glob(pat); err == nil {
			hits = append(hits, got...)
		}
	}
	if len(hits) == 0 {
		return ""
	}
	//: 版本号大的优先（Python3.14 > Python3.9，按目录名字符串比就够用）
	sort.Sort(sort.Reverse(sort.StringSlice(hits)))
	return hits[0]
}

// shouldAutoSetup 判「这次该不该先跑一遍首次运行准备」。
//
// 判据两条，都是**必要**的：
//
//	· `nflag == 0` —— 玩家双击进来的那条路（无参数）。任何显式开关（`-selftest`、
//	  `-preflight`、`-dump*`…）都不走它，免得判据与排障被"顺手下载几十 MB"污染。
//	· 计划非空 —— 什么都不缺时 `runSetup` 本来就是哑的，这条只是让调用点读起来清楚。
//
// 单独抽成纯函数是为了能被判据直接喂两格走一遍：真跑一遍会去下载（长等待），
// 不该塞进无终端自检。
func shouldAutoSetup(nflag int, plan []setupStep) bool {
	return nflag == 0 && len(plan) > 0
}

// playerSteps 是**玩家真正需要的**那几步（`rebuild_data.py --only` 的 key，精确匹配）。
//
// ★ 为什么不是整跑（博士 2026-09-27 问「为什么 release 包还会拉 wiki 的干员正文和备注」）：
// 实测「谁在读这些产物」——Go 运行时与 `ak_tactic` 的**产品路径**里，
// `prts-notes.sqlite`（wiki 干员备注）与 `op-briefs.txt`（备注语料展平）**零命中**，
// `ranges.json` 也只被 prts 抓取器自己读。它们只在**判据与开发审计**里用
// （`check_data_ready.py`／`audit_op_notes.py`／`fetch_prts_notes.py`）。
//
// 而这三步是硬依赖：
//
//	· `akdb.sqlite`    —— 界面取关卡表、干员库（`rios-sim/data`）都读它；
//	· `stage 表`       —— 关卡索引，顺带产出引擎要的 `gamedata/_level_index.json` 缓存；
//	· `enemydb.sqlite` —— 引擎的 `refraction.go` 在读（敌人抗性那一族）。
//
// ★ 2026-09-27 博士裁：**关卡数据随用随取** —— 「关卡文件」那一步**从这份清单里去掉了**
// （它本来会一次下 1765 个文件、98 MB、5～25 分钟）。改成玩家选定某一关时，由
// `onStagePicked` 调桥的 `ensure_level` 取那**一个**文件（约 60 KB）。
// ⇒ 首次运行只剩下面三步；想一次取齐的人仍旧可以跑 `cache --fetch-levels`。
//
// ⇒ 整跑会让玩家白等两段联网抓取（prts 备注与范围页），还顺带把
// `fetch_prts_notes.py` 拖进安装包 —— 那两件都该只留在开发侧。
// ★ 2026-09-28 补第一步「gamedata 源表」：离线建干员库要 8 张 excel 源表
// （`excel/character_table.json` 等），而"随用随取"只覆盖关卡文件 —— 这批源表
// **原先没有任何取数步骤**，全新机器上首启必然挂在第一步（报错还把玩家指去
// GitHub 手动下载）。现在它是正经的一步：联网取、可续跑、带百分比与速度。
var playerSteps = []string{"gamedata 源表", "akdb.sqlite", "stage 表", "enemydb.sqlite"}

// runCheckUpdates 只查一次更新并打印读数，**不动手**（`-check-updates`）。
//
// 这一条是给排障与发布前核对用的：它把「本地记的是哪一版、上游是哪一版、
// 该不该动手」原样摆出来，而 `maybeAutoUpdate` 是它的自动版（查完就做）。
func runCheckUpdates() int {
	info, err := checkUpdates()
	if err != nil {
		fmt.Printf("★ 查更新失败：%s\n", err)
		return 3
	}
	pl, lt := info.PackLocal, info.PackLatest
	if pl == "" {
		pl = "（没装）"
	}
	if lt == "" {
		lt = "（没查到）"
	}
	fmt.Println("== 上游游戏数据 ==")
	fmt.Printf("  本地（我们库里记的）：%s\n", lastLineOf(info.DataLocal))
	fmt.Printf("  上游（现读）        ：%s\n", lastLineOf(info.DataRemote))
	fmt.Printf("  结论：%s\n", info.Note)
	fmt.Println("== 数据包 ==")
	fmt.Printf("  已装：%s｜最新：%s\n", pl, lt)
	if info.PackUpdate {
		fmt.Println("  结论：有新版")
	} else {
		fmt.Println("  结论：无更新或未核")
	}
	if acts := updateActions(info); len(acts) == 0 {
		fmt.Println("⇒ 不需要更新。")
	} else {
		fmt.Printf("⇒ 该做：%s（打开工具时会自动做）\n", strings.Join(acts, "、"))
	}
	return 0
}

// lastLineOf 取多行版本串的最后一行（`data_version.txt` 的第三行才是版本号）。
func lastLineOf(s string) string {
	s = strings.TrimSpace(s)
	if s == "" {
		return "（未记）"
	}
	lines := strings.Split(s, "\n")
	return strings.TrimSpace(lines[len(lines)-1])
}

// maybeAutoUpdate 在**打开工具时**自动请求一次数据文件（博士 2026-09-27 要求）：
// 「让用户打开本工具的时候程序自动请求数据文件」。
//
// 三件性质：
//   - **便宜**：两条很小的请求（上游版本戳几百字节 ＋ 一次 releases API）；
//   - **不误报**：查不到（离线、被墙）就**静默跳过**，绝不把"没问到"说成"有新版本"；
//   - **不动手就没损失**：真要更新时走的是既有的那两条流程（重建 / 拉数据包），
//     它们本来就"只加不删、缺件具名、每项任务一条进度条"。
func maybeAutoUpdate() int {
	info, err := checkUpdates()
	if err != nil || info == nil || !info.Checked {
		return 0 //: 查不到当无事发生；不打印、不拦路
	}
	acts := updateActions(info)
	if len(acts) == 0 {
		return 0
	}
	fmt.Println()
	fmt.Println("检测到有更新，自动处理（本程序打开时会自己查一次）：")
	if info.DataUpdate {
		fmt.Printf("  · 游戏数据：%s → %s\n",
			lastLineOf(info.DataLocal), lastLineOf(info.DataRemote))
	}
	if info.PackUpdate {
		fmt.Printf("  · 数据包：%s → %s\n", info.PackLocal, info.PackLatest)
	}
	for _, a := range acts {
		switch a {
		case "rebuild":
			py, _ := probeInterpreter()
			if py == "" {
				fmt.Printf("★ 要重建数据但没有可用的 Python（%s）—— 这一步做不了。\n", pythonURL)
				return 3
			}
			if rc := runRebuildData(py); rc != 0 {
				return rc
			}
		case "pack":
			if rc := runDatapackFetch(); rc != 0 {
				return rc
			}
		}
	}
	fmt.Println("更新完成。")
	return 0
}

// runDatapackFetch 从数据仓拉最新数据包并装入（`datapack --fetch-latest`）。
func runDatapackFetch() int {
	script := rebuildScript()
	if script == "" {
		fmt.Println("★ 找不到工程侧脚本（tools/rebuild_data.py）—— 发布树里它在 eng/tools/ 下。")
		return 3
	}
	root := filepath.Dir(filepath.Dir(script))
	py, _ := probeInterpreter()
	if py == "" {
		fmt.Printf("★ 没有可用的 Python（%s）⇒ 数据包这一步做不了。\n", pythonURL)
		return 3
	}
	fmt.Println("  拉数据包（我们的公开数据仓，约 2.5 MB）：")
	rc := runStreaming(py, []string{"-m", "ak_tactic", "datapack", "--fetch-latest"}, root)
	if rc != 0 {
		fmt.Printf("★ 数据包没更新成（退出码 %d）—— 游戏数据那部分不受影响。\n", rc)
		return 3
	}
	return 0
}

// runInstallDatapack 装入数据包（`-install-datapack <zip|目录>`）。
//
// ★ 这个包是**可选**的：它只装 prts.wiki 与 theresa.wiki 那两块派生数据
// （许可是 CC BY-NC-SA 4.0，见仓里的 THIRD-PARTY.md）。装上就不必再去抓那两站。
// 游戏本体数据**不在包里**（那部分不可再分发），照样要自己取。
//
// 走的就是 Python 那条命令（校验逻辑只有一份，在 `ak_tactic/datapack.py` 里：
// 先验包内五份许可/来源文件齐不齐、有没有夹带本体数据，缺一件就拒装）。
func runInstallDatapack(pack string) int {
	if _, err := os.Stat(pack); err != nil {
		fmt.Printf("★ 找不到数据包：%s\n", pack)
		return 3
	}
	script := rebuildScript()
	if script == "" {
		fmt.Println("★ 找不到工程侧脚本（tools/rebuild_data.py）—— 发布树里它在 eng/tools/ 下。")
		return 3
	}
	root := filepath.Dir(filepath.Dir(script))
	py, ver := probeInterpreter()
	if py == "" {
		fmt.Printf("★ 没有可用的 Python（%s）⇒ 这一步做不了。\n", pythonURL)
		return 3
	}
	_ = ver
	fmt.Println("装入数据包（会先校验包内许可与来源文件，并拒绝含游戏本体数据的包）：")
	fmt.Printf("  $ %s -m ak_tactic datapack --install \"%s\"\n", py, pack)
	fmt.Println()
	rc := runStreaming(py, []string{"-m", "ak_tactic", "datapack",
		"--install", pack}, root)
	if rc != 0 {
		fmt.Println()
		fmt.Printf("★ 没装成（退出码 %d）。上面的输出写了是哪一条不满足。\n", rc)
		return 3
	}
	fmt.Println()
	fmt.Println("装好了。注意：游戏本体数据（关卡地图／敌人数值／源表）不在这个包里，")
	fmt.Println("      那部分仍要自己取 —— 直接双击 rios-tui.exe，缺什么它会自己补。")
	return 0
}

// runRebuildData 跑那条「把数据与派生库一次做齐」的命令。
//
// ★ 2026-09-27 改：**每项任务一条进度条**（博士要求：「初次运行时的下载不用逐条
// 给出在下载什么东西，每项任务渲染一个进度条就行了」）。做法是
// `--progress-file` ＋ `--quiet`：子进程把进度写成 JSONL 到文件、把各步的原话
// 改写成日志文件；这边按偏移量增量读那个文件、原地重画进度条。
// 失败时那一步的 msg 里已经带着日志尾部（Python 侧拼好的），照旧具名。
func runRebuildData(py string) int {
	script := rebuildScript()
	if script == "" {
		fmt.Println("★ 找不到工程侧脚本（tools/rebuild_data.py）—— 发布树里它在 eng/tools/ 下。")
		fmt.Println("  这一步没它做不了；请确认安装完整，或手动跑：python tools/rebuild_data.py")
		return 3
	}
	root := filepath.Dir(filepath.Dir(script))
	only := strings.Join(playerSteps, ",")
	pf := filepath.Join(os.TempDir(), fmt.Sprintf("rios-progress-%d.jsonl", os.Getpid()))
	defer func() { _ = os.Remove(pf) }()

	fmt.Println()
	fmt.Printf("开始取数据与建库（%d 步，每步一条进度条）：\n", len(playerSteps))
	fmt.Println("  （只跑玩家真正需要的几步：游戏源表／干员库／关卡索引／敌人库；")
	fmt.Println("   关卡地图**随用随取** —— 玩到哪一关才下那一关的那一个文件；")
	fmt.Println("   wiki 备注语料与范围索引只有判据与开发工具用得上，不在这里拉）")
	fmt.Println("  （中途可以 Ctrl+C 停，停了下次双击会接着做）")
	fmt.Println()

	err := waitWithBars(func(progressFile string) error {
		c := exec.Command(py, script, "--only", only,
			"--progress-file", progressFile, "--quiet")
		c.Dir = root
		//: **继承 stdio，不抓管道**（本机沙箱下抓管道会 EPERM；见 progress.go 的文件头）
		c.Stdin, c.Stdout, c.Stderr = os.Stdin, os.Stdout, os.Stderr
		return c.Run()
	}, pf)

	rc := 0
	if err != nil {
		rc = 1
		var ee *exec.ExitError
		if errors.As(err, &ee) {
			rc = ee.ExitCode()
		}
	}
	if rc != 0 {
		fmt.Println()
		fmt.Printf("★ 这一步没跑成（退出码 %d）。\n", rc)
		fmt.Println("  手动重试（原样输出，能看到每一步的细节）：")
		fmt.Printf("    cd /d \"%s\"\n", root)
		fmt.Printf("    %s tools\\rebuild_data.py --only %s\n", py, only)
		fmt.Println("  它的输出里会写明是哪一步、缺什么（本仓的规矩是缺件具名）。")
		return 3
	}
	return 0
}

// runStreaming 起一个子进程，把它的三路 stdio **直接接给当前终端**。
//
// ★ 与 `engclient.go` 那套 capture 的区别：那边要的是应答（一行 JSON），这边要的是
// 「让人看着它跑」。capture 之后一次性打印，与卡死长得一模一样。
func runStreaming(exe string, args []string, dir string) int {
	cmd := exec.Command(exe, args...)
	if dir != "" {
		cmd.Dir = dir
	}
	//: 环境**一处拼装**（`pythonEnv`）：UTF-8 两项防编码崩，`PYTHONDONTWRITEBYTECODE`
	//: 防它往 eng/ 里写 __pycache__ —— 那一项原先由 `启动.cmd` 设，现在搬进了 Go（§12.9）。
	cmd.Env = pythonEnv()
	cmd.Stdout, cmd.Stderr, cmd.Stdin = os.Stdout, os.Stderr, os.Stdin
	if err := cmd.Start(); err != nil {
		fmt.Printf("★ 起不来：%v\n", err)
		return 1
	}
	//: 给一个宽到不会误杀的上限：下载与建库是分钟级的。
	done := make(chan error, 1)
	go func() { done <- cmd.Wait() }()
	select {
	case err := <-done:
		if err != nil {
			if ee, ok := err.(*exec.ExitError); ok {
				return ee.ExitCode()
			}
			return 1
		}
		return 0
	case <-time.After(2 * time.Hour):
		_ = cmd.Process.Kill()
		fmt.Println("★ 超过 2 小时仍未结束，已中止。")
		return 1
	}
}
