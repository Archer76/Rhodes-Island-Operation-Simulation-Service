# -*- coding: utf-8 -*-
"""兼容入口 —— 实现已经搬到 `ak_tactic/skland.py`。

留在 `tools/` 的原因只有一个：**README、THIRD-PARTY 与本项目的既有说明里
写的都是 `python tools/skland.py <子命令>`**，而它现在要同时被命令行和 TUI
两边用（TUI 的登录屏要申请二维码、轮询、落盘 hgToken）。放进包里，
`ak_tactic.tui.app` 才能正经 import，不必反向依赖 tools/。
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.skland import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
