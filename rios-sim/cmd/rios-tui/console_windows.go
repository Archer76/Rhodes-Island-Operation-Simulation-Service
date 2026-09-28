//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"
	"strconv"
	"syscall"
	"unsafe"
)

// # 自己把控制台调成 UTF-8，并在需要时停住窗口
//
// 这两件事原先都落在 `启动.cmd` 里（`chcp 65001` 与 `pause`）。博士 2026-09-27 问
// 「为什么 release 包里是 cmd 文件、能不能改成 exe 直接调用用户默认终端」——
// 能，而且**根本不需要那个壳**：那三件事里有两件本来就该由程序自己做。
//
//   - `cd /d "%~dp0"` 已经不需要：路径解析三处全走 `os.Executable()`；
//   - 先 `-setup` 再起界面：`-setup` 是**同一个程序自己的参数**，无参数运行时自己跑即可；
//   - 剩下这两件（代码页、失败时别让窗口一闪就没）在这里补上。
//
// ★ 中文乱码的根因：中文 Windows 的控制台缺省代码页是 936（GBK），而本程序输出的是
// UTF-8 字节 ⇒ 不切代码页就满屏乱码。`chcp 65001` 干的就是这件事，等价。
//
// ⚠ `SetConsoleOutputCP` 改的是**当前控制台窗口**的状态：玩家自己开的那个窗口里
// 跑完之后会被留在 65001。所以退出前**恢复原值**（礼貌，也免得影响同一窗口里
// 之后的命令）。
const utf8CodePage = 65001

var (
	kernel32            = syscall.NewLazyDLL("kernel32.dll")
	procGetConsoleCP    = kernel32.NewProc("GetConsoleOutputCP")
	procSetConsoleCP    = kernel32.NewProc("SetConsoleOutputCP")
	consoleCPRestore    uintptr
	consoleCPNeedsReset bool

	procGetConsoleMode = kernel32.NewProc("GetConsoleMode")
	procSetConsoleMode = kernel32.NewProc("SetConsoleMode")
	//: 输出模式里开 VT：让 `\x1b[2K` / `\x1b[3A` 这类序列被**解释**，而不是当普通字符打出来。
	consoleModeRestore    uint32
	consoleModeNeedsReset bool
)

// : `ENABLE_VIRTUAL_TERMINAL_PROCESSING`（Windows 10+ 控制台输出模式位）。
const enableVirtualTerminalProcessing = 0x0004

// vtEnabled 记录"这个进程的输出句柄到底能不能解释 ANSI 序列"。
//
// ★ 2026-09-28 真机踩到（博士截图）：首次运行那段进度条跑在 bubbletea **之前**，
// 而"开 VT"这活一直是 bubbletea 进来时干的 ⇒ 在那之前 `\x1b[2K` 全是字面量
// （屏幕上看得见 `[2K`、`[3A`），"原地重画"根本没发生 ⇒ 进度条不动、还越堆越多。
// 这里自己开一次；开不了就记成 false，渲染侧退化成**不用转义序列**的追加式输出。
var vtEnabled bool

// setupConsole 把控制台输出代码页切成 UTF-8、并打开 VT 序列解释；原值都记下供退出还原。
// 拿不到控制台（重定向、判据里跑）时**什么都不做** —— 那不是错误。
func setupConsole() {
	old, _, _ := procGetConsoleCP.Call()
	if old != 0 && old != utf8CodePage {
		if ret, _, _ := procSetConsoleCP.Call(utf8CodePage); ret != 0 {
			consoleCPRestore, consoleCPNeedsReset = old, true
		}
	}
	enableVT()
}

// enableVT 给标准输出句柄打开 VT 处理。开了（或本来就有）算 true。
func enableVT() {
	handle, err := syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE)
	if err != nil {
		return
	}
	var mode uint32
	if ret, _, _ := procGetConsoleMode.Call(
		uintptr(handle), uintptr(unsafe.Pointer(&mode))); ret == 0 {
		return //: 不是真控制台（重定向/管道）⇒ 没有"解释序列"这回事
	}
	if mode&enableVirtualTerminalProcessing != 0 {
		vtEnabled = true
		return
	}
	if ret, _, _ := procSetConsoleMode.Call(
		uintptr(handle), uintptr(mode|enableVirtualTerminalProcessing)); ret != 0 {
		consoleModeRestore, consoleModeNeedsReset = mode, true
		vtEnabled = true
	}
}

// restoreConsole 把代码页与输出模式都还回去（只有真改过才还）。
func restoreConsole() {
	if consoleCPNeedsReset {
		_, _, _ = procSetConsoleCP.Call(consoleCPRestore)
		consoleCPNeedsReset = false
	}
	if consoleModeNeedsReset {
		if handle, err := syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE); err == nil {
			_, _, _ = procSetConsoleMode.Call(uintptr(handle), uintptr(consoleModeRestore))
		}
		consoleModeNeedsReset = false
	}
}

// stdinIsTerminal 判「这次是被双击／在真终端里跑」还是「被管道或重定向接走的」。
//
// ★ 为什么要这个判别式：双击启动的进程**窗口随进程关闭**，失败信息必须停住让人看；
// 而判据 / CI 里是管道接走的，停住就会把自动化挂死。两者要分开。
func stdinIsTerminal() bool {
	st, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return st.Mode()&os.ModeCharDevice != 0
}

// pauseIfInteractive 在真终端里等一个按键（附带一句为什么要等）。
func pauseIfInteractive(reason string) {
	if !stdinIsTerminal() {
		return
	}
	fmt.Println()
	if reason != "" {
		fmt.Println(reason)
	}
	fmt.Print("按回车键关闭本窗口……")
	_, _ = bufio.NewReader(os.Stdin).ReadString('\n')
}

// ---------------------------------------------------------------- 终端尺寸

var procGetConsoleScreenBufferInfo = kernel32.NewProc("GetConsoleScreenBufferInfo")

type consoleCoord struct{ x, y int16 }

type consoleSmallRect struct{ left, top, right, bottom int16 }

type consoleScreenBufferInfo struct {
	size              consoleCoord
	cursorPosition    consoleCoord
	attributes        uint16
	window            consoleSmallRect
	maximumWindowSize consoleCoord
}

// terminalWidth 取**可见窗口**的列数。
//
// ★ 为什么首次运行那段非要它不可（2026-09-28 真机踩到）：进度条是"打印 N 行、
// 下一帧 `\x1b[NA` 移回来原地重画"。**只要有一行超过终端宽度，终端就会折行**，
// 那一行占两个物理行，而上移仍按逻辑行数算 ⇒ 每帧往下漂一行，旧帧的残字留在屏上
// —— 几十帧之后满屏都是半截进度条。行宽必须按这里读到的列数夹住。
//
// 拿不到控制台（重定向、判据里跑）时退回 `COLUMNS`，再退回 80。
func terminalWidth() int {
	if handle, err := syscall.GetStdHandle(syscall.STD_OUTPUT_HANDLE); err == nil {
		var info consoleScreenBufferInfo
		ret, _, _ := procGetConsoleScreenBufferInfo.Call(
			uintptr(handle), uintptr(unsafe.Pointer(&info)))
		if ret != 0 {
			if w := int(info.window.right-info.window.left) + 1; w > 0 {
				return w
			}
		}
	}
	if v, err := strconv.Atoi(os.Getenv("COLUMNS")); err == nil && v > 0 {
		return v
	}
	return 80
}
