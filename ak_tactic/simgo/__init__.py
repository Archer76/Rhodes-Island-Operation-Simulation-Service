"""`rios-sim`（Go 版模拟器）的 Python 侧：把一场战斗**序列化**过去，再把判决收回来。

这一层存在的理由见 `docs/tui-plan.md` 第十二节。边界只有一句话：

    **数字由 Python 算完送去，Go 只负责把它们推成结果。**

所以这里读的是 `BattleSimulator` 已经建好的东西（敌人实例、干员对象、路线分段、
费用参数），而不是按 `enemy_id` 再去查一遍库——「再查一遍」等于在 Go 侧重写一遍
`_build_enemy`，多一处实现就多一处会漂的地方。

模块分工：

* `spec.build_spec(sim)` —— `BattleSimulator` → 规格 dict；用到了最小版本没覆盖
  的机制时，把原因逐条写进 `unsupported`（Go 侧见到就拒跑）。
* `client.Simgo` —— 子进程 + 一行一个 JSON 的调用；`client.compare` 逐项对拍。
"""

from .client import (EngineBinaryUnpinned, Simgo, compare, find_binary,
                     legacy_binary, require_binary, staleness_minutes)
from .spec import build_spec, unsupported_reasons

__all__ = ["Simgo", "compare", "find_binary", "require_binary", "EngineBinaryUnpinned",
           "legacy_binary", "staleness_minutes", "build_spec", "unsupported_reasons"]
