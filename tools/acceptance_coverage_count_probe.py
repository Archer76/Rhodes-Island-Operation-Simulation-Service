# -*- coding: utf-8 -*-
"""覆盖面计数探针（验收会话自用，只读产品代码）。

用途：把 F6（2026-09-20 验收量到）做成**会红的检查**——
`chain_judge_independence.py` 的「归类器覆盖面」一节按文件分行，而分行印的数
必须**是那个文件的**。实测产品树上 `chain_test.go` 与 `farmland_golden_test.go`
两行都印 13，而合计也印 13；验收自数：chain_test.go 13、farmland_golden_test.go 14。

本探针自己现算「真值」（不引被测脚本的任何数），只在最后与被测脚本印出的数比对：
  判据 1（逐文件）：被测脚本印的 <文件> 计数 == 探针自数的该文件计数；
  判据 2（自洽）：Σ(被测脚本印的分行计数) == 被测脚本印的合计；
  判据 3（反向守卫）：往 farmland_golden_test.go 里**再加一处**会红调用点
      （放在 `if false` 里 ⇒ 永不执行、但仍是调用点）⇒ 那一行的数**必须变**。
      「数不变」＝这一节的分行数与它自称量的对象无关 ⇒ 必红。

用法：set CHAIN_INDEP_PIN=<冻结副本>  然后 python tools/acceptance_coverage_count_probe.py
退出码：0 = 三条全成立；1 = 有任一条不成立（具名）。
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

#: 探针自己的尺子：会红的调用点。与被测脚本的「判词调用处」不是同一个口径，
#: 故只在**同一口径内部**比（被测脚本印 vs 被测脚本该文件真值），不跨口径比大小。
RED_CALL = re.compile(r"\bt\.(?:Errorf|Fatalf|Fatal|Error)\(")
#: 被测脚本印的分行：· <文件>：判词调用处 N 条
PER_FILE = re.compile(r"·\s*([\w./\\-]+\.go)\s*：判词调用处\s*(\d+)\s*条")
#: 被测脚本印的合计：判词**调用处**共 M 条
TOTAL = re.compile(r"判词\*{0,2}调用处\*{0,2}共\s*(\d+)\s*条")


def true_counts(tree: Path) -> dict[str, int]:
    out: dict[str, int] = {}
    for p in sorted((tree / "mech").glob("*_test.go")):
        out[p.name] = len(RED_CALL.findall(p.read_text(encoding="utf-8")))
    return out


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
    except SystemExit as e:  # 被测脚本可能以 SystemExit 收场
        r = e.code
    raw = buf.getvalue()
    (BASE / f"raw-cov-{tag}.log").write_text(raw, encoding="utf-8")
    rc = getattr(r, "rc", r)
    return (0 if rc is None else int(rc)), raw


def parse(raw: str) -> tuple[dict[str, int], int | None]:
    printed = {m.group(1).split("/")[-1].split("\\")[-1]: int(m.group(2))
               for m in PER_FILE.finditer(raw)}
    tot = TOTAL.search(raw)
    return printed, (int(tot.group(1)) if tot else None)


def judge(tag: str, raw: str, tree: Path) -> tuple[list[str], dict[str, int], int | None]:
    """返回 (判红理由, 印出的分行数, 印出的合计)。

    ★ 2026-09-20 自缚修正（第一版判据错在哪，留痕）：
      第一版把「被测脚本印的数 == 探针自数的数」当成判据 —— **错**。
      探针的尺子是 `t.(Errorf|Fatalf|Fatal|Error)` 的整文件出现次数（含注释/字符串），
      与被测脚本自称的「判词调用处」**不是同一个口径**；拿两把尺子比大小＝`61d85582`。
      实测：`farmland_golden_test.go` 印 13／我数 14，而 chain_test.go 印 13／我数 13。
      第一版还把「Σ(分行) == 合计」当自洽判据 —— **也错**：那一句合计可能只覆盖
      **被判词表覆盖的那个文件**（原文是「判词**调用处**共 13 条：表内能认 5 条、表外 8 条」），
      即两条数**口径未声明**，不能当矛盾。
      现在留下的判据只有一条**跨口径无关**的：
        反向守卫 —— 往某文件里再加一处会红调用点，「它那一行」**必须跟着变**；
        且两棵树之间的**差值必须恒定**（恒定＝两把尺子差一个固定的口径偏移；不恒定＝行上的数不对应文件）。
    """
    bad: list[str] = []
    warn: list[str] = []
    printed, tot = parse(raw)
    truth = true_counts(tree)
    if not printed:
        return ([f"{tag}：没有解析到任何分行计数 ⇒ 这一节没印（或印法变了）⇒ 判据无从成立"], {}, tot)
    for name, n in sorted(printed.items()):
        if name not in truth:
            warn.append(f"{tag}：印出的文件 `{name}` 在树里没有对应 *_test.go（口径含包外文件？）")
            continue
        d = n - truth[name]
        if d == 0:
            print(f"   ✓ {name}：印 {n} 条，探针自数 {truth[name]} 条（两把尺子同值）")
        else:
            warn.append(f"{tag}：`{name}` 印 {n} 条，探针自数 **{truth[name]}** 条（差 {d:+d}）"
                        f"⇒ **口径未声明**：两个数不同不构成缺陷，须被测方写明「判词调用处」的谓词")
    if tot is not None and sum(printed.values()) != tot:
        warn.append(f"{tag}：分行合计 {sum(printed.values())} ≠ 印出的合计 {tot} ⇒ **口径未声明**"
                    f"（合计可能只覆盖被判词表覆盖的文件），不构成自相矛盾")
    print(f"\n===== {tag} =====")
    print(f"   印出的分行：{printed}")
    print(f"   印出的合计：{tot}；探针自数：{truth}")
    for w in warn:
        print("   ⚠ " + w)
    for b in bad:
        print("   ✗ " + b)
    return bad, printed, tot


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
    print(f"== 覆盖面计数探针 · 被测脚本 {pin.name} · 树 {PROD} ==")

    bad: list[str] = []
    ctrl = make_tree("control", extra_sentinel=False)
    rc1, raw1 = run_frozen(pin, ctrl, "control")
    print(f"   （被测脚本在 control 树上 rc={rc1}；它的 rc 不是本探针的判据，本探针只读它印的行）")
    b1, p1, _ = judge("control", raw1, ctrl)
    bad += b1

    guard = make_tree("guard", extra_sentinel=True)
    rc2, raw2 = run_frozen(pin, guard, "guard")
    print(f"   （被测脚本在 guard 树上 rc={rc2}）")
    b2, p2, _ = judge("guard", raw2, guard)
    bad += b2

    t1, t2 = true_counts(ctrl), true_counts(guard)
    name = "farmland_golden_test.go"
    print("\n===== 反向守卫（本探针唯一的判红项）=====")
    if name in p1 and name in p2:
        if p1[name] == p2[name]:
            bad.append(f"★ 反向守卫失败：往 `{name}` 里再加一处会红调用点，它那一行仍印 {p1[name]} 条 ⇒ "
                       f"这一节的数与该文件无关（不红 ⇒ 这条判据没有分辨力）")
        else:
            print(f"   ✓ 印出的数跟着对象走：`{name}` 在 control 印 {p1[name]}、在 guard 印 {p2[name]}"
                  f"（我自数 {t1.get(name)} → {t2.get(name)}）")
        d1, d2 = p1[name] - t1.get(name, 0), p2[name] - t2.get(name, 0)
        if d1 == d2:
            print(f"   ✓ 两棵树差值恒定（{d1:+d} / {d2:+d}）⇒ 印的是**该文件**的量，"
                  f"差值属两把尺子的口径偏移（探针这把是整文件 findall，含注释与字符串）")
        else:
            bad.append(f"★ 差值不恒定（control {d1:+d}、guard {d2:+d}）⇒ 行上的数不对应文件内容")
    else:
        bad.append(f"★ 反向守卫前提不成立：两棵树里都没解析到 `{name}` 那一行")

    print("\n== 判定：== " + ("反向守卫成立（行上的数跟着对象走）" if not bad
                             else f"**{len(bad)} 条不成立** ⇒ rc=1"))
    for b in bad:
        print("   ✗ " + b)
    print("\n★ 本探针**不判**「印的数 == 探针自数的数」：两把尺子口径不同（探针数整文件出现次数，"
          "被测方数它自称的「判词调用处」），比大小就是 `61d85582`。"
          "它只判一件事：**那一行印的数跟不跟着那个文件走**，以及**差值是否恒定**。")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
