# -*- coding: utf-8 -*-
"""**转出壳**：`battle/environment.py` 的实现已搬到 `ak_tactic/frontend/environment.py`。

## 为什么留一层壳而不是直接删

```
ak_tactic/battle/sim.py:535   from .environment import FarmlandSystem, PolluteParams
ak_tactic/battle/sim.py:1395  from .environment import pump_once
ak_tactic/battle/sim.py:4897  from .environment import PUMP_RANGE, PUMP_RANGE_BONUS
ak_tactic/activity.py:223     anchor="ak_tactic.battle.environment:RUNES_KEY"
```

最后一条尤其要注意：那是个**字符串锚点**，用 importlib + getattr 解析。
`activity.py` 属于别的模块/会话，**我不改它** —— 壳让这个锚点继续解析得到，
搬完之后实测验证过（见 `tools/check_battle_shims.py`）。

## ⚠ 为什么要 __getattr__ 兜一层

同 `battle/devices.py` 那份壳：`import *` 只转 `__all__`，
而 `pump_once` 就**不在** `__all__` 里却真的被 `sim.py` 点着。
PEP 562 把所有名字都兜住；**取不到照样 AttributeError**，只是转发查找。
"""
from __future__ import annotations

from ..frontend.environment import *          # noqa: F401,F403
from ..frontend.environment import __all__    # noqa: F401


def __getattr__(name: str):
    """`__all__` 之外的名字也照转（PEP 562）。取不到照样 AttributeError。"""
    from ..frontend import environment as _new
    return getattr(_new, name)


def __dir__() -> list[str]:
    from ..frontend import environment as _new
    return sorted(set(globals()) | set(dir(_new)))