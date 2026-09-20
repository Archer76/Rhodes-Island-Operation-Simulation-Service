"""验收探针：**修法自己带来的新面**（PM 复验派单的加问 ①②③）。一个进程一个用例。

差分法——不引用被测脚本的自陈，用**注入前／后同一变异下的读数差**说话：

* **faceA（问①「判词优先于日志」的反面）**：一行里 `t.Logf` 在前、`t.Errorf` 在后，而 **Logf 的正文以表内断言1 的前缀开头**。
  该行种类＝判词 ⇒ Logf 的**日志文本**被归给这条判词行 ⇒ 若它进了**表内计数**，M2 那行会多出一条「断言1」。
  ★ 隔离手法：同行的 Errorf 故意用**表外**文案（它只能进「认不出」栏）⇒ 多出来的表内红**只可能**来自那行日志文本。
* **faceB（问②`spans_stay_inside_funcs` 会不会误伤合法代码）**：合法的多行调用、实参含匿名函数字面量，放进**死代码**（`if false`）
  ⇒ 不产生任何红 ⇒ 若守卫误伤，读数会与对照**不同**；不误伤则四个变异行逐行相同、且不出现「跨过」。
* **faceC（问③`_strip_literals` 会不会把真问题换成假绿）**：多行调用的实参里放一个**块注释** `/* ( */`
  ——`_strip_literals` 只处理 `"`/`'`/反引号 与 `//` 行注释，**不处理 `/* */`** ⇒ 该行的 `(` 仍参与配平 ⇒ 跨度失控。
  判据：它**大声失败（rc≠0 且出现「跨过」）** ⇒ 不是假绿；若静默绿 ⇒ 才是被换成假绿。

用法：`set CHAIN_INDEP_PIN=<冻结副本>` 后 `python tools/acceptance_scope_faces_probe.py <control|faceA|faceB|faceC>`。
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p / "rios-sim" / "go.mod").exists())
ORIG = (Path(os.environ["CHAIN_INDEP_PIN"]) if os.environ.get("CHAIN_INDEP_PIN")
        else ROOT / "tools" / "chain_judge_independence.py")
SRC_PROD = ROOT / "rios-sim"
BASE = ROOT / "out" / "acceptance" / "scope-faces"
P2_ANCHOR = "\t\tif len(bad) > 0 {"

CASES = {
    "control": None,
    #: 问①：同行 Logf（正文＝表内断言1 前缀）＋ Errorf（表外文案）
    "faceA": ('\t\tif seqs[2][1] != chainBase*chainScale { '
              't.Logf("实现未过判据：自陈日志 %v", seqs[2][1]); '
              't.Errorf("验收面A 表外红：%v", seqs[2][1]) }\n'),
    #: 问②：合法的多行调用 ＋ 匿名函数字面量实参，放在死代码里（不产生红）
    "faceB": ('\t\tif false {\n'
              '\t\t\tt.Errorf("验收面B 死代码：跨行匿名函数字面量 %v",\n'
              '\t\t\t\tfunc() float64 { return seqs[2][1] }())\n'
              '\t\t}\n'),
    #: 问③：多行调用实参里的**块注释**含未配平左括号（`_strip_literals` 不覆盖 `/* */`）
    "faceC": ('\t\tif false {\n'
              '\t\t\tt.Errorf("验收面C 块注释配平 %v",\n'
              '\t\t\t\t/* ( */ 1)\n'
              '\t\t}\n'),
}


def make_tree(name: str) -> Path:
    tree = BASE / name / "rios-sim"
    if tree.exists():
        shutil.rmtree(tree)
    (tree / "mech").mkdir(parents=True)
    shutil.copy2(SRC_PROD / "go.mod", tree / "go.mod")
    for p in (SRC_PROD / "mech").glob("*.go"):
        shutil.copy2(p, tree / "mech" / p.name)
    inject = CASES[name]
    if inject is not None:
        f = tree / "mech" / "chain_test.go"
        s = f.read_text(encoding="utf-8")
        assert s.count(P2_ANCHOR) == 1, "锚点不唯一"
        f.write_text(s.replace(P2_ANCHOR, inject + P2_ANCHOR, 1), encoding="utf-8")
    return tree


def run_their_main(tree: Path, tag: str) -> tuple[object, str]:
    work = BASE / tag / "work" / "rios-sim"
    spec = importlib.util.spec_from_file_location(f"indep_{tag}", ORIG)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    m.SRC, m.WORK = tree, work
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            rc = m.main()
    except SystemExit as e:                      #: 它大声失败的一种形态；code 可能是字符串
        rc = e.code if e.code is not None else 1
        buf.write(f"[SystemExit] {e}\n")
    return rc, buf.getvalue()


def rows(txt: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in txt.splitlines():
        s = ln.strip()
        for tag in ("M1 ", "M2 ", "M3 ", "M4 "):
            if s.startswith(("✓", "✗")) and f" {tag}" in s:
                out[tag.strip()] = s
    return out


def main() -> int:
    case = sys.argv[1] if len(sys.argv) > 1 else ""
    if case not in CASES:
        print("用法：python tools/acceptance_scope_faces_probe.py <control|faceA|faceB|faceC>")
        return 2
    print(f"[仪器] 被审文件 = {ORIG}")
    rc, txt = run_their_main(make_tree(case), case)
    print(f"===== {case}：它 rc={rc} =====")
    for u in txt.splitlines():
        s = u.strip()
        if s.startswith(("✓", "✗", "⊘", "[SystemExit]")) or "判定：" in s or "跨过" in s or "不适用" in s:
            print("   " + s[:150])
    rs = rows(txt)
    if case != "control":
        print("   [本用例四行] " + " ｜ ".join(f"{k}: {rs.get(k, '(缺)')[:70]}" for k in ("M1", "M2", "M3", "M4")))
    print(f"   [要点] 出现「跨过」：{'跨过' in txt}；rc：{rc}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
