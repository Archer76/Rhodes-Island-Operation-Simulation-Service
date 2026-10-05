package main

import (
	"encoding/json"
	"go/ast"
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"reflect"
	"sort"
	"strconv"
	"testing"
)

func TestSelftestManifestMatchesStaticCallsitesAndReleaseGate(t *testing.T) {
	f, err := parser.ParseFile(token.NewFileSet(), "selftest.go", nil, 0)
	if err != nil {
		t.Fatal(err)
	}
	sites := map[string]bool{"prerequisites": true}
	ast.Inspect(f, func(n ast.Node) bool {
		call, ok := n.(*ast.CallExpr)
		if !ok {
			return true
		}
		name := ""
		switch fn := call.Fun.(type) {
		case *ast.Ident:
			name = fn.Name
		case *ast.SelectorExpr:
			name = fn.Sel.Name
		}
		if name != "check" && name != "CheckExpectedFalse" {
			return true
		}
		if len(call.Args) == 0 {
			t.Fatal("check without fixed ID")
		}
		lit, ok := call.Args[0].(*ast.BasicLit)
		if !ok || lit.Kind != token.STRING {
			t.Fatal("runtime-generated required ID")
		}
		id, err := strconv.Unquote(lit.Value)
		if err != nil {
			t.Fatal(err)
		}
		sites[id] = true
		return true
	})
	got := []string{}
	for id := range sites {
		got = append(got, id)
	}
	sort.Strings(got)
	want := append([]string{}, selftestManifest...)
	sort.Strings(want)
	if !reflect.DeepEqual(got, want) {
		t.Fatalf("static callsite inventory drift: got %v want %v", got, want)
	}
	raw, err := os.ReadFile(filepath.Join("..", "..", "..", "tools", "selftest_manifest.json"))
	if err != nil {
		t.Fatal(err)
	}
	var gate struct {
		RequiredIDs   []string       `json:"required_ids"`
		MinimumChecks map[string]int `json:"minimum_checks"`
	}
	if err := json.Unmarshal(raw, &gate); err != nil {
		t.Fatal(err)
	}
	sort.Strings(gate.RequiredIDs)
	if !reflect.DeepEqual(gate.RequiredIDs, want) || !reflect.DeepEqual(gate.MinimumChecks, selftestMinimumChecks) {
		t.Fatal("Go and release manifests differ")
	}
}
