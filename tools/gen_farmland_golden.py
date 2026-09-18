# -*- coding: utf-8 -*-
"""生成 Go 侧的田地**金标测试**（`rios-sim/mech/farmland_golden_test.go`）。

金标值来自**原版 Python 实现**（`ak_tactic/battle/environment.py`）：同一串脚本化
事件喂给它，逐步记下三个量（每片【最大】【缓存】、每格【实际】）。Go 的端口一旦在
某条口径上漂了——少一次夹取、缓存的节拍差一帧、`ceil` 与 `floor` 之差——测试会
**在数值上**立刻红，而不是等对拍到"病害值涨得快一点"这种没人看得见的现象。

为什么不手写期望值：手写的测的是"我以为的原文"，不是"Python 怎么算的"。

为什么不把金标放成独立数据文件：测试要**自足**（克隆仓库的人 `go test ./mech/`
就能跑，不必先有 Python 环境与游戏数据）。所以金标作为 JSON 字面量嵌在生成的
Go 文件里，几万字节的事。

判据是**精确相等**（不是近似）：两边跑的是同一串浮点加法，JSON 的浮点字面量在
Python 侧走 `repr`、在 Go 侧走 `strconv`，两边都精确往返。容差在这里是有害的
——它会把"缓存节拍差一帧"这种错误平均掉。

重跑：

    python tools/gen_farmland_golden.py
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import environment as env     # noqa: E402
from ak_tactic.simgo import mech                    # noqa: E402

OUT = ROOT / "rios-sim" / "mech" / "farmland_golden_test.go"

#: 一块手工田。布局（x 向右、y 向下；`#` 田地、`Z` 播种 60、`.` 不是田地）：
#:
#:     # # . # # .
#:     # Z . # # .
#:     # # . # # .
#:     . # . # . .
#:     . . . S . .      ← S=(2,4) 是泵站的水源地（泵站自身在 (2,3)、朝上）
#:
#: 左片 6 格（含 Z）、右片 7 格，中间那列是沟——分割与还原都会真的改变分组。
CELLS = [(0, 0), (1, 0), (3, 0), (4, 0),
         (0, 1), (1, 1), (3, 1), (4, 1),
         (0, 2), (1, 2), (3, 2), (4, 2),
         (1, 3), (3, 3),
         (2, 4)]                                    # 泵站的水源地
INIT_POLLUT = {(1, 1): 60.0}
PARAMS = dict(basic_damage=30.0, damage_ratio=4.0, first_basic_damage=200.0,
              first_damage_ratio=14.0, hp_recovery_per_sec=50.0)
WIDTH, HEIGHT = 6, 5
PUMP_CELL = (2, 3)
PUMP_DIR = "UP"
STEPS = 40


class _FakeSim:
    """`farmland_spec` 只读 `farmland` 与 `_devices`。"""

    def __init__(self, fs):
        self.farmland = fs
        self._devices = []


def build():
    params = env.PolluteParams(**PARAMS, difficulty="NORMAL",
                              init_pollut=dict(INIT_POLLUT))
    stub = mech._StubMap(WIDTH, HEIGHT, set(CELLS))
    return env.FarmlandSystem(mech._Stage(stub), params)


def script() -> list[dict]:
    """事件串。刻意小，但每一类都走到：节拍、圆污染（含半径 0）、单格污染、
    加缓存、抽干、分割、还原、泵站两支、三个结算读数。"""
    out: list[dict] = []
    for i in range(STEPS):
        out.append({"op": "tick", "v": 0.1})
        if i == 3:
            out.append({"op": "pollute_area", "x": 1, "y": 1, "r": 1.0, "v": 15.0})
        if i == 5:
            out.append({"op": "pollute_area", "x": 3, "y": 1, "r": 0.0, "v": 10.0})
        if i == 8:
            out.append({"op": "pollute_cell", "x": 0, "y": 2, "v": 5.0})
        if i == 10:
            out.append({"op": "add_cache", "x": 4, "y": 2, "v": 40.0})
        if i == 12:
            out.append({"op": "pump", "ally": False})
        if i == 14:
            out.append({"op": "drain", "x": 1, "y": 1, "v": 10.0})
        if i == 16:
            out.append({"op": "sever", "x": 1, "y": 2})
        if i == 18:
            out.append({"op": "pump", "ally": True})
        if i == 22:
            out.append({"op": "restore", "x": 1, "y": 2})
        if i == 25:
            out.append({"op": "pollute_area", "x": 3, "y": 2, "r": 1.5, "v": 25.0})
        if i == 28:
            out.append({"op": "readings", "x": 1, "y": 1})
        if i == 30:
            out.append({"op": "sever", "x": 3, "y": 0})
        if i == 33:
            out.append({"op": "pump", "ally": False})
        if i == 36:
            out.append({"op": "restore", "x": 3, "y": 0})
        if i == 38:
            out.append({"op": "readings", "x": 0, "y": 0})
    return out


def run() -> list[dict]:
    """跑一遍原版，返回带着期望值的步骤表。"""
    fs = build()
    out: list[dict] = []
    for ev in script():
        kind = ev["op"]
        ret: float | None = None
        if kind == "tick":
            fs.tick(ev["v"])
        elif kind == "pollute_area":
            ret = fs.pollute_area(ev["x"], ev["y"], ev["r"], ev["v"])
        elif kind == "pollute_cell":
            ret = fs.pollute_cell(ev["x"], ev["y"], ev["v"])
        elif kind == "add_cache":
            ret = fs.add_cache(ev["x"], ev["y"], ev["v"])
        elif kind == "drain":
            ret = fs.drain_cell(ev["x"], ev["y"], ev["v"])
        elif kind == "sever":
            fs.sever(ev["x"], ev["y"])
        elif kind == "restore":
            fs.restore(ev["x"], ev["y"])
        elif kind == "pump":
            r = fs.pump(PUMP_CELL, PUMP_DIR, ally_on_source=bool(ev["ally"]))
            ret = None if r is None else float(r["delta"])
        step = dict(ev)
        if ret is not None:
            step["ret"] = ret
        if kind == "readings":
            step["readings"] = [fs.deploy_damage(ev["x"], ev["y"]),
                                fs.damage_per_second(ev["x"], ev["y"]),
                                fs.regen_per_second(ev["x"], ev["y"])]
        step["fields"] = [{"cells": sig(sorted(f.cells)),
                           "maximum": f.maximum, "cache": f.cache}
                          for f in fs.fields]
        step["actual"] = [[c[0], c[1], v] for c, v in sorted(fs.actual.items())]
        out.append(step)
    return out


def sig(cells) -> str:
    """一片田地的身份：格集合的规范字符串（与顺序无关）。"""
    return ";".join(f"{x},{y}" for x, y in sorted(cells))


GO_TEMPLATE = '''// Code generated by tools/gen_farmland_golden.py. DO NOT EDIT.
//
// 田地/病害值状态机的**金标测试**：期望值来自原版 Python 实现
// （`ak_tactic/battle/environment.py`），同一串脚本化事件逐步记下三个量。
//
// 重跑：`python tools/gen_farmland_golden.py`
//
// 判据是**精确相等**：两边跑的是同一串浮点加法，JSON 的浮点字面量两侧都精确往返。
// 容差在这里是有害的——它会把"缓存节拍差一帧"这种错误平均掉。
package mech

import (
	"encoding/json"
	"sort"
	"strconv"
	"strings"
	"testing"
)

const goldenSpecJSON = `%SPEC%`

const goldenStepsJSON = `%STEPS%`

type goldenField struct {
	Cells   string  `json:"cells"`
	Maximum float64 `json:"maximum"`
	Cache   float64 `json:"cache"`
}

type goldenStep struct {
	Op       string          `json:"op"`
	X        int             `json:"x"`
	Y        int             `json:"y"`
	R        float64         `json:"r"`
	V        float64         `json:"v"`
	Ally     bool            `json:"ally"`
	Ret      *float64        `json:"ret"`
	Readings []float64       `json:"readings"`
	Fields   []goldenField   `json:"fields"`
	Actual   [][3]float64    `json:"actual"`
}

// fieldSig 与生成器里的 `sig()` 同口径：格集合的规范字符串。
func fieldSig(cells map[Cell]bool) string {
	xs := make([]Cell, 0, len(cells))
	for c := range cells {
		xs = append(xs, c)
	}
	sort.Slice(xs, func(i, j int) bool {
		if xs[i][0] != xs[j][0] {
			return xs[i][0] < xs[j][0]
		}
		return xs[i][1] < xs[j][1]
	})
	parts := make([]string, 0, len(xs))
	for _, c := range xs {
		parts = append(parts, strconv.Itoa(c[0])+","+strconv.Itoa(c[1]))
	}
	return strings.Join(parts, ";")
}

// TestFarmlandGolden 逐步重放脚本，每一步都比三个量与返回值。
func TestFarmlandGolden(t *testing.T) {
	var spec FarmlandSpec
	if err := json.Unmarshal([]byte(goldenSpecJSON), &spec); err != nil {
		t.Fatalf("规格解不开：%%v", err)
	}
	var steps []goldenStep
	if err := json.Unmarshal([]byte(goldenStepsJSON), &steps); err != nil {
		t.Fatalf("步骤解不开：%%v", err)
	}
	fs, err := NewFarmland(&spec)
	if err != nil {
		t.Fatalf("建田地失败：%%v", err)
	}
	if len(steps) == 0 {
		t.Fatal("金标是空的")
	}
	for i, st := range steps {
		var ret float64
		switch st.Op {
		case "tick":
			fs.Tick(st.V)
		case "pollute_area":
			ret = fs.PolluteArea(st.X, st.Y, st.R, st.V)
		case "pollute_cell":
			ret = fs.PolluteCell(st.X, st.Y, st.V)
		case "add_cache":
			ret = fs.AddCache(st.X, st.Y, st.V)
		case "drain":
			ret = fs.DrainCell(st.X, st.Y, st.V)
		case "sever":
			fs.Sever(st.X, st.Y)
		case "restore":
			fs.Restore(st.X, st.Y)
		case "pump":
			r := fs.Pump([2]int{%PUMPX%, %PUMPY%}, %PUMPDIR%, st.Ally)
			if st.Ret == nil && r != nil {
				t.Errorf("第 %%d 步泵水：Python 什么也没做，Go 做了 %%v", i, r)
			}
			if st.Ret != nil {
				if r == nil {
					t.Errorf("第 %%d 步泵水：Python 做了 %%v，Go 什么也没做", i, *st.Ret)
				} else {
					ret = r.Delta
				}
			}
		case "readings":
			got := [3]float64{fs.DeployDamage(st.X, st.Y),
				fs.DamagePerSecond(st.X, st.Y), fs.RegenPerSecond(st.X, st.Y)}
			for k := range got {
				if got[k] != st.Readings[k] {
					t.Errorf("第 %%d 步读数[%%d]：Go %%v，Python %%v",
						i, k, got[k], st.Readings[k])
				}
			}
		default:
			t.Fatalf("第 %%d 步有不认识的指令 %%q", i, st.Op)
		}
		if st.Ret != nil && st.Op != "pump" && ret != *st.Ret {
			t.Errorf("第 %%d 步 %%s 的返回值：Go %%v，Python %%v", i, st.Op, ret, *st.Ret)
		}
		snap := fs.Snapshot()
		if len(snap.Fields) != len(st.Fields) {
			t.Fatalf("第 %%d 步片数：Go %%d，Python %%d", i, len(snap.Fields), len(st.Fields))
		}
		// 片按身份字符串对齐后逐片比：Go 的片序与 Python 的片序都不保证一致
		bySig := map[string][3]float64{}
		for _, f := range fs.fields {
			bySig[fieldSig(f.Cells)] = [3]float64{0, f.Maximum, f.Cache}
		}
		for _, want := range st.Fields {
			got, ok := bySig[want.Cells]
			if !ok {
				t.Fatalf("第 %%d 步少了片 %%s（Go 有 %%v）", i, want.Cells, sigKeys(bySig))
			}
			if got[1] != want.Maximum || got[2] != want.Cache {
				t.Errorf("第 %%d 步片 %%s：【最大/缓存】Go %%v，Python %%v",
					i, want.Cells, got[1:], [2]float64{want.Maximum, want.Cache})
			}
		}
		gotActual := make([][3]float64, 0, len(snap.Actual))
		gotActual = append(gotActual, snap.Actual...)
		if len(gotActual) != len(st.Actual) {
			t.Fatalf("第 %%d 步【实际】格数：Go %%d，Python %%d", i, len(gotActual), len(st.Actual))
		}
		for k := range gotActual {
			if gotActual[k] != st.Actual[k] {
				t.Errorf("第 %%d 步【实际】第 %%d 项：Go %%v，Python %%v",
					i, k, gotActual[k], st.Actual[k])
			}
		}
	}
}

func sigKeys(m map[string][3]float64) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	sort.Strings(out)
	return out
}
'''


def main() -> int:
    fs = build()
    spec = mech.farmland_spec(_FakeSim(fs))
    steps = run()
    spec_json = json.dumps(spec, ensure_ascii=False, separators=(",", ":"))
    steps_json = json.dumps(steps, ensure_ascii=False, separators=(",", ":"))
    src = (GO_TEMPLATE
           # 模板里的 `%%` 是按 `%`-格式化写的转义；这里是 replace，得先解回来，
           # 否则生成出来的 Go 文件里留着 `%%v`，`go vet` 会报"格式串没有动词、
           # 却给了参数"。替换在插入 JSON **之前**做，免得动到金标内容。
           .replace("%%", "%")
           .replace("%SPEC%", spec_json)
           .replace("%STEPS%", steps_json)
           .replace("%PUMPX%", str(PUMP_CELL[0]))
           .replace("%PUMPY%", str(PUMP_CELL[1]))
           .replace("%PUMPDIR%", json.dumps(PUMP_DIR)))
    OUT.write_text(src, encoding="utf-8")
    dirty = sum(1 for f in fs.fields if f.maximum > 0)
    print(f"写好了 {OUT.relative_to(ROOT)}：{len(steps)} 步，"
          f"{len(fs.fields)} 片（有病害 {dirty} 片），"
          f"{len(spec_json) + len(steps_json)} 字节金标")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
