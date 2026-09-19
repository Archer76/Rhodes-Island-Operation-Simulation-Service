#!/usr/bin/env python3
"""chain 判据的**独立性实测**：一个变异红几条。

通则（验收顶回、PM 提成通则 `msg-mu903tfp-g0`）：
**「一个改动红几条」就是独立性的判据** ——
红一条 ⇒ 那条断言是**独立的信息**；红两条 ⇒ **至少有一条多余**；红三条以上 ⇒ **同一个判据的多份副本**。

★ 为什么这条要**实测**而不是自述：上一版我的「盲区断言」被前两条在算术上**蕴含**
（盲区用例绿 ＋ 实现过判据 ⇒ `blind[1] == seq[1]`），一个字没改就能"证明"一个恒等式；
验收在副本里变异一次、**红了两条**，才把这件事照出来（同族 `d8706dc5`）。

本脚本做什么
------------
1. 把 `rios-sim/go.mod` 与 `rios-sim/mech/*.go` 复制到 `out/backend2-b1/indep/rios-sim/`
   （**不碰产品树**，产品树只读）；
2. 先跑一次基线：`go test ./mech/ -run Chain -count=1 -v` 必须 **rc=0**；
3. 逐个施加**最小变异**（每处替换自带 `expect` 自校验，替换不到即报错），每次重跑；
4. 按**判词前缀**把红的断言归类（`t.Logf` 与 `t.Errorf` 在 `-v` 输出里长得一样，
   所以不按行号数，按我自己写的判词认）；
5. **断言每个变异恰好红一条**，并把矩阵印出来；任一行不是 1 ⇒ rc=1。

用法：`python tools/chain_judge_independence.py`
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "rios-sim"
WORK = ROOT / "out" / "backend2-b1" / "indep" / "rios-sim"

#: 断言的身份：id → 判词前缀（判词是我自己写的，故这是**按内容认**而不是按行号认）
ASSERTIONS: list[tuple[str, str]] = [
    ("断言1 实现过判据", "实现未过判据："),
    ("断言2 真实参数必须拒绝", "时必须返回 ErrJumpUndetermined"),
    ("断言3 合成反例被抓", "没抓住「"),
    ("断言5 读法判别器", "读法判别器红："),
    ("断言6 分岔点只有 n=3", "n=3 的 "),
]

PER_JUMP_IF = ("\t\tif k == 1 {\n"
               "\t\t\tseq[k-1] = base\n"
               "\t\t} else {\n"
               "\t\t\tseq[k-1] = base * scale\n"
               "\t\t}")

#: (名字, 相对 rios-sim 的路径, 旧串, 新串, 预期红哪条断言)
MUTATIONS: list[tuple[str, str, str, str, str]] = [
    ("M1 实现 n=2 写错（×1.05）", "mech/chain.go",
     "\tcase 2:\n\t\treturn scale, nil",
     "\tcase 2:\n\t\treturn scale * 1.05, nil",
     "断言1 实现过判据"),
    ("M2 候选③ 的 n=2 写错（×1.05）", "mech/chain_test.go",
     "\t\t} else {\n\t\t\tseq[k-1] = base * scale\n\t\t}",
     "\t\t} else {\n\t\t\tseq[k-1] = base * scale * 1.05\n\t\t}",
     "断言5 读法判别器"),
    ("M3 候选③ 的 n=3 变成与②同值", "mech/chain_test.go",
     PER_JUMP_IF,
     ("\t\tif k == 1 {\n"
      "\t\t\tseq[k-1] = base\n"
      "\t\t} else if k == 3 {\n"
      "\t\t\tseq[k-1] = base * 0.5\n"
      "\t\t} else {\n"
      "\t\t\tseq[k-1] = base * scale\n"
      "\t\t}"),
     "断言6 分岔点只有 n=3"),
    ("M4 实现对 scale 不敏感", "mech/chain.go",
     "\tcase 2:\n\t\treturn scale, nil",
     "\tcase 2:\n\t\treturn 1.0, nil",
     "断言1 实现过判据"),
]


def stage() -> None:
    """把包搭到工作目录（mech 包自含，故只需 go.mod ＋ mech/*.go）。"""
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


def red_assertions(out: str) -> list[str]:
    return [aid for aid, prefix in ASSERTIONS if any(prefix in ln for ln in out.splitlines())]


def mutate(rel: str, old: str, new: str) -> None:
    """施加一处变异；**替换不到就报错**（`466798b5`：每处替换自带 expect 自校验）。"""
    f = WORK / rel
    text = f.read_text(encoding="utf-8")
    n = text.count(old)
    if n != 1:
        raise SystemExit(f"✗ 变异锚点在 {rel} 里出现 {n} 次（应为 1）⇒ 变异没到达目标那行，读数无效")
    f.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> int:
    stage()
    print(f"== 工作副本：{WORK.relative_to(ROOT)}（产品树只读，未改动）==")

    rc, out = go_test()
    n_red = red_assertions(out)
    print(f"== 基线：rc={rc}、红 {len(n_red)} 条 {n_red} ==")
    if rc != 0 or n_red:
        print("✗ 基线就不是全绿 ⇒ 后面的矩阵无意义")
        return 1

    rows: list[tuple[str, list[str], str]] = []
    ok = True
    for name, rel, old, new, expect in MUTATIONS:
        stage()                      # 每个变异从干净副本开始
        mutate(rel, old, new)
        rc, out = go_test()
        reds = red_assertions(out)
        mark = "✓" if (len(reds) == 1 and reds[0] == expect) else "✗"
        if mark == "✗":
            ok = False
        print(f"{mark} {name}：rc={rc}、红 {len(reds)} 条 {reds}（预期只红 {expect}）")
        rows.append((name, reds, expect))

    print("\n== 矩阵（一个变异 × 红的断言）==")
    for name, reds, expect in rows:
        print(f"  {name:34s} 红 {len(reds)} 条：{'／'.join(reds) or '—'}")
    print(f"\n== 判定：{'全部恰好红一条 ⇒ 各断言互相独立' if ok else '有变异红 ≠1 条 ⇒ 存在冗余或耦合'} ==")
    print("★ 纪律：红两条以上时不要问「哪条对」，先按这条把冗余删掉——否则读者无法知道是哪条在起作用")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
