package main

import (
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

// # 启动前自检（`-preflight`）
//
// 发布形态是**拆分目录**（迁移图 §12.2）：`rios-tui.exe` ／ `rios-sim.exe` ／ `eng/` ／
// `启动.cmd`；而 `data/` 与 Python 运行时**不随包**（§12.5）。拆分的代价是
// 「目录少一个文件就跑不起来」—— 单文件 exe 用体积换来的那点好处，拆开就得自己还
// （§12.3）。所以入口在起界面**之前**逐项检查。
//
// ## 两档，判据不同
//
//   - **致命**：引擎 exe、工程侧 Python 代码（`eng/`）。这两件是**安装器保证装上**的
//     （§12.5），缺了就是包坏了或被删了 ⇒ rc=2，且**不启动界面**。启动界面的坏处不是
//     "难看"，而是报错会晚一步、混在别的话里（§12.3 明说要防「跑一半才报」）。
//   - **待办**：Python 解释器、`data/gamedata/`、派生库。这三件是**玩家自己要做的事**
//     （§12.5 的三步引导）。缺了界面照样起得来（没有关卡时有那一屏空数据退路），
//     所以 rc 不变，但要把「下一步做什么」写在脸上。
//
// ## 两处必须照办的细节
//
//  1. **文档不随包**（§12.6）⇒ 这里给的指路**只能给 URL**，不能写 `docs/xxx.md`。
//     （开发树里那句「见 docs/data-sources.md」在玩家的机器上是死路。）
//  2. **`data/gamedata/` 不是派生的** —— 它只能**下载**，`rebuild_data.py` 建不出来。
//     这句话必须原样出现在提示里，否则玩家会去跑一条永远建不出它的命令（§12.5 那条
//     「必须纠正的说法」就是这么来的）。
const repoURL = "https://github.com/Archer76/Rhodes-Island-Operation-Simulation-Service"

// pfItem 是自检里的一项。
type pfItem struct {
	name   string
	ok     bool
	fatal  bool   // 安装包本该保证的（缺 ⇒ 包坏了）
	blocks bool   // 缺了界面**起不来**（缺 ⇒ 先做完玩家那几步）
	detail string // 实得（找到了什么 / 错在哪一行）
	fix    string // 缺了怎么办，具名（多行）
}

func runPreflight() int {
	items := preflightChecks()
	fatal, blocked, todo := 0, 0, 0
	fmt.Println("R.I.O.S. 启动前自检")
	fmt.Println(strings.Repeat("─", 64))
	for _, it := range items {
		mark := "  ✓   "
		switch {
		case it.ok:
		case it.fatal:
			mark = "  ★ 缺 "
			fatal++
		case it.blocks:
			mark = "  起不来 "
			blocked++
		default:
			mark = "  待办 "
			todo++
		}
		fmt.Printf("%s%s\n", mark, it.name)
		if it.detail != "" {
			for _, ln := range strings.Split(it.detail, "\n") {
				fmt.Printf("        %s\n", ln)
			}
		}
		if !it.ok && it.fix != "" {
			for _, ln := range strings.Split(it.fix, "\n") {
				fmt.Printf("        %s\n", ln)
			}
		}
	}
	fmt.Println(strings.Repeat("─", 64))

	switch {
	case fatal > 0:
		fmt.Printf("★ %d 件致命缺件：这套目录不完整，界面不启动。\n", fatal)
		fmt.Println("  这几件本来由安装器保证装上；若你是手动解压的，请重新装一次，")
		fmt.Printf("  或到 %s/releases 重新下载。\n", repoURL)
		return 2
	case blocked > 0:
		//: ★ 这一档存在的理由：缺派生库时 `main` 自己会在 `resolveDataDir` 那一步
		//: 退出（rc=3）。若不自检先拦，玩家看到的是先一屏自检、再一句找不到库 ——
		//: 两句都对，但没人告诉他"照上面做完再来"。自检的价值就在于把这句说出来。
		fmt.Printf("★ %d 件还没做，界面现在起不来。\n", blocked)
		printFirstRunSteps()
		return 3
	}
	if todo > 0 {
		fmt.Printf("%d 件待办（界面仍可启动，缺的那部分功能会具名报错）。\n", todo)
		printFirstRunSteps()
		return 0
	}
	fmt.Println("全项通过。")
	return 0
}

// printFirstRunSteps 是「首次运行三步引导」（§12.5）。
//
// ★ 这里印的是**四步**而不是标题里的"三步"：第四条（名册）是可选的，但缺了要让玩家
// 知道"为什么界面上没有名册"，否则「空名册」与「这个号没干员」长得一模一样。
func printFirstRunSteps() {
	fmt.Println()
	fmt.Println("首次运行要做的几件事（按顺序）：")
	fmt.Println("  1. 装 Python（若上面说没找到解释器）—— 到 https://www.python.org/downloads/ 自行下载")
	fmt.Println("     装完再跑一次本启动器；扫码登录还要 pip install qrcode。")
	fmt.Println("  2. 取游戏数据（data/gamedata/）—— 这一步**不能构建，只能下载**。")
	fmt.Printf("     说明与地址：%s/blob/main/docs/data-sources.md\n", repoURL)
	fmt.Println("     ★ 安装出来的目录里工程侧 Python 住在 eng/，它的根也是 eng/ ⇒ 数据")
	fmt.Println("       实际落在 eng/data/gamedata/（两侧认同一处，别分两处放）。")
	fmt.Println("  3. 建派生库 —— 数据到位后跑：python -m ak_tactic db build（约 14 秒）")
	fmt.Println("     或 python tools/rebuild_data.py（把派生数据一次建齐）。")
	fmt.Println("  4. （可选）森空岛名册 —— 不登也能用，编队那一步手动输名字。")
}

// preflightChecks 逐项查一遍。顺序按「缺了之后多严重」排，先报致命的。
func preflightChecks() []pfItem {
	items := []pfItem{}

	// ---- 1. 引擎 exe（致命）----
	// ★ 复用 `findEngineExe`，**自己不再写一套查找**：两处各写一遍迟早会漂，
	//    而漂的表现是「自检说在位、真跑起来说找不到」。
	epath, etried, eerr := findEngineExe()
	switch {
	case eerr != nil:
		//: 这里**不再补一句 fix** —— 那条错误文本本身已经把两个处置都写了
		//: （改对，或清掉让界面自己找），再补一句就是同一句话说两遍。
		items = append(items, pfItem{name: "引擎 rios-sim.exe", fatal: true,
			detail: eerr.Error()})
	case epath == "":
		items = append(items, pfItem{name: "引擎 rios-sim.exe", fatal: true,
			detail: "找过这些位置：\n" + strings.Join(dedupe(etried), "\n"),
			fix: "它应当与 rios-tui.exe 在**同一个目录**（安装器就是这么装的）。\n" +
				"手动摆放的话放回去，或用 RIOS_SIM_BIN=<绝对路径> 指定。"})
	default:
		items = append(items, pfItem{name: "引擎 rios-sim.exe", ok: true, detail: epath})
	}

	// ---- 2. 工程侧 Python 代码（致命）----
	script, btried := findBridgeScript()
	if script == "" {
		items = append(items, pfItem{name: "工程侧 Python（eng/）", fatal: true,
			detail: "找不到桥脚本。找过这些位置：\n" + strings.Join(dedupe(btried), "\n"),
			fix: "发布树里它在 eng/tools/rios_bridge.py，且 eng/ak_tactic/ 要在同级\n" +
				"（登录、名册、建库这三件事全走它）。\n" +
				"手动摆放的话放回去，或用 RIOS_BRIDGE=<绝对路径> 指定。"})
	} else {
		items = append(items, pfItem{name: "工程侧 Python（eng/）", ok: true, detail: script})
	}

	// ---- 3. Python 解释器 ＋ qrcode（待办）----
	py := interpreterName()
	pv, hasQR, perr := probePython(py)
	switch {
	case perr != nil:
		items = append(items, pfItem{name: "Python 解释器", detail: "试过 " + py + "：" + perr.Error(),
			fix: "到 https://www.python.org/downloads/ 下载安装（3.10 以上）。\n" +
				"装好后若仍找不到，用 RIOS_PYTHON=<python.exe 的绝对路径> 指定。\n" +
				"影响范围：登录、名册、建库不可用；界面其余部分照常。"})
	case !hasQR:
		items = append(items, pfItem{name: "Python 解释器", detail: "Python " + pv + "（qrcode 未安装）",
			fix: "pip install qrcode —— 只有**扫码登录**要用它（二维码由它编码）。\n" +
				"不装也能用：编队那一步手动输名字。"})
	default:
		items = append(items, pfItem{name: "Python 解释器", ok: true,
			detail: "Python " + pv + "（qrcode 已装）"})
	}

	// ---- 4. 桥握手（待办）：真起一次 ----
	// ★ 这一条**真起子进程**（不是 stat）。理由：它顺手证明了「解释器能跑、
	//    脚本能跑、ak_tactic 导得进来、协议答得回来」四件事，而 stat 只能证明文件在。
	//    报错文本由桥自己给（带上异常类名），所以缺哪个模块一看就知道。
	if perr == nil && script != "" {
		if bc, err := newBridgeClient(); err != nil {
			items = append(items, pfItem{name: "桥握手（登录／名册那条链）", detail: firstLineWith(err.Error(), "★")})
		} else if resp, err := bc.call("ping", 1, nil, 20*time.Second); err != nil {
			items = append(items, pfItem{name: "桥握手（登录／名册那条链）",
				detail: firstLineWith(err.Error(), "★"),
				fix: "上一次报的 python -c 能过、这一次过不了，多半是 ak_tactic 导不进来：\n" +
					"确认 eng/ak_tactic/ 与 eng/tools/rios_bridge.py 都在（桥把**脚本的上一层**当仓库根）。"})
		} else {
			items = append(items, pfItem{name: "桥握手（登录／名册那条链）", ok: true,
				detail: fmt.Sprintf("协议 %d，Python %s，凭据 %s", resp.Proto, resp.Python, credWord(resp.CredState))})
		}
	}

	// ---- 5. 游戏数据（待办）----
	ddir, dtried := findDataDir()
	gd := ""
	if ddir != "" {
		gd = filepath.Join(ddir, "gamedata", "_level_index.json")
	}
	if ddir == "" || !fileExists(gd) {
		items = append(items, pfItem{name: "游戏数据 data/gamedata/", detail: dataMissDetail(ddir, dtried, gd),
			fix: "它**不是派生数据**：rebuild_data.py 建不出它，**只能下载**（约 156 MB）。\n" +
				"地址与说明：" + repoURL + "/blob/main/docs/data-sources.md\n" +
				"放到 <本目录>/data/gamedata/。★ 安装出来的目录里文档与 Python 都在 eng/，\n" +
				"而 Python 侧的数据根同样是 eng/ ⇒ 实际位置是 eng/data/gamedata/。"})
	} else {
		items = append(items, pfItem{name: "游戏数据 data/gamedata/", ok: true, detail: gd})
	}

	// ---- 6. 派生库（待办）----
	db := ""
	if ddir != "" {
		db = filepath.Join(ddir, "akdb.sqlite")
	}
	if ddir == "" || !fileExists(db) {
		items = append(items, pfItem{name: "派生库 data/akdb.sqlite", blocks: true,
			detail: "没找到（干员库）",
			fix: "数据到位后跑：python -m ak_tactic db build（约 14 秒）\n" +
				"或 python tools/rebuild_data.py（把派生数据一次建齐）。\n" +
				"★ 前置是上一条：gamedata 没到位时这条建不出来。"})
	} else {
		items = append(items, pfItem{name: "派生库 data/akdb.sqlite", ok: true, detail: db})
	}

	return items
}

// interpreterName 是「用哪个解释器」：`RIOS_PYTHON` 优先，缺省 `python`。
//
// ★ 与 `newBridgeClient` 同一条口径（那边是真正跑起来用的那个）。两处都要改的时候
// 一起改 —— 自检说"有 Python"而桥说"找不到解释器"是最难查的那种不一致。
func interpreterName() string {
	if v := strings.TrimSpace(os.Getenv(envPython)); v != "" {
		return v
	}
	return "python"
}

// probePython 起一次解释器，问两件事：版本号，以及 qrcode 能不能导入。
//
// 用一条 `-c` 而不是两次，是为了少起一个进程（启动器每加一次进程启动，双击后
// 到界面出现就多一顿）。
func probePython(py string) (version string, hasQR bool, err error) {
	code := strings.Join([]string{
		"import sys, json",
		"try:",
		"    import qrcode",
		"    qr = True",
		"except Exception:",
		"    qr = False",
		"print(json.dumps({'v': sys.version.split()[0], 'qrcode': qr}))",
	}, "\n")
	out, err := exec.Command(py, "-c", code).Output()
	if err != nil {
		//: 起不来与"起来了但报错"要分开说：前者是没装，后者多半是 RIOS_PYTHON 指错了东西。
		if ee, ok := err.(*exec.ExitError); ok {
			tail := strings.TrimSpace(string(ee.Stderr))
			if tail != "" {
				return "", false, fmt.Errorf("这条命令没跑成：%s", firstNonEmptyLine(tail))
			}
		}
		return "", false, fmt.Errorf("起不来（%v）", err)
	}
	s := strings.TrimSpace(string(out))
	v, qr := parseProbeJSON(s)
	if v == "" {
		return "", false, fmt.Errorf("应答看不懂：%s", cut(s, 120))
	}
	return v, qr, nil
}

// parseProbeJSON 从探针那一行里抠出版本与 qrcode 两项。
//
// 不走 `encoding/json`：这一行是我们自己印的，形状固定，抠两个字段比解一整份结构
// 少一层「解不出来怎么办」的分支。
func parseProbeJSON(s string) (version string, qrcode bool) {
	for _, f := range strings.Split(strings.Trim(s, "{}"), ",") {
		kv := strings.SplitN(f, ":", 2)
		if len(kv) != 2 {
			continue
		}
		key := strings.Trim(strings.TrimSpace(kv[0]), `"`)
		val := strings.Trim(strings.TrimSpace(kv[1]), `"`)
		switch key {
		case "v":
			version = val
		case "qrcode":
			qrcode = val == "true"
		}
	}
	return version, qrcode
}

// dataMissDetail 把「找过哪里」如实列出来 —— 缺件要具名，不能只说一句没找到。
func dataMissDetail(ddir string, tried []string, gd string) string {
	if ddir != "" {
		return "在 " + ddir + " 里没找到 " + filepath.Base(gd)
	}
	return "连 data 目录都没有。找过这些位置：\n" + strings.Join(tried, "\n")
}

// credWord 把凭据三态翻成人话（与登录屏同一个口径）。
func credWord(s string) string {
	switch s {
	case "cred":
		return "已保存凭据"
	case "hgtoken":
		return "只有 hgToken（尚未铸成 cred）"
	default:
		return "本机没有森空岛凭据"
	}
}

func fileExists(p string) bool {
	if p == "" {
		return false
	}
	st, err := os.Stat(p)
	return err == nil && !st.IsDir()
}

// dedupe 去掉重复项、保持原顺序。
//
// ★ 为什么要它：查找路径是「先 exe 同级、再 cwd」各往上走若干层，exe 与 cwd 在同一棵
// 树上时两串会**重叠** ⇒ 缺件报告里同一个路径会出现两次。报告里出现重复路径不只是难看：
// 它会让人以为程序查了两遍（进而不信任"找过这些位置"这句话）。
func dedupe(in []string) []string {
	seen := map[string]bool{}
	out := make([]string, 0, len(in))
	for _, s := range in {
		if seen[s] {
			continue
		}
		seen[s] = true
		out = append(out, s)
	}
	return out
}

// firstNonEmptyLine 取第一行非空内容（探针的 stderr 尾部常带空行）。
func firstNonEmptyLine(s string) string {
	for _, ln := range strings.Split(s, "\n") {
		if t := strings.TrimSpace(ln); t != "" {
			return t
		}
	}
	return ""
}
