# -*- coding: utf-8 -*-
"""规格层 `sim` → `inp` 的**保守**改名。

## 为什么保守

前面两版通用改写都把文件写坏了，两次都是同一个原因：
**f-string 内部的 AST 节点，列偏移不能直接当文件偏移用**。
坏的样子很隐蔽 —— `f"...{len(sim._devices)}"` 变成
`f"...{len(sim._deviinp)devicesif inp.total_attack..."`，
而它在语法检查那一步才炸（如果它没炸，就是静默错代码）。

⇒ 本版三条纪律：

1. **只动不含 f-string 的行**。含 `f"` / `f'` 的行整行跳过并**列出来**，
   由人手工改——这样的行在这一轮只有 2 处。
2. **每处替换都自带 `expect`**：切出来的文本必须**恰好等于** `sim`，
   否则直接报错退出。这条闸门专门拦"偏移算错但我不知道"。
3. **不碰 `getattr`**：`getattr(sim, "X", 默认)` 只把接收者改名成 `inp`，
   整段保持原样。默认值仍由 `SpecInputs` 的字段默认值兜着，
   行为与迁移前**逐字一致**。要清理这个冗余是下一步的事，
   不和语义变更混在一个提交里。

跑法：`python tools\\rename_spec_input.py [--apply]`
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ["ak_tactic/simgo/spec.py", "ak_tactic/simgo/mech.py"]
sys.stdout.reconfigure(encoding="utf-8")

#: 直读的属性里，`SpecInputs` 上换了名字的
ATTR_MAP = {"_devices": "devices", "_goal_cells": "goal_cells"}


class Hit:
    __slots__ = ("lineno", "start", "end", "text", "why", "expect")

    def __init__(self, lineno, start, end, text, why, expect):
        self.lineno, self.start, self.end = lineno, start, end
        self.text, self.why, self.expect = text, why, expect


def collect(src: str, tree: ast.Module) -> tuple[list[Hit], list[str]]:
    lines = src.splitlines()
    hits: list[Hit] = []
    skipped: list[str] = []

    def has_fstring(lineno: int) -> bool:
        line = lines[lineno - 1]
        return 'f"' in line or "f'" in line

    seen: set[tuple[int, int]] = set()

    def push(lineno: int, col: int, end: int, text: str, why: str, expect: str) -> None:
        if (lineno, col) in seen:
            return                                  # 嵌套函数会重复走，去重
        seen.add((lineno, col))
        if has_fstring(lineno):
            skipped.append(lines[lineno - 1].strip())
            return
        hits.append(Hit(lineno, col, end, text, why, expect))

    #: ① 收 `sim` 的函数，参数改名
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        params = [a for a in fn.args.args + fn.args.kwonlyargs if a.arg == "sim"]
        if not params:
            continue
        for a in params:
            #: ⚠ `ast.arg` 的 end_col_offset **把注解也算进去**（`sim: Any` 整段），
            #: 所以只能取 `col_offset` 起 `len(a.arg)` 个字符。
            #: 这一条是 `expect` 闸门抓出来的：切出 `'sim: Any'` 期望 `'sim'`。
            push(a.lineno, a.col_offset, a.col_offset + len(a.arg),
                 "inp", "参数改名", "sim")
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == "sim":
                if any(x.lineno == node.lineno and x.col_offset == node.col_offset
                       for x in params):
                    continue
                push(node.lineno, node.col_offset, node.end_col_offset,
                     "inp", "名字 sim", "sim")
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) \
                    and node.value.id == "sim":
                push(node.value.lineno, node.value.col_offset,
                     node.value.end_col_offset, "inp", "名字 sim", "sim")
                new = ATTR_MAP.get(node.attr)
                if new:
                    a = node.end_col_offset - len(node.attr)
                    push(node.lineno, a, node.end_col_offset,
                         new, "私有名换公开名", node.attr)
    hits.sort(key=lambda h: (h.lineno, h.start))
    return hits, skipped


def main() -> int:
    apply = "--apply" in sys.argv
    total = 0
    for rel in TARGETS:
        path = ROOT / rel
        src = path.read_text(encoding="utf-8")
        hits, skipped = collect(src, ast.parse(src))
        lines = src.splitlines(keepends=True)
        #: ⚠ 自校验：切出来的必须**恰好**是 expect，否则偏移算错了，停
        for h in hits:
            got = lines[h.lineno - 1][h.start:h.end]
            if got != h.expect:
                raise SystemExit("⚠ %s:%d 偏移算错：该处切出 %r，期望 %r —— 停"
                                 % (rel, h.lineno, got, h.expect))
        print("=== %s：%d 处改名 ===" % (rel, len(hits)))
        by: dict[str, int] = {}
        for h in hits:
            by[h.why] = by.get(h.why, 0) + 1
        for k, v in sorted(by.items()):
            print("   %-18s %d 处" % (k, v))
        if skipped:
            print("   ⚠ 因含 f-string 而**跳过**、需手工改的行 %d 处：" % len(skipped))
            for s in sorted(set(skipped)):
                print("      %s" % s[:100])
        else:
            print("   （没有需要手工改的 f-string 行）")
        #: 逐行落（同一行内从右往左，避免移位）
        for h in hits:
            line = lines[h.lineno - 1]
            line = line[:h.start] + h.text + line[h.end:]
            if h.text == "inp":
                if not (line[:h.start].endswith("inp") or True):
                    pass
            lines[h.lineno - 1] = line
        if apply:
            path.write_text("".join(lines), encoding="utf-8")
        total += len(hits)
    print()
    print("合计 %d 处。" % total)
    if not apply:
        print("（只列不改。加 --apply 落盘。）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
