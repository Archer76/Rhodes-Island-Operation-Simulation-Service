# -*- coding: utf-8 -*-
"""`prts.grid` 的自检：钉住「站位格的两套画法」与回退路径的边界。

跑法：`python tools/check_prts_grid.py`

**全部是合成 SVG，不联网、不读 `data/`。** 秒级可跑。

这里的断言分别对应 2026-09-20 真踩过的事：

1. **站位格有两套画法**。`prts.wiki` 的 73 个 `Widget:Range/<代号>` 里，
   63 个把站位格画成 `<use xlink:href="#1">`（画法 A），**9 个**（`1-5` `2-7`
   `3-16` `4-3` `4-4` `4-5` `4-6` `4-7` `4-13`）**压根没有 `#1`**，
   站位格被**内联画成蓝色 `<path fill="#27a6f3">`**（画法 B）。
   旧解析器只认 A ⇒ 这 9 个永远报「实得 0 个站位格」，**并被误读成"prts 上没有"**。
   ★ **判据是颜色，不是序号 `#1`。**

2. **`<use>` 的属性之间可以没有空格**。`4-13` 原文有
   `<use xlink:href="#2"x="28"y="54"id="use10" />`，旧正则要求 `\\s+`
   ⇒ 该页**漏掉 5 个覆盖格**。
   ★ **它与第 1 条会耦合**：只修画法那一半，`4-13` 就从**"响亮的失败"**变成
   **"成功的静默少 5 格"**。所以本文件把两者**钉在一起**。

3. ★★ **回退路径必须有界**。放宽一条判据（从只认 `#1` 到也认蓝 path）时，
   必须同时写下**它从今往后不能再接受什么**——否则修完就变成
   **"什么都当站位格"**，那是**把一个漏判换成一批误判**。
   ⇒ 「有 `<use>` 但既无 `#1`、又无蓝色 path」**仍须抛错**。

4. **回退路径命中要留痕**（`self_source`）。否则将来蓝 path 回退在某页上
   **误命中**时，**查不出是哪一类**。
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ak_tactic.prts.grid import (SRC_PATH, SRC_USE, AttackRange,  # noqa: E402
                                 RangeParseError, parse_svg)

FAILED = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global FAILED
    if ok:
        print(f"  ✓ {label}" + (f"  {detail}" if detail else ""))
    else:
        FAILED += 1
        print(f"  ✗ {label}  {detail}")


# ------------------------------------------------------------------ 合成样本

#: 画法 A：`<defs>` 定义 `#1`（蓝）与 `#2`（灰），站位格用 `<use href="#1">` 摆位。
SVG_A = (
    '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<defs id="defs1">'
    '<rect id="1" fill="#27a6f3" stroke="transparent" width="22" height="22"/>'
    '<rect id="2" fill="none" stroke="gray" width="20" height="20"/>'
    "</defs>"
    '<use xlink:href="#2" x="2" y="2"/>'
    '<use xlink:href="#1" x="1" y="27"/>'
    '<use xlink:href="#2" x="28" y="28"/>'
    "</svg>"
)

#: 画法 B：`<defs>` **只有 `#2`**，站位格是内联蓝 path + `translate`。
#: 数值抄自真实的 `4-3`（`translate(-1,51)`）。
SVG_B = (
    '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<defs id="defs1"><rect id="2" fill="none" stroke="gray" width="20" height="20"/></defs>'
    '<use xlink:href="#2" x="54" y="2"/>'
    '<use xlink:href="#2" x="80" y="2"/>'
    '<path d="M 2,2 V 24 H 24 V 2 Z" style="fill:#27a6f3;stroke-width:2"'
    ' transform="translate(-1,51)"/>'
    "</svg>"
)

#: 抄自 `4-13` 原文的**无空格**属性写法。
SVG_TIGHT = (
    '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<use xlink:href="#1" x="1" y="1"/>'
    '<use xlink:href="#2"x="28"y="2"/>'
    '<use xlink:href="#2"x="54"y="2"/>'
    "</svg>"
)

#: 有 `<use>`，但既无 `#1`、也无蓝色 path。
SVG_NO_SELF = (
    '<svg xmlns:xlink="http://www.w3.org/1999/xlink">'
    '<use xlink:href="#2" x="28" y="2"/></svg>'
)

#: 连 `<use>` 都没有。
SVG_NO_USE = "<svg><rect id='9'/></svg>"


def _err(svg: str) -> str:
    try:
        parse_svg("__t__", svg)
    except RangeParseError as e:
        return str(e)
    return ""


# ------------------------------------------------------------ 1 · 两套画法

def section_two_conventions() -> None:
    print("[1] 站位格的两套画法都要认")

    a = parse_svg("A", SVG_A)
    check("画法 A（`#1` 的 use）解析成功", True, f"self={a.self_cell} size={a.size}")
    check("画法 A 的来源记为 use#1", a.self_source == SRC_USE, a.self_source)
    check("画法 A 的站位格与覆盖格正确",
          a.self_cell == (0, 1) and a.cells == frozenset({(0, -1), (1, 0)}),
          f"self={a.self_cell} cells={sorted(a.cells)}")

    b = parse_svg("B", SVG_B)
    check("★ 画法 B（内联蓝 path、`#1` 不存在）解析成功",
          True, f"self={b.self_cell} size={b.size}")
    check("★ 画法 B 的来源记为 path（回退痕迹）",
          b.self_source == SRC_PATH, b.self_source)
    check("★ 画法 B 的 is_fallback 为真", b.is_fallback)
    check("画法 B 的站位格算对（translate + d 的起点）",
          b.self_cell == (0, 2), f"self={b.self_cell}")
    check("画法 B 的覆盖格算对",
          b.cells == frozenset({(2, -2), (3, -2)}), f"cells={sorted(b.cells)}")

    # 两套用的是同一套格坐标：translate 的 y 取 24.728024 与 25 必须落同一格
    def _y(ty: str) -> int:
        svg = ('<svg><use xlink:href="#2" x="2" y="2"/>'
               f'<path d="M 2,2 V 24 H 24 V 2 Z" style="fill:#27a6f3"'
               f' transform="translate(-1,{ty})"/></svg>')
        return parse_svg("J", svg).self_cell[1]

    check("★ 浮点抖动（24.728024 与 25）吸附到同一格",
          _y("24.728024") == _y("25"), f"{_y('24.728024')} vs {_y('25')}")

    # 局部起点必须从 `d` 读，不能写死 2,2
    odd = ('<svg><use xlink:href="#2" x="2" y="2"/>'
           '<path d="M 5,7 V 24 H 24 V 2 Z" style="fill:#27a6f3"'
           ' transform="translate(20,20)"/></svg>')
    check("回退路径从 `d` 的起点算（不写死 2,2）",
          parse_svg("O", odd).self_cell == (1, 1),
          f"self={parse_svg('O', odd).self_cell}")

    # 画法 A 优先
    both = SVG_B.replace('<defs id="defs1">',
                         '<defs id="defs1"><rect id="1" fill="#27a6f3"/>') \
                .replace('<use xlink:href="#2" x="54" y="2"/>',
                         '<use xlink:href="#2" x="54" y="2"/>'
                         '<use xlink:href="#1" x="1" y="1"/>')
    check("两套同时在场时以画法 A 为准",
          parse_svg("AB", both).self_source == SRC_USE,
          parse_svg("AB", both).self_source)


# --------------------------------------------------- 2 · 属性之间可以没空格

def section_tight_attributes() -> None:
    print("[2] `<use>` 的属性之间可以没有空格（`4-13` 的回归）")
    r = parse_svg("T", SVG_TIGHT)
    check("★ 无空格的 `<use>` 必须被抓到（2 个覆盖格，不是 0）",
          r.size == 2, f"size={r.size}")
    check("无空格写法下站位格也对", r.self_cell == (0, 0), f"self={r.self_cell}")
    check("同时也认不带 `xlink:` 前缀的 `href`",
          parse_svg("H", SVG_TIGHT.replace("xlink:href", "href")).size == 2)


# ------------------------------------------------------ 3 · 回退路径的边界

def section_fallback_bound() -> None:
    print("[3] ★ 回退路径必须有界（不许退化成「什么都当站位格」）")
    msg = _err(SVG_NO_SELF)
    check("★ 有 `<use>` 但既无 `#1`、又无蓝 path ⇒ **必须抛错**", bool(msg), msg)
    msg2 = _err(SVG_NO_USE)
    check("连 `<use>` 都没有 ⇒ 仍须抛错", bool(msg2), msg2)
    check("两条错误的说法不同（不是同一条兜底）", msg != msg2 and bool(msg) and bool(msg2))
    # 蓝 path 在但**颜色不对**（灰 path）⇒ 仍须抛错：判据是颜色
    grey = ('<svg><use xlink:href="#2" x="2" y="2"/>'
            '<path d="M 2,2 V 24 H 24 V 2 Z" style="fill:#cccccc"'
            ' transform="translate(-1,-1)"/></svg>')
    check("★ 颜色不对的 `<path>` **不算**站位格（判据是颜色不是标签）",
          bool(_err(grey)), _err(grey) or "（没抛错）")


# --------------------------------------------------------- 4 · 留痕与不变量

def section_trace() -> None:
    print("[4] 回退痕迹必须留得住")
    b = parse_svg("B", SVG_B)
    check("`to_dict()` 带 `self_source`", b.to_dict().get("self_source") == SRC_PATH,
          str(b.to_dict().get("self_source")))
    check("`rotated()` 保留 `self_source`",
          b.rotated(1).self_source == SRC_PATH, b.rotated(1).self_source)
    check("`rotated()` 四次回到原状", b.rotated(4) == b)
    fresh = AttackRange("X", 1, 1, (0, 0))
    check("★ 旧构造（不带 self_source）不炸，且来源是 unknown 三态之一",
          fresh.self_source == "unknown", fresh.self_source)
    check("★ `unknown` **不许**被读成「回退取到的」（两种空不能压成一个值）",
          fresh.is_fallback is False, f"is_fallback={fresh.is_fallback}")


def main() -> int:
    print("prts.grid 自检（站位格两套画法 + 回退边界）\n")
    section_two_conventions()
    print()
    section_tight_attributes()
    print()
    section_fallback_bound()
    print()
    section_trace()
    print()
    if FAILED:
        print(f"失败 {FAILED} 项。")
        return 1
    print("全部通过。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
