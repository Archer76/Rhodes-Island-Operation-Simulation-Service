package main

import (
	"bufio"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
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
// ★ 静默的常规路径：什么都不缺时**一个字节都不打印**、立刻返回 0。启动器每次都会调它，
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
func setupPlanFrom(pythonOK, dataOK, derivedOK bool) []setupStep {
	out := []setupStep{}
	if !pythonOK {
		out = append(out, setupStep{key: "python", what: "装 Python 解释器",
			why: "没找到可用的解释器（登录、名册、建库三条路都靠它）"})
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
	py := probeInterpreter()
	ddir, _ := findDataDir()
	dataOK := ddir != "" && fileExists(filepath.Join(ddir, "gamedata", "_level_index.json"))
	derivedOK := ddir != "" && fileExists(filepath.Join(ddir, "akdb.sqlite"))
	return setupPlanFrom(py != "", dataOK, derivedOK)
}

// probeInterpreter 探一次解释器：能用就返回它的路径（或名字），否则空串。
func probeInterpreter() string {
	py := interpreterName()
	if _, _, err := probePython(py); err == nil {
		return py
	}
	return ""
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

	//: ★ 常规路径：什么都不缺 ⇒ 立刻返回、不打印（启动器每次都会调它）。
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

	py := probeInterpreter()
	if py == "" {
		py = offerPythonInstall()
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
			fmt.Printf("  装好之后（%s）再双击一次本启动器即可。\n", pythonURL)
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
func offerPythonInstall() string {
	fmt.Printf("没找到 Python 解释器（%s 起不来）。两种办法：\n", interpreterName())
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
		fmt.Println("装好了，但本次进程还没看到它（PATH 要刷新）—— 关掉窗口再双击一次启动器。")
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

// runRebuildData 跑那条「把数据与派生库一次做齐」的命令，**输出实时透传**。
func runRebuildData(py string) int {
	script := rebuildScript()
	if script == "" {
		fmt.Println("★ 找不到工程侧脚本（tools/rebuild_data.py）—— 发布树里它在 eng/tools/ 下。")
		fmt.Println("  这一步没它做不了；请确认安装完整，或手动跑：python tools/rebuild_data.py")
		return 3
	}
	root := filepath.Dir(filepath.Dir(script))
	fmt.Println()
	fmt.Printf("开始取数据与建库（这一步要下载，可能要几分钟到十几分钟）：\n")
	fmt.Printf("  $ %s %s\n", py, script)
	fmt.Println("  （输出直接打在这里；中途可以 Ctrl+C 停，停了下次双击会接着做）")
	fmt.Println()
	rc := runStreaming(py, []string{script}, root)
	if rc != 0 {
		fmt.Println()
		fmt.Printf("★ 这一步没跑成（退出码 %d）。\n", rc)
		fmt.Println("  手动重试：")
		fmt.Printf("    cd /d \"%s\"\n", root)
		fmt.Printf("    %s tools\\rebuild_data.py\n", py)
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
	//: 中文 Windows 缺省 GBK：不钉 UTF-8 的话，子进程一遇中文就编码崩（本仓踩过）。
	cmd.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONUTF8=1")
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
