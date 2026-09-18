"""TUI 的视觉层：一套 CSS 与几个常量。

配色照 Ave Mujica 的世界观走——月光、夜幕、人偶的银。**不引第三方主题包**，
Textual 自带的 design token 变量在这个文件里统一覆盖一遍，屏幕里不再出现裸色值。
"""

from __future__ import annotations

#: 应用标题（栏头与窗口标题都用它）
APP_TITLE = "R.I.O.S. 罗德岛作战演算服务"
APP_SUBTITLE = "Rhodes Island Operation Simulation Service"

CSS = """
Screen {
    background: $surface;
    color: $foreground;
}

Header {
    background: $panel;
    color: $text;
}

Footer {
    background: $panel;
}

/* ---- 通用版式 ---- */

/* `height: auto` 是**必需的**，不是顺手写的：Textual 的 `Vertical` 默认
 * `height: 1fr`，也就是"把剩余空间按块数均分"——三块各自被撑高 3 行，中间就出现
 * 空行，内容被推到窗口下沿之外（博士两次报的那两个现象，最底下那一层成因就是这个）。
 * 块要贴着内容长，多余的高度留在最下面，而不是摊进每一块里。 */
.block {
    height: auto;
    border: round $primary;
    padding: 1 2;
    margin: 1 2;
}

/* ---- 矮窗口：装饰让路，内容优先（博士 2026-09-18）----
 *
 * 「做好页面排版，保证终端窗口小的时候也要让玩家看到所有内容」。
 *
 * 一个 `.block` 的固定开销是 6 行（上下边框各 1、上下内边距各 1、上下外边距各 1
 * —— 见上面那条）。三块就是 18 行，加上顶栏、步骤条、底栏，**一屏要 25 行才装得下**；
 * 博士的终端只有 ~20 行，于是内容被挤到窗口外面（他两次报的「只看得见四行标题」
 * 「没有名册那句」都是这一条）。
 *
 * 矮窗口下把块的边框、内边距、外边距全收掉：每块只剩「标签 + 内容」。
 * 这一条是**所有屏共用**的——列表屏也因此能把多出来的行让给表体。
 */
Screen.compact .block {
    border: none;
    padding: 0 2;
    margin: 0 1;
}

Screen.compact .block-title {
    color: $accent;
}

Screen.compact #steps {
    height: 1;
    padding: 0 2;
}

/* 解算日志与结果正文：内容比屏幕长时**可滚动**，滚一下就能看全
 * （不是"截断就没了"）。 */
#log,
#result,
#cands,
#login-status,
#login-accounts {
    overflow-y: auto;
}

.block-title {
    text-style: bold;
    color: $accent;
    padding: 0 1;
}

.muted {
    color: $text-muted;
}

.dim {
    color: $text-disabled;
}

.ok {
    color: $success;
}

.warn {
    color: $warning;
}

.bad {
    color: $error;
}

/* ---- 向导的步骤条 ---- */

#steps {
    height: 2;
    padding: 1 2 0 2;
    color: $text-muted;
}

/* ---- 表格 ---- */

DataTable {
    height: 1fr;
    margin: 0 2;
}

DataTable > .datatable--cursor {
    background: $accent 30%;
}

/* ---- 解算屏 ---- */

#prog {
    margin: 1 2;
}

#log {
    height: 1fr;
    border: round $primary;
    margin: 1 2;
    padding: 0 1;
}

/* ---- 结果屏 ---- */

#result {
    height: 1fr;
    border: round $primary;
    margin: 1 2;
    padding: 1 2;
}

Input {
    margin: 0 2;
}

SelectionList {
    height: 1fr;
    margin: 0 2;
}

#hint {
    height: auto;
    padding: 0 2;
    color: $text-muted;
}
"""

#: 向导的四个步骤，用于画上面的步骤条
STEPS = ("[0] 准备", "[1] 选关卡", "[2] 选编队", "[3] 解算", "[4] 结果")


def step_bar(current: int) -> str:
    """画步骤条。`current` 是 0 起的下标。"""
    out = []
    for i, name in enumerate(STEPS):
        if i < current:
            out.append(f"[dim]{name}[/] ✓")
        elif i == current:
            out.append(f"[bold reverse] {name} [/]")
        else:
            out.append(f"[dim]{name}[/]")
    return "  ·  ".join(out)
