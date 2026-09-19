#!/usr/bin/env python3
"""带闸门的提交：**先跑检查，rc≠0 就不提交**。

为什么要有这个工具（而不是每次手打两条命令）
------------------------------------------------
PM 把这条提成通则（`msg-mu901myi-fw`）：

> **检查必须拦在动作前，否则它只是一段好看的输出。**

这是「能变检查的变检查」的**下一层**：上一条解决"有没有检查"，
这一条解决"**检查的结论有没有接到动作上**"。
实测账（要诚实）：散文引号检查一夜**报出 4 次、拦住 0 次**——前 3 次是人看见了手动改的，
第 4 次是人没看见、它也没拦住（因为 `git commit` 手打在检查后面、**没有判 rc**）。
⇒ 把"判 rc 再决定提不提交"写成一个**动作**，而不是一条**纪律**。

用法
------------------------------------------------
    python tools/gated_commit.py -F <message-file> -- <paths...>
    python tools/gated_commit.py --dry-run -F <msg> -- <paths...>          # 只跑闸门，不提交
    python tools/gated_commit.py --gate "go test ./mech/" --cwd rios-sim -F <msg> -- <paths...>

* 默认闸门＝ `tools/cjk_quote_lint.py` 扫这些路径（散文里的半角引号）；
* `--gate` 可给多条，**逐条跑、逐条判 rc**，任何一条红就退出且**不提交**；
* 退出码：0＝闸门全绿且已提交（或 `--dry-run` 下全绿）；1＝**被闸门拦下**；2＝闸门绿但 git 失败。

★ 一处刻意的设计：**闸门红的输出会原样转给用户**（不做过滤）——
被拦下的人需要看到"哪一行、为什么"，否则他会绕过闸门。

★ 自测履历（**两次控制组，第一次是错的，留着**）
------------------------------------------------
* **第一次（错）**：控制输入写成 `半角引号 "bad"` ⇒ 闸门 **rc=0 放行**。
  ★ 判词：**不是闸门坏了，是控制组选错了**——尺子的范围是「引号**内含中文**」（见
  `cjk_quote_lint.PROSE_QUOTE`），`"bad"` 的引号里没有中文 ⇒ **它压根没进被测分支**
  （同族 `2d6f0f2d`：合成反例必须确认假注入真进了被测分支）。
  ★ 更该记的是：那一笔（`374cdbd`）的**提交信息里已经写了「rc=1 拦下」——那句话在提交时是假的**，
  因为我是**先写判词、后跑控制**。⇒ 纪律：**控制组的读数要跑出来再写进提交信息**；
  已写错的不改旧话，留勘误（本条即勘误）。
* **第二次（对）**：控制输入 `半角引号 "中文"`（引号内含中文 ⇒ 在范围内）
  ⇒ 尺子 rc=1；闸门 **rc=1 拦下**，且**不给 `--dry-run` 时该文件仍是 `??`（没被 add）**。
  ★ 附带一把元尺子也要先证明活着：判定"有没有被 add"用的是 `git status --porcelain`——
  先手动 `git add -f` 看它显示 `A`、再 `git reset` 看它显示 `??`，**尺子活了才敢用它的读数**
  （`557ee93b`：工具报"找不到"时先证明工具自己是活的）。
  ★ 另：`out/` 在 .gitignore 里 ⇒ 拿它当控制组时 `--porcelain` **无输出**，会把"看不见"读成"没 add"；
  控制组因此放在受跟踪目录（`docs/`）下做，读数才是 `??`。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def run(cmd: list[str], cwd: Path) -> tuple[int, str]:
    """跑一条命令；**按字节捕获再自行解码**（PowerShell 管道会按 CP936 错解中文，见 `3daf8c9a`）。"""
    p = subprocess.run(cmd, cwd=str(cwd), capture_output=True)
    out = (p.stdout or b"").decode("utf-8", "replace") + (p.stderr or b"").decode("utf-8", "replace")
    return p.returncode, out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(add_help=True)
    ap.add_argument("-F", "--file", required=True, help="提交信息文件（git commit -F）")
    ap.add_argument("--gate", action="append", default=[], help="额外闸门命令（可重复；给多条则逐条判 rc）")
    ap.add_argument("--cwd", default=str(ROOT), help="闸门命令的工作目录（默认仓库根）")
    ap.add_argument("--dry-run", action="store_true", help="只跑闸门、不提交")
    ap.add_argument("--no-default-gate", action="store_true", help="不要默认的引号闸门")
    ap.add_argument("paths", nargs="+", help="要提交的路径（逐路径 add，禁用 add -A）")
    a = ap.parse_args(argv[1:])

    gates: list[list[str]] = []
    if not a.no_default_gate:
        lint = str(ROOT / "tools" / "cjk_quote_lint.py")
        gates.append([sys.executable, lint, "--", *a.paths])
    for g in a.gate:
        gates.append(g.split())

    print(f"== 闸门 {len(gates)} 条；目标 {len(a.paths)} 个路径 ==")
    for cmd in gates:
        rc, out = run(cmd, Path(a.cwd))
        print(f"-- $ {' '.join(cmd)}")
        for line in out.splitlines():
            if line.strip():
                print(f"   {line}")
        if rc != 0:
            print(f"== ✗ 闸门拦住（rc={rc}）⇒ **不提交**。修好再跑；"
                  f"若是引号闸门，可先 `python tools/cjk_quote_lint.py --fix -- <paths>` ==")
            return 1
        print(f"   ✓ rc=0")
    print("== ✓ 闸门全绿 ==")

    if a.dry_run:
        print("== --dry-run：放行但**不提交** ==")
        return 0

    rc, out = run(["git", "add", "--", *a.paths], Path(a.cwd))
    if rc != 0:
        print(out)
        return 2
    rc, out = run(["git", "commit", "-q", "-F", a.file], Path(a.cwd))
    print(out.strip())
    if rc != 0:
        return 2
    rc, out = run(["git", "log", "-1", "--format=%h %s"], Path(a.cwd))
    print(f"== 已提交：{out.strip()} ==")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
