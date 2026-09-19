# -*- coding: utf-8 -*-
"""排程层的一致性判据：`Schedule` ≡ 模拟器（五个列表逐条比）。

用法：
    python tools\\sched_parity_check.py
    python tools\\sched_parity_check.py --plan out\\plan-hsex08.json

## 为什么要有它

目标②要求"把排程（部署/撤退/开技/费用）在**一层不依赖 `battle/`** 上实现"。
`frontend/schedule.py` 的 `Schedule` 已经写好、`verify.py` 也已经**同时写两份**
（`sched` 与 `sim`，方法名与参数逐字相同），注释里写着"一致性可用 `sched.diff(sim)` 核"。

⚠ **但 `diff()` 从来没有任何调用点**——全仓只有三处**注释**提到它。
⇒ "两边同时写"这件事**至今没有被证明过**：漏写一处就只会在切换那天暴露。
（这正是记忆 `68a8a308` 那一类："有实现、有测试、**零调用点**"。）

本工具把那个核对**跑起来**，并且是**逐份**跑：17 份里红哪几份必须看得见，
不是"总之一致"。全绿才说明"切过去只是不再调 `sim` 而已"这句话成立。

## 判据

对每一份夹具：在 `_run_other_engine` 那个挂载点上（`sim` 已排好程、还没跑），
`Schedule.diff(sim)` 必须返回**空列表**。

⚠ 挂载点借的是 `verify.py` 的现成位置，**不复制它的排程逻辑**——
复制出来的第二份必然漂移，而漂移的那一份恰恰是判据本身。
"""
from __future__ import annotations

import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.plan import Plan, Roster                         # noqa: E402
from ak_tactic.verify import Verifier                           # noqa: E402

FIXTURES = ROOT / "out"

#: 五个列表的名字，与 `Schedule.__init__` 逐字相同。
NAMES = ("deployments", "device_deployments", "summon_deployments",
         "retreats", "skill_uses")


def _probe_samples(sched):
    """按排程**现有内容**造 5 个合成条目——每条都用排程里已有的真实对象**形态**。

    ⚠ 只用"真实作业也可能出现的输入"（PM 转述的守则 / 记忆 `6e20b44e`：
    断言不许喂不可能的输入）。所以：
    * 部署：复用排程里第一条部署**本身**；
    * 撤退：复用该干员的坐标，时刻取它落地后 1 秒；
    * 开技：同坐标、同后 1 秒（`SkillUse` 的形状由 `Schedule.use_skill` 给出）；
    * 装置 / 召唤：排程里没有样本可借（本树无用例），用一个**最小的占位对象**——
      它们只被 `diff` 拿去比 `list` 相等，不参与任何机制结算。
    """
    from ak_tactic.frontend.schedule import Schedule as _S

    dep = sched.deployments[0] if sched.deployments else None
    pos = tuple(getattr(dep, "position", (0, 0))) if dep is not None else (0, 0)
    t0 = float(getattr(dep, "time", 0.0)) if dep is not None else 0.0

    #: `retreats` 两侧都是 `(时刻, 坐标)` 元组（`schedule.py:134`）。
    #: `skill_uses` 两侧都是 `SkillUse`——用排程自己的构造路径造，不手搓形状。
    probe = _S()
    probe.retreat(pos, t0 + 1.0)
    probe.use_skill(pos, t0 + 1.0)
    return {
        "deployments": dep,
        "retreats": probe.retreats[0],
        "skill_uses": probe.skill_uses[0],
        #: ⚠ 装置 / 召唤本树无任何样本，只能用最小占位。**它证明的是"这一列比得到"**，
        #: 不是"这条业务路对"——后者本树无法验收，已按 `act31side_07` 先例登记。
        "device_deployments": ("<合成:装置>",),
        "summon_deployments": ("<合成:召唤>",),
    }


def _inject_all(sched, sim, *, only: str | None = None) -> dict[str, int]:
    """把 5 个合成条目填进两边。`only` 给了就**只填一边**——那是反向守卫。

    ⚠ **同一个对象塞两侧**才是绿：`verify.py:454` 的原文口径就是
    "两边拿到同一批对象，`diff` 比出来的才是**排程**的差"。
    ⇒ 只塞一侧 ⇒ `diff` 必须报差 ⇒ 这就是"这一列红得起来"的证据。
    """
    samples = _probe_samples(sched)
    counts: dict[str, int] = {}
    for name in NAMES:
        obj = samples[name]
        if obj is None:
            continue
        if only != "sim":
            getattr(sched, name).append(obj)
        if only != "sched":
            getattr(sim, name).append(obj)
    for name in NAMES:
        counts[name] = len(getattr(sched, name, ()))
    return counts


def _inject_retreat(path: pathlib.Path) -> pathlib.Path:
    """把一份计划复制到 `out/_synth_*.json`，**加一条撤退**后再返回新路径。

    ⚠ 写到新文件名而不是改原夹具：金标准是基线，**不许为了测一条路去动夹具**。
    ⚠ 撤退的是第 1 个部署的干员、时刻取它落地后 1 秒：这样的命令在真实作业里
    也可能出现，不是"不可能的输入"（断言不许喂不可能的输入）。
    """
    import tempfile
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("deploys") or []
    if not rows:
        return path
    first = rows[0]
    who = first.get("operator") or first.get("name")
    when = float(first.get("time", 0.0)) + 1.0
    data["retreats"] = [{"operator": who, "time": when}]
    out = pathlib.Path(tempfile.gettempdir()) / ("rios_synth_" + path.name)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> int:
    args = sys.argv[1:]
    only = None
    if "--plan" in args:
        only = pathlib.Path(args[args.index("--plan") + 1]).resolve()
    synth = "--synthetic-retreat" in args
    synth_all = "--synthetic-all" in args
    #: `--negative-skip sched|sim|<列名>`：只填一边 / 只少填一列 —— 判据**必须**变红。
    neg = None
    if "--negative-skip" in args:
        neg = args[args.index("--negative-skip") + 1]
    elif "--negative-control" in args:
        neg = "deployments"

    plans = sorted(FIXTURES.glob("plan-*.json"))
    if only is not None:
        plans = [only]
    if synth or synth_all:
        #: ⚠ **反例**：本树 25 个作业**没有一个用 retreats**（全是 `deploys` 键），
        #: 于是 `撤退` 那一列永远是 `[] == []`——**空洞的绿**。
        #: 主用例全绿不等于对（记忆 `f58dace9`：须配第二组反例）。
        #: 这里把每份计划**就地加一条撤退**再比：只有真被填过，那一列才算检过。
        plans = [_inject_retreat(p) for p in plans]
    if not plans:
        print("  ⚠ out/ 里没有 plan-*.json")
        return 1

    if neg == "deployments" or (neg is not None and neg.startswith("dep")):
        #: ⚠ **反向守卫（部署列）**：让 `Schedule.plan()` 故意少记一条 ⇒
        #: `sched` 比 `sim` 少一笔部署，这个工具**必须**报出来。
        from ak_tactic.frontend.schedule import Schedule as _S
        _orig_plan = _S.plan

        def _drop(self, deployment):
            if not getattr(self, "_dropped", False):
                self._dropped = True          #: 只丢第一条，后面照常
                return
            return _orig_plan(self, deployment)

        _S.plan = _drop

    roster = Roster.empty()
    p = FIXTURES / "roster_max_modelled.json"
    if p.exists():
        roster = Roster.from_json(p)

    rows: list[tuple[str, list[str], dict[str, int]]] = []
    orig = Verifier._run_other_engine

    #: 当前正在跑的夹具名——由主循环设，挂在闭包里。不用 `rows[-1]` 反查：
    #: 那样一旦 `patched` 没被调到（路径不对），就会把上一份的结果**算成本份的**。
    current = {"name": "?"}

    #: 五个列表的名字，与 `Schedule.__init__` 逐字相同。
    NAMES = ("deployments", "device_deployments", "summon_deployments",
             "retreats", "skill_uses")

    def patched(self, *, sim, plan, stage, deployed, title,
                schedule=None, env=None, _o=orig):
        #: ⚠ `schedule` 就是 `verify.py` 同时写的那一份。它是 None 说明
        #: 这一条路径根本没在填排程——那也是差，而且是更大的差。
        if schedule is None:
            diffs = ["排程对象是 None（这条路径没填排程）"]
            counts: dict[str, int] = {}
        else:
            #: (b)：合成用例。`synth_all` 时给**五列**各填一条（同对象塞两侧 ⇒ 应当绿）；
            #: `neg` 指向某一列时**只填一边** ⇒ 那一列必须红（这就是"红得起来"的证据）。
            if synth_all or neg in ("sim", "sched") or neg in NAMES:
                only_side = neg if neg in ("sim", "sched") else None
                if neg in NAMES:
                    #: 只少填一列：把那一条从**排程侧**拿掉。
                    _inject_all(schedule, sim, only=None)
                    setattr(schedule, neg, [x for x in getattr(schedule, neg)][:-1])
                else:
                    _inject_all(schedule, sim, only=only_side)
            diffs = schedule.diff(sim)
            #: ⚠ **必须记条数**：五个列表若两边都是空的，`[] == []` 也报"一致"，
            #: 那是**空洞的绿**。这个重构里我已经栽过一次同型（判据看不见所断言之物）。
            counts = {n: len(getattr(schedule, n, []) or []) for n in NAMES}
        rows.append((current["name"], diffs, counts))
        raise SystemExit(0)

    Verifier._run_other_engine = patched
    try:
        for path in plans:
            current["name"] = path.name
            plan = Plan.from_dict(json.loads(path.read_text(encoding="utf-8")))
            try:
                Verifier(engine="go").run(plan, roster=roster)
            except SystemExit:
                pass
            if not rows or rows[-1][0] != path.name:
                #: 挂载点没被调到 = 这条路径**根本没走**（例如引擎不走 Go）。
                #: 必须显式记一笔，不能让它静默地不出现——那是"判据沉默"。
                rows.append((path.name, ["没有走到挂载点（这条路径没建立排程）"], {}))
    finally:
        Verifier._run_other_engine = orig

    #: 列头照 `Schedule.__init__` 的顺序：部署 / 装置 / 召唤 / 撤退 / 开技
    print(f"  {'夹具':<22} {'部署':>4} {'装置':>4} {'召唤':>4} {'撤退':>4} {'开技':>4}  判定")
    n_ok = n_total_entries = 0
    for name, diffs, counts in rows:
        n_total_entries += sum(counts.values())
        nums = "".join(f"{counts.get(k, 0):>5} " for k in
                       ("deployments", "device_deployments", "summon_deployments",
                        "retreats", "skill_uses"))
        if not diffs:
            n_ok += 1
            print(f"  {name:<22} {nums} ✅ 一致")
        else:
            print(f"  {name:<22} {nums} ⛔ {len(diffs)} 处差：")
            for d in diffs:
                print(f"      · {d}")

    print()
    print(f"  Schedule ≡ 模拟器 ：{n_ok}/{len(rows)}")
    print(f"  比到的排程条目合计：{n_total_entries} 条")
    if n_total_entries == 0:
        print("  ⛔ **空洞的绿**：一条排程都没比到，这个 17/17 什么都证明不了。")
        return 1

    #: ⚠ **每一列都要计数可见**（PM 转述的守则）：合成模式下某列若还是 0 条，
    #: 说明那一条**根本没被比到**——"没比到"与"一致"在输出上长得一样，必须分开判。
    if synth_all and neg is None:
        zero_cols = [k for k, v in (rows[-1][2] if rows else {}).items() if v == 0]
        if zero_cols:
            print(f"  ⛔ **空洞的绿**：这些列一条都没比到 ⇒ {zero_cols}")
            print("     （合成模式下仍为 0 = 注入没生效 / 列名不对，不是'一致'。）")
            return 1

    if n_ok != len(rows):
        print("  ⛔ **切过去之前**必须先把这些差补齐——"
              "否则切换当天才会发现排程少写了一处。")
        return 1
    print("  ✅ 排程层已等价：切过去只是不再调 `sim` 而已（PM #5 口径）。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
