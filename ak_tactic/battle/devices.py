# -*- coding: utf-8 -*-
"""**转出壳**：`battle/devices.py` 的实现已搬到 `ak_tactic/frontend/devices.py`。

## 为什么留一层壳而不是直接删

这个模块在仓库里还有三个**不是我这一层**的消费者，删了会一起断：

```
ak_tactic/sim.py:523    from .devices import (BLOCKER_KEY, DeviceUnit, ...)
ak_tactic/sim.py:2970   from .devices import (BLOCKER_BUILD_FRACTION, ...)
ak_tactic/sim.py:4896   from .devices import DIRECTIONS, PUMP_KEY, behind_of
ak_tactic/activity.py:77    anchor="ak_tactic.battle.devices:BLOCKER_KEY"
ak_tactic/activity.py:82    anchor="ak_tactic.battle.devices:PUMP_KEY"
ak_tactic/activity.py:376   from .battle.devices import parse_devices
```

`activity.py` 属于别的模块/会话，**我不改它**。壳让这些写法一个字都不用动，
等 `battle/` 整个删掉时这层壳也跟着删。

## ⚠ 为什么要 __getattr__ 兜一层

`from ..frontend.devices import *` 只转 `__all__` 里的名字。
`__all__` 之外的（例如被 `sim.py` 直接点的 `BLOCKER_BUILD_FRACTION` 之类）
会 ImportError —— **而且是那种「改名时漏了一个」的错，只在跑到那一行时才响**。
PEP 562 的模块级 `__getattr__` 把所有名字都兜住，这类漏项就不可能发生。

这不是「偷懒的兜底」，它和本项目禁止的那种 getattr 带默认值是两件事：
**这里取不到就照常 AttributeError**，只是把查找转发到了新家。
"""
from __future__ import annotations

from ..frontend.devices import *          # noqa: F401,F403
from ..frontend.devices import __all__    # noqa: F401


def __getattr__(name: str):
    """`__all__` 之外的名字也照转（PEP 562）。取不到照样 AttributeError。"""
    from ..frontend import devices as _new
    return getattr(_new, name)


def __dir__() -> list[str]:
    from ..frontend import devices as _new
    return sorted(set(globals()) | set(dir(_new)))