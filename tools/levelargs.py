# -*- coding: utf-8 -*-
"""把「关卡清单」从命令行搬进文件（2026-09-27）。

## 为什么

总闸与冻结档录制都是把**全量缓存关卡**当位置参数喂给各套判据的。实测：
缓存涨到 **2676** 个关卡键时，Windows 的 `CreateProcess` 直接报

    FileNotFoundError: [WinError 206] 文件名或扩展名太长

（命令行上限约 32767 字符；2314 个键≈30k 刚好塞得下，2676 个≈35k 就超了）。
它挑在**录制冻结档**时炸，而录制是重录那一套的第一步 —— 一炸就什么都录不成。

## 怎么用

调用方（总闸、冻结档）把清单写成一个文件，然后传 **`@<路径>`** 这一个参数；
各套判据在解析位置参数时调 `expand()` 把它展开成 id 列表。

    args = expand([a for a in sys.argv[1:] if not a.startswith("-")])

★ `@` 是**唯一**的约定：只认"以 @ 开头且指向一个存在文件"的参数，
其余原样返回 —— 这样"手敲几个关卡"的老用法一字不变。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def expand(items: list[str]) -> list[str]:
    """把 `@<文件>` 展开成文件里的 id（一行一个；空行与 `#` 注释跳过）。"""
    out: list[str] = []
    for it in items:
        if it.startswith("@") and len(it) > 1:
            p = Path(it[1:])
            if p.is_file():
                for line in p.read_text(encoding="utf-8").splitlines():
                    s = line.strip()
                    if s and not s.startswith("#"):
                        out.append(s)
                continue
        out.append(it)
    return out


def as_arg(ids: list[str]) -> str:
    """把一列 id 写成临时文件，返回那个 `@<路径>` 参数（调用方用完自行删）。"""
    fd, path = tempfile.mkstemp(prefix="rios-levels-", suffix=".txt")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("\n".join(ids) + "\n")
    return "@" + path
