# -*- coding: utf-8 -*-
"""给界面用的**进度事件**通道（JSONL 文件）。

与 `tools/rebuild_data.py::Progress` 同一份形状 —— 界面（`rios-tui`）按偏移量
增量读那个文件、原地重画进度条：

    {"ev":"tick","key":…,"done":N,"total":M,"bytes":B}

★ 为什么是**文件**不是管道：本仓记过一条硬约束 —— 本机沙箱下用管道捕获子进程
输出会 **EPERM**（`tools/rebuild_data.py::_run_step` 的注释就是它）。所以父子之间
的进度走普通文件：子进程 append 一行、父进程按偏移量增量读，谁也不碰管道。

★ `bytes` 是**累计已下载字节**：界面拿它算速度（两次 tick 的差 ÷ 时间差）。
给不出就写 0 —— 界面会只画百分比、不编速度。
"""
from __future__ import annotations

import json
import time

__all__ = ["ProgressWriter"]


class ProgressWriter:
    """往进度文件追加事件。`path` 为 None 时**全部是空操作**（判据/试跑里常这样）。"""

    def __init__(self, path: str | None = None) -> None:
        self.path = path

    def _w(self, obj: dict) -> None:
        if not self.path:
            return
        try:
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(json.dumps(obj, ensure_ascii=False) + "\n")
        except OSError:
            pass                       #: 进度写不进去不该让建库失败

    def tick(self, key: str, done: int, total: int, *, bytes_: int = 0) -> None:
        """报一次进度。

        ★ `t`（epoch 秒）**必须带**：界面按 150ms 的节奏批量读这个文件，同一批里
        的几行会被打上同一个"读到的时刻" ⇒ 相邻取样时间差≈0 ⇒ **算不出速度**。
        带上各自的时刻，速度就与轮询节奏无关了（2026-09-28 博士："没看到下载速度"）。
        """
        self._w({"ev": "tick", "key": key, "done": int(done), "total": int(total),
                 "bytes": int(bytes_), "t": round(time.time(), 3)})
