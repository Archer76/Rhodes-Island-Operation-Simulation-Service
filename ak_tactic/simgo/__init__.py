"""`rios-sim`（Go 版模拟器）的 Python 侧：把一场战斗**序列化**过去，再把判决收回来。

这一层存在的理由见 `docs/tui-plan.md` 第十二节。边界在**2026-09-23 变了**，现在是：

    **规格由 Go 从「关卡＋名册＋计划」自己造**（查询形式），Python 只送输入；
    Go 把没移植的部分写成 `unsupported` 带回来 ⇒ **具名拒跑**（Python 不再回退跑模拟器）。

改之前那句边界是「数字由 Python 算完送去，Go 只负责把它们推成结果」——它现在是**错的**，
但它换来的性质仍然成立：Python 侧不再先算规格，所以「跑完 `life=0` 的规格」那类坑
在这条路上结构性地不可能发生。

模块分工：

* `spec.build_spec(sim)` —— `BattleSimulator` → 规格 dict。★ 它现在**只作对拍权威**
  （判据靠它算期望值），**不再**是生产路径上送给 Go 的那一份；用到了最小版本没覆盖
  的机制时，把原因逐条写进 `unsupported`。
* `client.Simgo` —— 子进程 + 一行一个 JSON 的调用。送**查询形式**用 `sim_query()`；
  送**造好的规格**用 `sim()`（旧形式，Go 侧仍收）。`client.compare` 逐项对拍。
"""

from .client import (EngineBinaryUnpinned, Simgo, compare, find_binary,
                     legacy_binary, require_binary, staleness_minutes)
from .spec import build_spec, unsupported_reasons

__all__ = ["Simgo", "compare", "find_binary", "require_binary", "EngineBinaryUnpinned",
           "legacy_binary", "staleness_minutes", "build_spec", "unsupported_reasons"]
