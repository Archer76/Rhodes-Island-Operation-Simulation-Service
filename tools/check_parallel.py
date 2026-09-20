# -*- coding: utf-8 -*-
"""并行层的自检：钉住「并行不改变结果」与几个容易复发的调度缺陷。

跑法：`python tools/check_parallel.py`

这里的三类断言分别对应三件真踩过的事：

1. **结果不变**。并行只是把同一份计算搬到别的进程，逐条战绩必须与串行
   逐字相同。这条一旦松掉，搜索的 beam 会选出不同的状态，整条搜索链
   静默跑偏（而且跑出来的还是一份"看着能过"的方案）。
2. **池大小稳定**。`plan_workers` 曾经跟着任务量返回不同进程数，而池是
   跨调用复用的——搜索每一层的候选数不同，于是每层都把池拆了重建，
   热池比冷池还慢（15.3s vs 14.2s）。
3. **小批量走串行**。进程池的启动开销在小任务上盖过收益，门槛必须真的
   拦得住，而不是"开了个小池"。
"""
from __future__ import annotations

import glob
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

from ak_tactic import parallel                                          # noqa: E402
from ak_tactic.plan import Roster                                        # noqa: E402
from ak_tactic.search import candidates_for                              # noqa: E402
from ak_tactic.verify import Verifier                                    # noqa: E402

FAILED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ✓ {label}" + (f"  {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  ✗ {label}  {detail}")


def _roster_path() -> str | None:
    hits = sorted(glob.glob(str(ROOT / "data" / "skland" / "roster_*.json")))
    return hits[0] if hits else None


# ---------------------------------------------------------------- 调度契约

def section_scheduling() -> None:
    print("[1] 进程数与批次大小的调度契约")
    cpu = parallel.cpu_count()
    check("cpu_count 至少留一核给主进程",
          cpu == max(1, (parallel.cpu_count())), f"cpu={cpu}")

    check("低于门槛 → 串行",
          parallel.plan_workers(3) == 1, f"3 条任务 → {parallel.plan_workers(3)} 进程")
    check("跨过门槛 → 铺满核数",
          parallel.plan_workers(1000) == cpu,
          f"1000 条任务 → {parallel.plan_workers(1000)} 进程")
    check("显式 workers 优先于门槛",
          parallel.plan_workers(3, workers=4) == 4)
    check("workers=1 强制串行",
          parallel.plan_workers(1000, workers=1) == 1)

    # 这条是池复用的前提：同一套设置下，进程数不能随任务量变。
    a, b = parallel.plan_workers(50), parallel.plan_workers(5000)
    check("进程数不随任务量变（池复用前提）", a == b,
          f"50 条 → {a}，5000 条 → {b}")

    n = 8
    sizes = [parallel._chunk_size(t, n) for t in (16, 100, 1000)]
    check("批次大小随任务量放大且不超上界",
          sizes[0] <= sizes[1] <= sizes[2] <= parallel._CHUNK, f"{sizes}")


# ---------------------------------------------------------------- 结果等价

def _double(x: int) -> int:
    """模块级、可 pickle 的测试函数——spawn 靠「模块名 + 函数名」找回它。"""
    return x * 2


def section_pmap() -> None:
    print("\n[2] 通用批处理 pmap")
    got = parallel.pmap(_double, list(range(12)), workers=1)
    check("串行路逐项正确", got == [i * 2 for i in range(12)], f"{got[:5]}…")

    parallel.shutdown()
    got = parallel.pmap(_double, list(range(40)))
    check("并行路同序且逐项正确", got == [i * 2 for i in range(40)],
          f"共 {len(got)} 项")
    check("空输入直接返回空", parallel.pmap(_double, []) == [])


def section_equivalence() -> None:
    print("\n[3] 并行求值 = 串行求值（逐字）")
    path = _roster_path()
    if path is None:
        print("  · 跳过：data/skland/ 下没有名册（该目录不入库，需先 tools/skland.py fetch）")
        return

    roster = Roster.from_json(path)
    v = Verifier()
    ops = [n for n in ("阿米娅", "德克萨斯", "拉普兰德", "能天使",
                       "白面鸮", "调香师", "玫兰莎") if roster.get(n)]
    states = [(c,) for c in candidates_for(v, "main_01-07", roster, ops, per_op=4)]
    check("候选数够触发并行", len(states) >= parallel.PARALLEL_MIN_TASKS,
          f"{len(states)} 条（门槛 {parallel.PARALLEL_MIN_TASKS}）")
    if len(states) < parallel.PARALLEL_MIN_TASKS:
        return

    parallel.shutdown()
    ser = parallel.eval_states("main_01-07", states, roster, workers=1)
    par = parallel.eval_states("main_01-07", states, roster, workers=None)
    parallel.shutdown()

    check("条目数相同", len(ser) == len(par), f"{len(ser)} vs {len(par)}")
    check("失败项的分布相同",
          [x is None for x in ser] == [x is None for x in par])
    ok = all((a is None) == (b is None) and (a is None or a[0] == b[0])
             for a, b in zip(ser, par))
    check("排序键 rank 逐条相同", ok)
    lines_a = [a[3].line() if a else None for a in ser]
    lines_b = [b[3].line() if b else None for b in par]
    check("战绩文本逐条相同", lines_a == lines_b)
    # 顺序也要一样：搜索靠这个顺序做 beam 截断。
    check("返回顺序与输入同序", all(
        (a is None or a[1] == st) for a, st in zip(ser, states)))


def main() -> int:
    print("并行层自检\n")
    section_scheduling()
    section_pmap()
    section_equivalence()
    parallel.shutdown()
    print()
    if FAILED:
        print(f"失败 {FAILED} 项。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    #: ★ 判据的输出不许依赖终端编码（2026-09-20 修，PM 裁定 msg-mu9cwt89-ll 第二节）。
    #: 本机 `sys.stdout.encoding` **默认就是 gbk**（PYTHONIOENCODING 未设），而本文件的输出里
    #: 含 ✓／✗／⇒／− 等 GBK **编不出**的字符 ⇒ **印总结行时**抛 UnicodeEncodeError
    #: ⇒ 退出码由崩溃给出：实测改前**恒 rc=1**，与它要判的东西毫无关系
    #: （＝一个从不发光的守卫；PM 每次 push 前的「tools/check_*.py 全绿」判据因此失去分辨力）。
    #: 只放宽错误处理器、**不改编码**：编不出的字符退化成转义文本，信息不丢，既有输出形状一字未动。
    #: ★ 全部写在 `__main__` 里：作为模块被 import 时行为**一字不变**。
    import sys as _sys
    try:
        _sys.stdout.reconfigure(errors="backslashreplace")
    except Exception:  # noqa: BLE001 - 不支持 reconfigure 的流 ⇒ 不适用，继续
        pass
    try:
        _rc = main()
    except BaseException as _e:  # noqa: BLE001 - 崩了必须是**与业务态不重叠**的一个值
        print(f"VERDICT=SELFCHECK_CRASH EXC={type(_e).__name__}: {_e}")
        _rc = 5
    #: ASCII 机读判定行：rc 从此是它自己的结论（0 无失败／1 有失败／5 没能判定）。
    print(f"VERDICT={'PASS' if _rc == 0 else 'FAIL'} rc={_rc}")
    raise SystemExit(_rc)
