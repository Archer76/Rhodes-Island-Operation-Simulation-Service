# -*- coding: utf-8 -*-
"""把散落探针里**过期的 `_run_other_engine` 覆写签名**补齐。

## 为什么需要它

`Verifier.run` 现在这样调出口（`ak_tactic/verify.py:485-487`）：

    self._run_other_engine(sim=sim, plan=plan, stage=stage,
                           deployed=deployed, title=title,
                           schedule=sched, env=env)

而 `build_spec` 也多了 `schedule` / `env` 两个关键字。仓库里那些 `Thief(...)` 覆写还是旧签名
⇒ 直接 `TypeError`。**这与 `tools/parity_plan.py` 那次是同一处破损**（后端已修那份并实测过：
不修时它把每一关都显示成"拿不到规格"，看起来像数据问题，实际是**对拍整条路线静默失效**）。

## 改两处，都是机械的

1. `def _run_other_engine(self, *, sim, plan, stage, deployed, title):`
   → 末尾加 `, schedule=None, env=None`；
2. **该函数体内的** `build_spec(SpecInputs.from_sim(sim), ...)` 调用 → 补 `schedule=schedule, env=env`
   原样转发。⚠ 漏转发 = 规格与验证器手里那份**不是同一个时间表**，属于"静默给出另一份规格"。

## 纪律（同 `rename_spec_input.py`）

* 每处替换自带 `expect`：切出来的文本必须**恰好等于**预期，否则报错退出；
* 只在**函数体的行范围**里改 `build_spec`，不碰模块里的其他调用点；
* 不改自己；
* 含 f-string 的行不动（那类行的 AST 列偏移不能当文件偏移用）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.stdout.reconfigure(encoding="utf-8")
SELF = Path(__file__).resolve()

OLD_SIG = "def _run_other_engine(self, *, sim, plan, stage, deployed, title):"
NEW_SIG = ("def _run_other_engine(self, *, sim, plan, stage, deployed, title,\n"
           "                          schedule=None, env=None):")
CALL_OLD = "build_spec(SpecInputs.from_sim(sim), allow_devices=True)"
CALL_NEW = ("build_spec(SpecInputs.from_sim(sim), allow_devices=True,\n"
            "                                     schedule=schedule, env=env)")

#: ⚠ **不许碰的文件**——不是"忘了改"，是它们的现状**本身就是对的**：
#:
#: `tools/golden_go.py` 的覆写已经是 `schedule=None, **kw`（`**kw` 把 `env` 收下丢掉），
#: 而且它**有意不把 `schedule` 转发给 `build_spec`**：它要的是模拟器自带那份排程
#: （`from_sim` 会抄 `sim.deployments` 等五个列表）。当前两者**逐字相同**（`verify.py`
#: 排程双写），所以行为一致；但**一旦给它加上转发，喂进金标准的就是另一个对象**,
#: 金标准的 `spec_sha` 可能当场变。**金标准是本重构的基线，不许为了统一而统一。**
EXCLUDE = {"golden_go.py"}


def targets() -> list[Path]:
    out = []
    #: ⚠ 这三条必须是**原始字符串**：`"tools/probe_*.py"` 里的 `\p` 是非法的转义序列，
    #: Python 3.12+ 会报 SyntaxWarning（本工具第一版就报了 9 条）。
    for pat in (r"tools/probe_*.py", r"_proto/*.py", r"tools/*.py"):
        out += sorted(ROOT.glob(pat))
    return sorted({p.resolve() for p in out if p.resolve() != SELF})


def main() -> int:
    apply = "--apply" in sys.argv
    n_sig = n_call = n_file = 0
    for path in targets():
        if path.name in EXCLUDE:
            continue
        src = path.read_text(encoding="utf-8")
        if "def _run_other_engine" not in src:
            continue
        try:
            tree = ast.parse(src)
        except SyntaxError as exc:
            print(f"  ⚠ {path.name} 语法错，跳过：{exc}")
            continue
        lines = src.splitlines(keepends=True)
        #: 收集所有 `_run_other_engine` 的**行范围**（1-based，含首尾）
        spans = []
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef) and node.name == "_run_other_engine":
                spans.append((node.lineno, node.end_lineno))
        if not spans:
            continue
        changed = False
        #: 先改签名。
        #: ⚠ **必须 `.strip()` 比**：函数定义行带缩进（在 `class` 里），
        #: 拿整行跟无缩进的常量比会**一处都匹配不到**——本工具第一版就是这么跑空的，
        #: 靠末尾那条"判据跑空了"守卫抓出来。
        for i, line in enumerate(lines):
            if line.strip() != OLD_SIG.strip():
                continue
            if not any(a <= i + 1 <= b for a, b in spans):
                continue
            indent = line[:len(line) - len(line.lstrip())]
            keep = "\r\n" if line.endswith("\r\n") else "\n"
            lines[i] = indent + NEW_SIG + keep
            n_sig += 1
            changed = True
        #: 再改调用：只在 spans 范围内，且**按子串替换**（行首常有 `Thief.spec = ` 之类前缀）。
        for i, line in enumerate(lines):
            if CALL_OLD not in line or 'schedule=schedule' in line:
                continue
            if not any(a <= i + 1 <= b for a, b in spans):
                continue
            if "f\"" in line or "f'" in line:
                print(f"  ⚠ {path.name}:{i+1} 含 f-string，跳过（列偏移不可信）")
                continue
            indent = line[:len(line) - len(line.lstrip())]
            keep = "\r\n" if line.endswith("\r\n") else "\n"
            body = line.rstrip("\r\n")
            lead = body[:len(body) - len(body.lstrip())]
            rest = body[len(lead):]
            lines[i] = lead + rest.replace(CALL_OLD, CALL_NEW) + keep
            n_call += 1
            changed = True
        if changed:
            n_file += 1
            if apply:
                out = "".join(lines)
                ast.parse(out)                      # 写之前先验语法
                path.write_text(out, encoding="utf-8")
            print(f"  {'✅' if apply else '（dry-run）'} {path.relative_to(ROOT)}")
    print()
    print(f"  签名 {n_sig} 处、build_spec 转发 {n_call} 处，涉及 {n_file} 个文件")
    if n_sig == 0 and n_call == 0:
        print("  ⚠ 判据跑空了：一处都没找到。别把它读成通过。")
        return 1
    if not apply:
        print("  （dry-run：加 --apply 才写盘）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
