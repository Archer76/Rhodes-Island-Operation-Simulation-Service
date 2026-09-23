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
from . import find_binary
from .client import Simgo

__all__ = ["GoEngineMixin", "GoVerifier", "GATE_ALLOW_DEVICES", "GATE_ALLOW_SKILLS",
           "GATE_RULING_REF", "gate_declaration"]


# ============================================================================
# ★★ 本次读数的**闸门口径** —— PM 裁定④（2026-09-20）「走乙」
# ============================================================================
#
# 这三行是**唯一的那一份口径**：`_run_other_engine` 从这里读，产物从
# `gate_declaration()` 抄。**改这里就会改跑出来的那一场**，所以它不是装饰。
#
# ## 现状（已知的、有意的，不是 bug）
#
# `_run_other_engine` 对**所有关卡**一律 `allow_devices=True`，而 `simgo/spec.py:112-123`
# 写明这个口子**本来要带证据开**：只在实测过「把 `_device_tick`（建成 / AuraHit 进入
# 触发 / 被拆后把地形还回去）与 `_pile_tick`（天桩链）**换成空操作之后判决一字不变**」
# 时才许传 True。
#
# ⇒ **凡是带装置的关，它的 Go 读数是在「装置运行期被关掉」的前提下取的。**
#    实测规模（穷举，不是抽样）：主线 433 行里 **196 行（45.3%）带装置** ——
#    尺子 `tools/mainline_devices.py`（content sha16 `8C429C47E1DF7464`），
#    表与按章分布见 `docs/mainline-stages.md` §九。**装置不是罕见个例。**
#
# ## 为什么保留一刀切（为什么没走「甲」）
#
# * **甲**＝关掉它、改成按证据的关卡白名单 ⇒ 那 196 行当场从「可跑」变「拒跑」，
#   而甲的前提是**先把 196 关的装置运行期建起来、或逐关补取证** —— 那是另一条线的工作量，
#   不该压在这里，也**不该用一个大洞换一个小洞**。
# * **乙**（本裁定）＝保留行为，但把口径**逐份记进产物**（`tools/golden_go.py` 的 `gate` 栏）
#   ⇒ 读数不失效，而 45.3% 这个数**从「藏着」变成「印出来」**。
#
# ## ⚠ 下一个人：请**不要**顺手把这里改成甲
#
# 那是另一个决定。改它要连 196 关的建模一起做；单独改掉只会让近一半主线关
# 当场拒跑，而**没有任何东西会红**（这正是乙要堵的那个静默）。
#
# ## 这个口径有判据撑着（不是只写在注释里）
#
# `tools/golden_go.py`：
#   * 每份产物的 `gate` 栏与这里**逐位比对**，不符即 rc≠0；
#   * 基线里**缺 `gate` 栏**即 rc≠0；
#   * `--gate-selftest` 是它的反向守卫（合成缺栏/改口径，必须变红）。
GATE_ALLOW_DEVICES = True
GATE_ALLOW_SKILLS = False
#: 指向裁定本身，让机器可读的那一栏能被人追回来。
GATE_RULING_REF = "PM 裁定④ 2026-09-20 走乙（docs/mainline-stages.md §九；甲方前提＝196 关建模）"


def gate_declaration(*, provenance: str = "run") -> dict:
    """本次读数的闸门口径，**机器可读**（要和四项读数同屏，不许只活在散文里）。

    `provenance` 是**两值**，不许压成一个：

    * `"run"` —— 这一栏来自**这一次真跑**（`run_one` 现场抄的）。
    * `"backfill"` —— 这一栏是**2026-09-20 回填**的：那些基线录的时候还没有这一栏。
      回填有据且已取证：`allow_devices=True` 只在 `046944a`（2026-09-19）进来过一次，
      而首个基线提交 `3bab699` **是它的后代**、当时 `verifier.py` 已经是 `True`
      ⇒ **23 份基线全部是在这个口径下录的**，不存在"某份是 False 录的"。
    """
    return {
        "allow_devices": GATE_ALLOW_DEVICES,
        "allow_skills": GATE_ALLOW_SKILLS,
        "ruling_ref": GATE_RULING_REF,
        "provenance": provenance,
    }


class GoEngineMixin:
    """给 `Verifier` 补上 Go 那台引擎的出口（见模块注释）。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs["engine"] = "go"
        super().__init__(*args, **kwargs)                     # type: ignore[misc]
        self._go: Simgo | None = None
        #: 这一路跑过的场次、累计耗时、以及**退回原版的次数**。
        #: 证据：目标那条「把 214 秒压下一个量级」要拿它们说话。
        self.go_runs = 0
        self.go_seconds = 0.0
        #: ⚠ **语义已变**（2026-09-23）：以前是「回退去跑原版 Python 模拟器」的次数，
        #: 现在是「**具名拒跑**」的次数（`unsupported` 非空 ⇒ 不跑，把理由列全）。
        #: 名字跟着改，是因为「叫回退、记的却是拒跑」正是本仓禁止的那种压缩
        #: ——而且 `go_fallbacks == 0` 那句结论（「不算放行」）在新语义下同样成立。
        self.go_refusals = 0
        #: 本次读数用的**闸门口径**（裁定④：「乙」）。产物靠它把「装置运行期已关」
        #: 这个前提印出来——见 `gate_declaration()` 与 `tools/golden_go.py` 的 `gate` 栏。
        self.gate = gate_declaration()

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

        ## 这一笔改了什么（2026-09-23，丙·第三十七批）

        **Python 不再自造规格送给 Go**：改送**查询形式**
        （`{level, plan, roster, difficulty, allow_devices, allow_skills}`），
        由 Go 侧的 `buildspec` 自己造规格。于是：

          · `unsupported` **从 Go 的应答里读**（规格在 Go 手里，Python 手上没有它）；
          · `unsupported` 非空 ⇒ **具名拒跑**：把理由列全，**不再回退去跑 Python 模拟器**
            （「只废弃模拟器那条运行路径」是博士 2026-09-23 的裁定；
            `build_spec` 本身仍是**对拍权威**，24 套判据靠它算期望值——所以它留在这儿，
            只是**不再走这条路**）。
          · 三态必须分开：**跑了且一致** / **跑了但不一致** / **拒跑**（没跑）。
            拒跑写在 `Verdict.refused` 里（非空即拒跑），**不许**压成「一场败仗」。

        ## 仍然成立的旧约定

        ⚠ **规格必须在跑之前取**。这一版是**结构上**保证的：规格由 Go 从
        **关卡数据 ＋ 计划 ＋ 名册**造出来（根本不读模拟器的 `life`／`cost`），
        而 Python 侧**一个规格字段都不碰**。旧的坑（跑完 `life=0` 的规格一帧不跑
        就判负）在这条路上不可能发生——这正是换成查询形式顺带拿到的性质。
        """
        # ★★ 具名注释 · 指向 **PM 裁定④（2026-09-20，「走乙」）** ★★
        #
        # `allow_devices=True` 在这里是**一刀切**——**已知的、有意的**，不是漏改、
        # 不是待办。`simgo/spec.py:112-123` 说这个口子要带证据开；本模块顶部
        # `GATE_ALLOW_DEVICES` 里写了取舍的全文与取证（196/433 行带装置）。
        #
        # ⚠ 把它改成按证据开 ＝ 走「甲」⇒ 196 行（45.3%）从「可跑」变「拒跑」，
        #   而甲的前提是**先建 196 关的装置运行期／逐关补取证**。那是一个**独立的决定**，
        #   请连建模一起做；单独改这里只会让近一半主线关静默拒跑。
        #
        # ⚠ 这两个值是从上面那两个常量读的，**不是字面量**——所以「改口径」只有一处，
        #   且产物侧的 `gate` 栏会自动跟着变（守卫会把不一致的基线判红）。
        #
        # ⚠⚠ 换成查询形式之后，这两个值**必须随查询送**（Go 侧缺了就具名失败、
        #    绝不兜默认值）：它们是**口径**，兜一个默认值等于替调用方改掉半个主线关的
        #    可跑性。Go 侧 `simquery.go::ParseSimQuery` 就是那条守卫。
        difficulty = ""
        if isinstance(env, dict):
            difficulty = str(env.get("environment_difficulty") or "")
        if not difficulty:
            difficulty = str(getattr(stage, "difficulty", "") or "NORMAL")
        started = time.perf_counter()
        resp = self._go_client().sim_query(
            #: ⚠ 关卡要给 **levelId**（`stage.level_id`），不是显示代号：
            #: 四星档那一档（`act31side_ex08#f#`）**只住在 levelId 上**，
            #: 送代号会被 Go 解析成普通档（难度轴静默丢掉）。
            level=str(getattr(stage, "level_id", "") or ""),
            plan=plan.to_dict(),
            #: 名册在 `Verifier.run` 里已经解析过、存在实例上（见那里的注释）。
            roster=getattr(self, "_roster_in_use", None),
            difficulty=difficulty,
            allow_devices=GATE_ALLOW_DEVICES,
            allow_skills=GATE_ALLOW_SKILLS)
        self.go_seconds += time.perf_counter() - started

        #: ★ **闸门理由从 Go 的应答里读**（不再自己造规格去读它）。
        #: Go 在**成功与失败两条路**上都会带上它；缺字段 ⇒ 下面那条断言当场炸，
        #: 而不是静默当成「没有理由」（那正是闸门静默失效的样子）。
        if "unsupported" not in resp:
            raise RuntimeError(
                "Go 的 sim 应答里**没有** `unsupported` 字段——闸门无从判定。"
                "★ 这一栏是「Go 自造规格」这条路上**唯一**的退回信号："
                "缺了它，本该拒跑的关卡会被当成可跑（`go_fallbacks` 变 0）。"
                f"应答键：{sorted(resp)}")
        unsupported = list(resp.get("unsupported") or [])
        if unsupported:
            #: 没移植的东西 —— **具名拒跑**，**不再跑 Python 模拟器**。
            self.go_refusals += 1
            return self._refusal_verdict(plan, stage, deployed, title=title,
                                         unsupported=unsupported)
        if not resp.get("ok"):
            #: 非闸门原因的失败（例如机制层拒跑天桩那一条）：与旧路径同口径——
            #: **抛**，不吞（吞掉会变成一份残缺判决，比报错坏得多）。
            raise RuntimeError(f"Go 拒绝了这一场：{resp.get('error')}")

        self.go_runs += 1
        return self._verdict_from_go(plan, stage, resp["verdict"], deployed,
                                     title=title)

    def _refusal_verdict(self, plan, stage, deployed, *, title="",
                         unsupported) -> Verdict:
        """**具名拒跑**那一态：没跑，把理由列全。

        ⚠ 与「一场败仗」必须分得开：这里 `refused` 非空。数值栏一律清零并**在
        第一句就说清这不是打输**——把「没跑」显示成「0 杀 3 漏」，下一个人会去
        查为什么打输了，而根本没打。
        """
        max_life = int(getattr(getattr(stage, "options", None),
                               "max_life_point", 1) or 1)
        v = Verdict(stars=0, won=False, life=0, max_life=max_life, kills=0,
                    leaks=0, elapsed=0.0, damage=0.0, title=title)
        v.refused = list(unsupported)
        v.diagnosis.append(
            "⛔ **具名拒跑**（没跑）：Go 侧还没移植这些字段 —— "
            + "、".join(unsupported)
            + "。★ 这不是「两边一致」，也不是「跑了不一致」，是**没跑**："
            "Python 模拟器那条运行路径已废弃（博士 2026-09-23 裁定），"
            "上面那些数值栏一律无意义。")
        return v

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
      （它的类上本来就有这些方法，绑上去的只是同名同实现）。

    绑的是混入类那几个方法 + 它 `__init__` 里那几个计数器。⚠ 漏掉任何一个，
    症状都是"跑到一半 AttributeError"，所以下面用一张表统一做，不手抄。
    ⚠ 但这张表**不会自己长大**：加了新方法要手动加进来，而且光加不够——
    要有一条判据**真的走到那个方法**（本轮 `_refusal_verdict` 就是漏在这里）。
    """
    import types

    #: ⚠⚠ **加了混入类的方法就必须加进这张表**（2026-09-23 实测踩到）：
    #: 本轮新加的 `_refusal_verdict` 一开始**没进这张表**，于是「具名拒跑」那条路
    #: 一走到就 `AttributeError: 'Verifier' object has no attribute '_refusal_verdict'`
    #: ——而**所有既有闸门都是绿的**：24 份夹具的 `unsupported` 全空，
    #: 拒跑那一态一次都没被行使（基线 24 条 `go_fallbacks: 0` 就是证据）。
    #: ★ 教训不是「补一个名字」，是「新方法要有判据真的走到它」——见
    #: `tools/check_sim_via_python_go.py` 的第三组（那把用例就是为此造的）。
    #:
    #: `close` 是**同一类病的既有实例**（不是本轮引入）：它一直在混入类上、
    #: 一直没进这张表，动态绑定出来的对象 `v.close()` 会 AttributeError。
    #: 顺手补上——今天没有调用方（`run_one` 从不 close），所以行为零变化；
    #: 留着它只会让下一个想 close 的人踩同一个坑。
    for name in ("_go_client", "_run_other_engine", "_verdict_from_go",
                 "_refusal_verdict", "close"):
        setattr(obj, name, types.MethodType(getattr(GoEngineMixin, name), obj))
    if "_go" not in obj.__dict__:
        obj._go = None
    #: 旧名字 `go_fallbacks` 这里**不用绑**：它是 `verify.Verifier` 类上的只读属性
    #: （`Verifier` 实例不继承混入类，所以别名必须住在**那一层**才能被看见——
    #: 曾试着在这里把它的 fget 绑成实例方法，读出来是**方法对象**而不是值，
    #: 于是 `or row["go_fallbacks"]` 恒真 ⇒ 闸门永久假红。记在这里免得再试一遍）。
    #: 与 `GoEngineMixin.__init__` 逐项对齐：跑过的场次、累计耗时、**具名拒跑**的次数、
    #: 以及**闸门口径**（漏掉 `gate` 的症状是产物里那一栏变成 `null`，
    #: 而 `golden_go` 的守卫会当场判红——这正是要的：**缺字段必须响**）。
    for attr, init in (("go_runs", 0), ("go_seconds", 0.0), ("go_refusals", 0),
                       ("gate", gate_declaration())):
        if attr not in obj.__dict__:
            setattr(obj, attr, init)


class GoVerifier(GoEngineMixin, Verifier):
    """完整版：排程照旧走原版，只有"跑这一场"换成 Go。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        if self.engine != "go":                               # pragma: no cover
            raise ValueError("GoVerifier 的 engine 必须是 'go'")
