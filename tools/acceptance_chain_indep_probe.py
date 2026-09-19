#!/usr/bin/env python3
"""验收侧探针：直接 import 原脚本 `tools/chain_judge_independence.py`，
只注入它模块级的 SRC / WORK / MUTATIONS，**不复制、不改原件**。

· 产品树只读；探针树与工作目录全在 out/acceptance/probe/ 内。
· 三个探针：
  P1 判词改名 ⇒ 归类失效必须**可观察**
  P2 新增一条判词不在表内的断言、且它在同一变异下也红 ⇒ 会不会被静默吞掉（★）
  P3 变异锚点找不到 ⇒ expect 自校验必须**当场退出**且不印矩阵
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
# 本文件可能被放在 tools/ 或 out/acceptance/ 下 ⇒ 向上找到含 rios-sim/go.mod 的那一层
ROOT = next(p for p in HERE.parents if (p / "rios-sim" / "go.mod").exists())
SRC = ROOT / "rios-sim"
PROBE = ROOT / "out" / "acceptance" / "probe"
ORIG = ROOT / "tools" / "chain_judge_independence.py"
assert (SRC / "go.mod").exists(), f"产品树定位错：{SRC}"


def load_module():
    spec = importlib.util.spec_from_file_location("chain_indep_orig", ORIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def make_tree(dst: Path) -> Path:
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "mech").mkdir(parents=True)
    shutil.copy2(SRC / "go.mod", dst / "go.mod")
    n = 0
    for p in (SRC / "mech").glob("*.go"):
        shutil.copy2(p, dst / "mech" / p.name)
        n += 1
    assert (dst / "go.mod").exists() and n >= 4, f"探针树没搭全：{dst}（{n} 个 .go）"
    return dst


def sub1(text: str, old: str, new: str, tag: str) -> str:
    n = text.count(old)
    assert n == 1, f"{tag}: 锚点出现 {n} 次（应为 1）"
    return text.replace(old, new, 1)


def run_probe(tree: Path, tag: str, tweak=None) -> tuple[int, str]:
    """tree=被测源码树（SRC）；WORK 另起一处。tweak(m) 用于改 MUTATIONS 等。"""
    m = load_module()
    m.SRC = tree
    m.WORK = PROBE / tag / "work" / "rios-sim"
    if tweak:
        tweak(m)
    buf = io.StringIO()
    code = 0
    try:
        with contextlib.redirect_stdout(buf):
            code = m.main()
    except SystemExit as e:                      # mutate() 的自校验走 SystemExit
        code = e.code if isinstance(e.code, int) else 1
        buf.write(f"\n[SystemExit] {e}\n")
    return code, buf.getvalue()


def go_test(cwd: Path) -> tuple[int, list[str]]:
    p = subprocess.run(["go", "test", "./mech/", "-run", "Chain", "-count=1", "-v"],
                       cwd=str(cwd), capture_output=True)
    raw = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")
    reds = [l.strip() for l in raw.splitlines()
            if "chain_test.go:" in l and ("红：" in l or "future" in l or "未过判据" in l)]
    return p.returncode, reds


M2_OLD = "\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}"
M2_NEW = "\t\t} else {\n\t\t\tseq[k-1] = base * scale * 1.05\n\t\t}"
PROBE.mkdir(parents=True, exist_ok=True)

# ── P1：断言5 判词改名
t1 = make_tree(PROBE / "p1" / "tree" / "rios-sim")
f1 = t1 / "mech" / "chain_test.go"
f1.write_text(sub1(f1.read_text(encoding="utf-8"),
                   't.Errorf("读法判别器红：\\n  %s", joinLines(bad))',
                   't.Errorf("读法判别器不通过：\\n  %s", joinLines(bad))', "P1"), encoding="utf-8")
rc1, out1 = run_probe(t1, "p1")

# ── P2：多一条「判词不在表内」的断言，与 M2 同时红
t2 = make_tree(PROBE / "p2" / "tree" / "rios-sim")
f2 = t2 / "mech" / "chain_test.go"
f2.write_text(sub1(f2.read_text(encoding="utf-8"),
                   '\t\tif len(bad) > 0 {\n\t\t\tt.Errorf("读法判别器红：\\n  %s", joinLines(bad))',
                   "\t\tif seqs[2][1] != chainBase*chainScale {\n"
                   '\t\t\tt.Errorf("future 新断言：候选③ n=2 与判据期望值不同（%v vs %v）",\n'
                   "\t\t\t\tseqs[2][1], chainBase*chainScale)\n"
                   "\t\t}\n"
                   '\t\tif len(bad) > 0 {\n\t\t\tt.Errorf("读法判别器红：\\n  %s", joinLines(bad))',
                   "P2"), encoding="utf-8")
rc2, out2 = run_probe(t2, "p2")

# P2 对照：把**同一棵探针树**（含注入）拷一份、手工施加 M2，数**真实**红行
w2 = PROBE / "p2" / "real"
if w2.exists():
    shutil.rmtree(w2)
shutil.copytree(t2, w2)
g = w2 / "mech" / "chain_test.go"
g.write_text(sub1(g.read_text(encoding="utf-8"), M2_OLD, M2_NEW, "P2-real"), encoding="utf-8")
rcR, redsR = go_test(w2)

# ── P3：把 M1 的锚点改坏（只改第一处；M1 与 M4 的 old 串逐字相同）
t3 = make_tree(PROBE / "p3" / "tree" / "rios-sim")


def break_anchor(m):
    old = m.MUTATIONS[0][2]
    m.MUTATIONS[0] = (m.MUTATIONS[0][0], m.MUTATIONS[0][1],
                      old.replace("return scale, nil", "return scale_XX_NOT_THERE, nil"),
                      m.MUTATIONS[0][3], m.MUTATIONS[0][4])


rc3, out3 = run_probe(t3, "p3", tweak=break_anchor)


def report(tag: str, rc: int, out: str, keys: list[str], head: int = 0) -> None:
    print(f"\n===== {tag} ⇒ rc={rc} =====")
    lines = out.splitlines()
    shown = 0
    for i, l in enumerate(lines):
        if head and i < head:
            print("   " + l[:150]); shown += 1; continue
        if not head and any(k in l for k in keys):
            print("   " + l[:150]); shown += 1
    if not shown:
        print("   （没有匹配行；原始输出尾部：）")
        for l in lines[-4:]:
            print("   " + l[:150])


report("P1 判词改名后", rc1, out1, ["基线：", "M2", "判定", "✗", "红 0 条", "红 1 条"])
report("P2 未知判词的额外红行", rc2, out2, ["基线：", "M2", "判定", "✗", "✓", "红 1 条", "红 2 条"])
report("P3 锚点找不到", rc3, out3, keys=[], head=6)
print(f"\n===== P2 真实对照（手工 M2 后 go test）⇒ rc={rcR}，真实红行 {len(redsR)} 条 =====")
for l in redsR:
    print("   " + l[:150])
print("\n===== P3 有没有印出矩阵 =====")
print("   含「矩阵」：", "矩阵" in out3, "｜含「判定：」：", "判定：" in out3,
      "｜含 SystemExit 锚点：", "锚点" in out3)

# ── P4：表内覆盖 vs 真实红面（不用变异，静态量）
import re
m0 = load_module()
txt = (SRC / "mech" / "chain_test.go").read_text(encoding="utf-8")
msgs = re.findall(r't\.(?:Errorf|Fatalf)\(\s*"((?:[^"\\]|\\.)*)"', txt)
covered, uncovered = [], []
for s in msgs:
    s_src = s.replace('\\n', '\n').replace('\\"', '"')
    (covered if any(p in s_src for _, p in m0.ASSERTIONS) else uncovered).append(s_src[:58])
print("\n===== P4 归类表覆盖 vs chain_test.go 里真实的判词 =====")
print(f"   文件里 Errorf/Fatalf 判词 {len(msgs)} 条；表内能认 {len(covered)} 条；**认不出 {len(uncovered)} 条**")
for s in uncovered:
    print("     ⊘ " + s)

