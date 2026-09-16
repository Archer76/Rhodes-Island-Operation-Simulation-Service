# -*- coding: utf-8 -*-
"""定位 MAA 的 OperBox 导出（账号名册这类**外部输入**）。

洁净化约定：**仓库里不留任何本机绝对路径**。真值按这个顺序找：

1. 环境变量 `AK_OPERBOX` —— 直接指向那份 json；
2. `data/operbox/Arknights_OperBox_Export.json` —— 约定落点。该目录已
   gitignore，把自己的导出按此文件名丢进去即可。

拿不到时**不报错**，只把路径交回调用方——各脚本自己判 `.exists()` 并跳过
对应小节（名册相关的那几节本来就有「没有就跳过」的分支）。

为什么要收在一处：这段路径原先在四个工具里各写了一遍绝对路径，既把人名
带进了公开仓库，也让别人克隆后完全跑不动这几套自检。
"""
from __future__ import annotations

import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: 约定落点。放这里的东西一律不入库（见 .gitignore 的 data/operbox/）。
DEFAULT = ROOT / "data" / "operbox" / "Arknights_OperBox_Export.json"


def operbox_path() -> pathlib.Path:
    """返回 OperBox 导出的路径（**未必存在**，由调用方判）。"""
    p = os.environ.get("AK_OPERBOX")
    return pathlib.Path(p) if p else DEFAULT
