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

	"github.com/charmbracelet/x/ansi"
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
	//: Bytes 是**累计已下载字节**（子进程报的），Rate 是**现算的下载速度**（字节/秒）。
	//: 2026-09-28 博士要的：进度条上要有百分比与速度。
	Bytes int64
	Rate  float64
}

// sample 是算速度用的一次取样（字节数 ＋ 取样的时刻）。
type sample struct {
	bytes int64
	at    time.Time
}

type setupBars struct {
	steps   []progressStep
	ok      int
	failed  int
	haveSum bool
	drew    int // 上次画了几行（重画时要把光标移回去）
	spins   int
	//: width ≤ 0 ⇒ 现读终端宽度（`terminalWidth()`）。判据里显式给一个小值，
	//: 好把"行超宽 ⇒ 折行 ⇒ 光标漂移"这件事故意逼出来。
	width int
	//: ansi=true 强制走转义序列重画（判据里用）。真机上由 `vtEnabled` 决定：
	//: 开不了 VT 就退化成追加式，**绝不把 `[2K` 这类字面量打给玩家看**。
	ansi bool
	//: last 只在追加式里用：记每一步上次印过的状态，同一个状态不重复印。
	last map[string]string
	//: samples 记每一步上次 tick 的（字节, 时刻），用来算下载速度。
	samples map[string]sample
}

// sampleRate 用**两次 tick 的字节差 ÷ 时间差**算下载速度。
//
// ★ 时刻取 tick **自带的** `t`（epoch 秒），不是"读到这一行的时刻"：界面每 150ms
// 批量读一次文件，同一批里的几行会被打上同一个时刻 ⇒ 时间差≈0 ⇒ 速度永远算不出来
// （2026-09-28 博士："我也没看到下载速度"）。`t` 缺省（老格式）时才退回当前时刻。
//
// ★ 只在字节**真的涨了**且间隔够长时才更新：缓存命中时字节不涨（那本来就没走网络），
// 报一个"0 B/s"会被读成"卡住了"；间隔太短（同一批里的连续两行）则会算出噪声速度。
func (b *setupBars) sampleRate(st *progressStep, bytes int64, atEpoch float64) {
	st.Bytes = bytes
	if b.samples == nil {
		b.samples = map[string]sample{}
	}
	now := time.Now()
	if atEpoch > 0 {
		sec := int64(atEpoch)
		now = time.Unix(sec, int64((atEpoch-float64(sec))*1e9))
	}
	prev, ok := b.samples[st.Key]
	b.samples[st.Key] = sample{bytes: bytes, at: now}
	if !ok || bytes <= prev.bytes {
		return
	}
	dt := now.Sub(prev.at).Seconds()
	if dt < 0.2 {
		return
	}
	st.Rate = float64(bytes-prev.bytes) / dt
}

// useANSI 这次能不能用转义序列原地重画。
func (b *setupBars) useANSI() bool { return b.ansi || vtEnabled }

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
		Bytes  int64   `json:"bytes"`
		T      float64 `json:"t"` //: tick 自己的时刻（epoch 秒）—— 算速度用它
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
		//: 键缺省时落到**正在跑**的那一步（`关卡文件` 之外的步骤现在也报 tick 了）
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
		b.sampleRate(st, ev.Bytes, ev.T)
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
//
// ★ 2026-09-28 修（博士真机截图报的）：**每一行必须先夹到终端宽度以内**。
// 原版按固定预算拼行（`barWidth` ＋ `pad(title, 22)`），而标题是中文（一个字占
// **两格**），"关卡索引（akdb 里的一张表）"这种长标题直接把行顶过终端宽度 ⇒
// 终端**折行** ⇒ 一行占两个物理行，而上移仍按逻辑行数 ⇒ 每帧往下漂一行、
// 旧帧的残字留在屏上，几十帧之后满屏半截进度条。
// 判据里三条宽度断言就是钉它的（`selftest` 的二十二节）。
func (b *setupBars) render(w io.Writer) {
	if !b.useANSI() {
		b.renderAppend(w)
		return
	}
	width := b.width
	if width <= 0 {
		width = terminalWidth()
	}
	if width < 24 {
		width = 24 //: 窗口窄到离谱时也得画得出来；真窄到 24 以下，内容会被 cut 兜住
	}
	//: ⚠ 再让一格：写到**最后一列**时有些终端会自动折行（那又回到"物理行多于逻辑行"
	//: 的老问题上）。让一格最省事，视觉上也留了边距。
	width--
	//: ★★ 行数**恒定** ＋ **先占位再锚定**（2026-09-28 博士物理机截图：同一行被印了三遍）。
	//:
	//: 两个坑叠在一起：
	//:   ① 原来每帧只印"当前有内容的行"⇒ 汇总行一出现，块就长高一行，而上移仍按
	//:      上一帧的行数 ⇒ 差一行，旧字留在屏上；
	//:   ② 块贴在窗口底部时，**打印换行会让终端滚动**（内容上移、光标不动）⇒ 接下来
	//:      `\x1b[NA` 落点整体偏移 ⇒ 旧行不被覆盖，看起来就是"同一行重复出现"。
	//: 处置：块高固定 `len(steps)+1`（给汇总留一格，没有就印空行）；第一帧先打印
	//: 这么多空行**把滚动吃在锚定之前**，再上移同样行数，此后每帧都印满同样行数。
	lines := len(b.steps) + 1
	if b.drew == 0 {
		for i := 0; i < lines; i++ {
			fmt.Fprint(w, "\n")
		}
		fmt.Fprintf(w, "\x1b[%dA", lines)
	} else {
		fmt.Fprintf(w, "\x1b[%dA", b.drew)
	}
	for i := range b.steps {
		fmt.Fprintf(w, "\x1b[2K%s\n", barLine(&b.steps[i], b.spins, width))
	}
	if b.haveSum {
		fmt.Fprintf(w, "\x1b[2K%s\n", cut("  "+summaryLine(b.ok, b.failed), width))
	} else {
		fmt.Fprint(w, "\x1b[2K\n") //: 占位：汇总还没来，这一行也必须占着
	}
	b.drew = lines
	b.spins++
}

// renderAppend 是 **VT 开不了时的退路**：一行转义序列都不发，只在某一步的**状态真的变了**
// 的时候追加一行。
//
// ★ 为什么要有这条退路（2026-09-28 博士截图）：那个控制台没开 VT，于是 `\x1b[2K` 被当
// 普通字符打了出来（屏幕上全是 `[2K`、`[3A`），"原地重画"根本没发生 ⇒ 进度条不动、
// 还越堆越多。开不了 VT 就**别装作能重画** —— 老老实实按行追加，屏幕至少是干净的。
func (b *setupBars) renderAppend(w io.Writer) {
	if b.last == nil {
		b.last = map[string]string{}
	}
	width := b.width
	if width <= 0 {
		width = terminalWidth()
	}
	for i := range b.steps {
		st := &b.steps[i]
		fp := st.State //: 只认状态变没变（进度 tick 太密，追加式里不重印）
		if b.last[st.Key] == fp {
			continue
		}
		b.last[st.Key] = fp
		fmt.Fprintln(w, barLine(st, 0, width))
	}
	if b.haveSum && b.last["\x00summary"] == "" {
		b.last["\x00summary"] = "1"
		fmt.Fprintln(w, cut("  "+summaryLine(b.ok, b.failed), width))
	}
}

// barLine 拼一行进度条，**保证显示宽度 ≤ width**（夹不住就会折行，见 render 的注释）。
// 布局：两格缩进 ／ 条形（`barWidth` ＋ 一对括号）／ 两格 ／ 标题（≤22 格）／ 两格 ／ 尾巴。
// 预算不够时先压标题（最少 6 格），最后还有一道 `cut` 兜底（尾巴太长时也压它）。
func barLine(st *progressStep, spin, width int) string {
	const lead = "  "
	tail := tailOf(st)
	title := 22
	if room := width - len(lead)*3 - (barWidth + 2) - ansi.StringWidth(tail); room < title {
		title = room
	}
	if title < 6 {
		title = 6
	}
	line := lead + barOf(st, spin) + lead + pad(cut(st.Title, title), title) + lead + tail
	if ansi.StringWidth(line) > width {
		line = cut(line, width)
	}
	return line
}

// firstLineOf 取第一行、并按 width 截断（进度条那一行只放得下这么点）。
// ⚠ 截断按**显示宽度**（`cut` 走 `ansi.StringWidth`），不是按字符个数 ——
// 中文一个字占两格，按个数截会算出半个宽度。
func firstLineOf(s string, width int) string {
	s = strings.TrimSpace(s)
	if i := strings.IndexAny(s, "\r\n"); i >= 0 {
		s = s[:i]
	}
	return cut(s, width)
}

func summaryLine(ok, failed int) string {
	if failed == 0 {
		return fmt.Sprintf("准备完成：%d 项做成", ok)
	}
	return fmt.Sprintf("★ 有 %d 项没做成（下面列出原因）", failed)
}

// humanBytes 把字节数写成人读的（进度条上只留三位有效数字量级）。
func humanBytes(n int64) string {
	switch {
	case n >= 1<<30:
		return fmt.Sprintf("%.2f GB", float64(n)/float64(int64(1)<<30))
	case n >= 1<<20:
		return fmt.Sprintf("%.1f MB", float64(n)/float64(int64(1)<<20))
	case n >= 1<<10:
		return fmt.Sprintf("%.0f KB", float64(n)/float64(int64(1)<<10))
	}
	return fmt.Sprintf("%d B", n)
}

// humanRate 把"每秒多少字节"写成同样的人读形式。
func humanRate(bps float64) string { return humanBytes(int64(bps)) + "/s" }

func tailOf(st *progressStep) string {
	switch st.State {
	case "run":
		if st.Total > 0 {
			//: ★ 2026-09-28 博士要的：**百分比 ＋ 下载速度 ＋ 已下多少**。
			//: 速度是现算的（两次 tick 的字节差 ÷ 时间差），字节没涨就不报速度。
			s := fmt.Sprintf("%d / %d（%.0f%%）", st.Done, st.Total,
				100*float64(st.Done)/float64(st.Total))
			if st.Rate > 0 {
				s += " · " + humanRate(st.Rate)
			}
			if st.Bytes > 0 {
				s += " · 已下 " + humanBytes(st.Bytes)
			}
			return s
		}
		if st.Bytes > 0 {
			//: 给不出总数（建库那几步）⇒ 不假装知道百分比，只报**已下多少 ＋ 速度**
			if st.Rate > 0 {
				return "进行中… · " + humanRate(st.Rate) + " · 已下 " + humanBytes(st.Bytes)
			}
			return "进行中… · 已下 " + humanBytes(st.Bytes)
		}
		return "进行中…"
	case "ok":
		//: ★ 带上下载量：短步骤的实时数字会在"完成"那一刻被这一行取代，
		//: 不带到这儿就变成"我从没见过速度"（2026-09-28 博士）。
		if st.Bytes > 0 {
			s := fmt.Sprintf("完成（%.1fs）· 已下 %s", st.Sec, humanBytes(st.Bytes))
			if st.Sec > 0.5 {
				s += fmt.Sprintf("（%s 平均）", humanRate(float64(st.Bytes)/st.Sec))
			}
			return s
		}
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
