# -*- coding: utf-8 -*-
"""兼容入口 —— 实现已经搬到 `ak_tactic/skland_did.py`（理由同 tools/skland.py）。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ak_tactic.skland_did import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
