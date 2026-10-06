package main

import (
	"bytes"
	"context"
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"sync"
	"testing"
	"time"
)

// Each scenario runs alone in a new test process; no cache reset can hide a
// warmed first-use path, and a timeout bounds hangs in worker coordination.
func TestSkillTableColdProcess(t *testing.T) {
	if mode := os.Getenv("RIOS_O1_COLD_CHILD"); mode != "" {
		if skillTableCache != nil {
			t.Fatal("child cache was not cold")
		}
		switch mode {
		case "workers":
			exerciseColdSkillWorkers(t)
		case "retry":
			exerciseSkillLoadRetry(t)
		default:
			t.Fatalf("unknown child mode %q", mode)
		}
		return
	}
	for _, mode := range []string{"workers", "retry"} {
		t.Run(mode, func(t *testing.T) {
			ctx, cancel := context.WithTimeout(context.Background(), 60*time.Second)
			defer cancel()
			cmd := exec.CommandContext(ctx, os.Args[0], "-test.run=^TestSkillTableColdProcess$", "-test.v")
			cmd.Env = append(os.Environ(), "RIOS_O1_COLD_CHILD="+mode)
			output, err := cmd.CombinedOutput()
			t.Logf("cold child %s:\n%s", mode, output)
			if err != nil {
				t.Fatalf("cold child failed: %v (context %v)", err, ctx.Err())
			}
			if !bytes.Contains(output, []byte("O1 exercised "+mode)) {
				t.Fatal("child did not report actual exercise")
			}
		})
	}
}

func exerciseColdSkillWorkers(t *testing.T) {
	chdirRepoRootForData(t)
	// Noir Corne has no skills. This is the original un-warmed first-state path.
	spec, prof, unknown, err := bindSkillTo("char_500_noirc", 0, 100, 100, 0, 1000, 100, 1, "physical")
	if err != nil || spec != nil || prof != nil || len(unknown) != 0 {
		t.Fatalf("no-skill first state: %v %v %v %v", spec, prof, unknown, err)
	}
	if skillTableCache != nil {
		t.Fatal("no-skill first state preheated skill cache")
	}
	const workers = 32
	ids := []string{"skcom_atk_up[1]", "skcom_atk_up[2]"}
	inputs := newBuildInputs("", "", "")
	metas := make([]*SkillMeta, workers)
	errs := make([]error, workers)
	start := make(chan struct{})
	var wg sync.WaitGroup
	for i := 0; i < workers; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			<-start
			// Different request-cache keys reach the shared table concurrently; nil
			// inputs also cover the direct (non-Solve) binding/metadata path.
			if i%2 == 0 {
				metas[i], errs[i] = inputs.skillMeta(ids[(i/2)%len(ids)], 7)
			} else {
				bound, _, _, err := bindSkillTo("char_208_melan", 0, 100, 100, 0, 1000, 100, 1, "physical")
				if err != nil {
					errs[i] = err
					return
				}
				if bound == nil {
					errs[i] = context.Canceled
					return
				}
				metas[i], errs[i] = SkillMetaFor(ids[(i/2)%len(ids)], 7)
			}
		}(i)
	}
	close(start)
	wg.Wait()
	for i := range metas {
		if errs[i] != nil || metas[i] == nil {
			t.Fatalf("worker %d: %v", i, errs[i])
		}
		want, err := SkillMetaFor(ids[(i/2)%len(ids)], 7)
		if err != nil {
			t.Fatal(err)
		}
		gotJSON, err := json.Marshal(metas[i])
		if err != nil {
			t.Fatal(err)
		}
		wantJSON, err := json.Marshal(want)
		if err != nil {
			t.Fatal(err)
		}
		if !bytes.Equal(gotJSON, wantJSON) {
			t.Fatalf("worker %d metadata changed", i)
		}
	}
	bound, _, _, err := bindSkillTo("char_208_melan", 0, 100, 100, 0, 1000, 100, 1, "physical")
	if err != nil || bound == nil {
		t.Fatalf("skill binding: %v", err)
	}
	snapshot, err := LoadSkillTable()
	if err != nil {
		t.Fatal(err)
	}
	raw := append([]byte(nil), snapshot[ids[0]]...)
	snapshot[ids[0]][0] = '!'
	delete(snapshot, ids[1])
	snapshot["O1_fake"] = json.RawMessage(`{}`)
	next, err := LoadSkillTable()
	if err != nil {
		t.Fatal(err)
	}
	if !bytes.Equal(next[ids[0]], raw) || next[ids[1]] == nil || next["O1_fake"] != nil {
		t.Fatal("caller mutation polluted published table")
	}
	if _, err := SkillMetaFor(ids[0], 0); err == nil {
		t.Fatal("invalid level accepted")
	}
	if _, err := SkillMetaFor("O1_missing", 7); err == nil {
		t.Fatal("unknown skill accepted")
	}
	t.Logf("O1 exercised workers: cold no-skill first state, %d workers, two IDs, complete metadata equality, binding and owned snapshot", workers)
}

func exerciseSkillLoadRetry(t *testing.T) {
	root := t.TempDir()
	t.Setenv("RIOS_DATA", root)
	dir := filepath.Join(root, "raw.githubusercontent.com", "excel")
	if err := os.MkdirAll(dir, 0755); err != nil {
		t.Fatal(err)
	}
	path := filepath.Join(dir, "skill_table.json")
	checkError := func(part string) {
		t.Helper()
		tbl, err := LoadSkillTable()
		if tbl != nil || err == nil || !strings.Contains(err.Error(), part) || !strings.Contains(err.Error(), path) {
			t.Fatalf("error semantics: table=%v err=%v", tbl, err)
		}
		if skillTableCache != nil {
			t.Fatal("failed load published cache")
		}
	}
	checkError("读 skill_table 失败")
	for _, tc := range []struct{ body, part string }{{"{", "不是合法 JSON"}, {"{}", "是空的"}} {
		if err := os.WriteFile(path, []byte(tc.body), 0644); err != nil {
			t.Fatal(err)
		}
		checkError(tc.part)
	}
	if err := os.WriteFile(path, []byte(`{"O1_fixture":{"levels":[]}}`), 0644); err != nil {
		t.Fatal(err)
	}
	tbl, err := LoadSkillTable()
	if err != nil || tbl["O1_fixture"] == nil {
		t.Fatalf("retry failed: %v", err)
	}
	if err := os.WriteFile(path, []byte(`{}`), 0644); err != nil {
		t.Fatal(err)
	}
	tbl, err = LoadSkillTable()
	if err != nil || tbl["O1_fixture"] == nil {
		t.Fatalf("successful snapshot changed: %v", err)
	}
	t.Log("O1 exercised retry: missing/malformed/empty errors retained, successful retry, stable publication")
}
