#!/usr/bin/env python3
"""验收侧复验器 v4 · 按 §十一 预注册的 G1..G5 逐条取证。

形态：**直接 import** `tools/chain_judge_independence.py`，只注入模块级
`SRC`／`WORK`／`MUTATIONS`，**不复制、不改原件** ⇒ 量的是它那一份。

读数列（每条都给 rc 与关键原文，不靠自陈）：
  A 基线 / G4 矩阵   —— 它自己的脚本（pinned sha）
  C G1 判词改名      —— 我的树：区间内但表外
  D G1 表外判词同红  —— 我的树：**预注册 G1 的那个形态**
  E G1 行号区间外    —— 它的两个控制组**都没覆盖**的那条分支（间接接收者）
  F ★ 同包另一个 _test.go 里的红 —— 取证范围 vs 结论范围
  G G3 反向守卫      —— 把两条锚点改成相同，看它的自校验会不会红
  H P3 锚点坏        —— 必须当场退出且不印矩阵
  I G2 我的尺子加词边界后复算 = 13
  J G5 外部哈希      —— 我自己算，不靠它脚本内打印
"""

from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import os
import re
import shutil
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = next(p for p in HERE.parents if (p / "rios-sim" / "go.mod").exists())
SRC = ROOT / "rios-sim"
PROBE = ROOT / "out" / "acceptance" / "probe"
ORIG = (Path(os.environ["CHAIN_INDEP_PIN"]) if os.environ.get("CHAIN_INDEP_PIN")
        else ROOT / "tools" / "chain_judge_independence.py")
assert (SRC / "go.mod").exists(), f"产品树定位错：{SRC}"

M2_OLD = "\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}"
M2_NEW = "\t\t} else {\n\t\t\tseq[k-1] = base * scale * 1.05\n\t\t}"
P2_ANCHOR = "\t\tif len(bad) > 0 {"
FOREIGN = """package mech

import "testing"

// 验收侧 P6：同包**另一个测试文件**里的判词（-run Chain 会跑到它）。
func TestChainForeignProbe(t *testing.T) {
	seq, err := chainHealJumps(chainBase, 2, chainScale)
	if err != nil {
		t.Fatalf("外文件探针：调用失败 %v", err)
	}
	if len(seq) > 1 && seq[1] != chainBase*chainScale {
		t.Errorf("P6 外文件的红：第 2 跳 %v，应为 %v", seq[1], chainBase*chainScale)
	}
}
"""


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
    except SystemExit as e:
        code = e.code if isinstance(e.code, int) else 1
        buf.write(f"\n[SystemExit] {e}\n")
    return code, buf.getvalue()


NEEDLES = ["实现未过判据：", "时必须返回 ErrJumpUndetermined", "没抓住「", "读法判别器红：",
           "n=3 的 ", "future 新断言", "P5 间接接收者", "P6 外文件的红", "P7b 同行被吞的红"]


def real_failures(tree: Path, tag: str, mut: tuple[str, ...]):
    """★ 独立对照：手工施加该变异，`go test`（**不带 -v**）后**按我自己的针数**。

    ★ 仪器说明（我自己先踩过）：不带 -v 只抑制「通过」的日志，**失败的测试仍会把它全部
    `t.Logf` dump 出来** ⇒ 输出行数 ≠ 红行数（我第一版就是这么数出「13 条」的假读数）。
    所以这里数的是**我注入/已知的判词原文**，并且**报出出现过哪些 _test.go 文件**——
    后者不依赖任何行号分类，是「另一个文件里到底有没有红」的直接读数。
    """
    d = PROBE / tag / "real"
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(tree, d)
    rel, old, new = mut[1], mut[2], mut[3]
    p = d / rel
    p.write_text(sub1(p.read_text(encoding="utf-8"), old, new, f"{tag}-real"), encoding="utf-8")
    r = subprocess.run(["go", "test", "./mech/", "-run", "Chain", "-count=1"],
                       cwd=str(d), capture_output=True)
    raw = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    lines = [l.strip() for l in raw.splitlines() if re.match(r"\s+\S+_test\.go:\d+:", l)]
    hits = {n: sum(1 for l in lines if n in l) for n in NEEDLES}
    files = sorted({re.match(r"\s*(\S+_test\.go):", l).group(1) for l in lines
                    if re.match(r"\s*(\S+_test\.go):", l)})
    return r.returncode, {k: v for k, v in hits.items() if v}, files, len(lines), lines


def precheck(tree: Path, tag: str):
    """对照的前置断言：未变异的树必须 rc=0、**输出一行都不该有**。"""
    d = PROBE / tag / "pre"
    if d.exists():
        shutil.rmtree(d)
    shutil.copytree(tree, d)
    r = subprocess.run(["go", "test", "./mech/", "-run", "Chain", "-count=1"],
                       cwd=str(d), capture_output=True)
    raw = ((r.stdout or b"") + (r.stderr or b"")).decode("utf-8", "replace")
    n_red = len([l for l in raw.splitlines() if re.match(r"\s+\S+_test\.go:\d+:", l)])
    return r.returncode, n_red


def go_reds(cwd: Path) -> tuple[int, list[str]]:
    p = subprocess.run(["go", "test", "./mech/", "-run", "Chain", "-count=1", "-v"],
                       cwd=str(cwd), capture_output=True)
    raw = ((p.stdout or b"") + (p.stderr or b"")).decode("utf-8", "replace")
    reds = [l.strip() for l in raw.splitlines() if re.match(r"\s+\S+_test\.go:\d+:", l)]
    return p.returncode, reds


def hashes() -> dict[str, str]:
    out = {}
    for p in [SRC / "go.mod"] + sorted((SRC / "mech").glob("*.go")):
        out[str(p.relative_to(SRC))] = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
    return out


PROBE.mkdir(parents=True, exist_ok=True)
_b = ORIG.read_bytes()
print(f"[仪器] 被审文件 = {ORIG}")
print(f"        sha256[:16] = {hashlib.sha256(_b).hexdigest()[:16]}、行数 = {_b.decode('utf-8').count(chr(10))}")
H0 = hashes()

# ── C：判词改名（区间内、表外）
tC = make_tree(PROBE / "c" / "rios-sim")
f = tC / "mech" / "chain_test.go"
f.write_text(sub1(f.read_text(encoding="utf-8"),
                  't.Errorf("读法判别器红：\\n  %s", joinLines(bad))',
                  't.Errorf("读法判别器不通过：\\n  %s", joinLines(bad))', "C"), encoding="utf-8")
rcC, outC = run_probe(tC, "c")

# ── D：★ 预注册 G1 的那个形态（表外判词 ＋ 表内同时红）
tD = make_tree(PROBE / "d" / "rios-sim")
f = tD / "mech" / "chain_test.go"
f.write_text(sub1(f.read_text(encoding="utf-8"), P2_ANCHOR,
                  "\t\tif seqs[2][1] != chainBase*chainScale {\n"
                  '\t\t\tt.Errorf("future 新断言：候选③ n=2 与判据期望值不同（%v vs %v）",\n'
                  "\t\t\t\tseqs[2][1], chainBase*chainScale)\n"
                  "\t\t}\n" + P2_ANCHOR, "D"), encoding="utf-8")
rcD, outD = run_probe(tD, "d")
M2_MUT = ("M2", "mech/chain_test.go", M2_OLD, M2_NEW)
M1_MUT = load_module().MUTATIONS[0]
pD = precheck(tD, "d")
rcDr, hitsD, filesD, nD, lD = real_failures(tD, "d", M2_MUT)

# ── E：行号落在任何已知调用区间外（间接接收者，CALL_RE 的 \bt\. 认不出）
tE = make_tree(PROBE / "e" / "rios-sim")
f = tE / "mech" / "chain_test.go"
f.write_text(sub1(f.read_text(encoding="utf-8"), P2_ANCHOR,
                  "\t\ttt := t\n"
                  "\t\tif seqs[2][1] != chainBase*chainScale {\n"
                  '\t\t\ttt.Errorf("P5 间接接收者：候选③ n=2 与期望不同")\n'
                  "\t\t}\n" + P2_ANCHOR, "E"), encoding="utf-8")
rcE, outE = run_probe(tE, "e")
pE = precheck(tE, "e")
rcEr, hitsE, filesE, nE, lE = real_failures(tE, "e", M2_MUT)

# ── F：★ 同包**另一个 _test.go** 里的红（RED_RE 只认 chain_test.go）
tF = make_tree(PROBE / "f" / "rios-sim")
(tF / "mech" / "zz_probe_test.go").write_text(FOREIGN, encoding="utf-8")
rcF, outF = run_probe(tF, "f")
pF = precheck(tF, "f")
rcFr, hitsF, filesF, nF, lF = real_failures(tF, "f", M1_MUT)

# ── G：G3 反向守卫（把 M4 的锚点改成与 M1 逐字相同）
def dup_anchor(m):
    m.MUTATIONS[3] = (m.MUTATIONS[3][0], m.MUTATIONS[3][1], m.MUTATIONS[0][2],
                      m.MUTATIONS[3][3], m.MUTATIONS[3][4])

rcG, outG = run_probe(make_tree(PROBE / "g" / "rios-sim"), "g", tweak=dup_anchor)

# ── H：P3 锚点坏
def break_anchor(m):
    o = m.MUTATIONS[0][2]
    m.MUTATIONS[0] = (m.MUTATIONS[0][0], m.MUTATIONS[0][1],
                      o.replace("return scale, nil", "return scale_XX_NOT_THERE, nil"),
                      m.MUTATIONS[0][3], m.MUTATIONS[0][4])

rcH, outH = run_probe(make_tree(PROBE / "h" / "rios-sim"), "h", tweak=break_anchor)


# ── P7：★ 同行两个调用、Logf 在前 ⇒ 整行被标成「日志」⇒ 同行的 Errorf 红被丢弃（G6 修不掉的那一半）
#        另记一条本轮实测：我先前那版（Logf 消息里含未配平的 ASCII 左括号）会造成跨度外溢，
#        但**被它自己后面那个 t.Errorf( 重新标回「判词」**（marking 后写覆盖前写）⇒ 外溢单独不致命。
tP7 = make_tree(PROBE / "p7" / "rios-sim")
f = tP7 / "mech" / "chain_test.go"
_p7 = ('\t\tif seqs[2][1] != chainBase*chainScale { t.Logf("P7b 同行日志"); '
       't.Errorf("P7b 同行被吞的红：%v", seqs[2][1]) }\n')
f.write_text(sub1(f.read_text(encoding="utf-8"), P2_ANCHOR, _p7 + P2_ANCHOR, "P7"), encoding="utf-8")
rcP7, outP7 = run_probe(tP7, "p7")
pP7 = precheck(tP7, "p7")
rcP7r, hitsP7, filesP7, nP7, lP7 = real_failures(tP7, "p7", M2_MUT)
H1 = hashes()


def show(tag: str, rc: int, out: str, pats: list[str], also: list[str] = ()) -> None:
    print(f"\n===== {tag} ⇒ rc={rc} =====")
    lines = out.splitlines()
    hit = 0
    for l in lines:
        if any(p in l for p in pats):
            print("   " + l.strip()[:158]); hit += 1
    if not hit:
        print("   （无匹配行 ⇒ 原文尾部）")
        for l in lines[-4:]:
            print("   " + l.strip()[:158])
    for a in also:
        print("   " + a)


show("C G1 判词改名", rcC, outC, ["不通过", "认不出 1 条", "判定：", "控制组"])
for tag, rcS, outS, pre, real, why in [
    ("D ★G1 表外判词＋表内同红（预注册 G1 的形态）", rcD, outD, pD, (rcDr, hitsD, filesD, nD, lD), "future 新断言"),
    ("E G1 行号区间外（它两个控制组都没覆盖的分支）", rcE, outE, pE, (rcEr, hitsE, filesE, nE, lE), "P5 间接接收者"),
    ("F ★同包另一个 _test.go 里的红", rcF, outF, pF, (rcFr, hitsF, filesF, nF, lF), "P6 外文件的红"),
]:
    show(tag, rcS, outS, ["认不出", "判定：", "✓ M1", "✗ M1", "future", "间接接收者", "不适用"])
    r, hits, files, nlines, _ = real
    print(f"   [对照·前置] 未变异树 rc={pre[0]}、`_test.go:` 行 {pre[1]} 条（须 rc=0 且 0 条；非 0 的 ok 行不算红）")
    print(f"   [对照·真值] 手工变异后 go test（无 -v）rc={r}")
    print(f"      · 我的针命中：{hits if hits else '（无）'}")
    print(f"      · 出现过的 _test.go：{files}")
    print(f"      · 输出总行数 {nlines}（★ 含被 dump 的 Logf，**不等于**红行数）")
    print(f"      · 本探针要找的那条红（{why}）出现：{hits.get(why, 0)} 次")
show("P7 ★同行 Logf+Errorf（整行被标成日志 ⇒ 红被丢弃）", rcP7, outP7,
     ["P7", "认不出", "判定：", "✓ M2", "✗ M2"])
print(f"   [对照·前置] 未变异树 rc={pP7[0]}、`_test.go:` 行 {pP7[1]} 条")
print(f"   [对照·真值] 手工 M2 后 rc={rcP7r}、针命中 {hitsP7}、文件 {filesP7}")
show("G G3 反向守卫（两锚点改成相同）", rcG, outG, ["锚点", "重复", "判定：", "✗"])
show("H P3 锚点坏", rcH, outH, ["锚点", "SystemExit"])
print("   " + f"含「矩阵」：{'矩阵' in outH}｜含「判定：」：{'判定：' in outH}")

# ── I：我的尺子加词边界后复算
txt = (SRC / "mech" / "chain_test.go").read_text(encoding="utf-8")
loose = re.findall(r't\.(?:Errorf|Fatalf)\(\s*"', txt)
tight_lines = [i for i, l in enumerate(txt.splitlines(), 1)
               if re.search(r'\bt\.(?:Errorf|Fatalf)\(\s*"', l)]
fmt_lines = [i for i, l in enumerate(txt.splitlines(), 1)
             if re.search(r'fmt\.Errorf\(\s*"', l)]
print(f"\n===== I G2 我的尺子 =====")
print(f"   旧正则（无词边界）＝ {len(loose)} 条；加 \\bt\\. 后 ＝ {len(tight_lines)} 条")
print(f"   被误命的 fmt.Errorf 行 = {fmt_lines}（共 {len(fmt_lines)} 条）")
print(f"   两口径：调用处 {len(tight_lines)} ＝ 表内 5 ＋ 表外 {len(tight_lines) - 5}（**不许相加**）")

# ── J：G5 外部哈希
print(f"\n===== J G5 产品树只读（我自己算，${'不靠它的打印'}）=====")
diff = [k for k in H0 if H0[k] != H1.get(k)]
print(f"   跑前跑后逐文件哈希不同的：{diff if diff else '无'}（共 {len(H0)} 个文件）")
