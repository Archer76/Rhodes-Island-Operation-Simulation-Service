"""把 Go 那份模拟器接进**验证/搜索**这条流水线（默认已是 Go，博士 2026-09-19 裁定）。

## 分工

`ak_tactic/verify.py` 是权威那一条路：它负责**排程**（把人摆在可部署格里、算费用
与落地时刻、把撤退与手动开技能按坐标排好）。这些和"用哪份模拟器算战斗"是两件事，
所以我们**只换最后那一步**：

    Verifier.run ──(排好 sim)──► engine="python" → sim.run()       → _verdict()
                                 engine="go"     → build_spec(sim) → Go → 判决

`build_spec` 读的就是那个**排好程、还没跑**的 `sim`（它不重放排程，只把"此刻"的
战场读出来）——排程口径两边完全共用，不存在第二份实现。

## 三条纪律

1. **默认已是 go**（博士 2026-09-19 裁定：怀黍离全部关卡对拍通过后切换，Python 那份
   退为对拍基准、不再作运行时引擎）。⚠ 因此 `Verifier` 的基类必须**自己接住 `"go"`**
   ——见 `ensure_go_engine` 的注释：默认值改过去而出口只挂在本模块的混入类上时，
   全仓的裸 `Verifier()` 会当场崩在"基类没有这个能力"上，而不是跑 Go。
2. **不支持就退回，并且说出来**。规格里出现没移植的字段时 Go 会拒跑
   （`spec.unsupported`），这里当场退回原版，并在 `diagnosis` 里写一行说明——
   静默换引擎等于让搜索结果没法归因。
3. **判决形状照着 `Verifier._verdict` 来**：`rank()` 只用
   `stars / life / kills / leak_events / damage`，这五项必须逐字对齐；逐人战报里
   Go 侧拿不到的字段（出手次数、承受伤害）**留 0 并标注**，不编数。

## 现在到哪一步了

对拍台（`tools/check_mech_parity.py`）全绿的关卡才能用这条路；其余关卡靠
`spec.unsupported` 那道门自动退回。那个字段是 Go 自己报的，不是这里猜的。
"""

from __future__ import annotations

import time
from typing import Any

from ..verify import Verdict, Verifier, stars_of
from . import build_spec, find_binary
from .client import Simgo

__all__ = ["GoEngineMixin", "GoVerifier"]


class GoEngineMixin:
    """给 `Verifier` 补上 Go 那台引擎的出口（见模块注释）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["engine"] = "go"
        super().__init__(*args, **kwargs)                     # type: ignore[misc]
        self._go: Simgo | None = None
        #: 这一路跑过的场次、累计耗时、以及**退回原版的次数**。
        #: 证据：目标那条"把 214 秒压下一个量级"要拿它们说话。
        self.go_runs = 0
        self.go_seconds = 0.0
        self.go_fallbacks = 0

    # ------------------------------------------------------------------ 引擎

    def _go_client(self) -> Simgo:
        """常驻一个 Go 子进程。

        搜索要跑上千场，每场起一次进程会把省下的时间又花在进程开销上——
        `Simgo` 本来就是**长连接**（一行请求一行回执），所以这里缓存它。
        """
        if self._go is None:
            self._go = Simgo(find_binary())
        return self._go

    def close(self) -> None:
        if self._go is not None:
            self._go.close()
            self._go = None

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ------------------------------------------------------------ 换引擎出口

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None):
        """`Verifier.run` 在 `engine != "python"` 时调到这里。

        ⚠ 规格必须在**跑之前**取：`build_spec` 读的是 `sim.life` / `sim.cost`
        这些"此刻"的字段，跑完之后 `life` 已经是 0，Go 收到一份 life=0 的规格会
        当场判负、一帧都不跑（这个坑实测撞过）。
        """
        spec = build_spec(sim, allow_devices=True, schedule=schedule, env=env)
        unsupported = list(spec.get("unsupported") or [])
        if unsupported:
            # 没移植的东西——**退回原版**，并且写清楚。
            self.go_fallbacks += 1
            res = sim.run(max_time=900.0)
            v = self._verdict(plan, stage, sim, res, deployed, title=title)
            v.diagnosis.append(
                "⚠ 本判决来自**原版 Python**：Go 侧还没移植这些字段 —— "
                + "、".join(unsupported)
                + "（这不是「两边一致」，是「没走 Go」）")
            return v

        started = time.perf_counter()
        got = self._go_client().sim(spec)
        self.go_seconds += time.perf_counter() - started
        self.go_runs += 1
        return self._verdict_from_go(plan, stage, got, deployed, title=title)

    def _verdict_from_go(self, plan, stage, got: dict, deployed, *, title="") -> Verdict:
        """把 Go 的回执变成判决。

        形状照着 `Verifier._verdict`：`rank()` 用到的五个量逐字对齐，其余照实标注。
        """
        max_life = int(getattr(stage.options, "max_life_point", 1) or 1)
        leak_events = [(float(t), str(name), int(cost))
                       for t, name, cost in (got.get("leak_events") or [])]
        ops = []
        for name, (at, pos, d, entry) in deployed.items():
            ops.append({
                "name": name, "time": at, "position": pos,
                "direction": d.direction, "skill": d.skill,
                "elite": entry["elite"], "level": entry["level"],
                # ⚠ Go 的回执里没有逐人出手数与承受伤害：**留 0 并标注**，
                # 不编数（显示的时候看得出来，`rank()` 也用不到）。
                "hits": 0, "alive": False, "hp": 0.0,
                "death_time": 0.0, "damage_taken": 0.0,
            })
        ops.sort(key=lambda x: x["time"])
        v = Verdict(
            stars=stars_of(bool(got["won"]), int(got["leaks"]),
                           challenge=bool(getattr(stage.options,
                                                  "is_hard_training", False))),
            won=bool(got["won"]), life=int(got["life"]), max_life=max_life,
            kills=int(got["kills"]), leaks=int(got["leaks"]),
            elapsed=float(got["elapsed"]), damage=float(got["damage_dealt"]),
            title=title or plan.title, operators=ops,
            leak_events=leak_events, result=got)
        v.diagnosis.append(
            "引擎：rios-sim（Go）。逐人战报里的**出手次数与承受伤害未回传**，留 0；"
            "判决的五个排序量（星级／生命／击杀／漏怪扣命／伤害）与原版同源。")
        if got.get("ms") is not None:
            v.diagnosis.append(f"Go 侧自称这一场用了 {float(got['ms']):.1f} ms。")
        return v


def ensure_go_engine(obj: Any) -> None:
    """把一个**裸 `Verifier`** 就地补成"能跑 Go"的那一份。

    ## 为什么必须有它

    `Verifier` 的默认引擎已经切成 `"go"`（博士 2026-09-19 裁定），可 Go 的出口
    本来**只挂在 `GoVerifier`（混入 `GoEngineMixin`）上**。于是全仓那些裸
    `Verifier()` 会**崩**在 `_run_other_engine` 的"基类没有这个能力"上，
    而不是跑 Go——**默认值一改就全仓崩**，这是实测撞到的，不是推的。

    ## 为什么绑实例、而不是改类或改继承

    * `verify.py` **不能** import `simgo`（`simgo.verifier` 反过来 import 了
      `verify`），循环。绑实例是惰性的，绕开了这条边。
    * 只有真正要跑 Go 的实例才付这份代价；而且 `GoVerifier` 那条路**完全不受影响**
      （它的类上本来就有这三个方法，绑上去的只是同名同实现）。

    绑的是混入类那三个方法 + 它 `__init__` 里那几个计数器。⚠ 漏掉任何一个，
    症状都是"跑到一半 AttributeError"，所以下面用一张表统一做，不手抄。
    """
    import types

    for name in ("_go_client", "_run_other_engine", "_verdict_from_go"):
        setattr(obj, name, types.MethodType(getattr(GoEngineMixin, name), obj))
    if "_go" not in obj.__dict__:
        obj._go = None
    #: 与 `GoEngineMixin.__init__` 逐项对齐：跑过的场次、累计耗时、退回原版的次数。
    for attr, init in (("go_runs", 0), ("go_seconds", 0.0), ("go_fallbacks", 0)):
        if attr not in obj.__dict__:
            setattr(obj, attr, init)


class GoVerifier(GoEngineMixin, Verifier):
    """完整版：排程照旧走原版，只有"跑这一场"换成 Go。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.engine != "go":                               # pragma: no cover
            raise ValueError("GoVerifier 的 engine 必须是 'go'")
