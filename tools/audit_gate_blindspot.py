#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""闸门盲区审计：**只在跑起来之后才被写、却被闸门读到的** `sim` 字段（静态，不跑战斗）。

## 为什么是静态的

闸门（`spec.unsupported_reasons`）与 `build_spec` 都在 `sim.run()` **之前**执行。
凡是"部署那一刻才创建"的对象，它们读到的**永远是空** —— 闸门不报、规格里也没这项，
Go 静默跑出另一场战斗，而 `go_fallbacks == 0` 看起来"走了 Go"。

⚠ **不能靠"跑完之后再核一遍"来补**：`GoVerifier` 走 Go 那条路时**根本不跑 Python**
（`verifier.py:88-105`，只在退回原版时才 `sim.run`）。没有运行期状态可核。

所以只能**静态**问：`spec.py` 里读的那些 `sim.X`，`X` 是谁写的、什么时候写的？

## 三道筛子（每一道都对应一次真实的误报，别拆）

1. **早 vs 晚**：早＝构造期或排程期可达。名单**从 `verify.py` 自动推**
   （`sim.run(` 之前每一处 `sim.<方法>(` 都是根）——手抄的名单会在"验证器新增
   一次跑前排程"时悄悄过期。第一版把 `plan`/`retreat`/`use_skill` 写的四个字段
   全报成了盲区，就是栽在这里。
2. **绑定 vs 改写**：字段若在早期就被 `self.X = …` 绑定过，后面的改写不构成盲区
   （`stage` 是这么被误报的：它在 `__init__` 里绑好，`_pile_spec` 只是往它里面写）。
3. **代码 vs 字符串**：docstring 里的 `sim.X` 不是"读"（`mode_skill` 是这么被误报的）。

## 已登记项带**自动守卫**

有些"晚写 + 被读"眼下确实不是盲区，但**成立与否取决于别处的代码**。那样的条目
不能只写一句理由就完事——理由会过期而没人知道。所以登记表里可以带一个**守卫函数**，
每次审计都重算一遍：守卫不成立就翻红。例如 `device_deployments` 的安全前提是
"`plan_device` 在整包里没有调用者"，一旦有人接上它，这条立刻变成真盲区。

用法:
    python tools\\audit_gate_blindspot.py          # 审计，有未登记项则退出码 1
    python tools\\audit_gate_blindspot.py --all    # 连已登记的一起列出来
    python tools\\audit_gate_blindspot.py --selftest
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.stdout.reconfigure(encoding="utf-8")

SIM = ROOT / "ak_tactic" / "battle" / "sim.py"
VERIFY = ROOT / "ak_tactic" / "verify.py"
GATE_FILES = [ROOT / "ak_tactic" / "simgo" / "spec.py",
              ROOT / "ak_tactic" / "simgo" / "mech.py"]


def _docstring_lines(tree: ast.Module) -> set[int]:
    """**跨行字符串**占用的行号（含 docstring，也含 `Entry(...)` 那种长文本参数）。

    两版都错在这里，方向相反，值得记全：

    * 第一版收**所有**字符串常量的行 → `if getattr(sim, "snow_fields", None):`
      因为自己带一个短串被整行剔除。**假读没滤掉，真读反而被滤掉**，审计"全绿"
      ——那是最危险的输出。
    * 第二版只收 docstring → `activity.py:128` 那种"长文本参数的第二行"漏网，
      守卫被它骗了（那句在**解释** `plan_device`，不是在调它）。

    现在只收**跨行**的字符串：足够长、又不会误伤单行短串。判据是"这一行整行
    都属于某个字符串常量"，所以 `lineno != end_lineno` 才算。
    """
    lines: set[int] = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Constant) and isinstance(node.value, str)
                and node.end_lineno and node.end_lineno > node.lineno):
            lines.update(range(node.lineno, node.end_lineno + 1))
    return lines


def _no_caller(method: str) -> tuple[bool, str]:
    """守卫：`sim.<method>(` 在整个包里除了定义处没有别的调用者。

    成立 ⇒ 那个列表在闸门执行时**不可能**非空，这条判据是**死判据**（不是盲区，
    因为眼下没有生产者）；一旦有人接上，守卫不成立 ⇒ 立刻按真盲区报出来。

    ⚠ **必须跳过字符串**：`activity.py:128` 是一句 docstring 里的
    「`BattleSimulator.plan_device()` 排一条 `DeviceDeployment`…」，它是在**解释**
    这个入口，不是调用。第一版守卫被它骗了，把 `device_deployments` 报成"已被调用"
    —— 与上一版把 docstring 当成读是同一个坑，两处都得跳过字符串。
    """
    hits = []
    for f in (ROOT / "ak_tactic").rglob("*.py"):
        if f == SIM:
            continue
        text = f.read_text(encoding="utf-8")
        rows = _docstring_lines(ast.parse(text))
        for i, line in enumerate(text.splitlines(), 1):
            if i in rows:
                continue
            if f".{method}(" in line.split("#", 1)[0]:
                hits.append(f"{f.name}:{i}")
    if hits:
        return False, f"已被调用：{', '.join(hits[:3])} —— 闸门读到的可能是开局态"
    return True, f"`{method}` 在整个包里没有调用者（死判据，眼下没有生产者）"


#: 已登记的"晚写 + 被读"字段。`guard` 可选：每次审计重算，不成立就翻红。
KNOWN: dict[str, dict] = {
    "snow_fields": {
        "why": "已改判据：`snow_spec` 从 `sim.deployments` 取数（`d.talents`），"
               "闸门与送数同一个来源；`unsupported_reasons` 里那句 "
               "`if sim.snow_fields` 已是死代码，留着只为提醒",
    },
    "team_auras": {
        "why": "已改判据：全场光环随**干员规格**送（`_team_auras_of`），"
               "闸门里那句同样是死代码",
    },
    "farmland": {
        "why": "田地对象在 `Sim.__init__` 里就建；后续的赋值是**改其内容**"
               "（污染值/断田），不是「这个对象此刻还不存在」",
    },
    "_devices": {
        "why": "装置在关卡装载时就在（`stage.devices`），由对拍台的 "
               "`allow_devices` 口子显式管控，不是盲区",
    },
    "total_attack": {
        "why": "关卡级装置，装载时就在；未移植时**总是**报（不依赖运行期）",
    },
    "stage": {
        "why": "`self.stage` 在 `__init__` 里绑成一个**真实对象**（不是空表），"
               "后面的写在往它里面记缓存（`_pile_spec` 等）——闸门读 "
               "`sim.stage.map` 随时可用",
    },
    "cost": {
        "why": "闸门读 `sim.cost` 要的就是**开局费用**（`build_spec` 把它当初始"
               "部署点数送过去）。它在帧循环里被改写是原版语义，不是"
               "「这个对象此刻还不存在」那一类。",
    },
    "device_deployments": {
        "why": "闸门那条判据是**死判据**：它的唯一生产者 `plan_device` 没人调",
        "guard": lambda: _no_caller("plan_device"),
    },
    "summon_deployments": {
        "why": "同上：唯一生产者 `plan_summon` 没人调",
        "guard": lambda: _no_caller("plan_summon"),
    },
}


def _sim_ast() -> ast.Module:
    return ast.parse(SIM.read_text(encoding="utf-8"))


def _writes_in_sim() -> dict[str, set[tuple[str, int, str]]]:
    """字段 → {(方法名, 行号, 'bind'|'mutate')}。

    ⚠ 带行号不是装饰：审计报出来的每一条都要能**点回原文**去判真假。
    只有方法名的话，"`stage` 被 `_pile_spec` 写"这种说法根本没法核。
    """
    out: dict[str, set[tuple[str, int, str]]] = {}
    for node in ast.walk(_sim_ast()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            name, kind = None, "mutate"
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                base = sub.func.value
                if (isinstance(base, ast.Attribute)
                        and isinstance(base.value, ast.Name)
                        and base.value.id == "self"):
                    name = base.attr
            elif isinstance(sub, (ast.Assign, ast.AnnAssign)):
                targets = sub.targets if isinstance(sub, ast.Assign) else [sub.target]
                for t in targets:
                    if (isinstance(t, ast.Attribute)
                            and isinstance(t.value, ast.Name)
                            and t.value.id == "self"):
                        name, kind = t.attr, "bind"     #: self.X = …  ← 绑定
                    elif isinstance(t, ast.Subscript):
                        v = t.value
                        while isinstance(v, ast.Attribute):
                            if isinstance(v.value, ast.Name) and v.value.id == "self":
                                name = v.attr
                                break
                            v = v.value
            if name:
                out.setdefault(name, set()).add((node.name, sub.lineno, kind))
    return out


def _string_lines() -> set[int]:
    """`sim.py` 里**字符串字面量**占用的行号（含 docstring）。

    读代码要跳过它们：`spec.py` 的 docstring 里写 `sim.mode_skill` 是在**解释**
    某件事，不是在读那个字段。把它算成读，就会造出假盲区。
    """
    lines: set[int] = set()
    for node in ast.walk(_sim_ast()):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            lines.update(range(node.lineno, (node.end_lineno or node.lineno) + 1))
    return lines


def _early_methods() -> set[str]:
    """构造期 + **排程期**可达的方法名集合（根名单从 `verify.py` 自动推）。"""
    text = VERIFY.read_text(encoding="utf-8")
    cut = text.find("sim.run(")
    roots = {"__init__"} | set(re.findall(r"\bsim\.(\w+)\s*\(",
                                         text[:cut] if cut >= 0 else text))
    calls: dict[str, set[str]] = {}
    for node in ast.walk(_sim_ast()):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for sub in ast.walk(node):
            if not isinstance(sub, ast.Call):
                continue
            f = sub.func
            if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) \
                    and f.value.id == "self":
                calls.setdefault(node.name, set()).add(f.attr)
            elif isinstance(f, ast.Name):
                calls.setdefault(node.name, set()).add(f.id)
    seen, stack = set(), list(roots)
    while stack:
        m = stack.pop()
        if m in seen:
            continue
        seen.add(m)
        stack.extend(calls.get(m, ()))
    return seen


def _reads_in_gate() -> dict[str, set[str]]:
    """闸门文件里**代码行**上的读：字段 → 文件名集合。

    ⚠ **`sch` 也算接收者**（`frontend/schedule.py` 的 `Schedule`）。
    排程那五张表在迁移期由 `verify.py` **同时**写进 `sim` 与 `sch`，
    `build_spec` 改读后者——如果审计只认 `sim.`，那五项的盲区就**看不见了**：
    登记项既不报"未登记"也不报"守卫失效"，只是**从表里消失**，
    看上去像"盲区治好了"。实测发生过：`summon_deployments` 就这么掉过一次。

    ⇒ 盲区的定义是"早期有、内容是空、晚点才填"，**与它挂在哪个对象上无关**。
    """
    out: dict[str, set[str]] = {}
    pats = (re.compile(r"\b(?:sim|sch)\.(\w+)"),
            re.compile(r"getattr\(\s*(?:sim|sch)\s*,\s*[\"'](\w+)[\"']"))
    strlines: dict[Path, set[int]] = {}
    for f in GATE_FILES:
        text = f.read_text(encoding="utf-8")
        rows = _docstring_lines(ast.parse(text))
        strlines[f] = rows
        for i, line in enumerate(text.splitlines(), 1):
            if i in rows:
                continue
            code = line.split("#", 1)[0]
            for pat in pats:
                for m in pat.finditer(code):
                    out.setdefault(m.group(1), set()).add(f.name)
    return out


def audit() -> tuple[list, list, list]:
    """返回 (未登记, 已登记但守卫不成立, 已登记且成立)。"""
    writes, reads, early = _writes_in_sim(), _reads_in_gate(), _early_methods()
    bad, broken, ok = [], [], []
    for field in sorted(reads):
        sites = writes.get(field)
        if not sites:
            continue                       #: 不在 sim.py 里写（可能是 stage 上的）
        #: ⚠ **不能**用"早期绑定过就算安全"当捷径：`self.snow_fields = []` 也是
        #: 早期绑定，可那个空表在闸门那一刻**恰恰就是空的** —— 盲区的定义正是
        #: "早期有、内容是空、晚点才填"。所以判据只能是"有没有**晚于闸门**的改写"。
        late = sorted((m, ln) for m, ln, _k in sites if m not in early)
        if not late:
            continue
        row = (field, ", ".join(f"{m}:{ln}" for m, ln in late),
               ", ".join(sorted(reads[field])))
        if field not in KNOWN:
            bad.append(row)
        elif "guard" in KNOWN[field]:
            good, detail = KNOWN[field]["guard"]()
            (ok if good else broken).append(row + (detail,))
        else:
            ok.append(row + ("",))
    return bad, broken, ok


def main() -> int:
    args = sys.argv[1:]
    if "--selftest" in args:
        #: 反向守卫：伪造一条**没登记**的晚写+被读字段，看它是否真会被报出来。
        #: 不做这一步，"这张表永远全绿"也可能是审计本身坏了。
        fake = "gate_audit_selftest_field"
        writes, reads = _writes_in_sim(), _reads_in_gate()
        writes[fake] = {("_do_deploy", 1, "mutate")}
        reads[fake] = {"spec.py"}
        early = _early_methods()
        caught = bool([m for m, _l, _k in writes[fake] if m not in early]) \
            and fake not in KNOWN
        print(f"自检：伪造一条晚写+被读的字段 → {'✅ 会被报出' if caught else '❌ 没报出来'}")
        return 0 if caught else 1

    bad, broken, ok = audit()
    if "--debug" in args:
        early = _early_methods()
        text = VERIFY.read_text(encoding="utf-8")
        cut = text.find("sim.run(")
        roots = sorted(set(re.findall(r"\bsim\.(\w+)\s*\(",
                                      text[:cut] if cut >= 0 else text)))
        print(f"[debug] 跑前根（取自 verify.py）：{roots}")
        for probe in ("_do_deploy", "run", "_pile_spec", "plan", "use_skill",
                      "_enemy_stats", "_do_deploy_device"):
            print(f"[debug] {probe:20s} 算作{'早' if probe in early else '晚'}")
    print(f"闸门盲区审计：{SIM.relative_to(ROOT)}")
    print(f"  扫的闸门文件：{', '.join(f.name for f in GATE_FILES)}")
    print(f"  已登记且守卫成立：{len(ok)} 条；**未登记：{len(bad)}**；"
          f"**守卫失效：{len(broken)}**")
    if "--all" in args:
        for f, w, _r, detail in ok:
            print(f"    · {f:18s} 晚写于 {w}")
            print(f"      └ {KNOWN[f]['why']}")
            if detail:
                print(f"      └ 守卫：{detail}")
    for f, w, r, detail in broken:
        print(f"    ⛔ {f:18s} 守卫失效 —— {detail}")
    for f, w, r in bad:
        print(f"    ⛔ {f:18s} 只在 {w} 里写，却被 {r} 读到"
              f" —— 闸门取的是开局态，读到的可能**永远是空**")
    if not bad and not broken:
        print("  ✅ 没有未登记的盲区")
    return 1 if (bad or broken) else 0


if __name__ == "__main__":
    raise SystemExit(main())
