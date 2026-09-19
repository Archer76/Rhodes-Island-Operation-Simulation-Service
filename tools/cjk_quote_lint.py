#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""中文散文里的半角引号检查（`9d16e3ae`：同一规矩一晚犯两次 ⇒ 能变检查的变检查）。

**规则**：**中文散文**里引用措辞一律用「」，不用半角 `"`。
**不算违规**：代码（Go/Python 字符串字面量、Markdown 围栏内的代码、行内代码 `` `...` ``）。

用法：
    python tools/cjk_quote_lint.py                      # 扫默认范围（全仓库散文）
    python tools/cjk_quote_lint.py -- rios-sim/mech/chain.go docs/x.md
    python tools/cjk_quote_lint.py --quiet              # 只报计数

退出码：0＝干净；1＝有违规（逐条打印 `文件:行`）。

★ 判据自身的两个坑（都实测踩过）：
  ① **围栏内的 Go 代码原文不能算违规**——`catch(chain.go)` 的原文行会被抄进 Markdown，
     若不过滤围栏，检查会把自己的证据当成违规（第一版就误报了 3 处）。
  ② **行内代码先剥掉再判**——`{"attack@chain.atk_scale": 0.75}` 这种 JSON 片段属于代码，
     正确改法是包反引号，而不是把它改成「」。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CJK = re.compile(r"[\u4e00-\u9fff]")
INLINE_CODE = re.compile(r"`[^`]*`")
#: ★ 收窄：**引号里含中文**才算「散文引用」。注释里举例一个键名（`"atk_scale"`）是技术写法，
#: 不是中文正文引用——不收窄的话全仓库会报 2933 处（实测），判据宽到没用。
PROSE_QUOTE = re.compile(r'"[^"]*[\u4e00-\u9fff][^"]*"')
DEFAULT_GLOBS = ("rios-sim/**/*.go", "rios-sim/**/*.md", "tools/*.py", "tools/*.md",
                 "docs/*.md", "ak_tactic/**/*.py")


def violations_in(path: Path) -> list[tuple[int, str]]:
    """返回 [(行号, 该行原文)]——只报**散文行**里的半角引号。"""
    out: list[tuple[int, str]] = []
    suffix = path.suffix
    in_fence = False
    for i, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        s = line.strip()
        if suffix == ".md":
            if s.startswith("```"):
                in_fence = not in_fence
                continue
            if in_fence:                       #: ★ 坑①：围栏内是代码，不算散文
                continue
        elif suffix == ".go":
            if not s.startswith("//"):         #: Go 字符串字面量是代码
                continue
        elif suffix == ".py":
            if not s.startswith("#"):
                continue
        if not CJK.search(line) or '"' not in line:
            continue
        body = INLINE_CODE.sub("", line)           #: ★ 坑②：行内代码里的引号不算
        if not PROSE_QUOTE.search(body):
            continue
        out.append((i, s))
    return out


def _show(p: Path) -> str:
    """显示的路径：仓库内用相对路径；**仓库外用绝对路径**。

    ★ 这里曾崩过：`p.relative_to(ROOT)` 对仓库外的文件抛 `ValueError`，
    于是合成反例那条的 rc=1 是**崩溃**给的、不是判据给的（`06c2d722`：脚本红了≠判据红了）。
    """
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def main(argv: list[str]) -> int:
    args = [a for a in argv[1:] if a != "--"]
    quiet = "--quiet" in args
    args = [a for a in args if not a.startswith("--")]
    if args:
        files = [Path(a) if Path(a).is_absolute() else ROOT / a for a in args]
    else:
        files = sorted({p for g in DEFAULT_GLOBS for p in ROOT.glob(g)})
    total, hit_files = 0, 0
    for p in files:
        if not p.is_file():
            continue
        v = violations_in(p)
        if not v:
            continue
        hit_files += 1
        total += len(v)
        if not quiet:
            for n, text in v:
                print(f"  {_show(p)}:{n}: {text[:96]}")
    print(f"  ⇒ 扫 {len(files)} 个文件：{hit_files} 个文件有违规、共 {total} 处"
          f"（散文行半角引号；围栏代码与行内代码已排除）")
    return 0 if total == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
