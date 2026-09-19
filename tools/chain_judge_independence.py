#!/usr/bin/env python3
r"""chain 判据的**独立性实测**：一个变异红几条。

★★★ 第一条纪律（验收 P2 探针后加，PM 转派）：
    **「认不出」必须自己会红，不能靠「恰好没有第二条」。**

前一版把「红了几条」按**判词前缀**归类，只认表内 5 条 ⇒ 表外的判词红了会被**静默丢掉**：
验收的 P2 探针（同块内加一条表外判词）实测 **`go test` 真红 2 行，本脚本报「红 1 条 ✓」、rc=0**
——矩阵漂亮、退出码 0，但那是**通道**漏了，不是读数对。**红行被丢掉且不留痕。**
现在：**按行号认语句种类**（`t.Errorf`／`t.Fatalf`＝判词，`t.Logf`＝日志），
**判词行凡是前缀不在表内的 ⇒ 具名打印 + rc=1**；行号落在任何已知调用区间之外 ⇒ 同样判失败（fail closed）。

★ 「一个改动红几条」＝独立性的判据（PM 提成通则 `msg-mu903tfp-g0`）：
红一条 ⇒ 独立信息；红两条 ⇒ 至少一条多余；红三条以上 ⇒ 同一判据的多份副本。

★ 本脚本自带的检查（不只是纪律）：
  · G1 双向：P2 形态（表外判词 ＋ 表内一条同时红）⇒ 必须 rc≠0 **且具名**；P1 形态（已认判词改名）⇒ 同样 rc≠0 具名
  · G3 锚点两两不同（否则改锚点会留下另一处）
  · G4 四个变异仍各恰好红 1 条、0 条认不出（**不许放宽**）
  · G5 产品树只读（跑前后逐文件 SHA256 相同）
  · **G6 红行的取证范围 ≥ 运行范围**：`-run Chain` 跑的是**整个包**，而旧版把红行的文件名
    写死成 `chain_test.go` ⇒ 同包另一个 `_test.go`（如 `mech/zz_probe_test.go`）里的红**看不见**，
    矩阵照样全绿（验收造树实测：真实 `rc=1`、两文件皆红，旧版报 `rc=0` 全绿）。
    现在正则 `^\s+(\S+_test\.go):(\d+):` **按文件**取语句种类；**非 `chain_test.go` 的红一律
    判「未认出」⇒ 具名 + rc≠0**（fail closed）。
  · **P7 同行两个调用**：`t.Logf(…); t.Errorf(…)` 同行时，按「行内第一个调用」标种类会把同行的红
    吞掉（验收探针 P7 实测旧版 `rc=0`，真值 `rc=1`）⇒ 种类按**集合**取、**「判词」优先于「日志」**。
    ★ 修法与 G6 **不是同一处**：G6 放宽的是**文件名**，P7 丢的是**行的种类** ⇒ G6 关不掉它。
  · **跨度自校验**：任一调用的括号跨度不许**跨过函数边界**（跨过 ⇒ 配平失控 ⇒ 整段被染错种类），
    且配平在**抠掉字面量**后的代码上算（消息里的括号不该参与配平）。
  · 环境自检：stdout 编不出 `✓`(U+2713) / `⇒`(U+21D2) 时**大声失败**并说明这是环境不是判据红
    （无编码约束的 str 流 ⇒ 该检查不适用，见 `console_check`）

    ★ **否证记录（验收构造、实测不成立，但性质必须留痕）**：曾猜「`Logf` 消息含未配平的 ASCII 左括号
      ⇒ 跨度外溢 ⇒ 后续行被标成日志」。**实测：外溢确实发生，但那个 `t.Errorf(` 自己的调用点更晚出现、
      把它自己那行标回「判词」** —— 因为旧写法 `kinds[k] = kind` 是**后写覆盖前写**。
      ⇒ ★ 旧实现的**性质＝标记顺序相关、后者胜**；**P7b 正是这条性质的反面**（Logf 在前就吞掉红）。
      ⇒ ★ 本版**故意去掉这个顺序依赖**：种类按**集合**取、「判词」优先，并把配平改为在**抠掉字面量**
      后的代码上算（`_strip_literals`）＋ 跨度不许跨函数边界（`spans_stay_inside_funcs` 当场红）。
      **不许把「依赖顺序」当地基用** —— 顺序一旦被重排，P7b 那类会以另一种形状回来。

用法：`python tools/chain_judge_independence.py`
"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "rios-sim"
WORK = ROOT / "out" / "backend2-b1" / "indep" / "rios-sim"
#: 判词表覆盖的**唯一**文件（＝本脚本的取证范围里唯一「认得」的文件）；
#: ★ 运行范围是**整个包**（`go test ./mech/ -run Chain`）⇒ 取证范围必须 ≥ 运行范围（G6）。
JUDGE_FILE = "chain_test.go"
TEST_REL = "mech/" + JUDGE_FILE

#: 断言的身份：表内 = (id, 判词前缀)。**表外不是「忽略」，是「具名 + rc=1」**。
ASSERTIONS: list[tuple[str, str]] = [
    ("断言1 实现过判据", "实现未过判据："),
    ("断言2 真实参数必须拒绝", "时必须返回 ErrJumpUndetermined"),
    ("断言3 合成反例被抓", "没抓住「"),
    ("断言5 读法判别器", "读法判别器红："),
    ("断言6 分岔点只有 n=3", "n=3 的 "),
]

#: 候选③ 的 n=2 写错（M2 与两个控制组共用一份原文）
M2_OLD = "\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}"
M2_NEW = "\t\t} else {\n\t\t\tseq[k-1] = base * scale * 1.05\n\t\t}"

#: (名字, 相对 rios-sim 的路径, 旧串, 新串, 预期红哪条断言)
#: ★ G3：验收指出 M1 与 M4 的旧串**逐字相同**（各 1 处命中、不违反 expect 自校验，
#:   但改锚点时只改一处会留下另一处）⇒ 两条锚点各自写长带上上下文，另有「两两不同」自校验兜底。
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    ("M1 实现 n=2 写错（×1.05）", "mech/chain.go",
     "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale, nil",
     "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale * 1.05, nil",
     "断言1 实现过判据"),
    ("M2 候选③ 的 n=2 写错（×1.05）", TEST_REL, M2_OLD, M2_NEW,
     "断言5 读法判别器"),
    ("M3 候选③ 的 n=3 变成与②同值", TEST_REL,
     "\t\tif k == 1 {\n\t\t\tseq[k-1] = base\n\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}",
     "\t\tif k == 1 {\n\t\t\tseq[k-1] = base\n\t\t} else if k == 3 {\n"
     "\t\t\tseq[k-1] = base * 0.5\n\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}",
     "断言6 分岔点只有 n=3"),
    ("M4 实现对 scale 不敏感", "mech/chain.go",
     "\tcase 2:\n\t\treturn scale, nil\n\tdefault:\n\t\treturn 0, ErrJumpUndetermined",
     "\tcase 2:\n\t\treturn 1.0, nil\n\tdefault:\n\t\treturn 0, ErrJumpUndetermined",
     "断言1 实现过判据"),
]

#: G6 控制组要往包里加的同包测试文件：**基线下绿、M1 下红**（验收造树的形态）。
PROBE_FILE = "mech/zz_probe_test.go"
PROBE_SRC = '''package mech

import "testing"

// G6 控制组：**同包另一个 _test.go 里的红**。
// 旧版把红行的文件名写死成 chain_test.go ⇒ 这一行的红**看不见**，
// 而运行范围是整个包（`go test ./mech/ -run Chain`）⇒ 矩阵照样全绿。
// 本文件在基线下绿（0.75 == 0.75）、在 M1（实现 n=2 ×1.05）下红 ⇒ 正是可构造的那扇门。
func TestChainProbe_ExtraFile(t *testing.T) {
	got, err := chainJumpScale(2, 0.75)
	if err != nil {
		t.Fatalf("两跳调用不该失败：%v", err)
	}
	if want := 0.75; got != want {
		t.Errorf("P6 外文件的红：chainJumpScale(2, 0.75) = %v，应为 %v", got, want)
	}
}
'''

#: 控制组：**期望脚本红**（这几条就是「认不出必须自己会红」的判据本身）
P2_ANCHOR = "\t\tif len(bad) > 0 {"
CONTROLS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("P2 同块内加一条**表外**判词（验收探针）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tt.Errorf(\"控制组 P2：表外判词（不在 ASSERTIONS 表内）\")\n" + P2_ANCHOR),
    ]),
    ("P1 把已认的判词**改名**（覆盖内消失）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, "读法判别器红：", "不通过："),
    ]),
    #: ★ P7：**同行两个调用、Logf 在前**——按「行内第一个调用」标种类就会把同行的 Errorf 红吞掉
    #:   （验收探针 P7 的形态；我上一版正是这个洞，它实测 rc=0 而我方真值是 rc=1）。
    ("P7 同行 Logf+Errorf（Logf 在前不许吞掉同行的红）", [
        (TEST_REL, M2_OLD, M2_NEW),
        (TEST_REL, P2_ANCHOR,
         "\t\tif seqs[2][1] != chainBase*chainScale { t.Logf(\"P7 同行日志\"); "
         "t.Errorf(\"P7 同行被吞的红：%v\", seqs[2][1]) }\n" + P2_ANCHOR),
    ]),
    #: ★ G6：**同包另一个 _test.go 的红**（验收造树实测：真实 rc=1、两文件皆红，旧版报 rc=0 全绿）
    ("G6 同包另一个 _test.go 的红（新增 zz_probe_test.go ＋ M1）", [
        ("mech/chain.go",
         "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale, nil",
         "\tcase 1:\n\t\treturn 1.0, nil\n\tcase 2:\n\t\treturn scale * 1.05, nil"),
        (PROBE_FILE, "", PROBE_SRC),
    ]),
]

RED_RE = re.compile(r"^\s+(\S+_test\.go):(\d+):\s?(.*)$")
CALL_RE = re.compile(r"\bt\.(Errorf|Fatalf|Logf)\(")
FUNC_RE = re.compile(r"^func\s+(\w+)\(")
#: 验收 P4 的口径：`t.Errorf/Fatalf(` 后面紧跟**单行首参字面量**
MSG_RE = re.compile(r't\.(?:Errorf|Fatalf)\(\s*"((?:[^"\\]|\\.)*)"')
WRAP_RE = re.compile(r"append\(bad,")
#: `fmt.Errorf`——注意：验收 P4 的正则 `t\.(?:Errorf|Fatalf)\(` 会**子串命中**它（`fm`＋`t.Errorf`），
#: 于是它把 helper 的 4 条返回文案也数成「判词调用处」。本脚本用 `\bt\.` ⇒ 不命中。
FMT_RE = re.compile(r"\bfmt\.Errorf\(")
#: 包内所有测试文件（**G6：运行范围是整个包，取证范围必须 ≥ 它**）
TEST_GLOB = "*_test.go"


def console_check() -> int:
    """环境自检：控制台编不出判据里的记号就**大声失败**，并说清它是环境不是判据红。

    ★ 现场（验收字符级更正）：GBK 控制台**先卡住的是 `✓`(U+2713)**，不是 `⇒`(U+21D2)
    —— 类别对（GBK 会让判据假红），字符别差一个。

    ★★ 本检查自己踩过一次假红（验收探针用 `contextlib.redirect_stdout(StringIO)`）：
    `StringIO` **没有** `encoding` 属性 ⇒ 取默认 "ascii" ⇒ 把「无编码约束的 str 流」判成 ascii，
    于是**每一次被重定向的调用都假红**、真读数一条都印不出来。
    修法：`encoding is None`（str 流）⇒ 这条检查**不适用，直接放行**；只有真有编码的文本流才验。
    """
    enc = getattr(sys.stdout, "encoding", None)
    if enc is None:
        return 0                      #: str 流（StringIO 之类）⇒ 编不出字符这件事不存在
    try:
        "✓ ⇒ 「」".encode(enc)
    except (UnicodeEncodeError, LookupError):
        print(f"[ENV] stdout 编码 = {enc}，编不出 U+2713(✓) / U+21D2(⇒) 这类记号。")
        print("[ENV] 这是**环境**不是判据红（同族 06c2d722：脚本红了≠判据红了）。")
        print("[ENV] 处置：设 PYTHONIOENCODING=utf-8 后重跑。")
        return 1
    return 0


def tree_hashes() -> dict[str, str]:
    """G5：产品树里**全部**文件的 SHA256（跑前跑后各取一次）。

    ★ 面5（PM 转派）：旧版只哈希 7 个文件（`go.mod` ＋ `mech/*.go`），而 `rios-sim` 下共 34 个
      ⇒ **哈希范围窄于结论范围**。现在写全树：范围 ≥ 结论，不必再逐个声明「其余为什么不可能被写」。
    """
    files = sorted(p for p in SRC.rglob("*") if p.is_file())
    return {str(p.relative_to(SRC)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


def git_evidence() -> tuple[str, str]:
    """脚本**自己手里**的 git 证据（三态：干净／脏／**本树不在 git 索引里 ⇒ 不适用**）。

    ★ 为什么要它：上一轮我说「产品树未变」用的是**外部证据**（别人跑的 `git status`），
      脚本自己手里没有全路径证据 ⇒ 换成别人跑、或树是拷贝出来的，那句话就没人能复核。
    ★ 为什么要有第三态：验收的探针把 `SRC` 指到 `out/...` 的**拷贝树**（`out/` 被 gitignore）
      ⇒ 那里的 `git status` **必然**是空的 ⇒ 若把它读成「产品树干净」就是**假绿**。
      故先问「这棵树在不在 git 索引里」，不在就明说**不适用**，不许当成通过。
    """
    rel = str(SRC.relative_to(ROOT)) if SRC.is_relative_to(ROOT) else None
    if rel is None:
        return "不适用", f"SRC 不在本仓库内（{SRC}）⇒ git 证据对本树无意义"
    probe = subprocess.run(["git", "ls-files", "--", f"{rel}/mech/chain.go"],
                           cwd=str(ROOT), capture_output=True)
    if not (probe.stdout or b"").strip():
        return "不适用", f"{rel} 不在 git 索引里（拷贝树/被忽略）⇒ git 证据对本树无意义"
    st = subprocess.run(["git", "status", "--short", "--", rel], cwd=str(ROOT), capture_output=True)
    dirty = (st.stdout or b"").decode("utf-8", "replace").strip()
    if dirty:
        return "脏", dirty
    return "干净", f"git status --short -- {rel} 空"


def stage() -> None:
    """把包搭到工作目录（mech 包自含，故只需 go.mod ＋ mech/*.go）。**产品树只读。**"""
    if WORK.exists():
        shutil.rmtree(WORK)
    (WORK / "mech").mkdir(parents=True)
    shutil.copy2(SRC / "go.mod", WORK / "go.mod")
    for p in (SRC / "mech").glob("*.go"):
        shutil.copy2(p, WORK / "mech" / p.name)


def go_test() -> tuple[int, str]:
    p = subprocess.run(["go", "test", "./mech/", "-run", "Chain", "-count=1", "-v"],
                       cwd=str(WORK), capture_output=True)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def _strip_literals(ln: str) -> str:
    """把字符串/字符字面量与行注释抠掉——**括号配平只能在剩下的代码上算**。

    ★ 为什么必须抠：若判词消息里出现一个**未配平的 ASCII 左括号**，整行的配平就永远回不到 0，
      「调用跨度」会一直吞到文件尾 ⇒ 它后面的行全被染成同一种类 ⇒ **日志能吞掉判词**
      （与 P7 同一族：红被丢弃）。验收的探针自己踩过这个形态（它源码注释里写了）。
    """
    out: list[str] = []
    i, n = 0, len(ln)
    while i < n:
        c = ln[i]
        if c in "\"'`":
            quote = c
            i += 1
            while i < n:
                if ln[i] == "\\" and quote != "`":
                    i += 2
                    continue
                if ln[i] == quote:
                    i += 1
                    break
                i += 1
            continue
        if c == "/" and i + 1 < n and ln[i + 1] == "/":
            break
        out.append(c)
        i += 1
    return "".join(out)


def _scan_one(path: Path) -> tuple[dict[int, str], dict[int, str], dict[int, str], list[tuple[int, int, str]]]:
    """扫一个测试文件：给行号标语句种类。

    ★ 为什么按行号而不是按消息形状：`-v` 输出里 `t.Logf` 与 `t.Errorf` 长得**一模一样**
    （都是 `    <file>_test.go:NN: 正文`），按形状分不出「日志」与「判词」；但**行号**能
    ——它指向发出该消息的语句。
    ★★ **一行可以有多个调用**（P7：`t.Logf(…); t.Errorf(…)` 同行）⇒ 种类按**集合**取，
      **「判词」优先于「日志」**：Logf 在前不许把同行的 Errorf 吞掉（吞掉就是红被丢弃）。
    ★ 已知区间**不是手写的表**：它是每次运行前从**被测文件现扫**出来的（扫描器与判词表是两个来源）。
    ★ 括号配平在**抠掉字面量**后的代码上算（见 `_strip_literals`）。

    返回 (全部行号→种类, 调用首行→种类, 函数首行→函数名, 每处调用的跨度)。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    kinds: dict[int, str] = {}
    starts: dict[int, str] = {}
    funcs: dict[int, str] = {}
    spans: list[tuple[int, int, str]] = []
    for i, ln in enumerate(lines, 1):
        fm = FUNC_RE.match(ln)
        if fm:
            funcs[i] = fm.group(1)
        found = list(CALL_RE.finditer(ln))
        if not found:
            continue
        here = {"日志" if m.group(1) == "Logf" else "判词" for m in found}
        line_kind = "判词" if "判词" in here else "日志"     #: ★ 判词优先（fail closed 方向）
        starts[i] = line_kind
        code = _strip_literals(ln)
        depth = code.count("(") - code.count(")")
        j = i
        while depth > 0 and j < len(lines):
            j += 1
            nxt = _strip_literals(lines[j - 1])
            depth += nxt.count("(") - nxt.count(")")
        spans.append((i, j, line_kind))
        for k in range(i, j + 1):
            if kinds.get(k) == "判词" or line_kind == "判词":
                kinds[k] = "判词"
            else:
                kinds.setdefault(k, "日志")
    return kinds, starts, funcs, spans


def scan_package() -> dict[str, tuple[dict[int, str], dict[int, str], dict[int, str], list[tuple[int, int, str]]]]:
    """扫**包内全部** `*_test.go`（G6：运行范围是整个包 ⇒ 不能只扫一个文件）。"""
    return {p.name: _scan_one(p) for p in sorted((WORK / "mech").glob(TEST_GLOB))}


def spans_stay_inside_funcs(per: dict) -> list[str]:
    """结构自校验：**任一调用的跨度不许跨过函数边界**（跨过 ⇒ 括号配平失控 ⇒ 整段被染错种类）。

    ★ 这条是 `_strip_literals` 的兜底：即便将来某种形态又让配平跑偏，也要**当场大声失败**，
      而不是让日志悄悄吞掉判词（那正是 P2/P7 家族的静默）。
    """
    bad: list[str] = []
    for fname, (_k, _s, funcs, spans) in per.items():
        fstarts = sorted(funcs)
        for a, b, _kind in spans:
            for f in fstarts:
                if a < f <= b:
                    bad.append(f"{fname}:{a}-{b} 的调用跨度跨过了 {funcs[f]}（第 {f} 行）"
                               f"⇒ 括号配平失控，种类标注不可信")
                    break
    return bad


def enclosing(funcs: dict[int, str], n: int) -> str:
    cand = [k for k in funcs if k <= n]
    return funcs[max(cand)] if cand else "（函数外）"


def coverage(per: dict) -> None:
    """G2 ＋ G6：把「不覆盖」的东西**显式印出来并说清为什么可以不覆盖**（理由由结构给出）。

    G6 加的一层：**运行范围是整个包**，故先把包内每个 `*_test.go` 列出来，标出哪个是判词表覆盖的，
    其余文件里**即便有判词也是未覆盖** ⇒ 它们一旦红了就是「未认出」⇒ 具名 + rc=1。
    """
    print(f"== 归类器覆盖面（现算，包内 {TEST_GLOB}；判词表只覆盖 {JUDGE_FILE}）==")
    for fname, (_k, st, _f, _sp) in per.items():
        n_judge = sum(1 for _n, k in st.items() if k == "判词")
        tag = "判词表覆盖" if fname == JUDGE_FILE else "**未覆盖**（红了 ⇒ 未认出 ⇒ rc=1）"
        print(f"   · {fname}：判词调用处 {n_judge} 条 —— {tag}")

    jf = per.get(JUDGE_FILE)
    if jf is None:
        print(f"   ✗ 判词表覆盖的文件 {JUDGE_FILE} 不在包里 ⇒ 判词表已失效")
        return
    lines = (WORK / "mech" / JUDGE_FILE).read_text(encoding="utf-8").splitlines()
    _kinds, starts, funcs, _spans = jf
    judge_starts = [(n, k) for n, k in sorted(starts.items()) if k == "判词"]
    inside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
              if any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    outside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
               if not any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    wrapped = [(i, lines[i - 1].strip()) for i, ln in enumerate(lines, 1) if WRAP_RE.search(ln)]
    msg_lits = MSG_RE.findall("\n".join(lines))
    n_fmt = sum(1 for ln in lines if FMT_RE.search(ln))

    print(f"   判词**调用处**共 {len(judge_starts)} 条：表内能认 {len(inside)} 条、**表外 {len(outside)} 条**")
    for n, text in outside:
        print(f"     ⊘ L{n}  {text[:66]}")
        print(f"        理由（结构给出）：属于 {enclosing(funcs, n)}；本轮 4 个变异只触碰 "
              f"chainJumpScale 与三个读法生成器 ⇒ 没有变异经过它。"
              f"**它一旦红了 ⇒ 本脚本 rc=1 并具名**（不是忽略）。")
    print(f"   另有 {len(wrapped)} 条只作为 `bad` 的文案出现（`append(bad,…)`）：")
    for n, text in wrapped:
        print(f"     ⊘ L{n}  {text[:66]}")
    print("        理由（结构给出）：它**不自己发消息**，只经 `joinLines(bad)` 随断言5 那一行一起打印 "
          "⇒ 结构上不能独立红。")
    print(f"   口径对账（两套分母**不许相加**）：本脚本按**调用处**数 ＝ {len(judge_starts)}；"
          f"验收 P4 按正则 `t\\.(?:Errorf|Fatalf)\\(` 数 ＝ {len(msg_lits)}"
          f" ＝ {len(judge_starts)} ＋ {n_fmt} 条 **`fmt.Errorf`**。")
    print(f"   ★ 机理（现算，不是我的叙述）：那条正则**子串命中**了 `fmt.Errorf`（`fm`＋`t.Errorf`），"
          f"多出的 {n_fmt} 条正是 helper `assertDecayFirstTwo` 的返回文案；加词边界 `\\bt\\.` 即只数 "
          f"{len(judge_starts)}。**两个数不同义，不许相加。**")


def classify(out: str, per: dict[str, tuple[dict[int, str], dict[int, str], dict[int, str]]]
             ) -> tuple[list[str], list[str]]:
    """把红行分成 (表内认得的断言 id, 表外/认不出的红行原文)。**认不出的一律进第二列。**

    ★★ G6：**取证范围必须 ≥ 运行范围**。`-run Chain` 跑的是整个包 ⇒ 出现在输出里的每个
    `*_test.go` 都要看；**非 `JUDGE_FILE` 的红行一律算「未认出」**（具名 + rc≠0），
    因为判词表**只**覆盖 `JUDGE_FILE` —— 「别的文件里的红」与「认不出的判词」是同一族的漏。
    """
    known: list[str] = []
    unknown: list[str] = []
    for ln in out.splitlines():
        m = RED_RE.match(ln)
        if not m:
            continue
        fname, n, text = m.group(1), int(m.group(2)), m.group(3).strip()
        if fname != JUDGE_FILE:
            unknown.append(f"{fname}:{n}: {text}（不在判词表覆盖的文件内 ⇒ 取证范围必须 ≥ 运行范围）")
            continue
        kinds = per.get(fname, ({}, {}, {}))[0]
        kind = kinds.get(n)
        if kind == "日志":
            continue                     #: 被认出来了，只是它不是判词 ⇒ 不算红
        if kind is None:
            unknown.append(f"{fname}:{n}: {text}（行号不在任何已知调用区间内 ⇒ 认不出）")
            continue
        hit = [aid for aid, p in ASSERTIONS if p in text]
        if hit:
            known.extend(hit)
        else:
            unknown.append(f"{fname}:{n}: {text}（表外判词 ⇒ 归类器认不出）")
    return known, unknown


def mutate(pairs: list[tuple[str, str, str]]) -> None:
    """施加**变异**；每处替换自带 expect 自校验，替换不到就退出（失败不留一份好看的矩阵）。

    `old == ""` 表示**新建文件**（内容为新串）——G6 控制组要往包里加一个同包 `_test.go`。
    """
    for rel, old, new in pairs:
        f = WORK / rel
        if old == "":
            if f.exists():
                raise SystemExit(f"✗ 变异要新建 {rel}，但它已存在 ⇒ 读数无效")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new, encoding="utf-8")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n != 1:
            raise SystemExit(f"✗ 变异锚点在 {rel} 里出现 {n} 次（应为 1）⇒ 变异没到达目标那行，读数无效")
        f.write_text(text.replace(old, new, 1), encoding="utf-8")


def apply_or_skip(pairs: list[tuple[str, str, str]]) -> list[str]:
    """施加**控制组**改动，并区分三种情形（第三种是外部树造成的，必须区别于「没做成」）：

    · 锚点在 ⇒ 替换，正常施加；
    · 锚点不在、但目标改动**已在树里** ⇒ 返回「不适用（外部树已施加该改动）」；
      ★ 验收的 P1 树就是这种：它先把判词改名成「读法判别器不通过：」，
      我的 P1 控制组再找「读法判别器红：」自然 0 命中——**这是「不适用」，不是「锚点坏了」**；
    · 两者都不在 ⇒ 仍**当场退出**（真锚点错误不许被当成不适用吞掉）。

    `old == ""`（新建文件）同理：文件已在且内容一致 ⇒ 不适用；内容不同 ⇒ 当场退出。
    """
    skipped: list[str] = []
    for rel, old, new in pairs:
        f = WORK / rel
        if old == "":
            if f.exists():
                if f.read_text(encoding="utf-8") == new:
                    skipped.append(f"{rel}：该文件已在树里且内容一致（外部施加）⇒ 本控制组**不适用**")
                    continue
                raise SystemExit(f"✗ 控制组要新建 {rel}，但它已存在且内容不同 ⇒ 锚点坏了，读数无效")
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(new, encoding="utf-8")
            continue
        text = f.read_text(encoding="utf-8")
        n = text.count(old)
        if n == 1:
            f.write_text(text.replace(old, new, 1), encoding="utf-8")
            continue
        if n == 0 and new in text:
            skipped.append(f"{rel}：目标改动已在树里（外部施加）⇒ 本控制组**不适用**")
            continue
        raise SystemExit(f"✗ 控制组锚点在 {rel} 里出现 {n} 次且目标改动不在 ⇒ 锚点坏了，读数无效")
    return skipped


def anchors_are_distinct() -> list[str]:
    """G3 自校验：**变异之间**旧串两两不同（否则改一处会留下另一处，验收探针第一版就踩了这个）。

    ★ 控制组**故意**复用 M2 的锚点（P1/P2 的定义就是「在 M2 条件下触发」）⇒ 不参与这条检查；
      控制组自身的检查是「**同一次运行内**各锚点不重复」。
    """
    bad: list[str] = []
    olds = [m[2] for m in MUTATIONS]
    dup = {o for o in olds if olds.count(o) > 1}
    for o in dup:
        bad.append(f"变异之间旧串重复（2 处）：{o[:60]!r}")
    for name, pairs in CONTROLS:
        co = [p[1] for p in pairs]
        if len(set(co)) != len(co):
            bad.append(f"控制组「{name}」内部锚点重复")
    return bad


def run_once(pairs: list[tuple[str, str, str]], *, control: bool = False) -> tuple[int, list[str], list[str], list[str]]:
    stage()
    skipped: list[str] = []
    if pairs:
        skipped = apply_or_skip(pairs) if control else (mutate(pairs), [])[1]
    per = scan_package()
    rc, out = go_test()
    known, unknown = classify(out, per)
    return rc, known, unknown, skipped


def main() -> int:
    if console_check():
        return 1
    before = tree_hashes()
    print(f"== 工作副本：{WORK.relative_to(ROOT) if WORK.is_relative_to(ROOT) else WORK}"
          f"（产品树只读：{SRC}）==")
    g3 = anchors_are_distinct()
    if g3:
        print("✗ G3 自校验失败（改锚点会留下另一处）：")
        for b in g3:
            print(f"      ↳ {b}")
        return 1
    rc, known, unknown, _sk = run_once([])
    per = scan_package()
    sp = spans_stay_inside_funcs(per)
    if sp:
        print("✗ 结构自校验失败（调用跨度跨过函数边界 ⇒ 括号配平失控 ⇒ 种类标注不可信）：")
        for b in sp:
            print(f"      ↳ {b}")
        return 1
    coverage(per)
    print(f"== 基线：rc={rc}、表内红 {len(known)} 条 {known}、认不出 {len(unknown)} 条 ==")
    for u in unknown:
        print(f"      ↳ {u}")
    if rc != 0 or known or unknown:
        print("✗ 基线不是全绿 ⇒ 后面的矩阵无意义")
        return 1

    ok = True
    #: ★ 矩阵**先算后印**：任何一步异常退出（如锚点找不到）都不会留下一份「看着正常」的矩阵。
    #:   验收 P3 的判据就是这条（旧版先印表头再跑 ⇒ 失败时表头已落地 ⇒ 检查读成「印了矩阵」）。
    rows: list[str] = []
    for name, rel, old, new, expect in MUTATIONS:
        rc, known, unknown, _sk = run_once([(rel, old, new)])
        #: 面4（PM 转派）：`rc != 0` 免费且严格更强——一个变异若连 go test 都没弄红，这一行不该算过。
        #: ★ 但它**关不掉静默**：P7b 那次的 rc 本来就是 1，缺的是「红行总数」的第二个来源（PM 已登记）。
        good = (rc != 0 and len(known) == 1 and not unknown and known[0] == expect)
        ok &= good
        rows.append(f"{'✓' if good else '✗'} {name}：rc={rc}、表内红 {len(known)} 条 {known}、"
                    f"认不出 {len(unknown)} 条（预期只红 {expect}）")
        for u in unknown:
            rows.append(f"      ↳ {u}")

    ctrl_rows: list[str] = []
    n_skipped = 0
    for name, pairs in CONTROLS:
        rc, known, unknown, skipped = run_once(pairs, control=True)
        n_skipped += len(skipped)
        good = bool(unknown) and rc != 0
        if skipped:
            #: ★ 「不适用」**不算通过**：控制组没跑过，通道证明就不完整 ⇒ 不许靠它变绿（fail closed）
            good = False
        ok &= good
        ctrl_rows.append(f"{'✓' if good else ('⊘' if skipped else '✗')} {name}：rc={rc}、"
                         f"表内红 {len(known)} 条、认不出 {len(unknown)} 条")
        for s in skipped:
            ctrl_rows.append(f"      ⊘ 不适用：{s} ⇒ **本树上通道证明不完整**（既不算通过、也不许因此变绿）")
        for u in unknown:
            ctrl_rows.append(f"      ↳ 具名：{u}")
        if not unknown and not skipped:
            ctrl_rows.append("      ↳ ✗ 没认出的红行没被报出来 ⇒ 「认不出」不会自己红（正是要防的静默）")

    print("== 变异矩阵（G4：每个最小变异**必须恰好红 1 条表内断言、且 0 条认不出**）==")
    for r in rows:
        print(r)
    print("== 控制组（G1/G6：**期望脚本红**——认不出、或别的文件里的红，都必须自己会红）==")
    for r in ctrl_rows:
        print(r)

    #: 面2（PM 转派）：对称于表外的 ⊘ 栏——把「**本轮零变异经过**」的**表内**断言也印出来。
    #: ★ 只印不判（PM 明确：做成硬判据「每个表内断言至少被一个变异经过」会要求补 2 个变异，
    #:   属另一件事；今天 5 条表内断言只经过 3 条 ⇒ 断言2／断言3 零变异经过）。
    exercised = {m[4] for m in MUTATIONS}
    idle = [aid for aid, _p in ASSERTIONS if aid not in exercised]
    print(f"== 变异覆盖到的表内断言：{len(exercised)}/{len(ASSERTIONS)}"
          f"（零变异经过的：{'、'.join(idle) if idle else '无'}）[只印不判，硬判据已由 PM 登记] ==")

    after = tree_hashes()
    same = before == after
    ok &= same
    print(f"== G5 产品树只读：{'✓ 逐文件 SHA256 跑前跑后相同' if same else '✗ 被改动了！'}"
          f"（**全树 {len(before)} 个文件**）==")
    if not same:
        for k in sorted(set(before) | set(after)):
            if before.get(k) != after.get(k):
                print(f"      ↳ {k}: {before.get(k)} → {after.get(k)}")
    g_state, g_text = git_evidence()
    print(f"== G5 脚本自带的 git 证据：{g_state} —— {g_text} ==")
    if g_state == "脏":
        ok = False

    print()
    if ok:
        print("== 判定：4/4 变异各恰红 1 条表内断言、4/4 控制组都能让脚本红并具名、产品树只读 "
              "⇒ 通道与矩阵都成立 ==")
    else:
        print("== 判定：✗ 有变异红 ≠1 条，或有「认不出的红行」没被具名，或控制组不适用，"
              "或产品树被写 ⇒ 判失败 ==")
    if n_skipped:
        print(f"   ★ 另有 {n_skipped} 处控制组「不适用」（外部树已施加该改动）⇒ 本树上通道证明不完整")
    print("★ 纪律：「认不出」必须自己会红，不能靠「恰好没有第二条」")
    print("★ 纪律：红行的取证范围必须 ≥ 运行范围（`-run` 跑几个文件，就得看几个文件）")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
