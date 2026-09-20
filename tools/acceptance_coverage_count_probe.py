# -*- coding: utf-8 -*-
"""覆盖面计数探针（验收会话自用，只读产品代码）。

用途：把 F6 那一节做成**会红的检查**。它经历过一次自缚修正，两版都留在这里：

★ v1（2026-09-20 上午，**错**）：判「被测脚本印的数 == 探针自数的数（宽口径整文件 findall）」，
  并判「Σ(分行) == 印出的合计」。两个都错——被测方的谓词当时**没有声明**，拿两把尺子比大小
  就是 `61d85582`；合计当时也**没有声明口径**（只覆盖被判词表覆盖的那个文件）。是反向守卫
  （往一个文件里加一处调用点，看那一行动不动）当场把 v1 的结论推翻的。

★ v2（`1647e51` 起，本版）：被测方已把口径**写进输出**（窄＝`t.Errorf(`／`t.Fatalf(`；
  宽＝再加 `t.Fatal(`／`t.Error(`；整包合计 vs 表内文件分列并写明不许相加）⇒ 此时
  「同口径逐位比」才是合法判据。故本版判四条：
    1. 每个文件：印出的数 == 探针按**同一谓词（窄）**自数的数；不等判红；
    2. Σ(印出的分行) == 印出的**整包合计**；不等判红；
    3. 反向守卫：往一个文件里再加一处会红调用点 ⇒ **只它那一行**变，别的行不动；不动判红；
    4. 两棵树之间的差值恒定（＝印的确实是该文件的量，而不是别处的数）。
  口径一旦被声明，第 1 条就从「跨尺子比大小」变成「同尺子对账」。

用法：CHAIN_INDEP_PIN=<冻结副本> python tools/acceptance_coverage_count_probe.py
退出码：0 = 四条全成立；1 = 有任一条不成立（具名）。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "rios-sim" / "go.mod").exists())
PROD = ROOT / "rios-sim"
BASE = ROOT / "out" / "acceptance" / "coverage-count"

#: 探针的尺子。窄＝与被测方声明的谓词逐字同形（同口径才能逐位比）。
NARROW_CALL = re.compile(r"\bt\.(?:Errorf|Fatalf)\(")
WIDE_CALL = re.compile(r"\bt\.(?:Errorf|Fatalf|Fatal|Error)\(")
PER_FILE = re.compile(r"·\s*([\w./\\-]+\.go)\s*：判词调用处\s*(\d+)\s*条")
PKG_TOTAL = re.compile(r"整包合计[^\n]*?共\s*(\d+)\s*条")
COVERED_TOTAL = re.compile(r"判词表覆盖的文件内[^\n]*?共\s*(\d+)\s*条|判词表覆盖的文件内：判词调用处\s*(\d+)\s*条")
#: v1 时代的写法（无「整包合计」那一行）＝口径未声明 ⇒ 判为不适用，不判红。
LEGACY_TOTAL = re.compile(r"判词\*{0,2}调用处\*{0,2}共\s*(\d+)\s*条")


def true_counts(tree: Path) -> dict[str, int]:
    return {p.name: len(NARROW_CALL.findall(p.read_text(encoding="utf-8")))
            for p in sorted((tree / "mech").glob("*_test.go"))}


def make_tree(tag: str, extra_sentinel: bool) -> Path:
    dst = BASE / tag / "rios-sim"
    if dst.exists():
        shutil.rmtree(dst)
    (dst / "mech").mkdir(parents=True)
    shutil.copy2(PROD / "go.mod", dst / "go.mod")
    for p in (PROD / "mech").glob("*.go"):
        shutil.copy2(p, dst / "mech" / p.name)
    if extra_sentinel:
        f = dst / "mech" / "farmland_golden_test.go"
        t = f.read_text(encoding="utf-8")
        marker = "func TestFarmlandGolden(t *testing.T) {"
        assert marker in t, "夹具前提不成立：farmland_golden_test.go 里没有预期的测试函数签名"
        t = t.replace(marker, marker + '\n\tif false {\n\t\tt.Errorf("coverage probe sentinel")\n\t}', 1)
        f.write_text(t, encoding="utf-8")
    return dst


def run_frozen(pin: Path, tree: Path, tag: str) -> tuple[int, str]:
    spec = importlib.util.spec_from_file_location("cov_" + tag, pin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SRC = tree
    m.WORK = BASE / (tag + "-work") / "rios-sim"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            r = m.main()
    except SystemExit as e:
        r = e.code
    raw = buf.getvalue()
    (BASE / f"raw-cov-{tag}.log").write_text(raw, encoding="utf-8")
    rc = getattr(r, "rc", r)
    return (0 if rc is None else int(rc)), raw


def parse(raw: str) -> tuple[dict[str, int], int | None, int | None, bool]:
    rows = {m.group(1).split("/")[-1].split("\\")[-1]: int(m.group(2)) for m in PER_FILE.finditer(raw)}
    pkg = PKG_TOTAL.search(raw)
    covm = COVERED_TOTAL.search(raw)
    cov = None
    if covm:
        cov = int(covm.group(1) or covm.group(2))
    legacy = LEGACY_TOTAL.search(raw) is not None and pkg is None
    return (rows, int(pkg.group(1)) if pkg else None, cov, legacy)


def judge(tag: str, raw: str, tree: Path) -> tuple[list[str], dict[str, int]]:
    bad: list[str] = []
    printed, pkg, cov, legacy = parse(raw)
    truth = true_counts(tree)
    print(f"\n===== {tag} =====")
    print(f"   印出的分行：{printed}；印出的整包合计：{pkg}；表内文件合计：{cov}")
    print(f"   探针自数（窄口径，与声明同谓词）：{truth}")
    if not printed:
        return [f"{tag}：没有解析到任何分行计数 ⇒ 这一节没印（或印法变了）⇒ 判据无从成立"], printed
    for name, n in sorted(printed.items()):
        if name not in truth:
            bad.append(f"{tag}：印出的文件 `{name}` 在树里没有对应 *_test.go")
        elif n != truth[name]:
            bad.append(f"{tag}：`{name}` 印 {n} 条，同口径自数 **{truth[name]}** 条 ⇒ 该行的数不是该文件的")
    if pkg is None:
        if legacy:
            print("   ⚠ 没有「整包合计」那一行（旧写法）⇒ 合计口径未声明 ⇒ 第 2 条**不适用**，不判红")
        else:
            bad.append(f"{tag}：既没有「整包合计」也没有旧式合计行 ⇒ 这一节没有可对账的汇总")
    else:
        s = sum(printed.values())
        if s != pkg:
            bad.append(f"{tag}：Σ(分行) {s} ≠ 印出的整包合计 {pkg} ⇒ 分行漏了文件或漏了行")
        else:
            print(f"   ✓ Σ(分行) {s} == 整包合计 {pkg}")
    if cov is not None and pkg is not None and cov > pkg:
        bad.append(f"{tag}：表内文件合计 {cov} > 整包合计 {pkg} ⇒ 两个口径串了")
    for b in bad:
        print("   ✗ " + b)
    return bad, printed


def main() -> int:
    pin_s = os.environ.get("CHAIN_INDEP_PIN")
    if not pin_s:
        print("★ CHAIN_INDEP_PIN 未设 ⇒ 拒跑（本探针只审冻结副本，不审工作区）")
        return 1
    pin = Path(pin_s)
    if not pin.exists():
        print(f"★ 冻结副本不存在：{pin} ⇒ 拒跑（不把「找不到」读成通过）")
        return 1
    BASE.mkdir(parents=True, exist_ok=True)
    print(f"== 覆盖面计数探针 v2 · 被测脚本 {pin.name} · 树 {PROD} ==")

    bad: list[str] = []
    ctrl = make_tree("control", extra_sentinel=False)
    rc1, raw1 = run_frozen(pin, ctrl, "control")
    b1, p1 = judge("control", raw1, ctrl)
    bad += b1
    print(f"   （被测脚本在 control 树上 rc={rc1}；它的 rc 不是本探针的判据）")

    guard = make_tree("guard", extra_sentinel=True)
    rc2, raw2 = run_frozen(pin, guard, "guard")
    b2, p2 = judge("guard", raw2, guard)
    bad += b2
    print(f"   （被测脚本在 guard 树上 rc={rc2}）")

    t1, t2 = true_counts(ctrl), true_counts(guard)
    name = "farmland_golden_test.go"
    print("\n===== 反向守卫（第 3／4 条）=====")
    if name in p1 and name in p2:
        if p1[name] == p2[name]:
            bad.append(f"★ 反向守卫失败：往 `{name}` 里再加一处会红调用点，它那一行仍印 {p1[name]} 条 ⇒ "
                       f"这一节的数与该文件无关（不红 ⇒ 这条判据没有分辨力）")
        else:
            print(f"   ✓ 加了 1 处 ⇒ `{name}` 从 {p1[name]} 变 {p2[name]}（我自数 {t1.get(name)} → {t2.get(name)}）")
        moved = [k for k in p1 if p1[k] != p2.get(k)]
        if moved == [name]:
            print(f"   ✓ 只有它那一行动（其余 {len(p1) - 1} 个文件的行未动）⇒ 分行数逐文件独立")
        elif moved:
            bad.append(f"★ 加一处调用点却动了多行：{moved} ⇒ 分行之间不独立")
        d1, d2 = p1[name] - t1.get(name, 0), p2[name] - t2.get(name, 0)
        if d1 == d2 == 0:
            print("   ✓ 两棵树差值均 0 ⇒ 印的数与该文件的同口径真值**逐位相同**")
        else:
            bad.append(f"★ 差值不恒定或非零（control {d1:+d}、guard {d2:+d}）⇒ 印的不是该文件的同口径真值")
    else:
        bad.append(f"★ 反向守卫前提不成立：两棵树里都没解析到 `{name}` 那一行")

    print("\n== 判定：== " + ("四条全成立（逐文件同口径对账／整包对账／反向守卫／差值恒定）" if not bad
                             else f"**{len(bad)} 条不成立** ⇒ rc=1"))
    for b in bad:
        print("   ✗ " + b)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
