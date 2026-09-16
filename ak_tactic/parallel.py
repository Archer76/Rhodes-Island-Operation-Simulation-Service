# -*- coding: utf-8 -*-
"""把「跑很多次模拟」摊到多个进程上。

## 为什么需要单独一层

搜索与参数扫描的共同点是：**同一个核跑上千次，每次之间零依赖**。单次模拟
在 1-7 上是 ~270 ms，一千次就是四分半钟，而机器有 16 个逻辑核只用了一个。

不能简单地把 `Verifier` 丢进进程池——它**不可 pickle**（内部持有
`_thread.lock`）。所以每个 worker 自己建一个，任务里只传纯数据。
好在 `Verifier()` 是惰性的（0.1 ms）、首次取关卡也只有 ~11 ms，
**单个 worker 的固定开销约 13 ms**，相对于动辄几十秒的批量任务可以忽略。

## 三条纪律

1. **结果与串行逐字一致**。返回值按输入顺序排好，不因为并行而让
   「同一批候选的排序」发生变化——搜索靠 `Verdict.rank()` 排序，
   顺序一变，beam 就可能选出不同的状态。
2. **失败不吞**。串行版 `_eval` 遇到异常返回 None（那条候选作废，
   搜索继续）；并行版保持同样语义，**异常一律降级为 None**，
   不许让一个 worker 的崩溃带走整轮搜索。
3. **小批量不并行**。进程池本身要几百毫秒才起来，任务数低于阈值时
   串行更快——这条不是优化，是防止「并行」在小任务上反而变慢。

## 用法

    from .parallel import eval_states
    results = eval_states("main_01-07", states, roster, sim_kwargs=kw)

`states` 是「一串候选元组」，每个元素是一条待验证的部署序列。
"""
from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from typing import Any, Sequence

__all__ = ["cpu_count", "plan_workers", "eval_states", "pmap", "shutdown",
           "PARALLEL_MIN_TASKS"]

#: 低于这么多条任务就串行——进程池的启动与分发开销盖过收益。
PARALLEL_MIN_TASKS = 12

#: 每批任务数的上界。实际批次大小按「任务数 ÷ (进程数×4)」动态算：
#: 固定批次会把并行度卡死——42 条任务按每批 8 条切成 6 批，就只有 6 个
#: 进程有活干，实测提速被压在 1.7×（应该接近核数）。批次取到
#: 「每进程 4 批」既能让负载均匀，又不至于把 IPC 往返摊得太薄。
_CHUNK = 8
_CHUNKS_PER_WORKER = 4


def cpu_count() -> int:
    """可用的逻辑核数。留一个给主进程，避免它自己也被调度走。"""
    return max(1, (os.cpu_count() or 1) - 1)


def plan_workers(tasks: int, *, workers: int | None = None) -> int:
    """这次用几个进程；返回 1 表示**走串行**。

    `workers=0` 或 `1` 表示明确要求串行（调用方要确定性、或在调试），
    `None` 表示用满核数。

    ⚠️ 返回值**只由 `workers` 与核数决定，不随 `tasks` 变**。池是跨调用复用的
    （见 `_pool_for`），池大小一变就得整个拆掉重建。所以"任务少"的处理是
    **直接退回串行**，而不是"开一个小池"——后者会让搜索的每一层因为候选数
    不同而各自建一次池，实测热池比冷池还慢。
    """
    if workers is not None:
        return max(1, int(workers))
    if tasks < PARALLEL_MIN_TASKS:
        return 1
    return cpu_count()


# ---------------------------------------------------------------- worker 侧

_WORKER: Any = None
#: 本次批量任务的公共上下文（关卡 / 名册 / 模拟开关）。
#: 放在 worker 里而不是每条任务里带着走——`roster` 对一份真实名册是几十 KB，
#: 42 条任务分 6 批就意味着它被 pickle 6 遍，纯属白花。
_CTX: tuple = ("", None, {})

# ---------------------------------------------------------------- 持久池
#
# 搜索是**逐层**调用批量的（每层一次），参数扫描是**逐档**调用。若每次调用都
# 建一个池再拆掉，那笔开销会按调用次数累加：实测 42 条任务 / 6.8 秒计算量下，
# 建池+初始化+收尾约占 2.5 秒，把 4 进程的提速从理论 4× 压到 1.5×。
# 所以池要**跨调用复用**，只在参数变了（进程数 / Verifier 开关 / 上下文）时重建。
_POOL: Any = None
_POOL_KEY: tuple | None = None


def _close_pool() -> None:
    global _POOL, _POOL_KEY
    if _POOL is not None:
        try:
            _POOL.shutdown(wait=True, cancel_futures=True)
        except Exception:                                # noqa: BLE001
            pass
    _POOL = None
    _POOL_KEY = None


def _pool_for(n: int, verifier_kwargs: dict, ctx: tuple):
    """取一个持久进程池；**参数变了才重建**。

    `n` 可以安全地进 key：`plan_workers` 保证它只随 `workers` 设置与核数变，
    不随任务量变，所以同一个调用方反复调用拿到的是同一个池。反过来，
    若让池大小跟着任务量走，搜索的每一层都会算出不同的 key，于是每层都把池
    拆掉重建（`shutdown(wait=True)` 还要等 worker 退干净）——实测那样热池
    比冷池还慢（15.3s vs 14.2s），并行的收益全被拆建吃掉。
    """
    global _POOL, _POOL_KEY
    key = (n, tuple(sorted(verifier_kwargs.items())),
           ctx[0], id(ctx[1]), tuple(sorted(ctx[2].items())))
    if _POOL is not None and _POOL_KEY == key:
        return _POOL
    _close_pool()
    _POOL = ProcessPoolExecutor(max_workers=n, initializer=_init_worker,
                               initargs=(verifier_kwargs, ctx))
    _POOL_KEY = key
    return _POOL


def shutdown() -> None:
    """收掉持久池。脚本退出时由 `atexit` 自动调用，也可手动调。"""
    _close_pool()


import atexit                                                    # noqa: E402

atexit.register(_close_pool)


def _init_worker(verifier_kwargs: dict, ctx: tuple) -> None:
    """在 worker 进程里建一个 Verifier，**一辈子只建这一次**。

    不放在 `_eval_chunk` 里，是因为池会反复调用它；每次重建会把
    「复用载入」这个前提整个丢掉。
    """
    global _WORKER, _CTX
    from .verify import Verifier
    _WORKER = Verifier(**verifier_kwargs)
    _CTX = ctx


def _eval_one(stage_id: str, state: Sequence, roster: Any,
              sim_kwargs: dict) -> tuple | None:
    """求一条方案。语义与 `Searcher._eval` 一致：失败返回 None。"""
    from .plan import Plan, DeployOrder, PlanError

    deploys = []
    for c in state:
        kw: dict[str, Any] = {}
        if roster is not None:
            e = roster.get(c.operator) or {}
            for src, dst in (("elite", "elite"), ("level", "level"),
                             ("potential", "potential"), ("trust", "trust"),
                             ("module", "module"),
                             ("module_level", "module_level")):
                if e.get(src) is not None:
                    kw[dst] = e[src]
        deploys.append(DeployOrder(c.operator, c.position, c.direction,
                                   skill=c.skill, mastery=c.mastery, **kw))
    plan = Plan(stage=stage_id, deploys=deploys, title=f"{len(state)} 人")
    try:
        plan.validate()
    except PlanError:
        return None
    try:
        v = _WORKER.run(plan, roster=roster, **sim_kwargs)
    except Exception:                                    # noqa: BLE001
        return None
    return (v.rank(), tuple(state), plan, v)


def _eval_chunk(states: list) -> list:
    """批量求值——**一次投递多条**，把 IPC 往返摊薄。

    关卡、名册、模拟开关都从 `_CTX` 取（由 initializer 设好），
    投递的载荷里只有待求值的状态本身，那是几百字节。
    """
    stage_id, roster, sim_kwargs = _CTX
    out: list = []
    for st in states:
        try:
            out.append(_eval_one(stage_id, st, roster, sim_kwargs))
        except Exception:                                # noqa: BLE001
            out.append(None)
    return out


def _chunk_size(tasks: int, workers: int) -> int:
    """动态批次大小——保证每个进程至少能分到几批，负载才摊得匀。"""
    if workers <= 1:
        return max(1, tasks)
    return max(1, min(_CHUNK, -(-tasks // (workers * _CHUNKS_PER_WORKER))))


# ---------------------------------------------------------------- 公开入口

def eval_states(stage_id: str, states: Sequence[Sequence],
                roster: Any, *,
                sim_kwargs: dict | None = None,
                verifier_kwargs: dict | None = None,
                workers: int | None = None) -> list:
    """并行求值一批状态，**返回与输入同序**的结果（失败项为 None）。

    `states` 里的元素是「一条部署序列」（候选元组的 tuple）。
    """
    states = list(states)
    if not states:
        return []
    sim_kwargs = dict(sim_kwargs or {})
    verifier_kwargs = dict(verifier_kwargs or {})

    n = plan_workers(len(states), workers=workers)
    ctx = (stage_id, roster, sim_kwargs)
    if n <= 1:
        # 串行路径也要能独立跑通——它顺便保证了「并行开关关掉时结果不变」
        _init_worker(verifier_kwargs, ctx)
        return _eval_chunk(states)

    size = _chunk_size(len(states), n)
    chunks = [states[i:i + size] for i in range(0, len(states), size)]
    pool = _pool_for(n, verifier_kwargs, ctx)
    out: list = []
    for part in pool.map(_eval_chunk, chunks):
        out.extend(part)
    return out


# ---------------------------------------------------------------- 通用批处理

_PMAP_FUNC: Any = None


def _pmap_init(func: Any, init: Any, initargs: tuple) -> None:
    global _PMAP_FUNC
    _PMAP_FUNC = func
    if init is not None:
        init(*initargs)


def _pmap_chunk(items: list) -> list:
    f = _PMAP_FUNC
    return [f(it) for it in items]


def pmap(func: Any, items: Sequence, *, workers: int | None = None,
         init: Any = None, initargs: tuple = (), key: str = "") -> list:
    """把 `func` 摊到多个进程上，返回与 `items` 同序的结果。

    与 `eval_states` 的分工：那个是搜索器专用的（worker 里建 `Verifier`），
    这个给「N 组参数各跑一次」的**参数扫描**用——敏感度分析里那些
    `speed_scale × sword_qi_speed × enemy_windup` 的笛卡尔积就走它。

    三条约束：

    * `func` 必须是**模块级函数**。Windows 只有 spawn，子进程靠「模块名 +
      函数名」把它找回来，闭包与 lambda 投不过去。
    * `items` 里每一项都要可 pickle。
    * `init` / `initargs` 是每个 worker **建一次**的准备工作（关卡、敌人库、
      名册、技能书）。这些千万别放进 `items` 逐条传——那等于每条任务都把
      几十 KB 的共同前提 pickle 一遍，正是 `_CTX` 要避免的事。

    `key` 用来标识「同一套 init」的池；同一个 key 反复调用复用同一个池，
    key 变了才重建。扫描时按 `key="srx8-sweep"` 这样给个稳定名即可。

    某一项抛异常会**直接中止整批**（不像 `eval_states` 那样降级为 None）——
    扫描里出错应该立刻看见，而不是拿到一堆看着正常的空值。
    """
    items = list(items)
    if not items:
        return []
    n = plan_workers(len(items), workers=workers)
    if n <= 1:
        _pmap_init(func, init, initargs)
        return _pmap_chunk(items)

    size = _chunk_size(len(items), n)
    chunks = [items[i:i + size] for i in range(0, len(items), size)]
    global _POOL, _POOL_KEY
    pool_key = ("pmap", key, n)
    if _POOL is None or _POOL_KEY != pool_key:
        _close_pool()
        _POOL = ProcessPoolExecutor(max_workers=n, initializer=_pmap_init,
                                   initargs=(func, init, initargs))
        _POOL_KEY = pool_key
    out: list = []
    for part in _POOL.map(_pmap_chunk, chunks):
        out.extend(part)
    return out
