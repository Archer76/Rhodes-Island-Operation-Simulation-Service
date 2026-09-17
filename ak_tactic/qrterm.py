"""把一段文本画成终端里的二维码。

    from ak_tactic.qrterm import render
    print(render("hypergryph://scan_login?scanId=xxx"))

## 为什么不用「亮格画空格」那种常见写法

终端二维码最常见的画法是「暗格画块字符、亮格留空格」，**它只在深色终端上扫得出来**。
浅色终端上亮格是白的、暗格是黑的，极性正好反了，手机扫不到；而且用户在浅色终端里
看到的是一块黑糊糊的东西，不知道哪里出了问题。

所以默认走**显式 ANSI 前景/背景色**：亮格一律 231（白）、暗格一律 16（黑），
与终端主题无关。用半角块 `▀` 一行压两格，高度减半。

两条退路：
- `plain=True`（或 stdout 不是 tty，例如重定向到文件）→ 退回两字符宽的纯文本，
  按「深色背景」的极性画（亮格空格、暗格 `██`），并在返回文本里注明前提；
- 上面两条路都**只改画法，不改矩阵**——矩阵由 `qrcode` 库给，我们不自己编码。

`qrcode` 是项目的第二个外部依赖（BSD），**惰性导入**：不画二维码就不需要它。
"""

from __future__ import annotations

import sys

__all__ = ["render", "render_plain", "matrix", "QRTermError"]

#: 256 色板里的纯黑与纯白。
_BLACK = 16
_WHITE = 231

#: 半角块：**下半格填前景色、上半格显背景色**，故前景取下格、背景取上格。
#:
#: 用的是 U+2584（▄ 下半块）而不是 U+2580（▀ 上半块），这不是风格问题：
#: **U+2580 编码不进 cp936，U+2584 可以**（实测 U+2581–U+258F、U+2593–U+2595
#: 都在 GBK 里，唯独 U+2580 不在）。本机控制台代码页是 GBK，用户没设
#: PYTHONIOENCODING=utf-8 时打印 U+2580 会当场 UnicodeEncodeError。
_LOWER_HALF = "\u2584"


class QRTermError(RuntimeError):
    pass


def matrix(text: str, *, border: int = 2) -> list[list[bool]]:
    """文本 → 二维码矩阵（True 是暗格）。`border` 是静默区，按规范至少 4，
    终端里 2 已经够用（终端本身有行距与边距）。"""
    try:
        import qrcode
    except ImportError as exc:                          # pragma: no cover
        raise QRTermError(
            "画二维码需要 qrcode：pip install qrcode（BSD，纯 Python）") from exc
    qr = qrcode.QRCode(
        error_correction=qrcode.constants.ERROR_CORRECT_M,   # M 级：终端易有摩尔纹
        border=border,
    )
    qr.add_data(text)
    qr.make(fit=True)
    return [[bool(c) for c in row] for row in qr.get_matrix()]


def render(text: str, *, plain: bool = False, border: int = 2) -> str:
    """画成终端二维码。`plain` 或缺 tty 时走纯文本退路。"""
    if plain or not sys.stdout.isatty():
        return render_plain(text, border=border)
    return _render_ansi(matrix(text, border=border))


def _render_ansi(m: list[list[bool]]) -> str:
    out: list[str] = []
    h = len(m)
    for y in range(0, h, 2):
        top = m[y]
        bottom = m[y + 1] if y + 1 < h else [False] * len(top)
        line = []
        for x, t in enumerate(top):
            b = bottom[x]
            # ▄ 画的是下半格 → 前景 = 下格的颜色，背景 = 上格的颜色
            line.append(
                f"\x1b[38;5;{_BLACK if b else _WHITE};"
                f"48;5;{_BLACK if t else _WHITE}m{_LOWER_HALF}")
        line.append("\x1b[0m")
        out.append("".join(line))
    return "\n".join(out)


def render_plain(text: str, *, border: int = 2) -> str:
    """纯文本退路：**假定深色背景**（亮格留空、暗格填块）。

    浅色背景的终端上这个极性是反的，故返回文本的第一行就把前提写出来——
    与其让用户对着一个扫不出的图发愣，不如先说清楚。
    """
    m = matrix(text, border=border)
    body = "\n".join("".join("██" if c else "  " for c in row) for row in m)
    return ("（纯文本二维码：假定深色背景；若你的终端是浅色，请用支持 ANSI 的终端，"
            "或改在图形界面里扫）\n" + body)
