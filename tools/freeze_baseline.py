#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""冻结基线：把判据的**期望值**从「现场跑 Python」改成「读一份冻住的 JSON」。

## 为什么要有这个工具

2026-09-19 的裁定是「基线全用 Go、Python 仅作历史参考、**门判据＝Go 自身基线漂移即红**」。
但 26 套判据里 24 套仍在**现跑 `ak_tactic` 当 oracle**。三条代价：

* (a) 有人改了 `ak_tactic/`，**判据的期望值跟着变** ⇒ 两侧同错也判绿；
* (b) `ak_tactic/` 永远删不掉；
* (c) 它量的是「与旧实现一致」，**不是「对」**。

本文件同时是**通道**（`tools/check_*.py` import 它）与**工具**（录 / 校验 / 现算进度）。

## 三种模式（**唯一开关是环境变量 `RIOS_GOLDEN`**）

| 值 | 语义 | 吃 Python 吗 |
| --- | --- | --- |
| 未设 / `0` / `off` | **现状**：直接调 `ak_tactic` 取期望值（对拍） | 吃 |
| `record` | 调 `ak_tactic` 取期望值，**同时**把 `键 → 值` 收下来落成基线 | 吃（录的时候本来就要吃） |
| `check` | **只读** `fixtures/golden/<套名>.json`；`ak_tactic` 被封死 | **不吃** |

★ 两条防线（**缺一条就会有假绿**）：

1. **import 拦截器**：`check` 档下 `import ak_tactic` 直接 ImportError。没转好的
   取期望值点**当场响**，不会静默走回 Python。
2. **绑定断言**：`check` 档的进程退出时，若这一套**从未** `bind()` 过通道，直接以
    **`rc=6`** 收场。**没有它，一套一个字没改的脚本在 check 档下照常跑 Python 并报绿**
   ——那正是「未转」被读成「已转」的形状（本仓记过：没有守卫的绿是零信息量。

## 退出码

* `0` / 判据自己的码 —— 判据的结论，本工具**不改它**；
* **`6`** —— **通道自己的错**：无基线、键缺、顶层 import 了 `ak_tactic`、期望值不可
  JSON 化、或从未绑定通道。`6` 的含义是「**这一套还没转**」，**不是「判据红」**。

## 给 `tools/check_*.py` 的改法（只动取期望值的地方）

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
import freeze_baseline as GB                      # 加这一条 import（不是 ak_tactic）

def main() -> int:
    G = GB.bind("生命上限", __file__)             # 套名与 check_go_all.SUITE 逐字相同
    def oracle():
        from ak_tactic.simgo.skills import _max_hp_after_bonus   # ★ import 写在函数里
        return _max_hp_after_bonus(op, eff)
    want = G.expect(("maxhp", q["base"], q["cur"], q["pct"]), oracle)
```

① 键必须**自带全部输入**且可 JSON 化——键相同而输入不同，等于录了一份假的；
② 期望值的 import **必须搬进函数里**（顶层 import 会让 check 档在 bind 时就报 6）；
③ **判据逻辑一行不动**（比法、计数、反向守卫、结论行全照旧）——迁移是增量的、可回退的。

### ★ 冻结的是**两半**：查询集 ＋ 期望值（只冻一半＝分母会静默缩水）

`分类` 的键集来自 `SkillBook`、`范围` 的代号集来自 `RangeTable`、`关卡` 的清单来自
`load_stage`——**「问哪些问题」本身就是 Python 侧的产物**。只冻答案不冻问题，check 档
要么响（拦截器让它响），要么更糟：有人「顺手」把查询集改成硬编码的一个子集，
**分母静默变小而全绿**（本仓记过：漏跑一套的症状是全绿，只是那份绿少了一块）。

⇒ 规矩：**凡是决定「问哪些问题」的那一段，也走 `G.expect()`**，键名以 `("query", …)`
开头（与期望值分开）。分母是判据的一部分，不是它的装饰。

★ **记录的分母**：查询集那一条本身就是基线里的一个值（`("query", …)`），
`--check` 的「新增 / 消失」两栏量到它——**分母变了会红**，不会被吞掉。
看基线里有多少个问题，直接读那条值即可。

### ★ 类型还原：JSON 会抹掉 `tuple` / `set`

`json` 把 `tuple` 写成 `list`、把 `set` 直接拒掉。于是**冻回来的值与现场那个值的
Python 类型不同**，而判据里常常有 `sorted(map(tuple, g)) != sorted(cells)` 这种比法
——那一比会**恒不相等**（假红），或者反过来恒相等（假绿）。

⇒ 规矩：**还原写在判据侧，而且两种模式走同一条路**。取法是把现场值**先规范化成 JSON
形状**（`[list(c) for c in cells]`），判据侧再统一还原（`[tuple(c) for c in want]`）。
不许只在 `check` 档还原——那两档就不是同一个判据了。

### ★ 第三态：**不适用于冻结**

判据里的东西有三种，别压成两种：

1. **期望值** ⇒ 冻；
2. **查询集 / 判定·计数口径常量**（判定或行使计数时要用到的 Python 常量，例如 `ASPD_MIN`）
   ⇒ 冻。⚠ 两者性质不同：**改常量未必能翻转判决**（实测：「攻击间隔」的 `ASPD_MIN`
   只进行使计数，改它 rc 照样 0），所以控制组只拿**期望值**做敏感性探针；
   常量冻住的目的是**让行使计数的口径可复现**，以及让 check 档不去 import Python；
3. **Python 侧自身的自检**（例如「`spec.ASPD_MIN` 与 `skill.ASPD_MIN` 两处常量必须相等」）
   ⇒ **冻不了也不该冻**：冻住之后两侧同源、**恒等**，是一条不可能失败的判据。
   这一态要**显式印出来**（`⚠ 本条在冻结档不适用`），不许静默当作通过——
   把它读成绿，就是又造了一条「预先被决定的绿」。

### ★ 每套的控制组（`--control`，**不是可选项**）

    python tools\\freeze_baseline.py --control <套名…>

* **P1 · 改一个期望值 ⇒ 必须判红**。证明「冻的值真的是 oracle」，
  而不是「读了个文件、判决照旧看 Go」。**控制组没红时本工具 exit 1。**
* **P2 · 查询集删一个 ⇒ 冻结档看不见（有界盲区，读数照印）**，
  而 **P2b · `--check`**（拿**现读**的查询集对账）**必须看见**。
  两条合起来才说明：分母缩水这件事有补偿控制，且补偿控制真的管用。

⚠ **登记在案的残余风险**：冻结档**自己**看不见分母被人改小（它只问冻住的那批问题）。
Python 还在的时候，锚是 `--check`（现读 vs 冻结，两条来源不同）。
**Python 删掉之后**，那条锚就没了，剩下的锚只有：基线的 `n_values` 身份栏、
查询集那条值本身、以及**它在版本控制里的历史**。
⇒ 建议（需要 Go 侧配合，不在本工具范围）：让 Go CLI 能**列出它认识的代号/关卡**，
则「Go 说有 73 个」↔「冻结的查询集有 73 个」就是一条**独立来源**的分母对账。

## 目录 / 用法

    python tools\\freeze_baseline.py --list                 # 26 套与各自脚本
    python tools\\freeze_baseline.py --record 生命上限      # 录（**必须显式**，会印覆盖了谁）
    python tools\\freeze_baseline.py --check                # 只读：现读 vs 冻结 + 身份对账
    python tools\\freeze_baseline.py --status               # **主判据**：现算几套在冻结模式下跑得通
    python tools\\freeze_baseline.py --control 生命上限     # **每套都要做**：改坏一个冻的值 ⇒ 必须红
"""
from __future__ import annotations

import atexit
import copy
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

SCHEMA = "rios-golden-baseline/1"

ENV_MODE = "RIOS_GOLDEN"
ENV_OUT = "RIOS_GOLDEN_OUT"          # record：收下来的值写到这里（父进程读走再落盘）
ENV_DIR = "RIOS_GOLDEN_DIR"          # 基线目录，缺省 <仓根>/fixtures/golden
ENV_RUNNER = "RIOS_GOLDEN_RUNNER"    # 由 runner 置 1：check 档**必须**经它起进程

OFF, RECORD, CHECK = "off", "record", "check"

#: 通道自己的错误码。**与判据的码分开**：6 ＝「这一套还没转」，不是「判据红」。
RC_CHANNEL = 6

ROOT = Path(__file__).resolve().parents[1]
TOOLS = Path(__file__).resolve().parent
PY = sys.executable

#: 冻结模式下**禁止** import 的顶层包名。
FORBIDDEN = ("ak_tactic",)


# =============================================================================
# 一 · 通道（判据脚本 import 本模块，用 bind / expect）
# =============================================================================

def _channel_fail(msg: str) -> None:
    """通道自己的错 ⇒ **一律 rc=6**，绝不与「判据红」共用一个码。

    ★ 为什么单独一个函数：本文件里有十来处「这一套还没转」的出口
    （无基线 / 键缺 / 顶层 import / 键不可 JSON 化 / 直跑）。
    它们各自写一遍 `raise SystemExit(文字)` 的话，Python 给的码是 **1**
    ——那正好是「判据红」的码，两个完全不同的意思压进同一个数。
    """
    sys.stderr.write(msg.rstrip() + "\n")
    sys.stderr.flush()
    raise SystemExit(RC_CHANNEL)


def _dump(obj) -> str:
    """基线落盘的**唯一**写法。紧凑（不缩进）。

    ★ 缩进会把几 MB 的关卡基线再放大两成，而它**每次缓存长大都要重录**
    （实测关卡缓存 72 → 320）。机器数据的可读性由工具提供，不由缩进提供。
    """
    return json.dumps(obj, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def mode() -> str:
    raw = (os.environ.get(ENV_MODE) or "").strip().lower()
    if raw in ("", "0", "off", "none"):
        return "off"
    if raw == RECORD:
        return RECORD
    if raw == CHECK:
        return CHECK
    #: 打错字不许静默掉回 off——那会把「我以为在验冻结基线」变成一次普通的对拍。
    _channel_fail("★ RIOS_GOLDEN=%r 不是合法取值（off / record / check）" % raw)


def golden_dir() -> Path:
    return Path(os.environ.get(ENV_DIR) or (ROOT / "fixtures" / "golden"))


def suite_file(suite: str) -> Path:
    return golden_dir() / ("%s.json" % suite)


def sh16(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()[:16]


def file_sha16(path: str | Path) -> str:
    return sh16(Path(path).read_bytes())


def _canon(obj) -> str:
    """键的规范化写法。**不可 JSON 化即大声失败**——不许 `default=str` 糊过去。"""
    try:
        return json.dumps(obj, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    except (TypeError, ValueError) as e:
        _channel_fail(
            "★ 冻结基线的键不可 JSON 化（%s）：%r\n"
            "  键必须自带全部输入且可 JSON 化；把不可序列化的对象拆成字段再传。" % (e, obj))


def _jsonable(v, where: str) -> None:
    if v is None or isinstance(v, (bool, int, float, str)):
        return
    if isinstance(v, (list, tuple)):
        for i, x in enumerate(v):
            _jsonable(x, "%s[%d]" % (where, i))
        return
    if isinstance(v, dict):
        for k, x in v.items():
            if not isinstance(k, str):
                _channel_fail("★ %s 的键不是字符串（%r）——JSON 化会静默改名" % (where, k))
            _jsonable(x, "%s.%s" % (where, k))
        return
    _channel_fail(
        "★ %s 的期望值不可 JSON 化（%s）：%r\n"
        "  冻结基线只收无聊的 JSON；取不出来的那部分就具名登记成「不转」的理由。" %
        (where, type(v).__name__, v))


def _short(key) -> str:
    s = _canon(key)
    return s if len(s) <= 160 else s[:157] + "..."


def _now() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


#: 拦截器响过的名字（用来把「还没转完」判成 **rc=6**，而不是让 ImportError 变成 rc=1）。
_BLOCKED: list[str] = []


class AkBlocker:
    """`check` 档下把 `ak_tactic` 物理封死。

    ★ 没有它，「还没转的取期望值点」会静默走回 Python：判据照样绿，而绿的来源
    正是**我们要断奶的那一侧**（本仓记过：闸门不放行时的静默退回＝假绿）。
    """

    def find_spec(self, fullname, path=None, target=None):     # noqa: ANN001
        head = fullname.split(".")[0]
        if head in FORBIDDEN:
            #: ★ 记一笔。否则这个 ImportError 会以 **rc=1**（＝**判据红**的码）
            #: 退出去，而它真正的意思是「**还没转完**」（rc=6）——
            #: 两个完全不同的意思又被压进同一个数（本轮实测：练度那一套就是这样，
            #: 一行只用来打印的 `import ak_tactic.verify` 把 rc 从 6 变成 1）。
            _BLOCKED.append(fullname)
            raise ImportError(
                "★ 冻结基线模式（RIOS_GOLDEN=check）禁止 import %s ——\n"
                "  这一套里还有取期望值的地方没走 freeze_baseline.expect()，"
                "或那里面的 import 写在模块顶层（含**只用来打印**的那种）。\n"
                "  这是「还没转完」的具名信号（rc=6），**不是判据红**。" % fullname)
        return None


class Coverage:
    """**输入批次**的对账：这一次要问的对象集，与冻的那一批比。

    ★ 为什么单独一个东西：乙类套（关卡/敌人/计划/…）的**对象集是活的**——
    `check_go_all` 按缓存现算关卡清单喂进来，而缓存在被别的会话逐章取数时**会长大**
    （实测当晚 72 → 320）。于是「现读 ≠ 冻结」有两种**完全不同**的因：

    * **Go 漂移了** ⇒ 判据红，要人去看实现；
    * **对象集变了**（多了/少了关卡）⇒ 读数**不可用**，基线该重录。

    这两种红压成一种，后果是本仓记过的那条：**永久假红等于没有判据**——
    天天红的判据，最后没人看。
    """

    def __init__(self, covered, extra, missing):
        self.covered = covered        # 两边都有（按输入身份配上的）
        self.extra = extra            # 只在**这一批**里有 ⇒ 基线没冻它们
        self.missing = missing        # 只在**冻的那一批**里有 ⇒ 分母缩水

    @property
    def ok(self) -> bool:
        return not self.extra and not self.missing

    def report(self, tag: str, n_live: int) -> str:
        lines = [
            "★ 输入批次对账（%s）：这一批 %d 个对象 ＝ 覆盖 %d ＋ **未覆盖 %d**；"
            "冻的那一批另有 %d 个**这次没问**"
            % (tag, n_live, len(self.covered), len(self.extra), len(self.missing)),
        ]
        if self.extra:
            lines.append("  · 基线里没有（前 8 个）：%s"
                         % "、".join(str(x[0]) for x in self.extra[:8]))
        if self.missing:
            lines.append("  · 这次没问、但冻着（前 8 个）：%s"
                         % "、".join(str(x[0]) for x in self.missing[:8]))
        lines.append(
            "  ⇒ **这不是「Go 漂移了」，是「录的是哪一批对象」变了**："
            "未覆盖的对象拿不到冻的期望值，分母因此不完整。\n"
            "     处置＝重录（`python tools\\freeze_baseline.py --record <套名>`）；"
            "重录是显式的、会印出覆盖了谁。")
        return "\n".join(lines)


class Channel:
    def __init__(self, suite: str, script: str | Path):
        self.suite = suite
        self.script = Path(script).resolve()
        self.mode = mode()
        self.values: dict[str, object] = {}          # record：收下来的
        self.readable: dict[str, str] = {}           # record：给人读的键
        self.frozen: dict[str, object] = {}          # check：冻的那份
        self.frozen_readable: dict[str, str] = {}
        self.meta: dict = {}
        self.n_hit = 0
        self.n_miss = 0
        self.coverage_used = False                   # 用过 input 批次对账就置起
        self.batch_used = False                      # 批次记录**真的进了判定**就置起
        self.section_rows: list[dict] = []           # 逐段覆盖面声明（第四态的依据）
        self.sections_declared = False

    def batch_consumed(self) -> None:
        """声明：本套**用**冻的批次记录做判定（不只是记着）。

        ★ 为什么要声明而不是让工具去猜：`--control` 的 **P4**（同一对象集、内容变了）
        只对**红得起来**的套有意义。判据是「记录被消费」——不声明的话，工具要么
        猜错、要么给一套红不起来的探针，而**一条永远不响的探针比没有更坏**
        （它看起来像有守卫）。
        """
        self.batch_used = True

    # ---- 覆盖面：第四态「部分覆盖」的落点 ---------------------------------

    #: 段的三种类。**工具按它计数，不按形容词**。
    SECTION_CLASSES = ("frozen", "python_both", "source_coupled")

    def sections(self, rows: list[dict]) -> None:
        """**逐段声明**本套判据的覆盖面。每行一条：

            {"id": "§2", "class": "python_both",
             "why": "harness() 与 spec['spawns'] 两侧都是 Python"}

        `class` 只能是三者之一：

        * `frozen` —— 这一段的两侧是「Python 期望值 ↔ Go 现读」⇒ 冻得住；
        * `python_both` —— **两侧都是 Python**（差分／敏感性／控制组）⇒
          冻住等于**让同一份冻值跟自己比**（恒等假绿，本仓禁止的「两把相同的尺子互证」）；
        * `source_coupled` —— 期望值取自**源码文本**（ast 等）⇒ 等值冻它＝每次改源码
          都该重录＝**永久假红**（本仓：永久假红等于没有判据）。

        ★ 声明进基线（`payload["sections"]`）。**`--status` 据此把这一套判成
        「部分覆盖」，而部分覆盖永远不进「跑通」的分子**——否则主判据会说谎
        （分子静默缩水，只不过这次缩的是**分子**）。

        ⚠ **信任模型**：这是**套自己声明**的，**工具验不了它是否真的覆盖了那么多**。
        工具只保证两件事：**声明可见**、**且不许当跑通**。
        （与 `batch_consumed` 同一个信任模型。）
        """
        rows = list(rows)
        for r in rows:
            if not isinstance(r, dict) or not r.get("id") or not r.get("why"):
                _channel_fail("★ 段声明必须带 id 与 why（这是一张表，不是形容词）：%r" % (r,))
            if r.get("class") not in self.SECTION_CLASSES:
                _channel_fail("★ 段「%s」的 class=%r 不合法（只能是 %s）"
                              % (r.get("id"), r.get("class"),
                                 "／".join(self.SECTION_CLASSES)))
        self.section_rows = rows
        self.sections_declared = True

    def section_counts(self) -> tuple[int, int, int]:
        """(总段数, 可冻段数, 未覆盖段数)。"""
        rows = getattr(self, "section_rows", []) or []
        un = [r for r in rows if r.get("class") != "frozen"]
        return len(rows), len(rows) - len(un), len(un)

    def uncovered_sections_text(self) -> str:
        rows = getattr(self, "section_rows", []) or []
        un = [r for r in rows if r.get("class") != "frozen"]
        if not un:
            return ""
        n_all, n_frozen, _ = self.section_counts()
        return "（本套冻结覆盖 %d/%d 段；%s 不适用等值冻结）" % (
            n_frozen, n_all,
            "／".join("%s %s" % (r["id"], r["class"]) for r in un))

    # ---- 输入批次（乙类：对象集是活的）------------------------------------

    def coverage(self, tag: str, live: list[tuple]) -> Coverage:
        self.coverage_used = True
        src = self.values if self.mode == RECORD else self.frozen
        frozen_groups: set[tuple] = set()
        for k in src:
            try:
                parts = json.loads(k)
            except (TypeError, ValueError):
                continue
            if isinstance(parts, list) and parts and parts[0] == tag and len(parts) >= 2:
                frozen_groups.add(tuple(parts[1:]))
        live_groups = {tuple(x) for x in live}
        if self.mode == RECORD:
            return Coverage(sorted(live_groups), [], [])
        covered = sorted(live_groups & frozen_groups)
        extra = sorted(live_groups - frozen_groups)
        missing = sorted(frozen_groups - live_groups)
        return Coverage(covered, extra, missing)

    def groups(self, tag: str) -> set[tuple]:
        """冻的那一批里按 `tag` 分组的**对象身份**集合（键去掉 tag 之后的部分）。

        给「要自己按归属分类」的套用（例如敌人的 refs：它既是 Go 的产出、
        又是查询集的来源——归属要分得比 `coverage()` 更细）。
        """
        out: set[tuple] = set()
        for k in self.frozen:
            try:
                parts = json.loads(k)
            except (TypeError, ValueError):
                continue
            if isinstance(parts, list) and parts and parts[0] == tag and len(parts) >= 2:
                out.add(tuple(parts[1:]))
        return out

    # ---- 唯一取数口 --------------------------------------------------------

    def expect(self, key, thunk):
        """取一个期望值。**判据唯一的取数口**。"""
        if self.mode == "off":
            return thunk()
        ck = _canon(key)
        if self.mode == RECORD:
            v = thunk()
            _jsonable(v, "套「%s」的键 %s" % (self.suite, ck))
            if ck in self.values and self.values[ck] != v:
                #: 同一个键两次算出不同的值 ⇒ 键没带全输入。**必须当场响**：
                #: 否则录下来的是一份「某一次的」值，而判据以为它是这份输入的函数。
                _channel_fail(
                    "★ 同一个键录到两个不同的值 —— 键没带全输入：\n    %s\n"
                    "  先前 %r，这次 %r" % (ck, self.values[ck], v))
            self.values[ck] = v
            self.readable[ck] = _short(key)
            return v
        #: ---- CHECK：只读冻的那份；缺键**不许**退回 Python（拦截器也让它退不回去）
        if ck in self.frozen:
            self.n_hit += 1
            return self.frozen[ck]
        self.n_miss += 1
        _channel_fail(
            "★ 冻结基线里没有这个键（套「%s」）：\n    %s\n"
            "  基线＝%s（录于 %s）。两种可能：\n"
            "    ① 这一套的取期望值点加过/改过而基线没重录；\n"
            "    ② 键没带全输入。\n"
            "  重录用：python tools\\freeze_baseline.py --record %s"
            % (self.suite, self.frozen_readable.get(ck, ck), suite_file(self.suite),
               self.meta.get("recorded_at", "（未记）"), self.suite))

    # ---- record 档落盘 ------------------------------------------------------

    def payload(self) -> dict:
        rel = None
        try:
            rel = self.script.relative_to(ROOT).as_posix()
        except ValueError:
            rel = str(self.script)
        return {
            "schema": SCHEMA,
            "suite": self.suite,
            "script": rel,
            "script_sha256_16": file_sha16(self.script),
            "recorded_at": _now(),
            "instrument": instrument_identity(),
            "python": python_identity(),
            #: ★ 这一套的**对象集是活的**（键里自带输入身份，见 `coverage()`）。
            #: 记下来给 `--control` 用：它据此决定要不要做「对象集变小」那个探针。
            "input_identity": bool(self.coverage_used),
            #: ★ 记下来给 `--control` 的 **P4** 用（同一对象集、内容变了）：
            #: 只有**记录真的进了判定**的套才红得起来那个形状，见 `batch_consumed()`。
            "batch_consumed": bool(self.batch_used),
            #: ★ **第四态「部分覆盖」的依据**：逐段声明 ＋ 由工具数出来的三个数。
            #: `--status` 据此把这一套判成 `部分覆盖`，而**它永远不进「跑通」的分子**。
            #: ⚠ 声明是**套自己写的**，工具验不了覆盖是否真有那么多——只保证
            #: 「声明可见」＋「不许当跑通」。
            "sections": self.section_rows,
            "sections_total": self.section_counts()[0],
            "sections_frozen": self.section_counts()[1],
            "sections_uncovered": self.section_counts()[2],
            "n_values": len(self.values),
            "values": self.values,
            "keys_readable": self.readable,
        }

    def _flush(self) -> None:
        if self.mode != RECORD:
            return
        out = os.environ.get(ENV_OUT)
        if not out:
            #: ★ 没有出口就大声失败：静默不落盘＝录了一整轮的假账。
            _channel_fail("★ record 档没有 RIOS_GOLDEN_OUT —— 收下来的值无处可去")
        Path(out).write_text(_dump(self.payload()), encoding="utf-8")

    def summary(self) -> str:
        if self.mode == "off":
            return ""
        #: ★ **未覆盖段每次都要印出来**（按名字）——覆盖面要在**用它的地方**可见，
        #: 不是只在一个要另外去跑的地方（`--status`）可见。
        tail = self.uncovered_sections_text()
        if self.mode == RECORD:
            return "★ 冻结基线通道 record —— 收下 %d 个期望值（套「%s」%s）%s" % (
                len(self.values), self.suite,
                "，含输入批次身份" if self.coverage_used else "",
                ("　" + tail) if tail else "")
        import_status = ("已封死（sys.modules 里没有顶层名 ak_tactic）"
                         if "ak_tactic" not in sys.modules else
                         "**仍在 sys.modules 里**（不该出现，请报）")
        return ("★ 冻结基线通道 check —— 取期望值 %d 次全部命中冻的那份，零次吃 Python；"
                "%s%s" % (self.n_hit, import_status, ("\n" + tail) if tail else ""))


_CHANNEL: Channel | None = None


def bind(suite: str, script: str | Path) -> Channel:
    """绑定套名与脚本。**每个 check 脚本在 main() 开头调一次**。"""
    global _CHANNEL
    ch = Channel(suite, script)
    _CHANNEL = ch
    if ch.mode == "off":
        return ch
    if ch.mode == RECORD:
        atexit.register(ch._flush)
        return ch
    #: ---- CHECK ----
    if os.environ.get(ENV_RUNNER) != "1":
        #: ★ **check 档不许直跑**：直跑时没转过的脚本**根本不会调 bind()**，
        #: 于是它照常跑 Python 并报绿——「未转」被读成「已转」。
        #: 典型触发面：有人把 `RIOS_GOLDEN=check` 导进环境，再跑 `check_go_all.py`
        #: （它是**直跑**子进程的）⇒ 4 套真冻结、23 套假绿，一张总表看不出区别。
        #: 与其把这条写成文档里的警告，不如让它**物理上做不到**。
        _channel_fail(
            "★ check 档**不许直跑**（缺 %s=1 这个 runner 标记）。\n"
            "  直跑时「没转过的套」不会调 bind()，会照常跑 Python 并报绿 ——\n"
            "  那是本设计要堵死的那种假绿。请改用：\n"
            "    python tools\\freeze_baseline.py --status | --check | --control | "
            "--run-script <脚本>" % ENV_RUNNER)
    if "ak_tactic" in sys.modules:
        _channel_fail(
            "★ 套「%s」在 import 期就吃了 ak_tactic（脚本顶层 import）—— 冻结模式不适用。\n"
            "  改法：把取期望值用的 import 搬进 oracle 函数里，顶层只留 "
            "`import freeze_baseline`。\n"
            "  在此之前，这一套的状态是「未转」，具名理由＝顶层 import。" % suite)
    if not any(isinstance(f, AkBlocker) for f in sys.meta_path):
        sys.meta_path.insert(0, AkBlocker())
    f = suite_file(suite)
    if not f.is_file():
        _channel_fail(
            "★ 套「%s」还没有冻结基线：%s\n"
            "  先录：python tools\\freeze_baseline.py --record %s" % (suite, f, suite))
    blob = load_frozen(suite)
    if blob.get("schema") != SCHEMA:
        _channel_fail("★ 冻结基线 schema 不是 %s：%s（实得 %r）"
                         % (SCHEMA, f, blob.get("schema")))
    ch.frozen = blob.get("values") or {}
    ch.frozen_readable = blob.get("keys_readable") or {}
    ch.meta = blob
    return ch


def load_frozen(suite: str) -> dict:
    """只读一份冻结基线（给工具与 `check` 档用）。"""
    f = suite_file(suite)
    if not f.is_file():
        return {}
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        _channel_fail("★ 冻结基线读不了（%s）：%s" % (f, e))


def channel_summary() -> str:
    return _CHANNEL.summary() if _CHANNEL is not None else ""


# =============================================================================
# 二 · 身份（基线的身份，不是元数据噪声）
# =============================================================================

def _git(*args: str) -> tuple[int, str]:
    p = subprocess.run(["git", *args], cwd=str(ROOT),
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return p.returncode, p.stdout.decode("utf-8", "replace").strip()


def git_head() -> str:
    rc, out = _git("rev-parse", "HEAD")
    return out if rc == 0 else "（取不到：rc=%d）" % rc


def git_dirty(pathspec: str) -> list[str]:
    rc, out = _git("status", "--porcelain", "--", pathspec)
    if rc != 0:
        return ["（取不到：rc=%d）" % rc]
    return [ln.strip() for ln in out.splitlines() if ln.strip()]


def ak_tactic_sig() -> dict:
    """`ak_tactic/` 的目录签名：全部 `.py` 的 `(相对路径, sha256)` 排序后再摘要。

    ★ 只用 `git HEAD` 判不了「这份基线取自哪个 Python 状态」：工作区可能是脏的，
    而**脏的那几行正是期望值的来源**。所以另带一份脏文件名单。
    """
    base = ROOT / "ak_tactic"
    rows = []
    if base.is_dir():
        for f in sorted(base.rglob("*.py")):
            rows.append("%s:%s" % (f.relative_to(base).as_posix(),
                                   hashlib.sha256(f.read_bytes()).hexdigest()))
    return {"n_py": len(rows), "sig16": sh16(("\n".join(rows)).encode("utf-8"))}


def python_identity() -> dict:
    return {
        "version": sys.version.split()[0],
        "executable": sys.executable,
        "git_head": git_head(),
        "ak_tactic": ak_tactic_sig(),
        "ak_tactic_dirty": git_dirty("ak_tactic"),
    }


def instrument_identity() -> dict:
    """仪器 `RIOS_SIM_BIN`：路径 ＋ **内容 sha256(16)** ＋ mtime ＋ 大小。

    ★ 读数的身份先于读数的值（本仓栽过：未设 `RIOS_SIM_BIN` 即落共享 exe，
    同一份基线、同一批夹具，只差仪器就绿红翻转）。
    """
    p = Path(resolve_exe())
    if not p.is_file():
        #: 默认路径必须大声失败，不退回任何东西。
        _channel_fail("★ 找不到仪器 %s —— 冻结基线不许在不知道仪器是谁的情况下录"
                         % p)
    st = p.stat()
    return {
        "path": str(p),
        "sha256_16": file_sha16(p),
        "size": st.st_size,
        "mtime": datetime.datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
    }


def resolve_exe() -> str:
    """仪器路径。**默认路径要能大声失败**，不许静默落共享 exe。"""
    return os.environ.get("RIOS_SIM_BIN") or str(
        ROOT / "out" / "acceptance" / "rios-sim-stage3.exe")


# =============================================================================
# 三 · 套表（**唯一来源**是 check_go_all.SUITE，不在这里抄第二份）
# =============================================================================

#: ★ **第三态**：不适用于冻结的套（**不是「未转」**）。口径见 `docs/golden-baseline.md` §4。
#: 为什么要有这张表而不是只在文档里写一句：文档里写了、`--status` 却把它们算进「未转」，
#: 那两条登记就**互相打架**（一边说三种状态，一边只认两种）。这里是**唯一**的分类处，
#: 文档只指向它、不抄第二份。
NOT_APPLICABLE: dict[str, str] = {
    "命令面": "被测方就是 Python CLI（spawn `python -m ak_tactic stage …`）——它测的是 "
              "Python，不是从 Python 取期望值，所以没有「Python 侧的期望值」可冻。",
    "敌方机制": "它的期望值**不从 Python 取**：判据是「数据侧现算键空间」与"
                "「**两台引擎的源码文本**现算消费面」（`rios-sim/*.go` 与 `ak_tactic/**.py`）"
                "两面求差 ⇒ 冻 Python 的输出**没有宾语**。"
                "若改冻 Go 自己的产物（已消费／具名 unported／未建模三类划分），"
                "其输入**含 Go 源码本身** ⇒ 任何一次改 Go 都会让它失效（rc=6 该重录），"
                "那就是本仓记过的「**永久假红等于没有判据**」。"
                "⇒ 正确定位是**棘轮/账本**（「已消费集合不许缩小」），不是等值基线；"
                "那是另一种工具形状。"
                "⚠ 附带一条：它**读** Python 源码文本（不调它），所以 `ak_tactic/` 删掉之后"
                "它「Python 侧有落点」那条腿的定义要重估。",
}


def suite_table() -> list[tuple[str, str, str, bool]]:
    """(套名, 脚本, 这条判据答什么, 要不要喂关卡清单)。"""
    sys.path.insert(0, str(TOOLS))
    import check_go_all                                        # noqa: PLC0415
    return list(check_go_all.SUITE)


_LEVELS: list[str] | None = None


def cached_levels() -> list[str]:
    """`check_go_all.cached_levels()`（**同一份**，不在本文件抄第二遍）。"""
    global _LEVELS
    if _LEVELS is None:
        sys.path.insert(0, str(TOOLS))
        import check_go_all                                    # noqa: PLC0415
        _LEVELS = list(check_go_all.cached_levels())
    return _LEVELS


def suite_args(name: str) -> list[str]:
    """喂给这一套的**额外参数**——与总入口同一口径。

    ★ 必须与 `check_go_all` 同源：关卡/敌人那几套的取证范围是**调用方喂进来的
    清单**（按缓存现算）。这里不给清单的话，`--record`／`--status` 只会跑那一套的
    **缺省样本**（1 关）——**分母小得误导**，正是本仓记过的形状
    （总表印「1 / 1」看着漂亮、覆盖面其实是抽样）。
    """
    for n, _s, _w, wants in suite_table():
        if n == name:
            return list(cached_levels()) if wants else []
    return []


def level_inputs(data_dir: Path | str, levels: list[str]) -> list[dict]:
    """关卡批次的**输入身份**：关卡 id ＋ `data_path` ＋ 缓存文件**内容 sha16**。

    ★ **数据侧**取数（只读 json 与文件字节），**不 import `ak_tactic`** ⇒ 冻结档也跑得动。
    ★ 关卡与敌人两套**共用这一份公式**——本仓记过：同一个公式两处各写一份，
      一改就对不上（`source_sig` 那次的根因就是这个）。
    """
    data_dir = Path(data_dir)
    idx = json.loads((data_dir / "_level_index.json").read_text(encoding="utf-8"))
    out = []
    for lid in levels:
        e = idx.get(lid)
        if e is None:
            _channel_fail("★ 权威索引里没有这个关卡：%s（缓存清单与索引不是同一批？）" % lid)
        p = data_dir / "map.ark-nights.com" / "levels" / e["data_path"]
        if not p.is_file():
            _channel_fail("★ 关卡 %s 的缓存文件不在场：%s" % (lid, p))
        out.append({"level": lid, "data_path": str(e["data_path"]),
                    "sha16": file_sha16(p)})
    return out


# =============================================================================
# 四 · runner：起一个子进程，先装防线，再跑判据脚本
# =============================================================================

_SPAWNED: list[str] = []


def _patch_subprocess() -> None:
    """把「spawn 出去的子进程里提到了 ak_tactic」记下来。

    ★ **拦截器的边界**：`sys.meta_path` 只盖得住**本进程**的 import。判据若
    `subprocess.run([PY, "-m", "ak_tactic", …])` 去取期望值，拦截器**看不见它**。
    与其把这句写成文档里的口号，不如把它变成**一个数**：spawn 过几次、argv 是什么，
    每次都印在结论旁边。0 次才有资格说「这一套没从子进程吃 Python」。
    """
    import subprocess as _sp
    if getattr(_sp.Popen, "_golden_patched", False):
        return
    orig = _sp.Popen.__init__

    def patched(self, args, *a, **kw):                          # noqa: ANN001
        try:
            flat = " ".join(str(x) for x in args) if isinstance(args, (list, tuple)) \
                else str(args)
        except Exception:                                       # noqa: BLE001
            flat = repr(args)
        if "ak_tactic" in flat:
            _SPAWNED.append(flat[:240])
        return orig(self, args, *a, **kw)

    patched._golden_patched = True                              # type: ignore[attr-defined]
    _sp.Popen.__init__ = patched


def _runner(argv: list[str]) -> int:
    """`--run-script <脚本> [给脚本的参数…]`：**由一个进程统一装防线**。

    ⚠ 为什么不直接 `python tools/check_x.py` 加环境变量：那样**没转过的脚本一个字
    没改、也不会调 `bind()`**，于是它照常跑 Python 并报绿——「未转」被读成「已转」。
    经过这里，`check` 档有两道防线：
      ① 任何 `import ak_tactic` 立即 ImportError；
      ② 退出时若这一套**从未** `bind()`，以 `rc=6` 收场。
    """
    m = mode()
    script = Path(argv[0]).resolve()
    args = argv[1:]
    #: 打上 runner 标记：check 档的 bind() 会认它（直跑不许进冻结档，见 bind）。
    os.environ[ENV_RUNNER] = "1"
    if m == CHECK and not any(isinstance(f, AkBlocker) for f in sys.meta_path):
        sys.meta_path.insert(0, AkBlocker())
    if m == CHECK:
        #: 拦截器只盖本进程；子进程那条路要**计数**（见 `_patch_subprocess`）。
        _patch_subprocess()

    def _guard() -> None:
        if m == "off":
            return
        if m == CHECK and _SPAWNED:
            sys.stdout.write(
                "★ 冻结档下 spawn 过 %d 个子进程，其命令行里提到 ak_tactic：\n%s\n"
                "  ⇒ **拦截器盖不到子进程**。这一套的取数口是不是全走 "
                "G.expect()，要人判（被测方本来就是 Python CLI 的套不算违规）。\n"
                % (len(_SPAWNED), "\n".join("    " + s for s in _SPAWNED[:4])))
            sys.stdout.flush()
        #: ★ 通道对象要读**判据脚本拿到的那一份**：`python tools/freeze_baseline.py`
        #: 时本文件既是 `__main__` 又是模块 `freeze_baseline`，是**两个不同的模块
        #: 对象**、各有一份 `_CHANNEL`。判据脚本 `import freeze_baseline as GB` 拿到的
        #: 是**模块副本**；守卫若只看 `__main__` 那份，就会把「绑过了」读成「没绑」
        #: ——实测：第一版正是这样，record 档把每一套都判成未转。
        ch = _CHANNEL
        if ch is None:
            mod = sys.modules.get("freeze_baseline")
            ch = getattr(mod, "_CHANNEL", None) if mod is not None else None
        if ch is None:
            sys.stderr.write(
                "★ 冻结基线防线：套「%s」从未绑定通道（脚本没调 "
                "freeze_baseline.bind()）⇒ **未转**，rc=6。\n"
                "  这不是判据红：把它读成绿才是真错。\n" % script.name)
            sys.stderr.flush()
            os._exit(RC_CHANNEL)
        if _BLOCKED:
            #: ★ 「还没转完」必须退 **6**，不能让它以 ImportError 的身份退 1
            #: （1 是**判据红**的码）。两者压成一个数，读的人就无法分辨
            #: 「该去看实现」还是「该去把这一套转完」。
            sys.stderr.write(
                "★ 冻结基线防线：拦截器响过（import %s）⇒ **未转完**，rc=6。\n"
                "  这不是判据红——把那一处 import 搬进 oracle 函数里，"
                "或改走 G.expect()。\n" % "、".join(_BLOCKED[:3]))
            sys.stderr.flush()
            os._exit(RC_CHANNEL)
        if m == CHECK:
            #: ★ **覆盖面每次都要印**（第四态的第一条规矩）：由 runner 自动印，
            #: 不依赖套的作者记得写那一行——「只在 --status 里可见」是不够的。
            try:
                tail = ch.uncovered_sections_text()
            except AttributeError:
                tail = ""
            if tail:
                sys.stdout.write(
                    "★ 本套是**部分覆盖**：%s\n"
                    "  ⇒ 未覆盖的那几段**不适用等值冻结**（两侧同源 ⇒ 冻了就是恒等假绿；\n"
                    "     源码耦合 ⇒ 冻了就是永久假红）。**这一套不计入「跑通」。**\n"
                    % tail.lstrip("（").rstrip("）"))
                sys.stdout.flush()
        if m == CHECK and ch.n_miss:
            sys.stderr.write("★ 冻结基线防线：缺键 %d 个 ⇒ rc=6。\n" % ch.n_miss)
            sys.stderr.flush()
            os._exit(RC_CHANNEL)

    atexit.register(_guard)
    src = script.read_text(encoding="utf-8")
    sys.argv = [str(script), *args]
    sys.path.insert(0, str(script.parent))
    g = {"__name__": "__main__", "__file__": str(script), "__builtins__": __builtins__}
    try:
        exec(compile(src, str(script), "exec"), g)             # noqa: S102
    except SystemExit as e:
        return int(e.code) if isinstance(e.code, int) else (0 if e.code is None else 1)
    return 0


def run_suite(script: str, extra: list[str], mode_: str, out: Path | None,
              timeout: float) -> dict:
    """跑一套判据（**总是经 runner**），把 rc / 输出 / 通道出口都收回来。"""
    env = {**os.environ, ENV_MODE: mode_, "RIOS_SIM_BIN": resolve_exe(),
           "PYTHONIOENCODING": "utf-8"}
    if out is not None:
        env[ENV_OUT] = str(out)
    cmd = [PY, "-X", "utf8", str(Path(__file__).resolve()),
           "--run-script", str(ROOT / script), *extra]
    t0 = time.time()
    try:
        p = subprocess.run(cmd, cwd=str(ROOT), capture_output=True, env=env,
                           timeout=timeout)
        rc, so, se = p.returncode, p.stdout, p.stderr
    except subprocess.TimeoutExpired as e:
        rc, so, se = 124, e.stdout or b"", (e.stderr or b"") + "\n★ 超时".encode("utf-8")
    return {"rc": rc, "sec": round(time.time() - t0, 1),
            "out": so.decode("utf-8", "replace"), "err": se.decode("utf-8", "replace")}


def verdict_of(out: str) -> str:
    v = ""
    for line in out.splitlines():
        if line.startswith("结论："):
            v = line.strip()
    return v


def named_reason(r: dict) -> str:
    """从输出里抠出**具名**的不转理由（不是「跑不通」三个字）。"""
    blob = (r["err"] or "") + "\n" + (r["out"] or "")
    for line in blob.splitlines():
        s = line.strip()
        if s.startswith("★") and ("冻结基线" in s or "禁止 import" in s or "未转" in s):
            return s.lstrip("★ ").strip()
    if r["rc"] == 124:
        return "超时（未在限内跑完）"
    return ""


# =============================================================================
# 五 · CLI
# =============================================================================

def cmd_list() -> int:
    rows = suite_table()
    print("套表来源：tools/check_go_all.py 的 SUITE（**不在这里抄第二份**）")
    print("共 %d 套；冻结基线目录：%s" % (len(rows), golden_dir()))
    print("-" * 92)
    for name, script, what, _ in rows:
        f = suite_file(name)
        if f.is_file():
            meta = load_frozen(name)
            state = "已录 %d 值（%s）" % (meta.get("n_values", 0),
                                         meta.get("recorded_at", "?"))
        else:
            state = "**无基线**"
        print("%-6s %-34s %s" % (name, script, state))
        print("       %s" % what)
    return 0


# ---- 控制组（每套都要做，贴在新路上）----------------------------------------

def _tamper(v, sentinel: int = 999999):
    """把一个期望值**改坏一处**，返回改后的值；改不动就返回 `None`。

    ★ 只作**控制组**用（探针），任何写回基线的路径都不会调它。
    ⚠ **会原地改**传入的那个对象（递归进 dict/list）⇒ **调用方必须先 deepcopy**。
    实测教训：第一版用浅拷贝，`_tamper` 把内存里的真值也改了，于是下一个探针
    凭空多出一条「改值」——控制组自己把读数污染了。
    """
    if isinstance(v, bool):
        return not v
    if isinstance(v, (int, float)):
        return v + 1.0
    if isinstance(v, str):
        return v + "<tampered>"
    if isinstance(v, list):
        #: 加一个哨兵元素：格集合/键名单都能被它撞出差异。
        return v + [[sentinel, sentinel]]
    if isinstance(v, dict):
        for kk in sorted(v):
            t = _tamper(v[kk], sentinel)
            if t is not None:
                v[kk] = t
                return v
    return None


#: 非「期望值」的两类键前缀：查询集与判定/计数口径常量。P1 只挑**期望值**。
_NON_EXPECT_PREFIX = ('["query"', '["consts"')


_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def _p4_target(values: dict):
    """找一个**可改的内容 sha**：`("query", …)` 那张记录表里某个 16 位字段。

    返回 `(键, 记录序号, 字段名, 旧值)`；找不到返回 `None`（该套 P4 不适用）。

    ★ 为什么判据是「**批次记录**里带内容 sha」而不是「键里带 sha」：
    * 改**批次记录**里那一项 ⇒ 对象集不变、**内容**变了（P4 要的那个形状）；
    * 改**键里**那一项 ⇒ 那个键配不上 ⇒ 走的是「**对象集**变了」的形状（P3 的形状）。
      两者都 rc=6，但**印出来的诊断不同**——混起来等于把两种因压成一个。
    """
    for k in sorted(values):
        if not k.startswith('["query"'):
            continue
        v = values[k]
        if not isinstance(v, list):
            continue
        for i, rec in enumerate(v):
            if not isinstance(rec, dict):
                continue
            for f in sorted(rec):
                x = rec[f]
                if isinstance(x, str) and _HEX16.match(x):
                    return (k, i, f, x)
    return None


def _p4_why(values: dict) -> str:
    """P4 不适用的**具名**理由（不许写「不适用」三个字了事）。

    ⚠ 这个函数**只在 `_p4_target()` 返回 `None` 之后才成立**：它说的
    「记录里没有 16 位字段」是**结论**，不是它自己查出来的。
    （第一版把这一句接在「记录不被消费」那条分支后面，于是印出一句
    **与事实相反**的话——字段表里明明有 `sha16`。输出的每一句都要是真的。）
    """
    qkeys = [k for k in sorted(values) if k.startswith('["query"')]
    if not qkeys:
        return "本套没有冻结的批次记录（`(\"query\", …)`）——它的对象集写死在脚本里"
    v = values[qkeys[0]]
    if not isinstance(v, list):
        return "批次记录不是列表（%s）——没有可改的项" % type(v).__name__
    if not v or not isinstance(v[0], dict):
        return ("批次记录是**扁平值表**（%s）——没有可改的字段，内容身份若住在别处，"
                "改它走的是别的形状" % type(v[0]).__name__)
    return "批次记录的记录里**确实没有** 16 位十六进制字段（字段表：%s）" % sorted(v[0])


def _keys_carry_sha(values: dict) -> bool:
    """期望值的**键**里有没有 16 位内容 sha（内容身份住在键里的一种形状）。"""
    for k in values:
        if k.startswith(('["query"', '["consts"')):
            continue
        try:
            parts = json.loads(k)
        except (TypeError, ValueError):
            continue
        if isinstance(parts, list) and any(
                isinstance(x, str) and _HEX16.match(x) for x in parts[1:4]):
            return True
    return False


def _diff_keys(oldv: dict, nowv: dict) -> tuple[list, list, list]:
    """现读与冻结的逐键差：新增 / 消失 / 同键改值。**只此一份**。

    （本仓记过：同一个公式两处各写一份，一改就对不上。）
    """
    added = sorted(set(nowv) - set(oldv))
    gone = sorted(set(oldv) - set(nowv))
    diff = sorted(k for k in set(oldv) & set(nowv) if oldv[k] != nowv[k])
    return added, gone, diff


def _run_with_dir(script: str, mode_: str, d: Path, timeout: float,
                  extra: list[str] | None = None) -> dict:
    """把基线目录指到 `d` 跑一次判据（控制组用；跑完还原环境变量）。"""
    old = os.environ.get(ENV_DIR)
    os.environ[ENV_DIR] = str(d)
    try:
        return run_suite(script, extra or [], mode_, None, timeout)
    finally:
        if old is None:
            os.environ.pop(ENV_DIR, None)
        else:
            os.environ[ENV_DIR] = old


def _live_values(script: str, timeout: float,
                 extra: list[str] | None = None) -> tuple[dict | None, dict]:
    """现读：以 record 档跑一遍判据，把通道出口读进内存（**不落盘**）。"""
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td) / "now.json"
        r = run_suite(script, extra, RECORD, tmp, timeout)
        if not tmp.is_file():
            return None, r
        return (json.loads(tmp.read_text(encoding="utf-8")).get("values") or {}), r


def cmd_control(names: list[str], timeout: float) -> int:
    """★ **敏感性控制组**：把冻的值改坏一处，判据**必须红**。

    本仓规矩：**控制组没红时工具自己吼出来并 exit 1**（没有反向守卫的绿是零信息量的绿）。
    两个探针，极性相反、各堵一种洞：

    * **P1 改一个期望值** ⇒ 必须**判红**。
      证明的是这句：**冻的值真的是 oracle**，而不是「读了个文件、判决照旧看 Go」。
    * **P2 从查询集里删一个** ⇒ 冻结档**看不见分母变小**（这是有界的盲区，读数照印，
      不假装不存在）；而 `--check`（拿**现读**的查询集对账）**必须看见**。
      两条合起来才说明：分母缩水这件事有补偿控制，且补偿控制真的管用。
    """
    rows = suite_table()
    known = {n: s for n, s, _w, _l in rows}
    names = names or [n for n, _s, _w, _l in rows]
    print("=" * 92)
    print("冻结基线的敏感性控制组（**每套都要做，贴在新路上**）")
    print("=" * 92)
    bad = 0
    for name in names:
        if name not in known:
            print("✗ 套名不在 SUITE 里：%r" % name)
            bad += 1
            continue
        script = known[name]
        extra = suite_args(name)          # 与总入口同一口径（关卡/敌人要喂清单）
        blob = load_frozen(name)
        values = blob.get("values") or {}
        if not values:
            print("⊘ %-6s 无基线，控制组无从做起（先 --record）" % name)
            continue
        print("-" * 92)
        print("%s（%s）；基线 %d 个值" % (name, script, len(values)))
        n_q = sum(1 for k in values if k.startswith('["query"'))
        n_c = sum(1 for k in values if k.startswith('["consts"'))
        print("  键的类：查询集 %d ／ 判定·计数口径常量 %d ／ 期望值 %d"
              % (n_q, n_c, len(values) - n_q - n_c))

        #: ---- P1：改一个**期望值** ----------------------------------------
        #: ⚠ 不许挑查询集或常量：改常量**未必**进判决（例如「攻击间隔」的
        #: `ASPD_MIN` 只进行使计数），拿它当 P1 会出一条假的「没红」。
        vkeys = [k for k in sorted(values)
                 if not k.startswith(_NON_EXPECT_PREFIX)]
        if not vkeys:
            print("  ✗ P1 跳过：基线里只有查询集/常量、没有期望值")
            bad += 1
        else:
            pick = vkeys[0]
            t1 = copy.deepcopy(values)
            nv = _tamper(t1[pick])
            if nv is None:
                print("  ✗ P1 跳过：挑不到可改坏的期望值（%s）" % pick[:90])
                bad += 1
            else:
                t1[pick] = nv
                with tempfile.TemporaryDirectory() as td:
                    d = Path(td)
                    b1 = copy.deepcopy(blob)
                    b1["values"] = t1
                    (d / ("%s.json" % name)).write_text(
                        json.dumps(b1, ensure_ascii=False), encoding="utf-8")
                    r1 = _run_with_dir(script, CHECK, d, timeout, extra)
                red = r1["rc"] != 0 and r1["rc"] != RC_CHANNEL
                if red:
                    print("  ✓ P1 改坏 %s ⇒ 判据红（rc=%d）：%s"
                          % (pick[:90], r1["rc"], verdict_of(r1["out"]) or "（无结论行）"))
                else:
                    print("  ✗ P1 改坏 %s ⇒ **判据没红**（rc=%d）—— 冻的值可能没进判决路径"
                          % (pick[:90], r1["rc"]))
                    bad += 1

        #: ---- P2：查询集删一个 --------------------------------------------
        qkey = next((k for k in sorted(values) if k.startswith('["query"')), None)
        if qkey is None:
            print("  ⊘ P2 不适用：本套没有冻结的查询集（`(\"query\", …)`）")
        else:
            qv = values[qkey]
            if not isinstance(qv, list) or len(qv) < 2:
                print("  ⊘ P2 不适用：查询集不是长度 ≥2 的列表（%r）" % type(qv).__name__)
            else:
                t2 = copy.deepcopy(values)
                t2[qkey] = qv[1:]
                b2 = copy.deepcopy(blob)
                b2["values"] = t2
                with tempfile.TemporaryDirectory() as td:
                    d = Path(td)
                    (d / ("%s.json" % name)).write_text(
                        json.dumps(b2, ensure_ascii=False), encoding="utf-8")
                    r2 = _run_with_dir(script, CHECK, d, timeout, extra)
                live, _r3 = _live_values(script, timeout, extra)
                #: ⚠ 查询集被删一个**不是**「新增/消失」：键还是同一个键，变的是**值**。
                #: 所以它落在「改值」那一栏——这条口径写清楚，别让人去找不存在的键差。
                added, gone, diff = _diff_keys(t2, live or {})
                print("  · P2 查询集 %d → %d 个问题：冻结档 rc=%d  %s"
                      % (len(qv), len(qv) - 1, r2["rc"],
                         verdict_of(r2["out"]) or "（无结论行）"))
                if blob.get("input_identity"):
                    #: ★ 这一套的**真正查询集是调用方给的清单**（对象集是活的）。
                    #: 那条 `("query", …)` 到底「只是记录」还是「被消费」，**按实测说**：
                    #: 实测「敌人」是**被消费**的（它决定比哪些关 ⇒ 改小它就红），
                    #: 而在冻的那批里改小它不一定等于「分母缩水」——措辞不许含糊，
                    #: 说错会让人去查一个不存在的东西。
                    if r2["rc"] == 0:
                        print("    ⇒ 冻结档**看不见**那条批次记录被改小"
                              "（它只问调用方给的那批对象）—— 有界盲区，登记不掩饰")
                    else:
                        print("    ⇒ 冻结档**自己就红了**（rc=%d）—— 这条不是盲区："
                              "那条记录**被消费**（它参与决定比哪些对象）" % r2["rc"])
                else:
                    print("    ⇒ 冻结档**看不见分母被改小**（它只问冻住的那批问题，"
                          "照样全绿）——有界盲区，登记不掩饰")
                if added or gone or diff:
                    print("    ✓ P2b `--check`（拿**现读**的查询集对账）看见了："
                          "新增 %d / 消失 %d / 改值 %d（查询集落在「改值」栏）"
                          % (len(added), len(gone), len(diff)))
                else:
                    print("    ✗ P2b `--check` **没看见**查询集被删 —— 补偿控制失效")
                    bad += 1

        #: ---- P3：对象集变小（只对**带输入身份**的套）------------------------
        #: 乙类套的对象集是活的（缓存长大就变）。这条探针证的是**分类**这件事：
        #: 「对象集变了」必须被报成**对象变了**，而不是被读成「Go 漂移了」。
        if not blob.get("input_identity"):
            print("  ⊘ P3 不适用：本套的键不带输入身份"
                  "（对象集写死在脚本里或来自冻结的查询集）")
        else:
            groups: dict[tuple, list[str]] = {}
            for k in sorted(values):
                if k.startswith(_NON_EXPECT_PREFIX):
                    #: ★ 只对**期望值键**分组。把 `("query", …)`／`("consts", …)`
                    #: 也放进来，会挑中一个「不是对象」的键去删——实测（练度那一套）
                    #: 它挑中了 `consts/loadout_names`，删掉之后套直接报错 rc=1，
                    #: 于是 P3 判「没被判成对象变了」——一条**假红**。
                    continue
                try:
                    parts = json.loads(k)
                except (TypeError, ValueError):
                    continue
                if not isinstance(parts, list) or len(parts) < 2:
                    continue
                #: ★ 分组的锚＝**内容 sha 那一位前面的那个分量**。键常常长成
                #: `(标签, 名, sha, …)`／`(标签, 关卡, sha, id, lv)`——按「前两位」
                #: 分组会把**同一个对象的多个标签**拆成好几组（实测 出怪规格：
                #: 它挑中了 `counters` 那一组，删掉后套报「缺键」而不是「对象集变了」，
                #: 于是 P3 判「没被判成对象变了」——又一条假红）。
                idx = next((i for i, x in enumerate(parts)
                            if isinstance(x, str) and _HEX16.match(x)), None)
                gk = (parts[idx - 1], parts[idx]) if idx else tuple(parts[:2])
                groups.setdefault(gk, []).append(k)
            pick_g = max(groups, key=lambda g: len(groups[g])) if groups else None
            if pick_g is None:
                print("  ✗ P3 跳过：基线里挑不出「按对象分组」的键")
                bad += 1
            else:
                drop = set(groups[pick_g])
                t3 = {k: v for k, v in values.items() if k not in drop}
                b3 = copy.deepcopy(blob)
                b3["values"] = t3
                with tempfile.TemporaryDirectory() as td:
                    d = Path(td)
                    (d / ("%s.json" % name)).write_text(_dump(b3), encoding="utf-8")
                    r3 = _run_with_dir(script, CHECK, d, timeout, extra)
                named = "输入批次对账" in (r3["out"] + "\n" + r3["err"])
                print("  · P3 删掉一个对象的全部键（%s，共 %d 键）：冻结档 rc=%d"
                      % ("/".join(str(x) for x in pick_g), len(drop), r3["rc"]))
                if r3["rc"] == RC_CHANNEL and named:
                    print("    ✓ 被判成**对象变了**（rc=6 且印出「输入批次对账」）"
                          "—— 与「Go 漂移了」（判据红 rc=1）分得开")
                else:
                    print("    ✗ **没有**被判成对象变了（rc=%d，具名消息=%s）"
                          "—— 这两种红会混成一个" % (r3["rc"], named))
                    bad += 1

            #: ---- P3b：反方向——**这一批少问了**（冻着、这次没问）------------
            #: 缓存被清（本仓真出过：`git worktree remove` 穿透 junction 删过
            #: 主仓 `data/`）时就是这个形状：分母缩水，而它**不红**才是灾难。
            if not extra:
                print("  ⊘ P3b 不适用：本套不从调用方拿清单（没有可少问的对象）")
            else:
                short = extra[:-1]
                r4 = run_suite(script, short, CHECK, None, timeout)
                named4 = "输入批次对账" in (r4["out"] + "\n" + r4["err"])
                print("  · P3b 少喂一个对象（%d → %d）：冻结档 rc=%d"
                      % (len(extra), len(short), r4["rc"]))
                if r4["rc"] == RC_CHANNEL and named4:
                    print("    ✓ 被判成**分母缩水**（rc=6 且印出「输入批次对账」）"
                          "—— 「这次没问」不会被当成绿")
                else:
                    print("    ✗ **没有**被判成分母缩水（rc=%d，具名消息=%s）"
                          % (r4["rc"], named4))
                    bad += 1

        #: ---- P4：同一对象集、**内容**变了（与 P3 是**两个不同的诊断**）--------
        #: P3 改的是**对象集**（多/少一个对象）；P4 改的是对象的**内容**。
        #: 两者都 rc=6，但印出来的话不一样，而下一个人要靠那句话决定
        #: 「重录」还是「查对象集」。
        #: ★ **只对红得起来的套加**：判据是**批次记录被消费**（套自己声明）＋
        #: 记录里真有 16 位内容 sha。硬加到红不起来的套上，只会造出一条
        #: **永远不响的探针**——那比没有探针更坏（它看起来像有守卫）。
        if not blob.get("batch_consumed"):
            print("  ⊘ P4 不适用：本套的批次记录**不参与判定**（套没声明消费它）")
            print("     具体：%s"
                  % ("内容身份住在**键**里 ⇒ 改它得到的是「键配不上」＝"
                     "**对象集变了**那个形状（那是 P3 的形状，不是 P4）"
                     if _keys_carry_sha(values) else _p4_why(values)))
        else:
            tgt = _p4_target(values)
            if tgt is None:
                print("  ⊘ P4 不适用：记录被消费了，但%s" % _p4_why(values))
            else:
                qkey, idx, field, old = tgt
                new = ("deadbeef" + old[8:]) if not old.startswith("deadbeef") \
                    else ("cafebabe" + old[8:])
                #: ★ **自证改到了东西**：不印这一行的话，「改了没红」与「根本没改」
                #: 在输出上长得一样（本仓记过的那类假信号）。
                assert new != old
                print("  · P4 **我改的是这一项**：批次记录第 %d 项的 %s：%s → %s"
                      % (idx, field, old, new))
                b5 = copy.deepcopy(blob)
                b5["values"][qkey][idx][field] = new
                with tempfile.TemporaryDirectory() as td:
                    d = Path(td)
                    (d / ("%s.json" % name)).write_text(_dump(b5), encoding="utf-8")
                    r5 = _run_with_dir(script, CHECK, d, timeout, extra)
                blob5 = r5["out"] + "\n" + r5["err"]
                named5 = "输入批次对账" in blob5
                if r5["rc"] == RC_CHANNEL and named5:
                    print("    ✓ 被判成**内容变了**（rc=6 且印出「输入批次对账」）")
                else:
                    print("    ✗ **没有**被判成内容变了（rc=%d，具名消息=%s）"
                          % (r5["rc"], named5))
                    bad += 1
    print("-" * 92)
    if bad:
        print("★ %d 处控制组不成立 —— **这一批的绿全部作废**"
              "（本仓规矩：控制组没红就是没有判据）" % bad)
        return 1
    print("✓ 全部控制组成立（P1 都红；P2b 都看得见分母被改小；"
          "P3 都把对象集变小判成「对象变了」；P4 在适用的套上都判成「内容变了」）")
    return 0


def _old_identity_text(meta: dict) -> str:
    py = meta.get("python") or {}
    ak = py.get("ak_tactic") or {}
    ins = meta.get("instrument") or {}
    return (
        "    套名        ：%s\n"
        "    脚本        ：%s（内容 sha16=%s）\n"
        "    录制时刻    ：%s\n"
        "    仪器        ：%s sha256(16)=%s mtime=%s\n"
        "    Python      ：%s（%s）\n"
        "    取自的源码态：HEAD=%s；ak_tactic/ 签名=%s（%d 个 .py；脏 %d 条）\n"
        "    值的条数    ：%s"
        % (meta.get("suite"), meta.get("script"), meta.get("script_sha256_16"),
           meta.get("recorded_at"), ins.get("path"), ins.get("sha256_16"),
           ins.get("mtime"), py.get("version"), py.get("executable"),
           py.get("git_head"), ak.get("sig16"), ak.get("n_py", 0),
           len(py.get("ak_tactic_dirty") or []), meta.get("n_values")))


def cmd_record(names: list[str], timeout: float) -> int:
    rows = suite_table()
    known = {n: s for n, s, _w, _l in rows}
    if not names:
        raise SystemExit("★ --record 必须显式点名要录哪几套（或 --all）。"
                         "可录的套名见 --list。")
    if names == ["--all"]:
        names = [n for n, _s, _w, _l in rows]
    bad = 0
    for name in names:
        if name not in known:
            print("✗ 套名不在 SUITE 里：%r" % name)
            bad += 1
            continue
        script = known[name]
        target = suite_file(name)
        print("=" * 92)
        print("录：%s（%s）" % (name, script))
        if target.is_file():
            #: ★ **覆盖必须留痕**：本仓记过「生成物被静默覆盖，没有历史」。
            old = load_frozen(name)
            print("★ 这次会**覆盖**已有基线：%s" % target)
            print("  旧文件的录制身份：")
            print(_old_identity_text(old))
            print("  旧值与新值的关系在下面「值差异」栏里逐块报出。")
        else:
            print("新建：%s" % target)
        extra = suite_args(name)
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "recorded.json"
            r = run_suite(script, extra, RECORD, tmp, timeout)
            print("  跑法：RIOS_GOLDEN=record 经 runner（rc=%d，%.1fs）；喂参数 %d 个%s"
                  % (r["rc"], r["sec"], len(extra),
                     "（关卡/敌人清单，与总入口同一口径）" if extra else ""))
            if r["rc"] == RC_CHANNEL or not tmp.is_file():
                print("✗ 录不出值（rc=%d）：%s" % (r["rc"], named_reason(r) or "通道没收下任何值"))
                for line in (r["err"] or "").strip().splitlines()[-6:]:
                    print("    " + line)
                bad += 1
                continue
            new = json.loads(tmp.read_text(encoding="utf-8"))
            if target.is_file():
                oldv = load_frozen(name).get("values") or {}
                newv = new.get("values") or {}
                added = sorted(set(newv) - set(oldv))
                gone = sorted(set(oldv) - set(newv))
                diff = sorted(k for k in set(oldv) & set(newv) if oldv[k] != newv[k])
                print("  值差异：新增 %d 键 / 消失 %d 键 / 同键不同值 %d 个"
                      % (len(added), len(gone), len(diff)))
                for tag, ks in (("新增", added), ("消失", gone), ("改值", diff)):
                    for k in ks[:5]:
                        print("    %s %s" % (tag, k[:120]))
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(_dump(new), encoding="utf-8")
            print("✓ 已写入 %s（%d 个值）" % (target, new.get("n_values")))
    return 1 if bad else 0


def cmd_check(names: list[str], timeout: float) -> int:
    """**只读**：现读 vs 冻结，逐项对账；一个字节都不写回基线。"""
    rows = suite_table()
    known = {n: s for n, s, _w, _l in rows}
    names = names or [n for n, _s, _w, _l in rows]
    print("冻结基线目录：%s" % golden_dir())
    print("模式：**只读**（现读经由 RIOS_GOLDEN=record 收进内存，**不落盘**）")
    print("-" * 92)
    prob = 0
    havemeta = None
    for name in names:
        if name not in known:
            print("✗ 套名不在 SUITE 里：%r" % name)
            prob += 1
            continue
        f = suite_file(name)
        if not f.is_file():
            print("⊘ %-6s 无基线（未转）" % name)
            continue
        meta = load_frozen(name)
        if havemeta is None:
            havemeta = meta
        script = known[name]
        now_sha = file_sha16(ROOT / script)
        notes = []
        if now_sha != meta.get("script_sha256_16"):
            notes.append("脚本内容已变（基线 %s / 现在 %s）⇒ 该重录"
                         % (meta.get("script_sha256_16"), now_sha))
        ins_now = instrument_identity()
        ins_old = (meta.get("instrument") or {}).get("sha256_16")
        if ins_now["sha256_16"] != ins_old:
            notes.append("仪器与录制时不同（基线 %s / 现在 %s；**这是常态**，"
                         "Go 漂移本来就该红）" % (ins_old, ins_now["sha256_16"]))
        py_now = python_identity()
        ak_now = py_now["ak_tactic"]["sig16"]
        ak_old = ((meta.get("python") or {}).get("ak_tactic") or {}).get("sig16")
        if ak_now != ak_old:
            notes.append("ak_tactic/ 签名与录制时不同（基线 %s / 现在 %s）⇒ "
                         "**期望值可能已经变了**" % (ak_old, ak_now))
        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td) / "now.json"
            r = run_suite(script, suite_args(name), RECORD, tmp, timeout)
            if not tmp.is_file():
                print("✗ %-6s 现读收不上（rc=%d）：%s" % (name, r["rc"],
                                                         named_reason(r) or "无出口"))
                prob += 1
                continue
            nowv = json.loads(tmp.read_text(encoding="utf-8")).get("values") or {}
        oldv = meta.get("values") or {}
        added, gone, diff = _diff_keys(oldv, nowv)
        if added or gone or diff:
            prob += 1
            print("✗ %-6s 现读与冻结**不一致**：新增 %d / 消失 %d / 改值 %d"
                  % (name, len(added), len(gone), len(diff)))
            for tag, ks, src in (("新增", added, nowv), ("消失", gone, oldv),
                                 ("改值", diff, None)):
                for k in ks[:6]:
                    if src is None:
                        print("    %s %s：冻 %r → 现 %r" % (tag, k[:110], oldv[k], nowv[k]))
                    else:
                        print("    %s %s = %r" % (tag, k[:110], src[k]))
        else:
            print("✓ %-6s 现读 ≡ 冻结（%d 个值逐键相同）" % (name, len(oldv)))
        for n in notes:
            print("    ⚠ %s" % n)
    print("-" * 92)
    if prob:
        print("★ %d 套对不上（含无基线的套不计入）" % prob)
        return 1
    print("✓ 全部有基线的套：现读 ≡ 冻结")
    return 0


def cmd_status(names: list[str], timeout: float, quick: bool, show: bool) -> int:
    """**主判据**：现算「26 套里几套在冻结模式下跑得通」。"""
    rows = suite_table()
    picked = [(n, s, w, l) for n, s, w, l in rows if not names or n in names]
    exe = resolve_exe()
    ins = instrument_identity()
    print("=" * 92)
    print("冻结基线进度（**现算**，不是登记表）")
    print("=" * 92)
    print("仪器：%s" % exe)
    print("     sha256(16)=%s mtime=%s" % (ins["sha256_16"], ins["mtime"]))
    print("套表：tools/check_go_all.py 的 SUITE，共 %d 套；本次跑 %d 套" % (len(rows), len(picked)))
    if quick:
        print("★ --quick：**不跑**默认档那一腿 ⇒ 下表「默认档」栏印 ⊘，"
              "即「两者同一结论」这条**本次没验**")
    else:
        print("说明：默认档那一腿**只在有基线的套上跑**（那句话只对已录的套有意义）；"
              "没基线的套印 ⊘无基线，它在默认档的绿由 check_go_all.py 总表覆盖。")
    print("-" * 92)
    green = 0
    na = 0
    partial: list[tuple[str, int, int]] = []
    rows_out = []
    for name, script, _what, _l in picked:
        if name in NOT_APPLICABLE:
            #: **第三态**：不适用于冻结 ⇒ 不进「跑得通」也不进「待转」，
            #: 否则那两条登记（文档说三种状态／本表只认两种）会互相打架。
            na += 1
            print("⊘ %-6s 不适用于冻结  %s" % (name, NOT_APPLICABLE[name]))
            continue
        f = suite_file(name)
        recorded = f.is_file()
        #: ★ **第四态「部分覆盖」的依据读自基线**（套逐段声明的三个数）。
        meta0 = load_frozen(name) if recorded else {}
        n_all = int(meta0.get("sections_total") or 0)
        n_un = int(meta0.get("sections_uncovered") or 0)
        extra = suite_args(name)
        r1 = run_suite(script, extra, CHECK, None, timeout)
        ok = r1["rc"] == 0 and n_un == 0
        if ok:
            green += 1
        elif r1["rc"] == 0 and n_un:
            #: ★ **部分覆盖永远不进「跑通」的分子**——否则主判据会说谎：
            #: 这一套的 check 档只覆盖了它一部分判据，却会以 rc=0 混进分子。
            partial.append((name, n_all - n_un, n_all))
        reason = ""
        if not ok:
            reason = named_reason(r1) or verdict_of(r1["out"]) or ("rc=%d" % r1["rc"])
        default_rc = None
        #: ★ 默认档那一腿**只在有基线的套上跑**：`两者必须给同一个结论`这句只对
        #: 已录的套有意义。没录的套在默认档绿不绿由 `check_go_all.py` 的总表覆盖
        #: ——在这里再跑一遍只是重复一次重活，而**不产出任何关于迁移的读数**。
        if not quick and recorded:
            r0 = run_suite(script, extra, "off", None, timeout)
            default_rc = r0["rc"]
        hit = ""
        for line in r1["out"].splitlines():
            if "冻结基线通道 check" in line:
                hit = line.strip()
        #: ★ 拦截器盖不到子进程 —— 那个数必须印出来，否则「封死了」是一句空话。
        spawn_note = ""
        for line in (r1["out"] + "\n" + r1["err"]).splitlines():
            if "spawn 过" in line:
                spawn_note = line.strip()
        rows_out.append((name, script, recorded, r1["rc"], default_rc, reason, hit))
        mark = "✓" if ok else ("◐" if r1["rc"] == 0 and n_un else "✗")
        if default_rc is None:
            d = "⊘无基线" if not recorded else "⊘"
        else:
            d = "绿" if default_rc == 0 else "红(%d)" % default_rc
        print("%s %-6s 冻结rc=%-3d 默认档=%-8s 基线=%s  %.1fs" %
              (mark, name, r1["rc"], d, "有" if recorded else "**无**", r1["sec"]))
        if r1["rc"] == 0 and n_un:
            print("        ◐ **部分覆盖**：声明 %d 段，其中 %d 段不适用等值冻结"
                  " ⇒ **不计入「跑通」**" % (n_all, n_un))
            for row in (meta0.get("sections") or []):
                if row.get("class") != "frozen":
                    print("           · %s（%s）：%s"
                          % (row.get("id"), row.get("class"), row.get("why")))
        if not ok and not (r1["rc"] == 0 and n_un):
            print("        未转理由：%s" % reason)
        if spawn_note:
            print("        %s" % spawn_note)
        if show and hit:
            print("        %s" % hit)
    print("-" * 92)
    denom = len(picked) - na
    print("★ **冻结模式下跑得通：%d / %d 套**（分母 ＝ 本次 %d 套 − 不适用于冻结 %d 套）"
          % (green, denom, len(picked), na))
    undone = [(n, rs) for n, _s, _r, c, _d, rs, _h in rows_out if c != 0]
    if not quick:
        #: ⚠ 分母只说**跑过默认档那一腿的套**（＝有基线的套）：拿总套数当分母，
        #: 会把「没跑」与「跑了但不一致」混成一个数（本仓记过：两套分母的数不许并列）。
        n_leg = sum(1 for _n, _s, _r, _c, d, _rs, _h in rows_out if d is not None)
        both = sum(1 for _n, _s, _r, c, d, _rs, _h in rows_out if c == 0 and d == 0)
        print("   有基线的 %d 套里，两种模式**都给绿**（＝这一套的基线录对了）：%d / %d"
              % (n_leg, both, n_leg))
    print("   **四分账**（**不重不漏**）：跑通 %d ＋ **部分覆盖 %d** ＋ 待转 %d "
          "＋ 不适用于冻结 %d ＝ 本次 %d 套"
          % (green, len(partial), len(undone), na, len(picked)))
    if partial:
        print("   ★ 部分覆盖（**永远不进「跑通」的分子**）：")
        for n, nf, nt in partial:
            print("     - %s：冻结覆盖 %d / %d 段；其余段两侧同源或源码耦合，"
                  "不适用等值冻结" % (n, nf, nt))
    if undone:
        print("   待转的 %d 套与具名理由：" % len(undone))
        for n, rs in undone:
            print("     - %s：%s" % (n, rs))
    print("   其中 %d 套连基线都没有。" % sum(1 for _n, _s, r, _c, _d, _rs, _h in rows_out
                                              if not r))
    #: 只要还有待转**或部分覆盖**，就没全绿 ⇒ rc=1（宁可严，不放宽守卫）。
    return 0 if (not undone and not partial) else 1


def main() -> int:
    argv = sys.argv[1:]
    if "--run-script" in argv:
        i = argv.index("--run-script")
        #: ★ 必须**转发给模块副本**：本文件被 `python tools/freeze_baseline.py` 起时，
        #: 它同时是 `__main__` 与模块 `freeze_baseline`（两个不同的模块对象、各有一份
        #: `_CHANNEL`）。判据脚本 `import freeze_baseline` 拿到的是模块副本，
        #: 所以 runner 与守卫也必须是那一份，否则「绑过没有」两边各看各的。
        import importlib
        return importlib.import_module("freeze_baseline")._runner(argv[i + 1:])
    if not argv or "-h" in argv or "--help" in argv:
        print(__doc__)
        return 0
    timeout = 1800.0
    if "--timeout" in argv:
        i = argv.index("--timeout")
        timeout = float(argv[i + 1])
        del argv[i:i + 2]
    action = None
    for a in ("--list", "--record", "--check", "--status", "--control"):
        if a in argv:
            action = a
            break
    if action is None:
        print("★ 没给动作。可用：--list / --record <套名…|--all> / --check [<套名…>] / "
              "--status [--quick] [--show] / --control [<套名…>]")
        return 2
    quick = "--quick" in argv
    show = "--show" in argv
    words = [a for a in argv if not a.startswith("--")]
    if "--all" in argv:
        #: `--all` 也是 `--` 开头，会被上面那行滤掉；这里补回来（否则它会变成
        #: 「没点名任何套」而拒跑，看不出是参数写法的锅）。
        words = words + ["--all"]
    if action == "--list":
        return cmd_list()
    if action == "--record":
        return cmd_record(words, timeout)
    if action == "--check":
        return cmd_check(words, timeout)
    if action == "--control":
        return cmd_control(words, timeout)
    return cmd_status(words, timeout, quick, show)


if __name__ == "__main__":
    raise SystemExit(main())
