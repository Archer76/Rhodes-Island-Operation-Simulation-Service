package main

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"os"
	"os/exec"
	"sync"
	"sync/atomic"

	tea "github.com/charmbracelet/bubbletea"
	"rios-sim/progress"
)

var solveTaskSequence atomic.Uint64

type solveProgressMsg struct {
	taskID   uint64
	round    int
	snapshot progress.Snapshot
}

type solveTask struct {
	id      uint64
	round   int
	ctx     context.Context
	cancel  context.CancelFunc
	updates chan solveProgressMsg
	result  chan solveRoundMsg
	exited  chan struct{}
}

// The screen owns a task; commands only read its channels. Neither process IO
// nor simulation runs in the Bubble Tea update loop. A one-slot mailbox keeps
// the newest snapshot without blocking the engine behind a slow renderer.
func startSolveTask(id uint64, round int, p solveParams, depth int) *solveTask {
	ctx, cancel := context.WithTimeout(context.Background(), solveTimeout)
	t := &solveTask{id: id, round: round, ctx: ctx, cancel: cancel,
		updates: make(chan solveProgressMsg, 1), result: make(chan solveRoundMsg, 1), exited: make(chan struct{})}
	go func() {
		defer close(t.exited)
		defer cancel()
		out, err := runSolveStreaming(ctx, p, depth, func(s progress.Snapshot) {
			m := solveProgressMsg{taskID: id, round: round, snapshot: s}
			select {
			case t.updates <- m:
			default:
				select {
				case <-t.updates:
				default:
				}
				select {
				case t.updates <- m:
				default:
				}
			}
		})
		t.result <- solveRoundMsg{taskID: id, round: round, depth: depth, out: out, err: err}
	}()
	return t
}

func (t *solveTask) next() tea.Cmd {
	return func() tea.Msg {
		select {
		case m := <-t.updates:
			return m
		default:
		}
		select {
		case m := <-t.updates:
			return m
		case m := <-t.result:
			return t.finalMessage(m)
		case <-t.ctx.Done():
			// Wait for exec.Wait to reap the process; this wait is outside the UI.
			<-t.exited
			return t.finalMessage(<-t.result)
		}
	}
}

// Once the final result is available the producer cannot emit another snapshot.
// Deliver any pending last snapshot first, then the final result on the next command.
func (t *solveTask) finalMessage(m solveRoundMsg) tea.Msg {
	select {
	case p := <-t.updates:
		t.result <- m
		return p
	default:
		return m
	}
}

// stderr is a separate, versioned progress stream. Plain diagnostic lines are
// retained in a bounded tail and never interpreted as stdout responses.
type progressWriter struct {
	mu        sync.Mutex
	pending   []byte
	tail      []byte
	requestID int
	emit      func(progress.Snapshot)
}

func (w *progressWriter) Write(p []byte) (int, error) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.pending = append(w.pending, p...)
	for {
		i := bytes.IndexByte(w.pending, '\n')
		if i < 0 {
			break
		}
		line := w.pending[:i]
		var event struct {
			Type     string            `json:"type"`
			Progress progress.Snapshot `json:"progress"`
		}
		if json.Unmarshal(line, &event) == nil && event.Type == "solve_progress" {
			if event.Progress.RequestID == w.requestID && w.emit != nil {
				w.emit(event.Progress)
			}
		} else {
			w.tail = append(w.tail, line...)
			w.tail = append(w.tail, '\n')
		}
		w.pending = w.pending[i+1:]
	}
	if len(w.pending) > 1<<20 {
		w.tail = append(w.tail, w.pending...)
		w.pending = nil
	}
	if len(w.tail) > 8192 {
		w.tail = append([]byte(nil), w.tail[len(w.tail)-8192:]...)
	}
	return len(p), nil
}
func (w *progressWriter) diagnostic() string {
	w.mu.Lock()
	defer w.mu.Unlock()
	return string(append(append([]byte(nil), w.tail...), w.pending...))
}

func solveRequest(p solveParams, depth int) map[string]any {
	spec := map[string]any{"roster": p.rosterPath, "operators": p.pool,
		"max_ops": depth, "min_ops": 1, "beam": p.beam, "per_op": p.perOp, "difficulty": p.difficulty}
	if p.support != "" {
		spec["support"] = p.support
	}
	return map[string]any{"id": 1, "cmd": "solve", "level": p.levelID, "spec": spec}
}

func runSolveStreaming(ctx context.Context, p solveParams, depth int, emit func(progress.Snapshot)) (solveOutView, error) {
	ec, err := newEngineClient()
	if err != nil {
		return solveOutView{}, err
	}
	return ec.solveStreaming(ctx, p, depth, emit)
}
func (e *engineClient) solveStreaming(ctx context.Context, p solveParams, depth int, emit func(progress.Snapshot)) (solveOutView, error) {
	var out solveOutView
	line, err := json.Marshal(solveRequest(p, depth))
	if err != nil {
		return out, err
	}
	c := exec.CommandContext(ctx, e.path, e.args...)
	c.Dir = e.dir
	if d := engineDataRoot(); d != "" {
		c.Env = append(os.Environ(), "RIOS_DATA="+d)
	}
	c.Stdin = bytes.NewReader(append(line, '\n'))
	var stdout bytes.Buffer
	stderr := &progressWriter{requestID: 1, emit: emit}
	c.Stdout = &stdout
	c.Stderr = stderr
	err = c.Run()
	if ctx.Err() != nil {
		return out, ctx.Err()
	}
	if err != nil {
		return out, fmt.Errorf("★ 引擎退出失败：%w；stderr：%s", err, tailLines(stderr.diagnostic(), 6))
	}
	// Exactly one final stdout response, regardless of progress volume.
	scanner := bufio.NewScanner(&stdout)
	scanner.Buffer(make([]byte, 4096), 1<<26)
	var responseLine []byte
	for scanner.Scan() {
		if len(bytes.TrimSpace(scanner.Bytes())) == 0 {
			continue
		}
		if responseLine != nil {
			return out, fmt.Errorf("★ 解算收到多条最终应答")
		}
		responseLine = append([]byte(nil), scanner.Bytes()...)
	}
	if err := scanner.Err(); err != nil {
		return out, err
	}
	if responseLine == nil {
		return out, fmt.Errorf("★ 引擎没有给出应答：%s", tailLines(stderr.diagnostic(), 6))
	}
	var resp struct {
		ID    int             `json:"id"`
		OK    bool            `json:"ok"`
		Error string          `json:"error"`
		Solve json.RawMessage `json:"solve"`
	}
	if err := json.Unmarshal(responseLine, &resp); err != nil {
		return out, fmt.Errorf("★ 解算应答解析失败：%w", err)
	}
	if resp.ID != 1 {
		return out, fmt.Errorf("★ 解算应答 id 对不上：%d", resp.ID)
	}
	if !resp.OK {
		return out, fmt.Errorf("★ 引擎报错：%s", resp.Error)
	}
	if len(resp.Solve) == 0 {
		return out, fmt.Errorf("★ 引擎应答缺 solve 段")
	}
	if err := json.Unmarshal(resp.Solve, &out); err != nil {
		return out, fmt.Errorf("★ solve 段解不开：%w", err)
	}
	return out, nil
}

// Assert the writer remains a streaming stderr sink, not a whole-run buffer.
var _ io.Writer = (*progressWriter)(nil)
