//go:build windows

package main

import (
	"bufio"
	"fmt"
	"os"
	"syscall"
)

// # 自己把控制台调成 UTF-8，并在需要时停住窗口
//
// 这两件事原先都落在 `启动.cmd` 里（`chcp 65001` 与 `pause`）。博士 2026-09-27 问
// 「为什么 release 包里是 cmd 文件、能不能改成 exe 直接调用用户默认终端」——
// 能，而且**根本不需要启动器**：那三件事里有两件本来就该由程序自己做。
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
)

// setupConsole 把控制台输出代码页切成 UTF-8，并记下原值供退出时恢复。
// 拿不到控制台（重定向、判据里跑）时**什么都不做** —— 那不是错误。
func setupConsole() {
	old, _, _ := procGetConsoleCP.Call()
	if old == 0 || old == utf8CodePage {
		return
	}
	ret, _, _ := procSetConsoleCP.Call(utf8CodePage)
	if ret != 0 {
		consoleCPRestore, consoleCPNeedsReset = old, true
	}
}

// restoreConsole 把代码页还回去（只有真改过才还）。
func restoreConsole() {
	if consoleCPNeedsReset {
		_, _, _ = procSetConsoleCP.Call(consoleCPRestore)
		consoleCPNeedsReset = false
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
