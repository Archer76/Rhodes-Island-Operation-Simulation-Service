//go:build !windows

package main

import (
	"bufio"
	"fmt"
	"os"
)

// 非 Windows 的对应物：**只为了让别的平台上 `go build` 不炸**，行为是空实现。
//
// 发布形态是 Windows（两个 exe 与安装器），这里不需要真做什么；
// 但本仓的判据与开发都在 Windows 上跑，所以这几行存在的意义是"别让跨平台构建断掉"，
// 顺带把「终端判别式」这份唯一实现留给两边共用（它是平台无关的）。
func setupConsole()   {}
func restoreConsole() {}

func stdinIsTerminal() bool {
	st, err := os.Stdin.Stat()
	if err != nil {
		return false
	}
	return st.Mode()&os.ModeCharDevice != 0
}

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
