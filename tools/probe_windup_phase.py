# -*- coding: utf-8 -*-
"""前摇停帧相位探针（交接文档 §4 的下一刀）。

病根假设：两台引擎都为「出手动作」停一帧，但**停在不同的帧**。本探针把两边
在同一时间线上的逐帧状态摊开，做两件事：

1. **按帧列出「谁在停」**：原版侧钩 `_environment_tick`（帧首，与 Go 的痕迹点
   同一时刻），记 `attack_pause` / `attack_timer` / `skill_atk_timer` / 坐标；
   Go 侧跑同一份规格（POS 痕迹本来就带 pause/legu）。
2. **对齐「停」的区间**：把每一帧的位移取出来，比"这一帧走了多少"。

用法：
    python tools/probe_windup_phase.py --k 1
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

from ak_tactic.battle import sim as simmod                       # noqa: E402
from ak_tactic.plan import Plan, Roster                          # noqa: E402
from ak_tactic.simgo import build_spec, find_binary              # noqa: E402
from ak_tactic.simgo.verifier import GoVerifier                  # noqa: E402
from ak_tactic.frontend.inputs import SpecInputs

#: 目标敌人（用户给的原始数据里那只「多停一帧 / 多走一帧」的敌人）。
TARGET = "去蚀"
#: 窗口（秒）——原始数据是 17–42。
WIN = (17.0, 42.0)

#: ⚠ 痕迹一律按**自描述的 `key=value`** 解析，不再逐列写死正则。
#: 原先 POS_RE 把列顺序钉死（`freeze=… leg=…`），Go 侧每加一列就**静默失配**，
#: 而失配的表现是「帧记录=0 / 共 0 条坐标分开」——**假绿**。
#: 本会话为此白跑过一轮：加了 `snow=`/`latch=` 两列，`probe_firstdiff` 报"0 条分歧"，
#: 看着像"已经对齐了"。**加列不该需要动这里；缺列必须显式报错。**
_KV_RE = re.compile(r"(\w+)=(\S+)")


def parse_trace(line: str) -> tuple[str, dict[str, str]] | None:
    """把一行痕迹拆成 `(标签, {键: 值})`；不是痕迹行就给 `None`。"""
    line = line.strip()
    if not line or "=" not in line:
        return None
    tag, _, rest = line.partition(" ")
    if not rest:
        return None
    return tag, dict(_KV_RE.findall(rest))


#: 坐标比对的**最低必需列**：少任何一列都必须当场报错，不许退化成"没有分歧"。
POS_NEEDED = ("t", "idx", "name", "x", "y")

ATK_RE = re.compile(
    r"ATK t=(?P<t>[\d.]+) enemy=(?P<name>\S+) idx=(?P<idx>\d+) "
    r"ecell=\d+,\d+ interval=(?P<interval>[\d.]+) pause=(?P<pause>[\d.]+) "
    r"hits=(?P<hits>\d+)")


#: 夹具与名册住在**验证工作树**里（`out/` 不进仓库）；先看本仓库，再退到 head 树。
HEAD = ROOT.parent / "ak-tactic-head"


def _fixture(name: str) -> pathlib.Path:
    p = pathlib.Path(name)
    if p.is_absolute() and p.exists():
        return p
    for base in (ROOT, HEAD):
        for cand in (base / "out" / name, base / "out" / f"{name}.json"):
            if cand.exists():
                return cand
    raise FileNotFoundError(f"out/{name} 在 {ROOT} 与 {HEAD} 都没有")


def load_plan(k: int) -> Plan:
    """夹具可用环境变量换关：`RIOS_PLAN=hs7`。

    ⚠ 为什么必须能换：这一族探针（出手台账 / 承伤逐账 / 索敌键 / 逐帧坐标）
    原先**全写死在 `hsex8_max.json`** 上。而"怀黍离全部关卡的 Go/Python 对拍"
    要求的是换一份作业就能查同一个问题；每个关卡复制一份脚本，
    筛选逻辑会各自漂移——那种漂移比 bug 更难查。
    """
    raw = json.loads(_fixture(os.environ.get("RIOS_PLAN", "hsex8_max.json"))
                     .read_text(encoding="utf-8"))
    if k:
        raw = dict(raw, deploys=raw["deploys"][:k])
    return Plan.from_dict(raw)


def load_roster() -> Roster:
    try:
        return Roster.from_json(_fixture(
            os.environ.get("RIOS_ROSTER", "roster_max_modelled.json")))
    except FileNotFoundError:
        return Roster.empty()


# ------------------------------------------------------------------ 原版

def run_python(plan: Plan, roster: Roster, *, max_time: float | None = 900.0,
               target=None) -> tuple[list[dict], object]:
    """跑原版，逐帧记目标敌人的状态（帧首，与 Go 痕迹同一时刻）。

    ⚠ `max_time` 默认 **900.0**，与 `tools/parity_plan.py:89` 的 `sim.run(max_time=900.0)`
    对齐。原来是 `None`（等于"不转发"）⇒ 原版走 `BattleSimulator.run` 的默认上限，
    与对拍工具**不是同一个上限**，两台工具的数字根本不可比。
    要显式取消上限就传 `0`（假值）——那是"用默认"，不是"跑到底"。

    ⚠ 同一关里**同名敌人同时有好几只**（HS-EX-8 上「去蚀」一度六只同时在跑），
    所以帧记录里带下标，比对时按 (名字, 出怪时刻/下标) 成组——见 §5.2 那两个坑。

    `target` 覆盖模块级的 `TARGET`（默认「去蚀」）。可以是名字字符串，也可以是
    **谓词 `e -> bool`**：名字里带全角引号那种（`“祟”`）从命令行传会被 shell 吃掉
    ——症状是"帧记录=0"，看着像"原版根本没这只敌人"。传一个按**出怪时刻**匹配的
    谓词就绕开了整条转义链。
    """
    frames: list[dict] = []
    attacks: list[dict] = []
    orig = simmod.BattleSimulator._snow_tick
    want = TARGET if target is None else target

    #: 每只敌人一个**稳定序号**，用来补上比对键缺的那一半。
    #:
    #: ⚠ 为什么必须有它：比对键只按 **(名字, 出怪时刻)** 分组，而**同名同刻的敌人真的存在**
    #: ——「天桩-乙」在 `sim._spawns` 里有 57 条出怪行、其中 16 个时刻是重复的。
    #: 键一撞车，`{(key,t): frame}` 这种字典后写覆盖先写，"两台引擎的差"里就混进了
    #: **「拿甲跟乙比」**，而报告长得和真分歧**一模一样**（记忆 `6c101989`）。
    #: 实测 `hsex8_max`：原版侧 **32430** 个 (键, 帧) 上有不止一条记录、Go 侧 0 ——
    #: 也就是说修之前那份「9375 条坐标分开」**不可信**。
    #:
    #: 序号按**首次见到该对象的先后**分配（同一个 `(name, spawn_time)` 组内从 0 起）。
    #: 两台引擎都按确定的出怪顺序处理，所以首次见到的次序应当一致；
    #: 若一边根本没见到某只，序号会错开——而那**正是我们要找的分歧**，不是噪声。
    seq_of: dict[int, int] = {}
    seen: dict[tuple, int] = {}

    def seq_for(e, key):
        i = seq_of.get(id(e))
        if i is None:
            i = seen.get(key, 0)
            seen[key] = i + 1
            seq_of[id(e)] = i
        return i

    def scan(self, t, src):
        for e in self.enemies:
            if not (want(e) if callable(want) else e.name == want):
                continue
            # ⚠ 比对键是 **(名字, 出怪时刻, 第几只)**：原版列表下标与 Go 的
            # `spec.Spawns` 序**不是一回事**（重生会插到列表里），实测错位两位。
            base = (e.name, round(float(e.spawn_time), 3))
            k3 = (base[0], base[1], seq_for(e, base))
            frames.append(dict(
                key=k3, seq=k3[2], t=t, name=e.name,
                x=e.position[0], y=e.position[1],
                hp=e.hp, pause=e.attack_pause, atk_timer=e.attack_timer,
                interval=float(e.attack_interval),
                sk_timer=getattr(e, "skill_atk_timer", 0.0),
                sk_first=bool(getattr(e, "skill_atk_first", False)),
                sluggish=e.sluggish_timer, frozen=bool(e.frozen),
                blocked=e.blocked_by is not None, src=src,
                # 移速的六个乘区**分开记**：只记"这一帧走了多少"没法回答
                # "是谁把速度改了"（原版 advance 的六项连乘）。
                speed_mult=getattr(e, "speed_multiplier", 1.0),
                haste=getattr(e, "haste_multiplier", 1.0),
                slow_pct=getattr(e, "slow_pct", 0.0),
                lock_slow=getattr(e, "lock_slow", 1.0),
                move_speed=getattr(e, "move_speed", 0.0),
                root=getattr(e, "root_timer", 0.0),
                idle=getattr(e, "idle_timer", 0.0),
            ))

    def env(self, dt, t):
        # ⚠⚠ **观测点必须与 Go 的 POS 痕迹同帧位置，否则比出来的差是"观察点的差"。**
        #
        # 实测踩过一次：这里原来挂在 `_environment_tick` 上（原版主循环 **3.7**），
        # 而 Go 的 POS 痕迹在**敌人推进循环内**（`rios-sim/sim.go:772`），
        # 它之后才是 `mechanisms.SnowTick`（`:901`）。原版主循环是
        # `advance`(:2725) → `_snow_tick`(:2737, **3.5**) → … → `_environment_tick`(:2752, **3.7**)。
        # 于是凡是在 3.2→3.7 之间发生的事（积雪、祝福、气、弹道、锤、p3r、环境）
        # 都会被读成"差一帧"。`hsex8_max` 上就现了一次：`t=65.8` 原版 hp=3773.6、
        # Go hp=4400.0，看着像"Go 少挨了 626.4"，其实 Go 的痕迹自己写着
        # `SNOWENTRY t=65.8000 … dmg=626.4 → hp=3773.600`——**两边都算了**，
        # 只是我站在积雪**之后**看原版、站在积雪**之前**看 Go。
        #
        # 现在改挂 `_snow_tick`（3.5）的**入口**：此时敌人已经推进完、
        # 积雪伤害还没落，与 Go 的 POS 位置对齐。
        scan(self, t, "loop")
        return orig(self, dt, t)

    orig_atk = simmod.BattleSimulator._enemies_attack

    def atk(self, dt, t):
        before = {id(e): e.attack_timer for e in self.enemies if e.name == TARGET}
        r = orig_atk(self, dt, t)
        for e in self.enemies:
            if e.name != TARGET:
                continue
            was = before.get(id(e))
            if was is not None and e.attack_timer < was - 1e-12:
                # 计时器归零了 = 这一帧出手了（`_enemies_attack` 的唯一一处）。
                attacks.append(dict(
                    key=(e.name, round(float(e.spawn_time), 3)), t=t,
                    timer_at_fire=was, interval=float(e.attack_interval),
                    pause_after=e.attack_pause,
                ))
        return r

    #: ⚠ 挂 `_snow_tick`（3.5）而**不是** `_environment_tick`（3.7）：理由见 `env` 上方那段。
    #: 两者的调用频率都是每帧一次，所以帧数不变；变的只是**站在帧内哪一步看**。
    simmod.BattleSimulator._snow_tick = env
    simmod.BattleSimulator._enemies_attack = atk
    try:
        from ak_tactic.verify import Verifier
        #: ⚠⚠ **必须显式钉 `engine="python"`。** 2026-09-19 引擎切换后，`Verifier` 的默认引擎
        #: 变成 `"go"`（`verify.py:145`），而 `verify.py:160` 那条注释就是为这件事写的：
        #: 「仓里凡是"必须拿到 Python 结果"的地方，都要**显式**传 `engine="python"`」。
        #: 裸 `Verifier()` 会跑 **Go**，而本函数照样打 `[python]` 那一行 ——
        #: 于是"两台引擎完全一致"其实是**自己跟自己比**。这是一个**假绿**：
        #: 它不报错，只会安静地什么都不比。实测 `hsex8_max`：本函数给出
        #: `48杀 3漏 221.667s`（与 Go 侧逐位相同），而钉了 engine 的 `parity_plan` 给
        #: `83杀 1漏 814.033s` —— 差 592 秒，全由这一个关键字造成。
        #:
        #: ⚠ 另：`max_time` 参数**不要往 `run()` 里塞**——它不是 `BattleSimulator` 的构造键
        #: （塞了会 `TypeError`）。基类的原版路径本来就是 `sim.run(max_time=900.0)`
        #: （`verify.py:492`），与 `parity_plan:89` 同值，**上限早就对齐了**。
        #: 我这轮先试过转发，实测炸在 `BattleSimulator.__init__` 上，已撤回。
        v = Verifier(engine="python").run(plan, roster=roster)
    finally:
        simmod.BattleSimulator._snow_tick = orig
        simmod.BattleSimulator._enemies_attack = orig_atk
    print(f"[python] {v.kills}杀 {v.leaks}漏 {v.elapsed:.6f}s "
          f"帧记录={len(frames)} 出手={len(attacks)}")
    return frames, v, attacks


# ------------------------------------------------------------------ Go

class SpecThief(GoVerifier):
    """在跑之前把规格偷出来（`build_spec` 读的是运行期状态）。"""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.spec: dict | None = None

    def _run_other_engine(self, *, sim, plan, stage, deployed, title,
                          schedule=None, env=None):
        self.spec = build_spec(SpecInputs.from_sim(sim), allow_devices=True,
                                     schedule=schedule, env=env)
        raise SystemExit(0)


def run_go(plan: Plan, roster: Roster) -> tuple[dict, list[dict], list[dict]]:
    exe = find_binary()
    thief = SpecThief()
    try:
        thief.run(plan, roster=roster)
    except SystemExit:
        pass
    spec = thief.spec
    assert spec is not None, "没偷到规格"

    env = dict(os.environ, RIOS_TRACE="1", RIOS_TRACE_POS=TARGET)
    p = subprocess.run([str(exe)], input=json.dumps({"id": 1, "cmd": "sim", "spec": spec}),
                       capture_output=True, text=True, encoding="utf-8", env=env)
    resp = json.loads(p.stdout.strip().splitlines()[-1])
    if not resp.get("ok"):
        raise RuntimeError(resp.get("error"))
    got = resp["verdict"]
    # 出怪时刻从规格里取：痕迹给的是 `idx`（= `spec.Spawns` 序），把它翻成
    # **(名字, 出怪时刻)**，与原版侧的键同义——下标两边不同义，不能当键。
    spawn_at = {i: round(float(sp.get("time", 0.0)), 3)
                for i, sp in enumerate(spec.get("spawns") or [])}
    frames = []
    attacks = []
    raw_pos: list[str] = []

    #: Go 侧的序号：与 Python 侧**同一条规则**——按**首次见到**分配，
    #: 组内从 0 起。这里用 `idx`（= `spec.Spawns` 下标，Go 侧本来就有的稳定身份）
    #: 当"见过没见过"的依据；Python 侧没有这个字段，只能按对象身份判。
    #: ⚠ 两侧规则一致是刻意的：规则不同会**制造**差，而不是揭示差。
    _seq_seen: dict[tuple, int] = {}
    _seq_of_idx: dict[int, int] = {}

    def _go_seq(idx: int, name: str, at: float) -> int:
        i = _seq_of_idx.get(idx)
        if i is None:
            base = (name, at)
            i = _seq_seen.get(base, 0)
            _seq_seen[base] = i + 1
            _seq_of_idx[idx] = i
        return i
    for line in (p.stderr or "").splitlines():
        parsed = parse_trace(line)
        if parsed is None:
            continue
        tag, d = parsed
        if tag == "POS":
            if len(raw_pos) < 3:
                raw_pos.append(line.strip())
            missing = [k for k in POS_NEEDED if k not in d]
            if missing:
                raise RuntimeError(
                    f"POS 痕迹缺列 {missing}——**解析器与该轮的痕迹格式对不上**。"
                    "这不是'没有记录'，别再当成'没有分歧'。原始行："
                    f"{line.strip()}")
            #: 冻结取 `latch`（= 推进门控真正读的那个锁存值）；没有才退回 `freeze`。
            #: ⚠ 它的采样点在**本帧雪算之前**，而原版那一列在**之后**——两边语义不同源，
            #: 只做参考，不要拿它当"谁先冻"的判据。
            lat = d.get("latch")
            frames.append(dict(
                key=(d["name"], spawn_at.get(int(d["idx"]), -1.0),
                     _go_seq(int(d["idx"]), d["name"],
                             spawn_at.get(int(d["idx"]), -1.0))),
                idx=int(d["idx"]),
                t=float(d["t"]), name=d["name"], x=float(d["x"]), y=float(d["y"]),
                hp=float(d.get("hp", 0.0)), pause=float(d.get("pause", 0.0)),
                sluggish=float(d.get("sluggish", 0.0)),
                frozen=(lat == "true") if lat is not None
                else float(d.get("freeze", 0.0)) > 0,
                blocked=d.get("blocked") == "true",
                leg=int(d.get("leg", 0)), legu=float(d.get("legu", 0.0)),
            ))
            continue
        m = ATK_RE.search(line)
        if m:
            d = m.groupdict()
            attacks.append(dict(
                key=(d["name"], spawn_at.get(int(d["idx"]), -1.0)),
                t=float(d["t"]), interval=float(d["interval"]),
                pause_after=float(d["pause"]), hits=int(d["hits"]),
            ))
    #: ⚠ **一条都没解析出来 = 仪器坏了，不是"对齐了"**。这道闸门是拿一次假绿换来的。
    if not frames:
        raise RuntimeError(
            "Go 侧 POS 痕迹一条都没解析出来。判据：`RIOS_TRACE=1` 与 "
            f"`RIOS_TRACE_POS={TARGET}` 是否生效、以及痕迹格式是否又变了。"
            "本会话曾因加列导致正则失配，被报成「帧记录=0 且共 0 条坐标分开」"
            f"（看着像已经对齐）。stderr 里 POS 行样本：{raw_pos or '（一行都没有）'}")
    print(f"[go]     {got['kills']}杀 {got['leaks']}漏 {got['elapsed']:.6f}s "
          f"帧记录={len(frames)} 出手={len(attacks)}")
    return got, frames, attacks


# ------------------------------------------------------------------ 比对

def dx(frames: list[dict]) -> dict[tuple, float]:
    """每一帧走了多少（用 (x,y) 的欧氏步长——路线拐弯时单看 x 会骗人）。

    键 = (敌人身份键, 帧时刻)：同一关里同名敌人有多只，按名字或按时刻当键
    都会把它们**并成一只**（这正是 §5.2 的坑）。
    """
    out: dict[tuple, float] = {}
    prev: dict[tuple, dict] = {}
    for f in frames:
        k = f["key"]
        p = prev.get(k)
        if p is not None:
            out[(k, round(f["t"], 4))] = round(
                ((f["x"] - p["x"]) ** 2 + (f["y"] - p["y"]) ** 2) ** 0.5, 7)
        prev[k] = f
    return out


def table() -> int:
    """逐手对拍水位表（交接文档 §3 那张）。

    ⚠ 每一行都要先确认 **Go 真跑**：`GoVerifier` 在闸门非空时静默退回原版，
    回退出来的"一致"毫无意义（见过一次假绿，写进了坑表）。
    """
    roster = load_roster()
    print(f"{'手数':>4} {'原版':>26} {'Go':>26} {'判决':>8} {'引擎':>12}")
    for k in range(1, 9):
        plan = load_plan(k)
        _py, pv, _pa = run_python(plan, roster)
        got, _gf, _ga = run_go(plan, roster)
        same = (int(pv.kills) == int(got["kills"]) and int(pv.leaks) == int(got["leaks"])
                and abs(float(pv.elapsed) - float(got["elapsed"])) < 1e-6)
        py_s = f"{pv.kills}杀{pv.leaks}漏 {pv.elapsed:.3f}s"
        go_s = f"{got['kills']}杀{got['leaks']}漏 {got['elapsed']:.3f}s"
        print(f"{k:>4} {py_s:>26} {go_s:>26} "
              f"{'一致' if same else '不一致':>8} {'go 真跑':>12}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=1)
    ap.add_argument("--lo", type=float, default=WIN[0])
    ap.add_argument("--hi", type=float, default=WIN[1])
    ap.add_argument("--tol", type=float, default=1e-6,
                    help="逐帧位移的容差（默认 1e-6：一帧位移 0.0133 的千分之一）")
    ap.add_argument("--spans", action="store_true", help="打印全部停帧区间（很长）")
    ap.add_argument("--tail", type=int, default=0, help="打印末尾 N 帧")
    ap.add_argument("--enemy", default="", help="只摊开这一只敌人的逐帧表（键形如 去蚀@22.0）")
    ap.add_argument("--first", type=int, default=0,
                    help="另打最早 N 条分歧（找『分歧从哪一帧起』）")
    ap.add_argument("--persist", type=int, default=6,
                    help="--first 用：连续多少条坐标都分开才算『真分开』")
    ap.add_argument("--table", action="store_true",
                    help="逐手对拍水位表（k=1..8，只打判决）")
    args = ap.parse_args()

    if args.table:
        return table()

    plan = load_plan(args.k)
    roster = load_roster()
    py, _v, py_atk = run_python(plan, roster)
    _got, go, go_atk = run_go(plan, roster)

    pyx = dx(py)
    gox = dx(go)
    keys = sorted(set(pyx) | set(gox), key=lambda k: (k[1], k[0][1]))
    keys = [k for k in keys if args.lo <= k[1] <= args.hi]
    pyat = {(f["key"], round(f["t"], 4)): f for f in py}
    goat = {(f["key"], round(f["t"], 4)): f for f in go}

    # ⚠ 比对位移要**带容差**：一帧位移 0.0133，而 0.4/30 在两边各算一次会差
    # 最后一位（1e-7）。拿逐位相等当判据，750 帧里会有 11 帧"不同"——那全是
    # 仪器精度，正是 §5.3 那条纪律说的假差异。
    rows = []
    for k in keys:
        a, b = pyx.get(k), gox.get(k)
        if a is None or b is None:
            rows.append((k, a, b))
        elif abs(a - b) > args.tol:
            rows.append((k, a, b))
    if args.first:
        # 「分歧从哪一帧起」= **坐标本身**第一次分开（且此后不再合上）。
        # ⚠ 别拿"位移差"当这个判据：某帧位移不同可能只是那一帧多停了一下，
        # 下一帧又追平（HS-EX-8 单手作业上就是 4 帧两两抵消）。位置分开才是真分开。
        print(f"--- 坐标首次分开（容差 {args.tol:g}，要求此后至少 {args.persist} 帧不再合上）---")
        keys_all = sorted(set(pyat) | set(goat), key=lambda x: (x[1], x[0][1]))
        run = 0
        reported = 0
        for k in keys_all:
            xa = pyat.get(k)
            xb = goat.get(k)
            if xa is None or xb is None:
                continue
            if abs(xa["x"] - xb["x"]) > args.tol or abs(xa["y"] - xb["y"]) > args.tol:
                run += 1
                if run == 1:
                    buffered = [(k, xa, xb)]
                else:
                    buffered.append((k, xa, xb))
                if run >= args.persist and reported < args.first:
                    reported += 1
                    k0, a0, b0 = buffered[0]
                    print(f"[{reported}] {k0[0]}@{k0[1]}  t={k0[1]:.4f} "
                          f"x py={a0['x']:.7f} go={b0['x']:.7f} "
                          f"差={a0['x'] - b0['x']:+.7f}  "
                          f"hp py={a0['hp']:.1f} go={b0['hp']:.1f}")
                    for kk, aa, bb in buffered[1:6]:
                        print(f"      t={kk[1]:.4f} x py={aa['x']:.7f} go={bb['x']:.7f} "
                              f"差={aa['x'] - bb['x']:+.7f}")
                    # 只报**第一处**；后面的等这一处解释清楚了再看
                    break
            else:
                run = 0
                buffered = []
    print(f"\n窗口 {args.lo}-{args.hi}s，{len(keys)} 条 (敌人,帧) 记录；"
          f"位移差 > {args.tol:g} 的有 {len(rows)} 条")
    if args.first:
        # 只打**最早**的几条：分歧从哪一帧起，比"一共差了多少条"有用得多。
        print(f"--- 最早的 {args.first} 条位移差 ---")
        for (ident, t), a, b in sorted(rows, key=lambda r: r[0][1])[:args.first]:
            xa = pyat.get((ident, t), {})
            xb = goat.get((ident, t), {})
            print(f"{ident[0]}@{ident[1]} t={t:9.4f} "
                  f"py Δ={a if a is not None else -1:10.7f} "
                  f"go Δ={b if b is not None else -1:10.7f}   "
                  f"x py={xa.get('x', float('nan')):.7f} "
                  f"go={xb.get('x', float('nan')):.7f} "
                  f"差={xa.get('x', 0) - xb.get('x', 0):+.7f}   "
                  f"sluggish py={xa.get('sluggish', float('nan')):.3f} "
                  f"blocked py={xa.get('blocked')} go={xb.get('blocked')}")
        print("--- 全部 ---")
    for (ident, t), a, b in rows:
        pa = pyat.get((ident, t), {}).get("pause")
        pb = goat.get((ident, t), {}).get("pause")
        print(f"{ident[0]}@{ident[1]} t={t:9.4f} "
              f"py Δ={a if a is not None else -1:10.7f} "
              f"go Δ={b if b is not None else -1:10.7f}   "
              f"pause py={pa if pa is not None else -1:.3f} "
              f"go={pb if pb is not None else -1:.3f}   "
              f"x py={pyat.get((ident, t), {}).get('x', float('nan')):.7f} "
              f"go={goat.get((ident, t), {}).get('x', float('nan')):.7f}")

    # 停帧区间（pause > 0 的**连续**帧），逐只敌人各自成组。
    def spans(frames):
        out: dict[tuple, list] = {}
        cur: dict[tuple, float] = {}
        prev_t: dict[tuple, float] = {}
        for f in frames:
            k = f["key"]
            stop = f.get("pause", 0.0) > 0
            if stop and k not in cur:
                cur[k] = f["t"]
            elif not stop and k in cur:
                out.setdefault(k, []).append(
                    (round(cur.pop(k), 4), round(prev_t[k], 4)))
            prev_t[k] = f["t"]
        for k, start in cur.items():
            out.setdefault(k, []).append((round(start, 4), round(prev_t[k], 4)))
        return out

    sp, sg = spans(py), spans(go)
    np_ = sum(len(v) for v in sp.values())
    ng = sum(len(v) for v in sg.values())
    print(f"\n停帧区间（pause>0 连续段） 原版 {np_} 段 / Go {ng} 段")
    for k in sorted(set(sp) | set(sg), key=lambda x: x[1]):
        a, b = sp.get(k, []), sg.get(k, [])
        if a == b:
            continue
        print(f"  {k[0]}@{k[1]} 段数 原版 {len(a)} / Go {len(b)}")
        n = max(len(a), len(b))
        for j in range(n):
            x = a[j] if j < len(a) else None
            y = b[j] if j < len(b) else None
            flag = "" if x == y else "   ← 不同"
            print(f"     {j:2d} 原版 {x}   Go {y}{flag}")

    if args.tail:
        print(f"\n末 {args.tail} 帧（看收场差在哪一帧）")
        for tag, fs in (("原版", py), ("Go  ", go)):
            last: dict[tuple, list] = {}
            for f in fs[-args.tail * 8:]:
                last.setdefault(f["key"], []).append(f)
            print(f"   {tag}：")
            for k, lst in sorted(last.items(), key=lambda x: x[0][1]):
                print(f"     {k[0]}@{k[1]} " + " ".join(
                    f"{g['t']:.4f}(x={g['x']:.4f},hp={g['hp']:.0f})"
                    for g in lst[-args.tail:]))

    # ---- 出手帧逐笔对：停帧的相位差只能从"谁在哪一帧出手"上看出来
    byk_py: dict[tuple, list] = {}
    byk_go: dict[tuple, list] = {}
    for a in py_atk:
        byk_py.setdefault(a["key"], []).append(a)
    for a in go_atk:
        byk_go.setdefault(a["key"], []).append(a)
    print(f"\n出手逐笔对（原版 {len(py_atk)} 笔 / Go {len(go_atk)} 笔）")
    shown = 0
    for k in sorted(set(byk_py) | set(byk_go), key=lambda x: x[1]):
        a = byk_py.get(k, [])
        b = byk_go.get(k, [])
        if args.lo > 0:
            a = [x for x in a if args.lo <= x["t"] <= args.hi]
            b = [x for x in b if args.lo <= x["t"] <= args.hi]
        if len(a) == len(b) and all(
                abs(x["t"] - y["t"]) < 1e-9 for x, y in zip(a, b)):
            continue
        shown += 1
        print(f"  {k[0]}@{k[1]}  原版 {len(a)} 笔 / Go {len(b)} 笔")
        n = max(len(a), len(b))
        for j in range(n):
            x = a[j] if j < len(a) else None
            y = b[j] if j < len(b) else None
            xt = f"t={x['t']:.4f} (timer@fire={x['timer_at_fire']:.7f}, itv={x['interval']:.4f})" if x else "—"
            yt = f"t={y['t']:.4f} (itv={y['interval']:.4f}, hits={y.get('hits')})" if y else "—"
            flag = ""
            if x and y and abs(x["t"] - y["t"]) > 1e-9:
                flag = "   ← 时刻不同"
            print(f"     {j:2d} 原版 {xt}   Go {yt}{flag}")
    if not shown:
        print("  这一段逐笔同刻（出手节奏一致）")

    if args.enemy:
        name, _, spawn = args.enemy.partition("@")
        want = (name, float(spawn))
        print(f"\n逐帧摊开 {want}（窗口 {args.lo}-{args.hi}s）")
        # Go 侧没有 attack_timer（痕迹里没记），逐帧给的是 pause/坐标/legu；
        # 原版多一列 atk_timer——两者并用才能看出"停"与"计时"谁先变。
        print(f"{'t':>9} | {'py pause':>8} {'py atk_t':>9} {'py x':>11} | "
              f"{'go pause':>8} {'go legu':>11} {'go x':>11}")
        a = {round(f["t"], 4): f for f in py if f["key"] == want}
        b = {round(f["t"], 4): f for f in go if f["key"] == want}
        for t in sorted(set(a) | set(b)):
            if not (args.lo <= t <= args.hi):
                continue
            x, y = a.get(t), b.get(t)
            print(f"{t:9.4f} | {x['pause'] if x else -1:8.4f} "
                  f"{x['atk_timer'] if x else -1:9.6f} "
                  f"{x['x'] if x else float('nan'):11.7f} | "
                  f"{y['pause'] if y else -1:8.4f} "
                  f"{y['legu'] if y else -1:11.7f} "
                  f"{y['x'] if y else float('nan'):11.7f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
