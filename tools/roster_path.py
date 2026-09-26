# -*- coding: utf-8 -*-
"""定位**账号名册文档**（`docs/roster-*.md` 这类**外部输入**）。

洁净化与隐私两条约定（与 `tools/operbox_path.py` 同族）：

1. **仓库里不留本机绝对路径，也不留账号 uid**。真值按这个顺序找：

   ① 环境变量 `AK_ROSTER` —— 直接指向那份 md；
   ② `docs/roster-*.md` —— 按文件名排序取第一个（本机导出，按 `.gitignore` 不入库）。

2. 拿不到时**不报错**，只把一个**不存在的约定路径**交回调用方，由各脚本自己判
   `.is_file()` 并走「缺输入」那一支 —— 名册相关判据本来就有那条三态分支。

为什么要收在一处：2026-09-26 之前，这个文件名在 `check_operator_go.py` 与
`verify_pinned_tree.py` 里**各写死了一遍**，而名字里带着**账号 uid**：

* 它把 uid 又公布了一次（那串 uid 2026-09-17 已按隐私口径从本仓历史里摘除过）；
* 它让这两件工具**只对那一个账号有效** —— 换个账号导出，文件名就对不上，
  判据会以「名册不在」的名义静默跳过整整一栏。
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 找不到时交回的名字。**两个作用**：给人看时说明"该有一份名册"，
#: 而 `.is_file()` 必为假（真文件名不会是字面的 `*`）⇒ 调用方的三态分支照旧走。
#: ★ 特意用通配符形态而不是某个具体账号名 —— 后者正是这次要清掉的东西。
MISSING_HINT = ROOT / "docs" / "roster-*.md"


def roster_path() -> pathlib.Path:
    """返回名册文档的路径（**未必存在**，由调用方判 `.is_file()`）。"""
    env = os.environ.get("AK_ROSTER")
    if env:
        return pathlib.Path(env)
    hits = sorted((ROOT / "docs").glob("roster-*.md"))
    return hits[0] if hits else MISSING_HINT
