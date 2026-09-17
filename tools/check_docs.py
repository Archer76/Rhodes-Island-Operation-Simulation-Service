# -*- coding: utf-8 -*-
"""文档守卫：markdown 里的相对链接必须指向真实存在的文件。

## 为什么值得单开一套

README 与 `docs/` 是**唯一靠手维护**的东西，而它们最容易犯的错是指空——
GitHub 上指空的链接**不会报错**，只会静静地显示成一段普通文字，谁都不会发现。
2026-09-17 把 README 拆成「README 只讲怎么用 + docs/ 收实测结论」时，
一次搬家就带出两处这种错（搬到 docs/ 下的文件里还写着 `docs/xxx.md`）。

## 只查相对链接

`http(s)://` 与 `mailto:` 一概跳过——那要走网络，不该进自检。
被 `.gitignore` 排除的文档（如 `docs/roster-*.md`，属个人数据）不算指空：
它确实不在仓库里，本就不该被链接。

## 反引号里的路径不查

本项目既有的约定是**反引号里写仓库相对路径**（`docs/formula-model.md`），
那是给源码注释与人看的，不是链接，指空与否不在这套自检的判据里。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def main() -> int:
    print("检查文档链接（README.md 与 docs/*.md）")
    targets = [ROOT / "README.md"] + sorted((ROOT / "docs").glob("*.md"))
    checked = 0
    bad: list[str] = []
    for f in targets:
        text = f.read_text(encoding="utf-8")
        for m in LINK.finditer(text):
            href = m.group(1).strip()
            if href.startswith(("http://", "https://", "mailto:")):
                continue
            href = href.split("#")[0]
            if not href:
                continue
            checked += 1
            p = (f.parent / href).resolve()
            if not p.exists():
                line = text[:m.start()].count("\n") + 1
                bad.append(f"{f.relative_to(ROOT)}:{line}  {href}")

    print(f"  扫了 {len(targets)} 份文档、{checked} 条相对链接")
    for b in bad:
        print(f"  [FAIL] 指空：{b}")
    if bad:
        print(f"\n通过 {checked - len(bad)} 项，失败 {len(bad)} 项。")
        return 1
    print(f"\n通过 {checked} 项，失败 0 项。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
