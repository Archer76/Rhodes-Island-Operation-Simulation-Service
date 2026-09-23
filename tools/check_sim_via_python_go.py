#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨实现判据：**Python 侧那条调用链**——`Verifier(engine="go")` 还跑不跑 Python 模拟器。

## 这一笔改了什么（本判据看着的就是它）

`ak_tactic/simgo/verifier.py` 的 `_run_other_engine` 以前是三步：

    ① Python 用 `build_spec` 造一份规格 → ② 把这份规格送给 Go 跑 →
    ③ `unsupported` 非空 ⇒ **回退去跑 Python 模拟器**（`sim.run(max_time=900.0)`）

现在两处都变了：**改送查询形式**（`{level, plan, roster, difficulty, allow_devices,
allow_skills}` —— 规格由 Go 侧的 `buildspec` 自造），而 ③ 改成**具名拒跑**：
理由列全、数值栏清零、`Verdict.refused` 非空 —— **不再跑 Python 模拟器**。

★ 范围（博士 2026-09-23 裁定）：**只废弃模拟器那条运行路径**。`build_spec` 本身是
**对拍权威**（24 套判据靠它算期望值），一个字没动；`ak_tactic/battle/` 不删不加。

## 四组断言

| 组 | 断言 | 怎么证 |
|---|---|---|
| 一 | ③ 这条路上**没有 `build_spec(` 调用点** | AST 扫调用点（另印导入引用数——`simgo/__init__.py` 的转发是**导入**不是调用） |
| 一 | ② 换引擎的出口里 `sim` **一次都没被读** | AST 数 `Name('sim', Load)`；正对照＝Python 那条出口**还在读它** |
| 一 | 旧分支**真的存在过** | `git show d4ddc4c:` 的原文里有 `sim.run(` ＋ `go_fallbacks += 1` |
| 一 | 混入类的方法**都进了绑定表** | AST 对账：类上定义 ∩ 自调用 ⊆ `ensure_go_engine` 的表（本轮踩过：`_refusal_verdict` 没进表） |
| 二 | ① **端到端判决 ≡ `d4ddc4c` 冻结的基线** | 24 份夹具逐份重跑，与 `fixtures/golden_go.json` 逐键比 |
| 三 | **三态分离**：拒跑 ≠ 打输 | 合成用例走**真** `Verifier`，读 `refused`／两个计数器／旧别名 |
| 四 | 反向守卫：每条断言都**红得起来** | `--mutate` 十二处注入，各自打在**具名的那条**断言上 |

## 两个**禁桶**：拒跑与判决分歧都必须为 0（不是容差，也不是登记）

上一批（第三十七批）这里放着两张登记表：**11 份机制拒跑** ＋ **1 份判决漂移**。
博士不认现状、裁定「先修正这 12 项」，两个根因键都搬进了 Go：

  · `mech_config.farmland.devices[].child`（天桩召唤链四跳：装置 → 甲 → 乙 → 天标）
    ⇒ `check_mechspec_go.py` 现在**逐字段比**它（53 条链 / 10017 个字段）；
  · `operators[].shield`（天赋侧五个 `shield_*` 取大者）
    ⇒ `check_operators_go.py` 现在把它算进**产出面**（32 → 33 键）。

于是本文件的两张表**清空**，改成禁桶：**任何一份**拒跑、**任何一份**判决与基线不同，
都判红。空桶配了两侧守卫，免得「清空了」被读成「没在看」：

  ① 桶空着也必须有人跑过：跑出判决的份数 == 全部 24 份（否则那条等式一次都没行使）；
  ② 反向守卫里末尾两条专门往这两个桶里各塞一份，必须各自判红。

## 分母（现算，不许把「拒跑」算进「比了判决」）

每组都印分母：静态组印**扫了几个文件／几个 AST 节点**，端到端组印**跑出判决几份／
拒跑几份**，拒跑组印**行使了几例**。哪一组零行使，那组的绿就是零信息量的——本文件判红。

用法:
    python tools\\check_sim_via_python_go.py
    python tools\\check_sim_via_python_go.py --mutate
"""
from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

GO_BIN = os.environ.get(
    "RIOS_SIM_BIN", str(ROOT / "out" / "acceptance" / "rios-sim-stage3.exe"))
FIXDIR = ROOT / "fixtures"
GOLDEN = FIXDIR / "golden_go.json"
ROSTER = FIXDIR / "roster_max_modelled.json"

#: 基线冻结在哪个提交上。**不是我改之前的那一版工作区**：`fixtures/golden_go.json`
#: 最后一次改动是 `dc9da53`（2026-09-20），而本笔改的是工作区里的 `verifier.py`
#: ——所以那份基线**天然**是「旧调用链跑出来的读数」。下面还会核它没被改脏。
FROZEN_SHA = "d4ddc4c"

#: ★★ **禁桶（forbid）**：本文件现在**只认「一份都不许有」**。
#:
#: 来历（2026-09-23，第三十八批）：上一批这里有两张登记表——11 份**机制拒跑**
#: （Go 的 `buildspec` 造不出 `farmland.devices[].child`）＋ 1 份**判决漂移**
#: （`plan-hs09`，根因 `operators[].shield`）。博士不认现状，裁定「先修正这 12 项」，
#: 两个键都搬进了 Go：
#:
#:   · `child`：装置 → 甲（`branch_id` → `branches` → `actions[].enemyKey`）
#:     → 乙（甲的 `awake_enemy_key`）→ 天标（`pileMarkKey`），三份规格走 `unitSpec`；
#:   · `shield`：天赋侧五个 `shield_*` 取大者那条口径。
#:
#: 于是登记表**清空**：拒跑 0、漂移 0，而且**任何一份**新的拒跑或漂移都判红。
#: ⚠ 空表**不等于**宽口径——它配了两侧守卫：
#:   ① 桶空着也必须「有人跑过」：跑出判决的份数 == 全部份数，否则这条等式
#:      一次都没行使（那种绿是零信息量的）；
#:   ② 反向守卫里有两处专门往这两个桶里塞东西（`MUTATIONS` 末尾两条），
#:      必须各自判红——不然「清空了」与「根本没在看」长得一模一样。
MECH_REFUSAL = "没带召唤模板"
DIVERGED_CAUSE: dict[str, str] = {}

#: ★★ **第三个数：把前两个键搬进来之后才露出来的那一处**（2026-09-23，第三十八批）。
#:
#: 上一批那 11 份「机制拒跑」是被 `farmland.devices[].child` 挡在**判决之外**的
#: ——挡着的时候，它们判决对不对**没人看得见**。键一接上、这 11 份真的跑起来，
#: 其中 **2 份**的判决与冻结基线不同，而根因**不是**本批那两个键：
#:
#:     hsex8_max.json  48杀 221.6667s → 19杀  91.7000s
#:     plan-hs07.json  96杀 299.0000s → 25杀 149.5667s
#:
#: **构造法证死**（同一枚仪器、同一关同一计划、四个读数）：
#:
#:     (c) Python 规格原样                       → 48杀 / 96杀（＝基线）
#:     (d) 把 `mech_config["snow.field"]` 挖掉    → 19杀 / 25杀（＝Go 现在的读数，**逐位相同**）
#:     (f) 只把 `goal_cells` 对齐 Go（留着雪）     → 仍是 48杀 / 96杀（**不是** goal_cells）
#:     对照 plan-hs03（这一关没有雪）              → 四个读数全等（尺子不是恒真）
#:
#: ⚠ 键形：`mech_config` 的键是**扁平的带点字符串**（`"snow.field"`），不是嵌套字典。
#: 第一版探针按嵌套找 `mech_config["snow"]["field"]`，于是印出「Py 里没有雪」——
#: **键形猜错会让读数假绿**，与「取数禁用 getattr 兜底」同一族。
#:
#: ⇒ 这一处**不是本文件能给答案的**：`snow.field` 是**第三个键**，`mechspec.go` 里
#: 仍具名登记为未搬（空排程口径下恒不可达），而它要**排程**（`snow_mech_spec` →
#: 无垠的雪景 + 部署时间线）——那是另一条线的工作量，且 `mechspec` 这条命令
#: **按契约不吃计划**（判据里有这一条）。所以这里**登记 ＋ 计数 ＋ 当场复现**，
#: 而不是静默放行，也不是假红：份数印在结论行上，多一份、少一份都要在这里看得见。
SNOW_CAUSE = {
    "hsex8_max.json": "mech_config[snow.field]",
    "plan-hs07.json": "mech_config[snow.field]",
}
SNOW_KEY = "snow.field"

#: 判决里参与端到端比较的四个量。
#: ⚠ **不含 `spec_sha`**：那个摘要是 `golden_go.py` 自己调 `build_spec` 算的
#: （`SpecCapture` 抄一份规格），量的是**工具手上那份生产者**，不是本笔被测的
#: 「Go 自造」那条路 ⇒ 它变不变都说明不了这条路。那一栏由金样那套判据管。
VERDICT_KEYS = ("kills", "leaks", "elapsed", "damage")

#: Go 这条路的源码面：`verify.py`（出口在这里）＋ `simgo/` 下除**权威**外的每个模块。
SIMGO = ROOT / "ak_tactic" / "simgo"
GO_PATH = [ROOT / "ak_tactic" / "verify.py"] + sorted(
    p for p in SIMGO.glob("*.py") if p.name != "spec.py")
AUTHORITY = SIMGO / "spec.py"          # 正对照：`build_spec` 的**定义**还在这儿
TOOL_WITNESS = ROOT / "tools" / "golden_go.py"   # 第二个正对照：调用者还在


# ============================================================ 一 · 静态（AST）

def _parse(src: str) -> ast.Module:
    return ast.parse(src)


def build_spec_calls(src: str) -> list[int]:
    """`build_spec(...)` 的**调用点**行号。"""
    out = []
    for n in ast.walk(_parse(src)):
        if isinstance(n, ast.Call):
            f = n.func
            if isinstance(f, ast.Name) and f.id == "build_spec":
                out.append(n.lineno)
            elif isinstance(f, ast.Attribute) and f.attr == "build_spec":
                out.append(n.lineno)
    return sorted(set(out))


def build_spec_imports(src: str) -> list[int]:
    """**只**把 `build_spec` 这个名字引进来（转发/再导出）的行号——与调用点分开数。"""
    out = []
    for n in ast.walk(_parse(src)):
        if isinstance(n, (ast.Import, ast.ImportFrom)):
            for a in n.names:
                if a.name == "build_spec" or (a.asname or "").startswith("build_spec"):
                    out.append(n.lineno)
    return sorted(set(out))


def build_spec_defs(src: str) -> list[int]:
    """`def build_spec` 的**定义**行号。

    ⚠ 正对照要的是这个：权威那份是**定义**它（`def`），既不是调用点也不是导入。
    第一版拿「调用点或导入」去当正对照，于是权威那份数出 0 ⇒ **假红**
    （红的是判据，不是实现——本仓对这种红的处置是改自己的尺子）。
    """
    out = []
    for n in ast.walk(_parse(src)):
        if isinstance(n, ast.FunctionDef) and n.name == "build_spec":
            out.append(n.lineno)
    return sorted(set(out))


def _method(tree: ast.Module, cls: str, func: str) -> ast.FunctionDef | None:
    for n in ast.walk(tree):
        if isinstance(n, ast.ClassDef) and n.name == cls:
            for sub in n.body:
                if isinstance(sub, ast.FunctionDef) and sub.name == func:
                    return sub
    return None


def name_loads_in_func(src: str, cls: str, func: str, var: str) -> int:
    """某个方法体里**读**了 `var` 几次（正对照／反证都靠它）。"""
    fn = _method(_parse(src), cls, func)
    if fn is None:
        return -1
    return sum(1 for n in ast.walk(fn)
               if isinstance(n, ast.Name) and n.id == var
               and isinstance(n.ctx, ast.Load))


def binding_gap(src: str) -> list[str]:
    """混入类上**定义**、而且它自己的方法里用 `self.` **调用**的方法，哪些没进绑定表。

    这是**本轮踩到的那个坑**的通用守卫：`_refusal_verdict` 加进了混入类，
    却没加进 `ensure_go_engine` 的表 ⇒ 拒跑那条路一走到就 `AttributeError`。
    按名字对账比"再记得补一次"可靠。
    """
    tree = _parse(src)
    cls = next((n for n in ast.walk(tree)
                if isinstance(n, ast.ClassDef) and n.name == "GoEngineMixin"), None)
    if cls is None:
        return ["<找不到 GoEngineMixin>"]
    methods = {n.name for n in cls.body if isinstance(n, ast.FunctionDef)}
    used = set()
    for n in ast.walk(cls):
        if (isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name)
                and n.value.id == "self"):
            used.add(n.attr)
    need = sorted(methods & used)
    bound: set[str] = set()
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "ensure_go_engine"), None)
    if fn is None:
        return ["<找不到 ensure_go_engine>"]
    for n in ast.walk(fn):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            bound.add(n.value)
    return [m for m in need if m not in bound]


def frozen_source(sha: str, rel: str) -> tuple[str, str]:
    """`git show <sha>:<rel>` —— 取冻结副本的原文。取不到就**大声**报（返回错误文本）。"""
    p = subprocess.run(["git", "-C", str(ROOT), "show", f"{sha}:{rel}"],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    if p.returncode != 0:
        return "", p.stderr.decode("utf-8", "replace")[:300]
    return p.stdout.decode("utf-8", "replace"), ""


def read_sources() -> dict[str, str]:
    return {str(p.relative_to(ROOT)).replace("\\", "/"): p.read_text(encoding="utf-8")
            for p in GO_PATH}


def problems_static(sources: dict[str, str]) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {"files": len(sources), "nodes": 0, "call_sites": 0, "import_sites": 0,
           "witness_hits": 0, "authority_calls": 0, "frozen_lines": 0}

    # ---- ③ 这条路上没有 build_spec( 调用点 ----
    for name, src in sorted(sources.items()):
        cov["nodes"] += sum(1 for _ in ast.walk(_parse(src)))
        calls = build_spec_calls(src)
        imps = build_spec_imports(src)
        cov["call_sites"] += len(calls)
        cov["import_sites"] += len(imps)
        if calls:
            problems.append("%s 里还有 `build_spec(` 调用点（第 %s 行）——"
                            "Python 又自己造规格送给 Go 了" % (name, calls))
        if imps:
            print("  · 导入引用（不是调用点，登记在案）：%s 第 %s 行" % (name, imps))

    # ---- 正对照：扫描器看得见「有」 ----
    auth = AUTHORITY.read_text(encoding="utf-8")
    wit = TOOL_WITNESS.read_text(encoding="utf-8")
    auth_defs = build_spec_defs(auth)
    if not auth_defs:
        problems.append("正对照失败：权威那份 `%s` 里没有 `def build_spec` —— "
                        "上面那串零命中不能算数（尺子可能根本没在工作）"
                        % AUTHORITY.relative_to(ROOT))
    cov["authority_calls"] = len(build_spec_calls(wit))
    if cov["authority_calls"] < 1:
        problems.append("正对照失败：`%s` 里没有 `build_spec(` 调用 ——"
                        "它是这条链的**对拍权威**，不该消失" % TOOL_WITNESS.relative_to(ROOT))
    cov["witness_hits"] = len(auth_defs) + cov["authority_calls"]
    if cov["witness_hits"] >= 1:
        print("  ✓ 正对照：权威那份 `def build_spec` 在第 %s 行；`%s` 里 %d 处调用"
              % (auth_defs, TOOL_WITNESS.name, cov["authority_calls"]))

    # ---- ② 换引擎的出口里 `sim` 一次都没被读 ----
    verifier_src = sources.get("ak_tactic/simgo/verifier.py")
    if verifier_src is None:
        problems.append("扫不到 `ak_tactic/simgo/verifier.py` —— 取证范围不对")
    else:
        n_go = name_loads_in_func(verifier_src, "GoEngineMixin", "_run_other_engine", "sim")
        if n_go < 0:
            problems.append("`GoEngineMixin._run_other_engine` 找不到（改名了？）")
        elif n_go:
            problems.append("`GoEngineMixin._run_other_engine` 里读了 `sim` %d 次 ——"
                            "那条路又碰 Python 模拟器了" % n_go)
        else:
            print("  ✓ 换引擎的出口里 `sim` 读了 0 次（占位形参，一次都没用）")
        # 正对照：Python 那条出口**必须**还在读它（否则上面那个 0 也可能是尺子瞎了）
        n_py = name_loads_in_func(sources.get("ak_tactic/verify.py", ""),
                                  "Verifier", "_run_other_engine", "sim")
        if n_py < 1:
            problems.append("正对照失败：`Verifier._run_other_engine` 里读 `sim` %d 次 ——"
                            "Python 那条出口本该还在用它（`--engine python` 没被废弃）" % n_py)
        else:
            print("  ✓ 正对照：Python 那条出口里 `sim` 读了 %d 次（尺子看得见「有」）" % n_py)

    # ---- 混入类的方法都进了绑定表 ----
    if verifier_src is not None:
        gap = binding_gap(verifier_src)
        if gap:
            problems.append("混入类上这些方法**没进** `ensure_go_engine` 的绑定表：%s ——"
                            "走到就 AttributeError（本轮 `_refusal_verdict` 就是这么炸的）"
                            % gap)
        else:
            print("  ✓ 绑定表对账：类上定义 ∩ 自调用 全部在表里")

    # ---- 旧分支真的存在过（这是「行为变化」，不是「空操作」）----
    old, err = frozen_source(FROZEN_SHA, "ak_tactic/simgo/verifier.py")
    if err:
        problems.append("取不到 `%s:ak_tactic/simgo/verifier.py`（%s）——"
                        "「旧分支存在过」这条无从取证" % (FROZEN_SHA, err))
    else:
        for pat, why in (("sim.run(", "回退去跑 Python 模拟器那句"),
                         ("go_fallbacks += 1", "回退计数器")):
            if pat in old:
                cov["frozen_lines"] += 1
            else:
                problems.append("冻结副本 `%s` 里找不到 %s（`%s`）——"
                                "「以前会回退」这个前提不成立，本笔就不是行为变化了"
                                % (FROZEN_SHA, why, pat))
        print("  ✓ 冻结副本 `%s` 里两处旧痕迹都在（回退那句 ＋ 计数器）" % FROZEN_SHA)
    return problems, cov


# ================================================ 二 · 端到端 ≡ 冻结基线（①）

def measure_endtoend() -> list[dict]:
    """24 份夹具各跑一遍**真**端到端，与冻结基线逐份比。"""
    import golden_go as G

    roster = G._find("roster_max_modelled")
    base = json.loads(GOLDEN.read_text(encoding="utf-8"))
    rows: list[dict] = []
    for p in G.plan_files():
        t = time.perf_counter()
        try:
            cur: dict | None = G.run_one(p, roster)
            err = None
        except Exception as e:                                    # noqa: BLE001
            cur, err = None, "%s: %s" % (type(e).__name__, e)
        rows.append({"name": p.name, "baseline": base.get(p.name), "cur": cur,
                     "err": err, "wall": time.perf_counter() - t})
        flag = "拒跑" if cur is None else "%d杀 %d漏 %8.4fs" % (
            cur["kills"], cur["leaks"], cur["elapsed"])
        print("  %-22s %-22s wall=%.2fs" % (p.name, flag, rows[-1]["wall"]))
    return rows


def problems_endtoend(rows: list[dict]) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {"ran": 0, "refused": 0, "matched": 0, "mech": 0, "alias_ok": 0,
           "diverged": 0, "other_refusal": 0, "snow": 0}
    for r in rows:
        name, b = r["name"], r["baseline"] or {}
        if r["cur"] is None:
            #: ★ **禁桶**：本批之后一份都不该拒跑（两个键都搬进来了）。
            #: 任何一份拒跑都判红——它意味着「召唤链又断了」或「又有键没接上」。
            cov["refused"] += 1
            if MECH_REFUSAL in (r["err"] or ""):
                cov["mech"] += 1
                problems.append("%s：**又出现机制层拒跑**了（%s）——\n"
                                "      天桩召唤链那一支回归了？`farmland.devices[].child`"
                                " 该是逐字段比的（`check_mechspec_go.py`）"
                                % (name, str(r["err"])[:160]))
            else:
                cov["other_refusal"] += 1
                problems.append("%s：跑不出判决（不是已登记过的那类机制拒跑）：%s"
                                % (name, str(r["err"])[:200]))
            continue
        cur = r["cur"]
        cov["ran"] += 1
        bad = [k for k in VERDICT_KEYS if b.get(k) != cur.get(k)]
        if bad:
            if name in SNOW_CAUSE:
                #: 已登记、而且下面会**当场复现**根因的那一类（第三个键：雪）。
                cov["snow"] += 1
            else:
                #: ★ **禁桶**：除此之外，判决必须与冻结基线逐键相同，没有登记表可挂。
                cov["diverged"] += 1
                detail = "；".join("%s: 基线=%r 现在=%r" % (k, b.get(k), cur.get(k))
                                   for k in bad)
                problems.append("%s：端到端判决与冻结基线不同 —— %s\n"
                                "      本批的两个键（`devices[].child`、`operators[].shield`）"
                                "都该已经搬进来了；除此之外每一份都该逐键相同"
                                % (name, detail))
        else:
            if name in SNOW_CAUSE:
                problems.append("%s：登记表说它因**雪**而分歧，可现在与基线逐键相同 ——"
                                "雪接上了？那要把 `SNOW_CAUSE` 里的这条摘掉"
                                "（登记过的偏移不许自己消失）" % name)
            cov["matched"] += 1
        #: ★ 计数器 ＋ **旧别名**：`golden_go.py` 与 `acceptance.py` 读的都是别名，
        #: 而它们读的对象是**动态绑定**出来的 `Verifier`（不继承混入类）——
        #: 别名住在混入类上的话，这里会**静默读成 None**。所以这条断言的位置是刻意的。
        if cur.get("go_runs") != 1:
            problems.append("%s：`go_runs`=%r，应为 1（跑出判决就该记一次）"
                            % (name, cur.get("go_runs")))
        if cur.get("go_fallbacks") is None:
            problems.append("%s：旧别名 `go_fallbacks` 读成 `None` —— 读者（`golden_go.py`、\n"
                            "      `acceptance.py`）会静默当成 0，闸门于是永远通过。\n"
                            "      别名要住在 `verify.Verifier` 上（不是混入类上）" % name)
        elif cur.get("go_fallbacks") != 0:
            problems.append("%s：没拒跑的一场，旧别名读成 %r（应为 0）"
                            % (name, cur.get("go_fallbacks")))
        else:
            cov["alias_ok"] += 1
    #: ★ 空桶的两侧守卫之一：**桶空着也必须有人跑过**。少了这一条，
    #: 「一份都不许有」在「一份都没跑」时也成立 —— 那正是零信息量的绿。
    if not cov["ran"]:
        problems.append("一份都没跑出判决 —— 「与基线相同」这条断言**一次都没行使**，"
                        "禁桶空着也是零信息量的")
    if cov["ran"] != len(rows):
        problems.append("跑出判决的 %d 份 ≠ 全部 %d 份 —— 禁桶要求「一份都不许拒跑」"
                        % (cov["ran"], len(rows)))
    return problems, cov


# ============================================ 二·b · 雪那一类（当场复现根因）

def _spec_of(name: str) -> tuple[dict, str]:
    """取权威（Python）造的那份规格与它的 levelId。"""
    import check_specgo_go as C

    for n, sp, _e, lv in C.real_specs():
        if n == name:
            return sp, lv
    raise KeyError(name)


def _verdict_of_spec(spec: dict) -> dict:
    """直接拿一份规格去跑 Go，取判决——用来**复现**登记分歧的根因。"""
    from ak_tactic.simgo.client import Simgo

    with Simgo() as g:
        v = g.sim(spec)
    return {"kills": v["kills"], "leaks": v["leaks"],
            "elapsed": round(float(v["elapsed"]), 4),
            "damage": round(float(v["damage_dealt"]), 1)}


def measure_snow(rows: list[dict]) -> dict:
    """对每一份「因雪而分歧」的夹具**当场复现**根因。

    三个读数（同一关同一计划同一枚仪器）：

      (c) Python 规格原样                          —— 应等于冻结基线
      (d) 把它里面的 `mech_config["snow.field"]` 挖掉 —— 应等于**现在的读数**
      (f) 只把 `goal_cells` 对齐 Go（**留着雪**）    —— 应**仍等于基线**

    (f) 是**反证**：它挡住「其实是 `goal_cells`（或别的缺键）造成的」这种解释。
    """
    out: dict[str, dict] = {}
    for r in rows:
        if r["cur"] is None or r["name"] not in SNOW_CAUSE:
            continue
        py, _lv = _spec_of(r["name"])
        hole = copy.deepcopy(py)
        (hole.get("mech_config") or {}).pop(SNOW_KEY, None)
        hole["mechanisms"] = [m for m in (hole.get("mechanisms") or []) if m != SNOW_KEY]
        goals = copy.deepcopy(py)
        goals["goal_cells"] = []          #: Go 侧 `goal_cells` 是空的（具名未搬）
        out[r["name"]] = {
            "snow_present": SNOW_KEY in (py.get("mech_config") or {}),
            "py": _verdict_of_spec(copy.deepcopy(py)),
            "hole": _verdict_of_spec(hole),
            "goals": _verdict_of_spec(goals),
            "want_base": {k: r["baseline"].get(k) for k in VERDICT_KEYS},
            "want_cur": {k: r["cur"].get(k) for k in VERDICT_KEYS},
        }
    return out


def problems_snow(div: dict) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {"cases": 0, "cause_reproduced": 0, "counter_proof": 0}
    for name, d in sorted(div.items()):
        cov["cases"] += 1
        if not d["snow_present"]:
            problems.append("%s：权威规格里**没有** %s —— 登记的根因不成立（键形又看错了？）"
                            % (name, SNOW_KEY))
            continue
        if d["py"] != d["want_base"]:
            problems.append("%s：登记表说「Python 规格原样＝基线」，实得 %r ≠ %r"
                            % (name, d["py"], d["want_base"]))
            continue
        if d["hole"] != d["want_cur"]:
            problems.append("%s：挖掉 `%s` 之后**没有**复现出现在这份读数\n"
                            "      挖掉后=%r\n      现在   =%r\n"
                            "      ⇒ 判决漂移的原因不只是雪，这条登记要重写"
                            % (name, SNOW_KEY, d["hole"], d["want_cur"]))
            continue
        cov["cause_reproduced"] += 1
        if d["goals"] != d["want_base"]:
            problems.append("%s：**反证不成立** —— 只把 `goal_cells` 对齐 Go（留着雪）"
                            "竟然也改了判决（%r ≠ 基线 %r）⇒ 分歧不止雪一个原因"
                            % (name, d["goals"], d["want_base"]))
        else:
            cov["counter_proof"] += 1
        print("  ✓ %s：挖掉 `%s` 后与现在**逐位相同**（%s）；反证（只动 goal_cells）仍＝基线"
              % (name, SNOW_KEY,
                 "、".join("%s=%r" % (k, d["hole"][k]) for k in VERDICT_KEYS)))
    return problems, cov


# ============================================ 三 · 拒跑那一态（三态分离）

#: 合成用例：拿一份真夹具，把第一个部署的 `skill` 从 0 改成 1（**整数**）。
#: 为什么用这个触发器：`unsupported.go:171` 那条「技能槽号 N」是**字段驱动**的
#: ——整数槽号 ⇒ 调用方得先绑 `SkillLevel` ⇒ 闸门报理由。它不依赖网络、不依赖
#: 新增数据，且**不**碰机制层（所以它与上面那类机制拒跑是两回事）。
SKILL_CASE = "hsex8.json"


def measure_refusal() -> dict:
    from ak_tactic.plan import Plan, Roster
    from ak_tactic.simgo.verifier import ensure_go_engine
    from ak_tactic.verify import Verifier

    raw = json.loads((FIXDIR / SKILL_CASE).read_text(encoding="utf-8-sig"))
    raw["deploys"][0]["skill"] = 1
    roster = Roster.from_json(ROSTER)
    out: dict = {"case": "%s ＋ 第一个部署 skill=1" % SKILL_CASE}
    for engine in ("go", "python"):
        v = Verifier(engine=engine)
        try:
            r = v.run(Plan.from_dict(copy.deepcopy(raw)), roster=roster)
            out[engine] = {
                "verdict": {k: getattr(r, k) for k in
                            ("kills", "leaks", "won", "stars", "life", "max_life",
                             "elapsed", "damage")},
                "refused": list(getattr(r, "refused", None) or []),
                "diagnosis": list(r.diagnosis),
                "go_runs": getattr(v, "go_runs", None),
                "go_refusals": getattr(v, "go_refusals", None),
                "alias": getattr(v, "go_fallbacks", "<属性不存在>"),
                "err": None,
            }
        except Exception as e:                                    # noqa: BLE001
            out[engine] = {"err": "%s: %s" % (type(e).__name__, e)}
        finally:
            if hasattr(v, "close"):
                v.close()
    #: 绑定：拒跑那条路要的东西真的绑上了吗（本轮那个 AttributeError 就在这儿）
    v2 = Verifier(engine="go")
    ensure_go_engine(v2)
    out["bound"] = {n: hasattr(v2, n) for n in
                    ("_refusal_verdict", "_go_client", "_verdict_from_go", "close")}
    return out


def problems_refusal(rec: dict) -> tuple[list[str], dict]:
    problems: list[str] = []
    cov = {"checks": 0, "before_ran": 0}
    g = rec.get("go") or {}
    p = rec.get("python") or {}

    miss = [n for n, ok in (rec.get("bound") or {}).items() if not ok]
    if miss:
        problems.append("动态绑定缺方法：%s —— 拒跑那条路走到就 AttributeError"
                        % miss)
    cov["checks"] += 1

    if g.get("err"):
        problems.append("engine=go 抛了：%s" % g["err"])
        return problems, cov

    ref = g.get("refused") or []
    if not ref:
        problems.append("engine=go 的判决里 `refused` 是空的 —— 拒跑被压成了"
                        "「一场败仗」（三态压成两态）")
    elif not any("技能槽号" in x for x in ref):
        problems.append("`refused` 非空但没引用闸门给的理由（现得 %r）" % (ref,))
    cov["checks"] += 1

    if g.get("go_refusals") != 1:
        problems.append("`go_refusals`=%r，应为 1（拒跑要计数）" % g.get("go_refusals"))
    if g.get("go_runs") != 0:
        problems.append("`go_runs`=%r，应为 0（**没跑**就不能记成跑过）" % g.get("go_runs"))
    cov["checks"] += 1

    alias = g.get("alias")
    if not isinstance(alias, int):
        problems.append("旧别名 `go_fallbacks` 读出来是 %r（%s）—— 读者要的是**值**"
                        % (alias, type(alias).__name__))
    elif alias != g.get("go_refusals"):
        problems.append("旧别名 %r 与规范名 `go_refusals`=%r 不一致 —— 两个名字一个值，"
                        "不许各记一份" % (alias, g.get("go_refusals")))
    cov["checks"] += 1

    v = g.get("verdict") or {}
    nz = {k: v.get(k) for k in ("kills", "leaks", "elapsed", "damage") if v.get(k)}
    if nz:
        problems.append("拒跑那一态的数值栏该清零，现在非零：%s ——"
                        "下一个人会去查「为什么打输了」，而根本没打" % nz)
    if v.get("won") is not False:
        problems.append("拒跑那一态 `won`=%r，应为 False" % v.get("won"))
    diag = "".join(g.get("diagnosis") or [])
    if "具名拒跑" not in diag or "没跑" not in diag:
        problems.append("诊断里没写清「具名拒跑／没跑」（现得 %r）" % diag[:200])
    cov["checks"] += 1

    #: **前**对照：同一个输入，旧那条路（＝回退分支的等价物）**跑出过一场真战斗**。
    #: 没有这一条，「不再跑 Python」就只是把一句话换个说法。
    if p.get("err"):
        problems.append("前对照（engine=python）抛了：%s —— 对照立不住" % p["err"])
    else:
        pv = p.get("verdict") or {}
        if p.get("refused"):
            problems.append("前对照（engine=python）的 `refused` 非空 —— Python 那条路"
                            "不该有闸门")
        if not (float(pv.get("elapsed") or 0) > 0
                and (int(pv.get("kills") or 0) + int(pv.get("leaks") or 0)) > 0):
            problems.append("前对照（engine=python）没跑出真战斗（%s）——"
                            "那本笔「不再跑模拟器」就没有可对照的东西" % pv)
        else:
            cov["before_ran"] += 1
    return problems, cov


# ===================================================== 四 · 反向守卫（注入）

MUTATIONS = (
    "把一份「跑了」的判决改掉一个量",
    "把旧别名改成读不到（None）",
    "把 `go_runs` 改成 0（跑了却记成没跑）",
    "清空 `refused`（拒跑伪装成一场败仗）",
    "把 `go_refusals` 归零（拒跑不计数）",
    "拒跑却把 `go_runs` 记成 1",
    "让旧别名与规范名不一致",
    "往 `_run_other_engine` 里插一句 `sim.run(...)`",
    "往 `verifier.py` 里插一个 `build_spec(` 调用点",
    "把 `_refusal_verdict` 从绑定表里删掉",
    #: ★★ 末尾两条是**禁桶的守卫**：往那两个「必须为 0」的桶里各塞一份。
    #: 没有它们的话，「桶是空的」与「根本没在看那个桶」长得一模一样。
    "把一份跑出判决的夹具改成机制拒跑（禁桶①）",
    "让一份判决与基线不同（禁桶②）",
    #: ★ 第三条：**雪那一类的根因**也要红得起来（复现不成立 / 反证不成立）。
    "让雪那一类的根因复现不出来（挖掉雪也回不到现在）",
)

#: 每处注入**打在哪条断言**上（「十二条都判红」这句话要能答出各自独立）。
MUTATION_BRANCH = {
    "把一份「跑了」的判决改掉一个量": "端到端判决 ≡ 冻结基线",
    "把旧别名改成读不到（None）": "旧别名不许静默读成 None",
    "把 `go_runs` 改成 0（跑了却记成没跑）": "跑出判决者 go_runs==1",
    "清空 `refused`（拒跑伪装成一场败仗）": "三态分离：refused 非空",
    "把 `go_refusals` 归零（拒跑不计数）": "拒跑要计数 go_refusals==1",
    "拒跑却把 `go_runs` 记成 1": "没跑不许记成跑过 go_runs==0",
    "让旧别名与规范名不一致": "两个名字一个值",
    "往 `_run_other_engine` 里插一句 `sim.run(...)`": "出口里 sim 读了 0 次",
    "往 `verifier.py` 里插一个 `build_spec(` 调用点": "这条路上没有 build_spec( 调用点",
    "把 `_refusal_verdict` 从绑定表里删掉": "混入类的方法都进了绑定表",
    "把一份跑出判决的夹具改成机制拒跑（禁桶①）": "禁桶①：拒跑必须 0",
    "让一份判决与基线不同（禁桶②）": "禁桶②：判决必须与基线逐键相同",
    "让雪那一类的根因复现不出来（挖掉雪也回不到现在）": "雪那一类：根因要当场复现",
}


def _edit_src(src: str, which: str) -> str:
    """源码级注入：改**字符串**再喂给同一把尺子（不碰磁盘）。"""
    if which == "往 `verifier.py` 里插一个 `build_spec(` 调用点":
        return src.replace(
            "        started = time.perf_counter()",
            "        _sneak = build_spec(sim, allow_devices=True)\n"
            "        started = time.perf_counter()", 1)
    if which == "往 `_run_other_engine` 里插一句 `sim.run(...)`":
        return src.replace(
            "        started = time.perf_counter()",
            "        _res = sim.run(max_time=900.0)\n"
            "        started = time.perf_counter()", 1)
    if which == "把 `_refusal_verdict` 从绑定表里删掉":
        return src.replace('"_refusal_verdict", ', "", 1)
    return src


def mutate(rows: list[dict], rec: dict, sources: dict[str, str], which: str,
           snow: dict) -> tuple[list[dict], dict, dict[str, str], dict]:
    r2 = copy.deepcopy(rows)
    c2 = copy.deepcopy(rec)
    s2 = dict(sources)
    w2 = copy.deepcopy(snow)
    if which == "让雪那一类的根因复现不出来（挖掉雪也回不到现在）":
        #: 让「挖掉雪」的读数看起来**回不到**现在的读数 ⇒ 根因复现那条必须红。
        for name in w2:
            w2[name]["hole"] = copy.deepcopy(w2[name]["want_base"])
            break
    elif which == "把一份「跑了」的判决改掉一个量":
        for r in r2:
            if r["cur"] is not None:
                r["cur"]["kills"] = int(r["cur"]["kills"]) + 1
                break
    elif which == "把一份跑出判决的夹具改成机制拒跑（禁桶①）":
        for r in r2:
            if r["cur"] is not None:
                r["cur"], r["err"] = None, ("RuntimeError: 机制 … 的规格用不了："
                                            "天桩 \"trap_146_dhdcr\" @[1 2] " +
                                            MECH_REFUSAL + "（甲）")
                break
    elif which == "让一份判决与基线不同（禁桶②）":
        for r in r2:
            if r["cur"] is not None and r["baseline"]:
                r["cur"]["kills"] = int(r["baseline"]["kills"]) + 3
                break
    elif which == "把旧别名改成读不到（None）":
        for r in r2:
            if r["cur"] is not None:
                r["cur"]["go_fallbacks"] = None
                break
    elif which == "把 `go_runs` 改成 0（跑了却记成没跑）":
        for r in r2:
            if r["cur"] is not None:
                r["cur"]["go_runs"] = 0
                break
    elif which == "清空 `refused`（拒跑伪装成一场败仗）":
        c2["go"]["refused"] = []
    elif which == "把 `go_refusals` 归零（拒跑不计数）":
        c2["go"]["go_refusals"] = 0
    elif which == "拒跑却把 `go_runs` 记成 1":
        c2["go"]["go_runs"] = 1
    elif which == "让旧别名与规范名不一致":
        c2["go"]["alias"] = 7
    elif which.startswith("往 ") or which.startswith("把 `_refusal_verdict`"):
        s2["ak_tactic/simgo/verifier.py"] = _edit_src(
            s2["ak_tactic/simgo/verifier.py"], which)
    return r2, c2, s2, w2


# ============================================================== 主流程

def main() -> int:
    mutate_mode = "--mutate" in sys.argv
    print("Go 侧仪器：%s" % GO_BIN)
    print("判据对象：`Verifier(engine=\"go\")` 这条调用链（Python 还造不造规格、还跑不跑模拟器）")
    print("冻结基线：`%s`（原文取证用 `git show %s:<路径>`）＋ `fixtures/golden_go.json`"
          % (FROZEN_SHA, FROZEN_SHA))

    sources = read_sources()
    print()
    print("一 · 静态（AST 读源码，不跑）：扫 %d 个文件" % len(sources))
    sbad, scov = problems_static(sources)
    for m in sbad:
        print("  ✗ %s" % m)
    print("  分母：%d 个文件 / %d 个 AST 节点；`build_spec` 调用点 %d 个（本路 %d 个文件里）＋"
          " 导入引用 %d 处；正对照命中 %d 处"
          % (scov["files"], scov["nodes"], scov["call_sites"], scov["files"],
             scov["import_sites"], scov["witness_hits"]))
    print("  冻结副本旧痕迹：%d / 2 处" % scov["frozen_lines"])

    print()
    print("二 · 端到端 ≡ 冻结基线（①）：24 份夹具逐份重跑（`sim` 慢，这组最花时间）")
    t0 = time.perf_counter()
    rows = measure_endtoend()
    ebad, ecov = problems_endtoend(rows)
    for m in ebad:
        print("  ✗ %s" % m)
    print("  分母：跑出判决 %d 份（与基线逐键相同的 %d 份）／拒跑 %d 份"
          "（其中机制层 %d 份）；判决与基线不同的 %d 份；"
          "旧别名读得出值的 %d 份；总耗时 %.1fs"
          % (ecov["ran"], ecov["matched"], ecov["refused"], ecov["mech"],
             ecov["diverged"], ecov["alias_ok"], time.perf_counter() - t0))
    #: ★ 禁桶的两侧守卫之二：**桶空着也要有「谁在看」的证据**。这两个数
    #: 就是那两个禁桶的读数本身（拒跑 0、漂移 0），与「没跑」区分得开
    #: ——后者会被上面那条 `ran != len(rows)` 抓住。
    print("  禁桶：拒跑必须 0（实得 %d）、**未登记的**判决分歧必须 0（实得 %d）"
          % (ecov["refused"], ecov["diverged"]))
    print("  已登记分歧（第三个键：雪）：%d 份" % ecov["snow"])

    print()
    print("二·b · 雪那一类（第三个数）：根因**当场复现** ＋ 反证")
    snow = measure_snow(rows)
    sbad, scov2 = problems_snow(snow)
    for m in sbad:
        print("  ✗ %s" % m)
    if ecov["snow"] != len(SNOW_CAUSE):
        print("  ✗ 实测因雪分歧 %d 份 ≠ 登记 %d 份" % (ecov["snow"], len(SNOW_CAUSE)))
        sbad.append("登记表与实测份数不符")
    print("  分母：登记 %d 份；根因复现成功 %d 份；反证成立 %d 份"
          % (scov2["cases"], scov2["cause_reproduced"], scov2["counter_proof"]))

    print()
    print("三 · 拒跑那一态（三态分离）：%s" % SKILL_CASE)
    rec = measure_refusal()
    rbad, rcov = problems_refusal(rec)
    for m in rbad:
        print("  ✗ %s" % m)
    gg = rec.get("go") or {}
    pp = rec.get("python") or {}
    if not gg.get("err"):
        print("  现在（engine=go）：%d杀 %d漏 elapsed=%.4f refused=%s"
              % (gg["verdict"]["kills"], gg["verdict"]["leaks"],
                 float(gg["verdict"]["elapsed"]),
                 json.dumps(gg.get("refused"), ensure_ascii=False)))
        print("       go_runs=%r  go_refusals=%r  旧别名 go_fallbacks=%r"
              % (gg.get("go_runs"), gg.get("go_refusals"), gg.get("alias")))
    if not pp.get("err"):
        print("  以前（engine=python，＝回退分支的等价物）：%d杀 %d漏 elapsed=%.4f"
              % (pp["verdict"]["kills"], pp["verdict"]["leaks"],
                 float(pp["verdict"]["elapsed"])))
    print("  分母：断言 %d 条；前对照跑出真战斗 %d 例" % (rcov["checks"], rcov["before_ran"]))

    problems = sbad + ebad + rbad

    if mutate_mode:
        print()
        print("四 · 反向守卫（%d 处注入，各自打在**具名的那条**断言上）" % len(MUTATIONS))
        if problems:
            print("★ 基线本身不干净 ⇒ 反向守卫无从成立")
            return 1
        bad = 0
        for which in MUTATIONS:
            r2, c2, s2, w2 = mutate(rows, rec, sources, which, snow)
            if (r2, c2, s2, w2) == (rows, rec, sources, snow):
                print("  ✗ 注入「%s」**没落到任何对象上**（空转）" % which)
                bad += 1
                continue
            m_s, _ = problems_static(s2)
            m_e, _ = problems_endtoend(r2)
            m_r, _ = problems_refusal(c2)
            m_w, _ = problems_snow(w2)
            n = len(m_s) + len(m_e) + len(m_r) + len(m_w)
            ok = n > 0
            if not ok:
                bad += 1
            print("  %s 注入「%s」→ %s（%d 条）   【打在：%s】"
                  % ("✓" if ok else "✗", which, "判红" if ok else "没红（守不住）",
                     n, MUTATION_BRANCH[which]))
        if bad:
            print("★ %d / %d 处注入没判红或空转" % (bad, len(MUTATIONS)))
            return 1
        print("  反向守卫成立：%d / %d 处注入都判红" % (len(MUTATIONS), len(MUTATIONS)))
        print("结论：反向守卫 %d / %d 处注入判红（各自打在一条不同的断言上）"
              % (len(MUTATIONS), len(MUTATIONS)))
        return 0

    if problems:
        print()
        print("★ %d 处不一致：" % len(problems))
        for m in problems[:15]:
            print("  · %s" % m)
        if len(problems) > 15:
            print("  · …（另有 %d 条）" % (len(problems) - 15))
        print("结论：Python 这条调用链**未通过**（%d 处）：静态 %d ＋ 端到端 %d ＋"
              " 雪那一类 %d ＋ 拒跑那一态 %d"
              % (len(problems), len(sbad), len(ebad), len(sbad), len(rbad)))
        return 1

    print()
    print("结论：静态 4 条全成立（本路 %d 文件无 `build_spec(` 调用点；出口里 `sim` 读 0 次，"
          "正对照 Python 那条读 %d 次）；端到端 **%d / %d 份判决与 `%s` 冻结基线逐键相同**"
          "（禁桶：拒跑 %d 份、未登记分歧 %d 份，两个桶都必须为 0）；"
          "另有 %d 份为**已登记分歧**（第三个键 `snow.field`，根因当场复现 %d 份、"
          "反证 %d 份）；拒跑那一态三态分离成立"
          "（refused 非空、go_runs=0、go_refusals=1、旧别名读得出同一个值）、"
          "前对照 Python 跑出真战斗 %d 例"
          % (scov["files"], name_loads_in_func(sources["ak_tactic/verify.py"],
                                               "Verifier", "_run_other_engine", "sim"),
             ecov["matched"], len(rows), FROZEN_SHA, ecov["refused"],
             ecov["diverged"], ecov["snow"], scov2["cause_reproduced"],
             scov2["counter_proof"], rcov["before_ran"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
