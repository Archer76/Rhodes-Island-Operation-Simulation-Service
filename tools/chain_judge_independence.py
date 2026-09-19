#!/usr/bin/env python3
"""chain 判据的**独立性实测**：一个变异红几条。

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
  · 环境自检：stdout 编不出 `✓`(U+2713) / `⇒`(U+21D2) 时**大声失败**并说明这是环境不是判据红

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
TEST_REL = "mech/chain_test.go"

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

#: 控制组：**期望脚本红**（这两条就是「认不出必须自己会红」的判据本身）
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
]

RED_RE = re.compile(r"^\s+chain_test\.go:(\d+):\s?(.*)$")
CALL_RE = re.compile(r"\bt\.(Errorf|Fatalf|Logf)\(")
FUNC_RE = re.compile(r"^func\s+(\w+)\(")
#: 验收 P4 的口径：`t.Errorf/Fatalf(` 后面紧跟**单行首参字面量**
MSG_RE = re.compile(r't\.(?:Errorf|Fatalf)\(\s*"((?:[^"\\]|\\.)*)"')
WRAP_RE = re.compile(r"append\(bad,")
#: `fmt.Errorf`——注意：验收 P4 的正则 `t\.(?:Errorf|Fatalf)\(` 会**子串命中**它（`fm`＋`t.Errorf`），
#: 于是它把 helper 的 4 条返回文案也数成「判词调用处」。本脚本用 `\bt\.` ⇒ 不命中。
FMT_RE = re.compile(r"\bfmt\.Errorf\(")


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
    """G5：产品树里本脚本会读到的那几份文件的 SHA256（跑前跑后各取一次）。"""
    files = [SRC / "go.mod"] + sorted((SRC / "mech").glob("*.go"))
    return {str(p.relative_to(SRC)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}


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


def scan_calls() -> tuple[dict[int, str], dict[int, str], dict[int, str]]:
    """扫描**副本**里的 `chain_test.go`，给行号标语句种类。

    ★ 为什么按行号而不是按消息形状：`-v` 输出里 `t.Logf` 与 `t.Errorf` 长得**一模一样**
    （都是 `    chain_test.go:NN: 正文`），按形状分不出「日志」与「判词」；但**行号**能
    ——它指向发出该消息的语句。多行调用按括号配平把整段区间都标上
    （Go 可能报首行也可能报收尾行，两种都认）。

    返回 (全部行号→种类, 调用首行→种类, 函数首行→函数名)。
    """
    lines = (WORK / TEST_REL).read_text(encoding="utf-8").splitlines()
    kinds: dict[int, str] = {}
    starts: dict[int, str] = {}
    funcs: dict[int, str] = {}
    for i, ln in enumerate(lines, 1):
        fm = FUNC_RE.match(ln)
        if fm:
            funcs[i] = fm.group(1)
        m = CALL_RE.search(ln)
        if not m:
            continue
        kind = "日志" if m.group(1) == "Logf" else "判词"
        starts[i] = kind
        depth = ln.count("(") - ln.count(")")
        j = i
        while depth > 0 and j < len(lines):
            j += 1
            depth += lines[j - 1].count("(") - lines[j - 1].count(")")
        for k in range(i, j + 1):
            kinds[k] = kind
    return kinds, starts, funcs


def enclosing(funcs: dict[int, str], n: int) -> str:
    cand = [k for k in funcs if k <= n]
    return funcs[max(cand)] if cand else "（函数外）"


def coverage() -> None:
    """G2：把「不覆盖」的判词**显式印出来并说清为什么可以不覆盖**（理由由结构给出）。"""
    lines = (WORK / TEST_REL).read_text(encoding="utf-8").splitlines()
    _kinds, starts, funcs = scan_calls()
    judge_starts = [(n, k) for n, k in sorted(starts.items()) if k == "判词"]
    inside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
              if any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    outside = [(n, lines[n - 1].strip()) for n, _k in judge_starts
               if not any(p in lines[n - 1] for _i, p in ASSERTIONS)]
    wrapped = [(i, lines[i - 1].strip()) for i, ln in enumerate(lines, 1) if WRAP_RE.search(ln)]
    msg_lits = MSG_RE.findall("\n".join(lines))
    n_fmt = sum(1 for ln in lines if FMT_RE.search(ln))

    print(f"== 归类器覆盖面（现算 {TEST_REL}）==")
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


def classify(out: str, kinds: dict[int, str]) -> tuple[list[str], list[str]]:
    """把红行分成 (表内认得的断言 id, 表外/认不出的红行原文)。**认不出的一律进第二列。**"""
    known: list[str] = []
    unknown: list[str] = []
    for ln in out.splitlines():
        m = RED_RE.match(ln)
        if not m:
            continue
        n, text = int(m.group(1)), m.group(2).strip()
        kind = kinds.get(n)
        if kind == "日志":
            continue                     #: 被认出来了，只是它不是判词 ⇒ 不算红
        if kind is None:
            unknown.append(f"chain_test.go:{n}: {text}（行号不在任何已知调用区间内 ⇒ 认不出）")
            continue
        hit = [aid for aid, p in ASSERTIONS if p in text]
        if hit:
            known.extend(hit)
        else:
            unknown.append(f"chain_test.go:{n}: {text}（表外判词 ⇒ 归类器认不出）")
    return known, unknown


def mutate(pairs: list[tuple[str, str, str]]) -> None:
    """施加**变异**；每处替换自带 expect 自校验，替换不到就退出（失败不留一份好看的矩阵）。"""
    for rel, old, new in pairs:
        f = WORK / rel
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
    """
    skipped: list[str] = []
    for rel, old, new in pairs:
        f = WORK / rel
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
    kinds, _s, _f = scan_calls()
    rc, out = go_test()
    known, unknown = classify(out, kinds)
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
    coverage()
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
        good = (len(known) == 1 and not unknown and known[0] == expect)
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
    print("== 控制组（G1：**期望脚本红**——认不出必须自己会红）==")
    for r in ctrl_rows:
        print(r)

    after = tree_hashes()
    same = before == after
    ok &= same
    print(f"== G5 产品树只读：{'✓ 逐文件 SHA256 跑前跑后相同' if same else '✗ 被改动了！'}"
          f"（{len(before)} 个文件）==")
    if not same:
        for k in sorted(set(before) | set(after)):
            if before.get(k) != after.get(k):
                print(f"      ↳ {k}: {before.get(k)} → {after.get(k)}")

    print()
    if ok:
        print("== 判定：4/4 变异各恰红 1 条表内断言、2/2 控制组都能让脚本红并具名、产品树只读 "
              "⇒ 通道与矩阵都成立 ==")
    else:
        print("== 判定：✗ 有变异红 ≠1 条，或有「认不出的红行」没被具名，或控制组不适用，"
              "或产品树被写 ⇒ 判失败 ==")
    if n_skipped:
        print(f"   ★ 另有 {n_skipped} 处控制组「不适用」（外部树已施加该改动）⇒ 本树上通道证明不完整")
    print("★ 纪律：「认不出」必须自己会红，不能靠「恰好没有第二条」")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
