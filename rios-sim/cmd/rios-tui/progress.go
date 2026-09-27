package main

// progress.go：首次运行准备的**进度条渲染器**（2026-09-27 博士要求）。
//
// 博士原话：「初次运行时的下载不用逐条给出在下载什么东西，每项任务渲染一个进度条就行了」。
//
// ## 数据从哪来
//
// 从**文件**，不是从管道。这一条是被本仓一条硬约束逼出来的：本机沙箱下用管道抓
// 子进程输出会 **EPERM**（`tools/rebuild_data.py` 的 `_run_step` 里记着同一条）。
// 所以子进程把进度按 JSONL **append 到文件**，父进程按偏移量**增量读**、原地重画。
// 子进程自己的散文输出则被改写成日志文件（失败时把日志尾部打出来，诊断不丢）。
//
// ## 事件形状（与 `tools/rebuild_data.py` 的 `Progress` 类一一对应）
//
//	{"ev":"plan","steps":[{"key":…,"title":…}, …]}
//	{"ev":"step","key":…,"state":"run|ok|fail|skip","sec":1.2,"msg":"…"}
//	{"ev":"tick","key":…,"done":N,"total":M}
//	{"ev":"summary","ok":N,"failed":N}
//
// ★ 认不出来的行**一律丢掉**：这个通道只画进度，不转发子进程的原话 ——
//   否则就等于把"逐条打印"从一条路换到另一条路（那正是这次要改掉的东西）。
//   判据里有一条专门钉它（见 selftest 的"非 JSON 行必须被丢掉"）。

import (
	"encoding/json"
	"fmt"
	"io"
	"os"
	"strings"
	"time"
)

const barWidth = 24

type progressStep struct {
	Key   string
	Title string
	State string // "" 未开始 / run / ok / fail / skip
	Done  int
	Total int
	Sec   float64
	Msg   string
}

type setupBars struct {
	steps   []progressStep
	ok      int
	failed  int
	haveSum bool
	drew    int // 上次画了几行（重画时要把光标移回去）
	spins   int
}

// apply 解析一行进度事件。认识的返回 true，其余（含子进程的散文）返回 false。
func (b *setupBars) apply(line []byte) bool {
	s := strings.TrimSpace(string(line))
	if !strings.HasPrefix(s, "{") {
		return false
	}
	var ev struct {
		Ev     string  `json:"ev"`
		Key    string  `json:"key"`
		State  string  `json:"state"`
		Sec    float64 `json:"sec"`
		Msg    string  `json:"msg"`
		Done   int     `json:"done"`
		Total  int     `json:"total"`
		OK     int     `json:"ok"`
		Failed int     `json:"failed"`
		Steps  []struct {
			Key   string `json:"key"`
			Title string `json:"title"`
		} `json:"steps"`
	}
	if err := json.Unmarshal([]byte(s), &ev); err != nil {
		return false
	}
	switch ev.Ev {
	case "plan":
		b.steps = b.steps[:0]
		for _, st := range ev.Steps {
			b.steps = append(b.steps, progressStep{Key: st.Key, Title: st.Title})
		}
		return true
	case "step":
		if st := b.find(ev.Key); st != nil {
			st.State, st.Sec, st.Msg = ev.State, ev.Sec, ev.Msg
			return true
		}
		return false
	case "tick":
		//: 只有一步会写 tick（关卡文件）⇒ 键缺省时落到**正在跑**的那一步
		st := b.find(ev.Key)
		if st == nil {
			for i := range b.steps {
				if b.steps[i].State == "run" {
					st = &b.steps[i]
					break
				}
			}
		}
		if st == nil {
			return false
		}
		st.Done, st.Total = ev.Done, ev.Total
		return true
	case "summary":
		b.ok, b.failed, b.haveSum = ev.OK, ev.Failed, true
		return true
	}
	return false //: 将来的新事件类型：老界面不认就不画，不炸
}

func (b *setupBars) find(key string) *progressStep {
	for i := range b.steps {
		if b.steps[i].Key == key {
			return &b.steps[i]
		}
	}
	return nil
}

// render 原地重画。第一次画 N 行，之后先用 ANSI 把光标移回这 N 行的开头。
func (b *setupBars) render(w io.Writer) {
	if b.drew > 0 {
		fmt.Fprintf(w, "\x1b[%dA", b.drew)
	}
	n := 0
	for i := range b.steps {
		st := &b.steps[i]
		fmt.Fprintf(w, "\x1b[2K  %s %s  %s\n", barOf(st, b.spins), pad(st.Title, 22), tailOf(st))
		n++
	}
	if b.haveSum {
		fmt.Fprintf(w, "\x1b[2K  %s\n", summaryLine(b.ok, b.failed))
		n++
	}
	b.drew = n
	b.spins++
}

// firstLineOf 取第一行、并按 width 截断（进度条那一行只放得下这么点）。
func firstLineOf(s string, width int) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexAny(s, "\r\n"); i >= 0 {
		s = s[:i]
	}
	r := []rune(s)
	if len(r) > width {
		return string(r[:width]) + "…"
	}
	return s
}

func summaryLine(ok, failed int) string {
	if failed == 0 {
		return fmt.Sprintf("准备完成：%d 项做成", ok)
	}
	return fmt.Sprintf("★ 有 %d 项没做成（下面列出原因）", failed)
}

func tailOf(st *progressStep) string {
	switch st.State {
	case "run":
		if st.Total > 0 {
			return fmt.Sprintf("%d / %d（%.0f%%）", st.Done, st.Total,
				100*float64(st.Done)/float64(st.Total))
		}
		return "进行中…"
	case "ok":
		return fmt.Sprintf("完成（%.1fs）", st.Sec)
	case "fail":
		m := st.Msg
		if m == "" {
			m = "失败"
		}
		return "★ " + firstLineOf(m, 70)
	case "skip":
		return "跳过"
	}
	return "等待"
}

func barOf(st *progressStep, spin int) string {
	switch st.State {
	case "ok":
		return "[" + strings.Repeat("█", barWidth) + "]"
	case "fail":
		return "[" + strings.Repeat("x", barWidth) + "]"
	case "skip":
		return "[" + strings.Repeat("·", barWidth) + "]"
	case "run":
		if st.Total > 0 {
			f := st.Done * barWidth / st.Total
			if f > barWidth {
				f = barWidth
			}
			return "[" + strings.Repeat("█", f) + strings.Repeat("░", barWidth-f) + "]"
		}
		//: 没有总数（建库那几步给不出百分比）⇒ 一个来回滚的块，别假装知道进度
		pos := spin % (barWidth + 4)
		cells := make([]rune, barWidth)
		for i := range cells {
			cells[i] = '░'
		}
		for k := 0; k < 4 && pos-k >= 0 && pos-k < barWidth; k++ {
			cells[pos-k] = '█'
		}
		return "[" + string(cells) + "]"
	}
	return "[" + strings.Repeat("░", barWidth) + "]"
}

// pollProgress 从上次的位置继续读进度文件（文件不存在/没新增都只是没新事件）。
func (b *setupBars) pollProgress(path string, off *int64) {
	f, err := os.Open(path)
	if err != nil {
		return
	}
	defer f.Close()
	if _, err := f.Seek(*off, io.SeekStart); err != nil {
		return
	}
	data, err := io.ReadAll(f)
	if err != nil || len(data) == 0 {
		return
	}
	*off += int64(len(data))
	for _, line := range strings.Split(strings.TrimRight(string(data), "\n"), "\n") {
		b.apply([]byte(line))
	}
}

// waitWithBars 起子进程（**stdio 继承，不抓管道**），一边轮询进度文件一边画进度条。
func waitWithBars(run func(progressFile string) error, progressFile string) error {
	done := make(chan error, 1)
	go func() { done <- run(progressFile) }()
	b := &setupBars{}
	var off int64
	tick := time.NewTicker(150 * time.Millisecond)
	defer tick.Stop()
	for {
		select {
		case err := <-done:
			b.pollProgress(progressFile, &off)
			b.render(os.Stdout)
			fmt.Println()
			return err
		case <-tick.C:
			b.pollProgress(progressFile, &off)
			b.render(os.Stdout)
		}
	}
}
