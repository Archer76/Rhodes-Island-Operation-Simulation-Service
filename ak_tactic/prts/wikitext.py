"""wikitext 的模板解析与内联标记还原。

prts.wiki 的干员页面本质上是「一堆模板调用」，而且参数本身又是模板：属性表里写
`{{精英2_满级_攻击}}` 的实参是数字，技能描述里却夹着 `{{color|#0098DC|3}}`。
要把它们变成计算器能吃的数字，需要三件事：

1. 找出顶层 `{{模板名|...}}` 调用（`templates`）；
2. 按**顶层**竖线切分参数，别被 `[[a|b]]` 与嵌套 `{{...}}` 里的竖线骗到（`split_top_level`）；
3. 把内联模板还原成纯文本（`render`）。

第 3 步的规则很朴素却普适：prts.wiki 的展示类模板（color / + / * / 变动数值lite …）
一律把「最后一个位置参数」当作人眼看到的内容。`{{color|#0098DC|3}}` → `3`，
`{{*|6%|+6%}}` → `+6%`，`{{变动数值lite|up|蓝|两名}}` → `两名`。一条规则全救。
"""

from __future__ import annotations

import re
from typing import Iterator

_TAG_RE = re.compile(r"<br\s*/?>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<(?:/?(?:span|div|small|big|b|i|u|s|sub|sup|font|center|poem|"
                         r"section|onlyinclude|includeonly|noinclude|nowiki|ref|ruby|rt|rb)"
                         r"[^>]*?)/?>", re.IGNORECASE)
_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)
_QUOTE_RE = re.compile(r"'{2,5}")
_LINK_RE = re.compile(r"\[\[([^\[\]|]*)\|([^\[\]]*)\]\]")
_PLAIN_LINK_RE = re.compile(r"\[\[([^\[\]]*)\]\]")
_EXT_LINK_RE = re.compile(r"\[(?:https?://\S+)\s+([^\]]+)\]")


# --------------------------------------------------------------------- 扫描

def iter_templates(text: str) -> Iterator[tuple[int, int, str]]:
    """产出所有**顶层** `{{...}}`：`(起点, 终点, 原始片段)`。

    只产出最外层——嵌套的内层模板会作为外层片段的一部分被带出来，
    这正是我们想要的：`{{技能|技能1描述=...{{color|#0098DC|3}}...}}` 整体可见。

    **不变式：`text[start:end] == raw`**，即 `end` 指向闭合 `}}` **之后**一位，
    可以直接拿来做续接游标（`last = end`）。曾经这里 yield 的是闭合 `}}` 的
    **第一个字符**下标（`i`）而不是 `i+2`，与 `raw = text[start:i+2]` 不自洽：
    照 `last = end` 续接的调用方会**每次都多吃一对 `}}`**。
    `resolve_fixes` 就中招了，114 个页面的 `ability_fixed` 全部混进孤立 `}}`。
    """
    stack: list[int] = []
    i, n = 0, len(text)
    while i < n:
        if text.startswith("{{", i):
            stack.append(i)
            i += 2
        elif text.startswith("}}", i):
            if stack:
                start = stack.pop()
                if not stack:
                    yield start, i + 2, text[start:i + 2]
            i += 2
        else:
            i += 1


def template_name(inner: str) -> str:
    """从 `{{...}}` 的内部片段取出模板名。

    必须先剥掉注释——prts.wiki 会在模板名和第一个竖线之间塞一大段
    `<!--下方为自动更新部分，您的修改可能会被覆盖-->`。
    """
    head = _COMMENT_RE.sub("", inner).split("|", 1)[0]
    head = head.split(":", 1)[0] if head.startswith("#") else head
    return head.strip()


def find_templates(text: str, name: str | None = None) -> list[str]:
    """取出所有顶层模板调用的**内部片段**（不含 `{{` `}}`）。

    name 为 None 时返回全部。模板名匹配忽略首尾空白。
    """
    out: list[str] = []
    for _, _, raw in iter_templates(text):
        inner = raw[2:-2]
        if name is None or template_name(inner) == name:
            out.append(inner)
    return out


def split_top_level(text: str, sep: str = "|") -> list[str]:
    """按顶层分隔符切分，跳过 `{{...}}`、`[[...]]`、`{{{...}}}` 内部的同名字符。"""
    parts: list[str] = []
    buf: list[str] = []
    depth_tpl = depth_link = 0
    i, n = 0, len(text)
    while i < n:
        if text.startswith("{{", i):
            depth_tpl += 1
            buf.append("{{")
            i += 2
            continue
        if text.startswith("}}", i):
            depth_tpl = max(0, depth_tpl - 1)
            buf.append("}}")
            i += 2
            continue
        if text.startswith("[[", i):
            depth_link += 1
            buf.append("[[")
            i += 2
            continue
        if text.startswith("]]", i):
            depth_link = max(0, depth_link - 1)
            buf.append("]]")
            i += 2
            continue
        if text[i] == sep and depth_tpl == 0 and depth_link == 0:
            parts.append("".join(buf))
            buf = []
            i += 1
            continue
        buf.append(text[i])
        i += 1
    parts.append("".join(buf))
    return parts


def parse_params(inner: str) -> tuple[str, dict[str, str], list[str]]:
    """解析一个模板调用。

    返回 `(模板名, 命名参数字典, 位置参数列表)`。
    参数值保留原始 wikitext（尚未还原内联模板）。
    """
    segments = split_top_level(inner)
    name = segments[0].strip()
    named: dict[str, str] = {}
    positional: list[str] = []
    for seg in segments[1:]:
        # 只在顶层找第一个 '='：`精英0范围=3-1`
        key, eq, value = _split_first_top_level_eq(seg)
        if eq:
            named[key.strip()] = value
        else:
            positional.append(seg.strip())
    return name, named, positional


def _split_first_top_level_eq(seg: str) -> tuple[str, bool, str]:
    depth_tpl = depth_link = 0
    i, n = 0, len(seg)
    while i < n:
        if seg.startswith("{{", i):
            depth_tpl += 1
            i += 2
            continue
        if seg.startswith("}}", i):
            depth_tpl = max(0, depth_tpl - 1)
            i += 2
            continue
        if seg.startswith("[[", i):
            depth_link += 1
            i += 2
            continue
        if seg.startswith("]]", i):
            depth_link = max(0, depth_link - 1)
            i += 2
            continue
        if seg[i] == "=" and depth_tpl == 0 and depth_link == 0:
            return seg[:i], True, seg[i + 1:]
        i += 1
    return seg, False, ""


# --------------------------------------------------------------------- 还原

def _render_inner_template(inner: str) -> str:
    """把一个内联模板还原成人眼看到的文本。

    规则：有位置参数就取最后一个（prts.wiki 展示模板的通用约定）；
    只有命名参数时，优先 `内容`／`文本`，否则取第一个命名值。
    """
    name, named, positional = parse_params(inner)
    if positional:
        return positional[-1]
    for key in ("内容", "文本", "text"):
        if key in named:
            return named[key]
    if named:
        return next(iter(named.values()))
    return ""


def render(text: str, *, max_passes: int = 12) -> str:
    """把 wikitext 片段还原成纯文本。

    反复展开最内层模板直到没有模板为止（上限 max_passes 防止病态嵌套）。
    """
    if not text:
        return ""
    s = _COMMENT_RE.sub("", text)

    for _ in range(max_passes):
        if "{{" not in s:
            break
        # 找最内层模板：内部不再含 "{{"
        changed = False
        out: list[str] = []
        i, n = 0, len(s)
        while i < n:
            if s.startswith("{{", i):
                end = s.find("}}", i + 2)
                if end == -1:
                    out.append(s[i:])
                    i = n
                    break
                inner = s[i + 2:end]
                if "{{" in inner:
                    # 不是最内层，原样保留，让下一轮处理
                    out.append(s[i:i + 2])
                    i += 2
                    continue
                out.append(_render_inner_template(inner))
                i = end + 2
                changed = True
            else:
                out.append(s[i])
                i += 1
        s = "".join(out)
        if not changed:
            break

    # 链接与标签
    s = _LINK_RE.sub(lambda m: m.group(2), s)
    s = _PLAIN_LINK_RE.sub(lambda m: m.group(1), s)
    s = _EXT_LINK_RE.sub(lambda m: m.group(1), s)
    s = _TAG_RE.sub("\n", s)
    s = _ANY_TAG_RE.sub("", s)
    s = _QUOTE_RE.sub("", s)
    s = s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    return s.strip()


def render_flat(text: str) -> str:
    """还原成单行文本（换行折成空格），适合做字段值。"""
    return re.sub(r"\s*\n\s*", " ", render(text)).strip()


_NUM_RE = re.compile(r"-?\d+(?:\.\d+)?")


def to_number(text: str) -> float | int | None:
    """从一段可能带单位的文本里抠出第一个数字。"""
    s = render_flat(text)
    m = _NUM_RE.search(s.replace(",", ""))
    if not m:
        return None
    v = float(m.group(0))
    return int(v) if v.is_integer() else v


def split_multi(text: str, seps: str = ",，、;；") -> list[str]:
    """按多种分隔符切列表（prts.wiki 用 `;;`、`,`、`、` 混用）。"""
    if not text:
        return []
    tmp = text
    for s in (";;",):
        tmp = tmp.replace(s, "\x00")
    parts: list[str] = []
    for chunk in tmp.split("\x00"):
        buf = chunk
        for sep in seps:
            buf = buf.replace(sep, "\x00")
        parts.extend(p.strip() for p in buf.split("\x00"))
    return [p for p in parts if p]
