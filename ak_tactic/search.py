# -*- coding: utf-8 -*-
"""搜索器：给定关卡与名册，找出一套能三星的阵容 + 落位 + 朝向 + 时机。

README「阶段 5 · 求解与搜索」的后半段。搜索空间是

    格子 × 干员 × 朝向 × 部署时机 × 技能时机

## 两层结构（这是本模块唯一的要旨）

一次完整模拟是秒级的，**不能拿它当内循环**。所以：

* **第一层：几何剪枝（不算打架）**。用 `ak_tactic.eta` 的到达时刻表算出
  每个「干员 × 格子 × 朝向」的攻击格集合里累计有多少**敌人·秒**，
  再乘上干员的攻击力当作价值上界。dwell 为零的落位连试都不必试——
  敌人的路线根本不经过那里。这一层把候选从
  「460 干员 × 数百格 × 4 朝向」压到每关几十个。

* **第二层：beam search（用模拟器评估）**。状态 = 一个有序的部署列表
  （顺序即落地顺序，因此也决定费用曲线）。每层把候选接到状态末尾，
  跑验证器，按 `Verdict.rank()` 排序，留前 `beam` 个。

部署时机用「钱够了就下」（与 MAA 自动作战同规则），技能用自动开启。
两者都是**可被 Plan 覆盖**的默认：搜索给出的是一个能跑的起点，
不是终点。

## 为什么按"加一个人"而不是"同时选一套阵容"

同时选阵容是组合爆炸（460 选 4 ≈ 1.8 亿），而且大部分组合在费用上
根本下不去。逐个追加天然尊重费用曲线——**先下的便宜、后下的贵**，
这与实机打法是同一个顺序。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Sequence

from .eta import ArrivalIndex, enemy_arrivals, route_plans
from .parallel import PARALLEL_MIN_TASKS, eval_states
from .plan import DeployOrder, Plan, PlanError, Roster
from .verify import Verdict, Verifier

__all__ = ["Candidate", "SearchResult", "Searcher", "candidates_for",
           "search"]

DIRECTIONS = ("Right", "Left", "Up", "Down")


@dataclass(frozen=True)
class Candidate:
    """一个候选落位：谁、站哪、朝哪、带哪个技能。"""

    operator: str
    char_id: str
    position: tuple[int, int]
    direction: str
    skill: int = 0
    mastery: int = 0
    #: 攻击格集合里累计的敌人·秒（几何上界）
    dwell: float = 0.0
    #: 攻击格集合里会经过的敌人次数
    visits: int = 0
    #: 排序用的价值 = dwell × 攻击力（粗略的"能打出多少活"）
    value: float = 0.0
    cells: frozenset = frozenset()

    def __str__(self) -> str:
        return (f"{self.operator}@{self.position}{self.direction[0]}"
                f"技能{self.skill} dwell={self.dwell:.1f}")


@dataclass
class SearchResult:
    """搜索结果。`plan` 为 None 表示在给定预算内没找到三星方案。"""

    plan: Plan | None = None
    verdict: Verdict | None = None
    #: 逐层的 beam 摘要（每层前几名），用于解释搜索怎么走的
    steps: list[dict[str, Any]] = field(default_factory=list)
    evaluated: int = 0
    depth: int = 0
    note: str = ""

    @property
    def ok(self) -> bool:
        return self.plan is not None and self.verdict is not None \
            and self.verdict.stars == 3

    def report(self) -> str:
        out = [f"搜索：评估 {self.evaluated} 个方案，最深 {self.depth} 人"]
        for s in self.steps:
            top = s.get("top") or []
            head = "、".join(f"{t['who']}" for t in top[:3])
            out.append(f"  第 {s['depth']} 人：{s['tried']} 个候选，"
                       f"最佳 {s['best']}  ——{head}")
        if self.ok:
            out.append("")
            out.append(self.verdict.report())
        else:
            out.append(self.note or "没找到三星方案（可加大 --beam / --per-op）")
        return "\n".join(out)


# ---------------------------------------------------------------- 候选生成

def _range_cells(verifier: Verifier, stage, char_id: str, elite: int,
                 direction: str, position: tuple[int, int]) -> frozenset:
    prov = verifier.range_provider(stage)
    try:
        return frozenset(prov(char_id, elite, direction, position))
    except Exception:                                    # noqa: BLE001
        return frozenset()


def candidates_for(
    verifier: Verifier,
    stage_id: str,
    roster: Roster,
    operators: Sequence[str],
    *,
    index: ArrivalIndex | None = None,
    cells: Iterable[tuple[int, int]] | None = None,
    per_op: int = 6,
    directions: Sequence[str] = DIRECTIONS,
    skill_of: Callable[[str], tuple[int, int]] | None = None,
) -> list[Candidate]:
    """给每个干员挑出最值钱的若干落位 × 朝向。

    价值 = `dwell × 攻击力`。dwell 是敌人在这片格子上累计待的秒数——
    **这就是"这个位置能不能接到活"的几何上界**，不需要跑模拟。
    乘攻击力是把它粗化成"能打出多少伤害"，否则一个高台奶妈会和
    一个术师排在同样的名次上。
    """
    stage = verifier.stage(stage_id)
    if index is None:
        index = ArrivalIndex(enemy_arrivals(stage, verifier.library(stage).get))
    if cells is None:
        cells = list(stage.map.melee_spots) + list(stage.map.ranged_spots)
    cells = list(cells)
    skill_of = skill_of or (lambda _n: (0, 0))

    out: list[Candidate] = []
    for name in operators:
        entry = roster.get(name)
        if entry is None:
            continue
        cid = entry.get("char_id") or verifier._by_name(name)
        if not cid:
            continue
        elite = int(entry.get("elite") or 0)
        melee = verifier.is_melee(cid)
        spots = stage.map.melee_spots if melee else stage.map.ranged_spots
        try:
            unit = verifier.unit({**entry, "char_id": cid})
        except Exception:                                # noqa: BLE001
            continue
        slot, mastery = skill_of(name)
        local: list[Candidate] = []
        for pos in cells:
            if pos not in spots:
                continue
            for d in directions:
                cs = _range_cells(verifier, stage, cid, elite, d, pos)
                if not cs:
                    continue
                dwell = index.dwell(cs)
                if dwell <= 0:
                    # **几何上就接不到任何敌人**——这一条剪掉的候选最多
                    continue
                local.append(Candidate(
                    operator=name, char_id=cid, position=tuple(pos),
                    direction=d, skill=slot, mastery=mastery,
                    dwell=dwell, visits=index.count(cs),
                    value=dwell * float(unit.atk), cells=cs))
        local.sort(key=lambda c: -c.value)
        # 同一个站位的四个朝向只留最好的那个：站同一格换朝向不值得各试一遍
        seen: set[tuple[int, int]] = set()
        kept = []
        for c in local:
            if c.position in seen:
                continue
            seen.add(c.position)
            kept.append(c)
            if len(kept) >= per_op:
                break
        out.extend(kept)
    out.sort(key=lambda c: -c.value)
    return out


# ---------------------------------------------------------------- 搜索

class Searcher:
    """两层搜索：几何剪枝 → beam search。"""

    def __init__(self, verifier: Verifier | None = None, *,
                 verbose: bool = False, sim_kwargs: dict | None = None,
                 workers: int | None = None,
                 verifier_kwargs: dict | None = None) -> None:
        self.verifier = verifier or Verifier()
        self.verbose = verbose
        #: 透传给模拟器的开关（`boss_mode_switch` / `speed_scale` 之类）
        self.sim_kwargs = dict(sim_kwargs or {})
        #: 用几个进程跑这一轮搜索。`None` = 按每层候选数自动定，`1` = 强制串行。
        self.workers = workers
        #: **worker 必须用与主进程完全相同的开关建 Verifier**，否则并行结果会
        #: 与串行分叉——`effect_source` 从 merge 换成 desc 就改了伤害口径，
        #: `use_range_table` 一关攻击范围就退化。从现成的 Verifier 反推，
        #: 不要求调用方重复声明；显式传入则以传入的为准。
        self.verifier_kwargs = (dict(verifier_kwargs) if verifier_kwargs
                                is not None else {
                                    "effect_source": self.verifier.effect_source,
                                    "use_range_table": self.verifier.use_range_table,
                                    "verbose": self.verifier.verbose,
                                })
        self.evaluated = 0

    # -------------------------------------------------- 内部

    def _plan(self, stage_id: str, state: Sequence[Candidate],
              title: str = "", roster: Roster | None = None) -> Plan:
        """把候选序列翻成打法。

        给了 `roster` 就**把用到的练度一并写进去**（精英/等级/潜能/信赖/
        模组）——否则存下来的打法一离开名册就跑不了。搜索结果应当自足：
        拿到 JSON 的人不必再有一份相同的名册。
        """
        deploys = []
        for c in state:
            kw: dict[str, Any] = {}
            if roster is not None:
                e = roster.get(c.operator) or {}
                for src, dst in (("elite", "elite"), ("level", "level"),
                                 ("potential", "potential"),
                                 ("trust", "trust"),
                                 ("module", "module"),
                                 ("module_level", "module_level")):
                    if e.get(src) is not None:
                        kw[dst] = e[src]
            deploys.append(DeployOrder(c.operator, c.position, c.direction,
                                       skill=c.skill, mastery=c.mastery, **kw))
        return Plan(stage=stage_id, deploys=deploys,
                    title=title or f"{len(state)} 人")

    def _eval(self, stage_id: str, state: Sequence[Candidate],
              roster: Roster) -> tuple[tuple, tuple, Plan, Verdict] | None:
        plan = self._plan(stage_id, state, roster=roster)
        try:
            plan.validate()
        except PlanError:
            return None
        try:
            v = self.verifier.run(plan, roster=roster, **self.sim_kwargs)
        except Exception:                                # noqa: BLE001
            return None
        self.evaluated += 1
        # 状态必须跟着一起回来：排序键是 rank，不是状态本身
        return (v.rank(), tuple(state), plan, v)

    def _eval_many(self, stage_id: str, states: Sequence[Sequence[Candidate]],
                   roster: Roster) -> list:
        """求值一层里的全部状态，返回成功项（失败项按串行的语义丢弃）。

        并行与串行**必须给出同一组结果**，所以这里只有一处分支差异：走进程池
        还是走本进程。`eval_states` 保证「与输入同序、失败为 None」，
        `_eval` 保证「失败返回 None」，两条路的输出因此同构。
        """
        from .parallel import plan_workers

        states = list(states)
        if not states:
            return []
        n = plan_workers(len(states), workers=self.workers)
        if n <= 1:
            out = []
            for st in states:
                got = self._eval(stage_id, st, roster)
                if got is not None:
                    out.append(got)
            return out
        # `evaluated` 在串行路里由 `_eval` 自己加，并行路里 worker 加不到主进程
        # 的计数器上，只能在这里补——两条路的计数口径都是「成功求值的条数」。
        results = eval_states(stage_id, states, roster,
                              sim_kwargs=self.sim_kwargs,
                              verifier_kwargs=self.verifier_kwargs,
                              workers=n)
        ok = [g for g in results if g is not None]
        self.evaluated += len(ok)
        return ok

    # -------------------------------------------------- 主入口

    def search(
        self,
        stage_id: str,
        roster: Roster,
        operators: Sequence[str],
        *,
        max_ops: int = 4,
        beam: int = 5,
        per_op: int = 6,
        min_ops: int = 1,
        skill_of: Callable[[str], tuple[int, int]] | None = None,
        cells: Iterable[tuple[int, int]] | None = None,
        on_step: Callable[[dict], None] | None = None,
    ) -> SearchResult:
        """从空阵容开始，逐人追加，直到三星或到达 `max_ops`。

        `beam` 是每层保留的状态数，`per_op` 是每个干员的候选落位数。
        总模拟次数上界 ≈ `beam × 候选数 × max_ops`，实际远小于它
        （`beam` 越大越接近这个上界，越小越省）。
        """
        stage = self.verifier.stage(stage_id)
        index = ArrivalIndex(
            enemy_arrivals(stage, self.verifier.library(stage).get))
        cands = candidates_for(
            self.verifier, stage_id, roster, operators, index=index,
            cells=cells, per_op=per_op, skill_of=skill_of)
        if not cands:
            return SearchResult(
                note="几何剪枝后一个候选都不剩——所有干员的攻击范围都罩不到"
                     "敌人的行进路线。先核对落位坐标口径（MAA，原点左上）")

        result = SearchResult()

        #: 状态 = 已选候选的元组（顺序即落地顺序）；按 rank 从好到坏排
        beam_states: list[tuple[tuple, tuple, Plan, Verdict]] = []
        overall: tuple[tuple, tuple, Plan, Verdict] | None = None
        depth = 0
        for depth in range(1, max_ops + 1):
            tried = 0
            # 空状态用 () 起步，之后每层从上一层的 beam 展开
            seeds: list[tuple] = ([tuple()] if not beam_states
                                  else [s[1] for s in beam_states])
            # 先把这一层**所有**待求值状态收集起来，再整批投出去。
            # 逐条求值会把并行退化成「一次一条」，IPC 往返与进程调度会盖过
            # 收益（实测只有 1.5×）；整批投递后同一批任务能到 4.8–7.4×。
            # 这一层是搜索里唯一的重活，也是唯一值得并行的位置。
            states: list[tuple] = []
            for seed in seeds:
                used_ops = {c.operator for c in seed}
                used_pos = {c.position for c in seed}
                for cand in cands:
                    if cand.operator in used_ops or cand.position in used_pos:
                        continue
                    tried += 1
                    states.append(seed + (cand,))
            pool = self._eval_many(stage_id, states, roster)
            if not pool:
                result.note = f"第 {depth} 人时已经没有可加的位置了"
                break

            # 去重：**同一套人不同顺序**算近似重复（费用曲线不同，但差别
            # 小于噪声），留排名最高的那个。不去重的话 beam 会被
            # "同一批人的各种排列"占满，多样性归零。
            pool.sort(key=lambda x: x[0], reverse=True)
            seen: set[frozenset] = set()
            uniq: list[tuple[tuple, tuple, Plan, Verdict]] = []
            for item in pool:
                key = frozenset((c.operator, c.position) for c in item[1])
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(item)

            beam_states = uniq[: beam]
            best = beam_states[0]
            # **跨层保留最好的**：多加一个人未必更好——费用曲线会被推后。
            # SR-EX-8 上"加机械师反而失败"（21 费排在前面，把部署线推后 20 秒）
            # 就是这一类。只交最后一层会把这个退步当成结果报出去。
            if overall is None or best[0] > overall[0]:
                overall = best
            step = {
                "depth": depth, "tried": tried, "kept": len(uniq),
                "best": best[3].line(),
                "top": [{"who": str(c)} for c in best[1]],
            }
            result.steps.append(step)
            result.depth = depth
            if on_step is not None:
                on_step(step)
            if best[3].stars == 3 and depth >= min_ops:
                result.plan = best[2]
                result.verdict = best[3]
                result.evaluated = self.evaluated
                return result
        result.evaluated = self.evaluated
        if overall is not None:
            # 没找到三星，把**所有层里**最好的交出去（至少让人看见差在哪）
            result.plan = overall[2]
            result.verdict = overall[3]
            result.note = (f"在 {max_ops} 人以内没找到三星；最好的是 "
                           f"{len(overall[1])} 人方案——"
                           f"{overall[3].line()}")
        return result


def search(stage_id: str, roster: Roster, operators: Sequence[str],
           **kw) -> SearchResult:
    """一次性的便捷入口（会现建 Verifier，适合单次调用）。"""
    return Searcher(**{k: kw.pop(k)
                       for k in ("verbose", "sim_kwargs", "workers",
                                 "verifier_kwargs")
                       if k in kw}).search(stage_id, roster, operators, **kw)
