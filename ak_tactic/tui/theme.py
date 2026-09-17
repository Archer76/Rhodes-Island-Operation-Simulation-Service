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

.block {
    border: round $primary;
    padding: 1 2;
    margin: 1 2;
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
    height: 3;
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
