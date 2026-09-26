package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"time"
)

// # 桥的**常驻会话**：扫码登录那条链必须活在一个进程里
//
// ## 为什么非有它不可
//
// `login_start` 在桥上做的事情是**起一个后台线程**跑 `skland.login_by_qr`（申请 →
// 轮询 → 换 token），然后立刻回应。而桥的 main 是「一行一条请求、stdin 读完就退出」。
// 一次一进程时，那个后台线程**随进程一起没了** —— 于是后面不管谁去问 `login_poll`，
// 看到的都是一个**已经不存在的会话**（phase 永远停在 `idle`）。
//
// 症状会非常隐蔽：二维码画得出来（`login_start` 的应答里带着矩阵），扫了却永远没反应。
// 所以这一条链必须是：起**一个**桥进程 → 把 `login_start` 与后续的 `login_poll` 都发
// 给它 → 直到登录结束或玩家放弃。
//
// ## 协议没变
//
// 还是一行一个 JSON 对象、`id` 回填在应答里。★ `id` 这个字段当初就是为长连接留的
// （见 `engclient.go` 的说明：一次一进程时它看着多余，但少了它以后换成常驻就得改协议）
// —— 这里是它的第一个真实使用者：`nextID` 自增，应答必须答在**同一问**上。

type bridgeSession struct {
	cmd    *exec.Cmd
	stdin  io.WriteCloser
	out    *bufio.Reader
	errBuf *bytes.Buffer
	nextID int
	closed bool
}

// newBridgeSession 起一个**常驻**的桥进程（解释器与脚本的解析与一次性调用同一套）。
func newBridgeSession() (*bridgeSession, error) {
	b, err := newBridgeClient()
	if err != nil {
		return nil, err
	}
	c := exec.Command(b.python, b.script)
	//: 与一次性调用同一条纪律：子进程输出一律 UTF-8（中文 Windows 缺省 GBK，
	//: 一个字符编不出来回给我们的就是空管道，而空管道与「桥死了」长得一样）。
	c.Env = append(os.Environ(), "PYTHONIOENCODING=utf-8", "PYTHONUTF8=1")
	stdin, err := c.StdinPipe()
	if err != nil {
		return nil, fmt.Errorf("★ 桥的 stdin 拿不到：%v", err)
	}
	stdout, err := c.StdoutPipe()
	if err != nil {
		_ = stdin.Close()
		return nil, fmt.Errorf("★ 桥的 stdout 拿不到：%v", err)
	}
	errBuf := &bytes.Buffer{}
	c.Stderr = errBuf
	if err := c.Start(); err != nil {
		return nil, startError(b, err)
	}
	return &bridgeSession{cmd: c, stdin: stdin,
		out: bufio.NewReaderSize(stdout, 1<<20), errBuf: errBuf}, nil
}

// call 发一问、等一答。
//
// ⚠ 读那一行**必须带超时**：Go 的管道读没有 deadline ⇒ 用一个 goroutine 收结果、
// `select` 上超时。超时之后那个 goroutine 还挂在读上 —— 所以调用方**必须**在超时后
// 关掉会话（`close` 杀进程，管道随之关闭，那个 goroutine 就退出了）。
func (s *bridgeSession) call(cmd string, extra map[string]any,
	timeout time.Duration) (*bridgeResp, error) {
	if s.closed {
		return nil, fmt.Errorf("★ 桥会话已经关了")
	}
	s.nextID++
	id := s.nextID
	payload := map[string]any{"id": id, "cmd": cmd}
	for k, v := range extra {
		payload[k] = v
	}
	blob, err := json.Marshal(payload)
	if err != nil {
		return nil, fmt.Errorf("★ 请求序列化失败：%v", err)
	}
	if _, err := s.stdin.Write(append(blob, '\n')); err != nil {
		return nil, fmt.Errorf("★ 给桥写请求失败：%v（会话可能已经断了）", err)
	}
	line, err := s.readLine(timeout)
	if err != nil {
		return nil, err
	}
	var resp bridgeResp
	if err := json.Unmarshal([]byte(line), &resp); err != nil {
		return nil, fmt.Errorf("★ 桥的应答不是一行 JSON：%v\n    原文：%s", err, cut(line, 200))
	}
	//: ★ `id` 在长连接里**真的会串**（这是它存在的理由）：答错问就必须当场报出来，
	//: 否则"这一条是哪个命令的结果"全靠猜。
	if resp.ID != id {
		return nil, fmt.Errorf("★ 应答的 id 对不上：请求 %d，应答 %d（协议串了）", id, resp.ID)
	}
	if !resp.OK {
		return nil, fmt.Errorf("★ 桥报错：%s", resp.Error)
	}
	return &resp, nil
}

// readLine 读一行，带超时。
func (s *bridgeSession) readLine(timeout time.Duration) (string, error) {
	type res struct {
		line string
		err  error
	}
	ch := make(chan res, 1) //: 缓冲 1：超时之后那个 goroutine 也能把它自己写出去、然后退出
	go func() {
		line, err := s.out.ReadString('\n')
		ch <- res{line, err}
	}()
	select {
	case r := <-ch:
		if r.err != nil && strings.TrimSpace(r.line) == "" {
			return "", fmt.Errorf("★ 桥没有给出应答行（%v）\n    stderr：%s",
				r.err, tailLines(s.errBuf.String(), 6))
		}
		return strings.TrimSpace(r.line), nil
	case <-time.After(timeout):
		return "", fmt.Errorf("★ 桥在 %s 内没给应答（已超时）。\n"+
			"    stderr：%s", timeout, tailLines(s.errBuf.String(), 6))
	}
}

// loginStart 在**这个会话里**起扫码。
//
// ★ 这是常驻会话存在的全部理由：那个后台线程活在桥进程里，会话一关它也没了
// （见文件头）。所以 `login_start` 与后续的每一次 `login_poll` **必须发给同一个会话**。
func (s *bridgeSession) loginStart(timeout time.Duration) (*loginStartData, error) {
	resp, err := s.call("login_start", nil, timeout)
	if err != nil {
		return nil, err
	}
	return &loginStartData{Phase: resp.Phase, URL: resp.URL, QRMatrix: resp.QRMatrix,
		QRSize: resp.QRSize, QRNote: resp.QRNote, Text: resp.Text}, nil
}

// loginPoll 在同一个会话里问一次进度。`phase` 停在 `idle` 就说明会话没在跑
// （那正是一次一进程时会看到的症状）。
func (s *bridgeSession) loginPoll(timeout time.Duration) (*loginPollData, error) {
	resp, err := s.call("login_poll", nil, timeout)
	if err != nil {
		return nil, err
	}
	return &loginPollData{Phase: resp.Phase, Status: resp.Status,
		Text: resp.Text, URL: resp.URL}, nil
}

// close 关掉会话（杀进程、收尸）。**可重复调用**（超时路径也要关）。
//
// ★ 收尾必须是**彻底**的：它在好几条错误路径上被调（申请二维码失败、轮询超时、
// 玩家按 Esc），其中任何一处炸掉都会把真正的原因盖掉（玩家看到的是 panic，不是
// "桥超时"）。所以这里逐字段护住 —— 会话可能只造了一半（拿到 stdin 但进程没起来）。
func (s *bridgeSession) close() {
	if s == nil || s.closed {
		return
	}
	s.closed = true
	if s.stdin != nil {
		_ = s.stdin.Close()
	}
	if s.cmd == nil {
		return
	}
	if s.cmd.Process != nil {
		_ = s.cmd.Process.Kill()
	}
	_ = s.cmd.Wait() //: 没起来过的 Cmd，Wait 返回 "exec: not started"，不炸
}
